#!/usr/bin/env python3
"""Medidor de coste del método: en qué se va el cupo, medido, no estimado.

Lectura PASIVA, como el canario: no instrumenta nada, no abre red, no llama a ningún
modelo y no escribe en `~/.claude/`. Lee los rollouts que Claude Code YA deja en
`~/.claude/projects/<proyecto>/*.jsonl` y los convierte en tres respuestas con números:

  1. ¿En qué se va el gasto? (entrada nueva · relectura de caché · escritura de caché · salida)
  2. ¿Qué hay dentro de esa relectura? (razonamiento · herramientas · andamiaje · persona)
  3. ¿Cuánto habría ahorrado cortar la sesión cada N turnos?

LO QUE **NO** MIDE, y se dice a propósito (lección de la carpeta `bench` de gentle-ai):
  - No mide reloj de pared: un turno lento y uno caro no son lo mismo.
  - No mide dinero: el precio depende del plan, del tier y del momento; aquí solo hay tokens.
  - No emite una nota compuesta. Una suma ponderada puede subir mientras baja justo la
    dimensión que importa. Cada eje se informa por separado y el juicio lo pone quien lee.

Uso:
    python3 docs/00-metodo/scripts/coste.py                    # el workspace actual
    python3 docs/00-metodo/scripts/coste.py --todos            # toda la máquina
    python3 docs/00-metodo/scripts/coste.py --corte 100        # simula cortar cada 100 turnos
    python3 docs/00-metodo/scripts/coste.py --json RUTA        # vuelca el detalle (línea base)
    python3 docs/00-metodo/scripts/coste.py --linea-base RUTA  # compara contra un volcado

Solo stdlib.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake (unidad 042).
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

COMANDO = "python3 docs/00-metodo/scripts/coste.py"

# Un turno = una petición a la API. `requestId` la identifica: los reintentos y las
# iteraciones internas de una misma petición NO son turnos distintos y se cuentan una vez.
EJES = ("lectura", "escritura", "entrada", "salida")
ETIQUETAS = {
    "lectura": "relectura de caché  (el agente releyendo lo ya dicho)",
    "escritura": "escritura de caché  (lo nuevo que entra al contexto)",
    "entrada": "entrada sin caché                                   ",
    "salida": "salida              (lo que el agente escribe)      ",
}

ORIGENES = ("agente", "herramientas", "sistema", "usuario")
NOMBRES_ORIGEN = {
    "agente": "razonamiento del agente  ",
    "herramientas": "salida de herramientas   ",
    "sistema": "andamiaje del harness    ",
    "usuario": "lo que escribe la gente  ",
}

# El texto que el harness carga ENTERO en cada turno. Su coste es tamaño x turnos: por eso
# se mide aquí y no se opina sobre él.
SIEMPRE_CARGADO = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".claude/personalidad.md")

TRAMOS = ((1, 50), (200, 300), (600, 900))


# --------------------------------------------------------------------------- localizar

def raiz_claude():
    """Dónde escribe Claude Code. La variable de entorno existe para los tests."""
    return Path(os.environ.get("COSTE_CLAUDE_PROJECTS") or (Path.home() / ".claude/projects"))


def normalizar_proyecto(ruta):
    """Nombre de carpeta con el que Claude Code guarda las sesiones de un directorio.

    La misma regla que `canario.py`: cada carácter que no sea alfanumérico pasa a guion.
    No es «cambiar / por -»: una ruta con puntos o guiones bajos se guardaría distinta y
    el medidor no encontraría ni una sesión.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(ruta))


def _variantes(ruta):
    """La ruta tal cual y su forma resuelta: AMBAS ortografías cuentan (bug 024).

    El harness nombra la carpeta con el cwd tal cual lo vio; buscar solo la resuelta pierde
    la sesión cuando hay un symlink por medio (`/var` → `/private/var` en macOS).
    """
    cruda = Path(os.path.abspath(str(ruta)))
    try:
        resuelta = cruda.resolve()
    except OSError:
        resuelta = cruda
    return [cruda] if str(cruda) == str(resuelta) else [cruda, resuelta]


def carpetas_de(raiz, proyecto):
    """Las carpetas de rollouts de este workspace, por cualquiera de sus dos ortografías."""
    encontradas, vistas = [], set()
    for variante in _variantes(proyecto):
        carpeta = Path(raiz) / normalizar_proyecto(variante)
        if carpeta.is_dir() and str(carpeta) not in vistas:
            vistas.add(str(carpeta))
            encontradas.append(carpeta)
    return encontradas


