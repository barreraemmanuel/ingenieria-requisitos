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
import sys
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

# Bug 077: desde que este módulo tiene línea de órdenes (`desbloquear`) también IMPRIME, y
# en Windows una salida redirigida a un pipe pasa a cp1252: un `ñ` o un `·` matarían el
# comando de recuperación justo cuando alguien lo necesita.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

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

    Un PID que no es un entero positivo es "no vive", y se filtra ANTES de tocar el
    sistema: `os.kill(-1, 0)` no pregunta por un proceso, se dirige a TODOS los del
    usuario (bug 077, al sondear el lanzador de un recibo sin ese campo).
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid < 1:
        return False
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

    def inspeccionar(self, scope):
        """(registro, ¿el dueño sigue vivo?) para `scope`, SIN retirar nada.

        Bug 077 · R2: `_active_records` retira los leases de dueño muerto por el camino,
        que es lo correcto para adquirir pero lo peor posible para DIAGNOSTICAR — quien
        quiere saber si quedó un lanzamiento a medias necesita ver el lease huérfano, no
        que desaparezca al mirarlo. Devuelve None si no hay lease; el segundo elemento es
        el mismo tri-estado de `_owner_alive`: True vivo, False muerto, None "no lo sé"
        (host remoto o marcador de arranque indeterminable), que se trata como vivo."""
        with self._coordinator():
            record = self._read(self._path(scope))
        if record is None:
            return None
        return record, self._owner_alive(record.get("owner", {}))

    def retirar_huerfano(self, scope):
        """Retira el lease de `scope` SOLO si su dueño ya no vive. Devuelve el registro
        retirado, o None si no había lease.

        Nunca se le roba un lease a un dueño vivo (P-20260818-3ad156c4): con el dueño
        vivo —o simplemente no comprobable— esto levanta `LeaseBusy`."""
        with self._coordinator():
            path = self._path(scope)
            record = self._read(path)
            if record is None:
                return None
            if self._owner_alive(record.get("owner", {})) is not False:
                owner = record.get("owner", {})
                raise LeaseBusy(
                    f"el lease {scope} tiene dueño VIVO (sesión "
                    f"{owner.get('session_id', '?')} en {owner.get('host', '?')}, PID "
                    f"{owner.get('pid', '?')}): no se retira. SALIDA: comprueba ese "
                    f"proceso (`ps -p {owner.get('pid', '?')}` en POSIX, "
                    f"`tasklist /FI \"PID eq {owner.get('pid', '?')}\"` en Windows) y, "
                    f"cuando ya no exista, repite `lease.py desbloquear`."
                )
            self._unlink_durable(path)
            return record

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


# --- Recuperación de un lanzamiento interrumpido (bug 077 · R2) -----------------------
#
# `ejecucion.py` limpia solo cuando le llega una señal. `kill -9`, el cierre brusco de la
# terminal o un cuelgue del sistema no dan esa oportunidad: lo que queda es un lease a
# nombre de un PID muerto, un harness huérfano que puede seguir escribiendo en el worktree
# y la ficha de la unidad congelada en 0444. Esto es el comando que lo deshace, y vive
# aquí porque el lease es el rastro que SIEMPRE queda; lo demás (qué hijo, qué ficha) lo
# dice el recibo del lanzamiento, que es un artefacto documentado del método.
#
# La regla que no se toca: NUNCA se le quita el lease a un dueño vivo.


