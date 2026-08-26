"""Suite del visor de contratos (unidad 009-revisar-contratos).

Cubre los cuatro criterios del contrato:

- R1 — el listado trae TODAS las unidades del workspace y el contrato de
  cualquiera se sirve entero (integración: se monta un workspace real en disco
  y se habla con el servidor por HTTP).
- R2 — la paleta y el interruptor de tema son los mismos que los del visor de
  flujos (unitario: comparación línea a línea de los dos ficheros).
- R3 — la plantilla pinta el Qué y los Criterios antes que el Cómo técnico y el
  Plan de trabajo, que además nacen plegados (BLUF).
- R4 — una unidad sin fecha de aprobación sale listada como pendiente, nunca
  oculta.
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

BASE = Path(__file__).resolve().parent.parent
SERVIR = BASE / "servir.py"
PLANTILLA = BASE / "plantilla.html"
PLANTILLA_FLUJOS = BASE.parent / "visor" / "plantilla.html"


def cargar_servir():
    if str(SERVIR.parent) not in sys.path:
        sys.path.insert(0, str(SERVIR.parent))
    spec = importlib.util.spec_from_file_location("servir_contratos_bajo_prueba", SERVIR)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


CONTRATO_009 = """---
unidad: 009-revisar-contratos
tipo: feature
carril: completo
estado: en_obra
aprobado: 2026-08-15
actividad: revisar-contratos
---

# 009 · Una web para leer los contratos de trabajo, en BLUF

## Qué (el contrato, en idioma de negocio)

Nate abre una web y lee los contratos sin tocar ficheros a mano.

## Criterios de aceptación

- **R1** — ve el listado completo.
"""

CONTRATO_010 = """---
unidad: 010-personalidad-agente
tipo: feature
carril: expres
estado: especificada
aprobado: no
---

# 010 · Personalidad del agente

## Qué (el contrato, en idioma de negocio)

Todavía sin aprobar.
"""

CONTRATO_008 = """---
unidad: 008-modularizar-runbook-tokens
tipo: refactor
carril: directo
estado: fusionada
aprobado: 2026-08-10
---

