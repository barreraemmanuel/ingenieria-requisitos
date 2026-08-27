#!/usr/bin/env python3
"""La web del método: UN servidor, UNA dirección, cuatro apartados (unidad 081).

Hasta la 080 había cuatro webs en cuatro puertos, con tres lanzadores y una barra
que enlazaba a `http://127.0.0.1:8766/` y compañía: navegar entre ellas era saltar
de servidor. Aquí hay un solo `ThreadingHTTPServer` y una tabla de prefijos:

    GET /                       el tablero (la portada)
    GET /contratos              los contratos de trabajo
    GET /presentaciones         la validación guiada (la última, o /<unidad>)
    GET /flujos                 los planos de la aplicación
    GET /<apartado>/<dato>      los datos de ese apartado, tal cual los daba su visor
    GET /render.js /base.css    el motor de bloques y la hoja común, una sola copia
    GET /meta.json              identidad del servicio, para `abrir.py`
    GET /api/huella             la huella de lo que se está mirando (unidad 107)

Y TRES escrituras, ni una más (unidades 091 y 107), que dispara el USUARIO con un
clic y nunca el agente:

    POST /contratos/aprobar/<NNN-slug>   `aprobado:` + `aprobado_por:` + rastro
    POST /api/aprobar-planos             lo mismo que `requisitos aprobar`
    POST /api/validar-ok                 el OK final de una validación guiada

Las tres llaman a la función que YA escribía eso desde el comando: la web no tiene
un segundo escritor para el mismo fichero. Las tres exigen cliente local, y admiten
la huella de lo que se sirvió: si el fichero cambió desde entonces, se manda releer.
Con `--solo-lectura` las tres responden 405 y ningún botón se pinta.

Los cuatro visores anteriores siguen siendo los dueños de sus datos y de sus
rastros: esta cáscara IMPORTA su `hacer_handler` y le delega la petición con la
ruta ya sin prefijo. Por eso las tres puertas duras del método (`despachar`,
`aprobar`, `cerrar`) siguen encontrando exactamente los mismos ficheros.

Uso:
    python3 web/servir.py --workspace <ruta del meta-repo>
"""

import argparse
import email.message
import hashlib
import http.server
import importlib.util
import io
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
CASCARA = BASE / "plantilla.html"
SERVICIO = "web-metodo"
PUERTO_BASE = 8770
RASTRO_FLUJOS = "visor-%d.log"
NOMBRE_UNIDAD = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")

# --------------------------------------------------- unidad 107: aprobar desde la web
# Quien aprueba, escrito igual en los tres sitios: la ficha, el recibo de los planos y
# el rastro. Si esto cambia, cambia en un solo sitio.
QUIEN = "usuario (web)"
# El rastro de cada clic, que es lo que `unidad.py despachar` exige desde la 107 (R5).
CARPETA_APROBACIONES = ".runtime/aprobaciones"
API_HUELLA = "/api/huella"
API_APROBAR_PLANOS = "/api/aprobar-planos"
API_VALIDAR_OK = "/api/validar-ok"
RUTA_APROBAR_CONTRATO = re.compile(r"^/contratos/aprobar/(\d{3}-[a-z0-9][a-z0-9-]*)$")
RUTA_PEDIR_CAMBIOS = re.compile(r"^/contratos/pedir-cambios/(\d{3}-[a-z0-9][a-z0-9-]*)$")
RUTA_DECISIONES = re.compile(r"^/presentaciones/\d{3}-[a-z0-9][a-z0-9-]*/decisiones$")
LINEA_APROBADO = re.compile(r"^aprobado:\s*(\d{4}-\d{2}-\d{2})", re.M)
LINEA_APROBADO_POR = re.compile(r"^aprobado_por:[^\n]*$", re.M)
CUALQUIER_APROBADO = re.compile(r"^aprobado:[^\n]*$", re.M)
MENSAJE_RELEER = ("lo que tienes delante ya no es lo que hay en disco: relee la página "
                  "antes de aprobar (recárgala y vuelve a pulsar)")


def cliente_local(direccion):
    """¿La petición viene de esta misma máquina?

    El bind a `127.0.0.1` ya lo garantiza hoy, pero el bind es configuración y esto es
    la REGLA: si alguien sirviera en `0.0.0.0`, aquí es donde se sigue diciendo que no.
    """
    if not direccion:
        return False
    ip = direccion[0] if isinstance(direccion, (tuple, list)) else str(direccion)
    return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def es_escritura(pedida):
    """Las rutas que ESCRIBEN. Todo lo demás de la web sigue siendo de lectura."""
    return bool(
        RUTA_APROBAR_CONTRATO.match(pedida)
        or RUTA_PEDIR_CAMBIOS.match(pedida)
        or RUTA_DECISIONES.match(pedida)
        or pedida in (API_APROBAR_PLANOS, API_VALIDAR_OK)
    )


def huella_fichero(ruta):
    """SHA-256 del fichero tal cual se sirvió: la huella que el POST trae de vuelta."""
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def fecha_aprobado(texto):
    """La fecha de `aprobado:` si ya la hay; `None` si el contrato sigue pendiente."""
    hallado = LINEA_APROBADO.search(texto)
    return hallado.group(1) if hallado else None


