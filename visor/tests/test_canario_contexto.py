"""023-canario-contexto · el canario lee las señales que el harness ya escribe y avisa.

Cubre los R1-R8 del contrato de la unidad y los R-1701..R-1704 del plano de la actividad
`canario-contexto`:

  R1 / R-1701  % y veredicto leyendo el JSONL de Claude Code, sin red
  R2           lo mismo con los rollouts de Codex CLI
  R3 / R-1702  umbral por MODELO desde la tabla del workspace, default global 80
  R4 / R-1701  el hook PreCompact sembrado por el bootstrap avisa aunque nadie mire
  R5 / R-1703  `retomada`: el parte pre-rellenado desde ESTADO.md + la unidad en obra
  R6           sin sesión, corrupto o harness desconocido: calla y sale con éxito
  R7           varias sesiones: la más reciente por mtime, y lo dice
  R8           segunda señal, de CONDUCTA, con aviso propio y prioritario
  R-1704       modelo sin ventana conocida: avisa de la incertidumbre, no inventa número
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CANARIO_PATH = RAIZ / "plantilla/docs/00-metodo/scripts/canario.py"
BOOTSTRAP_PATH = RAIZ / "visor/bootstrap.py"


def _cargar(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


canario = _cargar("canario_bajo_test", CANARIO_PATH)
bootstrap = _cargar("bootstrap_bajo_test", BOOTSTRAP_PATH)


class BaseCanario(unittest.TestCase):
    """Un HOME de juguete con las dos jerarquías de sesión y un workspace vacío."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="canario-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.claude = self.base / "claude-projects"
        self.codex = self.base / "codex-sessions"
        self.claude.mkdir()
        self.codex.mkdir()
        self.cwd = self.base / "workspace"
        self.cwd.mkdir()

    # --- fábricas de sesiones sintéticas ------------------------------------

    # `claude-opus-4-1-…` y no `claude-opus-5`: desde el bug 062 la tabla da 1.000.000 a los
    # modelos actuales, y estos tests hablan de porcentajes de una ventana de 200.000. El
    # modelo del fixture cambia; lo que se afirma, no.
    def sesion_claude(self, *, tokens, modelo="claude-opus-4-1-20250805",
                      nombre="sesion.jsonl",
                      eventos=(), cwd=None, mtime=None):
        cwd = str(cwd or self.cwd)
        carpeta = self.claude / canario.normalizar_proyecto(cwd)
        carpeta.mkdir(parents=True, exist_ok=True)
        lineas = [json.dumps({"type": "user", "cwd": cwd,
                              "message": {"role": "user", "content": "hola"}})]
        lineas.extend(eventos)
        lineas.append(json.dumps({
            "type": "assistant", "cwd": cwd,
            "message": {"model": modelo,
                        "usage": {"input_tokens": tokens,
                                  "cache_read_input_tokens": 0,
                                  "cache_creation_input_tokens": 0,
                                  "output_tokens": 100}},
        }))
        fichero = carpeta / nombre
        fichero.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        if mtime is not None:
            os.utime(fichero, (mtime, mtime))
        return fichero

    def par_fallido_claude(self, comando, fallo, veces):
        """`veces` repeticiones del MISMO comando con el MISMO fallo (señal de conducta)."""
        lineas = []
        for i in range(veces):
            uso = f"tu_{i}"
            lineas.append(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": uso, "name": "Bash",
                     "input": {"command": comando}}]},
            }))
            lineas.append(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": uso,
                     "is_error": True, "content": fallo}]},
            }))
        return lineas

    def sesion_codex(self, *, tokens, ventana=258400, nombre="rollout-2026-08-18T10-00-00.jsonl",
                     cwd=None, mtime=None, eventos=()):
        cwd = str(cwd or self.cwd)
        carpeta = self.codex / "2026" / "08" / "18"
        carpeta.mkdir(parents=True, exist_ok=True)
        lineas = [json.dumps({"type": "session_meta",
                              "payload": {"id": "abc", "cwd": cwd}})]
        lineas.extend(eventos)
        lineas.append(json.dumps({
            "type": "event_msg",
            "payload": {"type": "token_count",
                        "info": {"total_token_usage": {"total_tokens": 9_000_000},
                                 "last_token_usage": {"total_tokens": tokens},
                                 "model_context_window": ventana}},
        }))
        fichero = carpeta / nombre
        fichero.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        if mtime is not None:
            os.utime(fichero, (mtime, mtime))
        return fichero

    def config(self, datos):
        destino = self.cwd / ".claude"
        destino.mkdir(exist_ok=True)
        (destino / "canario.json").write_text(json.dumps(datos), encoding="utf-8")

    def diagnostico(self):
        return canario.diagnosticar(raiz=self.cwd, cwd=self.cwd,
                                    claude_projects=self.claude,
                                    codex_sessions=self.codex)


