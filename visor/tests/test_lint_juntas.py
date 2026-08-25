"""Guardián de juntas: lo que se rompe ENTRE dos piezas que por separado están bien (unidad 050).

`lint_juntas.py` vigila tres juntas medidas sobre el método:

  (a) el vocabulario que comparten `unidad.py`, `lint_metodo.py` y la prosa de
      `00-metodo/README.md`;
  (b) el tope de 250 líneas que promete el carril directo y que hasta hoy no medía nadie;
  (c) el inventario congelado de puertas duras, cada una con su columna `dueño`.

Aquí se prueban las reglas de comparación sobre workspaces sintéticos y —como integración—
la medida del diff sobre un repo git de verdad con dos ramas: medir un diff no se puede
simular sin mentir.

La marca de puerta dura se compone en trozos a propósito. El ADR-029 la retiró del texto del
método y `test_reglas_con_ejecutor.py` barre `visor/` entero para comprobarlo: escribirla
entera aquí pondría en rojo a ese guardián. La comprobación es exactamente la misma.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

RAIZ = Path(__file__).resolve().parents[2]
METODO = RAIZ / "plantilla/docs/00-metodo"
SCRIPTS = METODO / "scripts"
GUARDIAN = SCRIPTS / "lint_juntas.py"
INVENTARIO_REAL = METODO / "puertas.json"

MARCA = "HARD" + "-GATE"
ANGULOS = "<" + MARCA + ">"

TIPOS = ("bug", "feature", "refactor")
ESTADOS = ("planificada", "en_obra", "en_validacion", "mergeada")


def cargar_modulo():
    """El guardián como módulo, para probar sus piezas sin pasar por la terminal."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("lint_juntas_bajo_prueba", GUARDIAN)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def fuente_unidad(tipos=TIPOS, estados=ESTADOS, extra=""):
    return f"{extra}TIPOS = {list(tipos)!r}\nESTADOS = {set(estados)!r}\n"


def fuente_lint(tipos=TIPOS, estados=ESTADOS, extra=""):
    return f"{extra}TIPOS = {set(tipos)!r}\nESTADOS_UNIDAD = {set(estados)!r}\n"


def prosa(tipos=TIPOS, estados=ESTADOS):
    return ("# El método\n\n## Vocabulario\n\n"
            + "".join(f"- `{t}`\n" for t in tipos)
            + "".join(f"- `{e}`\n" for e in estados))


def escribir_workspace(raiz, *, unidad=None, lint=None, readme=None, puertas=None):
    """Un workspace mínimo: los dos scripts del vocabulario, la prosa y el inventario."""
    scripts = raiz / "docs/00-metodo/scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "unidad.py").write_text(unidad or fuente_unidad(), encoding="utf-8")
    (scripts / "lint_metodo.py").write_text(lint or fuente_lint(), encoding="utf-8")
    (raiz / "docs/00-metodo/README.md").write_text(readme or prosa(), encoding="utf-8")
    (raiz / "docs/00-metodo/puertas.json").write_text(
        json.dumps({"puertas": puertas if puertas is not None else {}}, ensure_ascii=False),
        encoding="utf-8")
    return raiz


def correr(raiz, *extra):
    return subprocess.run(
        [sys.executable, str(GUARDIAN), "--raiz", str(raiz), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(RAIZ), timeout=180,
    )


class VocabularioTest(unittest.TestCase):
    """R1, R2, R10 — la junta (a): el mismo vocabulario en tres sitios."""

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="juntas-vocabulario-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()

    def test_r1_vocabularios_desalineados_fallan_nombrando_el_lado(self):
        escribir_workspace(
            self.raiz,
            unidad=fuente_unidad(tipos=TIPOS + ("inventado",)),
            readme=prosa(tipos=TIPOS + ("inventado",)),
        )
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        self.assertIn("TIPOS", salida.stdout)
        self.assertIn("inventado", salida.stdout)
        self.assertIn("unidad.py", salida.stdout)

    def test_r1_alineados_dan_verde(self):
        escribir_workspace(self.raiz)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)

    def test_r1_los_estados_tambien_se_comparan(self):
        escribir_workspace(
            self.raiz,
            lint=fuente_lint(estados=ESTADOS + ("zombi",)),
            readme=prosa(estados=ESTADOS + ("zombi",)),
        )
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("zombi", salida.stdout)
        self.assertIn("lint_metodo.py", salida.stdout)

    def test_r2_termino_en_el_codigo_y_no_en_la_prosa_falla(self):
        """La deriva real que ya existía el 23-08: `en_validacion` sin fila en el README."""
        escribir_workspace(
            self.raiz,
            readme=prosa(estados=[e for e in ESTADOS if e != "en_validacion"]),
        )
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("en_validacion", salida.stdout)
        self.assertIn("README.md", salida.stdout)

    def test_r2_termino_en_la_prosa_y_no_en_el_codigo_falla(self):
        """El «o al revés» de R2: la prosa manda a escribir un valor que el script rechaza."""
        escribir_workspace(
            self.raiz,
            readme=prosa() + "\n```yaml\nestado: "
                   + " | ".join(list(ESTADOS) + ["jubilada"]) + "\n```\n",
        )
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("jubilada", salida.stdout)
        self.assertIn("README.md", salida.stdout)

    def test_r2_la_prosa_que_coincide_con_el_codigo_da_verde(self):
        escribir_workspace(
            self.raiz,
            readme=prosa() + "\n```yaml\nestado: " + " | ".join(ESTADOS) + "\n```\n",
        )
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)

    def test_r10_todo_fallo_nombra_un_comando(self):
        escribir_workspace(self.raiz, unidad=fuente_unidad(tipos=TIPOS + ("inventado",)))
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        for linea in salida.stdout.splitlines():
            if linea.strip().startswith("FAIL"):
                self.assertIn("salida:", salida.stdout)
        self.assertIn("lint_juntas.py", salida.stdout)


