"""Unidad 060: la receta de despliegue de serie (VPS + Docker + Cloudflare).

Nada de aquí toca red, SSH ni Docker: `vps.py` canaliza TODA ejecución externa por dos
funciones inyectables — `ejecutar(cmd)` y `http(metodo, url, cuerpo, cabeceras)` — y estas
pruebas las sustituyen por dobles que graban lo que se habría hecho. El resto son asertos
de texto sobre las plantillas, el runbook y el ADR: son el contrato operativo, y lo que el
linter no mira lo mira este fichero.
"""
import datetime
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
import contextlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
METODO = RAIZ / "plantilla/docs/00-metodo"
SCRIPTS = METODO / "scripts"
SCRIPT = SCRIPTS / "vps.py"
PLANTILLAS_VPS = METODO / "plantillas/vps"
RUNBOOK = METODO / "runbooks/deploy-vps-docker.md"
ADR = METODO / "decisiones/032-receta-de-despliegue-de-serie.md"
PRIMER_DESPLIEGUE = METODO / "runbooks/primer-despliegue.md"
DEPLOY = METODO / "runbooks/deploy.md"
BOOTSTRAP = RAIZ / "visor/bootstrap.py"

FICHEROS_NUEVOS = (
    SCRIPT, RUNBOOK, ADR,
    PLANTILLAS_VPS / "compose.prod.yml",
    PLANTILLAS_VPS / "Caddyfile",
    PLANTILLAS_VPS / "env.ejemplo",
    PLANTILLAS_VPS / "servidor-preparar.sh",
    PLANTILLAS_VPS / "backup.sh",
    PLANTILLAS_VPS / "restaurar-prueba.sh",
)

HOY = datetime.date.today().isoformat()


def leer(ruta):
    return ruta.read_text(encoding="utf-8")


def cargar_vps():
    """El módulo, fresco en cada test: los dobles se pinchan sobre él."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("vps_bajo_prueba", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# --------------------------------------------------------------------------- #
#  El script                                                                    #
# --------------------------------------------------------------------------- #

class VpsBase(unittest.TestCase):
    """Workspace de mentira con `.private/`, y los dos dobles ya puestos."""

    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), f"falta {SCRIPT}")
        tmp = tempfile.TemporaryDirectory(prefix="vps-")
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name).resolve()
        (self.ws / ".private").mkdir()

        self.vps = cargar_vps()
        self.vps.RAIZ = self.ws
        self.vps.PAUSA = 0            # la espera a /health no duerme en la suite

        self.comandos = []            # [(cmd, entrada)]
        self.peticiones = []          # [(metodo, url, cuerpo)]
        self.respuestas_http = []     # cola de (estado, texto)
        self.respuesta_por_defecto = (200, '{"success": true, "result": {}}')
        self.salidas = {}             # subcadena del comando -> (codigo, salida)
        self.respuestas = {}          # clave del .env -> lo que "teclea" el usuario

        def ejecutar(cmd, entrada=None):
            self.comandos.append((list(cmd), entrada))
            texto = " ".join(cmd)
            for aguja, valor in self.salidas.items():
                if aguja in texto:
                    return valor
            return 0, ""

        def http(metodo, url, cuerpo=None, cabeceras=None):
            self.peticiones.append((metodo, url, cuerpo))
            if self.respuestas_http:
                return self.respuestas_http.pop(0)
            return self.respuesta_por_defecto

        def leer_respuesta(prompt):
            for clave, valor in self.respuestas.items():
                if clave in prompt:
                    return valor
            return ""

        self.vps.ejecutar = ejecutar
        self.vps.http = http
        self.vps.leer_respuesta = leer_respuesta

    # -- ayudas ------------------------------------------------------------- #

    def correr(self, *argv):
        """(codigo, salida completa) de `vps.py <argv>`, sin tocar el mundo."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            codigo = self.vps.main(list(argv))
        return codigo, buffer.getvalue()

    def env_de_prueba(self, **cambios):
        """`.private/produccion.env` con valores marcados: si uno sale por pantalla, se ve."""
        valores = {
            "DOMINIO": "ejemplo.com",
            "VPS_IP": "203.0.113.10",
            "VPS_USUARIO": "desplegador",
            "APP_IMAGEN": "miapp:prod",
            "POSTGRES_DB": "miapp",
            "POSTGRES_USER": "miapp",
            "POSTGRES_PASSWORD": "MARCA-SECRETA-POSTGRES",
            "SECRET_KEY": "MARCA-SECRETA-APP",
            "BUGSINK_SECRET_KEY": "MARCA-SECRETA-BUGSINK",
            "BUGSINK_SUPERUSER": "yo@ejemplo.com:MARCA-SECRETA-SUPER",
            "SENTRY_DSN": "https://MARCA-SECRETA-DSN@errores.ejemplo.com/1",
            "HEARTBEAT_URL": "https://uptime.betterstack.com/api/v1/heartbeat/MARCA-SECRETA-HB",
            "RCLONE_REMOTE": "copias-cifradas:miapp",
        }
        valores.update(cambios)
        for clave in [c for c, v in valores.items() if v is None]:
            del valores[clave]
        texto = "".join(f"{clave}={valor}\n" for clave, valor in valores.items())
        destino = self.ws / ".private/produccion.env"
        destino.write_text(texto, encoding="utf-8")
        return valores

    def token_de_prueba(self):
        (self.ws / ".private/cloudflare.token").write_text(
            "MARCA-SECRETA-TOKEN\n", encoding="utf-8")

    MARCAS = ("MARCA-SECRETA-POSTGRES", "MARCA-SECRETA-APP", "MARCA-SECRETA-BUGSINK",
              "MARCA-SECRETA-SUPER", "MARCA-SECRETA-DSN", "MARCA-SECRETA-HB",
              "MARCA-SECRETA-TOKEN")

    def sin_secretos(self, salida):
        for marca in self.MARCAS:
            self.assertNotIn(marca, salida, f"un secreto ({marca}) salió por pantalla")


