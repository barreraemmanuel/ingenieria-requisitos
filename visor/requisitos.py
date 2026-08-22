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


def cmd_abrir(workspace, mapa, args):
    puerto, reutilizado = elegir_puerto(
        workspace, mapa, getattr(args, "puerto", None)
    )
    if reutilizado:
        anotar_apertura(workspace, puerto)
        url = "http://127.0.0.1:%d/" % puerto
        print("Visor ya activo: %s" % url)
        if not args.sin_navegador:
            webbrowser.open(url)
        return 0
    if puerto == 0:
        # El hijo elegiría un puerto que este proceso no podría conocer:
        # se resuelve aquí para poder imprimir la URL igualmente.
        puerto = puerto_libre()
    registro = anotar_apertura(workspace, puerto)
    comando = [
        sys.executable,
        str(BASE / "servir.py"),
        "--datos",
        str(mapa),
        "--puerto",
        str(puerto),
        "--minutos",
        str(args.minutos),
        # El navegador lo abre este proceso, no el hijo: así la URL se
        # imprime aquí SIEMPRE y el servidor queda desahogado en segundo
        # plano en vez de colgar la terminal (sesión estable, ADR del visor).
        "--sin-navegador",
    ]
    with open(registro, "ab") as salida:
        proceso = subprocess.Popen(
            comando,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=salida,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    url = "http://127.0.0.1:%d/" % puerto
    for _ in range(50):  # hasta ~10 s a que el servidor conteste
        meta = meta_puerto(puerto)
        if meta and Path(meta.get("datos", "")).resolve() == mapa.resolve():
            print("Visor abierto: %s" % url)
            print(
                "Queda corriendo en segundo plano (registro: %s)."
                % registro
            )
            if not args.sin_navegador:
                webbrowser.open(url)
            return 0
        if proceso.poll() is not None:
            break
        time.sleep(0.2)
    print("ERROR: el visor no llegó a arrancar. Su registro dice:")
    try:
        print(registro.read_text(encoding="utf-8").strip()[-2000:])
    except OSError:
        pass
    return 1


def main():
    ap = argparse.ArgumentParser(description="Abre y gestiona la revisión de planos")
    sub = ap.add_subparsers(dest="comando", required=True)

    abrir = sub.add_parser("abrir", help="abre o reutiliza el visor estable")
    abrir.add_argument("--workspace", default=".")
    abrir.add_argument("--puerto", type=int)
    abrir.add_argument("--minutos", type=float, default=0)
    abrir.add_argument("--sin-navegador", action="store_true")

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
