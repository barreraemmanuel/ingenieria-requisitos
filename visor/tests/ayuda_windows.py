"""Lo que la suite necesita para correr en Windows además de en POSIX.

Se importa como módulo hermano: los tests se descubren con `discover -s visor/tests`,
que pone esa carpeta en sys.path. Ya hay precedente en la suite —
`test_peticion_unidad.py` importa `test_version_metodo` del mismo modo.
"""
import os
import shutil
import stat
import sys


def enlazar_o_saltar(test, enlace, destino, *, directorio=False):
    """Crea un symlink; si esta máquina no deja, salta el test diciendo por qué.

    Crear symlinks en Windows exige Modo Desarrollador o privilegio de
    administrador: sin él, `symlink_to` muere con WinError 1314 y un test de una
    guarda anti-symlink ni siquiera puede montar su escenario. Se salta, con el
    motivo escrito — nunca en silencio.

    OJO: saltar aquí NO quiere decir que la guarda esté cubierta en Windows. Un
    *junction* (`mklink /J`) redirige igual, no exige privilegio, y las guardas
    que solo miran `is_symlink()` no lo ven. Eso es la unidad 043.
    """
    try:
        enlace.symlink_to(destino, target_is_directory=directorio)
    except (OSError, NotImplementedError):
        test.skipTest("este sistema no permite crear symlinks (Windows sin privilegio)")
    return enlace


def borrar_arbol(ruta):
    """rmtree que borra también lo que git deja en solo-lectura (Windows).

    Los objetos de `.git/` son 0o444 y en Windows el atributo de solo-lectura
    impide borrarlos: sin esto la limpieza falla (WinError 5) y contamina al
    siguiente test, que se encuentra la carpeta ya creada (WinError 183).
    """
    def reintentar(func, objetivo, _exc):
        os.chmod(objetivo, stat.S_IWRITE)
        func(objetivo)

    if sys.version_info >= (3, 12):
        shutil.rmtree(ruta, onexc=reintentar)
    else:
        shutil.rmtree(ruta, onerror=reintentar)
