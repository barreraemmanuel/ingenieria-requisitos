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
  5. Lo aprendido se rellena de memoria al cerrar, o no se rellena: la sección
     `## Aprendizajes` de `hallazgos.md` tiene que traer, de quien construyó y de quien
     revisó, 1-5 frases o un `ninguno` explícito. Un hallazgos.md sin esos bloques es
     anterior a la 071 y no se re-exige.
  6. La firma del revisor lleva fecha pero no dice QUÉ se revisó: `revisado_patch_id` en
     blanco junto a un `revisado:` con fecha. Una firma sin el ancla del contenido vale
     para cualquier cosa, que es lo mismo que no valer para nada (068). Como en el punto 5,
     ausencia ≠ vacío: sin la clave en la cabecera, la unidad nació antes y no se re-exige.

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
FECHA_EJEMPLO = "2026-08-27"

CABECERA = re.compile(r"```parte-de-cierre[ \t]*\r?\n(.*?)```", re.DOTALL)
VERDICTOS_OK = {"entregada", "verde", "ok", "exito", "éxito"}
VERDICTOS_FALLO = {"fallo", "rojo", "bloqueada", "fail"}

# Lo que R1 exige que traiga la cabecera. Un bloque al que le falta la mitad de las claves no
# es un parte: es la misma prosa de antes dentro de un ```.
CLAVES = ("veredicto", "tests_cmd", "tests_exit", "tests_output", "tests_sha256",
          "build_cmd", "build_exit", "build_output", "build_sha256",
          "requisitos", "plan", "bloqueadores")
# Unidad 071 — la sección `## Aprendizajes`: lo aprendido lo escribe quien lo aprendió, en el
# momento. Se comprueba que esté RELLENA, no que sea buena: `ninguno` explícito vale, y una
# unidad nacida con la plantilla anterior (sin BLOQUES) no se re-exige — ausencia ≠ vacío.
APRENDIZAJES_QUIENES = ("constructor", "revisor")

# Unidad 068 — el ancla de la firma del revisor. La escribe `ejecucion.py` al lanzarlo, y
# aquí solo se comprueba que no se haya borrado dejando la fecha.
ANCLA = "revisado_patch_id"
RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COMANDO_REVISION = ("python3 docs/00-metodo/scripts/ejecucion.py lanzar {nombre} "
                    "--harness claude --rol revisor "
                    "--prompt \"Revisa el diff contra el contrato y firma hallazgos.md\"")

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


def bloque_aprendizajes(texto, quien):
    """El contenido del bloque ```aprendizajes-<quien>```, o None si no está."""
    m = re.search(r"```aprendizajes-" + quien + r"[ \t]*\r?\n(.*?)```", texto, re.DOTALL)
    return None if m is None else m.group(1)


def frases_de(bloque):
    """Las viñetas del bloque que dicen algo. Un `—` no dice nada; `ninguno`, sí."""
    frases = []
    for linea in bloque.splitlines():
        linea = linea.strip()
        if not linea.startswith("-"):
            continue
        contenido = linea[1:].strip()
        if not sin_rellenar(contenido):
            frases.append(contenido)
    return frases


def revisar_aprendizajes(nombre, texto):
    """Lista de (qué no cuadra, cómo se sale) sobre la sección `## Aprendizajes`.

    Vacía si no hay NINGÚN bloque ```aprendizajes-*```: los hallazgos.md nacidos antes de la
    071 no se re-exigen, ni siquiera los que ya traían una sección `## Aprendizajes` en
    prosa (mismo criterio que la 068 — ausencia ≠ sección dejada vacía). En cuanto aparece
    un bloque, tienen que estar los dos y rellenos: el del constructor y el del revisor.
    """
    bloques = {q: bloque_aprendizajes(texto, q) for q in APRENDIZAJES_QUIENES}
    if not any(b is not None for b in bloques.values()):
        # La puerta se ancla en los BLOQUES, no en el título: hay hallazgos.md antiguos con
        # una sección `## Aprendizajes` escrita en prosa, sin bloques (p. ej. la 059), y
        # exigírselos ahora es re-exigir la plantilla nueva a quien nació con la vieja.
        return []
    problemas = []
    for quien in APRENDIZAJES_QUIENES:
        bloque = bloques[quien]
        if bloque is None:
            problemas.append((
                f"{nombre}: la sección ## Aprendizajes no trae el bloque "
                f"```aprendizajes-{quien}```",
                "copia la sección entera de docs/00-metodo/plantillas/hallazgos.md y "
                f"escribe ahí lo que aprendió el {quien}"))
        elif not frases_de(bloque):
            problemas.append((
                f"{nombre}: ```aprendizajes-{quien}``` sigue con el marcador de la plantilla",
                f"escribe 1-5 frases con fecha y quién (`- {FECHA_EJEMPLO} · {quien}: …`) en "
                f"docs/05-trabajo/{nombre}/hallazgos.md, o `ninguno` explícito si de verdad no "
                f"hubo — lo que se rellena de memoria al cerrar es inventado"))
    return problemas


