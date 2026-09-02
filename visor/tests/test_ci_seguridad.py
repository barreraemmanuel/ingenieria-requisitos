import ast
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RAIZ = Path(__file__).resolve().parents[2]
BOOTSTRAP = RAIZ / "visor" / "bootstrap.py"
LINT_CI = RAIZ / "plantilla" / "docs" / "00-metodo" / "scripts" / "lint_ci.py"
LINT_DEPLOY = RAIZ / "plantilla" / "docs" / "00-metodo" / "scripts" / "lint_deploy.py"
CONTROL_PLANE = RAIZ / "plantilla" / "docs" / "00-metodo" / "scripts" / "control_plane.py"
REPO_CONFIG = RAIZ / "plantilla" / "docs" / "00-metodo" / "scripts" / "repo_config.py"
WORKSPACE_PATHS = RAIZ / "plantilla" / "docs" / "00-metodo" / "scripts" / "workspace_paths.py"
SHA_ACCION = "a" * 40


def cargar_bootstrap():
    spec = importlib.util.spec_from_file_location("bootstrap_bajo_prueba", BOOTSTRAP)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def cargar_lint_ci():
    spec = importlib.util.spec_from_file_location("lint_ci_bajo_prueba", LINT_CI)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def cargar_control_plane():
    spec = importlib.util.spec_from_file_location("control_plane_ci_bajo_prueba", CONTROL_PLANE)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class ContratoCITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="test-ci-seguridad-")
        self.temporal = Path(self.tmp.name)
        self.bootstrap = cargar_bootstrap()
        self.git_env = os.environ.copy()
        self.git_env.update({
            "GIT_AUTHOR_NAME": "Pruebas CI",
            "GIT_AUTHOR_EMAIL": "pruebas@example.invalid",
            "GIT_COMMITTER_NAME": "Pruebas CI",
            "GIT_COMMITTER_EMAIL": "pruebas@example.invalid",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def crear_repo(self, codigo):
        repo = self.temporal / ("repo-codigo" if codigo else "repo-vacio")
        repo.mkdir()
        (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
        if codigo:
            (repo / "app.py").write_text("print('demo')\n", encoding="utf-8")
        return repo

    def crear_script(self, repo, nombre):
        ruta = repo / "scripts" / "ci" / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("#!/bin/sh\nset -eu\nprintf 'OK\\n'\n", encoding="utf-8")
        ruta.chmod(ruta.stat().st_mode | stat.S_IXUSR)

    def crear_contrato_ci(self, repo):
        for nombre in ("full-suite", "lint", "security"):
            self.crear_script(repo, nombre)
        (repo / "AGENTS.md").write_text(
            "# AGENTS.md — Demo\n\n"
            "- Suite completa: `scripts/ci/full-suite`\n"
            "- Linters: `scripts/ci/lint`\n"
            "- Seguridad: `scripts/ci/security`\n",
            encoding="utf-8",
        )
        workflows = repo / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "tests.yml").write_text(
            "name: tests\n"
            "on:\n  pull_request:\n"
            "jobs:\n  tests:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - uses: actions/checkout@{SHA_ACCION}\n"
            "      - run: scripts/ci/full-suite\n",
            encoding="utf-8",
        )
        (workflows / "quality-security.yml").write_text(
            "name: quality-security\n"
            "on:\n"
            "  pull_request:\n"
            "  push:\n    branches: [main]\n"
            "  schedule:\n    - cron: '17 4 * * 1'\n"
            "jobs:\n"
            "  lint:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - uses: actions/checkout@{SHA_ACCION}\n"
            "      - run: scripts/ci/lint\n"
            "  security:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - uses: actions/checkout@{SHA_ACCION}\n"
            "      - run: scripts/ci/security\n"
            "  quality-security:\n"
            "    if: always()\n"
            "    needs: [lint, security]\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: >-\n"
            "          test '${{ needs.lint.result }}' = success &&\n"
            "          test '${{ needs.security.result }}' = success\n",
            encoding="utf-8",
        )
        dependabot = repo / ".github" / "dependabot.yml"
        dependabot.write_text(
            "version: 2\nupdates:\n"
            "  - package-ecosystem: pip\n"
            "    directory: /\n"
            "    schedule:\n      interval: weekly\n",
            encoding="utf-8",
        )

    def crear_manifiesto_control_plane(self, repo, *, productivo=False, secreto=False):
        cp = cargar_control_plane()
        identidad = cp.RunIdentity("demo", "001-ci", "run-17")
        seguro = {
            "APP_ENV": "test", "DB_HOST": "localhost", "DB_NAME": identidad.database()
        }
        fingerprint = cp.assert_safe_test_target(
            seguro, expected_namespace=identidad.namespace
        ).fingerprint
        destino = {
            "env": "production" if productivo else "test",
            "host": "db.prod.example" if productivo else "localhost",
            "database": "clientes_prod" if productivo else identidad.database(),
            "fingerprint": fingerprint,
        }
        manifiesto = {
            "version": 1,
            "identity": identidad.as_dict(),
            "targets": [destino],
            "guard_script": "scripts/ci/control-plane-guard",
            "receipt": ".runtime/control-plane-receipt.json",
        }
        if secreto:
            manifiesto["API_TOKEN"] = "valor-privado-123"
        ruta = repo / "scripts" / "ci" / "control-plane.json"
        ruta.write_text(json.dumps(manifiesto), encoding="utf-8")
        runtime = repo / ".runtime"
        runtime.mkdir(exist_ok=True)
        (runtime / "control-plane-env.json").write_text(
            json.dumps(seguro), encoding="utf-8"
        )
        recibo = {
            "version": 1,
            "claim": "provision usa target aislado",
            "target_fingerprint": fingerprint,
            "route": "directo",
            "test_scope": "area",
            "runs": [
                {"phase": "legacy", "target_fingerprint": fingerprint, "passed": False,
                 "command": "pytest legacy", "exit_code": 1, "output_digest": "a" * 64},
                {"phase": "new", "target_fingerprint": fingerprint, "passed": True,
                 "command": "pytest new", "exit_code": 0, "output_digest": "b" * 64},
                {"phase": "mutant", "target_fingerprint": fingerprint, "passed": False,
                 "command": "pytest mutant", "exit_code": 1, "output_digest": "c" * 64},
            ],
            "metrics": {
                "first_artifact_seconds": 20, "close_seconds": 100,
                "method_seconds": 10, "total_seconds": 100,
            },
        }
        (runtime / "control-plane-receipt.json").write_text(
            json.dumps(recibo), encoding="utf-8"
        )
        guard = repo / "scripts/ci/control-plane-guard"
        guard.write_text(
            "#!/bin/sh\nset -eu\n"
            "exec python3 docs/00-metodo/scripts/control_plane.py guard-test "
            "--env-json .runtime/control-plane-env.json\n",
            encoding="utf-8",
        )
        guard.chmod(guard.stat().st_mode | stat.S_IXUSR)
        provision = repo / "scripts/ci/provision-e2e"
        provision.write_text(
            "#!/bin/sh\nset -eu\nscripts/ci/control-plane-guard\n"
            "provisionar-datos --database app_test\n",
            encoding="utf-8",
        )
        provision.chmod(provision.stat().st_mode | stat.S_IXUSR)

    def ejecutar_lint_ci(self, repo, *opciones):
        return subprocess.run(
            [sys.executable, str(LINT_CI), "--repo", str(repo), *opciones],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=self.git_env,
        )

    @staticmethod
    def guarda_destino_e2e():
        return (
            "case \"${E2E_DATABASE:-}\" in\n"
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n"
        )

    @staticmethod
    def comando_provision_e2e():
        return 'provisionar-datos --database "$E2E_DATABASE"\n'

    def crear_contrato_e2e(self, repo, provision_seguro=True):
        e2e = repo / "scripts" / "ci" / "e2e"
        e2e.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "scripts/ci/provision-e2e\n"
            "pytest tests/e2e\n",
            encoding="utf-8",
        )
        e2e.chmod(e2e.stat().st_mode | stat.S_IXUSR)
        provision = repo / "scripts" / "ci" / "provision-e2e"
        if provision_seguro:
            provision.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "case \"${APP_ENV:-}\" in\n"
                "  local|test|e2e) ;;\n"
                "  production|prod) exit 1 ;;\n"
                "  *) exit 1 ;;\n"
                "esac\n"
                + self.guarda_destino_e2e()
                + self.comando_provision_e2e(),
                encoding="utf-8",
            )
            provision.chmod(provision.stat().st_mode | stat.S_IXUSR)
        else:
            self.crear_script(repo, "provision-e2e")
        full_suite = repo / "scripts" / "ci" / "full-suite"
        full_suite.write_text(
            full_suite.read_text(encoding="utf-8") + "scripts/ci/e2e\n",
            encoding="utf-8",
        )
        agents = repo / "AGENTS.md"
        agents.write_text(
            agents.read_text(encoding="utf-8")
            + "- E2E: `scripts/ci/e2e`\n"
            + "- Datos E2E: `scripts/ci/provision-e2e`\n",
            encoding="utf-8",
        )

    def ejecutar_git(self, repo, *args):
        resultado = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
            env=self.git_env,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def escribir_control(self, repo, nombre, salida, codigo):
        ruta = repo / "scripts" / "ci" / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            f"#!/bin/sh\nset -eu\nprintf '{salida}\\n'\nexit {codigo}\n",
            encoding="utf-8",
        )
        ruta.chmod(ruta.stat().st_mode | stat.S_IXUSR)

    def crear_workspace_deploy(self, contrato=True, suite_exit=0, security_exit=0):
        workspace = Path(tempfile.mkdtemp(prefix="workspace-deploy-", dir=self.temporal))
        scripts_metodo = workspace / "docs" / "00-metodo" / "scripts"
        scripts_metodo.mkdir(parents=True)
        shutil.copyfile(LINT_DEPLOY, scripts_metodo / "lint_deploy.py")
        shutil.copyfile(LINT_CI, scripts_metodo / "lint_ci.py")
        shutil.copyfile(CONTROL_PLANE, scripts_metodo / "control_plane.py")
        shutil.copyfile(REPO_CONFIG, scripts_metodo / "repo_config.py")
        shutil.copyfile(WORKSPACE_PATHS, scripts_metodo / "workspace_paths.py")
        conocimiento = workspace / "docs" / "conocimiento"
        conocimiento.mkdir(parents=True)
        (conocimiento / "plano-deploy.md").write_text(
            "# Plano de deploy\n\n"
            "| Clave | Valor |\n|---|---|\n"
            "| etapa | local |\n"
            "| camino | scripts/deploy |\n"
            "| vuelta_atras | git revert HEAD |\n"
            "| datos | SIN DATOS |\n"
            "| vigilancia | logs locales |\n",
            encoding="utf-8",
        )
        main = workspace / "main"
        main.mkdir()
        self.ejecutar_git(main, "init", "-b", "main")
        (main / "README.md").write_text("# Demo deploy\n", encoding="utf-8")
        (main / ".gitignore").write_text(".env\n", encoding="utf-8")
        (main / "app.py").write_text("print('demo')\n", encoding="utf-8")
        if contrato:
            self.crear_contrato_ci(main)
            self.escribir_control(main, "full-suite", "SALIDA_SUITE", suite_exit)
            self.escribir_control(main, "security", "SALIDA_SEGURIDAD", security_exit)
        self.ejecutar_git(main, "add", "-A")
        self.ejecutar_git(main, "commit", "-m", "Fixture de deploy")
        return workspace

    def ejecutar_lint_deploy(self, workspace):
        return subprocess.run(
            [sys.executable, str(workspace / "docs/00-metodo/scripts/lint_deploy.py")],
            cwd=workspace,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=self.git_env,
        )

    def crear_workspace_metodo(self):
        workspace = self.temporal / "workspace-metodo"
        shutil.copytree(RAIZ / "plantilla", workspace)
        for nombre in (
            "01-constitucion", "02-flujos", "03-investigacion", "04-planificacion",
            "05-trabajo", "bugs", "conocimiento", "decisiones",
        ):
            (workspace / "docs" / nombre).mkdir(parents=True, exist_ok=True)
        (workspace / "docs" / "05-trabajo" / "ESTADO.md").write_text(
            "# Estado\n", encoding="utf-8"
        )
        (workspace / "repos.yaml").write_text(
            "codigo:\n  ruta_local: main/\n  rama_principal: main\n",
            encoding="utf-8",
        )
        main = workspace / "main"
        main.mkdir()
        (main / "README.md").write_text("# Demo\n", encoding="utf-8")
        (main / ".gitignore").write_text(".env\n", encoding="utf-8")
        (main / "app.py").write_text("print('demo')\n", encoding="utf-8")
        self.crear_contrato_ci(main)
        self.ejecutar_git(main, "init", "-b", "main")
        return workspace

    def test_repo_vacio_no_presupone_python_ni_crea_workflow(self):
        destino = self.temporal / "demo-agents"
        destino.mkdir()
        with mock.patch.dict(os.environ, self.git_env, clear=False):
            self.bootstrap.montar_git(destino, "demo", "Demo", None, None)
        main = destino / "main"
        self.assertTrue((main / "README.md").is_file())
        self.assertTrue((main / ".gitignore").is_file())
        self.assertFalse((main / ".github").exists())

    @mock.patch("subprocess.run")
    def test_proteccion_exige_tests_y_quality_security(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.bootstrap.proteger_main("cuenta", "demo")
        cuerpo = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(
            cuerpo["required_status_checks"]["contexts"],
            ["tests", "quality-security"],
        )

    def test_lint_ci_acepta_repo_sin_codigo(self):
        repo = self.crear_repo(codigo=False)
        resultado = self.ejecutar_lint_ci(repo)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("repositorio todavía vacío", resultado.stdout)

    def test_lint_ci_rechaza_codigo_real_sin_controles(self):
        # 029: contrato COMPLETAMENTE ausente (ni scripts/ci/ ni workflows) deja de ser
        # FAIL eterno — es deuda declarada con WARN, exit 0 (R1). Un contrato PARCIAL
        # sigue siendo FAIL (R2, cubierto en test_lint_ci_deploy.py).
        repo = self.crear_repo(codigo=True)
        resultado = self.ejecutar_lint_ci(repo)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("DEUDA-CI", resultado.stdout)

    def test_lint_ci_acepta_contrato_completo(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        resultado = self.ejecutar_lint_ci(repo)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_control_plane_es_opt_in_y_el_flag_exige_manifiesto(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)

        compatible = self.ejecutar_lint_ci(repo)
        estricto = self.ejecutar_lint_ci(repo, "--require-control-plane")

        self.assertEqual(compatible.returncode, 0, compatible.stdout + compatible.stderr)
        self.assertEqual(estricto.returncode, 1)
        self.assertIn("control-plane.json", estricto.stdout)

    def test_control_plane_valido_supera_el_modo_estricto(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_manifiesto_control_plane(repo)

        resultado = self.ejecutar_lint_ci(repo, "--require-control-plane")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_manifiesto_presente_se_valida_aunque_no_haya_flag_y_redacta(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_manifiesto_control_plane(repo, productivo=True, secreto=True)

        resultado = self.ejecutar_lint_ci(repo)

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("control-plane.json", resultado.stdout)
        self.assertNotIn("valor-privado-123", resultado.stdout + resultado.stderr)

    def test_control_plane_rechaza_guard_tardio_y_recibo_de_otro_target(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_manifiesto_control_plane(repo)
        provision = repo / "scripts/ci/provision-e2e"
        provision.write_text(
            "#!/bin/sh\nset -eu\nprovisionar-datos --database app_test\n"
            "scripts/ci/control-plane-guard\n",
            encoding="utf-8",
        )

        tardio = self.ejecutar_lint_ci(repo, "--require-control-plane")

        self.assertEqual(tardio.returncode, 1)
        self.assertIn("antes", tardio.stdout.lower())
        self.crear_manifiesto_control_plane(repo)
        recibo = repo / ".runtime/control-plane-receipt.json"
        datos = json.loads(recibo.read_text(encoding="utf-8"))
        datos["target_fingerprint"] = "otro-target"
        recibo.write_text(json.dumps(datos), encoding="utf-8")

        ajeno = self.ejecutar_lint_ci(repo, "--require-control-plane")

        self.assertEqual(ajeno.returncode, 1)
        self.assertIn("recibo", ajeno.stdout.lower())

        self.crear_manifiesto_control_plane(repo)
        guard = repo / "scripts/ci/control-plane-guard"
        guard.write_text(
            "#!/bin/sh\nset -eu\n"
            "exec python3 vendor/control_plane.py guard-test "
            "--env-json .runtime/control-plane-env.json\n",
            encoding="utf-8",
        )

        guard_suplante = self.ejecutar_lint_ci(repo, "--require-control-plane")

        self.assertEqual(guard_suplante.returncode, 1)
        self.assertIn("guard-test", guard_suplante.stdout)

    def test_control_plane_exige_fail_fast_antes_del_guard(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_manifiesto_control_plane(repo)
        provision = repo / "scripts/ci/provision-e2e"
        provision.write_text(
            "#!/bin/sh\nscripts/ci/control-plane-guard\n"
            "provisionar-datos --database app_test\n",
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-control-plane")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("antes", resultado.stdout.lower())

    def test_lint_ci_rechaza_action_sin_sha(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        workflow = repo / ".github" / "workflows" / "tests.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8").replace(f"@{SHA_ACCION}", "@v4"),
            encoding="utf-8",
        )
        resultado = self.ejecutar_lint_ci(repo)
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("SHA de 40 caracteres", resultado.stdout)

    def test_lint_ci_rechaza_agregador_que_ignora_seguridad(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        workflow = repo / ".github" / "workflows" / "quality-security.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8").replace(
                "needs.security.result", "security.result"
            ),
            encoding="utf-8",
        )
        resultado = self.ejecutar_lint_ci(repo)
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("needs.security.result", resultado.stdout)

    def test_require_e2e_exige_scripts_y_documentacion(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/e2e", resultado.stdout)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)

        self.crear_script(repo, "e2e")
        self.crear_script(repo, "provision-e2e")
        (repo / "scripts/ci/e2e").write_text(
            "#!/bin/sh\npruebas-e2e || true\n", encoding="utf-8"
        )
        (repo / "scripts/ci/provision-e2e").write_text(
            "#!/bin/sh\n<pendiente>\n", encoding="utf-8"
        )
        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("AGENTS.md", resultado.stdout)
        self.assertIn("scripts/ci/e2e", resultado.stdout)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)
        self.assertIn("|| true", resultado.stdout)
        self.assertIn("marcador de plantilla", resultado.stdout)

    def test_require_e2e_rechaza_full_suite_desconectada(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        full_suite = repo / "scripts" / "ci" / "full-suite"
        full_suite.write_text(
            full_suite.read_text(encoding="utf-8").replace(
                "scripts/ci/e2e\n",
                "printf 'scripts/ci/e2e\\n'\n",
            ),
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/full-suite", resultado.stdout)
        self.assertIn("scripts/ci/e2e", resultado.stdout)

    def test_require_e2e_rechaza_contexto_no_directo(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        full_suite = repo / "scripts" / "ci" / "full-suite"
        original = full_suite.read_text(encoding="utf-8")

        for invocacion in (
            "if scripts/ci/e2e; then printf 'OK\\n'; fi",
            "if false\nthen\nscripts/ci/e2e\nfi",
            "ejecutar() {\nscripts/ci/e2e\n}\nejecutar",
            "cat <<EOF\nscripts/ci/e2e\nEOF",
            "! scripts/ci/e2e",
            "scripts/ci/e2e &",
            "scripts/ci/e2e | true",
            "exit 0 && scripts/ci/e2e",
            "exec env APP_ENV=test sh scripts/ci/e2e",
        ):
            full_suite.write_text(
                original.replace("scripts/ci/e2e\n", f"{invocacion}\n"),
                encoding="utf-8",
            )

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, invocacion)
            self.assertIn("scripts/ci/full-suite", resultado.stdout)
            self.assertIn(
                "no acredita invocación autónoma con set -e activo",
                resultado.stdout,
            )

    def test_require_e2e_acepta_sintaxis_shell_dentro_de_texto_citado(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        full_suite = repo / "scripts" / "ci" / "full-suite"
        full_suite.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "printf \"APP_ENV=${APP_ENV:-test}\"\n"
            "scripts/ci/e2e\n",
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_require_e2e_exige_fail_fast_antes_de_e2e_y_provision(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        full_suite = repo / "scripts" / "ci" / "full-suite"
        e2e = repo / "scripts" / "ci" / "e2e"
        full_original = full_suite.read_text(encoding="utf-8")
        e2e_original = e2e.read_text(encoding="utf-8")

        for destino, original in ((full_suite, full_original), (e2e, e2e_original)):
            destino.write_text(original.replace("set -eu\n", "set -u\n"), encoding="utf-8")

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, str(destino))
            self.assertIn(destino.relative_to(repo).as_posix(), resultado.stdout)
            destino.write_text(original, encoding="utf-8")

        for destino, original in ((full_suite, full_original), (e2e, e2e_original)):
            destino.write_text(
                original.replace("set -eu\n", "set -e\nset +e\n"),
                encoding="utf-8",
            )

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, str(destino))
            self.assertIn(destino.relative_to(repo).as_posix(), resultado.stdout)
            destino.write_text(original, encoding="utf-8")

        e2e.write_text(e2e_original + "set +e\nrun-tests\n", encoding="utf-8")
        self.assertFalse(
            cargar_lint_ci().e2e_provisiona_antes_de_pruebas(
                e2e.read_text(encoding="utf-8")
            )
        )
        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/e2e", resultado.stdout)

    def test_require_e2e_rechaza_neutralizadores_despues_de_provision(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        e2e = repo / "scripts" / "ci" / "e2e"
        original = e2e.read_text(encoding="utf-8")

        for neutralizador in (
            "run-tests||true",
            "run-tests || :",
            "comando-e2e || echo ignorado",
            "playwright test | tee resultado.log",
        ):
            e2e.write_text(original + neutralizador + "\n", encoding="utf-8")
            self.assertFalse(
                cargar_lint_ci().e2e_provisiona_antes_de_pruebas(
                    e2e.read_text(encoding="utf-8")
                ),
                neutralizador,
            )

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, neutralizador)
            self.assertIn("scripts/ci/e2e", resultado.stdout)

        citado = original + "printf 'playwright test | tee resultado.log'\n"
        self.assertTrue(cargar_lint_ci().e2e_provisiona_antes_de_pruebas(citado))
        e2e.write_text(citado, encoding="utf-8")
        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_require_e2e_rechaza_runner_que_solo_provisiona(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        e2e = repo / "scripts" / "ci" / "e2e"
        e2e.write_text(
            "#!/bin/sh\nset -eu\nscripts/ci/provision-e2e\n",
            encoding="utf-8",
        )
        texto = e2e.read_text(encoding="utf-8")

        self.assertFalse(cargar_lint_ci().e2e_provisiona_antes_de_pruebas(texto))
        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn(
            "no acredita provision como primera orden con fail-fast continuo",
            resultado.stdout,
        )

    def test_require_e2e_rechaza_printf_como_supuesta_prueba(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        e2e = repo / "scripts" / "ci" / "e2e"
        for no_op in ("printf 'OK\\n'", "echo OK", "true", ":", "sleep 0"):
            e2e.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "scripts/ci/provision-e2e\n"
                + no_op
                + "\n",
                encoding="utf-8",
            )
            self.assertFalse(
                cargar_lint_ci().e2e_provisiona_antes_de_pruebas(
                    e2e.read_text(encoding="utf-8")
                ),
                no_op,
            )
            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, no_op)
            self.assertIn("scripts/ci/e2e", resultado.stdout)

    def test_require_e2e_rechaza_wrapper_local_que_solo_imprime_ok(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        self.crear_script(repo, "run-e2e-tests")
        (repo / "scripts/ci/e2e").write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "scripts/ci/provision-e2e\n"
            "scripts/ci/run-e2e-tests\n",
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("scripts/ci/e2e", resultado.stdout)

    def test_require_e2e_rechaza_continuacion_o_literal_multilinea(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        full_suite = repo / "scripts" / "ci" / "full-suite"
        for cuerpo in (
            "printf 'antes' \\\nscripts/ci/e2e\n",
            "printf '\nscripts/ci/e2e\n'\n",
        ):
            full_suite.write_text("#!/bin/sh\nset -eu\n" + cuerpo, encoding="utf-8")

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, cuerpo)
            self.assertIn("scripts/ci/full-suite", resultado.stdout)

    def test_require_e2e_rechaza_cadena_antes_de_e2e(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        full_suite = repo / "scripts" / "ci" / "full-suite"
        full_suite.write_text(
            full_suite.read_text(encoding="utf-8").replace(
                "scripts/ci/e2e\n",
                "scripts/ci/provision-e2e && scripts/ci/e2e\n",
            ),
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/full-suite", resultado.stdout)

    def test_require_e2e_exige_que_e2e_provisione_antes_de_las_pruebas(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        e2e = repo / "scripts" / "ci" / "e2e"
        for cuerpo in (
            "printf 'tests sin provisión\\n'\n",
            "printf 'tests antes\\n'\nscripts/ci/provision-e2e\n",
            "printf 'tests' | cat\nscripts/ci/provision-e2e\n",
            "if true; then printf 'tests'; fi\nscripts/ci/provision-e2e\n",
            "scripts/ci/provision-e2e | cat\n",
            "RESULT=$(printf tests)\nscripts/ci/provision-e2e\n",
            "set -eu; printf tests\nscripts/ci/provision-e2e\n",
            "cat <<EOF\ntests\nEOF\nscripts/ci/provision-e2e\n",
            "printf 'antes' \\\nscripts/ci/provision-e2e\n",
            "printf '\nscripts/ci/provision-e2e\n'\n",
        ):
            e2e.write_text("#!/bin/sh\nset -eu\n" + cuerpo, encoding="utf-8")

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, cuerpo)
            self.assertIn("scripts/ci/e2e", resultado.stdout)
            self.assertIn("scripts/ci/provision-e2e", resultado.stdout)
            self.assertIn(
                "no acredita provision como primera orden con fail-fast continuo",
                resultado.stdout,
            )

    def test_require_e2e_rechaza_provision_sin_guardas_de_entorno(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo, provision_seguro=False)

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)
        self.assertIn("producci", resultado.stdout.lower())

        provision = repo / "scripts" / "ci" / "provision-e2e"
        provision.write_text(
            "#!/bin/sh\n"
            "APP_ENV=\"${APP_ENV:-}\"\n"
            "printf 'local test e2e production exit 1\\n'\n"
            "if command -v printf >/dev/null; then\n"
            "  printf 'sin guarda real\\n'\n"
            "fi\n",
            encoding="utf-8",
        )
        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)

    def test_provision_exige_guarda_independiente_del_destino(self):
        lint_ci = cargar_lint_ci()
        guarda_entorno = (
            "#!/bin/sh\n"
            "set -eu\n"
            "case \"${APP_ENV:-}\" in\n"
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n"
        )
        segura = (
            guarda_entorno
            + self.guarda_destino_e2e()
            + self.comando_provision_e2e()
        )

        self.assertTrue(lint_ci.provision_tiene_guarda_segura(segura))
        for insegura in (
            guarda_entorno + "provisionar-datos\n",
            guarda_entorno
            + self.guarda_destino_e2e().replace("E2E_DATABASE", "APP_ENV")
            + 'provisionar-datos --database "$APP_ENV"\n',
            guarda_entorno
            + self.guarda_destino_e2e().replace("E2E_DATABASE", "FEATURE_FLAG")
            + 'provisionar-datos --database "$FEATURE_FLAG"\n',
            guarda_entorno
            + self.guarda_destino_e2e()
            + "provisionar-datos\n",
            guarda_entorno
            + self.guarda_destino_e2e().replace("E2E_DATABASE", "E2E_TARGET")
            + 'DATABASE_URL=production provisionar-datos --database "$DATABASE_URL"\n',
        ):
            self.assertFalse(lint_ci.provision_tiene_guarda_segura(insegura), insegura)

    def test_require_e2e_rechaza_provision_sin_guarda_de_destino(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        provision = repo / "scripts" / "ci" / "provision-e2e"
        texto = provision.read_text(encoding="utf-8")
        provision.write_text(
            texto.replace(self.guarda_destino_e2e(), ""),
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)
        self.assertIn("destino", resultado.stdout.lower())

        provision = repo / "scripts/ci/provision-e2e"
        provision.write_text(
            "#!/bin/sh\n"
            "APP_ENV=\"${APP_ENV:-}\"\n"
            "printf 'local test e2e production exit 1\\n'\n"
            "if command -v printf >/dev/null; then\n"
            "  printf 'sin guarda real\\n'\n"
            "fi\n",
            encoding="utf-8",
        )
        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)

    def test_require_e2e_acepta_contrato_completo(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_require_e2e_acepta_invocacion_exec_directa(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        full_suite = repo / "scripts" / "ci" / "full-suite"
        full_suite.write_text(
            full_suite.read_text(encoding="utf-8").replace(
                "scripts/ci/e2e\n",
                "exec ./scripts/ci/e2e\n",
            ),
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_require_e2e_rechaza_guardas_con_variables_distintas(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        provision = repo / "scripts" / "ci" / "provision-e2e"
        provision.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "if os.getenv('APP_ENV') not in ('local', 'test', 'e2e'):\n"
            "    raise SystemExit(1)\n"
            "if os.getenv('OTHER_ENV') == 'production':\n"
            "    raise SystemExit(1)\n",
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)

    def test_require_e2e_rechaza_provision_que_solo_imprime_el_fallo(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        provision = repo / "scripts" / "ci" / "provision-e2e"
        provision.write_text(
            "#!/bin/sh\n"
            "case ${APP_ENV:-} in\n"
            "  local|test|e2e) ;;\n"
            "  production|prod) echo exit 1 ;;\n"
            "  *) echo exit 1 ;;\n"
            "esac\n",
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("scripts/ci/provision-e2e", resultado.stdout)

    def test_require_e2e_rechaza_fallo_neutralizado_o_allowlist_roja(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        provision = repo / "scripts" / "ci" / "provision-e2e"

        for cuerpo in (
            "  local|test|e2e) ;;\n"
            "  production|prod) false||true ;;\n"
            "  *) false||true ;;\n",
            "  local|test|e2e) ;;\n"
            "  production|prod) false || true ;;\n"
            "  *) false || true ;;\n",
            "  local|test|e2e) exit 1 ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n",
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1; exit 0 ;;\n"
            "  *) exit 1 ;;\n",
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1 | true ;;\n"
            "  *) exit 1 ;;\n",
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1; true ;;\n"
            "  *) exit 1 ;;\n",
            "  local|test|e2e) ;;\n"
            "  production|prod) create-users; exit 1 ;;\n"
            "  *) exit 1 ;;\n",
            "  local|test|e2e) run-tests ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n",
        ):
            provision.write_text(
                "#!/bin/sh\ncase ${APP_ENV:-} in\n" + cuerpo + "esac\n",
                encoding="utf-8",
            )

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, cuerpo)
            self.assertIn("scripts/ci/provision-e2e", resultado.stdout)

    def test_require_e2e_acepta_allowlist_case_en_ramas_separadas(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        provision = repo / "scripts" / "ci" / "provision-e2e"
        provision.write_text(
            "#!/bin/sh\n"
            "case ${APP_ENV:-} in\n"
            "  local) ;;\n"
            "  test) ;;\n"
            "  e2e) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n"
            + self.guarda_destino_e2e()
            + self.comando_provision_e2e(),
            encoding="utf-8",
        )

        resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_require_e2e_acepta_expresiones_case_canonicas(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        provision = repo / "scripts" / "ci" / "provision-e2e"
        for expresion in ("$APP_ENV", '"${APP_ENV}"', "${APP_ENV:-}"):
            provision.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                f"case {expresion} in\n"
                "  local|test|e2e) ;;\n"
                "  production|prod) exit 1 ;;\n"
                "  *) exit 1 ;;\n"
                "esac\n"
                + self.guarda_destino_e2e()
                + self.comando_provision_e2e(),
                encoding="utf-8",
            )

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_require_e2e_rechaza_layouts_de_provision_no_canonicos(self):
        repo = self.crear_repo(codigo=True)
        self.crear_contrato_ci(repo)
        self.crear_contrato_e2e(repo)
        provision = repo / "scripts" / "ci" / "provision-e2e"
        casos = (
            "case ${APP_ENV:-} in\n"
            "  local|test|e2e|*) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            "case ${APP_ENV:+local} in\n"
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            "case '${APP_ENV:-}' in\n"
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            "if false; then printf 'no'; fi\n"
            "case ${APP_ENV:-} in\n"
            "  local|test|e2e) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            "case ${APP_ENV:-} in\n"
            "  local|test|e2e) ;;\n"
            "  local) ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            "case ${APP_ENV:-} in\n"
            "  local|test|e2e) case $OTHER_ENV in\n"
            "    demo) ;;\n"
            "  esac ;;\n"
            "  production|prod) exit 1 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
        )
        for caso in casos:
            provision.write_text("#!/bin/sh\nset -eu\n" + caso, encoding="utf-8")

            resultado = self.ejecutar_lint_ci(repo, "--require-e2e")

            self.assertEqual(resultado.returncode, 1, caso)
            self.assertIn("scripts/ci/provision-e2e", resultado.stdout)

    def test_lint_metodo_activa_require_e2e_desde_mapa_o_actividad(self):
        workspace = self.crear_workspace_metodo()
        planos = workspace / "docs" / "02-flujos" / "planos"
        sin_e2e = subprocess.run(
            [sys.executable, str(workspace / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=workspace,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
            env=self.git_env,
        )
        self.assertNotIn("materialización del CI está incompleta", sin_e2e.stdout)

        ubicaciones = (
            planos / "planos.json",
            planos / "actividades" / "pedidos" / "planos.json",
        )

        for ubicacion in ubicaciones:
            for anterior in planos.rglob("planos.json") if planos.exists() else ():
                anterior.unlink()
            ubicacion.parent.mkdir(parents=True, exist_ok=True)
            ubicacion.write_text(
                json.dumps({"pruebas_e2e": [{"id": "E2E-1"}]}),
                encoding="utf-8",
            )

            resultado = subprocess.run(
                [sys.executable, str(workspace / "docs/00-metodo/scripts/lint_metodo.py")],
                cwd=workspace,
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
                env=self.git_env,
            )

            self.assertIn(
                "materialización del CI está incompleta",
                resultado.stdout,
                f"No activó E2E para {ubicacion}:\n{resultado.stdout}{resultado.stderr}",
            )

    def test_lint_metodo_rechaza_pkill_en_artefactos_ejecutables(self):
        workspace = self.crear_workspace_metodo()
        scripts = workspace / "main" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        guion = scripts / "dev.sh"
        guion.write_text("#!/bin/sh\npkill -f 'node server'\n", encoding="utf-8")

        resultado = subprocess.run(
            [sys.executable, str(workspace / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=workspace,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
            env=self.git_env,
        )
        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("pkill -f / killall en", resultado.stdout)
        self.assertIn("main/scripts/dev.sh", resultado.stdout)

        guion.write_text('#!/bin/sh\nkill "$(cat .runtime/pid)"\n', encoding="utf-8")
        resultado = subprocess.run(
            [sys.executable, str(workspace / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=workspace,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
            env=self.git_env,
        )
        self.assertNotIn("pkill -f / killall en", resultado.stdout)

    def test_lint_metodo_no_rechaza_pkill_mencionado_solo_en_comentarios(self):
        workspace = self.crear_workspace_metodo()
        scripts = workspace / "main" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        guion = scripts / "run_case.sh"
        guion.write_text(
            "#!/bin/sh\n# nunca uses pkill -f aquí\nkill \"$(cat .runtime/pid)\"\n",
            encoding="utf-8",
        )

        comentario = self.ejecutar_lint_metodo(workspace)
        self.assertNotIn("pkill -f / killall en", comentario.stdout)

        guion.write_text(
            "#!/bin/sh\nprintf 'pkill -f no debe ejecutarse'\nkillall servidor\n",
            encoding="utf-8",
        )
        real = self.ejecutar_lint_metodo(workspace)
        self.assertIn("pkill -f / killall en", real.stdout)

    def escribir_manifiesto_metodo(self, workspace):
        base = workspace / "docs" / "00-metodo"
        archivos = sorted(
            ruta.relative_to(workspace).as_posix()
            for ruta in base.rglob("*")
            if ruta.is_file()
            and "__pycache__" not in ruta.parts
            and ruta.name != ".DS_Store"
        )
        (workspace / "METODO.json").write_text(
            json.dumps({"formato": 1, "huella": "0" * 64, "archivos": archivos}),
            encoding="utf-8",
        )
        return archivos

    def ejecutar_lint_metodo(self, workspace):
        return subprocess.run(
            [sys.executable, str(workspace / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=workspace,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=self.git_env,
        )

    def test_lint_metodo_defiende_su_propio_arsenal(self):
        # Auditoría 2026-08-03, hallazgo 3: se podía borrar runbooks y ADRs y VACIAR
        # unidad.py con 0 FAIL, porque el linter validaba todo menos docs/00-metodo/.
        # La lista de ficheros del método viaja en METODO.json; el linter la recorre.
        workspace = self.crear_workspace_metodo()
        self.escribir_manifiesto_metodo(workspace)

        integro = self.ejecutar_lint_metodo(workspace)
        self.assertIn("arsenal del método completo", integro.stdout)

        (workspace / "docs/00-metodo/runbooks/cierre.md").unlink()
        (workspace / "docs/00-metodo/scripts/unidad.py").write_text("", encoding="utf-8")
        for adr in sorted((workspace / "docs/00-metodo/decisiones").glob("00[1-8]-*.md")):
            adr.unlink()

        desarmado = self.ejecutar_lint_metodo(workspace)

        self.assertEqual(desarmado.returncode, 1)
        self.assertIn("arsenal del método incompleto", desarmado.stdout)
        self.assertIn("runbooks/cierre.md", desarmado.stdout)
        self.assertIn("scripts/unidad.py", desarmado.stdout)

    def test_lint_metodo_avisa_si_nadie_le_dio_manifiesto(self):
        workspace = self.crear_workspace_metodo()

        resultado = self.ejecutar_lint_metodo(workspace)

        self.assertIn("METODO.json", resultado.stdout)
        self.assertNotIn("arsenal del método completo", resultado.stdout)

    def test_deploy_rechaza_controles_ausentes(self):
        workspace = self.crear_workspace_deploy(contrato=False)
        resultado = self.ejecutar_lint_deploy(workspace)
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("suite completa", resultado.stdout)

    def test_deploy_propaga_fallo_de_suite_y_guarda_output(self):
        workspace = self.crear_workspace_deploy(suite_exit=7)
        resultado = self.ejecutar_lint_deploy(workspace)
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("suite completa terminó con código 7", resultado.stdout)
        log = workspace / ".runtime" / "pre-deploy" / "full-suite.log"
        self.assertIn("SALIDA_SUITE", log.read_text(encoding="utf-8"))

    def test_deploy_propaga_fallo_de_seguridad(self):
        workspace = self.crear_workspace_deploy(security_exit=9)
        resultado = self.ejecutar_lint_deploy(workspace)
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("seguridad terminó con código 9", resultado.stdout)

    def test_deploy_abre_gate_con_suite_y_seguridad_verdes(self):
        workspace = self.crear_workspace_deploy()
        resultado = self.ejecutar_lint_deploy(workspace)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("suite completa: verde", resultado.stdout)
        self.assertIn("seguridad: verde", resultado.stdout)

    def seccion_3bis_de_la_plantilla(self):
        plantilla = RAIZ / "plantilla/docs/00-metodo/plantillas/plano-operativo.md"
        seccion = re.search(
            r"^## 3bis[^\n]*\n(.*?)(?=^## |\Z)",
            plantilla.read_text(encoding="utf-8"),
            re.M | re.S,
        )
        self.assertIsNotNone(seccion, "plano-operativo.md ya no tiene la ficha §3bis")
        return seccion.group(1)

    def test_gate_deploy_exige_exactamente_las_casillas_de_la_plantilla(self):
        # Auditoría 2026-08-03, hallazgo 5: el gate pedía secciones ('## Backups', …) que
        # ninguna plantilla producía — un rojo IMPOSIBLE de quitar. La fuente única ahora es
        # la ficha §3bis de plano-operativo.md; si plantilla y gate divergen, falla esto y no
        # el usuario delante de un FAIL sin salida.
        casillas = None
        for nodo in ast.walk(ast.parse(LINT_DEPLOY.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CASILLAS" for t in nodo.targets
            ):
                casillas = [ast.literal_eval(clave) for clave in nodo.value.keys]
        self.assertIsNotNone(casillas, "lint_deploy.py ya no define CASILLAS")

        claves = re.findall(r"^\|\s*`(\w+)`\s*\|", self.seccion_3bis_de_la_plantilla(), re.M)

        self.assertEqual(sorted(claves), sorted(casillas))
        self.assertEqual(len(claves), len(set(claves)))

    def test_plantilla_sin_rellenar_cierra_el_gate_pero_con_instrucciones_cumplibles(self):
        # La otra mitad del hallazgo 5: copiar la plantilla tal cual NO abre el gate (los
        # menús sin elegir y los huecos `<...>` no son decisiones), pero el FAIL nombra las
        # casillas que la plantilla sí tiene, no secciones de un formato muerto.
        workspace = self.crear_workspace_deploy()
        (workspace / "docs/conocimiento/plano-deploy.md").write_text(
            "# Plano deploy\n" + self.seccion_3bis_de_la_plantilla(), encoding="utf-8"
        )

        resultado = self.ejecutar_lint_deploy(workspace)

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("sin decidir", resultado.stdout)
        for clave in ("etapa", "camino", "vuelta_atras", "datos", "vigilancia"):
            self.assertIn(clave, resultado.stdout)


if __name__ == "__main__":
    unittest.main()
