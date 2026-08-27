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

Unidad 107 (segunda mitad) añade abajo lo que la 091 dejó fuera, con el R* del
contrato de la 107 al lado:

- R1 — `aprobado_por: usuario (web)` como campo propio, rastro en
  `.runtime/aprobaciones/<unidad>-<fecha>.json` y 409 si la ficha ya estaba
  aprobada (sin tocar disco).
- R2 — `POST /api/aprobar-planos` produce los MISMOS ficheros que
  `requisitos aprobar` (`aprobacion.json` + `historial/`) porque llama a la
  misma función (`visor/revision.py: aprobar`), y `POST /api/validar-ok` deja el
  MISMO recibo que la validación guiada, que `unidad.py cerrar --ok-usuario`
  acepta.
- R3 — la huella del contenido servido: si difiere de la del disco, 409 «relee».
- R4 — solo `127.0.0.1` aprueba (403), y una `ref` fuera de `docs/` o un campo no
  previsto es 4xx sin tocar disco.
- R6 — con `--solo-lectura` no se pinta ningún botón y los tres endpoints de
  aprobación responden 405.
"""

import hashlib
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

def manifiesto_de(unidad):
    """El manifiesto tal y como lo escribe `unidad.py validar`: el id de la presentación
    ES el nombre de la unidad, que es por lo que `cerrar --ok-usuario` busca sus recibos."""
    return {
        "version": 1,
        "presentaciones": [{
            "id": unidad,
            "tipo": "validacion",
            "titulo": "%s · cómo lo pruebas tú" % unidad,
            "version": "1",
            "pasos": ["Abre la web."],
            "evidencia": ["Tests: OK"],
            "opciones": ["confirmado", "problema"],
            "comentario_obligatorio": ["problema"],
        }],
    }


RECIBO = {"presentacion": "070-ya-aprobada", "eleccion": "confirmado"}


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

    # Un mapa de flujos DE VERDAD: `visor/ejemplo.json` es el único que
    # `validar.py --perfil revision` da por válido, y aprobar planos pasa por ese
    # validador. Un mapa inventado a mano no llegaría ni a la primera puerta.
    planos = raiz / "docs" / "02-flujos" / "planos"
    planos.mkdir(parents=True)
    shutil.copy2(RAIZ / "visor" / "ejemplo.json", planos / "planos.json")

    for unidad, decidida in (("091-aprobar-desde-la-web", False),
                             ("070-ya-aprobada", True)):
        carpeta = raiz / ".runtime" / "presentaciones" / unidad
        carpeta.mkdir(parents=True)
        (carpeta / "manifiesto.json").write_text(
            json.dumps(manifiesto_de(unidad), ensure_ascii=False), encoding="utf-8")
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


# ===========================================================================
# Unidad 107 · lo que la 091 dejó fuera
# ===========================================================================


def unidad_py():
    """El `unidad.py` del método, importado de verdad: la 107 promete que el
    recibo que escribe la web es el que `cerrar --ok-usuario` acepta, y eso solo
    lo prueba el código que lo lee, no una copia de su formato."""
    scripts = (RAIZ / "plantilla" / "docs" / "00-metodo" / "scripts").resolve()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    return cargar("unidad_para_aprobar_web", scripts / "unidad.py")


class AprobarUnContratoConHuellaTest(ConWorkspace):
    """R1 y R3 — el gesto de la 091, ahora con el «quién» como campo propio, su
    rastro en `.runtime/aprobaciones/` y las dos puertas que faltaban: no se
    aprueba dos veces, y no se aprueba lo que no se leyó."""

    def rastro_aprobacion(self, nombre="091-aprobar-desde-la-web"):
        carpeta = self.raiz / ".runtime" / "aprobaciones"
        if not carpeta.is_dir():
            return None
        ficheros = sorted(carpeta.glob(nombre + "-*.json"))
        if not ficheros:
            return None
        return json.loads(ficheros[-1].read_text(encoding="utf-8"))

    def huella_de(self, ruta):
        return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()

    def test_la_ficha_gana_el_campo_aprobado_por_no_solo_un_comentario(self):
        """Un comentario YAML no es un dato: `aprobado_por:` es lo que cualquier
        lector del frontmatter (script o persona) puede leer sin adivinar."""
        codigo, _ = self.web.json("/contratos/aprobar/091-aprobar-desde-la-web", "POST")
        self.assertEqual(200, codigo)
        texto = self.ficha_unidad().read_text(encoding="utf-8")
        self.assertRegex(texto, r"(?m)^aprobado_por: usuario \(web\)\s*$")

    def test_deja_el_rastro_completo_en_runtime_aprobaciones(self):
        """R1: ruta, huella, hora y cliente. Sin esos cuatro, el rastro no
        acredita QUÉ se aprobó ni QUIÉN estaba delante."""
        self.web.json("/contratos/aprobar/091-aprobar-desde-la-web", "POST")
        rastro = self.rastro_aprobacion()
        self.assertIsNotNone(rastro, "no hay .runtime/aprobaciones/<unidad>-<fecha>.json")
        for campo in ("ruta", "huella", "hora", "cliente"):
            self.assertIn(campo, rastro)
        self.assertEqual("127.0.0.1", rastro["cliente"])
        self.assertIn("091-aprobar-desde-la-web", rastro["ruta"])

    def test_una_ficha_ya_aprobada_es_409_y_no_toca_disco(self):
        """R1: aprobar es un gesto sobre lo PENDIENTE. Repetirlo no puede
        reescribir una fecha que ya está firmada."""
        antes = self.ficha_unidad("070-ya-aprobada").read_text(encoding="utf-8")
        codigo, datos = self.web.json("/contratos/aprobar/070-ya-aprobada", "POST")
        self.assertEqual(409, codigo)
        self.assertIn("ya", datos["error"].lower())
        self.assertEqual(antes,
                         self.ficha_unidad("070-ya-aprobada").read_text(encoding="utf-8"))

    def test_con_la_huella_de_lo_que_se_sirvio_aprueba(self):
        codigo, datos = self.web.json("/api/huella?tipo=contrato&"
                                      "ref=091-aprobar-desde-la-web")
        self.assertEqual(200, codigo)
        self.assertEqual(self.huella_de(self.ficha_unidad()), datos["huella"])
        codigo, _ = self.web.json("/contratos/aprobar/091-aprobar-desde-la-web",
                                  "POST", {"huella": datos["huella"]})
        self.assertEqual(200, codigo)
        self.assertEqual(self.hoy, self.campo_aprobado(self.ficha_unidad()))

    def test_si_el_contrato_cambio_desde_que_se_mostro_manda_releer(self):
        """R3 — el caso de la pestaña vieja: aprobar un texto que ya no es el que
        se leyó es exactamente firmar a ciegas."""
        huella_vieja = self.huella_de(self.ficha_unidad())
        with open(self.ficha_unidad(), "a", encoding="utf-8") as ficha:
            ficha.write("\nUna línea que nadie ha leído.\n")
        codigo, datos = self.web.json("/contratos/aprobar/091-aprobar-desde-la-web",
                                      "POST", {"huella": huella_vieja})
        self.assertEqual(409, codigo)
        self.assertIn("relee", datos["error"].lower())
        self.assertEqual("no", self.campo_aprobado(self.ficha_unidad()))


class AprobarPlanosDesdeLaWebTest(ConWorkspace):
    """R2 (criterio PORTANTE) — el apartado Flujos aprueba llamando a la MISMA
    función que `requisitos aprobar` (`visor/revision.py: aprobar`), así que deja
    exactamente los mismos ficheros: `aprobacion.json`, el `historial/` y el
    `definicion.estado: aprobado` de cada plano. Si la web tuviera su propio
    escritor, alguno de los tres no aparecería."""

    def planos(self):
        return self.raiz / "docs" / "02-flujos" / "planos" / "planos.json"

    def mirar_los_planos(self):
        """El rastro que `revision.exigir_visor_visto` reclama lo deja la propia
        web al servir /flujos: aprobar sin haber mirado tiene que seguir sin poder."""
        codigo, _ = self.web.pedir("/flujos")
        self.assertEqual(200, codigo)

    def test_aprobar_planos_deja_los_mismos_ficheros_que_el_comando(self):
        self.mirar_los_planos()
        codigo, datos = self.web.json("/api/aprobar-planos", "POST", {})
        self.assertEqual(200, codigo, datos)
        aprobacion = self.planos().parent / "aprobacion.json"
        self.assertTrue(aprobacion.is_file(), "no hay aprobacion.json")
        recibo = json.loads(aprobacion.read_text(encoding="utf-8"))
        self.assertEqual("aprobado", recibo["estado"])
        self.assertEqual("usuario (web)", recibo["por"])
        historial = list((self.planos().parent / "historial").glob("*.json"))
        self.assertEqual(1, len(historial), "el historial no recibió el snapshot")
        mapa = json.loads(self.planos().read_text(encoding="utf-8"))
        self.assertEqual("aprobado", mapa["definicion"]["estado"])

    def test_sin_haber_mirado_los_planos_no_se_aprueban(self):
        """La puerta de la unidad 033 sigue en pie: se aprueba desde la web, pero
        la web no la salta. Es la prueba de que se pasa por `revision.aprobar`."""
        codigo, datos = self.web.json("/api/aprobar-planos", "POST", {})
        self.assertEqual(400, codigo)
        self.assertIn("visor", datos["error"])
        self.assertFalse((self.planos().parent / "aprobacion.json").exists())

    def test_una_huella_distinta_de_los_planos_manda_releer(self):
        self.mirar_los_planos()
        codigo, datos = self.web.json("/api/aprobar-planos", "POST",
                                      {"huella": "0" * 64})
        self.assertEqual(409, codigo)
        self.assertIn("relee", datos["error"].lower())
        self.assertFalse((self.planos().parent / "aprobacion.json").exists())

    def test_la_huella_de_los_planos_servidos_deja_aprobar(self):
        self.mirar_los_planos()
        codigo, datos = self.web.json("/api/huella?tipo=planos")
        self.assertEqual(200, codigo)
        codigo, datos = self.web.json("/api/aprobar-planos", "POST",
                                      {"huella": datos["huella"]})
        self.assertEqual(200, codigo, datos)


class ElOkDeLaValidacionDesdeLaWebTest(ConWorkspace):
    """R2 (segunda mitad) — el OK final de una validación guiada escribe el MISMO
    recibo que ya escribía el apartado Presentaciones, y la prueba de que es el
    mismo no es su forma: es que `unidad.py` lo lee y `cerrar --ok-usuario` lo da
    por bueno."""

    UNIDAD = "091-aprobar-desde-la-web"

    def decision(self, **cambios):
        cuerpo = {"unidad": self.UNIDAD, "presentacion": self.UNIDAD,
                  "version": "1", "contenido_revisado": "Abre la web.",
                  "eleccion": "confirmado", "comentario": "", "confirmado": True}
        cuerpo.update(cambios)
        return cuerpo

    def recibos(self):
        carpeta = (self.raiz / ".runtime" / "presentaciones" / self.UNIDAD / "recibos")
        return sorted(carpeta.glob("*.json")) if carpeta.is_dir() else []

    def test_el_ok_deja_el_recibo_en_la_carpeta_de_la_unidad(self):
        codigo, datos = self.web.json("/api/validar-ok", "POST", self.decision())
        self.assertEqual(201, codigo, datos)
        self.assertEqual(1, len(self.recibos()))
        recibo = json.loads(self.recibos()[0].read_text(encoding="utf-8"))
        self.assertEqual("confirmado", recibo["eleccion"])
        self.assertEqual(self.UNIDAD, recibo["presentacion"])

    def test_cerrar_ok_usuario_acepta_ese_recibo(self):
        """La promesa entera de R2 en una línea: lo que escribe el botón es lo que
        lee la puerta del cierre."""
        self.web.json("/api/validar-ok", "POST", self.decision())
        unidad = unidad_py()
        unidad.RAIZ = self.raiz
        (self.raiz / "main" / "web").mkdir(parents=True, exist_ok=True)
        for nombre in ("abrir.py", "servir.py"):
            (self.raiz / "main" / "web" / nombre).write_text("", encoding="utf-8")
        problema, nota, _ = unidad.puerta_recibo_validacion(self.UNIDAD, self.hoy)
        self.assertIsNone(problema, problema)
        self.assertIn("confirmado por el usuario", nota or "")

    def test_una_decision_que_no_casa_con_el_manifiesto_es_400_y_no_deja_recibo(self):
        codigo, _ = self.web.json("/api/validar-ok", "POST",
                                  self.decision(contenido_revisado="otra cosa"))
        self.assertEqual(400, codigo)
        self.assertEqual([], self.recibos())

    def test_una_unidad_sin_validacion_guiada_es_404(self):
        codigo, _ = self.web.json("/api/validar-ok", "POST",
                                  self.decision(unidad="123-no-montada"))
        self.assertEqual(404, codigo)


class LaFronteraDeLaAprobacionTest(ConWorkspace):
    """R4 — quién puede aprobar y qué se le acepta. Las tres escrituras nuevas
    son locales, con campos cerrados y sin rutas que salgan de `docs/`."""

    def test_un_cliente_que_no_es_local_recibe_403(self):
        """El bind a 127.0.0.1 es la primera barrera, pero no es la comprobación:
        si mañana alguien sirve en 0.0.0.0, esto es lo que sigue diciendo que no."""
        original = servir.cliente_local
        servir.cliente_local = lambda direccion: False
        self.addCleanup(setattr, servir, "cliente_local", original)
        for ruta in ("/contratos/aprobar/091-aprobar-desde-la-web",
                     "/api/aprobar-planos", "/api/validar-ok"):
            with self.subTest(ruta=ruta):
                codigo, _ = self.web.json(ruta, "POST", {})
                self.assertEqual(403, codigo)
        self.assertEqual("no", self.campo_aprobado(self.ficha_unidad()))

    def test_un_campo_no_previsto_es_400_y_no_escribe(self):
        codigo, _ = self.web.json("/api/aprobar-planos", "POST",
                                  {"huella": "0" * 64, "estado": "aprobado"})
        self.assertEqual(400, codigo)
        codigo, _ = self.web.json("/contratos/aprobar/091-aprobar-desde-la-web",
                                  "POST", {"aprobado": "2030-01-01"})
        self.assertEqual(400, codigo)
        self.assertEqual("no", self.campo_aprobado(self.ficha_unidad()))

    def test_una_ref_fuera_de_docs_es_400(self):
        for ref in ("../../etc/passwd", "/etc/passwd", "~/planos.json"):
            with self.subTest(ref=ref):
                codigo, _ = self.web.json("/api/huella?tipo=contrato&ref=" + ref)
                self.assertIn(codigo, (400, 404))


class SoloLecturaTest(unittest.TestCase):
    """R6 (límite) — la web sigue pudiendo levantarse SIN manos: ni botón que
    pulsar ni endpoint que responda."""

    def setUp(self):
        self.raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.servidor = servir.ServidorWeb(
            ("127.0.0.1", 0),
            servir.hacer_handler(str(self.raiz), solo_lectura=True))
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()
        self.addCleanup(self.parar)
        self.web = _Cliente(self.servidor.server_address[1])

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def test_los_endpoints_de_aprobacion_responden_405(self):
        for ruta in ("/contratos/aprobar/091-aprobar-desde-la-web",
                     "/contratos/pedir-cambios/091-aprobar-desde-la-web",
                     "/api/aprobar-planos", "/api/validar-ok"):
            with self.subTest(ruta=ruta):
                codigo, _ = self.web.json(ruta, "POST", {})
                self.assertEqual(405, codigo)

    def test_nada_se_escribio(self):
        self.web.json("/contratos/aprobar/091-aprobar-desde-la-web", "POST", {})
        ficha = (self.raiz / "docs" / "05-trabajo" / "091-aprobar-desde-la-web"
                 / "especificacion.md").read_text(encoding="utf-8")
        self.assertIn("aprobado: no", ficha)

    def test_ninguna_pagina_pinta_un_boton_de_aprobar(self):
        for ruta in ("/", "/contratos", "/flujos", "/presentaciones"):
            with self.subTest(ruta=ruta):
                codigo, cuerpo = self.web.pedir(ruta)
                self.assertEqual(200, codigo)
                texto = cuerpo.decode("utf-8")
                self.assertIn("solo_lectura", texto)
                self.assertRegex(texto, r'"solo_lectura":\s*true')

    def test_la_web_se_puede_lanzar_en_solo_lectura(self):
        """El flag tiene que existir en el lanzador, no solo en el handler."""
        self.assertIn("--solo-lectura", (WEB / "servir.py").read_text(encoding="utf-8"))


class _Cliente:
    """El cliente HTTP de `ServidorDePrueba`, suelto: `SoloLecturaTest` monta su
    propio servidor (con el flag) y necesita el mismo hablante."""

    def __init__(self, puerto):
        self.puerto = puerto

    pedir = ServidorDePrueba.pedir
    json = ServidorDePrueba.json


class LosBotonesNuevosTest(ConWorkspace):
    """Los dos gestos que faltaban tienen que estar DONDE se miran: en Flujos y en
    Presentaciones. Los pinta la cáscara (`web/plantilla.html`), que es la que
    sabe si la web va en solo lectura."""

    def test_la_cascara_trae_los_dos_botones_nuevos(self):
        texto = (WEB / "plantilla.html").read_text(encoding="utf-8")
        self.assertIn("/api/aprobar-planos", texto)
        self.assertIn("/api/validar-ok", texto)
        self.assertIn("/api/huella", texto)

    def test_el_apartado_flujos_sirve_el_boton_de_aprobar_planos(self):
        codigo, cuerpo = self.web.pedir("/flujos")
        self.assertEqual(200, codigo)
        self.assertIn("/api/aprobar-planos", cuerpo.decode("utf-8"))

    def test_el_apartado_presentaciones_sirve_el_boton_del_ok(self):
        codigo, cuerpo = self.web.pedir("/presentaciones")
        self.assertEqual(200, codigo)
        self.assertIn("/api/validar-ok", cuerpo.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
