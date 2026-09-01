#!/usr/bin/env python3
"""Publica las cuentas del oráculo adjudicado de incidentes.

El oráculo es `fixtures/reforma/oraculo-incidentes.jsonl`: una fila por incidente conocido del
método, en dos bloques —`esta-maquina` (los 92 registros de la caja negra con los que se midió la
reforma) y `alumnos` (lo que han reportado quienes usan la herramienta)— con la familia del
defecto, el arreglo de la reforma que lo cubriría y qué se espera de ese arreglo.

Sin argumentos imprime tres tablas y la partición de cada bloque. Con `--json`, lo mismo en JSON.
Con `--ayuda`, cómo se añade un incidente nuevo para que el fichero crezca con la realidad.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ORACULO = RAIZ / "fixtures" / "reforma" / "oraculo-incidentes.jsonl"
FAMILIAS = RAIZ / "fixtures" / "reforma" / "oraculo-familias.json"

BLOQUES = ["esta-maquina", "alumnos"]
EXPECTATIVAS = ["evita", "detecta", "sin cobertura", "previo", "fuera de alcance"]
PARTICIONES = ["operacional", "plataforma", "notas"]
ARREGLOS = ["1", "2", "3", "4", "5", "6", "7", "8", "previo", "ninguno"]

AYUDA = """Cómo se añade un incidente nuevo al oráculo
==========================================

Cada incidente nuevo —de la caja negra de esta máquina, de la caja negra que manda un alumno, de
un issue del repo del método o de una petición con autor de soporte— entra AQUÍ antes de que se
cierre. Si no está en el fichero, no está en el denominador, y cualquier porcentaje que se
publique sobre la reforma es falso.

1. Añade una línea a `visor/tests/fixtures/reforma/oraculo-incidentes.jsonl` con estos campos:

   id             estable y por origen: IR12 · AL-2026-08-24-03 · GH-89 · SOP-P-20260901-2cd11ab9
   bloque         esta-maquina | alumnos
   origen         caja-negra | caja-negra-alumno | issue | soporte
   fecha          AAAA-MM-DD del incidente, no del día en que lo apuntas
   harness        claude | codex | ambos
   so             macOS | Windows | ambos
   version_metodo la del método donde ocurrió, si figura; cadena vacía si no
   familia        Fxx de `oraculo-familias.json`; si ninguna encaja, añade una nueva con su
                  definición de UNA línea (ese fichero es el vocabulario cerrado)
   arreglo        1-8 (el arreglo de la reforma que lo cubriría), `previo` (ya tenía arreglo
                  antes de la reforma) o `ninguno`
   expectativa    evita · detecta · sin cobertura · previo · fuera de alcance
   particion      operacional (cuenta en el denominador) · plataforma · notas
   sintoma        UNA línea, sin nombres, correos ni rutas de casa de nadie
   evidencia      de dónde sale y POR QUÉ se adjudicó así; empieza por la fuente citable:
                  matriz-incidentes-reforma-v2.md · caja-negra-alumnos-indice.md · issue #N · P-ID
   duplicado_de   null, o el id de la fila original si es el mismo síntoma en el mismo taller
   contado        true, o false si `duplicado_de` apunta a otra fila

2. Reglas que los tests hacen cumplir (`python3 -m unittest visor/tests/test_oraculo_incidentes.py`):
   - un duplicado NO se cuenta y NO apunta a otro duplicado: siempre a la fila original;
   - `arreglo: ninguno` solo admite `sin cobertura` o `fuera de alcance`; `arreglo: previo`, solo
     `previo` o `fuera de alcance`: ningún arreglo promete lo que no tiene;
   - `plataforma` y `notas` van siempre `fuera de alcance`, con el motivo en `evidencia`;
   - el bloque 1 está CONGELADO en los 92 de la matriz: alta nueva de esta máquina va al bloque 2
     o abre una revisión del corpus, nunca cambia el denominador a escondidas;
   - nada de PII: ni una arroba, ni un `/Users/<alguien>`, ni un identificador de sesión.

