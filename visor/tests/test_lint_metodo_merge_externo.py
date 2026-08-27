"""Bug 118: `lint_metodo.py` no conocía el proceso `merge-externo` (unidad 087).

`peticion.py enlazar --tipo merge-externo --ref <sha>` acepta un merge hecho fuera del método
y nace terminal; el lint, en cambio, no tenía `merge-externo` en sus contratos canónicos y
trataba la `ref` como una ruta de fichero: dos FAIL falsos permanentes por cada petición así
(`P-20260827-f7c22906`), que además bloquean `unidad.py prefusion`.
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
SCRIPTS = RAIZ_REPO / "plantilla/docs/00-metodo/scripts"
LINT = SCRIPTS / "lint_metodo.py"
PID = "P-20260827-0000ab12"


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout.strip()


class LintConoceElMergeExternoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-merge-externo-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        (self.raiz / "docs/00-metodo/scripts").mkdir(parents=True)
        (self.raiz / "docs/05-trabajo/peticiones").mkdir(parents=True)
        self.main = self.raiz / "main"
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        git(self.main, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q",
            "--allow-empty", "-m", "base")
        git(self.main, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q",
            "--allow-empty", "-m", "merge externo")
        self.sha = git(self.main, "rev-parse", "HEAD")
        (self.raiz / "docs/00-metodo/repos.yaml").write_text(
            "ruta_local: main/\nrama_principal: main\n", encoding="utf-8")

    def peticion(self, ref):
        carpeta = self.raiz / "docs/05-trabajo/peticiones" / PID
        carpeta.mkdir()
        (carpeta / "peticion.json").write_text(json.dumps({
            "id": PID, "formato": 1, "revision": 1, "estado": "encaminada",
            "original": {"autor": "t", "resumen": "x", "texto": "x"},
            "aclaraciones": [], "cierres": [], "evaluaciones": [], "reclamos": [],
            "relaciones": [], "responsable": None,
            "procesos": [{
                "tipo": "merge-externo", "ref": ref, "relacion": "satisface", "revision": 1,
                "estado": "terminal", "contrato_terminal": "merge-externo-v1",
                "evidencia": f"merge externo {ref}",
                "fecha": "2026-08-27T06:56:40+00:00",
                "fecha_terminal": "2026-08-27T06:56:40+00:00",
            }],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def lineas_del_pid(self):
        proceso = subprocess.run([sys.executable, str(LINT), "--raiz", str(self.raiz)],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace")
        salida = proceso.stdout + proceso.stderr
        return [l.strip() for l in salida.splitlines() if PID in l]

    def test_un_merge_externo_con_sha_real_no_da_ningun_fail(self):
        self.peticion(self.sha[:7])
        fails = [l for l in self.lineas_del_pid() if l.startswith("FAIL")]
        self.assertEqual(fails, [], "bug 118: FAIL falsos sobre un merge externo real")

    def test_un_merge_externo_por_pr_no_da_ningun_fail(self):
        self.peticion("#36")
        fails = [l for l in self.lineas_del_pid() if l.startswith("FAIL")]
        self.assertEqual(fails, [])

    def test_un_sha_que_no_esta_en_el_repo_da_un_fail_con_salida(self):
        self.peticion("0badc0ffee1")
        fails = [l for l in self.lineas_del_pid() if l.startswith("FAIL")]
        self.assertEqual(len(fails), 1, fails)
        self.assertIn("SALIDA:", fails[0])
        self.assertIn("0badc0ffee1", fails[0])

    def test_el_contrato_canonico_es_el_mismo_que_declara_peticion_py(self):
        lint = (SCRIPTS / "lint_metodo.py").read_text(encoding="utf-8")
        peticion = (SCRIPTS / "peticion.py").read_text(encoding="utf-8")
        en_peticion = re.search(r'"merge-externo":\s*"([^"]+)"', peticion)
        self.assertIsNotNone(en_peticion)
        en_lint = re.search(r'"merge-externo":\s*"([^"]+)"', lint)
        self.assertIsNotNone(en_lint, "bug 118: lint_metodo.py no tiene merge-externo en CONTRATOS_PETICION")
        self.assertEqual(en_lint.group(1), en_peticion.group(1))


if __name__ == "__main__":
    unittest.main()
