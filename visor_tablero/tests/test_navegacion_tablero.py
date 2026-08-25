"""Bug 067 — el tablero navega y se ve como las otras webs.

Un test por criterio del contrato del arreglo (§1 de
`docs/bugs/067-tablero-navega-como-las-otras-webs.md`):

- R1 — el tablero deja de duplicar: en el HTML SERVIDO quedan exactamente tres
  entradas de menú (Ahora · Te toca a ti · Por hacer) y no hay ni rastro de
  «Historial» ni de «Documentación». `/estado.json` sigue trayéndolas: la
  fuente de datos (`estado.py`) no se toca.
- R2 — cada línea de «Te toca a ti» y de «Por hacer» enlaza a la web donde se
  hace eso (contratos :8766, presentaciones :9043, flujos :8765) y, si esa web
  no está levantada, el tablero lo DICE al lado en vez de dejar un enlace
  muerto. Se comprueba ejecutando el JS de la plantilla en node con una foto
  sintética y con la foto REAL que sirve el tablero.
- R3 — la barra común de las cuatro webs, con la actual marcada, en el HTML
  servido.
- R4 — mismo esqueleto y estilo que la 056: el bloque de estilos compartido es
  el mismo LÍNEA A LÍNEA, y las tres secciones van por hash con enlaces de
  verdad (el botón atrás funciona).
- R5 — «Ahora» sólo con los agentes vivos; los terminados del día, plegados.
"""

import html.parser
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parent
BASE = AQUI.parent                      # visor_tablero/
RAIZ = BASE.parent
PLANTILLA = BASE / "plantilla.html"
PLANTILLA_056 = RAIZ / "visor_presentaciones" / "plantilla.html"
PLANTILLA_CONTRATOS = RAIZ / "visor_contratos" / "plantilla.html"
RENDER_JS = RAIZ / "visor_contratos" / "render.js"

if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

from test_visor_tablero import (            # noqa: E402  (mismo directorio)
    ServidorDePrueba, agente, scripts_de, workspace_sintetico,
)


# --------------------------------------------------------------------------- utilidades

WEBS = (
    ("tablero", "http://127.0.0.1:8768/", "Tablero"),
    ("contratos", "http://127.0.0.1:8766/", "Contratos"),
    ("presentaciones", "http://127.0.0.1:9043/", "Presentaciones"),
    ("flujos", "http://127.0.0.1:8765/", "Flujos"),
)


class _Barra(html.parser.HTMLParser):
    """Los enlaces de la barra común, tal y como los ve el navegador."""

    def __init__(self):
        super().__init__()
        self.enlaces = []
        self._dentro = False
        self._actual = None

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "nav" and "barra-webs" in (atributos.get("class") or ""):
            self._dentro = True
        elif tag == "a" and self._dentro:
            self._actual = dict(atributos, texto="")
            self.enlaces.append(self._actual)

    def handle_endtag(self, tag):
        if tag == "nav":
            self._dentro = False
        elif tag == "a":
            self._actual = None

    def handle_data(self, datos):
        if self._actual is not None:
            self._actual["texto"] += datos


def barra_de(texto):
    parser = _Barra()
    parser.feed(texto)
    parser.close()
    return parser.enlaces


class _Menu(html.parser.HTMLParser):
    """Las entradas del menú lateral del tablero (`nav#secciones`)."""

    def __init__(self):
        super().__init__()
        self.entradas = []
        self._dentro = False

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == "nav" and atributos.get("id") == "secciones":
            self._dentro = True
        elif tag == "a" and self._dentro:
            self.entradas.append(atributos)

    def handle_endtag(self, tag):
        if tag == "nav":
            self._dentro = False


def menu_de(texto):
    parser = _Menu()
    parser.feed(texto)
    parser.close()
    return parser.entradas


def bloque_comun(texto):
    """El bloque de estilos que las tres webs comparten, línea a línea.

    Va desde el comentario de la paleta hasta el cierre del `@media` de 860px:
    es exactamente lo que hoy tienen IGUAL el visor de contratos y el de
    presentaciones (la 056), y lo que el tablero tiene que tener igual.
    """
    lineas = texto.splitlines()
    inicio = next(i for i, l in enumerate(lineas)
                  if l.strip().startswith("/* ---------- paleta"))
    fin = next(i for i, l in enumerate(lineas)
               if l.strip().startswith("@media (max-width: 860px)"))
    return lineas[inicio:fin + 4]


