#!/usr/bin/env python3
"""unidad.py — el despacho de una unidad, scriptado (regla del método: script > plantilla > prosa).

Hasta hoy el ritual de despacho era prosa en `00-metodo/README.md` y en los runbooks: el padre
recordaba asignar NNN, copiar la plantilla, esperar la aprobación y crear el worktree. Esto lo
convierte en tres comandos con PRECONDICIONES que bloquean, para que las reglas duras 4 (el NNN
no se renumera), 5 (una unidad en vuelo), "la spec va antes que la rama" y "el contrato lo
aprueba el usuario" (frontmatter `aprobado:`) se cumplan solas.

Uso (desde cualquier directorio del workspace; la raíz se deriva de la ruta del script):
  python3 docs/00-metodo/scripts/unidad.py nnn                      siguiente NNN libre
  python3 docs/00-metodo/scripts/unidad.py nueva feature mi-slug    crea la unidad (sin rama)
  python3 docs/00-metodo/scripts/unidad.py nueva feature mi-slug --directo
                                                                  carril directo: contrato corto
  python3 docs/00-metodo/scripts/unidad.py despachar 004-mi-slug    crea rama + worktree
  python3 docs/00-metodo/scripts/unidad.py despachar 005-auditoria --documental
                                                                  trabaja solo en su ficha
  python3 docs/00-metodo/scripts/unidad.py validar 004-mi-slug     abre la validación guiada
                                                                  (la web que el usuario mira
                                                                   para dar su OK)
  python3 docs/00-metodo/scripts/unidad.py cerrar 004-mi-slug --ok-usuario 2026-08-01
                                                                  cierra la unidad ya fusionada
  python3 docs/00-metodo/scripts/unidad.py estado                   resumen de un vistazo

Solo stdlib. Nada destructivo: este script crea y avisa, jamás borra ni pisa lo escrito.
Exit 0 si todo bien; exit 1 con mensaje claro si una precondición bloquea.
"""
import argparse
import contextlib
import datetime
import hashlib
import importlib.util
import json
import os
import posixpath
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

import peticion as gestion_peticiones
import control_plane
import lease as gestion_leases
import lint_cierre
import repo_config
import workspace_paths

# Windows: en cuanto la salida va a un PIPE —setup.py, la CI, cualquier harness de agente— el
# encoding deja de ser el de la consola y pasa a ser el local (cp1252), donde un `→` o un `·`
# mata el script con UnicodeEncodeError. Se fuerza UTF-8 antes de imprimir nada.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

# Este script vive en docs/00-metodo/scripts/, igual que lint_metodo.py:
# parents[3] es la raíz del meta-repo sea cual sea el directorio de trabajo.
RAIZ = Path(__file__).resolve().parents[3]
TRABAJO = RAIZ / "docs/05-trabajo"
ARCHIVO = TRABAJO / "archivo"
BUGS = RAIZ / "docs/bugs"
PLANTILLAS = RAIZ / "docs/00-metodo/plantillas"
WORKTREES = RAIZ / "worktrees"

# Vocabulario cerrado: el mismo que valida lint_metodo.py, y por eso ya no se escribe aquí.
# Vive en `repo_config.py`, que importan los catorce scripts; las dos copias coincidían por
# suerte y nada lo comprobaba (unidad 050). No se crean variantes.
TIPOS = repo_config.TIPOS
ESTADOS = repo_config.ESTADOS_UNIDAD
# `en_validacion` NO está en vuelo (ADR-010): su rama ya está fusionada y el trabajo de
# construcción terminó; lo único pendiente es que el usuario pruebe la app. Ocupaba cupo de
# paralelismo sin consumir atención de nadie, y eso obligaba a subir el tope para seguir
# trabajando: el problema no era el tope, era un estado que no existía.
EN_VUELO = {"en_obra", "en_revision"}
RE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RE_UNIDAD = re.compile(r"^(\d{3})-([a-z0-9][a-z0-9-]*)$")

# Caracteres mínimos de prosa PROPIA que debe tener el contrato para poder despacharse.
MINIMO_PROSA = 200

# El contrato lo aprueba el USUARIO, no el agente: `aprobado:` solo vale si es una fecha ISO.
# Todo lo demás (`no`, vacío, ausente, "sí", "ok") es ausencia de aprobación.
RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MARCA_DEUDA = ("> **DEUDA DE SPEC — HOTFIX**: rama creada sin contrato completo. "
               "Rellenar al estabilizar.")

HOY = datetime.date.today().isoformat()


def ok(msg):
    print(f"  OK   {msg}")


def warn(msg):
    print(f"  WARN {msg}")


def fail(msg):
    err(f"  FAIL {msg}")


def err(msg):
    """Escribe en stderr sin descolocar la salida: stdout va con búfer y stderr no."""
    sys.stdout.flush()
    print(msg, file=sys.stderr)
    sys.stderr.flush()


def rel(p):
    """Ruta relativa a la raíz para que la salida sea legible."""
    try:
        return str(Path(p).relative_to(RAIZ))
    except ValueError:
        return str(p)


def fichero_unidad_seguro(path):
    return workspace_paths.regular_file(RAIZ, path, label="fichero de unidad")


def leer_fichero_unidad(path):
    return fichero_unidad_seguro(path).read_text(encoding="utf-8")


class ErrorFichaBloqueada(Exception):
    """La ficha está en solo lectura y el cierre no puede escribirla (bug 065, R4).

    Pasaba de verdad: la ventana de solo lectura del launcher se quedaba abierta cuando el
    proceso moría por señal, y el `cerrar` siguiente reventaba con un `PermissionError`
    pelado a media faena. Un traceback no es una salida — este error sí nombra el `chmod`.
    """


def escribir_fichero_unidad(path, text):
    destino = fichero_unidad_seguro(path)
    try:
        destino.write_text(text, encoding="utf-8")
    except PermissionError as exc:
        raise ErrorFichaBloqueada(
            f"no puedo escribir {rel(destino)}: está en solo lectura ({exc.strerror}). Es el "
            f"rastro de una ejecución del launcher que murió con su ventana de solo lectura "
            f"abierta; el contenido está intacto, solo faltan los permisos. "
            f"{SALIDA} devuélvele la escritura con `chmod u+w {rel(destino)}` y repite el "
            f"mismo comando"
        ) from exc


# --------------------------------------------------------------------------- frontmatter y prosa

def frontmatter(path):
    """Parseo mínimo del frontmatter YAML (clave: valor). Devuelve dict o None.

    Idéntico al de lint_metodo.py a propósito: si el linter lo acepta, este script también.

    Admite las DOS formas en que se escribe una lista de verdad:

        ficheros: [api/rutas.py, api/modelos.py]      en línea
        ficheros:                                     multilínea
          - api/rutas.py
          - api/modelos.py

    Sin esto el parseo era línea a línea y una lista multilínea dejaba `ficheros` en cadena
    VACÍA: la comprobación de ficheros disjuntos comparaba conjuntos vacíos y daba el visto
    bueno siempre. Un guardián que mira de menos es peor que ninguno, porque da permiso con
    cara de haber mirado. Las listas se normalizan a "a, b" para que quien lea el valor no
    tenga que cambiar.
    """
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    segura = fichero_unidad_seguro(path)
    try:
        lineas = segura.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lineas or lineas[0].strip() != "---":
        return None
    datos = {}
    clave_abierta, items = None, []

    def cerrar_lista():
        nonlocal clave_abierta, items
        if clave_abierta and items:
            datos[clave_abierta] = ", ".join(items)
        clave_abierta, items = None, []

    for linea in lineas[1:]:
        if linea.strip() == "---":
            cerrar_lista()
            return datos
        m = re.match(r"^(\w+):\s*(.*)$", linea)
        if m:
            cerrar_lista()
            valor = m.group(2).split("#")[0].strip()
            datos[m.group(1)] = valor
            if not valor:
                clave_abierta = m.group(1)      # puede venir una lista debajo
            continue
        item = re.match(r"^\s+-\s*(.+)$", linea)
        if item and clave_abierta:
            items.append(item.group(1).split("#")[0].strip().strip("'\""))
    return None


def ficheros_de(fm):
    """Conjunto de rutas NORMALIZADAS que declara una unidad. Mismo criterio que lint_metodo.py.

    La puerta de paralelismo compara CONJUNTOS DE CADENAS, así que `api/x.py`, `./api/x.py` y
    `API/x.py` —el mismo fichero en disco, en macOS y en Windows— eran tres rutas distintas y
    dos unidades podían declarar el mismo fichero con el visto bueno de la puerta. Y esas
    variantes no son rebuscadas: las produce solo un agente que copia rutas de contextos
    distintos. Se normaliza el separador, los `./` y las mayúsculas.

    `casefold` acerca de más en sistemas de ficheros sensibles a mayúsculas (Linux): allí
    `API/x.py` y `api/x.py` PUEDEN ser dos ficheros. Se prefiere ese error, que bloquea un
    paralelismo legítimo y raro, al contrario, que bendice un choque real.
    """
    crudos = (fm.get("ficheros") or "").strip("[]").split(",")
    limpias = set()
    for crudo in crudos:
        ruta = crudo.strip().strip("'\"")
        if not ruta:
            continue
        limpias.add(posixpath.normpath(ruta.replace("\\", "/")).casefold())
    return limpias


def aprobacion(fm):
    """Fecha de aprobación del contrato, o None si nadie lo ha aprobado todavía.

    `aprobado:` es el ÚNICO rastro de que el usuario dio su OK. Se exige fecha ISO a propósito:
    un `sí` lo teclea cualquiera sin haber leído nada, una fecha dice CUÁNDO se leyó. Y no
    puede ser futura (mismo criterio que el OK del usuario, `fecha_ok`): `aprobado: 2030-01-01`
    es lo que teclea un agente que deja "preparada" la aprobación, no un usuario que leyó.
    """
    return fecha_ok(fm.get("aprobado"))


# R3 del bug 054: `visor_contratos/servir.py` anota una línea por contrato mostrado en
# `.runtime/visor-contratos.log` — mismo criterio que el rastro del visor de flujos
# (unidad 033). El comando que la deja escrita es el que se imprime en todos los FAIL de abajo.
RASTRO_VISOR_CONTRATOS = ".runtime/visor-contratos.log"
COMANDO_VISOR_CONTRATOS = (
    "python3 main/visor_contratos/servir.py --workspace . --minutos 0"
)
RE_RASTRO_CONTRATO = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T[\d:]+\s+contrato mostrado:\s+(\S+)\s*$"
)


def rastro_visor_contrato(nombre):
    """Fechas ISO (posibles varias) en las que el visor de contratos mostró ESTE contrato.

    Sin `.runtime/visor-contratos.log`, o sin ninguna línea de esta unidad, lista vacía:
    nunca se ha visto.
    """
    registro = RAIZ / RASTRO_VISOR_CONTRATOS
    if not registro.is_file():
        return []
    try:
        texto = registro.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        m.group(1) for linea in texto.splitlines()
        if (m := RE_RASTRO_CONTRATO.match(linea)) and m.group(2) == nombre
    ]


# ------------------------------------------- bug 057: las webs del OK se abren solas
# La 054 hizo COMPROBABLE que un contrato se mostró, pero abrirlo seguía siendo un acto
# manual del agente; y la validación guiada (051/056) ni comando tenía: el manifiesto se
# escribía a mano. Pedir un OK pasa a ser EJECUTAR algo, no acordarse de algo.

# Puerto del visor de contratos. Se puede fijar por entorno para no chocar con otra sesión
# (mismo patrón que IR_TOPE_HOOK_SEGUNDOS).
PUERTO_VISOR_CONTRATOS = int(os.environ.get("IR_PUERTO_VISOR_CONTRATOS", "8766"))
# Los datos de cada validación guiada: una carpeta por unidad, con su manifiesto y sus
# recibos. Es la ruta que la 051 ya usa; aquí solo deja de escribirse a mano.
RUTA_PRESENTACIONES = ".runtime/presentaciones"
# Dónde puede vivir cada visor: en el workspace de alumno lo reparte `bootstrap.py`; en el
# meta-repo del método viene con el repo de código, bajo `main/`.
CARPETAS_PRESENTACIONES = ("docs/00-metodo/requisitos/visor_presentaciones",
                           "main/visor_presentaciones")
CARPETAS_CONTRATOS = ("main/visor_contratos",
                      "docs/00-metodo/requisitos/visor_contratos")


def comando_validar(nombre):
    return f"python3 {rel(__file__)} validar {nombre}"


def hay_pantalla():
    """¿Tiene esta sesión un navegador que abrir?

    MISMA regla que `visor_presentaciones/abrir.py:hay_pantalla` y a propósito duplicada:
    los scripts del método viajan con la plantilla y el visor vive en el repo de código,
    así que esto tiene que funcionar en un workspace donde el visor todavía no está.
    `IR_SIN_NAVEGADOR` es la declaración explícita de quien lanza (un agente en batch, la
    CI, una sesión por SSH) y manda; `BROWSER` es la contraria. Sin ninguna se mira el
    escritorio: en Linux/BSD sin `DISPLAY` ni `WAYLAND_DISPLAY` no hay dónde pintar.
    """
    if os.environ.get("IR_SIN_NAVEGADOR", "").strip():
        return False
    if os.environ.get("BROWSER", "").strip():
        return True
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def carpeta_visor(candidatas, *ficheros):
    for sub in candidatas:
        carpeta = RAIZ / sub
        if all((carpeta / fichero).is_file() for fichero in ficheros):
            return carpeta
    return None


def visor_presentaciones():
    return carpeta_visor(CARPETAS_PRESENTACIONES, "abrir.py", "manifestar.py", "servir.py")


def modulos_de_presentaciones(carpeta):
    """Carga `manifestar` y `abrir` DEL WORKSPACE, no una copia.

    El contrato JSON del manifiesto y la mecánica de levantar el visor viven en el visor de
    presentaciones. Reimplementarlos aquí sería tener dos verdades del mismo formato, que es
    exactamente como nacen los manifiestos escritos a mano que este bug arregla.
    """
    sys.path.insert(0, str(carpeta))
    try:
        modulos = []
        for nombre in ("manifestar", "abrir"):
            spec = importlib.util.spec_from_file_location(
                f"visor_presentaciones_{nombre}", carpeta / f"{nombre}.py")
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)
            modulos.append(modulo)
        return modulos
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(carpeta))


# --------------------------------------------------- leer la ficha: pasos, evidencia, adjuntos

RE_COMO_PRUEBAS = re.compile(r"Cómo lo pruebas tú", re.I)


def bloque_como_lo_pruebas(texto):
    """Las líneas de «Cómo lo pruebas tú», sea encabezado (unidad) o viñeta de la §6 de un
    bug. Fuera de esa sección no se mira: es LO que el usuario va a tener delante."""
    lineas = texto.splitlines()
    inicio = next((i for i, l in enumerate(lineas) if RE_COMO_PRUEBAS.search(l)), None)
    if inicio is None:
        return []
    ancla = lineas[inicio]
    es_vineta = ancla.lstrip().startswith(("-", "*"))
    bloque = [ancla.split(":", 1)[1]] if (es_vineta and ":" in ancla) else []
    for linea in lineas[inicio + 1:]:
        if linea.startswith("#"):
            break                                  # empieza otra sección
        if (es_vineta and not linea.startswith((" ", "\t"))
                and linea.strip().startswith(("-", "*"))):
            break                                  # empieza otra viñeta de la §6
        bloque.append(linea)
    return bloque


def pasos_de_prueba(texto):
    """Los pasos que el usuario va a seguir: las filas de la tabla si la hay, y si no los
    puntos numerados de esa sección. Lo que sigue siendo plantilla (`<...>`) no cuenta."""
    bloque = [l for l in bloque_como_lo_pruebas(texto)
              if l.strip() and not l.strip().startswith("<")]
    filas = []
    for linea in bloque:
        s = linea.strip()
        if not s.startswith("|"):
            continue
        celdas = [c.strip() for c in s.strip("|").split("|")]
        if not celdas or all(set(c) <= set("-: ") for c in celdas):
            continue                               # separador `|---|---|`
        filas.append(celdas)
    if filas:
        if filas[0] and filas[0][0] in {"#", "N", "Nº"}:
            filas = filas[1:]                      # la cabecera es rótulo, no paso
        pasos = [" · ".join(c for c in fila if c) for fila in filas]
    else:
        plano = " ".join(l.strip() for l in bloque)
        numerados = re.findall(r"\d+\.\s*(.+?)(?=\s+\d+\.\s|$)", plano)
        pasos = numerados or [VINETA.sub("", l.strip()).strip() for l in bloque]
    return [p.strip() for p in pasos if MARCADOR.sub("", p).strip(" ·-—")]


def evidencia_de_la_ficha(texto):
    """La evidencia que se le enseña al usuario: el bloque `parte-de-cierre` de
    `hallazgos.md` (unidades) o la sección de Resolución de la ficha (bugs, ADR-006).
    Los marcadores sin rellenar (`—`) no son evidencia: no viajan."""
    lineas = []
    bloque = re.search(r"```parte-de-cierre\n(.*?)```", texto, re.S)
    if bloque:
        for linea in bloque.group(1).splitlines():
            pareja = linea.split("#")[0].strip()
            if ":" in pareja and pareja.split(":", 1)[1].strip() not in PLACEHOLDERS:
                lineas.append(pareja)
    if lineas:
        return lineas
    seccion = re.search(r"^#{1,6}[^\n]*Resoluci[óo]n[^\n]*$", texto, re.M)
    if seccion:
        for linea in texto[seccion.end():].splitlines():
            if linea.startswith("#"):
                break
            s = MARCADOR.sub("", VINETA.sub("", linea.strip()).strip()).strip()
            if ":" in s and s.split(":", 1)[1].strip() not in PLACEHOLDERS:
                lineas.append(s)
    return lineas


def adjuntos_de(fm, ruta, permitida):
    """Los ficheros que la unidad CITA, como rutas del workspace (adjuntos de la 056): su
    propia ficha primero y luego cada `ficheros:` allí donde de verdad esté — el repo de
    código cuelga de `main/`, así que la ruta declarada se prueba con y sin ese prefijo."""
    rutas = [rel(ruta).replace("\\", "/")]
    for crudo in (fm.get("ficheros") or "").strip("[]").split(","):
        declarado = crudo.strip().strip("'\"").replace("\\", "/")
        if not declarado:
            continue
        for candidata in (declarado, posixpath.join("main", declarado)):
            if (RAIZ / candidata).is_file():
                rutas.append(candidata)
                break
    return [r for r in dict.fromkeys(rutas) if permitida.match(r)]


# --------------------------------------------------------------- R2: el contrato se abre solo

def _meta_visor_contratos(puerto):
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/meta.json" % puerto, timeout=0.5
        ) as respuesta:
            return json.loads(respuesta.read())
    except (OSError, ValueError):
        return None


