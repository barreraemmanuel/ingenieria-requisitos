"""081 · Una sola web: los cuatro visores son la misma página, en el mismo servidor.

Un test por criterio del contrato (`docs/05-trabajo/081-una-sola-web/especificacion.md`):

- R1 — un solo proceso sirve las cuatro páginas y todos sus datos bajo su prefijo, y
  ningún otro `servir.py` del repo se puede lanzar como servidor.
- R2 — barra común con los cuatro apartados en rutas del mismo origen, vuelta a la
  portada desde cualquiera y `popstate` para que la flecha atrás no pierda el estado.
- R3 — `web/abrir.py` reutiliza el servidor vivo del workspace y compone la URL del
  apartado; los lanzadores del método llaman a él.
- R4 — los tres rastros duros siguen escribiéndose igual: `.runtime/visor-contratos.log`
  por contrato mostrado, `.runtime/visor-<puerto>.log` al abrir los flujos y el recibo
  de `/presentaciones` en `.runtime/presentaciones/<unidad>/recibos/`.
- R6 — puerto por workspace, `INGENIERIA_REQUISITOS_PUERTO` manda, y un apartado que no
  existe es un 404 amable con enlace a la portada.
- R7 — sin `docs/02-flujos/planos/planos.json` la web arranca igual.
"""

import http.client
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parent
WEB = AQUI.parent
RAIZ = WEB.parent


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


servir = cargar("web_servir_bajo_prueba", WEB / "servir.py")
abrir_mod = cargar("web_abrir_bajo_prueba", WEB / "abrir.py")


CONTRATO = """---
unidad: 081-una-sola-web
tipo: feature
carril: completo
estado: en_obra
aprobado: no
actividad: presentar-y-observar-proceso
---

# 081 · Una sola web

## Qué

Una sola web para los cuatro apartados.
"""

PLANOS = {
    "version": 1,
    "proyecto": "prueba",
    "flujos": [{"id": "f1", "nombre": "Un flujo", "momento": "hoy", "pasos": []}],
    "actores": [],
}

MANIFIESTO = {
    "version": 1,
    "presentaciones": [
        {
            "id": "081-una-sola-web",
            "tipo": "validacion",
            "titulo": "081 · cómo lo pruebas tú",
            "version": "1",
            "pasos": ["Abre la web."],
            "evidencia": ["Tests: OK"],
            "opciones": ["confirmado", "problema"],
            "comentario_obligatorio": ["problema"],
        }
    ],
}


def workspace_sintetico(con_planos=True):
    """Un meta-repo mínimo: una unidad, un plano y una presentación."""
    raiz = Path(tempfile.mkdtemp(prefix="web-unica-"))
    (raiz / "main").mkdir()
    unidad = raiz / "docs" / "05-trabajo" / "081-una-sola-web"
    unidad.mkdir(parents=True)
    (unidad / "especificacion.md").write_text(CONTRATO, encoding="utf-8")
    (raiz / "docs" / "bugs").mkdir(parents=True)
    if con_planos:
        planos = raiz / "docs" / "02-flujos" / "planos"
        planos.mkdir(parents=True)
        (planos / "planos.json").write_text(json.dumps(PLANOS), encoding="utf-8")
    datos = raiz / ".runtime" / "presentaciones" / "081-una-sola-web"
    datos.mkdir(parents=True)
    (datos / "manifiesto.json").write_text(
        json.dumps(MANIFIESTO, ensure_ascii=False), encoding="utf-8")
    return raiz


class ServidorDePrueba:
    """La web única, en un puerto libre, sobre un workspace de verdad."""

    def __init__(self, workspace):
        self.servidor = servir.ServidorWeb(
            ("127.0.0.1", 0), servir.hacer_handler(str(workspace)))
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    @property
    def puerto(self):
        return self.servidor.server_address[1]

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def pedir(self, ruta, metodo="GET", cuerpo=None, tipo=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            cabeceras = {"Content-Type": tipo} if tipo else {}
            conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras)
            respuesta = conexion.getresponse()
            return respuesta.status, dict(respuesta.headers), respuesta.read()
        finally:
            conexion.close()


class ConWorkspace(unittest.TestCase):
    con_planos = True

    def setUp(self):
        self.raiz = workspace_sintetico(self.con_planos)
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.web = ServidorDePrueba(self.raiz)
        self.addCleanup(self.web.parar)


# --------------------------------------------------------------------------- R1

