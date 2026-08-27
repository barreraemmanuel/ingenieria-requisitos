"""Regresión de la issue #3: el contrato E2E en proyectos con mapa.

Dos versiones del bug:
1. Trivial: el índice raíz de un mapa tiene actores pero ni flujos ni superficie,
   así que el visor no pinta "Por persona"; esperarla colgaba validar_web.
2. General (lo que el primer fix NO cubrió): mapa CON superficie o flujos. El
   visor sí pinta "Por persona", pero el recorrido del lateral deja la SPA en una
   sub-vista de actividad que oculta el `nav`; había que volver a la vista global,
   y una navegación por hash no lo hace (el visor no escucha `hashchange`).

Sin Playwright en el CI, se modela la MECÁNICA con un doble de página: en la
sub-vista de actividad el `nav` está oculto y "Por persona" no es accesible
(count 0, clic cuelga); solo tras pulsar el botón del mapa (`BOTON_MAPA`) reaparece.
"""

import argparse
import re
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from visor import requisitos

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "validar_web", RAIZ / "visor/validar_web.py"
)
validar_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validar_web)

class BotonFalso:
    def __init__(self, page, nombre):
        self.page = page
        self.nombre = nombre

    def count(self):
        return 1 if self.nombre in self.page.pestanas_accesibles() else 0

    def click(self):
        if self.nombre == validar_web.BOTON_MAPA:
            self.page.vista = "global"
            return
        if self.nombre not in self.page.pestanas_accesibles():
            raise TimeoutError(
                f'Timeout esperando el botón "{self.nombre}" (nav oculto en {self.page.vista})'
            )
        self.page.pestana_activa = self.nombre


class LocatorTexto:
    def __init__(self, texto):
        self._texto = texto

    def inner_text(self):
        return self._texto

    def all(self):
        return []


class PaginaMapa:
    """SPA con mapa: arranca en una sub-vista de actividad (como la deja
    comprobar_lateral) donde el nav está oculto; el botón del mapa lo restaura."""

    def __init__(self, tiene_superficie):
        self.vista = "actividad"
        self.pestana_activa = None
        self.tiene_superficie = tiene_superficie

    def pestanas_accesibles(self):
        if self.vista != "global":
            return set()  # nav.hidden en la sub-vista de actividad
        tabs = {validar_web.BOTON_MAPA}
        if self.tiene_superficie:
            tabs.add("Por persona")
        return tabs

    def get_by_role(self, rol, name, exact=True):
        return BotonFalso(self, name)

    def wait_for_function(self, *_a, **_k):
        return None

    def locator(self, selector):
        return LocatorTexto("")


class JuntaBotonDelMapaTest(unittest.TestCase):
    """Bug 115: el E2E buscaba «🗺 El mapa» y la plantilla pinta «El mapa» (el emoji se fue
    con la estética 076/081 y el E2E no se enteró): `validar_web.py` fallaba en el lateral
    de TODO proyecto con mapa y con él `requisitos.py aprobar` y `finalizar.py`. La junta
    se fija leyendo los dos ficheros: el nombre con el que el E2E busca el botón es el
    literal que la plantilla renderiza."""

    def nombre_en_el_e2e(self):
        fuente = (RAIZ / "visor/validar_web.py").read_text(encoding="utf-8")
        nombres = set(re.findall(r'get_by_role\("button",\s*name=("[^"]*[Mm]apa[^"]*"|BOTON_MAPA)', fuente))
        self.assertTrue(nombres, "validar_web.py ya no pulsa el botón del mapa por su nombre")
        resueltos = set()
        for nombre in nombres:
            resueltos.add(nombre.strip('"') if nombre.startswith('"') else getattr(validar_web, nombre))
        self.assertEqual(len(resueltos), 1, resueltos)
        return resueltos.pop()

    def nombre_en_la_plantilla(self):
        html = (RAIZ / "visor/plantilla.html").read_text(encoding="utf-8")
        encontrado = re.search(r'el\("button",[^\n]*"menu-item"[^\n]*,\s*"([^"]+)"\)', html)
        self.assertIsNotNone(encontrado, "plantilla.html ya no pinta el botón del mapa como menu-item")
        return encontrado.group(1)

    def test_el_e2e_busca_el_boton_del_mapa_con_el_texto_que_la_plantilla_pinta(self):
        self.assertEqual(
            self.nombre_en_el_e2e(), self.nombre_en_la_plantilla(),
            "bug 115: el E2E y la plantilla no llaman igual al botón del mapa → "
            "validar_web falla en el lateral y bloquea aprobar/finalizar",
        )

    def test_el_e2e_espera_la_clase_con_la_que_la_plantilla_marca_el_boton_elegido(self):
        html = (RAIZ / "visor/plantilla.html").read_text(encoding="utf-8")
        clase = re.search(r'"menu-item" \+ \(seleccion === "mapa" \? " (\w+)" : ""\)', html)
        self.assertIsNotNone(clase, "plantilla.html ya no marca el botón elegido del menú")
        fuente = (RAIZ / "visor/validar_web.py").read_text(encoding="utf-8")
        self.assertFalse("contains('activo')" in fuente,
                         "bug 115: el E2E esperaba la clase `activo` y la plantilla pinta `activa`")
        self.assertEqual(validar_web.CLASE_ACTIVA, clase.group(1))

    def test_la_lista_esperada_del_lateral_empieza_por_ese_mismo_boton(self):
        fuente = (RAIZ / "visor/validar_web.py").read_text(encoding="utf-8")
        encontrado = re.search(r'esperados = \[("[^"]+"|[A-Z_]+)\]', fuente)
        self.assertIsNotNone(encontrado)
        literal = encontrado.group(1)
        primero = literal.strip('"') if literal.startswith('"') else getattr(validar_web, literal)
        self.assertEqual(primero, self.nombre_en_la_plantilla())


