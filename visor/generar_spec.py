#!/usr/bin/env python3
"""Genera spec.md desde planos.json. Proyección de TEXTO de los planos:
determinista, misma estructura siempre. No se edita el spec a mano; se
edita planos.json y se regenera.

Uso: python3 generar_spec.py --datos <ruta/planos.json> [--salida <ruta/spec.md>]
(por defecto escribe spec.md junto al planos.json)
"""

import argparse
import json
import os
import sys


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
L = []  # líneas del documento


def p(texto=""):
    L.append(texto)


def celda(x):
    # Sin '|' ni saltos de línea dentro de una celda: romperían la tabla.
    return " ".join(str(x).split()).replace("|", "\\|")


def texto_nunca(valor):
    if isinstance(valor, dict):
        refs = " · ".join(
            x for x in (valor.get("requisito"), valor.get("criterio")) if x
        )
        return "%s%s" % (
            valor.get("accion", ""),
            " (%s)" % refs if refs else "",
        )
    return str(valor)


def tabla_md(columnas, filas):
    p("| " + " | ".join(celda(c) for c in columnas) + " |")
    p("|" + "---|" * len(columnas))
    for f in filas:
        p("| " + " | ".join(celda(c) for c in f) + " |")
    p()


ETIQUETAS = {"humano": "persona", "estatico": "automático: código",
             "ia": "automático: IA", "externo": "tercero externo"}


