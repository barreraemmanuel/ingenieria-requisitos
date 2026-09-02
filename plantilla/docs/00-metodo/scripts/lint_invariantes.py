#!/usr/bin/env python3
"""Las ocho señales de la reforma, medidas sobre el taller real, con fecha de corte.

Esto NO es un guardián más. Un guardián dice «esto está mal»; esto dice «esto es lo que
sigue pasando hoy». La diferencia importa porque las ocho señales que mide no son
violaciones: son SEÑALES. Que 122 fichas aprobadas no tengan recibo no significa que 122
personas se saltaran nada — significa que el recibo se inventó después, y ninguna de esas
122 lo va a tener nunca. Pedir «que baje a cero» sería pedir reescribir el pasado, y un
número inalcanzable se ignora a la semana.

Por eso cada señal se imprime en DOS cuentas, y solo una puede bloquear:

  - **histórica** — informa, con su DENOMINADOR. «122» no significa nada; «122 de 144» sí.
    Ese denominador es la objeción del observador incorporada como R5: sin él, la señal
    parece una acusación y no una medida.
  - **posterior al corte** — FAIL si es mayor que cero. Es lo único que la reforma puede
    evitar de verdad: lo que ocurra a partir de la fecha que se le pase.

Las señales con sujeto fechado (S1-S4, S8) reparten por la fecha de ese sujeto. Las de
código (S5-S7) no tienen sujeto fechado —un `fail()` sin id no ocurre «un martes»—, así que
su «posterior al corte» es lo que SUBE sobre una línea base congelada; el mismo trinquete
que `salidas-baseline.json`, y por el mismo motivo: exigir cero para poder existir es lo
mismo que no existir nunca.

  S1  ficha aprobada sin recibo de aprobación
  S2  recibo de ejecución sin resultado (el ayudante que se fue y nadie cerró)
  S3  petición cerrada con un solo proceso terminal, o con ninguno
  S4  petición encaminada sin ningún proceso terminal
  S5  `fail()` sin id estructurado — no se puede contar lo que no se puede nombrar
  S6  rechazo que no nombra su salida
  S7  ejecutor sin par de dientes que demuestre que hace algo
  S8  revisor firmando con la misma sesión que construyó

Uso:
  python3 docs/00-metodo/scripts/lint_invariantes.py --corte 2026-09-01
  python3 docs/00-metodo/scripts/lint_invariantes.py --json
  python3 docs/00-metodo/scripts/lint_invariantes.py --congelar

Exit 0 si ninguna señal tiene cuenta posterior al corte; exit 1 si alguna la tiene.
Sin dependencias: solo stdlib. NO está enganchado a `lint_metodo.py`: la 146 solo añade la
medida, y engancharla al cierre es una decisión posterior con su propia unidad.
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# Windows: en cuanto la salida va a un PIPE el encoding pasa a ser el local y un `ñ` mata
# el script. Es el camino normal de cualquier harness, no una consola rara.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

YO = "docs/00-metodo/scripts/lint_invariantes.py"

# Señales de código: sin sujeto fechado, su «posterior» es lo que sube sobre la base.
ESTRUCTURALES = ("S5", "S6", "S7")

# Un id estructurado al principio del mensaje: `[M-001]`, `M-001`, `[ADR-026]`…
ID_ESTRUCTURADO = re.compile(r'^\s*f?["\']\s*\[?[A-Z]{1,5}-?\d+')
SALIDA = "SALIDA:"

PORQUE = ("Línea base de las ocho señales de la reforma (unidad 146). Las señales de código "
          "(S5-S7) no tienen sujeto fechado: su cuenta «posterior al corte» es lo que SUBE "
          "sobre estos números. Solo pueden bajar. La escribe lint_invariantes.py --congelar, "
          "con su fecha y su commit; a mano no vale.")


# ------------------------------------------------------------------ utilidades
def leer_json(ruta):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def leer_texto(ruta):
    try:
        return ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def solo_fecha(valor):
    """`2026-09-01T22:13:27+00:00` → `2026-09-01`. None si no hay nada que sacar."""
    if not valor:
        return None
    texto = str(valor)
    return texto[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", texto) else None


def posterior(fecha, corte):
    """Comparación de fechas ISO como cadenas: para `YYYY-MM-DD` es exacta."""
    return bool(fecha) and fecha > corte


def sha_corto(raiz):
    """El commit contra el que se midió, para que la base diga de dónde salió.

    Se pregunta primero al taller y, si no es un repo —un workspace no siempre lo es, y los
    talleres de solapa con los que se congela una base post-fusión nunca lo son—, al repo del
    propio método. Ese segundo es de hecho la respuesta más útil: lo que fecha estos números
    es la versión del método que los midió, no la del taller medido.
    """
    for candidata in (raiz, Path(__file__).resolve().parent):
        try:
            hecho = subprocess.run(["git", "-C", str(candidata), "rev-parse", "--short", "HEAD"],
                                   capture_output=True, text=True, timeout=10,
                                   encoding="utf-8", errors="replace")
            if hecho.returncode == 0 and hecho.stdout.strip():
                return hecho.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return "sin-git"


def senal(identificador, titulo, violaciones, universo, posteriores, detalle=None):
    return {"id": identificador, "titulo": titulo, "violaciones": violaciones,
            "universo": universo, "posteriores": posteriores, "detalle": detalle or []}


# ------------------------------------------------------------------ S1
def s1_aprobado_sin_recibo(ws, corte):
    """Ficha con `aprobado: <fecha>` cuyo OK no dejó recibo en `.runtime/aprobaciones/`.

    El denominador son las fichas CON fecha de aprobado, no todas: una ficha sin aprobar
    todavía no puede haberse aprobado mal.
    """
    con_recibo = set()
    for ruta in (ws / ".runtime/aprobaciones").glob("*.json"):
        datos = leer_json(ruta)
        if isinstance(datos, dict) and datos.get("unidad"):
            con_recibo.add(datos["unidad"])

    fichas = []
    trabajo = ws / "docs/05-trabajo"
    for patron in ("*/especificacion.md", "archivo/*/especificacion.md",
                   "archivo/*/*/especificacion.md"):
        fichas += sorted(trabajo.glob(patron))
    fichas += sorted((ws / "docs/bugs").glob("*.md"))

    universo = violaciones = posteriores = 0
    detalle = []
    for ruta in fichas:
        encaje = re.search(r"^aprobado:\s*(\d{4}-\d{2}-\d{2})", leer_texto(ruta), re.M)
        if not encaje:
            continue
        fecha = encaje.group(1)
        nombre = ruta.stem if ruta.parent.name == "bugs" else ruta.parent.name
        universo += 1
        if nombre in con_recibo:
            continue
        violaciones += 1
        if posterior(fecha, corte):
            posteriores += 1
            detalle.append(f"{nombre} (aprobado {fecha})")
    return senal("S1", "ficha aprobada sin recibo de aprobación",
                 violaciones, universo, posteriores, detalle)


# ------------------------------------------------------------------ recibos
def recibos_de_ejecucion(ws):
    """Los recibos `ejecucion/v1`, con la fecha que se les pueda sacar.

    Los recibos reales NO llevan campo de fecha (medido sobre 288 de este taller): se cae a
    la mtime del fichero, que es el único rastro temporal que existe. Los sintéticos de la
    suite sí la llevan, y esa manda.
    """
    salida = []
    for ruta in sorted((ws / ".runtime/ejecuciones").glob("*.json")):
        datos = leer_json(ruta)
        if not isinstance(datos, dict):
            continue
        fecha = solo_fecha(datos.get("fecha") or datos.get("iniciado"))
        if not fecha:
            try:
                fecha = date.fromtimestamp(ruta.stat().st_mtime).isoformat()
            except OSError:
                fecha = None
        salida.append((datos, fecha))
    return salida


def s2_recibo_sin_resultado(recibos, corte):
    """El ayudante que se fue y nadie cerró: recibo abierto para siempre."""
    universo = violaciones = posteriores = 0
    for datos, fecha in recibos:
        universo += 1
        if "resultado" in datos:
            continue
        violaciones += 1
        if posterior(fecha, corte):
            posteriores += 1
    return senal("S2", "recibo de ejecución sin resultado",
                 violaciones, universo, posteriores)


def s8_revisor_con_sesion_del_constructor(recibos, corte):
    """El auto-sello: el revisor firma con la misma sesión que construyó.

    El denominador son los recibos de REVISOR: es el único sitio donde el auto-sello puede
    ocurrir, y meter en el denominador a los constructores lo diluiría hasta la nada.
    """
    del_constructor = {}
    for datos, _ in recibos:
        if datos.get("rol") == "constructor":
            sesion = (datos.get("lease") or {}).get("session_id")
            if sesion:
                del_constructor.setdefault(datos.get("unidad"), set()).add(sesion)

    universo = violaciones = posteriores = 0
    detalle = []
    for datos, fecha in recibos:
        if datos.get("rol") != "revisor":
            continue
        universo += 1
        sesion = (datos.get("lease") or {}).get("session_id")
        if not sesion or sesion not in del_constructor.get(datos.get("unidad"), set()):
            continue
        violaciones += 1
        if posterior(fecha, corte):
            posteriores += 1
            detalle.append(str(datos.get("unidad")))
    return senal("S8", "revisor firmando con la sesión del constructor",
                 violaciones, universo, posteriores, detalle)


# ------------------------------------------------------------------ peticiones
def peticiones_del_taller(ws):
    salida = []
    for ruta in sorted((ws / "docs/05-trabajo/peticiones").glob("*/peticion.json")):
        datos = leer_json(ruta)
        if isinstance(datos, dict):
            salida.append(datos)
    return salida


def terminales(peticion):
    return [p for p in peticion.get("procesos", []) if p.get("estado") == "terminal"]


def s3_cerrada_con_un_proceso(peticiones, corte):
    """Cerrar con un solo proceso terminal es cerrar por cascada: nadie escribió cobertura."""
    universo = violaciones = posteriores = 0
    for peticion in peticiones:
        if peticion.get("estado") != "cerrada":
            continue
        universo += 1
        if len(terminales(peticion)) > 1:
            continue
        violaciones += 1
        if posterior(solo_fecha(peticion.get("creada")), corte):
            posteriores += 1
    return senal("S3", "petición cerrada con ≤1 proceso terminal",
                 violaciones, universo, posteriores)


def s4_encaminada_sin_terminal(peticiones, corte):
    """Encaminada y sin un solo proceso terminal: se dijo «va por aquí» y ahí quedó."""
    universo = violaciones = posteriores = 0
    for peticion in peticiones:
        if peticion.get("estado") != "encaminada":
            continue
        universo += 1
        if terminales(peticion):
            continue
        violaciones += 1
        if posterior(solo_fecha(peticion.get("creada")), corte):
            posteriores += 1
    return senal("S4", "petición encaminada sin ningún proceso terminal",
                 violaciones, universo, posteriores)


# ------------------------------------------------------------------ S5 · S6
def rechazos_de_los_scripts(ws):
    """[(fichero, texto del primer argumento de cada `fail(...)`)] de los scripts del método.

    Con `ast`, no con `grep`: `fail` citado en un comentario o dentro de una cadena no es un
    rechazo, y contar de más aquí sería inventar una señal.
    """
    encontrados = []
    for ruta in sorted((ws / "docs/00-metodo/scripts").glob("*.py")):
        fuente = leer_texto(ruta)
        try:
            arbol = ast.parse(fuente)
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call) or not nodo.args:
                continue
            nombre = getattr(nodo.func, "id", None) or getattr(nodo.func, "attr", None)
            if nombre != "fail":
                continue
            crudo = ast.get_source_segment(fuente, nodo.args[0]) or ""
            encontrados.append((ruta.name, crudo))
    return encontrados


def s5_fail_sin_id(rechazos):
    """Un rechazo sin id estructurado no se puede contar, ni citar, ni buscar dos veces."""
    violaciones = sum(1 for _, crudo in rechazos if not ID_ESTRUCTURADO.match(crudo))
    return senal("S5", "`fail()` sin id estructurado", violaciones, len(rechazos), 0)


def s6_rechazo_sin_salida(ws, rechazos):
    """Un bloqueo que no dice cómo salir es un defecto, no un mensaje (regla 13).

    Esta señal NO se vuelve a implementar: se le pregunta a `lint_salidas.py`, que es el
    guardián que ya posee esa definición (qué es un rechazo, qué cuenta como salida, qué
    está exento por diseño). Dos definiciones del mismo concepto derivarían, y entonces la
    señal mediría el desacuerdo entre dos scripts en vez de medir el método. Si no se puede
    importar —un taller sin ese guardián— se cae a la cuenta pobre sobre los `fail()`, que
    es peor pero no es cero.
    """
    try:
        aqui = str(Path(__file__).resolve().parent)
        if aqui not in sys.path:
            sys.path.insert(0, aqui)
        import lint_salidas
        cubos, _ = lint_salidas.inventario(ws / "docs/00-metodo/scripts", ws)
        universo = sum(len(v) for v in cubos.values())
        return senal("S6", "rechazo que no nombra su salida",
                     len(cubos["fuera_de_banda"]), universo, 0)
    except Exception:
        violaciones = sum(1 for _, crudo in rechazos if SALIDA not in crudo)
        return senal("S6", "rechazo que no nombra su salida (cuenta pobre)",
                     violaciones, len(rechazos), 0)


# ------------------------------------------------------------------ S7
def nombres_de_test(ws):
    """Los nombres de función `test_*` de la suite del repo de código, leídos con `ast`."""
    encontrados = set()
    for relativa in ("main/visor/tests", "visor/tests"):
        carpeta = ws / relativa
        if not carpeta.is_dir():
            continue
        for ruta in sorted(carpeta.rglob("test_*.py")):
            try:
                arbol = ast.parse(leer_texto(ruta))
            except SyntaxError:
                continue
            for nodo in ast.walk(arbol):
                if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    encontrados.add(nodo.name)
    return encontrados


def s7_ejecutor_sin_dientes(ws):
    """Ejecutor cuyo par de dientes no está declarado, o está declarado y no existe.

    `funcion_existe()` acepta un `def` VACIADO: «tiene ejecutor» significa hoy «existe un
    `def` con ese nombre». El par de dientes es la otra verdad, y un nombre escrito a mano
    en el JSON no es un par: tiene que existir como test.
    """
    datos = leer_json(ws / "docs/00-metodo/reglas.json") or {}
    reglas = datos.get("reglas", {})
    tests = nombres_de_test(ws)
    universo = violaciones = 0
    detalle = []
    for clave in sorted(reglas):
        entrada = reglas[clave] or {}
        if not entrada.get("ejecutor"):
            continue
        universo += 1
        par = entrada.get("dientes")
        existe = bool(par) and (par in tests or all(
            f"{par}{sufijo}" in tests for sufijo in ("_bloquea", "_abierto_pasa")))
        if not existe:
            violaciones += 1
            detalle.append(str(entrada["ejecutor"]))
    return senal("S7", "ejecutor sin par de dientes", violaciones, universo, 0, detalle[:5])


# ------------------------------------------------------------------ medida
def medir(ws, corte):
    recibos = recibos_de_ejecucion(ws)
    peticiones = peticiones_del_taller(ws)
    rechazos = rechazos_de_los_scripts(ws)
    return [
        s1_aprobado_sin_recibo(ws, corte),
        s2_recibo_sin_resultado(recibos, corte),
        s3_cerrada_con_un_proceso(peticiones, corte),
        s4_encaminada_sin_terminal(peticiones, corte),
        s5_fail_sin_id(rechazos),
        s6_rechazo_sin_salida(ws, rechazos),
        s7_ejecutor_sin_dientes(ws),
        s8_revisor_con_sesion_del_constructor(recibos, corte),
    ]


def aplicar_trinquete(senales, base):
    """Para S5-S7, «posterior al corte» es lo que SUBIÓ sobre la línea base congelada.

    Sin base congelada no hay «subió»: se informa y no se bloquea. Un guardián que se
    inventa el pasado para poder fallar es peor que no tenerlo.
    """
    congeladas = (base or {}).get("senales") or {}
    for una in senales:
        if una["id"] not in ESTRUCTURALES:
            continue
        tope = congeladas.get(una["id"])
        una["base"] = tope if isinstance(tope, int) else None
        if isinstance(tope, int):
            una["posteriores"] = max(0, una["violaciones"] - tope)
    return senales


# ------------------------------------------------------------------ main
def main(argv=None):
    p = argparse.ArgumentParser(
        description="Las ocho señales de la reforma, con fecha de corte y denominador.")
    p.add_argument("--workspace", default=".", help="raíz del taller (por defecto, el cwd)")
    p.add_argument("--corte", default=date.today().isoformat(),
                   help="fecha YYYY-MM-DD: solo lo POSTERIOR puede bloquear")
    p.add_argument("--base", default=None,
                   help="línea base congelada (por defecto, docs/00-metodo/"
                        "invariantes-baseline.json del workspace)")
    p.add_argument("--json", action="store_true", help="la medida entera, en JSON")
    p.add_argument("--congelar", action="store_true",
                   help="reescribe la línea base de las señales de código con la de hoy")
    args = p.parse_args(argv)

    ws = Path(args.workspace).resolve()
    ruta_base = (Path(args.base) if args.base
                 else ws / "docs/00-metodo/invariantes-baseline.json")

    # `fromisoformat`, no un regex de dígitos: `2026-13-99` casa con `\d{4}-\d{2}-\d{2}`
    # y no es una fecha. Un corte imposible no falla — se queda por delante de TODO y deja
    # la cuenta que bloquea en 0 para siempre, que es la peor manera de romper esto.
    try:
        date.fromisoformat(args.corte)
        corte_valido = True
    except ValueError:
        corte_valido = False
    if not corte_valido:
        print(f"FAIL [INV-001] el corte `{args.corte}` no es una fecha YYYY-MM-DD: sin corte "
              f"no se puede separar lo que la reforma puede evitar de lo que ya pasó.\n"
              f"    SALIDA: repite con  python3 {YO} --corte {date.today().isoformat()}")
        return 1

    senales = medir(ws, args.corte)

    if args.congelar:
        ruta_base.parent.mkdir(parents=True, exist_ok=True)
        ruta_base.write_text(json.dumps({
            "_porque": PORQUE,
            "base": {"fecha": date.today().isoformat(), "sha": sha_corto(ws),
                     "corte": args.corte},
            "senales": {una["id"]: una["violaciones"] for una in senales},
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"OK línea base congelada en {ruta_base.name}: "
              + " · ".join(f"{u['id']}={u['violaciones']}" for u in senales))
        return 0

    base = leer_json(ruta_base) if ruta_base.is_file() else None
    senales = aplicar_trinquete(senales, base)
    rojas = [una for una in senales if una["posteriores"] > 0]
    veredicto = "rojo" if rojas else "verde"

    if args.json:
        print(json.dumps({"corte": args.corte, "veredicto": veredicto,
                          "base": (base or {}).get("base"), "senales": senales},
                         ensure_ascii=False, indent=1))
        return 1 if rojas else 0

    print(f"Señales de la reforma · corte {args.corte}"
          f"{'' if base else '  (sin línea base congelada)'}")
    print(f"{'':4} {'histórica':>12}  {'desde el corte':>14}")
    for una in senales:
        marca = "FAIL" if una["posteriores"] else "  ok"
        cuenta = f"{una['violaciones']}/{una['universo']}"
        print(f"{una['id']:4} {cuenta:>12}  {una['posteriores']:>14}  {marca}  {una['titulo']}")
        for linea in una["detalle"][:3]:
            print(f"       · {linea}")

    if base is None:
        print(f"\nLas señales de código (S5-S7) informan pero no pueden bloquear: no hay "
              f"línea base con la que comparar.\n"
              f"    SALIDA: congélala una vez con  python3 {YO} --congelar")

    print(f"\nVEREDICTO: {veredicto}"
          + (f" · {len(rojas)} señal(es) con cuenta posterior al corte: "
             + ", ".join(una["id"] for una in rojas) if rojas else
             " · nada posterior al corte; lo histórico informa, no bloquea"))
    if rojas:
        print(f"    SALIDA: mira el detalle con  python3 {YO} --corte {args.corte} --json ; "
              f"si la señal es de código y de verdad bajó, adopta el encogimiento con "
              f"python3 {YO} --congelar")
    return 1 if rojas else 0


if __name__ == "__main__":
    sys.exit(main())
