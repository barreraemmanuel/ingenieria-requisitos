"""Guardián de juntas: lo que se rompe ENTRE dos piezas que por separado están bien (unidad 050).

`lint_juntas.py` vigila tres juntas medidas sobre el método:

  (a) el vocabulario que comparten `unidad.py`, `lint_metodo.py` y la prosa de
      `00-metodo/README.md`;
  (b) el tope de 250 líneas que promete el carril directo y que hasta hoy no medía nadie;
  (c) el inventario congelado de puertas duras, cada una con su columna `dueño`;
  (d) el inventario congelado de REGLAS del método, cada una con ejecutor, con motivo de
      inejecutabilidad, o contada como huérfana en una cuenta que solo puede bajar (unidad 073).

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
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
METODO = RAIZ / "plantilla/docs/00-metodo"
SCRIPTS = METODO / "scripts"
GUARDIAN = SCRIPTS / "lint_juntas.py"
INVENTARIO_REAL = METODO / "puertas.json"
REGLAS_REAL = METODO / "reglas.json"

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


def inventario_reglas(reglas=None, base=None):
    """El inventario de la junta (d), con su base congelada (número + fecha + commit)."""
    return {
        "base": base if base is not None
        else {"sin_ejecutor": 0, "fecha": "2026-01-01", "sha": "0000000"},
        "reglas": reglas or {},
    }


def regla(fichero="AGENTS.md", texto="Una regla", ejecutor=None, por_diseno=None):
    return {"fichero": fichero, "texto": texto, "ejecutor": ejecutor, "por_diseno": por_diseno}


def escribir_workspace(raiz, *, unidad=None, lint=None, readme=None, puertas=None,
                       agents=None, reglas=None):
    """Un workspace mínimo: los dos scripts del vocabulario, la prosa y los inventarios."""
    scripts = raiz / "docs/00-metodo/scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "unidad.py").write_text(unidad or fuente_unidad(), encoding="utf-8")
    (scripts / "lint_metodo.py").write_text(lint or fuente_lint(), encoding="utf-8")
    (raiz / "docs/00-metodo/README.md").write_text(readme or prosa(), encoding="utf-8")
    (raiz / "docs/00-metodo/puertas.json").write_text(
        json.dumps({"puertas": puertas if puertas is not None else {}}, ensure_ascii=False),
        encoding="utf-8")
    if agents is not None:
        (raiz / "AGENTS.md").write_text(agents, encoding="utf-8")
    (raiz / "docs/00-metodo/reglas.json").write_text(
        json.dumps(reglas if reglas is not None else inventario_reglas(), ensure_ascii=False),
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
        # Una puerta dura ES una regla (R1 de la 073): plantar la marca crea también una regla
        # nueva. Se inventaría aquí para que estos tests sigan midiendo la junta (c) sola.
        correr(self.raiz, "--congelar-reglas")

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


AGENTS_MINIMO = """# AGENTS.md de prueba

## Reglas duras

1. **Primera regla inventada.** Cuerpo que no importa.
2. **Segunda regla inventada.** Cuerpo que tampoco importa.

## Reglas de oro (siempre)

- **Una regla de oro inventada.** Con su cuerpo.

## Otra sección

