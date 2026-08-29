#!/usr/bin/env python3
"""Las fuentes del tablero de control, leídas y nada más (unidad 058).

Funciones PURAS de lectura: cada una abre los ficheros que el método ya escribe
y devuelve un `dict` serializable. Aquí no se recalcula nada con scripts
externos, no se inventa un dato que no esté en disco y no se escribe jamás.

Cada sección viaja con su propio `estado` — `ok`, `ausente` o `no_comprobable` —
y con la hora en que se leyó. Es la regla G-2302 del plano
(`presentar-y-observar-proceso`): un dato que no se pudo leer nunca se presenta
como un cero ni como un verde.

Fuentes (investigación P1 de la unidad):

    docs/05-trabajo/<NNN-slug>/especificacion.md   unidades vivas
    docs/bugs/<NNN-slug>.md                        bugs (historial completo)
    docs/05-trabajo/archivo/<NNN-slug>/            entregas cerradas
    docs/05-trabajo/peticiones/<P-ID>/peticion.json
    .runtime/ejecuciones/*.json                    recibos `ejecucion/v1`
    .runtime/leases/active/*.json                  cerrojos con PID
    docs/00-metodo/VERSION vs la versión declarada por el workspace
    docs/00-metodo/scripts/canario.py --json
    git -C main log / rev-list
"""

import json
import os
import posixpath
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Estados de una FUENTE (no de una unidad).
OK = "ok"
AUSENTE = "ausente"
NO_COMPROBABLE = "no_comprobable"

# Mismos conjuntos que `unidad.py`: si el despacho los usa para decidir, el
# tablero no puede usar otros o contaría una película distinta de la real.
EN_VUELO = {"en_obra", "en_revision"}
POR_HACER = {"planificada", "en_obra", "en_revision", "bloqueada"}
CERRADAS = {"mergeada"}

FASES = {
    "planificada": "planificada",
    "en_obra": "en obra",
    "en_revision": "en revisión",
    "en_validacion": "en validación",
    "bloqueada": "bloqueada",
    "mergeada": "entregada",
}

ROLES = ("constructor", "revisor", "padre")

NOMBRE_UNIDAD = re.compile(r"^\d{3}-[a-z0-9][a-z0-9-]*$")
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAREA = re.compile(r"^\s*-\s*\[([ xX])\]")
# Misma familia que `visor_presentaciones/manifestar.SENSIBLE`: lo que no puede
# salir por la web local (R8 del contrato, G-2303 del plano).
CORREO = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
OCULTO = "[correo oculto]"

PUERTO_CONTRATOS = 8766
SERVICIOS = (
    ("visor_contratos", "visor de contratos"),
    ("visor_presentaciones", "visor de presentaciones"),
    ("visor_tablero", "tablero de control"),
    ("visor", "visor de flujos"),
)
PUERTOS_VIGILADOS = (8765, 8766, 8767, 9043)

# --- taller (unidad 121) ---------------------------------------------------
# La web única (081) ya no vive en un puerto fijo: el suyo sale de la huella del
# workspace. Lo que SÍ es fijo es el rastro que deja al levantarse
# (`.runtime/web-<puerto>.log`), y de ahí se saca «desde cuándo».
RECIBOS_SERVIDOR = (
    ("web-", "la web del método"),
    ("visor-contratos-", "visor de contratos"),
    ("tablero-", "tablero de control"),
    ("visor-", "visor de flujos"),
)
# `_arbol_de` reconoce un servidor por la carpeta de su `servir.py`. Para el
# taller se añade la cáscara de la web única, que en SERVICIOS no hacía falta.
SERVICIOS_TALLER = SERVICIOS + (("web", "la web del método"),)
# Ni el nombre de la persona ni su árbol de carpetas salen de aquí (R8 de la 058):
# de una ruta absoluta sólo viaja el último tramo.
GITHUB = re.compile(
    r"^(?:git@github\.com:|ssh://git@github\.com/|git://github\.com/"
    r"|https?://(?:[^@/]+@)?github\.com/)(?P<ruta>[^\s]+?)(?:\.git)?/?$"
)
SEGUNDOS_COMANDO_EXTERNO = 2.0     # R6: nada de la tarjeta bloquea la página

VIGILADAS = (
    ("docs", "05-trabajo"),
    ("docs", "bugs"),
    (".runtime", "ejecuciones"),
    (".runtime", "leases", "active"),
)


# --------------------------------------------------------------------------- utilidades

def _ahora():
    return datetime.now(timezone.utc)


def _leido():
    return _ahora().isoformat(timespec="seconds")


def _sin_pii(texto):
    """Ningún correo viaja al navegador, venga de donde venga (R8)."""
    return CORREO.sub(OCULTO, texto or "")


def _dias_desde(fecha):
    """Días enteros desde una fecha `YYYY-MM-DD` o un ISO completo; None si no hay."""
    if not fecha:
        return None
    try:
        limpia = str(fecha).strip()
        if FECHA.match(limpia):
            momento = datetime.fromisoformat(limpia).replace(tzinfo=timezone.utc)
        else:
            momento = datetime.fromisoformat(limpia.replace("Z", "+00:00"))
            if momento.tzinfo is None:
                momento = momento.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0, (_ahora() - momento).days)


def _hoy_local():
    return datetime.now().date()


