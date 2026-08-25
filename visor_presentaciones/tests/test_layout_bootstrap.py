"""Bug 064 — la web de presentaciones en el layout que crea `bootstrap.py`.

Los tests de la 056 sirven las presentaciones desde el repo de código, donde
`visor_contratos/render.js` está al lado. Un workspace de alumno NO es ese
layout: `bootstrap.py` copia `ARCHIVOS_PRESENTACIONES` dentro de
`docs/00-metodo/requisitos/visor_presentaciones/` y nada más. Aquí se monta
exactamente ESE layout —con los ficheros que copia el bootstrap, en su
carpeta— y se piden las tres cosas que carga el navegador al abrir la web:
`/`, `/render.js` y una vista.

Antes del arreglo: `GET /render.js` moría con un `FileNotFoundError` sin
capturar dentro de `do_GET` (la conexión se cortaba, sin respuesta) y las
vistas quedaban en blanco con `ReferenceError: esc` porque el motor nunca
llegaba al navegador.
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
    """El layout de un workspace recién creado: sólo los ficheros que el
    bootstrap declara, en `docs/00-metodo/requisitos/visor_presentaciones/`.

    Se copia con la misma fuente que usa el bootstrap (`origen_presentacion`
    si existe; si no, la carpeta `visor_presentaciones/` del repo): así el
    test mide lo que el bootstrap reparte de verdad, no una lista paralela.
    """
    raiz = Path(tempfile.mkdtemp(prefix="visor-presentaciones-workspace-"))
    (raiz / "docs").mkdir()
    (raiz / "main").mkdir()
    carpeta = raiz / "docs" / "00-metodo" / "requisitos" / "visor_presentaciones"
    carpeta.mkdir(parents=True)
    for nombre in bootstrap.ARCHIVOS_PRESENTACIONES:
        origen = getattr(bootstrap, "origen_presentacion", None)
        origen = origen(nombre) if origen else RAIZ / "visor_presentaciones" / nombre
        shutil.copyfile(origen, carpeta / nombre)

    datos = raiz / ".runtime" / "presentaciones" / "unidad"
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
    """Importa el `servir.py` COPIADO (no el del repo): sus rutas relativas
    son las del workspace, que es justo lo que se está probando."""
    previo = sys.modules.get("manifestar")
    spec = importlib.util.spec_from_file_location("manifestar", carpeta / "manifestar.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["manifestar"] = modulo
    spec.loader.exec_module(modulo)
    try:
        spec = importlib.util.spec_from_file_location(
            "servir_workspace_064", carpeta / "servir.py")
        servir = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(servir)
    finally:
        if previo is None:
            sys.modules.pop("manifestar", None)
        else:
            sys.modules["manifestar"] = previo
    return servir


class LayoutDelBootstrapTest(unittest.TestCase):
    """R1/R2/R4 del bug 064, sobre el layout real del workspace."""

    def setUp(self):
        self.raiz, self.carpeta, self.datos = montar_layout_bootstrap()
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.servir = cargar_servir_copiado(self.carpeta)
        self.estado = {"ultimo": 0.0}
        self.servidor = self.servir.ServidorPresentaciones(
            ("127.0.0.1", 0),
            self.servir.hacer_handler(self.datos, self.estado, self.raiz),
        )
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

    def test_el_bootstrap_reparte_el_motor_con_las_presentaciones(self):
        """R1: `render.js` viaja al workspace; sin él la web nace en blanco."""
        self.assertIn("render.js", bootstrap.ARCHIVOS_PRESENTACIONES)
        self.assertTrue((self.carpeta / "render.js").is_file())

    def test_la_web_del_workspace_sirve_portada_motor_y_vista(self):
        """R1/R4: las tres peticiones que hace el navegador al abrir la web
        responden 200 en el layout del workspace."""
        estado_raiz, _, portada = self.pedir("/")
        self.assertEqual(200, estado_raiz)
        self.assertIn(b"<!doctype html>", portada.lower())

        estado_motor, cabeceras, motor = self.pedir("/render.js")
        self.assertEqual(200, estado_motor)
        self.assertIn("javascript", cabeceras["Content-Type"])
        self.assertIn(b"function esc(", motor)
        self.assertIn(b"function bloques(", motor)

        estado_vista, _, vista = self.pedir("/presentacion/validacion")
        self.assertEqual(200, estado_vista)
        self.assertEqual(portada, vista)

    def test_la_vista_no_se_queda_sin_esc_ni_bloques(self):
        """El `ReferenceError: esc` del reporte: la plantilla servida usa
        `esc(` y `bloques(` y su único `<script src>` es `/render.js`; si ese
        motor no llega con las funciones, la vista muere en blanco."""
        _, _, portada = self.pedir("/")
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
        """R2: ninguna excepción sin capturar en `do_GET`. Se borra el motor
        del workspace: la respuesta es 404, no una conexión cortada."""
        (self.carpeta / "render.js").unlink(missing_ok=True)
        estado, _, cuerpo = self.pedir("/render.js")
        self.assertEqual(404, estado)
        self.assertIn(b"error", cuerpo)


if __name__ == "__main__":
    unittest.main()
