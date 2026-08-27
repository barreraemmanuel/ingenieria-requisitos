#!/usr/bin/env python3
"""El ÚNICO lanzador de la web del método (unidad 081).

Funde `visor_presentaciones/abrir.py` y `visor_tablero/abrir.py`, que hacían lo
mismo para dos de las cuatro webs: el puerto sale del propio workspace, así que
dos llamadas seguidas sobre el mismo meta-repo caen en el MISMO servidor en vez
de levantar un segundo; `INGENIERIA_REQUISITOS_PUERTO` lo fija a mano cuando hace
falta. Lo nuevo es `--apartado`: la web es una sola, y lo que se elige al lanzarla
es la dirección concreta a la que se abre el navegador.

    python3 web/abrir.py --workspace . --apartado contratos#081-una-sola-web
    python3 web/abrir.py --workspace . --apartado presentaciones/081-una-sola-web
    python3 web/abrir.py --workspace . --apartado flujos --sin-navegador
    python3 web/abrir.py --workspace . --apartado tablero
"""

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
    from .servir import SERVICIO, huella_workspace
except ImportError:  # También funciona como `python3 web/abrir.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from servir import SERVICIO, huella_workspace


BASE = Path(__file__).resolve().parent
PUERTO_BASE = 8770
VARIABLE_PUERTO = "INGENIERIA_REQUISITOS_PUERTO"
APARTADOS = ("tablero", "contratos", "presentaciones", "flujos")
# Bug 124 (R2): lo que se levanta para enseñar un contrato o una validación no se queda
# vivo para siempre. Cuatro horas sin que nadie pida una página son de sobra para la
# sesión más larga y poco para acumular visores de anteayer.
MINUTOS_POR_DEFECTO = 240


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


def argumentos_prueba(apartado=None, puerto=None, minutos=0):
    """Los argumentos que usan los tests y los lanzadores del método al llamar en
    proceso. `minutos` va como PEDIDO explícitamente: un test que dice 0 quiere 0."""
    return argparse.Namespace(apartado=apartado, puerto=puerto, minutos=minutos,
                              minutos_explicito=True, sin_navegador=True)


def minutos_efectivos(args):
    """Cuántos minutos de inactividad aguanta la web que se va a levantar (R2, 124).

    `unidad.py validar/nueva/estado` construyen su Namespace con `minutos=0` sin
    haberlo pedido nadie: ese 0 heredado significaba «no caduca nunca» y es lo que
    dejó siete servidores vivos desde anteayer. Aquí un 0 (o un `None`, o la
    ausencia del campo) que llega SIN `minutos_explicito` quiere decir «el defecto»;
    para pedir de verdad una web eterna hay que decirlo: `--minutos 0`.
    """
    minutos = getattr(args, "minutos", None)
    if getattr(args, "minutos_explicito", False) and minutos is not None:
        return minutos
    return MINUTOS_POR_DEFECTO if not minutos else minutos


def _puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexion:
        conexion.bind(("127.0.0.1", 0))
        return conexion.getsockname()[1]


def puerto_de(workspace):
    """El puerto de ESTE workspace (R6).

    Sale de la huella de su ruta, como en las webs que sustituye: dos workspaces
    abiertos a la vez no chocan y dos llamadas sobre el mismo caen en el mismo
    servidor. `INGENIERIA_REQUISITOS_PUERTO` manda sobre todo: es la salida
    cuando el puerto calculado lo ocupa otra cosa.
    """
    fijado = os.environ.get(VARIABLE_PUERTO, "").strip()
    if fijado:
        try:
            puerto = int(fijado)
        except ValueError:
            raise ValueError("%s no es un puerto: %r" % (VARIABLE_PUERTO, fijado))
        if not (0 <= puerto <= 65535):
            raise ValueError("%s fuera de rango: %d" % (VARIABLE_PUERTO, puerto))
        return puerto
    return PUERTO_BASE + (int(huella_workspace(workspace)[:8], 16) % 1000)


def url_de(puerto, apartado):
    """La URL del apartado pedido: `contratos#081-x`, `presentaciones/081-x`…

    El apartado se escribe como se lee en la barra de direcciones, con su ancla
    si la tiene. `tablero` es la portada y por tanto `/`.
    """
    destino = (apartado or "tablero").strip().lstrip("/")
    camino, _, ancla = destino.partition("#")
    camino = camino.strip("/")
    primero = camino.split("/")[0] if camino else "tablero"
    if primero not in APARTADOS:
        raise ValueError("no existe el apartado %r (son: %s)"
                         % (primero, ", ".join(APARTADOS)))
    if primero == "tablero":
        ruta = "/" + camino[len("tablero"):].lstrip("/")
    else:
        ruta = "/" + camino
    return "http://127.0.0.1:%d%s%s" % (puerto, ruta, "#" + ancla if ancla else "")


