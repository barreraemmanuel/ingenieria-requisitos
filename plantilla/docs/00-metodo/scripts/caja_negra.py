#!/usr/bin/env python3
"""Registra incidentes de ejecución sin copiar conversaciones ni secretos.

El JSONL es material de entrada para una revisión semántica posterior. Este comando captura
contexto; no clasifica causas ni pretende reemplazar el análisis de un LLM.

Subcomandos: `registrar` (añade un episodio), `listar` (tabla compacta), `validar` (revisa
el JSONL) y `enviar` (canal VOLUNTARIO: comparte los incidentes ya redactados con el autor
de la herramienta, enseñando antes exactamente lo que viaja).
"""
import argparse
import datetime
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import control_plane

# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

SEVERIDADES = ("P0", "P1", "P2", "nota")
# Campos sin los cuales un incidente no cuenta nada. Las líneas v1 no llevan severidad ni
# version_metodo y siguen siendo válidas: solo se exige lo que siempre existió.
OBLIGATORIOS = ("schema", "id", "timestamp", "fase", "sintoma", "esperado", "actual")

# Canal PRIVADO de entrega del feedback (decisión de producto 2026-08-05: repo público,
# feedback nunca público). Vacío = sin canal: `enviar` solo empaqueta en local. Cuando el
# endpoint exista, una actualización del método (Modo D) rellena esta constante y los
# workspaces la reciben; el contrato del endpoint vive con el autor de la herramienta.
ENDPOINT_FEEDBACK = ""

LIMITE_ENVIO = 60 * 1024  # tope del paquete: suficiente contexto sin volcar historia entera

# Rutas con el nombre del usuario dentro: en el envío se colapsan a `~`.
RE_HOME = re.compile(r"/(?:Users|home)/[^/\s\"'\\]+")

# Formas de credencial reconocibles que la redacción genérica no sabe limpiar (no van
# precedidas de `clave=`): si una sobrevive a la redacción, NO se envía nada.
CREDENCIALES_RESIDUALES = (
    ("clave privada PEM", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("clave de acceso AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token de GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("token de Slack", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b")),
    ("token JWT", re.compile(
        r"\beyJ[0-9A-Za-z_+/=-]{8,}\.[0-9A-Za-z_+/=-]{8,}\.[0-9A-Za-z_+/=-]{8,}\b"
    )),
)


# 074 · Clasificación del bloqueo que causó el incidente. El vocabulario y el criterio son
# los de `lint_salidas.py` (la 049): se IMPORTA, nunca se copia, para que el mismo mensaje
# reciba la misma etiqueta lo mire quien lo mire. `no_aplica` es el caso límite que importa:
# un crash o un timeout no es el rechazo de un script y contarlo como `fuera_de_banda`
# inflaría con ruido la métrica de «cuántas veces el método atrapa a quien lo conduce».
CONTINUACIONES = ("en_banda", "por_diseño", "fuera_de_banda", "no_aplica")

# De qué script habla el incidente. La `fase` es texto libre («despacho · unidad.py …»), así
# que el nombre se saca de ahí y, si no aparece, del propio mensaje.
RE_SCRIPT = re.compile(r"[\w.\-]+\.py")


def _lint_salidas():
    """El guardián de salidas, importado desde su misma carpeta. None si no está."""
    carpeta = str(Path(__file__).resolve().parent)
    if carpeta not in sys.path:
        sys.path.insert(0, carpeta)
    try:
        import lint_salidas
    except ImportError:
        return None
    return lint_salidas


def clasificar_continuacion(texto):
    """en_banda | por_diseño | fuera_de_banda | no_aplica para el mensaje de un incidente."""
    texto = (texto or "").strip()
    lint = _lint_salidas()
    if not texto or lint is None:
        return "no_aplica"
    # `veredicto` pide el corro de mensajes y su ventana de código; aquí solo hay un texto,
    # que hace de ambos: el criterio (comando > marcador > mudo) es exactamente el mismo.
    clase, _forma = lint.veredicto({"corro": texto, "ventana": texto})
    if clase == "fuera_de_banda" and not (
        lint.BLOQUEO.search(texto) and not lint.NO_BLOQUEA.match(texto)
    ):
        return "no_aplica"
    return clase


