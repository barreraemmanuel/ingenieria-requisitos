"""Bug 005-enlaces-indice-finalizar: compilar.py escribe en el README los enlaces con
la estructura de la carpeta temporal de compilación (01-constitution/, 02-flows/AREA/),
pero finalizar.py copia la constitución con OTRO nombre (manifiesto.md) y aplana todos
los .md de las actividades directamente en docs/02-flujos/. El INDICE.md resultante
queda con el 100% de sus enlaces apuntando a rutas que no existen."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
COMPILAR = RAIZ / "visor/compilar.py"
# finalizar.py hace `import revision` a pelo cuando no corre como paquete (mismo motivo
# que test_escenarios_campo.py): visor/ tiene que estar en el sys.path antes de cargarlo.
if str(RAIZ / "visor") not in sys.path:
    sys.path.insert(0, str(RAIZ / "visor"))


def cargar_modulo(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class EnlacesIndiceFinalizarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="finalizar-enlaces-")
        self.addCleanup(self.tmp.cleanup)
        self.proyecto = Path(self.tmp.name) / "proyecto"
        self.proyecto.mkdir()
        self.workspace = Path(self.tmp.name) / "ws"
        (self.workspace / "docs/01-constitucion").mkdir(parents=True)
        (self.workspace / "docs/02-flujos").mkdir(parents=True)
        self.finalizar = cargar_modulo("finalizar_005", RAIZ / "visor/finalizar.py")

    def planos_dos_actividades(self):
        mapa = self.proyecto / "planos.json"
        mapa.write_text(json.dumps({
            "version": 2, "titulo": "Demo",
            "actividades": [
                {"id": "act-uno", "nombre": "Actividad Uno", "area": "General",
                 "estado": "especificada"},
                {"id": "act-dos", "nombre": "Actividad Dos", "area": "Otra",
                 "estado": "especificada"},
            ],
        }), encoding="utf-8")
        for act_id in ("act-uno", "act-dos"):
            carpeta = self.proyecto / "actividades" / act_id
            carpeta.mkdir(parents=True)
            (carpeta / "planos.json").write_text(json.dumps({
                "version": 2, "titulo": act_id,
                "actividades": [], "flujos": [], "episodios": [],
            }), encoding="utf-8")
        return mapa

    def compilar(self, mapa):
        salida = self.proyecto / "especificaciones"
        resultado = subprocess.run(
            [sys.executable, str(COMPILAR), "--mapa", str(mapa), "--salida", str(salida)],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return salida

    def test_enlace_a_constitucion_resuelve_tras_finalizar(self):
        salida = self.compilar(self.planos_dos_actividades())
        self.finalizar.copiar_documentacion(self.workspace, salida)

        indice = (self.workspace / "docs/02-flujos/INDICE.md").read_text(encoding="utf-8")
        import re
        # La ETIQUETA del enlace conserva el texto original de compilar.py
        # ("01-constitution/constitution.md"); lo que se reescribe es el DESTINO.
        m = re.search(r"\[01-constitution/constitution\.md\]\(([^)]+)\)", indice)
        self.assertIsNotNone(m, "el índice no enlaza a la constitución en absoluto")
        destino = (self.workspace / "docs/02-flujos" / m.group(1)).resolve()
        self.assertTrue(
            destino.is_file(),
            f"el enlace a la constitución ({m.group(1)}) no resuelve a un fichero real",
        )
        # No es un enlace, pero nombraba una carpeta inexistente tras aplanar — mismo
        # síntoma; sin esta línea, los 3 tests pasan igual con o sin ese replace
        # (revisión ronda 3: hueco de cobertura real).
        self.assertNotIn("02-flows", indice, indice)

    def test_enlaces_de_actividades_resuelven_tras_finalizar(self):
        salida = self.compilar(self.planos_dos_actividades())
        self.finalizar.copiar_documentacion(self.workspace, salida)

        indice = (self.workspace / "docs/02-flujos/INDICE.md").read_text(encoding="utf-8")
        import re
        enlaces = re.findall(r"\]\(([^)]+\.md)\)", indice)
        enlaces_actividad = [e for e in enlaces if "manifiesto" not in e and "constitution" not in e]
        self.assertEqual(len(enlaces_actividad), 2, indice)
        for enlace in enlaces_actividad:
            destino = (self.workspace / "docs/02-flujos" / enlace).resolve()
            self.assertTrue(
                destino.is_file(),
                f"el enlace de actividad ({enlace}) no resuelve a un fichero real",
            )
        self.assertNotIn("02-flows", indice, indice)

    def test_proyecto_de_una_sola_actividad_tambien_resuelve(self):
        mapa = self.proyecto / "planos.json"
        mapa.write_text(json.dumps({
            "version": 2, "titulo": "Demo mono-actividad", "actividades": [],
            "flujos": [], "episodios": [],
        }), encoding="utf-8")
        salida = self.compilar(mapa)
        self.finalizar.copiar_documentacion(self.workspace, salida)

        indice = (self.workspace / "docs/02-flujos/INDICE.md").read_text(encoding="utf-8")
        import re
        enlaces = [e for e in re.findall(r"\]\(([^)]+\.md)\)", indice)
                   if "manifiesto" not in e and "constitution" not in e]
        self.assertEqual(len(enlaces), 1, indice)
        destino = (self.workspace / "docs/02-flujos" / enlaces[0]).resolve()
        self.assertTrue(destino.is_file(), f"{enlaces[0]} no resuelve")
        self.assertNotIn("02-flows", indice, indice)


if __name__ == "__main__":
    unittest.main()