def anotar_aprobado_por(ruta, quien=QUIEN):
    """`aprobado_por: usuario (web)` como CAMPO del frontmatter, no como comentario.

    La 091 dejaba el «quién» dentro del comentario YAML de la línea `aprobado:`; eso lo
    lee una persona, pero no un script. Se escribe justo debajo, y si ya estaba se pisa.
    """
    ruta = Path(ruta)
    texto = ruta.read_text(encoding="utf-8")
    linea = "aprobado_por: %s" % quien
    if LINEA_APROBADO_POR.search(texto):
        texto = LINEA_APROBADO_POR.sub(linea, texto, count=1)
    else:
        hallado = CUALQUIER_APROBADO.search(texto)
        if not hallado:
            return None
        texto = texto[:hallado.end()] + "\n" + linea + texto[hallado.end():]
    ruta.write_text(texto, encoding="utf-8")
    return linea


def escribir_rastro_aprobacion(workspace, que, ruta, huella, cliente, extra=None):
    """El rastro del clic: `.runtime/aprobaciones/<que>-<fecha>.json`.

    Cuatro datos, que son los que hacen falta para volver a mirarlo dentro de un año:
    QUÉ se aprobó (ruta), QUÉ decía entonces (huella), CUÁNDO y QUIÉN estaba delante.
    Es lo que lee `unidad.py despachar` (unidad 107, R5).
    """
    hoy = time.strftime("%Y-%m-%d")
    carpeta = Path(workspace) / CARPETA_APROBACIONES
    datos = {"unidad": que, "fecha": hoy, "ruta": str(ruta), "huella": huella,
             "hora": time.strftime("%Y-%m-%dT%H:%M:%S"), "cliente": cliente,
             "aprobado_por": QUIEN}
    datos.update(extra or {})
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / ("%s-%s.json" % (que, hoy))
        destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    except OSError:
        return None
    return destino

# Los cuatro apartados, en el orden de la barra común (desde la 076):
# (clave, ruta, rótulo, marca de la cabecera).
# Unidad 121: los rótulos son los que lee una persona que no conoce el método.
# «Tablero» no decía qué era ni que fuese la portada; «Presentaciones» no decía
# que ahí te toca probar algo. La clave interna (`tablero`, `presentaciones`) NO
# cambia: es la que enrutan `web/abrir.py` y los lanzadores del método.
APARTADOS = (
    ("tablero", "/", "Inicio"),
    ("contratos", "/contratos", "Contratos"),
    ("presentaciones", "/presentaciones", "Entregas"),
    ("flujos", "/flujos", "Flujos"),
)
CLAVES = tuple(clave for clave, _, _ in APARTADOS)

# Dónde vive el módulo de datos y su plantilla, en los DOS layouts posibles: en el
# repo de código cada visor conserva su carpeta; en el workspace del alumno todo
# viaja aplanado a `docs/00-metodo/requisitos/web/` (ARCHIVOS_WEB del bootstrap).
# Mismo idioma que los `*_LAYOUTS` de los visores: se busca, no se adivina.
LAYOUTS = {
    "flujos": (("datos_flujos.py", "flujos.html"),
               (("..", "visor", "servir.py"), ("..", "visor", "plantilla.html"))),
    "contratos": (("datos_contratos.py", "contratos.html"),
                  (("..", "visor_contratos", "servir.py"),
                   ("..", "visor_contratos", "plantilla.html"))),
    "presentaciones": (("datos_presentaciones.py", "presentaciones.html"),
                       (("..", "visor_presentaciones", "servir.py"),
                        ("..", "visor_presentaciones", "plantilla.html"))),
    "tablero": (("datos_tablero.py", "tablero.html"),
                (("..", "visor_tablero", "servir.py"),
                 ("..", "visor_tablero", "plantilla.html"))),
}
# `render.js` y `base.css` tienen UN solo sitio vivo y dos layouts (bugs 055 y 064).
RENDER_JS_LAYOUTS = (BASE / "render.js", BASE.parent / "visor_contratos" / "render.js")
BASE_CSS_LAYOUTS = (BASE / "base.css", BASE.parent / "visor" / "base.css")

# Datos que cada apartado sirve directamente (sin seleccionar unidad): lo que va
# detrás de `/presentaciones/` y no es uno de estos es el nombre de una unidad.
DATOS_PRESENTACIONES = ("manifiesto.json", "recibos.json", "adjunto",
                        "presentacion", "decisiones", "meta.json", "render.js",
                        "base.css")


def _primera(candidatas):
    for candidata in candidatas:
        if Path(candidata).is_file():
            return Path(candidata)
    return Path(candidatas[0])


def ruta_modulo(cual):
    plano, anidado = LAYOUTS[cual]
    return _primera((BASE / plano[0], BASE.joinpath(*anidado[0])))


def ruta_plantilla(cual):
    plano, anidado = LAYOUTS[cual]
    return _primera((BASE / plano[1], BASE.joinpath(*anidado[1])))


def ruta_render_js():
    return _primera(RENDER_JS_LAYOUTS)


def ruta_base_css():
    return _primera(BASE_CSS_LAYOUTS)


def huella_workspace(workspace):
    """Identifica el workspace servido sin publicar su ruta local."""
    ruta = str(Path(workspace).expanduser().resolve()).encode("utf-8")
    return hashlib.sha256(b"web-metodo\0" + ruta).hexdigest()