class ContratoE2EConMapaTest(unittest.TestCase):
    def test_la_pestana_solo_es_accesible_tras_volver_al_mapa(self):
        """La mecánica del bug: en la sub-vista de actividad 'Por persona' no es
        accesible; volver_a_vista_global la restaura. Un hash no lo haría."""
        page = PaginaMapa(tiene_superficie=True)
        datos = {"actividades": [{"area": "a"}]}
        self.assertIsNone(validar_web.pestana_si_existe(page, "Por persona"))
        validar_web.volver_a_vista_global(page, datos)
        self.assertIsNotNone(validar_web.pestana_si_existe(page, "Por persona"))

    def test_mapa_con_superficie_vuelve_a_la_vista_global_antes_de_por_persona(self):
        """El caso general (issue #3): mapa + superficie no debe colgar en 'Por persona'."""
        page = PaginaMapa(tiene_superficie=True)
        datos = {
            "actividades": [{"nombre": "vender", "area": "negocio"}],
            "actores": [],  # sin actores concretos: no entra en comprobar_actores
            "superficie": {"permisos": {"roles": []}},
        }
        # No debe lanzar TimeoutError: vuelve al mapa antes de tocar la pestaña.
        validar_web.comprobar_contrato_e2e(page, datos)
        self.assertEqual(page.vista, "global")

    def test_mapa_sin_superficie_ni_flujos_no_busca_la_pestana(self):
        page = PaginaMapa(tiene_superficie=False)
        datos = {
            "actividades": [{"nombre": "vender", "area": "negocio"}],
            "actores": [{"nombre": "Persona de negocio"}],
        }
        validar_web.comprobar_contrato_e2e(page, datos)  # no cuelga: pestaña ausente

    def test_sin_actores_no_hay_contrato_de_personas(self):
        page = PaginaMapa(tiene_superficie=True)
        validar_web.comprobar_contrato_e2e(page, {"actividades": [{"area": "a"}]})


class AbrirActividadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="abrir-actividad-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.mapa = self.workspace / "docs/02-flujos/planos/planos.json"
        self.mapa.parent.mkdir(parents=True)
        self.mapa.write_text(
            json.dumps({"actividades": [{"id": "canario-contexto"}]}),
            encoding="utf-8",
        )

    def args(self, actividad):
        return argparse.Namespace(
            actividad=actividad,
            puerto=None,
            sin_navegador=True,
            minutos=0,
        )

    def _abrir(self, actividad, url):
        """`cmd_abrir` con la web ya en pie: sólo se mira la URL que compone."""
        salida = io.StringIO()
        falso = mock.Mock()
        falso.abrir.return_value = mock.Mock(url=url, proceso=None, navegador=False)
        falso.puerto_de.return_value = 8765
        with mock.patch.object(requisitos, "carpeta_web",
                               return_value=Path("web")), \
             mock.patch.object(requisitos, "modulo_abrir", return_value=falso), \
             mock.patch.object(requisitos, "anotar_apertura"), \
             contextlib.redirect_stdout(salida):
            codigo = requisitos.cmd_abrir(self.workspace, self.mapa,
                                          self.args(actividad))
        return codigo, salida.getvalue(), falso

    def test_actividad_valida_abre_su_apartado_de_flujos_en_su_resumen(self):
        """081: la actividad se pide como apartado de la web única, no como un
        puerto propio; el ancla del resumen se conserva tal cual."""
        codigo, salida, falso = self._abrir(
            "canario-contexto",
            "http://127.0.0.1:8770/flujos#canario-contexto::resumen")
        self.assertEqual(0, codigo)
        self.assertIn("http://127.0.0.1:8770/flujos#canario-contexto::resumen",
                      salida)
        argumentos = falso.abrir.call_args[0][1]
        self.assertEqual("flujos#canario-contexto::resumen", argumentos.apartado)

    def test_actividad_inexistente_no_abre_nada(self):
        with mock.patch.object(requisitos, "carpeta_web") as carpeta:
            with self.assertRaisesRegex(ValueError, "no existe"):
                requisitos.cmd_abrir(
                    self.workspace, self.mapa, self.args("no-existe")
                )
        carpeta.assert_not_called()

    def test_sin_actividad_conserva_la_portada_del_apartado(self):
        codigo, salida, falso = self._abrir(None, "http://127.0.0.1:8770/flujos")
        self.assertEqual(0, codigo)
        self.assertIn("http://127.0.0.1:8770/flujos", salida)
        self.assertEqual("flujos", falso.abrir.call_args[0][1].apartado)

    def test_deja_el_rastro_que_exige_aprobar(self):
        """R4 (unidad 033): sin `.runtime/visor-<puerto>.log` la aprobación
        firmaría unos planos que nadie ha visto."""
        falso = mock.Mock()
        falso.abrir.return_value = mock.Mock(
            url="http://127.0.0.1:8770/flujos", proceso=None, navegador=False)
        falso.puerto_de.return_value = 8770
        with mock.patch.object(requisitos, "carpeta_web",
                               return_value=Path("web")), \
             mock.patch.object(requisitos, "modulo_abrir", return_value=falso), \
             mock.patch.object(requisitos, "anotar_apertura") as rastro, \
             contextlib.redirect_stdout(io.StringIO()):
            requisitos.cmd_abrir(self.workspace, self.mapa, self.args(None))
        rastro.assert_called_once()
        self.assertEqual(8770, rastro.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
