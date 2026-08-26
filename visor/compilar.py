#!/usr/bin/env python3
"""Compila la documentación final de la aplicación: especificaciones/.

Dos formatos de salida, y manda el que YA tiene el proyecto (bug 092):

  carpetas (el de una salida nueva)      plano (el de los workspaces del bootstrap)
    especificaciones/                      docs/02-flujos/
      README.md          (índice)            INDICE.md        (lo mantiene el padre)
      01-constitution/                       <actividad>.md   (un spec por actividad,
        constitution.md  (lo global)                           hermanos del índice)
      02-flows/
        <area>/<actividad>.md

Antes de escribir se mira `--salida`: si ya hay .md planos con el nombre de las
actividades del mapa (o un índice que enlaza a ellos) y NO hay 01-constitution/ ni
02-flows/, se recompila el plano; si están las carpetas, se hacen carpetas; si hay
las dos cosas —o documentación que no se reconoce— no se escribe nada y se piden
`--formato plano` o `--formato carpetas`. Migrar de un formato al otro no es cosa
de este script: cambiaría sin permiso ficheros que el usuario versiona.

Lo que este script controla se regenera ENTERO en cada ejecución: no se edita a
mano. En formato plano solo son suyos los `<actividad>.md`; el índice y la
constitución los mantiene el padre del workspace. Solo stdlib.

Uso: python3 compilar.py --mapa <ruta/planos.json> [--salida <dir>]
                         [--formato plano|carpetas]
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


def nombres_planos(d):
    """Los .md que tendría este mapa compilado en formato plano (uno por actividad)."""
    actividades = d.get("actividades", [])
    if actividades:
        return [x["id"] + ".md" for x in actividades]
    return [slug(d.get("proyecto") or d.get("titulo") or "aplicacion") + ".md"]


def detectar_formato(out, esperados):
    """Qué formato tiene YA la carpeta de salida: 'plano', 'carpetas' o None (ambiguo).

    Segundo valor: el motivo, para poder explicarlo cuando no se puede decidir.
    Una salida que todavía no existe (o sin ningún .md) no es ambigua: es nueva, y
    ahí el formato de siempre es el de carpetas.
    """
    if not os.path.isdir(out):
        return "carpetas", "salida nueva"
    entradas = sorted(os.listdir(out))
    marcas_carpetas = [x for x in ("01-constitution", "02-flows")
                       if os.path.isdir(os.path.join(out, x))]
    if os.path.isfile(os.path.join(out, "README.md")):
        marcas_carpetas.append("README.md")
    marcas_planas = [x for x in esperados if os.path.isfile(os.path.join(out, x))]
    indice = os.path.join(out, "INDICE.md")
    if os.path.isfile(indice):
        try:
            with open(indice, "r", encoding="utf-8", errors="replace") as f:
                texto = f.read()
        except OSError:
            texto = ""
        for nombre in esperados:
            if ("](%s)" % nombre) in texto and nombre not in marcas_planas:
                marcas_planas.append("INDICE.md → %s" % nombre)
    if marcas_carpetas and marcas_planas:
        return None, "conviven %s con %s" % (", ".join(marcas_planas),
                                             ", ".join(marcas_carpetas))
    if marcas_planas:
        return "plano", ", ".join(marcas_planas)
    if marcas_carpetas:
        return "carpetas", ", ".join(marcas_carpetas)
    ajenos = [x for x in entradas if x.lower().endswith(".md")]
    if ajenos:
        return None, ("ya hay documentación (%s) que no corresponde a ninguna "
                      "actividad del mapa" % ", ".join(ajenos))
    return "carpetas", "salida vacía"


def compilar_plano(d, ruta_mapa, raiz, out):
    """Un .md por actividad, hermanos del índice. No toca nada más de la carpeta."""
    escritos = []
    actividades = d.get("actividades", [])
    if actividades:
        sin_planos = []
        for x in actividades:
            pj = os.path.join(raiz, "actividades", x["id"], "planos.json")
            if os.path.isfile(pj):
                nombre = x["id"] + ".md"
                generar(pj, os.path.join(out, nombre))
                escritos.append(nombre)
            else:
                sin_planos.append(x["nombre"])
        resumen = "%d actividad(es) recompilada(s)" % len(escritos)
        if sin_planos:
            resumen += ", %d aún sin planos (%s)" % (len(sin_planos), ", ".join(sin_planos))
    else:
        nombre = nombres_planos(d)[0]
        generar(ruta_mapa, os.path.join(out, nombre))
        escritos.append(nombre)
        resumen = "proyecto de una sola actividad"
    return escritos, resumen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapa", required=True, help="El planos.json del mapa (o de un proyecto de una sola actividad)")
    ap.add_argument("--salida", help="Carpeta destino (defecto: especificaciones/ junto al mapa)")
    ap.add_argument("--formato", choices=("plano", "carpetas"),
                    help="Fuerza el formato de salida en vez de deducirlo de lo que ya hay")
    args = ap.parse_args()

    ruta_mapa = os.path.abspath(args.mapa)
    try:
        with open(ruta_mapa, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("No pude leer los planos: %s" % e)

    raiz = os.path.dirname(ruta_mapa)
    out = os.path.abspath(args.salida or os.path.join(raiz, "especificaciones"))

    # Antes de escribir, mirar qué estructura tiene YA el proyecto: escribir la
    # estructura de carpetas encima de un proyecto plano dejaba su .md histórico
    # huérfano y la documentación incoherente (bug 092).
    formato, motivo = detectar_formato(out, nombres_planos(d))
    if args.formato:
        formato = args.formato
    elif formato is None:
        sys.exit(
            "compilar: no sé en qué formato está %s (%s), así que no escribo nada "
            "para no pisar el que ya usas.\n"
            "SALIDA: dime cuál quieres con --formato plano (un .md por actividad, "
            "hermanos del índice) o --formato carpetas (01-constitution/ + 02-flows/ "
            "+ README.md)." % (out, motivo)
        )

    if formato == "plano":
        os.makedirs(out, exist_ok=True)
        escritos, resumen = compilar_plano(d, ruta_mapa, raiz, out)
        print("Especificaciones compiladas en %s, formato plano (%s): %s" %
              (out, resumen, ", ".join(escritos) or "nada que compilar"))
        print("No he tocado el índice ni la constitución: en este formato los "
              "mantiene el padre del workspace.")
        sobrantes = [x for x in sorted(os.listdir(out))
                     if x.lower().endswith(".md") and x != "INDICE.md" and x not in escritos]
        if sobrantes:
            print("Tampoco he tocado, y ya no salen del mapa: %s" % ", ".join(sobrantes))
        return

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
