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
    python3 web/abrir.py --workspace . --apartado plan
    python3 web/abrir.py --workspace . --apartado contratos#162-x --lan

Lo último es la unidad 162: la misma web, escuchando también en la red local, y un
ENLACE FIRMADO que el agente imprime para que el usuario apruebe desde el móvil. El
enlace vale para ESE contrato (o esa entrega), una sola vez y quince minutos.
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
    from .servir import (CLAVES, MINUTOS_ENLACE, NOMBRE_UNIDAD, PARAM_ENLACE,
                         SERVICIO, emitir_enlace, huella_workspace, ip_de_la_lan)
except ImportError:  # También funciona como `python3 web/abrir.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from servir import (CLAVES, MINUTOS_ENLACE, NOMBRE_UNIDAD, PARAM_ENLACE,
                        SERVICIO, emitir_enlace, huella_workspace, ip_de_la_lan)


BASE = Path(__file__).resolve().parent
PUERTO_BASE = 8770
VARIABLE_PUERTO = "INGENIERIA_REQUISITOS_PUERTO"
# Los apartados los declara el servidor, y este lanzador los LEE (unidad 155): con
# la lista copiada, un apartado nuevo nacía enrutado en la web y desconocido aquí.
APARTADOS = CLAVES
# Bug 124 (R2): lo que se levanta para enseñar un contrato o una validación no se queda
# vivo para siempre. Cuatro horas sin que nadie pida una página son de sobra para la
# sesión más larga y poco para acumular visores de anteayer.
MINUTOS_POR_DEFECTO = 240


@dataclass
class Resultado:
    url: str
    proceso: object = None
    navegador: bool = False
    # Sólo con `--lan`: hasta cuándo vale el enlace que lleva la URL, para poder
    # decírselo al usuario. El token va DENTRO de `url` y no se guarda en otro sitio.
    caduca_en_minutos: float = 0


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


