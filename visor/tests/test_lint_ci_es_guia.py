"""Unidad 015: el contrato de CI es un aviso, nunca un bloqueo de cierre (ADR-028, que
aplica ADR-026 a este control concreto). Ausencia de CI no pierde trabajo, no pisa
producción, no filtra secretos y no absorbe cambios ajenos: por la propia regla de
ADR-026 nunca debió ser un fail() en `lint_metodo.py`, sección "7b"."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts"
DETALLE_INCOMPLETO = "la materialización del CI está incompleta"
DETALLE_SIN_MATERIALIZAR = "CI real aún sin materializar"
DETALLE_SIN_REPO = "no se pudo comprobar el contrato de CI"


class LintCiEsGuiaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-ci-guia-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in ("lint_metodo.py", "repo_config.py", "workspace_paths.py",
                       "lint_ci.py", "control_plane.py"):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        (self.ws / "repos.yaml").write_text(
            "ruta_local: main/\nrama_principal: main\n", encoding="utf-8"
        )
        (self.ws / "docs/05-trabajo").mkdir(parents=True)
        self.repo = self.ws / "main"

    def repo_con_codigo_sin_ci(self):
        """Repo de código real (con historia git) pero sin ninguna pieza del contrato CI."""
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "app.py").write_text("print('hola')\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")

    def declarar_e2e(self):
        carpeta = self.ws / "docs/02-flujos/planos"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "planos.json").write_text('{"pruebas_e2e": true}\n', encoding="utf-8")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def lint(self):
        return subprocess.run(
            [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    # R1: sin ninguna pieza de CI materializada → aviso, nunca bloqueo.
    def test_repo_sin_ninguna_pieza_de_ci_avisa_y_no_bloquea(self):
        self.repo_con_codigo_sin_ci()

        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertIn(f"WARN {DETALLE_SIN_MATERIALIZAR}", salida)
        self.assertNotIn(f"FAIL {DETALLE_SIN_MATERIALIZAR}", salida)
        self.assertNotIn(f"FAIL {DETALLE_INCOMPLETO}", salida)

    # R2: un plano declara pruebas_e2e y faltan scripts/ci/e2e y provision-e2e → aviso, no bloqueo.
    def test_e2e_declarado_sin_piezas_avisa_y_no_bloquea(self):
        self.repo_con_codigo_sin_ci()
        self.declarar_e2e()

        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertIn(f"WARN {DETALLE_INCOMPLETO}", salida)
        self.assertNotIn(f"FAIL {DETALLE_INCOMPLETO}", salida)
        self.assertIn("lint_ci.py", salida)
        self.assertIn("--require-e2e", salida)

    # R3: con piezas parciales/mal formadas el sistema sigue señalando el detalle, solo
    # baja de FAIL a WARN.
    def test_piezas_parciales_sigue_senalando_el_detalle_como_aviso(self):
        self.repo_con_codigo_sin_ci()
        (self.repo / "scripts/ci").mkdir(parents=True)
        (self.repo / "scripts/ci/lint").write_text("<pega aquí tu lint>\n", encoding="utf-8")

        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertIn(f"WARN {DETALLE_INCOMPLETO}", salida)
        self.assertNotIn(f"FAIL {DETALLE_INCOMPLETO}", salida)
        self.assertIn("para ver el detalle", salida)

    # R4 (caso límite): si lint_ci.py no puede ejecutarse porque el repo de código no
    # existe, avisa y sigue el resto de la ronda de lint, nunca aborta por esto.
    def test_repo_de_codigo_inexistente_avisa_y_sigue_el_resto_del_lint(self):
        # self.repo NO se crea: repos.yaml apunta a main/ y no hay nada ahí.
        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertIn(DETALLE_SIN_REPO, salida)
        self.assertIn("FAIL ·", salida)  # el linter llegó al resumen final, no reventó a medias
        self.assertNotIn("Traceback", salida)


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- unidad 097
# ADR-035: la verificación del método es LOCAL. Un CI remoto (GitHub Actions u otro) solo
# nace si el usuario lo pide y lo deja escrito en `01-constitucion/bias.md`. Estos tests
# vigilan las dos mitades de esa regla: la prosa que la enuncia y el guardián que dejaría
# de contradecirla empujando hacia workflows que nadie pidió.

RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
PLANTILLA = RAIZ_REPO / "plantilla"
ADR_035 = "035-sin-ci-remoto-por-defecto.md"
TOPE_AGENTS = 160

# Los dos ficheros del método que HOY siguen mandando crear `.github/workflows/`. No están
# en el alcance de la unidad 097 (no los posee), así que quedan CONGELADOS: esta lista solo
# puede encoger. Un fichero nuevo que empuje a montar CI remoto es FAIL.
PENDIENTES_CI_REMOTO = {
    "docs/00-metodo/runbooks/planificacion.md",
    "docs/00-metodo/plantillas/agents-repo-codigo.md",
}
# Los guardianes LEEN los workflows de quien ya los tiene (ADR-035 no borra ese caso): que
# nombren la ruta no es empujar a crearla.
LECTORES_DE_WORKFLOWS = {
    "docs/00-metodo/scripts/lint_ci.py",
    "docs/00-metodo/scripts/lint_metodo.py",
}


class SinCiRemotoPorDefectoTest(unittest.TestCase):
    """R1, R2 y R5: la regla existe, viaja y ningún papel del método la contradice."""

    def test_r1_agents_declara_la_verificacion_local_dentro_del_tope(self):
        ruta = PLANTILLA / "AGENTS.md"
        texto = ruta.read_text(encoding="utf-8")

        self.assertLessEqual(len(texto.splitlines()), TOPE_AGENTS,
                             "AGENTS.md se pasa del tope de 160 líneas")
        self.assertIn("ADR-035", texto)
        self.assertRegex(texto, r"(?i)verificaci[óo]n es LOCAL")
        self.assertIn("ci_remoto", texto)
        self.assertIn("01-constitucion/bias.md", texto)

    def test_r1_readme_y_cierre_lo_dicen_igual(self):
        for relativa in ("docs/00-metodo/README.md",
                         "docs/00-metodo/runbooks/cierre.md"):
            texto = (PLANTILLA / relativa).read_text(encoding="utf-8")
            with self.subTest(relativa=relativa):
                self.assertIn("ADR-035", texto)
                self.assertIn("ci_remoto", texto)

    def test_r2_el_adr_035_existe_y_supera_lo_que_018_y_028_asumian(self):
        ruta = PLANTILLA / "docs/00-metodo/decisiones" / ADR_035
        self.assertTrue(ruta.is_file(), f"falta {ruta}")
        texto = ruta.read_text(encoding="utf-8")
        self.assertIn("ADR-018", texto)
        self.assertIn("ADR-028", texto)
        self.assertIn("ci_remoto", texto)

    def test_r2_el_adr_035_viaja_en_el_bootstrap(self):
        sys.path.insert(0, str(RAIZ_REPO / "visor"))
        try:
            import bootstrap
        finally:
            sys.path.pop(0)
        self.assertIn(ADR_035, bootstrap.DECISIONES)

    def test_r5_ningun_papel_nuevo_del_metodo_manda_crear_workflows(self):
        culpables = set()
        for carpeta in ("docs/00-metodo/scripts", "docs/00-metodo/runbooks",
                        "docs/00-metodo/plantillas"):
            for ruta in sorted((PLANTILLA / carpeta).rglob("*")):
                if not ruta.is_file():
                    continue
                texto = ruta.read_text(encoding="utf-8", errors="replace")
                if ".github/workflows" in texto:
                    culpables.add(ruta.relative_to(PLANTILLA).as_posix())
        for relativa in ("AGENTS.md", "docs/00-metodo/README.md"):
            if ".github/workflows" in (PLANTILLA / relativa).read_text(encoding="utf-8"):
                culpables.add(relativa)

        nuevos = culpables - LECTORES_DE_WORKFLOWS - PENDIENTES_CI_REMOTO
        self.assertFalse(nuevos, f"papeles del método que mandan crear CI remoto: {nuevos}")
        self.assertFalse(PENDIENTES_CI_REMOTO - culpables,
                         "la lista congelada nombra ficheros ya limpios: bórralos de "
                         "PENDIENTES_CI_REMOTO, la lista solo puede encoger")


class LintCiSinCiRemotoTest(unittest.TestCase):
    """R3 (criterio portante) y R4: el guardián deja de empujar hacia un CI que nadie pidió."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-ci-sin-remoto-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in ("lint_ci.py", "control_plane.py"):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.repo = self.ws / "main"
        self.repo.mkdir()
        (self.repo / "app.py").write_text("print('hola')\n", encoding="utf-8")

    def declarar_checks_locales(self):
        (self.repo / "AGENTS.md").write_text(
            "# AGENTS.md — Demo\n\n## Checks locales (antes de fusionar)\n\n"
            "- Suite completa: `python3 -m pytest`\n"
            "- Linters: `ruff check .`\n"
            "- Seguridad: `pip-audit`\n",
            encoding="utf-8",
        )

    def declarar_bias(self, valor):
        bias = self.ws / "docs/01-constitucion"
        bias.mkdir(parents=True, exist_ok=True)
        (bias / "bias.md").write_text(
            f"# Bias\n\n- ci_remoto: {valor}\n", encoding="utf-8"
        )

    def contrato_ci_completo(self):
        ci = self.repo / "scripts/ci"
        ci.mkdir(parents=True)
        for nombre in ("full-suite", "lint", "security"):
            (ci / nombre).write_text("#!/bin/sh\nset -eu\nprintf 'OK\\n'\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text(
            "# AGENTS.md — Demo\n\n- Suite: `scripts/ci/full-suite`\n"
            "- Lint: `scripts/ci/lint`\n- Seguridad: `scripts/ci/security`\n",
            encoding="utf-8",
        )
        workflows = self.repo / ".github/workflows"
        workflows.mkdir(parents=True)
        sha = "a" * 40
        (workflows / "tests.yml").write_text(
            "on:\n  pull_request:\njobs:\n  tests:\n    steps:\n"
            f"      - uses: actions/checkout@{sha}\n"
            "      - run: scripts/ci/full-suite\n",
            encoding="utf-8",
        )
        (workflows / "quality-security.yml").write_text(
            "on:\n  pull_request:\n  push:\n    branches: [main]\n  schedule:\n"
            "    - cron: '0 3 * * 1'\njobs:\n  lint:\n    steps:\n"
            f"      - uses: actions/checkout@{sha}\n      - run: scripts/ci/lint\n"
            "  security:\n    steps:\n      - run: scripts/ci/security\n"
            "  quality-security:\n    needs: [lint, security]\n    steps:\n"
            "      - run: echo ${{ needs.lint.result }} ${{ needs.security.result }}\n",
            encoding="utf-8",
        )
        (self.repo / ".github/dependabot.yml").write_text(
            "updates:\n  - package-ecosystem: pip\n    schedule:\n      interval: weekly\n",
            encoding="utf-8",
        )

    def lint_ci(self, *opciones):
        return subprocess.run(
            [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_ci.py"),
             "--repo", str(self.repo), *opciones],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    # R3 (portante): sin CI remoto pedido y con checks locales declarados, ni FAIL ni deuda.
    def test_r3_sin_ci_remoto_pedido_y_con_checks_locales_no_hay_deuda(self):
        self.declarar_checks_locales()

        resultado = self.lint_ci()
        salida = resultado.stdout + resultado.stderr

        self.assertEqual(resultado.returncode, 0, salida)
        self.assertNotIn("DEUDA-CI", salida)
        self.assertNotIn("FAIL", salida.replace("0 FAIL", ""))
        self.assertIn("python3 -m pytest", salida)

    # R3: el bias manda. Si el proyecto pidió CI remoto y no existe, sigue el aviso (ADR-028).
    def test_r3_bias_pide_ci_remoto_y_no_existe_avisa_sin_bloquear(self):
        self.declarar_checks_locales()
        self.declarar_bias("sí")

        resultado = self.lint_ci()
        salida = resultado.stdout + resultado.stderr

        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("DEUDA-CI", salida)
        self.assertIn("WARN", salida)

    # R3 (límite): `ci_remoto: no` explícito se comporta como la ausencia de la clave.
    def test_r3_bias_dice_no_y_se_comporta_como_la_ausencia(self):
        self.declarar_checks_locales()
        self.declarar_bias("no")

        salida = self.lint_ci().stdout
        self.assertNotIn("DEUDA-CI", salida)

    # R3 (límite): sin checks locales declarados no hay nada que acreditar → sigue el aviso.
    def test_r3_sin_checks_declarados_sigue_avisando(self):
        resultado = self.lint_ci()
        salida = resultado.stdout + resultado.stderr

        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("DEUDA-CI", salida)
        self.assertIn("AGENTS.md", salida)

    # R4: un proyecto que YA tiene workflows se comprueba exactamente como hoy.
    def test_r4_repo_con_workflows_se_comprueba_como_hoy(self):
        self.contrato_ci_completo()

        resultado = self.lint_ci()
        salida = resultado.stdout + resultado.stderr

        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("materializados", salida)

    # R4: y si esos workflows están mal formados, sigue siendo FAIL (no lo relaja ADR-035).
    def test_r4_workflows_mal_formados_siguen_siendo_fail(self):
        self.contrato_ci_completo()
        (self.repo / ".github/workflows/tests.yml").write_text(
            "on:\n  pull_request:\njobs:\n  tests:\n    steps:\n"
            "      - uses: actions/checkout@v4\n      - run: scripts/ci/full-suite\n",
            encoding="utf-8",
        )

        resultado = self.lint_ci()

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("no está fijada a un SHA", resultado.stdout)
