"""091 · Aprobar (y pedir cambios) desde la web: la parte que YA existe, fijada.

Hasta aquí el OK del usuario acababa escrito por el agente. Desde el 26-08 la web
única tiene dos únicas escrituras, y las dispara el usuario con un clic:

    POST /contratos/aprobar/<NNN-slug>        → `aprobado: <hoy>` + rastro
    POST /contratos/pedir-cambios/<NNN-slug>  → una sección fechada al final

Este fichero es la red que impide que eso se caiga sin que nadie se entere, y
sobre todo que la frontera se ensanche: TODO lo demás sigue siendo de lectura.
Se prueba contra el servidor de verdad (`web/servir.py`) en un puerto libre y
sobre un workspace temporal, que es el nivel que pide §Verificación del contrato.

Qué vigila cada bloque, con el R* del contrato al lado:

- R1 — aprobar un contrato pendiente (unidad Y bug) escribe la fecha de hoy en
  su ficha y deja la línea de rastro en `.runtime/visor-contratos.log`.
- R1 — pedir cambios añade la sección al final del contrato, sin tocar el
  frontmatter; un comentario vacío es un 400 y no escribe nada.
- R3 — la frontera: cualquier otro POST es 405, y un nombre que no sea
  `NNN-slug` (empezando por `../`) ni siquiera llega al disco.
- (menú de Presentaciones) — `/presentaciones/indice.json` enumera TODAS las
  validaciones guiadas del workspace, cada una con si ya está decidida.

Lo que este fichero NO prueba, porque en la rama TODAVÍA NO EXISTE, está escrito
en `hallazgos.md`: la huella del contenido servido (R4), el 403 a un cliente no
local y el 405 con `--solo-lectura` (R6), y aprobar planos de flujos y el OK de
la validación guiada desde la web (R2).
"""

import http.client
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import threading
import time
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


servir = cargar("web_servir_para_aprobar", WEB / "servir.py")


CONTRATO_PENDIENTE = """---
unidad: %(nombre)s
tipo: feature
carril: normal
estado: planificada
aprobado: no             # LO PONE EL USUARIO
actividad: revisar-contratos
---

# %(nombre)s · una unidad que espera tu OK

## Qué

Lo que sea.
"""

CONTRATO_APROBADO = """---
unidad: 070-ya-aprobada
tipo: feature
carril: normal
estado: en_obra
aprobado: 2026-08-01
actividad: revisar-contratos
---

# 070 · ya aprobada
"""

BUG_PENDIENTE = """---
unidad: 099-un-bug-cualquiera
tipo: bug
carril: directo
estado: planificada
aprobado: no
actividad: revisar-contratos
---

# 099 · un bug que espera tu OK
"""

MANIFIESTO = {
    "version": 1,
    "presentaciones": [{
        "id": "validacion",
        "tipo": "validacion",
        "titulo": "cómo lo pruebas tú",
        "version": "1",
        "pasos": ["Abre la web."],
        "evidencia": ["Tests: OK"],
        "opciones": ["confirmado", "problema"],
        "comentario_obligatorio": ["problema"],
    }],
}

RECIBO = {"presentacion": "validacion", "eleccion": "confirmado"}


