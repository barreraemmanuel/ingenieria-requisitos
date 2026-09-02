"""Unidad 147: la entrega del constructor se deriva de git y tiene tres consumidores."""

import argparse
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
for ruta in (str(SCRIPTS), str(RAIZ / "visor/tests/reforma")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import ejecucion  # noqa: E402
import entrega  # noqa: E402
import subagente  # noqa: E402
import unidad  # noqa: E402
from taller_reforma import Worktree  # noqa: E402


class EntregaPuraTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="entrega-147-")
        self.addCleanup(self.tmp.cleanup)
        self.wt = Worktree(Path(self.tmp.name) / "worktrees/147-demo", "147-demo")

    def test_entrega_buena_derivada_de_git_pasa(self):
        head = self.wt.commitear()
        problemas, avisos = ejecucion.exigir_entrega_constructor(
            self.wt.ruta,
            self.wt.unidad,
            [self.wt.recibo(resultado="ok", head=head)],
            self.wt.base(marcadas=0),
        )
        self.assertEqual(problemas, [])
        self.assertEqual(avisos, [])

    def test_recibo_fail_bloquea_con_salida(self):
        self.wt.commitear()
        problemas, _ = ejecucion.exigir_entrega_constructor(
            self.wt.ruta,
            self.wt.unidad,
            [self.wt.recibo(resultado="fail")],
            self.wt.base(),
        )
        self.assertTrue(problemas)
        self.assertTrue(all("SALIDA:" in problema for problema in problemas))

    def test_un_commit_vacio_no_cuenta_como_cambio_entregado(self):
        arbol_base = entrega.hechos_git(self.wt.ruta)["tree"]
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "solo cambia la cabeza"],
            cwd=self.wt.ruta, check=True, capture_output=True, text=True,
        )
        recibo = self.wt.recibo(resultado="ok", head=self.wt.head())
        recibo["git"]["inicial"]["tree"] = arbol_base
        recibo["git"]["final"]["tree"] = arbol_base

        problemas, _ = ejecucion.exigir_entrega_constructor(
            self.wt.ruta, self.wt.unidad, [recibo], self.wt.base()
        )

        self.assertTrue(problemas, "R3: mover HEAD sin cambiar el árbol no es una entrega")

    def test_diff_fuera_de_ficheros_es_aviso_y_no_bloqueo(self):
        """R3, última frase: «Diff fuera de `ficheros:`» = aviso. Informa y deja pasar."""
        (self.wt.ruta / "otro.py").write_text("print('fuera del contrato')\n",
                                              encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.wt.ruta,
                       check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "toca un fichero no declarado"],
                       cwd=self.wt.ruta, check=True, capture_output=True)
        base = self.wt.base(marcadas=0)
        base["ficheros"] = ["modulo.py"]

        problemas, avisos = ejecucion.exigir_entrega_constructor(
            self.wt.ruta, self.wt.unidad,
            [self.wt.recibo(resultado="ok", head=self.wt.head())], base,
        )

        self.assertEqual(problemas, [], "R3: el diff de más avisa, NO bloquea")
        self.assertTrue(avisos, "R3: nadie emitió el aviso de «diff fuera de `ficheros:`»")
        self.assertIn("otro.py", avisos[0])
        self.assertIn("ficheros:", avisos[0])

    def test_un_diff_dentro_de_ficheros_no_avisa(self):
        """El falso positivo inverso: lo declarado no genera ruido."""
        head = self.wt.commitear()          # solo toca modulo.py
        base = self.wt.base(marcadas=0)
        base["ficheros"] = ["modulo.py"]

        problemas, avisos = ejecucion.exigir_entrega_constructor(
            self.wt.ruta, self.wt.unidad,
            [self.wt.recibo(resultado="ok", head=head)], base,
        )

        self.assertEqual(problemas, [])
        self.assertEqual(avisos, [])

    def test_una_ficha_sin_ficheros_declarados_no_avisa(self):
        """Sin lista declarada no hay nada contra lo que comparar: ni aviso ni invento."""
        head = self.wt.commitear()
        problemas, avisos = ejecucion.exigir_entrega_constructor(
            self.wt.ruta, self.wt.unidad,
            [self.wt.recibo(resultado="ok", head=head)], self.wt.base(marcadas=0),
        )
        self.assertEqual((problemas, avisos), ([], []))

    def test_ficheros_declarados_lee_la_lista_de_la_ficha(self):
        """El prefijo `nuevo:` marca lo que aún no existe: no es parte de la ruta."""
        ficha = Path(self.tmp.name) / "especificacion.md"
        ficha.write_text(
            "---\nunidad: 147-demo\ncarril: normal\n"
            "ficheros: [a/uno.py, nuevo:b/dos.py]\n---\n", encoding="utf-8")
        self.assertEqual(entrega.ficheros_declarados(ficha), ["a/uno.py", "b/dos.py"])

    def test_exencion_se_decide_por_el_carril(self):
        base = self.wt.base()
        base.update({"carril": "directo", "espera_cambios": False})
        problemas, _ = ejecucion.exigir_entrega_constructor(
            self.wt.ruta, self.wt.unidad, [], base
        )
        self.assertEqual(problemas, [])


