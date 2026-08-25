"""Bug 065 — el lanzador y la regla 10: modelo por carril, revisión sin worktree, permisos.

Tres defectos de `ejecucion.py` vistos la noche del 25-08, uno por sección del contrato:

  A (R1/R2) `--modelo` era opcional y no había tabla: todo subagente salía con el modelo
            por defecto del harness (el más caro) y el recibo no guardaba el esfuerzo.
  B (R3)    revisar una unidad ya entregada cuyo worktree ya no existe no tenía camino:
            `lanzar --rol revisor` moría con «no figura en git worktree list».
  C (R4)    la ventana de solo lectura de la ficha no era a prueba de muertes: si el
            lanzador moría con ella abierta, la ficha se quedaba en 0444 PARA SIEMPRE
            (la ejecución siguiente leía 0444 como «modo previo» y lo re-congelaba), y
            `unidad.py cerrar` reventaba con un PermissionError pelado en vez de decir
            cómo salir.

Los tests de aquí son end-to-end sobre el launcher REAL (dobles de harness que graban su
argv), salvo los que interrogan a la tabla o a los ayudantes puros de `unidad.py`.
"""
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import repo_config  # noqa: E402  (el REAL, sin mutar)
import unidad as gestion_unidad  # noqa: E402

# Los ficheros del método que el launcher necesita a su lado dentro del workspace de prueba.
ACOMPANANTES = ("control_plane.py", "lease.py", "workspace_paths.py", "repo_config.py")


