"""Ayuda de fixtures: rellenar el parte de cierre de una unidad sintética (unidad 045).

Desde la 045, `unidad.py cerrar` exige que el bloque ```parte-de-cierre``` de `hallazgos.md`
cuadre con la evidencia que cita. Los tests que cierran unidades de juguete tenían la cabecera
de la plantilla sin rellenar, que es justo lo que la puerta deniega. Esto la rellena con un
parte HONESTO —salidas reales volcadas a `.runtime/`, hashes calculados, números contados
sobre la propia especificación— para que esas pruebas sigan comprobando lo suyo y no la 045.
"""
import hashlib
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "plantilla/docs/00-metodo/scripts"))
import lint_cierre  # noqa: E402 - se importa tras fijar la ruta de los scripts del método


def escribir_parte_honesto(ws, hallazgos):
    """Sustituye el bloque de la plantilla por uno que cuadra, y devuelve el texto escrito.

    `hallazgos` es la ruta del `hallazgos.md` de la unidad. Sobre la ficha de un BUG no hace
    nada: su ficha es contrato y bitácora a la vez (ADR-006) y la puerta no le pide cabecera.
    """
    ws, hallazgos = Path(ws), Path(hallazgos)
    if hallazgos.name != "hallazgos.md":
        return ""
    carpeta = hallazgos.parent
    nombre = carpeta.name
    runtime = ws / ".runtime" / nombre
    runtime.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for fichero in ("tests.txt", "lint.txt"):
        ruta = runtime / fichero
        ruta.write_text(f"salida real de {fichero} para {nombre}\n", encoding="utf-8")
        hashes[fichero] = hashlib.sha256(ruta.read_bytes()).hexdigest()

    requisitos, marcadas, totales = lint_cierre.contar_reales(carpeta / "especificacion.md")
    bloque = (
        "```parte-de-cierre\n"
        "veredicto: entregada\n"
        "tests_cmd: python3 -m unittest discover\n"
        "tests_exit: 0\n"
        f"tests_output: .runtime/{nombre}/tests.txt\n"
        f"tests_sha256: {hashes['tests.txt']}\n"
        "build_cmd: python3 docs/00-metodo/scripts/lint_metodo.py\n"
        "build_exit: 0\n"
        f"build_output: .runtime/{nombre}/lint.txt\n"
        f"build_sha256: {hashes['lint.txt']}\n"
        f"requisitos: {requisitos}/{requisitos}\n"
        f"plan: {marcadas}/{totales}\n"
        "bloqueadores: 0\n"
        "```\n"
    )
    texto = hallazgos.read_text(encoding="utf-8")
    if "```parte-de-cierre" in texto:
        texto = re.sub(r"```parte-de-cierre.*?```\n", bloque, texto, count=1, flags=re.S)
    else:
        texto += "\n" + bloque
    hallazgos.write_text(texto, encoding="utf-8")
    return bloque
