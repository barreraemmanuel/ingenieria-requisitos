#!/usr/bin/env python3
"""actualizar.py — lleva el método de esta herramienta a los workspaces ya creados.

    python3 visor/actualizar.py buscar            encuentra workspaces y los registra
    python3 visor/actualizar.py revisar --todos    qué cambiaría (no toca nada)
    python3 visor/actualizar.py aplicar --todos    lo actualiza

POR QUÉ NO ES UN `git pull`: el workspace es OTRO repositorio, con su propio remoto. Su
copia del método salió de aquí por copia de ficheros al hacer el bootstrap; no hay
submódulo, ni subtree, ni remoto compartido. `git pull` allí trae el historial de ESE
proyecto y del método no se entera.

CÓMO SE DESHACE: con git, que para eso está. Antes de tocar se exige un repositorio con
árbol e índice limpios; su HEAD es el punto de retorno. Volver atrás es
`git checkout <ese commit>`, y el commit queda escrito en `HISTORIAL.md`.

Por eso el método se sobrescribe ENTERO, sin clasificar nada ni preguntar por cada fichero:
la copia de seguridad no es un algoritmo, es un commit. Si un proyecto había adaptado un
runbook a su gusto, esa versión no se pierde — está en el punto de retorno, a un checkout.

Solo stdlib. `revisar` no escribe nada. `aplicar` solo escribe el método y las piezas que
lo ejecutan: jamás los planos, el trabajo, los bugs, el conocimiento ni el código.
"""
import argparse
import base64
import binascii
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath

import bootstrap
import proyectos

SCRIPTS_METODO = (
    Path(__file__).resolve().parents[1] / "plantilla/docs/00-metodo/scripts"
)
if str(SCRIPTS_METODO) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_METODO))
import lease as gestion_leases
import repo_config
import workspace_paths

for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
HERRAMIENTA = BASE.parent
PLANTILLA = HERRAMIENTA / "plantilla"
HOY = datetime.date.today().isoformat()

RE_TITULO = re.compile(r"^#\s*AGENTS\.md\s*—\s*(.+?)\s*\(meta-repo\)", re.M)
HISTORIAL = "docs/00-metodo/HISTORIAL.md"
RETIRADOS_METODO = (
    "docs/00-metodo/scripts/sandbox_lanzar.py",
    # Unidad 081: las cuatro webs pasaron a ser los cuatro apartados de una sola,
    # que vive en `requisitos/web/`. Lo que dejó de existir se RETIRA del
    # workspace: si se quedara, `unidad.py` podría volver a encontrar un visor
    # viejo y levantar un quinto puerto.
    "docs/00-metodo/requisitos/servir.py",
    "docs/00-metodo/requisitos/plantilla.html",
    "docs/00-metodo/requisitos/base.css",
    "docs/00-metodo/requisitos/visor_presentaciones/abrir.py",
    "docs/00-metodo/requisitos/visor_presentaciones/manifestar.py",
    "docs/00-metodo/requisitos/visor_presentaciones/servir.py",
    "docs/00-metodo/requisitos/visor_presentaciones/plantilla.html",
    "docs/00-metodo/requisitos/visor_presentaciones/render.js",
    "docs/00-metodo/requisitos/visor_contratos/servir.py",
    "docs/00-metodo/requisitos/visor_contratos/plantilla.html",
    "docs/00-metodo/requisitos/visor_contratos/render.js",
)
CABECERA_HISTORIAL = (
    "# Historial de actualizaciones del método\n"
    "\n"
    "> Lo escribe `visor/actualizar.py` de la herramienta de ingeniería de requisitos.\n"
    "> El método se sobrescribe entero en cada actualización: lo que hubiera antes en este\n"
    "> workspace queda guardado en el commit que cada entrada anota. Para volver a ese\n"
    "> estado: `git checkout <ese commit>`.\n"
)
JOURNAL = Path(".runtime/transactions/modo-d.json")
FASES_JOURNAL = {"preparada", "escribiendo", "validada", "pre_commit", "committed"}
CLAVES_JOURNAL = {
    "formato", "operacion", "id", "fase", "punto_retorno", "snapshot",
    "publicado", "arbol_publicado", "commit",
}
CLAVES_ENTRADA = {"contenido", "modo", "sha256"}
RE_SHA_GIT = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=False)
    except OSError:
        return 1, ""
    return p.returncode, (p.stdout + p.stderr).strip()


def rutas_sucias(workspace):
    """Inventario explícito del estado que existía antes de actualizar."""
    rutas = set()
    comandos = (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
        ("ls-files", "--deleted", "-z"),
    )
    for comando in comandos:
        codigo, salida = git(workspace, *comando)
        if codigo:
            continue
        rutas.update(ruta for ruta in salida.split("\0") if ruta)
    return sorted(
        ruta for ruta in rutas
        # .claude/ guarda preferencias del dueño (personalidad, avisos de actualización)
        # que viven a propósito FUERA de lo que Modo D gestiona. El .gitignore nuevo ya
        # lo ignora, pero en un workspace anterior a ese .gitignore una preferencia
        # recién guardada bloquearía la actualización como "árbol sucio".
        if not ruta.startswith((".runtime/", "main/", "worktrees/", ".claude/"))
        # Bytecode de Python: aparece en cuanto el usuario ejecuta cualquier script del
        # método y no es trabajo de nadie. Los .gitignore nuevos ya lo ignoran, pero este
        # chequeo corre ANTES de repartir ese .gitignore: sin filtrarlo aquí, un workspace
        # viejo con __pycache__/ quedaba bloqueado para siempre ("árbol sucio").
        and "__pycache__" not in ruta.split("/")
        and not ruta.endswith((".pyc", ".pyo"))
    )


# Bug 088: el árbol sucio que detiene la actualización casi siempre lo dejó el PROPIO
# método — `peticion.py capturar` escribe en docs/05-trabajo/peticiones/, `setup.py`
# actualiza el conocimiento de la máquina y el despliegue deja su ficha— y en un
# workspace de usuario nadie hace git por él. El aviso reparte por dueño y da el
# comando exacto; `git stash` nunca es opción (la pila es única y compartida).
CARPETAS_DEL_METODO = ("docs/05-trabajo/peticiones/",)
FICHEROS_DEL_METODO = ("docs/conocimiento/entorno-de-esta-maquina.md",)
PREFIJOS_DEL_METODO = ("docs/05-trabajo/despliegue",)
MENSAJE_COLA_DEL_METODO = "docs: cola y conocimiento del método"


def raiz_del_metodo(ruta):
    """Con qué ruta se confirma `ruta` si la dejó el método; None si es del usuario.

    Lista CERRADA a propósito: lo que no esté aquí es trabajo del usuario y Modo D
    no lo stagea ni lo commitea jamás.
    """
    for carpeta in CARPETAS_DEL_METODO:
        if ruta.startswith(carpeta):
            return carpeta
    if ruta in FICHEROS_DEL_METODO:
        return ruta
    for prefijo in PREFIJOS_DEL_METODO:
        if ruta.startswith(prefijo):
            return ruta
    return None


def repartir_por_dueno(sucias):
    """(lo del método, lo del usuario, las rutas con las que se confirma lo del método)."""
    metodo, usuario, raices = [], [], []
    for ruta in sucias:
        raiz = raiz_del_metodo(ruta)
        if raiz is None:
            usuario.append(ruta)
            continue
        metodo.append(ruta)
        if raiz not in raices:
            raices.append(raiz)
    return metodo, usuario, sorted(raices)


def comando_confirmar(raices):
    return (f"git add {' '.join(raices)} "
            f'&& git commit -m "{MENSAJE_COLA_DEL_METODO}"')


def _lista(rutas, tope=10):
    lineas = [f"          {r}" for r in rutas[:tope]]
    if len(rutas) > tope:
        lineas.append(f"          … y {len(rutas) - tope} más")
    return lineas


def aviso_arbol_sucio(sucias):
    """El motivo del bloqueo, con quién dejó cada fichero y qué desbloquea cada grupo."""
    metodo, usuario, raices = repartir_por_dueno(sucias)
    lineas = ["el árbol o el índice Git está sucio; Modo D no stagea ni commitea "
              "trabajo ajeno."]
    if metodo:
        lineas.append("    Lo dejó el método (cola de peticiones, conocimiento de esta "
                      "máquina, fichas de despliegue):")
        lineas += _lista(metodo)
        lineas.append(f"      Confírmalo tal cual:  {comando_confirmar(raices)}")
        lineas.append("      O repite esto mismo con --confirmar-lo-del-metodo y lo "
                      "confirmo yo por ti.")
    if usuario:
        lineas.append("    Tuyo (Modo D no lo toca; decides tú):")
        lineas += _lista(usuario)
        lineas.append("      Guarda (git add <ruta> && git commit -m \"...\") o descarta "
                      "(git checkout -- <ruta>) y reintenta.")
    return "\n".join(lineas)