def abrir_visor_de_contratos(pendientes, sin_navegador):
    """Levanta el visor de contratos y abre el navegador en el primero de `pendientes`.

    Devuelve las líneas (nivel, mensaje) que hay que imprimir. Cuando NO puede abrir nada
    lo dice y nombra el comando: un visor que no se levanta en silencio sería exactamente
    el fallo que esta unidad arregla.
    """
    if sin_navegador:
        return [("warn", "--sin-navegador: no levanto el visor de contratos. Enséñaselo tú: "
                         + COMANDO_VISOR_CONTRATOS)]
    if not hay_pantalla():
        return [("warn", "sesión sin pantalla: no abro el visor de contratos. El comando, "
                         "para cuando la haya: " + COMANDO_VISOR_CONTRATOS)]
    carpeta = carpeta_visor(CARPETAS_CONTRATOS, "servir.py")
    if carpeta is None:
        return [("warn", "no encuentro el visor de contratos en este workspace "
                         f"({' ni '.join(CARPETAS_CONTRATOS)}). Enséñaselo tú: "
                         + COMANDO_VISOR_CONTRATOS)]
    puerto = PUERTO_VISOR_CONTRATOS
    lineas = []
    meta = _meta_visor_contratos(puerto)
    if meta is None:
        registro = RAIZ / ".runtime" / f"visor-contratos-{puerto}.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        orden = [sys.executable, str(carpeta / "servir.py"), "--workspace", str(RAIZ),
                 "--minutos", "0", "--puerto", str(puerto), "--sin-navegador"]
        try:
            with registro.open("ab") as salida:
                # Desasido a propósito: el visor tiene que seguir en pie cuando este
                # comando termine — es lo que el usuario va a mirar.
                subprocess.Popen(orden, stdin=subprocess.DEVNULL, stdout=salida,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            return [("warn", f"no pude levantar el visor de contratos ({exc}). Ábrelo tú: "
                             + COMANDO_VISOR_CONTRATOS)]
        for _ in range(50):
            meta = _meta_visor_contratos(puerto)
            if meta is not None:
                break
            time.sleep(0.1)
        if meta is None:
            return [("warn", f"el visor de contratos no llegó a arrancar (log en "
                             f"{rel(registro)}). Ábrelo tú: " + COMANDO_VISOR_CONTRATOS)]
        lineas.append(("ok", f"visor de contratos levantado en http://127.0.0.1:{puerto}/"))
    else:
        suyo = str(meta.get("workspace", ""))
        if not suyo or Path(suyo).resolve() != RAIZ:
            return [("warn", f"el puerto {puerto} lo ocupa otro visor ({suyo or 'desconocido'}). "
                             "Ábrelo tú en otro puerto: " + COMANDO_VISOR_CONTRATOS)]
        lineas.append(("ok", f"visor de contratos ya en pie en http://127.0.0.1:{puerto}/"))
    url = f"http://127.0.0.1:{puerto}/#{pendientes[0]}"
    webbrowser.open(url)
    lineas.append(("ok", f"navegador abierto en {url} — el usuario ya lo tiene delante"))
    if len(pendientes) > 1:
        lineas.append(("warn", f"quedan {len(pendientes) - 1} contrato(s) más sin aprobar, en "
                               f"la misma página: {', '.join(pendientes[1:])}"))
    return lineas


def imprimir_lineas(lineas):
    for nivel, mensaje in lineas:
        (ok if nivel == "ok" else warn)(mensaje)


def contratos_pendientes(primero=None):
    """Contratos sin `aprobado:`, con `primero` al frente si sigue estándolo."""
    pendientes = sorted(
        n for n, u in censo().items()
        if u["fm"].get("estado") == "planificada" and aprobacion(u["fm"]) is None
    )
    if primero in pendientes:
        pendientes.remove(primero)
        pendientes.insert(0, primero)
    return pendientes


# ------------------------------------------------------- R3: el OK se lee, no se teclea

def recibos_de_validacion(nombre):
    """Recibos que el visor de presentaciones selló para ESTA unidad, del más viejo al más
    nuevo. Formato de la 051: aquí solo se lee, jamás se escribe."""
    carpeta = RAIZ / RUTA_PRESENTACIONES / nombre / "recibos"
    if not carpeta.is_dir():
        return []
    recibos = []
    for fichero in sorted(carpeta.glob("*.json")):
        try:
            recibo = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                               # un recibo ilegible no acredita nada
        if not isinstance(recibo, dict) or recibo.get("presentacion") != nombre:
            continue
        marca = str(recibo.get("fecha", ""))
        if not RE_FECHA.match(marca[:10]):
            continue
        recibos.append({"eleccion": recibo.get("eleccion"), "dia": marca[:10],
                        "marca": marca,
                        "comentario": (recibo.get("comentario") or "").strip()})
    return sorted(recibos, key=lambda r: r["marca"])


def mismo_dia_o_vispera(dia, fecha_ok_usuario):
    """El recibo lo fecha el servidor en UTC y el OK lo fecha el usuario en su huso: un día
    de margen evita que una validación de las once de la noche parezca de otro día."""
    try:
        distancia = datetime.date.fromisoformat(dia) - datetime.date.fromisoformat(fecha_ok_usuario)
    except ValueError:
        return False
    return abs(distancia.days) <= 1


def puerta_recibo_validacion(nombre, ok_usuario):
    """(problema, nota, aviso) — R3: `--ok-usuario` sin recibo es una fecha tecleada.

    `--force` no entra aquí: `cerrar` no lo tiene, y la válvula de hotfix es de `despachar`.
    """
    if visor_presentaciones() is None:
        return None, None, (
            "validación guiada: no hay visor de presentaciones en este workspace "
            f"({' ni '.join(CARPETAS_PRESENTACIONES)}), así que no puedo leer el OK del "
            "usuario y la puerta queda en AVISO — una regla sin ejecutor se dice, no se "
            "finge (ADR-029)")
    recibos = recibos_de_validacion(nombre)
    ultimo = recibos[-1] if recibos else None
    if ultimo and ultimo["eleccion"] == "problema":
        # Un `problema` al que nadie ha vuelto es el usuario diciendo que esto no está bien.
        # Un `confirmado` posterior sí desbloquea: es él revalidando después del arreglo.
        return (f"el usuario marcó «problema» en la validación guiada de {nombre} el "
                f"{ultimo['dia']}: «{ultimo['comentario'] or 'sin comentario'}». Eso no se "
                f"cierra: se abre un bug con su ejemplo. {SALIDA} python3 {rel(__file__)} "
                f"nueva bug <slug> --desde <P-ID> (runbooks/bug.md) y, ya arreglado, "
                f"{comando_validar(nombre)} otra vez", None, None)
    if not ok_usuario:
        return None, None, None
    confirmados = [r for r in recibos if r["eleccion"] == "confirmado"]
    if not confirmados:
        return (f"--ok-usuario {ok_usuario} sin recibo `confirmado` de la validación guiada "
                f"de {nombre}: una fecha tecleada por el agente no es un OK leído al usuario. "
                f"{SALIDA} {comando_validar(nombre)} y que decida él en la web", None, None)
    if not any(mismo_dia_o_vispera(r["dia"], ok_usuario) for r in confirmados):
        dias = ", ".join(sorted({r["dia"] for r in confirmados}))
        return (f"--ok-usuario {ok_usuario}, pero los `confirmado` de {nombre} son de otro día "
                f"({dias}): el OK que se firma es el que se dio. {SALIDA} "
                f"{comando_validar(nombre)} y pide el OK de hoy", None, None)
    return None, f"OK leído del visor de presentaciones: {nombre} confirmado por el usuario", None


# ----------------------------------------------------------- subcomando: validar (R1)

def cmd_validar(args):
    nombre = args.unidad.strip("/")
    if not RE_UNIDAD.match(nombre):
        fail(f"'{nombre}' no tiene forma NNN-slug (tres dígitos, guion, slug)")
        return 1
    unidad = buscar_unidad(nombre)
    if unidad is None:
        fail(f"no existe la unidad {nombre} (¿ya está cerrada y archivada?)")
        return 1
    carpeta = visor_presentaciones()
    if carpeta is None:
        fail(f"no encuentro el visor de presentaciones en este workspace "
             f"({' ni '.join(CARPETAS_PRESENTACIONES)}): sin él no hay validación guiada "
             f"que abrir. {SALIDA} vuelve a repartirlo con el actualizador del workspace "
             f"(`python3 main/visor/actualizar.py`) o clona el repo de código en main/")
        return 1

    ruta, fm, clase = unidad["ruta"], unidad["fm"], unidad["clase"]
    texto = leer_fichero_unidad(ruta)
    fuente_evidencia = ruta if clase == "bug" else ruta.parent / "hallazgos.md"
    pasos = pasos_de_prueba(texto)
    if not pasos:
        fail(f"{rel(ruta)} no tiene escrito «Cómo lo pruebas tú»: sin eso el usuario devuelve "
             f"un «me parece bien» que firma una entrega sin haber comprobado nada "
             f"(runbooks/cierre.md, paso 5). {SALIDA} escríbelo en {rel(ruta)} y repite: "
             f"python3 {rel(__file__)} validar {nombre}")
        return 1
    texto_evidencia = (leer_fichero_unidad(fuente_evidencia)
                       if fuente_evidencia.exists() else "")
    evidencia = evidencia_de_la_ficha(texto_evidencia) or [
        f"sin evidencia escrita todavía en {rel(fuente_evidencia)}"]

    mod_manifestar, mod_abrir = modulos_de_presentaciones(carpeta)
    presentacion = mod_manifestar.presentacion_validacion(
        nombre,
        f"{nombre} · cómo lo pruebas tú",
        fm.get("actualizado") or HOY,
        pasos,
        evidencia,
        adjuntos_de(fm, ruta, mod_manifestar.RUTA_ADJUNTO),
    )
    try:
        contenido = mod_manifestar.manifiesto([presentacion])
    except ValueError as exc:
        fail(f"el manifiesto que sale de {rel(ruta)} no pasa su propio contrato ({exc}). "
             f"{SALIDA} arregla eso en la ficha y repite "
             f"python3 {rel(__file__)} validar {nombre}")
        return 1

    datos = RAIZ / RUTA_PRESENTACIONES / nombre
    datos.mkdir(parents=True, exist_ok=True)
    (datos / "manifiesto.json").write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"== Validación guiada de {nombre} ==\n")
    ok(f"manifiesto en {rel(datos / 'manifiesto.json')}: {len(pasos)} paso(s), "
       f"{len(presentacion.get('adjuntos', []))} adjunto(s)")
    # Idempotente (R1): el manifiesto se reescribe, los recibos NUNCA se tocan — son la
    # decisión del usuario y son inmutables desde la 051.
    anteriores = recibos_de_validacion(nombre)
    if anteriores:
        ok(f"{len(anteriores)} recibo(s) anterior(es) intactos en {rel(datos / 'recibos')}")

    orden_manual = (f"python3 {rel(carpeta / 'abrir.py')} --datos {rel(datos)} "
                    f"--workspace . --presentacion {nombre}")
    if args.sin_navegador:
        warn("--sin-navegador: manifiesto listo, pero no levanto nada ni abro el navegador")
        print(f"\n  Cuando quieras enseñárselo:\n      {orden_manual}")
        return 0
    if not hay_pantalla():
        warn("sesión sin pantalla: manifiesto listo, pero no hay navegador que abrir")
        print(f"\n  Desde una sesión con pantalla:\n      {orden_manual}")
        return 0
    argumentos = argparse.Namespace(
        puerto=args.puerto, presentacion=nombre, sin_navegador=False, workspace=str(RAIZ))
    try:
        resultado = mod_abrir.abrir(datos, argumentos)
    except (OSError, RuntimeError, ValueError) as exc:
        fail(f"no pude levantar el visor de presentaciones ({exc}). {SALIDA} lánzalo a mano: "
             f"python3 {rel(carpeta / 'abrir.py')} --datos {rel(datos)} --workspace . "
             f"--presentacion {nombre}")
        return 1
    ok(f"visor de presentaciones: {resultado.url}")
    if resultado.navegador:
        ok("navegador abierto ahí — el usuario ya lo tiene delante")
    else:
        warn(f"no he podido abrir el navegador; pásale esta dirección: {resultado.url}")
    print(f"\n  Cuando el usuario decida en la web, el recibo queda en {rel(datos / 'recibos')}\n"
          f"  y el cierre lo lee solo:\n"
          f"      python3 {rel(__file__)} cerrar {nombre} --ok-usuario {HOY}")
    return 0


def severidad_declarada(texto):
    """Severidad P0-P4 realmente ELEGIDA en la ficha del bug, o None.

    La plantilla trae la escalera entera en la misma línea ("P0 (producción caída) … P4
    (cosmético)"): si en el valor siguen apareciendo varios niveles, nadie ha triado aún y
    aceptar ese "P0" convertiría la válvula de hotfix en un bypass gratis.
    """
    for m in re.finditer(r"^\s*(?:[-*]\s*)?\**\s*Severidad[^:\n]*:\s*(.+)$", texto,
                         flags=re.M | re.I):
        niveles = set(re.findall(r"\bP[0-4]\b", m.group(1)))
        if len(niveles) == 1:
            return niveles.pop()
    return None


def cuerpo(texto):
    """El documento sin su frontmatter (el frontmatter son metadatos, no contrato)."""
    lineas = texto.splitlines()
    if lineas and lineas[0].strip() == "---":
        for i, linea in enumerate(lineas[1:], start=1):
            if linea.strip() == "---":
                return "\n".join(lineas[i + 1:])
    return texto


MARCADOR = re.compile(r"<[^>\n]*>")       # `<lo que hay que rellenar>`
VINETA = re.compile(r"^(?:[-*]|\d+\.)\s*(?:\[[ xX]\]\s*)?")
PLACEHOLDERS = {"", "—", "-", "…", "..."}


def prosa_real(texto, texto_plantilla):
    """Caracteres de prosa PROPIA: lo escrito por encima de la plantilla.

    Por qué no basta con "el fichero existe y es largo": la plantilla ya trae mucha prosa fija
    (Reglas del constructor, Definición de hecho, Plan de trabajo). Un fichero recién copiado
    pesa miles de caracteres sin que nadie haya escrito UNA línea de contrato. Así que se
    descuenta línea a línea todo lo que sigue siendo plantilla, y de lo que queda se ignoran
    encabezados, citas `>` (instrucciones de la plantilla), marcadores `<...>` (huecos sin
    rellenar) y viñetas vacías (`- —`). Lo que sobrevive es contrato escrito por una persona.
    """
    plantilla_lineas = {l.strip() for l in cuerpo(texto_plantilla).splitlines() if l.strip()}
    total = 0
    for linea in cuerpo(texto).splitlines():
        s = linea.strip()
        if not s or s in plantilla_lineas:
            continue                                   # vacío o idéntico a la plantilla: no aporta
        if s.startswith(("#", ">", "<", "```", "|", "---")):
            continue                                   # encabezado, cita, marcador, código o tabla
        s = MARCADOR.sub("", s)                        # huecos `<...>` embebidos: no son prosa
        s = VINETA.sub("", s).strip()                  # viñeta o casilla `- [ ]`
        if s in PLACEHOLDERS:
            continue
        total += len(s)
    return total


# --------------------------------------------------------------------------- repo de código

def repo_codigo():
    """Lee de repos.yaml la ruta local y la rama principal del repo de código.

    Parseo mínimo con regex (nada de PyYAML: el método es solo stdlib). repos.yaml es la única
    fuente de verdad de dónde vive el código; este script no la duplica.
    """
    return repo_config.repo_code(RAIZ)


def modo_push():
    """Política de publicación del workspace (repos.yaml): `agente` (defecto) | `usuario`."""
    return repo_config.modo_push(RAIZ)


def avisar_principal_sin_empujar(repo, principal):
    """Camino B del cierre: la rama principal local fusionada y todavía sin publicar.

    Con `push: agente` es un descuido y se avisa: al despachar, la rama de cada unidad nace
    de `origin/<principal>`, así que si el merge se queda en local la SIGUIENTE unidad parte
    de una base vieja y su merge ya no será fast-forward. Con `push: usuario` es exactamente
    lo que el workspace pidió (007, R2 punto 6): mismo comando, pero como recibo del cierre,
    no como alarma. Sin remoto no hay nada que decir.
    """
    if git(repo, "remote", "get-url", "origin", silencioso=True)[0] != 0:
        return
    codigo, salida = git(repo, "rev-list", "--count",
                         f"origin/{principal}..{principal}", silencioso=True)
    if codigo != 0 or not salida.strip().isdigit() or int(salida.strip()) == 0:
        return
    comando = f"git -C {rel(repo)} push origin {principal}"
    if modo_push() == "usuario":
        ok(f"push: usuario — la rama principal local va {salida.strip()} commit(s) por "
           f"delante de origin/{principal}: el método no la empuja. Publícala tú cuando "
           f"quieras → {comando}")
    else:
        warn(f"la rama principal local va {salida.strip()} commit(s) por delante de "
             f"origin/{principal}: empújala o la siguiente unidad partirá de una base "
             f"vieja → {comando}")


def git(repo, *args, silencioso=False):
    """Ejecuta git y devuelve (codigo, salida). Nunca lanza: los errores se deciden arriba."""
    try:
        p = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=False)
    except OSError as e:
        if not silencioso:
            warn(f"no se pudo ejecutar git: {e}")
        return 1, ""
    return p.returncode, (p.stdout + p.stderr).strip()


def ramas_del_codigo():
    """Nombres de rama del repo de código (locales y remotas), sin el prefijo del remoto."""
    repo, _ = repo_codigo()
    if not (repo / ".git").exists():
        return None                                    # sin clon: quien llame decide si avisa
    codigo, salida = git(repo, "branch", "-a", "--format=%(refname:short)", silencioso=True)
    if codigo != 0:
        return None
    nombres = set()
    for linea in salida.splitlines():
        nombre = linea.strip().split(" ")[0]
        if not nombre or "HEAD" in nombre:
            continue
        nombres.add(nombre.split("/")[-1])             # origin/004-x → 004-x
    return nombres


# --------------------------------------------------------------------------- censo y numeración

def censo():
    """Unidades VIVAS: carpetas de 05-trabajo/ y fichas de docs/bugs/. Devuelve {nombre: dict}."""
    unidades = {}
    if TRABAJO.is_dir():
        for carpeta in sorted(TRABAJO.iterdir()):
            if not carpeta.is_dir() or carpeta.name == "archivo":
                continue
            if not RE_UNIDAD.match(carpeta.name):
                continue
            unidades[carpeta.name] = {"ruta": carpeta / "especificacion.md",
                                      "clase": "unidad",
                                      "fm": frontmatter(carpeta / "especificacion.md") or {}}
    if BUGS.is_dir():
        for fichero in sorted(BUGS.glob("*.md")):
            if not RE_UNIDAD.match(fichero.stem):
                continue
            unidades[fichero.stem] = {"ruta": fichero,
                                      "clase": "bug",
                                      "fm": frontmatter(fichero) or {}}
    return unidades


def numeros_ocupados():
    """{NNN: [de dónde sale]} mirando TODAS las fuentes donde un número puede haberse gastado.

    Regla dura 4: el NNN lo asigna el padre y NUNCA se renumera. Por eso no vale con mirar
    05-trabajo/: un número puede estar gastado y no verse ahí porque (a) la unidad ya se cerró
    y vive en archivo/, (b) es un bug, y los bugs no se archivan ni tienen carpeta: viven en
    docs/bugs/NNN-slug.md (ADR-006), o (c) la carpeta se movió/borró pero la RAMA sigue en el
    repo de código, y una colisión ahí rompe la trazabilidad rama ↔ PR ↔ unidad. Los worktrees
    no se miran aparte: cada worktree tiene su rama, así que la fuente (c) ya los cubre.
    """
    usados = {}

    def apunta(nnn, fuente):
        usados.setdefault(nnn, []).append(fuente)

    for base, etiqueta in ((TRABAJO, "05-trabajo"), (ARCHIVO, "archivo")):
        if not base.is_dir():
            continue
        for carpeta in sorted(base.iterdir()):
            if carpeta.is_dir() and RE_UNIDAD.match(carpeta.name):
                apunta(carpeta.name[:3], f"{etiqueta}/{carpeta.name}")
    if BUGS.is_dir():
        for fichero in sorted(BUGS.glob("*.md")):
            if RE_UNIDAD.match(fichero.stem):
                apunta(fichero.stem[:3], f"bugs/{fichero.name}")
    ramas = ramas_del_codigo()
    if ramas is None:
        # Por stderr: `nnn` debe poder usarse en un $(...) sin que el aviso ensucie el número.
        err("  WARN no pude listar las ramas del repo de código (¿falta el clon en main/?): "
            "el NNN se calcula solo con lo que hay en docs/")
    else:
        for rama in sorted(ramas):
            m = RE_UNIDAD.match(rama)
            if m:
                apunta(m.group(1), f"rama {rama}")
    return usados


def siguiente_nnn():
    """Máximo ocupado + 1, a 3 dígitos. Nunca reutiliza huecos: un número gastado es historia."""
    usados = numeros_ocupados()
    maximo = max((int(n) for n in usados), default=0)
    return f"{maximo + 1:03d}", usados


def buscar_unidad(nombre):
    """Localiza una unidad por nombre NNN-slug (carpeta o ficha de bug). None si no existe."""
    return censo().get(nombre)


def slug_ya_usado(slug):
    """¿Existe ya una unidad (viva o archivada) con este slug? Devuelve su nombre o None."""
    for nombre in censo():
        if nombre[4:] == slug:
            return nombre
    if ARCHIVO.is_dir():
        for carpeta in sorted(ARCHIVO.iterdir()):
            if carpeta.is_dir() and RE_UNIDAD.match(carpeta.name) and carpeta.name[4:] == slug:
                return f"archivo/{carpeta.name}"
    return None


# --------------------------------------------------------------------------- subcomando: nnn

def cmd_nnn(args):
    nnn, usados = siguiente_nnn()
    if args.detalle:
        print("== Números ocupados ==")
        for n in sorted(usados):
            print(f"  {n}  {', '.join(usados[n])}")
        print(f"\nSiguiente NNN libre: {nnn}")
    else:
        print(nnn)
    return 0


# --------------------------------------------------------------------------- subcomando: nueva

def rellenar(texto, nombre, nnn, tipo, carril="", peticiones=()):
    """Sustituye los marcadores obvios de la plantilla. Lo demás lo escribe una persona."""
    texto = texto.replace("NNN-slug", nombre)                       # frontmatter y rutas
    texto = texto.replace("actualizado: YYYY-MM-DD", f"actualizado: {HOY}")
    texto = re.sub(r"^# NNN ", f"# {nnn} ", texto, flags=re.M)      # encabezado del documento
    texto = re.sub(r"^tipo: \S+", f"tipo: {tipo}", texto, count=1, flags=re.M)
    if carril:
        texto = re.sub(r"^carril: \S+", f"carril: {carril}", texto, count=1, flags=re.M)
    if peticiones:
        referencias = ", ".join(peticiones)
        texto = re.sub(
            r"^peticiones:\s*\[\]",
            f"peticiones: [{referencias}]",
            texto,
            count=1,
            flags=re.M,
        )
    return texto


RE_PETICION_REVISION = re.compile(r"^(P-\d{8}-[a-f0-9]{8})@(\d+)$")


def peticiones_de(fm):
    """Referencias P-ID@revision del frontmatter, sin depender de un parser YAML."""
    valor = (fm.get("peticiones") or "").strip()
    if valor.startswith("[") and valor.endswith("]"):
        valor = valor[1:-1].strip()
    if not valor:
        return []
    return [item.strip().strip("'\"") for item in valor.split(",") if item.strip()]


def validar_origenes(referencias, carril, tipo):
    """Valida peticiones y fija la revisión que la orden ha entendido."""
    if not referencias:
        raise gestion_peticiones.ErrorPeticion(
            "toda unidad nueva exige al menos una petición evaluada con --desde P-ID"
        )
    resultado = []
    for pid in referencias:
        revision = gestion_peticiones.validar_para_orden(pid, carril, tipo)
        resultado.append(f"{pid}@{revision}")
    return resultado


