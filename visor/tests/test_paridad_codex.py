"""Unidad 100 — paridad Codex = Claude: el método entero funciona igual con los dos harness.

Hasta la 100, tres piezas del método eran solo-Claude y `roles.md` lo daba por inevitable:
la tabla de la regla 10 (identificadores de Anthropic), el veto de `--modelo` en
`ejecucion.py --harness codex`, y los hooks (`.claude/settings.json`, con
`$CLAUDE_PROJECT_DIR`). La investigación de la petición P-20260827-9630b5c1 demostró contra
`codex-cli 0.149.0` que las tres tienen equivalente, y las pruebas de riesgo del paso 0 de
esta unidad corrigieron tres suposiciones de esa investigación (`hallazgos.md`):

  · `codex exec --json` NO emite `model_slug`: son cuatro eventos y ninguno habla de modelo.
    Lo que de verdad corrió está en el `turn_context` del rollout de la sesión, dentro del
    propio `CODEX_HOME` efímero — por eso el argv de codex pierde `--ephemeral`.
  · Los hooks del repo tienen DOS puertas y las dos fallan CALLADAS: `--ignore-user-config`
    apaga también el `.codex/` del repo, y sin `--dangerously-bypass-hook-trust` el hook no
    corre y no se dice nada.
  · `-s read-only` es absoluto (ignora `--add-dir` y `writable_roots`), así que el revisor
    Codex conserva la frontera del revisor Claude (enmienda del padre a R4, 27-08).

Los tests de aquí usan DOBLES del binario (`codex debug models`, `codex exec`): la prueba
contra el binario real es la de sistema de R4, y su evidencia vive en `hallazgos.md`.
"""
import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(RAIZ / "visor") not in sys.path:
    sys.path.insert(0, str(RAIZ / "visor"))
import repo_config                      # noqa: E402
import ejecucion                        # noqa: E402
import bootstrap                        # noqa: E402

# El catálogo tal y como lo imprime `codex debug models` (recortado a lo que se usa). Los
# slugs de aquí son DATOS DE PRUEBA, no la tabla: la tabla se deriva por posición.
CATALOGO = {
    "models": [
        {"slug": "modelo-punta", "visibility": "list", "priority": 1,
         "default_reasoning_level": "low",
         "supported_reasoning_levels": [{"effort": e} for e in
                                        ("low", "medium", "high", "xhigh", "max")]},
        {"slug": "modelo-segundo", "visibility": "list", "priority": 2,
         "default_reasoning_level": "medium",
         "supported_reasoning_levels": [{"effort": e} for e in
                                        ("low", "medium", "high", "xhigh")]},
        {"slug": "modelo-oculto", "visibility": "hide", "priority": 3,
         "default_reasoning_level": "medium",
         "supported_reasoning_levels": [{"effort": "medium"}]},
        {"slug": "modelo-pequeno", "visibility": "list", "priority": 26,
         "default_reasoning_level": "high",
         "supported_reasoning_levels": [{"effort": e} for e in ("low", "medium", "high")]},
    ]
}


def instalar_ejecutable(carpeta, nombre, cuerpo):
    """Un doble del binario en `carpeta`, ejecutable en las tres plataformas."""
    if os.name == "nt":
        script = carpeta / f"{nombre}.py"
        script.write_text(cuerpo, encoding="utf-8")
        (carpeta / f"{nombre}.bat").write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return carpeta / f"{nombre}.bat"
    destino = carpeta / nombre
    destino.write_text("#!/usr/bin/env python3\n" + cuerpo, encoding="utf-8")
    destino.chmod(destino.stat().st_mode | stat.S_IXUSR)
    return destino


CUERPO_CATALOGO = """import json, pathlib, sys
CATALOGO = %s
CONTADOR = pathlib.Path(%s)
if sys.argv[1:3] == ['debug', 'models']:
    CONTADOR.write_text(str(int(CONTADOR.read_text() or 0) + 1) if CONTADOR.exists() else '1')
    print(json.dumps(CATALOGO))
    raise SystemExit(0)
raise SystemExit(1)
"""


