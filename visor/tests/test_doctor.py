"""revisar_plataforma() de visor/doctor.py: desde la unidad 013 (bug), ninguna plataforma
comprueba ni receta un mecanismo de sandbox de SO — la unidad 012 lo quitó del lanzador
(ejecucion.py) y la promesa de WSL2/bubblewrap que dependía de él quedó falsa. Windows solo
avisa de lo que sigue siendo real: bash y el alias python3."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DOCTOR_PATH = RAIZ / "visor/doctor.py"

_spec = importlib.util.spec_from_file_location("doctor_bajo_test", DOCTOR_PATH)
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)


class RevisarPlataformaTest(unittest.TestCase):
    def setUp(self):
        self._platform_original = sys.platform
        self._which_original = doctor.shutil.which
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        sys.platform = self._platform_original
        doctor.shutil.which = self._which_original

    # R1 (bug 013): win32 ya NO receta WSL2/sandbox --------------------------

    def test_win32_no_menciona_wsl2_ni_sandbox(self):
        sys.platform = "win32"
        # `path=` porque buscar_bash() usa shutil.which con esa firma.
        doctor.shutil.which = lambda nombre, path=None: "/usr/bin/" + nombre

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "OK")
        texto = detalle + " " + consecuencia
        self.assertNotIn("WSL2", texto)
        self.assertNotIn("sandbox", texto)
        self.assertNotIn("VERSION 2", texto)

    def test_win32_sin_bash_sigue_avisando_bash(self):
        """Lo que seguía siendo real (bash/python3 vienen de Git for Windows, no del
        sandbox) no se pierde al quitar la promesa falsa de WSL2."""
        sys.platform = "win32"
        # Ni en el PATH ni junto a git: aquí bash de verdad no está.
        doctor.shutil.which = lambda nombre, path=None: (
            None if nombre in ("bash", "git") else "/usr/bin/" + nombre
        )

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "WARN")
        self.assertIn("bash", consecuencia)
        self.assertNotIn("WSL2", consecuencia)

    def test_win32_encuentra_el_bash_de_git_for_windows_fuera_del_PATH(self):
        """El PATH de Windows lleva `Git\\cmd` (solo git.exe), no `Git\\bin`: which("bash")
        daba None y el doctor avisaba de una falta que no existía, mientras el despacho
        se negaba a correr hooks con el bash que tenía al lado. Se busca junto a git."""
        sys.platform = "win32"
        temporal = tempfile.TemporaryDirectory(prefix="git-for-windows-")
        self.addCleanup(temporal.cleanup)
        raiz = Path(temporal.name)
        (raiz / "cmd").mkdir(parents=True)
        (raiz / "bin").mkdir(parents=True)
        (raiz / "cmd" / "git.exe").write_text("", encoding="utf-8")
        (raiz / "bin" / "bash.exe").write_text("", encoding="utf-8")
        doctor.shutil.which = lambda nombre, path=None: (
            str(raiz / "cmd" / "git.exe") if nombre == "git"
            else None if nombre == "bash"
            else "/usr/bin/" + nombre
        )

        self.assertEqual(doctor.buscar_bash(), str(raiz / "bin" / "bash.exe"))
        estado, _detalle, consecuencia = doctor.revisar_plataforma()
        self.assertEqual(estado, "OK")
        self.assertNotIn("bash", consecuencia)

    def test_win32_sin_python3_sigue_avisando_el_alias(self):
        sys.platform = "win32"
        doctor.shutil.which = lambda nombre, path=None: (
            None if nombre == "python3" else "/usr/bin/" + nombre
        )

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "WARN")
        self.assertIn("python3", consecuencia)
        self.assertNotIn("WSL2", consecuencia)

    # R2 (bug 013): linux/darwin ya NO comprueban ningún mecanismo de sandbox --

    def test_linux_no_comprueba_mecanismo_de_sandbox(self):
        sys.platform = "linux"

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "OK")
        self.assertNotIn("bubblewrap", detalle + consecuencia)
        self.assertNotIn("bwrap", detalle + consecuencia)
        self.assertNotIn("srt", detalle + consecuencia)

    def test_darwin_no_comprueba_mecanismo_de_sandbox(self):
        sys.platform = "darwin"

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "OK")
        self.assertNotIn("sandbox-exec", detalle + consecuencia)
        self.assertNotIn("srt", detalle + consecuencia)


class LosTresTextosYaNoNombranWSL2Test(unittest.TestCase):
    """R3 (bug 014): la misma verdad en manual, RUNBOOK y sandbox.md de la plantilla — sin
    sandbox de SO desde la unidad 012, ninguno de los tres debe recetar WSL2/bubblewrap."""

    def test_manual_faq_funciona_en_windows_no_nombra_wsl2(self):
        texto = (RAIZ / "manual-ingenieria-requisitos.html").read_text(encoding="utf-8")
        inicio = texto.index("¿Funciona en Windows?")
        fragmento = texto[inicio:inicio + 1500]
        self.assertNotIn("WSL2", fragmento)
        self.assertNotIn("VERSION 2", fragmento)
        self.assertIn("Windows", fragmento)  # sigue respondiendo la pregunta

    def test_runbook_no_nombra_wsl2_ni_version_2(self):
        texto = (RAIZ / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertNotIn("WSL2", texto)
        self.assertNotIn("VERSION 2", texto)
        self.assertNotIn("bubblewrap", texto)

    def test_sandbox_md_no_nombra_wsl2_ni_version_2(self):
        texto = (RAIZ / "plantilla/docs/00-metodo/sandbox.md").read_text(encoding="utf-8")
        self.assertNotIn("WSL2", texto)
        self.assertNotIn("VERSION 2", texto)
        self.assertNotIn("win32", texto)

    def test_sandbox_md_describe_el_mecanismo_real_sin_sandbox_de_so(self):
        """No basta con que no mencione WSL2: tiene que decir la verdad de hoy — que ya
        no hay sandbox de SO, no quedarse en blanco. Mencionar sandbox-exec/bwrap para
        explicar que se retiraron sigue siendo honesto; lo que no puede pasar es que el
        documento SIGA recetando un mecanismo por plataforma como si aplicara hoy."""
        texto = (RAIZ / "plantilla/docs/00-metodo/sandbox.md").read_text(encoding="utf-8")
        self.assertNotIn("Mecanismos por plataforma", texto)
        self.assertIn("no impone", texto.lower())
        self.assertIn("cwd", texto)


if __name__ == "__main__":
    unittest.main()
