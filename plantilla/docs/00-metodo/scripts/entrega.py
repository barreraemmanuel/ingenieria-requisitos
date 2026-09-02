#!/usr/bin/env python3
"""Acredita la entrega de un constructor a partir del estado real de git."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[3]
EJECUCIONES = RAIZ / ".runtime/ejecuciones"
WORKTREES = RAIZ / "worktrees"
SALIDA = "SALIDA:"
EXENTOS = {"expres", "exprés", "directo", "documental"}
RE_CASILLA = re.compile(r"^\s*-\s*\[([ xX])\]", re.M)


class ErrorEntrega(RuntimeError):
    pass


def _git(worktree, *args, env=None):
    proceso = subprocess.run(
        ["git", *args], cwd=str(worktree), env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proceso.returncode:
        raise ErrorEntrega(
            f"git {' '.join(args)} falló en {worktree}: "
            f"{(proceso.stdout + proceso.stderr).strip()}"
        )
    return proceso.stdout.strip()


def _arbol_completo(worktree):
    """Hash del árbol visible sin modificar el índice ni el worktree del constructor."""
    descriptor, indice = tempfile.mkstemp(prefix="entrega-index-")
    os.close(descriptor)
    os.unlink(indice)  # read-tree exige un índice inexistente o válido, no un fichero vacío
    entorno = dict(os.environ)
    entorno["GIT_INDEX_FILE"] = indice
    try:
        _git(worktree, "read-tree", "HEAD", env=entorno)
        _git(worktree, "add", "-A", env=entorno)
        return _git(worktree, "write-tree", env=entorno)
    finally:
        try:
            os.unlink(indice)
        except FileNotFoundError:
            pass


def hechos_git(worktree):
    worktree = Path(worktree)
    estado = _git(worktree, "status", "--porcelain").splitlines()
    head = _git(worktree, "rev-parse", "HEAD")
    return {
        "head": head,
        "tree": _arbol_completo(worktree),
        "status_porcelain": estado,
    }


def materializar_commit(worktree, unidad, ronda):
    """Crea un commit inmutable del árbol visible sin mover HEAD ni tocar el índice."""
    hechos = hechos_git(worktree)
    if not hechos["status_porcelain"]:
        hechos.update({"ref": None, "materializada": False})
        return hechos
    mensaje = f"entrega sintética {unidad} ronda {ronda}"
    commit = _git(
        worktree, "commit-tree", hechos["tree"], "-p", hechos["head"], "-m", mensaje
    )
    ref = f"refs/entregas/{unidad}/{ronda}-{uuid.uuid4().hex[:12]}"
    _git(worktree, "update-ref", ref, commit)
    hechos.update({"head": commit, "ref": ref, "materializada": True})
    return hechos


def plan_en(ruta):
    try:
        texto = Path(ruta).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"marcadas": 0, "totales": 0}
    marcas = RE_CASILLA.findall(texto)
    return {
        "marcadas": sum(1 for marca in marcas if marca.lower() == "x"),
        "totales": len(marcas),
    }


def ficha_y_plan(raiz, unidad):
    raiz = Path(raiz)
    carpeta = raiz / "docs/05-trabajo" / unidad
    ficha = carpeta / "especificacion.md"
    plan = carpeta / "hallazgos.md"
    if not ficha.is_file():
        ficha = raiz / "docs/bugs" / f"{unidad}.md"
        plan = ficha
    return ficha, plan_en(plan)


def recibos_de(unidad, ejecuciones=None):
    carpeta = Path(ejecuciones or EJECUCIONES)
    recibos = []
    if not carpeta.is_dir():
        return recibos
    for ruta in sorted(carpeta.glob(f"{unidad}-*.json"), key=lambda p: p.stat().st_mtime_ns):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            recibos.append({"_corrupto": str(ruta)})
            continue
        datos["_ruta"] = str(ruta)
        recibos.append(datos)
    return recibos


def ficheros_declarados(ficha):
    """La lista `ficheros:` de la ficha, sin el prefijo `nuevo:` de los que aún no existen."""
    try:
        texto = Path(ficha).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    encontrado = re.search(r"(?ms)^ficheros:\s*\[(.*?)\]", texto)
    if not encontrado:
        return []
    declarados = []
    for pieza in encontrado.group(1).split(","):
        pieza = pieza.strip().strip("'\"")
        pieza = re.sub(r"^(nuevo|nueva|new)\s*:\s*", "", pieza)
        if pieza:
            declarados.append(pieza)
    return declarados


def ficheros_del_diff(repo, desde, hasta):
    """Los ficheros que cambiaron entre dos commits. Sin ellos no hay aviso, nunca bloqueo."""
    if not (desde and hasta) or desde == hasta:
        return []
    try:
        salida = _git(repo, "diff", "--name-only", desde, hasta)
    except (ErrorEntrega, OSError):
        return []
    return [linea.strip() for linea in salida.splitlines() if linea.strip()]


def aviso_diff_fuera_de_ficheros(repo, unidad, declarados, desde, hasta):
    """R3: «diff fuera de `ficheros:`» es AVISO, no bloqueo.

    32 de los 92 incidentes de guardianes eran marcar de más, así que esto informa y sigue:
    lo que decida endurecerlo será el replay, no esta puerta.
    """
    if not declarados:
        return []
    fuera = sorted(f for f in ficheros_del_diff(repo, desde, hasta) if f not in declarados)
    if not fuera:
        return []
    muestra = ", ".join(fuera[:8])
    resto = "" if len(fuera) <= 8 else f" (+{len(fuera) - 8} más)"
    return [
        f"la entrega de {unidad} toca {len(fuera)} fichero(s) fuera de `ficheros:` de la "
        f"ficha: {muestra}{resto}. Es un aviso, no un bloqueo: decláralos en hallazgos.md "
        f"para que el padre los apruebe, o añádelos a `ficheros:` al reabrir el contrato"
    ]


def _problema(texto, comando="git status --porcelain"):
    return f"{texto}. {SALIDA} {comando}"


def validar_entrega(worktree, unidad, recibos, base):
    """Puerta pura usada por los fixtures y por los consumidores reales."""
    base = dict(base or {})
    carril = str(base.get("carril") or "normal").strip().lower()
    espera_cambios = bool(base.get("espera_cambios", carril not in EXENTOS))
    if carril in EXENTOS or not espera_cambios:
        return [], []

    candidatos = [
        r for r in recibos
        if isinstance(r, dict) and r.get("schema") == "ejecucion/v1"
        and r.get("unidad") == unidad and r.get("rol") == "constructor"
    ]
    if not candidatos:
        if not recibos:
            return [_problema(
                f"la entrega del ayudante de {unidad} está ausente",
                f"python3 docs/00-metodo/scripts/ejecucion.py lanzar {unidad} "
                "--harness claude --rol constructor --prompt \"termina la entrega\"",
            )], []
        return [_problema(f"ningún recibo legible acredita al constructor de {unidad}")], []

    propios = [r for r in candidatos if r.get("harness") == "subagente-del-padre"]
    recibo = (propios or candidatos)[-1]
    resultado = recibo.get("resultado")
    if resultado != "ok":
        return [_problema(
            f"la entrega del ayudante de {unidad} terminó en {resultado or 'abierto'}"
        )], []

    final = (recibo.get("git") or {}).get("final") or {}
    repo = Path(worktree) if Path(worktree).is_dir() else Path(worktree).parent.parent / "main"
    try:
        if Path(worktree).is_dir():
            actual = hechos_git(worktree)
        else:
            # Un cierre reanudado puede llegar después de que el worktree se retirase. La
            # evidencia sigue en el commit inmutable y en main; ausencia no se convierte en
            # exención: sin `final.head` válido este camino también bloquea.
            head_final = str(final.get("head") or "")
            tree_final = _git(repo, "rev-parse", f"{head_final}^{{tree}}")
            actual = {"head": head_final, "tree": tree_final, "status_porcelain": []}
    except (ErrorEntrega, OSError) as exc:
        return [_problema(f"no se pudo derivar la entrega de {unidad}: {exc}")], []
    sintetica = bool(final.get("materializada"))
    if actual["status_porcelain"] and not (
        sintetica and final.get("tree") == actual["tree"]
    ):
        return [_problema(
            f"la entrega del ayudante no está: worktree sucio "
            f"({len(actual['status_porcelain'])} fichero(s))"
        )], []
    if sintetica:
        vigente = final.get("tree") == actual["tree"]
    else:
        vigente = final.get("head") == actual["head"]
    if not vigente:
        return [_problema(f"el recibo de {unidad} está obsoleto: git cambió después")], []

    inicial = (recibo.get("git") or {}).get("inicial") or base
    mismo_arbol = (
        bool(final.get("tree"))
        and bool(inicial.get("tree"))
        and final.get("tree") == inicial.get("tree")
    )
    if mismo_arbol or final.get("head") == inicial.get("head"):
        return [_problema(f"{unidad} no contiene cambios desde la base del despacho")], []
    plan_inicial = (base.get("plan") or inicial.get("plan") or {})
    plan_final = ((recibo.get("trabajo") or {}).get("plan") or {})
    if plan_final and int(plan_final.get("marcadas", 0)) <= int(
        plan_inicial.get("marcadas", 0)
    ):
        return [_problema(f"{unidad} no tiene ninguna casilla nueva del plan")], []
    if not plan_final and (recibo.get("trabajo") or {}).get("acreditado") is not True:
        return [_problema(f"{unidad} no acredita progreso del plan")], []
    # La entrega es buena. Lo único que queda es lo que R3 declara AVISO: si el diff se salió
    # de los ficheros que la ficha declaró, se dice y se sigue.
    return [], aviso_diff_fuera_de_ficheros(
        repo, unidad, base.get("ficheros") or [],
        inicial.get("head"), actual.get("head"),
    )


def _frontmatter(ruta):
    try:
        lineas = Path(ruta).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    if not lineas or lineas[0].strip() != "---":
        return {}
    datos = {}
    for linea in lineas[1:]:
        if linea.strip() == "---":
            break
        pareja = re.match(r"^(\w+):\s*([^#]*)", linea)
        if pareja:
            datos[pareja.group(1)] = pareja.group(2).strip()
    return datos


def exigir_entrega_constructor(unidad, encargo=None):
    """Deriva y exige la entrega real de una unidad del workspace."""
    ficha, _ = ficha_y_plan(RAIZ, unidad)
    fm = _frontmatter(ficha)
    carril = str((encargo or {}).get("carril") if isinstance(encargo, dict) else "")
    carril = carril or fm.get("carril") or "normal"
    ejecucion = str((encargo or {}).get("ejecucion") if isinstance(encargo, dict) else "")
    ejecucion = ejecucion or fm.get("ejecucion") or ""
    espera = carril.lower() not in EXENTOS and ejecucion.lower() != "documental"
    recibos = recibos_de(unidad)
    constructores = [r for r in recibos if r.get("rol") == "constructor"]
    inicial = ((constructores[-1].get("git") or {}).get("inicial")
               if constructores else {}) or {}
    base = {
        **inicial,
        "unidad": unidad,
        "carril": "documental" if ejecucion.lower() == "documental" else carril,
        "espera_cambios": espera,
        "plan": inicial.get("plan") or {},
        "ficheros": ficheros_declarados(ficha),
    }
    return validar_entrega(WORKTREES / unidad, unidad, recibos, base)