class BaseCatalogo(unittest.TestCase):
    """Un `codex` de mentira que sabe responder `debug models` y cuenta cuántas veces."""

    catalogo = CATALOGO

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="paridad-codex-")
        self.addCleanup(self.temporal.cleanup)
        self.base = Path(self.temporal.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.contador = self.base / "consultas.txt"
        self.codex = instalar_ejecutable(
            self.bin, "codex",
            CUERPO_CATALOGO % (json.dumps(self.catalogo), repr(str(self.contador))))
        repo_config.olvidar_catalogo_codex()
        self.addCleanup(repo_config.olvidar_catalogo_codex)

    def consultas(self):
        return int(self.contador.read_text()) if self.contador.exists() else 0

    def plan(self, carril, rol, **kwargs):
        return repo_config.plan_de_modelo(
            carril, rol, harness="codex", ejecutable_codex=str(self.codex), **kwargs)


# ============================================================ R1 · la tabla, por harness
class TablaPorHarnessTest(BaseCatalogo):

    def test_el_constructor_codex_sale_en_el_modelo_de_punta_del_catalogo(self):
        # No hay slug escrito en el código: es el de `priority` más baja de los visibles.
        self.assertEqual(self.plan("normal", "constructor").modelo, "modelo-punta")

    def test_el_revisor_codex_jamas_repite_el_modelo_del_constructor(self):
        # Regla 10: dos instancias del mismo modelo comparten puntos ciegos.
        for carril in repo_config.CARRILES:
            with self.subTest(carril=carril):
                constructor = self.plan(carril, "constructor")
                revisor = self.plan(carril, "revisor")
                self.assertNotEqual(revisor.modelo, constructor.modelo)
                self.assertEqual(revisor.modelo, "modelo-segundo")

    def test_lo_documental_sale_en_el_modelo_pequeno_del_catalogo(self):
        self.assertEqual(
            self.plan("completo", "constructor", documental=True).modelo, "modelo-pequeno")

    def test_los_modelos_ocultos_no_se_eligen_jamas(self):
        elegidos = {self.plan(c, r).modelo
                    for c in repo_config.CARRILES for r in ("constructor", "revisor")}
        self.assertNotIn("modelo-oculto", elegidos)

    def test_el_esfuerzo_del_carril_se_traduce_al_vocabulario_de_codex(self):
        self.assertEqual(self.plan("directo", "constructor").esfuerzo, "low")
        self.assertEqual(self.plan("expres", "constructor").esfuerzo, "low")
        self.assertEqual(self.plan("normal", "constructor").esfuerzo, "medium")
        self.assertEqual(self.plan("completo", "constructor").esfuerzo, "high")
        self.assertEqual(self.plan("hotfix", "constructor").esfuerzo, "high")

    def test_el_catalogo_se_consulta_una_sola_vez_por_sesion(self):
        for carril in repo_config.CARRILES:
            self.plan(carril, "constructor")
            self.plan(carril, "revisor")
        self.assertEqual(self.consultas(), 1)

    def test_el_codigo_no_memoriza_ningun_slug_de_openai(self):
        # Los slugs caducan; el catálogo del binario es la única fuente que no envejece.
        fuente = (SCRIPTS / "repo_config.py").read_text(encoding="utf-8")
        self.assertNotIn("gpt-", fuente)

    def test_claude_sigue_saliendo_de_la_tabla_de_siempre(self):
        # R6: el harness por defecto no cambia ni de modelo ni de vocabulario de esfuerzo.
        plan = repo_config.plan_de_modelo("normal", "constructor")
        self.assertEqual(plan.modelo, "claude-opus-5")
        self.assertEqual(plan.esfuerzo, "medio")
        self.assertEqual(self.consultas(), 0, "claude no consulta el catálogo de codex")


class CatalogoQueFallaTest(BaseCatalogo):

    def test_un_catalogo_ilegible_se_rechaza_nombrando_la_salida(self):
        instalar_ejecutable(self.bin, "codex", "print('esto no es json')\n")
        repo_config.olvidar_catalogo_codex()

        with self.assertRaises(repo_config.RepoConfigError) as capturado:
            self.plan("normal", "constructor")
        mensaje = str(capturado.exception)
        self.assertIn("SALIDA:", mensaje)
        self.assertIn("codex debug models", mensaje)

    def test_un_catalogo_con_un_solo_modelo_no_le_da_al_revisor_el_del_constructor(self):
        instalar_ejecutable(self.bin, "codex", CUERPO_CATALOGO % (
            json.dumps({"models": [CATALOGO["models"][0]]}), repr(str(self.contador))))
        repo_config.olvidar_catalogo_codex()

        with self.assertRaises(repo_config.RepoConfigError) as capturado:
            self.plan("normal", "revisor")
        self.assertIn("SALIDA:", str(capturado.exception))


# ================================================ R2 · argv de codex y recibo acreditado
CUERPO_EXEC = """import json, os, pathlib, re, sys
DESTINO = pathlib.Path(%s)
argv = sys.argv[1:]
DESTINO.write_text(json.dumps({'argv': argv, 'cwd': os.getcwd(),
                               'codex_home': os.environ.get('CODEX_HOME')}), encoding='utf-8')
# El binario real escribe el rollout de la sesión dentro de CODEX_HOME; este doble imita
# el ÚNICO evento que el método lee de él.
home = os.environ.get('CODEX_HOME')
if home and %s:
    modelo = argv[argv.index('-m') + 1] if '-m' in argv else None
    esfuerzo = None
    for pieza in argv:
        if pieza.startswith('model_reasoning_effort='):
            esfuerzo = pieza.split('=', 1)[1]
    carpeta = pathlib.Path(home) / 'sessions/2026/08/27'
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / 'rollout-prueba.jsonl').write_text(
        json.dumps({'type': 'session_meta', 'payload': {'cli_version': '0.149.0'}}) + chr(10)
        + json.dumps({'type': 'turn_context',
                      'payload': {'model': modelo, 'effort': esfuerzo,
                                  'approval_policy': 'never'}}) + chr(10),
        encoding='utf-8')
encontrado = None
for pieza in argv:
    candidato = re.search(r'CONTRATO: (.+)', pieza)
    if candidato:
        encontrado = candidato
        break
if encontrado:
    hallazgos = pathlib.Path(encontrado.group(1).strip()).parent / 'hallazgos.md'
    with open(hallazgos, 'a', encoding='utf-8') as fh:
        fh.write('\\n- [x] trabajo marcado por el doble de prueba\\n')
"""


class BaseLanzadorCodex(unittest.TestCase):
    """Workspace mínimo con el launcher real y dobles de `codex` (catálogo + exec)."""

    carril = "normal"
    escribe_rollout = True

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="paridad-codex-e2e-")
        self.addCleanup(self.temporal.cleanup)
        self.base = Path(self.temporal.name)
        self.ws = self.base / "demo-agents"
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in ("ejecucion.py", "control_plane.py", "entrega.py", "lease.py",
                       "workspace_paths.py", "repo_config.py"):
            (scripts / nombre).write_bytes((SCRIPTS / nombre).read_bytes())
        self.launcher = scripts / "ejecucion.py"

        self.unidad = "001-demo"
        self.ficha = self.ws / "docs/05-trabajo" / self.unidad / "especificacion.md"
        self.ficha.parent.mkdir(parents=True)
        self.ficha.write_text(
            "---\nnumero: 001\ntipo: feature\nestado: en_obra\n"
            f"carril: {self.carril}\nficheros: [app/demo.py]\n---\n# Demo\n",
            encoding="utf-8")
        (self.ficha.parent / "hallazgos.md").write_text("# Hallazgos\n", encoding="utf-8")
        (self.ws / ".runtime").mkdir()

        self.main = self.ws / "main"
        self.main.mkdir()
        self.git("init", "-b", "main", cwd=self.main)
        self.git("config", "user.name", "Test", cwd=self.main)
        self.git("config", "user.email", "test@example.com", cwd=self.main)
        (self.main / "README.md").write_text("# demo\n", encoding="utf-8")
        self.git("add", "README.md", cwd=self.main)
        self.git("commit", "-m", "base", cwd=self.main)
        (self.main / "BASELINE.md").write_text("base de entrega\n", encoding="utf-8")
        self.git("add", "BASELINE.md", cwd=self.main)
        self.git("commit", "-m", "segunda base para entregas de fixture", cwd=self.main)
        (self.ws / "worktrees").mkdir()
        self.worktree = self.ws / "worktrees" / self.unidad
        self.git("worktree", "add", str(self.worktree), "-b", self.unidad, "main",
                 cwd=self.main)

        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.registro = self.base / "exec-record.json"
        self.contador = self.base / "consultas.txt"
        self.instalar_codex()

        self.home = self.base / "home-real"
        self.home.mkdir()
        (self.home / ".gitconfig").write_text(
            "[user]\n\tname = Tester\n\temail = t@example.com\n", encoding="utf-8")
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep
                        + os.environ.get("PATH", ""), HOME=str(self.home))

    def instalar_codex(self):
        """Un solo `codex` que atiende `debug models` y `exec`, como el real."""
        catalogo = CUERPO_CATALOGO % (json.dumps(CATALOGO), repr(str(self.contador)))
        ejecutor = CUERPO_EXEC % (repr(str(self.registro)),
                                  "True" if self.escribe_rollout else "False")
        instalar_ejecutable(
            self.bin, "codex",
            "import sys\n"
            "if sys.argv[1:3] == ['debug', 'models']:\n"
            + "".join(f"    {l}\n" for l in catalogo.splitlines())
            + "\n" + ejecutor)

    def git(self, *args, cwd):
        r = subprocess.run(["git", *args], cwd=str(cwd), text=True, encoding="utf-8",
                           errors="replace", capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def sembrar_entrega_constructor(self):
        carpeta = self.ws / ".runtime/ejecuciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        for ruta in carpeta.glob(f"{self.unidad}-*.json"):
            with contextlib.suppress(OSError, ValueError):
                if json.loads(ruta.read_text(encoding="utf-8")).get("rol") == "constructor":
                    return
        final = self.git("rev-parse", "HEAD", cwd=self.worktree).stdout.strip()
        principal = self.git("rev-parse", "main", cwd=self.main).stdout.strip()
        inicial = principal if final != principal else self.git(
            "rev-parse", f"{final}^", cwd=self.main).stdout.strip()
        arbol_inicial = self.git(
            "rev-parse", f"{inicial}^{{tree}}", cwd=self.main).stdout.strip()
        arbol_final = self.git(
            "rev-parse", f"{final}^{{tree}}", cwd=self.main).stdout.strip()
        plan = self.ficha.parent / "hallazgos.md"
        previas = len(re.findall(r"(?m)^\s*-\s*\[[xX]\]", plan.read_text(encoding="utf-8")))
        with open(plan, "a", encoding="utf-8") as salida:
            salida.write("\n- [x] entrega de fixture lista para revisión\n")
        recibo = {
            "schema": "ejecucion/v1", "id": "entrega-fixture", "unidad": self.unidad,
            "harness": "subagente-del-padre", "rol": "constructor", "resultado": "ok",
            "git": {
                "inicial": {"head": inicial, "tree": arbol_inicial,
                            "plan": {"marcadas": previas, "totales": previas + 1}},
                "final": {"head": final, "tree": arbol_final,
                          "status_porcelain": [], "materializada": False},
            },
            "trabajo": {"acreditado": True,
                        "plan": {"marcadas": previas + 1, "totales": previas + 1}},
            "exit_code": 0,
        }
        (carpeta / f"{self.unidad}-entrega-fixture.json").write_text(
            json.dumps(recibo), encoding="utf-8")

    def ejecutar(self, *extra, rol="constructor"):
        if rol == "revisor":
            self.sembrar_entrega_constructor()
        return subprocess.run(
            [sys.executable, str(self.launcher), "lanzar", self.unidad,
             "--harness", "codex", "--rol", rol, *extra, "--prompt", "Haz la tarea"],
            cwd=str(self.main), env=self.env, text=True, encoding="utf-8",
            errors="replace", capture_output=True)

    def argv(self):
        return json.loads(self.registro.read_text(encoding="utf-8"))["argv"]

    def recibo(self):
        recibos = sorted((self.ws / ".runtime/ejecuciones").glob(f"{self.unidad}-*.json"))
        self.assertEqual(len(recibos), 1, f"se esperaba un único recibo: {recibos}")
        return json.loads(recibos[0].read_text(encoding="utf-8"))


class ArgvDeCodexTest(BaseLanzadorCodex):

    def test_codex_recibe_el_modelo_y_el_esfuerzo_de_la_tabla(self):
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "modelo-punta")
        self.assertIn("model_reasoning_effort=medium", argv)
        self.assertEqual(argv[argv.index("model_reasoning_effort=medium") - 1], "-c")

    def test_el_revisor_codex_sale_en_un_modelo_distinto(self):
        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        self.assertEqual(argv[argv.index("-m") + 1], "modelo-segundo")

    def test_el_revisor_codex_no_usa_el_sandbox_read_only(self):
        # Sigue siendo cierto lo que probó la 100: `-s read-only` es absoluto (ignora
        # `--add-dir` y `writable_roots`) y dejaría al revisor sin poder firmar. Lo que
        # cambia en la 108 es la SALIDA: ya no se cae a `workspace-write`, sino a un perfil
        # de permisos que extiende `:read-only` y abre solo lo imprescindible. La exigencia
        # se endurece, no se relaja — lo comprueba `PerfilDelRevisorCodexTest`.
        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        self.assertNotIn("-s", argv)
        self.assertNotIn("workspace-write", argv)

    def test_codex_corre_con_json_y_sin_ephemeral_para_poder_acreditar(self):
        # `--ephemeral` es justo lo que impide que se escriba el rollout de la sesión,
        # que es de donde sale la acreditación de R2.
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        self.assertIn("--json", argv)
        self.assertNotIn("--ephemeral", argv)

    def test_codex_abre_las_dos_puertas_de_los_hooks(self):
        # R3, probado contra el binario real: `--ignore-user-config` apaga también el
        # `.codex/` DEL REPO, y sin `--dangerously-bypass-hook-trust` el hook no corre y
        # no se dice nada. Las dos fallan calladas, así que las fija el lanzador.
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        self.assertNotIn("--ignore-user-config", argv)
        self.assertIn("--dangerously-bypass-hook-trust", argv)

    def test_el_aislamiento_sigue_siendo_el_home_efimero(self):
        # Quitar `--ignore-user-config` no reabre la configuración del usuario: el
        # aislamiento lo da `CODEX_HOME`, que apunta a un temporal con solo `auth.json`.
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        registro = json.loads(self.registro.read_text(encoding="utf-8"))
        self.assertIsNotNone(registro["codex_home"])
        self.assertNotEqual(registro["codex_home"], str(self.home / ".codex"))


