"""155 · La web enseña también la investigación y la planificación.

Un test por criterio del contrato
(`docs/05-trabajo/155-web-con-investigacion-y-planificacion/especificacion.md`):

- R1 — la barra común tiene un quinto apartado «Plan» (`/plan`), en las CINCO páginas,
  y `web/abrir.py --apartado plan` compone su URL.
- R2 — `/plan` sirve `docs/03-investigacion/SINTESIS.md` y `docs/04-planificacion/ROADMAP.md`
  con índice lateral de sus `##`, y los `.md` que enlazan se sirven en
  `/plan/doc/<ruta>`, nunca fuera de `docs/`.
- R3 — sin esos dos ficheros el apartado carga igual y dice quién los escribe; una ruta
  fuera de `docs/` es un 404 con SALIDA.

Nivel: integración sobre el servidor HTTP con taller temporal, sin navegador (como
`test_aprobar_desde_la_web.py`).
"""

import http.client
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parent
WEB = AQUI.parent


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


servir = cargar("web_servir_fases", WEB / "servir.py")
abrir_mod = cargar("web_abrir_fases", WEB / "abrir.py")


SINTESIS = """# Síntesis de la investigación

Lo que se miró antes de escribir una línea.

## Qué se decidió

| Tema | Decisión |
|---|---|
| Lenguaje | Python de serie |

## Qué queda abierto

- Ver el [informe de soporte](informe-01-soporte-python.md).
"""

INFORME = """# Informe 01 · soporte de Python

Las versiones que se sostienen hoy.
"""

ROADMAP = """# Plan por delante

## Ahora

- La web enseña las dos fases.

## Después

- Lo demás.
"""

PLANOS = {"version": 1, "proyecto": "prueba",
          "flujos": [{"id": "f1", "nombre": "Un flujo", "momento": "hoy", "pasos": []}],
          "actores": []}

CONTRATO = """---
unidad: 155-web-con-investigacion-y-planificacion
tipo: feature
carril: normal
estado: en_obra
aprobado: no
actividad: presentar-y-observar-proceso
---

# 155 · La web enseña las fases 3 y 4

## Qué

Un quinto apartado.
"""


