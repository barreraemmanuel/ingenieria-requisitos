"""Trinquete de codificación (bug 042): que esto no vuelva con el próximo script nuevo.

El arreglo de la 042 tocó 32 sitios —22 `subprocess` en modo texto y 10 guardianes de
salida— y se fusionó apoyado SOLO en evidencia manual de una consola de Windows. Nada
impedía que el script nº 31 naciera sin guardián y el mojibake volviera. Esto es esa
pieza, y es un trinquete: recorre los puntos de entrada de producción y falla si uno
imprime sin guardián, o si lanza un `subprocess` en modo texto sin decir la codificación.

Las dos mitades son la misma causa raíz por las dos puntas. En Windows la codificación
local es cp1252 y Python la usa por defecto en ambas direcciones:

- **al escribir** — con stdout redirigido (`> log.txt`, un agente capturando) el script
  hereda cp1252; un `→ ≤ ✓` mata el proceso con `UnicodeEncodeError`;
- **al leer** — `text=True` sin `encoding=` decodifica en cp1252 lo que el hijo escribió
  en UTF-8, y sale `mÃ©todo` donde ponía `método`.

Fuera de Windows los dos arreglos son un no-op, así que este test es lo único que los
sostiene en la máquina donde se desarrolla. Por eso lee el CÓDIGO, no la salida.
"""
import ast
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Producción: todo lo que se despacha al usuario. Los tests quedan fuera a propósito —
# los suyos los cubre la 041, que además los lanza con el modo UTF-8 puesto.
ZONAS = ("visor", "visor_contratos", "plantilla", "plantilla/docs/00-metodo/scripts")

# Un punto de entrada que imprime y NO lleva guardián propio. La lista es corta y cada
# entrada dice por dónde le llega la reconfiguración; el test comprueba que sigue siendo
# verdad, para que la excusa no sobreviva al motivo.
SIN_GUARDIAN_PROPIO = {
    "plantilla/docs/00-metodo/scripts/ejecucion.py": (
        "plantilla/docs/00-metodo/scripts/control_plane.py",   # redactar_salidas() reconfigura
    ),
}

LANZADORAS = ("run", "Popen", "check_output", "call", "check_call")


def guardian(fuente):
    """¿Reconfigura su salida a UTF-8? Se mira el AST, no el texto: un comentario que
    hable de `reconfigure` no debe contar como cobertura."""
    for nodo in ast.walk(ast.parse(fuente)):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "reconfigure"
                and any(k.arg == "encoding" for k in nodo.keywords)):
            return True
    return False


def imprime(arbol):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
               for n in ast.walk(arbol))


def es_punto_de_entrada(arbol):
    """Tiene el `if __name__ == "__main__":` que lo hace ejecutable a mano."""
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.If) and isinstance(nodo.test, ast.Compare)
                and isinstance(nodo.test.left, ast.Name) and nodo.test.left.id == "__name__"):
            return True
    return False


def modo_texto(nodo):
    return any(k.arg in ("text", "universal_newlines")
               and isinstance(k.value, ast.Constant) and k.value.value is True
               for k in nodo.keywords)


def es_subprocess(nodo):
    f = nodo.func
    return (isinstance(f, ast.Attribute) and f.attr in LANZADORAS
            and isinstance(f.value, ast.Name) and f.value.id == "subprocess")


def fuentes():
    vistas = {}
    for zona in ZONAS:
        for ruta in sorted((RAIZ / zona).glob("*.py")):
            vistas[ruta.relative_to(RAIZ).as_posix()] = ruta.read_text(encoding="utf-8")
    return vistas


