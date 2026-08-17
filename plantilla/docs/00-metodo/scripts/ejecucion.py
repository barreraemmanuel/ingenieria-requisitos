#!/usr/bin/env python3
"""Control plane fail-closed para lanzar Claude o Codex en una unidad real.

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
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import control_plane
import lease as gestion_leases
import workspace_paths

control_plane.redactar_salidas()


RAIZ = Path(__file__).resolve().parents[3]
MAIN = RAIZ / "main"
WORKTREES = RAIZ / "worktrees"
ESTADOS_EJECUTABLES = {"en_obra", "en_revision"}
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
    # ADR-027: sin SystemRoot un ejecutable NATIVO de Windows no encuentra las DLL del
    # sistema y el proceso se aborta antes de main() con 0xC0000409 (exit 3221226505),
    # sin un solo mensaje. Medido: la misma allowlist sin SystemRoot da 3221226505 y
    # añadiendo SOLO esa variable da exit 0. Las demás son el mínimo para que el CLI
    # funcione de verdad y no solo arranque (cachés, shell, resolución de ejecutables).
    # En Linux y macOS no existen y el filtro `if os.environ.get(clave)` las omite solas:
    # no hace falta lógica por plataforma.
    "SystemRoot", "SystemDrive", "windir", "ComSpec", "PATHEXT",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "ProgramData",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
}


class ErrorEjecucion(Exception):
    pass


def git(cwd, *args):
    resultado = subprocess.run(
        ["git", *args], cwd=str(cwd), text=True, capture_output=True
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
            if estado not in ESTADOS_EJECUTABLES:
                raise ErrorEjecucion(
                    f"la unidad {nombre} está en estado {estado or 'vacío'}; "
                    "solo en_obra/en_revision se ejecutan"
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
        text=True, capture_output=True, check=False,
    )
    if diferencia.returncode or estado.returncode:
        detalle = (diferencia.stderr.decode("utf-8", "replace") + estado.stderr).strip()
        raise ErrorEjecucion(f"no puedo acreditar el estado Git del worktree: {detalle}")
    return {
        "head": head,
        "diff_sha256": hashlib.sha256(diferencia.stdout).hexdigest(),
        "status_porcelain": estado.stdout.splitlines(),
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
    esta unidad no le recorta ni le añade nada."""
    return [hallazgos]


@contextlib.contextmanager
def _ficha_solo_lectura(ruta):
    """Fuerza `ruta` a modo lectura mientras dura el bloque y restaura su modo previo al
    salir (incluso si el harness revienta). Es la única frontera de escritura real posible
    para R3: sin sandbox de SO (unidad 012) y con `--add-dir` concediendo el directorio
    entero, un permiso de fichero real es lo único que produce una denegación auténtica
    del sistema operativo cuando el harness intenta escribir la ficha."""
    modo_previo = stat.S_IMODE(ruta.stat().st_mode)
    ruta.chmod(0o444)
    try:
        yield
    finally:
        ruta.chmod(modo_previo)


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


def _lanzar_bajo_lease(args, ficha, manager, autoridades):
    worktree, gitdir, common = resolver_worktree(args.unidad)
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
    recibo = {
        "schema": "ejecucion/v1",
        "id": id_ejecucion,
        "unidad": args.unidad,
        "harness": args.harness,
        "rol": args.rol,
        "cwd": str(worktree),
        "rama": args.unidad,
        "lease": {
            "session_id": manager.session_id,
            "fencing": {
                scope: token
                for autoridad in autoridades
                for scope, token in autoridad.tokens.items()
            },
        },
        "git": {"inicial": evidencia_git(worktree), "final": None},
        "skills_tecnicas": list(args.skill_tecnica),
        "checkpoints": [],
        "exit_code": None,
    }
    checkpoint(
        recibo,
        "lease",
        "ok",
        ", ".join(f"{scope}#{token}" for scope, token in recibo["lease"]["fencing"].items()),
    )
    checkpoint(recibo, "identidad", "ok", f"{worktree} · rama {args.unidad}")
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
            modelo=getattr(args, "modelo", None),
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
                    args, ficha_actual, manager, autoridades
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
                   help="modelo explícito para el harness claude (regla 10: el revisor "
                        "usa un modelo DISTINTO del que construyó)")
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
