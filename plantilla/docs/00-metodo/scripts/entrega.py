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
        if not isinstance(datos, dict):
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


def _commit_exacto(repo, valor):
    """Resuelve únicamente un SHA completo que designa un objeto commit existente."""
    if not re.fullmatch(r"[0-9a-f]{40}", str(valor or "")):
        raise ErrorEntrega("base y commit requieren SHA completo de 40 caracteres")
    if _git(repo, "cat-file", "-t", valor) != "commit":
        raise ErrorEntrega(f"{valor} no designa un commit")
    return valor


def _ancestro(repo, base, punta):
    proceso = subprocess.run(["git", "merge-base", "--is-ancestor", base, punta],
                             cwd=str(repo), capture_output=True, check=False)
    return proceso.returncode == 0


def hechos_recuperacion(worktree, base, commit, comprobar_rama=True):
    """Reconstruye la evidencia desde Git; jamás confía en campos del recibo."""
    worktree = Path(worktree)
    if Path(_git(worktree, "rev-parse", "--show-toplevel")).resolve() != worktree.resolve():
        raise ErrorEntrega("la ruta no es la raíz del repositorio de código esperado")
    base = _commit_exacto(worktree, base)
    commit = _commit_exacto(worktree, commit)
    if not _ancestro(worktree, base, commit) or base == commit:
        raise ErrorEntrega("commit fuera de base o sin cambios")
    if comprobar_rama:
        actual = hechos_git(worktree)
        if actual["status_porcelain"]:
            raise ErrorEntrega("worktree sucio después del anclaje")
        if not _ancestro(worktree, commit, actual["head"]):
            raise ErrorEntrega("commit fuera de la rama vigente")
    tree = _git(worktree, "rev-parse", f"{commit}^{{tree}}")
    if tree == _git(worktree, "rev-parse", f"{base}^{{tree}}"):
        raise ErrorEntrega("base y commit tienen el mismo árbol")
    diff = subprocess.run(["git", "diff", "--binary", "--full-index", base, commit],
                          cwd=str(worktree), capture_output=True, check=False)
    if diff.returncode or not diff.stdout:
        raise ErrorEntrega("diff de recuperación vacío o ilegible")
    autor = _git(worktree, "show", "-s", "--format=%an%x00%ae%x00%aI", commit).split("\x00")
    return {"base": base, "commit": commit, "tree": tree,
            "diff_sha256": hashlib.sha256(diff.stdout).hexdigest(),
            "autor_git": {"nombre": autor[0], "email": autor[1], "fecha": autor[2]}}


def validar_recuperacion(worktree, unidad, recibo):
    datos = recibo.get("recuperacion") or {}
    worktree = Path(worktree)
    existe_worktree = worktree.is_dir()
    repo = worktree if existe_worktree else worktree.parent.parent / "main"
    try:
        hechos = hechos_recuperacion(repo, datos.get("base"), datos.get("commit"),
                                     comprobar_rama=existe_worktree)
    except (ErrorEntrega, OSError) as exc:
        return [_problema(f"recuperación Git de {unidad} inválida: {exc}")], []
    if recibo.get("unidad") != unidad or any(datos.get(k) != v for k, v in hechos.items()):
        return [_problema(f"recuperación Git de {unidad} no coincide con los hechos actuales")], []
    if existe_worktree:
        actual = hechos_git(repo)
        if actual["head"] != datos["commit"] or actual["tree"] != datos["tree"]:
            return [_problema(f"recuperación Git de {unidad} obsoleta: cambió el contenido")], []
    return [], []


def ancla_entrega_git(repo, unidad, recibo, worktree=None):
    """Base, punta y árbol de la entrega vigente, derivados de objetos Git."""
    if not recibo or recibo.get("unidad") != unidad or recibo.get("resultado") != "ok":
        raise ErrorEntrega("falta una entrega vigente terminada de esta unidad")
    if recibo.get("schema") == "entrega-git/v1":
        problemas, _ = validar_recuperacion(worktree or repo, unidad, recibo)
        if problemas:
            raise ErrorEntrega(problemas[0])
        hechos = recibo["recuperacion"]
        return {k: hechos[k] for k in ("base", "commit", "tree", "diff_sha256")}
    if recibo.get("schema") != "ejecucion/v1":
        raise ErrorEntrega("recibo sin ancla Git verificable")
    if recibo.get("protocolo") == "nativo/v1":
        problema = validar_vinculo_nativo(recibo)
        if problema:
            raise ErrorEntrega(problema)
    inicial = (recibo.get("git") or {}).get("inicial") or {}
    final = (recibo.get("git") or {}).get("final") or {}
    base = _commit_exacto(repo, recibo.get("base") or inicial.get("head"))
    commit = _commit_exacto(repo, final.get("head"))
    if base == commit or not _ancestro(repo, base, commit):
        raise ErrorEntrega("la punta entregada no desciende de su base")
    tree = _git(repo, "rev-parse", f"{commit}^{{tree}}")
    if tree != final.get("tree") or tree == _git(repo, "rev-parse", f"{base}^{{tree}}"):
        raise ErrorEntrega("árbol final no coincide con el commit entregado")
    diff = subprocess.run(["git", "diff", "--binary", "--full-index", base, commit],
                          cwd=str(repo), capture_output=True, check=False)
    if diff.returncode or not diff.stdout:
        raise ErrorEntrega("diff de la entrega vacío o ilegible")
    return {"base": base, "commit": commit, "tree": tree,
            "diff_sha256": hashlib.sha256(diff.stdout).hexdigest()}


