"""149 · el mismo guardián, pero contra el corpus ENTERO de este taller (R4).

La fixture pública es una muestra adjudicada a mano; el corpus son las ~11.500 llamadas a
Bash/Edit/Write que los agentes de este taller han tecleado de verdad (49 sesiones + 155
subagentes de Claude Code, más los `exec` en claro de Codex). Vive fuera de git —lleva prosa
de bugs, nombres y correos— y se regenera en la máquina del dueño:

    python3 visor/tests/extraer_replay.py --privado

**Si el corpus no está, este test FALLA; no se salta.** Un `skip` silencioso es otro test
verde: la línea base dejaría de medirse sin que nadie lo decidiera.

Lo que congela: (a) ninguna de las escrituras reales en `main/` adjudicadas se escapa;
(b) el número total de `deny` no sube del tope adjudicado el día de la extracción — un `deny`
nuevo es un caso que hay que adjudicar a mano y meter en la fixture pública, no un rojo que se
sube de tope; (c) todo `deny` y todo `aviso` dicen cómo salir.
"""

import importlib.util
import json
import os
import re
import unittest
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
GUARDIAN = RAIZ / "plantilla/docs/00-metodo/scripts/guardian_rutas.py"
EXTRACTOR = RAIZ / "visor/tests/extraer_replay.py"
FIXTURE = RAIZ / "visor/tests/fixtures/reforma/comandos-adjudicados.jsonl"

# Linea base MEDIDA el 2026-09-02 sobre las 12.397 llamadas reales del taller (el detalle,
# en hallazgos.md de la 149). Los topes solo pueden ENCOGER: si suben, hay un `deny` sin
# adjudicar, y eso se arregla adjudicandolo a mano en la fixture publica, no subiendo el
# numero.
#
# Van partidos en dos a proposito, porque son dos hechos distintos y solo uno es un
# guardian funcionando:
#
#   · 38 son el `git -C main merge --no-ff|--squash` del paso 3 del cierre sin `gh`. ADR-009
#     acota esa excepcion a `merge --ff-only` (`runbooks/cierre.md:28`), asi que el guardian,
#     tal y como lo define R1, los para. Es EL hallazgo de esta unidad: el hook del arreglo 2
#     no se puede desplegar como bloqueo sin decidir antes que pasa con el cierre.
#   · 7 es todo lo demas en 12.397 llamadas: 6 escrituras reales en `main/` (las que la
#     unidad tenia que cazar) y 1 falso conocido y nombrado (`bd7fc86ea797`, ver hallazgos).
#
# Un solo tope de 45 dejaria crecer la segunda cuenta a costa de la primera sin que se note.
TOPE_DENY_CIERRE = 38
TOPE_DENY_OTROS = 7
TOPE_AVISO_POR_MIL = 40      # avisos por cada 1.000 llamadas; hoy ~6

# El merge del cierre sin `gh`: la excepcion nombrada de ADR-009.
MERGE_DEL_CIERRE = re.compile(r"git\s+-C\s+\S*main\S*\s+merge\s+--(?:no-ff|squash)")


def _categoria(decision):
    """La familia del rechazo: el trozo del motivo anterior a los dos puntos."""
    return (decision.motivo or "").split(":")[0][:40]