def revalidar_origenes(fm, proceso=None, permitir_legacy=False):
    """Valida (o revalida) las peticiones de origen de una unidad/bug.

    `permitir_legacy` (unidad 027, R1/R2) solo lo activa `cerrar`: una unidad SIN
    `peticiones:` que figure en `peticiones/LEGACY.json` se acepta con lista vacía en vez de
    bloquear para siempre — la vía es para el pasado (anterior al sistema de peticiones), no
    un agujero: sin listar en LEGACY.json, el bloqueo de siempre sigue igual.
    """
    referencias = peticiones_de(fm)
    if not referencias:
        if permitir_legacy and proceso:
            tipo_proceso, nombre = proceso
            if gestion_peticiones.unidad_legacy(nombre, tipo_proceso):
                return []
        raise gestion_peticiones.ErrorPeticion(
            "la unidad no declara peticiones: [P-ID@revision]"
        )
    carril = (fm.get("carril") or "normal").strip()
    for referencia in referencias:
        encontrada = RE_PETICION_REVISION.fullmatch(referencia)
        if not encontrada:
            raise gestion_peticiones.ErrorPeticion(
                f"referencia de petición inválida: {referencia}; usa P-ID@revision"
            )
        pid, revision = encontrada.groups()
        if proceso:
            tipo_proceso, ref = proceso
            gestion_peticiones.validar_proceso(
                pid, int(revision), tipo_proceso, ref
            )
        else:
            gestion_peticiones.validar_para_orden(
                pid, carril, fm.get("tipo"), revision=int(revision)
            )
    return referencias


RE_NIVEL_TEST = re.compile(r"^\s*[-*]\s*\*\*Nivel de test:?\*\*(.*)$", re.M | re.I)


def nivel_de_test(texto):
    """Lo que se ha escrito de verdad en '**Nivel de test:**', o cadena vacía.

    Los huecos `<...>` de la plantilla NO cuentan: son la pregunta, no la respuesta. Se
    descuentan igual que en `prosa_real`, para que la puerta mire lo mismo que el resto.
    """
    m = RE_NIVEL_TEST.search(texto)
    if not m:
        return ""
    resto = MARCADOR.sub("", m.group(1)).strip()
    # El hueco de la plantilla ocupa VARIAS líneas: abre `<` aquí y cierra `>` tres líneas más
    # abajo, así que MARCADOR —que no cruza saltos de línea— no lo ve y lo dejaría pasar como
    # respuesta. Si lo que queda empieza por `<`, sigue siendo la pregunta, no la respuesta.
    if resto.startswith("<"):
        return ""
    return resto.strip(" .:·-")


RE_CRITERIO_PORTANTE = re.compile(r"^\s*[-*]\s*\*\*Criterio portante:?\*\*(.*)$", re.M | re.I)


def criterio_portante(texto):
    """Lo que se ha escrito de verdad en '**Criterio portante:**', o cadena vacía.

    Mismo molde que `nivel_de_test`, y por el mismo motivo: los huecos `<...>` de la
    plantilla son la pregunta, no la respuesta, y el de este campo ocupa varias líneas.
    """
    m = RE_CRITERIO_PORTANTE.search(texto)
    if not m:
        return ""
    resto = MARCADOR.sub("", m.group(1)).strip()
    if resto.startswith("<"):
        return ""
    return resto.strip(" .:·-")


def plantilla_de(clase, fm):
    """Qué plantilla es el MOLDE de esta unidad.

    Importa para `prosa_real`: compara el contrato contra su molde para descontar lo que sigue
    siendo plantilla. Si se compara contra otro molde, el texto fijo del molde de verdad no
    casa con nada y cuenta como contrato escrito — la puerta se abriría sola justo en las
    unidades más ligeras, que es donde más falta hace que no se abra.
    """
    if clase == "bug":
        return "bug.md"
    if (fm.get("carril") or "").strip() == "directo":
        return "directo.md"
    return "especificacion.md"


def _cmd_nueva(args, autoridad):
    tipo, slug = args.tipo, args.slug
    if tipo not in TIPOS:
        fail(f"tipo '{tipo}' fuera del vocabulario cerrado: {' | '.join(TIPOS)}")
        return 1
    if not RE_SLUG.match(slug):
        fail(f"slug '{slug}' inválido: debe casar con ^[a-z0-9][a-z0-9-]*$ "
             "(minúsculas, números y guiones; sin acentos ni espacios)")
        return 1

    if args.directo and getattr(args, "completo", False):
        fail("--directo y --completo son carriles opuestos: elige uno")
        return 1
    if getattr(args, "completo", False) and tipo == "bug":
        fail("un bug va por carril directo o normal (runbooks/bug.md); si es "
             "transversal, escala a decisión con el usuario en vez de --completo")
        return 1
    carril = ("directo" if args.directo
              else "completo" if getattr(args, "completo", False) else "normal")
    try:
        referencias = validar_origenes(args.desde, carril, tipo)
    except gestion_peticiones.ErrorPeticion as exc:
        fail(str(exc))
        return 1

    # Idempotencia: si ya hay una unidad con este slug, no se crea otra ni se pisa nada.
    ya = slug_ya_usado(slug)
    if ya:
        warn(f"ya existe una unidad con el slug '{slug}': {ya} — no toco nada")
        print(f"\n  Si de verdad es trabajo NUEVO, usa otro slug. Si quieres despacharla:\n"
              f"      python3 {rel(__file__)} despachar {Path(ya).name}")
        return 0

    nnn, _ = siguiente_nnn()
    autoridad.assert_owner()
    gestion_leases.failpoint("nueva_tras_nnn")
    nombre = f"{nnn}-{slug}"
    # Carril directo (runbooks/directo.md): cambia comportamiento pero encaja donde ya vive.
    # El molde es más corto; construye el padre y revisa un agente fresco. Carril completo
    # (regla 9): transversal/arriesgado/desconocido — misma especificación MÁS su
    # investigacion.md, que se rellena antes. Sin flag, el frontmatter nace "normal".
    carril_plantilla = "" if carril == "normal" else carril

    if tipo == "bug":
        # ADR-006: el bug es un fichero vivo en docs/bugs/, sin carpeta y sin archivarse.
        # Su molde es el mismo en los dos carriles: lo que cambia es el nivel de test y quién
        # revisa, no la ficha (un bug siempre necesita su par ROJO→VERDE).
        plantilla = PLANTILLAS / "bug.md"
        destino = BUGS / f"{nombre}.md"
        if destino.exists():
            warn(f"{rel(destino)} ya existe — no toco nada")
            return 0
        if not plantilla.exists():
            fail(f"falta la plantilla {rel(plantilla)}")
            return 1
        BUGS.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            rellenar(plantilla.read_text(encoding="utf-8"), nombre, nnn, tipo,
                     carril_plantilla, referencias),
            encoding="utf-8")
        creados = [destino]
        fichero_contrato = destino
    else:
        carpeta = TRABAJO / nombre
        if carpeta.exists():
            warn(f"{rel(carpeta)} ya existe — no toco nada")
            return 0
        molde = "directo.md" if args.directo else "especificacion.md"
        piezas = [(molde, "especificacion.md"), ("hallazgos.md", "hallazgos.md")]
        if carril == "completo":
            # La investigación de la unidad se rellena ANTES de la especificación (regla 9).
            piezas.append(("investigacion.md", "investigacion.md"))
        faltan = [origen for origen, _ in piezas if not (PLANTILLAS / origen).exists()]
        if faltan:
            fail(f"faltan plantillas en {rel(PLANTILLAS)}: {faltan}")
            return 1
        carpeta.mkdir(parents=True)
        creados = []
        # El molde del carril directo se copia COMO especificacion.md: el linter, el despacho y
        # el cierre siguen encontrando el mismo fichero. Lo que cambia es lo que hay dentro.
        for origen, nombre_destino in piezas:
            destino = carpeta / nombre_destino
            destino.write_text(
                rellenar((PLANTILLAS / origen).read_text(encoding="utf-8"),
                         nombre, nnn, tipo, carril_plantilla, referencias),
                encoding="utf-8")
            creados.append(destino)
        fichero_contrato = carpeta / "especificacion.md"

    tipo_proceso = "bug" if tipo == "bug" else "unidad"
    try:
        gestion_peticiones.enlazar_procesos(referencias, tipo_proceso, nombre)
    except gestion_peticiones.ErrorPeticion as exc:
        # Estos artefactos acaban de nacer y todavía no se han anunciado ni despachado. Si el
        # lote de orígenes no puede enlazarse completo, se retiran para no dejar media orden.
        if tipo == "bug":
            destino.unlink(missing_ok=True)
        else:
            shutil.rmtree(carpeta)
        fail(str(exc))
        return 1

    print(f"== Unidad {nombre} creada ({tipo}{', carril ' + carril if carril != 'normal' else ''}) ==")
    for c in creados:
        ok(f"creado {rel(c)}")
    contrato = ("Qué · Criterios R* · Cómo lo pruebas tú · Verificación · ficheros que posee"
                if carril == "directo" else
                "Qué · Criterios R* · Deltas al mapa · Verificación · ficheros que posee")
    if carril == "completo":
        print(f"\n  Siguientes pasos (en este orden — el worktree NO se crea todavía):\n"
              f"    0. Rellena {rel(carpeta / 'investigacion.md')} ANTES de la especificación:\n"
              f"       sus respuestas alimentan el Cómo y los criterios (regla 9).")
    else:
        print(f"\n  Siguientes pasos (en este orden — el worktree NO se crea todavía):")
    print(f"    1. Rellena el contrato en {rel(fichero_contrato)}\n"
          f"       ({contrato}).\n"
          f"    2. El visor de contratos se levanta SOLO al terminar este comando (abajo).\n"
          f"       El usuario lo lee, anota y aprueba ahí; su OK se escribe después como\n"
          f"       'aprobado: YYYY-MM-DD' en el frontmatter. A mano, si hiciera falta:\n"
          f"       `{COMANDO_VISOR_CONTRATOS}`. Sin esa fecha ni el rastro del visor no\n"
          f"       hay despacho.\n"
          f"    3. Rellena Contexto para el constructor y Plan de trabajo.\n"
          f"    4. python3 {rel(__file__)} despachar {nombre}\n"
          f"    5. Registra la unidad en ESTADO.md"
          f"{' e INDICE.md de bugs' if tipo == 'bug' else ''} (lo escribe el padre).")
    # R2 del bug 057: el contrato que acaba de nacer se ABRE, no se anuncia. Imprimir el
    # comando ya se hacía y no bastó: el 25-08 el padre pidió dos OK sin abrir nada.
    pendientes = contratos_pendientes(nombre)
    if pendientes:
        print()
        imprimir_lineas(abrir_visor_de_contratos(
            pendientes, getattr(args, "sin_navegador", False)))
    return 0


def cmd_nueva(args):
    try:
        with gestion_leases.LeaseManager(RAIZ).acquire("unit-namespace") as autoridad:
            return _cmd_nueva(args, autoridad)
    except gestion_leases.LeaseError as exc:
        fail(f"no puedo numerar otra unidad ahora: {exc}")
        return 1


# --------------------------------------------------------------------------- subcomando: despachar

def marcar_deuda(ruta, motivo):
    """Escribe la marca de deuda de spec y la emergencia declarada, tras el frontmatter.

    Idempotente. El motivo se guarda AQUÍ y no en un log aparte porque la ficha es lo único
    que el linter, el revisor y el usuario van a leer después: una emergencia sin nombre
    escrito es indistinguible de un atajo.
    """
    ruta = fichero_unidad_seguro(ruta)
    texto = leer_fichero_unidad(ruta)
    if "DEUDA DE SPEC" in texto:
        return False
    lineas = texto.splitlines()
    corte = 0
    if lineas and lineas[0].strip() == "---":
        for i, linea in enumerate(lineas[1:], start=1):
            if linea.strip() == "---":
                corte = i + 1
                break
    lineas[corte:corte] = ["", MARCA_DEUDA,
                           f"> **Emergencia declarada por el usuario ({HOY}):** {motivo}",
                           "> Deuda a pagar en 24 h (runbook `hotfix.md`); el linter la vigila."]
    escribir_fichero_unidad(ruta, "\n".join(lineas) + "\n")
    return True


def marcar_en_obra(ruta, documental=False):
    """estado → en_obra y actualizado → hoy: el despacho es lo que pone la unidad en obra."""
    ruta = fichero_unidad_seguro(ruta)
    texto = leer_fichero_unidad(ruta)
    texto = re.sub(r"^estado:\s*\S+", "estado: en_obra", texto, count=1, flags=re.M)
    texto = re.sub(r"^actualizado:\s*\S+", f"actualizado: {HOY}", texto, count=1, flags=re.M)
    if documental and not re.search(r"^ejecucion:", texto, flags=re.M):
        texto = texto.replace(
            "\n---\n", "\nejecucion: documental\n---\n", 1
        )
    escribir_fichero_unidad(ruta, texto)


def escribir_recibo_preparacion(destino, estado, hook=None, hook_sha256=None,
                                codigo_salida=None, motivo=None):
    """Persiste qué sabemos —y qué no— sobre el entorno recién creado."""
    recibo = {
        "schema": "worktree-readiness/v1",
        "unidad": destino.name,
        "worktree": f"worktrees/{destino.name}",
        "estado": estado,
        "preparacion_verificada": estado == "preparado",
        "hook": hook,
        "hook_sha256": hook_sha256,
        "codigo_salida": codigo_salida,
        "motivo": motivo,
    }
    ruta = RAIZ / ".runtime/worktree-readiness" / f"{destino.name}.json"
    gestion_peticiones.escribir_atomico(ruta, recibo)
    return ruta


# La búsqueda de bash vive en workspace_paths para que el despacho, el gate de deploy y
# el doctor usen el MISMO criterio: tres criterios distintos daban tres respuestas
# distintas en Windows, y las tres decían "no hay bash" con bash instalado al lado.
def orden_para_hook(gancho):
    """En POSIX el shebang ejecuta el hook solo; en Windows el shebang no existe:
    si el hook lo trae se ejecuta vía bash (viene con Git for Windows), y si no hay
    bash se dice en claro en vez de morir con WinError 193."""
    if gancho.suffix == ".py":
        return [sys.executable, str(gancho)]
    if os.name == "nt":
        with open(gancho, "rb") as stream:
            if stream.read(2) == b"#!":
                bash = workspace_paths.buscar_bash()
                if not bash:
                    raise OSError(
                        "en Windows este hook necesita bash (Git for Windows) "
                        "o un worktree-listo.py"
                    )
                return [bash, str(gancho)]
    return [str(gancho)]


# El hook corre con los leases de la unidad tomados: sin tope, un hook colgado retiene
# los candados de todas las sesiones. 10 min dan para un `npm ci`/`pip install` normal;
# un entorno que tarde más de verdad lo sube por entorno (y los tests lo bajan).
TOPE_HOOK_SEGUNDOS = int(os.environ.get("IR_TOPE_HOOK_SEGUNDOS", "600"))


def preparar_worktree(destino):
    """Ejecuta, si existe, el gancho explícito del proyecto y devuelve si permite despachar.

    Un worktree recién creado es código sin entorno: sin dependencias instaladas, sin base de
    datos de pruebas, sin lo que el stack necesite. El constructor que aterriza ahí ve fallar
    tests que en main pasan, y los usa como vara de medir durante horas antes de descubrir que
    medía el entorno. El método no sabe montar eso —depende del stack— pero sí sabe CUÁNDO hay
    que montarlo: justo aquí.

    El método no instala nada por su cuenta. Si el proyecto deja `worktree-listo` (ejecutable)
    o `worktree-listo.py` en la raíz, se ejecuta con el worktree como argumento y como cwd. El
    fichero debe ser regular, no un enlace, y estar directamente en la raíz. Un fallo bloquea
    el despacho. La ausencia es válida, pero se registra como `sin_hook`, no como entorno listo.
    """
    try:
        raiz_real = RAIZ.resolve(strict=True)
        base_real = WORKTREES.resolve(strict=True)
        destino_real = destino.resolve(strict=True)
    except OSError:
        ruta = escribir_recibo_preparacion(
            destino, "fallido", motivo="worktree_no_confinado"
        )
        fail(f"preparación bloqueada: no pude resolver el worktree; recibo {rel(ruta)}")
        return False
    if (destino.is_symlink() or not destino.is_dir()
            or destino_real.parent != base_real or base_real.parent != raiz_real):
        ruta = escribir_recibo_preparacion(
            destino, "fallido", motivo="worktree_no_confinado"
        )
        fail(f"preparación bloqueada: el worktree no está confinado; recibo {rel(ruta)}")
        return False

    encontrados = []
    for nombre in ("worktree-listo", "worktree-listo.py"):
        gancho = RAIZ / nombre
        try:
            metadatos = gancho.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadatos.st_mode) or not stat.S_ISREG(metadatos.st_mode):
            ruta = escribir_recibo_preparacion(
                destino, "fallido", hook=nombre, motivo="hook_no_regular"
            )
            fail(f"preparación bloqueada: {nombre} es un enlace simbólico o no es un fichero "
                 f"regular confinado; recibo {rel(ruta)}")
            return False
        if gancho.parent.resolve(strict=True) != raiz_real:
            ruta = escribir_recibo_preparacion(
                destino, "fallido", hook=nombre, motivo="hook_no_confinado"
            )
            fail(f"preparación bloqueada: {nombre} queda fuera de la raíz; recibo {rel(ruta)}")
            return False
        encontrados.append((nombre, gancho))

    if not encontrados:
        ruta = escribir_recibo_preparacion(destino, "sin_hook", motivo="hook_ausente")
        print(f"  INFO preparación del entorno: sin_hook · no verificada · recibo {rel(ruta)}")
        return True
    if len(encontrados) != 1:
        ruta = escribir_recibo_preparacion(
            destino, "fallido", motivo="hooks_ambiguos"
        )
        fail(f"preparación bloqueada: existen worktree-listo y worktree-listo.py; deja un "
             f"único contrato ejecutable · recibo {rel(ruta)}")
        return False

    nombre, gancho = encontrados[0]
    if gancho.suffix != ".py" and not os.access(gancho, os.X_OK):
        ruta = escribir_recibo_preparacion(
            destino, "fallido", hook=nombre, motivo="hook_no_ejecutable"
        )
        fail(f"preparación bloqueada: {nombre} no es ejecutable; recibo {rel(ruta)}")
        return False
    huella = hashlib.sha256(gancho.read_bytes()).hexdigest()
    print(f"\n  Preparando el entorno del worktree con {nombre}…", flush=True)
    try:
        orden = orden_para_hook(gancho)
        # stdin CERRADO, tope de tiempo y salida a FICHERO: este hook corre con los
        # leases de la unidad ya tomados. Un `npm install` que pregunta, un ssh pidiendo
        # host-key o cualquier `read` colgaba aquí el despacho reteniendo los candados —
        # el "subagente esperando una aprobación que no llega" del feedback de campo
        # (ADR-026). Y la salida NO se hereda: un nieto huérfano que sobreviva al kill
        # (msys rompe la cadena de padres, killpg no existe en Windows) retendría la
        # tubería del agente padre y lo dejaría colgado leyendo; con un fichero de
        # .runtime/ retiene el fichero y a nadie más (regla 12: outputs por ruta).
        registro = RAIZ / ".runtime/worktree-readiness" / f"{destino.name}.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "wb") as salida_hook:
            proceso = subprocess.Popen(
                [*orden, str(destino_real)], cwd=str(destino_real), shell=False,
                close_fds=True, stdin=subprocess.DEVNULL,
                stdout=salida_hook, stderr=subprocess.STDOUT,
                start_new_session=(os.name == "posix"),
            )
            try:
                codigo = proceso.wait(timeout=TOPE_HOOK_SEGUNDOS)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proceso.pid, signal.SIGKILL)
                else:
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(proceso.pid)],
                        capture_output=True,
                    )
                    proceso.kill()
                proceso.wait()
                ruta = escribir_recibo_preparacion(
                    destino, "fallido", hook=nombre, hook_sha256=huella,
                    motivo="hook_timeout",
                )
                fail(f"preparación bloqueada: {nombre} superó su tope de "
                     f"{TOPE_HOOK_SEGUNDOS} s sin terminar (su stdin va cerrado a "
                     f"propósito: si esperaba input, ese es el bug del hook); su salida "
                     f"quedó en {rel(registro)} · recibo {rel(ruta)}")
                return False
        print(f"  salida del hook: {rel(registro)}")
    except OSError as exc:
        ruta = escribir_recibo_preparacion(
            destino, "fallido", hook=nombre, hook_sha256=huella,
            motivo="error_ejecucion",
        )
        fail(f"preparación bloqueada: no pude ejecutar {nombre} ({exc}); recibo {rel(ruta)}")
        return False
    if codigo:
        ruta = escribir_recibo_preparacion(
            destino, "fallido", hook=nombre, hook_sha256=huella,
            codigo_salida=codigo, motivo="hook_rojo",
        )
        fail(f"preparación bloqueada: {nombre} terminó con código {codigo}; "
             f"recibo {rel(ruta)}")
        return False
    ruta = escribir_recibo_preparacion(
        destino, "preparado", hook=nombre, hook_sha256=huella, codigo_salida=0
    )
    ok(f"entorno preparado por {nombre} · recibo verificable {rel(ruta)}")
    return True


def huella_ficha(ruta):
    segura = fichero_unidad_seguro(ruta)
    return hashlib.sha256(segura.read_bytes()).hexdigest()


def ficha_conserva_huella(ruta, esperada):
    try:
        return huella_ficha(ruta) == esperada
    except (OSError, workspace_paths.WorkspacePathError):
        return False


class AutoridadDespacho:
    """Une el lease de unidad con los leases de recursos adquiridos después."""

    def __init__(self, *grupos):
        self.grupos = tuple(grupo for grupo in grupos if grupo is not None)

    def assert_owner(self):
        for grupo in self.grupos:
            grupo.assert_owner()


