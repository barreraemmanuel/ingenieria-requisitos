"""Bug 044 (ronda 2) — el `git clone` también necesita `core.longpaths` en Windows.

`ajustar_rutas_largas()` configuraba el repo DESPUÉS de clonarlo, pero es el clon el que
materializa el árbol profundo: con un `node_modules` corriente muere con «Filename too long»
antes de que el ajuste exista. `git -c core.longpaths=true clone …` lo aplica al propio clon.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent.parent


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class OpcionesDeClonTest(unittest.TestCase):
    def setUp(self):
        if str(RAIZ / "visor") not in sys.path:
            sys.path.insert(0, str(RAIZ / "visor"))
        self.bootstrap = cargar("bootstrap_044", RAIZ / "visor" / "bootstrap.py")
        self.setup = cargar("setup_044", RAIZ / "plantilla" / "setup.py")

    def test_en_windows_el_clon_lleva_longpaths(self):
        for modulo in (self.bootstrap, self.setup):
            with mock.patch.object(modulo.sys, "platform", "win32"):
                self.assertEqual(modulo.opciones_git_clone(), ["-c", "core.longpaths=true"],
                                 modulo.__name__)

    def test_fuera_de_windows_no_se_añade_nada(self):
        for modulo in (self.bootstrap, self.setup):
            with mock.patch.object(modulo.sys, "platform", "darwin"):
                self.assertEqual(modulo.opciones_git_clone(), [], modulo.__name__)

    def test_los_dos_clones_usan_las_opciones(self):
        # El cableado: no basta con que exista el helper, hay que pasárselo al clone.
        fuente_b = (RAIZ / "visor" / "bootstrap.py").read_text(encoding="utf-8")
        fuente_s = (RAIZ / "plantilla" / "setup.py").read_text(encoding="utf-8")
        self.assertTrue('*opciones_git_clone(), "clone", remoto_codigo' in fuente_b, "bootstrap.py no pasa las opciones al clone")
        self.assertTrue('*opciones_git_clone(), "clone", "--branch"' in fuente_s, "setup.py no pasa las opciones al clone")


if __name__ == "__main__":
    unittest.main()
