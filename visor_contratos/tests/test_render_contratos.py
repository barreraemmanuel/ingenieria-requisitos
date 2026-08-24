"""Bug 055 — el render markdown de la plantilla no puede quedarse en bucle.

El servidor entregaba el contrato en menos de un milisegundo y la página se quedaba
«pillada»: `bloques()` rompía el bucle de párrafo sin avanzar cuando una línea empezaba
por `*`, `-`, `#`, `>` o `|` y ninguna rama anterior la había consumido (negrita a
principio de párrafo, una raya `---`, un `# ` repetido). Estos tests extraen la función
de la plantilla y la ejecutan con node bajo un tope de tiempo: sin node, se saltan.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PLANTILLA = BASE / "plantilla.html"
NODE = shutil.which("node")
TOPE_SEGUNDOS = 5


def funciones_de_render():
    """El bloque de script que define `bloques()`, hasta `trocear` (sin DOM)."""
    html = PLANTILLA.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    script = next(s for s in scripts if "function bloques" in s)
    inicio = script.index("function esc")
    return script[inicio:script.index("function trocear")]


def renderizar(lineas):
    """Devuelve el HTML que produce `bloques(lineas)`; lanza si node no termina."""
    programa = funciones_de_render() + (
        "\nprocess.stdout.write(bloques(%s));" % json.dumps(lineas)
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fichero:
        fichero.write(programa)
        ruta = fichero.name
    try:
        salida = subprocess.run([NODE, ruta], capture_output=True, text=True,
                                timeout=TOPE_SEGUNDOS, check=True)
    finally:
        Path(ruta).unlink(missing_ok=True)
    return salida.stdout


@unittest.skipUnless(NODE, "sin node no se puede ejecutar el render de la plantilla")
class RenderNoSeCuelga(unittest.TestCase):

    def test_negrita_a_principio_de_parrafo(self):
        html = renderizar(["**El borrador** ya está escrito."])
        self.assertIn("<p><strong>El borrador</strong> ya está escrito.</p>", html)

    def test_raya_horizontal(self):
        html = renderizar(["antes", "---", "después"])
        self.assertIn("antes", html)
        self.assertIn("después", html)

    def test_titulo_de_nivel_uno_repetido(self):
        html = renderizar(["# Otro título", "texto"])
        self.assertIn("Otro título", html)
        self.assertIn("texto", html)

    def test_los_contratos_reales_del_workspace_se_pintan(self):
        raiz = BASE.parent.parent.parent / "docs" / "05-trabajo"
        contratos = sorted(raiz.glob("*/especificacion.md"))
        if not contratos:
            self.skipTest("este repo no tiene contratos al lado")
        for contrato in contratos:
            lineas = contrato.read_text(encoding="utf-8").split("\n")
            with self.subTest(contrato=contrato.parent.name):
                html = renderizar(lineas)
                self.assertTrue(html.strip(), "render vacío")

    def test_el_resto_del_render_sigue_igual(self):
        html = renderizar(["- uno", "- [x] dos", "", "| a | b |", "|---|---|", "| 1 | 2 |",
                           "", "> cita", "", "```", "código", "```"])
        for esperado in ("<ul>", 'class="tarea hecha"', "<table>", "<thead>",
                         "<blockquote>", "<pre><code>código</code></pre>"):
            self.assertIn(esperado, html)


if __name__ == "__main__":
    unittest.main()
