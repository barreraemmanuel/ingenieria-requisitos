"""Bug 084 (hotfix, ADR-033): el constructor de normal/completo es un subagente DEL PADRE.

Hasta la 1.8.1 el «siguiente paso» de `unidad.py despachar` en carril normal/completo era un
`ejecucion.py lanzar … --rol constructor`: un proceso `claude -p` aparte, sin visibilidad ni
canal de vuelta, que el padre solo podía vigilar por su recibo. Nate lo paró en cuanto lo vio
(26-08-2026). Desde ahora el despacho entrega el ENCARGO para un subagente del propio padre
(worktree de la unidad, modelo y esfuerzo de la tabla de la regla 10) y la prosa del método
deja de mandar `ejecucion.py` para construir. `ejecucion.py` sigue siendo el lanzador del
REVISOR (su recibo es lo que acredita la firma) y una vía opcional para Codex o sesiones
desatendidas.
"""
import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
METODO = RAIZ / "plantilla/docs/00-metodo"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config  # noqa: E402

import test_peticion_unidad as base  # noqa: E402 - módulo hermano; no se importa la clase para no re-descubrir sus tests aquí


class DespachoEntregaSubagenteDelPadre(unittest.TestCase):
    """R1: el despacho de normal/completo imprime el encargo del subagente, no un `claude -p`.

    Reutiliza el workspace real de `PeticionUnidadTest` por composición (heredar re-ejecutaría
    sus 80 tests aquí).
    """

    def setUp(self):
        self.ws_test = base.PeticionUnidadTest("test_no_crea_unidad_sin_peticion_de_origen")
        self.ws_test.setUp()
        self.addCleanup(self.ws_test.tearDown)

    def despachar_normal(self):
        t = self.ws_test
        pid = t.capturar()
        t.evaluar(pid)
        creada = t.ejecutar(t.unidad, "nueva", "feature", "lanzamiento", "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stderr)
        t.aprobar_para_despacho("001-lanzamiento")
        resultado = t.ejecutar(t.unidad, "despachar", "001-lanzamiento")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return resultado.stdout

    def test_despacho_normal_no_manda_lanzar_un_constructor_por_ejecucion(self):
        salida = self.despachar_normal()
        self.assertNotIn("--rol constructor", salida)
        self.assertNotRegex(salida, r"ejecucion\.py lanzar \S+ --harness \S+ --rol constructor")

    def test_despacho_normal_entrega_el_encargo_del_subagente_del_padre(self):
        salida = self.despachar_normal()
        plan = repo_config.plan_de_modelo("normal", "constructor")
        self.assertIn("subagente del padre", salida.lower())
        self.assertIn("worktrees/001-lanzamiento", salida)
        self.assertIn(f"modelo {plan.modelo}", salida)
        self.assertIn(f"esfuerzo {plan.esfuerzo}", salida)
        # el revisor NO cambia: sigue siendo fresco y por el lanzador, para que deje recibo
        self.assertIn("--rol revisor", salida)


class LaProsaDelMetodoYaNoMandaClaudeP(unittest.TestCase):
    """R2: ninguna regla ni runbook manda construir por `ejecucion.py`."""

    def texto(self, rel):
        return (RAIZ / rel).read_text(encoding="utf-8")

    def test_regla_1_construye_un_subagente_del_padre(self):
        agents = self.texto("plantilla/AGENTS.md")
        regla_1 = re.search(r"^1\. \*\*Quién construye.*?(?=^2\. )", agents, re.S | re.M).group(0)
        self.assertNotIn("subagente constructor por `scripts/ejecucion.py`", regla_1)
        self.assertIn("subagente del propio padre", regla_1)
        # el revisor sí sigue por el lanzador: es lo que deja recibo
        self.assertIn("revisor", regla_1)

    def test_regla_15_no_obliga_a_pasar_por_ejecucion(self):
        agents = self.texto("plantilla/AGENTS.md")
        regla_15 = re.search(r"^15\. \*\*Proceso nativo.*?(?=^16\. )", agents, re.S | re.M).group(0)
        self.assertNotIn("Todo agente delegado pasa por `ejecucion.py`", regla_15)
        self.assertIn("ADR-033", regla_15)

    def test_roles_y_runbooks_no_mandan_construir_por_ejecucion(self):
        for rel in ("plantilla/docs/00-metodo/roles.md",
                    "plantilla/docs/00-metodo/runbooks/feature.md",
                    "plantilla/docs/00-metodo/runbooks/bug.md",
                    "plantilla/docs/00-metodo/sandbox.md",
                    "plantilla/docs/00-metodo/README.md"):
            texto = self.texto(rel)
            self.assertNotRegex(
                texto, r"exclusivamente con\s+`docs/00-metodo/scripts/ejecucion\.py`",
                f"{rel} sigue obligando a construir por ejecucion.py")
            self.assertNotIn("control plane obligatorio", texto, rel)
            self.assertNotIn("la única entrada para lanzar constructores", texto, rel)

    def test_el_adr_033_existe_y_viaja_en_el_bootstrap(self):
        adr = METODO / "decisiones/033-el-constructor-es-un-subagente-del-padre.md"
        self.assertTrue(adr.exists(), adr)
        cuerpo = adr.read_text(encoding="utf-8")
        self.assertIn("Supera", cuerpo)
        self.assertIn("ADR-022", cuerpo)
        bootstrap = (RAIZ / "visor/bootstrap.py").read_text(encoding="utf-8")
        self.assertIn('"033-el-constructor-es-un-subagente-del-padre.md"', bootstrap)


if __name__ == "__main__":
    unittest.main()
