"""El lanzador de la suite (`visor/tests/correr.py`) tiene que decir la verdad (bug 093).

El padre lee el código de salida de `correr.py` como puerta antes de fusionar: 0 si todas
las suites pasaron, ≠ 0 solo si alguna falló. El 26-08 la suite salió con **exit 144** con
todo en verde por pantalla, y el padre no pudo distinguir «verde» de «muerto al final».

144 no lo inventa nadie: `144 == 128 | 16`. El lanzador acumulaba los códigos con un OR de
bits (`codigo |= subprocess.run(...).returncode`), así que dos suites que salen con 128 y
con 16 producen 144, un hijo matado por una señal (returncode negativo) produce un exit de
240-247, y en ningún caso queda escrito por pantalla QUÉ suite falló ni por qué.

Aquí se fija lo contrario: el lanzador no muere por señales que no son de parada, cuenta
suites rojas en vez de mezclar bits, termina SIEMPRE con una línea `VEREDICTO: …` y su
propio exit es 0 o 1 — nunca 144, nunca 240.

Los procesos son de mentira y diminutos a propósito: reproducir esto NO puede pasar por
correr la suite entera (9 minutos en la máquina de Nate).
"""
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
if str(CARPETA) not in sys.path:
    sys.path.insert(0, str(CARPETA))
import correr  # noqa: E402

TOPE = 90  # segundos: las suites falsas tardan milisegundos; esto es solo un seguro


def modulo(cuerpo=""):
    """Un test_*.py con UN test verde y, opcionalmente, una forma de morir al final."""
    return textwrap.dedent("""\
        import atexit
        import os
        import signal
        import unittest


        class Falsa(unittest.TestCase):
            def test_verde(self):
                self.assertTrue(True)
        """) + textwrap.dedent(cuerpo)


VERDE = modulo()
# `atexit` corre DESPUÉS de que unittest imprima «OK» y decida su propio código: es la forma
# exacta del síntoma reportado — pantalla en verde, proceso que se va con otro número.
VERDE_LUEGO_144 = modulo("atexit.register(lambda: os._exit(144))")
VERDE_LUEGO_128 = modulo("atexit.register(lambda: os._exit(128))")
VERDE_LUEGO_16 = modulo("atexit.register(lambda: os._exit(16))")
VERDE_LUEGO_MATADO = modulo("atexit.register(lambda: os.kill(os.getpid(), signal.SIGKILL))")
ROJO = textwrap.dedent("""\
    import unittest


    class Falsa(unittest.TestCase):
        def test_rojo(self):
            self.fail("falla a propósito")
    """)
LENTO = textwrap.dedent("""\
    import os
    import time
    import unittest


    class Falsa(unittest.TestCase):
        def test_lento(self):
            open(os.environ["MARCA_093"], "w", encoding="utf-8").write("dentro")
            time.sleep(20)
    """)


