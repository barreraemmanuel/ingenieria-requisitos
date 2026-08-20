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
fallos, avisos = [], []
HOY = datetime.date.today()


def ok(msg):
    print(f"  OK   {msg}")


def warn(msg):
    avisos.append(msg)
    print(f"  WARN {msg}")


def fail(msg):
    fallos.append(msg)
    print(f"  FAIL {msg}")


ESTADOS_UNIDAD = {"planificada", "en_obra", "en_revision", "en_validacion", "mergeada",
                  "bloqueada", "descartada"}
TIPOS = {"bug", "feature", "refactor", "migracion", "auditoria", "investigacion", "documentacion"}
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
             f"(hotfix.md: se paga ANTES de cerrar; borra la marca al completar la ficha)")
        return
    actualizado = (fm.get("actualizado") or "").strip()
    try:
        dias = (HOY - datetime.date.fromisoformat(actualizado)).days
    except ValueError:
        fail(f"{nombre}: deuda de hotfix con 'actualizado: {actualizado or 'ausente'}' "
             f"ilegible — sin fecha no hay plazo que valga")
        return
    if dias > 1:
        fail(f"{nombre}: DEUDA DE SPEC del hotfix sin pagar {dias} días después de "
             f"'actualizado: {actualizado}' (plazo: 24 h, hotfix.md). No se abre trabajo "
             f"nuevo que no sea otro hotfix hasta pagarla")
    else:
        warn(f"{nombre}: DEUDA DE SPEC del hotfix sin pagar (dentro del plazo de 24 h desde "
             f"{actualizado}): completa la ficha y borra la marca")


def repo_codigo():
    """Ruta y rama principal del repo de código, leídas de repos.yaml (igual que unidad.py)."""
    try:
        return repo_config.repo_code(RAIZ)
    except repo_config.RepoConfigError as exc:
        fail(str(exc))
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
        rutas.extend(
            mapa.parent / "actividades" / actividad["id"] / "planos.json"
            for actividad in raiz.get("actividades", [])
        )
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
    sin_reglas = texto.replace("<HARD-GATE>", "")
    if fm.get("proceso") != "deploy" or fm.get("estado") != "desplegado":
        return False
    if fm.get("etapa") not in {"0-local", "1-lan", "2-vps"}:
        return False
    if not fecha_iso_valida(fm.get("fecha", "")):
        return False
    if re.search(r"<[^>]+>|PENDIENTE|DESPLEGADO\s*\|", sin_reglas):
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
        fail(f"peticiones/LEGACY.json ilegible: {exc}")
        return {"formato": 1, "modo": "estricto", "unidades": [], "bugs": [], "ramas": []}
    if datos.get("formato") != 1 or datos.get("modo") not in {"observacion", "estricto"}:
        fail("peticiones/LEGACY.json exige formato 1 y modo observacion|estricto")
        datos["modo"] = "estricto"
    for clave in ("unidades", "bugs", "ramas"):
        if not isinstance(datos.get(clave), list):
            fail(f"peticiones/LEGACY.json: {clave} debe ser una lista exacta")
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
    (warn if LEGACY.get("modo") == "observacion" else fail)(mensaje)


def validar_origen_peticion(nombre, fm, clase="unidad"):
    referencias = referencias_peticion(fm)
    if not referencias:
        huerfano(nombre, clase)
        return
    for referencia in referencias:
        encontrada = RE_PETICION_REVISION.fullmatch(referencia)
        if not encontrada:
            fail(f"{nombre}: referencia de petición inválida '{referencia}' (usa P-ID@revision)")
            continue
        pid, revision = encontrada.groups()
        ruta = PETICIONES / pid / "peticion.json"
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            fail(f"{nombre}: petición inexistente {pid}")
            continue
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"{nombre}: no se puede leer {pid}: {exc}")
            continue
        if datos.get("revision") != int(revision):
            fail(f"{nombre}: {pid} está en revisión {datos.get('revision')}; "
                 f"la orden referencia revisión {revision}")
        tipo_proceso = "bug" if clase == "bug" else "unidad"
        enlazada = any(
            proceso.get("tipo") == tipo_proceso
            and proceso.get("ref") == nombre
            and proceso.get("revision") == int(revision)
            for proceso in datos.get("procesos", [])
        )
        if not enlazada:
            fail(f"{nombre}: {pid}@{revision} no enlaza de vuelta este proceso")


