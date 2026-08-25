#!/usr/bin/env python3
"""Guardián de salidas: un bloqueo que no dice cómo salir es un defecto, no un mensaje.

El método ES un agente conduciendo catorce scripts. Cuando uno de ellos rechaza y no nombra
la continuación, el agente gasta un turno entero adivinando y, en el peor caso, se inventa un
rodeo que salta la puerta que acababa de cerrarse. La regla 12 exige evidencia y la 16 regula
el chat, pero hasta ahora nada exigía que un RECHAZO nombre su salida.

Este guardián recorre con `ast` todos los puntos de rechazo de los scripts del método y exige
que cada mensaje cumpla UNA de tres cosas:

  1. **Nombra un comando ejecutable.** Lo normal.
  2. **Lleva al lado un marcador de vocabulario CERRADO** explicando por qué no puede existir
     tal comando:  `salida:por-diseño FORMA: motivo`, con FORMA en
       - `conocimiento-del-operador` — solo la persona sabe el dato que falta
       - `accion-del-mundo`          — hay que hacer algo fuera de la máquina
       - `autoridad-humana`          — hace falta una decisión que ningún comando puede tomar
  3. **Está congelado en la línea base**, que SOLO PUEDE ENCOGER.

Por qué un trinquete y no «arréglalos todos»: exigir que la lista llegue a cero para que el
guardián pueda existir significa que el guardián no existe nunca. Congelarla y prohibir que
crezca es la parte que se paga sola.

Dos detalles de diseño que NO son accidentales:

  - La línea base se indexa por (fichero, mensaje), **jamás por línea**. Editar código más
    arriba no la mueve; pero cambiar el texto de un rechazo reabre la pregunta, que es justo
    el momento en que ese mensaje le debe una salida al operador.
  - Una entrada de la línea base que ya no casa con nada es **FAIL, no nota**. Puede significar
    que se arregló (y la lista encoge, que es la gracia) o que se movió a una forma que el
    analizador no ve (y se perdió cobertura sin que nadie lo decidiera). Desde fuera son
    indistinguibles, así que se para y lo decide una persona.

Uso: python3 docs/00-metodo/scripts/lint_salidas.py [--detalle] [--congelar]
"""

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

# Windows: en cuanto la salida va a un PIPE —la CI, cualquier harness de agente— el encoding
# pasa a ser el local (cp1252) y un `ñ` o un `·` mata el script con UnicodeEncodeError. Es el
# camino normal, no una consola rara: se fuerza UTF-8 antes de imprimir nada.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

FORMAS = ("conocimiento-del-operador", "accion-del-mundo", "autoridad-humana")
MARCADOR = re.compile(r"salida:por-dise(?:ñ|n)o\s+(" + "|".join(FORMAS) + r")\s*:\s*(.+)")

# Emisores PRIMITIVOS: lo único que de verdad escribe en la terminal. Todo lo demás —`err`,
# `fail`, `linea`…— se descubre por módulo, en cascada: es la única forma de no cablear los
# nombres que hoy usa cada script y que el guardián siga valiendo cuando cambien.
EMISORES = {"print", "write", "exit"}

# Qué hace que un mensaje sea un RECHAZO y no información. Deliberadamente estrecho: es
# preferible que se escape un rechazo raro a inundar de falsos positivos y que nadie mire.
BLOQUEO = re.compile(
    r"\bFAIL\b|BLOQUEAD|PROHIBIDO|\bno puedo\b|\bimposible\b"
    r"|\bse bloquea\b|\brechaz", re.IGNORECASE)

# Un WARN no bloquea: avisa y sigue. Y un mensaje que empieza por OK tampoco, aunque por dentro
# diga «no hay». Contarlos infla el inventario con cosas que no cuestan un turno a nadie.
# Un rótulo `== … ==` tampoco: es el título de un informe, nunca un veredicto. Sin esta pieza,
# el propio encabezado de este guardián —«N puntos de RECHAZO en M scripts»— entraba en su
# inventario como bloqueo mudo, y el guardián se suspendía a sí mismo (R10).
NO_BLOQUEA = re.compile(r"^\s*(OK\b|WARN\b|==)", re.IGNORECASE | re.MULTILINE)