def _meta(puerto):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/meta.json" % puerto, timeout=0.5
        ) as respuesta:
            return json.loads(respuesta.read())
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _identidad(meta, workspace):
    return (isinstance(meta, dict)
            and meta.get("servicio") == SERVICIO
            and meta.get("huella_workspace") == huella_workspace(workspace))


def puertos_anotados(workspace):
    """Los puertos que alguna vez levantó ESTE workspace, por sus `.runtime/web-<puerto>.log`.

    Es el único rastro que deja una web al arrancar, y el mismo que lee Inicio para
    listar servidores. Un registro puede estar caduco (el servidor murió): quien lo
    use tiene que preguntar por `meta.json`, no fiarse del fichero.
    """
    puertos = []
    for registro in sorted((Path(workspace) / ".runtime").glob("web-*.log")):
        try:
            puerto = int(registro.stem.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        if 0 < puerto <= 65535:
            puertos.append(puerto)
    return puertos


def servidor_vivo(workspace, puerto):
    """El puerto donde YA está la web de este workspace, o None (R1, bug 124).

    Mira primero el puerto que toca y después los que anotaron los arranques
    anteriores: la web del método vale igual sirva donde sirva, y dos webs del
    mismo meta-repo (`:8790` y `:9041`) es exactamente lo que este bug quita.
    La identidad la firma `meta.json`; jamás se reutiliza la web de OTRO workspace.
    """
    if _identidad(_meta(puerto), workspace):
        return puerto
    for otro in puertos_anotados(workspace):
        if otro != puerto and _identidad(_meta(otro), workspace):
            return otro
    return None


def abrir(workspace, args):
    """Levanta la web del workspace, o REUTILIZA la que ya esté en pie, y abre
    el navegador en el apartado pedido."""
    workspace = Path(workspace).expanduser().resolve()
    if not (workspace / "docs" / "05-trabajo").is_dir():
        raise ValueError("no parece un meta-repo (falta docs/05-trabajo/): %s"
                         % workspace)
    puerto = getattr(args, "puerto", None)
    if puerto is None:
        puerto = puerto_de(workspace)
    elif puerto == 0:
        puerto = _puerto_libre()
        args.puerto = puerto
    apartado = getattr(args, "apartado", None)
    url = url_de(puerto, apartado)      # valida el apartado ANTES de levantar nada

    vivo = servidor_vivo(workspace, puerto)
    if vivo is not None:
        url = url_de(vivo, apartado)
        return Resultado(url, navegador=abrir_navegador(url, args))
    meta = _meta(puerto)
    if meta is not None:
        raise ValueError(
            "el puerto %d ya lo usa otra sesión (%s). Fija otro con %s=<puerto>"
            % (puerto, meta.get("servicio", "desconocida"), VARIABLE_PUERTO))

    registro = workspace / ".runtime" / ("web-%d.log" % puerto)
    registro.parent.mkdir(parents=True, exist_ok=True)
    comando = [sys.executable, str(BASE / "servir.py"),
               "--workspace", str(workspace), "--puerto", str(puerto),
               "--minutos", str(minutos_efectivos(args)),
               "--sin-navegador"]
    with registro.open("ab") as salida:
        # Desasido a propósito: la web tiene que seguir en pie cuando el comando
        # que la levantó termine — es lo que el usuario va a mirar.
        proceso = subprocess.Popen(
            comando, stdin=subprocess.DEVNULL, stdout=salida,
            stderr=subprocess.STDOUT, start_new_session=True,
        )

    for _ in range(100):
        if _identidad(_meta(puerto), workspace):
            return Resultado(url, proceso, abrir_navegador(url, args))
        if proceso.poll() is not None:
            break
        time.sleep(0.1)
    detener(proceso)
    raise RuntimeError("la web del método no llegó a arrancar; mira %s" % registro)


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
    parser = argparse.ArgumentParser(description="Abre la web del método")
    parser.add_argument("--workspace", required=True,
                        help="Ruta del meta-repo (el que tiene docs/05-trabajo/)")
    parser.add_argument("--apartado", default="tablero",
                        help="apartado y ancla: tablero | contratos[#unidad] | "
                             "presentaciones[/unidad] | flujos[#actividad]")
    parser.add_argument("--puerto", type=int)
    parser.add_argument("--minutos", type=float, default=None,
                        help="minutos sin actividad antes de apagarse; 0 = no caduca. "
                             "Por defecto, %d" % MINUTOS_POR_DEFECTO)
    parser.add_argument("--sin-navegador", action="store_true")
    args = parser.parse_args()
    # Haberlo escrito en la línea de órdenes es lo que distingue «no caduca» (0 pedido)
    # de «lo de siempre» (nada dicho): ver `minutos_efectivos`.
    args.minutos_explicito = args.minutos is not None
    try:
        resultado = abrir(args.workspace, args)
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
