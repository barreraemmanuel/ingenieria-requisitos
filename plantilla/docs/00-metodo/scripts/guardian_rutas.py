#!/usr/bin/env python3
"""¿Adónde va este comando? La decisión por RUTA RESUELTA, sin hook y sin I/O.

El método ya tiene un filtro que mira comandos: el del canario (`canario.py:614-636`). Mide
bien la CONDUCTA de una sesión terminada, pero como puerta previa miente: pasado por las 12.397
llamadas reales de este taller, cerca de la mitad de sus disparos son texto que *cita* el
comando dentro de un heredoc —los propios informes de la investigación—. Ese es el defecto de
fondo: decide por el símbolo (la palabra `rm -rf main/`) y no por el hecho (qué ruta se toca).

Aquí la decisión es al revés: se resuelve la ruta contra el `cwd` de la llamada y se pregunta
si cae bajo `<raíz>/main`. Tres consecuencias, todas medidas contra el corpus:

  · **Copiar DESDE `main/` deja de disparar.** `cp main/x /tmp/` tiene su destino fuera; el
    origen no se toca. El filtro por palabra lo marcaba.
  · **El heredoc que cita un comando deja de disparar.** El cuerpo de un heredoc es DATO
    (`cat > fichero <<EOF`) salvo que lo coma un intérprete (`python3 - <<EOF`), y solo
    entonces se lee como código.
  · **Lo que no se puede resolver no se bloquea.** `rm -rf $D/x`, `~/x`, `x*`: 23 casos reales
    en el corpus, todos legítimos. Cuando la asignación está a la vista en el mismo comando
    (`M=$PWD/main; rm -rf $M/x`) la variable se expande y sí se decide; cuando no lo está, sale
    `aviso` con la salida escrita y **nunca `deny`**: fallar cerrado ahí recrea la familia de
    falsos rojos que ya costó 32 incidentes.

    decidir(herramienta, entrada, cwd, raiz) -> Decision(veredicto, motivo, salida)

`veredicto` ∈ {`deny`, `allow`, `aviso`}. Función pura: no lee ficheros (salvo `realpath`, que
necesita el disco para los enlaces simbólicos), no escribe, no sabe qué es un hook. Envolverla
en un `PreToolUse` es la 2.ª entrega; aquí solo se mide si se puede.
"""

import os
import re
from collections import namedtuple

Decision = namedtuple("Decision", "veredicto motivo salida")

ALLOW = Decision("allow", "", "")

SALIDA_MAIN = ("main/ es el clon de solo lectura: haz el cambio en worktrees/NNN-slug/ "
               "y deja lo generado en .runtime/")
SALIDA_GIT = ("el clon main/ solo se adelanta con `git -C main fetch` y "
              "`git -C main merge --ff-only` (ADR-009); commitear va en worktrees/NNN-slug/")
SALIDA_DUDOSA = ("usa una ruta literal (sin $VAR, sin ~ y sin *), dentro de .runtime/ o de "
                 "worktrees/NNN-slug/, y repite el comando")

HERRAMIENTAS_DE_FICHERO = ("edit", "write", "multiedit", "notebookedit")
HERRAMIENTAS_QUE_EJECUTAN = ("bash", "shell", "exec", "exec_command", "run_command")
CAMPOS_DE_RUTA = ("file_path", "notebook_path", "path")

# --- vocabulario de bash -------------------------------------------------------------
# Comandos cuyos argumentos son TODOS destinos: lo que nombran, lo tocan.
TOCA_TODO = {"rm", "rmdir", "unlink", "shred", "truncate", "touch", "mkdir", "tee",
             "patch", "chmod", "chown", "chgrp", "mkfifo"}
