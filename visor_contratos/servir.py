#!/usr/bin/env python3
"""Visor local de los contratos de trabajo (una unidad = un `especificacion.md`).

Desde la unidad 081 esto NO es un servidor: es el módulo de datos del apartado
«Contratos» de la web única. `web/servir.py` importa `hacer_handler` y monta estas
rutas bajo `/contratos/`.

Sirve las unidades del meta-repo (``docs/05-trabajo/<NNN-slug>/especificacion.md``)
para leerlas en BLUF desde el navegador. Aprobar o pedir cambios sigue siendo por
conversación con el agente: aquí sólo se lee. Y sigue dejando el rastro por contrato
mostrado en `.runtime/visor-contratos.log`, que es lo que `unidad.py despachar` exige.
"""

import http.server
import json
import os
import re
import socket
import sys
import time
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
# La hoja común de las cuatro webs (unidad 076). Ruta resuelta desde el módulo,
# nunca desde el cwd: el visor se lanza desde donde le da la gana al usuario.
# Dos layouts (bug 080), igual que en el visor de presentaciones: en el WORKSPACE este
# fichero cuelga de `docs/00-metodo/requisitos/visor_contratos/` y la hoja está en
# `requisitos/base.css`; en el repo de código, en `visor/base.css`.
BASE_CSS_LAYOUTS = (os.path.join(os.path.dirname(BASE), "base.css"),
                    os.path.join(os.path.dirname(BASE), "visor", "base.css"))


def ruta_base_css():
    """La hoja común, en el layout que toque: workspace primero, repo después."""
    for candidato in BASE_CSS_LAYOUTS:
        if os.path.isfile(candidato):
            return candidato
    return BASE_CSS_LAYOUTS[0]


BASE_CSS = ruta_base_css()
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


LINEA_APROBADO = re.compile(r"^aprobado:[^\n]*$", re.M)


def aprobar_contrato(workspace, nombre, quien="usuario (web)"):
    """Escribe `aprobado: <hoy>` en el frontmatter del contrato y deja rastro.

    Es la aprobación del USUARIO desde la web (iteración rápida del 26-08, alcance de la
    unidad 091): el agente nunca llama a esto. Conserva el comentario guía de la línea.
    """
    ruta = ruta_contrato(workspace, nombre)
    if not ruta:
        raise FileNotFoundError(nombre)
    hoy = time.strftime("%Y-%m-%d")
    texto = Path(ruta).read_text(encoding="utf-8")
    if not LINEA_APROBADO.search(texto):
        raise ValueError("el contrato no tiene línea aprobado:")
    texto = LINEA_APROBADO.sub(
        "aprobado: %s      # aprobado desde la web por el %s" % (hoy, quien), texto, count=1)
    Path(ruta).write_text(texto, encoding="utf-8")
    registro = Path(workspace) / ".runtime" / RASTRO
    registro.parent.mkdir(parents=True, exist_ok=True)
    with open(registro, "a", encoding="utf-8") as rastro:
        rastro.write("%s contrato aprobado desde la web: %s\n"
                     % (time.strftime("%Y-%m-%dT%H:%M:%S"), nombre))
    return hoy


def pedir_cambios(workspace, nombre, comentario):
    """Añade al final del contrato una sección fechada con lo que el usuario pide.

    El agente la lee al arrancar (la ficha es la fuente); no toca el frontmatter.
    """
    ruta = ruta_contrato(workspace, nombre)
    if not ruta:
        raise FileNotFoundError(nombre)
    comentario = (comentario or "").strip()
    if not comentario:
        raise ValueError("comentario vacío")
    cuando = time.strftime("%Y-%m-%d %H:%M")
    with open(ruta, "a", encoding="utf-8") as f:
        f.write("\n\n## Cambios pedidos desde la web (%s)\n\n%s\n" % (cuando, comentario))
    return cuando


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
                # Hoja común de las cuatro webs (unidad 076), en el layout que toque.
                self._fichero(ruta_base_css(), "text/css; charset=utf-8")
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
            pedida = urlsplit(self.path).path
            m = re.match(r"^/(aprobar|pedir-cambios)/(\d{3}-[a-z0-9][a-z0-9-]*)$", pedida)
            if not m:
                return self._json(404, {"error": "ruta inexistente"})
            accion, nombre = m.group(1), m.group(2)
            try:
                largo = int(self.headers.get("Content-Length") or 0)
                cuerpo = json.loads(self.rfile.read(largo) or b"{}") if largo else {}
                if accion == "aprobar":
                    fecha = aprobar_contrato(workspace, nombre)
                    return self._json(200, {"unidad": nombre, "aprobado": fecha})
                cuando = pedir_cambios(workspace, nombre, cuerpo.get("comentario", ""))
                return self._json(200, {"unidad": nombre, "anotado": cuando})
            except FileNotFoundError:
                return self._json(404, {"error": "no hay contrato de " + nombre})
            except (ValueError, OSError) as exc:
                return self._json(400, {"error": str(exc)})

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

# 081: este fichero dejó de ser un programa. Es el MÓDULO DE DATOS del apartado
# «Contratos» de la web única: `web/servir.py` importa `hacer_handler` y le monta
# estas mismas rutas bajo `/contratos/`. El rastro por contrato mostrado
# (`.runtime/visor-contratos.log`, que `unidad.py despachar` exige) lo sigue
# escribiendo `anotar_apertura`, aquí, con el mismo formato.
