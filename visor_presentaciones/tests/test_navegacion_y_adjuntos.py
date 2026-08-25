"""Suite de la unidad 056 — la web de presentaciones funciona como las otras.

Cubre los seis criterios del contrato:

- R1 — misma cabecera, paleta, tipografía e interruptor de tema que el visor
  de contratos (comparación de bloques, línea a línea).
- R2 — menú lateral con todas las presentaciones agrupadas por tipo, con su
  estado; una sola plantilla sirve todas las rutas (la navegación es de hash,
  sin recarga: se comprueba sobre el HTML servido, sin E2E de navegador).
- R3 — «bandeja» siempre presente en el menú; tras decidir, el cliente vuelve
  al hash de la bandeja.
- R4 — adjuntos `.md` y de código servidos por `/adjunto/<ruta>` y pintados
  con el motor compartido (`render.js`, bug 055).
- R5 — un adjunto fuera del workspace, con `..`, absoluto o vía symlink se
  rechaza (403 en el servidor, y `manifestar.validar` rechaza lo sintáctico).
- R6 — un manifiesto v1 de hoy (sin adjuntos) y los recibos ya escritos se
  siguen leyendo igual; se prueba contra el manifiesto real de hoy si está.
"""

import http.client
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from visor_presentaciones import manifestar, servir

BASE = Path(__file__).resolve().parent.parent
PLANTILLA = BASE / "plantilla.html"
PLANTILLA_CONTRATOS = BASE.parent / "visor_contratos" / "plantilla.html"
RENDER_JS = BASE.parent / "visor_contratos" / "render.js"
NODE = shutil.which("node")


def manifiesto_con_adjuntos():
    return {
        "version": 1,
        "presentaciones": [
            {
                "id": "bandeja", "tipo": "bandeja", "titulo": "Pruebas pendientes",
                "version": "1", "estado": "pendiente",
                "peticiones": [
                    {"id": "P-1", "titulo": "Validar 047", "detalle": "detalle",
                     "estado": "pendiente", "destino": "validacion-047"},
                ],
            },
            {
                "id": "lectura-047", "tipo": "lector", "variante": "investigacion",
                "titulo": "047 · Leer el mapa", "version": "1",
                "preguntas": ["¿Qué guardián falta?"], "hechos": ["Hay una tabla."],
                "fuentes": ["docs/detectores.md"], "hallazgos": ["La tabla se lee."],
                "conclusiones": ["Queda claro."], "limites": ["Sin archivos completos."],
            },
            {
                "id": "validacion-047", "tipo": "validacion",
                "titulo": "047 · Validar el mapa de detectores", "version": "1",
                "pasos": ["Lee detectores.md", "Lee ejemplo.py"],
                "evidencia": ["Tests: OK"],
                "opciones": ["confirmado", "problema"],
                "comentario_obligatorio": ["problema"],
                "adjuntos": ["docs/detectores.md", "main/ejemplo.py"],
            },
        ],
    }


