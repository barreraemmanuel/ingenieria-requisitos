"""121 · La web se explica sola: el estado del taller en Inicio, y cada apartado dicho.

Un test por criterio del contrato
(`docs/05-trabajo/121-la-web-se-explica-sola/especificacion.md`), al nivel que
declara su §Verificación:

- R1 — `estado.taller()` cruza los DOS repos de verdad (meta-repo y `main/`):
  nombre, rama, enlace de GitHub cuando el remoto lo es, «N cambios sin
  commitear» (0 = limpio) y «N commits sin empujar». Integración: dos repos git
  temporales con un espejo bare, un cambio suelto y un commit sin empujar.
- R2 — la misma tarjeta lista los servidores locales del método que ESTÁN
  escuchando (puerto, apartado y desde cuándo, cruzando los recibos de
  `.runtime/` con los puertos abiertos) y los contenedores de `docker ps`; sin
  Docker se dice en una línea y no revienta. Integración con dobles: un
  proveedor de puertos inyectado y un `docker` de mentira en el PATH.
- R3 — `estado.sesion_principal()`: «trabajando ahora» con un cerrojo vivo o un
  recibo de ejecución en curso, «parada desde <hora>» si no. Unitario.
- R4/R5 — los rótulos y las cabeceras que se leen en pantalla: «Inicio» en la
  barra, «Te toca validar» en vez de «terminadas», y las cabeceras de Contratos
  y de «Entregas: te toca probar». Unitario sobre las plantillas.
- R6 — sin `.git`, sin remoto, sin Docker y sin recibos: cada dato dice que no
  hay dato, la foto se compone igual y no tarda más de 2 s.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # visor_tablero/
RAIZ = BASE.parent
ESTADO = BASE / "estado.py"
PLANTILLA_TABLERO = BASE / "plantilla.html"
PLANTILLA_CONTRATOS = RAIZ / "visor_contratos" / "plantilla.html"
PLANTILLA_PRESENTACIONES = RAIZ / "visor_presentaciones" / "plantilla.html"
CASCARA = RAIZ / "web" / "plantilla.html"


def _cargar(ruta, nombre):
    if str(ruta.parent) not in sys.path:
        sys.path.insert(0, str(ruta.parent))
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


estado_mod = _cargar(ESTADO, "estado_taller_bajo_prueba")


# --------------------------------------------------------------------------- fixtures

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False)


def repo_con_remoto(ruta, url_publica=None, sin_commitear=0, sin_empujar=0,
                    ignorar=(), espejos=None):
    """Un repo git de verdad, con espejo bare y —si se pide— URL de GitHub.

    El espejo local es lo que da una rama de seguimiento auténtica (sin ella
    `rev-list @{u}..HEAD` no significa nada). Después se le cambia la URL a la
    pública: la referencia `origin/main` ya está en disco, así que el conteo
    sigue siendo real y el enlace es el que vería una persona.

    `ignorar` va al `.gitignore` del primer commit: el meta-repo lleva dentro
    `main/`, que es OTRO repo, y sin ignorarlo el conteo de cambios sueltos
    contaría la carpeta del repo de código.
    """
    ruta = Path(ruta)
    ruta.mkdir(parents=True, exist_ok=True)
    _git(ruta, "init", "-q", "-b", "main")
    _git(ruta, "config", "user.email", "prueba@local")
    _git(ruta, "config", "user.name", "prueba")
    (ruta / "README.md").write_text("base\n", encoding="utf-8")
    if ignorar:
        (ruta / ".gitignore").write_text("\n".join(ignorar) + "\n", encoding="utf-8")
    _git(ruta, "add", "-A")
    _git(ruta, "commit", "-q", "-m", "base")
    espejo = Path(espejos or ruta.parent) / (ruta.name + ".espejo.git")
    _git(espejo.parent, "init", "-q", "--bare", str(espejo))
    _git(ruta, "remote", "add", "origin", str(espejo))
    _git(ruta, "push", "-q", "origin", "main")
    _git(ruta, "branch", "-q", "--set-upstream-to=origin/main", "main")
    if url_publica:
        _git(ruta, "remote", "set-url", "origin", url_publica)
    for i in range(sin_empujar):
        (ruta / ("empujado-no-%d.txt" % i)).write_text("x\n", encoding="utf-8")
        _git(ruta, "add", "-A")
        _git(ruta, "commit", "-q", "-m", "sin empujar %d" % i)
    for i in range(sin_commitear):
        (ruta / ("suelto-%d.txt" % i)).write_text("y\n", encoding="utf-8")
    return ruta


def docker_falso(carpeta, salida="", codigo=0):
    """Un `docker` ejecutable en una carpeta, para meterlo delante del PATH."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    guion = carpeta / "docker"
    # `printf` es un builtin del shell: el PATH de la prueba se queda a propósito
    # sin `/bin`, y con `cat` este doble no imprimiría nada.
    guion.write_text(
        "#!/bin/sh\nprintf '%%s\\n' '%s'\nexit %d\n" % (salida, codigo),
        encoding="utf-8")
    guion.chmod(0o755)
    return carpeta


