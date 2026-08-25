#!/usr/bin/env python3
"""sanidad.py — el guardián de sanidad del workspace (unidad 059, ADR-031).

Uso, desde la raíz del workspace (donde están `docs/` y `main/`):

    python3 docs/00-metodo/scripts/sanidad.py medir [--eje N] [--anotar] [--json]
                                                    [--detalle] [--estricto] [--red]
    python3 docs/00-metodo/scripts/sanidad.py reparar [--simular] [--solo N]
    python3 docs/00-metodo/scripts/sanidad.py capturar [--eje N] [--incluir-media]
    python3 docs/00-metodo/scripts/sanidad.py atraso [--estricto]
    python3 docs/00-metodo/scripts/sanidad.py ejes

Once ejes, un número y un veredicto por eje, y SIEMPRE «con qué midió»: el método tenía la
doctrina de la limpieza y ningún ejecutor (ADR-029). Lo que no se pudo medir sale como
`NO_COMPROBADO` con su `SALIDA:`, nunca como `OK` (G-2402).

Reparar es una lista CERRADA de papeles del meta-repo (actas, rutas rotas con destino
único, ficheros generados) y jamás toca código, planos ni papeles de trabajo (G-2401): el
commit lo hace el padre, con rutas explícitas. Todo lo del código sale como petición con
evidencia (`capturar`), que decide el usuario.

Solo biblioteca estándar (Python ≥ 3.9). Las herramientas externas (vulture, coverage,
interrogate, ruff, pip-audit) se usan SI ESTÁN y no se exigen: sin ellas se mide por
aproximación y se dice.
"""

import argparse
import ast
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import control_plane  # noqa: E402
import repo_config  # noqa: E402
import workspace_paths  # noqa: E402

for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

control_plane.redactar_salidas()

RAIZ = Path(__file__).resolve().parents[3]
DOCS = RAIZ / "docs"
TRABAJO = DOCS / "05-trabajo"
PETICIONES = TRABAJO / "peticiones"
ARCHIVO = TRABAJO / "archivo"
LIBRO = TRABAJO / "SANIDAD.md"
PLANTILLA_LIBRO = DOCS / "00-metodo" / "plantillas" / "sanidad.md"
PETICION_PY = Path(__file__).with_name("peticion.py")
HOY = datetime.date.today()
RUNTIME = RAIZ / ".runtime" / "sanidad"

OK, WARN, FAIL, NADA = "OK", "WARN", "FAIL", "NO_COMPROBADO"
PESO = {OK: 0, NADA: 1, WARN: 2, FAIL: 3}

# Nunca se entra aquí: `.private/` es la regla de oro (R10) y el resto es ruido generado o
# copias de trabajo que no son la verdad del workspace.
PROHIBIDAS = {
    ".private", ".git", ".runtime", "worktrees", "node_modules", "__pycache__",
    "venv", ".venv", ".tox", ".mypy_cache", ".pytest_cache", "site-packages",
    "dist", "build", ".idea", ".vscode", "migrations",
}
# Los papeles del meta que `reparar` no toca NUNCA, ni para reescribir una referencia.
INTOCABLES = (
    "docs/00-metodo", "docs/02-flujos/planos", "docs/05-trabajo/peticiones", "docs/bugs",
)
GENERADOS = (".DS_Store", "Thumbs.db")
GENERADOS_SUFIJOS = (".orig", ".rej", "~")
LISTA_BLANCA_MD = {
    "readme.md", "agents.md", "claude.md", "gemini.md", "changelog.md",
    "contributing.md", "license.md", "license", "security.md", "code_of_conduct.md",
}
CARPETAS_DOC_DEL_CODIGO = {"plantilla", "docs", "runbook", ".github"}
# Nombres que en cualquier stack los llama el marco, no el repo: no son código muerto.
NOMBRES_VIVOS = {
    "manage", "wsgi", "asgi", "settings", "urls", "admin", "apps", "models", "views",
    "forms", "serializers", "signals", "middleware", "context_processors", "conftest",
    "setup", "__main__", "main", "app",
}
FUNCIONES_VIVAS = {"main", "setUp", "tearDown", "setUpClass", "tearDownClass", "run"}
MARCAS_DEUDA = ("TODO", "FIXME", "XXX", "HACK")
DIAS_TODO_FOSIL = 90
DIAS_ACTA_VIEJA = 30
ACTAS_TOLERADAS = 2
TOPE_LIBRO = 100
TOPE_ESTADO = 100
TOPE_MD_BYTES = 40 * 1024
ATRASO_CIERRES = 5
ATRASO_DIAS = 14
SALIDA_MEDIR = "python3 docs/00-metodo/scripts/sanidad.py medir --anotar"


class Hallazgo:
    """Una cosa concreta que está mal, con su sitio y su nivel de confianza (R8)."""

    def __init__(self, ruta, texto, confianza="alta", linea=0, reparable=False,
                 destino=None):
        self.ruta = str(ruta)
        self.linea = int(linea)
        self.texto = str(texto)
        self.confianza = confianza
        self.reparable = reparable
        self.destino = destino

    def sitio(self):
        return f"{self.ruta}:{self.linea}" if self.linea else self.ruta

    def linea_de_detalle(self):
        return f"{self.sitio()} · {self.texto} · confianza {self.confianza}"

    def como_json(self):
        return {
            "ruta": self.ruta, "linea": self.linea, "texto": self.texto,
            "confianza": self.confianza, "reparable": self.reparable,
        }


class Resultado:
    """Lo que devuelve un eje: veredicto, número, con qué se midió y sus hallazgos."""

    def __init__(self, eje, veredicto, valor, unidad, midio_con, hallazgos=None,
                 motivo="", direccion="menos_mejor"):
        self.eje = eje
        self.veredicto = veredicto
        self.valor = valor
        self.unidad = unidad
        self.midio_con = midio_con
        self.hallazgos = list(hallazgos or ())
        self.motivo = motivo
        self.direccion = direccion
        self.comparacion = "primera pasada"
        self.detalle_ruta = ""

    def numero(self):
        if self.valor is None:
            return "—"
        if isinstance(self.valor, float):
            return f"{self.valor:.1f}"
        return str(self.valor)

    def como_json(self):
        return {
            "eje": self.eje, "veredicto": self.veredicto, "valor": self.valor,
            "unidad": self.unidad, "midio_con": self.midio_con, "motivo": self.motivo,
            "comparacion": self.comparacion, "detalle_ruta": self.detalle_ruta,
            "hallazgos": [h.como_json() for h in self.hallazgos],
        }


# --------------------------------------------------------------------- utilidades

def peor(*veredictos):
    return max(veredictos, key=lambda v: PESO[v]) if veredictos else OK


def prohibida(ruta, base):
    try:
        partes = ruta.relative_to(base).parts
    except ValueError:
        return True
    return bool(PROHIBIDAS & set(partes))


def recorrer(base, patron="*"):
    """Ficheros bajo `base` saltando lo prohibido y sin seguir jamás un enlace (R10)."""
    if not base.is_dir():
        return
    for ruta in sorted(base.rglob(patron)):
        if prohibida(ruta, base) or workspace_paths.es_enlace(ruta):
            continue
        if ruta.is_file():
            yield ruta


def leer(ruta):
    try:
        return ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def relativa(ruta):
    try:
        return Path(ruta).resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return str(ruta)


def intocable(ruta):
    """¿Es un papel que `reparar` no puede tocar ni para reescribir una referencia?"""
    texto = relativa(ruta)
    if any(texto.startswith(prefijo) for prefijo in INTOCABLES):
        return True
    # Papeles de una unidad (en obra o archivada): son contrato, no papeles sueltos.
    partes = texto.split("/")
    if partes[:2] == ["docs", "05-trabajo"] and len(partes) > 2:
        siguiente = partes[2]
        if siguiente == "archivo":
            return len(partes) > 3
        if re.match(r"^\d{3}-", siguiente):
            return True
    return False


def herramienta(nombre):
    """Ruta de una herramienta externa, o None. Nunca mira el directorio actual."""
    return workspace_paths.which_sin_cwd(nombre)


def correr(orden, cwd=None, timeout=45):
    """(ok, salida). Una herramienta ausente o rota es un dato, jamás una excepción."""
    if not orden or herramienta(orden[0]) is None:
        return False, ""
    try:
        proceso = subprocess.run(
            list(orden), cwd=str(cwd) if cwd else None, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return proceso.returncode == 0, (proceso.stdout or "") + (proceso.stderr or "")


def repo_codigo():
    """Raíz del repo de código, o None si este workspace todavía no tiene ninguno."""
    try:
        ruta, _rama = repo_config.repo_code(RAIZ)
    except (repo_config.RepoConfigError, workspace_paths.WorkspacePathError, OSError):
        ruta = RAIZ / "main"
    return ruta if ruta.is_dir() else None


def sin_codigo(eje, unidad):
    return Resultado(
        eje, NADA, None, unidad, "stdlib:sin-repo",
        motivo="este workspace no tiene repo de código todavía · "
               "SALIDA: clónalo en main/ (repos.yaml) y vuelve a medir",
    )


def edad_en_dias(instante):
    if instante is None:
        return None
    return (HOY - instante).days


def fecha_de(texto):
    """Primera fecha ISO de un texto (frontmatter, línea de libro, salida de git)."""
    encontrada = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(texto))
    if not encontrada:
        return None
    try:
        return datetime.date(*(int(g) for g in encontrada.groups()))
    except ValueError:
        return None


def frontmatter(texto):
    if not texto.startswith("---"):
        return {}
    fin = texto.find("\n---", 3)
    if fin < 0:
        return {}
    datos = {}
    for linea in texto[3:fin].splitlines():
        if ":" in linea and not linea.startswith((" ", "\t", "#")):
            clave, valor = linea.split(":", 1)
            datos[clave.strip()] = valor.split("#", 1)[0].strip()
    return datos