# Comandos donde el destino es el ÚLTIMO argumento; los demás son ORIGEN (se leen).
DESTINO_ULTIMO = {"cp", "mv", "rsync", "install", "ln"}
# Borrar de verdad: lo único por lo que merece la pena avisar cuando la ruta no se resuelve.
BORRA = {"rm", "rmdir", "unlink", "shred"}
# Prefijos que no son el comando: se saltan y se vuelve a mirar.
PREFIJOS = {"sudo", "time", "env", "nohup", "command", "stdbuf", "xargs", "exec", "nice",
            "then", "do", "else", "!"}
INTERPRETES = {"python", "python3", "python2", "perl", "ruby", "node", "php"}
CONCHAS = {"bash", "sh", "zsh", "dash", "ksh"}

# Un git que MUTA el repositorio al que apunta.
GIT_MUTADORES = {"commit", "add", "rm", "mv", "clean", "reset", "stash", "apply", "am",
                 "cherry-pick", "revert", "rebase", "gc", "prune", "init", "filter-branch",
                 "update-ref", "reflog-expire", "checkout", "switch", "restore", "merge"}
# Lo que se hace en `main/` todos los días y NO puede bloquearse (medido: log 196,
# rev-parse 181, worktree 115, merge --ff-only 55, pull 46, branch 59, push 34…).
GIT_LECTURAS = {"log", "rev-parse", "status", "diff", "show", "merge-base", "remote",
                "branch", "worktree", "pull", "push", "fetch", "ls-files", "ls-tree",
                "describe", "config", "cat-file", "blame", "shortlog", "for-each-ref",
                "rev-list", "tag", "grep", "help", "version", "count-objects", "notes",
                "check-ignore", "symbolic-ref", "whatchanged", "bisect", "difftool"}

# Verbos de Python/Perl que ESCRIBEN. Sin uno de estos, mencionar `main/` es leer.
#
# Y no basta con que el verbo y la ruta estén en el mismo bloque: eso es otra vez decidir por
# el símbolo. Medido contra el corpus, esa versión producía 6 rechazos falsos —un
# `sys.path.insert(0, "main/visor_presentaciones")` (leer) junto a un `json.dump(…, open(p,
# "w"))` que escribía fuera; una lista de evidencias `["main/visor/actualizar.py"]` dentro del
# JSON que se guardaba en `docs/`; un `(RAIZ / "main/.git/worktrees/…").resolve()` al lado de
# un `mkdir` sobre `.runtime/`—. Por eso la ruta tiene que ser ARGUMENTO del verbo que muta,
# resolviendo antes las variables locales del propio trozo de código.
VERBOS_FUNCION = ("rmtree|unlink|remove|removedirs|rmdir|mkdir|makedirs|rename|replace|"
                  "copy|copy2|copyfile|copytree|move|truncate|touch|chmod|symlink|write")
VERBOS_METODO = ("write_text|write_bytes|writelines|unlink|mkdir|rmdir|touch|chmod|"
                 "symlink_to|hardlink_to|rename|replace|write")
# Verbos cuyo destino es el ÚLTIMO argumento: el primero es el ORIGEN y solo se lee
# (copiar DESDE main/ es legítimo, y es el caso que más falsos daba en el filtro por palabra).
SOLO_ULTIMO = {"copy", "copy2", "copyfile", "copytree", "move", "rename", "replace",
               "symlink", "link"}
CODIGO_MUTADOR = re.compile(r"\b(?:" + VERBOS_FUNCION + r")\s*\(|"
                            r"\.\s*(?:" + VERBOS_METODO + r")\s*\(|"
                            r"open\s*\([^)]*['\"][wax]", re.I)
LLAMADA_FUNCION = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
LLAMADA_METODO = re.compile(r"(?:(['\"])([^'\"\n]{1,200})\1\s*\)|\b([A-Za-z_]\w*))"
                            r"\s*\.\s*(" + VERBOS_METODO + r")\s*\(")
# `p = Path("x")`, `p = "x"`, `p = pathlib.Path('x')`: la ruta que lleva una variable.
ASIGNACION = re.compile(
    r"^[ \t]*([A-Za-z_]\w*)\s*=\s*(?:[\w.]*Path\s*\(\s*)?(['\"])([^'\"\n]{1,200})\2",
    re.M)
