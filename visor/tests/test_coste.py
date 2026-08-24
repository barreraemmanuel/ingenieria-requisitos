"""048-medidor-de-coste · el medidor dice en qué se va el cupo, y deja comparar antes/después.

Lee lo que el harness YA escribe (`~/.claude/projects/*.jsonl`) y reparte el gasto. Cada
caso de aquí es una fila de §Verificación del contrato:

  R1  los cuatro ejes suman el 100 % y NO hay nota compuesta
  R2  la relectura se atribuye a cuatro orígenes; un `user` de solo `tool_result` es
      herramienta, no persona; y el prompt de sistema se declara fuera del rollout
  R3  el texto siempre cargado cuesta tamaño x turnos, y se imprime como % del total
  R4  la simulación del corte imprime SIEMPRE su supuesto
  R5  `--json` vuelca y `--linea-base` compara por eje y tokens por turno
  R6  sin rollouts / proyecto inexistente / línea base ilegible → falla NOMBRANDO el comando
  R7  un tramo sin datos se declara «sin sesiones tan largas», jamás `0.0x`
  R8  un turno es un `requestId`: los reintentos se cuentan una sola vez

Los rollouts son sintéticos y la raíz del harness se inyecta por entorno, como hace la
suite del canario: ni un test toca `~/.claude/`.
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
COSTE_PATH = RAIZ / "plantilla/docs/00-metodo/scripts/coste.py"


def _cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


coste = _cargar("coste_bajo_test", COSTE_PATH)


def uso(entrada=0, lectura=0, escritura=0, salida=0):
    return {"input_tokens": entrada, "cache_read_input_tokens": lectura,
            "cache_creation_input_tokens": escritura, "output_tokens": salida}


class BaseCoste(unittest.TestCase):
    """Un workspace de mentira y una raíz de rollouts de mentira, por test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.proyecto = base / "workspace"
        self.proyecto.mkdir()
        self.claude = base / "claude-projects"
        self.claude.mkdir()
        self.entorno = os.environ.get("COSTE_CLAUDE_PROJECTS")
        os.environ["COSTE_CLAUDE_PROJECTS"] = str(self.claude)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._restaurar_entorno)

    def _restaurar_entorno(self):
        if self.entorno is None:
            os.environ.pop("COSTE_CLAUDE_PROJECTS", None)
        else:
            os.environ["COSTE_CLAUDE_PROJECTS"] = self.entorno

    def escribir_sesion(self, lineas, nombre="sesion.jsonl", proyecto=None):
        destino = self.claude / coste.normalizar_proyecto(str(proyecto or self.proyecto))
        destino.mkdir(parents=True, exist_ok=True)
        fichero = destino / nombre
        with fichero.open("w", encoding="utf-8") as fh:
            for linea in lineas:
                fh.write(json.dumps(linea, ensure_ascii=False) + "\n")
        return fichero

    def turno(self, rid, **kwargs):
        return {"type": "assistant", "requestId": rid,
                "message": {"model": "claude-opus-5", "content": [{"type": "text", "text": "ok"}],
                            "usage": uso(**kwargs)}}

    def correr(self, *argumentos):
        """Ejecuta el medidor en proceso y devuelve (codigo, salida)."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            codigo = coste.main(list(argumentos))
        return codigo, buffer.getvalue()

    def correr_proyecto(self, *argumentos):
        return self.correr("--proyecto", str(self.proyecto), *argumentos)


class EjesTest(BaseCoste):
    """R1 · los cuatro ejes suman el 100 % y no sale ninguna nota compuesta."""

    def test_los_cuatro_ejes_suman_cien(self):
        self.escribir_sesion([
            self.turno("r1", entrada=10, lectura=1000, escritura=100, salida=50),
            self.turno("r2", entrada=0, lectura=2000, escritura=200, salida=70),
            self.turno("r3", entrada=5, lectura=3000, escritura=300, salida=90),
        ])
        codigo, salida = self.correr_proyecto()
        self.assertEqual(codigo, 0, salida)
        porcentajes = [float(p.replace(",", ".")) for p in re.findall(r"([\d.]+) %", salida)]
        self.assertGreaterEqual(len(porcentajes), 4)
        self.assertAlmostEqual(sum(porcentajes[:4]), 100.0, delta=0.1)

    def test_no_emite_nota_compuesta(self):
        self.escribir_sesion([self.turno("r1", lectura=1000, salida=10)])
        _, salida = self.correr_proyecto()
        for prohibido in ("nota compuesta:", "puntuación", "índice de eficiencia", "score"):
            self.assertNotIn(prohibido, salida.lower())


class ComposicionTest(BaseCoste):
    """R2 · de quién es el peso que se relee, y qué NO se puede ver desde el rollout."""

    def test_tool_result_es_herramienta_no_persona(self):
        fichero = self.escribir_sesion([
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "x" * 4000}]}},
            self.turno("r1", lectura=1000, salida=10),
            self.turno("r2", lectura=2000, salida=10),
        ])
        acumulado, _ = coste.composicion(fichero)
        self.assertGreater(acumulado["herramientas"], 0)
        self.assertEqual(acumulado["usuario"], 0)

    def test_lo_que_escribe_la_persona_si_cuenta_como_persona(self):
        fichero = self.escribir_sesion([
            {"type": "user", "message": {"role": "user", "content": "hola" * 1000}},
            self.turno("r1", lectura=1000, salida=10),
            self.turno("r2", lectura=2000, salida=10),
        ])
        acumulado, _ = coste.composicion(fichero)
        self.assertGreater(acumulado["usuario"], 0)
        self.assertEqual(acumulado["herramientas"], 0)

    def test_declara_que_el_prompt_de_sistema_no_esta_en_el_rollout(self):
        self.escribir_sesion([
            {"type": "user", "message": {"role": "user", "content": "hola"}},
            self.turno("r1", lectura=1000, salida=10),
        ])
        _, salida = self.correr_proyecto()
        self.assertIn("prompt de sistema", salida)
        self.assertIn("se mide aparte", salida)

    def test_los_cuatro_origenes_aparecen_en_la_salida(self):
        self.escribir_sesion([
            {"type": "user", "message": {"role": "user", "content": "hola"}},
            self.turno("r1", lectura=1000, salida=10),
        ])
        _, salida = self.correr_proyecto()
        for nombre in ("razonamiento del agente", "salida de herramientas",
                       "andamiaje del harness", "lo que escribe la gente"):
            self.assertIn(nombre, salida)


class TurnoUnicoTest(BaseCoste):
    """R8 · un turno es un `requestId`: el reintento no duplica ni turno ni tokens."""

    def test_reintento_con_el_mismo_request_id_cuenta_una_vez(self):
        fichero = self.escribir_sesion([
            self.turno("r1", lectura=1000, salida=10),
            self.turno("r1", lectura=1000, salida=10),
        ])
        turnos, _ = coste.leer_sesion(fichero)
        self.assertEqual(len(turnos), 1)
        self.assertEqual(sum(t["tokens"] for t in turnos), 1010)

    def test_peticiones_distintas_son_turnos_distintos(self):
        fichero = self.escribir_sesion([
            self.turno("r1", lectura=1000, salida=10),
            self.turno("r2", lectura=1000, salida=10),
        ])
        turnos, _ = coste.leer_sesion(fichero)
        self.assertEqual(len(turnos), 2)


class ProsaSiempreCargadaTest(BaseCoste):
    """R3 · el texto siempre cargado cuesta tamaño x turnos, y se dice en % del total."""

    def test_porcentaje_exacto_de_la_prosa(self):
        (self.proyecto / "AGENTS.md").write_text("a" * 8192, encoding="utf-8")
        lineas = [self.turno(f"r{i}", lectura=1000, salida=0) for i in range(10)]
        self.escribir_sesion(lineas)
        total = 10 * 1000
        esperado = 100.0 * (8192 / 4.0 * 10) / total
        _, salida = self.correr_proyecto()
        encontrado = re.search(r"Texto del método siempre cargado: .*→ ([\d.]+) %", salida)
        self.assertIsNotNone(encontrado, salida)
        self.assertAlmostEqual(float(encontrado.group(1)), round(esperado, 2), delta=0.01)

    def test_sin_prosa_no_se_inventa_la_linea(self):
        self.escribir_sesion([self.turno("r1", lectura=1000, salida=10)])
        _, salida = self.correr_proyecto()
        self.assertNotIn("Texto del método siempre cargado", salida)


class SimulacionTest(BaseCoste):
    """R4 · la simulación imprime su supuesto; R7 · un tramo sin datos se declara."""

    def sesion_larga(self, turnos, nombre="larga.jsonl"):
        self.escribir_sesion(
            [self.turno(f"{nombre}-{i}", lectura=1000 + 10 * i, salida=10) for i in range(turnos)],
            nombre=nombre)

    def test_la_simulacion_imprime_siempre_su_supuesto(self):
        self.sesion_larga(300)
        _, salida = self.correr_proyecto("--corte", "100")
        self.assertIn("supuesto declarado", salida)
        self.assertIn("gasto real", salida)
        self.assertIn("gasto simulado", salida)
        self.assertIn("retomadas", salida)
        self.assertRegex(salida, r"→ *[\d.]+ % menos")

    def test_cortar_mas_tarde_ahorra_menos(self):
        self.sesion_larga(300)
        perfil, _ = coste.perfil_por_indice(self.sesiones())
        real_100, sim_100, _ = coste.simular_corte(self.sesiones(), perfil, 100, 40_000)
        real_250, sim_250, _ = coste.simular_corte(self.sesiones(), perfil, 250, 40_000)
        self.assertGreater(coste.pct(real_100 - sim_100, real_100),
                           coste.pct(real_250 - sim_250, real_250))

    def sesiones(self):
        todas = []
        raiz = Path(os.environ["COSTE_CLAUDE_PROJECTS"])
        for fichero in sorted((raiz / coste.normalizar_proyecto(str(self.proyecto))).glob("*.jsonl")):
            turnos, meta = coste.leer_sesion(fichero)
            if turnos:
                todas.append((turnos, meta))
        return todas

    def test_tramo_sin_datos_se_declara_y_nunca_es_cero_por_equis(self):
        self.sesion_larga(30)
        _, salida = self.correr_proyecto()
        self.assertIn("sin sesiones tan largas", salida)
        self.assertNotIn("0.0x", salida)


class LineaBaseTest(BaseCoste):
    """R5 · integración: un volcado se compara contra la ejecución de hoy."""

    def test_compara_por_eje_y_tokens_por_turno(self):
        self.escribir_sesion([self.turno("r1", lectura=1000, escritura=100, salida=10)])
        volcado = Path(self.tmp.name) / "linea-base.json"
        codigo, _ = self.correr_proyecto("--json", str(volcado))
        self.assertEqual(codigo, 0)
        self.assertTrue(volcado.is_file())
        guardado = json.loads(volcado.read_text(encoding="utf-8"))
        self.assertIn("ejes", guardado)
        self.assertIn("turnos", guardado)

        # Hoy se gasta el doble por turno: la comparación tiene que verlo.
        self.escribir_sesion([
            self.turno("r2", lectura=2000, escritura=200, salida=20),
            self.turno("r3", lectura=2000, escritura=200, salida=20),
        ], nombre="hoy.jsonl")
        codigo, salida = self.correr_proyecto("--linea-base", str(volcado))
        self.assertEqual(codigo, 0, salida)
        self.assertIn("Contra la línea base", salida)
        self.assertIn("tokens por turno", salida)
        self.assertRegex(salida, r"[+-][\d.]+")


class SalidasDeFalloTest(BaseCoste):
    """R6 · un fallo NOMBRA el comando que lo resuelve. Nunca un cero mudo."""

    def comprobar_fallo(self, codigo, salida):
        self.assertNotEqual(codigo, 0, salida)
        self.assertIn("FAIL", salida)
        self.assertIn("salida:", salida)
        self.assertRegex(salida, r"python3 .*coste\.py")

    def test_proyecto_inexistente(self):
        codigo, salida = self.correr("--proyecto", str(Path(self.tmp.name) / "no-existe"))
        self.comprobar_fallo(codigo, salida)

    def test_sin_raiz_de_rollouts(self):
        os.environ["COSTE_CLAUDE_PROJECTS"] = str(Path(self.tmp.name) / "sin-harness")
        codigo, salida = self.correr_proyecto()
        self.comprobar_fallo(codigo, salida)

    def test_sin_ninguna_sesion_con_uso(self):
        self.escribir_sesion([{"type": "user", "message": {"role": "user", "content": "hola"}}])
        codigo, salida = self.correr_proyecto()
        self.comprobar_fallo(codigo, salida)

    def test_linea_base_ilegible(self):
        self.escribir_sesion([self.turno("r1", lectura=1000, salida=10)])
        rota = Path(self.tmp.name) / "rota.json"
        rota.write_text("{esto no es json", encoding="utf-8")
        codigo, salida = self.correr_proyecto("--linea-base", str(rota))
        self.comprobar_fallo(codigo, salida)

    def test_linea_base_inexistente(self):
        self.escribir_sesion([self.turno("r1", lectura=1000, salida=10)])
        codigo, salida = self.correr_proyecto(
            "--linea-base", str(Path(self.tmp.name) / "no-esta.json"))
        self.comprobar_fallo(codigo, salida)


if __name__ == "__main__":
    unittest.main()
