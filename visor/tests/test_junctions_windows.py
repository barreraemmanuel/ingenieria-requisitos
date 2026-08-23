"""Un *junction* de Windows NO puede esquivar las guardas anti-enlace (unidad 043).

Por qué existe este fichero: los tests de symlink no pueden montar su escenario en
Windows (crear un symlink exige privilegio) y se saltan. Saltar no es cubrir. El
junction es el equivalente de Windows que **no** exige privilegio, y hasta esta unidad
era invisible para `is_symlink()`: se demostró que sacaba la escritura fuera del
workspace en DOS sitios (el lease y el reparto del método).

Simétrico a los de symlink: aquellos se saltan en Windows, estos se saltan en POSIX.
Entre los dos, la guarda queda cubierta en las dos plataformas.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import ayuda_windows  # noqa: E402 - módulo hermano de la suite

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
for _ruta in (SCRIPTS, RAIZ / "visor"):   # actualizar.py importa bootstrap y proyectos
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))
import workspace_paths  # noqa: E402


def cargar(ruta):
    spec = importlib.util.spec_from_file_location(f"bajo_test_{uuid.uuid4().hex}", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class BaseJunction(unittest.TestCase):
    def setUp(self):
        if os.name != "nt":
            self.skipTest("los junctions son de Windows")
        self.base = Path(tempfile.mkdtemp(prefix="junction-"))
        self.addCleanup(ayuda_windows.borrar_arbol, self.base)

    def junction(self, enlace, destino):
        """Crea un junction. A diferencia del symlink, NO exige privilegio."""
        Path(destino).mkdir(parents=True, exist_ok=True)
        Path(enlace).parent.mkdir(parents=True, exist_ok=True)
        hecho = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(enlace), str(destino)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if hecho.returncode:
            self.skipTest(f"esta máquina no deja crear junctions: {hecho.stdout}{hecho.stderr}")
        return Path(enlace)


class DeteccionTest(BaseJunction):
    """R1 — `es_enlace()` ve lo que `is_symlink()` no ve."""

    def test_is_symlink_no_lo_ve_pero_es_enlace_si(self):
        enlace = self.junction(self.base / "dentro" / "enlace", self.base / "real")

        # El punto de partida del bug: los tres criterios de siempre dicen que no.
        self.assertFalse(os.path.islink(enlace))
        self.assertFalse(enlace.is_symlink())
        # Y sin embargo redirige fuera igual que un symlink.
        self.assertEqual(enlace.resolve(), (self.base / "real").resolve())

        self.assertTrue(workspace_paths.es_enlace(enlace))

    def test_un_directorio_normal_no_es_enlace(self):
        normal = self.base / "carpeta-de-verdad"
        normal.mkdir()
        self.assertFalse(workspace_paths.es_enlace(normal))

    def test_una_ruta_que_no_existe_no_es_enlace(self):
        self.assertFalse(workspace_paths.es_enlace(self.base / "no-existe"))


class LeaseTest(BaseJunction):
    """R2 — la raíz de leases no se deja sustituir por un junction."""

    def test_active_como_junction_no_deja_escribir_fuera(self):
        lease = cargar(SCRIPTS / "lease.py")
        ws = self.base / "ws"
        exterior = self.base / "exterior"
        (ws / ".runtime/leases").mkdir(parents=True)
        exterior.mkdir()
        self.junction(ws / ".runtime/leases/active", exterior)

        gestor = lease.LeaseManager(ws, session_id="sesion", host="host-local")
        with self.assertRaises(lease.LeaseError):
            gestor.acquire("unit:004")

        self.assertEqual(list(exterior.iterdir()), [],
                         "el lease se ha escrito FUERA del workspace")


class ModoDTest(BaseJunction):
    """R3 — el reparto del método tampoco escribe a través de un junction."""

    def setUp(self):
        super().setUp()
        self.actualizar = cargar(RAIZ / "visor/actualizar.py")

    def test_ruta_workspace_rechaza_el_junction(self):
        ws = self.base / "ws"
        exterior = self.base / "exterior"
        (ws / "docs").mkdir(parents=True)
        exterior.mkdir()
        (exterior / "victima.md").write_text("de fuera\n", encoding="utf-8")
        self.junction(ws / "docs" / "00-metodo", exterior)

        with self.assertRaises(RuntimeError):
            self.actualizar.ruta_workspace(str(ws), "docs/00-metodo/victima.md")

    def test_preparar_padre_seguro_rechaza_el_junction(self):
        ws = self.base / "ws"
        exterior = self.base / "exterior"
        (ws / "docs").mkdir(parents=True)
        exterior.mkdir()
        self.junction(ws / "docs" / "00-metodo", exterior)

        with self.assertRaises(RuntimeError):
            self.actualizar.preparar_padre_seguro(str(ws), "docs/00-metodo/nuevo.md")

    def test_una_ruta_normal_sigue_funcionando(self):
        """La guarda nueva no puede romper el camino bueno."""
        ws = self.base / "ws"
        (ws / "docs" / "00-metodo").mkdir(parents=True)
        (ws / "docs" / "00-metodo" / "VERSION").write_text("1.7.1\n", encoding="utf-8")

        ruta = self.actualizar.ruta_workspace(str(ws), "docs/00-metodo/VERSION")

        self.assertEqual(ruta, ws.resolve() / "docs" / "00-metodo" / "VERSION")


class ConfinedPathTest(BaseJunction):
    """R4 — `confined_path` ya aguantaba por su contraste con la raíz; sigue igual."""

    def test_confined_path_rechaza_el_junction(self):
        ws = self.base / "ws"
        exterior = self.base / "exterior"
        ws.mkdir()
        exterior.mkdir()
        (exterior / "fichero.md").write_text("fuera\n", encoding="utf-8")
        self.junction(ws / "salida", exterior)

        with self.assertRaises(workspace_paths.WorkspacePathError):
            workspace_paths.confined_path(ws, ws / "salida" / "fichero.md")


if __name__ == "__main__":
    unittest.main()
