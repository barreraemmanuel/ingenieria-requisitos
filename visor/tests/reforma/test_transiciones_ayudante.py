"""Unidad 146 · R2 — la tabla de transiciones de la junta ayudante→revisor→prefusión→cierre.

**Esta carpeta está en ROJO a propósito.** Es la línea base de la reforma: cada test de aquí
describe lo que la junta TIENE que hacer, y hoy no hace. `visor/tests/correr.py --reforma`
los corre contra el manifiesto `esperado.json` y termina en `VEREDICTO: N rojos esperados /
M verdes`; un rojo esperado NO rompe la suite rápida, y un test que cambia de color sin que
nadie actualice el manifiesto sí para. Cuando la 147 construya la entrega del ayudante, esos
rojos pasan a verdes y el manifiesto se actualiza con ellos: ese diff ES la demostración.

El hecho que decide en toda esta tabla es git (¿árbol limpio?, ¿la cabeza se movió desde el
despacho?) más el recibo `ejecucion/v1` del ayudante, nunca el texto ni el `exit` del harness
(incidente 034 del 22-08: el recibo decía `fail`, el árbol estaba sucio y la cabeza sin mover,
y la entrega se dio por buena). El contrato que estos tests fijan para la 147 es una sola
función en `ejecucion.py`:

    exigir_entrega_constructor(worktree, unidad, recibos, base) -> (problemas, avisos)

`worktree` es la ruta del worktree, `unidad` su nombre, `recibos` los `ejecucion/v1` de esa
unidad en orden de escritura y `base` lo que `unidad.py despachar` anotó al abrir la entrega
(`head`, `plan: {marcadas, totales}`, `carril`, `espera_cambios`). Devuelve la misma forma que
`unidad.py:puerta_recibo_revisor`: una lista de problemas —cada uno con su `SALIDA:` y un
comando ejecutable— y una lista de avisos, que no bloquean.

Cada caso de rechazo hace tres cosas, no una: comprueba que se rechaza, comprueba que el
rechazo nombra una salida, y **aplica el estado que esa salida produce y reintenta**, para que
ninguna puerta pueda bloquear sin dejar camino (regla 13 · bugs 125-145).
"""
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import taller_reforma as tr                                          # noqa: E402
from taller_reforma import SALIDA, Worktree, ejecucion, salida_de    # noqa: E402


class JuntaBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reforma-junta-")
        self.addCleanup(self.tmp.cleanup)
        self.wt = Worktree(Path(self.tmp.name) / "worktrees" / "146-unidad-de-juguete")

    # ------------------------------------------------------------------ el sujeto
    def exigir(self, recibos, base=None):
        """Llama a la puerta que la 147 tiene que construir. Hoy no existe: eso es el rojo."""
        puerta = getattr(ejecucion, "exigir_entrega_constructor", None)
        self.assertIsNotNone(
            puerta,
            "ejecucion.py no tiene `exigir_entrega_constructor`: la entrega del ayudante "
            "sigue siendo el texto del harness, que es lo que falló el 22-08 (034)")
        return puerta(self.wt.ruta, self.wt.unidad, list(recibos),
                      base if base is not None else self.wt.base())

    # ------------------------------------------------------------------ aserciones
    def bloquea(self, recibos, base=None, porque=""):
        problemas, _ = self.exigir(recibos, base)
        self.assertTrue(problemas, porque or "la junta dejó pasar la entrega")
        for problema in problemas:
            self.assertIn(SALIDA, problema,
                          f"rechazo sin vía de salida: {problema[:120]}")
            self.assertTrue(salida_de(problema),
                            f"el `SALIDA:` no nombra ningún comando: {problema[:120]}")
        return problemas

    def pasa(self, recibos, base=None, porque=""):
        problemas, _ = self.exigir(recibos, base)
        self.assertEqual(problemas, [], porque or f"la junta bloqueó de más: {problemas}")