def taller(con_fases=True):
    """Un meta-repo mínimo, con o sin las fases 3 y 4 escritas."""
    raiz = Path(tempfile.mkdtemp(prefix="plan-fases-"))
    unidad = raiz / "docs" / "05-trabajo" / "155-web-con-investigacion-y-planificacion"
    unidad.mkdir(parents=True)
    (unidad / "especificacion.md").write_text(CONTRATO, encoding="utf-8")
    (raiz / "docs" / "bugs").mkdir(parents=True)
    planos = raiz / "docs" / "02-flujos" / "planos"
    planos.mkdir(parents=True)
    (planos / "planos.json").write_text(json.dumps(PLANOS), encoding="utf-8")
    if con_fases:
        investigacion = raiz / "docs" / "03-investigacion"
        investigacion.mkdir(parents=True)
        (investigacion / "SINTESIS.md").write_text(SINTESIS, encoding="utf-8")
        (investigacion / "informe-01-soporte-python.md").write_text(
            INFORME, encoding="utf-8")
        corpus = investigacion / "corpus"
        corpus.mkdir()
        (corpus / "nota.md").write_text("# Una nota suelta\n", encoding="utf-8")
        planificacion = raiz / "docs" / "04-planificacion"
        planificacion.mkdir(parents=True)
        (planificacion / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    return raiz


class ServidorDePrueba:
    """La web única, en un puerto libre, sobre un taller de verdad."""

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

    def pedir(self, ruta, metodo="GET"):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            conexion.request(metodo, ruta)
            respuesta = conexion.getresponse()
            return respuesta.status, respuesta.read()
        finally:
            conexion.close()

    def json(self, ruta):
        codigo, cuerpo = self.pedir(ruta)
        return codigo, json.loads(cuerpo.decode("utf-8"))

    def html(self, ruta):
        codigo, cuerpo = self.pedir(ruta)
        return codigo, cuerpo.decode("utf-8")


class ConTaller(unittest.TestCase):
    con_fases = True

    def setUp(self):
        self.raiz = taller(self.con_fases)
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.web = ServidorDePrueba(self.raiz)
        self.addCleanup(self.web.parar)


# --------------------------------------------------------------------------- R1

class QuintoApartadoTest(ConTaller):
    """R1 — «Plan» es un apartado más: está en la barra de las cinco páginas."""

    def test_la_barra_de_las_cinco_paginas_lleva_el_enlace_a_plan(self):
        for ruta in ("/", "/contratos", "/presentaciones", "/flujos", "/plan"):
            with self.subTest(ruta=ruta):
                codigo, html = self.web.html(ruta)
                self.assertEqual(200, codigo)
                self.assertIn('href="/plan" data-web="plan"', html)

    def test_el_apartado_plan_se_marca_a_si_mismo_y_solo_a_si_mismo(self):
        codigo, html = self.web.html("/plan")
        self.assertEqual(200, codigo)
        marcados = re.findall(r'data-web="([^"]+)"[^>]*aria-current="page"', html)
        marcados += re.findall(r'aria-current="page"[^>]*data-web="([^"]+)"', html)
        self.assertEqual(["plan"], marcados)

    def test_plan_es_una_clave_del_servicio_y_abrir_sabe_enrutarla(self):
        self.assertIn("plan", servir.CLAVES)
        codigo, meta = self.web.json("/meta.json")
        self.assertEqual(200, codigo)
        self.assertIn("plan", meta["apartados"])
        self.assertEqual("http://127.0.0.1:8770/plan",
                         abrir_mod.url_de(8770, "plan"))

    def test_los_otros_apartados_no_se_llevan_puesta_la_seccion_de_plan(self):
        """La sección vive en la cáscara: si no se recorta, viaja a las otras cuatro."""
        for ruta in ("/", "/contratos", "/presentaciones", "/flujos"):
            with self.subTest(ruta=ruta):
                _, html = self.web.html(ruta)
                self.assertNotIn('id="indice-plan"', html)


# --------------------------------------------------------------------------- R2

class LasDosFasesSeLeenTest(ConTaller):
    """R2 — los dos documentos, su índice y los informes que enlazan."""

    def test_el_dato_trae_los_dos_documentos_con_su_markdown(self):
        codigo, datos = self.web.json("/plan/dato")
        self.assertEqual(200, codigo)
        claves = [d["clave"] for d in datos["documentos"]]
        self.assertEqual(["sintesis", "roadmap"], claves)
        porClave = {d["clave"]: d for d in datos["documentos"]}
        self.assertTrue(porClave["sintesis"]["existe"])
        self.assertIn("| Tema | Decisión |", porClave["sintesis"]["markdown"])
        self.assertEqual("docs/03-investigacion/SINTESIS.md",
                         porClave["sintesis"]["ruta"])
        self.assertTrue(porClave["roadmap"]["existe"])
        self.assertIn("La web enseña las dos fases.",
                      porClave["roadmap"]["markdown"])
        self.assertEqual("docs/04-planificacion/ROADMAP.md",
                         porClave["roadmap"]["ruta"])

    def test_el_indice_lateral_sale_de_los_segundos_niveles(self):
        _, datos = self.web.json("/plan/dato")
        porClave = {d["clave"]: d for d in datos["documentos"]}
        self.assertEqual(["Qué se decidió", "Qué queda abierto"],
                         [s["titulo"] for s in porClave["sintesis"]["secciones"]])
        self.assertEqual(["Ahora", "Después"],
                         [s["titulo"] for s in porClave["roadmap"]["secciones"]])
        anclas = [s["ancla"] for s in porClave["sintesis"]["secciones"]]
        self.assertEqual(len(anclas), len(set(anclas)))
        for ancla in anclas:
            self.assertRegex(ancla, r"^[a-z0-9-]+$")

    def test_la_pagina_monta_el_indice_y_el_motor_de_render_compartido(self):
        codigo, html = self.web.html("/plan")
        self.assertEqual(200, codigo)
        self.assertIn('class="menu-lateral"', html)
        self.assertIn('id="indice-plan"', html)
        self.assertIn('src="/render.js"', html)
        self.assertIn("bloques(", html)
        self.assertIn('"apartado": "plan"', html)

    def test_los_informes_de_investigacion_se_listan(self):
        _, datos = self.web.json("/plan/dato")
        rutas = [i["ruta"] for i in datos["informes"]]
        self.assertIn("docs/03-investigacion/informe-01-soporte-python.md", rutas)
        self.assertNotIn("docs/03-investigacion/SINTESIS.md", rutas)

    def test_el_indice_no_se_llena_con_el_material_de_las_subcarpetas(self):
        _, datos = self.web.json("/plan/dato")
        rutas = [i["ruta"] for i in datos["informes"]]
        self.assertNotIn("docs/03-investigacion/corpus/nota.md", rutas)
        codigo, dato = self.web.json("/plan/doc/docs/03-investigacion/corpus/nota.md")
        self.assertEqual(200, codigo, "lo enlazado se abre aunque no se liste")
        self.assertEqual("Una nota suelta", dato["titulo"])

    def test_un_informe_enlazado_se_sirve_en_solo_lectura(self):
        codigo, datos = self.web.json(
            "/plan/doc/docs/03-investigacion/informe-01-soporte-python.md")
        self.assertEqual(200, codigo)
        self.assertIn("Las versiones que se sostienen hoy.", datos["markdown"])
        self.assertEqual("Informe 01 · soporte de Python", datos["titulo"])

    def test_el_apartado_plan_no_escribe_nada(self):
        for metodo in ("POST", "PUT", "DELETE"):
            with self.subTest(metodo=metodo):
                codigo, _ = self.web.pedir("/plan/dato", metodo)
                self.assertEqual(404, codigo)


# --------------------------------------------------------------------------- R3

class SinLasFasesYFueraDeDocsTest(unittest.TestCase):
    """R3 — el caso límite: un taller sin fases 3 y 4, y la frontera de `docs/`."""

    def setUp(self):
        self.raiz = taller(con_fases=False)
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.web = ServidorDePrueba(self.raiz)
        self.addCleanup(self.web.parar)

    def test_sin_los_dos_ficheros_el_apartado_carga_igual(self):
        codigo, html = self.web.html("/plan")
        self.assertEqual(200, codigo)
        self.assertIn('href="/plan" data-web="plan"', html)

    def test_cada_documento_que_falta_dice_quien_lo_escribe(self):
        codigo, datos = self.web.json("/plan/dato")
        self.assertEqual(200, codigo)
        porClave = {d["clave"]: d for d in datos["documentos"]}
        self.assertFalse(porClave["sintesis"]["existe"])
        self.assertIn("todavía no existe", porClave["sintesis"]["aviso"])
        self.assertIn("fase 3", porClave["sintesis"]["aviso"])
        self.assertIn("runbooks/investigacion.md", porClave["sintesis"]["aviso"])
        self.assertFalse(porClave["roadmap"]["existe"])
        self.assertIn("fase 4", porClave["roadmap"]["aviso"])
        self.assertIn("runbooks/planificacion.md", porClave["roadmap"]["aviso"])
        self.assertEqual([], datos["informes"])


class FronteraDeDocsTest(ConTaller):
    """R3 (segunda mitad) — de `docs/` no se sale, y el rechazo dice cómo salir."""

    FUERA = (
        "/plan/doc/../../etc/passwd",
        "/plan/doc/docs/../../etc/passwd",
        "/plan/doc//etc/passwd",
        "/plan/doc/main/README.md",
    )

    def test_una_ruta_fuera_de_docs_es_404_con_salida(self):
        for ruta in self.FUERA:
            with self.subTest(ruta=ruta):
                codigo, datos = self.web.json(ruta)
                self.assertEqual(404, codigo)
                self.assertIn("SALIDA", datos["error"])

    def test_lo_que_no_es_markdown_no_se_sirve(self):
        codigo, datos = self.web.json("/plan/doc/docs/02-flujos/planos/planos.json")
        self.assertEqual(404, codigo)
        self.assertIn("SALIDA", datos["error"])

    def test_un_markdown_que_no_existe_es_404_con_salida(self):
        codigo, datos = self.web.json("/plan/doc/docs/03-investigacion/no-hay.md")
        self.assertEqual(404, codigo)
        self.assertIn("SALIDA", datos["error"])


if __name__ == "__main__":
    unittest.main()
