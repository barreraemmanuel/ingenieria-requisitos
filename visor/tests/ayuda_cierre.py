"""Ayuda de fixtures: rellenar el parte de cierre de una unidad sintética (unidad 045).

Desde la 045, `unidad.py cerrar` exige que el bloque ```parte-de-cierre``` de `hallazgos.md`
cuadre con la evidencia que cita. Los tests que cierran unidades de juguete tenían la cabecera
de la plantilla sin rellenar, que es justo lo que la puerta deniega. Esto la rellena con un
parte HONESTO —salidas reales volcadas a `.runtime/`, hashes calculados, números contados
sobre la propia especificación— para que esas pruebas sigan comprobando lo suyo y no la 045.
"""
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "plantilla/docs/00-metodo/scripts"))
import lint_cierre  # noqa: E402 - se importa tras fijar la ruta de los scripts del método
import unidad as gestion_unidades  # noqa: E402 - mismo motivo


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
    hallazgos.write_text(sellar_ancla(ws, nombre, rellenar_aprendizajes(texto)),
                         encoding="utf-8")
    return bloque


def sellar_ancla(ws, nombre, texto):
    """Unidad 068: una firma de revisión con fecha lleva pegada la huella del contenido que
    se revisó (`revisado_patch_id`), y quien la sella es `ejecucion.py` al lanzar al revisor.

    Las unidades de juguete firman su cabecera a mano, así que aquí se sella lo mismo que
    habría sellado el launcher — el patch-id REAL de la rama, calculado con las mismas
    funciones que usa la puerta del cierre, para que fixture y guardián no puedan discrepar.
    Cuando no hay rama medible (repo sin git, rama ya fusionada sin base registrada) se cae a
    una huella con forma de patch-id: la puerta lo avisa y sigue, que es su comportamiento
    declarado. El ancla contra un git de verdad la miden los tests de la propia 068.
    """
    return re.sub(r"(?m)^revisado_patch_id:.*$",
                  "revisado_patch_id: " + (patch_id_real(ws, nombre) or "a" * 40),
                  texto, count=1)


def patch_id_real(ws, nombre):
    """El patch-id que tendría la rama `nombre` del repo de juguete, o "" si no se puede.

    Se mide con las MISMAS funciones y la MISMA base que la puerta del cierre: la registrada
    en el despacho manda en cuanto la rama ya está dentro de la principal (ahí el merge-base
    es la propia punta y mediría cero). Reconstruirla de otra forma haría que el fixture y el
    guardián hablaran de árboles distintos, que es justo el fallo que la 068 persigue.
    """
    repo = Path(ws) / "main"
    if not (repo / ".git").exists():
        return ""
    punta = gestion_unidades.punta_a_medir(repo, nombre, "main")
    base, _ = gestion_unidades.base_de_medida(
        repo, punta, "main", base_registrada(ws, nombre))
    return gestion_unidades.patch_id_del_diff(repo, base, punta)


def base_registrada(ws, nombre):
    """El `base_sha` que el despacho anotó para esta unidad en sus peticiones, o None.

    Se lee del JSON a pelo en vez de por `peticion.py` porque ese módulo resuelve su raíz
    contra el repo de verdad, no contra el workspace de juguete que monta cada test.
    """
    carpeta = Path(ws) / "docs/05-trabajo/peticiones"
    for ruta in sorted(carpeta.glob("P-*/peticion.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for proceso in datos.get("procesos", []):
            if proceso.get("ref") == nombre:
                sha = (proceso.get("metadata") or {}).get("base_sha")
                if sha:
                    return sha
    return None


def rellenar_aprendizajes(texto):
    """Unidad 071: la sección `## Aprendizajes` también llega con marcadores, y desde la 071
    la puerta del cierre la exige rellena. Aquí se pone una frase honesta por bloque para que
    las pruebas que CIERRAN unidades de juguete sigan comprobando lo suyo y no la 071."""
    hoy = datetime.date.today().isoformat()
    for quien in ("constructor", "revisor"):
        texto = re.sub(
            r"(```aprendizajes-" + quien + r"[ \t]*\n).*?(```)",
            lambda m, q=quien: (m.group(1) + f"- {hoy} · {q}: ninguno\n" + m.group(2)),
            texto, count=1, flags=re.S)
    return texto