def revisar_cola_peticiones():
    if not PETICIONES.is_dir():
        fail("docs/05-trabajo/peticiones/ no existe")
        return
    for ruta in sorted(PETICIONES.glob("P-*/peticion.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"{ruta.parent.name}: peticion.json ilegible: {exc}")
            continue
        pid = datos.get("id") or ruta.parent.name
        if pid != ruta.parent.name:
            fail(f"{ruta.parent.name}: peticion.json declara id {pid}")
        for proceso in datos.get("procesos", []):
            tipo, ref = proceso.get("tipo"), proceso.get("ref", "?")
            esperado = CONTRATOS_PETICION.get(tipo)
            if not esperado or proceso.get("contrato_terminal") != esperado:
                fail(f"{pid}: proceso {tipo} {ref} sin contrato terminal canónico")
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
            elif tipo not in {"expres"}:
                candidata = Path(str(ref))
                if not candidata.is_absolute() and ".." not in candidata.parts:
                    resuelta = (RAIZ / candidata).resolve()
                    if resuelta.is_file() and RAIZ.resolve() in resuelta.parents:
                        canonica = resuelta
                if tipo == "deploy":
                    esperada = re.fullmatch(
                        r"docs/(?:05-trabajo|bugs)/\d{3}-[a-z0-9][a-z0-9-]*/despliegue\.md",
                        str(ref),
                    )
                    if canonica is None or not esperada:
                        canonica = None
                if tipo == "flujos" and ref != "docs/02-flujos/planos/aprobacion.json":
                    canonica = None
                if tipo == "investigacion" and ref != "docs/03-investigacion/SINTESIS.md":
                    canonica = None
            if tipo != "expres" and canonica is None:
                fail(f"{pid}: proceso {tipo} inexistente: {ref}")
                continue
            if proceso.get("estado") == "terminal" and tipo in {"unidad", "bug", "auditoria"}:
                fm = frontmatter(canonica) or {}
                if fm.get("estado") != "mergeada":
                    fail(
                        f"{pid}: proceso terminal {tipo} {ref}, pero su artefacto está "
                        f"{fm.get('estado') or 'sin estado'}"
                    )
            if proceso.get("estado") == "terminal" and tipo == "deploy" and canonica:
                if not ficha_deploy_terminal_valida(canonica):
                    fail(f"{pid}: deploy {ref} terminal sin ficha desplegada y completa")
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
                    fail(f"{pid}: flujos terminal sin recibo aprobado")
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
                    fail(
                        f"{pid}: investigación terminal sin al menos 10 informes "
                        "y síntesis completa"
                    )
            if proceso.get("estado") == "terminal" and tipo == "expres":
                repo, principal = repo_codigo()
                metadata = proceso.get("metadata") or {}
                if not rama_fusionada(repo, ref, principal, metadata):
                    fail(f"{pid}: exprés terminal sin cambio fusionado en {principal}")
        abiertos = [
            proceso.get("ref", "?")
            for proceso in datos.get("procesos", [])
            if proceso.get("relacion") == "satisface"
            and proceso.get("revision") == datos.get("revision")
            and proceso.get("estado") not in {"terminal", "sustituido", "cancelado"}
        ]
        if datos.get("estado") in {"cerrada", "cancelada"} and abiertos:
            fail(f"{pid}: {datos.get('estado')} con proceso abierto: {', '.join(abiertos)}")
        satisface = [
            proceso for proceso in datos.get("procesos", [])
            if proceso.get("relacion") == "satisface"
            and proceso.get("revision") == datos.get("revision")
            and proceso.get("estado") != "sustituido"
        ]
        if datos.get("resultado") == "entregada" and not satisface:
            fail(f"{pid}: entregada sin ningún proceso que la satisfaga")
        # ADR-030: un enfoque abandonado se marca `cancelado` (con motivo, autor y fecha)
        # y no debe dejar la peticion en FAIL para siempre. Los mismos tres estados que ya
        # tratan como acabados la comprobacion de `abiertos` doce lineas mas arriba y
        # peticion.py en sus tres filtros. Lo que SI debe seguir fallando es un proceso
        # vivo (`evaluando`, `en obra`): esa garantia queda entera.
        ACABADOS = {"terminal", "sustituido", "cancelado"}
        if datos.get("resultado") == "entregada" and any(
            proceso.get("estado") not in ACABADOS for proceso in satisface
        ):
            fail(f"{pid}: entregada con procesos no terminales")
        if datos.get("estado") in {"capturada", "evaluando"}:
            warn(f"{pid}: {datos.get('estado')} sin siguiente proceso; evaluar o aparcar")
        if datos.get("estado") == "aparcada":
            revisar_el = (datos.get("aparcada") or {}).get("revisar_el")
            try:
                vencida = bool(revisar_el) and datetime.date.fromisoformat(revisar_el) <= HOY
            except ValueError:
                fail(f"{pid}: fecha de revisión aparcada ilegible: {revisar_el}")
                vencida = False
            if vencida:
                warn(f"{pid}: aparcada vencida desde {revisar_el}; reanudar, cancelar o reprogramar")


print("== Linter del método ==")

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
         "(lo escribe el bootstrap; recupéralo con `git checkout -- METODO.json`)")
else:
    try:
        datos_metodo = json.loads(metodo_json.read_text(encoding="utf-8"))
        if not isinstance(datos_metodo, dict):
            raise ValueError("no es un objeto JSON")
    except (OSError, ValueError) as exc:
        fail(f"METODO.json ilegible ({exc}): sin él no se puede verificar el arsenal del método")
        datos_metodo = None
    if datos_metodo is not None:
        archivos_metodo = datos_metodo.get("archivos") or []
        if not archivos_metodo:
            warn("METODO.json sin la lista `archivos`: el arsenal del método queda sin "
                 "vigilar hasta repartir el método actualizado (Modo D de la herramienta)")
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
                     "el Modo D de la herramienta")
            else:
                ok(f"arsenal del método completo ({len(archivos_metodo)} ficheros presentes "
                   f"y con contenido)")

