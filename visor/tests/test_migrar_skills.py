import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
MIGRAR = RAIZ / "visor/migrar_skills.py"


class MigrarSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="migrar-skills-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / "demo-agents"
        self.workspace.mkdir()

    def skill(self, raiz, nombre, contenido):
        destino = self.workspace / raiz / nombre
        destino.mkdir(parents=True)
        (destino / "SKILL.md").write_text(contenido, encoding="utf-8")
        return destino

    def ejecutar(self, *args):
        return subprocess.run(
            [sys.executable, str(MIGRAR), *args],
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    def test_dry_run_no_mueve_y_aplicar_preserva_allowlist_tecnica(self):
        proceso = self.skill(".agents/skills", "using-superpowers", "proceso\n")
        deploy = self.skill(".claude/skills", "deploy", "rol de proceso\n")
        tecnica = self.skill(".agents/skills", "vue-testing", "dominio técnico\n")

        dry = self.ejecutar(
            "revisar", str(self.workspace), "--permitir", "vue-testing"
        )
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertTrue(proceso.is_dir())
        self.assertTrue(deploy.is_dir())
        self.assertTrue(tecnica.is_dir())

        aplicar = self.ejecutar(
            "aplicar", str(self.workspace), "--permitir", "vue-testing"
        )
        self.assertEqual(aplicar.returncode, 0, aplicar.stdout + aplicar.stderr)
        self.assertFalse(proceso.exists())
        self.assertFalse(deploy.exists())
        self.assertTrue(tecnica.is_dir())
        recibo = self.workspace / ".private/skills-retiradas/RECIBO.json"
        datos = json.loads(recibo.read_text(encoding="utf-8"))
        self.assertEqual({m["nombre"] for m in datos["movimientos"]}, {"using-superpowers", "deploy"})
        self.assertNotIn("proceso\n", recibo.read_text(encoding="utf-8"))

        restaurar = self.ejecutar("restaurar", str(self.workspace))
        self.assertEqual(restaurar.returncode, 0, restaurar.stdout + restaurar.stderr)
        self.assertTrue(proceso.is_dir())
        self.assertTrue(deploy.is_dir())
        self.assertFalse(recibo.exists())

    def test_skill_no_clasificada_se_retira_por_defecto_sin_borrarse(self):
        desconocida = self.skill(".codex/skills", "mi-helper", "contenido\n")

        resultado = self.ejecutar("aplicar", str(self.workspace))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(desconocida.exists())
        retirada = self.workspace / ".private/skills-retiradas/codex/mi-helper/SKILL.md"
        self.assertEqual(retirada.read_text(encoding="utf-8"), "contenido\n")


if __name__ == "__main__":
    unittest.main()
