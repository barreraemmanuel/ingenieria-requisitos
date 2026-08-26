"""Escenarios de campo: cada test reproduce una queja real de usuarios (agosto 2026)
y demuestra que ya no ocurre. La numeración es estable para poder citarlos.

Familias y origen:
  01-07  «los subagentes se quedan esperando una aprobación que no llega» (Discord, 06-08)
  08-14  Modo D: migración que se salta pasos, contamina el repo o revierte en falso
         y consumo desbocado (Discord, 08-08 y 10-08)
  15-18  brownfield: la adopción se saltaba entera (Discord, 08-08)
  19-22  publicar/arrancar bloqueado por un rojo del propio método (Discord, 08-08)
  23-25  «el agente decidió parar los tests porque sí, sin avisar» (Discord, 07-08)

Doctrina que estos escenarios vigilan: ADR-026 (guiar, no bloquear; gate duro solo ante
daño irreversible, siempre con salida nombrada).
"""
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(RAIZ / "visor") not in sys.path:
    # finalizar.py hace `import revision` a pelo cuando no corre como paquete.
    sys.path.insert(0, str(RAIZ / "visor"))
import test_peticion_bootstrap_actualizar as mod_modo_d  # noqa: E402
import test_peticion_unidad as mod_unidad  # noqa: E402
import test_version_metodo as mod_version  # noqa: E402


