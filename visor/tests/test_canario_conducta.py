"""062-canario-ciego · el canario deja de estar ciego: ventana, conducta y hook Stop.

Contrato del bug `docs/bugs/062-canario-ciego.md` (sección 1):

  R1  tabla de ventanas por defecto de los modelos actuales; modelo desconocido → asumir la
      MENOR conocida y decirlo UNA vez (nunca callar). `.claude/canario.json` sigue mandando.
  R2  conducta por CONTENIDO: la regex de fallo se aplica también al texto de los
      `tool_result` de Claude Code, y los comandos se comparan NORMALIZADOS (sin números,
      rutas temporales ni sufijos `| tail/head`, `2>&1`, `|| true`).
  R3  señales de atasco SIN error: mismo fichero editado ≥ N veces seguidas; mismo test
      lanzado ≥ N veces sin pasar a verde; ≥ N turnos con herramientas sin tocar ficheros.
  R4  hook `Stop` sembrado por `bootstrap.py` junto al `PreCompact`, barato y cada N turnos.
  R5  fixture con un jsonl real (anonimizado y recortado) donde el canario de HOY no dispara
      y el nuevo sí.

Las dos fixtures viven en `visor/tests/fixtures/canario/` y tienen la forma exacta que lee
`canario.leer_claude`: recortadas de una sesión real de Claude Code y anonimizadas (rutas,
sessionId y modelo). En `sesion-claude-conducta.jsonl` los tres `tool_result` traen
`is_error: false` —el fallo viaja dentro de un `| tail`, y el exit del pipeline es 0— y los
tres comandos difieren solo en el directorio temporal y en el `-20`/`-40` del tail: es el
caso de campo del reporte, en el que el canario viejo no ve nada.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CANARIO_PATH = RAIZ / "plantilla/docs/00-metodo/scripts/canario.py"
BOOTSTRAP_PATH = RAIZ / "visor/bootstrap.py"
FIXTURES = Path(__file__).parent / "fixtures" / "canario"


def _cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


canario = _cargar("canario_conducta_bajo_test", CANARIO_PATH)
bootstrap = _cargar("bootstrap_conducta_bajo_test", BOOTSTRAP_PATH)

_base = _cargar("canario_base_conducta", Path(__file__).parent / "test_canario_contexto.py")
BaseCanario = _base.BaseCanario


class BaseConducta(BaseCanario):
    """Añade a la base del 023 la siembra de una fixture real y unos eventos sintéticos."""

    def instalar_fixture(self, nombre):
        """Copia una fixture al sitio donde el harness la habría escrito."""
        carpeta = self.claude / canario.normalizar_proyecto(str(self.cwd))
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / nombre
        shutil.copyfile(FIXTURES / nombre, destino)
        return destino

    # --- eventos sintéticos con la forma que escribe Claude Code ------------

    def turno_con_herramienta(self, indice, nombre, entrada, salida, *, is_error=False):
        """Un turno del asistente que usa una herramienta, y su `tool_result`."""
        tid = f"tu_{indice}"
        return [
            json.dumps({"type": "assistant", "message": {
                "role": "assistant", "model": "claude-opus-5", "content": [
                    {"type": "tool_use", "id": tid, "name": nombre, "input": entrada}]}}),
            json.dumps({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid,
                 "is_error": is_error, "content": salida}]}}),
        ]

    def eventos_edicion(self, fichero, veces):
        eventos = []
        for i in range(veces):
            eventos += self.turno_con_herramienta(
                f"ed{i}", "Edit", {"file_path": fichero, "old_string": "a", "new_string": "b"},
                "The file has been updated.")
        return eventos

    def eventos_test(self, comando, veces, *, salida="FAILED (failures=1)"):
        eventos = []
        for i in range(veces):
            eventos += self.turno_con_herramienta(
                f"ts{i}", "Bash", {"command": comando}, salida)
        return eventos


# --------------------------------------------------------------------------- R2


class ConductaPorContenidoTest(BaseConducta):
    """R2: el fallo se lee del TEXTO, y los comandos se comparan normalizados."""

    def test_la_sesion_real_del_reporte_dispara_conducta(self):
        """El caso de campo: 3 comandos casi iguales fallando dentro de `| tail`."""
        self.instalar_fixture("sesion-claude-conducta.jsonl")

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sintomas",
                         "tres fallos idénticos sin `is_error` siguen siendo un atasco")
        self.assertEqual(informe["sintoma"]["veces"], 3)
        self.assertIn("node scripts/build.js", informe["sintoma"]["comando"])

    def test_el_aviso_de_la_sesion_real_se_ve(self):
        self.instalar_fixture("sesion-claude-conducta.jsonl")

        texto = canario.texto_veredicto(self.diagnostico())

        self.assertIn("YA está degradando", texto)
        self.assertIn("canario.py retomada", texto)

    def test_ningun_tool_result_de_la_fixture_trae_is_error(self):
        """La fixture no vale si el canario viejo podía verla: se comprueba aquí."""
        crudo = (FIXTURES / "sesion-claude-conducta.jsonl").read_text(encoding="utf-8")
        marcados = 0
        for linea in crudo.splitlines():
            mensaje = json.loads(linea).get("message", {})
            for bloque in mensaje.get("content", []) if isinstance(
                    mensaje.get("content"), list) else []:
                if bloque.get("type") == "tool_result" and bloque.get("is_error"):
                    marcados += 1
        self.assertEqual(marcados, 0)

    def test_comandos_casi_iguales_normalizan_al_mismo(self):
        """Números, rutas temporales y colas de pipe no distinguen dos intentos."""
        uno = canario.normalizar_comando(
            "node build.js --out /var/folders/ab/T/tmp1234/out 2>&1 | tail -20")
        dos = canario.normalizar_comando(
            "node build.js --out /var/folders/ab/T/tmp5678/out 2>&1 | tail -40")
        tres = canario.normalizar_comando(
            "node build.js --out /tmp/tmp9012/out 2>&1 | tail -20 || true")

        self.assertEqual(uno, dos)
        self.assertEqual(uno, tres)

    def test_dos_comandos_de_verdad_distintos_no_se_confunden(self):
        """Normalizar no puede volverlo todo igual: eso sería un canario que grita."""
        self.assertNotEqual(canario.normalizar_comando("pytest -q tests/a.py"),
                            canario.normalizar_comando("npm run build"))

    def test_salida_limpia_repetida_no_es_un_fallo(self):
        """Falso negativo antes que falso positivo: sin marcas de fallo, silencio."""
        eventos = self.eventos_test("git status --porcelain", 5,
                                    salida="nothing to commit, working tree clean")
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertIsNone(informe["sintoma"])
        self.assertEqual(informe["veredicto"], "sano")


# --------------------------------------------------------------------------- R3


class AtascoSinErrorTest(BaseConducta):
    """R3: hay atascos que no dejan ni una línea de error."""

    def test_los_umbrales_de_atasco_viven_en_defectos(self):
        for clave in ("ediciones_seguidas", "tests_sin_verde", "turnos_sin_ficheros"):
            self.assertIn(clave, canario.DEFECTOS)
            self.assertGreater(canario.DEFECTOS[clave], 0)

    def test_mismo_fichero_editado_muchas_veces_seguidas(self):
        veces = canario.DEFECTOS["ediciones_seguidas"]
        self.sesion_claude(tokens=100_000, eventos=self.eventos_edicion("src/app.py", veces))

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertEqual(informe["sintoma"]["tipo"], "ediciones")
        self.assertIn("src/app.py", canario.texto_veredicto(informe))

    def test_pocas_ediciones_del_mismo_fichero_no_son_atasco(self):
        self.sesion_claude(tokens=100_000, eventos=self.eventos_edicion("src/app.py", 2))

        self.assertIsNone(self.diagnostico()["sintoma"])

    def test_alternar_de_fichero_reinicia_la_cuenta(self):
        eventos = []
        for i in range(canario.DEFECTOS["ediciones_seguidas"] * 2):
            eventos += self.eventos_edicion(f"src/mod_{i % 2}.py", 1)
        self.sesion_claude(tokens=100_000, eventos=eventos)

        self.assertIsNone(self.diagnostico()["sintoma"],
                          "editar dos ficheros a la vez es trabajar, no atascarse")

    def test_mismo_test_lanzado_sin_pasar_a_verde(self):
        veces = canario.DEFECTOS["tests_sin_verde"]
        # Salidas SIN marca de fallo: el test ni siquiera dice "FAILED", solo no dice OK.
        eventos = self.eventos_test("python3 -m unittest visor.tests.test_x", veces,
                                    salida="Ran 3 tests in 0.4s")
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertEqual(informe["sintoma"]["tipo"], "tests")
        self.assertIn("unittest", canario.texto_veredicto(informe))

    def test_si_el_test_pasa_a_verde_la_cuenta_se_reinicia(self):
        veces = canario.DEFECTOS["tests_sin_verde"]
        orden = "python3 -m unittest visor.tests.test_x"
        eventos = self.eventos_test(orden, veces - 1, salida="Ran 3 tests in 0.4s")
        eventos += self.eventos_test(orden, 1, salida="Ran 3 tests in 0.4s\n\nOK")
        eventos += self.eventos_test(orden, veces - 1, salida="Ran 3 tests in 0.4s")
        self.sesion_claude(tokens=100_000, eventos=eventos)

        self.assertIsNone(self.diagnostico()["sintoma"],
                          "un verde por en medio dice que la sesión avanza")

    def test_muchos_turnos_con_herramientas_sin_tocar_un_fichero(self):
        veces = canario.DEFECTOS["turnos_sin_ficheros"]
        eventos = []
        for i in range(veces):
            eventos += self.turno_con_herramienta(
                f"ls{i}", "Bash", {"command": f"ls carpeta_{i}"}, f"fichero_{i}.txt")
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertEqual(informe["sintoma"]["tipo"], "sin_ficheros")

    def test_una_edicion_al_final_rompe_la_racha_de_turnos_secos(self):
        veces = canario.DEFECTOS["turnos_sin_ficheros"]
        eventos = []
        for i in range(veces):
            eventos += self.turno_con_herramienta(
                f"ls{i}", "Bash", {"command": f"ls carpeta_{i}"}, f"fichero_{i}.txt")
        eventos += self.eventos_edicion("src/app.py", 1)
        self.sesion_claude(tokens=100_000, eventos=eventos)

        self.assertIsNone(self.diagnostico()["sintoma"])

    def test_una_conversacion_larga_sin_herramientas_no_es_atasco(self):
        """Turnos de charla no son turnos de trabajo: el eje de POSICIÓN ya los cubre."""
        eventos = [json.dumps({"type": "assistant", "message": {
            "role": "assistant", "model": "claude-opus-5",
            "content": [{"type": "text", "text": "te explico"}]}})
            for _ in range(canario.DEFECTOS["turnos_sin_ficheros"] * 3)]
        self.sesion_claude(tokens=100_000, eventos=eventos)

        self.assertIsNone(self.diagnostico()["sintoma"])

    def test_los_umbrales_de_atasco_se_declaran_en_la_config(self):
        self.config({"ediciones_seguidas": 2})
        self.sesion_claude(tokens=100_000, eventos=self.eventos_edicion("src/app.py", 2))

        self.assertEqual(self.diagnostico()["veredicto"], "sintomas")


# --------------------------------------------------------------------------- R1


class VentanaDeLosModelosActualesTest(BaseConducta):
    """R1: el canario ya no se queda ciego ante un modelo que no tiene apuntado."""

    def test_los_modelos_actuales_traen_ventana_de_serie(self):
        config = canario.cargar_config(self.cwd)
        esperado = {
            "claude-fable-5": 1_000_000,
            "claude-opus-5": 1_000_000,
            "claude-sonnet-5": 1_000_000,
            "claude-haiku-4-5-20251001": 200_000,
        }
        for modelo, ventana in esperado.items():
            self.assertEqual(canario.ventana_de(modelo, config), ventana, modelo)

    def test_la_sesion_de_hoy_ya_no_dice_sin_umbral(self):
        self.sesion_claude(tokens=291_000, modelo="claude-fable-5")

        informe = self.diagnostico()

        self.assertEqual(informe["ventana"], 1_000_000)
        self.assertEqual(round(informe["porcentaje"]), 29)
        self.assertNotIn("sin umbral", canario.texto_veredicto(informe))

    def test_modelo_desconocido_asume_la_menor_conocida_y_lo_dice(self):
        self.instalar_fixture("sesion-claude-modelo-nuevo.jsonl")

        informe = self.diagnostico()
        texto = canario.texto_veredicto(informe)

        self.assertEqual(informe["ventana"], 200_000,
                         "la menor conocida: asumir de menos avisa antes, nunca de más")
        self.assertTrue(informe["ventana_asumida"])
        self.assertEqual(round(informe["porcentaje"]), 75)
        self.assertIn("claude-quixote-6-20270210", texto)
        self.assertIn("asumo", texto.lower())

    def test_el_modelo_desconocido_ya_no_apaga_la_vigilancia(self):
        self.sesion_claude(tokens=180_000, modelo="modelo-de-otro-lab")

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "aviso",
                         "90 % de la ventana asumida: antes callaba con `incierto`")

    def test_el_aviso_del_modelo_nuevo_sale_una_sola_vez(self):
        self.instalar_fixture("sesion-claude-modelo-nuevo.jsonl")

        uno, dos = self.diagnostico(), self.diagnostico()
        primero, segundo = canario.texto_veredicto(uno), canario.texto_veredicto(dos)

        self.assertTrue(uno["avisar_modelo"])
        self.assertFalse(dos["avisar_modelo"], "una vez es una vez")
        self.assertIn("claude-quixote-6-20270210", primero)
        self.assertIn("asumo", primero.lower())
        self.assertNotIn("asumo", segundo.lower())
        self.assertNotEqual(segundo, "", "callarse del todo, jamás: la línea de estado sigue")
        self.assertIn("75", segundo, "la vigilancia sigue viva después del aviso")

    def test_la_config_del_workspace_sigue_mandando_sobre_la_tabla(self):
        self.config({"ventanas": {"claude-opus-5": 300_000}})
        self.sesion_claude(tokens=150_000, modelo="claude-opus-5")

        informe = self.diagnostico()

        self.assertEqual(informe["ventana"], 300_000)
        self.assertFalse(informe["ventana_asumida"])


# --------------------------------------------------------------------------- R4


class HookStopTest(BaseConducta):
    """R4: el canario corre solo, cada N turnos, en el hook `Stop`."""

    def correr(self, *argumentos, entrada="{}"):
        import os
        return subprocess.run(
            [sys.executable, str(CANARIO_PATH), *argumentos,
             "--cwd", str(self.cwd), "--workspace", str(self.cwd)],
            input=entrada, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env={**os.environ,
                 "CANARIO_CLAUDE_PROJECTS": str(self.claude),
                 "CANARIO_CODEX_SESSIONS": str(self.codex)})

    def sesion_de_n_turnos(self, turnos, *, eventos=()):
        cwd = str(self.cwd)
        carpeta = self.claude / canario.normalizar_proyecto(cwd)
        carpeta.mkdir(parents=True, exist_ok=True)
        lineas = [json.dumps({"type": "user", "cwd": cwd,
                              "message": {"role": "user", "content": "hola"}})]
        lineas.extend(eventos)
        for _ in range(turnos):
            lineas.append(json.dumps({
                "type": "assistant", "cwd": cwd,
                "message": {"model": "claude-opus-5",
                            "usage": {"input_tokens": 900_000,
                                      "cache_read_input_tokens": 0,
                                      "cache_creation_input_tokens": 0,
                                      "output_tokens": 10}}}))
        fichero = carpeta / "stop.jsonl"
        fichero.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return fichero

    def test_el_umbral_de_turnos_del_hook_vive_en_defectos(self):
        self.assertGreater(canario.DEFECTOS["turnos_hook"], 0)

    def test_hook_stop_no_bloquea_nunca(self):
        self.sesion_de_n_turnos(3)

        r = self.correr("hook-stop")

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout).get("continue"))

    def test_hook_stop_calla_entre_dos_rondas(self):
        cada = canario.DEFECTOS["turnos_hook"]
        self.sesion_de_n_turnos(cada + 1)          # 900k de 1M: hay motivo de sobra

        salida = json.loads(self.correr("hook-stop").stdout)

        self.assertNotIn("systemMessage", salida,
                         "barato quiere decir que no habla en todos los turnos")

    def test_hook_stop_avisa_al_llegar_a_la_ronda(self):
        cada = canario.DEFECTOS["turnos_hook"]
        self.sesion_de_n_turnos(cada)

        salida = json.loads(self.correr("hook-stop").stdout)

        self.assertIn("zona de riesgo", salida.get("systemMessage", ""))

    def test_hook_stop_avisa_de_la_conducta_sin_esperar_a_la_ronda(self):
        """Un atasco no espera turno: repetirse es un hecho, y ya está pasando."""
        fixture = self.instalar_fixture("sesion-claude-conducta.jsonl")

        salida = json.loads(self.correr("hook-stop").stdout)

        self.assertIn("YA está degradando", salida.get("systemMessage", ""))
        self.assertTrue(fixture.is_file())

    def test_hook_stop_lee_el_transcript_que_le_pasa_el_harness(self):
        """Lo barato: el harness ya dice qué fichero es; no hace falta rastrear nada."""
        fixture = FIXTURES / "sesion-claude-conducta.jsonl"

        r = self.correr("hook-stop", entrada=json.dumps(
            {"hook_event_name": "Stop", "transcript_path": str(fixture)}))

        salida = json.loads(r.stdout)
        self.assertIn("YA está degradando", salida.get("systemMessage", ""))
        self.assertIn(str(fixture), salida["systemMessage"])

    def test_sesion_sana_y_corta_no_dice_nada(self):
        cwd = str(self.cwd)
        carpeta = self.claude / canario.normalizar_proyecto(cwd)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "corta.jsonl").write_text(json.dumps({
            "type": "assistant", "cwd": cwd,
            "message": {"model": "claude-opus-5",
                        "usage": {"input_tokens": 1000, "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0}}}) + "\n",
            encoding="utf-8")

        salida = json.loads(self.correr("hook-stop").stdout)

        self.assertNotIn("systemMessage", salida)

    def test_sin_sesion_el_hook_stop_sale_limpio_y_callado(self):
        r = self.correr("hook-stop")

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("systemMessage", json.loads(r.stdout))


class SiembraDelHookStopTest(BaseConducta):
    """R4: lo siembra el bootstrap, junto al PreCompact que ya sembraba, sin duplicar."""

    def test_el_bootstrap_siembra_el_hook_stop(self):
        destino = self.base / "ws-stop"
        destino.mkdir()

        bootstrap.sembrar_hook_canario(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        ordenes = [orden["command"]
                   for entrada in settings["hooks"]["Stop"]
                   for orden in entrada["hooks"]]
        self.assertEqual(len(ordenes), 1)
        self.assertIn("canario.py", ordenes[0])
        self.assertIn("hook-stop", ordenes[0])

    def test_el_precompact_sigue_estando(self):
        destino = self.base / "ws-stop"
        destino.mkdir()

        bootstrap.sembrar_hook_canario(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual([g["matcher"] for g in settings["hooks"]["PreCompact"]], ["auto"])

    def test_sembrar_dos_veces_no_duplica_el_stop(self):
        destino = self.base / "ws-stop"
        destino.mkdir()

        bootstrap.sembrar_hook_canario(destino)
        bootstrap.sembrar_hook_canario(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)
        self.assertEqual(len(settings["hooks"]["Stop"][0]["hooks"]), 1)
        self.assertEqual(len(settings["hooks"]["PreCompact"]), 1)

    def test_un_workspace_que_ya_tenia_el_precompact_gana_el_stop(self):
        """Modo D / workspace viejo: el PreCompact ya está y el Stop todavía no."""
        destino = self.base / "ws-viejo"
        (destino / ".claude").mkdir(parents=True)
        (destino / ".claude/settings.json").write_text(json.dumps({
            "hooks": {"PreCompact": [{"matcher": "auto", "hooks": [
                {"type": "command", "command": bootstrap.ORDEN_CANARIO}]}]}}),
            encoding="utf-8")

        self.assertTrue(bootstrap.sembrar_hook_canario(destino))

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(len(settings["hooks"]["PreCompact"]), 1)
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)

    def test_se_respeta_un_hook_stop_ajeno(self):
        destino = self.base / "ws-ajeno"
        (destino / ".claude").mkdir(parents=True)
        (destino / ".claude/settings.json").write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "echo mio"}]}]}}), encoding="utf-8")

        bootstrap.sembrar_hook_canario(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        ordenes = [orden["command"]
                   for entrada in settings["hooks"]["Stop"]
                   for orden in entrada["hooks"]]
        self.assertIn("echo mio", ordenes)
        self.assertTrue(any("hook-stop" in o for o in ordenes))


if __name__ == "__main__":
    unittest.main()