def sesiones(directorios):
    for directorio in directorios:
        for fichero in sorted(Path(directorio).glob("*.jsonl")):
            yield fichero


# --------------------------------------------------------------------------- los ejes

def leer_sesion(fichero):
    """Devuelve (turnos, meta). Un turno: {entrada, lectura, escritura, salida, tokens}."""
    turnos, vistos, modelos, ramas = [], set(), {}, set()
    primera = ultima = None
    try:
        fh = open(fichero, "r", encoding="utf-8", errors="replace")
    except OSError:
        return [], {"fichero": str(fichero), "sesion": Path(fichero).stem}
    with fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            try:
                dato = json.loads(linea)
            except ValueError:
                continue
            if not isinstance(dato, dict) or dato.get("type") != "assistant":
                continue
            rid = dato.get("requestId")
            if rid:
                if rid in vistos:
                    continue
                vistos.add(rid)
            mensaje = dato.get("message") or {}
            uso = mensaje.get("usage") or {}
            if not uso:
                continue
            entrada = int(uso.get("input_tokens") or 0)
            lectura = int(uso.get("cache_read_input_tokens") or 0)
            escritura = int(uso.get("cache_creation_input_tokens") or 0)
            salida = int(uso.get("output_tokens") or 0)
            modelo = mensaje.get("model") or "desconocido"
            modelos[modelo] = modelos.get(modelo, 0) + entrada + lectura + escritura + salida
            marca = dato.get("timestamp")
            if marca:
                primera = primera or marca
                ultima = marca
            if dato.get("gitBranch"):
                ramas.add(dato["gitBranch"])
            turnos.append({
                "entrada": entrada, "lectura": lectura, "escritura": escritura,
                "salida": salida, "tokens": entrada + lectura + escritura + salida,
                "modelo": modelo,
                # Un subagente escribe en el MISMO fichero marcado como sidechain: su gasto
                # es real y cuenta, pero no es un turno de la sesión principal.
                "sidechain": bool(dato.get("isSidechain")),
            })
    meta = {"fichero": str(fichero), "sesion": Path(fichero).stem, "desde": primera,
            "hasta": ultima, "modelos": modelos, "ramas": sorted(ramas)}
    return turnos, meta


# ------------------------------------------------------------------ qué hay en la relectura
#
# `cache_read_input_tokens` dice CUÁNTO se releyó, nunca QUÉ. Para saber qué hay dentro se
# mide lo único observable: el tamaño de cada mensaje y cuántos turnos posteriores lo
# arrastró la sesión. Tamaño x turnos arrastrado es, salvo compactaciones, proporcional a
# su parte de la relectura.
#
# Límite honesto: si el harness compactó, lo anterior al corte deja de arrastrarse y esta
# atribución SOBREESTIMA lo antiguo. Las compactaciones se cuentan y se declaran.

def texto_de(contenido):
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        trozos = []
        for bloque in contenido:
            if not isinstance(bloque, dict):
                trozos.append(str(bloque))
                continue
            for clave in ("text", "thinking", "content", "input"):
                if clave in bloque:
                    trozos.append(texto_de(bloque[clave]))
                    break
        return "".join(trozos)
    if isinstance(contenido, dict):
        return json.dumps(contenido, ensure_ascii=False)
    return ""


def clasificar(dato):
    """De qué origen es el peso que este mensaje mete en el contexto."""
    tipo = dato.get("type")
    if tipo in ("system", "attachment") or dato.get("isMeta"):
        return "sistema"
    if tipo == "assistant":
        return "agente"
    if tipo == "user":
        contenido = (dato.get("message") or {}).get("content")
        # Un `user` cuyo contenido son bloques `tool_result` NO lo escribió la persona: es
        # lo que devolvió una herramienta. Confundirlos es el error que hace parecer que el
        # gasto lo provoca quien escribe en el chat.
        if isinstance(contenido, list):
            for bloque in contenido:
                if isinstance(bloque, dict) and bloque.get("type") == "tool_result":
                    return "herramientas"
        return "usuario"
    return None


