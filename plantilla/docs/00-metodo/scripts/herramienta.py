#!/usr/bin/env python3
"""herramienta.py — el workspace se pone al día aunque la herramienta no esté en el disco.

    python3 docs/00-metodo/scripts/herramienta.py comprobar    (cada arranque: ¿hay método nuevo?)
    python3 docs/00-metodo/scripts/herramienta.py aplicar      (el usuario dijo que sí)
    python3 docs/00-metodo/scripts/herramienta.py aplicar --todos
    python3 docs/00-metodo/scripts/herramienta.py nunca        (no volver a avisar aquí)

POR QUÉ ESTE SCRIPT VIAJA CON EL MÉTODO: el canal de actualización dependía de que el
usuario mantuviera a mano un clon de la herramienta. Si borraba esa carpeta, el workspace
se quedaba sin avisos en silencio y sin forma de arreglarlo: `visor/actualizar.py` vive
justo en lo que falta. La pieza que comprueba y consigue la herramienta tiene que estar
DENTRO del workspace; por eso está aquí y por eso no importa nada de la herramienta.

QUÉ LEE DEL REMOTO: lo mínimo. Un `git ls-remote` (un viaje) como primer filtro y, solo
si el remoto se movió, un clon superficial y sin blobs para leer un único fichero: el
VERSION del método. Nunca el repositorio entero para responder "¿hay novedades?".

QUÉ NO HACE NUNCA: reparar, resetear ni reescribir el clon personal del usuario. Una
copia local se examina SOLO CON LECTURAS (limpieza, rama, remoto, commits propios) y solo
si supera todas recibe un `git pull --ff-only`; una copia sucia, divergente o de otro
origen se descarta sin que git la toque —ni un fetch— y se descarga otra en una carpeta
temporal. Y cualquier fallo del canal (sin red, sin credenciales, repo privado) es
silencio con salida 0: un arranque no se bloquea por esto jamás.

CUÁNTO PUEDE TARDAR: `comprobar` corre bajo un presupuesto TOTAL (PRESUPUESTO, 15 s) para
todo el proceso, no un timeout por orden. Un remoto que responde al `ls-remote` y luego se
atasca no puede sumar minutos de arranque: agotado el presupuesto, se calla y sale 0.

Solo stdlib.
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

# scripts/ -> 00-metodo/ -> docs/ -> el workspace
WORKSPACE = Path(__file__).resolve().parents[3]
PREFERENCIAS = ".claude/actualizaciones.md"
CABECERA_PREFERENCIAS = (
    "# Avisos de actualización del método\n"
    "\n"
    "> Lo lee el arranque del agente (AGENTS.md § Al arrancar). La línea\n"
    "> `preferencia: nunca` silencia el aviso de versión nueva en todos los arranques\n"
    "> futuros de este workspace; borra esa línea para volver a preguntarlo.\n"
    "> La línea `herramienta: <ruta>` recuerda dónde vive la herramienta en esta máquina.\n"
    "> La línea `remoto: <sha>` es lo último visto en el origen del método: evita\n"
    "> descargar nada cuando no se ha movido.\n"
)
ORDEN = "python3 docs/00-metodo/scripts/herramienta.py"

# Copiadas de visor/actualizar.py A PROPÓSITO: este script no puede importar de una
# herramienta que quizá no existe en esta máquina. Es la razón de ser del fichero.
SALTAR = {"node_modules", "__pycache__", "Library", "Applications", ".git", ".venv",
          "venv", "worktrees", "main", "dist", "build", ".Trash", "System", "vendor"}
RAICES_HABITUALES = ("Project", "Projects", "Proyectos", "Developer", "dev", "code",
                     "Documents", "Desktop", "repos", "src", "work")
PROFUNDIDAD = 3          # la herramienta vive a un par de carpetas de casa, no enterrada
TIMEOUT = int(os.environ.get("INGENIERIA_REQUISITOS_TIMEOUT", "12"))
# Presupuesto TOTAL del arranque (R4): no es el timeout de una orden, es lo que puede
# tardar `comprobar` ENTERO. Timeouts por orden se suman —ls-remote, clone, sparse,
# checkout— y un remoto que se atasca a mitad convertiría "silencio y rápido" en minutos.
PRESUPUESTO = int(os.environ.get("INGENIERIA_REQUISITOS_PRESUPUESTO", "15"))
MINIMO_UTIL = 0.5        # por debajo de esto no da tiempo ni a arrancar un git: se calla
_LIMITE = None           # instante (monotónico) en que se acaba el presupuesto, o None


def abrir_presupuesto(segundos=None):
    """Arranca el reloj del proceso. A partir de aquí ningún git lo sobrepasa."""
    global _LIMITE
    _LIMITE = time.monotonic() + (PRESUPUESTO if segundos is None else segundos)


def presupuesto_restante():
    return None if _LIMITE is None else _LIMITE - time.monotonic()


def git(*args, cwd=None, timeout=TIMEOUT):
    """git con las credenciales que ya tenga la máquina y SIN preguntar nada.

    Un arranque no puede quedarse colgado en un prompt de contraseña: sin acceso, el
    canal calla (R4). Devuelve None si git no está, falla el arranque o expira.
    Bajo presupuesto abierto, el timeout de cada orden se recorta a lo que quede: la
    suma de todas nunca pasa del presupuesto total."""
    queda = presupuesto_restante()
    if queda is not None:
        if queda <= MINIMO_UTIL:
            return None
        timeout = min(timeout, queda)
    entorno = dict(os.environ)
    entorno.setdefault("GIT_TERMINAL_PROMPT", "0")
    entorno.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    try:
        return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=entorno)
    except (OSError, subprocess.SubprocessError):
        return None


def git_leer(ruta, *args, timeout=TIMEOUT):
    """git de SOLO LECTURA sobre un clon ajeno: `--no-optional-locks` para no tocar ni
    el índice. Es lo único que se le hace a la carpeta del usuario antes de decidir."""
    return git("--no-optional-locks", "-C", str(ruta), *args, timeout=timeout)


# --- preferencias del workspace (.claude/, fuera de git y de lo que Modo D toca) ---

def texto_preferencias(workspace):
    try:
        return (workspace / PREFERENCIAS).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def preferencia(workspace, clave):
    m = re.search(rf"(?mi)^{clave}:[ \t]*(.+?)[ \t]*$", texto_preferencias(workspace))
    return m.group(1) if m else None


def guardar_preferencia(workspace, clave, valor):
    """Escribe (o reemplaza) `clave: valor`. Nunca falla hacia arriba: es una caché."""
    ruta = workspace / PREFERENCIAS
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        previo = texto_preferencias(workspace)
        base = previo if previo.strip() else CABECERA_PREFERENCIAS + "\n"
        linea = f"{clave}: {valor}"
        patron = rf"(?mi)^{clave}:[ \t]*.*$"
        # Reemplazo con lambda, no con la cadena: una ruta de Windows (C:\Users\…)
        # como texto de sustitución la leería re como escapes y la destrozaría.
        nuevo = (re.sub(patron, lambda _m: linea, base, count=1)
                 if re.search(patron, base)
                 else base.rstrip("\n") + "\n" + linea + "\n")
        ruta.write_text(nuevo, encoding="utf-8")
    except OSError:
        pass


# --- lo que el workspace sabe de sí mismo ---

def metodo_json(workspace):
    try:
        datos = json.loads((workspace / "METODO.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def origen(workspace):
    """La URL del repositorio del método. Sin ella no hay autosuficiencia posible.

    Se rechaza lo que git no debe recibir de un fichero: un valor que empiece por `-`
    (git lo leería como opción, no como URL) y el transporte `ext::`, que ejecuta el
    comando que le pongan. METODO.json viaja en un repositorio ajeno; que su contenido
    acabe siendo una orden en esta máquina no.
    """
    url = metodo_json(workspace).get("origen")
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if url.startswith("-") or url.lower().startswith("ext::"):
        return None
    return url


def version_local(workspace):
    try:
        return (workspace / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = metodo_json(workspace).get("version")
        return version.strip() if isinstance(version, str) else "sin versión"


# --- comprobar: lo mínimo del remoto, y silencio si no hay novedad ---

def sha_remoto(url):
    r = git("ls-remote", url, "HEAD")
    if r is None or r.returncode:
        return None
    primera = r.stdout.split("\n", 1)[0].split("\t", 1)[0].strip()
    return primera or None


def borrar_arbol(ruta):
    """rmtree que se lleva también lo que git deja en solo-lectura.

    Los objetos de `.git/` son 0o444 y en Windows el atributo de solo-lectura impide
    borrarlos: con `ignore_errors=True` el fallo se tragaba en silencio y el clon
    temporal se quedaba en %TEMP% en CADA arranque de CADA sesión, para siempre.
    """
    def reintentar(func, objetivo, _exc):
        try:
            os.chmod(objetivo, stat.S_IWRITE)
            func(objetivo)
        except OSError:
            pass                       # el borrado del temporal jamás bloquea el arranque

    if sys.version_info >= (3, 12):
        shutil.rmtree(ruta, onexc=reintentar)
    else:
        shutil.rmtree(ruta, onerror=reintentar)


def version_remota(url):
    """El VERSION publicado, leído con un clon superficial, sin blobs y sparse."""
    temporal = tempfile.mkdtemp(prefix="ir-version-")
    try:
        destino = Path(temporal) / "metodo"
        relativo = "plantilla/docs/00-metodo"
        r = git("clone", "--depth", "1", "--filter=blob:none", "--sparse",
                "--no-checkout", "--quiet", url, str(destino), timeout=TIMEOUT * 3)
        if r is None or r.returncode:
            return None
        for orden in (("sparse-checkout", "set", relativo), ("checkout",)):
            r = git(*orden, cwd=destino, timeout=TIMEOUT * 3)
            if r is None or r.returncode:
                return None
        try:
            return (destino / relativo / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            return None
    finally:
        borrar_arbol(temporal)


def aviso(workspace, publicada):
    mia = version_local(workspace)
    return "\n".join([
        f"Hay una actualización del método para este workspace: método {mia} → {publicada}",
        "Responde una vez por sesión:",
        f"    sí           → {ORDEN} aplicar",
        f"    todos        → {ORDEN} aplicar --todos",
        "    no por ahora → seguir tal cual; se volverá a preguntar en otro arranque",
        f"    nunca más    → {ORDEN} nunca",
    ])


def cmd_comprobar(workspace, _args):
    abrir_presupuesto()
    if preferencia(workspace, "preferencia") == "nunca":
        return 0
    url = origen(workspace)
    if not url:
        return 0
    sha = sha_remoto(url)
    if not sha:
        return 0
    if sha == preferencia(workspace, "remoto"):
        return 0
    publicada = version_remota(url)
    if not publicada:
        return 0
    if publicada == version_local(workspace):
        guardar_preferencia(workspace, "remoto", sha)
        return 0
    print(aviso(workspace, publicada))
    return 0


# --- aplicar: asegurar una herramienta utilizable y delegar en ella ---

def es_herramienta(ruta):
    try:
        return ((ruta / "visor/actualizar.py").is_file()
                and (ruta / "plantilla/docs/00-metodo/VERSION").is_file())
    except OSError:
        return False


def normalizar_remoto(url):
    """La identidad de un repositorio, comparable entre dos formas de escribirlo.

    Normalización deliberadamente CORTA y conservadora: solo lo que sin duda es la
    misma cosa (forma `scp` de ssh, usuario en la URL, `.git` y `/` finales, mayúsculas
    del esquema y del host). El camino NO se toca (hay servidores sensibles a mayúsculas)
    y `ext::` no se normaliza: se rechaza. Ante la duda, distinto —y un distinto solo
    cuesta una descarga en temporal, mientras un igual de más ejecutaría código ajeno.
    """
    if not isinstance(url, str):
        return None
    texto = url.strip()
    if not texto or texto.lower().startswith("ext::"):
        return None
    # `git@github.com:org/repo` es ssh escrito a la vieja usanza. El host pide dos
    # caracteres o más para no confundir `C:\Users\…` con host `C`.
    if "://" not in texto:
        scp = re.match(r"^(?:[^@/]+@)?([^/:]{2,}):(?!/)(.+)$", texto)
        if scp:
            texto = "ssh://{}/{}".format(scp.group(1), scp.group(2).lstrip("/"))
    partes = urllib.parse.urlsplit(texto)
    esquema = partes.scheme.lower()
    if esquema in ("", "file"):
        crudo = urllib.parse.unquote(partes.path) if esquema == "file" else texto
        try:
            return "file:" + str(Path(crudo).expanduser().resolve())
        except (OSError, ValueError):
            return None
    camino = re.sub(r"/+$", "", partes.path)
    camino = re.sub(r"\.git$", "", camino)
    puerto = ":{}".format(partes.port) if partes.port else ""
    return "{}://{}{}{}".format(esquema, (partes.hostname or "").lower(), puerto, camino)


def motivo_de_descarte(ruta, url):
    """Por qué NO se puede usar esta copia local, o None si se puede.

    TODO lo que hay aquí son lecturas (`--no-optional-locks`): la decisión de tocar o no
    la carpeta del usuario se toma ANTES de la primera orden que escribe. Un fetch —que
    es lo que hace `pull` incluso cuando fracasa— ya mueve FETCH_HEAD y las referencias
    remotas de un repositorio que no es nuestro, y el contrato dice que no se toca.
    """
    esperado = normalizar_remoto(url)
    if not esperado:
        return "no sé con qué origen compararla (falta `origen` en METODO.json)"
    if not (ruta / ".git").exists():
        return "no es un clon de git"
    r = git_leer(ruta, "rev-parse", "--is-inside-work-tree")
    if not (r and r.returncode == 0 and r.stdout.strip() == "true"):
        return "no es un árbol de trabajo de git"
    r = git_leer(ruta, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not (r and r.returncode == 0 and r.stdout.strip()):
        return "no está en una rama (HEAD desprendido)"
    rama = r.stdout.strip()
    r = git_leer(ruta, "config", "--get", "branch.{}.remote".format(rama))
    remoto = r.stdout.strip() if r and r.returncode == 0 else ""
    if not remoto:
        return "su rama {} no sigue a ningún remoto".format(rama)
    r = git_leer(ruta, "remote", "get-url", remoto)
    if not (r and r.returncode == 0 and r.stdout.strip()):
        return "no declara la URL de su remoto"
    if normalizar_remoto(r.stdout) != esperado:
        return "apunta a otro repositorio ({}), no al origen de este workspace".format(
            r.stdout.strip())
    r = git_leer(ruta, "status", "--porcelain")
    if r is None or r.returncode:
        return "no se puede leer su estado"
    if r.stdout.strip():
        return "tiene cambios sin guardar"
    r = git_leer(ruta, "rev-list", "--count", "@{upstream}..HEAD")
    if not (r and r.returncode == 0 and r.stdout.strip().isdigit()):
        return "no se puede comparar con su remoto"
    if r.stdout.strip() != "0":
        return "tiene {} commit(s) propios: su historia ha divergido".format(
            r.stdout.strip())
    return None


def pull_ff(ruta):
    r = git("-C", str(ruta), "pull", "--ff-only", "--quiet", timeout=TIMEOUT * 3)
    return bool(r and r.returncode == 0)


def buscar_en_disco():
    """Paseo acotado por las raíces habituales: subsegundo, con poda y tope de hondura."""
    casa = Path.home()
    raices = [casa] + [casa / nombre for nombre in RAICES_HABITUALES]
    vistas = set()
    for raiz in raices:
        if not raiz.is_dir():
            continue
        base = len(raiz.parts)
        for carpeta, hijas, _ficheros in os.walk(raiz, topdown=True):
            actual = Path(carpeta)
            if actual in vistas:
                hijas[:] = []
                continue
            vistas.add(actual)
            if len(actual.parts) - base >= PROFUNDIDAD:
                hijas[:] = []
            else:
                hijas[:] = [h for h in hijas if h not in SALTAR
                            and not h.startswith(".")]
            if es_herramienta(actual):
                hijas[:] = []
                yield actual


def clonar_en_temporal(url):
    destino = Path(tempfile.mkdtemp(prefix="ir-herramienta-")) / "ingenieria-requisitos"
    print(f"    Descargo la herramienta en una carpeta temporal: {destino}")
    r = git("clone", "--depth", "1", "--quiet", url, str(destino), timeout=TIMEOUT * 10)
    if r is None or r.returncode or not es_herramienta(destino):
        return None
    return destino


def candidata_anotada(workspace):
    anotada = preferencia(workspace, "herramienta")
    if not anotada:
        return None
    ruta = Path(anotada).expanduser()
    return ruta if es_herramienta(ruta) else None


def usar_copia_local(ruta, url):
    """¿Nos sirve esta copia? Solo si es del origen esperado y está impecable.

    Si no lo es, se dice por qué y se deja EXACTAMENTE como estaba: ni un fetch."""
    motivo = motivo_de_descarte(ruta, url)
    if motivo:
        print(f"    Dejo intacta tu copia de {ruta}: {motivo}.")
        return False
    if not pull_ff(ruta):
        print(f"    Dejo intacta tu copia de {ruta}: no admite `git pull --ff-only`.")
        return False
    print(f"    Uso tu copia de la herramienta, al día con git pull: {ruta}")
    return True


def asegurar_herramienta(workspace, url):
    """La herramienta utilizable, o None. Nunca repara la carpeta del usuario.

    Orden: la ruta anotada (si sigue siendo válida) → búsqueda acotada en el disco →
    clon nuevo en temporal. Una copia que no sea del origen esperado, esté sucia o haya
    divergido se descarta SIN tocarla —la comprobación es de solo lectura—: enderezarla
    sería tocar una carpeta que no es nuestra, y ejecutar el `visor/actualizar.py` de un
    repositorio que no es el origen del método sería ejecutar código de un desconocido.
    """
    anotada = candidata_anotada(workspace)
    descartadas = set()
    for ruta in ([anotada] if anotada else []):
        if usar_copia_local(ruta, url):
            return ruta
        descartadas.add(ruta.resolve())
    for ruta in buscar_en_disco():
        if ruta.resolve() in descartadas:
            continue
        if usar_copia_local(ruta, url):
            if not anotada:
                guardar_preferencia(workspace, "herramienta", str(ruta))
            return ruta
    if not url:
        print("    No sé de dónde descargarla: falta `origen` en METODO.json.")
        return None
    return clonar_en_temporal(url)


def registro_conocido(herramienta):
    """¿Esa copia de la herramienta sabe ya qué workspaces hay en esta máquina?

    El registro vive DENTRO de la herramienta, así que un clon recién descargado nace
    sin memoria: sin esto, "actualizar los demás" no encontraría ni uno."""
    if os.environ.get("INGENIERIA_REQUISITOS_REGISTRO"):
        return True
    return (herramienta / ".ingenieria-requisitos-local/registro.json").is_file()


def cmd_aplicar(workspace, args):
    url = origen(workspace)
    herramienta = asegurar_herramienta(workspace, url)
    if herramienta is None:
        print("    No he podido conseguir la herramienta de ingeniería de requisitos. "
              "No he tocado nada.")
        return 1
    actualizar = str(herramienta / "visor/actualizar.py")
    if args.todos and not registro_conocido(herramienta):
        print("    Primero busco tus workspaces en el disco (esta copia acaba de nacer).")
        subprocess.run([sys.executable, actualizar, "buscar"], cwd=str(herramienta))
    objetivo = ["--todos"] if args.todos else [str(workspace)]
    salida = subprocess.run(
        [sys.executable, actualizar, "aplicar", *objetivo],
        cwd=str(herramienta),
    ).returncode
    if salida == 0 and not args.todos:
        print(f"\n¿Actualizo también tus otros workspaces? → {ORDEN} aplicar --todos")
    return salida


def cmd_nunca(workspace, _args):
    guardar_preferencia(workspace, "preferencia", "nunca")
    print(f"Guardado en {PREFERENCIAS}: no volveré a avisar de actualizaciones del "
          f"método en {workspace}.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Comprueba y consigue la herramienta del método para este workspace.")
    sub = ap.add_subparsers(dest="orden", required=True)
    p_comprobar = sub.add_parser(
        "comprobar", help="¿hay método más nuevo publicado? No escribe nada y nunca bloquea")
    p_comprobar.set_defaults(func=cmd_comprobar)
    p_aplicar = sub.add_parser(
        "aplicar", help="consigue la herramienta y actualiza este workspace")
    p_aplicar.add_argument("--todos", action="store_true",
                           help="además, todos los workspaces registrados en esta máquina")
    p_aplicar.set_defaults(func=cmd_aplicar)
    p_nunca = sub.add_parser("nunca", help="no volver a avisar en este workspace")
    p_nunca.set_defaults(func=cmd_nunca)
    for parser in (p_comprobar, p_aplicar, p_nunca):
        parser.add_argument("ruta", nargs="?", default=str(WORKSPACE),
                            help="el workspace (por defecto, el que contiene este script)")
    args = ap.parse_args()
    return args.func(Path(args.ruta).expanduser().resolve(), args)


if __name__ == "__main__":
    sys.exit(main())
