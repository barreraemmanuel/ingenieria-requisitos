"""149-replay-del-corpus-real · el guardián que mira ADÓNDE va un comando, medido contra lo real.

Contrato de `docs/05-trabajo/149-replay-del-corpus-real/especificacion.md`:

  R1  `guardian_rutas.decidir(herramienta, entrada, cwd, raiz)` devuelve
      `Decision(veredicto ∈ {deny, allow, aviso}, motivo, salida)`. Decide por la ruta
      RESUELTA (`realpath(cwd/token)`), no por la forma de escribir el comando.
  R2  la fixture `fixtures/reforma/comandos-adjudicados.jsonl` (≥150 casos) trae las
      escrituras reales en `main/` de los rollouts, los rodeos de verificación-02 §2,
      los comandos legítimos reales y los `rm -r` con rutas irresolubles.
  R3  umbrales fijos: recall 9/9 + 32/32 sobre lo prohibido, ≤2 falsos sobre lo legítimo,
      0 `deny` sobre los irresolubles (que son `aviso`), y cada `deny` con salida.
  R5  la fixture pública no lleva correos, ni la ruta de usuario real, ni nombres.

Por qué el umbral de falsos es tan estrecho: el filtro que el método ya tiene
(`canario.py:614-636`) alcanza recall 100 % sobre las escrituras reales, pero aplicado como
hook **~40 % de sus disparos son falsos** — dispara sobre el texto que CITA el comando dentro
de un heredoc. Un guardián que bloquea el trabajo legítimo se desinstala el primer día; por eso
el criterio portante no es el recall, es el recall CON los falsos por debajo de dos.
"""

import importlib.util
import json
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
GUARDIAN = RAIZ / "plantilla/docs/00-metodo/scripts/guardian_rutas.py"
FIXTURE = Path(__file__).parent / "fixtures" / "reforma" / "comandos-adjudicados.jsonl"

CATEGORIAS = ("escritura_real", "rodeo", "legitimo", "irresoluble")
CAMPOS = ("id", "herramienta", "entrada", "cwd", "raiz", "esperado", "categoria",
          "motivo", "origen")

# R5: lo que jamás puede viajar al repo público. `@` cubre cualquier correo; el resto son
# la ruta de usuario real y los nombres propios de este taller y de su gente.
PROHIBIDO = ("@", "/Users/nate", "nate", "gentile", "mastermind", "ijgentile",
             "claude-501")


def _cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _casos():
    casos = []
    for numero, linea in enumerate(FIXTURE.read_text(encoding="utf-8").splitlines(), 1):
        linea = linea.strip()
        if not linea or linea.startswith("//"):
            continue
        dato = json.loads(linea)
        dato["_linea"] = numero
        casos.append(dato)
    return casos


