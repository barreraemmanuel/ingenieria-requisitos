"""Unidad 159: un retoque visual sin regla va por la vía corta —exprés en lote «a la vista»—,
el agente lo OFRECE en su primera respuesta, el parte es una línea por retoque, y lo que
cambia comportamiento sale del lote y sube a directo. Aquí se fija la prosa de los tres
ficheros que lo dicen (los runbooks se testean como el resto)."""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
METODO = RAIZ / "plantilla" / "docs" / "00-metodo"
EXPRES = METODO / "runbooks" / "expres.md"
PETICIONES = METODO / "runbooks" / "peticiones.md"
COMUNICACION = METODO / "comunicacion.md"


def leer(ruta):
    return ruta.read_text(encoding="utf-8")


class RetoquesVisualesEnLoteALaVistaTest(unittest.TestCase):

    def test_r1_expres_tiene_la_fila_y_el_bloque_del_lote(self):
        texto = leer(EXPRES)
        tabla = texto[texto.index("| SÍ | NO |"):texto.index("## El flujo")]
        self.assertRegex(tabla, r"(?i)retoque visual sin regla[^\n]*SÍ, en lote «a la vista»")
        self.assertIn("## Retoques visuales: el lote «a la vista»", texto)
        bloque = texto[texto.index("## Retoques visuales"):texto.index("## El flujo")]
        for frase in ("esto va por la vía corta: lo cambio y te lo enseño",
                      "Una captura por lote", "peticion.py capturar", "abrir-expres",
                      "Cada retoque se enseña antes del siguiente", "Sin ficha, sin `NNN`"):
            self.assertIn(frase, bloque, frase)

    def test_r1_peticiones_manda_ofrecer_la_via_corta_en_la_primera_respuesta(self):
        texto = leer(PETICIONES)
        secuencia = texto[texto.index("## Secuencia"):texto.index("## Salidas sin obra")]
        self.assertIn("esto va por la vía corta: lo cambio y te lo enseño", secuencia)
        self.assertRegex(secuencia, r"(?i)ofrece[^\n]*la vía corta")
        self.assertRegex(secuencia, r"(?i)una sola captura para todo el lote")

    def test_r2_comunicacion_fija_el_parte_del_lote_y_su_cierre_sin_web(self):
        texto = leer(COMUNICACION)
        parte = texto[texto.index("## El parte de avance"):texto.index("## Pedir un OK")]
        self.assertIn("una línea por retoque", parte)
        self.assertIn("hecho · dónde mirarlo", parte)
        self.assertIn("sin OK por la web", parte)
        self.assertIn("mensaje de commit del lote", parte)

    def test_r3_lo_que_cambia_comportamiento_sale_del_lote_con_la_frase(self):
        texto = leer(EXPRES)
        self.assertIn("esto cambia comportamiento: lo saco del lote y va con ficha", texto)
        self.assertRegex(texto, r"(?i)lo sube a \*\*directo\*\*")
        # La regla 9 se conserva: un bug jamás es exprés.
        self.assertIn("Un bug sigue sin ser exprés nunca", texto)
        self.assertIn("**Un bug JAMÁS es exprés, sin excepciones.**", texto)


if __name__ == "__main__":
    unittest.main()
