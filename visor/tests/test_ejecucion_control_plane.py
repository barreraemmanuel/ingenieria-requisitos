import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
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
        shutil.copy2(LAUNCHER.with_name("lease.py"), scripts / "lease.py")
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

    def crear_doble_harness(self, nombre):
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
        self.instalar_doble(nombre, cuerpo)

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

    def ejecutar(self, harness="claude", rol="constructor", skills=(), prompt="Haz la tarea",
                 unidad=None, env=None):
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
        self.assertIn("--ignore-user-config", harness["argv"])
        self.assertIn("--ignore-rules", harness["argv"])
        self.assertIn("--ephemeral", harness["argv"])
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
        self.assertEqual(
            [item["nombre"] for item in recibo["checkpoints"]],
            ["lease", "identidad", "harness"],
        )
        self.assertTrue(all(item["estado"] == "ok" for item in recibo["checkpoints"]))
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
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
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
        self.assertEqual(nuevo.returncode, 0, nuevo.stdout + nuevo.stderr)
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

    def test_lanzar_acepta_modelo_explicito(self):
        argv = self.argumentos()
        argv[argv.index("--rol"):argv.index("--rol")] = ["--modelo", "claude-opus-5"]
        resultado = subprocess.run(
            argv, cwd=self.main, env=self.env, text=True,
            encoding="utf-8", errors="replace", capture_output=True
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        harness = self.registros()
        registrado = harness["argv"]
        self.assertIn("--model", registrado)
        self.assertEqual(registrado[registrado.index("--model") + 1], "claude-opus-5")

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


if __name__ == "__main__":
    unittest.main()
