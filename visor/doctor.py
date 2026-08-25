#!/usr/bin/env python3
"""doctor.py — primer arranque del clone: ¿funciona esta herramienta AQUÍ?

Uso: python3 visor/doctor.py

Recién clonado el repo, esto comprueba en un minuto lo que el RUNBOOK da por
supuesto: que el clone está entero, que hay git con identidad, que el ejemplo
valida con el Python de esta máquina, y qué piezas opcionales faltan (y qué
implica cada ausencia). Informa en cristiano y sale con 1 SOLO si el clone es
inutilizable; los avisos no bloquean.

Solo stdlib. Es el hermano del doctor de los workspaces
(plantilla/docs/00-metodo/scripts/doctor.py), que mira la máquina para el
ROADMAP; este mira la herramienta misma.
"""
import platform
import shutil
import os
import subprocess
import sys
from pathlib import Path

# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent      # visor/
RAIZ = BASE.parent                          # el clone


def which_sin_cwd(programa):
    """`shutil.which` pero SIN el directorio actual, que en Windows se antepone al PATH.

    Gemelo de workspace_paths.which_sin_cwd() por la misma razón que buscar_bash().
    """
    rutas = os.environ.get("PATH", os.defpath).split(os.pathsep)
    cwd = os.path.abspath(os.getcwd())
    limpias = [r for r in rutas if r and os.path.abspath(r) != cwd]
    return shutil.which(programa, path=os.pathsep.join(limpias))


def buscar_bash():
    """Ruta a un `bash` utilizable, o None. Gemelo de workspace_paths.buscar_bash().

    Se copia en vez de importarse A PROPÓSITO: este doctor tiene que seguir dando su
    diagnóstico en un clone INCOMPLETO —es media razón de existir— y un import de
    plantilla/ lo mataría justo en el caso que debe diagnosticar.

    Gemelo quiere decir gemelo: MISMO criterio, incluida la exclusión del cwd. Si
    divergieran, el doctor diría «OK Plataforma» con un `bash.exe` versionado en el
    repo de código mientras `unidad.orden_para_hook` lo rechaza — el diagnóstico
    mentiría justo sobre lo que existe para diagnosticar.
    `visor/tests/test_buscar_bash.py::LosDosGemelosDecidenIgualTest` ata las dos copias.

    En Windows el PATH lleva `Git\\cmd` (que solo tiene git.exe), no `Git\\bin`, así que
    `which("bash")` da None aunque Git for Windows SIEMPRE traiga bash. Si no está en el
    PATH se busca junto al git que sí se encontró: misma instalación, misma confianza.
    """
    encontrado = which_sin_cwd("bash")
    if encontrado:
        return encontrado
    git = which_sin_cwd("git")
    if not git or os.name != "nt":
        return None
    raiz_git = Path(git).resolve().parent.parent
    for candidato in (raiz_git / "bin" / "bash.exe", raiz_git / "usr" / "bin" / "bash.exe"):
        if candidato.is_file():
            return str(candidato)
    return None


def correr(*comando, cwd=None):
    """(ok, primera línea). Nunca lanza: lo ausente es un dato, no un error."""
    if shutil.which(comando[0]) is None:
        return False, ""
    try:
        p = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, check=False, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    salida = (p.stdout or p.stderr or "").strip().splitlines()
    return p.returncode == 0, (salida[0] if salida else "")


def revisar_python():
    version = platform.python_version()
    if sys.version_info < (3, 9):
        return "FAIL", f"{version} ({sys.executable})", (
            "demasiado viejo para los scripts del método; instala Python 3.11+")
    if sys.version_info < (3, 11):
        return "WARN", f"{version} ({sys.executable})", (
            "puede funcionar, pero el CI solo prueba 3.11 y 3.13")
    return "OK", f"{version} ({sys.executable})", ""


def revisar_clone():
    piezas = ("RUNBOOK.md", "AGENTS.md", "plantilla/docs/00-metodo/README.md",
              "visor/plantilla.html", "visor/ejemplo.json", "visor/esquema.json")
    ausentes = [pieza for pieza in piezas if not (RAIZ / pieza).is_file()]
    if ausentes:
        return "FAIL", "clone incompleto", (
            "faltan: " + ", ".join(ausentes) + " — ¿descarga parcial o zip a medias? "
            "Clona el repo entero con git")
    return "OK", f"todas las piezas en {RAIZ}", ""


def revisar_git():
    hay, version = correr("git", "--version")
    if not hay:
        return "FAIL", "no instalado", "sin git no hay bootstrap ni Modo D: instálalo"
    _, nombre = correr("git", "-C", str(RAIZ), "config", "--get", "user.name")
    _, correo = correr("git", "-C", str(RAIZ), "config", "--get", "user.email")
    if not (nombre and correo):
        return "WARN", f"{version} · SIN IDENTIDAD", (
            'el primer commit fallará: git config --global user.name "…" '
            'y user.email "…"')
    return "OK", f"{version} · {nombre} <{correo}>", ""


