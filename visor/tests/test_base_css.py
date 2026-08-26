"""Unidad 076 — una sola hoja de estilos para las cuatro webs, y legible.

Hasta hoy el esqueleto (paleta, cabecera, menú, panel, tipografía) estaba
COPIADO LITERAL en las cuatro plantillas y un test lo comparaba línea a línea:
la copia se mantenía a mano. Aquí vive en `visor/base.css`, las cuatro la
enlazan y los cuatro servidores la sirven en local.

Qué vigila cada bloque:

- R1/R6 — existe `base.css`, las cuatro la enlazan, ninguna repite un selector
  suyo ni redefine sus variables (la copia literal no puede volver sola).
- R2 — los valores que Nate ve raros, medidos EN EL CSS: tamaño y interlineado
  del texto de lectura, suelo de la letra pequeña, escala de títulos y aire
  entre párrafos y bloques.
- R3 — tema claro/oscuro con el mismo interruptor en las cuatro.
- R4 — sin red: ni un `http(s)://` fuera de 127.0.0.1.
- R5 — si `base.css` no llegara, la plantilla conserva un mínimo inline.
- Integración — `GET /base.css` responde 200 `text/css` en los cuatro
  servidores, y con el mismo contenido.
"""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASE_CSS = RAIZ / "visor" / "base.css"

# Las cuatro webs: nombre, plantilla, carpeta del servidor.
WEBS = (
    ("flujos", RAIZ / "visor" / "plantilla.html"),
    ("contratos", RAIZ / "visor_contratos" / "plantilla.html"),
    ("presentaciones", RAIZ / "visor_presentaciones" / "plantilla.html"),
    ("tablero", RAIZ / "visor_tablero" / "plantilla.html"),
)

ENLACE = '<link rel="stylesheet" href="/base.css">'
# El único `<style>` que puede quedar en una plantilla además del suyo propio:
# el mínimo de R5, marcado para que este test lo distinga del resto.
MARCA_MINIMO = 'id="minimo-sin-base-css"'

# Etiquetas de una palabra en mayúsculas: R2 les permite bajar hasta aquí.
T_ETIQUETA = 11.0
# Suelo de cualquier otro texto informativo.
T_NOTA = 12.5


# --------------------------------------------------------------- utilidades