def fecha_git(ruta, base):
    """Fecha del último commit que tocó un fichero, o None si aquí no hay git."""
    ok, salida = correr(
        ["git", "-C", str(base), "log", "-1", "--format=%cI", "--", str(ruta)],
        timeout=20,
    )
    return fecha_de(salida) if ok else None


def fecha_de_fichero(ruta, base=None):
    """Fecha del fichero: git si lo hay (el clon miente con las mtime), si no la mtime."""
    if base is not None:
        del_git = fecha_git(ruta, base)
        if del_git:
            return del_git
    try:
        return datetime.date.fromtimestamp(ruta.stat().st_mtime)
    except OSError:
        return None


# ------------------------------------------------------- 1 · pendiente (meta-repo)

def peticiones_en_cola():
    """(id, estado, edad en días) de cada petición que sigue esperando triaje."""
    cola = []
    for ruta in sorted(PETICIONES.glob("P-*/peticion.json")):
        try:
            datos = json.loads(leer(ruta))
        except (json.JSONDecodeError, ValueError):
            continue
        if datos.get("estado") in ("capturada", "evaluando"):
            cola.append((datos.get("id", ruta.parent.name),
                         datos.get("estado"),
                         edad_en_dias(fecha_de(datos.get("creada"))) or 0))
    return cola


def unidades_en_docs():
    """Cada unidad viva de `05-trabajo/` con su frontmatter ya leído."""
    if not TRABAJO.is_dir():
        return []
    unidades = []
    for carpeta in sorted(TRABAJO.iterdir()):
        if not carpeta.is_dir() or not re.match(r"^\d{3}-", carpeta.name):
            continue
        ficha = carpeta / "especificacion.md"
        if ficha.is_file():
            unidades.append((carpeta.name, frontmatter(leer(ficha)), ficha))
    return unidades


def worktrees_reales():
    """Inventario de worktrees: los que ve git y los que hay en disco, unidos."""
    nombres = set()
    carpeta = RAIZ / "worktrees"
    if carpeta.is_dir():
        nombres |= {p.name for p in carpeta.iterdir() if p.is_dir()}
    repo = repo_codigo()
    if repo is not None:
        ok, salida = correr(["git", "-C", str(repo), "worktree", "list", "--porcelain"])
        if ok:
            for linea in salida.splitlines():
                if linea.startswith("worktree "):
                    ruta = Path(linea.split(" ", 1)[1].strip())
                    if ruta.parent.name == "worktrees":
                        nombres.add(ruta.name)
    return sorted(nombres)


def eje_pendiente(_ctx):
    hallazgos = []
    cola = peticiones_en_cola()
    edad_maxima = max([edad for _pid, _estado, edad in cola], default=0)
    veredicto = OK
    if len(cola) > 20:
        veredicto = WARN
        hallazgos.append(Hallazgo(
            "docs/05-trabajo/peticiones", f"{len(cola)} peticiones sin evaluar (tope 20) · "
            "la cola larga esconde lo urgente"))
    for pid, estado, edad in cola:
        if edad > 14:
            veredicto = WARN
            hallazgos.append(Hallazgo(
                f"docs/05-trabajo/peticiones/{pid}",
                f"{estado} desde hace {edad} días · nadie la ha triado"))
    for nombre, datos, ficha in unidades_en_docs():
        if datos.get("estado") == "en_validacion":
            edad = edad_en_dias(fecha_de(datos.get("actualizado"))) or 0
            if edad > 7:
                veredicto = WARN
                hallazgos.append(Hallazgo(
                    relativa(ficha), f"en_validacion desde hace {edad} días · "
                    "el usuario no la ha probado"))
        if datos.get("estado") in ("en_obra", "en_revision") and \
                datos.get("aprobado") in ("no", "", None):
            veredicto = WARN
            hallazgos.append(Hallazgo(
                relativa(ficha), "en obra sin aprobación del usuario (`aprobado: no`)"))
    vivas = {nombre for nombre, _d, _f in unidades_en_docs()}
    archivadas = {p.name for p in ARCHIVO.iterdir()} if ARCHIVO.is_dir() else set()
    for worktree in worktrees_reales():
        if worktree in vivas:
            continue
        veredicto = FAIL
        hallazgos.append(Hallazgo(
            f"worktrees/{worktree}",
            "la unidad ya está archivada: el worktree debió borrarse en el cierre"
            if worktree in archivadas else
            "worktree sin unidad, ni viva ni archivada · puede haber trabajo sin dueño"))
    return Resultado(
        "pendiente", veredicto, len(cola), f"en cola (máx {edad_maxima} d)",
        "stdlib:exacto", hallazgos,
        motivo="" if veredicto != FAIL else
        "worktree huérfano · SALIDA: python3 docs/00-metodo/scripts/unidad.py estado",
    )


# ------------------------------------------------------------- 2 · deuda (código)

RE_DEUDA = re.compile(r"\b(" + "|".join(MARCAS_DEUDA) + r")\b")


def eje_deuda(ctx):
    repo = ctx["repo"]
    hallazgos = []
    veredicto = OK
    # Deudas de hotfix declaradas en los papeles: si vencieron, es FAIL sin matices.
    for nombre, datos, ficha in unidades_en_docs():
        vence = datos.get("deuda_spec_vence") or datos.get("deuda_vence")
        fecha = fecha_de(vence) if vence else None
        if fecha and fecha < HOY:
            veredicto = FAIL
            hallazgos.append(Hallazgo(
                relativa(ficha), f"deuda de hotfix vencida el {fecha.isoformat()}"))
    # Solo el «Trabajo descubierto» de las unidades VIVAS, y solo esa sección: en una
    # unidad archivada ya lo cosechó el cierre, y fuera de la sección todo son viñetas.
    for nombre, _datos, ficha in unidades_en_docs():
        ruta = ficha.parent / "hallazgos.md"
        if not ruta.is_file():
            continue
        cuerpo = leer(ruta).splitlines()
        dentro = False
        for numero, linea in enumerate(cuerpo, 1):
            if linea.startswith("## "):
                dentro = linea.startswith("## Trabajo descubierto")
                continue
            crudo = linea.strip()
            if not dentro or not crudo.startswith("- ") or len(crudo) <= 4:
                continue
            if "→" in crudo or crudo.startswith("- —") or "<" in crudo:
                continue  # ya promovido/descartado, vacío, o el texto de ayuda.
            hallazgos.append(Hallazgo(
                relativa(ruta),
                f"trabajo descubierto sin petición ni descarte: {crudo[2:72]}",
                confianza="media", linea=numero))
    if repo is None:
        parcial = Resultado("deuda", peor(veredicto, NADA), len(hallazgos),
                            "deudas de papeles", "stdlib:exacto", hallazgos,
                            motivo="sin repo de código: los TODO no se pueden contar · "
                                   "SALIDA: clónalo en main/ (repos.yaml)")
        return parcial
    hay_git = bool(herramienta("git")) and (repo / ".git").exists()
    fosiles, totales = [], 0
    for ruta in recorrer(repo, "*.py"):
        for numero, linea in enumerate(leer(ruta).splitlines(), 1):
            if not RE_DEUDA.search(linea):
                continue
            totales += 1
            fosiles.append((ruta, numero, linea.strip()[:70]))
    marcados = 0
    for ruta, numero, texto in fosiles:
        edad = None
        if hay_git:
            ok, salida = correr(
                ["git", "-C", str(repo), "blame", "-L", f"{numero},{numero}",
                 "--porcelain", "--", str(ruta.relative_to(repo).as_posix())], timeout=20)
            if ok:
                marca = re.search(r"(?m)^author-time (\d+)$", salida)
                if marca:
                    edad = (HOY - datetime.date.fromtimestamp(int(marca.group(1)))).days
        if hay_git and edad is not None and edad < DIAS_TODO_FOSIL:
            continue  # R8: un TODO de este trimestre no es deuda todavía.
        marcados += 1
        hallazgos.append(Hallazgo(
            relativa(ruta), f"{texto} · sin dueño ni fecha"
            + (f" (de hace {edad} días)" if edad is not None else ""),
            confianza="alta" if hay_git else "media", linea=numero))
    if any(h.confianza == "alta" for h in hallazgos):
        veredicto = peor(veredicto, WARN)
    return Resultado(
        "deuda", veredicto, marcados, f"TODO > {DIAS_TODO_FOSIL} d (de {totales})",
        "stdlib:exacto" if hay_git else "stdlib:aproximación", hallazgos,
        motivo="" if hay_git else
        "sin git no hay fecha de cada TODO · SALIDA: instala git para datarlos",
    )


# ------------------------------------------------------------ 3 · papeles (meta)

def actas_sueltas():
    """Los `.md` que viven al lado de ESTADO.md sin ser ni ESTADO ni el libro."""
    if not TRABAJO.is_dir():
        return []
    return sorted(
        ruta for ruta in TRABAJO.glob("*.md")
        if ruta.is_file() and ruta.name not in ("ESTADO.md", "SANIDAD.md")
    )


def generados_en_docs():
    sospechosos = []
    for ruta in recorrer(DOCS):
        if ruta.name in GENERADOS or ruta.name.endswith(GENERADOS_SUFIJOS):
            sospechosos.append(ruta)
    return sospechosos


