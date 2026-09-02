"""R1/R3b: auditoría por frontmatter, no por el nombre de la carpeta."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"


class LintDeployAuditoriaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-deploy-auditoria-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in ("lint_deploy.py", "repo_config.py", "workspace_paths.py"):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        (self.ws / "repos.yaml").write_text(
            "codigo:\n  ruta_local: main/\n  rama_principal: main\n", encoding="utf-8"
        )
        (self.ws / "docs/conocimiento").mkdir(parents=True)
        (self.ws / "docs/conocimiento/plano-deploy.md").write_text(
            "# Deploy\n\n| Clave | Valor |\n|---|---|\n"
            "| etapa | internet |\n| camino | scripts/deploy |\n"
            "| vuelta_atras | git revert HEAD |\n| datos | SIN DATOS |\n"
            "| vigilancia | logs |\n", encoding="utf-8",
        )
        (self.ws / "docs/05-trabajo/archivo").mkdir(parents=True)
        self.main = self.ws / "main"
        self.main.mkdir()
        self.git_env = dict(os.environ)
        self.git_env.update({
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        })
        self.git("init", "-b", "main")
        (self.main / "README.md").write_text("# demo\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.main), *args], check=True,
                       capture_output=True, env=self.git_env)

    def unidad(self, slug, tipo):
        carpeta = self.ws / "docs/05-trabajo/archivo" / slug
        carpeta.mkdir()
        (carpeta / "especificacion.md").write_text(
            f"---\nunidad: {slug}\ntipo: {tipo}\nestado: mergeada\n---\n",
            encoding="utf-8",
        )
        (carpeta / "informe.md").write_text("# Informe\n\nResultado.\n", encoding="utf-8")

    def ejecutar(self, json_=False):
        orden = [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_deploy.py")]
        if json_:
            orden.append("--json")
        return subprocess.run(
            orden, cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, env=self.git_env,
        )

    def test_tipo_auditoria_con_informe_cuenta_aunque_el_slug_no_lo_diga(self):
        self.unidad("042-revision-owasp", "auditoria")
        salida = self.ejecutar().stdout
        self.assertNotIn("sin auditoría de seguridad archivada", salida)
        self.assertIn("auditoría de seguridad archivada: 042-revision-owasp", salida)

    def test_slug_auditoria_seguridad_no_cuenta_si_el_tipo_no_es_auditoria(self):
        self.unidad("043-auditoria-seguridad-de-mentira", "feature")
        salida = self.ejecutar().stdout
        self.assertIn("sin auditoría de seguridad archivada", salida)

    def test_json_de_deploy_usa_el_mismo_esquema(self):
        datos = json.loads(self.ejecutar(json_=True).stdout)
        self.assertEqual(datos["schema"], "lint-hallazgos/v1")
        for hallazgo in datos["hallazgos"]:
            self.assertEqual(
                set(hallazgo), {"id", "severidad", "sujeto", "ruta", "instancia"}
            )


if __name__ == "__main__":
    unittest.main()