class BaseLanzador(unittest.TestCase):
    """Workspace de prueba mínimo: meta-repo con su ficha, repo de código y su worktree."""

    estado_inicial = "en_obra"
    carril_inicial = "normal"

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="modelo-por-carril-")
        self.addCleanup(self.temporal.cleanup)
        self.base = Path(self.temporal.name)
        self.ws = self.base / "demo-agents"
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        launcher_canonico = SCRIPTS / "ejecucion.py"
        self.assertTrue(launcher_canonico.is_file(), "falta el launcher canónico")
        for nombre in ("ejecucion.py", *ACOMPANANTES):
            (scripts / nombre).write_bytes((SCRIPTS / nombre).read_bytes())
        self.launcher = scripts / "ejecucion.py"

        self.unidad = "001-demo"
        self.ficha = self.ws / "docs/05-trabajo" / self.unidad / "especificacion.md"
        self.ficha.parent.mkdir(parents=True)
        self.escribir_ficha()
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
        self.sha_base = self.git(
            "rev-parse", "HEAD", cwd=self.main).stdout.strip()
        (self.ws / "worktrees").mkdir()
        self.worktree = self.ws / "worktrees" / self.unidad
        self.git("worktree", "add", str(self.worktree), "-b", self.unidad, "main",
                 cwd=self.main)

        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.registro = self.base / "harness-record.json"
        self.instalar_grabador()

        self.home = self.base / "home-real"
        self.home.mkdir()
        (self.home / ".gitconfig").write_text(
            "[user]\n\tname = Tester De Campo\n\temail = tester@example.com\n",
            encoding="utf-8",
        )
        self.env = dict(
            os.environ,
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            HOME=str(self.home),
        )

    # ------------------------------------------------------------------ utilidades
    def escribir_ficha(self, estado=None, carril=None, extra=""):
        self.ficha.write_text(
            "---\nnumero: 001\ntipo: feature\n"
            f"estado: {estado or self.estado_inicial}\n"
            f"carril: {carril or self.carril_inicial}\n"
            "ficheros: [app/demo.py]\n"
            f"{extra}---\n# Demo\n",
            encoding="utf-8",
        )

    def git(self, *args, cwd):
        resultado = subprocess.run(
            ["git", *args], cwd=str(cwd), text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return resultado

    PREAMBULO = """import os, re, sys

def resolver(valor):
    coincide = re.fullmatch(r'##(IR_CMDARG_\\d+)##', valor) if isinstance(valor, str) else None
    return os.environ.get(coincide.group(1), valor) if coincide else valor

argv = [resolver(v) for v in sys.argv[1:]]
prompt = argv[-1] if argv else ''
"""

    # El destino se hornea en el cuerpo del doble: `ejecucion.py` filtra el entorno del
    # harness contra HEREDAR_ENV, así que una variable de test JAMÁS lo cruza; y el
    # registro tiene que sobrevivir al worktree efímero, que se borra antes de mirarlo.
    CUERPO_GRABADOR = """import json, pathlib, subprocess
destino = pathlib.Path(DESTINO)
destino.write_text(json.dumps({
    'argv': argv,
    'cwd': os.getcwd(),
    'head': subprocess.run(['git', 'rev-parse', 'HEAD'], text=True,
                           capture_output=True).stdout.strip(),
    'branch': subprocess.run(['git', 'branch', '--show-current'], text=True,
                             capture_output=True).stdout.strip(),
}), encoding='utf-8')
"""

    def instalar_grabador(self):
        cabecera = f"DESTINO = {str(self.registro)!r}\n"
        for nombre in ("claude", "codex"):
            self.instalar_doble(nombre, cabecera + self.CUERPO_GRABADOR)

    def instalar_doble(self, nombre, cuerpo):
        cuerpo = self.PREAMBULO + cuerpo
        if os.name == "nt":
            script = self.bin / f"{nombre}.py"
            script.write_text(cuerpo, encoding="utf-8")
            (self.bin / f"{nombre}.bat").write_text(
                f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
            )
        else:
            destino = self.bin / nombre
            destino.write_text("#!/usr/bin/env python3\n" + cuerpo, encoding="utf-8")
            destino.chmod(destino.stat().st_mode | stat.S_IXUSR)

    def argumentos(self, *extra, harness="claude", rol="constructor",
                   prompt="Haz la tarea", unidad=None):
        return [
            sys.executable, str(self.launcher), "lanzar", unidad or self.unidad,
            "--harness", harness, "--rol", rol, *extra, "--prompt", prompt,
        ]

    def ejecutar(self, *extra, **kwargs):
        env = kwargs.pop("env", None) or self.env
        return subprocess.run(
            self.argumentos(*extra, **kwargs), cwd=str(self.main), env=env, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )

    def registros(self, ruta=None):
        return json.loads((ruta or self.registro).read_text(encoding="utf-8"))

    def modelo_del_argv(self, argv):
        self.assertIn("--model", argv, f"el argv del harness no lleva modelo: {argv}")
        return argv[argv.index("--model") + 1]

    def recibo(self):
        recibos = sorted((self.ws / ".runtime/ejecuciones").glob(f"{self.unidad}-*.json"))
        self.assertEqual(len(recibos), 1, f"se esperaba un único recibo: {recibos}")
        return json.loads(recibos[0].read_text(encoding="utf-8"))


# ===================================================== R1 · la tabla carril × rol
class TablaDeModelosTest(unittest.TestCase):
    """La tabla vive en `repo_config` y tiene una respuesta para cada carril y cada rol."""

    def test_el_constructor_sale_en_opus_en_todos_los_carriles(self):
        # Decisión de Nate del 25-08: «prefiero Opus para los subagentes».
        for carril in repo_config.CARRILES:
            with self.subTest(carril=carril):
                plan = repo_config.plan_de_modelo(carril, "constructor")
                self.assertEqual(plan.modelo, "claude-opus-5")

    def test_el_revisor_sale_en_un_modelo_distinto_del_constructor(self):
        # Regla 10: dos instancias del mismo modelo comparten puntos ciegos.
        for carril in repo_config.CARRILES:
            with self.subTest(carril=carril):
                constructor = repo_config.plan_de_modelo(carril, "constructor")
                revisor = repo_config.plan_de_modelo(carril, "revisor")
                self.assertNotEqual(revisor.modelo, constructor.modelo)
                self.assertEqual(revisor.modelo, "claude-fable-5")

    def test_lo_documental_y_el_lint_usan_el_modelo_pequeno(self):
        plan = repo_config.plan_de_modelo("normal", "constructor", documental=True)
        self.assertEqual(plan.modelo, "claude-haiku-4-5")

    def test_el_esfuerzo_sube_con_el_carril(self):
        # Regla 10: exprés y directo lo más barato; normal medio; completo y hotfix alto.
        self.assertEqual(repo_config.plan_de_modelo("directo", "constructor").esfuerzo, "bajo")
        self.assertEqual(repo_config.plan_de_modelo("expres", "constructor").esfuerzo, "bajo")
        self.assertEqual(repo_config.plan_de_modelo("normal", "constructor").esfuerzo, "medio")
        self.assertEqual(repo_config.plan_de_modelo("completo", "constructor").esfuerzo, "alto")
        self.assertEqual(repo_config.plan_de_modelo("hotfix", "constructor").esfuerzo, "alto")

    def test_el_acento_de_expres_no_abre_un_carril_distinto(self):
        self.assertEqual(
            repo_config.plan_de_modelo("Exprés", "constructor"),
            repo_config.plan_de_modelo("expres", "constructor"),
        )

    def test_un_carril_desconocido_no_se_inventa_un_modelo(self):
        with self.assertRaises(repo_config.RepoConfigError) as capturado:
            repo_config.plan_de_modelo("turbo", "constructor")
        self.assertIn("turbo", str(capturado.exception))


class DespachoSinFlagsTest(BaseLanzador):
    """R1 end-to-end: sin `--modelo`, el launcher deriva el modelo del carril de la ficha."""

    def test_el_constructor_sin_flags_sale_en_opus(self):
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.modelo_del_argv(self.registros()["argv"]), "claude-opus-5")

    def test_el_revisor_sin_flags_sale_en_un_modelo_distinto(self):
        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.modelo_del_argv(self.registros()["argv"]), "claude-fable-5")

    def test_una_unidad_documental_sale_en_el_modelo_pequeno(self):
        self.escribir_ficha(extra="ejecucion: documental\n")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.modelo_del_argv(self.registros()["argv"]), "claude-haiku-4-5")

    def test_el_modelo_explicito_sin_motivo_se_rechaza_y_nombra_su_salida(self):
        resultado = self.ejecutar("--modelo", "claude-sonnet-5")

        self.assertNotEqual(resultado.returncode, 0)
        salida = resultado.stdout + resultado.stderr
        self.assertIn("SALIDA:", salida)
        self.assertIn("--motivo-modelo", salida)
        self.assertFalse(self.registro.exists())

    def test_el_modelo_explicito_con_motivo_manda_y_queda_anotado(self):
        resultado = self.ejecutar(
            "--modelo", "claude-sonnet-5",
            "--motivo-modelo", "el fable no está disponible en esta cuenta",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.modelo_del_argv(self.registros()["argv"]), "claude-sonnet-5")
        recibo = self.recibo()
        self.assertEqual(recibo["modelo_origen"], "excepcion")
        self.assertIn("fable no está disponible", recibo["motivo_modelo"])

    def test_codex_no_recibe_modelo_derivado_de_la_tabla(self):
        # R5: la tabla son identificadores de Anthropic; codex no los admite y el
        # launcher no se los inventa. Lo que NO puede pasar es que la tabla lo mate.
        resultado = self.ejecutar(harness="codex")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("--model", self.registros()["argv"])
        self.assertEqual(self.recibo()["modelo"], None)


