"""Bug 152 — el revisor fresco se lanza con el harness que HAY, no con el que dice el papel.

Tres hechos encadenados hacían inejecutable el cierre en un taller solo-Codex y en Windows:

  1. `runbooks/cierre.md` recetaba `--harness claude` y declaraba `codex` «inejecutable»,
     justo lo contrario de lo que `roles.md` promete desde la unidad 100.
  2. `ejecucion.py lanzar` exigía `--harness` y no miraba qué ejecutable existe: sin
     `claude` en el PATH, el cierre moría con «no encuentro el ejecutable claude» y sin
     decir que había otra vía.
  3. En Windows el revisor Codex ni arrancaba: el perfil de permisos con DOS conjuntos de
     rutas escribibles (carpeta de la unidad + temporal) devuelve `UnsupportedOperation`
     porque el sandbox de Windows sin elevación no admite varios.

Aquí se fija el comportamiento contrario, y se fija en los tres sitios a la vez: el
lanzador, la prosa que lo receta y el perfil de Windows.
"""
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(RAIZ / "visor") not in sys.path:
    sys.path.insert(0, str(RAIZ / "visor"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import ejecucion                                    # noqa: E402
from test_paridad_codex import BaseLanzadorCodex    # noqa: E402

CIERRE = RAIZ / "plantilla/docs/00-metodo/runbooks/cierre.md"
ROLES = RAIZ / "plantilla/docs/00-metodo/roles.md"


# =============================================================== (b) elegir por disponibilidad
class EleccionDeHarnessTest(unittest.TestCase):
    """`elegir_harness` es pura: recibe qué hay instalado y qué usó el constructor."""

    def elegir(self, pedido, disponibles, rol="revisor", constructor=None):
        return ejecucion.elegir_harness(
            pedido, rol, "001-demo", disponibles=tuple(disponibles),
            constructor=constructor)

    def test_auto_prefiere_el_harness_distinto_del_que_construyo(self):
        harness, origen = self.elegir("auto", ("claude", "codex"), constructor="claude")

        self.assertEqual(harness, "codex")
        self.assertIn("constructor", origen)

    def test_auto_prefiere_el_distinto_tambien_al_reves(self):
        harness, _ = self.elegir("auto", ("claude", "codex"), constructor="codex")

        self.assertEqual(harness, "claude")

    def test_con_un_solo_harness_instalado_el_revisor_sale_con_ese(self):
        # El caso del incidente 4f6bdaed: taller solo-Codex. La revisión fresca NO se
        # cancela — el modelo distinto lo sigue garantizando la tabla de la regla 10.
        harness, origen = self.elegir("auto", ("codex",), constructor="codex")

        self.assertEqual(harness, "codex")
        self.assertIn("único", origen)

    def test_sin_ningun_harness_instalado_el_rechazo_dice_que_instalar(self):
        with self.assertRaises(ejecucion.ErrorEjecucion) as caja:
            self.elegir("auto", ())

        mensaje = str(caja.exception)
        self.assertIn(ejecucion.SALIDA, mensaje)
        self.assertIn("claude", mensaje)
        self.assertIn("codex", mensaje)
        self.assertIn("npm install -g", mensaje)

    def test_pedir_a_mano_un_harness_que_no_esta_nombra_el_que_si(self):
        with self.assertRaises(ejecucion.ErrorEjecucion) as caja:
            self.elegir("claude", ("codex",))

        mensaje = str(caja.exception)
        self.assertIn(ejecucion.SALIDA, mensaje)
        self.assertIn("--harness auto", mensaje)
        self.assertIn("codex", mensaje)

    def test_pedir_a_mano_uno_que_si_esta_manda_sobre_la_preferencia(self):
        harness, origen = self.elegir("codex", ("claude", "codex"), constructor="codex")

        self.assertEqual(harness, "codex")
        self.assertIn("mano", origen)

    def test_el_constructor_sin_pedir_nada_prefiere_claude_si_lo_hay(self):
        harness, _ = self.elegir("auto", ("claude", "codex"), rol="constructor")

        self.assertEqual(harness, "claude")

    def test_el_constructor_sin_claude_sale_con_codex(self):
        harness, _ = self.elegir("auto", ("codex",), rol="constructor")

        self.assertEqual(harness, "codex")


class HarnessDelConstructorTest(unittest.TestCase):
    """De dónde sale «con qué construyó»: de los recibos, no de la memoria de nadie."""

    def test_un_harness_desconocido_no_dicta_preferencia(self):
        # `subagente-del-padre` (ADR-033) no es un ejecutable: no sirve para decir «el otro».
        self.assertIsNone(ejecucion.harness_conocido("subagente-del-padre"))
        self.assertEqual(ejecucion.harness_conocido("codex"), "codex")


# ============================================================ (c) el perfil de Windows
class PerfilDelRevisorPorPlataformaTest(unittest.TestCase):
    """Windows sin elevación no admite VARIOS conjuntos de rutas escribibles."""

    def setUp(self):
        self.unidad = Path("/tmp/ws/docs/05-trabajo/001-demo")
        self.temporal = Path("/tmp/ws/.runtime/ejecucion-001-demo-abc")

    def test_en_posix_siguen_siendo_dos_raices(self):
        nombre, escribibles = ejecucion.perfil_revisor_codex(
            [str(self.unidad)], self.temporal, so="posix")

        self.assertEqual(nombre, ejecucion.PERFIL_REVISOR_CODEX)
        self.assertEqual([str(r) for r in escribibles],
                         [str(self.unidad), str(self.temporal)])

    def test_en_windows_queda_una_sola_raiz_escribible(self):
        nombre, escribibles = ejecucion.perfil_revisor_codex(
            [str(self.unidad)], self.temporal, so="nt")

        self.assertEqual(nombre, ejecucion.PERFIL_REVISOR_CODEX_UNA_RAIZ)
        self.assertEqual(len(escribibles), 1)
        # La que queda es el temporal: sin él la sesión de Codex no arranca (ni rollout ni
        # CODEX_HOME), y sin sesión no hay revisión ninguna.
        self.assertEqual(str(escribibles[0]), str(self.temporal))
        self.assertNotIn(str(self.unidad), [str(r) for r in escribibles])

    def test_el_argv_de_windows_declara_ese_perfil_y_solo_esa_raiz(self):
        argv = ejecucion.argv_harness(
            "codex", "/bin/codex", "revisor", Path("/tmp/ws/worktrees/001-demo"), "encargo",
            documentos=[self.unidad / "hallazgos.md"], temporal=self.temporal, so="nt")

        config = [argv[i + 1] for i, pieza in enumerate(argv[:-1]) if pieza == "-c"]
        perfil = ejecucion.PERFIL_REVISOR_CODEX_UNA_RAIZ
        self.assertIn(f'default_permissions="{perfil}"', config)
        mapa = next(c for c in config if c.startswith(f"permissions.{perfil}.filesystem="))
        self.assertEqual(mapa.count('"write"'), 1, mapa)
        self.assertNotIn(str(self.unidad), mapa)


class FirmaSelladaPorElLanzadorTest(unittest.TestCase):
    """Bajo una sola raíz el revisor NO puede escribir su firma: la sella el lanzador,
    desde el recibo, igual que ya hace con `revisado_patch_id`."""

    def setUp(self):
        import tempfile
        self.temporal = tempfile.TemporaryDirectory(prefix="firma-152-")
        self.addCleanup(self.temporal.cleanup)
        self.hallazgos = Path(self.temporal.name) / "hallazgos.md"
        self.hallazgos.write_text(
            "---\nunidad: 001-demo\nrevisor: no\nrevisado: no\n"
            "revisado_patch_id: no\nronda: 1\n---\n# Hallazgos\n", encoding="utf-8")

    def test_sella_revisor_y_revisado_desde_el_recibo(self):
        sellada = ejecucion.sellar_firma_del_revisor(
            self.hallazgos, "modelo-segundo", "2026-09-03")

        self.assertTrue(sellada)
        texto = self.hallazgos.read_text(encoding="utf-8")
        self.assertIn("revisor: modelo-segundo", texto)
        self.assertIn("revisado: 2026-09-03", texto)

    def test_sin_modelo_acreditado_no_se_inventa_una_firma(self):
        self.assertFalse(
            ejecucion.sellar_firma_del_revisor(self.hallazgos, "", "2026-09-03"))
        self.assertIn("revisor: no", self.hallazgos.read_text(encoding="utf-8"))


# ================================================== (b) de punta a punta, con el doble de codex
class SoloCodexInstaladoTest(BaseLanzadorCodex):
    """El taller de Javier: Codex instalado, `claude` no. El cierre TIENE que poder revisar."""

    def setUp(self):
        super().setUp()
        # PATH sin `claude` de ninguna clase, pero con `git` (el lanzador lo necesita).
        solo_git = self.base / "bin-sistema"
        solo_git.mkdir()
        for orden in ("git", "python3"):
            ruta = shutil.which(orden)
            if not ruta:
                self.skipTest(f"sin `{orden}` en el PATH")
            os.symlink(ruta, solo_git / orden)
        self.env["PATH"] = os.pathsep.join([str(self.bin), str(solo_git)])

    def recibo(self):
        """El del REVISOR: la entrega del constructor la siembra un fixture y también deja
        recibo, así que el de la base (que exige uno solo) no vale aquí."""
        carpeta = self.ws / ".runtime/ejecuciones"
        recibos = [json.loads(r.read_text(encoding="utf-8"))
                   for r in sorted(carpeta.glob(f"{self.unidad}-*.json"))]
        revisores = [r for r in recibos if r.get("rol") == "revisor"]
        self.assertEqual(len(revisores), 1, recibos)
        return revisores[0]

    def lanzar_sin_harness(self, rol="revisor"):
        import subprocess
        if rol == "revisor":
            self.sembrar_entrega_constructor()
        return subprocess.run(
            [sys.executable, str(self.launcher), "lanzar", self.unidad,
             "--rol", rol, "--prompt", "Revisa el diff contra el contrato"],
            cwd=str(self.main), env=self.env, text=True, encoding="utf-8",
            errors="replace", capture_output=True)

    def test_sin_claude_el_revisor_sale_igual_con_codex(self):
        resultado = self.lanzar_sin_harness()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertEqual(recibo["harness"], "codex")
        self.assertTrue(recibo.get("harness_origen"), recibo)

    def test_el_recibo_deja_constancia_de_por_que_ese_harness(self):
        self.lanzar_sin_harness()

        self.assertIn("codex", self.recibo()["harness_origen"])

    def test_pedir_claude_a_mano_rechaza_nombrando_la_salida(self):
        import subprocess
        self.sembrar_entrega_constructor()
        resultado = subprocess.run(
            [sys.executable, str(self.launcher), "lanzar", self.unidad,
             "--harness", "claude", "--rol", "revisor", "--prompt", "Revisa"],
            cwd=str(self.main), env=self.env, text=True, encoding="utf-8",
            errors="replace", capture_output=True)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn(ejecucion.SALIDA, resultado.stderr)
        self.assertIn("--harness auto", resultado.stderr)

    def test_el_recibo_dice_bajo_que_perfil_corrio_el_revisor(self):
        self.lanzar_sin_harness()

        perfil = self.recibo().get("perfil_revisor")
        self.assertIsInstance(perfil, dict, self.recibo())
        self.assertEqual(perfil["nombre"], ejecucion.PERFIL_REVISOR_CODEX)
        self.assertTrue(perfil["escribibles"])


# ======================================================== (a) los dos papeles dicen lo mismo
class LaProsaNoContradiceAlLanzadorTest(unittest.TestCase):

    def test_cierre_ya_no_declara_codex_inejecutable(self):
        texto = CIERRE.read_text(encoding="utf-8")

        self.assertNotIn("inejecutable", texto)
        self.assertNotIn("--harness claude --rol revisor", texto)

    def test_cierre_receta_el_harness_disponible(self):
        texto = CIERRE.read_text(encoding="utf-8")

        self.assertIn("--rol revisor", texto)
        self.assertIn("harness", texto)
        self.assertIn("disponible", texto)

    def test_roles_explica_la_eleccion_y_el_perfil_de_una_raiz(self):
        texto = ROLES.read_text(encoding="utf-8")

        self.assertIn("una sola raíz", texto)
        self.assertIn("Windows", texto)

    def test_el_comando_que_receta_unidad_py_no_cablea_claude(self):
        unidad = (SCRIPTS / "unidad.py").read_text(encoding="utf-8")
        lint = (SCRIPTS / "lint_cierre.py").read_text(encoding="utf-8")

        self.assertNotIn("--harness claude --rol revisor", unidad)
        self.assertNotIn("--harness claude --rol revisor", lint)


if __name__ == "__main__":
    unittest.main()