# Qué cuenta como «nombra un comando». Un verbo con su objeto: `python3 x.py …`, `git …`.
# Una palabra suelta como «despachar» NO cuenta: el operador no puede pegarla en su terminal.
# El «…» cuenta como principio de argumento: los mensajes reales son f-strings y la ruta del
# script viene de una variable, así que el texto estático es `python3 … nueva <tipo> …`. Sin
# esta pieza el analizador daba 0 % en banda, que es falso: el operador SÍ ve el comando.
COMANDO = re.compile(
    r"(?:^|[\s`'\"(])(?:python3?|py|git|gh|pytest|npm|npx|make|bash|sh|pip3?|docker|node)\s+[-\w./…]",
    re.MULTILINE)


def texto_de(nodo):
    """El texto estático de un literal o de un f-string, con los huecos como '…'."""
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    if isinstance(nodo, ast.JoinedStr):
        trozos = []
        for parte in nodo.values:
            if isinstance(parte, ast.Constant) and isinstance(parte.value, str):
                trozos.append(parte.value)
            else:
                trozos.append("…")
        return "".join(trozos)
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add):
        # Una concatenación con una variable en medio sigue teniendo texto útil: se conserva
        # lo estático y el hueco se marca. Devolver None aquí perdía rechazos enteros.
        izq, der = texto_de(nodo.left), texto_de(nodo.right)
        if izq is None and der is None:
            return None
        return (izq or "…") + (der or "…")
    return None


def nombre_llamada(nodo):
    f = nodo.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def clave(fichero, mensaje):
    """Índice de la línea base: (fichero, mensaje). Nunca la línea."""
    normalizado = re.sub(r"\s+", " ", mensaje).strip()
    huella = hashlib.sha256(normalizado.encode("utf-8")).hexdigest()[:16]
    return f"{fichero}::{huella}"


def emisores_indirectos(arbol, max_sentencias=5):
    """Descubre, por módulo, las dos capas de reporte que hay entre un rechazo y la terminal.

    Es la junta que se escapaba, y tiene DOS piezas, no una:

      - **conductos**: funciones pequeñas que reenvían un parámetro a la terminal.
        `def err(msg): ... print(msg, file=sys.stderr) ...` — no estampan nada, pero por ahí
        sale el texto, así que una llamada a `err` es una emisión.
      - **marcadores**: conductos que además ESTAMPAN la marca de bloqueo sobre un parámetro.
        `def fail(msg): err(f"  FAIL {msg}")`. Una llamada a `fail` ES un rechazo aunque su
        argumento no lleve la palabra FAIL: la pone la imprenta.
      - **atenuadores**: la simétrica, y por eso está aquí. `def ok(msg): print(f"  OK   {msg}")`
        estampa un OK igual que `fail` estampa un FAIL, así que `ok("no hay rechazos mudos")`
        NO es un bloqueo aunque su argumento diga «rechazo». Sin esta pieza, la línea del
        propio enganche en `lint_metodo.py` entraba en el inventario como rechazo mudo.

    Se descubre en cascada hasta punto fijo porque encadenan: `fail` → `err` → `print`. Con
    una sola pasada, `fail` —el que usan de verdad los rechazos— quedaba fuera, y unidad.py,
    el script con más puertas del método, salía con CERO rechazos detectados.

    Nada de esto está cableado a los nombres de hoy: si mañana el ayudante se llama `abortar`,
    el guardián lo encuentra igual.
    """
    conductos, marcadores, atenuadores = set(), set(), set()
    for _ronda in range(6):
        antes = (len(conductos), len(marcadores), len(atenuadores))
        emisores = EMISORES | conductos
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if len(nodo.body) > max_sentencias:
                continue
            parametros = {a.arg for a in nodo.args.args}
            if not parametros:
                continue
            for hijo in ast.walk(nodo):
                if not (isinstance(hijo, ast.Call) and nombre_llamada(hijo) in emisores):
                    continue
                for arg in hijo.args:
                    if not any(isinstance(n, ast.Name) and n.id in parametros
                               for n in ast.walk(arg)):
                        continue
                    conductos.add(nodo.name)
                    t = texto_de(arg)
                    if t and NO_BLOQUEA.match(t):
                        atenuadores.add(nodo.name)
                    elif t and BLOQUEO.search(t):
                        marcadores.add(nodo.name)
        if (len(conductos), len(marcadores), len(atenuadores)) == antes:
            break
    return conductos, marcadores, atenuadores


