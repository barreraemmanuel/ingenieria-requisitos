"""`version_remota()` no deja basura en %TEMP% (bug 042, D2).

`herramienta.py comprobar` corre en CADA arranque de CADA sesión y, para leer un único
fichero (el VERSION del método), clona superficialmente en un temporal. El clon se
borraba con `shutil.rmtree(temporal, ignore_errors=True)`: los objetos que git deja son
de solo-lectura, el borrado fallaba y `ignore_errors=True` se tragaba el fallo. En
Windows eso dejaba un `%TEMP%\\ir-version-*` de ~400 KB por arranque, para siempre.

Las dos plataformas ponen la misma barrera por sitios distintos, y este fichero prueba
las dos: en Windows manda el atributo de solo-lectura del FICHERO (0o444); en POSIX el
permiso que decide si una entrada se puede borrar es el del DIRECTORIO que la contiene.
El caso del directorio de solo-lectura es el que corre en rojo fuera de Windows.
"""
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import herramienta  # noqa: E402


def clon_de_git_falso(raiz):
    """Un árbol con las dos formas de solo-lectura que trae un clon de git."""
    objetos = raiz / ".git" / "objects" / "pack"
    objetos.mkdir(parents=True)
    paquete = objetos / "pack-675a2f06.pack"
    paquete.write_text("no importa el contenido", encoding="utf-8")
    paquete.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)          # 0o444, el de git
    objetos.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP)  # 0o550
    return raiz


def liberar(raiz):
    """Cleanup de emergencia: si el test falla, el temporal no se queda tampoco aquí."""
    for actual, carpetas, _ficheros in os.walk(str(raiz)):
        for nombre in [actual] + [os.path.join(actual, c) for c in carpetas]:
            try:
                os.chmod(nombre, 0o755)
            except OSError:
                pass
    shutil.rmtree(raiz, ignore_errors=True)


class BorrarArbolTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="borrar-arbol-")).resolve()
        self.addCleanup(liberar, self.base)

    def test_rmtree_a_secas_NO_puede_con_esto(self):
        """La línea de partida: sin el arreglo la carpeta sobrevive, y en silencio.
        Si algún día esto pasara a dar False, el resto del fichero sería vacuo."""
        arbol = clon_de_git_falso(self.base / "clon")
        shutil.rmtree(arbol, ignore_errors=True)
        self.assertTrue(arbol.exists(),
                        "rmtree(ignore_errors=True) borró el árbol: el escenario ya no reproduce")

    def test_borra_el_fichero_de_solo_lectura_y_la_carpeta_entera(self):
        arbol = clon_de_git_falso(self.base / "clon")

        herramienta.borrar_arbol(arbol)

        self.assertFalse(arbol.exists())

    def test_no_lanza_ni_bloquea_el_arranque_si_aun_asi_queda_algo(self):
        """Regla de la unidad: el borrado del temporal JAMÁS bloquea un arranque."""
        arbol = clon_de_git_falso(self.base / "clon")
        with mock.patch.object(herramienta.os, "chmod", side_effect=PermissionError(13, "no")):
            herramienta.borrar_arbol(arbol)      # no debe lanzar


class VersionRemotaNoDejaTemporalTest(unittest.TestCase):
    """El defecto reportado, por su puerta: tras `version_remota` no queda `ir-version-*`."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="temp-de-mentira-")).resolve()
        self.addCleanup(liberar, self.temp)
        # tempfile.gettempdir() devuelve `tempfile.tempdir` si está puesto: así el
        # `mkdtemp(prefix="ir-version-")` de producción cae aquí y se puede auditar.
        previo = tempfile.tempdir
        tempfile.tempdir = str(self.temp)
        self.addCleanup(setattr, tempfile, "tempdir", previo)

    def restos(self):
        return sorted(p.name for p in self.temp.iterdir() if p.name.startswith("ir-version-"))

    def git_de_mentira(self, *, falla_en=None):
        """Sustituye a `herramienta.git`: monta un clon con la solo-lectura de git."""
        def falso(*args, cwd=None, timeout=None):
            if falla_en is not None and args[0] == falla_en:
                return None
            if args[0] == "clone":
                destino = Path(args[-1])
                metodo = destino / "plantilla/docs/00-metodo"
                metodo.mkdir(parents=True)
                (metodo / "VERSION").write_text("1.7.3\n", encoding="utf-8")
                clon_de_git_falso(destino)
            return mock.Mock(returncode=0, stdout="", stderr="")
        return falso

    def test_el_camino_bueno_devuelve_la_version_y_no_deja_nada(self):
        with mock.patch.object(herramienta, "git", self.git_de_mentira()):
            self.assertEqual(herramienta.version_remota("https://example.invalid/x.git"), "1.7.3")

        self.assertEqual(self.restos(), [])

    def test_tampoco_deja_nada_cuando_el_clon_falla_a_media(self):
        """Sin red, sin credenciales o repo privado el canal calla — pero limpia igual."""
        with mock.patch.object(herramienta, "git", self.git_de_mentira(falla_en="checkout")):
            self.assertIsNone(herramienta.version_remota("https://example.invalid/x.git"))

        self.assertEqual(self.restos(), [])


if __name__ == "__main__":
    unittest.main()
