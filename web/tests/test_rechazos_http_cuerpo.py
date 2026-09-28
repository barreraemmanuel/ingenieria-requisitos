"""151: los rechazos tempranos consumen solo el cuerpo HTTP declarado."""

import http.client
import json
import shutil
import socket
import threading
import time
import unittest
from unittest import mock

from web.tests import test_aprobar_desde_la_web as apoyo


RUTA = "/contratos/aprobar/091-aprobar-desde-la-web"


class LectorContado:
    def __init__(self, original):
        self.original = original
        self.leidos = 0
        self.llamadas = 0

    def read1(self, cantidad):
        self.llamadas += 1
        datos = self.original.read1(cantidad)
        self.leidos += len(datos)
        return datos

    def __getattr__(self, nombre):
        return getattr(self.original, nombre)


class RechazosHTTPTest(unittest.TestCase):
    def setUp(self):
        self.workspace = apoyo.workspace_sintetico()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.ficha = (self.workspace / "docs/05-trabajo/091-aprobar-desde-la-web/"
                      "especificacion.md")
        self.antes = self.ficha.read_bytes()
        self.servidores = []
        self.addCleanup(self._cerrar_servidores)

    def _cerrar_servidores(self):
        for servidor, hilo, handler in self.servidores:
            servidor.shutdown()
            servidor.server_close()
            hilo.join(timeout=3)
            self.assertFalse(hilo.is_alive(), "hilo de serve_forever pendiente")
            hasta = time.monotonic() + 1
            while handler.activos and time.monotonic() < hasta:
                time.sleep(0.005)
            self.assertEqual(0, handler.activos, "hilo HTTP pendiente")
        self.assertEqual(self.antes, self.ficha.read_bytes())
        self.assertFalse((self.workspace / ".runtime/visor-contratos.log").exists())
        self.assertFalse((self.workspace / ".runtime/aprobaciones").exists())

    def _servidor(self, *, solo_lectura=False, remoto=False,
                  timeout_inicial=None):
        eventos = []
        listo = threading.Event()
        base = apoyo.servir.hacer_handler(str(self.workspace),
                                           solo_lectura=solo_lectura)

        class Handler(base):
            activos = 0
            activos_lock = threading.Lock()

            def setup(self):
                super().setup()
                with type(self).activos_lock:
                    type(self).activos += 1
                self.rfile = LectorContado(self.rfile)
                if timeout_inicial is not None:
                    self.connection.settimeout(timeout_inicial)

            def send_response(self, code, message=None):
                self.codigo_emitido = code
                return super().send_response(code, message)

            def finish(self):
                try:
                    if hasattr(self, "codigo_emitido"):
                        evento = {"codigo": self.codigo_emitido,
                                  "leidos": self.rfile.leidos,
                                  "llamadas": self.rfile.llamadas,
                                  "timeout": self.connection.gettimeout()}
                        # Inspección posterior al handler y anterior al cierre.
                        if getattr(self, "medir_pendiente", False):
                            previo = self.connection.gettimeout()
                            try:
                                self.connection.settimeout(0.05)
                                evento["pendiente"] = self.rfile.read1(1)
                            except (OSError, ValueError):
                                evento["pendiente"] = b""
                            finally:
                                self.connection.settimeout(previo)
                        eventos.append(evento)
                        listo.set()
                    return super().finish()
                finally:
                    with type(self).activos_lock:
                        type(self).activos -= 1

        Handler.medir_pendiente = False
        if remoto:
            parche = mock.patch.object(apoyo.servir, "cliente_local",
                                       return_value=False)
            parche.start()
            self.addCleanup(parche.stop)
        servidor = apoyo.servir.ServidorWeb(("127.0.0.1", 0), Handler)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        self.servidores.append((servidor, hilo, Handler))
        return servidor.server_address[1], Handler, eventos, listo

    def _pedir(self, puerto, metodo="POST", cuerpo=b"{}"):
        conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=2)
        try:
            conexion.request(metodo, RUTA if metodo == "POST" else "/meta.json",
                             body=cuerpo)
            respuesta = conexion.getresponse()
            datos = respuesta.read()
            self.assertEqual(int(respuesta.getheader("Content-Length")), len(datos))
            return respuesta.status, json.loads(datos)
        finally:
            conexion.close()

    def _raw(self, puerto, cabeceras, cuerpo=b""):
        conexion = socket.create_connection(("127.0.0.1", puerto), timeout=2)
        conexion.settimeout(2)
        self.addCleanup(conexion.close)
        mensaje = (f"POST {RUTA} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                   + cabeceras + "\r\n\r\n").encode("ascii")
        conexion.sendall(mensaje + cuerpo)
        return conexion

    def _respuesta_raw(self, conexion):
        lector = conexion.makefile("rb")
        self.addCleanup(lector.close)
        linea = lector.readline()
        cabeceras = {}
        while linea and linea != b"\r\n":
            if b":" in linea:
                clave, valor = linea.split(b":", 1)
                cabeceras[clave.lower()] = valor.strip()
            linea = lector.readline()
        cuerpo = lector.read(int(cabeceras[b"content-length"]))
        self.assertEqual(len(cuerpo), int(cabeceras[b"content-length"]))
        return json.loads(cuerpo)

    def test_cuerpo_original_agotado_antes_del_cierre(self):
        for remoto, solo_lectura, codigo in ((False, True, 405),
                                              (True, False, 403)):
            with self.subTest(codigo=codigo):
                puerto, handler, eventos, listo = self._servidor(
                    remoto=remoto, solo_lectura=solo_lectura)
                handler.medir_pendiente = True
                estado, datos = self._pedir(puerto)
                self.assertEqual(codigo, estado)
                self.assertTrue(datos["error"])
                self.assertTrue(listo.wait(2))
                self.assertEqual(2, eventos[-1]["leidos"])
                self.assertEqual(b"", eventos[-1]["pendiente"])

    def test_limite_40000_y_cabeceras_ambiguas(self):
        for cabeceras in ("Content-Length: 40001", "Content-Length: -1",
                          "Content-Length: +2", "Content-Length: 2, 2",
                          "Content-Length: 2\r\nContent-Length: 2",
                          "Content-Length: xyz", "X-Test: sin-longitud",
                          "Content-Length: " + "9" * 5000,
                          "Content-Length: 2\r\nTransfer-Encoding:",
                          "Content-Length: 2\r\nTransfer-Encoding: chunked"):
            with self.subTest(cabeceras=cabeceras):
                puerto, _, eventos, listo = self._servidor(solo_lectura=True)
                conexion = self._raw(puerto, cabeceras, b"x")
                respuesta = self._respuesta_raw(conexion)
                self.assertTrue(respuesta["error"])
                self.assertTrue(listo.wait(2))
                self.assertEqual(405, eventos[-1]["codigo"])
                self.assertEqual(0, eventos[-1]["leidos"])
                self.assertEqual(0, eventos[-1]["llamadas"])
                self.assertEqual(200, self._pedir(puerto, "GET", None)[0])

        puerto, _, eventos, listo = self._servidor(solo_lectura=True)
        estado, datos = self._pedir(puerto, cuerpo=b"x" * 40_000)
        self.assertEqual(405, estado)
        self.assertTrue(datos["error"])
        self.assertTrue(listo.wait(2))
        self.assertEqual(40_000, eventos[-1]["leidos"])
        self.assertEqual(200, self._pedir(puerto, "GET", None)[0])

    def test_cuerpo_retenido_y_goteo_no_bloquean_otro_cliente(self):
        for cabeceras, goteo in (("Content-Length: 2", False),
                                  ("Content-Length: 10", True)):
            with self.subTest(goteo=goteo):
                puerto, _, eventos, listo = self._servidor(solo_lectura=True)
                conexion = self._raw(puerto, cabeceras)
                inicio = time.monotonic()
                respuesta = self._respuesta_raw(conexion)
                self.assertTrue(respuesta["error"])
                self.assertLess(time.monotonic() - inicio, 0.20)
                self.assertEqual(200, self._pedir(puerto, "GET", None)[0])
                if goteo:
                    for _ in range(3):
                        time.sleep(0.07)
                        conexion.sendall(b"x")
                hasta = time.monotonic() + 1
                while not any(e["codigo"] == 405 for e in eventos) \
                        and time.monotonic() < hasta:
                    time.sleep(0.005)
                self.assertLess(time.monotonic() - inicio, 0.40)
                rechazo = next(e for e in eventos if e["codigo"] == 405)
                self.assertLess(rechazo["leidos"],
                                10 if goteo else 2)
                self.assertEqual(200, self._pedir(puerto, "GET", None)[0])

    def test_error_de_lectura_restaura_timeout_y_conserva_rechazo(self):
        puerto, _, eventos, listo = self._servidor(solo_lectura=True,
                                                   timeout_inicial=0.8)
        with mock.patch.object(LectorContado, "read1", side_effect=OSError("lectura")):
            conexion = self._raw(puerto, "Content-Length: 2")
            datos = self._respuesta_raw(conexion)
            self.assertTrue(datos["error"])
            self.assertTrue(listo.wait(2))
        self.assertEqual(405, eventos[-1]["codigo"])
        self.assertEqual(0.8, eventos[-1]["timeout"])
        self.assertEqual(200, self._pedir(puerto, "GET", None)[0])


if __name__ == "__main__":
    unittest.main()