class OrtografiaDeRutaTest(BaseCanario):
    """Bug 024: el harness guarda la sesión con el cwd TAL CUAL lo vio; el canario debe
    encontrarla aunque la ruta lleve un symlink por medio (/var → /private/var en macOS)
    o se entre por la otra ortografía. Rojo sin el arreglo, verde con él."""

    def _workspace_con_symlink(self):
        real = self.base / "workspace-real"
        real.mkdir()
        enlace = self.base / "workspace-enlace"
        try:
            enlace.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema no permite crear symlinks (Windows sin privilegio)")
        return real, enlace

    def test_sesion_guardada_con_la_ruta_del_symlink_se_encuentra(self):
        # El usuario trabaja entrando por el enlace: el harness nombra la carpeta con ESA
        # ortografía. Es exactamente el caso de los 26 rojos del 18-08 (TMPDIR /var vs
        # /private/var).
        real, enlace = self._workspace_con_symlink()
        self.sesion_claude(tokens=100_000, cwd=str(enlace))

        informe = canario.diagnosticar(raiz=enlace, cwd=enlace,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)

        self.assertEqual(informe["veredicto"], "sano")
        self.assertEqual(informe["harness"], "claude")

    def test_sesion_guardada_con_la_ruta_real_se_encuentra_entrando_por_el_enlace(self):
        # El caso inverso: el harness guardó la ortografía CANÓNICA (resuelta del todo) y
        # el usuario invoca el canario desde la ruta simbólica. La canónica es el puente:
        # una tercera ortografía intermedia no es alcanzable y queda fuera del contrato.
        real, enlace = self._workspace_con_symlink()
        self.sesion_claude(tokens=100_000, cwd=str(real.resolve()))

        informe = canario.diagnosticar(raiz=enlace, cwd=enlace,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)

        self.assertEqual(informe["veredicto"], "sano")

    def test_un_rollout_de_codex_con_la_otra_ortografia_tambien_cuenta(self):
        real, enlace = self._workspace_con_symlink()
        self.sesion_codex(tokens=100_000, cwd=str(enlace))

        informe = canario.diagnosticar(raiz=real, cwd=real,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)

        self.assertEqual(informe["harness"], "codex")
        self.assertEqual(informe["veredicto"], "sano")

    def test_el_techo_de_ascenso_sigue_en_pie_con_symlink(self):
        # La doble ortografía no puede reabrir la puerta que _ancestros cerró: una sesión
        # del PADRE del workspace sigue sin colarse.
        real, enlace = self._workspace_con_symlink()
        self.sesion_claude(tokens=100_000, cwd=str(self.base))

        informe = canario.diagnosticar(raiz=enlace, cwd=enlace,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)

        self.assertEqual(informe["veredicto"], "sin_datos")


