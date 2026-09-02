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
from datetime import date
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
MANIFIESTO = AQUI / "esperado.json"
YO = "visor/tests/reforma/correr_reforma.py"


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


PORQUE = ("El color que cada transición de la junta ayudante→revisor→prefusión→cierre tiene "
          "HOY. Los `rojo` son la línea base de la reforma: la 147 y la 148 los ponen en "
          "verde y actualizan este fichero AL CERRAR. Un rojo que pasa a verde sin tocar "
          "esto es un FAIL, no una alegría: significa que nadie se enteró de que el método "
          "cambió. Y al revés todavía menos: el número de VERDES solo puede subir. "
          "`--congelar` compara contra el manifiesto anterior y RECHAZA cualquier bajada de "
          "verdes; para adoptarla hace falta `--congelar --motivo \"<texto>\"`, que queda en "
          "`historial`. Sin esa comparación, congelar sería la forma más rápida de hacer "
          "desaparecer una regresión: se vuelve a medir y se llama línea base a lo roto.")


def congelar(colores, previo, esperado, motivo):
    """Reescribe el manifiesto, pero los verdes solo pueden subir.

    Un `--congelar` que adopta lo que hay sin mirar lo que había convierte el manifiesto en
    un espejo: siempre coincide, nunca avisa. La cuenta que se protege es la de VERDES —lo
    que ya funciona—, porque los rojos bajan solos según la reforma avanza y eso es la buena
    noticia que este fichero existe para registrar.
    """
    verdes_antes = sum(1 for c in esperado.values() if c == "verde")
    verdes_ahora = sum(1 for c in colores.values() if c == "verde")
    perdidos = sorted(n for n, c in esperado.items()
                      if c == "verde" and colores.get(n) not in (None, "verde"))

    if esperado and verdes_ahora < verdes_antes and not motivo:
        print(f"FAIL [REF-001] el manifiesto perdería verdes ({verdes_antes} → "
              f"{verdes_ahora}) y eso no se congela solo: {', '.join(perdidos) or '—'}.\n"
              f"    Congelar sin mirar el manifiesto anterior es la forma más rápida de "
              f"hacer desaparecer una regresión — se vuelve a medir y se llama línea base a "
              f"lo que se acaba de romper.\n"
              f"    SALIDA: arregla lo que se puso rojo y vuelve a medir con  python3 "
              f"visor/tests/correr.py --reforma  ; si de verdad hay que adoptarlo, fírmalo "
              f"con  python3 {YO} --congelar --motivo \"por qué se pierde\"")
        return 1

    historial = list(previo.get("historial") or [])
    if esperado and verdes_ahora < verdes_antes:
        historial.append({"fecha": date.today().isoformat(), "verdes_de": verdes_antes,
                          "verdes_a": verdes_ahora, "tests": perdidos, "motivo": motivo})

    MANIFIESTO.write_text(json.dumps({
        "_porque": PORQUE,
        "tests": dict(sorted(colores.items())),
        "historial": historial,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"OK esperado.json congelado: {len(colores)} transiciones "
          f"({verdes_ahora} verdes)")
    if esperado and verdes_ahora < verdes_antes:
        print(f"   AVISO se PERDIERON verdes {verdes_antes}→{verdes_ahora}, adoptado con "
              f"motivo: {motivo}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--congelar", action="store_true",
                   help="reescribe esperado.json con los colores de hoy (147/148 lo hacen "
                        "al cerrar, cuando ponen en verde lo que estaba rojo). Si el número "
                        "de verdes BAJA, se rechaza sin --motivo")
    p.add_argument("--motivo", default=None,
                   help="firma por la que se adopta una BAJADA de verdes; queda escrita en "
                        "`historial` y se imprime mientras exista")
    args = p.parse_args(argv)

    resultado = correr(args.verbose)
    colores = resultado.colores
    previo = {}
    if MANIFIESTO.is_file():
        previo = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    esperado = previo.get("tests", {})

    if args.congelar:
        return congelar(colores, previo, esperado, args.motivo)

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

    # Los dos desvíos NO son la misma noticia y no se cuentan juntos:
    #   · verde → rojo es una REGRESIÓN: algo que ya funcionaba se rompió. Falla siempre.
    #   · rojo  → verde es un AVISO: la reforma avanzó y nadie actualizó el manifiesto. Para
    #     igual —si no, el manifiesto se queda mintiendo—, pero se dice con otras palabras,
    #     porque lo que hay que hacer es distinto: uno se arregla, el otro se adopta.
    regresiones = [(n, p_, r) for n, p_, r in desvios if p_ == "verde"]
    avances = [(n, p_, r) for n, p_, r in desvios if p_ == "rojo"]
    nuevos = [(n, p_, r) for n, p_, r in desvios if p_ not in ("verde", "rojo")]

    print(f"\nVEREDICTO: {len(rojos)} rojos esperados / {len(verdes)} verdes")
    if huerfanos:
        print(f"  {len(huerfanos)} en el manifiesto que ya no existen: {', '.join(huerfanos)}")
    if desvios or huerfanos:
        for nombre, previsto, real in regresiones:
            print(f"  REGRESIÓN  {nombre}: estaba en verde y ahora sale {real}")
        for nombre, previsto, real in avances:
            print(f"  AVISO      {nombre}: era un rojo esperado y ahora pasa")
        for nombre, previsto, real in nuevos:
            print(f"  DESVÍO     {nombre}: {previsto}, salió {real}")
        if regresiones:
            print(f"  SALIDA: {len(regresiones)} transición(es) que YA funcionaban se han "
                  f"roto: arréglalas y vuelve a medir con  python3 visor/tests/correr.py "
                  f"--reforma  . Adoptar esto con --congelar borraría la regresión, y por "
                  f"eso el trinquete lo rechaza sin  --motivo")
        else:
            print("  SALIDA: si es que la reforma avanzó y estos ya están bien, adopta el "
                  "nuevo color con  python3 visor/tests/reforma/correr_reforma.py --congelar")
        return 1
    print("  la tabla coincide con el manifiesto: la línea base sigue siendo la que dice ser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