# ===================================================== R2 · el recibo guarda lo efectivo
class ReciboConModeloYEsfuerzoTest(BaseLanzador):

    def test_el_recibo_guarda_modelo_y_esfuerzo_efectivos(self):
        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertEqual(recibo["modelo"], "claude-opus-5")
        self.assertEqual(recibo["esfuerzo"], "medio")
        self.assertEqual(recibo["modelo_origen"], "tabla")

    def test_el_carril_completo_queda_acreditado_con_su_esfuerzo(self):
        self.escribir_ficha(carril="completo")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.recibo()["esfuerzo"], "alto")


class CierreMuestraElModeloTest(unittest.TestCase):
    """R2 — `unidad.py cerrar` enseña con qué modelo y esfuerzo se hizo cada cosa."""

    def recibo(self, rol, modelo, esfuerzo="", origen="tabla", motivo=""):
        return {"rol": rol, "modelo": modelo, "esfuerzo": esfuerzo,
                "modelo_origen": origen, "motivo_modelo": motivo,
                "resultado": "ok", "exit_code": 0, "lease": {"session_id": f"s-{rol}"}}

    def test_la_linea_nombra_modelo_y_esfuerzo_de_cada_rol(self):
        lineas = gestion_unidad.lineas_de_modelo([
            self.recibo("constructor", "claude-opus-5", "medio"),
            self.recibo("revisor", "claude-fable-5", "medio"),
        ])

        texto = " | ".join(lineas)
        self.assertIn("claude-opus-5", texto)
        self.assertIn("claude-fable-5", texto)
        self.assertIn("medio", texto)
        self.assertIn("constructor", texto)
        self.assertIn("revisor", texto)

    def test_la_excepcion_a_la_tabla_se_ve_con_su_motivo(self):
        lineas = gestion_unidad.lineas_de_modelo([
            self.recibo("constructor", "claude-sonnet-5", "medio",
                        origen="excepcion", motivo="la cuenta no tiene opus"),
        ])

        texto = " | ".join(lineas)
        self.assertIn("excepción", texto)
        self.assertIn("la cuenta no tiene opus", texto)

    def test_un_recibo_viejo_sin_esfuerzo_no_inventa_nada(self):
        lineas = gestion_unidad.lineas_de_modelo([
            {"rol": "constructor", "modelo": "opus", "resultado": "ok"},
        ])

        self.assertIn("opus", " | ".join(lineas))
        self.assertNotIn("esfuerzo", " | ".join(lineas))