class CapacidadClaudeTest(BaseCanario):
    """R1 / R3 / R-1701: el % de la ventana y el veredicto a los dos lados del umbral."""

    def test_por_debajo_del_umbral_es_sano_y_no_hay_warning(self):
        self.sesion_claude(tokens=100_000)          # 50 % de 200k

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sano")
        self.assertEqual(informe["harness"], "claude")
        self.assertEqual(round(informe["porcentaje"]), 50)
        self.assertNotIn("CANARIO", canario.texto_veredicto(informe))

    def test_en_el_umbral_es_aviso_con_el_texto_de_capacidad(self):
        self.sesion_claude(tokens=160_000)          # 80 % de 200k, la frontera

        informe = self.diagnostico()
        texto = canario.texto_veredicto(informe)

        self.assertEqual(informe["veredicto"], "aviso")
        self.assertEqual(round(informe["porcentaje"]), 80)
        self.assertIn("zona de riesgo", texto)
        self.assertIn("retomada", texto)
        self.assertIn("sesión nueva", texto)

    def test_justo_por_debajo_de_la_frontera_sigue_sano(self):
        self.sesion_claude(tokens=159_000)

        self.assertEqual(self.diagnostico()["veredicto"], "sano")

    def test_no_abre_red_ni_lanza_procesos(self):
        """R1: 'sin red ni llamadas a modelos' — el canario no importa clientes de red."""
        fuente = CANARIO_PATH.read_text(encoding="utf-8")

        for prohibido in ("urllib", "requests", "http.client", "socket", "anthropic"):
            self.assertNotIn(f"import {prohibido}", fuente)


class UmbralPorModeloTest(BaseCanario):
    """R3 / R-1702: tabla por modelo con default global; cada modelo usa SU cifra."""

    def test_sin_entrada_propia_manda_el_default_de_80(self):
        self.sesion_claude(tokens=150_000, modelo="claude-sonnet-5")   # 75 %

        informe = self.diagnostico()

        self.assertEqual(informe["umbral"], 80)
        self.assertEqual(informe["veredicto"], "sano")

    def test_el_modelo_con_cifra_propia_avisa_antes(self):
        self.config({"umbral_default": 80,
                     "umbrales": {"claude-opus-4-1-20250805": 60}})
        self.sesion_claude(tokens=150_000, modelo="claude-opus-4-1-20250805")   # 75 %

        informe = self.diagnostico()

        self.assertEqual(informe["umbral"], 60)
        self.assertEqual(informe["veredicto"], "aviso")

    def test_la_tabla_no_contagia_a_los_demas_modelos(self):
        self.config({"umbral_default": 80, "umbrales": {"claude-opus-5": 60}})
        self.sesion_claude(tokens=150_000, modelo="claude-sonnet-5")   # 75 %

        informe = self.diagnostico()

        self.assertEqual(informe["umbral"], 80)
        self.assertEqual(informe["veredicto"], "sano")

    def test_modelo_sin_ventana_conocida_asume_la_menor_y_lo_dice(self):
        """R-1704 del plano, releída por el R1 del bug 062.

        El plano decía «sin ventana publicada NO se inventa un número», y el canario se
        callaba. En campo eso salió mal: los modelos con los que se trabaja no estaban en la
        tabla y la vigilancia quedó apagada meses. La regla nueva conserva el fondo —no
        inventar— y quita el efecto: se asume la MENOR ventana conocida, que es un techo
        prudente, se sigue vigilando y se DICE que es una suposición.
        """
        self.sesion_claude(tokens=150_000, modelo="modelo-de-otro-lab")

        informe = self.diagnostico()
        texto = canario.texto_veredicto(informe)

        self.assertEqual(informe["ventana"], canario.VENTANA_MINIMA)
        self.assertTrue(informe["ventana_asumida"])
        self.assertEqual(round(informe["porcentaje"]), 75)
        self.assertIn("modelo-de-otro-lab", texto)
        self.assertIn("asumo", texto.lower())

    def test_un_porcentaje_imposible_se_declara_incierto_en_vez_de_cantarlo(self):
        """Caso de campo 18-08: claude-fable-5 gastó 202.822 tokens con la tabla en 200.000.

        Más del 100 % no es 'el doble de llena': es que la ventana apuntada es falsa. Un
        número imposible dicho con aplomo es peor que no decir nada.
        """
        self.sesion_claude(tokens=202_822, modelo="claude-opus-4-1-20250805")

        informe = self.diagnostico()
        texto = canario.texto_veredicto(informe)

        self.assertEqual(informe["veredicto"], "incierto")
        self.assertIsNone(informe["porcentaje"])
        self.assertEqual(informe["ventana_incoherente"], 200_000)
        self.assertIn("no cuadra", texto)
        self.assertIn("canario.json", texto)

    def test_la_ventana_declarada_arregla_el_porcentaje_imposible(self):
        self.config({"ventanas": {"claude-opus-5": 400_000}})
        self.sesion_claude(tokens=202_822, modelo="claude-opus-5")

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sano")
        self.assertEqual(round(informe["porcentaje"]), 51)

    def test_la_ventana_declarada_en_config_resuelve_la_incertidumbre(self):
        self.config({"ventanas": {"modelo-de-otro-lab": 100_000}})
        self.sesion_claude(tokens=90_000, modelo="modelo-de-otro-lab")

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "aviso")
        self.assertEqual(round(informe["porcentaje"]), 90)


