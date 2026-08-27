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


class EnlacesDePruebaTest(unittest.TestCase):
    def test_symlink_permitido_se_conserva(self):
        enlace, destino = Path("enlace"), Path("destino")
        with mock.patch.object(Path, "symlink_to") as crear:
            self.assertEqual(
                ayuda_windows.enlazar_o_saltar(self, enlace, destino), enlace)
        crear.assert_called_once_with(destino, target_is_directory=False)

    def test_posix_usa_symlink_real_de_directorio(self):
        enlace, destino = Path("alias"), Path("destino")
        with mock.patch.object(ayuda_windows.os, "name", "posix"), mock.patch.object(
            Path, "symlink_to"
        ) as crear:
            self.assertEqual(ayuda_windows.enlazar_directorio(enlace, destino), enlace)
        crear.assert_called_once_with(destino, target_is_directory=True)

    def test_symlink_con_ruta_erronea_no_se_omite(self):
        with mock.patch.object(Path, "symlink_to", side_effect=FileNotFoundError("ruta mala")):
            with self.assertRaises(FileNotFoundError):
                ayuda_windows.enlazar_o_saltar(self, Path("enlace"), Path("destino"))

    def test_symlink_con_error_ajeno_no_se_omite(self):
        with mock.patch.object(Path, "symlink_to", side_effect=PermissionError("otro permiso")):
            with self.assertRaisesRegex(PermissionError, "otro permiso"):
                ayuda_windows.enlazar_o_saltar(self, Path("enlace"), Path("destino"))

    def test_junction_fallido_es_error_y_auxiliar_windows_oculto(self):
        fallo = subprocess.CompletedProcess([], 1, "", "fallo sintético")
        enlace, destino = Path("alias"), Path("destino")
        with mock.patch.object(ayuda_windows.os, "name", "nt"), mock.patch.object(
            ayuda_windows.subprocess, "run", return_value=fallo
        ) as ejecutar:
            with self.assertRaisesRegex(OSError, "fallo sintético"):
                ayuda_windows.enlazar_directorio(enlace, destino)
        self.assertEqual(ejecutar.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)



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
            ayuda_windows.enlazar_directorio(alias, real_dir)
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
            ayuda_windows.enlazar_directorio(alias, base / "runneradmin")
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




# --- Bug 077: el lanzador interrumpido tiene que limpiar lo que dejó -----------------




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


class VariablesDeWindowsEnLaAllowlistTest(unittest.TestCase):
    """ADR-039 · el detector de regresión que la propia decisión pide por escrito.

    La unidad 165 (delegación nativa) se llevó por delante el E2E del launcher externo
    que antes cubría esto: aquel test lanzaba un harness doble como proceso aparte, y
    ese proceso ya no existe. Lo que SÍ sigue existiendo es la allowlist `HEREDAR_ENV`
    y `entorno_base()`, que la lee. ADR-039 dice literalmente que si una actualización
    ve desaparecer las variables de Windows de `HEREDAR_ENV`, eso es la regresión y no
    el arreglo — así que la garantía se vigila donde vive, sin resucitar 1800 líneas de
    tests de una máquina que ya no se lanza.

    Alcance honesto: esto comprueba el FILTRO, no que winsock resuelva DNS. Lo segundo
    lo acredita una máquina Windows real, no esta suite.
    """

    # Las variables sin las que un ejecutable nativo de Windows ni carga sus DLL
    # (0xC0000409) ni resuelve nombres (socket 11003) ni encuentra su configuración.
    VARIABLES_DE_WINDOWS = (
        "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
    )

    # El envenenamiento que la allowlist existe para dejar fuera: si alguna de estas
    # entrara, el aislamiento del entorno limpio dejaría de valer nada.
    VARIABLES_ENVENENADAS = (
        "BASH_ENV", "ENV", "ZDOTDIR", "CDPATH", "PYTHONPATH", "NODE_OPTIONS",
    )

    def test_la_allowlist_conserva_las_variables_de_sistema_de_windows(self):
        for variable in self.VARIABLES_DE_WINDOWS:
            self.assertIn(
                variable, ejecucion.HEREDAR_ENV,
                f"ADR-039: {variable} ha desaparecido de HEREDAR_ENV. Eso es la "
                f"regresion, no el arreglo: sin ella Windows nativo se queda sin "
                f"salida. Ver decisiones/039-el-entorno-limpio-tambien-tiene-que-"
                f"serlo-en-windows.md",
            )

    def test_la_allowlist_sigue_dejando_fuera_el_entorno_envenenado(self):
        # ADR-039 § Limites: esto no relaja lo que el launcher aisla.
        for variable in self.VARIABLES_ENVENENADAS:
            self.assertNotIn(
                variable, ejecucion.HEREDAR_ENV,
                f"{variable} no puede colarse en la allowlist: el entorno limpio deja "
                f"de serlo.",
            )

    def test_entorno_base_simulando_windows_conserva_esas_variables(self):
        # El mecanismo, no solo la lista: `entorno_base()` filtra POR la allowlist, asi
        # que lo que no este en ella no llega al hijo, corra donde corra.
        entorno_windows = {
            "PATH": r"C:\Windows\system32;C:\Program Files\Git\cmd",
            "SYSTEMROOT": r"C:\Windows",
            "SYSTEMDRIVE": "C:",
            "WINDIR": r"C:\Windows",
            "COMSPEC": r"C:\Windows\system32\cmd.exe",
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "USERPROFILE": r"C:\Users\alumno",
            "APPDATA": r"C:\Users\alumno\AppData\Roaming",
            "LOCALAPPDATA": r"C:\Users\alumno\AppData\Local",
            "PROGRAMDATA": r"C:\ProgramData",
            "NUMBER_OF_PROCESSORS": "8",
            "PROCESSOR_ARCHITECTURE": "AMD64",
            "OS": "Windows_NT",
            # Y una envenenada, para que el filtro se vea trabajando en el mismo test.
            "NODE_OPTIONS": "--require /tmp/malo.js",
        }
        with tempfile.TemporaryDirectory(prefix="adr039-") as tmp:
            base = Path(tmp)
            worktree = base / "worktree"
            worktree.mkdir()
            with mock.patch.object(ejecucion.os, "environ", entorno_windows):
                limpio = ejecucion.entorno_base(worktree, base / "tmp", base / "home")

        for variable in self.VARIABLES_DE_WINDOWS:
            self.assertEqual(
                limpio.get(variable), entorno_windows[variable],
                f"ADR-039: entorno_base() descarta {variable} — la allowlist se "
                f"escribio para POSIX y nunca se reviso contra Windows.",
            )
        self.assertNotIn("NODE_OPTIONS", limpio)


if __name__ == "__main__":
    unittest.main()