# --- 1. Raíz: ficheros y tope de tamaño del router ---
agents = RAIZ / "AGENTS.md"
if not agents.exists():
    fail("AGENTS.md no existe")
else:
    n = len(agents.read_text(encoding="utf-8").splitlines())
    if n > 160:
        fail(f"AGENTS.md tiene {n} líneas (tope 160): el router está engordando")
    else:
        ok(f"AGENTS.md existe ({n} líneas ≤ 160)")

for puente in ("CLAUDE.md", "GEMINI.md"):
    ruta_puente = RAIZ / puente
    contenido_puente = ruta_puente.read_text(encoding="utf-8") if ruta_puente.exists() else ""
    lineas_esperadas = ("@AGENTS.md\n", "@AGENTS.md\n@.claude/personalidad.md\n")
    if contenido_puente not in lineas_esperadas:
        fail(f"{puente} debe redirigir a AGENTS.md (y opcionalmente a .claude/personalidad.md)")
    else:
        ok(f"{puente} redirige directamente a AGENTS.md")

# --- 2. El árbol congelado ---
for d in sorted(DOCS_PERMITIDOS):
    if not (RAIZ / "docs" / d).is_dir():
        fail(f"falta docs/{d}/ (árbol congelado, ver ADR/estructura)")
extras = {p.name for p in (RAIZ / "docs").iterdir() if p.is_dir()} - DOCS_PERMITIDOS
if extras:
    fail(f"directorios NO permitidos en docs/ (cambiar la estructura exige ADR): {sorted(extras)}")