class AyudaTest(VpsBase):
    def test_la_ayuda_explica_las_seis_ordenes(self):
        proceso = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(proceso.returncode, 0, proceso.stdout + proceso.stderr)
        for orden in ("env", "cloudflare", "servidor", "desplegar", "backup", "comprobar"):
            self.assertIn(orden, proceso.stdout)


class EnvTest(VpsBase):
    def test_env_escribe_todas_las_claves_y_no_enseña_ningún_secreto(self):
        self.respuestas = {
            "DOMINIO": "ejemplo.com", "VPS_IP": "203.0.113.10",
            "VPS_USUARIO": "desplegador", "APP_IMAGEN": "miapp:prod",
            "POSTGRES_DB": "miapp", "POSTGRES_USER": "miapp",
            "BUGSINK_SUPERUSER": "yo@ejemplo.com",
            "SENTRY_DSN": "", "HEARTBEAT_URL": "",
            "RCLONE_REMOTE": "copias-cifradas:miapp",
        }
        codigo, salida = self.correr("env")
        self.assertEqual(codigo, 0, salida)

        destino = self.ws / ".private/produccion.env"
        self.assertTrue(destino.is_file(), salida)
        escrito = dict(
            linea.split("=", 1) for linea in destino.read_text(encoding="utf-8").splitlines()
            if linea.strip() and not linea.startswith("#"))

        ejemplo = leer(PLANTILLAS_VPS / "env.ejemplo")
        claves_ejemplo = re.findall(r"(?m)^([A-Z][A-Z0-9_]+)=", ejemplo)
        self.assertTrue(claves_ejemplo)
        for clave in claves_ejemplo:
            self.assertIn(clave, escrito, f"`env` se dejó {clave} de env.ejemplo")

        for clave in ("POSTGRES_PASSWORD", "SECRET_KEY", "BUGSINK_SECRET_KEY"):
            self.assertGreaterEqual(len(escrito[clave]), 32, f"{clave} es demasiado corto")
        # el superusuario es email:contraseña, y la contraseña la inventa el script
        self.assertIn(":", escrito["BUGSINK_SUPERUSER"])

        # ni un solo valor generado puede haber salido por pantalla
        for clave in ("POSTGRES_PASSWORD", "SECRET_KEY", "BUGSINK_SECRET_KEY"):
            self.assertNotIn(escrito[clave], salida)
        self.assertNotIn(escrito["BUGSINK_SUPERUSER"].split(":", 1)[1], salida)
        self.assertIn("deploy-vps-docker.md", salida)   # dice cuál es el paso siguiente

    @unittest.skipIf(os.name == "nt", "los modos POSIX no existen en Windows")
    def test_el_env_queda_en_modo_0600(self):
        self.respuestas = {"DOMINIO": "ejemplo.com"}
        codigo, salida = self.correr("env")
        self.assertEqual(codigo, 0, salida)
        modo = (self.ws / ".private/produccion.env").stat().st_mode & 0o777
        self.assertEqual(modo, 0o600, oct(modo))

    def test_env_comprobar_en_verde_con_el_fichero_entero(self):
        self.env_de_prueba()
        codigo, salida = self.correr("env", "--comprobar")
        self.assertEqual(codigo, 0, salida)
        self.sin_secretos(salida)

    def test_env_comprobar_delata_la_clave_que_falta_y_el_paso_que_la_crea(self):
        self.env_de_prueba(SECRET_KEY=None)
        codigo, salida = self.correr("env", "--comprobar")
        self.assertEqual(codigo, 1, salida)
        self.assertIn("FAIL", salida)
        self.assertIn("SECRET_KEY", salida)
        self.assertIn("vps.py env", salida)
        self.assertIn("deploy-vps-docker.md", salida)
        self.sin_secretos(salida)