def _recibos_pendientes(workspace, unidad):
    """Recibos de `unidad` que nunca llegaron a cerrarse (sin `exit_code`)."""
    carpeta = Path(workspace) / ".runtime/ejecuciones"
    pendientes = []
    if not carpeta.is_dir():
        return pendientes
    for ruta in sorted(carpeta.glob(f"{unidad}-*.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(datos, dict) or datos.get("exit_code") is not None:
            continue
        if datos.get("resultado") in ("interrumpido", "recuperado"):
            continue
        pendientes.append((ruta, datos))
    return pendientes


def _rematar_harness(info):
    """Termina el harness huérfano descrito por el recibo. Devuelve qué se hizo."""
    if not isinstance(info, dict) or not isinstance(info.get("pid"), int):
        return "el recibo no anotó ningún proceso de harness"
    pid = info["pid"]
    if not _pid_vivo(pid):
        return f"el harness (PID {pid}) ya no estaba vivo"
    esperado = info.get("process_started")
    actual = process_start_marker(pid)
    if esperado and actual != "desconocido" and actual != esperado:
        # Fail-closed contra la reutilización de PID: ese número lo ocupa ahora otro
        # proceso, que no tiene nada que ver con el lanzamiento interrumpido.
        return f"el PID {pid} lo ocupa ahora otro proceso: no se toca"
    if os.name == "nt":  # pragma: no cover - rama Windows, la ejercita su CI
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True
        )
        return f"taskkill /T /F sobre el harness (PID {pid})"
    import signal as senales

    grupo = info.get("pgid")
    if not isinstance(grupo, int):
        try:
            grupo = os.getpgid(pid)
        except OSError:
            grupo = None

    def golpear(numero):
        try:
            if grupo is not None and grupo != os.getpgrp():
                os.killpg(grupo, numero)
            else:
                os.kill(pid, numero)
        except OSError:
            return

    golpear(senales.SIGTERM)
    limite = time.monotonic() + 5
    while _pid_vivo(pid) and time.monotonic() < limite:
        time.sleep(0.05)
    if not _pid_vivo(pid):
        return f"harness huérfano (PID {pid}) terminado con SIGTERM"
    golpear(senales.SIGKILL)
    limite = time.monotonic() + 5
    while _pid_vivo(pid) and time.monotonic() < limite:
        time.sleep(0.05)
    return f"harness huérfano (PID {pid}) terminado con SIGKILL"


def _descongelar_ficha(info):
    """Devuelve la escritura a la ficha que el lanzamiento dejó en 0444."""
    if not isinstance(info, dict) or not info.get("ruta"):
        return "el recibo no dejó ninguna ficha congelada"
    ruta = Path(info["ruta"])
    modo = info.get("modo_previo")
    destino = (modo | 0o200) if isinstance(modo, int) else 0o644
    try:
        ruta.chmod(destino)
    except OSError as exc:
        return f"no pude devolver la escritura a {ruta}: {exc}"
    return f"{ruta} devuelta a {oct(destino)}"


def desbloquear(workspace, unidad):
    """Retira lo que dejó un lanzamiento interrumpido de `unidad`. Devuelve las líneas
    de lo que ha hecho; levanta `LeaseBusy` si el dueño sigue vivo."""
    workspace = Path(workspace).resolve()
    manager = LeaseManager(workspace)
    pendientes = _recibos_pendientes(workspace, unidad)
    scopes = [f"unit:{unidad}"]
    for _, recibo in pendientes:
        for scope in (recibo.get("lease") or {}).get("fencing") or {}:
            if isinstance(scope, str) and scope not in scopes:
                scopes.append(scope)

    # Antes de tocar NADA: si alguno de esos leases tiene dueño vivo, aquí no hay ningún
    # huérfano que recuperar — hay un lanzamiento en marcha. Se comprueba primero, porque
    # matar al harness y luego descubrirlo sería exactamente el robo que esto prohíbe.
    for scope in scopes:
        hallado = manager.inspeccionar(scope)
        if hallado is not None and hallado[1] is not False:
            owner = hallado[0].get("owner", {})
            raise LeaseBusy(
                f"el lease {scope} tiene dueño VIVO (sesión "
                f"{owner.get('session_id', '?')} en {owner.get('host', '?')}, PID "
                f"{owner.get('pid', '?')}): no hay nada interrumpido que recuperar. "
                f"SALIDA: comprueba ese proceso (`ps -p {owner.get('pid', '?')}` en POSIX, "
                f"`tasklist /FI \"PID eq {owner.get('pid', '?')}\"` en Windows) y, cuando "
                f"ya no exista, repite `lease.py desbloquear {unidad}`."
            )
    # Un recibo cuyo lanzador SIGUE VIVO tampoco se toca: puede ser otra unidad del mismo
    # taller corriendo sin lease sobre este scope.
    pendientes = [
        (ruta, recibo) for ruta, recibo in pendientes
        if not _pid_vivo((recibo.get("lanzador") or {}).get("pid", -1))
    ]

    hecho = []
    # 1) el hijo primero: mientras siga vivo puede escribir en el worktree de la unidad,
    #    y soltar la autoridad antes que él dejaría entrar a un segundo lanzamiento con
    #    el primero todavía tecleando. Mismo orden que R1.
    for ruta, recibo in pendientes:
        hecho.append(_rematar_harness(recibo.get("harness_proceso")))
    # 2) los leases: solo los huérfanos, y solo tras comprobar que el dueño no vive.
    for scope in scopes:
        registro = manager.retirar_huerfano(scope)
        if registro is not None:
            hecho.append(f"lease {scope} retirado (dueño muerto)")
    # 3) la ficha, lo último: es lo que devuelve la unidad a estado trabajable.
    for ruta, recibo in pendientes:
        hecho.append(_descongelar_ficha(recibo.get("ficha_bloqueada")))
        recibo["resultado"] = "recuperado"
        recibo.setdefault("checkpoints", []).append({
            "nombre": "recuperado",
            "estado": "fail",
            "detalle": f"lanzamiento interrumpido, recuperado por `lease.py desbloquear {unidad}`",
        })
        with contextlib.suppress(OSError, TypeError, ValueError):
            _write_json_atomic(ruta, recibo)
        hecho.append(f"recibo {ruta.name} marcado como recuperado")
    if not pendientes and len(hecho) == 0:
        hecho.append(f"no había nada interrumpido en {unidad}")
    return hecho


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Autoridad local de leases del método.")
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser(
        "desbloquear",
        help="retira lo que dejó un lanzamiento interrumpido de una unidad: harness "
             "huérfano, leases de dueño muerto y ficha en solo lectura",
    )
    p.add_argument("unidad")
    p.add_argument(
        "--workspace", default=str(Path(__file__).resolve().parents[3]),
        help="raíz del workspace (por defecto, la que cuelga de este script)",
    )
    args = parser.parse_args(argv)
    try:
        for linea in desbloquear(args.workspace, args.unidad):
            print(linea)
    except LeaseError as exc:
        print(
            f"lease: FAIL {exc}\n"
            f"  Reintento, cuando el dueño ya no exista: "
            f"python3 {Path(__file__)} desbloquear {args.unidad}",
            file=sys.stderr,
        )
        return 3
    print(
        f"lease: {args.unidad} vuelve a estar libre. Sigue con: "
        f"python3 {Path(__file__).with_name('ejecucion.py')} lanzar {args.unidad} "
        f"--harness … --prompt …"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
