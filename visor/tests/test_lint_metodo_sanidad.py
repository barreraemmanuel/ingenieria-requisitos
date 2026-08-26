#!/usr/bin/env python3
"""Unidad 079 — el arranque avisa cuando la sanidad del workspace lleva demasiado sin pasarse.

R-2405 del plano `sanear-workspace`: `sanidad.py atraso` sabía desde la 059 cuántos cierres y
cuántos días llevaba el workspace sin medirse, pero nadie lo preguntaba. Aquí se comprueba que
`lint_metodo.py` —el que corre en CADA arranque de sesión y en cada cierre— lo pregunta y
publica la respuesta como WARN (nunca FAIL: la sanidad guía, no bloquea, ADR-026), sin
duplicar la lógica de conteo (R3: lo que dice el WARN es lo que dijo `atraso`).
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
SCRIPTS = RAIZ_REPO / "plantilla/docs/00-metodo/scripts"
LINT = SCRIPTS / "lint_metodo.py"
SANIDAD = SCRIPTS / "sanidad.py"
COMANDO = "python3 docs/00-metodo/scripts/sanidad.py medir --anotar"


class AvisoDeSanidadAtrasadaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-sanidad-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / "docs/00-metodo/scripts").mkdir(parents=True)
        (self.raiz / "docs/05-trabajo").mkdir(parents=True)

    # --- utilidades -----------------------------------------------------

    def sanidad_de_mentira(self, salida="", codigo=0, error=""):
        """Un `sanidad.py` que solo contesta a `atraso`: aquí se prueba el lint, no la sanidad."""
        guion = (
            "import sys\n"
            f"sys.stderr.write({error!r})\n"
            f"sys.stdout.write({salida!r})\n"
            f"sys.exit({codigo})\n"
        )
        (self.raiz / "docs/00-metodo/scripts/sanidad.py").write_text(guion, encoding="utf-8")

    def sanidad_real(self):
        """La de verdad, con sus vecinos: la junta lint↔sanidad se prueba entera (R3)."""
        destino = self.raiz / "docs/00-metodo/scripts"
        shutil.rmtree(destino)
        shutil.copytree(SCRIPTS, destino)

    def libro(self, fecha):
        (self.raiz / "docs/05-trabajo/SANIDAD.md").write_text(
            "# Libro de sanidad\n\n| fecha | deuda |\n|---|---|\n"
            f"| {fecha} | 0 |\n", encoding="utf-8")

    def lint(self):
        proceso = subprocess.run(
            [sys.executable, str(LINT), "--raiz", str(self.raiz)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proceso.stdout + proceso.stderr

    def lineas_de_sanidad(self, salida):
        return [l.strip() for l in salida.splitlines() if "sanidad" in l.lower()
                and l.strip().startswith(("OK", "WARN", "FAIL"))]

    # --- R1: atrasada → WARN con cierres, días y comando ------------------

    def test_atrasada_publica_un_warn_con_cierres_dias_y_comando(self):
        self.sanidad_de_mentira(
            f"WARN sanidad atrasada: 7 cierres / 40 días desde 2026-07-01 · SALIDA: {COMANDO}\n")
        salida = self.lint()
        avisos = [l for l in self.lineas_de_sanidad(salida) if l.startswith("WARN")]
        self.assertTrue(avisos, f"el lint no avisó del atraso de sanidad:\n{salida}")
        aviso = avisos[0]
        self.assertIn("7 cierres", aviso)
        self.assertIn("40 días", aviso)
        self.assertIn(COMANDO, aviso)
        self.assertNotIn("FAIL", aviso, "la sanidad guía, no bloquea (ADR-026)")

    def test_atrasada_no_convierte_el_lint_en_rojo(self):
        self.sanidad_de_mentira(
            f"WARN sanidad atrasada: 7 cierres / 40 días desde 2026-07-01 · SALIDA: {COMANDO}\n")
        proceso = subprocess.run(
            [sys.executable, str(LINT), "--raiz", str(self.raiz)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertNotIn("sanidad atrasada",
                         "\n".join(l for l in proceso.stdout.splitlines()
                                   if l.strip().startswith("FAIL")))

    # --- al día → silencio (un OK, ningún WARN) ---------------------------

    def test_al_dia_no_avisa_de_nada(self):
        self.sanidad_de_mentira("OK sanidad al día (1 cierres, 3 días)\n")
        avisos = [l for l in self.lineas_de_sanidad(self.lint()) if l.startswith("WARN")]
        self.assertEqual([], avisos, "estando al día el lint no debe avisar de sanidad")

    # --- R2: sin pasada previa y fallos ----------------------------------

    def test_sin_ninguna_pasada_previa_avisa_de_que_nunca_se_ha_pasado(self):
        self.sanidad_de_mentira(f"WARN nunca se ha pasado sanidad · SALIDA: {COMANDO}\n")
        avisos = [l for l in self.lineas_de_sanidad(self.lint()) if l.startswith("WARN")]
        self.assertEqual(1, len(avisos), f"un solo WARN, no dos: {avisos}")
        self.assertIn("nunca se ha pasado", avisos[0])
        self.assertIn(COMANDO, avisos[0])

    def test_si_sanidad_falla_hay_un_solo_warn_y_el_lint_sigue(self):
        self.sanidad_de_mentira(salida="", codigo=2, error="Traceback: boom\n")
        salida = self.lint()
        avisos = [l for l in self.lineas_de_sanidad(salida) if l.startswith("WARN")]
        self.assertEqual(1, len(avisos), f"un solo WARN, no dos: {avisos}")
        self.assertIn("boom", avisos[0])
        self.assertIn(COMANDO, avisos[0])
        self.assertIn("FAIL ·", salida, "el lint sigue hasta el recuento final")

    def test_si_sanidad_no_existe_avisa_y_no_revienta(self):
        salida = self.lint()  # setUp deja la carpeta de scripts vacía
        avisos = [l for l in self.lineas_de_sanidad(salida) if l.startswith("WARN")]
        self.assertEqual(1, len(avisos), f"un solo WARN, no dos: {avisos}")
        self.assertIn("sanidad.py", avisos[0])
        self.assertIn("FAIL ·", salida, "el lint sigue hasta el recuento final")

    # --- R3: la cuenta la lleva sanidad.py, no el lint --------------------

    def test_el_lint_no_cuenta_por_su_cuenta_sino_que_repite_lo_que_dijo_atraso(self):
        self.sanidad_de_mentira(
            f"WARN sanidad atrasada: 99 cierres / 123 días desde 2020-01-01 · SALIDA: {COMANDO}\n")
        avisos = [l for l in self.lineas_de_sanidad(self.lint()) if l.startswith("WARN")]
        self.assertTrue(avisos and "99 cierres" in avisos[0] and "123 días" in avisos[0],
                        f"el WARN debe repetir la cuenta de `atraso`, no inventar la suya: {avisos}")

    def test_con_la_sanidad_de_verdad_un_libro_viejo_produce_el_aviso(self):
        # La junta completa: `atraso` real leyendo un libro real y el lint publicándolo.
        self.sanidad_real()
        self.libro("2020-01-01")
        avisos = [l for l in self.lineas_de_sanidad(self.lint()) if l.startswith("WARN")]
        self.assertTrue(any("atrasada" in a and COMANDO in a for a in avisos),
                        f"con una pasada de 2020 la sanidad está atrasada: {avisos}")

    def test_sanidad_py_sigue_nombrando_la_salida_que_el_lint_promete(self):
        # Si `atraso` deja de imprimir el comando, el WARN del lint se queda sin salida.
        fuente = SANIDAD.read_text(encoding="utf-8")
        self.assertIn(f'SALIDA_MEDIR = "{COMANDO}"', fuente)


if __name__ == "__main__":
    unittest.main()