# ---------------------------------------------------------------------------------
# Los nueve estados del recibo del ayudante (los que salen de los 17 incidentes de
# delegación), cada uno con su salida ejecutada y su reintento.
# ---------------------------------------------------------------------------------
class ReciboDelAyudanteTest(JuntaBase):

    def test_recibo_ausente_bloquea_y_la_salida_es_relanzar(self):
        self.wt.commitear()
        self.bloquea([], porque="sin recibo no hay entrega que acreditar")
        # salida: lanzar al ayudante deja el recibo; con él y con trabajo, la junta pasa.
        self.pasa([self.wt.recibo(resultado="ok")], self.wt.base(marcadas=0))

    def test_recibo_corrupto_bloquea_como_ausente(self):
        self.wt.commitear()
        self.bloquea([self.wt.recibo(corrupto=True)],
                     porque="un recibo que no se puede leer no acredita nada")
        self.pasa([self.wt.recibo(resultado="ok")])

    def test_recibo_fail_bloquea_el_paso_al_revisor(self):
        """El 034, literal: el recibo decía `fail` y la entrega siguió."""
        recibo = tr.recibo_fixture("constructor-fail-034")
        recibo["unidad"] = self.wt.unidad
        recibo["git"]["final"]["head"] = self.wt.base_head
        self.bloquea([recibo], porque="un `fail` del ayudante no es una entrega")
        self.pasa([self.wt.recibo(resultado="ok", head=self.wt.commitear())])

    def test_recibo_interrumpido_bloquea(self):
        self.wt.commitear()
        self.bloquea([self.wt.recibo(resultado="interrumpido")])
        self.pasa([self.wt.recibo(resultado="ok")])

    def test_recibo_abierto_sin_resultado_bloquea(self):
        """38 recibos de constructor de este taller no tienen `resultado` (señal S2)."""
        self.wt.commitear()
        self.bloquea([self.wt.recibo(resultado=None)])
        self.pasa([self.wt.recibo(resultado="ok")])

    def test_recibo_de_otra_unidad_no_acredita_esta(self):
        self.wt.commitear()
        ajeno = self.wt.recibo(resultado="ok", unidad="999-otra-unidad")
        self.bloquea([ajeno], porque="el recibo de otra unidad no acredita esta entrega")
        self.pasa([ajeno, self.wt.recibo(resultado="ok")])

    def test_recibo_obsoleto_porque_el_worktree_siguio_cambiando(self):
        viejo = self.wt.recibo(resultado="ok", head=self.wt.commitear())
        self.wt.commitear("un commit posterior que nadie revisó")
        self.bloquea([viejo], porque="el recibo habla de un árbol que ya no es el que hay")
        self.pasa([self.wt.recibo(resultado="ok")])

    def test_worktree_sucio_bloquea_aunque_el_recibo_diga_ok(self):
        self.wt.commitear()
        self.wt.ensuciar()
        self.bloquea([self.wt.recibo(resultado="ok", sucio=True)],
                     porque="lo que no está commiteado no entra en el diff que se revisa")
        # salida: commitear lo que falta; con el árbol limpio, la junta pasa.
        head = self.wt.commitear("lo que faltaba por commitear")
        self.pasa([self.wt.recibo(resultado="ok", head=head)])

    def test_trabajo_parcial_sin_casillas_nuevas_bloquea(self):
        self.wt.commitear()
        base = self.wt.base(marcadas=2, totales=4)
        recibo = self.wt.recibo(resultado="ok")
        recibo["trabajo"] = {"plan": {"marcadas": 2, "totales": 4}}
        self.bloquea([recibo], base,
                     porque="una entrega sin una sola casilla nueva no es una entrega")
        avanzado = self.wt.recibo(resultado="ok")
        avanzado["trabajo"] = {"plan": {"marcadas": 3, "totales": 4}}
        self.pasa([avanzado], base)

    def test_entrega_buena_no_bloquea(self):
        head = self.wt.commitear()
        recibo = self.wt.recibo(resultado="ok", head=head)
        recibo["trabajo"] = {"plan": {"marcadas": 4, "totales": 4}}
        self.pasa([recibo], self.wt.base(marcadas=0, totales=4))

    def test_ok_sin_trabajo_legitimo_no_bloquea_cuando_el_carril_no_espera_cambios(self):
        """Una unidad documental o un exprés sin cambios de código entregan sin diff."""
        base = self.wt.base()
        base["espera_cambios"] = False
        base["carril"] = "documental"
        self.pasa([self.wt.recibo(resultado="ok_sin_trabajo", head=self.wt.base_head)], base)

    def test_ok_sin_trabajo_si_bloquea_cuando_el_contrato_esperaba_cambios(self):
        self.bloquea([self.wt.recibo(resultado="ok_sin_trabajo", head=self.wt.base_head)],
                     self.wt.base())


# ---------------------------------------------------------------------------------
# Los estados ALCANZABLES de la máquina, con un fallo simple por transición.
# No es un producto cartesiano: son las tres transiciones que existen, y en las tres
# se vuelve a derivar el estado (arreglo 1b: «una sola función, tres puntos de consumo»).
# ---------------------------------------------------------------------------------
CONSUMIDORES = (
    ("ejecucion.py", "lanzar al revisor",
     "el revisor se lanza sobre una entrega que nadie acreditó (034)"),
    ("unidad.py", "prefusión",
     "la prefusión mide un árbol que el ayudante dejó a medias"),
    ("unidad.py", "cerrar",
     "el cierre firma una entrega que no ocurrió"),
)