def _sin_bajar_a_bloques(sentencia):
    """Recorre una sentencia SIN entrar en cuerpos anidados.

    `ast.walk` sí entra, y eso contaba dos veces cada rechazo: una al ver la sentencia dentro
    de su propio bloque y otra al ver la función o el `if` que la contiene desde el bloque de
    fuera. El resultado eran rechazos duplicados con dos números de línea distintos.
    """
    pila = [sentencia]
    while pila:
        nodo = pila.pop()
        yield nodo
        for campo, valor in ast.iter_fields(nodo):
            if campo in ("body", "orelse", "finalbody", "handlers"):
                continue
            if isinstance(valor, list):
                pila.extend(v for v in valor if isinstance(v, ast.AST))
            elif isinstance(valor, ast.AST):
                pila.append(valor)


def _emisiones_de(sentencia, emisores):
    """Los textos que una sentencia emite, si es una llamada a un emisor."""
    textos = []
    for nodo in _sin_bajar_a_bloques(sentencia):
        if not isinstance(nodo, ast.Call):
            continue
        nombre = nombre_llamada(nodo)
        if nombre not in emisores:
            continue
        for arg in nodo.args:
            t = texto_de(arg)
            if t:
                textos.append((nombre, t))
                break
    return textos


def _bloques(nodo):
    """Todas las listas de sentencias del árbol: cada `body`, `orelse`, `finalbody`."""
    for hijo in ast.walk(nodo):
        for campo in ("body", "orelse", "finalbody"):
            cuerpo = getattr(hijo, campo, None)
            if isinstance(cuerpo, list) and cuerpo and isinstance(cuerpo[0], ast.stmt):
                yield cuerpo


def rechazos_de(ruta, raiz):
    """Los puntos de rechazo de un fichero.

    Un punto de rechazo NO es un literal suelto, y tampoco es «todo lo que emite un fichero».
    Es un CORRO: sentencias CONSECUTIVAS del MISMO bloque que emiten texto, de las que al menos
    una bloquea. Dos cosas se aprendieron midiendo, y las dos cambian el número:

      - Agrupar por bloque, no por cercanía de líneas. El patrón real es
        `err("FAIL …")` seguido de `err("  Créala primero: python3 …")`: separados parecen un
        bloqueo mudo más información suelta; juntos se ve que el rechazo SÍ nombra su salida.
        Pero agrupar por «líneas cercanas» fundía en uno los rechazos de ramas distintas de un
        `if`, y hundía el recuento a 36.
      - Contar las llamadas a los AYUDANTES de bloqueo. Casi ningún script escribe «FAIL» donde
        rechaza: escribe `fail("la unidad ya está mergeada")` y es `def fail` quien pone el
        FAIL. Mirando solo literales, la mayoría de los rechazos del método era invisible.
    """
    fuente = ruta.read_text(encoding="utf-8", errors="replace")
    lineas = fuente.splitlines()
    try:
        arbol = ast.parse(fuente, filename=str(ruta))
    except SyntaxError as e:
        return None, f"{ruta}: no se puede analizar ({e})"
    # La clave es el NOMBRE del fichero, no su ruta: el mismo script vive en
    # `plantilla/docs/00-metodo/scripts/` en la herramienta y en `docs/00-metodo/scripts/` en
    # cada workspace. Indexar por ruta relativa haría que la línea base congelada aquí saliera
    # entera huérfana allí, y el trinquete no viajaría.
    rel = ruta.name
    del raiz  # se conserva en la firma: el rastro de qué se descartó es parte de la decisión

    conductos, marcadores, atenuadores = emisores_indirectos(arbol)
    emisores = EMISORES | conductos

    # El cuerpo del ayudante NO es un punto de rechazo: es la imprenta. `def fail(msg):
    #     print(f"  FAIL {msg}")` aparecía como un rechazo mudo en cada script, y no lo es.
    lineas_ayudantes = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name in conductos:
            fin = max((getattr(h, "lineno", nodo.lineno) for h in ast.walk(nodo)),
                      default=nodo.lineno)
            lineas_ayudantes.update(range(nodo.lineno, fin + 1))

    encontrados = []

    def cerrar(corro):
        if not corro:
            return
        textos = []
        for nombre, t, _linea in corro:
            # La marca la pone el ayudante, no quien lo llama: se antepone para que el
            # corro se reconozca como rechazo. Y la simétrica: lo que sale por `ok()` lleva
            # su OK delante aunque el texto hable de fallos.
            if nombre in atenuadores:
                t = "OK " + t
            elif nombre in marcadores and not BLOQUEO.search(t):
                t = "FAIL " + t
            textos.append(t)
        texto = "\n".join(textos)
        if not BLOQUEO.search(texto):
            return
        # Solo cuenta si hay una línea que bloquea de verdad, no un OK/WARN que de paso
        # menciona un fallo.
        bloqueantes = [t for t in textos if BLOQUEO.search(t) and not NO_BLOQUEA.match(t)]
        if not bloqueantes:
            return
        inicio = corro[0][2]
        if inicio in lineas_ayudantes:
            return
        fin = corro[-1][2]
        encontrados.append({
            "fichero": rel,
            "linea": inicio,
            "mensaje": bloqueantes[0],
            "corro": texto,
            "ventana": "\n".join(lineas[max(0, inicio - 4):fin + 1]),
        })

    for cuerpo in _bloques(arbol):
        corro = []
        for sentencia in cuerpo:
            textos = _emisiones_de(sentencia, emisores)
            if textos:
                corro.extend((n, t, sentencia.lineno) for n, t in textos)
            else:
                # Un `return`, un `sys.exit` o un `raise` NO rompen el corro: son justo el
                # final del rechazo. Cualquier otra sentencia sí lo rompe.
                if not isinstance(sentencia, (ast.Return, ast.Raise, ast.Pass,
                                              ast.Continue, ast.Break)):
                    cerrar(corro)
                    corro = []
        cerrar(corro)

    # Un mismo corro puede verse dos veces si su bloque está anidado; se deduplica por sitio.
    unicos, vistos = [], set()
    for r in encontrados:
        k = (r["fichero"], r["linea"], r["mensaje"])
        if k not in vistos:
            vistos.add(k)
            unicos.append(r)
    return unicos, None


