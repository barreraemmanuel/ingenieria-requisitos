"""Redacción en el embudo de salida de los scripts del método (P0.4 del forense).

peticion.py y ejecucion.py instalan al importarse un envoltorio de stdout/stderr
que pasa todo lo impreso por control_plane.redact_secrets: da igual de dónde
venga el texto (un motivo tecleado por el usuario, un env volcado en un error),
una credencial no puede salir por consola. Se prueba en subproceso real, que es
como se ejecutan de verdad.
"""

import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "plantilla/docs/00-metodo/scripts"
CHIVATO = (
    "antes postgres://usuario:supersecreta@db.interna:5432/prod "
    "y despues password=hunter2 fin"
)


def imprimir_tras_importar(modulo):
    codigo = (
        f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); "
        f"import {modulo}; print({CHIVATO!r}); "
        f"print({CHIVATO!r}, file=sys.stderr)"
    )
    return subprocess.run(
        [sys.executable, "-c", codigo], text=True,
        encoding="utf-8", errors="replace", capture_output=True, timeout=60
    )


class RedaccionSalidasTest(unittest.TestCase):
    def comprobar(self, resultado):
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        for flujo in (resultado.stdout, resultado.stderr):
            self.assertNotIn("supersecreta", flujo)
            self.assertNotIn("hunter2", flujo)
            self.assertIn("antes", flujo)
            self.assertIn("fin", flujo)

    def test_peticion_redacta_stdout_y_stderr(self):
        self.comprobar(imprimir_tras_importar("peticion"))

    def test_ejecucion_redacta_stdout_y_stderr(self):
        self.comprobar(imprimir_tras_importar("ejecucion"))


if __name__ == "__main__":
    unittest.main()
