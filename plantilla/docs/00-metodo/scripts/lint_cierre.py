#!/usr/bin/env python3
"""lint_cierre.py — que el «47/47 verdes» tenga que cuadrar con algo que se pueda volver a mirar.

Todo el método descansa en que lo escrito al cerrar una unidad sea verdad. La regla 12 dice
«evidencia, no afirmación», y el cierre exige verificación, revisión firmada y OK del usuario.
Pero el parte de cierre es prosa que escribe el mismo agente que hizo (o dirigió) el trabajo, y
nada comprobaba que esa prosa concordara con la evidencia que dice tener. Un «47/47 verdes» y un
«plan completado» se creían porque estaban escritos. La regla existía; el guardián no.

Cuatro formas de mentir, y las cuatro se deniegan:

  1. Un código de salida distinto de cero conviviendo con un veredicto de éxito.
  2. El veredicto declara fallo pero toda la evidencia está en verde. Es la forma en que un
     agente se cubre sin haber trabajado: es tan mentira como la anterior, y casi nadie la
     comprueba.
  3. Los números declarados (requisitos cubiertos, casillas del plan) no coinciden con el
     conteo real hecho sobre `especificacion.md`, para que nadie escriba un «6/6» inventado.
     Es a propósito el MISMO fichero que el agente tiene delante mientras trabaja: si marca
     las casillas según se hacen, el número cuadra solo, y solo se descuadra cuando se
     rellena de memoria.
  4. Se cita una ruta de `.runtime/` que no existe, o un hash que no corresponde al fichero.

Ni una comprobación más: juzgar si los tests son BUENOS no es de aquí, y reescribir partes
antiguos tampoco — la cabecera se exige a partir de la unidad que trajo este script.

Uso:
  python3 docs/00-metodo/scripts/lint_cierre.py                 todas las unidades activas
  python3 docs/00-metodo/scripts/lint_cierre.py 045-mi-slug     solo esa

Solo stdlib. Exit 0 si los partes cuadran; exit 1 con el comando que resuelve cada fallo.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

# Windows: en cuanto la salida va a un PIPE el encoding pasa a ser cp1252 y un `·` mata el
# script. Mismo cinturón que unidad.py, por el mismo motivo.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parents[3]
SALIDA = "salida:"

CABECERA = re.compile(r"```parte-de-cierre[ \t]*\r?\n(.*?)```", re.DOTALL)
VERDICTOS_OK = {"entregada", "verde", "ok", "exito", "éxito"}
VERDICTOS_FALLO = {"fallo", "rojo", "bloqueada", "fail"}

# Lo que R1 exige que traiga la cabecera. Un bloque al que le falta la mitad de las claves no
# es un parte: es la misma prosa de antes dentro de un ```.
CLAVES = ("veredicto", "tests_cmd", "tests_exit", "tests_output", "tests_sha256",
          "build_cmd", "build_exit", "build_output", "build_sha256",
          "requisitos", "plan", "bloqueadores")
# Los marcadores con que la plantilla llega: dejarlos tal cual es no haber rellenado nada.
MARCADORES = {"", "—", "-", "--", "...", "…", "n/a", "na", "pendiente", "tbd", "xxx",
              "nnn-slug", "?"}


def leer_cabecera(texto):
    """El bloque ```parte-de-cierre``` como diccionario, o None si no está."""
    m = CABECERA.search(texto)
    if not m:
        return None
    datos = {}
    for linea in m.group(1).splitlines():
        if ":" not in linea or linea.strip().startswith("#"):
            continue
        clave, _, valor = linea.partition(":")
        # Los comentarios de la plantilla van detrás del valor: `tests_exit: 0   # verde`.
        datos[clave.strip()] = valor.split("#")[0].strip()
    return datos


def sin_rellenar(valor):
    return valor.strip().lower() in MARCADORES or valor.strip().startswith("<")


def entero(valor):
    try:
        return int(valor.strip())
    except (AttributeError, ValueError):
        return None


def fraccion(valor):
    m = re.match(r"^(\d+)\s*/\s*(\d+)$", (valor or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def contar_reales(spec):
    """Requisitos del contrato y casillas del plan, contados sobre la especificación."""
    texto = spec.read_text(encoding="utf-8", errors="replace")
    requisitos = len(re.findall(r"^\s*-\s+\*\*R\d+\*\*", texto, re.MULTILINE))
    marcadas = len(re.findall(r"^\s*-\s+\[x\]", texto, re.MULTILINE | re.IGNORECASE))
    totales = marcadas + len(re.findall(r"^\s*-\s+\[ \]", texto, re.MULTILINE))
    return requisitos, marcadas, totales


def validar_parte(nombre, spec, hallazgos, raiz):
    """Lista de (qué no cuadra, comando que lo resuelve). Vacía = el parte cuadra.

    Recibe las rutas ya resueltas para que `unidad.py cerrar` pueda llamarlo con las suyas
    —la unidad puede estar en 05-trabajo o ya archivada— sin duplicar la búsqueda.
    """
    if not spec.is_file():
        return [(f"no encuentro la especificación de {nombre}",
                 "crea la unidad con  python3 docs/00-metodo/scripts/unidad.py nueva "
                 "<tipo> <slug> --desde P-ID")]
    if not hallazgos.is_file():
        return [(f"no encuentro el hallazgos.md de {nombre}",
                 "lo crea  unidad.py nueva ; si falta, cópialo de "
                 "docs/00-metodo/plantillas/hallazgos.md")]

    datos = leer_cabecera(hallazgos.read_text(encoding="utf-8", errors="replace"))
    if datos is None:
        return [(f"{nombre}: hallazgos.md no trae el bloque ```parte-de-cierre```",
                 "copia la cabecera de docs/00-metodo/plantillas/hallazgos.md y rellénala "
                 "con lo que ejecutaste de verdad")]

    faltan = [c for c in CLAVES if c not in datos]
    if faltan:
        return [(f"{nombre}: al bloque ```parte-de-cierre``` le faltan claves: "
                 f"{', '.join(faltan)}",
                 "copia la cabecera entera de docs/00-metodo/plantillas/hallazgos.md — un "
                 "bloque a medias es la prosa de siempre dentro de un ```")]
    vacias = [c for c in CLAVES if sin_rellenar(datos[c])]
    if vacias:
        return [(f"{nombre}: la cabecera sigue sin rellenar en: {', '.join(vacias)}",
                 "rellénala con lo que EJECUTASTE (comando, código de salida, ruta de la "
                 "salida en .runtime/ y su  shasum -a 256 ), nunca de memoria")]

    problemas = []
    veredicto = datos["veredicto"].lower()
    salidas = {c: entero(datos[c]) for c in ("tests_exit", "build_exit")}
    conocidos = {c: v for c, v in salidas.items() if v is not None}
    for clave, valor in salidas.items():
        if valor is None:
            problemas.append((
                f"{nombre}: {clave} vale '{datos[clave]}' y eso no es un código de salida",
                f"pon el número que devolvió el comando; lo ves con  {datos.get(clave[:-5] + '_cmd')}"
                f" ; echo $?"))

    # (1) R2 — éxito declarado con un rojo dentro: la mentira clásica.
    rojos = {c: v for c, v in conocidos.items() if v != 0}
    if veredicto in VERDICTOS_OK and rojos:
        detalle = ", ".join(f"{c}={v}" for c, v in sorted(rojos.items()))
        problemas.append((
            f"{nombre}: veredicto '{veredicto}' con código de salida ≠ 0 ({detalle})",
            "arregla el rojo y vuelve a ejecutar el comando declarado, o cambia el "
            "veredicto: no se cierra en verde sobre un comando que falló"))

    # (2) R3 — fallo declarado con todo en verde: cubrirse sin haber trabajado.
    if veredicto in VERDICTOS_FALLO and conocidos and not rojos:
        problemas.append((
            f"{nombre}: veredicto '{veredicto}' pero toda la evidencia está en verde",
            "declara qué falló y con qué comando, o corrige el veredicto: un fallo sin un "
            "rojo que lo sostenga es tan poco comprobable como un verde sin evidencia"))

    # (3) R4 — los números declarados contra el conteo real sobre la especificación.
    reales_req, marcadas, totales = contar_reales(spec)
    ruta_spec = ruta_legible(spec, raiz)
    dec_req = fraccion(datos["requisitos"])
    if dec_req is None:
        problemas.append((
            f"{nombre}: requisitos vale '{datos['requisitos']}' y se espera N/M",
            f"cuenta los `- **Rn** —` de {ruta_spec} y escribe cubiertos/total"))
    elif dec_req[1] != reales_req:
        problemas.append((
            f"{nombre}: declara {dec_req[0]}/{dec_req[1]} requisitos, pero la especificación "
            f"tiene {reales_req}",
            f"cuadra el denominador con los `- **Rn** —` de {ruta_spec}"))

    dec_plan = fraccion(datos["plan"])
    if dec_plan is None:
        problemas.append((
            f"{nombre}: plan vale '{datos['plan']}' y se espera N/M",
            f"cuenta las casillas del plan de {ruta_spec} y escribe marcadas/total"))
    elif dec_plan != (marcadas, totales):
        problemas.append((
            f"{nombre}: declara {dec_plan[0]}/{dec_plan[1]} casillas del plan, pero las "
            f"marcadas de verdad son {marcadas}/{totales}",
            f"marca las casillas de {ruta_spec} según se hacen — rellenarlas después de "
            f"memoria es inventarlas"))

    # (4) R5/R6 — la evidencia citada existe y es la que dice ser.
    for clave in ("tests_output", "build_output"):
        citada = datos[clave].split()[0]
        ruta = (raiz / citada).resolve()
        if not ruta.is_file():
            problemas.append((
                f"{nombre}: {clave} cita {citada} y ese fichero no existe",
                f"vuelca la salida real ahí y cita su ruta: la regla 12 pide referenciarla, "
                f"no pegarla —  {datos[clave[:-7] + '_cmd']} > {citada}"))
            continue
        declarado = datos[clave.replace("_output", "_sha256")].strip()
        real = hashlib.sha256(ruta.read_bytes()).hexdigest()
        if not real.startswith(declarado.lower()):
            problemas.append((
                f"{nombre}: el hash de {citada} no cuadra (declarado {declarado[:16]}…, "
                f"real {real[:16]}…)",
                f"vuelve a calcularlo con  shasum -a 256 {citada}"))
    return problemas


def ruta_legible(ruta, raiz):
    try:
        return ruta.resolve().relative_to(Path(raiz).resolve()).as_posix()
    except ValueError:
        return str(ruta)


def carpeta_de(nombre, raiz):
    trabajo = raiz / "docs/05-trabajo"
    for candidata in (trabajo / nombre, trabajo / "archivo" / nombre):
        if candidata.is_dir():
            return candidata
    return trabajo / nombre


def validar(nombre, raiz):
    carpeta = carpeta_de(nombre, raiz)
    return validar_parte(nombre, carpeta / "especificacion.md", carpeta / "hallazgos.md", raiz)


def activas(raiz):
    trabajo = raiz / "docs/05-trabajo"
    return [c.name for c in sorted(trabajo.glob("[0-9][0-9][0-9]-*"))
            if (c / "hallazgos.md").is_file()]


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("unidad", nargs="?", help="NNN-slug; sin argumento, todas las activas")
    p.add_argument("--raiz", default=str(RAIZ), help="raíz del meta-repo")
    args = p.parse_args()
    raiz = Path(args.raiz).resolve()

    unidades = [args.unidad] if args.unidad else activas(raiz)
    if not unidades:
        print("OK   no hay ninguna unidad activa con parte de cierre que validar.")
        return 0

    print("== Parte de cierre ==\n")
    total = 0
    for nombre in unidades:
        problemas = validar(nombre, raiz)
        total += len(problemas)
        print(f"   {nombre:<44} {'FAIL · ' + str(len(problemas)) if problemas else 'OK'}")
        for que, salida in problemas:
            print(f"     FAIL {que}")
            print(f"          {SALIDA} {salida}")
    print()
    if total:
        print(f"{total} problema(s): el parte de cierre no cuadra con su evidencia.")
        return 1
    print("OK   los partes de cierre cuadran con la evidencia que citan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