class CloudflareTest(VpsBase):
    ZONA = '{"success": true, "result": [{"id": "zona123", "name": "ejemplo.com"}]}'
    SIN_REGISTRO = '{"success": true, "result": []}'
    CON_REGISTRO = '{"success": true, "result": [{"id": "rec456"}]}'
    HECHO = '{"success": true, "result": {}}'

    def test_sin_token_no_se_toca_nada_y_se_dice_qué_fichero_crear(self):
        self.env_de_prueba()
        codigo, salida = self.correr("cloudflare", "--dry-run")
        self.assertEqual(codigo, 1, salida)
        self.assertIn("FAIL", salida)
        self.assertIn(".private/cloudflare.token", salida)
        self.assertIn("deploy-vps-docker.md", salida)
        self.assertEqual(self.peticiones, [], "sin token no se habla con Cloudflare")

    def test_dry_run_enseña_el_plan_entero_y_no_llama_a_nadie(self):
        self.env_de_prueba()
        self.token_de_prueba()
        codigo, salida = self.correr("cloudflare", "--dry-run")
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(self.peticiones, [], "--dry-run no puede tocar la API")
        self.assertIn("/zones?name=ejemplo.com", salida)
        self.assertIn("dns_records", salida)
        self.assertIn("203.0.113.10", salida)
        for ajuste in ("ssl", "always_use_https", "min_tls_version", "security_level"):
            self.assertIn(f"settings/{ajuste}", salida)
        # los tres clics que quedan a mano
        self.assertIn("WAF", salida)
        self.assertIn("Bot Fight Mode", salida)
        self.assertIn("rate limiting", salida)
        self.sin_secretos(salida)

    def test_crea_el_registro_y_los_cuatro_ajustes_en_orden(self):
        self.env_de_prueba()
        self.token_de_prueba()
        self.respuestas_http = [
            (200, self.ZONA),            # GET zona
            (200, self.SIN_REGISTRO),    # GET registro del dominio
            (200, self.HECHO),           # POST registro del dominio
            (200, self.SIN_REGISTRO),    # GET registro de errores.<dominio>
            (200, self.HECHO),           # POST registro de errores.<dominio>
            (200, self.HECHO), (200, self.HECHO), (200, self.HECHO), (200, self.HECHO),
        ]
        codigo, salida = self.correr("cloudflare")
        self.assertEqual(codigo, 0, salida)

        metodos = [(m, u) for m, u, _ in self.peticiones]
        self.assertIn("/zones?name=ejemplo.com", metodos[0][1])
        self.assertEqual(metodos[0][0], "GET")
        patches = [u for m, u in metodos if m == "PATCH"]
        self.assertEqual(len(patches), 4, metodos)
        for ajuste in ("ssl", "always_use_https", "min_tls_version", "security_level"):
            self.assertTrue(any(u.endswith(f"settings/{ajuste}") for u in patches), patches)
        posts = [(m, u, c) for m, u, c in self.peticiones if m == "POST"]
        self.assertTrue(posts, "no se creó el registro A")
        self.assertIn('"proxied": true', posts[0][2].replace("'", '"'))
        self.assertIn("203.0.113.10", posts[0][2])
        self.sin_secretos(salida)

    def test_un_registro_que_ya_existe_se_actualiza_en_vez_de_duplicarse(self):
        self.env_de_prueba()
        self.token_de_prueba()
        self.respuestas_http = [
            (200, self.ZONA),
            (200, self.CON_REGISTRO), (200, self.HECHO),
            (200, self.CON_REGISTRO), (200, self.HECHO),
            (200, self.HECHO), (200, self.HECHO), (200, self.HECHO), (200, self.HECHO),
        ]
        codigo, salida = self.correr("cloudflare")
        self.assertEqual(codigo, 0, salida)
        self.assertFalse([m for m, _, _ in self.peticiones if m == "POST"],
                         "el registro existía: no se crea otro")
        self.assertTrue(any("dns_records/rec456" in u for _, u, _ in self.peticiones))

    def test_un_error_de_la_api_no_puede_parecer_un_éxito(self):
        self.env_de_prueba()
        self.token_de_prueba()
        self.respuestas_http = [
            (403, '{"success": false, "errors": [{"message": "Invalid API Token"}]}')]
        codigo, salida = self.correr("cloudflare")
        self.assertEqual(codigo, 1, salida)
        self.assertIn("FAIL", salida)
        self.assertIn("Invalid API Token", salida)
        self.sin_secretos(salida)


