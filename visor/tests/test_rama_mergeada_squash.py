"""rama_mergeada ante un squash cuyo título no nombra la rama (caso de campo, 04-08).

Los PR de campo se titulan «044: …» sin el slug entero; el squash hereda ese asunto y el
grep del cierre no lo ve: trabajo entregado que no se podía cerrar (cinco unidades de un mismo proyecto, y
el rodeo manual era verificar `git diff <rama> <sha>` vacío). La prueba fuerte es el árbol:
si la principal contiene un commit con el mismo árbol que la punta de la unidad, el trabajo
está dentro se llame como se llame el PR. Y al revés: trabajo posterior al squash NO puede
darse por fusionado.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts"
sys.path.insert(0, str(SCRIPTS))

import unidad  # noqa: E402


class RamaMergeadaSquashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="rama-mergeada-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "codigo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "app.py").write_text("v1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace"
        )

    def squash_sin_slug(self, rama):
        self.git("checkout", "-b", rama)
        (self.repo / "app.py").write_text("v2\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "trabajo 1")
        (self.repo / "extra.py").write_text("x\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "trabajo 2")
        self.git("checkout", "main")
        self.git("merge", "--squash", rama)
        self.git("commit", "-m", "044: contenedores con pilotos")  # sin el slug entero

    def test_squash_sin_slug_en_el_titulo_cuenta_como_mergeada(self):
        rama = "044-contenedores-luminosos"
        self.squash_sin_slug(rama)

        mergeada, motivo, fuerte, sha = unidad.rama_mergeada(self.repo, rama, "main")

        self.assertTrue(mergeada, motivo)
        self.assertTrue(fuerte, motivo)
        self.assertIn("MISMO árbol", motivo)
        self.assertTrue(sha)

    def test_trabajo_posterior_al_squash_no_se_da_por_mergeado(self):
        rama = "044-contenedores-luminosos"
        self.squash_sin_slug(rama)
        self.git("checkout", rama)
        (self.repo / "app.py").write_text("v3, sin fusionar\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "trabajo 3, posterior al squash")
        self.git("checkout", "main")

        mergeada, motivo, _, _ = unidad.rama_mergeada(self.repo, rama, "main")

        self.assertFalse(mergeada, motivo)


if __name__ == "__main__":
    unittest.main()
