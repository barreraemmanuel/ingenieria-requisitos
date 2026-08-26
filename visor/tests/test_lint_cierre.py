"""Unidad 045: el «47/47 verdes» tiene que cuadrar con algo que se pueda volver a mirar.

El parte de cierre lo escribe el mismo agente que hizo (o dirigió) el trabajo, y hasta hoy
nada comprobaba que su prosa concordara con la evidencia que dice tener. Estos tests fijan
las cuatro denegaciones del validador (R2-R6), el caso honesto que pasa en verde (R7) —un
guardián que solo sabe decir que no acaba desactivado—, la exigencia de la cabecera (R1),
que todo fallo nombre el comando que lo resuelve (R9) y, en integración, que el validador
corra de verdad dentro de `unidad.py cerrar` y bloquee (R8).
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
METODO = RAIZ / "plantilla/docs/00-metodo"
SCRIPTS = METODO / "scripts"
PLANTILLAS = METODO / "plantillas"
LINT_CIERRE = SCRIPTS / "lint_cierre.py"

SPEC = """---
unidad: 001-demo
tipo: feature
carril: normal
estado: en_revision
aprobado: 2026-08-25
ficheros: [app/demo.py]
---

# 001 · Demo

## Criterios de aceptación

- **R1** — lo primero.
- **R2** — lo segundo.
- **R3** — lo tercero.

## Plan de trabajo