def workspace_sintetico():
    """Un meta-repo mínimo: dos unidades (una pendiente, otra aprobada), un bug
    pendiente y dos validaciones guiadas, una decidida y otra no."""
    raiz = Path(tempfile.mkdtemp(prefix="aprobar-web-"))
    trabajo = raiz / "docs" / "05-trabajo"
    for nombre, texto in (("091-aprobar-desde-la-web",
                           CONTRATO_PENDIENTE % {"nombre": "091-aprobar-desde-la-web"}),
                          ("070-ya-aprobada", CONTRATO_APROBADO)):
        (trabajo / nombre).mkdir(parents=True)
        (trabajo / nombre / "especificacion.md").write_text(texto, encoding="utf-8")
    bugs = raiz / "docs" / "bugs"
    bugs.mkdir(parents=True)
    (bugs / "099-un-bug-cualquiera.md").write_text(BUG_PENDIENTE, encoding="utf-8")
    # `INDICE.md` convive con las fichas y NO es un contrato: no debe colarse.
    (bugs / "INDICE.md").write_text("# Índice de bugs\n", encoding="utf-8")

    for unidad, decidida in (("091-aprobar-desde-la-web", False),
                             ("070-ya-aprobada", True)):
        carpeta = raiz / ".runtime" / "presentaciones" / unidad
        carpeta.mkdir(parents=True)
        (carpeta / "manifiesto.json").write_text(
            json.dumps(MANIFIESTO, ensure_ascii=False), encoding="utf-8")
        if decidida:
            recibos = carpeta / "recibos"
            recibos.mkdir()
            (recibos / "validacion.json").write_text(
                json.dumps(RECIBO, ensure_ascii=False), encoding="utf-8")
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

    def pedir(self, ruta, metodo="GET", datos=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
            cabeceras = {"Content-Type": "application/json"} if cuerpo else {}
            conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras)
            respuesta = conexion.getresponse()
            return respuesta.status, respuesta.read()
        finally:
            conexion.close()

    def json(self, ruta, metodo="GET", datos=None):
        codigo, cuerpo = self.pedir(ruta, metodo, datos)
        return codigo, json.loads(cuerpo.decode("utf-8"))


class ConWorkspace(unittest.TestCase):
    def setUp(self):
        self.raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.web = ServidorDePrueba(self.raiz)
        self.addCleanup(self.web.parar)
        self.hoy = time.strftime("%Y-%m-%d")

    # rutas de las tres fichas del workspace sintético
    def ficha_unidad(self, nombre="091-aprobar-desde-la-web"):
        return self.raiz / "docs" / "05-trabajo" / nombre / "especificacion.md"

    def ficha_bug(self, nombre="099-un-bug-cualquiera"):
        return self.raiz / "docs" / "bugs" / (nombre + ".md")

    def rastro(self):
        registro = self.raiz / ".runtime" / "visor-contratos.log"
        return registro.read_text(encoding="utf-8") if registro.is_file() else ""

    def campo_aprobado(self, ruta):
        hallado = re.search(r"^aprobado:\s*(\S+)", ruta.read_text(encoding="utf-8"),
                            re.M)
        return hallado.group(1) if hallado else None


# --------------------------------------------------------------------------- R1

class AprobarEscribeLaFechaTest(ConWorkspace):
    """R1 — el clic del usuario escribe la aprobación, y deja rastro de que fue él."""

    def test_aprobar_una_unidad_pendiente_le_pone_la_fecha_de_hoy(self):
        codigo, datos = self.web.json(
            "/contratos/aprobar/091-aprobar-desde-la-web", "POST")
        self.assertEqual(200, codigo)
        self.assertEqual(self.hoy, datos["aprobado"])
        self.assertEqual(self.hoy, self.campo_aprobado(self.ficha_unidad()))

    def test_la_ficha_aprobada_dice_que_la_aprobo_el_usuario_desde_la_web(self):
        """Es la mitad que cierra ADR-029: sin el «quién», la fecha vuelve a ser
        una firma tecleada que cualquiera pudo poner."""
        self.web.json("/contratos/aprobar/091-aprobar-desde-la-web", "POST")
        texto = self.ficha_unidad().read_text(encoding="utf-8")
        self.assertRegex(texto,
                         r"(?m)^aprobado: %s\s+#.*usuario \(web\)" % self.hoy)

    def test_aprobar_deja_su_linea_en_el_rastro_que_lee_despachar(self):
        self.web.json("/contratos/aprobar/091-aprobar-desde-la-web", "POST")
        self.assertIn("contrato aprobado desde la web: 091-aprobar-desde-la-web",
                      self.rastro())

    def test_un_bug_se_aprueba_igual_que_una_unidad(self):
        """`docs/bugs/NNN-slug.md` es el contrato entero del bug (ADR-006): el
        botón tiene que servir ahí también, o los bugs siguen firmándose a mano."""
        codigo, datos = self.web.json(
            "/contratos/aprobar/099-un-bug-cualquiera", "POST")
        self.assertEqual(200, codigo)
        self.assertEqual(self.hoy, datos["aprobado"])
        self.assertEqual(self.hoy, self.campo_aprobado(self.ficha_bug()))
        self.assertIn("contrato aprobado desde la web: 099-un-bug-cualquiera",
                      self.rastro())

    def test_la_lista_de_contratos_deja_de_darlo_por_pendiente(self):
        """El usuario tiene que VER el efecto: la lista que sondea la página
        (`/contratos/unidades.json`) es la que se lo enseña."""
        def pendiente(nombre):
            _, datos = self.web.json("/contratos/unidades.json")
            fila = [u for u in datos["unidades"] if u["carpeta"] == nombre][0]
            return fila["pendiente_de_aprobar"]

        self.assertTrue(pendiente("091-aprobar-desde-la-web"))
        self.web.json("/contratos/aprobar/091-aprobar-desde-la-web", "POST")
        self.assertFalse(pendiente("091-aprobar-desde-la-web"))

    def test_aprobar_no_toca_ninguna_otra_ficha(self):
        antes = self.ficha_bug().read_text(encoding="utf-8")
        self.web.json("/contratos/aprobar/091-aprobar-desde-la-web", "POST")
        self.assertEqual(antes, self.ficha_bug().read_text(encoding="utf-8"))

    def test_una_unidad_que_no_existe_es_un_404_y_no_crea_nada(self):
        codigo, _ = self.web.json("/contratos/aprobar/123-no-existe", "POST")
        self.assertEqual(404, codigo)
        self.assertFalse((self.raiz / "docs" / "05-trabajo" / "123-no-existe").exists())