def _cmd_despachar(args, autoridad, snapshot=None):
    nombre = args.unidad.strip("/")
    if not RE_UNIDAD.match(nombre):
        fail(f"'{nombre}' no tiene forma NNN-slug (tres dígitos, guion, slug)")
        return 1

    # --- Precondición 1: la unidad existe y su frontmatter es válido -----------------------
    unidad = buscar_unidad(nombre)
    if unidad is None:
        fail(f"no existe la unidad {nombre} (ni carpeta en 05-trabajo/ ni ficha en docs/bugs/)")
        err(f"\n  Créala primero:  python3 {rel(__file__)} nueva <tipo> {nombre[4:]}")
        return 1
    ruta, fm = unidad["ruta"], unidad["fm"]
    if snapshot is not None:
        ruta_esperada, huella_esperada = snapshot
        if ruta != ruta_esperada or not ficha_conserva_huella(ruta, huella_esperada):
            fail(
                f"{nombre}: la ficha cambió mientras se adquirían sus recursos; "
                "no se despacha con una allowlist obsoleta"
            )
            return 1
    else:
        huella_esperada = huella_ficha(ruta)
    if not fm:
        fail(f"{rel(ruta)} no tiene frontmatter válido (debe abrir con --- y cerrar con ---)")
        return 1
    if fm.get("unidad") != nombre:
        fail(f"{rel(ruta)}: el frontmatter dice unidad '{fm.get('unidad')}' y la carpeta/ficha "
             f"dice '{nombre}' — arréglalo antes de despachar")
        return 1
    if fm.get("tipo") not in TIPOS:
        fail(f"{rel(ruta)}: tipo '{fm.get('tipo')}' fuera del vocabulario cerrado")
        return 1
    if fm.get("estado") not in ESTADOS:
        fail(f"{rel(ruta)}: estado '{fm.get('estado')}' fuera del vocabulario cerrado")
        return 1
    ok(f"{nombre} existe con frontmatter válido ({fm.get('tipo')} · {fm.get('estado')})")

    try:
        revalidar_origenes(fm)
    except gestion_peticiones.ErrorPeticion as exc:
        fail(f"{rel(ruta)}: {exc}")
        return 1

    if args.documental and fm.get("tipo") not in {
        "auditoria", "investigacion", "documentacion", "bug"
    }:
        fail(
            "--documental solo vale para auditoria, investigacion, documentacion "
            "o un bug del META-repo que NO toca el repositorio de código"
        )
        return 1
    if args.documental and fm.get("tipo") == "bug":
        # Un bug del propio meta-repo (un runbook roto, un script del método, una ficha) no
        # necesita rama ni worktree de código: despacharlo como código creaba un worktree
        # inútil y un cierre imposible (pasó dos veces en campo). La prueba ejecutable de que
        # es meta es su `ficheros:`: declarado, y sin una sola ruta dentro de main/.
        rutas_bug = ficheros_de(fm)
        if not rutas_bug:
            fail(
                "--documental en un bug exige declarar `ficheros:` en la ficha "
                "(todas las rutas fuera de main/): es la prueba de que el bug es del meta-repo"
            )
            return 1
        dentro_codigo = sorted(r for r in rutas_bug if r == "main" or r.startswith("main/"))
        if dentro_codigo:
            fail(
                f"--documental no vale: la ficha declara rutas del repo de código "
                f"({', '.join(dentro_codigo)}). Un bug que toca main/ se despacha normal"
            )
            return 1
    if args.documental and args.force:
        fail("--documental no se combina con --force; un hotfix siempre toca código")
        return 1

    texto_unidad = leer_fichero_unidad(ruta)

    # --- Precondición 2: si se invoca --force, que sea de verdad una emergencia --------------
    # --force es la ÚNICA válvula que salta las puertas 3 (aprobación) y 4 (contrato escrito),
    # y por eso se acota a lo que `hotfix.md` permite: producción caída. Sin las tres cosas
    # (bug + P0 triado + motivo escrito) no es una emergencia, es un atajo con otro nombre.
    motivo = (args.motivo or "").strip()
    if args.force:
        severidad = severidad_declarada(texto_unidad)
        problemas = []
        if fm.get("tipo") != "bug":
            problemas.append(f"la unidad es tipo '{fm.get('tipo')}', y un hotfix es SIEMPRE "
                             f"un bug (plantillas/bug.md → docs/bugs/)")
        if severidad != "P0":
            problemas.append(f"la ficha no declara severidad P0 "
                             f"(leído: {severidad or 'sin triar'}) — P0 es producción caída "
                             f"para usuarios reales, no 'urgente'")
        if not motivo:
            problemas.append("falta --motivo: la emergencia se escribe en la ficha con "
                             "nombre y apellidos")
        if problemas:
            fail(f"--force rechazado para {nombre}: no es un hotfix")
            for p in problemas:
                err(f"       · {p}")
            err(f"\n  --force NO es un bypass de la aprobación: es la válvula de producción\n"
                f"  caída, y solo el usuario declara la emergencia. Lee\n"
                f"  {rel(RAIZ / 'docs/00-metodo/runbooks/hotfix.md')}.\n"
                f"  Si de verdad hay sangría:\n"
                f"      python3 {rel(__file__)} despachar {nombre} --force "
                f"--motivo \"produccion caida: ...\"\n"
                f"  Si no la hay, es un bug normal: rellena la ficha, que el usuario la\n"
                f"  apruebe (aprobado: {HOY}) y despacha sin --force.")
            return 1
        warn(f"--force aceptado: bug P0 con emergencia declarada — «{motivo}»")

    # --- Precondición 3: el usuario ha aprobado el contrato (regla dura: lo aprueba él) ------
    aprobado = aprobacion(fm)
    if aprobado is None and not args.force:
        fail(f"{rel(ruta)}: sin aprobación del usuario (aprobado: "
             f"{fm.get('aprobado') or 'ausente'})")
        err(f"\n  EL CONTRATO LO APRUEBA EL USUARIO, NO EL AGENTE. Que la spec esté escrita\n"
            f"  no la convierte en acordada: la escribió el mismo que quiere despacharla.\n"
            f"  Para desbloquear: enséñale el contrato al usuario y, cuando dé su OK, que\n"
            f"  quede escrita la fecha en el frontmatter de {rel(ruta)}:\n"
            f"      aprobado: {HOY}\n"
            f"  Producción caída (bug P0): runbooks/hotfix.md → --force --motivo \"...\".")
        return 1
    if aprobado:
        ok(f"contrato aprobado por el usuario el {aprobado}")
        # R3 del bug 054: la fecha sola no basta — sin rastro de que ALGUIEN abrió el visor
        # de contratos y lo vio ANTES (o el mismo día) de aprobar, "aprobado: {fecha}" puede
        # ser un agente tecleando la fecha a ciegas. `--force` (hotfix P0) sigue siendo la
        # única válvula que la salta.
        vistas_a_tiempo = [v for v in rastro_visor_contrato(nombre) if v <= aprobado]
        if not vistas_a_tiempo and not args.force:
            fail(f"{rel(ruta)}: no consta que el visor de contratos mostrara {nombre} "
                 f"en o antes de 'aprobado: {aprobado}'")
            err(f"\n  NADIE APRUEBA A CIEGAS. La fecha en 'aprobado:' no prueba que el usuario\n"
                f"  viera el contrato: la prueba es el rastro del visor. SALIDA: levanta el\n"
                f"  visor de contratos, enséñale el contrato al usuario y que vuelva a dar su\n"
                f"  OK:\n"
                f"      {COMANDO_VISOR_CONTRATOS}\n"
                f"  Si el 'aprobado: {aprobado}' es de una fecha pasada, abrir el visor hoy NO "
                f"basta: pide el OK otra vez y actualiza 'aprobado:' a la fecha de hoy.\n"
                f"  Producción caída (bug P0): runbooks/hotfix.md → --force --motivo \"...\".")
            return 1
        if vistas_a_tiempo:
            ok(f"visor de contratos mostró {nombre} el {max(vistas_a_tiempo)} "
               f"(≤ aprobado: {aprobado})")

    # --- Precondición 4: el contrato está escrito (la spec va antes que la rama) -------------
    plantilla = PLANTILLAS / plantilla_de(unidad["clase"], fm)
    texto_plantilla = ""
    if plantilla.exists():
        # Se compara contra la plantilla YA RELLENADA con los datos de esta unidad (NNN, slug,
        # tipo, fecha): si no, esas mismas líneas dejarían de casar y contarían como prosa.
        texto_plantilla = rellenar(plantilla.read_text(encoding="utf-8"),
                                   nombre, nombre[:3], fm.get("tipo", ""))
    prosa = prosa_real(texto_unidad, texto_plantilla)
    if prosa < MINIMO_PROSA:
        if not args.force:
            fail(f"{rel(ruta)} sigue siendo la plantilla: solo {prosa} caracteres de prosa propia "
                 f"(mínimo {MINIMO_PROSA})")
            if unidad["clase"] == "bug":
                que_falta = ("el Reporte: qué esperaba el usuario, qué pasa de verdad (con "
                             "ejemplo\n  concreto), severidad y triaje")
            elif (fm.get("carril") or "").strip() == "directo":
                que_falta = ("el Qué, los criterios R*, cómo lo prueba el usuario y la\n"
                             "  verificación")
            else:
                que_falta = "el Qué, los criterios R*, los deltas al mapa y la\n  verificación"
            err(f"\n  LA SPEC VA ANTES QUE LA RAMA. Sin contrato escrito y aprobado por el\n"
                f"  usuario no hay worktree: un constructor sin contrato inventa el suyo.\n"
                f"  Rellena en {rel(ruta)} {que_falta};\n"
                f"  después vuelve a ejecutar este comando.\n"
                f"  Producción caída: solo un bug P0 con --force --motivo \"...\" (hotfix.md),\n"
                f"  y la deuda se paga en 24 h.")
            return 1
        err(f"  WARN --force: despacho SIN contrato completo ({prosa}/{MINIMO_PROSA} caracteres "
            f"de prosa).")
    else:
        ok(f"contrato escrito ({prosa} caracteres de prosa propia ≥ {MINIMO_PROSA})")

    # La marca se escribe SIEMPRE que se acepta --force, tenga o no prosa la ficha: lo que se
    # ha saltado (la aprobación previa del usuario) es deuda igual, y sin marca el linter no
    # puede vigilarla.
    if args.force:
        autoridad.assert_owner()
        if not ficha_conserva_huella(ruta, huella_esperada):
            fail(f"{nombre}: la ficha cambió antes de registrar la deuda; no toco nada")
            return 1
        if marcar_deuda(ruta, motivo):
            ok(f"deuda de hotfix y emergencia declarada escritas en {rel(ruta)}")
        else:
            warn(f"{rel(ruta)} ya tenía marca de deuda sin pagar: no la piso "
                 f"(págala antes de abrir más trabajo — hotfix.md)")
        huella_esperada = huella_ficha(ruta)

    # --- Precondición 4bis: el nivel de test está ELEGIDO, no dejado a la costumbre ----------
    # ADR-015 creó este freno y lo dejó en la plantilla, donde no lo comprobaba nadie: la línea
    # se quedaba tal cual y `prosa_real` la descontaba como plantilla, así que la puerta de los
    # 200 caracteres pasaba igual. Un freno que ningún script mira es prosa, y el propio método
    # dice que la prosa se olvida. Sin nivel declarado, el constructor hace "de todo por si
    # acaso": tests de integración y end-to-end para cambiar una regla de negocio.
    if unidad["clase"] != "bug":     # el bug ya tiene su nivel fijado: el par ROJO→VERDE
        nivel = nivel_de_test(texto_unidad)
        if not nivel:
            if not args.force:
                fail(f"{rel(ruta)}: §Verificación sin '**Nivel de test:**' relleno")
                err("\n  El nivel de test se ELIGE y se justifica en una línea (ADR-015):\n"
                    "  unitario si es una regla de negocio · de integración si cruza una\n"
                    "  frontera (base de datos, servicio, API) · end-to-end SOLO si cruza la\n"
                    "  aplicación de punta a punta. Un test que no puede fallar por culpa de\n"
                    "  ESTE cambio no se escribe: infla la suite, tarda y no protege nada.\n"
                    "  Sin esta línea el constructor escribe de todo por si acaso, que es\n"
                    "  exactamente lo que hace que una tarea pequeña dure horas.")
                return 1
            warn("nivel de test sin declarar: --force lo deja pasar (deuda del hotfix)")
        else:
            ok(f"nivel de test declarado: {nivel[:60]}")

    # --- Precondición 4ter: el criterio PORTANTE está declarado (ADR-030) -------------------
    # El cierre exige la contraprueba —romper a propósito lo que el criterio protege y enseñar
    # el rojo— sobre UN criterio. Si se elige al llegar al cierre, lo elige quien construyó, y
    # elegirá el más fácil de romper: se declara aquí, antes de que exista una línea de código.
    # Acotado a normal y completo a propósito: en directo y exprés no se pide (el carril entero
    # existe para no pagar ceremonia) y en bug ya está, en el par ROJO→VERDE del paso 7.
    # Sin válvula `--force`: esa es la de producción caída, y solo la abre un bug P0, que no
    # paga esta puerta.
    carril_unidad = (fm.get("carril") or "normal").strip().lower()
    modo_unidad = (fm.get("ejecucion") or "").strip().lower()
    if (unidad["clase"] != "bug" and carril_unidad in ("normal", "completo")
            and modo_unidad != "expres"):
        portante = criterio_portante(texto_unidad)
        if not portante:
            fail(f"{rel(ruta)}: §Verificación sin '**Criterio portante:**' relleno — "
                 f"Arréglalo: escribe `**Criterio portante:** R-n` en §Verificación de {rel(ruta)} "
                 f"y vuelve a ejecutar: python3 docs/00-metodo/scripts/unidad.py despachar {args.unidad}")
            err("\n  Declara CUÁL de los R* es el criterio portante: el que, si no estuviera\n"
                "  implementado, deja el resto sin sentido. Uno solo, nombrado como `R-n`.\n"
                "  Al cerrar hay que DEMOSTRAR que su test muerde —romperlo a propósito, pegar\n"
                "  el rojo, restaurar y enseñar el árbol intacto (ADR-030)—, y elegirlo\n"
                "  entonces es elegir el que más fácil sea de romper. Un test vacuo, el que\n"
                "  pasa exista o no el comportamiento, atraviesa hoy la revisión firmada, la\n"
                "  suite completa y el OK del usuario sin que nadie lo note.\n"
                "  En carril directo y exprés no se pide; en bug tampoco (runbooks/bug.md, 7).")
            return 1
        ok(f"criterio portante declarado: {portante[:60]}")

    # --- Precondición 5: trabajo en vuelo (regla 5: UNA unidad por defecto) ------------------
    # Las documentales quedan fuera del censo de vuelo: la regla 5 lo dice («las --documental
    # tampoco: pueden ir en paralelo») y contarlas bloqueaba despachos legítimos por tope
    # (caso de campo, 05-08: una auditoría documental aparcada consumía cupo de constructor).
    activas = sorted(n for n, u in censo().items()
                     if n != nombre and u["fm"].get("estado") in EN_VUELO
                     and (u["fm"].get("ejecucion") or "").strip() != "documental")
    if activas and not args.paralelo:
        fail(f"ya hay {len(activas)} unidad(es) en vuelo: {', '.join(activas)}")
        err(f"\n  Regla 5: UNA unidad en vuelo por defecto — el límite real es la atención, no\n"
            f"  la máquina. Cierra la que está en obra, o repite con --paralelo si esta unidad\n"
            f"  NO comparte ningún fichero con ella (declarado en el frontmatter 'ficheros').")
        return 1
    # Sin tope numérico (ADR-027): con --paralelo caben tantas unidades como quepan sin
    # chocar — el límite lo pone el propio grafo de ficheros del trabajo pedido, no una
    # constante. El único gate real es la disjunción de ficheros que sigue abajo.
    # La regla "en paralelo jamás se comparten ficheros" la comprobaba un WARN dirigido a un
    # humano, o sea a nadie: se despachaban dos unidades sobre el mismo fichero sin que nada
    # avisara. Aquí se verifica y se bloquea. Una unidad --documental no toca el repo de
    # código, así que no tiene ficheros que declarar y queda fuera de la comprobación.
    if activas and not args.documental:
        mios = ficheros_de(fm)
        censo_actual = censo()
        if not mios:
            fail(f"{rel(ruta)}: 'ficheros:' vacío y hay trabajo en vuelo ({', '.join(activas)})")
            err("\n  Para trabajar en paralelo hay que declarar qué ficheros POSEE esta unidad:\n"
                "  sin declaración no hay forma de comprobar que no pisáis lo mismo, y el\n"
                "  guardián daría el visto bueno sin haber mirado nada.\n"
                "      ficheros: [ruta/uno.py, ruta/dos.py]")
            return 1
        for otra in activas:
            comunes = mios & ficheros_de(censo_actual[otra]["fm"])
            if comunes:
                fail(f"{nombre} y {otra} comparten ficheros declarados: {sorted(comunes)}")
                err("\n  Dos unidades en paralelo JAMÁS comparten fichero: el segundo merge\n"
                    "  llega a un fichero que ya no es el que leyó su constructor. Los hotspots\n"
                    "  (migraciones, rutas, modelos compartidos, manifiestos, lockfiles) van\n"
                    "  SIEMPRE en secuencia: cierra una, o quítale el fichero a esta unidad y\n"
                    "  que lo proponga en hallazgos.md para que lo aplique el padre al cerrar.")
                return 1
        ok(f"ficheros disjuntos de {', '.join(activas)} ({len(mios)} declarado(s))")
    elif activas:
        warn(f"despacho documental en paralelo con: {', '.join(activas)} (no toca código)")
    else:
        ok("no hay ninguna otra unidad en vuelo")

    # --- Guía (ADR-026): en un brownfield, la ADOPCIÓN va primero ---------------------------
    # La puerta de adopcion.md era prosa que nadie ejecutaba: los despachos de código
    # salían sin gap-map y la fase 3 se comía el repo entero (caso de campo 08-08). Avisa,
    # no encierra: el despacho sigue, con la deuda nombrada.
    if not args.documental:
        bias = RAIZ / "docs/01-constitucion/bias.md"
        adopcion = RAIZ / "docs/03-investigacion/ADOPCION.md"
        if (bias.is_file() and not adopcion.is_file()
                and "brownfield" in bias.read_text(encoding="utf-8",
                                                   errors="replace").lower()):
            warn(f"brownfield sin {rel(adopcion)}: la ADOPCIÓN es la primera unidad del "
                 f"workspace (runbook adopcion.md) — sin ella no hay gap-map código↔flujos "
                 f"y la fase 3 no está acotada. Este despacho sigue, pero esa deuda no se "
                 f"paga sola.")

    if args.documental:
        autoridad.assert_owner()
        if not ficha_conserva_huella(ruta, huella_esperada):
            fail(f"{nombre}: la ficha cambió antes de marcarla en obra; no toco nada")
            return 1
        tipo_proceso = "bug" if unidad["clase"] == "bug" else "unidad"
        try:
            # Una documental no crea rama, pero SÍ deja registro de despacho: es lo que
            # permite al cierre saber que su modo es documental sin creerse el frontmatter
            # (R3 y R5 del bug 034).
            gestion_peticiones.registrar_despacho(
                revalidar_origenes(fm, proceso=(tipo_proceso, nombre)),
                tipo_proceso,
                nombre,
                carril=(fm.get("carril") or "normal").strip(),
                ejecucion="documental",
                ficheros=sorted(ficheros_de(fm)),
            )
        except gestion_peticiones.ErrorPeticion as exc:
            fail(f"no pude registrar el despacho documental; no toco la ficha: {exc}")
            return 1
        marcar_en_obra(ruta, documental=True)
        ok(f"{rel(ruta)}: estado → en_obra · ejecución documental (sin rama ni worktree)")
        print(
            "\n  Siguientes pasos:\n"
            f"    1. Lanza el subagente documental con {rel(ruta)} como punto de entrada.\n"
            "       Solo puede leer main/ y escribir en la carpeta de esta unidad.\n"
            "    2. Actualiza ESTADO.md con la unidad en obra (lo escribe el padre).\n"
            f"    3. python3 {rel(RAIZ / 'docs/00-metodo/scripts/lint_metodo.py')}"
        )
        return 0

    # --- Precondición 6: el repo de código está listo y la rama/worktree no existen ----------
    repo, rama_principal = repo_codigo()
    if git(repo, "rev-parse", "--is-inside-work-tree", silencioso=True)[0] != 0:
        fail(f"no encuentro el clon del repo de código en {rel(repo)} (repos.yaml → ruta_local)")
        err("\n  Ejecuta primero:  python3 setup.py")
        return 1
    tiene_origin = git(
        repo, "remote", "get-url", "origin", silencioso=True
    )[0] == 0
    if tiene_origin:
        codigo, salida = git(repo, "fetch", "origin", rama_principal)
        if codigo != 0:
            fail(
                f"no pude actualizar origin/{rama_principal}; no creo trabajo desde "
                f"una referencia posiblemente antigua:\n{salida}"
            )
            return 1
        ok(f"origin/{rama_principal} actualizado antes de crear la rama")
    destino = WORKTREES / nombre
    if destino.exists():
        fail(f"{rel(destino)} ya existe — no piso worktrees (¿cierre a medias?)")
        return 1
    if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{nombre}", silencioso=True)[0] == 0:
        fail(f"la rama '{nombre}' ya existe en {rel(repo)} — el NNN no se reutiliza")
        return 1
    base_remota = f"origin/{rama_principal}"
    if git(repo, "rev-parse", "--verify", "--quiet",
           f"refs/remotes/{base_remota}", silencioso=True)[0] == 0:
        base = base_remota
    elif git(repo, "rev-parse", "--verify", "--quiet",
             f"refs/heads/{rama_principal}", silencioso=True)[0] == 0:
        base = rama_principal
    else:
        fail(f"no existe la rama principal '{rama_principal}' en {rel(repo)}")
        err("\n  Crea o recupera la rama principal antes de despachar trabajo.")
        return 1
    ok(f"repo de código listo en {rel(repo)} (base: {base})")
    base_sha = git(repo, "rev-parse", base, silencioso=True)[1].strip()
    if not base_sha:
        fail(f"no pude fijar el SHA base de {base}")
        return 1

    # --- Acción: rama + worktree ------------------------------------------------------------
    gestion_leases.failpoint("despachar_antes_accion")
    autoridad.assert_owner()
    if not ficha_conserva_huella(ruta, huella_esperada):
        fail(
            f"{nombre}: la ficha cambió después de validar sus recursos; "
            "no creo rama ni worktree"
        )
        return 1
    WORKTREES.mkdir(parents=True, exist_ok=True)
    codigo, salida = git(repo, "worktree", "add", str(destino), "-b", nombre, base)
    if codigo != 0:
        fail(f"git worktree add falló:\n{salida}")
        return 1
    ok(f"worktree {rel(destino)} en la rama {nombre}")
    if not preparar_worktree(destino):
        quitado = git(repo, "worktree", "remove", "--force", str(destino), silencioso=True)[0]
        borrada = git(repo, "branch", "-D", nombre, silencioso=True)[0]
        if quitado or borrada:
            fail("despacho bloqueado y preparación fallida; revisa rama/worktree residual antes "
                 "de reintentar")
        else:
            fail("despacho bloqueado por preparación fallida; rama y worktree deshechos")
        return 1
    autoridad.assert_owner()
    if not ficha_conserva_huella(ruta, huella_esperada):
        git(repo, "worktree", "remove", "--force", str(destino), silencioso=True)
        git(repo, "branch", "-D", nombre, silencioso=True)
        fail(
            f"{nombre}: la ficha cambió durante la preparación del entorno; "
            "deshice rama y worktree"
        )
        return 1
    tipo_proceso = "bug" if unidad["clase"] == "bug" else "unidad"
    try:
        # R5 (034): el despacho registra también CARRIL, MODO y FICHEROS. El cierre los lee
        # de aquí y no del frontmatter, que lo escribe el agente al que vigila.
        gestion_peticiones.registrar_despacho(
            revalidar_origenes(fm, proceso=(tipo_proceso, nombre)),
            tipo_proceso,
            nombre,
            carril=(fm.get("carril") or "normal").strip(),
            ejecucion=(fm.get("ejecucion") or "").strip(),
            ficheros=sorted(ficheros_de(fm)),
            base_sha=base_sha,
            principal=rama_principal,
        )
    except gestion_peticiones.ErrorPeticion as exc:
        git(repo, "worktree", "remove", "--force", str(destino), silencioso=True)
        git(repo, "branch", "-D", nombre, silencioso=True)
        fail(f"no pude registrar el origen de la rama; deshice el despacho: {exc}")
        return 1
    ok(f"origen de rama registrado: {base_sha[:8]} en {rama_principal}")
    marcar_en_obra(ruta)
    ok(f"{rel(ruta)}: estado → en_obra · actualizado → {HOY}")

    if (fm.get("carril") or "").strip() == "directo":
        paso_obra = (
            f"    1. Construye el padre en {rel(destino)}, a la vista del usuario "
            f"(ADR-017).\n       Al terminar revisa un agente fresco que no construyó."
        )
    else:
        launcher = str((RAIZ / "docs/00-metodo/scripts/ejecucion.py").resolve())
        prompt = "Lee el contrato canónico y ejecuta solo su plan aprobado"
        paso_obra = (
            "    1. Lanza el constructor por el control plane canónico (elige un harness):\n"
            f"       python3 {launcher} lanzar {nombre} --harness claude --rol constructor "
            f"--prompt \"{prompt}\"\n"
            f"       python3 {launcher} lanzar {nombre} --harness codex --rol constructor "
            f"--prompt \"{prompt}\"\n"
            f"       El launcher deriva y verifica {rel(destino)}; no pases cwd ni argv a mano.\n"
            f"       Tarda lo que tarde la unidad: lánzalo en SEGUNDO PLANO y sigue su recibo\n"
            f"       en .runtime/ejecucion/ — un shell con tope corto (p. ej. 10 min) lo\n"
            f"       mataría a mitad y lo verías como «esperando una aprobación que no llega»."
        )
    print(f"\n  Siguientes pasos:\n{paso_obra}\n"
          f"    2. Actualiza ESTADO.md con la unidad en obra (lo escribe el padre).\n"
          f"    3. python3 {rel(RAIZ / 'docs/00-metodo/scripts/lint_metodo.py')}")
    return 0