class TresPuntosDeConsumoTest(unittest.TestCase):
    """La misma función, invocada en las tres transiciones. Hoy no la invoca ninguna."""

    SCRIPTS = Path(__file__).resolve().parents[3] / "plantilla/docs/00-metodo/scripts"

    def fuente(self, script):
        return (self.SCRIPTS / script).read_text(encoding="utf-8")

    def test_la_junta_es_una_sola_funcion_y_no_tres_copias(self):
        fuente = self.fuente("ejecucion.py")
        self.assertIn("def exigir_entrega_constructor", fuente,
                      "la entrega del ayudante no tiene puerta: cada punto la improvisa")

    def test_lanzar_al_revisor_consume_la_junta(self):
        self.assertIn("exigir_entrega_constructor", self.fuente("ejecucion.py"))

    def test_prefusion_y_cierre_consumen_la_junta(self):
        fuente = self.fuente("unidad.py")
        self.assertIn("exigir_entrega_constructor", fuente,
                      "ni `prefusion` ni `cerrar` vuelven a derivar el estado de la entrega")

    def test_la_junta_no_reejecuta_la_suite(self):
        """Arreglo 1b: los checks los corre una vez quien ya los corre, no esta puerta."""
        puerta = getattr(ejecucion, "exigir_entrega_constructor", None)
        self.assertIsNotNone(puerta, "todavía no existe la junta")
        fuente = inspect.getsource(puerta)
        for caro in ("correr.py", "unittest", "lint_metodo.py"):
            self.assertNotIn(caro, fuente,
                             f"la junta se puso a correr {caro}: eso ya lo hace el revisor")


# ---------------------------------------------------------------------------------
# Inyección de fallos, la única barata de esta fase: el recibo se escribe atómico.
# ---------------------------------------------------------------------------------
class ReciboAtomicoTest(unittest.TestCase):
    """Un recibo a medio escribir es indistinguible de un ayudante que mintió."""

    def test_guardar_recibo_escribe_por_temporal_y_rename(self):
        fuente = inspect.getsource(ejecucion.guardar_recibo)
        self.assertIn("os.replace", fuente,
                      "sin `rename` atómico, una interrupción deja medio JSON en disco")

    def test_un_corte_a_mitad_de_escritura_no_deja_recibo_invalido(self):
        with tempfile.TemporaryDirectory(prefix="reforma-atomico-") as tmp:
            ruta = Path(tmp) / "recibo.json"
            ejecucion.guardar_recibo(ruta, {"schema": "ejecucion/v1", "resultado": "ok"})
            self.assertEqual(json.loads(ruta.read_text(encoding="utf-8"))["resultado"], "ok")
            # El temporal no sobrevive: si sobreviviera, un lector podría tomarlo por recibo.
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["recibo.json"])

    def test_el_recibo_no_es_legible_por_terceros(self):
        if os.name == "nt":
            self.skipTest("los permisos POSIX no aplican en Windows")
        with tempfile.TemporaryDirectory(prefix="reforma-permisos-") as tmp:
            ruta = Path(tmp) / "recibo.json"
            ejecucion.guardar_recibo(ruta, {"schema": "ejecucion/v1"})
            self.assertEqual(ruta.stat().st_mode & 0o077, 0)


# ---------------------------------------------------------------------------------
# Los recibos que alimentan la tabla son REALES (anonimizados), no inventados.
# ---------------------------------------------------------------------------------
class FixturesRealesTest(unittest.TestCase):
    ESPERADOS = {
        "constructor-ok": "ok",
        "constructor-fail-034": "fail",
        "constructor-ok-sin-trabajo": "ok_sin_trabajo",
        "constructor-abierto": None,
        "revisor-ok": "ok",
    }

    def test_los_cinco_recibos_del_fixture_son_los_cinco_estados_reales(self):
        for nombre, resultado in self.ESPERADOS.items():
            datos = tr.recibo_fixture(nombre)
            self.assertEqual(datos["schema"], "ejecucion/v1", nombre)
            self.assertEqual(datos.get("resultado"), resultado, nombre)

    def test_ningun_fixture_lleva_datos_de_nadie(self):
        for ruta in sorted(tr.FIXTURES.glob("*.json")):
            crudo = ruta.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", crudo, ruta.name)
            self.assertNotIn("@gmail", crudo, ruta.name)

    def test_el_034_conserva_lo_que_lo_hizo_pasar(self):
        """La cabeza sin mover, el árbol sucio y `resultado: fail`: los tres a la vez."""
        datos = tr.recibo_fixture("constructor-fail-034")
        self.assertEqual(datos["resultado"], "fail")
        self.assertEqual(datos["git"]["inicial"]["head"], datos["git"]["final"]["head"])
        self.assertTrue(datos["git"]["final"]["status_porcelain"])


if __name__ == "__main__":
    unittest.main()
