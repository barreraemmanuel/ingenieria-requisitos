#!/usr/bin/env python3
"""Contrato JSON v1 para las presentaciones locales."""

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

TIPOS = {"bandeja", "lector", "propuesta", "validacion"}
COMUNES = {"id", "tipo", "titulo", "version"}
CAMPOS = {
    "bandeja": COMUNES | {"estado", "peticiones"},
    "lector": COMUNES | {"variante", "preguntas", "hechos", "fuentes", "hallazgos", "conclusiones", "limites"},
    "propuesta": COMUNES | {"resumen", "opciones", "comentario_obligatorio"},
    "validacion": COMUNES | {"pasos", "evidencia", "opciones", "comentario_obligatorio"},
}
# Campo opcional (unidad 056): `adjuntos` en validacion, propuesta y lector.
# Nunca en bandeja (es sólo el índice de peticiones).
CON_ADJUNTOS = {"lector", "propuesta", "validacion"}
ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")
SENSIBLE = re.compile(r"PRIVATE KEY|Authorization\s*:\s*Bearer|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.I)
# Ruta relativa de adjunto: sin absolutas, sin `~`, sin `\`, sin segmento `..`.
RUTA_ADJUNTO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


def _texto(valor, nombre):
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nombre}: texto vacío o inválido")
    if len(valor) > 2000:
        raise ValueError(f"{nombre}: contenido extenso")
    if SENSIBLE.search(valor):
        raise ValueError(f"{nombre}: contenido sensible")
    return valor


def _lista_textos(valor, nombre):
    if not isinstance(valor, list):
        raise ValueError(f"{nombre}: debe ser una lista")
    for item in valor:
        _texto(item, nombre)


def _adjuntos(valor):
    if not isinstance(valor, list):
        raise ValueError("adjuntos: debe ser una lista")
    for ruta in valor:
        if not isinstance(ruta, str) or not ruta:
            raise ValueError("adjuntos: ruta vacía o inválida")
        if len(ruta) > 400 or not RUTA_ADJUNTO.match(ruta):
            raise ValueError("adjuntos: ruta con caracteres no permitidos")
        if ".." in ruta.split("/"):
            raise ValueError("adjuntos: ruta insegura")
    return valor


def validar(datos):
    if not isinstance(datos, dict) or set(datos) != {"version", "presentaciones"}:
        raise ValueError("campos raíz inválidos")
    if datos["version"] != 1 or not isinstance(datos["presentaciones"], list):
        raise ValueError("versión o presentaciones inválidas")
    ids = set()
    for p in datos["presentaciones"]:
        if not isinstance(p, dict) or p.get("tipo") not in TIPOS:
            raise ValueError("tipo de presentación inválido")
        campos = CAMPOS[p["tipo"]]
        opcionales = {"adjuntos"} if p["tipo"] in CON_ADJUNTOS else set()
        if not campos <= set(p) <= campos | opcionales:
            raise ValueError("campo de presentación inválido")
        if not isinstance(p["id"], str) or not ID.fullmatch(p["id"]) or p["id"] in ids:
            raise ValueError("id inválido o repetido")
        ids.add(p["id"])
        _texto(p["titulo"], "titulo")
        _texto(p["version"], "version")
        if "adjuntos" in p:
            _adjuntos(p["adjuntos"])
        if p["tipo"] == "bandeja":
            _texto(p["estado"], "estado")
            if not isinstance(p["peticiones"], list):
                raise ValueError("peticiones inválidas")
            for peticion in p["peticiones"]:
                if set(peticion) != {"id", "titulo", "detalle", "estado", "destino"}:
                    raise ValueError("campo de petición inválido")
                for campo, valor in peticion.items():
                    _texto(valor, campo)
        elif p["tipo"] == "lector":
            _texto(p["variante"], "variante")
            for campo in ("preguntas", "hechos", "fuentes", "hallazgos", "conclusiones", "limites"):
                _lista_textos(p[campo], campo)
            if any(".." in ref or ref.startswith(("/", "~")) for ref in p["fuentes"]):
                raise ValueError("referencia insegura")
        else:
            contenido = "resumen" if p["tipo"] == "propuesta" else "pasos"
            (_texto if contenido == "resumen" else _lista_textos)(p[contenido], contenido)
            if p["tipo"] == "validacion":
                _lista_textos(p["evidencia"], "evidencia")
            _lista_textos(p["opciones"], "opciones")
            _lista_textos(p["comentario_obligatorio"], "comentario_obligatorio")
            if not p["opciones"] or not set(p["comentario_obligatorio"]) <= set(p["opciones"]):
                raise ValueError("opciones inválidas")
    destinos = {pet["destino"] for p in datos["presentaciones"] if p["tipo"] == "bandeja" for pet in p["peticiones"]}
    if not destinos <= ids:
        raise ValueError("destino de petición inexistente")
    return datos