class ReciboAcreditadoTest(BaseLanzadorCodex):
    carril = "completo"

    def test_el_recibo_acredita_el_modelo_que_de_verdad_corrio(self):
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertEqual(recibo["model_slug"], "modelo-punta")
        self.assertEqual(recibo["requested_model"], "modelo-punta")
        self.assertEqual(recibo["requested_reasoning_effort"], "high")
        self.assertEqual(recibo["modelo_origen"], "harness-acreditado")
        self.assertEqual(recibo["modelo"], "modelo-punta")
        self.assertEqual(recibo["esfuerzo"], "high")


class ReciboSinRolloutTest(BaseLanzadorCodex):
    """Si el rollout no aparece, el recibo NO miente: declara, no acredita."""
    escribe_rollout = False

    def test_sin_rollout_el_recibo_no_se_declara_acreditado(self):
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertIsNone(recibo["model_slug"])
        self.assertEqual(recibo["modelo_origen"], "tabla")
        self.assertEqual(recibo["requested_model"], "modelo-punta")


# ================================================================ R3 · hooks para Codex
HOOKS_PLANTILLA = RAIZ / "plantilla/.codex/hooks.json"


class HooksCodexPlantillaTest(unittest.TestCase):

    def setUp(self):
        self.assertTrue(HOOKS_PLANTILLA.is_file(),
                        f"falta el fichero de hooks de codex: {HOOKS_PLANTILLA}")
        self.datos = json.loads(HOOKS_PLANTILLA.read_text(encoding="utf-8"))

    def ordenes(self):
        return [orden.get("command", "")
                for entradas in self.datos["hooks"].values()
                for entrada in entradas
                for orden in entrada.get("hooks", [])]

    def test_cubre_los_mismos_momentos_que_los_hooks_de_claude(self):
        # `.claude/settings.json` del método siembra canario (PreCompact + Stop) y aviso
        # (Notification + Stop). Codex no tiene `Notification`: su evento para "el agente
        # necesita a la persona" es `PermissionRequest`.
        self.assertEqual(set(self.datos["hooks"]),
                         {"PreCompact", "Stop", "PermissionRequest"})

    def test_llama_a_los_mismos_scripts_del_metodo(self):
        ordenes = " ".join(self.ordenes())
        for script in ("canario.py hook", "canario.py hook-stop",
                       "aviso.py notificacion", "aviso.py fin-de-turno"):
            with self.subTest(script=script):
                self.assertIn(script, ordenes)

    def test_resuelve_la_raiz_sin_la_variable_de_claude(self):
        # Codex no tiene equivalente a `$CLAUDE_PROJECT_DIR` (investigación P2): cada
        # hook resuelve su raíz con git.
        for orden in self.ordenes():
            with self.subTest(orden=orden):
                self.assertNotIn("CLAUDE_PROJECT_DIR", orden)
                self.assertIn("git rev-parse --show-toplevel", orden)


