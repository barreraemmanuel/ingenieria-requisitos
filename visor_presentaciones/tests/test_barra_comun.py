"""Bug 067 + unidad 081 — la barra común, ahora en la CÁSCARA de la web única.

El 067 pedía una misma barra «Tablero · Contratos · Presentaciones · Flujos» con la
web actual marcada. La 081 la deja donde debía estar desde el principio: escrita UNA
vez, en `web/plantilla.html`, con rutas relativas del mismo origen en vez de cuatro
puertos. Aquí se comprueba, desde el apartado presentaciones:

- la plantilla de este apartado ya NO lleva barra propia ni puertos: lleva el hueco
  `<!-- apartado:barra -->` donde la cáscara le encaja la común;
- la cáscara declara los cuatro apartados, en orden, como rutas relativas;
- `web/servir.py` marca este apartado —y sólo este— al servirlo.
"""

import html.parser
import importlib.util
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MIA = RAIZ / "visor_presentaciones" / "plantilla.html"
CASCARA = RAIZ / "web" / "plantilla.html"
APARTADOS = (RAIZ / "visor_tablero" / "plantilla.html",
             RAIZ / "visor_contratos" / "plantilla.html",
             RAIZ / "visor_presentaciones" / "plantilla.html",
             RAIZ / "visor" / "plantilla.html")
YO = "presentaciones"

WEBS = (
    ("tablero", "/", "Inicio"),
    ("contratos", "/contratos", "Contratos"),
    ("presentaciones", "/presentaciones", "Entregas"),
    ("flujos", "/flujos", "Flujos"),
)


def _cargar_servir():
    spec = importlib.util.spec_from_file_location(
        "web_servir_barra_presentaciones", RAIZ / "web" / "servir.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


servir = _cargar_servir()


class _Barra(html.parser.HTMLParser):
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


class BarraComunTest(unittest.TestCase):

    def test_esta_plantilla_ya_no_lleva_barra_propia_ni_puertos(self):
        texto = MIA.read_text(encoding="utf-8")
        self.assertIn("<!-- apartado:barra -->", texto,
                      "falta el hueco donde la cáscara encaja la barra común")
        self.assertEqual([], barra_de(texto), "sigue llevando barra propia")
        self.assertNotIn("127.0.0.1:", texto, "sigue nombrando un puerto")

    def test_la_cascara_declara_los_cuatro_apartados_en_orden(self):
        enlaces = barra_de(CASCARA.read_text(encoding="utf-8"))
        self.assertEqual([w[0] for w in WEBS],
                         [e.get("data-web") for e in enlaces])
        self.assertEqual([w[1] for w in WEBS],
                         [e.get("href") for e in enlaces])
        self.assertEqual([w[2] for w in WEBS],
                         [e["texto"].strip() for e in enlaces])

    def test_la_barra_servida_marca_este_apartado_y_solo_este(self):
        enlaces = barra_de(servir.barra(YO))
        marcados = [e for e in enlaces if e.get("aria-current") == "page"]
        self.assertEqual(1, len(marcados))
        self.assertEqual(YO, marcados[0].get("data-web"))
        self.assertIn("actual", (marcados[0].get("class") or ""))

    def test_los_cuatro_apartados_llevan_el_mismo_hueco(self):
        for plantilla in APARTADOS:
            with self.subTest(apartado=plantilla.parent.name):
                texto = plantilla.read_text(encoding="utf-8")
                self.assertIn("<!-- apartado:barra -->", texto)
                self.assertEqual([], barra_de(texto))

    def test_la_marca_y_el_interruptor_de_tema_siguen_siendo_los_comunes(self):
        texto = MIA.read_text(encoding="utf-8")
        self.assertTrue("ingeniería de requisitos · " in texto, "falta la marca")
        self.assertTrue('var GUARDADO = "visor-tema";' in
                        CASCARA.read_text(encoding="utf-8"),
                        "la cáscara perdió el interruptor compartido")

    def test_la_barra_se_estila_en_la_hoja_comun(self):
        """Desde la 076 el estilo de la barra vive en `visor/base.css`.

        Ninguna plantilla la estila por su cuenta, y la cáscara enlaza la hoja.
        """
        hoja = (RAIZ / "visor" / "base.css").read_text(encoding="utf-8")
        self.assertIn(".barra-webs a.actual", hoja)
        self.assertIn('<link rel="stylesheet" href="/base.css">',
                      CASCARA.read_text(encoding="utf-8"))
        for plantilla in APARTADOS:
            with self.subTest(plantilla=plantilla.parent.name):
                self.assertNotIn(".barra-webs",
                                 plantilla.read_text(encoding="utf-8"),
                                 "%s estila la barra por su cuenta"
                                 % plantilla.parent.name)


if __name__ == "__main__":
    unittest.main()