- [x] 1. Tests en rojo
- [x] 2. Implementar
- [ ] 3. Cerrar
"""


def cabecera(**cambios):
    """La cabecera honesta; cada test cambia SOLO el dato que quiere poner a prueba."""
    datos = {
        "veredicto": "entregada",
        "tests_cmd": "python3 visor/tests/correr.py",
        "tests_exit": "0",
        "tests_output": ".runtime/001-demo/tests.txt",
        "tests_sha256": "PENDIENTE",
        "build_cmd": "python3 docs/00-metodo/scripts/lint_metodo.py",
        "build_exit": "0",
        "build_output": ".runtime/001-demo/lint.txt",
        "build_sha256": "PENDIENTE",
        "requisitos": "3/3",
        "plan": "2/3",
        "bloqueadores": "0",
    }
    datos.update(cambios)
    cuerpo = "\n".join(f"{k}: {v}" for k, v in datos.items())
    return "```parte-de-cierre\n" + cuerpo + "\n```\n"


# --- Unidad 071: la sección `## Aprendizajes` del hallazgos.md ---------------------------
def seccion_aprendizajes(constructor="- 2026-08-27 · constructor: el linter lee el fichero "
                                     "entero, no solo la cabecera.",
                         revisor="- 2026-08-27 · revisor: ninguno"):
    """La sección tal y como la trae la plantilla, con el contenido que pida cada caso."""
    partes = ["## Aprendizajes\n"]
    if constructor is not None:
        partes.append("```aprendizajes-constructor\n" + constructor + "\n```\n")
    if revisor is not None:
        partes.append("```aprendizajes-revisor\n" + revisor + "\n```\n")
    return "\n".join(partes)


APRENDIZAJES_OK = seccion_aprendizajes()
APRENDIZAJES_MARCADOR = seccion_aprendizajes(constructor="- —", revisor="- —")
APRENDIZAJES_NINGUNO = seccion_aprendizajes(constructor="- 2026-08-27 · constructor: ninguno",
                                            revisor="- 2026-08-27 · revisor: ninguno")


class ValidadorTest(unittest.TestCase):
    """Un workspace de juguete con una unidad coherente; cada caso introduce una mentira."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-cierre-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        self.carpeta = self.ws / "docs/05-trabajo/001-demo"
        self.carpeta.mkdir(parents=True)
        (self.carpeta / "especificacion.md").write_text(SPEC, encoding="utf-8")
        # Vía legacy (unidad 027): la unidad no nace de una petición, y no es lo que se
        # prueba aquí. Lo que se prueba es que el parte de cierre llegue a las puertas.
        peticiones = self.ws / "docs/05-trabajo/peticiones"
        peticiones.mkdir(parents=True)
        (peticiones / "LEGACY.json").write_text(json.dumps({
            "formato": 1, "modo": "observacion",
            "unidades": ["001-demo"], "bugs": [], "ramas": []}), encoding="utf-8")
        self.runtime = self.ws / ".runtime/001-demo"
        self.runtime.mkdir(parents=True)
        self.hashes = {}
        for nombre in ("tests.txt", "lint.txt"):
            ruta = self.runtime / nombre
            ruta.write_text(f"salida real de {nombre}\n", encoding="utf-8")
            self.hashes[nombre] = hashlib.sha256(ruta.read_bytes()).hexdigest()

    def escribir_parte(self, texto, aprendizajes=APRENDIZAJES_OK):
        """`aprendizajes=None` escribe un hallazgos.md de la plantilla ANTERIOR a la 071."""
        cuerpo = texto + ("\n" + aprendizajes if aprendizajes else "")
        (self.carpeta / "hallazgos.md").write_text(
            "---\nunidad: 001-demo\n---\n\n# 001 · Hallazgos\n\n" + cuerpo,
            encoding="utf-8")

    def parte_honesto(self, **cambios):
        datos = {"tests_sha256": self.hashes["tests.txt"],
                 "build_sha256": self.hashes["lint.txt"]}
        datos.update(cambios)
        return cabecera(**datos)

    def validar(self, *extra):
        return subprocess.run(
            [sys.executable, str(LINT_CIERRE), "001-demo", "--raiz", str(self.ws), *extra],
            text=True, encoding="utf-8", errors="replace", capture_output=True)

    def denegado(self, salida):
        """Un fallo de verdad: código 1, la palabra FAIL y (R9) el comando que lo resuelve."""
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        texto = salida.stdout + salida.stderr
        self.assertIn("FAIL", texto)
        self.assertIn("salida:", texto)
        return texto

    # --- R7: el caso honesto ------------------------------------------------------------
    def test_parte_honesto_pasa_en_verde(self):
        self.escribir_parte(self.parte_honesto())
        salida = self.validar()
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("OK", salida.stdout)

    # --- R1: sin cabecera no hay parte --------------------------------------------------
    def test_sin_bloque_de_cabecera_falla(self):
        self.escribir_parte("Todo salió bien, 47/47 verdes.\n")
        texto = self.denegado(self.validar())
        self.assertIn("parte-de-cierre", texto)

    def test_cabecera_a_medias_falla_nombrando_las_claves(self):
        self.escribir_parte("```parte-de-cierre\nveredicto: entregada\n```\n")
        texto = self.denegado(self.validar())
        self.assertIn("tests_exit", texto)

    def test_cabecera_sin_rellenar_falla(self):
        """La plantilla trae la cabecera con marcadores: dejarla tal cual no es un parte."""
        self.escribir_parte(cabecera(
            veredicto="—", tests_cmd="—", tests_exit="—", tests_output="—",
            tests_sha256="—", build_cmd="—", build_exit="—", build_output="—",
            build_sha256="—", requisitos="—", plan="—", bloqueadores="—"))
        texto = self.denegado(self.validar())
        self.assertIn("sin rellenar", texto)

    # --- R2: la mentira clásica ---------------------------------------------------------
    def test_exito_con_codigo_de_salida_distinto_de_cero_se_deniega(self):
        self.escribir_parte(self.parte_honesto(veredicto="entregada", tests_exit="1"))
        texto = self.denegado(self.validar())
        self.assertIn("tests_exit", texto)
        self.assertIn("entregada", texto)

    # --- R3: la mentira que casi nadie comprueba ----------------------------------------
    def test_fallo_con_toda_la_evidencia_en_verde_se_deniega(self):
        self.escribir_parte(self.parte_honesto(veredicto="fallo"))
        texto = self.denegado(self.validar())
        self.assertIn("verde", texto)

    # --- R4: los números se cuentan de verdad -------------------------------------------
    def test_requisitos_inventados_se_deniegan_con_el_numero_real(self):
        self.escribir_parte(self.parte_honesto(requisitos="6/6"))
        texto = self.denegado(self.validar())
        self.assertIn("3", texto)
        self.assertIn("requisito", texto.lower())

    def test_casillas_del_plan_inventadas_se_deniegan_con_el_conteo_real(self):
        self.escribir_parte(self.parte_honesto(plan="9/9"))
        texto = self.denegado(self.validar())
        self.assertIn("2/3", texto)

    # --- R5: citar sin volcar es afirmar ------------------------------------------------
    def test_ruta_de_evidencia_ausente_se_deniega(self):
        (self.runtime / "tests.txt").unlink()
        self.escribir_parte(self.parte_honesto())
        texto = self.denegado(self.validar())
        self.assertIn(".runtime/001-demo/tests.txt", texto)

    # --- R6: el hash, con el comando para recalcularlo ----------------------------------
    def test_hash_que_no_cuadra_se_deniega_y_trae_el_comando(self):
        malo = "0" + self.hashes["tests.txt"][1:]
        self.escribir_parte(self.parte_honesto(tests_sha256=malo))
        texto = self.denegado(self.validar())
        self.assertIn("shasum -a 256", texto)
        self.assertIn(".runtime/001-demo/tests.txt", texto)

    # --- R9: ningún fallo se queda sin salida -------------------------------------------
    def test_todo_fallo_nombra_el_comando_que_lo_resuelve(self):
        malos = [
            self.parte_honesto(tests_exit="1"),
            self.parte_honesto(veredicto="fallo"),
            self.parte_honesto(requisitos="6/6"),
            self.parte_honesto(plan="9/9"),
            self.parte_honesto(tests_sha256="0" + self.hashes["tests.txt"][1:]),
        ]
        for parte in malos:
            with self.subTest(parte=parte.splitlines()[1:3]):
                self.escribir_parte(parte)
                texto = self.denegado(self.validar())
                fallos = [l for l in texto.splitlines() if l.strip().startswith("FAIL ")]
                self.assertEqual(len(fallos), texto.count("salida:"))

    # --- 071/R2: lo aprendido se escribe, y se escribe en el momento --------------------
    def test_aprendizajes_con_el_marcador_de_plantilla_se_deniegan(self):
        self.escribir_parte(self.parte_honesto(), APRENDIZAJES_MARCADOR)
        texto = self.denegado(self.validar())
        self.assertIn("aprendizajes-constructor", texto)
        self.assertIn("aprendizajes-revisor", texto)

    def test_falta_el_bloque_del_revisor_y_se_deniega_nombrandolo(self):
        self.escribir_parte(self.parte_honesto(), seccion_aprendizajes(revisor=None))
        texto = self.denegado(self.validar())
        self.assertIn("aprendizajes-revisor", texto)

    def test_ninguno_explicito_cuenta_como_rellenado(self):
        self.escribir_parte(self.parte_honesto(), APRENDIZAJES_NINGUNO)
        salida = self.validar()
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)

    # --- 071/R3: la plantilla vieja no se re-exige (ausencia ≠ sección vacía) ------------
    def test_hallazgos_sin_seccion_de_aprendizajes_no_se_reexige(self):
        self.escribir_parte(self.parte_honesto(), None)
        salida = self.validar()
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)

    def test_sin_argumento_recorre_las_unidades_activas(self):
        self.escribir_parte(self.parte_honesto())
        salida = subprocess.run(
            [sys.executable, str(LINT_CIERRE), "--raiz", str(self.ws)],
            text=True, encoding="utf-8", errors="replace", capture_output=True)
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertIn("001-demo", salida.stdout)