def _cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class ReplayDelCorpus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.guardian = _cargar("guardian_rutas", GUARDIAN)
        cls.extractor = _cargar("extraer_replay", EXTRACTOR)
        cls.corpus_path = cls.extractor.ruta_corpus()
        cls.registros = []
        if cls.corpus_path.exists():
            for linea in cls.corpus_path.read_text(encoding="utf-8").splitlines():
                linea = linea.strip()
                if linea:
                    cls.registros.append(json.loads(linea))

    def setUp(self):
        if not self.corpus_path.exists():
            self.fail(
                f"no existe {self.corpus_path}: el corpus no se guarda en git. "
                "Regenéralo con `python3 visor/tests/extraer_replay.py --privado`")

    def _decisiones(self):
        for registro in self.registros:
            decision = self.guardian.decidir(
                registro["tool"], registro["entrada"], registro["cwd"],
                registro.get("raiz") or self.extractor.raiz_taller())
            yield registro, decision

    def test_tabla_de_disparos(self):
        """Imprime la tabla que exige la especificación y congela los topes."""
        cuenta = Counter()
        denies, avisos, cierres = [], [], []
        for registro, decision in self._decisiones():
            cuenta[decision.veredicto] += 1
            if decision.veredicto == "deny":
                cuenta["motivo:" + _categoria(decision)] += 1
                if MERGE_DEL_CIERRE.search(str(registro["entrada"])):
                    cierres.append((registro, decision))
                else:
                    denies.append((registro, decision))
            elif decision.veredicto == "aviso":
                avisos.append((registro, decision))
        total = len(self.registros)
        print(f"\n== replay del corpus ({total} llamadas, {self.corpus_path}) ==")
        for clave in sorted(cuenta):
            print(f"  {clave:28} {cuenta[clave]}")
        print(f"  -- deny del cierre sin gh (ADR-009): {len(cierres)} --")
        print(f"  -- deny, todo lo demas ({len(denies)}, uno a uno) --")
        for registro, decision in denies:
            print(f"    {registro['id']} {registro['sesion']} {_categoria(decision)}: "
                  f"{str(registro['entrada'])[:110]}")
        print(f"  -- aviso: {len(avisos)} (muestra de 10) --")
        for registro, decision in avisos[:10]:
            print(f"    {registro['id']}: {str(registro['entrada'])[:110]}")
        self.assertGreater(total, 5000, "el corpus extraído parece incompleto")
        self.assertLessEqual(
            len(denies), TOPE_DENY_OTROS,
            "hay `deny` nuevos sin adjudicar fuera del merge del cierre: metelos en "
            "comandos-adjudicados.jsonl (o arregla el guardian), no subas el tope")
        self.assertLessEqual(
            len(cierres), TOPE_DENY_CIERRE,
            "el guardian para mas merges del cierre que el dia que se midio")
        self.assertLessEqual(len(avisos) * 1000 // max(total, 1), TOPE_AVISO_POR_MIL)

    def test_no_se_escapa_ninguna_escritura_real_adjudicada(self):
        """Las escrituras reales de la fixture pública, buscadas en el corpus por su id."""
        adjudicadas = {}
        for linea in FIXTURE.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            caso = json.loads(linea)
            if caso["categoria"] == "escritura_real" and caso["origen"] != "sintetico":
                adjudicadas[caso["origen"]] = caso
        self.assertGreaterEqual(len(adjudicadas), 5,
                                "la fixture debe traer escrituras reales con origen")
        por_id = {r["id"]: r for r in self.registros}
        perdidas, escapes = [], []
        for origen, caso in adjudicadas.items():
            registro = por_id.get(origen)
            if registro is None:
                perdidas.append(origen)
                continue
            decision = self.guardian.decidir(
                registro["tool"], registro["entrada"], registro["cwd"],
                registro.get("raiz") or self.extractor.raiz_taller())
            if decision.veredicto != "deny":
                escapes.append((origen, str(registro["entrada"])[:90]))
        self.assertEqual([], escapes, f"escrituras reales que se escapan: {escapes}")
        self.assertEqual([], perdidas,
                         f"ids de la fixture que ya no están en el corpus: {perdidas}")

    def test_todo_rechazo_dice_como_salir(self):
        mudos = []
        for registro, decision in self._decisiones():
            if decision.veredicto in ("deny", "aviso"):
                if not (decision.motivo or "").strip() or not (decision.salida or "").strip():
                    mudos.append(registro["id"])
        self.assertEqual([], mudos, f"rechazos sin salida: {mudos[:20]}")

    def test_el_extractor_regenera_los_casos_publicos(self):
        """R2: cada caso real de la fixture pública sigue existiendo, igual, en el corpus."""
        desviados = []
        por_id = {r["id"]: r for r in self.registros}
        for linea in FIXTURE.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            caso = json.loads(linea)
            if caso["origen"] == "sintetico":
                continue
            registro = por_id.get(caso["origen"])
            if registro is None:
                desviados.append(f"{caso['id']}: id {caso['origen']} no está en el corpus")
            elif str(registro["entrada"]).strip() != str(caso["entrada"]).strip():
                desviados.append(f"{caso['id']}: el comando del corpus ya no coincide")
        self.assertEqual([], desviados, "\n".join(desviados))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    unittest.main()