class ConPath:
    """PATH acotado: sólo lo que la prueba ponga (o nada, para «sin Docker»)."""

    def __init__(self, prueba, valor):
        self.anterior = os.environ.get("PATH", "")
        os.environ["PATH"] = valor
        prueba.addCleanup(self._restaurar)

    def _restaurar(self):
        os.environ["PATH"] = self.anterior


# --------------------------------------------------------------------------- R1

class RepoDelTallerTest(unittest.TestCase):
    """R1 — los dos repos, con su rama, su enlace y sus dos cuentas."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp(prefix="taller-r1-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.fuera = Path(tempfile.mkdtemp(prefix="taller-r1-espejos-"))
        self.addCleanup(shutil.rmtree, self.fuera, True)
        repo_con_remoto(
            self.raiz,
            url_publica="https://github.com/nategentile/ingenieria-requisitos-agents.git",
            sin_commitear=1, sin_empujar=1, ignorar=("main/",),
            espejos=self.fuera)
        repo_con_remoto(
            self.raiz / "main",
            url_publica="git@github.com:nategentile/ingenieria-requisitos.git",
            espejos=self.fuera)

    def _repos(self):
        return {r["clave"]: r for r in estado_mod.taller(self.raiz)["repos"]}

    def test_los_dos_repos_salen_con_nombre_y_rama(self):
        repos = self._repos()
        self.assertEqual({"meta-repo", "repo de código"}, set(repos),
                         "R1: Inicio tiene que traer los DOS repos del taller")
        self.assertEqual("ingenieria-requisitos-agents", repos["meta-repo"]["nombre"],
                         "R1: el nombre del meta-repo")
        self.assertEqual("ingenieria-requisitos", repos["repo de código"]["nombre"])
        self.assertEqual("main", repos["meta-repo"]["rama"],
                         "R1: la rama del meta-repo")
        self.assertEqual("main", repos["repo de código"]["rama"])

    def test_el_remoto_de_github_se_convierte_en_enlace_en_las_dos_formas(self):
        repos = self._repos()
        self.assertEqual(
            "https://github.com/nategentile/ingenieria-requisitos-agents",
            repos["meta-repo"]["github"],
            "R1: el remoto de GitHub tiene que llegar como enlace")
        self.assertEqual("https://github.com/nategentile/ingenieria-requisitos",
                         repos["repo de código"]["github"])

    def test_cuenta_los_cambios_sueltos_y_los_commits_sin_empujar(self):
        repos = self._repos()
        meta = repos["meta-repo"]
        self.assertEqual(estado_mod.OK, meta["sin_commitear"]["estado"])
        self.assertEqual(1, meta["sin_commitear"]["cambios"],
                         "R1: «N cambios sin commitear» del meta-repo")
        self.assertEqual(1, meta["sin_empujar"]["commits"],
                         "R1: «N commits sin empujar» del meta-repo")
        codigo = repos["repo de código"]
        self.assertEqual(0, codigo["sin_commitear"]["cambios"])
        self.assertEqual(0, codigo["sin_empujar"]["commits"])

    def test_un_remoto_que_no_es_de_github_no_inventa_enlace(self):
        otro = Path(tempfile.mkdtemp(prefix="taller-r1b-"))
        self.addCleanup(shutil.rmtree, otro, True)
        repo_con_remoto(otro / "repo",
                        url_publica="https://gitlab.com/quien/que.git")
        repos = {r["clave"]: r for r in estado_mod.taller(otro / "repo")["repos"]}
        self.assertIsNone(repos["meta-repo"]["github"])
        self.assertEqual("que", repos["meta-repo"]["nombre"])

    def test_ninguna_ruta_absoluta_de_la_maquina_viaja_al_navegador(self):
        crudo = json.dumps(estado_mod.taller(self.raiz), ensure_ascii=False)
        self.assertNotIn(str(self.raiz), crudo)


# --------------------------------------------------------------------------- R2

class ServidoresYDockerTest(unittest.TestCase):
    """R2 — lo que escucha de verdad y lo que Docker tiene en marcha."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp(prefix="taller-r2-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        runtime = self.raiz / ".runtime"
        runtime.mkdir(parents=True)
        # El recibo que deja `web/abrir.py` al levantar la web única.
        self.desde = datetime.now(timezone.utc) - timedelta(minutes=9)
        recibo = runtime / "web-9041.log"
        recibo.write_text("levantada\n", encoding="utf-8")
        os.utime(recibo, (self.desde.timestamp(), self.desde.timestamp()))

    def _procesos(self):
        return lambda: [
            {"pid": 4242, "puerto": 9041, "cwd": str(self.raiz / "main"),
             "comando": "python3 %s/main/web/servir.py --workspace %s"
                        % (self.raiz, self.raiz)},
            # Algo que escucha pero no es del método: no se cuenta.
            {"pid": 99, "puerto": 5432, "cwd": "/", "comando": "postgres"},
        ]

    def test_lista_el_servidor_del_metodo_con_puerto_apartado_y_desde_cuando(self):
        foto = estado_mod.taller(self.raiz, procesos=self._procesos())
        servidores = foto["servidores"]
        self.assertEqual(estado_mod.OK, servidores["estado"])
        self.assertEqual(1, len(servidores["lista"]), servidores)
        uno = servidores["lista"][0]
        self.assertEqual(9041, uno["puerto"])
        self.assertIn("web", uno["servicio"])
        self.assertTrue(uno["desde"], "el recibo de .runtime dice desde cuándo")
        self.assertEqual(self.desde.date().isoformat(), uno["desde"][:10])

    def test_un_servidor_de_otro_workspace_no_ensena_la_ruta_de_la_maquina(self):
        """R8 de la 058, que la 121 vuelve a tocar: mirar TODOS los puertos hace
        aparecer servidores de otros proyectos, y su ruta lleva dentro el nombre
        de la persona. Se dice que están fuera, no dónde."""
        def fuera():
            return [{"pid": 7, "puerto": 8875, "cwd": "/Users/quien/otro",
                     "comando": "python3 /Users/quien/otro/visor_tablero/servir.py"}]
        foto = estado_mod.taller(self.raiz, procesos=fuera)
        uno = foto["servidores"]["lista"][0]
        self.assertNotIn("/Users", json.dumps(foto, ensure_ascii=False))
        self.assertEqual("otro workspace de esta máquina", uno["arbol"])

    def test_si_no_se_pueden_mirar_los_puertos_se_dice_en_vez_de_decir_ninguno(self):
        def revienta():
            raise OSError("lsof no está")
        foto = estado_mod.taller(self.raiz, procesos=revienta)
        self.assertEqual(estado_mod.NO_COMPROBABLE, foto["servidores"]["estado"])
        self.assertEqual([], foto["servidores"]["lista"])
        self.assertIn("lsof", foto["servidores"]["detalle"])

    def test_docker_en_marcha_sale_con_nombre_e_imagen(self):
        carpeta = docker_falso(
            self.raiz / "bin",
            salida='{"Names":"prueba","Image":"nginx","Status":"Up 3 minutes"}')
        ConPath(self, str(carpeta))
        foto = estado_mod.taller(self.raiz, procesos=self._procesos())
        docker = foto["docker"]
        self.assertEqual(estado_mod.OK, docker["estado"], docker)
        self.assertEqual([{"nombre": "prueba", "imagen": "nginx",
                           "estado": "Up 3 minutes"}], docker["lista"])

    def test_sin_docker_se_dice_en_una_linea_y_la_foto_sigue(self):
        vacio = self.raiz / "sin-docker"
        vacio.mkdir()
        ConPath(self, str(vacio))
        foto = estado_mod.taller(self.raiz, procesos=self._procesos())
        self.assertNotEqual(estado_mod.OK, foto["docker"]["estado"])
        self.assertEqual([], foto["docker"]["lista"])
        self.assertIn("Docker", foto["docker"]["detalle"])
        self.assertEqual(estado_mod.OK, foto["estado"])

    def test_docker_que_falla_no_se_cuenta_como_cero_contenedores(self):
        carpeta = docker_falso(self.raiz / "roto",
                               salida="Cannot connect to the Docker daemon",
                               codigo=1)
        ConPath(self, str(carpeta))
        foto = estado_mod.taller(self.raiz, procesos=self._procesos())
        self.assertNotEqual(estado_mod.OK, foto["docker"]["estado"])
        self.assertEqual([], foto["docker"]["lista"])


