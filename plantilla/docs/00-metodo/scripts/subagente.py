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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lease as gestion_leases  # el cerrojo lo escribe lease.py: integridad y fencing válidos

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
                                   capture_output=True, text=True).stdout.strip() or 0)
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


def cmd_abrir(args):
    if recibo_de(args.unidad):
        print(f"ya hay un recibo abierto de subagente para {args.unidad}; ciérralo antes (subagente.py cerrar)")
        return 1
    worktree = RAIZ / "worktrees" / args.unidad
    session_id = str(uuid.uuid4())
    pid = args.pid or pid_abuelo()
    EJECUCIONES.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex
    recibo = {
        "schema": "ejecucion/v1", "id": rid, "unidad": args.unidad, "harness": HARNESS,
        "rol": args.rol, "modelo": args.modelo, "esfuerzo": args.esfuerzo,
        "modelo_origen": "tabla", "motivo_modelo": "", "worktree_efimero": False,
        "cwd": str(worktree), "rama": args.unidad,
        "lease": {"session_id": session_id, "scopes": [f"subagente:{args.unidad}"]},
        "git": {}, "skills_tecnicas": [],
        "checkpoints": [{"nombre": "lanzado", "detalle": f"subagente del padre · {args.modelo} · esfuerzo {args.esfuerzo}",
                         "cuando": ahora()}],
        "exit_code": None,
    }
    (EJECUCIONES / f"{args.unidad}-{rid}.json").write_text(
        json.dumps(recibo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    datos["resultado"] = args.resultado
    datos["exit_code"] = 0 if args.resultado == "ok" else 1
    datos.setdefault("checkpoints", []).append(
        {"nombre": "terminado", "detalle": args.resultado, "cuando": ahora()})
    fichero.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    c.set_defaults(fn=cmd_cerrar)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
