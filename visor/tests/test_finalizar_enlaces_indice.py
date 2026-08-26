"""Bug 005-enlaces-indice-finalizar: compilar.py escribe en el README los enlaces con
la estructura de la carpeta temporal de compilación (01-constitution/, 02-flows/AREA/),
pero finalizar.py copia la constitución con OTRO nombre (manifiesto.md) y aplana todos
los .md de las actividades directamente en docs/02-flujos/. El INDICE.md resultante
queda con el 100% de sus enlaces apuntando a rutas que no existen."""

import hashlib
import importlib.util
import json
import os
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


# Unidad 095: salida de referencia (sha256 de cada fichero que deja
# `copiar_documentacion`), medida sobre el aplanado propio de finalizar.py ANTES de
# delegarlo en `compilar.py --formato plano`. Es el testigo de R1: byte a byte lo mismo,
# lo escriba quien lo escriba. Si un cambio legítimo del formato mueve estos hashes, se
# regenera la referencia A PROPÓSITO y se dice en la ficha; nunca "para que pase".
REFERENCIA_DOS_ACTIVIDADES = {
    "01-constitucion/manifiesto.md":
        "69db62feba66008a73cca8ef81128b2884852e90240c1dd72e5969d70e33f8ea",
    "02-flujos/INDICE.md":
        "7be90c05d74fb5073a5982e8343ae36c13f66d34fb74bf8226bf92614dc62634",
    "02-flujos/act-dos.md":
        "7df9c4a895cef7b16f7792fb97853e7d7dc44dc56cbdab49692f446ce3184071",
    "02-flujos/act-uno.md":
        "2fe2163a7f971455a7cb13f9a8f19875d6a72e0db3b2ad0436b22ebdb871a9c7",
}
REFERENCIA_MONO_ACTIVIDAD = {
    "01-constitucion/manifiesto.md":
        "9a603530d7894aa28d319dc9da803cdde4530d33150780c8fccdace8d9c4d0d7",
    "02-flujos/INDICE.md":
        "97a38731e03edb02c5eb631ba95aeafb3c16146026f2c5e76085cd34ae270af8",
    "02-flujos/demo-mono-actividad.md":
        "f3f7954bb31161dbd791b4db165dcc44b573b6287b8344b8e19ade48b7c11811",
}


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

    def planos_una_actividad(self):
        mapa = self.proyecto / "planos.json"
        mapa.write_text(json.dumps({
            "version": 2, "titulo": "Demo mono-actividad", "actividades": [],
            "flujos": [], "episodios": [],
        }), encoding="utf-8")
        return mapa

    def huellas(self):
        raiz = self.workspace / "docs"
        return {str(f.relative_to(raiz)).replace(os.sep, "/"):
                hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(raiz.rglob("*.md"))}

    def compilar(self, mapa):
        salida = self.proyecto / "especificaciones"
        resultado = subprocess.run(
            [sys.executable, str(COMPILAR), "--mapa", str(mapa), "--salida", str(salida)],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return salida

    def test_enlace_a_constitucion_resuelve_tras_finalizar(self):
        mapa = self.planos_dos_actividades()
        self.finalizar.copiar_documentacion(self.workspace, self.compilar(mapa), mapa)

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
        mapa = self.planos_dos_actividades()
        self.finalizar.copiar_documentacion(self.workspace, self.compilar(mapa), mapa)

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
        mapa = self.planos_una_actividad()
        self.finalizar.copiar_documentacion(self.workspace, self.compilar(mapa), mapa)

        indice = (self.workspace / "docs/02-flujos/INDICE.md").read_text(encoding="utf-8")
        import re
        enlaces = [e for e in re.findall(r"\]\(([^)]+\.md)\)", indice)
                   if "manifiesto" not in e and "constitution" not in e]
        self.assertEqual(len(enlaces), 1, indice)
        destino = (self.workspace / "docs/02-flujos" / enlaces[0]).resolve()
        self.assertTrue(destino.is_file(), f"{enlaces[0]} no resuelve")
        self.assertNotIn("02-flows", indice, indice)

    # --- Unidad 095 · R1-R2: el formato plano sale de `compilar.py --formato plano`,
    # no de una copia del aplanado dentro de finalizar.py. ---

    def test_salida_byte_a_byte_identica_a_la_referencia_con_actividades(self):
        mapa = self.planos_dos_actividades()
        self.finalizar.copiar_documentacion(self.workspace, self.compilar(mapa), mapa)
        self.assertEqual(self.huellas(), REFERENCIA_DOS_ACTIVIDADES)

    def test_salida_byte_a_byte_identica_a_la_referencia_mono_actividad(self):
        mapa = self.planos_una_actividad()
        self.finalizar.copiar_documentacion(self.workspace, self.compilar(mapa), mapa)
        self.assertEqual(self.huellas(), REFERENCIA_MONO_ACTIVIDAD)

    def test_los_documentos_los_escribe_compilar_con_formato_plano(self):
        """R1: el aplanado ya no lo hace finalizar.py con código propio."""
        mapa = self.planos_dos_actividades()
        salida = self.compilar(mapa)
        llamadas = []
        original = self.finalizar.ejecutar

        def espia(comando, cwd=None):
            llamadas.append([str(x) for x in comando])
            return original(comando, cwd=cwd)

        self.finalizar.ejecutar = espia
        self.finalizar.copiar_documentacion(self.workspace, salida, mapa)

        planas = [c for c in llamadas
                  if any(x.endswith("compilar.py") for x in c) and "plano" in c]
        self.assertEqual(len(planas), 1, llamadas)
        self.assertIn("--formato", planas[0])
        self.assertIn("--mapa", planas[0])
        self.assertEqual(planas[0][planas[0].index("--mapa") + 1], str(mapa))
        # Y el código duplicado de aplanado desapareció del fichero.
        fuente = (RAIZ / "visor/finalizar.py").read_text(encoding="utf-8")
        self.assertNotIn("rglob", fuente, "sigue habiendo un aplanado propio en finalizar.py")

    def test_si_compilar_falla_no_deja_documentacion_a_medias(self):
        """R2: el rechazo de compilar.py (incluida su línea SALIDA:) llega tal cual y la
        documentación anterior del workspace queda intacta."""
        mapa = self.planos_dos_actividades()
        salida = self.compilar(mapa)

        flujos = self.workspace / "docs/02-flujos"
        (flujos / "INDICE.md").write_text("indice anterior\n", encoding="utf-8")
        (flujos / "act-uno.md").write_text("documento anterior\n", encoding="utf-8")
        manifiesto = self.workspace / "docs/01-constitucion/manifiesto.md"
        manifiesto.write_text("manifiesto anterior\n", encoding="utf-8")
        antes = self.huellas()

        falso = Path(self.tmp.name) / "falso"
        falso.mkdir()
        (falso / "compilar.py").write_text(
            "import sys\n"
            "sys.exit('compilar: no se en que formato esta la salida, asi que no "
            "escribo nada.\\nSALIDA: dime cual quieres con --formato plano o "
            "--formato carpetas.')\n", encoding="utf-8")
        self.finalizar.BASE = falso

        with self.assertRaises(SystemExit) as cm:
            self.finalizar.copiar_documentacion(self.workspace, salida, mapa)
        self.assertIn("SALIDA:", str(cm.exception))
        self.assertIn("--formato plano", str(cm.exception))
        self.assertEqual(self.huellas(), antes, "dejó la documentación a medias")


if __name__ == "__main__":
    unittest.main()
