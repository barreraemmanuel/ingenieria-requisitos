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
import time
import uuid
from pathlib import Path

import control_plane
import entrega
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

# --------------------------------------------------------------- unidad 069: rondas contadas
# El vocabulario del veredicto es CERRADO, y el patrón es LITERALMENTE el de `unidad.py`
# (`RE_VEREDICTO`): el lanzador decide si hay que gastar una ronda y el cierre decide si se
# puede cerrar; si los dos leyeran la misma línea de forma distinta, una unidad se pararía
# donde la otra pasa. Hay un test que compara los dos patrones carácter a carácter.
RE_VEREDICTO = re.compile(r"^\s*[-*]?\s*\**\s*(?:Veredicto|Revisi[oó]n)[^:\n]*:\s*(.+)$",
                          re.M | re.I)
# Máximo de rondas que el método gasta solo. La tercera no la decide un script (R2).
TOPE_DE_RONDAS = 2
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
      `harness-acreditado` lo escribe el CIERRE de la ejecución, no esta función: cuando el
                           harness deja constancia de con qué modelo corrió de verdad y
                           coincide con lo pedido (hoy solo Codex; ver `acreditar_codex`).

    Ya no existe `harness-sin-tabla`: desde la unidad 100 la tabla es POR HARNESS
    (`repo_config.plan_de_modelo(..., harness=…)`) y Codex tiene la suya, derivada de su
    propio catálogo. Un harness sin tabla se rechaza en `repo_config`, no se tolera aquí.
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
    documental = (datos.get("ejecucion") or "").strip().lower() == "documental"
    carril = datos.get("carril") or "normal"
    try:
        plan = repo_config.plan_de_modelo(
            carril, args.rol, documental=documental, harness=args.harness)
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


def senales_para_el_revisor(worktree, rol):
    """R3 (070): lo delicado que toca ESTE diff, para ponérselo delante al revisor.

    Un revisor fresco llega sin saber dónde mirar primero y empieza por el principio del
    diff, que es donde menos importa. La tabla de `senales-de-riesgo.json` ya sabe qué es
    delicado; aquí solo se aplica al cambio real de la rama.

    Nunca bloquea ni levanta: si el repo de código no está, si la rama no tiene base común o
    si `unidad.py` no viaja al lado, el revisor recibe el encargo de siempre. El foco es una
    ayuda, y una ayuda que impide lanzar al revisor es peor que no tenerla.
    """
    if rol != "revisor":
        return ()
    try:
        import unidad as gestion_unidades
    except ImportError:
        return ()
    try:
        principal = repo_config.repo_code(RAIZ)[1]
    except repo_config.RepoConfigError:
        principal = "main"
    codigo, base = git(worktree, "merge-base", principal, "HEAD")
    if codigo or not base:
        return ()
    return tuple(gestion_unidades.senales_del_diff(
        base=base.strip().splitlines()[-1], punta="HEAD", repo=worktree))


def patch_id_de_la_rama(worktree, base_registrada=None):
    """R1 (068) — la huella del CONTENIDO que se está a punto de revisar.

    `git patch-id --stable` del diff `merge-base(principal, HEAD)..HEAD`. Se eligió frente
    al SHA del commit porque el SHA cambia con un rebase limpio —mismo contenido, otra
    historia— y eso obligaba a repetir revisiones válidas o a firmar a mano; y frente al
    `diff_sha256` del recibo, que es el diff de lo NO commiteado y no habla del contenido de
    la rama. El patch-id sobrevive al rebase y muere con cualquier línea, que es exactamente
    lo que una firma tiene que prometer.

    Devuelve `""` cuando no se puede calcular (sin repo, sin base común, rama sin diff
    propio): igual que las señales del revisor, un ancla que no se puede calcular NUNCA
    impide lanzar la revisión — quien la lee decide, y el cierre solo compara lo que existe.
    El porqué de ese vacío lo cuenta `patch_id_y_motivo` (bug 113).
    """
    return patch_id_y_motivo(worktree, base_registrada)[0]


def _sha(worktree, referencia):
    codigo, salida = git(worktree, "rev-parse", "--verify", "--quiet",
                         f"{referencia}^{{commit}}")
    return salida.strip().splitlines()[-1] if codigo == 0 and salida.strip() else ""


def base_para_el_ancla(worktree, base_registrada=None):
    """(sha base, de dónde salió) contra la que se calcula el ancla del revisor (bug 113).

    Lo normal es `merge-base(principal, HEAD)`. Pero en la ronda 2 tras el ff del cierre la
    rama entera YA está dentro de la principal: el merge-base es la propia punta, el diff
    sale vacío y el recibo del revisor nacía con `revisado_patch_id: null` (107 y 108 el
    27-08), o sea una firma sin ancla justo en el caso que la 069 quería proteger. Ahí se
    mira, por este orden: la base de despacho REGISTRADA en la petición (`metadata.base_sha`,
    la que `unidad.py prefusion` re-anota al rebasar: el commit de la principal de antes de
    la fusión) si es antecesora estricta de HEAD; y si no la hay, el primer padre de HEAD
    cuando HEAD es un merge (lo que había en la principal antes de fusionar). Sin ninguna de
    las dos no hay contra qué medir y se devuelve ("", motivo): mejor un vacío que se explica
    que una base inventada.
    """
    try:
        principal = repo_config.repo_code(RAIZ)[1]
    except repo_config.RepoConfigError:
        principal = "main"
    punta = _sha(worktree, "HEAD")
    if not punta:
        return "", "sin repo o sin HEAD que revisar"
    codigo, base = git(worktree, "merge-base", principal, "HEAD")
    merge_base = base.strip().splitlines()[-1] if codigo == 0 and base.strip() else ""
    if not merge_base:
        return "", f"sin base común con {principal}"
    if merge_base != punta:
        return merge_base, f"merge-base con {principal} ({merge_base[:8]})"
    registrada = _sha(worktree, base_registrada) if base_registrada else ""
    if registrada and registrada != punta and git(
            worktree, "merge-base", "--is-ancestor", registrada, punta)[0] == 0:
        return registrada, (f"rama ya fusionada en {principal}: base de despacho "
                            f"registrada ({registrada[:8]})")
    codigo, padres = git(worktree, "rev-list", "--parents", "-n", "1", "HEAD")
    lista = padres.strip().split() if codigo == 0 else []
    if len(lista) > 2:
        return lista[1], (f"rama ya fusionada en {principal}: primer padre del merge "
                          f"({lista[1][:8]})")
    return "", (f"rama ya fusionada en {principal} (merge-base == HEAD) sin base de "
                f"despacho registrada ni merge del que tomar el primer padre: no hay diff "
                f"propio que anclar")


