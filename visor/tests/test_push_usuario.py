"""Unidad 018: `push: usuario` — el método nunca escribe en el remoto por su cuenta.

Diseño: investigación 007 (`docs/05-trabajo/archivo/007-metodo-sin-tocar-remoto/hallazgos.md`),
tabla R2, puntos 3-6. Los puntos de LECTURA (fetch/clone/pull) no cambian y esta suite no los
toca. `HookPostCierreDeadlockTest` sí toca el hook `pre-push`: es la regresión del bug 020
(el recibo/aviso que este mismo módulo prueba arriba quedaba vetado por ese hook).
"""

import importlib.util
import json
import os
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
RUNBOOKS = RAIZ / "plantilla/docs/00-metodo/runbooks"
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
HOOK = RAIZ / "plantilla/githooks/pre-push"

# Los 8 runbooks de tipo con el paso "commit, push y PR" del constructor (007, R2 punto 3).
RUNBOOKS_DE_TIPO = ("feature", "bug", "directo", "migracion", "refactor", "hotfix",
                    "expres", "documentacion")


def cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


class ModoPushEnRepoConfigTest(unittest.TestCase):
    """R4: `repo_config.py` expone la clave con el mismo patrón que `remoto`/`rama_principal`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="modo-push-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        self.repo_config = cargar("repo_config", SCRIPTS / "repo_config.py")

    def escribir(self, texto):
        (self.ws / "repos.yaml").write_text(texto, encoding="utf-8")

    def test_ausente_es_agente(self):
        # R3: ningún workspace existente migra — sin la clave, todo sigue como hoy.
        self.escribir("codigo:\n  ruta_local: main/\n  rama_principal: main\n")
        self.assertEqual(self.repo_config.modo_push(self.ws), "agente")

    def test_usuario_se_lee(self):
        self.escribir("codigo:\n  ruta_local: main/\n  push: usuario\n")
        self.assertEqual(self.repo_config.modo_push(self.ws), "usuario")

    def test_valor_invalido_falla_nombrando_los_validos(self):
        self.escribir("codigo:\n  ruta_local: main/\n  push: banana\n")
        with self.assertRaises(self.repo_config.RepoConfigError) as capturado:
            self.repo_config.modo_push(self.ws)
        mensaje = str(capturado.exception)
        self.assertIn("push", mensaje)
        self.assertIn("agente", mensaje)
        self.assertIn("usuario", mensaje)

    def test_el_comentario_de_ejemplo_no_activa_el_modo(self):
        # `push:` dentro de un comentario es documentación, no configuración.
        self.escribir("codigo:\n  ruta_local: main/\n  #  push: usuario   # ejemplo\n")
        self.assertEqual(self.repo_config.modo_push(self.ws), "agente")

    def test_repo_code_rechaza_el_valor_invalido(self):
        # El valor inválido no puede pasar desapercibido a los consumidores del fichero.
        self.escribir("codigo:\n  ruta_local: main/\n  push: banana\n")
        with self.assertRaises(self.repo_config.RepoConfigError):
            self.repo_config.repo_code(self.ws)


class BootstrapDocumentaPushTest(unittest.TestCase):
    """R4: el `repos.yaml` generado documenta la clave con sus dos valores."""

    def setUp(self):
        sys.path.insert(0, str(RAIZ / "visor"))
        self.addCleanup(sys.path.remove, str(RAIZ / "visor"))
        self.bootstrap = cargar("bootstrap_018", BOOTSTRAP)

    def test_repos_yaml_generado_documenta_push(self):
        texto = self.bootstrap.generar_repos_yaml("demo", "git@example.com:demo/demo.git")
        self.assertRegex(texto, r"(?m)^\s*push:\s*agente")
        self.assertIn("usuario", texto)

    def test_el_defecto_generado_se_comporta_como_hoy(self):
        texto = self.bootstrap.generar_repos_yaml("demo", "git@example.com:demo/demo.git")
        tmp = tempfile.TemporaryDirectory(prefix="repos-generado-")
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        (ws / "repos.yaml").write_text(texto, encoding="utf-8")
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        repo_config = cargar("repo_config", SCRIPTS / "repo_config.py")
        self.assertEqual(repo_config.modo_push(ws), "agente")


class RunbooksCondicionalesTest(unittest.TestCase):
    """R1/R2: el texto y el código cuentan lo mismo (grep estructural por runbook)."""

    def test_los_ocho_runbooks_condicionan_el_paso_de_push(self):
        for nombre in RUNBOOKS_DE_TIPO:
            with self.subTest(runbook=nombre):
                texto = (RUNBOOKS / f"{nombre}.md").read_text(encoding="utf-8")
                self.assertIn("`push: usuario`", texto)
                self.assertIn("commit local", texto)
                self.assertIn("gh pr create", texto)
                self.assertIn("hallazgos.md", texto)

    def test_cierre_declara_la_excepcion_del_camino_b(self):
        texto = (RUNBOOKS / "cierre.md").read_text(encoding="utf-8")
        self.assertIn("`push: usuario`", texto)
        self.assertIn("SIEMPRE", texto)
        self.assertIn("git -C main push origin main", texto)


class WorkspaceGitTest(unittest.TestCase):
    """Base común: meta-repo con `main/` clonado de un remoto bare local."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="push-usuario-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ws = self.base / "workspace"
        (self.ws / "docs/05-trabajo").mkdir(parents=True)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in ("control_plane.py", "entrega.py", "lease.py", "lint_ci.py",
                       "lint_cierre.py", "lint_metodo.py", "peticion.py", "repo_config.py",
                       "subagente.py", "unidad.py", "veredicto_lint.py", "workspace_paths.py"):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.unidad = scripts / "unidad.py"
        self.linter = scripts / "lint_metodo.py"

        self.remoto = self.base / "remoto.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.remoto)],
                       check=True, capture_output=True)
        semilla = self.base / "semilla"
        semilla.mkdir()
        self.git(semilla, "init", "-b", "main")
        self.git(semilla, "config", "user.name", "Test")
        self.git(semilla, "config", "user.email", "test@example.com")
        (semilla / "app.py").write_text("print('ok')\n", encoding="utf-8")
        self.git(semilla, "add", "-A")
        self.git(semilla, "commit", "-m", "base")
        self.git(semilla, "remote", "add", "origin", str(self.remoto))
        self.git(semilla, "push", "-u", "origin", "main")

        self.repo = self.ws / "main"
        subprocess.run(["git", "clone", str(self.remoto), str(self.repo)],
                       check=True, capture_output=True)
        self.git(self.repo, "config", "user.name", "Test")
        self.git(self.repo, "config", "user.email", "test@example.com")

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              text=True, encoding="utf-8", errors="replace",
                              capture_output=True).stdout.strip()

    def repos_yaml(self, modo=None):
        texto = ("codigo:\n  nombre: demo\n"
                 f"  remoto: {self.remoto}\n"
                 "  rama_principal: main\n  ruta_local: main/\n")
        if modo:
            texto += f"  push: {modo}\n"
        (self.ws / "repos.yaml").write_text(texto, encoding="utf-8")

    def commit_local_sin_empujar(self):
        (self.repo / "app.py").write_text("print('mas')\n", encoding="utf-8")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-m", "trabajo fusionado en local")

    def sha_remoto(self):
        return self.git(self.remoto, "rev-parse", "main")

    def ejecutar(self, script, *args):
        return subprocess.run([sys.executable, str(script), *args], cwd=self.ws,
                              text=True, encoding="utf-8", errors="replace",
                              capture_output=True)


