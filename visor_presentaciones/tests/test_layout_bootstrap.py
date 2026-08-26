"""Bug 064, releído por la unidad 081: la web en el layout que crea `bootstrap.py`.

Los tests de la 056 servían las presentaciones desde el repo de código, donde
`visor_contratos/render.js` estaba al lado. Un workspace de alumno no es ese layout, y
desde la 081 tampoco es el de la 064: `bootstrap.py` copia `ARCHIVOS_WEB` —los cuatro
módulos de datos, sus plantillas, la cáscara, el motor y la hoja— dentro de
`docs/00-metodo/requisitos/web/`, aplanado y con nombre propio. Aquí se monta
exactamente ESE layout y se piden las cosas que carga el navegador al abrir la web.

La lección del 064 sigue vigente y es la que se vigila: un fichero que falta tiene que
ser un 404, nunca un `FileNotFoundError` sin capturar que corta la conexión y deja la
página a medias con `ReferenceError: esc`.
"""

import http.client
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from visor import bootstrap

RAIZ = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")


def montar_layout_bootstrap():
    """El layout de un workspace recién creado: sólo los ficheros que el bootstrap
    declara en `ARCHIVOS_WEB`, en `docs/00-metodo/requisitos/web/`."""
    raiz = Path(tempfile.mkdtemp(prefix="web-workspace-"))
    (raiz / "main").mkdir()
    (raiz / "docs" / "05-trabajo").mkdir(parents=True)
    (raiz / "docs" / "bugs").mkdir()
    carpeta = raiz / "docs" / "00-metodo" / "requisitos" / "web"
    carpeta.mkdir(parents=True)
    for nombre in bootstrap.ARCHIVOS_WEB:
        shutil.copyfile(bootstrap.origen_web(nombre), carpeta / nombre)
    # `revision.py` no es de la web: viaja en ARCHIVOS_REQUISITOS, al lado.
    shutil.copyfile(RAIZ / "visor" / "revision.py",
                    carpeta.parent / "revision.py")

    datos = raiz / ".runtime" / "presentaciones" / "081-unidad"
    datos.mkdir(parents=True)
    (datos / "manifiesto.json").write_text(
        json.dumps({"version": 1, "presentaciones": [
            {"id": "bandeja", "tipo": "bandeja", "titulo": "Peticiones",
             "version": "1", "estado": "pendiente", "peticiones": [
                 {"id": "P-1", "titulo": "Validar", "detalle": "detalle",
                  "estado": "pendiente", "destino": "validacion"}]},
            {"id": "validacion", "tipo": "validacion", "titulo": "Validar",
             "version": "1", "pasos": ["Abre la web."], "evidencia": ["Tests: OK"],
             "opciones": ["confirmado", "problema"],
             "comentario_obligatorio": ["problema"]},
        ]}), encoding="utf-8",
    )
    return raiz, carpeta, datos


def cargar_servir_copiado(carpeta):
    """Importa el `servir.py` COPIADO (no el del repo): sus rutas relativas son las
    del workspace, que es justo lo que se está probando."""
    spec = importlib.util.spec_from_file_location(
        "web_servir_workspace_064", carpeta / "servir.py")
    servir = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = servir
    spec.loader.exec_module(servir)
    return servir


class LayoutDelBootstrapTest(unittest.TestCase):
    """R1/R2/R4 del bug 064 y R5 de la 081, sobre el layout real del workspace."""

    def setUp(self):
        self.raiz, self.carpeta, self.datos = montar_layout_bootstrap()
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.servir = cargar_servir_copiado(self.carpeta)
        self.servidor = self.servir.ServidorWeb(
            ("127.0.0.1", 0), self.servir.hacer_handler(str(self.raiz)))
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()
        self.addCleanup(self.parar)

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def pedir(self, ruta):
        conexion = http.client.HTTPConnection(
            "127.0.0.1", self.servidor.server_address[1], timeout=5)
        try:
            conexion.request("GET", ruta)
            respuesta = conexion.getresponse()
            return respuesta.status, respuesta.headers, respuesta.read()
        finally:
            conexion.close()

    def test_el_bootstrap_reparte_el_motor_con_la_web(self):
        """R1: `render.js` viaja al workspace; sin él la web nace en blanco."""
        self.assertIn("render.js", bootstrap.ARCHIVOS_WEB)
        self.assertTrue((self.carpeta / "render.js").is_file())

    def test_la_web_del_workspace_sirve_los_cuatro_apartados_y_el_motor(self):
        """R1/R4: lo que pide el navegador al abrir la web responde 200 en el
        layout del workspace, sin `visor_contratos/` ni `visor/` al lado."""
        for ruta in ("/", "/contratos", "/presentaciones", "/flujos"):
            with self.subTest(ruta=ruta):
                estado, _, cuerpo = self.pedir(ruta)
                self.assertEqual(200, estado)
                self.assertIn(b"<!doctype html>", cuerpo.lower())

        estado_motor, cabeceras, motor = self.pedir("/render.js")
        self.assertEqual(200, estado_motor)
        self.assertIn("javascript", cabeceras["Content-Type"])
        self.assertIn(b"function esc(", motor)
        self.assertIn(b"function bloques(", motor)

        estado_hoja, cabeceras, hoja = self.pedir("/base.css")
        self.assertEqual(200, estado_hoja)
        self.assertIn("css", cabeceras["Content-Type"])
        self.assertIn(b".barra-webs", hoja)

    def test_la_vista_no_se_queda_sin_esc_ni_bloques(self):
        """El `ReferenceError: esc` del reporte: la página servida usa `esc(` y
        `bloques(` y su único `<script src>` es `/render.js`; si ese motor no llega
        con las funciones, la vista muere en blanco."""
        _, _, portada = self.pedir("/presentaciones")
        html = portada.decode("utf-8")
        self.assertIn("esc(", html)
        self.assertIn("bloques(", html)
        self.assertIn('<script src="/render.js"></script>', html)

        _, _, motor = self.pedir("/render.js")
        if not NODE:
            self.skipTest("sin node no se puede ejecutar el motor servido")
        programa = motor.decode("utf-8") + (
            '\nprocess.stdout.write(esc("<a>") + "|" + bloques(["### Hola"]));')
        with tempfile.NamedTemporaryFile(
                "w", suffix=".js", delete=False, encoding="utf-8") as fichero:
            fichero.write(programa)
            ruta = fichero.name
        try:
            salida = subprocess.run([NODE, ruta], capture_output=True, text=True,
                                    timeout=10)
        finally:
            Path(ruta).unlink(missing_ok=True)
        self.assertNotIn("ReferenceError", salida.stderr)
        self.assertEqual(0, salida.returncode, salida.stderr)
        self.assertIn("&lt;a&gt;", salida.stdout)
        self.assertIn("<h4>Hola</h4>", salida.stdout)

    def test_un_fichero_que_falta_da_404_y_no_tumba_la_conexion(self):
        """R2: ninguna excepción sin capturar en `do_GET`. Se borra el motor del
        workspace: la respuesta es 404, no una conexión cortada."""
        (self.carpeta / "render.js").unlink(missing_ok=True)
        estado, _, cuerpo = self.pedir("/render.js")
        self.assertEqual(404, estado)
        self.assertIn(b"error", cuerpo)


if __name__ == "__main__":
    unittest.main()