def frontmatter_de(texto):
    """Las claves del frontmatter, con el comentario ya recortado. {} si no trae cabecera.

    Parseo mínimo y deliberadamente tonto: aquí solo se leen escalares de una línea, que es
    todo lo que tiene la cabecera de un `hallazgos.md`. Un `{}` significa «no hay cabecera»,
    y eso nunca se convierte en un FAIL: es un fichero anterior a que la cabecera existiera.
    """
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        return {}
    datos = {}
    for linea in lineas[1:]:
        if linea.strip() == "---":
            break
        encontrado = re.match(r"^(\w+):\s*(.*)$", linea)
        if encontrado:
            datos[encontrado.group(1)] = encontrado.group(2).split("#", 1)[0].strip()
    return datos


def revisar_ancla_de_revision(nombre, texto, texto_spec=""):
    """068/R4-R5 — una firma de revisión sin el contenido que revisó no es una firma.

    Tres estados, y solo uno es un fallo:

      · la clave NO está en la cabecera → la unidad nació antes de la 068 y no se re-exige
        (mismo criterio que los aprendizajes de la 071: ausencia ≠ vacío);
      · la clave está y `revisado:` todavía no es una fecha → nadie ha firmado; el campo
        llega así de fábrica y no hay nada que anclar;
      · la clave está VACÍA (o con el `no` de la plantilla) junto a una fecha real → la
        huella se borró y quedó la fecha. Eso es exactamente la firma tecleada a mano que
        cazó ADR-029, y es lo que se deniega.

    Y una excepción con nombre: la unidad `--documental` no tiene rama ni worktree por
    diseño (regla 2), así que su revisión NO pasa por el launcher y nadie puede sellarle el
    ancla. Exigírsela sería pedir una evidencia que su propio carril le prohíbe generar —
    el mismo motivo por el que `unidad.py cerrar` la exime del recibo del control plane
    (034/R3). La excepción no se calla: vive aquí, con su porqué.
    """
    if re.search(r"(?m)^ejecucion:\s*documental\b", texto_spec):
        return []
    fm = frontmatter_de(texto)
    if ANCLA not in fm:
        return []
    if not RE_FECHA.match((fm.get("revisado") or "").strip()):
        return []
    valor = fm[ANCLA].strip()
    if valor and valor.lower() != "no" and not sin_rellenar(valor):
        return []
    return [(
        f"{nombre}: la cabecera de hallazgos.md tiene `revisado:` con fecha y "
        f"`{ANCLA}` sin rellenar — la firma no dice QUÉ contenido se revisó, así que "
        f"valdría igual para la rama de hoy que para la de dentro de tres commits",
        f"no la escribas a mano (sería otra firma inventada): vuelve a lanzar la revisión, "
        f"que sella el ancla sola —  {COMANDO_REVISION.format(nombre=nombre)}")]


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

    texto_hallazgos = hallazgos.read_text(encoding="utf-8", errors="replace")
    datos = leer_cabecera(texto_hallazgos)
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

    # (5) 071 — lo aprendido, escrito por quien lo aprendió y en el momento.
    problemas += revisar_aprendizajes(nombre, texto_hallazgos)
    # (6) 068 — la firma del revisor, pegada al contenido que revisó.
    problemas += revisar_ancla_de_revision(
        nombre, texto_hallazgos, spec.read_text(encoding="utf-8", errors="replace"))
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
            # La remediación concreta viaja en `salida` (una variable), así que el texto
            # ESTÁTICO de este rechazo no nombraba ningún comando: para el guardián de
            # salidas (049) era un rechazo mudo. El comando que cierra el corro —volver a
            # pasar esta misma puerta— se escribe aquí literalmente, y quien conduce lo ve
            # sin adivinar.
            print(f"          {SALIDA} {salida}"
                  f"  ·  y vuelve a pasarlo:  python3 docs/00-metodo/scripts/lint_cierre.py")
    print()
    if total:
        print(f"{total} problema(s): el parte de cierre no cuadra con su evidencia.")
        return 1
    print("OK   los partes de cierre cuadran con la evidencia que citan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