@unittest.skipIf(os.name == "nt", "el comando del hook es sh; en Windows va a su matriz")
class HooksCodexSeEjecutanTest(unittest.TestCase):
    """R3 · integración: la orden del hook, tal cual, con el CODEX_HOME efímero real."""

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="hooks-codex-")
        self.addCleanup(self.temporal.cleanup)
        self.base = Path(self.temporal.name)
        self.repo = self.base / "repo"
        (self.repo / "docs/00-metodo/scripts").mkdir(parents=True)
        for orden in (("git", "init", "-b", "main", "."),
                      ("git", "config", "user.name", "T"),
                      ("git", "config", "user.email", "t@t")):
            subprocess.run(orden, cwd=str(self.repo), check=True, capture_output=True)
        # Un `canario.py` de mentira que deja constancia de con qué raíz lo llamaron.
        (self.repo / "docs/00-metodo/scripts/canario.py").write_text(
            "import os, pathlib, sys\n"
            "pathlib.Path('marcador.txt').write_text(os.getcwd() + ' ' + sys.argv[1])\n",
            encoding="utf-8")

    def test_la_orden_del_hook_encuentra_la_raiz_con_git_y_el_home_efimero(self):
        datos = json.loads(HOOKS_PLANTILLA.read_text(encoding="utf-8"))
        orden = next(o["command"] for o in datos["hooks"]["PreCompact"][0]["hooks"])

        env = {"PATH": os.environ.get("PATH", "")}
        tmp = self.base / "tmp"
        tmp.mkdir()
        home = self.base / "home"
        home.mkdir()
        ejecucion.preparar_codex_home(env, tmp, home)
        self.assertTrue(Path(env["CODEX_HOME"]).is_dir())
        self.assertEqual(env["CODEX_HOME"], env["HOME"])

        # Desde un subdirectorio: si el hook dependiera del cwd, aquí se rompería.
        hondo = self.repo / "docs/00-metodo"
        resultado = subprocess.run(["/bin/sh", "-c", orden], cwd=str(hondo), env=env,
                                   capture_output=True, text=True)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        marcador = (self.repo / "marcador.txt").read_text(encoding="utf-8")
        self.assertEqual(marcador.split()[0], os.path.realpath(str(self.repo)))
        self.assertIn("hook", marcador)