# --------------------------------------------------------------------------- R3

class SesionPrincipalTest(unittest.TestCase):
    """R3 — trabajando ahora, o parada desde una hora concreta."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp(prefix="taller-r3-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        self.activos = self.raiz / ".runtime" / "leases" / "active"
        self.activos.mkdir(parents=True)
        (self.raiz / ".runtime" / "ejecuciones").mkdir(parents=True)

    def _cerrojo(self, pid, minutos=6):
        creado = (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()
        (self.activos / "sesion.json").write_text(json.dumps({
            "created": creado, "scope": "unit:121", "fencing": 1,
            "owner": {"host": "local", "pid": pid, "session_id": "s-121"},
        }), encoding="utf-8")
        return creado

    def _pid_muerto(self):
        proceso = subprocess.Popen([sys.executable, "-c", "pass"])
        proceso.wait()
        return proceso.pid

    def test_con_un_cerrojo_vivo_la_sesion_esta_trabajando_ahora(self):
        self._cerrojo(os.getpid(), minutos=6)
        sesion = estado_mod.sesion_principal(self.raiz)
        self.assertEqual(estado_mod.OK, sesion["estado"])
        self.assertTrue(sesion["activa"])
        self.assertEqual(6, sesion["minutos"])

    def test_sin_nada_vivo_la_sesion_esta_parada_desde_la_ultima_senal(self):
        creado = self._cerrojo(self._pid_muerto(), minutos=40)
        sesion = estado_mod.sesion_principal(self.raiz)
        self.assertFalse(sesion["activa"])
        self.assertEqual(creado[:16], (sesion["desde"] or "")[:16])

    def test_un_recibo_de_ejecucion_en_curso_tambien_cuenta_como_viva(self):
        recibo = self.raiz / ".runtime" / "ejecuciones" / "121-abc.json"
        recibo.write_text(json.dumps({
            "schema": "ejecucion/v1", "unidad": "121", "rol": "constructor",
            "lease": {"session_id": "s-121"},
            "lanzador": {"pid": os.getpid()},
        }), encoding="utf-8")
        sesion = estado_mod.sesion_principal(self.raiz)
        self.assertTrue(sesion["activa"], sesion)

    def test_sin_una_sola_senal_no_se_afirma_ni_viva_ni_parada_desde_cuando(self):
        sesion = estado_mod.sesion_principal(self.raiz)
        self.assertFalse(sesion["activa"])
        self.assertIsNone(sesion["desde"])
        self.assertEqual(estado_mod.AUSENTE, sesion["estado"])


# --------------------------------------------------------------------------- R4 y R5

def _texto(ruta):
    return ruta.read_text(encoding="utf-8")


class RotulosTest(unittest.TestCase):
    """R4 y R5 — lo que una persona lee, sin jerga y sin «terminadas»."""

    def test_el_primer_apartado_se_llama_inicio_en_la_barra(self):
        cascara = _texto(CASCARA)
        self.assertIn('data-web="tablero">Inicio<', cascara.replace("\n", ""))
        self.assertNotIn(">Tablero<", cascara)

    def test_inicio_tambien_en_el_titulo_de_la_pagina_y_en_su_menu(self):
        plantilla = _texto(PLANTILLA_TABLERO)
        self.assertIn("<title>Inicio", plantilla)
        self.assertIn('<div class="titulo-menu">Inicio</div>', plantilla)

    def test_web_servir_declara_el_apartado_como_inicio(self):
        servir = _cargar(RAIZ / "web" / "servir.py", "web_servir_rotulos")
        rotulos = {clave: rotulo for clave, _, rotulo in servir.APARTADOS}
        self.assertEqual("Inicio", rotulos["tablero"])
        self.assertEqual("Entregas", rotulos["presentaciones"])

    def test_lo_que_espera_tu_ok_se_llama_te_toca_validar_y_se_explica(self):
        plantilla = _texto(PLANTILLA_TABLERO)
        self.assertIn("Te toca validar", plantilla)
        self.assertNotIn("Entregas por validar", plantilla)
        self.assertIn("fusionada y revisada", plantilla)
        self.assertIn("se archiva cuando la pruebes y confirmes", plantilla)

    def test_inicio_pinta_una_tarjeta_llamada_taller(self):
        plantilla = _texto(PLANTILLA_TABLERO)
        self.assertIn("pintarTaller", plantilla)
        self.assertIn(">Taller<", plantilla)

    def test_contratos_lleva_una_cabecera_de_seis_lineas_como_mucho(self):
        plantilla = _texto(PLANTILLA_CONTRATOS)
        self.assertIn('<div class="explica"', plantilla)
        cabecera = plantilla.split('<div class="explica"', 1)[1].split("</div>", 1)[0]
        self.assertLessEqual(len([l for l in cabecera.splitlines() if l.strip()]), 6)
        for trozo in ("se compromete a construir", "aprobar", "pedir cambios"):
            self.assertIn(trozo, plantilla)

    def test_presentaciones_se_titula_entregas_te_toca_probar_y_se_explica(self):
        plantilla = _texto(PLANTILLA_PRESENTACIONES)
        self.assertIn("<h1>Entregas: te toca probar</h1>", plantilla)
        self.assertIn("<title>Entregas", plantilla)
        self.assertIn('<div class="explica"', plantilla)
        for trozo in ("confirmar", "problema"):
            self.assertIn(trozo, plantilla)


# --------------------------------------------------------------------------- R6

class SinNadaQueLeerTest(unittest.TestCase):
    """R6 — sin `.git`, sin remoto, sin Docker y sin recibos: se dice y se sigue."""

    def setUp(self):
        self.raiz = Path(tempfile.mkdtemp(prefix="taller-r6-"))
        self.addCleanup(shutil.rmtree, self.raiz, True)
        vacio = self.raiz / "sin-nada"
        vacio.mkdir()
        ConPath(self, str(vacio))

    def test_cada_dato_dice_que_no_hay_dato_en_vez_de_un_cero(self):
        foto = estado_mod.taller(self.raiz, procesos=lambda: [])
        self.assertEqual(estado_mod.OK, foto["estado"])
        for repo in foto["repos"]:
            self.assertEqual(estado_mod.AUSENTE, repo["estado"])
            self.assertIsNone(repo["sin_commitear"]["cambios"])
            self.assertIsNone(repo["sin_empujar"]["commits"])
            self.assertIsNone(repo["github"])
            self.assertTrue(repo["detalle"])
        self.assertEqual(estado_mod.AUSENTE, foto["sesion"]["estado"])
        self.assertNotEqual(estado_mod.OK, foto["docker"]["estado"])

    def test_la_foto_se_compone_igual_y_no_se_queda_colgada(self):
        arranque = time.monotonic()
        foto = estado_mod.taller(self.raiz, procesos=lambda: [])
        self.assertLess(time.monotonic() - arranque, 2.0)
        self.assertTrue(foto["leido"])

    def test_el_taller_viaja_dentro_de_la_foto_entera_de_inicio(self):
        foto = estado_mod.instantanea(self.raiz, procesos=lambda: [])
        self.assertIn("taller", foto)
        self.assertIn("repos", foto["taller"])


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
