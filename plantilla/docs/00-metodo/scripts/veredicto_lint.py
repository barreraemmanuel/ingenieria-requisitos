#!/usr/bin/env python3
"""Decide si los hallazgos estructurados de los linters bloquean un cierre.

La identidad no depende del texto humano: usa id, sujeto, ruta relativa e instancia. La
diferencia es de multiconjuntos para que un segundo ejemplar no desaparezca detrás del
primero. Este módulo no ejecuta linters ni git; quien integra `unidad.py` le entrega dos
snapshots ya obtenidos sobre la misma copia inmutable del taller.
"""

from collections import Counter, namedtuple
import datetime
from pathlib import PurePosixPath, PureWindowsPath
import re


CAMPOS_IDENTIDAD = ("id", "sujeto", "ruta", "instancia")
CAMPOS_HALLAZGO = frozenset((*CAMPOS_IDENTIDAD, "severidad"))
CAMPOS_EVIDENCIA = frozenset((
    "base_revision", "head_revision", "snapshot_id",
    "base_evaluada_en", "head_evaluada_en",
))
SEVERIDADES = {"FAIL", "WARN"}
Veredicto = namedtuple("Veredicto", "bloquea agrega motivo salida meta")
RE_SUJETO = re.compile(
    r"(?:taller|unidad:\d{3}(?:-[a-z0-9][a-z0-9-]*)?|"
    r"bug:\d{3}(?:-[a-z0-9][a-z0-9-]*)?|"
    r"peticion:P-\d{8}-[a-f0-9]{8}(?:@\d+)?)"
)
RE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")


def _normalizar_ruta(valor):
    if not isinstance(valor, str):
        raise ValueError("ruta debe ser texto JSON")
    texto = valor
    ruta = PurePosixPath(texto)
    ruta_windows = PureWindowsPath(texto)
    if (not texto or texto != texto.strip() or "\\" in texto
            or ruta.is_absolute() or ruta_windows.drive
            or ruta_windows.is_absolute() or ".." in ruta.parts
            or ruta.as_posix() != texto):
        raise ValueError("ruta debe ser relativa, normalizada y confinada")
    return ruta.as_posix()


