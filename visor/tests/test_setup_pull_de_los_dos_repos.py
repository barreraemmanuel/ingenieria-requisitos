"""Unidad 119: al arrancar, `setup.py` trae también el meta-repo (pull de los DOS repos).

Hasta la 119 `setup.py` solo ponía `main/` (código) en `origin/<rama>` por fast-forward; el
meta-repo —ESTADO.md, fichas, peticiones— se quedaba como estuviera, y una sesión abierta en
otra máquina arrancaba con papeles viejos. R1: ff cuando se puede; R2: si no es ff o hay
cambios sin commitear, no se toca nada, se dice cómo resolverlo y el arranque sigue; sin
remoto, una línea y sigue. Integración: git real sobre repos temporales.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[2]
PLANTILLA = RAIZ_REPO / "plantilla"
SCRIPTS = PLANTILLA / "docs/00-metodo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("setup_plantilla", PLANTILLA / "setup.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       encoding="utf-8", env=ENV)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stdout}{r.stderr}"
    return r.stdout.strip()


class PullDelMetaRepoTest(unittest.TestCase):
    """`remoto` (bare) ← `mio` (el workspace) y `otro` (otra máquina que empuja)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="setup-119-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.remoto = base / "remoto.git"
        git(base, "init", "-q", "--bare", "-b", "main", str(self.remoto))
        self.mio = base / "mio"
        git(base, "clone", "-q", str(self.remoto), str(self.mio))
        git(self.mio, "checkout", "-q", "-b", "main")
        (self.mio / "ESTADO.md").write_text("# v1\n", encoding="utf-8")
        git(self.mio, "add", "ESTADO.md"); git(self.mio, "commit", "-q", "-m", "v1")
        git(self.mio, "push", "-q", "-u", "origin", "main")
        self.otro = base / "otro"
        git(base, "clone", "-q", str(self.remoto), str(self.otro))

    def empuja_el_otro(self, texto="# v2\n"):
        (self.otro / "ESTADO.md").write_text(texto, encoding="utf-8")
        git(self.otro, "commit", "-q", "-am", "v2 desde otra máquina")
        git(self.otro, "push", "-q", "origin", "main")
        return git(self.otro, "rev-parse", "--short", "HEAD")

    def actualizar(self):
        lineas = []
        resultado = setup.actualizar_meta_repo(self.mio, imprimir=lineas.append)
        return resultado, "\n".join(lineas)

    # --- R1 -----------------------------------------------------------------
    def test_ff_trae_lo_que_empujo_otra_maquina(self):
        sha = self.empuja_el_otro()
        resultado, salida = self.actualizar()
        self.assertEqual(resultado, "actualizado", salida)
        self.assertIn(sha, salida)
        self.assertEqual((self.mio / "ESTADO.md").read_text(encoding="utf-8"), "# v2\n")

    def test_sin_novedades_dice_al_dia(self):
        resultado, salida = self.actualizar()
        self.assertEqual(resultado, "al_dia", salida)
        self.assertIn("al día", salida)

    # --- R2 -----------------------------------------------------------------
    def test_con_cambios_sin_commitear_no_toca_nada_y_lo_dice(self):
        self.empuja_el_otro()
        (self.mio / "ESTADO.md").write_text("# editado a mano\n", encoding="utf-8")
        resultado, salida = self.actualizar()
        self.assertEqual(resultado, "no_tocado", salida)
        self.assertIn("sin commitear", salida)
        self.assertIn("SALIDA", salida)
        self.assertEqual((self.mio / "ESTADO.md").read_text(encoding="utf-8"), "# editado a mano\n")

    def test_si_divergio_no_fuerza_nada_y_da_el_comando(self):
        self.empuja_el_otro()
        (self.mio / "local.md").write_text("mío\n", encoding="utf-8")
        git(self.mio, "add", "local.md"); git(self.mio, "commit", "-q", "-m", "commit local")
        antes = git(self.mio, "rev-parse", "HEAD")
        resultado, salida = self.actualizar()
        self.assertEqual(resultado, "no_tocado", salida)
        self.assertIn("fast-forward", salida)
        self.assertIn("git pull --rebase", salida)
        self.assertEqual(git(self.mio, "rev-parse", "HEAD"), antes)

    def test_sin_remoto_una_linea_y_sigue(self):
        git(self.mio, "remote", "remove", "origin")
        resultado, salida = self.actualizar()
        self.assertEqual(resultado, "sin_remoto", salida)
        self.assertIn("sin remoto", salida)

    def test_main_lo_llama_para_el_meta_repo(self):
        fuente = (PLANTILLA / "setup.py").read_text(encoding="utf-8")
        cuerpo_main = fuente[fuente.index("def main():"):]
        self.assertIn("actualizar_meta_repo(RAIZ", cuerpo_main,
                      "R1: setup.py main() no actualiza el meta-repo")


if __name__ == "__main__":
    unittest.main()