class ComandoDeRevisionArrancaTest(unittest.TestCase):
    """R1 — la salida que ofrece el cierre tiene que seguir ARRANCANDO tras la tabla.

    `comando_revision` ofrecía `--modelo <modelo-distinto-del-constructor>`. Con la tabla
    puesta, `--modelo` es una excepción que exige `--motivo-modelo`: ese comando pegado tal
    cual moriría en el argparse, y el operador se quedaría sin salida justo donde el método
    le prometía una.
    """

    def test_la_salida_del_cierre_no_ofrece_un_modelo_a_medias(self):
        comando = gestion_unidad.comando_revision("001-demo")

        if "--modelo" in comando:
            self.assertIn("--motivo-modelo", comando)
        self.assertIn("--rol revisor", comando)
        self.assertNotIn("<", comando, f"la salida sigue teniendo huecos: {comando}")


# ===================================================== R3 · revisar sin worktree
class RevisorSinWorktreeTest(BaseLanzador):
    """B — con el worktree borrado, `lanzar --rol revisor` se lo crea él solo."""

    def preparar_entregada(self, estado="en_validacion", fusion=True):
        self.git("worktree", "remove", "--force", str(self.worktree), cwd=self.main)
        self.git("branch", "-D", self.unidad, cwd=self.main)
        extra = f"fusion: {self.sha_base}\n" if fusion else ""
        self.escribir_ficha(estado=estado, extra=extra)

    def test_el_revisor_crea_el_worktree_efimero_sobre_la_fusion(self):
        self.preparar_entregada()

        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        registro = self.registros(self.registro)
        self.assertEqual(registro["head"], self.sha_base)
        self.assertEqual(registro["branch"], "", "el worktree de revisión va detached")
        self.assertEqual(Path(registro["cwd"]).name, self.unidad)

    def test_el_worktree_efimero_se_borra_al_terminar(self):
        self.preparar_entregada()

        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(self.worktree.exists(), "el worktree efímero sigue en disco")
        inventario = self.git("worktree", "list", "--porcelain", cwd=self.main).stdout
        self.assertNotIn(self.unidad, inventario)

    def test_una_unidad_mergeada_tambien_se_puede_revisar(self):
        self.preparar_entregada(estado="mergeada")

        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.registros(self.registro)["head"], self.sha_base)

    def test_sin_fusion_anotada_el_rechazo_nombra_su_salida(self):
        self.preparar_entregada(fusion=False)

        resultado = self.ejecutar(rol="revisor")

        self.assertNotEqual(resultado.returncode, 0)
        salida = resultado.stdout + resultado.stderr
        self.assertIn("SALIDA:", salida)
        self.assertIn("fusion", salida)

    def test_el_constructor_sin_worktree_sigue_bloqueado(self):
        # La puerta trasera es SOLO del revisor: una unidad entregada no se sigue
        # construyendo, y una en obra sin worktree es un despacho a medias.
        self.preparar_entregada(estado="en_obra")

        resultado = self.ejecutar(rol="constructor")

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("SALIDA:", resultado.stdout + resultado.stderr)
        self.assertFalse(self.worktree.exists())

    def test_el_worktree_registrado_de_siempre_sigue_mandando(self):
        # Regresión: con worktree vivo NO se crea nada efímero ni se borra nada.
        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.registros(self.registro)["branch"], self.unidad)
        self.assertTrue(self.worktree.is_dir())