RUTAS_R1 = (
    "/",
    "/flujos",
    "/contratos",
    "/presentaciones",
    "/contratos/unidades.json",
    "/flujos/datos.json",
    "/presentaciones/manifiesto.json",
    "/tablero/estado.json",
    "/render.js",
    "/base.css",
)


class UnSoloPuertoTest(ConWorkspace):
    """R1 — un proceso, un puerto, las cuatro páginas y sus datos bajo prefijo."""

    def test_las_cuatro_paginas_y_sus_datos_responden_en_el_mismo_puerto(self):
        for ruta in RUTAS_R1:
            with self.subTest(ruta=ruta):
                estado, cabeceras, cuerpo = self.web.pedir(ruta)
                self.assertEqual(200, estado, "%s no responde 200" % ruta)
                self.assertTrue(cuerpo, "%s responde vacío" % ruta)
                if ruta.endswith(".json"):
                    self.assertIn("json", cabeceras["Content-Type"])
                elif ruta.endswith(".js"):
                    self.assertIn("javascript", cabeceras["Content-Type"])
                elif ruta.endswith(".css"):
                    self.assertIn("css", cabeceras["Content-Type"])
                else:
                    self.assertIn("html", cabeceras["Content-Type"])

    def test_cada_apartado_trae_sus_datos_de_verdad(self):
        _, _, unidades = self.web.pedir("/contratos/unidades.json")
        carpetas = [u["carpeta"] for u in json.loads(unidades)["unidades"]]
        self.assertIn("081-una-sola-web", carpetas)

        _, _, planos = self.web.pedir("/flujos/datos.json")
        self.assertEqual("prueba", json.loads(planos)["proyecto"])

        _, _, manifiesto = self.web.pedir("/presentaciones/manifiesto.json")
        self.assertEqual("081-una-sola-web",
                         json.loads(manifiesto)["presentaciones"][0]["id"])

        _, _, foto = self.web.pedir("/tablero/estado.json")
        self.assertIn("ahora", json.loads(foto))

    def test_el_contrato_se_sirve_bajo_el_prefijo_de_contratos(self):
        estado, cabeceras, cuerpo = self.web.pedir(
            "/contratos/contrato/081-una-sola-web.md")
        self.assertEqual(200, estado)
        self.assertIn("markdown", cabeceras["Content-Type"])
        self.assertIn(b"Una sola web", cuerpo)

    def test_ningun_otro_servir_del_repo_se_puede_lanzar_como_servidor(self):
        """R1: los cuatro anteriores son módulos de datos, no programas.

        Un `servir.py` que todavía tuviera su `main()` seguiría siendo un
        quinto puerto a un `python3` de distancia, que es justo lo que esta
        unidad quita.
        """
        otros = sorted(
            ruta for ruta in RAIZ.rglob("servir.py")
            if WEB not in ruta.parents and ".git" not in ruta.parts
        )
        self.assertTrue(otros, "no encuentro los módulos de datos de los visores")
        for ruta in otros:
            with self.subTest(fichero=str(ruta.relative_to(RAIZ))):
                texto = ruta.read_text(encoding="utf-8")
                self.assertNotIn('if __name__ == "__main__"', texto)
                self.assertNotIn("argparse", texto)
                self.assertNotIn("webbrowser", texto)
                self.assertNotIn("serve_forever", texto)

    def test_solo_la_web_unica_abre_un_puerto(self):
        """R1, tal cual lo pide §Verificación: `HTTPServer(` fuera de `web/`."""
        for ruta in sorted(RAIZ.rglob("*.py")):
            if WEB in ruta.parents or ruta == WEB / "servir.py":
                continue
            if ".git" in ruta.parts or "tests" in ruta.parts:
                continue
            with self.subTest(fichero=str(ruta.relative_to(RAIZ))):
                self.assertNotIn("HTTPServer(", ruta.read_text(encoding="utf-8"))


