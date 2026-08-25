"""Guardián de salidas: un rechazo que no nombra su salida no puede crecer (unidad 049).

`lint_salidas.py` recorre con AST los scripts del método, clasifica cada punto de rechazo en
`en_banda` / `por_diseño` / `fuera_de_banda` y compara los de fuera de banda contra una línea
base congelada que SOLO puede encoger. Aquí se prueba la clasificación sobre módulos
sintéticos, el trinquete sobre una copia de los scripts reales, y —como integración— que el
guardián se aplica su propia regla.
"""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
GUARDIAN = SCRIPTS / "lint_salidas.py"
BASELINE = RAIZ / "plantilla/docs/00-metodo/salidas-baseline.json"


def cargar_modulo():
    spec = importlib.util.spec_from_file_location("lint_salidas_bajo_prueba", GUARDIAN)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def correr(carpeta, base, *extra, cwd=None):
    return subprocess.run(
        [sys.executable, str(GUARDIAN), "--scripts", str(carpeta), "--base", str(base), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd or RAIZ), timeout=180,
    )


def escribir(carpeta, nombre, fuente):
    ruta = Path(carpeta) / nombre
    ruta.write_text(fuente, encoding="utf-8")
    return ruta


# Los ayudantes reales de los scripts del método, en pequeño: `fail` estampa la marca
# llamando a `err`, y `err` es quien habla con la terminal. Se dedenta cada trozo por
# separado: pegar dos bloques con sangrías distintas y dedentar el todo produce un módulo
# que no compila, y un módulo que no compila sale del inventario en silencio.
AYUDANTES = """
import sys

def err(msg):
    print(msg, file=sys.stderr)

def fail(msg):
    err(f"  FAIL {msg}")
"""


class ClasificacionTest(unittest.TestCase):
    """R1, R4, R8, R9 — el reparto en tres cubos sobre módulos sintéticos."""

    def cubos_de(self, *trozos, nombre="modulo.py"):
        modulo = cargar_modulo()
        with TemporaryDirectory() as tmp:
            escribir(tmp, nombre, "".join(textwrap.dedent(t) for t in trozos))
            cubos, errores = modulo.inventario(Path(tmp), Path(tmp))
            self.assertEqual(errores, [], "el módulo de prueba no compila")
            return cubos

    def test_r1_un_caso_de_cada_cubo(self):
        cubos = self.cubos_de(AYUDANTES, '''
            def con_salida():
                fail("no hay ficha para la unidad")
                err("  Créala primero: python3 unidad.py nueva feature")

            def por_diseno():
                # salida:por-diseño autoridad-humana: solo tú decides si esto se aprueba
                fail("la unidad no está aprobada")

            def muda():
                fail("la unidad ya está mergeada")
        ''')
        self.assertEqual(len(cubos["en_banda"]), 1, cubos)
        self.assertEqual(len(cubos["por_diseño"]), 1, cubos)
        self.assertEqual(len(cubos["fuera_de_banda"]), 1, cubos)

    def test_r4_forma_inventada_no_vale(self):
        cubos = self.cubos_de(AYUDANTES, '''
            def inventada():
                # salida:por-diseño porque-si: me apetece
                fail("la unidad ya está mergeada")
        ''')
        self.assertEqual(len(cubos["por_diseño"]), 0, cubos)
        self.assertEqual(len(cubos["fuera_de_banda"]), 1, cubos)

    def test_r8_ayudante_con_otro_nombre(self):
        cubos = self.cubos_de('''
            import sys

            def escupir(msg):
                print(msg, file=sys.stderr)

            def abortar(msg):
                escupir(f"  FAIL {msg}")

            def puerta():
                abortar("la unidad ya está mergeada")
        ''')
        self.assertEqual(len(cubos["fuera_de_banda"]), 1, cubos)

    def test_r9_cuerpo_del_ayudante_y_ok_warn_no_cuentan(self):
        cubos = self.cubos_de(AYUDANTES, '''
            def informa():
                print("OK: no hay unidades bloqueadas")
                print("WARN el FAIL de ayer ya no aparece")
        ''')
        self.assertEqual(sum(len(v) for v in cubos.values()), 0, cubos)


    def test_r9_un_ok_emitido_por_su_ayudante_tampoco_bloquea(self):
        """La marca OK la estampa `ok()`, igual que `fail()` estampa el FAIL.

        Salió al enganchar el guardián en `lint_metodo.py`: su propio `ok("todo rechazo nuevo
        nombra su salida")` entraba en el inventario como bloqueo mudo, porque la palabra
        «rechazo» estaba en el argumento y el «OK» lo ponía la imprenta.
        """
        cubos = self.cubos_de(AYUDANTES, '''
            def ok(msg):
                print(f"  OK   {msg}")

            def warn(msg):
                print(f"  WARN {msg}")

            def informa():
                ok("todo rechazo nuevo nombra su salida")
                warn("ayer hubo un rechazo mudo")
        ''')
        self.assertEqual(sum(len(v) for v in cubos.values()), 0, cubos)


