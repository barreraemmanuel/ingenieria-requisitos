#!/usr/bin/env python3
"""Primitivas stdlib de rutas: confinar dentro del workspace y localizar herramientas."""

import os
import shutil
import stat
from pathlib import Path


class WorkspacePathError(ValueError):
    pass


def which_sin_cwd(programa):
    """`shutil.which` pero SIN el directorio actual, que en Windows se antepone al
    PATH: si no, un `bash.exe` versionado en el repo de código (que suele ser el cwd)
    ganaría al de Git for Windows y se ejecutaría fuera de todo control."""
    rutas = os.environ.get("PATH", os.defpath).split(os.pathsep)
    cwd = os.path.abspath(os.getcwd())
    limpias = [r for r in rutas if r and os.path.abspath(r) != cwd]
    return shutil.which(programa, path=os.pathsep.join(limpias))


def buscar_bash():
    """Ruta a un `bash` utilizable, o None.

    En Windows el PATH lleva `Git\\cmd` (que solo tiene git.exe), no `Git\\bin`, así que
    `which("bash")` da None aunque Git for Windows SIEMPRE traiga bash. Con eso, el hook
    de preparación del worktree no corría nunca y el doctor avisaba de una falta que no
    existía. Se busca primero en el PATH y, si no está, junto al git que sí se encontró
    — misma instalación, misma confianza; no se inventa ninguna ruta absoluta.
    """
    encontrado = which_sin_cwd("bash")
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
        if cursor.is_symlink():
            raise WorkspacePathError(f"{label} no admite symlink ({part})")
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