def scripts_inline(texto):
    return [cuerpo for atributos, cuerpo in scripts_de(texto).scripts
            if not atributos.get("src")]


STUBS = r"""
/* DOM mínimo: la plantilla sólo necesita colgar oyentes y devolver HTML. */
function nodoFalso() {
  return {
    innerHTML: "", textContent: "", value: "", className: "", dataset: {},
    classList: {add: function () {}, remove: function () {}, toggle: function () {}},
    addEventListener: function () {}, setAttribute: function () {},
    appendChild: function () {}, insertAdjacentHTML: function () {},
    querySelector: function () { return nodoFalso(); },
    querySelectorAll: function () { return []; },
    scrollIntoView: function () {}
  };
}
var document = {
  documentElement: {dataset: {}},
  getElementById: function () { return nodoFalso(); },
  createElement: function () { return nodoFalso(); },
  addEventListener: function () {},
  querySelectorAll: function () { return []; }
};
var window = {
  addEventListener: function () {},
  matchMedia: function () { return {matches: false, addEventListener: function () {}}; },
  innerWidth: 1200
};
var location = {hash: "", pathname: "/"};
var localStorage = {getItem: function () { return null; }, setItem: function () {}};
function fetch() {
  var promesa = {then: function () { return promesa; },
                 catch: function () { return promesa; }};
  return promesa;
}
function setInterval() {}
"""


def pintar(funcion, foto):
    """Ejecuta en node una de las funciones que pintan la plantilla.

    Es la única forma honesta de comprobar los enlaces: los pinta el navegador
    con lo que trae `/estado.json`, no el servidor.
    """
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("sin node no se puede ejecutar el JS de la plantilla")
    partes = [STUBS, RENDER_JS.read_text(encoding="utf-8")]
    partes += scripts_inline(PLANTILLA.read_text(encoding="utf-8"))
    partes.append(
        "var fotoDePrueba = %s;\n"
        "if (!window.tablero || !window.tablero.%s) {\n"
        "  throw new Error('la plantilla no expone window.tablero.%s');\n"
        "}\n"
        "process.stdout.write(String(window.tablero.%s(fotoDePrueba)));"
        % (json.dumps(foto, ensure_ascii=False), funcion, funcion, funcion)
    )
    with tempfile.TemporaryDirectory() as tmp:
        guion = Path(tmp) / "pintar.js"
        guion.write_text("\n".join(partes), encoding="utf-8")
        hecho = subprocess.run([node, str(guion)], capture_output=True, text=True)
    if hecho.returncode != 0:
        raise AssertionError("la plantilla no pudo pintar %s:\n%s"
                             % (funcion, hecho.stderr))
    return hecho.stdout


PUERTOS = {"visor de contratos": 8766, "visor de presentaciones": 9043,
           "visor de flujos": 8765}


