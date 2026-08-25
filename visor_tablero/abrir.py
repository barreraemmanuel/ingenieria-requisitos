#!/usr/bin/env python3
"""Inicia o reutiliza la sesión local del tablero de control.

Mismo patrón que `visor_presentaciones/abrir.py`: el puerto sale del propio
workspace, así que dos llamadas seguidas sobre el mismo meta-repo caen en el
mismo servidor en vez de levantar un segundo tablero. Si el puerto lo ocupa
otra cosa, se dice y no se toca nada.

    python3 visor_tablero/abrir.py --workspace <ruta del meta-repo>
"""

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

try:
    from .servir import SERVICIO, huella_workspace
except ImportError:  # También funciona como `python3 visor_tablero/abrir.py`.
    from servir import SERVICIO, huella_workspace


BASE = Path(__file__).resolve().parent
PUERTO_BASE = 8768


@dataclass
class Resultado:
    url: str
    proceso: object = None


def argumentos_prueba(puerto=0, seccion=None):
    return argparse.Namespace(puerto=puerto, seccion=seccion, sin_navegador=True)


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexion:
        conexion.bind(("127.0.0.1", 0))
        return conexion.getsockname()[1]


def _puerto_determinista(workspace):
    return PUERTO_BASE + (int(huella_workspace(workspace)[:8], 16) % 1000)


def _meta(puerto):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/meta.json" % puerto, timeout=0.5
        ) as respuesta:
            return json.loads(respuesta.read())
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _url(puerto, seccion):
    return "http://127.0.0.1:%d/%s" % (puerto, "#" + seccion if seccion else "")


def abrir(workspace, args):
    workspace = Path(workspace).expanduser().resolve()
    if not (workspace / "docs" / "05-trabajo").is_dir():
        raise ValueError("no parece un meta-repo (falta docs/05-trabajo/): %s"
                         % workspace)
    puerto = getattr(args, "puerto", None)
    if puerto is None:
        puerto = _puerto_determinista(workspace)
    elif puerto == 0:
        puerto = _puerto_libre()
        # Permite que dos llamadas programáticas con los mismos argumentos
        # reutilicen también un puerto inicialmente efímero.
        args.puerto = puerto

    identidad = {"servicio": SERVICIO,
                 "huella_workspace": huella_workspace(workspace)}
    meta = _meta(puerto)
    if meta == identidad:
        url = _url(puerto, getattr(args, "seccion", None))
        if not getattr(args, "sin_navegador", False):
            webbrowser.open(url)
        return Resultado(url)
    if meta is not None:
        raise ValueError("el puerto %d ya lo usa otra sesión" % puerto)

    registro = workspace / ".runtime" / ("tablero-%d.log" % puerto)
    registro.parent.mkdir(parents=True, exist_ok=True)
    comando = [sys.executable, str(BASE / "servir.py"),
               "--workspace", str(workspace), "--puerto", str(puerto),
               "--sin-navegador"]
    with registro.open("ab") as salida:
        proceso = subprocess.Popen(
            comando, stdin=subprocess.DEVNULL, stdout=salida,
            stderr=subprocess.STDOUT, start_new_session=True,
        )

    for _ in range(50):
        if _meta(puerto) == identidad:
            url = _url(puerto, getattr(args, "seccion", None))
            if not getattr(args, "sin_navegador", False):
                webbrowser.open(url)
            return Resultado(url, proceso)
        if proceso.poll() is not None:
            break
        time.sleep(0.1)
    detener(proceso)
    raise RuntimeError("el tablero no llegó a arrancar; mira %s" % registro)


def detener(proceso):
    if proceso is None or proceso.poll() is not None:
        return
    proceso.terminate()
    try:
        proceso.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proceso.kill()
        proceso.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser(description="Abre el tablero de control local")
    parser.add_argument("--workspace", required=True,
                        help="Ruta del meta-repo (el que tiene docs/05-trabajo/)")
    parser.add_argument("--seccion", choices=["ahora", "te-toca", "por-hacer",
                                              "historial", "documentacion"])
    parser.add_argument("--puerto", type=int)
    parser.add_argument("--sin-navegador", action="store_true")
    args = parser.parse_args()
    try:
        print(abrir(args.workspace, args).url)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print("ERROR: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