LITERAL = re.compile(r"'([^'\n]{1,200})'|\"([^\"\n]{1,200})\"")
APERTURA_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
IRRESOLUBLE = re.compile(r"[$*?`]|^~|\{[^}]*,")
OPERADORES = {"&&", "||", ";", "|", "\n", "(", ")", "{", "}", "&", "|&"}
REDIRECCIONES = {">", ">>", ">|"}


def _deny(categoria, trozo, salida):
    return Decision("deny", f"esto es {categoria}: {str(trozo)[:120]}", salida)


def _aviso(trozo):
    return Decision("aviso", f"ruta que no puedo comprobar: {str(trozo)[:120]}",
                    SALIDA_DUDOSA)


# --- rutas ---------------------------------------------------------------------------
def _normalizar(ruta):
    return str(ruta).replace("\\", "/").rstrip("/") or "/"


def _irresoluble(token):
    return bool(IRRESOLUBLE.search(token))


def _resolver(token, cwd):
    """La ruta absoluta a la que apunta el token, o None si no se deja resolver."""
    if not token or _irresoluble(token):
        return None
    token = _normalizar(token)
    if not os.path.isabs(token):
        if cwd is None:
            return None
        token = os.path.join(_normalizar(cwd), token)
    return os.path.realpath(token)


def _bajo(ruta, main):
    if not ruta:
        return False
    return ruta == main or ruta.startswith(main + "/")


# --- heredocs ------------------------------------------------------------------------
def _separar_heredocs(comando):
    """El texto sin los cuerpos, y los cuerpos con la línea que los abrió.

    El cuerpo de un heredoc es DATO —prosa, markdown, un fichero que se escribe— salvo que
    quien lo lee sea un intérprete. Esa distinción es la que quita el ~40 % de falsos del
    filtro por palabra: los informes de esta misma investigación citan `rm -rf main/…`.
    """
    lineas = comando.split("\n")
    fuera, cuerpos = [], []
    indice = 0
    while indice < len(lineas):
        linea = lineas[indice]
        fuera.append(linea)
        indice += 1
        for _, delimitador in APERTURA_HEREDOC.findall(linea):
            cuerpo = []
            while indice < len(lineas) and lineas[indice].strip() != delimitador:
                cuerpo.append(lineas[indice])
                indice += 1
            indice += 1
            cuerpos.append((linea, "\n".join(cuerpo)))
    return "\n".join(fuera), cuerpos


# --- tokenizador ---------------------------------------------------------------------
def _tokenizar(texto):
    """Palabras y operadores, respetando comillas. Las comillas se quitan, no el contenido."""
    tokens, actual, comilla, tenia = [], "", None, False
    indice, largo = 0, len(texto)
    while indice < largo:
        caracter = texto[indice]
        if comilla:
            if caracter == comilla:
                comilla = None
            elif caracter == "\\" and comilla == '"' and indice + 1 < largo:
                actual += texto[indice + 1]
                indice += 1
            else:
                actual += caracter
            indice += 1
            continue
        if caracter in "'\"":
            comilla, tenia = caracter, True
            indice += 1
            continue
        if caracter == "\\" and indice + 1 < largo:
            if texto[indice + 1] == "\n":       # continuación de línea
                indice += 2
                continue
            actual += texto[indice + 1]
            indice += 2
            continue
        if caracter.isspace():
            if actual or tenia:
                tokens.append(actual)
                actual, tenia = "", False
            if caracter == "\n":
                tokens.append("\n")
            indice += 1
            continue
        operador = None
        for candidato in (">>", "&&", "||", "|&", ">|"):
            if texto.startswith(candidato, indice):
                operador = candidato
                break
        if operador is None and caracter in ";|&()>":
            operador = caracter
        if operador is None and caracter in "{}":
            # `{ cmd; }` de bash lleva espacios; `main/RUNBOOK/{a,b}.md` es UNA ruta
            # (con llaves, o sea irresoluble). Partirla convertia
            # `cp main/x/{a,b}.md $R/` —copiar DESDE main/— en un rechazo: el destino
            # se perdia por el camino y quedaba el origen como ultimo argumento.
            siguiente = texto[indice + 1] if indice + 1 < largo else " "
            if not actual and not tenia and siguiente.isspace():
                operador = caracter
        if operador is None and caracter == "<":
            # `<` y `<<` son ENTRADA: no tocan nada. Se comen con su argumento.
            salto = 2 if texto.startswith("<<", indice) else 1
            if actual or tenia:
                tokens.append(actual)
                actual, tenia = "", False
            tokens.append("<")
            indice += salto
            continue
        if operador is not None:
            if actual or tenia:
                if not (operador in REDIRECCIONES and actual.isdigit()):
                    tokens.append(actual)
                actual, tenia = "", False
            tokens.append(operador)
            indice += len(operador)
            continue
        actual += caracter
        indice += 1
    if actual or tenia:
        tokens.append(actual)
    return tokens