def montar_workspace_y_datos():
    """Un workspace con `docs/` y `main/` (la frontera de R5) y una carpeta de
    datos con el manifiesto, fuera del workspace real del checkout."""
    raiz = Path(tempfile.mkdtemp(prefix="visor-presentaciones-test-"))
    (raiz / "docs").mkdir()
    (raiz / "main").mkdir()
    (raiz / "docs" / "detectores.md").write_text(
        "# Detectores\n\n| Guardián | Ve | No ve |\n|---|---|---|\n"
        "| lint | estilo | intención |\n", encoding="utf-8",
    )
    (raiz / "main" / "ejemplo.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    datos = raiz / ".runtime" / "presentaciones" / "pruebas"
    datos.mkdir(parents=True)
    (datos / "manifiesto.json").write_text(
        json.dumps(manifiesto_con_adjuntos()), encoding="utf-8"
    )
    return raiz, datos


class ServidorDePrueba:
    def __init__(self, datos, workspace=None):
        self.estado = {"ultimo": 0.0}
        self.servidor = servir.ServidorPresentaciones(
            ("127.0.0.1", 0), servir.hacer_handler(datos, self.estado, workspace)
        )
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def pedir(self, ruta, metodo="GET", cuerpo=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        try:
            datos_cuerpo = None if cuerpo is None else json.dumps(cuerpo)
            cabeceras = {} if datos_cuerpo is None else {"Content-Type": "application/json"}
            conexion.request(metodo, ruta, body=datos_cuerpo, headers=cabeceras)
            respuesta = conexion.getresponse()
            contenido = respuesta.read()
            return respuesta.status, respuesta.headers, contenido
        finally:
            conexion.close()


class NavegacionYAdjuntosTest(unittest.TestCase):
    """R2-R5: servidor real, workspace real en disco."""

    def setUp(self):
        self.workspace, self.datos = montar_workspace_y_datos()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.servidor = ServidorDePrueba(self.datos, self.workspace)
        self.addCleanup(self.servidor.parar)

    # ---- R2: menú con todas las presentaciones, agrupadas por tipo ----

    def test_una_sola_plantilla_sirve_todas_las_rutas(self):
        """La navegación es de hash: toda ruta del servidor devuelve la MISMA
        plantilla; no hay una página por vista (eso sería «recargar»)."""
        _, _, raiz = self.servidor.pedir("/")
        _, _, directa = self.servidor.pedir("/presentacion/validacion-047")
        self.assertEqual(raiz, directa)
        self.assertIn(b"<!doctype html>", raiz.lower())

    def test_el_manifiesto_trae_las_presentaciones_para_el_menu(self):
        estado, _, cuerpo = self.servidor.pedir("/manifiesto.json")
        self.assertEqual(200, estado)
        presentaciones = json.loads(cuerpo)["presentaciones"]
        self.assertEqual(
            {"bandeja", "lectura-047", "validacion-047"},
            {p["id"] for p in presentaciones},
        )

    def test_la_plantilla_agrupa_el_menu_por_tipo_sin_la_bandeja(self):
        """La bandeja tiene su propio botón fijo (R3); los grupos del menú
        cubren lector/propuesta/validacion, en este orden."""
        texto = PLANTILLA.read_text(encoding="utf-8")
        grupos = re.findall(r'\{tipo:\s*"([^"]+)",\s*titulo:\s*"[^"]+"\}', texto)
        self.assertEqual(["lector", "propuesta", "validacion"], grupos)

    def test_la_plantilla_navega_por_hash_sin_recargar(self):
        texto = PLANTILLA.read_text(encoding="utf-8")
        self.assertIn('addEventListener("hashchange"', texto)
        self.assertNotIn("location.reload", texto)
        self.assertNotIn("location.href =", texto)

    # ---- R3: bandeja siempre visible + vuelta tras decidir ----

    def test_bandeja_siempre_tiene_boton_fijo_en_el_menu(self):
        texto = PLANTILLA.read_text(encoding="utf-8")
        self.assertIn("boton-bandeja", texto)

    def test_tras_decidir_el_cliente_vuelve_al_hash_de_la_bandeja(self):
        texto = PLANTILLA.read_text(encoding="utf-8")
        self.assertIn("if (bandeja) irA(bandeja.id", texto)

    # ---- R4: adjuntos markdown y de código ----

    def test_get_adjunto_markdown_se_sirve_con_su_contenido(self):
        estado, cabeceras, cuerpo = self.servidor.pedir("/adjunto/docs/detectores.md")
        self.assertEqual(200, estado)
        self.assertIn("text/markdown", cabeceras["Content-Type"])
        self.assertIn(b"| Gu", cuerpo)

    def test_get_adjunto_de_codigo_se_sirve_como_texto_plano(self):
        estado, cabeceras, cuerpo = self.servidor.pedir("/adjunto/main/ejemplo.py")
        self.assertEqual(200, estado)
        self.assertIn("text/plain", cabeceras["Content-Type"])
        self.assertIn(b"def suma", cuerpo)

    def test_get_adjunto_no_declarado_da_404(self):
        (self.workspace / "docs" / "otro.md").write_text("otro", encoding="utf-8")
        estado, _, _ = self.servidor.pedir("/adjunto/docs/otro.md")
        self.assertEqual(404, estado)

    @unittest.skipUnless(NODE, "sin node no se puede ejecutar el motor compartido")
    def test_el_adjunto_markdown_se_pinta_con_el_motor_compartido(self):
        """El mismo `render.js` del bug 055 pinta la tabla de tres columnas
        del adjunto: no hay un segundo render duplicado en presentaciones."""
        lineas = (self.workspace / "docs" / "detectores.md").read_text(encoding="utf-8").split("\n")
        programa = RENDER_JS.read_text(encoding="utf-8") + (
            "\nprocess.stdout.write(bloques(%s));" % json.dumps(lineas)
        )
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fichero:
            fichero.write(programa)
            ruta = fichero.name
        try:
            salida = subprocess.run([NODE, ruta], capture_output=True, text=True, timeout=5, check=True)
        finally:
            Path(ruta).unlink(missing_ok=True)
        html = salida.stdout
        self.assertIn("<table>", html)
        self.assertIn("<thead>", html)
        self.assertEqual(html.count("<th>"), 3)

    def test_la_plantilla_pinta_codigo_con_numeros_de_linea(self):
        texto = PLANTILLA.read_text(encoding="utf-8")
        self.assertIn('class="num"', texto)
        self.assertIn("pre.codigo", PLANTILLA.read_text(encoding="utf-8"))

    # ---- R5: seguridad de adjuntos ----

    def test_adjunto_con_symlink_fuera_del_workspace_da_403_y_no_lee_nada(self):
        exterior = Path(tempfile.mkdtemp(prefix="fuera-"))
        self.addCleanup(shutil.rmtree, exterior, True)
        secreto = exterior / "secreto.md"
        secreto.write_text("CONTENIDO SECRETO", encoding="utf-8")
        (self.workspace / "docs" / "detectores.md").unlink()
        (self.workspace / "docs" / "detectores.md").symlink_to(secreto)

        estado, _, cuerpo = self.servidor.pedir("/adjunto/docs/detectores.md")

        self.assertEqual(403, estado)
        self.assertNotIn(b"SECRETO", cuerpo)

    def test_manifiesto_con_adjunto_con_puntos_o_absoluto_no_valida(self):
        for ruta_mala in ("../fuera.md", "/etc/passwd", "~/secreto.md", "docs/../../fuera.md"):
            datos = manifiesto_con_adjuntos()
            datos["presentaciones"][2]["adjuntos"] = [ruta_mala]
            with self.subTest(ruta=ruta_mala):
                with self.assertRaisesRegex(ValueError, "adjunto"):
                    manifestar.validar(datos)

    def test_manifiesto_con_adjunto_en_bandeja_no_valida(self):
        datos = manifiesto_con_adjuntos()
        datos["presentaciones"][0]["adjuntos"] = ["docs/detectores.md"]
        with self.assertRaisesRegex(ValueError, ".+"):
            manifestar.validar(datos)


class ManifiestoV1SinAdjuntosTest(unittest.TestCase):
    """R6 — caso límite: un manifiesto de hoy, sin `adjuntos`, sigue abriendo
    igual, y los recibos ya escritos se siguen leyendo."""

    def setUp(self):
        self.workspace, self.datos = montar_workspace_y_datos()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        # Manifiesto v1 "de hoy": sin el campo `adjuntos` en ninguna presentación.
        sin_adjuntos = manifiesto_con_adjuntos()
        del sin_adjuntos["presentaciones"][2]["adjuntos"]
        (self.datos / "manifiesto.json").write_text(json.dumps(sin_adjuntos), encoding="utf-8")
        (self.datos / "recibos").mkdir()
        (self.datos / "recibos" / "un-recibo.json").write_text(json.dumps({
            "id": "un-recibo", "presentacion": "validacion-047", "version": "1",
            "contenido_revisado": "Lee detectores.md\nLee ejemplo.py",
            "eleccion": "confirmado", "comentario": "", "fecha": "2026-08-24T00:00:00+00:00",
        }), encoding="utf-8")
        self.servidor = ServidorDePrueba(self.datos, self.workspace)
        self.addCleanup(self.servidor.parar)

    def test_abre_igual_sin_el_campo_adjuntos(self):
        estado, _, cuerpo = self.servidor.pedir("/manifiesto.json")
        self.assertEqual(200, estado)
        presentaciones = json.loads(cuerpo)["presentaciones"]
        validacion = next(p for p in presentaciones if p["id"] == "validacion-047")
        self.assertNotIn("adjuntos", validacion)

    def test_los_recibos_de_hoy_se_siguen_leyendo(self):
        estado, _, cuerpo = self.servidor.pedir("/recibos.json")
        self.assertEqual(200, estado)
        recibos = json.loads(cuerpo)["recibos"]
        self.assertEqual(["un-recibo"], [r["id"] for r in recibos])

    def test_la_raiz_se_sigue_sirviendo(self):
        estado, cabeceras, cuerpo = self.servidor.pedir("/")
        self.assertEqual(200, estado)
        self.assertIn("text/html", cabeceras["Content-Type"])


class ManifiestoRealDeHoyTest(unittest.TestCase):
    """La fila 6 de "cómo lo pruebas tú": el manifiesto real de hoy, si está
    al lado del checkout (se salta si no, igual que el resto de la suite)."""

    @staticmethod
    def datos_reales():
        for candidato in BASE.parents:
            posible = candidato / ".runtime" / "presentaciones" / "pruebas-25-08"
            if (posible / "manifiesto.json").is_file():
                return posible
        return None

    def setUp(self):
        self.datos = self.datos_reales()
        if self.datos is None:
            self.skipTest("no hay manifiesto real al lado de este checkout")
        self.servidor = ServidorDePrueba(self.datos)
        self.addCleanup(self.servidor.parar)

    def test_el_manifiesto_real_de_hoy_abre_y_lista_sus_recibos(self):
        estado, _, cuerpo = self.servidor.pedir("/manifiesto.json")
        self.assertEqual(200, estado)
        presentaciones = json.loads(cuerpo)["presentaciones"]
        self.assertTrue(any(p["tipo"] == "bandeja" for p in presentaciones))

        estado, _, cuerpo = self.servidor.pedir("/recibos.json")
        self.assertEqual(200, estado)
        self.assertGreaterEqual(len(json.loads(cuerpo)["recibos"]), 1)


def bloque_paleta(texto):
    inicio = texto.index(":root {")
    marca = texto.index(':root[data-theme="light"]', inicio)
    fin = texto.index("}", texto.index("{", marca)) + 1
    return [l.strip() for l in texto[inicio:fin].splitlines() if l.strip()]


def bloque_interruptor(texto):
    inicio = texto.index('var GUARDADO = "visor-tema";')
    fin = texto.index("})();", inicio)
    return [l.strip() for l in texto[inicio:fin].splitlines() if l.strip()]


class EstiloIgualQueElVisorDeContratosTest(unittest.TestCase):
    """R1 — misma cabecera, paleta, tipografía e interruptor de tema que el
    visor de contratos (mismo método que el R2 de la 009: bloques comparados
    línea a línea, no el fichero entero: presentaciones añade CSS propia
    para pestañas/adjuntos que contratos no necesita)."""

    def setUp(self):
        self.presentaciones = PLANTILLA.read_text(encoding="utf-8")
        self.contratos = PLANTILLA_CONTRATOS.read_text(encoding="utf-8")

    def test_la_paleta_es_la_misma_linea_a_linea(self):
        esperado = bloque_paleta(self.contratos)
        self.assertGreater(len(esperado), 20, "la paleta de contratos no se pudo leer")
        self.assertEqual(esperado, bloque_paleta(self.presentaciones))

    def test_el_interruptor_de_tema_se_comporta_igual(self):
        esperado = bloque_interruptor(self.contratos)
        self.assertGreater(len(esperado), 15, "el interruptor de contratos no se pudo leer")
        self.assertEqual(esperado, bloque_interruptor(self.presentaciones))

    def test_la_cabecera_es_la_misma(self):
        for declaracion in (
            'header { position: relative; padding-right: 44px; }',
            '.boton-tema { position: absolute; top: -2px; right: 0; width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--line); background: var(--sheet); color: var(--muted); font-size: 15px; line-height: 1; cursor: pointer; }',
            "h1 { font-size: 25px; line-height: 1.2; margin: 6px 0 2px; }",
            ".sub { color: var(--muted); font-size: 13.5px; }",
        ):
            with self.subTest(declaracion=declaracion):
                self.assertIn(declaracion, self.contratos)
                self.assertIn(declaracion, self.presentaciones)

    def test_la_tipografia_es_la_misma(self):
        for declaracion in (
            "--sans: -apple-system, BlinkMacSystemFont",
            "font: 16px/1.5 var(--sans)",
        ):
            with self.subTest(declaracion=declaracion):
                self.assertIn(declaracion, self.presentaciones)

    def test_el_menu_lateral_usa_las_mismas_clases_que_contratos(self):
        for declaracion in (
            ".menu-unidades { flex: 0 0 268px;",
            ".chip-pendiente { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }",
            ".chip-aprobado { background: var(--ok-bg); border-color: var(--ok); color: var(--ok); }",
        ):
            with self.subTest(declaracion=declaracion):
                self.assertIn(declaracion, self.contratos)
                self.assertIn(declaracion, self.presentaciones)


class AdjuntosFiltradosTest(unittest.TestCase):
    """Bug 064 R3 — el adjunto pasa por la MISMA frontera que el manifiesto.

    La 051 firmó (R2/R5) que la web nunca enseña secretos ni vuelca salida
    extensa: el manifiesto lo garantiza con `manifestar.SENSIBLE` y un tope de
    2000 caracteres por campo. `/adjunto/` se saltaba las dos cosas y servía
    el cuerpo entero del fichero tal cual.
    """

    def setUp(self):
        self.workspace, self.datos = montar_workspace_y_datos()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        manifiesto = manifiesto_con_adjuntos()
        manifiesto["presentaciones"][2]["adjuntos"] = [
            "docs/despliegue.md", "main/grande.txt", "docs/notas.md",
            "main/tira.txt",
        ]
        (self.datos / "manifiesto.json").write_text(
            json.dumps(manifiesto), encoding="utf-8")
        (self.workspace / "docs" / "despliegue.md").write_text(
            "# Despliegue\n\nLlamada de ejemplo:\n\n"
            "    curl -H 'Authorization: Bearer x' https://api.local/v1\n"
            "\nDudas: soporte.tecnico@ejemplo.local\n"
            "\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIB\n",
            encoding="utf-8",
        )
        (self.workspace / "main" / "grande.txt").write_text(
            "linea de relleno para pasar del tope\n" * 12000, encoding="utf-8")
        # Un mega en UNA sola línea y sin ninguna `@`: el peor caso de la
        # alternativa de correo de `SENSIBLE`. Es lo que tiene un SVG con una
        # imagen embebida o un `.min.js` — ficheros que un alumno adjunta.
        (self.workspace / "main" / "tira.txt").write_text(
            "a" * (1024 * 1024) + "\n", encoding="utf-8")
        # `.private/` es la carpeta de evidencia sensible del método: aunque
        # `manifestar` ya rechaza declararla (empieza por punto), un enlace
        # dentro del workspace la alcanzaba igual.
        (self.workspace / ".private").mkdir()
        (self.workspace / ".private" / "secreto.md").write_text(
            "credencial del usuario\n", encoding="utf-8")
        (self.workspace / "docs" / "notas.md").symlink_to(
            self.workspace / ".private" / "secreto.md")
        self.servidor = ServidorDePrueba(self.datos, self.workspace)
        self.addCleanup(self.servidor.parar)

    def test_el_adjunto_con_un_bearer_dentro_sale_filtrado(self):
        estado, _, cuerpo = self.servidor.pedir("/adjunto/docs/despliegue.md")
        self.assertEqual(200, estado)
        self.assertNotIn(b"Authorization: Bearer x", cuerpo)
        self.assertNotRegex(cuerpo.decode("utf-8"), servir.manifestar.SENSIBLE)
        # El resto del adjunto sigue sirviendo: se tacha lo sensible, no todo.
        self.assertIn(b"# Despliegue", cuerpo)

    def test_el_adjunto_tacha_correos_y_claves_privadas(self):
        """R3: acotar la regex por coste no puede perder lo que tachaba."""
        estado, _, cuerpo = self.servidor.pedir("/adjunto/docs/despliegue.md")
        self.assertEqual(200, estado)
        self.assertNotIn(b"soporte.tecnico@ejemplo.local", cuerpo)
        self.assertNotIn(b"PRIVATE KEY", cuerpo)
        self.assertNotRegex(cuerpo.decode("utf-8"), servir.manifestar.SENSIBLE)

    def test_una_tira_larga_sin_arroba_no_cuelga_el_servidor(self):
        """R3: el tope acota el COSTE, no sólo el tamaño de la respuesta.

        Filtrar el fichero ENTERO antes de recortarlo dejaba correr la
        alternativa de correo (cuadrática sobre tiras sin `@`) sobre el mega
        completo: decenas de segundos con el servidor bloqueado, un adjunto
        para tumbar la web. Se recorta primero y se filtra sólo el recorte.
        """
        arranque = time.monotonic()
        estado, _, cuerpo = self.servidor.pedir("/adjunto/main/tira.txt")
        tardanza = time.monotonic() - arranque
        self.assertEqual(200, estado)
        self.assertLess(tardanza, 1.0, "un adjunto grande cuelga el servidor")
        self.assertLessEqual(len(cuerpo), servir.TOPE_ADJUNTO + 2000)
        self.assertIn("truncado", cuerpo.decode("utf-8").lower())

    def test_el_adjunto_enorme_se_trunca_con_aviso_visible(self):
        estado, _, cuerpo = self.servidor.pedir("/adjunto/main/grande.txt")
        self.assertEqual(200, estado)
        self.assertLessEqual(len(cuerpo), servir.TOPE_ADJUNTO + 2000)
        self.assertIn("truncado", cuerpo.decode("utf-8").lower())

    def test_un_adjunto_que_acaba_en_private_nunca_se_sirve(self):
        """R3: `.private/` queda fuera aunque se llegue por un enlace que no
        sale del workspace (la guarda de la 056 sólo mira la frontera)."""
        estado, _, cuerpo = self.servidor.pedir("/adjunto/docs/notas.md")
        self.assertEqual(403, estado)
        self.assertNotIn(b"credencial", cuerpo)


if __name__ == "__main__":
    unittest.main()
