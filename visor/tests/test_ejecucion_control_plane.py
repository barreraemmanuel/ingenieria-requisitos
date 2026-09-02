import contextlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

import ayuda_windows  # noqa: E402 - módulo hermano de la suite


RAIZ = Path(__file__).resolve().parents[2]
LAUNCHER = RAIZ / "plantilla/docs/00-metodo/scripts/ejecucion.py"
WORKSPACE_PATHS = RAIZ / "plantilla/docs/00-metodo/scripts/workspace_paths.py"
SCRIPTS = LAUNCHER.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import ejecucion  # noqa: E402  (el REAL, sin mutar)


class ControlPlaneE2ETest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="control-plane-")
        self.addCleanup(self.temporal.cleanup)
        self.base = Path(self.temporal.name)
        self.ws = self.base / "demo-agents"
        self.ws.mkdir()
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        self.assertTrue(LAUNCHER.is_file(), "falta el launcher canónico ejecucion.py")
        shutil.copy2(LAUNCHER, scripts / "ejecucion.py")
        shutil.copy2(LAUNCHER.with_name("control_plane.py"), scripts / "control_plane.py")
        shutil.copy2(LAUNCHER.with_name("entrega.py"), scripts / "entrega.py")
        shutil.copy2(LAUNCHER.with_name("lease.py"), scripts / "lease.py")
        # Bug 065: el launcher deriva el modelo de la tabla de la regla 10, que vive en
        # repo_config; sin él a su lado, ejecucion.py no importa.
        shutil.copy2(LAUNCHER.with_name("repo_config.py"), scripts / "repo_config.py")
        shutil.copy2(WORKSPACE_PATHS, scripts / "workspace_paths.py")
        self.launcher = scripts / "ejecucion.py"

        self.unidad = "001-demo"
        ficha = self.ws / "docs/05-trabajo" / self.unidad / "especificacion.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nnumero: 001\ntipo: feature\nestado: en_obra\ncarril: normal\n"
            "ficheros: [app/demo.py]\n---\n"
            "# Demo\n",
            encoding="utf-8",
        )
        (ficha.parent / "hallazgos.md").write_text("# Hallazgos\n", encoding="utf-8")
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
        self.git(
            "worktree", "add", str(self.worktree), "-b", self.unidad, "main",
            cwd=self.main,
        )

        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.crear_doble_harness("claude")
        self.crear_doble_harness("codex")

        self.home = self.base / "home-real"
        tecnica = self.home / ".agents/skills/vue-best-practices"
        proceso = self.home / ".agents/skills/using-superpowers"
        plugin = self.home / ".codex/plugins/cache/plugin-de-proceso"
        for ruta in (tecnica, proceso, plugin):
            ruta.mkdir(parents=True)
        (tecnica / "SKILL.md").write_text(
            "---\nname: vue-best-practices\n---\nCONTENIDO_TECNICO_PERMITIDO\n",
            encoding="utf-8",
        )
        (proceso / "SKILL.md").write_text(
            "---\nname: using-superpowers\n---\nCONTENIDO_PROCESO_PROHIBIDO\n",
            encoding="utf-8",
        )
        (plugin / "plugin.json").write_text('{"name":"proceso"}\n', encoding="utf-8")
        # HOME "real" de fixture con identidad de git configurada: unidad 012, Claude
        # hereda este HOME tal cual (ya no lo aísla), así que necesita lo que un HOME
        # real ya tendría.
        (self.home / ".gitconfig").write_text(
            "[user]\n\tname = Tester De Campo\n\temail = tester@example.com\n",
            encoding="utf-8",
        )

        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": str(self.bin) + os.pathsep + self.env.get("PATH", ""),
                "HOME": str(self.home),
                "SHELL": "/bin/fish",
                "SCRATCH": "",
                "BASH_ENV": str(self.base / "bash-env-peligroso"),
                "ENV": str(self.base / "sh-env-peligroso"),
                "ZDOTDIR": str(self.base / "zsh-peligroso"),
                "CDPATH": str(self.main),
                "PYTHONPATH": str(self.base / "python-peligroso"),
                "NODE_OPTIONS": "--require=/tmp/plugin-peligroso.js",
            }
        )

    def git(self, *args, cwd):
        resultado = subprocess.run(
            ["git", *args], cwd=cwd, text=True,
            encoding="utf-8", errors="replace", capture_output=True
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return resultado

    def hacer_ejecutable(self, ruta, texto):
        ruta.write_text(texto, encoding="utf-8")
        ruta.chmod(ruta.stat().st_mode | stat.S_IXUSR)

    # Preámbulo que recibe TODO doble. Define `argv` (ya resuelto) y `prompt`.
    #
    # Ronda 4 del bug 017: en Windows el argumento problemático no cruza cmd.exe tal
    # cual — solo su REFERENCIA literal (##IR_CMDARG_N##, sin ningún '%' que cmd.exe
    # pueda expandir) llega como argv. Quien recibe ese token debe resolverlo leyendo
    # su propio entorno heredado (que sí viaja intacto, ajeno al parser de cmd.exe)
    # para reconstruir el argumento EFECTIVO — eso es lo que un harness real, al ver
    # ese literal, tendría que hacer para no perder el prompt multilínea.
    #
    # Vive aquí y no dentro de un doble concreto porque los dobles de la unidad 028
    # leen el prompt igual que el primero: cuando esto era privado de uno solo, los
    # otros recibían el literal `##IR_CMDARG_1##` y no encontraban su "CONTRATO:".
    PREAMBULO_DOBLE = """import os, re, sys

def resolver(valor):
    coincide = re.fullmatch(r'##(IR_CMDARG_\\d+)##', valor) if isinstance(valor, str) else None
    return os.environ.get(coincide.group(1), valor) if coincide else valor

argv = [resolver(v) for v in sys.argv[1:]]
prompt = argv[-1] if argv else ''
"""

    def crear_doble_harness(self, nombre, marca_trabajo=True):
        cuerpo = """import json, pathlib, stat, subprocess
tmp = pathlib.Path(os.environ['TMPDIR'])

record = {
    'argv': argv,
    # Instrumentación de la ronda 4 del bug 017: qué llegó ANTES de resolver y
    # qué referencias había realmente en el entorno. Sin esto, un fallo en el
    # job de Windows solo dice «el prompt no es el prompt» y no distingue
    # «la línea de comando se truncó» de «el doble no reconstruyó».
    'argv_crudo': list(sys.argv[1:]),
    'cmdarg_env': {k: v for k, v in os.environ.items() if k.startswith('IR_CMDARG_')},
    'lanzado_por': {'ejecutable': sys.executable, 'script': __file__,
                    'comspec': os.environ.get('ComSpec'), 'os_name': os.name},
    'cwd': os.getcwd(),
    'pwd': os.environ.get('PWD'),
    'branch': subprocess.run(['git', 'branch', '--show-current'], text=True,
                             encoding="utf-8", errors="replace",
                             capture_output=True).stdout.strip(),
    'tmp': str(tmp),
    'tmp_mode': stat.S_IMODE(tmp.stat().st_mode),
    # Se comprueba AQUÍ, mientras tmp todavía existe: el launcher lo borra en
    # su propio `finally` antes de devolver el control al test (bug 017
    # ronda 3), así que comprobarlo desde fuera después siempre da falso.
    'tmp_accesible': os.access(tmp, os.R_OK | os.W_OK),
    'home': os.environ.get('HOME'),
    'codex_home': os.environ.get('CODEX_HOME'),
    # Bug 037: las cinco variables que Windows necesita para resolver nombres y
    # cargar sus propias DLL. En Windows `os.environ` normaliza las claves a
    # MAYÚSCULAS (os.py, encodekey=str.upper), así que este mismo literal vale
    # en la máquina real y en la simulación de este taller (macOS).
    'windows': {k: os.environ.get(k) for k in
                ('SYSTEMROOT', 'WINDIR', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')},
    'poison': {k: os.environ.get(k) for k in
               ('SCRATCH','BASH_ENV','ENV','ZDOTDIR','CDPATH','PYTHONPATH','NODE_OPTIONS')},
}
pathlib.Path('.harness-record.json').write_text(json.dumps(record), encoding="utf-8")
"""
        if marca_trabajo:
            cuerpo += """
encontrado = re.search(r'CONTRATO: (.+)', prompt)
if encontrado:
    ficha = pathlib.Path(encontrado.group(1).strip())
    hallazgos = ficha if ficha.parent.name == 'bugs' else ficha.parent / 'hallazgos.md'
    with open(hallazgos, 'a', encoding='utf-8') as fh:
        fh.write('\\n- [x] trabajo marcado por el doble de prueba\\n')
"""
        self.instalar_doble(nombre, cuerpo)

    CATALOGO_CODEX = """import json as _json, sys as _sys
if _sys.argv[1:3] == ['debug', 'models']:
    print(_json.dumps({'models': [
        {'slug': 'oai-punta', 'visibility': 'list', 'priority': 1,
         'default_reasoning_level': 'low',
         'supported_reasoning_levels': [{'effort': e} for e in ('low', 'medium', 'high')]},
        {'slug': 'oai-segundo', 'visibility': 'list', 'priority': 2,
         'default_reasoning_level': 'medium',
         'supported_reasoning_levels': [{'effort': e} for e in ('low', 'medium', 'high')]},
    ]}))
    raise SystemExit(0)
"""

    def instalar_doble(self, nombre, cuerpo):
        """Deja `cuerpo` (Python) invocable como el ejecutable `nombre` del PATH.

        En Windows no hay shebang y `shutil.which()` solo encuentra ejecutables con una
        extensión de PATHEXT (.bat/.cmd/.exe…): un fichero sin extensión, aunque lleve
        el bit +x, no cuenta ahí (bug 017 familia 2). El .bat delega en el .py real.

        TODO doble pasa por aquí. Cuando esta lógica vivía dentro de un solo creador,
        los dobles que llegaron después (unidad 028) se quedaron con el shebang y en
        Windows no arrancaban nunca: el test no fallaba por lo que vigila, fallaba por
        no haberse ejecutado.
        """
        cuerpo = self.PREAMBULO_DOBLE + cuerpo
        if nombre == "codex":
            # Unidad 100: la tabla de la regla 10 para codex se DERIVA de su catálogo, así
            # que el lanzador ejecuta `codex debug models` antes de lanzar. Un doble que no
            # sepa responder eso no llega ni a registrar su argv.
            cuerpo = self.CATALOGO_CODEX + cuerpo
        if os.name == "nt":
            script = self.bin / f"{nombre}.py"
            script.write_text(cuerpo, encoding="utf-8")
            (self.bin / f"{nombre}.bat").write_text(
                f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
            )
        else:
            self.hacer_ejecutable(self.bin / nombre, "#!/usr/bin/env python3\n" + cuerpo)

    def crear_doble_harness_que_intenta_escribir_ficha(self, nombre):
        # Unidad 028, R3: el doble intenta escribir la ficha canónica que lee de su propio
        # prompt ("CONTRATO: <ruta>") y deja constancia de si lo consiguió o de la
        # denegación real que recibió — sin esto no hay forma de comprobar la frontera
        # desde fuera del proceso del harness.
        cuerpo = """import json, pathlib
encontrado = re.search(r'CONTRATO: (.+)', prompt)
ficha = encontrado.group(1).strip() if encontrado else None
registro = {'ficha': ficha, 'escribio': False, 'error': None}
try:
    with open(ficha, 'a', encoding='utf-8') as fh:
        fh.write('\\nINTENTO_DE_ESCRITURA_DEL_CONSTRUCTOR\\n')
    registro['escribio'] = True
except OSError as exc:
    registro['error'] = str(exc)
pathlib.Path('.intento-escritura-ficha.json').write_text(json.dumps(registro), encoding="utf-8")
hallazgos = pathlib.Path(ficha).parent / 'hallazgos.md'
with open(hallazgos, 'a', encoding='utf-8') as fh:
    fh.write('\\n- [x] trabajo marcado por el doble de prueba\\n')
"""
        self.instalar_doble(nombre, cuerpo)

    def crear_doble_harness_que_marca_trabajo(self, nombre):
        # Unidad 028, R6: el doble SÍ trabaja de verdad — escribe en hallazgos.md, que es
        # justo lo que el recibo debe acreditar como trabajo real.
        cuerpo = """import json, pathlib
encontrado = re.search(r'CONTRATO: (.+)', prompt)
ficha = pathlib.Path(encontrado.group(1).strip())
hallazgos = ficha.parent / 'hallazgos.md'
with open(hallazgos, 'a', encoding='utf-8') as fh:
    fh.write('\\n- [x] trabajo marcado por el doble de prueba\\n')
pathlib.Path('.harness-record.json').write_text(
    json.dumps({'trabajo_marcado': True}), encoding='utf-8')
"""
        self.instalar_doble(nombre, cuerpo)

    def argumentos(self, harness="claude", rol="constructor", skills=(),
                   prompt="Haz la tarea", unidad=None):
        args = [
            sys.executable,
            str(self.launcher),
            "lanzar",
            unidad or self.unidad,
            "--harness",
            harness,
            "--rol",
            rol,
        ]
        for skill in skills:
            args.extend(("--skill-tecnica", skill))
        args.extend(("--prompt", prompt))
        return args

    def sembrar_entrega_constructor(self, unidad):
        """Precondición realista de los tests históricos que ejercitan al revisor."""
        ficha = self.ws / "docs/05-trabajo" / unidad / "especificacion.md"
        if not ficha.is_file():
            ficha = self.ws / "docs/bugs" / f"{unidad}.md"
        if not ficha.is_file():
            return
        texto = ficha.read_text(encoding="utf-8")
        if re.search(r"(?m)^ejecucion:\s*documental\b", texto):
            return
        carril = re.search(r"(?m)^carril:\s*([^\s#]+)", texto)
        if carril and carril.group(1).lower() in {"directo", "expres", "exprés"}:
            return
        carpeta = self.ws / ".runtime/ejecuciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        for ruta in carpeta.glob(f"{unidad}-*.json"):
            with contextlib.suppress(OSError, ValueError):
                if json.loads(ruta.read_text(encoding="utf-8")).get("rol") == "constructor":
                    return
        worktree = self.ws / "worktrees" / unidad
        if worktree.is_dir():
            final = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
            estado = self.git("status", "--porcelain", cwd=worktree).stdout.splitlines()
        else:
            fusion = re.search(r"(?m)^fusion:\s*([^\s#]+)", texto)
            if not fusion:
                return
            final = fusion.group(1)
            estado = []
        principal = self.git("rev-parse", "main", cwd=self.main).stdout.strip()
        inicial = principal if final != principal else self.git(
            "rev-parse", f"{final}^", cwd=self.main).stdout.strip()
        arbol_inicial = self.git(
            "rev-parse", f"{inicial}^{{tree}}", cwd=self.main).stdout.strip()
        arbol_final = self.git(
            "rev-parse", f"{final}^{{tree}}", cwd=self.main).stdout.strip()
        plan = ficha if ficha.parent.name == "bugs" else ficha.parent / "hallazgos.md"
        previas = len(re.findall(r"(?m)^\s*-\s*\[[xX]\]", plan.read_text(encoding="utf-8")))
        with open(plan, "a", encoding="utf-8") as salida:
            salida.write("\n- [x] entrega de fixture lista para revisión\n")
        recibo = {
            "schema": "ejecucion/v1", "id": "entrega-fixture", "unidad": unidad,
            "harness": "subagente-del-padre", "rol": "constructor", "resultado": "ok",
            "git": {
                "inicial": {"head": inicial, "tree": arbol_inicial,
                            "plan": {"marcadas": previas, "totales": previas + 1}},
                "final": {"head": final, "tree": arbol_final,
                          "status_porcelain": estado, "materializada": False},
            },
            "trabajo": {"acreditado": True,
                        "plan": {"marcadas": previas + 1, "totales": previas + 1}},
            "exit_code": 0,
        }
        (carpeta / f"{unidad}-entrega-fixture.json").write_text(
            json.dumps(recibo), encoding="utf-8")

    def ejecutar(self, harness="claude", rol="constructor", skills=(), prompt="Haz la tarea",
                 unidad=None, env=None):
        if rol == "revisor":
            self.sembrar_entrega_constructor(unidad or self.unidad)
        return subprocess.run(
            self.argumentos(harness, rol, skills, prompt, unidad),
            cwd=self.main, env=env or self.env, text=True,
            encoding="utf-8", errors="replace", capture_output=True
        )

    def proceso_en_barrera(self, nombre="ejecucion_antes_harness", unidad=None):
        # Barrera por ficheros: los FDs no cruzan procesos en Windows (pass_fds
        # es POSIX). El hijo toca `ready` al llegar y espera a que exista `gate`.
        barrera = Path(tempfile.mkdtemp(prefix="barrera-"))
        self.addCleanup(shutil.rmtree, barrera, True)
        ready = barrera / "ready"
        gate = barrera / "gate"
        env = self.env.copy()
        prefijo = f"IR_FAILPOINT_{nombre.upper()}"
        env[f"{prefijo}_READY_FILE"] = str(ready)
        env[f"{prefijo}_WAIT_FILE"] = str(gate)
        env["IR_SESSION_ID"] = "ejecucion-a"
        proceso = subprocess.Popen(
            self.argumentos(unidad=unidad), cwd=self.main, env=env, text=True,
            encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: proceso.poll() is None and proceso.kill())
        limite = time.monotonic() + 5
        while not ready.exists():
            self.assertLess(
                time.monotonic(), limite, "el launcher no alcanzó la barrera"
            )
            time.sleep(0.01)
        return proceso, gate

    def crear_unidad_paralela(self, nombre, recurso):
        ficha = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nnumero: 002\ntipo: feature\nestado: en_obra\ncarril: normal\n"
            f"ficheros: [{recurso}]\n---\n# Paralela\n",
            encoding="utf-8",
        )
        (ficha.parent / "hallazgos.md").write_text("# Hallazgos\n", encoding="utf-8")
        destino = self.ws / "worktrees" / nombre
        self.git("worktree", "add", str(destino), "-b", nombre, "main", cwd=self.main)
        return destino

    def registros(self):
        return json.loads((self.worktree / ".harness-record.json").read_text(encoding="utf-8"))

    def diagnostico(self, harness):
        # Ronda 4 del bug 017: cuando estos asserts fallan en el job de Windows
        # el único dato disponible es el log del CI, así que el mensaje lleva el
        # harness-record ENTERO (argv resuelto y crudo, referencias IR_CMDARG_*
        # del entorno y cómo se lanzó el doble) más el envoltorio que ejecucion.py
        # habría construido para este ejecutable. Se conserva porque no cuesta
        # nada en verde y es lo único que hace accionable un rojo remoto.
        muestra = ejecucion.comando_subproceso(
            str(self.bin / "claude.bat"),
            [str(self.bin / "claude.bat"), "-p", "linea1\nlinea2"],
            {},
        )
        return (
            "\n--- harness-record completo (bug 017 ronda 4) ---\n"
            + json.dumps(harness, indent=2, ensure_ascii=False)
            + "\n--- envoltorio que construye comando_subproceso aquí ---\n"
            + json.dumps(muestra, ensure_ascii=False)
            + f"\n--- os.name={os.name} bin={self.bin} ---"
        )

    def test_claude_arranca_en_worktree_con_entorno_saneado_y_skill_tecnica(self):
        resultado = self.ejecutar(skills=("vue-best-practices",))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        self.assertEqual(harness["cwd"], str(self.worktree.resolve()))
        self.assertEqual(harness["pwd"], str(self.worktree.resolve()))
        self.assertEqual(harness["branch"], self.unidad)
        if os.name == "nt":
            # chmod() en Windows solo alterna el atributo de solo-lectura; no hay
            # bits de permiso POSIX que fijar 0o700 pueda hacer cumplir de verdad
            # ahí (comportamiento documentado de os.chmod en la stdlib de
            # Windows), así que el propio ejecucion.py lo llama igual (no hace
            # daño) pero el mode resultante no es una garantía comprobable en
            # esta plataforma — solo se comprueba que el tmp existió y era
            # legible/escribible por su dueño, que es lo que sí puede pedirse.
            # Se lee `tmp_accesible` (grabado por el propio doble MIENTRAS tmp
            # todavía existía) en vez de repetir os.access aquí: el launcher
            # borra tmp en su `finally` antes de devolver el control a este
            # test, así que comprobarlo ahora desde fuera siempre daría falso
            # (bug 017 ronda 3).
            self.assertTrue(harness["tmp_accesible"])
        else:
            self.assertEqual(harness["tmp_mode"], 0o700)
        self.assertTrue(all(value is None for value in harness["poison"].values()))
        self.assertIn("--safe-mode", harness["argv"])
        self.assertIn("--disable-slash-commands", harness["argv"])
        self.assertIn("--add-dir", harness["argv"])
        self.assertIn(str((self.ws / "docs/05-trabajo/001-demo").resolve()), harness["argv"])
        prompt = harness["argv"][-1]
        self.assertIn("CONTENIDO_TECNICO_PERMITIDO", prompt, self.diagnostico(harness))
        self.assertNotIn("CONTENIDO_PROCESO_PROHIBIDO", prompt, self.diagnostico(harness))

    def test_codex_no_recibe_el_flag_de_aprobacion_retirado(self):
        # Bug 025: codex-cli 0.146.0 retiró `-a` y muere con `unexpected argument`
        # antes del prompt. En modo `exec` no hay aprobaciones interactivas por
        # definición, así que el flag sobra: no debe aparecer en el argv.
        resultado = self.ejecutar(harness="codex")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        self.assertNotIn("-a", harness["argv_crudo"])
        self.assertNotIn("never", harness["argv_crudo"])
        # El sandbox del propio codex sigue declarado:
        self.assertIn("workspace-write", harness["argv"])

    def test_codex_usa_home_efimero_y_no_descubre_plugins_instalados(self):
        resultado = self.ejecutar(harness="codex")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        self.assertNotEqual(harness["home"], str(self.home))
        self.assertEqual(harness["home"], harness["codex_home"])
        self.assertTrue(harness["home"].startswith(harness["tmp"]))
        self.assertIn("--ignore-rules", harness["argv"])
        # Unidad 100 — dos banderas cambian, y las dos por algo comprobado contra el
        # binario real (codex-cli 0.149.0), no por gusto:
        #   · `--ignore-user-config` se RETIRA: no era solo «no leas el config del
        #     usuario», apagaba la capa de configuración entera, hooks del `.codex/` DEL
        #     REPO incluidos. Y no hacía falta para aislar — el aislamiento lo da el
        #     CODEX_HOME efímero, que es lo que este mismo test comprueba arriba.
        #   · `--ephemeral` se RETIRA porque es justo lo que impide escribir el rollout de
        #     la sesión, la única fuente donde Codex dice con qué modelo corrió de verdad.
        self.assertNotIn("--ignore-user-config", harness["argv"])
        self.assertNotIn("--ephemeral", harness["argv"])
        self.assertIn("--dangerously-bypass-hook-trust", harness["argv"])
        self.assertNotIn("plugin-de-proceso", " ".join(harness["argv"]))

    def test_prompt_con_flags_peligrosos_sigue_siendo_un_solo_argumento_literal(self):
        # Unidad 012: sin sandbox de SO de por medio, la garantía la da por completo
        # que ejecucion.py invoque argv como LISTA (subprocess.run, nunca shell=True):
        # esto se verifica en el argv que el propio harness recibió, no en un wrapper.
        prompt = "explica --dangerously-skip-permissions; touch /mut048"
        resultado = self.ejecutar(prompt=prompt)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        self.assertEqual(harness["argv"][-1].splitlines()[-1], prompt,
                         self.diagnostico(harness))
        self.assertNotIn("/bin/sh", harness["argv"])
        self.assertNotIn("-c", harness["argv"])
        self.assertEqual(sum(prompt in arg for arg in harness["argv"]), 1,
                         self.diagnostico(harness))

    def test_rechaza_skill_de_proceso_aunque_se_solicite(self):
        resultado = self.ejecutar(skills=("using-superpowers",))

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("skill de proceso", resultado.stderr.lower())
        self.assertFalse((self.worktree / ".harness-record.json").exists())

    def test_rechaza_alias_symlink_a_skill_de_proceso(self):
        alias = self.home / ".agents/skills/alias-tecnico"
        ayuda_windows.enlazar_o_saltar(
            self, alias, self.home / ".agents/skills/using-superpowers", directorio=True
        )

        resultado = self.ejecutar(skills=("alias-tecnico",))

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("symlink", resultado.stderr.lower())
        self.assertFalse((self.worktree / ".harness-record.json").exists())

    def test_rechaza_alias_cuyo_frontmatter_declara_skill_de_proceso(self):
        alias = self.home / ".agents/skills/alias-real"
        alias.mkdir()
        (alias / "SKILL.md").write_text(
            "---\nname: using-superpowers\n---\nCONTENIDO_PROCESO_PROHIBIDO\n",
            encoding="utf-8",
        )

        resultado = self.ejecutar(skills=("alias-real",))

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("proceso", resultado.stderr.lower())
        self.assertFalse((self.worktree / ".harness-record.json").exists())

    def test_rechaza_rama_distinta_antes_de_ejecutar_harness(self):
        self.git("checkout", "-b", "rama-intrusa", cwd=self.worktree)

        resultado = self.ejecutar()

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("rama", resultado.stderr.lower())
        self.assertFalse((self.worktree / ".harness-record.json").exists())

    def test_rechaza_carril_directo_sin_lanzar_otro_llm(self):
        ficha = self.ws / "docs/05-trabajo" / self.unidad / "especificacion.md"
        ficha.write_text(
            ficha.read_text(encoding="utf-8").replace("carril: normal", "carril: directo"),
            encoding="utf-8")

        resultado = self.ejecutar()

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("padre", resultado.stderr.lower())
        self.assertFalse((self.worktree / ".harness-record.json").exists())

    def test_rechaza_hallazgos_symlink_antes_de_lanzar_harness(self):
        hallazgos = self.ws / "docs/05-trabajo" / self.unidad / "hallazgos.md"
        exterior = self.ws / ".hallazgos-exterior.md"
        contenido = hallazgos.read_bytes()
        exterior.write_bytes(contenido)
        hallazgos.unlink()
        ayuda_windows.enlazar_o_saltar(self, hallazgos, exterior)

        resultado = self.ejecutar()

        self.assertNotEqual(resultado.returncode, 0)
        # Se comprueba lo que la guarda PROMETE —rechaza y nombra el documento—, no una
        # palabra suya: desde la 043 caza también junctions y dice "no admite enlaces".
        salida = resultado.stderr.lower()
        self.assertIn("no admite enlaces", salida)
        self.assertIn("hallazgos.md", salida)
        self.assertEqual(exterior.read_bytes(), contenido)
        self.assertFalse((self.worktree / ".harness-record.json").exists())

    def test_dos_launchers_de_la_misma_unidad_no_solapan(self):
        primero, gate = self.proceso_en_barrera()
        segundo = self.ejecutar(env={**self.env, "IR_SESSION_ID": "ejecucion-b"})

        self.assertNotEqual(segundo.returncode, 0)
        self.assertIn("ocupado", segundo.stderr.lower())
        gate.write_text("1", encoding="ascii")
        salida, error = primero.communicate(timeout=10)
        self.assertEqual(primero.returncode, 0, salida + error)
        recibos = list((self.ws / ".runtime/ejecuciones").glob("001-demo-*.json"))
        self.assertEqual(len(recibos), 1)

    def test_dos_unidades_con_el_mismo_recurso_no_solapan(self):
        segunda = "002-paralela"
        self.crear_unidad_paralela(segunda, "app/demo.py")
        primero, gate = self.proceso_en_barrera()

        resultado = self.ejecutar(
            unidad=segunda, env={**self.env, "IR_SESSION_ID": "ejecucion-b"}
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("resource:app/demo.py", resultado.stderr)
        gate.write_text("1", encoding="ascii")
        salida, error = primero.communicate(timeout=10)
        self.assertEqual(primero.returncode, 0, salida + error)
        self.assertFalse(
            (self.ws / "worktrees" / segunda / ".harness-record.json").exists()
        )

    def test_publica_resultado_con_checkpoints_verificables(self):
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibos = list((self.ws / ".runtime/ejecuciones").glob("001-demo-*.json"))
        self.assertEqual(len(recibos), 1)
        recibo = json.loads(recibos[0].read_text(encoding="utf-8"))
        self.assertEqual(recibo["schema"], "ejecucion/v1")
        self.assertEqual(recibo["unidad"], self.unidad)
        self.assertEqual(recibo["cwd"], str(self.worktree.resolve()))
        self.assertEqual(recibo["rama"], self.unidad)
        self.assertEqual(recibo["exit_code"], 0)
        self.assertEqual(
            set(recibo["lease"]["fencing"]),
            {"unit:001-demo", "resource:app/demo.py"},
        )
        self.assertEqual(recibo["git"]["inicial"]["head"], recibo["git"]["final"]["head"])
        self.assertRegex(recibo["git"]["inicial"]["diff_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("status_porcelain", recibo["git"]["final"])
        # Unidad 012: sin sandbox de SO no hay campo sandbox/sandbox_ejecutable ni
        # checkpoint "sandbox" — el recibo pasa directo de "identidad" a "harness".
        self.assertNotIn("sandbox", recibo)
        self.assertNotIn("sandbox_ejecutable", recibo)
        # Bug 065, R2: entre "identidad" y "harness" entra "modelo" — qué modelo y qué
        # esfuerzo salieron de la tabla de la regla 10, y si fueron tabla o excepción.
        # Antes esa decisión no dejaba rastro ninguno en el recibo.
        # Unidad 108, R1/R2: y detrás de "harness" entra "modelo-acreditado", que dice si
        # el recibo ACREDITA (leyó con qué modelo corrió de verdad) o solo declara.
        self.assertEqual(
            [item["nombre"] for item in recibo["checkpoints"]],
            ["lease", "identidad", "modelo", "harness", "modelo-acreditado"],
        )
        modelo = next(i for i in recibo["checkpoints"] if i["nombre"] == "modelo")
        self.assertIn(recibo["modelo_origen"], modelo["detalle"])
        # Este doble no deja transcript, así que la acreditación sale `warn` — que es justo
        # lo que R2 pide: sin fuente, el recibo no se declara acreditado.
        acreditacion = next(
            i for i in recibo["checkpoints"] if i["nombre"] == "modelo-acreditado")
        self.assertEqual(acreditacion["estado"], "warn")
        self.assertIsNone(recibo["model_slug"])
        self.assertTrue(all(item["estado"] == "ok" for item in recibo["checkpoints"]
                            if item["nombre"] != "modelo-acreditado"))
        self.assertIn("RESULTADO", resultado.stdout)

    # --- Unidad 028: control plane endurecido -----------------------------------------

    def test_constructor_no_puede_escribir_su_propia_ficha(self):
        # R3 (adversarial 12-08, hallazgo 9): el constructor pierde escritura sobre
        # especificacion.md de su unidad. La denegación tiene que ser REAL (regla del
        # método para permisos), no solo la ausencia de la ruta en argv.
        self.crear_doble_harness_que_intenta_escribir_ficha("claude")
        ficha = self.ws / "docs/05-trabajo" / self.unidad / "especificacion.md"
        contenido_previo = ficha.read_text(encoding="utf-8")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        intento = json.loads(
            (self.worktree / ".intento-escritura-ficha.json").read_text(encoding="utf-8"))
        self.assertEqual(intento["ficha"], str(ficha.resolve()))
        self.assertFalse(
            intento["escribio"], f"el constructor pudo escribir su propia ficha: {intento}"
        )
        self.assertTrue(
            intento["error"], f"se esperaba una denegación REAL del sistema de ficheros: {intento}"
        )
        self.assertEqual(
            ficha.read_text(encoding="utf-8"), contenido_previo,
            "la ficha no debe cambiar aunque el intento de escritura falle",
        )
        # La frontera es solo mientras corre el harness: el padre debe poder seguir
        # escribiendo la ficha después (aprobado:, estado: en_revision, ...).
        ficha.write_text(contenido_previo + "\n# tocado por el padre tras el harness\n",
                         encoding="utf-8")

    def test_revisor_no_pierde_escritura_de_hallazgos(self):
        # R4: nada de esta unidad recorta al revisor — sigue sin la ficha en su set
        # escribible (como hoy) y sin que se le fuerce ningún modo de solo lectura.
        ficha = self.ws / "docs/05-trabajo" / self.unidad / "especificacion.md"
        modo_previo = ficha.stat().st_mode

        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(
            ficha.stat().st_mode, modo_previo,
            "R4: el revisor no toca el modo de la ficha, ni antes ni ahora",
        )

    def test_recibo_ok_sin_trabajo_cuando_el_harness_no_toca_nada(self):
        # R5: el fallo del "verde que miente" — exit 0 sin ninguna casilla nueva ni
        # hallazgos.md actualizado debe distinguirse de un ok real.
        self.crear_doble_harness("claude", marca_trabajo=False)
        resultado = self.ejecutar()

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = json.loads(
            next((self.ws / ".runtime/ejecuciones").glob("001-demo-*.json"))
                .read_text(encoding="utf-8")
        )
        self.assertEqual(recibo["resultado"], "ok_sin_trabajo")
        self.assertFalse(recibo["trabajo"]["acreditado"])
        self.assertIn("no acreditó trabajo", recibo["trabajo"]["detalle"])
        self.assertIn("ok_sin_trabajo", resultado.stdout)

    def test_recibo_ok_cuando_el_harness_marca_trabajo(self):
        # R6 (caso límite): el falso positivo inverso no se introduce — si SÍ hubo
        # trabajo real, el recibo sigue diciendo ok, igual que hoy.
        self.crear_doble_harness_que_marca_trabajo("claude")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = json.loads(
            next((self.ws / ".runtime/ejecuciones").glob("001-demo-*.json"))
                .read_text(encoding="utf-8")
        )
        self.assertEqual(recibo["resultado"], "ok")
        self.assertTrue(recibo["trabajo"]["acreditado"])

    def test_aurora_old_new_y_mutante_de_cwd(self):
        # OLD: un proceso heredado desde main ve el cwd equivocado y una variable vacía
        # convierte `$SCRATCH/mut048` en la ruta raíz observada en Aurora.
        old = subprocess.run(
            [sys.executable, "-c",
             "import json,os; print(json.dumps({'cwd':os.getcwd(), "
             "'target':(os.environ.get('SCRATCH','') + '/mut048')}))"],
            cwd=self.main, env=self.env, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )
        observado_old = json.loads(old.stdout)
        # _real() (no .resolve()), para COMPARAR: en Windows el runner reporta el
        # mismo directorio unas veces por su alias corto 8.3 (RUNNER~1, lo que
        # devuelve os.getcwd() del proceso hijo aquí) y otras por el nombre largo
        # (runneradmin, lo que devuelve Path.resolve()) — misma causa de la
        # familia 3 del bug 017, aquí en el propio test.
        self.assertEqual(
            {"cwd": ejecucion._real(observado_old["cwd"]), "target": observado_old["target"]},
            {"cwd": ejecucion._real(self.main), "target": "/mut048"},
        )

        # NEW: el control plane corrige cwd antes de ejecutar el harness — por código,
        # sin sandbox de SO de por medio (unidad 012: esta es la garantía que se
        # mantiene íntegra).
        nuevo = self.ejecutar()
        self.assertNotEqual(nuevo.returncode, 0, nuevo.stdout + nuevo.stderr)
        harness = self.registros()
        self.assertEqual(harness["cwd"], str(self.worktree.resolve()))

        # Unidad 012 retira el tercer tramo (MUTANTE) de este test: verificaba que un
        # `cwd` de arranque incorrecto fallara en claro, pero esa verificación vivía en
        # el probe DENTRO del sandbox de SO (`verificar_sandbox`), que corría el probe
        # como proceso aparte y comparaba su `os.getcwd()` observado contra el
        # `worktree` esperado — una comprobación independiente del propio valor de la
        # variable `cwd` que se le pasaba a `subprocess.run`. Sin sandbox, esa segunda
        # verificación independiente ya no existe: `resolver_worktree()` sigue siendo
        # la única fuente de verdad, auditada por lectura de código, no por un runtime
        # check redundante. Documentado como hallazgo en docs/05-trabajo/
        # 012-quitar-sandbox-so-lanzador/hallazgos.md — es una pérdida de
        # defensa-en-profundidad real, distinta del riesgo de escritura ya aceptado en
        # el contrato, y candidata a una unidad de seguimiento si se quiere recuperar
        # sin volver al sandbox de SO.


class LanzadorHarnessClaudeDeFabricaTest(ControlPlaneE2ETest):
    """Bug 001-lanzador-harness-claude: el camino claude no funciona de fábrica.

    Cada test reproduce uno de los defectos de la ficha docs/bugs/001-… del
    workspace que reportó la caja negra de campo (12-08-2026). E2E sobre el
    fixture donde el defecto es observable en argv/entorno; a nivel de módulo
    (el fichero ORIGINAL) donde el defecto vive en la preparación del entorno.

    Unidad 012 (15-08-2026) retiró los defectos 1, 5 (mitad estado del CLI) y 10, que
    vivían en el perfil seatbelt y el probe de sandbox — ya no existen, así que sus
    tests (`test_seatbelt_*`, `test_probe_ejercita_el_guardado_atomico`) se retiran
    con ellos. El defecto 4 se invierte: ya NO se aísla el HOME de claude a propósito
    (`test_claude_hereda_home_real` sustituye a `test_claude_usa_home_aislado`).
    """

    def modulo_original(self):
        import importlib.util

        origen = RAIZ / "plantilla/docs/00-metodo/scripts"
        spec = importlib.util.spec_from_file_location(
            "ejecucion_original", origen / "ejecucion.py"
        )
        modulo = importlib.util.module_from_spec(spec)
        anterior = sys.path[:]
        sys.path.insert(0, str(origen))
        try:
            spec.loader.exec_module(modulo)
        finally:
            sys.path[:] = anterior
        return modulo

    # --- Defecto 2: el CLI rechaza --mcp-config {} (exige la clave mcpServers)

    def test_mcp_config_declara_mcpservers(self):
        resultado = self.ejecutar()
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        argv = harness["argv"]
        mcp = json.loads(argv[argv.index("--mcp-config") + 1])
        self.assertIn("mcpServers", mcp, "el CLI de claude rechaza un mcp-config sin la clave mcpServers")

    # --- Defecto 6: dontAsk deniega Write/Edit en headless; debe ser bypassPermissions

    def test_permission_mode_no_es_dontask(self):
        resultado = self.ejecutar()
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        argv = harness["argv"]
        modo = argv[argv.index("--permission-mode") + 1]
        self.assertEqual(
            modo, "bypassPermissions",
            "dontAsk deniega Write/Edit/Bash por defecto en headless",
        )

    # --- Defecto 4 (unidad 012, invertido): claude hereda el HOME real, no uno aislado

    def test_claude_hereda_home_real(self):
        resultado = self.ejecutar()
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        self.assertEqual(
            harness["home"], str(self.home.resolve()),
            "unidad 012: claude ya no recibe un HOME aislado — hereda la sesión real "
            "del usuario (llavero incluido), que es lo que resuelve la autenticación "
            "sin token manual",
        )

    # --- Defecto 5 (mitad lecturas): el constructor debe poder leer docs/ del meta-repo

    def test_add_dir_incluye_docs_del_workspace(self):
        resultado = self.ejecutar()
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        argv = harness["argv"]
        directorios = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--add-dir"]
        self.assertIn(
            str((self.ws / "docs").resolve()), directorios,
            "el contrato manda leer bias/flujos/síntesis: docs/ del meta-repo debe ir en --add-dir",
        )

    # --- Defecto 11: el revisor exige modelo DISTINTO (regla 10); falta --modelo
    #
    # Bug 065: `--modelo` dejó de ser la vía normal —el modelo lo deriva la tabla del carril
    # (repo_config.plan_de_modelo)— y pasó a ser una EXCEPCIÓN declarada. El flag sigue
    # mandando sobre la tabla, que es lo que este test fija; lo que cambia es que ahora
    # exige decir por qué, y eso se comprueba aquí mismo en vez de dejarlo implícito.

    def test_lanzar_acepta_modelo_explicito(self):
        argv = self.argumentos()
        argv[argv.index("--rol"):argv.index("--rol")] = [
            "--modelo", "claude-opus-5",
            "--motivo-modelo", "excepción declarada por el padre",
        ]
        resultado = subprocess.run(
            argv, cwd=self.main, env=self.env, text=True,
            encoding="utf-8", errors="replace", capture_output=True
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        registrado = harness["argv"]
        self.assertIn("--model", registrado)
        self.assertEqual(registrado[registrado.index("--model") + 1], "claude-opus-5")

    def test_el_modelo_explicito_sin_motivo_no_arranca_el_harness(self):
        argv = self.argumentos()
        argv[argv.index("--rol"):argv.index("--rol")] = ["--modelo", "claude-opus-5"]
        resultado = subprocess.run(
            argv, cwd=self.main, env=self.env, text=True,
            encoding="utf-8", errors="replace", capture_output=True
        )
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("--motivo-modelo", resultado.stdout + resultado.stderr)
        self.assertFalse((self.worktree / ".harness-record.json").exists())

    # --- Defectos 3 y 8: credenciales de suscripción y de GitHub deben heredarse

    def test_heredar_env_incluye_credenciales_de_claude_y_github(self):
        modulo = self.modulo_original()
        for variable in ("CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            self.assertIn(
                variable, modulo.HEREDAR_ENV,
                f"{variable} sigue disponible para CI/hosts sin sesión interactiva "
                "(unidad 012: ya no es la única vía, pero sigue siendo válida)",
            )

    def test_heredar_env_incluye_user_y_logname_para_el_llavero(self):
        # R1: heredar HOME NO basta para que el llavero de macOS sirva la credencial
        # de Claude — verificado en sesión con `claude auth status` real: sin USER/
        # LOGNAME el resultado es loggedIn=false pese a HOME correcto.
        modulo = self.modulo_original()
        for variable in ("USER", "LOGNAME"):
            self.assertIn(variable, modulo.HEREDAR_ENV)

    # --- Bug 037: en Windows el agente delegado arranca sin las variables del sistema
    #
    # ESTE TALLER ES macOS: no hay máquina Windows donde ejecutar el fallo real
    # (socket 11003 al resolver chatgpt.com). Lo que sí es independiente de la
    # plataforma es el MECANISMO: `entorno_base()` construye el entorno del hijo con
    # una allowlist, y lo que no está en la allowlist NO llega, corra donde corra.
    # Por eso el test de abajo se comprueba de dos maneras honestas:
    #   1. end-to-end de verdad (el launcher real lanza el harness doble) con las
    #      cinco variables presentes en el entorno padre, y se mira qué recibió el
    #      hijo. Aquí lo simulado es solo el ORIGEN de las variables, no el filtro.
    #   2. simulando la plataforma (os.name='nt', sys.platform='win32') y un
    #      os.environ con la pinta que tiene en Windows.
    # Lo que NO se puede comprobar aquí y queda pendiente de una máquina Windows
    # real: que con estas cinco variables winsock resuelva DNS y el harness deje de
    # reconectar. Eso lo acredita el equipo del alumno, no esta suite.

    VARIABLES_DE_WINDOWS = ("SYSTEMROOT", "WINDIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA")

    def test_el_agente_delegado_recibe_las_variables_de_sistema_de_windows(self):
        entorno_windows = {
            "SYSTEMROOT": r"C:\Windows",
            "WINDIR": r"C:\Windows",
            "USERPROFILE": r"C:\Users\alumno",
            "APPDATA": r"C:\Users\alumno\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\alumno\AppData\Local",
        }
        env = dict(self.env, **entorno_windows)
        resultado = self.ejecutar(env=env)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibido = self.registros()["windows"]
        for variable, valor in entorno_windows.items():
            self.assertEqual(
                recibido.get(variable), valor,
                f"bug 037: {variable} no llega al agente delegado; en Windows sin ella "
                "el resolvedor de nombres muere con el socket 11003 y el harness se "
                "queda reconectando (caja negra a19ef4d7, Nicolas Varela)",
            )

    def test_entorno_base_simulando_windows_conserva_las_variables_del_sistema(self):
        modulo = self.modulo_original()
        # os.environ en Windows expone las claves en MAYÚSCULAS aunque el sistema las
        # escriba `SystemRoot`/`windir`: lo hace el propio os.py (encodekey=str.upper).
        # Se simula así, que es lo que vería el launcher en la máquina del alumno.
        entorno_windows = {
            "PATH": r"C:\Windows\system32;C:\Program Files\Git\cmd",
            "SYSTEMROOT": r"C:\Windows",
            "WINDIR": r"C:\Windows",
            "USERPROFILE": r"C:\Users\alumno",
            "APPDATA": r"C:\Users\alumno\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\alumno\AppData\Local",
        }
        with mock.patch.object(modulo.os, "environ", entorno_windows), \
                mock.patch.object(modulo.os, "name", "nt"), \
                mock.patch.object(modulo.sys, "platform", "win32"):
            limpio = modulo.entorno_base(self.worktree, self.base / "tmp", self.home)
        for variable in self.VARIABLES_DE_WINDOWS:
            self.assertEqual(
                limpio.get(variable), entorno_windows[variable],
                f"bug 037: entorno_base() descarta {variable} — la allowlist se "
                "escribió para macOS/Linux y nunca se revisó contra Windows",
            )

    def test_heredar_env_incluye_las_variables_de_windows(self):
        modulo = self.modulo_original()
        for variable in self.VARIABLES_DE_WINDOWS:
            self.assertIn(
                variable, modulo.HEREDAR_ENV,
                f"bug 037: {variable} falta en la allowlist del launcher",
            )

    def test_la_allowlist_sigue_siendo_allowlist_tras_el_arreglo(self):
        # Guarda, no reproducción: pasa con y sin el arreglo. Está para que ampliar la
        # lista por Windows no acabe convirtiéndose en "heredarlo todo".
        modulo = self.modulo_original()
        for variable in ("PSMODULEPATH", "PROMPT", "NODE_OPTIONS", "PYTHONPATH"):
            self.assertNotIn(variable, modulo.HEREDAR_ENV)

    # --- Defecto 9 (unidad 012: adaptado a HOME real, ya no aislado)

    def test_preparar_claude_home_configura_gh_con_token(self):
        modulo = self.modulo_original()
        self.assertTrue(
            hasattr(modulo, "preparar_claude_home"),
            "falta preparar_claude_home()",
        )
        gh_registro = Path(self.temporal.name) / "gh-setup-git.json"
        cuerpo_gh = (
            "import json, os, pathlib, sys\n"
            f"pathlib.Path({str(gh_registro)!r}).write_text(json.dumps(\n"
            "    {'argv': sys.argv[1:], 'home': os.environ.get('HOME')}),\n"
            "    encoding='utf-8')\n"
        )
        self.instalar_doble("gh", cuerpo_gh)
        env = {
            "HOME": str(self.home),
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "GH_TOKEN": "gho_token_de_prueba",
        }
        modulo.preparar_claude_home(env, self.home)
        self.assertEqual(env["HOME"], str(self.home), "unidad 012: HOME no se aísla")
        self.assertTrue(gh_registro.is_file(), "con GH_TOKEN presente debe correr gh auth setup-git")
        registro = json.loads(gh_registro.read_text(encoding="utf-8"))
        self.assertEqual(registro["argv"][:2], ["auth", "setup-git"])
        self.assertEqual(registro["home"], str(self.home))

    def test_preparar_claude_home_para_en_claro_sin_identidad_de_git(self):
        # Caso límite (R1): sin sandbox de SO que dé igual un HOME vacío, un HOME real
        # sin identidad de git configurada debe fallar en claro, no arrastrar el
        # problema hasta que el harness intente comitear a medio trabajo.
        modulo = self.modulo_original()
        home_vacio = Path(self.temporal.name) / "home-sin-git"
        home_vacio.mkdir()
        env = {"HOME": str(home_vacio), "PATH": os.environ.get("PATH", "")}
        with self.assertRaises(modulo.ErrorEjecucion) as contexto:
            modulo.preparar_claude_home(env, home_vacio)
        self.assertIn("user.name", str(contexto.exception))

    def test_codex_no_recibe_lecturas_como_escribibles(self):
        resultado = self.ejecutar(harness="codex")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        argv = harness["argv"]
        directorios = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--add-dir"]
        # En codex --add-dir significa "directorio ESCRIBIBLE adicional" (su --help):
        # las lecturas de docs/ son un asunto exclusivo del harness claude.
        self.assertNotIn(
            str((self.ws / "docs").resolve()), directorios,
            "docs/ entero no debe declararse escribible en la capa codex",
        )


class RevisorEnCarrilDirectoTest(ControlPlaneE2ETest):
    """Bug 002-revisor-carril-directo: el revisor fresco debe poder lanzarse por el
    control plane en carril directo/exprés (AGENTS.md regla 1); solo el
    CONSTRUCTOR debe quedar rechazado en esos carriles."""

    def crear_unidad_directo(self, nombre="002-demo"):
        ficha = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nnumero: 002\ntipo: feature\nestado: en_obra\ncarril: directo\n"
            "ficheros: [app/demo.py]\n---\n# Demo directo\n",
            encoding="utf-8",
        )
        (ficha.parent / "hallazgos.md").write_text("# Hallazgos\n", encoding="utf-8")
        destino = self.ws / "worktrees" / nombre
        self.git("worktree", "add", str(destino), "-b", nombre, "main", cwd=self.main)
        return destino

    def test_revisor_se_lanza_en_carril_directo(self):
        worktree = self.crear_unidad_directo()
        resultado = self.ejecutar(rol="revisor", unidad="002-demo")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = json.loads((worktree / ".harness-record.json").read_text(encoding="utf-8"))
        self.assertEqual(harness["branch"], "002-demo")

    def test_constructor_sigue_rechazado_en_carril_directo(self):
        self.crear_unidad_directo()
        resultado = self.ejecutar(rol="constructor", unidad="002-demo")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn(
            "el carril directo lo construye el padre",
            resultado.stdout + resultado.stderr,
        )


class AnclaDeLaRevisionTest(ControlPlaneE2ETest):
    """Unidad 068 · R1 — al lanzar al revisor, el launcher congela QUÉ se está revisando.

    Hasta hoy la firma era una fecha y un modelo: nada decía sobre qué contenido se dio el
    veredicto, así que un commit posterior la dejaba intacta. El ancla es el `git patch-id
    --stable` del diff de la rama contra la principal, y lo escribe el launcher —no el
    agente— en el recibo y en la cabecera de hallazgos.md.
    """

    CABECERA = ("---\nunidad: 001-demo\nrevisor: no\nrevisado: no\n"
                "revisado_patch_id: no      # lo escribe el launcher\n---\n\n"
                "# 001 · Hallazgos\n")

    def setUp(self):
        super().setUp()
        self.hallazgos = self.ws / "docs/05-trabajo" / self.unidad / "hallazgos.md"
        self.hallazgos.write_text(self.CABECERA, encoding="utf-8")
        # Una rama sin commits propios no tiene diff, y sin diff no hay huella que anclar.
        (self.worktree / "app").mkdir(parents=True, exist_ok=True)
        (self.worktree / "app/demo.py").write_text("print('uno')\n", encoding="utf-8")
        self.git("add", "app/demo.py", cwd=self.worktree)
        self.git("commit", "-m", "001-demo: el trabajo a revisar", cwd=self.worktree)

    def patch_id_esperado(self):
        base = subprocess.run(
            ["git", "-C", str(self.worktree), "merge-base", "main", "HEAD"],
            check=True, capture_output=True).stdout.decode().strip()
        diff = subprocess.run(["git", "-C", str(self.worktree), "diff", base, "HEAD"],
                              check=True, capture_output=True).stdout
        salida = subprocess.run(["git", "-C", str(self.worktree), "patch-id", "--stable"],
                                input=diff, check=True, capture_output=True).stdout
        piezas = salida.decode().split()
        self.assertTrue(piezas, "git patch-id no devolvió nada para el diff de la rama")
        return piezas[0]

    def recibo(self):
        recibos = [r for r in (self.ws / ".runtime/ejecuciones").glob("001-demo-*.json")
                   if json.loads(r.read_text(encoding="utf-8")).get("rol") != "constructor"]
        self.assertEqual(len(recibos), 1, recibos)
        return json.loads(recibos[0].read_text(encoding="utf-8"))

    def firmado_en_hallazgos(self):
        encontrado = re.search(r"(?m)^revisado_patch_id:\s*([^\s#]*)",
                               self.hallazgos.read_text(encoding="utf-8"))
        self.assertIsNotNone(encontrado, self.hallazgos.read_text(encoding="utf-8"))
        return encontrado.group(1)

    def test_el_lanzamiento_del_revisor_ancla_recibo_y_cabecera_al_mismo_patch_id(self):
        esperado = self.patch_id_esperado()
        resultado = self.ejecutar(rol="revisor")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.recibo()["revisado_patch_id"], esperado)
        self.assertEqual(self.firmado_en_hallazgos(), esperado)

    def test_el_patch_id_no_cambia_con_un_rebase_limpio(self):
        """El ancla habla del CONTENIDO: otro SHA con las mismas líneas es la misma firma."""
        antes = self.patch_id_esperado()
        (self.main / "OTRO.md").write_text("trabajo ajeno\n", encoding="utf-8")
        self.git("add", "OTRO.md", cwd=self.main)
        self.git("commit", "-m", "la principal avanza", cwd=self.main)
        punta_previa = subprocess.run(
            ["git", "-C", str(self.worktree), "rev-parse", "HEAD"],
            check=True, capture_output=True).stdout.decode().strip()
        self.git("rebase", "main", cwd=self.worktree)
        punta_nueva = subprocess.run(
            ["git", "-C", str(self.worktree), "rev-parse", "HEAD"],
            check=True, capture_output=True).stdout.decode().strip()
        self.assertNotEqual(punta_previa, punta_nueva, "el rebase no movió la punta")
        self.assertEqual(self.patch_id_esperado(), antes)
        resultado = self.ejecutar(rol="revisor")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.recibo()["revisado_patch_id"], antes)

    def test_el_constructor_no_ancla_nada(self):
        """El ancla la pone quien revisa. Un constructor no firma, así que no congela nada."""
        resultado = self.ejecutar(rol="constructor")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIsNone(self.recibo()["revisado_patch_id"])
        self.assertEqual(self.firmado_en_hallazgos(), "no")

    def test_una_cabecera_anterior_a_la_068_no_se_toca(self):
        """R5: sin la clave, la unidad nació antes; el launcher no le inventa una cabecera."""
        self.hallazgos.write_text("# Hallazgos\n", encoding="utf-8")
        resultado = self.ejecutar(rol="revisor")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("revisado_patch_id",
                         self.hallazgos.read_text(encoding="utf-8"))
        self.assertEqual(self.recibo()["revisado_patch_id"], self.patch_id_esperado())


class RondasDeCorreccionTest(ControlPlaneE2ETest):
    """Unidad 069 · R1-R6 — las vueltas al constructor se CUENTAN, y a la tercera se para.

    `cierre.md` decía en prosa que «una segunda ronda solo la abre un fallo crítico» y nada
    la contaba: la 054 fue a segunda ronda sin que ningún script lo supiera. El contador lo
    escribe el lanzador —no el agente—, por el mismo motivo que el ancla de la 068: un
    número tecleado por quien tiene que respetarlo no es una medida (ADR-029).
    """

    CABECERA = ("---\nunidad: 001-demo\nrevisor: no\nrevisado: no\n"
                "revisado_patch_id: no\nronda: 1        # lo escribe el lanzador\n"
                "correccion: no  # lo escribe el lanzador desde la ronda 2\n---\n\n"
                "# 001 · Hallazgos\n\n## Revisión\n\n"
                "- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN\n")

    def setUp(self):
        super().setUp()
        self.hallazgos = self.ws / "docs/05-trabajo" / self.unidad / "hallazgos.md"
        self.hallazgos.write_text(self.CABECERA, encoding="utf-8")
        # Una rama con trabajo propio: sin diff original no hay nada contra lo que medir la
        # corrección (R4), y el patch-id de la 068 tampoco tendría qué anclar.
        (self.worktree / "app").mkdir(parents=True, exist_ok=True)
        (self.worktree / "app/demo.py").write_text(
            "print('uno')\nprint('dos')\nprint('tres')\n", encoding="utf-8")
        self.git("add", "app/demo.py", cwd=self.worktree)
        self.git("commit", "-m", "001-demo: el trabajo original", cwd=self.worktree)

    def crear_doble_harness_que_corrige(self, nombre):
        """Un doble que SÍ deja trabajo commiteado: una ronda real, no una vacía (R5)."""
        cuerpo = """import json, pathlib, subprocess
destino = pathlib.Path('app/demo.py')
destino.write_text("print('uno')\\nprint('corregido')\\n", encoding='utf-8')
subprocess.run(['git', 'add', 'app/demo.py'])
subprocess.run(['git', 'commit', '-m', 'correccion de la ronda'], capture_output=True)
pathlib.Path('.harness-record.json').write_text(
    json.dumps({'corrigio': True}), encoding='utf-8')
"""
        self.instalar_doble(nombre, cuerpo)

    def clave(self, nombre):
        encontrado = re.search(rf"(?m)^{nombre}:\s*([^\s#]*)",
                               self.hallazgos.read_text(encoding="utf-8"))
        return encontrado.group(1) if encontrado else None

    def poner_veredicto(self, valor):
        self.hallazgos.write_text(
            self.hallazgos.read_text(encoding="utf-8").replace(
                "- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN",
                f"- **Veredicto:** {valor}"),
            encoding="utf-8")

    def recibo(self):
        recibos = [r for r in (self.ws / ".runtime/ejecuciones").glob("001-demo-*.json")
                   if json.loads(r.read_text(encoding="utf-8")).get("harness")
                   != "subagente-del-padre"]
        self.assertEqual(len(recibos), 1, recibos)
        return json.loads(recibos[0].read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ R1: contar
    def test_el_primer_constructor_deja_la_ronda_en_1(self):
        """Sin veredicto previo no hay vuelta: la primera obra es la ronda 1, no la 2."""
        self.crear_doble_harness_que_corrige("claude")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.clave("ronda"), "1")
        self.assertEqual(self.recibo()["ronda"], 1)

    def test_un_veredicto_con_huecos_sube_la_ronda_a_2(self):
        """R1 — la vuelta que hoy nadie cuenta. La sube el lanzador, no el constructor."""
        self.crear_doble_harness_que_corrige("claude")
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.clave("ronda"), "2")
        self.assertEqual(self.recibo()["ronda"], 2)

    def test_un_veredicto_limpio_no_sube_la_ronda(self):
        """Relanzar al constructor tras un LIMPIO no es una corrección: no gasta ronda."""
        self.crear_doble_harness_que_corrige("claude")
        self.poner_veredicto("LIMPIO")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.clave("ronda"), "1")

    # ------------------------------------------------------------------ R4: medir
    def test_la_ronda_2_anota_el_tamano_de_la_correccion(self):
        """R4 — informa, no bloquea: `+N/-M` de la corrección frente al diff original."""
        self.crear_doble_harness_que_corrige("claude")
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        medida = re.search(r"(?m)^correccion:\s*(.+)$",
                           self.hallazgos.read_text(encoding="utf-8")).group(1)
        self.assertRegex(medida, r"\+\d+/-\d+")
        self.assertRegex(medida, r"rama.*\+\d+/-\d+")
        self.assertRegex(self.recibo()["correccion"], r"\+\d+/-\d+")

    def test_la_ronda_1_no_anota_correccion(self):
        """Nada que medir en la primera obra: la clave se queda como estaba."""
        self.crear_doble_harness_que_corrige("claude")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.clave("correccion"), "no")

    # ------------------------------------------------------------- R2: la parada
    def test_la_tercera_ronda_se_rechaza_y_la_decide_el_usuario(self):
        """**El criterio portante**: sin esta parada, contar rondas no cambia nada."""
        self.crear_doble_harness_que_corrige("claude")
        self.hallazgos.write_text(
            self.hallazgos.read_text(encoding="utf-8").replace("ronda: 1", "ronda: 2"),
            encoding="utf-8")
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        resultado = self.ejecutar()

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("tercera ronda", salida.lower())
        for opcion in ("subir de carril", "reabrir el contrato", "cancelar"):
            self.assertIn(opcion, salida.lower(), salida)
        self.assertFalse(
            (self.worktree / ".harness-record.json").exists(),
            "R2: el rechazo es ANTES del harness; si el agente llegó a correr, no hubo parada")
        self.assertEqual(self.clave("ronda"), "2", "un rechazo no gasta la ronda")

    def test_bajar_la_ronda_a_mano_no_regala_una_tercera_vuelta(self):
        """H1 de la revisión — la parada NO puede depender de una línea que el constructor
        posee. `hallazgos.md` está en su set escribible: si el contador solo viviera en su
        cabecera, `sed -i 's/ronda: 2/ronda: 1/'` compraba una ronda más. Los recibos de
        `.runtime/ejecuciones` los escribe el lanzador y nadie los tiene escribibles, así
        que mandan ellos (ADR-029)."""
        self.crear_doble_harness_que_corrige("claude")
        recibos = self.ws / ".runtime/ejecuciones"
        recibos.mkdir(parents=True, exist_ok=True)
        (recibos / f"{self.unidad}-anterior.json").write_text(json.dumps({
            "schema": "ejecucion/v1", "id": "anterior", "unidad": self.unidad,
            "rol": "constructor", "ronda": 2, "exit_code": 0, "resultado": "ok",
        }), encoding="utf-8")
        # La cabecera dice 1 —es el número que el constructor SÍ posee y puede rebajar—
        # mientras el recibo de arriba acredita que la ronda 2 ya se gastó.
        self.assertEqual(self.clave("ronda"), "1")
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        resultado = self.ejecutar()

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("tercera ronda", salida.lower())
        self.assertFalse(
            (self.worktree / ".harness-record.json").exists(),
            "la cabecera decía 1, pero los recibos acreditan 2: el harness no debió arrancar")

    def test_sin_recibos_con_ronda_manda_la_cabecera(self):
        """La simétrica: los recibos ACREDITAN, no inventan. Una unidad anterior a la 069
        —recibos sin `ronda`— sigue contando por su cabecera y no se para de más."""
        self.crear_doble_harness_que_corrige("claude")
        recibos = self.ws / ".runtime/ejecuciones"
        recibos.mkdir(parents=True, exist_ok=True)
        (recibos / f"{self.unidad}-viejo.json").write_text(json.dumps({
            "schema": "ejecucion/v1", "id": "viejo", "unidad": self.unidad,
            "rol": "constructor", "exit_code": 0, "resultado": "ok",
        }), encoding="utf-8")
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.clave("ronda"), "2")

    def test_el_rechazo_de_la_tercera_ronda_lleva_su_marca_de_salida_por_diseno(self):
        """R6 — no hay comando que lo arregle, y eso se declara con el vocabulario cerrado
        de `lint_salidas.py`: la decisión es del usuario, no del método."""
        fuente = LAUNCHER.read_text(encoding="utf-8")
        bloque = fuente[fuente.index("def rondas_del_constructor"):]
        bloque = bloque[:bloque.index("\ndef ", 1)]
        self.assertIn("salida:por-diseño autoridad-humana", bloque)

    # -------------------------------------------------------- R5: la ronda vacía
    def test_una_ejecucion_que_no_toca_nada_no_gasta_ronda(self):
        """R5 (404f41af: el 18 % terminó sin dejar un byte) — mismo head y mismo
        diff_sha256 que al empezar no es una corrección: no cuenta y queda marcada."""
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        self.crear_doble_harness("claude", marca_trabajo=False)
        resultado = self.ejecutar()

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.clave("ronda"), "1", "R5: la ronda vacía se devuelve")
        recibo = self.recibo()
        self.assertTrue(recibo["ronda_vacia"])
        self.assertEqual(recibo["ronda"], 1)
        self.assertIn("vacía", (resultado.stdout + resultado.stderr).lower())

    def test_una_ejecucion_con_trabajo_no_se_marca_vacia(self):
        """El falso positivo inverso: si hubo corrección real, la ronda se gasta."""
        self.crear_doble_harness_que_corrige("claude")
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(self.recibo()["ronda_vacia"])

    # ------------------------------------------------- fronteras que no se mueven
    def test_una_cabecera_anterior_a_la_069_no_se_inventa(self):
        """Igual que el ancla de la 068: sin la clave, la unidad nació antes. No se le
        añade una cabecera a medias que el linter tendría que perdonar igual."""
        self.hallazgos.write_text("# Hallazgos\n", encoding="utf-8")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("ronda:", self.hallazgos.read_text(encoding="utf-8"))
        self.assertIsNone(self.recibo()["ronda"])

    def test_el_revisor_no_toca_la_ronda(self):
        """Las rondas las gasta quien corrige. Lanzar al revisor no cuenta ninguna.

        Bug 113 (R3): su recibo sí DECLARA la ronda que tiene delante —la de la cabecera—
        para que la firma quede pegada a una vuelta concreta; la cabecera no se mueve."""
        self.poner_veredicto("HUECOS DE CORRECCIÓN")

        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.clave("ronda"), "1")
        self.assertEqual(self.recibo()["ronda"], 1)
        self.assertFalse(self.recibo()["ronda_vacia"])

    def test_el_veredicto_que_lee_el_lanzador_es_el_mismo_que_lee_el_cierre(self):
        """La junta: `ejecucion.py` decide si hubo huecos y `unidad.py cerrar` decide si se
        puede cerrar. Si las dos lecturas divergen, una unidad se para donde la otra pasa —
        así que el patrón es literalmente el mismo texto en los dos scripts."""
        lanzador = LAUNCHER.read_text(encoding="utf-8")
        cierre = (LAUNCHER.parent / "unidad.py").read_text(encoding="utf-8")
        patron = re.search(r'(?m)^RE_VEREDICTO = re\.compile\(\n?(.+?)\n', cierre, re.S)
        self.assertIsNotNone(patron, "unidad.py ya no declara RE_VEREDICTO como se esperaba")
        self.assertIn(patron.group(1).strip(), lanzador,
                      "el lanzador y el cierre leen el veredicto con patrones distintos")