def _segmentar(tokens):
    """Trocitos ejecutables, con la marca de si abrieron o cerraron un subshell."""
    segmentos, actual = [], []
    for token in tokens:
        if token in OPERADORES:
            if actual:
                segmentos.append((actual, token))
                actual = []
            elif token in ("(", ")"):
                segmentos.append(([], token))
            continue
        actual.append(token)
    if actual:
        segmentos.append((actual, ""))
    return segmentos


def _sin_prefijos(palabras):
    indice = 0
    while indice < len(palabras):
        palabra = palabras[indice]
        if "=" in palabra and not palabra.startswith("-") and "/" not in palabra.split("=")[0]:
            indice += 1
            continue
        if palabra in PREFIJOS:
            indice += 1
            continue
        break
    return palabras[indice:]


def _es_bandera(token):
    return token.startswith("-") and token != "-"


# --- código dentro de un intérprete ---------------------------------------------------
def _argumentos(codigo, apertura):
    """El texto entre el paréntesis que abre en `apertura` y el que lo cierra."""
    nivel, indice, largo = 0, apertura, len(codigo)
    comilla = None
    while indice < largo:
        caracter = codigo[indice]
        if comilla:
            if caracter == "\\":
                indice += 2
                continue
            if caracter == comilla:
                comilla = None
        elif caracter in "'\"":
            comilla = caracter
        elif caracter == "(":
            nivel += 1
        elif caracter == ")":
            nivel -= 1
            if nivel == 0:
                return codigo[apertura + 1:indice]
        indice += 1
    return codigo[apertura + 1:apertura + 400]


def _partir_argumentos(texto):
    """Los argumentos de primer nivel, sin romper por las comas de dentro."""
    partes, actual, nivel, comilla = [], "", 0, None
    for caracter in texto:
        if comilla:
            actual += caracter
            if caracter == comilla:
                comilla = None
            continue
        if caracter in "'\"":
            comilla = caracter
        elif caracter in "([{":
            nivel += 1
        elif caracter in ")]}":
            nivel -= 1
        elif caracter == "," and nivel == 0:
            partes.append(actual)
            actual = ""
            continue
        actual += caracter
    if actual.strip():
        partes.append(actual)
    return partes