class BootstrapRepartelosHooksCodexTest(unittest.TestCase):
    """R3 · el workspace nuevo nace con los hooks de los DOS harness."""

    def test_el_bootstrap_siembra_hooks_codex_y_es_idempotente(self):
        with tempfile.TemporaryDirectory(prefix="bootstrap-codex-") as tmp:
            destino = Path(tmp)
            self.assertTrue(bootstrap.sembrar_hooks_codex(destino))
            fichero = destino / ".codex/hooks.json"
            self.assertTrue(fichero.is_file())
            datos = json.loads(fichero.read_text(encoding="utf-8"))
            self.assertEqual(set(datos["hooks"]),
                             {"PreCompact", "Stop", "PermissionRequest"})
            self.assertFalse(bootstrap.sembrar_hooks_codex(destino),
                             "sembrar dos veces no debe duplicar nada")

    def test_no_pisa_los_hooks_propios_del_dueno(self):
        with tempfile.TemporaryDirectory(prefix="bootstrap-codex-") as tmp:
            destino = Path(tmp)
            (destino / ".codex").mkdir()
            (destino / ".codex/hooks.json").write_text(json.dumps(
                {"hooks": {"SessionStart": [{"hooks": [
                    {"type": "command", "command": "echo mio"}]}]}}), encoding="utf-8")

            bootstrap.sembrar_hooks_codex(destino)

            datos = json.loads((destino / ".codex/hooks.json").read_text(encoding="utf-8"))
            self.assertIn("SessionStart", datos["hooks"])
            self.assertIn("PreCompact", datos["hooks"])


