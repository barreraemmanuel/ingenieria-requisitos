#!/usr/bin/env python3
"""Memoria local de workspaces creados por la lanzadera. Solo stdlib."""

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import bootstrap

# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = Path(
    os.environ.get(
        "INGENIERIA_REQUISITOS_REGISTRO",
        str(RAIZ / ".ingenieria-requisitos-local" / "registro.json"),
    )
).expanduser().resolve()
FORMATO = 1


@contextlib.contextmanager
def bloqueo_registro():
    """Serializa el ciclo cargar→modificar→guardar entre procesos de esta máquina."""
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    candado = REGISTRO.with_name(REGISTRO.name + ".lock")
    descriptor = os.open(str(candado), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            import fcntl

            # Igual que la rama Windows: sondeo con tope en vez de espera infinita a un
            # candado que puede ser huérfano (ADR-026).
            limite = time.monotonic() + 60
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= limite:
                        raise SystemExit(
                            "No pude obtener el candado del registro en 60 s; "
                            "¿otro proceso lo tiene retenido?"
                        )
                    time.sleep(0.05)
            liberar = lambda: fcntl.flock(descriptor, fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover - rama Windows
            import msvcrt

            inicializar = os.fstat(descriptor).st_size == 0
            os.lseek(descriptor, 0, os.SEEK_SET)
            # LK_LOCK abandona a los ~10 s con EDEADLK; varios procesos registrando a
            # la vez pueden esperar más. Se sondea sin bloquear hasta un límite ancho.
            limite = time.monotonic() + 60
            while True:
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= limite:
                        raise SystemExit(
                            "No pude obtener el candado del registro en 60 s; "
                            "¿otro proceso lo tiene retenido?"
                        )
                    time.sleep(0.05)
                    os.lseek(descriptor, 0, os.SEEK_SET)

            # El byte se escribe solo bajo el candado. Otro proceso puede haberlo
            # creado mientras esperábamos, por lo que se comprueba otra vez.
            if inicializar and os.fstat(descriptor).st_size == 0:
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, b"0")

            def liberar():
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        try:
            yield
        finally:
            liberar()
    finally:
        os.close(descriptor)


def cargar():
    if not REGISTRO.is_file():
        return {"formato": FORMATO, "proyectos": []}
    try:
        datos = json.loads(REGISTRO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit("No puedo leer el registro local: %s" % exc)
    if datos.get("formato") != FORMATO:
        raise SystemExit("El registro es de otra versión de la lanzadera.")
    return datos


def guardar(datos):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=REGISTRO.parent, prefix="registro-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        limite = time.monotonic() + 2
        while True:
            try:
                os.replace(temporal, REGISTRO)
                break
            except OSError as exc:
                if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32):
                    raise
                restante = limite - time.monotonic()
                if restante <= 0:
                    raise
                time.sleep(min(0.05, restante))
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def leer_marca(workspace):
    ruta = workspace / "METODO.json"
    try:
        return json.loads(ruta.read_text(encoding="utf-8")).get("huella", "desconocida")
    except (OSError, ValueError):
        return "anterior-a-las-huellas"


def remoto_meta(workspace):
    """Identidad estable del origin sin usuario, credenciales, query ni fragmento."""
    resultado = subprocess.run(
        ["git", "-C", str(workspace), "remote", "get-url", "origin"],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if resultado.returncode:
        return ""
    valor = resultado.stdout.strip().rstrip("/")
    if not valor:
        return ""
    if "://" in valor:
        partes = urlsplit(valor)
        host = (partes.hostname or "").lower()
        if partes.port:
            host += ":%d" % partes.port
        camino = partes.path.lstrip("/")
        identidad = host + "/" + camino
    elif "@" in valor and ":" in valor.split("@", 1)[1]:
        host, camino = valor.split("@", 1)[1].split(":", 1)
        identidad = host.lower() + "/" + camino.lstrip("/")
    else:
        identidad = "local:" + str(Path(valor).expanduser().resolve())
    return identidad[:-4] if identidad.endswith(".git") else identidad


def registrar(workspace):
    workspace = workspace.expanduser().resolve()
    planos = workspace / "docs/02-flujos/planos/planos.json"
    if not (workspace / "AGENTS.md").is_file() or not planos.is_file():
        raise SystemExit("No parece un workspace generado: %s" % workspace)
    try:
        titulo = json.loads(planos.read_text(encoding="utf-8")).get("titulo", workspace.name)
    except (OSError, ValueError):
        titulo = workspace.name
    remoto = remoto_meta(workspace)
    with bloqueo_registro():
        datos = cargar()
        for previa in datos["proyectos"]:
            ruta_previa = Path(previa.get("ruta", ""))
            identidad_previa = previa.get("remoto_meta") or (
                remoto_meta(ruta_previa) if ruta_previa.is_dir() else ""
            )
            if (
                remoto
                and identidad_previa == remoto
                and ruta_previa.resolve() != workspace
                and ruta_previa.is_dir()
            ):
                raise SystemExit(
                    "El mismo remoto meta ya está registrado en %s; no registro otro clon vivo "
                    "en %s. Elige cuál es canónico y usa 'olvidar' solo sobre la entrada sobrante."
                    % (ruta_previa, workspace)
                )
        entrada = {
            "ruta": str(workspace),
            "titulo": titulo,
            "huella": leer_marca(workspace),
        }
        if remoto:
            entrada["remoto_meta"] = remoto
        datos["proyectos"] = [p for p in datos["proyectos"] if p.get("ruta") != str(workspace)]
        datos["proyectos"].append(entrada)
        datos["proyectos"].sort(key=lambda p: p["ruta"])
        guardar(datos)
    print("Registrado: %s" % workspace)


def olvidar(ruta):
    objetivo = str(Path(ruta).expanduser().resolve())
    with bloqueo_registro():
        datos = cargar()
        quedan = [p for p in datos["proyectos"] if p.get("ruta") != objetivo]
        if len(quedan) == len(datos["proyectos"]):
            raise SystemExit("Proyecto no registrado: %s" % objetivo)
        datos["proyectos"] = quedan
        guardar(datos)
    # Solo se olvida la ENTRADA del registro: el workspace no se toca.
    print("Olvidado: %s (el workspace en disco queda intacto)" % objetivo)


def depurar(aplicar=False):
    """Encuentra entradas cuyo workspace ya no existe; solo escribe con --aplicar."""
    datos = cargar()
    ausentes = [p for p in datos["proyectos"] if not Path(p.get("ruta", "")).is_dir()]
    if not ausentes:
        print("Registro limpio: no hay rutas ausentes.")
        return
    for entrada in ausentes:
        print("[AUSENTE] %s — %s" % (entrada.get("titulo", "sin título"), entrada.get("ruta")))
    if not aplicar:
        print("Dry-run: usa 'depurar --aplicar' para olvidar solo estas entradas; no borra discos.")
        return
    with bloqueo_registro():
        datos = cargar()
        ausentes = [p for p in datos["proyectos"] if not Path(p.get("ruta", "")).is_dir()]
        ausentes_rutas = {p.get("ruta") for p in ausentes}
        datos["proyectos"] = [
            p for p in datos["proyectos"] if p.get("ruta") not in ausentes_rutas
        ]
        guardar(datos)
    print("Olvidadas %d entrada(s) ausentes; ningún workspace fue borrado." % len(ausentes))


def main():
    ap = argparse.ArgumentParser(description="Recuerda los workspaces de este ordenador.")
    sub = ap.add_subparsers(dest="orden", required=True)
    sub.add_parser("listar")
    reg = sub.add_parser("registrar")
    reg.add_argument("ruta")
    reg.add_argument("--generado", action="store_true", help=argparse.SUPPRESS)
    olv = sub.add_parser(
        "olvidar",
        help="borra una entrada del registro (no toca el workspace en disco)",
    )
    olv.add_argument("ruta")
    dep = sub.add_parser(
        "depurar",
        help="lista rutas ausentes; --aplicar solo las olvida del registro",
    )
    dep.add_argument("--aplicar", action="store_true")
    contexto = sub.add_parser("contexto", help="datos para el playbook de actualización")
    grupo = contexto.add_mutually_exclusive_group(required=True)
    grupo.add_argument("ruta", nargs="?")
    grupo.add_argument("--todos", action="store_true")
    args = ap.parse_args()

    if args.orden == "registrar":
        registrar(Path(args.ruta))
        return
    if args.orden == "olvidar":
        olvidar(args.ruta)
        return
    if args.orden == "depurar":
        depurar(args.aplicar)
        return
    datos = cargar()
    proyectos = datos["proyectos"]
    if args.orden == "listar":
        if not proyectos:
            print("No hay proyectos registrados.")
        for p in proyectos:
            estado = "OK" if Path(p["ruta"]).is_dir() else "NO ENCONTRADO"
            print("[%s] %s — %s" % (estado, p["titulo"], p["ruta"]))
        return
    if not args.todos:
        objetivo = str(Path(args.ruta).expanduser().resolve())
        proyectos = [p for p in proyectos if p.get("ruta") == objetivo]
        if not proyectos:
            raise SystemExit("Proyecto no registrado: %s" % objetivo)
    print(json.dumps({
        "huella_actual": bootstrap.huella_plantilla(),
        "proyectos": proyectos,
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
