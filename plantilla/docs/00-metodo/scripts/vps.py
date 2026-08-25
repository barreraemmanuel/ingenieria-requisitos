#!/usr/bin/env python3
"""vps.py — la receta de despliegue de serie, conducida desde TU ordenador.

Uso: python3 docs/00-metodo/scripts/vps.py <orden> [--dry-run]

    env                  escribe .private/produccion.env preguntándote lo que solo sabes tú
    cloudflare           deja el dominio apuntando al VPS y protegido (y dice qué clicar)
    servidor preparar    instala Docker y cierra el cortafuegos del VPS
    desplegar            sube la aplicación y comprueba que la que responde es la que mandaste
    backup               lanza la copia de la base de datos (y prueba a restaurarla)
    comprobar            informe de una pantalla: salud, contenedores, disco, copias, errores

Se ejecuta: paso a paso, desde `docs/00-metodo/runbooks/deploy-vps-docker.md`. Cada orden
dice cuál es la siguiente; cada rechazo dice qué fichero crear o qué paso te desbloquea.

POR QUÉ ES UN SCRIPT LOCAL Y NO UNA CI: el despliegue lo conduce una persona desde su
máquina, con sus llaves en `.private/`, mirando lo que pasa. No hay ninguna CI remota
por medio (ADR-032); si algún día hiciera falta, sería otra unidad.

Solo stdlib. Todo lo que sale de esta máquina —ssh, scp, docker, la API de Cloudflare—
pasa por `ejecutar()` y `http()`, que son las dos únicas puertas al mundo: así la suite las
sustituye por dobles y ninguna prueba toca red, SSH ni Docker.
Los secretos se leen SOLO de `.private/` y ninguno se imprime jamás.
"""
import argparse
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

for _salida in (sys.stdout, sys.stderr):
    if hasattr(_salida, "reconfigure"):
        _salida.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parents[3]
PLANTILLAS = Path(__file__).resolve().parents[1] / "plantillas" / "vps"
RUNBOOK = "docs/00-metodo/runbooks/deploy-vps-docker.md"
YO = "python3 docs/00-metodo/scripts/vps.py"
API = "https://api.cloudflare.com/client/v4"

# Cuánto se espera a que la aplicación conteste después de arrancarla.
INTENTOS = 30
PAUSA = 5

# Los que inventa el script: nadie los teclea, nadie los ve, no salen por pantalla.
GENERADOS = ("POSTGRES_PASSWORD", "SECRET_KEY", "BUGSINK_SECRET_KEY")
# Los que se rellenan más adelante, cuando Bugsink y Better Stack existan.
APLAZADOS = {"SENTRY_DSN": "paso 10", "HEARTBEAT_URL": "paso 11"}


class Rechazo(Exception):
    """Un no con salida escrita: el mensaje dice qué falta y `salida` cómo desbloquearlo."""

    def __init__(self, mensaje, salida):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.salida = salida


# --------------------------------------------------------------------------- #
#  Las dos únicas puertas al mundo (los tests las sustituyen)                    #
# --------------------------------------------------------------------------- #

def ejecutar(cmd, entrada=None):
    """(codigo, salida) de un comando externo. Nunca lanza: un fallo es un dato."""
    try:
        p = subprocess.run(list(cmd), input=entrada, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=False)
    except OSError as exc:
        return 1, str(exc)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def http(metodo, url, cuerpo=None, cabeceras=None):
    """(estado, texto) de una petición HTTP. Un error de red también es una respuesta."""
    datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
    peticion = urllib.request.Request(url, data=datos, method=metodo,
                                      headers=cabeceras or {})
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            return respuesta.status, respuesta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)


def leer_respuesta(prompt):
    """Lo que teclea el usuario. Aparte para que la suite pueda contestar por él."""
    return input(prompt)


# --------------------------------------------------------------------------- #
#  Salida: OK/WARN/FAIL, y ni un secreto por pantalla                           #
# --------------------------------------------------------------------------- #

SECRETOS = set()


def enmascarar(texto):
    """Todo valor secreto conocido, tapado. Se aplica al EMBUDO, no en cada print:
    da igual si el texto lo escribió este script o lo devolvió la API de Cloudflare."""
    for secreto in sorted(SECRETOS, key=len, reverse=True):
        if secreto:
            texto = texto.replace(secreto, "«oculto»")
    return texto