def revisar_ejemplo():
    ok, linea = correr(sys.executable, str(BASE / "validar.py"),
                       "--datos", str(BASE / "ejemplo.json"), cwd=RAIZ)
    if not ok:
        return "FAIL", linea or "la validación murió sin decir nada", (
            "el validador no funciona con este Python: los planos de tus proyectos "
            "tampoco validarán")
    return "OK", "visor/ejemplo.json valida con este Python", ""


def revisar_escritura_local():
    # El registro puede vivir fuera del clone (INGENIERIA_REQUISITOS_REGISTRO), así
    # que un clone en ruta de solo lectura es perfectamente usable: esto AVISA, no
    # bloquea, y comprueba el destino real del registro, no siempre el del clone.
    env = os.environ.get("INGENIERIA_REQUISITOS_REGISTRO")
    destino = Path(env).expanduser().parent if env else RAIZ / ".ingenieria-requisitos-local"
    try:
        destino.mkdir(parents=True, exist_ok=True)
        prueba = destino / ".doctor-escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
    except OSError as exc:
        return "WARN", f"no puedo escribir el registro en {destino} ({exc})", (
            "si el clone es de solo lectura, apunta el registro fuera con "
            "INGENIERIA_REQUISITOS_REGISTRO=/ruta/escribible/registro.json")
    return "OK", f"registro escribible ({destino})", ""


def revisar_playwright():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "WARN", "no instalado", (
            "solo hace falta para el E2E del visor (validar_web.py): "
            "pip install -r requirements-dev.txt && playwright install chromium")
    return "OK", "instalado (E2E del visor disponible)", ""


def revisar_gh():
    hay, version = correr("gh", "--version")
    if not hay:
        return "WARN", "no instalado", (
            "sin gh no hay repos en GitHub desde bootstrap; todo lo demás funciona")
    autenticado, _ = correr("gh", "auth", "status")
    if not autenticado:
        return "WARN", f"{version} · sin sesión", "`gh auth login` si quieres GitHub"
    return "OK", version, ""


def rutas_largas_activas():
    """¿Windows tiene levantado el límite de 260 caracteres de MAX_PATH?

    Solo se LEE el registro; jamás se toca: activarlo exige administrador y es un
    cambio del sistema del usuario, no nuestro. Se avisa y decide él.
    """
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\FileSystem") as clave:
            valor, _ = winreg.QueryValueEx(clave, "LongPathsEnabled")
        return bool(valor)
    except (ImportError, OSError):
        return False        # ausente = desactivado, que es el defecto de Windows


def revisar_plataforma():
    # El lanzador (ejecucion.py) no exige sandbox de sistema operativo en ninguna
    # plataforma desde la unidad 012 (bug 013): no hay nada de sandbox que comprobar
    # ni recetar aquí, en Windows ni en ningún otro sitio.
    if sys.platform == "win32":
        avisos = []
        if not rutas_largas_activas():
            avisos.append("rutas largas desactivadas en Windows: git ya las sortea en los "
                          "repos del método, pero npm o un compilador seguirán topando en "
                          "260 caracteres (se activa con LongPathsEnabled=1)")
        if buscar_bash() is None:
            avisos.append("sin bash: los hooks y gates en shell no correrán "
                          "(bash viene con Git for Windows)")
        if shutil.which("python3") is None:
            avisos.append("aquí `python3` no existe: donde el manual diga python3, "
                          "escribe `python`")
        if avisos:
            return "WARN", f"Windows {platform.release()}", " · ".join(avisos)
        return "OK", f"Windows {platform.release()}", ""

    return "OK", f"{platform.system()} {platform.release()}", ""


REVISIONES = (
    ("El clone", revisar_clone),
    ("Python", revisar_python),
    ("git", revisar_git),
    ("El ejemplo", revisar_ejemplo),
    ("Escritura local", revisar_escritura_local),
    ("Playwright", revisar_playwright),
    ("gh (GitHub)", revisar_gh),
    ("Plataforma", revisar_plataforma),
)


def main():
    print("== Doctor del primer arranque ==")
    filas = [(nombre, *revision()) for nombre, revision in REVISIONES]
    ancho = max(len(f[0]) for f in filas)
    peor = 0
    for nombre, estado, detalle, consecuencia in filas:
        print(f"  {estado.ljust(4)} {nombre.ljust(ancho)}  {detalle}")
        if consecuencia:
            print(f"       {' ' * ancho}→ {consecuencia}")
        peor = max(peor, {"OK": 0, "WARN": 0, "FAIL": 1}[estado])
    if peor:
        print("\nHay algo roto de verdad (FAIL): arréglalo antes de empezar.")
    else:
        print("\nTodo lo imprescindible en verde. Abre tu agente aquí y di «hola».")
    return peor


if __name__ == "__main__":
    sys.exit(main())