class CompatibilidadWindowsTest(unittest.TestCase):
    """Bug 017: reproducción portátil (mock/symlink, no requiere Windows) de las tres
    familias de fallo del CI en windows-latest. La verificación REAL de que el job
    windows-latest queda en verde la da el CI del PR, no esta suite en macOS/Linux."""

    def test_comando_subproceso_envuelve_bat_y_cmd_solo_en_windows(self):
        # Familia 2 (parte 2): CreateProcess no sabe arrancar un .bat/.cmd sin pasar
        # por el intérprete de comandos — sin este envoltorio, WinError 193.
        argv = ["C:\\bin\\claude.bat", "--safe-mode"]
        with mock.patch.object(ejecucion.os, "name", "nt"):
            envuelto_bat = ejecucion.comando_subproceso("C:\\bin\\claude.bat", argv)
            envuelto_cmd = ejecucion.comando_subproceso("C:\\bin\\codex.CMD", argv)
        comspec = ejecucion.os.environ.get("ComSpec", "cmd.exe")
        self.assertEqual(envuelto_bat, [comspec, "/c", *argv])
        self.assertEqual(envuelto_cmd, [comspec, "/c", *argv])

    def test_comando_subproceso_no_toca_nada_fuera_de_bat_cmd_o_windows(self):
        argv = ["/usr/bin/claude", "--safe-mode"]
        with mock.patch.object(ejecucion.os, "name", "posix"):
            self.assertEqual(ejecucion.comando_subproceso("/usr/bin/claude", argv), argv)
        # ni en Windows si el ejecutable ya es un .exe real, no un shim de shell.
        with mock.patch.object(ejecucion.os, "name", "nt"):
            self.assertEqual(
                ejecucion.comando_subproceso("C:\\bin\\claude.exe", argv), argv
            )

    def test_comando_subproceso_con_env_indirecciona_argumentos_multilinea(self):
        # Ronda 2 del bug 017: cmd.exe /c trocea su línea de comando en el primer
        # salto de línea, incluso entre comillas — el prompt del harness
        # (encargo(), siempre multilínea) llegaba truncado a la primera línea.
        # Ronda 3: dejar que el propio cmd.exe resolviera %IR_CMDARG_N% NO basta
        # — su sustitución trocea igual en el salto de línea y además parte el
        # resto en palabras sueltas por los espacios sin comillas.
        # Ronda 4: escribir ``%%IR_CMDARG_N%%`` TAMPOCO basta. El colapso
        # ``%%`` → ``%`` sin resolver es la regla de los ficheros .bat; en la
        # línea de comando de ``cmd /c`` el parser deja literal el primer ``%``
        # (no abre un nombre válido) y expande el ``%IR_CMDARG_N%`` que viene
        # justo detrás, devolviendo el valor multilínea a la línea de comando.
        # La referencia que cruza intacta es la que no tiene NINGÚN ``%``:
        # ``##IR_CMDARG_N##`` — es quien recibe ese token quien debe leer la
        # variable de su propio entorno heredado para reconstruir el argumento
        # efectivo.
        argv = ["C:\\bin\\claude.bat", "--safe-mode", "UNIDAD: 001\nROL: x", "sin-saltos"]
        env = {"YA_HABIA": "1"}
        with mock.patch.object(ejecucion.os, "name", "nt"):
            envuelto = ejecucion.comando_subproceso("C:\\bin\\claude.bat", argv, env)
        comspec = ejecucion.os.environ.get("ComSpec", "cmd.exe")
        self.assertEqual(
            envuelto,
            [comspec, "/c", "C:\\bin\\claude.bat", "--safe-mode", "##IR_CMDARG_1##", "sin-saltos"],
        )
        self.assertEqual(env["IR_CMDARG_1"], "UNIDAD: 001\nROL: x")
        self.assertNotIn("IR_CMDARG_2", env, "el argumento sin salto de línea no se toca")
        self.assertEqual(env["YA_HABIA"], "1", "no se pisa el resto del entorno del llamante")

    def test_la_referencia_en_la_linea_de_comando_no_lleva_metacaracteres_de_cmd(self):
        # Invariante que las rondas 2 y 3 violaron y que costó dos runs rojos: el
        # token que cruza cmd.exe no puede contener NADA que cmd.exe interprete.
        # Un '%' basta para que la línea de comando vuelva a expandir el valor
        # multilínea y se trunque en el primer salto de línea.
        argv = ["C:\\bin\\claude.bat", "-p", "linea1\nlinea2"]
        env = {}
        with mock.patch.object(ejecucion.os, "name", "nt"):
            envuelto = ejecucion.comando_subproceso("C:\\bin\\claude.bat", argv, env)
        referencia = envuelto[-1]
        self.assertNotIn(referencia, env.values(), "el valor no puede viajar en la línea")
        for metacaracter in '%&|<>^()" \t\r\n':
            self.assertNotIn(
                metacaracter, referencia,
                f"la referencia {referencia!r} lleva un metacarácter de cmd.exe",
            )
        self.assertEqual(env["IR_CMDARG_1"], "linea1\nlinea2")

    def test_doble_harness_en_windows_es_encontrable_por_pathext_y_delega_en_python(self):
        # Familia 2 (parte 1): shutil.which() en Windows solo ve extensiones de
        # PATHEXT; el doble de prueba sin extensión ("no encuentro el ejecutable
        # claude/codex" en el CI) necesita un .bat que delegue en el .py real.
        tmp = Path(tempfile.mkdtemp(prefix="doble-win-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        caso = ControlPlaneE2ETest.__new__(ControlPlaneE2ETest)
        caso.bin = tmp
        with mock.patch.object(os, "name", "nt"):
            caso.crear_doble_harness("claude")
        bat, script = tmp / "claude.bat", tmp / "claude.py"
        self.assertTrue(bat.is_file())
        self.assertTrue(script.is_file())
        self.assertIn(sys.executable, bat.read_text(encoding="utf-8"))
        self.assertIn(str(script), bat.read_text(encoding="utf-8"))
        self.assertIn(".harness-record.json", script.read_text(encoding="utf-8"))

    def test_real_normaliza_un_alias_de_ruta_al_mismo_destino(self):
        # Familia 3: análogo portable del alias corto (RUNNER~1) contra el largo
        # (runneradmin) de Windows — dos cadenas de ruta DISTINTAS que apuntan al
        # MISMO directorio (aquí, vía symlink) deben comparar igual tras _real().
        base = Path(tempfile.mkdtemp(prefix="real-alias-"))
        self.addCleanup(shutil.rmtree, base, True)
        real_dir = base / "runneradmin"
        real_dir.mkdir()
        alias = base / "RUNNER~1"
        # En Windows de verdad, NTFS ya genera "RUNNER~1" como alias 8.3
        # automático de "runneradmin" (>8 caracteres) en cuanto se crea el
        # directorio — crear el symlink a mano falla con WinError 183 (ya
        # existe) porque el alias ya está ahí sin que nadie lo pida; en ese
        # caso el propio SO nos regala el segundo nombre que el test necesita.
        if not alias.exists():
            alias.symlink_to(real_dir)
        self.assertNotEqual(str(alias), str(real_dir), "el test no aísla nada si ya son iguales")
        self.assertEqual(ejecucion._real(alias), ejecucion._real(real_dir))

    def test_inventario_worktrees_reconoce_el_worktree_pese_al_alias_de_ruta(self):
        # Sin _real(), un lookup de diccionario por Path/cadena exacta falla ante dos
        # representaciones del mismo directorio — es justo lo que reportó el CI
        # («... no figura en git worktree list») cuando git y Python difieren en cómo
        # escriben la MISMA ruta.
        base = Path(tempfile.mkdtemp(prefix="inventario-alias-"))
        self.addCleanup(shutil.rmtree, base, True)
        (base / "runneradmin").mkdir()
        alias = base / "RUNNER~1"
        # Ver el comentario equivalente en test_real_normaliza_...: en Windows
        # de verdad NTFS ya se adelanta y crea este alias 8.3 solo.
        if not alias.exists():
            alias.symlink_to(base / "runneradmin")
        destino_via_alias = alias / "worktrees" / "001-demo"
        destino_via_alias.parent.mkdir()
        destino_via_alias.mkdir()
        destino_via_python = base / "runneradmin" / "worktrees" / "001-demo"

        inventario = {ejecucion._real(destino_via_alias): {"branch": "refs/heads/001-demo"}}
        self.assertIn(ejecucion._real(destino_via_python), inventario)
        # El defecto real (antes del arreglo): sin pasar por _real(), la clave cruda
        # que habría guardado el lookup por Path era la del alias, y no coincidía
        # textualmente con la ruta que reporta Python del otro lado.
        self.assertNotEqual(str(destino_via_alias), str(destino_via_python))


class RevisorSobreUnidadDocumentalTest(ControlPlaneE2ETest):
    """Bug 090: una unidad `--documental` no tiene rama ni worktree por diseño (regla 2),
    así que `lanzar --rol revisor` moría con «no figura en git worktree list» y dejaba sin
    revisor fresco a auditorías, investigaciones y documentación.

    El worktree efímero de la 065 (R3) no cubre este caso: exige `estado:` entregado y un
    `fusion:` con commit, y una documental en `en_revision` no tiene ninguno de los dos.
    """

    UNIDAD = "003-auditoria"

    def setUp(self):
        super().setUp()
        self.registro = self.base / "registro-documental.json"
        self.sha_main = self.git("rev-parse", "HEAD", cwd=self.main).stdout.strip()
        self.destino_documental = self.ws / "worktrees" / self.UNIDAD

    # El doble escribe FUERA del worktree a propósito: el efímero se borra antes de que el
    # test pueda mirarlo, así que un `.harness-record.json` dentro de él no sobrevive.
    def instalar_grabador(self):
        cuerpo = f"DESTINO = {str(self.base / 'registro-documental.json')!r}\n" + """import json, pathlib, subprocess
def _git(*args):
    return subprocess.run(['git', *args], text=True, encoding='utf-8',
                          errors='replace', capture_output=True).stdout.strip()
pathlib.Path(DESTINO).write_text(json.dumps({
    'argv': argv,
    'cwd': os.getcwd(),
    'head': _git('rev-parse', 'HEAD'),
    'branch': _git('branch', '--show-current'),
}), encoding='utf-8')
"""
        for nombre in ("claude", "codex"):
            self.instalar_doble(nombre, cuerpo)

    def crear_unidad_documental(self, estado="en_revision", ejecucion_fm="documental"):
        self.instalar_grabador()
        ficha = self.ws / "docs/05-trabajo" / self.UNIDAD / "especificacion.md"
        ficha.parent.mkdir(parents=True, exist_ok=True)
        linea = f"ejecucion: {ejecucion_fm}\n" if ejecucion_fm else ""
        ficha.write_text(
            f"---\nnumero: 003\ntipo: auditoria\nestado: {estado}\ncarril: normal\n"
            f"{linea}ficheros: [docs/05-trabajo/{self.UNIDAD}/hallazgos.md]\n---\n"
            "# Auditoría documental\n",
            encoding="utf-8",
        )
        (ficha.parent / "hallazgos.md").write_text("# Hallazgos\n", encoding="utf-8")
        return ficha

    def recibo(self):
        recibos = sorted((self.ws / ".runtime/ejecuciones").glob(f"{self.UNIDAD}-*.json"))
        self.assertEqual(len(recibos), 1, f"se esperaba un único recibo: {recibos}")
        return json.loads(recibos[0].read_text(encoding="utf-8"))

    def registro_grabado(self):
        # Nombre propio: `registros()` es del padre y apunta al worktree, que aquí puede
        # no existir ya cuando el test mira.
        return json.loads(self.registro.read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- el bug
    def test_el_revisor_de_una_documental_se_lanza_sin_worktree_propio(self):
        self.crear_unidad_documental()

        resultado = self.ejecutar(rol="revisor", unidad=self.UNIDAD)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        registro = self.registro_grabado()
        self.assertEqual(Path(registro["cwd"]).name, self.UNIDAD)
        self.assertEqual(registro["head"], self.sha_main,
                         "el revisor documental lee lo que la unidad leyó: el HEAD de main/")
        self.assertEqual(registro["branch"], "", "el worktree de revisión va detached")

    def test_el_worktree_de_la_revision_documental_no_deja_rastro(self):
        self.crear_unidad_documental()

        resultado = self.ejecutar(rol="revisor", unidad=self.UNIDAD)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(self.destino_documental.exists(),
                         "el worktree efímero de la documental sigue en disco")
        inventario = self.git("worktree", "list", "--porcelain", cwd=self.main).stdout
        self.assertNotIn(self.UNIDAD, inventario)
        ramas = self.git("branch", "--list", cwd=self.main).stdout
        self.assertNotIn(self.UNIDAD, ramas, "una documental no estrena rama al revisarse")

    def test_el_recibo_dice_que_el_worktree_era_de_una_documental(self):
        self.crear_unidad_documental()

        resultado = self.ejecutar(rol="revisor", unidad=self.UNIDAD)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertTrue(recibo["worktree_efimero"])
        self.assertEqual(recibo["worktree_origen"], "documental")

    # ------------------------------------------------------- lo que NO cambia
    def test_el_constructor_de_una_documental_sigue_bloqueado(self):
        # La puerta es SOLO del revisor: una documental se construye leyendo main/, nunca
        # desde un worktree que el launcher se invente.
        self.crear_unidad_documental(estado="en_obra")

        resultado = self.ejecutar(rol="constructor", unidad=self.UNIDAD)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("SALIDA:", resultado.stdout + resultado.stderr)
        self.assertFalse(self.destino_documental.exists())

    def test_una_unidad_de_codigo_sin_worktree_sigue_rechazada(self):
        # Regresión de la 065: sin `ejecucion: documental` y sin worktree, el revisor sigue
        # topándose con el rechazo de siempre (y su salida), no con el camino nuevo.
        self.crear_unidad_documental(estado="en_revision", ejecucion_fm=None)

        resultado = self.ejecutar(rol="revisor", unidad=self.UNIDAD)

        self.assertNotEqual(resultado.returncode, 0)
        salida = resultado.stdout + resultado.stderr
        self.assertIn("no figura en git worktree list", salida)
        self.assertIn("SALIDA:", salida)
        self.assertFalse(self.destino_documental.exists())

    def test_el_worktree_registrado_de_siempre_sigue_mandando(self):
        # Con worktree vivo no se crea ni se borra nada, y el recibo lo dice.
        self.instalar_grabador()

        resultado = self.ejecutar(rol="revisor", unidad=self.unidad)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.registro_grabado()["branch"], self.unidad)
        self.assertTrue(self.worktree.is_dir())
        recibos = sorted((self.ws / ".runtime/ejecuciones").glob(f"{self.unidad}-*.json"))
        recibo = json.loads(recibos[0].read_text(encoding="utf-8"))
        self.assertFalse(recibo["worktree_efimero"])
        self.assertEqual(recibo["worktree_origen"], "worktree")

    def test_una_documental_no_pisa_un_directorio_que_ya_existe(self):
        self.crear_unidad_documental()
        self.destino_documental.mkdir(parents=True)
        (self.destino_documental / "algo.txt").write_text("no me pises\n", encoding="utf-8")

        resultado = self.ejecutar(rol="revisor", unidad=self.UNIDAD)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("SALIDA:", resultado.stdout + resultado.stderr)
        self.assertTrue((self.destino_documental / "algo.txt").is_file())


# --- Bug 077: el lanzador interrumpido tiene que limpiar lo que dejó -----------------


@unittest.skipIf(os.name == "nt", "señales POSIX: en Windows lo cubre R3 (taskkill) y `desbloquear`")
class LanzadorInterrumpidoTest(ControlPlaneE2ETest):
    """Ctrl-C, `kill` o terminal cerrada a mitad de un lanzamiento.

    Bug 077 (Fernando, Windows 11 · Manuel, macOS): al interrumpir, el lanzador dejaba
    el harness hijo VIVO reteniendo los leases de la unidad y la ficha en 0444. R1 exige
    el orden matar-hijo → soltar-leases → devolver-la-ficha, salida != 0 y un checkpoint
    `interrumpido` en el recibo; R2, que lo que quede tras un `kill -9` se detecte y se
    recupere por comando sin robarle nunca el lease a un dueño vivo.
    """

    def doble_que_no_se_muere_solo(self, nombre="claude"):
        """Hijo que IGNORA SIGTERM (R4) y anota su PID donde el test lo ve.

        Ignorar SIGTERM es el caso real que importa: un harness ocupado no atiende la
        señal amable, así que el lanzador tiene que escalar. El PID se escribe en el
        worktree porque el entorno del hijo es una allowlist (no cruza ninguna variable
        del test) y su TMPDIR lo borra el propio lanzador al salir.
        """
        cuerpo = """import json, pathlib, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGHUP, signal.SIG_IGN)
pathlib.Path('.hijo-vivo.json').write_text(
    json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp()}), encoding='utf-8')
time.sleep(120)
"""
        self.instalar_doble(nombre, cuerpo)

    def lanzador_con_hijo_vivo(self, env=None):
        """Arranca el lanzador de verdad y espera a que el harness hijo esté corriendo."""
        proceso = subprocess.Popen(
            self.argumentos(), cwd=self.main, env=env or self.env, text=True,
            encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.addCleanup(self.rematar, proceso)
        rastro = self.worktree / ".hijo-vivo.json"
        limite = time.monotonic() + 20
        while not rastro.exists():
            self.assertIsNone(proceso.poll(), self.salida_de(proceso))
            self.assertLess(time.monotonic(), limite, "el harness hijo no llegó a arrancar")
            time.sleep(0.02)
        hijo = json.loads(rastro.read_text(encoding="utf-8"))
        self.addCleanup(self.rematar_pid, hijo["pid"])
        return proceso, hijo

    def salida_de(self, proceso):
        try:
            salida, error = proceso.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            return "(el lanzador sigue vivo)"
        return salida + error

    def rematar(self, proceso):
        if proceso.poll() is None:
            proceso.kill()
            proceso.wait(timeout=10)

    def rematar_pid(self, pid):
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)

    def vivo(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def esperar_muerto(self, pid, tope=15):
        limite = time.monotonic() + tope
        while self.vivo(pid):
            if time.monotonic() >= limite:
                return False
            time.sleep(0.05)
        return True

    def leases_activos(self):
        return sorted((self.ws / ".runtime/leases/active").glob("*.json"))

    def recibo_unico(self):
        recibos = sorted((self.ws / ".runtime/ejecuciones").glob(f"{self.unidad}-*.json"))
        self.assertEqual(len(recibos), 1, recibos)
        return json.loads(recibos[0].read_text(encoding="utf-8"))

    @property
    def ficha(self):
        return self.ws / "docs/05-trabajo" / self.unidad / "especificacion.md"

    def test_sigterm_mata_al_hijo_suelta_los_leases_y_devuelve_la_ficha(self):
        # EL BUG: hoy el lanzador muere y deja detrás hijo + leases + ficha en 0444.
        self.doble_que_no_se_muere_solo()
        proceso, hijo = self.lanzador_con_hijo_vivo()
        self.assertEqual(stat.S_IMODE(self.ficha.stat().st_mode), 0o444,
                         "precondición: la ficha está congelada mientras corre el harness")

        os.kill(proceso.pid, signal.SIGTERM)
        salida, error = proceso.communicate(timeout=30)

        traza = salida + error
        self.assertNotEqual(proceso.returncode, 0, f"R1: salida != 0 · {traza}")
        self.assertTrue(self.esperar_muerto(hijo["pid"]),
                        f"R1: el harness hijo (PID {hijo['pid']}) sobrevivió al lanzador · {traza}")
        self.assertEqual(self.leases_activos(), [],
                         f"R1: los leases de la unidad quedaron retenidos · {traza}")
        self.assertTrue(os.access(self.ficha, os.W_OK),
                        f"R1: la ficha quedó en solo lectura · "
                        f"{oct(stat.S_IMODE(self.ficha.stat().st_mode))}")
        recibo = self.recibo_unico()
        self.assertIn("interrumpido", [item["nombre"] for item in recibo["checkpoints"]],
                      f"R1: el recibo no acredita la interrupción · {recibo['checkpoints']}")

    def test_ctrl_c_limpia_igual_que_sigterm(self):
        # Caso límite del reporte de campo: Ctrl-C es SIGINT, no SIGTERM.
        self.doble_que_no_se_muere_solo()
        proceso, hijo = self.lanzador_con_hijo_vivo()

        os.kill(proceso.pid, signal.SIGINT)
        salida, error = proceso.communicate(timeout=30)

        self.assertNotEqual(proceso.returncode, 0, salida + error)
        self.assertTrue(self.esperar_muerto(hijo["pid"]), "SIGINT dejó al hijo vivo")
        self.assertEqual(self.leases_activos(), [])
        self.assertTrue(os.access(self.ficha, os.W_OK))
        # Sin el arreglo, el Ctrl-C salía por KeyboardInterrupt: la pila SÍ se desenrollaba
        # (por eso los leases y la ficha se salvaban por casualidad) pero el recibo se
        # quedaba mudo — un traceback en la terminal y un recibo que parecía a medio hacer,
        # sin decir en ningún sitio que aquello lo había parado una persona.
        recibo = self.recibo_unico()
        self.assertEqual(recibo["resultado"], "interrumpido",
                         f"el recibo no acredita la interrupción · {recibo}")
        self.assertIn("interrumpido", [item["nombre"] for item in recibo["checkpoints"]])

    def test_padre_muerto_a_lo_bruto_deja_huerfano_y_el_siguiente_lanzar_lo_dice(self):
        # R2: `kill -9` no admite manejador; lo que queda lo tiene que ver el siguiente.
        self.doble_que_no_se_muere_solo()
        proceso, hijo = self.lanzador_con_hijo_vivo()
        os.kill(proceso.pid, signal.SIGKILL)
        proceso.wait(timeout=10)
        self.crear_doble_harness("claude")   # el siguiente lanzamiento sería uno normal

        segundo = self.ejecutar(env={**self.env, "IR_SESSION_ID": "ejecucion-b"})

        traza = segundo.stdout + segundo.stderr
        self.assertNotEqual(segundo.returncode, 0, traza)
        self.assertIn("desbloquear", traza,
                      f"R2: no dice CÓMO salir del lease huérfano · {traza}")
        self.assertIn(self.unidad, traza)

    def test_desbloquear_retira_el_huerfano_mata_al_hijo_y_devuelve_la_ficha(self):
        # R2: el comando de recuperación deja la unidad lanzable otra vez.
        self.doble_que_no_se_muere_solo()
        proceso, hijo = self.lanzador_con_hijo_vivo()
        os.kill(proceso.pid, signal.SIGKILL)
        proceso.wait(timeout=10)

        recuperacion = subprocess.run(
            [sys.executable, str(self.launcher.with_name("lease.py")), "desbloquear",
             self.unidad, "--workspace", str(self.ws)],
            cwd=self.main, env=self.env, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )

        traza = recuperacion.stdout + recuperacion.stderr
        self.assertEqual(recuperacion.returncode, 0, traza)
        self.assertTrue(self.esperar_muerto(hijo["pid"]), f"el hijo huérfano sigue vivo · {traza}")
        self.assertEqual(self.leases_activos(), [], traza)
        self.assertTrue(os.access(self.ficha, os.W_OK), traza)
        self.crear_doble_harness("claude")
        tercero = self.ejecutar(env={**self.env, "IR_SESSION_ID": "ejecucion-c"})
        self.assertEqual(tercero.returncode, 0, tercero.stdout + tercero.stderr)

    def test_desbloquear_no_le_roba_el_lease_a_un_dueno_vivo(self):
        # P-20260818-3ad156c4: la recuperación jamás desaloja a un lanzador que sigue ahí.
        self.doble_que_no_se_muere_solo()
        proceso, hijo = self.lanzador_con_hijo_vivo()

        recuperacion = subprocess.run(
            [sys.executable, str(self.launcher.with_name("lease.py")), "desbloquear",
             self.unidad, "--workspace", str(self.ws)],
            cwd=self.main, env=self.env, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )

        traza = recuperacion.stdout + recuperacion.stderr
        self.assertNotEqual(recuperacion.returncode, 0, traza)
        self.assertIn("vivo", traza.lower())
        self.assertNotEqual(self.leases_activos(), [], "le robó el lease a un dueño vivo")
        self.assertTrue(self.vivo(hijo["pid"]), "mató al hijo de un lanzador vivo")


# ============================================ Unidad 108 · R1/R2 · el recibo de Claude ACREDITA
#
# Hasta la 108 el recibo del harness Claude solo podía DECLARAR el modelo de la tabla: la
# regla 10 quedaba en promesa escrita justo en el harness que más se usa. La 100 resolvió lo
# mismo para Codex leyendo el rollout de la sesión; aquí la fuente equivalente es el
# transcript de Claude Code (`~/.claude/projects/<slug del cwd>/<session_id>.jsonl`), cuyos
# registros `assistant` traen `message.model` y el `effort` con el que corrió el turno.
#
# Los tests usan un HOME de fixture y un transcript SINTÉTICO escrito por el doble: jamás se
# leen transcripts reales del usuario.
CUERPO_TRANSCRIPT = """import json, pathlib
sid = argv[argv.index('--session-id') + 1] if '--session-id' in argv else None
pathlib.Path('.harness-record.json').write_text(
    json.dumps({'argv': argv, 'session_id': sid, 'cwd': os.getcwd()}), encoding='utf-8')
if sid and os.environ.get('HOME') and %s:
    slug = os.getcwd().replace(os.sep, '-')
    carpeta = pathlib.Path(os.environ['HOME']) / '.claude' / 'projects' / slug
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / (sid + '.jsonl')).write_text(
        json.dumps({'type': 'user', 'sessionId': sid,
                    'message': {'role': 'user', 'content': 'encargo'}}) + chr(10)
        + json.dumps({'type': 'assistant', 'sessionId': sid, 'effort': %s,
                      'message': {'role': 'assistant', 'model': %s}}) + chr(10),
        encoding='utf-8')
encontrado = re.search(r'CONTRATO: (.+)', prompt)
if encontrado:
    hallazgos = pathlib.Path(encontrado.group(1).strip()).parent / 'hallazgos.md'
    with open(hallazgos, 'a', encoding='utf-8') as fh:
        fh.write('\\n- [x] trabajo marcado por el doble de transcript\\n')
"""


class AcreditacionDeClaudeTest(ControlPlaneE2ETest):
    """El doble de `claude` deja un transcript sintético como el del CLI real.

    El doble se instala DENTRO de cada test (patrón de `RondasDeCorreccionTest`): así el
    `setUp` de la base sigue valiendo y los tests heredados no corren con un doble que no
    es el suyo.
    """

    MODELO_REAL = "claude-el-que-de-verdad-corrio"
    ESFUERZO_REAL = "xhigh"

    def doble_con_transcript(self, escribe=True):
        self.instalar_doble("claude", CUERPO_TRANSCRIPT % (
            "True" if escribe else "False",
            repr(self.ESFUERZO_REAL), repr(self.MODELO_REAL)))

    def recibo(self):
        recibos = sorted((self.ws / ".runtime/ejecuciones").glob(f"{self.unidad}-*.json"))
        self.assertEqual(len(recibos), 1, f"se esperaba un único recibo: {recibos}")
        return json.loads(recibos[0].read_text(encoding="utf-8"))

    def registro(self):
        return json.loads(
            (self.worktree / ".harness-record.json").read_text(encoding="utf-8"))

    def test_claude_corre_con_id_de_sesion_propio_y_persistiendo_el_transcript(self):
        # Simétrico a `--ephemeral` en Codex (unidad 100): `--no-session-persistence` es
        # justo lo que impide que se escriba el transcript, y el transcript es el ÚNICO
        # sitio donde Claude dice con qué modelo corrió de verdad.
        self.doble_con_transcript()

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        argv = self.registro()["argv"]
        self.assertNotIn("--no-session-persistence", argv)
        self.assertIn("--session-id", argv)
        uuid.UUID(argv[argv.index("--session-id") + 1])  # el CLI exige un UUID válido

    def test_el_recibo_acredita_el_modelo_que_de_verdad_corrio(self):
        self.doble_con_transcript()

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertEqual(recibo["model_slug"], self.MODELO_REAL)
        self.assertEqual(recibo["modelo"], self.MODELO_REAL)
        self.assertEqual(recibo["esfuerzo"], self.ESFUERZO_REAL)
        self.assertEqual(recibo["modelo_origen"], "harness-acreditado")
        # Lo PEDIDO se conserva: sale de la tabla, no del transcript.
        self.assertIsNotNone(recibo["requested_model"])
        self.assertNotEqual(recibo["requested_model"], self.MODELO_REAL)
        checkpoints = {c["nombre"]: c for c in recibo["checkpoints"]}
        self.assertIn("modelo-acreditado", checkpoints)
        self.assertEqual(checkpoints["modelo-acreditado"]["estado"], "ok")
        self.assertIn("transcript", checkpoints["modelo-acreditado"]["detalle"])
        self.assertIn(self.MODELO_REAL, checkpoints["modelo-acreditado"]["detalle"])

    def test_sin_transcript_el_recibo_declara_y_lo_dice(self):
        # R2 · el límite: nunca se inventa. Sin transcript, el recibo sigue DECLARANDO.
        self.doble_con_transcript(escribe=False)

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertIsNone(recibo["model_slug"])
        self.assertEqual(recibo["modelo_origen"], "tabla")
        self.assertEqual(recibo["modelo"], recibo["requested_model"])
        checkpoints = {c["nombre"]: c for c in recibo["checkpoints"]}
        self.assertIn("modelo-acreditado", checkpoints)
        self.assertEqual(checkpoints["modelo-acreditado"]["estado"], "warn")


class AcreditarClaudeDirectoTest(unittest.TestCase):
    """La lectura del transcript, sin lanzador de por medio: la regla del slug y los
    límites (transcript ausente, sin modelo, ilegible) no deben levantar jamás."""

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="acreditar-claude-")
        self.addCleanup(self.temporal.cleanup)
        self.home = Path(self.temporal.name) / "home"
        self.worktree = Path(self.temporal.name) / "ws" / "worktrees" / "001-demo"
        self.worktree.mkdir(parents=True)
        self.sesion = "11111111-2222-3333-4444-555555555555"

    def transcript(self, carpeta, lineas):
        destino = self.home / ".claude" / "projects" / carpeta
        destino.mkdir(parents=True, exist_ok=True)
        (destino / f"{self.sesion}.jsonl").write_text(
            "".join(json.dumps(l) + "\n" for l in lineas), encoding="utf-8")

    def test_el_slug_del_proyecto_es_el_cwd_con_las_barras_en_guiones(self):
        self.transcript(
            str(self.worktree).replace(os.sep, "-"),
            [{"type": "assistant", "effort": "high",
              "message": {"role": "assistant", "model": "claude-de-verdad"}}])

        self.assertEqual(
            ejecucion.acreditar_claude(self.home, self.worktree, self.sesion),
            ("claude-de-verdad", "high"))

    def test_manda_el_ultimo_mensaje_del_asistente(self):
        self.transcript(
            str(self.worktree).replace(os.sep, "-"),
            [{"type": "assistant", "effort": "low",
              "message": {"role": "assistant", "model": "primero"}},
             {"type": "user", "message": {"role": "user", "content": "sigue"}},
             {"type": "assistant", "effort": "max",
              "message": {"role": "assistant", "model": "ultimo"}}])

        self.assertEqual(
            ejecucion.acreditar_claude(self.home, self.worktree, self.sesion),
            ("ultimo", "max"))

    def test_sin_transcript_no_acredita_y_no_levanta(self):
        self.assertEqual(
            ejecucion.acreditar_claude(self.home, self.worktree, self.sesion),
            (None, None))

    def test_un_transcript_sin_modelo_no_acredita(self):
        self.transcript(
            str(self.worktree).replace(os.sep, "-"),
            [{"type": "user", "message": {"role": "user", "content": "hola"}},
             {"type": "system", "subtype": "init"}])

        self.assertEqual(
            ejecucion.acreditar_claude(self.home, self.worktree, self.sesion),
            (None, None))

    def test_una_linea_rota_no_tumba_la_lectura(self):
        carpeta = self.home / ".claude" / "projects" / str(self.worktree).replace(os.sep, "-")
        carpeta.mkdir(parents=True)
        (carpeta / f"{self.sesion}.jsonl").write_text(
            "{esto no es json\n"
            + json.dumps({"type": "assistant", "effort": "medium",
                          "message": {"role": "assistant", "model": "sobrevive"}}) + "\n",
            encoding="utf-8")

        self.assertEqual(
            ejecucion.acreditar_claude(self.home, self.worktree, self.sesion),
            ("sobrevive", "medium"))

    def test_si_el_slug_no_casa_se_busca_la_sesion_por_su_id(self):
        # macOS resuelve /var → /private/var y el slug deja de casar; el id de sesión es
        # único, así que el transcript se encuentra igual en vez de perder la acreditación.
        self.transcript("-otro-camino-al-mismo-sitio",
                        [{"type": "assistant", "effort": "high",
                          "message": {"role": "assistant", "model": "encontrado"}}])

        self.assertEqual(
            ejecucion.acreditar_claude(self.home, self.worktree, self.sesion),
            ("encontrado", "high"))


if __name__ == "__main__":
    unittest.main()
