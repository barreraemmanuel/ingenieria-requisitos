#!/usr/bin/env python3
"""Unidad 146 · R4 — la contraprueba: ¿estos tests MUERDEN, o pasarían igual sin mecanismo?

Un test verde no demuestra que el mecanismo exista. Un test VACUO —el que pasaría igual con
el guardián arrancado— es peor que no tener test: ocupa el sitio del que sí habría avisado y
deja a todo el mundo tranquilo. El ADR-030 lo zanjó para las unidades; esto es lo mismo
aplicado a la prueba base entera.

El método es siempre el mismo: **apagar un mecanismo por separado y exigir que se ponga
rojo el test que dice protegerlo**. Si sigue verde con el mecanismo apagado, ese test no
mide el mecanismo, y el número que la 146 entrega como línea base no vale nada.

Los cinco mecanismos que se apagan:

  1. el corte de `lint_invariantes.py` — llevado al futuro, una señal posterior deja de serlo
  2. `unidad.py:puerta_recibo_revisor` — vaciada en la copia del taller de prueba
  3. `lint_juntas.py:junta_tope_directo` — sustituida por «no hay nada que decir»
  4. `herramienta.py:cmd_comprobar` — el paso 0 del arranque, callado
  5. `canario.py:salida_hook_stop` — el aviso de fin de turno, callado

`guardian_rutas` (el replay del corpus) NO está aquí: llega con la 149, y su fila se añade
cuando exista. Fingirla ahora sería exactamente el vicio que este fichero persigue.

Uso:  python3 visor/tests/nightly/contraprueba_reforma.py
      python3 visor/tests/correr.py --nightly     # lo corre al final

VEREDICTO: N/5 mecanismos con dientes. Exit 1 si alguno sigue verde apagado.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[3]
for ruta in (str(RAIZ), str(RAIZ / "visor/tests"),
             str(RAIZ / "plantilla/docs/00-metodo/scripts")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from visor.tests.reforma import test_dientes_reforma as dientes   # noqa: E402
import canario                                                     # noqa: E402
import herramienta                                                 # noqa: E402
import lint_juntas                                                 # noqa: E402


def correr_uno(clase, metodo):
    """(rojo, primera línea del fallo) de UN solo test, sin ensuciar la pantalla."""
    suite = unittest.TestLoader().loadTestsFromName(metodo, clase)
    with open(os.devnull, "w") as mudo:
        resultado = unittest.TextTestRunner(stream=mudo, verbosity=0).run(suite)
    fallos = resultado.failures + resultado.errors
    motivo = ""
    if fallos:
        lineas = [l for l in str(fallos[0][1]).strip().splitlines() if l.strip()]
        motivo = lineas[-1][:120] if lineas else ""
    return (not resultado.wasSuccessful()), motivo


# ------------------------------------------------------- 1 · el corte de lint_invariantes
def contraprueba_corte():
    """Con el corte en el futuro, una señal posterior deja de existir: eso DEBE romper R1.

    Es el mecanismo más fácil de volver vacuo sin querer: basta con que el corte se calcule
    mal —o se ponga «hoy» cuando el sujeto es de hoy— para que la cuenta que bloquea sea
    siempre 0 y el linter salga verde para siempre.
    """
    import lint_invariantes

    with tempfile.TemporaryDirectory(prefix="contraprueba-corte-") as tmp:
        ws = Path(tmp)
        for sub in ("docs/05-trabajo/peticiones", "docs/bugs", "docs/00-metodo/scripts",
                    ".runtime/aprobaciones", ".runtime/ejecuciones"):
            (ws / sub).mkdir(parents=True, exist_ok=True)
        ficha = ws / "docs/05-trabajo/900-aprobada-despues-del-corte"
        ficha.mkdir(parents=True)
        (ficha / "especificacion.md").write_text(
            "---\nunidad: 900-aprobada-despues-del-corte\naprobado: 2026-09-15\n---\n",
            encoding="utf-8")
        base = ws / "base.json"

        def veredicto(corte):
            pantalla = io.StringIO()
            with contextlib.redirect_stdout(pantalla):
                codigo = lint_invariantes.main(
                    ["--workspace", str(ws), "--corte", corte, "--base", str(base)])
            return codigo

        con_mecanismo = veredicto("2026-09-01")
        apagado = veredicto("2099-01-01")

    if con_mecanismo != 1:
        return False, "con el corte puesto R1 ya salía verde: no medía nada desde el principio"
    if apagado == 1:
        return False, "con el corte en 2099 sigue bloqueando: el FAIL no viene del corte"
    return True, "corte 2026-09-01 → exit 1 · corte 2099-01-01 → exit 0"


# ------------------------------------------------------- 2 · puerta_recibo_revisor
def contraprueba_recibo_revisor():
    """Vaciada la puerta en la COPIA del taller, el cierre sin revisión ya no se para."""
    class ConLaPuertaVaciada(dientes.DientesReciboDelRevisorTest):
        def setUp(self):
            super().setUp()
            dientes.vaciar_en_la_copia(self.unidad, "puerta_recibo_revisor", "return [], []")

    rojo, motivo = correr_uno(ConLaPuertaVaciada, "test_dientes_R_REV_01_bloquea")
    return rojo, motivo or "el cierre siguió parándose con la puerta vaciada"


# ------------------------------------------------------- 3 · junta_tope_directo
def contraprueba_tope_directo():
    with mock.patch.object(lint_juntas, "junta_tope_directo", lambda raiz: []):
        rojo, motivo = correr_uno(dientes.DientesTopeDelDirectoTest,
                                  "test_dientes_R_DIR_01_bloquea")
    return rojo, motivo or "el tope del directo lo denuncia algo que no es `junta_tope_directo`"


# ------------------------------------------------------- 4 · cmd_comprobar
def contraprueba_aviso_del_metodo():
    with mock.patch.object(herramienta, "cmd_comprobar", lambda ws, args: 0):
        rojo, motivo = correr_uno(dientes.DientesAvisoDelMetodoTest,
                                  "test_dientes_R_AVI_01_bloquea")
    return rojo, motivo or "el aviso de versión lo imprime alguien que no es `cmd_comprobar`"


# ------------------------------------------------------- 5 · salida_hook_stop
def contraprueba_canario():
    with mock.patch.object(canario, "salida_hook_stop",
                           lambda informe, config, **kwargs: {"continue": True}):
        rojo, motivo = correr_uno(dientes.DientesCanarioTest,
                                  "test_dientes_R_CAN_01_bloquea")
    return rojo, motivo or "el aviso de fin de turno no sale de `salida_hook_stop`"


MECANISMOS = (
    ("lint_invariantes.py: el corte", contraprueba_corte),
    ("unidad.py:puerta_recibo_revisor", contraprueba_recibo_revisor),
    ("lint_juntas.py:junta_tope_directo", contraprueba_tope_directo),
    ("herramienta.py:cmd_comprobar", contraprueba_aviso_del_metodo),
    ("canario.py:salida_hook_stop", contraprueba_canario),
)


def main():
    print("Contraprueba de no vacuidad · se apaga cada mecanismo y se exige ROJO\n")
    vacuos = []
    for nombre, prueba in MECANISMOS:
        try:
            rojo, motivo = prueba()
        except Exception as exc:                      # noqa: BLE001 - un fallo aquí es dato
            rojo, motivo = False, f"la contraprueba reventó: {type(exc).__name__}: {exc}"
        marca = "rojo esperado" if rojo else "VACUO       "
        print(f"  {marca}  {nombre}")
        print(f"                 {motivo}")
        if not rojo:
            vacuos.append(nombre)

    total = len(MECANISMOS)
    print(f"\nVEREDICTO: {total - len(vacuos)}/{total} mecanismos con dientes")
    if vacuos:
        print(f"  {len(vacuos)} test(s) siguen VERDES con su mecanismo apagado: no miden lo "
              f"que dicen medir — {', '.join(vacuos)}")
        print("  SALIDA: arregla el test para que dependa del mecanismo, o retíralo; un test "
              "vacuo ocupa el sitio del que sí habría avisado (ADR-030)")
        return 1
    print("  ninguno pasa con su mecanismo apagado: la línea base mide lo que dice medir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