def eje_papeles(ctx):
    hallazgos, veredicto = [], OK
    actas = actas_sueltas()
    if len(actas) > ACTAS_TOLERADAS:
        veredicto = WARN
    for acta in actas:
        fecha = fecha_de_fichero(acta, RAIZ if ctx["git_meta"] else None)
        edad = edad_en_dias(fecha)
        vieja = edad is not None and edad > DIAS_ACTA_VIEJA
        if vieja:
            veredicto = WARN
        hallazgos.append(Hallazgo(
            relativa(acta),
            f"acta suelta en 05-trabajo ({edad if edad is not None else '?'} días)",
            reparable=vieja or len(actas) > ACTAS_TOLERADAS,
            destino=relativa(ARCHIVO / "actas" / acta.name)))
    md = [ruta for ruta in recorrer(DOCS, "*.md")]
    for ruta in md:
        try:
            if ruta.stat().st_size > TOPE_MD_BYTES:
                veredicto = peor(veredicto, WARN)
                hallazgos.append(Hallazgo(
                    relativa(ruta),
                    f"{ruta.stat().st_size // 1024} KB · pasa de 40 KB: parte o archiva"))
        except OSError:
            continue
    estado = TRABAJO / "ESTADO.md"
    if estado.is_file():
        lineas = len(leer(estado).splitlines())
        if lineas > TOPE_ESTADO:
            veredicto = peor(veredicto, WARN)
            hallazgos.append(Hallazgo(
                relativa(estado), f"{lineas} líneas · tope {TOPE_ESTADO}"))
    texto_docs = "\n".join(leer(ruta) for ruta in md)
    for ruta in sorted((DOCS / "conocimiento").glob("*.md")):
        if ruta.name not in texto_docs:
            veredicto = peor(veredicto, WARN)
            hallazgos.append(Hallazgo(
                relativa(ruta), "en conocimiento/ y nadie lo cita", confianza="media"))
    sintesis = DOCS / "03-investigacion" / "SINTESIS.md"
    if sintesis.is_file():
        enlazados = leer(sintesis)
        for ruta in sorted((DOCS / "03-investigacion").glob("*.md")):
            if ruta.name not in ("SINTESIS.md",) and ruta.name not in enlazados:
                veredicto = peor(veredicto, WARN)
                hallazgos.append(Hallazgo(
                    relativa(ruta), "informe sin enlace desde SINTESIS.md",
                    confianza="media"))
    for ruta in generados_en_docs():
        veredicto = peor(veredicto, WARN)
        hallazgos.append(Hallazgo(
            relativa(ruta), "fichero generado que no debería estar en docs/",
            reparable=True, destino="(borrado)"))
    return Resultado("papeles", veredicto, len(actas),
                     f"actas sueltas (de {len(md)} .md)", "stdlib:exacto", hallazgos)


# -------------------------------------------------------------- 4 · rutas (meta)

RE_RUTA = re.compile(
    r"(?<![\w./-])((?:docs|main|scripts)/[\w.@+-]+(?:/[\w.@+-]+)*\.[A-Za-z0-9]{1,6})"
)
FORMULARIO = ("NNN", "AAAA", "nnn", "<", ">", "*", "?", "slug", "MM-DD")


def md_del_meta():
    """Los `.md` del meta que sí afirman cosas. Las plantillas son formularios: no."""
    for ruta in recorrer(DOCS, "*.md"):
        if relativa(ruta).startswith("docs/00-metodo/plantillas/"):
            continue
        yield ruta


def existe_ruta(cruda):
    if (RAIZ / cruda).exists():
        return True
    if cruda.startswith("scripts/"):
        if (DOCS / "00-metodo" / cruda).exists():
            return True
        repo = repo_codigo()
        if repo is not None and (repo / cruda).exists():
            return True
    return False


def candidatos_para(cruda):
    """Dónde podría estar hoy una ruta rota: mismo nombre final, bajo `docs/`."""
    nombre = Path(cruda).name
    vistos = []
    for ruta in recorrer(DOCS):
        if ruta.name == nombre:
            vistos.append(relativa(ruta))
    return sorted(set(vistos))


def rutas_rotas():
    """(fichero, línea, ruta citada, candidatos) de cada ruta que no existe."""
    rotas = []
    for ruta in md_del_meta():
        for numero, linea in enumerate(leer(ruta).splitlines(), 1):
            for cruda in dict.fromkeys(RE_RUTA.findall(linea)):
                if any(marca in cruda for marca in FORMULARIO) or existe_ruta(cruda):
                    continue
                rotas.append((ruta, numero, cruda, candidatos_para(cruda)))
    return rotas


MUCHOS_CANDIDATOS = 3


def es_papel_de_unidad(ruta):
    """¿Es la spec o los hallazgos de una unidad? Ahí una ruta que aún no existe es una
    PROMESA de la obra en curso, no un enlace roto: baja sola a confianza media (R8)."""
    partes = relativa(ruta).split("/")
    if partes[:2] != ["docs", "05-trabajo"] or len(partes) < 4:
        return False
    return bool(re.match(r"^\d{3}-", partes[2]))


def eje_rutas(_ctx):
    hallazgos = []
    rotas = rutas_rotas()
    for ruta, numero, cruda, candidatos in rotas:
        confianza = "alta"
        if len(candidatos) == 1:
            texto = f"`{cruda}` no existe · destino único: {candidatos[0]}"
        elif len(candidatos) > MUCHOS_CANDIDATOS:
            # `007-albaranes/especificacion.md`, `P-ID/peticion.json`: el nombre final
            # existe decenas de veces, así que lo citado es un ejemplo, no una ruta.
            texto = (f"`{cruda}` no existe · {len(candidatos)} ficheros se llaman igual: "
                     "parece un ejemplo o un formulario, no una ruta")
            confianza = "media"
        elif candidatos:
            texto = f"`{cruda}` no existe · {len(candidatos)} candidatos: " \
                    + ", ".join(candidatos[:MUCHOS_CANDIDATOS])
        else:
            texto = f"`{cruda}` no existe · sin candidato: bórrala o escríbela"
        if es_papel_de_unidad(ruta):
            confianza = "media"
            texto += " · la cita una unidad en obra: puede ser una promesa"
        hallazgos.append(Hallazgo(
            relativa(ruta), texto, linea=numero, confianza=confianza,
            reparable=len(candidatos) == 1 and not intocable(ruta),
            destino=candidatos[0] if len(candidatos) == 1 else None))
    return Resultado("rutas", WARN if rotas else OK, len(rotas), "rutas rotas",
                     "stdlib:exacto", hallazgos)


# --------------------------------------------------- 5 · docs-en-codigo (código)

RE_DOC_SOSPECHOSA = re.compile(r"decisi|adr|arquitectur|design|spec", re.I)


def es_doc_de_lista_blanca(ruta, repo):
    partes = ruta.relative_to(repo).parts
    if ruta.name.lower() in LISTA_BLANCA_MD:
        return True
    if partes[0].lower() in CARPETAS_DOC_DEL_CODIGO:
        return True
    if ruta.name.lower().startswith("license"):
        return True
    # Junto a un README que lo enlace: el README es su índice, no es un papel suelto.
    vecino = ruta.parent / "README.md"
    return vecino.is_file() and ruta.name in leer(vecino)


def eje_docs_en_codigo(ctx):
    repo = ctx["repo"]
    if repo is None:
        return sin_codigo("docs-en-codigo", "papeles en el código")
    hallazgos = []
    for ruta in recorrer(repo):
        if ruta.suffix.lower() not in (".md", ".rst"):
            continue
        if es_doc_de_lista_blanca(ruta, repo):
            continue
        sospechosa = RE_DOC_SOSPECHOSA.search(ruta.stem)
        destino = "docs/decisiones/" if sospechosa else "docs/conocimiento/"
        hallazgos.append(Hallazgo(
            f"main/{ruta.relative_to(repo).as_posix()}",
            f"documentación fuera del meta-repo (ADR-001) · destino propuesto: {destino}",
            confianza="alta" if sospechosa else "media"))
    altos = [h for h in hallazgos if h.confianza == "alta"]
    return Resultado("docs-en-codigo", WARN if hallazgos else OK, len(hallazgos),
                     f"papeles fuera del meta ({len(altos)} de decisión)",
                     "stdlib:exacto", hallazgos)


# ------------------------------------------------------ 6 · codigo-muerto (código)

RE_COMENTADO = re.compile(
    r"^\s*#\s*(def |class |import |from .+ import|if .+:|for .+:|return |elif .+:)"
)


def modulos_python(repo):
    """{nombre punteado: ruta} de cada módulo del repo, sin `__init__` ni prohibidos."""
    modulos = {}
    for ruta in recorrer(repo, "*.py"):
        partes = ruta.relative_to(repo).with_suffix("").parts
        if partes[-1] == "__init__":
            continue
        modulos[".".join(partes)] = ruta
    return modulos


def importados(repo):
    """Todo lo que algún `.py` del repo importa, con y sin paquete."""
    nombres = set()
    for ruta in recorrer(repo, "*.py"):
        try:
            arbol = ast.parse(leer(ruta))
        except (SyntaxError, ValueError):
            continue
        paquete = ".".join(ruta.relative_to(repo).parts[:-1])
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                nombres |= {alias.name for alias in nodo.names}
            elif isinstance(nodo, ast.ImportFrom):
                base = nodo.module or ""
                if nodo.level:
                    arriba = paquete.split(".") if paquete else []
                    arriba = arriba[:len(arriba) - nodo.level + 1]
                    base = ".".join(arriba + ([nodo.module] if nodo.module else []))
                nombres.add(base)
                nombres |= {f"{base}.{alias.name}" for alias in nodo.names if base}
    return nombres


def texto_no_python(repo):
    """Todo lo que NO es Python: ahí es donde un `.sh` o un `.yml` mantiene vivo un módulo."""
    trozos = []
    for ruta in recorrer(repo):
        if ruta.suffix.lower() in (".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini",
                                   ".txt", ".md", ".json", ".html", ".service", ""):
            trozos.append(leer(ruta))
    return "\n".join(trozos)


