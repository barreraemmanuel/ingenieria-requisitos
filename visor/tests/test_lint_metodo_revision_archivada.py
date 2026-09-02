"""R3c: una revisión nueva no convierte la historia archivada en una puerta imposible."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
PLANTILLA = RAIZ / "plantilla"


class LintMetodoRevisionArchivadaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-revision-archivada-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "workspace"
        shutil.copytree(PLANTILLA, self.ws)
        for nombre in (
            "01-constitucion", "02-flujos", "03-investigacion", "04-planificacion",
            "05-trabajo", "bugs", "conocimiento", "decisiones",
        ):
            (self.ws / "docs" / nombre).mkdir(parents=True, exist_ok=True)
        (self.ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        (self.ws / "docs/05-trabajo/archivo").mkdir(exist_ok=True)
        (self.ws / "docs/05-trabajo/peticiones").mkdir(exist_ok=True)

    def preparar(self, archivada):
        pid = "P-20260901-1234abcd"
        slug = "042-entrega-antigua"
        base = self.ws / "docs/05-trabajo" / ("archivo" if archivada else "")
        carpeta = base / slug
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            "---\n"
            f"unidad: {slug}\ntipo: feature\ncarril: normal\n"
            "estado: mergeada\nactividad: demo\nficheros: []\n"
            f"peticiones: [{pid}@1]\nactualizado: 2026-09-01\naprobado: 2026-09-01\n"
            "---\n\n# Entrega\n", encoding="utf-8",
        )
        peticion = self.ws / "docs/05-trabajo/peticiones" / pid
        peticion.mkdir()
        (peticion / "peticion.json").write_text(json.dumps({
            "id": pid, "revision": 2, "estado": "entregada",
            "original": {"resumen": "demo"}, "evaluaciones": [],
            "procesos": [{
                "tipo": "unidad", "ref": slug, "revision": 1,
                "estado": "terminal", "relacion": "satisface",
                "contrato_terminal": "unidad-mergeada-v1",
            }], "cierres": [],
        }), encoding="utf-8")

    def ejecutar(self):
        return subprocess.run(
            [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )

    def test_archivada_avisa_como_historia_sin_salida_invalida(self):
        self.preparar(archivada=True)
        salida = self.ejecutar().stdout
        self.assertIn("WARN", salida)
        self.assertIn("historia: satisfizo la revisión 1", salida)
        linea = next(linea for linea in salida.splitlines() if "historia:" in linea)
        self.assertNotIn("reencuadrar-orden", linea)

    def test_unidad_viva_sigue_fallando_y_nombra_reencuadrar(self):
        self.preparar(archivada=False)
        salida = self.ejecutar().stdout
        linea = next(linea for linea in salida.splitlines() if "está en revisión 2" in linea)
        self.assertIn("FAIL", linea)
        self.assertIn("reencuadrar-orden", linea)


if __name__ == "__main__":
    unittest.main()