class CierreBloqueaTest(unittest.TestCase):
    """Integración (R8): un validador que no corre en el cierre es decorativo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cierre-parte-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in ("control_plane.py", "lease.py", "lint_cierre.py", "peticion.py",
                       "repo_config.py", "unidad.py", "workspace_paths.py"):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.unidad = scripts / "unidad.py"
        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True)
        for nombre in ("especificacion.md", "directo.md", "bug.md", "hallazgos.md"):
            shutil.copy2(PLANTILLAS / nombre, plantillas / nombre)
        self.carpeta = self.ws / "docs/05-trabajo/001-demo"
        self.carpeta.mkdir(parents=True)
        (self.carpeta / "especificacion.md").write_text(SPEC, encoding="utf-8")
        # Vía legacy (unidad 027): la unidad no nace de una petición, y no es lo que se
        # prueba aquí. Lo que se prueba es que el parte de cierre llegue a las puertas.
        peticiones = self.ws / "docs/05-trabajo/peticiones"
        peticiones.mkdir(parents=True)
        (peticiones / "LEGACY.json").write_text(json.dumps({
            "formato": 1, "modo": "observacion",
            "unidades": ["001-demo"], "bugs": [], "ramas": []}), encoding="utf-8")
        self.runtime = self.ws / ".runtime/001-demo"
        self.runtime.mkdir(parents=True)
        self.hashes = {}
        for nombre in ("tests.txt", "lint.txt"):
            ruta = self.runtime / nombre
            ruta.write_text(f"salida real de {nombre}\n", encoding="utf-8")
            self.hashes[nombre] = hashlib.sha256(ruta.read_bytes()).hexdigest()

    def escribir_hallazgos(self, parte, aprendizajes=APRENDIZAJES_OK):
        plantilla = (PLANTILLAS / "hallazgos.md").read_text(encoding="utf-8")
        # 071: la sección llega con marcadores; cada caso pone lo suyo (o los deja).
        if aprendizajes:
            plantilla = re.sub(r"(?ms)^## Aprendizajes.*?(?=^## |\Z)", aprendizajes + "\n",
                               plantilla, count=1)
        plantilla = re.sub(r"^revisor:.*$", "revisor: agente-fresco", plantilla,
                           count=1, flags=re.M)
        plantilla = re.sub(r"^revisado:.*$", "revisado: 2026-08-25", plantilla,
                           count=1, flags=re.M)
        # La plantilla ya trae su propio bloque; se sustituye por el del caso.
        plantilla = re.sub(r"```parte-de-cierre.*?```\n", "", plantilla, flags=re.S)
        (self.carpeta / "hallazgos.md").write_text(plantilla + "\n" + parte, encoding="utf-8")

    def bloqueos(self, texto):
        """Solo las viñetas de CIERRE BLOQUEADO: el resto de la salida menciona la puerta
        también cuando la pasa, y eso no es un bloqueo."""
        return [l.strip() for l in texto.splitlines() if l.strip().startswith("·")]

    def cerrar(self):
        return subprocess.run(
            [sys.executable, str(self.unidad), "cerrar", "001-demo"],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace", capture_output=True)

    def test_una_cabecera_mentirosa_bloquea_el_cierre(self):
        honesto = {"tests_sha256": self.hashes["tests.txt"],
                   "build_sha256": self.hashes["lint.txt"]}
        self.escribir_hallazgos(cabecera(tests_exit="1", **honesto))
        salida = self.cerrar()
        texto = salida.stdout + salida.stderr
        self.assertEqual(salida.returncode, 1, texto)
        self.assertIn("CIERRE BLOQUEADO", texto)
        del_parte = [b for b in self.bloqueos(texto) if b.startswith("· parte de cierre")]
        self.assertTrue(del_parte, texto)
        self.assertIn("tests_exit", del_parte[0])
        self.assertIn("SALIDA:", del_parte[0])

    def test_aprendizajes_sin_rellenar_bloquean_el_cierre(self):
        honesto = {"tests_sha256": self.hashes["tests.txt"],
                   "build_sha256": self.hashes["lint.txt"]}
        self.escribir_hallazgos(cabecera(**honesto), aprendizajes=None)
        salida = self.cerrar()
        texto = salida.stdout + salida.stderr
        self.assertEqual(salida.returncode, 1, texto)
        self.assertIn("CIERRE BLOQUEADO", texto)
        del_parte = [b for b in self.bloqueos(texto) if b.startswith("· parte de cierre")]
        self.assertTrue(del_parte, texto)
        self.assertIn("aprendizajes", " ".join(del_parte))

    def test_con_la_cabecera_bien_el_parte_deja_de_ser_el_bloqueo(self):
        honesto = {"tests_sha256": self.hashes["tests.txt"],
                   "build_sha256": self.hashes["lint.txt"]}
        self.escribir_hallazgos(cabecera(**honesto))
        salida = self.cerrar()
        texto = salida.stdout + salida.stderr
        self.assertIn("parte de cierre: veredicto", texto)
        self.assertFalse([b for b in self.bloqueos(texto) if b.startswith("· parte de cierre")],
                         texto)


class PlantillaYRunbookTest(unittest.TestCase):
    """071/R1: el hueco existe donde lo va a leer quien construye y quien revisa."""

    def setUp(self):
        self.plantilla = (PLANTILLAS / "hallazgos.md").read_text(encoding="utf-8")

    def test_la_plantilla_trae_la_seccion_con_los_dos_bloques(self):
        self.assertRegex(self.plantilla, r"(?m)^##\s+Aprendizajes\b")
        self.assertIn("```aprendizajes-constructor", self.plantilla)
        self.assertIn("```aprendizajes-revisor", self.plantilla)

    def test_la_plantilla_dice_cuantas_frases_y_que_ninguno_vale(self):
        seccion = self.plantilla.split("## Aprendizajes", 1)[1]
        self.assertIn("1-5", seccion)
        self.assertIn("ninguno", seccion)

    def test_la_plantilla_sin_rellenar_no_pasa_su_propio_linter(self):
        """El hueco llega con marcadores: la plantilla tal cual NO es un parte válido."""
        sys.path.insert(0, str(SCRIPTS))
        import lint_cierre  # noqa: E402 - se importa tras fijar la ruta de los scripts
        self.assertTrue(lint_cierre.revisar_aprendizajes("001-demo", self.plantilla))

    def test_el_cierre_promueve_solo_desde_aprendizajes(self):
        cierre = (METODO / "runbooks/cierre.md").read_text(encoding="utf-8")
        self.assertIn("## Aprendizajes", cierre)


if __name__ == "__main__":
    unittest.main()
