#!/usr/bin/env python3
"""Lectura única y confinada de ``repos.yaml``.

``ruta_local`` siempre es una ruta relativa directa del workspace. No se aceptan rutas
absolutas, ``..`` ni componentes symlink: todos los consumidores obtienen así exactamente
la misma frontera antes de pasar la ruta a Git o escribir en ella.
"""

import re
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


def plan_de_modelo(carril, rol, *, documental=False):
    """(modelo, esfuerzo) que la regla 10 le toca a este carril y este rol.

    `documental=True` gana al carril: una unidad documental no toca código en ningún carril,
    así que su modelo es el pequeño se despache como se despache.
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
    if documental:
        return PlanDeModelo(MODELO_PEQUENO, ESFUERZO_DOCUMENTAL)
    return PlanDeModelo(ROLES_CON_MODELO[rol], ESFUERZO_POR_CARRIL[nombre])


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