- **Esto no es una regla de oro**, porque no está bajo ese título.
"""


class ReglasConEjecutorTest(unittest.TestCase):
    """R1-R6 de la 073 — la junta (d): toda regla tiene ejecutor, está declarada inejecutable
    o está contada, y la cuenta de las que no ejecuta nadie SOLO PUEDE BAJAR."""

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="juntas-reglas-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        self.modulo = cargar_modulo()

    def inventario_de(self, agents, **por_clave):
        """Congela el inventario a mano a partir de las reglas que AGENTS.md declara hoy.

        Cada `por_clave` mapea un trozo del texto de la regla a su entrada, para no tener que
        escribir las anclas completas en cada test.
        """
        escribir_workspace(self.raiz, agents=agents)
        entradas = {}
        for viva in self.modulo.reglas_en_prosa(self.raiz):
            clave = self.modulo.clave_de(viva)
            entrada = regla(fichero=viva["fichero"], texto=viva["texto"])
            for trozo, ajuste in por_clave.items():
                if trozo.replace("_", " ").lower() in viva["texto"].lower():
                    entrada.update(ajuste)
            entradas[clave] = entrada
        return entradas

    def sembrar(self, agents, base_sin_ejecutor=None, **por_clave):
        entradas = self.inventario_de(agents, **por_clave)
        sin = sum(1 for e in entradas.values()
                  if not e.get("ejecutor") and not e.get("por_diseno"))
        base = {"sin_ejecutor": sin if base_sin_ejecutor is None else base_sin_ejecutor,
                "fecha": "2026-01-01", "sha": "0000000"}
        escribir_workspace(self.raiz, agents=agents,
                           reglas=inventario_reglas(entradas, base))
        return entradas

    # ---- R1: el extractor
    def test_r1_el_extractor_coge_numerales_y_reglas_de_oro_y_nada_mas(self):
        escribir_workspace(self.raiz, agents=AGENTS_MINIMO)
        textos = [r["texto"] for r in self.modulo.reglas_en_prosa(self.raiz)]
        self.assertIn("Primera regla inventada.", textos)
        self.assertIn("Segunda regla inventada.", textos)
        self.assertIn("Una regla de oro inventada.", textos)
        self.assertNotIn("Esto no es una regla de oro", textos)

    def test_r1_una_puerta_dura_de_un_runbook_tambien_es_una_regla(self):
        escribir_workspace(self.raiz, agents=AGENTS_MINIMO)
        carpeta = self.raiz / "docs/00-metodo/runbooks"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "cierre.md").write_text(
            f"# Cierre\n\n`{ANGULOS}` **Sin OK del usuario no hay cierre.**\n",
            encoding="utf-8")
        ficheros = {r["fichero"] for r in self.modulo.reglas_en_prosa(self.raiz)}
        self.assertIn("docs/00-metodo/runbooks/cierre.md", ficheros)

    # ---- R2: una regla nueva sin entrada
    def test_r2_una_regla_nueva_sin_entrada_falla_nombrando_ancla_y_comando(self):
        self.sembrar(AGENTS_MINIMO)
        (self.raiz / "AGENTS.md").write_text(
            AGENTS_MINIMO.replace(
                "2. **Segunda regla inventada.**",
                "2. **Segunda regla inventada.** Cuerpo.\n3. **Regla diecisiete recién nacida.**"),
            encoding="utf-8")
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        self.assertIn("Regla diecisiete recién nacida", salida.stdout)
        self.assertIn("AGENTS.md", salida.stdout)
        self.assertIn("--congelar-reglas", salida.stdout)

    def test_r2_el_inventario_completo_da_verde(self):
        self.sembrar(AGENTS_MINIMO)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)

    # ---- R3: el trinquete (criterio PORTANTE)
    def test_r3_la_cuenta_que_sube_falla(self):
        """El PORTANTE: sin trinquete sobre la cuenta, el inventario es una foto más.

        Tres reglas huérfanas contra una base de dos: exactamente lo que pasa cuando alguien
        escribe una regla nueva y no le pone ejecutor, o cuando se lo quita a una que lo tenía.
        """
        self.sembrar(AGENTS_MINIMO, base_sin_ejecutor=2)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        self.assertIn("sin ejecutor", salida.stdout)
        self.assertIn("base 2", salida.stdout)
        self.assertIn("--congelar-reglas", salida.stdout)

    def test_r3_la_cuenta_que_baja_da_verde_y_lo_dice(self):
        self.sembrar(AGENTS_MINIMO, base_sin_ejecutor=9)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("3 reglas sin ejecutor (base 9)", salida.stdout)

    def test_r5_la_cuenta_sale_aunque_no_falle(self):
        self.sembrar(AGENTS_MINIMO)
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("3 reglas sin ejecutor (base 3)", salida.stdout)

    def test_r3_por_diseno_no_cuenta_como_sin_ejecutor(self):
        self.sembrar(AGENTS_MINIMO, base_sin_ejecutor=3,
                     primera_regla={"por_diseno": "solo la persona sabe si lo leyó"})
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("2 reglas sin ejecutor (base 3)", salida.stdout)

    # ---- R4: el ejecutor perdido
    def test_r4_un_ejecutor_que_ya_no_existe_falla(self):
        self.sembrar(AGENTS_MINIMO, base_sin_ejecutor=3,
                     primera_regla={"ejecutor": "unidad.py:no_existe"})
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        self.assertIn("unidad.py:no_existe", salida.stdout)
        self.assertIn("Primera regla inventada", salida.stdout)

    def test_r4_un_ejecutor_que_existe_de_verdad_da_verde(self):
        entradas = self.inventario_de(
            AGENTS_MINIMO, primera_regla={"ejecutor": "unidad.py:cerrar"})
        escribir_workspace(
            self.raiz, agents=AGENTS_MINIMO,
            unidad=fuente_unidad() + "\n\ndef cerrar():\n    return 1\n",
            reglas=inventario_reglas(
                entradas, {"sin_ejecutor": 2, "fecha": "2026-01-01", "sha": "0000000"}))
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("2 reglas sin ejecutor (base 2)", salida.stdout)

    def test_r4_un_ejecutor_en_un_script_que_ya_no_esta_falla(self):
        self.sembrar(AGENTS_MINIMO, base_sin_ejecutor=3,
                     primera_regla={"ejecutor": "borrado.py:lo_que_sea"})
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("borrado.py", salida.stdout)

    # ---- R6: la base se recongela con un comando
    def test_r6_congelar_escribe_la_cuenta_con_fecha_y_commit(self):
        escribir_workspace(self.raiz, agents=AGENTS_MINIMO)
        for orden in (("init", "-b", "main"), ("config", "user.name", "Test"),
                      ("config", "user.email", "test@example.com"), ("add", "-A"),
                      ("commit", "-m", "base")):
            subprocess.run(["git", *orden], cwd=self.raiz, check=True, capture_output=True)
        salida = correr(self.raiz, "--congelar-reglas")
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        datos = json.loads(
            (self.raiz / "docs/00-metodo/reglas.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["base"]["sin_ejecutor"], 3)
        self.assertRegex(datos["base"]["fecha"], r"^\d{4}-\d{2}-\d{2}$")
        sha = subprocess.run(["git", "-C", str(self.raiz), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(datos["base"]["sha"], sha)
        self.assertEqual(correr(self.raiz).returncode, 0)

    def test_r6_congelar_no_pierde_los_ejecutores_ya_declarados(self):
        """Recongelar adopta el encogimiento; NO borra la autoría, igual que en la junta (c)."""
        entradas = self.inventario_de(
            AGENTS_MINIMO, primera_regla={"ejecutor": "unidad.py:cerrar"})
        escribir_workspace(
            self.raiz, agents=AGENTS_MINIMO,
            unidad=fuente_unidad() + "\n\ndef cerrar():\n    return 1\n",
            reglas=inventario_reglas(entradas, {"sin_ejecutor": 5, "fecha": "2026-01-01",
                                                "sha": "0000000"}))
        self.assertEqual(correr(self.raiz, "--congelar-reglas").returncode, 0)
        datos = json.loads(
            (self.raiz / "docs/00-metodo/reglas.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["base"]["sin_ejecutor"], 2)
        ejecutores = [e.get("ejecutor") for e in datos["reglas"].values()]
        self.assertIn("unidad.py:cerrar", ejecutores)

    def test_r6_una_base_sin_fecha_ni_commit_no_vale(self):
        """Bajar el número a mano en el JSON no es recongelar: la base la escribe el comando."""
        entradas = self.inventario_de(AGENTS_MINIMO)
        escribir_workspace(self.raiz, agents=AGENTS_MINIMO,
                           reglas=inventario_reglas(entradas, {"sin_ejecutor": 3}))
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("--congelar-reglas", salida.stdout)

    def test_r6_sin_inventario_el_guardian_dice_como_crearlo(self):
        escribir_workspace(self.raiz, agents=AGENTS_MINIMO)
        (self.raiz / "docs/00-metodo/reglas.json").unlink()
        salida = correr(self.raiz)
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("--congelar-reglas", salida.stdout)


class ReglasDelMetodoRealTest(unittest.TestCase):
    """R1 y R7 sobre el método que viaja: el punto de partida honesto de hoy."""

    def test_r1_el_inventario_real_cubre_todas_las_reglas_de_hoy(self):
        modulo = cargar_modulo()
        raiz = METODO.parent.parent
        datos = json.loads(REGLAS_REAL.read_text(encoding="utf-8"))
        vivas = {modulo.clave_de(r) for r in modulo.reglas_en_prosa(raiz)}
        self.assertTrue(vivas, "el extractor no encuentra ni una regla en AGENTS.md")
        self.assertFalse(vivas - set(datos["reglas"]),
                         "reglas de la prosa que no están inventariadas")
        for clave, entrada in datos["reglas"].items():
            self.assertIn("ejecutor", entrada, clave)
            self.assertIn("por_diseno", entrada, clave)

    def test_r1_las_reglas_duras_numeradas_estan_todas(self):
        modulo = cargar_modulo()
        raiz = METODO.parent.parent
        vivas = [r for r in modulo.reglas_en_prosa(raiz) if r["fichero"] == "AGENTS.md"]
        self.assertGreaterEqual(len(vivas), 23, "faltan reglas de AGENTS.md")

    def test_r3_el_metodo_real_pasa_su_propio_trinquete(self):
        salida = correr(METODO.parent.parent)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("reglas sin ejecutor (base", salida.stdout)

    def test_r4_todos_los_ejecutores_declarados_existen(self):
        modulo = cargar_modulo()
        raiz = METODO.parent.parent
        datos = json.loads(REGLAS_REAL.read_text(encoding="utf-8"))
        for clave, entrada in datos["reglas"].items():
            if entrada.get("ejecutor"):
                self.assertIs(modulo.funcion_existe(raiz, entrada["ejecutor"]), True, clave)

    def test_r1_el_inventario_de_reglas_viaja_con_el_metodo(self):
        sys.path.insert(0, str(RAIZ / "visor"))
        try:
            import bootstrap
        finally:
            sys.path.remove(str(RAIZ / "visor"))
        self.assertIn("reglas.json", bootstrap.ARCHIVOS_METODO)

    def test_r7_los_rechazos_nuevos_estan_en_banda(self):
        salida = subprocess.run(
            [sys.executable, str(SCRIPTS / "lint_salidas.py"),
             "--scripts", "plantilla/docs/00-metodo/scripts"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(RAIZ), timeout=180)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)


class DientesDeCadaEjecutorTest(unittest.TestCase):
    """R3 de la 146 — la junta (e): un ejecutor sin par de dientes es un `def` del que
    nadie ha demostrado que haga nada, y esa cuenta SOLO PUEDE BAJAR.

    El motivo está medido: `funcion_existe()` devuelve `True` sobre la función VACIADA
    —cuerpo sustituido por «todo bien» con la forma correcta—, que es exactamente como los
    mecanismos se pierden en la práctica. La junta (d) mira que el `def` exista; esta mira
    que alguien haya demostrado que muerde.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="juntas-dientes-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        self.modulo = cargar_modulo()

    def taller(self, entradas, base, *, tests=""):
        (self.raiz / "docs/00-metodo").mkdir(parents=True, exist_ok=True)
        (self.raiz / "docs/00-metodo/reglas.json").write_text(json.dumps({
            "base": dict({"sin_ejecutor": 0, "fecha": "2026-09-01", "sha": "abc1234"}, **base),
            "reglas": entradas,
        }, ensure_ascii=False), encoding="utf-8")
        carpeta = self.raiz / "main/visor/tests"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "test_dientes_de_juguete.py").write_text(tests, encoding="utf-8")
        return self.raiz / "docs/00-metodo/reglas.json"

    def par_de(self, prefijo, funcion):
        return (f"def {prefijo}_bloquea():\n"
                f"    con_el_mecanismo({funcion})\n\n"
                f"def {prefijo}_abierto_pasa():\n"
                f"    sin_el_mecanismo({funcion})\n")

    # ------------------------------------------------------------------ R3
    def test_r3_un_ejecutor_con_su_par_completo_no_cuenta(self):
        inventario = self.taller(
            {"A::uno": {"ejecutor": "unidad.py:puerta", "id": "R-X-01",
                        "dientes": "test_dientes_R_X_01", "por_diseno": None}},
            {"sin_dientes": 0},
            tests=self.par_de("test_dientes_R_X_01", "puerta"))
        problemas, sin, tope = self.modulo.junta_dientes(self.raiz, inventario)
        self.assertEqual((sin, tope), (0, 0))
        self.assertEqual(problemas, [])

    def test_r3_un_ejecutor_sin_dientes_declarados_cuenta(self):
        inventario = self.taller(
            {"A::uno": {"ejecutor": "unidad.py:puerta", "dientes": None}},
            {"sin_dientes": 1})
        problemas, sin, _ = self.modulo.junta_dientes(self.raiz, inventario)
        self.assertEqual(sin, 1)
        self.assertEqual(problemas, [], "la base congelada es 1: no ha subido, no bloquea")

    def test_r3_la_cuenta_que_sube_sobre_la_base_es_fail_con_salida(self):
        inventario = self.taller(
            {"A::uno": {"ejecutor": "unidad.py:puerta", "dientes": None},
             "A::dos": {"ejecutor": "unidad.py:otra", "dientes": None}},
            {"sin_dientes": 1})
        problemas, sin, tope = self.modulo.junta_dientes(self.raiz, inventario)
        self.assertEqual((sin, tope), (2, 1))
        self.assertEqual(len(problemas), 1)
        self.assertIn("SUBIÓ", problemas[0][0])
        self.assertIn("test_dientes_", problemas[0][1], "el rechazo no nombra cómo salir")

    def test_r3_un_par_declarado_a_medias_no_vale(self):
        """Un `_bloquea` sin su `_abierto_pasa` no demuestra que el mecanismo muerda."""
        inventario = self.taller(
            {"A::uno": {"ejecutor": "unidad.py:puerta", "id": "R-X-01",
                        "dientes": "test_dientes_R_X_01", "por_diseno": None}},
            {"sin_dientes": 0},
            tests="def test_dientes_R_X_01_bloquea():\n    con_el_mecanismo(puerta)\n")
        problemas, sin, _ = self.modulo.junta_dientes(self.raiz, inventario)
        self.assertEqual(sin, 1)
        self.assertTrue(problemas)

    def test_r3_un_par_que_no_nombra_al_ejecutor_no_vale(self):
        """El nombre correcto no basta: el par tiene que hablar DE esta función."""
        inventario = self.taller(
            {"A::uno": {"ejecutor": "unidad.py:puerta_recibo_revisor", "id": "R-X-01",
                        "dientes": "test_dientes_R_X_01", "por_diseno": None}},
            {"sin_dientes": 0},
            tests=self.par_de("test_dientes_R_X_01", "otra_cosa_cualquiera"))
        problemas, sin, _ = self.modulo.junta_dientes(self.raiz, inventario)
        self.assertEqual(sin, 1)
        self.assertIn("no nombra", problemas[0][0])

    def test_r3_un_nombre_citado_en_un_comentario_no_es_un_test(self):
        """Se lee con `ast`: «tener» no puede ser «parecer», que es el fallo que se mide."""
        inventario = self.taller(
            {"A::uno": {"ejecutor": "unidad.py:puerta", "id": "R-X-01",
                        "dientes": "test_dientes_R_X_01", "por_diseno": None}},
            {"sin_dientes": 0},
            tests="# aquí iría test_dientes_R_X_01_bloquea y test_dientes_R_X_01_abierto_pasa\n")
        _, sin, _ = self.modulo.junta_dientes(self.raiz, inventario)
        self.assertEqual(sin, 1)

    def test_r3_sin_base_congelada_se_dice_como_congelarla(self):
        inventario = self.taller(
            {"A::uno": {"ejecutor": "unidad.py:puerta", "dientes": None}}, {})
        problemas, _, tope = self.modulo.junta_dientes(self.raiz, inventario)
        self.assertIsNone(tope)
        self.assertIn("--congelar-reglas", problemas[0][1])

    # ------------------------------------------------------------------ integración
    def test_r3_la_junta_e_es_opt_in_y_no_cambia_lo_que_decide_el_guardian_de_siempre(self):
        """La 146 mide; no mueve ninguna puerta de producción."""
        sin_flag = correr(METODO.parent.parent)
        con_flag = correr(METODO.parent.parent, "--dientes")
        self.assertEqual(sin_flag.returncode, 0, sin_flag.stdout + sin_flag.stderr)
        self.assertNotIn("(e) ejecutores con dientes", sin_flag.stdout)
        self.assertIn("(e) ejecutores con dientes", con_flag.stdout)

    def test_r3_el_metodo_real_pasa_su_propio_trinquete_de_dientes(self):
        salida = correr(METODO.parent.parent, "--dientes")
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("ejecutores sin par (base", salida.stdout)

    def test_r3_los_cuatro_ejecutores_medidos_declaran_id_y_par(self):
        datos = json.loads(REGLAS_REAL.read_text(encoding="utf-8"))
        con_par = {e["ejecutor"]: (e.get("id"), e.get("dientes"))
                   for e in datos["reglas"].values() if e.get("dientes")}
        self.assertEqual(con_par, {
            "unidad.py:puerta_recibo_revisor": ("R-REV-01", "test_dientes_R_REV_01"),
            "entrega.py:exigir_entrega_constructor": ("R-ENT-01", "test_dientes_R_ENT_01"),
            "lint_juntas.py:junta_tope_directo": ("R-DIR-01", "test_dientes_R_DIR_01"),
            "herramienta.py:cmd_comprobar": ("R-AVI-01", "test_dientes_R_AVI_01"),
            "canario.py:salida_hook_stop": ("R-CAN-01", "test_dientes_R_CAN_01"),
        })
        self.assertIsInstance(datos["base"].get("sin_dientes"), int,
                              "sin trinquete congelado, la cuenta puede subir sin ruido")


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