else:
    ok("docs/ contiene exactamente el árbol congelado")

# --- 3. ESTADO.md: existe y no engorda ---
estado_md = RAIZ / "docs/05-trabajo/ESTADO.md"
if not estado_md.exists():
    fail("docs/05-trabajo/ESTADO.md no existe")
else:
    n = len(estado_md.read_text(encoding="utf-8").splitlines())
    (ok if n <= 100 else fail)(f"ESTADO.md: {n} líneas {'≤ 100' if n <= 100 else '> 100 (es un digest, no un archivo)'}")

# --- 4. Unidades: nombre, frontmatter, vocabulario, coherencia ---
trabajo = RAIZ / "docs/05-trabajo"
unidades, numeros = {}, {}
for carpeta in sorted(trabajo.iterdir()):
    if not carpeta.is_dir() or carpeta.name in {"archivo", "peticiones"}:
        continue
    if not re.match(r"^\d{3}-[a-z0-9-]+$", carpeta.name):
        fail(f"unidad con nombre fuera de convención NNN-slug: {carpeta.name}")
        continue
    nnn = carpeta.name[:3]
    if nnn in numeros:
        fail(f"NNN duplicado: {carpeta.name} y {numeros[nnn]}")
    numeros[nnn] = carpeta.name
    spec = carpeta / "especificacion.md"
    fm = frontmatter(spec)
    if fm is None:
        fail(f"{carpeta.name}: especificacion.md sin frontmatter válido")
        continue
    faltan = CLAVES_FRONTMATTER - set(fm)
    if faltan:
        fail(f"{carpeta.name}: frontmatter sin claves {sorted(faltan)}")
    if fm.get("estado") not in ESTADOS_UNIDAD:
        fail(f"{carpeta.name}: estado '{fm.get('estado')}' fuera del vocabulario {sorted(ESTADOS_UNIDAD)}")
    if fm.get("tipo") not in TIPOS:
        fail(f"{carpeta.name}: tipo '{fm.get('tipo')}' fuera del vocabulario")
    if fm.get("carril") not in CARRILES:
        fail(f"{carpeta.name}: carril '{fm.get('carril')}' fuera del vocabulario")
    if fm.get("estado") in EN_VUELO:
        spec_txt = spec.read_text(encoding="utf-8") if spec.exists() else ""
        if "## Plan de trabajo" not in spec_txt:
            fail(f"{carpeta.name}: en obra sin 'Plan de trabajo' en su especificacion (ADR-005)")
        # El contrato lo aprueba el usuario: estar en obra con 'aprobado: no' significa que
        # alguien se despachó a sí mismo. La única excepción es el hotfix P0, que deja marca
        # de deuda (y esa deuda la vigila revisar_deuda_hotfix con su propio reloj).
        if not aprobado_por_el_usuario(fm) and MARCA_DEUDA not in spec_txt:
            fail(f"{carpeta.name}: {fm.get('estado')} con 'aprobado: "
                 f"{fm.get('aprobado') or 'ausente'}' — se despachó SIN aprobación del usuario "
                 f"(el contrato lo aprueba él, no el agente)")
    revisar_deuda_hotfix(carpeta.name, spec, fm)
    if fm.get("estado") == "mergeada":
        fail(f"{carpeta.name}: mergeada pero sin archivar (el cierre quedó a medias — re-ejecutar)")
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
            fail(f"bug con nombre fuera de convención NNN-slug.md: bugs/{fichero.name}")
            continue
        nnn = nombre[:3]
        if nnn in numeros:
            fail(f"NNN duplicado: bugs/{nombre} y {numeros[nnn]}")
        numeros[nnn] = f"bugs/{nombre}"
        fm = frontmatter(fichero)
        if fm is None:
            fail(f"bugs/{nombre}: sin frontmatter válido")
            continue
        if fm.get("tipo") != "bug":
            fail(f"bugs/{nombre}: tipo '{fm.get('tipo')}' (en docs/bugs/ solo tipo bug)")
        if fm.get("estado") not in ESTADOS_UNIDAD:
            fail(f"bugs/{nombre}: estado '{fm.get('estado')}' fuera del vocabulario {sorted(ESTADOS_UNIDAD)}")
        texto_bug = fichero.read_text(encoding="utf-8")
        if fm.get("estado") in EN_VUELO and not aprobado_por_el_usuario(fm) \
                and MARCA_DEUDA not in texto_bug:
            fail(f"bugs/{nombre}: {fm.get('estado')} con 'aprobado: "
                 f"{fm.get('aprobado') or 'ausente'}' — se despachó SIN aprobación del usuario "
                 f"(o, si fue producción caída, sin la marca de deuda del hotfix)")
        revisar_deuda_hotfix(f"bugs/{nombre}", fichero, fm)
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
                     f"arregló ESTE bug (bug.md paso 9: evidencia, no afirmación)")
        if fm.get("estado") == "mergeada" and not validado_por_el_usuario(texto_bug):
            fail(f"bugs/{nombre}: mergeada sin 'Validación del usuario: OK' en la sección de "
                 f"cierre — un bug no está cerrado hasta que el USUARIO lo valida sobre una "
                 f"instancia corriendo; sin ese OK el bug sigue ABIERTO (bug.md, hard-gate "
                 f"del paso 9)")
        # El alta en el índice la hace el padre al reportar el bug: una ficha fuera del índice
        # es un bug invisible para quien solo mira docs/bugs/INDICE.md. WARN, no FAIL: el bug
        # existe y está bien escrito; lo que falta es su línea en el índice.
        if nombre not in texto_indice:
            warn(f"bugs/{nombre}: no aparece en docs/bugs/INDICE.md (el padre da de alta el "
                 f"bug en el índice al reportarlo: una línea con NNN, ficha, severidad, "
                 f"triaje y estado)")
        unidades[nombre] = fm  # mismo censo: tope en vuelo, ficheros disjuntos y worktrees
        validar_origen_peticion(nombre, fm, clase="bug")

