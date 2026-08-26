#!/usr/bin/env python3
"""Punto de entrada humano para revisar requisitos dentro de un workspace.

Uso desde la raíz de ``<nombre>-agents``:

    python3 docs/00-metodo/requisitos/requisitos.py abrir
    python3 docs/00-metodo/requisitos/requisitos.py listo
    python3 docs/00-metodo/requisitos/requisitos.py estado
    python3 docs/00-metodo/requisitos/requisitos.py aprobar --por "Nombre"
    python3 docs/00-metodo/requisitos/requisitos.py solicitar-cambios --texto "..."
    python3 docs/00-metodo/requisitos/requisitos.py resolver FB-1
"""

import argparse
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
try:
    from . import revision
except ImportError:
    import revision

BASE = Path(__file__).resolve().parent


def mapa_workspace(workspace):
    workspace = Path(workspace).expanduser().resolve()
    mapa = workspace / "docs" / "02-flujos" / "planos" / "planos.json"
    if not mapa.is_file():
        raise ValueError("no encuentro los planos canónicos en %s" % mapa)
    return workspace, mapa


def puerto_determinista(workspace):
    huella = hashlib.sha256(
        str(Path(workspace).expanduser().resolve()).encode("utf-8")
    ).hexdigest()
    return 8766 + (int(huella[:8], 16) % 1000)


def puerto_ocupado(puerto):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexion:
        conexion.settimeout(0.2)
        return conexion.connect_ex(("127.0.0.1", puerto)) == 0


def meta_puerto(puerto):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/meta.json" % puerto, timeout=0.5
        ) as respuesta:
            return json.loads(respuesta.read())
    except (OSError, ValueError, urllib.error.URLError):
        return None


def elegir_puerto(workspace, mapa, pedido=None):
    if pedido is not None:
        if pedido == 0:
            return 0, False
        meta = meta_puerto(pedido)
        if meta and Path(meta.get("datos", "")).resolve() == mapa.resolve():
            return pedido, True
        if puerto_ocupado(pedido):
            raise ValueError("el puerto %d ya lo usa otro servicio" % pedido)
        return pedido, False

    candidatos = [8765, puerto_determinista(workspace)]
    candidatos += [
        puerto_determinista(workspace) + desplazamiento
        for desplazamiento in range(1, 50)
    ]
    for puerto in candidatos:
        meta = meta_puerto(puerto)
        if meta and Path(meta.get("datos", "")).resolve() == mapa.resolve():
            return puerto, True
        if not puerto_ocupado(puerto):
            return puerto, False
    raise ValueError("no encontré un puerto local libre para el visor")


def cmd_listo(mapa):
    """Cierra F5: valida la entrega completa y marca los planos como
    "listo para revisar". Es el ÚNICO camino para ese estado — el RUNBOOK
    prohíbe editarlo a mano, y `aprobar` exige que ya esté puesto."""
    validacion = revision.ejecutar_validador(
        mapa, "revision", extra=["--tolerar-borrador"]
    )
    if not validacion["valido"]:
        print("NO LISTO: la entrega aún no pasa la revisión.")
        for linea in validacion["errores"]:
            print("- %s" % linea)
        return 1
    for ruta in revision.rutas_planos(mapa):
        datos = revision.leer_json(ruta)
        definicion = datos.setdefault("definicion", {})
        if definicion.get("estado") in ("aprobado", "congelado"):
            continue  # una versión ya aprobada no se degrada
        definicion["estado"] = "listo para revisar"
        revision.escribir_json(ruta, datos)
    print("LISTOS PARA REVISAR: entrega completa validada.")
    for linea in validacion["avisos"]:
        print("AVISO  %s" % linea)
    print(
        "Siguiente paso: el usuario revisa la web pestaña a pestaña y, con "
        'su OK, `aprobar --por "NOMBRE"`.'
    )
    return 0


def cmd_estado(mapa):
    estado = revision.estado_revision(mapa)
    if estado["listo"]:
        print("LISTO PARA REVISAR")
        if estado["aprobacion_vigente"]:
            print("La aprobación vigente coincide con estos planos.")
        return 0
    print("NO LISTO PARA REVISAR")
    if estado["feedback_pendiente"]:
        print(
            "%d comentario(s) pendiente(s)." % estado["feedback_pendiente"]
        )
    for bloqueo in estado["bloqueos"]:
        print("- %s" % bloqueo)
    return 1


def puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexion:
        conexion.bind(("127.0.0.1", 0))
        return conexion.getsockname()[1]


def anotar_apertura(workspace, puerto):
    """Deja fechado el rastro de sesión del visor y devuelve su registro.

    Es la evidencia que `revision.aprobar` exige desde la unidad 033 (R3). Se anota
    TAMBIÉN cuando el visor ya estaba activo: si el rastro solo se escribiera al
    arrancar, mirar los planos en un visor abierto desde ayer no contaría como
    haberlos visto hoy, y la puerta bloquearía el camino legítimo.
    """
    registro = Path(workspace) / ".runtime" / ("visor-%d.log" % puerto)
    registro.parent.mkdir(parents=True, exist_ok=True)
    with open(registro, "a", encoding="utf-8") as rastro:
        rastro.write(
            "%s visor abierto sobre estos planos (puerto %d)\n"
            % (time.strftime("%Y-%m-%dT%H:%M:%S"), puerto)
        )
    return registro


