"""D1 y el bonus del bug 042, medidos de verdad: mojibake al leer, cp1252 al escribir.

Lo primero que veía un usuario de Windows al montar su workspace era esto:

    == Linter del mÃ©todo ==
      OK   AGENTS.md existe (160 lÃ­neas â‰¤ 160)

El hijo (`lint_metodo.py`) escribe UTF-8; el padre (`bootstrap.py`) lo pedía en modo
texto sin decir la codificación y lo decodificaba con la local, cp1252. Y por la otra
punta, los puntos de entrada que imprimían sin reconfigurar su stdout escribían cp1252
cuando la salida iba redirigida — y morían con `UnicodeEncodeError` en cuanto el texto
llevaba un `→` o un `≤`, que los mensajes del método llevan.

**Cómo se reproduce fuera de Windows.** El defecto no es de Windows, es de «la
codificación local no es UTF-8»; Windows solo es donde eso pasa de fábrica. Aquí se
provoca la misma condición con un entorno de locale ASCII: `LC_ALL=C` más
`PYTHONCOERCECLOCALE=0` y `PYTHONUTF8=0` (sin los dos últimos Python 3.7+ se corrige
solo a UTF-8 y el fallo no aparece). ASCII es más estrecho que cp1252, así que lo que
allí salía torcido aquí revienta: el rojo es aún más claro que el original.

`visor/tests/correr.py` lanza la suite con el modo UTF-8 puesto; por eso estos tests
CONSTRUYEN su entorno desde cero en vez de heredarlo, o medirían el cinturón del
lanzador en lugar del arreglo.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
VALIDAR = RAIZ / "visor/validar.py"
EJEMPLO = RAIZ / "visor/ejemplo.json"


def entorno_sin_utf8(**extra):
    """El entorno de una máquina cuya codificación local NO es UTF-8."""
    entorno = dict(os.environ)
    for variable in ("PYTHONUTF8", "PYTHONIOENCODING"):
        entorno.pop(variable, None)
    entorno.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", **extra)
    return entorno


class BootstrapNoImprimeMojibakeTest(unittest.TestCase):
    """Al LEER: el bootstrap reimprime la salida del linter tal cual la escribió."""

    def test_el_linter_del_metodo_conserva_sus_acentos_al_reimprimirse(self):
        temporal = tempfile.mkdtemp(prefix="mojibake-")
        self.addCleanup(shutil.rmtree, temporal, True)
        raiz = Path(temporal)
        planos = raiz / "planos"
        planos.mkdir()
        shutil.copyfile(EJEMPLO, planos / "planos.json")

        resultado = subprocess.run(
            [sys.executable, str(BOOTSTRAP), "--planos", str(planos),
             "--destino", str(raiz / "ws"), "--tipo", "otro", "--compilar"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            # El registro real de la máquina no se toca (igual que el e2e de contrato).
            env=entorno_sin_utf8(INGENIERIA_REQUISITOS_REGISTRO=str(raiz / "registro.json")),
        )

        # Sin el arreglo esto es un UnicodeDecodeError dentro de subprocess: el bootstrap
        # ni siquiera llega a imprimir el bloque del linter.
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        salida = resultado.stdout
        self.assertIn("== Linter del método ==", salida)
        self.assertIn("arsenal del método completo", salida)
        self.assertNotIn("mÃ©todo", salida)
        self.assertNotIn("lÃ­neas", salida)
        self.assertNotIn("â‰¤", salida)
        # Y el carácter que además MATABA el proceso, no solo lo afeaba.
        self.assertIn("≤", salida)


class LosPuntosDeEntradaEscribenUTF8Test(unittest.TestCase):
    """Al ESCRIBIR: con la salida redirigida se sigue emitiendo UTF-8, no la local."""

    def salida_cruda(self, *orden):
        return subprocess.run([sys.executable, *orden], capture_output=True,
                              env=entorno_sin_utf8()).stdout          # bytes, sin decodificar

    def test_validar_emite_UTF8_y_no_la_codificacion_local(self):
        crudo = self.salida_cruda(str(VALIDAR), "--datos", str(EJEMPLO))

        self.assertIn("válidos".encode("utf-8"), crudo)               # 0xC3 0xA1
        self.assertNotIn("válidos".encode("cp1252"), crudo)           # 0xE1, el defecto

    def test_un_caracter_fuera_de_la_codificacion_local_ya_no_mata_el_script(self):
        """`→ ≤ ✓ ⚠` salen en los mensajes del método. Sin guardián, con la salida
        redirigida, imprimirlos era un UnicodeEncodeError y el script moría."""
        temporal = tempfile.mkdtemp(prefix="mojibake-flecha-")
        self.addCleanup(shutil.rmtree, temporal, True)
        rotos = json.loads(EJEMPLO.read_text(encoding="utf-8"))
        rotos.pop("identidad", None)          # que el validador tenga algo que contar
        planos = Path(temporal) / "planos.json"
        planos.write_text(json.dumps(rotos, ensure_ascii=False), encoding="utf-8")

        proceso = subprocess.run(
            [sys.executable, str(VALIDAR), "--datos", str(planos)],
            capture_output=True, env=entorno_sin_utf8())

        self.assertNotIn(b"UnicodeEncodeError", proceso.stderr)
        self.assertNotIn(b"charmap", proceso.stderr)


if __name__ == "__main__":
    unittest.main()