3. Vuelve a publicar las cuentas: `python3 visor/tests/oraculo_cuentas.py`.
"""


def cargar(ruta=ORACULO):
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def cuentas(filas):
    por_bloque = {}
    for b in BLOQUES:
        del_bloque = [f for f in filas if f["bloque"] == b]
        c = Counter(f["expectativa"] for f in del_bloque if f["contado"])
        por_bloque[b] = {"total": len(del_bloque),
                         "contados": sum(1 for f in del_bloque if f["contado"]),
                         "duplicados": sum(1 for f in del_bloque if not f["contado"]),
                         **{e: c.get(e, 0) for e in EXPECTATIVAS}}
    familias = defaultdict(lambda: {b: 0 for b in BLOQUES})
    for f in filas:
        if f["contado"]:
            familias[f["familia"]][f["bloque"]] += 1
    arreglos = defaultdict(lambda: {e: 0 for e in EXPECTATIVAS})
    for f in filas:
        if f["contado"]:
            arreglos[f["arreglo"]][f["expectativa"]] += 1
    particion = {}
    for b in BLOQUES:
        c = Counter(f["particion"] for f in filas if f["bloque"] == b and f["contado"])
        particion[b] = {p: c.get(p, 0) for p in PARTICIONES}
    origenes = Counter(f["origen"] for f in filas)
    return {"totales": {"filas": len(filas),
                        "contados": sum(1 for f in filas if f["contado"]),
                        "duplicados": sum(1 for f in filas if not f["contado"])},
            "por_bloque": por_bloque,
            "por_familia": {k: dict(v) for k, v in sorted(familias.items())},
            "por_arreglo": {k: dict(arreglos[k]) for k in ARREGLOS if k in arreglos},
            "particion": particion,
            "por_origen": dict(origenes)}


def tabla(titulo, cabecera, cuerpo):
    anchos = [max(len(str(fila[i])) for fila in [cabecera, *cuerpo]) for i in range(len(cabecera))]
    linea = lambda f: "  ".join(str(v).ljust(a) if i == 0 else str(v).rjust(a)
                                for i, (v, a) in enumerate(zip(f, anchos)))
    salida = [f"\n{titulo}", "-" * len(titulo), linea(cabecera), "  ".join("-" * a for a in anchos)]
    salida += [linea(f) for f in cuerpo]
    return "\n".join(salida)


def imprimir(d, familias):
    print("Oráculo adjudicado de incidentes — {filas} filas, {contados} contadas, "
          "{duplicados} enlazadas como duplicado".format(**d["totales"]))
    print("Origen: " + " · ".join(f"{k} {v}" for k, v in sorted(d["por_origen"].items())))

    print(tabla("Cuentas por bloque y expectativa",
                ["bloque", "contados", *EXPECTATIVAS, "dup."],
                [[b, d["por_bloque"][b]["contados"], *[d["por_bloque"][b][e] for e in EXPECTATIVAS],
                  d["por_bloque"][b]["duplicados"]] for b in BLOQUES]))

    print(tabla("Cuentas por familia y bloque",
                ["familia", *BLOQUES, "total", "definición"],
                [[k, v["esta-maquina"], v["alumnos"], v["esta-maquina"] + v["alumnos"],
                  familias.get(k, "")[:58]] for k, v in d["por_familia"].items()]))

    print(tabla("Cuentas por arreglo y expectativa",
                ["arreglo", *EXPECTATIVAS, "total"],
                [[k, *[v[e] for e in EXPECTATIVAS], sum(v.values())]
                 for k, v in d["por_arreglo"].items()]))

    print(tabla("Partición operacional / plataforma / notas",
                ["bloque", *PARTICIONES, "total"],
                [[b, *[d["particion"][b][p] for p in PARTICIONES], sum(d["particion"][b].values())]
                 for b in BLOQUES]))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="las mismas cuentas en JSON")
    p.add_argument("--ayuda", action="store_true",
                   help="cómo se añade un incidente nuevo al oráculo")
    args = p.parse_args(argv)
    if args.ayuda:
        print(AYUDA)
        return 0
    filas = cargar()
    d = cuentas(filas)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0
    imprimir(d, json.loads(FAMILIAS.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
