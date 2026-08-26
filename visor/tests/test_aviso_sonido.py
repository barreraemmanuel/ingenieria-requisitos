"""Unidad 063 · Cuando la IA necesita a Nate, suena — en todos los PCs que usen el método.

Cubre los cinco criterios del contrato:

  R1  `aviso.py` elige el reproductor de SU plataforma y, sin reproductor o sin sonido,
      sale 0 y no escribe nada (un hook que falla molesta más que el silencio).
  R2  `bootstrap.py` siembra `Notification` y `Stop` -> `aviso.py <evento>`, conservando
      el `PreCompact` del canario; sembrar dos veces no duplica (Modo D).
  R3  `personalidad.md` manda: `no` calla, `sistema` suena el del sistema, un preset busca
      `.claude/sonidos/<nombre>.<ext>` y, si falta, cae al del sistema y lo dice UNA vez.
  R4  `comunicacion.md` cuenta qué suena, cuándo y que en Codex no hay hooks.
  R5  Un `settings.json` con hooks propios del usuario no se pisa.

Sin audio real: nada de esto reproduce nada. Se comprueba la ORDEN elegida, no el sonido.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
AVISO = SCRIPTS / "aviso.py"
COMUNICACION = RAIZ / "plantilla/docs/00-metodo/comunicacion.md"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(RAIZ / "visor") not in sys.path:
    sys.path.insert(0, str(RAIZ / "visor"))

import aviso                                                        # noqa: E402
import bootstrap                                                    # noqa: E402


def doble_which(*disponibles):
    """Un `shutil.which` de mentira: solo estos programas existen en esta máquina."""
    encontrados = set(disponibles)
    return lambda nombre: f"/usr/bin/{nombre}" if nombre in encontrados else None


class BaseAviso(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aviso-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def workspace(self, personalidad=None, sonidos=()):
        """Un meta-repo de mentira con su `.claude/` y, si se pide, sus sonidos."""
        ws = self.base / "ws"
        (ws / ".claude").mkdir(parents=True, exist_ok=True)
        if personalidad is not None:
            (ws / ".claude/personalidad.md").write_text(personalidad, encoding="utf-8")
        for nombre in sonidos:
            fichero = ws / ".claude/sonidos" / nombre
            fichero.parent.mkdir(parents=True, exist_ok=True)
            fichero.write_bytes(b"RIFF")
        return ws


# --------------------------------------------------------------------------- R1

class ReproductorPorPlataformaTest(BaseAviso):
    """R1: cada plataforma tiene el suyo, y sin él no suena nada (ni se rompe nada)."""

    def test_macos_usa_afplay(self):
        orden = aviso.orden_de_reproduccion("/s/Ping.aiff", "darwin", doble_which("afplay"))

        self.assertEqual(orden, ["/usr/bin/afplay", "/s/Ping.aiff"])

    def test_linux_prefiere_paplay(self):
        orden = aviso.orden_de_reproduccion("/s/complete.oga", "linux",
                                            doble_which("paplay", "aplay"))

        self.assertEqual(orden, ["/usr/bin/paplay", "/s/complete.oga"])

    def test_linux_cae_a_aplay_con_un_wav(self):
        orden = aviso.orden_de_reproduccion("/s/bell.wav", "linux", doble_which("aplay"))

        self.assertEqual(orden, ["/usr/bin/aplay", "-q", "/s/bell.wav"])

    def test_linux_no_manda_un_oga_a_aplay(self):
        """`aplay` solo entiende WAV: mandarle un .oga es ruido en stderr, no un sonido."""
        orden = aviso.orden_de_reproduccion("/s/complete.oga", "linux", doble_which("aplay"))

        self.assertIsNone(orden)

    def test_windows_usa_soundplayer_de_powershell(self):
        orden = aviso.orden_de_reproduccion(r"C:\W\notify.wav", "win32",
                                            doble_which("powershell"))

        self.assertEqual(orden[0], "/usr/bin/powershell")
        self.assertIn("SoundPlayer", orden[-1])
        self.assertIn("notify.wav", orden[-1])

    def test_sin_ningun_reproductor_no_hay_orden(self):
        self.assertIsNone(aviso.orden_de_reproduccion("/s/x.wav", "linux", doble_which()))
        self.assertIsNone(aviso.orden_de_reproduccion("/s/x.aiff", "darwin", doble_which()))

    def test_una_plataforma_desconocida_no_inventa_reproductor(self):
        self.assertIsNone(aviso.orden_de_reproduccion("/s/x.wav", "aix7",
                                                      doble_which("paplay", "afplay")))


class SilencioQueNoRompeTest(BaseAviso):
    """R1: sin reproductor sale 0 y no escribe NADA. Es un hook: molestar sale caro."""

    def test_sin_reproductor_sale_cero_y_callado(self):
        ws = self.workspace()
        entorno = dict(os.environ, PATH="", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")

        r = subprocess.run([sys.executable, str(AVISO), "fin-de-turno",
                            "--workspace", str(ws)],
                           text=True, encoding="utf-8", errors="replace",
                           capture_output=True, env=entorno)

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")

    def test_un_evento_desconocido_tampoco_rompe_el_turno(self):
        ws = self.workspace()

        r = subprocess.run([sys.executable, str(AVISO), "lo-que-sea",
                            "--workspace", str(ws), "--no-reproducir"],
                           text=True, encoding="utf-8", errors="replace",
                           capture_output=True)

        self.assertEqual(r.returncode, 0, r.stderr)

    def test_sin_fichero_de_sonido_en_la_maquina_no_hay_nada_que_sonar(self):
        """Un Linux pelado sin `/usr/share/sounds`: silencio, no una orden a un fichero
        que no existe."""
        self.assertIsNone(aviso.sonido_del_sistema("linux", existe=lambda _: False))


# --------------------------------------------------------------------------- R3

class PreferenciaDePersonalidadTest(BaseAviso):
    """R3: el interruptor y los presets viven en `.claude/personalidad.md`."""

    def test_sin_la_clave_suena_el_del_sistema(self):
        ws = self.workspace("# Personalidad\n\nHáblame de tú.\n")

        self.assertEqual(aviso.preferencia(ws), "sistema")

    def test_sin_personalidad_md_tampoco_pasa_nada(self):
        ws = self.workspace()

        self.assertEqual(aviso.preferencia(ws), "sistema")

    def test_la_clave_se_lee(self):
        ws = self.workspace("sonido: toasty\n")

        self.assertEqual(aviso.preferencia(ws), "toasty")

    def test_los_ejemplos_del_bloque_de_codigo_no_cuentan(self):
        """El placeholder documenta la clave con ejemplos: si el lector los tomara por la
        preferencia, todo workspace nuevo nacería con el sonido del ejemplo."""
        ws = self.workspace("# Personalidad\n\n```\nsonido: wololo\n```\n")

        self.assertEqual(aviso.preferencia(ws), "sistema")

    def test_sonido_no_es_silencio(self):
        ws = self.workspace("sonido: no\n")

        ruta, recado = aviso.resolver(ws, "darwin", existe=lambda _: True)

        self.assertIsNone(ruta)
        self.assertIsNone(recado)

    def test_un_preset_busca_en_claude_sonidos(self):
        ws = self.workspace("sonido: toasty\n", sonidos=("toasty.wav",))

        ruta, recado = aviso.resolver(ws, "darwin", existe=os.path.exists)

        self.assertEqual(Path(ruta), ws / ".claude/sonidos/toasty.wav")
        self.assertIsNone(recado)

    def test_un_preset_que_falta_cae_al_del_sistema_y_lo_dice_una_vez(self):
        ws = self.workspace("sonido: wololo\n")

        ruta, recado = aviso.resolver(ws, "darwin", existe=os.path.exists)
        self.assertEqual(ruta, aviso.sonido_del_sistema("darwin", existe=os.path.exists))
        self.assertIn("wololo", recado)

        segunda, callado = aviso.resolver(ws, "darwin", existe=os.path.exists)
        self.assertEqual(segunda, ruta)
        self.assertIsNone(callado)

    def test_cambiar_de_preset_vuelve_a_dar_derecho_a_un_recado(self):
        ws = self.workspace("sonido: wololo\n")
        aviso.resolver(ws, "darwin", existe=os.path.exists)
        (ws / ".claude/personalidad.md").write_text("sonido: toasty\n", encoding="utf-8")

        _, recado = aviso.resolver(ws, "darwin", existe=os.path.exists)

        self.assertIn("toasty", recado)

    def test_una_ruta_propia_se_usa_tal_cual(self):
        ws = self.workspace()
        mio = self.base / "mio.wav"
        mio.write_bytes(b"RIFF")
        (ws / ".claude/personalidad.md").write_text(f"sonido: {mio}\n", encoding="utf-8")

        ruta, recado = aviso.resolver(ws, "darwin", existe=os.path.exists)

        self.assertEqual(Path(ruta), mio)
        self.assertIsNone(recado)

    def test_el_recado_sale_por_stdout_como_json_y_solo_esa_vez(self):
        ws = self.workspace("sonido: wololo\n")

        primera = self.correr(ws)
        self.assertIn("wololo", json.loads(primera)["systemMessage"])

        self.assertEqual(self.correr(ws), "")

    def correr(self, ws):
        salida = io.StringIO()
        with redirect_stdout(salida):
            codigo = aviso.main(["fin-de-turno", "--workspace", str(ws), "--no-reproducir"])
        self.assertEqual(codigo, 0)
        return salida.getvalue().strip()


# --------------------------------------------------------------------------- R2 y R5

class SiembraDeLosHooksTest(BaseAviso):
    """R2 y R5: los dos hooks nuevos entran sin pisar nada y sin duplicarse."""

    def ordenes(self, destino, gancho):
        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        return [orden["command"]
                for entrada in settings["hooks"].get(gancho, [])
                for orden in entrada["hooks"]]

    def test_siembra_notification_y_stop_apuntando_a_aviso(self):
        destino = self.base / "ws-nuevo"
        destino.mkdir()

        self.assertTrue(bootstrap.sembrar_hook_aviso(destino))

        for gancho, evento in (("Notification", "notificacion"), ("Stop", "fin-de-turno")):
            ordenes = self.ordenes(destino, gancho)
            self.assertTrue(any("aviso.py" in o and evento in o for o in ordenes),
                            f"{gancho}: {ordenes}")

    def test_el_hook_lleva_timeout_corto(self):
        destino = self.base / "ws-nuevo"
        destino.mkdir()
        bootstrap.sembrar_hook_aviso(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        ordenes = [orden for entrada in settings["hooks"]["Stop"]
                   for orden in entrada["hooks"] if "aviso.py" in orden["command"]]
        self.assertEqual([o["timeout"] for o in ordenes], [bootstrap.TIMEOUT_AVISO])

    def test_sembrar_dos_veces_no_duplica(self):
        """Modo D pasa por todos los workspaces cada vez que se actualiza el método."""
        destino = self.base / "ws-nuevo"
        destino.mkdir()

        bootstrap.sembrar_hook_aviso(destino)
        self.assertFalse(bootstrap.sembrar_hook_aviso(destino))

        self.assertEqual(len(self.ordenes(destino, "Notification")), 1)
        self.assertEqual(len(self.ordenes(destino, "Stop")), 1)

    def test_no_pisa_los_hooks_del_usuario_ni_su_orden(self):
        destino = self.base / "ws-ajeno"
        (destino / ".claude").mkdir(parents=True)
        (destino / ".claude/settings.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(git status:*)"]},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mio"}]}],
                      "Notification": [{"hooks": [
                          {"type": "command", "command": "echo aviso mio"}]}]},
        }), encoding="utf-8")

        bootstrap.sembrar_hook_aviso(destino)

        settings = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["permissions"]["allow"], ["Bash(git status:*)"])
        self.assertEqual(self.ordenes(destino, "Stop")[0], "echo mio")
        self.assertEqual(self.ordenes(destino, "Notification")[0], "echo aviso mio")
        self.assertEqual(len(self.ordenes(destino, "Stop")), 2)

    def test_los_ganchos_locales_traen_canario_y_aviso_juntos(self):
        """Lo que siembra el bootstrap de un workspace nuevo: el canario NO se pierde."""
        destino = self.base / "ws-todo"
        destino.mkdir()

        self.assertTrue(bootstrap.sembrar_hooks_locales(destino))
        self.assertFalse(bootstrap.sembrar_hooks_locales(destino))

        self.assertTrue(any("canario.py hook" in o
                            for o in self.ordenes(destino, "PreCompact")))
        stop = self.ordenes(destino, "Stop")
        self.assertTrue(any("canario.py hook-stop" in o for o in stop))
        self.assertTrue(any("aviso.py" in o for o in stop))
        self.assertTrue(any("aviso.py" in o for o in self.ordenes(destino, "Notification")))

    def test_un_workspace_que_ya_tenia_el_canario_gana_el_sonido(self):
        """El caso de Modo D: el PreCompact y el Stop del canario ya estaban."""
        destino = self.base / "ws-viejo"
        (destino / ".claude").mkdir(parents=True)
        bootstrap.sembrar_hook_canario(destino)

        self.assertTrue(bootstrap.sembrar_hooks_locales(destino))

        self.assertEqual(len([o for o in self.ordenes(destino, "Stop")
                              if "canario.py" in o]), 1)
        self.assertEqual(len([o for o in self.ordenes(destino, "Stop")
                              if "aviso.py" in o]), 1)

    def test_aviso_viaja_en_el_manifiesto_del_metodo(self):
        """Sin esto el script no llega a ningún workspace y el hook apunta al vacío."""
        self.assertIn("scripts/aviso.py", bootstrap.ARCHIVOS_METODO)

    def test_el_placeholder_de_personalidad_documenta_el_interruptor(self):
        texto = bootstrap.PLACEHOLDER_PERSONALIDAD

        self.assertIn("sonido:", texto)
        for valor in ("no", "sistema", "toasty"):
            self.assertIn(valor, texto)
        self.assertIn(".claude/sonidos/", texto)


# --------------------------------------------------------------------------- R4

class LoQueSeCuentaTest(unittest.TestCase):
    """R4: si no está escrito, el usuario no sabe ni que suena ni por qué no suena."""

    def test_comunicacion_explica_el_aviso_sonoro_y_el_limite_de_codex(self):
        texto = COMUNICACION.read_text(encoding="utf-8")

        self.assertIn("sonido", texto.lower())
        self.assertIn("Codex", texto)
        self.assertIn("personalidad.md", texto)


if __name__ == "__main__":
    unittest.main()


class HooksAncladosAlProyectoTest(unittest.TestCase):
    """27-08: los hooks corren con el cwd del último `cd` del agente (un worktree) y ahí no
    hay `docs/00-metodo/`. Toda orden sembrada va anclada a `$CLAUDE_PROJECT_DIR`, y las ya
    sembradas sin ancla se reanclan al volver a sembrar (Modo D)."""

    def test_toda_orden_sembrada_va_anclada_y_las_viejas_se_reanclan(self):
        import json, tempfile
        from pathlib import Path
        destino = Path(tempfile.mkdtemp())
        (destino / ".claude").mkdir()
        (destino / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": [
            {"hooks": [{"type": "command",
                        "command": "python3 docs/00-metodo/scripts/canario.py hook-stop"}]}],
            "Notification": [{"hooks": [{"type": "command", "command": "echo mio"}]}]}}),
            encoding="utf-8")
        bootstrap.sembrar_hook_canario(destino)
        bootstrap.sembrar_hook_aviso(destino)
        cfg = json.loads((destino / ".claude/settings.json").read_text(encoding="utf-8"))
        ordenes = [g["command"] for v in cfg["hooks"].values() for e in v for g in e["hooks"]]
        del_metodo = [o for o in ordenes if "docs/00-metodo/scripts/" in o]
        self.assertEqual(len(del_metodo), 4)
        for orden in del_metodo:
            self.assertTrue(orden.startswith(bootstrap.ANCLA_PROYECTO), orden)
        self.assertIn("echo mio", ordenes)  # los hooks propios del dueño no se tocan
