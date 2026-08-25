#!/usr/bin/env python3
"""Autoridad local para operaciones que comparten un workspace.

Los leases viven fuera de git en ``.runtime/leases``. La creación y el
fencing se serializan con un lock del sistema operativo; un proceso muerto no
puede dejar ese lock interno ocupado. Los registros de autoridad sí son
durables y llevan identidad suficiente para distinguir un PID reutilizado.

Esta capa coordina procesos que ven el MISMO filesystem. Un hostname distinto
se considera propietario remoto vivo: nunca se rompe automáticamente ni se
finge coordinación entre clones distintos.
"""

import contextlib
import datetime
import hashlib
import hmac
import json
import os
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import workspace_paths

try:
    import fcntl
except ImportError:  # pragma: no cover - en Windows el candado lo da msvcrt
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

# Tope de espera al candado del coordinador, en las DOS plataformas: esperar sin límite a
# un candado huérfano dejaba a todas las sesiones colgadas en silencio (ADR-026). Los
# tests lo bajan por entorno para no pagar el minuto entero.
TOPE_COORDINADOR_SEGUNDOS = int(os.environ.get("IR_TOPE_COORDINADOR_SEGUNDOS", "60"))


class LeaseError(RuntimeError):
    pass


class LeaseBusy(LeaseError):
    pass


class LeaseLost(LeaseError):
    pass


def ahora():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _pid_vivo(pid):
    """True si existe un proceso local con ese PID.

    En Windows NO vale os.kill(pid, 0): allí cualquier señal que no sea de
    consola TERMINA el proceso vía TerminateProcess en vez de sondearlo.
    (Duplicado de control_plane.pid_vivo: este módulo se carga standalone.)
    """
    if os.name == "nt":  # pragma: no cover - rama Windows, la ejercita su CI
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_ACCESS_DENIED = 5
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            codigo = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(codigo)):
                return codigo.value == STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _marca_arranque_windows(pid):  # pragma: no cover - rama Windows, la ejercita su CI
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        # GetProcessTimes rellena cuatro FILETIME de 8 bytes: creación, salida,
        # kernel y usuario. Solo interesa la creación.
        tiempos = (ctypes.c_ulonglong * 4)()
        if kernel32.GetProcessTimes(
            handle,
            ctypes.byref(tiempos, 0),
            ctypes.byref(tiempos, 8),
            ctypes.byref(tiempos, 16),
            ctypes.byref(tiempos, 24),
        ):
            return f"win:{tiempos[0]}"
        return ""
    finally:
        kernel32.CloseHandle(handle)


def process_start_marker(pid):
    """Identidad estable de una encarnación de PID, no solo su número."""
    if os.name == "nt":  # pragma: no cover - rama Windows, la ejercita su CI
        return _marca_arranque_windows(pid) or "desconocido"
    proc = Path("/proc") / str(pid) / "stat"
    try:
        campos = proc.read_text(encoding="utf-8").split()
        if len(campos) > 21:
            return f"proc:{campos[21]}"
    except OSError:
        pass
    try:
        salida = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout.strip()
    except OSError:
        salida = ""
    return f"ps:{salida}" if salida else "desconocido"


def session_id_default():
    for clave in ("IR_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID"):
        valor = os.environ.get(clave, "").strip()
        if valor:
            return valor
    return str(uuid.uuid4())


