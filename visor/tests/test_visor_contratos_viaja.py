"""Bug 080: el visor de contratos viaja al workspace (bootstrap y actualizar) y allí
encuentra su hoja de estilos. Sin esto, la puerta de despacho del 054 llegaba sin llave."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
ACTUALIZAR = RAIZ / "visor/actualizar.py"
CARPETA = "docs/00-metodo/requisitos/visor_contratos"
FICHEROS = ("servir.py", "plantilla.html", "render.js")

sys.path.insert(0, str(RAIZ / "visor"))
import bootstrap  # noqa: E402


class VisorContratosViajaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="visor-contratos-viaja-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.entorno = dict(os.environ)
        self.entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(self.base / "registro.json")

    def ejecutar(self, script, *args):
        return subprocess.run([sys.executable, str(script), *args], cwd=RAIZ, text=True,
                              encoding="utf-8", errors="replace", capture_output=True,
                              env=self.entorno)

    def planos_minimos(self):
        proyecto = self.base / "planos"
        (proyecto / "especificaciones/01-constitution").mkdir(parents=True)
        (proyecto / "especificaciones/02-flows").mkdir()
        (proyecto / "planos.json").write_text(json.dumps({
            "version": 2, "proyecto": "demo", "titulo": "Demo",
            "contrato": {"frase": "Una demostración"}, "actividades": []}), encoding="utf-8")
        (proyecto / "especificaciones/01-constitution/constitution.md").write_text(
            "# Constitución\n", encoding="utf-8")
        return proyecto

    def workspace_nuevo(self):
        destino = self.base / "demo-agents"
        r = self.ejecutar(BOOTSTRAP, "--planos", str(self.planos_minimos()),
                          "--destino", str(destino))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return destino

    def assert_visor_repartido(self, ws):
        for nombre in FICHEROS:
            repartido = ws / CARPETA / nombre
            self.assertTrue(repartido.is_file(), f"falta {CARPETA}/{nombre}")
            self.assertEqual(repartido.read_bytes(),
                             (RAIZ / "visor_contratos" / nombre).read_bytes(), nombre)

    def test_la_lista_de_ficheros_es_la_del_visor(self):
        self.assertEqual(set(bootstrap.ARCHIVOS_CONTRATOS), set(FICHEROS))

    def test_bootstrap_reparte_el_visor_de_contratos(self):
        self.assert_visor_repartido(self.workspace_nuevo())

    def test_actualizar_lo_repone_donde_falta_y_lo_deja_al_dia(self):
        ws = self.workspace_nuevo()
        shutil.rmtree(ws / CARPETA)                       # workspace anterior a la 1.8.1
        subprocess.run(["git", "-C", str(ws), "commit", "-qam", "sin visor de contratos"],
                       check=True, env={**self.entorno, "GIT_AUTHOR_NAME": "t",
                                        "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                        "GIT_COMMITTER_EMAIL": "t@t"})
        r = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_visor_repartido(ws)
        r = self.ejecutar(ACTUALIZAR, "revisar", str(ws))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("visor_contratos", r.stdout, "al día y aún lo marca")

    def test_en_el_workspace_sirve_el_base_css_de_requisitos(self):
        ws = self.workspace_nuevo()
        hoja = ws / "docs/00-metodo/requisitos/base.css"
        self.assertTrue(hoja.is_file())
        hoja.write_text(hoja.read_text(encoding="utf-8") + "\n/* marca-080 */\n",
                        encoding="utf-8")
        self.assertFalse((ws / "docs/00-metodo/requisitos/visor/base.css").exists())
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); puerto = s.getsockname()[1]; s.close()
        proc = subprocess.Popen([sys.executable, str(ws / CARPETA / "servir.py"),
                                 "--workspace", str(ws), "--puerto", str(puerto),
                                 "--sin-navegador", "--minutos", "1"],
                                cwd=self.base, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        import time
        cuerpo = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/base.css",
                                            timeout=1) as resp:
                    self.assertEqual(resp.status, 200)
                    cuerpo = resp.read().decode("utf-8")
                break
            except Exception:
                time.sleep(0.1)
        self.assertIsNotNone(cuerpo, "el visor no arrancó en el workspace")
        self.assertIn("marca-080", cuerpo, "sirve otro base.css, no el de requisitos/")


if __name__ == "__main__":
    unittest.main()
