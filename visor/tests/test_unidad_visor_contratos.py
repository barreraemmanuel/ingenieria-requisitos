"""Bug 054: el método tiene un visor de contratos y nunca manda abrirlo.

Cubre R3 y R4 del contrato del arreglo (R2 y R5 se cubren en `visor_contratos/tests/`):

- R3 — `unidad.py despachar` exige, además de `aprobado: FECHA`, rastro del visor de
  contratos sobre ESA unidad con fecha ≤ `aprobado:`. Sin rastro: FAIL con el comando
  que desbloquea. `--force` (hotfix P0) lo sigue saltando.
- R4 — `unidad.py nueva` y `unidad.py estado` imprimen el comando del visor; `lint_metodo.py`
  avisa (WARN, no FAIL) por cada contrato pendiente sin rastro.
"""
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
PLANTILLAS = RAIZ / "plantilla/docs/00-metodo/plantillas"
HOY = datetime.date.today().isoformat()
COMANDO_VISOR = "python3 main/web/abrir.py --workspace . --apartado contratos"


class WorkspaceBase(unittest.TestCase):
    """Workspace de método mínimo pero real: scripts, plantillas y repo de código."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="visor-contratos-unidad-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()

        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in (
            "control_plane.py", "ejecucion.py", "lease.py", "lint_cierre.py",
            "peticion.py", "repo_config.py", "unidad.py", "workspace_paths.py",
            "lint_metodo.py",
        ):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.peticion = scripts / "peticion.py"
        self.unidad = scripts / "unidad.py"
        self.linter = scripts / "lint_metodo.py"

        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True)
        for nombre in (
            "especificacion.md", "directo.md", "bug.md", "hallazgos.md",
            "peticion-investigacion-plan.md",
            "peticion-investigacion-informe.md",
            "peticion-investigacion-sintesis.md",
        ):
            shutil.copy2(PLANTILLAS / nombre, plantillas / nombre)

        (self.ws / "docs/05-trabajo").mkdir(parents=True)
        (self.ws / "docs/bugs").mkdir(parents=True)
        decision = self.ws / "docs/decisiones/004-paleta.md"
        decision.parent.mkdir(parents=True)
        decision.write_text("# Paleta vigente\n", encoding="utf-8")

        self.repo = self.ws / "main"
        (self.repo / "app").mkdir(parents=True)
        (self.repo / "app/terminal.py").write_text("print('ok')\n", encoding="utf-8")
        self.git(self.repo, "init", "-b", "main")
        self.git(self.repo, "config", "user.name", "Test")
        self.git(self.repo, "config", "user.email", "test@example.com")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-m", "base")
        self.sha = self.git(self.repo, "rev-parse", "HEAD")

    def git(self, cwd, *args):
        resultado = subprocess.run(
            ["git", *args], cwd=str(cwd), text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return resultado.stdout.strip()

    def ejecutar(self, script, *args):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    def capturar(self, resumen="Cambio solicitado"):
        resultado = self.ejecutar(
            self.peticion, "capturar", "--resumen", resumen,
            "--texto", "Implementa el cambio descrito", "--autor", "Nate",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return re.search(r"P-\d{8}-[a-f0-9]{8}", resultado.stdout).group(0)

    def evaluar(self, pid, ruta="feature", tipo=None):
        args = [
            "evaluar", pid, "--ruta", ruta, "--investigacion", "ninguna",
            "--motivo", "contraste suficiente para encaminar",
            "--flujo", "REC-1", "--huella-flujo", "planos-v1",
            "--sha", self.sha, "--ruta-codigo", "app/terminal.py",
            "--conocimiento", "docs/decisiones/004-paleta.md",
        ]
        if tipo:
            args.extend(("--tipo", tipo))
        resultado = self.ejecutar(self.peticion, *args)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def crear_feature_aprobada_sin_rastro(self, slug):
        """Unidad con `aprobado: HOY` en el frontmatter pero SIN rastro del visor:
        el caso exacto que R3 debe bloquear."""
        pid = self.capturar(f"Preparar {slug}")
        self.evaluar(pid)
        creada = self.ejecutar(self.unidad, "nueva", "feature", slug, "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = f"001-{slug}"
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        texto = ruta.read_text(encoding="utf-8")
        texto = re.sub(r"^aprobado:.*$", f"aprobado: {HOY}", texto, count=1, flags=re.M)
        cierre = texto.find("---", 4)
        cabecera = texto[:cierre + 3]
        cuerpo = (
            "\n\n# Contrato aprobado\n\n"
            "El usuario podrá completar el cambio solicitado sin alterar el comportamiento "
            "adyacente. La implementación conservará los datos existentes y mostrará un "
            "resultado verificable en la misma entrada que usa hoy, sin pedir un paso "
            "nuevo ni mover nada de sitio en el proceso habitual.\n\n"
            "## Criterios de aceptación\n\n"
            "- R1: el resultado solicitado aparece con un ejemplo real.\n"
            "- R2: el caso límite no cambia los datos existentes.\n\n"
            "## Verificación\n\n"
            "- **Nivel de test:** unitario, porque la conducta es una regla local.\n"
            "- **Criterio portante:** R1 — sin él la unidad entera no sirve de nada.\n"
        )
        ruta.write_text(cabecera + cuerpo, encoding="utf-8")
        return nombre

    def dejar_rastro(self, nombre, fecha=HOY):
        registro = self.ws / ".runtime" / "visor-contratos.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "a", encoding="utf-8") as rastro:
            rastro.write(f"{fecha}T09:00:00 contrato mostrado: {nombre}\n")
        # Unidad 107 (R5): la aprobación de verdad deja también el rastro del clic en la web.
        carpeta = self.ws / ".runtime" / "aprobaciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{nombre}-{fecha}.json").write_text(json.dumps({
            "unidad": nombre, "fecha": fecha,
            "ruta": f"docs/05-trabajo/{nombre}/especificacion.md",
            "huella": "0" * 64, "hora": f"{fecha}T09:00:00", "cliente": "127.0.0.1",
        }), encoding="utf-8")


class PuertaDelVisorTest(WorkspaceBase):
    """R3 — la fecha de `aprobado:` sola no basta: hace falta el rastro del visor."""

    def test_despachar_sin_rastro_bloquea_y_nombra_el_comando(self):
        nombre = self.crear_feature_aprobada_sin_rastro("sin-rastro")

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("visor de contratos", resultado.stderr.lower())
        self.assertIn(COMANDO_VISOR, resultado.stderr)
        self.assertFalse((self.ws / "worktrees" / nombre).exists())

    def test_despachar_con_rastro_igual_o_anterior_a_aprobado_pasa(self):
        nombre = self.crear_feature_aprobada_sin_rastro("con-rastro")
        self.dejar_rastro(nombre)

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertTrue((self.ws / "worktrees" / nombre).exists())

    def test_rastro_posterior_a_la_aprobacion_no_cuenta(self):
        """Que se abra el visor DESPUÉS de teclear la fecha no prueba que se viera el
        contrato antes de aprobarlo — sería aprobar a ciegas y maquillarlo después."""
        nombre = self.crear_feature_aprobada_sin_rastro("rastro-tardio")
        manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self.dejar_rastro(nombre, fecha=manana)

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn(COMANDO_VISOR, resultado.stderr)

    def test_rastro_de_otra_unidad_no_sirve(self):
        nombre = self.crear_feature_aprobada_sin_rastro("ajena")
        self.dejar_rastro("001-otra-unidad-cualquiera")

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)

    def test_force_sigue_saltando_la_puerta_del_visor(self):
        """NO debe cambiar: `--force` (hotfix P0) es la única válvula, y sigue siéndolo."""
        pid = self.capturar("Hotfix urgente")
        self.evaluar(pid, ruta="bug")
        creada = self.ejecutar(self.unidad, "nueva", "bug", "produccion-caida", "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        ficha = next((self.ws / "docs/bugs").glob("[0-9][0-9][0-9]-produccion-caida.md"))
        texto = ficha.read_text(encoding="utf-8").replace(
            "P0 (producción caída) … P4 (cosmético)", "P0 (producción caída)"
        )
        ficha.write_text(texto, encoding="utf-8")

        resultado = self.ejecutar(
            self.unidad, "despachar", ficha.stem, "--force",
            "--motivo", "producción caída de verdad",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)


class GuiaDelVisorTest(WorkspaceBase):
    """R4 — `unidad.py nueva` y `unidad.py estado` imprimen el comando del visor."""

    def test_nueva_imprime_el_comando_del_visor_en_los_siguientes_pasos(self):
        pid = self.capturar("Nueva unidad")
        self.evaluar(pid)

        resultado = self.ejecutar(self.unidad, "nueva", "feature", "guia-visor", "--desde", pid)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn(COMANDO_VISOR, resultado.stdout)

    def test_estado_avisa_de_contratos_planificados_sin_aprobar(self):
        pid = self.capturar("Unidad pendiente")
        self.evaluar(pid)
        creada = self.ejecutar(self.unidad, "nueva", "feature", "pendiente-de-ok", "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)

        resultado = self.ejecutar(self.unidad, "estado")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        salida = resultado.stdout + resultado.stderr
        self.assertIn("001-pendiente-de-ok", salida)
        self.assertIn(COMANDO_VISOR, salida)

    def test_estado_no_avisa_cuando_no_hay_contratos_pendientes(self):
        resultado = self.ejecutar(self.unidad, "estado")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn(COMANDO_VISOR, resultado.stdout + resultado.stderr)


class LintAvisaDelVisorTest(WorkspaceBase):
    """R4 — `lint_metodo.py` avisa (WARN, no FAIL) por cada contrato pendiente sin rastro."""

    def lint(self):
        return subprocess.run(
            [sys.executable, str(self.linter), "--raiz", str(self.ws)],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )

    def test_lint_avisa_de_una_unidad_pendiente_sin_rastro(self):
        pid = self.capturar("Unidad para el linter")
        self.evaluar(pid)
        creada = self.ejecutar(self.unidad, "nueva", "feature", "para-lint", "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)

        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertIn("001-para-lint", salida)
        self.assertIn("WARN", salida)
        self.assertIn(COMANDO_VISOR, salida)

    def test_lint_no_avisa_si_ya_hay_rastro_del_visor(self):
        pid = self.capturar("Unidad ya vista")
        self.evaluar(pid)
        creada = self.ejecutar(self.unidad, "nueva", "feature", "ya-vista", "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        self.dejar_rastro("001-ya-vista")

        resultado = self.lint()
        salida = resultado.stdout + resultado.stderr

        self.assertNotIn(COMANDO_VISOR, salida)


if __name__ == "__main__":
    unittest.main()
