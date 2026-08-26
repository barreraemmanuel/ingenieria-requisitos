#!/usr/bin/env python3
"""El tablero de control: qué hay en curso, qué falta, quién trabaja y qué te toca.

La PORTADA de la web del método, y el único apartado de OBSERVACIÓN: aquí no se
aprueba, no se decide y no se cierra nada — eso vive en los otros tres.

Desde la unidad 081 esto NO es un servidor: es el módulo de datos que `web/servir.py`
monta bajo `/tablero/`, y cuya página sirve en `/`.

Rutas, todas de lectura:

    GET /estado.json      la foto entera del workspace (la página la sondea)
    GET /doc/<ruta>.md    un markdown de dentro del meta-repo (con guarda)

Cualquier POST responde 405: el tablero no escribe (R8).
"""

import hashlib
import http.server
import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    from . import estado as estado_mod
except ImportError:  # También funciona como `python3 visor_tablero/servir.py`.
    import estado as estado_mod


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
PLANTILLA = BASE / "plantilla.html"
RENDER_JS = BASE.parent / "visor_contratos" / "render.js"
# La hoja común de las cuatro webs (unidad 076), leída de su único sitio.
BASE_CSS = BASE.parent / "visor" / "base.css"
RASTRO = "tablero.log"
SERVICIO = "visor-tablero"


def huella_workspace(workspace):
    """Identifica el workspace servido sin publicar su ruta local."""
    ruta = str(Path(workspace).expanduser().resolve()).encode("utf-8")
    return hashlib.sha256(b"visor-tablero\0" + ruta).hexdigest()


class ServidorTablero(http.server.ThreadingHTTPServer):
    """Mismo bind exclusivo que las otras webs: en Windows SO_REUSEADDR deja que
    un segundo servidor robe un puerto ya en uso (bug del puerto 8765)."""

    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == "win32":
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        http.server.HTTPServer.server_bind(self)


def hacer_handler(workspace, estado):
    workspace = str(Path(workspace).resolve())
    cache = estado_mod.Cache(workspace)

    class Tablero(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            estado["ultimo"] = time.time()
            pedida = urlsplit(self.path).path
            if pedida in ("/", "/index.html"):
                return self._fichero(PLANTILLA, "text/html; charset=utf-8")
            if pedida == "/render.js":
                # El motor de la 056, leído de su sitio: una sola copia viva.
                return self._fichero(RENDER_JS, "text/javascript; charset=utf-8")
            if pedida == "/base.css":
                # Hoja común de las cuatro webs (unidad 076).
                return self._fichero(BASE_CSS, "text/css; charset=utf-8")
            if pedida == "/meta.json":
                return self._json(200, {
                    "servicio": SERVICIO,
                    "huella_workspace": huella_workspace(workspace),
                })
            if pedida == "/estado.json":
                # La página lo sondea: un fallo leyendo el workspace viaja como
                # JSON, nunca mata la conexión ni deja la web en blanco.
                try:
                    return self._json(200, cache.instantanea())
                except Exception as exc:  # noqa: BLE001 - el sondeo no se cae
                    return self._json(500, {
                        "error": str(exc) or exc.__class__.__name__,
                    })
            if pedida.startswith("/doc/"):
                return self._doc(pedida[len("/doc/"):])
            return self._json(404, {"error": "ruta inexistente"})

        def _doc(self, cruda):
            try:
                ruta = estado_mod.ruta_doc(workspace, unquote(cruda))
            except ValueError:
                return self._json(403, {"error": "ruta no permitida"})
            except (FileNotFoundError, OSError):
                return self._json(404, {"error": "no existe ese documento"})
            return self._fichero(ruta, "text/markdown; charset=utf-8")

        def do_POST(self):
            estado["ultimo"] = time.time()
            return self._json(405, {
                "error": ("el tablero sólo mira: aprobar, decidir y cerrar se "
                          "hacen en las otras webs y hablando con el agente"),
            })

        def do_PUT(self):
            return self.do_POST()

        def do_DELETE(self):
            return self.do_POST()

        def do_HEAD(self):
            estado["ultimo"] = time.time()
            self.send_response(200)
            self.end_headers()

        def _fichero(self, ruta, tipo):
            try:
                cuerpo = Path(ruta).read_bytes()
            except OSError:
                return self.send_error(500, "No se pudo leer " + Path(ruta).name)
            self.send_response(200)
            self._cabeceras(tipo, len(cuerpo))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, codigo, datos):
            cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self._cabeceras("application/json; charset=utf-8", len(cuerpo))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _cabeceras(self, tipo, longitud):
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(longitud))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
            )

        def log_message(self, *args):
            pass

    return Tablero


def anotar_apertura(workspace):
    """Rastro fechado de que el tablero se levantó, como las otras webs."""
    registro = Path(workspace) / ".runtime" / RASTRO
    try:
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "a", encoding="utf-8") as rastro:
            rastro.write("%s tablero levantado\n"
                         % time.strftime("%Y-%m-%dT%H:%M:%S"))
    except OSError:
        return None
    return registro

# 081: este fichero dejó de ser un programa. Es el MÓDULO DE DATOS de la PORTADA
# de la web única: `web/servir.py` importa `hacer_handler` y le monta estas rutas
# bajo `/tablero/`, y la página en `/`. El rastro `.runtime/tablero.log` lo
# escribe ahora la web al levantarse.