class GuardianDeSalidaTest(unittest.TestCase):
    """Al escribir: todo punto de entrada que imprime reconfigura su stdout a UTF-8."""

    def test_todo_punto_de_entrada_que_imprime_lleva_guardian(self):
        faltan = []
        for relativa, fuente in fuentes().items():
            arbol = ast.parse(fuente)
            if not (es_punto_de_entrada(arbol) and imprime(arbol)):
                continue
            if guardian(fuente) or relativa in SIN_GUARDIAN_PROPIO:
                continue
            faltan.append(relativa)

        self.assertEqual(faltan, [], "\n".join([
            "estos scripts imprimen y no reconfiguran su salida: con stdout redirigido",
            "escriben cp1252 y un '→' los mata. Añade junto a los imports:",
            '    for _salida in (sys.stdout, sys.stderr):',
            '        if hasattr(_salida, "reconfigure"):',
            '            _salida.reconfigure(encoding="utf-8", errors="replace")',
        ] + faltan))

    def test_la_excepcion_declarada_sigue_estando_cubierta_por_donde_dice(self):
        """La lista de excepciones no puede sobrevivir a su motivo: si mañana
        `control_plane` deja de reconfigurar, este test cae y `ejecucion.py` vuelve a
        necesitar guardián propio."""
        for eximido, coberturas in SIN_GUARDIAN_PROPIO.items():
            with self.subTest(eximido=eximido):
                self.assertTrue((RAIZ / eximido).is_file(), f"{eximido} ya no existe")
                self.assertTrue(
                    any(guardian((RAIZ / c).read_text(encoding="utf-8")) for c in coberturas),
                    f"{eximido} está eximido porque {coberturas} reconfiguraban, y ya no")
                # Y que de verdad lo importe: la cobertura tiene que llegarle.
                fuente = (RAIZ / eximido).read_text(encoding="utf-8")
                self.assertTrue(
                    any(Path(c).stem in fuente for c in coberturas),
                    f"{eximido} ya no importa a quien le reconfiguraba la salida")

    def test_el_guardian_declara_errors_replace(self):
        """`errors="replace"` es parte del arreglo, no un adorno: sin él una consola
        que no admita el carácter vuelve a matar el proceso en vez de degradarlo."""
        sin_replace = []
        for relativa, fuente in fuentes().items():
            for nodo in ast.walk(ast.parse(fuente)):
                if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                        and nodo.func.attr == "reconfigure"
                        and any(k.arg == "encoding" for k in nodo.keywords)
                        and not any(k.arg == "errors" for k in nodo.keywords)):
                    sin_replace.append(f"{relativa}:{nodo.lineno}")

        self.assertEqual(sin_replace, [])


class SubprocessEnModoTextoTest(unittest.TestCase):
    """Al leer: nadie decodifica la salida de un hijo con la codificación local."""

    def test_ningun_subprocess_en_modo_texto_se_calla_la_codificacion(self):
        mudos = []
        for relativa, fuente in fuentes().items():
            for nodo in ast.walk(ast.parse(fuente)):
                if not (isinstance(nodo, ast.Call) and es_subprocess(nodo)):
                    continue
                if modo_texto(nodo) and not any(k.arg == "encoding" for k in nodo.keywords):
                    mudos.append(f"{relativa}:{nodo.lineno}")

        self.assertEqual(mudos, [], "\n".join([
            "estos subprocess piden modo texto sin decir en qué codificación: en Windows",
            'decodifican cp1252 lo que el hijo escribió en UTF-8 y sale "mÃ©todo".',
            'Añade encoding="utf-8", errors="replace".',
        ] + mudos))

    def test_el_trinquete_ve_de_verdad_los_sitios_que_dice_cubrir(self):
        """Que no pase en verde por no estar mirando nada. El arreglo dejó 22 llamadas
        en modo texto en producción; si el barrido encontrara cero, estaría roto."""
        en_modo_texto = sum(
            1
            for fuente in fuentes().values()
            for nodo in ast.walk(ast.parse(fuente))
            if isinstance(nodo, ast.Call) and es_subprocess(nodo) and modo_texto(nodo)
        )
        self.assertGreaterEqual(en_modo_texto, 22, "el barrido dejó de ver la producción")


if __name__ == "__main__":
    unittest.main()