def nombres_referenciados(repo):
    """Nombres usados en algún sitio: llamadas, atributos, cadenas y decoradores."""
    usados = set()
    for ruta in recorrer(repo, "*.py"):
        try:
            arbol = ast.parse(leer(ruta))
        except (SyntaxError, ValueError):
            continue
        definidos_aqui = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definidos_aqui.add(nodo.name)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Name):
                usados.add(nodo.id)
            elif isinstance(nodo, ast.Attribute):
                usados.add(nodo.attr)
            elif isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                usados.add(nodo.value.strip())
            elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorador in nodo.decorator_list:
                    for hijo in ast.walk(decorador):
                        if isinstance(hijo, ast.Name):
                            usados.add(hijo.id)
                        elif isinstance(hijo, ast.Attribute):
                            usados.add(hijo.attr)
    return usados


def definiciones_publicas(repo):
    """(ruta, línea, clase de cosa, nombre) de lo público que se define en el repo."""
    for ruta in recorrer(repo, "*.py"):
        if ruta.name.startswith("test_") or "tests" in ruta.relative_to(repo).parts:
            continue
        try:
            arbol = ast.parse(leer(ruta))
        except (SyntaxError, ValueError):
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if nodo.name.startswith("_") or nodo.name.startswith("test") \
                        or nodo.name in FUNCIONES_VIVAS or nodo.decorator_list:
                    continue  # R8: marco, prueba o decorada: no es un hallazgo.
                yield ruta, nodo.lineno, "función", nodo.name
            elif isinstance(nodo, ast.ClassDef):
                if nodo.name.startswith("_") or nodo.decorator_list:
                    continue
                yield ruta, nodo.lineno, "clase", nodo.name


def eje_codigo_muerto(ctx):
    repo = ctx["repo"]
    if repo is None:
        return sin_codigo("codigo-muerto", "candidatos muertos")
    modulos = modulos_python(repo)
    if not modulos:
        return Resultado(
            "codigo-muerto", NADA, None, "candidatos muertos", "stdlib:sin-python",
            motivo="no hay módulos Python que analizar · "
                   "SALIDA: stack sin detector, ver detectores.md")
    hallazgos = []
    ya_importados = importados(repo)
    fuera = texto_no_python(repo)
    usados = nombres_referenciados(repo)
    # R8: un módulo que un `.sh`/`.yml`/`.md` del repo nombra puede estar vivo por una vía
    # que el `ast` no ve (cron, systemd, `python3 x.py`). Ni él ni NADA de lo que define
    # sale con confianza alta: desde aquí no se puede saber quién lo llama.
    sostenidos_desde_fuera = {
        ruta for nombre, ruta in modulos.items()
        if nombre.rsplit(".", 1)[-1] in fuera
        or f"{nombre.rsplit('.', 1)[-1]}.py" in fuera
    }
    for nombre, ruta in sorted(modulos.items()):
        ultimo = nombre.rsplit(".", 1)[-1]
        if ultimo in NOMBRES_VIVOS or ultimo.startswith("test") \
                or "tests" in ruta.relative_to(repo).parts:
            continue
        if nombre in ya_importados or ultimo in ya_importados:
            continue
        citado_fuera = ruta in sostenidos_desde_fuera
        hallazgos.append(Hallazgo(
            f"main/{ruta.relative_to(repo).as_posix()}",
            f"módulo {nombre} no importado ni referenciado en Python"
            + (" · pero lo nombra un fichero no-Python del repo" if citado_fuera else ""),
            confianza="media" if citado_fuera else "alta"))
    for ruta, linea, clase, nombre in definiciones_publicas(repo):
        if nombre in usados or nombre in fuera:
            continue
        hallazgos.append(Hallazgo(
            f"main/{ruta.relative_to(repo).as_posix()}",
            f"{clase} {nombre} nunca referenciada por nombre"
            + (" · pero su módulo lo nombra un fichero no-Python del repo"
               if ruta in sostenidos_desde_fuera else ""),
            linea=linea,
            confianza="media" if ruta in sostenidos_desde_fuera else "alta"))
    for ruta in recorrer(repo, "*.py"):
        seguidas = 0
        for numero, linea in enumerate(leer(ruta).splitlines(), 1):
            seguidas = seguidas + 1 if RE_COMENTADO.match(linea) else 0
            if seguidas == 3:
                hallazgos.append(Hallazgo(
                    f"main/{ruta.relative_to(repo).as_posix()}",
                    "bloque de código comentado · git ya lo recuerda",
                    linea=numero - 2, confianza="media"))
    midio, veredicto = "stdlib:aproximación", OK
    if herramienta("vulture"):
        ok, salida = correr(["vulture", "--min-confidence", "80", str(repo)])
        if ok or salida:
            midio = "herramienta:vulture"
    altos = [h for h in hallazgos if h.confianza == "alta"]
    if altos:
        veredicto = WARN
    return Resultado("codigo-muerto", veredicto, len(altos),
                     f"candidatos alta (de {len(hallazgos)})", midio, hallazgos)


# ------------------------------------------------------------- 7 · tests (código)

def modulos_y_tests(repo):
    modulos, tests = [], set()
    for ruta in recorrer(repo, "*.py"):
        partes = ruta.relative_to(repo).parts
        if ruta.name.startswith("test_") or "tests" in partes:
            tests.add(ruta.stem)
            continue
        if ruta.stem == "__init__":
            continue
        modulos.append(ruta)
    return modulos, tests


