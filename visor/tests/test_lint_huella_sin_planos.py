"""Bug 053 — `lint_metodo.huella_planos_actual()` con una actividad «sin empezar».

El mapa declara actividades y cada una tiene su `actividades/<id>/planos.json`… salvo las
que aún están sin empezar. `peticion.py` (bug 026) las salta con aviso; la copia gemela de
`lint_metodo.py` reventaba y devolvía None, y `§5` comparaba el recibo de aprobación contra
ese None: FAIL falso «flujos terminal sin recibo aprobado» con la firma del usuario intacta.
Las dos copias tienen que dar la MISMA huella sobre el mismo workspace: es lo que el recibo
firma y lo que el linter contrasta.
"""

import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts"


def cargar(nombre, raiz):
    """Solo la función `huella_planos_actual` del script, aislada de su módulo.

    `lint_metodo.py` lintea entero al importarse (es un script, no una librería), así que se
    recorta la función con `ast` y se ejecuta con el `RAIZ` del workspace temporal: es la misma
    función que corre en producción, byte a byte."""
    import ast, hashlib, json as _json, sys as _sys, types
    fuente = (SCRIPTS / f"{nombre}.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    nodo = next(n for n in arbol.body if isinstance(n, ast.FunctionDef)
                and n.name == "huella_planos_actual")
    espacio = {"RAIZ": raiz, "json": _json, "hashlib": hashlib, "sys": _sys, "Path": Path}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), str(SCRIPTS / f"{nombre}.py"), "exec"), espacio)
    return types.SimpleNamespace(huella_planos_actual=espacio["huella_planos_actual"])


class HuellaConActividadSinPlanosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-huella-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        planos = self.raiz / "docs/02-flujos/planos"
        (planos / "actividades/hecha").mkdir(parents=True)
        (planos / "planos.json").write_text(json.dumps({
            "actividades": [{"id": "hecha", "estado": "especificada"},
                            {"id": "sin-empezar", "estado": "sin empezar"}]
        }), encoding="utf-8")
        (planos / "actividades/hecha/planos.json").write_text(
            json.dumps({"requisitos": [{"id": "R-1"}]}), encoding="utf-8")

    def test_el_linter_no_devuelve_none_por_una_actividad_sin_planos(self):
        lint = cargar("lint_metodo", self.raiz)
        self.assertIsNotNone(lint.huella_planos_actual(),
                             "una actividad sin empezar no puede dejar al linter sin huella")

    def test_las_dos_copias_dan_la_misma_huella(self):
        lint = cargar("lint_metodo", self.raiz)
        peticion = cargar("peticion", self.raiz)
        self.assertEqual(lint.huella_planos_actual(), peticion.huella_planos_actual())


if __name__ == "__main__":
    unittest.main()