def confirmar_lo_del_metodo(workspace):
    """Confirma SOLO lo que dejó el método. Si queda algo del usuario, no toca nada.

    Devuelve el mensaje de lo que hizo (o "" si no había nada del método que confirmar).
    """
    metodo, usuario, raices = repartir_por_dueno(rutas_sucias(workspace))
    if usuario or not metodo:
        return ""
    codigo, salida = stage_explicit(workspace, raices)
    if codigo:
        return ""
    codigo, salida = git(workspace, "commit", "-m", MENSAJE_COLA_DEL_METODO, "--", *raices)
    if codigo:
        git(workspace, "reset", "--", *raices)
        return ""
    return (f"confirmo {len(metodo)} fichero(s) que dejó el método en "
            f"{', '.join(raices)} como \"{MENSAJE_COLA_DEL_METODO}\".")


def colision_tardia(workspace, rutas_tocadas):
    """Rutas del método que Modo D va a sobrescribir y que HAN ENSUCIADO desde que
    se declaró el árbol limpio. Reejecuta la comprobación de suciedad justo antes de
    escribir para no capturar (y perder) una edición aparecida en la ventana."""
    sucias = set(rutas_sucias(workspace))
    return sorted(sucias.intersection(rutas_tocadas))


def trabajo_en_vuelo(workspace):
    """Devuelve fichas cuyo estado declara trabajo operativo todavía activo."""
    candidatas = []
    trabajo = workspace / "docs/05-trabajo"
    if trabajo.is_dir():
        candidatas.extend(trabajo.glob("[0-9][0-9][0-9]-*/especificacion.md"))
    bugs = workspace / "docs/bugs"
    if bugs.is_dir():
        candidatas.extend(bugs.glob("[0-9][0-9][0-9]-*.md"))
    activas = []
    for ficha in sorted(candidatas):
        try:
            contenido = ficha.read_text(encoding="utf-8")
        except OSError:
            continue
        if re.search(r"(?m)^estado:\s*(?:en_obra|en_revision)\s*$", contenido):
            activas.append(str(ficha.relative_to(workspace)).replace("\\", "/"))
    return activas


def stage_explicit(workspace, rutas):
    rutas = sorted(set(rutas))
    if not rutas:
        return 0, ""
    return git(workspace, "add", "--", *rutas)


def git_con_stdin(repo, argumentos, contenido):
    try:
        proceso = subprocess.run(
            ["git", "-C", str(repo), *argumentos], input=contenido,
            capture_output=True, check=False,
        )
    except OSError:
        return 1, ""
    salida = (proceso.stdout + proceso.stderr).decode("utf-8", errors="replace").strip()
    return proceso.returncode, salida


def modo_git(estado):
    return "100755" if stat.S_IMODE(estado[1]) & 0o111 else "100644"


def stage_exacto(workspace, publicado):
    blobs = {}
    for relativo, estado in sorted(publicado.items()):
        if estado is None:
            codigo, salida = git(workspace, "update-index", "--force-remove", "--", relativo)
            if codigo and "no se pudo" not in salida.lower():
                raise RuntimeError(f"no pude retirar del índice {relativo}: {salida}")
            blobs[relativo] = None
            continue
        codigo, blob = git_con_stdin(workspace, ["hash-object", "-w", "--stdin"], estado[0])
        if codigo or not RE_SHA_GIT.fullmatch(blob):
            raise RuntimeError(f"no pude crear blob exacto para {relativo}: {blob}")
        codigo, salida = git(
            workspace, "update-index", "--add", "--cacheinfo", modo_git(estado), blob, relativo
        )
        if codigo:
            raise RuntimeError(f"no pude stagear blob exacto de {relativo}: {salida}")
        blobs[relativo] = (modo_git(estado), blob)
    return blobs


def verificar_stage_exacto(workspace, blobs):
    for relativo, esperado in blobs.items():
        codigo, salida = git(workspace, "ls-files", "--stage", "--", relativo)
        if esperado is None:
            if codigo == 0 and salida:
                raise RuntimeError(f"el índice conserva una ruta retirada: {relativo}")
            continue
        campos = salida.split(None, 3)
        if codigo or len(campos) < 4 or (campos[0], campos[1]) != esperado:
            raise RuntimeError(f"el índice no contiene el blob exacto de {relativo}")


def limpiar_indice(workspace, sha, rutas):
    codigo, salida = git(workspace, "reset", "--quiet", sha, "--", *sorted(set(rutas)))
    if codigo:
        raise RuntimeError(f"no pude devolver el índice al punto de retorno: {salida}")


def comprobar_remoto(workspace):
    """Fetch antes de tocar; bloquea si la rama remota contiene trabajo no local."""
    if git(workspace, "remote", "get-url", "origin")[0] != 0:
        return ""
    codigo, rama = git(workspace, "symbolic-ref", "--quiet", "--short", "HEAD")
    if codigo or not rama:
        return "no puedo verificar el remoto porque HEAD no está en una rama"
    codigo, salida = git(workspace, "fetch", "origin", rama)
    if codigo:
        return f"no pude actualizar el remoto antes de tocar:\n{salida}"
    remoto = f"origin/{rama}"
    if git(workspace, "rev-parse", "--verify", "--quiet", remoto)[0] != 0:
        return ""
    codigo, cuentas = git(workspace, "rev-list", "--left-right", "--count",
                           f"HEAD...{remoto}")
    if codigo:
        return f"no pude comparar HEAD con {remoto}: {cuentas}"
    partes = cuentas.replace("\t", " ").split()
    if len(partes) == 2 and int(partes[1]) > 0:
        return (f"el remoto {remoto} tiene {partes[1]} commit(s) que este workspace no "
                "tiene; actualízalo y vuelve a ejecutar Modo D")
    return ""


def inventario_legacy(workspace):
    trabajo = workspace / "docs/05-trabajo"
    unidades = []
    if trabajo.is_dir():
        unidades.extend(
            ruta.name
            for ruta in trabajo.iterdir()
            if ruta.is_dir()
            and ruta.name not in {"archivo", "peticiones"}
            and re.fullmatch(r"\d{3}-[a-z0-9][a-z0-9-]*", ruta.name)
        )
        archivo = trabajo / "archivo"
        if archivo.is_dir():
            unidades.extend(
                ruta.name
                for ruta in archivo.iterdir()
                if ruta.is_dir() and re.fullmatch(r"\d{3}-[a-z0-9][a-z0-9-]*", ruta.name)
            )
    bugs_dir = workspace / "docs/bugs"
    bugs = (
        [
            ruta.stem
            for ruta in bugs_dir.glob("*.md")
            if re.fullmatch(r"\d{3}-[a-z0-9][a-z0-9-]*", ruta.stem)
        ]
        if bugs_dir.is_dir()
        else []
    )
    repo, principal = repo_config.repo_code(workspace)
    codigo, salida = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    ramas = [] if codigo else [r for r in salida.splitlines() if r and r != principal]
    return {
        "formato": 1,
        "modo": "observacion",
        "unidades": sorted(set(unidades)),
        "bugs": sorted(set(bugs)),
        "ramas": sorted(set(ramas)),
    }


