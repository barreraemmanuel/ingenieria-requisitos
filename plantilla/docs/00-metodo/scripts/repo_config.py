#!/usr/bin/env python3
"""Lectura única y confinada de ``repos.yaml``.

``ruta_local`` siempre es una ruta relativa directa del workspace. No se aceptan rutas
absolutas, ``..`` ni componentes symlink: todos los consumidores obtienen así exactamente
la misma frontera antes de pasar la ruta a Git o escribir en ella.
"""

import json
import re
import shutil
import subprocess
import unicodedata
from collections import namedtuple
from pathlib import Path, PureWindowsPath

import workspace_paths


class RepoConfigError(ValueError):
    pass


# --------------------------------------------------------- el vocabulario cerrado de la unidad
# `TIPOS` y `ESTADOS` estaban escritos DOS veces en código —`unidad.py` como listas,
# `lint_metodo.py` como conjuntos— y una tercera en la prosa de `00-metodo/README.md`. Coincidían
# por suerte: nada lo comprobaba, y la tercera copia ya había derivado (`en_validacion` vivía en
# el código y no en el README). Viven aquí, en el módulo que ya importan los catorce scripts,
# porque una junta que no se puede desalinear no hay que vigilarla (unidad 050).
#
# Son TUPLAS, no conjuntos: el orden es el del ciclo de vida y el de la ayuda de `unidad.py
# nueva`, y un conjunto lo perdía. Quien necesite operaciones de conjunto hace `set(...)`.
TIPOS = ("bug", "feature", "refactor", "migracion", "auditoria", "investigacion",
         "documentacion")
# `en_validacion` NO está en vuelo (ADR-010): su rama ya está fusionada y lo único pendiente es
# que el usuario pruebe la app.
ESTADOS_UNIDAD = ("planificada", "en_obra", "en_revision", "en_validacion", "mergeada",
                  "bloqueada", "descartada")


# Política de publicación del workspace (unidad 018). `agente` es el comportamiento de
# siempre: el método empuja la rama y abre el PR. `usuario` significa que publicar es cosa
# de la persona, y entonces el método se detiene en el commit/merge local y le deja el
# comando exacto. Ausente ⇒ `agente`: ningún workspace existente necesita migrar.
MODOS_PUSH = ("agente", "usuario")


# --------------------------------------------------------------- regla 10: modelo y esfuerzo
# «Esfuerzo y modelo por carril» (AGENTS.md regla 10, ADR-016) era una regla sin ejecutor: el
# lanzador tenía `--modelo` opcional y ningún `--esfuerzo`, así que sin flag TODO subagente
# salía con el modelo por defecto del harness —el más caro— y la regla vivía en la cabeza de
# quien despachaba. La tabla vive aquí, junto al resto de la política del workspace, para que
# `ejecucion.py` la DERIVE del carril de la ficha en vez de esperar a que alguien la teclee.
#
# Los valores son los que decidió Nate el 25-08 («prefiero Opus para los subagentes»):
MODELO_CONSTRUCTOR = "claude-opus-5"
# El revisor NO puede compartir modelo con el constructor: dos instancias del mismo comparten
# puntos ciegos, y esa es toda la razón de ser de la revisión fresca (regla 10, ADR-017).
MODELO_REVISOR = "claude-fable-5"
MODELO_REVISOR_ALTERNATIVO = "claude-sonnet-5"
# Lint y unidades documentales: el pequeño. No hay código que razonar, hay texto que ordenar.
MODELO_PEQUENO = "claude-haiku-4-5"

# El esfuerzo sale del carril, tal cual lo escribe la regla 10: «Exprés y directo: el modelo y
# el razonamiento más baratos que hagan el trabajo. Normal: medio. Completo y hotfix: el alto».
ESFUERZO_POR_CARRIL = {
    "directo": "bajo",
    "expres": "bajo",
    "normal": "medio",
    "completo": "alto",
    "hotfix": "alto",
}
CARRILES = tuple(ESFUERZO_POR_CARRIL)
ESFUERZO_DOCUMENTAL = "bajo"

ROLES_CON_MODELO = {
    "constructor": MODELO_CONSTRUCTOR,
    "revisor": MODELO_REVISOR,
}