def patch_id_y_motivo(worktree, base_registrada=None):
    """(patch_id, motivo): el ancla y, en una frase, contra qué se calculó o por qué no."""
    base, motivo = base_para_el_ancla(worktree, base_registrada)
    if not base:
        return "", motivo
    diferencia = subprocess.run(
        ["git", "diff", base, "HEAD"], cwd=str(worktree), capture_output=True, check=False,
    )
    if diferencia.returncode:
        return "", f"git diff {base[:8]}..HEAD falló ({motivo})"
    if not diferencia.stdout:
        return "", f"diff vacío contra {base[:8]} ({motivo})"
    calculo = subprocess.run(
        ["git", "patch-id", "--stable"], cwd=str(worktree), input=diferencia.stdout,
        capture_output=True, check=False,
    )
    if calculo.returncode:
        return "", f"git patch-id falló ({motivo})"
    piezas = calculo.stdout.decode("utf-8", "replace").split()
    if not piezas:
        return "", f"git patch-id no devolvió huella ({motivo})"
    return piezas[0], motivo


def base_registrada_de_la_unidad(datos, unidad, ficha):
    """El `base_sha` que `despachar`/`prefusion` dejó en la petición de origen, o None.

    Bug 113: es la única memoria de dónde nació la rama cuando ya está fusionada. Se lee
    con las mismas funciones que el cierre (`peticion.base_despacho`); cualquier tropiezo
    —módulo ausente, referencia mal escrita, petición borrada— devuelve None: el ancla es
    una medida, no una puerta de lanzamiento.
    """
    # `frontmatter()` devuelve la lista EN LÍNEA tal cual, corchetes incluidos
    # (`[P-…@1]`): la misma limpieza que `unidad.peticiones_de`, sin parser YAML.
    valor = (datos.get("peticiones") or "").strip()
    if valor.startswith("[") and valor.endswith("]"):
        valor = valor[1:-1].strip()
    referencias = [r.strip().strip("'\"") for r in valor.split(",") if r.strip()]
    if not referencias:
        return None
    tipo = "bug" if ficha.parent == RAIZ / "docs/bugs" else "unidad"
    try:
        import peticion as gestion_peticiones
    except ImportError:
        return None
    try:
        return gestion_peticiones.base_despacho(referencias, tipo, unidad)
    except Exception:  # noqa: BLE001 — una medida nunca bloquea la revisión
        return None


def sellar_clave(hallazgos, clave, valor):
    """Escribe `clave: valor` en la cabecera de `hallazgos.md`. Devuelve si la escribió.

    Solo sustituye la clave si YA está en el frontmatter: un `hallazgos.md` nacido antes de
    la 068 (ancla) o de la 069 (ronda) no la tiene, y añadírsela aquí convertiría una
    plantilla vieja en una cabecera a medias que el linter tendría que perdonar igual
    (ausencia ≠ vacío). Tampoco levanta si el fichero no se deja escribir: estas claves son
    una MEDIDA, no una puerta de lanzamiento, y ninguna vale una obra bloqueada.
    """
    if valor in (None, ""):
        return False
    try:
        texto = hallazgos.read_text(encoding="utf-8")
    except OSError:
        return False
    nuevo, sustituciones = re.subn(
        rf"(?m)^{re.escape(clave)}:[^\n]*$", f"{clave}: {valor}", texto, count=1
    )
    if not sustituciones or nuevo == texto:
        return False
    try:
        hallazgos.write_text(nuevo, encoding="utf-8")
    except OSError:
        return False
    return True


def sellar_patch_id(hallazgos, patch_id):
    """R1 (068) — el ancla del contenido revisado, por la misma puerta que la ronda."""
    return sellar_clave(hallazgos, "revisado_patch_id", patch_id)


def veredicto_ultimo(texto):
    """El veredicto de la revisión MÁS RECIENTE, o None si sigue siendo el menú.

    Copia deliberada de `unidad.veredicto_elegido`: importar `unidad` desde aquí arrastraría
    `peticion` y `lint_cierre` a cada lanzamiento y ataría el control plane al gestor de
    unidades. Lo que NO se duplica es el criterio: el patrón vive arriba y un test lo compara
    con el de `unidad.py`.
    """
    elegido = None
    for m in RE_VEREDICTO.finditer(texto):
        valor = m.group(1).strip().strip("*").strip()
        if "|" in valor or not valor or valor in {"—", "-"}:
            continue                                   # menú sin elegir o hueco vacío
        elegido = valor
    return elegido


def hay_huecos(veredicto):
    """¿La última revisión mandó al constructor de vuelta? Vocabulario cerrado."""
    return "HUECOS" in (veredicto or "").upper()


def ronda_declarada(texto):
    """El `ronda: N` de la cabecera, o None si la clave no está o no es un entero.

    None significa «esta unidad no lleva contador», no «va por la 0»: es lo que deja pasar
    intactas a las unidades anteriores a la 069.
    """
    encontrado = re.search(r"(?m)^ronda:\s*([^\s#]+)", texto or "")
    if not encontrado:
        return None
    try:
        valor = int(encontrado.group(1))
    except ValueError:
        return None
    return valor if valor >= 1 else None