def _scope_key(scope):
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _fsync_directory(path):
    """Hace durable un replace/unlink, no solo los bytes del fichero."""
    if os.name == "nt":  # pragma: no cover - Windows no deja abrir directorios
        # con os.open (PermissionError); NTFS journalea los metadatos y no
        # ofrece fsync de directorio, así que no hay versión durable posible.
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(str(path), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporal, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def failpoint(name):
    """Barrera determinista de tests: notifica por un FD y espera por otro.

    En Windows los FDs no cruzan procesos (no hay pass_fds), así que existe la
    variante por ficheros: *_READY_FILE se toca al llegar y *_WAIT_FILE se
    espera hasta que exista. Misma semántica, transporte portable."""
    prefix = f"IR_FAILPOINT_{name.upper()}"
    ready = os.environ.get(f"{prefix}_READY_FD")
    wait = os.environ.get(f"{prefix}_WAIT_FD")
    if ready:
        os.write(int(ready), b"1")
    if wait:
        os.read(int(wait), 1)
    ready_file = os.environ.get(f"{prefix}_READY_FILE")
    wait_file = os.environ.get(f"{prefix}_WAIT_FILE")
    if ready_file:
        with open(ready_file, "w", encoding="ascii") as stream:
            stream.write("1")
    if wait_file:
        # Tope de seguridad: la variante por FDs se desbloquea sola si el otro
        # extremo muere; la de ficheros no lo detecta, así que un test colgado (o
        # una env var olvidada en una shell de producción) no cuelga para siempre.
        limite = time.monotonic() + 300
        while not os.path.exists(wait_file):
            if time.monotonic() >= limite:
                raise RuntimeError(
                    f"failpoint {name}: la barrera {wait_file} no se abrió en 300 s"
                )
            time.sleep(0.01)


class LeaseGroup:
    def __init__(self, manager, records):
        self.manager = manager
        self.records = records
        self.tokens = {record["scope"]: record["fencing"] for record in records}

    def assert_owner(self):
        self.manager._assert_records(self.records)

    def release(self):
        self.manager._release_records(self.records)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


class LeaseManager:
    def __init__(
        self,
        workspace,
        *,
        session_id=None,
        host=None,
        pid=None,
        process_started=None,
    ):
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".runtime/leases"
        self.active = self.root / "active"
        self.fencing = self.root / "fencing"
        self.session_id = session_id or session_id_default()
        self.host = host or socket.gethostname()
        self.pid = int(pid if pid is not None else os.getpid())
        self.process_started = (
            process_started
            if process_started is not None
            else process_start_marker(self.pid)
        )

    @contextlib.contextmanager
    def _coordinator(self):
        self._ensure_directory(self.root, "raíz de leases")
        lock_path = self.root / "coordinator.lock"
        descriptor = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            tope = TOPE_COORDINADOR_SEGUNDOS
            if fcntl is not None:
                # Mismo contrato que la rama Windows de abajo: se sondea con tope y se
                # traduce a LeaseBusy. El flock bloqueante sin límite dejaba a TODAS las
                # sesiones POSIX esperando para siempre a un candado huérfano — el arreglo
                # de 1.1.1/1.2.0 solo había llegado a Windows (ADR-026).
                limite = time.monotonic() + tope
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        if time.monotonic() >= limite:
                            raise LeaseBusy(
                                f"el coordinador de leases sigue ocupado tras {tope} s; "
                                "¿otra sesión retiene el candado?"
                            )
                        time.sleep(0.05)
                liberar = lambda: fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif msvcrt is not None:
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                # LK_LOCK abandona a los ~10 s con EDEADLK y el OSError no es LeaseError:
                # ningún llamador lo captura. Se sondea sin bloquear hasta un límite ancho
                # y, si no entra, se traduce a LeaseBusy como en el resto del control plane.
                limite = time.monotonic() + tope
                while True:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    try:
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= limite:
                            raise LeaseBusy(
                                f"el coordinador de leases sigue ocupado tras {tope} s; "
                                "¿otra sesión retiene el candado?"
                            )
                        time.sleep(0.05)

                def liberar():
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                raise LeaseError(
                    "los leases locales requieren un lock exclusivo del sistema "
                    "(flock o msvcrt.locking); este sistema no ofrece ninguno y la "
                    "operación concurrente se bloquea por seguridad"
                )
            try:
                yield
            finally:
                liberar()
        finally:
            os.close(descriptor)

    def _path(self, scope):
        return self.active / f"{_scope_key(scope)}.json"

    def _confinar(self, path, label):
        """Los DOS controles de la unidad 043, no uno.

        1) `es_enlace` y no `is_symlink`: en Windows un junction (mklink /J, SIN
           privilegio) redirige igual y es invisible para is_symlink(). Se comprobó
           explotable: con .runtime/leases/active como junction, el lease se escribía
           FUERA del workspace.
        2) el contraste de la ruta REAL contra la raíz del workspace, el mismo que
           hace `workspace_paths.confined_path`. Hace falta porque el control (1) solo
           mira la HOJA que se le pasa —.runtime/leases, active, fencing— y nunca el
           tramo `.runtime`: con el enlace ahí, `mkdir(parents=True)` lo atravesaba y
           la escritura salía del workspace igual. `confined_path` recorre TODOS los
           tramos y además comprueba que la ruta resuelta cuelgue de la raíz.
        """
        if workspace_paths.es_enlace(path):
            raise LeaseError(f"{label} no puede ser un enlace (symlink o junction)")
        try:
            workspace_paths.confined_path(self.workspace, path, label=label)
        except workspace_paths.WorkspacePathError as exc:
            raise LeaseError(f"{label} no queda dentro del workspace: {exc}") from exc

    def _ensure_directory(self, path, label):
        self._confinar(path, label)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LeaseError(f"{label} ilegible: {exc}") from exc
        # Otra vez después del mkdir: entre comprobar y crear, alguien ha podido
        # sustituir el directorio por un enlace.
        self._confinar(path, label)
        if not path.is_dir():
            raise LeaseError(f"{label} no es un directorio regular")

    @staticmethod
    def _record_integrity(record):
        payload = {key: value for key, value in record.items() if key != "integrity"}
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _validate_record(self, path, record):
        expected_keys = {
            "format", "scope", "operation", "fencing", "created", "owner", "integrity"
        }
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise LeaseError(f"lease corrupto {path.name}: schema inválido")
        scope = record.get("scope")
        if (not isinstance(scope, str) or not scope or scope != scope.strip()
                or any(ord(character) < 32 for character in scope)):
            raise LeaseError(f"lease corrupto {path.name}: scope inválido")
        if path.name != f"{_scope_key(scope)}.json":
            raise LeaseError(f"lease corrupto {path.name}: hash de scope incoherente")
        owner = record.get("owner")
        owner_keys = {"session_id", "host", "pid", "process_started"}
        if (
            record.get("format") != 1
            or type(record.get("fencing")) is not int
            or record["fencing"] < 1
            or not isinstance(record.get("operation"), str)
            or not isinstance(record.get("created"), str)
            or not isinstance(owner, dict)
            or set(owner) != owner_keys
            or type(owner.get("pid")) is not int
            or owner["pid"] < 1
            or any(
                not isinstance(owner.get(key), str) or not owner[key].strip()
                for key in ("session_id", "host", "process_started")
            )
        ):
            raise LeaseError(f"lease corrupto {path.name}: schema/owner inválido")
        try:
            uuid.UUID(record["operation"])
            datetime.datetime.fromisoformat(record["created"])
        except (ValueError, TypeError) as exc:
            raise LeaseError(f"lease corrupto {path.name}: identidad/fecha inválida") from exc
        integrity = record.get("integrity")
        if (
            not isinstance(integrity, str)
            or len(integrity) != 64
            or not hmac.compare_digest(integrity, self._record_integrity(record))
        ):
            raise LeaseError(f"lease corrupto {path.name}: integridad inválida")
        return record

    def _read(self, path):
        if path.is_symlink():
            raise LeaseError(f"lease corrupto {path.name}: symlink no permitido")
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LeaseError(f"lease ilegible {path.name}: {exc}") from exc
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LeaseError(f"lease corrupto {path.name}: JSON inválido") from exc
        return self._validate_record(path, record)

    @staticmethod
    def _unlink_durable(path):
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)

    def _owner_alive(self, owner):
        if owner.get("host") != self.host:
            return None
        pid = owner.get("pid")
        if not isinstance(pid, int):
            return False
        if not _pid_vivo(pid):
            return False
        marcador_actual = process_start_marker(pid)
        if marcador_actual == "desconocido":
            # R1 (adversarial 12-08, hallazgo 8): un marcador de arranque indeterminable
            # con el PID vivo es "no lo sé", nunca "está muerto". Antes esto comparaba
            # "desconocido" contra el marcador guardado, daba False y robaba el lease de un
            # dueño VIVO. Fail-closed: se trata como vivo (None), igual que el host remoto.
            return None
        return marcador_actual == owner.get("process_started")

    def _active_records(self):
        self._ensure_directory(self.active, "raíz active de leases")
        records = []
        for path in self.active.glob("*.json"):
            record = self._read(path)
            if not record:
                continue
            alive = self._owner_alive(record.get("owner", {}))
            if alive is False:
                self._unlink_durable(path)
                continue
            records.append(record)
        return records

    @staticmethod
    def _conflict(first, second):
        return first == second or first == "workspace" or second == "workspace"

    def _next_fencing(self, scope):
        self._ensure_directory(self.fencing, "raíz fencing de leases")
        path = self.fencing / f"{_scope_key(scope)}.counter"
        if path.is_symlink():
            raise LeaseError(f"contador de fencing corrupto para {scope}: symlink")
        if path.exists():
            try:
                raw = path.read_text(encoding="ascii").strip()
                current = int(raw)
            except (OSError, ValueError) as exc:
                raise LeaseError(f"contador de fencing corrupto para {scope}") from exc
            if current < 1 or raw != str(current):
                raise LeaseError(f"contador de fencing corrupto para {scope}")
        else:
            current = 0
        following = current + 1
        descriptor, temporal = tempfile.mkstemp(prefix=".counter.", dir=str(path.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(f"{following}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporal, path)
            _fsync_directory(path.parent)
        finally:
            if os.path.exists(temporal):
                os.unlink(temporal)
        return following

    def acquire(self, scopes):
        if isinstance(scopes, str):
            requested = [scopes]
        else:
            requested = list(dict.fromkeys(scopes))
        if not requested or any(
            not isinstance(scope, str)
            or not scope.strip()
            or scope != scope.strip()
            or any(ord(character) < 32 for character in scope)
            for scope in requested
        ):
            raise LeaseError("se necesita al menos un scope de lease no vacío")
        with self._coordinator():
            active = self._active_records()
            for existing in active:
                for wanted in requested:
                    if self._conflict(existing["scope"], wanted):
                        owner = existing.get("owner", {})
                        ruta_lease = self._path(existing["scope"])
                        # R1: el aspirante necesita PID, ruta del lease y el comando de
                        # desbloqueo manual — el lease NO se roba solo porque el marcador de
                        # arranque sea indeterminable; esto es lo que le dice a un humano
                        # cómo destrabarlo él mismo tras comprobar el dueño (mismo criterio
                        # auditable que `peticion.py desbloquear`, adaptado a leases: nunca
                        # automático, siempre tras comprobar que el proceso ya no existe).
                        raise LeaseBusy(
                            f"scope {wanted} ocupado por sesión "
                            f"{owner.get('session_id', '?')} en {owner.get('host', '?')} "
                            f"(PID {owner.get('pid', '?')}); lease: {ruta_lease}. Si "
                            f"compruebas que ese PID ya no está vivo, desbloquéalo a mano "
                            f"borrando ese fichero (mismo criterio auditable que "
                            f"`peticion.py desbloquear`: primero comprueba el dueño, luego "
                            f"retira el lock — nunca automático)."
                        )
            operation = str(uuid.uuid4())
            records = []
            owner = {
                "session_id": self.session_id,
                "host": self.host,
                "pid": self.pid,
                "process_started": self.process_started,
            }
            try:
                for scope in requested:
                    record = {
                        "format": 1,
                        "scope": scope,
                        "operation": operation,
                        "fencing": self._next_fencing(scope),
                        "created": ahora(),
                        "owner": owner,
                    }
                    record["integrity"] = self._record_integrity(record)
                    self._validate_record(self._path(scope), record)
                    # Se añade antes de publicar: si replace ya ocurrió pero falló el fsync,
                    # el rollback todavía conoce exactamente qué registro puede retirar.
                    records.append(record)
                    _write_json_atomic(self._path(scope), record)
            except Exception:
                for published in reversed(records):
                    path = self._path(published["scope"])
                    try:
                        current = self._read(path)
                    except LeaseError:
                        continue
                    if self._same_record(current, published):
                        self._unlink_durable(path)
                raise
            return LeaseGroup(self, records)

    @staticmethod
    def _same_record(current, expected):
        return bool(
            current
            and current.get("scope") == expected.get("scope")
            and current.get("fencing") == expected.get("fencing")
            and current.get("operation") == expected.get("operation")
            and current.get("owner") == expected.get("owner")
            and current.get("integrity") == expected.get("integrity")
        )

    def _assert_records(self, records):
        with self._coordinator():
            for expected in records:
                if not self._same_record(self._read(self._path(expected["scope"])), expected):
                    raise LeaseLost(
                        f"autoridad perdida para {expected['scope']} "
                        f"(fencing {expected['fencing']})"
                    )

    def _release_records(self, records):
        with self._coordinator():
            for expected in records:
                path = self._path(expected["scope"])
                if self._same_record(self._read(path), expected):
                    self._unlink_durable(path)