class ServidorTest(VpsBase):
    def test_preparar_dry_run_lista_los_comandos_y_no_ejecuta_ninguno(self):
        self.env_de_prueba()
        codigo, salida = self.correr("servidor", "preparar", "--dry-run")
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(self.comandos, [], "--dry-run no toca el servidor")
        self.assertIn("ssh", salida)
        self.assertIn("desplegador@203.0.113.10", salida)
        self.assertIn("servidor-preparar.sh", salida)
        self.sin_secretos(salida)

    def test_preparar_sin_env_rechaza_nombrando_el_paso(self):
        codigo, salida = self.correr("servidor", "preparar", "--dry-run")
        self.assertEqual(codigo, 1, salida)
        self.assertIn(".private/produccion.env", salida)
        self.assertIn("vps.py env", salida)

    def test_preparar_sin_vps_ip_rechaza_nombrando_la_variable(self):
        self.env_de_prueba(VPS_IP=None)
        codigo, salida = self.correr("servidor", "preparar")
        self.assertEqual(codigo, 1, salida)
        self.assertIn("VPS_IP", salida)
        self.assertEqual(self.comandos, [])

    def test_preparar_manda_el_script_por_la_entrada_estándar(self):
        self.env_de_prueba()
        codigo, salida = self.correr("servidor", "preparar")
        self.assertEqual(codigo, 0, salida)
        entradas = [entrada for _, entrada in self.comandos if entrada]
        self.assertTrue(entradas, "el .sh viaja por stdin, no se copia suelto")
        self.assertIn("ufw", entradas[0])


