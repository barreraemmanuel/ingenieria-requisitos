"""Bug 038 — la ficha de despliegue de una unidad YA archivada también es un proceso `deploy`.

`lint_metodo.py` validaba `deploy` con una expresión que solo admitía
`docs/(05-trabajo|bugs)/NNN-slug/despliegue.md`; `unidad` y `auditoria` sí miran también
`archivo/`. Desplegar después de cerrar es el caso normal, y quedaba atrapado entre
`peticion.py` (que exigía la ruta activa) y el linter (que la rechazaba).
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts/lint_metodo.py"
DENUNCIA = "proceso deploy inexistente"


class DeployDeUnidadArchivadaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-deploy-archivo-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / "docs/05-trabajo/archivo/013-flask-a-django").mkdir(parents=True)
        (self.raiz / "docs/05-trabajo/peticiones/P-20260101-abcd1234").mkdir(parents=True)

    def ficha_despliegue(self, ruta_relativa):
        ruta = self.raiz / ruta_relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text("---\nproceso: deploy\nestado: pendiente\n---\n\n# despliegue\n", encoding="utf-8")

    def peticion_con_deploy(self, ref):
        datos = {"formato": 1, "id": "P-20260101-abcd1234", "estado": "encaminada",
                 "creada": "2026-01-01T00:00:00+00:00", "actualizada": "2026-01-01T00:00:00+00:00",
                 "original": {"autor": "test", "resumen": "desplegar", "texto": "desplegar la 013"},
                 "aclaraciones": [], "evaluaciones": [], "cierres": [],
                 "procesos": [{"tipo": "deploy", "ref": ref, "estado": "pendiente",
                               "revision": 1, "relacion": "satisface", "fecha": "2026-01-01T00:00:00+00:00",
                               "contrato_terminal": "despliegue-verificado-v1", "metadata": {}}]}
        (self.raiz / "docs/05-trabajo/peticiones/P-20260101-abcd1234/peticion.json").write_text(
            json.dumps(datos), encoding="utf-8")

    def lint(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--raiz", str(self.raiz)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_la_ficha_de_despliegue_en_archivo_es_un_proceso_deploy_valido(self):
        ref = "docs/05-trabajo/archivo/013-flask-a-django/despliegue.md"
        self.ficha_despliegue(ref)
        self.peticion_con_deploy(ref)
        salida = self.lint()
        self.assertNotIn(DENUNCIA, salida.stdout + salida.stderr,
                         "una unidad archivada también se despliega: su ficha es un deploy válido")

    def test_el_despliegue_de_lote_tambien_es_valido_para_el_linter(self):
        ref = "docs/05-trabajo/despliegues/ola-agosto.md"
        self.ficha_despliegue(ref)
        self.peticion_con_deploy(ref)
        salida = self.lint()
        self.assertNotIn(DENUNCIA, salida.stdout + salida.stderr)

    def test_peticion_py_acepta_la_misma_ruta_de_archivo_que_el_linter(self):
        # Las dos mordazas: sin esto, la ruta que el linter acepta es la que peticion.py rechaza.
        import importlib.util, sys
        scripts = SCRIPT.parent
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        spec = importlib.util.spec_from_file_location("peticion_038", scripts / "peticion.py")
        peticion = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(peticion)
        peticion.RAIZ = self.raiz.resolve()  # macOS: /var → /private/var
        ref = "docs/05-trabajo/archivo/013-flask-a-django/despliegue.md"
        self.ficha_despliegue(ref)
        resuelta = peticion.ruta_proceso_canonico("deploy", ref)
        self.assertTrue(str(resuelta).endswith("archivo/013-flask-a-django/despliegue.md"))

    def test_una_ruta_fuera_de_las_tres_carpetas_sigue_siendo_inexistente(self):
        ref = "docs/conocimiento/despliegue.md"
        self.ficha_despliegue(ref)
        self.peticion_con_deploy(ref)
        salida = self.lint()
        self.assertIn(DENUNCIA, salida.stdout + salida.stderr)


if __name__ == "__main__":
    unittest.main()
