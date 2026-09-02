#!/usr/bin/env python3
"""La tabla de transiciones de la reforma: qué está rojo HOY, y si sigue estándolo.

Estos tests están escritos contra el método que TODAVÍA NO EXISTE (la entrega del ayudante
de la 147, los rojos por sujeto de la 148). Casi todos están en rojo a propósito: son la
línea base que esas unidades tienen que poner en verde. Si se dejaran en la suite rápida la
romperían todos los días y en dos semanas alguien los borraría, que es exactamente cómo se
pierde una prueba base.

Por eso viven en `visor/tests/reforma/`, que NO tiene `__init__.py` y por tanto `unittest
discover` no recorre —el mecanismo, no un olvido— y se corren solo con:

    python3 visor/tests/correr.py --reforma

El veredicto NO es «verde/rojo»: es «coincide o no coincide con `esperado.json`». Un test
que estaba rojo y ahora pasa es una noticia tan importante como uno que estaba verde y ha
dejado de pasar: lo primero significa que la 147 llegó y el manifiesto está sin actualizar,
y lo segundo, que alguien rompió lo poco que ya funcionaba. Las dos paran con exit 1.
"""
import argparse
import json
import os
import sys
import unittest
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
MANIFIESTO = AQUI / "esperado.json"


def identificador(test):
    """`ClaseDelTest.test_lo_que_sea` — sin el módulo, que se mueve al renombrar ficheros."""
    return f"{test.__class__.__name__}.{test._testMethodName}"


def aplanar(suite):
    for hijo in suite:
        if isinstance(hijo, unittest.TestSuite):
            yield from aplanar(hijo)
        else:
            yield hijo


class Colector(unittest.TextTestResult):
    """Recoge el color de cada test en vez de imprimir un mar de puntos."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.colores = {}
        self.motivos = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.colores[identificador(test)] = "verde"

    def _rojo(self, test, err):
        self.colores[identificador(test)] = "rojo"
        primera = str(err[1]).strip().splitlines()
        self.motivos[identificador(test)] = primera[0][:110] if primera else ""

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._rojo(test, err)

    def addError(self, test, err):
        super().addError(test, err)
        self._rojo(test, err)

    def addSkip(self, test, razon):
        super().addSkip(test, razon)
        self.colores[identificador(test)] = "saltado"


def cargar_tests():
    """Los tests de esta carpeta, por NOMBRE de módulo y no con `discover`.

    `discover` exige que la carpeta de arranque sea importable (Python 3.9 lo dice con todas
    las letras), y esta carpeta no tiene `__init__.py` a propósito: es justo lo que la
    mantiene fuera de la suite rápida. Así que se cargan como `visor.tests.reforma.test_x`,
    que sí funciona por paquete de espacio de nombres, y el mecanismo se conserva.
    """
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    cargador = unittest.TestLoader()
    tests = []
    for ruta in sorted(AQUI.glob("test_*.py")):
        modulo = f"visor.tests.reforma.{ruta.stem}"
        tests += list(aplanar(cargador.loadTestsFromName(modulo)))
    return tests


def correr(verbose=False):
    """Los 32 casos, con la pantalla del corredor tirada: aquí manda la tabla, no los puntos."""
    suite = unittest.TestSuite(cargar_tests())
    with open(os.devnull, "w") as mudo:
        corredor = unittest.TextTestRunner(stream=mudo, verbosity=2 if verbose else 0,
                                           resultclass=Colector)
        return corredor.run(suite)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--congelar", action="store_true",
                   help="reescribe esperado.json con los colores de hoy (147/148 lo hacen "
                        "al cerrar, cuando ponen en verde lo que estaba rojo)")
    args = p.parse_args(argv)

    resultado = correr(args.verbose)
    colores = resultado.colores
    esperado = {}
    if MANIFIESTO.is_file():
        esperado = json.loads(MANIFIESTO.read_text(encoding="utf-8")).get("tests", {})

    if args.congelar:
        MANIFIESTO.write_text(json.dumps({
            "_porque": ("El color que cada transición de la junta ayudante→revisor→prefusión→"
                        "cierre tiene HOY. Los `rojo` son la línea base de la reforma: la 147 "
                        "y la 148 los ponen en verde y actualizan este fichero AL CERRAR. Un "
                        "rojo que pasa a verde sin tocar esto es un FAIL, no una alegría: "
                        "significa que nadie se enteró de que el método cambió."),
            "tests": dict(sorted(colores.items())),
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"OK esperado.json congelado: {len(colores)} transiciones")
        return 0

    rojos = sorted(k for k, v in colores.items() if v == "rojo")
    verdes = sorted(k for k, v in colores.items() if v == "verde")
    desvios = []
    for nombre in sorted(colores):
        previsto = esperado.get(nombre)
        if previsto is None:
            desvios.append((nombre, "sin declarar en el manifiesto", colores[nombre]))
        elif previsto != colores[nombre]:
            desvios.append((nombre, previsto, colores[nombre]))
    huerfanos = sorted(set(esperado) - set(colores))

    print("Transiciones de la junta del ayudante · rojo = lo que la 147/148 debe arreglar\n")
    for nombre in sorted(colores):
        color = colores[nombre]
        marca = {"verde": "verde", "rojo": "rojo ", "saltado": "salt."}[color]
        previsto = esperado.get(nombre, "—")
        aviso = "" if previsto == color else f"   <-- se esperaba {previsto}"
        print(f"  {marca}  {nombre}{aviso}")
        if color == "rojo" and args.verbose:
            print(f"          {resultado.motivos.get(nombre, '')}")

    print(f"\nVEREDICTO: {len(rojos)} rojos esperados / {len(verdes)} verdes")
    if huerfanos:
        print(f"  {len(huerfanos)} en el manifiesto que ya no existen: {', '.join(huerfanos)}")
    if desvios or huerfanos:
        for nombre, previsto, real in desvios:
            print(f"  DESVÍO  {nombre}: se esperaba {previsto}, salió {real}")
        print("  SALIDA: si es que la reforma avanzó y estos ya están bien, adopta el nuevo "
              "color con  python3 visor/tests/reforma/correr_reforma.py --congelar")
        return 1
    print("  la tabla coincide con el manifiesto: la línea base sigue siendo la que dice ser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
