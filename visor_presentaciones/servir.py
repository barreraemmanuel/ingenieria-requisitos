#!/usr/bin/env python3
"""Servidor local de presentaciones y recibos de decisión inmutables."""

import argparse
import hashlib
import http.server
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    from . import manifestar
except ImportError:  # También funciona como `python3 visor_presentaciones/servir.py`.
    import manifestar

BASE = Path(__file__).resolve().parent
PLANTILLA = BASE / "plantilla.html"
# El motor de bloques se comparte con el visor de contratos (unidad 056): en el repo de
# código vive en `visor_contratos/`, y en un workspace de alumno el bootstrap lo copia al
# lado de este fichero — es el ÚNICO sitio donde puede estar allí (bug 064). Se busca en
# los dos layouts, en cada petición: el fichero puede aparecer o desaparecer en caliente.
RENDER_JS_LAYOUTS = (BASE / "render.js", BASE.parent / "visor_contratos" / "render.js")
# La hoja común de las cuatro webs (unidad 076). Como `render.js`, tiene un
# solo sitio vivo y dos layouts posibles: en el WORKSPACE cuelga de
# `docs/00-metodo/requisitos/base.css` (la reparte `bootstrap.py` junto a la
# plantilla del visor de flujos) y en el repo de código, de `visor/base.css`.
BASE_CSS_LAYOUTS = (BASE.parent / "base.css", BASE.parent / "visor" / "base.css")
# Por encima de este tope el adjunto se sirve truncado con un aviso: la 051 (R2) prometió
# que la web nunca vuelca salida extensa.
TOPE_ADJUNTO = 200 * 1024
# Margen de lectura sobre el tope: se leen unos bytes de más para que el recorte caiga
# dentro de un carácter multibyte sin inventarse el final, y NADA más. El fichero puede
# tener megas; el servidor nunca los carga.
MARGEN_ADJUNTO = 4 * 1024
# La MISMA frontera que `manifestar.SENSIBLE`, con las tiras acotadas. La alternativa de
# correo del manifiesto (`[\w.+-]+@...`) es cuadrática sobre cualquier tira larga sin `@`
# (una línea base64 de un SVG embebido, un `.min.js`): 20 KB tardaban 0,9 s y 200 KB
# decenas de segundos, así que un solo adjunto colgaba el servidor. Un campo del
# manifiesto son 2000 caracteres y ahí no se nota; un adjunto es un fichero de disco.
# El límite de 64 es el del local-part en RFC 5321: no se pierde ningún correo real.
SENSIBLE_ADJUNTO = re.compile(
    r"PRIVATE KEY|Authorization\s*:\s*Bearer|[\w.+-]{1,64}@[\w.-]{1,255}\.[A-Za-z]{2,24}",
    re.I,
)
# Extensión → content-type; el resto de código llega como texto plano y la
# página decide con la extensión si pinta markdown o código con números de línea.
CONTENT_TYPE_ADJUNTO = {".md": "text/markdown; charset=utf-8"}
PRIVADO = ".private"
REDACTADO = "[REDACTADO: dato sensible, no se sirve]"
AVISO_TRUNCADO = ("\n\n[ADJUNTO TRUNCADO: se muestran los primeros {tope} KB de "
                  "{total} KB. Abre el fichero en tu editor para verlo entero.]\n")


def ruta_render_js():
    """El motor, en el layout que toque: workspace primero, repo de código después."""
    for candidato in RENDER_JS_LAYOUTS:
        if candidato.is_file():
            return candidato
    return RENDER_JS_LAYOUTS[0]


def ruta_base_css():
    """La hoja común, en el layout que toque: workspace primero, repo después."""
    for candidato in BASE_CSS_LAYOUTS:
        if candidato.is_file():
            return candidato
    return BASE_CSS_LAYOUTS[0]


def detectar_workspace(datos):
    """Sube desde `datos` buscando la raíz del workspace (tiene `docs/` y
    `main/`, como este propio meta-repo): es la frontera de R5 para adjuntos.
    Si no aparece (fixtures de test u otros layouts), cae en `datos` mismo:
    los adjuntos sólo podrán vivir dentro de los propios datos servidos."""
    for candidato in (datos, *datos.parents):
        if (candidato / "docs").is_dir() and (candidato / "main").is_dir():
            return candidato
    return datos


def huella_datos(datos):
    """Identifica un directorio sin publicar su ruta local."""
    ruta = str(Path(datos).expanduser().resolve()).encode("utf-8")
    return hashlib.sha256(b"visor-presentaciones\0" + ruta).hexdigest()


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


def _adjuntos_declarados(manifiesto):
    """Todas las rutas de `adjuntos` declaradas en el manifiesto (R4): sólo se
    sirve lo que el propio manifiesto valida, nunca una ruta adivinada."""
    return {
        ruta
        for p in manifiesto["presentaciones"]
        for ruta in p.get("adjuntos", [])
    }


def _ruta_de_adjunto(workspace, ruta):
    """Resuelve el adjunto dentro de `workspace` o rechaza (R5): `..`, ruta
    absoluta o enlace simbólico que escape se tratan igual — 403, nada leído."""
    if ".." in ruta.split("/") or ruta.startswith(("/", "~")):
        raise ValueError("ruta de adjunto insegura")
    resuelta = (workspace / ruta).resolve(strict=True)
    raiz = workspace.resolve(strict=True)
    try:
        relativa = resuelta.relative_to(raiz)
    except ValueError:
        raise ValueError("adjunto fuera del workspace")
    # `.private/` es la carpeta de evidencia sensible del método: está DENTRO del
    # workspace, así que la frontera de R5 no la para. Se mira la ruta ya resuelta
    # porque a ella se llega también por un enlace que no sale del workspace.
    if PRIVADO in relativa.parts:
        raise ValueError("adjunto en .private/")
    return resuelta


