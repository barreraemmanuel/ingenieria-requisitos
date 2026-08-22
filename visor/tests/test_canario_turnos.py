"""035-canario-cuenta-turnos · el canario avisa por POSICIÓN, no por porcentaje de ventana.

Medido el 22-08-2026 sobre 63 sesiones y 4.006 M de tokens: la alarma de capacidad no saltó
ni una sola vez. El máximo alcanzado fue 767k y el umbral está en el 80 % de 1M = 800k. El
100 % del gasto ocurre por debajo del disparo. Lo que sí predice el coste es la posición del
turno: uno en el 900 cuesta 8,7× lo que el mismo en el 50.

  R1  más de 250 turnos → avisa por posición, con la cuenta y el comando de retomada
  R2  por debajo de los dos umbrales → sin aviso (la línea de estado «sano» sigue igual)
  R3  turnos + conducta a la vez → manda la conducta, y sale UN solo aviso
  R4  el umbral de turnos se declara en la config del workspace; por defecto 250
  R5  transcripción ilegible o harness desconocido → silencio y salida limpia
"""

import importlib.util
import json
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CANARIO_PATH = RAIZ / "plantilla/docs/00-metodo/scripts/canario.py"


def _cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


canario = _cargar("canario_turnos_bajo_test", CANARIO_PATH)

_base = _cargar("canario_base_bajo_test", Path(__file__).parent / "test_canario_contexto.py")
BaseCanario = _base.BaseCanario


