"""Unidad 046: la contraprueba del test portante, en normal y completo.

Un test vacuo —el que pasa tanto si el comportamiento existe como si no— atraviesa hoy la
revisión firmada, la suite completa y el OK del usuario sin que nadie lo note. El paso 7 de
`runbooks/bug.md` ya obliga a demostrar que el test muerde, pero solo en el carril bug.

Cubre los criterios del contrato:

- R1 — `unidad.py despachar` BLOQUEA una unidad normal o completa cuyo `**Criterio
  portante:**` siga sin rellenar, y la deja pasar cuando está puesto.
- R2, R3 — la plantilla de `hallazgos.md` trae el hueco de la contraprueba con sus tres
  apartados (la rotura, el rojo, y la restauración DEMOSTRADA).
- R5 — `runbooks/cierre.md` prohíbe `git stash` justo donde pide la contraprueba.
- R6 — en carril directo NO se pide: el carril entero existe para no pagar ceremonia.
- R7 — en carril bug NO se pide: allí ya existe por el par ROJO→VERDE del paso 7.
- R8 — el ADR está escrito, viaja en el bootstrap y el runbook lo cita.
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
METODO = RAIZ / "plantilla/docs/00-metodo"
SCRIPTS = METODO / "scripts"
PLANTILLAS = METODO / "plantillas"
HOY = datetime.date.today().isoformat()
ADR = "030-el-test-portante-tiene-que-morder.md"


class WorkspaceBase(unittest.TestCase):
    """Workspace de método mínimo pero real: scripts, plantillas y repo de código."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="criterio-portante-")
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

        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True)
        for nombre in (
            "especificacion.md", "directo.md", "bug.md", "hallazgos.md",
            "investigacion.md", "informe.md", "sintesis.md",
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

    def evaluar(self, pid, ruta="feature"):
        resultado = self.ejecutar(
            self.peticion, "evaluar", pid, "--ruta", ruta, "--investigacion", "ninguna",
            "--motivo", "contraste suficiente para encaminar",
            "--flujo", "REC-1", "--huella-flujo", "planos-v1",
            "--sha", self.sha, "--ruta-codigo", "app/terminal.py",
            "--conocimiento", "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def dejar_rastro(self, nombre):
        registro = self.ws / ".runtime" / "visor-contratos.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "a", encoding="utf-8") as rastro:
            rastro.write(f"{HOY}T09:00:00 contrato mostrado: {nombre}\n")
        # Unidad 107 (R5): la aprobación de verdad deja también el rastro del clic en la web.
        carpeta = self.ws / ".runtime" / "aprobaciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{nombre}-{HOY}.json").write_text(json.dumps({
            "unidad": nombre, "fecha": HOY,
            "ruta": f"docs/05-trabajo/{nombre}/especificacion.md",
            "huella": "0" * 64, "hora": f"{HOY}T09:00:00", "cliente": "127.0.0.1",
        }), encoding="utf-8")

    # -- fichas -------------------------------------------------------------------------

    CUERPO = (
        "\n\n# Contrato aprobado\n\n"
        "El usuario podrá completar el cambio solicitado sin alterar el comportamiento "
        "adyacente. La implementación conservará los datos existentes y mostrará un "
        "resultado verificable en la misma entrada que usa hoy, sin pedir un paso "
        "nuevo ni mover nada de sitio en el proceso habitual.\n\n"
        "## Criterios de aceptación\n\n"
        "- **R1** — el resultado solicitado aparece con un ejemplo real.\n"
        "- **R2** — el caso límite no cambia los datos existentes.\n\n"
        "## Verificación\n\n"
        "- **Nivel de test:** unitario, porque la conducta es una regla local.\n"
    )
    PORTANTE = "- **Criterio portante:** R1 — sin él la unidad entera no sirve de nada.\n"

    def ficha_lista(self, slug, carril=None, portante=False):
        """Unidad aprobada, con rastro del visor y todas las puertas anteriores en verde:
        lo único en juego es el criterio portante."""
        pid = self.capturar(f"Preparar {slug}")
        self.evaluar(pid, ruta="directo" if carril == "directo" else "feature")
        args = ["nueva", "feature", slug, "--desde", pid]
        if carril:
            args.append(f"--{carril}")
        creada = self.ejecutar(self.unidad, *args)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = f"001-{slug}"
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        texto = ruta.read_text(encoding="utf-8")
        texto = re.sub(r"^aprobado:.*$", f"aprobado: {HOY}", texto, count=1, flags=re.M)
        cabecera = texto[:texto.find("---", 4) + 3]
        cuerpo = self.CUERPO + (self.PORTANTE if portante else "")
        ruta.write_text(cabecera + cuerpo, encoding="utf-8")
        self.dejar_rastro(nombre)
        return nombre

    def ficha_de_bug(self, slug):
        pid = self.capturar(f"Bug {slug}")
        self.evaluar(pid, ruta="bug")
        creada = self.ejecutar(self.unidad, "nueva", "bug", slug, "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        ficha = next((self.ws / "docs/bugs").glob(f"[0-9][0-9][0-9]-{slug}.md"))
        texto = ficha.read_text(encoding="utf-8")
        texto = re.sub(r"^aprobado:.*$", f"aprobado: {HOY}", texto, count=1, flags=re.M)
        cabecera = texto[:texto.find("---", 4) + 3]
        ficha.write_text(cabecera + (
            "\n\n# El bug\n\n## Reporte\n\n"
            "El usuario esperaba ver el albarán 4471 al buscarlo por número y la pantalla "
            "aparece vacía. Pasa siempre desde el martes, con cualquier albarán del año "
            "en curso, y en el listado general sí sale. Severidad: P2, molesta pero hay "
            "un rodeo por el listado. Triaje: se arregla en esta tanda.\n\n"
            "## Verificación\n\n"
            "- El test del bug pasa de ROJO a VERDE sin tocarlo.\n"
        ), encoding="utf-8")
        self.dejar_rastro(ficha.stem)
        return ficha.stem


class PuertaDelCriterioPortanteTest(WorkspaceBase):
    """R1 — sin criterio portante declarado no se despacha una unidad normal ni completa.

    Esta puerta no tiene válvula `--force`: `--force` es la de producción caída y solo la
    abre un bug P0 (`runbooks/hotfix.md`), y los bugs no pagan esta puerta (R7).
    """

    def test_normal_sin_criterio_portante_bloquea_y_nombra_el_campo(self):
        nombre = self.ficha_lista("sin-portante")

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("Criterio portante", salida)
        self.assertFalse((self.ws / "worktrees" / nombre).exists())

    def test_normal_con_el_campo_puesto_despacha(self):
        nombre = self.ficha_lista("con-portante", portante=True)

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertTrue((self.ws / "worktrees" / nombre).exists())

    def test_completo_sin_criterio_portante_tambien_bloquea(self):
        nombre = self.ficha_lista("completo-sin-portante", carril="completo")

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)

    def test_el_hueco_de_la_plantilla_no_cuenta_como_declarado(self):
        """La pregunta no es la respuesta: dejar el `<...>` del molde tal cual es
        exactamente el caso que esta puerta existe para cazar."""
        nombre = self.ficha_lista("hueco-sin-rellenar")
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        with open(ruta, "a", encoding="utf-8") as ficha:
            ficha.write("- **Criterio portante:** <cuál de los R* es el que sostiene todo>\n")

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)