class DesplegarTest(VpsBase):
    def preparar(self):
        self.env_de_prueba()
        self.salidas["rev-parse"] = (0, "abc1234def5678")

    def test_dry_run_lista_los_pasos_en_orden(self):
        self.preparar()
        codigo, salida = self.correr("desplegar", "--dry-run")
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(self.comandos, [])
        self.assertEqual(self.peticiones, [])
        posiciones = [salida.index(aguja) for aguja in
                      ("docker build", "compose.prod.yml", "up -d --remove-orphans",
                       "/health")]
        self.assertEqual(posiciones, sorted(posiciones), salida)
        self.assertIn("Caddyfile", salida)
        self.assertIn("commit", salida)
        self.sin_secretos(salida)

    def test_sin_env_no_se_despliega(self):
        codigo, salida = self.correr("desplegar", "--dry-run")
        self.assertEqual(codigo, 1, salida)
        self.assertIn(".private/produccion.env", salida)
        self.assertIn("vps.py env", salida)

    def test_el_commit_que_responde_tiene_que_ser_el_que_se_mandó(self):
        self.preparar()
        self.respuestas_http = [(200, '{"commit": "0000000"}')]
        codigo, salida = self.correr("desplegar")
        self.assertEqual(codigo, 1, salida)
        self.assertIn("FAIL", salida)
        self.assertIn("0000000", salida)
        self.assertIn("abc1234", salida)

    def test_un_despliegue_bueno_deja_su_registro(self):
        self.preparar()
        self.respuestas_http = [(200, '{"commit": "abc1234def5678", "estado": "ok"}')]
        codigo, salida = self.correr("desplegar")
        self.assertEqual(codigo, 0, salida)
        registros = sorted((self.ws / ".runtime/deploy").glob("*.log"))
        self.assertEqual(len(registros), 1, registros)
        self.assertIn("abc1234", registros[0].name)
        self.sin_secretos(leer(registros[0]))
        self.sin_secretos(salida)

    def test_anterior_vuelve_a_la_imagen_previa_sin_construir_nada(self):
        self.preparar()
        self.respuestas_http = [(200, '{"commit": "abc1234def5678"}')]
        codigo, salida = self.correr("desplegar", "--anterior")
        self.assertEqual(codigo, 0, salida)
        texto = " ".join(" ".join(cmd) for cmd, _ in self.comandos)
        self.assertNotIn("docker build", texto)
        self.assertIn("anterior", texto)


class BackupTest(VpsBase):
    def test_dry_run_de_la_restauración_de_prueba(self):
        self.env_de_prueba()
        codigo, salida = self.correr("backup", "--probar-restauracion", "--dry-run")
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(self.comandos, [])
        self.assertIn("restaurar-prueba.sh", salida)
        self.assertIn("plano-deploy.md", salida)

    def test_la_restauración_de_prueba_se_anota_en_el_plano(self):
        self.env_de_prueba()
        plano = self.ws / "docs/conocimiento/plano-deploy.md"
        plano.parent.mkdir(parents=True)
        plano.write_text(
            "## 3bis · Ficha de despliegue\n\n"
            "| clave | valor |\n|---|---|\n"
            "| `etapa` | internet |\n"
            "| `datos` | pg_dump diario a Drive |\n"
            "| `vigilancia` | Better Stack |\n", encoding="utf-8")
        codigo, salida = self.correr("backup", "--probar-restauracion")
        self.assertEqual(codigo, 0, salida)
        self.assertIn(HOY, leer(plano))
        self.assertIn("restauración de prueba", leer(plano))

    def test_el_backup_normal_enseña_el_último_fichero_subido(self):
        self.env_de_prueba()
        self.salidas["backup.sh"] = (0, "subido: miapp-2026-08-25.dump.gpg")
        codigo, salida = self.correr("backup")
        self.assertEqual(codigo, 0, salida)
        self.assertIn("miapp-2026-08-25.dump", salida)
        self.sin_secretos(salida)


class ComprobarTest(VpsBase):
    def test_el_informe_cabe_en_una_pantalla_y_mira_las_cinco_cosas(self):
        self.env_de_prueba()
        self.salidas["compose ps"] = (0, "app  Up (healthy)")
        self.salidas["df"] = (0, "/dev/sda1  40G  12G  28G  31% /")
        self.respuestas_http = [(200, '{"commit": "abc1234"}'), (200, "<html>Bugsink</html>")]
        codigo, salida = self.correr("comprobar")
        self.assertEqual(codigo, 0, salida)
        for pieza in ("/health", "compose ps", "disco", "backup", "Bugsink"):
            self.assertIn(pieza, salida)
        self.assertLessEqual(len(salida.splitlines()), 30, "el informe cabe en una pantalla")
        self.sin_secretos(salida)


