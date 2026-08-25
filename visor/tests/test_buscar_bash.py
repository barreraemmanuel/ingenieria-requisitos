"""`buscar_bash()` — el gemelo de PRODUCCIÓN, y que los dos gemelos decidan igual.

La primera ronda del bug 042 fusionó `workspace_paths.buscar_bash()` sin un solo test:
lo único probado fue la copia local de `visor/doctor.py`, que es la que *avisa*, no la
que arregla el daño. Los consumidores reales son `unidad.orden_para_hook` (el hook de
preparación del worktree, que en Windows no corría NUNCA) y `lint_deploy.ejecutar_control`
(el gate que no comprobaba los scripts de shell). Esos dos son los que este fichero fija.

Windows se **simula**: `os.name` a "nt" en el módulo bajo prueba (ver
`ayuda_windows.OsDeWindows`, que explica por qué no se parchea el global) y un
`Git for Windows` de mentira montado en un temporal — `<raiz>/cmd/git` en el PATH,
`<raiz>/bin/bash.exe` fuera de él, que es exactamente la disposición real.
"""
import contextlib
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ayuda_windows  # noqa: E402 - módulo hermano de la suite

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import workspace_paths  # noqa: E402

_spec = importlib.util.spec_from_file_location("doctor_buscar_bash", RAIZ / "visor/doctor.py")
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)


