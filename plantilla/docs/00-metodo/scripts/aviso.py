#!/usr/bin/env python3
"""Aviso sonoro: cuando el agente necesita a la persona, suena.

Lo llaman dos hooks de Claude Code que el bootstrap siembra en cada workspace:

    Notification -> aviso.py notificacion     pide un permiso, o lleva rato esperando
    Stop         -> aviso.py fin-de-turno     ha terminado de trabajar

Regla dura, la misma del canario: **este script no rompe ni retrasa un turno jamás**. Sin
reproductor, sin fichero de sonido, sin tarjeta de audio o con el `personalidad.md` a
medio escribir -> sale 0 y no escribe nada. Un hook que falla molesta más que el silencio.
Por eso el reproductor se lanza y se suelta (no se espera a que acabe): un clip de dos
segundos no puede añadirse al final de cada turno. El corte, si hiciera falta, lo pone el
`timeout` del hook.

El interruptor vive en `.claude/personalidad.md` —preferencia del dueño, fuera de git,
que ni el Modo D ni una actualización pisan— con una línea:

    sonido: no          calla
    sonido: sistema     el sonido de notificación del sistema  (lo de serie)
    sonido: toasty      .claude/sonidos/toasty.(wav|aiff|mp3|…)
    sonido: /ruta/a/lo/que/sea.wav

Los presets NO viajan en la plantilla: los clips de Mortal Kombat o de Age of Empires
tienen dueño. Cada cual pone los suyos en `.claude/sonidos/`. Si el preset no está, suena
el del sistema y se dice UNA vez —hasta que se cambie de preferencia—: repetirlo cada
turno sería el ruido que este script intenta evitar.

En Codex CLI no hay hooks, así que allí esto no suena: es una limitación declarada del
harness, no un fallo (`detectores.md`).

Solo stdlib.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

# Este script vive en docs/00-metodo/scripts/, igual que canario.py: parents[3] es la raíz
# del meta-repo sea cual sea el directorio de trabajo.
RAIZ = Path(__file__).resolve().parents[3]

PERSONALIDAD = ".claude/personalidad.md"
CARPETA_SONIDOS = ".claude/sonidos"
# Dónde se apunta que ya se dijo lo del preset que falta. En `.claude/` como el resto de
# preferencias locales: gitignorado, y nadie lo reparte.
MEMORIA = ".claude/aviso.json"

EVENTOS = ("notificacion", "fin-de-turno")

# Extensiones que se buscan para un preset, en orden de preferencia. `.wav` primero
# porque es la única que entiende TODO reproductor de las tres plataformas.
EXTENSIONES = (".wav", ".aiff", ".aif", ".mp3", ".oga", ".ogg", ".m4a", ".flac")

# El sonido de notificación de cada sistema, por orden: el primero que exista. Son rutas
# de serie del SO, no ficheros que reparta el método.
SONIDOS_DEL_SISTEMA = {
    "darwin": ("/System/Library/Sounds/Ping.aiff",
               "/System/Library/Sounds/Glass.aiff",
               "/System/Library/Sounds/Submarine.aiff"),
    "linux": ("/usr/share/sounds/freedesktop/stereo/complete.oga",
              "/usr/share/sounds/freedesktop/stereo/message.oga",
              "/usr/share/sounds/freedesktop/stereo/bell.oga",
              "/usr/share/sounds/alsa/Front_Center.wav",
              "/usr/share/sounds/sound-icons/prompt.wav"),
    "windows": (r"C:\Windows\Media\Windows Notify System Generic.wav",
                r"C:\Windows\Media\Windows Notify.wav",
                r"C:\Windows\Media\notify.wav",
                r"C:\Windows\Media\ding.wav"),
}


def familia(plataforma=None):
    """La familia de sistema a la que pertenece `sys.platform`, o None si no la conozco.

    `sys.platform` da `linux`, `darwin`, `win32`, `cygwin`, `freebsd14`… Se normaliza aquí
    para que el resto del script hable de tres familias y no de una lista de cadenas.
    """
    nombre = (plataforma if plataforma is not None else sys.platform).lower()
    if nombre.startswith("darwin"):
        return "darwin"
    if nombre.startswith("win") or nombre.startswith("cygwin"):
        return "windows"
    if nombre.startswith(("linux", "freebsd", "openbsd", "netbsd", "sunos", "gnu")):
        return "linux"
    return None


def sonido_del_sistema(plataforma=None, existe=os.path.exists):
    """El primer sonido de notificación de serie que exista en esta máquina, o None.

    Devolver None es un resultado normal, no un error: un Linux de servidor sin
    `/usr/share/sounds` no tiene nada que sonar, y entonces no suena nada.
    """
    for ruta in SONIDOS_DEL_SISTEMA.get(familia(plataforma) or "", ()):
        if existe(ruta):
            return ruta
    return None


def orden_de_reproduccion(ruta, plataforma=None, which=None):
    """La orden concreta que hace sonar `ruta` en esta plataforma, o None si no hay con qué.

    `which` se inyecta para poder probar las tres plataformas desde una sola: lo que se
    verifica es la ELECCIÓN del reproductor, nunca que suene (en CI no hay audio).
    """
    which = which or shutil.which
    ruta = str(ruta)
    casa = familia(plataforma)
    extension = os.path.splitext(ruta)[1].lower()

    if casa == "darwin":
        programa = which("afplay")
        return [programa, ruta] if programa else None

    if casa == "windows":
        # SoundPlayer solo entiende WAV; para lo demás, el reproductor por defecto del
        # sistema vía Start-Process, que no espera y no abre ventana para un audio.
        programa = which("powershell") or which("pwsh")
        if not programa:
            return None
        escapada = ruta.replace("'", "''")
        if extension == ".wav":
            guion = f"(New-Object Media.SoundPlayer '{escapada}').PlaySync()"
        else:
            guion = f"Start-Process -WindowStyle Hidden -FilePath '{escapada}'"
        return [programa, "-NoProfile", "-NonInteractive", "-Command", guion]

    if casa == "linux":
        # `aplay` va el último y solo con WAV: mandarle un .oga no suena y ensucia stderr.
        candidatos = (
            ("paplay", lambda p: [p, ruta], None),
            ("pw-play", lambda p: [p, ruta], None),
            ("ffplay", lambda p: [p, "-nodisp", "-autoexit", "-loglevel", "quiet", ruta], None),
            ("aplay", lambda p: [p, "-q", ruta], (".wav",)),
        )
        for nombre, construir, solo in candidatos:
            if solo and extension not in solo:
                continue
            programa = which(nombre)
            if programa:
                return construir(programa)
    return None


def preferencia(raiz):
    """El valor de `sonido:` en `.claude/personalidad.md`; `sistema` si no dice nada.

    Solo cuenta una línea de prosa que EMPIECE por la clave y que esté fuera de un bloque
    de código: el propio placeholder documenta la clave con ejemplos, y si los ejemplos
    contaran, todo workspace nuevo nacería con el sonido del ejemplo. Un fichero ilegible
    equivale a no haber dicho nada.
    """
    fichero = Path(raiz) / PERSONALIDAD
    try:
        texto = fichero.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "sistema"
    dentro_de_codigo = False
    for linea in texto.splitlines():
        pelada = linea.strip()
        if pelada.startswith("```") or pelada.startswith("~~~"):
            dentro_de_codigo = not dentro_de_codigo
            continue
        if dentro_de_codigo or not pelada.lower().startswith("sonido:"):
            continue
        valor = pelada.split(":", 1)[1].strip().strip("`\"'").strip()
        if valor:
            return valor
    return "sistema"


def _parece_una_ruta(valor):
    """¿El usuario ha escrito una ruta, o el nombre de un preset?"""
    return (valor.startswith("~") or valor.startswith(".")
            or "/" in valor or "\\" in valor
            or os.path.splitext(valor)[1].lower() in EXTENSIONES)


def _fichero_del_preset(raiz, nombre, existe):
    """`.claude/sonidos/<nombre>.<ext>`, con la primera extensión que exista."""
    carpeta = Path(raiz) / CARPETA_SONIDOS
    for extension in EXTENSIONES:
        candidato = carpeta / (nombre + extension)
        if existe(str(candidato)):
            return str(candidato)
    return None


def _ya_se_dijo(raiz, valor):
    """¿Ya se avisó de que ESTE preset falta? Cambiar de preferencia rearma el recado."""
    try:
        memoria = json.loads((Path(raiz) / MEMORIA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(memoria, dict) and memoria.get("dicho") == valor


def _apuntar_que_se_dijo(raiz, valor):
    """Deja constancia del recado. Si no se puede escribir, se repetirá: no es grave."""
    fichero = Path(raiz) / MEMORIA
    try:
        fichero.parent.mkdir(parents=True, exist_ok=True)
        fichero.write_text(json.dumps({"dicho": valor}, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    except OSError:
        pass


def resolver(raiz, plataforma=None, existe=os.path.exists):
    """Qué fichero suena y qué hay que contarle al usuario.

    Devuelve `(ruta, recado)`. `ruta` None significa silencio querido (`sonido: no`) o que
    en esta máquina no hay nada que sonar. `recado` es el aviso de una sola vez cuando el
    preset o la ruta elegidos no existen y se cae al sonido del sistema.
    """
    raiz = Path(raiz)
    valor = preferencia(raiz)
    if valor.lower() in ("no", "off", "ninguno", "silencio"):
        return None, None
    if valor.lower() in ("sistema", "si", "sí", "default", "defecto"):
        return sonido_del_sistema(plataforma, existe), None

    if _parece_una_ruta(valor):
        elegido = Path(os.path.expanduser(valor))
        if not elegido.is_absolute():
            elegido = raiz / elegido
        elegido = str(elegido)
        if existe(elegido):
            return elegido, None
    else:
        elegido = _fichero_del_preset(raiz, valor, existe)
        if elegido:
            return elegido, None

    respaldo = sonido_del_sistema(plataforma, existe)
    if _ya_se_dijo(raiz, valor):
        return respaldo, None
    _apuntar_que_se_dijo(raiz, valor)
    return respaldo, (
        f"Aviso sonoro: `sonido: {valor}` está puesto en .claude/personalidad.md pero no "
        f"encuentro el fichero. Déjalo en .claude/sonidos/{valor}.wav (o pon la ruta "
        f"entera) y sonará; mientras tanto suena el del sistema. Esto se dice una sola vez."
    )


def lanzar(orden):
    """Suelta el reproductor y sigue: el turno no espera a que acabe el sonido."""
    try:
        subprocess.Popen(orden, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def sonar(raiz, plataforma=None, reproducir=True):
    """El trabajo completo de un evento: elegir, sonar y devolver el recado si lo hay."""
    ruta, recado = resolver(raiz, plataforma)
    if ruta and reproducir:
        orden = orden_de_reproduccion(ruta, plataforma)
        if orden:
            lanzar(orden)
    return ruta, recado


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Aviso sonoro cuando el agente necesita a la persona.")
    parser.add_argument("evento", nargs="?", default="fin-de-turno",
                        help="notificacion | fin-de-turno (lo pasa el hook; solo informa)")
    parser.add_argument("--workspace", default=None, help="raíz del meta-repo")
    parser.add_argument("--no-reproducir", action="store_true",
                        help="elige el sonido pero no lo lanza (para probar)")
    parser.add_argument("--diagnostico", action="store_true",
                        help="cuenta qué sonaría en esta máquina y por qué")
    args = parser.parse_args(argv)

    raiz = Path(args.workspace or RAIZ)

    if args.diagnostico:
        # Apagado a mano y "aquí no hay nada que sonar" son dos silencios MUY distintos:
        # confundirlos es media hora buscando un reproductor que nadie había pedido.
        gusto = preferencia(raiz)
        apagado = gusto.lower() in ("no", "off", "ninguno", "silencio")
        ruta, _ = resolver(raiz)
        orden = orden_de_reproduccion(ruta) if ruta else None
        print(f"evento:      {args.evento}")
        print(f"preferencia: {gusto}   ({raiz / PERSONALIDAD})")
        if apagado:
            print("sonido:      apagado a mano (`sonido: no`); pon `sonido: sistema` para oírlo")
        else:
            print(f"sonido:      {ruta or 'nada que sonar en esta máquina'}")
            print(f"reproductor: {' '.join(orden) if orden else 'ninguno instalado'}")
        print("prueba:      python3 docs/00-metodo/scripts/aviso.py fin-de-turno")
        return 0

    _, recado = sonar(raiz, reproducir=not args.no_reproducir)
    if recado:
        # Mismo formato que el canario: Claude Code enseña `systemMessage` al usuario.
        # Sin recado no se escribe NADA: el silencio es la salida normal de este hook.
        print(json.dumps({"continue": True, "systemMessage": recado}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                   # noqa: BLE001 — un aviso JAMÁS rompe un turno
        sys.exit(0)