# 008 · Modularizar el RUNBOOK
"""


def montar_workspace():
    """Workspace de meta-repo con tres unidades reales y el ruido que convive
    con ellas (ESTADO.md, archivo/, peticiones/), que no son unidades."""
    raiz = Path(tempfile.mkdtemp(prefix="visor-contratos-test-"))
    trabajo = raiz / "docs" / "05-trabajo"
    for nombre, texto in (
        ("008-modularizar-runbook-tokens", CONTRATO_008),
        ("009-revisar-contratos", CONTRATO_009),
        ("010-personalidad-agente", CONTRATO_010),
    ):
        carpeta = trabajo / nombre
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(texto, encoding="utf-8")
    (trabajo / "ESTADO.md").write_text("# Estado\n", encoding="utf-8")
    (trabajo / "peticiones").mkdir()
    archivada = trabajo / "archivo" / "001-vieja"
    archivada.mkdir(parents=True)
    (archivada / "especificacion.md").write_text(CONTRATO_008, encoding="utf-8")
    return raiz


class ServidorDePrueba:
    """Levanta el visor de contratos en un puerto libre de 127.0.0.1."""

    def __init__(self, workspace):
        self.servir = cargar_servir()
        estado = {"ultimo": 0.0}
        self.servidor = self.servir.ServidorVisorContratos(
            ("127.0.0.1", 0), self.servir.hacer_handler(str(workspace), estado)
        )
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def pedir(self, ruta, metodo="GET"):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        try:
            conexion.request(metodo, ruta)
            respuesta = conexion.getresponse()
            cuerpo = respuesta.read().decode("utf-8")
            return respuesta.status, respuesta.headers, cuerpo
        finally:
            conexion.close()


class RutasDelVisorTest(unittest.TestCase):
    """Integración: cruzan el sistema de ficheros del meta-repo y el HTTP real."""

    def setUp(self):
        self.workspace = montar_workspace()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.servidor = ServidorDePrueba(self.workspace)
        self.addCleanup(self.servidor.parar)

    def unidades(self):
        codigo, _, cuerpo = self.servidor.pedir("/unidades.json")
        self.assertEqual(200, codigo)
        return json.loads(cuerpo)["unidades"]

    def test_lista_todas_las_unidades_del_workspace(self):
        """R1 — ninguna unidad del workspace se pierde por el camino."""
        nombres = [u["unidad"] for u in self.unidades()]
        self.assertEqual(
            [
                "008-modularizar-runbook-tokens",
                "009-revisar-contratos",
                "010-personalidad-agente",
            ],
            nombres,
        )

    def test_el_listado_trae_los_campos_del_frontmatter(self):
        """R1 — el listado se lee del frontmatter real, no se inventa."""
        una = [u for u in self.unidades() if u["unidad"] == "009-revisar-contratos"][0]
        self.assertEqual("feature", una["tipo"])
        self.assertEqual("completo", una["carril"])
        self.assertEqual("en_obra", una["estado"])
        self.assertEqual("2026-08-15", una["aprobado"])
        self.assertFalse(una["pendiente_de_aprobar"])

    def test_el_listado_ignora_lo_que_no_es_una_unidad(self):
        """Ni ESTADO.md, ni peticiones/, ni el archivo/ de unidades cerradas."""
        nombres = [u["unidad"] for u in self.unidades()]
        self.assertNotIn("peticiones", nombres)
        self.assertNotIn("archivo", nombres)
        self.assertNotIn("001-vieja", nombres)

    def test_sirve_el_markdown_exacto_del_contrato(self):
        """R1 — la ruta que consume la plantilla devuelve el fichero tal cual."""
        codigo, cabeceras, cuerpo = self.servidor.pedir(
            "/contrato/009-revisar-contratos.md"
        )
        self.assertEqual(200, codigo)
        # En Windows, Path.write_text() traduce \n a \r\n al escribir el
        # fixture (modo texto universal); el propio contenido servido es
        # idéntico línea a línea, así que se normaliza antes de comparar.
        self.assertEqual(CONTRATO_009, cuerpo.replace("\r\n", "\n"))
        self.assertIn("charset=utf-8", cabeceras["Content-Type"])
        self.assertEqual("no-store", cabeceras["Cache-Control"])

    def test_una_unidad_inexistente_da_404_sin_inventar_contenido(self):
        codigo, _, _ = self.servidor.pedir("/contrato/999-no-existe.md")
        self.assertEqual(404, codigo)

    def test_la_ruta_de_contrato_no_deja_salir_del_workspace(self):
        for ruta in (
            "/contrato/../../../../etc/passwd.md",
            "/contrato/..%2f..%2fAGENTS.md",
            "/contrato/archivo%2f001-vieja.md",
        ):
            with self.subTest(ruta=ruta):
                codigo, _, cuerpo = self.servidor.pedir(ruta)
                self.assertEqual(404, codigo)
                self.assertNotIn("root:", cuerpo)

    def test_la_raiz_sirve_la_plantilla(self):
        codigo, cabeceras, cuerpo = self.servidor.pedir("/")
        self.assertEqual(200, codigo)
        self.assertIn("text/html", cabeceras["Content-Type"])
        self.assertIn("<!doctype html>", cuerpo.lower())

    def test_es_de_solo_lectura(self):
        """Aprobar o pedir cambios sigue siendo por conversación, no por la web."""
        codigo, _, cuerpo = self.servidor.pedir("/unidades.json", metodo="POST")
        self.assertEqual(405, codigo)
        self.assertIn("solo lectura", json.loads(cuerpo)["error"])


class UnidadPendienteTest(unittest.TestCase):
    """R4 — caso límite: contrato aún sin aprobar."""

    def setUp(self):
        self.workspace = montar_workspace()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.servidor = ServidorDePrueba(self.workspace)
        self.addCleanup(self.servidor.parar)

    def test_la_unidad_sin_fecha_de_aprobacion_sale_marcada_como_pendiente(self):
        _, _, cuerpo = self.servidor.pedir("/unidades.json")
        unidades = json.loads(cuerpo)["unidades"]
        nombres = [u["unidad"] for u in unidades]
        self.assertIn("010-personalidad-agente", nombres, "no puede desaparecer")
        pendiente = [u for u in unidades if u["unidad"] == "010-personalidad-agente"][0]
        self.assertTrue(pendiente["pendiente_de_aprobar"])

    def test_una_unidad_sin_frontmatter_aprobado_tambien_es_pendiente(self):
        carpeta = self.workspace / "docs" / "05-trabajo" / "011-sin-campo"
        carpeta.mkdir()
        (carpeta / "especificacion.md").write_text(
            "---\nunidad: 011-sin-campo\nestado: especificada\n---\n\n# 011\n",
            encoding="utf-8",
        )
        _, _, cuerpo = self.servidor.pedir("/unidades.json")
        unidades = json.loads(cuerpo)["unidades"]
        sin_campo = [u for u in unidades if u["unidad"] == "011-sin-campo"][0]
        self.assertTrue(sin_campo["pendiente_de_aprobar"])
        self.assertEqual("", sin_campo["aprobado"])


CONTRATO_CON_COMENTARIOS = """---
unidad: 012-quitar-sandbox-so-lanzador
tipo: refactor            # feature | refactor | migracion | documentacion
carril: completo           # normal | completo
estado: en_obra
aprobado: 2026-08-15             # LO PONE EL USUARIO, jamás el agente
---

