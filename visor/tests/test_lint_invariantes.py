"""Unidad 146 · R1 — las ocho señales, con fecha de corte y con denominador.

`lint_invariantes.py` no mide «violaciones»: mide SEÑALES sobre el taller real. Una señal
alta no implica por sí sola que alguien hiciera nada mal (los 122 aprobados históricos no
van a tener recibo retroactivo), y por eso se imprimen SIEMPRE dos cuentas:

- **histórica** — informa, nunca bloquea; lleva su denominador para que el número signifique
  algo («122 de 144» no es «122 de infinito»);
- **posterior al corte** — FAIL si es mayor que cero. Es lo único que puede bloquear, porque
  es lo único que la reforma puede evitar.

Las señales con fecha por sujeto (S1-S4, S8) reparten por esa fecha. Las señales de código
(S5-S7) no tienen fecha por sujeto: su «posterior» es lo que SUBE sobre la línea base
congelada, que es el mismo trinquete de `salidas-baseline.json`.

Todo se mide aquí sobre talleres sintéticos en `TemporaryDirectory`: ningún test depende de
cómo esté hoy la máquina de quien corre la suite.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
LINT = SCRIPTS / "lint_invariantes.py"

IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
CORTE = "2026-09-01"

# Un linter de juguete con dos rechazos: uno con id estructurado y salida, otro sin nada.
LINTER_MIXTO = '''\
def fail(mensaje):
    print("FAIL " + mensaje)


def revisar(x):
    if not x:
        fail("[M-001] falta el dato. SALIDA: ejecuta  python3 arregla.py")
        return 1
    if x == 2:
        fail("esto no me gusta")
        return 1
    return 0
'''

LINTER_LIMPIO = '''\
def fail(mensaje):
    print("FAIL " + mensaje)


def revisar(x):
    if not x:
        fail("[M-002] falta el otro dato. SALIDA: ejecuta  python3 arregla.py --otro")
        return 1
    return 0
'''


class TallerSintetico:
    """Un taller de método mínimo: solo lo que las ocho señales leen."""

    def __init__(self, raiz):
        self.raiz = Path(raiz)
        for sub in ("docs/05-trabajo/peticiones", "docs/bugs", "docs/00-metodo/scripts",
                    ".runtime/aprobaciones", ".runtime/ejecuciones"):
            (self.raiz / sub).mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- S1
    def ficha(self, nombre, aprobado=None, recibo=False):
        carpeta = self.raiz / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        cabecera = f"---\nunidad: {nombre}\n"
        if aprobado:
            cabecera += f"aprobado: {aprobado}\n"
        (carpeta / "especificacion.md").write_text(
            cabecera + "---\n\n# " + nombre + "\n", encoding="utf-8")
        if recibo:
            (self.raiz / ".runtime/aprobaciones" / f"{nombre}-{aprobado}.json").write_text(
                json.dumps({"unidad": nombre, "fecha": aprobado,
                            "hora": f"{aprobado}T09:00:00"}), encoding="utf-8")

    # ---------------------------------------------------------------- S2 · S8
    def recibo(self, nombre, *, unidad, rol="constructor", resultado="ok",
               session_id=None, fecha=None):
        datos = {"schema": "ejecucion/v1", "id": nombre, "unidad": unidad, "rol": rol,
                 "lease": {"session_id": session_id} if session_id else {}}
        if resultado is not None:
            datos["resultado"] = resultado
        if fecha:
            datos["fecha"] = fecha
        (self.raiz / ".runtime/ejecuciones" / f"{nombre}.json").write_text(
            json.dumps(datos), encoding="utf-8")

    # ---------------------------------------------------------------- S3 · S4
    def peticion(self, pid, *, estado, procesos=(), creada, actualizada=None):
        carpeta = self.raiz / "docs/05-trabajo/peticiones" / pid
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "peticion.json").write_text(json.dumps({
            "id": pid, "estado": estado, "creada": creada,
            "actualizada": actualizada or creada,
            "procesos": [{"id": f"{pid}-{i}", "estado": e}
                         for i, e in enumerate(procesos)],
        }), encoding="utf-8")

    # ---------------------------------------------------------------- S5 · S6
    def linter(self, nombre, fuente):
        (self.raiz / "docs/00-metodo/scripts" / nombre).write_text(fuente, encoding="utf-8")

    # ---------------------------------------------------------------- S7
    def reglas(self, entradas):
        (self.raiz / "docs/00-metodo/reglas.json").write_text(json.dumps({
            "base": {"sin_ejecutor": 0, "fecha": CORTE, "sha": "0000000"},
            "reglas": entradas,
        }), encoding="utf-8")

    def tests_del_repo(self, nombre, fuente):
        carpeta = self.raiz / "main/visor/tests"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / nombre).write_text(fuente, encoding="utf-8")


class InvariantesBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="invariantes-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()
        self.taller = TallerSintetico(self.ws)
        self.base = self.ws / "invariantes-baseline.json"

    def correr(self, *extra, corte=CORTE):
        return subprocess.run(
            [sys.executable, str(LINT), "--workspace", str(self.ws),
             "--corte", corte, "--base", str(self.base), *extra],
            capture_output=True, text=True, encoding="utf-8", errors="replace")

    def medir(self, corte=CORTE):
        salida = self.correr("--json", corte=corte)
        self.assertTrue(salida.stdout.strip(), salida.stdout + salida.stderr)
        datos = json.loads(salida.stdout)
        return datos, {s["id"]: s for s in datos["senales"]}, salida

    def congelar(self):
        salida = self.correr("--congelar")
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)


class OchoSenalesTest(InvariantesBase):
    """R1 · las ocho señales existen, se llaman por su id y traen denominador."""

    def test_r1_imprime_las_ocho_senales_con_su_denominador(self):
        salida = self.correr()
        for identificador in IDS:
            self.assertIn(identificador, salida.stdout,
                          f"falta la señal {identificador}:\n{salida.stdout}")
        _, senales, _ = self.medir()
        self.assertEqual(sorted(senales), sorted(IDS))
        for identificador, senal in senales.items():
            self.assertIn("violaciones", senal, identificador)
            self.assertIn("universo", senal, identificador)
            self.assertIn("posteriores", senal, identificador)
            self.assertIn("titulo", senal, identificador)

    def test_r1_taller_vacio_no_bloquea(self):
        self.congelar()
        salida = self.correr()
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("VEREDICTO: verde", salida.stdout)


class S1AprobadoSinReciboTest(InvariantesBase):
    def test_s1_cuenta_las_fichas_aprobadas_sin_recibo_con_denominador(self):
        self.taller.ficha("001-con-recibo", aprobado="2026-08-01", recibo=True)
        self.taller.ficha("002-sin-recibo", aprobado="2026-08-02")
        self.taller.ficha("003-sin-aprobar")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S1"]["violaciones"], 1)
        self.assertEqual(senales["S1"]["universo"], 2,
                         "el denominador son las fichas CON fecha de aprobado, no todas")
        self.assertEqual(senales["S1"]["posteriores"], 0)

    def test_s1_una_ficha_aprobada_despues_del_corte_y_sin_recibo_es_fail(self):
        self.congelar()
        self.taller.ficha("004-despues-del-corte", aprobado="2026-09-15")
        datos, senales, salida = self.medir()
        self.assertEqual(senales["S1"]["posteriores"], 1)
        self.assertEqual(datos["veredicto"], "rojo")
        self.assertEqual(self.correr().returncode, 1)

    def test_s1_mira_tambien_las_fichas_de_bug(self):
        (self.ws / "docs/bugs/900-un-bug.md").write_text(
            "---\nbug: 900\naprobado: 2026-08-03\n---\n", encoding="utf-8")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S1"]["violaciones"], 1)


class S2ReciboSinResultadoTest(InvariantesBase):
    def test_s2_el_ayudante_abierto_para_siempre_se_cuenta(self):
        self.taller.recibo("a", unidad="001-x", resultado="ok", fecha="2026-08-01T10:00:00")
        self.taller.recibo("b", unidad="001-x", resultado=None, fecha="2026-08-02T10:00:00")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S2"]["violaciones"], 1)
        self.assertEqual(senales["S2"]["universo"], 2)
        self.assertEqual(senales["S2"]["posteriores"], 0)

    def test_s2_un_recibo_abierto_posterior_al_corte_bloquea(self):
        self.congelar()
        self.taller.recibo("c", unidad="001-x", resultado=None, fecha="2026-09-20T10:00:00")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S2"]["posteriores"], 1)


class S3yS4PeticionesTest(InvariantesBase):
    def test_s3_cerrada_con_un_solo_proceso_terminal(self):
        self.taller.peticion("P-1", estado="cerrada", procesos=("terminal",),
                             creada="2026-08-01T10:00:00")
        self.taller.peticion("P-2", estado="cerrada", procesos=("terminal", "terminal"),
                             creada="2026-08-01T10:00:00")
        self.taller.peticion("P-3", estado="cerrada", procesos=(),
                             creada="2026-08-01T10:00:00")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S3"]["violaciones"], 2, "P-1 y P-3")
        self.assertEqual(senales["S3"]["universo"], 3)

    def test_s4_encaminada_sin_ningun_proceso_terminal(self):
        self.taller.peticion("P-4", estado="encaminada", procesos=("en_curso",),
                             creada="2026-08-01T10:00:00")
        self.taller.peticion("P-5", estado="encaminada", procesos=("terminal",),
                             creada="2026-08-01T10:00:00")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S4"]["violaciones"], 1)
        self.assertEqual(senales["S4"]["universo"], 2)

    def test_s4_una_encaminada_nueva_sin_terminal_es_posterior_al_corte(self):
        self.congelar()
        self.taller.peticion("P-6", estado="encaminada", procesos=(),
                             creada="2026-09-10T10:00:00")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S4"]["posteriores"], 1)


class S5yS6CodigoTest(InvariantesBase):
    def test_s5_cuenta_los_fail_sin_id_estructurado(self):
        self.taller.linter("lint_uno.py", LINTER_MIXTO)
        _, senales, _ = self.medir()
        self.assertEqual(senales["S5"]["violaciones"], 1, "el `[M-001]` sí lleva id")
        self.assertEqual(senales["S5"]["universo"], 2)

    def test_s6_cuenta_los_rechazos_que_no_nombran_salida(self):
        self.taller.linter("lint_uno.py", LINTER_MIXTO)
        _, senales, _ = self.medir()
        self.assertGreaterEqual(senales["S6"]["universo"], 2)
        self.assertGreaterEqual(senales["S6"]["violaciones"], 1)


class S7DientesTest(InvariantesBase):
    def test_s7_ejecutor_sin_par_de_dientes_declarado(self):
        self.taller.reglas({
            "R::uno": {"ejecutor": "unidad.py:puerta", "dientes": "test_dientes_uno_bloquea"},
            "R::dos": {"ejecutor": "unidad.py:otra", "dientes": None},
            "R::tres": {"ejecutor": None, "por_diseno": "no se puede"},
        })
        self.taller.tests_del_repo("test_dientes.py",
                                   "def test_dientes_uno_bloquea():\n    pass\n")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S7"]["violaciones"], 1, "solo `R::dos` está sin dientes")
        self.assertEqual(senales["S7"]["universo"], 2, "el denominador son los ejecutores")

    def test_s7_dientes_que_nombran_un_test_inexistente_no_cuentan(self):
        self.taller.reglas({
            "R::uno": {"ejecutor": "unidad.py:puerta", "dientes": "test_que_no_existe"},
        })
        _, senales, _ = self.medir()
        self.assertEqual(senales["S7"]["violaciones"], 1,
                         "un nombre escrito a mano no es un par de dientes")


class S8RevisorConSesionDelConstructorTest(InvariantesBase):
    def test_s8_el_auto_sello_se_cuenta_sobre_los_recibos_de_revisor(self):
        self.taller.recibo("c1", unidad="001-x", rol="constructor", session_id="AAA",
                           fecha="2026-08-01T10:00:00")
        self.taller.recibo("r1", unidad="001-x", rol="revisor", session_id="AAA",
                           fecha="2026-08-02T10:00:00")
        self.taller.recibo("c2", unidad="002-y", rol="constructor", session_id="BBB",
                           fecha="2026-08-01T10:00:00")
        self.taller.recibo("r2", unidad="002-y", rol="revisor", session_id="CCC",
                           fecha="2026-08-02T10:00:00")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S8"]["violaciones"], 1)
        self.assertEqual(senales["S8"]["universo"], 2, "el denominador son los revisores")


class TrinqueteEstructuralTest(InvariantesBase):
    """S5-S7 no tienen fecha por sujeto: su «posterior al corte» es lo que SUBE."""

    def test_una_senal_de_codigo_que_sube_sobre_la_base_es_posterior_al_corte(self):
        self.taller.linter("lint_uno.py", LINTER_MIXTO)
        self.congelar()
        self.taller.linter("lint_dos.py", LINTER_MIXTO)     # otro rechazo mudo más
        _, senales, salida = self.medir()
        self.assertGreater(senales["S5"]["posteriores"], 0,
                           "un `fail()` nuevo sin id es lo único que la reforma puede evitar")
        self.assertEqual(self.correr().returncode, 1)

    def test_una_senal_de_codigo_que_baja_no_bloquea(self):
        self.taller.linter("lint_uno.py", LINTER_MIXTO)
        self.taller.linter("lint_dos.py", LINTER_MIXTO)
        self.congelar()
        (self.ws / "docs/00-metodo/scripts/lint_dos.py").write_text(
            LINTER_LIMPIO, encoding="utf-8")
        _, senales, _ = self.medir()
        self.assertEqual(senales["S5"]["posteriores"], 0)
        self.assertEqual(self.correr().returncode, 0)

    def test_sin_linea_base_las_senales_de_codigo_no_pueden_bloquear(self):
        """Sin base congelada no hay «subió»: se informa y se dice cómo congelarla."""
        self.taller.linter("lint_uno.py", LINTER_MIXTO)
        salida = self.correr()
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("--congelar", salida.stdout)


class LineaBaseTest(InvariantesBase):
    def test_congelar_escribe_la_base_con_fecha_y_commit(self):
        self.taller.linter("lint_uno.py", LINTER_MIXTO)
        self.congelar()
        datos = json.loads(self.base.read_text(encoding="utf-8"))
        self.assertIn("base", datos)
        self.assertRegex(str(datos["base"].get("fecha")), r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("sha", datos["base"])
        self.assertEqual(sorted(datos["senales"]), sorted(IDS))

    def test_la_base_congelada_viaja_en_la_plantilla(self):
        """La línea base de la reforma se distribuye con el método, como `reglas.json`."""
        viajera = RAIZ / "plantilla/docs/00-metodo/invariantes-baseline.json"
        self.assertTrue(viajera.is_file(), f"falta {viajera}")
        datos = json.loads(viajera.read_text(encoding="utf-8"))
        self.assertEqual(sorted(datos["senales"]), sorted(IDS))
        self.assertRegex(str(datos["base"].get("fecha")), r"^\d{4}-\d{2}-\d{2}$")


class NoBloqueaElCierreTest(InvariantesBase):
    """El contrato de la 146 dice: linter nuevo que NO cambia lo que decide un guardián."""

    def test_lint_invariantes_no_esta_enganchado_a_lint_metodo_todavia(self):
        fuente = (SCRIPTS / "lint_metodo.py").read_text(encoding="utf-8")
        self.assertNotIn("lint_invariantes", fuente,
                         "la 146 solo añade la medida; engancharla al cierre es otra unidad")

    def test_la_salida_json_no_lleva_rutas_de_nadie(self):
        self.taller.ficha("005-x", aprobado="2026-08-01")
        datos, _, _ = self.medir()
        crudo = json.dumps(datos, ensure_ascii=False)
        self.assertNotIn("/Users/", crudo)


if __name__ == "__main__":
    unittest.main()
