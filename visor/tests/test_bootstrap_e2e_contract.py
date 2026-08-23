import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
BOOTSTRAP = RAIZ / "visor" / "bootstrap.py"
EJEMPLO = RAIZ / "visor" / "ejemplo.json"
PLANTILLA_HTML = RAIZ / "visor" / "plantilla.html"
VALIDAR_WEB = RAIZ / "visor" / "validar_web.py"


class BootstrapE2EContractTest(unittest.TestCase):
    def test_visor_renderiza_identidad_restricciones_y_seleccion_e2e(self):
        html = PLANTILLA_HTML.read_text(encoding="utf-8")

        for fragmento in (
            "a.organizacion",
            "a.grupos",
            "permisos.restricciones",
            "pruebas_e2e",
            "Pruebas E2E seleccionadas",
            "textoNunca",
        ):
            with self.subTest(fragmento=fragmento):
                self.assertIn(fragmento, html)

    def test_bootstrap_transporta_planos_sin_inventar_e2e_en_repo_vacio(self):
        with tempfile.TemporaryDirectory(prefix="bootstrap-e2e-") as temporal:
            raiz = Path(temporal)
            proyecto = raiz / "planos-origen"
            destino = raiz / "demo-agents"
            proyecto.mkdir()
            shutil.copyfile(EJEMPLO, proyecto / "planos.json")

            registro_real = RAIZ / ".ingenieria-requisitos-local/registro.json"
            contenido_real = registro_real.read_bytes() if registro_real.exists() else None
            registro_prueba = raiz / "estado-prueba/registro.json"
            entorno = os.environ.copy()
            entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(registro_prueba)
            resultado = subprocess.run(
                [
                    sys.executable,
                    str(BOOTSTRAP),
                    "--planos",
                    str(proyecto),
                    "--destino",
                    str(destino),
                    "--tipo",
                    "otro",
                    "--compilar",
                ],
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
                env=entorno,
            )

            self.assertEqual(
                resultado.returncode, 0, resultado.stdout + resultado.stderr
            )
            transportado = json.loads(
                (destino / "docs/02-flujos/planos/planos.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                transportado.get("pruebas_e2e"),
                json.loads(EJEMPLO.read_text(encoding="utf-8")).get("pruebas_e2e"),
            )
            self.assertFalse((destino / "main/scripts/ci/e2e").exists())
            self.assertFalse((destino / "main/scripts/ci/provision-e2e").exists())
            self.assertTrue(registro_prueba.is_file())
            actual_real = registro_real.read_bytes() if registro_real.exists() else None
            self.assertEqual(actual_real, contenido_real)
            self.assertTrue(
                (destino / "docs/00-metodo/scripts/control_plane.py").is_file()
            )

    @unittest.skipUnless(
        importlib.util.find_spec("playwright"),
        "Playwright no está instalado en este entorno",
    )
    def test_navegador_muestra_permiso_concedido_solo_por_grupo(self):
        ejemplo = json.loads(EJEMPLO.read_text(encoding="utf-8"))
        maria = next(a for a in ejemplo["actores"] if a["nombre"] == "María")
        maria["rol"] = "operadora"
        maria["grupos"] = ["operaciones e2e"]
        permisos = ejemplo["superficie"]["permisos"]
        fila_operadora = next(
            r for r in permisos["roles"] if r["rol"] in ("operadora", "María")
        )
        fila_operadora["rol"] = "operadora"
        concedidas = list(fila_operadora["permitidas"])
        fila_operadora["permitidas"] = []
        permisos["grupos"] = [
            {"grupo": "operaciones e2e", "permitidas": concedidas}
        ]
        for restriccion in permisos.get("restricciones", []):
            restriccion["grupo"] = "operaciones e2e"
            restriccion.pop("rol", None)

        with tempfile.TemporaryDirectory(prefix="visor-grupo-") as temporal:
            datos = Path(temporal) / "planos.json"
            datos.write_text(
                json.dumps(ejemplo, ensure_ascii=False), encoding="utf-8"
            )
            resultado = subprocess.run(
                [sys.executable, str(VALIDAR_WEB), "--datos", str(datos)],
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
            )

        self.assertEqual(
            resultado.returncode, 0, resultado.stdout + resultado.stderr
        )
        self.assertIn("OK: menú lateral visible", resultado.stdout)

    @unittest.skipUnless(
        importlib.util.find_spec("playwright"),
        "Playwright no está instalado en este entorno",
    )
    def test_navegador_conserva_matriz_legacy_por_nombre(self):
        ejemplo = json.loads(EJEMPLO.read_text(encoding="utf-8"))
        ejemplo.pop("pruebas_e2e", None)
        permisos = ejemplo["superficie"]["permisos"]
        permisos.pop("restricciones", None)
        maria = next(a for a in ejemplo["actores"] if a["nombre"] == "María")
        maria.pop("grupos", None)
        fila_operadora = next(
            r for r in permisos["roles"] if r["rol"] in ("operadora", "María")
        )
        fila_operadora["rol"] = "María"

        with tempfile.TemporaryDirectory(prefix="visor-legacy-") as temporal:
            datos = Path(temporal) / "planos.json"
            datos.write_text(
                json.dumps(ejemplo, ensure_ascii=False), encoding="utf-8"
            )
            resultado = subprocess.run(
                [sys.executable, str(VALIDAR_WEB), "--datos", str(datos)],
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
            )

        self.assertEqual(
            resultado.returncode, 0, resultado.stdout + resultado.stderr
        )


if __name__ == "__main__":
    unittest.main()
