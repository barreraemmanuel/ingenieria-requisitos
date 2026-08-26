#!/usr/bin/env python3
"""doctor.py — qué hay REALMENTE instalado en esta máquina, ANTES de prometer nada.

Uso: python3 docs/00-metodo/scripts/doctor.py [--escribir]
     python3 docs/00-metodo/scripts/doctor.py instalar <docker|wsl> [--simular-ausente]
Se ejecuta: al final de `setup.py` (primer arranque) y cuando la fase 4 vaya a decidir
tecnología. `--escribir` deja la foto en docs/conocimiento/entorno-de-esta-maquina.md.

Por qué existe: la fase 4 elige el entorno de desarrollo (contenedores o no, dónde corren los
tests, cómo se publica) apoyándose en supuestos sobre la máquina que nadie había comprobado.
Escribir "se desarrolla con Docker" sin saber si hay Docker es la forma más cara de
descubrirlo: se paga con un ROADMAP corregido, un ADR y una unidad reespecificada a mitad.
REGLA (runbooks/planificacion.md): el ROADMAP no fija una herramienta que el doctor no haya
visto en verde.

Esto INFORMA, no bloquea: una máquina sin Docker no es una máquina inválida, es una máquina
que va por el peldaño mínimo. El diagnóstico sale siempre con código 0.

El subcomando `instalar` (unidad 098) es la ÚNICA parte que muta la máquina, y por eso es la
única que puede salir con 1: primero ENSEÑA (qué, de dónde —fuente oficial—, cuánto ocupa, qué
cambia, cómo se desinstala) y pide un «sí» tecleado por una persona; sin ese «sí» no ejecuta
nada. Producción y la máquina del usuario son LECTURA por defecto (regla de oro de AGENTS.md):
instalar software pesado es una mutación y exige autorización explícita. No instala en remoto
—el VPS lo prepara `plantillas/vps/servidor-preparar.sh` con su propio aviso— y el catálogo es
cerrado: docker y wsl, lo que hace falta para desplegar. Todo lo demás sigue siendo diagnóstico.
Solo stdlib, y agnóstico del lenguaje del proyecto.
"""
import argparse
import datetime
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Windows: con la salida en un pipe (setup.py) el encoding por defecto es cp1252 y cualquier
# carácter fuera de él mataría el informe con UnicodeEncodeError. Se fuerza UTF-8.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parents[3]
HOY = datetime.date.today().isoformat()
YO = "python3 docs/00-metodo/scripts/doctor.py"


def correr(*comando):
    """(ok, primera línea de salida). Nunca lanza: una herramienta ausente es un dato, no un error."""
    if shutil.which(comando[0]) is None:
        return False, ""
    try:
        p = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    salida = (p.stdout or p.stderr or "").strip().splitlines()
    return p.returncode == 0, (salida[0] if salida else "")


def revisar_python():
    return "sí", f"{platform.python_version()} ({sys.executable})", ""


def revisar_git():
    hay, version = correr("git", "--version")
    if not hay:
        return "NO", "no instalado", "sin git no hay método: instálalo antes de nada"
    _, nombre = correr("git", "-C", str(RAIZ), "config", "--get", "user.name")
    _, correo = correr("git", "-C", str(RAIZ), "config", "--get", "user.email")
    if not (nombre and correo):
        return ("a medias", f"{version} · SIN IDENTIDAD",
                'el primer commit fallará con "Author identity unknown": '
                'git config --global user.name "…" y user.email "…"')
    return "sí", f"{version} · {nombre} <{correo}>", ""


def revisar_gh():
    hay, version = correr("gh", "--version")
    if not hay:
        return ("NO", "no instalado",
                "no hay pull requests: el cierre va por el CAMINO B de runbooks/cierre.md "
                "(revisión sobre el diff y merge local del padre)")
    autenticado, _ = correr("gh", "auth", "status")
    if not autenticado:
        return ("a medias", f"{version} · sin sesión",
                "`gh auth login` o, si no vas a usar GitHub, camino B de runbooks/cierre.md")
    return "sí", version, ""


def revisar_docker():
    hay, version = correr("docker", "--version")
    if not hay:
        return ("NO", "no instalado",
                "el ROADMAP NO puede prometer contenedores: se desarrolla y se prueba en el "
                "peldaño mínimo (entorno local del lenguaje). Ver 01-constitucion/bias.md. "
                "¿Lo necesitas? " + YO + " instalar docker  (te enseña qué instala y pregunta "
                "antes de tocar nada)")
    vivo, _ = correr("docker", "info")
    if not vivo:
        return ("a medias", f"{version} · demonio parado",
                "arranca Docker Desktop (o el servicio) antes de contar con él")
    return "sí", version, ""