class GuardianRutas(unittest.TestCase):
    """R1: la decisión, caso a caso, con los ejemplos de la tabla «cómo lo pruebas tú»."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _cargar("guardian_rutas", GUARDIAN)
        cls.taller = "/Users/agente/Proyecto/taller"

    def decidir(self, entrada, cwd=None, herramienta="Bash"):
        return self.mod.decidir(herramienta, entrada, cwd or self.taller, self.taller)

    def test_veredicto_es_de_los_tres(self):
        for comando in ("ls", "rm -rf main/x", "rm -rf $D/visor"):
            self.assertIn(self.decidir(comando).veredicto, ("deny", "allow", "aviso"))

    def test_cd_a_main_y_borrar_es_deny_con_salida(self):
        decision = self.decidir("cd main && rm -rf visor/.runtime")
        self.assertEqual("deny", decision.veredicto)
        self.assertIn("ESCRIBIR EN main/", decision.motivo)
        self.assertTrue(decision.salida.strip())

    def test_lectura_en_main_es_allow(self):
        for comando in ("git -C main log --oneline -5",
                        "cp main/visor/tests/correr.py /tmp/",
                        "cd main && python3 visor/tests/correr.py",
                        "grep -rn deny main/visor"):
            self.assertEqual("allow", self.decidir(comando).veredicto, comando)

    def test_ruta_irresoluble_es_aviso_nunca_deny(self):
        decision = self.decidir("rm -rf $D/visor")
        self.assertEqual("aviso", decision.veredicto)
        self.assertIn("no puedo comprobar", decision.motivo)
        self.assertTrue(decision.salida.strip())

    def test_edit_bajo_main_es_deny(self):
        decision = self.decidir({"file_path": "main/visor/tests/correr.py"},
                                herramienta="Edit")
        self.assertEqual("deny", decision.veredicto)
        decision = self.decidir({"file_path": "visor/tests/correr.py"},
                                cwd=self.taller + "/worktrees/149-x", herramienta="Write")
        self.assertEqual("allow", decision.veredicto)

    def test_la_salida_nombra_un_camino_que_existe(self):
        decision = self.decidir("rm -rf main/visor/.runtime")
        self.assertTrue(re.search(r"\.runtime/|worktrees/", decision.salida),
                        decision.salida)


class UmbralesSobreLaFixture(unittest.TestCase):
    """R3: los números que deciden si el arreglo 2 se despliega como bloqueo o como aviso."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _cargar("guardian_rutas", GUARDIAN)
        cls.casos = _casos()

    def _veredictos(self, categoria):
        salida = []
        for caso in self.casos:
            if caso["categoria"] != categoria:
                continue
            decision = self.mod.decidir(caso["herramienta"], caso["entrada"],
                                        caso["cwd"], caso["raiz"])
            salida.append((caso, decision))
        return salida

    def test_fixture_tiene_los_casos_prometidos(self):
        self.assertGreaterEqual(len(self.casos), 150)
        cuenta = {c: 0 for c in CATEGORIAS}
        vistos = set()
        for caso in self.casos:
            self.assertIn(caso["categoria"], CATEGORIAS, caso)
            for campo in CAMPOS:
                self.assertIn(campo, caso, caso.get("id"))
            self.assertNotIn(caso["id"], vistos, "id repetido")
            vistos.add(caso["id"])
            cuenta[caso["categoria"]] += 1
        self.assertEqual(9, cuenta["escritura_real"])
        self.assertEqual(32, cuenta["rodeo"])
        self.assertGreaterEqual(cuenta["legitimo"], 60)
        self.assertEqual(24, cuenta["irresoluble"])

    def test_recall_sobre_las_escrituras_reales(self):
        pares = self._veredictos("escritura_real")
        escapes = [c["id"] for c, d in pares if d.veredicto != "deny"]
        self.assertEqual([], escapes, f"escrituras reales que se escapan: {escapes}")
        self.assertEqual(9, len(pares))

    def test_recall_sobre_los_rodeos(self):
        pares = self._veredictos("rodeo")
        escapes = [c["id"] for c, d in pares if d.veredicto != "deny"]
        self.assertEqual([], escapes, f"rodeos que se escapan: {escapes}")
        self.assertEqual(32, len(pares))

    def test_falsos_sobre_lo_legitimo(self):
        pares = self._veredictos("legitimo")
        falsos = [(c["id"], c["entrada"], d.motivo) for c, d in pares
                  if d.veredicto == "deny"]
        self.assertLessEqual(len(falsos), 2, f"falsos rojos: {falsos}")

    def test_los_irresolubles_avisan_y_no_bloquean(self):
        pares = self._veredictos("irresoluble")
        bloqueados = [c["id"] for c, d in pares if d.veredicto == "deny"]
        self.assertEqual([], bloqueados, f"irresolubles bloqueados: {bloqueados}")
        sin_aviso = [c["id"] for c, d in pares if d.veredicto != "aviso"]
        self.assertEqual([], sin_aviso, f"irresolubles sin aviso: {sin_aviso}")

    def test_cada_caso_sale_como_dice_su_adjudicacion(self):
        """El `esperado` de la fixture manda: adjudicado a mano, uno a uno."""
        fallos = []
        for caso in self.casos:
            decision = self.mod.decidir(caso["herramienta"], caso["entrada"],
                                        caso["cwd"], caso["raiz"])
            if decision.veredicto != caso["esperado"]:
                fallos.append(f"{caso['id']}: esperado {caso['esperado']}, "
                              f"dio {decision.veredicto} — {caso['entrada'][:70]}")
        self.assertEqual([], fallos, "\n".join(fallos))

    def test_todo_deny_y_todo_aviso_dicen_como_salir(self):
        mudos = []
        for caso in self.casos:
            decision = self.mod.decidir(caso["herramienta"], caso["entrada"],
                                        caso["cwd"], caso["raiz"])
            if decision.veredicto in ("deny", "aviso"):
                if not (decision.motivo or "").strip() or not (decision.salida or "").strip():
                    mudos.append(caso["id"])
        self.assertEqual([], mudos, f"rechazos sin salida: {mudos}")


class Anonimizacion(unittest.TestCase):
    """R5: el repo es público. La fixture se lee entera, en crudo."""

    def test_la_fixture_no_lleva_datos_del_dueno(self):
        crudo = FIXTURE.read_text(encoding="utf-8").lower()
        encontrados = [p for p in PROHIBIDO if p.lower() in crudo]
        self.assertEqual([], encontrados, f"datos privados en la fixture: {encontrados}")

    def test_el_readme_dice_cuando_y_con_que_se_regenera(self):
        readme = FIXTURE.parent / "README.md"
        texto = readme.read_text(encoding="utf-8")
        self.assertRegex(texto, r"\d{4}-\d{2}-\d{2}")
        self.assertIn("extraer_replay.py", texto)

    def test_el_extractor_anonimiza_en_origen(self):
        extractor = _cargar("extraer_replay", Path(__file__).parent / "extraer_replay.py")
        sucio = ("cd /Users/nate/Project/x && gam user nate" "@" "example.com show info")
        limpio = extractor.anonimizar(sucio)
        for patron in ("@", "/Users/nate"):
            self.assertNotIn(patron, limpio, limpio)


if __name__ == "__main__":
    unittest.main()