def _normalizar_evidencia(valor):
    if not isinstance(valor, dict) or set(valor) != CAMPOS_EVIDENCIA:
        recibidos = sorted(valor) if isinstance(valor, dict) else type(valor).__name__
        raise ValueError(
            "evidencia de revisiones incompleta: "
            f"esperados {sorted(CAMPOS_EVIDENCIA)}, recibidos {recibidos}"
        )
    evidencia = {campo: str(valor.get(campo, "")).strip() for campo in CAMPOS_EVIDENCIA}
    vacios = sorted(campo for campo, contenido in evidencia.items() if not contenido)
    if vacios:
        raise ValueError("evidencia sin " + ", ".join(vacios))
    if evidencia["base_revision"] == evidencia["head_revision"]:
        raise ValueError("base_revision y head_revision deben ser distintas")
    for campo in ("base_evaluada_en", "head_evaluada_en"):
        try:
            instante = datetime.datetime.fromisoformat(
                evidencia[campo].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(f"{campo} no es una fecha ISO") from exc
        if instante.tzinfo is None:
            raise ValueError(f"{campo} no incluye zona horaria")
    return evidencia


def _normalizar(hallazgo):
    if not isinstance(hallazgo, dict):
        raise ValueError("cada hallazgo debe ser un objeto JSON")
    if set(hallazgo) != CAMPOS_HALLAZGO:
        raise ValueError(
            "campos de hallazgo distintos del contrato: "
            f"esperados {sorted(CAMPOS_HALLAZGO)}, recibidos {sorted(hallazgo)}"
        )
    no_textuales = [campo for campo in CAMPOS_IDENTIDAD
                    if not isinstance(hallazgo.get(campo), str)]
    if no_textuales:
        raise ValueError("identidad JSON no textual: " + ", ".join(no_textuales))
    faltan = [campo for campo in (*CAMPOS_IDENTIDAD, "severidad")
              if not str(hallazgo.get(campo, "")).strip()]
    if faltan:
        raise ValueError("hallazgo sin " + ", ".join(faltan))
    severidad = str(hallazgo["severidad"]).upper().strip()
    if severidad not in SEVERIDADES:
        raise ValueError(f"severidad fuera del vocabulario: {severidad}")
    id_ = str(hallazgo["id"]).strip()
    if not RE_ID.fullmatch(id_):
        raise ValueError(f"id fuera del vocabulario: {id_}")
    sujeto = str(hallazgo["sujeto"]).strip()
    if not RE_SUJETO.fullmatch(sujeto):
        raise ValueError(f"sujeto fuera del vocabulario: {sujeto}")
    normalizado = dict(hallazgo)
    normalizado.update({
        "id": id_,
        "severidad": severidad,
        "sujeto": sujeto,
        "ruta": _normalizar_ruta(hallazgo["ruta"]),
        "instancia": str(hallazgo["instancia"]).strip(),
    })
    return normalizado


def _lista(valor, nombre):
    if not isinstance(valor, list):
        raise ValueError(f"{nombre} no es una lista de hallazgos")
    return [_normalizar(item) for item in valor]


def _identidad(hallazgo):
    return tuple(hallazgo[campo] for campo in CAMPOS_IDENTIDAD)


def _expandir(contador, por_identidad):
    salida = []
    for identidad, cantidad in contador.items():
        salida.extend([por_identidad[identidad]] * cantidad)
    return salida


def _hallazgos_nuevos(base, head):
    """FAIL de HEAD que exceden el multiconjunto de FAIL de base."""
    fallos_base = [item for item in base if item["severidad"] == "FAIL"]
    fallos_head = [item for item in head if item["severidad"] == "FAIL"]
    cuenta = Counter(map(_identidad, fallos_head)) - Counter(map(_identidad, fallos_base))
    indice = {_identidad(item): item for item in fallos_head}
    return _expandir(cuenta, indice)


def veredicto_cierre(base, head, unidad, peticiones, evidencia=None):
    """Devuelve un veredicto cerrado ante datos inválidos, propios o FAIL nuevos."""
    try:
        base_n = _lista(base, "base")
        head_n = _lista(head, "head")
        evidencia_n = _normalizar_evidencia(evidencia)
        if not isinstance(unidad, str) or not unidad.strip():
            raise ValueError("unidad ausente")
        if not isinstance(peticiones, (list, tuple, set)):
            raise ValueError("peticiones no es una colección")
        propios = {f"unidad:{unidad.strip()}"}
        propios.update(f"peticion:{str(pid).strip()}" for pid in peticiones if str(pid).strip())
    except (TypeError, ValueError) as exc:
        return Veredicto(
            True, 0, f"fallo de infraestructura del linter: {exc}",
            "SALIDA: ejecuta `python3 docs/00-metodo/scripts/lint_metodo.py --json | "
            "python3 -m json.tool`, corrige el esquema y repite el cierre.",
            {"propios": [], "nuevos": [], "ajenos_preexistentes": 0,
             "evidencia": {}},
        )

    fallos_head = [item for item in head_n if item["severidad"] == "FAIL"]
    hallazgos_propios = [item for item in fallos_head if item["sujeto"] in propios]
    hallazgos_nuevos = _hallazgos_nuevos(base_n, head_n)
    fallos_base = [item for item in base_n if item["severidad"] == "FAIL"]
    preexistentes = Counter(map(_identidad, fallos_base)) & Counter(
        map(_identidad, fallos_head)
    )
    indice_head = {_identidad(item): item for item in fallos_head}
    ajenos = sum(
        cantidad for identidad, cantidad in preexistentes.items()
        if indice_head[identidad]["sujeto"] not in propios
    )
    bloquea = bool(hallazgos_propios or hallazgos_nuevos)
    if bloquea:
        motivo = (f"{len(hallazgos_propios)} hallazgo(s) propio(s) y "
                  f"{len(hallazgos_nuevos)} FAIL nuevo(s)")
        salida = ("SALIDA: corrige los hallazgos propios/nuevos, ejecuta de nuevo "
                  "`python3 docs/00-metodo/scripts/lint_metodo.py --json` y repite el cierre.")
    else:
        motivo = "sin FAIL propios ni nuevos"
        salida = (f"{ajenos} hallazgos ajenos preexistentes, no bloquean: "
                  "`python3 docs/00-metodo/scripts/lint_metodo.py`")
    return Veredicto(
        bloquea, ajenos, motivo, salida,
        {
            "propios": hallazgos_propios,
            "nuevos": hallazgos_nuevos,
            "ajenos_preexistentes": ajenos,
            "evidencia": evidencia_n,
        },
    )