def revisar_node():
    hay, version = correr("node", "--version")
    if not hay:
        return "NO", "no instalado", "solo importa si el stack lo pide"
    _, npm = correr("npm", "--version")
    return "sí", f"{version} · npm {npm or '?'}", ""


REVISIONES = (
    ("Python", revisar_python),
    ("git", revisar_git),
    ("gh (GitHub)", revisar_gh),
    ("Docker", revisar_docker),
    ("Node", revisar_node),
)


def informe():
    filas = [(nombre, *revision()) for nombre, revision in REVISIONES]
    ancho = max(len(f[0]) for f in filas)
    lineas = [f"# Entorno de esta máquina ({platform.system()} {platform.release()})",
              f"", f"Comprobado el {HOY} con `docs/00-metodo/scripts/doctor.py`.", ""]
    lineas.append("| Herramienta | ¿Está? | Qué hay | Qué implica |")
    lineas.append("|---|---|---|---|")
    for nombre, estado, detalle, consecuencia in filas:
        lineas.append(f"| {nombre} | {estado} | {detalle} | {consecuencia or '—'} |")
    lineas += ["", "REGLA: el ROADMAP no fija una herramienta que no aparezca aquí en verde",
               "(`runbooks/planificacion.md`). Esta foto caduca: se rehace, no se edita a mano."]
    pantalla = ["", "== Entorno de esta máquina =="]
    for nombre, estado, detalle, consecuencia in filas:
        marca = {"sí": "  OK  ", "a medias": "  WARN", "NO": "  FALTA"}.get(estado, "  ?   ")
        pantalla.append(f"{marca} {nombre.ljust(ancho)}  {detalle}")
        if consecuencia:
            pantalla.append(f"{' ' * (ancho + 9)}→ {consecuencia}")
    return "\n".join(pantalla), "\n".join(lineas) + "\n"


# --------------------------------------------------------------------------- #
#  `instalar`: lo único que muta la máquina — enseña, pregunta y solo entonces  #
# --------------------------------------------------------------------------- #

# Catálogo CERRADO a propósito: solo lo que hace falta para desplegar y lo que hoy deja al
# usuario tirado si falta. git, python o node siguen siendo diagnóstico (fuera de alcance):
# un instalador que crece sin freno acaba siendo un gestor de paquetes peor que el del SO.
# Cada receta es la OFICIAL de su plataforma, con la URL de la que sale, y se ejecuta por
# `subprocess` SIN shell (nada de tuberías: `curl … | sh` no se puede auditar ni parar).
CATALOGO = {
    "docker": {
        "nombre": "Docker",
        "para_que": "construir y correr la aplicación en contenedores (y desplegarla)",
        "comprobar": ("docker", "--version"),
        "sistemas": ("Darwin", "Linux", "Windows"),
    },
    "wsl": {
        "nombre": "WSL (Subsistema de Windows para Linux)",
        "para_que": "tener un Linux dentro de Windows, que es de lo que vive Docker Desktop",
        "comprobar": ("wsl", "--status"),
        "sistemas": ("Windows",),
    },
}