class DatosBajoSuPrefijoTest(unittest.TestCase):
    """R1 — «todos sus datos bajo su prefijo»: ningún guion de apartado puede pedir un
    dato en relativo.

    Montada la cáscara, `/flujos` (sin barra final) hace que `fetch("historial.json")`
    resuelva a `/historial.json`, que es la portada o su 404, no el dato: el apartado se
    queda sin lo que enseñaba y el `.catch` lo tapa en silencio. `RUTA(...)` es el único
    sitio que sabe el prefijo (y devuelve la ruta de siempre servido suelto), así que
    aquí se exige que TODA petición pase por él.
    """

    PLANTILLAS = ("visor/plantilla.html", "visor_contratos/plantilla.html",
                  "visor_presentaciones/plantilla.html", "visor_tablero/plantilla.html")
    LLAMADA = re.compile(r"\b(fetch|apiJSON)\(\s*(.{0,24})", re.S)

    def test_ninguna_peticion_de_un_apartado_va_sin_RUTA(self):
        for relativa in self.PLANTILLAS:
            texto = (RAIZ / relativa).read_text(encoding="utf-8")
            for funcion, argumento in self.LLAMADA.findall(texto):
                with self.subTest(plantilla=relativa, llamada=argumento.split("\n")[0]):
                    self.assertFalse(
                        argumento.startswith(('"', "'", "`")),
                        "%s: %s(%s…) pide un dato en relativo; envuélvelo en RUTA(...)"
                        % (relativa, funcion, argumento.split("\n")[0]))

    def test_el_historial_y_la_comparacion_de_flujos_cuelgan_del_prefijo(self):
        """Los dos datos que se perdieron: se piden por su ruta absoluta del apartado."""
        texto = (RAIZ / "visor/plantilla.html").read_text(encoding="utf-8")
        for dato in ("historial.json", "comparacion.json"):
            with self.subTest(dato=dato):
                self.assertTrue('RUTA("/%s")' % dato in texto,
                                "%s se sigue pidiendo sin RUTA(...)" % dato)

    def test_servidos_bajo_la_cascara_esos_dos_datos_responden(self):
        raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, raiz, True)
        web = ServidorDePrueba(raiz)
        self.addCleanup(web.parar)
        for dato in ("historial.json", "comparacion.json"):
            with self.subTest(dato=dato):
                estado, cabeceras, _ = web.pedir("/flujos/" + dato)
                self.assertEqual(200, estado)
                self.assertIn("json", cabeceras.get("Content-Type", ""))
                # …y en relativo (sin el prefijo) NO están: por eso hay que usar RUTA.
                self.assertEqual(404, web.pedir("/" + dato)[0])


# --------------------------------------------------------------------------- R2

class BarraYVueltaAtrasTest(unittest.TestCase):
    """R2 — DOM estático de la cáscara: los cuatro enlaces, del mismo origen."""

    @classmethod
    def setUpClass(cls):
        cls.cascara = (WEB / "plantilla.html").read_text(encoding="utf-8")

    def test_los_cuatro_apartados_son_rutas_relativas_del_mismo_origen(self):
        barra = re.search(r'<nav class="barra-webs".*?</nav>', self.cascara, re.S)
        self.assertIsNotNone(barra, "la cáscara no lleva la barra común")
        enlaces = re.findall(r'<a[^>]*href="([^"]+)"[^>]*data-web="([^"]+)"',
                             barra.group(0))
        self.assertEqual(
            [("/", "tablero"), ("/contratos", "contratos"),
             ("/presentaciones", "presentaciones"), ("/flujos", "flujos")],
            enlaces)
        self.assertNotIn("127.0.0.1", barra.group(0))
        self.assertNotIn("http://", barra.group(0))

    def test_la_cascara_escucha_popstate(self):
        self.assertIn("popstate", self.cascara)

    def test_desde_cualquier_apartado_se_vuelve_a_la_portada(self):
        """Cada página servida trae el enlace a `/` de la barra."""
        raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, raiz, True)
        web = ServidorDePrueba(raiz)
        self.addCleanup(web.parar)
        for ruta in ("/", "/flujos", "/contratos", "/presentaciones"):
            with self.subTest(ruta=ruta):
                _, _, cuerpo = web.pedir(ruta)
                html = cuerpo.decode("utf-8")
                self.assertIn('href="/" data-web="tablero"', html)
                self.assertNotIn("127.0.0.1:876", html)

    def test_el_apartado_servido_se_marca_a_si_mismo_y_solo_a_si_mismo(self):
        raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, raiz, True)
        web = ServidorDePrueba(raiz)
        self.addCleanup(web.parar)
        for ruta, cual in (("/", "tablero"), ("/flujos", "flujos"),
                           ("/contratos", "contratos"),
                           ("/presentaciones", "presentaciones")):
            with self.subTest(ruta=ruta):
                _, _, cuerpo = web.pedir(ruta)
                html = cuerpo.decode("utf-8")
                marcados = re.findall(r'data-web="([^"]+)"[^>]*aria-current="page"',
                                      html)
                marcados += re.findall(r'aria-current="page"[^>]*data-web="([^"]+)"',
                                       html)
                self.assertEqual([cual], marcados)


# --------------------------------------------------------------------------- R3, R6

