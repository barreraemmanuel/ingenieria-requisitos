#!/usr/bin/env python3
"""Recibos de delegación nativa: preparar → vincular resultado de herramienta → finalizar.

Este programa nunca inicia una IA. El padre usa Agent/SendMessage (Claude) o
collaboration (Codex). Preparar no demuestra ejecución; un resultado síncrono también
puede vincularse al regresar. La evidencia registra su fuente, no ofrece autenticación
criptográfica ni permisos de sistema operativo que la herramienta no expone.
"""
import argparse
import contextlib
import datetime
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import entrega
import ejecucion
import lease as gestion_leases
import repo_config

RAIZ = Path(__file__).resolve().parents[3]
EJECUCIONES = RAIZ / ".runtime/ejecuciones"
LEASES = RAIZ / ".runtime/leases/active"
HARNESS = "subagente-del-padre"
ROLES = ("constructor", "revisor", "investigador", "auditor", "validador")
TERMINALES = {"ok": "terminado", "fallo": "fallido", "cancelado": "cancelado", "parado": "cancelado"}


def ahora():
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def pid_abuelo():
    try:
        padre = int(subprocess.run(["ps", "-o", "ppid=", "-p", str(os.getppid())],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip() or 0)
    except (ValueError, OSError):
        padre = 0
    return padre or os.getppid()


def guardar_recibo(fichero, datos):
    fichero = Path(fichero)
    temporal = fichero.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporal.chmod(0o600)
    os.replace(str(temporal), str(fichero))


def checkpoint(datos, nombre, detalle):
    datos.setdefault("checkpoints", []).append({"nombre": nombre, "detalle": detalle, "cuando": ahora()})


def error(texto):
    raise ValueError(texto + ". SALIDA: consulta `subagente.py estado UNIDAD` y usa el recibo exacto; "
                     "si falta capacidad nativa, continúa en una sesión compatible, sin IA externa")


def plataforma_sesion(explicita=None):
    return repo_config.plataforma_sesion(explicita)


def exacto(args):
    if not ejecucion.RE_NOMBRE.fullmatch(args.unidad):
        error("unidad inválida")
    if not re.fullmatch(r"[a-f0-9]{32}", args.recibo_id):
        error("recibo-id inválido")
    path = EJECUCIONES / f"{args.unidad}-{args.recibo_id}.json"
    datos = json.loads(path.read_text(encoding="utf-8"))
    if (datos.get("unidad"), datos.get("id"), datos.get("rol")) != (args.unidad, args.recibo_id, args.rol):
        error("unidad, recibo o rol no coinciden")
    if datos.get("protocolo") != "nativo/v1":
        error("recibo histórico: consúltalo con estado; prepara una tarea nativa nueva")
    return path, datos


def autoridad(datos):
    manager = gestion_leases.LeaseManager(RAIZ, session_id=datos["lease"]["session_id"])
    group = gestion_leases.LeaseGroup(manager, datos["lease"]["records"])
    group.assert_owner()
    return group


def documentos_snapshot(carpeta, informe):
    if carpeta.name == "bugs":
        return {}  # otros bugs pertenecen a tareas independientes
    return {str(p.relative_to(carpeta)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(carpeta.rglob("*")) if p.is_file() and p != informe}


def huella_contrato(ficha):
    texto = Path(ficha).read_text(encoding="utf-8")
    if Path(ficha).parent.name == "bugs":
        # La ficha del bug incluye SU informe; la sección de cierre es la única mutable
        # por el revisor. El contrato anterior y las demás fichas siguen independientes.
        texto = re.split(r"(?m)^## 6[^\n]*Cierre", texto, maxsplit=1)[0]
        texto = re.sub(r"(?m)^(revisor|revisado|revisado_patch_id|ronda|correccion):.*(?:\n|$)", "", texto)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def huella_texto(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def proteger_bloques_del_informe(texto):
    """Los ejemplos de Markdown son evidencia, no secciones ni firmas editables."""
    salida, bloque, marca, aprendizaje = [], [], "", False
    for linea in texto.splitlines(keepends=True):
        if marca:
            bloque.append(linea)
            if re.fullmatch(r"[ ]{0,3}" + re.escape(marca[0]) + "{" + str(len(marca)) + r",}[ \t]*\n?", linea):
                if not aprendizaje:
                    salida.append(re.match(r"[ \t]*", bloque[0])[0] + "bloque:" + huella_texto("".join(bloque)) + "\n")
                bloque, marca = [], ""
            continue
        inicio = re.match(r"[ ]{0,3}(`{3,}|~{3,})([^\n]*)\n?$", linea)
        if inicio:
            marca, aprendizaje = inicio[1], inicio[2].strip() == "aprendizajes-revisor"
            bloque = [linea]
        else:
            salida.append(linea)
    if bloque:  # Una valla sin cerrar nunca concede permiso sobre el resto del informe.
        salida.append(re.match(r"[ \t]*", bloque[0])[0] + "bloque:" + huella_texto("".join(bloque)) + "\n")
    return "".join(salida)


def partes_informe_revisor(texto):
    """Separa permisos de escritura; conserva hashes, nunca copia el informe al recibo."""
    texto = proteger_bloques_del_informe(texto)
    firmas = {}
    cabecera = re.match(r"\A---\n(.*?)^---(?:\n|\Z)", texto, re.M | re.S)
    if cabecera:
        def firma(match):
            firmas[match[1]] = match[2].split("#", 1)[0].strip()
            return ""
        limpia = re.sub(r"(?m)^(revisor|revisado):([^\n]*)\n", firma, cabecera[1])
        texto = texto[:cabecera.start(1)] + limpia + texto[cabecera.end(1):]
    revision = []
    def extraer(match):
        revision.append(match[0].strip())
        return ""
    texto = re.sub(r"(?ms)^## Revisión[^\n]*\n.*?(?=^## |\Z)", extraer, texto)
    # En bugs el informe vive en una viñeta de Cierre, junto a evidencia del padre.
    texto = re.sub(r"(?m)^- \*\*Revisión[^\n]*(?:\n[ \t]+[^\n]*)*\n?", extraer, texto)
    trabajo = re.search(r"(?ms)(^## Trabajo descubierto[^\n]*\n)(.*?)(?=^## |\Z)", texto)
    lineas = trabajo[2].splitlines(keepends=True) if trabajo else []
    if trabajo:
        texto = texto[:trabajo.start(2)] + texto[trabajo.end(2):]
    return {"protegido": huella_texto(texto.strip()),
            "revision": huella_texto("\n".join(revision)), "firma": firmas,
            "trabajo": [huella_texto(linea) for linea in lineas]}, "\n".join(revision), lineas


def validar_informe_revisor(datos, informe):
    anterior = datos.get("informe_revisor_inicial")
    if anterior is None:
        error("preparación sin fronteras del informe; prepara una revisión nueva con este protocolo")
    actual, revision, lineas = partes_informe_revisor(informe.read_text(encoding="utf-8"))
    if actual["protegido"] != anterior["protegido"]:
        error("revisor modificó Plan, evidencia u otra parte protegida del informe")
    diferencias = difflib.SequenceMatcher(a=anterior["trabajo"], b=actual["trabajo"], autojunk=False)
    for op, _, _, inicio, fin in diferencias.get_opcodes():
        if op == "equal":
            continue
        nuevas = lineas[inicio:fin]
        marcada = False
        for linea in nuevas:
            if not linea.strip():
                continue
            if re.match(r"^- \[revisor\](?:\s|$)", linea):
                marcada = True
            elif not (marcada and linea.startswith(("  ", "\t"))):
                error("Trabajo descubierto solo admite añadidos nuevos [revisor]")
        if op != "insert" or not marcada:
            error("el revisor no puede borrar ni reescribir hallazgos previos")
    firma = actual["firma"]
    if (firma == anterior["firma"] or
            firma.get("revisor", "").split(" · ", 1)[0] != datos["native_task_id"]):
        error("falta firma nueva del native_task_id de esta revisión")
    try:
        fecha = datetime.date.fromisoformat(firma.get("revisado", ""))
        inicio = datetime.date.fromisoformat(datos["checkpoints"][0]["cuando"][:10])
        if not inicio <= fecha <= datetime.datetime.now(datetime.timezone.utc).date():
            raise ValueError()
    except ValueError:
        error("firma de revisión sin fecha válida de esta ejecución")
    if not revision or actual["revision"] == anterior["revision"]:
        error("falta revisión nueva: el veredicto anterior no pertenece a esta ejecución")
    veredicto = ejecucion.veredicto_ultimo(revision)
    if veredicto not in ("LIMPIO", "HUECOS DE CORRECCIÓN"):
        error("falta veredicto LIMPIO o HUECOS DE CORRECCIÓN en la revisión nueva")
    return actual, veredicto


def cmd_preparar(args):
    with contextlib.ExitStack() as cleanup:
        resultado = _preparar(args, cleanup)
        cleanup.pop_all()
        return resultado


def _preparar(args, cleanup):
    if not ejecucion.RE_NOMBRE.fullmatch(args.unidad):
        error("unidad inválida: se esperaba NNN-slug")
    plataforma = plataforma_sesion(args.plataforma)
    # Las funciones de evidencia se reutilizan con la raíz del workspace actual.
    ejecucion.RAIZ = RAIZ
    ficha, fm = ejecucion.ficha_unidad(args.unidad, rol=args.rol)
    worktree = RAIZ / "worktrees" / args.unidad
    efimero = False
    documental = fm.get("ejecucion") == "documental" or fm.get("documental") in (True, "true", "sí", "si")
    if not worktree.is_dir():
        if documental:
            worktree = RAIZ / "main"
        elif args.rol == "revisor" and fm.get("estado") in ejecucion.ESTADOS_ENTREGADOS:
            fusion = fm.get("fusion") or ""
            if not re.fullmatch(r"[0-9a-fA-F]{7,40}", fusion):
                error("la revisión entregada sin worktree requiere fusion: con commit válido")
            worktree = RAIZ / ".runtime/revisiones" / (args.unidad + "-" + uuid.uuid4().hex)
            worktree.parent.mkdir(parents=True, exist_ok=True)
            entrega._git(RAIZ / "main", "worktree", "add", "--detach", str(worktree), fusion)
            efimero = True
            cleanup.callback(ejecucion.git, RAIZ / "main", "worktree", "remove", str(worktree))
        else:
            error(f"falta worktree de {args.unidad}; restaura la mesa con unidad.py antes de preparar")
    if not documental and not efimero:
        rama = entrega._git(worktree, "branch", "--show-current")
        if rama != args.unidad:
            error(f"rama {rama} distinta de {args.unidad}; recupera el worktree correcto")
    if worktree.is_symlink() or ficha.is_symlink():
        error("worktree o ficha enlazados fuera de su frontera")
    informe = ficha if ficha.parent.name == "bugs" else ficha.with_name("hallazgos.md")
    if informe.is_symlink():
        error("el informe no puede ser un symlink")
    modelo = args.modelo
    esfuerzo = args.esfuerzo
    if not modelo:
        plan = repo_config.plan_de_modelo(fm.get("carril") or "normal", args.rol,
                                         documental=documental, harness=plataforma)
        modelo, esfuerzo = plan.modelo, esfuerzo or plan.esfuerzo
    if (plataforma == "codex" and modelo.startswith("claude-")) or (plataforma == "claude" and modelo.startswith("gpt-")):
        error("modelo de otra plataforma; selecciona uno de esta sesión")
    inicial = entrega.hechos_git(worktree)
    if args.rol == "revisor" and not documental:
        if inicial["status_porcelain"]:
            error("el contenido a revisar debe estar commiteado por el constructor; worktree sucio")
        problemas, _ = entrega.exigir_entrega_constructor(args.unidad)
        if problemas:
            error("; ".join(problemas))
    _, plan = entrega.ficha_y_plan(RAIZ, args.unidad)
    inicial["plan"] = plan
    base = fm.get("base_sha") or fm.get("base") or ejecucion.base_registrada_de_la_unidad(fm, args.unidad, ficha)
    patch_id, ancla_motivo = ejecucion.patch_id_y_motivo(worktree, base)
    previa, ronda = ejecucion.rondas_del_constructor(informe, args.unidad) if args.rol == "constructor" else (None, ejecucion.ronda_declarada(informe.read_text()) if informe.exists() else None)
    session = str(uuid.uuid4())
    rid = uuid.uuid4().hex
    scope = f"subagente:{args.unidad}"
    manager = gestion_leases.LeaseManager(RAIZ, session_id=session, pid=args.pid or pid_abuelo())
    group = manager.acquire([scope])
    cleanup.callback(group.release)
    datos = {
        "schema": "ejecucion/v1", "protocolo": "nativo/v1", "id": rid, "unidad": args.unidad,
        "harness": HARNESS, "plataforma": plataforma, "rol": args.rol, "estado_nativo": "preparado",
        "modelo": modelo, "modelo_solicitado": modelo, "modelo_observado": None, "modelo_acreditado": None,
        "modelo_origen": "solicitud" if args.modelo else "tabla", "esfuerzo": esfuerzo,
        "native_task_id": None, "native_parent_session_id": None, "cwd": str(worktree),
        "rama": args.unidad, "worktree_efimero": efimero, "documental": documental, "lease": {"session_id": session, "scopes": [scope],
                                          "fencing": group.tokens, "records": group.records},
        "git": {"inicial": inicial}, "trabajo": {"plan": plan}, "exit_code": None,
        "ficha": str(ficha), "contrato_inicial": huella_contrato(ficha),
        "informe": str(informe), "informe_inicial": hashlib.sha256(informe.read_bytes()).hexdigest() if informe.exists() else None,
        "documentos_inicial": documentos_snapshot(ficha.parent, informe),
        "informe_revisor_inicial": partes_informe_revisor(informe.read_text(encoding="utf-8") if informe.exists() else "")[0] if args.rol == "revisor" else None,
        "revisado_patch_id": patch_id if args.rol == "revisor" else None,
        "ancla_motivo": ancla_motivo, "base": base,
        "ronda_previa": previa, "ronda": ronda,
        "senales": ejecucion.senales_para_el_revisor(worktree, args.rol),
        "aislamiento": {"instruccion": "solo lectura; única escritura: informe" if args.rol != "constructor" else "worktree y hallazgos",
                        "so": "no acreditado", "control": "snapshots antes/después"},
        "limites": ["Un modelo solicitado no es observado", "La herramienta no acredita aislamiento de SO"],
        "checkpoints": [],
    }
    checkpoint(datos, "preparado", "Pendiente de herramienta nativa; no acredita ejecución")
    EJECUCIONES.mkdir(parents=True, exist_ok=True)
    try:
        guardar_recibo(EJECUCIONES / f"{args.unidad}-{rid}.json", datos)
    except BaseException:
        group.release()
        raise
    print(json.dumps({"recibo_id": rid, "estado": "preparado", "modelo_solicitado": modelo,
                      "esfuerzo": esfuerzo, "encargo": datos["aislamiento"]["instruccion"], "senales": datos["senales"],
                      "firma_revisor": "revisor: <native_task_id> · <modelo>; revisado: YYYY-MM-DD; escribe Revisión nueva, aprendizajes-revisor y solo añadidos [revisor] sin alterar evidencia previa" if args.rol == "revisor" else None,
                      "siguiente": "Usa Agent o collaboration.spawn_agent; conserva el resultado y vincúlalo con --evidencia"}, ensure_ascii=False))
    return 0


def observar_metadata(evidencia, plataforma):
    """Lee SOLO metadatos del hijo exacto. Nunca busca la última sesión global."""
    ruta = evidencia.get("metadata_path")
    if not ruta:
        return {"modelo": None, "esfuerzo": None, "motivo": "sin fuente de metadata"}
    task, parent = evidencia["native_task_id"], evidencia["parent_session_id"]
    modelo = esfuerzo = session = None
    lineas_modelo = []
    identidad = False
    with Path(ruta).open(encoding="utf-8") as stream:
        for numero, linea in enumerate(stream, 1):
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            if not isinstance(evento, dict):
                continue
            if plataforma == "codex":
                if evento.get("type") == "session_meta":
                    carga = evento.get("payload") or {}
                    spawn = ((carga.get("source") or {}).get("subagent") or {}).get("thread_spawn") or {}
                    identidad = spawn.get("parent_thread_id") == parent and task in (spawn.get("agent_path"), carga.get("id"))
                    if not identidad:
                        error("metadata pertenece a otro hijo o padre; no se lee una sesión ajena")
                    session = carga.get("id")
                elif evento.get("type") == "turn_context" and identidad:
                    carga = evento.get("payload") or {}
                    if carga.get("model"):
                        modelo, esfuerzo = carga["model"], carga.get("effort")
                        lineas_modelo.append(numero)
            elif evento.get("type") == "assistant":
                # Claude identifica los eventos del subagente por agentId y sessionId.
                if evento.get("agentId") != task or evento.get("sessionId") != parent:
                    error("metadata Claude no corresponde al agentId/sessionId del encargo")
                identidad = True
                session = evento["sessionId"]
                if (evento.get("message") or {}).get("model"):
                    modelo, esfuerzo = evento["message"]["model"], evento.get("effort")
                    lineas_modelo.append(numero)
    if not identidad:
        error("fuente sin identidad del hijo nativo")
    return {"modelo": modelo, "esfuerzo": esfuerzo, "session_id": session,
            "ruta": str(Path(ruta).resolve()), "lineas_modelo": lineas_modelo,
            "fuente": "session_meta/turn_context" if plataforma == "codex" else "assistant.agentId/sessionId/message.model"}


def cmd_vincular(args):
    path, datos = exacto(args)
    task = args.native_task_id.strip()
    if not task or task == datos["lease"]["session_id"]:
        error("el ID nativo real debe ser distinto del ID de cerrojo")
    raw = Path(args.evidencia).read_bytes()
    evidencia = json.loads(raw)
    if not isinstance(evidencia, dict):
        error("el resultado nativo debe ser un objeto JSON")
    tool = evidencia.get("tool")
    admitidas = ("collaboration.spawn_agent", "collaboration.followup_task") if datos["plataforma"] == "codex" else ("Agent",)
    if tool not in admitidas or evidencia.get("native_task_id") != task or not evidencia.get("parent_session_id"):
        error("la evidencia debe conservar tool, native_task_id y parent_session_id del resultado nativo")
    if task == evidencia["parent_session_id"]:
        error("el hijo no puede tener la identidad de su padre")
    if datos["estado_nativo"] != "preparado":
        if datos.get("native_task_id") == task and datos.get("evidencia_nativa", {}).get("sha256") == hashlib.sha256(raw).hexdigest():
            return 0
        error("este recibo ya está vinculado a otro resultado; prepara otro para reanudar")
    autoridad(datos)
    metadata = observar_metadata(evidencia, datos["plataforma"])
    if datos["rol"] == "revisor":
        if evidencia.get("contexto") != "fresco" or tool == "collaboration.followup_task":
            error("la revisión exige un agente nuevo con contexto fresco")
        for previo in entrega.recibos_de(args.unidad, EJECUCIONES):
            if previo.get("id") == datos["id"]:
                continue
            if task == previo.get("native_task_id"):
                error("el revisor debe ser una identidad nueva, nunca reutilizada")
            if previo.get("rol") == "constructor" and metadata.get("modelo") and metadata.get("modelo") == previo.get("modelo_observado", previo.get("modelo")):
                error("revisor y constructor deben usar modelos distintos")
    almacen = EJECUCIONES / "evidencias"
    almacen.mkdir(exist_ok=True)
    copia = almacen / f"{datos['id']}.json"
    copia.write_bytes(raw)
    copia.chmod(0o600)
    datos.update({"native_task_id": task, "native_parent_session_id": evidencia["parent_session_id"],
                  "estado_nativo": "vinculado", "contexto": evidencia.get("contexto"),
                  "modelo_observado": metadata.get("modelo"),
                  "modelo_acreditado": metadata.get("modelo") or None,
                  "metadata_observada": metadata,
                  "evidencia_nativa": {"ruta": str(copia), "sha256": hashlib.sha256(raw).hexdigest(),
                                        "fuente": tool, "tipo": "resultado-herramienta", "autenticacion": "no criptográfica"}})
    if not datos["modelo_acreditado"]:
        datos["limites"].append("Capacidad insuficiente: el resultado nativo no acredita modelo efectivo")
    checkpoint(datos, "vinculado", f"{tool}: {task}")
    guardar_recibo(path, datos)
    print(f"vinculado {datos['id']} a {task}")
    return 0


def cmd_finalizar(args):
    path, datos = exacto(args)
    if datos.get("native_task_id") != args.native_task_id or not datos.get("native_task_id"):
        error("el vínculo nativo no coincide con el recibo exacto")
    problema = entrega.validar_vinculo_nativo(datos, exigir_terminado=False)
    if problema:
        error(problema)
    if datos.get("resultado"):
        if datos["resultado"] == args.resultado:
            return 0
        error("finalización ya registrada: no puede cambiarse")
    group = autoridad(datos)
    if args.resultado != "ok" and not args.motivo.strip():
        error("cancelación o fallo exige --motivo")
    payload = json.loads(Path(datos["evidencia_nativa"]["ruta"]).read_bytes())
    if args.resultado == "ok":
        metadata = observar_metadata(payload, datos["plataforma"])
        datos.update(modelo_observado=metadata.get("modelo"), modelo_acreditado=metadata.get("modelo"),
                     metadata_observada=metadata)
    worktree = Path(datos["cwd"])
    informe = Path(datos["informe"])
    try:
        final = entrega.hechos_git(worktree)
    except (OSError, entrega.ErrorEntrega):
        if args.resultado == "ok":
            raise
        final = {}
        datos["limites"].append("Snapshot final no disponible; el intento fallido no acredita trabajo ni ausencia de cambios")
    inicial = datos["git"]["inicial"]
    if args.resultado == "ok":
        if datos["rol"] == "constructor" and not datos.get("documental"):
            _, plan = entrega.ficha_y_plan(RAIZ, args.unidad)
            if plan["marcadas"] <= inicial["plan"]["marcadas"]:
                error("ninguna casilla nueva del plan: registra el trabajo realmente terminado")
            if final["tree"] == inicial["tree"]:
                error("mismo árbol inicial: no hay trabajo de código acreditable")
            final = entrega.materializar_commit(worktree, args.unidad, datos.get("ronda") or 1)
            datos["trabajo"] = {"plan": plan, "acreditado": True}
            if not final.get("materializada"):
                datos["entregado_patch_id"] = ejecucion.patch_id_de_la_rama(worktree, datos.get("base"))
        else:
            if final != {k: v for k, v in inicial.items() if k != "plan"}:
                error("código modificado durante tarea de solo lectura; repite con contenido estable")
            if huella_contrato(datos["ficha"]) != datos["contrato_inicial"]:
                error("contrato modificado durante revisión")
            if documentos_snapshot(informe.parent, informe) != datos["documentos_inicial"]:
                error("documentos del encargo modificados durante lectura")
            if not informe.exists() or hashlib.sha256(informe.read_bytes()).hexdigest() == datos["informe_inicial"]:
                error("falta informe nuevo de la tarea")
            if datos["rol"] == "revisor":
                patch_id, _ = ejecucion.patch_id_y_motivo(worktree, datos.get("base"))
                if patch_id != datos["revisado_patch_id"]:
                    error("contenido revisado cambió")
                datos["informe_revisor_final"], datos["veredicto"] = validar_informe_revisor(datos, informe)
                ejecucion.sellar_patch_id(informe, patch_id)
    datos["git"]["final"] = final
    if datos["rol"] == "constructor" and final:
        vacia = final["tree"] == inicial["tree"]
        datos["ronda_vacia"] = vacia
        if vacia:
            datos["ronda"] = datos.get("ronda_previa")
        elif datos.get("ronda"):
            ejecucion.sellar_clave(informe, "ronda", str(datos["ronda"]))
    datos.update({"resultado": args.resultado, "estado_nativo": TERMINALES[args.resultado],
                  "exit_code": 0 if args.resultado == "ok" else 1, "motivo": args.motivo})
    checkpoint(datos, "terminado", args.resultado)
    group.assert_owner()
    guardar_recibo(path, datos)
    group.release()
    if datos.get("worktree_efimero"):
        # Sin --force: el código modificado se conserva como evidencia del fallo.
        codigo, salida = ejecucion.git(RAIZ / "main", "worktree", "remove", str(worktree))
        if codigo:
            print(f"AVISO worktree de revisión conservado: {salida}. SALIDA: git -C main worktree list")
    print(f"finalizado {datos['id']}: {args.resultado}")
    return 0


def cmd_cancelar(args):
    path, datos = exacto(args)
    if datos.get("estado_nativo") == "cancelado" and not datos.get("native_task_id"):
        return 0
    if datos.get("estado_nativo") != "preparado":
        error("cancelar sin vínculo solo sirve para preparado; interrumpe el hijo y usa finalizar --resultado cancelado")
    if not args.motivo.strip():
        error("cancelar exige --motivo")
    group = autoridad(datos)
    datos.update({"estado_nativo": "cancelado", "resultado": "cancelado", "motivo": args.motivo,
                  "exit_code": None, "sin_ejecucion": True, "ronda": datos.get("ronda_previa")})
    checkpoint(datos, "cancelado", args.motivo)
    guardar_recibo(path, datos)
    group.release()
    if datos.get("worktree_efimero"):
        ejecucion.git(RAIZ / "main", "worktree", "remove", datos["cwd"])
    return 0


def cmd_recuperar(args):
    """Declara intento perdido del padre muerto; no afirma haber detenido al hijo."""
    path, datos = exacto(args)
    if datos.get("resultado"):
        error("el recibo ya tiene resultado")
    manager = gestion_leases.LeaseManager(RAIZ)
    records = datos["lease"]["records"]
    if any(manager._owner_alive(r["owner"]) is not False for r in records):
        error("el padre sigue vivo o no se puede comprobar; interrumpe mediante su herramienta nativa")
    if not args.motivo.strip():
        error("recuperar exige --motivo y comprobar el estado del hijo en la sesión nativa")
    datos.update({"resultado": "fallo", "estado_nativo": "fallido", "exit_code": None,
                  "motivo": args.motivo, "recuperacion": "padre muerto; no acredita parada del hijo",
                  "ronda": datos.get("ronda_previa")})
    checkpoint(datos, "recuperado", args.motivo)
    guardar_recibo(path, datos)
    manager._release_records(records)  # fenced: jamás retira el registro de otro dueño
    return 0


def cmd_estado(args):
    for recibo in entrega.recibos_de(args.unidad, EJECUCIONES):
        print(json.dumps(recibo, ensure_ascii=False))
    return 0


def cmd_acreditar_git(args):
    """Anota trabajo previo desde Git sin inventar una tarea nativa pasada."""
    if not ejecucion.RE_NOMBRE.fullmatch(args.unidad):
        error("unidad inválida")
    ejecucion.RAIZ = RAIZ
    ficha, fm = ejecucion.ficha_unidad(args.unidad, rol="constructor")
    worktree = RAIZ / "worktrees" / args.unidad
    if not worktree.is_dir() or worktree.is_symlink():
        error("falta el worktree de la unidad")
    if entrega._git(worktree, "branch", "--show-current") != args.unidad:
        error("la rama del worktree no coincide con la unidad")
    registrada = fm.get("base_sha") or fm.get("base") or ejecucion.base_registrada_de_la_unidad(fm, args.unidad, ficha)
    if registrada and args.base != registrada:
        error("la base indicada difiere de la base registrada en el contrato o despacho")
    hechos = entrega.hechos_recuperacion(worktree, args.base, args.commit)
    actual = entrega.hechos_git(worktree)
    if actual["head"] != args.commit or actual["tree"] != hechos["tree"]:
        error("el commit recuperado debe ser la punta y el árbol vigentes")
    informe = ficha if ficha.parent.name == "bugs" else ficha.with_name("hallazgos.md")
    if informe.is_symlink():
        error("informe enlazado fuera de su frontera")
    _, plan = entrega.ficha_y_plan(RAIZ, args.unidad)
    if plan["marcadas"] == 0:
        error("el plan no acredita ningún paso realizado")
    previos = [r for r in entrega.recibos_de(args.unidad, EJECUCIONES)
               if r.get("schema") == "entrega-git/v1"]
    if previos and previos[-1].get("recuperacion") == hechos:
        print(f"acreditación Git ya registrada: {previos[-1]['id']}")
        return 0
    previa, ronda = ejecucion.rondas_del_constructor(informe, args.unidad)
    if ronda is None:
        ronda = 1
    rid = uuid.uuid4().hex
    datos = {"schema": "entrega-git/v1", "protocolo": "git-recuperacion/v1",
             "id": rid, "unidad": args.unidad, "rol": "constructor",
             "origen": "hechos-git; autoría Git no identifica a un agente histórico",
             "resultado": "ok", "exit_code": 0, "cuando": ahora(),
             "ronda": ronda, "recuperacion": hechos,
             "git": {"inicial": {"head": args.base, "tree": entrega._git(worktree, "rev-parse", f"{args.base}^{{tree}}")},
                     "final": {"head": args.commit, "tree": hechos["tree"]}},
             "trabajo": {"plan": plan, "acreditado": True}}
    EJECUCIONES.mkdir(parents=True, exist_ok=True)
    guardar_recibo(EJECUCIONES / f"{args.unidad}-{rid}.json", datos)
    ejecucion.sellar_clave(informe, "ronda", str(ronda))
    print(f"acreditado {args.unidad}: {args.base[:12]}..{args.commit[:12]}, árbol {hechos['tree'][:12]}; recibo {rid}; revisión fresca requerida")
    return 0


def migracion(args):
    print(f"Comando retirado. SALIDA: python3 docs/00-metodo/scripts/subagente.py preparar {args.unidad} "
          "--rol constructor --plataforma codex (o claude, la plataforma de ESTA sesión); "
          "después usa su herramienta nativa, vincular y finalizar con --recibo-id y --native-task-id. "
          "Los recibos históricos se consultan con estado; ninguna IA externa se inicia.")
    return 2


cmd_abrir = migracion
cmd_cerrar = migracion


def main(argv=None):
    global RAIZ, EJECUCIONES, LEASES
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--workspace", type=Path, help="workspace explícito para migrar desde una copia de la herramienta")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("preparar", help="prepara encargo; NO inicia un agente")
    a.add_argument("unidad")
    a.add_argument("--rol", choices=ROLES, required=True)
    a.add_argument("--plataforma", choices=("codex", "claude"))
    a.add_argument("--modelo")
    a.add_argument("--esfuerzo")
    a.add_argument("--pid", type=int, default=0)
    a.set_defaults(fn=cmd_preparar)
    for nombre, funcion in (("vincular", cmd_vincular), ("finalizar", cmd_finalizar)):
        a = sub.add_parser(nombre)
        a.add_argument("unidad")
        a.add_argument("--recibo-id", required=True)
        a.add_argument("--rol", choices=ROLES, required=True)
        a.add_argument("--native-task-id", required=True)
        if nombre == "vincular":
            a.add_argument("--evidencia", required=True, help="JSON del resultado de la herramienta nativa; ver runbooks/control-plane.md")
        else:
            a.add_argument("--resultado", choices=tuple(TERMINALES), default="ok")
            a.add_argument("--motivo", default="")
        a.set_defaults(fn=funcion)
    a = sub.add_parser("cancelar", help="cancela preparación que nunca ejecutó un hijo")
    a.add_argument("unidad")
    a.add_argument("--recibo-id", required=True)
    a.add_argument("--rol", choices=ROLES, required=True)
    a.add_argument("--motivo", required=True)
    a.set_defaults(fn=cmd_cancelar)
    a = sub.add_parser("recuperar", help="registra fallo de padre muerto; no mata ni acredita parada del hijo")
    a.add_argument("unidad")
    a.add_argument("--recibo-id", required=True)
    a.add_argument("--rol", choices=ROLES, required=True)
    a.add_argument("--motivo", required=True)
    a.set_defaults(fn=cmd_recuperar)
    a = sub.add_parser("estado", help="consulta recibos nativos e históricos")
    a.add_argument("unidad")
    a.set_defaults(fn=cmd_estado)
    a = sub.add_parser("acreditar-git", help="recupera trabajo previo mediante commits Git verificables")
    a.add_argument("unidad")
    a.add_argument("--base", required=True, help="SHA completo de la base registrada")
    a.add_argument("--commit", required=True, help="SHA completo de la punta entregada")
    a.set_defaults(fn=cmd_acreditar_git)
    for nombre in ("abrir", "cerrar"):
        a = sub.add_parser(nombre, help="retirado: muestra migración, nunca ejecuta IA")
        a.add_argument("unidad")
        for flag in ("modelo", "rol", "esfuerzo", "pid", "resultado", "motivo"):
            a.add_argument("--" + flag)
        a.set_defaults(fn=migracion)
    args = p.parse_args(argv)
    if args.workspace:
        RAIZ = args.workspace.resolve()
        EJECUCIONES = RAIZ / ".runtime/ejecuciones"
        LEASES = RAIZ / ".runtime/leases/active"
        for modulo in (ejecucion, entrega):
            modulo.RAIZ = RAIZ
            modulo.WORKTREES = RAIZ / "worktrees"
            modulo.EJECUCIONES = EJECUCIONES
    try:
        if args.cmd in ("vincular", "finalizar", "cancelar", "recuperar"):
            if not re.fullmatch(r"[a-f0-9]{32}", args.recibo_id):
                error("recibo-id inválido")
            # Serializa operaciones sobre EL MISMO recibo antes de leerlo: repetir cierre
            # concurrentemente nunca materializa dos commits ni resella evidencia.
            mutex = gestion_leases.LeaseManager(RAIZ)
            with mutex.acquire([f"native-receipt:{args.recibo_id}"]):
                return args.fn(args)
        return args.fn(args)
    except (ValueError, OSError, entrega.ErrorEntrega, ejecucion.ErrorEjecucion, gestion_leases.LeaseError) as exc:
        print(f"subagente: FAIL {exc}. SALIDA: python3 docs/00-metodo/scripts/subagente.py estado {args.unidad}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