# Fuentes consultadas el 2026-08-27. Los tamaños son APROXIMADOS y envejecen: se dicen para
# que el usuario decida con una idea del coste, no como promesa.
RECETAS = {
    ("docker", "Darwin"): {
        "que": "Docker Desktop para macOS (incluye el motor, la CLI y Compose)",
        "url": "https://docs.docker.com/desktop/setup/install/mac-install/",
        "tamano": "~1,5 GB de descarga, ~2,5 GB en disco",
        "cambios": ("instala Docker Desktop en /Applications y una máquina virtual ligera "
                    "que arranca con tu sesión y consume memoria mientras esté encendida"),
        "desinstalar": "brew uninstall --cask docker",
        "pasos": [["brew", "install", "--cask", "docker"]],
        "requiere": "brew",
    },
    ("docker", "Linux"): {
        "que": "Docker Engine + Compose desde el script oficial de Docker",
        "url": "https://docs.docker.com/engine/install/",
        "tamano": "~500 MB en disco",
        "cambios": ("añade el repositorio oficial de Docker y su clave a tu gestor de "
                    "paquetes (apt o dnf), instala docker-ce y deja el servicio arrancado; "
                    "pide tu contraseña de administrador (sudo)"),
        "desinstalar": ("sudo apt-get purge docker-ce docker-ce-cli containerd.io   "
                        "(o sudo dnf remove docker-ce)"),
        # Dos órdenes, ninguna con shell: primero se BAJA el script oficial a .runtime, donde
        # se puede leer antes de correrlo; después se ejecuta. `curl … | sh` haría lo mismo
        # sin dejar ver nunca lo que se ejecutó.
        "pasos": [["curl", "-fsSL", "https://get.docker.com", "-o", "@GUION@"],
                  ["sudo", "sh", "@GUION@"]],
    },
    ("docker", "Windows"): {
        "que": "Docker Desktop para Windows (necesita WSL activado)",
        "url": "https://docs.docker.com/desktop/setup/install/windows-install/",
        "tamano": "~1,5 GB de descarga, ~3 GB en disco",
        "cambios": ("instala Docker Desktop, se apoya en WSL2 y puede pedirte reiniciar el "
                    "ordenador al terminar"),
        "desinstalar": "winget uninstall Docker.DockerDesktop",
        "pasos": [["winget", "install", "--id", "Docker.DockerDesktop", "-e",
                   "--accept-package-agreements", "--accept-source-agreements"]],
        "requiere": "winget",
    },
    ("wsl", "Windows"): {
        "que": "WSL2 con su distribución Ubuntu por defecto",
        "url": "https://learn.microsoft.com/windows/wsl/install",
        "tamano": "~1,5 GB en disco",
        "cambios": ("activa la característica WSL de Windows, instala su kernel y una "
                    "Ubuntu; casi siempre pide reiniciar el ordenador"),
        "desinstalar": ("wsl --unregister Ubuntu  y luego quitar «Subsistema de Windows "
                        "para Linux» en «Activar o desactivar las características de Windows»"),
        "pasos": [["wsl", "--install"]],
    },
}

# Lo que `instalar` acepta. `--host` y compañía NO están, y no es un olvido (R5): esta orden
# solo actúa en LOCAL. Un VPS se prepara con `plantillas/vps/servidor-preparar.sh`, que lleva
# su propio aviso y su propia idempotencia.
BANDERAS_DE_INSTALAR = ("--simular-ausente", "--si", "--ayuda", "-h", "--help")
BANDERAS_REMOTAS = ("--host", "--remoto", "--ssh", "--servidor", "--vps")

AYUDA_INSTALAR = f"""Uso: {YO} instalar <docker|wsl> [--simular-ausente]

  Enseña qué se va a instalar, de dónde, cuánto ocupa, qué cambia en tu máquina y cómo se
  desinstala; y solo instala si contestas «sí». Solo en ESTA máquina.

  --simular-ausente   hace como si la herramienta no estuviera, para ver el aviso sin
                      desinstalar nada (es la forma de probarlo)."""


def plataforma():
    """Envuelta para que los tests puedan fingir otro SO sin tocar `platform`."""
    return platform.system()


def hay_tty():
    """¿Hay una persona delante? Sin terminal no se pide permiso a nadie (R4)."""
    try:
        return sys.stdin.isatty()
    except (ValueError, AttributeError):
        return False


def tiene(nombre):
    return shutil.which(nombre) is not None


def es_un_si(texto):
    """Solo un «sí» de verdad. «y», «yes» o un enter no son consentimiento."""
    limpio = (texto or "").strip().lower()
    return limpio in ("sí", "si")


def esta_instalado(clave):
    hay, _ = correr(*CATALOGO[clave]["comprobar"])
    return hay


def verificar(clave):
    """(ok, lo que dijo la herramienta) después de instalar."""
    return correr(*CATALOGO[clave]["comprobar"])


def receta_de(clave, sistema):
    """La receta oficial para ese SO, o None si aquí no hay camino automático."""
    receta = RECETAS.get((clave, sistema))
    if receta is None:
        return None
    requiere = receta.get("requiere")
    if requiere and not tiene(requiere):
        return None
    guion = str(RAIZ / ".runtime" / "doctor" / "get-docker.sh")
    pasos = [[trozo.replace("@GUION@", guion) for trozo in paso]
             for paso in receta["pasos"]]
    return dict(receta, pasos=pasos)


