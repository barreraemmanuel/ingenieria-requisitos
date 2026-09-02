#!/usr/bin/env python3
"""Recibo de un SUBAGENTE DEL PADRE, para que el tablero lo vea trabajar (P-20260827-f7c22906).

Desde la 1.8.2 (ADR-033) el constructor de normal/completo es un subagente del propio padre
(Agent tool), no un proceso lanzado por `ejecucion.py`, así que no dejaba recibo en
`.runtime/ejecuciones/` ni cerrojo en `.runtime/leases/active/` y la sección «Ahora» del
tablero solo enseñaba revisores. Este script escribe los dos ficheros con el MISMO formato
que lee `visor_tablero/estado.py` (`agentes()`): recibo `ejecucion/v1` sin `resultado` +
cerrojo con el PID del padre. Mientras el padre viva y no lo cierre, el subagente cuenta
como vivo; `cerrar` pone el resultado y retira el cerrojo.

    python3 docs/00-metodo/scripts/subagente.py abrir NNN-slug --modelo claude-opus-5 [--rol constructor] [--pid PID]
    python3 docs/00-metodo/scripts/subagente.py cerrar NNN-slug [--resultado ok|parado|fallo]

Sin `--pid` usa el proceso abuelo (el agente que lanzó el shell). Los outputs largos siguen
en `hallazgos.md`: esto es solo la señal de «alguien trabaja aquí, desde cuándo y con qué».
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake (guardián de
# codificación, unidad 049): se reconfigura antes de imprimir nada.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lease as gestion_leases  # el cerrojo lo escribe lease.py: integridad y fencing válidos
import entrega

RAIZ = Path(__file__).resolve().parents[3]
EJECUCIONES = RAIZ / ".runtime" / "ejecuciones"
LEASES = RAIZ / ".runtime" / "leases" / "active"
HARNESS = "subagente-del-padre"


def ahora():
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def pid_abuelo():
    """El agente que lanzó este shell: python ← shell ← agente."""
    try:
        padre = int(subprocess.run(["ps", "-o", "ppid=", "-p", str(os.getppid())],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace").stdout.strip() or 0)
    except (ValueError, OSError):
        padre = 0
    return padre or os.getppid()


def recibo_de(unidad):
    if not EJECUCIONES.is_dir():
        return None
    for fichero in sorted(EJECUCIONES.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if datos.get("harness") == HARNESS and datos.get("unidad") == unidad and "resultado" not in datos:
            return fichero, datos
    return None


def guardar_recibo(fichero, datos):
    """El lector nunca observa medio JSON si el proceso muere al escribir."""
    fichero = Path(fichero)
    temporal = fichero.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporal.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporal.chmod(0o600)
    os.replace(str(temporal), str(fichero))


def cmd_abrir(args):
    if recibo_de(args.unidad):
        print(f"ya hay un recibo abierto de subagente para {args.unidad}; ciérralo antes (subagente.py cerrar)")
        return 1
    worktree = RAIZ / "worktrees" / args.unidad
    session_id = str(uuid.uuid4())
    pid = args.pid or pid_abuelo()
    EJECUCIONES.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex
    try:
        inicial = entrega.hechos_git(worktree)
    except entrega.ErrorEntrega as exc:
        print(f"no pude abrir la entrega de {args.unidad}: {exc}")
        return 1
    _, plan = entrega.ficha_y_plan(RAIZ, args.unidad)
    inicial["plan"] = plan
    recibo = {
        "schema": "ejecucion/v1", "id": rid, "unidad": args.unidad, "harness": HARNESS,
        "rol": args.rol, "modelo": args.modelo, "esfuerzo": args.esfuerzo,
        "modelo_origen": "tabla", "motivo_modelo": "", "worktree_efimero": False,
        "cwd": str(worktree), "rama": args.unidad,
        "lease": {"session_id": session_id, "scopes": [f"subagente:{args.unidad}"]},
        "git": {"inicial": inicial}, "trabajo": {"plan": plan},
        "skills_tecnicas": [],
        "checkpoints": [{"nombre": "lanzado", "detalle": f"subagente del padre · {args.modelo} · esfuerzo {args.esfuerzo}",
                         "cuando": ahora()}],
        "exit_code": None,
    }
    guardar_recibo(EJECUCIONES / f"{args.unidad}-{rid}.json", recibo)
    manager = gestion_leases.LeaseManager(RAIZ, session_id=session_id, pid=pid)
    try:
        manager.acquire([f"subagente:{args.unidad}"])
    except gestion_leases.LeaseError as exc:
        print(f"no pude escribir el cerrojo del subagente: {exc}")
        return 1
    print(f"recibo abierto: {args.unidad} · {args.rol} · {args.modelo} · pid {pid} · {rid[:8]}")
    return 0


def cmd_cerrar(args):
    encontrado = recibo_de(args.unidad)
    if not encontrado:
        print(f"no hay recibo abierto de subagente para {args.unidad}")
        return 1
    fichero, datos = encontrado
    motivo = (getattr(args, "motivo", "") or "").strip()
    if args.resultado != "ok" and not motivo:
        print(
            f"{args.resultado} exige --motivo para que la siguiente ronda sepa por qué. "
            f"SALIDA: python3 docs/00-metodo/scripts/subagente.py cerrar {args.unidad} "
            f"--resultado {args.resultado} --motivo \"qué impidió terminar\""
        )
        return 1
    if args.resultado == "ok":
        try:
            inicial = (datos.get("git") or {}).get("inicial") or {}
            _, plan = entrega.ficha_y_plan(RAIZ, args.unidad)
            if int(plan.get("marcadas", 0)) <= int(
                (inicial.get("plan") or {}).get("marcadas", 0)
            ):
                print(
                    f"la entrega de {args.unidad} no tiene ninguna casilla nueva del plan. "
                    f"SALIDA: marca en docs/05-trabajo/{args.unidad}/hallazgos.md la "
                    "casilla realmente terminada y repite este comando"
                )
                return 1
            final = entrega.materializar_commit(
                RAIZ / "worktrees" / args.unidad,
                args.unidad,
                len(list(EJECUCIONES.glob(f"{args.unidad}-*.json"))),
            )
            if final.get("tree") == inicial.get("tree"):
                print(
                    f"la entrega de {args.unidad} tiene el mismo árbol que al abrirse. "
                    f"SALIDA: git -C worktrees/{args.unidad} status --porcelain"
                )
                return 1
            datos.setdefault("git", {})["final"] = final
            datos["trabajo"] = {"plan": plan, "acreditado": True}
        except entrega.ErrorEntrega as exc:
            print(
                f"no pude derivar la entrega de {args.unidad}: {exc}. "
                f"SALIDA: git -C worktrees/{args.unidad} status --porcelain"
            )
            return 1
    datos["resultado"] = args.resultado
    if motivo:
        datos["motivo"] = motivo
    datos["exit_code"] = 0 if args.resultado == "ok" else 1
    datos.setdefault("checkpoints", []).append(
        {"nombre": "terminado", "detalle": args.resultado, "cuando": ahora()})
    guardar_recibo(fichero, datos)
    # El cerrojo se retira por su ruta canónica (la que lease.py calcula del scope):
    # mismo criterio auditable que el desbloqueo a mano, con el recibo ya cerrado.
    manager = gestion_leases.LeaseManager(RAIZ, session_id=(datos.get("lease") or {}).get("session_id"))
    cerrojo = manager._path(f"subagente:{args.unidad}")
    if cerrojo.exists():
        cerrojo.unlink()
    print(f"recibo cerrado: {args.unidad} · {args.resultado}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("abrir", help="el padre acaba de lanzar un subagente en esta unidad")
    a.add_argument("unidad")
    a.add_argument("--modelo", required=True)
    a.add_argument("--rol", default="constructor", choices=("constructor", "revisor"))
    a.add_argument("--esfuerzo", default="medio")
    a.add_argument("--pid", type=int, default=0, help="PID del agente padre (por defecto, el abuelo de este proceso)")
    a.set_defaults(fn=cmd_abrir)
    c = sub.add_parser("cerrar", help="el subagente devolvió su parte final")
    c.add_argument("unidad")
    c.add_argument("--resultado", default="ok", choices=("ok", "parado", "fallo"))
    c.add_argument("--motivo", default="", help="obligatorio con parado/fallo")
    c.set_defaults(fn=cmd_cerrar)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