class LecturaSinImportarTest(unittest.TestCase):
    """R3 — las constantes se leen con AST: importar contagia la salida ajena."""

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="juntas-ast-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        self.modulo = cargar_modulo()

    def test_r3_un_modulo_que_sale_al_cargarse_se_lee_igual(self):
        veneno = "import sys\nsys.exit(1)\n"
        ruta = self.raiz / "veneno.py"
        ruta.write_text(fuente_unidad(extra=veneno), encoding="utf-8")
        leida = self.modulo.constante(ruta, "TIPOS")
        self.assertIsNotNone(leida)
        self.assertEqual(leida.valores, set(TIPOS))

    def test_r3_el_guardian_sigue_vivo_con_scripts_venenosos(self):
        veneno = "import sys\nprint('ruido ajeno')\nsys.exit(1)\n"
        escribir_workspace(
            self.raiz,
            unidad=fuente_unidad(extra=veneno),
            lint=fuente_lint(extra=veneno),
        )
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertNotIn("ruido ajeno", salida.stdout)

    def test_r3_una_constante_importada_de_repo_config_se_resuelve(self):
        """Tras centralizar el vocabulario, el valor ya no es un literal: es un alias."""
        (self.raiz / "repo_config.py").write_text(
            f"TIPOS = {list(TIPOS)!r}\n", encoding="utf-8")
        ruta = self.raiz / "unidad.py"
        ruta.write_text("import repo_config\n\nTIPOS = repo_config.TIPOS\n", encoding="utf-8")
        leida = self.modulo.constante(ruta, "TIPOS")
        self.assertIsNotNone(leida)
        self.assertEqual(leida.valores, set(TIPOS))
        self.assertIn("repo_config.py", leida.origen)


class TopeDelCarrilDirectoTest(unittest.TestCase):
    """R4, R5 — la junta (b): la promesa de 250 líneas, medida contra git."""

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="juntas-directo-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        escribir_workspace(self.raiz)
        self.repo = self.raiz / "main"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "base")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    def unidad_directa(self, nombre, estado="en_obra"):
        carpeta = self.raiz / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "especificacion.md").write_text(
            f"---\nunidad: {nombre}\ntipo: feature\ncarril: directo\nestado: {estado}\n---\n\n"
            f"# {nombre}\n", encoding="utf-8")

    def rama_con(self, nombre, lineas):
        self.git("checkout", "-b", nombre)
        (self.repo / "trabajo.txt").write_text("x\n" * lineas, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", f"{nombre}: trabajo")
        self.git("checkout", "main")

    def test_r4_un_directo_de_300_lineas_falla_con_el_numero_y_el_comando(self):
        self.unidad_directa("900-directo-gordo")
        self.rama_con("900-directo-gordo", 300)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        self.assertIn("900-directo-gordo", salida.stdout)
        self.assertIn("300", salida.stdout)
        self.assertIn("250", salida.stdout)
        self.assertIn("unidad.py", salida.stdout)

    def test_r4_un_directo_de_30_lineas_da_verde(self):
        self.unidad_directa("901-directo-fino")
        self.rama_con("901-directo-fino", 30)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)

    def test_r5_una_unidad_sin_rama_se_salta_en_silencio(self):
        """El cierre borra la rama: si eso fallara, cada cierre dejaría un FAIL eterno."""
        self.unidad_directa("902-ya-cerrada", estado="mergeada")
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertNotIn("902-ya-cerrada", salida.stdout)

    def test_r4_el_carril_normal_no_se_mide(self):
        carpeta = self.raiz / "docs/05-trabajo/903-normal-gorda"
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            "---\nunidad: 903-normal-gorda\ntipo: feature\ncarril: normal\nestado: en_obra\n"
            "---\n\n# 903\n", encoding="utf-8")
        self.rama_con("903-normal-gorda", 300)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)


