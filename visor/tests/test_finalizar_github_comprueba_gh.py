"""Bug 158: `finalizar.py --github` empujaba sin comprobar nada y el primer push moría
con «Password authentication is not supported» tras un `gh auth login` recién hecho
(faltaba `gh auth setup-git`). Antes de empujar se comprueban, en este orden y cada una
con su salida escrita: gh instalado · sesión iniciada · credential helper de gh."""

import importlib.util
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent.parent
if str(RAIZ / "visor") not in sys.path:
    sys.path.insert(0, str(RAIZ / "visor"))


def _cargar():
    spec = importlib.util.spec_from_file_location("finalizar_158", RAIZ / "visor/finalizar.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class Terminal:
    """Simula la máquina: qué hay instalado, qué contesta cada comando, qué se ejecutó."""

    def __init__(self, *, gh=True, sesion=True, helper="!/usr/bin/gh auth git-credential"):
        self.gh, self.sesion, self.helper = gh, sesion, helper
        self.ejecutados = []

    def which(self, programa):
        return "/usr/bin/gh" if (programa == "gh" and self.gh) else None

    def ejecutar(self, comando, cwd=None):
        self.ejecutados.append(list(comando))
        if comando[:3] == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(comando, 0 if self.sesion else 1,
                                               "" if self.sesion else "not logged in")
        if comando[:3] == ["git", "config", "--get-all"]:
            return subprocess.CompletedProcess(comando, 0 if self.helper else 1, self.helper)
        return subprocess.CompletedProcess(comando, 0, "")

    @property
    def empujo(self):
        return any(c[:2] == ["git", "push"] for c in self.ejecutados)


class ComprobacionesAntesDePublicarTest(unittest.TestCase):

    def setUp(self):
        self.finalizar = _cargar()

    def publicar(self, terminal):
        f = self.finalizar
        # `f.shutil` ES el módulo global de la stdlib: se parchea con `mock.patch.object`
        # y se restaura al acabar (ronda 2 del revisor: dejarlo pisado rompía otros tests
        # de la suite que llaman a `shutil.which("git")`). `ejecutar` es del módulo recién
        # cargado en setUp, así que morirá con él.
        parche = mock.patch.object(shutil, "which", terminal.which)
        parche.start()
        self.addCleanup(parche.stop)
        f.ejecutar = terminal.ejecutar
        f.commit_inicial_o_aviso = lambda repo: None
        f.configurar_remoto = lambda repo, url: None
        f.commit_si_hay_cambios = lambda repo, mensaje, incluir_todo=False: None
        workspace = Path(self.id())  # no se toca el disco: repos.yaml no se lee si se para antes
        return f.publicar_github(workspace, "cuenta", "proyecto")

    def test_sin_gh_para_antes_de_empujar_y_dice_como_instalarlo(self):
        terminal = Terminal(gh=False)
        with self.assertRaises(SystemExit) as parada:
            self.publicar(terminal)
        self.assertIn("gh", str(parada.exception))
        self.assertIn("--sin-github", str(parada.exception))
        self.assertFalse(terminal.empujo)

    def test_sin_sesion_manda_gh_auth_login_y_setup_git(self):
        terminal = Terminal(sesion=False)
        with self.assertRaises(SystemExit) as parada:
            self.publicar(terminal)
        self.assertIn("gh auth login", str(parada.exception))
        self.assertIn("gh auth setup-git", str(parada.exception))
        self.assertFalse(terminal.empujo)

    def test_sin_credential_helper_de_gh_manda_setup_git_antes_del_primer_push(self):
        """El caso de campo: `gh auth login` hecho, push muerto por «Password authentication»."""
        for helper in ("", "osxkeychain", "manager"):
            with self.subTest(helper=helper):
                terminal = Terminal(helper=helper)
                with self.assertRaises(SystemExit) as parada:
                    self.publicar(terminal)
                self.assertIn("gh auth setup-git", str(parada.exception))
                self.assertFalse(terminal.empujo)

    def test_las_tres_comprobaciones_van_en_orden_antes_del_primer_push(self):
        terminal = Terminal()
        with self.assertRaises((SystemExit, FileNotFoundError)):
            # Con todo en orden llega a leer repos.yaml, que aquí no existe: eso ya es
            # DESPUÉS del primer push, que es lo que este test mide.
            self.publicar(terminal)
        ordenes = [c[:3] for c in terminal.ejecutados]
        estado = ordenes.index(["gh", "auth", "status"])
        helper = ordenes.index(["git", "config", "--get-all"])
        push = next(i for i, c in enumerate(ordenes) if c[:2] == ["git", "push"])
        self.assertLess(estado, helper)
        self.assertLess(helper, push)

    def test_el_runbook_nombra_los_tres_pasos_en_el_bloque_de_publicacion(self):
        texto = (RAIZ / "RUNBOOK/arranque.md").read_text(encoding="utf-8")
        bloque = texto[texto.index("**Si dice que sí**"):]
        for paso in ("gh --version", "gh auth login", "gh auth setup-git"):
            self.assertIn(paso, bloque, paso)


if __name__ == "__main__":
    unittest.main()
