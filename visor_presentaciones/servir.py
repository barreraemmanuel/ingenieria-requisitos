#!/usr/bin/env python3
"""Servidor local de presentaciones y recibos de decisión inmutables."""

import argparse
import http.server
import json
import os
import socket
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

try:
    from . import manifestar
except ImportError:  # También funciona como `python3 visor_presentaciones/servir.py`.
    import manifestar

BASE = Path(__file__).resolve().parent
PLANTILLA = BASE / "plantilla.html"


class ServidorPresentaciones(http.server.ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        elif sys.platform != "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        http.server.HTTPServer.server_bind(self)


def _leer_manifiesto(datos):
    contenido = json.loads((datos / "manifiesto.json").read_text(encoding="utf-8"))
    return manifestar.validar(contenido)


def _ruta_en_datos(datos, ruta):
    """Devuelve la ruta resuelta o rechaza enlaces que escapen de datos."""
    resuelta = Path(ruta).resolve(strict=False)
    try:
        resuelta.relative_to(datos)
    except ValueError:
        raise ValueError("ruta de recibos fuera del directorio de datos")
    return resuelta


def hacer_handler(datos, estado):
    datos = Path(datos).resolve()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            estado["ultimo"] = time.time()
            ruta = urlsplit(self.path).path
            if ruta in ("/", "/index.html"):
                return self._fichero(PLANTILLA, "text/html; charset=utf-8")
            if ruta.startswith("/presentacion/") and ruta.count("/") == 2 and manifestar.ID.fullmatch(ruta.rsplit("/", 1)[1]):
                try:
                    identificador = ruta.rsplit("/", 1)[1]
                    if any(p["id"] == identificador for p in _leer_manifiesto(datos)["presentaciones"]):
                        return self._fichero(PLANTILLA, "text/html; charset=utf-8")
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
                return self._json(404, {"error": "presentación inexistente"})
            if ruta == "/manifiesto.json":
                try:
                    return self._json(200, _leer_manifiesto(datos))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    return self._json(400, {"error": str(exc)})
            if ruta == "/recibos.json":
                try:
                    carpeta = _ruta_en_datos(datos, datos / "recibos")
                    recibos = []
                    for fichero in sorted(carpeta.glob("*.json")):
                        fichero = _ruta_en_datos(datos, fichero)
                        try:
                            recibos.append(json.loads(fichero.read_text(encoding="utf-8")))
                        except (OSError, json.JSONDecodeError):
                            continue
                    return self._json(200, {"recibos": recibos})
                except (OSError, ValueError) as exc:
                    return self._json(400, {"error": str(exc) or "recibos inválidos"})
            return self._json(404, {"error": "ruta inexistente"})

        def do_POST(self):
            estado["ultimo"] = time.time()
            if urlsplit(self.path).path != "/decisiones":
                return self._json(405, {"error": "POST no autorizado"})
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Content-Type debe ser application/json")
                longitud = int(self.headers.get("Content-Length", "0"))
                if longitud <= 0 or longitud > 20_000:
                    raise ValueError("tamaño de JSON inválido")
                peticion = json.loads(self.rfile.read(longitud))
                recibo = self._validar_decision(peticion)
                carpeta = _ruta_en_datos(datos, datos / "recibos")
                carpeta.mkdir(mode=0o700, exist_ok=True)
                ruta = _ruta_en_datos(datos, carpeta / (recibo["id"] + ".json"))
                with ruta.open("x", encoding="utf-8") as salida:
                    json.dump(recibo, salida, ensure_ascii=False, indent=2)
                    salida.write("\n")
                return self._json(201, {"recibo": recibo})
            except (ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc) or "decisión inválida"})

        def _validar_decision(self, d):
            campos = {"presentacion", "version", "contenido_revisado", "eleccion", "comentario", "confirmado"}
            if not isinstance(d, dict) or set(d) != campos or d["confirmado"] is not True:
                raise ValueError("campos o confirmación inválidos")
            manifiesto = _leer_manifiesto(datos)
            p = next((x for x in manifiesto["presentaciones"] if x["id"] == d["presentacion"]), None)
            if not p or p["tipo"] not in {"propuesta", "validacion"}:
                raise ValueError("presentación no autorizada")
            esperado = p["resumen"] if p["tipo"] == "propuesta" else "\n".join(p["pasos"])
            if d["version"] != p["version"] or d["contenido_revisado"] != esperado:
                raise ValueError("versión o contenido revisado no coincide")
            if d["eleccion"] not in p["opciones"]:
                raise ValueError("elección inválida")
            comentario = d["comentario"]
            if not isinstance(comentario, str) or len(comentario) > 2000 or manifestar.SENSIBLE.search(comentario):
                raise ValueError("comentario inválido o sensible")
            if d["eleccion"] in p["comentario_obligatorio"] and not comentario.strip():
                raise ValueError("el comentario es obligatorio")
            return {"id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex, "presentacion": p["id"], "version": p["version"], "contenido_revisado": esperado, "eleccion": d["eleccion"], "comentario": comentario, "fecha": datetime.now(timezone.utc).isoformat()}

        def _fichero(self, ruta, tipo):
            cuerpo = Path(ruta).read_bytes()
            self.send_response(200)
            self._cabeceras(tipo, len(cuerpo))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, codigo, valor):
            cuerpo = json.dumps(valor, ensure_ascii=False).encode()
            self.send_response(codigo)
            self._cabeceras("application/json; charset=utf-8", len(cuerpo))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _cabeceras(self, tipo, longitud):
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(longitud))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")

        def log_message(self, *_):
            pass

    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--datos", required=True)
    p.add_argument("--puerto", type=int, default=8767)
    p.add_argument("--sin-navegador", action="store_true")
    args = p.parse_args()
    datos = Path(args.datos).resolve()
    _leer_manifiesto(datos)
    servidor = ServidorPresentaciones(("127.0.0.1", args.puerto), hacer_handler(datos, {"ultimo": time.time()}))
    url = f"http://127.0.0.1:{servidor.server_port}/"
    print("Presentaciones locales: " + url, flush=True)
    if not args.sin_navegador:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
