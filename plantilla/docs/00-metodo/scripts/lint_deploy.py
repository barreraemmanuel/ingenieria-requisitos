#!/usr/bin/env python3
"""Gate de pre-despliegue: no se despliega lo que no está DEFINIDO.

Uso: python3 docs/00-metodo/scripts/lint_deploy.py   (desde la raíz del workspace)
Salida: OK/WARN/FAIL por comprobación. Exit 0 si no hay FAIL; exit 1 si hay alguno.
Se ejecuta: paso 1 del runbook de deploy (docs/00-metodo/runbooks/deploy.md).

QUÉ COMPRUEBA Y QUÉ NO. Este gate NO sabe cómo se despliega tu proyecto, y no debe saberlo:
puede ser una web con Docker, una app de móvil, un mod de un juego o un proceso que corre en
un portátil. Antes exigía `main/deploy.py` y un `pg_dump` en un docker-compose — o sea, la
receta de UNA clase de proyecto aplicada a todos, y para los demás era un rojo imposible.

Lo que comprueba es que las cinco cosas que sí son universales estén ESCRITAS y decididas por
el usuario, en `docs/conocimiento/plano-deploy.md` (entrevista del rol DEPLOY, `roles.md`; si
nunca ha desplegado nada, `runbooks/primer-despliegue.md`): dónde va, cómo se sube, cómo se
deshace, qué datos hay que salvar y dónde se mira si falla.

Sin dependencias: solo stdlib. El disco es la verdad; este script solo la comprueba.
"""
import os
import re
import subprocess
import sys
import time
from fnmatch import fnmatchcase
from pathlib import Path

import repo_config
import workspace_paths

for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parents[3]
fallos, avisos = [], []

# Las cinco decisiones que tiene TODO despliegue, se despliegue como se despliegue.
CASILLAS = {
    "etapa": "dónde va a correr: local | lan | internet",
    "camino": "el comando o los pasos exactos con los que sube (nunca improvisados)",
    "vuelta_atras": "qué se deshace y cómo, si sale mal",
    "datos": "qué se copia y adónde antes de tocar nada — o SIN DATOS si esta app no guarda",
    "vigilancia": "dónde se mira si falla: registro, panel o comando",
}
# Un valor que sigue siendo plantilla no es una decisión: hueco `<...>`, menú sin elegir
# (`local | lan | internet`), guion o vacío.
VACIO = {"", "—", "-", "…", "..."}

ARTEFACTOS_DIR = {".claude", ".cursor", "planning"}
ARTEFACTOS_FICHERO = ["CLAUDE.md", "AGENTS.md", ".cursorrules", "PLAN.md", "plan.md",
                      "TODO.md", "especificacion*.md", "tareas*.md", "hallazgos*.md"]
NO_ESCANEAR = {".git", ".github", "tests"}
# En la RAÍZ del repo de código, el AGENTS.md y sus puentes de una línea no son basura de
# agente: el método OBLIGA a crearlos (runbooks/planificacion.md regla 6 +
# plantillas/agents-repo-codigo.md) porque llevan los comandos literales de test y de arranque
# sin los cuales "suite en verde" y "lanzar instancia" no los puede ejecutar un agente fresco.
# Exigir su borrado era un gate imposible, y un rojo imposible solo enseña a desplegar con el
# gate en rojo — mismo defecto que ADR-011 arregló en la comprobación 5 de este script. La
# excepción es SOLO la raíz: anidados (main/loquesea/AGENTS.md) siguen siendo basura.
PERMITIDOS_EN_RAIZ = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}

DIAS_AUDITORIA = 60


def ok(msg):
    print(f"  OK   {msg}")


def warn(msg):
    avisos.append(msg)
    print(f"  WARN {msg}")


def fail(msg):
    fallos.append(msg)
    print(f"  FAIL {msg}")


def git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=False)
    except OSError:
        return 1, ""
    return p.returncode, (p.stdout + p.stderr).strip()


def casillas_del_plano(texto):
    """{clave: valor} leídos de la tabla del plano. Solo cuenta lo que es una DECISIÓN."""
    valores = {}
    for clave, valor in re.findall(r"^\|\s*`?(\w+)`?\s*\|\s*(.*?)\s*\|\s*$", texto, flags=re.M):
        limpio = valor.strip().strip("`").strip()
        if clave not in CASILLAS:
            continue
        if limpio in VACIO or "<" in limpio or "|" in limpio:
            continue                      # hueco sin rellenar o menú sin elegir
        valores[clave] = limpio
    return valores


def ruta_para_bash(ruta):
    """La ruta tal y como la entiende el bash de Git for Windows: con barras normales.

    Bug 039: `str(ruta)` en Windows lleva barras invertidas y bash se las come
    (`D:\\Proyectos\\x` → `D:Proyectosx`, exit 127). `D:/Proyectos/x` la entienden bash y
    Windows por igual.
    """
    return str(ruta).replace("\\", "/")


