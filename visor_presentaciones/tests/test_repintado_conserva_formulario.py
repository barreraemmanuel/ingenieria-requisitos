"""Bug 154 (issue #117): el refresco periódico de la web de entregas (`setInterval(cargar,
10000)`) volvía a pintar la sección entera, textarea del problema incluido: lo tecleado se
perdía y el foco saltaba. El refresco no toca el formulario que tiene foco, texto o una
opción elegida sin enviar, y sigue actualizando el resto (listado y contador)."""

import re
import unittest
from pathlib import Path

PLANTILLA = Path(__file__).resolve().parents[1] / "plantilla.html"


class ElRefrescoNoPisaLoQueEscribesTest(unittest.TestCase):

    def setUp(self):
        self.html = PLANTILLA.read_text(encoding="utf-8")

    def cuerpo_de(self, nombre):
        inicio = self.html.index("function " + nombre + "(")
        fin = self.html.index("\n  }\n", inicio)
        return self.html[inicio:fin]

    def test_hay_una_sola_pregunta_de_si_se_esta_editando(self):
        cuerpo = self.cuerpo_de("editandoDecision")
        # Las tres señales: texto en el comentario, una opción elegida, o el foco dentro.
        self.assertIn("#comentario", cuerpo)
        self.assertIn(":checked", cuerpo)
        self.assertIn("activeElement", cuerpo)
        # Un formulario ya enviado (bloqueado) no cuenta como edición en curso.
        self.assertIn("disabled", cuerpo)

    def test_el_refresco_periodico_pregunta_antes_de_repintar_el_panel(self):
        cargar = self.cuerpo_de("cargar")
        self.assertIn("editandoDecision()", cargar)
        # El listado y el contador se actualizan igual…
        self.assertIn("pintarListado()", cargar)
        # …pero `abrir(` (el repintado del panel) solo corre si no se está editando.
        self.assertRegex(cargar, r"if \(!editandoDecision\(\)\)[\s\S]*?abrir\(")

    def test_el_refresco_es_el_unico_repintado_periodico(self):
        self.assertEqual(len(re.findall(r"setInterval\(", self.html)), 1)


if __name__ == "__main__":
    unittest.main()
