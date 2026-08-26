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
    # Accidentes de sesión (unidad 072): no son rachas, pasan UNA vez y a partir de ahí el
    # agente trabaja sobre una realidad que ya no es la que cree. Por eso casi todos valen 1.
    "cwd_erroneo": 2,         # `cd` a una carpeta que no existe
    "git_destructivo": 1,     # `git reset --hard`, `git checkout --`, `git restore`
    "conflicto": 1,           # un CONFLICT resuelto dentro de la sesión
    "stash": 1,               # `git stash` (prohibido por cierre.md)
    "escritura_en_main": 1,   # escribir o commitear dentro de `main/`
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

AVISO_INCIDENTE = (
    "🚨 CANARIO DE CONTEXTO — esta sesión ha tenido un accidente\n"
    "   {detalle} (turno {turno})\n"
    "   Eso no se deshace solo: {accion}.\n"
    "   (contexto: {contexto})\n"
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
                  "turnos_hook", "cwd_erroneo", "git_destructivo", "conflicto",
                  "stash", "escritura_en_main"):
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


def leer_memoria(raiz):
    """Lo apuntado en `.claude/canario-visto.json`, o un dict vacío si no hay nada legible."""
    try:
        datos = json.loads((Path(raiz) / MEMORIA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def guardar_memoria(raiz, datos):
    """Apunta la memoria. Si no se puede escribir, se sigue: un canario no rompe nada."""
    fichero = Path(raiz) / MEMORIA
    try:
        fichero.parent.mkdir(parents=True, exist_ok=True)
        fichero.write_text(json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True)
                           + "\n", encoding="utf-8")
    except OSError:
        pass


def modelo_ya_anunciado(raiz, modelo):
    """¿Se anunció ya este modelo nuevo? PREGUNTA PURA: no apunta nada.

    Bug 062, hueco H1 del revisor: antes esto apuntaba el modelo al preguntar, así que
    `diagnosticar` gastaba el «una sola vez» aunque el aviso no llegara a imprimirse nunca
    —y con el hook `Stop` sembrado, un veredicto `sano` no imprime—. La memoria se gasta
    solo donde el aviso SE ESCRIBE (`apuntar_modelo`, desde `texto_veredicto`).

    Si la memoria no se puede leer, se responde `no`: repetir el aviso es un incordio menor;
    callarlo sería justo la ceguera que este bug arregla.
    """
    if not modelo:
        return True
    vistos = leer_memoria(raiz).get("modelos")
    return modelo in [str(m) for m in vistos] if isinstance(vistos, list) else False


def apuntar_modelo(raiz, modelo):
    """Consume el «una sola vez» del modelo nuevo. Se llama al IMPRIMIR el aviso, jamás antes."""
    if not modelo:
        return
    datos = leer_memoria(raiz)
    vistos = datos.get("modelos")
    vistos = [str(m) for m in vistos] if isinstance(vistos, list) else []
    if modelo in vistos:
        return
    vistos.append(modelo)
    datos["modelos"] = vistos[-50:]
    guardar_memoria(raiz, datos)


def turno_del_ultimo_aviso(raiz, fichero):
    """En qué turno de ESTA sesión habló el hook `Stop` por última vez (0 si nunca)."""
    hablado = leer_memoria(raiz).get("hook_stop")
    if not isinstance(hablado, dict) or not fichero:
        return 0
    valor = hablado.get(str(fichero))
    return int(valor) if isinstance(valor, (int, float)) and valor > 0 else 0


def apuntar_aviso(raiz, fichero, turnos):
    """Apunta el turno en el que el hook `Stop` acaba de hablar, para esta sesión."""
    if not fichero:
        return
    datos = leer_memoria(raiz)
    hablado = datos.get("hook_stop")
    hablado = dict(hablado) if isinstance(hablado, dict) else {}
    hablado[str(fichero)] = int(turnos)
    # Se guardan las 20 sesiones más recientes: la memoria es una nota, no un archivo.
    datos["hook_stop"] = dict(list(hablado.items())[-20:])
    guardar_memoria(raiz, datos)


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

# Bug 075: la terminal también escribe. Con un modo de permisos que manda usar Bash (sed,
# heredocs, tee, python3 -) en vez de Edit/Write, ninguna escritura contaba y el canario
# gritaba «N turnos sin tocar un fichero» en una sesión que acababa de fusionar dos unidades.
# Un comando de Bash toca un fichero si lleva una de estas formas. Las redirecciones de
# stderr (`2>&1`, `2>/dev/null`) y a `/dev/null` NO son escrituras: se descartan antes.
HERRAMIENTAS_DE_SHELL = {"bash", "shell", "run_shell_command", "execute_command", "terminal"}
_SIN_RUIDO = re.compile(r"\d?>\s*&\d|\d?>>?\s*/dev/null")
ESCRITURAS_DESDE_BASH = re.compile(
    r"(?:^|[\s;&|(])(?:sed\s+-[a-zA-Z]*i|tee\b|cp\b|mv\b|rm\b|mkdir\b|touch\b|rmdir\b|"
    r"install\b|patch\b|git\s+(?:commit|mv|rm|merge|rebase|cherry-pick|revert|reset|checkout|"
    r"restore|stash|apply|am|pull|clone|worktree|init)\b|"
    r"python3?\s+-\s*<<|python3?\s+-c\b.*(?:write_text|write_bytes|open\([^)]*['\"][wa])|"
    r"pip3?\s+install\b|npm\s+(?:install|ci)\b)|"
    r"(?<![\d&])>>?(?!\s*&)|<<-?\s*['\"]?\w+['\"]?", re.S)


def bash_escribe(comando):
    """¿Este comando de terminal toca un fichero? Heurística por texto, sin ejecutar nada."""
    if not comando:
        return False
    limpio = _SIN_RUIDO.sub(" ", comando)
    return bool(ESCRITURAS_DESDE_BASH.search(limpio))

# Herramientas que EJECUTAN algo: son las únicas cuyo TEXTO de salida puede leerse como
# fallo (bug 062, hueco H3 del revisor). Un `Read` o un `Grep` devuelven el contenido del
# proyecto, y casi cualquier fuente lleva dentro las palabras `error`, `failed` o `denied`:
# aplicarles la heurística convertía releer un fichero tres veces —rutina— en «la sesión YA
# está degradando». Para lo que no ejecuta sigue valiendo el `is_error` del harness, que es
# un hecho y no una heurística.
HERRAMIENTAS_QUE_EJECUTAN = {"bash", "shell", "local_shell", "exec", "execute", "run",
                             "run_command", "run_terminal_cmd", "terminal", "powershell",
                             "container.exec", "bashoutput", "killshell"}


# --------------------------------------------------------------------------- incidentes (072)
#
# Hay degradaciones que no son una racha ni un comando repetido: son un ACCIDENTE. Pasa una
# vez —te equivocas de carpeta, deshaces commits, resuelves un conflicto a mano, escondes
# cambios en un `stash`, escribes dentro de `main/`— y a partir de ahí el agente sigue
# trabajando sobre una realidad que ya no es la que cree. gentle-ai lo tiene escrito como
# «Delegation Stop Rules» (`docs/intended-usage.md`): tras un accidente de cwd/git/merge/
# entorno, auditoría fresca. Aquí no se ventana: un accidente no caduca dentro de su sesión.
#
# Dos acciones, y cuál toca depende del patrón: perderse de carpeta es desorientación (se
# corta), tocar la historia de git es trabajo que puede haberse perdido (se audita).
ACCION_CORTAR = "corta y sigue en una sesión NUEVA: esta ya no sabe dónde está"
ACCION_REVISION = "pide una revisión fresca de lo que llevas antes de seguir"

# `cd` que se va a una carpeta que no existe. La marca se busca en la SALIDA y pegada a la
# palabra `cd` a propósito: un «No such file or directory» suelto lo suelta cualquier `cat`
# de un fichero que no está, y eso es rutina, no desorientación.
CD_A_CIEGAS = re.compile(r"(?:^|[;&|(]\s*)cd\s+(?!-)\S+", re.I)
FALLO_DE_CD = re.compile(
    r"cd(?::| to)[^\n]*?(?:no such file or directory|not a directory|no existe|"
    r"not found|blocked|denied)", re.I)

# Deshacer trabajo. `git restore --staged` solo saca del índice: no borra nada escrito.
GIT_DESTRUCTIVO = re.compile(
    r"git\s+(?:-C\s+\S+\s+)*"
    r"(?:reset\s+--hard|checkout\s+--\s|restore\s+(?!--staged\b))(?:\s*\S+)?", re.I)

# Esconder cambios. `list`/`show` solo miran, y mirar no es esconder.
GIT_STASH = re.compile(
    r"git\s+(?:-C\s+\S+\s+)*stash\b(?!\s+(?:list|show))", re.I)

# Un conflicto solo cuenta si lo produjo un comando que PUEDE producirlo: si no, el texto
# «CONFLICT» de cualquier log o fichero leído bastaría para gritar.
GIT_QUE_FUSIONA = re.compile(
    r"git\s+(?:-C\s+\S+\s+)*(?:merge|rebase|cherry-pick|pull|revert|am|apply|"
    r"stash\s+(?:pop|apply))\b", re.I)
MARCA_DE_CONFLICTO = re.compile(
    r"^CONFLICT \(|Automatic merge failed|Unmerged paths|both modified:", re.M)

# `main/` es el clon canónico: solo `git pull`. Dos formas de escribir dentro, y las dos
# medidas contra 63 transcripts reales de este workspace antes de darlas por buenas:
#
#   · un git que MUTA lanzado con `-C …/main`. Fuera de la lista quedan `pull`, `branch`,
#     `worktree add` y `push`: actualizar el clon, mirar sus ramas y colgarle un worktree
#     son justo el uso normal de `main/`, y meterlos disparaba en 24 de 63 sesiones sanas.
#     El `(?![\w-])` no es adorno: sin él, `merge-base` —una CONSULTA— se leía como `merge`.
#     `merge` tampoco está: el del paso 3 del cierre sin `gh` es la ÚNICA excepción nombrada
#     y acotada del método (ADR-009), y avisar ahí sería gritar en todos los cierres —37 de
#     los 44 disparos medidos eran justo eso—. Si ese merge choca, lo coge `conflicto`.
#   · un comando cuyo DESTINO es una ruta `main/…`. Se exige que main/ sea el destino y no
#     un argumento cualquiera: `cp main/x .` y un `python3 - <<EOF` que solo menciona
#     `main/visor/…` de pasada leen, no escriben (44 falsos positivos medidos así).
GIT_MUTA = (r"commit|add|rebase|cherry-pick|revert|reset|checkout|restore|stash|"
            r"apply|am|rm|mv|clean")
GIT_MUTA_EN_MAIN = re.compile(
    r"git\s+-C\s+\S*?main/?\s+(?:" + GIT_MUTA + r")(?![\w-])", re.I)
ESCRITURA_EN_MAIN = re.compile(
    r">>?\s*(?:\./)?main/\S"
    r"|sed\s+-[a-zA-Z]*i\b[^|;&\n]*?\s(?:\./)?main/\S"
    r"|\b(?:tee|rm|rmdir|mkdir|touch|chmod|chown|patch)\b[^|;&\n]*?\s(?:\./)?main/\S"
    r"|\b(?:cp|mv|install)\b[^|;&\n]*\s(?:\./)?main/\S*\s*(?:$|[|;&])", re.I | re.M)
FICHERO_EN_MAIN = re.compile(r"(?:^|/)main/")

# Lo que hace un SUBAGENTE no es de esta sesión (R3): su recibo viaja DENTRO de la salida
# del comando que lo lanzó, con sus propios `git stash` y sus propios CONFLICT.
HERRAMIENTAS_DE_SUBAGENTE = {"task", "agent", "dispatch_agent", "subagent"}
LANZA_SUBAGENTE = re.compile(r"\bejecucion\.py\b|\bclaude\s+-p\b|\bcodex\s+exec\b", re.I)

# Orden de severidad: con varios patrones a la vez manda el primero de esta lista.
ORDEN_INCIDENTES = ("escritura_en_main", "git_destructivo", "conflicto", "stash",
                    "cwd_erroneo")

DETALLES_INCIDENTE = {
    "cwd_erroneo": "{veces} veces `cd` a una carpeta que no existe: {comando}",
    "git_destructivo": "se ha deshecho trabajo con git: {comando}",
    "conflicto": "un conflicto de merge resuelto dentro de esta sesión: {comando}",
    "stash": "`git stash` (prohibido por el runbook de cierre): {comando}",
    "escritura_en_main": "escritura dentro de `main/`, que es de solo lectura: {comando}",
}

ACCIONES_INCIDENTE = {
    "cwd_erroneo": ACCION_CORTAR,
    "git_destructivo": ACCION_REVISION,
    "conflicto": ACCION_REVISION,
    "stash": ACCION_REVISION,
    "escritura_en_main": ACCION_REVISION,
}


def es_de_subagente(herramienta, comando):
    """¿Este turno delega en otro agente? Entonces lo que salga es suyo, no de esta sesión."""
    if (herramienta or "").lower() in HERRAMIENTAS_DE_SUBAGENTE:
        return True
    return bool(comando and LANZA_SUBAGENTE.search(str(comando)))


def _pillado(patron, encaje):
    """(patrón, el TROZO que lo delató). Enseñar el trozo y no el comando entero importa:
    un comando de campo son 400 caracteres y el `git checkout --` está en el medio."""
    return patron, _sin_ruido(encaje.group(0))[:120]


def incidente_por_comando(herramienta, comando, fichero=None):
    """El patrón que se ve con solo mirar lo que se ordenó (sin esperar a la salida)."""
    herramienta = (herramienta or "").lower()
    if fichero and herramienta in HERRAMIENTAS_DE_FICHERO and FICHERO_EN_MAIN.search(
            str(fichero).replace("\\", "/")):
        return "escritura_en_main", str(fichero)[:120]
    if not comando or herramienta not in HERRAMIENTAS_QUE_EJECUTAN:
        return None, None
    comando = str(comando)
    if es_de_subagente(herramienta, comando):
        return None, None
    for regex, patron in ((GIT_MUTA_EN_MAIN, "escritura_en_main"),
                          (ESCRITURA_EN_MAIN, "escritura_en_main"),
                          (GIT_DESTRUCTIVO, "git_destructivo"),
                          (GIT_STASH, "stash")):
        encaje = regex.search(comando)
        if encaje:
            return _pillado(patron, encaje)
    return None, None


def incidente_por_salida(herramienta, comando, salida):
    """El patrón que solo delata la SALIDA: el `cd` que no llegó y el merge que chocó."""
    herramienta = (herramienta or "").lower()
    if not salida or herramienta not in HERRAMIENTAS_QUE_EJECUTAN:
        return None, None
    comando = str(comando or "")
    if es_de_subagente(herramienta, comando):
        return None, None
    if CD_A_CIEGAS.search(comando) and FALLO_DE_CD.search(salida):
        return _pillado("cwd_erroneo", CD_A_CIEGAS.search(comando))
    if GIT_QUE_FUSIONA.search(comando) and MARCA_DE_CONFLICTO.search(salida):
        return _pillado("conflicto", GIT_QUE_FUSIONA.search(comando))
    return None, None


def apuntar_incidente(incidentes, hallazgo, turno):
    """Añade el accidente a la lista de la sesión, con el turno en el que ocurrió."""
    patron, trozo = hallazgo
    if not patron:
        return
    incidentes.append({"patron": patron, "turno": turno, "comando": trozo or "—"})


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
    eso aquí el fallo se lee igual que en Codex: por el CONTENIDO —pero SOLO en las
    herramientas que ejecutan algo (`HERRAMIENTAS_QUE_EJECUTAN`), nunca en las que leen o
    buscan, cuyo texto es el del propio proyecto—. Y de paso se recogen las tres señales de
    atasco que no dejan ni una línea de error (R3).
    """
    modelo, tokens, turnos = None, None, 0
    comandos, fallos = {}, []
    ediciones, pruebas, turnos_secos, incidentes = [], [], [], []
    # Turno en el que se ordenó cada cosa: el parte de retomada tiene que poder decir
    # DÓNDE pasó el accidente, y `turnos` solo cuenta los mensajes que traen `usage`.
    turno = 0
    for dato in _lineas(fichero):
        mensaje = dato.get("message")
        if not isinstance(mensaje, dict):
            continue
        if dato.get("type") == "assistant" or mensaje.get("role") == "assistant":
            turno += 1
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
        herramientas, toco_fichero, sin_evidencia = 0, False, False
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
                elif nombre.lower() in HERRAMIENTAS_DE_SHELL:
                    # Bug 075: la terminal también escribe. Y si el harness no guardó el
                    # comando, este turno no es evidencia de nada: ni seco ni húmedo.
                    comando_shell = entrada.get("command")
                    if not comando_shell:
                        sin_evidencia = True
                    elif bash_escribe(str(comando_shell)):
                        toco_fichero = True
                orden = entrada.get("command") or fichero_tocado or entrada.get(
                    "pattern") or json.dumps(entrada, sort_keys=True, ensure_ascii=False)
                comandos[bloque.get("id")] = (
                    nombre.lower(), f"{nombre}: {normalizar_comando(orden)}"[:200],
                    entrada.get("command"), turno)
                apuntar_incidente(
                    incidentes,
                    incidente_por_comando(nombre, entrada.get("command"), fichero_tocado),
                    turno)
            elif bloque.get("type") == "tool_result":
                par = comandos.get(bloque.get("tool_use_id"))
                if not par:
                    continue
                herramienta, orden, crudo, turno_orden = par
                texto = _texto_de(bloque.get("content"))
                apuntar_incidente(incidentes,
                                  incidente_por_salida(herramienta, crudo, texto),
                                  turno_orden)
                # H3: la heurística por CONTENIDO solo para lo que ejecuta. Lo que lee o
                # busca únicamente falla si el harness lo dice con el booleano.
                roto = bool(bloque.get("is_error")) or bool(
                    herramienta in HERRAMIENTAS_QUE_EJECUTAN
                    and MARCAS_DE_FALLO.search(texto))
                if roto:
                    fallos.append((orden, _firma(texto)))
                if MARCAS_DE_TEST.search(orden):
                    # Verde = ni error ni marca de fallo Y la palabra que dice que pasó.
                    verde = not roto and bool(re.search(r"\b(?:ok|passed|passing|all tests)\b",
                                                        texto, re.I))
                    pruebas.append((orden, verde))
        if herramientas and (toco_fichero or not sin_evidencia):
            turnos_secos.append(toco_fichero)
    if tokens is None:
        return None
    return {"modelo": modelo, "tokens": tokens, "ventana": None, "fallos": fallos,
            "turnos": turnos, "ediciones": ediciones, "pruebas": pruebas,
            "turnos_secos": turnos_secos, "incidentes": incidentes}


def leer_codex(fichero):
    """Uso de contexto y pares comando/fallo de un rollout de Codex CLI.

    `last_token_usage.total_tokens` es lo que ocupa la ÚLTIMA petición, o sea el contexto
    vivo; `total_token_usage` es acumulado de toda la sesión y supera la ventana sin que
    eso signifique nada. La ventana la declara el propio rollout: aquí no hace falta tabla.
    """
    tokens, ventana, modelo, turnos = None, None, None, 0
    comandos, fallos, incidentes = {}, [], []
    turno = 0
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
            turno += 1
            orden_cruda = _orden(crudo)
            comandos[payload.get("call_id")] = (
                f"{payload.get('name')}: {normalizar_comando(orden_cruda)}"[:200],
                orden_cruda, turno)
            # Codex ejecuta siempre por shell: aquí la herramienta se da por ejecutora.
            apuntar_incidente(incidentes,
                              incidente_por_comando("shell", orden_cruda), turno)
        elif tipo in ("function_call_output", "custom_tool_call_output"):
            texto = _texto_de(payload.get("output"))
            par = comandos.get(payload.get("call_id"))
            orden = par[0] if par else None
            if orden and MARCAS_DE_FALLO.search(texto):
                fallos.append((orden, _firma(texto)))
            if par:
                apuntar_incidente(incidentes,
                                  incidente_por_salida("shell", par[1], texto), par[2])
        elif tipo is None and dato.get("type") == "session_meta":
            modelo = payload.get("model") or modelo
    if tokens is None:
        return None
    # Codex no publica ediciones ni tests por separado: sus señales de atasco son las
    # mismas repeticiones de siempre. Las claves viajan vacías para que el veredicto no
    # tenga que preguntar de qué harness viene. Los accidentes, en cambio, se leen igual
    # que en Claude Code: son comandos de terminal y aquí también se ven.
    return {"modelo": modelo, "tokens": tokens, "ventana": ventana, "fallos": fallos,
            "turnos": turnos, "ediciones": [], "pruebas": [], "turnos_secos": [],
            "incidentes": incidentes}


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


def detectar_incidentes(incidentes, config):
    """R1 de la 072: el accidente que ya ha pasado en esta sesión.

    A diferencia de las rachas, esto NO se mide en una ventana reciente: un `git stash` de
    hace cien turnos sigue escondiendo lo que escondió, y una carpeta equivocada sigue
    siendo la carpeta desde la que se trabajó. Un accidente no caduca dentro de su sesión.

    Con varios patrones a la vez manda el más grave (`ORDEN_INCIDENTES`), y se nombra la
    ÚLTIMA vez que pasó: es la que la sesión nueva tiene que auditar primero.
    """
    if not incidentes:
        return None
    for patron in ORDEN_INCIDENTES:
        casos = [i for i in incidentes if i["patron"] == patron]
        if len(casos) < int(config.get(patron, DEFECTOS.get(patron, 1))):
            continue
        ultimo = casos[-1]
        detalle = DETALLES_INCIDENTE[patron].format(veces=len(casos),
                                                    comando=ultimo["comando"] or "—")
        return {"tipo": "incidente", "patron": patron, "veces": len(casos),
                "turno": ultimo["turno"], "sujeto": ultimo["comando"],
                "detalle": detalle, "accion": ACCIONES_INCIDENTE[patron]}
    return None


def diagnosticar(*, raiz=None, cwd=None, claude_projects=None, codex_sessions=None,
                 transcript=None):
    """Informe completo de la sesión más reciente. Nunca lanza: como mucho, `sin_datos`.

    `transcript` es el atajo barato del hook `Stop`: el harness ya dice qué fichero está
    escribiendo, así que no hace falta rastrear ninguna carpeta.

    Sin efectos de lado: diagnosticar solo MIRA. El «una sola vez» del modelo nuevo se gasta
    al imprimir el aviso, no al calcularlo (hueco H1 del revisor).
    """
    raiz = Path(raiz or RAIZ)
    cwd = Path(cwd or Path.cwd())
    por_defecto = _rutas_por_defecto()
    claude_projects = Path(claude_projects or por_defecto[0])
    codex_sessions = Path(codex_sessions or por_defecto[1])
    config = cargar_config(raiz)
    informe = {"harness": None, "fichero": None, "modelo": None, "tokens": None,
               "ventana": None, "porcentaje": None, "umbral": config["umbral_default"],
               "veredicto": "sin_datos", "sintoma": None, "incidentes": [],
               "candidatos": 0,
               "turnos": None, "turnos_aviso": config["turnos_aviso"],
               "ventana_incoherente": None, "ventana_asumida": False,
               "avisar_modelo": False,
               "raiz": str(raiz),
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

    # Los accidentes van los ÚLTIMOS a propósito: los avisos de siempre —el comando
    # repetido y el atasco sin error— no cambian ni de forma ni de prioridad por esto.
    informe["incidentes"] = señal.get("incidentes") or []
    informe["sintoma"] = (detectar_sintomas(señal["fallos"], config)
                          or detectar_atasco(señal, config)
                          or detectar_incidentes(informe["incidentes"], config))
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
    """El texto que ve el usuario. Vacío = silencio: sin sesión no se dice nada.

    Aquí —y solo aquí— se gasta el «una sola vez» del modelo nuevo: la memoria se consume
    cuando el aviso SE ESCRIBE. Si el texto sale vacío, no se ha dicho nada y el aviso sigue
    pendiente para la próxima (hueco H1 del revisor).
    """
    return con_aviso_de_modelo(informe, _cuerpo_veredicto(informe))


def con_aviso_de_modelo(informe, cuerpo):
    """El cuerpo con la nota del modelo nuevo delante, y la memoria gastada al ponerla."""
    if not cuerpo or not informe.get("avisar_modelo"):
        return cuerpo
    apuntar_modelo(informe.get("raiz") or RAIZ, informe["modelo"])
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
        if sintoma.get("tipo") == "incidente":
            return AVISO_INCIDENTE.format(detalle=sintoma["detalle"],
                                          turno=sintoma["turno"],
                                          accion=sintoma["accion"], contexto=contexto,
                                          fichero=informe["fichero"])
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


def texto_retomada(raiz=None, *, incidentes=None):
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
    if incidentes:
        # R2 de la 072: la sesión nueva tiene que saber qué le pasó a la vieja —el patrón,
        # el turno y qué hacer—, o repetirá el trabajo sobre el mismo suelo movido. Una
        # línea por PATRÓN, no por vez: cuatro `git checkout --` seguidos son un solo
        # accidente que auditar, y el parte cabe en una pantalla o no lo lee nadie.
        partes.append("## Incidentes de la sesión anterior\n\n" + "\n".join(
            f"- turno {casos[-1]['turno']} · {patron}"
            + (f" ({len(casos)} veces)" if len(casos) > 1 else "")
            + f": {casos[-1]['comando']} → {ACCIONES_INCIDENTE.get(patron, ACCION_REVISION)}"
            for patron, casos in _por_patron(incidentes)))
    parte = "\n\n".join(partes) + "\n"
    return _capar(parte)


def _por_patron(incidentes):
    """Los accidentes agrupados por patrón, en el orden en que ocurrió el primero de cada uno."""
    grupos = {}
    for incidente in incidentes:
        grupos.setdefault(incidente["patron"], []).append(incidente)
    return list(grupos.items())


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
    que este script existe para no generar, así que la capacidad y la posición se dicen cada
    N turnos. La conducta no espera turno: repetirse ya está pasando. Y el modelo nuevo
    tampoco espera (hueco H1): si esperase a un veredicto que no sea `sano`, con el hook
    sembrado el aviso podría no verlo nadie — la ceguera de R1, ahora en silencio.

    «Cada N turnos» se cuenta contra el ÚLTIMO turno en el que se habló, no con un
    `turnos % N` (hueco H2 del revisor): un `Stop` cubre una cadena entera de herramientas,
    así que la cuenta de turnos salta de varias en varias y puede no caer NUNCA en un
    múltiplo exacto. Medido sobre tres sesiones reales: 989 turnos / 33 paradas → cero
    avisos. Con el resto (`turnos - ultimo >= N`) el aviso llega en la primera parada que
    pase de largo.
    """
    salida = {"continue": True}
    if informe["veredicto"] == "sin_datos":
        return salida
    raiz = informe.get("raiz") or RAIZ
    if informe["veredicto"] == "sintomas" or informe.get("avisar_modelo"):
        mensaje = texto_veredicto(informe)
        if mensaje:
            salida["systemMessage"] = mensaje
            apuntar_aviso(raiz, informe.get("fichero"), informe.get("turnos") or 0)
        return salida
    if informe["veredicto"] == "sano":
        return salida
    turnos = informe.get("turnos") or 0
    cada = max(1, int(config["turnos_hook"]))
    ultimo = turno_del_ultimo_aviso(raiz, informe.get("fichero"))
    if ultimo > turnos:                 # la sesión se reinició bajo el mismo nombre
        ultimo = 0
    if turnos < cada or turnos - ultimo < cada:
        return salida
    mensaje = texto_veredicto(informe)
    if mensaje:
        salida["systemMessage"] = mensaje
        apuntar_aviso(raiz, informe.get("fichero"), turnos)
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
        # El parte mira TAMBIÉN la sesión, no solo los papeles: sin los accidentes, la
        # sesión nueva empieza a ciegas sobre lo que la vieja movió (072).
        informe = diagnosticar(raiz=raiz, cwd=args.cwd or Path.cwd())
        print(texto_retomada(raiz, incidentes=informe["incidentes"]))
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
        mensaje = texto_veredicto(informe) if informe["veredicto"] == "sintomas" else ""
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
            # El cuerpo se ha rehecho a mano: la nota del modelo nuevo se le pone aquí, que
            # es donde de verdad se imprime (H1: la memoria se gasta al decirlo).
            mensaje = con_aviso_de_modelo(informe, mensaje)
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