class TrinqueteTest(unittest.TestCase):
    """R2, R3, R4, R5, R6, R7 — el trinquete sobre una copia de los scripts reales."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.carpeta = Path(self.tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, self.carpeta)
        self.base = Path(self.tmp.name) / "salidas-baseline.json"
        congelado = correr(self.carpeta, self.base, "--congelar")
        self.assertEqual(congelado.returncode, 0, congelado.stdout + congelado.stderr)
        self.victima = self.carpeta / "unidad.py"

    def anadir(self, codigo):
        with self.victima.open("a", encoding="utf-8") as f:
            f.write(textwrap.dedent(codigo))

    @staticmethod
    def cuenta_por_diseno(salida):
        for linea in salida.splitlines():
            if "por diseño" in linea:
                return int(linea.split()[-1])
        raise AssertionError(f"no encuentro el cubo «por diseño» en:\n{salida}")

    def test_r2_rechazo_nuevo_mudo_falla_y_senala_la_linea(self):
        self.anadir('''

            def prueba_del_guardian():
                fail("algo no cuadra y no digo como salir")
        ''')
        r = correr(self.carpeta, self.base)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("unidad.py:", r.stdout)
        self.assertIn("algo no cuadra", r.stdout)
        # R2: nombra LAS DOS formas de arreglarlo.
        self.assertIn("salida:por-diseño", r.stdout)
        self.assertRegex(r.stdout, r"nombra el comando")

    def test_r3_nombrando_el_comando_vuelve_a_verde(self):
        self.anadir('''

            def prueba_del_guardian():
                fail("algo no cuadra y no digo como salir")
                err("  Arreglalo:  python3 setup.py")
        ''')
        r = correr(self.carpeta, self.base)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_r4_marcador_valido_vuelve_a_verde_y_sube_por_diseno(self):
        antes = correr(self.carpeta, self.base)
        self.assertEqual(antes.returncode, 0, antes.stdout)
        self.anadir('''

            def prueba_del_guardian():
                # salida:por-diseño autoridad-humana: solo tú decides
                fail("algo no cuadra y no digo como salir")
        ''')
        r = correr(self.carpeta, self.base)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.cuenta_por_diseno(r.stdout),
                         self.cuenta_por_diseno(antes.stdout) + 1, r.stdout)

    def test_r5_mover_el_codigo_no_reabre_la_linea_base(self):
        modulo = cargar_modulo()
        antes = modulo.inventario(self.carpeta, self.carpeta)[0]
        fuente = self.victima.read_text(encoding="utf-8")
        self.victima.write_text("\n" * 30 + fuente, encoding="utf-8")
        r = correr(self.carpeta, self.base)
        self.assertEqual(r.returncode, 0, r.stdout)
        despues = modulo.inventario(self.carpeta, self.carpeta)[0]
        self.assertEqual({x["clave"] for x in antes["fuera_de_banda"]},
                         {x["clave"] for x in despues["fuera_de_banda"]})

    def test_r5_reescribir_el_texto_del_rechazo_si_la_reabre(self):
        fuente = self.victima.read_text(encoding="utf-8")
        base = json.loads(self.base.read_text(encoding="utf-8"))["entradas"]
        candidatos = [v["mensaje"].strip() for v in base.values() if v["fichero"] == "unidad.py"]
        aguja = next(m for m in candidatos if len(m) > 25 and m in fuente)
        self.victima.write_text(fuente.replace(aguja, aguja + " (redactado de nuevo)", 1),
                                encoding="utf-8")
        r = correr(self.carpeta, self.base)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("NUEVOS", r.stdout)

    def test_r6_entrada_huerfana_es_fail(self):
        datos = json.loads(self.base.read_text(encoding="utf-8"))
        datos["entradas"]["unidad.py::0000000000000000"] = {
            "fichero": "unidad.py", "mensaje": "un rechazo que ya no existe"}
        self.base.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        r = correr(self.carpeta, self.base)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("ya no casan", r.stdout)
        self.assertIn("--congelar", r.stdout)

    def test_r7_ejecutar_sin_congelar_no_toca_la_linea_base(self):
        huella = hashlib.sha256(self.base.read_bytes()).hexdigest()
        self.anadir('''

            def prueba_del_guardian():
                fail("algo no cuadra y no digo como salir")
        ''')
        r = correr(self.carpeta, self.base)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(hashlib.sha256(self.base.read_bytes()).hexdigest(), huella,
                         "un trinquete que se auto-afloja no es un trinquete")


class GuardianSobreSiMismoTest(unittest.TestCase):
    """R10 (integración) + la línea base versionada del repo."""

    def test_r10_los_fallos_del_guardian_nombran_su_comando(self):
        modulo = cargar_modulo()
        with TemporaryDirectory() as tmp:
            copia = Path(tmp) / "scripts"
            copia.mkdir(parents=True)
            shutil.copy(GUARDIAN, copia / GUARDIAN.name)
            cubos = modulo.inventario(copia, copia)[0]
        self.assertEqual(cubos["fuera_de_banda"], [],
                         "el guardián predica una regla que él mismo no cumple")
        self.assertTrue(cubos["en_banda"], "el guardián no rechaza en ningún sitio")

    def test_la_linea_base_del_repo_esta_en_verde(self):
        r = correr(SCRIPTS, BASELINE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