# ====================================================== R5 · ADR-037 y roles.md al día
ADR = RAIZ / "plantilla/docs/00-metodo/decisiones/037-paridad-codex-claude.md"
ROLES = RAIZ / "plantilla/docs/00-metodo/roles.md"


class DoctrinaAlDiaTest(unittest.TestCase):

    def test_el_adr_037_existe_y_enmienda_al_033(self):
        self.assertTrue(ADR.is_file(), f"falta {ADR}")
        texto = ADR.read_text(encoding="utf-8")
        self.assertIn("ADR-033", texto)
        self.assertIn("spawn_agent", texto)

    def test_el_adr_viaja_a_los_workspaces(self):
        # Un ADR que no está en el manifiesto del bootstrap no llega a ningún proyecto.
        self.assertIn("037-paridad-codex-claude.md", bootstrap.DECISIONES)

    def test_roles_retira_que_codex_sea_inejecutable(self):
        texto = ROLES.read_text(encoding="utf-8")
        self.assertNotIn("INEJECUTABLE", texto)

    def test_roles_describe_la_tabla_por_harness(self):
        texto = ROLES.read_text(encoding="utf-8")
        self.assertIn("codex debug models", texto)
        self.assertIn("harness", texto.lower())


# ============================== Unidad 108 · R3 · el revisor Codex es solo-lectura de verdad
#
# La 100 probó que `-s read-only` es ABSOLUTO (ignora `--add-dir` y `writable_roots`: no
# queda ninguna ruta escribible y el revisor no podría firmar su veredicto) y dejó abierta
# la vía de los perfiles de permisos. El spike del paso 0 de esta unidad la abrió contra el
# binario real: un perfil `[permissions.<nombre>]` que EXTIENDE `:read-only` y añade rutas
# escribibles por su mapa `filesystem` sí da las dos mitades a la vez — worktree en solo
# lectura y carpeta de la unidad escribible. La evidencia cruda está en `hallazgos.md`.
PERFIL = "revisor-solo-lectura"