def _dentro_de_cadena(codigo):
    """Para cada posicion, si cae dentro de un literal de cadena del propio codigo.

    Un heredoc de Python que CITA comandos —los informes de esta investigacion guardan
    los 32 rodeos en una lista de cadenas— trae dentro un `shutil.rmtree('main/…')`
    que nunca se ejecuta. Es la cita en heredoc de siempre, un nivel mas adentro: el
    verbo empieza dentro de una cadena, asi que es texto y no una llamada.
    """
    marcas = bytearray(len(codigo))
    indice, largo, cierre = 0, len(codigo), None
    triples = ('"""', "'''")
    while indice < largo:
        if cierre is None:
            for triple in triples:
                if codigo.startswith(triple, indice):
                    cierre = triple
                    indice += 3
                    break
            else:
                if codigo[indice] in "'\"":
                    cierre = codigo[indice]
                    indice += 1
                else:
                    indice += 1
            continue
        if codigo[indice] == "\\":
            marcas[indice] = 1
            if indice + 1 < largo:
                marcas[indice + 1] = 1
            indice += 2
            continue
        if codigo.startswith(cierre, indice):
            indice += len(cierre)
            cierre = None
            continue
        if len(cierre) == 1 and codigo[indice] == "\n":
            cierre = None            # una cadena simple no cruza el salto de linea
            indice += 1
            continue
        marcas[indice] = 1
        indice += 1
    return marcas


def _variables(codigo):
    """Qué ruta lleva cada variable local del trozo: `p = Path("x")` → {"p": "x"}."""
    mapa = {}
    for encaje in ASIGNACION.finditer(codigo):
        mapa.setdefault(encaje.group(1), encaje.group(3))
    return mapa


def _rutas_de(argumento, variables):
    """Las rutas candidatas de UN argumento: su literal, o lo que lleve su variable."""
    argumento = argumento.strip()
    if not argumento:
        return []
    encaje = LITERAL.search(argumento)
    if encaje:
        return [encaje.group(1) or encaje.group(2) or ""]
    nombre = argumento.split(".")[0].split("[")[0].strip()
    if nombre in variables:
        return [variables[nombre]]
    return []


def _parece_ruta(literal):
    if not literal or " " in literal or "\n" in literal:
        return False
    return "/" in literal or literal.endswith((".py", ".md", ".json", ".txt"))


def _revisar_codigo(codigo, cwd, main):
    """Un `python3 -c` o un heredoc que se come un intérprete.

    La ruta tiene que ser ARGUMENTO del verbo que escribe, no una cadena cualquiera que
    aparezca cerca: mencionar `main/x` como dato (una evidencia en un JSON, un
    `sys.path.insert`) no es tocarlo. Los verbos que copian o mueven solo miran su ÚLTIMO
    argumento, que es el destino.
    """
    if not CODIGO_MUTADOR.search(codigo):
        return None
    variables = _variables(codigo)
    en_cadena = _dentro_de_cadena(codigo)
    sospechosas = []

    for encaje in LLAMADA_FUNCION.finditer(codigo):
        if en_cadena[encaje.start()]:
            continue
        verbo = encaje.group(1)
        base = verbo.lower()
        if base == "open":
            argumentos = _partir_argumentos(_argumentos(codigo, encaje.end() - 1))
            modo = argumentos[1].strip(" '\"") if len(argumentos) > 1 else ""
            if not modo or modo[0] not in "wax":
                continue
            sospechosas += _rutas_de(argumentos[0], variables) if argumentos else []
            continue
        if not re.fullmatch(VERBOS_FUNCION, base):
            continue
        argumentos = _partir_argumentos(_argumentos(codigo, encaje.end() - 1))
        if not argumentos:
            continue
        if base in SOLO_ULTIMO:
            argumentos = argumentos[-1:]
        for argumento in argumentos:
            sospechosas += _rutas_de(argumento, variables)

    for encaje in LLAMADA_METODO.finditer(codigo):
        if en_cadena[encaje.end() - 1]:
            continue
        literal, nombre = encaje.group(2), encaje.group(3)
        if literal:
            sospechosas.append(literal)
        elif nombre in variables:
            sospechosas.append(variables[nombre])

    for literal in sospechosas:
        if not _parece_ruta(literal):
            continue
        if _bajo(_resolver(literal, cwd), main):
            return _deny("ESCRIBIR EN main/ desde código", literal, SALIDA_MAIN)
    return None