def ronda_acreditada(unidad):
    """La ronda más alta que los RECIBOS de constructor de esta unidad acreditan, o None.

    H1 de la revisión de la 069: la cabecera de `hallazgos.md` es un fichero de texto que el
    constructor posee, así que bajar `ronda: 2` a `ronda: 1` era una tercera ronda gratis. Un
    contador que se puede editar no es un contador (ADR-029). Los recibos viven en
    `.runtime/ejecuciones`, los escribe el lanzador y nadie los tiene en su set escribible:
    la parada se apoya en ellos, y la cabecera pasa a ser su copia legible.

    Devuelve None cuando no hay recibos con ronda —unidad anterior a la 069, o primera
    obra—: ahí no hay nada que acreditar y manda la cabecera.
    """
    carpeta = RAIZ / ".runtime/ejecuciones"
    if not carpeta.is_dir():
        return None
    rondas = []
    for ruta in sorted(carpeta.glob(f"{unidad}-*.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue                  # un recibo ilegible no acredita nada; se ignora
        if not isinstance(datos, dict) or datos.get("unidad") != unidad:
            continue
        if str(datos.get("rol") or "").strip() != "constructor":
            continue
        if isinstance(datos.get("ronda"), int):
            rondas.append(datos["ronda"])
    return max(rondas, default=None)


def rondas_del_constructor(hallazgos, unidad):
    """(ronda_previa, ronda_a_gastar) para este lanzamiento. Levanta en la tercera (R2).

    La cuenta la lleva el LANZADOR y no el agente por lo mismo que el ancla de la 068: un
    número que teclea quien tiene que respetarlo no mide nada (ADR-029). Y se rechaza ANTES
    de que el harness arranque, no después: parar a un agente ya lanzado cuesta el turno
    entero y deja trabajo a medias en el worktree.
    """
    try:
        texto = hallazgos.read_text(encoding="utf-8")
    except OSError:
        return None, None
    previa = ronda_declarada(texto)
    if previa is None:
        return None, None
    # H1 de la revisión: manda la MAYOR de las dos. Bajar el número a mano en la cabecera no
    # devuelve rondas gastadas, porque los recibos siguen contándolas.
    acreditada = ronda_acreditada(unidad)
    if acreditada is not None and acreditada > previa:
        previa = acreditada
    if not hay_huecos(veredicto_ultimo(texto)):
        return previa, previa           # relanzar tras un LIMPIO no es una corrección
    siguiente = previa + 1
    if siguiente > TOPE_DE_RONDAS:
        # salida:por-diseño autoridad-humana: subir de carril, reabrir el contrato o
        # cancelar la unidad son decisiones del usuario sobre el alcance de SU trabajo;
        # ningún comando del método puede tomarlas por él, y uno que lo intentara sería
        # justo el «loop-until-clean» que esta unidad viene a cerrar.
        raise ErrorEjecucion(
            f"tercera ronda de corrección en {unidad}: se rechaza el lanzamiento. Van "
            f"{previa} vueltas al constructor con veredicto HUECOS DE CORRECCIÓN y el "
            f"método no abre una tercera por su cuenta — a partir de aquí decides TÚ, y "
            f"las opciones son tres: subir de carril (el trabajo era mayor de lo "
            f"contratado), reabrir el contrato (lo contratado no era lo que hacía falta) "
            f"o cancelar la unidad. Ni se reinicia el contador ni se amplía: un "
            f"presupuesto agotado que se estira no era un presupuesto"
        )
    return previa, siguiente


def numstat(worktree, desde, hasta):
    """(+N, -M) de `git diff --numstat desde..hasta`, o None si no se puede medir."""
    if not desde or not hasta:
        return None
    codigo, salida = git(worktree, "diff", "--numstat", desde, hasta)
    if codigo:
        return None
    mas = menos = 0
    for linea in salida.splitlines():
        piezas = linea.split("\t")
        if len(piezas) < 2:
            continue
        for indice, acumulado in ((0, "mas"), (1, "menos")):
            if not piezas[indice].isdigit():
                continue          # binario: git escribe `-` y no hay líneas que contar
            if acumulado == "mas":
                mas += int(piezas[indice])
            else:
                menos += int(piezas[indice])
    return mas, menos


def medida_de_la_correccion(worktree, cabeza_inicial, ronda):
    """R4 — el tamaño de esta corrección FRENTE al diff original de la rama.

    Informa, no bloquea: la queja de la que nace esta unidad es el gasto, no el tamaño, y
    una puerta de líneas se abriría después y con datos, no antes y a ojo. El dato que hace
    falta para decidirlo es justo este: cuánto se está corrigiendo comparado con lo que se
    construyó.
    """
    try:
        principal = repo_config.repo_code(RAIZ)[1]
    except repo_config.RepoConfigError:
        principal = "main"
    codigo, base = git(worktree, "merge-base", principal, "HEAD")
    if codigo or not base.strip():
        return ""
    base = base.strip().splitlines()[-1]
    correccion = numstat(worktree, cabeza_inicial, "HEAD")
    original = numstat(worktree, base, cabeza_inicial)
    if correccion is None or original is None:
        return ""
    return (f"+{correccion[0]}/-{correccion[1]} en la ronda {ronda}, "
            f"sobre una rama original de +{original[0]}/-{original[1]}")


def bloque_de_senales(senales):
    """Las líneas del encargo que enseñan el foco. Vacío si no hay señales: sin ellas el
    encargo del revisor es el de siempre, byte a byte (R4)."""
    if not senales:
        return []
    filas = []
    for senal in senales:
        donde = senal.ruta if senal.linea is None else f"{senal.ruta}:{senal.linea}"
        marca = "" if senal.nivel == "alta" else "  (informativa: vive en pruebas)"
        filas.append(f"  - {senal.nombre} → {donde}{marca}")
    return [
        "\n--- Señales de riesgo detectadas (mira esto primero) ---",
        "El cambio toca sitios que la tabla del método marca como delicados. No son "
        "veredictos: son dónde empezar a leer.",
        *filas,
        "--- fin de las señales ---",
    ]


def encargo(nombre, rol, ficha, prompt, skills, home_original, senales=()):
    partes = [
        f"UNIDAD CANÓNICA: {nombre}",
        f"ROL: {rol}",
        f"CONTRATO: {ficha}",
        "Trabaja únicamente bajo el contrato y los permisos ya impuestos por el launcher.",
        *bloque_de_senales(senales),
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


def acreditar_codex(codex_home):
    """(modelo, esfuerzo) con los que Codex corrió DE VERDAD, o (None, None).

    `codex exec --json` no lo dice —comprobado contra 0.149.0: emite `thread.started`,
    `turn.started`, `item.completed` y `turn.completed`, y ninguno nombra el modelo—. Lo
    que sí queda es el rollout de la sesión, dentro del propio `CODEX_HOME`: su evento
    `turn_context` trae `model` y `effort` efectivos. Se lee aquí, antes de que el temporal
    se borre.

    Nunca levanta: una acreditación que no se puede leer deja el recibo DECLARANDO, que es
    lo que ya hacía. Mentir sería peor que no acreditar.
    """
    try:
        sesiones = Path(codex_home) / "sessions"
        if not sesiones.is_dir():
            return None, None
        rollouts = sorted(sesiones.rglob("rollout-*.jsonl"),
                          key=lambda ruta: ruta.stat().st_mtime)
    except OSError:
        return None, None
    for ruta in reversed(rollouts):
        try:
            lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for linea in lineas:
            if '"turn_context"' not in linea:
                continue
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            if evento.get("type") != "turn_context":
                continue
            carga = evento.get("payload") or {}
            modelo = carga.get("model")
            if modelo:
                return modelo, carga.get("effort")
    return None, None


def acreditar_claude(home, worktree, session_id):
    """(modelo, esfuerzo) con los que Claude corrió DE VERDAD, o (None, None).

    Simétrica a `acreditar_codex`, con la fuente que le toca a este harness: Claude Code
    guarda el transcript de cada sesión en
    `<HOME>/.claude/projects/<slug del cwd>/<session_id>.jsonl`, y cada registro
    `assistant` trae el modelo efectivo en `message.model` y el esfuerzo del turno en
    `effort`. El slug es el cwd con los separadores en guiones. Manda el ÚLTIMO mensaje
    del asistente: si la sesión cambió de modelo a mitad, lo que vale es con qué acabó.

    Si el slug no casa —macOS resuelve `/var` en `/private/var` y el enlace se pierde por
    el camino— se busca el transcript por el `session_id`, que es único.

    Nunca levanta: una acreditación que no se puede leer deja el recibo DECLARANDO, que es
    lo que ya hacía. Mentir sería peor que no acreditar.
    """
    if not session_id:
        return None, None
    proyectos = Path(home) / ".claude" / "projects"
    slug = str(worktree).replace("/", "-").replace("\\", "-")
    candidatos = [proyectos / slug / f"{session_id}.jsonl"]
    try:
        candidatos.extend(sorted(proyectos.glob(f"*/{session_id}.jsonl")))
    except OSError:
        pass
    for ruta in candidatos:
        try:
            if not ruta.is_file():
                continue
            lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        modelo = esfuerzo = None
        for linea in lineas:
            if '"assistant"' not in linea:
                continue
            try:
                registro = json.loads(linea)
            except ValueError:
                continue
            if registro.get("type") != "assistant":
                continue
            mensaje = registro.get("message") or {}
            if mensaje.get("model"):
                modelo = mensaje["model"]
                esfuerzo = registro.get("effort") or None
        if modelo:
            return modelo, esfuerzo
    return None, None


def acreditar(harness, env, worktree, session_id):
    """(modelo, esfuerzo, fuente) de lo que de VERDAD corrió, por harness.

    La regla 10 deja de creerse por estar escrita en los DOS harness (unidad 108): el
    `fuente` es lo que el checkpoint del recibo enseña al usuario.
    """
    if harness == "codex":
        modelo, esfuerzo = acreditar_codex(env.get("CODEX_HOME", ""))
        return modelo, esfuerzo, "rollout de la sesión"
    modelo, esfuerzo = acreditar_claude(env.get("HOME", ""), worktree, session_id)
    return modelo, esfuerzo, "transcript de la sesión"


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


PERFIL_REVISOR_CODEX = "revisor-solo-lectura"


def opciones_de_perfil_revisor_codex(perfil, escribibles):
    """Los `-c` que ponen al revisor Codex en solo lectura DE VERDAD (unidad 108).

    La 100 probó que `-s read-only` es absoluto: ignora `--add-dir` y
    `sandbox_workspace_write.writable_roots`, no deja ninguna ruta escribible y por
    tanto el revisor no podría escribir su veredicto ni su firma —su ÚNICA escritura
    obligatoria—. El spike del paso 0 de la 108 encontró la vía que sí da las dos
    mitades, probada contra `codex-cli 0.149.0`: un perfil de permisos propio que
    EXTIENDE el built-in `:read-only` y añade rutas escribibles por su mapa
    `filesystem`. Bajo él, el worktree de código se lee pero no se escribe (`Operation
    not permitted`) y la carpeta de la unidad sí.

    Dos detalles que solo se ven corriendo el binario (evidencia en `hallazgos.md`):
    `sandbox_mode` y el perfil no pueden convivir —quien usa el perfil no lleva `-s`—, y el
    perfil se ELIGE con `default_permissions`: `permission_profile` existe como campo
    interno pero `codex exec --strict-config` lo rechaza como override (`unknown
    configuration field`).
    """
    mapa = ", ".join(f'{json.dumps(str(ruta))} = "write"' for ruta in escribibles)
    return [
        "-c", f'permissions.{perfil}.extends=":read-only"',
        "-c", f"permissions.{perfil}.filesystem={{{mapa}}}",
        "-c", f'default_permissions="{perfil}"',
    ]


def argv_harness(harness, ejecutable, rol, worktree, texto, documentos=(), lecturas=(),
                 modelo=None, esfuerzo=None, session_id=None, temporal=None):
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
            # dontAsk deniega Write/Edit y Bash por defecto en headless: no es un modo
            # permisivo (bug 001). Sin sandbox de SO (unidad 012) la única frontera de
            # escritura es el cwd correcto más la disciplina del contrato de la unidad —
            # riesgo aceptado explícitamente, igual que ya confía el carril directo.
            "--permission-mode",
            "bypassPermissions",
        ]
        if modelo:
            argv.extend(("--model", modelo))
        if session_id:
            # Unidad 108 · R1. El transcript de la sesión es el ÚNICO sitio donde
            # Claude dice con qué modelo corrió de verdad, y `--no-session-persistence`
            # era justo lo que impedía escribirlo (mismo caso que `--ephemeral` en
            # Codex, unidad 100): por eso ya no está. Con el id fijado desde aquí no
            # hace falta capturar el stdout del harness —que el padre necesita ver en
            # directo— para saber qué transcript leer al cerrar el recibo.
            argv.extend(("--session-id", session_id))
        for directorio in directorios:
            argv.extend(("--add-dir", directorio))
        argv.extend(("-p", texto))
        return argv
    # Unidad 100 — las cuatro decisiones de este argv salen de correr el binario, no de
    # leer su documentación. Están probadas contra codex-cli 0.149.0 y cada una arregla un
    # fallo SILENCIOSO (la evidencia, en los hallazgos de la 100):
    #
    #   sin `--ephemeral`   `--ephemeral` es justo lo que impide escribir el rollout de la
    #                       sesión, y el rollout es el ÚNICO sitio donde Codex dice con qué
    #                       modelo y esfuerzo corrió de verdad (`codex exec --json` NO lo
    #                       emite: son cuatro eventos y ninguno habla de modelo). Sin él no
    #                       hay acreditación, solo declaración. El aislamiento no se pierde:
    #                       lo da `CODEX_HOME`, que apunta al temporal que se borra al salir.
    #   sin `--ignore-user-config`
    #                       esa bandera no es solo «no leas el config.toml del usuario»: se
    #                       lleva por delante la capa de configuración ENTERA, hooks del
    #                       `.codex/` DEL REPO incluidos. Y tampoco hace falta para aislar:
    #                       el `CODEX_HOME` efímero solo contiene `auth.json`, así que no hay
    #                       configuración de usuario que leer.
    #   `--dangerously-bypass-hook-trust`
    #                       segunda puerta, también muda: un hook del repo no corre hasta que
    #                       alguien confía su hash, y si nadie lo ha hecho NO SE DICE NADA —
    #                       salida idéntica a un repo sin hooks—. No hay subcomando para
    #                       confiarlos (solo el `/hooks` interactivo), así que en sesión
    #                       delegada esta es la única vía. El repo es el del propio método:
    #                       el «dangerously» aquí es confiar en lo que uno mismo escribió.
    #   `--json`            el flujo de eventos que el lanzador puede leer.
    #
    # Lo que NO lleva, y es deliberado: `-s read-only` para el revisor. Bajo ese sandbox
    # Codex ignora `--add-dir` y `sandbox_workspace_write.writable_roots` y no queda ninguna
    # ruta escribible, así que el revisor no podría escribir su veredicto ni su firma en
    # `hallazgos.md` — que es su ÚNICA escritura y lo que el cierre le exige. El revisor
    # Codex conserva, por tanto, la misma frontera que el de Claude: el cwd correcto más la
    # disciplina del contrato (ADR-022, enmienda del padre a R4 el 27-08).
    argv = [
        ejecutable,
        "exec",
        "--ignore-rules",
        "--strict-config",
        "--dangerously-bypass-hook-trust",
        "--json",
        "-C",
        str(worktree),
        # Sin "-a": codex-cli 0.146.0 lo retiró y muere con `unexpected argument`;
        # en modo `exec` no hay aprobaciones interactivas por definición (bug 025).
    ]
    if modelo:
        argv.extend(("-m", modelo))
    if esfuerzo:
        # Codex no tiene flag propio de esfuerzo: viaja por el override general de config.
        argv.extend(("-c", f"model_reasoning_effort={esfuerzo}"))
    if rol == "revisor":
        # Unidad 108 · R3: la promesa que la 100 tuvo que retirar, cumplida por otra vía.
        # El cwd sigue siendo el worktree (ADR-022); lo que cambia es qué puede ESCRIBIR.
        escribibles = list(directorios)
        if temporal is not None:
            # TMPDIR (y el CODEX_HOME efímero, que vive dentro): sin él la sesión no puede
            # ni escribir su propio rollout, y sin rollout no hay acreditación.
            escribibles.append(str(temporal))
        argv.extend(opciones_de_perfil_revisor_codex(PERFIL_REVISOR_CODEX, escribibles))
    else:
        argv.extend(("-s", "workspace-write"))
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
                   plan=None, worktree_efimero=False, worktree_origen="worktree",
                   patch_id="", ronda=None, motivo_patch_id="", motivo_ronda=""):
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
        # R2 (100): lo PEDIDO y lo que de verdad corrió, separados. `model_slug` lo rellena
        # `acreditar_codex` al terminar, leyendo el rollout de la sesión; mientras siga a
        # None el recibo DECLARA, no acredita, y `modelo_origen` no dice `harness-acreditado`.
        "requested_model": modelo,
        "requested_reasoning_effort": esfuerzo,
        "model_slug": None,
        "worktree_efimero": worktree_efimero,
        # Bug 090: `efimero` dice si el launcher lo creó; `origen` dice de dónde salió
        # el commit (worktree de la rama · `fusion:` · HEAD de main/ para la documental).
        "worktree_origen": worktree_origen,
        "cwd": str(worktree),
        "rama": args.unidad,
        "lease": {"session_id": session_id, "fencing": dict(fencing)},
        "git": {"inicial": git_inicial, "final": None},
        # R1 (068): a QUÉ contenido queda pegada esta revisión. `head` y `diff_sha256` ya
        # estaban, pero hablan del commit y de lo no commiteado; ninguno sobrevive a un
        # rebase limpio ni cambia con una línea de la rama. None mientras no haya ancla
        # (rol constructor, rama sin diff propio, repo que no se puede leer).
        "revisado_patch_id": patch_id or None,
        # Bug 113: si el ancla va vacía, AQUÍ se dice por qué (rama fusionada sin base,
        # diff vacío…): un null mudo era indistinguible de «se me olvidó». Con ancla, None.
        "motivo_patch_id": (motivo_patch_id or None) if not patch_id else None,
        # R1/R5 (069): qué vuelta al constructor es ESTA, y si acabó sin tocar un byte.
        # `None` en las dos mientras no haya contador (rol revisor, cabecera anterior a la
        # 069): el recibo no inventa una ronda que nadie está contando.
        "ronda": ronda,
        # Bug 117 (R2): si el revisor no lleva ronda, AQUÍ se dice por qué; con ronda, None.
        "motivo_ronda": (motivo_ronda or None) if ronda is None else None,
        "ronda_vacia": None,
        "correccion": None,
        "skills_tecnicas": list(args.skill_tecnica),
        # Bug 077 · R2: lo que necesita `lease.py desbloquear` para recuperar un
        # lanzamiento que murió sin señal (`kill -9`, terminal cerrada). Sin esto, el
        # recibo decía quién tenía el lease pero no QUÉ proceso hijo había quedado vivo
        # ni qué ficha había que descongelar, y la recuperación seguía siendo a mano.
        "lanzador": {
            "pid": os.getpid(),
            "process_started": gestion_leases.process_start_marker(os.getpid()),
        },
        "harness_proceso": None,
        "ficha_bloqueada": None,
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


def exigir_entrega_constructor(worktree, unidad, recibos, base):
    """Compatibilidad pública de la tabla de transiciones de la reforma."""
    return entrega.validar_entrega(worktree, unidad, recibos, base)


def exit_de_resultado(resultado, rol, espera_cambios):
    """El resultado semántico manda sobre el exit del harness."""
    if resultado in {"fail", "fallo", "parado", "interrumpido"}:
        return 1
    if resultado == "ok_sin_trabajo" and (rol == "revisor" or espera_cambios):
        return 1
    return 0


def imprimir_resultado(ruta, resultado, avisos=()):
    """Deja RESULTADO al final para que sobreviva incluso a `| tail -3`."""
    for aviso in avisos:
        print(aviso, flush=True)
    print(f"RESULTADO {ruta} · {resultado}", flush=True)


def hay_arbol_que_revisar(unidad):
    """¿Tiene esta revisión un árbol del que derivar la entrega?

    La puerta de la entrega deriva de git, así que solo habla cuando hay algo que mirar:
    un worktree registrado, o uno de los dos caminos efímeros del revisor (065: unidad ya
    entregada con `fusion:`; 090: `ejecucion: documental`). Sin ninguno, el rechazo que
    manda es el específico del lanzador —«no figura en git worktree list»— que trae la
    salida útil; adelantarlo con un motivo genérico dejaba al usuario sin ese comando.
    """
    destino = (WORKTREES / unidad).resolve()
    if _real(destino) in inventario_worktrees():
        return True
    try:
        _, datos = ficha_unidad(unidad, rol="revisor")
    except ErrorEjecucion:
        return False
    estado = (datos.get("estado") or "").strip()
    documental = (datos.get("ejecucion") or "").strip().lower() == "documental"
    return documental or estado in ESTADOS_ENTREGADOS


def puerta_entrega_para_revisor(unidad):
    """Único adaptador del lanzador a la puerta común de la entrega."""
    return entrega.exigir_entrega_constructor(unidad)


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


class _EnVuelo:
    """Lo que un lanzamiento tiene EN LA MANO y debe soltar si lo interrumpen.

    Bug 077 (Fernando en Windows, Manuel en macOS): al cancelar la espera, cerrar la
    terminal o perder la conexión, el lanzador moría y dejaba tres cosas atrás — el
    harness hijo VIVO, los leases de la unidad retenidos por un PID que ya no existía y
    la ficha congelada en 0444. Cada una exigía cirugía a mano.

    El arreglo de la 065 solo cubría la tercera, y solo desde dentro de
    `_ficha_solo_lectura`: un manejador local que restauraba el modo y se moría. No podía
    hacer más porque desde ahí no se ve ni el hijo ni los leases. Este objeto es lo que
    faltaba: el estado vivo del lanzamiento, en UN sitio, para que UN solo manejador de
    señal pueda limpiar las tres cosas EN EL ORDEN que manda R1 — primero el hijo (si no,
    sigue escribiendo en el worktree mientras se suelta su autoridad), luego los leases
    (para que la unidad quede lanzable) y por último la ficha.
    """

    def __init__(self):
        self.hijo = None                 # Popen del harness, mientras corre
        self.autoridades = ()            # LeaseGroup adquiridos para esta unidad
        self.restaurar_ficha = None      # callable de `_ficha_solo_lectura`, si está abierta
        self.recibo = None
        self.ruta_recibo = None


_EN_VUELO = None


def comando_matar_windows(pid):
    """`taskkill` con /T: Windows no tiene grupos de proceso POSIX y matar solo al PID
    deja viva a la descendencia (el harness real arranca desde un shim .cmd, así que
    SIEMPRE hay descendencia). /F porque el hijo puede estar ignorando el cierre amable.

    Función aparte para que la forma del comando sea comprobable desde cualquier
    plataforma, igual que `comando_subproceso` (bug 017)."""
    return ["taskkill", "/T", "/F", "/PID", str(int(pid))]


def opciones_de_aislamiento():
    """El hijo nace en su PROPIO grupo/sesión: sin esto no hay forma de matarlo entero.

    Además le quita el Ctrl-C del terminal: la señal la recibe SOLO el lanzador, que es
    quien sabe en qué orden hay que soltar las cosas. Con el hijo en el mismo grupo, el
    Ctrl-C llegaba a los dos a la vez y el harness moría (o no: el de Fernando no lo
    hacía) sin que nadie liberase su autoridad."""
    if os.name == "nt":  # pragma: no cover - rama Windows, la ejercita su CI
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _grupo_de(pid):
    """Grupo de procesos del hijo, o None donde no exista el concepto (Windows)."""
    if os.name == "nt":  # pragma: no cover - rama Windows, la ejercita su CI
        return None
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def matar_arbol(pid, *, pgid=None, gracia=5.0, proceso=None):
    """Termina al harness y a toda su descendencia. Devuelve qué se hizo, para el recibo.

    Primero el cierre amable y, si sigue vivo pasada la gracia, el que no se puede
    ignorar: el hijo simulado del bug 077 IGNORA SIGTERM a propósito porque un harness
    ocupado tampoco lo atiende."""
    if pid is None:
        return "no había harness que matar"
    if os.name == "nt":  # pragma: no cover - rama Windows, la ejercita su CI
        subprocess.run(comando_matar_windows(pid), capture_output=True)
        if proceso is not None:
            with contextlib.suppress(Exception):
                proceso.wait(timeout=gracia)
        return f"taskkill /T /F sobre el PID {pid}"

    def sigue_vivo():
        if proceso is not None and proceso.poll() is not None:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def golpear(senal):
        objetivo = pgid
        if objetivo is None:
            try:
                objetivo = os.getpgid(pid)
            except OSError:
                objetivo = None
        try:
            if objetivo is not None and objetivo != os.getpgrp():
                os.killpg(objetivo, senal)
            else:
                os.kill(pid, senal)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        return True

    if not sigue_vivo():
        return "el harness ya había terminado"
    golpear(signal.SIGTERM)
    limite = time.monotonic() + gracia
    while sigue_vivo() and time.monotonic() < limite:
        time.sleep(0.05)
    if not sigue_vivo():
        detalle = f"harness {pid} terminado con SIGTERM"
    else:
        golpear(signal.SIGKILL)
        limite = time.monotonic() + gracia
        while sigue_vivo() and time.monotonic() < limite:
            time.sleep(0.05)
        detalle = f"harness {pid} terminado con SIGKILL (ignoraba SIGTERM)"
    if proceso is not None:
        with contextlib.suppress(Exception):
            proceso.wait(timeout=1)
    return detalle


def _limpiar_lo_que_quede(numero):
    """Suelta, EN ORDEN (R1), lo que el lanzamiento tuviera en la mano.

    Cada paso va aislado: que falle uno no puede impedir los otros dos. Un lease que no
    se pudo soltar aquí no queda perdido — lo recupera `lease.py desbloquear`, que es
    justo la red de R2 para cuando ni siquiera hay señal que atender (`kill -9`)."""
    estado = _EN_VUELO
    if estado is None:
        return
    partes = []
    try:
        proceso = estado.hijo
        if proceso is not None:
            partes.append(matar_arbol(proceso.pid, proceso=proceso))
    except Exception as exc:                       # nunca abortar la limpieza a medias
        partes.append(f"no pude terminar el harness: {exc}")
    for autoridad in reversed(list(estado.autoridades)):
        try:
            autoridad.release()
            partes.append("leases liberados")
        except Exception as exc:
            partes.append(f"no pude liberar leases: {exc}")
    if estado.restaurar_ficha is not None:
        try:
            estado.restaurar_ficha()
            partes.append("ficha devuelta a escritura")
        except Exception as exc:
            partes.append(f"no pude devolver la ficha: {exc}")
    if estado.recibo is not None and estado.ruta_recibo is not None:
        with contextlib.suppress(Exception):
            estado.recibo["resultado"] = "interrumpido"
            estado.recibo["error"] = (
                f"lanzamiento interrumpido por la señal {numero}: el trabajo parcial queda "
                f"en el worktree"
            )
            checkpoint(
                estado.recibo, "interrumpido", "fail",
                f"señal {numero} · " + " · ".join(partes),
            )
            guardar_recibo(estado.ruta_recibo, estado.recibo)


@contextlib.contextmanager
def red_de_seguridad(autoridades):
    """UN manejador para las tres señales de muerte, durante TODO el lanzamiento.

    Antes esto vivía dentro de `_ficha_solo_lectura` y solo existía mientras la ficha
    estaba congelada; ahora la ventana cubre desde que hay autoridad hasta que se
    devuelve, que es cuando hay algo que soltar. Se muere IGUAL que se iba a morir
    —misma señal, restaurando el manejador previo— para no tragarse nada ni mentir sobre
    el código de salida."""
    global _EN_VUELO
    previo_en_vuelo = _EN_VUELO
    estado = _EnVuelo()
    estado.autoridades = list(autoridades)
    _EN_VUELO = estado
    previos = {}

    def morir(numero, _marco):
        _limpiar_lo_que_quede(numero)
        signal.signal(numero, previos.get(numero, signal.SIG_DFL))
        os.kill(os.getpid(), numero)

    try:
        for numero in SENALES_DE_MUERTE:
            try:
                previos[numero] = signal.signal(numero, morir)
            except (OSError, ValueError):
                pass   # sin hilo principal o sin esa señal en esta plataforma: se sigue
        yield estado
    finally:
        for numero, previo in previos.items():
            with contextlib.suppress(OSError, ValueError):
                signal.signal(numero, previo)
        _EN_VUELO = previo_en_vuelo


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

    Bug 077: el manejador de señales ya NO vive aquí. Desde aquí no se ve ni el harness
    hijo ni los leases, así que un manejador local solo podía arreglar un tercio del
    problema. Lo que hace ahora es DECLARAR su restauración en `red_de_seguridad`, que es
    quien lo llama en el orden correcto (hijo → leases → ficha). El `finally` sigue igual
    para el camino normal.
    """
    modo_previo = stat.S_IMODE(ruta.stat().st_mode)
    modo_restaurado = modo_previo | stat.S_IWUSR

    def restaurar():
        try:
            ruta.chmod(modo_restaurado)
        except OSError:
            pass                       # la ficha ya no está: no hay permiso que devolver

    ruta.chmod(0o444)
    if _EN_VUELO is not None:
        _EN_VUELO.restaurar_ficha = restaurar
    try:
        yield
    finally:
        if _EN_VUELO is not None:
            _EN_VUELO.restaurar_ficha = None
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
    with red_de_seguridad(autoridades) as vuelo, \
            worktree_de_la_ejecucion(args, datos) as (worktree, efimero, origen_worktree):
        home_original = Path(os.environ.get("HOME", str(Path.home()))).resolve()
        texto = encargo(
            args.unidad, args.rol, ficha, args.prompt, args.skill_tecnica, home_original,
            senales=senales_para_el_revisor(worktree, args.rol),
        )
        ficha_bloqueada = None
        patch_id_revisado = motivo_patch_id = motivo_ronda = ""
        ronda_previa = ronda_actual = ronda_revisada = None
        es_bug = ficha.parent == RAIZ / "docs/bugs"
        if es_bug:
            # Los bugs no tienen hallazgos.md aparte: su propia ficha es a la vez contrato y
            # bitácora de casillas (AGENTS.md regla 2), así que R3 no le aplica.
            documentos = [ficha]
            cabecera = ficha
        else:
            hallazgos = ficha.parent / "hallazgos.md"
            cabecera = hallazgos
            if args.rol == "constructor":
                documentos = perfil_constructor(hallazgos)
                ficha_bloqueada = ficha
                # R1/R2 (069): la cuenta se hace y se rechaza AQUÍ, antes de reservar nada
                # más y mucho antes del harness. Un rechazo posterior costaría el turno del
                # agente y dejaría trabajo a medias en el worktree.
                ronda_previa, ronda_actual = rondas_del_constructor(hallazgos, args.unidad)
            else:
                documentos = perfil_revisor(hallazgos)
        if args.rol == "revisor":
            # R1 (068): el ancla se calcula y se sella ANTES de que el revisor escriba
            # nada, y la pone el launcher, no el agente — otra huella tecleada a mano
            # sería el mismo agujero de ADR-029 con otro nombre. Va aquí, antes de
            # `huella_previa`, para que el sello del launcher no se confunda con el
            # trabajo del revisor cuando el recibo decida si hubo trabajo (R5/R6).
            # Bug 117: fuera del `else` de las unidades — para una ficha de `docs/bugs/`
            # nunca se calculaba y el recibo salía con `revisado_patch_id: null` aunque la
            # rama tuviera diff.
            patch_id_revisado, motivo_patch_id = patch_id_y_motivo(
                worktree, base_registrada_de_la_unidad(datos, args.unidad, ficha))
            # R3 (113): el recibo del revisor lleva la ronda que declara la cabecera
            # —la que el constructor gastó y este revisor va a juzgar—; `None` solo si
            # la cabecera no lleva contador, y entonces el recibo dice por qué (117, R2).
            # Va en `ronda_revisada`, NO en `ronda_actual`: el revisor no gasta rondas ni
            # las sella (069), y `cerrar_la_ronda` solo cuenta las del constructor.
            try:
                ronda_revisada = ronda_declarada(cabecera.read_text(encoding="utf-8"))
            except OSError:
                ronda_revisada = None
            if ronda_revisada is None:
                motivo_ronda = (
                    "la ficha del bug no lleva contador de rondas" if es_bug
                    else "la cabecera de hallazgos.md no lleva `ronda:` (anterior a la 069)")
        seguros = []
        for documento in documentos:
            try:
                seguros.append(workspace_paths.regular_file(
                    RAIZ, documento, label="documento escribible de la unidad"
                ))
            except workspace_paths.WorkspacePathError as exc:
                raise ErrorEjecucion(str(exc)) from exc
        documentos = seguros
        if patch_id_revisado and documentos:
            sellar_patch_id(documentos[0], patch_id_revisado)
        if ronda_actual and ronda_actual != ronda_previa and documentos:
            # Antes de `huella_previa` a propósito: el sello lo pone el lanzador, y si
            # entrara en la huella el recibo contaría como «trabajo del agente» una línea
            # que el agente no escribió (R5/R6 de la 028).
            sellar_clave(documentos[0], "ronda", str(ronda_actual))
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
            patch_id=patch_id_revisado,
            ronda=ronda_actual if args.rol == "constructor" else ronda_revisada,
            motivo_patch_id=motivo_patch_id,
            motivo_ronda=motivo_ronda,
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
        vuelo.recibo = recibo
        vuelo.ruta_recibo = ruta_recibo
        tmp = Path(tempfile.mkdtemp(prefix=f"ejecucion-{args.unidad}-", dir=str(runtime))).resolve()
        tmp.chmod(0o700)
        try:
            env = entorno_base(worktree, tmp, home_original)
            if args.harness == "codex":
                preparar_codex_home(env, tmp, home_original)
            else:
                preparar_claude_home(env, home_original)
            # Unidad 108 · R1: el id de la sesión de Claude se FIJA aquí, antes de
            # lanzar, y es lo que permite encontrar su transcript al cerrar el recibo.
            sesion_harness = str(uuid.uuid4()) if args.harness == "claude" else None
            argv = argv_harness(
                args.harness, ejecutable, args.rol, worktree, texto, documentos=documentos,
                # El contrato de la unidad manda leer bias, flujos y la síntesis de su
                # petición: docs/ del meta-repo viaja como lectura de herramientas del
                # harness claude (sin sandbox de SO, --add-dir sigue siendo la única vía
                # explícita de lectura adicional; codex la ignora porque su --add-dir
                # significa escribible).
                lecturas=(RAIZ / "docs",),
                modelo=recibo["modelo"],
                esfuerzo=recibo["esfuerzo"],
                session_id=sesion_harness,
                temporal=tmp,
            )
            contexto_ficha = (
                _ficha_solo_lectura(ficha_bloqueada)
                if ficha_bloqueada is not None
                else contextlib.nullcontext()
            )
            modo_previo_ficha = (
                stat.S_IMODE(ficha_bloqueada.stat().st_mode)
                if ficha_bloqueada is not None else None
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
                    if ficha_bloqueada is not None:
                        recibo["ficha_bloqueada"] = {
                            "ruta": str(ficha_bloqueada),
                            "modo_previo": modo_previo_ficha,
                        }
                    # Popen y no `run` (bug 077): hace falta el PID del hijo ANTES de
                    # esperarlo, para poder matarlo desde el manejador de señal y para
                    # dejarlo escrito en el recibo — es lo único que le permite a
                    # `lease.py desbloquear` rematar a un huérfano de `kill -9`.
                    proceso = subprocess.Popen(
                        comando_subproceso(ejecutable, argv, env), cwd=str(worktree), env=env,
                        stdin=subprocess.DEVNULL, **opciones_de_aislamiento(),
                    )
                    vuelo.hijo = proceso
                    recibo["harness_proceso"] = {
                        "pid": proceso.pid,
                        "pgid": _grupo_de(proceso.pid),
                        "process_started": gestion_leases.process_start_marker(proceso.pid),
                    }
                    guardar_recibo(ruta_recibo, recibo)
                    try:
                        proceso.wait(timeout=tope * 60 if tope else None)
                    except subprocess.TimeoutExpired:
                        matar_arbol(proceso.pid, proceso=proceso)
                        raise
                    finally:
                        vuelo.hijo = None
                    return tope, proceso

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
            # R2 (100) y R1 (108): se lee AQUÍ, con el temporal todavía vivo. La regla 10
            # deja de creerse por estar escrita en los DOS harness: el recibo dice con qué
            # corrió de verdad, o dice que no ha podido saberlo. Nunca se inventa.
            acreditado, esfuerzo_real, fuente = acreditar(
                args.harness, env, worktree, sesion_harness)
            if acreditado:
                recibo["model_slug"] = acreditado
                recibo["modelo"] = acreditado
                if esfuerzo_real:
                    recibo["esfuerzo"] = esfuerzo_real
                if recibo["modelo_origen"] == "tabla":
                    recibo["modelo_origen"] = "harness-acreditado"
                checkpoint(
                    recibo, "modelo-acreditado", "ok",
                    f"{acreditado} · esfuerzo {esfuerzo_real or 'sin declarar'} ({fuente})",
                )
            else:
                checkpoint(
                    recibo, "modelo-acreditado", "warn",
                    f"el {fuente} no dice con qué modelo corrió; el recibo declara lo "
                    "pedido, no lo acredita",
                )
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
            aviso_ronda = cerrar_la_ronda(
                recibo, documentos, worktree, ronda_previa, ronda_actual
            )
            guardar_recibo(ruta_recibo, recibo)
            avisos = [aviso_ronda] if aviso_ronda else []
            if recibo["resultado"] == "ok_sin_trabajo":
                avisos.append("AVISO ok_sin_trabajo: " + recibo["trabajo"]["detalle"])
            imprimir_resultado(ruta_recibo, recibo["resultado"], avisos)
            # R1: una unidad `ejecucion: documental` (y una investigación «sin cambio»)
            # sigue saliendo 0 aunque no acredite trabajo — la exención es por carril
            # escrito en la ficha, y manda también sobre el rol revisor.
            documental = (datos.get("ejecucion") or "").strip().lower() == "documental"
            carril_exento = (datos.get("carril") or "normal").strip().lower() in {
                "expres", "exprés", "directo", "documental"}
            if documental or carril_exento:
                espera_cambios = False
                rol_efectivo = "constructor"
            else:
                espera_cambios = True
                rol_efectivo = args.rol
            return exit_de_resultado(recibo["resultado"], rol_efectivo, espera_cambios)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def cerrar_la_ronda(recibo, documentos, worktree, previa, actual):
    """R4/R5 — qué queda escrito de esta vuelta. Devuelve el aviso a imprimir, o "".

    Va DESPUÉS de `huella_posterior`: lo que escriba el lanzador aquí no puede contar como
    trabajo del agente, ni en un sentido ni en el otro.

    R5 nace de `P-20260822-404f41af`: el 18 % de las ejecuciones de constructor terminó sin
    dejar un byte. Una vuelta así no es una corrección fallida, es una vuelta que no ocurrió,
    y gastarle una ronda al usuario por ella sería cobrarle un trabajo que nadie hizo. El
    criterio es el mismo `head` y el mismo `diff_sha256` con los que empezó — dos datos que
    el recibo ya guardaba y que nadie comparaba.
    """
    if not actual:
        return ""
    inicial = recibo["git"]["inicial"] or {}
    final = recibo["git"]["final"] or {}
    vacia = bool(final) and (
        inicial.get("head") == final.get("head")
        and inicial.get("diff_sha256") == final.get("diff_sha256")
    )
    recibo["ronda_vacia"] = vacia
    if vacia:
        if actual != previa and documentos:
            sellar_clave(documentos[0], "ronda", str(previa))
        recibo["ronda"] = previa
        return (
            f"AVISO ronda vacía: la ejecución terminó con el mismo commit y el mismo diff "
            f"con los que empezó, así que NO cuenta como ronda de corrección (sigue en la "
            f"{previa}). Si de verdad había que corregir algo, el agente no lo hizo"
        )
    if actual >= 2:
        medida = medida_de_la_correccion(worktree, inicial.get("head"), actual)
        if medida:
            recibo["correccion"] = medida
            if documentos:
                sellar_clave(documentos[0], "correccion", medida)
            return f"MEDIDA de la corrección: {medida} (informa, no bloquea)"
    return ""


def avisar_de_lanzamiento_interrumpido(manager, unidad):
    """R2 del bug 077: un lease cuyo dueño ya no vive NO se atraviesa en silencio.

    `kill -9`, la terminal cerrada de golpe o la conexión perdida no dejan que corra
    ningún manejador: lo que queda atrás es un lease con el PID de un proceso muerto y,
    detrás, un harness huérfano que puede seguir escribiendo en el worktree y una ficha
    en 0444. El adquirente normal retiraba ese lease él solo y seguía adelante, así que
    el huérfano y la ficha congelada quedaban ahí, invisibles, hasta que alguien se
    encontraba a mano con el desastre de Fernando.

    Se comprueba ANTES de adquirir, sin retirar nada, y se para nombrando el comando que
    lo resuelve. Un dueño VIVO no cae por aquí: eso sigue siendo el "ocupado" de siempre
    (P-20260818-3ad156c4, un lease nunca se roba)."""
    scope = f"unit:{unidad}"
    try:
        hallado = manager.inspeccionar(scope)
    except gestion_leases.LeaseError:
        return                   # lease corrupto o ilegible: lo diagnostica `acquire`
    if hallado is None:
        return
    registro, vivo = hallado
    if vivo is not False:
        return
    owner = registro.get("owner", {})
    raise ErrorEjecucion(
        f"la unidad {unidad} tiene un lanzamiento INTERRUMPIDO: el lease {scope} sigue "
        f"a nombre de la sesión {owner.get('session_id', '?')} (PID {owner.get('pid', '?')}), "
        f"que ya no existe. Puede haber quedado un harness vivo y la ficha en solo lectura. "
        f"SALIDA: python3 {Path(__file__).with_name('lease.py')} desbloquear {unidad}"
    )


def lanzar(args):
    if not RE_NOMBRE.fullmatch(args.unidad):
        raise ErrorEjecucion("unidad inválida: se esperaba NNN-slug")
    if args.rol == "revisor" and hay_arbol_que_revisar(args.unidad):
        problemas, avisos = puerta_entrega_para_revisor(args.unidad)
        for aviso in avisos:
            print(f"AVISO {aviso}")
        if problemas:
            raise ErrorEjecucion("; ".join(problemas))
    manager = gestion_leases.LeaseManager(RAIZ)
    avisar_de_lanzamiento_interrumpido(manager, args.unidad)
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