def sin_comentarios(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def bloques_style(html):
    """Los `<style>…</style>` de una plantilla, con su etiqueta de apertura."""
    return re.findall(r"<style([^>]*)>(.*?)</style>", html, flags=re.S)


def style_propio(html):
    """El `<style>` de la plantilla que NO es el mínimo de R5."""
    trozos = [cuerpo for atributos, cuerpo in bloques_style(html)
              if MARCA_MINIMO not in atributos]
    return "\n".join(trozos)


def selectores(css):
    """Los selectores de una hoja, incluidos los de dentro de un `@media`.

    Basta con un barrido de texto: estas hojas son CSS plano, sin anidamiento
    ni preprocesador. Devuelve cada selector individual normalizado (una coma
    separa selectores distintos, `a, b {}` cuenta como dos).
    """
    css = sin_comentarios(css)
    # Fuera el cuerpo de los @keyframes: allí `50%` no es un selector.
    css = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    encontrados = set()
    for cabecera in re.findall(r"([^{}]+)\{", css):
        cabecera = " ".join(cabecera.split())
        if cabecera.startswith("@"):   # el prelude de un at-rule no es selector
            continue
        for uno in cabecera.split(","):
            uno = " ".join(uno.split())
            if uno:
                encontrados.add(uno)
    return encontrados


def variables_declaradas(css):
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", sin_comentarios(css)))


def tamanos_px(css):
    """Cada tamaño de letra en px que declara la hoja, con su selector."""
    css = sin_comentarios(css)
    salida = []
    for cabecera, cuerpo in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        cabecera = " ".join(cabecera.split())
        for prop, valor in re.findall(r"(font-size|font)\s*:\s*([^;]+)", cuerpo):
            for numero in re.findall(r"(\d+(?:\.\d+)?)px", valor):
                if prop == "font" and "px" not in valor.split("/")[0]:
                    continue
                salida.append((cabecera, float(numero), cuerpo))
                break
    return salida


def es_etiqueta(cuerpo):
    """Una ETIQUETA: un rótulo corto en negrita, no un texto que se lee.

    Es la única excusa que R2 admite para bajar del suelo, y se puede
    comprobar. Hasta la 091 la marca era `text-transform: uppercase`; el
    26-08 las mayúsculas forzadas salieron de TODA la web (se leen peor y
    gritan), y la marca pasó a ser la que dejó esa iteración en cada rótulo:
    negrita + `text-transform: none` explícito. Un texto corrido de 11px que
    no lleve las dos sigue suspendiendo, que es lo que este suelo vigila.
    """
    negrita = re.search(r"font-weight\s*:\s*bold|font\s*:\s*bold", cuerpo)
    return bool(negrita) and re.search(r"text-transform\s*:\s*none", cuerpo)


def declaracion(css, selector, propiedad):
    """El valor de `propiedad` en la regla `selector` de esta hoja."""
    css = sin_comentarios(css)
    for cabecera, cuerpo in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        if " ".join(cabecera.split()) != selector:
            continue
        hallado = re.search(r"(?:^|;)\s*%s\s*:\s*([^;]+)" % re.escape(propiedad),
                            cuerpo)
        if hallado:
            return hallado.group(1).strip()
    return None


def valor_variable(css, nombre):
    hallado = re.search(r"%s\s*:\s*([^;}]+)" % re.escape(nombre),
                        sin_comentarios(css))
    return hallado.group(1).strip() if hallado else None


def px(valor):
    hallado = re.search(r"(\d+(?:\.\d+)?)px", valor or "")
    return float(hallado.group(1)) if hallado else None


def resolver(css, valor):
    """Sustituye `var(--x)` por lo que `:root` declare, una vuelta basta."""
    if valor is None:
        return None
    def cambio(m):
        return valor_variable(css, m.group(1)) or m.group(0)
    return re.sub(r"var\(\s*(--[a-z0-9-]+)\s*\)", cambio, valor)


# ------------------------------------------------------------------- R1, R6

class HojaComunTest(unittest.TestCase):
    """R1 y R6 — una sola hoja, enlazada por las cuatro, sin copias."""

    def setUp(self):
        self.assertTrue(BASE_CSS.is_file(), "no existe visor/base.css")
        self.css = BASE_CSS.read_text(encoding="utf-8")

    def test_las_cuatro_plantillas_enlazan_base_css(self):
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                self.assertIn(ENLACE, plantilla.read_text(encoding="utf-8"),
                              "%s no enlaza /base.css" % nombre)

    def test_la_hoja_trae_el_esqueleto_comun(self):
        suyos = selectores(self.css)
        for selector in (":root", "body", ".pagina", "header", "header .marca",
                         ".boton-tema", ".menu-unidades", ".panel", ".md",
                         "h1", "h2", "h3"):
            with self.subTest(selector=selector):
                self.assertIn(selector, suyos)

    def test_ninguna_plantilla_repite_un_selector_de_la_hoja(self):
        suyos = selectores(self.css)
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                repetidos = suyos & selectores(style_propio(
                    plantilla.read_text(encoding="utf-8")))
                self.assertEqual(set(), repetidos,
                                 "%s repite reglas de base.css" % nombre)

    def test_ninguna_plantilla_redefine_las_variables_de_la_hoja(self):
        suyas = variables_declaradas(self.css)
        self.assertIn("--paper", suyas)
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                propias = variables_declaradas(style_propio(
                    plantilla.read_text(encoding="utf-8")))
                self.assertEqual(set(), suyas & propias,
                                 "%s redefine variables de base.css" % nombre)

    def test_la_paleta_ya_no_esta_copiada_en_las_plantillas(self):
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                self.assertNotIn(":root", style_propio(
                    plantilla.read_text(encoding="utf-8")),
                    "%s aún declara la paleta" % nombre)


# ----------------------------------------------------------------------- R2

class LegibilidadTest(unittest.TestCase):
    """R2 — lo que Nate ve raro, medido en el CSS."""

    def setUp(self):
        self.css = BASE_CSS.read_text(encoding="utf-8")

    def test_el_texto_de_lectura_va_al_tamano_del_cuerpo(self):
        tamano = px(resolver(self.css, declaracion(self.css, ".md", "font-size")))
        self.assertIsNotNone(tamano, "`.md` no declara font-size")
        self.assertGreaterEqual(tamano, 16)
        self.assertLessEqual(tamano, 17)

    def test_el_texto_de_lectura_respira(self):
        # 1.6 desde el 26-08 (commit 89f177a): un solo interlineado en toda la
        # web, el mismo que el cuerpo, en vez de dos parecidos que se notaban.
        alto = resolver(self.css, declaracion(self.css, ".md", "line-height"))
        self.assertEqual("1.6", (alto or "").strip())

    def test_el_cuerpo_conserva_16px_y_line_height_1_6(self):
        # El cuerpo sigue siendo 16px; el interlineado subió a 1.6 el 26-08
        # (commit 89f177a) y es el ÚNICO de la web (`.md` usa el mismo).
        fuente = resolver(self.css, declaracion(self.css, "body", "font"))
        self.assertIsNotNone(fuente, "`body` no declara font")
        self.assertTrue(re.match(r"16px\s*/\s*1\.6(\s|$)", fuente.strip()),
                        "el cuerpo ya no es 16px/1.6: %r" % fuente)

    def test_la_columna_de_texto_sigue_midiendose_en_ch(self):
        self.assertEqual("78ch", declaracion(self.css, ".md", "max-width"))

    def test_la_escala_de_titulos_tiene_escalones(self):
        for selector, esperado in (("h1", 25), ("h2", 20), ("h3", 17)):
            with self.subTest(titulo=selector):
                self.assertEqual(esperado, px(resolver(
                    self.css, declaracion(self.css, selector, "font-size"))))

    def test_ningun_texto_informativo_baja_del_suelo(self):
        crudo = re.sub(r"var\(\s*(--[a-z0-9-]+)\s*\)",
                       lambda m: valor_variable(self.css, m.group(1)) or "",
                       sin_comentarios(self.css))
        for selector, tamano, cuerpo in tamanos_px(crudo):
            if tamano >= T_NOTA:
                continue
            with self.subTest(selector=selector):
                self.assertTrue(
                    tamano == T_ETIQUETA and es_etiqueta(cuerpo),
                    "%s usa %spx: por debajo de %spx sólo se admite una "
                    "etiqueta de %spx en MAYÚSCULAS"
                    % (selector, tamano, T_NOTA, T_ETIQUETA))

    def test_tampoco_las_plantillas_bajan_del_suelo(self):
        """El suelo vale para las CUATRO webs, no sólo para la hoja común.

        Es donde vivían los peores casos (chips de 10.5px, notas de 12px):
        si esto no se comprueba, la letra ilegible vuelve por la puerta de
        atrás de una plantilla.
        """
        for nombre, plantilla in WEBS:
            propio = style_propio(plantilla.read_text(encoding="utf-8"))
            crudo = re.sub(r"var\(\s*(--[a-z0-9-]+)\s*\)",
                           lambda m: valor_variable(self.css, m.group(1)) or "",
                           sin_comentarios(propio))
            for selector, tamano, cuerpo in tamanos_px(crudo):
                if tamano >= T_NOTA:
                    continue
                with self.subTest(web=nombre, selector=selector):
                    self.assertTrue(
                        tamano == T_ETIQUETA and es_etiqueta(cuerpo),
                        "%s · %s usa %spx: el suelo es %spx (%spx sólo para "
                        "una etiqueta en MAYÚSCULAS)"
                        % (nombre, selector, tamano, T_NOTA, T_ETIQUETA))

    def test_los_parrafos_y_los_bloques_llevan_aire(self):
        parrafo = px(valor_variable(self.css, "--e-parrafo"))
        bloque = px(valor_variable(self.css, "--e-bloque"))
        self.assertIsNotNone(parrafo, "falta --e-parrafo")
        self.assertIsNotNone(bloque, "falta --e-bloque")
        # 16px desde el 26-08 (commit 0ad93d7): los párrafos pegados eran
        # justo lo que se leía mal. El tope alto impide que se dispare.
        self.assertGreaterEqual(parrafo, 10)
        self.assertLessEqual(parrafo, 16)
        self.assertGreaterEqual(bloque, 16)

    def test_el_aire_se_usa_donde_se_ve(self):
        margen_p = resolver(self.css, declaracion(self.css, ".md p", "margin"))
        self.assertGreaterEqual(px(margen_p) or 0, 10)
        for selector in (".md table", ".md pre", ".plegable"):
            with self.subTest(selector=selector):
                margen = declaracion(self.css, selector, "margin") or ""
                margen = margen or (declaracion(self.css, selector,
                                                "margin-top") or "")
                self.assertGreaterEqual(px(resolver(self.css, margen)) or 0, 16)


# ----------------------------------------------------------------------- R3

class TemaTest(unittest.TestCase):
    """R3 — un solo interruptor, y el tema vive en la hoja común."""

    def setUp(self):
        self.css = BASE_CSS.read_text(encoding="utf-8")

    def test_la_hoja_trae_los_dos_temas(self):
        suyos = selectores(self.css)
        self.assertIn(':root[data-theme="dark"]', suyos)
        self.assertIn(':root[data-theme="light"]', suyos)
        self.assertIn("(prefers-color-scheme: dark)", self.css)

    def test_las_cuatro_usan_el_mismo_interruptor_guardado(self):
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                texto = plantilla.read_text(encoding="utf-8")
                self.assertIn('var GUARDADO = "visor-tema";', texto)

    def test_el_tema_se_aplica_antes_de_pintar(self):
        """Sin destellos: el `data-theme` se fija ANTES del primer contenido."""
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                texto = plantilla.read_text(encoding="utf-8")
                self.assertLess(texto.index("raiz.dataset.theme"),
                                texto.index('class="pagina'),
                                "%s pinta antes de saber su tema" % nombre)


# ----------------------------------------------------------------------- R4

class SinRedTest(unittest.TestCase):
    """R4 — ni un recurso fuera de 127.0.0.1."""

    def test_ni_la_hoja_ni_las_plantillas_salen_a_la_red(self):
        fuentes = [("base.css", BASE_CSS)] + list(WEBS)
        for nombre, ruta in fuentes:
            with self.subTest(fuente=nombre):
                texto = ruta.read_text(encoding="utf-8")
                fuera = [u for u in re.findall(r"https?://[^\s\"'<>()]+", texto)
                         if not u.startswith(("http://127.0.0.1",
                                              "https://127.0.0.1"))]
                self.assertEqual([], fuera, "%s sale a la red" % nombre)

    def test_ningun_link_ni_script_apunta_fuera(self):
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                texto = plantilla.read_text(encoding="utf-8")
                for atributo in re.findall(
                        r"<(?:link|script)[^>]*?(?:href|src)\s*=\s*[\"']([^\"']+)",
                        texto):
                    self.assertFalse(
                        atributo.startswith(("http://", "https://", "//")),
                        "%s carga %s de fuera" % (nombre, atributo))


# ----------------------------------------------------------------------- R5

class MinimoSinHojaTest(unittest.TestCase):
    """R5 — si `/base.css` no llegara, la página no se queda en blanco."""

    def test_cada_plantilla_lleva_su_minimo_inline(self):
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                texto = plantilla.read_text(encoding="utf-8")
                minimos = [cuerpo for atributos, cuerpo in bloques_style(texto)
                           if MARCA_MINIMO in atributos]
                self.assertEqual(1, len(minimos),
                                 "%s no marca su mínimo de R5" % nombre)
                minimo = minimos[0]
                for propiedad in ("background", "color", "font"):
                    self.assertIn(propiedad, minimo,
                                  "el mínimo de %s no fija %s"
                                  % (nombre, propiedad))
                self.assertNotIn("var(--", minimo,
                                 "el mínimo de %s depende de base.css" % nombre)

    def test_el_minimo_va_antes_del_enlace_para_no_pisarlo(self):
        for nombre, plantilla in WEBS:
            with self.subTest(web=nombre):
                texto = plantilla.read_text(encoding="utf-8")
                self.assertLess(texto.index(MARCA_MINIMO), texto.index(ENLACE),
                                "el mínimo de %s pisa base.css" % nombre)


# ----------------------------------------------------- reparto al workspace

class RepartidaAlWorkspaceTest(unittest.TestCase):
    """R1 — la hoja viaja al workspace, como `render.js` desde el bug 064.

    Desde la unidad 081 la web del workspace es UNA y vive en
    `docs/00-metodo/requisitos/web/`: la hoja viaja en su misma lista
    (`ARCHIVOS_WEB`) y a su lado. Si no se repartiera, la web nacería sin
    estilos —justo el bug que la 064 aprendió con `render.js`— y sólo quedaría
    el mínimo de R5.
    """

    def setUp(self):
        from visor import bootstrap
        self.bootstrap = bootstrap

    def test_el_manifiesto_de_la_web_la_incluye(self):
        self.assertIn("base.css", self.bootstrap.ARCHIVOS_WEB)
        self.assertEqual(RAIZ / "visor" / "base.css",
                         self.bootstrap.origen_web("base.css"))

    def test_un_workspace_recien_montado_la_tiene_donde_la_piden(self):
        """Bootstrap de verdad: se monta un workspace y se mira el árbol."""
        raiz = Path(tempfile.mkdtemp(prefix="076-bootstrap-"))
        self.addCleanup(shutil.rmtree, raiz, True)
        planos = raiz / "planos"
        (planos / "especificaciones" / "01-constitution").mkdir(parents=True)
        (planos / "especificaciones" / "02-flows").mkdir()
        (planos / "planos.json").write_text(json.dumps({
            "version": 2, "proyecto": "demo", "titulo": "Demo",
            "contrato": {"frase": "Una demostración"}, "actividades": [],
        }), encoding="utf-8")
        (planos / "especificaciones" / "01-constitution" /
         "constitution.md").write_text("# Constitución\n", encoding="utf-8")

        destino = raiz / "demo-agents"
        r = subprocess.run(
            [sys.executable, str(RAIZ / "visor" / "bootstrap.py"),
             "--planos", str(planos), "--destino", str(destino)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)

        repartida = (destino / "docs" / "00-metodo" / "requisitos" / "web"
                     / "base.css")
        self.assertTrue(repartida.is_file(),
                        "la hoja común no viajó al workspace")
        self.assertEqual(BASE_CSS.read_text(encoding="utf-8"),
                         repartida.read_text(encoding="utf-8"))

    def test_la_web_la_busca_primero_al_lado_y_luego_en_el_repo(self):
        """Los dos layouts: en el workspace la hoja está DENTRO de `web/`; en el
        repo de código, en `visor/base.css`. Se busca, no se adivina."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "web_servir_base_css", RAIZ / "web" / "servir.py")
        servir = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = servir
        spec.loader.exec_module(servir)
        self.assertEqual(RAIZ / "web" / "base.css", servir.BASE_CSS_LAYOUTS[0])
        self.assertEqual(RAIZ / "visor" / "base.css", servir.ruta_base_css())


# --------------------------------------------------------------- integración

def _libre():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


class ServidoPorLosCuatroTest(unittest.TestCase):
    """Integración — `GET /base.css` en los cuatro servidores."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="076-base-css-")
        cls.procesos = []

    @classmethod
    def tearDownClass(cls):
        for proceso in cls.procesos:
            proceso.terminate()
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proceso.kill()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _arrancar(self, argumentos):
        puerto = _libre()
        entorno = dict(os.environ, PYTHONPATH=str(RAIZ))
        proceso = subprocess.Popen(
            [sys.executable] + argumentos + ["--puerto", str(puerto)],
            cwd=str(RAIZ), env=entorno,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        type(self).procesos.append(proceso)
        limite = time.time() + 20
        while time.time() < limite:
            if proceso.poll() is not None:
                self.fail("el servidor murió: %s"
                          % proceso.stderr.read().decode("utf-8", "replace"))
            try:
                conexion = http.client.HTTPConnection("127.0.0.1", puerto,
                                                      timeout=2)
                conexion.request("GET", "/base.css")
                return conexion.getresponse(), puerto
            except OSError:
                time.sleep(0.2)
        self.fail("el servidor no levantó a tiempo")

    # --- datos mínimos que cada visor exige para arrancar ---

    def _workspace(self):
        raiz = Path(self.tmp) / "workspace"
        (raiz / "docs" / "05-trabajo").mkdir(parents=True, exist_ok=True)
        (raiz / "main").mkdir(exist_ok=True)
        return raiz

    def _planos(self):
        ruta = Path(self.tmp) / "planos.json"
        if not ruta.exists():
            ruta.write_text(json.dumps(
                {"proyecto": {"nombre": "prueba"}, "actividades": []}),
                encoding="utf-8")
        return ruta

    def _datos_presentaciones(self):
        carpeta = Path(self.tmp) / "presentaciones"
        carpeta.mkdir(exist_ok=True)
        (carpeta / "manifiesto.json").write_text(
            json.dumps({"version": 1, "presentaciones": []}), encoding="utf-8")
        return carpeta

    def _comprobar(self, respuesta):
        self.assertEqual(200, respuesta.status)
        self.assertIn("text/css", respuesta.getheader("Content-Type") or "")
        return respuesta.read().decode("utf-8")

    def test_la_web_unica_sirve_la_hoja_a_los_cuatro_apartados(self):
        """081: ya no hay cuatro servidores que puedan servir cuatro hojas
        distintas. Hay uno, y `/base.css` es la misma para los cuatro
        apartados — que es lo que la 076 quería asegurar."""
        esperado = BASE_CSS.read_text(encoding="utf-8")
        respuesta, puerto = self._arrancar(
            ["web/servir.py", "--workspace", str(self._workspace())])
        self.assertEqual(esperado, self._comprobar(respuesta),
                         "la web sirve otra hoja")
        for apartado in ("/", "/contratos", "/presentaciones", "/flujos"):
            with self.subTest(apartado=apartado):
                conexion = http.client.HTTPConnection("127.0.0.1", puerto,
                                                      timeout=5)
                try:
                    conexion.request("GET", apartado)
                    pagina = conexion.getresponse()
                    self.assertEqual(200, pagina.status)
                    self.assertIn('<link rel="stylesheet" href="/base.css">',
                                  pagina.read().decode("utf-8"))
                finally:
                    conexion.close()


if __name__ == "__main__":
    unittest.main()