def composicion(fichero):
    """Devuelve ({origen: tokens_arrastrados}, compactaciones_vistas)."""
    mensajes, compactaciones = [], 0
    try:
        fh = open(fichero, "r", encoding="utf-8", errors="replace")
    except OSError:
        return {o: 0.0 for o in ORIGENES}, 0
    with fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            try:
                dato = json.loads(linea)
            except ValueError:
                continue
            if not isinstance(dato, dict):
                continue
            if dato.get("subtype") == "compact_boundary" or dato.get("isCompactSummary"):
                compactaciones += 1
            origen = clasificar(dato)
            if not origen:
                continue
            peso = len(texto_de((dato.get("message") or {}).get("content", ""))) if dato.get("message") else 0
            if origen == "sistema" and not peso:
                peso = len(json.dumps(dato.get("attachment", {}), ensure_ascii=False))
            if peso:
                mensajes.append((origen, peso / 4.0, dato.get("type") == "assistant"))
    restantes = sum(1 for _, _, es_turno in mensajes if es_turno)
    acumulado = {o: 0.0 for o in ORIGENES}
    for origen, peso, es_turno in mensajes:
        if es_turno:
            restantes -= 1
        acumulado[origen] += peso * restantes
    return acumulado, compactaciones


# --------------------------------------------------------------------------- el corte

def perfil_por_indice(todas):
    """Coste medio del turno k-ésimo sobre todas las sesiones que llegaron a él.

    Es el modelo que hace falta para simular el corte: al abrir sesión nueva, el turno
    siguiente vuelve a costar lo que cuesta un turno temprano, no lo que costaba el 700.
    """
    suma, cuenta = {}, {}
    for turnos, _ in todas:
        for k, turno in enumerate(turnos, start=1):
            suma[k] = suma.get(k, 0) + turno["tokens"]
            cuenta[k] = cuenta.get(k, 0) + 1
    return {k: suma[k] / cuenta[k] for k in suma}, cuenta


def simular_corte(todas, perfil, corte, coste_retomada):
    """Gasto real vs gasto si cada sesión se hubiera cortado cada `corte` turnos.

    SUPUESTO DECLARADO: tras un corte, el turno k de la sesión nueva cuesta el promedio
    histórico del turno k. Es optimista en un sentido (el trabajo retomado arrastra estado)
    y pesimista en otro (una sesión nueva sobre trabajo hecho va más al grano). Se declara
    en la salida para que nadie lo lea como una promesa.
    """
    if not perfil:
        return 0, 0, 0
    ultimo = perfil[max(perfil)]
    real = simulado = retomadas = 0
    for turnos, _ in todas:
        real += sum(t["tokens"] for t in turnos)
        n, pos = len(turnos), 0
        while pos < n:
            tramo = min(corte, n - pos)
            simulado += sum(perfil.get(k, ultimo) for k in range(1, tramo + 1))
            pos += tramo
            if pos < n:
                retomadas += 1
                simulado += coste_retomada
    return real, simulado, retomadas


# --------------------------------------------------------------------------- salida

def pct(parte, total):
    return 0.0 if not total else 100.0 * parte / total


def formatear_millones(n):
    return f"{n/1_000_000:.1f} M"


def fallo(mensaje, salida, comando):
    """Un fallo NOMBRA el comando que lo resuelve: un fallo mudo cuesta un turno entero."""
    print(f"FAIL {mensaje}")
    print(f"     salida: {salida}")
    print(f"     {comando}")
    return 1


