"""El lease no escribe fuera del workspace ni con un enlace en un tramo INTERMEDIO.

Por qué existe este fichero (unidad 043, ronda 2): `_ensure_directory` mira las HOJAS
—`.runtime/leases`, `active`, `fencing`— y nunca el tramo `.runtime`. Cambiar
`is_symlink()` por `es_enlace()` cerró el escenario de la sección 2 del bug (el enlace
sobre `active`), pero no la clase de fallo: basta con poner el enlace un nivel más
arriba, en `.runtime`, para que `mkdir(parents=True)` lo atraviese y el lease acabe
FUERA del workspace. Lo que falta es el segundo control que la propuesta pedía —
contrastar la ruta resuelta contra la raíz del workspace, como `confined_path`.

Las dos plataformas, cada una con el enlace que puede montar:
  - POSIX: symlink (en Windows crear uno exige privilegio -> se salta con motivo).
  - Windows: junction, `mklink /J`, que NO exige privilegio (se salta en POSIX).
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
if str(SCRIPTS) not in sys.path:   # lease.py importa su hermano workspace_paths
    sys.path.insert(0, str(SCRIPTS))


def cargar_lease():
    spec = importlib.util.spec_from_file_location(
        f"lease_bajo_test_{uuid.uuid4().hex}", SCRIPTS / "lease.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class BaseTramoIntermedio(unittest.TestCase):
    """Monta ws/ y exterior/, deja que la subclase enlace `.runtime` -> exterior."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="lease-confinado-")).resolve()
        self.addCleanup(ayuda_windows.borrar_arbol, self.base)
        self.lease = cargar_lease()
        self.ws = self.base / "ws"
        self.ws.mkdir()
        self.exterior = self.base / "exterior"
        self.exterior.mkdir()

    def enlazar_runtime(self):
        raise NotImplementedError

    def comprobar_guarda(self):
        self.enlazar_runtime()

        gestor = self.lease.LeaseManager(self.ws, session_id="sesion", host="host-local")
        with self.assertRaises(self.lease.LeaseError):
            gestor.acquire("unit:004")

        escrito = sorted(p.name for p in self.exterior.rglob("*"))
        self.assertEqual(escrito, [], "el lease ha escrito FUERA del workspace")


class EnlaceIntermedioSymlinkTest(BaseTramoIntermedio):
    """POSIX: `.runtime` es un symlink que sale del workspace."""

    def enlazar_runtime(self):
        ayuda_windows.enlazar_o_saltar(
            self, self.ws / ".runtime", self.exterior, directorio=True
        )

    def test_runtime_como_symlink_no_deja_adquirir(self):
        self.comprobar_guarda()


class EnlaceIntermedioJunctionTest(BaseTramoIntermedio):
    """Windows: `.runtime` es un junction — el mismo escenario SIN privilegio."""

    def setUp(self):
        if os.name != "nt":
            self.skipTest("los junctions son de Windows")
        super().setUp()

    def enlazar_runtime(self):
        hecho = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(self.ws / ".runtime"), str(self.exterior)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if hecho.returncode:
            self.skipTest(f"esta máquina no deja crear junctions: {hecho.stdout}{hecho.stderr}")

    def test_runtime_como_junction_no_deja_adquirir(self):
        self.comprobar_guarda()


class CaminoBuenoTest(unittest.TestCase):
    """La guarda nueva no puede romper el camino de siempre."""

    def test_un_workspace_normal_sigue_adquiriendo_y_soltando(self):
        base = Path(tempfile.mkdtemp(prefix="lease-confinado-ok-")).resolve()
        self.addCleanup(ayuda_windows.borrar_arbol, base)
        gestor = cargar_lease().LeaseManager(base, session_id="sesion", host="host-local")

        grupo = gestor.acquire("unit:004")
        try:
            grupo.assert_owner()
            self.assertTrue((base / ".runtime/leases/active").is_dir())
        finally:
            grupo.release()


if __name__ == "__main__":
    unittest.main()
