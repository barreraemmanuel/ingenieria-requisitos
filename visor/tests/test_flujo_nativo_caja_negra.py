import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
PLANTILLA = RAIZ / "plantilla"
CAJA_NEGRA = (
    PLANTILLA / "docs" / "00-metodo" / "scripts" / "caja_negra.py"
)


class FlujoNativoTest(unittest.TestCase):
    def test_feature_conversa_diseno_y_fija_un_unico_contrato_antes_de_delegar(self):
        runbook = (PLANTILLA / "docs/00-metodo/runbooks/feature.md").read_text(
            encoding="utf-8"
        )
        spec = (
            PLANTILLA / "docs/00-metodo/plantillas/especificacion.md"
        ).read_text(encoding="utf-8")

        self.assertIn("## Diseño conversado", spec)
        self.assertIn("Alternativas descartadas", spec)
        self.assertIn("Diseño aprobado por el usuario", spec)
        self.assertIn("Plan listo para despacho", spec)
        self.assertIn("un único contrato canónico", runbook)
        self.assertLess(runbook.index("Diseño conversado"), runbook.index("Despacho"))

    def test_bug_exige_bucle_semantico_antes_del_arreglo(self):
        runbook = (PLANTILLA / "docs/00-metodo/runbooks/bug.md").read_text(
            encoding="utf-8"
        )
        ficha = (PLANTILLA / "docs/00-metodo/plantillas/bug.md").read_text(
            encoding="utf-8"
        )

        for texto in ("Observación", "Hipótesis", "Experimento", "Conclusión"):
            self.assertIn(texto, ficha)
        self.assertIn("no se implementa", runbook.lower())
        self.assertIn("causa raíz", runbook.lower())

    def test_reemplazo_es_nativo_y_no_distribuye_skills_de_proceso(self):
        agents = (PLANTILLA / "AGENTS.md").read_text(encoding="utf-8")
        politica = (
            PLANTILLA / "docs/00-metodo/proceso-nativo.md"
        ).read_text(encoding="utf-8")

        self.assertIn("skills de proceso", agents.lower())
        self.assertIn("nativo", agents.lower())
        self.assertIn("skills técnicas", politica.lower())
        self.assertIn("fuente canónica", politica.lower())
        for ruta in (".agents/skills", ".claude/skills", ".codex/skills", "docs/superpowers"):
            self.assertFalse((PLANTILLA / ruta).exists(), ruta)
        historicos_superpowers = RAIZ / "docs/superpowers"
        self.assertFalse(
            historicos_superpowers.exists()
            and any(ruta.is_file() for ruta in historicos_superpowers.rglob("*")),
            "el repo de la herramienta aún contiene artefactos de proceso Superpowers",
        )


class CajaNegraE2ETest(unittest.TestCase):
    def test_redactor_no_fuga_dsn_cabeceras_cookies_userinfo_o_valores_citados(self):
        sentinel = "SENTINEL-ULTRAPRIVADO"
        texto = (
            f"postgres://admin:{sentinel}@prod/db "
            f"Authorization: Bearer {sentinel} Cookie: sid={sentinel} "
            f"Set-Cookie: sid={sentinel}; password='{sentinel} con espacios'"
        )
        with tempfile.TemporaryDirectory(prefix="caja-negra-secretos-") as temporal:
            repo = Path(temporal) / "repo"
            repo.mkdir()
            resultado = subprocess.run(
                [
                    sys.executable, str(CAJA_NEGRA), "registrar", "--repo", str(repo),
                    "--fase", "prueba", "--sintoma", texto,
                    "--esperado", texto, "--actual", texto, "--workaround", texto,
                ],
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
            )
            registro = (repo / ".caja-negra/incidentes.jsonl").read_text(encoding="utf-8")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn(sentinel, resultado.stdout + resultado.stderr + registro)

    def test_registra_identidad_de_ejecucion_y_redacta_secretos(self):
        with tempfile.TemporaryDirectory(prefix="caja-negra-e2e-") as temporal:
            repo = Path(temporal) / "demo-agents"
            repo.mkdir()
            subprocess.run(
                ["git", "init", "-q", "-b", "main"], cwd=repo, check=True
            )
            env = os.environ.copy()
            env["CODEX_THREAD_ID"] = "thread-demo"
            resultado = subprocess.run(
                [
                    sys.executable,
                    str(CAJA_NEGRA),
                    "registrar",
                    "--repo",
                    str(repo),
                    "--fase",
                    "despacho",
                    "--sintoma",
                    "falló token=secreto-demo",
                    "--esperado",
                    "cwd en worktree",
                    "--actual",
                    "cwd fuera del repo",
                    "--evidencia",
                    ".runtime/salida.txt",
                ],
                cwd=repo.parent,
                env=env,
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
            )
            self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
            registro = json.loads(
                (repo / ".caja-negra/incidentes.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertEqual(registro["repo_root"], str(repo.resolve()))
            self.assertEqual(registro["cwd"], str(repo.parent.resolve()))
            self.assertEqual(registro["fase"], "despacho")
            self.assertEqual(registro["harness"], "codex")
            self.assertEqual(registro["session_id"], "thread-demo")
            self.assertNotIn("secreto-demo", json.dumps(registro))
            self.assertIn("[REDACTADO]", registro["sintoma"])

    def test_no_admite_evidencia_absoluta_fuera_del_repo(self):
        with tempfile.TemporaryDirectory(prefix="caja-negra-limite-") as temporal:
            repo = Path(temporal) / "demo-agents"
            repo.mkdir()
            resultado = subprocess.run(
                [
                    sys.executable,
                    str(CAJA_NEGRA),
                    "registrar",
                    "--repo",
                    str(repo),
                    "--fase",
                    "prueba",
                    "--sintoma",
                    "algo raro",
                    "--esperado",
                    "A",
                    "--actual",
                    "B",
                    "--evidencia",
                    "/etc/passwd",
                ],
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
            )
            self.assertNotEqual(resultado.returncode, 0)
            self.assertFalse((repo / ".caja-negra/incidentes.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
