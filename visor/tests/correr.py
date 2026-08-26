#!/usr/bin/env python3
"""Lanza la suite en cualquier plataforma y termina con un VEREDICTO explícito.

    python visor/tests/correr.py            # rápida (web, visor, visor_contratos, visor_presentaciones, visor_tablero)
    python visor/tests/correr.py --nightly  # la adversarial
    python visor/tests/correr.py -v         # verboso

La última línea es siempre `VEREDICTO: verde|rojo (n suites, m rojas)` y el código de
salida es 0 (verde) o 1 (rojo). Nada más. Ese código es la puerta que se lee antes de
fusionar, así que no puede ser el número que devolvió un hijo: hasta el bug 093 se
acumulaba con un OR de bits (`codigo |= …`), y `128 | 16` da 144 — un código que no
devolvió nadie, con toda la pantalla en verde. Ahora las suites rojas se cuentan y cada
una dice por qué lo es (código de salida o nombre de la señal que la mató).

Por lo mismo, el lanzador ignora EXPLÍCITAMENTE las señales que no son de parada (SIGURG,
SIGWINCH): en una máquina cargada llegan solas y no significan nada. SIGCHLD no se toca:
ignorarla auto-recolecta a los hijos y deja a `wait()` sin nadie a quien esperar. Si llega
una señal de parada de verdad (SIGINT, SIGTERM, SIGHUP, SIGQUIT) se corta la suite en
marcha y se dice en la última línea, con el nombre de la señal, saliendo distinto de 0.

Activa además el modo UTF-8 de Python en los hijos. Es un cinturón, NO el arreglo: la
suite declara `encoding="utf-8"` en cada llamada y pasa en verde sin este lanzador. Está
para que un script de proyecto lanzado desde un test tampoco herede cp1252 por descuido.
"""
import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
# La suite de presentaciones (051/056) se quedó fuera del lanzador: sus tests
# existían pero no corrían con los demás, y por ahí se coló el bug 064. La del
# tablero (058) estaba en el mismo sitio: existía y no corría (bug 067).
# La suite de la web única (081) va la primera: es el criterio portante.
RAPIDAS = ("web/tests", "visor/tests", "visor_contratos/tests",
           "visor_presentaciones/tests", "visor_tablero/tests")
NIGHTLY = ("visor/tests/nightly",)

# Ruido, no órdenes: llegan solas en máquinas cargadas o al redimensionar la terminal.
IGNORABLES = ("SIGURG", "SIGWINCH")
# Paradas de verdad: se obedecen, pero dejando dicho quién cortó.
DE_PARADA = ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT")

_parada = {"senal": None}      # nombre de la señal de parada que llegó, si llegó
_en_marcha = {"hijo": None}    # el subprocess vivo, para cortarlo al recibirla


def nombre_de_senal(numero):
    """'SIGURG' a partir de 16. Devuelve el número tal cual si no lo conoce."""
    try:
        return signal.Signals(numero).name
    except (ValueError, AttributeError):
        return f"señal {numero}"


def _anotar_parada(numero, _marco):
    _parada["senal"] = nombre_de_senal(numero)
    hijo = _en_marcha["hijo"]
    if hijo is not None and hijo.poll() is None:
        try:
            hijo.terminate()
        except OSError:
            pass


def blindar_senales():
    """Ignora lo que no para y anota lo que sí. Lo que no exista en la plataforma
    (Windows no tiene SIGURG ni SIGHUP) se salta sin ruido."""
    for nombre in IGNORABLES:
        numero = getattr(signal, nombre, None)
        if numero is None:
            continue
        try:
            signal.signal(numero, signal.SIG_IGN)
        except (ValueError, OSError, RuntimeError):
            pass       # hilo secundario o señal no manejable: no es motivo para no correr
    for nombre in DE_PARADA:
        numero = getattr(signal, nombre, None)
        if numero is None:
            continue
        try:
            signal.signal(numero, _anotar_parada)
        except (ValueError, OSError, RuntimeError):
            pass


def motivo(codigo):
    """Por qué una suite es roja, en cristiano."""
    if codigo < 0:                       # POSIX: el hijo murió por una señal
        return f"matada por {nombre_de_senal(-codigo)}"
    if 128 < codigo < 193:               # 128+N: alguien de la cadena murió por una señal
        return f"salió con {codigo} (= 128 + {codigo - 128}, {nombre_de_senal(codigo - 128)})"
    return f"salió con {codigo}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nightly", action="store_true", help="la suite adversarial")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    blindar_senales()
    entorno = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    carpetas = NIGHTLY if args.nightly else RAPIDAS
    resultados = []                      # (carpeta, código) en el orden en que se corrieron

    for carpeta in carpetas:
        if _parada["senal"]:
            break
        print(f"== {carpeta} ==", flush=True)
        orden = [sys.executable, "-X", "utf8", "-m", "unittest", "discover",
                 "-s", carpeta, "-p", "test_*.py"]
        if args.verbose:
            orden.append("-v")
        hijo = subprocess.Popen(orden, cwd=str(RAIZ), env=entorno)
        _en_marcha["hijo"] = hijo
        try:
            codigo = hijo.wait()
        finally:
            _en_marcha["hijo"] = None
        resultados.append((carpeta, codigo))

    rojas = [(carpeta, codigo) for carpeta, codigo in resultados if codigo != 0]
    print("", flush=True)
    for carpeta, codigo in resultados:
        print(f"  {'verde' if codigo == 0 else 'rojo '}  {carpeta}"
              + ("" if codigo == 0 else f" ({motivo(codigo)})"), flush=True)
    for carpeta in carpetas[len(resultados):]:
        print(f"  ——     {carpeta} (sin correr)", flush=True)

    total = len(carpetas)
    cuenta = f"{total} suite{'s' if total != 1 else ''}, {len(rojas)} roja{'s' if len(rojas) != 1 else ''}"
    if _parada["senal"]:
        print(f"VEREDICTO: rojo ({cuenta}) — interrumpido por {_parada['senal']}", flush=True)
        return 1
    print(f"VEREDICTO: {'rojo' if rojas else 'verde'} ({cuenta})", flush=True)
    return 1 if rojas else 0


if __name__ == "__main__":
    sys.exit(main())
