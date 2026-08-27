#!/usr/bin/env python3
"""Prepara un workspace generado en Windows, macOS o Linux.

Lee ``repos.yaml``, monta o actualiza ``main/``, activa el hook de Git,
recrea las carpetas locales y ejecuta el linter del método. Es idempotente
y no necesita dependencias externas aparte de Python y Git.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Windows: este programa imprime y además CAPTURA la salida de los scripts del método. Las dos
# direcciones tienen que hablar UTF-8 o el arranque muere con un `charmap codec` que parece un
# FAIL del método y no lo es: aquí se fuerza la escritura, y en `ejecutar` la lectura.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent
SCRIPTS_METODO = RAIZ / "docs/00-metodo/scripts"
if str(SCRIPTS_METODO) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_METODO))
import repo_config


def opciones_git_clone():
    """Opciones para el PROPIO `git clone`: en Windows, `core.longpaths` desde el primer byte.

    Bug 044 (ronda 2): `ajustar_rutas_largas()` configura el repo después de clonarlo,
    pero es el clon el que materializa el árbol profundo dentro de `<workspace>/main/`;
    con un `node_modules` corriente muere con «Filename too long» antes de que el ajuste
    exista. `-c core.longpaths=true` se lo aplica al clon mismo. Fuera de Windows, nada.
    """
    if sys.platform != "win32":
        return []
    return ["-c", "core.longpaths=true"]


def ejecutar(*comando, cwd=RAIZ):
    # stdin va CERRADO y git tiene prohibido preguntar por terminal: un remoto que pide
    # credenciales o un host SSH sin verificar se convertía aquí en una espera muda con el
    # stdout capturado — el agente (o el usuario) veía "nada" durante minutos (ADR-026).
    # Con esto, ese caso falla en segundos y con el mensaje de git delante.
    entorno = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    entorno.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    return subprocess.run(
        [str(parte) for parte in comando],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=entorno,
    )


def morir(mensaje):
    raise SystemExit(f"ERROR: {mensaje}")


def valor_config(texto, clave):
    patron = re.compile(rf"^\s*{re.escape(clave)}:\s*(.*?)\s*$")
    for linea in texto.splitlines():
        coincidencia = patron.match(linea)
        if coincidencia:
            valor = coincidencia.group(1).strip().strip("\"'")
            if valor.startswith("PENDIENTE"):
                return ""
            return valor.split("  #", 1)[0].strip()
    return ""


def es_repo_git(ruta):
    if not ruta.exists():
        return False
    resultado = ejecutar("git", "-C", ruta, "rev-parse", "--is-inside-work-tree")
    return resultado.returncode == 0


def actualizar_meta_repo(raiz, imprimir=print):
    """Unidad 119 — el meta-repo también se pone al día al arrancar, no solo `main/`.

    Devuelve `al_dia` · `actualizado` · `no_tocado` · `sin_remoto`. Solo fast-forward, y
    solo con el árbol limpio: si hay cambios sin commitear o la rama divergió, no se toca
    nada, se imprime cómo resolverlo (SALIDA) y el arranque SIGUE — un meta-repo atrasado
    se avisa, no bloquea (el que sí bloquea es `main/`, que es de donde sale el código).
    """
    raiz = Path(raiz)
    if not es_repo_git(raiz):
        imprimir("[3b/5] meta-repo: no es un repo git, nada que traer.")
        return "sin_remoto"
    remoto = ejecutar("git", "-C", raiz, "remote", "get-url", "origin", cwd=raiz)
    if remoto.returncode:
        imprimir("[3b/5] meta-repo: sin remoto, no hay nada que traer.")
        return "sin_remoto"
    rama = ejecutar("git", "-C", raiz, "rev-parse", "--abbrev-ref", "HEAD", cwd=raiz)
    rama = rama.stdout.strip() if rama.returncode == 0 else ""
    if not rama or rama == "HEAD":
        imprimir("[3b/5] meta-repo: sin rama (HEAD suelto), no lo toco.")
        return "no_tocado"
    sucio = ejecutar("git", "-C", raiz, "status", "--porcelain", "--untracked-files=no", cwd=raiz)
    if sucio.returncode == 0 and sucio.stdout.strip():
        imprimir(
            f"[3b/5] meta-repo: no lo toco, hay cambios sin commitear que un pull pisaría. "
            f"SALIDA: commitea (o descarta) y repite `git -C {raiz} pull --ff-only origin {rama}`."
        )
        return "no_tocado"
    traido = ejecutar("git", "-C", raiz, "fetch", "origin", rama, cwd=raiz)
    if traido.returncode:
        imprimir(
            f"[3b/5] meta-repo: no pude consultar origin ({traido.stdout.strip().splitlines()[-1] if traido.stdout.strip() else 'sin detalle'}); sigo con lo local."
        )
        return "no_tocado"
    antes = ejecutar("git", "-C", raiz, "rev-parse", "--short", "HEAD", cwd=raiz).stdout.strip()
    pull = ejecutar("git", "-C", raiz, "merge", "--ff-only", "FETCH_HEAD", cwd=raiz)
    if pull.returncode:
        imprimir(
            f"[3b/5] meta-repo: no lo toco, la rama {rama} divergió de origin y no es "
            f"fast-forward. SALIDA: en {raiz}, `git pull --rebase origin {rama}`, resuelve "
            f"y vuelve a arrancar."
        )
        return "no_tocado"
    despues = ejecutar("git", "-C", raiz, "rev-parse", "--short", "HEAD", cwd=raiz).stdout.strip()
    if antes == despues:
        imprimir(f"[3b/5] meta-repo: al día ({despues}).")
        return "al_dia"
    imprimir(f"[3b/5] meta-repo: actualizado {antes} → {despues} (fast-forward desde origin/{rama}).")
    return "actualizado"


def main():
    print("\n=== Preparando el workspace ===\n")
    if shutil.which("git") is None:
        morir(
            "Git no está instalado. Instálalo desde https://git-scm.com "
            "y vuelve a ejecutar este programa."
        )

    version = ejecutar("git", "--version")
    if version.returncode:
        morir(version.stdout.strip())
    print(f"[1/5] {version.stdout.strip()}")

    repos = RAIZ / "repos.yaml"
    if not repos.is_file():
        morir("no encuentro repos.yaml junto a setup.py")
    configuracion = repos.read_text(encoding="utf-8")
    remoto = valor_config(configuracion, "remoto")
    ruta_local = valor_config(configuracion, "ruta_local")
    # La rama principal la dice repos.yaml, igual que en unidad.py y lint_metodo.py: un repo
    # adoptado puede llamarla `master` y dar por hecho `main` rompe el clon y cada pull.
    if not ruta_local:
        morir("repos.yaml no declara ruta_local")
    try:
        codigo, rama = repo_config.repo_code(RAIZ, require_file=True)
    except repo_config.RepoConfigError as exc:
        morir(str(exc))
    print(f"[2/5] repo de código: {remoto or '(solo local)'} -> {codigo}")

    if es_repo_git(codigo):
        if remoto:
            print(f"[3/5] {ruta_local} ya existe: actualización desde origin/{rama}.")
            actualizado = ejecutar(
                "git", "-C", codigo, "fetch", "origin", rama
            )
            if actualizado.returncode == 0:
                cambio = ejecutar(
                    "git", "-C", codigo, "switch", rama
                )
                if cambio.returncode:
                    cambio = ejecutar(
                        "git", "-C", codigo, "switch", "-c", rama,
                        "--track", f"origin/{rama}"
                    )
                if cambio.returncode == 0:
                    actualizado = ejecutar(
                        "git", "-C", codigo, "pull", "--ff-only", "origin", rama
                    )
                else:
                    actualizado = cambio
            if actualizado.returncode:
                morir(
                    f"no pude actualizar {ruta_local}:\n{actualizado.stdout.strip()}"
                )
        else:
            print(f"[3/5] {ruta_local} ya existe y no tiene remoto pendiente: se conserva.")
    elif codigo.exists():
        morir(f"{codigo} existe, pero no es un repositorio Git")
    elif remoto:
        print(f"[3/5] clonando el repo de código en {ruta_local}…")
        clonado = ejecutar("git", *opciones_git_clone(), "clone", "--branch", rama, remoto, codigo)
        if clonado.returncode:
            morir(f"no pude clonar {remoto}:\n{clonado.stdout.strip()}")
    else:
        morir(
            f"falta {ruta_local} y repos.yaml todavía no contiene el remoto del código"
        )

    # Unidad 119: el meta-repo también (ESTADO.md, fichas, peticiones), en cuanto `main/`
    # está en su sitio. Nunca bloquea: avisa y sigue.
    actualizar_meta_repo(RAIZ)

    hook = (RAIZ / ".githooks").resolve()
    configurado = ejecutar(
        "git", "-C", codigo, "config", "core.hooksPath", hook
    )
    if configurado.returncode:
        morir(f"no pude activar el hook de Git:\n{configurado.stdout.strip()}")

    if sys.platform == "win32":
        # El método añade `worktrees/<NNN-slug>/` (unos 80 caracteres) sobre la ruta que
        # tendría el repo suelto. Con un `node_modules` corriente eso basta para pasar de
        # los 260 de MAX_PATH y que `git worktree add` muera con «Filename too long»,
        # dejando el worktree a medias. Config LOCAL de estos dos repos: no toca el git
        # global del usuario ni su sistema.
        for repo in (RAIZ, codigo):
            ejecutar("git", "-C", repo, "config", "core.longpaths", "true")

    for nombre in ("worktrees", ".private", ".runtime"):
        (RAIZ / nombre).mkdir(exist_ok=True)
    print("[4/5] carpetas locales y hook de Git preparados.")

    linter = RAIZ / "docs" / "00-metodo" / "scripts" / "lint_metodo.py"
    comprobacion = ejecutar(sys.executable, linter)
    print("\n" + comprobacion.stdout.rstrip())
    if comprobacion.returncode:
        # Un FAIL del linter NO corta el arranque (ADR-026): cortar aquí dejaba al usuario
        # atrapado también cuando el rojo era un bug del propio método, que él tiene
        # prohibido arreglar en su workspace. El rojo se enseña, con su salida escrita.
        print(
            "\nOJO: el linter del método está en ROJO. El arranque sigue; el rojo no se "
            "ignora, se despacha:\n"
            "  - ¿El fallo es de tu proyecto (una ficha, una rama, el estado)? Arréglalo "
            "antes de seguir.\n"
            "  - ¿Viene del método (no has tocado docs/00-metodo/)? Regístralo y sigue "
            "trabajando:\n"
            "      python3 docs/00-metodo/scripts/caja_negra.py registrar --repo . "
            "--fase arranque --severidad P1 \\\n"
            "        --sintoma \"<pega aquí el FAIL>\" --esperado \"linter en verde\" "
            "--actual \"<pega aquí el FAIL>\"\n"
            "    El arreglo llega con la próxima versión del método (Modo D)."
        )

    ultimo = ejecutar("git", "-C", codigo, "log", "--oneline", "-1")
    if ultimo.returncode:
        morir(f"no pude leer el último commit:\n{ultimo.stdout.strip()}")
    print(f"\n[5/5] último commit del código: {ultimo.stdout.strip()}")

    # Qué hay de verdad en esta máquina. INFORMA, no bloquea (ADR-009): una máquina sin
    # Docker no es inválida, es una máquina que irá por el peldaño mínimo. Lo que sí evita
    # es que la fase 4 prometa herramientas que aquí no existen.
    doctor = RAIZ / "docs" / "00-metodo" / "scripts" / "doctor.py"
    if doctor.is_file():
        revision = ejecutar(sys.executable, doctor, "--escribir")
        print(revision.stdout.rstrip())

    print("\n=== Workspace listo ===")
    print(
        "Los secretos de .private/ no viajan por Git; cópialos por un canal seguro."
    )


if __name__ == "__main__":
    main()