# 012 · Quitar el sandbox
"""


class FrontmatterDeLaPlantillaTest(unittest.TestCase):
    """Caso límite de campo: las especificaciones nacen de `plantillas/` y
    arrastran el comentario guía a la derecha del valor. Es comentario YAML, no
    dato: sin recortarlo, una unidad APROBADA salía marcada como pendiente."""

    def setUp(self):
        self.workspace = montar_workspace()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        carpeta = self.workspace / "docs" / "05-trabajo" / "012-quitar-sandbox-so-lanzador"
        carpeta.mkdir()
        (carpeta / "especificacion.md").write_text(
            CONTRATO_CON_COMENTARIOS, encoding="utf-8"
        )
        self.servidor = ServidorDePrueba(self.workspace)
        self.addCleanup(self.servidor.parar)

    def test_el_comentario_guia_no_contamina_el_valor(self):
        _, _, cuerpo = self.servidor.pedir("/unidades.json")
        unidades = json.loads(cuerpo)["unidades"]
        u = [x for x in unidades if x["unidad"] == "012-quitar-sandbox-so-lanzador"][0]
        self.assertEqual("refactor", u["tipo"])
        self.assertEqual("completo", u["carril"])
        self.assertEqual("2026-08-15", u["aprobado"])
        self.assertFalse(u["pendiente_de_aprobar"], "está aprobada, no pendiente")


class WorkspaceRealTest(unittest.TestCase):
    """Integración con el meta-repo de verdad: si está al lado, se lee.

    Es el escenario de la fila 1 de "cómo lo pruebas tú"; se salta cuando la
    suite corre sin meta-repo (CI del repo de código a secas).
    """

    @staticmethod
    def workspace_real():
        """El meta-repo se busca subiendo por los padres, no asumiendo la
        profundidad del checkout: vale igual desde main/ que desde
        worktrees/<unidad>/ (mitad pendiente del bug 019)."""
        for candidato in BASE.parents:
            if (candidato / "docs" / "05-trabajo").is_dir():
                return candidato
        return None

    def setUp(self):
        self.WORKSPACE = self.workspace_real()
        if self.WORKSPACE is None:
            self.skipTest("no hay meta-repo por encima de este checkout")
        self.servidor = ServidorDePrueba(self.WORKSPACE)
        self.addCleanup(self.servidor.parar)

    def unidades_reales(self):
        """Las carpetas NNN-slug con especificacion.md que existen HOY en el
        meta-repo — el test se ancla a lo que hay, no a un nombre grabado que
        se archiva y deja el test ciego (bug 019)."""
        trabajo = self.WORKSPACE / "docs" / "05-trabajo"
        return sorted(
            p.name for p in trabajo.iterdir()
            if p.is_dir() and (p / "especificacion.md").is_file()
        )

    def bugs_reales(self):
        """Los `NNN-slug.md` de `docs/bugs/` que HOY siguen pidiendo un OK (R5, bug
        054): `aprobado: no` (o sin fecha) y los `estado: planificada` — el mismo
        filtro que aplica `listar_bugs`, para no ahogar los pendientes entre las
        docenas de bugs ya `mergeada` del historial (hueco H2 de la ronda 2)."""
        bugs = self.WORKSPACE / "docs" / "bugs"
        if not bugs.is_dir():
            return []
        servir = cargar_servir()
        pendientes = []
        for p in sorted(bugs.glob("*.md")):
            if not re.match(r"^\d{3}-[a-z0-9][a-z0-9-]*$", p.stem):
                continue
            campos = servir.leer_frontmatter(p.read_text(encoding="utf-8"))
            aprobado = campos.get("aprobado", "")
            estado = campos.get("estado", "")
            if not servir.FECHA.match(aprobado) or estado == "planificada":
                pendientes.append(p.stem)
        return sorted(pendientes)

    def test_lista_las_unidades_reales_del_workspace(self):
        reales = self.unidades_reales()
        if not reales:
            self.skipTest("el meta-repo no tiene ninguna unidad activa ahora mismo")
        _, _, cuerpo = self.servidor.pedir("/unidades.json")
        unidades = json.loads(cuerpo)["unidades"]
        # R5 (bug 054): el listado ya no es solo docs/05-trabajo/, también trae
        # docs/bugs/ — se filtra por origen para seguir anclando el viejo contrato
        # (unidades de trabajo EXACTAS) sin perder cobertura sobre los bugs.
        nombres_trabajo = sorted(u["carpeta"] for u in unidades if u["origen"] == "trabajo")
        self.assertEqual(nombres_trabajo, reales,
                         "el visor debe listar EXACTAMENTE las unidades de docs/05-trabajo")
        for u in unidades:
            with self.subTest(unidad=u["unidad"]):
                self.assertNotIn("#", u["aprobado"], "comentario YAML sin recortar")
                self.assertNotIn("#", u["tipo"])

    def test_lista_tambien_los_bugs_reales_del_workspace(self):
        """R5 (bug 054): docs/bugs/*.md también se listan, no solo docs/05-trabajo/."""
        bugs = self.bugs_reales()
        if not bugs:
            self.skipTest("el meta-repo no tiene ningún bug ahora mismo")
        _, _, cuerpo = self.servidor.pedir("/unidades.json")
        unidades = json.loads(cuerpo)["unidades"]
        nombres_bug = sorted(u["carpeta"] for u in unidades if u["origen"] == "bug")
        self.assertEqual(nombres_bug, bugs,
                         "el visor debe listar EXACTAMENTE los bugs de docs/bugs/")

    def test_sirve_el_contrato_de_una_unidad_viva(self):
        reales = self.unidades_reales()
        if not reales:
            self.skipTest("el meta-repo no tiene ninguna unidad activa ahora mismo")
        _, _, cuerpo = self.servidor.pedir("/unidades.json")
        unidades = json.loads(cuerpo)["unidades"]
        viva = next(u["carpeta"] for u in unidades if u["origen"] == "trabajo")
        _, _, contrato = self.servidor.pedir(f"/contrato/{viva}.md")
        self.assertIn("## Qué (el contrato, en idioma de negocio)", contrato)
        self.assertIn("## Criterios de aceptación", contrato)


BASE_CSS = PLANTILLA.parent.parent / "visor" / "base.css"
ENLACE_BASE_CSS = '<link rel="stylesheet" href="/base.css">'


def bloque_paleta(texto):
    """Las líneas de la paleta: desde `:root {` hasta cerrar el bloque
    `:root[data-theme="light"]`, sin espacios de sangrado ni líneas vacías."""
    inicio = texto.index(":root {")
    marca = texto.index(':root[data-theme="light"]', inicio)
    fin = texto.index("}", texto.index("{", marca)) + 1
    return [l.strip() for l in texto[inicio:fin].splitlines() if l.strip()]


def bloque_interruptor(texto):
    """El script del interruptor de tema, de `var GUARDADO` a su cierre."""
    inicio = texto.index('var GUARDADO = "visor-tema";')
    fin = texto.index("})();", inicio)
    return [l.strip() for l in texto[inicio:fin].splitlines() if l.strip()]


class TemaIgualQueElVisorDeFlujosTest(unittest.TestCase):
    """R2 — riesgo de divergencia visual entre las dos webs."""

    def setUp(self):
        self.contratos = PLANTILLA.read_text(encoding="utf-8")
        self.flujos = PLANTILLA_FLUJOS.read_text(encoding="utf-8")

    def test_la_paleta_ya_no_se_copia_sino_que_se_enlaza(self):
        """R2, releído por la 076.

        El riesgo de divergencia visual se cerraba comparando la paleta línea
        a línea entre las dos plantillas. Desde la 076 no hay dos paletas que
        comparar: hay una, en `visor/base.css`, y las dos webs la enlazan.
        """
        paleta = bloque_paleta(BASE_CSS.read_text(encoding="utf-8"))
        self.assertGreater(len(paleta), 20, "la paleta de base.css no se leyó")
        for nombre, texto in (("contratos", self.contratos),
                              ("flujos", self.flujos)):
            with self.subTest(web=nombre):
                self.assertIn(ENLACE_BASE_CSS, texto)
                self.assertNotIn(":root", texto)

    def test_el_interruptor_de_tema_se_comporta_igual(self):
        esperado = bloque_interruptor(self.flujos)
        self.assertGreater(len(esperado), 15, "el interruptor de flujos no se pudo leer")
        self.assertEqual(esperado, bloque_interruptor(self.contratos))

    def test_la_tipografia_es_la_misma(self):
        hoja = BASE_CSS.read_text(encoding="utf-8")
        for declaracion in (
        # Unidad 082: la pila dejó de ser sans y pasó a ser MONOESPACIADA en
        # todo. Lo que este test vigila no cambia —una sola pila, en la
        # hoja común, para los cuatro apartados—, cambia cuál es.
            '--mono: "SF Mono"',
            "--sans: var(--mono)",
            "font: 16px/1.5 var(--sans)",
        ):
            with self.subTest(declaracion=declaracion):
                self.assertIn(declaracion, hoja)

    def test_no_toca_la_plantilla_del_visor_de_flujos(self):
        """El visor de flujos sigue siendo el que pinta planos.json."""
        self.assertIn("Planos del proyecto", self.flujos)
        self.assertNotIn("unidades.json", self.flujos)


class OrdenBlufTest(unittest.TestCase):
    """R3 — la conclusión primero: Qué y Criterios arriba, lo técnico plegado."""

    def setUp(self):
        texto = PLANTILLA.read_text(encoding="utf-8")
        self.secciones = re.findall(
            r'\{\s*prefijo:\s*"([^"]+)"\s*,\s*plegada:\s*(true|false)\s*\}', texto
        )

    def posicion(self, prefijo):
        for i, (nombre, _) in enumerate(self.secciones):
            if nombre.startswith(prefijo):
                return i
        self.fail("la plantilla no declara la sección " + prefijo)

    def plegada(self, prefijo):
        for nombre, plegada in self.secciones:
            if nombre.startswith(prefijo):
                return plegada == "true"
        self.fail("la plantilla no declara la sección " + prefijo)

    def test_la_plantilla_declara_el_orden_bluf(self):
        self.assertGreaterEqual(len(self.secciones), 6)

    def test_que_y_criterios_van_antes_que_lo_tecnico(self):
        for tecnica in ("Cómo (enfoque técnico)", "Contexto para el constructor",
                        "Plan de trabajo"):
            with self.subTest(seccion=tecnica):
                self.assertLess(self.posicion("Qué"), self.posicion(tecnica))
                self.assertLess(
                    self.posicion("Criterios de aceptación"), self.posicion(tecnica)
                )

    def test_lo_de_negocio_se_ve_abierto_y_lo_tecnico_plegado(self):
        self.assertFalse(self.plegada("Qué"))
        self.assertFalse(self.plegada("Criterios de aceptación"))
        self.assertFalse(self.plegada("Cómo lo pruebas tú"))
        self.assertTrue(self.plegada("Cómo (enfoque técnico)"))
        self.assertTrue(self.plegada("Contexto para el constructor"))
        self.assertTrue(self.plegada("Plan de trabajo"))


CONTRATO_BUG_030 = """---
unidad: 030-bug-pendiente
tipo: bug
carril: normal
estado: planificada
aprobado: no
actividad: revisar-contratos
---

# 030 · BUG de prueba

## 1 · Reporte
Algo se rompió y todavía nadie lo ha aprobado.
"""


class RastroDeAperturaTest(unittest.TestCase):
    """R2 (bug 054) — cada contrato SERVIDO deja fecha ISO + NNN-slug en
    `.runtime/visor-contratos.log`, igual que `requisitos.anotar_apertura`."""

    def setUp(self):
        self.workspace = montar_workspace()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.servidor = ServidorDePrueba(self.workspace)
        self.addCleanup(self.servidor.parar)

    def rastro(self):
        ruta = self.workspace / ".runtime" / "visor-contratos.log"
        return ruta.read_text(encoding="utf-8") if ruta.is_file() else ""

    def test_no_hay_rastro_antes_de_pedir_ningun_contrato(self):
        self.assertEqual("", self.rastro())

    def test_servir_un_contrato_deja_fecha_y_nombre_en_el_rastro(self):
        codigo, _, _ = self.servidor.pedir("/contrato/009-revisar-contratos.md")
        self.assertEqual(200, codigo)
        texto = self.rastro()
        self.assertRegex(
            texto,
            r"(?m)^\d{4}-\d{2}-\d{2}T[\d:]+ contrato mostrado: 009-revisar-contratos$",
        )

    def test_se_anota_tambien_cuando_el_servidor_ya_estaba_levantado(self):
        """El servidor de la prueba ya está arriba: no es un arranque, y aun así anota."""
        self.servidor.pedir("/contrato/009-revisar-contratos.md")
        primera = self.rastro().count("009-revisar-contratos")
        self.servidor.pedir("/contrato/009-revisar-contratos.md")
        segunda = self.rastro().count("009-revisar-contratos")
        self.assertGreater(segunda, primera, "una segunda petición debe dejar otra línea")

    def test_una_unidad_no_pedida_no_deja_rastro(self):
        self.servidor.pedir("/contrato/010-personalidad-agente.md")
        self.assertNotIn("009-revisar-contratos", self.rastro())

    def test_un_404_no_deja_rastro(self):
        self.servidor.pedir("/contrato/999-no-existe.md")
        self.assertEqual("", self.rastro())


class BugsEnElVisorTest(unittest.TestCase):
    """R5 (bug 054) — `docs/bugs/*.md` también son contratos que piden un OK: se listan y
    se sirven, no solo `docs/05-trabajo/`."""

    def setUp(self):
        self.workspace = montar_workspace()
        bugs = self.workspace / "docs" / "bugs"
        bugs.mkdir(parents=True)
        (bugs / "030-bug-pendiente.md").write_text(CONTRATO_BUG_030, encoding="utf-8")
        (bugs / "INDICE.md").write_text("# Índice de bugs\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.servidor = ServidorDePrueba(self.workspace)
        self.addCleanup(self.servidor.parar)

    def unidades(self):
        codigo, _, cuerpo = self.servidor.pedir("/unidades.json")
        self.assertEqual(200, codigo)
        return json.loads(cuerpo)["unidades"]

    def test_el_listado_incluye_los_bugs(self):
        nombres = [u["unidad"] for u in self.unidades()]
        self.assertIn("030-bug-pendiente", nombres)
        # Y las unidades de 05-trabajo siguen ahí: no es un reemplazo, es una suma.
        self.assertIn("009-revisar-contratos", nombres)

    def test_indice_md_no_es_un_bug(self):
        nombres = [u["unidad"] for u in self.unidades()]
        self.assertNotIn("INDICE", nombres)

    def test_un_bug_sin_aprobar_sale_marcado_pendiente(self):
        bug = [u for u in self.unidades() if u["unidad"] == "030-bug-pendiente"][0]
        self.assertTrue(bug["pendiente_de_aprobar"])
        self.assertEqual("planificada", bug["estado"])

    def test_sirve_el_markdown_exacto_del_bug(self):
        codigo, cabeceras, cuerpo = self.servidor.pedir("/contrato/030-bug-pendiente.md")
        self.assertEqual(200, codigo)
        self.assertEqual(CONTRATO_BUG_030, cuerpo.replace("\r\n", "\n"))
        self.assertIn("charset=utf-8", cabeceras["Content-Type"])

    def test_servir_un_bug_tambien_deja_rastro(self):
        """R2 + R5 juntas: un bug mostrado cuenta igual que una unidad."""
        self.servidor.pedir("/contrato/030-bug-pendiente.md")
        ruta = self.workspace / ".runtime" / "visor-contratos.log"
        self.assertIn("030-bug-pendiente", ruta.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
