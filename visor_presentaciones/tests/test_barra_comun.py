"""Bug 067 — la barra común de las cuatro webs, en el visor de presentaciones.

R3 del contrato: una misma barra superior «Tablero · Contratos · Presentaciones
· Flujos», con la web actual marcada, en el tablero, en el visor de contratos y
en presentaciones. Aquí se comprueba la de ESTA web y que es, marcado a
marcado, la misma que la de las otras dos.
"""

import html.parser
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MIA = RAIZ / "visor_presentaciones" / "plantilla.html"
OTRAS = (
    ("tablero", RAIZ / "visor_tablero" / "plantilla.html"),
    ("contratos", RAIZ / "visor_contratos" / "plantilla.html"),
    ("presentaciones", RAIZ / "visor_presentaciones" / "plantilla.html"),
)
YO = "presentaciones"

WEBS = (
    ("tablero", "http://127.0.0.1:8768/", "Tablero"),
    ("contratos", "http://127.0.0.1:8766/", "Contratos"),
    ("presentaciones", "http://127.0.0.1:9043/", "Presentaciones"),
    ("flujos", "http://127.0.0.1:8765/", "Flujos"),
)


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


def barra_de(ruta):
    parser = _Barra()
    parser.feed(ruta.read_text(encoding="utf-8"))
    parser.close()
    return parser.enlaces


class BarraComunTest(unittest.TestCase):

    def setUp(self):
        self.enlaces = barra_de(MIA)

    def test_estan_las_cuatro_webs_en_orden_y_con_su_puerto(self):
        self.assertEqual([w[0] for w in WEBS],
                         [e.get("data-web") for e in self.enlaces])
        self.assertEqual([w[1] for w in WEBS],
                         [e.get("href") for e in self.enlaces])
        self.assertEqual([w[2] for w in WEBS],
                         [e["texto"].strip() for e in self.enlaces])

    def test_esta_web_es_la_unica_marcada(self):
        marcados = [e for e in self.enlaces if e.get("aria-current") == "page"]
        self.assertEqual(1, len(marcados))
        self.assertEqual(YO, marcados[0].get("data-web"))
        self.assertIn("actual", (marcados[0].get("class") or ""))

    def test_las_tres_plantillas_llevan_el_mismo_marcado(self):
        for quien, plantilla in OTRAS:
            with self.subTest(web=quien):
                enlaces = barra_de(plantilla)
                self.assertEqual(
                    [(w[0], w[1], w[2]) for w in WEBS],
                    [(e.get("data-web"), e.get("href"), e["texto"].strip())
                     for e in enlaces])
                marcados = [e for e in enlaces if e.get("aria-current") == "page"]
                self.assertEqual([quien], [e.get("data-web") for e in marcados])

    def test_la_marca_y_el_interruptor_de_tema_siguen_siendo_los_comunes(self):
        texto = MIA.read_text(encoding="utf-8")
        self.assertTrue("ingeniería de requisitos · " in texto, "falta la marca")
        self.assertTrue('var GUARDADO = "visor-tema";' in texto,
                        "falta el interruptor compartido")

    def test_la_barra_se_estila_en_la_hoja_comun(self):
        """Desde la 076 el estilo de la barra vive en `visor/base.css`.

        Antes se comprobaba que estuviera COPIADO en cada plantilla; ahora, lo
        contrario: que no lo esté en ninguna y sí en la hoja que las tres
        enlazan.
        """
        hoja = (RAIZ / "visor" / "base.css").read_text(encoding="utf-8")
        self.assertIn(".barra-webs a.actual", hoja)
        for _, plantilla in OTRAS:
            with self.subTest(plantilla=plantilla.parent.name):
                texto = plantilla.read_text(encoding="utf-8")
                self.assertIn('<link rel="stylesheet" href="/base.css">', texto,
                              "%s no enlaza la hoja común" % plantilla.parent.name)
                self.assertNotIn(
                    ".barra-webs", texto,
                    "%s estila la barra por su cuenta" % plantilla.parent.name)


if __name__ == "__main__":
    unittest.main()