def continuacion_de(datos):
    """La clase guardada en el registro o, si es viejo y no la lleva, la derivada al vuelo."""
    valor = str(datos.get("continuacion") or "")
    return valor if valor in CONTINUACIONES else clasificar_continuacion(datos.get("actual"))


def script_de(datos):
    for campo in ("fase", "actual", "sintoma"):
        encontrado = RE_SCRIPT.search(str(datos.get(campo) or ""))
        if encontrado:
            return encontrado.group(0)
    fase = " ".join(str(datos.get("fase", "")).split())
    return fase[:30] or "(sin script)"


def morir(mensaje):
    raise SystemExit(f"caja_negra: {mensaje}")


def redactar(texto):
    return control_plane.redact_secrets(texto or "").replace("***", "[REDACTADO]")


def git(repo, *argumentos):
    resultado = subprocess.run(
        ["git", "-C", str(repo), *argumentos],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return resultado.stdout.strip() if resultado.returncode == 0 else ""


def dentro(ruta, raiz):
    try:
        ruta.relative_to(raiz)
        return True
    except ValueError:
        return False


def evidencia_relativa(repo, valor):
    ruta = Path(valor)
    if ruta.is_absolute() or ".." in ruta.parts:
        morir(f"la evidencia debe ser una ruta relativa dentro del repo: {valor}")
    resuelta = (repo / ruta).resolve()
    if resuelta != repo and not dentro(resuelta, repo):
        morir(f"la evidencia sale del repo: {valor}")
    return str(ruta).replace("\\", "/")


def detectar_harness():
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID"):
        return "codex"
    if os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID"):
        return "claude"
    return os.environ.get("AGENT_HARNESS", "desconocido")


def detectar_sesion():
    for clave in (
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_SESSION_ID",
        "AGENT_SESSION_ID",
    ):
        if os.environ.get(clave):
            return redactar(os.environ[clave])
    return "desconocida"


def version_metodo(repo):
    """La versión del método del repo donde se registra, o "desconocida"."""
    try:
        version = (Path(repo) / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "desconocida"
    return version or "desconocida"


def repo_valido(args):
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        morir(f"el repo no existe: {repo}")
    return repo


def cargar_incidentes(repo, *, tolerar_malas):
    """Lee el JSONL. Devuelve (incidentes, líneas malformadas [(número, error)])."""
    destino = repo / ".caja-negra" / "incidentes.jsonl"
    if not destino.is_file():
        return [], []
    incidentes, malas = [], []
    for numero, linea in enumerate(
        destino.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not linea.strip():
            continue
        try:
            datos = json.loads(linea)
            if not isinstance(datos, dict):
                raise ValueError("no es un objeto JSON")
        except ValueError as exc:
            if not tolerar_malas:
                morir(f"línea {numero} malformada ({exc}); repásala con `validar`")
            malas.append((numero, str(exc)))
            continue
        incidentes.append(datos)
    return incidentes, malas


def registrar(args):
    repo = repo_valido(args)
    evidencias = [evidencia_relativa(repo, item) for item in args.evidencia]
    worktree = git(repo, "rev-parse", "--show-toplevel")
    git_common = git(repo, "rev-parse", "--git-common-dir")
    if git_common and not Path(git_common).is_absolute():
        git_common = str((repo / git_common).resolve())
    actual = redactar(args.actual)
    registro = {
        "schema": "incidente-metarepo-v1",
        "id": str(uuid.uuid4()),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "harness": detectar_harness(),
        "session_id": detectar_sesion(),
        "severidad": args.severidad,
        "version_metodo": version_metodo(repo),
        "fase": redactar(args.fase),
        "repo_root": str(repo),
        "cwd": str(Path.cwd().resolve()),
        "worktree_root": str(Path(worktree).resolve()) if worktree else "",
        "git_common_dir": git_common,
        "branch": git(repo, "branch", "--show-current"),
        "sintoma": redactar(args.sintoma),
        "esperado": redactar(args.esperado),
        "actual": actual,
        "continuacion": args.continuacion or clasificar_continuacion(actual),
        "workaround": redactar(args.workaround),
        "evidencia": evidencias,
    }
    directorio = repo / ".caja-negra"
    directorio.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directorio.chmod(0o700)
    except OSError:
        pass
    destino = directorio / "incidentes.jsonl"
    descriptor = os.open(str(destino), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8") as salida:
            salida.write(json.dumps(registro, ensure_ascii=False, sort_keys=True) + "\n")
    finally:
        try:
            destino.chmod(0o600)
        except OSError:
            pass
    print(f"OK incidente {registro['id']} registrado en {destino}")
    return 0


def listar_bloqueos(incidentes):
    """Cuántos incidentes de cada clase deja cada script, y cuántos dejaron atrapado al
    agente. Los registros viejos, sin el campo, se clasifican al vuelo por su mensaje."""
    conteo = {}
    for datos in incidentes:
        fila = conteo.setdefault(script_de(datos), dict.fromkeys(CONTINUACIONES, 0))
        fila[continuacion_de(datos)] += 1
    ancho = max([len("script")] + [len(nombre) for nombre in conteo])
    print(f"{'script':<{ancho}}  " + "  ".join(f"{clase:>14}" for clase in CONTINUACIONES))
    for nombre in sorted(conteo):
        cuentas = "  ".join(f"{conteo[nombre][clase]:>14}" for clase in CONTINUACIONES)
        print(f"{nombre:<{ancho}}  {cuentas}")
    atrapados = sum(fila["fuera_de_banda"] for fila in conteo.values())
    print(f"Total atrapado (fuera_de_banda): {atrapados} de {len(incidentes)} incidente(s)")
    return 0


def listar(args):
    repo = repo_valido(args)
    incidentes, malas = cargar_incidentes(repo, tolerar_malas=True)
    if getattr(args, "bloqueos", False) and incidentes:
        return listar_bloqueos(incidentes)
    if not incidentes and not malas:
        print("Caja negra vacía: sin incidentes registrados.")
        return 0
    print(f"{'fecha':<10}  {'sev':<4}  {'fase':<22}  síntoma")
    for datos in incidentes:
        fecha = str(datos.get("timestamp", ""))[:10] or "sin fecha"
        severidad = str(datos.get("severidad") or "nota")
        fase = " ".join(str(datos.get("fase", "")).split())
        fase = fase[:21] + "…" if len(fase) > 22 else fase
        sintoma = " ".join(str(datos.get("sintoma", "")).split())
        sintoma = sintoma[:59] + "…" if len(sintoma) > 60 else sintoma
        print(f"{fecha:<10}  {severidad:<4}  {fase:<22}  {sintoma}")
    resumen = f"{len(incidentes)} incidente(s)"
    if malas:
        resumen += f" · {len(malas)} línea(s) malformadas (repásalas con `validar`)"
    print(resumen)
    return 0


def validar(args):
    repo = repo_valido(args)
    destino = repo / ".caja-negra" / "incidentes.jsonl"
    if not destino.is_file():
        print(f"OK: no hay caja negra que validar ({destino} no existe).")
        return 0
    incidentes, malas = cargar_incidentes(repo, tolerar_malas=True)
    problemas = [f"línea {numero}: JSON malformado ({error})" for numero, error in malas]
    for datos in incidentes:
        etiqueta = str(datos.get("id") or "sin id")
        faltan = [campo for campo in OBLIGATORIOS if not str(datos.get(campo) or "").strip()]
        if faltan:
            problemas.append(f"incidente {etiqueta}: faltan campos {', '.join(faltan)}")
        # v1 no llevaba severidad ni version_metodo: su ausencia es válida; si están, se
        # valida su forma.
        if "severidad" in datos and datos["severidad"] not in SEVERIDADES:
            problemas.append(
                f"incidente {etiqueta}: severidad '{datos['severidad']}' fuera de "
                f"{'/'.join(SEVERIDADES)}"
            )
        if "version_metodo" in datos and not str(datos["version_metodo"] or "").strip():
            problemas.append(f"incidente {etiqueta}: version_metodo vacía")
        if "continuacion" in datos and datos["continuacion"] not in CONTINUACIONES:
            problemas.append(
                f"incidente {etiqueta}: continuacion '{datos['continuacion']}' fuera de "
                f"{'/'.join(CONTINUACIONES)}"
            )
        if "evidencia" in datos and not isinstance(datos["evidencia"], list):
            problemas.append(f"incidente {etiqueta}: evidencia debe ser una lista")
    if problemas:
        for problema in problemas:
            print(f"FAIL {problema}")
        print(f"{len(problemas)} problema(s) en {destino}")
        return 1
    print(f"OK {len(incidentes)} incidente(s) bien formados en {destino}")
    return 0


def redactar_envio(texto):
    """Redacción reforzada para lo que sale del ordenador: secretos + rutas de usuario."""
    return RE_HOME.sub("~", redactar(texto))


def _redactar_valor(valor):
    if isinstance(valor, str):
        return redactar_envio(valor)
    if isinstance(valor, list):
        return [_redactar_valor(item) for item in valor]
    if isinstance(valor, dict):
        return {clave: _redactar_valor(item) for clave, item in valor.items()}
    return valor


def redactar_incidente(incidente):
    """Copia del incidente lista para viajar: todo texto redactado y sin hostname."""
    return {
        clave: _redactar_valor(valor)
        for clave, valor in incidente.items()
        if clave != "host"
    }


def credencial_residual(texto):
    """Nombre del patrón de credencial que sobrevivió a la redacción, o ""."""
    for etiqueta, patron in CREDENCIALES_RESIDUALES:
        if patron.search(texto):
            return etiqueta
    return ""


def empaquetar(incidentes, version, limite=None):
    """Paquete de envío. Si no cabe en `limite` bytes, conserva los MÁS RECIENTES.

    Devuelve (paquete, texto JSON). El JSONL es cronológico: truncar es descartar por
    delante. La plataforma viaja sin hostname ni usuario.
    """
    total = len(incidentes)
    recorte = list(incidentes)
    while True:
        paquete = {
            "schema": "caja-negra-envio-v1",
            "version_metodo": version,
            "plataforma": {
                "sistema": platform.system(),
                "version_sistema": platform.release(),
                "python": platform.python_version(),
            },
            "total_registrados": total,
            "incluidos": len(recorte),
            "truncado": len(recorte) < total,
            "incidentes": recorte,
        }
        texto = json.dumps(paquete, ensure_ascii=False, indent=2, sort_keys=True)
        if limite is None or len(texto.encode("utf-8")) <= limite or not recorte:
            return paquete, texto
        recorte = recorte[1:]





def enviar(args):
    repo = repo_valido(args)
    # (a) Redactar ANTES de cualquier salida: nada del JSONL crudo llega a la pantalla.
    crudos, _ = cargar_incidentes(repo, tolerar_malas=False)
    if not crudos:
        print("No hay nada que enviar: la caja negra está vacía.")
        return 0
    incidentes = [redactar_incidente(incidente) for incidente in crudos]
    version = version_metodo(repo)
    paquete, texto = empaquetar(incidentes, version, limite=LIMITE_ENVIO)
    # (e) Si tras redactar queda una credencial reconocible, no sale nada de aquí.
    residuo = credencial_residual(texto)
    if residuo:
        morir(
            "NO se envía nada: tras la redacción sigue habiendo un patrón de credencial "
            f"que no sé limpiar ({residuo}). Limpia ese incidente a mano en "
            ".caja-negra/incidentes.jsonl y vuelve a intentarlo."
        )
    # (d) Enseñar antes exactamente lo que viaja, y pedir permiso.
    print("Esto es EXACTAMENTE lo que se compartiría (ya redactado: sin secretos, sin "
          "hostname y sin tu nombre de usuario en las rutas):\n")
    print(texto)
    if paquete["truncado"]:
        print(f"\nAviso: de {paquete['total_registrados']} incidentes solo viajan los "
              f"{paquete['incluidos']} más recientes; el paquete no cabía entero.")
    print("\nCompartirlo es VOLUNTARIO y sirve solo para mejorar el método. "
          "No se envía nada más que lo de arriba.")
    if not args.si:
        # Un stdin que no es una terminal (un agente, un PIPE) no puede contestar: el
        # input() se quedaba esperando para siempre. El consentimiento no se presupone:
        # sin terminal, no se envía y se dice cómo consentir (ADR-026).
        if not sys.stdin.isatty():
            print("\nSin terminal interactiva no envío nada. Para consentir el envío, "
                  "repite el comando con --si.")
            return 0
        try:
            respuesta = input("¿Enviar ahora? [s/N] ").strip().lower()
        except EOFError:
            respuesta = ""
        if respuesta not in {"s", "si", "sí"}:
            print("No se envió nada.")
            return 0
    # La entrega SOLO va a un canal privado. Un sitio público (un issue, un foro) no vale:
    # la redacción quita credenciales, pero no la semántica del negocio del usuario.
    if ENDPOINT_FEEDBACK:
        peticion = urllib.request.Request(
            ENDPOINT_FEEDBACK,
            data=texto.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Metodo-Version": version,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=20) as respuesta_http:
                if 200 <= respuesta_http.status < 300:
                    print("Enviado por el canal privado. Gracias: esto mejora el método.")
                    return 0
                estado = respuesta_http.status
        except (urllib.error.URLError, OSError) as exc:
            estado = exc
        print(f"El canal privado no respondió bien ({estado}); te dejo el paquete en local.")
    fecha = datetime.date.today().isoformat()
    destino = repo / ".caja-negra" / f"envio-{fecha}.json"
    destino.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destino.write_text(texto + "\n", encoding="utf-8")
    print(f"Paquete guardado en {destino} (no se ha enviado nada).")
    if not ENDPOINT_FEEDBACK:
        print("El canal de entrega privado está en preparación; cuando exista, este mismo "
              "comando lo usará. Mientras tanto el paquete es tuyo: compártelo solo por un "
              "medio privado si quieres hacerlo llegar.")
    else:
        print("Puedes reintentar `enviar` más tarde; el paquete no viaja a ningún sitio solo.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("registrar", help="añade un episodio a la caja negra privada")
    p.add_argument("--repo", default=".", help="raíz declarada del meta-repo")
    p.add_argument("--fase", required=True)
    p.add_argument("--sintoma", required=True)
    p.add_argument("--esperado", required=True)
    p.add_argument("--actual", required=True)
    p.add_argument("--workaround", default="")
    p.add_argument("--evidencia", action="append", default=[])
    p.add_argument("--continuacion", choices=CONTINUACIONES, default=None,
                   help="si el bloqueo nombraba la salida. Sin esto se deriva del texto de "
                        "--actual con el mismo criterio que lint_salidas.py")
    p.add_argument("--severidad", choices=SEVERIDADES, default="nota",
                   help="P0 bloquea, P1 duele, P2 molesta, nota es contexto (defecto)")
    p.set_defaults(func=registrar)
    p = sub.add_parser("listar", help="tabla compacta de los incidentes registrados")
    p.add_argument("--repo", default=".", help="raíz declarada del meta-repo")
    p.add_argument("--bloqueos", action="store_true",
                   help="en vez de la tabla, el reparto por script de en banda / por diseño "
                        "/ fuera de banda y el total que dejó atrapado al agente")
    p.set_defaults(func=listar)
    p = sub.add_parser("validar", help="revisa el JSONL: líneas rotas o campos ausentes")
    p.add_argument("--repo", default=".", help="raíz declarada del meta-repo")
    p.set_defaults(func=validar)
    p = sub.add_parser(
        "enviar",
        help="VOLUNTARIO: comparte los incidentes redactados con el autor de la "
             "herramienta (enseña antes lo que viaja y pide confirmación)",
    )
    p.add_argument("--repo", default=".", help="raíz declarada del meta-repo")
    p.add_argument("--si", action="store_true",
                   help="no preguntar (para uso no interactivo); el envío sigue siendo opt-in")
    p.set_defaults(func=enviar)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
