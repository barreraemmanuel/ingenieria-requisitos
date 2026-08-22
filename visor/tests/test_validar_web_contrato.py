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
(count 0, clic cuelga); solo tras pulsar "🗺 El mapa" reaparece.
"""

import argparse
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
        if self.nombre == "🗺 El mapa":
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
        tabs = {"🗺 El mapa"}
        if self.tiene_superficie:
            tabs.add("Por persona")
        return tabs

    def get_by_role(self, rol, name, exact=True):
        return BotonFalso(self, name)

    def wait_for_function(self, *_a, **_k):
        return None

    def locator(self, selector):
        return LocatorTexto("")


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

    def test_actividad_valida_abre_su_resumen_directamente(self):
        salida = io.StringIO()
        with mock.patch.object(requisitos, "elegir_puerto", return_value=(8765, True)), \
             mock.patch.object(requisitos, "anotar_apertura"), \
             contextlib.redirect_stdout(salida):
            self.assertEqual(
                requisitos.cmd_abrir(self.workspace, self.mapa, self.args("canario-contexto")),
                0,
            )
        self.assertIn(
            "http://127.0.0.1:8765/#canario-contexto::resumen", salida.getvalue()
        )

    def test_actividad_valida_abre_su_resumen_al_arrancar_servidor(self):
        salida = io.StringIO()
        proceso = mock.Mock()
        proceso.poll.return_value = None
        with mock.patch.object(requisitos, "elegir_puerto", return_value=(0, False)), \
             mock.patch.object(requisitos, "puerto_libre", return_value=8767), \
             mock.patch.object(requisitos, "anotar_apertura", return_value=self.workspace / "visor.log"), \
             mock.patch.object(requisitos.subprocess, "Popen", return_value=proceso), \
             mock.patch.object(
                 requisitos,
                 "meta_puerto",
                 return_value={"datos": str(self.mapa)},
             ), \
             contextlib.redirect_stdout(salida):
            self.assertEqual(
                requisitos.cmd_abrir(self.workspace, self.mapa, self.args("canario-contexto")),
                0,
            )
        self.assertIn(
            "http://127.0.0.1:8767/#canario-contexto::resumen", salida.getvalue()
        )

    def test_actividad_inexistente_no_abre_la_portada(self):
        with mock.patch.object(requisitos, "elegir_puerto") as elegir:
            with self.assertRaisesRegex(ValueError, "no existe"):
                requisitos.cmd_abrir(
                    self.workspace, self.mapa, self.args("no-existe")
                )
        elegir.assert_not_called()

    def test_sin_actividad_conserva_la_portada(self):
        salida = io.StringIO()
        with mock.patch.object(requisitos, "elegir_puerto", return_value=(8765, True)), \
             mock.patch.object(requisitos, "anotar_apertura"), \
             contextlib.redirect_stdout(salida):
            requisitos.cmd_abrir(self.workspace, self.mapa, self.args(None))
        self.assertIn("http://127.0.0.1:8765/", salida.getvalue())
        self.assertNotIn("#", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
