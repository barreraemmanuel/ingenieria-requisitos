#!/usr/bin/env python3
"""Entrada persistente de peticiones del usuario.

La primera escritura de cualquier encargo accionable es ``capturar``. Este
script conserva el original, serializa cambios concurrentes por petición y
escribe JSON mediante reemplazo atómico. Solo usa la biblioteca estándar.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path

import repo_config


for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

import control_plane

control_plane.redactar_salidas()


RAIZ = Path(__file__).resolve().parents[3]
PETICIONES = RAIZ / "docs/05-trabajo/peticiones"
LOCKS = RAIZ / ".runtime/locks"
RE_ID = re.compile(r"^P-\d{8}-[a-f0-9]{8}$")
ESTADOS = {
    "capturada",
    "evaluando",
    "esperando_usuario",
    "aparcada",
    "encaminada",
    "cerrada",
    "cancelada",
}
TERMINALES = {"cerrada", "cancelada"}
PERFILES_INVESTIGACION = {"ninguna", "acotada", "plataforma"}
TIPOS_PROCESO = {
    "unidad",
    "bug",
    "expres",
    "investigacion",
    "auditoria",
    "flujos",
    "deploy",
}
CONTRATOS_TERMINALES = {
    "unidad": "unidad-mergeada-v1",
    "bug": "bug-mergeado-v1",
    "expres": "rama-expres-v1",
    "investigacion": "fase3-sintetizada-v1",
    "auditoria": "unidad-auditoria-mergeada-v1",
    "flujos": "planos-aprobados-v1",
    "deploy": "despliegue-verificado-v1",
}
RELACIONES_PROCESO = {"satisface", "origino", "sustituida_por"}
RESULTADOS = {
    "entregada",
    "ya_existia",
    "sin_cambio",
    "duplicada",
    "rechazada",
    "cancelada",
}
RIESGOS_BLOQUEANTES = {"seguridad", "dinero", "pii", "contrato", "perdida-datos"}

# El CARRIL (unidad 027, R5): antes vivía mezclado con el tipo dentro de un único --ruta y
# obligaba a adivinar cuál de los dos significaba cada vez (el baile evaluar↔nueva sufrido en
# campo). Ahora --ruta es SIEMPRE uno de estos valores; el tipo viaja aparte en --tipo.
CARRILES = {"expres", "directo", "normal", "completo", "hotfix", "documental"}
# Vocabulario legacy de --ruta (forma antigua, sin --tipo): los tipos de unidad.py TIPOS más
# los tipos de proceso de aquí arriba (TIPOS_PROCESO). Duplicado a propósito — peticion.py no
# importa unidad.py (sería circular) — y NO se relee de LEGACY.json ni de ningún otro sitio: es
# el vocabulario cerrado que ya aceptaba `--ruta` antes de esta unidad, ahora con nombre.
TIPOS_UNIDAD_LEGACY = {
    "bug", "feature", "refactor", "migracion", "auditoria", "investigacion", "documentacion",
}
RUTAS_LEGACY_VALIDAS = TIPOS_UNIDAD_LEGACY | TIPOS_PROCESO


class ErrorPeticion(ValueError):
    pass


def ahora():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def cargar_legacy():
    """Vías legales para el pasado (unidad 027, R1/R2): unidades y bugs anteriores al sistema
    de peticiones, listados a mano en peticiones/LEGACY.json — el mismo fichero y formato que
    ya lee `lint_metodo.py`. Función ÚNICA para que `unidad.py` no duplique esta lectura (la
    alternativa descartada en el diseño: deriva de copias, como pasó con el testigo del squash
    021/022)."""
    ruta = PETICIONES / "LEGACY.json"
    if not ruta.exists():
        return {"formato": 1, "modo": "estricto", "unidades": [], "bugs": [], "ramas": []}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrorPeticion(f"peticiones/LEGACY.json ilegible: {exc}") from exc
    if datos.get("formato") != 1 or datos.get("modo") not in {"observacion", "estricto"}:
        raise ErrorPeticion("peticiones/LEGACY.json exige formato 1 y modo observacion|estricto")
    for clave in ("unidades", "bugs", "ramas"):
        if not isinstance(datos.get(clave), list):
            raise ErrorPeticion(f"peticiones/LEGACY.json: {clave} debe ser una lista exacta")
    return datos


def unidad_legacy(nombre, tipo_proceso):
    """True si `nombre` (unidad o bug) figura en LEGACY.json bajo la lista de su clase."""
    legacy = cargar_legacy()
    lista = "bugs" if tipo_proceso == "bug" else "unidades"
    return nombre in set(legacy.get(lista, []))


def ruta_peticion(pid):
    if not RE_ID.fullmatch(pid or ""):
        raise ErrorPeticion(
            f"identificador inválido '{pid}': se espera P-AAAAMMDD-xxxxxxxx"
        )
    return PETICIONES / pid / "peticion.json"


def escribir_atomico(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=f".{ruta.name}.", dir=str(ruta.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as fichero:
            json.dump(datos, fichero, ensure_ascii=False, indent=2, sort_keys=True)
            fichero.write("\n")
            fichero.flush()
            os.fsync(fichero.fileno())
        os.replace(temporal, ruta)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def escribir_bytes_atomico(ruta, contenido):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=f".{ruta.name}.", dir=str(ruta.parent))
    try:
        with os.fdopen(descriptor, "wb") as fichero:
            fichero.write(contenido)
            fichero.flush()
            os.fsync(fichero.fileno())
        os.replace(temporal, ruta)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


@contextlib.contextmanager
def lock(pid):
    LOCKS.mkdir(parents=True, exist_ok=True)
    ruta = LOCKS / f"peticion-{pid}.lock"
    try:
        ruta.mkdir()
    except FileExistsError as exc:
        raise ErrorPeticion(
            f"la petición {pid} está siendo modificada por otra sesión; "
            f"lock: {ruta.relative_to(RAIZ)}"
        ) from exc
    try:
        escribir_atomico(
            ruta / "owner.json",
            {"pid": os.getpid(), "host": socket.gethostname(), "creado": ahora()},
        )
        yield
    finally:
        shutil.rmtree(ruta, ignore_errors=True)


def cmd_desbloquear(args):
    ruta = LOCKS / f"peticion-{args.peticion}.lock"
    if not ruta.is_dir():
        raise ErrorPeticion(f"{args.peticion} no tiene un lock pendiente")
    try:
        owner = json.loads((ruta / "owner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        owner = {}
    host = owner.get("host")
    pid = owner.get("pid")
    vivo = False
    if host == socket.gethostname() and isinstance(pid, int):
        # En Windows os.kill(pid, 0) MATA el proceso en vez de sondearlo.
        vivo = control_plane.pid_vivo(pid)
    if vivo:
        raise ErrorPeticion(f"el proceso {pid} sigue vivo; no se retira su lock")
    if host and host != socket.gethostname() and not args.forzar:
        raise ErrorPeticion(
            f"el lock pertenece a {host}; compruébalo y usa --forzar --motivo si quedó huérfano"
        )
    if args.forzar and not args.motivo.strip():
        raise ErrorPeticion("--forzar exige --motivo")
    shutil.rmtree(ruta)
    print(
        f"lock huérfano de {args.peticion} retirado"
        + (f" · {args.motivo.strip()}" if args.motivo.strip() else "")
    )
    return 0


def cargar(pid):
    ruta = ruta_peticion(pid)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ErrorPeticion(f"no existe la petición {pid}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrorPeticion(f"no puedo leer {ruta.relative_to(RAIZ)}: {exc}") from exc
    if datos.get("id") != pid or datos.get("estado") not in ESTADOS:
        raise ErrorPeticion(f"{ruta.relative_to(RAIZ)} tiene un formato incoherente")
    return datos


def guardar(datos):
    datos["actualizada"] = ahora()
    escribir_atomico(ruta_peticion(datos["id"]), datos)


def nueva_peticion(resumen, texto, autor):
    if not resumen.strip() or not texto.strip() or not autor.strip():
        raise ErrorPeticion("resumen, texto y autor no pueden estar vacíos")
    pid = f"P-{datetime.date.today():%Y%m%d}-{uuid.uuid4().hex[:8]}"
    instante = ahora()
    datos = {
        "formato": 1,
        "id": pid,
        "estado": "capturada",
        "revision": 1,
        "responsable": None,
        "creada": instante,
        "actualizada": instante,
        "original": {
            "resumen": resumen.strip(),
            "texto": texto.strip(),
            "autor": autor.strip(),
        },
        "aclaraciones": [],
        "evaluaciones": [],
        "relaciones": [],
        "procesos": [],
        "cierres": [],
        "reclamos": [],
    }
    escribir_atomico(ruta_peticion(pid), datos)
    return datos


def evaluacion_vigente(datos):
    for evaluacion in reversed(datos.get("evaluaciones", [])):
        if evaluacion.get("revision") == datos.get("revision"):
            return evaluacion
    return None


def ruta_investigacion(pid, revision, nombre):
    return ruta_peticion(pid).parent / "investigacion" / f"revision-{revision}" / nombre


def renderizar_plan(datos, evaluacion):
    plantilla = RAIZ / "docs/00-metodo/plantillas/peticion-investigacion-plan.md"
    try:
        texto = plantilla.read_text(encoding="utf-8")
    except OSError as exc:
        raise ErrorPeticion(f"falta la plantilla {plantilla.relative_to(RAIZ)}") from exc
    reemplazos = {
        "{{PETICION}}": datos["id"],
        "{{REVISION}}": str(datos["revision"]),
        "{{MOTIVO}}": evaluacion["investigacion"]["motivo"],
        "{{DISPARADORES}}": "\n".join(
            f"- {valor}" for valor in evaluacion["investigacion"]["disparadores"]
        )
        or "- sin disparadores adicionales",
        "{{PREGUNTAS}}": "\n".join(
            f"- {valor}" for valor in evaluacion["investigacion"]["preguntas"]
        )
        or "- sin preguntas",
    }
    for origen, destino in reemplazos.items():
        texto = texto.replace(origen, destino)
    plan = ruta_investigacion(datos["id"], datos["revision"], "PLAN.md")
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(texto, encoding="utf-8")
    plantilla_sintesis = (
        RAIZ / "docs/00-metodo/plantillas/peticion-investigacion-sintesis.md"
    )
    sintesis = ruta_investigacion(datos["id"], datos["revision"], "SINTESIS.md")
    if plantilla_sintesis.is_file() and not sintesis.exists():
        contenido = plantilla_sintesis.read_text(encoding="utf-8")
        contenido = contenido.replace("{{PETICION}}", datos["id"])
        contenido = contenido.replace("{{REVISION}}", str(datos["revision"]))
        contenido = contenido.replace(
            "{{RESPUESTAS}}",
            "\n".join(
                f"- <respondida|no_concluyente> · {pregunta} · "
                "evidencia: <URL-o-ruta#ancla> · fecha: <AAAA-MM-DD>"
                for pregunta in evaluacion["investigacion"].get("preguntas", [])
            ),
        )
        sintesis.write_text(contenido, encoding="utf-8")


def evidencia_investigacion_valida(valor):
    if re.fullmatch(r"https://[^\s#]+(?:#[^\s]+)?", valor):
        return True
    if "#" not in valor:
        return False
    nombre, ancla = valor.split("#", 1)
    if not nombre or not ancla:
        return False
    ruta = Path(nombre)
    if ruta.is_absolute() or ".." in ruta.parts:
        return False
    resuelta = (RAIZ / ruta).resolve()
    if not resuelta.is_file() or RAIZ.resolve() not in resuelta.parents:
        return False
    try:
        lineas = resuelta.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    linea = re.fullmatch(r"L(\d+)(?:-L(\d+))?", ancla)
    if linea:
        inicio = int(linea.group(1))
        final = int(linea.group(2) or inicio)
        return 1 <= inicio <= final <= len(lineas)

    def slug(titulo):
        titulo = unicodedata.normalize("NFKD", titulo)
        titulo = "".join(c for c in titulo if not unicodedata.combining(c)).lower()
        titulo = re.sub(r"[^a-z0-9 _-]", "", titulo)
        return re.sub(r"[ _]+", "-", titulo).strip("-")

    anclas = {
        slug(encontrada.group(1))
        for contenido in lineas
        if (encontrada := re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", contenido))
    }
    return ancla in anclas


def validar_sintesis_acotada(datos, evaluacion):
    sintesis = ruta_investigacion(
        datos["id"], datos["revision"], "SINTESIS.md"
    )
    try:
        texto = sintesis.read_text(encoding="utf-8")
    except OSError as exc:
        raise ErrorPeticion(
            f"falta {sintesis.relative_to(RAIZ)}; sintetiza antes de abrir una orden"
        ) from exc
    cabecera = f"# Síntesis de investigación · {datos['id']} · revisión {datos['revision']}"
    if not texto.startswith(cabecera + "\n") or "{{" in texto or re.search(r"<[^>]+>", texto):
        raise ErrorPeticion(
            f"{sintesis.relative_to(RAIZ)} no identifica la petición/revisión o conserva marcadores"
        )
    faltan = []
    no_concluyentes = []
    for pregunta in evaluacion["investigacion"].get("preguntas", []):
        patron = re.compile(
            rf"^- (respondida|no_concluyente) · {re.escape(pregunta)} · "
            rf"evidencia: (\S+) · fecha: (\d{{4}}-\d{{2}}-\d{{2}})$",
            re.M,
        )
        encontrada = patron.search(texto)
        if not encontrada:
            faltan.append(pregunta)
            continue
        try:
            datetime.date.fromisoformat(encontrada.group(3))
        except ValueError:
            faltan.append(pregunta)
            continue
        if not evidencia_investigacion_valida(encontrada.group(2)):
            faltan.append(pregunta)
            continue
        if encontrada.group(1) == "no_concluyente":
            no_concluyentes.append(pregunta)
    if faltan:
        raise ErrorPeticion(
            "SINTESIS.md no aporta respuesta, evidencia anclada y fecha para: "
            + "; ".join(faltan)
        )
    decision = re.search(
        r"^## Decisión para el triaje definitivo\s*$\n(.*?)(?=^## |\Z)",
        texto,
        re.M | re.S,
    )
    if not decision or len(decision.group(1).strip()) < 30:
        raise ErrorPeticion("SINTESIS.md no contiene una decisión de triaje suficiente")
    return no_concluyentes


def validar_sintesis_plataforma(evaluacion):
    referencia = evaluacion["investigacion"].get("sintesis_plataforma")
    if referencia != "docs/03-investigacion/SINTESIS.md":
        raise ErrorPeticion(
            "investigación plataforma exige --sintesis-plataforma "
            "docs/03-investigacion/SINTESIS.md"
        )
    ruta = RAIZ / referencia
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise ErrorPeticion(f"falta {referencia}") from exc
    validar_fase3_terminal(ruta)
    faltan = []
    no_concluyentes = []
    for pregunta in evaluacion["investigacion"].get("preguntas", []):
        patron = re.compile(
            rf"^- (respondida|no_concluyente) · {re.escape(pregunta)} · "
            rf"evidencia: (\S+) · fecha: (\d{{4}}-\d{{2}}-\d{{2}})$",
            re.M,
        )
        encontrada = patron.search(texto)
        if not encontrada or not evidencia_investigacion_valida(encontrada.group(2)):
            faltan.append(pregunta)
            continue
        try:
            datetime.date.fromisoformat(encontrada.group(3))
        except ValueError:
            faltan.append(pregunta)
            continue
        if encontrada.group(1) == "no_concluyente":
            no_concluyentes.append(pregunta)
    if faltan:
        raise ErrorPeticion(
            "la síntesis de plataforma no responde con evidencia y fecha: "
            + "; ".join(faltan)
        )
    return no_concluyentes


def validar_fase3_terminal(ruta):
    texto = ruta.read_text(encoding="utf-8")
    if len(texto.strip()) < 200 or re.search(r"<[^>]+>|YYYY-MM-DD", texto):
        raise ErrorPeticion(
            f"{ruta.relative_to(RAIZ)} sigue vacía o con marcadores"
        )
    informes = sorted(ruta.parent.glob("informe-[0-9][0-9]-*.md"))
    if len(informes) < 10:
        raise ErrorPeticion(
            f"la fase 3 de plataforma exige al menos 10 informes; hay {len(informes)}"
        )
    indices = {informe.name.split("-", 2)[1] for informe in informes}
    esperados = {f"{indice:02d}" for indice in range(1, 11)}
    if not esperados.issubset(indices):
        raise ErrorPeticion("la fase 3 no conserva los informes fundacionales 01..10")
    for informe in informes:
        contenido = informe.read_text(encoding="utf-8")
        if len(contenido.strip()) < 200 or re.search(r"<[^>]+>|YYYY-MM-DD", contenido):
            raise ErrorPeticion(f"{informe.relative_to(RAIZ)} está incompleto")
        if not re.search(r"https://\S+", contenido):
            raise ErrorPeticion(f"{informe.relative_to(RAIZ)} no contiene fuentes URL")
        fechas = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", contenido)
        if not any(fecha_iso_valida(fecha) for fecha in fechas):
            raise ErrorPeticion(f"{informe.relative_to(RAIZ)} no contiene fuentes fechadas")
        if not re.search(r"\bnivel\s*[:|]", contenido, re.I):
            raise ErrorPeticion(f"{informe.relative_to(RAIZ)} no declara nivel de fuente")
    return True


def investigacion_lista(datos, evaluacion=None):
    evaluacion = evaluacion or evaluacion_vigente(datos)
    if not evaluacion:
        raise ErrorPeticion(f"{datos['id']} no tiene evaluación para revisión {datos['revision']}")
    investigacion = evaluacion["investigacion"]
    if investigacion["perfil"] == "ninguna":
        return True
    no_concluyentes = (
        validar_sintesis_plataforma(evaluacion)
        if investigacion["perfil"] == "plataforma"
        else validar_sintesis_acotada(datos, evaluacion)
    )
    riesgos = set(investigacion.get("disparadores", [])) & RIESGOS_BLOQUEANTES
    if riesgos and no_concluyentes:
        raise ErrorPeticion(
            "la investigación no concluyente bloquea por riesgo "
            + ", ".join(sorted(riesgos))
        )
    return True


def ruta_efectiva_evaluacion(evaluacion):
    """Reconstruye el valor único que ANTES vivía en 'ruta_provisional' (unidad 027, R5) a
    partir del par (carril, tipo) que ahora se guarda por separado. El carril 'directo'
    manda igual que antes — bypasa el tipo (incidente de campo 06-08, contexto_proceso) —
    y si no hay tipo evaluado (formas antiguas de --ruta con un carril suelto) se cae al
    propio carril, para no cambiar el comportamiento de ninguna llamada ya existente."""
    carril_eval = evaluacion.get("carril_provisional", evaluacion.get("ruta_provisional"))
    tipo_eval = evaluacion.get("tipo_provisional")
    if carril_eval == "directo":
        return "directo"
    return tipo_eval if tipo_eval else carril_eval


def validar_para_orden(pid, carril=None, tipo=None, revision=None):
    datos = cargar(pid)
    if datos["estado"] in TERMINALES:
        raise ErrorPeticion(f"{pid} está {datos['estado']}")
    if revision is not None and datos["revision"] != int(revision):
        raise ErrorPeticion(
            f"{pid} está en revisión {datos['revision']}; la orden usa revisión {revision}"
        )
    evaluacion = evaluacion_vigente(datos)
    if not evaluacion:
        raise ErrorPeticion(f"{pid} no está evaluada en revisión {datos['revision']}")
    ruta = ruta_efectiva_evaluacion(evaluacion)
    ruta_esperada = "directo" if carril == "directo" else tipo
    if ruta_esperada and ruta != ruta_esperada:
        raise ErrorPeticion(
            f"{pid} fue evaluada para ruta {ruta}; no puede abrir trabajo "
            f"por {ruta_esperada}"
        )
    perfil = evaluacion["investigacion"]["perfil"]
    if carril in {"directo", "expres"} and perfil != "ninguna":
        raise ErrorPeticion(
            f"el carril {carril} exige investigación ninguna; {pid} declara {perfil}"
        )
    investigacion_lista(datos, evaluacion)
    return datos["revision"]


def enlazar_proceso(pid, tipo, ref, revision=None, relacion="satisface",
                    contrato_terminal=None, metadata=None):
    """Enlaza idempotentemente una orden creada por otro script.

    La revisión se comprueba dentro del mismo lock que protege la escritura: una aclaración
    no puede colarse entre la validación y el enlace dejando una orden recién nacida obsoleta.
    """
    revision = revision if revision is not None else validar_para_orden(pid)
    return enlazar_procesos(
        [f"{pid}@{revision}"], tipo, ref, relacion, contrato_terminal, metadata
    )[0]


def parsear_referencias(referencias):
    resultado = []
    vistos = set()
    for referencia in referencias:
        encontrada = re.fullmatch(r"(P-\d{8}-[a-f0-9]{8})@(\d+)", referencia)
        if not encontrada:
            raise ErrorPeticion(f"referencia de petición inválida: {referencia}")
        pid, revision = encontrada.groups()
        if pid in vistos:
            raise ErrorPeticion(f"petición repetida en la misma orden: {pid}")
        vistos.add(pid)
        resultado.append((pid, int(revision)))
    if not resultado:
        raise ErrorPeticion("la orden debe enlazar al menos una petición")
    return resultado


def enlazar_procesos(referencias, tipo, ref, relacion="satisface",
                     contrato_terminal=None, metadata=None):
    """Enlaza una orden a una o varias peticiones sin dejar un lote parcial.

    Toma todos los locks en orden estable y valida todas las revisiones antes de la primera
    escritura. Así, una aclaración o una sesión concurrente aborta el lote entero.
    """
    if tipo not in TIPOS_PROCESO:
        raise ErrorPeticion(f"tipo de proceso fuera de vocabulario: {tipo}")
    if relacion not in RELACIONES_PROCESO:
        raise ErrorPeticion(f"relación fuera de vocabulario: {relacion}")
    contrato_esperado = CONTRATOS_TERMINALES[tipo]
    if contrato_terminal and contrato_terminal != contrato_esperado:
        raise ErrorPeticion(
            f"contrato terminal de {tipo} debe ser {contrato_esperado}"
        )
    parsed = parsear_referencias(referencias)
    ruta_canonica = validar_proceso_canonico(tipo, ref, terminal=False)
    carril_proceso, ruta_proceso = contexto_proceso(tipo, ruta_canonica)
    with contextlib.ExitStack() as locks:
        for pid, _ in sorted(parsed):
            locks.enter_context(lock(pid))
        lote = []
        for pid, revision in parsed:
            datos = cargar(pid)
            validar_para_orden(
                pid,
                carril=carril_proceso,
                tipo=ruta_proceso,
                revision=revision,
            )
            validar_enlace_canonico(tipo, ruta_canonica, pid, revision)
            existente = next(
                (
                    proceso
                    for proceso in datos["procesos"]
                    if proceso.get("tipo") == tipo and proceso.get("ref") == ref
                ),
                None,
            )
            if existente and existente.get("revision") != revision:
                raise ErrorPeticion(f"{tipo} {ref} ya enlaza otra revisión de {pid}")
            lote.append((datos, existente))

        originales = {
            datos["id"]: ruta_peticion(datos["id"]).read_bytes()
            for datos, _ in lote
        }
        resultados = []
        try:
            for datos, existente in lote:
                if existente:
                    resultados.append(False)
                    continue
                proceso_nuevo = {
                        "tipo": tipo,
                        "ref": ref,
                        "relacion": relacion,
                        "revision": datos["revision"],
                        "estado": "pendiente",
                        "contrato_terminal": contrato_esperado,
                        "fecha": ahora(),
                    }
                if metadata:
                    proceso_nuevo["metadata"] = dict(metadata)
                datos["procesos"].append(proceso_nuevo)
                datos["estado"] = "encaminada"
                guardar(datos)
                resultados.append(True)
        except Exception:
            for pid, contenido in originales.items():
                escribir_bytes_atomico(ruta_peticion(pid), contenido)
            raise
    return resultados


def registrar_base_despacho(referencias, tipo, ref, base_sha, principal):
    """Fija de qué principal nació una rama normal antes de que pueda recibir trabajo.

    El pre-push usa este recibo para distinguir una rama creada antes del cambio de otra
    creada después, apuntando a un commit que se hizo directamente en la principal.
    """
    parsed = parsear_referencias(referencias)
    if tipo not in {"unidad", "bug"}:
        raise ErrorPeticion(f"{tipo} no admite recibo de despacho con rama")
    repo, principal_configurada = repo_codigo()
    if principal != principal_configurada:
        raise ErrorPeticion(
            f"la rama principal del despacho debe ser {principal_configurada}, no {principal}"
        )
    if git(repo, "rev-parse", "--verify", "--quiet", f"{base_sha}^{{commit}}")[0] != 0:
        raise ErrorPeticion(f"SHA base de despacho inexistente: {base_sha}")
    with contextlib.ExitStack() as locks:
        for pid, _ in sorted(parsed):
            locks.enter_context(lock(pid))
        lote = []
        for pid, revision in parsed:
            datos = cargar(pid)
            proceso = next(
                (
                    item for item in datos.get("procesos", [])
                    if item.get("tipo") == tipo and item.get("ref") == ref
                    and item.get("revision") == revision
                ),
                None,
            )
            if proceso is None:
                raise ErrorPeticion(f"{pid}@{revision} no enlaza {tipo} {ref}")
            metadata = proceso.get("metadata") or {}
            if metadata.get("base_sha") and metadata.get("base_sha") != base_sha:
                raise ErrorPeticion(f"{pid}@{revision} ya conserva otra base de despacho")
            lote.append((datos, proceso))
        originales = {
            datos["id"]: ruta_peticion(datos["id"]).read_bytes() for datos, _ in lote
        }
        try:
            for datos, proceso in lote:
                proceso["metadata"] = {
                    **(proceso.get("metadata") or {}),
                    "base_sha": base_sha,
                    "principal": principal,
                }
                guardar(datos)
        except Exception:
            for pid, contenido in originales.items():
                escribir_bytes_atomico(ruta_peticion(pid), contenido)
            raise


def base_despacho(referencias, tipo, ref):
    """El SHA del que nació la rama de un proceso, tal y como lo dejó `despachar`.

    Unidad 033 (R5): el punto de partida ya se anotaba para el pre-push; el cierre lo usa
    para MEDIR el cambio de un carril directo contra lo que había cuando se despachó.
    Devuelve None si ninguna petición de origen lo conserva (unidades legacy o despachos
    anteriores a que se registrara).
    """
    for pid, revision in parsear_referencias(referencias):
        try:
            datos = cargar(pid)
        except ErrorPeticion:
            continue
        for proceso in datos.get("procesos", []):
            if (proceso.get("tipo") == tipo and proceso.get("ref") == ref
                    and proceso.get("revision") == revision):
                base = (proceso.get("metadata") or {}).get("base_sha")
                if base:
                    return base
    return None


def ruta_proceso_canonico(tipo, ref):
    if tipo in {"unidad", "bug"}:
        if not re.fullmatch(r"\d{3}-[a-z0-9][a-z0-9-]*", ref):
            raise ErrorPeticion(f"referencia {tipo} inválida: {ref}")
        candidatos = (
            [
                RAIZ / "docs/05-trabajo" / ref / "especificacion.md",
                RAIZ / "docs/05-trabajo/archivo" / ref / "especificacion.md",
            ]
            if tipo == "unidad"
            else [RAIZ / "docs/bugs" / f"{ref}.md"]
        )
        ruta = next((item for item in candidatos if item.is_file()), None)
        if ruta is None:
            raise ErrorPeticion(f"no existe el proceso canónico {tipo} {ref}")
        return ruta
    if tipo == "auditoria":
        if not re.fullmatch(r"\d{3}-[a-z0-9][a-z0-9-]*", ref):
            raise ErrorPeticion(f"referencia auditoria inválida: {ref}")
        candidatos = (
            RAIZ / "docs/05-trabajo" / ref / "especificacion.md",
            RAIZ / "docs/05-trabajo/archivo" / ref / "especificacion.md",
        )
        ruta = next((item for item in candidatos if item.is_file()), None)
        if ruta is None or valor_frontmatter(ruta, "tipo") != "auditoria":
            raise ErrorPeticion(f"no existe la unidad canónica de auditoría {ref}")
        return ruta
    if tipo == "expres":
        repo, _ = repo_codigo()
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{ref}")[0] != 0:
            raise ErrorPeticion(f"no existe la rama exprés canónica {ref}")
        return None
    if tipo == "flujos" and ref != "docs/02-flujos/planos/aprobacion.json":
        raise ErrorPeticion(
            "flujos exige el recibo canónico docs/02-flujos/planos/aprobacion.json"
        )
    if tipo == "investigacion" and ref != "docs/03-investigacion/SINTESIS.md":
        raise ErrorPeticion(
            "investigacion exige la síntesis canónica docs/03-investigacion/SINTESIS.md"
        )
    ruta = Path(ref)
    if ruta.is_absolute() or ".." in ruta.parts:
        raise ErrorPeticion(f"referencia de proceso insegura: {ref}")
    resuelta = (RAIZ / ruta).resolve()
    if not resuelta.is_file() or RAIZ.resolve() not in resuelta.parents:
        raise ErrorPeticion(f"no existe el proceso canónico {tipo} {ref}")
    if tipo == "deploy":
        relativa = resuelta.relative_to(RAIZ).as_posix()
        if not re.fullmatch(
            r"docs/(?:05-trabajo|bugs)/\d{3}-[a-z0-9][a-z0-9-]*/despliegue\.md"
            r"|docs/05-trabajo/despliegues/[a-z0-9][a-z0-9-]*\.md",
            relativa,
        ):
            raise ErrorPeticion(
                "deploy exige la ficha canónica docs/05-trabajo/NNN-slug/despliegue.md "
                "(o docs/bugs/NNN-slug/despliegue.md para un hotfix), o —si el despliegue "
                "es de LOTE, varias unidades a la vez— docs/05-trabajo/despliegues/<slug>.md"
            )
    return resuelta


def estado_frontmatter(ruta):
    encontrada = re.search(
        r"\A---\s*\n.*?^estado:\s*(\S+).*?^---\s*$",
        ruta.read_text(encoding="utf-8"),
        re.M | re.S,
    )
    return encontrada.group(1) if encontrada else ""


def fecha_iso_valida(valor):
    try:
        datetime.date.fromisoformat(valor)
    except (TypeError, ValueError):
        return False
    return True


def valor_frontmatter(ruta, clave):
    encontrada = re.search(
        rf"\A---\s*\n.*?^{re.escape(clave)}:\s*(\S+).*?^---\s*$",
        ruta.read_text(encoding="utf-8"),
        re.M | re.S,
    )
    return encontrada.group(1) if encontrada else ""


def contexto_proceso(tipo, ruta):
    if tipo == "unidad":
        tipo_unidad = valor_frontmatter(ruta, "tipo")
        carril = valor_frontmatter(ruta, "carril") or "normal"
        if not tipo_unidad:
            raise ErrorPeticion(f"{ruta.relative_to(RAIZ)} no declara tipo")
        return carril, tipo_unidad
    if tipo == "bug":
        # Un bug también viaja con carril (directo o normal, runbooks/bug.md). Ignorarlo
        # aquí hacía imposible crear un bug evaluado como directo: la primera validación
        # exigía ruta 'directo' y este enlace revalidaba con 'bug' — imposible complacer
        # a las dos (incidente de campo, 06-08).
        carril = valor_frontmatter(ruta, "carril") or "normal"
        return carril, "bug"
    if tipo == "expres":
        return "expres", "expres"
    if tipo == "auditoria":
        return "normal", "auditoria"
    return "normal", tipo


def lista_frontmatter(ruta, clave):
    """Una lista `clave: [a, b, c]` del frontmatter, o [] si no está o está vacía."""
    encontrada = re.search(
        rf"\A---\s*\n.*?^{re.escape(clave)}:\s*\[(.*?)\].*?^---\s*$",
        ruta.read_text(encoding="utf-8"),
        re.M | re.S,
    )
    if not encontrada:
        return []
    return [item.strip() for item in encontrada.group(1).split(",") if item.strip()]


def referencias_frontmatter(ruta):
    return lista_frontmatter(ruta, "peticiones")


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


CAMPOS_DEPLOY_OBLIGATORIOS = (
    "Commit/tag",
    "Etapa destino y máquina exacta",
    "Qué cambia para el usuario, en una frase",
    "OK del usuario ANTES de salir",
    "Suite completa sobre este commit",
    "Seguridad sobre este commit",
    "Qué se copió y adónde",
    "Volcado — comando y salida",
    "Restauración de prueba",
    "Pasos",
    "Vuelta atrás",
    "Flujo real de negocio de punta a punta",
    "Vigilancia",
    "Validación del usuario sobre la etapa desplegada",
    "Resultado",
    "Quién y cuándo",
    "Anotado en `conocimiento/plano-deploy.md`",
)


def unidades_ficha_deploy_lote(ruta):
    """Las unidades NNN-slug que una ficha de despliegue de LOTE dice llevar (R3, unidad 027).

    Solo aplica a `docs/05-trabajo/despliegues/<slug>.md`: la ficha de lote existe precisamente
    para no mentir eligiendo UNA unidad cuando el despliegue llevó varias; exige listar al
    menos dos, todas con forma NNN-slug.
    """
    unidades = lista_frontmatter(ruta, "unidades")
    if len(unidades) < 2:
        raise ErrorPeticion(
            f"{ruta.relative_to(RAIZ)}: la ficha de lote exige `unidades: [NNN-slug, …]` con "
            "al menos dos (si es una sola, usa la ficha simple del propio NNN-slug)"
        )
    invalidas = [u for u in unidades if not re.fullmatch(r"\d{3}-[a-z0-9][a-z0-9-]*", u)]
    if invalidas:
        raise ErrorPeticion(
            f"{ruta.relative_to(RAIZ)}: unidad(es) con forma inválida en `unidades:`: "
            + ", ".join(invalidas)
        )
    return unidades


def validar_ficha_deploy_terminal(ruta):
    texto = ruta.read_text(encoding="utf-8")
    if valor_frontmatter(ruta, "proceso") != "deploy":
        raise ErrorPeticion(f"{ruta.relative_to(RAIZ)} no declara proceso: deploy")
    if ruta.parent.name == "despliegues":
        unidades_ficha_deploy_lote(ruta)
    if valor_frontmatter(ruta, "estado") != "desplegado":
        raise ErrorPeticion("la ficha de deploy no declara estado: desplegado")
    etapa = valor_frontmatter(ruta, "etapa")
    if etapa not in {"0-local", "1-lan", "2-vps"}:
        raise ErrorPeticion("la ficha de deploy no declara una etapa canónica")
    fecha = valor_frontmatter(ruta, "fecha")
    if not fecha_iso_valida(fecha):
        raise ErrorPeticion("la ficha de deploy no declara una fecha válida")
    commit = valor_frontmatter(ruta, "commit")
    repo, principal = repo_codigo()
    if not commit or git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")[0]:
        raise ErrorPeticion("la ficha de deploy no referencia un commit/tag existente")
    if git(repo, "merge-base", "--is-ancestor", commit, principal)[0] != 0:
        raise ErrorPeticion(f"el commit desplegado todavía no pertenece a {principal}")
    if re.search(r"<[^>]+>|PENDIENTE|DESPLEGADO\s*\|", texto):
        raise ErrorPeticion("la ficha de deploy conserva huecos o decisiones pendientes")
    campos = campos_ficha_deploy(texto)
    faltan = [
        nombre for nombre in CAMPOS_DEPLOY_OBLIGATORIOS
        if len(campos.get(nombre, "").strip(" .:·-")) < 3
    ]
    if faltan:
        raise ErrorPeticion(
            "la ficha de deploy carece de evidencia obligatoria: " + ", ".join(faltan)
        )
    if not re.match(rf"{re.escape(commit)}\b", campos["Commit/tag"]):
        raise ErrorPeticion("Commit/tag no coincide con el frontmatter de deploy")
    ok_previo = re.match(
        r"OK\s*\((\d{4}-\d{2}-\d{2}),\s*([^)]+)\)",
        campos["OK del usuario ANTES de salir"],
    )
    if not ok_previo or not fecha_iso_valida(ok_previo.group(1)) or not ok_previo.group(2).strip():
        raise ErrorPeticion("el OK anterior al deploy no está fechado ni atribuido")
    if not re.match(r"VERDE\b.*\.runtime/pre-deploy/full-suite\.log", campos["Suite completa sobre este commit"]):
        raise ErrorPeticion("la ficha no acredita la suite completa del commit")
    if not re.match(r"VERDE\b.*\.runtime/pre-deploy/security\.log", campos["Seguridad sobre este commit"]):
        raise ErrorPeticion("la ficha no acredita el gate de seguridad del commit")
    ok_final = re.match(
        r"OK\s*\((\d{4}-\d{2}-\d{2})\)",
        campos["Validación del usuario sobre la etapa desplegada"],
    )
    if not ok_final or not fecha_iso_valida(ok_final.group(1)):
        raise ErrorPeticion("la ficha de deploy no acredita el OK final del usuario")
    if not campos["Resultado"].startswith("DESPLEGADO"):
        raise ErrorPeticion("la ficha de deploy no declara resultado DESPLEGADO")
    if not re.search(r"\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\b", campos["Quién y cuándo"]):
        raise ErrorPeticion("la ficha no identifica quién desplegó y cuándo")
    return True


def evidencia_rama_fusionada(repo, rama, principal, metadata):
    metadata = metadata or {}
    base_sha = metadata.get("base_sha", "")
    if not base_sha or git(
        repo, "merge-base", "--is-ancestor", base_sha, principal
    )[0] != 0:
        return None
    codigo, punta_viva = git(
        repo, "rev-parse", "--verify", "--quiet", f"{rama}^{{commit}}"
    )
    punta = punta_viva.strip() if codigo == 0 else metadata.get("tip_sha", "")
    if punta == base_sha:
        return None
    # Sin punta (rama borrada tras el merge y sin tip_sha guardado) los caminos
    # por ancestría no existen, pero el grep del squash de más abajo sigue
    # valiendo: el asunto del merge es el testigo (bug 021).
    punta_existe = git(
        repo, "rev-parse", "--verify", "--quiet", f"{punta}^{{commit}}"
    )[0] == 0
    merge_guardado = metadata.get("merge_sha", "")
    modo_guardado = metadata.get("modo_fusion", "")
    if merge_guardado and git(
        repo, "merge-base", "--is-ancestor", merge_guardado, principal
    )[0] == 0:
        if modo_guardado == "ancestry" and merge_guardado == punta:
            return {
                "tip_sha": punta, "merge_sha": merge_guardado,
                "modo_fusion": "ancestry",
            }
        codigo, asunto = git(repo, "show", "-s", "--format=%s", merge_guardado)
        if modo_guardado == "squash" and codigo == 0 and rama in asunto:
            return {
                "tip_sha": punta, "merge_sha": merge_guardado,
                "modo_fusion": "squash",
            }

    if punta:
        if not punta_existe or git(
            repo, "merge-base", "--is-ancestor", base_sha, punta
        )[0] != 0:
            return None
        if git(repo, "merge-base", "--is-ancestor", punta, principal)[0] == 0:
            return {"tip_sha": punta, "merge_sha": punta, "modo_fusion": "ancestry"}

    # Grep del squash: primero el nombre exacto de la rama; si el título del PR
    # no lo conservó (p. ej. "expres P-… " con espacio), vale el P-ID que el
    # nombre de una rama exprés siempre contiene. Un asunto sin ninguno de los
    # dos NO es testigo: esto no se relaja (bug 021).
    patrones = [rama]
    p_id = re.search(r"P-\d{8}-[0-9a-f]{8}", rama)
    if p_id:
        patrones.append(p_id.group(0))
    for patron in patrones:
        codigo, salida = git(
            repo, "log", principal, f"^{base_sha}", "--fixed-strings",
            f"--grep={patron}", "--format=%H", "-1",
        )
        merge_sha = salida.strip() if codigo == 0 else ""
        if merge_sha:
            return {"tip_sha": punta, "merge_sha": merge_sha, "modo_fusion": "squash"}
    return None


def validar_enlace_canonico(tipo, ruta, pid, revision):
    if tipo in {"unidad", "bug", "auditoria", "deploy"}:
        referencia = f"{pid}@{revision}"
        if referencia not in referencias_frontmatter(ruta):
            raise ErrorPeticion(
                f"{ruta.relative_to(RAIZ)} no declara peticiones: [{referencia}]"
            )
    if tipo == "deploy":
        encontrada = re.search(r"^estado:\s*(.*?)\s*$", ruta.read_text(encoding="utf-8"), re.M)
        estado = encontrada.group(1) if encontrada else ""
        if estado not in {"preparada", "desplegado", "vuelta_atras"}:
            raise ErrorPeticion("la ficha de deploy no declara un estado único y válido")


def validar_proceso_canonico(tipo, ref, terminal, metadata=None):
    if tipo == "expres" and terminal:
        repo, principal = repo_codigo()
        if evidencia_rama_fusionada(repo, ref, principal, metadata) is None:
            raise ErrorPeticion(
                f"la rama exprés {ref} todavía no está fusionada en {principal}"
            )
        return None
    ruta = ruta_proceso_canonico(tipo, ref)
    if terminal and tipo in {"unidad", "bug", "auditoria"}:
        estado = estado_frontmatter(ruta)
        if estado != "mergeada":
            raise ErrorPeticion(
                f"{tipo} {ref} todavía está {estado or 'sin estado terminal'}"
            )
    if tipo == "flujos":
        try:
            recibo = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ErrorPeticion(f"recibo de flujos ilegible: {exc}") from exc
        if terminal and not (
            recibo.get("estado") == "aprobado"
            and recibo.get("huella") == huella_planos_actual()
            and fecha_iso_valida(recibo.get("fecha"))
            and isinstance(recibo.get("por"), str)
            and recibo.get("por").strip()
        ):
            raise ErrorPeticion("el recibo de flujos no acredita aprobación vigente")
    if tipo == "investigacion" and terminal:
        validar_fase3_terminal(ruta)
    if tipo == "deploy":
        if valor_frontmatter(ruta, "proceso") != "deploy":
            raise ErrorPeticion(f"{ruta.relative_to(RAIZ)} no declara proceso: deploy")
        if terminal:
            validar_ficha_deploy_terminal(ruta)
    return ruta


def huella_planos_actual():
    mapa = RAIZ / "docs/02-flujos/planos/planos.json"
    try:
        raiz = json.loads(mapa.read_text(encoding="utf-8"))
        rutas = [mapa]
        for actividad in raiz.get("actividades", []):
            ruta = mapa.parent / "actividades" / actividad["id"] / "planos.json"
            if not ruta.exists():
                # Bug 026: una actividad declarada con la entrevista a medias no
                # tiene fichero todavía; reventar aquí bloqueaba el gobierno de
                # peticiones del workspace entero. Fuera de la huella, con aviso:
                # cuando el fichero exista, la huella cambiará — como debe ser.
                print(
                    f"AVISO: actividad {actividad['id']} sin planos todavía: "
                    "fuera de la huella hasta que exista",
                    file=sys.stderr,
                )
                continue
            rutas.append(ruta)
        bundle = {
            ruta.relative_to(mapa.parent).as_posix(): json.loads(
                ruta.read_text(encoding="utf-8")
            )
            for ruta in rutas
        }
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ErrorPeticion(f"no puedo calcular la huella vigente de los planos: {exc}") from exc
    bruto = json.dumps(
        bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()


# Unidad 033 — R4. `huella_planos_actual()` existía y solo se usaba al cerrar una petición
# de flujos: al EVALUAR se aceptaba cualquier cadena, así que la trazabilidad entre una
# petición y el mapa que la encaminó era decorativa.
SALIDA = "SALIDA:"
MAPA_PLANOS = RAIZ / "docs/02-flujos/planos/planos.json"
COMANDO_HUELLA = "python3 docs/00-metodo/scripts/peticion.py huella-planos"


def mensaje_huella_discrepante(declarada, real):
    return (
        "la huella de flujo declarada no es la de los planos vigentes:\n"
        f"  declarada: {declarada}\n"
        f"  real:      {real}\n"
        f"{SALIDA} pide la huella real con `{COMANDO_HUELLA}` y vuelve a evaluar con "
        f"--huella-flujo <esa huella>"
    )


def mensaje_sin_planos():
    return (
        "AVISO: este workspace todavía no tiene planos (docs/02-flujos/planos/planos.json), "
        "así que la huella declarada no se puede contrastar con nada. "
        f"{SALIDA} cuando existan los planos, saca la huella con `{COMANDO_HUELLA}` y "
        "reevalúa la petición para que quede atada al mapa"
    )


def exigir_huella_de_flujo(declarada):
    """R4: la huella declarada al evaluar se compara con la real, o se dice que no hay."""
    if not MAPA_PLANOS.is_file():
        print(mensaje_sin_planos(), file=sys.stderr)
        return
    real = huella_planos_actual()
    if (declarada or "").strip() != real:
        raise ErrorPeticion(mensaje_huella_discrepante(declarada, real))


def cmd_huella_planos(_args):
    print(huella_planos_actual())
    return 0


def validar_proceso(pid, revision, tipo, ref):
    """Comprueba el enlace vigente incluso si la petición ya quedó cerrada.

    Se usa al reanudar un cierre: una reconciliación anterior puede haber cerrado la petición
    antes de que terminara la limpieza mecánica de la unidad.
    """
    datos = cargar(pid)
    if datos["revision"] != int(revision):
        raise ErrorPeticion(
            f"{pid} está en revisión {datos['revision']}; el proceso usa {revision}"
        )
    proceso = next(
        (
            item
            for item in datos["procesos"]
            if item.get("tipo") == tipo and item.get("ref") == ref
            and item.get("revision") == int(revision)
        ),
        None,
    )
    if not proceso:
        raise ErrorPeticion(f"{pid} no enlaza {tipo} {ref}")
    if proceso.get("revision") != int(revision):
        raise ErrorPeticion(
            f"{pid}: {tipo} {ref} enlaza revisión {proceso.get('revision')}, no {revision}"
        )
    esperado = CONTRATOS_TERMINALES[tipo]
    if proceso.get("contrato_terminal") != esperado:
        raise ErrorPeticion(
            f"{pid}: {tipo} {ref} no declara el contrato terminal {esperado}"
        )
    if tipo == "expres" and not (proceso.get("metadata") or {}).get("base_sha"):
        raise ErrorPeticion(f"{pid}: la rama exprés no conserva su SHA base")
    return proceso


def reconciliar_ids(referencias, tipo, ref, evidencia):
    """Marca un proceso terminal y cierra solo las peticiones completamente satisfechas."""
    parsed = parsear_referencias(referencias)
    with contextlib.ExitStack() as locks:
        for pid, _ in sorted(parsed):
            locks.enter_context(lock(pid))
        lote = []
        for pid, revision in parsed:
            datos = cargar(pid)
            validar_proceso(pid, revision, tipo, ref)
            proceso = next(
                item
                for item in datos["procesos"]
                if item.get("tipo") == tipo and item.get("ref") == ref
                and item.get("revision") == int(revision)
            )
            if datos["estado"] in TERMINALES:
                if not (
                    datos["estado"] == "cerrada"
                    and datos.get("resultado") == "entregada"
                    and proceso.get("estado") == "terminal"
                ):
                    raise ErrorPeticion(f"{pid} ya está {datos['estado']}; no se reconcilia")
            lote.append((datos, proceso))

        if not evidencia.strip():
            raise ErrorPeticion("la evidencia terminal no puede estar vacía")
        if tipo == "expres":
            repo, principal = repo_codigo()
            for _, proceso in lote:
                prueba = evidencia_rama_fusionada(
                    repo, ref, principal, proceso.get("metadata") or {}
                )
                if prueba is None:
                    raise ErrorPeticion(
                        "la rama exprés no contiene un cambio fusionado sobre su base"
                    )
                proceso.setdefault("metadata", {}).update(prueba)
        validar_proceso_canonico(
            tipo,
            ref,
            terminal=True,
            metadata=(lote[0][1].get("metadata") or {}) if tipo == "expres" else None,
        )
        originales = {
            datos["id"]: ruta_peticion(datos["id"]).read_bytes()
            for datos, _ in lote
        }
        try:
            for datos, proceso in lote:
                if proceso.get("estado") == "terminal":
                    continue
                proceso["estado"] = "terminal"
                proceso["evidencia"] = evidencia.strip()
                proceso["actualizado"] = ahora()
                satisface = [
                    item for item in datos["procesos"]
                    if item.get("relacion") == "satisface"
                    and item.get("revision") == datos["revision"]
                    and item.get("estado") not in {"sustituido", "cancelado"}
                ]
                pendientes = [
                    item for item in satisface if item.get("estado") != "terminal"
                ]
                # Una única orden tiene cobertura inequívoca. En fan-out, el padre debe
                # cerrar después con una evidencia de cobertura conjunta explícita.
                if len(satisface) == 1 and not pendientes:
                    datos["estado"] = "cerrada"
                    datos["resultado"] = "entregada"
                    datos["cierres"].append(
                        {
                            "resultado": "entregada",
                            "evidencia": evidencia.strip(),
                            "cobertura": f"proceso único {tipo} {ref}",
                            "fecha": ahora(),
                            "revision": datos["revision"],
                        }
                    )
                guardar(datos)
        except Exception:
            for pid, contenido in originales.items():
                escribir_bytes_atomico(ruta_peticion(pid), contenido)
            raise


def cmd_capturar(args):
    datos = nueva_peticion(args.resumen, args.texto, args.autor)
    print(f"{datos['id']} capturada · {datos['original']['resumen']}")
    return 0


def cmd_aclarar(args):
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(
                f"{args.peticion} está {datos['estado']}; reábrela antes de aclarar"
            )
        if not args.informativa:
            datos["revision"] += 1
        datos["aclaraciones"].append(
            {
                "revision": datos["revision"],
                "texto": args.texto.strip(),
                "autor": args.autor.strip(),
                "fecha": ahora(),
                "material": not args.informativa,
            }
        )
        if not args.informativa:
            datos["estado"] = "evaluando"
        guardar(datos)
    print(f"{args.peticion} actualizada a revisión {datos['revision']}")
    return 0


def cmd_reclamar(args):
    responsable = args.por.strip()
    if not responsable:
        raise ErrorPeticion("--por no puede estar vacío")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        actual = (datos.get("responsable") or "").strip()
        if actual and actual != responsable:
            raise ErrorPeticion(
                f"{args.peticion} ya está reclamada por {actual}; no la toma {responsable}"
            )
        datos["responsable"] = responsable
        datos.setdefault("reclamos", []).append(
            {"por": responsable, "fecha": ahora(), "revision": datos["revision"]}
        )
        if datos["estado"] == "capturada":
            datos["estado"] = "evaluando"
        guardar(datos)
    print(f"{args.peticion} reclamada por {responsable}")
    return 0


def resolver_ruta_tipo(ruta, tipo):
    """Separa carril y tipo de --ruta/--tipo (unidad 027, R5/R6).

    Forma nueva: --ruta es un CARRIL del vocabulario cerrado y --tipo viaja aparte.
    Forma antigua (compatibilidad retro, sin --tipo): --ruta es el tipo/proceso de siempre;
    el carril queda 'normal' implícito, con aviso por stderr. Cualquier otro valor —viejo o
    nuevo— revienta EN LA EVALUACIÓN con la lista de válidos (antes se aceptaba en silencio
    y reventaba tarde, punto 1 del lote UX P-93354696)."""
    if tipo:
        if ruta not in CARRILES:
            raise ErrorPeticion(
                f"--ruta '{ruta}' fuera del vocabulario de carriles: "
                + ", ".join(sorted(CARRILES))
            )
        return ruta, tipo
    if ruta not in CARRILES and ruta not in RUTAS_LEGACY_VALIDAS:
        raise ErrorPeticion(
            f"--ruta '{ruta}' fuera de vocabulario: usa un carril ("
            + ", ".join(sorted(CARRILES))
            + ") junto con --tipo, o -en forma antigua, sin --tipo- uno de estos: "
            + ", ".join(sorted(RUTAS_LEGACY_VALIDAS))
        )
    print(
        f"AVISO: --ruta {ruta} es la forma antigua (mezclaba carril y tipo); a partir de "
        f"ahora usa --ruta <carril> --tipo {ruta}. Se asume carril normal.",
        file=sys.stderr,
    )
    if ruta in CARRILES:
        return ruta, None
    return "normal", ruta


def cmd_evaluar(args):
    carril, tipo = resolver_ruta_tipo(args.ruta, args.tipo)
    faltan = []
    if not args.flujo:
        faltan.append("flujo")
    if not args.huella_flujo:
        faltan.append("huella del flujo")
    if args.investigacion != "plataforma" and not args.sha:
        faltan.append("SHA")
    if args.investigacion != "plataforma" and not args.ruta_codigo:
        faltan.append("ruta de código")
    if args.investigacion == "ninguna" and not args.conocimiento:
        faltan.append("conocimiento o decisión vigente")
    if args.investigacion in {"acotada", "plataforma"}:
        if not args.disparador:
            faltan.append("disparador de investigación")
        if not args.pregunta:
            faltan.append("pregunta de investigación")
    if args.investigacion == "plataforma" and not args.sintesis_plataforma:
        faltan.append("síntesis de plataforma")
    if faltan:
        raise ErrorPeticion("evaluación incompleta: falta " + ", ".join(faltan))
    exigir_huella_de_flujo(args.huella_flujo)
    if args.investigacion != "plataforma":
        repo, _ = repo_codigo()
        if git(repo, "rev-parse", "--verify", "--quiet", f"{args.sha}^{{commit}}")[0] != 0:
            raise ErrorPeticion(f"SHA de evaluación inexistente en {repo}: {args.sha}")
        for nombre in args.ruta_codigo:
            ruta = Path(nombre)
            resuelta = (repo / ruta).resolve()
            if ruta.is_absolute() or ".." in ruta.parts or not resuelta.exists() \
                    or repo.resolve() not in resuelta.parents:
                raise ErrorPeticion(f"ruta de código inexistente o insegura: {nombre}")
    for nombre in args.conocimiento:
        ruta = Path(nombre)
        resuelta = (RAIZ / ruta).resolve()
        if ruta.is_absolute() or ".." in ruta.parts or not resuelta.exists() \
                or RAIZ.resolve() not in resuelta.parents:
            raise ErrorPeticion(f"conocimiento inexistente o inseguro: {nombre}")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        evaluacion = {
            "revision": datos["revision"],
            "fecha": ahora(),
            "ruta_provisional": carril,
            "carril_provisional": carril,
            "tipo_provisional": tipo,
            "flujo": {"refs": args.flujo, "huella": args.huella_flujo},
            "codigo": {"sha": args.sha, "rutas": args.ruta_codigo},
            "conocimiento": args.conocimiento,
            "investigacion": {
                "perfil": args.investigacion,
                "motivo": args.motivo.strip(),
                "disparadores": args.disparador,
                "preguntas": args.pregunta,
                "sintesis_plataforma": args.sintesis_plataforma,
            },
        }
        datos["evaluaciones"].append(evaluacion)
        datos["estado"] = "evaluando"
        datos.pop("aparcada", None)
        guardar(datos)
        if args.investigacion == "acotada":
            renderizar_plan(datos, evaluacion)
    print(
        f"{args.peticion} evaluada · investigación {args.investigacion} · "
        f"revisión {datos['revision']}"
    )
    return 0


def cmd_enlazar(args):
    if args.tipo == "expres":
        raise ErrorPeticion("las ramas exprés solo se abren con peticion.py abrir-expres")
    revision = validar_para_orden(args.peticion)
    creado = enlazar_proceso(
        args.peticion,
        args.tipo,
        args.ref,
        revision=revision,
        relacion=args.relacion,
        contrato_terminal=args.contrato_terminal,
    )
    if not creado:
        raise ErrorPeticion(f"{args.tipo} {args.ref} ya está enlazado")
    print(f"{args.peticion} enlaza {args.tipo} {args.ref}")
    return 0


def cmd_desenlazar(args):
    """Cancela el enlace de una revisión SUSTITUIDA (unidad 027, R4/R7).

    No borra nada: el proceso queda `cancelado`, con motivo, autor y fecha. El enlace VIGENTE
    (o uno ya terminal) no se toca aquí — eso es lo que reconcilia o reencuadra, no lo que se
    desenlaza; cancelar no puede ser una puerta trasera para borrar lo que sigue vivo.
    """
    motivo = (args.motivo or "").strip()
    if not motivo:
        raise ErrorPeticion("desenlazar exige --motivo: sin motivo, no hay desenlace")
    autor = (args.autor or "").strip()
    if not autor:
        raise ErrorPeticion("desenlazar exige --autor")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        candidatos = [
            proceso for proceso in datos["procesos"]
            if proceso.get("tipo") == args.tipo and proceso.get("ref") == args.ref
        ]
        if not candidatos:
            raise ErrorPeticion(f"{args.peticion} no enlaza {args.tipo} {args.ref}")
        objetivo = next(
            (proceso for proceso in candidatos if proceso.get("estado") == "sustituido"),
            None,
        )
        if objetivo is None:
            raise ErrorPeticion(
                f"{args.peticion}: el enlace de {args.tipo} {args.ref} no es una revisión "
                "sustituida (solo se cancelan enlaces de revisiones sustituidas por "
                "reencuadrar-orden; lo vigente se reconcilia, no se borra)"
            )
        objetivo["estado"] = "cancelado"
        objetivo["actualizado"] = ahora()
        objetivo["motivo_cancelacion"] = motivo
        objetivo["autor_cancelacion"] = autor
        guardar(datos)
    print(f"{args.peticion} · {args.tipo} {args.ref} → cancelado ({motivo})")
    return 0


def cmd_comprobar_revision(args):
    datos = cargar(args.peticion)
    if datos["revision"] != args.revision:
        raise ErrorPeticion(
            f"{args.peticion} está en revisión {datos['revision']}; "
            f"la referencia usa revisión {args.revision}"
        )
    print(f"{args.peticion}@{args.revision} vigente")
    return 0


def cmd_marcar_proceso(args):
    if not args.evidencia.strip():
        raise ErrorPeticion("la evidencia no puede estar vacía")
    if args.estado == "terminal":
        reconciliar_ids(
            [f"{args.peticion}@{args.revision}"],
            args.tipo,
            args.ref,
            args.evidencia,
        )
        print(f"{args.peticion} · {args.tipo} {args.ref} → terminal")
        return 0
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        validar_proceso(args.peticion, args.revision, args.tipo, args.ref)
        proceso = next(
            item for item in datos["procesos"]
            if item.get("tipo") == args.tipo
            and item.get("ref") == args.ref
            and item.get("revision") == args.revision
        )
        proceso["estado"] = "cancelado"
        proceso["evidencia"] = args.evidencia.strip()
        proceso["actualizado"] = ahora()
        guardar(datos)
    print(f"{args.peticion} · {args.tipo} {args.ref} → cancelado")
    return 0


def cmd_reencuadrar_orden(args):
    """Hace que una orden existente adopte una aclaración material ya evaluada."""
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        if args.desde_revision >= datos["revision"]:
            raise ErrorPeticion("--desde-revision debe ser anterior a la revisión vigente")
        anterior = next(
            (
                proceso for proceso in datos["procesos"]
                if proceso.get("tipo") == args.tipo
                and proceso.get("ref") == args.ref
                and proceso.get("revision") == args.desde_revision
            ),
            None,
        )
        if not anterior:
            raise ErrorPeticion(
                f"{args.peticion} no enlaza {args.tipo} {args.ref} en revisión "
                f"{args.desde_revision}"
            )
        if anterior.get("estado") != "pendiente":
            raise ErrorPeticion(
                f"el enlace anterior está {anterior.get('estado')}; no se reencuadra"
            )
        if any(
            proceso.get("tipo") == args.tipo
            and proceso.get("ref") == args.ref
            and proceso.get("revision") == datos["revision"]
            for proceso in datos["procesos"]
        ):
            raise ErrorPeticion("la orden ya adoptó la revisión vigente")

        artefacto = validar_proceso_canonico(args.tipo, args.ref, terminal=False)
        carril, tipo_orden = contexto_proceso(args.tipo, artefacto)
        original_artefacto = None
        texto_actualizado = None
        if args.tipo in {"unidad", "bug", "auditoria", "deploy"}:
            original_artefacto = artefacto.read_bytes()
            texto = original_artefacto.decode("utf-8")
            vieja = f"{args.peticion}@{args.desde_revision}"
            nueva = f"{args.peticion}@{datos['revision']}"
            texto_actualizado, cambios = re.subn(
                rf"(?<![A-Za-z0-9-]){re.escape(vieja)}(?!\d)", nueva, texto
            )
            if cambios != 1:
                raise ErrorPeticion(
                    f"{artefacto.relative_to(RAIZ)} debe contener una sola vez {vieja}"
                )
            if args.tipo in {"unidad", "bug", "auditoria"}:
                texto_actualizado = re.sub(
                    r"^aprobado:\s*\S+", "aprobado: no", texto_actualizado,
                    count=1, flags=re.M,
                )
        validar_para_orden(
            args.peticion,
            carril=carril,
            tipo=tipo_orden,
            revision=datos["revision"],
        )
        anterior["estado"] = "sustituido"
        anterior["actualizado"] = ahora()
        datos["procesos"].append(
            {
                "tipo": args.tipo,
                "ref": args.ref,
                "relacion": anterior.get("relacion", "satisface"),
                "revision": datos["revision"],
                "estado": "pendiente",
                "contrato_terminal": anterior.get("contrato_terminal", args.tipo),
                "fecha": ahora(),
                "sustituye_revision": args.desde_revision,
                **(
                    {"metadata": dict(anterior["metadata"])}
                    if anterior.get("metadata") else {}
                ),
            }
        )
        datos["estado"] = "encaminada"
        try:
            if texto_actualizado is not None:
                escribir_bytes_atomico(artefacto, texto_actualizado.encode("utf-8"))
            guardar(datos)
        except Exception:
            if original_artefacto is not None:
                escribir_bytes_atomico(artefacto, original_artefacto)
            raise
    print(
        f"{args.tipo} {args.ref} adopta {args.peticion}@{datos['revision']}; "
        "la aprobación queda invalidada"
    )
    return 0


def cmd_reconciliar(args):
    referencia = f"{args.peticion}@{args.revision}"
    reconciliar_ids(
        [referencia], args.tipo, args.ref, args.evidencia.strip()
    )
    print(f"{referencia} reconciliada con {args.tipo} {args.ref}")
    return 0


def repo_codigo():
    try:
        return repo_config.repo_code(RAIZ)
    except repo_config.RepoConfigError as exc:
        raise ErrorPeticion(str(exc)) from exc


def git(repo, *argumentos):
    try:
        resultado = subprocess.run(
            ["git", "-C", str(repo), *argumentos],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ErrorPeticion(f"no se puede ejecutar git: {exc}") from exc
    return resultado.returncode, (resultado.stdout + resultado.stderr).strip()


def cmd_abrir_expres(args):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.slug):
        raise ErrorPeticion("slug exprés inválido: usa minúsculas, números y guiones")
    revision = validar_para_orden(args.peticion, carril="expres", tipo="expres")
    rama = f"expres-{args.peticion}-{args.slug}"
    repo, principal = repo_codigo()
    if git(repo, "rev-parse", "--is-inside-work-tree")[0] != 0:
        raise ErrorPeticion(f"no encuentro el repositorio de código en {repo}")
    if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{principal}")[0] != 0:
        raise ErrorPeticion(f"no existe la rama principal {principal} en {repo.name}")
    base_sha = git(repo, "rev-parse", principal)[1].strip()
    ya_existe = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{rama}")[0] == 0
    if not ya_existe:
        codigo, salida = git(repo, "branch", rama, principal)
        if codigo:
            raise ErrorPeticion(f"git no pudo crear {rama}: {salida}")
    try:
        enlazar_proceso(
            args.peticion,
            "expres",
            rama,
            revision=revision,
            metadata={"base_sha": base_sha, "principal": principal},
        )
    except ErrorPeticion:
        if not ya_existe:
            git(repo, "branch", "-D", rama)
        raise
    print(f"{rama} creada desde {principal} y enlazada a {args.peticion}@{revision}")
    return 0


def cmd_abrir_hotfix(args):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.slug):
        raise ErrorPeticion("slug de hotfix inválido: usa minúsculas, números y guiones")
    validar_para_orden(args.peticion, carril="normal", tipo="bug")
    unidad = Path(__file__).with_name("unidad.py")
    if not unidad.is_file():
        raise ErrorPeticion(f"falta el despachador {unidad.relative_to(RAIZ)}")
    creada = subprocess.run(
        [
            sys.executable,
            str(unidad),
            "nueva",
            "bug",
            args.slug,
            "--desde",
            args.peticion,
        ],
        cwd=RAIZ,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if creada.returncode:
        raise ErrorPeticion(
            "no pude crear la ficha del hotfix:\n" + (creada.stdout + creada.stderr).strip()
        )
    candidatas = sorted((RAIZ / "docs/bugs").glob(f"[0-9][0-9][0-9]-{args.slug}.md"))
    if len(candidatas) != 1:
        raise ErrorPeticion(
            f"no puedo identificar la ficha creada para el hotfix {args.slug}"
        )
    ficha = candidatas[0]
    texto_ficha = ficha.read_text(encoding="utf-8")
    texto_ficha, cambios = re.subn(
        r"^(\s*[-*]\s*\*\*Severidad preliminar:\*\*)\s*.*$",
        r"\1 P0 (producción caída declarada por el usuario)",
        texto_ficha,
        count=1,
        flags=re.M,
    )
    if cambios != 1:
        raise ErrorPeticion(f"{ficha.relative_to(RAIZ)} no tiene línea de severidad")
    ficha.write_text(texto_ficha, encoding="utf-8")
    nombre = ficha.stem
    despachada = subprocess.run(
        [
            sys.executable,
            str(unidad),
            "despachar",
            nombre,
            "--force",
            "--motivo",
            args.motivo,
        ],
        cwd=RAIZ,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if despachada.returncode:
        raise ErrorPeticion(
            "la petición y la ficha P0 quedan guardadas, pero el despacho falló:\n"
            + (despachada.stdout + despachada.stderr).strip()
        )
    print(creada.stdout, end="")
    print(despachada.stdout, end="")
    print(f"{args.peticion} → hotfix {nombre} despachado")
    return 0


def cmd_cerrar(args):
    if args.resultado not in RESULTADOS:
        raise ErrorPeticion(f"resultado fuera de vocabulario: {args.resultado}")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        pendientes = [
            p["ref"]
            for p in datos["procesos"]
            if p.get("relacion") == "satisface"
            and p.get("revision") == datos["revision"]
            and p.get("estado") not in {"terminal", "sustituido", "cancelado"}
        ]
        if pendientes:
            raise ErrorPeticion("quedan procesos abiertos: " + ", ".join(pendientes))
        satisface = [
            p for p in datos["procesos"]
            if p.get("relacion") == "satisface"
            and p.get("revision") == datos["revision"]
            and p.get("estado") != "sustituido"
        ]
        if args.resultado == "entregada" and not satisface:
            raise ErrorPeticion("entregada exige al menos un proceso que la satisfaga")
        if args.resultado == "entregada" and any(
            proceso.get("estado") != "terminal" for proceso in satisface
        ):
            raise ErrorPeticion(
                "entregada exige que todos los procesos que satisfacen estén terminales"
            )
        if not args.evidencia.strip() or not args.cobertura.strip():
            raise ErrorPeticion("evidencia y cobertura no pueden estar vacías")
        datos["estado"] = "cerrada"
        datos["resultado"] = args.resultado
        datos["cierres"].append(
            {
                "resultado": args.resultado,
                "evidencia": args.evidencia.strip(),
                "cobertura": args.cobertura.strip(),
                "fecha": ahora(),
                "revision": datos["revision"],
            }
        )
        guardar(datos)
    print(f"{args.peticion} cerrada · {args.resultado}")
    return 0


def cmd_aparcar(args):
    if not args.revisar_el and not args.condicion:
        raise ErrorPeticion(
            "aparcar exige --revisar-el AAAA-MM-DD o --condicion para retomarla"
        )
    if args.revisar_el:
        try:
            datetime.date.fromisoformat(args.revisar_el)
        except ValueError as exc:
            raise ErrorPeticion("--revisar-el debe ser una fecha AAAA-MM-DD") from exc
    if not args.motivo.strip() or not args.por.strip():
        raise ErrorPeticion("aparcar exige motivo y responsable no vacíos")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        datos["estado"] = "aparcada"
        datos["aparcada"] = {
            "motivo": args.motivo.strip(),
            "revisar_el": args.revisar_el,
            "condicion": args.condicion,
            "responsable": args.por.strip(),
            "fecha": ahora(),
        }
        guardar(datos)
    print(f"{args.peticion} aparcada")
    return 0


def cmd_reanudar(args):
    responsable = args.por.strip()
    if not responsable:
        raise ErrorPeticion("--por no puede estar vacío")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] != "aparcada" or not datos.get("aparcada"):
            raise ErrorPeticion(f"{args.peticion} no está aparcada")
        actual = (datos.get("responsable") or "").strip()
        if actual and actual != responsable:
            raise ErrorPeticion(f"{args.peticion} pertenece a {actual}")
        anterior = dict(datos.pop("aparcada"))
        anterior.update({"reanudada": ahora(), "por": responsable})
        datos.setdefault("historial_aparcados", []).append(anterior)
        datos["responsable"] = responsable
        datos["estado"] = "evaluando"
        guardar(datos)
    print(f"{args.peticion} reanudada por {responsable}")
    return 0


def cmd_reabrir(args):
    if not args.motivo.strip() or not args.por.strip():
        raise ErrorPeticion("reabrir exige motivo y responsable no vacíos")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] not in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} no está cerrada ni cancelada")
        datos.setdefault("reaperturas", []).append(
            {
                "estado_anterior": datos["estado"],
                "resultado_anterior": datos.get("resultado"),
                "motivo": args.motivo.strip(),
                "por": args.por.strip(),
                "fecha": ahora(),
            }
        )
        datos["revision"] += 1
        datos["estado"] = "evaluando"
        datos.pop("resultado", None)
        guardar(datos)
    print(f"{args.peticion} reabierta en revisión {datos['revision']}")
    return 0


def cmd_relacionar(args):
    cargar(args.con)
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if not any(
            relacion.get("tipo") == args.tipo and relacion.get("ref") == args.con
            for relacion in datos["relaciones"]
        ):
            datos["relaciones"].append(
                {"tipo": args.tipo, "ref": args.con, "fecha": ahora()}
            )
            guardar(datos)
    print(f"{args.peticion} · {args.tipo} → {args.con}")
    return 0


def cmd_duplicar(args):
    if args.peticion == args.de:
        raise ErrorPeticion("una petición no puede ser duplicada de sí misma")
    cargar(args.de)
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        datos["estado"] = "cerrada"
        datos["resultado"] = "duplicada"
        datos["relaciones"].append(
            {"tipo": "duplicada_de", "ref": args.de, "fecha": ahora()}
        )
        datos["cierres"].append(
            {"resultado": "duplicada", "ref": args.de, "fecha": ahora()}
        )
        guardar(datos)
    print(f"{args.peticion} cerrada como duplicada de {args.de}")
    return 0


def cmd_cancelar(args):
    if not args.motivo.strip() or not args.por.strip():
        raise ErrorPeticion("cancelar exige motivo y responsable no vacíos")
    with lock(args.peticion):
        datos = cargar(args.peticion)
        if datos["estado"] in TERMINALES:
            raise ErrorPeticion(f"{args.peticion} ya está {datos['estado']}")
        abiertos = [
            proceso.get("ref", "?") for proceso in datos["procesos"]
            if proceso.get("relacion") == "satisface"
            and proceso.get("estado") not in {"terminal", "cancelado", "sustituido"}
        ]
        if abiertos:
            raise ErrorPeticion(
                "cancela o termina cada proceso antes de cancelar la petición: "
                + ", ".join(abiertos)
            )
        datos["estado"] = "cancelada"
        datos["resultado"] = "cancelada"
        datos["cierres"].append(
            {
                "resultado": "cancelada",
                "motivo": args.motivo.strip(),
                "por": args.por.strip(),
                "fecha": ahora(),
            }
        )
        guardar(datos)
    print(f"{args.peticion} cancelada")
    return 0


def cmd_estado(args):
    datos = cargar(args.peticion)
    print(
        f"{datos['id']} · {datos['estado']} · revisión {datos['revision']} · "
        f"{datos['original']['resumen']}"
    )
    return 0


def cmd_listar(args):
    encontrados = 0
    for ruta in sorted(PETICIONES.glob("P-*/peticion.json")):
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if args.estado and datos.get("estado") != args.estado:
            continue
        encontrados += 1
        print(
            f"{datos.get('id')} · {datos.get('estado')} · "
            f"{datos.get('original', {}).get('resumen', '')}"
        )
    if not encontrados:
        print("sin peticiones")
    return 0


def parser_cli():
    parser = argparse.ArgumentParser(
        description="Captura y gobierna peticiones antes de abrir trabajo"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("capturar", help="primera escritura de un encargo accionable")
    p.add_argument("--resumen", required=True)
    p.add_argument("--texto", required=True)
    p.add_argument("--autor", required=True)
    p.set_defaults(func=cmd_capturar)

    p = sub.add_parser("desbloquear", help="retira un lock huérfano tras comprobar su dueño")
    p.add_argument("peticion")
    p.add_argument("--forzar", action="store_true")
    p.add_argument("--motivo", default="")
    p.set_defaults(func=cmd_desbloquear)

    p = sub.add_parser("aclarar", help="añade una aclaración sin tocar el original")
    p.add_argument("peticion")
    p.add_argument("--texto", required=True)
    p.add_argument("--autor", required=True)
    p.add_argument("--informativa", action="store_true")
    p.set_defaults(func=cmd_aclarar)

    p = sub.add_parser("reclamar", help="asigna un único responsable al triaje")
    p.add_argument("peticion")
    p.add_argument("--por", required=True)
    p.set_defaults(func=cmd_reclamar)

    p = sub.add_parser("evaluar", help="contrasta alcance y decide investigación")
    p.add_argument("peticion")
    p.add_argument("--ruta", required=True,
                    help="carril (expres|directo|normal|completo|hotfix|documental); en forma "
                         "antigua, sin --tipo, un tipo/proceso (compatibilidad retro)")
    p.add_argument("--tipo",
                    help="tipo de la unidad (bug|feature|…) o del proceso; junto con --ruta "
                         "como carril, evalúa el par en una sola pasada (unidad 027, R5)")
    p.add_argument("--investigacion", required=True, choices=sorted(PERFILES_INVESTIGACION))
    p.add_argument("--motivo", required=True)
    p.add_argument("--flujo", action="append", default=[])
    p.add_argument("--huella-flujo")
    p.add_argument("--sha")
    p.add_argument("--ruta-codigo", action="append", default=[])
    p.add_argument("--conocimiento", action="append", default=[])
    p.add_argument("--disparador", action="append", default=[])
    p.add_argument("--pregunta", action="append", default=[])
    p.add_argument("--sintesis-plataforma")
    p.set_defaults(func=cmd_evaluar)

    p = sub.add_parser(
        "huella-planos",
        help="imprime la huella real del bundle de planos vigente (la que exige evaluar)",
    )
    p.set_defaults(func=cmd_huella_planos)

    p = sub.add_parser("enlazar", help="enlaza un proceso canónico")
    p.add_argument("peticion")
    p.add_argument("--tipo", required=True, choices=sorted(TIPOS_PROCESO))
    p.add_argument("--ref", required=True)
    p.add_argument("--relacion", default="satisface", choices=sorted(RELACIONES_PROCESO))
    p.add_argument("--contrato-terminal")
    p.set_defaults(func=cmd_enlazar)

    p = sub.add_parser(
        "desenlazar", help="cancela el enlace de una revisión sustituida (con motivo)"
    )
    p.add_argument("peticion")
    p.add_argument("--tipo", required=True, choices=sorted(TIPOS_PROCESO))
    p.add_argument("--ref", required=True)
    p.add_argument("--motivo", required=True)
    p.add_argument("--autor", required=True)
    p.set_defaults(func=cmd_desenlazar)

    p = sub.add_parser("comprobar-revision", help="comprueba que una orden sigue vigente")
    p.add_argument("peticion")
    p.add_argument("--revision", required=True, type=int)
    p.set_defaults(func=cmd_comprobar_revision)

    p = sub.add_parser("marcar-proceso", help="registra el resultado observado de un enlace")
    p.add_argument("peticion")
    p.add_argument("--revision", required=True, type=int)
    p.add_argument("--tipo", required=True, choices=sorted(TIPOS_PROCESO))
    p.add_argument("--ref", required=True)
    p.add_argument("--estado", required=True, choices=("terminal", "cancelado"))
    p.add_argument("--evidencia", required=True)
    p.set_defaults(func=cmd_marcar_proceso)

    p = sub.add_parser(
        "reencuadrar-orden",
        help="hace que una orden adopte la revisión material ya reevaluada",
    )
    p.add_argument("peticion")
    p.add_argument("--desde-revision", required=True, type=int)
    p.add_argument("--tipo", required=True, choices=sorted(TIPOS_PROCESO))
    p.add_argument("--ref", required=True)
    p.set_defaults(func=cmd_reencuadrar_orden)

    p = sub.add_parser("reconciliar", help="reconcilia el cierre de un proceso enlazado")
    p.add_argument("peticion")
    p.add_argument("--revision", required=True, type=int)
    p.add_argument("--tipo", required=True, choices=sorted(TIPOS_PROCESO))
    p.add_argument("--ref", required=True)
    p.add_argument("--evidencia", required=True)
    p.set_defaults(func=cmd_reconciliar)

    p = sub.add_parser("abrir-expres", help="crea la rama exprés canónica desde una petición")
    p.add_argument("peticion")
    p.add_argument("slug")
    p.set_defaults(func=cmd_abrir_expres)

    p = sub.add_parser("abrir-hotfix", help="crea, tria P0 y despacha un bug de emergencia")
    p.add_argument("peticion")
    p.add_argument("slug")
    p.add_argument("--motivo", required=True)
    p.set_defaults(func=cmd_abrir_hotfix)

    p = sub.add_parser("cerrar", help="cierra solo cuando todos los enlaces bloqueantes terminan")
    p.add_argument("peticion")
    p.add_argument("--resultado", required=True, choices=sorted(RESULTADOS))
    p.add_argument("--evidencia", required=True)
    p.add_argument("--cobertura", required=True)
    p.set_defaults(func=cmd_cerrar)

    p = sub.add_parser("aparcar", help="aplaza con condición explícita de retorno")
    p.add_argument("peticion")
    p.add_argument("--motivo", required=True)
    p.add_argument("--revisar-el")
    p.add_argument("--condicion")
    p.add_argument("--por", required=True)
    p.set_defaults(func=cmd_aparcar)

    p = sub.add_parser("reanudar", help="devuelve una petición aparcada a evaluación")
    p.add_argument("peticion")
    p.add_argument("--por", required=True)
    p.set_defaults(func=cmd_reanudar)

    p = sub.add_parser("reabrir", help="abre una revisión nueva sin borrar el cierre anterior")
    p.add_argument("peticion")
    p.add_argument("--motivo", required=True)
    p.add_argument("--por", required=True)
    p.set_defaults(func=cmd_reabrir)

    p = sub.add_parser("relacionar", help="enlaza peticiones sin convertirlas en órdenes")
    p.add_argument("peticion")
    p.add_argument("--tipo", required=True, choices=("padre", "duplicada_de"))
    p.add_argument("--con", required=True)
    p.set_defaults(func=cmd_relacionar)

    p = sub.add_parser("duplicar", help="cierra como duplicada de la petición canónica")
    p.add_argument("peticion")
    p.add_argument("--de", required=True)
    p.set_defaults(func=cmd_duplicar)

    p = sub.add_parser("cancelar", help="detiene sin borrar historia")
    p.add_argument("peticion")
    p.add_argument("--motivo", required=True)
    p.add_argument("--por", required=True)
    p.set_defaults(func=cmd_cancelar)

    p = sub.add_parser("estado", help="muestra una petición")
    p.add_argument("peticion")
    p.set_defaults(func=cmd_estado)

    p = sub.add_parser("listar", help="lista la cola persistente")
    p.add_argument("--estado", choices=sorted(ESTADOS))
    p.set_defaults(func=cmd_listar)
    return parser


def main():
    args = parser_cli().parse_args()
    try:
        return args.func(args)
    except ErrorPeticion as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
