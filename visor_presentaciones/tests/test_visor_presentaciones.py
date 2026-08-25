import http.client
import json
import urllib.request
import tempfile
import threading
import unittest
from pathlib import Path

from visor_presentaciones import abrir, manifestar, servir


def manifiesto_valido():
    return {
        "version": 1,
        "presentaciones": [
            {
                "id": "peticion-uno",
                "tipo": "bandeja",
                "titulo": "Peticiones por decidir",
                "version": "2026-08-23.1",
                "estado": "pendiente",
                "peticiones": [
                    {
                        "id": "P-001",
                        "titulo": "Preparar una vista local",
                        "detalle": "Leer el encargo y decidir antes de construir.",
                        "estado": "pendiente",
                        "destino": "propuesta-uno",
                    },
                    {
                        "id": "P-002",
                        "titulo": "Revisar evidencia",
                        "detalle": "Comprobar el resultado entregado.",
                        "estado": "decidida",
                        "destino": "validacion-uno",
                    },
                ],
            },
            {
                "id": "lectura-uno",
                "tipo": "lector",
                "variante": "incidencia",
                "titulo": "Investigación de la vista local",
                "version": "11",
                "preguntas": ["¿Qué debe decidir la persona?"],
                "hechos": ["El servidor escucha sólo en la interfaz local."],
                "fuentes": ["docs/investigacion.md#P1"],
                "hallazgos": ["Una plantilla sirve para varias clases de lectura."],
                "conclusiones": ["La decisión necesita un recibo nuevo."],
                "limites": ["No muestra archivos completos ni registros largos."],
            },
            {
                "id": "propuesta-uno",
                "tipo": "propuesta",
                "titulo": "Propuesta de cuatro vistas",
                "version": "3",
                "resumen": "Construir cuatro superficies locales con una plantilla fija.",
                "opciones": ["aprobar", "pedir_cambios"],
                "comentario_obligatorio": ["pedir_cambios"],
            },
            {
                "id": "validacion-uno",
                "tipo": "validacion",
                "titulo": "Validar las cuatro vistas",
                "version": "1",
                "pasos": ["Abrir la bandeja", "Registrar un problema"],
                "evidencia": ["python3 -m unittest: OK"],
                "opciones": ["confirmado", "problema"],
                "comentario_obligatorio": ["problema"],
            },
        ],
    }


class PruebasManifiesto(unittest.TestCase):
    def test_acepta_las_cuatro_vistas_y_genera_ejemplo_seguro(self):
        datos = manifiesto_valido()
        self.assertEqual(manifestar.validar(datos), datos)
        ejemplo = manifestar.crear_ejemplo()
        self.assertEqual({p["tipo"] for p in ejemplo["presentaciones"]},
                         {"bandeja", "lector", "propuesta", "validacion"})
        manifestar.validar(ejemplo)

    def test_rechaza_tipo_version_campo_y_referencia_inseguros(self):
        casos = []
        for mutacion in (
            lambda d: d.update(version=2),
            lambda d: d["presentaciones"][0].update(tipo="tablero"),
            lambda d: d["presentaciones"][0].update(secreto="no"),
            lambda d: d["presentaciones"][1]["fuentes"].__setitem__(0, "../.private/token"),
        ):
            datos = manifiesto_valido()
            mutacion(datos)
            casos.append(datos)
        for datos in casos:
            with self.subTest(datos=datos):
                with self.assertRaisesRegex(ValueError, ".+"):
                    manifestar.validar(datos)

    def test_rechaza_secretos_pii_y_salida_extensa(self):
        textos = [
            "-----BEGIN PRIVATE KEY-----",
            "Authorization: Bearer abcdefghijklmnop",
            "persona@example.com",
            "x" * 2001,
        ]
        for texto in textos:
            datos = manifiesto_valido()
            datos["presentaciones"][1]["hallazgos"] = [texto]
            with self.subTest(texto=texto[:30]):
                with self.assertRaisesRegex(ValueError, "sensible|extenso"):
                    manifestar.validar(datos)


class PruebasLanzadorEstable(unittest.TestCase):
    def test_abre_y_reutiliza_la_ruta_directa_con_servidor_vivo(self):
        with tempfile.TemporaryDirectory() as temporal:
            datos = Path(temporal)
            (datos / "manifiesto.json").write_text(
                json.dumps(manifiesto_valido()), encoding="utf-8"
            )
            try:
                puerto = abrir._puerto_libre()
            except PermissionError:
                raise unittest.SkipTest("sandbox sin sockets locales")
            args = abrir.argumentos_prueba(
                puerto=puerto, presentacion="propuesta-uno"
            )
            primera = abrir.abrir(datos, args)
            self.addCleanup(abrir.detener, primera.proceso)
            self.assertTrue(primera.url.endswith("/presentacion/propuesta-uno"))
            with urllib.request.urlopen(primera.url, timeout=3) as respuesta:
                self.assertEqual(respuesta.status, 200)

            segunda = abrir.abrir(datos, args)

            self.assertEqual(segunda.url, primera.url)
            self.assertIsNone(segunda.proceso)

