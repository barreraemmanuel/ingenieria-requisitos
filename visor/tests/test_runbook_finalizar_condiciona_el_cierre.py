"""Bug 116: la orden de relevo («cierra esta sesión y abre una nueva») solo con finalizar en verde.

En el E2E de clínica (auditoría 112) el harness de requisitos no pudo abrir el visor,
`requisitos.py aprobar` y `finalizar.py` quedaron bloqueados y, aun así, dio la orden de
cerrar la sesión y abrir la de construcción: el paso 7 de finalizar (`RUNBOOK/fases.md`)
no estaba condicionado al paso 6. Aquí se fija la prosa: el paso 7 nombra la condición y
dice qué hacer cuando finalizar está bloqueado.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FASES = RAIZ / "RUNBOOK" / "fases.md"


def paso_7_de_finalizar():
    texto = FASES.read_text(encoding="utf-8")
    inicio = texto.index("finaliza con `visor/finalizar.py`")
    encontrado = re.search(r"(?ms)^7\. .*?(?=^\S)", texto[inicio:])
    assert encontrado, "fases.md ya no tiene el paso 7 de finalizar"
    return encontrado.group(0)


class RelevoSoloConFinalizarEnVerdeTest(unittest.TestCase):
    def test_el_paso_7_condiciona_la_orden_de_cerrar_a_finalizar_en_verde(self):
        paso = paso_7_de_finalizar()
        self.assertIn("cerrar esta sesión", paso)
        self.assertRegex(
            paso, r"finalizar\.py[^.]*(en verde|ha terminado|haya terminado)",
            "bug 116: el paso 7 manda cerrar la sesión sin exigir que finalizar.py haya "
            "terminado en verde",
        )

    def test_el_paso_7_dice_que_hacer_si_finalizar_esta_bloqueado(self):
        paso = paso_7_de_finalizar()
        self.assertRegex(
            paso, r"(?i)bloquea",
            "bug 116: el paso 7 no dice qué hacer cuando requisitos.py/finalizar.py se bloquean",
        )
        self.assertRegex(
            paso, r"(?i)no (le )?(mandes|digas|pidas)[^.]*cerrar",
            "bug 116: el paso 7 no prohíbe la orden de cerrar con finalizar bloqueado",
        )


if __name__ == "__main__":
    unittest.main()