class _Embudo:
    def __init__(self, flujo):
        self._flujo = flujo

    def write(self, texto):
        return self._flujo.write(enmascarar(texto))

    def __getattr__(self, nombre):
        return getattr(self._flujo, nombre)


def decir(msg=""):
    print(msg)


def ok(msg):
    print(f"  OK   {msg}")


def warn(msg):
    print(f"  WARN {msg}")


def fail(msg, salida=None):
    print(f"  FAIL {msg}")
    if salida is not None:
        print(f"       SALIDA: {salida}")


def recordar_secreto(valor):
    if valor and len(valor) >= 8:
        SECRETOS.add(valor)


# --------------------------------------------------------------------------- #
#  `.private/`: lo único que este script lee de secretos                        #
# --------------------------------------------------------------------------- #

def privado():
    return RAIZ / ".private"


def ruta_env():
    return privado() / "produccion.env"


def ruta_token():
    return privado() / "cloudflare.token"


def pares_del_ejemplo():
    """[(clave, explicación de una línea)] tal y como están en plantillas/vps/env.ejemplo."""
    ejemplo = PLANTILLAS / "env.ejemplo"
    if not ejemplo.is_file():
        raise Rechazo(f"falta la plantilla {ejemplo}",
                      salida="la trae el método: vuelve a instalarlo con "
                             "`python3 docs/00-metodo/scripts/herramienta.py actualizar`")
    pares, comentario = [], ""
    for linea in ejemplo.read_text(encoding="utf-8").splitlines():
        if linea.startswith("#"):
            comentario = linea.lstrip("# ").strip()
            continue
        casa = re.match(r"^([A-Z][A-Z0-9_]+)=(.*)$", linea)
        if casa:
            pares.append((casa.group(1), comentario))
        comentario = ""
    return pares


def leer_env():
    """Los valores de `.private/produccion.env`. Parser propio: CLAVE=valor, sin dependencias."""
    ruta = ruta_env()
    if not ruta.is_file():
        raise Rechazo(
            "no hay configuración de producción: falta `.private/produccion.env`",
            salida=f"{YO} env  (paso 6 de {RUNBOOK})")
    valores = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valores[clave.strip()] = valor.strip()
    for clave, valor in valores.items():
        if clave in GENERADOS or clave in ("BUGSINK_SUPERUSER", "SENTRY_DSN", "HEARTBEAT_URL"):
            recordar_secreto(valor)
            if ":" in valor:
                recordar_secreto(valor.split(":", 1)[1])
    return valores


def exigir(valores, clave, paso):
    valor = valores.get(clave, "")
    if not valor:
        raise Rechazo(f"`{clave}` está vacía en `.private/produccion.env`",
                      salida=f"{YO} env  ({paso} de {RUNBOOK})")
    return valor


def leer_token():
    ruta = ruta_token()
    if not ruta.is_file():
        raise Rechazo(
            "no hay token de Cloudflare: falta `.private/cloudflare.token`",
            salida=f"créalo con el token del paso 3 de {RUNBOOK} "
                   "(permisos Zone:Read + DNS:Edit + Zone Settings:Edit)")
    token = ruta.read_text(encoding="utf-8").strip()
    if not token:
        raise Rechazo("`.private/cloudflare.token` está vacío",
                      salida=f"pega dentro el token del paso 3 de {RUNBOOK}")
    recordar_secreto(token)
    return token


# --------------------------------------------------------------------------- #
#  env                                                                          #
# --------------------------------------------------------------------------- #

