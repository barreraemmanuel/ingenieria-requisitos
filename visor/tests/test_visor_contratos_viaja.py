"""R5 de la unidad 081 (y herencia del bug 080): la WEB ENTERA viaja al workspace.

Antes había una lista de reparto por visor y cada olvido fue un bug: el 064 (sin
`render.js` la web nacía en blanco) y el 080 (el visor de contratos no viajaba y la
puerta de despacho del 054 llegaba sin la llave). Desde la 081 hay UNA lista
—`bootstrap.ARCHIVOS_WEB`— con todo lo que la web necesita, y aquí se comprueba que:

- el bootstrap la reparte entera a `docs/00-metodo/requisitos/web/`;
- `actualizar.py` la repone donde falta y retira las carpetas de los visores viejos;
- en ese workspace recién creado, `/` (el tablero) y `/contratos` responden 200 y con
  los estilos que se repartieron, no con otros.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
ACTUALIZAR = RAIZ / "visor/actualizar.py"
CARPETA = "docs/00-metodo/requisitos/web"
# Las carpetas que la 081 retira: si se quedaran, `unidad.py` podría volver a
# encontrar un visor viejo y levantar un quinto puerto.
VIEJAS = ("docs/00-metodo/requisitos/visor_contratos",
          "docs/00-metodo/requisitos/visor_presentaciones")

sys.path.insert(0, str(RAIZ / "visor"))
import bootstrap  # noqa: E402


class WebViajaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="web-viaja-")
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

    def assert_web_repartida(self, ws):
        for nombre in bootstrap.ARCHIVOS_WEB:
            repartido = ws / CARPETA / nombre
            self.assertTrue(repartido.is_file(), f"falta {CARPETA}/{nombre}")
            self.assertEqual(repartido.read_bytes(),
                             bootstrap.origen_web(nombre).read_bytes(), nombre)

    # ------------------------------------------------------------------ R5

    def test_la_lista_es_una_sola_y_lleva_todo_lo_que_la_web_necesita(self):
        """Sin cualquiera de estas piezas la web del workspace no funciona."""
        nombres = set(bootstrap.ARCHIVOS_WEB)
        self.assertLessEqual(
            {"servir.py", "abrir.py", "plantilla.html", "render.js", "base.css",
             "datos_tablero.py", "datos_contratos.py", "datos_presentaciones.py",
             "datos_flujos.py", "tablero.html", "contratos.html",
             "presentaciones.html", "flujos.html", "manifestar.py", "estado.py"},
            nombres)
        self.assertFalse(hasattr(bootstrap, "ARCHIVOS_CONTRATOS"),
                         "sigue habiendo una lista por visor")
        self.assertFalse(hasattr(bootstrap, "ARCHIVOS_PRESENTACIONES"),
                         "sigue habiendo una lista por visor")

    def test_bootstrap_reparte_la_web_entera(self):
        self.assert_web_repartida(self.workspace_nuevo())

    def test_actualizar_la_repone_donde_falta_y_la_deja_al_dia(self):
        ws = self.workspace_nuevo()
        shutil.rmtree(ws / CARPETA)                       # workspace anterior a la 081
        subprocess.run(["git", "-C", str(ws), "commit", "-qam", "sin web"],
                       check=True, env={**self.entorno, "GIT_AUTHOR_NAME": "t",
                                        "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                        "GIT_COMMITTER_EMAIL": "t@t"})
        r = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_web_repartida(ws)
        r = self.ejecutar(ACTUALIZAR, "revisar", str(ws))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("requisitos/web", r.stdout, "al día y aún lo marca")

    def test_las_carpetas_de_los_visores_viejos_no_se_quedan_en_el_workspace(self):
        ws = self.workspace_nuevo()
        for vieja in VIEJAS:
            with self.subTest(carpeta=vieja):
                self.assertFalse((ws / vieja).exists(),
                                 f"{vieja} sigue en el workspace")
        self.assertFalse((ws / "docs/00-metodo/requisitos/servir.py").exists())

    def test_en_el_workspace_la_web_sirve_el_tablero_y_los_contratos_con_estilos(self):
        """R5: en un workspace recién creado, `/` y `/contratos` responden 200 y la
        hoja que sirven es la que se repartió, no otra de otro layout."""
        ws = self.workspace_nuevo()
        hoja = ws / CARPETA / "base.css"
        self.assertTrue(hoja.is_file())
        hoja.write_text(hoja.read_text(encoding="utf-8") + "\n/* marca-081 */\n",
                        encoding="utf-8")
        s = socket.socket(); s.bind(("127.0.0.1", 0)); puerto = s.getsockname()[1]; s.close()
        proc = subprocess.Popen([sys.executable, str(ws / CARPETA / "servir.py"),
                                 "--workspace", str(ws), "--puerto", str(puerto),
                                 "--sin-navegador", "--minutos", "1"],
                                cwd=self.base, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        cuerpos = {}
        for _ in range(100):
            try:
                for ruta in ("/", "/contratos", "/base.css"):
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{puerto}{ruta}", timeout=2) as resp:
                        self.assertEqual(resp.status, 200, ruta)
                        cuerpos[ruta] = resp.read().decode("utf-8")
                break
            except Exception:
                time.sleep(0.1)
        self.assertEqual({"/", "/contratos", "/base.css"}, set(cuerpos),
                         "la web no arrancó en el workspace")
        self.assertIn("marca-081", cuerpos["/base.css"],
                      "sirve otro base.css, no el que se repartió")
        for ruta in ("/", "/contratos"):
            self.assertIn('<link rel="stylesheet" href="/base.css">', cuerpos[ruta])
            self.assertIn('class="barra-webs"', cuerpos[ruta])


if __name__ == "__main__":
    unittest.main()