class AbrirTest(unittest.TestCase):
    """R3/R6 — un solo lanzador: reutiliza la sesión y compone la URL."""

    def setUp(self):
        self.raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.otra = workspace_sintetico()
        self.addCleanup(shutil.rmtree, self.otra, True)

    def test_el_puerto_sale_del_workspace_y_dos_workspaces_no_chocan(self):
        self.assertNotEqual(abrir_mod.puerto_de(self.raiz),
                            abrir_mod.puerto_de(self.otra))
        self.assertEqual(abrir_mod.puerto_de(self.raiz),
                         abrir_mod.puerto_de(self.raiz))

    def test_la_variable_de_entorno_fija_el_puerto(self):
        previo = os.environ.get("INGENIERIA_REQUISITOS_PUERTO")
        os.environ["INGENIERIA_REQUISITOS_PUERTO"] = "8891"
        try:
            self.assertEqual(8891, abrir_mod.puerto_de(self.raiz))
        finally:
            if previo is None:
                os.environ.pop("INGENIERIA_REQUISITOS_PUERTO", None)
            else:
                os.environ["INGENIERIA_REQUISITOS_PUERTO"] = previo

    def test_compone_la_url_del_apartado_con_su_ancla(self):
        self.assertEqual(
            "http://127.0.0.1:9000/contratos#081-una-sola-web",
            abrir_mod.url_de(9000, "contratos#081-una-sola-web"))
        self.assertEqual("http://127.0.0.1:9000/", abrir_mod.url_de(9000, "tablero"))
        self.assertEqual("http://127.0.0.1:9000/flujos",
                         abrir_mod.url_de(9000, "flujos"))
        self.assertEqual("http://127.0.0.1:9000/presentaciones/081-una-sola-web",
                         abrir_mod.url_de(9000, "presentaciones/081-una-sola-web"))

    def test_la_segunda_llamada_reutiliza_el_servidor_vivo(self):
        primera = abrir_mod.abrir(self.raiz, abrir_mod.argumentos_prueba(
            apartado="contratos"))
        self.addCleanup(abrir_mod.detener, primera.proceso)
        self.assertIsNotNone(primera.proceso, "la primera llamada levanta el servidor")
        segunda = abrir_mod.abrir(self.raiz, abrir_mod.argumentos_prueba(
            apartado="flujos"))
        self.assertIsNone(segunda.proceso, "la segunda llamada abrió un segundo puerto")
        self.assertTrue(primera.url.endswith("/contratos"))
        self.assertTrue(segunda.url.endswith("/flujos"))
        self.assertEqual(primera.url.rsplit("/", 1)[0], segunda.url.rsplit("/", 1)[0])


class SinNavegadorTest(unittest.TestCase):
    """R3 — `--sin-navegador` sólo imprime la URL."""

    def test_el_lanzador_imprime_la_url_y_no_abre_nada(self):
        raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, raiz, True)
        salida = subprocess.run(
            [sys.executable, str(WEB / "abrir.py"), "--workspace", str(raiz),
             "--apartado", "contratos", "--sin-navegador", "--minutos", "0.05"],
            capture_output=True, text=True, timeout=60,
            env=dict(os.environ, PYTHONUTF8="1", IR_SIN_NAVEGADOR="1"))
        self.addCleanup(self._matar, raiz)
        self.assertEqual(0, salida.returncode, salida.stderr)
        self.assertRegex(salida.stdout, r"http://127\.0\.0\.1:\d+/contratos")

    def _matar(self, raiz):
        for registro in (raiz / ".runtime").glob("web-*.log"):
            registro.unlink(missing_ok=True)


# --------------------------------------------------------------------------- R4

