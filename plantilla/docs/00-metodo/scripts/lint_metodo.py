#!/usr/bin/env python3
"""Linter del método: valida que la estructura y el vocabulario cerrado no degeneren.

Uso: python3 docs/00-metodo/scripts/lint_metodo.py   (desde la raíz del meta-repo)
Salida: OK/WARN/FAIL por comprobación. Exit 0 si no hay FAIL; exit 1 si hay alguno.
Se ejecuta: al arrancar sesión del padre, en cada cierre, y en CI del meta-repo.
Sin dependencias: solo stdlib. El disco es la verdad; este script solo la comprueba.
"""
import datetime
import hashlib
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path

import repo_config

# Windows: en cuanto la salida va a un PIPE —setup.py, la CI, cualquier harness de agente— el
# encoding deja de ser el de la consola y pasa a ser el local (cp1252), donde un `≤` o un `→`
# mata el script con UnicodeEncodeError. Es decir: el fallo no era una consola rara, era el
# camino normal. Se fuerza UTF-8 antes de imprimir nada.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parents[3]
# `--raiz RUTA` desacopla el linter del workspace donde vive: Modo D mide el workspace
# VIEJO con el linter NUEVO —la misma vara antes y después de actualizar— para que un
# cambio de redacción de un check no se disfrace de regresión y revierta en falso (ADR-026).
if "--raiz" in sys.argv:
    _indice = sys.argv.index("--raiz")
    if _indice + 1 >= len(sys.argv):
        sys.exit("uso: lint_metodo.py [--raiz RUTA_DEL_META_REPO]")
    RAIZ = Path(sys.argv[_indice + 1]).resolve()
BASE_REF = None
if "--base-ref" in sys.argv:
    _indice_base = sys.argv.index("--base-ref")
    if _indice_base + 1 >= len(sys.argv):
        sys.exit("uso: lint_metodo.py [--raiz RUTA_DEL_META_REPO] [--base-ref COMMIT]")
    BASE_REF = sys.argv[_indice_base + 1].strip()
fallos, avisos = [], []
hallazgos = []
HOY = datetime.date.today()
MODO_JSON = "--json" in sys.argv

REGISTRO_DEGRADADOS = RAIZ / "docs/00-metodo/guardianes-degradados.json"
IDS_NO_DEGRADABLES = {
    "guardianes-degradados-invalido",
    "guardianes-degradados-modificado",
    "pkill",
    "dockerignore-ausente",
    "dockerignore-incompleto",
    "rechazos-sin-salida",
}