def ejecutable(ruta):
    """Un fichero que `shutil.which` acepte: en POSIX exige el bit de ejecución."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("", encoding="utf-8")
    ruta.chmod(ruta.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return ruta


class BuscarBashTest(unittest.TestCase):
    """El gemelo de producción: plantilla/docs/00-metodo/scripts/workspace_paths.py."""

    def setUp(self):
        # `.resolve()`: en macOS el temporal es /var/… → /private/var/…, y which_sin_cwd
        # compara el PATH con `os.getcwd()`, que sí viene resuelto. Sin esto el test
        # mediría el symlink de /var, no la regla.
        self.raiz = Path(tempfile.mkdtemp(prefix="git-for-windows-")).resolve()
        self.addCleanup(shutil.rmtree, self.raiz, True)

    def con_path(self, *carpetas):
        return mock.patch.dict(os.environ, {"PATH": os.pathsep.join(str(c) for c in carpetas)})

    # Los módulos a los que se les simula Windows. La subclase añade el doctor.
    MODULOS = (workspace_paths,)

    @contextlib.contextmanager
    def como_windows(self):
        with contextlib.ExitStack() as pila:
            for modulo in self.MODULOS:
                pila.enter_context(
                    mock.patch.object(modulo, "os", ayuda_windows.OsDeWindows()))
            yield

    # El hallazgo del bug ---------------------------------------------------

    def test_windows_encuentra_el_bash_junto_al_git_aunque_no_este_en_el_PATH(self):
        """El PATH de Windows lleva `Git\\cmd`, que solo tiene git.exe. `which("bash")`
        da None y bash está ahí al lado, en `Git\\bin`."""
        ejecutable(self.raiz / "cmd" / "git")
        ejecutable(self.raiz / "bin" / "bash.exe")

        with self.con_path(self.raiz / "cmd"), self.como_windows():
            self.assertEqual(workspace_paths.buscar_bash(),
                             str(self.raiz / "bin" / "bash.exe"))

    def test_windows_tambien_mira_el_bash_de_usr_bin(self):
        """Git for Windows trae dos: `Git\\bin\\bash.exe` y `Git\\usr\\bin\\bash.exe`.
        Si el primero no está, el segundo sirve igual."""
        ejecutable(self.raiz / "cmd" / "git")
        ejecutable(self.raiz / "usr" / "bin" / "bash.exe")

        with self.con_path(self.raiz / "cmd"), self.como_windows():
            self.assertEqual(workspace_paths.buscar_bash(),
                             str(self.raiz / "usr" / "bin" / "bash.exe"))

    # Los límites: no se inventa nada ---------------------------------------

    def test_sin_git_no_hay_de_donde_deducir_y_devuelve_None(self):
        """El rodeo se apoya en el git que sí se encontró. Sin git no hay instalación
        de la que fiarse y NO se codifica ninguna ruta absoluta a mano."""
        ejecutable(self.raiz / "bin" / "bash.exe")     # existe, pero nadie lo señala

        with self.con_path(self.raiz / "vacio"), self.como_windows():
            self.assertIsNone(workspace_paths.buscar_bash())

    def test_con_git_pero_sin_bash_al_lado_devuelve_None(self):
        ejecutable(self.raiz / "cmd" / "git")

        with self.con_path(self.raiz / "cmd"), self.como_windows():
            self.assertIsNone(workspace_paths.buscar_bash())

    def test_el_bash_del_PATH_gana_y_no_se_toca_git(self):
        del_path = ejecutable(self.raiz / "cmd" / "bash")
        ejecutable(self.raiz / "cmd" / "git")
        ejecutable(self.raiz / "bin" / "bash.exe")

        with self.con_path(self.raiz / "cmd"), self.como_windows():
            self.assertEqual(workspace_paths.buscar_bash(), str(del_path))

    def test_fuera_de_windows_no_se_deduce_nada_del_git(self):
        """El rodeo existe porque Git for Windows pone bash fuera del PATH. En POSIX
        el PATH es la única verdad: si bash no está, no está."""
        ejecutable(self.raiz / "cmd" / "git")
        ejecutable(self.raiz / "bin" / "bash.exe")

        with self.con_path(self.raiz / "cmd"):         # os.name real, POSIX aquí
            self.assertIsNone(workspace_paths.buscar_bash())

    def test_un_bash_versionado_en_el_cwd_no_gana(self):
        """En Windows el directorio actual se antepone al PATH. El cwd de un agente es
        el repo de código: un `bash` versionado ahí se ejecutaría fuera de todo control.
        Por eso `which_sin_cwd` y no `shutil.which` a secas."""
        ejecutable(self.raiz / "bash")
        cwd_previo = os.getcwd()
        os.chdir(self.raiz)
        self.addCleanup(os.chdir, cwd_previo)

        with self.con_path(self.raiz), self.como_windows():
            self.assertIsNone(workspace_paths.which_sin_cwd("bash"))
            self.assertIsNone(workspace_paths.buscar_bash())


class LosDosGemelosDecidenIgualTest(BuscarBashTest):
    """`visor/doctor.py` lleva una COPIA de `buscar_bash()` a propósito: tiene que dar
    diagnóstico en un clone incompleto, y un import de `plantilla/` lo mataría justo en
    el caso que existe para diagnosticar. Lo que la duplicación no puede permitirse es
    divergir: si el doctor dice «OK Plataforma» y `unidad.orden_para_hook` rechaza ese
    mismo bash, el diagnóstico miente. Este test corre los MISMOS escenarios contra la
    copia del doctor y exige el mismo veredicto.

    Hereda los casos de arriba redirigiendo el módulo bajo prueba: no hay una segunda
    lista de escenarios que se pueda quedar atrás de la primera.
    """

    MODULOS = (workspace_paths, doctor)

    def setUp(self):
        super().setUp()
        # Cada test de la clase base llama a workspace_paths.buscar_bash(): se
        # sustituye por una función que llama a las DOS y exige que coincidan.
        original = workspace_paths.buscar_bash
        original_which = workspace_paths.which_sin_cwd

        def ambas():
            mio, del_doctor = original(), doctor.buscar_bash()
            self.assertEqual(del_doctor, mio, "los dos gemelos deben decidir igual")
            return mio

        def ambas_which(programa):
            mio, del_doctor = original_which(programa), doctor.which_sin_cwd(programa)
            self.assertEqual(del_doctor, mio, "los dos gemelos deben decidir igual")
            return mio

        mock.patch.object(workspace_paths, "buscar_bash", ambas).start()
        mock.patch.object(workspace_paths, "which_sin_cwd", ambas_which).start()
        self.addCleanup(mock.patch.stopall)


if __name__ == "__main__":
    unittest.main()
