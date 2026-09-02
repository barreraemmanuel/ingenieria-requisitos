#!/usr/bin/env python3
"""Guardián de JUNTAS: lo que se rompe entre dos piezas que por separado están bien.

La autopsia de gentle-ai es honesta sobre por qué, tras cientos de arreglos y decenas de
guardianes, seguían escapándose defectos: **la verificación mira hacia dentro, y los defectos
viven en las juntas** — el guardián con su punto de llamada, el productor con su consumidor,
la promesa escrita con quien debería hacerla cumplir.

Aplica literal a `lint_metodo.py`: sección a sección es un validador hacia dentro (la raíz
tiene la forma correcta, el árbol congelado, los frontmatters, el archivo). La ÚNICA sección
que mira una junta —worktrees contra unidades— es la que sigue cogiendo cosas reales. Por eso
esto es un fichero APARTE: son comprobaciones ENTRE piezas, y meterlas dentro del validador
hacia dentro sería repetir el error que se está corrigiendo.

Las cuatro juntas que vigila:

  (a) EL VOCABULARIO EN TRES SITIOS. `TIPOS` y `ESTADOS` se escribían dos veces en código
      (`unidad.py` como listas, `lint_metodo.py` como conjuntos) y una tercera en la prosa de
      `00-metodo/README.md`. Coincidían por suerte: nada lo comprobaba, y la copia de prosa ya
      había derivado. Ahora el código sale de `repo_config.py` —una junta que no se puede
      desalinear— y lo que aquí se vigila es que siga siendo así y que la PROSA lo acompañe.
  (b) EL TOPE DE DIFF DEL CARRIL DIRECTO. La regla 9 y el ADR-017 prometen «menos de 250
      líneas» y ningún script lo medía: no había un solo `--shortstat` ni `--numstat` en los
      catorce scripts del método. Aquí se mide contra git, que es donde está la verdad.
  (c) LAS PUERTAS DURAS NO TIENEN DUEÑO. Una puerta que el texto declara infranqueable y que
      ningún script ejecuta es prosa: ya se descubrió una vez, y el ADR-029 retiró la marca
      del método entero por eso mismo. El inventario congelado de `puertas.json` es la memoria
      de esa retirada, viaja a cada workspace y solo puede encoger — el mismo trinquete de la
      049, y por el mismo motivo: exigir que la lista llegue a cero para que el guardián pueda
      existir significa que el guardián no existe nunca.
  (d) LAS REGLAS DEL MÉTODO SIN EJECUTOR. La junta más grande, y la que da nombre al ADR-029:
      una regla escrita que ningún script hace cumplir es una promesa, no una defensa. El
      inventario del 22-08 contó 110 reglas y 58 huérfanas; la 033 puso ejecutor a las cuatro
      de más daño y el resto quedó en una PETICIÓN, que es un sitio que no lee ningún script.
      `reglas.json` las pone donde sí se leen: cada regla con su ancla, y con ejecutor
      (`script.py:función`), con motivo de inejecutabilidad (`por_diseno`), o sin nada — y esa
      última cuenta está congelada y SOLO PUEDE BAJAR. Escribir una regla nueva sin decir quién
      la ejecuta es FAIL; quitar el script que ejecutaba una, también.

  (e) LOS EJECUTORES SIN DIENTES (146, opt-in con `--dientes`). `funcion_existe()` acepta un
      `def` VACIADO: «tiene ejecutor» significa hoy «existe un `def` con ese nombre», y así
      es como los mecanismos se pierden de verdad —nadie los borra, se vacían—. Cada ejecutor
      declara en `reglas.json` su `id` y su `dientes`: el par de tests que demuestra que el
      mecanismo hace algo (con él, el acto se bloquea; con el ejecutor abierto solo dentro
      del test, el mismo acto pasa). `base.sin_dientes` es el trinquete y solo baja.

Uso: python3 docs/00-metodo/scripts/lint_juntas.py [--raiz RUTA] [--dientes]
                                                   [--congelar-puertas] [--congelar-reglas]
Sin dependencias: solo stdlib. Exit 0 si las cuatro juntas cuadran; exit 1 si alguna no.
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import date
from collections import namedtuple
from pathlib import Path

# Windows: en cuanto la salida va a un PIPE —la CI, cualquier harness de agente— el encoding
# pasa a ser el local (cp1252) y un `ñ` o un `·` mata el script con UnicodeEncodeError. Es el
# camino normal, no una consola rara: se fuerza UTF-8 antes de imprimir nada.
for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

TOPE_DIRECTO = 250  # regla 9 de AGENTS.md y ADR-017
YO = "docs/00-metodo/scripts/lint_juntas.py"

# La marca de puerta dura, compuesta en trozos A PROPÓSITO: el ADR-029 la retiró del texto del
# método y un test barre estos ficheros para comprobarlo. Escribirla entera aquí pondría en
# rojo a ese guardián; la comprobación es exactamente la misma.
MARCA = "<" + "HARD" + "-GATE" + ">"

Constante = namedtuple("Constante", "valores origen")


# ------------------------------------------------------------------ (a) vocabulario
def constante(ruta, nombre, _vistos=None):
    """Lee una constante de nivel de módulo SIN importar el script.

    Importar no vale: varios scripts del método ejecutan su linter al cargarse y el guardián
    heredaría su salida y su código de salida (R3).

    Resuelve tres formas, que son las que de verdad aparecen: el literal (`TIPOS = [...]`), el
    alias a otro módulo del mismo directorio (`TIPOS = repo_config.TIPOS`, que es como quedó
    tras centralizar el vocabulario) y el envoltorio de conversión (`set(...)`, `tuple(...)`).
    Devuelve `Constante(valores, origen)`: el ORIGEN importa tanto como el valor, porque dos
    constantes que salen del mismo fichero no pueden desalinearse.
    """
    ruta = Path(ruta)
    # El corte de ciclos va por (fichero, NOMBRE), no por fichero: dentro de un módulo una
    # constante se define a partir de otra —`CARRILES = tuple(ESFUERZO_POR_CARRIL)`— y cortar
    # por fichero dejaba ese caso sin leer, en silencio.
    _vistos = _vistos or set()
    if (str(ruta), nombre) in _vistos:
        return None  # un alias circular: se corta y se informa como ilegible
    _vistos = _vistos | {(str(ruta), nombre)}
    try:
        arbol = ast.parse(ruta.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None
    for nodo in arbol.body:
        if not isinstance(nodo, ast.Assign):
            continue
        if not any(isinstance(d, ast.Name) and d.id == nombre for d in nodo.targets):
            continue
        return _resolver(nodo.value, ruta, _vistos)
    return None


def _resolver(valor, ruta, vistos):
    """El valor de una asignación, siguiendo un salto de módulo como mucho por escalón."""
    if isinstance(valor, ast.Call) and isinstance(valor.func, ast.Name) \
            and valor.func.id in {"set", "tuple", "list", "frozenset", "sorted"} \
            and len(valor.args) == 1:
        return _resolver(valor.args[0], ruta, vistos)
    if isinstance(valor, ast.Attribute) and isinstance(valor.value, ast.Name):
        vecino = ruta.parent / f"{valor.value.id}.py"
        if vecino.is_file():
            return constante(vecino, valor.attr, vistos)
        return None
    if isinstance(valor, ast.Name):
        return constante(ruta, valor.id, vistos)
    try:
        return Constante(set(ast.literal_eval(valor)), ruta.name)
    except (ValueError, TypeError, SyntaxError):
        return None


# Las dos parejas que tienen que decir lo mismo, con el nombre que usa cada lado.
PAREJAS = (
    ("TIPOS", "unidad.py", "TIPOS", "lint_metodo.py", "TIPOS"),
    ("ESTADOS", "unidad.py", "ESTADOS", "lint_metodo.py", "ESTADOS_UNIDAD"),
)

# La copia en PROSA se declara en el frontmatter de ejemplo de `00-metodo/README.md`, y ahí
# sí es una lista cerrada que se puede comparar término a término en los DOS sentidos:
#   tipo: bug | feature | refactor | …
#   estado: planificada | en_obra | …
DECLARACION = {"TIPOS": "tipo", "ESTADOS": "estado"}


def declarado_en_prosa(texto, clave):
    """El conjunto que la prosa declara para `tipo:` o `estado:`. None si no lo declara."""
    patron = re.compile(rf"^{re.escape(clave)}:\s*(.+)$", re.MULTILINE)
    encaje = patron.search(texto)
    if not encaje:
        return None
    valores = {t.strip().strip("`") for t in encaje.group(1).split("|")}
    valores = {v for v in valores if re.fullmatch(r"[a-z_]+", v)}
    return valores or None


def junta_vocabulario(raiz):
    scripts = raiz / "docs/00-metodo/scripts"
    problemas = []
    for etiqueta, f1, n1, f2, n2 in PAREJAS:
        a = constante(scripts / f1, n1)
        b = constante(scripts / f2, n2)
        if a is None or b is None:
            ilegible = f1 if a is None else f2
            problemas.append((
                f"{etiqueta}: no puedo leer el vocabulario en {ilegible} sin importarlo",
                f"declara la constante en el nivel de módulo, como literal o como alias de "
                f"repo_config, y vuelve a medir con  python3 {YO}"))
            continue
        if a.valores != b.valores:
            problemas.append((
                f"{etiqueta} no coincide entre {f1} y {f2}: solo en {f1} "
                f"{sorted(a.valores - b.valores)} · solo en {f2} "
                f"{sorted(b.valores - a.valores)}",
                f"mueve el vocabulario a docs/00-metodo/scripts/repo_config.py e impórtalo en "
                f"los dos, y vuelve a medir con  python3 {YO}"))

    # La tercera copia, la de prosa: cada término del vocabulario está escrito en el README.
    readme = raiz / "docs/00-metodo/README.md"
    if not readme.is_file():
        problemas.append((
            "no existe docs/00-metodo/README.md: la copia en prosa del vocabulario no se "
            "puede comprobar",
            f"repárala con  python3 visor/actualizar.py revisar --todos  desde la herramienta "
            f"de ingeniería de requisitos, y vuelve a medir con  python3 {YO}"))
        return problemas
    texto = readme.read_text(encoding="utf-8", errors="replace")
    for etiqueta, f1, n1, _f2, _n2 in PAREJAS:
        leida = constante(scripts / f1, n1)
        if leida is None:
            continue
        ausentes = sorted(v for v in leida.valores if v not in texto)
        if ausentes:
            problemas.append((
                f"{etiqueta}: {ausentes} está(n) en el código y NO en la prosa de "
                f"docs/00-metodo/README.md",
                f"añádelo a la tabla del README, o retíralo del vocabulario de "
                f"docs/00-metodo/scripts/repo_config.py; después  python3 {YO}"))
            continue
        # Y al revés (R2): un término que la prosa declara y el código ya no admite. La deriva
        # va en los dos sentidos, y la de vuelta es peor: manda a alguien a escribir en su
        # ficha un valor que el script rechazará.
        prosa = declarado_en_prosa(texto, DECLARACION[etiqueta])
        if prosa and prosa - leida.valores:
            problemas.append((
                f"{etiqueta}: {sorted(prosa - leida.valores)} lo declara la prosa de "
                f"docs/00-metodo/README.md y NO existe en el código",
                f"retíralo del README, o añádelo al vocabulario de "
                f"docs/00-metodo/scripts/repo_config.py; después  python3 {YO}"))
    return problemas


def junta_carriles(raiz):
    """R9 — informativo, JAMÁS un fallo: son conceptos distintos con el mismo nombre."""
    scripts = raiz / "docs/00-metodo/scripts"
    trozos = []
    for fichero in ("lint_metodo.py", "peticion.py", "repo_config.py"):
        leida = constante(scripts / fichero, "CARRILES")
        if leida is not None:
            trozos.append(f"{fichero} {len(leida.valores)}")
    return trozos


# ------------------------------------------------------------------ (b) tope del carril directo
def frontmatter(ruta):
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    if not texto.startswith("---"):
        return {}
    fin = texto.find("\n---", 3)
    datos = {}
    for linea in texto[3:fin if fin > 0 else len(texto)].splitlines():
        if ":" in linea and not linea.strip().startswith("#"):
            clave, _, valor = linea.partition(":")
            datos[clave.strip()] = valor.split("#")[0].strip()
    return datos


def lineas_de_diff(repo, rama, principal="main"):
    """Líneas cambiadas de una rama contra la principal. None si no se puede medir."""
    try:
        salida = subprocess.run(
            ["git", "-C", str(repo), "diff", "--shortstat", f"{principal}...{rama}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if salida.returncode != 0:
        return None
    pares = re.findall(r"(\d+) insertion|(\d+) deletion", salida.stdout)
    return sum(int(a or b) for a, b in pares)


def repo_de_codigo(raiz):
    """(carpeta del repo de código, rama principal) según repos.yaml, con el defecto de siempre."""
    try:
        import repo_config
        return repo_config.repo_code(raiz)
    except Exception:  # noqa: BLE001 — sin repos.yaml legible se mide contra el defecto
        return raiz / "main", "main"


def junta_tope_directo(raiz):
    problemas = []
    trabajo = raiz / "docs/05-trabajo"
    if not trabajo.is_dir():
        return problemas
    repo, principal = repo_de_codigo(raiz)
    for carpeta in sorted(trabajo.glob("[0-9][0-9][0-9]-*")):
        ficha = carpeta / "especificacion.md"
        if not ficha.is_file():
            continue
        fm = frontmatter(ficha)
        if fm.get("carril") != "directo":
            continue
        if fm.get("estado") in ("planificada", "descartada"):
            continue
        medidas = lineas_de_diff(repo, carpeta.name, principal)
        # R5: la rama ya no existe porque el cierre la borró. No es un fallo y no se dice:
        # si lo fuera, cada unidad cerrada dejaría un FAIL eterno detrás.
        if medidas is None:
            continue
        if medidas > TOPE_DIRECTO:
            problemas.append((
                f"{carpeta.name}: carril directo con {medidas} líneas de diff medidas contra "
                f"{principal} (tope {TOPE_DIRECTO}, regla 9 y ADR-017)",
                f"súbela de carril: rehaz la ficha con  python3 "
                f"docs/00-metodo/scripts/unidad.py nueva {fm.get('tipo', 'feature')} <slug>  "
                f"sin --directo y re-encuadra su petición"))
    return problemas


# ------------------------------------------------------------------ (c) puertas duras con dueño
def puertas_en_prosa(raiz):
    """Cada marca de puerta dura de la prosa del método, con su fichero y su línea.

    Solo `docs/00-metodo/`. Un contrato de unidad que habla DE las puertas duras no declara
    ninguna: incluir `docs/05-trabajo/` hacía que escribir sobre este guardián disparara este
    guardián, con seis falsos positivos a la primera.

    Y NO se excluye la marca entre acentos graves. Las puertas reales de los runbooks se
    escriben justo así —«`<…>` **Ante la duda…**»— y excluirlas dejaba el inventario en CERO,
    que es peor que no tenerlo.
    """
    encontradas = []
    for ruta in sorted((raiz / "docs/00-metodo").rglob("*.md")):
        try:
            lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for numero, linea in enumerate(lineas, 1):
            if MARCA in linea:
                encontradas.append({
                    "fichero": ruta.relative_to(raiz).as_posix(),
                    "linea": numero,
                    "texto": re.sub(r"\s+", " ", linea.replace(MARCA, "")).strip()[:160],
                })
    return encontradas


def clave_de(puerta):
    """Índice del inventario: fichero + principio del texto. Nunca la línea.

    Editar prosa más arriba no debe mover una entrada; cambiar lo que la puerta DICE sí reabre
    la pregunta, que es justo cuando esa puerta le debe un dueño a alguien.
    """
    return f"{puerta['fichero']}::{puerta['texto'][:80]}"


PORQUE = ("Cada puerta dura del método y QUIÉN la hace cumplir. Una puerta sin dueño es prosa: "
          "ya nos pasó con la de adopcion.md, que era texto que nadie ejecutaba, y el ADR-029 "
          "retiró la marca del método por eso. Esta lista está CONGELADA y solo puede encoger; "
          "una marca nueva que no esté aquí es FAIL, y una entrada que ya no case con ninguna "
          "marca también, porque arreglada y perdida son indistinguibles desde fuera.")


def congelar(inventario, puertas):
    anterior = {}
    if inventario.is_file():
        try:
            anterior = json.loads(inventario.read_text(encoding="utf-8")).get("puertas", {})
        except (OSError, ValueError):
            anterior = {}
    inventario.parent.mkdir(parents=True, exist_ok=True)
    congeladas = {}
    for puerta in puertas:
        clave = clave_de(puerta)
        congeladas[clave] = {
            "fichero": puerta["fichero"],
            "texto": puerta["texto"],
            # Un dueño ya declarado NO se pierde al recongelar: la lista encoge, la autoría no.
            "dueno": anterior.get(clave, {}).get("dueno"),
        }
    inventario.write_text(
        json.dumps({"_porque": PORQUE, "puertas": congeladas}, ensure_ascii=False, indent=1)
        + "\n", encoding="utf-8")
    return congeladas


def junta_puertas(raiz, inventario):
    puertas = puertas_en_prosa(raiz)
    vivas = {clave_de(p): p for p in puertas}
    if not inventario.is_file():
        return [(f"no existe el inventario de puertas {inventario.name}: sin memoria, el "
                 f"trinquete no vigila nada",
                 f"créalo una vez con  python3 {YO} --congelar-puertas")], 0
    try:
        datos = json.loads(inventario.read_text(encoding="utf-8")).get("puertas", {})
    except (OSError, ValueError) as exc:
        return [(f"el inventario de puertas no se puede leer ({exc})",
                 f"recongélalo con  python3 {YO} --congelar-puertas")], 0
    problemas = []
    nuevas = [k for k in vivas if k not in datos]
    huerfanas = [k for k in datos if k not in vivas]
    if nuevas:
        detalle = "; ".join(f"{vivas[k]['fichero']}:{vivas[k]['linea']}" for k in nuevas[:5])
        problemas.append((
            f"{len(nuevas)} puerta(s) dura(s) NUEVA(s) sin dueño declarado: {detalle}",
            f"declara en el inventario qué script la hace cumplir, o quita la marca —una "
            f"puerta que nadie ejecuta es prosa (ADR-029)—; después  python3 {YO}"))
    if huerfanas:
        detalle = "; ".join(datos[k].get("fichero", k) for k in huerfanas[:5])
        problemas.append((
            f"{len(huerfanas)} entrada(s) del inventario ya no existe(n) en la prosa: "
            f"{detalle}. Arreglada y perdida son indistinguibles desde fuera",
            f"si se retiraron a propósito, adopta el encogimiento con  python3 {YO} "
            f"--congelar-puertas"))
    sin_dueno = sum(1 for k in datos if not datos[k].get("dueno"))
    return problemas, sin_dueno


# ------------------------------------------------------------------ (d) reglas con ejecutor
# Una regla del método se escribe SIEMPRE de una de estas dos formas, y por eso se puede
# extraer sin ambigüedad: numerada («7. **Merge y cierre son indivisibles.**») o en viñeta
# bajo «Reglas de oro» («- **Fusionar main NO despliega.**»). Lo que ancla la entrada es el
# TÍTULO EN NEGRITA, no el numeral: renumerar AGENTS.md no debe mover el inventario entero,
# pero cambiar lo que una regla DICE sí reabre la pregunta de quién la ejecuta.
REGLA_NUMERADA = re.compile(r"^\d+\.\s+\*\*(.+?)\*\*")
REGLA_ORO = re.compile(r"^[-*]\s+\*\*(.+?)\*\*")
TITULO_ORO = re.compile(r"^#+\s*Reglas de oro", re.IGNORECASE)

PORQUE_REGLAS = (
    "Cada regla del método y QUIÉN la hace cumplir. El ADR-029 lo zanjó: una regla o la "
    "ejecuta un script, o está declarada inejecutable con su motivo, o se retira. Esta lista "
    "está CONGELADA por el número de reglas SIN ejecutor, y ese número solo puede bajar: una "
    "regla nueva sin entrada es FAIL, una cuenta que sube es FAIL, y un ejecutor que ya no "
    "existe es FAIL —arreglada y perdida son indistinguibles desde fuera—. La base la escribe "
    "lint_juntas.py --congelar-reglas, con su fecha y su commit; a mano no vale.")


def reglas_en_prosa(raiz):
    """Cada regla del método de hoy, con su fichero, su línea y su título.

    Tres fuentes, que son las tres formas en que el método escribe una obligación: los
    numerales de `AGENTS.md` (el arranque y las reglas duras), las viñetas de su sección
    «Reglas de oro», y las puertas duras marcadas en la prosa de `docs/00-metodo/` —una puerta
    infranqueable ES una regla, y la más cara de todas si nadie la ejecuta.
    """
    encontradas = []
    agents = raiz / "AGENTS.md"
    if agents.is_file():
        en_reglas_de_oro = False
        texto = agents.read_text(encoding="utf-8", errors="replace")
        for numero, linea in enumerate(texto.splitlines(), 1):
            if linea.startswith("#"):
                en_reglas_de_oro = bool(TITULO_ORO.match(linea))
            encaje = REGLA_NUMERADA.match(linea)
            if encaje is None and en_reglas_de_oro:
                encaje = REGLA_ORO.match(linea)
            if encaje is None:
                continue
            encontradas.append({
                "fichero": "AGENTS.md",
                "linea": numero,
                "texto": re.sub(r"\s+", " ", encaje.group(1)).strip()[:80],
            })
    for puerta in puertas_en_prosa(raiz):
        encontradas.append({"fichero": puerta["fichero"], "linea": puerta["linea"],
                            "texto": puerta["texto"][:80]})
    return encontradas


def estado_de(entrada):
    """`ejecutor` · `por_diseño` · `sin_ejecutor`. Las tres casillas del ADR-029, y ninguna más."""
    if entrada.get("ejecutor"):
        return "ejecutor"
    if entrada.get("por_diseno"):
        return "por_diseño"
    return "sin_ejecutor"


def funcion_existe(raiz, ejecutor):
    """¿Existe de verdad la función `script.py:función` que una regla declara como ejecutor?

    Con `ast` y sin importar, por el mismo motivo que `constante()`: varios scripts del método
    ejecutan su linter al cargarse. Se acepta cualquier `def` del árbol —también un método de
    clase—: lo que se vigila es que el ejecutor no se haya evaporado, no dónde vive.
    """
    if not isinstance(ejecutor, str) or ":" not in ejecutor:
        return False
    script, _, funcion = ejecutor.partition(":")
    for candidata in (raiz / "docs/00-metodo/scripts" / script, raiz / script):
        if not candidata.is_file():
            continue
        try:
            arbol = ast.parse(candidata.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            return None
        return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == funcion
                   for n in ast.walk(arbol))
    return False


def sha_corto(raiz):
    """El commit sobre el que se congela. None si esto no es un repo: no todo workspace lo es."""
    try:
        salida = subprocess.run(
            ["git", "-C", str(raiz), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return salida.stdout.strip() or None if salida.returncode == 0 else None


def congelar_reglas(raiz, inventario, reglas, motivo=None):
    previo = {}
    if inventario.is_file():
        try:
            previo = json.loads(inventario.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previo = {}
    anterior = previo.get("reglas", {}) if isinstance(previo, dict) else {}
    congeladas = {}
    for regla in reglas:
        clave = clave_de(regla)
        previa = anterior.get(clave, {})
        congeladas[clave] = {
            "fichero": regla["fichero"],
            "texto": regla["texto"],
            # Recongelar adopta el ENCOGIMIENTO; jamás borra la autoría ya declarada.
            "ejecutor": previa.get("ejecutor"),
            # 146: el id y el par de dientes son autoría declarada, como el ejecutor; una
            # recongelación adopta encogimientos, nunca borra lo que alguien ya demostró.
            "id": previa.get("id"),
            "dientes": previa.get("dientes"),
            "por_diseno": previa.get("por_diseno"),
        }
    sin = sum(1 for e in congeladas.values() if estado_de(e) == "sin_ejecutor")
    sin_dientes = sum(1 for e in congeladas.values()
                      if e.get("ejecutor") and not e.get("dientes"))

    # El trinquete (146, ronda 2). Recongelar SIN comparar contra la base anterior es un
    # indulto: mide la regresión que acaba de entrar y la escribe como si siempre hubiera
    # estado ahí, con exit 0 y sin que nadie se entere. Las dos cuentas congeladas
    # —`sin_ejecutor` y `sin_dientes`— solo pueden encoger; para adoptar una subida hay que
    # firmarla con `--motivo`, que queda en `historial` y se imprime mientras exista.
    # Solo `sin_dientes`, que es la cuenta que introduce la 146. `sin_ejecutor` NO lleva
    # trinquete aquí a propósito: recongelar es el acto con el que se INVENTARÍA una regla
    # nueva —y una regla nueva nace sin ejecutor, así que esa cuenta sube por diseño—; quien
    # vigila que no crezca es la junta (d) al MEDIR, que ya falla si `sin > tope`. Meterla
    # aquí rompería el camino normal de declarar una regla, que no es lo que se estaba
    # arreglando.
    base_previa = (previo or {}).get("base") or {}
    crecidas = []
    antes = base_previa.get("sin_dientes")
    if isinstance(antes, int) and sin_dientes > antes:
        crecidas.append(("sin_dientes", antes, sin_dientes))
    if crecidas and not motivo:
        return None, sin, crecidas

    historial = list((previo or {}).get("historial") or [])
    for nombre, antes, ahora in crecidas:
        historial.append({"fecha": date.today().isoformat(), "cuenta": nombre,
                          "de": antes, "a": ahora, "motivo": motivo})

    inventario.parent.mkdir(parents=True, exist_ok=True)
    inventario.write_text(json.dumps({
        "_porque": PORQUE_REGLAS,
        "base": {"sin_ejecutor": sin, "fecha": date.today().isoformat(),
                 "sha": sha_corto(raiz), "sin_dientes": sin_dientes},
        "historial": historial,
        "reglas": dict(sorted(congeladas.items())),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return congeladas, sin, crecidas


def junta_reglas(raiz, inventario):
    """(problemas, sin_ejecutor, base) — la cuenta de huérfanas contra la congelada."""
    vivas = {clave_de(r): r for r in reglas_en_prosa(raiz)}
    if not inventario.is_file():
        return [(f"no existe el inventario de reglas {inventario.name}: sin memoria, nadie "
                 f"sabe cuántas reglas del método no las hace cumplir nadie",
                 f"créalo una vez con  python3 {YO} --congelar-reglas")], 0, None
    try:
        datos = json.loads(inventario.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [(f"el inventario de reglas no se puede leer ({exc})",
                 f"recongélalo con  python3 {YO} --congelar-reglas")], 0, None
    reglas = datos.get("reglas", {})
    base = datos.get("base") or {}
    problemas = []

    nuevas = [k for k in vivas if k not in reglas]
    if nuevas:
        detalle = "; ".join(f"{vivas[k]['fichero']}:{vivas[k]['linea']} «{vivas[k]['texto']}»"
                            for k in sorted(nuevas)[:5])
        problemas.append((
            f"{len(nuevas)} regla(s) del método SIN inventariar: {detalle}. Una regla que "
            f"nadie ejecuta y que nadie ha contado es una promesa, no una defensa (ADR-029)",
            f"dile quién la ejecuta —`ejecutor: script.py:función`— o por qué no se puede "
            f"—`por_diseno: motivo`— en {inventario.name}; después  python3 {YO} "
            f"--congelar-reglas"))

    perdidos = [(k, reglas[k]["ejecutor"]) for k in sorted(reglas)
                if reglas[k].get("ejecutor")
                and funcion_existe(raiz, reglas[k]["ejecutor"]) is not True]
    if perdidos:
        detalle = "; ".join(f"«{reglas[k].get('texto', k)}» → {ej}" for k, ej in perdidos[:5])
        problemas.append((
            f"{len(perdidos)} ejecutor(es) declarados que ya NO existen: {detalle}. Arreglada "
            f"y perdida son indistinguibles desde fuera, así que se para",
            f"apunta la regla al ejecutor que hoy la hace cumplir en {inventario.name}, o "
            f"pásala a `por_diseno` con su motivo; después  python3 {YO}"))

    sin = sum(1 for e in reglas.values() if estado_de(e) == "sin_ejecutor")
    tope = base.get("sin_ejecutor")
    if not isinstance(tope, int) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                                                    str(base.get("fecha"))) \
            or "sha" not in base:
        problemas.append((
            f"la base de {inventario.name} no lleva número, fecha y commit: un número escrito "
            f"a mano no es una base congelada, es una opinión",
            f"recongélala con  python3 {YO} --congelar-reglas"))
        return problemas, sin, None
    if sin > tope:
        problemas.append((
            f"{sin} reglas sin ejecutor, y la base congelada son {tope}: la cuenta SUBIÓ. El "
            f"trinquete del ADR-029 solo deja que baje",
            f"dale ejecutor a la regla nueva, o decláralo imposible con su motivo en "
            f"{inventario.name}; si de verdad se retiró alguna, adopta el encogimiento con  "
            f"python3 {YO} --congelar-reglas"))
    return problemas, sin, tope


# ------------------------------------------------------- (e) dientes de cada ejecutor (146)
# Dónde vive la suite según DESDE DÓNDE se mire, que son tres sitios distintos y los tres
# reales: en un workspace el repo de código cuelga de `main/`; dentro del propio repo de
# código la suite está en la raíz; y cuando se apunta al método tal y como VIAJA
# (`--raiz .../plantilla`, que es como lo llama la suite del repo) queda un nivel por encima.
# Sin el tercero, el guardián no encuentra ni un test y denuncia como «sin dientes» a los
# cuatro ejecutores que sí lo tienen — que es justo el falso positivo que más caro sale.
CARPETAS_DE_TESTS = ("main/visor/tests", "visor/tests", "../visor/tests")
SUFIJOS_DEL_PAR = ("_bloquea", "_abierto_pasa")


def tests_del_repo(raiz):
    """{nombre del test: fuente del fichero} de la suite del repo de código.

    Con `ast`, no con `grep`: un nombre citado en un comentario o en una cadena no es un
    test, y el trinquete de los dientes existe justo para que «tener» no sea «parecer».
    """
    encontrados = {}
    for relativa in CARPETAS_DE_TESTS:
        carpeta = (raiz / relativa).resolve()
        if not carpeta.is_dir():
            continue
        for ruta in sorted(carpeta.rglob("test_*.py")):
            try:
                fuente = ruta.read_text(encoding="utf-8", errors="replace")
                arbol = ast.parse(fuente)
            except (OSError, SyntaxError):
                continue
            for nodo in ast.walk(arbol):
                if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    encontrados.setdefault(nodo.name, fuente)
    return encontrados


def par_de_dientes(entrada, tests):
    """None si el ejecutor tiene su par completo; si no, por qué no lo tiene.

    Tres cosas, y las tres importan: que el par esté DECLARADO, que sus dos mitades EXISTAN
    como tests de verdad, y que la fuente del par NOMBRE al ejecutor. Sin la tercera, un par
    con el nombre correcto puede estar midiendo cualquier otra cosa.
    """
    ejecutor = entrada.get("ejecutor")
    par = entrada.get("dientes")
    if not par:
        return "no declara `dientes`"
    faltan = [par + s for s in SUFIJOS_DEL_PAR if (par + s) not in tests]
    if faltan:
        return f"declara `dientes: {par}` y no existe {', '.join(faltan)}"
    funcion = str(ejecutor).partition(":")[2]
    if funcion and not any(funcion in tests[par + s] for s in SUFIJOS_DEL_PAR):
        return (f"el par `{par}` no nombra a `{funcion}`: mide algo, pero no consta que mida "
                f"este ejecutor")
    return None


def junta_dientes(raiz, inventario):
    """(problemas, sin_dientes, base) — ejecutores sin par de dientes, contra la congelada.

    `funcion_existe()` devuelve `True` sobre una función VACIADA (medido: cuerpo sustituido
    por «todo bien» con la forma correcta). O sea: hoy «esta regla tiene ejecutor» significa
    «existe un `def` con ese nombre», y así es exactamente como los mecanismos se pierden —
    nadie los borra, se vacían—. El par de dientes es la otra verdad: con el mecanismo el
    acto se bloquea, con el ejecutor abierto DENTRO del test el mismo acto pasa.

    Igual que (d), esto es un trinquete y no una exigencia de llegar a cero: pedir cero para
    poder existir es lo mismo que no existir. La cuenta de hoy se congela y solo puede bajar.
    """
    if not inventario.is_file():
        return [(f"no existe el inventario de reglas {inventario.name}: sin él no se sabe "
                 f"qué ejecutores deberían tener dientes",
                 f"créalo una vez con  python3 {YO} --congelar-reglas")], 0, None
    try:
        datos = json.loads(inventario.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [(f"el inventario de reglas no se puede leer ({exc})",
                 f"recongélalo con  python3 {YO} --congelar-reglas")], 0, None
    reglas = datos.get("reglas", {})
    tests = tests_del_repo(raiz)
    huerfanos = []
    for clave in sorted(reglas):
        entrada = reglas[clave]
        if not entrada.get("ejecutor"):
            continue
        motivo = par_de_dientes(entrada, tests)
        if motivo:
            huerfanos.append((entrada["ejecutor"], motivo))
    tope = (datos.get("base") or {}).get("sin_dientes")
    problemas = []
    if not isinstance(tope, int):
        problemas.append((
            f"la base de dientes de {inventario.name} no lleva número: sin trinquete, la "
            f"cuenta de ejecutores sin par puede subir sin que nadie se entere",
            f"congélala con  python3 {YO} --congelar-reglas"))
        return problemas, len(huerfanos), None
    if len(huerfanos) > tope:
        detalle = "; ".join(f"{ejecutor} ({motivo})" for ejecutor, motivo in huerfanos[:5])
        problemas.append((
            f"{len(huerfanos)} ejecutor(es) sin par de dientes, y la base congelada son "
            f"{tope}: la cuenta SUBIÓ. Un ejecutor sin par es un `def` del que nadie ha "
            f"demostrado que haga nada: {detalle}",
            f"escribe el par `test_dientes_<ID>_bloquea` / `_abierto_pasa` en "
            f"visor/tests/reforma/test_dientes_reforma.py y decláralo en {inventario.name}; "
            f"si de verdad bajó, adopta el encogimiento con  python3 {YO} --congelar-reglas"))
    return problemas, len(huerfanos), tope


# ------------------------------------------------------------------ main
def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raiz", default=str(Path(__file__).resolve().parents[3]),
                   help="raíz del meta-repo a medir (por defecto, el de este script)")
    p.add_argument("--puertas", default="docs/00-metodo/puertas.json",
                   help="inventario congelado de puertas duras, relativo a la raíz")
    p.add_argument("--congelar-puertas", action="store_true",
                   help="reescribe el inventario con las puertas de hoy (solo debe encoger)")
    p.add_argument("--reglas", default="docs/00-metodo/reglas.json",
                   help="inventario congelado de reglas del método, relativo a la raíz")
    p.add_argument("--congelar-reglas", action="store_true",
                   help="reescribe la base de reglas sin ejecutor con la de hoy, con su fecha "
                        "y su commit (solo debe bajar)")
    p.add_argument("--motivo", default=None,
                   help="firma por la que se adopta una SUBIDA de la base de reglas; queda "
                        "escrita en `historial` y se imprime mientras exista")
    p.add_argument("--dientes", action="store_true",
                   help="además, la junta (e): qué ejecutores no tienen par de dientes que "
                        "demuestre que hacen algo (unidad 146)")
    args = p.parse_args(argv)

    raiz = Path(args.raiz).resolve()
    inventario = raiz / args.puertas
    inventario_reglas = raiz / args.reglas
    print("== Guardián de juntas ==")

    if args.congelar_reglas:
        congeladas, sin, crecidas = congelar_reglas(
            raiz, inventario_reglas, reglas_en_prosa(raiz), args.motivo)
        if congeladas is None:
            detalle = ", ".join(f"{n}: {a}→{b}" for n, a, b in crecidas)
            print(f"  FAIL [JUN-002] la base de reglas SUBIRÍA y eso no se recongela solo "
                  f"({detalle}). Recongelar sin mirar el número anterior adopta la regresión "
                  f"que acaba de entrar y la deja escrita como si fuera lo normal.\n"
                  f"       salida: si de verdad hay que adoptarla, fírmala con  python3 {YO} "
                  f"--congelar-reglas --motivo \"por qué sube\"  ; si no, arregla lo que "
                  f"subió y vuelve a medir con  python3 {YO} --dientes")
            return 1
        print(f"   (d) base de reglas congelada en {sin} sin ejecutor, con fecha y commit, en "
              f"{args.reglas}")
        for nombre, antes, ahora in crecidas:
            print(f"       AVISO {nombre} SUBIÓ {antes}→{ahora}, adoptada con motivo: "
                  f"{args.motivo}")
        return 0

    if args.congelar_puertas:
        congeladas = congelar(inventario, puertas_en_prosa(raiz))
        print(f"   (c) inventario de puertas congelado con {len(congeladas)} entrada(s) en "
              f"{args.puertas}")
        return 0

    problemas = []
    vocabulario = junta_vocabulario(raiz)
    print(f"   (a) vocabulario compartido      "
          f"{'FAIL · ' + str(len(vocabulario)) if vocabulario else 'OK'}")
    problemas += vocabulario

    tope = junta_tope_directo(raiz)
    print(f"   (b) tope del carril directo     "
          f"{'FAIL · ' + str(len(tope)) if tope else 'OK'}")
    problemas += tope

    puertas, sin_dueno = junta_puertas(raiz, inventario)
    print(f"   (c) puertas duras con dueño     "
          f"{'FAIL · ' + str(len(puertas)) if puertas else 'OK'}"
          f"   ({sin_dueno} sin dueño declarado todavía)")
    problemas += puertas

    reglas, sin_ejecutor, tope = junta_reglas(raiz, inventario_reglas)
    base = "sin base" if tope is None else f"base {tope}"
    print(f"   (d) reglas con ejecutor         "
          f"{'FAIL · ' + str(len(reglas)) if reglas else 'OK'}"
          f"   ({sin_ejecutor} reglas sin ejecutor ({base}))")
    problemas += reglas

    if args.dientes:
        dientes, sin_dientes, tope_dientes = junta_dientes(raiz, inventario_reglas)
        base_dientes = "sin base" if tope_dientes is None else f"base {tope_dientes}"
        print(f"   (e) ejecutores con dientes      "
              f"{'FAIL · ' + str(len(dientes)) if dientes else 'OK'}"
              f"   ({sin_dientes} ejecutores sin par ({base_dientes}))")
        problemas += dientes

    # R9, y por eso va FUERA del recuento: `CARRILES` vale cosas distintas en cada script
    # porque son conceptos distintos con el mismo nombre. Se documenta, no se unifica.
    carriles = junta_carriles(raiz)
    if carriles:
        print(f"   (i) CARRILES: {' · '.join(carriles)} — conceptos distintos con el mismo "
              f"nombre; no se unifican (R9)")

    if problemas:
        print()
        for que, salida in problemas:
            print(f"  FAIL {que}")
            print(f"       salida: {salida}")
            print(f"       vuelve a medir con  python3 {YO}")
        print(f"\n{len(problemas)} junta(s) sin cuadrar.")
        return 1
    print("\n  OK   las cuatro juntas cuadran.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
