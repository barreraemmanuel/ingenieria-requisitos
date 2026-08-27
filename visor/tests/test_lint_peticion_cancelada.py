"""ADR-034 §2: una petición entregada cuyo `satisface` incluye un proceso `cancelado`
no debe quedar en FAIL para siempre.

`lint_metodo.py` es incoherente consigo mismo: la comprobación de procesos `abiertos`
trata {terminal, sustituido, cancelado} como acabados, y doce líneas más abajo la de
`entregada` exige `terminal` para todos. `peticion.py` acepta los tres en sus tres
filtros y por eso deja cerrar la petición — así que el workspace se cierra bien y se
queda en rojo permanente, sin salida escrita: la definición de bug de ADR-026.

Caso real que lo destapó (P-20260818-24c59c2c): se abrió carril exprés para subir una
dependencia, el AGENTS.md del repo de código lo prohibía, se abandonó el exprés como
manda el método y se rehízo como unidad. Resultado: `cancelado` + `terminal`, entregada
de verdad, FAIL eterno.

Lo que este test NO relaja: un proceso VIVO (`evaluando`, `en obra`) sigue haciendo
fallar la petición entregada. Esa es la garantía que el gate protegía y se conserva.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts/lint_metodo.py"
DENUNCIA = "entregada con procesos no terminales"
PID = "P-20260818-24c59c2c"


class LintPeticionCanceladaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-cancelada-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / "docs/05-trabajo/peticiones" / PID).mkdir(parents=True)

    def proceso(self, tipo, ref, estado, contrato):
        return {
            "actualizado": "2026-08-18T20:50:48+00:00",
            "contrato_terminal": contrato,
            "estado": estado,
            "evidencia": "motivo escrito en el momento",
            "fecha": "2026-08-18T19:48:46+00:00",
            "ref": ref,
            "relacion": "satisface",
            "revision": 1,
            "tipo": tipo,
        }

    def escribir(self, procesos):
        datos = {
            "formato": 1,
            "id": PID,
            "creada": "2026-08-18T19:48:34+00:00",
            "actualizada": "2026-08-18T20:50:48+00:00",
            "original": "subir sqlparse por las CVE",
            "responsable": "padre",
            "estado": "cerrada",
            "resultado": "entregada",
            "revision": 1,
            "aclaraciones": [],
            "cierres": [],
            "evaluaciones": [],
            "procesos": procesos,
            "reclamos": [],
            "relaciones": [],
        }
        ruta = self.raiz / "docs/05-trabajo/peticiones" / PID / "peticion.json"
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

    def lint(self):
        resultado = subprocess.run(
            [sys.executable, str(SCRIPT), "--raiz", str(self.raiz)],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        return resultado.stdout + resultado.stderr

    def test_expres_cancelado_junto_a_la_unidad_que_si_entrego_no_denuncia(self):
        # El caso real: el carril se abandonó (cancelado, con su motivo) y el trabajo
        # se rehízo como unidad, que llegó a terminal. No queda NADA colgando.
        self.escribir([
            self.proceso("expres", f"expres-{PID}-sqlparse-060", "cancelado", "rama-expres-v1"),
            self.proceso("unidad", "004-sqlparse-al-dia", "terminal", "unidad-mergeada-v1"),
        ])
        self.assertNotIn(DENUNCIA, self.lint())

    def test_un_proceso_vivo_sigue_denunciando(self):
        # La garantía intacta: si algo sigue en obra, "entregada" es mentira y el
        # linter debe decirlo. Sin esto el arreglo sería una relajación, no una
        # corrección de coherencia.
        self.escribir([
            self.proceso("unidad", "004-sqlparse-al-dia", "en obra", "unidad-mergeada-v1"),
        ])
        self.assertIn(DENUNCIA, self.lint())

    def test_sustituido_solo_tampoco_denuncia(self):
        # `sustituido` ya estaba excluido del conjunto `satisface` aguas arriba; se fija
        # aquí para que un futuro refactor de ese filtro no lo pierda en silencio.
        self.escribir([
            self.proceso("unidad", "004-sqlparse-al-dia", "terminal", "unidad-mergeada-v1"),
            self.proceso("unidad", "003-intento-previo", "sustituido", "unidad-mergeada-v1"),
        ])
        self.assertNotIn(DENUNCIA, self.lint())


if __name__ == "__main__":
    unittest.main()
