#!/usr/bin/env python3
"""Canario de contexto: avisa de una sesión degradada y deja el parte de retomada.

Lectura PASIVA: no mide nada por su cuenta, no abre red, no llama a ningún modelo. Lee las
señales que el harness YA escribe en disco —el JSONL de sesión de Claude Code y los
rollouts de Codex CLI— y las convierte en una decisión para el usuario. Coste: abrir un
fichero. Por eso puede correr en cada arranque sin que nadie lo note.

Dos señales, dos avisos DISTINTOS (esta distinción es el contrato, no un detalle):

  capacidad (`aviso`)     el % de la ventana del modelo real supera el umbral del workspace
                          → "zona de riesgo: planifica el corte al terminar este paso"
  conducta  (`sintomas`)  el transcript repite el mismo comando con el mismo fallo, o se
                          atasca sin dejar ni una línea de error
                          → "la sesión YA está degradando: escribe la retomada y corta ahora"

Llenarse es un riesgo; repetirse es un hecho. Si coinciden, manda la conducta y sale UN
solo aviso: dos a la vez confundirían.

Subcomandos:
  (sin nada)   veredicto de la sesión más reciente de este workspace
  retomada     el parte pre-rellenado desde ESTADO.md y la unidad en obra (≤2.000 tokens)
  hook         salida para el hook PreCompact(auto) de Claude Code: informa, JAMÁS bloquea
  hook-stop    salida para el hook Stop: barato (solo lee el jsonl) y habla cada N turnos

Regla dura de este script: nunca rompe ni retrasa un arranque. Sin sesión localizable,
fichero corrupto o harness desconocido → silencio y exit 0. El aviso informa; no bloquea.
Solo stdlib.
"""
import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

# Este script vive en docs/00-metodo/scripts/, igual que unidad.py: parents[3] es la raíz
# del meta-repo sea cual sea el directorio de trabajo.
RAIZ = Path(__file__).resolve().parents[3]

# Config del workspace: vive en .claude/ porque es preferencia del dueño (como
# personalidad.md), va gitignorada y ni el Modo D ni una actualización la pisan.
CONFIG = ".claude/canario.json"

# Política PROPIA y declarada: ningún lab publica curvas de degradación por contexto
# (investigacion.md de la unidad 023). 80 % es el default global; la tabla `umbrales` da
# a cualquier modelo su propia cifra cuando haya evidencia que la respalde.
DEFECTOS = {
    "umbral_default": 80,     # % de la ventana a partir del cual el veredicto es `aviso`
    "umbrales": {},           # {modelo: %} — la tabla que Nate toca a mano
    "ventanas": {},           # {modelo: tokens} — ventana declarada para modelos no conocidos
    "turnos_aviso": 250,      # turnos del asistente a partir de los cuales conviene cortar
    "repeticiones": 3,        # repeticiones del mismo comando+fallo que ya son `sintomas`
    "ventana_eventos": 60,    # cuántos pares comando/fallo recientes se miran
    # Atascos SIN error (bug 062): el agente no falla, simplemente no avanza. Umbrales
    # holgados a propósito: el canario existe para no generar ruido.
    "ediciones_seguidas": 5,  # ediciones consecutivas del MISMO fichero
    "tests_sin_verde": 4,     # lanzadas seguidas del mismo test sin que pase a verde
    "turnos_sin_ficheros": 40,  # turnos CON herramienta y sin tocar un solo fichero
    "turnos_hook": 25,        # cada cuántos turnos habla el hook Stop
}

# Ventanas de contexto conocidas, por familia de modelo. Se emparejan por prefijo porque el
# id trae sufijos de fecha (`claude-sonnet-4-5-20250929`), y el ORDEN manda: las entradas
# largas van primero para que `claude-opus-5` no se coma el prefijo genérico `claude-opus-`.
#
# Bug 062: sin las familias actuales aquí, el canario se quedaba mudo justo en los modelos
# con los que se trabaja («sin umbral para este modelo», visto en campo el 25-08). Un modelo
# que no case tampoco apaga la vigilancia: se asume la MENOR conocida y se dice UNA vez
# (`VENTANA_MINIMA`). Asumir de menos avisa antes de tiempo; asumir de más deja ciego.
VENTANAS_CONOCIDAS = (
    ("claude-fable-5", 1_000_000),
    ("claude-opus-5", 1_000_000),
    ("claude-sonnet-5", 1_000_000),
    ("claude-haiku-4-5", 200_000),
    ("claude-opus-", 200_000),
    ("claude-sonnet-", 200_000),
    ("claude-haiku-", 200_000),
    ("claude-3-", 200_000),
)

VENTANA_MINIMA = min(v for _, v in VENTANAS_CONOCIDAS)

# Dónde se apunta lo ya dicho una vez (qué modelos nuevos se han anunciado). Vive junto a
# la config, en `.claude/`: es memoria local, no método repartido.
MEMORIA = ".claude/canario-visto.json"

# Marcas de fallo en la salida de una herramienta. Heurística declarada: el harness de Codex
# no marca el error con un booleano como hace Claude Code, así que la señal de conducta ahí
# se apoya en el texto. Falso negativo antes que falso positivo: un aviso que no toca es
# ruido, y el ruido es exactamente lo que este script existe para no generar.
MARCAS_DE_FALLO = re.compile(
    r"(error|failed|failure|fatal|traceback|exit code [1-9]|command not found|"
    r"no such file|denied|timed out|aborted)", re.I)

AVISO_CAPACIDAD = (
    "⚠️  CANARIO DE CONTEXTO — zona de riesgo\n"
    "   Esta sesión lleva {pct} % de su ventana ({tokens} de {ventana} tokens, {modelo}).\n"
    "   Planifica el corte AL TERMINAR ESTE PASO: escribe la retomada y sigue en una\n"
    "   sesión nueva. No se bloquea nada; decides tú.\n"
    "     python3 docs/00-metodo/scripts/canario.py retomada\n"
    "   Señal leída en {fichero}"
)

AVISO_POSICION = (
    "⚠️  CANARIO DE CONTEXTO — la sesión se ha hecho larga\n"
    "   Van {turnos} turnos. El coste de cada turno crece con su POSICIÓN, no con lo llena que\n"
    "   esté la ventana: uno en el turno 900 cuesta unas 8 veces lo que el mismo en el 50.\n"
    "   Corta AL TERMINAR ESTE PASO y sigue en una sesión nueva. No se bloquea nada.\n"
    "     python3 docs/00-metodo/scripts/canario.py retomada\n"
    "   Señal leída en {fichero}"
)