def veredicto(r):
    """en_banda | por_diseño | fuera_de_banda — la misma clasificación que usará el registro
    de fricción, para que el reparto no derive en opinión entre dos ejecuciones."""
    if COMANDO.search(r["corro"]):
        return "en_banda", None
    m = MARCADOR.search(r["ventana"])
    if m:
        return "por_diseño", m.group(1)
    return "fuera_de_banda", None


def inventario(carpeta, raiz):
    """El reparto en tres cubos de todos los `*.py` de una carpeta, y los que no se pudieron
    analizar. Devuelve (cubos, errores); cada rechazo lleva ya su veredicto y su clave."""
    cubos = {"en_banda": [], "por_diseño": [], "fuera_de_banda": []}
    errores = []
    for fichero in sorted(Path(carpeta).glob("*.py")):
        encontrados, error = rechazos_de(fichero, raiz)
        if error:
            errores.append(error)
            continue
        for r in encontrados:
            v, forma = veredicto(r)
            r["veredicto"], r["forma"] = v, forma
            r["clave"] = clave(r["fichero"], r["mensaje"])
            cubos[v].append(r)
    return cubos, errores


def congelar(cubos, ruta_base):
    entradas = {r["clave"]: {"fichero": r["fichero"],
                             "mensaje": re.sub(r"\s+", " ", r["mensaje"]).strip()[:200]}
                for r in cubos["fuera_de_banda"]}
    ruta_base.parent.mkdir(parents=True, exist_ok=True)
    ruta_base.write_text(json.dumps({
        "_porque": "Rechazos que hoy no nombran su salida. Esta lista SOLO PUEDE ENCOGER: "
                   "lint_salidas.py falla si crece, y también si una entrada deja de casar.",
        "entradas": dict(sorted(entradas.items())),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return entradas


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scripts", default="docs/00-metodo/scripts",
                   help="carpeta de scripts a vigilar")
    # Sin `--base`, la línea base es la HERMANA de la carpeta de scripts, no una ruta fija:
    # el mismo árbol se mira desde el workspace (`docs/00-metodo/scripts`) y desde la
    # herramienta (`plantilla/docs/00-metodo/scripts`). Con una ruta fija, pasar solo
    # `--scripts plantilla/...` inventariaba la herramienta y buscaba la línea base del
    # workspace: FAIL «no existe la línea base», que es un rechazo que miente sobre su causa.
    p.add_argument("--base", default=None,
                   help="línea base congelada (por defecto, junto a la carpeta de scripts)")
    p.add_argument("--congelar", action="store_true",
                   help="reescribe la línea base con lo que hay HOY. Solo la primera vez, o "
                        "cuando una persona decide adoptar un encogimiento.")
    p.add_argument("--detalle", action="store_true", help="lista los rechazos fuera de banda")
    args = p.parse_args()

    yo = Path(__file__).name
    raiz = Path.cwd()
    carpeta = Path(args.scripts)
    if not carpeta.is_dir():
        print(f"FAIL no encuentro los scripts en {carpeta}")
        print(f"     salida: ejecútalo desde la raíz del workspace, o pasa "
              f"`python3 {yo} --scripts RUTA`.")
        return 1

    cubos, errores = inventario(carpeta, raiz)
    todos = [r for cubo in cubos.values() for r in cubo]

    ruta_base = Path(args.base) if args.base else carpeta.parent / "salidas-baseline.json"
    if args.congelar:
        entradas = congelar(cubos, ruta_base)
        print(f"OK   línea base congelada con {len(entradas)} rechazos en {ruta_base}")
        return 0

    if not ruta_base.is_file():
        print(f"FAIL no existe la línea base {ruta_base}")
        print(f"     salida: créala una vez con  python3 {yo} --congelar")
        return 1
    base = json.loads(ruta_base.read_text(encoding="utf-8")).get("entradas", {})

    nuevos = [r for r in cubos["fuera_de_banda"] if r["clave"] not in base]
    presentes = {r["clave"] for r in cubos["fuera_de_banda"]}
    huerfanas = [k for k in base if k not in presentes]

    total = len(todos)
    scripts = len(list(carpeta.glob("*.py")))
    print(f"== Guardián de salidas · {total} puntos de rechazo en {scripts} scripts ==")
    print(f"   en banda (nombran un comando)   {len(cubos['en_banda']):4d}  "
          f"{100 * len(cubos['en_banda']) / total if total else 0:.0f} %")
    print(f"   por diseño (marcador explícito) {len(cubos['por_diseño']):4d}")
    # Sitios y mensajes NO son lo mismo, y confundirlos hace que el trinquete parezca roto:
    # el mismo texto de rechazo repetido en cinco sitios es UN mensaje que arreglar, y la
    # línea base —indexada por (fichero, mensaje)— lo cuenta una vez.
    print(f"   fuera de banda                  {len(cubos['fuera_de_banda']):4d} sitios · "
          f"{len(presentes)} mensajes distintos "
          f"({len(base) - len(huerfanas)} congelados en la línea base)")
    for e in errores:
        print(f"   WARN {e}")

    if args.detalle:
        for r in sorted(cubos["fuera_de_banda"], key=lambda x: (x["fichero"], x["linea"]))[:200]:
            marca = " " if r["clave"] in base else "+"
            print(f"   {marca} {r['fichero']}:{r['linea']}  "
                  f"{re.sub(chr(10), ' / ', r['mensaje'])[:110]}")

    fallos = 0
    if nuevos:
        fallos += 1
        print()
        print(f"FAIL {len(nuevos)} rechazo(s) NUEVOS sin salida nombrada. La línea base no crece.")
        # Las dos salidas van PEGADAS al FAIL, antes del listado: el guardián se aplica su
        # propia regla (R10) y un corro se corta en cuanto aparece un `for`.
        print(f"     salida: nombra el comando en el mensaje —`err(\"  Arréglalo: python3 …\")`—")
        print(f"             o pon encima el marcador "
              f"`# salida:por-diseño {FORMAS[0]}: motivo`.")
        for r in nuevos[:20]:
            print(f"     {r['fichero']}:{r['linea']}  "
                  f"{re.sub(chr(10), ' / ', r['mensaje'])[:100]}")
    if huerfanas:
        fallos += 1
        print()
        print(f"FAIL {len(huerfanas)} entrada(s) de la línea base ya no casan con ningún rechazo.")
        print(f"     O se arreglaron (y la lista debe encoger) o se movieron a una forma que no")
        print(f"     veo (y se perdió cobertura). Desde fuera son indistinguibles: decídelo tú.")
        print(f"     salida: si están arregladas, adopta el encogimiento con  python3 {yo} "
              f"--congelar")
        for k in huerfanas[:20]:
            print(f"     {base[k]['fichero']}: {base[k]['mensaje'][:100]}")

    if not fallos:
        print()
        print("OK   ningún rechazo nuevo sin salida, y la línea base sigue casando entera.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
