#!/usr/bin/env python3
"""Visor local de los contratos de trabajo (una unidad = un `especificacion.md`).

Mismo patrón que ``visor/servir.py`` — ThreadingHTTPServer en 127.0.0.1,
estrictamente de sólo lectura, sin caché — pero con plantilla y rutas propias:
NO toca el visor de flujos ni su esquema de planos.

Sirve las unidades del meta-repo (``docs/05-trabajo/<NNN-slug>/especificacion.md``)
para leerlas en BLUF desde el navegador. Aprobar o pedir cambios sigue siendo por
conversación con el agente: aquí sólo se lee.

Uso:
    python3 visor_contratos/servir.py --workspace <ruta del meta-repo>
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
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
# El nombre de unidad es el de las carpetas de trabajo: NNN-slug. Al ser el
# único patrón aceptado, la ruta no puede escaparse del workspace (ni `..`, ni
# separadores, ni rutas absolutas llegan a tocar el sistema de ficheros).
RUTA_CONTRATO = re.compile(r"^/contrato/(\d{3}-[a-z0-9][a-z0-9-]*)\.md$")
NOMBRE_UNIDAD = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COMENTARIO = re.compile(r"\s+#")
CAMPOS = ("unidad", "tipo", "carril", "estado", "aprobado", "actividad")

BASE = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(BASE, "plantilla.html")
RENDER_JS = os.path.join(BASE, "render.js")
# La hoja común de las cuatro webs (unidad 076): se lee de visor/, su único
# sitio, igual que `render.js` se lee de aquí. Ruta resuelta desde el módulo,
# nunca desde el cwd: el visor se lanza desde donde le da la gana al usuario.
BASE_CSS = os.path.join(os.path.dirname(BASE), "visor", "base.css")
SUBRUTA_TRABAJO = ("docs", "05-trabajo")
SUBRUTA_BUGS = ("docs", "bugs")
RASTRO = "visor-contratos.log"


class ServidorVisorContratos(http.server.ThreadingHTTPServer):
    """Mismo bind exclusivo que el visor de flujos: en Windows SO_REUSEADDR deja
    que un segundo visor robe un puerto ya en uso (bug del puerto 8765)."""

    allow_reuse_address = False

    def server_bind(self):
        if sys.platform == "win32":
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        http.server.HTTPServer.server_bind(self)


def carpeta_trabajo(workspace):
    return os.path.join(workspace, *SUBRUTA_TRABAJO)


def carpeta_bugs(workspace):
    return os.path.join(workspace, *SUBRUTA_BUGS)


def anotar_apertura(workspace, nombre):
    """Deja fechado el rastro de que este contrato se sirvió a alguien.

    Mismo criterio que `visor/requisitos.py anotar_apertura` (unidad 033, R3): se anota
    POR CONTRATO MOSTRADO, también cuando el servidor ya estaba levantado desde antes — si
    solo se anotara al arrancar, releer un contrato en un visor abierto desde ayer no
    contaría como haberlo visto hoy, y `unidad.py despachar` bloquearía el camino legítimo.
    """
    registro = Path(workspace) / ".runtime" / RASTRO
    registro.parent.mkdir(parents=True, exist_ok=True)
    with open(registro, "a", encoding="utf-8") as rastro:
        rastro.write(
            "%s contrato mostrado: %s\n"
            % (time.strftime("%Y-%m-%dT%H:%M:%S"), nombre)
        )
    return registro


def leer_frontmatter(texto):
    """Los pocos campos escalares del frontmatter de una especificación.

    Deliberadamente mínimo (no es un parser de YAML): las listas y los bloques
    multilínea no se usan aquí y se ignoran sin romper.
    """
    campos = {}
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        return campos
    for linea in lineas[1:]:
        if linea.strip() == "---":
            break
        if ":" not in linea or linea.startswith((" ", "\t", "#", "-")):
            continue
        clave, _, valor = linea.partition(":")
        clave = clave.strip()
        if clave in CAMPOS:
            # Las especificaciones nacen de la plantilla y conservan el
            # comentario guía a la derecha del valor
            # (`aprobado: 2026-08-13   # LO PONE EL USUARIO…`): es comentario
            # YAML, no parte del dato. Sin recortarlo, una unidad aprobada
            # aparecería como pendiente.
            valor = COMENTARIO.split(valor, 1)[0]
            campos[clave] = valor.strip().strip('"').strip("'")
    return campos


def listar_trabajo(workspace):
    """Todas las unidades activas de `docs/05-trabajo/`, en orden de número.

    Nunca se oculta una unidad: si le falta el frontmatter, o la fecha de
    aprobación, sale igualmente marcada como pendiente de aprobar.
    """
    raiz = carpeta_trabajo(workspace)
    unidades = []
    try:
        nombres = sorted(os.listdir(raiz))
    except OSError:
        return unidades
    for nombre in nombres:
        # `archivo/`, `peticiones/` y `ESTADO.md` conviven aquí y no son unidades.
        if not NOMBRE_UNIDAD.match(nombre):
            continue
        ruta = os.path.join(raiz, nombre, "especificacion.md")
        if not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                campos = leer_frontmatter(f.read())
        except OSError:
            campos = {}
        aprobado = campos.get("aprobado", "")
        unidades.append({
            "unidad": campos.get("unidad") or nombre,
            "carpeta": nombre,
            "tipo": campos.get("tipo", ""),
            "carril": campos.get("carril", ""),
            "estado": campos.get("estado", ""),
            "actividad": campos.get("actividad", ""),
            "aprobado": aprobado,
            "pendiente_de_aprobar": not FECHA.match(aprobado),
            "origen": "trabajo",
        })
    return unidades


def listar_bugs(workspace):
    """Los bugs de `docs/bugs/*.md` que TODAVÍA piden un OK del usuario (R5, bug 054):
    `aprobado: no` (o sin fecha) y los `estado: planificada`.

    `docs/bugs/` es el historial completo (ADR-006, no se archiva); listarlo entero
    ahogaría los pendientes entre docenas de bugs ya `mergeada` con fecha de
    aprobación antigua (hueco H2 de la ronda 2 de revisión). Un fichero de bug ES el
    contrato entero: a diferencia de una unidad, no vive en una carpeta con
    `especificacion.md` sino como `NNN-slug.md` suelto junto a `INDICE.md` y otros
    ficheros de soporte, que se descartan por no casar NNN-slug.
    """
    raiz = carpeta_bugs(workspace)
    bugs = []
    try:
        nombres = sorted(os.listdir(raiz))
    except OSError:
        return bugs
    for nombre in nombres:
        if not nombre.endswith(".md"):
            continue
        base = nombre[:-3]
        if not NOMBRE_UNIDAD.match(base):
            continue  # INDICE.md y demás soporte: no son fichas de bug
        ruta = os.path.join(raiz, nombre)
        if not os.path.isfile(ruta):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                campos = leer_frontmatter(f.read())
        except OSError:
            campos = {}
        aprobado = campos.get("aprobado", "")
        estado = campos.get("estado", "")
        pendiente_de_aprobar = not FECHA.match(aprobado)
        if not pendiente_de_aprobar and estado != "planificada":
            continue  # ya aprobado y en marcha o cerrado: no pide un OK hoy
        bugs.append({
            "unidad": campos.get("unidad") or base,
            "carpeta": base,
            "tipo": campos.get("tipo", ""),
            "carril": campos.get("carril", ""),
            "estado": estado,
            "actividad": campos.get("actividad", ""),
            "aprobado": aprobado,
            "pendiente_de_aprobar": pendiente_de_aprobar,
            "origen": "bug",
        })
    return bugs


def listar_unidades(workspace):
    """Unidades de `docs/05-trabajo/` Y bugs de `docs/bugs/`: los dos sitios donde se pide
    un OK (R5, bug 054) — ninguno de los dos se oculta."""
    return sorted(
        listar_trabajo(workspace) + listar_bugs(workspace),
        key=lambda u: u["carpeta"],
    )


def ruta_contrato(workspace, nombre):
    """Ruta del contrato de `nombre`: primero como unidad, si no, como bug (R5)."""
    candidata = os.path.join(carpeta_trabajo(workspace), nombre, "especificacion.md")
    if os.path.isfile(candidata):
        return candidata
    candidata = os.path.join(carpeta_bugs(workspace), nombre + ".md")
    if os.path.isfile(candidata):
        return candidata
    return None


def hacer_handler(workspace, estado):
    class VisorContratos(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            estado["ultimo"] = time.time()
            pedida = urlsplit(self.path).path
            if pedida in ("/", "/index.html"):
                self._fichero(PLANTILLA, "text/html; charset=utf-8")
            elif pedida == "/render.js":
                # Motor de bloques compartido con el visor de presentaciones
                # (unidad 056): un solo fichero, sin copia (bug 055).
                self._fichero(RENDER_JS, "text/javascript; charset=utf-8")
            elif pedida == "/base.css":
                # Hoja común de las cuatro webs (unidad 076).
                self._fichero(BASE_CSS, "text/css; charset=utf-8")
            elif pedida == "/meta.json":
                self._json(200, {"workspace": workspace})
            elif pedida == "/unidades.json":
                # Se relee en cada petición: la página lo sondea sola.
                self._json_seguro(listar_unidades)
            elif RUTA_CONTRATO.match(pedida):
                nombre = RUTA_CONTRATO.match(pedida).group(1)
                ruta = ruta_contrato(workspace, nombre)
                if ruta:
                    # R2 (bug 054): rastro por contrato mostrado, mismo criterio que el
                    # visor de flujos — se anota SIEMPRE que se sirve, no solo al arrancar.
                    anotar_apertura(workspace, nombre)
                    self._fichero(ruta, "text/markdown; charset=utf-8")
                else:
                    self.send_error(404, "No hay contrato de la unidad " + nombre)
            else:
                self._json(404, {"error": "ruta inexistente"})

        def do_POST(self):
            estado["ultimo"] = time.time()
            return self._json(
                405,
                {
                    "error": (
                        "visor de solo lectura; aprobar el contrato o pedir "
                        "cambios se sigue haciendo hablando con el agente"
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
            # La página sondea este endpoint: un fallo leyendo el workspace debe
            # viajar como JSON, nunca matar la conexión.
            try:
                self._json(200, {"workspace": workspace, "unidades": funcion(workspace)})
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

    return VisorContratos


def main():
    p = argparse.ArgumentParser(description="Visor local de los contratos de trabajo")
    p.add_argument("--workspace", required=True,
                   help="Ruta del meta-repo (el que tiene docs/05-trabajo/)")
    p.add_argument("--minutos", type=float, default=0,
                   help="minutos sin actividad antes de apagarse; 0 = no caduca")
    p.add_argument("--puerto", type=int, default=8766,
                   help="puerto local; 0 pide uno libre (defecto: 8766)")
    p.add_argument("--sin-navegador", action="store_true", help="No abrir el navegador")
    args = p.parse_args()

    if not (0 <= args.minutos <= 1440):
        sys.exit("--minutos debe estar entre 0 y 1440")
    if not (0 <= args.puerto <= 65535):
        sys.exit("--puerto debe estar entre 0 y 65535")

    workspace = os.path.abspath(args.workspace)
    trabajo = carpeta_trabajo(workspace)
    if not os.path.isdir(trabajo):
        sys.exit("No existe la carpeta de unidades: " + trabajo)
    if not os.path.isfile(PLANTILLA):
        sys.exit("Falta la plantilla: " + PLANTILLA)
    if not os.path.isfile(RENDER_JS):
        sys.exit("Falta el motor de render: " + RENDER_JS)

    estado = {"ultimo": time.time()}
    try:
        servidor = ServidorVisorContratos(
            ("127.0.0.1", args.puerto), hacer_handler(workspace, estado)
        )
    except OSError as exc:
        sys.exit("No pude abrir el puerto %d: %s" % (args.puerto, exc))
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()

    url = "http://127.0.0.1:%d/" % puerto
    print("Visor de contratos levantado: %s" % url, flush=True)
    print("Unidades: %s (%d encontradas, se releen al recargar)"
          % (trabajo, len(listar_unidades(workspace))), flush=True)
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
    print("Visor de contratos cerrado.", flush=True)


if __name__ == "__main__":
    main()