AVISO_CONDUCTA = (
    "🚨 CANARIO DE CONTEXTO — la sesión YA está degradando\n"
    "   {veces} veces el mismo comando con el mismo fallo: {comando}\n"
    "   → {fallo}\n"
    "   Esto no es un riesgo, es un hecho: escribe la retomada y corta AHORA, en una\n"
    "   sesión nueva. (contexto: {contexto})\n"
    "     python3 docs/00-metodo/scripts/canario.py retomada\n"
    "   Señal leída en {fichero}"
)

AVISO_ATASCO = (
    "🚨 CANARIO DE CONTEXTO — la sesión YA está degradando\n"
    "   {detalle}\n"
    "   Esto no es un riesgo, es un hecho: escribe la retomada y corta AHORA, en una\n"
    "   sesión nueva. (contexto: {contexto})\n"
    "     python3 docs/00-metodo/scripts/canario.py retomada\n"
    "   Señal leída en {fichero}"
)

# No lleva la cabecera «CANARIO DE CONTEXTO» a propósito: no es un veredicto, es una nota
# al pie que acompaña al veredicto de siempre. Y sale UNA sola vez por modelo.
AVISO_MODELO_NUEVO = (
    "CANARIO — modelo nuevo ({modelo})\n"
    "   No tengo su ventana apuntada, así que asumo la MENOR que conozco ({ventana} tokens)\n"
    "   para no quedarme ciego: el porcentaje es un TECHO, no una medida. Si sabes la real,\n"
    "   declárala en {config} (\"ventanas\": {{\"{modelo}\": <tokens>}}).\n"
    "   (este aviso sale una sola vez por modelo)"
)

AVISO_INCIERTO = (
    "CANARIO DE CONTEXTO — sin umbral para este modelo\n"
    "   La sesión ({modelo}) lleva {tokens} tokens, pero no sé cuál es su ventana de\n"
    "   contexto: no me invento el porcentaje. Declara su ventana en {config}\n"
    "   (\"ventanas\": {{\"{modelo}\": <tokens>}}) y el canario vuelve a vigilar.\n"
    "   Señal leída en {fichero}"
)

AVISO_VENTANA_RARA = (
    "CANARIO DE CONTEXTO — la ventana que tengo apuntada no cuadra\n"
    "   La sesión ({modelo}) lleva {tokens} tokens y yo la creía de {ventana}: no sé cuál\n"
    "   es su ventana real, así que no me invento el porcentaje. Declárala en {config}\n"
    "   (\"ventanas\": {{\"{modelo}\": <tokens>}}) y el canario vuelve a vigilar.\n"
    "   Señal leída en {fichero}"
)

LINEA_SANA = "contexto: {pct} % de {ventana} ({modelo}) · sano · {fichero}"


# --------------------------------------------------------------------------- config