# --- git ------------------------------------------------------------------------------
def _revisar_git(palabras, cwd, main):
    directorio, subcomando, resto = None, None, []
    indice = 1
    while indice < len(palabras):
        palabra = palabras[indice]
        if palabra in ("-C", "--git-dir", "--work-tree"):
            directorio = palabras[indice + 1] if indice + 1 < len(palabras) else None
            indice += 2
            continue
        if palabra.startswith("--git-dir=") or palabra.startswith("--work-tree="):
            directorio = palabra.split("=", 1)[1]
            indice += 1
            continue
        if _es_bandera(palabra) or palabra in ("-c",):
            indice += 2 if palabra == "-c" else 1
            continue
        subcomando = palabra
        resto = palabras[indice + 1:]
        break
    if subcomando is None:
        return None

    muta = subcomando in GIT_MUTADORES
    if subcomando == "stash" and resto and resto[0] in ("list", "show"):
        muta = False          # `git stash` a secas esconde el árbol: eso es mutar
    if subcomando == "merge" and "--ff-only" in resto:
        muta = False          # ADR-009: así se adelanta el clon, y son 55 casos reales
    if subcomando in ("checkout", "switch", "restore"):
        # Cambiar de rama NO deshace nada; `checkout -- .` sí. La diferencia es el `--`,
        # el `.` o una ruta suelta: cuatro casos reales de mantenimiento del clon dependen
        # de ello (`cd main && git checkout main && git pull --ff-only`).
        argumentos = [t for t in resto if not _es_bandera(t)]
        muta = "--" in resto or any(t == "." or "/" in t for t in argumentos)
    if not muta:
        return None

    if directorio is None:
        objetivo = _normalizar(cwd) if cwd else None
    else:
        if _irresoluble(directorio):
            return _aviso(f"git -C {directorio} {subcomando}")
        objetivo = _resolver(directorio, cwd)
    if _bajo(objetivo, main):
        return _deny("ESCRIBIR EN main/ con git",
                     " ".join(palabras[:6]), SALIDA_GIT)
    return None


# --- destinos de un comando -----------------------------------------------------------
def _destinos(palabras):
    """Los tokens que este comando va a TOCAR (no los que solo lee)."""
    if not palabras:
        return []
    orden = os.path.basename(palabras[0])
    argumentos = palabras[1:]
    libres = [t for t in argumentos if not _es_bandera(t)]
    banderas = [t for t in argumentos if _es_bandera(t)]
    if orden in TOCA_TODO:
        if orden in ("chmod", "chown", "chgrp") and libres:
            return libres[1:]
        return libres
    if orden in DESTINO_ULTIMO:
        return libres[-1:] if libres else []
    if orden == "sed" and any(b.startswith("-i") or b == "--in-place" for b in banderas):
        return libres[1:] if len(libres) > 1 else []
    if orden == "tar":
        # `tar xf x.tar -C main/` no lleva guion en el modo: hay que mirar tambien el
        # primer argumento suelto, o el rodeo entra por la puerta de al lado.
        junto = " ".join(banderas)
        if libres and not libres[0].startswith("-") and "." not in libres[0][:1]:
            junto += " " + libres[0]
        if "x" in junto.replace("--", "") or "--extract" in banderas:
            for indice, token in enumerate(argumentos):
                if token == "-C" and indice + 1 < len(argumentos):
                    return [argumentos[indice + 1]]
        return []
    if orden == "unzip":
        for indice, token in enumerate(argumentos):
            if token == "-d" and indice + 1 < len(argumentos):
                return [argumentos[indice + 1]]
        return []
    if orden == "find":
        if "-delete" in argumentos or "-exec" in argumentos or "-execdir" in argumentos:
            return libres[:1]
        return []
    if orden == "dd":
        return [t.split("=", 1)[1] for t in argumentos if t.startswith("of=")]
    if orden in ("mkfifo", "install"):
        return libres[-1:] if libres else []
    return []


def _borra(palabras):
    if not palabras:
        return False
    orden = os.path.basename(palabras[0])
    if orden in BORRA:
        return True
    if orden == "rsync" and any(b.startswith("--delete") for b in palabras):
        return True
    if orden == "find" and "-delete" in palabras:
        return True
    return False