class CapacidadCodexTest(BaseCanario):
    """R2: mismo veredicto leyendo `token_count` + `model_context_window` de un rollout."""

    def test_rollout_por_debajo_del_umbral(self):
        self.sesion_codex(tokens=50_000, ventana=200_000)

        informe = self.diagnostico()

        self.assertEqual(informe["harness"], "codex")
        self.assertEqual(round(informe["porcentaje"]), 25)
        self.assertEqual(informe["veredicto"], "sano")

    def test_rollout_sobre_el_umbral_avisa(self):
        self.sesion_codex(tokens=180_000, ventana=200_000)

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "aviso")
        self.assertEqual(round(informe["porcentaje"]), 90)

    def test_usa_la_ventana_del_propio_rollout_no_una_tabla(self):
        self.sesion_codex(tokens=180_000, ventana=400_000)

        informe = self.diagnostico()

        self.assertEqual(informe["ventana"], 400_000)
        self.assertEqual(informe["veredicto"], "sano")


class ConductaTest(BaseCanario):
    """R8: la segunda señal, con aviso propio y prioridad sobre la de capacidad."""

    def test_tres_repeticiones_del_mismo_fallo_dan_sintomas_con_contexto_bajo(self):
        eventos = self.par_fallido_claude("pytest -q", "ImportError: no module named x", 3)
        self.sesion_claude(tokens=20_000, eventos=eventos)             # 10 %: contexto bajo

        informe = self.diagnostico()
        texto = canario.texto_veredicto(informe)

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertEqual(informe["sintoma"]["veces"], 3)
        self.assertIn("pytest -q", informe["sintoma"]["comando"])
        self.assertIn("corta", texto.lower())
        self.assertNotIn("zona de riesgo", texto)

    def test_dos_repeticiones_todavia_no_son_sintomas(self):
        eventos = self.par_fallido_claude("pytest -q", "ImportError: no module named x", 2)
        self.sesion_claude(tokens=20_000, eventos=eventos)

        self.assertEqual(self.diagnostico()["veredicto"], "sano")

    def test_el_mismo_comando_con_fallos_distintos_no_es_sintoma(self):
        eventos = []
        for i in range(4):
            eventos.extend(self.par_fallido_claude(
                "curl -s https://api.ejemplo/v1/cosas", f"fallo distinto {i}", 1))
        self.sesion_claude(tokens=20_000, eventos=eventos)

        self.assertEqual(self.diagnostico()["veredicto"], "sano")

    def test_el_umbral_de_repeticiones_es_configurable(self):
        self.config({"repeticiones": 2})
        eventos = self.par_fallido_claude("sh visor/tests/run-fast", "FAILED test_x", 2)
        self.sesion_claude(tokens=20_000, eventos=eventos)

        self.assertEqual(self.diagnostico()["veredicto"], "sintomas")

    def test_la_conducta_manda_sobre_la_capacidad_y_solo_sale_un_aviso(self):
        eventos = self.par_fallido_claude("pytest -q", "ImportError: no module named x", 3)
        self.sesion_claude(tokens=190_000, eventos=eventos)            # 95 %: también aviso

        informe = self.diagnostico()
        texto = canario.texto_veredicto(informe)

        self.assertEqual(informe["veredicto"], "sintomas")
        self.assertIn("ya está degradando", texto.lower())
        self.assertNotIn("zona de riesgo", texto)

    def test_tambien_lee_la_conducta_de_un_rollout_de_codex(self):
        eventos = []
        for i in range(3):
            eventos.append(json.dumps({
                "type": "response_item",
                "payload": {"type": "function_call", "name": "shell",
                            "call_id": f"c{i}",
                            "arguments": json.dumps({"command": ["pytest", "-q"]})},
            }))
            eventos.append(json.dumps({
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": f"c{i}",
                            "output": "error: ImportError no module named x"},
            }))
        self.sesion_codex(tokens=10_000, ventana=200_000, eventos=eventos)

        self.assertEqual(self.diagnostico()["veredicto"], "sintomas")