def _cargar_degradados():
    try:
        datos = json.loads(REGISTRO_DEGRADADOS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set(), None
    except (OSError, json.JSONDecodeError) as exc:
        return set(), str(exc)
    ids = datos.get("ids") if isinstance(datos, dict) and datos.get("version") == 1 else None
    if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
        return set(), "exige {\"version\": 1, \"ids\": [<id>, ...]}"
    return set(ids), None


DEGRADADOS, ERROR_DEGRADADOS = _cargar_degradados()
ERROR_COMPARACION_DEGRADADOS = None


def _sujeto_y_ruta(msg):
    """Atribución conservadora para los checks antiguos migrados a identidad estable."""
    texto = str(msg)
    match = re.match(r"bugs/(\d{3}-[a-z0-9-]+)", texto)
    if match:
        slug = match.group(1)
        return f"bug:{slug}", f"docs/bugs/{slug}.md"
    match = re.match(r"(?:archivo/)?(\d{3}-[a-z0-9-]+)", texto)
    if match:
        slug = match.group(1)
        activa = RAIZ / "docs/05-trabajo" / slug / "especificacion.md"
        prefijo = "docs/05-trabajo" if activa.is_file() else "docs/05-trabajo/archivo"
        return f"unidad:{slug}", f"{prefijo}/{slug}/especificacion.md"
    match = re.match(r"(P-\d{8}-[a-f0-9]{8})(?:@(\d+))?", texto)
    if match:
        pid = match.group(1)
        revision = match.group(2)
        if revision is None:
            try:
                datos = json.loads(
                    (RAIZ / "docs/05-trabajo/peticiones" / pid / "peticion.json")
                    .read_text(encoding="utf-8")
                )
                revision = str(datos.get("revision") or "")
            except (OSError, json.JSONDecodeError):
                revision = ""
        revision = f"@{revision}" if revision else ""
        return f"peticion:{pid}{revision}", f"docs/05-trabajo/peticiones/{pid}/peticion.json"
    return "taller", "."


def _revision_tiene_degradados(repo, revision, relativa):
    """Lee ids del registro en una revisión sin depender del checkout actual."""
    codigo, contenido = git(repo, "show", f"{revision}:{relativa}")
    if codigo:
        return False
    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError:
        return False
    ids = datos.get("ids") if isinstance(datos, dict) and datos.get("version") == 1 else None
    return isinstance(ids, list) and bool(ids)


def _registrar(id_, severidad, msg, sujeto=None, ruta=None, instancia=None):
    sujeto_inferido, ruta_inferida = _sujeto_y_ruta(msg)
    hallazgos.append({
        "id": str(id_),
        "severidad": severidad,
        "sujeto": sujeto or sujeto_inferido,
        "ruta": str(ruta or ruta_inferida).replace("\\", "/"),
        "instancia": str(instancia or "unica"),
    })


def ok(msg):
    if not MODO_JSON:
        print(f"  OK   {msg}")


def warn(msg, *, id_, sujeto=None, ruta=None, instancia=None):
    avisos.append(msg)
    _registrar(id_, "WARN", msg, sujeto, ruta, instancia)
    if not MODO_JSON:
        print(f"  WARN {msg}")


def fail(msg, *, id_, sujeto=None, ruta=None, instancia=None):
    if id_ in DEGRADADOS and id_ not in IDS_NO_DEGRADABLES:
        avisos.append(msg)
        _registrar(id_, "WARN", msg, sujeto, ruta, instancia)
        if not MODO_JSON:
            severidad = "WARN"
            print(f"  {severidad:<4} {msg}")
        return
    fallos.append(msg)
    _registrar(id_, "FAIL", msg, sujeto, ruta, instancia)
    if not MODO_JSON:
        print(f"  FAIL {msg}")


def _registro_degradados_modificado():
    """Detecta autoindulto en un árbol de trabajo o en una rama aún no integrada."""
    global ERROR_COMPARACION_DEGRADADOS
    codigo, raiz_git = git(RAIZ, "rev-parse", "--show-toplevel")
    if codigo:
        if BASE_REF:
            ERROR_COMPARACION_DEGRADADOS = (
                f"no hay repositorio git para comparar --base-ref {BASE_REF} con HEAD"
            )
            return True
        return False
    raiz_git = Path(raiz_git)
    try:
        relativa = REGISTRO_DEGRADADOS.resolve().relative_to(raiz_git.resolve()).as_posix()
    except ValueError:
        return False
    if git(raiz_git, "status", "--porcelain", "--", relativa)[1].strip():
        # Modo D puede añadir por primera vez el registro vacío a un taller antiguo.
        # Eso no rebaja nada. Vaciar uno que HEAD ya tenía con ids sí es autoindulto.
        return bool(DEGRADADOS) or _revision_tiene_degradados(
            raiz_git, "HEAD", relativa
        )
    if BASE_REF:
        if git(raiz_git, "rev-parse", "--verify", "--quiet",
               f"{BASE_REF}^{{commit}}")[0] != 0:
            ERROR_COMPARACION_DEGRADADOS = (
                f"--base-ref {BASE_REF} no identifica un commit en {raiz_git}"
            )
            return True
        if git(raiz_git, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")[0] != 0:
            ERROR_COMPARACION_DEGRADADOS = "HEAD no identifica un commit comparable"
            return True
        codigo, cambiado = git(
            raiz_git, "diff", "--name-only", f"{BASE_REF}...HEAD", "--", relativa
        )
        if codigo:
            ERROR_COMPARACION_DEGRADADOS = (
                f"git diff {BASE_REF}...HEAD no pudo comparar el registro"
            )
            return True
        return bool(cambiado.strip()) and (
            bool(DEGRADADOS)
            or _revision_tiene_degradados(raiz_git, BASE_REF, relativa)
        )
    rama = git(raiz_git, "branch", "--show-current")[1].strip()
    for principal in ("main", "master"):
        if (rama and rama != principal
                and git(raiz_git, "rev-parse", "--verify", principal)[0] == 0):
            cambiado = git(
                raiz_git, "diff", "--name-only", f"{principal}...HEAD", "--", relativa
            )[1]
            return bool(cambiado.strip()) and (
                bool(DEGRADADOS)
                or _revision_tiene_degradados(raiz_git, principal, relativa)
            )
    return False


# El vocabulario cerrado de la unidad vive en `repo_config.py` (unidad 050): estaba escrito
# aquí y en `unidad.py`, coincidiendo por suerte, sin que nada lo comprobara.
ESTADOS_UNIDAD = repo_config.ESTADOS_UNIDAD
TIPOS = repo_config.TIPOS
# `CARRILES` NO se centraliza: aquí son los tres carriles que admite el frontmatter de una
# unidad, y en `peticion.py` son los seis valores de `--ruta` de una petición. Mismo nombre,
# conceptos distintos; forzarlos a uno inventaría un bug (unidad 050, R9).
CARRILES = {"directo", "normal", "completo"}
DOCS_PERMITIDOS = {"00-metodo", "01-constitucion", "02-flujos", "03-investigacion",
                   "04-planificacion", "05-trabajo", "bugs", "conocimiento", "decisiones"}
CLAVES_FRONTMATTER = {"unidad", "tipo", "carril", "estado", "actividad", "ficheros",
                      "actualizado", "aprobado"}
EN_VUELO = {"en_obra", "en_revision"}
RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONTRATOS_PETICION = {
    "unidad": "unidad-mergeada-v1", "bug": "bug-mergeado-v1",
    "expres": "rama-expres-v1", "investigacion": "fase3-sintetizada-v1",
    "auditoria": "unidad-auditoria-mergeada-v1", "flujos": "planos-aprobados-v1",
    "deploy": "despliegue-verificado-v1",
    # Bug 118: el proceso de la 087 (un merge hecho FUERA del método) nace terminal en
    # `peticion.py`; sin esta entrada el lint lo daba por «sin contrato canónico».
    "merge-externo": "merge-externo-v1",
}

# Marca que `unidad.py despachar --force` escribe en la ficha de un hotfix P0. Es la única
# forma legítima de estar en obra sin `aprobado:`, y es DEUDA: hotfix.md da 24 h para pagarla.
MARCA_DEUDA = "DEUDA DE SPEC — HOTFIX"

# Línea de cierre de la ficha de bug: "**Validación del usuario:** PENDIENTE | OK (fecha) | …".
# El separador es laxo (`:`, `*`, espacios) porque el énfasis markdown varía entre fichas.
RE_VALIDACION = re.compile(r"Validaci[oó]n del usuario[\s:*]*(.*)$", re.IGNORECASE)
# Marcador de plantilla sin rellenar: `<ruta del test>`, `<qué se cambió>`, …
RE_PLACEHOLDER = re.compile(r"<[^<>\n]{2,}>")
PISTA_PLANTILLA = "(pegado, no resumido)"


def lineas_de_plantilla_bug():
    """Líneas literales de plantillas/bug.md: sirven para separar PLANTILLA de EVIDENCIA.

    La propia plantilla nombra ROJO y VERDE en sus instrucciones ("Test del bug: VERDE —
    output pegado…"), así que buscar esas palabras a pelo daría por buena una ficha en blanco.
    Solo cuenta como evidencia el texto que alguien AÑADIÓ a la ficha.
    """
    try:
        texto = (RAIZ / "docs/00-metodo/plantillas/bug.md").read_text(encoding="utf-8")
    except OSError:
        return set()
    return {linea.strip() for linea in texto.splitlines() if linea.strip()}


PLANTILLA_BUG = lineas_de_plantilla_bug()


def validado_por_el_usuario(texto):
    """¿La sección 6 de la ficha lleva la validación del usuario en OK?

    Se mira el VALOR que sigue a 'Validación del usuario:' y se exige que EMPIECE por OK. Así
    la línea intacta de la plantilla —que contiene la palabra OK dentro del menú
    'PENDIENTE | OK (YYYY-MM-DD) | REABIERTO'— no cuela como validación.
    """
    for linea in texto.splitlines():
        m = RE_VALIDACION.search(linea)
        if m and re.match(r"^OK\b", m.group(1).strip().strip("*").strip(), re.IGNORECASE):
            return True
    return False


def evidencia_rojo_verde(texto):
    """¿Está pegado el par ROJO (§2) → VERDE (§5) del test del bug? Devuelve (rojo, verde).

    Detección a propósito tolerante —basta con que aparezcan las palabras ROJO y VERDE, porque
    el formato del output pegado no se puede predecir—, pero se descarta todo lo que siga
    siendo plantilla: líneas idénticas a plantillas/bug.md, marcadores `<…>` sin rellenar o la
    pista "(pegado, no resumido)". Una ficha sin tocar no puede pasar por evidencia.
    """
    rojo = verde = False
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia or limpia in PLANTILLA_BUG:
            continue
        if RE_PLACEHOLDER.search(limpia) or PISTA_PLANTILLA in limpia:
            continue
        minuscula = limpia.lower()
        rojo = rojo or "rojo" in minuscula
        verde = verde or "verde" in minuscula
    return rojo, verde


# R4 del bug 054: mismo criterio que `unidad.py` (que es quien bloquea el despacho, R3) —
# el apartado de contratos de la web anota una línea por contrato mostrado en este
# fichero. Desde la 081 la web es una sola y el comando dice a qué apartado se abre.
RASTRO_VISOR_CONTRATOS = ".runtime/visor-contratos.log"
COMANDO_VISOR_CONTRATOS = (
    "python3 main/web/abrir.py --workspace . --apartado contratos"
)
RE_RASTRO_CONTRATO = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T[\d:]+\s+contrato mostrado:\s+(\S+)\s*$"
)


def visto_por_visor_contratos(nombre):
    """¿El visor de contratos mostró ALGUNA vez este contrato? WARN, no FAIL (R4): avisa,
    no bloquea — la puerta dura vive en `unidad.py despachar` (R3)."""
    registro = RAIZ / RASTRO_VISOR_CONTRATOS
    if not registro.is_file():
        return False
    try:
        texto = registro.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(
        (m := RE_RASTRO_CONTRATO.match(linea)) and m.group(2) == nombre
        for linea in texto.splitlines()
    )


def aprobado_por_el_usuario(fm):
    """¿El frontmatter lleva una fecha de aprobación real? (`no`, vacío o ausente = no).

    Ni futura: una aprobación fechada en 2030 no la firmó nadie que hubiera leído el contrato.
    Mismo criterio que `unidad.py`, que es quien bloquea el despacho.
    """
    valor = (fm.get("aprobado") or "").strip().strip("`'\"")
    if not RE_FECHA.match(valor):
        return False
    try:
        return datetime.date.fromisoformat(valor) <= HOY
    except ValueError:
        return False


def revisar_deuda_hotfix(nombre, ruta, fm):
    """La deuda de spec de un hotfix deja de ser un adorno: aquí se le pone reloj.

    Criterio (runbook hotfix.md): la marca se borra al pagar la deuda — reproducción
    determinista, causa raíz y tests de regresión contraprobados — en las 24 h siguientes a
    estabilizar. Por eso:
      · FAIL si la unidad ya está `mergeada`: se cerró con el contrato a deber, y después de
        cerrar nadie vuelve a pagarlo.
      · FAIL si `actualizado:` tiene más de 24 h (granularidad de día: ayer aún cabe en el
        plazo, anteayer ya no): venció el plazo del runbook.
      · WARN mientras siga dentro del plazo, para que se vea en cada arranque de sesión.
    """
    if MARCA_DEUDA not in ruta.read_text(encoding="utf-8"):
        return
    if fm.get("estado") == "mergeada":
        fail(f"{nombre}: mergeada con la DEUDA DE SPEC del hotfix sin pagar "
             f"(hotfix.md: se paga ANTES de cerrar; borra la marca al completar la ficha)", id_='revisar-deuda-hotfix-mergeada-deuda-spec-hotfix-pagar-hotfix')
        return
    actualizado = (fm.get("actualizado") or "").strip()
    try:
        dias = (HOY - datetime.date.fromisoformat(actualizado)).days
    except ValueError:
        fail(f"{nombre}: deuda de hotfix con 'actualizado: {actualizado or 'ausente'}' "
             f"ilegible — sin fecha no hay plazo que valga", id_='revisar-deuda-hotfix-deuda-hotfix-actualizado-ilegible-fecha-plazo')
        return
    if dias > 1:
        fail(f"{nombre}: DEUDA DE SPEC del hotfix sin pagar {dias} días después de "
             f"'actualizado: {actualizado}' (plazo: 24 h, hotfix.md). No se abre trabajo "
             f"nuevo que no sea otro hotfix hasta pagarla", id_='revisar-deuda-hotfix-deuda-spec-hotfix-pagar-dias-despues')
    else:
        warn(f"{nombre}: DEUDA DE SPEC del hotfix sin pagar (dentro del plazo de 24 h desde "
             f"{actualizado}): completa la ficha y borra la marca", id_='revisar-deuda-hotfix-deuda-spec-hotfix-pagar-dentro-plazo')


RE_MERGE_EXTERNO_PR = re.compile(r"#\d+|https?://\S+/(?:pull|merge_requests)/\d+/?")
RE_MERGE_EXTERNO_SHA = re.compile(r"[0-9a-f]{7,40}")


def merge_externo_existe(ref):
    """Bug 118 — ¿la cita de un merge externo apunta a algo real? PR: sí por forma; SHA: si
    el repo de código lo tiene (`git cat-file -e`), igual que `peticion.validar_merge_externo`."""
    ref = str(ref or "").strip()
    if RE_MERGE_EXTERNO_PR.fullmatch(ref):
        return True
    if not RE_MERGE_EXTERNO_SHA.fullmatch(ref):
        return False
    repo, _ = repo_codigo()
    return git(repo, "cat-file", "-e", f"{ref}^{{commit}}")[0] == 0


TITULOS_DE_PLANTILLA = ("<síntoma en una frase>", "<título en una frase>")


def avisar_titulo_de_plantilla(nombre, texto, prefijo=""):
    """Bug 120 — la ficha sigue con el H1 de la plantilla: no dice de qué va y la web lo enseña.
    WARN, no FAIL: `unidad.py despachar` es quien bloquea; aquí se avisa mientras se escribe."""
    for linea in (texto or "").splitlines():
        if linea.startswith("# "):
            if any(m in linea for m in TITULOS_DE_PLANTILLA):
                warn(f"{prefijo}{nombre}: el título sigue siendo el de la plantilla ({linea.strip()}). "
                     f"SALIDA: escribe ahí el síntoma o el cambio en una frase; hasta entonces "
                     f"`python3 docs/00-metodo/scripts/unidad.py despachar {nombre}` la rechaza", id_='avisar-titulo-de-plantilla-titulo-sigue-siendo-plantilla-salida-escribe')
            return


def repo_codigo():
    """Ruta y rama principal del repo de código, leídas de repos.yaml (igual que unidad.py)."""
    try:
        return repo_config.repo_code(RAIZ)
    except repo_config.RepoConfigError as exc:
        fail(str(exc), id_='repo-codigo-error-interno', sujeto="taller", ruta="repos.yaml",
             instancia="configuracion-repo-codigo")
        return RAIZ / ".ruta-local-invalida", "main"


def planos_declaran_e2e():
    """Detecta una selección E2E en el mapa o en cualquiera de sus actividades."""
    carpeta = RAIZ / "docs/02-flujos/planos"
    if not carpeta.is_dir():
        return False
    for ruta in carpeta.rglob("planos.json"):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(datos, dict) and datos.get("pruebas_e2e"):
            return True
    return False


def huella_planos_actual():
    mapa = RAIZ / "docs/02-flujos/planos/planos.json"
    try:
        raiz = json.loads(mapa.read_text(encoding="utf-8"))
        rutas = [mapa]
        for actividad in raiz.get("actividades", []):
            ruta = mapa.parent / "actividades" / actividad["id"] / "planos.json"
            if not ruta.exists():
                # Bug 053 (gemelo del 026 en peticion.py): una actividad «sin empezar» no
                # tiene planos todavía. Reventar aquí devolvía None y el §5 comparaba el
                # recibo aprobado contra ese None: FAIL falso con la firma intacta. Fuera
                # de la huella, igual que en peticion.py, para que las dos copias firmen
                # lo mismo.
                continue
            rutas.append(ruta)
        bundle = {
            ruta.relative_to(mapa.parent).as_posix(): json.loads(
                ruta.read_text(encoding="utf-8")
            )
            for ruta in rutas
        }
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    bruto = json.dumps(
        bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()


def git(repo, *args):
    """git acotado a un repo. Devuelve (codigo, salida); jamás lanza: sin git no hay veredicto."""
    try:
        p = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", check=False)
    except OSError:
        return 1, ""
    return p.returncode, (p.stdout + p.stderr).strip()


def rama_fusionada(repo, rama, principal, metadata):
    metadata = metadata or {}
    base_sha = metadata.get("base_sha", "")
    if not base_sha or git(
        repo, "merge-base", "--is-ancestor", base_sha, principal
    )[0] != 0:
        return False
    codigo, punta = git(repo, "rev-parse", "--verify", "--quiet", f"{rama}^{{commit}}")
    punta = punta.strip() if codigo == 0 else metadata.get("tip_sha", "")
    if punta == base_sha:
        return False
    # Sin punta (rama borrada tras el merge y sin tip_sha guardado) los caminos
    # por ancestría no existen, pero el grep del squash de más abajo sigue
    # valiendo: el asunto del merge es el testigo (bugs 021/022).
    punta_existe = git(
        repo, "rev-parse", "--verify", "--quiet", f"{punta}^{{commit}}"
    )[0] == 0
    merge_guardado = metadata.get("merge_sha", "")
    modo_guardado = metadata.get("modo_fusion", "")
    if merge_guardado and git(
        repo, "merge-base", "--is-ancestor", merge_guardado, principal
    )[0] == 0:
        if modo_guardado == "ancestry" and merge_guardado == punta:
            return True
        codigo, asunto = git(repo, "show", "-s", "--format=%s", merge_guardado)
        if modo_guardado == "squash" and codigo == 0 and rama in asunto:
            return True
    if punta:
        if not punta_existe or git(
            repo, "merge-base", "--is-ancestor", base_sha, punta
        )[0] != 0:
            return False
        if git(repo, "merge-base", "--is-ancestor", punta, principal)[0] == 0:
            return True
    # Grep del squash: primero el nombre exacto de la rama; si el título del PR
    # no lo conservó, vale el P-ID que el nombre de una rama exprés siempre
    # contiene. Sin ninguno de los dos en el asunto NO hay testigo (021/022).
    patrones = [rama]
    p_id = re.search(r"P-\d{8}-[0-9a-f]{8}", rama)
    if p_id:
        patrones.append(p_id.group(0))
    for patron in patrones:
        codigo, salida = git(
            repo, "log", principal, f"^{base_sha}", "--fixed-strings",
            f"--grep={patron}", "--format=%H", "-1",
        )
        if codigo == 0 and salida.strip():
            return True
    return False


def fecha_iso_valida(valor):
    try:
        datetime.date.fromisoformat(valor)
    except (TypeError, ValueError):
        return False
    return True


CAMPOS_DEPLOY_OBLIGATORIOS = (
    "Commit/tag", "Etapa destino y máquina exacta",
    "Qué cambia para el usuario, en una frase", "OK del usuario ANTES de salir",
    "Suite completa sobre este commit", "Seguridad sobre este commit",
    "Qué se copió y adónde", "Volcado — comando y salida", "Restauración de prueba",
    "Pasos", "Vuelta atrás", "Flujo real de negocio de punta a punta", "Vigilancia",
    "Validación del usuario sobre la etapa desplegada", "Resultado", "Quién y cuándo",
    "Anotado en `conocimiento/plano-deploy.md`",
)


def campos_ficha_deploy(texto):
    campos = {}
    for linea in texto.splitlines():
        encontrada = re.match(
            r"^\s*(?:[-*]|\d+\.)\s+\*\*([^*]+?)(?::)?\*\*\s*:?\s*(.+?)\s*$",
            linea,
        )
        if encontrada:
            campos[encontrada.group(1).strip().rstrip(":")] = encontrada.group(2).strip()
    return campos


def ficha_deploy_terminal_valida(ruta):
    fm = frontmatter(ruta) or {}
    texto = ruta.read_text(encoding="utf-8")
    if fm.get("proceso") != "deploy" or fm.get("estado") != "desplegado":
        return False
    if fm.get("etapa") not in {"0-local", "1-lan", "2-vps"}:
        return False
    if not fecha_iso_valida(fm.get("fecha", "")):
        return False
    if re.search(r"<[^>]+>|PENDIENTE|DESPLEGADO\s*\|", texto):
        return False
    campos = campos_ficha_deploy(texto)
    if any(len(campos.get(nombre, "").strip(" .:·-")) < 3 for nombre in CAMPOS_DEPLOY_OBLIGATORIOS):
        return False
    commit = fm.get("commit", "")
    repo, principal = repo_codigo()
    if not commit or git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")[0]:
        return False
    if git(repo, "merge-base", "--is-ancestor", commit, principal)[0] != 0:
        return False
    ok_previo = re.match(
        r"OK\s*\((\d{4}-\d{2}-\d{2}),\s*([^)]+)\)",
        campos["OK del usuario ANTES de salir"],
    )
    ok_final = re.match(
        r"OK\s*\((\d{4}-\d{2}-\d{2})\)",
        campos["Validación del usuario sobre la etapa desplegada"],
    )
    return bool(
        re.match(rf"{re.escape(commit)}\b", campos["Commit/tag"])
        and ok_previo and fecha_iso_valida(ok_previo.group(1)) and ok_previo.group(2).strip()
        and re.match(r"VERDE\b.*\.runtime/pre-deploy/full-suite\.log", campos["Suite completa sobre este commit"])
        and re.match(r"VERDE\b.*\.runtime/pre-deploy/security\.log", campos["Seguridad sobre este commit"])
        and ok_final and fecha_iso_valida(ok_final.group(1))
        and campos["Resultado"].startswith("DESPLEGADO")
        and re.search(r"\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\b", campos["Quién y cuándo"])
    )


def frontmatter(path):
    """Parseo mínimo del frontmatter YAML (clave: valor). Devuelve dict o None.

    Admite lista en línea (`ficheros: [a, b]`) y lista multilínea (`ficheros:` y debajo
    `  - a`), que es como se escribe cuando son más de dos rutas. Antes solo se leía la
    primera línea, así que una lista multilínea quedaba en cadena vacía y la comprobación
    de ficheros disjuntos de la sección 4b comparaba conjuntos vacíos: pasaba siempre.
    Misma implementación que en unidad.py, a propósito: si uno lo acepta, el otro también.
    """
    try:
        lineas = path.read_text(encoding="utf-8").splitlines()
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
                clave_abierta = m.group(1)
            continue
        item = re.match(r"^\s+-\s*(.+)$", linea)
        if item and clave_abierta:
            items.append(item.group(1).split("#")[0].strip().strip("'\""))
    return None


PETICIONES = RAIZ / "docs/05-trabajo/peticiones"
RE_PETICION_REVISION = re.compile(r"^(P-\d{8}-[a-f0-9]{8})@(\d+)$")


def cargar_legacy():
    ruta = PETICIONES / "LEGACY.json"
    if not ruta.exists():
        return {"formato": 1, "modo": "estricto", "unidades": [], "bugs": [], "ramas": []}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"peticiones/LEGACY.json ilegible: {exc}", id_='cargar-legacy-peticiones-legacy-json-ilegible')
        return {"formato": 1, "modo": "estricto", "unidades": [], "bugs": [], "ramas": []}
    if datos.get("formato") != 1 or datos.get("modo") not in {"observacion", "estricto"}:
        fail("peticiones/LEGACY.json exige formato 1 y modo observacion|estricto", id_='cargar-legacy-peticiones-legacy-json-exige-formato-modo')
        datos["modo"] = "estricto"
    for clave in ("unidades", "bugs", "ramas"):
        if not isinstance(datos.get(clave), list):
            fail(f"peticiones/LEGACY.json: {clave} debe ser una lista exacta", id_='cargar-legacy-peticiones-legacy-json-debe-ser-lista')
            datos[clave] = []
    return datos


LEGACY = cargar_legacy()


def referencias_peticion(fm):
    valor = (fm.get("peticiones") or "").strip()
    if valor.startswith("[") and valor.endswith("]"):
        valor = valor[1:-1]
    return [item.strip().strip("'\"") for item in valor.split(",") if item.strip()]


def huerfano(nombre, clase, detalle="sin petición de origen"):
    lista = "bugs" if clase == "bug" else "unidades"
    if nombre in set(LEGACY.get(lista, [])):
        return
    mensaje = f"{nombre}: {detalle}"
    reporter = warn if LEGACY.get("modo") == "observacion" else fail
    reporter(mensaje, id_="origen-huerfano")


def validar_origen_peticion(nombre, fm, clase="unidad", archivada=False):
    referencias = referencias_peticion(fm)
    if not referencias:
        huerfano(nombre, clase)
        return
    for referencia in referencias:
        encontrada = RE_PETICION_REVISION.fullmatch(referencia)
        if not encontrada:
            fail(f"{nombre}: referencia de petición inválida '{referencia}' (usa P-ID@revision)", id_='referencia-peticion-invalida-usa-p-id')
            continue
        pid, revision = encontrada.groups()
        ruta = PETICIONES / pid / "peticion.json"
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            fail(f"{nombre}: petición inexistente {pid}", id_='peticion-inexistente')
            continue
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"{nombre}: no se puede leer {pid}: {exc}", id_='puede-leer')
            continue
        if datos.get("revision") != int(revision):
            if archivada:
                warn(f"{nombre}: historia: satisfizo la revisión {revision} de {pid}; "
                     f"la petición viva está en revisión {datos.get('revision')}", id_="revision-desfasada-historica")
            else:
                fail(f"{nombre}: {pid} está en revisión {datos.get('revision')}; "
                     f"la orden referencia revisión {revision} · SALIDA: python3 "
                     f"docs/00-metodo/scripts/peticion.py reencuadrar-orden {pid}", id_='revision-desfasada')
        tipo_proceso = "bug" if clase == "bug" else "unidad"
        enlazada = any(
            proceso.get("tipo") == tipo_proceso
            and proceso.get("ref") == nombre
            and proceso.get("revision") == int(revision)
            for proceso in datos.get("procesos", [])
        )
        if not enlazada:
            fail(f"{nombre}: {pid}@{revision} no enlaza de vuelta este proceso", id_='enlaza-vuelta-proceso')