def cargar_modulo(cual):
    """Importa el módulo de datos de un apartado, con SU carpeta en el path.

    Los cuatro traen sus propias dependencias por nombre suelto (`revision`,
    `manifestar`, `estado`): en el repo están en su carpeta y en el workspace, en
    `requisitos/` o al lado. Se añaden las dos y se quitan al terminar.
    """
    ruta = ruta_modulo(cual)
    carpeta = ruta.parent
    añadidas = [str(carpeta), str(carpeta.parent)]
    sys.path[:0] = añadidas
    try:
        spec = importlib.util.spec_from_file_location("web_datos_%s" % cual, ruta)
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = modulo
        spec.loader.exec_module(modulo)
        return modulo
    finally:
        for entrada in añadidas:
            try:
                sys.path.remove(entrada)
            except ValueError:
                pass


# ------------------------------------------------------------------ la cáscara

MARCADORES = ("estilos", "barra", "cuerpo", "guion")


def _entre(texto, marca):
    """Lo que hay entre `<!-- apartado:X -->` y `<!-- /apartado:X -->`."""
    inicio = "<!-- apartado:%s -->" % marca
    fin = "<!-- /apartado:%s -->" % marca
    i = texto.find(inicio)
    j = texto.find(fin)
    if i < 0 or j < 0:
        return ""
    return texto[i + len(inicio):j]


def barra(actual, cascara=None):
    """La barra común de los cuatro apartados, con el actual marcado.

    El marcado sale de `<template id="barra-comun">` de la cáscara: un solo sitio
    donde están escritos los cuatro enlaces, y son rutas relativas del mismo
    origen (R2). Aquí sólo se marca cuál se está sirviendo.
    """
    texto = cascara if cascara is not None else CASCARA.read_text(encoding="utf-8")
    i = texto.find('<template id="barra-comun">')
    if i < 0:
        return ""
    i = texto.index(">", i) + 1
    j = texto.index("</template>", i)
    nav = texto[i:j].strip("\n")
    return nav.replace('data-web="%s"' % actual,
                       'data-web="%s" class="actual" aria-current="page"' % actual)


def pagina(actual, base, cuerpo_alternativo=None, titulo=None,
           solo_lectura=False):
    """La página completa de un apartado: cáscara + su sección.

    Las plantillas de los cuatro visores siguen siendo documentos válidos por su
    cuenta (sus tests las abren tal cual); de ellas se recortan por marcadores las
    tres piezas que la cáscara monta: estilos propios, cuerpo y guion.
    """
    cascara = CASCARA.read_text(encoding="utf-8")
    if cuerpo_alternativo is None:
        plantilla = ruta_plantilla(actual).read_text(encoding="utf-8")
        piezas = {marca: _entre(plantilla, marca) for marca in MARCADORES}
    else:
        piezas = {"estilos": "", "barra": "", "cuerpo": cuerpo_alternativo,
                  "guion": ""}
    contexto = json.dumps({"apartado": actual, "base": base,
                           "solo_lectura": bool(solo_lectura)}, ensure_ascii=False)
    nav = barra(actual, cascara)
    # El `<template>` es la FUENTE de la barra, no contenido de la página: si
    # viajara al navegador, cada página llevaría la barra dos veces en el DOM.
    inicio = cascara.find('<template id="barra-comun">')
    if inicio >= 0:
        fin = cascara.index("</template>", inicio) + len("</template>\n")
        cascara = cascara[:inicio] + cascara[fin:]
    return (cascara
            .replace("<!--{TITULO}-->", titulo or _rotulo(actual))
            .replace("<!--{CONTEXTO}-->",
                     "<script>window.IR = %s;</script>" % contexto)
            .replace("<!--{ESTILOS}-->", piezas["estilos"])
            .replace("<!--{CUERPO}-->",
                     piezas["cuerpo"].replace("<!-- apartado:barra -->", nav))
            .replace("<!--{GUION}-->", piezas["guion"])
            ).encode("utf-8")


def _rotulo(clave):
    for otra, _, rotulo in APARTADOS:
        if otra == clave:
            return rotulo
    return clave


CUERPO_SIN_PLANOS = """
  <div class="pagina">
    <header>
      <button type="button" id="boton-tema" class="boton-tema" aria-label="Cambiar entre claro y oscuro"></button>
      <!-- apartado:barra -->
      <div class="marca">ingeniería de requisitos · flujos</div>
      <h1>Todavía no hay planos</h1>
      <div class="sub">Este proyecto aún no tiene <code>docs/02-flujos/planos/planos.json</code>.</div>
    </header>
    <div class="cuerpo">
      <main class="panel">
        <div class="vacio">Aquí no hay planos que enseñar todavía. Cuando el analista
        de flujos escriba el mapa, este apartado se llena solo. Mientras tanto, los
        otros tres apartados funcionan: <a href="/">Inicio</a>,
        <a href="/contratos">Contratos</a> y
        <a href="/presentaciones">Presentaciones</a>.</div>
      </main>
    </div>
  </div>
"""

