#!/usr/bin/env python3
"""El oráculo adjudicado de incidentes: un denominador que cualquiera puede contar.

La objeción que da origen a esta unidad es de conteo, no de opinión: los 93 registros de
la caja negra con los que se midió la reforma tienen todos `cwd` bajo el mismo `/Users`,
o sea que **ningún fallo reportado por los alumnos estaba en el denominador**. Estos tests
fijan el fichero que lo arregla: `fixtures/reforma/oraculo-incidentes.jsonl`, una fila por
incidente, dos bloques (`esta-maquina` y `alumnos`), con la familia `Fxx` a la que
pertenece, el arreglo de la reforma que lo cubriría y qué se espera de ese arreglo.

Qué vigila cada test:

- **esquema y bloques** — que las filas tengan todos los campos, con valores del vocabulario
  cerrado, y que el bloque 1 sea exactamente los 92 registros de la matriz de Codex
  (`docs/03-investigacion/2026-09-01-por-que-fallan-los-agentes/matriz-incidentes-reforma-v2.md`).
- **sin PII** — el repo es público y las fuentes del bloque 2 son correos de alumnos: aquí no
  entra un correo, ni una ruta de casa de nadie, ni un identificador de sesión.
- **cuentas del bloque 1 = matriz** — 61 operacionales repartidos 34 evita / 16 detecta /
  6 sin cobertura / 5 previo, más 13 de plataforma y 18 notas. Si alguien reclasifica una
  fila sin tocar la matriz, este test se pone rojo.
- **dedupe** — un incidente contado dos veces infla la cobertura. Los duplicados se enlazan
  con `duplicado_de` y salen del recuento de únicos, no del fichero.

La lista de nombres propios del índice de la caja de los alumnos NO vive aquí: escribirla
sería el mismo escape que el test quiere impedir. El test comprueba patrones (correo, HOME
de una persona, UUID de sesión) y, si el índice está en la máquina —vive fuera de git, en
`.runtime/` del meta-repo—, lo lee y comprueba también sus nombres.
"""
import json
import re
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FIXTURES = RAIZ / "visor" / "tests" / "fixtures" / "reforma"
ORACULO = FIXTURES / "oraculo-incidentes.jsonl"
FAMILIAS = FIXTURES / "oraculo-familias.json"
CUENTAS = RAIZ / "visor" / "tests" / "oraculo_cuentas.py"

BLOQUES = {"esta-maquina", "alumnos"}
ORIGENES = {"caja-negra", "caja-negra-alumno", "issue", "soporte"}
EXPECTATIVAS = {"evita", "detecta", "fuera de alcance", "previo", "sin cobertura"}
PARTICIONES = {"operacional", "plataforma", "notas"}
ARREGLOS = {"1", "2", "3", "4", "5", "6", "7", "8", "previo", "ninguno"}
CAMPOS = ("id", "bloque", "origen", "fecha", "harness", "so", "version_metodo",
          "familia", "arreglo", "expectativa", "particion", "sintoma", "evidencia",
          "duplicado_de", "contado")

# Los 92 del bloque 1, tal y como los nombra la matriz §3.
IDS_BLOQUE_1 = ([f"IN{n}" for n in range(1, 15)] + [f"IR{n}" for n in range(1, 56)]
                + [f"MM{n}" for n in range(1, 17)] + [f"WB{n}" for n in range(1, 8)])

RE_ID = re.compile(r"^(IN|IR|MM|WB)\d{1,2}$|^AL-\d{4}-\d{2}-\d{2}-\d{2}$"
                   r"|^GH-\d+$|^SOP-P-\d{8}-[0-9a-f]{8}$")


def filas():
    return [json.loads(linea) for linea in ORACULO.read_text(encoding="utf-8").splitlines()
            if linea.strip()]