def texto_aviso(clave, receta, sistema):
    paquete = CATALOGO[clave]
    ordenes = "\n".join(f"      $ {' '.join(paso)}" for paso in receta["pasos"])
    return f"""
== Instalar {paquete['nombre']} en esta máquina ({sistema}) ==

  Para qué             {paquete['para_que']}
  Qué se instala       {receta['que']}
  De dónde (oficial)   {receta['url']}
  Tamaño aproximado    {receta['tamano']}
  Qué cambia en tu máquina
      {receta['cambios']}
  Cómo se desinstala   {receta['desinstalar']}

  Esto es lo que se ejecutaría, tal cual:
{ordenes}

  Nada de esto se ha hecho todavía."""


def instalar_paquete(pasos):
    """Ejecuta la receta. SIN shell y sin capturar: el usuario ve la instalación al vivo.

    Es el punto que los tests sustituyen por un doble: la suite no instala nunca nada."""
    for paso in pasos:
        try:
            codigo = subprocess.run(paso, check=False).returncode
        except OSError as error:
            return 1, f"no se pudo ejecutar {' '.join(paso)}: {error}"
        if codigo != 0:
            return codigo, f"falló: {' '.join(paso)}"
    return 0, ""


def escribir_recibo(datos):
    """El rastro de lo que pasó, en .runtime/doctor/ (regla 12: evidencia, no afirmación)."""
    carpeta = RAIZ / ".runtime" / "doctor"
    carpeta.mkdir(parents=True, exist_ok=True)
    sello = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destino = carpeta / f"{sello}-instalar-{datos['paquete']}.json"
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    return destino


def pedir_confirmacion():
    """El «sí» tecleado. Solo se llama con TTY comprobado."""
    return es_un_si(input("  ¿Lo instalo? Escribe «sí» para seguir, cualquier otra cosa "
                          "para dejarlo: "))


def rechazar(mensaje):
    """Un FAIL con su SALIDA DENTRO del mismo mensaje.

    No es cosmética: un rechazo que no nombra la continuación le cuesta un turno entero a
    quien lo recibe (`lint_salidas.py`), y ese guardián lee el mensaje del rechazo, no lo que
    venga en otro argumento. Aquí el comando va escrito entero y literal, sin variables, para
    que se pueda copiar de la pantalla y encontrar con un grep."""
    print(f"\n  FAIL {mensaje}")
    return 1