CUERPO_404 = """
  <div class="pagina">
    <header>
      <button type="button" id="boton-tema" class="boton-tema" aria-label="Cambiar entre claro y oscuro"></button>
      <!-- apartado:barra -->
      <div class="marca">ingeniería de requisitos</div>
      <h1>Aquí no hay nada</h1>
      <div class="sub">La dirección <code>%s</code> no es ninguno de los cuatro apartados.</div>
    </header>
    <div class="cuerpo">
      <main class="panel">
        <div class="vacio">Vuelve a la portada: <a href="/">el tablero</a>.</div>
      </main>
    </div>
  </div>
"""


# ------------------------------------------------------------------ el servidor

class ServidorWeb(http.server.ThreadingHTTPServer):
    """Mismo bind exclusivo que las webs que sustituye: en Windows SO_REUSEADDR
    deja que un segundo servidor robe un puerto ya en uso (bug del puerto 8765)."""

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32":
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        http.server.HTTPServer.server_bind(self)


def ruta_planos(workspace, planos=None):
    """El mapa de flujos del workspace, o el que se pida a mano.

    `--planos` existe para `validar_web.py`, que valida el mapa de un proyecto que
    todavía no es un workspace montado: la carpeta de planos existe antes que
    `docs/05-trabajo/`.
    """
    if planos:
        return Path(planos)
    return Path(workspace) / "docs" / "02-flujos" / "planos" / "planos.json"


def carpeta_presentaciones(workspace):
    return Path(workspace) / ".runtime" / "presentaciones"


def unidad_por_defecto(workspace):
    """La validación guiada más reciente: es la que `unidad.py validar` acaba de
    escribir, y por tanto la que el usuario viene a mirar."""
    raiz = carpeta_presentaciones(workspace)
    candidatas = [d for d in raiz.glob("*")
                  if (d / "manifiesto.json").is_file()] if raiz.is_dir() else []
    if not candidatas:
        return None
    return max(candidatas, key=lambda d: (d / "manifiesto.json").stat().st_mtime).name


def indice_presentaciones(workspace):
    """Una entrada por carpeta con manifiesto: unidad, si ya tiene decisión y cuándo se montó."""
    raiz = carpeta_presentaciones(workspace)
    salida = []
    if not raiz.is_dir():
        return salida
    for d in sorted(raiz.glob("*")):
        manifiesto = d / "manifiesto.json"
        if not manifiesto.is_file():
            continue
        recibos = d / "recibos"
        decidida = recibos.is_dir() and any(recibos.glob("*.json"))
        salida.append({"unidad": d.name, "decidida": bool(decidida),
                       "montada": int(manifiesto.stat().st_mtime)})
    salida.sort(key=lambda x: x["montada"], reverse=True)
    return salida


# Atributos que un handler necesita para responder sin volver a parsear la petición.
PRESTADOS = ("rfile", "wfile", "headers", "command", "request_version",
             "requestline", "client_address", "server", "close_connection",
             "connection", "raw_requestline")