def escribir_env(valores):
    destino = ruta_env()
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = ("# Configuración de producción. La escribió `vps.py env`.\n"
             "# JAMÁS se copia a docs ni a git: vive aquí y solo aquí.\n")
    texto += "".join(f"{clave}={valor}\n" for clave, valor in valores.items())
    descriptor = os.open(str(destino), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as fichero:
        fichero.write(texto)
    try:
        os.chmod(str(destino), 0o600)     # por si el fichero ya existía con otro modo
    except OSError:
        pass


def orden_env(args):
    if args.comprobar:
        return comprobar_env()

    decir("Voy a preguntarte los datos de tu despliegue. Las contraseñas y las claves las")
    decir("invento yo: no las teclees, no las verás y no salen por pantalla nunca.")
    decir("")
    valores = {}
    for clave, explicacion in pares_del_ejemplo():
        if clave in GENERADOS:
            valores[clave] = secrets.token_urlsafe(48)
            recordar_secreto(valores[clave])
            decir(f"{clave} · {explicacion}")
            decir("  → inventada (no se imprime)")
            continue
        if clave == "BUGSINK_SUPERUSER":
            correo = leer_respuesta(f"{clave} · {explicacion}\n  correo> ").strip()
            clave_super = secrets.token_urlsafe(18)
            recordar_secreto(clave_super)
            valores[clave] = f"{correo or 'yo@ejemplo.com'}:{clave_super}"
            recordar_secreto(valores[clave])
            decir("  → contraseña inventada (la leerás del fichero en el paso 10)")
            continue
        if clave in APLAZADOS:
            decir(f"{clave} · {explicacion}")
            decir(f"  → se rellena en el {APLAZADOS[clave]}; lo dejo vacío")
            valores[clave] = leer_respuesta(f"  {clave} (enter para dejarlo vacío)> ").strip()
            continue
        valores[clave] = leer_respuesta(f"{clave} · {explicacion}\n  > ").strip()

    escribir_env(valores)
    decir("")
    ok(f"escrito `.private/produccion.env` con {len(valores)} valores "
       f"({len(GENERADOS) + 1} secretos inventados), en modo 0600")
    decir(f"Siguiente: paso 7 de {RUNBOOK} → {YO} servidor preparar")
    return 0


def comprobar_env():
    valores = leer_env()
    faltan, aplazados = [], []
    for clave, _ in pares_del_ejemplo():
        valor = valores.get(clave, "")
        if valor:
            continue
        if clave in APLAZADOS:
            aplazados.append(clave)
        else:
            faltan.append(clave)
    if faltan:
        raise Rechazo(
            "a `.private/produccion.env` le falta: " + ", ".join(faltan),
            salida=f"{YO} env  (vuelve a contestar; paso 6 de {RUNBOOK})")
    for clave in aplazados:
        warn(f"`{clave}` todavía vacía: se rellena en el {APLAZADOS[clave]} de {RUNBOOK}")
    ok(f"`.private/produccion.env` completa ({len(valores)} valores)")
    return 0


# --------------------------------------------------------------------------- #
#  cloudflare                                                                   #
# --------------------------------------------------------------------------- #

AJUSTES = (
    ("ssl", "strict", "TLS Full (strict): Cloudflare exige certificado válido en tu VPS"),
    ("always_use_https", "on", "todo el que llegue por http se va a https"),
    ("min_tls_version", "1.2", "nada de TLS viejo"),
    ("security_level", "medium", "el filtro de reputación de Cloudflare, en medio"),
)

CLICS = [
    "WAF gestionado: Security → WAF → Managed rules → activa el «Free Managed Ruleset»",
    "Bot Fight Mode: Security → Bots → activa «Bot Fight Mode»",
    "regla de rate limiting (el plan Free trae 1): Security → WAF → Rate limiting rules → "
    "«Create rule», 100 peticiones / 10 s por IP sobre `/`, acción «Block»",
]


def cloudflare_api(token, metodo, ruta, cuerpo=None):
    cabeceras = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    texto_cuerpo = json.dumps(cuerpo) if cuerpo is not None else None
    estado, texto = http(metodo, API + ruta, texto_cuerpo, cabeceras)
    try:
        datos = json.loads(texto or "{}")
    except ValueError:
        raise Rechazo(f"Cloudflare contestó algo que no es JSON a {metodo} {ruta} "
                      f"(estado {estado})",
                      salida=f"reintenta; si sigue, mira el paso 8 de {RUNBOOK}")
    if not datos.get("success"):
        motivos = "; ".join(str(e.get("message", e)) for e in datos.get("errors") or []) \
            or f"estado {estado}"
        raise Rechazo(f"Cloudflare rechazó {metodo} {ruta}: {motivos}",
                      salida=f"revisa los permisos del token (Zone:Read + DNS:Edit + "
                             f"Zone Settings:Edit) en el paso 3 de {RUNBOOK}")
    return datos.get("result")


def orden_cloudflare(args):
    valores = leer_env()
    dominio = exigir(valores, "DOMINIO", "paso 6")
    ip = exigir(valores, "VPS_IP", "paso 5")
    token = leer_token()
    nombres = [dominio, f"errores.{dominio}"]

    if args.dry_run:
        decir(f"Esto es lo que HARÍA contra Cloudflare para {dominio} (no toco nada):")
        decir(f"  1. GET   {API}/zones?name={dominio}")
        decir("     → de ahí sale el identificador de la zona (<zona>)")
        for numero, nombre in enumerate(nombres, start=2):
            decir(f"  {numero}. GET   {API}/zones/<zona>/dns_records?type=A&name={nombre}")
            decir(f"     → si no existe: POST del registro A {nombre} → {ip} (proxied)")
            decir(f"     → si ya existe: PATCH de ese registro a {ip} (proxied)")
        for numero, (ajuste, valor, porque) in enumerate(AJUSTES, start=len(nombres) + 2):
            decir(f"  {numero}. PATCH {API}/zones/<zona>/settings/{ajuste} → {valor}")
            decir(f"     → {porque}")
        decir("")
        decir("Y esto te quedaría a ti, en el panel (el plan Free no lo da por API):")
        for clic in CLICS:
            decir(f"  · {clic}")
        return 0

    zona = cloudflare_api(token, "GET", f"/zones?name={dominio}")
    if not zona:
        raise Rechazo(f"Cloudflare no conoce el dominio `{dominio}`",
                      salida=f"añádelo a tu cuenta y cambia los DNS en tu registrador "
                             f"(paso 2 de {RUNBOOK})")
    zona_id = zona[0]["id"]
    ok(f"zona encontrada para {dominio}")

    for nombre in nombres:
        registros = cloudflare_api(
            token, "GET", f"/zones/{zona_id}/dns_records?type=A&name={nombre}")
        cuerpo = {"type": "A", "name": nombre, "content": ip, "proxied": True, "ttl": 1}
        if registros:
            cloudflare_api(token, "PATCH",
                           f"/zones/{zona_id}/dns_records/{registros[0]['id']}", cuerpo)
            ok(f"registro A {nombre} → {ip} actualizado (por el proxy de Cloudflare)")
        else:
            cloudflare_api(token, "POST", f"/zones/{zona_id}/dns_records", cuerpo)
            ok(f"registro A {nombre} → {ip} creado (por el proxy de Cloudflare)")

    for ajuste, valor, porque in AJUSTES:
        cloudflare_api(token, "PATCH", f"/zones/{zona_id}/settings/{ajuste}",
                       {"value": valor})
        ok(f"{ajuste} = {valor} · {porque}")

    decir("")
    decir("Te quedan TRES clics en el panel de Cloudflare (el plan Free no los da por API):")
    for clic in CLICS:
        decir(f"  · {clic}")
    decir(f"Siguiente: paso 9 de {RUNBOOK} → {YO} desplegar")
    return 0


# --------------------------------------------------------------------------- #
#  servidor preparar                                                            #
# --------------------------------------------------------------------------- #

def plantilla(nombre):
    ruta = PLANTILLAS / nombre
    if not ruta.is_file():
        raise Rechazo(f"falta la plantilla `plantillas/vps/{nombre}`",
                      salida="la trae el método: "
                             "`python3 docs/00-metodo/scripts/herramienta.py actualizar`")
    return ruta


def destino_ssh(valores):
    usuario = exigir(valores, "VPS_USUARIO", "paso 5")
    ip = exigir(valores, "VPS_IP", "paso 5")
    return f"{usuario}@{ip}"


def ssh(destino, orden):
    return ["ssh", "-o", "BatchMode=yes", destino, orden]


def correr_pasos(pasos, dry_run, titulo):
    """Ejecuta (o solo enseña) una lista de (qué hace, comando, entrada)."""
    if dry_run:
        decir(f"{titulo} (no ejecuto nada):")
        for numero, (que, cmd, _) in enumerate(pasos, 1):
            decir(f"  {numero}. {que}")
            decir(f"     $ {' '.join(cmd)}")
        return []
    registro = []
    for que, cmd, entrada in pasos:
        codigo, salida = ejecutar(cmd, entrada)
        registro.append((que, " ".join(cmd), codigo, salida.strip()))
        if codigo != 0:
            ok_previos = "\n".join(f"       · {r[0]}" for r in registro[:-1])
            raise Rechazo(
                f"falló en «{que}»: {salida.strip().splitlines()[-1] if salida.strip() else 'sin salida'}"
                + (f"\n       ya estaba hecho:\n{ok_previos}" if ok_previos else ""),
                salida=f"arregla eso y vuelve a lanzar la misma orden; es idempotente "
                       f"(pasos 7 a 9 de {RUNBOOK})")
        ok(que)
    return registro


def orden_servidor(args):
    valores = leer_env()
    destino = destino_ssh(valores)
    guion = plantilla("servidor-preparar.sh").read_text(encoding="utf-8")

    pasos = [("instalar Docker, cerrar el cortafuegos y dejar /srv/app y el cron del backup",
              ssh(destino, "bash -s"), guion)]
    rclone = privado() / "rclone.conf"
    if rclone.is_file():
        pasos.append(("copiar la configuración de rclone al servidor",
                      ["scp", str(rclone), f"{destino}:/srv/app/.config/rclone/rclone.conf"],
                      None))
    else:
        warn("no hay `.private/rclone.conf`: las copias a Drive no funcionarán todavía "
             f"(se crea en el paso 12 de {RUNBOOK})")

    decir(f"servidor-preparar.sh va por la entrada estándar de ssh a {destino}")
    correr_pasos(pasos, args.dry_run, "Esto es lo que HARÍA en el servidor")
    if not args.dry_run:
        decir(f"Siguiente: paso 8 de {RUNBOOK} → {YO} cloudflare")
    return 0


# --------------------------------------------------------------------------- #
#  desplegar                                                                    #
# --------------------------------------------------------------------------- #

def commit_actual():
    repo = RAIZ / "main" if (RAIZ / "main").is_dir() else RAIZ
    codigo, salida = ejecutar(["git", "-C", str(repo), "rev-parse", "HEAD"])
    if codigo != 0 or not salida.strip():
        raise Rechazo("no sé qué commit estoy desplegando: `git rev-parse HEAD` falló",
                      salida="despliega desde un repositorio con al menos un commit "
                             f"(paso 9 de {RUNBOOK})")
    return salida.strip().splitlines()[0]


def esperar_salud(dominio, unico_intento=False):
    """(estado, texto) de https://<dominio>/health. La app tarda en levantar: se reintenta."""
    url = f"https://{dominio}/health"
    intentos = 1 if unico_intento else INTENTOS
    estado, texto = 0, ""
    for numero in range(intentos):
        estado, texto = http("GET", url)
        if estado == 200:
            return estado, texto
        if numero + 1 < intentos:
            time.sleep(PAUSA)
    return estado, texto


def comprobar_commit(texto, sha):
    """El fallo clásico: el despliegue «funciona» y sigue corriendo lo de antes."""
    try:
        datos = json.loads(texto or "{}")
    except ValueError:
        datos = {}
    corriendo = str(datos.get("commit", "")).strip()
    if not corriendo:
        warn("tu /health no dice qué commit corre: no puedo comprobar que subiera este. "
             f"Añádelo (requisito previo 2 de {RUNBOOK})")
        return
    if not (corriendo.startswith(sha[:7]) or sha.startswith(corriendo[:7])):
        raise Rechazo(
            f"el servidor corre {corriendo}, y se mandó {sha[:7]}: el despliegue no entró",
            salida=f"{YO} desplegar --anterior  para volver atrás, y luego mira el paso 9 "
                   f"de {RUNBOOK}")
    ok(f"responde el commit que se mandó ({sha[:7]})")


def anotar_registro(nombre, lineas):
    carpeta = RAIZ / ".runtime" / "deploy"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / nombre
    destino.write_text(enmascarar("\n".join(lineas) + "\n"), encoding="utf-8")
    return destino


def orden_desplegar(args):
    valores = leer_env()
    destino = destino_ssh(valores)
    dominio = exigir(valores, "DOMINIO", "paso 6")
    imagen = exigir(valores, "APP_IMAGEN", "paso 6")
    base = imagen.split(":", 1)[0]
    compose = "docker compose -f /srv/app/compose.prod.yml"

    if args.anterior:
        pasos = [
            (f"volver a la imagen anterior ({base}:anterior)",
             ssh(destino, f"docker tag {base}:anterior {imagen}"), None),
            ("arrancar los contenedores con ella",
             ssh(destino, f"cd /srv/app && {compose} up -d --remove-orphans"), None),
        ]
        correr_pasos(pasos, args.dry_run, "Esto es lo que HARÍA para volver atrás")
        if args.dry_run:
            decir(f"  {len(pasos) + 1}. esperar a que https://{dominio}/health conteste 200")
            return 0
        estado, _ = esperar_salud(dominio)
        if estado != 200:
            raise Rechazo(f"tras volver atrás, https://{dominio}/health no contesta 200 "
                          f"(dio {estado})",
                          salida=f"{YO} comprobar  y el paso 16 de {RUNBOOK}")
        ok(f"vuelta atrás hecha: https://{dominio}/health en verde")
        anotar_registro(f"{datetime.date.today().isoformat()}-anterior.log",
                        [f"vuelta a {base}:anterior el {datetime.datetime.now().isoformat()}"])
        return 0

    if not args.dry_run:
        # Aviso, no bloqueo: si de verdad falta, el `scp` de más abajo para el despliegue
        # entero; lo que este mensaje añade es el paso del runbook que lo arregla.
        faltan = [f".private/{n}" for n in ("origin.pem", "origin.key")
                  if not (privado() / n).is_file()]
        if faltan:
            warn("falta el certificado de origen (" + ", ".join(faltan) +
                 f"): se crea en el paso 4 de {RUNBOOK}")

    sha = "<el commit de ahora>" if args.dry_run else commit_actual()
    tar = RAIZ / ".runtime" / "deploy" / "imagen.tar"
    # El Dockerfile es el del repo de CÓDIGO (`main/`), no el del workspace.
    contexto = RAIZ / "main" if (RAIZ / "main").is_dir() else RAIZ
    pasos = [
        (f"construir la imagen {imagen} con el commit dentro",
         ["docker", "build", "-t", imagen, "--build-arg", f"COMMIT={sha}", str(contexto)], None),
        ("empaquetar la imagen para llevarla al VPS (sin registro que pagar)",
         ["docker", "save", "-o", str(tar), imagen], None),
        ("copiar la imagen al VPS", ["scp", str(tar), f"{destino}:/srv/app/imagen.tar"], None),
        ("copiar compose.prod.yml",
         ["scp", str(plantilla("compose.prod.yml")), f"{destino}:/srv/app/compose.prod.yml"],
         None),
        ("copiar el Caddyfile",
         ["scp", str(plantilla("Caddyfile")), f"{destino}:/srv/app/Caddyfile"], None),
        ("copiar el certificado de origen",
         ["scp", str(privado() / "origin.pem"), str(privado() / "origin.key"),
          f"{destino}:/srv/app/certificados/"], None),
        ("copiar la configuración de producción",
         ["scp", str(ruta_env()), f"{destino}:/srv/app/.env"], None),
        ("guardar la imagen de ahora como «anterior» (es la vuelta atrás)",
         ssh(destino, f"docker tag {imagen} {base}:anterior || true"), None),
        ("cargar la imagen nueva en el VPS",
         ssh(destino, "docker load -i /srv/app/imagen.tar"), None),
        ("traer las imágenes oficiales (Postgres, Caddy, Bugsink, autoheal)",
         ssh(destino, f"cd /srv/app && {compose} pull db caddy bugsink autoheal"), None),
        ("arrancar todo",
         ssh(destino, f"cd /srv/app && {compose} up -d --remove-orphans"), None),
    ]

    registro = correr_pasos(pasos, args.dry_run, "Esto es lo que HARÍA para desplegar")
    if args.dry_run:
        decir(f"  {len(pasos) + 1}. esperar a que https://{dominio}/health conteste 200")
        decir(f"  {len(pasos) + 2}. comprobar que el commit que responde es el que se mandó")
        decir(f"  {len(pasos) + 3}. dejar el registro en .runtime/deploy/<fecha>-<sha>.log")
        return 0

    estado, texto = esperar_salud(dominio)
    if estado != 200:
        raise Rechazo(
            f"https://{dominio}/health no contesta 200 (dio {estado}) tras "
            f"{INTENTOS} intentos",
            salida=f"{YO} desplegar --anterior  para volver atrás; el porqué, en "
                   f"{YO} comprobar (paso 16 de {RUNBOOK})")
    ok(f"https://{dominio}/health contesta 200")
    comprobar_commit(texto, sha)

    fichero = anotar_registro(
        f"{datetime.date.today().isoformat()}-{sha[:7]}.log",
        [f"despliegue de {sha} el {datetime.datetime.now().isoformat()}",
         f"destino: {destino} · dominio: {dominio}", ""]
        + [f"[{codigo}] {que}\n      $ {cmd}" for que, cmd, codigo, _ in registro])
    ok(f"registro en {fichero.relative_to(RAIZ)}")
    decir(f"Siguiente: paso 10 de {RUNBOOK} (Bugsink) o {YO} comprobar")
    return 0


# --------------------------------------------------------------------------- #
#  backup                                                                       #
# --------------------------------------------------------------------------- #

def anotar_restauracion_en_el_plano():
    """La ficha §3bis del plano de deploy es donde vive «cuándo se restauró la última vez»."""
    plano = RAIZ / "docs/conocimiento/plano-deploy.md"
    hoy = datetime.date.today().isoformat()
    if not plano.is_file():
        warn("no encuentro `docs/conocimiento/plano-deploy.md`: apunta tú la restauración "
             f"de prueba del {hoy} en su ficha §3bis (paso 14 de {RUNBOOK})")
        return
    texto = plano.read_text(encoding="utf-8")
    patron = re.compile(r"(?m)^(\|\s*`?datos`?\s*\|\s*)(.*?)(\s*\|\s*)$")
    casa = patron.search(texto)
    if not casa:
        warn("la ficha §3bis del plano no tiene fila `datos`: apúntala tú "
             f"(paso 14 de {RUNBOOK})")
        return
    valor = re.sub(r"\s*·\s*restauración de prueba:\s*\S+", "", casa.group(2)).strip()
    nuevo = f"{casa.group(1)}{valor} · restauración de prueba: {hoy}{casa.group(3)}"
    plano.write_text(texto[:casa.start()] + nuevo + texto[casa.end():], encoding="utf-8")
    ok(f"anotada la restauración de prueba del {hoy} en la ficha §3bis del plano de deploy")


def orden_backup(args):
    valores = leer_env()
    destino = destino_ssh(valores)

    if args.probar_restauracion:
        pasos = [("restaurar la última copia en una base de datos temporal y contar tablas",
                  ssh(destino, "sh /srv/app/restaurar-prueba.sh"), None)]
        if args.dry_run:
            correr_pasos(pasos, True, "Esto es lo que HARÍA para probar la restauración")
            decir("  2. anotar la fecha en la ficha §3bis de "
                  "`docs/conocimiento/plano-deploy.md`")
            return 0
        registro = correr_pasos(pasos, False, "")
        for linea in registro[0][3].splitlines()[-3:]:
            decir(f"       {linea}")
        anotar_restauracion_en_el_plano()
        return 0

    pasos = [("volcar la base de datos, cifrarla, subirla a Drive y rotar lo viejo",
              ssh(destino, "sh /srv/app/backup.sh"), None)]
    if args.dry_run:
        correr_pasos(pasos, True, "Esto es lo que HARÍA para copiar la base de datos")
        return 0
    registro = correr_pasos(pasos, False, "")
    subido = [l for l in registro[0][3].splitlines() if l.startswith("subido:")]
    decir(f"  último fichero: {subido[-1][len('subido:'):].strip() if subido else '¿?'}")
    decir(f"Un backup no cuenta hasta que se restaura: {YO} backup --probar-restauracion")
    return 0


# --------------------------------------------------------------------------- #
#  comprobar                                                                    #
# --------------------------------------------------------------------------- #

def orden_comprobar(args):
    valores = leer_env()
    destino = destino_ssh(valores)
    dominio = exigir(valores, "DOMINIO", "paso 6")
    compose = "docker compose -f /srv/app/compose.prod.yml"
    fallos = 0

    estado, texto = esperar_salud(dominio, unico_intento=True)
    if estado == 200:
        ok(f"/health de https://{dominio} contesta 200 · {texto.strip()[:60]}")
    else:
        fallos += 1
        fail(f"/health de https://{dominio} contesta {estado}\n"
             f"       SALIDA: python3 docs/00-metodo/scripts/vps.py desplegar --anterior  (paso 16 de {RUNBOOK})")

    codigo, salida = ejecutar(ssh(destino, f"cd /srv/app && {compose} ps"))
    if codigo == 0:
        ok("compose ps:")
        for linea in salida.strip().splitlines()[:6]:
            decir(f"       {linea}")
    else:
        fallos += 1
        fail(f"no puedo listar los contenedores (compose ps)\n"
             f"       SALIDA: comprueba el acceso: ssh {destino}  y repite "
             f"python3 docs/00-metodo/scripts/vps.py comprobar  (paso 5 de {RUNBOOK})")

    codigo, salida = ejecutar(ssh(destino, "df -h /"))
    linea = salida.strip().splitlines()[-1] if salida.strip() else "?"
    (ok if codigo == 0 else warn)(f"disco: {linea}")

    codigo, salida = ejecutar(ssh(destino, "cat /srv/app/.ultimo-backup"))
    if codigo == 0 and salida.strip():
        ok(f"último backup: {salida.strip().splitlines()[-1]}")
    else:
        warn(f"no consta ningún backup todavía (paso 12 de {RUNBOOK})")

    estado, _ = http("GET", f"https://errores.{dominio}/")
    if estado and estado < 400:
        ok(f"Bugsink responde en https://errores.{dominio}")
    else:
        fallos += 1
        fail(f"Bugsink no responde en https://errores.{dominio} (estado {estado})\n"
             f"       SALIDA: python3 docs/00-metodo/scripts/vps.py desplegar  y el paso 10 de {RUNBOOK}")

    return 1 if fallos else 0


# --------------------------------------------------------------------------- #

def construir_parser():
    parser = argparse.ArgumentParser(
        prog="vps.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ordenes = parser.add_subparsers(dest="orden", metavar="<orden>")

    p_env = ordenes.add_parser(
        "env", help="escribe .private/produccion.env preguntándote lo que solo sabes tú")
    p_env.add_argument("--comprobar", action="store_true",
                       help="no pregunta nada: dice qué variable falta")
    p_env.set_defaults(funcion=orden_env)

    p_cf = ordenes.add_parser(
        "cloudflare", help="apunta el dominio al VPS, lo protege y dice qué te queda por clicar")
    p_cf.add_argument("--dry-run", action="store_true", help="enseña el plan sin tocar nada")
    p_cf.set_defaults(funcion=orden_cloudflare)

    p_srv = ordenes.add_parser("servidor", help="prepara el VPS: Docker, cortafuegos, cron")
    p_srv.add_argument("accion", choices=["preparar"])
    p_srv.add_argument("--dry-run", action="store_true", help="enseña el plan sin tocar nada")
    p_srv.set_defaults(funcion=orden_servidor)

    p_dep = ordenes.add_parser(
        "desplegar", help="sube la aplicación y comprueba que responde el commit que mandaste")
    p_dep.add_argument("--dry-run", action="store_true", help="enseña el plan sin tocar nada")
    p_dep.add_argument("--anterior", action="store_true",
                       help="vuelve a la imagen anterior (la vuelta atrás)")
    p_dep.set_defaults(funcion=orden_desplegar)

    p_bak = ordenes.add_parser("backup", help="copia la base de datos a tu Drive, cifrada")
    p_bak.add_argument("--probar-restauracion", action="store_true", dest="probar_restauracion",
                       help="restaura la última copia en una base temporal y lo anota")
    p_bak.add_argument("--dry-run", action="store_true", help="enseña el plan sin tocar nada")
    p_bak.set_defaults(funcion=orden_backup)

    p_com = ordenes.add_parser("comprobar", help="informe de una pantalla de cómo está aquello")
    p_com.set_defaults(funcion=orden_comprobar)
    return parser


def main(argv=None):
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "funcion", None):
        parser.print_help()
        return 0

    stdout, stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _Embudo(stdout), _Embudo(stderr)
    try:
        return args.funcion(args)
    except Rechazo as rechazo:
        fail(rechazo.mensaje, rechazo.salida)
        return 1
    finally:
        sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    sys.exit(main())