# --- el cuerpo de la decisión ----------------------------------------------------------
ASIGNACION_SHELL = re.compile(r"^([A-Za-z_]\w*)=(.*)$", re.S)


def _expandir(token, variables):
    """Sustituye `$VAR` y `${VAR}` por lo que ya se vio asignar en este mismo comando.

    `M=$PWD/main; rm -rf $M/visor/.runtime` es el rodeo 17 de verificacion-02 y hay 41
    `$VAR/main` reales en los rollouts. Sin esto sale `aviso` (que es lo correcto para
    una variable que no se puede saber), pero cuando la asignacion esta A LA VISTA en el
    propio comando la ruta si se conoce, y entonces avisar en vez de parar seria regalar
    justo el rodeo mas facil.
    """
    if "$" not in token:
        return token
    def reemplazo(encaje):
        nombre = encaje.group(1) or encaje.group(2)
        return variables.get(nombre, encaje.group(0))
    return re.sub(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)", reemplazo, token)


def _seguir_enlaces(ruta, enlaces):
    """Deshace los symlinks que el propio comando acaba de crear.

    `ln -sf main/visor enlace && rm -rf enlace/.runtime` es el rodeo del symlink de
    verificacion-02 §2. `realpath` no lo deshace porque el enlace todavia no existe en
    disco: las dos ordenes viajan en la MISMA llamada, y el guardian las ve antes de que
    ninguna se ejecute. Asi que el enlace se sigue aqui, por lo que dice el comando.
    """
    for _ in range(4):
        for nombre, objetivo in enlaces.items():
            if ruta == nombre:
                ruta = objetivo
                break
            if ruta.startswith(nombre + "/"):
                ruta = objetivo + ruta[len(nombre):]
                break
        else:
            return ruta
    return ruta