def cmd_despachar(args):
    nombre = args.unidad.strip("/")
    manager = gestion_leases.LeaseManager(RAIZ)
    try:
        # Orden TOCTOU: la ficha queda serializada antes de decidir qué recursos posee.
        with manager.acquire(f"unit:{nombre}") as autoridad_unidad:
            unidad = buscar_unidad(nombre) if RE_UNIDAD.match(nombre) else None
            snapshot = None
            recursos = []
            if unidad and unidad.get("fm"):
                snapshot = (unidad["ruta"], huella_ficha(unidad["ruta"]))
                recursos = [
                    f"resource:{ruta}" for ruta in sorted(ficheros_de(unidad["fm"]))
                ]
            gestion_leases.failpoint("despachar_tras_leer_recursos")
            contexto = (
                manager.acquire(recursos) if recursos else contextlib.nullcontext(None)
            )
            with contexto as autoridad_recursos:
                autoridad = AutoridadDespacho(autoridad_unidad, autoridad_recursos)
                autoridad.assert_owner()
                return _cmd_despachar(args, autoridad, snapshot=snapshot)
    except gestion_leases.LeaseError as exc:
        fail(f"la unidad o uno de sus recursos ya tiene propietario: {exc}")
        return 1


# --------------------------------------------------------------------------- subcomando: cerrar

# La línea de veredicto de hallazgos.md y la de revisión de una ficha de bug. Si el valor
# conserva el menú de la plantilla ("LIMPIO | HUECOS DE CORRECCIÓN"), nadie ha revisado nada:
# mismo truco que `severidad_declarada`, porque una plantilla intacta no es una decisión.
RE_VEREDICTO = re.compile(r"^\s*[-*]?\s*\**\s*(?:Veredicto|Revisi[oó]n)[^:\n]*:\s*(.+)$",
                          re.M | re.I)
# Marca de cosecha, tolerante al énfasis markdown: `→ promovido a X` y `→ **descartado** (…)`.
RE_COSECHA = re.compile(r"→\s*\**\s*(promovido|descartado)", re.I)
LINEA_OK_USUARIO = "- **Validación del usuario sobre la app corriendo:**"


def fecha_ok(valor):
    """Fecha ISO real y no futura, o None. El OK del usuario no se firma por adelantado."""
    valor = (valor or "").strip().strip("`'\"")
    if not RE_FECHA.match(valor):
        return None
    try:
        dia = datetime.date.fromisoformat(valor)
    except ValueError:
        return None
    return None if dia > datetime.date.today() else valor


# --------------------------------------------------------- unidad 033: puertas con ejecutor

# Toda puerta nueva de la unidad 033 escribe su vía de salida detrás de esta marca. Una
# puerta sin salida escrita es un defecto del método, no una protección (R7).
SALIDA = "SALIDA:"

EJECUCIONES = RAIZ / ".runtime/ejecuciones"