class PuertasDurasTest(unittest.TestCase):
    """R6, R7, R8 — la junta (c): el inventario congelado, con columna de dueño."""

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="juntas-puertas-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        escribir_workspace(self.raiz)

    def runbook(self, texto):
        carpeta = self.raiz / "docs/00-metodo/runbooks"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "cierre.md").write_text(texto, encoding="utf-8")

    def test_r6_una_marca_nueva_fuera_del_inventario_falla(self):
        self.runbook(f"# Cierre\n\n`{ANGULOS}` **Sin OK del usuario no hay cierre.**\n")
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("runbooks/cierre.md", salida.stdout.replace("\\", "/"))

    def test_r7_una_entrada_huerfana_del_inventario_falla(self):
        escribir_workspace(self.raiz, puertas={
            "docs/00-metodo/runbooks/inventada.md::una puerta que ya no existe": {
                "fichero": "docs/00-metodo/runbooks/inventada.md",
                "texto": "una puerta que ya no existe",
                "dueno": None,
            }})
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("ya no existe", salida.stdout.lower())

    def test_r8_la_cuenta_sin_dueno_sale_en_la_salida_normal(self):
        self.runbook(f"# Cierre\n\n`{ANGULOS}` **Sin OK del usuario no hay cierre.**\n")
        congelar = correr(self.raiz, "--congelar-puertas")
        self.assertEqual(congelar.returncode, 0, congelar.stdout + congelar.stderr)
        datos = json.loads(
            (self.raiz / "docs/00-metodo/puertas.json").read_text(encoding="utf-8"))
        self.assertEqual(len(datos["puertas"]), 1)
        self.assertIsNone(next(iter(datos["puertas"].values()))["dueno"])
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("1 sin dueño", salida.stdout)

    def test_r8_una_puerta_con_dueno_no_cuenta_como_deuda(self):
        self.runbook(f"# Cierre\n\n`{ANGULOS}` **Sin OK del usuario no hay cierre.**\n")
        self.assertEqual(correr(self.raiz, "--congelar-puertas").returncode, 0)
        ruta = self.raiz / "docs/00-metodo/puertas.json"
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        for entrada in datos["puertas"].values():
            entrada["dueno"] = "unidad.py cerrar"
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout)
        self.assertIn("0 sin dueño", salida.stdout)

    def test_r6_sin_inventario_el_guardian_dice_como_crearlo(self):
        (self.raiz / "docs/00-metodo/puertas.json").unlink()
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("--congelar-puertas", salida.stdout)


class CarrilesTest(unittest.TestCase):
    """R9 — dos conceptos con el mismo nombre no son una deriva: se documentan."""

    def test_r9_los_carriles_reales_de_hoy_no_son_fallo(self):
        salida = correr(METODO.parent.parent)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("CARRILES", salida.stdout)

    def test_r9_el_guardian_los_nombra_sin_unificarlos(self):
        salida = correr(METODO.parent.parent)
        self.assertIn("peticion.py", salida.stdout)
        self.assertIn("lint_metodo.py", salida.stdout)


class SobreElMetodoRealTest(unittest.TestCase):
    """El guardián se aplica sobre el método que viaja: verde y con inventario congelado."""

    def test_el_metodo_de_la_plantilla_pasa_sus_propias_juntas(self):
        salida = correr(METODO.parent.parent)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)

    def test_el_inventario_de_puertas_viaja_con_el_metodo(self):
        self.assertTrue(INVENTARIO_REAL.is_file(),
                        "puertas.json es la memoria del trinquete: sin él no viaja nada")
        datos = json.loads(INVENTARIO_REAL.read_text(encoding="utf-8"))
        self.assertIn("puertas", datos)
        for clave, entrada in datos["puertas"].items():
            self.assertIn("dueno", entrada, clave)

    def test_el_guardian_y_su_inventario_los_reparte_el_bootstrap(self):
        sys.path.insert(0, str(RAIZ / "visor"))
        try:
            import bootstrap
        finally:
            sys.path.remove(str(RAIZ / "visor"))
        self.assertIn("scripts/lint_juntas.py", bootstrap.ARCHIVOS_METODO)
        self.assertIn("puertas.json", bootstrap.ARCHIVOS_METODO)

    def test_lint_metodo_lleva_dentro_el_guardian_de_juntas(self):
        """Un guardián que nadie llama es prosa: el enganche es la mitad del trabajo."""
        fuente = (SCRIPTS / "lint_metodo.py").read_text(encoding="utf-8")
        self.assertIn("lint_juntas.py", fuente)

    def test_el_vocabulario_vive_en_un_solo_sitio(self):
        """R1 en el método real: `unidad.py` y `lint_metodo.py` ya no lo redeclaran."""
        modulo = cargar_modulo()
        for fichero, nombre in (("unidad.py", "TIPOS"), ("unidad.py", "ESTADOS"),
                                ("lint_metodo.py", "TIPOS"),
                                ("lint_metodo.py", "ESTADOS_UNIDAD")):
            leida = modulo.constante(SCRIPTS / fichero, nombre)
            self.assertIsNotNone(leida, f"{fichero}:{nombre}")
            self.assertIn("repo_config.py", leida.origen, f"{fichero}:{nombre}")


if __name__ == "__main__":
    unittest.main()
