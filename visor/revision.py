#!/usr/bin/env python3
"""Dominio de revisión humana de los planos.

Mantiene feedback, preparación, aprobaciones verificables, snapshots y
comparaciones. No conoce HTTP ni HTML; sus funciones trabajan sobre el
``planos.json`` raíz para poder probarlas sin servidor.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent


def ahora():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def leer_json(ruta, defecto=None):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defecto


def escribir_json(ruta, datos):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporal = tempfile.mkstemp(
        prefix=".%s-" % ruta.name, dir=str(ruta.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as fichero:
            fichero.write(contenido)
        os.replace(temporal, ruta)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def rutas_planos(mapa):
    mapa = Path(mapa).resolve()
    datos = leer_json(mapa)
    if not isinstance(datos, dict):
        raise ValueError("no pude leer el planos.json raíz")
    rutas = [mapa]
    for actividad in datos.get("actividades", []):
        if not actividad.get("id"):
            continue
        ruta = mapa.parent / "actividades" / actividad["id"] / "planos.json"
        # Una actividad "sin empezar" todavía no tiene planos: es un estado
        # normal del método (el mapa se cartografía entero y las actividades
        # se especifican una a una), no un error. La completitud la exige
        # validar.py --perfil revision, que es la puerta de aprobación.
        if ruta.is_file():
            rutas.append(ruta)
    return rutas


def nombre_relativo(mapa, ruta):
    return Path(ruta).resolve().relative_to(Path(mapa).resolve().parent).as_posix()


def bundle_planos(mapa):
    return {
        nombre_relativo(mapa, ruta): leer_json(ruta)
        for ruta in rutas_planos(mapa)
    }


def huella_bundle(bundle):
    bruto = json.dumps(
        bundle,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(bruto).hexdigest()


def huella_planos(mapa):
    return huella_bundle(bundle_planos(mapa))


# Unidad 033 — R3. El visor deja rastro de sesión en `.runtime/visor-<puerto>.log` desde
# que existe; nadie lo leía, así que el mapa de negocio se podía aprobar sin haberlo
# enseñado (ocurrió dos veces en un día). Aprobar sin mirar es firmar a ciegas.
COMANDO_VISOR = "python3 docs/00-metodo/requisitos/requisitos.py abrir"
MENSAJE_SIN_VISOR = (
    "no consta que el visor se haya abierto sobre estos planos DESPUÉS de su último "
    "cambio: sin ese rastro, la aprobación firma algo que nadie ha visto. "
    "SALIDA: ábrelo, míralo y aprueba después con `%s`" % COMANDO_VISOR
)


def rastro_visor(mapa):
    """Momento del rastro de sesión del visor sobre el workspace de estos planos.

    ``planos.json`` vive en ``<workspace>/docs/02-flujos/planos/``; el rastro, en
    ``<workspace>/.runtime/``. Sin workspace reconocible no hay rastro que buscar.
    """
    mapa = Path(mapa).resolve()
    if len(mapa.parents) < 4:
        return None
    runtime = mapa.parents[3] / ".runtime"
    momentos = [
        registro.stat().st_mtime
        for registro in runtime.glob("visor-*.log")
        if registro.is_file()
    ]
    return max(momentos) if momentos else None


def momento_planos(mapa):
    """Última escritura de cualquiera de los planos del bundle."""
    return max(Path(ruta).stat().st_mtime for ruta in rutas_planos(mapa))


def exigir_visor_visto(mapa):
    visto = rastro_visor(mapa)
    if visto is None or visto < momento_planos(mapa):
        raise ValueError(MENSAJE_SIN_VISOR)


def ruta_feedback(mapa):
    return Path(mapa).resolve().parent / "feedback.json"


def ruta_aprobacion(mapa):
    return Path(mapa).resolve().parent / "aprobacion.json"


def leer_feedback(mapa):
    return leer_json(
        ruta_feedback(mapa), {"version": 1, "comentarios": []}
    )


def anadir_feedback(mapa, texto, contexto=None):
    texto = " ".join(str(texto or "").split())
    if not texto:
        raise ValueError("el comentario está vacío")
    if len(texto) > 4000:
        raise ValueError("el comentario supera 4000 caracteres")
    datos = leer_feedback(mapa)
    usados = []
    for comentario in datos["comentarios"]:
        try:
            usados.append(int(comentario["id"].split("-", 1)[1]))
        except (KeyError, ValueError, IndexError):
            continue
    comentario = {
        "id": "FB-%d" % ((max(usados) if usados else 0) + 1),
        "fecha": ahora(),
        "estado": "pendiente",
        "texto": texto,
        "contexto": contexto if isinstance(contexto, dict) else {},
    }
    datos["comentarios"].append(comentario)
    escribir_json(ruta_feedback(mapa), datos)
    return comentario


def resolver_feedback(mapa, identificador):
    datos = leer_feedback(mapa)
    for comentario in datos["comentarios"]:
        if comentario.get("id") == identificador:
            comentario["estado"] = "resuelto"
            comentario["resuelto_en"] = ahora()
            escribir_json(ruta_feedback(mapa), datos)
            return comentario
    raise ValueError("no existe el comentario %s" % identificador)


def ejecutar_validador(mapa, perfil="revision", extra=None):
    r = subprocess.run(
        [
            sys.executable,
            str(BASE / "validar.py"),
            "--datos",
            str(Path(mapa).resolve()),
            "--perfil",
            perfil,
        ] + list(extra or []),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lineas = [linea.strip() for linea in r.stdout.splitlines() if linea.strip()]
    return {
        "valido": r.returncode == 0,
        "errores": [
            linea.removeprefix("ERROR  ") for linea in lineas
            if linea.startswith("ERROR  ")
        ],
        "avisos": [
            linea.removeprefix("AVISO  ") for linea in lineas
            if linea.startswith("AVISO  ")
        ],
        "salida": r.stdout,
    }


def estado_revision(mapa):
    validacion = ejecutar_validador(mapa, "revision")
    feedback = leer_feedback(mapa)
    pendientes = [
        comentario for comentario in feedback["comentarios"]
        if comentario.get("estado") == "pendiente"
    ]
    recibo = leer_json(ruta_aprobacion(mapa), None)
    return {
        "listo": validacion["valido"] and not pendientes,
        "validacion": validacion,
        "feedback_pendiente": len(pendientes),
        "bloqueos": validacion["errores"] + (
            ["Hay %d comentario(s) pendiente(s)." % len(pendientes)]
            if pendientes else []
        ),
        "aprobacion": recibo,
        "aprobacion_vigente": aprobacion_vigente(mapa),
    }


def supuestos_propuestos(mapa):
    resultado = []
    for ruta in rutas_planos(mapa):
        datos = leer_json(ruta)
        for supuesto in (datos.get("definicion") or {}).get("supuestos", []):
            if supuesto.get("estado") == "propuesto":
                resultado.append(
                    {
                        "plano": nombre_relativo(mapa, ruta),
                        "id": supuesto.get("id"),
                        "texto": supuesto.get("texto"),
                    }
                )
    return resultado


def siguiente_version(mapa):
    versiones = [
        entrada.get("version", 0) for entrada in listar_historial(mapa)
    ]
    return (max(versiones) if versiones else 0) + 1


def aprobar(mapa, por, confirmar_supuestos=False):
    por = " ".join(str(por or "").split())
    if not por:
        raise ValueError("falta la identidad de quien aprueba")
    if len(por) > 120:
        raise ValueError("la identidad supera 120 caracteres")
    estado = estado_revision(mapa)
    if estado["feedback_pendiente"]:
        raise ValueError("hay comentarios pendientes de resolver")
    if not estado["validacion"]["valido"]:
        raise ValueError(
            "los planos no superan revisión: %s"
            % "; ".join(estado["validacion"]["errores"][:5])
        )
    propuestos = supuestos_propuestos(mapa)
    if propuestos and not confirmar_supuestos:
        raise ValueError("hay supuestos propuestos que deben confirmarse")
    exigir_visor_visto(mapa)

    originales = {
        ruta: ruta.read_text(encoding="utf-8") for ruta in rutas_planos(mapa)
    }
    try:
        for ruta in originales:
            datos = leer_json(ruta)
            definicion = datos.setdefault("definicion", {})
            definicion["estado"] = "aprobado"
            if confirmar_supuestos:
                for supuesto in definicion.get("supuestos", []):
                    if supuesto.get("estado") == "propuesto":
                        supuesto["estado"] = "confirmado"
            escribir_json(ruta, datos)
        validacion = ejecutar_validador(mapa, "revision")
        if not validacion["valido"]:
            raise ValueError(
                "la aprobación dejó planos inválidos: %s"
                % "; ".join(validacion["errores"][:5])
            )
    except Exception:
        for ruta, contenido in originales.items():
            ruta.write_text(contenido, encoding="utf-8")
        raise

    bundle = bundle_planos(mapa)
    version = siguiente_version(mapa)
    recibo = {
        "version": version,
        "estado": "aprobado",
        "por": por,
        "fecha": ahora(),
        "huella": huella_bundle(bundle),
        "planos": sorted(bundle),
    }
    historial = Path(mapa).resolve().parent / "historial"
    snapshot = {
        "version": version,
        "aprobacion": recibo,
        "planos": bundle,
    }
    escribir_json(
        historial / ("%04d-%s.json" % (version, recibo["huella"][:12])),
        snapshot,
    )
    escribir_json(ruta_aprobacion(mapa), recibo)
    return recibo


def listar_historial(mapa):
    historial = Path(mapa).resolve().parent / "historial"
    entradas = []
    for ruta in sorted(historial.glob("*.json")) if historial.is_dir() else []:
        snapshot = leer_json(ruta, {})
        aprobacion = snapshot.get("aprobacion") or {}
        entradas.append(
            {
                "version": snapshot.get("version"),
                "por": aprobacion.get("por"),
                "fecha": aprobacion.get("fecha"),
                "huella": aprobacion.get("huella"),
                "fichero": ruta.name,
            }
        )
    return entradas


def ultimo_snapshot(mapa):
    entradas = listar_historial(mapa)
    if not entradas:
        return None
    elegido = max(entradas, key=lambda x: x.get("version") or 0)
    return leer_json(
        Path(mapa).resolve().parent / "historial" / elegido["fichero"]
    )


def comparar_bloques(anterior, actual):
    claves_anterior = set(anterior or {})
    claves_actual = set(actual or {})
    return {
        "anadidos": sorted(claves_actual - claves_anterior),
        "eliminados": sorted(claves_anterior - claves_actual),
        "cambiados": sorted(
            clave for clave in claves_actual & claves_anterior
            if actual[clave] != anterior[clave]
        ),
    }


def comparar_ultima_aprobacion(mapa):
    snapshot = ultimo_snapshot(mapa)
    actual = bundle_planos(mapa)
    if not snapshot:
        return {
            "hay_aprobacion": False,
            "identico": False,
            "planos": {},
        }
    anterior = snapshot.get("planos") or {}
    nombres = sorted(set(anterior) | set(actual))
    planos = {}
    for nombre in nombres:
        planos[nombre] = comparar_bloques(
            anterior.get(nombre, {}), actual.get(nombre, {})
        )
    identico = anterior == actual
    return {
        "hay_aprobacion": True,
        "version": snapshot.get("version"),
        "huella_aprobada": (snapshot.get("aprobacion") or {}).get("huella"),
        "huella_actual": huella_bundle(actual),
        "identico": identico,
        "planos": planos,
    }


def aprobacion_vigente(mapa):
    recibo = leer_json(ruta_aprobacion(mapa), None)
    if not recibo or recibo.get("estado") != "aprobado":
        return False
    try:
        return recibo.get("huella") == huella_planos(mapa)
    except (OSError, ValueError):
        return False


def solicitar_cambios(mapa, texto, contexto=None):
    comentario = anadir_feedback(mapa, texto, contexto)
    for ruta in rutas_planos(mapa):
        datos = leer_json(ruta)
        datos.setdefault("definicion", {})["estado"] = "borrador"
        escribir_json(ruta, datos)
    recibo = leer_json(ruta_aprobacion(mapa), None)
    if recibo:
        recibo["estado"] = "cambios solicitados"
        recibo["invalidada_en"] = ahora()
        escribir_json(ruta_aprobacion(mapa), recibo)
    return comentario