def url_de(puerto, apartado, host="127.0.0.1", token=None):
    """La URL del apartado pedido: `contratos#081-x`, `presentaciones/081-x`…

    El apartado se escribe como se lee en la barra de direcciones, con su ancla
    si la tiene. `tablero` es la portada y por tanto `/`. `host` y `token` son de
    la unidad 162: la misma dirección, vista desde el móvil y con la llave.
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
    consulta = "?%s=%s" % (PARAM_ENLACE, token) if token else ""
    return "http://%s:%d%s%s%s" % (host, puerto, ruta, consulta,
                                   "#" + ancla if ancla else "")


def enlace_pedido(apartado):
    """QUÉ se va a aprobar desde el móvil, leído del apartado (unidad 162).

    Un enlace firmado vale para UNA cosa, así que hay que saber cuál: el contrato
    (`contratos#NNN-slug`) o la entrega (`presentaciones/NNN-slug`). Abrir la LAN
    «por si acaso», sin nada concreto que aprobar, no es una comodidad: es dejar la
    puerta puesta sin saber para qué.
    """
    destino = (apartado or "").strip().lstrip("/")
    camino, _, ancla = destino.partition("#")
    trozos = [trozo for trozo in camino.strip("/").split("/") if trozo]
    primero = trozos[0] if trozos else ""
    ref = None
    if primero == "contratos":
        ref, tipo = ancla.strip(), "contrato"
    elif primero == "presentaciones":
        ref = trozos[1] if len(trozos) > 1 else ancla.strip()
        tipo = "validacion"
    if not ref or not NOMBRE_UNIDAD.match(ref):
        raise ValueError(
            "--lan necesita saber QUÉ vas a aprobar desde el móvil, porque el enlace "
            "vale para una sola cosa. SALIDA: --apartado contratos#NNN-slug (un "
            "contrato) o --apartado presentaciones/NNN-slug (una entrega)")
    return tipo, ref


def _huella_servida(puerto, tipo, ref):
    """La huella de lo que se va a aprobar, se la pedimos a la propia web.

    Es el mismo `/api/huella` que usa la página para no aprobar algo que ya cambió
    (unidad 107): el enlace queda atado a ESE contenido, no sólo a ese nombre.
    """
    direccion = ("http://127.0.0.1:%d/api/huella?tipo=%s&ref=%s"
                 % (puerto, tipo, ref))
    try:
        with urllib.request.urlopen(direccion, timeout=2) as respuesta:
            return json.loads(respuesta.read()).get("huella")
    except (OSError, ValueError, urllib.error.URLError):
        return None


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
    lan = bool(getattr(args, "lan", False))
    # Igual que el apartado: si `--lan` no sabe qué se aprueba, se dice AHORA y no
    # después de haber dejado una web escuchando en la red.
    tipo, ref = enlace_pedido(apartado) if lan else (None, None)

    vivo = servidor_vivo(workspace, puerto)
    if vivo is not None:
        if lan and not _meta(vivo).get("lan"):
            raise ValueError(
                "ya hay una web de este taller en pie (:%d) y NO escucha en la red "
                "local. SALIDA: ciérrala (Ctrl-C donde la lanzaste, o espera a que "
                "caduque) y vuelve a abrirla con --lan" % vivo)
        url = url_de(vivo, apartado)
        if lan:
            return _con_enlace(workspace, vivo, apartado, tipo, ref)
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
    if lan:
        comando.append("--lan")
    with registro.open("ab") as salida:
        # Desasido a propósito: la web tiene que seguir en pie cuando el comando
        # que la levantó termine — es lo que el usuario va a mirar.
        proceso = subprocess.Popen(
            comando, stdin=subprocess.DEVNULL, stdout=salida,
            stderr=subprocess.STDOUT, start_new_session=True,
        )

    for _ in range(100):
        if _identidad(_meta(puerto), workspace):
            if lan:
                return _con_enlace(workspace, puerto, apartado, tipo, ref, proceso)
            return Resultado(url, proceso, abrir_navegador(url, args))
        if proceso.poll() is not None:
            break
        time.sleep(0.1)
    detener(proceso)
    raise RuntimeError("la web del método no llegó a arrancar; mira %s" % registro)


def _con_enlace(workspace, puerto, apartado, tipo, ref, proceso=None):
    """La URL para el móvil: la IP de la red, el apartado y el enlace firmado.

    El navegador NO se abre: esta dirección no es para esta máquina, es para el
    teléfono que la va a teclear. El token se devuelve UNA vez, dentro de la URL;
    en disco sólo queda su hash, y quien lo pierda pide otro.
    """
    ip = ip_de_la_lan()
    if not ip:
        raise RuntimeError(
            "no encuentro la IP de esta máquina en la red local. SALIDA: conéctate a "
            "la wifi (o al cable) y vuelve a lanzarlo, o apruébalo desde este mismo "
            "ordenador sin --lan")
    huella = _huella_servida(puerto, tipo, ref)
    if not huella:
        raise ValueError(
            "no hay nada que aprobar en %s: la web no encuentra ese %s. SALIDA: "
            "comprueba el nombre (NNN-slug) en el apartado correspondiente"
            % (ref, tipo))
    token, _recibo = emitir_enlace(workspace, puerto, tipo, ref, huella)
    return Resultado(url_de(puerto, apartado, host=ip, token=token), proceso,
                     navegador=False, caduca_en_minutos=MINUTOS_ENLACE)


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
    parser.add_argument("--lan", action="store_true",
                        help="servir también en la red local y emitir un enlace "
                             "firmado de un uso para aprobar desde el móvil; hay que "
                             "decir QUÉ se aprueba (--apartado contratos#NNN-slug o "
                             "presentaciones/NNN-slug)")
    args = parser.parse_args()
    # Haberlo escrito en la línea de órdenes es lo que distingue «no caduca» (0 pedido)
    # de «lo de siempre» (nada dicho): ver `minutos_efectivos`.
    args.minutos_explicito = args.minutos is not None
    try:
        resultado = abrir(args.workspace, args)
        print(resultado.url)
        if args.lan:
            print("Ábrelo en el móvil (misma red). Vale para ESA aprobación, una vez "
                  "y %g minutos." % resultado.caduca_en_minutos)
            return 0
        if not resultado.navegador:
            print("(no abro el navegador: %s)" % (
                "--sin-navegador" if args.sin_navegador else "sesión sin pantalla"))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print("ERROR: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
