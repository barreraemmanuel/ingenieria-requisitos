#!/usr/bin/env python3
"""Congela un workspace aprobado y, opcionalmente, publica sus dos repos.

La operación se hace sobre el mismo ``<nombre>-agents`` creado por
``iniciar.py``: valida los planos completos, prueba el visor real, regenera
constitución y flows, conserva ``main/`` y deja ambos repos enlazados.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
try:
    from . import revision
except ImportError:
    import revision

BASE = Path(__file__).resolve().parent


def morir(mensaje):
    raise SystemExit("finalizar: %s" % mensaje)


def ejecutar(comando, cwd=None):
    return subprocess.run(
        comando,
        cwd=cwd,
        text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def exigir_verde(comando, etiqueta, cwd=None):
    r = ejecutar(comando, cwd=cwd)
    if r.returncode:
        morir("%s falló:\n%s" % (etiqueta, r.stdout))
    print(r.stdout, end="")


# Estados del mapa en los que una actividad DICE tener planos completos
# (mismo criterio que validar.py). Una actividad "sin empezar" o "en
# entrevista" no tiene planos todavía y eso es un estado normal del mapa,
# no un impedimento para congelar la versión aprobada.
ESTADOS_ACTIVIDAD_CON_PLANOS = ("especificada", "en obra", "entregada")


def rutas_planos(mapa, datos):
    yield mapa, None
    base = mapa.parent
    for actividad in datos.get("actividades", []):
        yield base / "actividades" / actividad["id"] / "planos.json", actividad


def congelar_planos(mapa):
    datos_mapa = json.loads(mapa.read_text(encoding="utf-8"))
    for ruta, actividad in rutas_planos(mapa, datos_mapa):
        pendiente = actividad is not None and (
            actividad.get("estado") not in ESTADOS_ACTIVIDAD_CON_PLANOS
        )
        if pendiente:
            # Sin planos, o con un borrador a medias: no forma parte de la
            # versión congelada; seguirá su vida en el workspace (modo C).
            continue
        if not ruta.is_file():
            morir(
                "falta el plano %s (la actividad dice %r)"
                % (ruta, (actividad or {}).get("estado"))
            )
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        definicion = datos.get("definicion") or {}
        if definicion.get("estado") not in ("aprobado", "congelado"):
            morir(
                "%s no está aprobado por el usuario (definicion.estado=%r)"
                % (ruta, definicion.get("estado"))
            )
        definicion["estado"] = "congelado"
        datos["definicion"] = definicion
        ruta.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def reescribir_enlaces_indice(texto):
    """compilar.py escribe el índice con las rutas de SU carpeta temporal
    (01-constitution/constitution.md, 02-flows/AREA/ID.md); este volcado renombra la
    constitución y aplana todas las actividades como hermanas del propio índice — sin
    reescribir los enlaces, el 100% apuntaba a rutas que nunca existieron (bug 005)."""
    texto = texto.replace(
        "](01-constitution/constitution.md)", "](../01-constitucion/manifiesto.md)"
    )
    texto = re.sub(r"\]\(02-flows/(?:[^)]+/)?([^/)]+\.md)\)", r"](\1)", texto)
    # No es un enlace, pero nombra una carpeta que tras aplanar no existe en el
    # destino — mismo síntoma (hace dudar si el proyecto está mal creado).
    return texto.replace(
        "- `02-flows/`: un documento por actividad.",
        "- un documento por actividad, en esta misma carpeta.",
    )


def copiar_documentacion(workspace, salida, mapa):
    """Vuelca al workspace la documentación compilada: manifiesto, índice y un .md por
    actividad.

    El aplanado (un `<actividad>.md` hermano del índice) NO se hace aquí: lo escribe
    `compilar.py --formato plano`, que desde el bug 092 conoce ese formato. Tener dos
    copias del mismo aplanado era el agujero que dejaba abierto aquel arreglo: si una
    cambiaba, la otra no se enteraba. Aquí queda solo lo que compilar.py no debe tocar
    en ese formato — la constitución y el INDICE.md con sus enlaces reescritos.
    """
    constitucion = salida / "01-constitution" / "constitution.md"
    if not constitucion.is_file():
        morir("la compilación no produjo constitution.md")
    indice = salida / "README.md"
    if not indice.is_file():
        morir("la compilación no produjo README.md")
    texto_indice = reescribir_enlaces_indice(indice.read_text(encoding="utf-8"))

    destino_flows = workspace / "docs" / "02-flujos"
    # Se compila a una carpeta temporal ANTES de borrar nada: si compilar.py se planta
    # (p. ej. pide --formato), su rechazo sale tal cual por `exigir_verde` y el
    # workspace se queda con la documentación anterior entera, no a medias.
    with tempfile.TemporaryDirectory(prefix="finalizar-plano-") as temporal:
        exigir_verde(
            [sys.executable, str(BASE / "compilar.py"), "--mapa", str(mapa),
             "--salida", temporal, "--formato", "plano"],
            "compilación en formato plano",
        )
        documentos = sorted(Path(temporal).glob("*.md"))
        if not documentos:
            morir("compilar.py --formato plano no produjo ningún documento")

        shutil.copyfile(constitucion, workspace / "docs" / "01-constitucion" / "manifiesto.md")
        for anterior in destino_flows.glob("*.md"):
            anterior.unlink()
        (destino_flows / "INDICE.md").write_text(texto_indice, encoding="utf-8")
        for documento in documentos:
            shutil.copyfile(documento, destino_flows / documento.name)


def escribir_estado_congelado(workspace):
    """Las rutas a commitear tras congelar la documentación.

    ESTADO.md lo escribe el PADRE del workspace: en un re-vuelco (modo C) machacarlo
    destruía la tabla de unidades y los bloqueos reales (ADR-026). Solo se escribe si
    no existe (primer finalizado); si existe, se conserva y se dice."""
    estado = workspace / "docs" / "05-trabajo" / "ESTADO.md"
    rutas_commit = ["docs/01-constitucion", "docs/02-flujos"]
    if not estado.is_file():
        estado.write_text(
            "# ESTADO — diseño congelado\n\n"
            "- Los planos fueron aprobados y pasaron validación estructural y E2E.\n"
            "- Constitución y flows están regenerados desde la fuente canónica.\n"
            "- Siguiente fase: investigación/planificación e implementación por recorridos.\n",
            encoding="utf-8",
        )
        rutas_commit.append("docs/05-trabajo/ESTADO.md")
    else:
        print("ESTADO.md conservado: lo mantiene el padre del workspace; anota tú allí "
              "que los planos quedaron congelados.")
    return rutas_commit


def commit_si_hay_cambios(repo, mensaje, incluir_todo=False):
    if incluir_todo:
        ejecutar(["git", "add", "-A"], cwd=repo)
    estado = ejecutar(["git", "status", "--porcelain=v1"], cwd=repo)
    if estado.returncode:
        morir("%s no es un repositorio git:\n%s" % (repo, estado.stdout))
    if estado.stdout.strip():
        r = ejecutar(["git", "commit", "-m", mensaje], cwd=repo)
        if r.returncode:
            morir("no pude crear el commit en %s:\n%s" % (repo, r.stdout))


def commit_inicial_o_aviso(main):
    """El barrido total (`add -A`) SOLO vale para el primer import de una carpeta ingerida
    sin historia: ahí todo lo que hay es, por definición, el estado inicial. Con historia,
    ese mismo barrido absorbía en silencio trabajo sin commitear del usuario o de una
    unidad a medio cerrar (ADR-026): se publica lo commiteado y lo demás se nombra."""
    sin_historia = ejecutar(["git", "rev-parse", "--verify", "HEAD"], cwd=main).returncode != 0
    if sin_historia:
        commit_si_hay_cambios(main, "Importa el estado inicial del código", incluir_todo=True)
        return
    pendiente = ejecutar(["git", "status", "--porcelain=v1"], cwd=main)
    if pendiente.stdout.strip():
        print("OJO: main/ tiene cambios sin commitear. NO los toco ni los publico "
              "(se publica lo commiteado); revisa si son tuyos o de una unidad a "
              "medio cerrar.")


def repo_github(owner, nombre):
    if not shutil.which("gh"):
        morir("falta GitHub CLI (`gh`) para publicar repositorios")
    existe = ejecutar(["gh", "repo", "view", "%s/%s" % (owner, nombre), "--json", "name"])
    if existe.returncode:
        creado = ejecutar(
            ["gh", "repo", "create", "%s/%s" % (owner, nombre), "--private"]
        )
        if creado.returncode:
            morir("no pude crear %s/%s:\n%s" % (owner, nombre, creado.stdout))
    return "https://github.com/%s/%s.git" % (owner, nombre)


def configurar_remoto(repo, url):
    actual = ejecutar(["git", "remote", "get-url", "origin"], cwd=repo)
    if actual.returncode:
        r = ejecutar(["git", "remote", "add", "origin", url], cwd=repo)
    else:
        r = ejecutar(["git", "remote", "set-url", "origin", url], cwd=repo)
    if r.returncode:
        morir("no pude configurar origin en %s:\n%s" % (repo, r.stdout))


def publicar_github(workspace, owner, nombre):
    main = workspace / "main"
    nombre_meta = nombre + "-agents"
    url_codigo = repo_github(owner, nombre)
    url_meta = repo_github(owner, nombre_meta)

    commit_inicial_o_aviso(main)
    configurar_remoto(main, url_codigo)
    subida = ejecutar(["git", "push", "-u", "origin", "HEAD:main"], cwd=main)
    if subida.returncode:
        morir("no pude publicar el repo de código:\n%s" % subida.stdout)

    repos = workspace / "repos.yaml"
    texto = repos.read_text(encoding="utf-8")
    texto = texto.replace(
        "PENDIENTE  # crear el remoto del repo de código y poner aquí su URL",
        url_codigo,
    )
    repos.write_text(texto, encoding="utf-8")
    ejecutar(["git", "add", "repos.yaml"], cwd=workspace)
    commit_si_hay_cambios(workspace, "Configura los dos repositorios independientes")
    configurar_remoto(workspace, url_meta)
    subida = ejecutar(["git", "push", "-u", "origin", "main"], cwd=workspace)
    if subida.returncode:
        morir("no pude publicar el meta-repo:\n%s" % subida.stdout)
    print("GitHub: %s/%s y %s/%s" % (owner, nombre, owner, nombre_meta))


def main():
    ap = argparse.ArgumentParser(
        description="Valida, congela y finaliza un workspace aprobado."
    )
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--nombre", help="nombre final del repo; por defecto el del workspace")
    # Una de las dos, OBLIGATORIA. Antes, olvidarse de --github finalizaba el proyecto en
    # silencio y sin remoto: el usuario se quedaba con todo su trabajo en un solo disco
    # creyendo que estaba publicado, y nada volvía a mencionarlo jamás. Ahora la decisión
    # hay que tomarla —y por tanto preguntársela a él— para poder terminar.
    destino = ap.add_mutually_exclusive_group(required=True)
    destino.add_argument("--github", metavar="CUENTA",
                         help="crea/publica los dos repos privados en esa cuenta")
    destino.add_argument("--sin-github", action="store_true",
                         help="el usuario ha dicho que NO quiere GitHub: todo queda en este "
                              "ordenador, sin copia de seguridad, y se le advierte")
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    if not (workspace / ".git").exists() or not (workspace / "main" / ".git").exists():
        morir("no es un workspace válido creado por iniciar.py: %s" % workspace)
    mapa = workspace / "docs" / "02-flujos" / "planos" / "planos.json"
    if not mapa.is_file():
        morir("no encuentro los planos canónicos: %s" % mapa)

    # No basta con escribir "aprobado" en el JSON: el recibo firmado desde
    # la revisión web debe coincidir byte a byte con la versión actual.
    if not revision.aprobacion_vigente(mapa):
        morir(
            "no hay una aprobación vigente para estos planos; ábrelos con "
            "requisitos.py, resuelve el feedback y aprueba esa versión"
        )

    exigir_verde(
        [sys.executable, str(BASE / "validar.py"), "--datos", str(mapa),
         "--perfil", "congelado"],
        "validación de congelación",
    )
    exigir_verde(
        [sys.executable, str(BASE / "validar_web.py"), "--datos", str(mapa)],
        "E2E del visor",
    )
    congelar_planos(mapa)
    exigir_verde(
        [sys.executable, str(BASE / "validar.py"), "--datos", str(mapa),
         "--perfil", "congelado"],
        "validación final",
    )

    with tempfile.TemporaryDirectory(prefix="ingenieria-requisitos-final-") as temporal:
        salida = Path(temporal) / "especificaciones"
        exigir_verde(
            [sys.executable, str(BASE / "compilar.py"), "--mapa", str(mapa),
             "--salida", str(salida)],
            "compilación",
        )
        copiar_documentacion(workspace, salida, mapa)

    # Rutas explícitas: `git add docs` entero arrastraba trabajo del usuario sin
    # commitear, contradiciendo la regla 3 del propio método.
    ejecutar(["git", "add", *escribir_estado_congelado(workspace)], cwd=workspace)
    commit_si_hay_cambios(workspace, "Congela planos aprobados y documentación")

    nombre = args.nombre or workspace.name.removesuffix("-agents")
    if args.github:
        publicar_github(workspace, args.github, nombre)
    print("Proyecto finalizado en %s" % workspace)
    print("Repo de código conservado en %s" % (workspace / "main"))
    # El método viaja por copia: cuando la herramienta mejore, este
    # workspace NO se entera solo. El reparto es el Modo D.
    print(
        "Nota: el método de trabajo viaja DENTRO del workspace por copia. "
        "Cuando esta herramienta se actualice, pon el proyecto al día desde "
        "aquí con «pon al día mis proyectos» (Modo D: visor/actualizar.py)."
    )
    if args.sin_github:
        print(
            "\n" + "=" * 70 + "\n"
            "AVISO: este proyecto existe SOLO en este ordenador.\n"
            "No hay copia en ningún otro sitio: si se rompe el disco, se pierde todo —\n"
            "los planos, el código y el historial. Díselo al usuario con estas palabras.\n"
            "Cuando quiera publicarlo, se ejecuta esto mismo con --github <su-cuenta>.\n"
            + "=" * 70
        )


if __name__ == "__main__":
    main()
