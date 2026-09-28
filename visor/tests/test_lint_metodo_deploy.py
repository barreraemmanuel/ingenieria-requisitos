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

    def peticion_con_deploy(self, ref, estado="pendiente"):
        datos = {"formato": 1, "id": "P-20260101-abcd1234", "estado": "encaminada",
                 "creada": "2026-01-01T00:00:00+00:00", "actualizada": "2026-01-01T00:00:00+00:00",
                 "original": {"autor": "test", "resumen": "desplegar", "texto": "desplegar la 013"},
                 "aclaraciones": [], "evaluaciones": [], "cierres": [],
                 "procesos": [{"tipo": "deploy", "ref": ref, "estado": estado,
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
        self.assertNotIn("unidad con nombre fuera de convención NNN-slug: despliegues",
                         salida.stdout + salida.stderr)

    def test_ficha_invalida_no_acredita_despliegue_terminal(self):
        ref = "docs/05-trabajo/despliegues/ola-agosto.md"
        self.ficha_despliegue(ref)
        self.peticion_con_deploy(ref, estado="terminal")
        salida = self.lint()
        self.assertIn("terminal sin ficha desplegada y completa", salida.stdout)
        self.assertNotEqual(salida.returncode, 0)

    def test_expres_terminal_sin_clon_deja_git_pendiente(self):
        ref = "expres-P-20260101-abcd1234-cambio"
        self.peticion_con_deploy(ref, estado="terminal")
        ruta = self.raiz / "docs/05-trabajo/peticiones/P-20260101-abcd1234/peticion.json"
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["procesos"][0].update(tipo="expres", metadata={"base_sha": "a" * 40})
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        (self.raiz / "main").mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.raiz, check=True)
        salida = self.lint()
        self.assertIn("verificación Git pendiente", salida.stdout)
        self.assertNotIn("exprés terminal sin cambio fusionado", salida.stdout)

    def test_identidad_git_exige_raiz_configurada_y_rama_principal(self):
        import importlib.util

        scripts = SCRIPT.parent
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        spec = importlib.util.spec_from_file_location("repo_config_132", scripts / "repo_config.py")
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        clon = self.raiz / "main"
        clon.mkdir()
        self.assertFalse(config.clon_codigo_disponible(clon, "main"))
        subprocess.run(["git", "init", "-q"], cwd=self.raiz, check=True)
        self.assertFalse(config.clon_codigo_disponible(clon, "main"))
        (self.raiz / ".git").rename(self.raiz / "git-padre-guardado")
        ajeno = self.raiz / "ajeno"
        clon.rmdir()
        clon = ajeno / "main"
        clon.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=ajeno, check=True)
        subprocess.run(["git", "-C", str(ajeno), "-c", "user.name=Test",
                        "-c", "user.email=test@example.com", "commit", "-q",
                        "--allow-empty", "-m", "base"], check=True)
        self.assertFalse(config.clon_codigo_disponible(clon, "main"))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=clon, check=True)
        self.assertFalse(config.clon_codigo_disponible(clon, "main"))
        subprocess.run(["git", "-C", str(clon), "-c", "user.name=Test",
                        "-c", "user.email=test@example.com", "commit", "-q",
                        "--allow-empty", "-m", "base"], check=True)
        self.assertTrue(config.clon_codigo_disponible(clon, "main"))

    def test_deploy_documental_completo_sin_clon_avisa_y_no_falla_la_ficha(self):
        ref = "docs/05-trabajo/despliegues/ola-agosto.md"
        self.peticion_con_deploy(ref, estado="terminal")
        sha = "a" * 40
        ruta = self.raiz / ref
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            "---\nproceso: deploy\nestado: desplegado\netapa: 1-lan\n"
            f"fecha: 2026-08-04\ncommit: {sha}\n---\n\n"
            f"- **Commit/tag:** {sha} en main\n"
            "- **Etapa destino y máquina exacta:** LAN servidor de pruebas\n"
            "- **Qué cambia para el usuario, en una frase:** mejora visible\n"
            "- **OK del usuario ANTES de salir:** OK (2026-08-04, Test)\n"
            "- **Suite completa sobre este commit:** VERDE .runtime/pre-deploy/full-suite.log\n"
            "- **Seguridad sobre este commit:** VERDE .runtime/pre-deploy/security.log\n"
            "- **Qué se copió y adónde:** base a servidor de pruebas\n"
            "- **Volcado — comando y salida:** backup completado\n"
            "- **Restauración de prueba:** restauración validada\n"
            "- **Pasos:** reiniciar servicio de pruebas\n"
            "- **Vuelta atrás:** restaurar backup anterior\n"
            "- **Flujo real de negocio de punta a punta:** alta completa\n"
            "- **Vigilancia:** monitor verde\n"
            "- **Validación del usuario sobre la etapa desplegada:** OK (2026-08-04)\n"
            "- **Resultado:** DESPLEGADO con éxito\n"
            "- **Quién y cuándo:** Test 2026-08-04 12:30\n"
            "- **Anotado en `conocimiento/plano-deploy.md`:** registro actualizado\n",
            encoding="utf-8",
        )
        salida = self.lint()
        self.assertIn("verificación Git pendiente", salida.stdout)
        self.assertNotIn("terminal sin ficha desplegada y completa", salida.stdout)

    def test_carpeta_ajena_sigue_denunciada(self):
        (self.raiz / "docs/05-trabajo/no-es-unidad").mkdir()
        salida = self.lint()
        self.assertIn("unidad con nombre fuera de convención NNN-slug: no-es-unidad",
                      salida.stdout)

    def test_ficha_de_lote_ausente_sigue_denunciada(self):
        ref = "docs/05-trabajo/despliegues/ausente.md"
        self.peticion_con_deploy(ref)
        salida = self.lint()
        self.assertIn(DENUNCIA, salida.stdout)

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
        self.assertEqual(resuelta, (self.raiz / ref).resolve())

    def test_una_ruta_fuera_de_las_tres_carpetas_sigue_siendo_inexistente(self):
        ref = "docs/conocimiento/despliegue.md"
        self.ficha_despliegue(ref)
        self.peticion_con_deploy(ref)
        salida = self.lint()
        self.assertIn(DENUNCIA, salida.stdout + salida.stderr)


if __name__ == "__main__":
    unittest.main()