def contenido_esperado(workspace):
    """{ruta en el workspace: contenido que debe tener}, y los avisos que salgan.

    Mismas fuentes que el bootstrap: si el bootstrap lo coloca, esto lo actualiza.
    """
    esperado, avisos = {}, []
    era_sin_inbox = not (
        workspace / "docs/00-metodo/scripts/peticion.py"
    ).is_file()
    for relativo in bootstrap.ARCHIVOS_METODO:
        esperado[f"docs/00-metodo/{relativo}"] = (
            PLANTILLA / "docs" / "00-metodo" / relativo).read_text(encoding="utf-8")
    for nombre in bootstrap.ARCHIVOS_REQUISITOS:
        origen = (HERRAMIENTA / nombre
                  if nombre == "requirements-dev.txt" or nombre.startswith("RUNBOOK")
                  else BASE / nombre)
        esperado[f"docs/00-metodo/requisitos/{nombre}"] = origen.read_text(encoding="utf-8")
    # La web del método, entera y de una sola lista (unidad 081, R5). Antes eran
    # tres listas por visor y cada olvido fue un bug: el 064 (sin `render.js` la
    # web nacía en blanco) y el 080 (el visor de contratos no viajaba y la puerta
    # de despacho llegaba sin la llave). Misma fuente que el bootstrap.
    for nombre in bootstrap.ARCHIVOS_WEB:
        esperado[f"docs/00-metodo/requisitos/web/{nombre}"] = (
            bootstrap.origen_web(nombre).read_text(encoding="utf-8"))
    for origen in sorted((PLANTILLA / "githooks").rglob("*")):
        if origen.is_file():
            rel = origen.relative_to(PLANTILLA / "githooks")
            esperado[f".githooks/{rel}"] = origen.read_text(encoding="utf-8")
    esperado["setup.py"] = (PLANTILLA / "setup.py").read_text(encoding="utf-8")
    # El .gitignore del meta-repo es infraestructura del método: es lo que mantiene main/ y
    # worktrees/ fuera de git. Sin él, el workspace intenta versionar el repo de código.
    # Pero machacarlo ENTERO destapaba lo que el usuario ignoraba a propósito: sus ficheros
    # aparecían como untracked, el árbol quedaba «sucio» y la SIGUIENTE actualización se
    # bloqueaba por ello (caso de campo 08-08). Sus líneas se conservan bajo un marcador.
    plantilla_gitignore = (PLANTILLA / "gitignore").read_text(encoding="utf-8")
    esperado[".gitignore"] = plantilla_gitignore
    gitignore_actual = workspace / ".gitignore"
    if gitignore_actual.is_file():
        texto_actual = gitignore_actual.read_text(encoding="utf-8", errors="replace")
        base = {linea.strip() for linea in plantilla_gitignore.splitlines()}
        tuyas = [linea.rstrip() for linea in texto_actual.splitlines()
                 if linea.strip() and not linea.strip().startswith("#")
                 and linea.strip() not in base]
        if tuyas:
            fusionado = (
                plantilla_gitignore.rstrip("\n")
                + "\n\n# --- tuyas (Modo D conserva esta sección) ---\n"
                + "\n".join(tuyas) + "\n"
            )
            esperado[".gitignore"] = fusionado
            if fusionado != texto_actual:
                avisos.append(
                    f".gitignore: conservo {len(tuyas)} línea(s) tuyas bajo el marcador")
    esperado["worktrees/README.md"] = (
        PLANTILLA / "worktrees-README.md").read_text(encoding="utf-8")
    esperado[".github/workflows/lint.yml"] = bootstrap.generar_ci()
    # La preferencia de tono (`.claude/personalidad.md`, R-1601) vive fuera de este
    # dict a propósito: así Modo D nunca la toca. El import se genera siempre, exista
    # o no el fichero — un @import a un fichero ausente no rompe el arranque del
    # agente (comprobado en la práctica), y así el puente ya queda listo desde el
    # primer `aplicar` para el día en que el dueño del workspace fije su tono (R-1602).
    for puente in ("CLAUDE.md", "GEMINI.md"):
        esperado[puente] = "@AGENTS.md\n@.claude/personalidad.md\n"

    # AGENTS.md lleva dentro el título del proyecto: se compara contra la plantilla rellenada
    # con SU título. Si no se puede leer, se dice y se deja fuera — antes desaparecía del
    # informe en silencio, que es la peor de las tres opciones.
    actual = workspace / "AGENTS.md"
    if actual.is_file():
        m = RE_TITULO.search(actual.read_text(encoding="utf-8", errors="replace"))
        if m:
            esperado["AGENTS.md"] = (PLANTILLA / "AGENTS.md").read_text(
                encoding="utf-8").replace("{{TITULO}}", m.group(1))
        else:
            avisos.append("no pude leer el título en la primera línea de AGENTS.md "
                          "(se espera '# AGENTS.md — <título> (meta-repo)'): lo dejo sin "
                          "actualizar para no borrarte el nombre del proyecto")
    # Carpetas del árbol congelado ausentes (workspaces anteriores a ellas): se repone su
    # ESQUELETO vacío, tal como lo crea el bootstrap. No es tocar contenido — sin la
    # carpeta, el linter no puede volver a verde y Modo D tiene prohibido inventar fichas.
    for carpeta, ficheros in sorted(bootstrap.esqueleto_congelado().items()):
        if (workspace / carpeta).is_dir():
            continue
        for nombre, texto in ficheros.items():
            esperado[f"{carpeta}/{nombre}"] = texto
        avisos.append(
            f"falta {carpeta}/ (árbol congelado): se repone su esqueleto vacío, sin contenido"
        )
    if era_sin_inbox:
        relativo = "docs/05-trabajo/peticiones/LEGACY.json"
        esperado[relativo] = json.dumps(
            inventario_legacy(workspace),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        avisos.append(
            "se creará peticiones/LEGACY.json en modo observacion con las unidades, bugs "
            "y ramas actuales; no se inventará ningún P-ID histórico"
        )
    return esperado, avisos


def diferencias(workspace, esperado):
    """(ficheros que cambian, retirados exactos, otros restos no publicados)."""
    cambios = []
    for relativo, texto in sorted(esperado.items()):
        destino = workspace / relativo
        if not destino.is_file() or destino.read_text(encoding="utf-8",
                                                      errors="replace") != texto:
            cambios.append(relativo)
    retirados = [
        relativo for relativo in RETIRADOS_METODO
        if (workspace / relativo).is_file() or (workspace / relativo).is_symlink()
    ]
    sobrantes = []
    metodo = workspace / "docs" / "00-metodo"
    if metodo.is_dir():
        for ruta in sorted(metodo.rglob("*")):
            if not ruta.is_file() or "__pycache__" in ruta.parts:
                continue
            relativo = str(ruta.relative_to(workspace)).replace("\\", "/")
            if (
                relativo not in esperado
                and relativo != HISTORIAL
                and relativo not in RETIRADOS_METODO
            ):
                sobrantes.append(relativo)
    return cambios, retirados, sobrantes


def version_workspace(workspace):
    """La versión del método que declara el METODO.json del workspace.

    Los workspaces anteriores al 1.1.0 no llevan el campo `version` (ni a veces el
    fichero): se responde "sin versión" y no se falla, que para eso está el Modo D.
    """
    try:
        datos = json.loads((Path(workspace) / "METODO.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "sin versión"
    version = datos.get("version") if isinstance(datos, dict) else None
    if isinstance(version, str) and version.strip():
        return version.strip()
    return "sin versión"


def origen_workspace(workspace):
    """La URL del método que el workspace ya declara, si la declara."""
    try:
        datos = json.loads((Path(workspace) / "METODO.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = datos.get("origen") if isinstance(datos, dict) else None
    return url.strip() if isinstance(url, str) and url.strip() else None


def linea_version(workspace):
    actual, nueva = version_workspace(workspace), bootstrap.version_metodo()
    if actual == nueva:
        return f"método {nueva} (al día)"
    return f"método {actual} → {nueva}"


def informe(ruta, titulo, cambios, retirados, sobrantes, avisos):
    print(f"\n=== {titulo} ===\n    {ruta}")
    print(f"    {linea_version(ruta)}")
    if cambios:
        print(f"    {len(cambios)} fichero(s) del método cambian:")
        for f in cambios:
            print(f"          {f}")
    else:
        print("    Al día: nada que actualizar.")
    if retirados:
        print(f"    {len(retirados)} launcher(s) inseguro(s) conocido(s) se retiran:")
        for f in retirados:
            print(f"          {f}")
    if sobrantes:
        print(f"    {len(sobrantes)} fichero(s) que el método ya no publica (no se tocan):")
        for f in sobrantes:
            print(f"          {f}")
    for a in avisos:
        print(f"    AVISO: {a}")


def punto_de_retorno(workspace):
    """Devuelve el HEAD limpio o el motivo por el que no puede ser punto de retorno."""
    if git(workspace, "rev-parse", "--is-inside-work-tree")[0] != 0:
        return None, "el workspace no es un repositorio git con un punto de retorno"
    sucias = rutas_sucias(workspace)
    if sucias:
        return None, aviso_arbol_sucio(sucias)
    codigo, sha = git(workspace, "rev-parse", "HEAD")
    if codigo:
        return None, f"el repositorio no tiene ni un commit:\n{sha}"
    return sha.strip(), ""


def contenido_historial(workspace, sha, cambios):
    ruta = workspace / HISTORIAL
    previo = ruta.read_text(encoding="utf-8") if ruta.is_file() else CABECERA_HISTORIAL
    bloque = [f"## {HOY} · método {bootstrap.huella_plantilla()[:12]}…",
              "",
              f"Estado anterior: `{sha[:8]}` — ahí está lo que hubiera aquí antes "
              f"(`git checkout {sha[:8]}`).",
              f"{len(cambios)} fichero(s) sobrescritos:",
              ""]
    bloque += [f"- `{c}`" for c in cambios]
    return (previo.rstrip("\n") + "\n\n" + "\n".join(bloque) + "\n").encode("utf-8")


def escribir_historial(workspace, sha, cambios):
    escribir_bytes_atomico(
        workspace, HISTORIAL, contenido_historial(workspace, sha, cambios), 0o644
    )


def pasar_linter(workspace):
    linter = workspace / "docs/00-metodo/scripts/lint_metodo.py"
    if not linter.is_file():
        return False, "no existe docs/00-metodo/scripts/lint_metodo.py"
    r = subprocess.run([sys.executable, str(linter)], cwd=str(workspace), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    salida = (r.stdout + r.stderr).strip()
    if r.returncode:
        print("\n    -- el linter del método NO pasa en este workspace --")
        for linea in salida.splitlines():
            print(f"      {linea}")
    elif salida:
        print(f"    linter del método: {salida.splitlines()[-1].strip()}")
    return r.returncode == 0, salida


def lineas_fail(salida):
    """Las líneas FAIL exactas de una salida del linter, sin sangría."""
    return {
        linea.strip() for linea in salida.splitlines()
        if linea.strip().startswith("FAIL ")
    }


def fallos_del_linter(workspace, esperado=None):
    """FAIL que da AHORA el workspace; None si no hay linter que consultar.

    Es la línea base previa a actualizar: sin ella no se distingue un fallo que la
    actualización introduce de uno que el workspace ya arrastraba, y ese matiz decide
    si se revierte (culpa nuestra) o se avisa (deuda del workspace).

    Con `esperado` (el contenido del método nuevo) la línea base se mide con el linter
    NUEVO sobre el workspace viejo (`--raiz`): la MISMA vara que el chequeo posterior.
    Con la vara vieja, renombrar el mensaje de un check convertía un fallo heredado en
    «nuevo» y revertía una actualización sana (ADR-026, caso de campo 08-08). Si el
    linter nuevo no puede medir (crash, versión sin --raiz), se cae al del workspace."""
    if esperado:
        with tempfile.TemporaryDirectory(prefix="modo-d-lint-") as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            for relativo, contenido in esperado.items():
                if relativo.startswith("docs/00-metodo/scripts/"):
                    (scripts / relativo.rsplit("/", 1)[1]).write_text(
                        contenido, encoding="utf-8")
            linter_nuevo = scripts / "lint_metodo.py"
            if linter_nuevo.is_file():
                r = subprocess.run(
                    [sys.executable, str(linter_nuevo), "--raiz", str(workspace)],
                    cwd=str(workspace), capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                )
                # Exit 0 = verde; exit 1 CON líneas FAIL = medición válida en rojo.
                # Cualquier otra cosa es un linter que reventó, no una línea base.
                if r.returncode == 0:
                    return set()
                medido = lineas_fail(r.stdout + r.stderr)
                if r.returncode == 1 and medido:
                    return medido
    linter = workspace / "docs/00-metodo/scripts/lint_metodo.py"
    if not linter.is_file():
        return None
    r = subprocess.run([sys.executable, str(linter)], cwd=str(workspace), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return lineas_fail(r.stdout + r.stderr)


def snapshot_rutas(workspace, rutas):
    return {relativo: estado_ruta(workspace, relativo) for relativo in rutas}


def ruta_workspace(workspace, relativo, *, permitir_ausente=True):
    """Resuelve una ruta canónica sin seguir enlaces dentro del workspace."""
    if not isinstance(relativo, str) or not relativo or "\\" in relativo or "\0" in relativo:
        raise RuntimeError(f"journal de Modo D contiene ruta inválida: {relativo!r}")
    pura = PurePosixPath(relativo)
    if pura.is_absolute() or pura.as_posix() != relativo or any(
        parte in {"", ".", ".."} for parte in pura.parts
    ):
        raise RuntimeError(f"journal de Modo D contiene ruta no canónica: {relativo!r}")
    raiz = Path(workspace).resolve()
    actual = raiz
    for indice, parte in enumerate(pura.parts):
        actual = actual / parte
        try:
            estado = os.lstat(actual)
        except FileNotFoundError:
            if not permitir_ausente and indice == len(pura.parts) - 1:
                raise RuntimeError(f"ruta ausente durante Modo D: {relativo}")
            continue
        # No basta S_ISLNK: un junction de Windows (mklink /J, SIN privilegio) es un
        # directorio a todos los efectos para lstat, pero redirige fuera igual que un
        # symlink. Se comprobó explotable contra esta misma función (unidad 043).
        if workspace_paths.es_enlace(actual):
            raise RuntimeError(
                f"Modo D rechaza un enlace (symlink o junction) en ruta protegida: {relativo}")
        if indice < len(pura.parts) - 1 and not stat.S_ISDIR(estado.st_mode):
            raise RuntimeError(f"Modo D rechaza padre no-directorio: {relativo}")
        if indice == len(pura.parts) - 1 and not stat.S_ISREG(estado.st_mode):
            raise RuntimeError(f"Modo D rechaza objeto no regular: {relativo}")
    return actual


def preparar_padre_seguro(workspace, relativo):
    pura = PurePosixPath(relativo)
    actual = Path(workspace).resolve()
    for parte in pura.parts[:-1]:
        actual = actual / parte
        try:
            estado = os.lstat(actual)
        except FileNotFoundError:
            try:
                actual.mkdir(mode=0o755)
            except FileExistsError:
                pass
            estado = os.lstat(actual)
        if workspace_paths.es_enlace(actual) or not stat.S_ISDIR(estado.st_mode):
            raise RuntimeError(f"Modo D rechaza padre inseguro: {relativo}")
    return ruta_workspace(workspace, relativo)


def fsync_directorio(ruta):
    try:
        descriptor = os.open(ruta, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def escribir_bytes_atomico(
    workspace, relativo, contenido, modo=0o644, *, anunciar_failpoint=False
):
    if not isinstance(contenido, bytes):
        raise TypeError("la escritura atómica exige bytes")
    destino = preparar_padre_seguro(workspace, relativo)
    descriptor, temporal = tempfile.mkstemp(prefix=f".{destino.name}.modo-d-", dir=destino.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), stat.S_IMODE(modo))
            else:
                # Windows no tiene fchmod; el chmod va sobre la ruta temporal, que
                # todavía es privada de este proceso.
                os.chmod(temporal, stat.S_IMODE(modo))
            stream.write(contenido)
            stream.flush()
            os.fsync(stream.fileno())
        if anunciar_failpoint:
            gestion_leases.failpoint("actualizar_antes_reemplazo_atomico")
        # Vuelve a comprobar el destino tras escribir el temporal: un enlace creado
        # concurrentemente nunca se sigue y queda reemplazado como entrada, no como target.
        ruta_workspace(workspace, relativo)
        os.replace(temporal, destino)
        fsync_directorio(destino.parent)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def estado_ruta(workspace, relativo):
    ruta = ruta_workspace(workspace, relativo)
    try:
        estado_previo = os.lstat(ruta)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(estado_previo.st_mode):
        raise RuntimeError(f"Modo D rechaza objeto no regular: {relativo}")
    # O_BINARY: en Windows os.open abre en modo texto de la CRT y os.read
    # traduciría CRLF→LF (y truncaría en 0x1A). El snapshot debe ser los BYTES
    # exactos del disco: de ellos dependen las huellas, el journal y la reversión.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(ruta, flags)
    try:
        estado_abierto = os.fstat(descriptor)
        if not stat.S_ISREG(estado_abierto.st_mode):
            raise RuntimeError(f"Modo D rechaza objeto no regular: {relativo}")
        partes = []
        while True:
            bloque = os.read(descriptor, 1024 * 1024)
            if not bloque:
                break
            partes.append(bloque)
    finally:
        os.close(descriptor)
    return b"".join(partes), stat.S_IMODE(estado_abierto.st_mode)


def huella_estado(estado):
    if estado is None:
        return "ausente"
    contenido, modo = estado
    modo = stat.S_IMODE(modo)
    if os.name == "nt":
        # Windows no conserva el modo Unix: un 0o644/0o755 recién escrito se relee como
        # 0o666, y el fichero que Modo D ACABABA de publicar pasaba por "trabajo ajeno"
        # y abortaba la actualización (caso de campo, 09-08). Se colapsa el modo a
        # escribible/solo-lectura, que es lo único que Windows distingue; el sha256 del
        # contenido sigue siendo exacto.
        modo = 0o666 if modo & 0o200 else 0o444
    return f"{modo:04o}:{hashlib.sha256(contenido).hexdigest()}"


def estados_iguales(primero, segundo):
    return huella_estado(primero) == huella_estado(segundo)


def verificar_estado_publicado(workspace, publicado):
    divergentes = [
        relativo
        for relativo, esperado in publicado.items()
        if not estados_iguales(estado_ruta(workspace, relativo), esperado)
    ]
    if divergentes:
        muestra = ", ".join(divergentes[:5])
        raise RuntimeError(
            "trabajo ajeno cambió una ruta que Modo D acababa de publicar; "
            f"no stageo ni sobrescribo: {muestra}"
        )


def verificar_recuperable(workspace, original, publicado):
    conflictos = []
    for relativo in original:
        actual = estado_ruta(workspace, relativo)
        if not estados_iguales(actual, original[relativo]) and not estados_iguales(
            actual, publicado[relativo]
        ):
            conflictos.append(relativo)
    if conflictos:
        raise RuntimeError(
            "journal válido pero hay trabajo ajeno en sus rutas; conservo journal y bytes: "
            + ", ".join(conflictos[:5])
        )


def restaurar_rutas(workspace, snapshot):
    nuevas = []
    for relativo, previo in snapshot.items():
        ruta = ruta_workspace(workspace, relativo)
        if previo is None:
            if ruta.is_file() or ruta.is_symlink():
                ruta.unlink()
                nuevas.append(ruta.parent)
            continue
        contenido, modo = previo
        escribir_bytes_atomico(workspace, relativo, contenido, modo)
    for carpeta in sorted(set(nuevas), key=lambda p: len(p.parts), reverse=True):
        actual = carpeta
        while actual != workspace:
            try:
                actual.rmdir()
            except OSError:
                break
            actual = actual.parent


def datos_snapshot(snapshot):
    serializado = {}
    for relativo, previo in snapshot.items():
        if previo is None:
            serializado[relativo] = None
            continue
        contenido, modo = previo
        serializado[relativo] = {
            "contenido": base64.b64encode(contenido).decode("ascii"),
            "modo": stat.S_IMODE(modo),
            "sha256": hashlib.sha256(contenido).hexdigest(),
        }
    return serializado


def snapshot_desde_datos(datos):
    if not isinstance(datos, dict) or not datos:
        raise ValueError("snapshot debe ser un objeto no vacío")
    snapshot = {}
    for relativo, previo in datos.items():
        # Valida la ruta aunque el valor sea null antes de tocar ningún fichero.
        if not isinstance(relativo, str):
            raise ValueError("snapshot contiene una ruta que no es texto")
        if previo is None:
            snapshot[relativo] = None
            continue
        if not isinstance(previo, dict) or set(previo) != CLAVES_ENTRADA:
            raise ValueError(f"entrada de snapshot inválida: {relativo}")
        if not isinstance(previo["contenido"], str) or not isinstance(previo["modo"], int):
            raise ValueError(f"tipos de snapshot inválidos: {relativo}")
        if isinstance(previo["modo"], bool) or not 0 <= previo["modo"] <= 0o777:
            raise ValueError(f"modo de snapshot inválido: {relativo}")
        if not isinstance(previo["sha256"], str) or not RE_SHA256.fullmatch(previo["sha256"]):
            raise ValueError(f"digest de snapshot inválido: {relativo}")
        try:
            contenido = base64.b64decode(previo["contenido"].encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise ValueError(f"base64 de snapshot inválido: {relativo}") from exc
        if hashlib.sha256(contenido).hexdigest() != previo["sha256"]:
            raise ValueError(f"digest de snapshot no coincide: {relativo}")
        snapshot[relativo] = (contenido, previo["modo"])
    return snapshot


def validar_journal(workspace, datos):
    if not isinstance(datos, dict) or set(datos) != CLAVES_JOURNAL:
        raise ValueError("schema cerrado de journal inválido")
    if datos["formato"] != 2 or datos["operacion"] != "modo-d":
        raise ValueError("versión u operación de journal inválida")
    try:
        if str(uuid.UUID(datos["id"])) != datos["id"]:
            raise ValueError("id de journal no canónico")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("id de journal inválido") from exc
    if datos["fase"] not in FASES_JOURNAL:
        raise ValueError("fase de journal inválida")
    if not isinstance(datos["punto_retorno"], str) or not RE_SHA_GIT.fullmatch(
        datos["punto_retorno"]
    ):
        raise ValueError("punto de retorno inválido")
    for clave in ("arbol_publicado", "commit"):
        valor = datos[clave]
        if valor is not None and (not isinstance(valor, str) or not RE_SHA_GIT.fullmatch(valor)):
            raise ValueError(f"{clave} inválido")
    snapshot = snapshot_desde_datos(datos["snapshot"])
    publicado = snapshot_desde_datos(datos["publicado"])
    if set(snapshot) != set(publicado):
        raise ValueError("snapshot y publicado deben cubrir las mismas rutas")
    for relativo in snapshot:
        ruta_workspace(workspace, relativo)
    return snapshot, publicado


def escribir_journal(
    workspace, sha, snapshot, fase, *, publicado=None, identificador=None,
    arbol_publicado=None, commit=None,
):
    ruta = workspace / JOURNAL
    if identificador is None and ruta.is_file():
        try:
            identificador = json.loads(ruta.read_text(encoding="utf-8")).get("id")
        except (OSError, ValueError, AttributeError):
            pass
    datos = {
            "formato": 2,
            "operacion": "modo-d",
            "id": identificador or str(uuid.uuid4()),
            "fase": fase,
            "punto_retorno": sha,
            "snapshot": datos_snapshot(snapshot),
            "publicado": datos_snapshot(publicado if publicado is not None else snapshot),
            "arbol_publicado": arbol_publicado,
            "commit": commit,
        }
    contenido = (json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    escribir_bytes_atomico(workspace, JOURNAL.as_posix(), contenido, 0o600)


def recuperar_journal(workspace):
    ruta = workspace / JOURNAL
    if not ruta.is_file():
        return False
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        snapshot, publicado = validar_journal(workspace, datos)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise RuntimeError(f"journal de Modo D ilegible; no toco nada: {exc}") from exc
    if datos["fase"] in {"pre_commit", "committed"}:
        codigo, cabecera = git(workspace, "show", "-s", "--format=%H%n%T%n%B", "HEAD")
        lineas = cabecera.splitlines()
        head = lineas[0] if len(lineas) > 0 else ""
        arbol = lineas[1] if len(lineas) > 1 else ""
        mensaje = "\n".join(lineas[2:])
        trailer = re.search(
            rf"^Modo-D-Operation:\s*{re.escape(datos['id'])}\s*$", mensaje, flags=re.M
        )
        commit_exacto = (
            codigo == 0
            and datos["arbol_publicado"] is not None
            and arbol == datos["arbol_publicado"]
            and trailer is not None
            and (datos["commit"] is None or datos["commit"] == head)
        )
        if commit_exacto:
            verificar_estado_publicado(workspace, publicado)
            ruta.unlink()
            fsync_directorio(ruta.parent)
            print("    Cerré el journal de una actualización que ya estaba commiteada.")
            return True
        if datos["fase"] == "committed":
            raise RuntimeError(
                "journal marcado committed no coincide con HEAD/trailer/árbol; no toco nada"
            )
    verificar_recuperable(workspace, snapshot, publicado)
    restaurar_rutas(workspace, snapshot)
    # Una muerte entre el stage exacto y el commit deja el ÍNDICE con el método nuevo:
    # restaurar el árbol sin limpiarlo bloqueaba la siguiente ejecución con un «índice
    # sucio» que no era del usuario (revisión adversarial 12-08). El punto de retorno
    # del journal es HEAD (no hubo commit), así que se repone índice = HEAD en las
    # rutas de la operación.
    limpiar_indice(workspace, datos["punto_retorno"], sorted(snapshot))
    ruta.unlink()
    print("    Recuperé una actualización interrumpida desde su journal durable.")
    return True


def preparar_publicado(workspace, cambios, retirados, esperado, snapshot, sha, operaciones):
    publicado = {}
    for relativo in snapshot:
        if relativo in retirados:
            publicado[relativo] = None
        elif relativo in cambios:
            destino = PurePosixPath(relativo)
            ejecutable = destino.suffix == ".py" or destino.parent.name == ".githooks"
            modo = 0o755 if ejecutable else (
                stat.S_IMODE(snapshot[relativo][1]) if snapshot[relativo] is not None else 0o644
            )
            publicado[relativo] = (esperado[relativo].encode("utf-8"), modo)
        elif relativo == "METODO.json":
            datos = {"formato": 1, "huella": bootstrap.huella_plantilla(),
                     "actualizado": HOY, "version": bootstrap.version_metodo(),
                     "archivos": bootstrap.manifiesto_metodo()}
            # `origen` es lo que hace autosuficiente al workspace: con esa URL su
            # herramienta.py comprueba y descarga el método sin depender de ninguna
            # carpeta local. Se conserva la que ya tuviera (es SUYA, no de esta copia)
            # y solo se repone cuando falta: los workspaces nacidos antes de que
            # existiera el campo se vuelven autosuficientes en su primera actualización.
            url_origen = origen_workspace(workspace) or bootstrap.origen_herramienta()
            if url_origen:
                datos["origen"] = url_origen
            metodo = json.dumps(
                datos, ensure_ascii=False, indent=2, sort_keys=True,
            ) + "\n"
            publicado[relativo] = (metodo.encode("utf-8"), 0o644)
        elif relativo == HISTORIAL:
            publicado[relativo] = (contenido_historial(workspace, sha, operaciones), 0o644)
        else:  # pragma: no cover - rutas_tocadas se construye de manera cerrada
            raise RuntimeError(f"ruta publicada sin contenido definido: {relativo}")
    return publicado


def _aplicar_bajo_lease(workspace, titulo, autoridad, confirmar_metodo=False):
    repo_config.repo_code(workspace)
    # El método compara BYTES (huellas sha256, journal, reversión exacta): en el
    # meta-repo git no convierte finales de línea jamás. Config del repo, no
    # global (Windows suele traer autocrlf=true); idempotente y autosanadora.
    git(workspace, "config", "core.autocrlf", "false")
    recuperar_journal(workspace)
    problema_remoto = comprobar_remoto(workspace)
    if problema_remoto:
        print(f"\n    NO TOCO NADA: {problema_remoto}")
        return 1
    activas = trabajo_en_vuelo(workspace)
    if activas:
        # ADR-025: el trabajo aparcado no bloquea. El riesgo que motivaba el bloqueo
        # lo cierran el lease de workspace, el árbol limpio y el stage exacto.
        print("\n    OJO, trabajo en vuelo declarado: " + ", ".join(activas))
        print("    Actualizo igualmente: tu trabajo queda intacto y esas unidades "
              "cerrarán ya con el método nuevo.")
    if confirmar_metodo:
        hecho = confirmar_lo_del_metodo(workspace)
        if hecho:
            print(f"\n    {hecho}")
    sha, motivo = punto_de_retorno(workspace)
    if sha is None:
        print(f"\n    NO TOCO NADA: {motivo}")
        return 1
    esperado, avisos = contenido_esperado(workspace)
    cambios, retirados, sobrantes = diferencias(workspace, esperado)
    informe(workspace, titulo, cambios, retirados, sobrantes, avisos)
    if not cambios and not retirados:
        return 0

    fallos_previos = fallos_del_linter(workspace, esperado)
    operaciones = list(cambios) + list(retirados)
    rutas_tocadas = list(operaciones)
    for extra in ("METODO.json", HISTORIAL):
        if extra not in rutas_tocadas:
            rutas_tocadas.append(extra)
    snapshot = snapshot_rutas(workspace, rutas_tocadas)
    # Cierre de carrera: entre punto_de_retorno (que declaró el árbol limpio) y aquí
    # corrió el linter completo — segundos en los que el usuario u otro agente pudo
    # editar un fichero del método. Sin este recheck, el snapshot habría capturado
    # esa edición como "original" y el bucle la sobrescribiría y commitearía: pérdida
    # silenciosa. Si cualquier ruta a tocar ensució, se aborta ANTES de escribir nada.
    colision = colision_tardia(workspace, rutas_tocadas)
    if colision:
        print(f"\n    NO TOCO NADA: apareció trabajo sin commitear en rutas del método "
              f"mientras preparaba la actualización: {', '.join(colision)}. Commitéalo o "
              f"descártalo y reintenta.")
        return 1
    publicado = preparar_publicado(
        workspace, cambios, retirados, esperado, snapshot, sha, operaciones
    )
    identificador = str(uuid.uuid4())
    escribir_journal(
        workspace, sha, snapshot, "preparada", publicado=publicado,
        identificador=identificador,
    )

    for indice, (relativo, estado) in enumerate(sorted(publicado.items())):
        autoridad.assert_owner()
        destino = ruta_workspace(workspace, relativo)
        if estado is None:
            if destino.exists():
                destino.unlink()
        else:
            escribir_bytes_atomico(
                workspace, relativo, estado[0], estado[1], anunciar_failpoint=True,
            )
        if indice == 0:
            escribir_journal(
                workspace, sha, snapshot, "escribiendo", publicado=publicado,
                identificador=identificador,
            )
            gestion_leases.failpoint("actualizar_despues_primera_escritura")

    linter_ok, salida_linter = pasar_linter(workspace)
    if not linter_ok:
        actuales = lineas_fail(salida_linter)
        if fallos_previos is None:
            heredados, nuevos = [], sorted(actuales)
        else:
            heredados = sorted(actuales & fallos_previos)
            nuevos = sorted(actuales - fallos_previos)
        if actuales and not nuevos:
            # Todos los FAIL ya estaban antes de tocar nada: revertir no limpia
            # ninguno y bloquear dejaría al workspace atrapado en el método viejo
            # (la misma trampa que el ADR-025 quitó del trabajo en vuelo).
            print(f"\n    OJO: el linter sigue en rojo, pero sus {len(heredados)} fallo(s) "
                  "ya estaban antes de actualizar. La actualización no los causó y se "
                  "queda; conviene limpiarlos ya con el método al día.")
        else:
            verificar_recuperable(workspace, snapshot, publicado)
            restaurar_rutas(workspace, snapshot)
            (workspace / JOURNAL).unlink(missing_ok=True)
            print("\n    ACTUALIZACIÓN REVERTIDA: solo se restauraron las rutas que esta "
                  "ejecución había tocado.")
            if not actuales:
                print("    El linter terminó mal sin imprimir ningún FAIL (¿reventó?): "
                      "no me fío de dejar la actualización puesta.")
            elif fallos_previos is None:
                print("    El linter falló y no había linter anterior con el que comparar, "
                      "así que no puedo asegurar que el rojo no sea de la actualización.")
            else:
                print(f"    La actualización introdujo {len(nuevos)} fallo(s) que antes "
                      "no estaban:")
                for fallo in nuevos:
                    print(f"      {fallo}")
                if heredados:
                    print(f"    (otros {len(heredados)} fallo(s) ya estaban antes: esos "
                          "no los causó la actualización)")
            return 1

    autoridad.assert_owner()
    gestion_leases.failpoint("actualizar_antes_stage_final")
    try:
        verificar_estado_publicado(workspace, publicado)
    except RuntimeError:
        limpiar_indice(workspace, sha, rutas_tocadas)
        raise
    escribir_journal(
        workspace, sha, snapshot, "validada", publicado=publicado,
        identificador=identificador,
    )
    try:
        blobs = stage_exacto(workspace, publicado)
        codigo, arbol_publicado = git(workspace, "write-tree")
        if codigo or not RE_SHA_GIT.fullmatch(arbol_publicado):
            raise RuntimeError(f"no pude identificar el árbol exacto publicado: {arbol_publicado}")
        escribir_journal(
            workspace, sha, snapshot, "pre_commit", publicado=publicado,
            identificador=identificador, arbol_publicado=arbol_publicado,
        )
        gestion_leases.failpoint("actualizar_despues_stage_exact")
        verificar_estado_publicado(workspace, publicado)
        verificar_stage_exacto(workspace, blobs)
    except RuntimeError:
        limpiar_indice(workspace, sha, rutas_tocadas)
        raise
    # El commit lleva TODO el índice: si el usuario metió un `git add` ajeno entre el
    # punto de retorno y aquí, ese trabajo entraría en silencio en el commit del
    # método — la clase de absorción que el P0 de 1.2.0 cerró para el árbol. Se
    # revierte entero; el índice del usuario queda exactamente como él lo dejó.
    codigo, staged = git(workspace, "diff", "--cached", "--name-only")
    ajenas = ([] if codigo else
              sorted(set(staged.splitlines()) - set(rutas_tocadas) - {""}))
    if codigo or ajenas:
        limpiar_indice(workspace, sha, rutas_tocadas)
        verificar_recuperable(workspace, snapshot, publicado)
        restaurar_rutas(workspace, snapshot)
        (workspace / JOURNAL).unlink(missing_ok=True)
        print(f"\n    ACTUALIZACIÓN REVERTIDA: apareció un git add tuyo a mitad de "
              f"actualización ({', '.join(ajenas) or 'no pude listar el índice'}). No "
              f"absorbo trabajo ajeno: tu índice queda como estaba; commitéalo o "
              f"quítalo del índice y reintenta.")
        return 1
    codigo, salida = git(workspace, "commit", "-m",
                         f"Método actualizado desde la herramienta ({len(operaciones)} ficheros)",
                         "-m", f"Modo-D-Operation: {identificador}")
    if codigo:
        limpiar_indice(workspace, sha, rutas_tocadas)
        verificar_recuperable(workspace, snapshot, publicado)
        restaurar_rutas(workspace, snapshot)
        (workspace / JOURNAL).unlink(missing_ok=True)
        print(f"\n    ACTUALIZACIÓN REVERTIDA: no pude crear el commit final: {salida}")
        return 1
    gestion_leases.failpoint("actualizar_despues_commit")
    _, commit = git(workspace, "rev-parse", "HEAD")
    escribir_journal(
        workspace, sha, snapshot, "committed", publicado=publicado,
        identificador=identificador, arbol_publicado=arbol_publicado, commit=commit,
    )
    (workspace / JOURNAL).unlink(missing_ok=True)
    print(f"\n    {len(cambios)} fichero(s) sobrescritos y {len(retirados)} retirado(s)"
          " y commiteados.")
    print(f"    Para volver atrás:  git -C {workspace} checkout {sha[:8]}")
    print(f"    Queda anotado en:   {HISTORIAL}")
    return 0


def sembrar_ganchos_locales(workspace):
    """Los hooks del canario en `.claude/`, para los workspaces que ya existían.

    Van FUERA de la transacción a propósito: `.claude/` está gitignorada —es preferencia
    local del dueño— y no forma parte del conjunto publicado que Modo D versiona, revierte
    y comprueba por huella. La siembra es idempotente y aditiva (respeta lo que hubiera),
    así que un fallo aquí no puede dejar el workspace a medias; se traga y se sigue.

    Sin esto, el hook `Stop` del bug 062 solo llegaría a los workspaces nuevos y el canario
    seguiría invisible justo donde ya se trabaja.
    """
    try:
        bootstrap.sembrar_hooks_locales(workspace)
    except OSError:
        pass


def aplicar(workspace, titulo, confirmar_metodo=False):
    try:
        ruta_workspace(workspace, JOURNAL.as_posix())
        manager = gestion_leases.LeaseManager(workspace)
        with manager.acquire(("workspace", "git-index")) as autoridad:
            codigo = _aplicar_bajo_lease(
                workspace, titulo, autoridad, confirmar_metodo)
        if codigo == 0:
            sembrar_ganchos_locales(workspace)
        return codigo
    except gestion_leases.LeaseBusy as exc:
        print(f"\n=== {titulo} ===\n    {workspace}\n    NO TOCO NADA: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"\n=== {titulo} ===\n    {workspace}\n    NO TOCO NADA: {exc}")
        return 1


SALTAR = {"node_modules", "__pycache__", "Library", "Applications", ".git", ".venv",
          "venv", "worktrees", "main", "dist", "build", ".Trash", "System", "vendor"}
RAICES_HABITUALES = ("Project", "Projects", "Proyectos", "Developer", "dev", "code",
                     "Documents", "Desktop", "repos", "src", "work")


def raiz_herramienta():
    return Path(os.environ.get(
        "INGENIERIA_REQUISITOS_HERRAMIENTA",
        str(Path(__file__).resolve().parents[1]),
    ))


def desfase_herramienta():
    """Cuántos commits va esta copia de la herramienta por detrás de su origin.

    None si no se puede saber (sin git, sin remoto, sin red): eso jamás detiene nada.
    Existe porque el método se reparte desde clones, y sin este aviso un usuario
    puede pasarse semanas repartiendo un método viejo convencido de que actualiza."""
    raiz = str(raiz_herramienta())
    if os.environ.get("INGENIERIA_REQUISITOS_SIN_FETCH") != "1":
        try:
            subprocess.run(["git", "-C", raiz, "fetch", "--quiet"],
                           capture_output=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            pass
    r = subprocess.run(["git", "-C", raiz, "rev-list", "--count", "HEAD..origin/main"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        return None
    salida = r.stdout.strip()
    return int(salida) if salida.isdigit() else None


def avisar_herramienta_vieja():
    atras = desfase_herramienta()
    if atras:
        print(f"OJO: esta copia de la herramienta va {atras} commit(s) por detrás de su "
              "origin.\nLo que repartas ahora será un método viejo: haz `git pull` aquí "
              "antes de actualizar tus proyectos.\n")


# Preferencia del canal proactivo (el aviso al arrancar el agente de un workspace).
# Vive en .claude/ a propósito: fuera de git y de contenido_esperado(), así ni Modo D
# ni una actualización la pisan jamás — mismo patrón que .claude/personalidad.md.
PREFERENCIAS = ".claude/actualizaciones.md"
CABECERA_PREFERENCIAS = (
    "# Avisos de actualización del método\n"
    "\n"
    "> Lo lee el arranque del agente (AGENTS.md § Al arrancar). La línea\n"
    "> `preferencia: nunca` silencia el aviso de versión nueva en todos los arranques\n"
    "> futuros de este workspace; borra esa línea para volver a preguntarlo.\n"
    "> La línea `herramienta: <ruta>` recuerda dónde vive la herramienta en esta máquina.\n"
)


def preferencia_nunca(workspace):
    try:
        texto = (Path(workspace) / PREFERENCIAS).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(re.search(r"(?mi)^preferencia:\s*nunca\s*$", texto))


def guardar_nunca(workspace):
    ruta = Path(workspace) / PREFERENCIAS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    previo = ""
    if ruta.is_file():
        previo = ruta.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?mi)^preferencia:\s*nunca\s*$", previo):
            return
    base = previo.rstrip("\n") + "\n" if previo.strip() else CABECERA_PREFERENCIAS + "\n"
    ruta.write_text(base + "preferencia: nunca\n", encoding="utf-8")


def comprobar_aviso(workspace):
    """El mensaje del aviso proactivo, o "" si no toca avisar.

    "" también cuando el origen del método no responde: sin red, sin remoto o repo
    privado sin credenciales con acceso son el mismo caso (R5) — el arranque del
    agente sigue sin aviso, sin bloquear y sin pedir nada. El acceso se comprueba con
    las credenciales git que YA tiene la máquina para esta copia de la herramienta
    (el fetch de desfase_herramienta), nunca con un fetch anónimo.
    """
    workspace = Path(workspace).expanduser().resolve()
    if preferencia_nunca(workspace):
        return ""
    atras = desfase_herramienta()
    if atras is None:
        return ""
    huella_ws = proyectos.leer_marca(workspace)
    if not atras and huella_ws == bootstrap.huella_plantilla():
        return ""
    lineas = ["Hay una actualización del método para este workspace: "
              + linea_version(workspace)]
    if atras:
        lineas.append(f"    (esta copia de la herramienta va {atras} commit(s) por "
                      "detrás de su origin: haz `git pull` en ella antes de aplicar)")
    lineas += [
        "Responde una vez por sesión:",
        f"    sí           → python3 visor/actualizar.py aplicar {workspace}",
        "    todos        → python3 visor/actualizar.py aplicar --todos",
        "    no por ahora → seguir tal cual; se volverá a preguntar en otro arranque",
        f"    nunca más    → python3 visor/actualizar.py avisar {workspace} --nunca",
    ]
    return "\n".join(lineas)


def cmd_avisar(args):
    ws = Path(args.ruta).expanduser().resolve()
    if not es_workspace(ws):
        # El canal proactivo jamás bloquea un arranque; solo persistir la
        # preferencia sobre una ruta que no es un workspace es un error de verdad.
        print(f"No parece un workspace generado: {ws}")
        return 1 if args.nunca else 0
    if args.nunca:
        guardar_nunca(ws)
        print(f"Guardado en {PREFERENCIAS}: no volveré a avisar de actualizaciones "
              f"del método en {ws}.")
        return 0
    mensaje = comprobar_aviso(ws)
    if mensaje:
        print(mensaje)
    return 0


def es_workspace(ruta):
    """AGENTS.md + los planos dentro. Nunca dentro de la propia herramienta: la regla 2 de
    su AGENTS.md prohíbe guardar proyectos aquí, así que tampoco se registran."""
    ruta = ruta.resolve()
    if ruta == HERRAMIENTA or HERRAMIENTA in ruta.parents:
        return False
    return ((ruta / "AGENTS.md").is_file()
            and (ruta / "docs/02-flujos/planos/planos.json").is_file())


def buscar(raices, profundidad=3):
    """Rastrea el disco buscando workspaces de esta herramienta y devuelve sus rutas.

    Existe porque el registro local solo conoce lo que se creó en ESTA máquina con esta
    herramienta: un workspace clonado de GitHub, movido de sitio o creado en el portátil de
    al lado no está en él, y sin esto habría que registrarlo a mano uno por uno.
    """
    encontrados, vistos = [], set()

    def recorrer(ruta, resto):
        try:
            hijos = sorted(p for p in ruta.iterdir() if p.is_dir())
        except (OSError, PermissionError):
            return
        for hijo in hijos:
            if hijo.name.startswith(".") or hijo.name in SALTAR or hijo.is_symlink():
                continue
            real = hijo.resolve()
            if real in vistos:
                continue
            vistos.add(real)
            if es_workspace(hijo):
                encontrados.append(hijo.resolve())
                continue                       # dentro de un workspace no hay otro
            if resto:
                recorrer(hijo, resto - 1)

    for raiz in raices:
        raiz = Path(raiz).expanduser()
        if raiz.is_dir():
            if es_workspace(raiz):
                encontrados.append(raiz.resolve())
            else:
                recorrer(raiz, profundidad)
    return sorted(set(encontrados))


def raices_por_defecto():
    """Dónde mirar si el usuario no dice: su carpeta de usuario, las carpetas de trabajo
    típicas, y el vecindario de los proyectos que ya conocemos."""
    casa = Path.home()
    raices = [casa] + [casa / nombre for nombre in RAICES_HABITUALES]
    for p in proyectos.cargar()["proyectos"]:
        padre = Path(p["ruta"]).parent
        if padre.is_dir():
            raices.append(padre)
    return raices


def cmd_buscar(args):
    raices = args.en or raices_por_defecto()
    print("Buscando workspaces (carpetas con AGENTS.md y planos dentro) en:")
    for r in raices[:8]:
        print(f"    {r}")
    if len(raices) > 8:
        print(f"    … y {len(raices) - 8} sitio(s) más")
    hallados = buscar(raices, profundidad=args.profundidad)
    conocidos = {p["ruta"] for p in proyectos.cargar()["proyectos"]}
    nuevos = [h for h in hallados if str(h) not in conocidos]
    print(f"\n{len(hallados)} workspace(s) encontrados · {len(nuevos)} sin registrar.")
    for h in hallados:
        print(f"    [{'NUEVO' if h in nuevos else 'ya registrado'}] {h}")
    for h in nuevos:
        proyectos.registrar(h)
    if nuevos:
        print(f"\nRegistrados {len(nuevos)}. Ahora: python3 visor/actualizar.py revisar --todos")
    elif not hallados:
        print("\nNinguno. Si están en otro sitio: "
              "python3 visor/actualizar.py buscar --en /ruta/donde/estan")
    return 0


def objetivos(args):
    datos = proyectos.cargar()["proyectos"]
    if args.todos:
        return datos
    ruta = str(Path(args.ruta).expanduser().resolve())
    encontrados = [p for p in datos if p.get("ruta") == ruta]
    return encontrados or [{"ruta": ruta, "titulo": Path(ruta).name}]


def main():
    ap = argparse.ArgumentParser(
        description="Lleva el método de esta herramienta a los workspaces ya creados.")
    sub = ap.add_subparsers(dest="orden", required=True)
    p_buscar = sub.add_parser("buscar",
                              help="rastrea el disco, encuentra workspaces y los registra")
    p_buscar.add_argument("--en", nargs="*", metavar="RUTA",
                          help="dónde mirar (por defecto: tu carpeta de usuario y las de "
                               "trabajo habituales)")
    p_buscar.add_argument("--profundidad", type=int, default=3,
                          help="cuántas carpetas hacia dentro (defecto: 3)")
    p_buscar.set_defaults(func=cmd_buscar)
    for nombre, ayuda in (("revisar", "informe; no toca nada"),
                          ("aplicar", "sobrescribe el método, con punto de retorno en git")):
        p = sub.add_parser(nombre, help=ayuda)
        grupo = p.add_mutually_exclusive_group(required=True)
        grupo.add_argument("ruta", nargs="?", help="carpeta del workspace <proyecto>-agents")
        grupo.add_argument("--todos", action="store_true", help="todos los registrados")
        if nombre == "aplicar":
            p.add_argument(
                "--confirmar-lo-del-metodo", action="store_true",
                help="si lo único sin confirmar lo dejó el método (cola de peticiones, "
                     "conocimiento de esta máquina, fichas de despliegue), lo commitea "
                     f'como "{MENSAJE_COLA_DEL_METODO}" y sigue. Si queda algo tuyo, para '
                     "igual y te lo nombra",
            )
    p_avisar = sub.add_parser(
        "avisar",
        help="canal proactivo del arranque: ¿hay método más nuevo para este workspace? "
             "No escribe nada (salvo con --nunca) y nunca bloquea",
    )
    p_avisar.add_argument("ruta", help="carpeta del workspace <proyecto>-agents")
    p_avisar.add_argument("--nunca", action="store_true",
                          help="guarda la preferencia de no volver a avisar en este workspace")
    args = ap.parse_args()
    if args.orden == "avisar":
        return cmd_avisar(args)
    if args.orden == "buscar" or getattr(args, "todos", False):
        # Solo en las entradas "de campaña": una ruta suelta debe funcionar sin red.
        avisar_herramienta_vieja()
    if args.orden == "buscar":
        return args.func(args)

    lista = objetivos(args)
    if not lista:
        print("No hay proyectos registrados. Regístralos con "
              "`python3 visor/proyectos.py registrar RUTA`.")
        return 0
    print(f"Método de esta herramienta: versión {bootstrap.version_metodo()} "
          f"· huella {bootstrap.huella_plantilla()[:12]}…")
    salida, pendientes = 0, 0
    for entrada in lista:
        ruta = Path(entrada["ruta"])
        titulo = entrada.get("titulo", ruta.name)
        if not ruta.is_dir():
            print(f"\n=== {titulo} ===\n    {ruta}\n    NO ENCONTRADO (¿movido o borrado?)")
            continue
        try:
            if args.orden == "revisar":
                repo_config.repo_code(ruta)
                esperado, avisos = contenido_esperado(ruta)
                cambios, retirados, sobrantes = diferencias(ruta, esperado)
                informe(ruta, titulo, cambios, retirados, sobrantes, avisos)
                pendientes += 1 if cambios or retirados else 0
            else:
                salida |= aplicar(
                    ruta, titulo,
                    getattr(args, "confirmar_lo_del_metodo", False))
        except (OSError, repo_config.RepoConfigError) as e:
            # Un proyecto roto no puede llevarse por delante la revisión de los demás.
            print(f"\n=== {titulo} ===\n    {ruta}\n    NO PUDE LEERLO: {e}")
            salida = 1
    if args.orden == "revisar":
        print(f"\n{pendientes} proyecto(s) con cambios pendientes de {len(lista)} revisado(s).")
        if pendientes:
            print("Para aplicarlos: python3 visor/actualizar.py aplicar --todos "
                  "(o con la ruta de uno). Antes de tocar exige HEAD, árbol e índice "
                  "limpios; ese HEAD permite deshacer con un checkout.")
    return salida


if __name__ == "__main__":
    sys.exit(main())
