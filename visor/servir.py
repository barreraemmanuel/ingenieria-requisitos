#!/usr/bin/env python3
"""Visor local de los planos (ingeniería de requisitos).

Sirve la plantilla fija (plantilla.html, junto a este script) y los datos del
proyecto (planos.json) en 127.0.0.1. Es estrictamente de sólo lectura: expone
planos, documentos, historial y comparación, pero nunca recibe feedback ni
aprobaciones. No caduca por defecto; ``--minutos`` permite un cierre opcional.

Uso:
    python3 servir.py --datos <ruta/planos.json> [--minutos 0] [--puerto 8765]
"""

import argparse
import http.server
import json
import os
import re
import socket
import sys
import threading
import time



# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
class ServidorVisor(http.server.ThreadingHTTPServer):
    """En Windows, SO_REUSEADDR deja que un segundo visor se quede con un puerto
    ya en uso y le robe las conexiones al primero (reportado en el bug del
    puerto 8765). El bind debe ser exclusivo allí; en el resto de plataformas
    SO_REUSEADDR conserva su comportamiento normal (rearrancar sin esperar el
    TIME_WAIT) y el robo no es posible."""

    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == "win32":
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        http.server.HTTPServer.server_bind(self)
import webbrowser
from urllib.parse import urlsplit

try:
    from . import revision
except ImportError:
    import revision

RUTA_ACTIVIDAD = re.compile(r"^/actividades/([a-z0-9][a-z0-9-]*)/(datos\.json|spec\.md|encargo\.md)$")

BASE = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(BASE, "plantilla.html")


def hacer_handler(ruta_datos, estado):
    class Visor(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            estado["ultimo"] = time.time()
            pedida = urlsplit(self.path).path
            if pedida in ("/", "/index.html"):
                self._fichero(PLANTILLA, "text/html; charset=utf-8")
            elif pedida == "/meta.json":
                self._json(200, {
                    "datos": ruta_datos,
                    "proyecto": os.path.basename(os.path.dirname(ruta_datos)),
                })
            elif pedida == "/historial.json":
                self._json_seguro(revision.listar_historial)
            elif pedida == "/comparacion.json":
                self._json_seguro(revision.comparar_ultima_aprobacion)
            elif pedida == "/datos.json":
                # Se relee en cada petición: la página lo sondea sola.
                self._fichero(ruta_datos, "application/json; charset=utf-8")
            elif pedida in ("/spec.md", "/encargo.md"):
                # Documentos de salida, si ya existen junto a los datos.
                ruta = os.path.join(os.path.dirname(ruta_datos), pedida.lstrip("/"))
                if os.path.isfile(ruta):
                    self._fichero(ruta, "text/plain; charset=utf-8")
                else:
                    self.send_error(404, "Aún no se ha generado " + pedida.lstrip("/"))
            elif RUTA_ACTIVIDAD.match(pedida):
                # Planos y documentos de cada actividad (proyectos mapa).
                m = RUTA_ACTIVIDAD.match(pedida)
                nombre = "planos.json" if m.group(2) == "datos.json" else m.group(2)
                ruta = os.path.join(os.path.dirname(ruta_datos), "actividades", m.group(1), nombre)
                if os.path.isfile(ruta):
                    tipo = "application/json; charset=utf-8" if nombre.endswith(".json") else "text/plain; charset=utf-8"
                    self._fichero(ruta, tipo)
                else:
                    self.send_error(404, "Esta actividad aún no tiene " + nombre)
            else:
                self._json(404, {"error": "ruta inexistente"})

        def do_POST(self):
            estado["ultimo"] = time.time()
            return self._json(
                405,
                {
                    "error": (
                        "visor de solo lectura; comunica cambios al agente "
                        "y usa requisitos.py"
                    )
                },
            )

        def do_HEAD(self):
            estado["ultimo"] = time.time()
            self.send_response(200)
            self.end_headers()

        def _fichero(self, ruta, tipo):
            try:
                with open(ruta, "rb") as f:
                    cuerpo = f.read()
            except OSError:
                self.send_error(500, "No se pudo leer " + os.path.basename(ruta))
                return
            self.send_response(200)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json_seguro(self, funcion):
            # La página sondea estos endpoints cada pocos segundos: un fallo
            # leyendo planos debe viajar como JSON, nunca matar la conexión
            # (una conexión muerta bloquea el sondeo y se traga los clics).
            try:
                self._json(200, funcion(ruta_datos))
            except Exception as exc:
                self._json(500, {"error": str(exc) or exc.__class__.__name__})

        def _json(self, codigo, datos):
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *args):
            pass

    return Visor


def main():
    p = argparse.ArgumentParser(description="Visor local de los planos")
    p.add_argument("--datos", required=True, help="Ruta al planos.json del proyecto")
    p.add_argument("--minutos", type=float, default=0,
                   help="minutos sin actividad antes de apagarse; 0 = no caduca")
    p.add_argument("--puerto", type=int, default=8765,
                   help="puerto local; 0 pide uno libre (defecto: 8765)")
    p.add_argument("--sin-navegador", action="store_true", help="No abrir el navegador")
    args = p.parse_args()

    if not (0 <= args.minutos <= 1440):
        sys.exit("--minutos debe estar entre 0 y 1440")
    if not (0 <= args.puerto <= 65535):
        sys.exit("--puerto debe estar entre 0 y 65535")

    ruta_datos = os.path.abspath(args.datos)
    if not os.path.isfile(ruta_datos):
        sys.exit("No existe el fichero de datos: " + ruta_datos)
    if not os.path.isfile(PLANTILLA):
        sys.exit("Falta la plantilla fija: " + PLANTILLA)
    try:
        with open(ruta_datos, "r", encoding="utf-8") as f:
            json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("El fichero de datos no es JSON válido: " + str(e))

    estado = {"ultimo": time.time()}
    try:
        servidor = ServidorVisor(
            ("127.0.0.1", args.puerto), hacer_handler(ruta_datos, estado)
        )
    except OSError as exc:
        sys.exit("No pude abrir el puerto %d: %s" % (args.puerto, exc))
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()

    url = "http://127.0.0.1:%d/" % puerto
    print("Visor levantado: %s" % url, flush=True)
    print("Datos: %s (se releen al recargar la página)" % ruta_datos, flush=True)
    if args.minutos:
        print("Se apaga tras %g minutos sin actividad." % args.minutos, flush=True)
    else:
        print("Sesión estable: no se apaga sola.", flush=True)
    if not args.sin_navegador:
        webbrowser.open(url)

    try:
        while True:
            if not args.minutos:
                time.sleep(15)
                continue
            restante = args.minutos * 60 - (time.time() - estado["ultimo"])
            if restante <= 0:
                break
            time.sleep(min(restante, 15))
    except KeyboardInterrupt:
        pass
    servidor.shutdown()
    print("Visor cerrado.", flush=True)


if __name__ == "__main__":
    main()
