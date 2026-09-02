"""Bug 113: el recibo del revisor sale sin `revisado_patch_id` ni `ronda` con la rama fusionada.

`ejecucion.py lanzar --rol revisor` sella la huella del contenido que el revisor tiene
delante (068) calculando `git patch-id` del diff `merge-base(principal, HEAD)..HEAD`. Con la
rama YA dentro de la principal (ronda 2 tras el ff del cierre) `merge-base == HEAD`, el diff
sale vacío y el recibo queda con `revisado_patch_id: null` y `ronda: null`, indistinguible de
«se me olvidó» (docs/bugs/113-recibo-del-revisor-sin-patch-id.md).

Lo que fija este fichero:
- R1: fusionada por ff y con base de despacho registrada → patch-id del diff base..HEAD.
- R1: fusionada por merge (sin base registrada) → patch-id contra el primer padre del merge.
- R2: sin nada que revisar → `""` y un motivo legible, que el recibo lleva en `motivo_patch_id`.
- R3: el recibo del revisor lleva la `ronda` que declara la cabecera de `hallazgos.md`.
- NO cambia: rama no fusionada → el mismo patch-id de siempre (merge-base..HEAD).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import ejecucion  # noqa: E402  (el REAL, sin mutar)


def git(cwd, *args, entrada=None):
    resultado = subprocess.run(
        ["git", *args], cwd=str(cwd), text=True, encoding="utf-8", capture_output=True,
        input=entrada, check=False,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"},
    )
    if resultado.returncode:
        raise AssertionError(f"git {' '.join(args)} → {resultado.returncode}: "
                             f"{resultado.stdout}{resultado.stderr}")
    return resultado.stdout.strip()


def patch_id_esperado(repo, base, punta):
    diff = subprocess.run(["git", "diff", base, punta], cwd=str(repo), capture_output=True,
                          check=True).stdout
    salida = subprocess.run(["git", "patch-id", "--stable"], cwd=str(repo), input=diff,
                            capture_output=True, check=True).stdout
    return salida.decode("utf-8").split()[0]


class RamaFusionadaTest(unittest.TestCase):
    """Repo temporal con `main` y la rama `001-demo`; el worktree apunta a la rama."""

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="bug-113-")
        self.addCleanup(self.temporal.cleanup)
        self.repo = Path(self.temporal.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("print('v1')\n", encoding="utf-8")
        git(self.repo, "add", "app.py")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "-b", "001-demo")
        (self.repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
        git(self.repo, "commit", "-q", "-am", "001-demo: cambio")
        self.punta = git(self.repo, "rev-parse", "HEAD")
        # El lanzador pregunta a repo_config cuál es la principal; aquí es `main` a secas.
        parche = mock.patch.object(ejecucion.repo_config, "repo_code",
                                   return_value=(self.repo, "main"))
        parche.start()
        self.addCleanup(parche.stop)

    def fusionar_por_ff(self):
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--ff-only", "001-demo")
        git(self.repo, "checkout", "-q", "001-demo")
        self.assertEqual(git(self.repo, "merge-base", "main", "HEAD"), self.punta,
                         "precondición del bug: merge-base == HEAD")

    # --- NO cambia: rama sin fusionar --------------------------------------------------
    def test_rama_no_fusionada_conserva_el_patch_id_de_siempre(self):
        esperado = patch_id_esperado(self.repo, self.base, "HEAD")
        self.assertEqual(ejecucion.patch_id_de_la_rama(self.repo), esperado)
        patch_id, motivo = ejecucion.patch_id_y_motivo(self.repo)
        self.assertEqual(patch_id, esperado)
        self.assertIn("merge-base", motivo)

    # --- El SÍNTOMA, con la API de siempre: rama dentro de la principal → ancla vacía ----
    def test_sintoma_113_rama_fusionada_devuelve_ancla_vacia(self):
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "otro.txt").write_text("ajeno\n", encoding="utf-8")
        git(self.repo, "add", "otro.txt")
        git(self.repo, "commit", "-q", "-m", "main avanza")
        primer_padre = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge 001-demo", "001-demo")
        git(self.repo, "branch", "-f", "001-demo", "HEAD")
        git(self.repo, "checkout", "-q", "001-demo")
        self.assertEqual(git(self.repo, "merge-base", "main", "HEAD"),
                         git(self.repo, "rev-parse", "HEAD"),
                         "precondición del bug: merge-base == HEAD")
        self.assertEqual(
            ejecucion.patch_id_de_la_rama(self.repo),
            patch_id_esperado(self.repo, primer_padre, "HEAD"),
            "bug 113: con la rama ya en la principal, el lanzador devolvía \"\" y el recibo "
            "del revisor salía con revisado_patch_id: null",
        )

    # --- R1: fusionada por ff, base de despacho registrada -----------------------------
    def test_rama_fusionada_por_ff_usa_la_base_de_despacho_registrada(self):
        self.fusionar_por_ff()
        esperado = patch_id_esperado(self.repo, self.base, "HEAD")
        patch_id, motivo = ejecucion.patch_id_y_motivo(self.repo, base_registrada=self.base)
        self.assertEqual(patch_id, esperado,
                         "bug 113: con la rama ya en la principal el ancla salía vacía")
        self.assertIn(self.base[:8], motivo)
        self.assertIn("base de despacho registrada", motivo)
        # La firma de siempre (sin motivo) también deja de salir vacía.
        self.assertEqual(ejecucion.patch_id_de_la_rama(self.repo, base_registrada=self.base),
                         esperado)

    # --- R1: fusionada por merge (no ff), sin base registrada → primer padre ------------
    def test_rama_fusionada_por_merge_usa_el_primer_padre_del_merge(self):
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "otro.txt").write_text("ajeno\n", encoding="utf-8")
        git(self.repo, "add", "otro.txt")
        git(self.repo, "commit", "-q", "-m", "main avanza")
        primer_padre = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge 001-demo", "001-demo")
        git(self.repo, "branch", "-f", "001-demo", "HEAD")
        git(self.repo, "checkout", "-q", "001-demo")
        self.assertEqual(git(self.repo, "merge-base", "main", "HEAD"),
                         git(self.repo, "rev-parse", "HEAD"))
        esperado = patch_id_esperado(self.repo, primer_padre, "HEAD")
        patch_id, motivo = ejecucion.patch_id_y_motivo(self.repo)
        self.assertEqual(patch_id, esperado)
        self.assertIn("primer padre", motivo)

    # --- R2: de verdad no hay nada que revisar → vacío CON motivo -----------------------
    def test_sin_diff_que_revisar_deja_motivo_legible(self):
        self.fusionar_por_ff()
        patch_id, motivo = ejecucion.patch_id_y_motivo(self.repo)  # sin base, sin merge
        self.assertEqual(patch_id, "")
        self.assertTrue(motivo.strip(), "R2: un null mudo no vale")
        self.assertIn("fusionada", motivo)
        # Una base registrada que no es antecesora tampoco vale, y se dice.
        patch_id, motivo = ejecucion.patch_id_y_motivo(self.repo, base_registrada="0" * 40)
        self.assertEqual(patch_id, "")
        self.assertTrue(motivo.strip())

    # --- R2/R3: el recibo lleva motivo y ronda --------------------------------------------
    def test_el_recibo_lleva_motivo_del_patch_id_y_la_ronda_de_la_cabecera(self):
        args = mock.Mock(unidad="001-demo", harness="claude", rol="revisor",
                         skill_tecnica=[], modelo=None)
        recibo = ejecucion.recibo_inicial(
            args, "abc", self.repo, "sesion", {}, {}, patch_id="", ronda=None,
            motivo_patch_id="rama fusionada: sin base",
        )
        self.assertIsNone(recibo["revisado_patch_id"])
        self.assertEqual(recibo["motivo_patch_id"], "rama fusionada: sin base")
        recibo = ejecucion.recibo_inicial(
            args, "abc", self.repo, "sesion", {}, {}, patch_id="deadbeef", ronda=2,
        )
        self.assertEqual(recibo["revisado_patch_id"], "deadbeef")
        self.assertIsNone(recibo["motivo_patch_id"])
        self.assertEqual(recibo["ronda"], 2)
        # R3: la ronda del revisor sale de la cabecera de hallazgos.md.
        self.assertEqual(ejecucion.ronda_declarada("---\nronda: 2\n---\n"), 2)
        self.assertIsNone(ejecucion.ronda_declarada("---\nrevisor: no\n---\n"))
        self.assertIsNone(ejecucion.ronda_declarada("---\nronda: —\n---\n"))

    # --- R1 de punta a punta: la ficha REAL (`frontmatter()`) → petición → base → ancla ---
    def test_la_base_registrada_se_lee_de_la_ficha_real_y_ancla_el_ff(self):
        """Ronda 2 (H1 del revisor): `frontmatter()` devuelve `peticiones` con corchetes
        (`[P-…@1]`); sin limpiarlos, `parsear_referencias` lo rechazaba y la vía principal
        de R1 se quedaba en «sin base registrada» justo en el caso ff de 107/108."""
        self.fusionar_por_ff()
        ws = Path(self.temporal.name).resolve() / "ws"   # macOS: /var → /private/var
        ficha = ws / "docs/bugs/001-demo.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nunidad: 001-demo\ntipo: bug\nestado: en_validacion\n"
            "peticiones: [P-20260827-25ca49dc@1]            # referencias P-ID@revision\n"
            "---\n# Bug\n",
            encoding="utf-8",
        )
        with mock.patch.object(ejecucion, "RAIZ", ws):
            datos = ejecucion.frontmatter(ficha)   # el parser real, no un dict a mano
            self.assertEqual(datos["peticiones"], "[P-20260827-25ca49dc@1]")
            import peticion as gestion_peticiones
            registro = {"procesos": [{
                "tipo": "bug", "ref": "001-demo", "revision": 1,
                "metadata": {"base_sha": self.base},
            }]}
            with mock.patch.object(gestion_peticiones, "cargar", return_value=registro):
                base = ejecucion.base_registrada_de_la_unidad(datos, "001-demo", ficha)
        self.assertEqual(base, self.base)
        patch_id, motivo = ejecucion.patch_id_y_motivo(self.repo, base_registrada=base)
        self.assertEqual(patch_id, patch_id_esperado(self.repo, self.base, "HEAD"))
        self.assertIn("base de despacho registrada", motivo)


# ---------------------------------------------------------------------------- bug 117
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
from test_ejecucion_control_plane import ControlPlaneE2ETest  # noqa: E402


class AnclaDelRevisorEnFichaDeBugTest(ControlPlaneE2ETest):
    """Bug 117: con la ficha en `docs/bugs/` el lanzador no calculaba el ancla del revisor.

    El cálculo (068/113) vivía en la rama `else` de las unidades de `_lanzar_bajo_lease`;
    para un bug —que no tiene `hallazgos.md` aparte— nunca se ejecutaba y el recibo salía
    con `revisado_patch_id: null` aunque la rama tuviera diff (recibos de 113 y 114 del
    27-08). Aquí se lanza el revisor DE VERDAD (doble de harness) sobre una ficha de bug con
    trabajo propio en la rama y se mira el recibo.
    """

    def setUp(self):
        super().setUp()
        # La ficha pasa a ser la de un BUG: docs/bugs/001-demo.md, sin hallazgos.md.
        vieja = self.ws / "docs/05-trabajo" / self.unidad
        self.ficha = self.ws / "docs/bugs" / f"{self.unidad}.md"
        self.ficha.parent.mkdir(parents=True, exist_ok=True)
        self.ficha.write_text(
            "---\nunidad: 001-demo\ntipo: bug\ncarril: normal\nestado: en_revision\n"
            "ficheros: [app/demo.py]\n---\n# Bug demo\n",
            encoding="utf-8",
        )
        import shutil as _shutil
        _shutil.rmtree(vieja)
        (self.worktree / "app").mkdir(parents=True, exist_ok=True)
        (self.worktree / "app/demo.py").write_text("print('arreglo')\n", encoding="utf-8")
        self.git("add", "app/demo.py", cwd=self.worktree)
        self.git("commit", "-m", "001-demo: el arreglo", cwd=self.worktree)

    def recibo(self):
        # Se descarta el recibo de entrega que siembra el fixture (147) por su id, no por
        # su rol: aquí también se lanza un constructor y su recibo es el que se mira.
        recibos = [r for r in (self.ws / ".runtime/ejecuciones").glob("001-demo-*.json")
                   if json.loads(r.read_text(encoding="utf-8")).get("id")
                   != "entrega-fixture"]
        self.assertEqual(len(recibos), 1, recibos)
        return json.loads(recibos[0].read_text(encoding="utf-8"))

    def test_el_recibo_del_revisor_de_un_bug_lleva_el_ancla(self):
        resultado = self.ejecutar(rol="revisor")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        recibo = self.recibo()
        self.assertEqual(
            recibo["revisado_patch_id"],
            patch_id_esperado(self.worktree, "main", "HEAD"),
            "bug 117: el ancla del revisor no se calculaba para fichas de docs/bugs/ "
            f"(motivo_patch_id={recibo.get('motivo_patch_id')!r})",
        )
        self.assertIsNone(recibo["motivo_patch_id"])
        # R2: la ficha de bug no lleva contador de rondas → None, y se dice por qué.
        self.assertIsNone(recibo["ronda"])
        self.assertIn("no lleva contador", recibo.get("motivo_ronda") or "")

    def test_el_constructor_de_un_bug_sigue_sin_ancla(self):
        """NO cambia: el ancla es del revisor; el constructor no la lleva ni la sella."""
        self.ficha.write_text(self.ficha.read_text(encoding="utf-8").replace(
            "estado: en_revision", "estado: en_obra"), encoding="utf-8")
        resultado = self.ejecutar(rol="constructor")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIsNone(self.recibo()["revisado_patch_id"])


# Se hereda la INFRAESTRUCTURA (workspace, repo, dobles de harness), no sus tests: los de
# la clase base ya corren en su propio fichero y aquí solo estorbarían.
for _nombre in dir(ControlPlaneE2ETest):
    if _nombre.startswith("test_") and _nombre not in AnclaDelRevisorEnFichaDeBugTest.__dict__:
        setattr(AnclaDelRevisorEnFichaDeBugTest, _nombre, None)


if __name__ == "__main__":
    unittest.main()