class CarrilesQueNoLaPaganTest(WorkspaceBase):
    """R6 y R7 — el acotamiento es un criterio, no un comentario."""

    def test_directo_sin_el_campo_despacha_igual(self):
        nombre = self.ficha_lista("directo-sin-portante", carril="directo")

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertNotIn("Criterio portante", salida)

    def test_bug_sin_el_campo_despacha_igual(self):
        nombre = self.ficha_de_bug("albaran-no-aparece")

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertNotIn("Criterio portante", salida)


class PlantillasYRunbookTest(unittest.TestCase):
    """R2, R3, R5, R8 — el hueco, la demostración y el ADR, en los ficheros del método."""

    def test_la_plantilla_de_especificacion_trae_el_campo(self):
        texto = (PLANTILLAS / "especificacion.md").read_text(encoding="utf-8")
        self.assertIn("**Criterio portante:**", texto)

    def test_la_plantilla_del_carril_directo_no_lo_pide(self):
        texto = (PLANTILLAS / "directo.md").read_text(encoding="utf-8")
        self.assertNotIn("Criterio portante", texto)

    def test_la_plantilla_de_hallazgos_trae_los_tres_apartados(self):
        texto = (PLANTILLAS / "hallazgos.md").read_text(encoding="utf-8")
        self.assertIn("## Contraprueba del criterio portante", texto)
        for apartado in ("rotura:", "rojo:", "restauracion:"):
            self.assertIn(apartado, texto, f"falta el apartado «{apartado}»")
        # R3: la restauración se DEMUESTRA con los dos comandos, no se afirma.
        self.assertIn("git diff HEAD", texto)
        self.assertIn("git rev-parse HEAD", texto)

    def test_el_cierre_pide_la_contraprueba_y_prohibe_git_stash_al_lado(self):
        texto = (METODO / "runbooks/cierre.md").read_text(encoding="utf-8")
        self.assertIn("contraprueba", texto.lower())
        bloque = texto[texto.lower().index("contraprueba"):]
        bloque = bloque[:bloque.index("\n3. **Fusionar**")]
        self.assertIn("git stash", bloque)
        self.assertIn("git diff HEAD", bloque)
        self.assertIn("normal", bloque)

    def test_el_adr_existe_y_el_runbook_lo_cita(self):
        adr = METODO / "decisiones" / ADR
        self.assertTrue(adr.exists(), f"falta {adr}")
        texto = adr.read_text(encoding="utf-8")
        for seccion in ("## Contexto", "## Decisión", "## Consecuencias"):
            self.assertIn(seccion, texto)
        cierre = (METODO / "runbooks/cierre.md").read_text(encoding="utf-8")
        self.assertIn("ADR-030", cierre)

    def test_el_adr_viaja_al_workspace(self):
        """Un fichero del método que no está en el bootstrap no llega a ningún proyecto."""
        bootstrap = (RAIZ / "visor/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn(ADR, bootstrap)

    def test_el_carril_bug_no_cambia(self):
        """R7 — la contraprueba del paso 7 sigue donde estaba, con su prohibición."""
        texto = (METODO / "runbooks/bug.md").read_text(encoding="utf-8")
        self.assertIn("nunca con `git stash`", texto)
        self.assertNotIn("Criterio portante", texto)


if __name__ == "__main__":
    unittest.main()