def cargar_config(raiz):
    """Config del workspace sobre los DEFECTOS. Una config rota no rompe: se ignora.

    Un canario que se cae porque alguien dejó una coma de más en un JSON no es un canario:
    es un arranque roto. Lo que no se entienda se descarta y manda el defecto.
    """
    config = dict(DEFECTOS)
    config["umbrales"] = {}
    config["ventanas"] = {}
    fichero = Path(raiz) / CONFIG
    try:
        datos = json.loads(fichero.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return config
    if not isinstance(datos, dict):
        return config
    for clave in ("umbral_default", "repeticiones", "ventana_eventos", "turnos_aviso",
                  "ediciones_seguidas", "tests_sin_verde", "turnos_sin_ficheros",
                  "turnos_hook"):
        valor = datos.get(clave)
        if isinstance(valor, (int, float)) and valor > 0:
            config[clave] = int(valor)
    for clave in ("umbrales", "ventanas"):
        tabla = datos.get(clave)
        if isinstance(tabla, dict):
            config[clave] = {str(k): int(v) for k, v in tabla.items()
                             if isinstance(v, (int, float)) and v > 0}
    return config


def resolver_ventana(modelo, config):
    """(ventana, origen) del modelo. `origen` ∈ config | tabla | asumida | None.

    Saber de DÓNDE sale la ventana es lo que distingue un porcentaje medido de un techo
    asumido, y de eso depende tanto lo que se le cuenta al usuario como si un porcentaje
    imposible es un error de tabla (hay que decirlo) o la consecuencia esperada de haber
    asumido la ventana más pequeña que existe.
    """
    if not modelo:
        return None, None
    declarada = config.get("ventanas", {}).get(modelo)
    if declarada:
        return int(declarada), "config"
    for prefijo, ventana in VENTANAS_CONOCIDAS:
        if modelo.startswith(prefijo):
            return ventana, "tabla"
    # R1 del bug 062: un modelo que no conozco NO apaga la vigilancia. Se asume la menor
    # ventana conocida —el techo más prudente— y se dice una vez.
    return VENTANA_MINIMA, "asumida"


def ventana_de(modelo, config):
    """Ventana de contexto del modelo (asumiendo la menor conocida si no lo tengo)."""
    return resolver_ventana(modelo, config)[0]


def modelo_ya_anunciado(raiz, modelo):
    """¿Se anunció ya este modelo nuevo? Lo apunta al preguntar: solo dice `no` una vez.

    Si la memoria no se puede leer NI escribir, se responde `no`: repetir el aviso es un
    incordio menor; callarlo sería justo la ceguera que este bug arregla.
    """
    if not modelo:
        return True
    fichero = Path(raiz) / MEMORIA
    try:
        datos = json.loads(fichero.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    vistos = datos.get("modelos") if isinstance(datos, dict) else None
    vistos = [str(m) for m in vistos] if isinstance(vistos, list) else []
    if modelo in vistos:
        return True
    vistos.append(modelo)
    try:
        fichero.parent.mkdir(parents=True, exist_ok=True)
        fichero.write_text(json.dumps({"modelos": vistos[-50:]}, ensure_ascii=False,
                                      indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass
    return False


def umbral_de(modelo, config):
    """El % del modelo si la tabla le da uno propio; si no, el default global."""
    return int(config.get("umbrales", {}).get(modelo, config["umbral_default"]))


# --------------------------------------------------------------------------- localizar sesión

def normalizar_proyecto(cwd):
    """Nombre de carpeta con el que Claude Code guarda las sesiones de un directorio."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def _rutas_por_defecto():
    """Dónde escriben los harnesses. Las variables de entorno existen para los tests."""
    claude = os.environ.get("CANARIO_CLAUDE_PROJECTS") or (Path.home() / ".claude/projects")
    codex = os.environ.get("CANARIO_CODEX_SESSIONS") or (Path.home() / ".codex/sessions")
    return Path(claude), Path(codex)


def _variantes(ruta):
    """La ruta tal cual llegó y su forma resuelta: AMBAS ortografías cuentan.

    El harness nombra la carpeta de sesiones con el cwd TAL CUAL lo vio; buscar solo con
    la forma resuelta pierde la sesión cuando hay un symlink por medio (`/var` →
    `/private/var` en macOS, 26 tests rojos en main el 18-08) o un nombre corto 8.3 en
    Windows. Y buscar solo con la cruda pierde el caso inverso (el harness guardó la
    resuelta). Se devuelven las dos, deduplicadas, sin tocar la red ni el overhead.
    """
    cruda = Path(os.path.abspath(str(ruta)))
    try:
        resuelta = cruda.resolve()
    except OSError:
        resuelta = cruda
    return [cruda] if str(cruda) == str(resuelta) else [cruda, resuelta]


def _ancestros(cwd, raiz=None):
    """Los directorios cuya sesión cuenta como TUYA: de `cwd` hasta la raíz del workspace.

    La sesión de un worktree se abre en el worktree, pero el harness la guarda por
    directorio: hay que subir. Subir SIN TECHO, en cambio, es peor que no subir: `/Users/x`
    es ancestro de todo, y una sesión suelta abierta en el home se colaba como si fuera la
    de este workspace (visto en real el 18-08). Se sube hasta la raíz y ni un palmo más.

    Si la raíz ES un worktree (`…/worktrees/023-x`), también cuenta el workspace que lo
    posee: ahí es donde el padre tiene abierta su sesión.

    Cada nivel aporta sus DOS ortografías (bug 024): la cadena se recorre una vez desde la
    ruta cruda y otra desde la resuelta, cada una con su propio techo, y el resultado se
    deduplica conservando el orden.
    """
    if raiz is None:
        return _variantes(cwd)
    paradas, finales, techos = set(), set(), []
    for r in _variantes(raiz):
        paradas.add(str(r))
        techos.append(r)
        if r.parent.name == "worktrees":
            dueno = r.parent.parent
            paradas.add(str(dueno))
            finales.add(str(dueno))
            techos.append(dueno)
        else:
            finales.add(str(r))
    validos, vistos, tope_alcanzado = [], set(), False
    for inicio in _variantes(cwd):
        recorrido, alcanzado = [], False
        for directorio in [inicio, *inicio.parents]:
            recorrido.append(directorio)
            if str(directorio) in paradas:
                alcanzado = True
                if str(directorio) in finales:
                    break
        if not alcanzado:
            # esta ortografía queda fuera del workspace: solo cuenta ella, sin escalar.
            recorrido = [inicio]
        else:
            tope_alcanzado = True
        for directorio in recorrido:
            if str(directorio) not in vistos:
                vistos.add(str(directorio))
                validos.append(directorio)
    if not tope_alcanzado:
        for techo in techos:
            if str(techo) not in vistos:
                vistos.add(str(techo))
                validos.append(techo)
    return validos


def _mtime(fichero):
    try:
        return fichero.stat().st_mtime
    except OSError:
        return None


def sesiones_claude(cwd, claude_projects, raiz=None):
    """Sesiones de Claude Code de este directorio, de la raíz del workspace o de en medio."""
    encontradas = []
    for candidato in _ancestros(cwd, raiz):
        carpeta = Path(claude_projects) / normalizar_proyecto(candidato)
        if not carpeta.is_dir():
            continue
        for fichero in carpeta.glob("*.jsonl"):
            marca = _mtime(fichero)
            if marca is not None:
                encontradas.append({"harness": "claude", "fichero": fichero, "mtime": marca})
    return encontradas


def sesiones_codex(cwd, codex_sessions, raiz=None, tope=300):
    """Rollouts de Codex CLI cuyo `cwd` es este directorio o alguno de sus padres.

    Se miran solo los `tope` más recientes: el histórico de Codex crece sin fin y abrir
    todos sus ficheros por un arranque sería justo el overhead que este script promete no
    tener.
    """
    carpeta = Path(codex_sessions)
    if not carpeta.is_dir():
        return []
    candidatos = []
    for fichero in carpeta.rglob("rollout-*.jsonl"):
        marca = _mtime(fichero)
        if marca is not None:
            candidatos.append((marca, fichero))
    candidatos.sort(reverse=True)
    validos = {str(p) for p in _ancestros(cwd, raiz)}
    encontradas = []
    for marca, fichero in candidatos[:tope]:
        propietario = _cwd_de_rollout(fichero)
        # El rollout trae el cwd escrito: aquí SÍ se pueden comparar las dos ortografías
        # del propietario (tal cual y resuelta), no solo las del que pregunta (bug 024).
        if propietario and any(str(v) in validos for v in _variantes(propietario)):
            encontradas.append({"harness": "codex", "fichero": fichero, "mtime": marca})
    return encontradas


def _cwd_de_rollout(fichero):
    """El `cwd` que Codex escribe en la cabecera `session_meta` del rollout."""
    try:
        with fichero.open(encoding="utf-8", errors="replace") as f:
            for _ in range(5):
                linea = f.readline()
                if not linea:
                    return None
                try:
                    dato = json.loads(linea)
                except ValueError:
                    continue
                if not isinstance(dato, dict):
                    continue
                payload = dato.get("payload") if isinstance(dato.get("payload"), dict) else {}
                cwd = payload.get("cwd") or dato.get("cwd")
                if cwd:
                    return cwd
    except OSError:
        return None
    return None


def localizar_sesion(cwd, claude_projects, codex_sessions, raiz=None):
    """La sesión MÁS RECIENTE por mtime, del harness que sea. None si no hay ninguna.

    R7: en una máquina viva hay varias sesiones abiertas del mismo workspace, y la
    ambigüedad es real. Se elige por mtime y la salida dice qué fichero se leyó: si la
    elección fue la equivocada, quien mira lo ve en el acto.
    """
    todas = (sesiones_claude(cwd, claude_projects, raiz)
             + sesiones_codex(cwd, codex_sessions, raiz))
    if not todas:
        return None
    todas.sort(key=lambda s: s["mtime"], reverse=True)
    elegida = dict(todas[0])
    elegida["candidatos"] = len(todas)
    return elegida


# --------------------------------------------------------------------------- leer la señal

def _lineas(fichero):
    """Las líneas JSON legibles del fichero. Lo corrupto se salta, no se explota."""
    try:
        with Path(fichero).open(encoding="utf-8", errors="replace") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    dato = json.loads(linea)
                except ValueError:
                    continue
                if isinstance(dato, dict):
                    yield dato
    except OSError:
        return


# Cola de un comando que no dice NADA sobre lo que se intentó: son las muletillas con las
# que el agente recorta la salida. Sin quitarlas, `… | tail -20` y `… | tail -40` son dos
# comandos distintos y el mismo atasco repetido tres veces no cuenta ni una (bug 062).
COLA_DE_PIPE = re.compile(
    r"\s*(?:2>&1|1>&2|\|\|\s*true|&&\s*true|"
    r"\|\s*(?:tail|head|cat|less|more|wc)\b[^|]*|"
    r">\s*/dev/null(?:\s*2>&1)?)", re.I)

# Directorios temporales: cada intento estrena uno y el comando parece nuevo cada vez.
RUTAS_TEMPORALES = re.compile(
    r"(?:/private)?/var/folders/\S+|/tmp/\S+|\$TMPDIR\S*|"
    r"[A-Za-z]:\\+Users\\+[^\\\s]+\\+AppData\\+Local\\+Temp\\+\S*", re.I)

NUMEROS = re.compile(r"\d+")

# Qué pinta tiene lanzar la batería de tests. Se usa para la señal «el mismo test N veces
# sin pasar a verde»: no hace falta acertar con todos los runners, basta con los habituales.
MARCAS_DE_TEST = re.compile(
    r"\b(?:pytest|unittest|jest|vitest|mocha|tox|rspec|phpunit|"
    r"go\s+test|cargo\s+test|npm\s+(?:run\s+)?test|yarn\s+test|"
    r"run-fast|run-nightly|correr\.py)\b", re.I)

# Herramientas que TOCAN un fichero. La señal de «turnos sin producir nada» necesita saber
# cuándo el agente escribió algo de verdad, no cuándo miró.
HERRAMIENTAS_DE_FICHERO = {"edit", "write", "multiedit", "notebookedit", "str_replace_editor",
                           "apply_patch", "create_file"}


def _sin_ruido(texto, *, numeros=False):
    """El texto sin colas de pipe ni rutas temporales; con `numeros`, también sin cifras."""
    texto = COLA_DE_PIPE.sub("", str(texto))
    texto = RUTAS_TEMPORALES.sub("<tmp>", texto)
    if numeros:
        texto = NUMEROS.sub("#", texto)
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_comando(orden):
    """R2: dos intentos del MISMO comando se reconocen aunque no sean literales.

    El agente atascado no repite el comando calcado: cambia el directorio temporal, sube el
    `-20` del tail a `-40`, añade un `|| true`. Comparar literalmente es no comparar.
    """
    return _sin_ruido(orden, numeros=True)[:200]


def _firma(texto):
    """Firma estable de un fallo: lo que permite decir 'el MISMO fallo' sin ser literal.

    Aquí los números SÍ distinguen, al revés que en el comando: «fallo en la línea 12» y
    «fallo en la línea 40» son dos fallos, y borrar la cifra los fundiría en uno solo —el
    canario gritaría por un agente que va probando cosas distintas—. Lo único que se quita
    es el directorio temporal, que cambia en cada intento sin significar nada.
    """
    return _sin_ruido(texto).lower()[:200]


def _texto_de(contenido):
    """Aplana el contenido de un resultado de herramienta (str, lista de bloques o dict)."""
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        piezas = []
        for bloque in contenido:
            if isinstance(bloque, dict):
                piezas.append(str(bloque.get("text") or bloque.get("content") or ""))
            else:
                piezas.append(str(bloque))
        return "\n".join(piezas)
    if isinstance(contenido, dict):
        return str(contenido.get("text") or contenido.get("output") or contenido)
    return str(contenido)


def leer_claude(fichero):
    """Uso de contexto, pares comando/fallo y señales de atasco de una sesión de Claude Code.

    El contexto de la petición es lo que el modelo vuelve a leer entero en cada turno:
    entrada + caché leída + caché escrita. La salida no ocupa ventana de entrada.

    Bug 062 — el harness de Claude Code marca `is_error` solo cuando el proceso sale con
    código != 0, y el agente encadena `| tail`, `2>&1` y `|| true`: el exit del pipeline es
    0 y el fallo viaja DENTRO del texto. En 223 turnos de campo hubo un solo `is_error`. Por
    eso aquí el fallo se lee igual que en Codex: por el CONTENIDO. Y de paso se recogen las
    tres señales de atasco que no dejan ni una línea de error (R3).
    """
    modelo, tokens, turnos = None, None, 0
    comandos, fallos = {}, []
    ediciones, pruebas, turnos_secos = [], [], []
    for dato in _lineas(fichero):
        mensaje = dato.get("message")
        if not isinstance(mensaje, dict):
            continue
        uso = mensaje.get("usage")
        if isinstance(uso, dict):
            suma = sum(int(uso.get(clave) or 0) for clave in
                       ("input_tokens", "cache_read_input_tokens",
                        "cache_creation_input_tokens"))
            if suma:
                tokens = suma
                modelo = mensaje.get("model") or modelo
                # Solo cuentan los turnos del ASISTENTE. Un registro de usuario puede traer
                # `usage` y no es un turno: contarlo infla la cuenta y adelanta el aviso.
                # Las dos señales, porque el harness usa una u otra según la versión.
                if dato.get("type") == "assistant" or mensaje.get("role") == "assistant":
                    turnos += 1
        contenido = mensaje.get("content")
        if not isinstance(contenido, list):
            continue
        herramientas, toco_fichero = 0, False
        for bloque in contenido:
            if not isinstance(bloque, dict):
                continue
            if bloque.get("type") == "tool_use":
                herramientas += 1
                entrada = bloque.get("input") if isinstance(bloque.get("input"), dict) else {}
                nombre = str(bloque.get("name") or "")
                fichero_tocado = entrada.get("file_path") or entrada.get("path")
                if nombre.lower() in HERRAMIENTAS_DE_FICHERO:
                    toco_fichero = True
                    if fichero_tocado:
                        ediciones.append(str(fichero_tocado))
                orden = entrada.get("command") or fichero_tocado or entrada.get(
                    "pattern") or json.dumps(entrada, sort_keys=True, ensure_ascii=False)
                comandos[bloque.get("id")] = f"{nombre}: {normalizar_comando(orden)}"[:200]
            elif bloque.get("type") == "tool_result":
                orden = comandos.get(bloque.get("tool_use_id"))
                if not orden:
                    continue
                texto = _texto_de(bloque.get("content"))
                roto = bool(bloque.get("is_error")) or bool(MARCAS_DE_FALLO.search(texto))
                if roto:
                    fallos.append((orden, _firma(texto)))
                if MARCAS_DE_TEST.search(orden):
                    # Verde = ni error ni marca de fallo Y la palabra que dice que pasó.
                    verde = not roto and bool(re.search(r"\b(?:ok|passed|passing|all tests)\b",
                                                        texto, re.I))
                    pruebas.append((orden, verde))
        if herramientas:
            turnos_secos.append(toco_fichero)
    if tokens is None:
        return None
    return {"modelo": modelo, "tokens": tokens, "ventana": None, "fallos": fallos,
            "turnos": turnos, "ediciones": ediciones, "pruebas": pruebas,
            "turnos_secos": turnos_secos}


def leer_codex(fichero):
    """Uso de contexto y pares comando/fallo de un rollout de Codex CLI.

    `last_token_usage.total_tokens` es lo que ocupa la ÚLTIMA petición, o sea el contexto
    vivo; `total_token_usage` es acumulado de toda la sesión y supera la ventana sin que
    eso signifique nada. La ventana la declara el propio rollout: aquí no hace falta tabla.
    """
    tokens, ventana, modelo, turnos = None, None, None, 0
    comandos, fallos = {}, []
    for dato in _lineas(fichero):
        payload = dato.get("payload")
        if not isinstance(payload, dict):
            continue
        tipo = payload.get("type")
        if tipo == "token_count":
            info = payload.get("info")
            if isinstance(info, dict):
                ultimo = info.get("last_token_usage") or info.get("total_token_usage") or {}
                if isinstance(ultimo, dict) and ultimo.get("total_tokens"):
                    tokens = int(ultimo["total_tokens"])
                    turnos += 1     # cada recuento de tokens marca un turno
                if info.get("model_context_window"):
                    ventana = int(info["model_context_window"])
        elif tipo in ("function_call", "custom_tool_call"):
            crudo = payload.get("arguments") or payload.get("input") or ""
            comandos[payload.get("call_id")] = (
                f"{payload.get('name')}: {normalizar_comando(_orden(crudo))}"[:200])
        elif tipo in ("function_call_output", "custom_tool_call_output"):
            texto = _texto_de(payload.get("output"))
            orden = comandos.get(payload.get("call_id"))
            if orden and MARCAS_DE_FALLO.search(texto):
                fallos.append((orden, _firma(texto)))
        elif tipo is None and dato.get("type") == "session_meta":
            modelo = payload.get("model") or modelo
    if tokens is None:
        return None
    # Codex no publica ediciones ni tests por separado: sus señales de atasco son las
    # mismas repeticiones de siempre. Las claves viajan vacías para que el veredicto no
    # tenga que preguntar de qué harness viene.
    return {"modelo": modelo, "tokens": tokens, "ventana": ventana, "fallos": fallos,
            "turnos": turnos, "ediciones": [], "pruebas": [], "turnos_secos": []}


def _orden(crudo):
    """El comando dentro de los argumentos de una llamada de Codex, si se deja leer."""
    try:
        datos = json.loads(crudo)
    except (ValueError, TypeError):
        return str(crudo)
    if isinstance(datos, dict):
        orden = datos.get("command") or datos.get("cmd") or datos
        if isinstance(orden, list):
            return " ".join(str(p) for p in orden)
        return str(orden)
    return str(crudo)


LECTORES = {"claude": leer_claude, "codex": leer_codex}


# --------------------------------------------------------------------------- veredicto

def detectar_sintomas(fallos, config):
    """R8: el mismo comando con el MISMO fallo, N veces en la ventana reciente.

    Se mira la ventana de los últimos pares y no la sesión entera: tres fallos iguales hace
    dos horas son historia; tres seguidos ahora mismo son un agente atascado.
    """
    recientes = list(fallos)[-config["ventana_eventos"]:]
    cuenta = {}
    for par in recientes:
        cuenta[par] = cuenta.get(par, 0) + 1
    if not cuenta:
        return None
    (comando, fallo), veces = max(cuenta.items(), key=lambda kv: kv[1])
    if veces < config["repeticiones"]:
        return None
    return {"tipo": "repeticion", "comando": comando, "fallo": fallo, "veces": veces}


def _racha_final(secuencia):
    """(elemento, longitud) de la racha de valores iguales con la que TERMINA la lista."""
    if not secuencia:
        return None, 0
    ultimo, largo = secuencia[-1], 1
    for valor in reversed(secuencia[:-1]):
        if valor != ultimo:
            break
        largo += 1
    return ultimo, largo


def detectar_atasco(señal, config):
    """R3 del bug 062: los atascos que no dejan ni una línea de error.

    Tres formas de no avanzar, en orden de cuánto delatan:
      1. el mismo fichero editado N veces SEGUIDAS (se reescribe el mismo sitio a ciegas),
      2. el mismo test lanzado N veces sin pasar a verde (se prueban remedios),
      3. N turnos con herramienta y sin tocar un solo fichero (se da vueltas).
    La racha se mide al FINAL, no en toda la sesión: lo que importa es si está pasando
    AHORA. Y solo cuentan los turnos que usaron herramienta: una conversación larga no es
    un atasco, es una conversación (de eso ya avisa el eje de posición).
    """
    fichero, veces = _racha_final(señal.get("ediciones") or [])
    if fichero and veces >= config["ediciones_seguidas"]:
        return {"tipo": "ediciones", "veces": veces, "sujeto": fichero,
                "detalle": f"{veces} ediciones seguidas del mismo fichero: {fichero}"}

    pruebas = señal.get("pruebas") or []
    if pruebas:
        seguidas, orden = 0, None
        for comando, verde in reversed(pruebas):
            if verde or (orden is not None and comando != orden):
                break
            orden, seguidas = comando, seguidas + 1
        if orden and seguidas >= config["tests_sin_verde"]:
            return {"tipo": "tests", "veces": seguidas, "sujeto": orden,
                    "detalle": f"{seguidas} veces el mismo test sin pasar a verde: {orden}"}

    tocado, secos = _racha_final(señal.get("turnos_secos") or [])
    if tocado is False and secos >= config["turnos_sin_ficheros"]:
        return {"tipo": "sin_ficheros", "veces": secos, "sujeto": None,
                "detalle": f"{secos} turnos seguidos usando herramientas sin tocar "
                           "un solo fichero"}
    return None


def diagnosticar(*, raiz=None, cwd=None, claude_projects=None, codex_sessions=None,
                 transcript=None):
    """Informe completo de la sesión más reciente. Nunca lanza: como mucho, `sin_datos`.

    `transcript` es el atajo barato del hook `Stop`: el harness ya dice qué fichero está
    escribiendo, así que no hace falta rastrear ninguna carpeta.

    Ojo, efecto de lado declarado: cuando el modelo no está en la tabla, apunta en
    `.claude/canario-visto.json` que ya se anunció, para que el aviso salga UNA vez (R1).
    """
    raiz = Path(raiz or RAIZ)
    cwd = Path(cwd or Path.cwd())
    por_defecto = _rutas_por_defecto()
    claude_projects = Path(claude_projects or por_defecto[0])
    codex_sessions = Path(codex_sessions or por_defecto[1])
    config = cargar_config(raiz)
    informe = {"harness": None, "fichero": None, "modelo": None, "tokens": None,
               "ventana": None, "porcentaje": None, "umbral": config["umbral_default"],
               "veredicto": "sin_datos", "sintoma": None, "candidatos": 0,
               "turnos": None, "turnos_aviso": config["turnos_aviso"],
               "ventana_incoherente": None, "ventana_asumida": False,
               "avisar_modelo": False,
               "config": str(raiz / CONFIG)}

    if transcript and Path(transcript).is_file():
        sesion = {"harness": "claude", "fichero": Path(transcript), "candidatos": 1}
    else:
        sesion = localizar_sesion(cwd, claude_projects, codex_sessions, raiz)
    if not sesion:
        return informe
    informe["harness"] = sesion["harness"]
    informe["fichero"] = str(sesion["fichero"])
    informe["candidatos"] = sesion["candidatos"]

    señal = LECTORES[sesion["harness"]](sesion["fichero"])
    if not señal:
        informe["harness"], informe["fichero"] = None, None
        return informe

    informe["modelo"] = señal["modelo"]
    informe["tokens"] = señal["tokens"]
    informe["turnos"] = señal.get("turnos")
    ventana, origen = resolver_ventana(señal["modelo"], config)
    if señal["ventana"]:                    # el rollout de Codex la trae escrita: manda
        ventana, origen = señal["ventana"], "config"
    informe["ventana"] = ventana
    informe["ventana_asumida"] = origen == "asumida"
    informe["umbral"] = umbral_de(señal["modelo"], config)
    if informe["ventana"]:
        informe["porcentaje"] = 100.0 * señal["tokens"] / informe["ventana"]
    if (informe["porcentaje"] is not None and informe["porcentaje"] > 100
            and origen != "asumida"):
        # Más del 100 % no significa "el doble de llena": significa que la ventana con la
        # que se divide es falsa (modelo nuevo, ventana ampliada). Caso de campo el 18-08
        # con claude-fable-5. Un número imposible dicho con aplomo es peor que no decirlo:
        # se declara la incertidumbre y se pide la ventana real en la config.
        #
        # Con la ventana ASUMIDA, en cambio, pasarse del 100 % no delata ningún error: es
        # la consecuencia esperada de haber asumido la más pequeña que existe. Ahí el
        # porcentaje es un techo y se dice como tal, no se tira a la basura.
        informe["ventana_incoherente"] = informe["ventana"]
        informe["ventana"] = None
        informe["porcentaje"] = None
    if informe["ventana_asumida"]:
        informe["avisar_modelo"] = not modelo_ya_anunciado(raiz, señal["modelo"])

    informe["sintoma"] = (detectar_sintomas(señal["fallos"], config)
                          or detectar_atasco(señal, config))
    if informe["sintoma"]:
        informe["veredicto"] = "sintomas"           # la conducta manda sobre la capacidad
    elif informe["porcentaje"] is not None and informe["porcentaje"] >= informe["umbral"]:
        informe["veredicto"] = "aviso"
    elif (informe["turnos"] or 0) >= informe["turnos_aviso"]:
        # Medido el 22-08-2026: 0 disparos por capacidad en 63 sesiones y 4 Gtok, porque
        # el umbral es un % de una ventana de 1M. Lo que sí predice el coste es la
        # posición del turno. Esta rama es la que de verdad frena el gasto.
        informe["veredicto"] = "largo"
    elif informe["porcentaje"] is None:
        informe["veredicto"] = "incierto"
    else:
        informe["veredicto"] = "sano"
    return informe


def texto_veredicto(informe):
    """El texto que ve el usuario. Vacío = silencio: sin sesión no se dice nada."""
    cuerpo = _cuerpo_veredicto(informe)
    if not cuerpo or not informe.get("avisar_modelo"):
        return cuerpo
    # La nota del modelo nuevo acompaña al veredicto de siempre; nunca lo sustituye ni lo
    # duplica (por eso no lleva la cabecera «CANARIO DE CONTEXTO»).
    return AVISO_MODELO_NUEVO.format(modelo=informe["modelo"] or "desconocido",
                                     ventana=informe["ventana"] or VENTANA_MINIMA,
                                     config=informe["config"]) + "\n" + cuerpo


def _cuerpo_veredicto(informe):
    veredicto = informe["veredicto"]
    if veredicto == "sin_datos":
        return ""
    if veredicto == "sintomas":
        contexto = ("%d %% de %s" % (round(informe["porcentaje"]), informe["ventana"])
                    if informe["porcentaje"] is not None else "sin porcentaje")
        sintoma = informe["sintoma"]
        if sintoma.get("tipo", "repeticion") != "repeticion":
            return AVISO_ATASCO.format(detalle=sintoma["detalle"], contexto=contexto,
                                       fichero=informe["fichero"])
        return AVISO_CONDUCTA.format(veces=sintoma["veces"],
                                     comando=sintoma["comando"],
                                     fallo=sintoma["fallo"][:120],
                                     contexto=contexto, fichero=informe["fichero"])
    if veredicto == "largo":
        return AVISO_POSICION.format(turnos=informe["turnos"], fichero=informe["fichero"])
    if veredicto == "incierto":
        if informe.get("ventana_incoherente"):
            return AVISO_VENTANA_RARA.format(
                modelo=informe["modelo"] or "desconocido", tokens=informe["tokens"],
                ventana=informe["ventana_incoherente"], config=informe["config"],
                fichero=informe["fichero"])
        return AVISO_INCIERTO.format(modelo=informe["modelo"] or "desconocido",
                                     tokens=informe["tokens"], config=informe["config"],
                                     fichero=informe["fichero"])
    if veredicto == "aviso":
        return AVISO_CAPACIDAD.format(pct=round(informe["porcentaje"]),
                                      tokens=informe["tokens"], ventana=informe["ventana"],
                                      modelo=informe["modelo"] or "modelo desconocido",
                                      fichero=informe["fichero"])
    return LINEA_SANA.format(pct=round(informe["porcentaje"]), ventana=informe["ventana"],
                             modelo=informe["modelo"] or "modelo desconocido",
                             fichero=informe["fichero"])


# --------------------------------------------------------------------------- retomada

TOPE_RETOMADA = 2000            # tokens: el parte cabe en una pantalla o no lo lee nadie


def tokens_aprox(texto):
    """Estimación local de tokens (~4 caracteres por token). Sin red, sin tokenizador."""
    return math.ceil(len(texto) / 4)


def _frontmatter(texto):
    """Parseo mínimo del frontmatter, con listas multilínea. Mismo criterio que unidad.py."""
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        return {}
    datos, abierta, items = {}, None, []
    for linea in lineas[1:]:
        if linea.strip() == "---":
            break
        cabecera = re.match(r"^(\w+):\s*(.*)$", linea)
        if cabecera:
            if abierta and items:
                datos[abierta] = items
            abierta, items = None, []
            valor = cabecera.group(2).split("#")[0].strip()
            datos[cabecera.group(1)] = valor
            if not valor:
                abierta = cabecera.group(1)
            continue
        item = re.match(r"^\s+-\s*(.+)$", linea)
        if item and abierta:
            items.append(item.group(1).split("#")[0].strip().strip("'\""))
    if abierta and items:
        datos[abierta] = items
    return datos


def _seccion(texto, titulo):
    """El cuerpo de una sección markdown `## Titulo…`, hasta el siguiente encabezado."""
    patron = re.compile(r"^##\s+" + re.escape(titulo) + r".*$", re.M)
    encaje = patron.search(texto)
    if not encaje:
        return ""
    resto = texto[encaje.end():]
    siguiente = re.search(r"^#{1,2}\s+", resto, re.M)
    return (resto[:siguiente.start()] if siguiente else resto).strip()


def _viñetas(bloque, tope=6):
    """Las viñetas de un bloque, cada una ENTERA: en estos documentos ocupan varias líneas."""
    viñetas = []
    for linea in bloque.splitlines():
        if linea.strip().startswith(("- ", "* ")):
            viñetas.append(linea.strip())
        elif viñetas and linea.strip() and linea.startswith((" ", "\t")):
            viñetas[-1] += " " + linea.strip()
    return viñetas[:tope]


def _primera_seccion(texto, titulos):
    """El primer título de la lista que exista: los papeles del método cambian de nombre."""
    for titulo in titulos:
        bloque = _seccion(texto, titulo)
        if bloque:
            return bloque
    return ""


def unidad_en_obra(raiz):
    """La unidad que está en obra ahora mismo: carpeta de 05-trabajo/ o ficha de bugs/."""
    candidatas = []
    trabajo = Path(raiz) / "docs/05-trabajo"
    if trabajo.is_dir():
        for carpeta in trabajo.iterdir():
            spec = carpeta / "especificacion.md"
            if carpeta.is_dir() and spec.is_file():
                candidatas.append(spec)
    bugs = Path(raiz) / "docs/bugs"
    if bugs.is_dir():
        candidatas.extend(f for f in bugs.glob("*.md") if f.stem != "INDICE")
    vivas = []
    for ruta in candidatas:
        try:
            texto = ruta.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _frontmatter(texto)
        if fm.get("estado") in ("en_obra", "en_revision"):
            marca = _mtime(ruta) or 0
            vivas.append((marca, ruta, texto, fm))
    if not vivas:
        return None
    vivas.sort(key=lambda v: v[0], reverse=True)
    _, ruta, texto, fm = vivas[0]
    return {"ruta": ruta, "texto": texto, "fm": fm}


def texto_retomada(raiz=None):
    """R5: el parte de retomada, pre-rellenado desde los papeles vivos del workspace.

    No es un resumen libre de la conversación —eso es justo lo que un agente degradado hace
    mal—: son ocho secciones sacadas de ESTADO.md, de la especificación de la unidad en obra
    y de sus hallazgos. Lo que no esté escrito, no aparece.
    """
    raiz = Path(raiz or RAIZ)
    unidad = unidad_en_obra(raiz)
    fm = unidad["fm"] if unidad else {}
    spec = unidad["texto"] if unidad else ""
    nombre = fm.get("unidad") or (unidad["ruta"].parent.name if unidad else "—")

    try:
        estado_md = (raiz / "docs/05-trabajo/ESTADO.md").read_text(encoding="utf-8")
    except OSError:
        estado_md = ""
    hallazgos = ""
    if unidad and unidad["ruta"].name == "especificacion.md":
        try:
            hallazgos = (unidad["ruta"].parent / "hallazgos.md").read_text(encoding="utf-8")
        except OSError:
            hallazgos = ""

    objetivo = _seccion(spec, "Qué") or _seccion(spec, "Síntoma") or "—"
    ahora = _primera_seccion(estado_md, ("Posición actual", "Ahora mismo",
                                        "Continuidad de sesión")) or "—"
    decisiones = _viñetas(_seccion(spec, "Diseño conversado")) or ["—"]
    ficheros = fm.get("ficheros") or []
    if isinstance(ficheros, str):
        ficheros = [f.strip() for f in ficheros.strip("[]").split(",") if f.strip()]
    evidencia = _seccion(hallazgos, "Evidencia de verificación")
    # Lo que va entre <…> en hallazgos.md es la INSTRUCCIÓN de la plantilla, no evidencia:
    # colarla como "último verde" sería decirle a la sesión nueva que algo pasó cuando no.
    verde = "\n".join(l for l in evidencia.splitlines()
                      if l.strip() and not l.startswith("```") and not l.lstrip().startswith("<"))
    plan = _seccion(spec, "Plan de trabajo")
    hechos = [l.strip() for l in plan.splitlines() if l.strip().startswith("- [x]")]
    pendientes = [l.strip() for l in plan.splitlines() if l.strip().startswith("- [ ]")]
    fuera = _viñetas(_seccion(spec, "Fuera de alcance")) or ["—"]

    partes = [
        f"# Parte de retomada · {nombre}\n\n"
        "> Generado por el canario desde ESTADO.md y la unidad en obra. Pégalo en la sesión\n"
        "> NUEVA como primer mensaje: es todo lo que hace falta para continuar.",
        f"## Objetivo\n\n{_recortar(objetivo, 700)}",
        f"## Estado\n\n{_recortar(ahora, 500)}\n\nUnidad: {nombre} "
        f"(estado: {fm.get('estado', '—')}, contrato: "
        f"{_relativa(raiz, unidad['ruta']) if unidad else '—'})",
        "## Decisiones\n\n" + "\n".join(_recortar(d, 300) for d in decisiones),
        "## Ficheros\n\n" + ("\n".join(f"- {f}" for f in ficheros) if ficheros else "- —"),
        "## Último verde\n\n" + (_recortar(verde, 400) if verde.strip() else "—"),
        "## Siguiente paso\n\n" + (pendientes[0] if pendientes else
                                    _recortar(_seccion(estado_md, "Siguiente acción"), 400)
                                    or "—"),
        "## No repetir (ya hecho)\n\n" + ("\n".join(hechos[-6:]) if hechos else "- —"),
        "## Fuera de alcance\n\n" + "\n".join(fuera),
    ]
    parte = "\n\n".join(partes) + "\n"
    return _capar(parte)


def _relativa(raiz, ruta):
    try:
        return str(Path(ruta).relative_to(raiz))
    except ValueError:
        return str(ruta)


def _recortar(texto, tope):
    texto = texto.strip()
    return texto if len(texto) <= tope else texto[:tope].rstrip() + " […]"


def _capar(parte):
    """El tope de 2.000 tokens es del contrato: un parte que no cabe no se lee."""
    limite = TOPE_RETOMADA * 4
    if len(parte) <= limite:
        return parte
    corte = parte[:limite - 60].rstrip()
    return corte + "\n\n[…] (parte recortado al tope de 2.000 tokens)\n"


# --------------------------------------------------------------------------- hooks

def _entrada_del_hook():
    """El JSON que el harness escribe por stdin, o {} si no hay nada legible.

    Nunca bloquea ni revienta: si stdin es una terminal o viene vacío, el hook sigue su
    camino y localiza la sesión como siempre.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        datos = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def salida_hook_stop(informe, config, *, entrada=None):
    """R4: lo que imprime el hook `Stop`. Barato, callado y JAMÁS bloqueante.

    El hook se dispara al final de CADA turno. Hablar en todos sería ruido y el ruido es lo
    que este script existe para no generar, así que la capacidad y la posición se cuentan
    de N en N turnos. La conducta no espera turno: repetirse ya está pasando.
    """
    salida = {"continue": True}
    if informe["veredicto"] == "sin_datos":
        return salida
    if informe["veredicto"] == "sintomas":
        salida["systemMessage"] = texto_veredicto(informe)
        return salida
    if informe["veredicto"] == "sano":
        return salida
    turnos = informe.get("turnos") or 0
    cada = max(1, int(config["turnos_hook"]))
    if turnos < cada or turnos % cada:
        return salida
    mensaje = texto_veredicto(informe)
    if mensaje:
        salida["systemMessage"] = mensaje
    return salida


# --------------------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Canario de contexto: avisa de una sesión degradada y deja la retomada.")
    parser.add_argument("comando", nargs="?", default="veredicto",
                        choices=["veredicto", "retomada", "hook", "hook-stop"])
    parser.add_argument("--workspace", default=None, help="raíz del meta-repo")
    parser.add_argument("--cwd", default=None, help="directorio de la sesión a mirar")
    parser.add_argument("--json", action="store_true", help="el informe crudo, para scripts")
    args = parser.parse_args(argv)

    raiz = Path(args.workspace or RAIZ)
    if args.comando == "retomada":
        print(texto_retomada(raiz))
        return 0

    if args.comando == "hook-stop":
        entrada = _entrada_del_hook()
        informe = diagnosticar(raiz=raiz, cwd=args.cwd or Path.cwd(),
                               transcript=entrada.get("transcript_path"))
        print(json.dumps(salida_hook_stop(informe, cargar_config(raiz)),
                         ensure_ascii=False))
        return 0

    informe = diagnosticar(raiz=raiz, cwd=args.cwd or Path.cwd())
    if args.comando == "hook":
        # PreCompact(auto): el harness va a compactar, o sea que la sesión YA está llena.
        # Aquí se avisa SIEMPRE, mire alguien el porcentaje o no. Y nunca se bloquea:
        # `continue: true` y exit 0, pase lo que pase (fuera de alcance del contrato).
        mensaje = texto_veredicto(informe)
        if informe["veredicto"] != "sintomas":
            # Compactar YA es la prueba de que la sesión está llena: aquí no vale ni el
            # "sano" ni el "no sé tu ventana". Suena el aviso de capacidad con lo que se
            # sepa, y lo que no se sepa va como "?" — mejor un hueco que un número falso.
            mensaje = AVISO_CAPACIDAD.format(
                pct=round(informe["porcentaje"]) if informe["porcentaje"] is not None else "?",
                tokens=informe["tokens"] if informe["tokens"] is not None else "?",
                ventana=informe["ventana"] or "?",
                modelo=informe["modelo"] or "modelo desconocido",
                fichero=informe["fichero"] or "el harness va a auto-compactar")
        print(json.dumps({"continue": True, "systemMessage": mensaje}, ensure_ascii=False))
        return 0

    if args.json:
        print(json.dumps(informe, ensure_ascii=False, sort_keys=True))
        return 0
    texto = texto_veredicto(informe)
    if texto:
        print(texto)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                       # noqa: BLE001 — un canario JAMÁS rompe un arranque
        sys.exit(0)