def hacer_handler(workspace, estado=None, planos=None, solo_lectura=False):
    workspace = str(Path(workspace).resolve())
    planos = str(Path(planos).resolve()) if planos else None
    estado = estado if estado is not None else {"ultimo": time.time()}
    modulos = {}
    handlers = {}
    presentaciones = {}

    def modulo(cual):
        if cual not in modulos:
            modulos[cual] = cargar_modulo(cual)
        return modulos[cual]

    def handler_de(cual):
        """La clase de handler del visor de `cual`, montada una sola vez."""
        if cual in handlers:
            return handlers[cual]
        mod = modulo(cual)
        if cual in ("contratos", "tablero"):
            handlers[cual] = mod.hacer_handler(workspace, estado)
        elif cual == "flujos":
            mapa = ruta_planos(workspace, planos)
            handlers[cual] = (mod.hacer_handler(str(mapa), estado)
                              if mapa.is_file() else None)
        return handlers[cual]

    def handler_presentacion(unidad):
        """Un handler por carpeta de validación guiada: los datos de cada unidad
        viven en `.runtime/presentaciones/<unidad>/` y ahí caen sus recibos (R4)."""
        if unidad in presentaciones:
            return presentaciones[unidad]
        datos = carpeta_presentaciones(workspace) / unidad
        presentaciones[unidad] = (
            modulo("presentaciones").hacer_handler(datos, estado, workspace)
            if (datos / "manifiesto.json").is_file() else None)
        return presentaciones[unidad]

    class Web(http.server.BaseHTTPRequestHandler):

        # ------------------------------------------------------------ entradas

        def do_GET(self):
            estado["ultimo"] = time.time()
            pedida = urlsplit(self.path).path
            if pedida == "/render.js":
                return self._fichero(ruta_render_js(),
                                     "text/javascript; charset=utf-8")
            if pedida == "/base.css":
                return self._fichero(ruta_base_css(), "text/css; charset=utf-8")
            if pedida == API_HUELLA:
                return self._huella(urlsplit(self.path).query)
            if pedida == "/meta.json":
                return self._json(200, {
                    "servicio": SERVICIO,
                    "workspace": workspace,
                    "huella_workspace": huella_workspace(workspace),
                    "apartados": list(CLAVES),
                })
            return self._enrutar("GET", pedida)

        def do_POST(self):
            estado["ultimo"] = time.time()
            pedida = urlsplit(self.path).path
            # R6 y R4: la frontera se comprueba ANTES de mirar qué se pedía, para que
            # una ruta nueva no pueda nacer por fuera de ella sin darse cuenta.
            if es_escritura(pedida):
                if solo_lectura:
                    return self._json(405, {"error": (
                        "esta web se lanzó en solo lectura (--solo-lectura): aquí no se "
                        "aprueba nada. SALIDA: relánzala sin ese flag y vuelve a pulsar")})
                if not cliente_local(self.client_address):
                    return self._json(403, {"error": (
                        "solo se aprueba desde esta máquina (127.0.0.1). SALIDA: abre la "
                        "web en el ordenador donde corre el método y pulsa allí")})
            aprobar = RUTA_APROBAR_CONTRATO.match(pedida)
            if aprobar:
                return self._aprobar_contrato(aprobar.group(1))
            if pedida == API_APROBAR_PLANOS:
                return self._aprobar_planos()
            if pedida == API_VALIDAR_OK:
                return self._validar_ok()
            return self._enrutar("POST", pedida)

        def do_HEAD(self):
            estado["ultimo"] = time.time()
            self.send_response(200)
            self.end_headers()

        def do_PUT(self):
            return self.do_POST()

        def do_DELETE(self):
            return self.do_POST()

        # ------------------------------------------------------------- enrutado

        def _enrutar(self, metodo, pedida):
            if pedida in ("/", "/index.html"):
                return self._pagina("tablero", "/tablero") if metodo == "GET" \
                    else self._delegar("tablero", "/", metodo)
            trozos = pedida.strip("/").split("/")
            cual = trozos[0]
            resto = "/" + "/".join(trozos[1:])
            if cual == "tablero":
                if len(trozos) == 1:
                    return self._redirigir("/")
                return self._delegar("tablero", resto, metodo)
            if cual == "contratos":
                if len(trozos) == 1:
                    return self._pagina("contratos", "/contratos")
                return self._delegar("contratos", resto, metodo)
            if cual == "flujos":
                if len(trozos) == 1:
                    return self._flujos()
                return self._delegar("flujos", resto, metodo)
            if cual == "presentaciones":
                return self._presentaciones(trozos, metodo)
            return self._no_esta(pedida)

        def _presentaciones(self, trozos, metodo):
            """`/presentaciones[/<unidad>][/<dato>]`.

            Sin unidad se sirve la validación más reciente: es la que acaba de
            escribir `unidad.py validar`. Con unidad, esa; y sus datos y su
            recibo caen en SU carpeta, que es donde los busca `cerrar` (R4).
            """
            unidad = None
            resto = trozos[1:]
            # `/presentaciones/indice.json`: TODAS las validaciones guiadas del workspace,
            # para que el menú lateral enseñe las demás y no solo la más reciente (27-08).
            if resto == ["indice.json"] and metodo == "GET":
                return self._json(200, {"presentaciones": indice_presentaciones(workspace)})
            if resto and NOMBRE_UNIDAD.match(resto[0]):
                unidad, resto = resto[0], resto[1:]
            if unidad is None:
                unidad = unidad_por_defecto(workspace)
            base = "/presentaciones" + ("/" + unidad if unidad else "")
            if not resto:
                if metodo != "GET":
                    return self._no_esta("/presentaciones")
                if unidad is None:
                    return self._pagina_sin_presentaciones()
                return self._pagina("presentaciones", base)
            if unidad is None:
                return self._json(404, {"error": "no hay ninguna validación guiada"})
            handler = handler_presentacion(unidad)
            if handler is None:
                return self._json(404, {"error": "no hay validación guiada de %s"
                                                 % unidad})
            # `/presentaciones/<unidad>/presentacion/<id>` es un enlace directo a
            # una vista: la página entera, no el fragmento del visor.
            if metodo == "GET" and resto[0] == "presentacion":
                return self._pagina("presentaciones", base)
            return self._delegar_a(handler, "/" + "/".join(resto), metodo,
                                   "presentaciones")

        # -------------------------------------------- unidad 107: aprobar desde la web

        def _cuerpo(self, permitidos):
            """El JSON del POST, con los campos CERRADOS (R4).

            Un campo no previsto no se ignora: se rechaza. Ignorarlo es como acaban
            entrando escrituras que nadie decidió («ya que estamos, esto también»).
            """
            largo = int(self.headers.get("Content-Length") or 0)
            if largo <= 0:
                return {}
            if largo > 40_000:
                raise ValueError("cuerpo demasiado grande")
            datos = json.loads(self.rfile.read(largo) or b"{}")
            if not isinstance(datos, dict):
                raise ValueError("el cuerpo debe ser un objeto JSON")
            sobra = sorted(set(datos) - set(permitidos))
            if sobra:
                raise ValueError("campo no previsto: %s. SALIDA: manda solo %s"
                                 % (", ".join(sobra), ", ".join(sorted(permitidos))))
            return datos

        def _cliente(self):
            direccion = getattr(self, "client_address", None)
            return direccion[0] if direccion else "desconocido"

        def _aprobar_contrato(self, nombre):
            """R1 — el clic sobre un contrato PENDIENTE.

            Quien escribe la fecha sigue siendo `visor_contratos.aprobar_contrato`, la
            misma función de la 091: aquí se le ponen delante las dos puertas que le
            faltaban (ya aprobado → 409; huella distinta → 409) y detrás el «quién» como
            campo y el rastro que lee `despachar`.
            """
            mod = modulo("contratos")
            try:
                datos = self._cuerpo(("huella",))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})
            ruta = mod.ruta_contrato(workspace, nombre)
            if not ruta:
                return self._json(404, {"error": "no hay contrato de " + nombre})
            try:
                texto = Path(ruta).read_text(encoding="utf-8")
                huella = huella_fichero(ruta)
            except OSError as exc:
                return self._json(400, {"error": str(exc)})
            ya = fecha_aprobado(texto)
            if ya:
                return self._json(409, {
                    "error": "%s ya estaba aprobada el %s: aprobar es un gesto sobre lo "
                             "pendiente y no reescribe una firma. SALIDA: no hay nada que "
                             "hacer aquí; si el contrato cambió, pide cambios"
                             % (nombre, ya),
                    "unidad": nombre, "aprobado": ya})
            if datos.get("huella") and datos["huella"] != huella:
                return self._json(409, {"error": MENSAJE_RELEER, "unidad": nombre})
            try:
                fecha = mod.aprobar_contrato(workspace, nombre, QUIEN)
            except FileNotFoundError:
                return self._json(404, {"error": "no hay contrato de " + nombre})
            except (ValueError, OSError) as exc:
                return self._json(400, {"error": str(exc)})
            anotar_aprobado_por(ruta)
            rastro = escribir_rastro_aprobacion(workspace, nombre, ruta, huella,
                                                self._cliente())
            return self._json(200, {"unidad": nombre, "aprobado": fecha,
                                    "aprobado_por": QUIEN,
                                    "rastro": str(rastro) if rastro else None})

        def _revision(self):
            """El módulo que YA aprueba planos desde el comando (`requisitos aprobar`)."""
            return modulo("flujos").revision

        def _aprobar_planos(self):
            """R2 — el mismo `revision.aprobar` que el comando, disparado por el clic.

            Ni una línea de escritura propia: `aprobacion.json`, el `historial/` y el
            `definicion.estado` de cada plano salen de la función de siempre, con sus
            puertas de siempre (planos válidos, sin feedback pendiente, visor visto).
            """
            try:
                datos = self._cuerpo(("huella", "por", "ref", "confirmar_supuestos"))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})
            mapa = ruta_planos(workspace, planos)
            if not mapa.is_file():
                return self._json(404, {"error": "este proyecto todavía no tiene planos"})
            if datos.get("ref") and not self._ref_en_docs(datos["ref"]):
                return self._json(400, {"error": (
                    "esa referencia cae fuera de docs/: aquí solo se aprueba lo del "
                    "workspace. SALIDA: pulsa Aprobar en el apartado Flujos")})
            revision = self._revision()
            try:
                huella = revision.huella_planos(str(mapa))
            except (ValueError, OSError) as exc:
                return self._json(400, {"error": str(exc)})
            if datos.get("huella") and datos["huella"] != huella:
                return self._json(409, {"error": MENSAJE_RELEER})
            try:
                recibo = revision.aprobar(str(mapa), datos.get("por") or QUIEN,
                                          bool(datos.get("confirmar_supuestos")))
            except (ValueError, KeyError) as exc:
                return self._json(400, {"error": str(exc)})
            except OSError as exc:
                return self._json(400, {"error": str(exc)})
            rastro = escribir_rastro_aprobacion(workspace, "planos", mapa, huella,
                                                self._cliente(),
                                                {"version": recibo.get("version")})
            return self._json(200, {"aprobacion": recibo,
                                    "rastro": str(rastro) if rastro else None})

        def _ref_en_docs(self, ref):
            """Una `ref` solo vale si cae DENTRO de `docs/` del workspace servido."""
            try:
                candidata = (Path(workspace) / str(ref)).resolve()
                candidata.relative_to(Path(workspace).resolve() / "docs")
            except (ValueError, OSError, RuntimeError):
                return False
            return True

        def _validar_ok(self):
            """R2 (segunda mitad) — el OK final de una validación guiada.

            El recibo lo sigue escribiendo el visor de presentaciones, con su propia
            validación contra el manifiesto: aquí se le entrega la decisión tal cual, por
            su ruta de siempre (`/decisiones`), para que el fichero que cae en
            `.runtime/presentaciones/<unidad>/recibos/` sea EXACTAMENTE el que
            `unidad.py cerrar --ok-usuario` sabe leer.
            """
            try:
                datos = self._cuerpo(("unidad", "huella", "presentacion", "version",
                                      "contenido_revisado", "eleccion", "comentario",
                                      "confirmado"))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})
            unidad = str(datos.pop("unidad", "") or "")
            if not NOMBRE_UNIDAD.match(unidad):
                return self._json(400, {"error": (
                    "falta la unidad de la validación guiada (NNN-slug). SALIDA: pulsa el "
                    "OK desde el apartado Presentaciones de esa unidad")})
            handler = handler_presentacion(unidad)
            if handler is None:
                return self._json(404, {"error": "no hay validación guiada de " + unidad})
            manifiesto = carpeta_presentaciones(workspace) / unidad / "manifiesto.json"
            try:
                huella = huella_fichero(manifiesto)
            except OSError as exc:
                return self._json(400, {"error": str(exc)})
            if datos.pop("huella", None) not in (None, huella):
                return self._json(409, {"error": MENSAJE_RELEER})
            recibos = carpeta_presentaciones(workspace) / unidad / "recibos"
            antes = len(list(recibos.glob("*.json"))) if recibos.is_dir() else 0
            self._delegar_cuerpo(handler, "/decisiones",
                                 json.dumps(datos, ensure_ascii=False).encode("utf-8"))
            despues = len(list(recibos.glob("*.json"))) if recibos.is_dir() else 0
            if despues > antes:
                escribir_rastro_aprobacion(workspace, unidad, manifiesto, huella,
                                           self._cliente(),
                                           {"eleccion": datos.get("eleccion")})

        def _delegar_cuerpo(self, clase, ruta, cuerpo):
            """Como `_delegar_a`, pero con un cuerpo YA leído: el visor de presentaciones
            lee su JSON de `rfile`, y aquí ese JSON ya se abrió para mirarle la huella."""
            sub = clase.__new__(clase)
            for nombre in PRESTADOS:
                if hasattr(self, nombre):
                    setattr(sub, nombre, getattr(self, nombre))
            cabeceras = email.message.Message()
            cabeceras["Content-Type"] = "application/json"
            cabeceras["Content-Length"] = str(len(cuerpo))
            sub.headers = cabeceras
            sub.rfile = io.BytesIO(cuerpo)
            sub.path = ruta
            sub._headers_buffer = []
            try:
                sub.do_POST()
            finally:
                self.close_connection = getattr(sub, "close_connection",
                                                self.close_connection)

        def _huella(self, consulta):
            """La huella de lo que la página está enseñando, para devolverla en el POST."""
            campos = parse_qs(consulta or "")
            tipo = (campos.get("tipo") or [""])[0]
            ref = (campos.get("ref") or [""])[0]
            if tipo == "planos":
                mapa = ruta_planos(workspace, planos)
                if not mapa.is_file():
                    return self._json(404, {"error": "este proyecto no tiene planos"})
                try:
                    return self._json(200, {"tipo": tipo,
                                            "huella": self._revision().huella_planos(str(mapa))})
                except (ValueError, OSError) as exc:
                    return self._json(400, {"error": str(exc)})
            if not NOMBRE_UNIDAD.match(ref):
                return self._json(400, {"error": (
                    "la referencia tiene que ser una unidad (NNN-slug). SALIDA: pide la "
                    "huella de lo que la página está enseñando, no de una ruta a mano")})
            if tipo == "contrato":
                destino = modulo("contratos").ruta_contrato(workspace, ref)
            elif tipo == "validacion":
                destino = carpeta_presentaciones(workspace) / ref / "manifiesto.json"
                destino = destino if destino.is_file() else None
            else:
                return self._json(400, {"error": (
                    "tipo desconocido. SALIDA: usa tipo=contrato, tipo=planos o "
                    "tipo=validacion")})
            if not destino:
                return self._json(404, {"error": "no hay nada que aprobar en " + ref})
            try:
                return self._json(200, {"tipo": tipo, "ref": ref,
                                        "huella": huella_fichero(destino)})
            except OSError as exc:
                return self._json(400, {"error": str(exc)})

        def _flujos(self):
            mapa = ruta_planos(workspace, planos)
            if not mapa.is_file():
                # R7: un proyecto sin planos todavía. La web arranca igual y este
                # apartado lo DICE, en vez de morirse y llevarse los otros tres.
                return self._html(200, pagina("flujos", "/flujos",
                                              CUERPO_SIN_PLANOS,
                                              "Flujos · aún no hay planos",
                                              solo_lectura=solo_lectura))
            # R4 (unidad 033): `requisitos.py aprobar` exige el rastro de que los
            # planos se enseñaron. Se anota POR VISTA, como hacía `requisitos.py
            # abrir`: mirarlos hoy en una web abierta ayer tiene que contar.
            self._anotar_flujos()
            return self._pagina("flujos", "/flujos")

        def _anotar_flujos(self):
            puerto = self.server.server_address[1]
            registro = (Path(workspace) / ".runtime" / (RASTRO_FLUJOS % puerto))
            try:
                registro.parent.mkdir(parents=True, exist_ok=True)
                with open(registro, "a", encoding="utf-8") as rastro:
                    rastro.write("%s visor abierto sobre estos planos (puerto %d)\n"
                                 % (time.strftime("%Y-%m-%dT%H:%M:%S"), puerto))
            except OSError:
                pass

        # ----------------------------------------------------------- delegación

        def _delegar(self, cual, ruta, metodo):
            handler = handler_de(cual)
            if handler is None:
                return self._json(404, {
                    "error": "este proyecto todavía no tiene planos "
                             "(docs/02-flujos/planos/planos.json)"})
            return self._delegar_a(handler, ruta, metodo, cual)

        def _delegar_a(self, clase, ruta, metodo, cual):
            """Le pasa la petición al visor dueño de esos datos, con la ruta ya
            sin prefijo. El visor responde por NUESTRO socket: no hay proxy, no
            hay segundo puerto y su lógica no se entera de que la montaron."""
            sub = clase.__new__(clase)
            for nombre in PRESTADOS:
                if hasattr(self, nombre):
                    setattr(sub, nombre, getattr(self, nombre))
            sub.path = ruta
            sub._headers_buffer = []
            metodo_sub = getattr(sub, "do_" + metodo, None)
            if metodo_sub is None:
                return self._json(405, {"error": "método no permitido"})
            try:
                metodo_sub()
            finally:
                self.close_connection = getattr(sub, "close_connection",
                                                self.close_connection)

        # -------------------------------------------------------------- salidas

        def _pagina(self, cual, base):
            return self._html(200, pagina(cual, base, solo_lectura=solo_lectura))

        def _pagina_sin_presentaciones(self):
            cuerpo = CUERPO_404 % "/presentaciones"
            cuerpo = cuerpo.replace(
                "Aquí no hay nada", "Todavía no hay nada que validar").replace(
                "La dirección <code>/presentaciones</code> no es ninguno de los "
                "cuatro apartados.",
                "Nadie ha lanzado aún <code>unidad.py validar</code> en este "
                "workspace.")
            return self._html(200, pagina("presentaciones", "/presentaciones",
                                          cuerpo, "Presentaciones",
                                          solo_lectura=solo_lectura))

        def _no_esta(self, pedida):
            # R6: un apartado que no existe es un 404 AMABLE con enlace a la
            # portada, no un 500 ni una página en blanco.
            escapada = (pedida.replace("&", "&amp;").replace("<", "&lt;")
                        .replace(">", "&gt;"))
            return self._html(404, pagina("tablero", "/tablero",
                                          CUERPO_404 % escapada,
                                          "Aquí no hay nada",
                                          solo_lectura=solo_lectura))

        def _redirigir(self, destino):
            self.send_response(301)
            self.send_header("Location", destino)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _html(self, codigo, cuerpo):
            self.send_response(codigo)
            self._cabeceras("text/html; charset=utf-8", len(cuerpo))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _fichero(self, ruta, tipo):
            try:
                cuerpo = Path(ruta).read_bytes()
            except OSError:
                return self._json(404, {"error": "fichero inexistente"})
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

    return Web