def filtrar_adjunto(texto, total=None):
    """El cuerpo que se sirve: recortado al tope PRIMERO y luego tachado.

    Misma frontera que el manifiesto (`manifestar.SENSIBLE`, unidad 051 R2/R5): un
    adjunto no puede ser la puerta trasera por la que salen las credenciales o media
    hora de logs que el manifiesto no habría dejado pasar.

    El orden importa y no es cosmético: filtrar antes de recortar hacía que el tope
    acotara lo que se ENVÍA pero no lo que se PROCESA, y la regex corría sobre el
    fichero entero. `total` es el tamaño real en disco, para que el aviso siga diciendo
    la verdad aunque aquí sólo haya llegado el primer trozo.
    """
    crudo = texto.encode("utf-8")
    total = len(crudo) if total is None else total
    if total <= TOPE_ADJUNTO:
        return SENSIBLE_ADJUNTO.sub(REDACTADO, texto).encode("utf-8")
    recorte = crudo[:TOPE_ADJUNTO].decode("utf-8", errors="ignore")
    aviso = AVISO_TRUNCADO.format(tope=TOPE_ADJUNTO // 1024, total=total // 1024)
    return (SENSIBLE_ADJUNTO.sub(REDACTADO, recorte) + aviso).encode("utf-8")


def hacer_handler(datos, estado, workspace=None):
    datos = Path(datos).resolve()
    workspace = Path(workspace).resolve() if workspace is not None else detectar_workspace(datos)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            estado["ultimo"] = time.time()
            ruta = urlsplit(self.path).path
            if ruta in ("/", "/index.html"):
                return self._fichero(PLANTILLA, "text/html; charset=utf-8")
            if ruta == "/render.js":
                # Motor de bloques compartido con el visor de contratos
                # (unidad 056, bug 055): un solo fichero, sin copia.
                return self._fichero(ruta_render_js(), "text/javascript; charset=utf-8")
            if ruta == "/base.css":
                # Hoja común de las cuatro webs (unidad 076).
                return self._fichero(ruta_base_css(), "text/css; charset=utf-8")
            if ruta == "/meta.json":
                return self._json(200, {
                    "servicio": "visor-presentaciones",
                    "huella_datos": huella_datos(datos),
                })
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
            if ruta.startswith("/adjunto/"):
                return self._adjunto(ruta[len("/adjunto/"):])
            return self._json(404, {"error": "ruta inexistente"})

        def _adjunto(self, ruta_cruda):
            # R5: fuera del workspace, `..`, absoluta o symlink que escape →
            # 403 y nada leído. No declarado en el manifiesto → 404: no es una
            # puerta a cualquier fichero del workspace, sólo a lo validado.
            ruta = unquote(ruta_cruda)
            try:
                manifiesto = _leer_manifiesto(datos)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})
            if ruta not in _adjuntos_declarados(manifiesto):
                return self._json(404, {"error": "adjunto no declarado"})
            try:
                resuelta = _ruta_de_adjunto(workspace, ruta)
            except (ValueError, OSError):
                return self._json(403, {"error": "adjunto fuera del workspace"})
            tipo = CONTENT_TYPE_ADJUNTO.get(Path(ruta).suffix.lower(), "text/plain; charset=utf-8")
            try:
                # El adjunto se lee como texto (es lo que la web pinta) y sale por
                # el mismo filtro que el manifiesto: nada crudo llega al navegador.
                # Se leen como mucho el tope y el margen: un fichero de megas ni se
                # carga en memoria ni se filtra entero (el tope acota el COSTE).
                total = resuelta.stat().st_size
                with resuelta.open("rb") as fichero:
                    crudo = fichero.read(TOPE_ADJUNTO + MARGEN_ADJUNTO)
            except OSError:
                return self._json(404, {"error": "adjunto ilegible"})
            cuerpo = filtrar_adjunto(crudo.decode("utf-8", errors="replace"), total)
            return self._fichero(resuelta, tipo, cuerpo)

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

        def _fichero(self, ruta, tipo, cuerpo=None):
            # Un fichero que falta es un 404, jamás una excepción que suba hasta
            # `do_GET`: eso cortaba la conexión sin respuesta y el navegador se
            # quedaba con la página a medias (bug 064 R2).
            if cuerpo is None:
                try:
                    cuerpo = Path(ruta).read_bytes()
                except OSError:
                    return self._json(404, {"error": "fichero inexistente"})
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
    p.add_argument("--workspace", help="raíz del meta-repo/main para servir adjuntos; se detecta sola si se omite")
    p.add_argument("--puerto", type=int, default=8767)
    p.add_argument("--sin-navegador", action="store_true")
    args = p.parse_args()
    datos = Path(args.datos).resolve()
    _leer_manifiesto(datos)
    workspace = Path(args.workspace).resolve() if args.workspace else None
    servidor = ServidorPresentaciones(
        ("127.0.0.1", args.puerto), hacer_handler(datos, {"ultimo": time.time()}, workspace)
    )
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