class PerfilDelRevisorCodexTest(BaseLanzadorCodex):
    """Sobre el argv que construye el lanzador, con el doble de `codex`."""

    def config(self, argv):
        return [argv[i + 1] for i, pieza in enumerate(argv[:-1]) if pieza == "-c"]

    def test_el_revisor_corre_bajo_un_perfil_que_extiende_solo_lectura(self):
        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        config = self.config(argv)
        self.assertIn(f'default_permissions="{PERFIL}"', config)
        self.assertIn(f'permissions.{PERFIL}.extends=":read-only"', config)
        # `sandbox_mode` y `permission_profile` no pueden convivir: el binario lo rechaza.
        self.assertNotIn("-s", argv)
        self.assertNotIn("workspace-write", argv)

    def test_el_perfil_deja_escribible_la_carpeta_de_la_unidad_y_el_temporal(self):
        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        filesystem = [c for c in self.config(self.argv())
                      if c.startswith(f"permissions.{PERFIL}.filesystem=")]
        self.assertEqual(len(filesystem), 1, self.argv())
        mapa = filesystem[0]
        # La única escritura obligatoria del revisor: su veredicto y su firma.
        self.assertIn(str(self.ficha.parent), mapa)
        # Y el temporal del lanzador (TMPDIR/CODEX_HOME): sin él, ni la sesión ni las
        # herramientas del agente pueden escribir nada y el revisor se queda mudo.
        registro = json.loads(self.registro.read_text(encoding="utf-8"))
        self.assertIn(str(Path(registro["codex_home"]).parent), mapa)
        self.assertIn('="write"', mapa.replace(" ", ""))

    def test_el_worktree_no_viaja_como_escribible(self):
        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        # `--add-dir` en codex significa "directorio escribible adicional": bajo el perfil
        # las rutas escribibles las declara el propio perfil, no esta bandera.
        self.assertNotIn("--add-dir", argv)
        filesystem = next(c for c in self.config(argv)
                          if c.startswith(f"permissions.{PERFIL}.filesystem="))
        self.assertNotIn(str(self.worktree.resolve()), filesystem)
        # El cwd sigue siendo el worktree (ADR-022): lo que cambia es qué puede escribir.
        self.assertEqual(Path(argv[argv.index("-C") + 1]).resolve(),
                         self.worktree.resolve())

    def test_el_constructor_codex_no_cambia(self):
        # Límite: el perfil es SOLO del revisor. El constructor escribe en su worktree.
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.argv()
        self.assertIn("workspace-write", argv)
        self.assertNotIn(f'default_permissions="{PERFIL}"', self.config(argv))


