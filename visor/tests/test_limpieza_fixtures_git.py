"""Límites de la limpieza de temporales del ensayo de actualización."""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_peticion_bootstrap_actualizar import borrar_tmp_silencioso


CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LimpiezaFixturesGitTest(unittest.TestCase):
    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp(prefix="limpieza-git-"))
        self.addCleanup(self.limpiar_restos)

    def limpiar_restos(self):
        # La prueba roja también debe retirar sus propios objetos Git.
        def writable(function, path, _error):
            os.chmod(path, stat.S_IWRITE)
            function(path)

        if self.raiz.exists():
            shutil.rmtree(self.raiz, onerror=writable)

    def test_git_real_readonly_se_retira_entero(self):
        repo = self.raiz / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True,
                       capture_output=True, creationflags=CREATIONFLAGS)
        objeto_git = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                                    input=b"objeto real\n", check=True, capture_output=True,
                                    creationflags=CREATIONFLAGS).stdout.decode("ascii").strip()
        objetos = [p for p in (repo / ".git/objects").rglob("*") if p.is_file()]
        self.assertTrue(objetos)
        for objeto in objetos:
            objeto.chmod(stat.S_IREAD)
        self.assertTrue(any(not (p.stat().st_mode & stat.S_IWRITE) for p in objetos))

        borrar_tmp_silencioso(repo)

        self.assertFalse(repo.exists(), "quedaron objetos Git readonly tras el cleanup")
        print(f"Git real: objeto={objeto_git}; readonly={len(objetos)}; temporal_ausente=True")

    def test_ruta_ausente_y_arbol_ordinario(self):
        borrar_tmp_silencioso(self.raiz / "ausente")
        arbol = self.raiz / "ordinario"
        arbol.mkdir()
        (arbol / "dato").write_bytes(b"propio")
        borrar_tmp_silencioso(arbol)
        self.assertFalse(arbol.exists())

    def test_destino_externo_conserva_bytes_y_atributos(self):
        externo = self.raiz / "externo"
        externo.mkdir()
        dato = externo / "dato"
        dato.write_bytes(b"fuera del temporal")
        dato.chmod(stat.S_IREAD)
        modo = dato.stat().st_mode
        atributos = getattr(dato.stat(), "st_file_attributes", None)
        temporal = self.raiz / "temporal"
        temporal.mkdir()
        enlace = temporal / "enlace"
        if os.name == "nt":
            creado = subprocess.run(["cmd", "/c", "mklink", "/J", str(enlace), str(externo)],
                                    capture_output=True, creationflags=CREATIONFLAGS)
            self.assertEqual(creado.returncode, 0, creado.stderr)
        else:
            enlace.symlink_to(externo, target_is_directory=True)

        borrar_tmp_silencioso(temporal)

        self.assertFalse(temporal.exists())
        self.assertEqual(dato.read_bytes(), b"fuera del temporal")
        self.assertEqual(dato.stat().st_mode, modo)
        self.assertEqual(getattr(dato.stat(), "st_file_attributes", None), atributos)
        print(f"Destino externo: bytes={dato.read_bytes().hex()}; modo={modo}; "
              f"atributos={atributos}")

    def test_callback_no_cambia_archivo_externo_ni_oculta_error_ajeno(self):
        externo = self.raiz / "externo"
        externo.write_bytes(b"intacto")
        externo.chmod(stat.S_IREAD)
        temporal = self.raiz / "temporal"
        temporal.mkdir()
        fallo = PermissionError(13, "denegado", str(externo))

        def fallo_simulado(_raiz, **opciones):
            callback = opciones.get("onexc") or opciones["onerror"]
            argumento = fallo if "onexc" in opciones else (PermissionError, fallo, None)
            callback(os.unlink, str(externo), argumento)

        with mock.patch("test_peticion_bootstrap_actualizar.shutil.rmtree",
                        side_effect=fallo_simulado):
            with self.assertRaises(PermissionError):
                borrar_tmp_silencioso(temporal)
        self.assertEqual(externo.read_bytes(), b"intacto")
        self.assertFalse(externo.stat().st_mode & stat.S_IWRITE)

    def test_callback_posix_compatible_solo_recupera_readonly_propio(self):
        temporal = self.raiz / "temporal"
        temporal.mkdir()
        archivo = temporal / "propio"
        archivo.write_bytes(b"propio")
        archivo.chmod(stat.S_IREAD)
        fallo = PermissionError(13, "readonly", str(archivo))
        llamadas = []

        def simular(_raiz, **opciones):
            callback = opciones.get("onexc") or opciones["onerror"]
            argumento = fallo if "onexc" in opciones else (PermissionError, fallo, None)
            callback(lambda ruta: llamadas.append(ruta), str(archivo), argumento)

        with mock.patch("test_peticion_bootstrap_actualizar.shutil.rmtree",
                        side_effect=simular):
            borrar_tmp_silencioso(temporal)
        self.assertEqual(llamadas, [str(archivo)])
        self.assertTrue(archivo.stat().st_mode & stat.S_IWRITE)

        # Un EACCES en un archivo escribible no autoriza chmod ni se silencia.
        with mock.patch("test_peticion_bootstrap_actualizar.shutil.rmtree",
                        side_effect=simular), mock.patch("os.chmod") as chmod:
            with self.assertRaises(PermissionError):
                borrar_tmp_silencioso(temporal)
        chmod.assert_not_called()

    def test_dos_fallos_comparten_un_solo_plazo(self):
        temporal = self.raiz / "temporal"
        temporal.mkdir()
        intentos = []

        def retenido(_raiz, **_opciones):
            nombre = "primero" if len(intentos) == 0 else "segundo"
            intentos.append(nombre)
            error = PermissionError(13, "sharing violation", str(temporal / nombre))
            error.winerror = 32
            raise error

        with mock.patch("test_peticion_bootstrap_actualizar.shutil.rmtree",
                        side_effect=retenido), mock.patch(
                            "test_peticion_bootstrap_actualizar.time.monotonic",
                            side_effect=(0, .8, 1.6, 2.01)), mock.patch(
                            "test_peticion_bootstrap_actualizar.time.sleep"):
            with self.assertRaises(PermissionError) as captura:
                borrar_tmp_silencioso(temporal)
        self.assertEqual(intentos, ["primero", "segundo"])
        self.assertIn("segundo", str(captura.exception))

    def test_no_reintenta_si_sleep_despierta_tras_el_plazo(self):
        temporal = self.raiz / "temporal"
        temporal.mkdir()
        reloj = [0.0]
        fallo = PermissionError(13, "sharing violation", str(temporal / "retenido"))
        fallo.winerror = 32

        def retenido(_raiz, **_opciones):
            raise fallo

        def despertar_tarde(_segundos):
            reloj[0] = 2.01

        with mock.patch("test_peticion_bootstrap_actualizar.shutil.rmtree",
                        side_effect=retenido) as rmtree, mock.patch(
                            "test_peticion_bootstrap_actualizar.time.monotonic",
                            side_effect=lambda: reloj[0]), mock.patch(
                            "test_peticion_bootstrap_actualizar.time.sleep",
                            side_effect=despertar_tarde) as sleep:
            with self.assertRaises(PermissionError) as captura:
                borrar_tmp_silencioso(temporal)
        self.assertEqual(rmtree.call_count, 1)
        sleep.assert_called_once()
        self.assertIn("retenido", str(captura.exception))

    @unittest.skipUnless(os.name == "nt", "handles de Windows")
    def test_handle_transitorio_y_persistente_tienen_presupuesto_global(self):
        # CreateFile sin FILE_SHARE_DELETE reproduce el lock real de Windows.
        codigo = (
            "import ctypes,sys,time\nfrom pathlib import Path\n"
            "k=ctypes.windll.kernel32\n"
            "k.CreateFileW.restype=ctypes.c_void_p\n"
            "h=k.CreateFileW(sys.argv[1], 0x80000000, 0, None, 3, 0, None)\n"
            "assert h != ctypes.c_void_p(-1).value, ctypes.GetLastError()\n"
            "print('listo', flush=True)\n"
            "while not Path(sys.argv[2]).exists(): time.sleep(.01)\n"
            "k.CloseHandle(ctypes.c_void_p(h))\n"
        )
        for persistente in (False, True):
            with self.subTest(persistente=persistente):
                temporal = self.raiz / ("persistente" if persistente else "transitorio")
                temporal.mkdir()
                archivo = temporal / "retenido"
                archivo.write_bytes(b"retenido")
                gate = self.raiz / ("gate-p" if persistente else "gate-t")
                hijo = subprocess.Popen([sys.executable, "-c", codigo, str(archivo), str(gate)],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True,
                                       creationflags=CREATIONFLAGS)
                try:
                    self.assertEqual(hijo.stdout.readline().strip(), "listo")
                    reloj = None
                    if not persistente:
                        reloj = threading.Timer(.2, gate.touch)
                        reloj.start()
                    inicio = time.monotonic()
                    if persistente:
                        with self.assertRaises(OSError) as captura:
                            borrar_tmp_silencioso(temporal)
                        self.assertIn("retenido", str(captura.exception))
                        self.assertTrue(temporal.exists())
                    else:
                        borrar_tmp_silencioso(temporal)
                        self.assertFalse(temporal.exists())
                    duracion = time.monotonic() - inicio
                    self.assertLess(duracion, 2.7)
                    if persistente:
                        self.assertGreaterEqual(duracion, 1.8)
                    print(f"Handle Windows: persistente={persistente}; "
                          f"duracion_s={duracion:.3f}; ruta={archivo.name}")
                finally:
                    if reloj is not None:
                        reloj.join(timeout=3)
                    gate.touch()
                    hijo.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
