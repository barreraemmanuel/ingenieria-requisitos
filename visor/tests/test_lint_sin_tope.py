"""Bug 061 — el linter no impone un tope numérico de unidades en vuelo (ADR-027).

Lo que sí bloquea es que dos unidades en vuelo compartan ficheros declarados. Con cuatro
unidades disjuntas en obra solo hay un aviso; con dos que comparten un fichero, FAIL.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts/lint_metodo.py"


class SinTopeNumericoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-sin-tope-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / "docs/05-trabajo").mkdir(parents=True)
        (self.raiz / "worktrees").mkdir()

    def unidad(self, nombre, ficheros):
        carpeta = self.raiz / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        (self.raiz / "worktrees" / nombre).mkdir(exist_ok=True)
        (carpeta / "especificacion.md").write_text(
            "---\n"
            f"unidad: {nombre}\n"
            "tipo: feature\n"
            "carril: normal\n"
            "estado: en_obra\n"
            "aprobado: 2026-08-25\n"
            f"ficheros: [{', '.join(ficheros)}]\n"
            "peticiones: []\n"
            "actualizado: 2026-08-25\n"
            "---\n\n"
            f"# {nombre}\n\n## Verificación\n\n- **Criterio portante:** R-1\n",
            encoding="utf-8",
        )

    def lint(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--raiz", str(self.raiz)],
                           capture_output=True, text=True, encoding="utf-8")
        return r.stdout + r.stderr

    def test_cuatro_unidades_disjuntas_en_vuelo_no_son_un_fail(self):
        for i, f in enumerate(("a.py", "b.py", "c.py", "d.py"), start=1):
            self.unidad(f"00{i}-unidad-{i}", [f])
        salida = self.lint()
        self.assertNotIn("tope absoluto", salida, "el ADR-027 quitó el tope numérico")
        self.assertIn("unidades en vuelo", salida, "el aviso informativo sí tiene que salir")

    def test_dos_unidades_que_comparten_un_fichero_siguen_siendo_fail(self):
        self.unidad("001-unidad-1", ["a.py", "comun.py"])
        self.unidad("002-unidad-2", ["comun.py"])
        salida = self.lint()
        self.assertIn("comparten ficheros declarados", salida)


if __name__ == "__main__":
    unittest.main()