def cobertura_medida(repo):
    """% de cobertura SOLO si `coverage` está y ya hay medida: no se corre la suite ajena."""
    if not herramienta("coverage"):
        return None
    if not any((repo / nombre).exists() for nombre in (".coverage", "coverage.json")):
        return None
    ok, salida = correr(["coverage", "json", "-o", "-"], cwd=repo, timeout=60)
    if not ok:
        return None
    try:
        return float(json.loads(salida)["totals"]["percent_covered"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def asserts_borrados(repo):
    """Tests debilitados: líneas de assert que un commit de modificación quitó."""
    if not herramienta("git") or not (repo / ".git").exists():
        return []
    ok, salida = correr(
        ["git", "-C", str(repo), "log", "--diff-filter=M", "-p", "-U0", "--", "tests/"],
        timeout=60)
    if not ok:
        return []
    borrados = []
    for linea in salida.splitlines():
        if linea.startswith("-") and not linea.startswith("---") \
                and re.search(r"\bassert\b|assertEqual|assertRaises|assertIn", linea):
            borrados.append(linea[1:].strip()[:70])
    return borrados


def bugs_sin_test_vivo(repo):
    """ADR-006: el test de un bug archivado es regresión permanente y debe seguir vivo."""
    huerfanos = []
    if not ARCHIVO.is_dir():
        return huerfanos
    fuente = "\n".join(leer(ruta) for ruta in recorrer(repo, "*.py"))
    for carpeta in sorted(ARCHIVO.iterdir()):
        ficha = carpeta / "especificacion.md"
        if not ficha.is_file() or frontmatter(leer(ficha)).get("tipo") != "bug":
            continue
        citados = set(re.findall(r"\btest_[A-Za-z0-9_]+", leer(ficha)))
        citados |= set(re.findall(r"\btest_[A-Za-z0-9_]+", leer(carpeta / "hallazgos.md")))
        for nombre in sorted(citados):
            if f"def {nombre}" not in fuente:
                huerfanos.append((relativa(ficha), nombre))
    return huerfanos


def eje_tests(ctx):
    repo = ctx["repo"]
    if repo is None:
        return sin_codigo("tests", "módulos sin test")
    modulos, tests = modulos_y_tests(repo)
    hallazgos, veredicto = [], OK
    for ficha, nombre in bugs_sin_test_vivo(repo):
        veredicto = FAIL
        hallazgos.append(Hallazgo(
            ficha, f"bug archivado cuyo test de regresión {nombre} ya no existe (ADR-006)"))
    for texto in asserts_borrados(repo)[:20]:
        veredicto = peor(veredicto, FAIL)
        hallazgos.append(Hallazgo(
            "main/tests", f"assert borrado en un commit de modificación: {texto}",
            confianza="media"))
    if not modulos:
        return Resultado(
            "tests", peor(veredicto, NADA), None, "módulos sin test", "stdlib:sin-suite",
            hallazgos,
            motivo="no hay módulos Python ni suite que medir · "
                   "SALIDA: stack sin detector (detectores.md) o repo sin código")
    sin_test = []
    for ruta in modulos:
        if f"test_{ruta.stem}" not in tests:
            sin_test.append(ruta)
            hallazgos.append(Hallazgo(
                f"main/{ruta.relative_to(repo).as_posix()}",
                f"ningún test_{ruta.stem}.py lo prueba",
                confianza="alta" if ruta.stem not in NOMBRES_VIVOS else "media"))
    porcentaje = cobertura_medida(repo)
    if porcentaje is not None:
        return Resultado(
            "tests", peor(veredicto, WARN if porcentaje < 100 else OK), porcentaje,
            "% cobertura", "herramienta:coverage", hallazgos, direccion="mas_mejor")
    if sin_test:
        veredicto = peor(veredicto, WARN)
    return Resultado(
        "tests", veredicto, len(sin_test), f"módulos sin test (de {len(modulos)})",
        "stdlib:aproximación", hallazgos,
        motivo="sin coverage instalado o sin medida previa se cuenta por fichero, "
               "no por línea · SALIDA: pip install coverage && coverage run …",
    )


# --------------------------------------------------------- 8 · docstrings (código)

def eje_docstrings(ctx):
    repo = ctx["repo"]
    if repo is None:
        return sin_codigo("docstrings", "% funciones documentadas")
    hallazgos, veredicto = [], OK
    total_mod = documentados_mod = total_fun = documentadas_fun = 0
    for ruta in recorrer(repo, "*.py"):
        partes = ruta.relative_to(repo).parts
        if ruta.name.startswith("test_") or "tests" in partes or ruta.stem == "__init__":
            continue
        try:
            arbol = ast.parse(leer(ruta))
        except (SyntaxError, ValueError):
            continue
        total_mod += 1
        if ast.get_docstring(arbol):
            documentados_mod += 1
        else:
            hallazgos.append(Hallazgo(
                f"main/{ruta.relative_to(repo).as_posix()}", "módulo sin docstring"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if nodo.name.startswith("_"):
                continue
            total_fun += 1
            if ast.get_docstring(nodo):
                documentadas_fun += 1
            else:
                hallazgos.append(Hallazgo(
                    f"main/{ruta.relative_to(repo).as_posix()}",
                    f"{nodo.name} público sin docstring", linea=nodo.lineno,
                    confianza="media"))
    agents = repo / "AGENTS.md"
    if agents.is_file():
        for numero, linea in enumerate(leer(agents).splitlines(), 1):
            for comando in re.findall(r"`([^`\n]+)`", linea):
                partes = comando.split()
                trozo = next((t for t in partes if "/" in t and "=" not in t), "")
                ejecutable = (trozo.endswith((".py", ".sh", ".js", ".ts"))
                              or trozo.startswith("scripts/"))
                if ejecutable and not (repo / trozo).exists():
                    veredicto = FAIL
                    hallazgos.append(Hallazgo(
                        "main/AGENTS.md", f"cita `{trozo}`, que no existe en el repo",
                        linea=numero))
    if not total_mod:
        return Resultado(
            "docstrings", peor(veredicto, NADA), None, "% funciones documentadas",
            "stdlib:sin-python", hallazgos,
            motivo="no hay módulos Python que analizar · SALIDA: ver detectores.md")
    midio = "stdlib:aproximación"
    if herramienta("interrogate"):
        midio = "herramienta:interrogate"
    porcentaje = round(100.0 * documentadas_fun / total_fun, 1) if total_fun else 100.0
    if documentados_mod < total_mod or porcentaje < 80:
        veredicto = peor(veredicto, WARN)
    return Resultado(
        "docstrings", veredicto, porcentaje,
        f"% públicas ({documentados_mod}/{total_mod} mód.)", midio, hallazgos,
        direccion="mas_mejor",
    )


# ------------------------------------------------------------- 9 · drift (juntas)

RE_SLUG = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+(?:\.[a-z]{2,4})?)`")


def eje_drift(ctx):
    hallazgos, veredicto = [], OK
    indice = DOCS / "02-flujos" / "INDICE.md"
    texto_flujos = "\n".join(leer(r) for r in recorrer(DOCS / "02-flujos", "*.md"))
    if indice.is_file():
        for carpeta in sorted(ARCHIVO.iterdir()) if ARCHIVO.is_dir() else []:
            ficha = carpeta / "especificacion.md"
            if not ficha.is_file():
                continue
            cuerpo = leer(ficha)
            bloque = cuerpo.split("## Deltas al mapa", 1)
            if len(bloque) < 2:
                continue
            for linea in bloque[1].split("\n##", 1)[0].splitlines():
                marca = re.match(r"^- \*\*(AÑADIDO|MODIFICADO)", linea.strip())
                if not marca or "—" in linea:
                    continue
                for slug in RE_SLUG.findall(linea):
                    if slug in texto_flujos:
                        continue
                    veredicto = FAIL
                    hallazgos.append(Hallazgo(
                        relativa(ficha),
                        f"delta {marca.group(1)} declara `{slug}` y el mapa no lo refleja"))
    for planos in sorted((DOCS / "02-flujos" / "planos").rglob("planos.json")) \
            if (DOCS / "02-flujos" / "planos").is_dir() else []:
        try:
            datos = json.loads(leer(planos))
        except (json.JSONDecodeError, ValueError):
            continue
        cobertura = datos.get("cobertura") or {}
        candidatas = list(cobertura.get("evidencias") or []) + list(datos.get("pruebas") or [])
        for cruda in candidatas:
            ruta = str(cruda if isinstance(cruda, str) else (cruda or {}).get("ruta", ""))
            if ruta and not any(marca in ruta for marca in FORMULARIO) \
                    and not (RAIZ / ruta).exists():
                veredicto = peor(veredicto, WARN)
                hallazgos.append(Hallazgo(
                    relativa(planos), f"cobertura apunta a `{ruta}`, que no existe"))
    detectores = DOCS / "00-metodo" / "detectores.md"
    if detectores.is_file():
        cuerpo = leer(detectores)
        for citado in dict.fromkeys(re.findall(r"`([\w./-]+\.py)`", cuerpo)):
            nombre = Path(citado).name
            if not any((DOCS / "00-metodo" / "scripts" / nombre).exists()
                       for _ in (0,)) and not (RAIZ / citado).exists():
                veredicto = peor(veredicto, WARN)
                hallazgos.append(Hallazgo(
                    relativa(detectores), f"cita `{citado}`, que ya no existe"))
        for guardian in sorted((DOCS / "00-metodo" / "scripts").glob("lint_*.py")):
            if guardian.name not in cuerpo:
                veredicto = peor(veredicto, WARN)
                hallazgos.append(Hallazgo(
                    relativa(detectores),
                    f"`{guardian.name}` es un detector sin fila en la tabla"))
    repo = ctx["repo"]
    if repo is not None:
        cambios = repo / "CHANGELOG.md"
        for version in (repo / "VERSION", DOCS / "00-metodo" / "VERSION",
                        repo / "plantilla/docs/00-metodo/VERSION"):
            if not (version.is_file() and cambios.is_file()):
                continue
            numero = leer(version).strip()
            primeras = "\n".join(leer(cambios).splitlines()[:40])
            if numero and numero not in primeras:
                veredicto = peor(veredicto, WARN)
                hallazgos.append(Hallazgo(
                    relativa(cambios),
                    f"VERSION dice {numero} y el CHANGELOG no la menciona arriba"))
            break
    return Resultado("drift", veredicto, len(hallazgos), "inconsistencias",
                     "stdlib:exacto", hallazgos)


# --------------------------------------------------- 10 · decisiones (tecnología)

# Windows-only y otros que no están en la stdlib de ESTA máquina pero sí en la del
# proyecto de al lado: si no se nombran, `winreg` parecería una dependencia sin decisión.
STDLIB_DE_OTRA_PLATAFORMA = frozenset("""
msvcrt winreg winsound nt _winapi fcntl grp pwd posix termios tty crypt syslog spwd nis
ossaudiodev readline resource curses
""".split())


def _stdlib_de_esta_maquina():
    """Qué trae de serie este intérprete. `sys.stdlib_module_names` no existe en 3.9."""
    nombres = set(sys.builtin_module_names) | STDLIB_DE_OTRA_PLATAFORMA
    declarados = getattr(sys, "stdlib_module_names", None)
    if declarados:
        return nombres | set(declarados)
    import sysconfig
    try:
        carpeta = Path(sysconfig.get_paths()["stdlib"])
        for hijo in carpeta.iterdir():
            if hijo.suffix == ".py":
                nombres.add(hijo.stem)
            elif hijo.is_dir() and (hijo / "__init__.py").is_file():
                nombres.add(hijo.name)
        for binario in (carpeta / "lib-dynload").glob("*"):
            nombres.add(binario.name.split(".")[0])
    except OSError:
        pass
    return nombres


STDLIB = _stdlib_de_esta_maquina() | frozenset("""
abc argparse ast asyncio base64 binascii bisect builtins bz2 calendar cgi cmath cmd
codecs collections colorsys concurrent configparser contextlib copy csv ctypes curses
dataclasses datetime decimal difflib dis email encodings enum errno faulthandler filecmp
fileinput fnmatch fractions ftplib functools gc getopt getpass gettext glob gzip hashlib
heapq hmac html http imaplib importlib inspect io ipaddress itertools json keyword linecache
locale logging lzma mailbox math mimetypes mmap multiprocessing netrc numbers operator os
pathlib pdb pickle pkgutil platform plistlib poplib posixpath pprint profile pty queue
quopri random re readline reprlib resource runpy sched secrets select selectors shelve
shlex shutil signal site smtplib socket socketserver sqlite3 ssl stat statistics string
stringprep struct subprocess symtable sys sysconfig tarfile tempfile termios textwrap
threading time timeit token tokenize traceback tracemalloc tty types typing unicodedata
unittest urllib uuid venv warnings wave weakref webbrowser xml xmlrpc zipfile zlib
""".split())
RE_REQUISITO = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)$")


def manifiestos(repo):
    """Cada fichero de dependencias del repo, con su ecosistema."""
    encontrados = []
    for ruta in recorrer(repo):
        nombre = ruta.name.lower()
        if nombre.startswith("requirements") and nombre.endswith(".txt"):
            encontrados.append((ruta, "pip"))
        elif nombre in ("pyproject.toml", "setup.cfg"):
            encontrados.append((ruta, "pip"))
        elif nombre == "package.json":
            encontrados.append((ruta, "npm"))
    return encontrados


def paquetes_de(ruta, ecosistema):
    """[(nombre, fijado)] de un manifiesto, sin parsear TOML (3.9 no trae tomllib)."""
    paquetes = []
    cuerpo = leer(ruta)
    if ecosistema == "npm":
        try:
            datos = json.loads(cuerpo)
        except (json.JSONDecodeError, ValueError):
            return paquetes
        for clave in ("dependencies", "devDependencies"):
            for nombre, version in (datos.get(clave) or {}).items():
                paquetes.append((nombre, bool(re.match(r"^\d", str(version)))))
        return paquetes
    if ruta.name.lower() in ("pyproject.toml", "setup.cfg"):
        for linea in cuerpo.splitlines():
            encontrado = re.match(r'^\s*["\']([A-Za-z0-9][A-Za-z0-9._-]*)\s*([^"\']*)["\']',
                                  linea.strip())
            if encontrado:
                paquetes.append((encontrado.group(1), "==" in encontrado.group(2)))
        return paquetes
    for linea in cuerpo.splitlines():
        crudo = linea.split("#", 1)[0].strip()
        if not crudo or crudo.startswith("-"):
            continue
        encontrado = RE_REQUISITO.match(crudo)
        if encontrado:
            paquetes.append((encontrado.group(1), "==" in crudo or "@sha" in crudo))
    return paquetes


def nombres_locales(repo):
    """Todo lo que `import X` puede resolver DENTRO del repo: un módulo hermano no es una
    tecnología de terceros. Se mira el nombre punteado y también el nombre del fichero,
    porque los scripts se importan por su stem con el `sys.path` puesto a su carpeta."""
    locales = set()
    for nombre in modulos_python(repo):
        locales.add(nombre.split(".")[0])
        locales.add(nombre.rsplit(".", 1)[-1])
    for ruta in recorrer(repo, "*.py"):
        locales.add(ruta.stem)
        if (ruta.parent / "__init__.py").is_file():
            locales.add(ruta.parent.name)
    if repo.is_dir():
        locales |= {p.name for p in repo.iterdir() if p.is_dir()}
    return locales


def tecnologias_del_codigo(repo):
    """{tecnología: (dónde, línea, es de desarrollo)} de lo que este repo usa de verdad."""
    tecnologias = {}
    for ruta, ecosistema in manifiestos(repo):
        de_desarrollo = bool(re.search(r"dev|test", ruta.name, re.I))
        for nombre, _fijado in paquetes_de(ruta, ecosistema):
            tecnologias.setdefault(nombre.lower(), (relativa(ruta), 0, de_desarrollo))
    locales = nombres_locales(repo)
    for ruta in recorrer(repo, "*.py"):
        es_test = ruta.name.startswith("test_") or "tests" in ruta.relative_to(repo).parts
        for numero, linea in enumerate(leer(ruta).splitlines(), 1):
            encontrado = re.match(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", linea)
            if not encontrado:
                continue
            cabeza = encontrado.group(1).split(".")[0]
            if not cabeza or cabeza in STDLIB or cabeza in locales \
                    or cabeza.startswith("_"):
                continue
            tecnologias.setdefault(
                cabeza.lower(),
                (f"main/{ruta.relative_to(repo).as_posix()}", numero, es_test))
    for ruta in recorrer(repo):
        if ruta.name.lower().startswith("dockerfile"):
            for imagen in re.findall(r"(?mi)^FROM\s+([\w./-]+)", leer(ruta)):
                tecnologias.setdefault(imagen.split(":")[0].lower(),
                                       (relativa(ruta), 0, False))
        elif ruta.name.lower() in ("docker-compose.yml", "compose.yml"):
            for imagen in re.findall(r"(?m)^\s*image:\s*([\w./-]+)", leer(ruta)):
                tecnologias.setdefault(imagen.split(":")[0].lower(),
                                       (relativa(ruta), 0, False))
    return tecnologias


def eje_decisiones(ctx):
    repo = ctx["repo"]
    if repo is None:
        return sin_codigo("decisiones", "tecnologías sin decisión")
    registrado = leer(DOCS / "01-constitucion" / "bias.md").lower()
    for ruta in recorrer(DOCS / "decisiones", "*.md"):
        registrado += "\n" + leer(ruta).lower()
    for ruta in recorrer(DOCS / "conocimiento", "*.md"):
        registrado += "\n" + leer(ruta).lower()
    hallazgos = []
    for nombre, (donde, linea, de_desarrollo) in sorted(
            tecnologias_del_codigo(repo).items()):
        if nombre in registrado:
            continue
        hallazgos.append(Hallazgo(
            donde, f"`{nombre}` se usa y no lo menciona ni bias.md ni docs/decisiones/ · "
                   "abre un DP o amplía el bias", linea=linea,
            confianza="media" if de_desarrollo else "alta"))
    return Resultado("decisiones", WARN if hallazgos else OK, len(hallazgos),
                     "sin decisión escrita", "stdlib:exacto", hallazgos)


# ------------------------------------------------------- 11 · dependencias (código)

def eje_dependencias(ctx):
    repo = ctx["repo"]
    if repo is None:
        return sin_codigo("dependencias", "sueltas")
    fuentes = manifiestos(repo)
    if not fuentes:
        return Resultado(
            "dependencias", NADA, None, "sueltas", "stdlib:sin-manifiesto",
            motivo="este repo no declara dependencias en ningún manifiesto conocido · "
                   "SALIDA: crea requirements.txt / pyproject.toml / package.json")
    hallazgos, sueltas, veredicto = [], 0, OK
    for ruta, ecosistema in fuentes:
        de_desarrollo = bool(re.search(r"dev|test", ruta.name, re.I))
        for nombre, fijado in paquetes_de(ruta, ecosistema):
            if fijado:
                continue
            sueltas += 1
            hallazgos.append(Hallazgo(
                relativa(ruta), f"`{nombre}` sin fijar ({ecosistema}) · una build de hoy "
                                "y otra de mañana no traen lo mismo",
                confianza="media" if de_desarrollo else "alta"))
    if sueltas:
        veredicto = WARN
    for candado in ("poetry.lock", "package-lock.json", "requirements.lock", "uv.lock"):
        ruta = repo / candado
        if not ruta.is_file():
            continue
        edad = edad_en_dias(fecha_de_fichero(ruta, repo))
        if edad is not None and edad > 180:
            veredicto = peor(veredicto, WARN)
            hallazgos.append(Hallazgo(
                relativa(ruta), f"lockfile de hace {edad} días · nadie lo revisa",
                confianza="media"))
    if not ctx["red"]:
        return Resultado(
            "dependencias", peor(veredicto, NADA), sueltas, "sueltas", "stdlib:exacto",
            hallazgos,
            motivo="vulnerabilidades y versiones nuevas NO se han comprobado (sin `--red`) "
                   "· SALIDA: repite con --red",
        )
    midio, comprobado = "stdlib:exacto", False
    for ruta, ecosistema in fuentes:
        if ecosistema == "pip" and herramienta("pip-audit") and ruta.suffix == ".txt":
            ok, salida = correr(["pip-audit", "-r", str(ruta), "-f", "json"], timeout=120)
            if ok or salida.strip().startswith("{"):
                comprobado, midio = True, "herramienta:pip-audit"
                for hueco in re.findall(r'"id":\s*"([\w-]+)"', salida):
                    veredicto = FAIL
                    hallazgos.append(Hallazgo(relativa(ruta), f"vulnerable: {hueco}"))
        elif ecosistema == "npm" and herramienta("npm"):
            ok, salida = correr(["npm", "audit", "--json"], cwd=ruta.parent, timeout=120)
            if salida.strip().startswith("{"):
                comprobado, midio = True, "herramienta:npm-audit"
                try:
                    total = json.loads(salida).get("metadata", {}) \
                        .get("vulnerabilities", {}).get("total", 0)
                except (json.JSONDecodeError, ValueError, AttributeError):
                    total = 0
                if total:
                    veredicto = FAIL
                    hallazgos.append(Hallazgo(
                        relativa(ruta), f"{total} vulnerabilidades según npm audit"))
    if not comprobado:
        return Resultado(
            "dependencias", peor(veredicto, NADA), sueltas, "sueltas",
            "stdlib:aproximación", hallazgos,
            motivo="con --red pero sin auditor instalado o sin red utilizable · "
                   "SALIDA: pip install pip-audit (o instala npm) y repite",
        )
    return Resultado("dependencias", veredicto, sueltas, "sueltas", midio, hallazgos)


EJES = (
    ("pendiente", eje_pendiente),
    ("deuda", eje_deuda),
    ("papeles", eje_papeles),
    ("rutas", eje_rutas),
    ("docs-en-codigo", eje_docs_en_codigo),
    ("codigo-muerto", eje_codigo_muerto),
    ("tests", eje_tests),
    ("docstrings", eje_docstrings),
    ("drift", eje_drift),
    ("decisiones", eje_decisiones),
    ("dependencias", eje_dependencias),
)
NOMBRES_EJES = tuple(nombre for nombre, _f in EJES)
EJES_DEL_CODIGO = ("deuda", "docs-en-codigo", "codigo-muerto", "tests", "docstrings",
                   "drift", "decisiones", "dependencias")


# ------------------------------------------------------------------ el libro

CABECERA_LIBRO = (
    "| fecha | " + " | ".join(NOMBRES_EJES) + " | midió con | reparaciones | peticiones |"
)
SEPARADOR_LIBRO = "|" + "---|" * (len(NOMBRES_EJES) + 4)


def celdas(linea):
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def es_fila_de_pasada(linea):
    return linea.startswith("|") and bool(
        re.match(r"^\d{4}-\d{2}-\d{2}$", celdas(linea)[0] if celdas(linea) else "")
    )


def cuerpo_del_libro():
    if not LIBRO.is_file():
        return [], []
    lineas = leer(LIBRO).splitlines()
    cabecera = [l for l in lineas if not es_fila_de_pasada(l)
                and not re.match(r"^\|\s*\d{4}-\d{2} ·", l)]
    filas = [l for l in lineas if es_fila_de_pasada(l)
             or re.match(r"^\|\s*\d{4}-\d{2} ·", l)]
    return cabecera, filas


def plantilla_del_libro():
    if PLANTILLA_LIBRO.is_file():
        return leer(PLANTILLA_LIBRO).rstrip("\n").splitlines()
    return ["# Libro de sanidad", "",
            "> Una fila por pasada. Lo escribe `sanidad.py medir --anotar`.", "",
            CABECERA_LIBRO, SEPARADOR_LIBRO]


def ultima_pasada():
    """(fecha, {eje: valor}, {eje: cómo se midió}) de la última fila escrita, o Nones."""
    _cabecera, filas = cuerpo_del_libro()
    for linea in reversed(filas):
        if not es_fila_de_pasada(linea):
            continue
        partes = celdas(linea)
        valores, formas = {}, {}
        for indice, eje in enumerate(NOMBRES_EJES, start=1):
            if indice >= len(partes):
                break
            try:
                valores[eje] = float(partes[indice])
            except ValueError:
                valores[eje] = None
        columna = partes[len(NOMBRES_EJES) + 1] if len(partes) > len(NOMBRES_EJES) + 1 else ""
        for par in columna.split():
            if "=" in par:
                clave, valor = par.split("=", 1)
                formas[clave] = valor
        return fecha_de(partes[0]), valores, formas
    return None, {}, {}


def comparar(resultados):
    """G-2403: la comparación se hace contra el libro, jamás contra un número recordado."""
    _fecha, valores, formas = ultima_pasada()
    if not valores:
        return
    for resultado in resultados:
        antes = valores.get(resultado.eje)
        ahora = resultado.valor
        if antes is None or ahora is None:
            resultado.comparacion = "sin fila anterior"
            continue
        forma_antes = formas.get(resultado.eje, "exacto")
        forma_ahora = resultado.midio_con.split(":", 1)[-1]
        if forma_antes != forma_ahora:
            resultado.comparacion = "sin comparar (midió otro)"
            continue
        if float(antes) == float(ahora):
            resultado.comparacion = "igual"
            continue
        mejora = (ahora > antes) if resultado.direccion == "mas_mejor" else (ahora < antes)
        etiqueta = "mejor" if mejora else "EMPEORÓ"
        resultado.comparacion = f"{etiqueta} {_corto(antes)}→{_corto(ahora)}"


def _corto(numero):
    return str(int(numero)) if float(numero).is_integer() else f"{float(numero):.1f}"


def compactar(cabecera, filas):
    """El libro nunca pasa de 100 líneas: lo viejo se resume en una línea por mes."""
    while len(cabecera) + len(filas) > TOPE_LIBRO:
        pasadas = [l for l in filas if es_fila_de_pasada(l)]
        if not pasadas:
            filas = filas[1:]
            continue
        mes = celdas(pasadas[0])[0][:7]
        grupo = [l for l in pasadas if celdas(l)[0].startswith(mes)]
        if len(grupo) < 2:
            filas = [l for l in filas if l != grupo[0]] if grupo else filas[1:]
            continue
        medias = []
        for indice in range(1, len(NOMBRES_EJES) + 1):
            numeros = []
            for linea in grupo:
                try:
                    numeros.append(float(celdas(linea)[indice]))
                except (ValueError, IndexError):
                    continue
            medias.append(_corto(sum(numeros) / len(numeros)) if numeros else "—")
        resumen = (f"| {mes} · {len(grupo)} pasadas | " + " | ".join(medias)
                   + " | (compactado) | — | — |")
        primera = filas.index(grupo[0])
        filas = [l for l in filas if l not in grupo]
        filas.insert(primera, resumen)
    return filas


def anotar(resultados, reparaciones, peticiones):
    cabecera, filas = cuerpo_del_libro()
    if not cabecera:
        cabecera = plantilla_del_libro()
    numeros = []
    formas = []
    for eje in NOMBRES_EJES:
        elegido = next((r for r in resultados if r.eje == eje), None)
        numeros.append(elegido.numero() if elegido else "—")
        if elegido:
            corto = elegido.midio_con.split(":", 1)[-1]
            if corto != "exacto":
                formas.append(f"{eje}={corto}")
    fila = (f"| {HOY.isoformat()} | " + " | ".join(numeros) + " | "
            + (" ".join(formas) or "todo exacto") + " | "
            + (str(reparaciones) if reparaciones else "—") + " | "
            + (" ".join(peticiones) if peticiones else "—") + " |")
    filas = [l for l in filas if not (es_fila_de_pasada(l)
                                      and celdas(l)[0] == HOY.isoformat())]
    filas.append(fila)
    filas = compactar(cabecera, filas)
    LIBRO.parent.mkdir(parents=True, exist_ok=True)
    LIBRO.write_text("\n".join(cabecera + filas) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ la salida

ANCHOS = (15, 14, 18, 23, 26)
TITULOS = ("EJE", "VEREDICTO", "NÚMERO", "MIDIÓ CON", "VS ANTERIOR")


def celda(texto, ancho):
    texto = str(texto)
    return (texto if len(texto) <= ancho else texto[:ancho - 1] + "…").ljust(ancho)


def fila_de_pantalla(valores):
    return " ".join(celda(v, a) for v, a in zip(valores, ANCHOS)).rstrip()


def render(resultados, detalle=False, carpeta=None):
    lineas = [f"== Sanidad del workspace · {HOY.isoformat()} ==", ""]
    lineas.append(fila_de_pantalla(TITULOS))
    lineas.append(fila_de_pantalla(tuple("-" * a for a in ANCHOS)))
    for resultado in resultados:
        lineas.append(fila_de_pantalla((
            resultado.eje, resultado.veredicto,
            f"{resultado.numero()} {resultado.unidad}".strip(),
            resultado.midio_con, resultado.comparacion)))
    lineas.append("")
    if carpeta is not None:
        lineas.append(f"detalle: {relativa(carpeta)}/ (una línea por hallazgo, por eje)")
    cuenta = {v: sum(1 for r in resultados if r.veredicto == v) for v in PESO}
    lineas.append(" · ".join(f"{cuenta[v]} {v}" for v in (FAIL, WARN, NADA, OK)))
    if detalle:
        for resultado in resultados:
            if not resultado.hallazgos and not resultado.motivo:
                continue
            lineas.append("")
            lineas.append(f"-- {resultado.eje} --")
            if resultado.motivo:
                lineas.append(f"   {resultado.motivo}")
            for hallazgo in resultado.hallazgos:
                lineas.append(f"   {hallazgo.linea_de_detalle()}")
    else:
        for resultado in resultados:
            if resultado.veredicto == NADA and resultado.motivo:
                lineas.append(f"  {resultado.eje}: {resultado.motivo}")
    return "\n".join(l[:100].rstrip() for l in lineas)


def escribir_detalle(resultados):
    """R2: la salida corta manda; los listados largos van a `.runtime/` y se referencian."""
    carpeta = RUNTIME / HOY.isoformat()
    carpeta.mkdir(parents=True, exist_ok=True)
    for resultado in resultados:
        if not resultado.hallazgos:
            continue
        destino = carpeta / f"{resultado.eje}.txt"
        cuerpo = [f"# {resultado.eje} · {HOY.isoformat()} · {resultado.veredicto} · "
                  f"midió con {resultado.midio_con}"]
        if resultado.motivo:
            cuerpo.append(f"# {resultado.motivo}")
        cuerpo += [h.linea_de_detalle() for h in resultado.hallazgos]
        destino.write_text(
            control_plane.redact_secrets("\n".join(cuerpo)) + "\n", encoding="utf-8")
        resultado.detalle_ruta = relativa(destino)
    return carpeta


def redactar_estructura(valor):
    """R10: nada que vaya a `.runtime/` sale sin pasar por el redactor.

    Se redacta el DATO, no el JSON ya serializado: así el fichero sigue siendo JSON
    válido pase lo que pase con las comillas de un secreto (`escribir_detalle` puede
    redactar el texto plano; aquí no)."""
    if isinstance(valor, dict):
        return {control_plane.redact_secrets(k) if isinstance(k, str) else k:
                redactar_estructura(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [redactar_estructura(v) for v in valor]
    if isinstance(valor, str):
        return control_plane.redact_secrets(valor)
    return valor


def como_json(resultados):
    repo = repo_codigo()
    sha = ""
    if repo is not None:
        ok, salida = correr(["git", "-C", str(repo), "rev-parse", "HEAD"], timeout=20)
        sha = salida.strip() if ok else ""
    return {
        "esquema": "sanidad/v1",
        "fecha": HOY.isoformat(),
        "raiz": str(RAIZ),
        "sha_main": sha,
        "ejes": [r.como_json() for r in resultados],
        "comparacion": {r.eje: r.comparacion for r in resultados},
    }


# ------------------------------------------------------------------ subórdenes

def medir(nombres, red=False):
    contexto = {
        "repo": repo_codigo(),
        "red": bool(red),
        "git_meta": bool(herramienta("git")) and (RAIZ / ".git").exists(),
    }
    resultados = []
    for nombre, funcion in EJES:
        if nombres and nombre not in nombres:
            continue
        try:
            resultados.append(funcion(contexto))
        except Exception as exc:  # el guardián informa, jamás muere (ADR-026)
            resultados.append(Resultado(
                nombre, NADA, None, "—", "stdlib:falló",
                motivo=f"el eje falló al medir ({type(exc).__name__}) · "
                       f"SALIDA: abre un bug con esta línea"))
    return resultados


def cmd_medir(args):
    resultados = medir(args.eje, red=args.red)
    comparar(resultados)
    carpeta = escribir_detalle(resultados)
    informe = redactar_estructura(como_json(resultados))
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "ultima.json").write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.anotar:
        anotar(resultados, 0, [])
    if args.json:
        print(json.dumps(informe, ensure_ascii=False, indent=2))
    else:
        print(render(resultados, detalle=args.detalle, carpeta=carpeta))
    if args.estricto and any(r.veredicto == FAIL or r.comparacion.startswith("EMPEORÓ")
                             for r in resultados):
        return 1
    return 0


def reparaciones_pendientes(solo=None):
    """La lista CERRADA de R4, ya resuelta a acciones concretas. Nada más entra aquí."""
    acciones = []
    if solo in (None, "papeles"):
        actas = actas_sueltas()
        for acta in actas:
            edad = edad_en_dias(fecha_de_fichero(
                acta, RAIZ if (RAIZ / ".git").exists() else None))
            if not (len(actas) > ACTAS_TOLERADAS or (edad is not None
                                                     and edad > DIAS_ACTA_VIEJA)):
                continue
            acciones.append(("papeles", "mover", acta, ARCHIVO / "actas" / acta.name))
    if solo in (None, "rutas"):
        for ruta, _numero, cruda, candidatos in rutas_rotas():
            if len(candidatos) == 1 and not intocable(ruta):
                acciones.append(("rutas", "reescribir", ruta, (cruda, candidatos[0])))
    if solo in (None, "papeles"):
        for ruta in generados_en_docs():
            acciones.append(("papeles", "borrar", ruta, None))
    return acciones


def reescribir_referencias(vieja, nueva):
    """Cambia una ruta por otra en los `.md` del meta que sí pueden tocarse."""
    tocados = 0
    for ruta in md_del_meta():
        if intocable(ruta):
            continue
        texto = leer(ruta)
        if vieja not in texto:
            continue
        ruta.write_text(texto.replace(vieja, nueva), encoding="utf-8")
        tocados += 1
    return tocados


def cmd_reparar(args):
    acciones = reparaciones_pendientes(args.solo)
    if not acciones:
        print("nada que reparar: los papeles del meta-repo están en su sitio")
        return 0
    marca = "SIMULADO" if args.simular else "REPARADO"
    hechas = 0
    for eje, clase, origen, destino in acciones:
        if clase == "mover":
            print(f"{marca} {eje} · {relativa(origen)} → {relativa(destino)}")
            if not args.simular:
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(origen), str(destino))
                reescribir_referencias(relativa(origen), relativa(destino))
        elif clase == "reescribir":
            vieja, nueva = destino
            print(f"{marca} {eje} · {relativa(origen)}: `{vieja}` → `{nueva}`")
            if not args.simular:
                texto = leer(origen)
                origen.write_text(texto.replace(vieja, nueva), encoding="utf-8")
        else:
            print(f"{marca} {eje} · {relativa(origen)} → (borrado: generado)")
            if not args.simular:
                origen.unlink()
        hechas += 1
    print(f"\n{hechas} {'simuladas' if args.simular else 'aplicadas'} · el commit lo hace "
          "el padre con rutas explícitas (`sanidad: …`), este script no ejecuta git")
    return 0


MARCA_PETICION = "sanidad/{}"


def peticion_viva_de(eje):
    marca = MARCA_PETICION.format(eje)
    for ruta in sorted(PETICIONES.glob("P-*/peticion.json")):
        try:
            datos = json.loads(leer(ruta))
        except (json.JSONDecodeError, ValueError):
            continue
        if datos.get("estado") in ("cerrada", "cancelada"):
            continue
        textos = [datos.get("original", {}).get("texto", "")]
        textos += [a.get("texto", "") for a in datos.get("aclaraciones", [])]
        if any(marca in t for t in textos):
            return datos.get("id"), "\n".join(textos)
    return None, ""


def texto_de_peticion(resultado, hallazgos):
    lineas = [
        MARCA_PETICION.format(resultado.eje),
        "",
        f"Sanidad {HOY.isoformat()} · eje `{resultado.eje}`: {len(hallazgos)} hallazgos.",
        f"Medido con {resultado.midio_con}. Detalle completo: "
        f"{resultado.detalle_ruta or '.runtime/sanidad/'}",
        "",
    ]
    for hallazgo in hallazgos:
        lineas.append(f"- {hallazgo.sitio()} · {hallazgo.texto} · "
                      f"confianza {hallazgo.confianza}")
    lineas += [
        "",
        "La sanidad no toca código (ADR-031): esto se decide en el visor de contratos y, "
        "si se acepta, se construye como unidad por el cauce normal.",
    ]
    return control_plane.redact_secrets("\n".join(lineas))


def cmd_capturar(args):
    nombres = args.eje or list(EJES_DEL_CODIGO)
    desconocidos = [n for n in nombres if n not in EJES_DEL_CODIGO]
    if desconocidos:
        print(f"FAIL {', '.join(desconocidos)} no es un eje del código · "
              f"Arréglalo: python3 docs/00-metodo/scripts/sanidad.py capturar --eje <uno de: "
              f"{', '.join(EJES_DEL_CODIGO)}>")
        return 1
    resultados = medir(nombres, red=args.red)
    escribir_detalle(resultados)
    creadas = 0
    for resultado in resultados:
        confianzas = ("alta", "media") if args.incluir_media else ("alta",)
        hallazgos = [h for h in resultado.hallazgos if h.confianza in confianzas]
        if not hallazgos:
            continue
        pid, ya_escrito = peticion_viva_de(resultado.eje)
        if pid is None:
            resumen = (f"Sanidad {HOY.isoformat()} · {resultado.eje}: "
                       f"{len(hallazgos)} hallazgos")
            orden = ["capturar", "--resumen", resumen,
                     "--texto", texto_de_peticion(resultado, hallazgos),
                     "--autor", "sanidad"]
        else:
            nuevos = [h for h in hallazgos if h.sitio() not in ya_escrito]
            if not nuevos:
                print(f"  ya capturado {resultado.eje} · {pid} (sin hallazgos nuevos)")
                continue
            orden = ["aclarar", pid, "--texto", texto_de_peticion(resultado, nuevos),
                     "--autor", "sanidad"]
        proceso = subprocess.run(
            [sys.executable, str(PETICION_PY), *orden], cwd=str(RAIZ),
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        salida = (proceso.stdout or "").strip() or (proceso.stderr or "").strip()
        if proceso.returncode != 0:
            print(f"FAIL {resultado.eje}: {salida}\n"
                  f"  Arréglalo: corrige lo que dice arriba y vuelve a ejecutar "
                  f"python3 docs/00-metodo/scripts/sanidad.py capturar --eje {resultado.eje}")
            return 1
        print(f"  {resultado.eje} · {salida}")
        creadas += 1
    if not creadas:
        print("sin hallazgos de confianza alta: nada que llevarle al usuario")
    return 0


def cierres_desde(fecha):
    """Unidades archivadas y bugs mergeados con fecha posterior a la última pasada."""
    cierres = 0
    if ARCHIVO.is_dir():
        for carpeta in sorted(ARCHIVO.iterdir()):
            ficha = carpeta / "especificacion.md"
            if not ficha.is_file():
                continue
            cuando = fecha_de(frontmatter(leer(ficha)).get("actualizado", ""))
            if cuando and cuando > fecha:
                cierres += 1
    for ruta in recorrer(DOCS / "bugs", "*.md"):
        datos = frontmatter(leer(ruta))
        cuando = fecha_de(datos.get("actualizado", ""))
        if datos.get("estado") == "mergeada" and cuando and cuando > fecha:
            cierres += 1
    return cierres


def cmd_atraso(args):
    fecha, _valores, _formas = ultima_pasada()
    if fecha is None:
        print(f"WARN nunca se ha pasado sanidad · SALIDA: {SALIDA_MEDIR}")
        return 1 if args.estricto else 0
    cierres = cierres_desde(fecha)
    dias = (HOY - fecha).days
    if cierres > ATRASO_CIERRES or dias > ATRASO_DIAS:
        print(f"WARN sanidad atrasada: {cierres} cierres / {dias} días desde "
              f"{fecha.isoformat()} · SALIDA: {SALIDA_MEDIR}")
        return 1 if args.estricto else 0
    print(f"OK sanidad al día ({cierres} cierres, {dias} días)")
    return 0


def cmd_ejes(_args):
    for nombre in NOMBRES_EJES:
        print(nombre)
    return 0


def parser_cli():
    parser = argparse.ArgumentParser(
        description="Mide la salud del workspace en once ejes, repara papeles y "
                    "convierte lo del código en peticiones.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("medir", help="los once ejes con veredicto, número y con qué midió")
    p.add_argument("--eje", action="append", choices=NOMBRES_EJES,
                   help="mide solo este eje; repetible")
    p.add_argument("--anotar", action="store_true", help="añade la fila al libro")
    p.add_argument("--json", action="store_true", help="vuelca el informe `sanidad/v1`")
    p.add_argument("--detalle", action="store_true", help="imprime también los hallazgos")
    p.add_argument("--estricto", action="store_true", help="exit 1 si hay FAIL o EMPEORÓ")
    p.add_argument("--red", action="store_true", help="permite salir a la red")
    p.set_defaults(func=cmd_medir)

    p = sub.add_parser("reparar", help="la lista cerrada de papeles del meta-repo")
    p.add_argument("--simular", action="store_true", help="lista sin escribir nada")
    p.add_argument("--solo", choices=("papeles", "rutas"), help="acota a un eje")
    p.set_defaults(func=cmd_reparar)

    p = sub.add_parser("capturar", help="lo del código, como petición con evidencia")
    p.add_argument("--eje", action="append", choices=EJES_DEL_CODIGO)
    p.add_argument("--incluir-media", action="store_true", dest="incluir_media")
    p.add_argument("--red", action="store_true")
    p.set_defaults(func=cmd_capturar)

    p = sub.add_parser("atraso", help="cuántos cierres y días desde la última pasada")
    p.add_argument("--estricto", action="store_true")
    p.set_defaults(func=cmd_atraso)

    p = sub.add_parser("ejes", help="los once nombres, en orden")
    p.set_defaults(func=cmd_ejes)
    return parser


def main():
    args = parser_cli().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
