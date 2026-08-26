#!/usr/bin/env python3
"""Control plane fail-closed para lanzar Claude o Codex en una unidad real.

Desde la 1.8.2 (ADR-033) es el lanzador del REVISOR fresco —su recibo acredita la firma— y
una vía OPCIONAL para el constructor (Codex, sesiones desatendidas). El constructor de
normal/completo es, por defecto, un subagente del propio padre: `unidad.py despachar` imprime
su encargo.

La unidad, el worktree y la rama se derivan; no se aceptan rutas ni argv arbitrarios.
El proceso nace siempre con el cwd, la rama y el entorno fijados por código (nunca por
shell intermedia) — es la garantía que evitó el incidente Aurora (ADR-022). No hay sandbox
de SO envolviendo al harness (unidad 012, ADR sucesor del 022): la frontera de escritura es
el cwd correcto más la disciplina del contrato, igual que ya confía el carril directo.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import control_plane
import lease as gestion_leases
import repo_config
import workspace_paths

control_plane.redactar_salidas()


RAIZ = Path(__file__).resolve().parents[3]
MAIN = RAIZ / "main"
WORKTREES = RAIZ / "worktrees"
ESTADOS_EJECUTABLES = {"en_obra", "en_revision"}

# R2 (034): `en_validacion` es ejecutable SOLO para el revisor. Una unidad que espera el OK
# del usuario y a la que el cierre le reclama un recibo de revisión no tenía forma de
# producirlo: la puerta pedía una evidencia que solo se generaba en un estado anterior al
# que la unidad ya tiene. Ocho unidades de este workspace quedaron así. Para el constructor
# sigue cerrado: lo entregado no se sigue construyendo por la puerta de atrás.
ESTADOS_REVISABLES = ESTADOS_EJECUTABLES | {"en_validacion", "mergeada"}

# R3 (065): estados en los que la unidad YA está entregada. Su worktree puede no existir —el
# cierre lo borra— y aun así hay que poder revisarla: es el caso de las 041-044, cuyo padre
# tuvo que recrear rama y worktree a mano para conseguir un revisor. Sobre estos estados, y
# SOLO para el revisor, el launcher se crea un worktree efímero detached sobre `fusion:`.
ESTADOS_ENTREGADOS = {"en_validacion", "mergeada"}

# Toda puerta escribe su vía de salida (ADR-029), y esa vía tiene que ARRANCAR: es lo que
# comprueba el test de R1 contra el argparse real de cada script.
SALIDA = "SALIDA:"
RE_NOMBRE = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")
RE_SKILL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")

# Estas skills deciden el proceso de trabajo. El método ya lo decide y nunca las importa,
# aunque el operador intente incluirlas en la allowlist técnica.
SKILLS_DE_PROCESO = {
    "brainstorming",
    "dispatching-parallel-agents",
    "executing-plans",
    "finishing-a-development-branch",
    "receiving-code-review",
    "requesting-code-review",
    "subagent-driven-development",
    "systematic-debugging",
    "test-driven-development",
    "using-git-worktrees",
    "using-superpowers",
    "verification-before-completion",
    "writing-plans",
}

HEREDAR_ENV = {
    "PATH", "TERM", "COLORTERM", "LANG", "LC_ALL", "LC_CTYPE",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "AWS_REGION", "AWS_DEFAULT_REGION", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    # Unidad 012: sin sandbox de SO ya no es la ÚNICA vía de autenticación (Claude hereda
    # el HOME real y su llavero), pero sigue siendo válida para CI/hosts sin sesión
    # interactiva — se mantiene la allowlist explícita por higiene, no por necesidad.
    "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN",
    # El llavero de macOS (Keychain, donde vive "Claude Code-credentials") exige USER/
    # LOGNAME resueltos para servir el item aunque HOME sea el correcto: sin ellos
    # `claude auth status` da loggedIn=false pese a heredar HOME real (verificado en
    # sesión, unidad 012 — no es HOME lo que faltaba, es esto).
    "USER", "LOGNAME",
    # Bug 037: Windows. Sin SYSTEMROOT/WINDIR el propio cargador del sistema no
    # encuentra sus DLL y winsock no llega a resolver un nombre: el agente delegado se
    # queda reconectando con el socket 11003 aunque el equipo resuelva DNS de sobra
    # (caja negra a19ef4d7, verificado por el alumno inyectando estas variables a
    # mano). USERPROFILE/APPDATA/LOCALAPPDATA son el equivalente de HOME allí, y sin
    # ellas ni el harness ni git encuentran su configuración. La lista se escribió
    # para macOS y Linux y nunca se revisó contra Windows.
    # `os.environ` normaliza estas claves a mayúsculas en Windows (os.py,
    # encodekey=str.upper), así que el nombre en mayúsculas es el que hay que buscar
    # aunque el sistema las escriba `SystemRoot` o `windir`.
    "SYSTEMROOT", "WINDIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
}


class ErrorEjecucion(Exception):
    pass


def git(cwd, *args):
    resultado = subprocess.run(
        ["git", *args], cwd=str(cwd), text=True,
        encoding="utf-8", errors="replace", capture_output=True
    )
    return resultado.returncode, (resultado.stdout + resultado.stderr).strip()


def frontmatter(ruta):
    try:
        ruta = workspace_paths.regular_file(RAIZ, ruta, label="ficha de unidad")
    except workspace_paths.WorkspacePathError as exc:
        raise ErrorEjecucion(str(exc)) from exc
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ErrorEjecucion(f"no puedo leer la unidad {ruta}: {exc}") from exc
    if not lineas or lineas[0].strip() != "---":
        raise ErrorEjecucion(f"la unidad {ruta} no tiene frontmatter")
    datos = {}
    clave_abierta = None
    items = []

    def cerrar_lista():
        nonlocal clave_abierta, items
        if clave_abierta and items:
            datos[clave_abierta] = ", ".join(items)
        clave_abierta, items = None, []

    for linea in lineas[1:]:
        if linea.strip() == "---":
            cerrar_lista()
            return datos
        encontrado = re.match(r"^(\w+):\s*(.*)$", linea)
        if encontrado:
            cerrar_lista()
            valor = encontrado.group(2).split("#", 1)[0].strip()
            datos[encontrado.group(1)] = valor
            if not valor:
                clave_abierta = encontrado.group(1)
            continue
        item = re.match(r"^\s+-\s*(.+)$", linea)
        if item and clave_abierta:
            items.append(item.group(1).split("#", 1)[0].strip().strip("'\""))
    raise ErrorEjecucion(f"frontmatter sin cierre en {ruta}")


def recursos_de(datos):
    recursos = set()
    for crudo in (datos.get("ficheros") or "").strip("[]").split(","):
        ruta = crudo.strip().strip("'\"").replace("\\", "/")
        if not ruta:
            continue
        partes = [parte for parte in ruta.split("/") if parte not in {"", "."}]
        if ruta.startswith("/") or ".." in partes:
            raise ErrorEjecucion(f"recurso fuera del repo de código: {ruta}")
        recursos.add("/".join(partes).casefold())
    return sorted(recursos)


def ficha_unidad(nombre, rol=None):
    if not RE_NOMBRE.fullmatch(nombre):
        raise ErrorEjecucion("unidad inválida: se esperaba NNN-slug")
    candidatas = [
        RAIZ / "docs/05-trabajo" / nombre / "especificacion.md",
        RAIZ / "docs/bugs" / f"{nombre}.md",
        # R3 (065): una unidad `mergeada` vive en archivo/. Si su ficha no se encuentra ahí,
        # el revisor de una entrega ya cerrada no tiene contrato que leer y la puerta del
        # cierre le pide un recibo que nadie puede producir.
        RAIZ / "docs/05-trabajo/archivo" / nombre / "especificacion.md",
    ]
    for ruta in candidatas:
        if ruta.exists() or ruta.is_symlink():
            try:
                ruta = workspace_paths.regular_file(
                    RAIZ, ruta, label=f"ficha canónica de {nombre}"
                )
            except workspace_paths.WorkspacePathError as exc:
                raise ErrorEjecucion(str(exc)) from exc
            datos = frontmatter(ruta)
            estado = (datos.get("estado") or "").strip()
            admitidos = ESTADOS_REVISABLES if rol == "revisor" else ESTADOS_EJECUTABLES
            if estado not in admitidos:
                raise ErrorEjecucion(
                    f"la unidad {nombre} está en estado {estado or 'vacío'} y el rol "
                    f"{rol or 'constructor'} solo se lanza sobre "
                    f"{'/'.join(sorted(admitidos))}. {SALIDA} "
                    + (
                        f"una unidad en {estado} ya está entregada: lo que cabe sobre ella "
                        f"es REVISARLA, con `python3 docs/00-metodo/scripts/ejecucion.py "
                        f"lanzar {nombre} --harness claude --rol revisor --prompt \"Revisa "
                        f"el diff contra el contrato y firma hallazgos.md\"`. Si de verdad "
                        f"hace falta volver a construir, el padre la devuelve a en_obra y lo "
                        f"deja escrito en la ficha"
                        if estado == "en_validacion" and rol != "revisor"
                        else f"el padre pasa la ficha de {nombre} al estado que le toca "
                             f"antes de lanzar nada: el estado lo escribe quien despacha, "
                             f"no quien ejecuta"
                    )
                )
            carril = (datos.get("carril") or "normal").strip().lower()
            # Solo el CONSTRUCTOR queda vetado en directo/exprés (regla 1: en esos
            # carriles construye el padre, a la vista del usuario). El revisor fresco
            # sí se lanza por aquí en CUALQUIER carril — la frontera del revisor "no la
            # relaja ningún carril" (ADR-017, ADR-022; bug 002 de campo, ADR-040).
            if rol == "constructor" and carril in {"directo", "expres", "exprés"}:
                raise ErrorEjecucion(
                    f"el carril {carril} lo construye el padre; no se lanza otro LLM"
                )
            return ruta, datos
    raise ErrorEjecucion(f"no existe la ficha canónica de {nombre}")


def _real(path):
    """Forma canónica para COMPARAR rutas, nunca para mostrarlas.

    ``Path.resolve()`` no basta en Windows: el propio runner de CI reporta el
    mismo directorio unas veces con su alias corto 8.3 (``RUNNER~1``) y otras
    con el nombre largo (``runneradmin``) según qué proceso lo emita (Python
    vs. git), y comparar esas dos cadenas como texto los ve como rutas
    distintas aunque sean el mismo inodo. ``os.path.realpath`` sí normaliza
    ambas formas al mismo resultado en las tres plataformas."""
    return os.path.realpath(str(path))


def inventario_worktrees():
    codigo, salida = git(MAIN, "worktree", "list", "--porcelain")
    if codigo:
        raise ErrorEjecucion(f"no puedo leer el inventario Git de worktrees: {salida}")
    inventario = {}
    actual = None
    for linea in salida.splitlines():
        if linea.startswith("worktree "):
            actual = _real(linea[9:])
            inventario[actual] = {}
        elif actual is not None and " " in linea:
            clave, valor = linea.split(" ", 1)
            inventario[actual][clave] = valor
    return inventario


def resolver_worktree(nombre):
    destino = (WORKTREES / nombre).resolve()
    if _real(destino.parent) != _real(WORKTREES):
        raise ErrorEjecucion("el worktree escaparía de worktrees/")
    entrada = inventario_worktrees().get(_real(destino))
    if entrada is None:
        raise ErrorEjecucion(f"{destino} no figura en git worktree list")
    rama_ref = entrada.get("branch")
    if rama_ref != f"refs/heads/{nombre}":
        raise ErrorEjecucion(
            f"rama registrada incorrecta: {rama_ref or 'sin rama'}; se esperaba {nombre}"
        )
    codigo, toplevel = git(destino, "rev-parse", "--show-toplevel")
    if codigo or _real(toplevel) != _real(destino):
        raise ErrorEjecucion("el destino no es la raíz real del worktree")
    codigo, rama = git(destino, "branch", "--show-current")
    if codigo or rama.strip() != nombre:
        raise ErrorEjecucion(
            f"la rama activa es {rama.strip() or 'detached'}; se esperaba {nombre}"
        )
    dotgit = destino / ".git"
    if not dotgit.is_file():
        raise ErrorEjecucion("el worktree no tiene un gitdir enlazado")
    encontrado = re.match(
        r"gitdir:\s*(.+)", dotgit.read_text(encoding="utf-8").strip()
    )
    if not encontrado:
        raise ErrorEjecucion("no puedo resolver el gitdir del worktree")
    gitdir = Path(encontrado.group(1)).resolve()
    esperado = MAIN / ".git/worktrees"
    if _real(gitdir.parent) != _real(esperado):
        raise ErrorEjecucion(f"gitdir fuera del repositorio canónico: {gitdir}")
    common = (gitdir / (gitdir / "commondir").read_text(encoding="utf-8").strip()).resolve()
    if _real(common) != _real(MAIN / ".git"):
        raise ErrorEjecucion("commondir no pertenece a main/.git")
    return destino, gitdir, common


def _head_de_main(unidad):
    """El commit que una unidad `--documental` estuvo leyendo: el HEAD de `main/`.

    Una documental no tiene rama ni `fusion:` (regla 2: no se le crea worktree), así que no
    hay commit propio sobre el que montar la revisión. El que sí describe lo que leyó es el
    HEAD del clon canónico, que el arranque deja en la última `origin/main` por fast-forward.
    """
    codigo, salida = git(MAIN, "rev-parse", "HEAD")
    sha = salida.strip()
    if codigo or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ErrorEjecucion(
            f"no puedo leer el HEAD de {MAIN} para montar la revisión de {unidad}: "
            f"{salida.strip() or 'sin salida'}. {SALIDA} pon el clon canónico al día con "
            f"`python3 setup.py` (deja main/ en la última origin/main) y vuelve a lanzar"
        )
    return sha


@contextlib.contextmanager
def _worktree_efimero(nombre, sha, destino):
    """Worktree de usar y tirar para revisar lo que no tiene worktree propio (R3).

    Dos clientes: la entrega cuyo worktree ya se borró (R3, `fusion:`) y la unidad
    `--documental`, que nunca lo tuvo (bug 090, HEAD de `main/`).

    Nace **detached** sobre `sha` y muere al salir del bloque: es lo más
    parecido a «solo lectura» que un árbol de trabajo puede ser sin pelearse con los
    permisos de medio repositorio. Sin rama no hay dónde commitear y sin árbol al terminar
    no queda residuo — cualquier cosa que el revisor escribiera ahí se va con él. Su
    veredicto vive donde siempre: en `hallazgos.md` (o en la ficha del bug), que está en el
    meta-repo y no en el worktree.
    """
    codigo, salida = git(MAIN, "worktree", "add", "--detach", str(destino), sha)
    if codigo:
        raise ErrorEjecucion(
            f"no puedo crear el worktree de revisión de {nombre} sobre {sha}: {salida}. "
            f"{SALIDA} comprueba que ese commit existe de verdad con "
            f"`git -C main cat-file -t {sha}` y corrige `fusion:` en la ficha si no "
            f"(en una unidad documental el commit es el HEAD de main/: ponlo al día con "
            f"`python3 setup.py`)"
        )
    checkpoint_suelto("worktree-efimero", "ok", f"{destino} detached sobre {sha[:8]}")
    try:
        yield destino
    finally:
        codigo, salida = git(MAIN, "worktree", "remove", "--force", str(destino))
        if codigo:
            # El árbol se va igual: dejarlo puesto convertiría la revisión de hoy en el
            # «worktree fantasma» que bloquea la de mañana.
            shutil.rmtree(destino, ignore_errors=True)
            git(MAIN, "worktree", "prune")
        checkpoint_suelto("worktree-efimero", "ok", f"{destino} borrado")


def checkpoint_suelto(nombre, estado, detalle):
    """Un checkpoint que ocurre ANTES de que exista el recibo (el worktree se crea antes)."""
    print(f"CHECKPOINT {nombre} {estado}: {detalle}", flush=True)


@contextlib.contextmanager
def worktree_de_la_ejecucion(args, datos):
    """(worktree, efímero, origen) donde correrá el harness, creado y borrado por el
    launcher si hace falta.

    Camino de siempre: el worktree registrado de la rama de la unidad, con todas sus
    comprobaciones (`resolver_worktree`). R3 añade UN camino más, y solo para el revisor:
    si la unidad ya está entregada y su worktree ya no existe, en vez del FAIL «no figura en
    git worktree list» se crea uno efímero sobre el commit de `fusion:`. El padre venía
    recreando rama y worktree A MANO para poder revisar las 041-044.

    El bug 090 añade el tercero, también solo para el revisor: la unidad `--documental`, que
    por la regla 2 no tiene worktree NUNCA. Ahí no hay `fusion:` que mirar y el commit sale
    del HEAD de `main/`. Sin esto, auditorías, investigaciones y documentación se quedaban
    sin revisor fresco por el control plane.

    `origen` es cuál de los tres fue (`worktree` · `fusion` · `documental`) y va al recibo:
    de dónde salió el árbol que revisó el agente es parte de la evidencia de la revisión.
    """
    destino = (WORKTREES / args.unidad).resolve()
    if _real(destino.parent) != _real(WORKTREES):
        raise ErrorEjecucion("el worktree escaparía de worktrees/")
    if _real(destino) in inventario_worktrees():
        yield resolver_worktree(args.unidad)[0], False, "worktree"
        return
    estado = (datos.get("estado") or "").strip()
    documental = (datos.get("ejecucion") or "").strip().lower() == "documental"
    if args.rol != "revisor" or not (documental or estado in ESTADOS_ENTREGADOS):
        raise ErrorEjecucion(
            f"{destino} no figura en git worktree list. {SALIDA} "
            + (
                f"el worktree de {args.unidad} lo crea el despacho: "
                f"`python3 docs/00-metodo/scripts/unidad.py despachar {args.unidad}`"
                if args.rol != "revisor" else
                f"una unidad en {estado or 'este estado'} todavía tiene su worktree: "
                f"recupéralo con `git -C main worktree add worktrees/{args.unidad} "
                f"{args.unidad}`. El worktree efímero de revisión solo lo crea el launcher "
                f"sobre unidades ya entregadas ({'/'.join(sorted(ESTADOS_ENTREGADOS))}) o "
                f"sobre unidades con `ejecucion: documental` en la ficha"
            )
        )
    if destino.exists():
        raise ErrorEjecucion(
            f"{destino} existe en disco pero Git no lo conoce: no lo piso. {SALIDA} "
            f"limpia el resto con `git -C main worktree prune` y, si sigue ahí, bórralo a "
            f"mano antes de volver a lanzar la revisión"
        )
    if documental:
        # Bug 090: una unidad `--documental` no tiene worktree NUNCA (regla 2), no es que
        # aún no lo tenga. No hay rama ni `fusion:` que mirar, así que el commit sale del
        # HEAD de main/ — lo que la unidad estuvo leyendo. El resto es idéntico al camino
        # de la 065: detached, y se va con el revisor.
        origen = "documental"
        sha = _head_de_main(args.unidad)
    else:
        origen = "fusion"
        sha = (datos.get("fusion") or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
            raise ErrorEjecucion(
                f"la ficha de {args.unidad} está en {estado} y no tiene `fusion:` con un "
                f"commit utilizable ({sha or 'vacío'}), así que no hay nada sobre lo que "
                f"montar la revisión. {SALIDA} anota la fusión cerrando la unidad "
                f"(`python3 docs/00-metodo/scripts/unidad.py cerrar {args.unidad}`), que "
                f"escribe `fusion:` en el frontmatter antes de borrar la rama"
            )
    with _worktree_efimero(args.unidad, sha, destino) as ruta:
        yield ruta, True, origen


def plan_de_ejecucion(args, datos):
    """(modelo, esfuerzo, origen, motivo) efectivos de esta ejecución — regla 10, R1.

    Tres orígenes posibles, y el recibo guarda cuál fue:

      `tabla`              lo normal: sale del carril de la ficha y del rol. Sin flags.
      `excepcion`          alguien pasó `--modelo`/`--esfuerzo` a mano y declaró por qué.
      `harness-sin-tabla`  codex (R5): la tabla son identificadores de Anthropic y este
                           launcher no le pasa `--model`, así que no se le inventa ninguno.
    """
    modelo = (getattr(args, "modelo", None) or "").strip() or None
    esfuerzo = (getattr(args, "esfuerzo", None) or "").strip() or None
    motivo = (getattr(args, "motivo_modelo", "") or "").strip()
    if modelo or esfuerzo:
        if not motivo:
            flag = "--modelo" if modelo else "--esfuerzo"
            raise ErrorEjecucion(
                f"{flag} es una EXCEPCIÓN a la tabla de la regla 10 y no se acepta muda: "
                f"sin motivo, el recibo no distingue una decisión de un descuido. "
                f"{SALIDA} repite el comando añadiendo "
                f"`--motivo-modelo \"por qué este modelo y no el de la tabla\"`"
            )
        return modelo, esfuerzo, "excepcion", motivo
    if args.harness != "claude":
        return None, None, "harness-sin-tabla", ""
    documental = (datos.get("ejecucion") or "").strip().lower() == "documental"
    carril = datos.get("carril") or "normal"
    try:
        plan = repo_config.plan_de_modelo(carril, args.rol, documental=documental)
    except repo_config.RepoConfigError as exc:
        raise ErrorEjecucion(
            f"{exc}. {SALIDA} corrige `carril:` en la ficha de {args.unidad}, o pasa el "
            f"modelo a mano con `--modelo <id> --motivo-modelo \"...\"`"
        ) from exc
    return plan.modelo, plan.esfuerzo, "tabla", ""


def _fichero_skill_canonico(raiz, candidata, nombre_solicitado):
    try:
        relativa = candidata.relative_to(raiz)
    except ValueError as exc:
        raise ErrorEjecucion(
            f"skill técnica fuera de su raíz: {nombre_solicitado}"
        ) from exc
    actual = raiz
    for parte in relativa.parts:
        actual = actual / parte
        if actual.is_symlink():
            raise ErrorEjecucion(
                f"skill técnica {nombre_solicitado} usa un symlink: {actual}"
            )
    try:
        raiz_real = raiz.resolve(strict=True)
        candidata_real = candidata.resolve(strict=True)
        candidata_real.relative_to(raiz_real)
        modo = candidata.lstat().st_mode
    except (OSError, ValueError) as exc:
        raise ErrorEjecucion(
            f"skill técnica fuera de su raíz real: {nombre_solicitado}"
        ) from exc
    if not stat.S_ISREG(modo):
        raise ErrorEjecucion(f"SKILL.md no es un fichero regular: {nombre_solicitado}")
    return candidata_real


def _nombre_skill_declarado(ruta, nombre_solicitado):
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ErrorEjecucion(f"no puedo leer la skill técnica {nombre_solicitado}: {exc}") from exc
    if not lineas or lineas[0].strip() != "---":
        raise ErrorEjecucion(f"skill técnica sin frontmatter: {nombre_solicitado}")
    for linea in lineas[1:]:
        if linea.strip() == "---":
            break
        encontrado = re.match(r"^name:\s*([^#]+?)\s*$", linea)
        if encontrado:
            declarado = encontrado.group(1).strip().strip("'\"")
            if not RE_SKILL.fullmatch(declarado):
                raise ErrorEjecucion(
                    f"nombre canónico inválido en la skill técnica {nombre_solicitado}"
                )
            return declarado
    raise ErrorEjecucion(f"skill técnica sin nombre canónico: {nombre_solicitado}")


def _validar_skill(raiz, candidata, nombre):
    ruta = _fichero_skill_canonico(raiz, candidata, nombre)
    declarado = _nombre_skill_declarado(ruta, nombre)
    esperado = nombre.split(":")[-1]
    if declarado in SKILLS_DE_PROCESO or declarado.split(":")[-1] in SKILLS_DE_PROCESO:
        raise ErrorEjecucion(f"{declarado} es una skill de proceso y está excluida")
    if declarado != esperado:
        raise ErrorEjecucion(
            f"la skill solicitada {nombre} declara otro nombre canónico: {declarado}"
        )
    return ruta


def resolver_skill(nombre, home_original):
    if not RE_SKILL.fullmatch(nombre):
        raise ErrorEjecucion(f"nombre de skill técnica inválido: {nombre}")
    base = nombre.split(":")[-1]
    if nombre in SKILLS_DE_PROCESO or base in SKILLS_DE_PROCESO:
        raise ErrorEjecucion(f"{nombre} es una skill de proceso y está excluida")
    raices = [
        home_original / ".agents/skills",
        home_original / ".codex/skills",
        home_original / ".claude/skills",
    ]
    for raiz in raices:
        candidata = raiz / nombre / "SKILL.md"
        if candidata.is_file():
            return _validar_skill(raiz, candidata, nombre)
    cache = home_original / ".codex/plugins/cache"
    if cache.is_dir():
        coincidencias = sorted(cache.glob(f"**/skills/{nombre}/SKILL.md"))
        if len(coincidencias) == 1:
            candidata = coincidencias[0]
            return _validar_skill(candidata.parent.parent, candidata, nombre)
        if len(coincidencias) > 1:
            raise ErrorEjecucion(f"skill técnica ambigua en plugins: {nombre}")
    raise ErrorEjecucion(f"skill técnica no instalada: {nombre}")


def encargo(nombre, rol, ficha, prompt, skills, home_original):
    partes = [
        f"UNIDAD CANÓNICA: {nombre}",
        f"ROL: {rol}",
        f"CONTRATO: {ficha}",
        "Trabaja únicamente bajo el contrato y los permisos ya impuestos por el launcher.",
    ]
    for nombre_skill in skills:
        ruta = resolver_skill(nombre_skill, home_original)
        partes.extend(
            (
                f"\n--- SKILL TÉCNICA EXPLÍCITA: {nombre_skill} ({ruta}) ---",
                ruta.read_text(encoding="utf-8"),
                f"--- FIN SKILL TÉCNICA: {nombre_skill} ---",
            )
        )
    partes.extend(("\n--- ENCARGO ---", prompt))
    return "\n".join(partes)


def entorno_base(worktree, tmp_privado, home_original):
    limpio = {clave: os.environ[clave] for clave in HEREDAR_ENV if os.environ.get(clave)}
    limpio.update(
        {
            "PWD": str(worktree),
            "TMPDIR": str(tmp_privado),
            "TMP": str(tmp_privado),
            "TEMP": str(tmp_privado),
            "SHELL": "/bin/sh",
            "HOME": str(home_original),
        }
    )
    return limpio


def preparar_codex_home(env, tmp_privado, home_original):
    aislado = tmp_privado / "home"
    aislado.mkdir(mode=0o700)
    origen = Path(os.environ.get("CODEX_HOME", str(home_original / ".codex")))
    auth = origen / "auth.json"
    if auth.is_file():
        shutil.copyfile(auth, aislado / "auth.json")
        (aislado / "auth.json").chmod(0o600)
    env["HOME"] = str(aislado)
    env["CODEX_HOME"] = str(aislado)


def preparar_claude_home(env, home_original):
    """Claude hereda el HOME real del usuario (unidad 012: ya no se aísla), sesión y
    llavero de credenciales incluidos — es lo que resuelve la autenticación sin token
    manual. Se conserva la comprobación de identidad de git y `gh auth setup-git` por si
    el HOME real aún no los tiene configurados de forma global (hosts sin FQDN, WSL2
    típico, "unable to auto-detect email address")."""
    for clave in ("user.name", "user.email"):
        valor = subprocess.run(
            ["git", "config", "--get", clave], env=env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if valor.returncode != 0 or not valor.stdout.strip():
            raise ErrorEjecucion(
                f"git no tiene configurado {clave} en {home_original}; "
                "configúralo antes de lanzar un constructor"
            )
    if env.get("GH_TOKEN") or env.get("GITHUB_TOKEN"):
        gh = shutil.which("gh", path=env.get("PATH"))
        if gh:
            subprocess.run(
                comando_subproceso(gh, [gh, "auth", "setup-git"], env),
                env=env, cwd=str(home_original),
                stdin=subprocess.DEVNULL, capture_output=True,
            )


def argv_harness(harness, ejecutable, rol, worktree, texto, documentos=(), lecturas=(),
                 modelo=None):
    directorios = sorted({str(ruta.parent) for ruta in documentos})
    if harness == "claude":
        # En claude --add-dir concede acceso de HERRAMIENTAS (lectura incluida): las
        # lecturas viajan solo aquí. En codex --add-dir significa "directorio escribible
        # adicional": pasarle docs/ cambiaría su política, así que codex no recibe
        # lecturas (revisión ronda 1).
        directorios = sorted(set(directorios) | {str(ruta) for ruta in lecturas})
        argv = [
            ejecutable,
            "--safe-mode",
            "--disable-slash-commands",
            "--strict-mcp-config",
            # El CLI exige la clave mcpServers aunque no haya servidores: un {} pelado
            # se rechaza con "Invalid MCP configuration" (bug 001).
            "--mcp-config",
            '{"mcpServers": {}}',
            "--no-session-persistence",
            # dontAsk deniega Write/Edit y Bash por defecto en headless: no es un modo
            # permisivo (bug 001). Sin sandbox de SO (unidad 012) la única frontera de
            # escritura es el cwd correcto más la disciplina del contrato de la unidad —
            # riesgo aceptado explícitamente, igual que ya confía el carril directo.
            "--permission-mode",
            "bypassPermissions",
        ]
        if modelo:
            argv.extend(("--model", modelo))
        for directorio in directorios:
            argv.extend(("--add-dir", directorio))
        argv.extend(("-p", texto))
        return argv
    if modelo:
        raise ErrorEjecucion("--modelo solo aplica al harness claude")
    argv = [
        ejecutable,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "-C",
        str(worktree),
        "-s",
        "workspace-write",
        # Sin "-a": codex-cli 0.146.0 lo retiró y muere con `unexpected argument`;
        # en modo `exec` no hay aprobaciones interactivas por definición (bug 025).
    ]
    for directorio in directorios:
        argv.extend(("--add-dir", directorio))
    argv.append(texto)
    return argv


def comando_subproceso(ejecutable, argv, env=None):
    """``argv`` listo para ``subprocess.run``, envuelto si Windows lo exige.

    En Windows, ``CreateProcess`` (lo que usa subprocess sin ``shell=True``) NO
    sabe arrancar un ``.bat``/``.cmd`` directamente — hace falta el intérprete
    de comandos con ``/c`` (documentado por Microsoft; sin esto sale
    ``WinError 193: %1 no es una aplicación Win32 válida``). Los propios
    ``claude``/``codex`` que instala npm en Windows son shims ``.cmd``, igual
    que los dobles de prueba: sin este envoltorio ni el harness real arranca
    ahí. En el resto de plataformas ``argv`` no cambia.

    ``cmd.exe /c`` lee su línea de comando por LÍNEAS: un salto de línea
    literal la trocea ahí mismo, aunque vaya entre comillas — el lector de
    cmd.exe no es un tokenizador consciente de comillas para el fin de línea,
    es el mismo por el que ni el propio Runbook mete scripts multilínea en el
    shell ``cmd`` de Windows. El prompt del harness (``encargo()``) SIEMPRE
    es multilínea, así que cruzar ``cmd.exe`` con él tal cual lo trunca en la
    primera línea (bug 017 ronda 2). Cuando se pasa ``env`` (mutable, el mismo
    dict que luego recibe ``subprocess.run``), cada argumento con salto de
    línea viaja SOLO por variable de entorno (``IR_CMDARG_N``) y en la línea de
    comando cruza únicamente una REFERENCIA literal a esa variable.

    Esa referencia NO puede llevar ningún ``%``. La ronda 2 escribió
    ``%IR_CMDARG_N%`` contando con que la sustitución de ``cmd.exe``
    devolviera el valor intacto: no lo hace, trocea igual en el salto de línea
    y parte el resto en palabras sueltas por los espacios sin comillas. La
    ronda 3 escribió ``%%IR_CMDARG_N%%`` contando con que ``cmd.exe``
    colapsara ``%%`` → ``%`` sin resolver la variable: ESA regla es la de los
    ficheros ``.bat``, no la de la línea de comando de ``cmd /c``. Ahí el
    parser deja literal solo el ``%`` que no abre un nombre válido (el
    primero, porque el carácter siguiente es otro ``%``) y a continuación
    encuentra un ``%IR_CMDARG_N%`` perfectamente válido y LO EXPANDE — el
    valor multilínea vuelve a la línea de comando y se trunca exactamente
    igual. Por eso las rondas 2 y 3 dieron el mismo traceback en el CI (bug
    017 ronda 4: el harness recibía como último argv ``001-demo``, la última
    palabra de la PRIMERA línea del encargo).

    La referencia es por tanto ``##IR_CMDARG_N##``: sin ``%`` no hay expansión
    posible ni en la línea de comando ni en el ``%*`` del propio ``.bat``, y
    sin espacios, saltos de línea ni ninguno de los metacaracteres de cmd
    (``& | < > ^ ( ) " %``) no hay nada que trocear. Quien recibe ese literal
    es responsabilidad de quien lo procesa: el doble de prueba lo resuelve
    leyendo la variable de su propio entorno heredado (que sí viaja intacto,
    ajeno al parser de ``cmd.exe``) para reconstruir el argumento EFECTIVO.
    Sin ``env`` (compatibilidad con las llamadas existentes) se mantiene el
    envoltorio simple, solo válido para argumentos de una sola línea."""
    if not (os.name == "nt" and str(ejecutable).lower().endswith((".bat", ".cmd"))):
        return argv
    comspec = os.environ.get("ComSpec", "cmd.exe")
    if env is None:
        return [comspec, "/c", *argv]
    comando = [comspec, "/c", argv[0]]
    for indice, valor in enumerate(argv[1:]):
        if isinstance(valor, str) and ("\n" in valor or "\r" in valor):
            clave = f"IR_CMDARG_{indice}"
            env[clave] = valor
            comando.append(f"##{clave}##")
        else:
            comando.append(valor)
    return comando


def evidencia_git(worktree):
    codigo, head = git(worktree, "rev-parse", "HEAD")
    if codigo or not head:
        raise ErrorEjecucion(f"no puedo fijar HEAD del worktree: {head}")
    diferencia = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--"], cwd=str(worktree),
        capture_output=True, check=False,
    )
    estado = subprocess.run(
        ["git", "status", "--porcelain=v1"], cwd=str(worktree),
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if diferencia.returncode or estado.returncode:
        detalle = (diferencia.stderr.decode("utf-8", "replace") + estado.stderr).strip()
        raise ErrorEjecucion(f"no puedo acreditar el estado Git del worktree: {detalle}")
    return {
        "head": head,
        "diff_sha256": hashlib.sha256(diferencia.stdout).hexdigest(),
        "status_porcelain": estado.stdout.splitlines(),
    }


def recibo_inicial(args, id_ejecucion, worktree, session_id, fencing, git_inicial,
                   plan=None, worktree_efimero=False, worktree_origen="worktree"):
    """El recibo tal y como nace, ANTES de lanzar el harness.

    `modelo` se guarda desde la unidad 033: llegaba por argumento, gobernaba qué modelo
    corría y luego se perdía, así que al cerrar no había forma de distinguir "otro agente"
    de "otro modelo" — y la regla 10 del método pide exactamente esa distinción.

    R2 (065) añade el resto de esa misma pregunta: el ESFUERZO efectivo y de dónde salió la
    decisión (`modelo_origen`), porque una excepción declarada y un descuido se veían igual.
    `plan` es la tupla (modelo, esfuerzo, origen, motivo); sin ella se cae al comportamiento
    de 033 —`args.modelo` a secas— para no romper a quien construya el recibo a mano.
    """
    modelo, esfuerzo, origen, motivo = plan or (
        getattr(args, "modelo", None), None, "argumento", ""
    )
    return {
        "schema": "ejecucion/v1",
        "id": id_ejecucion,
        "unidad": args.unidad,
        "harness": args.harness,
        "rol": args.rol,
        "modelo": modelo,
        "esfuerzo": esfuerzo,
        "modelo_origen": origen,
        "motivo_modelo": motivo,
        "worktree_efimero": worktree_efimero,
        # Bug 090: `efimero` dice si el launcher lo creó; `origen` dice de dónde salió
        # el commit (worktree de la rama · `fusion:` · HEAD de main/ para la documental).
        "worktree_origen": worktree_origen,
        "cwd": str(worktree),
        "rama": args.unidad,
        "lease": {"session_id": session_id, "fencing": dict(fencing)},
        "git": {"inicial": git_inicial, "final": None},
        "skills_tecnicas": list(args.skill_tecnica),
        "checkpoints": [],
        "exit_code": None,
    }


def guardar_recibo(ruta, recibo):
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(
        json.dumps(recibo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporal.chmod(0o600)
    os.replace(str(temporal), str(ruta))


def checkpoint(recibo, nombre, estado, detalle):
    recibo["checkpoints"].append(
        {"nombre": nombre, "estado": estado, "detalle": detalle}
    )
    print(f"CHECKPOINT {nombre} {estado}: {detalle}", flush=True)


def perfil_constructor(hallazgos):
    """R3 (adversarial 12-08, hallazgo 9): el CONSTRUCTOR pierde escritura sobre
    `especificacion.md` de su propia unidad — no puede autoaprobarse ni tocar su
    contrato. Sus únicas escrituras persistentes en el meta-repo quedan en
    `hallazgos.md`: las casillas `[x]` de su plan pasan a marcarse ahí (decisión
    documentada en hallazgos.md de la unidad 028; la ficha ya no es su fichero).

    `--add-dir` concede el DIRECTORIO entero, no fichero a fichero, y
    `especificacion.md` vive en la misma carpeta que `hallazgos.md` — quitar la ficha de
    esta lista no basta por sí sola. La frontera real la pone `_ficha_solo_lectura`,
    forzando la ficha a modo lectura mientras corre el harness."""
    return [hallazgos]


def perfil_revisor(hallazgos):
    """R4: el revisor conserva exactamente su escritura de hoy — solo `hallazgos.md`,
    donde van su veredicto y su firma. La ficha nunca formó parte de su set escribible;
    esta unidad no le recorta ni le añade nada.

    R4 del bug 065: el perfil del revisor **no toca ningún permiso**, ni de la ficha ni de
    la carpeta de la unidad, y no hay nada que restaurar en un `finally`. Su frontera ya la
    dan el recibo y el cerrojo; abrir aquí una segunda ventana de `chmod` solo añadiría otro
    sitio donde dejarse la ficha en 0444. Está fijado con un test.
    """
    return [hallazgos]


SENALES_DE_MUERTE = tuple(
    senal for senal in (
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGHUP", None),
    ) if senal is not None
)


@contextlib.contextmanager
def _ficha_solo_lectura(ruta):
    """Fuerza `ruta` a modo lectura mientras dura el bloque y le devuelve la escritura al
    salir. Es la única frontera de escritura real posible para R3 (unidad 028): sin sandbox
    de SO (unidad 012) y con `--add-dir` concediendo el directorio entero, un permiso de
    fichero real es lo único que produce una denegación auténtica del sistema operativo
    cuando el harness intenta escribir la ficha.

    Bug 065, defecto C — esta ventana dejaba la ficha muerta en 0444, y por dos vías que se
    alimentaban entre sí:

      1. **`finally` no es un seguro contra la muerte del proceso.** Un SIGTERM (el `kill`
         del padre que aborta un lanzamiento, un apagado, el cierre de la terminal) mata al
         intérprete sin desenrollar la pila: la ventana se quedaba abierta para siempre. Por
         eso ahora las señales de muerte se atienden, se restaura y se muere IGUAL que se
         iba a morir —mismo código de salida, misma señal—, sin tragarse nada.
      2. **El modo restaurado se leía del disco**, así que una ficha que llegaba ya en 0444
         (por lo anterior) se re-congelaba en cada lanzamiento siguiente: un trinquete del
         que no se salía sin `chmod` a mano, que es exactamente lo que le pasó al padre con
         la 046. Se restaura el modo previo **con la escritura del dueño puesta**: la
         ventana devuelve la ficha viva aunque llegara muerta.
    """
    modo_previo = stat.S_IMODE(ruta.stat().st_mode)
    modo_restaurado = modo_previo | stat.S_IWUSR
    previos = {}

    def restaurar():
        try:
            ruta.chmod(modo_restaurado)
        except OSError:
            pass                       # la ficha ya no está: no hay permiso que devolver

    def morir(numero, _marco):
        restaurar()
        signal.signal(numero, previos.get(numero, signal.SIG_DFL))
        os.kill(os.getpid(), numero)

    ruta.chmod(0o444)
    try:
        for numero in SENALES_DE_MUERTE:
            try:
                previos[numero] = signal.signal(numero, morir)
            except (OSError, ValueError):
                pass       # sin hilo principal o sin esa señal en esta plataforma: se sigue
        yield
    finally:
        for numero, previo in previos.items():
            try:
                signal.signal(numero, previo)
            except (OSError, ValueError):
                pass
        restaurar()


def _huella_documentos(rutas):
    """Contenido de cada documento escribible, para detectar si el harness tocó alguno
    (R5/R6: trabajo acreditado = alguna casilla nueva o hallazgos.md cambiado)."""
    huella = {}
    for ruta in rutas:
        try:
            huella[str(ruta)] = hashlib.sha256(ruta.read_bytes()).hexdigest()
        except OSError:
            huella[str(ruta)] = None
    return huella


def _lanzar_bajo_lease(args, ficha, datos, manager, autoridades):
    # El `with` envuelve TODO el cuerpo a propósito, en vez de delegar en una función
    # aparte: `cwd=str(worktree)` tiene que seguir viéndose DENTRO de esta función. Es
    # lo que lee el guardián de ADR-022 (`test_ejecucion_gate_real`) sobre el código
    # fuente de `_lanzar_bajo_lease`, y partirla en dos habría vaciado esa comprobación
    # sin que nadie lo decidiera.
    with worktree_de_la_ejecucion(args, datos) as (worktree, efimero, origen_worktree):
        home_original = Path(os.environ.get("HOME", str(Path.home()))).resolve()
        texto = encargo(
            args.unidad, args.rol, ficha, args.prompt, args.skill_tecnica, home_original
        )
        ficha_bloqueada = None
        if ficha.parent == RAIZ / "docs/bugs":
            # Los bugs no tienen hallazgos.md aparte: su propia ficha es a la vez contrato y
            # bitácora de casillas (AGENTS.md regla 2), así que R3 no le aplica.
            documentos = [ficha]
        else:
            hallazgos = ficha.parent / "hallazgos.md"
            if args.rol == "constructor":
                documentos = perfil_constructor(hallazgos)
                ficha_bloqueada = ficha
            else:
                documentos = perfil_revisor(hallazgos)
        seguros = []
        for documento in documentos:
            try:
                seguros.append(workspace_paths.regular_file(
                    RAIZ, documento, label="documento escribible de la unidad"
                ))
            except workspace_paths.WorkspacePathError as exc:
                raise ErrorEjecucion(str(exc)) from exc
        documentos = seguros
        huella_previa = _huella_documentos(documentos)
        ejecutable = shutil.which(args.harness)
        if not ejecutable:
            raise ErrorEjecucion(f"no encuentro el ejecutable {args.harness}")
        runtime = RAIZ / ".runtime"
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        resultados = runtime / "ejecuciones"
        resultados.mkdir(mode=0o700, exist_ok=True)
        id_ejecucion = uuid.uuid4().hex
        ruta_recibo = resultados / f"{args.unidad}-{id_ejecucion}.json"
        plan = plan_de_ejecucion(args, datos)
        recibo = recibo_inicial(
            args,
            id_ejecucion,
            worktree,
            manager.session_id,
            {
                scope: token
                for autoridad in autoridades
                for scope, token in autoridad.tokens.items()
            },
            evidencia_git(worktree),
            plan=plan,
            worktree_efimero=efimero,
            worktree_origen=origen_worktree,
        )
        checkpoint(
            recibo,
            "lease",
            "ok",
            ", ".join(f"{scope}#{token}" for scope, token in recibo["lease"]["fencing"].items()),
        )
        checkpoint(recibo, "identidad", "ok", f"{worktree} · rama {args.unidad}")
        checkpoint(
            recibo, "modelo", "ok",
            f"{recibo['modelo'] or 'el del harness'} · esfuerzo "
            f"{recibo['esfuerzo'] or 'sin declarar'} · origen {recibo['modelo_origen']}"
            + (f" ({recibo['motivo_modelo']})" if recibo["motivo_modelo"] else ""),
        )
        guardar_recibo(ruta_recibo, recibo)
        tmp = Path(tempfile.mkdtemp(prefix=f"ejecucion-{args.unidad}-", dir=str(runtime))).resolve()
        tmp.chmod(0o700)
        try:
            env = entorno_base(worktree, tmp, home_original)
            if args.harness == "codex":
                preparar_codex_home(env, tmp, home_original)
            else:
                preparar_claude_home(env, home_original)
            argv = argv_harness(
                args.harness, ejecutable, args.rol, worktree, texto, documentos=documentos,
                # El contrato de la unidad manda leer bias, flujos y la síntesis de su
                # petición: docs/ del meta-repo viaja como lectura de herramientas del
                # harness claude (sin sandbox de SO, --add-dir sigue siendo la única vía
                # explícita de lectura adicional; codex la ignora porque su --add-dir
                # significa escribible).
                lecturas=(RAIZ / "docs",),
                modelo=recibo["modelo"],
            )
            contexto_ficha = (
                _ficha_solo_lectura(ficha_bloqueada)
                if ficha_bloqueada is not None
                else contextlib.nullcontext()
            )

            def _correr_harness():
                for autoridad in autoridades:
                    autoridad.assert_owner()
                gestion_leases.failpoint("ejecucion_antes_harness")
                # stdin CERRADO: el harness delegado corre sin nadie al otro lado — cualquier
                # cosa que pregunte por stdin (git, ssh, un instalador) se quedaba esperando
                # una respuesta que no puede llegar, y el padre lo veía como un cuelgue mudo
                # de minutos (feedback de campo 06-08, ADR-026).
                tope = getattr(args, "tope_minutos", 0) or 0
                # argv como lista, cwd fijado por código, sin sandbox de SO ni shell
                # intermedia (unidad 012: la garantía real, Aurora/ADR-022, era esto, no el
                # aislamiento de SO). La ficha va en modo lectura durante todo este bloque
                # cuando el rol es constructor (R3): es la única denegación real posible sin
                # sandbox de SO, porque --add-dir concede el directorio entero.
                with contexto_ficha:
                    return tope, subprocess.run(
                        comando_subproceso(ejecutable, argv, env), cwd=str(worktree), env=env,
                        stdin=subprocess.DEVNULL, timeout=tope * 60 if tope else None,
                    )

            try:
                tope, resultado = _correr_harness()
            except subprocess.TimeoutExpired as exc:
                checkpoint(recibo, "harness", "fail", f"tope de {args.tope_minutos} min superado")
                recibo["error"] = f"el harness superó el tope de {args.tope_minutos} min y fue detenido"
                recibo["git"]["final"] = evidencia_git(worktree)
                guardar_recibo(ruta_recibo, recibo)
                raise ErrorEjecucion(
                    f"{args.harness} superó el tope de {args.tope_minutos} min; el trabajo "
                    f"parcial queda en el worktree y el recibo en {ruta_recibo}") from exc
            except OSError as exc:
                checkpoint(recibo, "harness", "fail", str(exc))
                recibo["error"] = str(exc)
                recibo["git"]["final"] = evidencia_git(worktree)
                guardar_recibo(ruta_recibo, recibo)
                raise ErrorEjecucion(f"no pude lanzar {args.harness}: {exc}") from exc
            for autoridad in autoridades:
                autoridad.assert_owner()
            recibo["exit_code"] = resultado.returncode
            recibo["git"]["final"] = evidencia_git(worktree)
            estado = "ok" if resultado.returncode == 0 else "fail"
            checkpoint(recibo, "harness", estado, f"exit {resultado.returncode}")
            if resultado.returncode == 0:
                # R5/R6: el recibo distingue "el proceso terminó sin error" de "hubo trabajo
                # acreditado" — una casilla nueva marcada o hallazgos.md (o la ficha del bug)
                # cambiado desde el arranque. Sin eso, `ok` mentía (hallazgo del análisis de
                # cajas negras del 18-08: "el recibo mide el proceso, no el trabajo").
                huella_posterior = _huella_documentos(documentos)
                trabajo_acreditado = huella_posterior != huella_previa
                recibo["trabajo"] = {
                    "acreditado": trabajo_acreditado,
                    "detalle": (
                        "hallazgos.md (o la ficha del bug) cambió durante el harness"
                        if trabajo_acreditado else
                        "proceso terminó sin error, pero no acreditó trabajo (sin casillas "
                        "nuevas ni hallazgos.md actualizado)"
                    ),
                }
                recibo["resultado"] = "ok" if trabajo_acreditado else "ok_sin_trabajo"
            else:
                recibo["resultado"] = "fail"
            guardar_recibo(ruta_recibo, recibo)
            print(f"RESULTADO {ruta_recibo}", flush=True)
            if recibo["resultado"] == "ok_sin_trabajo":
                print(
                    "AVISO ok_sin_trabajo: " + recibo["trabajo"]["detalle"], flush=True
                )
            return resultado.returncode
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def lanzar(args):
    if not RE_NOMBRE.fullmatch(args.unidad):
        raise ErrorEjecucion("unidad inválida: se esperaba NNN-slug")
    manager = gestion_leases.LeaseManager(RAIZ)
    try:
        with manager.acquire(f"unit:{args.unidad}") as autoridad_unidad:
            ficha, datos = ficha_unidad(args.unidad, rol=args.rol)
            recursos = recursos_de(datos)
            scopes_recursos = [f"resource:{ruta}" for ruta in recursos]
            contexto = (
                manager.acquire(scopes_recursos)
                if scopes_recursos
                else contextlib.nullcontext(None)
            )
            with contexto as autoridad_recursos:
                ficha_actual, datos_actuales = ficha_unidad(args.unidad, rol=args.rol)
                if ficha_actual != ficha or recursos_de(datos_actuales) != recursos:
                    raise ErrorEjecucion(
                        "la ficha o sus recursos cambiaron mientras se adquiría autoridad"
                    )
                autoridades = [autoridad_unidad]
                if autoridad_recursos is not None:
                    autoridades.append(autoridad_recursos)
                return _lanzar_bajo_lease(
                    args, ficha_actual, datos_actuales, manager, autoridades
                )
    except gestion_leases.LeaseError as exc:
        raise ErrorEjecucion(f"autoridad de ejecución ocupada o perdida: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("lanzar", help="valida y lanza un agente en una unidad")
    p.add_argument("unidad")
    p.add_argument("--harness", required=True, choices=("claude", "codex"))
    p.add_argument("--rol", choices=("constructor", "revisor"), default="constructor")
    p.add_argument("--skill-tecnica", action="append", default=[])
    p.add_argument("--prompt", required=True)
    p.add_argument("--modelo", default=None,
                   help="EXCEPCIÓN a la tabla de la regla 10 (repo_config.plan_de_modelo): "
                        "sin este flag el modelo se deriva del carril de la ficha y del rol. "
                        "Exige --motivo-modelo y queda anotado en el recibo")
    p.add_argument("--esfuerzo", default=None,
                   help="EXCEPCIÓN al esfuerzo de la tabla (bajo | medio | alto). Viaja al "
                        "recibo; ningún harness admite hoy un flag para él. Exige "
                        "--motivo-modelo")
    p.add_argument("--motivo-modelo", default="",
                   help="por qué esta ejecución se sale de la tabla de la regla 10; "
                        "obligatorio con --modelo o --esfuerzo")
    p.add_argument("--tope-minutos", type=int, default=0,
                   help="mata el harness si supera este tope (0 = sin tope); el recibo "
                        "queda con el motivo en vez de un cuelgue mudo")
    args = parser.parse_args()
    try:
        return lanzar(args)
    except ErrorEjecucion as exc:
        print(f"ejecucion: FAIL {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
