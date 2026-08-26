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

    def test_releer_el_mismo_fichero_no_es_un_fallo_aunque_hable_de_errores(self):
        """H3: el texto de un `Read` es el del PROYECTO, no el de un fallo.

        Reproducción del revisor: tres `Read` del mismo módulo —que dentro tiene
        `except OSError as error:`— intercalados con ediciones normales daban «3 veces el
        mismo comando con el mismo fallo: Read: /proyecto/src/guardar.py · corta AHORA».
        Releer un fichero tres veces es rutina, y casi cualquier fuente lleva dentro las
        palabras `error`, `failed` o `denied`.
        """
        fuente = ("def guardar(ruta, datos):\n"
                  "    try:\n"
                  "        ruta.write_text(datos)\n"
                  "    except OSError as error:\n"
                  "        raise RuntimeError('failed to save') from error\n")
        eventos = []
        for i in range(4):
            eventos += self.turno_con_herramienta(
                f"rd{i}", "Read", {"file_path": "/proyecto/src/guardar.py"}, fuente)
            eventos += self.eventos_edicion(f"/proyecto/src/otro_{i}.py", 1)
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertIsNone(informe["sintoma"],
                          "leer no es ejecutar: el contenido del proyecto no es un fallo")
        self.assertEqual(informe["veredicto"], "sano")

    def test_buscar_lo_mismo_varias_veces_tampoco_es_un_fallo(self):
        """La misma guarda para lo que BUSCA: `Grep` devuelve líneas del proyecto."""
        eventos = []
        for i in range(5):
            eventos += self.turno_con_herramienta(
                f"gr{i}", "Grep", {"pattern": "OSError"},
                "src/guardar.py:12:    except OSError as error:  # permission denied")
        self.sesion_claude(tokens=100_000, eventos=eventos)

        self.assertIsNone(self.diagnostico()["sintoma"])

    def test_el_mismo_fallo_ejecutando_si_sigue_siendo_sintoma(self):
        """El contraste que da sentido a la guarda: en `Bash` el texto SÍ delata."""
        eventos = self.eventos_test("node scripts/build.js", 3,
                                    salida="Error: Cannot find module './lib/x'")
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertEqual(informe["sintoma"]["veces"], 3)

    def test_un_read_que_el_harness_marca_roto_si_cuenta(self):
        """Acotar la heurística no ciega el hecho: `is_error` es del harness, no una pista."""
        eventos = []
        for i in range(3):
            eventos += self.turno_con_herramienta(
                f"rx{i}", "Read", {"file_path": "/proyecto/src/no_existe.py"},
                "File does not exist.", is_error=True)
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertIn("no_existe.py", informe["sintoma"]["comando"])

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

        uno = self.diagnostico()
        primero = canario.texto_veredicto(uno)
        dos = self.diagnostico()
        segundo = canario.texto_veredicto(dos)

        self.assertTrue(uno["avisar_modelo"])
        self.assertFalse(dos["avisar_modelo"], "una vez es una vez")
        self.assertIn("claude-quixote-6-20270210", primero)
        self.assertIn("asumo", primero.lower())
        self.assertNotIn("asumo", segundo.lower())
        self.assertNotEqual(segundo, "", "callarse del todo, jamás: la línea de estado sigue")
        self.assertIn("75", segundo, "la vigilancia sigue viva después del aviso")

    def test_diagnosticar_no_gasta_el_aviso_del_modelo_nuevo(self):
        """H1: mirar no es decir. Si el aviso no se imprime, sigue pendiente.

        Antes `diagnosticar` apuntaba el modelo en cuanto lo veía, así que un hook `Stop`
        que callaba —o cualquier informe que nadie llegara a imprimir— se comía el «una
        sola vez» y el usuario no veía el aviso JAMÁS: la ceguera de R1, en silencio.
        """
        self.instalar_fixture("sesion-claude-modelo-nuevo.jsonl")

        for _ in range(3):
            self.assertTrue(self.diagnostico()["avisar_modelo"],
                            "sin imprimir nada, el aviso sigue debiéndose")

        self.assertIn("asumo", canario.texto_veredicto(self.diagnostico()).lower())
        self.assertFalse(self.diagnostico()["avisar_modelo"],
                         "y una vez dicho, ya no se repite")

    def test_la_memoria_solo_guarda_el_modelo_cuando_el_aviso_se_escribe(self):
        """La misma regla, mirada desde el fichero de memoria."""
        self.instalar_fixture("sesion-claude-modelo-nuevo.jsonl")
        memoria = self.cwd / canario.MEMORIA

        informe = self.diagnostico()
        self.assertNotIn("claude-quixote-6-20270210",
                         canario.leer_memoria(self.cwd).get("modelos", []))

        canario.texto_veredicto(informe)

        self.assertTrue(memoria.is_file())
        self.assertIn("claude-quixote-6-20270210",
                      canario.leer_memoria(self.cwd).get("modelos", []))

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

    def sesion_de_n_turnos(self, turnos, *, eventos=(), modelo="claude-opus-5",
                           tokens=900_000):
        cwd = str(self.cwd)
        carpeta = self.claude / canario.normalizar_proyecto(cwd)
        carpeta.mkdir(parents=True, exist_ok=True)
        lineas = [json.dumps({"type": "user", "cwd": cwd,
                              "message": {"role": "user", "content": "hola"}})]
        lineas.extend(eventos)
        for _ in range(turnos):
            lineas.append(json.dumps({
                "type": "assistant", "cwd": cwd,
                "message": {"model": modelo,
                            "usage": {"input_tokens": tokens,
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
        self.sesion_de_n_turnos(cada)              # 900k de 1M: hay motivo de sobra
        primera = json.loads(self.correr("hook-stop").stdout)

        self.sesion_de_n_turnos(cada + 1)          # la parada siguiente, un turno después
        salida = json.loads(self.correr("hook-stop").stdout)

        self.assertIn("systemMessage", primera, "la primera ronda sí habla")
        self.assertNotIn("systemMessage", salida,
                         "barato quiere decir que no habla en todos los turnos")

    def test_hook_stop_vuelve_a_hablar_pasada_otra_ronda(self):
        cada = canario.DEFECTOS["turnos_hook"]
        self.sesion_de_n_turnos(cada)
        self.correr("hook-stop")

        self.sesion_de_n_turnos(cada * 2)
        salida = json.loads(self.correr("hook-stop").stdout)

        self.assertIn("zona de riesgo", salida.get("systemMessage", ""))

    def test_hook_stop_habla_aunque_la_cuenta_no_caiga_en_un_multiplo(self):
        """H2: un `Stop` cubre una cadena entera de herramientas, y la cuenta SALTA.

        Medido sobre tres sesiones reales de esta máquina: 989 turnos repartidos en 33
        paradas (salto medio 25,9 turnos) no caían NI UNA VEZ en un múltiplo de 25, así que
        la capacidad y la posición no habrían sonado en toda la sesión. Lo que manda es
        cuánto ha pasado desde el último aviso, no el resto de una división.
        """
        cada = canario.DEFECTOS["turnos_hook"]
        self.sesion_de_n_turnos(cada - 1)          # parada anterior: aún no toca
        self.assertNotIn("systemMessage", json.loads(self.correr("hook-stop").stdout))

        self.sesion_de_n_turnos(cada * 2 + 1)      # el salto se lleva el múltiplo por delante
        salida = json.loads(self.correr("hook-stop").stdout)

        self.assertIn("zona de riesgo", salida.get("systemMessage", ""),
                      "51 turnos sin decir nada y el aviso tiene que salir")

    def test_hook_stop_no_se_calla_el_modelo_nuevo_en_una_sesion_sana(self):
        """H1 desde el hook: si esperase a un veredicto, el aviso no lo vería nadie."""
        self.sesion_de_n_turnos(3, modelo="claude-quixote-6", tokens=1_000)

        primera = json.loads(self.correr("hook-stop").stdout)
        segunda = json.loads(self.correr("hook-stop").stdout)

        self.assertIn("claude-quixote-6", primera.get("systemMessage", ""))
        self.assertIn("asumo", primera["systemMessage"].lower())
        self.assertTrue(primera.get("continue"))
        self.assertNotIn("systemMessage", segunda, "una vez dicho, se calla")

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

# --------------------------------------------------------------------------- bug 075


class EscriturasDesdeBashTest(BaseConducta):
    """Bug 075: escribir desde la terminal también es tocar un fichero.

    Con un modo de permisos que manda escribir por Bash (`sed -i`, heredocs, `tee`, `git
    commit`), el canario de la 062 no veía ninguna escritura y disparaba «N turnos sin tocar
    un fichero» en una sesión que acababa de fusionar dos unidades (Nate, 25-08: «no debería
    avisar si no hay síntomas»).
    """

    ESCRITURAS = [
        "sed -i '' 's/a/b/' docs/x.md",
        "cat > docs/y.md <<'EOF'\nhola\nEOF",
        "python3 - <<'EOF'\nimport pathlib\npathlib.Path('z').write_text('x')\nEOF",
        "git add docs/x.md && git commit -q -m 'docs: x'",
        "echo hola | tee .runtime/salida.txt",
        "cp a.txt b.txt",
        "mkdir -p .runtime/cierre && echo ok >> .runtime/cierre/log.txt",
    ]

    def _turnos_bash(self, comandos, veces):
        eventos = []
        for i in range(veces):
            comando = comandos[i % len(comandos)]
            eventos += self.turno_con_herramienta(
                f"b{i}", "Bash", {"command": comando}, "")
        return eventos

    def test_escribir_por_bash_no_es_un_turno_seco(self):
        veces = canario.DEFECTOS["turnos_sin_ficheros"] + 10
        self.sesion_claude(tokens=100_000, eventos=self._turnos_bash(self.ESCRITURAS, veces))

        self.assertIsNone(self.diagnostico()["sintoma"])

    def test_solo_mirar_por_bash_sigue_siendo_seco(self):
        veces = canario.DEFECTOS["turnos_sin_ficheros"]
        lecturas = ["ls docs", "grep -n foo docs/x.md", "cat docs/y.md 2>&1 | head",
                    "git status --short", "python3 -c 'print(1)' 2>/dev/null"]
        self.sesion_claude(tokens=100_000, eventos=self._turnos_bash(lecturas, veces))

        informe = self.diagnostico()
        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertEqual(informe["sintoma"]["tipo"], "sin_ficheros")

    def test_redirigir_stderr_no_cuenta_como_escritura(self):
        veces = canario.DEFECTOS["turnos_sin_ficheros"]
        self.sesion_claude(tokens=100_000, eventos=self._turnos_bash(
            ["ls 2>&1", "cat x 2>/dev/null", "grep a b >/dev/null"], veces))

        self.assertEqual(self.diagnostico()["sintoma"]["tipo"], "sin_ficheros")

    def test_sin_comandos_en_el_jsonl_no_hay_aviso(self):
        """R2: un harness que no escribe el comando no da evidencia; sin evidencia no hay aviso."""
        veces = canario.DEFECTOS["turnos_sin_ficheros"] + 5
        eventos = []
        for i in range(veces):
            eventos += self.turno_con_herramienta(f"m{i}", "Bash", {}, "")
        self.sesion_claude(tokens=100_000, eventos=eventos)

        self.assertIsNone(self.diagnostico()["sintoma"])

    def test_la_lista_de_escrituras_vive_junto_a_las_herramientas_de_fichero(self):
        self.assertTrue(hasattr(canario, "ESCRITURAS_DESDE_BASH"))
        for comando in self.ESCRITURAS:
            self.assertTrue(canario.ESCRITURAS_DESDE_BASH.search(comando), comando)


# --------------------------------------------------------------------------- 072 · incidentes


class IncidentesDeLaSesionTest(BaseConducta):
    """072 · R1-R2: hay accidentes que degradan la sesión sin repetir ni un comando.

    Equivocarse de carpeta, deshacer trabajo con git, resolver un conflicto a mano, esconder
    cambios en un `stash` o escribir dentro de `main/` no dejan una racha ni un fallo
    repetido: pasan UNA vez y a partir de ahí el agente trabaja sobre una realidad que ya no
    es la que cree. gentle-ai lo llama «Delegation Stop Rules»: tras un accidente de
    cwd/git/merge/entorno, auditoría fresca.
    """

    def turnos_bash(self, comandos, salida="", *, prefijo="inc"):
        eventos = []
        for i, comando in enumerate(comandos):
            eventos += self.turno_con_herramienta(
                f"{prefijo}{i}", "Bash", {"command": comando}, salida)
        return eventos

    def sesion_con(self, comandos, salida=""):
        self.sesion_claude(tokens=100_000, eventos=self.turnos_bash(comandos, salida))
        return self.diagnostico()

    # --- R1: cada patrón, con su umbral ------------------------------------

    def test_los_umbrales_de_incidente_viven_en_defectos(self):
        for clave in ("cwd_erroneo", "git_destructivo", "conflicto", "stash",
                      "escritura_en_main"):
            self.assertIn(clave, canario.DEFECTOS)
            self.assertGreater(canario.DEFECTOS[clave], 0)

    def test_dos_cd_a_una_carpeta_que_no_existe(self):
        informe = self.sesion_con(
            ["cd worktrees/072-x && ls", "cd worktrees/072-x && ls"],
            salida="/bin/bash: line 1: cd: worktrees/072-x: No such file or directory")

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertEqual(informe["sintoma"]["tipo"], "incidente")
        self.assertEqual(informe["sintoma"]["patron"], "cwd_erroneo")

    def test_un_solo_cd_fallido_todavia_no_es_un_accidente(self):
        informe = self.sesion_con(
            ["cd worktrees/072-x && ls"],
            salida="/bin/bash: line 1: cd: worktrees/072-x: No such file or directory")

        self.assertIsNone(informe["sintoma"])

    def test_un_cd_que_funciona_no_cuenta(self):
        informe = self.sesion_con(["cd main && git status", "cd main && git status"],
                                  salida="nothing to commit, working tree clean")

        self.assertIsNone(informe["sintoma"])

    def test_deshacer_trabajo_con_git_cuenta_a_la_primera(self):
        for comando in ("git reset --hard HEAD~1",
                        "git checkout -- docs/x.md",
                        "git restore visor/tests/test_x.py"):
            with self.subTest(comando=comando):
                self.setUp()
                informe = self.sesion_con([comando])
                self.assertEqual(informe["sintoma"]["patron"], "git_destructivo", comando)

    def test_un_conflicto_de_merge_cuenta_a_la_primera(self):
        informe = self.sesion_con(
            ["git merge --no-ff 072-incidentes"],
            salida="CONFLICT (content): Merge conflict in docs/05-trabajo/ESTADO.md\n"
                   "Automatic merge failed; fix conflicts and then commit the result.")

        self.assertEqual(informe["sintoma"]["patron"], "conflicto")

    def test_el_stash_cuenta_a_la_primera(self):
        informe = self.sesion_con(["git stash"])

        self.assertEqual(informe["sintoma"]["patron"], "stash")

    def test_mirar_el_stash_no_es_esconder_nada(self):
        informe = self.sesion_con(["git stash list", "git stash show -p"])

        self.assertIsNone(informe["sintoma"])

    def test_escribir_dentro_de_main_cuenta_a_la_primera(self):
        informe = self.sesion_con(["sed -i '' 's/a/b/' main/web/abrir.py"])

        self.assertEqual(informe["sintoma"]["patron"], "escritura_en_main")

    def test_commitear_dentro_de_main_cuenta_a_la_primera(self):
        informe = self.sesion_con(["git -C main commit -m 'arreglo'"])

        self.assertEqual(informe["sintoma"]["patron"], "escritura_en_main")

    def test_editar_un_fichero_de_main_con_la_herramienta_de_edicion(self):
        self.sesion_claude(tokens=100_000, eventos=self.turno_con_herramienta(
            "e0", "Write", {"file_path": str(self.cwd / "main/web/abrir.py"),
                            "content": "x"}, "The file has been written."))

        self.assertEqual(self.diagnostico()["sintoma"]["patron"], "escritura_en_main")

    def test_leer_main_y_actualizarlo_con_pull_no_es_un_accidente(self):
        informe = self.sesion_con(["git -C main pull --ff-only",
                                   "git -C main log --oneline -5",
                                   "grep -rn 'abrir' main/web/abrir.py",
                                   "git -C main worktree list"])

        self.assertIsNone(informe["sintoma"])

    def test_una_sesion_limpia_sigue_sana(self):
        informe = self.sesion_con(["ls docs", "git status --short", "python3 -V"])

        self.assertEqual(informe["veredicto"], "sano")

    def test_los_umbrales_de_incidente_se_declaran_en_la_config(self):
        self.config({"cwd_erroneo": 1})
        informe = self.sesion_con(
            ["cd worktrees/072-x && ls"],
            salida="/bin/bash: line 1: cd: worktrees/072-x: No such file or directory")

        self.assertEqual(informe["sintoma"]["patron"], "cwd_erroneo")

    # --- R2: el aviso y el parte dicen patrón, turno y acción ---------------

    def test_el_aviso_nombra_el_patron_y_que_hacer(self):
        informe = self.sesion_con(["git stash"])

        texto = canario.texto_veredicto(informe)

        self.assertIn("stash", texto)
        self.assertIn("revisión fresca", texto)
        self.assertIn("canario.py retomada", texto)

    def test_el_aviso_del_cwd_manda_cortar_la_sesion(self):
        informe = self.sesion_con(
            ["cd worktrees/072-x && ls", "cd worktrees/072-x && ls"],
            salida="/bin/bash: line 1: cd: worktrees/072-x: No such file or directory")

        self.assertIn("sesión NUEVA", canario.texto_veredicto(informe))

    def test_el_aviso_no_bloquea_y_dice_el_turno(self):
        informe = self.sesion_con(["ls docs", "ls main", "git stash"])

        self.assertEqual(informe["sintoma"]["turno"], 3)
        self.assertIn("turno 3", canario.texto_veredicto(informe))

    def test_el_parte_de_retomada_nombra_patron_turno_y_accion(self):
        informe = self.sesion_con(["ls docs", "git stash"])

        parte = canario.texto_retomada(self.cwd, incidentes=informe["incidentes"])

        self.assertIn("Incidentes", parte)
        self.assertIn("stash", parte)
        self.assertIn("turno 2", parte)
        self.assertIn("revisión fresca", parte)

    def test_el_parte_sin_incidentes_no_inventa_la_seccion(self):
        parte = canario.texto_retomada(self.cwd, incidentes=[])

        self.assertNotIn("Incidentes", parte)

    def test_el_comando_retomada_trae_los_incidentes_de_la_sesion_real(self):
        """De punta a punta: `canario.py retomada` mira la sesión, no solo los papeles."""
        import os
        self.sesion_con(["git stash"])

        r = subprocess.run(
            [sys.executable, str(CANARIO_PATH), "retomada",
             "--cwd", str(self.cwd), "--workspace", str(self.cwd)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ,
                 "CANARIO_CLAUDE_PROJECTS": str(self.claude),
                 "CANARIO_CODEX_SESSIONS": str(self.codex)})

        self.assertEqual(r.returncode, 0)
        self.assertIn("Incidentes", r.stdout)
        self.assertIn("stash", r.stdout)

    # --- R3: el caso límite y la no-regresión ------------------------------

    def test_lo_que_hace_un_subagente_no_cuenta_en_la_sesion_del_padre(self):
        """El recibo de `ejecucion.py` trae DENTRO los comandos del subagente."""
        recibo = ("worktree: worktrees/072-x\n"
                  "$ git stash\n"
                  "$ git reset --hard HEAD~1\n"
                  "CONFLICT (content): Merge conflict in docs/x.md\n"
                  "cd: worktrees/072-x: No such file or directory\n")
        informe = self.sesion_con(
            ["python3 docs/00-metodo/scripts/ejecucion.py --unidad 072-x --modelo opus",
             "python3 docs/00-metodo/scripts/ejecucion.py --unidad 072-x --modelo opus"],
            salida=recibo)

        self.assertIsNone(informe["sintoma"],
                          "los comandos del subagente son suyos, no de esta sesión")

    def test_la_herramienta_de_subagente_tampoco_cuenta(self):
        self.sesion_claude(tokens=100_000, eventos=self.turno_con_herramienta(
            "t0", "Task", {"prompt": "git stash y luego git reset --hard"},
            "hecho: git stash, git reset --hard HEAD~1"))

        self.assertIsNone(self.diagnostico()["sintoma"])

    def test_el_comando_repetido_sigue_mandando_sobre_el_incidente(self):
        """No-regresión: los avisos de siempre no cambian de forma ni de prioridad."""
        eventos = self.par_fallido_claude("node scripts/build.js", "Error: cannot find module",
                                          canario.DEFECTOS["repeticiones"])
        eventos += self.turnos_bash(["git stash"])
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertEqual(informe["sintoma"]["tipo"], "repeticion")
        self.assertIn("YA está degradando", canario.texto_veredicto(informe))

    def test_el_atasco_sin_error_sigue_mandando_sobre_el_incidente(self):
        eventos = self.eventos_edicion("src/app.py", canario.DEFECTOS["ediciones_seguidas"])
        eventos += self.turnos_bash(["git stash"])
        self.sesion_claude(tokens=100_000, eventos=eventos)

        self.assertEqual(self.diagnostico()["sintoma"]["tipo"], "ediciones")

    def test_los_incidentes_viajan_en_el_informe_aunque_mande_otro_sintoma(self):
        eventos = self.eventos_edicion("src/app.py", canario.DEFECTOS["ediciones_seguidas"])
        eventos += self.turnos_bash(["git stash"])
        self.sesion_claude(tokens=100_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertEqual([i["patron"] for i in informe["incidentes"]], ["stash"])

    def test_una_sesion_de_codex_tambien_ve_los_accidentes(self):
        eventos = [
            json.dumps({"type": "response_item", "payload": {
                "type": "function_call", "call_id": "c1", "name": "shell",
                "arguments": json.dumps({"command": ["bash", "-lc", "git stash"]})}}),
            json.dumps({"type": "response_item", "payload": {
                "type": "function_call_output", "call_id": "c1",
                "output": "Saved working directory"}}),
        ]
        self.sesion_codex(tokens=50_000, eventos=eventos)

        informe = self.diagnostico()

        self.assertEqual(informe["sintoma"]["patron"], "stash")

    # --- R3: lo medido sobre los 63 transcripts reales del workspace --------
    #
    # Cada uno de estos casos disparaba un aviso falso al medir la unidad contra las
    # sesiones reales de este taller. Quedan escritos como test para que no vuelvan.

    def test_consultar_no_es_escribir_aunque_el_verbo_se_parezca(self):
        informe = self.sesion_con([
            "git -C main merge-base --is-ancestor 8e16127 main",
            "git -C main branch --show-current",
            "git -C main worktree add -b 072-x ../worktrees/072-x origin/main",
            "cd main && git checkout main && git pull --ff-only",
        ])

        self.assertIsNone(informe["sintoma"],
                          "actualizar el clon y colgarle un worktree es el uso normal de main/")

    def test_el_merge_del_cierre_sin_gh_no_es_un_accidente(self):
        """ADR-009: es la única excepción nombrada. Avisar ahí sería gritar en cada cierre."""
        informe = self.sesion_con(["git -C main merge --no-ff 072-incidentes -m 'Merge'"])

        self.assertIsNone(informe["sintoma"])

    def test_pero_si_ese_merge_choca_el_conflicto_si_se_ve(self):
        informe = self.sesion_con(
            ["git -C main merge --no-ff 072-incidentes -m 'Merge'"],
            salida="CONFLICT (content): Merge conflict in docs/05-trabajo/ESTADO.md")

        self.assertEqual(informe["sintoma"]["patron"], "conflicto")

    def test_mencionar_una_ruta_de_main_no_es_escribir_en_main(self):
        informe = self.sesion_con([
            "cp main/plantilla/docs/00-metodo/scripts/sanidad.py docs/00-metodo/scripts/",
            "python3 - <<'EOF'\nfrom pathlib import Path\n"
            "p = Path('docs/bugs/080-x.md')\np.write_text(p.read_text() + 'main/visor/x')\nEOF",
            "python3 main/web/abrir.py --workspace . --apartado contratos > .runtime/log.txt",
        ])

        self.assertIsNone(informe["sintoma"],
                          "leer de main/ y nombrarlo de pasada no lo toca")

    def test_un_fallo_suelto_de_fichero_no_es_perderse_de_carpeta(self):
        informe = self.sesion_con(
            ["cd worktrees/072-x && cat falta.txt", "cd worktrees/072-x && cat falta.txt"],
            salida="cat: falta.txt: No such file or directory")

        self.assertIsNone(informe["sintoma"],
                          "el «no such file» tiene que hablar del `cd`, no de un fichero")

    def test_el_aviso_de_incidente_no_bloquea_el_hook(self):
        self.sesion_claude(tokens=100_000, eventos=self.turnos_bash(["git stash"]))

        r = subprocess.run(
            [sys.executable, str(CANARIO_PATH), "hook-stop",
             "--cwd", str(self.cwd), "--workspace", str(self.cwd)],
            input="{}", capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**__import__("os").environ,
                 "CANARIO_CLAUDE_PROJECTS": str(self.claude),
                 "CANARIO_CODEX_SESSIONS": str(self.codex)})
        salida = json.loads(r.stdout)

        self.assertEqual(r.returncode, 0)
        self.assertTrue(salida["continue"])
        self.assertIn("stash", salida["systemMessage"])