class EsquemaYBloques(unittest.TestCase):
    """R1 · una fila por incidente, campos completos y los dos bloques poblados."""

    def setUp(self):
        self.filas = filas()
        self.familias = json.loads(FAMILIAS.read_text(encoding="utf-8"))

    def test_cada_fila_trae_todos_los_campos_con_valores_del_vocabulario(self):
        for f in self.filas:
            with self.subTest(id=f.get("id")):
                self.assertEqual(set(f), set(CAMPOS), "campos exactos, ni de más ni de menos")
                self.assertRegex(f["id"], RE_ID)
                self.assertIn(f["bloque"], BLOQUES)
                self.assertIn(f["origen"], ORIGENES)
                self.assertRegex(f["fecha"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertIn(f["arreglo"], ARREGLOS)
                self.assertIn(f["expectativa"], EXPECTATIVAS)
                self.assertIn(f["particion"], PARTICIONES)
                self.assertIn(f["familia"], self.familias,
                              "toda familia usada está definida en oraculo-familias.json")
                self.assertTrue(f["sintoma"].strip(), "el síntoma no puede ir vacío")
                self.assertNotIn("\n", f["sintoma"], "el síntoma es UNA línea")
                self.assertTrue(f["evidencia"].strip(), "sin evidencia no entra la fila")
                self.assertIsInstance(f["contado"], bool)

    def test_los_ids_no_se_repiten(self):
        repes = [i for i, n in Counter(f["id"] for f in self.filas).items() if n > 1]
        self.assertEqual(repes, [], "un id duplicado rompe el denominador")

    def test_el_bloque_1_son_los_92_registros_de_la_matriz(self):
        b1 = [f for f in self.filas if f["bloque"] == "esta-maquina"]
        self.assertEqual(len(b1), 92)
        self.assertEqual(sorted(f["id"] for f in b1), sorted(IDS_BLOQUE_1))
        self.assertTrue(all(f["origen"] == "caja-negra" for f in b1))

    def test_MM17_queda_fuera_por_ser_posterior_al_corte(self):
        self.assertNotIn("MM17", [f["id"] for f in self.filas])

    def test_el_bloque_2_trae_las_tres_fuentes_y_no_es_menor_que_ellas(self):
        b2 = [f for f in self.filas if f["bloque"] == "alumnos"]
        por_origen = Counter(f["origen"] for f in b2)
        self.assertEqual(por_origen["caja-negra-alumno"], 70,
                         "los 70 incidentes únicos bajados de la caja de los alumnos")
        self.assertGreaterEqual(por_origen["issue"], 14, "los issues abiertos del repo")
        self.assertEqual(por_origen["soporte"], 34, "las peticiones con autor de soporte")
        self.assertEqual(len(b2), sum(por_origen.values()))
        self.assertGreaterEqual(len(b2), 118)

    def test_las_familias_nuevas_del_bloque_2_estan_definidas_en_una_linea(self):
        for clave, definicion in self.familias.items():
            with self.subTest(familia=clave):
                self.assertRegex(clave, r"^F\d{2}$")
                self.assertTrue(definicion.strip())
                self.assertNotIn("\n", definicion)
        usadas = {f["familia"] for f in self.filas}
        self.assertEqual(usadas - set(self.familias), set())

    def test_un_arreglo_ninguno_nunca_promete_cobertura(self):
        for f in self.filas:
            if f["arreglo"] == "ninguno":
                with self.subTest(id=f["id"]):
                    self.assertIn(f["expectativa"], {"sin cobertura", "fuera de alcance"})
            if f["arreglo"] == "previo":
                with self.subTest(id=f["id"]):
                    self.assertIn(f["expectativa"], {"previo", "fuera de alcance"})


class SinPII(unittest.TestCase):
    """R2 · el repo es público: aquí no entra nada de nadie."""

    def setUp(self):
        self.texto = ORACULO.read_text(encoding="utf-8")
        self.filas = filas()

    def test_no_hay_correos(self):
        self.assertEqual(re.findall(r"@", self.texto), [], "ni una arroba: no hay correos")

    def test_la_unica_ruta_de_usuario_es_la_del_agente(self):
        usuarios = set(re.findall(r"/Users/([A-Za-z0-9._-]+)", self.texto))
        self.assertLessEqual(usuarios, {"agente"})
        windows = set(re.findall(r"[Cc]:\\+Users\\+([A-Za-z0-9._-]+)", self.texto))
        self.assertLessEqual(windows, {"agente"})
        self.assertNotIn("CloudStorage", self.texto)
        self.assertNotIn("/home/", self.texto)

    def test_no_hay_identificadores_de_sesion_ni_de_maquina(self):
        uuids = re.findall(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                           self.texto)
        self.assertEqual(uuids, [], "los UUID de sesión/incidente no viajan al repo")
        self.assertEqual(re.findall(r"\.local\b", self.texto), [])

    def test_ningun_nombre_del_indice_de_alumnos_aparece(self):
        indice = RAIZ.parent.parent / ".runtime" / "caja-negra-alumnos-indice.md"
        if not indice.exists():
            self.skipTest("el índice vive fuera de git; sin él no hay lista contra la que cruzar")
        nombres = set()
        for linea in indice.read_text(encoding="utf-8").splitlines():
            if linea.startswith("| 1") and linea.count("|") > 5:
                nombres.add(linea.split("|")[3].strip())
        nombres = {n for n in nombres if n and len(n) > 3 and "(" not in n}
        self.assertTrue(nombres, "el índice debería listar los remitentes")
        aparecen = sorted(n for n in nombres if re.search(rf"\b{re.escape(n)}\b", self.texto))
        self.assertEqual(aparecen, [], "un nombre propio del índice se coló en el fixture")

    def test_la_evidencia_apunta_a_una_fuente_citable_nunca_a_un_correo(self):
        patron = re.compile(
            r"^(matriz-incidentes-reforma-v2\.md|caja-negra-alumnos-indice\.md|"
            r"issue #\d+|P-\d{8}-[0-9a-f]{8})\b")
        for f in self.filas:
            with self.subTest(id=f["id"]):
                self.assertRegex(f["evidencia"], patron)


class CuentasDelBloque1(unittest.TestCase):
    """R3 · la matriz es el oráculo firmado; el fixture no puede decir otra cosa."""

    def setUp(self):
        self.b1 = [f for f in filas() if f["bloque"] == "esta-maquina"]

    def test_la_particion_es_61_operacionales_13_plataforma_18_notas(self):
        self.assertEqual(Counter(f["particion"] for f in self.b1),
                         Counter({"operacional": 61, "plataforma": 13, "notas": 18}))

    def test_los_61_operacionales_son_34_16_6_5(self):
        op = Counter(f["expectativa"] for f in self.b1 if f["particion"] == "operacional")
        self.assertEqual(op, Counter({"evita": 34, "detecta": 16,
                                      "sin cobertura": 6, "previo": 5}))

    def test_plataforma_y_notas_quedan_fuera_de_alcance_con_motivo(self):
        for f in self.b1:
            if f["particion"] in {"plataforma", "notas"}:
                with self.subTest(id=f["id"]):
                    self.assertEqual(f["expectativa"], "fuera de alcance")

    def test_los_seis_sin_cobertura_son_los_que_nombra_la_sintesis(self):
        sin = sorted(f["id"] for f in self.b1 if f["expectativa"] == "sin cobertura")
        self.assertEqual(sin, sorted(["IN13", "IR11", "IR14", "IR51", "MM14", "MM15"]))


class Dedupe(unittest.TestCase):
    """R1 · los duplicados se enlazan, no se cuentan: no inflar el denominador."""

    def setUp(self):
        self.filas = filas()
        self.por_id = {f["id"]: f for f in self.filas}

    def test_todo_duplicado_apunta_a_una_fila_que_existe_y_no_es_el_mismo(self):
        for f in self.filas:
            if f["duplicado_de"]:
                with self.subTest(id=f["id"]):
                    self.assertIn(f["duplicado_de"], self.por_id)
                    self.assertNotEqual(f["duplicado_de"], f["id"])
                    self.assertFalse(f["contado"], "un duplicado no entra en el recuento")

    def test_un_duplicado_no_apunta_a_otro_duplicado(self):
        for f in self.filas:
            if f["duplicado_de"]:
                with self.subTest(id=f["id"]):
                    self.assertIsNone(self.por_id[f["duplicado_de"]]["duplicado_de"],
                                      "las cadenas de duplicados esconden el original")

    def test_lo_no_duplicado_se_cuenta(self):
        for f in self.filas:
            if not f["duplicado_de"]:
                self.assertTrue(f["contado"], f["id"])

    def test_el_bloque_1_no_trae_duplicados_colgados(self):
        # IN8 es «decisión sobre IN7», y así lo dice la matriz: es una nota, no un duplicado
        # que se descuente, porque los 92 son el denominador congelado del corte.
        b1 = [f for f in self.filas if f["bloque"] == "esta-maquina"]
        self.assertTrue(all(f["contado"] for f in b1))

    def test_hay_duplicados_reales_enlazados_en_el_bloque_2(self):
        b2 = [f for f in self.filas if f["bloque"] == "alumnos"]
        enlazados = [f for f in b2 if f["duplicado_de"]]
        self.assertGreaterEqual(len(enlazados), 5,
                                "las tres fuentes se solapan; si no hay enlaces, no se cruzó")


class ScriptDeCuentas(unittest.TestCase):
    """R3 y R5 · las cuentas se publican y el fichero sabe crecer."""

    def correr(self, *args):
        return subprocess.run([sys.executable, str(CUENTAS), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_imprime_las_tres_tablas_y_la_particion(self):
        r = self.correr()
        self.assertEqual(r.returncode, 0, r.stderr)
        for titulo in ("por bloque", "por familia", "por arreglo", "partición"):
            self.assertIn(titulo, r.stdout.lower())

    def test_el_json_trae_las_mismas_cuentas_que_el_fixture(self):
        r = self.correr("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        datos = json.loads(r.stdout)
        self.assertEqual(datos["totales"]["filas"], len(filas()))
        self.assertEqual(datos["por_bloque"]["esta-maquina"]["total"], 92)
        op = datos["particion"]["esta-maquina"]
        self.assertEqual([op["operacional"], op["plataforma"], op["notas"]], [61, 13, 18])

    def test_la_ayuda_explica_como_se_anade_un_incidente_nuevo(self):
        r = self.correr("--ayuda")
        self.assertEqual(r.returncode, 0, r.stderr)
        for pieza in ("oraculo-incidentes.jsonl", "oraculo-familias.json",
                      "duplicado_de", "familia", "arreglo", "expectativa"):
            self.assertIn(pieza, r.stdout)


if __name__ == "__main__":
    unittest.main()