revisar_cola_peticiones()

if unidades:
    ok(f"{len(unidades)} unidad(es) activas con frontmatter válido")
else:
    ok("sin unidades activas")

# --- 4b. Trabajo en vuelo: tope y ownership disjunto ---
activas = {n: fm for n, fm in unidades.items() if fm.get("estado") in {"en_obra", "en_revision"}}
if len(activas) > 3:
    fail(f"{len(activas)} unidades en vuelo (tope absoluto 3, default 1): {sorted(activas)}")
elif len(activas) > 1:
    warn(f"{len(activas)} unidades en vuelo (default 1; 2-3 solo sin ficheros compartidos y pedido por el usuario)")


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
         f"--ok-usuario FECHA` en cuanto dé el OK")


nombres_activas = sorted(activas)
for i, a in enumerate(nombres_activas):
    for b in nombres_activas[i + 1:]:
        comunes = ficheros_de(activas[a]) & ficheros_de(activas[b])
        if comunes:
            fail(f"{a} y {b} comparten ficheros declarados: {sorted(comunes)} (paralelas jamás comparten)")

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
    fail(f"worktree huérfano sin unidad: worktrees/{h} (¿cierre a medias?)")
for h in sorted(huerfanos_archivados):
    warn(f"worktrees/{h}: su unidad ya está archivada pero el worktree sigue en disco — "
         f"bórralo a mano si el cierre no pudo hacerlo (o es la ventana normal de un cierre en curso)")
for z in sorted(en_obra - wt):
    warn(f"unidad {z} en obra sin worktree (¿aún no despachada de verdad?)")
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
                     f"no ha terminado: recupera el trabajo antes de cerrar")
            else:
                warn(f"{aviso}: pide commits al constructor")
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
                 f"aparece, recupérala con `git -C {repo_cod.name} branch {nombre} <sha>`")
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
                         f"ficha debe acreditarlo con su 'fusion: <sha>'")

