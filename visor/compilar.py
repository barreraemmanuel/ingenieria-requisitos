#!/usr/bin/env python3
"""Compila la documentación final de la aplicación: especificaciones/.

Estructura de salida, siempre la misma:
    especificaciones/
      README.md                  (índice)
      01-constitution/
        constitution.md          (los principios y el mapa: lo global)
      02-flows/
        <area>/<actividad>.md    (un spec por actividad con planos)

Se regenera ENTERA en cada ejecución: no se edita a mano. Solo stdlib.

Uso: python3 compilar.py --mapa <ruta/planos.json> [--salida <dir>]
(por defecto escribe en especificaciones/ junto al planos.json)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))


def slug(texto):
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "area"


def generar(datos, salida):
    r = subprocess.run([sys.executable, os.path.join(BASE, "generar_spec.py"),
                        "--datos", datos, "--salida", salida],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit("Fallo generando %s:\n%s%s" % (salida, r.stdout, r.stderr))


def md_constitution(d):
    L = []
    a = L.append
    a("# Constitución: %s" % d.get("titulo", "Proyecto"))
    a("")
    a("Lo que vale para TODA la aplicación: qué es, para qué, quién aparece, "
      "qué reglas de calidad se respetan siempre y qué queda fuera. Generado "
      "desde los planos: no editar a mano.")
    a("")
    definicion = d.get("definicion") or {}
    cobertura = d.get("cobertura") or {}
    if definicion or cobertura:
        a("## Estado y procedencia")
        a("")
        if definicion:
            a("- Diseño: **%s** (modo: %s)." % (
                definicion.get("estado", "borrador"),
                definicion.get("modo", "sin declarar"),
            ))
        if cobertura:
            a("- Cobertura observada en el código actual: **%s**." %
              cobertura.get("estado", "no verificado"))
        for supuesto in definicion.get("supuestos", []):
            a("- %s [%s, %s]: %s" % (
                supuesto.get("id", "Supuesto"),
                supuesto.get("origen", "inferido"),
                supuesto.get("estado", "propuesto"),
                supuesto.get("texto", ""),
            ))
        a("")
    if d.get("descripcion"):
        a("## Qué es")
        a("")
        a(d["descripcion"])
        a("")
    c = d.get("contrato") or {}
    if c.get("frase"):
        a("## Propósito")
        a("")
        a(c["frase"])
        exito = c.get("exito")
        if exito:
            a("")
            a("Criterios de éxito:")
            for x in (exito if isinstance(exito, list) else [exito]):
                a("- %s" % x)
        a("")
    if d.get("actores") or d.get("vocabulario"):
        a("## Actores y vocabulario")
        a("")
        for x in d.get("actores", []):
            a("- **%s**%s" % (x["nombre"], (": %s" % x["rol"]) if x.get("rol") else ""))
        if d.get("vocabulario"):
            a("")
            for v in d["vocabulario"]:
                a("- \"%s\": %s" % (v["termino"], v["significado"]))
        a("")
    if d.get("actividades"):
        a("## El mapa de la aplicación")
        a("")
        a("Cada actividad tiene (o tendrá) su propio documento en `02-flows/`.")
        a("")
        areas = []
        for x in d["actividades"]:
            if x["area"] not in areas:
                areas.append(x["area"])
        for area in areas:
            a("### %s" % area)
            a("")
            for x in [y for y in d["actividades"] if y["area"] == area]:
                extra = []
                if x.get("resumen"):
                    extra.append(x["resumen"])
                if x.get("depende_de"):
                    extra.append("necesita antes: %s" % ", ".join(x["depende_de"]))
                a("- [%s] **%s** (`%s`)%s" % (x.get("estado", "sin empezar"), x["nombre"], x["id"],
                                              (": " + "; ".join(extra)) if extra else ""))
            a("")
    if d.get("datos"):
        a("## Datos compartidos")
        a("")
        for x in d["datos"]:
            a("- **%s**: %s%s" % (x["cosa"], ", ".join(x.get("guarda", [])),
                                  (" (origen: %s)" % x["origen"]) if x.get("origen") else ""))
        a("")
    if d.get("integraciones"):
        a("## Integraciones")
        a("")
        for x in d["integraciones"]:
            a("- **%s**%s" % (x["con"], (": %s" % x["para"]) if x.get("para") else ""))
        a("")
    if d.get("calidad"):
        a("## Compromisos de toda la aplicación")
        a("")
        for q in d["calidad"]:
            a("- **%s**: %s" % (q["id"], q["criterio"]))
        a("")
    if d.get("fuera"):
        a("## Fuera de alcance")
        a("")
        for x in d["fuera"]:
            a("- %s" % x)
        a("")
    if d.get("preguntas"):
        a("## Preguntas abiertas globales")
        a("")
        for x in d["preguntas"]:
            a("- %s" % x)
        a("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapa", required=True, help="El planos.json del mapa (o de un proyecto de una sola actividad)")
    ap.add_argument("--salida", help="Carpeta destino (defecto: especificaciones/ junto al mapa)")
    args = ap.parse_args()

    ruta_mapa = os.path.abspath(args.mapa)
    try:
        with open(ruta_mapa, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("No pude leer los planos: %s" % e)

    raiz = os.path.dirname(ruta_mapa)
    out = os.path.abspath(args.salida or os.path.join(raiz, "especificaciones"))
    c1 = os.path.join(out, "01-constitution")
    c2 = os.path.join(out, "02-flows")
    # Estas rutas son propiedad exclusiva del compilador. Se reconstruyen
    # completas para que una actividad eliminada no deje archivos residuales.
    for controlado in (c1, c2):
        if os.path.isdir(controlado):
            shutil.rmtree(controlado)
    indice = os.path.join(out, "README.md")
    if os.path.isfile(indice):
        os.remove(indice)
    os.makedirs(c1, exist_ok=True)
    os.makedirs(c2, exist_ok=True)

    with open(os.path.join(c1, "constitution.md"), "w", encoding="utf-8") as f:
        f.write(md_constitution(d))

    idx = []
    idx.append("# %s: especificaciones" % d.get("titulo", "Proyecto"))
    idx.append("")
    if (d.get("contrato") or {}).get("frase"):
        idx.append("> %s" % d["contrato"]["frase"])
        idx.append("")
    idx.append("Generado desde los planos con `visor/compilar.py`: no editar a mano.")
    idx.append("")
    idx.append("- [01-constitution/constitution.md](01-constitution/constitution.md): lo que vale para toda la aplicación.")
    idx.append("- `02-flows/`: un documento por actividad.")
    idx.append("")

    actividades = d.get("actividades", [])
    if actividades:
        con, sin = 0, 0
        areas = []
        for x in actividades:
            if x["area"] not in areas:
                areas.append(x["area"])
        for area in areas:
            idx.append("## %s" % area)
            idx.append("")
            for x in [y for y in actividades if y["area"] == area]:
                pj = os.path.join(raiz, "actividades", x["id"], "planos.json")
                estado = x.get("estado", "sin empezar")
                if os.path.isfile(pj):
                    destino_rel = os.path.join("02-flows", slug(area), x["id"] + ".md")
                    destino = os.path.join(out, destino_rel)
                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    generar(pj, destino)
                    idx.append("- [%s](%s) · %s" % (x["nombre"], destino_rel.replace(os.sep, "/"), estado))
                    con += 1
                else:
                    idx.append("- %s · %s · (aún sin planos)" % (x["nombre"], estado))
                    sin += 1
            idx.append("")
        resumen = "%d actividades con especificación, %d aún sin planos." % (con, sin)
    else:
        nombre = slug(d.get("proyecto") or d.get("titulo") or "aplicacion")
        destino_rel = os.path.join("02-flows", nombre + ".md")
        generar(ruta_mapa, os.path.join(out, destino_rel))
        idx.append("- [%s](%s)" % (d.get("titulo", "Especificación"), destino_rel.replace(os.sep, "/")))
        idx.append("")
        resumen = "Proyecto de una sola actividad."

    idx.append("---")
    idx.append("")
    idx.append(resumen)
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(idx) + "\n")
    print("Especificaciones compiladas en %s (%s)" % (out, resumen))


if __name__ == "__main__":
    main()