class ExitDelLanzadorTest(unittest.TestCase):
    def test_fail_parado_y_revisor_sin_trabajo_salen_distinto_de_cero(self):
        self.assertEqual(ejecucion.exit_de_resultado("fail", "constructor", True), 1)
        self.assertEqual(ejecucion.exit_de_resultado("parado", "constructor", True), 1)
        self.assertEqual(ejecucion.exit_de_resultado("ok_sin_trabajo", "revisor", True), 1)

    def test_sin_trabajo_legitimo_sigue_saliendo_cero(self):
        self.assertEqual(ejecucion.exit_de_resultado("ok_sin_trabajo", "constructor", False), 0)

    def test_resultado_es_la_ultima_linea(self):
        pantalla = io.StringIO()
        with redirect_stdout(pantalla):
            ejecucion.imprimir_resultado(Path("recibo.json"), "fail", avisos=["diagnostico"])
        self.assertEqual(pantalla.getvalue().splitlines()[-1], "RESULTADO recibo.json · fail")


class ReciboDelSubagenteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="subagente-147-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.unidad = "147-demo"
        self.worktree = self.raiz / "worktrees" / self.unidad
        self.worktree.mkdir(parents=True)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Suite")
        self.git("config", "user.email", "suite@example.invalid")
        (self.worktree / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "base.txt")
        self.git("commit", "-m", "base")
        ficha = self.raiz / "docs/05-trabajo" / self.unidad
        ficha.mkdir(parents=True)
        (ficha / "especificacion.md").write_text(
            "---\nunidad: 147-demo\ntipo: feature\ncarril: normal\n---\n"
            "\n## Plan de trabajo\n- [ ] uno\n- [ ] dos\n",
            encoding="utf-8",
        )
        (ficha / "hallazgos.md").write_text(
            "## Plan\n- [ ] uno\n- [ ] dos\n", encoding="utf-8"
        )
        self.ejecuciones = self.raiz / ".runtime/ejecuciones"
        self.leases = self.raiz / ".runtime/leases/active"

    def git(self, *args):
        hecho = subprocess.run(
            ["git", *args], cwd=self.worktree, capture_output=True, text=True
        )
        self.assertEqual(hecho.returncode, 0, hecho.stdout + hecho.stderr)
        return hecho.stdout.strip()

    def args(self, resultado=None, motivo=""):
        datos = {"unidad": self.unidad, "modelo": "modelo-prueba", "rol": "constructor",
                 "esfuerzo": "medio", "pid": os.getpid()}
        if resultado is not None:
            datos.update(resultado=resultado, motivo=motivo)
        return argparse.Namespace(**datos)

    def parchear_raiz(self):
        return mock.patch.multiple(
            subagente,
            RAIZ=self.raiz,
            EJECUCIONES=self.ejecuciones,
            LEASES=self.leases,
        )

    def test_abrir_guarda_head_arbol_y_plan_inicial(self):
        with self.parchear_raiz():
            self.assertEqual(subagente.cmd_abrir(self.args()), 0)
        recibo = json.loads(next(self.ejecuciones.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(recibo["git"]["inicial"]["head"], self.git("rev-parse", "HEAD"))
        self.assertTrue(recibo["git"]["inicial"]["tree"])
        self.assertEqual(recibo["trabajo"]["plan"], {"marcadas": 0, "totales": 2})

    def test_cerrar_ok_materializa_diff_sin_tocar_head(self):
        with self.parchear_raiz():
            self.assertEqual(subagente.cmd_abrir(self.args()), 0)
            head_antes = self.git("rev-parse", "HEAD")
            (self.worktree / "nuevo.txt").write_text("entrega\n", encoding="utf-8")
            hallazgos = self.raiz / "docs/05-trabajo" / self.unidad / "hallazgos.md"
            hallazgos.write_text("## Plan\n- [x] uno\n- [ ] dos\n", encoding="utf-8")
            self.assertEqual(subagente.cmd_cerrar(self.args("ok")), 0)
        recibo = json.loads(next(self.ejecuciones.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(self.git("rev-parse", "HEAD"), head_antes)
        self.assertEqual(recibo["resultado"], "ok")
        self.assertNotEqual(recibo["git"]["final"]["head"], head_antes)
        self.assertTrue(recibo["git"]["final"]["ref"].startswith("refs/entregas/147-demo/"))
        self.assertEqual(self.git("show", f'{recibo["git"]["final"]["head"]}:nuevo.txt'), "entrega")

    def test_cerrar_parado_exige_motivo_y_no_exige_diff(self):
        with self.parchear_raiz():
            self.assertEqual(subagente.cmd_abrir(self.args()), 0)
            self.assertEqual(subagente.cmd_cerrar(self.args("parado")), 1)
            self.assertEqual(subagente.cmd_cerrar(self.args("parado", "contrato ambiguo")), 0)
        recibo = json.loads(next(self.ejecuciones.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(recibo["motivo"], "contrato ambiguo")


class IntegracionTest(unittest.TestCase):
    def test_los_tres_consumidores_llaman_la_misma_puerta(self):
        fuente_ejecucion = (SCRIPTS / "ejecucion.py").read_text(encoding="utf-8")
        fuente_unidad = (SCRIPTS / "unidad.py").read_text(encoding="utf-8")
        self.assertIn("entrega.exigir_entrega_constructor", fuente_ejecucion)
        self.assertGreaterEqual(fuente_unidad.count("entrega.exigir_entrega_constructor"), 2)

    def test_comparador_bloquea_si_el_snapshot_deriva(self):
        hallazgos = []
        revisiones = [
            ({"schema": "lint-hallazgos/v1", "hallazgos": hallazgos}, "snap-a"),
            ({"schema": "lint-hallazgos/v1", "hallazgos": hallazgos}, "snap-b"),
        ]
        with mock.patch.object(unidad, "_revisar_guardian_en_commit", side_effect=revisiones):
            veredicto = unidad.comparar_guardian_revisionado(
                Path("repo"), "a" * 40, "b" * 40, "147-demo", []
            )
        self.assertTrue(veredicto.bloquea)
        self.assertIn("drift", veredicto.motivo.lower())


class DientesEntregaConstructorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dientes-entrega-147-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.nombre = "147-demo"
        carpeta = self.raiz / "docs/05-trabajo" / self.nombre
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            "---\nunidad: 147-demo\ntipo: feature\ncarril: normal\n---\n",
            encoding="utf-8",
        )
        self.worktree = Worktree(self.raiz / "worktrees" / self.nombre, self.nombre)

    def acto(self):
        with mock.patch.multiple(
            entrega,
            RAIZ=self.raiz,
            WORKTREES=self.raiz / "worktrees",
            EJECUCIONES=self.raiz / ".runtime/ejecuciones",
        ):
            return ejecucion.puerta_entrega_para_revisor(self.nombre)

    def test_dientes_R_ENT_01_bloquea(self):
        problemas, _ = self.acto()
        self.assertTrue(problemas)
        self.assertIn("SALIDA:", problemas[0])

    def test_dientes_R_ENT_01_abierto_pasa(self):
        with mock.patch.object(
            entrega, "exigir_entrega_constructor", return_value=([], [])
        ):
            problemas, _ = self.acto()
        self.assertEqual(problemas, [])


if __name__ == "__main__":
    unittest.main()
