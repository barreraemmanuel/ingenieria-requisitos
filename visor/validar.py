#!/usr/bin/env python3
"""Validador oficial de planos.json. Solo biblioteca estándar.

Comprueba lo que el esquema exige más lo que el método promete: ids únicos
globales, referencias que existen, tablas cuadradas, fichas completas.
Ejecútalo tras CADA actualización de planos.json.

Uso: python3 validar.py --datos <ruta/planos.json> [--perfil borrador|revision|congelado]
Sale con código 0 si no hay errores (los avisos no bloquean), 1 si los hay.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


# Windows: la salida por PIPE hereda cp1252 y los acentos salen como mojibake.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")
TIPOS_ACCION = ("humano", "estatico", "ia", "externo")
BASE = Path(__file__).resolve().parent
CAMPOS_FICHA = ("quien", "llega", "cuando", "ve", "puede", "nunca")
ESTADOS_DEFINICION = ("borrador", "listo para revisar", "aprobado", "congelado")
# Estados del mapa en los que una actividad DICE tener planos completos.
ESTADOS_ACTIVIDAD_CON_PLANOS = ("especificada", "en obra", "entregada")
MODOS_DEFINICION = ("entrevista", "autopropuesto", "analisis de codigo", "mixto")
ORIGENES = ("usuario", "codigo", "inferido", "mixto")
ESTADOS_COBERTURA = (
    "no verificado", "implementado", "parcial", "no implementado", "contradice"
)

errores = []
avisos = []


def err(donde, msg):
    errores.append("%s: %s" % (donde, msg))


def aviso(donde, msg):
    avisos.append("%s: %s" % (donde, msg))


def _resolver_ref(esquema_raiz, ref):
    if not ref.startswith("#/"):
        raise ValueError("solo se admiten referencias locales en esquema.json: %s" % ref)
    actual = esquema_raiz
    for parte in ref[2:].split("/"):
        actual = actual[parte.replace("~1", "/").replace("~0", "~")]
    return actual


def _es_tipo(valor, tipo):
    tipos = {
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: isinstance(x, list),
        "string": lambda x: isinstance(x, str),
        "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "boolean": lambda x: isinstance(x, bool),
        "null": lambda x: x is None,
    }
    return tipo in tipos and tipos[tipo](valor)


# Lo que _errores_esquema implementa DE VERDAD. Si esquema.json usara cualquier otra keyword
# de validación (if/then, patternProperties, allOf, maxLength, …), este validador la ignoraría
# EN SILENCIO y unos planos inválidos pasarían por válidos. Antes de validar nada se recorre
# el esquema entero y cualquier keyword fuera de esta lista es un error ruidoso.
KEYWORDS_SOPORTADAS = frozenset((
    "$ref", "anyOf", "oneOf", "type", "const", "enum", "minLength", "pattern",
    "minItems", "items", "required", "properties", "additionalProperties",
))
# Anotaciones y estructura: por definición no validan nada, así que ignorarlas es correcto.
KEYWORDS_ESTRUCTURALES = frozenset((
    "$schema", "$id", "$comment", "title", "description", "examples", "default",
    "definitions",
))


def _keywords_no_soportadas(regla, donde="#"):
    """Keywords de esquema.json que este validador ignoraría en silencio.

    Distingue posición de KEYWORD de posición de NOMBRE: las claves dentro de `properties`
    o `definitions` son nombres de campo (un campo puede llamarse `if` sin ser la keyword),
    así que ahí no se juzga la clave, solo se desciende a su subesquema. También caza las
    FORMAS no implementadas de keywords soportadas: `items` como lista (tupla), `type` como
    lista y `additionalProperties` con un subesquema en vez de un booleano.
    """
    if not isinstance(regla, dict):
        return ["%s: se esperaba un objeto-esquema, no %s" % (donde, type(regla).__name__)]
    hallazgos = []
    for clave, valor in regla.items():
        ruta = "%s/%s" % (donde, clave)
        if clave in ("properties", "definitions"):
            if isinstance(valor, dict):
                for nombre, sub in valor.items():
                    hallazgos += _keywords_no_soportadas(sub, "%s/%s" % (ruta, nombre))
        elif clave in ("anyOf", "oneOf"):
            if isinstance(valor, list):
                for i, sub in enumerate(valor):
                    hallazgos += _keywords_no_soportadas(sub, "%s[%d]" % (ruta, i))
        elif clave == "items":
            if isinstance(valor, list):
                hallazgos.append("%s: items en forma de lista (tupla) no está implementado"
                                 % ruta)
            else:
                hallazgos += _keywords_no_soportadas(valor, ruta)
        elif clave == "additionalProperties":
            if not isinstance(valor, bool):
                hallazgos.append("%s: additionalProperties solo se implementa como booleano"
                                 % ruta)
        elif clave == "type":
            if not isinstance(valor, str):
                hallazgos.append("%s: type como lista no está implementado" % ruta)
        elif clave not in KEYWORDS_SOPORTADAS and clave not in KEYWORDS_ESTRUCTURALES:
            hallazgos.append("%s: keyword de validación no soportada por este validador "
                             "(se ignoraría en silencio)" % ruta)
    return hallazgos


def _errores_esquema(valor, regla, raiz, donde="$" ):
    """Subconjunto Draft 7 usado por nuestro esquema, sin dependencias externas."""
    if "$ref" in regla:
        return _errores_esquema(valor, _resolver_ref(raiz, regla["$ref"]), raiz, donde)
    fallos = []
    if "anyOf" in regla:
        opciones = [_errores_esquema(valor, x, raiz, donde) for x in regla["anyOf"]]
        if not any(not x for x in opciones):
            fallos.append("%s: no cumple ninguna alternativa" % donde)
    if "oneOf" in regla:
        validas = sum(not _errores_esquema(valor, x, raiz, donde) for x in regla["oneOf"])
        if validas != 1:
            fallos.append("%s: debe cumplir exactamente una alternativa" % donde)

    tipo = regla.get("type")
    if tipo and not _es_tipo(valor, tipo):
        return ["%s: se esperaba %s" % (donde, tipo)]
    if "const" in regla and valor != regla["const"]:
        fallos.append("%s: debe ser %r" % (donde, regla["const"]))
    if "enum" in regla and valor not in regla["enum"]:
        fallos.append("%s: valor no permitido" % donde)
    if isinstance(valor, str):
        if len(valor) < regla.get("minLength", 0):
            fallos.append("%s: texto demasiado corto" % donde)
        if regla.get("pattern") and re.search(regla["pattern"], valor) is None:
            fallos.append("%s: no cumple el patrón %s" % (donde, regla["pattern"]))
    if isinstance(valor, list):
        if len(valor) < regla.get("minItems", 0):
            fallos.append("%s: faltan elementos" % donde)
        if "items" in regla:
            for i, item in enumerate(valor):
                fallos.extend(_errores_esquema(item, regla["items"], raiz, "%s[%d]" % (donde, i)))
    if isinstance(valor, dict):
        for nombre in regla.get("required", []):
            if nombre not in valor:
                fallos.append("%s: falta %s" % (donde, nombre))
        propiedades = regla.get("properties", {})
        if regla.get("additionalProperties") is False:
            for nombre in valor:
                if nombre not in propiedades:
                    fallos.append("%s.%s: campo desconocido" % (donde, nombre))
        for nombre, subregla in propiedades.items():
            if nombre in valor:
                fallos.extend(_errores_esquema(valor[nombre], subregla, raiz,
                                                "%s.%s" % (donde, nombre)))
    return fallos


def validar_esquema(d):
    try:
        esquema = json.loads((BASE / "esquema.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return err("esquema.json", "no se puede leer: %s" % exc)
    sospechosas = _keywords_no_soportadas(esquema)
    if sospechosas:
        for hallazgo in sospechosas:
            err("esquema.json", hallazgo)
        return err("esquema.json", "NO se validó nada contra el esquema: primero quita o "
                   "implementa las keywords de arriba (validar.py, _errores_esquema)")
    for fallo in _errores_esquema(d, esquema, esquema):
        err("esquema", fallo)


def _identificadores(d):
    for regla in d.get("reglas", []) or []:
        yield regla.get("id"), "reglas"
    for episodio in d.get("episodios", []) or []:
        yield episodio.get("id"), "episodios"
    for rec in d.get("recorridos", []) or []:
        yield rec.get("id"), "recorridos"
        for req in rec.get("requisitos", []) or []:
            yield req.get("id"), "%s.requisitos" % rec.get("id", "recorrido")
        for criterio in rec.get("criterios", []) or []:
            yield criterio.get("id"), "%s.criterios" % rec.get("id", "recorrido")
    for calidad in d.get("calidad", []) or []:
        yield calidad.get("id"), "calidad"
    superficie = d.get("superficie") or {}
    for punto in superficie.get("puntos", []) or []:
        yield punto.get("id"), "superficie.puntos"
    permisos = superficie.get("permisos") or {}
    for restriccion in permisos.get("restricciones", []) or []:
        yield restriccion.get("id"), "superficie.permisos.restricciones"
    for prueba in d.get("pruebas_e2e", []) or []:
        yield prueba.get("id"), "pruebas_e2e"


def validar_ids_del_proyecto(d, ruta_mapa):
    """Comprueba la promesa de unicidad entre el mapa y todas sus actividades."""
    if not d.get("actividades"):
        return
    raiz = Path(ruta_mapa).resolve().parent
    documentos = [(Path(ruta_mapa).resolve(), d)]
    for actividad in d.get("actividades", []):
        aid = actividad.get("id")
        ruta = raiz / "actividades" / str(aid) / "planos.json"
        if not ruta.is_file():
            continue
        try:
            documentos.append((ruta, json.loads(ruta.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:
            err("ids globales.%s" % aid, "no se puede leer %s: %s" % (ruta, exc))
    vistos = {}
    for ruta, datos in documentos:
        relativo = str(ruta.relative_to(raiz)) if ruta != raiz else str(ruta)
        for identificador, lugar in _identificadores(datos):
            if not identificador:
                continue
            actual = "%s:%s" % (relativo, lugar)
            if identificador in vistos:
                err("ids globales", 'id duplicado "%s" en %s; ya estaba en %s' %
                    (identificador, actual, vistos[identificador]))
            else:
                vistos[identificador] = actual


def validar_paso(p, donde, ids_quien):
    if not isinstance(p, dict):
        return err(donde, "el paso no es un objeto")
    tipo = p.get("tipo")
    if tipo == "decision":
        if p.get("clase") not in ("regla", "excepcion"):
            err(donde, 'decision sin "clase" regla/excepcion')
        if not p.get("condicion"):
            err(donde, 'decision sin "condicion"')
        ramas = p.get("ramas") if isinstance(p.get("ramas"), list) else ([p["rama"]] if isinstance(p.get("rama"), dict) else [])
        if not ramas:
            err(donde, "decision sin rama ni ramas")
        for i, r in enumerate(ramas):
            d2 = "%s.rama[%d]" % (donde, i)
            if not isinstance(r, dict) or not r.get("etiqueta"):
                err(d2, "rama sin etiqueta")
                continue
            if not isinstance(r.get("pasos"), list) or not r["pasos"]:
                err(d2, "rama sin pasos")
                continue
            for j, x in enumerate(r["pasos"]):
                validar_paso(x, "%s.pasos[%d]" % (d2, j), ids_quien)
    elif tipo in TIPOS_ACCION:
        if not p.get("texto"):
            err(donde, 'paso "%s" sin "texto"' % tipo)
        quien = p.get("quien")
        if quien and ids_quien and quien.lower() not in ids_quien:
            aviso(donde, 'quien "%s" no está en actores (ni como miembro)' % quien)
    else:
        err(donde, 'tipo de paso desconocido: "%s"' % tipo)


def validar_implementacion(valor, donde):
    if not isinstance(valor, dict):
        return err(donde, "falta el objeto de cobertura de implementación")
    if valor.get("estado") not in ESTADOS_COBERTURA:
        err(donde, "estado inválido; usa: %s" % ", ".join(ESTADOS_COBERTURA))
    if not isinstance(valor.get("evidencias", []), list):
        err(donde, "evidencias debe ser una lista")
    if not isinstance(valor.get("pruebas", []), list):
        err(donde, "pruebas debe ser una lista")


def revisar_preguntas(d, donde, sufijo):
    """Las preguntas que el usuario no puede responder (un mecanismo sin
    decidir, un documento pendiente de ver) NO bloquean la entrega: el
    RUNBOOK (F3) manda dejarlas escritas para que viajen al constructor
    como deuda visible. Solo bloquea acumularlas: más de 3 ya no es deuda,
    es una entrevista sin terminar."""
    preguntas = d.get("preguntas") or []
    if len(preguntas) > 3:
        err(
            donde,
            "hay %d preguntas abiertas%s (tope 3 para entregar): responde "
            "las que el usuario sí sepa, o conviértelas en supuestos "
            "propuestos" % (len(preguntas), sufijo),
        )
    elif preguntas:
        aviso(
            donde,
            "%d pregunta(s) abierta(s)%s: viajan al constructor como deuda "
            "visible (pestaña Sin decidir y spec.md)"
            % (len(preguntas), sufijo),
        )


def exigir_revision(d, tolerar_borrador=False):
    """Impide presentar planos parciales como si estuvieran listos."""
    definicion = d.get("definicion")
    if not isinstance(definicion, dict):
        err("perfil revision", "falta definicion")
        definicion = {}
    if definicion.get("estado") not in ("listo para revisar", "aprobado", "congelado"):
        # `--tolerar-borrador` existe SOLO para `requisitos.py listo`: valida
        # todo lo demás y, si pasa, es ese comando quien pone el estado.
        if not tolerar_borrador:
            err(
                "perfil revision",
                'definicion.estado debe ser "listo para revisar" o posterior — '
                "lo marca `requisitos.py listo` cuando los planos están "
                "completos; no se edita a mano",
            )
    no_aplican = set(definicion.get("bloques_no_aplican", []) or [])

    if d.get("actividades"):
        for nombre, valor in (
            ("descripcion", d.get("descripcion")),
            ("contrato.frase", (d.get("contrato") or {}).get("frase")),
            ("contrato.exito", (d.get("contrato") or {}).get("exito")),
            ("actores", d.get("actores")),
        ):
            if not valor and nombre.split(".", 1)[0] not in no_aplican:
                err("perfil revision", "bloque de mapa sin completar: %s" % nombre)
        revisar_preguntas(d, "perfil revision", " en el mapa")
        validar_implementacion(d.get("cobertura"), "perfil revision.cobertura")
        # Un mapa vive AÑOS con actividades "sin empezar": es su estado
        # normal desde la cartografía hasta la última entrega, y el visor y
        # la aprobación por versiones existen justamente para eso. La barra
        # de revisión se aplica a lo que DICE estar especificado; a lo
        # pendiente solo se le exige su ficha de catálogo.
        for i, actividad in enumerate(d.get("actividades", [])):
            donde = "perfil revision.actividades[%d]" % i
            if actividad.get("origen") not in ORIGENES:
                err(donde, "falta origen válido")
            if actividad.get("estado") in ESTADOS_ACTIVIDAD_CON_PLANOS:
                validar_implementacion(actividad.get("cobertura"), donde + ".cobertura")
            elif not actividad.get("resumen"):
                err(donde, "actividad pendiente sin resumen: el catálogo del mapa exige su línea")
        return

    obligatorios = (
        ("descripcion", d.get("descripcion")),
        ("contrato.frase", (d.get("contrato") or {}).get("frase")),
        ("contrato.exito", (d.get("contrato") or {}).get("exito")),
        ("actores", d.get("actores")),
        ("flujos", d.get("flujos")),
        ("recorridos", d.get("recorridos")),
        ("estados", d.get("estados")),
        ("datos", d.get("datos")),
        ("superficie", d.get("superficie")),
        ("calidad", d.get("calidad")),
        ("fuera", d.get("fuera")),
    )
    for nombre, valor in obligatorios:
        if not valor and nombre.split(".", 1)[0] not in no_aplican:
            err("perfil revision", "bloque obligatorio sin completar: %s" % nombre)
    for nombre in ("episodios", "reglas", "volumen", "integraciones"):
        if not d.get(nombre) and nombre not in no_aplican:
            err(
                "perfil revision",
                'el bloque "%s" está vacío: complétalo o decláralo en bloques_no_aplican'
                % nombre,
            )
    revisar_preguntas(d, "perfil revision", "")
    flujos = d.get("flujos", []) or []
    if not any(f.get("momento") == "futuro" for f in flujos):
        err("perfil revision", "falta al menos un flujo futuro (el diseño a implementar)")
    if len(flujos) > 3:
        # La frontera flujo/actividad (RUNBOOK, "el mapa y las actividades"):
        # una actividad sana son 2-3 variantes del mismo verbo. Más flujos en
        # una actividad única suele ser un mapa sin dibujar: en el visor todo
        # queda apelmazado en una sola página con anchors en vez de una
        # página por actividad.
        aviso(
            "perfil revision",
            "%d flujos en una actividad única: una actividad sana son 2-3 "
            "variantes del MISMO verbo con el MISMO resultado (hoy/futuro, "
            "otro canal). La norma del método es el MAPA — varias "
            "actividades, cada una con su carpeta y su propia página en el "
            "visor, no una sola página con anchors; actividad única es la "
            "excepción (RUNBOOK: la frontera flujo/actividad)" % len(flujos),
        )
    validar_implementacion(d.get("cobertura"), "perfil revision.cobertura")

    for i, f in enumerate(d.get("flujos", [])):
        if f.get("origen") not in ORIGENES:
            err("perfil revision.flujos[%d]" % i, "falta origen válido")
    for i, rec in enumerate(d.get("recorridos", [])):
        if not rec.get("requisitos"):
            err("perfil revision.recorridos[%d]" % i, "no contiene requisitos")
        if not rec.get("criterios"):
            err("perfil revision.recorridos[%d]" % i, "no contiene criterios comprobables")
        for j, req in enumerate(rec.get("requisitos", []) or []):
            donde = "perfil revision.recorridos[%d].requisitos[%d]" % (i, j)
            if req.get("origen") not in ORIGENES:
                err(donde, "falta origen válido")
            validar_implementacion(req.get("implementacion"), donde + ".implementacion")


def validar_definicion_y_cobertura(d):
    definicion = d.get("definicion")
    if definicion is not None:
        if not isinstance(definicion, dict):
            err("definicion", "debe ser un objeto")
        else:
            if definicion.get("estado") not in ESTADOS_DEFINICION:
                err("definicion.estado", "valor inválido; usa: %s" % ", ".join(ESTADOS_DEFINICION))
            if definicion.get("modo") not in MODOS_DEFINICION:
                err("definicion.modo", "valor inválido; usa: %s" % ", ".join(MODOS_DEFINICION))
            for i, supuesto in enumerate(definicion.get("supuestos", []) or []):
                if supuesto.get("origen") not in ORIGENES:
                    err("definicion.supuestos[%d]" % i, "falta origen válido")
                if supuesto.get("estado") not in ("propuesto", "confirmado", "rechazado"):
                    err("definicion.supuestos[%d]" % i, "estado inválido")
    cobertura = d.get("cobertura")
    if cobertura is not None:
        validar_implementacion(cobertura, "cobertura")


def validar_planos_de_actividades(d, ruta_mapa, perfil, tolerar_borrador=False):
    if not d.get("actividades"):
        return
    base = Path(ruta_mapa).resolve().parent
    for actividad in d["actividades"]:
        aid = actividad.get("id")
        if not aid:
            continue
        # La barra de cada actividad la marca SU estado en el mapa: lo que
        # dice estar especificado se valida al perfil pedido; lo pendiente
        # ("sin empezar", "en entrevista") puede no tener planos aún, y si
        # tiene un borrador a medias se valida como borrador.
        especificada = actividad.get("estado") in ESTADOS_ACTIVIDAD_CON_PLANOS
        perfil_actividad = perfil if especificada else "borrador"
        ruta = base / "actividades" / aid / "planos.json"
        if not ruta.is_file():
            if perfil != "borrador" and especificada:
                err(
                    "perfil %s.actividades.%s" % (perfil, aid),
                    'la actividad dice "%s" y falta %s'
                    % (actividad.get("estado"), ruta),
                )
            continue
        comando = [sys.executable, __file__, "--datos", str(ruta),
                   "--perfil", perfil_actividad]
        if tolerar_borrador and perfil_actividad == "revision":
            comando.append("--tolerar-borrador")
        r = subprocess.run(
            comando,
            text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if r.returncode:
            resumen = " | ".join(x.strip() for x in r.stdout.splitlines() if x.strip())
            err("perfil %s.actividades.%s" % (perfil, aid), resumen)
        coherencia_con_mapa(d, ruta, aid)


def coherencia_con_mapa(mapa, ruta_actividad, aid):
    """La coherencia que promete el RUNBOOK (§mapa, punto 5): los actores y
    el vocabulario de cada actividad existen en el mapa. Lo global nuevo se
    añade AL MAPA, no a la actividad; esto avisa de lo que se quedó local."""
    try:
        actividad = json.loads(
            Path(ruta_actividad).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return  # ilegible: ya lo reporta la subvalidación
    conocidos = set()
    for a in mapa.get("actores", []) or []:
        if a.get("nombre"):
            conocidos.add(a["nombre"].lower())
        for m in a.get("miembros", []) or []:
            conocidos.add(str(m).lower())
    for a in actividad.get("actores", []) or []:
        nombre = a.get("nombre")
        if nombre and nombre.lower() not in conocidos:
            aviso(
                "actividades.%s" % aid,
                'el actor "%s" no está en el mapa: si es global, va AL MAPA '
                "(RUNBOOK, coherencia del cierre de actividad)" % nombre,
            )
    terminos = {
        (v.get("termino") or "").lower()
        for v in mapa.get("vocabulario", []) or []
    }
    for v in actividad.get("vocabulario", []) or []:
        termino = v.get("termino")
        if termino and termino.lower() not in terminos:
            aviso(
                "actividades.%s" % aid,
                'el término "%s" no está en el vocabulario del mapa: lo '
                "global va AL MAPA" % termino,
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", required=True)
    ap.add_argument(
        "--perfil",
        choices=("borrador", "revision", "congelado"),
        default="borrador",
        help="borrador tolera huecos; revision exige entrega completa; congelado exige aprobación",
    )
    ap.add_argument(
        "--tolerar-borrador",
        action="store_true",
        help="uso interno de `requisitos.py listo`: valida revision entera "
             "salvo el propio estado, que pondrá ese comando si todo pasa",
    )
    args = ap.parse_args()

    try:
        with open(args.datos, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit("ERROR: no pude leer el JSON: %s" % e)

    validar_esquema(d)
    if d.get("version") != 2:
        err("version", "debe ser 2")
    if not d.get("titulo"):
        err("titulo", "falta")
    validar_definicion_y_cobertura(d)
    validar_ids_del_proyecto(d, args.datos)

    # actores y quienes válidos
    ids_quien = set()
    personas = {}
    for a in d.get("actores", []):
        if not a.get("nombre"):
            err("actores", "actor sin nombre")
            continue
        nombre_normalizado = a["nombre"].lower()
        if nombre_normalizado in personas:
            err("actores", 'persona duplicada: "%s"' % a["nombre"])
        personas[nombre_normalizado] = {
            "nombre": a["nombre"],
            "rol": a.get("rol"),
            "organizacion": a.get("organizacion"),
            "grupos": a.get("grupos", []) or [],
            "estado": a.get("estado"),
        }
        ids_quien.add(nombre_normalizado)
        for m in a.get("miembros", []) or []:
            miembro_normalizado = str(m).lower()
            if miembro_normalizado in personas:
                err("actores", 'persona duplicada: "%s"' % m)
            personas[miembro_normalizado] = {
                "nombre": str(m),
                "rol": a.get("rol"),
                "organizacion": a.get("organizacion"),
                "grupos": a.get("grupos", []) or [],
                "estado": a.get("estado"),
            }
            ids_quien.add(miembro_normalizado)

    # actividades (plano mapa)
    ids_act = set()
    for i, a in enumerate(d.get("actividades", [])):
        donde = "actividades[%d]" % i
        if not a.get("id") or not a.get("nombre") or not a.get("area"):
            err(donde, "actividad sin id/nombre/area")
            continue
        if a["id"] in ids_act:
            err(donde, 'id de actividad duplicado: "%s"' % a["id"])
        ids_act.add(a["id"])
    for i, a in enumerate(d.get("actividades", [])):
        for dep in a.get("depende_de", []) or []:
            if dep not in ids_act:
                err("actividades[%d] (%s)" % (i, a.get("id")), 'depende de "%s", que no existe en el mapa' % dep)

    # flujos
    vistos_flujo = set()
    flujos_por_id = {}
    for i, f in enumerate(d.get("flujos", [])):
        donde = "flujos[%d]" % i
        if not f.get("id") or not f.get("titulo") or f.get("momento") not in ("hoy", "futuro"):
            err(donde, "flujo sin id/titulo/momento válido")
        if f.get("id") in vistos_flujo:
            err(donde, 'id de flujo duplicado: "%s"' % f.get("id"))
        vistos_flujo.add(f.get("id"))
        if f.get("id"):
            flujos_por_id[f["id"]] = f
        for j, p in enumerate(f.get("pasos", []) or []):
            validar_paso(p, "%s.pasos[%d]" % (donde, j), ids_quien)
        if not f.get("pasos"):
            err(donde, "flujo sin pasos")

    if args.perfil in ("revision", "congelado"):
        exigir_revision(
            d, args.perfil == "revision" and args.tolerar_borrador
        )
    if args.perfil == "congelado":
        definicion = d.get("definicion") or {}
        if definicion.get("estado") not in ("aprobado", "congelado"):
            err("perfil congelado", 'definicion.estado debe ser "aprobado" o "congelado"')
        for i, supuesto in enumerate(definicion.get("supuestos", []) or []):
            if supuesto.get("estado") != "confirmado":
                err(
                    "perfil congelado",
                    "el supuesto %s debe estar confirmado antes de congelar"
                    % supuesto.get("id", i + 1),
                )
    validar_planos_de_actividades(
        d, args.datos, args.perfil,
        args.perfil == "revision" and args.tolerar_borrador,
    )

    # ids globales únicos
    ids = {}

    def registrar(idv, patron, donde):
        if not idv:
            return
        if not re.match(patron, idv):
            err(donde, 'id "%s" no cumple el patrón %s' % (idv, patron))
        if idv in ids:
            err(donde, 'id duplicado "%s" (ya usado en %s); la numeración es GLOBAL' % (idv, ids[idv]))
        ids[idv] = donde

    todos_r, todas_g = set(), set()
    recorrido_por_requisito = {}
    recorrido_por_criterio = {}
    cubre_por_criterio = {}
    permisos_documento = ((d.get("superficie") or {}).get("permisos") or {})
    restricciones_documento = permisos_documento.get("restricciones", []) or []
    contrato_nuevo = "pruebas_e2e" in d or bool(restricciones_documento)
    tipo_por_criterio = {}
    for g in d.get("reglas", []):
        registrar(g.get("id"), r"^G-\d+$", "reglas")
        todas_g.add(g.get("id"))
        t = g.get("tabla")
        if t:
            ncol = len(t.get("columnas", []))
            for k, fila in enumerate(t.get("filas", [])):
                if len(fila) != ncol:
                    err("reglas %s fila %d" % (g.get("id"), k + 1),
                        "tiene %d celdas y la tabla %d columnas" % (len(fila), ncol))
    for rec in d.get("recorridos", []):
        registrar(rec.get("id"), r"^REC-\d+$", "recorridos")
        vistos_enlaces = set()
        for flujo in rec.get("flujos", []) or []:
            if flujo in vistos_enlaces:
                err(
                    "%s.flujos" % rec.get("id", "recorrido"),
                    'flujo duplicado: "%s"' % flujo,
                )
            vistos_enlaces.add(flujo)
            if flujo not in flujos_por_id:
                err(
                    "%s.flujos" % rec.get("id", "recorrido"),
                    'cita el flujo inexistente "%s"' % flujo,
                )
            elif flujos_por_id[flujo].get("momento") != "futuro":
                err(
                    "%s.flujos" % rec.get("id", "recorrido"),
                    '"%s" no es un flujo futuro' % flujo,
                )
        for q in rec.get("requisitos", []) or []:
            registrar(q.get("id"), r"^R-\d+$", rec.get("id", "recorrido"))
            todos_r.add(q.get("id"))
            if q.get("id"):
                recorrido_por_requisito[q["id"]] = rec.get("id")
    for rec in d.get("recorridos", []):
        for q in rec.get("requisitos", []) or []:
            if q.get("regla") and q["regla"] not in todas_g:
                err("%s %s" % (rec.get("id"), q.get("id")), 'cita la regla inexistente "%s"' % q["regla"])
        for c in rec.get("criterios", []) or []:
            registrar(c.get("id"), r"^C-\d+$", rec.get("id", "recorrido"))
            if c.get("id"):
                recorrido_por_criterio[c["id"]] = rec.get("id")
                cubre_por_criterio[c["id"]] = c.get("cubre")
                tipo_por_criterio[c["id"]] = c.get("tipo")
            if contrato_nuevo and not c.get("tipo"):
                err(
                    "%s %s" % (rec.get("id"), c.get("id")),
                    'falta "tipo": el contrato E2E distingue criterios "feliz" y "denegacion"',
                )
            if args.perfil in ("revision", "congelado") and not c.get("cubre"):
                (err if contrato_nuevo else aviso)(
                    "%s %s" % (rec.get("id"), c.get("id")),
                    'falta "cubre": todo criterio C-n debe verificar un requisito del mismo recorrido',
                )
            if c.get("cubre") and c["cubre"] not in todos_r:
                err("%s %s" % (rec.get("id"), c.get("id")), 'dice cubrir el requisito inexistente "%s"' % c["cubre"])
            elif (
                c.get("cubre")
                and recorrido_por_requisito.get(c["cubre"]) != rec.get("id")
            ):
                err(
                    "%s %s" % (rec.get("id"), c.get("id")),
                    'no puede cubrir %s: pertenece a %s, no al mismo recorrido'
                    % (c["cubre"], recorrido_por_requisito.get(c["cubre"])),
                )
    for q in d.get("calidad", []):
        registrar(q.get("id"), r"^Q-\d+$", "calidad")
    for i, episodio in enumerate(d.get("episodios", []) or []):
        registrar(episodio.get("id"), r"^EP-\d+$", "episodios[%d]" % i)
    superficie = d.get("superficie") or {}
    for i, punto in enumerate(superficie.get("puntos", []) or []):
        registrar(punto.get("id"), r"^SUP-\d+$", "superficie.puntos[%d]" % i)
    permisos = superficie.get("permisos") or {}
    for i, restriccion in enumerate(permisos.get("restricciones", []) or []):
        registrar(
            restriccion.get("id"),
            r"^P-\d+$",
            "superficie.permisos.restricciones[%d]" % i,
        )
    for i, prueba in enumerate(d.get("pruebas_e2e", []) or []):
        registrar(prueba.get("id"), r"^E2E-\d+$", "pruebas_e2e[%d]" % i)

    # estados: acciones como texto u objeto; pasa_a debe apuntar a un estado real
    for e in d.get("estados", []):
        nombres = {x.get("nombre") for x in e.get("estados", [])}
        entrantes = set()
        for x in e.get("estados", []):
            for a in x.get("acciones", []) or []:
                if isinstance(a, dict):
                    if not a.get("accion"):
                        err("estados %s/%s" % (e.get("entidad"), x.get("nombre")), "acción sin texto")
                    if a.get("pasa_a") and a["pasa_a"] not in nombres:
                        aviso("estados %s/%s" % (e.get("entidad"), x.get("nombre")),
                              'pasa_a "%s" no es un estado declarado de esta entidad' % a["pasa_a"])
                    if a.get("pasa_a"):
                        entrantes.add(a["pasa_a"])
        # F5.2: todo estado es alcanzable. El primero de la lista se toma
        # como inicial; a cualquier otro tiene que llegarle algún pasa_a.
        for j, x in enumerate(e.get("estados", [])):
            if j and x.get("nombre") and x["nombre"] not in entrantes:
                aviso("estados %s/%s" % (e.get("entidad"), x["nombre"]),
                      "estado inalcanzable: ningún `pasa_a` llega aquí (si es el inicial, ponlo el primero)")

    # cobertura: reglas huérfanas y requisitos sin prueba. Mientras los
    # planos crecen (borrador) son avisos; al pedir revisión o congelar son
    # incumplimientos del cierre de coherencia de F5 y BLOQUEAN: es la
    # trazabilidad que permite detectar reglas huérfanas y promesas sin
    # prueba, y en prosa nadie la exige (RUNBOOK F5.2).
    exigente = args.perfil in ("revision", "congelado")
    marcar = err if exigente and contrato_nuevo else aviso
    reglas_citadas = set()
    requisitos_cubiertos = set()
    for rec in d.get("recorridos", []):
        for q in rec.get("requisitos", []) or []:
            if q.get("regla"):
                reglas_citadas.add(q["regla"])
        for c in rec.get("criterios", []) or []:
            if c.get("cubre"):
                requisitos_cubiertos.add(c["cubre"])
    for g in todas_g:
        if g and g not in reglas_citadas:
            marcar("reglas", '%s no la implementa ningún requisito (campo "regla"): regla huérfana o campo sin rellenar' % g)
    for rid in sorted(todos_r):
        if rid and rid not in requisitos_cubiertos:
            marcar("recorridos", '%s no tiene ninguna prueba que lo cubra (campo "cubre" de los criterios)' % rid)

    # pasos `ia` de los flujos futuros: cada uno exige al menos un requisito
    # de fallo ("Si ..., entonces ...", EARS de protección) con criterio que
    # lo cubra. Sin él, el comportamiento ante el fallo del modelo queda a la
    # imaginación del constructor (RUNBOOK F3 y F5.2).
    def contar_ia(pasos):
        n = 0
        for p in pasos or []:
            if not isinstance(p, dict):
                continue
            if p.get("tipo") == "ia":
                n += 1
            if p.get("tipo") == "decision":
                ramas = p.get("ramas") if isinstance(p.get("ramas"), list) else (
                    [p["rama"]] if isinstance(p.get("rama"), dict) else [])
                for r in ramas:
                    if isinstance(r, dict):
                        n += contar_ia(r.get("pasos"))
        return n

    n_ia = sum(contar_ia(f.get("pasos")) for f in d.get("flujos", [])
               if f.get("momento") == "futuro")
    if n_ia:
        protecciones = [
            q for rec in d.get("recorridos", [])
            for q in rec.get("requisitos", []) or []
            if re.match(r"(?i)^si\b", (q.get("texto") or "").strip())
        ]
        con_prueba = [
            q for q in protecciones if q.get("id") in requisitos_cubiertos
        ]
        if not con_prueba:
            marcar(
                "flujos",
                'hay %d paso(s) `ia` en los flujos futuros y ningún requisito '
                'de protección ("Si …, entonces …") con criterio que lo '
                "cubra (RUNBOOK F5.2)" % n_ia,
            )

    # episodios: refs que existan
    for i, e in enumerate(d.get("episodios", [])):
        for ref in e.get("refs", []) or []:
            if ref not in ids:
                err(
                    "episodios[%d] %s" % (i, e.get("id") or "EP-?"),
                    'ref "%s" no corresponde a ningún id' % ref,
                )

    # superficie: fichas completas, avisos con canal
    sup = d.get("superficie") or {}
    for i, p in enumerate(sup.get("puntos", []) or []):
        # Un campo AUSENTE es un hueco; una lista declarada vacía ([]) es una
        # respuesta: "este punto no ofrece acciones" (puntos de solo
        # recepción). Decidir que no hay nada también es claridad.
        faltan = [
            c for c in CAMPOS_FICHA
            if (p.get(c) is None or p.get(c) == "")
        ]
        if faltan:
            aviso("superficie.puntos[%d] (%s)" % (i, p.get("nombre", "?")),
                  "ficha coja, faltan: %s (el método exige los 7 campos)" % ", ".join(faltan))
        for j, nunca in enumerate(p.get("nunca", []) or []):
            punto_id = p.get("id") or p.get("nombre", "?")
            donde_nunca = "superficie.puntos[%d] %s.nunca[%d]" % (
                i, punto_id, j,
            )
            if isinstance(nunca, str):
                if contrato_nuevo:
                    err(
                        donde_nunca,
                        '"%s" debe declarar accion, requisito y criterio en el contrato nuevo'
                        % nunca,
                    )
                continue
            if not isinstance(nunca, dict):
                continue
            requisito = nunca.get("requisito")
            criterio = nunca.get("criterio")
            if requisito not in recorrido_por_requisito:
                err(donde_nunca, 'cita el requisito inexistente "%s"' % requisito)
            if criterio not in recorrido_por_criterio:
                err(donde_nunca, 'cita el criterio inexistente "%s"' % criterio)
                continue
            if tipo_por_criterio.get(criterio) != "denegacion":
                err(
                    donde_nunca,
                    '%s debe ser un criterio de tipo "denegacion"' % criterio,
                )
            if requisito in recorrido_por_requisito and cubre_por_criterio.get(criterio) != requisito:
                err(
                    donde_nunca,
                    '%s cubre %s, no el requisito %s declarado por "nunca"'
                    % (criterio, cubre_por_criterio.get(criterio), requisito),
                )
    for i, a in enumerate(sup.get("avisos", []) or []):
        if not a.get("canal"):
            aviso("superficie.avisos[%d]" % i, "aviso sin canal (el método exige canal explícito)")
    perm = sup.get("permisos")
    acciones_fichas = {
        x for p in (sup.get("puntos", []) or []) for x in p.get("puede", []) or []
    }
    roles_matriz = {}
    grupos_matriz = {}
    roles_interactivos = set()
    if perm:
        acciones = perm.get("acciones", []) or []
        acc = set(acciones)
        if len(acc) != len(acciones):
            err("superficie.permisos.acciones", "hay acciones duplicadas")
        for r in perm.get("roles", []) or []:
            rol = r.get("rol")
            rol_normalizado = (rol or "").lower()
            if contrato_nuevo and rol_normalizado in personas:
                err(
                    "superficie.permisos.roles",
                    '"%s" es una persona, no un rol; los permisos base del contrato nuevo se conceden por rol o grupo'
                    % rol,
                )
            if rol_normalizado in roles_matriz:
                err("superficie.permisos.roles", 'rol duplicado: "%s"' % rol)
            roles_matriz[rol_normalizado] = r
            permitidas = r.get("permitidas", []) or []
            if len(set(permitidas)) != len(permitidas):
                err(
                    "superficie.permisos",
                    'el rol "%s" tiene acciones permitidas duplicadas' % rol,
                )
            for x in permitidas:
                if x not in acc:
                    err("superficie.permisos", 'el rol "%s" tiene permitida "%s", que no está en acciones' % (r.get("rol"), x))

        for g in perm.get("grupos", []) or []:
            grupo = g.get("grupo")
            grupo_normalizado = (grupo or "").lower()
            if grupo_normalizado in grupos_matriz:
                err("superficie.permisos.grupos", 'grupo duplicado: "%s"' % grupo)
            grupos_matriz[grupo_normalizado] = g
            permitidas = g.get("permitidas", []) or []
            if len(set(permitidas)) != len(permitidas):
                err(
                    "superficie.permisos",
                    'el grupo "%s" tiene acciones permitidas duplicadas' % grupo,
                )
            for x in permitidas:
                if x not in acc:
                    err(
                        "superficie.permisos",
                        'el grupo "%s" tiene permitida "%s", que no está en acciones'
                        % (grupo, x),
                    )

        restricciones = perm.get("restricciones", []) or []
        e2e_denegacion_por_restriccion = {}
        personas_e2e_por_criterio = {}
        ids_e2e_por_criterio = {}
        for prueba in d.get("pruebas_e2e", []) or []:
            if prueba.get("tipo") != "denegacion":
                continue
            for pid in prueba.get("restricciones", []) or []:
                e2e_denegacion_por_restriccion.setdefault(pid, []).append(prueba)
            for criterio in prueba.get("criterios", []) or []:
                personas_e2e_por_criterio.setdefault(criterio, set()).update(
                    str(nombre).lower() for nombre in (prueba.get("personas", []) or [])
                )
                ids_e2e_por_criterio.setdefault(criterio, set()).add(
                    prueba.get("id", "E2E-?")
                )
        for i, punto in enumerate(sup.get("puntos", []) or []):
            donde = "superficie.puntos[%d] (%s)" % (
                i,
                punto.get("id") or punto.get("nombre", "?"),
            )
            for quien in punto.get("quien", []) or []:
                persona = personas.get(str(quien).lower())
                if contrato_nuevo and not persona:
                    err(
                        donde,
                        '"%s" no es una persona declarada en actores; los roles no se usan como personas'
                        % quien,
                    )
                    continue
                rol_canonico = (persona or {}).get("rol")
                rol_normalizado = (rol_canonico or "").lower()
                # Compatibilidad: los planos previos usaban el nombre de la
                # persona como fila de la matriz. El contrato nuevo usa su rol.
                if rol_normalizado in roles_matriz:
                    rol_punto = rol_normalizado
                elif not contrato_nuevo and str(quien).lower() in roles_matriz:
                    rol_punto = str(quien).lower()
                else:
                    rol_punto = None
                    if contrato_nuevo and rol_canonico:
                        err(
                            donde,
                            'el rol "%s" de %s no existe en la matriz'
                            % (rol_canonico, quien),
                        )
                if not rol_punto:
                    continue
                roles_interactivos.add(rol_punto)
                permitidas = set(
                    roles_matriz[rol_punto].get("permitidas", []) or []
                )
                grupos_persona = {
                    str(grupo).lower()
                    for grupo in ((persona or {}).get("grupos", []) or [])
                }
                for grupo in grupos_persona:
                    permitidas.update(
                        (grupos_matriz.get(grupo) or {}).get("permitidas", []) or []
                    )
                for accion in punto.get("puede", []) or []:
                    if accion not in permitidas:
                        (err if contrato_nuevo else aviso)(
                            donde,
                            'dice que %s puede "%s", pero ni su rol "%s" ni sus grupos lo tienen permitido en la matriz'
                            % (quien, accion, roles_matriz[rol_punto].get("rol")),
                        )
                for nunca in punto.get("nunca", []) or []:
                    accion = nunca.get("accion") if isinstance(nunca, dict) else nunca
                    if accion in permitidas:
                        (err if contrato_nuevo else aviso)(
                            donde,
                            'dice que %s nunca puede "%s", pero su rol "%s" o uno de sus grupos sí lo permite en la matriz'
                            % (quien, accion, roles_matriz[rol_punto].get("rol")),
                        )

        # F5.2: toda acción de las fichas está en la matriz, Y AL REVÉS.
        for accion in sorted(acciones_fichas - acc):
            (err if contrato_nuevo and args.perfil in ("revision", "congelado") else aviso)(
                "superficie", 'la acción "%s" está en una ficha (`puede`) pero no en la matriz de permisos' % accion
            )
        for accion in sorted(acc - acciones_fichas):
            (err if contrato_nuevo and args.perfil in ("revision", "congelado") else aviso)(
                "superficie.permisos", 'la acción "%s" está en la matriz pero no la ofrece ninguna ficha (`puede`)' % accion
            )

        for restriccion in restricciones:
            pid = restriccion.get("id") or "P-?"
            donde = "superficie.permisos.restricciones %s" % pid
            rol = restriccion.get("rol")
            grupo = restriccion.get("grupo")
            if rol:
                fila = roles_matriz.get(rol.lower())
                sujeto = 'rol "%s"' % rol
            else:
                fila = grupos_matriz.get((grupo or "").lower())
                sujeto = 'grupo "%s"' % grupo
            if not fila:
                err(donde, "cita el %s inexistente" % sujeto)
            accion = restriccion.get("accion")
            if accion not in acc:
                err(donde, 'cita la acción inexistente "%s"' % accion)
            elif fila and accion not in set(fila.get("permitidas", []) or []):
                err(
                    donde,
                    'la acción "%s" no está concedida al %s' % (accion, sujeto),
                )
            if grupo and not any(
                grupo.lower() in {
                    str(g).lower() for g in (persona.get("grupos", []) or [])
                }
                for persona in personas.values()
            ):
                err(donde, 'ninguna persona pertenece al grupo "%s"' % grupo)
            requisito = restriccion.get("requisito")
            criterio = restriccion.get("criterio")
            if requisito not in recorrido_por_requisito:
                err(donde, 'cita el requisito inexistente "%s"' % requisito)
            if criterio not in recorrido_por_criterio:
                err(donde, 'cita el criterio inexistente "%s"' % criterio)
            elif requisito in recorrido_por_requisito and cubre_por_criterio.get(criterio) != requisito:
                err(
                    donde,
                    '%s cubre %s, no el requisito %s de la restricción'
                    % (criterio, cubre_por_criterio.get(criterio), requisito),
                )
            if criterio in recorrido_por_criterio and tipo_por_criterio.get(criterio) != "denegacion":
                err(
                    donde,
                    '%s debe ser un criterio de tipo "denegacion"' % criterio,
                )
            casos_denegacion = [
                prueba
                for prueba in e2e_denegacion_por_restriccion.get(pid, [])
                if criterio in (prueba.get("criterios", []) or [])
            ]
            if "pruebas_e2e" in d and not casos_denegacion:
                err(
                    donde,
                    '%s no está seleccionado por un E2E de denegacion que enlace %s'
                    % (criterio, pid),
                )
            elif "pruebas_e2e" in d:
                nombres_e2e = personas_e2e_por_criterio.get(criterio, set())
                personas_del_sujeto = {
                    nombre
                    for nombre, persona in personas.items()
                    if (
                        rol
                        and str(persona.get("rol") or "").lower() == rol.lower()
                    )
                    or (
                        grupo
                        and grupo.lower()
                        in {
                            str(g).lower()
                            for g in (persona.get("grupos", []) or [])
                        }
                    )
                }
                if not nombres_e2e.intersection(personas_del_sujeto):
                    err(
                        donde,
                        "%s selecciona %s, pero ninguna de sus personas pertenece al %s"
                        % (
                            ", ".join(sorted(ids_e2e_por_criterio.get(criterio, [])))
                            or "E2E-?",
                            criterio,
                            sujeto,
                        ),
                    )
    elif acciones_fichas and args.perfil in ("revision", "congelado"):
        aviso("superficie", "hay fichas con acciones (`puede`) y falta la matriz de permisos: F4 la exige como pieza transversal")

    pruebas_e2e = d.get("pruebas_e2e", []) or []
    roles_con_e2e = set()
    restricciones_por_id = {
        restriccion.get("id"): restriccion
        for restriccion in restricciones_documento
        if restriccion.get("id")
    }
    for i, prueba in enumerate(pruebas_e2e):
        eid = prueba.get("id") or "E2E-?"
        donde = "pruebas_e2e[%d] %s" % (i, eid)
        for campo in ("criterios", "personas", "fronteras", "restricciones"):
            valores = prueba.get(campo, []) or []
            normalizados = [
                str(valor).lower() if campo == "personas" else valor
                for valor in valores
            ]
            if len(set(normalizados)) != len(normalizados):
                err(donde, "%s contiene referencias duplicadas" % campo)
        for criterio in prueba.get("criterios", []) or []:
            if criterio not in recorrido_por_criterio:
                err(donde, 'cita el criterio inexistente "%s"' % criterio)
            elif prueba.get("tipo") == "camino_feliz" and tipo_por_criterio.get(criterio) != "feliz":
                err(donde, '%s no es un criterio de tipo "feliz"' % criterio)
            elif prueba.get("tipo") == "denegacion" and tipo_por_criterio.get(criterio) != "denegacion":
                err(donde, '%s no es un criterio de tipo "denegacion"' % criterio)
        if prueba.get("tipo") == "denegacion":
            criterios_de_restricciones = set()
            for pid in prueba.get("restricciones", []) or []:
                restriccion = restricciones_por_id.get(pid)
                if not restriccion:
                    err(donde, 'cita la restricción inexistente "%s"' % pid)
                    continue
                criterio_restriccion = restriccion.get("criterio")
                criterios_de_restricciones.add(criterio_restriccion)
                if criterio_restriccion not in (prueba.get("criterios", []) or []):
                    err(
                        donde,
                        '%s exige seleccionar su criterio %s'
                        % (pid, criterio_restriccion),
                    )
            for criterio in set(prueba.get("criterios", []) or []) - criterios_de_restricciones:
                err(
                    donde,
                    '%s no corresponde a ninguna restricción enlazada por este E2E de denegacion'
                    % criterio,
                )
        for nombre in prueba.get("personas", []) or []:
            persona = personas.get(str(nombre).lower())
            if not persona:
                err(donde, 'cita la persona inexistente "%s"' % nombre)
                continue
            rol = persona.get("rol")
            if not rol:
                err(donde, 'la persona "%s" no tiene rol' % nombre)
                continue
            rol_normalizado = rol.lower()
            if rol_normalizado not in roles_matriz:
                err(
                    donde,
                    'el rol "%s" de la persona "%s" no existe en la matriz'
                    % (rol, nombre),
                )
                continue
            if prueba.get("tipo") == "camino_feliz":
                roles_con_e2e.add(rol_normalizado)

    if args.perfil in ("revision", "congelado") and "pruebas_e2e" not in d:
        restricciones = (perm or {}).get("restricciones", []) or []
        if restricciones:
            ids_restricciones = ", ".join(
                restriccion.get("id", "P-?") for restriccion in restricciones
            )
            err(
                "perfil revision.pruebas_e2e",
                "las restricciones %s pertenecen al contrato nuevo y exigen pruebas_e2e"
                % ids_restricciones,
            )
        elif roles_interactivos:
            aviso(
                "perfil revision.pruebas_e2e",
                "hay roles interactivos pero el plan anterior no selecciona pruebas_e2e; "
                "complétalo cuando se modifique esta actividad",
            )
    elif "pruebas_e2e" in d:
        ids_e2e = ", ".join(
            prueba.get("id", "E2E-?") for prueba in pruebas_e2e
        ) or "E2E-?"
        for rol in sorted(roles_interactivos - roles_con_e2e):
            err(
                "pruebas_e2e %s" % ids_e2e,
                'el rol interactivo "%s" no tiene un camino feliz seleccionado'
                % roles_matriz[rol].get("rol"),
            )

    for linea in avisos:
        print("AVISO  %s" % linea)
    for linea in errores:
        print("ERROR  %s" % linea)
    if errores:
        print("\n%d error(es), %d aviso(s). Corrige los errores antes de seguir." % (len(errores), len(avisos)))
        sys.exit(1)
    print("OK: planos válidos para perfil %s (%d aviso(s))." % (args.perfil, len(avisos)))


if __name__ == "__main__":
    main()