# ------------------------------------------------------- la MISMA regla 10, en Codex (100)
# `roles.md` daba a Codex por INEJECUTABLE bajo la regla 10: «la tabla son identificadores de
# Anthropic». Era cierto y dejaba medio método atado a un solo harness. La salida NO es una
# segunda lista de slugs escrita a mano —los de OpenAI cambian de nombre cada pocas semanas y
# una lista congelada envejece sin que nadie se entere—: es DERIVAR la tabla del catálogo que
# el propio binario instalado imprime con `codex debug models`.
#
# La derivación es por POSICIÓN, no por nombre, y así no hay un solo slug en este fichero:
#
#   constructor  el de `priority` más baja de los visibles — el que Codex pone primero.
#   revisor      el SIGUIENTE. La regla 10 prohíbe que revisor y constructor compartan
#                modelo (dos instancias del mismo comparten puntos ciegos), así que si el
#                catálogo trae uno solo esto no se apaña: se para.
#   pequeño      el de `priority` más alta — el último de la lista, para documental y lint.
#
# `visibility: hide` se descarta: el binario marca así los modelos que no son para elegir a
# mano (los de reserva y el de auto-revisión). Ni siquiera COMO EJEMPLO se escribe aquí un
# identificador de OpenAI: un test lo prohíbe, porque un slug escrito es un slug que alguien
# copiará el día que el catálogo falle.
HARNESS_CON_TABLA = ("claude", "codex")

# El esfuerzo del método (bajo/medio/alto) al vocabulario de Codex. Es traducción, no
# decisión: el carril sigue mandando.
ESFUERZO_CODEX = {"bajo": "low", "medio": "medium", "alto": "high"}
# De menos a más, para ajustar cuando un modelo no admita el nivel exacto que toca.
ESCALA_CODEX = ("low", "medium", "high", "xhigh", "max", "ultra")

CatalogoCodex = namedtuple("CatalogoCodex", "constructor revisor pequeno esfuerzos")

# Caché de SESIÓN: `codex debug models` imprime ~350 KB y el lanzador preguntaría por cada
# rol. Se consulta una vez por proceso y ejecutable.
_CATALOGO_CODEX = {}


def olvidar_catalogo_codex():
    """Vacía la caché de sesión del catálogo (los tests y el Modo D la necesitan)."""
    _CATALOGO_CODEX.clear()


def _ejecutable_codex(ejecutable=None):
    encontrado = ejecutable or shutil.which("codex")
    if not encontrado:
        raise RepoConfigError(
            "no encuentro el ejecutable `codex` y la tabla de la regla 10 para ese harness "
            "sale de su catálogo. SALIDA: instala Codex CLI y compruébalo con "
            "`codex --version`, o lanza con `--harness claude`"
        )
    return encontrado