class PedirCambiosTest(ConWorkspace):
    """R1 — la otra mitad del gesto: «esto no, cámbiame esto» sin pasar por el chat."""

    def test_lo_que_escribes_queda_al_final_del_contrato_con_su_fecha(self):
        codigo, datos = self.web.json(
            "/contratos/pedir-cambios/091-aprobar-desde-la-web", "POST",
            {"comentario": "Falta la huella del contenido servido."})
        self.assertEqual(200, codigo)
        texto = self.ficha_unidad().read_text(encoding="utf-8")
        self.assertIn("## Cambios pedidos desde la web", texto)
        self.assertIn("Falta la huella del contenido servido.", texto)
        self.assertIn(datos["anotado"], texto)

    def test_pedir_cambios_no_aprueba_de_rebote(self):
        self.web.json("/contratos/pedir-cambios/091-aprobar-desde-la-web", "POST",
                      {"comentario": "no todavía"})
        self.assertEqual("no", self.campo_aprobado(self.ficha_unidad()))

    def test_un_comentario_vacio_es_un_400_y_el_contrato_queda_intacto(self):
        antes = self.ficha_unidad().read_text(encoding="utf-8")
        for cuerpo in ({"comentario": ""}, {"comentario": "   "}, {}):
            with self.subTest(cuerpo=cuerpo):
                codigo, _ = self.web.json(
                    "/contratos/pedir-cambios/091-aprobar-desde-la-web", "POST", cuerpo)
                self.assertEqual(400, codigo)
        self.assertEqual(antes, self.ficha_unidad().read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- R3

class LaFronteraDeEscrituraTest(ConWorkspace):
    """R3 — dos escrituras, y ni una más: todo lo demás que llegue por POST es 405.

    Es el criterio que impide que «la web escribe» se convierta en «la web edita».
    """

    POSTS_QUE_NO_EXISTEN = (
        "/contratos/borrar/091-aprobar-desde-la-web",
        "/contratos/aprobar",
        "/contratos/unidades.json",
        "/contratos/contrato/091-aprobar-desde-la-web.md",
        "/contratos/aprobar/091-aprobar-desde-la-web/extra",
    )

    def test_cualquier_otro_post_sobre_contratos_es_405(self):
        for ruta in self.POSTS_QUE_NO_EXISTEN:
            with self.subTest(ruta=ruta):
                codigo, datos = self.web.json(ruta, "POST")
                self.assertEqual(405, codigo)
                self.assertIn("solo lectura", datos["error"])

    def test_solo_se_aprueba_lo_que_se_llama_NNN_slug(self):
        """El nombre de unidad es el ÚNICO patrón aceptado: por eso una ruta no
        puede escaparse del workspace. Un nombre raro se para en el enrutado,
        antes de tocar el disco."""
        for nombre in ("../../etc/passwd", "..", "ESTADO.md", "91-corto",
                       "091_guion_bajo", "091-MAYUS", ""):
            with self.subTest(nombre=nombre):
                codigo, _ = self.web.pedir("/contratos/aprobar/" + nombre, "POST")
                self.assertEqual(405, codigo)

    def test_ni_un_get_aprueba_nada(self):
        """Aprobar es un gesto, no una URL que se pueda visitar (ni precargar)."""
        codigo, _ = self.web.pedir("/contratos/aprobar/091-aprobar-desde-la-web")
        self.assertEqual(404, codigo)
        self.assertEqual("no", self.campo_aprobado(self.ficha_unidad()))

    def test_los_otros_tres_apartados_siguen_sin_escribir_nada(self):
        for ruta in ("/tablero/estado.json", "/flujos/datos.json",
                     "/presentaciones/indice.json"):
            with self.subTest(ruta=ruta):
                codigo, _ = self.web.pedir(ruta, "POST")
                self.assertIn(codigo, (404, 405),
                              "%s aceptó un POST" % ruta)


# ------------------------------------------------- el menú de Presentaciones

class IndiceDeValidacionesTest(ConWorkspace):
    """El menú de Presentaciones enseña TODAS las entregas del workspace, no sólo
    la última que montó `unidad.py validar`: sin esto, una validación anterior
    sin decidir desaparece de la vista y nadie vuelve a ella."""

    def indice(self):
        codigo, datos = self.web.json("/presentaciones/indice.json")
        self.assertEqual(200, codigo)
        return datos["presentaciones"]

    def test_estan_todas_las_validaciones_montadas(self):
        self.assertEqual({"091-aprobar-desde-la-web", "070-ya-aprobada"},
                         {p["unidad"] for p in self.indice()})

    def test_cada_una_dice_si_ya_esta_decidida(self):
        decididas = {p["unidad"]: p["decidida"] for p in self.indice()}
        self.assertTrue(decididas["070-ya-aprobada"], "tiene recibo y sale sin decidir")
        self.assertFalse(decididas["091-aprobar-desde-la-web"],
                         "sin recibo y ya sale decidida")

    def test_la_mas_reciente_va_primera(self):
        """El orden no es cosmético: la de arriba es la que se viene a mirar."""
        carpeta = (self.raiz / ".runtime" / "presentaciones"
                   / "091-aprobar-desde-la-web" / "manifiesto.json")
        futuro = int(time.time()) + 120
        import os
        os.utime(carpeta, (futuro, futuro))
        self.assertEqual("091-aprobar-desde-la-web", self.indice()[0]["unidad"])

    def test_una_carpeta_sin_manifiesto_no_es_una_entrega(self):
        (self.raiz / ".runtime" / "presentaciones" / "restos").mkdir()
        self.assertEqual(2, len(self.indice()))


# --------------------------------------------- el botón, donde el usuario mira

class ElBotonEstaDondeSeMiraTest(unittest.TestCase):
    """El gesto tiene que estar en las DOS pantallas donde el usuario se entera de
    que le toca: la ficha del contrato y «Te toca a ti» del tablero."""

    def test_la_ficha_del_contrato_ofrece_aprobar_y_pedir_cambios(self):
        texto = (RAIZ / "visor_contratos" / "plantilla.html").read_text(encoding="utf-8")
        self.assertIn('data-accion="aprobar"', texto)
        self.assertIn('"/aprobar/"', texto)
        self.assertIn('"/pedir-cambios/"', texto)

    def test_el_tablero_aprueba_contra_el_apartado_de_contratos(self):
        texto = (RAIZ / "visor_tablero" / "plantilla.html").read_text(encoding="utf-8")
        self.assertIn("data-aprobar", texto)
        self.assertIn('WEBS.contratos + "/aprobar/"', texto)

    def test_aprobar_pide_confirmacion_en_linea_y_no_un_confirm_del_navegador(self):
        """Un `confirm()` bloquea la página y no se puede probar; la confirmación
        en línea es la que el usuario aprobó el 26-08."""
        for plantilla in ("visor_contratos/plantilla.html",
                          "visor_tablero/plantilla.html"):
            texto = (RAIZ / plantilla).read_text(encoding="utf-8")
            with self.subTest(plantilla=plantilla):
                self.assertNotIn("confirm(", texto)
                self.assertIn("confirmar", texto)


if __name__ == "__main__":
    unittest.main()