def foto_sintetica(vivas=("visor de contratos", "visor de presentaciones",
                          "visor de flujos")):
    """Una foto con la forma exacta de `/estado.json`, con las webs que se digan."""
    return {
        "generado": "2026-08-25T09:00:00+00:00",
        "cabecera": {
            "estado": "ok", "leido": "2026-08-25T09:00:00+00:00",
            "servidores": {
                "estado": "ok", "detalle": "",
                "lista": [{"servicio": s, "puerto": PUERTOS[s], "pid": 1,
                           "arbol": "main"} for s in vivas],
            },
        },
        "ahora": {
            "estado": "ok", "leido": "2026-08-25T09:00:00+00:00",
            "vivos": [{"unidad": "100-en-obra", "rol": "constructor",
                       "modelo": "claude-opus-5", "minutos": 12,
                       "avatar": "constructor", "checkpoint": None,
                       "ficheros": [], "ficheros_estado": "ok"}],
            "terminados_hoy": [{"unidad": "104-ya-termino", "rol": "revisor",
                                "modelo": "claude-opus-5", "minutos": 30,
                                "avatar": "revisor", "resultado": "ok"}],
        },
        "te_toca": {
            "estado": "ok", "leido": "2026-08-25T09:00:00+00:00",
            "contratos": [{"unidad": "103-sin-aprobar", "titulo": "103-sin-aprobar",
                           "tipo": "feature", "origen": "trabajo",
                           "estado": "planificada", "desde": "2026-08-21",
                           "dias": 4,
                           "enlace": "http://127.0.0.1:8766/#103-sin-aprobar"}],
            "en_validacion": [{"unidad": "104-en-validacion",
                               "titulo": "104-en-validacion", "tipo": "feature",
                               "origen": "trabajo", "estado": "en_validacion",
                               "desde": "2026-08-22", "dias": 3,
                               "enlace": "/doc/docs/05-trabajo/104/especificacion.md"}],
            "peticiones": [{"id": "P-20260820-aaaaaaaa", "estado": "capturada",
                            "resumen": "Quiero un tablero", "dias": 5,
                            "enlace": None}],
        },
        "por_hacer": {
            "estado": "ok", "leido": "2026-08-25T09:00:00+00:00",
            "unidades": [{"unidad": "101-planificada", "carpeta": "101-planificada",
                          "origen": "trabajo", "tipo": "feature",
                          "carril": "normal", "estado": "planificada",
                          "actividad": "construir-unidad", "aprobado": "2026-08-24",
                          "pendiente_de_aprobar": False, "actualizado": "2026-08-24",
                          "fusion": "", "ficheros": ["api/rutas.py"],
                          "plan": {"hechos": 1, "total": 4},
                          "fase": "planificada", "bloqueo": None,
                          "ficha": "docs/05-trabajo/101-planificada/especificacion.md",
                          "enlace": "/doc/docs/05-trabajo/101-planificada/especificacion.md"}],
            "peticiones": {"evaluando": [{"id": "P-20260822-cccccccc",
                                          "estado": "evaluando",
                                          "resumen": "En evaluación", "dias": 3}]},
            "peticiones_estado": "ok",
        },
    }


# --------------------------------------------------------------------------- R1

class TresSeccionesYNadaDuplicadoTest(unittest.TestCase):
    """R1 — el tablero deja de duplicar el visor de contratos y presentaciones."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="tablero-067-")
        cls.raiz = workspace_sintetico(cls.tmp)
        cls.servidor = ServidorDePrueba(cls.raiz)
        _, _, cls.html = cls.servidor.pedir("/")
        _, _, cuerpo = cls.servidor.pedir("/estado.json")
        cls.foto = json.loads(cuerpo)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_el_menu_servido_tiene_exactamente_tres_entradas(self):
        entradas = menu_de(self.html)
        self.assertEqual(["ahora", "te-toca", "por-hacer"],
                         [e.get("data-seccion") for e in entradas])

    def test_no_queda_ni_rastro_de_historial_ni_de_documentacion(self):
        for muerta in ('href="#historial"', 'href="#documentacion"',
                       ">Historial<", ">Documentación<"):
            with self.subTest(muerta=muerta):
                self.assertFalse(muerta in self.html,
                                 "el HTML servido todavía pinta %s" % muerta)

    def test_la_fuente_de_datos_sigue_calculando_historial_y_documentacion(self):
        """`estado.py` y `/estado.json` NO se tocan: sólo deja de pintarse."""
        self.assertIn("historial", self.foto)
        self.assertIn("documentacion", self.foto)
        self.assertTrue(self.foto["documentacion"]["ficheros"])


# --------------------------------------------------------------------------- R3

class BarraComunTest(unittest.TestCase):
    """R3 — la misma barra en las tres plantillas, con la actual marcada."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="tablero-067b-")
        cls.raiz = workspace_sintetico(cls.tmp)
        cls.servidor = ServidorDePrueba(cls.raiz)
        _, _, cls.html = cls.servidor.pedir("/")

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_el_html_servido_trae_las_cuatro_webs_en_orden(self):
        enlaces = barra_de(self.html)
        self.assertEqual([w[0] for w in WEBS],
                         [e.get("data-web") for e in enlaces])
        self.assertEqual([w[1] for w in WEBS], [e.get("href") for e in enlaces])
        self.assertEqual([w[2] for w in WEBS],
                         [e["texto"].strip() for e in enlaces])

    def test_el_tablero_se_marca_a_si_mismo_y_solo_a_si_mismo(self):
        enlaces = barra_de(self.html)
        marcados = [e for e in enlaces if e.get("aria-current") == "page"]
        self.assertEqual(1, len(marcados))
        self.assertEqual("tablero", marcados[0].get("data-web"))
        self.assertIn("actual", (marcados[0].get("class") or ""))

    def test_las_otras_dos_plantillas_llevan_la_misma_barra(self):
        for plantilla, quien in ((PLANTILLA_CONTRATOS, "contratos"),
                                 (PLANTILLA_056, "presentaciones")):
            with self.subTest(web=quien):
                enlaces = barra_de(plantilla.read_text(encoding="utf-8"))
                self.assertEqual([w[0] for w in WEBS],
                                 [e.get("data-web") for e in enlaces])
                self.assertEqual([w[1] for w in WEBS],
                                 [e.get("href") for e in enlaces])
                marcados = [e for e in enlaces if e.get("aria-current") == "page"]
                self.assertEqual(1, len(marcados))
                self.assertEqual(quien, marcados[0].get("data-web"))

    def test_la_marca_y_el_interruptor_son_los_de_siempre(self):
        self.assertTrue("ingeniería de requisitos · tablero de control" in self.html,
                        "falta la marca común")
        self.assertTrue('var GUARDADO = "visor-tema";' in self.html,
                        "falta el interruptor de tema compartido")


