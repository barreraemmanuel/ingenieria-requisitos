"""R1/R4/R5: salida JSON completa, ids explícitos y cola agregada."""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
PLANTILLA = RAIZ / "plantilla"
LINT = PLANTILLA / "docs/00-metodo/scripts/lint_metodo.py"
LINT_DEPLOY = PLANTILLA / "docs/00-metodo/scripts/lint_deploy.py"
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
ACTUALIZAR = RAIZ / "visor/actualizar.py"
ARTEFACTOS_R5 = (
    "docs/00-metodo/guardianes-degradados.json",
    "docs/00-metodo/scripts/veredicto_lint.py",
)


class LintMetodoJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-metodo-json-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "workspace"
        shutil.copytree(PLANTILLA, self.ws)
        for nombre in (
            "01-constitucion", "02-flujos", "03-investigacion", "04-planificacion",
            "05-trabajo", "bugs", "conocimiento", "decisiones",
        ):
            (self.ws / "docs" / nombre).mkdir(parents=True, exist_ok=True)
        (self.ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        (self.ws / "docs/05-trabajo/archivo").mkdir(exist_ok=True)
        (self.ws / "docs/05-trabajo/peticiones").mkdir(exist_ok=True)

    def ejecutar(self, json_=False):
        orden = [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_metodo.py")]
        if json_:
            orden.append("--json")
        return subprocess.run(
            orden, cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    def peticion(self, sufijo, estado="capturada"):
        pid = f"P-20260901-{sufijo}"
        carpeta = self.ws / "docs/05-trabajo/peticiones" / pid
        carpeta.mkdir()
        (carpeta / "peticion.json").write_text(json.dumps({
            "id": pid, "revision": 1, "estado": estado,
            "original": {"resumen": "demo"}, "evaluaciones": [],
            "procesos": [], "cierres": [],
        }), encoding="utf-8")

    def planos_minimos(self):
        proyecto = Path(self.tmp.name) / "planos"
        (proyecto / "especificaciones/01-constitution").mkdir(parents=True)
        (proyecto / "especificaciones/02-flows").mkdir()
        (proyecto / "planos.json").write_text(json.dumps({
            "version": 2,
            "proyecto": "r5-distribucion",
            "titulo": "R5 distribucion",
            "contrato": {"frase": "Prueba de distribucion"},
            "actividades": [],
        }), encoding="utf-8")
        (proyecto / "especificaciones/01-constitution/constitution.md").write_text(
            "# Constitucion\n", encoding="utf-8"
        )
        return proyecto

    def ejecutar_en_workspace(self, workspace, *orden):
        return subprocess.run(
            [sys.executable, *map(str, orden)], cwd=workspace, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )

    def comprobar_runtime_r5(self, workspace):
        for relativo in ARTEFACTOS_R5:
            self.assertTrue((workspace / relativo).is_file(), relativo)
        scripts = workspace / "docs/00-metodo/scripts"
        importar = self.ejecutar_en_workspace(
            workspace, "-c",
            f"import sys; sys.path.insert(0, {str(scripts)!r}); import unidad",
        )
        self.assertEqual(importar.returncode, 0, importar.stdout + importar.stderr)
        lint = self.ejecutar_en_workspace(
            workspace, scripts / "lint_metodo.py", "--json",
        )
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        self.assertEqual(json.loads(lint.stdout)["schema"], "lint-hallazgos/v1")

    def test_json_es_un_documento_unico_y_cada_hallazgo_tiene_identidad_completa(self):
        self.peticion("00000001")
        resultado = self.ejecutar(json_=True)
        datos = json.loads(resultado.stdout)
        self.assertEqual(datos["schema"], "lint-hallazgos/v1")
        self.assertTrue(datos["hallazgos"])
        for hallazgo in datos["hallazgos"]:
            self.assertEqual(
                set(hallazgo), {"id", "severidad", "sujeto", "ruta", "instancia"}
            )
            self.assertTrue(all(str(valor).strip() for valor in hallazgo.values()))

    def test_toda_llamada_fail_warn_declara_id_en_los_dos_linterns(self):
        for ruta in (LINT, LINT_DEPLOY):
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            sin_id = []
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Name):
                    continue
                if nodo.func.id not in {"fail", "warn"}:
                    continue
                ids = [kw.value for kw in nodo.keywords if kw.arg == "id_"]
                if (
                    len(nodo.args) != 1
                    or len(ids) != 1
                    or not isinstance(ids[0], ast.Constant)
                    or not isinstance(ids[0].value, str)
                    or not ids[0].value.strip()
                ):
                    sin_id.append(nodo.lineno)
            self.assertEqual(sin_id, [], f"R1: {ruta.name} tiene fail/warn sin id: {sin_id}")

    def test_cola_q_a_un_aviso_sin_ocultar_el_resto(self):
        for sufijo in ("00000001", "00000002", "00000003"):
            self.peticion(sufijo)
        resultado = self.ejecutar()
        lineas = resultado.stdout.splitlines()
        cola = [linea for linea in lineas if "peticiones sin siguiente proceso" in linea]
        individuales = [linea for linea in lineas if "capturada sin siguiente proceso" in linea]
        self.assertEqual(len(cola), 1, resultado.stdout)
        self.assertIn("3 peticiones", cola[0])
        self.assertEqual(individuales, [])

    def test_registro_de_degradados_nace_vacio(self):
        ruta = PLANTILLA / "docs/00-metodo/guardianes-degradados.json"
        self.assertTrue(ruta.is_file(), "R5 ROJO: falta guardianes-degradados.json")
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        self.assertEqual(datos, {"version": 1, "ids": []})

    def test_r5_bootstrap_y_modo_d_distribuyen_registro_y_veredicto(self):
        destino = Path(self.tmp.name) / "r5-agents"
        entorno = dict(os.environ)
        entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(
            Path(self.tmp.name) / "registro-proyectos.json"
        )
        bootstrap = subprocess.run(
            [
                sys.executable, str(BOOTSTRAP), "--planos", str(self.planos_minimos()),
                "--destino", str(destino),
            ],
            cwd=RAIZ, env=entorno, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )
        self.assertEqual(bootstrap.returncode, 0, bootstrap.stdout + bootstrap.stderr)
        self.comprobar_runtime_r5(destino)

        for relativo in ARTEFACTOS_R5:
            (destino / relativo).unlink()
        subprocess.run(["git", "add", *ARTEFACTOS_R5], cwd=destino, check=True,
                       capture_output=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "simula metodo anterior",
        ], cwd=destino, check=True, capture_output=True)

        actualizar = subprocess.run(
            [sys.executable, str(ACTUALIZAR), "aplicar", str(destino)],
            cwd=RAIZ, env=entorno, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )
        self.assertEqual(actualizar.returncode, 0, actualizar.stdout + actualizar.stderr)
        self.comprobar_runtime_r5(destino)

    def test_cambiar_registro_y_anadir_su_rojo_no_autoindulta_el_diff(self):
        subprocess.run(["git", "init", "-b", "main"], cwd=self.ws, check=True,
                       capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=self.ws, check=True, capture_output=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "base",
        ], cwd=self.ws, check=True, capture_output=True)
        registro = self.ws / "docs/00-metodo/guardianes-degradados.json"
        registro.write_text(json.dumps({"version": 1, "ids": ["agents-md-existe"]}),
                            encoding="utf-8")
        (self.ws / "AGENTS.md").unlink()
        # El propio cambio del registro debe bloquear antes de que su WARN pueda abrir nada.
        datos = json.loads(self.ejecutar(json_=True).stdout)
        por_id = {item["id"]: item for item in datos["hallazgos"]}
        self.assertEqual(por_id["agents-md-existe"]["severidad"], "WARN")
        self.assertEqual(por_id["guardianes-degradados-modificado"]["severidad"], "FAIL")

    def test_registro_cambiado_se_detecta_en_head_detached_con_base_explicita(self):
        subprocess.run(["git", "init", "-b", "main"], cwd=self.ws, check=True,
                       capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=self.ws, check=True, capture_output=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "base",
        ], cwd=self.ws, check=True, capture_output=True)
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.ws, check=True,
            text=True, capture_output=True,
        ).stdout.strip()
        registro = self.ws / "docs/00-metodo/guardianes-degradados.json"
        registro.write_text(json.dumps({"version": 1, "ids": ["agents-md-existe"]}),
                            encoding="utf-8")
        subprocess.run(["git", "add", str(registro)], cwd=self.ws, check=True,
                       capture_output=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "intenta degradar",
        ], cwd=self.ws, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "--detach", "HEAD"], cwd=self.ws, check=True,
                       capture_output=True)

        resultado = subprocess.run(
            [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_metodo.py"),
             "--json", "--base-ref", base],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

        datos = json.loads(resultado.stdout)
        por_id = {item["id"]: item for item in datos["hallazgos"]}
        self.assertEqual(por_id["guardianes-degradados-modificado"]["severidad"], "FAIL")

        copia_sin_git = Path(self.tmp.name) / "copia-sin-git"
        shutil.copytree(PLANTILLA, copia_sin_git)
        for nombre in (
            "01-constitucion", "02-flujos", "03-investigacion", "04-planificacion",
            "05-trabajo/archivo", "05-trabajo/peticiones", "bugs", "conocimiento",
            "decisiones",
        ):
            (copia_sin_git / "docs" / nombre).mkdir(parents=True, exist_ok=True)
        (copia_sin_git / "docs/05-trabajo/ESTADO.md").write_text(
            "# Estado\n", encoding="utf-8"
        )
        (copia_sin_git / "docs/00-metodo/guardianes-degradados.json").write_text(
            json.dumps({"version": 1, "ids": ["agents-md-existe"]}), encoding="utf-8"
        )
        sin_git = subprocess.run(
            [sys.executable, str(copia_sin_git / "docs/00-metodo/scripts/lint_metodo.py"),
             "--json", "--base-ref", base],
            cwd=copia_sin_git, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )
        self.assertTrue(sin_git.stdout, sin_git.stderr)
        hallazgos_sin_git = {
            item["id"]: item for item in json.loads(sin_git.stdout)["hallazgos"]
        }
        self.assertEqual(
            hallazgos_sin_git["guardianes-degradados-modificado"]["severidad"], "FAIL"
        )


if __name__ == "__main__":
    unittest.main()
