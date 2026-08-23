#!/usr/bin/env python3
"""Crea al principio el workspace visible donde vivirá toda la entrevista.

Este comando no congela el diseño. Prepara ``<proyecto>-agents`` y ``main/``
antes de analizar o preguntar nada:

* proyecto nuevo: ``main/`` es un repositorio con solo un README;
* remoto existente: ``main/`` es el clon del remoto;
* carpeta existente: se copia literalmente, incluido su estado git, sin tocar
  el original.

Los planos nacen en borrador dentro del propio workspace. A partir de ese
momento esa copia es la fuente de verdad que entrevista, visor y finalización
deben actualizar.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
BASE = Path(__file__).resolve().parent


def morir(mensaje):
    raise SystemExit("iniciar: %s" % mensaje)


def ejecutar(comando, cwd=None):
    return subprocess.run(
        comando,
        cwd=cwd,
        text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def planos_iniciales(nombre, titulo, existente):
    return {
        "version": 2,
        "proyecto": nombre,
        "titulo": titulo,
        "descripcion": "Borrador inicial; todavía no se ha completado la ingeniería de requisitos.",
        "definicion": {
            "estado": "borrador",
            "modo": "analisis de codigo" if existente else "entrevista",
            "bloques_no_aplican": [],
            "supuestos": [],
        },
        "cobertura": {
            "estado": "no verificado" if existente else "no implementado",
            "evidencias": [],
            "pruebas": [],
        },
        "contrato": {"frase": "", "exito": []},
        "actores": [],
        "flujos": [],
        "episodios": [],
        "recorridos": [],
        "reglas": [],
        "estados": [],
        "datos": [],
        "volumen": [],
        "integraciones": [],
        "superficie": {},
        "calidad": [],
        "fuera": [],
        "preguntas": [],
    }


def copiar_carpeta_literal(origen, destino):
    """Sustituye el repo vacío por una copia byte a byte del código del usuario."""
    if not origen.is_dir():
        morir("la carpeta de código no existe: %s" % origen)
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(origen, destino, symlinks=True)
    if not (destino / ".git").exists():
        r = ejecutar(["git", "init", "-b", "main"], cwd=destino)
        if r.returncode:
            morir("no pude iniciar git en la copia local:\n%s" % r.stdout)


def dejar_repo_nuevo_minimo(main):
    workflows = main / ".github" / "workflows"
    if workflows.exists():
        shutil.rmtree(workflows)
    github = main / ".github"
    if github.exists() and not any(github.iterdir()):
        github.rmdir()
    ejecutar(["git", "add", "-A"], cwd=main)
    ejecutar(["git", "commit", "-m", "Inicio: repo vacío con README"], cwd=main)


def marcar_inicio(destino, existente):
    estado = destino / "docs" / "05-trabajo" / "ESTADO.md"
    siguiente = (
        "analizar profundamente `main/` ANTES de entrevistar y extraer todos "
        "los flujos actuales con evidencia"
        if existente
        else "entrevistar al usuario o, si la salta, proponer y completar todos los planos"
    )
    estado.write_text(
        "# ESTADO — ingeniería de requisitos en curso\n\n"
        "## Posición actual\n\n"
        "- **Fase**: definición de flujos; el diseño aún no está congelado.\n"
        "- **Workspace**: creado desde el principio; los planos canónicos ya viven aquí.\n"
        "- **Siguiente acción obligatoria**: %s.\n\n"
        "## Regla de salida\n\n"
        "No presentar para aprobación hasta pasar `validar.py --perfil revision` y "
        "`validar_web.py`; no congelar hasta la aprobación explícita del usuario.\n"
        % siguiente,
        encoding="utf-8",
    )
    ejecutar(["git", "add", "docs/05-trabajo/ESTADO.md"], cwd=destino)
    ejecutar(["git", "commit", "-m", "Inicia ingeniería de requisitos"], cwd=destino)


def main():
    ap = argparse.ArgumentParser(
        description="Crea inmediatamente <nombre>-agents y prepara main/."
    )
    ap.add_argument("--destino", required=True)
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--titulo", required=True)
    ap.add_argument("--tipo", choices=("webapp", "automatizacion", "agente", "otro"),
                    default="webapp")
    fuente = ap.add_mutually_exclusive_group()
    fuente.add_argument("--remoto", help="URL del repositorio de código existente")
    fuente.add_argument("--carpeta", help="carpeta local existente; se COPIA, nunca se mueve")
    args = ap.parse_args()

    destino = Path(args.destino).expanduser().resolve()
    carpeta = Path(args.carpeta).expanduser().resolve() if args.carpeta else None
    existente = bool(args.remoto or carpeta)
    if not destino.name.endswith("-agents"):
        morir("el destino debe terminar en -agents")
    if destino.exists() and any(destino.iterdir()):
        morir("el destino ya existe y no está vacío: %s" % destino)
    if carpeta and (
        destino == carpeta
        or destino in carpeta.parents
        or carpeta in destino.parents
    ):
        morir("el workspace no puede contener ni sustituir la carpeta original")

    with tempfile.TemporaryDirectory(prefix="ingenieria-requisitos-inicio-") as temporal:
        borrador = Path(temporal)
        (borrador / "planos.json").write_text(
            json.dumps(
                planos_iniciales(args.nombre, args.titulo, existente),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        comando = [
            sys.executable,
            str(BASE / "bootstrap.py"),
            "--planos",
            str(borrador),
            "--destino",
            str(destino),
            "--tipo",
            args.tipo,
            "--compilar",
        ]
        if args.remoto:
            comando += ["--remoto", args.remoto]
        r = ejecutar(comando)
        if r.returncode:
            morir("el bootstrap inicial falló:\n%s" % r.stdout)

    if carpeta:
        copiar_carpeta_literal(carpeta, destino / "main")
        shutil.copyfile(
            BASE.parent / "plantilla" / "bias" / "brownfield.md",
            destino / "docs" / "01-constitucion" / "bias.md",
        )
        ejecutar(["git", "add", "docs/01-constitucion/bias.md"], cwd=destino)
        ejecutar(["git", "commit", "-m", "Activa análisis brownfield"], cwd=destino)
    elif not args.remoto:
        dejar_repo_nuevo_minimo(destino / "main")

    # El hook se configura solo en la copia, nunca en el repositorio original.
    ejecutar(
        ["git", "config", "core.hooksPath", str((destino / ".githooks").resolve())],
        cwd=destino / "main",
    )
    marcar_inicio(destino, existente)

    planos = destino / "docs" / "02-flujos" / "planos" / "planos.json"
    print("Workspace de requisitos listo: %s" % destino)
    print("Código de trabajo: %s" % (destino / "main"))
    print("Planos canónicos: %s" % planos)
    if existente:
        print("Siguiente paso obligatorio: analizar main/ antes de hacer preguntas.")
    else:
        print("Siguiente paso: completar los flujos por entrevista o autopropuesta.")
    print(
        'Revisión estable: cd %s && "%s" '
        "docs/00-metodo/requisitos/requisitos.py abrir"
        % (destino, sys.executable)
    )


if __name__ == "__main__":
    main()
