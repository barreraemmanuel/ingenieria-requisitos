"""Bug 039 — en Windows `lint_deploy.py` lanzaba los gates con el bash equivocado y la ruta mal.

`ejecutar_control()` cogía el primer `bash` del PATH (en un Windows con WSL, el de
`System32`, que no entiende las rutas del anfitrión) y le pasaba `str(ruta)` con barras
invertidas, que bash se come: `D:Proyectos...` → exit 127 sin ejecutar nada. Se aísla la
función con `ast` (el script lintea al importarse) y se simula Windows con dobles.
"""

import ast
import types
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts/lint_deploy.py"


def cargar(os_doble, which_doble, buscar_bash_doble, run_doble, raiz):
    fuente = SCRIPT.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    nombres = {"ejecutar_control", "ruta_para_bash", "bash_del_anfitrion"}
    nodos = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name in nombres]
    mensajes = []
    espacio = {
        "os": os_doble, "Path": Path, "RAIZ": raiz,
        "subprocess": types.SimpleNamespace(run=run_doble, TimeoutExpired=Exception),
        "workspace_paths": types.SimpleNamespace(buscar_bash=buscar_bash_doble,
                                                 which_sin_cwd=which_doble),
        "fail": lambda m: mensajes.append(("FAIL", m)), "ok": lambda m: mensajes.append(("OK", m)),
        "warn": lambda m: mensajes.append(("WARN", m)), "time": types.SimpleNamespace(time=lambda: 0.0),
    }
    exec(compile(ast.Module(body=nodos, type_ignores=[]), str(SCRIPT), "exec"), espacio)
    return espacio, mensajes


class RutaComoEnWindows:
    """Un fichero real del tmpdir cuyo `str()` es una ruta de Windows con barras invertidas.

    `open()` e `is_file()` van al fichero real (vía `__fspath__`); `str()` es lo que
    `ejecutar_control` pasaba a bash en Windows. Así el test muerde el cableado de
    `ruta_para_bash` y no solo la función aislada."""

    def __init__(self, real):
        self.real = Path(real)
        self.name = self.real.name

    def __fspath__(self):
        return str(self.real)

    def is_file(self):
        return self.real.is_file()

    def __str__(self):
        return "D:\\Proyectos\\demo\\scripts\\ci\\" + self.name


class BashYRutasEnWindowsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-deploy-win-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.gate = self.raiz / "scripts" / "ci" / "full-suite"
        self.gate.parent.mkdir(parents=True)
        self.gate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.llamadas = []

    def run_doble(self, orden, **kw):
        self.llamadas.append(list(orden))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def windows(self):
        return types.SimpleNamespace(name="nt", environ={})

    def test_la_ruta_del_gate_va_en_formato_posix_no_con_barras_invertidas(self):
        espacio, _ = cargar(self.windows(), lambda n: None,
                            lambda: "C:\\Program Files\\Git\\bin\\bash.exe", self.run_doble, self.raiz)
        self.assertIn("ruta_para_bash", set(espacio), "falta la conversión de ruta para bash")
        self.assertEqual(espacio["ruta_para_bash"]("D:\\Proyectos\\demo\\scripts\\ci\\full-suite"),
                         "D:/Proyectos/demo/scripts/ci/full-suite")

    def test_no_se_usa_el_bash_de_wsl_si_hay_git_for_windows(self):
        wsl = "C:\\Windows\\System32\\bash.exe"
        git = "C:\\Program Files\\Git\\cmd\\git.exe"
        # Git for Windows «instalado» en el temporal: …\Git\bin\bash.exe junto al git encontrado
        raiz_git = self.raiz / "Git"
        (raiz_git / "cmd").mkdir(parents=True); (raiz_git / "bin").mkdir()
        git = str(raiz_git / "cmd" / "git.exe"); (raiz_git / "bin" / "bash.exe").write_text("", encoding="utf-8")
        espacio, mensajes = cargar(self.windows(), lambda n: git if n == "git" else None,
                                   lambda: wsl, self.run_doble, self.raiz)
        espacio["ejecutar_control"]("full-suite", RutaComoEnWindows(self.gate), self.raiz)
        self.assertTrue(self.llamadas, mensajes)
        self.assertNotIn("System32", self.llamadas[0][0], "se eligió el bash de WSL")
        self.assertTrue(self.llamadas[0][0].endswith("bash.exe"))
        self.assertEqual(self.llamadas[0][1], "D:/Proyectos/demo/scripts/ci/full-suite",
                         "la ruta llegó a bash con barras invertidas")

    def test_sin_bash_de_git_se_dice_en_claro_y_no_se_lanza_nada(self):
        espacio, mensajes = cargar(self.windows(), lambda n: None, lambda: "C:\\Windows\\System32\\bash.exe",
                                   self.run_doble, self.raiz)
        espacio["ejecutar_control"]("full-suite", self.gate, self.raiz)
        self.assertFalse(self.llamadas)
        self.assertTrue(any(n == "FAIL" and "Git for Windows" in m for n, m in mensajes), mensajes)


if __name__ == "__main__":
    unittest.main()