# --------------------------------------------------------------- generar, no escribir a mano
# Bug 057: el manifiesto de una validación guiada se escribía A MANO cada vez que había que
# pedir un OK, así que pedir un OK dependía de que el agente se acordara. `unidad.py validar`
# lo genera desde la ficha y usa esto: el contrato JSON se conoce AQUÍ, en un solo sitio, y
# no se duplica en los scripts del método.

RECORTE = "… [recortado]"
VACIO = "—"


def sanear(valor, tope=2000):
    """Un texto que `validar` va a aceptar: sin dato sensible y dentro del tope.

    Lo que entra viene de una ficha escrita por personas: puede traer saltos de línea, un
    correo de contacto o un párrafo de más. Recortar y tachar AQUÍ evita el peor final
    posible —un manifiesto generado que su propio validador rechaza— sin relajar la
    frontera: `SENSIBLE` y el tope siguen siendo los mismos de la 051.
    """
    texto = " ".join(str(valor).split()) or VACIO
    texto = SENSIBLE.sub("[dato sensible]", texto)
    if len(texto) > tope:
        texto = texto[:tope - len(RECORTE)] + RECORTE
    return texto


def presentacion_validacion(identificador, titulo, version, pasos, evidencia, adjuntos=()):
    """La vista de validación guiada de UNA unidad, ya saneada y lista para `validar`."""
    presentacion = {
        "id": identificador,
        "tipo": "validacion",
        "titulo": sanear(titulo),
        "version": sanear(version),
        "pasos": [sanear(paso) for paso in pasos] or [VACIO],
        "evidencia": [sanear(linea) for linea in evidencia] or [VACIO],
        "opciones": ["confirmado", "problema"],
        "comentario_obligatorio": ["problema"],
    }
    adjuntos = [ruta for ruta in adjuntos if RUTA_ADJUNTO.match(ruta or "")]
    if adjuntos:
        presentacion["adjuntos"] = adjuntos
    return presentacion


def manifiesto(presentaciones):
    """Envuelve las presentaciones en el contrato v1 y lo valida antes de devolverlo."""
    return validar({"version": 1, "presentaciones": list(presentaciones)})


def crear_ejemplo():
    return copy.deepcopy({"version": 1, "presentaciones": [
        {"id": "bandeja", "tipo": "bandeja", "titulo": "Peticiones", "version": "1", "estado": "pendiente", "peticiones": [{"id": "P-001", "titulo": "Propuesta", "detalle": "Revisar la propuesta.", "estado": "pendiente", "destino": "propuesta"}]},
        {"id": "lector", "tipo": "lector", "variante": "investigacion", "titulo": "Investigación", "version": "1", "preguntas": ["¿Qué se decide?"], "hechos": ["La vista es local."], "fuentes": ["docs/investigacion.md#p1"], "hallazgos": ["Hay evidencia resumida."], "conclusiones": ["La decisión queda registrada."], "limites": ["No se muestran archivos completos."]},
        {"id": "propuesta", "tipo": "propuesta", "titulo": "Propuesta", "version": "1", "resumen": "Construir la mejora descrita.", "opciones": ["aprobar", "pedir_cambios"], "comentario_obligatorio": ["pedir_cambios"]},
        {"id": "validacion", "tipo": "validacion", "titulo": "Validación", "version": "1", "pasos": ["Abrir la vista."], "evidencia": ["Pruebas: OK"], "opciones": ["confirmado", "problema"], "comentario_obligatorio": ["problema"]},
    ]})