class TurnosTest(BaseCanario):
    """El canario cuenta turnos del asistente y avisa cuando la sesión se hace larga."""

    def sesion_de_turnos(self, *, turnos, tokens=120_000, modelo="claude-opus-5",
                         eventos=(), nombre="larga.jsonl"):
        """Una sesión con `turnos` mensajes de asistente, cada uno con su uso.

        Es la forma real: cada turno del asistente trae su bloque `usage`. El canario
        cuenta esos bloques, que es exactamente lo que el harness ya escribe.
        """
        cwd = str(self.cwd)
        carpeta = self.claude / canario.normalizar_proyecto(cwd)
        carpeta.mkdir(parents=True, exist_ok=True)
        lineas = [json.dumps({"type": "user", "cwd": cwd,
                              "message": {"role": "user", "content": "hola"}})]
        lineas.extend(eventos)
        for i in range(turnos):
            lineas.append(json.dumps({
                "type": "assistant", "cwd": cwd,
                "message": {"model": modelo,
                            "usage": {"input_tokens": tokens,
                                      "cache_read_input_tokens": 0,
                                      "cache_creation_input_tokens": 0,
                                      "output_tokens": 50}},
            }))
        fichero = carpeta / nombre
        fichero.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return fichero

    # --- R1 -----------------------------------------------------------------

    def test_r1_sesion_larga_avisa_por_posicion(self):
        self.sesion_de_turnos(turnos=300)
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertEqual(informe["veredicto"], "largo")
        self.assertEqual(informe["turnos"], 300)
        texto = canario.texto_veredicto(informe)
        self.assertIn("300", texto)
        self.assertIn("canario.py retomada", texto,
                      "el aviso por posición tiene que nombrar el parte de retomada")

    def test_r1_el_aviso_dice_lo_que_cuesta_seguir(self):
        """No basta con avisar: el usuario tiene que saber POR QUÉ conviene cortar."""
        self.sesion_de_turnos(turnos=400)
        texto = canario.texto_veredicto(canario.diagnosticar(
            raiz=self.cwd, cwd=self.cwd, claude_projects=self.claude,
            codex_sessions=self.codex))
        self.assertRegex(texto.lower(), r"turno|posición|posicion",
                         "el aviso debe explicar que el coste crece con la posición")

    # --- R2 -----------------------------------------------------------------

    def test_r2_sesion_corta_calla(self):
        self.sesion_de_turnos(turnos=40)
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertEqual(informe["veredicto"], "sano")
        texto = canario.texto_veredicto(informe)
        self.assertNotIn("⚠️", texto,
                         "por debajo de los dos umbrales no hay AVISO (la línea informativa "
                         "de estado sí sigue saliendo: es conducta previa y no se toca)")
        self.assertIn("sano", texto)

    def test_r2_el_informe_trae_los_turnos_aunque_calle(self):
        """El dato se publica siempre; lo que cambia es si se dice algo o no."""
        self.sesion_de_turnos(turnos=40)
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertEqual(informe["turnos"], 40)

    # --- R3 -----------------------------------------------------------------

    def test_r3_conducta_manda_sobre_posicion(self):
        """Llenarse es un riesgo; repetirse es un hecho. Y sale UN solo aviso."""
        eventos = self.par_fallido_claude("pytest -q", "ImportError: no such module", 4)
        self.sesion_de_turnos(turnos=300, eventos=eventos)
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertEqual(informe["veredicto"], "sintomas")
        texto = canario.texto_veredicto(informe)
        self.assertEqual(texto.count("CANARIO DE CONTEXTO"), 1,
                         "dos avisos a la vez confundirían: sale uno solo")

    # --- R4 -----------------------------------------------------------------

    def test_r4_umbral_de_turnos_declarable(self):
        (self.cwd / ".claude").mkdir(parents=True, exist_ok=True)
        (self.cwd / ".claude/canario.json").write_text(
            json.dumps({"turnos_aviso": 100}), encoding="utf-8")
        self.sesion_de_turnos(turnos=150)
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertEqual(informe["veredicto"], "largo",
                         "con el umbral en 100, una sesión de 150 turnos ya es larga")

    def test_r4_el_defecto_es_250(self):
        self.assertEqual(canario.DEFECTOS["turnos_aviso"], 250)

    def test_r4_umbral_declarado_por_encima_no_dispara(self):
        (self.cwd / ".claude").mkdir(parents=True, exist_ok=True)
        (self.cwd / ".claude/canario.json").write_text(
            json.dumps({"turnos_aviso": 900}), encoding="utf-8")
        self.sesion_de_turnos(turnos=300)
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertNotEqual(informe["veredicto"], "largo")

    # --- R5 -----------------------------------------------------------------

    def test_r5_transcripcion_corrupta_calla_y_sale_bien(self):
        carpeta = self.claude / canario.normalizar_proyecto(str(self.cwd))
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "rota.jsonl").write_text("{no es json\n" * 5, encoding="utf-8")
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertEqual(canario.texto_veredicto(informe), "")
        self.assertIsNone(informe["turnos"])

    def test_r5_sin_sesion_no_hay_turnos_ni_ruido(self):
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertEqual(informe["veredicto"], "sin_datos")
        self.assertIsNone(informe["turnos"])
        self.assertEqual(canario.texto_veredicto(informe), "")

    # --- la razón de ser de la unidad ---------------------------------------

    def test_la_sesion_que_hoy_nunca_dispara_ahora_si(self):
        """767k tokens en ventana de 1M: el caso real medido. Antes: silencio.

        La ventana de 1M se declara en la config, que es como el método la conoce hoy
        para los modelos de ventana grande.
        """
        (self.cwd / ".claude").mkdir(parents=True, exist_ok=True)
        (self.cwd / ".claude/canario.json").write_text(
            json.dumps({"ventanas": {"claude-opus-5": 1_000_000}}), encoding="utf-8")
        self.sesion_de_turnos(turnos=900, tokens=767_000)
        informe = canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)
        self.assertLess(informe["porcentaje"], informe["umbral"],
                        "por capacidad seguiría callado: es el caso de campo")
        self.assertEqual(informe["veredicto"], "largo")
        self.assertNotEqual(canario.texto_veredicto(informe), "")


if __name__ == "__main__":
    unittest.main()