def _revisar_bash(comando, cwd, main, profundidad=0):
    fuera, cuerpos = _separar_heredocs(comando)
    segmentos = _segmentar(_tokenizar(fuera))

    cwd_actual, pila, aviso = _normalizar(cwd) if cwd else None, [], None
    variables, enlaces = {}, {}
    for palabras, cierre in segmentos:
        if cierre == "(":
            pila.append(cwd_actual)
        if not palabras:
            if cierre == ")" and pila:
                cwd_actual = pila.pop()
            continue

        # Redirecciones: el destino se toca aunque el comando solo escriba en pantalla.
        destinos, limpias, indice = [], [], 0
        while indice < len(palabras):
            token = palabras[indice]
            if token in REDIRECCIONES:
                if indice + 1 < len(palabras):
                    destinos.append(palabras[indice + 1])
                indice += 2
                continue
            if token == "<":
                indice += 2
                continue
            limpias.append(token)
            indice += 1
        for palabra in limpias:
            encaje = ASIGNACION_SHELL.match(palabra)
            if encaje and not palabra.startswith("-"):
                valor = _expandir(encaje.group(2), variables)
                if cwd_actual and "$PWD" not in valor:
                    valor = valor.replace("$PWD", cwd_actual)
                variables[encaje.group(1)] = valor.replace("$PWD", cwd_actual or "$PWD")
            else:
                break
        destinos = [_expandir(d, variables) for d in destinos]
        palabras = _sin_prefijos(limpias)
        if not palabras:
            for destino in destinos:
                if _bajo(_resolver(destino, cwd_actual), main):
                    return _deny("ESCRIBIR EN main/", destino, SALIDA_MAIN)
            continue

        orden = os.path.basename(palabras[0])

        if orden == "cd":
            argumentos = [t for t in palabras[1:] if not _es_bandera(t)]
            if not argumentos or argumentos[0] == "-":
                continue
            cwd_actual = _resolver(_expandir(argumentos[0], variables), cwd_actual)
            continue

        if orden == "ln":
            libres = [t for t in palabras[1:] if not _es_bandera(t)]
            if len(libres) >= 2:
                objetivo = _resolver(_expandir(libres[-2], variables), cwd_actual)
                nombre = _resolver(_expandir(libres[-1], variables), cwd_actual)
                if objetivo and nombre:
                    enlaces[nombre] = objetivo

        if orden == "git":
            veredicto = _revisar_git(palabras, cwd_actual, main)
            if veredicto is not None and veredicto.veredicto == "deny":
                return veredicto
            if veredicto is not None and aviso is None:
                aviso = veredicto

        if orden in INTERPRETES or orden in CONCHAS:
            for indice, token in enumerate(palabras):
                if token in ("-c", "-e") and indice + 1 < len(palabras):
                    codigo = palabras[indice + 1]
                    if orden in CONCHAS:
                        if profundidad < 2:
                            veredicto = _revisar_bash(codigo, cwd_actual, main,
                                                      profundidad + 1)
                            if veredicto.veredicto == "deny":
                                return veredicto
                            if veredicto.veredicto == "aviso" and aviso is None:
                                aviso = veredicto
                    else:
                        veredicto = _revisar_codigo(codigo, cwd_actual, main)
                        if veredicto is not None:
                            return veredicto

        destinos += [_expandir(d, variables) for d in _destinos(palabras)]
        borra = _borra(palabras)
        for destino in destinos:
            if _irresoluble(destino):
                if borra and aviso is None:
                    aviso = _aviso(destino)
                continue
            ruta = _resolver(destino, cwd_actual)
            if ruta is None:
                continue
            ruta = _seguir_enlaces(ruta, enlaces)
            if _bajo(ruta, main):
                return _deny("ESCRIBIR EN main/", destino, SALIDA_MAIN)

        if cierre == ")" and pila:
            cwd_actual = pila.pop()

    # Los cuerpos de heredoc: solo los que se come un intérprete son código.
    for apertura, cuerpo in cuerpos:
        palabras = _sin_prefijos(_tokenizar(apertura))
        if not palabras:
            continue
        orden = os.path.basename(palabras[0])
        if orden in INTERPRETES:
            veredicto = _revisar_codigo(cuerpo, cwd_actual, main)
            if veredicto is not None:
                return veredicto
        elif orden in CONCHAS and profundidad < 2:
            veredicto = _revisar_bash(cuerpo, cwd_actual, main, profundidad + 1)
            if veredicto.veredicto == "deny":
                return veredicto
            if veredicto.veredicto == "aviso" and aviso is None:
                aviso = veredicto

    return aviso or ALLOW


def _entrada_de_fichero(entrada):
    if isinstance(entrada, dict):
        for campo in CAMPOS_DE_RUTA:
            if entrada.get(campo):
                return str(entrada[campo])
        return None
    return str(entrada) if entrada else None


def _entrada_de_bash(entrada):
    if isinstance(entrada, dict):
        for campo in ("command", "cmd", "comando"):
            if entrada.get(campo):
                return str(entrada[campo])
        return None
    return str(entrada) if entrada else None


def decidir(herramienta, entrada, cwd, raiz):
    """El veredicto sobre UNA llamada: deny, allow o aviso, siempre con salida escrita."""
    nombre = (herramienta or "").lower()
    raiz = _normalizar(os.path.realpath(_normalizar(raiz))) if raiz else None
    main = raiz + "/main" if raiz else None
    if not main:
        return ALLOW

    if nombre in HERRAMIENTAS_DE_FICHERO:
        ruta = _entrada_de_fichero(entrada)
        if not ruta:
            return ALLOW
        if _irresoluble(ruta):
            return _aviso(ruta)
        if _bajo(_resolver(ruta, cwd), main):
            return _deny("ESCRIBIR EN main/", ruta, SALIDA_MAIN)
        return ALLOW

    if nombre not in HERRAMIENTAS_QUE_EJECUTAN:
        return ALLOW
    comando = _entrada_de_bash(entrada)
    if not comando:
        return ALLOW
    return _revisar_bash(comando, cwd, main)