# ------------------------------------------------------- decidir: el recibo, en UN solo sitio
# Unidad 122: la decisión del usuario podía llegar por dos puertas —el clic en la web y
# `unidad.py confirmar` desde la terminal— y cada puerta con su copia de la validación era
# tener DOS verdades sobre el mismo fichero: el día que una aceptara algo que la otra
# rechaza, `unidad.py cerrar` leería recibos que no significan lo mismo. Las puertas y el
# esquema del recibo viven aquí, junto al contrato del manifiesto que validan.

CAMPOS_DECISION = {"presentacion", "version", "contenido_revisado", "eleccion",
                   "comentario", "confirmado"}


def contenido_revisable(presentacion):
    """Lo que el usuario ha tenido delante y sobre lo que decide: el texto que su recibo
    devuelve para que se pueda comprobar que decidió sobre ESTO y no sobre otra versión."""
    return (presentacion["resumen"] if presentacion["tipo"] == "propuesta"
            else "\n".join(presentacion["pasos"]))


def decidir(datos, decision, extra=None):
    """Valida una decisión contra el manifiesto `datos` y devuelve su recibo inmutable.

    Mismas puertas de siempre (unidad 051): campos exactos, confirmación explícita,
    presentación decidible, versión y contenido idénticos a lo servido, elección dentro de
    las opciones y comentario obligatorio donde el manifiesto lo exige.

    `extra` añade campos al recibo SIN tocar los que se comparan entre vías (`via`, `por`,
    `dia`, `huella`, `ejecutable` de la terminal, unidad 122): quien lee el recibo después
    —`unidad.py cerrar`— sigue encontrando exactamente los mismos campos que ya leía.
    """
    if (not isinstance(decision, dict) or set(decision) != CAMPOS_DECISION
            or decision["confirmado"] is not True):
        raise ValueError("campos o confirmación inválidos")
    presentacion = next(
        (p for p in datos["presentaciones"] if p["id"] == decision["presentacion"]), None)
    if not presentacion or presentacion["tipo"] not in {"propuesta", "validacion"}:
        raise ValueError("presentación no autorizada")
    esperado = contenido_revisable(presentacion)
    if (decision["version"] != presentacion["version"]
            or decision["contenido_revisado"] != esperado):
        raise ValueError("versión o contenido revisado no coincide")
    if decision["eleccion"] not in presentacion["opciones"]:
        raise ValueError("elección inválida")
    comentario = decision["comentario"]
    if not isinstance(comentario, str) or len(comentario) > 2000 or SENSIBLE.search(comentario):
        raise ValueError("comentario inválido o sensible")
    if decision["eleccion"] in presentacion["comentario_obligatorio"] and not comentario.strip():
        raise ValueError("el comentario es obligatorio")
    recibo = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex,
        "presentacion": presentacion["id"],
        "version": presentacion["version"],
        "contenido_revisado": esperado,
        "eleccion": decision["eleccion"],
        "comentario": comentario,
        "fecha": datetime.now(timezone.utc).isoformat(),
    }
    recibo.update(extra or {})
    return recibo


def escribir_recibo(carpeta_datos, recibo):
    """Sella el recibo en `<datos>/recibos/<id>.json`. Inmutable: nunca pisa uno existente."""
    carpeta = Path(carpeta_datos) / "recibos"
    carpeta.mkdir(mode=0o700, parents=True, exist_ok=True)
    ruta = carpeta / (recibo["id"] + ".json")
    with ruta.open("x", encoding="utf-8") as salida:
        json.dump(recibo, salida, ensure_ascii=False, indent=2)
        salida.write("\n")
    return ruta