def bash_del_anfitrion():
    """El bash que entiende las rutas de ESTE Windows: el de Git for Windows, nunca el de WSL.

    Bug 039: en un Windows con WSL, `which("bash")` devuelve `System32\\bash.exe`, que es el
    lanzador de WSL y vive en otro sistema de ficheros. Se descarta y se busca el de Git
    junto al `git.exe` que sí se encontró; si no está, se dice en claro.
    """
    candidato = workspace_paths.buscar_bash()
    if candidato and "system32" not in candidato.lower():
        return candidato
    git = workspace_paths.which_sin_cwd("git")  # nunca el cwd: un git.exe en el repo ganaría
    if git:
        raiz = Path(git).resolve().parent.parent
        for bash in (raiz / "bin" / "bash.exe", raiz / "usr" / "bin" / "bash.exe"):
            if bash.is_file():
                return str(bash)
    return None


def ejecutar_control(nombre, ruta, cwd):
    """Ejecuta una puerta del repo y guarda el output completo fuera de git."""
    if not ruta.is_file():
        fail(f"falta {ruta.relative_to(RAIZ)}: no se puede ejecutar {nombre}")
        return
    logs = RAIZ / ".runtime" / "pre-deploy"
    logs.mkdir(parents=True, exist_ok=True)
    destino = logs / f"{ruta.name}.log"
    orden = [str(ruta)]
    if os.name == "nt":
        # Windows no entiende el shebang: los scripts de gate corren vía bash
        # (viene con Git for Windows) o el gate lo dice en claro.
        try:
            with open(ruta, "rb") as stream:
                lleva_shebang = stream.read(2) == b"#!"
        except OSError:
            lleva_shebang = False
        if lleva_shebang:
            bash = bash_del_anfitrion()
            if not bash:
                fail(f"en Windows {nombre} necesita el bash de Git for Windows (el de WSL no "
                     f"entiende las rutas de este equipo): instálalo o ponlo en el PATH")
                return
            orden = [bash, ruta_para_bash(ruta)]
    try:
        resultado = subprocess.run(
            orden, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
    except OSError as exc:
        fail(f"no pude ejecutar {nombre}: {exc}")
        return
    destino.write_text(resultado.stdout + resultado.stderr, encoding="utf-8")
    salida = destino.relative_to(RAIZ)
    if resultado.returncode:
        fail(f"{nombre} terminó con código {resultado.returncode}; output: {salida}")
    else:
        ok(f"{nombre}: verde (output: {salida})")


print("== Gate de pre-despliegue ==")

# --- 1. Esto se corre en el workspace completo ---
try:
    main_dir, principal_configurada = repo_config.repo_code(RAIZ)
except repo_config.RepoConfigError as exc:
    fail(str(exc))
    main_dir, principal_configurada = RAIZ / ".ruta-local-invalida", "main"
if not main_dir.is_dir():
    fail("main/ no existe: este gate se corre en el workspace completo (meta-repo con "
         "main/ dentro), no en el repo de código suelto")

# --- 2. El despliegue está DEFINIDO por el usuario ---
plano = RAIZ / "docs/conocimiento/plano-deploy.md"
casillas = {}
if not plano.is_file():
    fail("docs/conocimiento/plano-deploy.md no existe: nadie ha decidido todavía cómo se "
         "despliega esto. Si el usuario ya despliega a mano, entrevístalo (roles.md, rol "
         "DEPLOY); si no ha desplegado nunca, sigue docs/00-metodo/runbooks/primer-despliegue.md")
else:
    casillas = casillas_del_plano(plano.read_text(encoding="utf-8"))
    faltan = [f"`{c}` ({CASILLAS[c]})" for c in CASILLAS if c not in casillas]
    if faltan:
        fail(f"plano-deploy.md sin decidir: {'; '.join(faltan)} — esas casillas las llena la "
             f"entrevista de arranque del rol DEPLOY (roles.md), preguntándole al usuario una "
             f"por una; si no ha desplegado nunca nada, runbooks/primer-despliegue.md")
    else:
        ok(f"despliegue definido: etapa {casillas['etapa']} · camino «{casillas['camino'][:40]}»")
        if casillas["datos"].upper().startswith("SIN DATOS"):
            ok("declarado SIN DATOS que salvar (no hay copia que verificar)")
        else:
            ok(f"datos a salvar declarados: {casillas['datos'][:60]}")

# --- 3. Se despliega lo que está en la rama principal, y nada más ---
if main_dir.is_dir():
    principal = principal_configurada
    codigo, sucio = git(main_dir, "status", "--porcelain")
    if codigo != 0:
        fail(f"main/ no es un repositorio git legible ({sucio})")
    else:
        if sucio:
            fail(f"main/ tiene {len(sucio.splitlines())} fichero(s) sin commitear: se "
                 f"desplegaría algo que no está en ninguna rama y que nadie ha revisado")
        actual = git(main_dir, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
        if actual != principal:
            fail(f"main/ está en la rama '{actual}' y no en '{principal}': no se despliega "
                 f"una rama sin fusionar (runbooks/deploy.md, paso 2)")
        elif not sucio:
            ok(f"main/ limpio y en {principal}")
        if git(main_dir, "remote")[1].strip():
            pendientes = git(main_dir, "rev-list", "--count",
                             f"origin/{principal}..{principal}")[1].strip()
            if pendientes.isdigit() and int(pendientes) > 0:
                warn(f"{pendientes} commit(s) locales sin empujar: lo que despliegues no "
                     f"estará en el remoto, así que nadie más podrá reproducirlo")

    # --- 4. El repo de código, limpio de artefactos de agentes ---
    def es_artefacto(entrada):
        if entrada.is_dir():
            return entrada.name in ARTEFACTOS_DIR
        return any(fnmatchcase(entrada.name, pat) for pat in ARTEFACTOS_FICHERO)

    sucios = []
    for entrada in sorted(main_dir.iterdir()):
        if entrada.name in NO_ESCANEAR:
            continue
        if entrada.is_file() and entrada.name in PERMITIDOS_EN_RAIZ:
            continue
        if es_artefacto(entrada):
            sucios.append(f"main/{entrada.name}{'/' if entrada.is_dir() else ''}")
        elif entrada.is_dir():
            sucios += [f"main/{entrada.name}/{e.name}{'/' if e.is_dir() else ''}"
                       for e in sorted(entrada.iterdir()) if es_artefacto(e)]
    if sucios:
        fail(f"repo de código SUCIO de artefactos de agentes (viven en el meta-repo, "
             f"jamás en main/): {sucios}")
    else:
        ok("repo de código limpio de artefactos de agentes")

# --- 5. Suite completa y seguridad del commit exacto que se va a desplegar ---
# No se queman minutos si una puerta estructural anterior ya cerró el gate. Cuando la base
# está bien, no basta con que alguien escribiera "estaba verde": se ejecutan los comandos del
# propio repo sobre main/ y el output queda en .runtime/.
if main_dir.is_dir() and not fallos:
    suite = main_dir / "scripts" / "ci" / "full-suite"
    seguridad = main_dir / "scripts" / "ci" / "security"
    if not suite.is_file():
        fail("falta main/scripts/ci/full-suite: no hay suite completa ejecutable antes de deploy")
    if not seguridad.is_file():
        fail("falta main/scripts/ci/security: no hay control de seguridad ejecutable antes de deploy")
    lint_ci = RAIZ / "docs" / "00-metodo" / "scripts" / "lint_ci.py"
    if not lint_ci.is_file():
        fail("falta docs/00-metodo/scripts/lint_ci.py: no puedo validar el contrato CI")
    elif suite.is_file() and seguridad.is_file():
        contrato = subprocess.run(
            [sys.executable, str(lint_ci), "--repo", str(main_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if contrato.returncode:
            detalle = " · ".join(
                linea.strip() for linea in contrato.stdout.splitlines() if "FAIL" in linea
            )
            fail(f"contrato CI incompleto: {detalle or 'ejecuta lint_ci.py para ver el detalle'}")
        else:
            ejecutar_control("suite completa", suite, main_dir)
            ejecutar_control("seguridad", seguridad, main_dir)

# --- 6. Auditoría de seguridad: obligatoria solo al salir a internet ---
# runbooks/deploy.md, precondición 4: se exige antes de la PRIMERA salida a internet. En
# local o en la red de la oficina no hay superficie que auditar, y un rojo imposible ahí
# solo enseña a desplegar con el gate en rojo.
expuesto = casillas.get("etapa", "").lower().startswith(("internet", "2", "vps", "publico",
                                                         "público"))
archivo = RAIZ / "docs/05-trabajo/archivo"
unidades = [p for p in sorted(archivo.iterdir())
            if p.is_dir() and "auditoria" in p.name and "seguridad" in p.name] \
    if archivo.is_dir() else []
con_informe = [u for u in unidades if any(u.rglob("*.md"))]
if not con_informe:
    mensaje = ("sin auditoría de seguridad archivada (docs/05-trabajo/archivo/"
               "*auditoria*seguridad*/ con informe): correr el playbook "
               "docs/00-metodo/auditoria-seguridad.md como unidad tipo auditoria")
    if expuesto:
        fail(f"{mensaje} — es innegociable antes de salir a internet")
    else:
        warn(f"{mensaje}. En esta etapa no bloquea, pero sí el día que salga a internet")
else:
    ultima = con_informe[-1]
    r = subprocess.run(["git", "log", "-1", "--format=%ct", "--",
                        str(ultima.relative_to(RAIZ))],
                       cwd=RAIZ, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ts = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    if ts is None:
        ok(f"auditoría de seguridad archivada: {ultima.name} (sin commit aún)")
    elif (dias := int((time.time() - ts) / 86400)) > DIAS_AUDITORIA:
        warn(f"auditoría de seguridad {ultima.name} tiene {dias} días (> {DIAS_AUDITORIA}): "
             "el código ha seguido cambiando — considerar re-auditar antes de desplegar")
    else:
        ok(f"auditoría de seguridad archivada: {ultima.name} ({dias} días)")

print(f"\n{len(fallos)} FAIL · {len(avisos)} WARN")
print("GATE ABIERTO: se puede seguir con el runbook de deploy." if not fallos else
      "GATE CERRADO: NO se despliega hasta dejar esto en verde (sin verde no hay deploy).")
sys.exit(1 if fallos else 0)
