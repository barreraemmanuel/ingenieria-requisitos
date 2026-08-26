#!/usr/bin/env python3
"""Visor local de los planos (ingeniería de requisitos).

Desde la unidad 081 esto NO es un servidor: es el módulo de datos del apartado
«Flujos» de la web única. `web/servir.py` importa `hacer_handler` y monta estas
rutas bajo `/flujos/`. Sigue siendo estrictamente de sólo lectura: expone planos,
documentos, historial y comparación, pero nunca recibe feedback ni aprobaciones.

Rutas (bajo `/flujos/` en la web; sueltas, en los tests de datos):

    GET /datos.json         los planos del proyecto
    GET /historial.json     el historial de revisiones
    GET /comparacion.json   contra la última aprobación
    GET /spec.md /encargo.md    los documentos de salida, si existen
    GET /actividades/<id>/…     los planos de cada actividad
"""

import http.server
import json
import os
import re
import socket
import sys
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
from urllib.parse import urlsplit

try:
    from . import revision
except ImportError:
    import revision

RUTA_ACTIVIDAD = re.compile(r"^/actividades/([a-z0-9][a-z0-9-]*)/(datos\.json|spec\.md|encargo\.md)$")

BASE = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(BASE, "plantilla.html")
# La hoja común de las cuatro webs (unidad 076): un solo fichero, sin copia.
# Vive AQUÍ y las otras tres la leen de este mismo sitio.
BASE_CSS = os.path.join(BASE, "base.css")


def hacer_handler(ruta_datos, estado):
    class Visor(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            estado["ultimo"] = time.time()
            pedida = urlsplit(self.path).path
            if pedida in ("/", "/index.html"):
                self._fichero(PLANTILLA, "text/html; charset=utf-8")
            elif pedida == "/base.css":
                # Hoja común de las cuatro webs (unidad 076).
                self._fichero(BASE_CSS, "text/css; charset=utf-8")
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

# 081: este fichero dejó de ser un programa. Es el MÓDULO DE DATOS del apartado
# «Flujos» de la web única: `web/servir.py` importa `hacer_handler` y le monta
# estas mismas rutas bajo `/flujos/`. Ya no abre puerto, ya no abre navegador y
# ya no tiene `main()`: sólo hay un servidor en el método.