# --- 6. Archivo: lo archivado debe estar mergeada/descartada ---
archivo = trabajo / "archivo"
for carpeta in sorted(p for p in archivo.iterdir() if p.is_dir()) if archivo.is_dir() else []:
    spec_archivada = carpeta / "especificacion.md"
    fm = frontmatter(spec_archivada)
    if fm and fm.get("estado") not in {"mergeada", "descartada"}:
        fail(f"archivo/{carpeta.name}: archivada con estado '{fm.get('estado')}' (solo mergeada/descartada)")
    if fm and spec_archivada.exists():
        revisar_deuda_hotfix(f"archivo/{carpeta.name}", spec_archivada, fm)
        validar_origen_peticion(carpeta.name, fm)

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
    hallazgos = carpeta / "hallazgos.md"
    if not hallazgos.exists():
        continue
    pendientes = hallazgos_sin_cosechar(hallazgos.read_text(encoding="utf-8"))
    if pendientes:
        warn(f"archivo/{carpeta.name}: {pendientes} hallazgo(s) sin cosechar. Formato exacto: "
             f"'→ promovido a <destino>' o '→ descartado (motivo)', en cualquier punto de la "
             f"viñeta (admite negrita). El ejemplo está en plantillas/hallazgos.md")
    sin_pid = promociones_sin_peticion(hallazgos.read_text(encoding="utf-8"))
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
             f"de construir nada, con .env, la carpeta del entorno, .git/ y los datos locales")
    else:
        contenido = ignore.read_text(encoding="utf-8")
        faltan = [p for p in IGNORAR_IMAGEN if p not in contenido]
        if faltan:
            fail(f"{etiqueta}/.dockerignore no menciona {faltan}: los secretos acabarían "
                 f"dentro de la imagen")
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
culpables_kill = sorted(
    p.relative_to(RAIZ).as_posix()
    for p in artefactos_kill
    if any(pat in p.read_text(encoding="utf-8", errors="ignore") for pat in PATRONES_KILL))
if culpables_kill:
    fail(f"pkill -f / killall en {', '.join(culpables_kill)}: eso mata procesos de otros "
         f"agentes o proyectos que compartan la máquina. Guarda el PID al lanzar y mata ese "
         f"PID exacto")
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
         "docs/00-metodo/scripts/lint_ci.py")
elif not hay_repo:
    warn(f"no se pudo comprobar el contrato de CI: el repo de código ({repo_cod}) "
         "no existe o no es un repositorio git")
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
             f"{' --require-e2e' if requiere_e2e else ''}` para ver el detalle")
    elif presentes_ci:
        ok("contrato CI materializado y completo")
    elif resultado_ci.returncode or deuda_sin_materializar:
        warn("CI real aún sin materializar: en brownfield debe ser la primera unidad técnica "
             "tras la adopción; en proyectos nuevos nace con el esqueleto")
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
             f'git config --global user.email "tu@correo"')
    else:
        ok("git tiene identidad configurada (user.name y user.email)")
    if git(RAIZ, "rev-parse", "--verify", "--quiet", "HEAD")[0] != 0:
        fail("el meta-repo no tiene NI UN commit: el bootstrap no pudo cerrar el inicial y "
             "todo lo escrito desde entonces —planos, decisiones, unidades— vive sin respaldo "
             "de git. Configura la identidad y haz el commit inicial antes de seguir")
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
         "herramienta de ingeniería de requisitos")
if hay_repo and sin_remoto(repo_cod):
    warn(f"el repo de código ({repo_cod.name}/) no tiene remoto: el código existe SOLO en "
         f"este ordenador y ningún push lo respalda")

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
        fail(str(exc))
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

# --- 9. Higiene ---
if (RAIZ / "codebase").exists():
    fail("codebase/ existe (estructura vieja: debe ser main/ + worktrees/)")

# --- Resultado ---
print(f"\n{len(fallos)} FAIL · {len(avisos)} WARN")
sys.exit(1 if fallos else 0)