def destino_actividad(mapa, actividad):
    """Devuelve el hash de una actividad existente o falla antes de abrir nada."""
    if not actividad:
        return ""
    try:
        datos = json.loads(mapa.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("no pude leer el mapa para abrir la actividad: %s" % exc)
    ids = {
        item.get("id") for item in datos.get("actividades", [])
        if isinstance(item, dict) and item.get("id")
    }
    if actividad not in ids:
        raise ValueError("la actividad '%s' no existe en el mapa actual" % actividad)
    return "#%s::resumen" % actividad


def carpeta_web():
    """La carpeta de la web del método, en los dos layouts (081).

    En el workspace del alumno este fichero vive en `docs/00-metodo/requisitos/`
    y la web, en su subcarpeta `web/`. En el repo de código, en `visor/` y la web
    en `main/web/` — es decir, el hermano `web/` de `visor/`.
    """
    for candidata in (BASE / "web", BASE.parent / "web"):
        if (candidata / "abrir.py").is_file() and (candidata / "servir.py").is_file():
            return candidata
    return None


def modulo_abrir(carpeta):
    """`abrir.py` de la web, cargado de SU sitio: una sola verdad del puerto."""
    sys.path.insert(0, str(carpeta))
    try:
        spec = importlib.util.spec_from_file_location(
            "web_metodo_abrir", carpeta / "abrir.py")
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = modulo
        spec.loader.exec_module(modulo)
        return modulo
    finally:
        try:
            sys.path.remove(str(carpeta))
        except ValueError:
            pass


def cmd_abrir(workspace, mapa, args):
    """Abre el apartado FLUJOS de la web del método (081).

    Ya no hay un visor de flujos en su propio puerto: hay una sola web con cuatro
    apartados, y `web/abrir.py` reutiliza la que ya esté en pie sobre este
    workspace. El rastro que `aprobar` exige (`.runtime/visor-<puerto>.log`,
    unidad 033 R3) lo sigue dejando esta llamada, y también la web cada vez que
    sirve `/flujos`: mirar los planos hoy cuenta como haberlos visto hoy.
    """
    # Una actividad que no existe REVIENTA aquí, antes de levantar nada: abrir la
    # portada «por si acaso» es enseñar otra cosa de la que se pidió.
    destino = destino_actividad(mapa, getattr(args, "actividad", None))
    carpeta = carpeta_web()
    if carpeta is None:
        print("ERROR: no encuentro la web del método (falta web/abrir.py). "
              "Vuelve a repartirla con `python3 main/visor/actualizar.py`.")
        return 1
    mod_abrir = modulo_abrir(carpeta)
    apartado = "flujos" + (destino if destino.startswith("#") else "")
    argumentos = argparse.Namespace(
        apartado=apartado, puerto=getattr(args, "puerto", None),
        minutos=getattr(args, "minutos", 0), sin_navegador=args.sin_navegador)
    try:
        resultado = mod_abrir.abrir(workspace, argumentos)
    except (OSError, RuntimeError, ValueError) as exc:
        print("ERROR: no pude abrir la web del método (%s)" % exc)
        return 1
    anotar_apertura(workspace, mod_abrir.puerto_de(Path(workspace).resolve()))
    print("Apartado Flujos de la web del método: %s" % resultado.url)
    if not resultado.navegador and not args.sin_navegador:
        print("(no he podido abrir el navegador; pásale esa dirección)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Abre y gestiona la revisión de planos")
    sub = ap.add_subparsers(dest="comando", required=True)

    abrir = sub.add_parser("abrir", help="abre o reutiliza el visor estable")
    abrir.add_argument("--workspace", default=".")
    abrir.add_argument("--puerto", type=int)
    abrir.add_argument("--minutos", type=float, default=0)
    abrir.add_argument("--sin-navegador", action="store_true")
    abrir.add_argument(
        "--actividad",
        help="ID de la actividad del mapa que se abre directamente en Resumen",
    )

    listo = sub.add_parser(
        "listo",
        help="valida la entrega completa y marca los planos como listos "
             "para revisar (el estado no se edita a mano)",
    )
    listo.add_argument("--workspace", default=".")

    estado = sub.add_parser("estado", help="muestra si se puede pedir aprobación")
    estado.add_argument("--workspace", default=".")

    resolver = sub.add_parser("resolver", help="marca un feedback como resuelto")
    resolver.add_argument("id")
    resolver.add_argument("--workspace", default=".")

    aprobar = sub.add_parser(
        "aprobar", help="registra por CLI la aprobación de esta versión"
    )
    aprobar.add_argument("--por", required=True)
    aprobar.add_argument("--confirmar-supuestos", action="store_true")
    aprobar.add_argument("--workspace", default=".")

    cambios = sub.add_parser(
        "solicitar-cambios", help="reabre los planos y registra el motivo"
    )
    cambios.add_argument("--texto", required=True)
    cambios.add_argument("--workspace", default=".")

    args = ap.parse_args()
    try:
        workspace, mapa = mapa_workspace(args.workspace)
        if args.comando == "listo":
            return cmd_listo(mapa)
        if args.comando == "estado":
            return cmd_estado(mapa)
        if args.comando == "resolver":
            revision.resolver_feedback(mapa, args.id)
            print("%s resuelto." % args.id)
            return 0
        if args.comando == "aprobar":
            recibo = revision.aprobar(
                mapa, args.por, args.confirmar_supuestos
            )
            print(
                "Versión %d aprobada por %s."
                % (recibo["version"], recibo["por"])
            )
            return 0
        if args.comando == "solicitar-cambios":
            comentario = revision.solicitar_cambios(
                mapa, args.texto, {"canal": "agente-cli"}
            )
            print("Cambios solicitados (%s)." % comentario["id"])
            return 0
        return cmd_abrir(workspace, mapa, args)
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