class AvisoPostCierreTest(WorkspaceGitTest):
    """R2/R3: el aviso de la principal sin empujar (007, R2 punto 6).

    Se invoca la función real del cierre (`unidad.py`), no el comando completo: el ritual
    entero exige revisor, recibo y estados; lo que esta unidad cambia son estas ~10 líneas.
    """

    def cargar_unidad(self):
        scripts = str(self.ws / "docs/00-metodo/scripts")
        sys.path.insert(0, scripts)
        self.addCleanup(sys.path.remove, scripts)
        for nombre in ("unidad", "repo_config", "workspace_paths", "control_plane",
                       "lease", "peticion"):
            sys.modules.pop(nombre, None)
        return cargar("unidad", self.unidad)

    def test_con_push_usuario_es_un_recibo_y_el_remoto_no_avanza(self):
        self.repos_yaml("usuario")
        antes = self.sha_remoto()
        self.commit_local_sin_empujar()
        modulo = self.cargar_unidad()

        salida = self.avisar(modulo)

        self.assertEqual(self.sha_remoto(), antes)
        self.assertIn("push: usuario", salida)
        # El comando imprime la ruta REAL del repo (aquí, absoluta en tmp), no el literal
        # "main": se afirma el prefijo y el final, no la ruta.
        self.assertIn("git -C ", salida)
        self.assertIn("push origin main", salida)
        self.assertNotIn("WARN", salida)
        self.assertNotIn("base vieja", salida)

    def test_sin_la_clave_el_warn_es_identico_al_de_hoy(self):
        self.repos_yaml()
        self.commit_local_sin_empujar()
        modulo = self.cargar_unidad()

        salida = self.avisar(modulo)

        self.assertIn("WARN", salida)
        self.assertIn("base vieja", salida)
        self.assertIn("git -C ", salida)
        self.assertIn("push origin main", salida)

    def test_sin_commits_pendientes_no_dice_nada(self):
        self.repos_yaml("usuario")
        modulo = self.cargar_unidad()

        self.assertEqual(self.avisar(modulo).strip(), "")

    def avisar(self, modulo):
        import io
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            modulo.avisar_principal_sin_empujar(self.repo, "main")
        return buffer.getvalue()