# ===================================================== R4 · permisos de la ficha
class PermisosDeLaFichaTest(BaseLanzador):
    """C — la ventana de solo lectura del constructor no puede dejar la ficha muerta."""

    def modo(self, ruta):
        return stat.S_IMODE(ruta.stat().st_mode)

    @unittest.skipIf(os.name == "nt", "los bits POSIX no se pueden exigir en Windows")
    def test_el_revisor_no_toca_los_permisos_de_la_ficha_ni_de_su_carpeta(self):
        antes = (self.modo(self.ficha), self.modo(self.ficha.parent))

        resultado = self.ejecutar(rol="revisor")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual((self.modo(self.ficha), self.modo(self.ficha.parent)), antes)

    @unittest.skipIf(os.name == "nt", "los bits POSIX no se pueden exigir en Windows")
    def test_el_constructor_devuelve_la_ficha_como_estaba(self):
        antes = self.modo(self.ficha)

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.modo(self.ficha), antes)

    @unittest.skipIf(os.name == "nt", "los bits POSIX no se pueden exigir en Windows")
    def test_una_ficha_que_llega_en_solo_lectura_no_se_queda_congelada(self):
        # El trinquete de C: `modo_previo` se leía del disco, así que una ficha que ya
        # venía en 0444 (de una ejecución anterior muerta) se re-congelaba en cada
        # lanzamiento y nadie volvía a poder escribirla.
        self.ficha.chmod(0o444)

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertTrue(self.modo(self.ficha) & stat.S_IWUSR,
                        f"la ficha sigue en solo lectura: {oct(self.modo(self.ficha))}")

    @unittest.skipIf(os.name == "nt", "no hay SIGTERM POSIX que enviar en Windows")
    def test_matar_al_lanzador_no_deja_la_ficha_en_solo_lectura(self):
        # La causa raíz de C: `finally` no corre cuando el proceso muere por SIGTERM.
        aviso = self.ws / "harness-listo"
        puerta = self.ws / "harness-puede-salir"
        self.instalar_doble("claude", f"""import pathlib, time
pathlib.Path({str(aviso)!r}).write_text('listo', encoding='utf-8')
limite = time.monotonic() + 30
while not pathlib.Path({str(puerta)!r}).exists() and time.monotonic() < limite:
    time.sleep(0.02)
""")
        proceso = subprocess.Popen(
            self.argumentos(), cwd=str(self.main), env=self.env, text=True,
            encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        def cerrar():
            if proceso.poll() is None:
                proceso.kill()
            for tuberia in (proceso.stdout, proceso.stderr):
                tuberia.close()

        self.addCleanup(cerrar)
        limite = time.monotonic() + 20
        while not aviso.exists():
            self.assertLess(time.monotonic(), limite, "el doble nunca arrancó")
            self.assertIsNone(proceso.poll(), "el lanzador murió antes de tiempo")
            time.sleep(0.02)
        self.assertEqual(self.modo(self.ficha), 0o444,
                         "la ventana de solo lectura ni siquiera se abrió")

        proceso.send_signal(signal.SIGTERM)
        # `communicate()` esperaría al HIJO, que heredó las tuberías y sigue vivo: se
        # espera solo al lanzador y la puerta se suelta después.
        proceso.wait(timeout=30)
        puerta.write_text("ya", encoding="utf-8")

        self.assertTrue(self.modo(self.ficha) & stat.S_IWUSR,
                        f"la ficha quedó muerta en {oct(self.modo(self.ficha))}")


class CerrarConLaFichaBloqueadaTest(unittest.TestCase):
    """R4, segunda mitad — `unidad.py` nombra `chmod u+w` en vez de reventar."""

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="ficha-bloqueada-")
        self.addCleanup(self.temporal.cleanup)
        raiz = Path(self.temporal.name).resolve()
        # `fichero_unidad_seguro` confina toda escritura a la raíz del workspace: para el
        # test la raíz ES el temporal, y así ninguna prueba escribe dentro del repo.
        parche = mock.patch.object(gestion_unidad, "RAIZ", raiz)
        parche.start()
        self.addCleanup(parche.stop)
        self.ruta = raiz / "docs/05-trabajo/001-demo/especificacion.md"
        self.ruta.parent.mkdir(parents=True)
        self.ruta.write_text("---\nestado: en_obra\n---\n", encoding="utf-8")

    @unittest.skipIf(os.name == "nt", "los bits POSIX no se pueden exigir en Windows")
    def test_escribir_una_ficha_en_0444_dice_como_desbloquearla(self):
        self.ruta.chmod(0o444)
        self.addCleanup(self.ruta.chmod, 0o644)

        with self.assertRaises(gestion_unidad.ErrorFichaBloqueada) as capturado:
            gestion_unidad.escribir_fichero_unidad(self.ruta, "nuevo\n")

        mensaje = str(capturado.exception)
        self.assertIn("SALIDA:", mensaje)
        self.assertRegex(mensaje, r"chmod u\+w\s+\S")


if __name__ == "__main__":
    unittest.main()