class SecretosTest(VpsBase):
    def test_ninguna_orden_deja_escapar_un_secreto(self):
        self.env_de_prueba()
        self.token_de_prueba()
        self.salidas["rev-parse"] = (0, "abc1234def5678")
        todo = []
        for argv in (("env", "--comprobar"), ("cloudflare", "--dry-run"),
                     ("servidor", "preparar", "--dry-run"), ("desplegar", "--dry-run"),
                     ("backup", "--dry-run"), ("comprobar",)):
            _, salida = self.correr(*argv)
            todo.append(salida)
        self.sin_secretos("\n".join(todo))

    def test_ni_siquiera_cuando_el_error_viene_de_fuera(self):
        # un mensaje de error que arrastra el token entero: se enmascara igual
        self.env_de_prueba()
        self.token_de_prueba()
        self.respuestas_http = [
            (403, '{"success": false, "errors": [{"message": '
                  '"bad token MARCA-SECRETA-TOKEN"}]}')]
        codigo, salida = self.correr("cloudflare")
        self.assertEqual(codigo, 1, salida)
        self.sin_secretos(salida)


# --------------------------------------------------------------------------- #
#  Las plantillas: son el contrato operativo                                    #
# --------------------------------------------------------------------------- #

class PlantillasTest(unittest.TestCase):
    def test_las_seis_plantillas_existen(self):
        for nombre in ("compose.prod.yml", "Caddyfile", "env.ejemplo",
                       "servidor-preparar.sh", "backup.sh", "restaurar-prueba.sh"):
            self.assertTrue((PLANTILLAS_VPS / nombre).is_file(), f"falta plantillas/vps/{nombre}")

    def test_compose_lleva_los_cinco_servicios_todos_vigilados(self):
        texto = leer(PLANTILLAS_VPS / "compose.prod.yml")
        servicios = re.findall(r"(?m)^  ([a-z][a-z0-9_-]*):\s*$", texto)
        self.assertEqual(sorted(servicios), ["app", "autoheal", "bugsink", "caddy", "db"], servicios)
        self.assertEqual(texto.count("healthcheck:"), 5, "los cinco se vigilan")
        self.assertEqual(texto.count("restart: unless-stopped"), 5)
        self.assertIn("condition: service_healthy", texto)
        self.assertIn("postgres:16", texto)
        self.assertIn("caddy:2", texto)
        self.assertIn("bugsink/bugsink", texto)
        self.assertIn("willfarrell/autoheal", texto)

    def test_solo_caddy_publica_puertos(self):
        texto = leer(PLANTILLAS_VPS / "compose.prod.yml")
        bloques = re.split(r"(?m)^  (?=[a-z])", texto)
        for bloque in bloques:
            if "ports:" not in bloque:
                continue
            self.assertTrue(bloque.startswith("caddy:"),
                            f"un servicio que no es caddy publica puertos: {bloque[:40]}")
        self.assertIn('"80:80"', texto)
        self.assertIn('"443:443"', texto)

    def test_caddy_sirve_el_dominio_y_los_errores_con_el_certificado_de_origen(self):
        texto = leer(PLANTILLAS_VPS / "Caddyfile")
        self.assertIn("{$DOMINIO}", texto)
        self.assertIn("errores.{$DOMINIO}", texto)
        self.assertIn("tls ", texto)
        self.assertIn("origin.pem", texto)
        self.assertIn("reverse_proxy", texto)

    def test_env_ejemplo_explica_cada_variable_en_una_línea(self):
        lineas = leer(PLANTILLAS_VPS / "env.ejemplo").splitlines()
        claves, sin_comentario = [], []
        for i, linea in enumerate(lineas):
            casa = re.match(r"^([A-Z][A-Z0-9_]+)=", linea)
            if not casa:
                continue
            claves.append(casa.group(1))
            if not (i and lineas[i - 1].lstrip().startswith("#")):
                sin_comentario.append(casa.group(1))
        self.assertEqual(sin_comentario, [], f"variables sin explicar: {sin_comentario}")
        for obligatoria in ("DOMINIO", "VPS_IP", "VPS_USUARIO", "APP_IMAGEN", "POSTGRES_DB",
                            "POSTGRES_USER", "POSTGRES_PASSWORD", "SECRET_KEY",
                            "BUGSINK_SECRET_KEY", "BUGSINK_SUPERUSER", "SENTRY_DSN",
                            "HEARTBEAT_URL", "RCLONE_REMOTE"):
            self.assertIn(obligatoria, claves)

    def test_preparar_el_servidor_es_idempotente_y_cierra_el_origen(self):
        texto = leer(PLANTILLAS_VPS / "servidor-preparar.sh")
        self.assertIn("set -eu", texto)
        self.assertIn("docker.com/linux/ubuntu", texto)          # repo apt oficial
        self.assertIn("ufw", texto)
        self.assertIn("cloudflare.com/ips-v4", texto)
        self.assertIn("cloudflare.com/ips-v6", texto)
        self.assertIn("/srv/app", texto)
        self.assertIn("rclone", texto)
        self.assertIn("backup.sh", texto)                        # el cron diario
        self.assertIn("03:00", texto + leer(PLANTILLAS_VPS / "backup.sh"))

    def test_el_backup_vuelca_cifra_rota_y_avisa(self):
        texto = leer(PLANTILLAS_VPS / "backup.sh")
        self.assertIn("set -eu", texto)
        self.assertIn("pg_dump -Fc", texto)
        self.assertIn("rclone copy", texto)
        self.assertIn("--min-age 30d", texto)
        self.assertIn("HEARTBEAT_URL", texto)
        self.assertIn("curl", texto)

    def test_la_restauración_de_prueba_usa_una_bd_temporal_y_la_borra(self):
        texto = leer(PLANTILLAS_VPS / "restaurar-prueba.sh")
        self.assertIn("set -eu", texto)
        self.assertIn("pg_restore", texto)
        self.assertIn("--clean --if-exists", texto)
        self.assertIn("CREATE DATABASE", texto)
        self.assertIn("DROP DATABASE", texto)
        self.assertIn("count", texto.lower())                    # cuenta tablas


