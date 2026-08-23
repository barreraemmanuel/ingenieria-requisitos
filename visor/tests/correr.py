#!/usr/bin/env python3
"""Lanza la suite en cualquier plataforma. `run-fast` y `run-nightly` son /bin/sh:
en Windows no hay forma documentada de correr los tests, y el método dice que toda
verificación es local en la máquina del usuario.

    python visor/tests/correr.py            # rápida (visor/tests + visor_contratos/tests)
    python visor/tests/correr.py --nightly  # la adversarial
    python visor/tests/correr.py -v         # verboso

Activa además el modo UTF-8 de Python en los hijos. Es un cinturón, NO el arreglo: la
suite declara `encoding="utf-8"` en cada llamada y pasa en verde sin este lanzador. Está
para que un script de proyecto lanzado desde un test tampoco herede cp1252 por descuido.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RAPIDAS = ("visor/tests", "visor_contratos/tests")
NIGHTLY = ("visor/tests/nightly",)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nightly", action="store_true", help="la suite adversarial")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    entorno = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    codigo = 0
    for carpeta in (NIGHTLY if args.nightly else RAPIDAS):
        print(f"== {carpeta} ==", flush=True)
        orden = [sys.executable, "-X", "utf8", "-m", "unittest", "discover",
                 "-s", carpeta, "-p", "test_*.py"]
        if args.verbose:
            orden.append("-v")
        codigo |= subprocess.run(orden, cwd=str(RAIZ), env=entorno).returncode
    return codigo


if __name__ == "__main__":
    sys.exit(main())