class DegradacionSilenciosaTest(BaseCanario):
    """R6: sin sesión, corrupta o desconocida, el canario calla y sale con éxito."""

    def test_sin_ninguna_sesion_no_dice_nada(self):
        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sin_datos")
        self.assertEqual(canario.texto_veredicto(informe), "")

    def test_jsonl_corrupto_no_rompe(self):
        carpeta = self.claude / canario.normalizar_proyecto(str(self.cwd))
        carpeta.mkdir(parents=True)
        (carpeta / "sesion.jsonl").write_text("{no es json\n\x00\n", encoding="utf-8")

        informe = self.diagnostico()

        self.assertEqual(informe["veredicto"], "sin_datos")
        self.assertEqual(canario.texto_veredicto(informe), "")

    def test_jsonl_sin_uso_de_tokens_no_rompe(self):
        carpeta = self.claude / canario.normalizar_proyecto(str(self.cwd))
        carpeta.mkdir(parents=True)
        (carpeta / "sesion.jsonl").write_text(
            json.dumps({"type": "user", "message": {"content": "hola"}}) + "\n",
            encoding="utf-8")

        self.assertEqual(self.diagnostico()["veredicto"], "sin_datos")

    def test_config_corrupta_cae_a_los_defaults(self):
        (self.cwd / ".claude").mkdir()
        (self.cwd / ".claude/canario.json").write_text("{roto", encoding="utf-8")
        self.sesion_claude(tokens=160_000)

        informe = self.diagnostico()

        self.assertEqual(informe["umbral"], 80)
        self.assertEqual(informe["veredicto"], "aviso")

    def test_el_comando_sale_con_exito_en_una_carpeta_sin_sesiones(self):
        entorno = dict(os.environ)
        entorno["CANARIO_CLAUDE_PROJECTS"] = str(self.claude)
        entorno["CANARIO_CODEX_SESSIONS"] = str(self.codex)
        r = subprocess.run([sys.executable, str(CANARIO_PATH), "--cwd", str(self.cwd),
                            "--workspace", str(self.cwd)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=entorno)

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.stderr.strip(), "")

    def test_el_aviso_nunca_es_bloqueante(self):
        """R6 / C-1705: con warning en pantalla, el proceso sigue saliendo con 0."""
        self.sesion_claude(tokens=190_000)
        entorno = dict(os.environ)
        entorno["CANARIO_CLAUDE_PROJECTS"] = str(self.claude)
        entorno["CANARIO_CODEX_SESSIONS"] = str(self.codex)
        r = subprocess.run([sys.executable, str(CANARIO_PATH), "--cwd", str(self.cwd),
                            "--workspace", str(self.cwd)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=entorno)

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("zona de riesgo", r.stdout)


class EleccionDeSesionTest(BaseCanario):
    """R7: con varias sesiones del mismo workspace, la más reciente por mtime, y dicho."""

    def test_elige_la_mas_reciente_y_nombra_el_fichero(self):
        ahora = time.time()
        self.sesion_claude(tokens=20_000, nombre="vieja.jsonl", mtime=ahora - 5000)
        nueva = self.sesion_claude(tokens=190_000, nombre="nueva.jsonl", mtime=ahora - 10)

        informe = self.diagnostico()

        self.assertEqual(Path(informe["fichero"]).name, "nueva.jsonl")
        self.assertEqual(informe["veredicto"], "aviso")
        self.assertIn("nueva.jsonl", canario.texto_veredicto(informe))
        self.assertEqual(Path(informe["fichero"]), nueva)

    def test_entre_harnesses_tambien_gana_el_mas_reciente(self):
        ahora = time.time()
        self.sesion_claude(tokens=20_000, mtime=ahora - 5000)
        self.sesion_codex(tokens=190_000, ventana=200_000, mtime=ahora - 10)

        informe = self.diagnostico()

        self.assertEqual(informe["harness"], "codex")

    def test_una_sesion_abierta_POR_ENCIMA_del_workspace_no_cuenta(self):
        """Visto en real el 18-08: `/Users/x` es ancestro de todo y su sesión se colaba."""
        self.sesion_claude(tokens=190_000, cwd=self.base)      # el padre del workspace

        self.assertEqual(self.diagnostico()["veredicto"], "sin_datos")

    def test_desde_un_worktree_cuenta_la_sesion_del_workspace_que_lo_posee(self):
        worktree = self.cwd / "worktrees" / "023-canario-contexto"
        worktree.mkdir(parents=True)
        self.sesion_claude(tokens=190_000)                     # sesión del workspace padre

        informe = canario.diagnosticar(raiz=worktree, cwd=worktree,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)

        self.assertEqual(informe["veredicto"], "aviso")

    def test_una_sesion_de_otro_workspace_no_cuenta(self):
        otro = self.base / "otro-workspace"
        otro.mkdir()
        self.sesion_claude(tokens=190_000, cwd=otro)

        self.assertEqual(self.diagnostico()["veredicto"], "sin_datos")

    def test_la_sesion_del_workspace_vale_desde_un_subdirectorio(self):
        """Los worktrees cuelgan del workspace: la sesión del padre sigue siendo la tuya."""
        sub = self.cwd / "worktrees" / "023-x"
        sub.mkdir(parents=True)
        self.sesion_claude(tokens=190_000)

        informe = canario.diagnosticar(raiz=self.cwd, cwd=sub,
                                       claude_projects=self.claude,
                                       codex_sessions=self.codex)

        self.assertEqual(informe["veredicto"], "aviso")


class RetomadaTest(BaseCanario):
    """R5 / R-1703: el parte pre-rellenado desde los papeles, con sus ocho secciones."""

    SECCIONES = ("Objetivo", "Estado", "Decisiones", "Ficheros", "Último verde",
                 "Siguiente paso", "No repetir", "Fuera de alcance")

    def workspace_de_juguete(self):
        trabajo = self.cwd / "docs/05-trabajo/023-canario-contexto"
        trabajo.mkdir(parents=True)
        (self.cwd / "docs/05-trabajo/ESTADO.md").write_text(
            "# Estado del proyecto\n\n"
            "## Ahora mismo\n\n- 023-canario-contexto en obra\n\n"
            "## Pendiente\n\n- cerrar la 023\n", encoding="utf-8")
        (trabajo / "especificacion.md").write_text(
            "---\nunidad: 023-canario-contexto\ntipo: feature\nestado: en_obra\n"
            "ficheros:\n  - plantilla/docs/00-metodo/scripts/canario.py\n  - visor/bootstrap.py\n"
            "---\n\n"
            "# 023 · Canario de contexto\n\n"
            "## Qué (el contrato, en idioma de negocio)\n\n"
            "Avisar fuerte cuando la sesión se degrade y dejar escrito el parte de retomada.\n\n"
            "## Diseño conversado\n\n- **Decisión:** lectura PASIVA de las señales del harness.\n\n"
            "## Fuera de alcance\n\n- Bloquear el auto-compact.\n- Telemetría.\n\n"
            "## Plan de trabajo\n\n- [x] 1. Tests en rojo\n- [ ] 2. Implementar\n",
            encoding="utf-8")
        (trabajo / "hallazgos.md").write_text(
            "---\nunidad: 023-canario-contexto\nrevisor: no\n---\n\n"
            "# 023 · Hallazgos de la obra\n\n"
            "## Evidencia de verificación (obligatorio)\n\n"
            "```\nRan 30 tests OK (2026-08-18)\n```\n", encoding="utf-8")
        return trabajo

    def test_el_parte_trae_las_ocho_secciones(self):
        self.workspace_de_juguete()

        parte = canario.texto_retomada(self.cwd)

        for seccion in self.SECCIONES:
            self.assertIn(seccion, parte)

    def test_el_parte_nombra_la_unidad_en_obra_y_sus_ficheros(self):
        self.workspace_de_juguete()

        parte = canario.texto_retomada(self.cwd)

        self.assertIn("023-canario-contexto", parte)
        self.assertIn("plantilla/docs/00-metodo/scripts/canario.py", parte)
        self.assertIn("visor/bootstrap.py", parte)

    def test_el_parte_arrastra_el_ultimo_verde_y_el_siguiente_paso_del_plan(self):
        self.workspace_de_juguete()

        parte = canario.texto_retomada(self.cwd)

        self.assertIn("Ran 30 tests OK", parte)
        self.assertIn("2. Implementar", parte)

    def test_el_parte_no_pasa_de_2000_tokens(self):
        trabajo = self.workspace_de_juguete()
        relleno = "\n".join(f"- decisión número {i} con su porqué largo" for i in range(4000))
        (trabajo / "especificacion.md").write_text(
            (trabajo / "especificacion.md").read_text(encoding="utf-8") + relleno,
            encoding="utf-8")

        parte = canario.texto_retomada(self.cwd)

        self.assertLessEqual(canario.tokens_aprox(parte), 2000)

    def test_lee_el_ESTADO_con_los_titulos_canonicos_del_metodo(self):
        """El ESTADO que reparte el bootstrap dice `## Posición actual`, no `## Ahora mismo`."""
        self.workspace_de_juguete()
        (self.cwd / "docs/05-trabajo/ESTADO.md").write_text(
            "# ESTADO — dónde estamos\n\n## Posición actual\n\n"
            "- **Fase**: construcción de la 023\n  con el canario a medio hacer.\n\n"
            "## Unidades\n\n- 023 en obra\n", encoding="utf-8")

        parte = canario.texto_retomada(self.cwd)

        self.assertIn("construcción de la 023", parte)
        self.assertIn("con el canario a medio hacer", parte)   # la viñeta entera, no su 1ª línea

    def test_el_hueco_de_la_plantilla_no_se_cuela_como_ultimo_verde(self):
        """Un `<output real…>` sin rellenar NO es evidencia: decirlo sería mentir al relevo."""
        trabajo = self.workspace_de_juguete()
        (trabajo / "hallazgos.md").write_text(
            "---\nunidad: 023-canario-contexto\n---\n\n"
            "## Evidencia de verificación (obligatorio)\n\n"
            "<output real de la suite de tests + lint. Pegado, no resumido.>\n",
            encoding="utf-8")

        parte = canario.texto_retomada(self.cwd)

        self.assertNotIn("output real de la suite", parte)
        self.assertIn("## Último verde\n\n—", parte)

    def test_sin_unidad_en_obra_el_parte_sigue_saliendo_sin_romper(self):
        (self.cwd / "docs/05-trabajo").mkdir(parents=True)
        (self.cwd / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n\n- nada\n",
                                                            encoding="utf-8")

        parte = canario.texto_retomada(self.cwd)

        for seccion in self.SECCIONES:
            self.assertIn(seccion, parte)

    def test_el_subcomando_retomada_sale_con_exito(self):
        self.workspace_de_juguete()
        r = subprocess.run([sys.executable, str(CANARIO_PATH), "retomada",
                            "--workspace", str(self.cwd)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("023-canario-contexto", r.stdout)


class HookPreCompactTest(BaseCanario):
    """R4: la alarma que suena sola cuando el harness va a compactar."""

    def test_el_subcomando_hook_avisa_aunque_el_porcentaje_no_se_sepa(self):
        r = subprocess.run([sys.executable, str(CANARIO_PATH), "hook",
                            "--cwd", str(self.cwd), "--workspace", str(self.cwd)],
                           input=json.dumps({"hook_event_name": "PreCompact",
                                             "trigger": "auto"}),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ,
                                "CANARIO_CLAUDE_PROJECTS": str(self.claude),
                                "CANARIO_CODEX_SESSIONS": str(self.codex)})

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CANARIO", r.stdout)
        self.assertIn("retomada", r.stdout)

    def test_el_hook_avisa_igual_con_un_modelo_de_ventana_desconocida(self):
        """Compactar YA prueba que la sesión está llena: el 'no sé tu ventana' no vale aquí."""
        self.sesion_claude(tokens=202_822, modelo="modelo-de-otro-lab")
        r = subprocess.run([sys.executable, str(CANARIO_PATH), "hook",
                            "--cwd", str(self.cwd), "--workspace", str(self.cwd)],
                           input=json.dumps({"trigger": "auto"}),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ,
                                "CANARIO_CLAUDE_PROJECTS": str(self.claude),
                                "CANARIO_CODEX_SESSIONS": str(self.codex)})

        self.assertEqual(r.returncode, 0, r.stderr)
        mensaje = json.loads(r.stdout)["systemMessage"]
        self.assertIn("zona de riesgo", mensaje)
        self.assertIn("202822", mensaje)

    def test_el_hook_prefiere_el_aviso_de_conducta_cuando_lo_hay(self):
        eventos = self.par_fallido_claude("pytest -q", "ImportError: no module named x", 3)
        self.sesion_claude(tokens=190_000, eventos=eventos)
        r = subprocess.run([sys.executable, str(CANARIO_PATH), "hook",
                            "--cwd", str(self.cwd), "--workspace", str(self.cwd)],
                           input="{}", capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env={**os.environ,
                                "CANARIO_CLAUDE_PROJECTS": str(self.claude),
                                "CANARIO_CODEX_SESSIONS": str(self.codex)})

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ya está degradando", json.loads(r.stdout)["systemMessage"].lower())

    def test_el_hook_no_bloquea_el_autocompact(self):
        """Fuera de alcance del contrato: bloquear. Exit 0 y `continue` siempre."""
        self.sesion_claude(tokens=190_000)
        r = subprocess.run([sys.executable, str(CANARIO_PATH), "hook",
                            "--cwd", str(self.cwd), "--workspace", str(self.cwd)],
                           input=json.dumps({"trigger": "auto"}),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ,
                                "CANARIO_CLAUDE_PROJECTS": str(self.claude),
                                "CANARIO_CODEX_SESSIONS": str(self.codex)})

        self.assertEqual(r.returncode, 0, r.stderr)
        salida = json.loads(r.stdout)
        self.assertTrue(salida.get("continue"))
        self.assertIn("zona de riesgo", salida["systemMessage"])

    def test_el_bootstrap_siembra_el_hook_en_settings(self):
        destino = self.base / "ws-nuevo"
        destino.mkdir()

        bootstrap.sembrar_hook_canario(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        ganchos = settings["hooks"]["PreCompact"]
        self.assertEqual([g["matcher"] for g in ganchos], ["auto"])
        orden = ganchos[0]["hooks"][0]
        self.assertEqual(orden["type"], "command")
        self.assertIn("canario.py", orden["command"])
        self.assertIn("hook", orden["command"])

    def test_sembrar_el_hook_es_idempotente(self):
        destino = self.base / "ws-nuevo"
        (destino / ".claude").mkdir(parents=True)

        bootstrap.sembrar_hook_canario(destino)
        bootstrap.sembrar_hook_canario(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(len(settings["hooks"]["PreCompact"]), 1)
        self.assertEqual(len(settings["hooks"]["PreCompact"][0]["hooks"]), 1)

    def test_sembrar_el_hook_respeta_lo_que_ya_hubiera(self):
        destino = self.base / "ws-nuevo"
        (destino / ".claude").mkdir(parents=True)
        (destino / ".claude/settings.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(git status:*)"]},
            "hooks": {"PreCompact": [{"matcher": "manual", "hooks": [
                {"type": "command", "command": "echo mio"}]}]},
        }), encoding="utf-8")

        bootstrap.sembrar_hook_canario(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["permissions"]["allow"], ["Bash(git status:*)"])
        matchers = [g["matcher"] for g in settings["hooks"]["PreCompact"]]
        self.assertIn("manual", matchers)
        self.assertIn("auto", matchers)

    def test_el_canario_viaja_en_el_manifiesto_del_metodo(self):
        """Sin esto, el script no llega a ningún workspace (y el bootstrap se cae)."""
        self.assertIn("scripts/canario.py", bootstrap.ARCHIVOS_METODO)


class InstruccionEnAgentsTest(unittest.TestCase):
    """El refuerzo que en Codex es el ÚNICO mecanismo (limitación declarada del contrato)."""

    def test_agents_de_la_plantilla_manda_consultar_el_canario(self):
        texto = (RAIZ / "plantilla/AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("canario.py", texto)
        self.assertIn("canario.py retomada", texto)


if __name__ == "__main__":
    unittest.main()