@unittest.skipUnless(shutil.which("codex"), "sin binario `codex` en esta máquina")
class PerfilDelRevisorContraElBinarioTest(unittest.TestCase):
    """La frontera se DEMUESTRA con el `codex` real: `codex sandbox -P <perfil>` corre un
    comando bajo exactamente el mismo perfil que recibirá `codex exec`."""

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="perfil-revisor-")
        self.addCleanup(self.temporal.cleanup)
        self.base = Path(self.temporal.name).resolve()
        self.repo = self.base / "repo"
        self.docs = self.base / "docs"
        self.repo.mkdir()
        self.docs.mkdir()
        (self.repo / "codigo.txt").write_text("hola\n", encoding="utf-8")
        (self.docs / "hallazgos.md").write_text("# Hallazgos\n", encoding="utf-8")
        (self.base / "codex-home").mkdir()
        for args in (("init", "-b", "main"), ("add", "codigo.txt"),
                     ("-c", "user.name=T", "-c", "user.email=t@e.x", "commit", "-m", "base")):
            subprocess.run(["git", *args], cwd=str(self.repo), check=True,
                           capture_output=True)

    def test_bajo_el_perfil_el_worktree_no_se_puede_escribir_y_la_unidad_si(self):
        argv = ejecucion.opciones_de_perfil_revisor_codex(PERFIL, [self.docs])
        orden = (
            f"(echo x >> '{self.docs}/hallazgos.md' && echo DOC=escribible || echo DOC=fallo);"
            f"(echo y >> '{self.repo}/codigo.txt' && echo REPO=escribible "
            f"|| echo REPO=solo-lectura);"
            f"(cat '{self.repo}/codigo.txt' > /dev/null && echo LECTURA=ok || echo LECTURA=fallo)"
        )
        # `codex sandbox` selecciona el perfil con `-P` (lo exige); `codex exec` lo hace con
        # el último `-c` (`default_permissions=…`), que es el que se descarta aquí. El perfil
        # que se monta es el MISMO: los dos primeros `-c` son literalmente los del lanzador.
        resultado = subprocess.run(
            [shutil.which("codex"), "sandbox", *argv[:-2], "-P", PERFIL,
             "-C", str(self.repo), "--", "/bin/sh", "-c", orden],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, CODEX_HOME=str(self.base / "codex-home")),
        )

        traza = resultado.stdout + resultado.stderr
        self.assertIn("DOC=escribible", traza, traza)
        self.assertIn("REPO=solo-lectura", traza, traza)
        self.assertIn("LECTURA=ok", traza, traza)


# ========================= Unidad 108 · R4 · confiar los hooks de Codex, escrito una vez
AGENTS_PLANTILLA = RAIZ / "plantilla/AGENTS.md"


class ConfiarLosHooksEstaEscritoTest(unittest.TestCase):
    """Las dos puertas mudas de la 100 sirven de poco si el arranque no las nombra."""

    def papeles(self):
        return {AGENTS_PLANTILLA: AGENTS_PLANTILLA.read_text(encoding="utf-8"),
                ROLES: ROLES.read_text(encoding="utf-8")}

    def test_los_dos_papeles_dicen_como_confiar_los_hooks(self):
        for ruta, texto in self.papeles().items():
            with self.subTest(papel=ruta.name):
                self.assertIn("/hooks", texto)

    def test_dicen_que_sin_confiarlos_no_corren_ni_avisan(self):
        for ruta, texto in self.papeles().items():
            with self.subTest(papel=ruta.name):
                bajo = texto.lower()
                self.assertIn("no los ejecuta", bajo)
                self.assertIn("no te avisa", bajo)

    def test_dicen_que_ejecucion_py_no_necesita_ese_paso(self):
        for ruta, texto in self.papeles().items():
            with self.subTest(papel=ruta.name):
                self.assertIn("--dangerously-bypass-hook-trust", texto)


if __name__ == "__main__":
    unittest.main()