# --------------------------------------------------------------------------- #
#  El texto: runbook, ADR y enlaces                                             #
# --------------------------------------------------------------------------- #

class TextoTest(unittest.TestCase):
    def test_ningún_fichero_nuevo_propone_github_actions(self):
        patron = re.compile(r"github\s*actions|\.github/workflows|uses:\s*actions/", re.I)
        for ruta in FICHEROS_NUEVOS:
            self.assertTrue(ruta.is_file(), f"falta {ruta}")
            for numero, linea in enumerate(leer(ruta).splitlines(), 1):
                if not patron.search(linea):
                    continue
                # única excepción: la frase del runbook que las excluye
                self.assertIs(ruta, RUNBOOK, f"{ruta}:{numero} propone CI remota")
                self.assertRegex(linea, r"(?i)no|sin|jamás|nunca|aparte",
                                 f"{ruta}:{numero}: {linea}")

    def test_el_runbook_guía_de_principio_a_fin(self):
        texto = leer(RUNBOOK)
        for seccion in ("Cuándo", "Quién", "Resultado"):
            self.assertIn(seccion, texto)
        for pieza in ("Cloudflare", "Origin CA", "Hetzner", "OVH", "Bugsink", "Better Stack",
                      "rclone", "Caddy", "autoheal", "3bis", "vuelta atrás"):
            self.assertIn(pieza, texto, f"el runbook no cubre {pieza}")
        for orden in ("vps.py env", "vps.py cloudflare", "vps.py servidor preparar",
                      "vps.py desplegar", "vps.py backup", "vps.py comprobar"):
            self.assertIn(orden, texto)
        self.assertIn("Zone:Read", texto)
        self.assertIn("DNS:Edit", texto)
        self.assertIn("Zone Settings:Edit", texto)
        self.assertIn(".private/", texto)
        self.assertIn("ADR-032", texto)

    def test_los_precios_van_fechados_y_con_su_fuente(self):
        texto = leer(RUNBOOK)
        self.assertIn("2026-08-25", texto)
        self.assertIn("3,79", texto)                      # Hetzner CX22
        self.assertIn("3,81", texto)                      # OVH VPS-1
        self.assertIn("CX22", texto)
        self.assertIn("VPS-1", texto)
        self.assertIn("## Fuentes", texto)
        for url in ("https://www.hetzner.com/cloud/regular-performance/",
                    "https://www.ovhcloud.com/en-ie/vps/",
                    "https://developers.cloudflare.com/waf/managed-rules/",
                    "https://www.bugsink.com/docs/docker-install/",
                    "https://rclone.org/drive/",
                    "https://docs.docker.com/engine/install/ubuntu/",
                    "https://www.cloudflare.com/ips-v4"):
            self.assertIn(url, texto, f"falta la fuente {url}")
        self.assertRegex(texto, r"(?i)caducan")

    def test_el_runbook_dice_quién_hace_cada_paso_de_manos_humanas(self):
        texto = leer(RUNBOOK)
        self.assertGreaterEqual(len(re.findall(r"(?m)^## \d+", texto)), 12,
                                "los pasos van numerados, de principio a fin")
        self.assertIn("el usuario", texto)
        self.assertIn("el agente", texto)

    def test_el_adr_030_supera_en_parte_al_011_y_dice_cómo_se_comprueba(self):
        texto = leer(ADR)
        self.assertIn("ADR-011", texto)
        self.assertIn("2026-08-25", texto)
        for seccion in ("## Contexto", "## Decisión", "## Consecuencias", "## Verificación"):
            self.assertIn(seccion, texto)
        self.assertRegex(texto, r"(?i)se mantiene")
        self.assertIn("lint_deploy.py", texto)
        self.assertIn("test_vps.py", texto)

    def test_los_dos_runbooks_de_siempre_ofrecen_la_receta(self):
        primero = leer(PRIMER_DESPLIEGUE)
        self.assertIn("deploy-vps-docker.md", primero)
        # sigue mandando investigar: la receta es la opción de serie, no la única
        self.assertIn("tres", primero)
        deploy = leer(DEPLOY)
        self.assertIn("deploy-vps-docker.md", deploy)

    def test_lint_deploy_no_ha_cambiado_de_criterio(self):
        texto = leer(SCRIPTS / "lint_deploy.py")
        for casilla in ("etapa", "camino", "vuelta_atras", "datos", "vigilancia"):
            self.assertIn(f'"{casilla}"', texto)
        self.assertNotIn("vps.py", texto, "el gate sigue sin saber cómo se despliega nadie")


class ManifiestoTest(unittest.TestCase):
    """R5. ROJO DECLARADO: `visor/bootstrap.py` lo tiene reservado la revisión del bug 044.

    Las líneas exactas están en `hallazgos.md` y las aplica el padre antes del merge; este
    test es lo que lo pondrá en verde. Es la ÚNICA excepción declarada de la unidad 060.
    """

    def test_los_ficheros_nuevos_viajan_al_workspace(self):
        texto = leer(BOOTSTRAP)
        self.assertIn('"deploy-vps-docker"', texto)
        self.assertIn('"032-receta-de-despliegue-de-serie.md"', texto)
        self.assertIn('"vps.py"', texto)
        self.assertIn("PLANTILLAS_VPS", texto)
        for nombre in ("compose.prod.yml", "Caddyfile", "env.ejemplo",
                       "servidor-preparar.sh", "backup.sh", "restaurar-prueba.sh"):
            self.assertIn(nombre, texto, f"plantillas/vps/{nombre} no viaja")


if __name__ == "__main__":
    unittest.main()