def recibos_ejecucion(nombre):
    """Recibos que el control plane ya escribe por cada agente delegado de una unidad.

    Llevan unidad, rol, identidad de sesión y (desde 033) modelo. Nadie los leía: la firma
    del revisor se creía a pies juntillas aunque estuviera tecleada a mano.
    """
    if not EJECUCIONES.is_dir():
        return []
    recibos = []
    for ruta in sorted(EJECUCIONES.glob(f"{nombre}-*.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue                      # un recibo ilegible no acredita nada; se ignora
        if isinstance(datos, dict) and datos.get("unidad") == nombre:
            recibos.append(datos)
    return recibos


def sesion_de(recibo):
    return str((recibo.get("lease") or {}).get("session_id") or "").strip()


def modelo_de(recibo):
    return str(recibo.get("modelo") or "").strip()


def esfuerzo_de(recibo):
    return str(recibo.get("esfuerzo") or "").strip()


def lineas_de_modelo(recibos):
    """Con qué modelo y esfuerzo se hizo cada rol de esta unidad (R2 del bug 065).

    La regla 10 se cumplía a ciegas: el recibo guardaba el modelo desde la 033, pero nadie
    lo enseñaba, así que la única forma de saber con qué se construyó era abrir el JSON. El
    cierre es el momento en que eso importa —es donde se comprueba que el revisor no repitió
    modelo—, así que se dice ahí, una línea por rol y sin inventar lo que el recibo no trae.
    """
    lineas = []
    for rol in ("constructor", "revisor"):
        propios = [r for r in recibos if str(r.get("rol") or "").strip() == rol]
        if not propios:
            continue
        vistos = []
        for recibo in propios:
            modelo = modelo_de(recibo) or "modelo sin declarar"
            detalle = modelo
            esfuerzo = esfuerzo_de(recibo)
            if esfuerzo:
                detalle += f" (esfuerzo {esfuerzo})"
            if str(recibo.get("modelo_origen") or "").strip() == "excepcion":
                motivo = str(recibo.get("motivo_modelo") or "").strip()
                detalle += f" · excepción a la tabla: {motivo or 'sin motivo declarado'}"
            if detalle not in vistos:
                vistos.append(detalle)
        lineas.append(f"{rol}: " + " / ".join(vistos))
    return lineas


# El prompt del revisor no es decorativo: `lanzar` lo exige y es lo que el agente fresco
# lee como encargo. Se ofrece ya redactado para que la salida se pueda pegar tal cual.
PROMPT_REVISION = "Revisa el diff contra el contrato y firma hallazgos.md"

def comando_revision(nombre):
    """La salida de las tres variantes del bloqueo del revisor, tal como se teclea.

    Se compone contra el `argparse` real de `ejecucion.py`: subcomando `lanzar`, la unidad
    como POSICIONAL (no existe ningún `--unidad`) y `--prompt`, que es obligatorio. La 033
    publicó aquí un comando que respondía `invalid choice` (bug 034, hallazgo A).

    Ya NO lleva `--modelo`. Hasta el bug 065 ofrecía `--modelo
    <modelo-distinto-del-constructor>`: un hueco que el lector tenía que rellenar
    adivinando, porque desde aquí no se sabe con qué construyó el otro. Ahora el modelo del
    revisor lo deriva la tabla de la regla 10 (`repo_config.plan_de_modelo`) y el comando se
    pega tal cual; ponerlo a mano exigiría además `--motivo-modelo`, así que el hueco de
    ayer sería hoy un comando que ni arranca.
    """
    return (f"python3 docs/00-metodo/scripts/ejecucion.py lanzar {nombre} "
            f"--harness claude --rol revisor --prompt \"{PROMPT_REVISION}\"")


def mensaje_sin_recibo_revisor(nombre):
    return (
        f"la firma de revisión de {nombre} no tiene recibo de ejecución: en "
        f"{rel(EJECUCIONES)} no hay ningún recibo con rol revisor para esta unidad, así que "
        f"el nombre del revisor está escrito a mano y no consta que la revisión ocurriera. "
        f"{SALIDA} lanza la revisión de verdad con "
        f"`{comando_revision(nombre)}` y vuelve a cerrar"
    )


def acredita_revision(recibo):
    """Motivo por el que este recibo NO acredita una revisión, o None si la acredita.

    `ejecucion.py` escribe el recibo ANTES de lanzar el harness y lo va completando: nace
    con `exit_code: null` y sin `resultado`, y solo al terminar guarda `resultado` (`ok`,
    `ok_sin_trabajo` o `fail`) y el código de salida. Aceptar cualquier JSON con
    `rol: revisor` habilitaba el cierre con una revisión que falló, que se quedó a medias
    o que ni siquiera arrancó — exactamente lo que la puerta existe para impedir.
    """
    identificador = str(recibo.get("id") or "sin id")
    resultado = str(recibo.get("resultado") or "").strip()
    exit_code = recibo.get("exit_code")
    if not resultado:
        return (f"el recibo {identificador} no tiene `resultado`: nació al arrancar la "
                f"ejecución y nunca se cerró, así que esa revisión no terminó")
    if resultado != "ok":
        return (f"el recibo {identificador} terminó con `resultado: {resultado}`: la "
                f"revisión no salió bien" +
                ("" if resultado != "ok_sin_trabajo" else
                 ", y un revisor que no escribe su veredicto no ha revisado"))
    if exit_code != 0:
        return (f"el recibo {identificador} declara `exit_code: {exit_code}`: el proceso "
                f"de revisión no terminó en cero")
    if not sesion_de(recibo):
        return (f"el recibo {identificador} no tiene identidad de sesión: sin ella no se "
                f"puede demostrar que el revisor no fuera el constructor")
    return None


def mensaje_recibo_no_acredita(nombre, motivos):
    return (
        f"el recibo de revisión de {nombre} no acredita que la revisión ocurriera: "
        + "; ".join(motivos)
        + f". Un recibo existe desde que la ejecución arranca; lo que prueba una revisión "
        f"es cómo TERMINÓ. {SALIDA} vuelve a lanzarla con `{comando_revision(nombre)}` y "
        f"cierra cuando su recibo salga en `resultado: ok`"
    )


def mensaje_auto_sello(nombre, sesion):
    return (
        f"el recibo de revisión de {nombre} tiene la MISMA identidad de sesión que el del "
        f"constructor ({sesion}): quien construyó se puso el sello, que es exactamente lo "
        f"que la revisión fresca existe para impedir. "
        f"{SALIDA} repite la revisión en una sesión nueva con "
        f"`{comando_revision(nombre)}`"
    )


def puerta_recibo_revisor(nombre):
    """R1/R2 — devuelve (problemas, avisos) sobre la revisión firmada de una unidad."""
    recibos = recibos_ejecucion(nombre)
    revisores = [r for r in recibos if str(r.get("rol") or "").strip() == "revisor"]
    if not revisores:
        return [mensaje_sin_recibo_revisor(nombre)], []
    motivos = [(r, acredita_revision(r)) for r in revisores]
    validos = [r for r, motivo in motivos if motivo is None]
    if not validos:
        return [mensaje_recibo_no_acredita(
            nombre, [motivo for _, motivo in motivos if motivo])], []
    constructores = [r for r in recibos if str(r.get("rol") or "").strip() == "constructor"]
    sesiones_constructor = {sesion_de(r) for r in constructores} - {""}
    limpios = [r for r in validos if sesion_de(r) not in sesiones_constructor]
    if not limpios:
        return [mensaje_auto_sello(nombre, sorted(sesiones_constructor)[0])], []
    avisos = []
    modelos_constructor = {modelo_de(r) for r in constructores} - {""}
    repetidos = sorted({modelo_de(r) for r in limpios} & modelos_constructor)
    if repetidos:
        avisos.append(
            f"revisor y constructor de {nombre} usaron el mismo modelo ({', '.join(repetidos)}): "
            f"distinta sesión, así que no es auto-sello y el cierre sigue; pero la regla 10 pide "
            f"un modelo DISTINTO porque dos instancias del mismo comparten puntos ciegos"
        )
    return [], avisos


def despacho_de(referencias, tipo_proceso, nombre):
    """(registro de despacho, aviso) — lo que el despacho dejó escrito sobre esta entrega."""
    try:
        registro = gestion_peticiones.despacho_registrado(referencias, tipo_proceso, nombre)
    except gestion_peticiones.ErrorPeticion:
        registro = None
    if registro is None:
        return None, (
            f"{nombre}: sin registro de despacho en sus peticiones, así que el carril y el "
            f"modo se leen del frontmatter, que lo escribe el mismo agente al que las puertas "
            f"vigilan. Se cierra con esa reserva escrita: inventarse el dato que decide si una "
            f"puerta aplica sería peor que no tenerla (unidad despachada antes de que el "
            f"registro existiera)"
        )
    return registro, None


def cotejar_con_el_despacho(nombre, fm, registro):
    """(carril, modo, ficheros efectivos, notas) — manda el registro, no el frontmatter (R5).

    El interruptor no puede estar junto a la cerradura: `carril: normal` sobre un trabajo
    despachado como directo apagaba la medida del carril, y `ejecucion: expres` apagaba la
    puerta del revisor entera. Los dos campos los teclea el constructor. El despacho, no.
    """
    carril_ficha = (fm.get("carril") or "normal").strip().lower()
    modo_ficha = (fm.get("ejecucion") or "").strip().lower()
    if registro is None:
        return carril_ficha, modo_ficha, ficheros_de(fm), []
    carril = (registro.get("carril") or "normal").strip().lower()
    modo = (registro.get("ejecucion") or "").strip().lower()
    ficheros = {
        posixpath.normpath(str(ruta).replace("\\", "/")).casefold()
        for ruta in registro.get("ficheros") or []
        if str(ruta).strip()
    } or ficheros_de(fm)
    notas = []
    if carril != carril_ficha:
        notas.append(
            f"la ficha declara `carril: {carril_ficha or 'vacío'}` y el registro de despacho "
            f"dice {carril}: manda el despacho, que es quien lo decidió, y las puertas se "
            f"aplican con ese carril"
        )
    if modo != modo_ficha:
        notas.append(
            f"la ficha declara `ejecucion: {modo_ficha or 'vacío'}` y el registro de despacho "
            f"dice {modo or 'sin modo especial'}: manda el despacho"
        )
    return carril, modo, ficheros, notas


# Los tres límites que definen el carril directo en `runbooks/directo.md`. Estaban escritos
# como norma y nadie los medía: se declaraban al despachar y jamás se comprobaban.
LIMITE_DIRECTO_FICHEROS = 3
LIMITE_DIRECTO_LINEAS = 250


def mensaje_directo_desbordado(nombre, ficheros, lineas, fuera, contra=""):
    razones = []
    if ficheros > LIMITE_DIRECTO_FICHEROS:
        razones.append(f"{ficheros} ficheros (el tope directo son {LIMITE_DIRECTO_FICHEROS})")
    if lineas > LIMITE_DIRECTO_LINEAS:
        razones.append(f"{lineas} líneas (el tope directo son {LIMITE_DIRECTO_LINEAS})")
    if fuera:
        razones.append("ficheros fuera de los declarados: " + ", ".join(fuera))
    return (
        f"{nombre} se despachó por el carril DIRECTO, pero su cambio mide "
        + "; ".join(razones)
        + (f" (medido desde su base de despacho hasta {contra})" if contra else "")
        + ". Eso no era un trabajo directo: un directo es un contrato de una pantalla que se "
        f"deshace revirtiendo. {SALIDA} el reencuadre de carril NO tiene comando: "
        f"`peticion.py reencuadrar-orden` hace otra cosa (que una orden adopte una revisión "
        f"material ya reevaluada) y `reabrir` solo toca peticiones ya cerradas. Es un paso "
        f"de mano, en tres tiempos: (1) no cierres {nombre} y pasa al padre esta misma "
        f"medida; (2) el padre reevalúa la petición y la vuelve a despachar por el carril "
        f"que le corresponde, que es quien escribe el registro de despacho; (3) se cierra "
        f"por el ritual de `runbooks/feature.md`. Si el cambio sí cabía en directo, la otra "
        f"salida es dejarlo dentro de los topes y volver a cerrar"
    )


def punta_a_medir(repo, rama, principal, sha_fusion=""):
    """La referencia contra la que medir el cambio de una unidad, de más a menos precisa.

    Que la rama ya no exista NO puede ser la forma de saltarse la puerta: el cierre real
    borra la rama, y borrarla a mano antes de cerrar dejaba pasar cualquier tamaño. Con la
    base de despacho registrada, la punta fusionada sirve igual de bien:

      1. la rama local, que es la que tiene el trabajo más nuevo,
      2. `origin/<rama>`, que el cierre ya no borra,
      3. el commit con el que la Puerta 5 acaba de PROBAR la fusión (el propio commit de
         la unidad, o el squash que lo metió),
      4. como último recurso, la punta de la principal — mide de más si otras unidades
         entraron por medio, y por eso va la última y el mensaje dice contra qué midió.
    """
    for referencia in (rama, f"origin/{rama}", sha_fusion, base_principal(repo, principal)):
        if referencia and git(repo, "rev-parse", "--verify", "--quiet", referencia,
                              silencioso=True)[0] == 0:
            return referencia
    return None


def medida_del_cambio(repo, base_sha, punta):
    """(ficheros tocados, líneas movidas) entre la base de despacho y la punta medible.

    Devuelve None solo cuando no hay con qué medir: sin base de despacho registrada
    (unidades legacy) medir sería inventarse el dato, y una puerta que se inventa el dato
    es peor que no tenerla.
    """
    if not base_sha or not punta:
        return None
    codigo, salida = git(repo, "diff", "--numstat", base_sha, punta, silencioso=True)
    if codigo != 0:
        return None
    tocados, lineas = [], 0
    for fila in salida.splitlines():
        piezas = fila.split("\t")
        if len(piezas) != 3:
            continue
        anadidas, borradas, ruta = piezas
        lineas += sum(int(valor) for valor in (anadidas, borradas) if valor.isdigit())
        tocados.append(ruta.replace("\\", "/"))
    return tocados, lineas


def es_ancestro(repo, posible, descendiente):
    """¿`posible` está dentro de la historia de `descendiente`? (también si son el mismo)."""
    if not posible or not descendiente:
        return False
    return git(repo, "merge-base", "--is-ancestor", posible, descendiente,
               silencioso=True)[0] == 0


def base_de_medida(repo, punta, principal, base_registrada):
    """(sha, de dónde salió) — contra qué se mide DE VERDAD el trabajo de una rama (066, R1).

    `metadata.base_sha` es el `origin/<principal>` del día del despacho, y ahí se quedaba.
    Pero con la principal por delante toda rama se rebasa para poder fusionar por ff, y
    entonces medir desde aquel SHA cuenta como propios los commits AJENOS que el rebase metió
    por debajo: el 25-08 la 055 aportaba 14 ficheros y 993 líneas a la medida de una unidad
    que había tocado dos, y el padre corrigió la base a mano ocho veces.

    La base honesta es `git merge-base(principal, rama)`: dónde se separa la rama de la
    principal HOY, se haya rebasado o no. Con una excepción, la del final del ritual: cuando
    la rama entera ya está dentro de la principal —lo normal tras el ff del paso 3— su
    merge-base ES la propia punta, y medir contra ella daría cero ficheros y cero líneas, que
    es apagar la puerta. Ahí manda la registrada, que para entonces el paso 3 ya re-anotó.

    Entre dos bases válidas gana la MÁS NUEVA (la que tiene a la otra por antecesora): las dos
    describen la misma rama, y la más nueva es la que no arrastra trabajo de nadie más.
    """
    sha_punta = sha_de(repo, punta) if punta else None
    if sha_punta is None:
        return None, "sin punta que medir"
    candidatas = []
    referencia_principal = base_principal(repo, principal)
    if referencia_principal:
        codigo, salida = git(repo, "merge-base", referencia_principal, sha_punta,
                             silencioso=True)
        merge_base = salida.strip() if codigo == 0 else ""
        if merge_base and merge_base != sha_punta:
            candidatas.append((merge_base, f"merge-base con {referencia_principal}"))
    sha_registrada = sha_de(repo, base_registrada) if base_registrada else None
    if sha_registrada and es_ancestro(repo, sha_registrada, sha_punta):
        candidatas.append((sha_registrada, "base de despacho registrada"))
    if not candidatas:
        return None, "sin base válida contra la que medir"
    elegida = candidatas[0]
    for otra in candidatas[1:]:
        if es_ancestro(repo, elegida[0], otra[0]):
            elegida = otra
    return elegida


def re_registrar_base(referencias, tipo, ref, nueva_base):
    """Re-anota `base_sha` tras un rebase y conserva la original (066, R1). Devuelve los P-ID.

    `registrar_despacho` se niega a pisar una base ya escrita, y hace bien: es el dato con el
    que el pre-push distingue una rama nacida antes de un cambio de principal. Pero un rebase
    la deja vieja de VERDAD, y conservarla intacta es conservar un dato falso. Así que no se
    pisa: la del despacho se muda a `base_sha_despacho_original` —donde nadie la borra, y solo
    la primera vez: un segundo rebase no la sustituye por la del primero— y `base_sha` pasa a
    ser la base de hoy, que es la que el cierre necesita para medir solo lo de la unidad.
    """
    tocadas = []
    for pid, revision in gestion_peticiones.parsear_referencias(referencias):
        with gestion_peticiones.lock(pid):
            try:
                datos = gestion_peticiones.cargar(pid)
            except gestion_peticiones.ErrorPeticion:
                continue
            cambiada = False
            for proceso in datos.get("procesos", []):
                if (proceso.get("tipo") != tipo or proceso.get("ref") != ref
                        or proceso.get("revision") != revision):
                    continue
                metadata = dict(proceso.get("metadata") or {})
                anterior = metadata.get("base_sha")
                if not anterior or anterior == nueva_base:
                    continue
                metadata.setdefault("base_sha_despacho_original", anterior)
                metadata["base_sha"] = nueva_base
                proceso["metadata"] = metadata
                cambiada = True
            if cambiada:
                gestion_peticiones.guardar(datos)
                tocadas.append(pid)
    return tocadas


def puerta_carril_directo(repo, nombre, carril, declarados, referencias, tipo_proceso,
                         principal, sha_fusion=""):
    """R5 — un directo que se pasó de tamaño se canta solo al cerrar.

    El carril y los ficheros llegan ya cotejados con el registro de despacho: esta puerta no
    vuelve a mirar el frontmatter, porque es justo el dato que el vigilado escribe. Y el tipo
    de proceso viene por argumento porque un BUG entrega código igual que una unidad: la 033
    lo pedía siempre como "unidad" y por eso los bugs nunca medían nada (bug 034, R4).

    La base ya no es la registrada a secas, sino la que `base_de_medida` da por buena (066).
    """
    if carril != "directo":
        return None, f"carril {carril or 'normal'}: sin límites de directo"
    try:
        base_sha = gestion_peticiones.base_despacho(referencias, tipo_proceso, nombre)
    except gestion_peticiones.ErrorPeticion:
        base_sha = None
    punta = punta_a_medir(repo, nombre, principal, sha_fusion)
    base, origen_base = base_de_medida(repo, punta, principal, base_sha)
    medida = medida_del_cambio(repo, base, punta)
    if medida is None:
        return None, (f"{nombre}: sin base de despacho registrada, el tamaño del carril "
                      f"directo no se puede medir contra nada; se cierra sin esa "
                      f"comprobación (unidad anterior a que el despacho anotara su origen)")
    tocados, lineas = medida
    fuera = sorted(
        ruta for ruta in tocados
        if posixpath.normpath(ruta).casefold() not in declarados
    )
    if (len(tocados) > LIMITE_DIRECTO_FICHEROS or lineas > LIMITE_DIRECTO_LINEAS or fuera):
        return mensaje_directo_desbordado(nombre, len(tocados), lineas, fuera, punta), None
    return None, (f"carril directo dentro de sus límites: {len(tocados)} fichero(s), "
                  f"{lineas} línea(s), todos declarados (medido desde {base[:8]}, "
                  f"{origen_base}, hasta {punta})")


COMANDO_GUARDIAN_METODO = "python3 docs/00-metodo/scripts/lint_metodo.py"


def guardian_del_metodo(raiz=None):
    """(verde, salida) — `lint_metodo.py`, que lleva dentro el trinquete de `lint_salidas`."""
    raiz = RAIZ if raiz is None else Path(raiz)
    linter = raiz / "docs/00-metodo/scripts/lint_metodo.py"
    if not linter.is_file():
        return False, f"no encuentro {rel(linter)}"
    proceso = subprocess.run(
        [sys.executable, str(linter), "--raiz", str(raiz)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    return proceso.returncode == 0, f"{proceso.stdout}{proceso.stderr}".strip()


def puerta_prefusion(repo, nombre, principal, guardian=None):
    """(problemas, notas) — R2 (066): lo que hay que cumplir ANTES del ff del paso 3.

    Dos cosas se comprobaban tarde, y las dos costaron trabajo manual el 25-08:

      1. **La rama, rebasada sobre la principal.** Con la principal por delante el ff no
         existe hasta que la rama se rebasa; y hasta que se rebasa, todo lo que se mida sobre
         ella —el tamaño del carril directo, el diff que miró el revisor— habla de otro árbol.
      2. **Los guardianes en verde SOBRE ese árbol rebasado.** La principal avanza entre el
         veredicto LIMPIO del revisor y el ff. El 25-08 avanzó dos veces y cada avance metió
         un rechazo mudo nuevo: el trinquete de `lint_salidas` los cazó al fusionar, con el
         cierre ya en marcha y el padre arreglando dentro del ritual.

    El orden importa y no es cosmético: si la rama no está rebasada se para ahí y no se gasta
    un linter entero sobre un árbol que va a cambiar. Cada problema nombra su salida.
    """
    guardian = guardian or guardian_del_metodo
    referencia_principal = base_principal(repo, principal)
    if referencia_principal is None:
        return [f"no encuentro la rama principal '{principal}' en {rel(repo)}, así que no "
                f"puedo saber si {nombre} está rebasada sobre ella. {SALIDA} comprueba "
                f"`ruta_local` y `principal` en repos.yaml y que el clon exista: "
                f"git -C {rel(repo)} branch -a"], []
    sha_rama = (sha_de(repo, f"refs/heads/{nombre}")
                or sha_de(repo, f"refs/remotes/origin/{nombre}"))
    if sha_rama is None:
        return [f"no queda rama {nombre} en {rel(repo)}: sin ella no hay ff que preparar ni "
                f"árbol rebasado que comprobar. {SALIDA} recupérala antes de fusionar: "
                f"git -C {rel(repo)} reflog"], []
    if not es_ancestro(repo, referencia_principal, sha_rama):
        return [f"{nombre} NO está rebasada sobre {referencia_principal}: el ff del paso 3 "
                f"no existe todavía, y lo que midan el cierre y el revisor habla de un árbol "
                f"que aún va a cambiar. {SALIDA} "
                f"git -C worktrees/{nombre} rebase {principal}"], []
    notas = [f"{nombre} está rebasada sobre {referencia_principal} ({sha_rama[:8]}): el ff "
             f"del paso 3 es posible"]
    verde, salida = guardian()
    if verde:
        notas.append("guardianes del método en verde sobre el árbol rebasado")
        return [], notas
    return [f"los guardianes del método NO están en verde sobre el árbol rebasado de "
            f"{nombre}; fusionar ahora mete ese rojo en {principal} y lo hereda el cierre. "
            f"{SALIDA} arregla lo que dice el linter y vuelve a pasarlo: "
            f"{COMANDO_GUARDIAN_METODO}\n{salida}"], notas


def cmd_prefusion(args):
    """Paso 3 de `runbooks/cierre.md`: lo que se comprueba justo ANTES del fast-forward."""
    nombre = args.unidad.strip("/")
    if not RE_UNIDAD.match(nombre):
        fail(f"'{nombre}' no tiene forma NNN-slug (tres dígitos, guion, slug). "
             f"{SALIDA} pásale el nombre completo: "
             f"python3 docs/00-metodo/scripts/unidad.py prefusion NNN-slug")
        return 1
    unidad = buscar_unidad(nombre)
    if unidad is None:
        fail(f"no existe la unidad {nombre} en docs/05-trabajo/ ni en docs/bugs/. "
             f"{SALIDA} mira qué hay en vuelo: "
             f"python3 docs/00-metodo/scripts/unidad.py estado")
        return 1
    repo, principal = repo_codigo()
    print(f"== Antes del ff de {nombre} ==\n")
    problemas, notas = puerta_prefusion(repo, nombre, principal)
    for nota in notas:
        ok(nota)
    if problemas:
        err(f"\n  FUSIÓN BLOQUEADA ({len(problemas)}). Arréglalo y vuelve a pasar la puerta: "
            f"python3 docs/00-metodo/scripts/unidad.py prefusion {nombre}")
        for problema in problemas:
            err(f"       · {problema}")
        return 1

    # La rama está rebasada: su merge-base con la principal es la punta de la principal, y esa
    # —no el `origin/main` del día del despacho— es la base contra la que el paso 6 tiene que
    # medir. Se re-anota AQUÍ, que es el único momento en que todavía se puede: después del ff
    # la rama entera está dentro de la principal y el merge-base ya no distingue nada.
    tipo_proceso = "bug" if unidad["clase"] == "bug" else "unidad"
    try:
        referencias = revalidar_origenes(
            unidad["fm"], proceso=(tipo_proceso, nombre), permitir_legacy=True
        )
    except gestion_peticiones.ErrorPeticion as exc:
        warn(f"no pude releer el origen de {nombre} ({exc}); la base de despacho se queda "
             f"como estaba y el cierre lo dirá")
        referencias = []
    if referencias:
        punta = sha_de(repo, f"refs/heads/{nombre}") or sha_de(repo, f"refs/remotes/origin/{nombre}")
        base_registrada = None
        try:
            base_registrada = gestion_peticiones.base_despacho(
                referencias, tipo_proceso, nombre)
        except gestion_peticiones.ErrorPeticion:
            pass
        nueva_base, origen_base = base_de_medida(repo, punta, principal, base_registrada)
        if nueva_base and base_registrada and nueva_base != base_registrada:
            try:
                tocadas = re_registrar_base(referencias, tipo_proceso, nombre, nueva_base)
            except gestion_peticiones.ErrorPeticion as exc:
                warn(f"no pude re-anotar la base de despacho de {nombre} ({exc}); el paso 6 "
                     f"medirá desde {base_registrada[:8]}, que el rebase dejó viejo")
                tocadas = []
            for pid in tocadas:
                ok(f"{pid}: base de despacho re-anotada a {nueva_base[:8]} ({origen_base}); "
                   f"la original queda en base_sha_despacho_original")
        elif nueva_base:
            ok(f"base de despacho al día: {nueva_base[:8]} ({origen_base})")

    print(f"\n  Puedes fusionar: git -C {rel(repo)} merge --ff-only {nombre}")
    return 0


# Tres entregas pueden compartir de verdad una tarde de validación. La cuarta ya no es una
# tarde: es una firma en lote (el 17-08 se firmaron 15 entregas con la misma fecha).
TOPE_OK_MISMA_FECHA = 3


def cierres_con_ok(fecha):
    """Artefactos YA cerrados cuyo OK del usuario lleva esta misma fecha."""
    marca = f"OK ({fecha})"
    encontrados = []
    candidatos = list(ARCHIVO.glob("*/hallazgos.md")) if ARCHIVO.is_dir() else []
    candidatos += sorted(BUGS.glob("*.md")) if BUGS.is_dir() else []
    for ruta in sorted(candidatos):
        try:
            texto = ruta.read_text(encoding="utf-8")
        except OSError:
            continue
        if marca in texto:
            encontrados.append(
                ruta.parent.name if ruta.name == "hallazgos.md" else ruta.stem
            )
    return sorted(set(encontrados))


def mensaje_ok_en_lote(nombre, fecha, ya_firmadas):
    return (
        f"el OK del usuario con fecha {fecha} ya firma {ya_firmadas} entrega(s) cerradas: "
        f"{nombre} sería la {ya_firmadas + 1}. Una fecha repetida en lote no acredita que "
        f"alguien probara CADA entrega en la app corriendo; acredita una firma masiva. "
        f"{SALIDA} o cierras con la fecha real en que se validó ESTA unidad "
        f"(`--ok-usuario YYYY-MM-DD`), o aportas el acta de validación con una fila por "
        f"unidad con `--validacion-lote <ruta del documento>`"
    )


# Lo que el contrato pide del acta es una FILA POR UNIDAD, no una mención: una lista de
# nombres o una frase suelta no dice qué probó el usuario en CADA entrega, que es lo único
# que distingue tres validaciones de una firma masiva.
CELDA_SIN_CONTENIDO = re.compile(r"^[\s\-—:./|\d]*$")


def fila_de_validacion(acta, unidad):
    """¿Hay en el acta una fila de tabla que sea de esta unidad Y diga cómo se validó?

    Una fila vale cuando es una fila de tabla markdown de verdad (no la separadora), una
    de sus celdas nombra a la unidad, y otra celda distinta lleva contenido: texto, no un
    hueco ni solo la fecha.
    """
    nombrada = re.compile(rf"\b{re.escape(unidad)}\b")
    for linea in acta.splitlines():
        recortada = linea.strip()
        if not (recortada.startswith("|") and recortada.endswith("|")):
            continue
        celdas = [celda.strip() for celda in recortada.strip("|").split("|")]
        if len(celdas) < 2:
            continue
        if not any(nombrada.search(celda) for celda in celdas):
            continue                      # incluye la fila separadora `|---|---|`
        if any(not nombrada.search(celda) and not CELDA_SIN_CONTENIDO.fullmatch(celda)
               for celda in celdas):
            return True
    return False


def mensaje_lote_incompleto(ruta, faltan):
    return (
        f"el documento de validación {ruta} no tiene una fila de tabla con qué se validó "
        f"cada unidad: falta(n) "
        + ", ".join(faltan)
        + f". Nombrarlas en una lista no acredita nada: hace falta una fila POR unidad, y "
        f"que la fila diga qué probó el usuario en ELLA. {SALIDA} añade esa fila por cada "
        f"unidad que comparte la fecha y vuelve a cerrar con `--validacion-lote {ruta}`"
    )


def puerta_ok_en_lote(nombre, fecha, validacion_lote):
    """R6 — la misma fecha de OK no vale para una cuarta entrega sin acta por unidad."""
    if not fecha:
        return None, None
    companeras = [otra for otra in cierres_con_ok(fecha) if otra != nombre]
    if len(companeras) < TOPE_OK_MISMA_FECHA:
        return None, None
    if not validacion_lote:
        return mensaje_ok_en_lote(nombre, fecha, len(companeras)), None
    ruta = Path(validacion_lote).expanduser()
    try:
        acta = fichero_unidad_seguro(ruta).read_text(encoding="utf-8")
    except (OSError, workspace_paths.WorkspacePathError) as exc:
        return (f"no puedo leer el documento de validación {validacion_lote}: {exc}. "
                f"{SALIDA} escribe el acta con una fila por unidad y pásala con "
                f"`--validacion-lote <ruta>`"), None
    faltan = [unidad for unidad in [*companeras, nombre]
              if not fila_de_validacion(acta, unidad)]
    if faltan:
        return mensaje_lote_incompleto(validacion_lote, faltan), None
    return None, (f"OK en lote acreditado: {validacion_lote} tiene una fila de validación "
                  f"por cada una de "
                  f"las {len(companeras) + 1} unidades que comparten el {fecha}")


def veredicto_elegido(texto):
    """El veredicto de la revisión MÁS RECIENTE, o None si sigue siendo el menú de la
    plantilla. hallazgos.md acumula una ronda de revisión debajo de otra: quedarse con
    la primera coincidencia devolvía el veredicto superado de la 1ª ronda (bug 004)."""
    elegido = None
    for m in RE_VEREDICTO.finditer(texto):
        valor = m.group(1).strip().strip("*").strip()   # `**Veredicto:** LIMPIO` → `LIMPIO`
        if "|" in valor or not valor or valor in {"—", "-"}:
            continue                                   # menú sin elegir o hueco vacío
        elegido = valor
    return elegido


def sin_cosechar(texto):
    """Viñetas con contenido y sin marca de cosecha en las dos secciones que se cosechan.

    Se mira la viñeta ENTERA —su línea y las indentadas que la continúan—, porque la
    conclusión ("→ promovido a X") cae de forma natural al final de una viñeta larga.
    """
    pendientes, en_seccion, bloque = 0, False, None

    def cerrar_bloque():
        nonlocal pendientes, bloque
        if bloque:
            entero = "\n".join(bloque)
            contenido = re.sub(r"^\s*[-*]\s+", "", entero).strip()
            if contenido not in {"—", "-", ""} and not RE_COSECHA.search(entero):
                pendientes += 1
        bloque = None

    for linea in texto.splitlines():
        if linea.startswith("#"):
            cerrar_bloque()
            titulo = linea.lstrip("#").strip()
            en_seccion = titulo.startswith(("Descubrimientos", "Trabajo descubierto"))
        elif en_seccion and re.match(r"^[-*]\s+\S", linea):
            cerrar_bloque()
            bloque = [linea]
        elif bloque is not None and re.match(r"^\s+\S", linea):
            bloque.append(linea)
        elif linea.strip():
            cerrar_bloque()
    cerrar_bloque()
    return pendientes


def sha_de(repo, referencia):
    """El SHA de una referencia (rama, remoto o SHA suelto), o None si no existe en el repo."""
    if not referencia:
        return None
    codigo, salida = git(repo, "rev-parse", "--verify", "--quiet", f"{referencia}^{{commit}}",
                         silencioso=True)
    return salida.strip() if codigo == 0 and salida.strip() else None


def base_principal(repo, principal):
    """La rama contra la que se mide la fusión: la principal local, o la del remoto."""
    if sha_de(repo, f"refs/heads/{principal}"):
        return principal
    if sha_de(repo, f"refs/remotes/origin/{principal}"):
        return f"origin/{principal}"
    return None


def rama_mergeada(repo, rama, principal, fusion_declarada=""):
    """(mergeada, motivo, prueba_fuerte, sha). Prueba de que el trabajo está en la principal.

    Antes, que la rama no existiera se tomaba como prueba de que ya se había fusionado, para
    poder reanudar un cierre a medias. Es exactamente lo contrario: la forma NORMAL de perder
    trabajo es un `git branch -D` sobre una rama sin fusionar —que es lo que el propio git
    sugiere cuando `-d` se queja— y el cierre lo archivaba como `mergeada`, con acta de que se
    entregó. Ausencia de rama no es prueba de nada.

    Se buscan pruebas de verdad, en orden de fiabilidad, y basta con que una diga que sí:

      1. la rama local,
      2. `origin/<rama>` — que ya no se borra en el cierre, justo para esto,
      3. el SHA que este mismo cierre anotó (`fusion:`) o el que declara `--fusion`,
      4. como último recurso, un commit de la principal que NOMBRE a la unidad: es la huella
         que deja un squash merge, donde el commit original no queda como ancestro de nada.
         Es prueba débil y se dice que lo es; sirve para no bloquear un flujo legítimo.

    Sin ninguna de las cuatro, FAIL: cerrar ahí es firmar una entrega que no existe.
    """
    base = base_principal(repo, principal)
    if base is None:
        return False, f"no encuentro la rama principal '{principal}' en el repo de código", \
            False, ""

    # Si la rama LOCAL existe, manda ella y nadie más: es la que tiene el trabajo más nuevo.
    # Mirar además `origin/<rama>` aquí bendeciría un cierre con la foto vieja del remoto
    # mientras quedan commits locales sin fusionar. Los otros dos rastros solo entran en juego
    # cuando la rama ya no está, que es justo el agujero que se está tapando.
    if sha_de(repo, f"refs/heads/{rama}"):
        candidatos = [(f"refs/heads/{rama}", f"la rama {rama}")]
    else:
        candidatos = [(f"refs/remotes/origin/{rama}", f"origin/{rama}")]
        if fusion_declarada:
            candidatos.append((fusion_declarada, f"el commit anotado {fusion_declarada[:8]}"))

    vivos = [(sha, etiqueta) for sha, etiqueta in
             ((sha_de(repo, ref), etiqueta) for ref, etiqueta in candidatos) if sha]
    for sha, etiqueta in vivos:
        if git(repo, "merge-base", "--is-ancestor", sha, base, silencioso=True)[0] == 0:
            return True, f"{etiqueta} está dentro de {base} ({sha[:8]})", True, sha

    # Ninguna referencia viva es ancestro de la principal. La huella FUERTE de un squash:
    # algún commit de la principal desde la base común tiene EXACTAMENTE el mismo árbol que
    # la punta de la unidad. No depende de cómo se titulara el PR — los PR de campo se
    # titulan «044: …» sin el slug entero y el grep de abajo no los ve, con el trabajo ya
    # dentro (visto en cinco unidades de un mismo proyecto, 04-08). Verificarlo a mano era `git diff <rama> <sha>`
    # vacío; esto es esa misma comprobación, commit a commit.
    for sha, etiqueta in vivos:
        codigo, arbol = git(repo, "rev-parse", f"{sha}^{{tree}}", silencioso=True)
        if codigo != 0:
            continue
        codigo, mb = git(repo, "merge-base", sha, base, silencioso=True)
        if codigo != 0:
            continue
        codigo, salida = git(repo, "log", base, f"^{mb.strip()}", "--format=%H %T",
                             silencioso=True)
        if codigo != 0:
            continue
        for linea in salida.splitlines():
            csha, _, carbol = linea.strip().partition(" ")
            if carbol.strip() == arbol.strip():
                return True, (f"{base} contiene el commit {csha[:8]} con el MISMO árbol que "
                              f"{etiqueta}: el trabajo completo está dentro (huella de squash "
                              f"merge), se titulara como se titulara el PR"), True, csha

    # Y como último recurso, la huella DÉBIL del squash: el método exige NNN-slug en el
    # título del PR, y el squash lo hereda como asunto.
    codigo, salida = git(repo, "log", base, f"--grep={rama}", "--format=%H %s", "-1",
                         silencioso=True)
    if codigo == 0 and salida.strip():
        sha, _, asunto = salida.strip().partition(" ")
        return True, (f"prueba INDIRECTA: {base} tiene «{sha[:8]} {asunto}», que nombra a "
                      f"{rama} (huella típica de un squash merge). Ninguna referencia de la "
                      f"unidad es ancestro de {base}"), False, sha

    if vivos:
        etiquetas = " ni ".join(etiqueta for _, etiqueta in vivos)
        return False, (f"{etiquetas} NO está fusionada en {base}: cerrar ahora dejaría el "
                       f"trabajo fuera de la rama principal (que es perderlo)"), False, ""
    return False, (f"no queda NI UNA prueba de que {rama} se fusionara en {base}: ni la rama "
                   f"local, ni origin/{rama}, ni un 'fusion:' anotado en la ficha, ni un "
                   f"commit de {base} que la nombre. Una rama que ya no existe NO prueba que "
                   f"se fusionara: prueba que alguien la borró. Recupérala (git reflog) o, si "
                   f"sabes con qué commit entró, cierra con --fusion <sha>"), False, ""


def anotar_fusion(ruta, sha):
    """Deja el commit que probó la fusión en el frontmatter, ANTES de borrar nada.

    Es la única forma de que un cierre reanudado —o uno en un proyecto sin remoto, donde no
    hay `origin/<rama>` que mirar— siga teniendo prueba después de que desaparezca la rama.
    """
    if not sha:
        return False
    texto = leer_fichero_unidad(ruta)
    if re.search(r"^fusion:\s*\S", texto, flags=re.M):
        return False
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        return False
    for i, linea in enumerate(lineas[1:], start=1):
        if linea.strip() == "---":
            lineas.insert(i, f"fusion: {sha}")
            escribir_fichero_unidad(ruta, "\n".join(lineas) + "\n")
            return True
    return False


def anotar_origen_legacy(ruta):
    """Deja escrito en el frontmatter que esta unidad se cerró por la vía legacy (unidad 027,
    R1): sin `peticiones:` propias, pero listada en `peticiones/LEGACY.json`. Mismo patrón que
    `anotar_fusion`: se inserta una vez, antes del `---` de cierre."""
    texto = leer_fichero_unidad(ruta)
    if re.search(r"^origen:\s*\S", texto, flags=re.M):
        return False
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        return False
    for i, linea in enumerate(lineas[1:], start=1):
        if linea.strip() == "---":
            lineas.insert(i, "origen: legacy (peticiones/LEGACY.json)")
            escribir_fichero_unidad(ruta, "\n".join(lineas) + "\n")
            return True
    return False


def escribir_ok_usuario(ruta, fecha):
    """Deja escrito el OK del usuario donde ya se lee la revisión. Sin vocabulario nuevo."""
    texto = leer_fichero_unidad(ruta)
    if LINEA_OK_USUARIO in texto:
        texto = re.sub(re.escape(LINEA_OK_USUARIO) + r".*",
                       f"{LINEA_OK_USUARIO} OK ({fecha})", texto, count=1)
    elif re.search(r"^\s*[-*]\s*\**Validaci[oó]n del usuario", texto, flags=re.M | re.I):
        texto = re.sub(r"^(\s*[-*]\s*\**Validaci[oó]n del usuario[^:\n]*:\**)\s*.*",
                       rf"\1 OK ({fecha})", texto, count=1, flags=re.M | re.I)
    else:
        texto = texto.rstrip("\n") + f"\n{LINEA_OK_USUARIO} OK ({fecha})\n"
    escribir_fichero_unidad(ruta, texto)


def procesos_dentro(destino):
    """PIDs ajenos con ficheros abiertos bajo `destino` (best-effort: lsof en POSIX).

    Sin lsof (o en Windows) devuelve [] y el borrado sigue como siempre: es un guard de
    máximo esfuerzo, no una promesa — pero cubre el caso real (macOS/Linux, una suite de
    tests corriendo en el worktree cuando alguien cierra la unidad)."""
    if not shutil.which("lsof"):
        return []
    try:
        r = subprocess.run(["lsof", "-t", "+D", str(destino)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    propios = {str(os.getpid()), str(os.getppid())}
    return sorted({pid.strip() for pid in r.stdout.split()
                   if pid.strip() and pid.strip() not in propios})


def borrar_worktree(repo, destino):
    """Quita el worktree. Se ha comprobado antes que no tiene cambios: --force solo vence a
    los ficheros IGNORADOS (node_modules, .venv, build/), que `git status` no ve y que en un
    proyecto real siempre están ahí. Sin esto el comando no valdría fuera de un repo de juguete."""
    if not destino.exists():
        return True, "ya no existía"
    # Borrar el directorio de trabajo de un proceso vivo lo mata sin aviso — así murieron
    # suites de tests de campo (07-08). Daño irreversible ⇒ gate duro con salida (ADR-026).
    vivos = procesos_dentro(destino)
    if vivos:
        return False, (f"hay procesos vivos trabajando dentro (PID {', '.join(vivos)}): "
                       f"no lo borro para no matarlos a mitad; espera a que terminen o "
                       f"ciérralos tú y repite el cierre")
    codigo, salida = git(repo, "worktree", "remove", str(destino))
    if codigo == 0:
        return True, "borrado"
    codigo, salida = git(repo, "worktree", "remove", "--force", str(destino))
    if codigo == 0:
        return True, "borrado (tenía ficheros ignorados dentro)"
    if destino.exists():
        shutil.rmtree(destino, ignore_errors=True)
        git(repo, "worktree", "prune")
    return (not destino.exists()), salida


def cmd_cerrar(args):
    nombre = args.unidad.strip("/")
    if not RE_UNIDAD.match(nombre):
        fail(f"'{nombre}' no tiene forma NNN-slug (tres dígitos, guion, slug)")
        return 1
    # ADR-023: el cierre reescribe fichas, archiva y deja el metarrepo listo para
    # commitear — toma la unidad y `git-index` para no cruzarse con Modo D ni con
    # un despacho de la misma unidad en otra sesión.
    manager = gestion_leases.LeaseManager(RAIZ)
    # El except cubre SOLO la adquisición: si el cuerpo del cierre completa y luego
    # el release tropieza (registro corrupto a media ejecución), no se puede reportar
    # "bloqueado" sobre un cierre que ya archivó y reconcilió.
    try:
        grupo = manager.acquire((f"unit:{nombre}", "git-index"))
    except gestion_leases.LeaseError as exc:
        fail(f"cierre bloqueado: otra sesión tiene la unidad o el índice ({exc})")
        return 1
    try:
        grupo.assert_owner()
        return _cerrar_bajo_lease(args, nombre, grupo)
    finally:
        try:
            grupo.release()
        except gestion_leases.LeaseError as exc:
            warn(f"el lease del cierre no se liberó limpiamente ({exc}); otra sesión lo "
                 "reclamará cuando este proceso muera")


def _cerrar_bajo_lease(args, nombre, autoridad):
    unidad = buscar_unidad(nombre)
    if unidad is None:
        fail(f"no existe la unidad {nombre} (¿ya está cerrada y archivada?)")
        return 1
    ruta, fm, clase = unidad["ruta"], unidad["fm"], unidad["clase"]
    estado = fm.get("estado")
    if estado not in {"en_revision", "en_validacion", "mergeada"}:
        fail(f"{nombre} está '{estado}': solo se cierra lo que está en_revision "
             f"(o 'en_validacion'/'mergeada', para reanudar un cierre que quedó a medias)")
        return 1
    try:
        tipo_proceso = "bug" if clase == "bug" else "unidad"
        referencias_peticion = revalidar_origenes(
            fm, proceso=(tipo_proceso, nombre), permitir_legacy=True
        )
    except gestion_peticiones.ErrorPeticion as exc:
        fail(f"{rel(ruta)}: {exc}")
        return 1
    origen_legacy = not referencias_peticion
    if origen_legacy:
        ok(f"{nombre}: sin `peticiones:` propias, pero listada en peticiones/LEGACY.json "
           "— cierre por la vía legacy")

    print(f"== Cerrando {nombre} ({fm.get('tipo')}) ==\n")
    print("Puertas (lo que NO se puede saltar):")
    problemas = []
    # R5 (034): carril, modo y ficheros se leen del registro de despacho. El frontmatter lo
    # escribe el constructor, que es a quien las puertas vigilan: mientras el dato que decide
    # SI la puerta aplica lo escriba el vigilado, endurecer la comprobación no cambia nada.
    registro_despacho, aviso_despacho = despacho_de(referencias_peticion, tipo_proceso, nombre)
    if aviso_despacho:
        warn(aviso_despacho)
    carril_real, modo_real, ficheros_reales, notas_despacho = cotejar_con_el_despacho(
        nombre, fm, registro_despacho
    )
    for nota in notas_despacho:
        warn(nota)
    ruta_cierre = modo_real or carril_real or "normal"
    if ruta_cierre == "completo":
        ruta_cierre = "normal"
    try:
        politica = control_plane.close_policy(ruta_cierre)
    except ValueError:
        # Compatibilidad con fichas antiguas que no conocían carriles: conservan las puertas
        # estrictas de normal en vez de obtener un bypass por un valor desconocido.
        politica = control_plane.close_policy("normal")
        warn(f"ruta de cierre desconocida '{ruta_cierre}': se aplican puertas de normal")
    ok(f"política de cierre {politica.name}: pruebas {politica.test_scope}")
    if politica.name == "prototipo":
        fail(
            "un prototipo descartado no es una entrega: `unidad.py cerrar` nunca lo archiva "
            "ni reconcilia. Marca cada proceso como cancelado con `peticion.py marcar-proceso` "
            "y conserva la ficha en estado descartada"
        )
        return 1

    recibo_requerido = (fm.get("control_plane") or "").strip().lower() == "requerido"
    if recibo_requerido or args.recibo_control_plane:
        if not args.recibo_control_plane:
            problemas.append("la ficha exige `--recibo-control-plane <json>`")
        else:
            try:
                ruta_recibo = Path(args.recibo_control_plane).expanduser().resolve()
                try:
                    ruta_recibo.relative_to(RAIZ.resolve())
                except ValueError as exc:
                    raise control_plane.InvalidEvidence(
                        "el recibo debe quedar dentro del workspace"
                    ) from exc
                recibo = json.loads(ruta_recibo.read_text(encoding="utf-8"))
                expected_target = (fm.get("target_fingerprint") or "").strip()
                if recibo_requerido and not expected_target:
                    raise control_plane.InvalidEvidence(
                        "la ficha requiere target_fingerprint para ligar el recibo"
                    )
                control_plane.validate_close_receipt(
                    recibo,
                    route=politica.name,
                    expected_target_fingerprint=expected_target,
                )
                ok("recibo control-plane: target, evidencia, scope y presupuesto válidos")
            except (OSError, json.JSONDecodeError, control_plane.InvalidEvidence) as exc:
                problemas.append(
                    "recibo control-plane inválido: " + control_plane.redact_secrets(exc)
                )

    # --- Puerta 0 (045): el parte de cierre cuadra con la evidencia que cita -----------------
    # Va la PRIMERA porque es la que sostiene a todas las demás: el resto de puertas leen lo
    # que el constructor escribió, y hasta hoy nadie comprobaba que eso concordara con nada.
    # Un «47/47 verdes» se creía por estar escrito. Un bug no tiene hallazgos.md aparte
    # (ADR-006): su ficha es contrato y bitácora a la vez, y la cabecera se pide donde vive.
    if clase == "unidad":
        problemas_parte = lint_cierre.validar_parte(
            nombre, ruta, ruta.parent / "hallazgos.md", RAIZ)
        for que, salida in problemas_parte:
            problemas.append(f"parte de cierre — {que}. {SALIDA} {salida}")
        if not problemas_parte:
            ok("parte de cierre: veredicto, códigos de salida, números y hashes cuadran")

    # --- Puerta 1: el usuario ha probado la app y ha dado su OK -----------------------------
    # No entra en `problemas` a propósito (ADR-010): es lo único de esta lista que no depende
    # del agente. Si TODO lo demás está en verde y solo falta esto, la unidad no se queda
    # bloqueada ocupando cupo: pasa a `en_validacion` y libera el sitio.
    ok_usuario = fecha_ok(args.ok_usuario)
    if ok_usuario:
        ok(f"OK del usuario sobre la app corriendo: {ok_usuario}")
        # R6 (033): la fecha del OK SÍ entra en `problemas`. La puerta 1 no bloquea cuando
        # el OK FALTA —eso lo decide el usuario, no el agente—, pero un OK firmado en lote
        # no es un OK que falte: es un OK que no ocurrió como dice que ocurrió.
        problema_lote, nota_lote = puerta_ok_en_lote(
            nombre, ok_usuario, getattr(args, "validacion_lote", None)
        )
        if problema_lote:
            problemas.append(problema_lote)
        elif nota_lote:
            ok(nota_lote)

    # --- Puerta 1 bis (bug 057, R3): ese OK, ¿lo dijo el usuario o lo tecleó el agente? ---
    # La fecha sola es un dato que escribe quien cierra. El recibo del visor de
    # presentaciones (051) lo sella el navegador del usuario sobre la validación guiada, y
    # es lo único que distingue "probó y dijo que sí" de "escribí la fecha de hoy".
    if politica.require_user_ok:
        problema_validacion, nota_validacion, aviso_validacion = puerta_recibo_validacion(
            nombre, ok_usuario
        )
        if problema_validacion:
            problemas.append(problema_validacion)
        elif nota_validacion:
            ok(nota_validacion)
        elif aviso_validacion:
            warn(aviso_validacion)

    # --- Puerta 2: la revisión fresca existe y dice algo -------------------------------------
    hallazgos = ruta.parent / "hallazgos.md" if clase == "unidad" else ruta
    texto_hallazgos = leer_fichero_unidad(hallazgos) if hallazgos.exists() else ""
    fm_hallazgos = frontmatter(hallazgos) or {} if clase == "unidad" else fm
    if politica.require_fresh_review and not texto_hallazgos:
        problemas.append(f"no encuentro {rel(hallazgos)}")
    elif politica.require_fresh_review:
        veredicto = veredicto_elegido(texto_hallazgos)
        if not veredicto:
            problemas.append(
                f"{rel(hallazgos)}: la revisión sigue sin veredicto (la línea conserva el menú "
                f"de la plantilla). El paso 2 del cierre es un agente FRESCO leyendo el diff "
                f"contra el contrato; sin eso no hay nada que cerrar")
        else:
            ok(f"revisión con veredicto: {veredicto[:60]}")
        # Un bug no tiene `hallazgos.md` aparte: su ficha es contrato y bitácora a la vez
        # (ADR-006), y su veredicto vive en la sección 6. La FIRMA de cabecera solo se le
        # pide a las unidades; el RECIBO, en cambio, se le pide igual (R4).
        firma_en_pie = True
        if clase == "unidad":
            revisor = (fm_hallazgos.get("revisor") or "").strip()
            revisado = fecha_ok(fm_hallazgos.get("revisado"))
            if revisor.lower() in {"", "no"} or not revisado:
                firma_en_pie = False
                problemas.append(
                    f"{rel(hallazgos)}: falta 'revisor:' y/o 'revisado: YYYY-MM-DD' en su "
                    f"cabecera — es lo que distingue una revisión de verdad de un constructor "
                    f"que se puso un sello a sí mismo. Si la revisión ocurrió pero nadie firmó, "
                    f"NO rellenes la cabecera de memoria: eso es inventarse la firma. "
                    f"{SALIDA} " + (
                        "esta unidad no tiene worktree (ejecución documental), así que su "
                        "revisión no se lanza por el control plane: la revisa un agente "
                        "FRESCO sobre la carpeta de la unidad y firma él mismo la cabecera "
                        "de hallazgos.md, con su nombre y la fecha del día"
                        if modo_real == "documental"
                        else f"vuelve a revisar con un agente fresco: "
                             f"`{comando_revision(nombre)}`"
                    ))
            else:
                ok(f"revisado por {revisor} el {revisado}")
        if firma_en_pie:
            # R1/R2 (033): la firma dice quién revisó; el recibo del control plane dice si esa
            # revisión ocurrió de verdad y si fue OTRO agente. Sin esto, la puerta más citada
            # del método se salta tecleando un nombre.
            #
            # R3 (034): salvo cuando la unidad no puede producir ese recibo. Una ejecución
            # documental no crea rama ni worktree por diseño (regla 2) y `ejecucion.py` exige
            # worktree para lanzar nada: pedirle el recibo era pedirle una evidencia que su
            # propio carril le prohíbe generar, y dejaba encerradas dos unidades reales. La
            # excepción no se calla: se dice aquí, con su motivo.
            if modo_real == "documental":
                ok("ejecución documental: sin rama ni worktree por diseño (regla 2), así que "
                   "no hay recibo de control plane que exigir — la revisión la acredita la "
                   "firma de hallazgos.md, que es toda la evidencia que este carril puede dar")
            else:
                fallos_recibo, avisos_recibo = puerta_recibo_revisor(nombre)
                problemas.extend(fallos_recibo)
                for aviso in avisos_recibo:
                    warn(aviso)
                if not fallos_recibo and not avisos_recibo:
                    ok("recibo de revisión: agente distinto del constructor")
                if not fallos_recibo:
                    for linea in lineas_de_modelo(recibos_ejecucion(nombre)):
                        ok(f"regla 10 · {linea}")
    else:
        ok(f"ruta {politica.name}: no exige revisión fresca")

    if politica.require_discard:
        descarte = (fm.get("descarte") or "").strip().lower()
        if descarte not in {"confirmado", "si", "sí", "true"}:
            problemas.append(
                "prototipo sin `descarte: confirmado`: el cierre debe declarar que sus "
                "recursos y resultados no pasan a producción"
            )
        else:
            ok("descarte del prototipo confirmado")

    # --- Puerta 3: un hotfix no se cierra con el contrato a deber ----------------------------
    # `despachar --force` deja la marca de deuda y hotfix.md da 24 h para pagarla. Si se cierra
    # sin pagarla nadie vuelve a mirarla: el FAIL del linter se quedaría para siempre sobre una
    # unidad ya archivada. La puerta va ANTES del cierre, que es cuando aún se puede pagar.
    if MARCA_DEUDA.split(":")[0] in leer_fichero_unidad(ruta):
        problemas.append(
            "esta unidad conserva la DEUDA DE SPEC del hotfix: se despachó sin contrato "
            "completo y hotfix.md da 24 h para escribirlo. Complétalo y borra la marca antes "
            "de cerrar — después de cerrar, nadie vuelve a pagarla")

    # --- Puerta 4: no queda trabajo sin guardar en el worktree -------------------------------
    repo, principal = repo_codigo()
    destino = WORKTREES / nombre
    sin_fusion = not politica.require_merge
    if destino.exists():
        codigo, salida = git(destino, "status", "--porcelain")
        if codigo == 0 and salida:
            problemas.append(
                f"worktrees/{nombre} tiene {len(salida.splitlines())} fichero(s) sin commitear: "
                f"cerrar ahora los borra y no hay copia en ningún sitio")
        elif codigo == 0:
            ok(f"worktrees/{nombre} sin cambios pendientes")

    # --- Puerta 5: la rama está fusionada en la principal ------------------------------------
    hay_repo = git(repo, "rev-parse", "--is-inside-work-tree", silencioso=True)[0] == 0
    sha_fusion = ""
    if sin_fusion:
        ok(f"ruta {politica.name}: sin rama fusionada que comprobar")
    elif not hay_repo:
        problemas.append(f"no encuentro el repo de código en {rel(repo)} (repos.yaml)")
    else:
        fusionada, motivo, fuerte, sha_fusion = rama_mergeada(
            repo, nombre, principal, args.fusion or fm.get("fusion", ""))
        if not fusionada:
            problemas.append(motivo)
        else:
            (ok if fuerte else warn)(motivo)

    # --- Antes de medir: la base de despacho, al día (066/R1) --------------------------------
    # El paso 3 del ritual re-anota la base al rebasar, que es cuando mejor se ve. Pero un
    # cierre puede llegar aquí sin haber pasado por él (unidad despachada antes de que el paso
    # existiera, cierre reanudado a medias), y entonces `base_sha` sigue siendo el
    # `origin/<principal>` del despacho con commits ajenos por debajo. Si todavía se puede
    # saber cuál es la base de verdad, se re-anota aquí y la original se conserva; si no, la
    # medida de la Puerta 6 lo dice contra qué midió y el cierre no se inventa nada.
    if hay_repo and referencias_peticion and not sin_fusion:
        punta_para_base = punta_a_medir(repo, nombre, principal, sha_fusion)
        try:
            base_registrada = gestion_peticiones.base_despacho(
                referencias_peticion, tipo_proceso, nombre)
        except gestion_peticiones.ErrorPeticion:
            base_registrada = None
        base_al_dia, origen_base = base_de_medida(
            repo, punta_para_base, principal, base_registrada)
        if base_al_dia and base_registrada and base_al_dia != base_registrada:
            try:
                for pid in re_registrar_base(
                        referencias_peticion, tipo_proceso, nombre, base_al_dia):
                    ok(f"{pid}: base de despacho re-anotada a {base_al_dia[:8]} "
                       f"({origen_base}) — la del despacho queda en "
                       f"base_sha_despacho_original")
            except gestion_peticiones.ErrorPeticion as exc:
                warn(f"no pude re-anotar la base de despacho de {nombre} ({exc}); la medida "
                     f"de abajo dice contra qué midió")

    # --- Puerta 6 (033/R5): un directo que se pasó de tamaño no era un directo -------------
    # R4 (034): la puerta ya no vive dentro de `if clase == "unidad"`. Un bug entrega código
    # por una rama exactamente igual que una unidad, y era la vía por la que cerraba sin
    # recibo y sin medida — la más usada del método.
    problema_directo, nota_directo = puerta_carril_directo(
        repo, nombre, carril_real, ficheros_reales, referencias_peticion, tipo_proceso,
        principal, sha_fusion
    )
    if problema_directo:
        problemas.append(problema_directo)
    elif nota_directo:
        ok(nota_directo)

    if problemas:
        err(f"\n  CIERRE BLOQUEADO ({len(problemas)}):")
        for p in problemas:
            err(f"       · {p}")
        err("\n  El cierre es indivisible: se arregla lo de arriba y se vuelve a ejecutar.")
        return 1

    # La prueba de la fusión se escribe ANTES de tocar nada, y vale para los dos caminos: si
    # este cierre se queda en `en_validacion` y días después alguien borra la rama, la ficha
    # sigue sabiendo con qué commit entró el trabajo.
    if sha_fusion and anotar_fusion(ruta, sha_fusion):
        ok(f"prueba de fusión anotada en {rel(ruta)} (fusion: {sha_fusion[:8]})")

    # --- Cierre parcial: todo hecho salvo lo que solo puede hacer el usuario ------------------
    if politica.require_user_ok and not ok_usuario:
        if estado != "en_validacion":
            texto = leer_fichero_unidad(ruta)
            texto = re.sub(r"^estado:\s*\S+", "estado: en_validacion", texto, count=1, flags=re.M)
            texto = re.sub(r"^actualizado:\s*\S+", f"actualizado: {HOY}", texto, count=1,
                           flags=re.M)
            escribir_fichero_unidad(ruta, texto)
            ok(f"{rel(ruta)}: estado → en_validacion")
        else:
            ok(f"{nombre} ya estaba en_validacion: sigue esperando al usuario")
        print(f"\n  CIERRE A MEDIAS, Y ES LO CORRECTO. Todo lo que depende de un agente está\n"
              f"  hecho y comprobado; falta lo único que no puede hacer: que el usuario pruebe\n"
              f"  la aplicación CORRIENDO y diga que sí.\n\n"
              f"  · La unidad DEJA de contar para el tope de trabajo en vuelo: puedes despachar\n"
              f"    otra sin tocar el tope ni inventarte un ADR.\n"
              f"  · No está cerrada: no se archiva, no se borra el worktree ni la rama, y el\n"
              f"    linter la enseñará en cada arranque hasta que se termine.\n"
              f"  · Para pedírselo, la web se abre sola (bug 057):\n"
              f"        {comando_validar(nombre)}\n"
              f"  · Cuando el usuario dé el OK ahí, con la fecha del día en que lo dio:\n"
              f"        python3 {rel(__file__)} cerrar {nombre} --ok-usuario {HOY}")
        return 0

    # --- Aviso (no bloquea): la cosecha de hallazgos ------------------------------------------
    pendientes = sin_cosechar(texto_hallazgos)
    if pendientes:
        warn(f"{pendientes} hallazgo(s) sin cosechar en {rel(hallazgos)}: marca cada viñeta "
             f"con '→ promovido a <destino>' o '→ descartado (motivo)' (formato en la propia "
             f"plantilla). No bloqueo el cierre, pero eso es conocimiento que se pierde")

    # --- Mecánica (lo que el padre tecleaba a mano, en orden) ---------------------------------
    print("\nMecánica:")
    evidencia_peticion = (
        f"unidad {nombre} verificada; OK usuario {ok_usuario or 'no-aplica'}; "
        f"fusión {sha_fusion or 'no-aplica'}; política {politica.name}"
    )
    originales_cierre = {
        fichero: fichero_unidad_seguro(fichero).read_bytes()
        for fichero in {ruta, hallazgos}
        if fichero.exists()
    }
    ruta_original, hallazgos_original = ruta, hallazgos
    final = ARCHIVO / nombre if clase == "unidad" else None
    if final is not None and final.exists():
        fail(f"{rel(final)} ya existe: no puedo cerrar sin pisar historia")
        return 1

    if ok_usuario:
        escribir_ok_usuario(hallazgos, ok_usuario)
        ok(f"OK del usuario escrito en {rel(hallazgos)}")
    else:
        ok(f"ruta {politica.name}: OK de usuario no aplica")

    # ADR-023: revalidar la autoridad JUSTO antes de la primera escritura irreversible.
    # Todo lo anterior fue lectura y verificación; de aquí en adelante se muta el
    # metarrepo (estado, archivado, worktree). Un fencing perdido en la ventana entre
    # el assert inicial y aquí (el linter tarda) bloquea esta escritura, no la consuma.
    try:
        autoridad.assert_owner()
    except gestion_leases.LeaseError as exc:
        fail(f"cierre abortado antes de tocar nada: se perdió la autoridad del lease ({exc})")
        return 1

    texto = leer_fichero_unidad(ruta)
    texto = re.sub(r"^estado:\s*\S+", "estado: mergeada", texto, count=1, flags=re.M)
    texto = re.sub(r"^actualizado:\s*\S+", f"actualizado: {HOY}", texto, count=1, flags=re.M)
    escribir_fichero_unidad(ruta, texto)
    ok(f"{rel(ruta)}: estado → mergeada")
    if origen_legacy and anotar_origen_legacy(ruta):
        ok(f"{rel(ruta)}: origen legacy anotado (peticiones/LEGACY.json)")

    # Para una unidad normal, `mergeada` solo es válida dentro de archivo/. Se mueve antes
    # del lint y se revierte junto con los ficheros si aparece cualquier incoherencia.
    if clase == "unidad":
        ARCHIVO.mkdir(parents=True, exist_ok=True)
        shutil.move(str(ruta.parent), str(final))
        ruta = final / "especificacion.md"
        hallazgos = final / "hallazgos.md"
        ok(f"unidad archivada provisionalmente en {rel(final)}")

    # El linter corre antes de cerrar la petición. Si falla, se restaura el contrato y el
    # veredicto exactos: nunca queda una petición entregada sobre una unidad a medio cerrar.
    linter = RAIZ / "docs/00-metodo/scripts/lint_metodo.py"
    if linter.exists():
        print()
        sys.stdout.flush()
        codigo_lint = subprocess.run([sys.executable, str(linter)]).returncode
        if codigo_lint:
            if clase == "unidad" and final.exists():
                shutil.move(str(final), str(ruta_original.parent))
            for fichero, contenido in originales_cierre.items():
                gestion_peticiones.escribir_bytes_atomico(fichero, contenido)
            fail("el linter bloqueó el cierre; contrato y revisión restaurados")
            return codigo_lint

    if politica.require_merge and hay_repo:
        borrado, detalle = borrar_worktree(repo, destino)
        (ok if borrado else warn)(f"worktree worktrees/{nombre}: {detalle}")
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{nombre}",
               silencioso=True)[0] == 0:
            codigo, salida = git(repo, "branch", "-d", nombre)
            (ok if codigo == 0 else warn)(
                f"rama local {nombre}: {'borrada' if codigo == 0 else salida}")
        # La rama REMOTA no se borra, a propósito. Es la única copia del trabajo que no vive
        # en este disco, y borrarla convierte cualquier accidente local en pérdida definitiva.
        # Cuesta nada dejarla y es la prueba que mira `rama_mergeada` cuando la local ya no
        # está. Si el repositorio tiene "delete branch on merge" activado en su servidor, esto
        # no lo impide: eso se decide allí, no aquí.
        if git(repo, "rev-parse", "--verify", "--quiet",
               f"refs/remotes/origin/{nombre}", silencioso=True)[0] == 0:
            ok(f"rama remota origin/{nombre}: se conserva (respaldo del trabajo entregado)")

    if hay_repo:
        avisar_principal_sin_empujar(repo, principal)

    if clase == "bug":
        # ADR-006: la ficha del bug NO se archiva; docs/bugs/ es el historial.
        ok(f"{rel(ruta)} se queda en docs/bugs/ (los bugs no se archivan, ADR-006)")
    else:
        ok(f"unidad archivada en {rel(final)}")

    # Esta es la última mutación semántica: el proceso canónico ya está terminal y, si algo
    # falla aquí, la petición queda abierta y el comando `peticion.py reconciliar` permite
    # reanudar sin fingir que la entrega terminó antes de tiempo.
    if referencias_peticion:
        try:
            gestion_peticiones.reconciliar_ids(
                referencias_peticion, tipo_proceso, nombre, evidencia_peticion
            )
        except gestion_peticiones.ErrorPeticion as exc:
            fail(f"la unidad quedó terminal, pero falta reconciliar su petición: {exc}")
            return 1
        ok("peticiones de origen reconciliadas con el cierre")
    else:
        ok("origen legacy: sin petición que reconciliar (peticiones/LEGACY.json)")

    print("\nLo que queda es tuyo, porque es criterio y no mecánica:")
    print("    · aplicar los Deltas al mapa (docs/02-flujos/) y pasar el flujo a 'entregada'")
    print("    · promover los hallazgos a conocimiento/, decisiones/ o al ROADMAP")
    print("    · actualizar ESTADO.md" + (" e INDICE.md de bugs" if clase == "bug" else ""))

    return 0


# --------------------------------------------------------------------------- subcomando: estado

def cmd_estado(args):
    unidades = censo()
    print("== Estado del trabajo ==\n")

    print("Unidades (docs/05-trabajo/):")
    filas = [(n, u) for n, u in sorted(unidades.items()) if u["clase"] == "unidad"]
    if not filas:
        print("  (ninguna)")
    for n, u in filas:
        fm = u["fm"]
        print(f"  {n:28} {fm.get('tipo', '?'):14} {fm.get('carril', '?'):9} "
              f"{fm.get('estado', 'SIN FRONTMATTER')}")

    print("\nBugs (docs/bugs/):")
    bugs = [(n, u) for n, u in sorted(unidades.items()) if u["clase"] == "bug"]
    abiertos = [(n, u) for n, u in bugs if u["fm"].get("estado") not in {"mergeada", "descartada"}]
    if not bugs:
        print("  (ninguno)")
    for n, u in bugs:
        estado = u["fm"].get("estado", "SIN FRONTMATTER")
        print(f"  {n:28} {estado}{'  ← abierto' if (n, u) in abiertos else ''}")

    print("\nWorktrees (worktrees/):")
    wt = sorted(p.name for p in WORKTREES.iterdir() if p.is_dir()) if WORKTREES.is_dir() else []
    if not wt:
        print("  (ninguno)")
    for w in wt:
        print(f"  {w}")

    print("\nCoherencia:")
    activas = sorted(n for n, u in unidades.items() if u["fm"].get("estado") in EN_VUELO)
    if not activas:
        ok("nada en vuelo (regla 5: 1 por defecto)")
    elif len(activas) == 1:
        ok(f"1 unidad en vuelo: {activas[0]}")
    else:
        warn(f"{len(activas)} unidades en vuelo: {', '.join(activas)} "
             f"(default 1; en paralelo jamás comparten ficheros)")
    esperando = sorted(n for n, u in unidades.items()
                       if u["fm"].get("estado") == "en_validacion")
    if esperando:
        warn(f"{len(esperando)} unidad(es) esperando a que el usuario pruebe la app: "
             f"{', '.join(esperando)} — no cuentan para el tope, pero tampoco están cerradas")
    # Mismo criterio que lint_metodo.py sección 5 (bug 003): una unidad archivada con
    # worktree aún en disco no es un huérfano ciego — es un resto que puede necesitar
    # borrado manual si `borrar_worktree` falló, así que avisa en vez de fallar en
    # silencio o de callarse del todo.
    archivadas = {p.name for p in ARCHIVO.iterdir() if p.is_dir()} if ARCHIVO.is_dir() else set()
    huerfanos_reales = set(wt) - set(unidades) - archivadas
    huerfanos_archivados = (set(wt) - set(unidades)) & archivadas
    for huerfano in sorted(huerfanos_reales):
        fail(f"worktree sin unidad: worktrees/{huerfano} (¿cierre a medias?)")
    for huerfano in sorted(huerfanos_archivados):
        warn(f"worktrees/{huerfano}: su unidad ya está archivada pero el worktree sigue "
             f"en disco — bórralo a mano si el cierre no pudo hacerlo")
    requieren_wt = [
        n for n in activas
        if unidades[n]["fm"].get("ejecucion") != "documental"
    ]
    for sin_wt in [n for n in requieren_wt if n not in wt]:
        warn(f"unidad {sin_wt} en obra SIN worktree (¿despachada de verdad?)")
    if wt and not huerfanos_reales and not huerfanos_archivados and all(n in wt for n in requieren_wt):
        ok("worktrees y unidades casan")

    # R4 del bug 054: sin este aviso, "planificada" se queda esperando a que alguien
    # se acuerde de enseñar el contrato — el visor existe, pero nadie lo manda abrir.
    pendientes = sorted(
        n for n, u in unidades.items()
        if u["fm"].get("estado") == "planificada" and aprobacion(u["fm"]) is None
    )
    if pendientes:
        warn(f"{len(pendientes)} contrato(s) sin aprobar: {', '.join(pendientes)} — "
             f"levanta el visor y pide el OK: {COMANDO_VISOR_CONTRATOS}")
        # R2 del bug 057: y se levanta aquí mismo, que para eso lo sabemos.
        imprimir_lineas(abrir_visor_de_contratos(
            pendientes, getattr(args, "sin_navegador", False)))

    nnn, _ = siguiente_nnn()
    print(f"\nSiguiente NNN libre: {nnn}")
    print(f"Repo de código: {rel(repo_codigo()[0])}")
    return 0


# --------------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(
        prog="unidad.py",
        description="Despacho de unidades del método: numeración, creación desde plantilla y "
                    "creación de rama/worktree con precondiciones que bloquean.")
    sub = ap.add_subparsers(
        dest="comando",
        metavar="{nnn,nueva,despachar,validar,prefusion,cerrar,estado}")

    p_nnn = sub.add_parser("nnn", help="imprime el siguiente NNN libre")
    p_nnn.add_argument("--detalle", action="store_true",
                       help="además, lista qué número ocupa cada fuente")
    p_nnn.set_defaults(func=cmd_nnn)

    p_nueva = sub.add_parser("nueva", help="crea la unidad desde su plantilla (NO crea worktree)")
    p_nueva.add_argument("tipo", help=" | ".join(TIPOS))
    p_nueva.add_argument("slug", help="slug en minúsculas: ^[a-z0-9][a-z0-9-]*$")
    p_nueva.add_argument("--completo", action="store_true",
                         help="carril COMPLETO (regla 9): transversal, arriesgado o territorio "
                              "desconocido — crea también investigacion.md, que se rellena antes "
                              "de la especificación")
    p_nueva.add_argument("--directo", action="store_true",
                         help="carril DIRECTO (runbooks/directo.md): cambia comportamiento pero "
                              "encaja en una actividad que ya existe, no mueve el mapa, 1-3 "
                              "ficheros sin hotspots y se deshace revirtiendo. Contrato de una "
                              "pantalla; construye el padre y revisa un agente fresco "
                              "(ADR-017); el resto del ritual, idéntico")
    p_nueva.add_argument(
        "--desde",
        action="append",
        default=[],
        metavar="P-ID",
        help="petición evaluada que origina la unidad; repetible",
    )
    p_nueva.add_argument("--sin-navegador", action="store_true",
                         help="no levantes el visor de contratos ni abras el navegador: "
                              "solo imprime el comando (bug 057, R2)")
    p_nueva.set_defaults(func=cmd_nueva)

    p_desp = sub.add_parser("despachar",
                            help="crea rama y worktree de una unidad ya especificada y aprobada")
    p_desp.add_argument("unidad", help="nombre completo NNN-slug")
    p_desp.add_argument("--paralelo", action="store_true",
                        help="permite despachar con otras unidades en vuelo — solo si NO "
                             "comparten ningún fichero")
    p_desp.add_argument(
        "--documental",
        action="store_true",
        help="despacha sin rama ni worktree; solo auditoria/investigacion/documentacion "
             "que leen main/ y escriben únicamente en su carpeta de unidad",
    )
    p_desp.add_argument("--force", action="store_true",
                        help="válvula de PRODUCCIÓN CAÍDA: salta la aprobación y la puerta de "
                             "la spec, y anota la deuda en la ficha. SOLO para unidades tipo "
                             "bug con severidad P0 declarada, y exige --motivo")
    p_desp.add_argument("--motivo", default="",
                        help="emergencia declarada por el usuario, en una frase; obligatorio "
                             'con --force (p. ej. --motivo "produccion caida: 500 en el login")')
    p_desp.set_defaults(func=cmd_despachar)

    p_cer = sub.add_parser("cerrar",
                           help="cierra una unidad revisada y ya fusionada: puertas + los "
                                "pasos mecánicos del ritual")
    p_cer.add_argument("unidad", help="nombre completo NNN-slug")
    p_cer.add_argument("--ok-usuario", default="", metavar="YYYY-MM-DD",
                       help="fecha en que el usuario probó la app corriendo y dio su OK. La "
                            "pone el usuario, igual que 'aprobado:' al despachar. Sin ella, si "
                            "todo lo demás está en verde, la unidad pasa a 'en_validacion': "
                            "deja de contar para el tope pero NO queda cerrada")
    p_cer.add_argument("--fusion", default="", metavar="SHA",
                       help="commit con el que el trabajo entró en la rama principal. Solo "
                            "hace falta si no queda rastro de la rama (ni local, ni remota, "
                            "ni anotada). No es un pase: el SHA tiene que existir y estar "
                            "dentro de la principal, o el cierre sigue bloqueado")
    p_cer.add_argument(
        "--recibo-control-plane",
        default="",
        metavar="JSON",
        help="recibo opt-in con target, legacy→new→mutant, scope y presupuesto",
    )
    p_cer.add_argument(
        "--validacion-lote",
        default="",
        metavar="RUTA",
        help="acta de validación con UNA FILA POR UNIDAD, cuando varias entregas comparten "
             "de verdad la misma fecha de OK del usuario. Es la única vía de salida de la "
             "puerta que impide firmar entregas en lote con una sola fecha",
    )
    p_cer.set_defaults(func=cmd_cerrar)

    p_val = sub.add_parser(
        "validar",
        help="paso 5 de runbooks/cierre.md: genera la validación guiada de la unidad desde "
             "su ficha, levanta el visor de presentaciones y la abre en el navegador. Pedir "
             "un OK es esto, no acordarse de enseñar una web")
    p_val.add_argument("unidad", help="nombre completo NNN-slug")
    p_val.add_argument("--sin-navegador", action="store_true",
                       help="genera el manifiesto y para ahí: ni levanta el visor ni abre "
                            "nada. Imprime el comando exacto para abrirlo tú")
    p_val.add_argument("--puerto", type=int,
                       help="puerto local del visor de presentaciones; por defecto uno "
                            "derivado de la carpeta de datos, estable entre llamadas")
    p_val.set_defaults(func=cmd_validar)

    p_pre = sub.add_parser(
        "prefusion",
        help="paso 3 de runbooks/cierre.md: comprueba ANTES del ff que la rama está rebasada "
             "sobre la principal y que los guardianes están verdes sobre ese árbol; de paso "
             "re-anota la base de despacho que el rebase dejó vieja")
    p_pre.add_argument("unidad", help="nombre completo NNN-slug")
    p_pre.set_defaults(func=cmd_prefusion)

    p_est = sub.add_parser("estado", help="resumen: unidades, bugs, worktrees y su coherencia")
    p_est.add_argument("--sin-navegador", action="store_true",
                       help="no levantes el visor de contratos ni abras el navegador: "
                            "solo imprime el comando (bug 057, R2)")
    p_est.set_defaults(func=cmd_estado)

    args = ap.parse_args()
    if not args.comando:
        ap.print_help()
        return 1
    try:
        return args.func(args)
    except (repo_config.RepoConfigError, workspace_paths.WorkspacePathError,
            ErrorFichaBloqueada) as exc:
        fail(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