# --------------------------------------------------------------------------- R4

class MismoEsqueletoQueLa056Test(unittest.TestCase):
    """R4 — estilos idénticos línea a línea y navegación por hash."""

    def setUp(self):
        self.tablero = PLANTILLA.read_text(encoding="utf-8")
        self.presentaciones = PLANTILLA_056.read_text(encoding="utf-8")
        self.contratos = PLANTILLA_CONTRATOS.read_text(encoding="utf-8")

    def test_el_bloque_comun_de_estilos_es_el_mismo_linea_a_linea(self):
        esperado = bloque_comun(self.presentaciones)
        self.assertGreater(len(esperado), 60, "el bloque de la 056 no se leyó")
        self.assertEqual(esperado, bloque_comun(self.contratos))
        self.assertEqual(esperado, bloque_comun(self.tablero))

    def test_la_barra_comun_se_estila_igual_en_las_tres(self):
        for nombre, texto in (("tablero", self.tablero),
                              ("contratos", self.contratos),
                              ("presentaciones", self.presentaciones)):
            with self.subTest(web=nombre):
                self.assertTrue(".barra-webs a.actual" in texto,
                                "%s no estila la barra común" % nombre)
        self.assertTrue(".barra-webs a.actual" in "\n".join(bloque_comun(self.tablero)),
                        "la barra se estila fuera del bloque común")

    def test_las_tres_secciones_van_por_hash_con_enlaces_de_verdad(self):
        entradas = menu_de(self.tablero)
        self.assertEqual(["#ahora", "#te-toca", "#por-hacer"],
                         [e.get("href") for e in entradas])

    def test_el_menu_lleva_el_recuento_de_cada_seccion(self):
        entradas = menu_de(self.tablero)
        self.assertEqual(["ahora", "te-toca", "por-hacer"],
                         [e.get("data-recuento") for e in
                          _recuentos(self.tablero)])
        self.assertEqual(3, len(entradas))