class LanzadorTest(unittest.TestCase):
    """Cada test monta un árbol de suites falsas y lanza `correr.main()` de verdad,
    en su propio proceso, para poder mirar el código de salida REAL del lanzador."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp(prefix="correr-093-")).resolve()
        self.addCleanup(self._limpiar)

    def _limpiar(self):
        import shutil
        shutil.rmtree(self.raiz, ignore_errors=True)

    def suite(self, nombre, cuerpo):
        carpeta = self.raiz / nombre
        carpeta.mkdir(parents=True)
        (carpeta / "test_falso.py").write_text(cuerpo, encoding="utf-8")
        return nombre

    def _guion(self, rapidas, nightly, args):
        return textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(CARPETA)!r})
            import correr
            correr.RAIZ = {str(self.raiz)!r}
            correr.RAPIDAS = {tuple(rapidas)!r}
            correr.NIGHTLY = {tuple(nightly)!r}
            sys.argv = ["correr.py"] + {list(args)!r}
            sys.exit(correr.main())
        """)

    def lanzar(self, rapidas=(), nightly=(), args=()):
        return subprocess.run(
            [sys.executable, "-c", self._guion(rapidas, nightly, args)],
            capture_output=True, text=True, encoding="utf-8", timeout=TOPE)

    def veredicto(self, salida):
        """La ÚLTIMA línea con contenido tiene que ser el veredicto."""
        lineas = [l for l in salida.strip().splitlines() if l.strip()]
        self.assertTrue(lineas, "el lanzador no imprimió nada")
        return lineas[-1]

    # ---- el síntoma reportado --------------------------------------------------

    def test_una_suite_que_se_va_con_144_no_contagia_el_exit_del_lanzador(self):
        """EL BUG: pantalla en verde y el lanzador saliendo con 144.
        El exit del lanzador es un veredicto (0/1), no el código del hijo."""
        self.suite("suite_a", VERDE_LUEGO_144)
        r = self.lanzar(rapidas=["suite_a"])
        self.assertIn("OK", r.stdout + r.stderr)          # la suite se vio verde
        self.assertNotEqual(144, r.returncode, "el lanzador se va con el 144 del hijo")
        self.assertEqual(1, r.returncode)
        linea = self.veredicto(r.stdout)
        self.assertTrue(linea.startswith("VEREDICTO: rojo"), linea)
        self.assertIn("144", r.stdout, "el veredicto no dice con qué código se fue la suite")

    def test_dos_suites_con_128_y_16_no_se_mezclan_en_un_144(self):
        """La aritmética de bits del lanzador fabricaba códigos que nadie devolvió:
        128 | 16 == 144. Las suites rojas se CUENTAN, no se mezclan."""
        self.assertEqual(144, 128 | 16)                   # la línea de partida del bug
        self.suite("suite_a", VERDE_LUEGO_128)
        self.suite("suite_b", VERDE_LUEGO_16)
        r = self.lanzar(rapidas=["suite_a", "suite_b"])
        self.assertNotEqual(144, r.returncode)
        self.assertEqual(1, r.returncode)
        self.assertEqual("VEREDICTO: rojo (2 suites, 2 rojas)", self.veredicto(r.stdout))

    def test_una_suite_matada_por_una_senal_no_sale_con_240_y_pico(self):
        """`returncode` negativo (-9) por el OR daba un exit de 247, ilegible.
        Ahora es rojo, con el nombre de la señal escrito."""
        self.suite("suite_a", VERDE_LUEGO_MATADO)
        r = self.lanzar(rapidas=["suite_a"])
        self.assertEqual(1, r.returncode)
        self.assertIn("SIGKILL", r.stdout)
        self.assertTrue(self.veredicto(r.stdout).startswith("VEREDICTO: rojo"))

    # ---- el veredicto, siempre -------------------------------------------------

    def test_todo_verde_termina_en_veredicto_verde_y_exit_0(self):
        self.suite("suite_a", VERDE)
        self.suite("suite_b", VERDE)
        r = self.lanzar(rapidas=["suite_a", "suite_b"])
        self.assertEqual(0, r.returncode)
        self.assertEqual("VEREDICTO: verde (2 suites, 0 rojas)", self.veredicto(r.stdout))

    def test_un_test_que_falla_de_verdad_sigue_siendo_rojo_con_su_nombre(self):
        self.suite("suite_a", VERDE)
        self.suite("suite_b", ROJO)
        r = self.lanzar(rapidas=["suite_a", "suite_b"])
        self.assertEqual(1, r.returncode)
        self.assertEqual("VEREDICTO: rojo (2 suites, 1 roja)", self.veredicto(r.stdout))
        self.assertIn("suite_b", r.stdout)

    # ---- señales ---------------------------------------------------------------

    def test_las_senales_que_no_son_de_parada_quedan_ignoradas_a_proposito(self):
        """SIGURG (16) y SIGWINCH no paran nada: en una máquina cargada llegan solas.
        El lanzador las ignora EXPLÍCITAMENTE en vez de depender del defecto del SO."""
        if not hasattr(signal, "SIGURG"):
            self.skipTest("plataforma sin SIGURG")
        previas = {n: signal.getsignal(getattr(signal, n))
                   for n in ("SIGURG", "SIGWINCH") if hasattr(signal, n)}
        self.addCleanup(lambda: [signal.signal(getattr(signal, n), v)
                                 for n, v in previas.items()])
        correr.blindar_senales()
        self.assertIs(signal.SIG_IGN, signal.getsignal(signal.SIGURG))
        self.assertIs(signal.SIG_IGN, signal.getsignal(signal.SIGWINCH))

    def test_SIGCHLD_no_se_toca_nunca(self):
        """Ignorar SIGCHLD auto-recolecta a los hijos y deja a `wait()` sin nadie a quien
        esperar (ECHILD): sería cambiar un bug por otro peor."""
        if not hasattr(signal, "SIGCHLD"):
            self.skipTest("plataforma sin SIGCHLD")
        antes = signal.getsignal(signal.SIGCHLD)
        self.addCleanup(signal.signal, signal.SIGCHLD, antes)
        correr.blindar_senales()
        self.assertIs(antes, signal.getsignal(signal.SIGCHLD))

    def test_una_senal_de_parada_de_verdad_lo_dice_con_su_nombre_y_sale_distinto_de_0(self):
        """SIGTERM sí para: el lanzador corta, lo escribe en la última línea con el
        nombre de la señal y NO se va en silencio con 143."""
        if os.name != "posix":
            self.skipTest("señales POSIX")
        self.suite("suite_a", LENTO)
        marca = self.raiz / "marca.txt"
        entorno = dict(os.environ, MARCA_093=str(marca))
        proc = subprocess.Popen(
            [sys.executable, "-c", self._guion(["suite_a"], (), [])],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", env=entorno)
        try:
            limite = time.time() + 30
            while not marca.exists() and time.time() < limite:
                time.sleep(0.05)
            self.assertTrue(marca.exists(), "la suite falsa no llegó a arrancar")
            proc.send_signal(signal.SIGTERM)
            salida, _ = proc.communicate(timeout=TOPE)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.assertNotEqual(0, proc.returncode)
        self.assertEqual(1, proc.returncode, "el lanzador murió en vez de dar veredicto")
        linea = self.veredicto(salida)
        self.assertTrue(linea.startswith("VEREDICTO: rojo"), linea)
        self.assertIn("SIGTERM", linea)

    # ---- lo que NO puede cambiar ------------------------------------------------

    def test_nightly_sigue_eligiendo_la_otra_lista(self):
        self.suite("rapida", ROJO)
        self.suite("adversarial", VERDE)
        r = self.lanzar(rapidas=["rapida"], nightly=["adversarial"], args=["--nightly"])
        self.assertEqual(0, r.returncode)
        self.assertIn("== adversarial ==", r.stdout)
        self.assertNotIn("== rapida ==", r.stdout)

    def test_verboso_sigue_llegando_al_hijo(self):
        self.suite("suite_a", VERDE)
        r = self.lanzar(rapidas=["suite_a"], args=["-v"])
        self.assertEqual(0, r.returncode)
        self.assertIn("test_verde", r.stdout + r.stderr)

    def test_los_hijos_siguen_naciendo_en_modo_utf8(self):
        cuerpo = textwrap.dedent("""\
            import os
            import unittest


            class Falsa(unittest.TestCase):
                def test_utf8(self):
                    assert os.environ.get("PYTHONUTF8") == "1", "sin PYTHONUTF8"
                    assert os.environ.get("PYTHONIOENCODING") == "utf-8", "sin encoding"
            """)
        self.suite("suite_a", cuerpo)
        r = self.lanzar(rapidas=["suite_a"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)

    def test_la_cabecera_por_suite_sigue_saliendo(self):
        self.suite("suite_a", VERDE)
        r = self.lanzar(rapidas=["suite_a"])
        self.assertIn("== suite_a ==", r.stdout)


if __name__ == "__main__":
    unittest.main()
