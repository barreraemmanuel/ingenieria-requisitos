#!/usr/bin/env python3
"""Contrato JSON v1 para las presentaciones locales."""

import copy
import re

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


def crear_ejemplo():
    return copy.deepcopy({"version": 1, "presentaciones": [
        {"id": "bandeja", "tipo": "bandeja", "titulo": "Peticiones", "version": "1", "estado": "pendiente", "peticiones": [{"id": "P-001", "titulo": "Propuesta", "detalle": "Revisar la propuesta.", "estado": "pendiente", "destino": "propuesta"}]},
        {"id": "lector", "tipo": "lector", "variante": "investigacion", "titulo": "Investigación", "version": "1", "preguntas": ["¿Qué se decide?"], "hechos": ["La vista es local."], "fuentes": ["docs/investigacion.md#p1"], "hallazgos": ["Hay evidencia resumida."], "conclusiones": ["La decisión queda registrada."], "limites": ["No se muestran archivos completos."]},
        {"id": "propuesta", "tipo": "propuesta", "titulo": "Propuesta", "version": "1", "resumen": "Construir la mejora descrita.", "opciones": ["aprobar", "pedir_cambios"], "comentario_obligatorio": ["pedir_cambios"]},
        {"id": "validacion", "tipo": "validacion", "titulo": "Validación", "version": "1", "pasos": ["Abrir la vista."], "evidencia": ["Pruebas: OK"], "opciones": ["confirmado", "problema"], "comentario_obligatorio": ["problema"]},
    ]})
