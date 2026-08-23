#!/usr/bin/env python3
"""Retira del descubrimiento skills locales de proceso, sin borrarlas.

Por defecto ninguna skill local se considera técnica: se conserva en su sitio únicamente si
se nombra con ``--permitir``. Lo demás se mueve a ``.private/skills-retiradas`` con recibo y
puede restaurarse. Los bootstraps nuevos no crean estas carpetas.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path



# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
RAICES = (".agents/skills", ".claude/skills", ".codex/skills")
DESTINO = ".private/skills-retiradas"
RECIBO = f"{DESTINO}/RECIBO.json"


def morir(mensaje):
    raise SystemExit(f"migrar_skills: {mensaje}")


def huella_arbol(ruta):
    digest = hashlib.sha256()
    for fichero in sorted(item for item in ruta.rglob("*") if item.is_file()):
        digest.update(str(fichero.relative_to(ruta)).encode("utf-8") + b"\0")
        digest.update(fichero.read_bytes() + b"\0")
    return digest.hexdigest()


def inventario(workspace):
    encontrados = []
    for raiz_rel in RAICES:
        raiz = workspace / raiz_rel
        if not raiz.is_dir() or raiz.is_symlink():
            continue
        for skill in sorted(raiz.iterdir()):
            if skill.is_dir() and not skill.is_symlink() and (skill / "SKILL.md").is_file():
                encontrados.append(
                    {
                        "nombre": skill.name,
                        "harness": raiz_rel.split("/")[0].lstrip("."),
                        "origen": str(skill.relative_to(workspace)).replace("\\", "/"),
                        "huella": huella_arbol(skill),
                    }
                )
    return encontrados


def guardar_recibo(workspace, datos):
    destino = workspace / RECIBO
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporal = tempfile.mkstemp(dir=destino.parent, prefix="recibo-skills-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as salida:
            json.dump(datos, salida, ensure_ascii=False, indent=2, sort_keys=True)
            salida.write("\n")
        os.chmod(temporal, 0o600)
        os.replace(temporal, destino)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def revisar(workspace, permitidas):
    skills = inventario(workspace)
    for skill in skills:
        estado = "PERMITIDA TÉCNICA" if skill["nombre"] in permitidas else "RETIRAR"
        print(f"[{estado}] {skill['origen']}")
    if not skills:
        print("No hay skills locales descubribles.")
    return skills


def aplicar(workspace, permitidas):
    skills = revisar(workspace, permitidas)
    retirar = [skill for skill in skills if skill["nombre"] not in permitidas]
    if not retirar:
        print("Nada que retirar.")
        return 0
    movimientos = []
    for skill in retirar:
        origen = workspace / skill["origen"]
        destino_rel = f"{DESTINO}/{skill['harness']}/{skill['nombre']}"
        destino = workspace / destino_rel
        if destino.exists():
            morir(f"el destino de recuperación ya existe: {destino}")
        destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.move(str(origen), str(destino))
        movimientos.append({**skill, "destino": destino_rel})
    guardar_recibo(
        workspace,
        {
            "formato": 1,
            "fecha": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "movimientos": movimientos,
        },
    )
    print(f"Retiradas {len(movimientos)} skill(s); no se borró ninguna. Recibo: {workspace / RECIBO}")
    return 0


def restaurar(workspace):
    recibo = workspace / RECIBO
    try:
        datos = json.loads(recibo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        morir(f"no puedo leer {recibo}: {exc}")
    movimientos = datos.get("movimientos")
    if datos.get("formato") != 1 or not isinstance(movimientos, list):
        morir("recibo incompatible")
    for movimiento in movimientos:
        origen = workspace / movimiento["destino"]
        destino = workspace / movimiento["origen"]
        if destino.exists():
            morir(f"no sobrescribo una skill restaurada o nueva: {destino}")
        if not origen.is_dir() or huella_arbol(origen) != movimiento["huella"]:
            morir(f"la copia retirada cambió o falta: {origen}")
    for movimiento in movimientos:
        origen = workspace / movimiento["destino"]
        destino = workspace / movimiento["origen"]
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origen), str(destino))
    recibo.unlink()
    print(f"Restauradas {len(movimientos)} skill(s) desde el recibo.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="orden", required=True)
    for nombre in ("revisar", "aplicar"):
        comando = sub.add_parser(nombre)
        comando.add_argument("workspace")
        comando.add_argument(
            "--permitir",
            action="append",
            default=[],
            metavar="SKILL_TECNICA",
            help="nombre exacto de una skill técnica que debe seguir descubrible",
        )
    restaurar_parser = sub.add_parser("restaurar")
    restaurar_parser.add_argument("workspace")
    args = parser.parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        morir(f"no existe el workspace: {workspace}")
    if args.orden == "restaurar":
        return restaurar(workspace)
    permitidas = set(args.permitir)
    if args.orden == "revisar":
        revisar(workspace, permitidas)
        return 0
    return aplicar(workspace, permitidas)


if __name__ == "__main__":
    sys.exit(main())