def anotar_apertura(workspace):
    """Rastro fechado de que la web se levantó, como hacían las cuatro webs."""
    registro = Path(workspace) / ".runtime" / "tablero.log"
    try:
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "a", encoding="utf-8") as rastro:
            rastro.write("%s tablero levantado\n"
                         % time.strftime("%Y-%m-%dT%H:%M:%S"))
    except OSError:
        return None
    return registro


def main():
    p = argparse.ArgumentParser(description="La web del método: los cuatro apartados")
    p.add_argument("--workspace", required=True,
                   help="Ruta del meta-repo (el que tiene docs/05-trabajo/)")
    p.add_argument("--planos",
                   help="mapa de flujos a servir en /flujos; por defecto, el del "
                        "workspace (docs/02-flujos/planos/planos.json)")
    p.add_argument("--puerto", type=int, default=0,
                   help="puerto local; 0 pide uno libre")
    p.add_argument("--minutos", type=float, default=0,
                   help="minutos sin actividad antes de apagarse; 0 = no caduca")
    p.add_argument("--sin-navegador", action="store_true",
                   help="No abrir el navegador")
    p.add_argument("--solo-lectura", action="store_true",
                   help="la web sin manos: ningún botón de aprobar y los endpoints de "
                        "aprobación responden 405 (unidad 107, R6)")
    args = p.parse_args()

    if not (0 <= args.minutos <= 1440):
        sys.exit("--minutos debe estar entre 0 y 1440")
    if not (0 <= args.puerto <= 65535):
        sys.exit("--puerto debe estar entre 0 y 65535")

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(os.path.join(workspace, "docs", "05-trabajo")):
        # No es un motivo para no arrancar: `validar_web.py` sirve el mapa de un
        # proyecto que todavía no tiene workspace montado. Los apartados que
        # dependan de lo que falte lo dirán ellos, cada uno en su sitio.
        print("AVISO: no hay docs/05-trabajo/ en %s; los apartados de contratos y "
              "tablero saldrán vacíos." % workspace, flush=True)
    if not CASCARA.is_file():
        sys.exit("Falta la cáscara de la web: %s" % CASCARA)

    estado = {"ultimo": time.time()}
    try:
        servidor = ServidorWeb(("127.0.0.1", args.puerto),
                               hacer_handler(workspace, estado, args.planos,
                                             args.solo_lectura))
    except OSError as exc:
        sys.exit("No pude abrir el puerto %d: %s" % (args.puerto, exc))
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    anotar_apertura(workspace)

    url = "http://127.0.0.1:%d/" % puerto
    print("La web del método está en pie: %s" % url, flush=True)
    print("Workspace: %s" % workspace, flush=True)
    if args.solo_lectura:
        print("Solo lectura: aquí no se aprueba nada.", flush=True)
    if args.minutos:
        print("Se apaga tras %g minutos sin actividad." % args.minutos, flush=True)
    else:
        print("Sesión estable: no se apaga sola.", flush=True)
    # `IR_SIN_NAVEGADOR` manda sobre todo (misma regla que `abrir.py: hay_pantalla`): un test
    # o un agente en batch que lance este servidor sin `--sin-navegador` abría el navegador
    # REAL del usuario en un puerto efímero que moría al acabar (bug 111, P-20260827-af7a3c37).
    if not args.sin_navegador and not os.environ.get("IR_SIN_NAVEGADOR", "").strip():
        import webbrowser
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
    print("La web del método se cerró.", flush=True)


if __name__ == "__main__":
    main()
