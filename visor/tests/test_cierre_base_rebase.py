"""Bug 066: el cierre mide desde una base que el rebase dejó vieja, y fusiona sin guardianes.

Dos síntomas del 25-08, un mismo momento del ritual —el paso 3 de `runbooks/cierre.md`, el
fast-forward— y las tres cosas que el contrato pide demostrar:

  · **A · la medida.** Con `main` por delante, toda rama se rebasa para poder fusionar por ff.
    `metadata.base_sha` sigue siendo el `origin/main` del día del despacho, así que el diff
    del carril directo cuenta como propios los commits AJENOS que el rebase metió por debajo.
    El padre corrigió el SHA a mano ocho veces (055 aportaba 14 ficheros y 993 líneas a la
    medida de una unidad que había tocado dos).
  · **B · los guardianes.** `main` avanzó entre el veredicto del revisor y el ff, y cada
    avance metió un rechazo mudo nuevo: el trinquete de `lint_salidas` lo cazó al fusionar,
    con el cierre ya en marcha.

Los tres tests son los de R3: rama rebasada con commits ajenos por debajo → la medida cuenta
solo lo suyo; rama sin rebasar → FAIL con salida; guardián rojo sobre el árbol rebasado →
FAIL con salida.
"""

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
sys.path.insert(0, str(SCRIPTS))

import peticion as gestion_peticiones  # noqa: E402
import unidad  # noqa: E402