class HookPostCierreDeadlockTest(WorkspaceGitTest):
    """020: el recibo/aviso post-cierre, ejecutado tal cual se imprime, ya no lo veta el
    propio hook `pre-push` que el método instala.

    Reproducción end-to-end sobre el fixture con remoto bare: `unidad.py cerrar` real (borra
    la rama NNN local, reconcilia el proceso a `terminal` y anota `fusion:` en la ficha) y
    LUEGO se ejecuta el comando exacto del recibo/aviso contra ese mismo remoto, con el hook
    real instalado. Antes del arreglo, el push moría con "PUSH BLOQUEADO" pese a ser
    exactamente el camino que la 018 promete.
    """

    def setUp(self):
        super().setUp()
        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PLANTILLAS / "bug.md", plantillas / "bug.md")
        (self.ws / "docs/bugs").mkdir(parents=True, exist_ok=True)
        (self.ws / "docs/05-trabajo/peticiones").mkdir(parents=True, exist_ok=True)
        conocimiento = self.ws / "docs/decisiones/004-paleta.md"
        conocimiento.parent.mkdir(parents=True, exist_ok=True)
        conocimiento.write_text("# Paleta vigente\n", encoding="utf-8")
        # El linter REAL exige un workspace bootstrapeado entero; aquí se prueba el hook y el
        # cierre, no el linter (ya tiene su propia suite) — como ya hace
        # `test_cierre_archiva_antes_del_lint_y_reconcilia_al_final` en test_peticion_unidad.py.
        (self.ws / "docs/00-metodo/scripts/lint_metodo.py").write_text(
            "import sys\nsys.exit(0)\n", encoding="utf-8"
        )
        self.peticion = self.ws / "docs/00-metodo/scripts/peticion.py"

        # El hook real, instalado como lo hace bootstrap.py (core.hooksPath -> .githooks).
        githooks = self.ws / ".githooks"
        githooks.mkdir(parents=True, exist_ok=True)
        hook = githooks / "pre-push"
        shutil.copy2(HOOK, hook)
        hook.chmod(hook.stat().st_mode | 0o111)
        self.git(self.repo, "config", "core.hooksPath", str(githooks.resolve()))
        # `despachar` arranca cada rama NNN desde `origin/<principal>`; con el auto-tracking
        # de git, `git branch -d` mediría el merge contra ESA rama remota en vez de contra
        # HEAD, y como el modo `push: usuario` deja `origin/main` deliberadamente atrás
        # (es la ventana que el recibo/aviso describe), la borrada real fallaría por un
        # motivo ajeno a este bug. Sin tracking, `-d` mide contra HEAD como pretende el
        # cierre (runbooks/cierre.md: "borra el worktree y la rama local").
        self.git(self.repo, "config", "branch.autoSetupMerge", "false")

    def ejecutar_script(self, script, *args):
        return subprocess.run(
            [sys.executable, str(script), *args], cwd=self.ws,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )

    def recibos_de_ejecucion(self, nombre):
        """Los recibos que el control plane deja al lanzar constructor y revisor."""
        carpeta = self.ws / ".runtime/ejecuciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        for rol in ("constructor", "revisor"):
            recibo = {
                "schema": "ejecucion/v1",
                "id": rol,
                "unidad": nombre,
                "harness": ("subagente-del-padre" if rol == "constructor" else "claude"),
                "rol": rol,
                "lease": {"session_id": f"{rol}-{nombre}", "fencing": {}},
                "exit_code": 0,
                "resultado": "ok",
            }
            if rol == "constructor":
                final = self.git(self.repo, "rev-parse", "HEAD")
                inicial = self.git(self.repo, "rev-parse", f"{final}^")
                recibo["git"] = {
                    "inicial": {"head": inicial,
                                "tree": self.git(self.repo, "rev-parse", f"{inicial}^{{tree}}"),
                                "plan": {"marcadas": 0, "totales": 1}},
                    "final": {"head": final,
                              "tree": self.git(self.repo, "rev-parse", f"{final}^{{tree}}"),
                              "status_porcelain": [], "materializada": False},
                }
                recibo["trabajo"] = {
                    "acreditado": True, "plan": {"marcadas": 1, "totales": 1}}
            (carpeta / f"{nombre}-{rol}.json").write_text(
                json.dumps(recibo, ensure_ascii=False), encoding="utf-8")

    def cerrar_bug_fusionado(self, slug="hook-post-cierre"):
        """Lleva un bug hasta `unidad.py cerrar` en verde, con el trabajo YA fusionado en
        `main` como lo dejaría el padre antes de cerrar. Devuelve (resultado_cerrar, nombre)."""
        capturada = self.ejecutar_script(
            self.peticion, "capturar", "--resumen", "Bug de prueba",
            "--texto", "Repro determinista", "--autor", "Test",
        )
        self.assertEqual(capturada.returncode, 0, capturada.stderr)
        pid = re.search(r"P-\d{8}-[a-f0-9]{8}", capturada.stdout).group(0)
        sha_base = self.git(self.repo, "rev-parse", "HEAD")
        evaluada = self.ejecutar_script(
            self.peticion, "evaluar", pid, "--ruta", "bug", "--investigacion", "ninguna",
            "--motivo", "contraste suficiente para encaminar", "--flujo", "REC-1",
            "--huella-flujo", "planos-v1", "--sha", sha_base,
            "--ruta-codigo", "app.py", "--conocimiento", "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)

        creada = self.ejecutar_script(self.unidad, "nueva", "bug", slug, "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        ficha = next((self.ws / "docs/bugs").glob(f"[0-9][0-9][0-9]-{slug}.md"))
        nombre = ficha.stem

        # El contrato mínimo (aprobado + prosa real) y el despacho REAL: es `despachar` quien
        # registra `metadata.base_sha` en el proceso — sin él el hook no tiene con qué medir
        # si la rama enlazada contiene de verdad el commit fusionado.
        texto = ficha.read_text(encoding="utf-8")
        texto = re.sub(r"^aprobado:.*$", "aprobado: 2026-08-18", texto, count=1, flags=re.M)
        # R2/R3 del bug 054: sin este rastro `despachar` bloquea aunque `aprobado:` tenga fecha.
        registro = self.ws / ".runtime" / "visor-contratos.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "a", encoding="utf-8") as rastro:
            rastro.write(f"2026-08-18T00:00:00 contrato mostrado: {nombre}\n")
        texto = texto.replace(
            "- **Qué pasa de verdad:** <el síntoma, con ejemplo concreto: datos, pasos, "
            "resultado>",
            "- **Qué pasa de verdad:** el arreglo determinista sobre app.py reproducido en "
            "un workspace de juguete con remoto bare, exactamente como pide el contrato "
            "de esta unidad de prueba, con pasos deterministas y verificables.",
        )
        texto = texto.replace(
            "BUG: <síntoma en una frase>",
            "BUG: el push del usuario se queda bloqueado tras un cierre legítimo")
        ficha.write_text(texto, encoding="utf-8")

        despachada = self.ejecutar_script(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        worktree = self.ws / "worktrees" / nombre
        self.assertTrue(worktree.is_dir(), despachada.stdout + despachada.stderr)

        # El trabajo se fusiona en main — lo que hace el padre antes de pedir el cierre.
        (worktree / "app.py").write_text("print('arreglo')\n", encoding="utf-8")
        self.git(worktree, "add", "-A")
        self.git(worktree, "commit", "-m", "arregla el bug")
        self.git(self.repo, "merge", "--ff-only", nombre)
        self.git(self.repo, "worktree", "remove", str(worktree))

        texto = ficha.read_text(encoding="utf-8")
        texto = re.sub(r"^estado:\s*\S+", "estado: en_revision", texto, count=1, flags=re.M)
        texto = texto.replace(
            "- **Revisión (revisor fresco, ANTES del merge):** LIMPIO | HUECOS DE CORRECCIÓN "
            "→ <cuáles;\n  cada uno vuelve al subagente antes del merge> · Fecha: YYYY-MM-DD",
            "- **Revisión (revisor fresco, ANTES del merge):** LIMPIO · Fecha: 2026-08-18",
        )
        ficha.write_text(texto, encoding="utf-8")

        # Desde el bug 034 (R4) las puertas del recibo y del carril aplican también a los
        # bugs: entregan código por una rama exactamente igual que una unidad. Los recibos
        # de constructor y revisor son los que `ejecucion.py` deja en cada lanzamiento.
        self.recibos_de_ejecucion(nombre)

        resultado = self.ejecutar_script(
            self.unidad, "cerrar", nombre, "--ok-usuario", "2026-08-18",
        )
        return resultado, nombre

    def test_push_usuario_recibo_post_cierre_ya_no_esta_bloqueado(self):
        self.repos_yaml("usuario")
        antes = self.sha_remoto()

        cerrado, nombre = self.cerrar_bug_fusionado("push-usuario")

        self.assertEqual(cerrado.returncode, 0, cerrado.stdout + cerrado.stderr)
        self.assertIn("push: usuario", cerrado.stdout)
        comando = re.search(r"git -C \S+ push origin main", cerrado.stdout)
        self.assertIsNotNone(comando, cerrado.stdout)
        # La rama NNN local ya no existe: es justo la reproducción del deadlock (020).
        ramas = self.git(self.repo, "branch", "--list", nombre)
        self.assertEqual(ramas, "")
        self.assertEqual(self.sha_remoto(), antes)

        push = subprocess.run(comando.group(0).split(), cwd=self.ws,
                              text=True, encoding="utf-8", errors="replace", capture_output=True)

        self.assertEqual(push.returncode, 0, push.stdout + push.stderr)
        self.assertNotIn("PUSH BLOQUEADO", push.stderr)
        self.assertNotEqual(self.sha_remoto(), antes)

    def test_warn_modo_agente_post_cierre_ya_no_esta_bloqueado(self):
        self.repos_yaml()  # sin `push:` → modo agente, el WARN clásico
        antes = self.sha_remoto()

        cerrado, nombre = self.cerrar_bug_fusionado("warn-agente")

        self.assertEqual(cerrado.returncode, 0, cerrado.stdout + cerrado.stderr)
        self.assertIn("WARN", cerrado.stdout)
        self.assertIn("base vieja", cerrado.stdout)
        comando = re.search(r"git -C \S+ push origin main", cerrado.stdout)
        self.assertIsNotNone(comando, cerrado.stdout)
        ramas = self.git(self.repo, "branch", "--list", nombre)
        self.assertEqual(ramas, "")

        push = subprocess.run(comando.group(0).split(), cwd=self.ws,
                              text=True, encoding="utf-8", errors="replace", capture_output=True)

        self.assertEqual(push.returncode, 0, push.stdout + push.stderr)
        self.assertNotIn("PUSH BLOQUEADO", push.stderr)
        self.assertNotEqual(self.sha_remoto(), antes)

    def test_commit_directo_a_main_sigue_bloqueado_tras_un_cierre_legitimo(self):
        # No se relaja el bloqueo de los pushes de verdad no trazados (alcance del bug 020):
        # un commit directo posterior al recibo, sin pasar por ninguna unidad, sigue vetado.
        self.repos_yaml("usuario")
        cerrado, _ = self.cerrar_bug_fusionado("push-usuario-directo")
        self.assertEqual(cerrado.returncode, 0, cerrado.stdout + cerrado.stderr)
        comando = re.search(r"git -C \S+ push origin main", cerrado.stdout)
        self.assertIsNotNone(comando, cerrado.stdout)
        subprocess.run(comando.group(0).split(), cwd=self.ws,
                       text=True,
                       encoding="utf-8", errors="replace", capture_output=True, check=True)

        (self.repo / "intruso.txt").write_text("commit directo sin unidad\n", encoding="utf-8")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-m", "directo")

        push = subprocess.run(
            ["git", "-C", str(self.repo), "push", "origin", "main"],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )

        self.assertNotEqual(push.returncode, 0)
        self.assertIn("PUSH BLOQUEADO", push.stderr)


class LintModoPushTest(unittest.TestCase):
    """R5: con el modo activo, los commits sin empujar son estado esperado, no error.

    Sobre un workspace REAL recién bootstrapeado (el único que sale verde entero): si el
    modo convirtiera el linter en rojo perpetuo, el aviso dejaría de leerse.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-push-usuario-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp.name, ignore_errors=True))
        self.base = Path(self.tmp.name)
        planos = self.base / "planos"
        (planos / "especificaciones/01-constitution").mkdir(parents=True)
        (planos / "especificaciones/02-flows").mkdir()
        (planos / "planos.json").write_text(
            '{"version": 2, "proyecto": "demo", "titulo": "Demo", '
            '"contrato": {"frase": "Una demostración"}, "actividades": []}',
            encoding="utf-8",
        )
        (planos / "especificaciones/01-constitution/constitution.md").write_text(
            "# Constitución\n", encoding="utf-8"
        )
        self.ws = self.base / "demo-agents"
        entorno = dict(os.environ)
        entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(self.base / "registro.json")
        creado = subprocess.run(
            [sys.executable, str(BOOTSTRAP), "--planos", str(planos),
             "--destino", str(self.ws)],
            cwd=RAIZ, text=True,
            encoding="utf-8", errors="replace", capture_output=True, env=entorno,
        )
        self.assertEqual(creado.returncode, 0, creado.stdout + creado.stderr)
        self.repo = self.ws / "main"
        self.remoto = self.base / "remoto.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.remoto)],
                       check=True, capture_output=True)
        self.git("remote", "add", "origin", str(self.remoto))
        # --no-verify: el hook `pre-push` del método vigila el Camino B y aquí solo estamos
        # montando el estado inicial del fixture. El hook no se toca (fuera de alcance).
        self.git("push", "--no-verify", "-u", "origin", "main")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def declarar(self, modo):
        repos = self.ws / "repos.yaml"
        texto = repos.read_text(encoding="utf-8")
        if modo is None:
            texto = re.sub(r"(?m)^\s*push:.*\n", "", texto)
        else:
            texto = re.sub(r"(?m)^(\s*push:)\s*\S+", rf"\1 {modo}", texto)
        repos.write_text(texto, encoding="utf-8")

    def commit_local_sin_empujar(self):
        (self.repo / "PENDIENTE.md").write_text("trabajo fusionado en local\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "unidad fusionada en local")

    def lint(self):
        return subprocess.run(
            [sys.executable, str(self.ws / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )

    def test_informa_el_conteo_sin_fallar(self):
        self.declarar("usuario")
        self.commit_local_sin_empujar()

        resultado = self.lint()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        lineas = [l for l in resultado.stdout.splitlines() if "push: usuario" in l]
        self.assertEqual(len(lineas), 1, resultado.stdout)
        self.assertIn("1 commit", lineas[0])
        self.assertIn("git -C main push origin main", lineas[0])
        self.assertIn("OK", lineas[0])
        self.assertNotIn("FAIL", lineas[0])
        self.assertNotIn("WARN", lineas[0])

    def test_sin_la_clave_no_aparece_el_informativo(self):
        # R3: sin la clave, el linter dice exactamente lo de hoy.
        self.declarar(None)
        self.commit_local_sin_empujar()

        resultado = self.lint()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("push: usuario", resultado.stdout)

    def test_valor_invalido_falla_en_claro(self):
        self.declarar("banana")

        resultado = self.lint()

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("push", salida)
        self.assertIn("agente | usuario", salida)


if __name__ == "__main__":
    unittest.main()