def prosa_siempre_cargada(proyecto):
    """Bytes del texto que entra ENTERO en cada turno (0 si no hay ninguno)."""
    total = 0
    for nombre in SIEMPRE_CARGADO:
        fichero = Path(proyecto) / nombre
        if fichero.is_file():
            total += fichero.stat().st_size
    return total


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--todos", action="store_true",
                   help="todos los proyectos de la máquina, no solo este workspace")
    p.add_argument("--proyecto", default=None, help="workspace a medir (por defecto, el actual)")
    p.add_argument("--corte", type=int, default=250,
                   help="turnos por sesión que simula el corte (0 = no simular)")
    p.add_argument("--coste-retomada", type=int, default=40_000,
                   help="tokens que se pagan al abrir sesión nueva y ponerla al día")
    p.add_argument("--json", default=None, help="vuelca el detalle, para comparar antes/después")
    p.add_argument("--linea-base", default=None, help="compara contra un volcado anterior")
    args = p.parse_args(argv)

    raiz = raiz_claude()
    if not raiz.is_dir():
        return fallo(f"no encuentro los rollouts del harness en {raiz}",
                     "este medidor lee Claude Code; con otro harness, mide con SU registro.",
                     f"{COMANDO} --help")

    proyecto = args.proyecto or os.getcwd()
    if args.todos:
        dirs = [d for d in sorted(raiz.iterdir()) if d.is_dir()]
        ambito = "todos los proyectos de esta máquina"
    else:
        dirs = carpetas_de(raiz, proyecto)
        if not dirs:
            return fallo(f"no hay sesiones registradas para {proyecto}",
                         "mide la máquina entera, o apunta a otro workspace con --proyecto RUTA.",
                         f"{COMANDO} --todos")
        ambito = str(proyecto)

    todas = []
    for fichero in sesiones(dirs):
        turnos, meta = leer_sesion(fichero)
        if turnos:
            todas.append((turnos, meta))
    if not todas:
        return fallo("no hay ni una sesión con uso registrado",
                     "comprueba la ruta, o mide la máquina entera.",
                     f"{COMANDO} --todos")

    # La línea base se valida ANTES de imprimir nada: comparar contra un fichero roto y
    # descubrirlo al final es el cero silencioso que R6 prohíbe.
    base = None
    if args.linea_base:
        try:
            base = json.loads(Path(args.linea_base).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fallo(f"no puedo leer la línea base {args.linea_base}",
                         "genera una primero y vuelve a comparar contra ella.",
                         f"{COMANDO} --json {args.linea_base}")
        if not isinstance(base, dict) or not base.get("ejes") or not base.get("turnos"):
            return fallo(f"la línea base {args.linea_base} no tiene el detalle que hace falta",
                         "vuelve a generarla con este mismo medidor.",
                         f"{COMANDO} --json {args.linea_base}")

    total = sum(sum(t["tokens"] for t in tt) for tt, _ in todas)
    ejes = {clave: sum(sum(t[clave] for t in tt) for tt, _ in todas) for clave in EJES}
    turnos_totales = sum(len(tt) for tt, _ in todas)

    print(f"== Coste del método · {ambito} ==")
    print(f"   {len(todas)} sesiones · {turnos_totales} turnos · {formatear_millones(total)} tokens")
    print()
    print("   En qué se va (estos cuatro ejes son TODO el gasto; sin nota compuesta):")
    for clave in EJES:
        print(f"     {ETIQUETAS[clave]} {pct(ejes[clave], total):5.1f} %  ({formatear_millones(ejes[clave])})")
    print()

    # Qué hay DENTRO de la relectura. Es la pregunta accionable: si manda el razonamiento
    # del agente, la palanca es cortar la sesión; si mandan las herramientas, leer más estrecho.
    acumulado = {o: 0.0 for o in ORIGENES}
    compactaciones = 0
    for _, meta in todas:
        parcial, comp = composicion(Path(meta["fichero"]))
        compactaciones += comp
        for origen in ORIGENES:
            acumulado[origen] += parcial[origen]
    peso_total = sum(acumulado.values())
    print("   Qué se relee (peso x turnos arrastrado; aproximación declarada, no facturación):")
    for origen in sorted(ORIGENES, key=lambda k: -acumulado[k]):
        print(f"     {NOMBRES_ORIGEN[origen]} {pct(acumulado[origen], peso_total):5.1f} %")
    if compactaciones:
        print(f"     ({compactaciones} compactaciones vistas: donde las hubo, esto sobreestima lo antiguo)")
    print("     'andamiaje' son avisos, listados y adjuntos del harness — NO es el texto del método:")
    print("     ese va en el prompt de sistema, que no aparece en el rollout y se mide aparte, abajo.")
    print()

    # ¿Tocar la prosa del método ahorraría algo? Se mide, no se opina: el texto siempre
    # cargado entra ENTERO en cada turno, así que su coste es tamaño x turnos.
    bytes_prosa = prosa_siempre_cargada(os.getcwd() if args.todos else proyecto)
    if bytes_prosa:
        coste_prosa = (bytes_prosa / 4.0) * turnos_totales
        print(f"   Texto del método siempre cargado: {bytes_prosa/1024:.0f} kB "
              f"→ {pct(coste_prosa, total):.2f} % del gasto.")
        print(f"     Adelgazarlo a la mitad ahorraría {pct(coste_prosa/2, total):.2f} %.")
        print()

    # Concentración: ¿unas pocas sesiones se llevan el grueso? key= explícito porque dos
    # sesiones con el mismo gasto y los mismos turnos harían comparar los metadatos.
    por_sesion = sorted(((sum(t["tokens"] for t in tt), len(tt)) for tt, _ in todas),
                        key=lambda fila: (fila[0], fila[1]), reverse=True)
    corte_20 = max(1, len(por_sesion) // 5)
    gasto_20 = sum(s[0] for s in por_sesion[:corte_20])
    print(f"   Concentración: el 20 % de sesiones más caras ({corte_20} de {len(por_sesion)}) "
          f"se lleva el {pct(gasto_20, total):.0f} % del gasto.")

    perfil, cuenta = perfil_por_indice(todas)

    def media_tramo(desde, hasta):
        ks = [k for k in perfil if desde <= k <= hasta]
        return sum(perfil[k] for k in ks) / len(ks) if ks else 0

    base_tramo = media_tramo(*TRAMOS[0])
    partes = []
    for desde, hasta in TRAMOS:
        media = media_tramo(desde, hasta)
        if not media:
            # Un tramo del que no hay datos se DECLARA. Imprimir `0.0x` sería afirmar sin
            # evidencia que ahí el turno no cuesta nada (R7).
            partes.append(f"turno {desde}-{hasta} = sin sesiones tan largas")
        elif (desde, hasta) == TRAMOS[0]:
            partes.append(f"turno {desde}-{hasta} = {media/1000:.0f}k tokens")
        else:
            razon = f"{media/base_tramo:.1f}x" if base_tramo else "sin referencia"
            if razon == "0.0x":
                razon = f"{media/base_tramo:.3f}x"
            partes.append(f"turno {desde}-{hasta} = {media/1000:.0f}k ({razon})")
    print("   Crecimiento: " + " · ".join(partes))
    print()

    simulacion = None
    if args.corte:
        real, simulado, retomadas = simular_corte(todas, perfil, args.corte, args.coste_retomada)
        ahorro = pct(real - simulado, real)
        simulacion = {"corte": args.corte, "real": real, "simulado": simulado,
                      "retomadas": retomadas, "ahorro_pct": round(ahorro, 1)}
        print(f"   Si se hubiera cortado cada {args.corte} turnos:")
        print(f"     gasto real      {formatear_millones(real)}")
        print(f"     gasto simulado  {formatear_millones(simulado)}   → {ahorro:.0f} % menos")
        print(f"     retomadas       {retomadas} (a {args.coste_retomada//1000}k tokens cada una, "
              f"{pct(retomadas*args.coste_retomada, real):.1f} % del gasto)")
        print("     supuesto declarado: tras cortar, el turno k cuesta el promedio histórico")
        print("     del turno k. Es una aproximación, no una promesa.")
        print()

    detalle = {
        "ambito": ambito,
        "sesiones": len(todas),
        "turnos": turnos_totales,
        "tokens": total,
        "ejes": ejes,
        "composicion": {o: round(acumulado[o]) for o in ORIGENES},
        "compactaciones": compactaciones,
        "perfil": {str(k): round(v) for k, v in sorted(perfil.items()) if cuenta[k] >= 3},
    }
    if simulacion:
        detalle["simulacion"] = simulacion

    if base:
        print("   Contra la línea base:")
        for clave in EJES:
            antes = pct(base["ejes"].get(clave, 0), base.get("tokens") or 0)
            ahora = pct(ejes[clave], total)
            print(f"     {ETIQUETAS[clave]} {antes:5.1f} % → {ahora:5.1f} %  ({ahora-antes:+.1f})")
        antes_turno = (base.get("tokens") or 0) / base["turnos"]
        ahora_turno = total / turnos_totales
        variacion = f"{100*(ahora_turno-antes_turno)/antes_turno:+.0f} %" if antes_turno else "sin referencia"
        print(f"     tokens por turno    {antes_turno/1000:.1f}k → {ahora_turno/1000:.1f}k ({variacion})")
        print()

    if args.json:
        destino = Path(args.json)
        if destino.parent and str(destino.parent) not in ("", "."):
            destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "w", encoding="utf-8") as fh:
            json.dump(detalle, fh, ensure_ascii=False, indent=1)
        print(f"   Detalle volcado en {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
