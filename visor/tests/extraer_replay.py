#!/usr/bin/env python3
"""Saca de los rollouts reales de esta máquina las llamadas que un guardián de rutas vería.

Un guardián que decide sobre rutas no se puede diseñar contra ejemplos inventados: los
rodeos que importan son los que un agente ya escribió alguna vez. Aquí está el corpus:

  · Claude Code — `~/.claude/projects/<slug>/*.jsonl` y `<sesión>/subagents/*.jsonl`.
    Una línea por registro; los `message.content[].tool_use` de Bash/Edit/Write/MultiEdit/
    NotebookEdit son lo que se ejecutó, y cada registro trae su `cwd`.
  · Codex CLI — `~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl`. Los `custom_tool_call`
    con `name: exec` llevan el comando EN CLARO dentro de un `tools.exec_command({cmd: …})`;
    los `spawn_agent` van cifrados y no son replayables (lector de referencia:
    `canario.leer_codex`).

**Anonimiza en el origen, no después.** 573 de los ~11.000 comandos Bash llevan un correo
(la skill de buzones, `gam`), y los heredocs se conservan enteros porque el guardián los
necesita: por eso el corpus COMPLETO no puede vivir en el repo público. De ahí los dos modos:

    python3 visor/tests/extraer_replay.py --privado     # todo → .runtime/replay/comandos.jsonl
    python3 visor/tests/extraer_replay.py --publico      # solo los ids ya adjudicados → stdout

Formato de salida, una línea por llamada:
    {"id", "ts", "sesion", "sub", "tool", "cwd", "raiz", "entrada", "harness"}

`entrada` es el comando (Bash / exec de Codex) o la ruta del fichero (Edit/Write/…), que es
justo lo que recibe `guardian_rutas.decidir`.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

HERRAMIENTAS = ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit")
CAMPO_DE_RUTA = ("file_path", "notebook_path", "path")

# --- anonimización -------------------------------------------------------------------
# El orden importa: el scratchpad va antes que la ruta de usuario porque la contiene.
CORREO = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}")
SCRATCH = re.compile(r"/private/tmp/claude-\d+/[\w.-]+/[0-9a-f-]+/scratchpad")
# Sustituto ABSOLUTO a propósito: un marcador relativo (`<scratch>`) se resolvería contra el
# `cwd` del registro y fabricaría rechazos que nunca ocurrieron — 14 en la primera medición.
SCRATCH_ANONIMO = "/tmp/agente/scratchpad"
CASA = re.compile(r"/Users/[A-Za-z0-9._-]+")
CASA_LINUX = re.compile(r"/home/[A-Za-z0-9._-]+")
USUARIO_ANONIMO = "/Users/agente"
# Los sustitutos NO llevan `<`/`>` ni `@`: en un comando, `<x>` son dos redirecciones y
# convierten el resto de la ruta en un destino de escritura inventado (20 rechazos falsos
# en la primera medición). El marcador tiene que poder pasar por el tokenizador sin ruido.
CORREO_ANONIMO = "correo-oculto"
NOMBRE_ANONIMO = "agente"


def _nombres_a_tapar():
    """Los nombres propios que no pueden viajar al repo público.

    No van escritos aquí —este fichero ES el repo público—: salen del nombre de la carpeta
    del usuario de esta máquina, y `REPLAY_NOMBRES` (lista por comas) añade los que haga
    falta. Sin esto, el nombre del dueño se cuela en la fixture por los mensajes de commit
    («Merge 071-… (local, sin push: orden de <nombre>)»), que el resto de la anonimización
    no toca.
    """
    nombres = {Path(os.path.expanduser("~")).name}
    nombres.update(n.strip() for n in os.environ.get("REPLAY_NOMBRES", "").split(","))
    return sorted({n for n in nombres if len(n) >= 3})


NOMBRES = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n) for n in _nombres_a_tapar()),
                     re.I) if _nombres_a_tapar() else None


def anonimizar(texto):
    """Quita del texto lo que identifica a la persona: correos, casa y scratchpad."""
    if not isinstance(texto, str):
        return texto
    texto = CORREO.sub(CORREO_ANONIMO, texto)
    texto = SCRATCH.sub(SCRATCH_ANONIMO, texto)
    texto = CASA.sub(USUARIO_ANONIMO, texto)
    texto = CASA_LINUX.sub(USUARIO_ANONIMO, texto)
    if NOMBRES is not None:
        texto = NOMBRES.sub(NOMBRE_ANONIMO, texto)
    return texto


# --- dónde está el taller ------------------------------------------------------------
def raiz_taller():
    """La raíz del meta-repo (la que tiene `main/` y `worktrees/`), anonimizada.

    El extractor vive en el repo de CÓDIGO, que se trabaja desde `worktrees/NNN-slug/`:
    subiendo por los padres se encuentra el taller. Si no lo encuentra (clon suelto),
    devuelve la raíz del propio repo: mejor una raíz que ninguna.
    """
    aqui = Path(__file__).resolve()
    for padre in aqui.parents:
        if (padre / "main").is_dir() and (padre / "worktrees").is_dir():
            return anonimizar(str(padre))
    return anonimizar(str(aqui.parents[2]))


def raiz_taller_real():
    """Lo mismo, pero SIN anonimizar: es la que se usa para localizar los rollouts."""
    aqui = Path(__file__).resolve()
    for padre in aqui.parents:
        if (padre / "main").is_dir() and (padre / "worktrees").is_dir():
            return padre
    return aqui.parents[2]


def ruta_corpus():
    """Dónde vive el corpus completo. Fuera de git, siempre (`.runtime/`)."""
    fijada = os.environ.get("REPLAY_CORPUS")
    if fijada:
        return Path(fijada)
    return raiz_taller_real() / ".runtime" / "replay" / "comandos.jsonl"


def slug_de_proyecto(raiz):
    """El nombre con el que Claude Code guarda los rollouts de un directorio."""
    return str(raiz).replace("/", "-").replace("_", "-")


def _id(sesion, ts, orden):
    crudo = f"{sesion}|{ts}|{orden}".encode("utf-8")
    return hashlib.sha1(crudo).hexdigest()[:12]


# --- Claude Code ---------------------------------------------------------------------
def ficheros_claude(raiz):
    base = Path(os.path.expanduser("~/.claude/projects")) / slug_de_proyecto(raiz)
    if not base.is_dir():
        return []
    ficheros = sorted(glob.glob(str(base / "*.jsonl")))
    ficheros += sorted(glob.glob(str(base / "*" / "subagents" / "*.jsonl")))
    return [Path(f) for f in ficheros]


def _entrada_de(nombre, datos):
    if nombre == "Bash":
        return datos.get("command")
    for campo in CAMPO_DE_RUTA:
        if datos.get(campo):
            return datos[campo]
    return None


def leer_claude(fichero, raiz_anon):
    """Una llamada por `tool_use` de las herramientas que escriben o ejecutan."""
    sub = "subagents" in str(fichero)
    orden = 0
    try:
        crudo = fichero.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with crudo:
        for linea in crudo:
            linea = linea.strip()
            if not linea or '"tool_use"' not in linea:
                continue
            try:
                dato = json.loads(linea)
            except ValueError:
                continue
            mensaje = dato.get("message")
            if not isinstance(mensaje, dict):
                continue
            contenido = mensaje.get("content")
            if not isinstance(contenido, list):
                continue
            for bloque in contenido:
                if not isinstance(bloque, dict) or bloque.get("type") != "tool_use":
                    continue
                nombre = bloque.get("name")
                if nombre not in HERRAMIENTAS:
                    continue
                datos = bloque.get("input")
                if not isinstance(datos, dict):
                    continue
                entrada = _entrada_de(nombre, datos)
                if not entrada:
                    continue
                sesion = (dato.get("sessionId") or fichero.stem)[:8]
                ts = dato.get("timestamp") or ""
                orden += 1
                yield {
                    "id": _id(sesion, ts, orden),
                    "ts": ts,
                    "sesion": sesion,
                    "sub": sub,
                    "harness": "claude",
                    "tool": nombre,
                    "cwd": anonimizar(dato.get("cwd") or str(raiz_anon)),
                    "raiz": raiz_anon,
                    "entrada": anonimizar(str(entrada)),
                }


# --- Codex CLI -----------------------------------------------------------------------
CMD_DE_EXEC = re.compile(r'cmd\s*:\s*"((?:[^"\\]|\\.)*)"')
WORKDIR_DE_EXEC = re.compile(r'"workdir"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _descomillar(texto):
    try:
        return json.loads('"' + texto + '"')
    except ValueError:
        return texto


def leer_codex(fichero, raiz_real, raiz_anon):
    """Los `exec` en claro de un rollout de Codex cuyo `cwd` sea este taller."""
    sesion, cwd_sesion, es_de_aqui = fichero.stem[-8:], str(raiz_real), False
    orden = 0
    try:
        crudo = fichero.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with crudo:
        for linea in crudo:
            if not linea.strip():
                continue
            try:
                dato = json.loads(linea)
            except ValueError:
                continue
            payload = dato.get("payload")
            if not isinstance(payload, dict):
                continue
            if dato.get("type") == "session_meta":
                cwd_sesion = payload.get("cwd") or cwd_sesion
                sesion = (payload.get("session_id") or sesion)[:8]
                es_de_aqui = str(raiz_real) in str(cwd_sesion)
                if not es_de_aqui:
                    return
                continue
            if not es_de_aqui or payload.get("type") not in (
                    "custom_tool_call", "function_call"):
                continue
            args = payload.get("arguments") or payload.get("input") or ""
            if not isinstance(args, str):
                continue
            destinos = WORKDIR_DE_EXEC.findall(args)
            for indice, comando in enumerate(CMD_DE_EXEC.findall(args)):
                orden += 1
                cwd = destinos[indice] if indice < len(destinos) else cwd_sesion
                yield {
                    "id": _id(sesion, dato.get("timestamp") or "", orden),
                    "ts": dato.get("timestamp") or "",
                    "sesion": sesion,
                    "sub": False,
                    "harness": "codex",
                    "tool": "Bash",
                    "cwd": anonimizar(cwd),
                    "raiz": raiz_anon,
                    "entrada": anonimizar(_descomillar(comando)),
                }


# --- extracción ----------------------------------------------------------------------
def extraer(con_codex=True):
    raiz_real = raiz_taller_real()
    raiz_anon = raiz_taller()
    for fichero in ficheros_claude(raiz_real):
        for registro in leer_claude(fichero, raiz_anon):
            yield registro
    if not con_codex:
        return
    base = Path(os.path.expanduser("~/.codex/sessions"))
    if not base.is_dir():
        return
    for ruta in sorted(glob.glob(str(base / "*" / "*" / "*" / "rollout-*.jsonl"))):
        for registro in leer_codex(Path(ruta), raiz_real, raiz_anon):
            yield registro


def ids_adjudicados(fixture):
    ids = set()
    if not Path(fixture).exists():
        return ids
    for linea in Path(fixture).read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            caso = json.loads(linea)
        except ValueError:
            continue
        if caso.get("origen") and caso["origen"] != "sintetico":
            ids.add(caso["origen"])
    return ids


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--privado", action="store_true",
                       help="todo el corpus a .runtime/replay/comandos.jsonl")
    grupo.add_argument("--publico", action="store_true",
                       help="solo las llamadas ya adjudicadas en la fixture pública")
    parser.add_argument("--ids", default=str(Path(__file__).parent / "fixtures" /
                                             "reforma" / "comandos-adjudicados.jsonl"),
                        help="fixture de la que se leen los ids adjudicados (--publico)")
    parser.add_argument("--salida", help="fichero de salida (por defecto: stdout o el corpus)")
    parser.add_argument("--sin-codex", action="store_true", help="solo rollouts de Claude")
    args = parser.parse_args(argv)

    arranque = time.time()
    filtro = ids_adjudicados(args.ids) if args.publico else None
    destino = Path(args.salida) if args.salida else (
        ruta_corpus() if args.privado else None)
    if destino is not None:
        destino.parent.mkdir(parents=True, exist_ok=True)

    cuenta, escritas = {}, 0
    lineas = []
    for registro in extraer(con_codex=not args.sin_codex):
        cuenta[registro["tool"]] = cuenta.get(registro["tool"], 0) + 1
        cuenta[registro["harness"]] = cuenta.get(registro["harness"], 0) + 1
        if filtro is not None and registro["id"] not in filtro:
            continue
        lineas.append(json.dumps(registro, ensure_ascii=False))
        escritas += 1
    texto = "\n".join(lineas) + ("\n" if lineas else "")
    if destino is not None:
        destino.write_text(texto, encoding="utf-8")
    else:
        sys.stdout.write(texto)

    resumen = " · ".join(f"{k} {v}" for k, v in sorted(cuenta.items()))
    print(f"OK {escritas} llamadas escritas en "
          f"{destino if destino is not None else 'stdout'} "
          f"({time.time() - arranque:.1f}s) — {resumen}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
