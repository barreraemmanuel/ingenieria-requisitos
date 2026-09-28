#!/usr/bin/env python3
"""Primitivas stdlib de rutas: confinar dentro del workspace y localizar herramientas."""

import os
import shutil
import stat
from pathlib import Path


class WorkspacePathError(ValueError):
    pass


# IO_REPARSE_TAG_MOUNT_POINT: la etiqueta de un *junction* de Windows.
TAG_JUNCTION = 0xA0000003


def es_enlace(path):
    """True para un symlink y TAMBIÉN para un junction de Windows.

    `os.path.islink()` responde, por contrato de la stdlib, «¿es un enlace
    SIMBÓLICO?», y un junction no lo es: devuelve False. Pero redirige igual —
    `resolve()` sale fuera— y, a diferencia del symlink, **se crea sin ningún
    privilegio** (`mklink /J`). En Windows es por tanto la vía barata para
    esquivar cualquier guarda que solo mire `is_symlink()`.

    Lo único que lo delata es el reparse tag del `lstat`.
    """
    try:
        estado = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(estado.st_mode):
        return True
    return getattr(estado, "st_reparse_tag", 0) == TAG_JUNCTION


def which_sin_cwd(programa, *, excluir_carpetas=()):
    """`shutil.which` pero SIN el directorio actual, que en Windows se antepone al
    PATH: si no, un `bash.exe` versionado en el repo de código (que suele ser el cwd)
    ganaría al de Git for Windows y se ejecutaría fuera de todo control."""
    rutas = os.environ.get("PATH", os.defpath).split(os.pathsep)
    cwd = Path.cwd().resolve()
    for ruta in rutas:
        if not ruta or Path(ruta).resolve() == cwd:
            continue
        # Un nombre con directorio impide que which anteponga cwd en Windows.
        base = str(Path(ruta).resolve() / programa)
        for nombre in ((base + ".exe", base) if os.name == "nt" else (base,)):
            encontrado = shutil.which(nombre)
            if encontrado and Path(encontrado).parent.name.lower() not in excluir_carpetas:
                return encontrado
    return None


def buscar_bash():
    """Ruta a un `bash` utilizable, o None.

    En Windows, System32/bash.exe y el alias de WindowsApps lanzan WSL y no
    entienden las rutas del host. Se busca Git Bash en PATH o junto a Git/cmd/git.exe.
    """
    excluidas = {"system32", "sysnative", "syswow64", "windowsapps"} if os.name == "nt" else ()
    encontrado = which_sin_cwd("bash", excluir_carpetas=excluidas)
    if encontrado:
        return encontrado
    git = which_sin_cwd("git")
    if not git or os.name != "nt":
        return None
    # …\Git\cmd\git.exe  ->  …\Git\bin\bash.exe  |  …\Git\usr\bin\bash.exe
    raiz = Path(git).resolve().parent.parent
    for candidato in (raiz / "bin" / "bash.exe", raiz / "usr" / "bin" / "bash.exe"):
        if candidato.is_file():
            return str(candidato)
    return None


def confined_path(root, candidate, *, label="ruta"):
    canonical_root = Path(root).resolve()
    lexical = Path(candidate)
    if not lexical.is_absolute():
        lexical = canonical_root / lexical
    try:
        relative = lexical.relative_to(canonical_root)
    except ValueError as exc:
        raise WorkspacePathError(f"{label} queda fuera del workspace") from exc
    if ".." in relative.parts:
        raise WorkspacePathError(f"{label} contiene '..'")
    cursor = canonical_root
    for part in relative.parts:
        cursor = cursor / part
        if es_enlace(cursor):
            raise WorkspacePathError(f"{label} no admite enlaces ({part})")
    resolved = lexical.resolve()
    try:
        resolved.relative_to(canonical_root)
    except ValueError as exc:
        raise WorkspacePathError(f"{label} escapa del workspace") from exc
    return resolved


def regular_file(root, candidate, *, label="fichero"):
    path = confined_path(root, candidate, label=label)
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise WorkspacePathError(f"{label} no es un fichero regular legible: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise WorkspacePathError(f"{label} no es un fichero regular")
    return path
