"""El linter no llama «muerta» a una unidad fusionada (incidente de campo, 06-08).

Tras un fast-forward la rama queda con 0 commits por encima de la principal — la misma foto
que un constructor muerto a mitad. El discriminador es la bitácora: si la ficha acredita el
merge con `fusion: <sha>` y ese commit está dentro de la principal, no hay nada que
denunciar; sin esa acreditación, la denuncia sigue (ese caso SÍ es un constructor muerto).
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts"
DENUNCIA = "NI UN commit por encima"


class LintUnidadFusionadaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-fusionada-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in ("lint_metodo.py", "repo_config.py", "workspace_paths.py"):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        (self.ws / "repos.yaml").write_text(
            "ruta_local: main/\nrama_principal: main\n", encoding="utf-8"
        )
        self.repo = self.ws / "main"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "app.py").write_text("v1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")
        # La unidad trabaja y main la absorbe por fast-forward: rama contenida, 0 por encima.
        self.git("checkout", "-b", "044-mux")
        (self.repo / "app.py").write_text("v2\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "trabajo de la 044")
        self.git("checkout", "main")
        self.git("merge", "--ff-only", "044-mux")
        self.sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def ficha(self, extra=""):
        carpeta = self.ws / "docs/05-trabajo/044-mux"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "especificacion.md").write_text(
            "---\n"
            "unidad: 044-mux\n"
            "tipo: feature\n"
            "carril: normal\n"
            "estado: en_revision\n"
            "aprobado: 2026-08-06\n"
            "ficheros: []\n"
            "peticiones: []\n"
            "actualizado: 2026-08-06\n"
            f"{extra}"
            "---\n\n# 044 · mux\n",
            encoding="utf-8",
        )

    def lint(self):
        return subprocess.run(
            [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    def test_fusionada_con_fusion_anotada_no_es_muerta(self):
        self.ficha(extra=f"fusion: {self.sha}\n")

        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertIn("FAIL ·", salida)  # el linter llegó al final, no reventó a medias
        self.assertNotIn(DENUNCIA, salida)

    def test_sin_fusion_anotada_sigue_denunciando_al_constructor_muerto(self):
        self.ficha()

        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertIn("FAIL ·", salida)
        self.assertIn(DENUNCIA, salida)


if __name__ == "__main__":
    unittest.main()
