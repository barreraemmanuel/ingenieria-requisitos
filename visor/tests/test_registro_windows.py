"""Regresión del registro con bloqueos reales de Windows y datos sintéticos."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proyectos


def esperar(ruta, segundos=5):
    limite = time.monotonic() + segundos
    while not ruta.exists():
        if time.monotonic() >= limite:
            raise TimeoutError(str(ruta))
        time.sleep(0.01)


def hijo(modo, carpeta, workspace):
    proyectos.REGISTRO = carpeta / "registro.json"
    if modo == "retrasado":
        original = os.fstat

        def barrera(fd):
            resultado = original(fd)
            (carpeta / "vacio").touch()
            esperar(carpeta / "retenido")
            return resultado

        os.fstat = barrera
    else:
        esperar(carpeta / "vacio")
        original = proyectos.cargar

        def retener():
            (carpeta / "retenido").touch()
            esperar(carpeta / "liberar")
            return original()

        proyectos.cargar = retener
    proyectos.registrar(workspace)


@unittest.skipUnless(os.name == "nt", "requiere bloqueos reales de Windows")
class RegistroWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="registro-test-")
        self.addCleanup(self.temporal.cleanup)
        self.carpeta = Path(self.temporal.name)
        self.registro_anterior = proyectos.REGISTRO
        proyectos.REGISTRO = self.carpeta / "registro.json"
        self.addCleanup(setattr, proyectos, "REGISTRO", self.registro_anterior)

    def workspace(self, nombre):
        ruta = self.carpeta / nombre
        planos = ruta / "docs/02-flujos/planos"
        planos.mkdir(parents=True)
        (ruta / "AGENTS.md").write_text("# Prueba\n", encoding="utf-8")
        (planos / "planos.json").write_text(json.dumps({"titulo": nombre}), encoding="utf-8")
        return ruta

    def retener_registro(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                       wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        # FILE_SHARE_READ | FILE_SHARE_WRITE, sin FILE_SHARE_DELETE.
        handle = kernel.CreateFileW(str(proyectos.REGISTRO), 0x80000000, 3, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value, ctypes.get_last_error())
        return kernel, handle

    def test_dos_altas_con_candado_vacio_conservan_ambas(self):
        primero = self.workspace("primero")
        segundo = self.workspace("segundo")
        procesos = [subprocess.Popen(
            [sys.executable, __file__, modo, str(self.carpeta), str(workspace)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        ) for modo, workspace in (("retrasado", primero), ("titular", segundo))]
        try:
            esperar(self.carpeta / "retenido")
            time.sleep(0.2)
            (self.carpeta / "liberar").touch()
            salidas = [p.communicate(timeout=10) for p in procesos]
            self.assertEqual([p.returncode for p in procesos], [0, 0], salidas)
            self.assertEqual({p["ruta"] for p in proyectos.cargar()["proyectos"]},
                             {str(primero), str(segundo)})
        finally:
            (self.carpeta / "liberar").touch()
            for proceso in procesos:
                if proceso.poll() is None:
                    proceso.kill()
                proceso.communicate()

    def test_reemplazo_transitorio_guarda_al_liberar(self):
        anterior = {"formato": 1, "proyectos": [{"titulo": "antes"}]}
        nuevo = {"formato": 1, "proyectos": [{"titulo": "después"}]}
        proyectos.guardar(anterior)
        kernel, handle = self.retener_registro()
        liberado = threading.Event()

        def liberar():
            time.sleep(0.2)
            kernel.CloseHandle(handle)
            liberado.set()

        hilo = threading.Thread(target=liberar)
        hilo.start()
        try:
            inicio = time.monotonic()
            proyectos.guardar(nuevo)
            self.assertLess(time.monotonic() - inicio, 2)
            self.assertEqual(proyectos.cargar(), nuevo)
            self.assertEqual(list(self.carpeta.glob("registro-*")), [])
        finally:
            hilo.join(timeout=3)
            if not liberado.is_set():
                kernel.CloseHandle(handle)

    def test_reemplazo_persistente_conserva_bytes_y_limpia_temporal(self):
        anterior = {"formato": 1, "proyectos": [{"titulo": "antes"}]}
        proyectos.guardar(anterior)
        bytes_anteriores = proyectos.REGISTRO.read_bytes()
        kernel, handle = self.retener_registro()
        try:
            inicio = time.monotonic()
            with self.assertRaises(PermissionError):
                proyectos.guardar({"formato": 1, "proyectos": []})
            duracion = time.monotonic() - inicio
            self.assertGreaterEqual(duracion, 1.8)
            self.assertLess(duracion, 2.5)
            self.assertEqual(proyectos.REGISTRO.read_bytes(), bytes_anteriores)
            self.assertEqual(list(self.carpeta.glob("registro-*")), [])
        finally:
            kernel.CloseHandle(handle)

    def test_error_ajeno_a_contencion_no_se_reintenta(self):
        with mock.patch.object(proyectos.os, "replace", side_effect=OSError(22, "inválido")) as reemplazar:
            with self.assertRaises(OSError):
                proyectos.guardar({"formato": 1, "proyectos": []})
        reemplazar.assert_called_once()
        self.assertEqual(list(self.carpeta.glob("registro-*")), [])

    def test_registrar_olvidar_y_depurar_conservan_las_entradas_vivas(self):
        activa = self.workspace("activa")
        olvidada = self.workspace("olvidada")
        ausente = self.workspace("ausente")
        for ruta in (activa, olvidada, ausente):
            proyectos.registrar(ruta)
        proyectos.olvidar(olvidada)
        self.assertTrue(olvidada.is_dir())
        shutil.rmtree(ausente)
        previo = proyectos.REGISTRO.read_bytes()
        proyectos.depurar()
        self.assertEqual(proyectos.REGISTRO.read_bytes(), previo)
        proyectos.depurar(aplicar=True)
        self.assertEqual([p["ruta"] for p in proyectos.cargar()["proyectos"]], [str(activa)])


if __name__ == "__main__":
    if len(sys.argv) == 4:
        hijo(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