class TrinqueteDeLaBaseDeDientesTest(unittest.TestCase):
    """146 · ronda 2 — recongelar NO puede indultar una subida de `sin_dientes`.

    El adversario lo reprodujo: `--congelar-reglas` escribía el número de HOY sin mirar el
    de ayer, así que un constructor que acababa de perder cuatro pares de dientes los
    borraba del mapa con un solo comando, exit 0 y sin una línea de aviso. Una base que
    adopta sus propias regresiones no es un trinquete: es un indulto.

    El par de dientes de este mecanismo:
      · `_bloquea`      — con el trinquete puesto, la subida se RECHAZA y nombra su salida;
      · `_abierto_pasa` — con la comparación abierta solo dentro del test, la misma subida
                          entra sin rechistar (que es lo que pasaba antes de la ronda 2).
    """

    def setUp(self):
        self.tmp = TemporaryDirectory(prefix="juntas-trinquete-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        self.modulo = cargar_modulo()
        self.inventario = self.raiz / "docs/00-metodo/reglas.json"
        self.inventario.parent.mkdir(parents=True, exist_ok=True)

    def sembrar_base(self, sin_dientes):
        """Una base ya congelada: dos ejecutores, y `sin_dientes` en el número que se diga."""
        self.inventario.write_text(json.dumps({
            "base": {"sin_ejecutor": 0, "fecha": "2026-09-01", "sha": "abc1234",
                     "sin_dientes": sin_dientes},
            "reglas": {},
        }, ensure_ascii=False), encoding="utf-8")

    def reglas_en_prosa_falsas(self, cuantas):
        return [{"fichero": "AGENTS.md", "texto": f"regla {i}"} for i in range(cuantas)]

    def congelar(self, motivo=None):
        return self.modulo.congelar_reglas(
            self.raiz, self.inventario, self.reglas_en_prosa_falsas(0), motivo)

    # ------------------------------------------------------------------ el par
    def test_dientes_trinquete_reglas_bloquea(self):
        """Con el mecanismo: la subida se rechaza y no toca el fichero."""
        self.sembrar_base(1)
        # Sin reglas en prosa, `sin_dientes` recalculado es 0: eso ENCOGE y debe entrar.
        congeladas, _, crecidas = self.congelar()
        self.assertIsNotNone(congeladas, "encoger nunca se bloquea")
        self.assertEqual(crecidas, [])

        # Ahora al revés: la base dice 0 y la realidad son 2 ejecutores sin par.
        self.inventario.write_text(json.dumps({
            "base": {"sin_ejecutor": 0, "fecha": "2026-09-01", "sha": "abc1234",
                     "sin_dientes": 0},
            "reglas": {"AGENTS.md::regla 0": {
                           "fichero": "AGENTS.md", "texto": "regla 0",
                           "ejecutor": "unidad.py:puerta", "dientes": None},
                       "AGENTS.md::regla 1": {
                           "fichero": "AGENTS.md", "texto": "regla 1",
                           "ejecutor": "unidad.py:otra", "dientes": None}},
        }, ensure_ascii=False), encoding="utf-8")
        antes = self.inventario.read_text(encoding="utf-8")
        congeladas, _, crecidas = self.modulo.congelar_reglas(
            self.raiz, self.inventario, self.reglas_en_prosa_falsas(2), None)
        self.assertIsNone(congeladas, "la subida de `sin_dientes` se coló sin firma")
        self.assertEqual(crecidas, [("sin_dientes", 0, 2)])
        self.assertEqual(self.inventario.read_text(encoding="utf-8"), antes,
                         "un rechazo que ya ha escrito el fichero no es un rechazo")

    def test_dientes_trinquete_reglas_abierto_pasa(self):
        """Con la comparación abierta solo aquí, la misma subida entra: el par mide ESTO."""
        self.inventario.write_text(json.dumps({
            "base": {"sin_ejecutor": 0, "fecha": "2026-09-01", "sha": "abc1234",
                     "sin_dientes": 0},
            "reglas": {"AGENTS.md::regla 0": {
                           "fichero": "AGENTS.md", "texto": "regla 0",
                           "ejecutor": "unidad.py:puerta", "dientes": None},
                       "AGENTS.md::regla 1": {
                           "fichero": "AGENTS.md", "texto": "regla 1",
                           "ejecutor": "unidad.py:otra", "dientes": None}},
        }, ensure_ascii=False), encoding="utf-8")
        # El interruptor vive en el test: la base anterior se lee como si no existiera, que
        # es exactamente lo que hacía el código antes de la ronda 2.
        real = self.modulo.json.loads

        def sin_memoria(texto):
            datos = real(texto)
            if isinstance(datos, dict) and "base" in datos:
                datos = dict(datos, base={})
            return datos

        with mock.patch.object(self.modulo.json, "loads", sin_memoria):
            congeladas, _, crecidas = self.modulo.congelar_reglas(
                self.raiz, self.inventario, self.reglas_en_prosa_falsas(2), None)
        self.assertIsNotNone(congeladas,
                             "sin la comparación la subida debería colarse; si no se cuela, "
                             "el par no está midiendo el trinquete")
        self.assertEqual(crecidas, [])

    # ------------------------------------------------------------------ la firma
    def test_con_motivo_la_subida_entra_y_queda_escrita_en_el_historial(self):
        self.inventario.write_text(json.dumps({
            "base": {"sin_ejecutor": 0, "fecha": "2026-09-01", "sha": "abc1234",
                     "sin_dientes": 0},
            "reglas": {"AGENTS.md::regla 0": {
                           "fichero": "AGENTS.md", "texto": "regla 0",
                           "ejecutor": "unidad.py:puerta", "dientes": None}},
        }, ensure_ascii=False), encoding="utf-8")
        congeladas, _, crecidas = self.modulo.congelar_reglas(
            self.raiz, self.inventario, self.reglas_en_prosa_falsas(1),
            "los pares se mudan de suite en la 147")
        self.assertIsNotNone(congeladas)
        datos = json.loads(self.inventario.read_text(encoding="utf-8"))
        self.assertEqual(datos["base"]["sin_dientes"], 1)
        self.assertEqual(len(datos["historial"]), 1)
        entrada = datos["historial"][0]
        self.assertEqual((entrada["cuenta"], entrada["de"], entrada["a"]),
                         ("sin_dientes", 0, 1))
        self.assertIn("147", entrada["motivo"])

    def test_el_rechazo_por_la_linea_de_comandos_nombra_su_salida(self):
        """Regla 13: un bloqueo que no dice cómo salir es un defecto, no un mensaje.

        Se monta el taller de verdad y se recorre el camino real (`--congelar-reglas` por la
        línea de comandos), no la función suelta: el rechazo tiene que llegar hasta la
        pantalla del agente con su salida nombrada.
        """
        escribir_workspace(self.raiz, agents=AGENTS_MINIMO)
        ruta = self.raiz / "docs/00-metodo/reglas.json"

        # 1. Inventariar lo que hay, que es el camino normal, y dejar la base honrada en 0
        #    diciendo que TODOS los ejecutores tienen su par.
        self.assertEqual(correr(self.raiz, "--congelar-reglas").returncode, 0)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        for entrada in datos["reglas"].values():
            entrada["ejecutor"] = "unidad.py:puerta"
            entrada["dientes"] = "test_dientes_R_X_01"
        datos["base"]["sin_dientes"] = 0
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

        # 2. La regresión: se pierden los pares (nadie los borra, se quedan sin declarar).
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        for entrada in datos["reglas"].values():
            entrada["dientes"] = None
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        antes = ruta.read_text(encoding="utf-8")

        # 3. El auto-indulto tiene que morir en la puerta.
        salida = correr(self.raiz, "--congelar-reglas")
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        self.assertIn("JUN-002", salida.stdout)
        self.assertIn("--motivo", salida.stdout)
        self.assertIn("sin_dientes", salida.stdout)
        self.assertEqual(ruta.read_text(encoding="utf-8"), antes,
                         "el rechazo escribió el fichero igualmente")

        # 4. Y con la firma entra, dejando el porqué por escrito.
        firmado = correr(self.raiz, "--congelar-reglas", "--motivo", "medido de otra forma")
        self.assertEqual(firmado.returncode, 0, firmado.stdout + firmado.stderr)
        self.assertIn("AVISO", firmado.stdout)
        historial = json.loads(ruta.read_text(encoding="utf-8"))["historial"]
        self.assertEqual(historial[-1]["motivo"], "medido de otra forma")