class RastrosIntactosTest(ConWorkspace):
    """R4 — las tres puertas duras siguen encontrando su rastro."""

    def test_servir_un_contrato_deja_su_linea_en_visor_contratos_log(self):
        estado, _, _ = self.web.pedir("/contratos/contrato/081-una-sola-web.md")
        self.assertEqual(200, estado)
        registro = self.raiz / ".runtime" / "visor-contratos.log"
        self.assertTrue(registro.is_file(), "no se escribió el rastro de contratos")
        ultima = registro.read_text(encoding="utf-8").strip().splitlines()[-1]
        self.assertRegex(
            ultima,
            r"^\d{4}-\d{2}-\d{2}T[\d:]+ contrato mostrado: 081-una-sola-web$")

    def test_abrir_los_flujos_deja_el_rastro_que_lee_requisitos_aprobar(self):
        estado, _, _ = self.web.pedir("/flujos")
        self.assertEqual(200, estado)
        registros = sorted((self.raiz / ".runtime").glob("visor-*.log"))
        nombres = [r.name for r in registros if r.name != "visor-contratos.log"]
        self.assertTrue(nombres, "no se escribió el rastro de sesión de los flujos")

    def test_el_recibo_de_presentaciones_cae_donde_lo_lee_cerrar(self):
        decision = json.dumps({
            "presentacion": "081-una-sola-web",
            "version": "1",
            "contenido_revisado": "Abre la web.",
            "eleccion": "confirmado",
            "comentario": "",
            "confirmado": True,
        })
        estado, _, cuerpo = self.web.pedir(
            "/presentaciones/081-una-sola-web/decisiones", metodo="POST",
            cuerpo=decision.encode("utf-8"), tipo="application/json")
        self.assertEqual(201, estado, cuerpo)
        recibos = sorted(
            (self.raiz / ".runtime" / "presentaciones" / "081-una-sola-web"
             / "recibos").glob("*.json"))
        self.assertEqual(1, len(recibos))
        self.assertEqual("confirmado",
                         json.loads(recibos[0].read_text(encoding="utf-8"))["eleccion"])


# --------------------------------------------------------------------------- R6

class ApartadoInexistenteTest(ConWorkspace):
    """R6 — un apartado que no existe es un 404 amable, no un 500."""

    def test_una_ruta_desconocida_da_404_con_enlace_a_la_portada(self):
        estado, cabeceras, cuerpo = self.web.pedir("/loquesea")
        self.assertEqual(404, estado)
        self.assertIn("html", cabeceras["Content-Type"])
        html = cuerpo.decode("utf-8")
        self.assertIn('href="/"', html)

    def test_un_dato_desconocido_bajo_un_prefijo_tampoco_revienta(self):
        for ruta in ("/contratos/loquesea.json", "/flujos/loquesea.json",
                     "/tablero/loquesea.json", "/presentaciones/loquesea.json"):
            with self.subTest(ruta=ruta):
                estado, _, _ = self.web.pedir(ruta)
                self.assertEqual(404, estado)


# --------------------------------------------------------------------------- R7

class SinPlanosTest(ConWorkspace):
    """R7 — un proyecto sin planos todavía: la web arranca igual."""

    con_planos = False

    def test_los_otros_tres_apartados_funcionan(self):
        for ruta in ("/", "/contratos", "/presentaciones",
                     "/contratos/unidades.json", "/tablero/estado.json"):
            with self.subTest(ruta=ruta):
                estado, _, _ = self.web.pedir(ruta)
                self.assertEqual(200, estado)

    def test_flujos_dice_que_no_hay_planos_en_vez_de_caerse(self):
        estado, cabeceras, cuerpo = self.web.pedir("/flujos")
        self.assertEqual(200, estado)
        self.assertIn("html", cabeceras["Content-Type"])
        self.assertIn("no hay planos", cuerpo.decode("utf-8").lower())

    def test_los_datos_de_flujos_lo_dicen_como_json_y_no_como_500(self):
        estado, _, cuerpo = self.web.pedir("/flujos/datos.json")
        self.assertEqual(404, estado)
        self.assertIn("planos", json.loads(cuerpo)["error"].lower())


if __name__ == "__main__":
    unittest.main()


class ServirRespetaIrSinNavegadorTest(unittest.TestCase):
    """Bug 110: `servir.py` lanzado SIN `--sin-navegador` pero con `IR_SIN_NAVEGADOR=1` en el
    entorno no abre el navegador real (ni `BROWSER` ni `webbrowser.open`)."""

    def test_con_la_variable_no_abre_navegador(self):
        raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, raiz, True)
        anotador = raiz / "anotador.sh"
        huella = raiz / "navegador-abierto.txt"
        anotador.write_text("#!/bin/sh\necho abierto > '%s'\n" % huella, encoding="utf-8")
        anotador.chmod(0o755)
        proceso = subprocess.Popen(
            [sys.executable, str(WEB / "servir.py"), "--workspace", str(raiz),
             "--minutos", "0.05"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=dict(os.environ, PYTHONUTF8="1", IR_SIN_NAVEGADOR="1",
                     BROWSER=str(anotador)))
        try:
            salida, _ = proceso.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proceso.kill(); salida, _ = proceso.communicate()
        self.assertIn("en pie", salida)
        self.assertFalse(huella.exists(), "abrió el navegador real con IR_SIN_NAVEGADOR=1")

