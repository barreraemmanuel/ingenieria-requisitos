#!/usr/bin/env python3
"""Inicia o reutiliza una sesión local de presentaciones."""

import argparse
import json
import os
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
    from .servir import huella_datos
except ImportError:  # También funciona como `python3 visor_presentaciones/abrir.py`.
    from servir import huella_datos


BASE = Path(__file__).resolve().parent


@dataclass
class Resultado:
    url: str
    proceso: object = None
    navegador: bool = False


# Bug 057: pedir un OK dejó de depender de que el agente se acordara de abrir la web. El
# "¿hay dónde abrirla?" se decide AQUÍ, en un solo sitio, y no en cada llamador.
def hay_pantalla():
    """¿Tiene esta sesión un navegador que abrir?

    `IR_SIN_NAVEGADOR` es la declaración explícita de quien lanza —un agente en batch, la
    CI, una sesión por SSH— y manda sobre todo lo demás. `BROWSER` es la contraria: si
    alguien ha dicho CON QUÉ abrir, hay con qué. Sin ninguna de las dos se mira el
    escritorio: en Linux/BSD sin `DISPLAY` ni `WAYLAND_DISPLAY` no hay ventana donde
    pintar; macOS y Windows siempre la tienen.
    """
    if os.environ.get("IR_SIN_NAVEGADOR", "").strip():
        return False
    if os.environ.get("BROWSER", "").strip():
        return True
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def abrir_navegador(url, args):
    """Abre `url` salvo que lo prohíba `--sin-navegador` o que no haya pantalla.
    Devuelve si de verdad se abrió: quien llama tiene que poder DECIRLO."""
    if getattr(args, "sin_navegador", False) or not hay_pantalla():
        return False
    webbrowser.open(url)
    return True


def argumentos_prueba(puerto=0, presentacion=None, workspace=None):
    return argparse.Namespace(
        puerto=puerto, presentacion=presentacion, sin_navegador=True,
        workspace=workspace,
    )


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexion:
        conexion.bind(("127.0.0.1", 0))
        return conexion.getsockname()[1]


def _puerto_determinista(datos):
    huella = huella_datos(datos)
    return 8767 + (int(huella[:8], 16) % 1000)


def _meta(puerto):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/meta.json" % puerto, timeout=0.5
        ) as respuesta:
            return json.loads(respuesta.read())
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _url(puerto, presentacion):
    sufijo = "/presentacion/%s" % presentacion if presentacion else "/"
    return "http://127.0.0.1:%d%s" % (puerto, sufijo)


def abrir(datos, args):
    datos = Path(datos).expanduser().resolve()
    puerto = getattr(args, "puerto", None)
    if puerto is None:
        puerto = _puerto_determinista(datos)
    elif puerto == 0:
        puerto = _puerto_libre()
        # Permite que dos llamadas programáticas con los mismos argumentos
        # reutilicen también un puerto inicialmente efímero.
        args.puerto = puerto

    meta = _meta(puerto)
    identidad = {
        "servicio": "visor-presentaciones",
        "huella_datos": huella_datos(datos),
    }
    if meta == identidad:
        url = _url(puerto, getattr(args, "presentacion", None))
        return Resultado(url, navegador=abrir_navegador(url, args))
    if meta is not None:
        raise ValueError("el puerto %d ya lo usa otra sesión" % puerto)

    registro = datos / ".runtime" / ("presentaciones-%d.log" % puerto)
    registro.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        sys.executable, str(BASE / "servir.py"), "--datos", str(datos),
        "--puerto", str(puerto), "--sin-navegador",
    ]
    workspace = getattr(args, "workspace", None)
    if workspace:
        comando += ["--workspace", str(workspace)]
    with registro.open("ab") as salida:
        proceso = subprocess.Popen(
            comando, stdin=subprocess.DEVNULL, stdout=salida,
            stderr=subprocess.STDOUT, start_new_session=True,
        )

    for _ in range(50):
        meta = _meta(puerto)
        if meta == identidad:
            url = _url(puerto, getattr(args, "presentacion", None))
            return Resultado(url, proceso, abrir_navegador(url, args))
        if proceso.poll() is not None:
            break
        time.sleep(0.1)
    detener(proceso)
    raise RuntimeError("el servidor de presentaciones no llegó a arrancar")


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
    parser = argparse.ArgumentParser(description="Abre una presentación local")
    parser.add_argument("--datos", required=True)
    parser.add_argument("--presentacion")
    parser.add_argument("--puerto", type=int)
    parser.add_argument("--workspace", help="raíz del meta-repo/main para servir adjuntos")
    parser.add_argument("--sin-navegador", action="store_true")
    args = parser.parse_args()
    try:
        resultado = abrir(args.datos, args)
        print(resultado.url)
        if not resultado.navegador:
            print("(no abro el navegador: %s)" % (
                "--sin-navegador" if args.sin_navegador else "sesión sin pantalla"))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print("ERROR: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
