"""Unidad 122: aprobar contratos y confirmar entregas SIN la web, desde la terminal.

Hasta aquí el OK del usuario solo tenía una puerta: la web (091 el contrato, 051/057 la
entrega). Quien trabaja por SSH, en un sandbox sin puertos o desde el móvil no podía darlo,
y el agente se quedaba esperando un clic imposible. Aquí se exige la segunda puerta, con el
mismo valor que la primera:

- R1 — `unidad.py aprobar NNN-slug --por "…"` enseña el contrato en texto, pide teclear
  `APRUEBO NNN` y deja `aprobado:` + los DOS rastros que `despachar` mira.
- R2 — `unidad.py confirmar NNN-slug --por "…"` monta la validación guiada sin navegador,
  la imprime, pide `CONFIRMO NNN` y sella un recibo que `cerrar --ok-usuario` acepta igual
  que uno de la web. Es el criterio PORTANTE: si el recibo no fuera indistinguible del de
  la web, `cerrar` tendría dos verdades.
- R3 — Sin `--por` o sin terminal (stdin redirigido: un agente en batch, la CI) los dos
  comandos se niegan con SALIDA y no escriben nada. El recibo guarda `via` y `ejecutable`.
- R4 — Los runbooks de peticiones y cierre nombran la vía terminal.
- R5 — Teclear otra cosa no escribe nada; aprobar dos veces no duplica el rastro.

La terminal de estas pruebas es un pty de verdad (`pty.openpty()`): el código de producción
no tiene ninguna variable de entorno que finja un TTY, porque esa variable sería justo el
agujero por el que un agente se auto-sella el OK. En Windows no hay pty y esas pruebas se
saltan, con el motivo escrito.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import test_unidad_validar  # noqa: E402  (la base NO se importa por nombre: ver 120)

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "visor_presentaciones"))
import manifestar  # noqa: E402
import servir as servir_presentaciones  # noqa: E402

HOY = datetime.date.today().isoformat()
SALIDA = "SALIDA:"
SIN_PTY = unittest.skipIf(os.name == "nt", "no hay pty en Windows: la puerta del TTY se "
                                           "prueba aquí en POSIX y allí queda sin cubrir")


class TerminalBase(test_unidad_validar.WorkspaceBase):
    """El workspace real de `test_unidad_validar` (con la web repartida) + una terminal."""

    def en_terminal(self, *args, teclea="", con_pantalla=False):
        """Lanza `unidad.py` con un pty de verdad por stdin y teclea una línea."""
        import pty
        maestro, esclavo = pty.openpty()
        proceso = subprocess.Popen(
            [sys.executable, str(self.unidad), *args], cwd=self.ws, stdin=esclavo,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=self.entorno(con_pantalla))
        os.close(esclavo)
        try:
            os.write(maestro, (teclea + "\n").encode("utf-8"))
            salida, error = proceso.communicate(timeout=180)
        finally:
            os.close(maestro)
        return subprocess.CompletedProcess(args, proceso.returncode, salida, error)

    def unidad_pendiente(self, slug, ficheros=("app/modulo1.py",)):
        """Una unidad REAL con su contrato escrito y SIN aprobar: lo que el usuario lee."""
        pid = self.capturar(f"Trabajo {slug}")
        self.evaluar(pid, ruta_codigo=ficheros[0])
        creada = self.ejecutar(self.unidad, "nueva", "feature", slug, "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        carpeta = next((self.ws / "docs/05-trabajo").glob(f"[0-9][0-9][0-9]-{slug}"))
        ruta, nombre = carpeta / "especificacion.md", carpeta.name
        texto = ruta.read_text(encoding="utf-8")
        cabecera = texto[: texto.find("---", 4) + 3]
        cabecera = re.sub(r"^ficheros:.*$", "ficheros: [" + ", ".join(ficheros) + "]",
                          cabecera, count=1, flags=re.M)
        cabecera = re.sub(r"^actividad:.*$", "actividad: pedidos", cabecera,
                          count=1, flags=re.M)
        ruta.write_text(cabecera + self.CUERPO.format(nnn=nombre), encoding="utf-8")
        return nombre, ruta

    def aprobaciones_de(self, nombre):
        carpeta = self.ws / ".runtime/aprobaciones"
        return sorted(carpeta.glob(f"{nombre}-*.json")) if carpeta.is_dir() else []

    def lineas_del_rastro(self, nombre):
        registro = self.ws / ".runtime/visor-contratos.log"
        if not registro.is_file():
            return []
        return [l for l in registro.read_text(encoding="utf-8").splitlines() if nombre in l]

    def recibos_de(self, nombre):
        carpeta = self.datos_de(nombre) / "recibos"
        return ([json.loads(f.read_text(encoding="utf-8"))
                 for f in sorted(carpeta.glob("*.json"))] if carpeta.is_dir() else [])


# ============================================================================ R1
@SIN_PTY
class AprobarDesdeLaTerminalTest(TerminalBase):
    """R1 — el contrato se lee y se aprueba en la terminal, con el mismo valor."""

    def test_aprobar_ensena_el_contrato_y_escribe_la_fecha_y_los_dos_rastros(self):
        nombre, ruta = self.unidad_pendiente("aprobar-en-terminal")

        resultado = self.en_terminal("aprobar", nombre, "--por", "Nate",
                                     teclea=f"APRUEBO {nombre[:3]}")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        # lo que el usuario tiene delante ES el contrato, no un resumen
        self.assertIn("Cambio pequeño y localizado", salida)
        self.assertIn("Cómo lo pruebas tú", salida)
        self.assertIn("albarán 4471", salida)
        self.assertIn("app/modulo1.py", salida)
        texto = ruta.read_text(encoding="utf-8")
        self.assertIn(f"aprobado: {HOY}", texto)
        self.assertIn("Nate", re.search(r"^aprobado_por:.*$", texto, re.M).group(0))
        self.assertEqual(len(self.aprobaciones_de(nombre)), 1, salida)
        rastro = json.loads(self.aprobaciones_de(nombre)[0].read_text(encoding="utf-8"))
        self.assertEqual(rastro["unidad"], nombre)
        self.assertEqual(rastro["fecha"], HOY)
        self.assertEqual(rastro["via"], "terminal")
        self.assertEqual(len(rastro["huella"]), 64)
        self.assertTrue([l for l in self.lineas_del_rastro(nombre)
                         if "contrato mostrado" in l], self.lineas_del_rastro(nombre))

    def test_despachar_pasa_la_puerta_del_rastro_tras_aprobar_en_la_terminal(self):
        nombre, _ = self.unidad_pendiente("despacha-tras-terminal")
        aprobada = self.en_terminal("aprobar", nombre, "--por", "Nate",
                                    teclea=f"APRUEBO {nombre[:3]}")
        self.assertEqual(aprobada.returncode, 0, aprobada.stdout + aprobada.stderr)

        despachada = self.ejecutar(self.unidad, "despachar", nombre)

        salida = despachada.stdout + despachada.stderr
        self.assertEqual(despachada.returncode, 0, salida)
        self.assertTrue((self.ws / "worktrees" / nombre).is_dir(), salida)


# ============================================================================ R5
@SIN_PTY
class CasosLimiteDeAprobarTest(TerminalBase):
    """R5 — el literal manda, y una firma no se reescribe."""

    def test_teclear_otra_cosa_no_escribe_nada_y_lo_dice(self):
        nombre, ruta = self.unidad_pendiente("literal-mal")

        resultado = self.en_terminal("aprobar", nombre, "--por", "Nate", teclea="vale, ok")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn(f"APRUEBO {nombre[:3]}", salida)
        self.assertIn(SALIDA, salida)
        self.assertIn("aprobado: no", ruta.read_text(encoding="utf-8"))
        self.assertEqual(self.aprobaciones_de(nombre), [])

    def test_aprobar_dos_veces_no_duplica_el_rastro(self):
        nombre, ruta = self.unidad_pendiente("ya-aprobada")
        primera = self.en_terminal("aprobar", nombre, "--por", "Nate",
                                   teclea=f"APRUEBO {nombre[:3]}")
        self.assertEqual(primera.returncode, 0, primera.stdout + primera.stderr)
        antes = ruta.read_text(encoding="utf-8")

        segunda = self.en_terminal("aprobar", nombre, "--por", "Nate",
                                   teclea=f"APRUEBO {nombre[:3]}")

        salida = segunda.stdout + segunda.stderr
        self.assertEqual(segunda.returncode, 1, salida)
        self.assertIn(f"ya aprobad", salida)
        self.assertIn(HOY, salida)
        self.assertIn(SALIDA, salida)
        self.assertEqual(ruta.read_text(encoding="utf-8"), antes)
        self.assertEqual(len(self.aprobaciones_de(nombre)), 1, salida)


# ============================================================================ R3
class NadieTecleaPorElUsuarioTest(TerminalBase):
    """R3 — sin persona delante no se escribe nada. Las dos puertas, en los dos comandos."""

    def test_aprobar_sin_tty_se_niega_y_no_escribe_nada(self):
        nombre, ruta = self.unidad_pendiente("sin-tty")

        resultado = self.ejecutar(self.unidad, "aprobar", nombre, "--por", "Nate")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn(SALIDA, salida)
        self.assertIn("terminal", salida.lower())
        self.assertIn("aprobado: no", ruta.read_text(encoding="utf-8"))
        self.assertEqual(self.aprobaciones_de(nombre), [])
        self.assertEqual(self.lineas_del_rastro(nombre), [])

    def test_confirmar_sin_tty_se_niega_y_no_escribe_ningun_recibo(self):
        nombre = self.unidad_cerrable("confirmar-sin-tty")

        resultado = self.ejecutar(self.unidad, "confirmar", nombre, "--por", "Nate")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn(SALIDA, salida)
        self.assertEqual(self.recibos_de(nombre), [])

    @SIN_PTY
    def test_aprobar_sin_por_se_niega_aunque_haya_terminal(self):
        nombre, ruta = self.unidad_pendiente("sin-por")

        resultado = self.en_terminal("aprobar", nombre, teclea=f"APRUEBO {nombre[:3]}")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("--por", salida)
        self.assertIn(SALIDA, salida)
        self.assertIn("aprobado: no", ruta.read_text(encoding="utf-8"))

    @SIN_PTY
    def test_confirmar_sin_por_se_niega_aunque_haya_terminal(self):
        nombre = self.unidad_cerrable("confirmar-sin-por")

        resultado = self.en_terminal("confirmar", nombre, teclea=f"CONFIRMO {nombre[:3]}")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("--por", salida)
        self.assertIn(SALIDA, salida)
        self.assertEqual(self.recibos_de(nombre), [])


# ============================================================================ R2
@SIN_PTY
class ConfirmarDesdeLaTerminalTest(TerminalBase):
    """R2 (criterio PORTANTE) — el recibo de la terminal vale lo mismo que el de la web."""

    def test_confirmar_ensena_pasos_y_evidencia_y_cerrar_acepta_su_recibo(self):
        nombre = self.unidad_cerrable("confirmar-en-terminal")

        confirmada = self.en_terminal("confirmar", nombre, "--por", "Nate",
                                      teclea=f"CONFIRMO {nombre[:3]}")

        salida = confirmada.stdout + confirmada.stderr
        self.assertEqual(confirmada.returncode, 0, salida)
        self.assertIn("albarán 4471", salida)
        self.assertIn("El total se recalcula solo", salida)
        recibos = self.recibos_de(nombre)
        self.assertEqual(len(recibos), 1, salida)
        recibo = recibos[0]
        self.assertEqual(recibo["presentacion"], nombre)
        self.assertEqual(recibo["eleccion"], "confirmado")
        self.assertEqual(recibo["via"], "terminal")
        self.assertEqual(recibo["por"], "Nate")
        self.assertEqual(recibo["dia"], HOY)
        self.assertEqual(len(recibo["huella"]), 64)
        self.assertTrue(recibo["ejecutable"])

        cerrada = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = cerrada.stdout + cerrada.stderr
        self.assertEqual(cerrada.returncode, 0,
                         "R2 (criterio portante): `cerrar --ok-usuario` no acepta el recibo "
                         "sellado desde la terminal, así que NO es indistinguible del de la "
                         "web\n" + salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).exists(),
                        "R2 (criterio portante): el recibo de la terminal no cerró la "
                        "unidad\n" + salida)

    def test_confirmar_con_problema_sella_el_problema_y_bloquea_el_cierre(self):
        nombre = self.unidad_cerrable("confirmar-con-problema")

        confirmada = self.en_terminal("confirmar", nombre, "--por", "Nate",
                                      "--problema", "el total sigue sin recalcularse",
                                      teclea=f"PROBLEMA {nombre[:3]}")

        salida = confirmada.stdout + confirmada.stderr
        self.assertEqual(confirmada.returncode, 0, salida)
        recibo = self.recibos_de(nombre)[0]
        self.assertEqual(recibo["eleccion"], "problema")
        self.assertEqual(recibo["comentario"], "el total sigue sin recalcularse")
        self.assertEqual(recibo["via"], "terminal")

        cerrada = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = cerrada.stdout + cerrada.stderr
        self.assertEqual(cerrada.returncode, 1, salida)
        self.assertIn("problema", salida)
        self.assertIn("bug", salida.lower())

    def test_teclear_otra_cosa_no_sella_ningun_recibo(self):
        nombre = self.unidad_cerrable("confirmar-literal-mal")

        resultado = self.en_terminal("confirmar", nombre, "--por", "Nate", teclea="sí")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn(f"CONFIRMO {nombre[:3]}", salida)
        self.assertIn(SALIDA, salida)
        self.assertEqual(self.recibos_de(nombre), [])


class ReciboIndistinguibleTest(unittest.TestCase):
    """R2, la parte que sostiene todo lo demás: la terminal y la web sellan LO MISMO.

    No es una comparación de campos escrita a mano: se le da la misma decisión a la función
    que usa la terminal (`manifestar.decidir`) y a la que usa la web
    (`visor_presentaciones/servir.py::_validar_decision`) sobre el mismo manifiesto, y se
    exige que los recibos coincidan campo a campo salvo en lo que por definición cambia
    (el `id` y la marca de tiempo).
    """

    VARIABLES = {"id", "fecha"}

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory(prefix="recibo-indistinguible-")
        self.addCleanup(self.tmp.cleanup)
        self.datos = Path(self.tmp.name)
        self.presentacion = manifestar.presentacion_validacion(
            "001-una-unidad", "001-una-unidad · cómo lo pruebas tú", "2026-08-28",
            ["Busca el albarán 4471", "Cambia la cantidad a 12"],
            ["Pruebas: 12/12 verdes"])
        self.manifiesto = manifestar.manifiesto([self.presentacion])
        (self.datos / "manifiesto.json").write_text(
            json.dumps(self.manifiesto, ensure_ascii=False), encoding="utf-8")

    def decision(self, eleccion="confirmado", comentario=""):
        return {"presentacion": self.presentacion["id"],
                "version": self.presentacion["version"],
                "contenido_revisado": "\n".join(self.presentacion["pasos"]),
                "eleccion": eleccion, "comentario": comentario, "confirmado": True}

    def recibo_de_la_web(self, decision):
        # `_validar_decision` no usa `self`: valida contra el manifiesto de su closure.
        clase = servir_presentaciones.hacer_handler(self.datos, {"ultimo": 0})
        return clase._validar_decision(None, decision)

    def test_los_dos_recibos_coinciden_campo_a_campo(self):
        for eleccion, comentario in (("confirmado", ""), ("problema", "no recalcula")):
            with self.subTest(eleccion=eleccion):
                decision = self.decision(eleccion, comentario)
                web = self.recibo_de_la_web(decision)
                terminal = manifestar.decidir(self.manifiesto, dict(decision))
                self.assertEqual(set(web), set(terminal),
                                 "R2 (criterio portante): los recibos no llevan los mismos "
                                 "campos")
                for campo in set(web) - self.VARIABLES:
                    self.assertEqual(web[campo], terminal[campo],
                                     f"R2 (criterio portante): el campo «{campo}» no "
                                     f"coincide entre la web y la terminal")

    def test_las_mismas_puertas_rechazan_lo_mismo(self):
        malas = (
            ("presentación inexistente", dict(self.decision(), presentacion="999-otra")),
            ("versión distinta", dict(self.decision(), version="9")),
            ("contenido cambiado", dict(self.decision(), contenido_revisado="otra cosa")),
            ("elección inválida", dict(self.decision(), eleccion="quizás")),
            ("problema sin comentario", self.decision("problema", "")),
            ("sin confirmar", dict(self.decision(), confirmado=False)),
        )
        for rotulo, decision in malas:
            with self.subTest(rotulo):
                with self.assertRaises(ValueError):
                    self.recibo_de_la_web(dict(decision))
                with self.assertRaises(ValueError):
                    manifestar.decidir(self.manifiesto, dict(decision))


# ============================================================================ R4
class LosRunbooksNombranLaViaTerminalTest(unittest.TestCase):
    """R4 — una vía que solo conoce el código no la usa nadie."""

    RUNBOOKS = RAIZ / "plantilla/docs/00-metodo/runbooks"

    def test_peticiones_nombra_aprobar_por_terminal(self):
        texto = (self.RUNBOOKS / "peticiones.md").read_text(encoding="utf-8")
        self.assertIn("unidad.py aprobar", texto)

    def test_cierre_nombra_confirmar_por_terminal(self):
        texto = (self.RUNBOOKS / "cierre.md").read_text(encoding="utf-8")
        self.assertIn("unidad.py confirmar", texto)


if __name__ == "__main__":
    unittest.main()