def revisar_cola_peticiones():
    if not PETICIONES.is_dir():
        fail("docs/05-trabajo/peticiones/ no existe", id_='docs-trabajo-peticiones-existe')
        return
    sin_siguiente = []
    for ruta in sorted(PETICIONES.glob("P-*/peticion.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"{ruta.parent.name}: peticion.json ilegible: {exc}", id_='peticion-json-ilegible')
            continue
        pid = datos.get("id") or ruta.parent.name
        if pid != ruta.parent.name:
            fail(f"{ruta.parent.name}: peticion.json declara id {pid}", id_='peticion-json-declara-id')
        for proceso in datos.get("procesos", []):
            tipo, ref = proceso.get("tipo"), proceso.get("ref", "?")
            esperado = CONTRATOS_PETICION.get(tipo)
            if not esperado or proceso.get("contrato_terminal") != esperado:
                fail(f"{pid}: proceso {tipo} {ref} sin contrato terminal canónico", id_='proceso-contrato-terminal-canonico')
            canonica = None
            if tipo == "unidad":
                candidatos = (
                    RAIZ / "docs/05-trabajo" / ref / "especificacion.md",
                    RAIZ / "docs/05-trabajo/archivo" / ref / "especificacion.md",
                )
                canonica = next((item for item in candidatos if item.is_file()), None)
            elif tipo == "bug":
                candidata = RAIZ / "docs/bugs" / f"{ref}.md"
                canonica = candidata if candidata.is_file() else None
            elif tipo == "auditoria":
                candidatos = (
                    RAIZ / "docs/05-trabajo" / ref / "especificacion.md",
                    RAIZ / "docs/05-trabajo/archivo" / ref / "especificacion.md",
                )
                canonica = next((item for item in candidatos if item.is_file()), None)
                if canonica and (frontmatter(canonica) or {}).get("tipo") != "auditoria":
                    canonica = None
            elif tipo == "merge-externo":
                # Bug 118: la `ref` no es un fichero: es un PR (`#36`, su URL) o un SHA del
                # repo de código. El PR se acepta tal cual (no hay GitHub que consultar en
                # local); el SHA tiene que existir en el repo, como exige `peticion.py`.
                if not merge_externo_existe(ref):
                    fail(f"{pid}: merge externo {ref} no existe en el repo de código · "
                         f"SALIDA: trae el commit (git -C main fetch origin) y vuelve a "
                         f"pasar el lint, o cita el PR con `peticion.py enlazar {pid} "
                         f"--tipo merge-externo --ref '#N'`", id_='merge-externo-existe-repo-codigo-salida')
                    continue
                canonica = True
            elif tipo not in {"expres"}:
                candidata = Path(str(ref))
                if not candidata.is_absolute() and ".." not in candidata.parts:
                    resuelta = (RAIZ / candidata).resolve()
                    if resuelta.is_file() and RAIZ.resolve() in resuelta.parents:
                        canonica = resuelta
                if tipo == "deploy":
                    # Bug 038: desplegar DESPUÉS de cerrar es el caso normal; la ficha de
                    # una unidad ya archivada vive en 05-trabajo/archivo/ y es tan válida
                    # como la activa (igual que hacen `unidad` y `auditoria` más arriba).
                    esperada = re.fullmatch(
                        r"docs/(?:05-trabajo(?:/archivo)?|bugs)/\d{3}-[a-z0-9][a-z0-9-]*/despliegue\.md"
                        r"|docs/05-trabajo/despliegues/[a-z0-9][a-z0-9-]*\.md",
                        str(ref),
                    )
                    if canonica is None or not esperada:
                        canonica = None
                if tipo == "flujos" and ref != "docs/02-flujos/planos/aprobacion.json":
                    canonica = None
                if tipo == "investigacion" and ref != "docs/03-investigacion/SINTESIS.md":
                    canonica = None
            if tipo != "expres" and canonica is None:
                fail(f"{pid}: proceso {tipo} inexistente: {ref}", id_='proceso-inexistente')
                continue
            if proceso.get("estado") == "terminal" and tipo in {"unidad", "bug", "auditoria"}:
                fm = frontmatter(canonica) or {}
                if fm.get("estado") != "mergeada":
                    fail(f"{pid}: proceso terminal {tipo} {ref}, pero su artefacto está "
                        f"{fm.get('estado') or 'sin estado'}", id_='proceso-terminal-pero-artefacto-estado-estado'
                    )
            if proceso.get("estado") == "terminal" and tipo == "deploy" and canonica:
                if not ficha_deploy_terminal_valida(canonica):
                    fail(f"{pid}: deploy {ref} terminal sin ficha desplegada y completa", id_='deploy-terminal-ficha-desplegada-completa')
            if proceso.get("estado") == "terminal" and tipo == "flujos" and canonica:
                try:
                    recibo = json.loads(canonica.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    recibo = {}
                if recibo.get("estado") != "aprobado" \
                        or recibo.get("huella") != huella_planos_actual() \
                        or not fecha_iso_valida(recibo.get("fecha")) \
                        or not isinstance(recibo.get("por"), str) \
                        or not recibo.get("por").strip():
                    fail(f"{pid}: flujos terminal sin recibo aprobado", id_='flujos-terminal-recibo-aprobado')
            if proceso.get("estado") == "terminal" and tipo == "investigacion" and canonica:
                informes = list(canonica.parent.glob("informe-[0-9][0-9]-*.md"))
                indices = {informe.name.split("-", 2)[1] for informe in informes}
                informes_validos = (
                    {f"{indice:02d}" for indice in range(1, 11)}.issubset(indices)
                    and all(
                        len(informe.read_text(encoding="utf-8").strip()) >= 200
                        and not re.search(
                            r"<[^>]+>|YYYY-MM-DD", informe.read_text(encoding="utf-8")
                        )
                        and re.search(r"https://\S+", informe.read_text(encoding="utf-8"))
                        and any(fecha_iso_valida(fecha) for fecha in re.findall(
                            r"\b20\d{2}-\d{2}-\d{2}\b",
                            informe.read_text(encoding="utf-8"),
                        ))
                        and re.search(
                            r"\bnivel\s*[:|]", informe.read_text(encoding="utf-8"), re.I
                        )
                        for informe in informes
                    )
                )
                sintesis = canonica.read_text(encoding="utf-8")
                if not informes_validos or len(sintesis.strip()) < 200 or re.search(
                    r"<[^>]+>|YYYY-MM-DD", sintesis
                ):
                    fail(f"{pid}: investigación terminal sin al menos 10 informes "
                        "y síntesis completa", id_='investigacion-terminal-menos-informes-sintesis-completa'
                    )
            if proceso.get("estado") == "terminal" and tipo == "expres":
                repo, principal = repo_codigo()
                metadata = proceso.get("metadata") or {}
                if not rama_fusionada(repo, ref, principal, metadata):
                    fail(f"{pid}: exprés terminal sin cambio fusionado en {principal}", id_='expres-terminal-cambio-fusionado')
        abiertos = [
            proceso.get("ref", "?")
            for proceso in datos.get("procesos", [])
            if proceso.get("relacion") == "satisface"
            and proceso.get("revision") == datos.get("revision")
            and proceso.get("estado") not in {"terminal", "sustituido", "cancelado"}
        ]
        if datos.get("estado") in {"cerrada", "cancelada"} and abiertos:
            fail(f"{pid}: {datos.get('estado')} con proceso abierto: {', '.join(abiertos)}", id_='proceso-abierto-estado')
        satisface = [
            proceso for proceso in datos.get("procesos", [])
            if proceso.get("relacion") == "satisface"
            and proceso.get("revision") == datos.get("revision")
            and proceso.get("estado") != "sustituido"
        ]
        if datos.get("resultado") == "entregada" and not satisface:
            fail(f"{pid}: entregada sin ningún proceso que la satisfaga", id_='entregada-ningun-proceso-satisfaga')
        if datos.get("resultado") == "entregada" and any(
            proceso.get("estado") != "terminal" for proceso in satisface
        ):
            fail(f"{pid}: entregada con procesos no terminales", id_='entregada-procesos-terminales')
        if datos.get("estado") in {"capturada", "evaluando"}:
            sin_siguiente.append(pid)
        if datos.get("estado") == "aparcada":
            revisar_el = (datos.get("aparcada") or {}).get("revisar_el")
            try:
                vencida = bool(revisar_el) and datetime.date.fromisoformat(revisar_el) <= HOY
            except ValueError:
                fail(f"{pid}: fecha de revisión aparcada ilegible: {revisar_el}", id_='fecha-revision-aparcada-ilegible')
                vencida = False
            if vencida:
                warn(f"{pid}: aparcada vencida desde {revisar_el}; reanudar, cancelar o reprogramar", id_='aparcada-vencida-desde-reanudar-cancelar-reprogramar')
    if sin_siguiente:
        warn(f"{len(sin_siguiente)} peticiones sin siguiente proceso "
             f"({', '.join(sin_siguiente)}); evaluar o aparcar · "
             "SALIDA: python3 docs/00-metodo/scripts/peticion.py listar", id_="peticiones-sin-siguiente-proceso",
             sujeto="taller", ruta="docs/05-trabajo/peticiones", instancia="cola")


if not MODO_JSON:
    print("== Linter del método ==")

if ERROR_DEGRADADOS:
    fail(f"guardianes-degradados.json ilegible: {ERROR_DEGRADADOS} · SALIDA: "
         "git checkout -- docs/00-metodo/guardianes-degradados.json", id_="guardianes-degradados-invalido",
         ruta="docs/00-metodo/guardianes-degradados.json")
elif IDS_NO_DEGRADABLES & DEGRADADOS:
    fail("guardianes-degradados.json intenta rebajar guardianes no degradables · "
         "SALIDA: git checkout -- docs/00-metodo/guardianes-degradados.json", id_="guardianes-degradados-invalido",
         ruta="docs/00-metodo/guardianes-degradados.json")
elif _registro_degradados_modificado():
    detalle_comparacion = (
        f" ({ERROR_COMPARACION_DEGRADADOS})" if ERROR_COMPARACION_DEGRADADOS else ""
    )
    # salida:por-diseño autoridad-humana: solo el autor del método decide la degradación
    # mediante una petición y una unidad aprobadas que nombren el id y el motivo.
    fail("guardianes-degradados.json cambia en el mismo trabajo que pretende usarlo"
         f"{detalle_comparacion} · "
         "solo el autor del método puede separarlo mediante una petición y una unidad "
         "aprobadas que nombren el id y el motivo", id_="guardianes-degradados-modificado",
         ruta="docs/00-metodo/guardianes-degradados.json", instancia="contenido-no-vacio")

# --- 0. El arsenal del método: los guardianes existen y no están vacíos ---
# Se demostró (auditoría adversaria 2026-08-03, hallazgo 3) que se podían borrar los
# runbooks y los ADRs y hasta VACIAR unidad.py con 0 FAIL: este linter validaba todo el
# workspace MENOS docs/00-metodo/, así que un agente «ordenando» podía desactivar a todos
# los demás guardianes en silencio. La lista de ficheros del método viaja en METODO.json
# (la escribe el bootstrap y la reescribe el Modo D); aquí solo se comprueba que cada uno
# existe y tiene contenido.
metodo_json = RAIZ / "METODO.json"
if not metodo_json.is_file():
    warn("METODO.json no existe: no puedo comprobar que el arsenal del método esté completo "
         "(lo escribe el bootstrap; recupéralo con `git checkout -- METODO.json`)", id_='metodo-json-existe-puedo-comprobar-arsenal')
else:
    try:
        datos_metodo = json.loads(metodo_json.read_text(encoding="utf-8"))
        if not isinstance(datos_metodo, dict):
            raise ValueError("no es un objeto JSON")
    except (OSError, ValueError) as exc:
        fail(f"METODO.json ilegible ({exc}): sin él no se puede verificar el arsenal del método", id_='metodo-json-ilegible-puede-verificar-arsenal')
        datos_metodo = None
    if datos_metodo is not None:
        archivos_metodo = datos_metodo.get("archivos") or []
        if not archivos_metodo:
            warn("METODO.json sin la lista `archivos`: el arsenal del método queda sin "
                 "vigilar hasta repartir el método actualizado (Modo D de la herramienta)", id_='metodo-json-lista-archivos-arsenal-metodo')
        else:
            rotos = []
            for relativo in archivos_metodo:
                # Manifiestos generados en Windows antes de 1.1.3 traen \ como
                # separador; se normaliza al leer y Modo D los reescribe con /.
                relativo = str(relativo).replace("\\", "/")
                ruta = RAIZ / relativo
                if not ruta.is_file():
                    rotos.append(f"{relativo} (no existe)")
                elif not ruta.read_text(encoding="utf-8", errors="replace").strip():
                    rotos.append(f"{relativo} (vacío)")
            if rotos:
                extra = f" … y {len(rotos) - 12} más" if len(rotos) > 12 else ""
                fail("arsenal del método incompleto — sin estos guardianes el resto del "
                     "linter no protege nada: " + "; ".join(rotos[:12]) + extra +
                     ". Recupéralos con `git checkout -- docs/00-metodo METODO.json` o con "
                     "el Modo D de la herramienta", id_='recuperalos-git-checkout-docs-metodo-metodo')
            else:
                ok(f"arsenal del método completo ({len(archivos_metodo)} ficheros presentes "
                   f"y con contenido)")

# --- 1. Raíz: ficheros y tope de tamaño del router ---
agents = RAIZ / "AGENTS.md"
if not agents.exists():
    fail("AGENTS.md no existe", id_='agents-md-existe')
else:
    n = len(agents.read_text(encoding="utf-8").splitlines())
    if n > 160:
        fail(f"AGENTS.md tiene {n} líneas (tope 160): el router está engordando", id_='agents-md-tiene-lineas-tope-router')
    else:
        ok(f"AGENTS.md existe ({n} líneas ≤ 160)")

for puente in ("CLAUDE.md", "GEMINI.md"):
    ruta_puente = RAIZ / puente
    contenido_puente = ruta_puente.read_text(encoding="utf-8") if ruta_puente.exists() else ""
    lineas_esperadas = ("@AGENTS.md\n", "@AGENTS.md\n@.claude/personalidad.md\n")
    if contenido_puente not in lineas_esperadas:
        fail(f"{puente} debe redirigir a AGENTS.md (y opcionalmente a .claude/personalidad.md)", id_='debe-redirigir-agents-md-opcionalmente-claude')
    else:
        ok(f"{puente} redirige directamente a AGENTS.md")

# --- 2. El árbol congelado ---
for d in sorted(DOCS_PERMITIDOS):
    if not (RAIZ / "docs" / d).is_dir():
        fail(f"falta docs/{d}/ (árbol congelado, ver ADR/estructura)", id_='falta-docs-arbol-congelado-ver-adr')
extras = {p.name for p in (RAIZ / "docs").iterdir() if p.is_dir()} - DOCS_PERMITIDOS
if extras:
    fail(f"directorios NO permitidos en docs/ (cambiar la estructura exige ADR): {sorted(extras)}", id_='directorios-permitidos-docs-cambiar-estructura-exige')
else:
    ok("docs/ contiene exactamente el árbol congelado")

# --- 3. ESTADO.md: existe y no engorda ---
estado_md = RAIZ / "docs/05-trabajo/ESTADO.md"
if not estado_md.exists():
    fail("docs/05-trabajo/ESTADO.md no existe", id_='docs-trabajo-estado-md-existe')
else:
    n = len(estado_md.read_text(encoding="utf-8").splitlines())
    mensaje_estado = f"ESTADO.md: {n} líneas {'≤ 100' if n <= 100 else '> 100 (es un digest, no un archivo)'}"
    if n <= 100:
        ok(mensaje_estado)
    else:
        fail(mensaje_estado, id_="estado-demasiado-largo")

# --- 4. Unidades: nombre, frontmatter, vocabulario, coherencia ---
trabajo = RAIZ / "docs/05-trabajo"
unidades, numeros = {}, {}
for carpeta in sorted(trabajo.iterdir()):
    if not carpeta.is_dir() or carpeta.name in {"archivo", "peticiones"}:
        continue
    if not re.match(r"^\d{3}-[a-z0-9-]+$", carpeta.name):
        fail(f"unidad con nombre fuera de convención NNN-slug: {carpeta.name}", id_='unidad-nombre-fuera-convencion-nnn-slug')
        continue
    nnn = carpeta.name[:3]
    if nnn in numeros:
        fail(f"NNN duplicado: {carpeta.name} y {numeros[nnn]}", id_='nnn-duplicado')
    numeros[nnn] = carpeta.name
    spec = carpeta / "especificacion.md"
    fm = frontmatter(spec)
    if fm is None:
        fail(f"{carpeta.name}: especificacion.md sin frontmatter válido", id_='especificacion-md-frontmatter-valido')
        continue
    faltan = CLAVES_FRONTMATTER - set(fm)
    if faltan:
        fail(f"{carpeta.name}: frontmatter sin claves {sorted(faltan)}", id_='frontmatter-claves')
    if fm.get("estado") not in ESTADOS_UNIDAD:
        fail(f"{carpeta.name}: estado '{fm.get('estado')}' fuera del vocabulario {sorted(ESTADOS_UNIDAD)}", id_='estado-fuera-vocabulario-estado')
    if fm.get("tipo") not in TIPOS:
        fail(f"{carpeta.name}: tipo '{fm.get('tipo')}' fuera del vocabulario", id_='tipo-fuera-vocabulario-tipo')
    if fm.get("carril") not in CARRILES:
        fail(f"{carpeta.name}: carril '{fm.get('carril')}' fuera del vocabulario", id_='carril-fuera-vocabulario-carril')
    if fm.get("estado") in EN_VUELO:
        spec_txt = spec.read_text(encoding="utf-8") if spec.exists() else ""
        if "## Plan de trabajo" not in spec_txt:
            fail(f"{carpeta.name}: en obra sin 'Plan de trabajo' en su especificacion (ADR-005)", id_='obra-plan-trabajo-especificacion-adr')
        # El contrato lo aprueba el usuario: estar en obra con 'aprobado: no' significa que
        # alguien se despachó a sí mismo. La única excepción es el hotfix P0, que deja marca
        # de deuda (y esa deuda la vigila revisar_deuda_hotfix con su propio reloj).
        if not aprobado_por_el_usuario(fm) and MARCA_DEUDA not in spec_txt:
            fail(f"{carpeta.name}: {fm.get('estado')} con 'aprobado: "
                 f"{fm.get('aprobado') or 'ausente'}' — se despachó SIN aprobación del usuario "
                 f"(el contrato lo aprueba él, no el agente)", id_='aprobado-despacho-aprobacion-usuario-contrato-aprueba')
    revisar_deuda_hotfix(carpeta.name, spec, fm)
    if fm.get("estado") == "mergeada":
        fail(f"{carpeta.name}: mergeada pero sin archivar (el cierre quedó a medias — re-ejecutar)", id_='mergeada-pero-archivar-cierre-quedo-medias')
    if not aprobado_por_el_usuario(fm) and not visto_por_visor_contratos(carpeta.name):
        warn(f"{carpeta.name}: contrato pendiente de aprobar y sin rastro del visor de "
             f"contratos — enséñaselo al usuario: {COMANDO_VISOR_CONTRATOS}", id_='contrato-pendiente-aprobar-rastro-visor-contratos')
    avisar_titulo_de_plantilla(carpeta.name, spec.read_text(encoding="utf-8") if spec.exists() else "")
    unidades[carpeta.name] = fm
    validar_origen_peticion(carpeta.name, fm)

# --- 4c. Bugs: docs/bugs/NNN-slug.md, fichero vivo por bug (ADR-006) ---
bugs_dir = RAIZ / "docs/bugs"
if bugs_dir.is_dir():
    indice_bugs = bugs_dir / "INDICE.md"
    texto_indice = indice_bugs.read_text(encoding="utf-8") if indice_bugs.exists() else ""
    for fichero in sorted(bugs_dir.glob("*.md")):
        nombre = fichero.stem
        if not re.match(r"^\d{3}", nombre):
            continue  # INDICE.md y ficheros de soporte: no son fichas de bug
        if not re.match(r"^\d{3}-[a-z0-9-]+$", nombre):
            fail(f"bug con nombre fuera de convención NNN-slug.md: bugs/{fichero.name}", id_='bug-nombre-fuera-convencion-nnn-slug')
            continue
        nnn = nombre[:3]
        if nnn in numeros:
            fail(f"NNN duplicado: bugs/{nombre} y {numeros[nnn]}", id_='nnn-duplicado-bugs')
        numeros[nnn] = f"bugs/{nombre}"
        fm = frontmatter(fichero)
        if fm is None:
            fail(f"bugs/{nombre}: sin frontmatter válido", id_='bugs-frontmatter-valido')
            continue
        if fm.get("tipo") != "bug":
            fail(f"bugs/{nombre}: tipo '{fm.get('tipo')}' (en docs/bugs/ solo tipo bug)", id_='bugs-tipo-docs-bugs-solo-tipo')
        if fm.get("estado") not in ESTADOS_UNIDAD:
            fail(f"bugs/{nombre}: estado '{fm.get('estado')}' fuera del vocabulario {sorted(ESTADOS_UNIDAD)}", id_='bugs-estado-fuera-vocabulario-estado')
        texto_bug = fichero.read_text(encoding="utf-8")
        if fm.get("estado") in EN_VUELO and not aprobado_por_el_usuario(fm) \
                and MARCA_DEUDA not in texto_bug:
            fail(f"bugs/{nombre}: {fm.get('estado')} con 'aprobado: "
                 f"{fm.get('aprobado') or 'ausente'}' — se despachó SIN aprobación del usuario "
                 f"(o, si fue producción caída, sin la marca de deuda del hotfix)", id_='bugs-aprobado-despacho-aprobacion-usuario-fue')
        revisar_deuda_hotfix(f"bugs/{nombre}", fichero, fm)
        if not aprobado_por_el_usuario(fm) and not visto_por_visor_contratos(nombre):
            warn(f"bugs/{nombre}: contrato pendiente de aprobar y sin rastro del visor de "
                 f"contratos — enséñaselo al usuario: {COMANDO_VISOR_CONTRATOS}", id_='bugs-contrato-pendiente-aprobar-rastro-visor')
        avisar_titulo_de_plantilla(nombre, texto_bug, prefijo="bugs/")
        # Un bug NO se archiva (ADR-006): `mergeada` es su estado final, así que nadie vuelve a
        # mirarlo después. Las dos puertas del paso 9 de runbooks/bug.md —evidencia rojo→verde
        # y OK del usuario— se comprueban aquí, sobre la ficha viva, o no se comprueban nunca.
        if fm.get("estado") in {"en_revision", "mergeada"}:
            rojo, verde = evidencia_rojo_verde(texto_bug)
            if not (rojo and verde):
                falta = " ni ".join(m for m, hay in (("ROJO (§2)", rojo), ("VERDE (§5)", verde))
                                    if not hay)
                fail(f"bugs/{nombre}: {fm.get('estado')} sin el output {falta} pegado en la "
                     f"ficha — el par ROJO→VERDE del MISMO test es la única prueba de que se "
                     f"arregló ESTE bug (bug.md paso 9: evidencia, no afirmación)", id_='bugs-output-pegado-ficha-par-rojoverde')
        if fm.get("estado") == "mergeada" and not validado_por_el_usuario(texto_bug):
            fail(f"bugs/{nombre}: mergeada sin 'Validación del usuario: OK' en la sección de "
                 f"cierre — un bug no está cerrado hasta que el USUARIO lo valida sobre una "
                 f"instancia corriendo; sin ese OK el bug sigue ABIERTO (bug.md, hard-gate "
                 f"del paso 9)", id_='mergeada-sin-ok')
        # El alta en el índice la hace el padre al reportar el bug: una ficha fuera del índice
        # es un bug invisible para quien solo mira docs/bugs/INDICE.md. WARN, no FAIL: el bug
        # existe y está bien escrito; lo que falta es su línea en el índice.
        if nombre not in texto_indice:
            warn(f"bugs/{nombre}: no aparece en docs/bugs/INDICE.md (el padre da de alta el "
                 f"bug en el índice al reportarlo: una línea con NNN, ficha, severidad, "
                 f"triaje y estado)", id_='bugs-aparece-docs-bugs-indice-md')
        unidades[nombre] = fm  # mismo censo: tope en vuelo, ficheros disjuntos y worktrees
        validar_origen_peticion(nombre, fm, clase="bug")

revisar_cola_peticiones()

if unidades:
    ok(f"{len(unidades)} unidad(es) activas con frontmatter válido")
else:
    ok("sin unidades activas")

# --- 4b. Trabajo en vuelo: tope y ownership disjunto ---
activas = {n: fm for n, fm in unidades.items() if fm.get("estado") in {"en_obra", "en_revision"}}
# Bug 061 / ADR-027: sin tope numérico. Lo que bloquea es compartir ficheros declarados
# (comprobado justo debajo); el número de unidades en vuelo solo se informa.
if len(activas) > 1:
    warn(f"{len(activas)} unidades en vuelo (default 1; en paralelo solo sin ficheros compartidos "
         f"y pedido por el usuario, ADR-027): {sorted(activas)}", id_='unidades-vuelo-default-paralelo-solo-ficheros')


def ficheros_de(fm):
    """Rutas declaradas por una unidad, normalizadas. Misma implementación que unidad.py.

    Se comparan conjuntos de CADENAS, así que sin normalizar `api/x.py`, `./api/x.py` y
    `API/x.py` son tres ficheros distintos para el linter y el mismo en disco: dos unidades
    paralelas podían poseer el mismo fichero sin que nadie lo viera.
    """
    crudos = (fm.get("ficheros") or "").strip("[]").split(",")
    limpias = set()
    for crudo in crudos:
        ruta = crudo.strip().strip("'\"")
        if not ruta:
            continue
        limpias.add(posixpath.normpath(ruta.replace("\\", "/")).casefold())
    return limpias


# Esperando al usuario: ni en vuelo ni cerradas (ADR-010). Se dicen en CADA arranque, porque
# una unidad que espera a una persona es justo la que se olvida.
esperando = sorted(n for n, fm in unidades.items() if fm.get("estado") == "en_validacion")
if esperando:
    warn(f"{len(esperando)} unidad(es) en_validacion (fusionadas, esperando a que el usuario "
         f"pruebe la app): {esperando} — termínalas con `unidad.py cerrar NNN-slug "
         f"--ok-usuario FECHA` en cuanto dé el OK", id_='unidad-validacion-fusionadas-esperando-usuario-pruebe')


nombres_activas = sorted(activas)
for i, a in enumerate(nombres_activas):
    for b in nombres_activas[i + 1:]:
        comunes = ficheros_de(activas[a]) & ficheros_de(activas[b])
        if comunes:
            fail(f"{a} y {b} comparten ficheros declarados: {sorted(comunes)} "
                 "(paralelas jamás comparten)", id_='unidades-paralelas-comparten-ficheros', sujeto="taller",
                 ruta="docs/05-trabajo", instancia="+".join(sorted((a, b))))

# --- 5. Worktrees ↔ unidades (huérfanos y zombis) ---
worktrees = RAIZ / "worktrees"
wt = {p.name for p in worktrees.iterdir() if p.is_dir()} if worktrees.is_dir() else set()
en_obra = {
    n for n, fm in unidades.items()
    if fm.get("estado") in {"en_obra", "en_revision"}
    and fm.get("ejecucion") != "documental"
}
# cmd_cerrar archiva la ficha ANTES de correr este linter y ANTES de borrar el worktree
# (orden necesario para poder restaurar los tres a la vez si el linter bloquea). En esa
# ventana intermedia la unidad ya no está en `unidades` (que se salta archivo/): sin
# distinguir este caso, un cierre legítimo se ve como huérfano y se revierte a sí mismo
# (bug 003). PERO archivar no garantiza que el worktree se borrara: si `borrar_worktree`
# falla (proceso vivo dentro, error de git), `cmd_cerrar` solo avisa y sigue — sin FAIL
# aquí ese resto quedaría invisible PARA SIEMPRE (revisión ronda 1 del bug 003). Por eso
# una unidad archivada con worktree en disco no es un OK silencioso: es un WARN que no
# bloquea el cierre en curso pero tampoco se pierde si el borrado de verdad falló.
archivo = RAIZ / "docs/05-trabajo/archivo"
archivadas = {p.name for p in archivo.iterdir() if p.is_dir()} if archivo.is_dir() else set()
huerfanos_reales = wt - set(unidades) - archivadas
huerfanos_archivados = (wt - set(unidades)) & archivadas
for h in sorted(huerfanos_reales):
    fail(f"worktree huérfano sin unidad: worktrees/{h} (¿cierre a medias?)", id_='worktree-huerfano-unidad-worktrees-cierre-medias')
for h in sorted(huerfanos_archivados):
    warn(f"worktrees/{h}: su unidad ya está archivada pero el worktree sigue en disco — "
         f"bórralo a mano si el cierre no pudo hacerlo (o es la ventana normal de un cierre en curso)", id_='worktrees-unidad-ya-archivada-pero-worktree')
for z in sorted(en_obra - wt):
    warn(f"unidad {z} en obra sin worktree (¿aún no despachada de verdad?)", id_='unidad-obra-worktree-aun-despachada-verdad')
if wt and not huerfanos_reales and not huerfanos_archivados:
    ok(f"worktrees coherentes con unidades: {sorted(wt)}")
elif not wt:
    ok("sin worktrees")

# --- 5b. Trabajo huérfano: que las casillas `[x]` no sean la única prueba de que existe ---
# Un constructor se queda sin contexto, se cancela o petan sus llamadas: eso pasa en todos los
# proyectos. Hasta aquí el método tenía dos señales de progreso —las casillas del plan y
# hallazgos.md— y NINGUNA se cruzaba con el disco: una unidad podía declararse terminada con
# todo el código sin commitear dentro de su worktree, que es la única forma de perder trabajo
# de verdad (nada más lo respalda). Estas dos comprobaciones cruzan las dos señales con git.
repo_cod, rama_principal = repo_codigo()
hay_repo = git(repo_cod, "rev-parse", "--is-inside-work-tree")[0] == 0
for nombre in sorted(en_obra):
    estado_unidad = unidades[nombre].get("estado")
    if nombre in wt:
        codigo, salida = git(worktrees / nombre, "status", "--porcelain")
        if codigo == 0 and salida:
            sucios = len(salida.splitlines())
            aviso = (f"{nombre}: {sucios} fichero(s) sin commitear en worktrees/{nombre} — "
                     f"un worktree es lo ÚNICO que no respalda nadie")
            if estado_unidad == "en_revision":
                fail(f"{aviso}. Una unidad que se declara terminada y no ha commiteado nada "
                     f"no ha terminado: recupera el trabajo antes de cerrar", id_='unidad-declara-terminada-ha-commiteado-nada')
            else:
                warn(f"{aviso}: pide commits al constructor", id_='pide-commits-constructor')
    if estado_unidad == "en_revision" and hay_repo:
        # Una unidad en_revision se declara TERMINADA y esperando merge. Lo primero es que su
        # trabajo exista en algún sitio: la rama local es lo normal, `origin/<unidad>` es lo
        # que sobrevive a un `git branch -D` (por eso el cierre ya no la borra) y `fusion:` es
        # el commit que el propio cierre anotó al comprobar el merge. Sin ninguna de las tres,
        # lo que hay es una ficha diciendo "hecho" sobre un trabajo que ya no existe.
        def existe(ref):
            return git(repo_cod, "rev-parse", "--verify", "--quiet", ref)[0] == 0

        tiene_local = existe(f"refs/heads/{nombre}")
        tiene_remota = existe(f"refs/remotes/origin/{nombre}")
        anotada = (unidades[nombre].get("fusion") or "").strip()
        if not (tiene_local or tiene_remota or anotada):
            fail(f"{nombre}: en_revision y NO queda rastro de su trabajo — ni la rama "
                 f"{nombre}, ni origin/{nombre}, ni un 'fusion:' anotado en su ficha. Una "
                 f"rama que no existe no prueba que se fusionara: prueba que alguien la "
                 f"borró. Búscala con `git -C {repo_cod.name} reflog` antes de tocar nada; si "
                 f"aparece, recupérala con `git -C {repo_cod.name} branch {nombre} <sha>`", id_='revision-queda-rastro-trabajo-rama-origin')
        elif tiene_local:
            codigo, salida = git(repo_cod, "rev-list", "--count", f"{rama_principal}..{nombre}")
            if codigo == 0 and salida.strip() == "0":
                # 0 commits por encima también es la foto DESPUÉS de un fast-forward: la
                # rama quedó contenida en la principal y la unidad espera validación. Si la
                # bitácora acredita el merge (fusion: anotado y ese commit dentro de la
                # principal), no hay constructor muerto que denunciar (incidente
                # incidente de campo, 06-08: FAIL precisamente por haber fusionado).
                acreditada = anotada and git(
                    repo_cod, "merge-base", "--is-ancestor", anotada, rama_principal
                )[0] == 0
                if not acreditada:
                    fail(f"{nombre}: en_revision y su rama no tiene NI UN commit por encima "
                         f"de {rama_principal} — no hay nada que revisar ni que mergear (¿el "
                         f"constructor murió a mitad?). Si en realidad ya se fusionó, la "
                         f"ficha debe acreditarlo con su 'fusion: <sha>'", id_='revision-rama-tiene-commit-encima-nada')

# --- 6. Archivo: lo archivado debe estar mergeada/descartada ---
archivo = trabajo / "archivo"
for carpeta in sorted(p for p in archivo.iterdir() if p.is_dir()) if archivo.is_dir() else []:
    spec_archivada = carpeta / "especificacion.md"
    fm = frontmatter(spec_archivada)
    if fm and fm.get("estado") not in {"mergeada", "descartada"}:
        fail(f"archivo/{carpeta.name}: archivada con estado '{fm.get('estado')}' (solo mergeada/descartada)", id_='archivo-archivada-estado-solo-mergeada-descartada')
    if fm and spec_archivada.exists():
        revisar_deuda_hotfix(f"archivo/{carpeta.name}", spec_archivada, fm)
        validar_origen_peticion(carpeta.name, fm, archivada=True)

# --- 6b. Cosecha de hallazgos en unidades archivadas ---
# Convención: en el cierre, el padre marca CADA viñeta de "Descubrimientos" y "Trabajo
# descubierto" con "→ promovido a <destino>" o "→ descartado (motivo)". Está escrita en
# plantillas/hallazgos.md, que es el fichero que uno tiene DELANTE mientras escribe: una
# convención que solo vive dentro de este script es una convención que nadie puede cumplir.
# Se mira la viñeta ENTERA (su línea más las indentadas que la continúan) y se tolera el
# énfasis markdown, porque `→ **promovido a** X` es como se escribe de verdad en un markdown.
# Misma implementación que en unidad.py, a propósito: los scripts del método son autónomos.
RE_COSECHA = re.compile(r"→\s*\**\s*(promovido|descartado)", re.IGNORECASE)


def hallazgos_sin_cosechar(texto):
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


def promociones_sin_peticion(texto):
    """Trabajo descubierto aceptado debe promoverse primero al inbox, nunca a memoria."""
    pendientes, en_seccion, bloque = 0, False, None

    def cerrar_bloque():
        nonlocal pendientes, bloque
        if bloque:
            entero = "\n".join(bloque)
            if re.search(r"→\s*\**\s*promovido", entero, re.I) \
                    and not re.search(r"P-\d{8}-[a-f0-9]{8}", entero):
                pendientes += 1
        bloque = None

    for linea in texto.splitlines():
        if linea.startswith("#"):
            cerrar_bloque()
            en_seccion = linea.lstrip("#").strip().startswith("Trabajo descubierto")
        elif en_seccion and re.match(r"^[-*]\s+\S", linea):
            cerrar_bloque()
            bloque = [linea]
        elif bloque is not None and re.match(r"^\s+\S", linea):
            bloque.append(linea)
        elif linea.strip():
            cerrar_bloque()
    cerrar_bloque()
    return pendientes


for carpeta in sorted(p for p in archivo.iterdir() if p.is_dir()) if archivo.is_dir() else []:
    ruta_hallazgos = carpeta / "hallazgos.md"
    if not ruta_hallazgos.exists():
        continue
    pendientes = hallazgos_sin_cosechar(ruta_hallazgos.read_text(encoding="utf-8"))
    if pendientes:
        warn(f"archivo/{carpeta.name}: {pendientes} hallazgo(s) sin cosechar. Formato exacto: "
             f"'→ promovido a <destino>' o '→ descartado (motivo)', en cualquier punto de la "
             f"viñeta (admite negrita). El ejemplo está en plantillas/hallazgos.md", id_='archivo-hallazgo-s-cosechar-formato-exacto')
    sin_pid = promociones_sin_peticion(ruta_hallazgos.read_text(encoding="utf-8"))
    if sin_pid:
        huerfano(
            carpeta.name,
            "unidad",
            f"{sin_pid} trabajo(s) descubierto(s) marcado(s) como promovido sin P-ID",
        )

# --- 7. Que un secreto no se hornee dentro de una imagen ---
# El método invierte mucho en que los secretos no se MUESTREN (regla de oro: nunca secretos
# ni PII) y nada en que no se PUBLIQUEN dentro de un artefacto. Es el mismo fallo por otro
# canal: un Dockerfile con `COPY . .` —que es lo que sale por defecto— mete el `.env` que el
# propio método exige tener ahí al lado dentro de una capa de la imagen, y de ahí no se borra.
# Solo se comprueba si el proyecto usa contenedores: para los demás, esta sección no existe.
IGNORAR_IMAGEN = (".env",)
for etiqueta, carpeta in ([("main", RAIZ / "main")]
                          + [(f"worktrees/{p.name}", p)
                             for p in (sorted(worktrees.iterdir()) if worktrees.is_dir() else [])
                             if p.is_dir()]):
    if not (carpeta / "Dockerfile").is_file():
        continue
    ignore = carpeta / ".dockerignore"
    if not ignore.is_file():
        fail(f"{etiqueta}/ tiene Dockerfile y NO tiene .dockerignore: el primer build hornea "
             f"el .env (y .git, y la base de datos local) dentro de la imagen. Créalo antes "
             f"de construir nada, con .env, la carpeta del entorno, .git/ y los datos locales", id_='dockerignore-ausente')
    else:
        contenido = ignore.read_text(encoding="utf-8")
        faltan = [p for p in IGNORAR_IMAGEN if p not in contenido]
        if faltan:
            fail(f"{etiqueta}/.dockerignore no menciona {faltan}: los secretos acabarían "
                 f"dentro de la imagen", id_='dockerignore-incompleto')
        else:
            ok(f"{etiqueta}/: Dockerfile con .dockerignore que excluye el .env")

# --- 7a-bis. Matar procesos por nombre está prohibido en artefactos ejecutables ---
# En una máquina con varios agentes, un `pkill -f` o un `killall` de un script mata trabajo
# ajeno (pasó: suites paralelas compartiendo máquina). Se mata por PID registrado, nunca por
# nombre. Solo se miran artefactos ejecutables del repo de código: la prosa puede discutirlo.
PATRONES_KILL = ("pkill -f", "killall ")
artefactos_kill = []
if repo_cod.is_dir():
    for rel in ("scripts", ".github/workflows"):
        base = repo_cod / rel
        if base.is_dir():
            artefactos_kill += [p for p in base.rglob("*") if p.is_file()]
    artefactos_kill += [repo_cod / n for n in ("Makefile", "makefile", "package.json")
                        if (repo_cod / n).is_file()]
culpables_kill = []
for artefacto in artefactos_kill:
    relativa = artefacto.relative_to(RAIZ).as_posix()
    for numero, linea in enumerate(
        artefacto.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
    ):
        ejecutable = linea.split("#", 1)[0]
        if any(patron in ejecutable for patron in PATRONES_KILL):
            culpables_kill.append((relativa, numero))
if culpables_kill:
    for relativa, numero in sorted(culpables_kill):
        fail(f"pkill -f / killall en {relativa}: eso mata procesos de otros "
             f"agentes o proyectos que compartan la máquina. Guarda el PID al lanzar y mata "
             f"ese PID exacto", id_='pkill', ruta=relativa, instancia=f"linea:{numero}")
else:
    ok("sin pkill -f ni killall en scripts, workflows ni Makefile del repo de código")

# --- 7b. El CI real es guía, no gate (ADR-028 aplica ADR-026 a este control) ---
# Ausencia de CI no pierde trabajo, no pisa producción, no filtra secretos ni absorbe
# cambios ajenos: por la regla de ADR-026 nunca debió ser un fail(). Quien SÍ quiera
# materializar su CI sigue teniendo el mismo detalle de qué falta o está mal formado.
PIEZAS_CI = (
    "scripts/ci/full-suite", "scripts/ci/lint", "scripts/ci/security",
    ".github/workflows/tests.yml", ".github/workflows/quality-security.yml",
    ".github/dependabot.yml",
)
presentes_ci = [ruta for ruta in PIEZAS_CI if (repo_cod / ruta).is_file()]
lint_ci = RAIZ / "docs/00-metodo/scripts/lint_ci.py"
if not lint_ci.is_file():
    warn("no se pudo comprobar el contrato de CI: falta "
         "docs/00-metodo/scripts/lint_ci.py", id_='pudo-comprobar-contrato-ci-falta-docs')
elif not hay_repo:
    warn(f"no se pudo comprobar el contrato de CI: el repo de código ({repo_cod}) "
         "no existe o no es un repositorio git", id_='pudo-comprobar-contrato-ci-repo-codigo')
else:
    requiere_e2e = planos_declaran_e2e()
    opciones_ci = [sys.executable, str(lint_ci), "--repo", str(repo_cod)]
    if requiere_e2e:
        opciones_ci.append("--require-e2e")
    resultado_ci = subprocess.run(
        opciones_ci,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    # lint_ci.py degrada el contrato-ausente a WARN con exit 0 (029): ese caso deja de
    # tener un returncode≠0 que delatarlo, y se reconoce por el marcador `DEUDA-CI:` que
    # imprime en su lugar. returncode≠0 sigue significando FAIL real (contrato parcial).
    deuda_sin_materializar = "DEUDA-CI:" in resultado_ci.stdout
    if (presentes_ci or requiere_e2e) and resultado_ci.returncode:
        warn("la materialización del CI está incompleta; ejecuta "
             "`python3 docs/00-metodo/scripts/lint_ci.py --repo main"
             f"{' --require-e2e' if requiere_e2e else ''}` para ver el detalle", id_='materializacion-ci-incompleta-ejecuta-python3-docs')
    elif presentes_ci:
        ok("contrato CI materializado y completo")
    elif resultado_ci.returncode or deuda_sin_materializar:
        warn("CI real aún sin materializar: en brownfield debe ser la primera unidad técnica "
             "tras la adopción; en proyectos nuevos nace con el esqueleto", id_='ci-real-aun-materializar-brownfield-debe')
    else:
        ok("repo de código todavía vacío: el CI nacerá cuando se conozca el stack")

# --- 7c. Git sabe quién eres, y este repo tiene historia ---
# El bootstrap avisa una vez si no pudo cerrar el commit inicial (falta identidad de git en la
# máquina) y ese aviso se pierde entre veinte líneas de salida. Después, durante días, todo
# parece normal: los commits fallan en silencio, cada uno en su comando, hasta que alguien va
# a hacer push y se estrella. Un aviso de una vez no es una comprobación; esto sí, y se repite
# en cada arranque de sesión hasta que se arregla.
if git(RAIZ, "rev-parse", "--is-inside-work-tree")[0] == 0:
    identidad = [c for c in ("user.name", "user.email")
                 if not git(RAIZ, "config", "--get", c)[1].strip()]
    if identidad:
        fail(f"git no tiene {' ni '.join(identidad)} en esta máquina: ningún commit puede "
             f"completarse y cada intento falla por su cuenta, en silencio. Arréglalo antes "
             f'de trabajar: git config --global user.name "Tu Nombre" · '
             f'git config --global user.email "tu@correo"', id_='git-tiene-maquina-ningun-commit-puede')
    else:
        ok("git tiene identidad configurada (user.name y user.email)")
    if git(RAIZ, "rev-parse", "--verify", "--quiet", "HEAD")[0] != 0:
        fail("el meta-repo no tiene NI UN commit: el bootstrap no pudo cerrar el inicial y "
             "todo lo escrito desde entonces —planos, decisiones, unidades— vive sin respaldo "
             "de git. Configura la identidad y haz el commit inicial antes de seguir", id_='meta-repo-tiene-commit-bootstrap-pudo')
    else:
        ok("el meta-repo tiene historia (al menos un commit)")

# --- 8. ¿Existe este proyecto en algún sitio más que este disco? ---
# Un workspace sin remoto es un proyecto entero —planos, código e historial— viviendo en un
# único disco. Es la mayor pérdida posible del método, y hasta ahora no lo decía nadie: si al
# finalizar no se pidió GitHub, el asunto no se volvía a mencionar jamás. WARN y no FAIL
# porque quedarse en local es una decisión legítima; pero se dice en CADA arranque de sesión.
def sin_remoto(repo):
    return git(repo, "remote")[1].strip() == ""


if git(RAIZ, "rev-parse", "--is-inside-work-tree")[0] == 0 and sin_remoto(RAIZ):
    warn("el meta-repo no tiene remoto: los planos, las decisiones y todo el trabajo de "
         "documentación existen SOLO en este ordenador. Si el usuario creía que esto estaba "
         "en GitHub, díselo; para publicarlo: visor/finalizar.py --github <cuenta> desde la "
         "herramienta de ingeniería de requisitos", id_='meta-repo-tiene-remoto-planos-decisiones')
if hay_repo and sin_remoto(repo_cod):
    warn(f"el repo de código ({repo_cod.name}/) no tiene remoto: el código existe SOLO en "
         f"este ordenador y ningún push lo respalda", id_='repo-codigo-tiene-remoto-codigo-existe')

# --- 8b. Política de publicación: `push: usuario` (unidad 018) ---
# Cuando el workspace declara que publicar es cosa de la persona, la principal local por
# delante del remoto NO es un olvido: es el estado que el modo produce en cada cierre. Se
# informa con el conteo y el comando (mismo patrón que el WARN de `unidad.py cerrar`), pero
# como OK — convertirlo en WARN sería un rojo perpetuo que enseña a ignorar el linter.
if hay_repo and not sin_remoto(repo_cod):
    try:
        modo_push = repo_config.modo_push(RAIZ)
    except repo_config.RepoConfigError as exc:
        modo_push = "agente"
        fail(str(exc), id_='repo-codigo-error-interno', sujeto="taller", ruta="repos.yaml",
             instancia="repositorios-no-disponibles")
    if modo_push == "usuario":
        codigo, salida = git(repo_cod, "rev-list", "--count",
                             f"origin/{rama_principal}..{rama_principal}")
        pendientes = int(salida) if codigo == 0 and salida.isdigit() else 0
        if pendientes:
            ok(f"push: usuario — {pendientes} commit(s) de {rama_principal} sin publicar; "
               f"el método no los empuja. Cuando quieras: "
               f"git -C {repo_cod.name} push origin {rama_principal}")
        else:
            ok(f"push: usuario — {rama_principal} no tiene nada pendiente de publicar")

# --- 8c. Un bloqueo que no dice cómo salir es un defecto (unidad 049) ---
# Quien conduce el método es un agente: cuando un script rechaza sin nombrar la continuación,
# gasta un turno adivinando y a veces se inventa un rodeo que salta la puerta recién cerrada.
# `lint_salidas.py` inventaría con AST los puntos de rechazo de los scripts y aplica un
# TRINQUETE: la lista de los que hoy no nombran salida está congelada y solo puede encoger.
# Aquí, al arrancar y al cerrar (regla 13), para que un rechazo mudo NUEVO se vea el mismo día
# que se escribe y no tres meses después.
lint_salidas = RAIZ / "docs/00-metodo/scripts/lint_salidas.py"
carpeta_scripts = RAIZ / "docs/00-metodo/scripts"
baseline_salidas = RAIZ / "docs/00-metodo/salidas-baseline.json"
if not lint_salidas.is_file() or not baseline_salidas.is_file():
    # Falta una pieza del MÉTODO, no del proyecto: por ADR-026 avisa y no bloquea; el arreglo
    # llega por Modo D.
    warn("no se pudo comprobar que los rechazos nombren su salida: falta "
         "docs/00-metodo/scripts/lint_salidas.py o docs/00-metodo/salidas-baseline.json; "
         "actualiza el método con `python3 visor/actualizar.py revisar --todos` desde la "
         "herramienta de ingeniería de requisitos", id_='pudo-comprobar-rechazos-nombren-salida-falta')
else:
    resultado_salidas = subprocess.run(
        [sys.executable, str(lint_salidas), "--scripts", str(carpeta_scripts),
         "--base", str(baseline_salidas)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if resultado_salidas.returncode:
        # El trinquete SÍ muerde: o hay un rechazo mudo nuevo o una entrada dejó de casar.
        # Las dos cosas las decide quien acaba de editar el script, y las dos tienen comando.
        fail("hay rechazos que no nombran su salida y no estaban congelados; el detalle y las "
             "dos formas de arreglarlo salen en "
             "`python3 docs/00-metodo/scripts/lint_salidas.py`", id_='rechazos-sin-salida')
    else:
        ok("todo rechazo nuevo de los scripts nombra su salida (línea base sin crecer)")

# --- 8d. Lo que se rompe ENTRE dos piezas que por separado están bien (unidad 050) ---
# Este linter, sección a sección, mira hacia DENTRO: la raíz tiene la forma correcta, el árbol
# está congelado, los frontmatters cuadran. La única sección que mira una junta —worktrees
# contra unidades— es la que sigue cogiendo cosas reales. `lint_juntas.py` es el guardián de
# las otras tres juntas medidas: el vocabulario que comparten los scripts con la prosa, el tope
# de 250 líneas que el carril directo promete y nadie medía, y el inventario congelado de
# puertas duras con su dueño. Va aquí, al arrancar y al cerrar (regla 13), y no dentro de este
# fichero: son comprobaciones ENTRE piezas, y meterlas en el validador hacia dentro sería
# repetir el error que corrigen.
lint_juntas = RAIZ / "docs/00-metodo/scripts/lint_juntas.py"
inventario_puertas = RAIZ / "docs/00-metodo/puertas.json"
if not lint_juntas.is_file() or not inventario_puertas.is_file():
    # Falta una pieza del MÉTODO, no del proyecto: por ADR-026 avisa y no bloquea; el arreglo
    # llega por Modo D.
    warn("no se pudieron comprobar las juntas del método: falta "
         "docs/00-metodo/scripts/lint_juntas.py o docs/00-metodo/puertas.json; actualiza el "
         "método con `python3 visor/actualizar.py revisar --todos` desde la herramienta de "
         "ingeniería de requisitos", id_='pudieron-comprobar-juntas-metodo-falta-docs')
else:
    resultado_juntas = subprocess.run(
        [sys.executable, str(lint_juntas), "--raiz", str(RAIZ)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if resultado_juntas.returncode:
        fail("hay juntas del método que no cuadran (vocabulario, tope del carril directo o "
             "puertas duras sin dueño); el detalle y la salida de cada una salen en "
             "`python3 docs/00-metodo/scripts/lint_juntas.py`", id_='juntas-metodo-cuadran-vocabulario-tope-carril')
    else:
        ok("las tres juntas del método cuadran (vocabulario, tope directo, puertas con dueño)")

# --- 8e. La sanidad del workspace tiene fecha de caducidad (unidad 079, R-2405) ---
# `sanidad.py atraso` sabe desde la 059 cuántos cierres y cuántos días lleva el workspace sin
# medirse, pero nadie se lo preguntaba: el ejecutor existía y el aviso no. Se pregunta aquí,
# donde ya se mira todo al arrancar sesión y al cerrar, y se publica TAL CUAL lo que conteste
# —con su cuenta y su SALIDA:— para no tener dos maneras distintas de contar lo mismo (R3).
# Siempre WARN, nunca FAIL: la sanidad guía, no bloquea (ADR-026).
COMO_PASAR_SANIDAD = "python3 docs/00-metodo/scripts/sanidad.py medir --anotar"
sanidad_py = RAIZ / "docs/00-metodo/scripts/sanidad.py"
if not sanidad_py.is_file():
    # Falta una pieza del MÉTODO, no del proyecto: avisa y no bloquea (ADR-026).
    warn("no se pudo comprobar si la sanidad del workspace está atrasada: falta "
         "docs/00-metodo/scripts/sanidad.py; actualiza el método con "
         "`python3 visor/actualizar.py revisar --todos` desde la herramienta de ingeniería "
         f"de requisitos, o pásala a mano: {COMO_PASAR_SANIDAD}", id_='pudo-comprobar-sanidad-workspace-atrasada-falta')
else:
    resultado_sanidad = subprocess.run(
        [sys.executable, str(sanidad_py), "atraso"], cwd=str(RAIZ),
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    veredicto = next((l.strip() for l in (resultado_sanidad.stdout or "").splitlines()
                      if l.strip().startswith(("OK", "WARN"))), "")
    if resultado_sanidad.returncode or not veredicto:
        # `atraso` sin `--estricto` sale 0 aunque avise: un returncode≠0 (o una salida que no
        # empieza por OK/WARN) es que se rompió. Un solo WARN con el error y el lint sigue.
        detalle = ((resultado_sanidad.stderr or "").strip().splitlines()
                   or (resultado_sanidad.stdout or "").strip().splitlines() or ["sin salida"])[-1]
        warn(f"no se pudo comprobar si la sanidad del workspace está atrasada: {detalle} · "
             f"pásala a mano: {COMO_PASAR_SANIDAD}", id_='pudo-comprobar-sanidad-workspace-atrasada-pasala')
    elif veredicto.startswith("WARN"):
        # Ya viene con cierres, días y `SALIDA:`; se reenvía sin reescribir la cuenta.
        warn(veredicto[len("WARN"):].strip(), id_='warn')
    else:
        ok(veredicto[len("OK"):].strip())

# --- 9. Higiene ---
if (RAIZ / "codebase").exists():
    fail("codebase/ existe (estructura vieja: debe ser main/ + worktrees/)", id_='codebase-existe-estructura-vieja-debe-ser')

# --- Resultado ---
if MODO_JSON:
    print(json.dumps({"schema": "lint-hallazgos/v1", "hallazgos": hallazgos},
                     ensure_ascii=False, sort_keys=True))
else:
    print(f"\n{len(fallos)} FAIL · {len(avisos)} WARN")
sys.exit(1 if fallos else 0)
