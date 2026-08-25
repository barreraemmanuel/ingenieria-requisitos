#!/usr/bin/env python3
"""El tablero de control: qué hay en curso, qué falta, quién trabaja y qué te toca.

Cuarta web local del método, y la única de OBSERVACIÓN: aquí no se aprueba, no
se decide y no se cierra nada — eso vive en las otras tres. Mismo patrón que
`visor_contratos/servir.py` (ThreadingHTTPServer en 127.0.0.1, sin caché de
navegador) y mismo motor de bloques: `render.js` se sirve LEÍDO de
`visor_contratos/`, no copiado (bug 055).

Rutas, todas de lectura:

    GET /                 la plantilla
    GET /estado.json      la foto entera del workspace (la página la sondea)
    GET /doc/<ruta>.md    un markdown de dentro del meta-repo (con guarda)
    GET /render.js        el motor de bloques del visor de contratos
    GET /meta.json        identidad del servicio, para `abrir.py`

Cualquier POST responde 405: el tablero no escribe (R8).

Uso:
    python3 visor_tablero/servir.py --workspace <ruta del meta-repo>
"""

import argparse
import hashlib
import http.server
import json
import os
import socket
import sys
import threading
import time
import webbrowser
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


def main():
    p = argparse.ArgumentParser(description="Tablero de control del workspace")
    p.add_argument("--workspace", required=True,
                   help="Ruta del meta-repo (el que tiene docs/05-trabajo/)")
    p.add_argument("--puerto", type=int, default=8768,
                   help="puerto local; 0 pide uno libre (defecto: 8768)")
    p.add_argument("--minutos", type=float, default=0,
                   help="minutos sin actividad antes de apagarse; 0 = no caduca")
    p.add_argument("--sin-navegador", action="store_true",
                   help="No abrir el navegador")
    args = p.parse_args()

    if not (0 <= args.minutos <= 1440):
        sys.exit("--minutos debe estar entre 0 y 1440")
    if not (0 <= args.puerto <= 65535):
        sys.exit("--puerto debe estar entre 0 y 65535")

    workspace = os.path.abspath(args.workspace)
    trabajo = os.path.join(workspace, "docs", "05-trabajo")
    if not os.path.isdir(trabajo):
        sys.exit("No existe la carpeta de unidades: " + trabajo)
    if not PLANTILLA.is_file():
        sys.exit("Falta la plantilla: %s" % PLANTILLA)
    if not RENDER_JS.is_file():
        sys.exit("Falta el motor de render del visor de contratos: %s" % RENDER_JS)

    estado = {"ultimo": time.time()}
    try:
        servidor = ServidorTablero(("127.0.0.1", args.puerto),
                                   hacer_handler(workspace, estado))
    except OSError as exc:
        sys.exit("No pude abrir el puerto %d: %s" % (args.puerto, exc))
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    anotar_apertura(workspace)

    url = "http://127.0.0.1:%d/" % puerto
    print("Tablero de control levantado: %s" % url, flush=True)
    print("Workspace: %s" % workspace, flush=True)
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
    print("Tablero de control cerrado.", flush=True)


if __name__ == "__main__":
    main()