def orden_instalar(argv):
    clave = None
    simular_ausente = False
    con_bandera_si = False
    for arg in argv:
        if arg in ("-h", "--help", "--ayuda"):
            print(AYUDA_INSTALAR)
            return 0
        if arg == "--simular-ausente":
            simular_ausente = True
        elif arg == "--si":
            con_bandera_si = True
        elif arg.split("=")[0] in BANDERAS_REMOTAS:
            return rechazar(
                "`instalar` no toca máquinas remotas: solo instala en ESTA\n"
                "       SALIDA: para dejar un VPS listo (Docker incluido, y con su propio "
                "aviso): python3 docs/00-metodo/scripts/vps.py servidor preparar")
        elif arg.startswith("-"):
            return rechazar(
                f"no conozco la opción {arg}\n"
                "       SALIDA: python3 docs/00-metodo/scripts/doctor.py instalar --ayuda")
        elif clave is None:
            clave = arg
        else:
            return rechazar(
                f"sobra «{arg}»: se instala de uno en uno\n"
                "       SALIDA: python3 docs/00-metodo/scripts/doctor.py instalar "
                f"{clave}")

    if clave not in CATALOGO:
        return rechazar(
            f"«{clave or 'nada'}» no está en el catálogo: solo docker y wsl "
            "(lo demás el doctor lo diagnostica, no lo instala)\n"
            "       SALIDA: python3 docs/00-metodo/scripts/doctor.py instalar docker   ·   "
            "python3 docs/00-metodo/scripts/doctor.py instalar wsl")

    sistema = plataforma()
    paquete = CATALOGO[clave]
    if sistema not in paquete["sistemas"]:
        return rechazar(
            f"{paquete['nombre']} solo existe en Windows: en {sistema} no hace falta\n"
            "       SALIDA: si lo que necesitas es Docker: "
            "python3 docs/00-metodo/scripts/doctor.py instalar docker")

    if not simular_ausente and esta_instalado(clave):
        _, version = correr(*paquete["comprobar"])
        print(f"\n  OK   {paquete['nombre']} ya está: nada que hacer ({version})")
        return 0

    receta = receta_de(clave, sistema)
    if receta is None:
        manual = RECETAS.get((clave, sistema))
        url = manual["url"] if manual else "https://docs.docker.com/get-started/get-docker/"
        falta = (manual or {}).get("requiere")
        return rechazar(
            f"en {sistema} no tengo receta automática para {paquete['nombre']}"
            + (f" sin {falta}" if falta else "")
            + f"\n       SALIDA: instálalo desde la página oficial ({url}) y compruébalo "
              "con: python3 docs/00-metodo/scripts/doctor.py")

    print(texto_aviso(clave, receta, sistema))
    recibo = {"fecha": datetime.datetime.now().isoformat(timespec="seconds"),
              "paquete": clave, "sistema": sistema, "receta": receta["pasos"],
              "fuente": receta["url"]}

    if con_bandera_si:
        recibo["resultado"] = "sin permiso"
        escribir_recibo(recibo)
        return rechazar(
            "`--si` no vale como permiso: instalar cambia TU máquina y lo autoriza una "
            "persona escribiéndolo\n"
            "       SALIDA: corre esto en una terminal y contesta «sí»: "
            f"python3 docs/00-metodo/scripts/doctor.py instalar {clave}")

    if not hay_tty():
        recibo["resultado"] = "sin permiso"
        escribir_recibo(recibo)
        return rechazar(
            "no hay nadie delante (la entrada no es una terminal) y esto no se instala solo\n"
            "       SALIDA: abre una terminal y corre: "
            f"python3 docs/00-metodo/scripts/doctor.py instalar {clave}")

    if not pedir_confirmacion():
        recibo["resultado"] = "sin permiso"
        destino = escribir_recibo(recibo)
        # No es un fallo del usuario, es su decisión: se le deja el camino escrito, no una
        # regañina. Sale con 1 porque la herramienta SIGUE sin estar, y quien llame a esto
        # (un runbook, otro script) tiene que enterarse.
        print(f"\n  OK   no se ha instalado nada: dijiste que no.")
        print(f"       la página oficial, por si lo quieres hacer a mano: {receta['url']}")
        print(f"       SALIDA: cuando quieras: {YO} instalar {clave}")
        print(f"       queda escrito en {destino}")
        return 1

    # La receta de Linux baja el script oficial a .runtime/doctor/: la carpeta tiene que
    # existir antes, o el `curl -o` falla por una tontería a mitad de instalación.
    (RAIZ / ".runtime" / "doctor").mkdir(parents=True, exist_ok=True)
    print(f"\n  == instalando {paquete['nombre']} ==")
    codigo, salida = instalar_paquete(receta["pasos"])
    correcto, version = verificar(clave)
    recibo["resultado"] = "instalado" if (codigo == 0 and correcto) else "falló"
    recibo["verificacion"] = version
    destino = escribir_recibo(recibo)
    if codigo != 0 or not correcto:
        return rechazar(
            f"la instalación de {paquete['nombre']} no terminó bien"
            + (f": {salida}" if salida else "")
            + f" (recibo en {destino})"
            + f"\n       SALIDA: hazlo a mano desde {receta['url']} y comprueba con: "
              "python3 docs/00-metodo/scripts/doctor.py")
    print(f"\n  OK   {paquete['nombre']} instalado y comprobado: {version}")
    print(f"       recibo en {destino}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # `instalar` va antes de argparse a posta: el uso de siempre (`doctor.py [--escribir]`)
    # no cambia ni una coma, y el subcomando trae sus propios rechazos con su SALIDA.
    if argv and argv[0] == "instalar":
        return orden_instalar(argv[1:])

    ap = argparse.ArgumentParser(description="Foto del entorno de esta máquina.")
    ap.add_argument("--escribir", action="store_true",
                    help="además, deja la foto en docs/conocimiento/entorno-de-esta-maquina.md")
    ap.epilog = AYUDA_INSTALAR
    args = ap.parse_args(argv)
    pantalla, documento = informe()
    print(pantalla)
    if args.escribir:
        destino = RAIZ / "docs" / "conocimiento" / "entorno-de-esta-maquina.md"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(documento, encoding="utf-8")
        print(f"\n  Escrito en {destino.relative_to(RAIZ)} (se sobrescribe: es una foto, "
              f"no un histórico)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
