"""Bug 114: nada de lo que la herramienta distribuye acaba en línea en blanco.

Los ficheros que viajan a cada workspace (plantilla/, ARCHIVOS_REQUISITOS y
ARCHIVOS_WEB, la misma lista que copia `visor/actualizar.py`) se commitean en el
repo del alumno; si su pre-commit corre `git diff --cached --check`, un fichero
acabado en `\\n\\n` («new blank line at EOF») o con espacios al final de línea
rechaza el commit y `herramienta.py` revierte la actualización entera. Pasó dos
veces en campo (1.8.0 y 1.9.0, docs/bugs/114-runbook-sin-linea-en-blanco-final.md).
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ / "visor") not in sys.path:
    sys.path.insert(0, str(RAIZ / "visor"))
import bootstrap  # noqa: E402


def ficheros_distribuidos():
    rutas = set()
    for ruta in (RAIZ / "plantilla").rglob("*"):
        if ruta.is_file() and "__pycache__" not in ruta.parts:
            rutas.add(ruta)
    for nombre in bootstrap.ARCHIVOS_REQUISITOS:
        if nombre == "requirements-dev.txt" or nombre.startswith("RUNBOOK"):
            rutas.add(RAIZ / nombre)
        else:
            rutas.add(RAIZ / "visor" / nombre)
    for nombre in bootstrap.ARCHIVOS_WEB:
        rutas.add(bootstrap.origen_web(nombre))
    return sorted(rutas)


class DistribucionSinBlancoFinalTest(unittest.TestCase):
    def test_hay_ficheros_que_revisar(self):
        self.assertGreater(len(ficheros_distribuidos()), 100)

    def test_ningun_fichero_distribuido_acaba_en_linea_en_blanco(self):
        culpables = []
        for ruta in ficheros_distribuidos():
            try:
                texto = ruta.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if texto.endswith("\n\n"):
                culpables.append(ruta.relative_to(RAIZ).as_posix())
        self.assertEqual(
            culpables, [],
            "acaban en línea en blanco (git diff --check: «new blank line at EOF»); "
            "un pre-commit de espacios rechaza el commit de la actualización y "
            "herramienta.py la revierte (bug 114)",
        )

    def test_ningun_fichero_distribuido_lleva_espacios_al_final_de_linea(self):
        culpables = []
        for ruta in ficheros_distribuidos():
            try:
                lineas = ruta.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            malas = [n for n, linea in enumerate(lineas, 1) if linea != linea.rstrip(" \t")]
            if malas:
                culpables.append(f"{ruta.relative_to(RAIZ).as_posix()}:{malas[:3]}")
        self.assertEqual(culpables, [], "espacios al final de línea (git diff --check los rechaza)")


if __name__ == "__main__":
    unittest.main()