class PruebasServidor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.datos = Path(self.tmp.name)
        (self.datos / "manifiesto.json").write_text(
            json.dumps(manifiesto_valido()), encoding="utf-8"
        )
        self.estado = {"ultimo": 0}
        try:
            self.servidor = servir.ServidorPresentaciones(
                ("127.0.0.1", 0), servir.hacer_handler(self.datos, self.estado)
            )
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

    def pedir(self, metodo, ruta, datos=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.servidor.server_port)
        cuerpo = None if datos is None else json.dumps(datos)
        cabeceras = {} if cuerpo is None else {"Content-Type": "application/json"}
        conexion.request(metodo, ruta, body=cuerpo, headers=cabeceras)
        respuesta = conexion.getresponse()
        contenido = respuesta.read()
        cabeceras_respuesta = dict(respuesta.getheaders())
        conexion.close()
        return respuesta.status, cabeceras_respuesta, contenido

    def test_get_sirve_plantilla_manifiesto_recibos_y_ruta_directa(self):
        # Unidad 056: una sola plantilla con menú + panel (hash), no una
        # página por vista; la ruta directa sirve la MISMA plantilla que "/".
        estado, cabeceras, html = self.pedir("GET", "/presentacion/propuesta-uno")
        self.assertEqual(estado, 200)
        self.assertIn(b'id="menu"', html)
        self.assertIn(b'id="panel"', html)
        self.assertIn(b"Content-Security-Policy", str(cabeceras).encode())
        self.assertEqual(cabeceras["Cache-Control"], "no-store")

        estado, _, cuerpo = self.pedir("GET", "/manifiesto.json")
        self.assertEqual(estado, 200)
        self.assertEqual(len(json.loads(cuerpo)["presentaciones"]), 4)
        estado, _, cuerpo = self.pedir("GET", "/recibos.json")
        self.assertEqual((estado, json.loads(cuerpo)), (200, {"recibos": []}))

    def test_meta_identifica_la_sesion_sin_exponer_la_ruta_de_datos(self):
        estado, _, cuerpo = self.pedir("GET", "/meta.json")

        self.assertEqual(estado, 200)
        meta = json.loads(cuerpo)
        self.assertEqual(meta["servicio"], "visor-presentaciones")
        self.assertEqual(meta["huella_datos"], abrir.huella_datos(self.datos))
        self.assertNotIn("datos", meta)
        self.assertNotIn(str(self.datos), cuerpo.decode("utf-8"))

    def test_plantilla_contiene_controles_foco_y_adaptacion_movil(self):
        _, _, html = self.pedir("GET", "/")
        texto = html.decode("utf-8")
        for esperado in (
            'id="menu"', 'id="listado"', 'id="panel"',
            'name="eleccion"', 'id="comentario"',
            ':focus-visible',
            '@media (max-width: 700px)',
            'aria-live="polite"',
        ):
            self.assertIn(esperado, texto)
        # El corte de 860px (el menú lateral que se apila) lo trae la hoja
        # común desde la 076: se comprueba donde ahora vive.
        _, cabeceras, hoja = self.pedir("GET", "/base.css")
        self.assertIn("text/css", cabeceras["Content-Type"])
        self.assertIn("@media (max-width: 860px)", hoja.decode("utf-8"))

    def test_plantilla_usa_el_lenguaje_visual_del_visor_de_contratos(self):
        # Unidad 056: la plantilla se rehizo sobre el esqueleto del visor de
        # contratos (antes copiaba la paleta del visor de flujos a 920px).
        # Unidad 076: ese esqueleto ya no viaja DENTRO del HTML — el servidor
        # sirve `/base.css`, la misma hoja que las otras tres webs. Así que se
        # comprueba lo mismo, pero donde ahora está.
        _, _, html = self.pedir("GET", "/")
        self.assertIn('<link rel="stylesheet" href="/base.css">',
                      html.decode("utf-8"))
        estado, cabeceras, cuerpo = self.pedir("GET", "/base.css")
        self.assertEqual(200, estado)
        self.assertIn("text/css", cabeceras["Content-Type"])
        hoja = cuerpo.decode("utf-8")
        for esperado in (
            "--paper: #F3F5F1", "--sans: -apple-system",
            ":root[data-theme=\"dark\"]", ".boton-tema",
            "outline: 2px solid var(--warn)", "--ancho-pagina: 1180px",
        ):
            self.assertIn(esperado, hoja)

    def test_decision_valida_crea_recibos_nuevos_inmutables(self):
        decision = {
            "presentacion": "propuesta-uno", "version": "3",
            "contenido_revisado": "Construir cuatro superficies locales con una plantilla fija.",
            "eleccion": "aprobar", "comentario": "Adelante", "confirmado": True,
        }
        estado, _, cuerpo = self.pedir("POST", "/decisiones", decision)
        self.assertEqual(estado, 201, cuerpo)
        primero = json.loads(cuerpo)["recibo"]
        self.assertEqual(primero["eleccion"], "aprobar")
        self.assertEqual(primero["version"], "3")
        self.assertIn("fecha", primero)

        estado, _, cuerpo = self.pedir("POST", "/decisiones", decision)
        self.assertEqual(estado, 201, cuerpo)
        segundo = json.loads(cuerpo)["recibo"]
        self.assertNotEqual(primero["id"], segundo["id"])
        recibos = sorted((self.datos / "recibos").glob("*.json"))
        self.assertEqual(len(recibos), 2)
        self.assertEqual(json.loads(recibos[0].read_text())["eleccion"], "aprobar")

    def test_validacion_registra_problema_con_nota(self):
        decision = {
            "presentacion": "validacion-uno", "version": "1",
            "contenido_revisado": "Abrir la bandeja\nRegistrar un problema",
            "eleccion": "problema", "comentario": "El foco no se ve", "confirmado": True,
        }
        estado, _, cuerpo = self.pedir("POST", "/decisiones", decision)
        self.assertEqual(estado, 201, cuerpo)
        self.assertEqual(json.loads(cuerpo)["recibo"]["eleccion"], "problema")

    def test_deniega_antes_de_escribir(self):
        base = {
            "presentacion": "propuesta-uno", "version": "3",
            "contenido_revisado": "Construir cuatro superficies locales con una plantilla fija.",
            "eleccion": "pedir_cambios", "comentario": "Explica el cambio", "confirmado": True,
        }
        casos = []
        for clave, valor in (
            ("comentario", ""), ("version", "2"), ("eleccion", "borrar"),
            ("confirmado", False), ("contenido_revisado", "otro contenido"),
        ):
            caso = dict(base)
            caso[clave] = valor
            casos.append(caso)
        for caso in casos:
            with self.subTest(caso=caso):
                estado, _, cuerpo = self.pedir("POST", "/decisiones", caso)
                self.assertEqual(estado, 400, cuerpo)
        self.assertFalse((self.datos / "recibos").exists())

    def test_deniega_post_ajeno_json_roto_y_traversal_sin_escribir(self):
        estado, _, _ = self.pedir("POST", "/manifiesto.json", {})
        self.assertEqual(estado, 405)
        conexion = http.client.HTTPConnection("127.0.0.1", self.servidor.server_port)
        conexion.request("POST", "/decisiones", body=b"{", headers={"Content-Type": "application/json"})
        respuesta = conexion.getresponse()
        respuesta.read()
        self.assertEqual(respuesta.status, 400)
        conexion.close()
        for ruta in ("/../manifiesto.json", "/presentacion/../../etc/passwd"):
            estado, _, _ = self.pedir("GET", ruta)
            self.assertEqual(estado, 404)
        self.assertFalse((self.datos / "recibos").exists())

    def test_deniega_post_si_recibos_es_symlink_exterior(self):
        exterior = Path(self.tmp.name + "-exterior")
        exterior.mkdir()
        self.addCleanup(exterior.rmdir)
        (self.datos / "recibos").symlink_to(exterior, target_is_directory=True)
        decision = {
            "presentacion": "propuesta-uno", "version": "3",
            "contenido_revisado": "Construir cuatro superficies locales con una plantilla fija.",
            "eleccion": "aprobar", "comentario": "Adelante", "confirmado": True,
        }

        estado, _, cuerpo = self.pedir("POST", "/decisiones", decision)

        self.assertEqual(estado, 400, cuerpo)
        self.assertEqual(list(exterior.iterdir()), [])

    def test_deniega_get_si_recibo_json_es_symlink_exterior(self):
        carpeta = self.datos / "recibos"
        carpeta.mkdir()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as salida:
            json.dump({"secreto": "exterior"}, salida)
            exterior = Path(salida.name)
        self.addCleanup(exterior.unlink)
        (carpeta / "escape.json").symlink_to(exterior)

        estado, _, cuerpo = self.pedir("GET", "/recibos.json")

        self.assertEqual(estado, 400, cuerpo)
        self.assertNotIn(b"secreto", cuerpo)


if __name__ == "__main__":
    unittest.main()