def _git(cwd, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


# --------------------------------------------------------------------------- frontmatter

def frontmatter(texto):
    """El frontmatter de una ficha, con listas en línea Y multilínea.

    Mismo criterio que `unidad.py frontmatter` a propósito: si el despacho lee
    `ficheros:` de esa manera, el tablero tiene que leerlo igual o diría que dos
    unidades no chocan cuando el despacho las bloquea (o al revés).
    """
    lineas = texto.splitlines()
    if not lineas or lineas[0].strip() != "---":
        return {}
    datos = {}
    clave_abierta, items = None, []

    def cerrar():
        if clave_abierta and items:
            datos[clave_abierta] = ", ".join(items)
        return None, []

    for linea in lineas[1:]:
        if linea.strip() == "---":
            clave_abierta, items = cerrar()
            return datos
        casa = re.match(r"^(\w+):\s*(.*)$", linea)
        if casa:
            clave_abierta, items = cerrar()
            valor = casa.group(2).split("#")[0].strip().strip("'\"")
            datos[casa.group(1)] = valor
            if not valor:
                clave_abierta = casa.group(1)
            continue
        item = re.match(r"^\s+-\s*(.+)$", linea)
        if item and clave_abierta:
            items.append(item.group(1).split("#")[0].strip().strip("'\""))
    return datos


def ficheros_de(fm):
    """Las rutas que POSEE una unidad, normalizadas como en `unidad.py`.

    `./API/x.py` y `api/x.py` son el mismo fichero en macOS y en Windows: si no
    se normaliza, el tablero diría «no chocan» donde el despacho dice «chocan».
    """
    crudos = (fm.get("ficheros") or "").strip("[]").split(",")
    limpias = set()
    for crudo in crudos:
        ruta = crudo.strip().strip("'\"")
        if ruta:
            limpias.add(posixpath.normpath(ruta.replace("\\", "/")).casefold())
    return limpias


# H1 del revisor de la 078: la sección se localiza por su LÍNEA de cabecera, no por la
# primera mención de esas palabras en el texto. Con un `split("## Plan")` bastaba con que la
# prosa de más arriba citara la sección —cosa que las propias plantillas hacen— para anclar
# el conteo en el párrafo equivocado y volver a enseñar un plan vacío.
RE_PLAN_FICHA = re.compile(r"^#{2,6}[ \t]+[^\n]*Plan de trabajo[^\n]*$", re.M)
RE_PLAN_HALLAZGOS = re.compile(r"^##[ \t]+Plan[ \t]*$", re.M)
RE_CORTE_SECCION = re.compile(r"^## ", re.M)


def _casillas(texto, patron):
    """Casillas marcadas/totales bajo esa cabecera, hasta el siguiente `## `. None si no hay.

    El corte importa desde el bug 078: `hallazgos.md` lleva más abajo la «Bitácora del
    cierre», que también son casillas y NO son el plan. Un `### sub-apartado` no corta, que
    es lo que mantiene intacta la lectura de las fichas de bug, donde el plan cuelga de
    `### Plan de trabajo del subagente`.
    """
    casa = patron.search(texto or "")
    if casa is None:
        return None
    inicio = casa.end()
    corte = RE_CORTE_SECCION.search(texto, inicio)
    cuerpo = texto[inicio:corte.start() if corte else len(texto)]
    hechos = total = 0
    for linea in cuerpo.splitlines():
        casilla = TAREA.match(linea)
        if casilla:
            total += 1
            hechos += casilla.group(1).lower() == "x"
    return {"hechos": hechos, "total": total} if total else None


def _plan(texto, texto_hallazgos=""):
    """Cuántos pasos del plan están marcados: la fase de verdad.

    Bug 078: se cuenta sobre `hallazgos.md`, no sobre la ficha. La ficha corre en 0444
    mientras dura la obra (unidad 028), así que sus casillas no las puede marcar quien
    construye — contarlas ahí daba «Plan: 0 de 8» con constructores llevando media hora, un
    dato que mentía. La ficha sigue siendo el respaldo (R4) para las unidades que ya estaban
    en vuelo, y para los bugs, cuya ficha SÍ es su propia bitácora.
    """
    plan = _casillas(texto_hallazgos or "", RE_PLAN_HALLAZGOS)
    if plan is not None:
        return plan
    return _casillas(texto, RE_PLAN_FICHA)


# --------------------------------------------------------------------------- unidades y bugs

def _ficha(ruta, carpeta, origen, relativa):
    try:
        texto = Path(ruta).read_text(encoding="utf-8")
    except OSError:
        texto = ""
    # Bug 078: el progreso vive en `hallazgos.md`, el único fichero de la unidad que el
    # constructor puede escribir. Un bug no tiene hallazgos aparte (ADR-006): su ficha es a
    # la vez contrato y bitácora, así que se queda con su propio texto.
    texto_hallazgos = ""
    if origen != "bug":
        hallazgos = Path(ruta).parent / "hallazgos.md"
        try:
            texto_hallazgos = hallazgos.read_text(encoding="utf-8")
        except OSError:
            texto_hallazgos = ""
    fm = frontmatter(texto)
    aprobado = fm.get("aprobado", "")
    return {
        "unidad": fm.get("unidad") or carpeta,
        "carpeta": carpeta,
        "origen": origen,
        "tipo": fm.get("tipo", ""),
        "carril": fm.get("carril", ""),
        "estado": fm.get("estado", ""),
        "actividad": fm.get("actividad", ""),
        "aprobado": aprobado,
        "pendiente_de_aprobar": not FECHA.match(aprobado or ""),
        "actualizado": fm.get("actualizado", ""),
        "fusion": fm.get("fusion", ""),
        "ficheros": sorted(ficheros_de(fm)),
        "plan": _plan(texto, texto_hallazgos),
        "fase": FASES.get(fm.get("estado", ""), fm.get("estado", "") or "sin estado"),
        "ficha": relativa,
    }


def unidades(workspace):
    """Todas las fichas vivas: `docs/05-trabajo/` y `docs/bugs/`, sin ocultar ninguna."""
    raiz = Path(workspace)
    trabajo = raiz / "docs" / "05-trabajo"
    bugs = raiz / "docs" / "bugs"
    if not trabajo.is_dir():
        return {"estado": AUSENTE, "leido": _leido(),
                "detalle": "no existe docs/05-trabajo/", "lista": []}
    lista = []
    for nombre in sorted(os.listdir(str(trabajo))):
        if not NOMBRE_UNIDAD.match(nombre):
            continue  # archivo/, peticiones/, ESTADO.md: no son unidades
        ruta = trabajo / nombre / "especificacion.md"
        if ruta.is_file():
            lista.append(_ficha(ruta, nombre, "trabajo",
                                "docs/05-trabajo/%s/especificacion.md" % nombre))
    if bugs.is_dir():
        for nombre in sorted(os.listdir(str(bugs))):
            if not nombre.endswith(".md") or not NOMBRE_UNIDAD.match(nombre[:-3]):
                continue  # INDICE.md y demás soporte no son fichas de bug
            ruta = bugs / nombre
            if ruta.is_file():
                lista.append(_ficha(ruta, nombre[:-3], "bug",
                                    "docs/bugs/%s" % nombre))
    lista.sort(key=lambda u: u["carpeta"])
    return {"estado": OK, "leido": _leido(), "lista": lista}


def bloqueo_de(ficha, censo):
    """Con qué unidad EN VUELO choca una planificada y en qué ficheros.

    El mismo cruce que hace `unidad.py despachar`: conjuntos de rutas declaradas
    en `ficheros:`. Si no comparte ninguna, no está bloqueada por ficheros y el
    tablero no se inventa otra razón.
    """
    if ficha["estado"] != "planificada":
        return None
    mios = set(ficha["ficheros"])
    if not mios:
        return None
    con, comunes = [], set()
    for otra in censo:
        if otra["carpeta"] == ficha["carpeta"] or otra["estado"] not in EN_VUELO:
            continue
        cruce = mios & set(otra["ficheros"])
        if cruce:
            con.append(otra["carpeta"])
            comunes |= cruce
    if not con:
        return None
    return {"con": sorted(con), "ficheros": sorted(comunes)}


# --------------------------------------------------------------------------- peticiones

def peticiones(workspace):
    """`docs/05-trabajo/peticiones/*/peticion.json`, lo que lista `peticion.py`."""
    raiz = Path(workspace) / "docs" / "05-trabajo" / "peticiones"
    if not raiz.is_dir():
        return {"estado": AUSENTE, "leido": _leido(),
                "detalle": "no existe docs/05-trabajo/peticiones/", "lista": []}
    lista = []
    for carpeta in sorted(raiz.iterdir()):
        fichero = carpeta / "peticion.json"
        if not fichero.is_file():
            continue
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        original = datos.get("original") or {}
        marca = datos.get("creada") or datos.get("actualizada") or ""
        lista.append({
            "id": datos.get("id") or carpeta.name,
            "estado": datos.get("estado", ""),
            "resumen": _sin_pii(original.get("resumen", ""))[:300],
            "desde": marca,
            "dias": _dias_desde(marca),
            "procesos": [
                {"tipo": p.get("tipo", ""), "ref": p.get("ref", ""),
                 "estado": p.get("estado", "")}
                for p in (datos.get("procesos") or [])
            ],
        })
    lista.sort(key=lambda p: p["id"])
    return {"estado": OK, "leido": _leido(), "lista": lista}


# --------------------------------------------------------------------------- agentes

def _pid_vivo(pid):
    """Mismo criterio que `lease._pid_vivo`: en Windows una señal MATA el proceso."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":  # pragma: no cover - rama Windows, la ejercita su CI
        import ctypes

        CONSULTA = 0x1000
        ACCESO_DENEGADO = 5
        SIGUE_VIVO = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(CONSULTA, False, pid)
        if not handle:
            return ctypes.get_last_error() == ACCESO_DENEGADO
        try:
            codigo = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(codigo)):
                return codigo.value == SIGUE_VIVO
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        pass
    return True


def _cerrojos(workspace):
    """Los cerrojos activos agrupados por sesión: `.runtime/leases/active/*.json`."""
    raiz = Path(workspace) / ".runtime" / "leases" / "active"
    por_sesion = {}
    if not raiz.is_dir():
        return por_sesion
    for fichero in sorted(raiz.glob("*.json")):
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dueno = datos.get("owner") or {}
        sesion = dueno.get("session_id")
        if not sesion:
            continue
        por_sesion.setdefault(sesion, []).append({
            "scope": datos.get("scope", ""),
            "pid": dueno.get("pid"),
            "creado": datos.get("created", ""),
        })
    return por_sesion


def _checkpoint_legible(checkpoint, workspace):
    """El último paso del agente, sin la ruta absoluta de la máquina.

    Los checkpoints de `ejecucion.py` llevan el worktree entero
    (`/Users/<quien>/…/worktrees/058-…`): eso es el nombre de la persona en
    pantalla (R8) y además tapa la única línea que importa. Se recorta a lo
    que se lee de un vistazo.
    """
    detalle = str(checkpoint.get("detalle") or "")
    raiz = str(Path(workspace).resolve())
    detalle = detalle.replace(raiz + os.sep, "").replace(raiz, ".")
    detalle = re.sub(r"(/[^\s]*/)+", "…/", detalle)
    if len(detalle) > 160:
        detalle = detalle[:157] + "…"
    return {"nombre": checkpoint.get("nombre", ""),
            "estado": checkpoint.get("estado", ""),
            "detalle": _sin_pii(detalle)}


def _ficheros_tocados(cwd):
    """Lo que el agente lleva movido en SU worktree: `git status --short`.

    Es lo único comprobable de «qué está haciendo»: el recibo no lo guarda
    (P2 de la investigación) y el tablero no se lo inventa.
    """
    if not cwd or not Path(cwd).is_dir():
        return {"estado": NO_COMPROBABLE, "lista": []}
    salida = _git(cwd, "status", "--short")
    if salida.returncode != 0:
        return {"estado": NO_COMPROBABLE, "lista": []}
    rutas = []
    for linea in salida.stdout.splitlines():
        ruta = linea[3:].strip().strip('"')
        if " -> " in ruta:
            ruta = ruta.split(" -> ", 1)[1]
        if ruta:
            rutas.append(ruta)
    return {"estado": OK, "lista": sorted(rutas)[:20]}


def agentes(workspace):
    """Quién trabaja AHORA y quién terminó hoy (R1).

    «Vivo» = recibo de ejecución sin `resultado` **y** un cerrojo de su sesión
    con el PID todavía existente. Las dos condiciones: un recibo abierto de una
    sesión que murió sin cerrar no es un agente trabajando, es un cadáver.
    """
    raiz = Path(workspace) / ".runtime" / "ejecuciones"
    if not raiz.is_dir():
        return {"estado": AUSENTE, "leido": _leido(),
                "detalle": "no existe .runtime/ejecuciones/",
                "vivos": [], "terminados_hoy": []}
    por_sesion = _cerrojos(workspace)
    vivos, terminados = [], []
    for fichero in sorted(raiz.glob("*.json")):
        try:
            recibo = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if recibo.get("schema") != "ejecucion/v1":
            continue
        sesion = (recibo.get("lease") or {}).get("session_id") or ""
        cerrojos = por_sesion.get(sesion, [])
        pid_vivo = any(_pid_vivo(c["pid"]) for c in cerrojos)
        vivo = "resultado" not in recibo and pid_vivo

        arranque = min((c["creado"] for c in cerrojos if c["creado"]), default="")
        if arranque:
            minutos = (_dias_desde(arranque) or 0) * 1440
            try:
                inicio = datetime.fromisoformat(arranque.replace("Z", "+00:00"))
                if inicio.tzinfo is None:
                    inicio = inicio.replace(tzinfo=timezone.utc)
                minutos = int((_ahora() - inicio).total_seconds() // 60)
            except ValueError:
                minutos = None
        else:
            minutos = int((time.time() - fichero.stat().st_mtime) // 60)

        checkpoints = recibo.get("checkpoints") or []
        rol = recibo.get("rol") or ""
        ultimo = _checkpoint_legible(checkpoints[-1], workspace) if checkpoints else None
        ficha = {
            "unidad": recibo.get("unidad", ""),
            "rol": rol,
            "avatar": rol if rol in ROLES else "otro",
            "modelo": recibo.get("modelo") or "sin declarar",
            "harness": recibo.get("harness", ""),
            "minutos": minutos,
            "arranque": arranque,
            "checkpoint": ultimo,
            "checkpoints": len(checkpoints),
            "vivo": vivo,
            "resultado": recibo.get("resultado"),
            "exit_code": recibo.get("exit_code"),
            "worktree": Path(recibo.get("cwd") or "").name,
            "ficha": "docs/05-trabajo/%s/especificacion.md" % recibo.get("unidad", ""),
        }
        if vivo:
            tocados = _ficheros_tocados(recibo.get("cwd"))
            ficha["ficheros"] = tocados["lista"]
            ficha["ficheros_estado"] = tocados["estado"]
            vivos.append(ficha)
        elif datetime.fromtimestamp(fichero.stat().st_mtime).date() == _hoy_local():
            terminados.append(ficha)
    vivos.sort(key=lambda a: (-(a["minutos"] or 0), a["unidad"]))
    terminados.sort(key=lambda a: a["unidad"])
    return {"estado": OK, "leido": _leido(),
            "vivos": vivos, "terminados_hoy": terminados}


# --------------------------------------------------------------------------- por hacer

def por_hacer(workspace, censo=None):
    """Lo que queda, con su fase y con por qué una planificada no arranca (R3)."""
    censo = censo if censo is not None else unidades(workspace)
    if censo["estado"] != OK:
        return {"estado": censo["estado"], "leido": _leido(),
                "detalle": censo.get("detalle", ""), "unidades": [],
                "peticiones": {}}
    lista = []
    for ficha in censo["lista"]:
        if ficha["estado"] not in POR_HACER:
            continue
        fila = dict(ficha)
        fila["bloqueo"] = bloqueo_de(ficha, censo["lista"])
        fila["enlace"] = "/doc/" + ficha["ficha"]
        lista.append(fila)
    peticion = peticiones(workspace)
    por_estado = {}
    for fila in peticion["lista"]:
        if fila["estado"] in ("cerrada",):
            continue  # cerradas van al historial, no a lo que queda por hacer
        por_estado.setdefault(fila["estado"], []).append(fila)
    return {"estado": OK, "leido": _leido(), "unidades": lista,
            "peticiones": por_estado, "peticiones_estado": peticion["estado"]}


# --------------------------------------------------------------------------- te toca a ti

def te_toca(workspace, censo=None, puerto_contratos=PUERTO_CONTRATOS):
    """Las tres cosas que esperan a una persona, con enlace a donde se hacen (R2)."""
    censo = censo if censo is not None else unidades(workspace)
    if censo["estado"] != OK:
        return {"estado": censo["estado"], "leido": _leido(),
                "detalle": censo.get("detalle", ""),
                "contratos": [], "en_validacion": [], "peticiones": []}
    contratos, validacion = [], []
    for ficha in censo["lista"]:
        espera = ficha["actualizado"] or ficha["aprobado"]
        fila = {
            "unidad": ficha["carpeta"],
            "titulo": ficha["unidad"],
            "tipo": ficha["tipo"],
            "origen": ficha["origen"],
            "estado": ficha["estado"],
            "desde": espera,
            "dias": _dias_desde(espera) or 0,
        }
        if ficha["pendiente_de_aprobar"] and ficha["estado"] not in CERRADAS:
            # El sitio donde SE APRUEBA es el visor de contratos, no éste.
            fila = dict(fila)
            fila["enlace"] = "http://127.0.0.1:%d/#%s" % (puerto_contratos,
                                                          ficha["carpeta"])
            contratos.append(fila)
        elif ficha["estado"] == "en_validacion":
            # La validación guiada todavía no existe (fuera de alcance de esta
            # unidad): hasta que exista, el enlace lleva a la ficha renderizada.
            fila = dict(fila)
            fila["enlace"] = "/doc/" + ficha["ficha"]
            validacion.append(fila)
    capturadas = [
        dict(p, enlace=None)
        for p in peticiones(workspace)["lista"] if p["estado"] == "capturada"
    ]
    for fila in capturadas:
        fila["dias"] = fila["dias"] or 0
    return {"estado": OK, "leido": _leido(), "contratos": contratos,
            "en_validacion": validacion, "peticiones": capturadas}


# --------------------------------------------------------------------------- historial

def historial(workspace, censo=None):
    """Lo entregado, por fecha de OK, y los commits de `main` de hoy (R4)."""
    raiz = Path(workspace)
    censo = censo if censo is not None else unidades(workspace)
    entregas = []
    archivo = raiz / "docs" / "05-trabajo" / "archivo"
    if archivo.is_dir():
        for carpeta in sorted(archivo.iterdir()):
            ruta = carpeta / "especificacion.md"
            if not (NOMBRE_UNIDAD.match(carpeta.name) and ruta.is_file()):
                continue
            relativa = "docs/05-trabajo/archivo/%s/especificacion.md" % carpeta.name
            ficha = _ficha(ruta, carpeta.name, "archivo", relativa)
            entregas.append({
                "unidad": ficha["carpeta"], "titulo": ficha["unidad"],
                "tipo": ficha["tipo"], "origen": "archivo",
                "fecha": ficha["actualizado"] or ficha["aprobado"],
                "fusion": ficha["fusion"], "enlace": "/doc/" + relativa,
            })
    if censo["estado"] == OK:
        for ficha in censo["lista"]:
            if ficha["origen"] == "bug" and ficha["estado"] in CERRADAS:
                entregas.append({
                    "unidad": ficha["carpeta"], "titulo": ficha["unidad"],
                    "tipo": ficha["tipo"], "origen": "bug",
                    "fecha": ficha["actualizado"] or ficha["aprobado"],
                    "fusion": ficha["fusion"],
                    "enlace": "/doc/" + ficha["ficha"],
                })
    entregas.sort(key=lambda e: (e["fecha"] or "", e["unidad"]), reverse=True)
    return {"estado": OK, "leido": _leido(), "entregas": entregas,
            "commits": commits_del_dia(raiz / "main")}


def commits_del_dia(repo):
    """Lo que se ha fusionado hoy en el repo de código. Sin repo: se dice."""
    if not (Path(repo) / ".git").exists():
        return {"estado": AUSENTE, "detalle": "no hay repo en %s" % repo,
                "lista": []}
    salida = _git(repo, "log", "--since=midnight", "--no-merges",
                  "--format=%h\x1f%s\x1f%cI", "-n", "40")
    if salida.returncode != 0:
        return {"estado": NO_COMPROBABLE,
                "detalle": salida.stderr.strip()[:200] or "git falló",
                "lista": []}
    lista = []
    for linea in salida.stdout.splitlines():
        trozos = linea.split("\x1f")
        if len(trozos) == 3:
            lista.append({"sha": trozos[0], "titulo": _sin_pii(trozos[1]),
                          "fecha": trozos[2]})
    return {"estado": OK, "lista": lista}


# --------------------------------------------------------------------------- documentación

def documentacion(workspace):
    """El árbol de `docs/`: sólo `.md`, y `.private/` no existe para el tablero (R5, R8)."""
    raiz = Path(workspace)
    docs = raiz / "docs"
    if not docs.is_dir():
        return {"estado": AUSENTE, "leido": _leido(),
                "detalle": "no existe docs/", "portada": None, "ficheros": []}
    ficheros = []
    for actual, subcarpetas, nombres in os.walk(str(docs)):
        subcarpetas[:] = sorted(s for s in subcarpetas if not s.startswith("."))
        for nombre in sorted(nombres):
            if not nombre.endswith(".md") or nombre.startswith("."):
                continue
            relativa = Path(actual, nombre).relative_to(raiz).as_posix()
            ficheros.append(relativa)
    ficheros.sort()
    portada = "docs/05-trabajo/ESTADO.md"
    if portada not in ficheros:
        portada = ficheros[0] if ficheros else None
    return {"estado": OK, "leido": _leido(), "portada": portada,
            "ficheros": ficheros}


# --------------------------------------------------------------------------- cabecera

def _version(workspace):
    raiz = Path(workspace)
    local = raiz / "docs" / "00-metodo" / "VERSION"
    publicada = raiz / "main" / "plantilla" / "docs" / "00-metodo" / "VERSION"
    try:
        texto_local = local.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {"estado": NO_COMPROBABLE, "detalle": str(exc)[:200],
                "local": None, "publicada": None, "al_dia": None}
    try:
        texto_publicada = publicada.read_text(encoding="utf-8").strip()
    except OSError:
        # Un proyecto ya creado tiene un repo de código normal en `main/`, no
        # el repositorio fuente de esta herramienta con su `plantilla/`. En
        # ese caso el manifiesto instalado es la autoridad de qué versión se
        # repartió al workspace. La ausencia de una ruta que no aplica no es
        # un error de lectura.
        try:
            manifiesto = json.loads((raiz / "METODO.json").read_text(encoding="utf-8"))
            texto_publicada = str(manifiesto["version"]).strip()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"estado": NO_COMPROBABLE, "detalle": str(exc)[:200],
                    "local": texto_local, "publicada": None, "al_dia": None}
    return {"estado": OK, "local": texto_local, "publicada": texto_publicada,
            "al_dia": texto_local == texto_publicada}


def _listeners_windows():
    """Listeners con PID y comando usando las APIs nativas de PowerShell."""
    guion = (
        "$map=@{}; Get-CimInstance Win32_Process | ForEach-Object { "
        "$map[[int]$_.ProcessId]=$_.CommandLine }; "
        "@(Get-NetTCPConnection -State Listen | ForEach-Object { "
        "[pscustomobject]@{pid=[int]$_.OwningProcess; puerto=[int]$_.LocalPort; "
        "comando=[string]$map[[int]$_.OwningProcess]} }) | ConvertTo-Json -Compress"
    )
    salida = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", guion],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
    )
    if salida.returncode != 0:
        raise OSError("PowerShell devolvió %d: %s" %
                      (salida.returncode, salida.stderr.strip()[:120]))
    try:
        datos = json.loads(salida.stdout or "[]")
    except ValueError as exc:
        raise OSError("PowerShell no devolvió JSON de listeners") from exc
    if isinstance(datos, dict):
        datos = [datos]
    return [{"pid": int(fila["pid"]), "puerto": int(fila["puerto"]),
             "comando": fila.get("comando") or "", "cwd": None}
            for fila in datos]


def _sin_empujar(repo):
    """Commits que este repo tiene y su remoto no. Sin remoto: NO son cero."""
    if not (Path(repo) / ".git").exists():
        return {"estado": AUSENTE, "commits": None,
                "detalle": "no hay repo en %s" % repo}
    salida = _git(repo, "rev-list", "--count", "@{u}..HEAD")
    if salida.returncode != 0:
        return {"estado": NO_COMPROBABLE, "commits": None,
                "detalle": (salida.stderr.strip().splitlines() or
                            ["sin rama de seguimiento"])[0][:200]}
    try:
        return {"estado": OK, "commits": int(salida.stdout.strip()), "detalle": ""}
    except ValueError:
        return {"estado": NO_COMPROBABLE, "commits": None,
                "detalle": "git devolvió algo que no es un número"}


def _canario(workspace):
    """El veredicto del canario de contexto, tal cual lo da él (`--json`)."""
    guion = Path(workspace) / "docs" / "00-metodo" / "scripts" / "canario.py"
    vacio = {"estado": NO_COMPROBABLE, "veredicto": None, "porcentaje": None,
             "modelo": None, "sintoma": None}
    if not guion.is_file():
        return dict(vacio, detalle="no está %s" % guion.name)
    try:
        salida = subprocess.run(
            [sys.executable, str(guion), "--json"], cwd=str(workspace),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return dict(vacio, detalle=str(exc)[:200])
    if salida.returncode != 0 or not salida.stdout.strip():
        return dict(vacio, detalle=(salida.stderr.strip()[:200] or
                                    "el canario no dijo nada"))
    try:
        informe = json.loads(salida.stdout.strip().splitlines()[-1])
    except ValueError:
        return dict(vacio, detalle="el canario no devolvió JSON")
    return {
        "estado": OK,
        "veredicto": informe.get("veredicto"),
        # Sin ventana declarada el canario NO da porcentaje: aquí tampoco se inventa.
        "porcentaje": informe.get("porcentaje") if informe.get("ventana") else None,
        "modelo": informe.get("modelo"),
        "ventana": informe.get("ventana"),
        "tokens": informe.get("tokens"),
        "sintoma": informe.get("sintoma"),
        "detalle": "",
    }


def _procesos_escuchando():
    """(pid, puerto, comando) de lo que escucha en los puertos de las webs.

    Best-effort con `lsof`, como hace `unidad.py` para los worktrees ocupados:
    si no está, la sección lo dice en vez de asegurar que no hay nada levantado.
    """
    if os.name == "nt":
        return [p for p in _listeners_windows()
                if p["puerto"] in PUERTOS_VIGILADOS]
    salida = subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=10,
    )
    if salida.returncode not in (0, 1):
        raise OSError("lsof devolvió %d" % salida.returncode)
    procesos, pid = [], None
    for linea in salida.stdout.splitlines():
        if linea.startswith("p"):
            pid = linea[1:].strip()
        elif linea.startswith("n") and pid:
            direccion = linea[1:].strip()
            if ":" not in direccion:
                continue
            try:
                puerto = int(direccion.rsplit(":", 1)[1])
            except ValueError:
                continue
            if puerto not in PUERTOS_VIGILADOS:
                continue
            comando = subprocess.run(
                ["ps", "-o", "command=", "-p", pid], capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=10,
            ).stdout.strip()
            procesos.append({"pid": int(pid), "puerto": puerto,
                             "comando": comando, "cwd": _cwd_de(pid)})
    return procesos


def _cwd_de(pid):
    """Desde dónde corre un proceso, para poder resolver su ruta relativa."""
    try:
        salida = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for linea in salida.stdout.splitlines():
        if linea.startswith("n/"):
            return linea[1:].strip()
    return None


def _arbol_de(comando, workspace, cwd=None, servicios=SERVICIOS):
    """De qué árbol sirve un visor: la carpeta que contiene su paquete.

    Es la mitad interesante de R6 — «visor de contratos: worktree 056, no main»:
    saber que hay algo en el 8766 no dice nada si no se sabe qué código sirve.

    Las webs se lanzan tanto con ruta absoluta como relativa
    (`python3 main/visor_contratos/servir.py`). Una ruta relativa sólo
    significa algo junto al `cwd` DEL SERVIDOR: resolverla contra el cwd del
    tablero decía «worktree 058» de un servidor que corría desde `main/` —
    justo la mentira que R6 existe para evitar. Sin `cwd` no se adivina: el
    árbol viaja como `None` y la web lo dice.
    """
    for trozo in comando.split():
        if not trozo.endswith("servir.py"):
            continue
        camino = Path(trozo)
        paquete = camino.parent
        for carpeta, servicio in servicios:
            if paquete.name != carpeta:
                continue
            if not camino.is_absolute():
                if not cwd:
                    return servicio, None
                paquete = Path(cwd) / paquete
            arbol = paquete.parent
            try:
                relativo = arbol.resolve().relative_to(Path(workspace).resolve())
                nombre = relativo.as_posix() or "."
            except (ValueError, OSError):
                nombre = arbol.as_posix()
            return servicio, nombre
    return None, None


def servidores(workspace, procesos=None):
    """Qué webs están levantadas, en qué puerto y desde qué árbol (R6)."""
    proveedor = procesos or _procesos_escuchando
    try:
        crudos = proveedor()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"estado": NO_COMPROBABLE, "lista": [],
                "detalle": "no pude mirar los puertos: %s" % str(exc)[:120]}
    lista = []
    for proceso in crudos:
        servicio, arbol = _arbol_de(proceso.get("comando", ""), workspace,
                                    proceso.get("cwd"))
        if not servicio:
            continue
        lista.append({"servicio": servicio, "puerto": proceso.get("puerto"),
                      "pid": proceso.get("pid"), "arbol": arbol})
    lista.sort(key=lambda s: (s["puerto"] or 0, s["servicio"]))
    return {"estado": OK, "lista": lista, "detalle": ""}


def cabecera(workspace, procesos=None):
    """La verdad de un vistazo: versión, lo no empujado, el canario y las webs."""
    raiz = Path(workspace)
    return {
        "estado": OK,
        "leido": _leido(),
        "version": _version(workspace),
        "sin_empujar": {"main": _sin_empujar(raiz / "main"),
                        "meta": _sin_empujar(raiz)},
        "canario": _canario(workspace),
        "servidores": servidores(workspace, procesos),
    }


# --------------------------------------------------------------------------- taller

def _url_github(remoto):
    """La URL que abriría una persona, o `None` si el remoto no es de GitHub.

    Las cuatro formas que escribe `git remote add` en esta casa —SSH corto,
    SSH largo, `git://` y HTTPS con o sin usuario— acaban en la misma página.
    Cualquier otro alojamiento NO se convierte: un enlace inventado es peor
    que ningún enlace.
    """
    encaje = GITHUB.match((remoto or "").strip())
    return "https://github.com/" + encaje.group("ruta") if encaje else None


def _nombre_de_repo(remoto, ruta):
    """El nombre por el que se conoce el repo: el del remoto, o el de su carpeta."""
    limpio = (remoto or "").strip().rstrip("/")
    if limpio:
        if limpio.endswith(".git"):
            limpio = limpio[:-4]
        ultimo = limpio.replace("\\", "/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        if ultimo:
            return ultimo
    return Path(ruta).resolve().name or None


def _cambios_sin_commitear(ruta):
    """Cuántas rutas lleva tocadas el repo. Sin poder mirar: NO es cero (G-2302)."""
    salida = _git(ruta, "status", "--porcelain")
    if salida.returncode != 0:
        return {"estado": NO_COMPROBABLE, "cambios": None,
                "detalle": (salida.stderr.strip().splitlines() or
                            ["git no pudo mirar el repo"])[0][:200]}
    lineas = [l for l in salida.stdout.splitlines() if l.strip()]
    return {"estado": OK, "cambios": len(lineas), "detalle": ""}


def _repo(ruta, clave):
    """Un repo del taller: nombre, rama, enlace y sus dos cuentas (R1).

    De la ruta sólo viaja el último tramo: el resto es el nombre de la persona
    y su árbol de carpetas, que no salen por la web (R8 de la 058).
    """
    ruta = Path(ruta)
    vacio = {
        "clave": clave, "carpeta": ruta.name or ".", "nombre": None,
        "rama": None, "remoto": None, "github": None,
        "sin_commitear": {"estado": AUSENTE, "cambios": None, "detalle": ""},
        "sin_empujar": {"estado": AUSENTE, "commits": None, "detalle": ""},
    }
    if not (ruta / ".git").exists():
        return dict(vacio, estado=AUSENTE,
                    detalle="no hay repo git en %s" % (ruta.name or "."))
    remoto = _git(ruta, "remote", "get-url", "origin")
    url = remoto.stdout.strip() if remoto.returncode == 0 else ""
    rama = _git(ruta, "rev-parse", "--abbrev-ref", "HEAD")
    return {
        "clave": clave,
        "carpeta": ruta.name or ".",
        "estado": OK,
        "detalle": "",
        "nombre": _nombre_de_repo(url, ruta),
        "rama": rama.stdout.strip() if rama.returncode == 0 else None,
        # El remoto se enseña sólo cuando es público: un `file:///Users/...`
        # sería la ruta de la persona en pantalla.
        "remoto": url if _url_github(url) else None,
        "github": _url_github(url),
        "sin_commitear": _cambios_sin_commitear(ruta),
        "sin_empujar": _sin_empujar(ruta),
    }


def _listeners():
    """(pid, puerto, comando, cwd) de TODO servidor del método que escucha.

    A diferencia de `_procesos_escuchando`, que sólo mira los cuatro puertos
    históricos, aquí no se filtra por puerto: desde la 081 el puerto sale de la
    huella del workspace y no hay lista que valga. Se filtra por lo que corre —
    un `servir.py` del método— y con UNA sola llamada a `ps` para todos los
    pids, que si no esto costaría un proceso por conexión abierta de la máquina.
    """
    if os.name == "nt":
        return _listeners_windows()
    salida = subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=SEGUNDOS_COMANDO_EXTERNO,
    )
    if salida.returncode not in (0, 1):
        raise OSError("lsof devolvió %d" % salida.returncode)
    pares, pid = [], None
    for linea in salida.stdout.splitlines():
        if linea.startswith("p"):
            pid = linea[1:].strip()
        elif linea.startswith("n") and pid:
            direccion = linea[1:].strip()
            if ":" not in direccion:
                continue
            try:
                pares.append((int(pid), int(direccion.rsplit(":", 1)[1])))
            except ValueError:
                continue
    if not pares:
        return []
    pids = sorted({str(par[0]) for par in pares})
    comandos = {}
    ps = subprocess.run(
        ["ps", "-o", "pid=,command=", "-p", ",".join(pids)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=SEGUNDOS_COMANDO_EXTERNO,
    )
    for linea in ps.stdout.splitlines():
        trozos = linea.strip().split(None, 1)
        if len(trozos) == 2 and trozos[0].isdigit():
            comandos[int(trozos[0])] = trozos[1]
    procesos = []
    for pid, puerto in sorted(set(pares)):
        comando = comandos.get(pid, "")
        if "servir.py" not in comando:
            continue
        procesos.append({"pid": pid, "puerto": puerto, "comando": comando,
                         "cwd": _cwd_de(pid)})
    return procesos


def _recibos_de_servidor(workspace):
    """`{puerto: (servicio, desde)}` leído de los rastros de `.runtime/`.

    Cada web del método deja un `.log` con su puerto en el nombre al levantarse
    (`web-9041.log`, `visor-8765.log`…). Su fecha de creación es el único
    «desde cuándo» honesto que hay en disco: el proceso no lo guarda.
    """
    runtime = Path(workspace) / ".runtime"
    encontrados = {}
    if not runtime.is_dir():
        return encontrados
    try:
        rastros = sorted(runtime.glob("*.log"))
    except OSError:
        return encontrados
    for rastro in rastros:
        for prefijo, servicio in RECIBOS_SERVIDOR:
            if not rastro.name.startswith(prefijo):
                continue
            resto = rastro.name[len(prefijo):-len(".log")]
            if not resto.isdigit():
                break
            try:
                marca = datetime.fromtimestamp(rastro.stat().st_mtime,
                                               timezone.utc)
            except OSError:
                break
            encontrados[int(resto)] = (servicio,
                                       marca.isoformat(timespec="seconds"))
            break
    return encontrados


def servidores_locales(workspace, procesos=None):
    """Los servidores del método que están escuchando AHORA (R2).

    Se cruzan dos fuentes y hacen falta las dos: los puertos realmente abiertos
    (un rastro viejo no es un servidor vivo) y los rastros de `.runtime/` (que
    son los que saben desde cuándo). Si no se pudieron mirar los puertos se
    DICE: no saber no es saber que no hay ninguno.
    """
    proveedor = procesos or _listeners
    try:
        crudos = proveedor()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"estado": NO_COMPROBABLE, "lista": [],
                "detalle": "no pude mirar los puertos: %s" % str(exc)[:120]}
    recibos = _recibos_de_servidor(workspace)
    lista = []
    for proceso in crudos:
        comando = proceso.get("comando", "")
        puerto = proceso.get("puerto")
        servicio, arbol = _arbol_de(comando, workspace, proceso.get("cwd"),
                                    SERVICIOS_TALLER)
        recibo = recibos.get(puerto)
        if not servicio:
            if not recibo or "servir.py" not in comando:
                continue
            servicio, arbol = recibo[0], None
        # `_arbol_de` devuelve la ruta TAL CUAL cuando el servidor no cuelga de
        # este workspace, y ahí dentro va el nombre de la persona
        # (`/Users/<quien>/Project/otro`). Al ampliar la mirada a todos los
        # puertos (y no a los cuatro de siempre) eso empezó a salir de verdad en
        # pantalla: fuera del workspace se dice que está fuera, y nada más (R8).
        if arbol and (arbol.startswith("/") or arbol.startswith("\\")
                      or ":" in arbol):
            arbol = "otro workspace de esta máquina"
        lista.append({"servicio": servicio, "puerto": puerto,
                      "pid": proceso.get("pid"), "arbol": arbol,
                      "desde": recibo[1] if recibo else None})
    lista.sort(key=lambda s: (s["puerto"] or 0, s["servicio"]))
    return {"estado": OK, "lista": lista, "detalle": ""}


def contenedores(ejecutar=None):
    """Lo que Docker tiene en marcha, o por qué no se sabe (R2, R6).

    `docker ps` con dos segundos de correa. Sin Docker instalado, con el demonio
    parado o si tarda, se dice en una línea y la página sigue: un cero aquí
    diría «no tienes nada levantado», que es justo lo contrario de la verdad.
    """
    correr = ejecutar or (lambda: subprocess.run(
        ["docker", "ps", "--format", "{{json .}}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=SEGUNDOS_COMANDO_EXTERNO))
    try:
        salida = correr()
    except FileNotFoundError:
        return {"estado": AUSENTE, "lista": [],
                "detalle": "Docker no disponible en esta máquina"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"estado": NO_COMPROBABLE, "lista": [],
                "detalle": "Docker no disponible: %s" % str(exc)[:120]}
    if salida.returncode != 0:
        motivo = (salida.stderr.strip() or salida.stdout.strip()
                  or "docker ps falló")
        return {"estado": NO_COMPROBABLE, "lista": [],
                "detalle": "Docker no disponible: %s" % motivo.splitlines()[0][:160]}
    lista = []
    for linea in salida.stdout.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            fila = json.loads(linea)
        except ValueError:
            continue
        lista.append({"nombre": _sin_pii(fila.get("Names", "")),
                      "imagen": _sin_pii(fila.get("Image", "")),
                      "estado": _sin_pii(fila.get("Status", ""))})
    return {"estado": OK, "lista": lista, "detalle": ""}


def sesion_principal(workspace):
    """¿La sesión que dirige el taller está trabajando ahora, o parada? (R3)

    El criterio, escrito una vez y probado:

    - **trabajando ahora** si hay al menos UNA señal viva: un cerrojo de
      `.runtime/leases/active/` cuyo PID todavía existe, o un recibo de
      `.runtime/ejecuciones/` sin `resultado` cuyo lanzador sigue vivo. Es el
      mismo criterio doble de `agentes()`: un fichero abierto de una sesión que
      murió sin cerrar no es alguien trabajando, es un cadáver.
    - **parada desde <hora>** si hay señales pero ninguna viva: la hora es la
      más reciente de todas ellas.
    - **sin datos** si no hay una sola señal: no se afirma que esté parada
      desde una hora que nadie escribió.

    Los minutos son los que lleva la señal viva más antigua, que es cuando
    empezó esta tanda de trabajo.
    """
    raiz = Path(workspace)
    vivas, todas = [], []

    for fichero in sorted((raiz / ".runtime" / "leases" / "active").glob("*.json")
                          if (raiz / ".runtime" / "leases" / "active").is_dir()
                          else []):
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        marca = datos.get("created") or ""
        todas.append(marca)
        if _pid_vivo((datos.get("owner") or {}).get("pid")):
            vivas.append(marca)

    ejecuciones = raiz / ".runtime" / "ejecuciones"
    for fichero in sorted(ejecuciones.glob("*.json") if ejecuciones.is_dir() else []):
        try:
            datos = json.loads(fichero.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            marca = datetime.fromtimestamp(
                fichero.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        except OSError:
            continue
        todas.append(marca)
        if datos.get("resultado") is not None:
            continue
        pid = (datos.get("lanzador") or {}).get("pid")
        if pid is None:
            pid = (datos.get("owner") or {}).get("pid")
        if _pid_vivo(pid):
            vivas.append(marca)

    if not todas:
        return {"estado": AUSENTE, "leido": _leido(), "activa": False,
                "desde": None, "minutos": None,
                "detalle": "sin cerrojos ni recibos: no hay dato"}
    if vivas:
        desde = min(m for m in vivas if m) if any(vivas) else None
        return {"estado": OK, "leido": _leido(), "activa": True,
                "desde": desde, "minutos": _minutos_desde(desde), "detalle": ""}
    desde = max(m for m in todas if m) if any(todas) else None
    return {"estado": OK, "leido": _leido(), "activa": False, "desde": desde,
            "minutos": _minutos_desde(desde), "detalle": ""}


def _minutos_desde(marca):
    if not marca:
        return None
    try:
        momento = datetime.fromisoformat(str(marca).replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return max(0, int((_ahora() - momento).total_seconds() // 60))


def taller(workspace, procesos=None, docker=None):
    """El estado de la máquina donde se trabaja, leído en el momento (R1-R3, R6).

    Nada de esto se guarda ni se cachea aquí: se lee del disco y de la máquina
    cada vez que se compone la foto. Ninguna de las cuatro piezas puede tumbar
    la página — cada una trae su propio `estado` y su motivo cuando no se pudo
    mirar, y los comandos externos van con correa (`SEGUNDOS_COMANDO_EXTERNO`).
    """
    raiz = Path(workspace)
    return {
        "estado": OK,
        "leido": _leido(),
        "repos": [_repo(raiz, "meta-repo"), _repo(raiz / "main", "repo de código")],
        "servidores": servidores_locales(workspace, procesos),
        "docker": contenedores(docker),
        "sesion": sesion_principal(workspace),
    }


# --------------------------------------------------------------------------- la foto entera

def instantanea(workspace, procesos=None):
    """Todo el tablero en un `dict`: lo que sirve `/estado.json`."""
    censo = unidades(workspace)
    cab = cabecera(workspace, procesos)
    puerto = PUERTO_CONTRATOS
    for fila in cab["servidores"]["lista"]:
        if fila["servicio"] == "visor de contratos" and fila["puerto"]:
            puerto = fila["puerto"]
    return {
        "generado": _leido(),
        "cabecera": cab,
        "ahora": agentes(workspace),
        "te_toca": te_toca(workspace, censo, puerto),
        "por_hacer": por_hacer(workspace, censo),
        "historial": historial(workspace, censo),
        "documentacion": documentacion(workspace),
        # Unidad 121: el estado de la máquina, que Inicio pinta arriba del todo.
        "taller": taller(workspace, procesos),
    }


class Cache:
    """La misma foto mientras nada cambie: la página sondea cada 5 s.

    Se invalida por dos vías, y hacen falta las dos: el mtime de las carpetas
    que se leen (una ficha editada se ve al instante) y un TTL corto para lo que
    no vive en un fichero del workspace — git, el canario y los puertos.
    """

    def __init__(self, workspace, ttl=4.0):
        self.workspace = str(workspace)
        self.ttl = ttl
        self._foto = None
        self._firma = None
        self._momento = 0.0

    def _firma_actual(self):
        """El mtime de cada FICHERO vigilado, no el de su carpeta.

        `ejecucion.py` cierra el recibo reescribiéndolo con el mismo nombre
        (`os.replace` sobre el temporal), y eso NO mueve el mtime del
        directorio: mirando sólo la carpeta, un agente que acaba de terminar
        seguía «vivo» en pantalla hasta que el TTL expirase. Son unos cientos
        de `stat`, muy por debajo del presupuesto de refresco (P3).
        """
        raiz = Path(self.workspace)
        marcas = []
        for partes in VIGILADAS:
            carpeta = raiz.joinpath(*partes)
            try:
                with os.scandir(str(carpeta)) as entradas:
                    for entrada in sorted(entradas, key=lambda e: e.name):
                        marcas.append((entrada.name, entrada.stat().st_mtime_ns))
                        if entrada.is_dir():
                            # docs/05-trabajo/<unidad>/especificacion.md
                            try:
                                ficha = os.stat(os.path.join(
                                    entrada.path, "especificacion.md"))
                                marcas.append((entrada.name, ficha.st_mtime_ns))
                            except OSError:
                                pass
            except OSError:
                marcas.append((str(carpeta), -1))
        return tuple(marcas)

    def instantanea(self):
        firma = self._firma_actual()
        ahora = time.monotonic()
        if (self._foto is not None and firma == self._firma
                and ahora - self._momento < self.ttl):
            return self._foto
        self._foto = instantanea(self.workspace)
        self._firma = firma
        self._momento = ahora
        return self._foto


# --------------------------------------------------------------------------- guarda de rutas

def ruta_doc(workspace, relativa):
    """La ruta real de un `.md` de dentro del meta-repo, o `ValueError`.

    Única puerta de lectura de ficheros del tablero (R8). Se rechaza, sin leer
    nada: lo que no acaba en `.md`, `..`, las rutas absolutas, `~`, y cualquier
    cosa que —resuelta, symlinks incluidos— caiga fuera del workspace o dentro
    de `.private/`. Misma guarda que `visor_presentaciones._ruta_de_adjunto`.
    """
    if not relativa or not relativa.endswith(".md"):
        raise ValueError("sólo se sirven ficheros .md")
    if relativa.startswith(("/", "~", "\\")) or ":" in relativa:
        raise ValueError("ruta absoluta")
    partes = relativa.replace("\\", "/").split("/")
    if any(parte in ("..", "") for parte in partes):
        raise ValueError("ruta con saltos")
    if any(parte.startswith(".") for parte in partes):
        raise ValueError("ruta oculta o privada")
    raiz = Path(workspace).resolve(strict=False)
    resuelta = (raiz / relativa).resolve(strict=False)
    try:
        resuelta.relative_to(raiz)
    except ValueError:
        raise ValueError("ruta fuera del meta-repo")
    if not resuelta.is_file():
        raise FileNotFoundError(relativa)
    return resuelta