def catalogo_codex(ejecutable=None, *, refrescar=False):
    """(constructor, revisor, pequeño, esfuerzos) derivados de `codex debug models`.

    Los slugs no se memorizan: se consultan al binario instalado, que es la única fuente
    que no envejece. `esfuerzos` es {slug: (por_defecto, (admitidos…))}.
    """
    binario = _ejecutable_codex(ejecutable)
    if refrescar:
        _CATALOGO_CODEX.pop(binario, None)
    if binario in _CATALOGO_CODEX:
        return _CATALOGO_CODEX[binario]

    try:
        salida = subprocess.run(
            [binario, "debug", "models"], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except OSError as exc:
        raise RepoConfigError(
            f"no pude preguntarle el catálogo de modelos a codex: {exc}. SALIDA: comprueba "
            f"`codex debug models` a mano, o lanza con `--harness claude`"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RepoConfigError(
            "`codex debug models` no respondió en 60 s. SALIDA: ejecútalo a mano para ver "
            "qué le pasa, o lanza con `--harness claude`"
        ) from exc
    if salida.returncode != 0:
        raise RepoConfigError(
            f"`codex debug models` falló (exit {salida.returncode}): "
            f"{(salida.stderr or salida.stdout).strip()[:200] or 'sin salida'}. SALIDA: "
            f"ejecuta `codex debug models` a mano para ver el error completo, o lanza con "
            f"`--harness claude`"
        )
    try:
        modelos = json.loads(salida.stdout)["models"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RepoConfigError(
            f"no entiendo lo que imprime `codex debug models` ({exc}): se esperaba un JSON "
            f"con la clave `models`. SALIDA: ejecuta `codex debug models` a mano y compara "
            f"con lo que espera esta versión del método, o lanza con `--harness claude`"
        ) from exc

    visibles = [m for m in modelos if (m or {}).get("visibility") == "list" and m.get("slug")]
    # `priority` puede faltar en un catálogo futuro: el orden del propio binario es el
    # desempate, y así un modelo sin prioridad no se cuela el primero.
    ordenados = sorted(
        enumerate(visibles),
        key=lambda par: (par[1].get("priority", 10 ** 6), par[0]),
    )
    ordenados = [modelo for _, modelo in ordenados]
    if len(ordenados) < 2:
        raise RepoConfigError(
            f"`codex debug models` solo ofrece {len(ordenados)} modelo(s) elegible(s) y la "
            f"regla 10 exige que el revisor NO comparta modelo con el constructor. SALIDA: "
            f"comprueba tu cuenta con `codex debug models`, o lanza el revisor a mano con "
            f"`--modelo <slug> --motivo-modelo \"...\"`"
        )

    esfuerzos = {
        modelo["slug"]: (
            modelo.get("default_reasoning_level"),
            tuple(nivel.get("effort") for nivel in modelo.get("supported_reasoning_levels")
                  or () if nivel.get("effort")),
        )
        for modelo in ordenados
    }
    catalogo = CatalogoCodex(ordenados[0]["slug"], ordenados[1]["slug"],
                             ordenados[-1]["slug"], esfuerzos)
    _CATALOGO_CODEX[binario] = catalogo
    return catalogo


def _esfuerzo_codex(slug, esfuerzo, esfuerzos):
    """El nivel del carril, traducido y ajustado a lo que ESE modelo admite."""
    pedido = ESFUERZO_CODEX.get(esfuerzo, esfuerzo)
    por_defecto, admitidos = esfuerzos.get(slug, (None, ()))
    if not admitidos or pedido in admitidos:
        return pedido
    # Un modelo que no admite el nivel exacto no es motivo para parar un despacho: se coge
    # el admitido más cercano hacia arriba, y si no hay, el más alto que tenga. Lo que
    # corrió de verdad lo dirá el recibo, que es donde se comprueba la regla 10.
    if pedido in ESCALA_CODEX:
        indice = ESCALA_CODEX.index(pedido)
        arriba = [n for n in admitidos if n in ESCALA_CODEX[indice:]]
        if arriba:
            return min(arriba, key=ESCALA_CODEX.index)
    conocidos = [n for n in admitidos if n in ESCALA_CODEX]
    return max(conocidos, key=ESCALA_CODEX.index) if conocidos else (
        por_defecto or admitidos[0])

# `esfuerzo` viaja aunque hoy ningún harness admita un flag para él: el recibo lo guarda y el
# cierre lo enseña, que es lo que convierte la regla 10 en algo comprobable a posteriori. El
# día que un CLI lo acepte, el dato ya está calculado y en su sitio.
PlanDeModelo = namedtuple("PlanDeModelo", "modelo esfuerzo")


def normalizar_carril(carril):
    """`Exprés`, `EXPRES` y `expres` son el MISMO carril.

    El frontmatter lo teclea una persona y el acento entra y sale; comparar la cadena cruda
    contra la tabla convertía `carril: exprés` en «carril desconocido» y paraba un despacho
    legítimo por una tilde.
    """
    crudo = str(carril or "normal").strip().lower()
    sin_tildes = "".join(
        letra for letra in unicodedata.normalize("NFD", crudo)
        if not unicodedata.combining(letra)
    )
    return sin_tildes or "normal"


def plan_de_modelo(carril, rol, *, documental=False, harness="claude",
                  ejecutable_codex=None):
    """(modelo, esfuerzo) que la regla 10 le toca a este carril, este rol y este harness.

    `documental=True` gana al carril: una unidad documental no toca código en ningún carril,
    así que su modelo es el pequeño se despache como se despache.

    `harness="codex"` (unidad 100) devuelve un slug del catálogo del binario instalado y el
    esfuerzo en el vocabulario de Codex (low/medium/high). La REGLA es la misma —el carril
    manda, el revisor no repite modelo—; lo único que cambia es de dónde salen los nombres.
    """
    nombre = normalizar_carril(carril)
    if nombre not in ESFUERZO_POR_CARRIL:
        raise RepoConfigError(
            f"carril desconocido para la tabla de la regla 10: {carril!r}; los carriles con "
            f"modelo asignado son {' | '.join(CARRILES)}"
        )
    if rol not in ROLES_CON_MODELO:
        raise RepoConfigError(
            f"rol sin modelo en la tabla de la regla 10: {rol!r}; los roles delegados son "
            f"{' | '.join(sorted(ROLES_CON_MODELO))}"
        )
    if harness not in HARNESS_CON_TABLA:
        raise RepoConfigError(
            f"harness sin tabla en la regla 10: {harness!r}; los harness con tabla son "
            f"{' | '.join(HARNESS_CON_TABLA)}. SALIDA: lanza con `--harness "
            f"{HARNESS_CON_TABLA[0]}`"
        )
    esfuerzo = ESFUERZO_DOCUMENTAL if documental else ESFUERZO_POR_CARRIL[nombre]
    if harness == "claude":
        modelo = MODELO_PEQUENO if documental else ROLES_CON_MODELO[rol]
        return PlanDeModelo(modelo, esfuerzo)

    catalogo = catalogo_codex(ejecutable_codex)
    if documental:
        slug = catalogo.pequeno
    else:
        slug = catalogo.constructor if rol == "constructor" else catalogo.revisor
    return PlanDeModelo(slug, _esfuerzo_codex(slug, esfuerzo, catalogo.esfuerzos))


def value(text, key):
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*(.*?)\s*$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            result = match.group(1).strip().strip("\"'")
            if result.startswith("PENDIENTE"):
                return ""
            return result.split("  #", 1)[0].strip()
    return ""


def modo_push_de(text):
    """Valida y normaliza la clave `push:` de un repos.yaml ya leído."""
    crudo = value(text, "push") or "agente"
    if crudo not in MODOS_PUSH:
        raise RepoConfigError(
            f"repos.yaml: push inválido ({crudo!r}); valores válidos: "
            f"{' | '.join(MODOS_PUSH)}"
        )
    return crudo


def canonical_local_path(workspace, raw_path):
    root = Path(workspace).resolve()
    raw = str(raw_path or "").strip()
    candidate = Path(raw)
    windows = PureWindowsPath(raw)
    if not raw:
        raise RepoConfigError("repos.yaml: ruta_local ausente")
    if candidate.is_absolute() or windows.is_absolute() or windows.drive:
        raise RepoConfigError("repos.yaml: ruta_local debe ser relativa al workspace")
    if ".." in candidate.parts or ".." in windows.parts:
        raise RepoConfigError("repos.yaml: ruta_local no admite '..'")
    if candidate.parts in {(), (".",)}:
        raise RepoConfigError("repos.yaml: ruta_local no puede ser el workspace")

    try:
        resolved = workspace_paths.confined_path(
            root, root / candidate, label="repos.yaml: ruta_local"
        )
    except workspace_paths.WorkspacePathError as exc:
        raise RepoConfigError(str(exc)) from exc
    if resolved == root:
        raise RepoConfigError("repos.yaml: ruta_local no puede ser el workspace")
    return resolved


def _leer(workspace, *, require_file=False):
    """Texto de repos.yaml (o cadena vacía si no existe y no se exige)."""
    root = Path(workspace).resolve()
    config = root / "repos.yaml"
    if config.is_symlink():
        raise RepoConfigError("repos.yaml no puede ser symlink")
    if not config.is_file():
        if require_file:
            raise RepoConfigError("repos.yaml ausente")
        return root, ""
    try:
        return root, config.read_text(encoding="utf-8")
    except OSError as exc:
        raise RepoConfigError(f"repos.yaml ilegible: {exc}") from exc


def modo_push(workspace, *, require_file=False):
    """Política de publicación declarada en repos.yaml: `agente` (defecto) | `usuario`."""
    return modo_push_de(_leer(workspace, require_file=require_file)[1])


def repo_code(workspace, *, require_file=False):
    root, text = _leer(workspace, require_file=require_file)
    # Un `push:` inválido se descubre aquí, en la misma lectura que `rama_principal`: si
    # solo fallara en quien pregunta por el modo, media herramienta seguiría corriendo con
    # una política de publicación que nadie entiende.
    modo_push_de(text)
    raw_path = value(text, "ruta_local") or "main/"
    branch = value(text, "rama_principal") or "main"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) or ".." in branch.split("/"):
        raise RepoConfigError("repos.yaml: rama_principal inválida")
    return canonical_local_path(root, raw_path.rstrip("/")), branch
