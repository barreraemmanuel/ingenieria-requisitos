"""162 · Aprobar desde la LAN con un enlace firmado de un uso.

Hasta aquí la web del método sólo escuchaba en `127.0.0.1` y `cliente_local`
rechazaba con 403 cualquier aprobación que no viniera de la propia máquina: quien
trabaja desde el móvil con el PC en casa no tenía forma de aprobar nada.

Esta unidad abre esa puerta y la abre CON llave:

    python3 web/abrir.py --workspace . --apartado contratos#162-x --lan

levanta la misma web en `0.0.0.0` y emite un **enlace firmado**: un token aleatorio
de 256 bits, ligado a UN contrato (o a UNA entrega), válido 15 minutos y un solo
uso. Sin `--lan` no cambia absolutamente nada.

Qué vigila cada bloque, con el R* del contrato al lado:

- R1 — el bind depende del flag; `emitir_enlace` deja el recibo del servidor con
  `lan: sí`, la caducidad, la huella y el token GUARDADO EN HASH (nunca en claro).
- R2 — un POST desde una IP no local se acepta sólo con el token vigente y con la
  huella que se calculó al emitirlo; el rastro dice `via: lan-enlace-firmado`.
  Sin token, caducado, ya usado, de otro contrato o con huella distinta → 403 con
  SALIDA.
- R3 — un GET desde la LAN sí lee; ninguna otra escritura de la web (planos,
  pedir cambios, decisiones del visor) se abre por la LAN aunque lleve token.
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


servir = cargar("web_servir_para_enlace", WEB / "servir.py")
abrir = cargar("web_abrir_para_enlace", WEB / "abrir.py")


UNIDAD = "162-aprobar-desde-la-lan-con-enlace-firmado"
OTRA = "070-ya-aprobada"

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


def manifiesto_de(unidad):
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


def workspace_sintetico():
    """Un meta-repo mínimo: dos contratos pendientes, sus dos validaciones guiadas
    y un mapa de flujos de verdad (el POST de planos tiene que llegar a su puerta)."""
    raiz = Path(tempfile.mkdtemp(prefix="enlace-lan-"))
    trabajo = raiz / "docs" / "05-trabajo"
    for nombre in (UNIDAD, OTRA):
        (trabajo / nombre).mkdir(parents=True)
        (trabajo / nombre / "especificacion.md").write_text(
            CONTRATO_PENDIENTE % {"nombre": nombre}, encoding="utf-8")
    planos = raiz / "docs" / "02-flujos" / "planos"
    planos.mkdir(parents=True)
    shutil.copy2(RAIZ / "visor" / "ejemplo.json", planos / "planos.json")
    for unidad in (UNIDAD, OTRA):
        carpeta = raiz / ".runtime" / "presentaciones" / unidad
        carpeta.mkdir(parents=True)
        (carpeta / "manifiesto.json").write_text(
            json.dumps(manifiesto_de(unidad), ensure_ascii=False), encoding="utf-8")
    return raiz


class ServidorDePrueba:
    """La web única, en un puerto libre, con la puerta de la LAN abierta o cerrada."""

    def __init__(self, workspace, lan=False):
        self.servidor = servir.ServidorWeb(
            ("127.0.0.1", 0), servir.hacer_handler(str(workspace), lan=lan))
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    @property
    def puerto(self):
        return self.servidor.server_address[1]

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def pedir(self, ruta, metodo="GET", datos=None, token=None, seguir=False):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
            cabeceras = {"Content-Type": "application/json"} if cuerpo else {}
            if token:
                cabeceras["Cookie"] = "%s=%s" % (servir.COOKIE_ENLACE, token)
            conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras)
            respuesta = conexion.getresponse()
            leido = respuesta.read()
            if seguir:
                return respuesta.status, dict(respuesta.getheaders())
            return respuesta.status, leido
        finally:
            conexion.close()

    def json(self, ruta, metodo="GET", datos=None, token=None):
        codigo, cuerpo = self.pedir(ruta, metodo, datos, token)
        return codigo, json.loads(cuerpo.decode("utf-8"))


class ConTaller(unittest.TestCase):
    """Un taller de mentira y la web encima, con el cliente SIEMPRE remoto: el bind
    sigue siendo local (los tests hablan por loopback) y lo que se simula es la
    respuesta de `cliente_local`, que es la regla de verdad."""

    LAN = True

    def setUp(self):
        self.raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.web = ServidorDePrueba(self.raiz, lan=self.LAN)
        self.addCleanup(self.web.parar)
        self.hoy = time.strftime("%Y-%m-%d")

    def desde_fuera(self):
        original = servir.cliente_local
        servir.cliente_local = lambda direccion: False
        self.addCleanup(setattr, servir, "cliente_local", original)

    def ficha(self, nombre=UNIDAD):
        return self.raiz / "docs" / "05-trabajo" / nombre / "especificacion.md"

    def manifiesto(self, nombre=UNIDAD):
        return self.raiz / ".runtime" / "presentaciones" / nombre / "manifiesto.json"

    def campo_aprobado(self, ruta):
        hallado = re.search(r"^aprobado:\s*(\S+)", ruta.read_text(encoding="utf-8"),
                            re.M)
        return hallado.group(1) if hallado else None

    def rastro_de(self, nombre=UNIDAD):
        """El rastro del clic. El OK de una entrega lo escribe DESPUÉS de contestar
        (lo escribía ya así), así que se espera un momento en vez de suponerlo."""
        fichero = (self.raiz / servir.CARPETA_APROBACIONES
                   / ("%s-%s.json" % (nombre, self.hoy)))
        for _ in range(50):
            if fichero.is_file():
                return json.loads(fichero.read_text(encoding="utf-8"))
            time.sleep(0.05)
        return None

    def emitir(self, tipo="contrato", ref=UNIDAD, minutos=servir.MINUTOS_ENLACE,
               huella=None):
        destino = self.ficha(ref) if tipo == "contrato" else self.manifiesto(ref)
        token, _recibo = servir.emitir_enlace(
            self.raiz, self.web.puerto, tipo, ref,
            huella if huella is not None else servir.huella_fichero(destino),
            minutos=minutos)
        return token

    def decision(self, unidad=UNIDAD, **cambios):
        cuerpo = {"unidad": unidad, "presentacion": unidad, "version": "1",
                  "contenido_revisado": "Abre la web.", "eleccion": "confirmado",
                  "comentario": "", "confirmado": True}
        cuerpo.update(cambios)
        return cuerpo


# --------------------------------------------------------------------------- R1

class SinLanTodoSigueIgualTest(ConTaller):
    """R1 (la otra mitad) — sin el flag, la web es la de siempre: bind local y un
    403 seco a cualquier POST de fuera, traiga lo que traiga."""

    LAN = False

    def test_el_bind_por_defecto_sigue_siendo_127_0_0_1(self):
        self.assertEqual("127.0.0.1", servir.direccion_de_bind(False))
        self.assertEqual("0.0.0.0", servir.direccion_de_bind(True))

    def test_meta_json_dice_que_esta_web_no_escucha_en_la_lan(self):
        _codigo, datos = self.web.json("/meta.json")
        self.assertIs(False, datos["lan"])

    def test_un_post_remoto_con_token_sigue_siendo_403(self):
        self.desde_fuera()
        token = self.emitir()
        codigo, datos = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST",
                                      {}, token=token)
        self.assertEqual(403, codigo)
        self.assertIn("127.0.0.1", datos["error"])
        self.assertEqual("no", self.campo_aprobado(self.ficha()))


class ElEnlaceQueSeEmiteTest(ConTaller):
    """R1 — qué es exactamente un enlace firmado y qué queda escrito de él."""

    def test_el_token_tiene_de_sobra_los_128_bits(self):
        token = self.emitir()
        self.assertGreaterEqual(len(token) * 6, 128)

    def test_el_recibo_del_servidor_dice_lan_si_con_su_caducidad_y_su_huella(self):
        token = self.emitir()
        recibos = list((self.raiz / servir.CARPETA_ENLACES).glob("*.enlace.json"))
        self.assertEqual(1, len(recibos))
        recibo = json.loads(recibos[0].read_text(encoding="utf-8"))
        self.assertEqual("sí", recibo["lan"])
        self.assertEqual("contrato", recibo["tipo"])
        self.assertEqual(UNIDAD, recibo["ref"])
        self.assertEqual(servir.huella_fichero(self.ficha()), recibo["huella"])
        self.assertEqual(self.web.puerto, recibo["puerto"])
        restante = float(recibo["caduca_en"]) - time.time()
        self.assertTrue(0 < restante <= servir.MINUTOS_ENLACE * 60, restante)
        self.assertIsNone(recibo["usado"])
        self.assertNotIn(token, recibos[0].read_text(encoding="utf-8"))

    def test_el_token_no_se_guarda_en_claro_en_ningun_sitio(self):
        token = self.emitir()
        for fichero in (self.raiz / ".runtime").rglob("*"):
            if fichero.is_file():
                with self.subTest(fichero=fichero.name):
                    self.assertNotIn(token, fichero.read_text(encoding="utf-8",
                                                              errors="replace"))

    def test_dos_enlaces_seguidos_no_son_el_mismo(self):
        self.assertNotEqual(self.emitir(), self.emitir())

    def test_un_tipo_que_no_existe_no_se_emite(self):
        with self.assertRaises(ValueError):
            servir.emitir_enlace(self.raiz, self.web.puerto, "planos", "x", "0" * 64)


# --------------------------------------------------------------------------- R2

class AprobarUnContratoDesdeLaLanTest(ConTaller):
    """R2 — la puerta: con el enlace vigente se aprueba desde el móvil, y queda
    escrito por dónde entró."""

    def setUp(self):
        super().setUp()
        self.desde_fuera()

    def test_con_el_enlace_vigente_el_contrato_queda_aprobado(self):
        token = self.emitir()
        codigo, datos = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST",
                                      {}, token=token)
        self.assertEqual(200, codigo, datos)
        self.assertEqual(self.hoy, self.campo_aprobado(self.ficha()))
        self.assertIn("aprobado_por: %s" % servir.QUIEN,
                      self.ficha().read_text(encoding="utf-8"))

    def test_el_rastro_dice_que_se_aprobo_por_la_lan(self):
        self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                      token=self.emitir())
        rastro = self.rastro_de()
        self.assertEqual(servir.VIA_LAN, rastro["via"])
        self.assertEqual(servir.QUIEN, rastro["aprobado_por"])

    def test_sin_enlace_no_se_aprueba_y_el_403_dice_como_salir(self):
        codigo, datos = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {})
        self.assertEqual(403, codigo)
        self.assertIn("SALIDA", datos["error"])
        self.assertEqual("no", self.campo_aprobado(self.ficha()))

    def test_un_token_inventado_no_vale(self):
        codigo, datos = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                      token="a" * 43)
        self.assertEqual(403, codigo)
        self.assertIn("SALIDA", datos["error"])
        self.assertEqual("no", self.campo_aprobado(self.ficha()))

    def test_el_mismo_enlace_no_aprueba_dos_veces(self):
        token = self.emitir()
        primero, _ = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                   token=token)
        self.assertEqual(200, primero)
        # La ficha ya está aprobada, así que se prueba sobre la OTRA: lo que tiene
        # que rechazar es el enlace gastado, no el contrato ya firmado.
        segundo, datos = self.web.json("/contratos/aprobar/%s" % OTRA, "POST", {},
                                       token=token)
        self.assertEqual(403, segundo)
        self.assertIn("SALIDA", datos["error"])
        self.assertEqual("no", self.campo_aprobado(self.ficha(OTRA)))

    def test_un_enlace_caducado_no_vale(self):
        token = self.emitir(minutos=-1)
        codigo, datos = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                      token=token)
        self.assertEqual(403, codigo)
        self.assertIn("SALIDA", datos["error"])
        self.assertEqual("no", self.campo_aprobado(self.ficha()))

    def test_el_enlace_de_un_contrato_no_aprueba_otro(self):
        token = self.emitir(ref=OTRA)
        codigo, _ = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                  token=token)
        self.assertEqual(403, codigo)
        self.assertEqual("no", self.campo_aprobado(self.ficha()))

    def test_si_el_contrato_cambio_desde_que_se_emitio_el_enlace_no_vale(self):
        token = self.emitir()
        with self.ficha().open("a", encoding="utf-8") as ficha:
            ficha.write("\notra cosa\n")
        codigo, datos = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                      token=token)
        self.assertEqual(403, codigo)
        self.assertIn("SALIDA", datos["error"])
        self.assertEqual("no", self.campo_aprobado(self.ficha()))

    def test_un_enlace_emitido_para_otro_servidor_no_vale(self):
        token, _ = servir.emitir_enlace(self.raiz, self.web.puerto + 1, "contrato",
                                        UNIDAD, servir.huella_fichero(self.ficha()))
        codigo, _ = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                  token=token)
        self.assertEqual(403, codigo)
        self.assertEqual("no", self.campo_aprobado(self.ficha()))


class ConfirmarLaEntregaDesdeLaLanTest(ConTaller):
    """R2 (segunda mitad) — «o confirmar la entrega»: el OK de la validación
    guiada entra por la misma puerta y deja el MISMO recibo de siempre."""

    def setUp(self):
        super().setUp()
        self.desde_fuera()

    def recibos(self, unidad=UNIDAD):
        carpeta = self.raiz / ".runtime" / "presentaciones" / unidad / "recibos"
        return sorted(carpeta.glob("*.json")) if carpeta.is_dir() else []

    def test_con_el_enlace_de_la_entrega_el_ok_queda_escrito(self):
        token = self.emitir(tipo="validacion")
        codigo, datos = self.web.json(servir.API_VALIDAR_OK, "POST",
                                      self.decision(), token=token)
        self.assertEqual(201, codigo, datos)
        self.assertEqual(1, len(self.recibos()))
        self.assertEqual(servir.VIA_LAN, self.rastro_de()["via"])

    def test_sin_enlace_la_entrega_no_se_confirma(self):
        codigo, datos = self.web.json(servir.API_VALIDAR_OK, "POST", self.decision())
        self.assertEqual(403, codigo)
        self.assertIn("SALIDA", datos["error"])
        self.assertEqual([], self.recibos())

    def test_el_enlace_de_un_contrato_no_confirma_una_entrega(self):
        codigo, _ = self.web.json(servir.API_VALIDAR_OK, "POST", self.decision(),
                                  token=self.emitir(tipo="contrato"))
        self.assertEqual(403, codigo)
        self.assertEqual([], self.recibos())

    def test_el_enlace_de_otra_entrega_no_confirma_esta(self):
        token = self.emitir(tipo="validacion", ref=OTRA)
        codigo, _ = self.web.json(servir.API_VALIDAR_OK, "POST", self.decision(),
                                  token=token)
        self.assertEqual(403, codigo)
        self.assertEqual([], self.recibos())


# --------------------------------------------------------------------------- R3

class LaLanLeePeroNoEscribeLoDemasTest(ConTaller):
    """R3 — el caso límite: desde la red se LEE sin token, y con token no se abre
    ni una escritura más que las dos de R2."""

    def setUp(self):
        super().setUp()
        self.desde_fuera()

    def test_un_get_desde_la_lan_sin_token_lee_el_contrato(self):
        for ruta in ("/", "/contratos", "/presentaciones", "/plan"):
            with self.subTest(ruta=ruta):
                codigo, _ = self.web.pedir(ruta)
                self.assertEqual(200, codigo)

    def test_ninguna_otra_escritura_se_abre_aunque_lleve_token(self):
        rutas = (servir.API_APROBAR_PLANOS,
                 "/contratos/pedir-cambios/%s" % UNIDAD,
                 "/presentaciones/%s/decisiones" % UNIDAD)
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                codigo, datos = self.web.json(ruta, "POST", {}, token=self.emitir())
                self.assertEqual(403, codigo)
                self.assertIn("SALIDA", datos["error"])
        self.assertFalse((self.raiz / "docs" / "02-flujos" / "planos"
                          / "aprobacion.json").exists())
        self.assertNotIn("otra cosa", self.ficha().read_text(encoding="utf-8"))

    def test_el_enlace_no_se_gasta_al_rechazar_otra_escritura(self):
        """Quemar el enlace por un POST que ni siquiera se admite dejaría al usuario
        sin llave por algo que no era suyo."""
        token = self.emitir()
        self.web.json(servir.API_APROBAR_PLANOS, "POST", {}, token=token)
        codigo, _ = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                  token=token)
        self.assertEqual(200, codigo)

    def test_un_put_o_un_delete_pasan_por_la_misma_puerta_que_el_post(self):
        """`do_PUT` y `do_DELETE` son alias de `do_POST`: la puerta de la LAN no se
        rodea cambiando el verbo."""
        for metodo in ("PUT", "DELETE"):
            with self.subTest(metodo=metodo):
                codigo, datos = self.web.json("/contratos/aprobar/%s" % UNIDAD,
                                              metodo, {})
                self.assertEqual(403, codigo)
                self.assertIn("SALIDA", datos["error"])
                codigo, _ = self.web.json(servir.API_APROBAR_PLANOS, metodo, {},
                                          token=self.emitir())
                self.assertEqual(403, codigo)
        self.assertEqual("no", self.campo_aprobado(self.ficha()))

    def test_el_enlace_en_la_url_se_convierte_en_cookie_y_desaparece(self):
        token = self.emitir()
        codigo, cabeceras = self.web.pedir(
            "/contratos?%s=%s" % (servir.PARAM_ENLACE, token), seguir=True)
        self.assertIn(codigo, (302, 303))
        self.assertEqual("/contratos", cabeceras["Location"])
        galleta = cabeceras["Set-Cookie"]
        self.assertIn("%s=%s" % (servir.COOKIE_ENLACE, token), galleta)
        self.assertIn("HttpOnly", galleta)
        self.assertIn("SameSite=Strict", galleta)

    def test_un_token_invalido_en_la_url_no_deja_cookie(self):
        codigo, cabeceras = self.web.pedir(
            "/contratos?%s=%s" % (servir.PARAM_ENLACE, "c" * 43), seguir=True)
        self.assertIn(codigo, (302, 303))
        self.assertNotIn("Set-Cookie", cabeceras)


class SoloLecturaGanaALaLanTest(unittest.TestCase):
    """R3 (frontera) — `--solo-lectura` es una web sin manos: el enlace firmado no
    se las devuelve."""

    def setUp(self):
        self.raiz = workspace_sintetico()
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.servidor = servir.ServidorWeb(
            ("127.0.0.1", 0),
            servir.hacer_handler(str(self.raiz), solo_lectura=True, lan=True))
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()
        self.addCleanup(self.parar)
        self.web = ServidorDePrueba.__new__(ServidorDePrueba)
        self.web.servidor = self.servidor

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def test_con_solo_lectura_ni_con_token_se_aprueba(self):
        original = servir.cliente_local
        servir.cliente_local = lambda direccion: False
        self.addCleanup(setattr, servir, "cliente_local", original)
        token, _ = servir.emitir_enlace(
            self.raiz, self.web.puerto, "contrato", UNIDAD,
            servir.huella_fichero(self.raiz / "docs" / "05-trabajo" / UNIDAD
                                  / "especificacion.md"))
        codigo, _ = self.web.json("/contratos/aprobar/%s" % UNIDAD, "POST", {},
                                  token=token)
        self.assertEqual(405, codigo)


# ------------------------------------------------------- el lanzador (`abrir.py`)

class ElLanzadorTest(unittest.TestCase):
    """R1 desde fuera: `--lan` existe, sabe QUÉ se va a aprobar y arma la URL."""

    def test_el_flag_existe_y_por_defecto_esta_apagado(self):
        self.assertIn("--lan", (WEB / "abrir.py").read_text(encoding="utf-8"))
        self.assertIn("--lan", (WEB / "servir.py").read_text(encoding="utf-8"))

    def test_el_apartado_dice_que_se_va_a_aprobar(self):
        self.assertEqual(("contrato", UNIDAD),
                         abrir.enlace_pedido("contratos#" + UNIDAD))
        self.assertEqual(("validacion", UNIDAD),
                         abrir.enlace_pedido("presentaciones/" + UNIDAD))

    def test_un_lan_sin_saber_que_se_aprueba_se_rechaza_diciendo_como(self):
        for apartado in ("contratos", "tablero", "flujos", "plan", None):
            with self.subTest(apartado=apartado):
                with self.assertRaises(ValueError) as fallo:
                    abrir.enlace_pedido(apartado)
                self.assertIn("SALIDA", str(fallo.exception))

    def test_la_url_de_la_lan_lleva_la_ip_el_token_y_el_ancla(self):
        url = abrir.url_de(8790, "contratos#" + UNIDAD, host="192.168.1.40",
                           token="TOKEN")
        self.assertEqual("http://192.168.1.40:8790/contratos?enlace=TOKEN#" + UNIDAD,
                         url)

    def test_la_url_de_siempre_no_cambia(self):
        self.assertEqual("http://127.0.0.1:8790/contratos#" + UNIDAD,
                         abrir.url_de(8790, "contratos#" + UNIDAD))

    def test_la_ip_de_la_lan_no_es_la_de_loopback(self):
        ip = servir.ip_de_la_lan()
        if ip is not None:
            self.assertFalse(ip.startswith("127."), ip)


if __name__ == "__main__":
    unittest.main()