class BaseDeMedidaTrasRebaseTest(unittest.TestCase):
    """A · R1 — la medida del carril directo cuenta solo lo de la unidad."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cierre-base-rebase-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "codigo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "declarado.py").write_text("v1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")
        self.base_despacho = self.sha("HEAD")
        self.rama = "033-carril-directo"

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    def sha(self, ref):
        return self.git("rev-parse", ref).stdout.strip()

    def rama_con_su_trabajo(self):
        """La unidad toca UN fichero declarado y dos líneas: un directo de manual."""
        self.git("checkout", "-b", self.rama)
        (self.repo / "declarado.py").write_text("v2\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", f"{self.rama}: el arreglo")
        self.git("checkout", "main")

    def main_avanza_con_lo_ajeno(self):
        """055 y compañía: 14 ficheros y casi mil líneas que no son de esta unidad."""
        for indice in range(14):
            ruta = self.repo / f"ajeno_{indice:02d}.py"
            ruta.write_text("\n".join(f"linea {n}" for n in range(70)) + "\n",
                            encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "055-otra-unidad: trabajo ajeno")

    def puerta(self, base_registrada, sha_fusion=""):
        original = gestion_peticiones.base_despacho
        gestion_peticiones.base_despacho = lambda *_a, **_k: base_registrada
        try:
            return unidad.puerta_carril_directo(
                self.repo, self.rama, "directo", {"declarado.py"},
                ["P-20260825-5acf8ea5@1"], "bug", "main", sha_fusion,
            )
        finally:
            gestion_peticiones.base_despacho = original

    def test_rebasada_con_commits_ajenos_debajo_mide_solo_lo_suyo(self):
        self.rama_con_su_trabajo()
        self.main_avanza_con_lo_ajeno()
        self.git("checkout", self.rama)
        self.git("rebase", "main")
        self.git("checkout", "main")

        problema, nota = self.puerta(self.base_despacho)

        self.assertIsNone(problema, problema)
        self.assertIn("1 fichero(s)", nota)
        self.assertIn("2 línea(s)", nota)

    def test_ya_fusionada_por_ff_sigue_midiendo_lo_suyo(self):
        """Tras el ff la rama entera está dentro de main: el merge-base ya no dice nada."""
        self.rama_con_su_trabajo()
        self.main_avanza_con_lo_ajeno()
        self.git("checkout", self.rama)
        self.git("rebase", "main")
        base_rebasada = self.sha("main")
        self.git("checkout", "main")
        self.git("merge", "--ff-only", self.rama)

        problema, nota = self.puerta(base_rebasada)

        self.assertIsNone(problema, problema)
        self.assertIn("1 fichero(s)", nota)

    def test_un_directo_desbordado_de_verdad_sigue_cantandose(self):
        """El arreglo no puede apagar la puerta: 14 ficheros propios siguen desbordando."""
        self.git("checkout", "-b", self.rama)
        for indice in range(14):
            (self.repo / f"propio_{indice:02d}.py").write_text(
                "\n".join(f"linea {n}" for n in range(70)) + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", f"{self.rama}: demasiado para un directo")
        self.git("checkout", "main")

        problema, _ = self.puerta(self.base_despacho)

        self.assertIsNotNone(problema)
        self.assertIn("14 ficheros", problema)


class PuertaPrefusionTest(unittest.TestCase):
    """B · R2 — antes del ff: rama rebasada y guardianes en verde sobre el árbol rebasado."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="prefusion-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "codigo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "app.py").write_text("v1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")
        self.rama = "049-guardian-de-salidas"
        self.git("checkout", "-b", self.rama)
        (self.repo / "app.py").write_text("v2\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", f"{self.rama}: el arreglo")
        self.git("checkout", "main")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    def main_avanza(self):
        (self.repo / "otro.py").write_text("rechazo mudo nuevo\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "061: main avanza entre el LIMPIO y el ff")

    def rebasar(self):
        self.git("checkout", self.rama)
        self.git("rebase", "main")
        self.git("checkout", "main")

    def test_rama_sin_rebasar_falla_y_nombra_su_salida(self):
        self.main_avanza()

        problemas, _ = unidad.puerta_prefusion(
            self.repo, self.rama, "main", guardian=lambda: (True, "0 FAIL · 0 WARN"))

        self.assertTrue(problemas)
        texto = "\n".join(problemas)
        self.assertIn(f"git -C worktrees/{self.rama} rebase main", texto)

    def test_guardian_rojo_sobre_el_arbol_rebasado_falla_y_nombra_su_salida(self):
        self.main_avanza()
        self.rebasar()
        rojo = ("  FAIL hay rechazos que no nombran su salida y no estaban congelados\n"
                "1 FAIL · 0 WARN")

        problemas, _ = unidad.puerta_prefusion(
            self.repo, self.rama, "main", guardian=lambda: (False, rojo))

        self.assertTrue(problemas)
        texto = "\n".join(problemas)
        self.assertIn("hay rechazos que no nombran su salida", texto)
        self.assertIn("lint_metodo.py", texto)

    def test_rebasada_y_en_verde_deja_pasar(self):
        self.main_avanza()
        self.rebasar()

        problemas, notas = unidad.puerta_prefusion(
            self.repo, self.rama, "main", guardian=lambda: (True, "0 FAIL · 0 WARN"))

        self.assertEqual([], problemas)
        self.assertTrue(any("rebasada" in nota for nota in notas))


class ComandoPrefusionTest(unittest.TestCase):
    """El paso 3 del ritual, tal y como lo teclea el padre: `unidad.py prefusion NNN-slug`."""

    RAMA = "066-cierre-base-tras-rebase-y-guardianes"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cmd-prefusion-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()  # macOS: /var → /private/var
        (self.raiz / "worktrees").mkdir()
        (self.raiz / "docs/bugs").mkdir(parents=True)
        (self.raiz / "docs/bugs" / f"{self.RAMA}.md").write_text(
            f"---\nunidad: {self.RAMA}\ntipo: bug\ncarril: normal\nestado: en_revision\n"
            f"aprobado: 2026-08-25\nficheros: []\npeticiones: []\n"
            f"actualizado: 2026-08-25\n---\n\n# 066 · BUG\n",
            encoding="utf-8",
        )
        self.repo = self.raiz / "main"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "app.py").write_text("v1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")
        self.git("checkout", "-b", self.RAMA)
        (self.repo / "app.py").write_text("v2\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", f"{self.RAMA}: el arreglo")
        self.git("checkout", "main")
        (self.repo / "otro.py").write_text("main avanza\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "061: main avanza entre el LIMPIO y el ff")
        for atributo, valor in (
            ("RAIZ", self.raiz),
            ("TRABAJO", self.raiz / "docs/05-trabajo"),
            ("ARCHIVO", self.raiz / "docs/05-trabajo/archivo"),
            ("BUGS", self.raiz / "docs/bugs"),
            ("WORKTREES", self.raiz / "worktrees"),
        ):
            anterior = getattr(unidad, atributo)
            setattr(unidad, atributo, valor)
            self.addCleanup(setattr, unidad, atributo, anterior)
        anterior_repo = unidad.repo_codigo
        unidad.repo_codigo = lambda: (self.repo, "main")
        self.addCleanup(setattr, unidad, "repo_codigo", anterior_repo)

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    def ejecutar(self, guardian):
        anterior = unidad.guardian_del_metodo
        unidad.guardian_del_metodo = guardian
        salida, errores = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
                codigo = unidad.cmd_prefusion(
                    argparse.Namespace(unidad=self.RAMA))
        finally:
            unidad.guardian_del_metodo = anterior
        return codigo, salida.getvalue() + errores.getvalue()

    def test_sin_rebasar_bloquea_la_fusion_y_dice_como_salir(self):
        codigo, texto = self.ejecutar(lambda: (True, "0 FAIL · 0 WARN"))

        self.assertEqual(1, codigo)
        self.assertIn("FUSIÓN BLOQUEADA", texto)
        self.assertIn(f"git -C worktrees/{self.RAMA} rebase main", texto)

    def test_rebasada_y_verde_autoriza_el_ff(self):
        self.git("checkout", self.RAMA)
        self.git("rebase", "main")
        self.git("checkout", "main")

        codigo, texto = self.ejecutar(lambda: (True, "0 FAIL · 0 WARN"))

        self.assertEqual(0, codigo)
        self.assertIn(f"merge --ff-only {self.RAMA}", texto)


class ReRegistroDeBaseTest(unittest.TestCase):
    """R1 · el re-registro conserva la base original del despacho."""

    PID = "P-20260825-5acf8ea5"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="re-registro-base-")
        self.addCleanup(self.tmp.cleanup)
        raiz = Path(self.tmp.name)
        self.peticiones = raiz / "docs/05-trabajo/peticiones"
        self.locks = raiz / ".runtime/locks"
        for atributo, valor in (("PETICIONES", self.peticiones), ("LOCKS", self.locks),
                                ("RAIZ", raiz)):
            anterior = getattr(gestion_peticiones, atributo)
            setattr(gestion_peticiones, atributo, valor)
            self.addCleanup(setattr, gestion_peticiones, atributo, anterior)
        ruta = self.peticiones / self.PID / "peticion.json"
        ruta.parent.mkdir(parents=True)
        ruta.write_text(json.dumps({
            "formato": 1, "id": self.PID, "estado": "encaminada", "revision": 1,
            "procesos": [{
                "tipo": "bug", "ref": "066-cierre-base-tras-rebase-y-guardianes",
                "revision": 1,
                "metadata": {"carril": "normal", "base_sha": "a" * 40, "principal": "main"},
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.ruta = ruta

    def metadata(self):
        datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        return datos["procesos"][0]["metadata"]

    def test_re_registro_mueve_la_original_y_no_la_pisa_dos_veces(self):
        tocadas = unidad.re_registrar_base(
            [f"{self.PID}@1"], "bug", "066-cierre-base-tras-rebase-y-guardianes", "b" * 40)

        self.assertEqual([self.PID], tocadas)
        self.assertEqual("b" * 40, self.metadata()["base_sha"])
        self.assertEqual("a" * 40, self.metadata()["base_sha_despacho_original"])

        unidad.re_registrar_base(
            [f"{self.PID}@1"], "bug", "066-cierre-base-tras-rebase-y-guardianes", "c" * 40)

        self.assertEqual("c" * 40, self.metadata()["base_sha"])
        self.assertEqual("a" * 40, self.metadata()["base_sha_despacho_original"],
                         "la base del despacho original no se pierde en un segundo rebase")


if __name__ == "__main__":
    unittest.main()
