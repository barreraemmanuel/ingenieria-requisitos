"""Bug 153: al pulsar «Confirmar decisión» la página no devolvía ninguna señal —sin bandeja
no cambiaba nada visible y el botón seguía activo—, el usuario pulsó tres veces y quedaron
tres recibos idénticos. Tras el POST, con o sin bandeja: mensaje visible con la hora y
«puedes cerrar la pestaña», formulario deshabilitado, y el servidor rechaza con 409 un
segundo recibo idéntico para la misma presentación dentro de la misma sesión."""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from visor_presentaciones import servir  # noqa: E402
from visor_presentaciones.tests.test_visor_presentaciones import manifiesto_valido  # noqa: E402

PLANTILLA = RAIZ / "visor_presentaciones" / "plantilla.html"


class ServidorEnSesion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.datos = Path(self.tmp.name)
        (self.datos / "manifiesto.json").write_text(json.dumps(manifiesto_valido()), encoding="utf-8")
        self.estado = {"ultimo": 0}
        try:
            self.servidor = servir.ServidorPresentaciones(
                ("127.0.0.1", 0), servir.hacer_handler(self.datos, self.estado))
        except PermissionError:
            self.tmp.cleanup()
            raise unittest.SkipTest("sandbox sin sockets locales")
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=2)
        self.tmp.cleanup()

    def post(self, decision):
        conexion = http.client.HTTPConnection("127.0.0.1", self.servidor.server_port)
        conexion.request("POST", "/decisiones", body=json.dumps(decision),
                         headers={"Content-Type": "application/json"})
        respuesta = conexion.getresponse()
        cuerpo = respuesta.read()
        conexion.close()
        return respuesta.status, json.loads(cuerpo)

    def recibos(self):
        return sorted((self.datos / "recibos").glob("*.json"))


DECISION = {
    "presentacion": "propuesta-uno", "version": "3",
    "contenido_revisado": "Construir cuatro superficies locales con una plantilla fija.",
    "eleccion": "aprobar", "comentario": "Adelante", "confirmado": True,
}


class SegundoClicNoDuplicaElReciboTest(ServidorEnSesion):

    def test_el_mismo_recibo_dos_veces_en_la_misma_sesion_es_409_y_no_escribe(self):
        estado, primero = self.post(DECISION)
        self.assertEqual(estado, 201, primero)
        estado, segundo = self.post(DECISION)
        self.assertEqual(estado, 409, segundo)
        self.assertIn("ya", segundo["error"].lower())
        self.assertEqual(segundo["recibo"]["id"], primero["recibo"]["id"])
        self.assertEqual(len(self.recibos()), 1)

    def test_tres_clics_en_quince_segundos_dejan_un_solo_recibo(self):
        """El caso de campo: tres pulsaciones, tres recibos idénticos. Ahora uno."""
        estados = [self.post(DECISION)[0] for _ in range(3)]
        self.assertEqual(estados, [201, 409, 409])
        self.assertEqual(len(self.recibos()), 1)

    def test_una_decision_distinta_sobre_la_misma_presentacion_si_se_guarda(self):
        self.post(DECISION)
        cambiada = dict(DECISION, comentario="Adelante, pero con el foco arreglado")
        estado, _ = self.post(cambiada)
        self.assertEqual(estado, 201)
        otra_eleccion = dict(DECISION, eleccion="pedir_cambios")
        estado, _ = self.post(otra_eleccion)
        self.assertEqual(estado, 201)
        self.assertEqual(len(self.recibos()), 3)

    def test_el_mismo_recibo_en_otra_sesion_del_servidor_se_acepta(self):
        """El candado es de la sesión, no del disco: otra sesión no lo hereda."""
        self.post(DECISION)
        otro_estado = {"ultimo": 0}
        otro = servir.ServidorPresentaciones(("127.0.0.1", 0), servir.hacer_handler(self.datos, otro_estado))
        hilo = threading.Thread(target=otro.serve_forever, daemon=True)
        hilo.start()
        try:
            conexion = http.client.HTTPConnection("127.0.0.1", otro.server_port)
            conexion.request("POST", "/decisiones", body=json.dumps(DECISION),
                             headers={"Content-Type": "application/json"})
            self.assertEqual(conexion.getresponse().status, 201)
            conexion.close()
        finally:
            otro.shutdown()
            otro.server_close()
            hilo.join(timeout=2)


class LaPaginaDaSenalTest(unittest.TestCase):

    def setUp(self):
        self.html = PLANTILLA.read_text(encoding="utf-8")

    def test_tras_guardar_dice_la_hora_y_que_puede_cerrar_la_pestana(self):
        self.assertIn("Guardado a las", self.html)
        self.assertIn("puedes cerrar la pestaña", self.html)
        self.assertIn("Problema registrado a las", self.html)

    def test_tras_guardar_o_rechazar_el_formulario_queda_deshabilitado(self):
        # Una sola función que apaga radios, comentario y botón; se llama al guardar y
        # también cuando el servidor contesta 409 (ya estaba guardado).
        self.assertIn("function bloquearDecision", self.html)
        self.assertIn(".disabled = true", self.html)
        self.assertRegex(self.html, r"409[\s\S]{0,400}bloquearDecision")

    def test_no_se_envia_dos_veces_mientras_el_primero_esta_en_vuelo(self):
        self.assertIn("enviando", self.html)


if __name__ == "__main__":
    unittest.main()