def paso_texto(paso, sangria):
    pre = "    " * sangria
    if paso["tipo"] == "decision":
        marca = "⚠ Excepción" if paso["clase"] == "excepcion" else "⚑ Regla"
        quien = (" (la evalúa %s)" % paso["quien"]) if paso.get("quien") else ""
        p("%s- %s%s: %s" % (pre, marca, quien, paso["condicion"]))
        ramas = paso.get("ramas") or ([paso["rama"]] if paso.get("rama") else [])
        for r in ramas:
            p("%s    - si %s:" % (pre, r["etiqueta"]))
            for x in r["pasos"]:
                paso_texto(x, sangria + 2)
            p("%s        - %s" % (pre, "aquí termina este camino" if r.get("termina") else "…y vuelve al flujo"))
        if paso.get("sigue"):
            p("%s    - camino normal: %s" % (pre, paso["sigue"]))
    else:
        quien = (" · %s" % paso["quien"]) if paso.get("quien") else ""
        p("%s- [%s] %s%s" % (pre, ETIQUETAS[paso["tipo"]], paso["texto"], quien))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", required=True)
    ap.add_argument("--salida")
    args = ap.parse_args()

    try:
        with open(args.datos, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("No pude leer los planos: %s" % e)
    if d.get("version") != 2 or not d.get("titulo"):
        sys.exit("planos.json debe tener version: 2 y titulo.")
    d["titulo"] = " ".join(str(d["titulo"]).split())
    no_aplican = set((d.get("definicion") or {}).get("bloques_no_aplican", []))

    def ausencia(bloque, pendiente="(Pendiente.)"):
        p("(No aplica a este proyecto.)" if bloque in no_aplican else pendiente)

    salida = args.salida or os.path.join(os.path.dirname(os.path.abspath(args.datos)), "spec.md")

    p("# Spec: %s" % d["titulo"])
    p()
    p("Proyecto `%s`. Generado desde `planos.json` (la fuente de verdad): no editar a mano." % d.get("proyecto", "?"))
    p()
    if d.get("definicion"):
        definicion = d["definicion"]
        p("**Estado del diseño:** %s · **modo:** %s." % (
            definicion.get("estado", "borrador"),
            definicion.get("modo", "sin declarar"),
        ))
        p()
    if d.get("cobertura"):
        p("**Cobertura observada en el código actual:** %s." %
          d["cobertura"].get("estado", "no verificado"))
        p()
    supuestos = (d.get("definicion") or {}).get("supuestos", [])
    if supuestos:
        p("Supuestos que el usuario debe revisar:")
        for supuesto in supuestos:
            p("- **%s · %s:** %s" % (
                supuesto.get("id", "supuesto"),
                supuesto.get("estado", "propuesto"),
                supuesto.get("texto", ""),
            ))
        p()

    p("## 1. Propósito")
    p()
    if d.get("descripcion"):
        p(d["descripcion"])
        p()
    c = d.get("contrato") or {}
    p(c.get("frase") or "(Pendiente: aún sin frase de contrato.)")
    exito = c.get("exito")
    if exito:
        p()
        p("Criterios de éxito:")
        for x in (exito if isinstance(exito, list) else [exito]):
            p("- %s" % x)
    p()

    if d.get("actividades"):
        p("## El mapa de la aplicación")
        p()
        p("Catálogo completo de actividades por zona del negocio. Cada actividad "
          "tiene (o tendrá) sus propios planos en `actividades/<id>/`.")
        p()
        areas = []
        for a in d["actividades"]:
            if a["area"] not in areas:
                areas.append(a["area"])
        for area in areas:
            p("### %s" % area)
            p()
            for a in d["actividades"]:
                if a["area"] != area:
                    continue
                extra = []
                if a.get("resumen"):
                    extra.append(a["resumen"])
                if a.get("depende_de"):
                    extra.append("necesita antes: %s" % ", ".join(a["depende_de"]))
                p("- [%s] **%s** (`%s`)%s" % (a.get("estado", "sin empezar"), a["nombre"], a["id"],
                                              (": " + "; ".join(extra)) if extra else ""))
            p()

    p("## 2. Actores y vocabulario")
    p()
    for a in d.get("actores", []):
        identidad = [a["nombre"]]
        if a.get("rol"):
            identidad.append(a["rol"])
        if a.get("organizacion"):
            identidad.append("organización: %s" % a["organizacion"])
        if a.get("grupos"):
            identidad.append("grupos: %s" % ", ".join(a["grupos"]))
        if a.get("estado"):
            identidad.append("estado: %s" % a["estado"])
        p("- **%s**" % " · ".join(identidad))
    if d.get("vocabulario"):
        p()
        for v in d["vocabulario"]:
            p("- \"%s\": %s" % (v["termino"], v["significado"]))
    if not d.get("actores") and not d.get("vocabulario"):
        ausencia("actores")
    p()

    p("## 3. El proceso (flujos)")
    p()
    p("La versión gráfica vive en el visor local del paquete (visor/servir.py).")
    p()
    flujos = sorted(d.get("flujos", []), key=lambda f: 0 if f["momento"] == "futuro" else 1)
    if any(f["momento"] == "hoy" for f in flujos) and any(f["momento"] == "futuro" for f in flujos):
        p("Lo que se construye son los flujos \"con la app\"; los flujos \"hoy\" "
          "son la foto del antes y se incluyen como contexto.")
        p()
    for f in flujos:
        p("### %s [%s%s]" % (
            f["titulo"],
            "hoy" if f["momento"] == "hoy" else "con la app",
            (" · origen: %s" % f["origen"]) if f.get("origen") else "",
        ))
        if f.get("descripcion"):
            p()
            p(f["descripcion"])
        p()
        for paso in f["pasos"]:
            paso_texto(paso, 0)
        p()
    if not d.get("flujos"):
        ausencia("flujos")
        p()

    p("## 4. Recorridos, requisitos y criterios de aceptación")
    p()
    p("El orden es el orden de entrega. El primero es el esqueleto: recorre el camino feliz de punta a punta.")
    p()
    for i, r in enumerate(d.get("recorridos", [])):
        extra = " · 1ª entrega" if i == 0 else ""
        p("### %s: %s (%s%s)" % (r["id"], r["nombre"], r.get("estado", "pendiente"), extra))
        if r.get("objetivo"):
            p()
            p(r["objetivo"])
        p()
        for q in r.get("requisitos", []):
            extras = []
            if q.get("regla"):
                extras.append("regla %s" % q["regla"])
            if q.get("origen"):
                extras.append("origen: %s" % q["origen"])
            implementacion = q.get("implementacion") or {}
            if implementacion.get("estado"):
                extras.append("código actual: %s" % implementacion["estado"])
            p("- **%s**: %s%s" % (
                q["id"],
                q["texto"],
                (" · " + " · ".join(extras)) if extras else "",
            ))
            for evidencia in implementacion.get("evidencias", []):
                if isinstance(evidencia, dict):
                    evidencia = "%s: %s%s" % (
                        evidencia.get("tipo", "evidencia"),
                        evidencia.get("referencia", ""),
                        (" — " + evidencia["detalle"]) if evidencia.get("detalle") else "",
                    )
                p("  - Evidencia: %s" % evidencia)
            for prueba in implementacion.get("pruebas", []):
                p("  - Prueba: %s" % prueba)
        p()
        for cr in r.get("criterios", []):
            cubre = (" · cubre %s" % cr["cubre"]) if cr.get("cubre") else ""
            p("- **%s**: Dado %s / Cuando %s / Entonces %s%s" % (
                cr["id"], cr["dado"], cr["cuando"], cr["entonces"], cubre,
            ))
        p()
    if not d.get("recorridos"):
        ausencia("recorridos")
        p()

    if d.get("episodios"):
        p("### Episodios reales que sustentan los requisitos")
        p()
        for e in d["episodios"]:
            refs = (" [%s]" % ", ".join(e["refs"])) if e.get("refs") else ""
            p("- %s%s" % (e["texto"], refs))
        p()

    p("## 5. Reglas de negocio")
    p()
    for g in d.get("reglas", []):
        p("### %s: %s" % (g["id"], g["nombre"]))
        p()
        if g.get("texto"):
            p(g["texto"])
            p()
        if g.get("tabla"):
            tabla_md(g["tabla"]["columnas"], g["tabla"]["filas"])
    if not d.get("reglas"):
        ausencia("reglas", "(Ninguna registrada.)")
        p()

    p("## 6. Estados")
    p()
    def accion_txt(a):
        if isinstance(a, str):
            return a
        out = a["accion"]
        if a.get("quien"):
            out += " (%s)" % a["quien"]
        if a.get("pasa_a"):
            out += " → pasa a '%s'" % a["pasa_a"]
        return out

    for e in d.get("estados", []):
        p("### %s" % e["entidad"])
        p()
        tabla_md(["Estado", "Qué se puede hacer (quién, y a qué estado pasa)"],
                 [[x["nombre"], " · ".join(accion_txt(a) for a in x.get("acciones", []))] for x in e["estados"]])
    if not d.get("estados"):
        ausencia("estados")
        p()

    p("## 7. Datos e integraciones")
    p()
    if d.get("datos"):
        tabla_md(["Cosa", "Qué se guarda", "De dónde viene"],
                 [[x["cosa"], ", ".join(x.get("guarda", [])), x.get("origen", "")] for x in d["datos"]])
    if d.get("volumen"):
        p("Números del negocio:")
        p()
        tabla_md(["Qué", "Cuánto"], [[v["que"], v["cuanto"]] for v in d["volumen"]])
    for x in d.get("integraciones", []):
        p("- Habla con **%s**%s" % (x["con"], (": %s" % x["para"]) if x.get("para") else ""))
    if not d.get("datos") and not d.get("integraciones"):
        if "datos" in no_aplican and "integraciones" in no_aplican:
            p("(No aplica a este proyecto.)")
        else:
            p("(Pendiente.)")
    p()

    p("## 8. Superficie de uso")
    p()
    sup = d.get("superficie") or {}
    for pt in sup.get("puntos", []):
        p("### %s" % pt["nombre"])
        p()
        tabla_md(["Campo", "Valor"], [
            ["Quién entra", ", ".join(pt.get("quien", []))],
            ["Por dónde llega", pt.get("llega", "")],
            ["Cuándo lo usa", pt.get("cuando", "")],
            ["Qué ve nada más entrar", pt.get("ve", "")],
            ["Qué puede hacer", " · ".join(pt.get("puede", []))],
            ["Qué NO debe poder jamás", " · ".join(
                texto_nunca(x) for x in pt.get("nunca", [])
            )],
        ])
    perm = sup.get("permisos")
    if perm:
        p("### Matriz de permisos")
        p()
        filas_permisos = [
            [r["rol"]] + ["✓" if a in r.get("permitidas", []) else "" for a in perm["acciones"]]
            for r in perm.get("roles", [])
        ] + [
            ["grupo: " + g["grupo"]] + ["✓" if a in g.get("permitidas", []) else "" for a in perm["acciones"]]
            for g in perm.get("grupos", [])
        ]
        tabla_md([""] + perm["acciones"], filas_permisos)
        if perm.get("restricciones"):
            p("### Restricciones de permisos")
            p()
            tabla_md(
                ["ID", "Sujeto", "Acción", "Recurso", "Alcance", "Condición", "Promesa", "Prueba"],
                [
                    [
                        x["id"],
                        ("rol: " + x["rol"]) if x.get("rol") else ("grupo: " + x["grupo"]),
                        x["accion"], x["recurso"],
                        x.get("alcance", ""), x.get("condicion", ""),
                        x["requisito"], x["criterio"],
                    ]
                    for x in perm["restricciones"]
                ],
            )
    if sup.get("avisos"):
        p("### Avisos")
        p()
        tabla_md(["Quién se entera", "De qué", "Por dónde", "Cuándo"],
                 [[a["quien"], a["que"], a.get("canal", ""), a.get("cuando", "")] for a in sup["avisos"]])
    if sup.get("condiciones"):
        p("### Condiciones de uso")
        p()
        for x in sup["condiciones"]:
            p("- %s" % x)
        p()
    if not sup:
        ausencia("superficie")
        p()

    if d.get("pruebas_e2e"):
        p("### Pruebas E2E seleccionadas")
        p()
        for prueba in d["pruebas_e2e"]:
            p("- **%s** · criterios: %s · personas: %s · fronteras: %s" % (
                prueba["id"],
                ", ".join(prueba["criterios"]),
                ", ".join(prueba["personas"]),
                ", ".join(prueba["fronteras"]),
            ))
        p()

    p("## 9. Calidad y límites")
    p()
    for q in d.get("calidad", []):
        p("- **%s**: %s" % (q["id"], q["criterio"]))
    if not d.get("calidad"):
        ausencia("calidad")
    p()

    p("## 10. Fuera de alcance")
    p()
    for x in d.get("fuera", []):
        p("- %s" % x)
    if not d.get("fuera"):
        ausencia("fuera")
    p()

    p("## 11. Preguntas abiertas")
    p()
    p("Buzón del constructor: sus dudas se apuntan aquí, nunca se responden de palabra.")
    p()
    for x in d.get("preguntas", []):
        p("- %s" % x)
    if not d.get("preguntas"):
        p("- (Ninguna por ahora.)")
    p()

    with open(salida, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("Spec generado: %s (%d líneas)" % (salida, len(L)))


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        sys.exit("planos.json no respeta el esquema: falta el campo %s en algún "
                 "bloque. Valida contra visor/esquema.json y reintenta." % e)