def cargar_modulo(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class Escenario(unittest.TestCase):
    """Base: presta los fixtures de las suites existentes sin re-ejecutar sus tests."""

    def fixture(self, clase):
        caso = clase(methodName="setUp")
        caso.setUp()
        self.addCleanup(caso.doCleanups)
        return caso


class EscenariosCuelgues(Escenario):
    """Diego (06-08): subagentes parados ~10 min «esperando una aprobación que no llega».
    Causa raíz: procesos hijos con stdin heredado y sin tope, y candados sin límite."""

    def test_escenario_01_hook_colgado_no_retiene_el_despacho_para_siempre(self):
        fx = self.fixture(mod_unidad.PeticionUnidadTest)
        nombre = fx.preparar_feature_aprobada("hook-colgado")
        hook = fx.ws / "worktree-listo"
        hook.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
        hook.chmod(0o755)

        with mock.patch.dict(os.environ, {"IR_TOPE_HOOK_SEGUNDOS": "2"}):
            inicio = time.monotonic()
            resultado = fx.ejecutar(fx.unidad, "despachar", nombre)
            duracion = time.monotonic() - inicio

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("tope", (resultado.stdout + resultado.stderr).lower())
        self.assertLess(duracion, 30, "el despacho no puede quedarse colgado")
        self.assertFalse((fx.ws / "worktrees" / nombre).exists())
        # Los leases quedaron libres: reintentar no choca contra la sesión muerta.
        with mock.patch.dict(os.environ, {"IR_TOPE_HOOK_SEGUNDOS": "2"}):
            reintento = fx.ejecutar(fx.unidad, "despachar", nombre)
        self.assertNotIn("propietario", reintento.stdout + reintento.stderr)

    def test_escenario_02_hook_que_espera_stdin_falla_en_vez_de_colgar(self):
        fx = self.fixture(mod_unidad.PeticionUnidadTest)
        nombre = fx.preparar_feature_aprobada("hook-stdin")
        hook = fx.ws / "worktree-listo"
        hook.write_text("#!/bin/sh\nread respuesta || exit 7\n", encoding="utf-8")
        hook.chmod(0o755)

        inicio = time.monotonic()
        resultado = fx.ejecutar(fx.unidad, "despachar", nombre)
        duracion = time.monotonic() - inicio

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertLess(duracion, 30, "un hook que pregunta debe fallar, no esperar")
        self.assertIn("bloqueada", (resultado.stdout + resultado.stderr).lower())

    def test_escenario_03_caja_negra_enviar_sin_terminal_no_cuelga(self):
        ws = Path(tempfile.mkdtemp(prefix="escenario-caja-"))
        self.addCleanup(shutil.rmtree, ws, True)
        registrado = subprocess.run(
            [sys.executable, str(SCRIPTS / "caja_negra.py"), "registrar", "--repo",
             str(ws), "--fase", "test", "--sintoma", "algo raro", "--esperado", "x",
             "--actual", "y"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(registrado.returncode, 0,
                         registrado.stdout + registrado.stderr)

        # stdin es un PIPE abierto y mudo: antes, input() esperaba para siempre.
        proceso = subprocess.Popen(
            [sys.executable, str(SCRIPTS / "caja_negra.py"), "enviar", "--repo", str(ws)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        salida, _ = proceso.communicate(timeout=30)

        self.assertEqual(proceso.returncode, 0, salida)
        self.assertIn("Sin terminal interactiva", salida)
        self.assertIn("--si", salida)

    @unittest.skipUnless(os.name == "posix", "flock es POSIX")
    def test_escenario_04_candado_de_leases_ocupado_termina_en_leasebusy(self):
        ws = Path(tempfile.mkdtemp(prefix="escenario-lease-"))
        self.addCleanup(shutil.rmtree, ws, True)
        with mock.patch.dict(os.environ, {"IR_TOPE_COORDINADOR_SEGUNDOS": "1"}):
            lease = cargar_modulo("lease_escenario", SCRIPTS / "lease.py")
        candado = ws / ".runtime/leases/coordinator.lock"
        candado.parent.mkdir(parents=True)
        ocupante = subprocess.Popen(
            [sys.executable, "-c",
             "import fcntl, sys, time\n"
             f"d = open({str(candado)!r}, 'w')\n"
             "fcntl.flock(d, fcntl.LOCK_EX)\n"
             "print('tomado', flush=True)\n"
             "time.sleep(60)\n"],
            stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        )

        def soltar_ocupante():
            ocupante.kill()
            ocupante.stdout.close()
            ocupante.wait(timeout=10)

        self.addCleanup(soltar_ocupante)
        self.assertIn("tomado", ocupante.stdout.readline())

        inicio = time.monotonic()
        with self.assertRaises(lease.LeaseBusy):
            with lease.LeaseManager(ws).acquire("unit:001-x"):
                pass
        self.assertLess(time.monotonic() - inicio, 30,
                        "esperar a un candado huérfano tiene tope, no es infinito")

    def test_escenario_05_setup_no_hereda_stdin_ni_deja_a_git_preguntar(self):
        setup = cargar_modulo("setup_escenario", RAIZ / "plantilla/setup.py")
        sonda = setup.ejecutar(
            sys.executable, "-c",
            "import os, sys; print(os.environ.get('GIT_TERMINAL_PROMPT'));"
            "print(repr(sys.stdin.read()))",
        )
        self.assertEqual(sonda.returncode, 0, sonda.stdout)
        lineas = sonda.stdout.strip().splitlines()
        self.assertEqual(lineas[0], "0", "git no puede preguntar por terminal")
        self.assertEqual(lineas[1], "''", "el stdin de los hijos va cerrado")

    def test_escenario_06_el_launcher_acepta_tope_explicito(self):
        ayuda = subprocess.run(
            [sys.executable, str(SCRIPTS / "ejecucion.py"), "lanzar", "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertEqual(ayuda.returncode, 0, ayuda.stdout + ayuda.stderr)
        self.assertIn("--tope-minutos", ayuda.stdout)

    def test_escenario_07_el_despacho_guia_al_subagente_del_padre(self):
        # Hasta la 1.8.1 el despacho guiaba a lanzar `ejecucion.py` en SEGUNDO PLANO y a
        # seguir su recibo: era un `claude -p` aparte. Bug 084 / ADR-033: el constructor es un
        # subagente del padre; la guía es dónde escribe, con qué modelo y cómo se le vigila.
        fx = self.fixture(mod_unidad.PeticionUnidadTest)
        nombre = fx.preparar_feature_aprobada("guia-fondo")

        resultado = fx.ejecutar(fx.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("SUBAGENTE DEL PADRE", resultado.stdout)
        self.assertIn("hallazgos.md", resultado.stdout)
        self.assertIn("5 min", resultado.stdout)
        self.assertNotIn("SEGUNDO PLANO", resultado.stdout)


class EscenariosModoD(Escenario):
    """D_vega y Lenox (08-08): la migración revierte en falso, se bloquea sola o
    contamina el repo; y el arreglo no puede absorber trabajo del usuario."""

    def test_escenario_08_migracion_no_revierte_por_rojo_heredado(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        ws = fx.workspace_antiguo()
        fx.plantar_fail_estable(ws)
        fx.commitear(ws, "defecto que ya estaba antes de migrar")

        resultado = fx.ejecutar(mod_version.ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ya estaban antes de actualizar", resultado.stdout)
        self.assertNotIn("REVERTIDA", resultado.stdout)

    def test_escenario_09_linter_viejo_permisivo_no_fabrica_fallos_nuevos(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        ws = fx.workspace_antiguo()
        primera = fx.ejecutar(mod_version.ACTUALIZAR, "aplicar", str(ws))
        self.assertEqual(primera.returncode, 0, primera.stdout + primera.stderr)
        fx.plantar_fail_estable(ws)
        (ws / "docs/00-metodo/scripts/lint_metodo.py").write_text(
            "import sys\nsys.exit(0)\n", encoding="utf-8")
        fx.commitear(ws, "linter permisivo y defecto preexistente")

        resultado = fx.ejecutar(mod_version.ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ya estaban antes de actualizar", resultado.stdout)

    def test_escenario_10_rojo_causado_por_el_update_si_revierte(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        copia = fx.herramienta_doctorada()
        ws = fx.workspace_antiguo()

        resultado = fx.ejecutar(copia / "visor/actualizar.py", "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("REVERTIDA", resultado.stdout)
        self.assertIn("MARCADOR_ROJO", resultado.stdout)

    def test_escenario_11_kill_entre_stage_y_commit_no_deja_bloqueo(self):
        fx = self.fixture(mod_modo_d.PeticionBootstrapActualizarTest)
        ws = fx.workspace_antiguo(con_trabajo=False)
        proceso, ready, gate = fx.proceso_actualizar_con_failpoint(
            "actualizar_despues_stage_exact", ws)
        fx.esperar_barrera(ready)
        proceso.kill()
        proceso.wait(timeout=10)

        # La siguiente ejecución debe recuperarse sola: ni «índice sucio», ni journal
        # colgado, ni diagnóstico falso. Y terminar de aplicar el método.
        resultado = fx.ejecutar(mod_modo_d.ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("Recuperé", resultado.stdout)
        self.assertNotIn("sucio", resultado.stdout)
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ws,
                                text=True, encoding="utf-8", errors="replace",
                                capture_output=True, check=True).stdout
        self.assertEqual(staged.strip(), "", "el índice queda limpio tras recuperar")

    def test_escenario_12_git_add_ajeno_a_mitad_no_se_absorbe(self):
        fx = self.fixture(mod_modo_d.PeticionBootstrapActualizarTest)
        ws = fx.workspace_antiguo(con_trabajo=False)
        proceso, ready, gate = fx.proceso_actualizar_con_failpoint(
            "actualizar_antes_stage_final", ws)
        fx.esperar_barrera(ready)
        (ws / "mi-trabajo.md").write_text("borrador del usuario\n", encoding="utf-8")
        subprocess.run(["git", "add", "mi-trabajo.md"], cwd=ws, check=True)
        fx.abrir_barrera(gate)
        salida, error = proceso.communicate(timeout=60)

        self.assertEqual(proceso.returncode, 1, salida + error)
        self.assertIn("REVERTIDA", salida)
        self.assertIn("mi-trabajo.md", salida)
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ws,
                                text=True, encoding="utf-8", errors="replace",
                                capture_output=True, check=True).stdout
        self.assertEqual(staged.strip(), "mi-trabajo.md",
                         "el add del usuario sigue exactamente donde él lo dejó")

    def test_escenario_13_gitignore_del_usuario_se_conserva(self):
        fx = self.fixture(mod_modo_d.PeticionBootstrapActualizarTest)
        ws = fx.workspace_antiguo(con_trabajo=False)
        (ws / ".gitignore").write_text("secreto-local/\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=ws, check=True)
        subprocess.run(["git", "commit", "-m", "ignora lo mío"], cwd=ws, check=True,
                       capture_output=True)
        (ws / "secreto-local").mkdir()
        (ws / "secreto-local/notas.txt").write_text("privado\n", encoding="utf-8")

        resultado = fx.ejecutar(mod_modo_d.ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        gitignore = (ws / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("secreto-local/", gitignore)
        self.assertIn("Modo D conserva esta sección", gitignore)
        estado = subprocess.run(["git", "status", "--porcelain=v1"], cwd=ws,
                                text=True, encoding="utf-8", errors="replace",
                                capture_output=True, check=True).stdout
        self.assertEqual(estado.strip(), "",
                         "lo que el usuario ignoraba sigue ignorado: árbol limpio")
        # Idempotente: una segunda pasada no ve nada que tocar en .gitignore.
        segunda = fx.ejecutar(mod_modo_d.ACTUALIZAR, "aplicar", str(ws))
        self.assertEqual(segunda.returncode, 0, segunda.stdout + segunda.stderr)
        self.assertNotIn(".gitignore", segunda.stdout)

    def test_escenario_14_los_docs_del_usuario_quedan_intactos(self):
        fx = self.fixture(mod_modo_d.PeticionBootstrapActualizarTest)
        ws = fx.workspace_antiguo(con_trabajo=False)
        propios = {
            "docs/01-constitucion/manifiesto.md": "# Mi manifiesto\ncontenido mío\n",
            "docs/02-flujos/mi-actividad.md": "# Actividad\npasos míos\n",
            "docs/decisiones/001-mi-decision.md": "# DP-001\nmi porqué\n",
            "docs/05-trabajo/ESTADO.md": "# ESTADO\n| 004 | mi-unidad | en_obra |\n",
        }
        for relativo, contenido in propios.items():
            destino = ws / relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(contenido, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
        subprocess.run(["git", "commit", "-m", "trabajo del usuario"], cwd=ws,
                       check=True, capture_output=True)

        resultado = fx.ejecutar(mod_modo_d.ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        for relativo, contenido in propios.items():
            self.assertEqual((ws / relativo).read_text(encoding="utf-8"), contenido,
                             f"{relativo} es del usuario: Modo D no lo toca")


class EscenariosBrownfield(Escenario):
    """D_vega (08-08): «se ha saltado totalmente el paso brownfield». La adopción
    era una puerta en prosa que nada ejecutaba y ninguna señal nombraba."""

    def bare_con_codigo(self, base):
        origen = base / "codigo-origen"
        origen.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=origen, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=origen, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=origen, check=True)
        (origen / "app.py").write_text("print('legado')\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=origen, check=True)
        subprocess.run(["git", "commit", "-m", "código legado"], cwd=origen,
                       check=True, capture_output=True)
        bare = base / "codigo.git"
        subprocess.run(["git", "clone", "--bare", str(origen), str(bare)], check=True,
                       capture_output=True)
        return bare

    def test_escenario_15_bootstrap_brownfield_pone_la_adopcion_primero(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        remoto = self.bare_con_codigo(fx.base)
        destino = fx.base / "legado-agents"

        resultado = fx.ejecutar(
            mod_version.BOOTSTRAP, "--planos", str(fx.planos_minimos()),
            "--destino", str(destino), "--remoto", str(remoto),
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        estado = (destino / "docs/05-trabajo/ESTADO.md").read_text(encoding="utf-8")
        self.assertIn("ADOPCIÓN", estado)
        self.assertIn("ADOPCION.md", estado)
        self.assertIn("la ADOPCIÓN", resultado.stdout)
        self.assertNotIn("Siguiente paso del método: fase 3", resultado.stdout)

    def test_escenario_16_bootstrap_greenfield_sigue_a_fase_3(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        destino = fx.base / "nuevo-agents"

        resultado = fx.ejecutar(
            mod_version.BOOTSTRAP, "--planos", str(fx.planos_minimos()),
            "--destino", str(destino),
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        estado = (destino / "docs/05-trabajo/ESTADO.md").read_text(encoding="utf-8")
        self.assertNotIn("ADOPCIÓN", estado)
        self.assertIn("Siguiente paso del método: fase 3", resultado.stdout)

    def test_escenario_17_despacho_sin_adopcion_avisa_pero_no_bloquea(self):
        fx = self.fixture(mod_unidad.PeticionUnidadTest)
        bias = fx.ws / "docs/01-constitucion/bias.md"
        bias.parent.mkdir(parents=True, exist_ok=True)
        bias.write_text("# Bias BROWNFIELD\nEl código ya existe.\n", encoding="utf-8")
        nombre = fx.preparar_feature_aprobada("sin-adopcion")

        resultado = fx.ejecutar(fx.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ADOPCIÓN", resultado.stdout + resultado.stderr)

    def test_escenario_18_despacho_con_adopcion_hecha_no_avisa(self):
        fx = self.fixture(mod_unidad.PeticionUnidadTest)
        bias = fx.ws / "docs/01-constitucion/bias.md"
        bias.parent.mkdir(parents=True, exist_ok=True)
        bias.write_text("# Bias BROWNFIELD\nEl código ya existe.\n", encoding="utf-8")
        adopcion = fx.ws / "docs/03-investigacion/ADOPCION.md"
        adopcion.parent.mkdir(parents=True, exist_ok=True)
        adopcion.write_text("# Adopción\ngap-map hecho\n", encoding="utf-8")
        nombre = fx.preparar_feature_aprobada("con-adopcion")

        resultado = fx.ejecutar(fx.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("ADOPCIÓN", resultado.stdout + resultado.stderr)


class EscenariosPublicacion(Escenario):
    """davidfox28 (08-08): un rojo que solo puede arreglarse «desde el método» dejaba
    al usuario sin salida; y el flujo de publicar absorbía o machacaba trabajo suyo."""

    def workspace_bootstrap(self, fx, nombre="demo-agents"):
        destino = fx.base / nombre
        resultado = fx.ejecutar(
            mod_version.BOOTSTRAP, "--planos", str(fx.planos_minimos()),
            "--destino", str(destino),
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return destino

    def test_escenario_19_setup_con_linter_rojo_no_bloquea_el_arranque(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        ws = self.workspace_bootstrap(fx)
        rota = ws / "docs/05-trabajo/001-demo"
        rota.mkdir(parents=True)
        (rota / "especificacion.md").write_text("sin frontmatter\n", encoding="utf-8")

        resultado = subprocess.run(
            [sys.executable, str(ws / "setup.py")], cwd=ws, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, timeout=300,
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ROJO", resultado.stdout)
        self.assertIn("caja_negra.py registrar", resultado.stdout)
        self.assertIn("Workspace listo", resultado.stdout)

    def test_escenario_20_el_workspace_nace_con_la_via_de_escape_escrita(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        ws = self.workspace_bootstrap(fx, "escape-agents")

        adr = ws / "docs/00-metodo/decisiones/026-guiar-no-bloquear.md"
        self.assertTrue(adr.is_file(), "el ADR-026 viaja con cada workspace")
        agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("ADR-026", agents)
        self.assertIn("NO te bloquea", agents)
        linter = subprocess.run(
            [sys.executable, str(ws / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=ws, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertEqual(linter.returncode, 0, linter.stdout + linter.stderr)

    def test_escenario_21_finalizar_no_machaca_estado_md(self):
        finalizar = cargar_modulo("finalizar_escenario", RAIZ / "visor/finalizar.py")
        ws = Path(tempfile.mkdtemp(prefix="escenario-estado-"))
        self.addCleanup(shutil.rmtree, ws, True)
        estado = ws / "docs/05-trabajo/ESTADO.md"
        estado.parent.mkdir(parents=True)
        vivo = "# ESTADO\n| 004 | mi-unidad | en_obra |\n- BLOQUEO: espera al proveedor\n"
        estado.write_text(vivo, encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()) as consola:
            rutas = finalizar.escribir_estado_congelado(ws)

        self.assertEqual(estado.read_text(encoding="utf-8"), vivo)
        self.assertNotIn("docs/05-trabajo/ESTADO.md", rutas)
        self.assertIn("conservado", consola.getvalue())
        # Primer finalizado (sin ESTADO.md): sí se escribe y se commitea.
        estado.unlink()
        rutas = finalizar.escribir_estado_congelado(ws)
        self.assertTrue(estado.is_file())
        self.assertIn("docs/05-trabajo/ESTADO.md", rutas)

    def test_escenario_22_publicar_no_absorbe_trabajo_sin_commitear(self):
        finalizar = cargar_modulo("finalizar_escenario2", RAIZ / "visor/finalizar.py")
        base = Path(tempfile.mkdtemp(prefix="escenario-publicar-"))
        self.addCleanup(shutil.rmtree, base, True)

        def repo(nombre):
            ruta = base / nombre
            ruta.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=ruta, check=True,
                           capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=ruta, check=True)
            subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=ruta,
                           check=True)
            return ruta

        # Con historia y cambios sin commitear: aviso, y NADA se commitea.
        con_historia = repo("con-historia")
        (con_historia / "app.py").write_text("v1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=con_historia, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=con_historia, check=True,
                       capture_output=True)
        (con_historia / "borrador.py").write_text("sin terminar\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as consola:
            finalizar.commit_inicial_o_aviso(con_historia)
        self.assertIn("NO los toco", consola.getvalue())
        estado = subprocess.run(["git", "status", "--porcelain=v1"], cwd=con_historia,
                                text=True, encoding="utf-8", errors="replace",
                                capture_output=True, check=True).stdout
        self.assertIn("borrador.py", estado, "el borrador sigue sin commitear")

        # Sin historia (carpeta ingerida): el import inicial sí barre todo.
        sin_historia = repo("sin-historia")
        (sin_historia / "legado.py").write_text("todo\n", encoding="utf-8")
        finalizar.commit_inicial_o_aviso(sin_historia)
        log = subprocess.run(["git", "log", "--oneline"], cwd=sin_historia, text=True,
                             encoding="utf-8", errors="replace",
                             capture_output=True, check=True).stdout
        self.assertIn("Importa el estado inicial", log)


class EscenariosProcesosAjenos(Escenario):
    """Manuel (07-08): «el agente decidió parar los tests porque sí, sin avisar».
    Nada del método puede matar procesos ajenos, ni sondeando ni borrando."""

    def test_escenario_23_sondear_un_proceso_no_lo_mata(self):
        lease = cargar_modulo("lease_escenario23", SCRIPTS / "lease.py")
        dormilon = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

        def acostar_dormilon():
            dormilon.kill()
            dormilon.wait(timeout=10)

        self.addCleanup(acostar_dormilon)

        for _ in range(5):
            lease.process_start_marker(dormilon.pid)
        time.sleep(0.2)

        self.assertIsNone(dormilon.poll(), "sondear la vida de un PID no puede matarlo")

    @unittest.skipUnless(shutil.which("lsof"), "el guard usa lsof (POSIX)")
    def test_escenario_24_no_se_borra_un_worktree_con_procesos_vivos(self):
        unidad = cargar_modulo("unidad_escenario", SCRIPTS / "unidad.py")
        base = Path(tempfile.mkdtemp(prefix="escenario-worktree-"))
        self.addCleanup(shutil.rmtree, base, True)
        repo = base / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
        (repo / "x.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True,
                       capture_output=True)
        destino = base / "worktree-unidad"
        subprocess.run(["git", "worktree", "add", str(destino), "-b", "unidad"],
                       cwd=repo, check=True, capture_output=True)

        # Una "suite de tests" viva dentro del worktree (fichero abierto + cwd allí).
        suite = subprocess.Popen(
            [sys.executable, "-c",
             "import time; f = open('suite-en-marcha.log', 'w'); time.sleep(60)"],
            cwd=destino,
        )

        def parar_suite():
            suite.kill()
            suite.wait(timeout=10)

        self.addCleanup(parar_suite)
        time.sleep(0.5)

        borrado, motivo = unidad.borrar_worktree(repo, destino)
        self.assertFalse(borrado, motivo)
        self.assertIn(str(suite.pid), motivo)
        self.assertTrue(destino.exists(), "el worktree sigue ahí: la suite vive")
        self.assertIsNone(suite.poll(), "la suite no fue interrumpida")

        suite.kill()
        suite.wait(timeout=10)
        borrado, motivo = unidad.borrar_worktree(repo, destino)
        self.assertTrue(borrado, motivo)

    def test_escenario_25_matar_procesos_por_nombre_es_fail_del_linter(self):
        fx = self.fixture(mod_version.VersionMetodoTest)
        destino = fx.base / "pkill-agents"
        resultado = fx.ejecutar(
            mod_version.BOOTSTRAP, "--planos", str(fx.planos_minimos()),
            "--destino", str(destino),
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        scripts = destino / "main/scripts"
        scripts.mkdir(parents=True)
        (scripts / "test.sh").write_text("#!/bin/sh\npkill -f pytest\n",
                                         encoding="utf-8")

        linter = subprocess.run(
            [sys.executable, str(destino / "docs/00-metodo/scripts/lint_metodo.py")],
            cwd=destino, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )

        self.assertEqual(linter.returncode, 1, linter.stdout + linter.stderr)
        self.assertIn("pkill", linter.stdout)


if __name__ == "__main__":
    unittest.main()
