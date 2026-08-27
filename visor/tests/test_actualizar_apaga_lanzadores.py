"""124 · Modo D apaga lo que retira.

`actualizar.py aplicar` borra del disco los lanzadores inseguros conocidos
(`RETIRADOS_METODO`), pero los procesos que ya los estaban ejecutando seguían
vivos: binarios que ya no existen en el repo, escuchando puertos y saliendo en
Inicio. Aquí se fija que, al retirarlos, también se apagan — SOLO los de ESE
workspace — y que la salida los nombra.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ACTUALIZAR = RAIZ / "visor/actualizar.py"
LANZADOR = "docs/00-metodo/scripts/sandbox_lanzar.py"

# Un proceso que se deja ver en `ps` y no hace nada más: ni red, ni ficheros.
CUERPO_LANZADOR = (
    "#!/usr/bin/env python3\n"
    "# launcher retirado (124): duerme hasta que lo apaguen\n"
    "import time\n"
    "time.sleep(600)\n"
)


def git(ws, *args):
    return subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


class ApagarLanzadoresRetiradosTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="apaga-lanzadores-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.entorno = dict(os.environ)
        self.entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(
            self.base / "registro-suite.json")

    def workspace_antiguo(self, nombre):
        ws = self.base / nombre
        for carpeta in ("00-metodo/scripts", "01-constitucion", "02-flujos/planos",
                        "03-investigacion", "04-planificacion", "05-trabajo/archivo",
                        "bugs", "conocimiento", "decisiones"):
            (ws / "docs" / carpeta).mkdir(parents=True)
        (ws / "AGENTS.md").write_text("# AGENTS.md — Antiguo (meta-repo)\n",
                                      encoding="utf-8")
        (ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        (ws / "docs/bugs/INDICE.md").write_text("001-antigua\n", encoding="utf-8")
        (ws / "docs/02-flujos/planos/planos.json").write_text(
            '{"version": 2, "titulo": "Antiguo"}\n', encoding="utf-8")
        (ws / LANZADOR).write_text(CUERPO_LANZADOR, encoding="utf-8")
        git(ws, "init", "-b", "main")
        git(ws, "config", "core.autocrlf", "false")
        git(ws, "config", "user.name", "Test")
        git(ws, "config", "user.email", "test@example.com")
        git(ws, "add", "-A")
        git(ws, "commit", "-m", "estado antiguo con launcher")
        return ws

    def arrancar_lanzador(self, ws, relativa=False):
        """El lanzador del workspace, en marcha. `relativa=True` lo arranca como se
        arranca de verdad desde dentro del workspace: `python3 docs/00-metodo/…`."""
        proceso = subprocess.Popen(
            [sys.executable, LANZADOR if relativa else str(ws / LANZADOR)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, cwd=str(ws))
        self.addCleanup(self.rematar, proceso)
        # Que `ps` ya lo vea antes de tocar nada.
        for _ in range(100):
            if self.en_ps(proceso.pid):
                break
            time.sleep(0.05)
        self.assertTrue(self.en_ps(proceso.pid), "el proceso de prueba no arrancó")
        return proceso

    def en_ps(self, pid):
        salida = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                capture_output=True, text=True, timeout=10)
        return bool(salida.stdout.strip())

    def rematar(self, proceso):
        if proceso.poll() is None:
            proceso.kill()
        proceso.wait(timeout=10)

    def aplicar(self, ws, cwd=None):
        return subprocess.run([sys.executable, str(ACTUALIZAR), "aplicar", str(ws)],
                              cwd=str(cwd or RAIZ), text=True, encoding="utf-8",
                              errors="replace", capture_output=True, env=self.entorno)

    @unittest.skipIf(os.name == "nt", "ps(1) es de POSIX; en Windows se avisa a mano")
    def test_aplicar_apaga_el_proceso_del_lanzador_retirado_y_lo_nombra(self):
        ws = self.workspace_antiguo("con-lanzador-vivo")
        proceso = self.arrancar_lanzador(ws)

        resultado = self.aplicar(ws)

        self.assertEqual(0, resultado.returncode, resultado.stdout + resultado.stderr)
        self.assertFalse((ws / LANZADOR).exists(), "el lanzador sigue en el disco")
        for _ in range(200):
            if proceso.poll() is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(
            proceso.poll(),
            "el proceso del lanzador retirado sigue vivo tras aplicar:\n"
            + resultado.stdout)
        self.assertIn(str(proceso.pid), resultado.stdout)
        self.assertIn(LANZADOR, resultado.stdout)

    @unittest.skipIf(os.name == "nt", "ps(1) es de POSIX; en Windows se avisa a mano")
    def test_no_toca_el_proceso_de_otro_workspace(self):
        """La regla de oro: jamás se apaga lo de otro workspace."""
        ajeno = self.workspace_antiguo("ajeno")
        proceso_ajeno = self.arrancar_lanzador(ajeno)
        mio = self.workspace_antiguo("mio")
        proceso_mio = self.arrancar_lanzador(mio)

        resultado = self.aplicar(mio)

        self.assertEqual(0, resultado.returncode, resultado.stdout + resultado.stderr)
        for _ in range(200):
            if proceso_mio.poll() is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(proceso_mio.poll(), resultado.stdout)
        time.sleep(0.5)
        self.assertIsNone(proceso_ajeno.poll(),
                          "apagó el proceso de OTRO workspace:\n" + resultado.stdout)
        self.assertNotIn(str(proceso_ajeno.pid), resultado.stdout)


    @unittest.skipIf(os.name == "nt", "ps(1) es de POSIX; en Windows se avisa a mano")
    def test_no_toca_un_proceso_ajeno_lanzado_con_ruta_relativa(self):
        """H1 de la revisión (27-08): una ruta RELATIVA en la línea de órdenes solo
        significa algo junto al cwd de QUIEN la lanzó.

        Si se resuelve contra el cwd de `actualizar.py` —y `aplicar` se ejecuta desde
        dentro del workspace, que es lo normal—, el lanzador de OTRO workspace arrancado
        como `python3 docs/00-metodo/scripts/sandbox_lanzar.py` casa con el candidato del
        nuestro y se lleva un SIGTERM. Aquí se fija que no.
        """
        ajeno = self.workspace_antiguo("ajeno-relativo")
        proceso_ajeno = self.arrancar_lanzador(ajeno, relativa=True)
        mio = self.workspace_antiguo("mio-absoluto")
        proceso_mio = self.arrancar_lanzador(mio)

        # El cwd que dispara el hueco: `cd <mi workspace> && actualizar.py aplicar .`
        resultado = self.aplicar(mio, cwd=mio)

        self.assertEqual(0, resultado.returncode, resultado.stdout + resultado.stderr)
        for _ in range(200):
            if proceso_mio.poll() is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(proceso_mio.poll(),
                             "no apagó ni el suyo:\n" + resultado.stdout)
        time.sleep(0.5)
        self.assertIsNone(
            proceso_ajeno.poll(),
            "apagó un proceso de OTRO workspace lanzado con ruta relativa:\n"
            + resultado.stdout)
        self.assertNotIn(str(proceso_ajeno.pid), resultado.stdout)


if __name__ == "__main__":
    unittest.main()