def recibo_vigente_constructor(unidad, recibos):
    """Selecciona la última entrega real, nativa o recuperada, conservando el historial."""
    nativos = [r for r in recibos if isinstance(r, dict)
               and r.get("schema") == "ejecucion/v1" and r.get("unidad") == unidad
               and r.get("rol") == "constructor" and r.get("estado_nativo") != "preparado"
               and not r.get("sin_ejecucion")]
    recuperados = [r for r in recibos if isinstance(r, dict)
                   and r.get("schema") == "entrega-git/v1" and r.get("unidad") == unidad
                   and r.get("rol") == "constructor"]
    propios = [r for r in nativos if r.get("harness") == "subagente-del-padre"]
    preferidos = propios + recuperados
    return next((r for r in reversed(recibos) if r in (preferidos or nativos)), None)


def validar_vinculo_nativo(recibo, exigir_terminado=True):
    """Integridad estructural de evidencia nativa; históricos conservan su lector."""
    task = recibo.get("native_task_id")
    if not task or task in ((recibo.get("lease") or {}).get("session_id"), recibo.get("native_parent_session_id")):
        return "identidad nativa ausente o confundida con padre/cerrojo"
    evidencia = recibo.get("evidencia_nativa") or {}
    try:
        raw = Path(evidencia["ruta"]).read_bytes()
        payload = json.loads(raw)
    except (KeyError, OSError, ValueError, TypeError):
        return "falta evidencia nativa legible"
    if hashlib.sha256(raw).hexdigest() != evidencia.get("sha256"):
        return "evidencia nativa modificada"
    if payload.get("native_task_id") != task or payload.get("parent_session_id") != recibo.get("native_parent_session_id"):
        return "vínculo nativo no coincide con su fuente"
    if recibo.get("contexto") != payload.get("contexto"):
        return "contexto no coincide con la herramienta nativa"
    metadata = recibo.get("metadata_observada") or {}
    if recibo.get("modelo_acreditado") and (
        metadata.get("modelo") != recibo.get("modelo_acreditado")
        or metadata.get("modelo") != recibo.get("modelo_observado")
        or not metadata.get("ruta") or not payload.get("metadata_path")
        or Path(metadata["ruta"]).resolve() != Path(payload["metadata_path"]).resolve()
    ):
        return "modelo acreditado no corresponde a su fuente de metadata"
    if exigir_terminado and recibo.get("estado_nativo") != "terminado":
        return "tarea nativa no terminada"
    return None


def validar_entrega(worktree, unidad, recibos, base):
    """Puerta pura usada por los fixtures y por los consumidores reales."""
    base = dict(base or {})
    carril = str(base.get("carril") or "normal").strip().lower()
    espera_cambios = bool(base.get("espera_cambios", carril not in EXENTOS))
    if carril in EXENTOS or not espera_cambios:
        return [], []

    recibo = recibo_vigente_constructor(unidad, recibos)
    if not recibo:
        if not recibos:
            return [_problema(
                f"la entrega del ayudante de {unidad} está ausente",
                f"python3 docs/00-metodo/scripts/subagente.py preparar {unidad} --rol constructor",
            )], []
        return [_problema(f"ningún recibo legible acredita al constructor de {unidad}")], []

    if recibo.get("schema") == "entrega-git/v1":
        if recibo.get("resultado") != "ok":
            return [_problema(f"recuperación Git de {unidad} no terminada")], []
        return validar_recuperacion(worktree, unidad, recibo)
    if recibo.get("protocolo") == "nativo/v1":
        problema = validar_vinculo_nativo(recibo)
        if problema:
            return [_problema(problema)], []
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
    if not vigente and recibo.get("protocolo") == "nativo/v1" and recibo.get("entregado_patch_id"):
        import ejecucion  # función compartida, import diferido para evitar ciclo de módulos
        vigente = ejecucion.patch_id_de_la_rama(repo, recibo.get("base")) == recibo["entregado_patch_id"]
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
    constructores = [r for r in recibos if r.get("rol") == "constructor"
                    and r.get("estado_nativo") != "preparado" and not r.get("sin_ejecucion")]
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