class _Recuentos(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.marcas = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if atributos.get("data-recuento"):
            self.marcas.append(atributos)


def _recuentos(texto):
    parser = _Recuentos()
    parser.feed(texto)
    parser.close()
    return parser.marcas


# --------------------------------------------------------------------------- R2

class CadaCosaLlevaASuWebTest(unittest.TestCase):
    """R2 — enlaces a la web donde se hace, y aviso si esa web está apagada."""

    def test_el_contrato_por_aprobar_enlaza_al_visor_de_contratos(self):
        pintado = pintar("pintarTeToca", foto_sintetica())
        self.assertIn('href="http://127.0.0.1:8766/contrato/103-sin-aprobar.md"',
                      pintado)

    def test_la_entrega_en_validacion_enlaza_a_presentaciones(self):
        pintado = pintar("pintarTeToca", foto_sintetica())
        self.assertIn('href="http://127.0.0.1:9043/', pintado)

    def test_ninguna_linea_apunta_ya_al_lector_de_documentos_del_tablero(self):
        for funcion in ("pintarTeToca", "pintarPorHacer"):
            with self.subTest(funcion=funcion):
                self.assertNotIn('href="/doc/', pintar(funcion, foto_sintetica()))

    def test_por_hacer_enlaza_la_unidad_a_su_contrato_y_su_flujo(self):
        pintado = pintar("pintarPorHacer", foto_sintetica())
        self.assertIn('href="http://127.0.0.1:8766/contrato/101-planificada.md"',
                      pintado)
        self.assertIn('href="http://127.0.0.1:8765/', pintado)

    def test_con_las_webs_vivas_no_se_avisa_de_nada(self):
        self.assertNotIn("web apagada", pintar("pintarTeToca", foto_sintetica()))

    def test_la_web_apagada_se_dice_al_lado_en_vez_de_dejar_el_enlace_muerto(self):
        foto = foto_sintetica(vivas=("visor de presentaciones",))
        pintado = pintar("pintarTeToca", foto)
        self.assertIn("web apagada", pintado)
        self.assertIn("pídele a tu IA que la abra", pintado)
        # la que sí está levantada no se marca como apagada
        self.assertEqual(1, pintado.count("web apagada"))

    def test_si_no_se_pudo_mirar_los_puertos_no_se_declara_nada_apagado(self):
        foto = foto_sintetica()
        foto["cabecera"]["servidores"] = {"estado": "no_comprobable",
                                          "lista": [],
                                          "detalle": "no pude mirar los puertos"}
        self.assertNotIn("web apagada", pintar("pintarTeToca", foto))


# --------------------------------------------------------------------------- R5

class AhoraSinRuidoTest(unittest.TestCase):
    """R5 — sólo los vivos; los terminados del día, plegados."""

    def test_los_terminados_van_dentro_de_un_plegable(self):
        pintado = pintar("pintarAhora", foto_sintetica())
        self.assertIn("<details", pintado)
        self.assertLess(pintado.index("100-en-obra"), pintado.index("<details"))
        self.assertGreater(pintado.index("104-ya-termino"), pintado.index("<details"))

    def test_el_plegable_dice_cuantos_terminaron_y_arranca_cerrado(self):
        pintado = pintar("pintarAhora", foto_sintetica())
        apertura = pintado[pintado.index("<details"):pintado.index(">", pintado.index("<details"))]
        self.assertNotIn("open", apertura, "el plegable no puede arrancar abierto")
        resumen = pintado[pintado.index("<summary"):pintado.index("</summary>")]
        self.assertIn("1", resumen)


# --------------------------------------------------------------------------- todo junto

class LaFotoRealSePintaTest(unittest.TestCase):
    """La foto que sirve DE VERDAD el tablero pasa por las tres secciones."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="tablero-067c-")
        cls.raiz = workspace_sintetico(cls.tmp)
        agente(cls.raiz, "100-en-obra", "constructor", "s-viva-067",
               os.getpid(), minutos=9)
        cls.servidor = ServidorDePrueba(cls.raiz)
        _, _, cuerpo = cls.servidor.pedir("/estado.json")
        cls.foto = json.loads(cuerpo)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_las_tres_secciones_se_pintan_con_la_foto_real(self):
        for funcion in ("pintarAhora", "pintarTeToca", "pintarPorHacer"):
            with self.subTest(funcion=funcion):
                self.assertTrue(pintar(funcion, self.foto).strip())

    def test_el_contrato_sin_aprobar_del_workspace_real_apunta_al_visor(self):
        pintado = pintar("pintarTeToca", self.foto)
        self.assertIn("/contrato/103-sin-aprobar.md", pintado)
        self.assertIn("/contrato/200-bug-abierto.md", pintado)


if __name__ == "__main__":
    unittest.main()
