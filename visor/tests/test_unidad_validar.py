"""Bug 057: pedir un OK sigue dependiendo de que el agente se acuerde de abrir la web.

La 054 hizo COMPROBABLE que un contrato se mostró; abrirlo seguía siendo un acto manual
del agente, y la validación guiada (051/056) ni siquiera tenía comando: el manifiesto se
escribía a mano. Aquí se exige que el método lo haga solo.

- R1 — `unidad.py validar NNN-slug` genera el manifiesto de la validación guiada DESDE la
  ficha («Cómo lo pruebas tú» → pasos, evidencia → evidencia, `ficheros:` → adjuntos),
  abre la web en el apartado Presentaciones y abre el navegador. Idempotente.
- R2 — `unidad.py nueva` y `unidad.py estado`, con contratos sin `aprobado:`, abren la web
  en el apartado Contratos y abren el navegador en ese contrato; con `--sin-navegador`
  solo imprimen, y lo dicen.
- R3 — `unidad.py cerrar --ok-usuario FECHA` exige un recibo `confirmado` del apartado
  Presentaciones para ESA unidad; un recibo `problema` bloquea y manda abrir un bug.

Desde la unidad 081 la web es UNA con cuatro apartados: el workspace de estos fixtures
lleva `docs/00-metodo/requisitos/web/` (lo que reparte `ARCHIVOS_WEB`) y las URL que se
comprueban son rutas de esa web, no cuatro puertos.

Las pruebas que levantan un servidor de verdad lo hacen en un puerto libre y lo matan al
terminar: nada queda escuchando cuando la suite acaba.
"""
import contextlib
import datetime
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import ayuda_cierre  # módulo hermano de la suite

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
PLANTILLAS = RAIZ / "plantilla/docs/00-metodo/plantillas"
HOY = datetime.date.today().isoformat()
SALIDA = "SALIDA:"
COMANDO_VISOR_CONTRATOS = "python3 main/web/abrir.py --workspace . --apartado contratos"

sys.path.insert(0, str(RAIZ / "visor"))
import bootstrap  # noqa: E402 - la lista única de la web (ARCHIVOS_WEB)
sys.path.insert(0, str(RAIZ / "visor_presentaciones"))
import manifestar  # noqa: E402 - se importa tras fijar la ruta del visor de presentaciones


def puerto_libre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexion:
        conexion.bind(("127.0.0.1", 0))
        return conexion.getsockname()[1]


def matar_en_puerto(puerto):
    """Deja el puerto sin nadie escuchando. Los visores se lanzan desasidos a propósito
    (sobreviven al comando que los levanta), así que el test los busca por puerto."""
    if sys.platform == "win32":
        salida = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace").stdout
        for linea in salida.splitlines():
            partes = linea.split()
            if len(partes) >= 5 and partes[1].endswith(f":{puerto}") and partes[3] == "LISTENING":
                subprocess.run(["taskkill", "/F", "/PID", partes[4]], capture_output=True)
        return
    if not shutil.which("lsof"):
        return
    salida = subprocess.run(["lsof", "-ti", f"tcp:{puerto}"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace").stdout
    for pid in salida.split():
        with contextlib.suppress(ProcessLookupError, ValueError, PermissionError):
            os.kill(int(pid), signal.SIGTERM)


def leer(url, intentos=60):
    for _ in range(intentos):
        try:
            with urllib.request.urlopen(url, timeout=1) as respuesta:
                return json.loads(respuesta.read())
        except (OSError, ValueError, urllib.error.URLError):
            pass
    return None


class WorkspaceBase(unittest.TestCase):
    """Workspace de método mínimo pero real, CON los dos visores en su sitio."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="unidad-validar-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()

        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in (
            "control_plane.py", "ejecucion.py", "lease.py", "lint_cierre.py",
            "peticion.py", "repo_config.py", "unidad.py", "workspace_paths.py",
        ):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.peticion = scripts / "peticion.py"
        self.unidad = scripts / "unidad.py"

        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True)
        for nombre in (
            "especificacion.md", "directo.md", "bug.md", "hallazgos.md",
            "peticion-investigacion-plan.md",
            "peticion-investigacion-informe.md",
            "peticion-investigacion-sintesis.md",
        ):
            shutil.copy2(PLANTILLAS / nombre, plantillas / nombre)

        (self.ws / "docs/05-trabajo").mkdir(parents=True)
        (self.ws / "docs/bugs").mkdir(parents=True)
        decision = self.ws / "docs/decisiones/004-paleta.md"
        decision.parent.mkdir(parents=True)
        decision.write_text("# Paleta vigente\n", encoding="utf-8")

        # La web viaja al workspace igual que la reparte `bootstrap.py`: UNA lista.
        self.web = self.ws / "docs/00-metodo/requisitos/web"
        self.web.mkdir(parents=True)
        for nombre in bootstrap.ARCHIVOS_WEB:
            shutil.copy2(bootstrap.origen_web(nombre), self.web / nombre)
        shutil.copy2(RAIZ / "visor/revision.py",
                     self.web.parent / "revision.py")

        self.repo = self.ws / "main"
        (self.repo / "app").mkdir(parents=True)
        for indice in range(1, 4):
            (self.repo / "app" / f"modulo{indice}.py").write_text(
                "print('base')\n", encoding="utf-8")
        # 081: no hay una copia por visor en el repo de código. La web del workspace,
        # la de arriba, es la única — y es la ruta que `unidad.py` busca de segundas.
        self.git(self.repo, "init", "-b", "main")
        self.git(self.repo, "config", "user.name", "Test")
        self.git(self.repo, "config", "user.email", "test@example.com")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-m", "base")
        self.sha = self.git(self.repo, "rev-parse", "HEAD")

        self.aperturas = self.ws / "aperturas.txt"
        anotador = self.ws / ("anota.cmd" if sys.platform == "win32" else "anota.sh")
        if sys.platform == "win32":
            anotador.write_text(f"@echo %1>>{self.aperturas}\n", encoding="utf-8")
        else:
            anotador.write_text(
                f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{self.aperturas}"\n', encoding="utf-8")
            anotador.chmod(0o755)
        self.anotador = anotador

    # ------------------------------------------------------------------ utilidades
    def git(self, cwd, *args):
        resultado = subprocess.run(
            ["git", *args], cwd=str(cwd), text=True,
            encoding="utf-8", errors="replace", capture_output=True)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return resultado.stdout.strip()

    def entorno(self, con_pantalla=False, puerto=None):
        """Por defecto, sesión SIN pantalla: los fixtures que no miden el navegador no
        levantan visores ni abren nada en la máquina de quien pasa la suite."""
        entorno = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        entorno.pop("BROWSER", None)
        if con_pantalla:
            entorno["BROWSER"] = str(self.anotador)
            entorno.pop("IR_SIN_NAVEGADOR", None)
        else:
            entorno["IR_SIN_NAVEGADOR"] = "1"
        if puerto is not None:
            # 081: un solo puerto para la web entera (R6).
            entorno["INGENIERIA_REQUISITOS_PUERTO"] = str(puerto)
        return entorno

    def ejecutar(self, script, *args, con_pantalla=False, puerto=None):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, env=self.entorno(con_pantalla, puerto))

    def urls_abiertas(self):
        if not self.aperturas.exists():
            return []
        return [l.strip() for l in self.aperturas.read_text(encoding="utf-8").splitlines()
                if l.strip()]

    def puerto_de_pruebas(self):
        puerto = puerto_libre()
        self.addCleanup(matar_en_puerto, puerto)
        return puerto

    def capturar(self, resumen="Cambio solicitado"):
        resultado = self.ejecutar(
            self.peticion, "capturar", "--resumen", resumen,
            "--texto", "Implementa el cambio descrito", "--autor", "Nate")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return re.search(r"P-\d{8}-[a-f0-9]{8}", resultado.stdout).group(0)

    def evaluar(self, pid, ruta="feature", tipo=None, ruta_codigo="app/modulo1.py"):
        args = [
            "evaluar", pid, "--ruta", ruta, "--investigacion", "ninguna",
            "--motivo", "contraste suficiente para encaminar",
            "--flujo", "REC-1", "--huella-flujo", "planos-v1",
            "--sha", self.sha, "--ruta-codigo", ruta_codigo,
            "--conocimiento", "docs/decisiones/004-paleta.md",
        ]
        if tipo:
            args.extend(("--tipo", tipo))
        resultado = self.ejecutar(self.peticion, *args)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def dejar_rastro_visor_contratos(self, nombre, fecha=HOY):
        registro = self.ws / ".runtime" / "visor-contratos.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "a", encoding="utf-8") as rastro:
            rastro.write(f"{fecha}T00:00:00 contrato mostrado: {nombre}\n")

    def recibo_ejecucion(self, unidad, rol, session_id):
        carpeta = self.ws / ".runtime/ejecuciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{unidad}-{rol}.json").write_text(json.dumps({
            "schema": "ejecucion/v1", "id": rol, "unidad": unidad, "harness": "claude",
            "rol": rol, "modelo": None, "cwd": str(self.ws / "worktrees" / unidad),
            "rama": unidad, "lease": {"session_id": session_id, "fencing": {}},
            "git": {"inicial": {}, "final": {}}, "skills_tecnicas": [],
            "checkpoints": [], "exit_code": 0, "resultado": "ok",
        }, ensure_ascii=False), encoding="utf-8")

    # ---------------------------------------------------------- unidades de juguete
    CUERPO = """

# {nnn} · Cambio pequeño y localizado

## Qué (en idioma de negocio)

El usuario podrá completar el cambio solicitado sin alterar el comportamiento adyacente.
La implementación conserva los datos existentes y muestra un resultado verificable en la
misma entrada que usa hoy, sin pedirle ningún paso nuevo ni mover nada de sitio.

## Criterios de aceptación

- **R1** — Cuando el usuario repite la acción de siempre, el resultado aparece igual.
- **R2** — (caso límite) Cuando el dato falta, no se pierde el trabajo ya hecho.

## Cómo lo pruebas tú (máximo 10 filas, sin tecnicismos)

| # | Dónde | Qué haces | Qué deberías ver |
|---|---|---|---|
| 1 | Listado de pedidos | Busca el albarán 4471 | La ficha del albarán 4471 |
| 2 | Ficha del albarán | Cambia la cantidad a 12 | El total se recalcula solo |

- **NO debe haber cambiado:** el listado de facturas de al lado.

## Verificación

- Comando(s) que deben salir en verde: `python3 -m pytest`
- **Nivel de test:** unitario, porque la conducta es una regla local y no cruza fronteras.
- **Criterio portante:** R1 — sin él la unidad entera no sirve de nada.
"""

    def unidad_con_rama(self, slug, ficheros=("app/modulo1.py",), cuerpo=None):
        pid = self.capturar(f"Trabajo {slug}")
        self.evaluar(pid, ruta_codigo=ficheros[0])
        creada = self.ejecutar(self.unidad, "nueva", "feature", slug, "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        carpeta = next((self.ws / "docs/05-trabajo").glob(f"[0-9][0-9][0-9]-{slug}"))
        ruta, nombre = carpeta / "especificacion.md", carpeta.name
        texto = ruta.read_text(encoding="utf-8")
        cabecera = texto[: texto.find("---", 4) + 3]
        cabecera = cabecera.replace("aprobado: no", f"aprobado: {HOY}")
        cabecera = re.sub(r"^ficheros:.*$", "ficheros: [" + ", ".join(ficheros) + "]",
                          cabecera, count=1, flags=re.M)
        cabecera = re.sub(r"^actividad:.*$", "actividad: pedidos", cabecera,
                          count=1, flags=re.M)
        ruta.write_text(cabecera + (cuerpo or self.CUERPO).format(nnn=nombre),
                        encoding="utf-8")
        self.dejar_rastro_visor_contratos(nombre)
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        return nombre

    def unidad_cerrable(self, slug):
        """Unidad REAL fusionada, revisada y con recibos: lista para `cerrar`."""
        nombre = self.unidad_con_rama(slug)
        worktree = self.ws / "worktrees" / nombre
        (worktree / "app/modulo1.py").write_text("print(1)\nprint(2)\n", encoding="utf-8")
        self.git(worktree, "add", "-A")
        self.git(worktree, "commit", "-m", f"trabajo de {nombre}")
        self.git(self.repo, "merge", "--ff-only", nombre)
        self.git(self.repo, "worktree", "remove", str(worktree))
        carpeta = self.ws / "docs/05-trabajo" / nombre
        spec, hallazgos = carpeta / "especificacion.md", carpeta / "hallazgos.md"
        spec.write_text(re.sub(r"^estado:\s*\S+", "estado: en_revision",
                               spec.read_text(encoding="utf-8"), count=1, flags=re.M),
                        encoding="utf-8")
        texto = hallazgos.read_text(encoding="utf-8")
        texto = re.sub(r"^revisor:.*$", "revisor: agente-fresco", texto, count=1, flags=re.M)
        texto = re.sub(r"^revisado:.*$", f"revisado: {HOY}", texto, count=1, flags=re.M)
        texto = texto.replace("- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN",
                              "- **Veredicto:** LIMPIO")
        hallazgos.write_text(texto, encoding="utf-8")
        ayuda_cierre.escribir_parte_honesto(self.ws, hallazgos)
        self.recibo_ejecucion(nombre, "constructor", f"c-{nombre}")
        self.recibo_ejecucion(nombre, "revisor", f"r-{nombre}")
        return nombre

    # ----------------------------------------------------------------- recibos 051
    def datos_de(self, nombre):
        return self.ws / ".runtime/presentaciones" / nombre

    def dejar_recibo(self, nombre, eleccion="confirmado", fecha=None, comentario=""):
        """Escribe un recibo con el MISMO formato que sella `visor_presentaciones`."""
        fecha = fecha or HOY
        carpeta = self.datos_de(nombre) / "recibos"
        carpeta.mkdir(parents=True, exist_ok=True)
        marca = f"{fecha}T09:00:00.000000+00:00"
        recibo = {
            "id": f"{fecha.replace('-', '')}T090000.000000Z-{eleccion}",
            "presentacion": nombre, "version": "1",
            "contenido_revisado": "pasos", "eleccion": eleccion,
            "comentario": comentario, "fecha": marca,
        }
        (carpeta / (recibo["id"] + ".json")).write_text(
            json.dumps(recibo, ensure_ascii=False), encoding="utf-8")
        return recibo


# ============================================================================ R1
class ValidarGeneraElManifiestoTest(WorkspaceBase):
    """R1 — un comando, no una costumbre."""

    def test_validar_genera_el_manifiesto_desde_la_ficha(self):
        nombre = self.unidad_con_rama("validacion-guiada")

        resultado = self.ejecutar(self.unidad, "validar", nombre, "--sin-navegador")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        ruta = self.datos_de(nombre) / "manifiesto.json"
        self.assertTrue(ruta.is_file(), resultado.stdout + resultado.stderr)
        datos = manifestar.validar(json.loads(ruta.read_text(encoding="utf-8")))
        vista = next(p for p in datos["presentaciones"] if p["tipo"] == "validacion")
        self.assertEqual(vista["id"], nombre)
        pasos = " | ".join(vista["pasos"])
        self.assertIn("albarán 4471", pasos)
        self.assertIn("El total se recalcula solo", pasos)
        self.assertEqual(vista["opciones"], ["confirmado", "problema"])
        self.assertEqual(vista["comentario_obligatorio"], ["problema"])
        self.assertTrue(vista["evidencia"])
        self.assertIn(f"docs/05-trabajo/{nombre}/especificacion.md", vista["adjuntos"])
        self.assertIn("main/app/modulo1.py", vista["adjuntos"])

    def test_validar_es_idempotente_y_no_pisa_los_recibos(self):
        nombre = self.unidad_con_rama("idempotente")
        primera = self.ejecutar(self.unidad, "validar", nombre, "--sin-navegador")
        self.assertEqual(primera.returncode, 0, primera.stdout + primera.stderr)
        self.dejar_recibo(nombre, "confirmado")

        segunda = self.ejecutar(self.unidad, "validar", nombre, "--sin-navegador")

        self.assertEqual(segunda.returncode, 0, segunda.stdout + segunda.stderr)
        self.assertTrue((self.datos_de(nombre) / "manifiesto.json").is_file())
        self.assertEqual(len(list((self.datos_de(nombre) / "recibos").glob("*.json"))), 1)

    def test_validar_sin_como_lo_pruebas_bloquea_y_dice_por_donde_salir(self):
        """Sin esa tabla el usuario firma un «me parece bien» sin haber comprobado nada."""
        cuerpo = self.CUERPO.replace(
            "## Cómo lo pruebas tú (máximo 10 filas, sin tecnicismos)", "## Otra cosa")
        nombre = self.unidad_con_rama("sin-como-se-prueba", cuerpo=cuerpo)

        resultado = self.ejecutar(self.unidad, "validar", nombre, "--sin-navegador")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("Cómo lo pruebas tú", salida)
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.datos_de(nombre) / "manifiesto.json").exists())

    def test_validar_sin_navegador_no_abre_nada(self):
        nombre = self.unidad_con_rama("sin-navegador")

        resultado = self.ejecutar(self.unidad, "validar", nombre, "--sin-navegador",
                                  con_pantalla=True)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.urls_abiertas(), [])
        self.assertIn("--sin-navegador", resultado.stdout)

    def test_validar_levanta_el_visor_y_abre_el_navegador(self):
        nombre = self.unidad_con_rama("abre-sola")
        puerto = self.puerto_de_pruebas()

        resultado = self.ejecutar(self.unidad, "validar", nombre, "--puerto", str(puerto),
                                  con_pantalla=True)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        url = f"http://127.0.0.1:{puerto}/presentaciones/{nombre}"
        self.assertIn(url, self.urls_abiertas(), salida)
        servido = leer(f"http://127.0.0.1:{puerto}/presentaciones/{nombre}/manifiesto.json")
        self.assertIsNotNone(servido, salida)
        self.assertEqual([p["id"] for p in servido["presentaciones"]], [nombre])


# ============================================================================ R2
class ContratoQueSeAbreSoloTest(WorkspaceBase):
    """R2 — `nueva` y `estado` levantan el visor de contratos y abren el navegador."""

    def crear_contrato_pendiente(self, slug="pendiente-de-ok", extra=(), **kwargs):
        pid = self.capturar(f"Nueva unidad {slug}")
        self.evaluar(pid)
        return self.ejecutar(self.unidad, "nueva", "feature", slug, "--desde", pid,
                             *extra, **kwargs)

    def test_nueva_levanta_el_visor_y_abre_el_contrato(self):
        puerto = self.puerto_de_pruebas()

        resultado = self.crear_contrato_pendiente(con_pantalla=True, puerto=puerto)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn(f"http://127.0.0.1:{puerto}/contratos#001-pendiente-de-ok",
                      self.urls_abiertas(), salida)
        self.assertIsNotNone(leer(f"http://127.0.0.1:{puerto}/meta.json"), salida)

    def test_nueva_con_sin_navegador_solo_imprime_y_lo_dice(self):
        puerto = self.puerto_de_pruebas()

        resultado = self.crear_contrato_pendiente(
            con_pantalla=True, puerto=puerto, extra=("--sin-navegador",))

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertEqual(self.urls_abiertas(), [])
        self.assertIn(COMANDO_VISOR_CONTRATOS, salida)
        self.assertIn("--sin-navegador", salida)
        self.assertIsNone(leer(f"http://127.0.0.1:{puerto}/meta.json", intentos=2), salida)

    def test_estado_abre_el_contrato_pendiente(self):
        creada = self.crear_contrato_pendiente()
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        puerto = self.puerto_de_pruebas()

        resultado = self.ejecutar(self.unidad, "estado", con_pantalla=True, puerto=puerto)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn(f"http://127.0.0.1:{puerto}/contratos#001-pendiente-de-ok",
                      self.urls_abiertas(), salida)

    def test_estado_sin_contratos_pendientes_no_abre_nada(self):
        puerto = self.puerto_de_pruebas()

        resultado = self.ejecutar(self.unidad, "estado", con_pantalla=True, puerto=puerto)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(self.urls_abiertas(), [])


# ============================================================================ R3
class ElOkSeLeeNoSeTecleaTest(WorkspaceBase):
    """R3 — `--ok-usuario` sin recibo del apartado es una fecha tecleada, no un OK."""

    def test_cerrar_sin_recibo_bloquea_y_nombra_validar(self):
        nombre = self.unidad_cerrable("sin-recibo")

        resultado = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn(f"validar {nombre}", salida)
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_cerrar_con_recibo_problema_bloquea_y_manda_abrir_un_bug(self):
        nombre = self.unidad_cerrable("con-problema")
        self.dejar_recibo(nombre, "problema", comentario="el total sigue sin recalcularse")

        resultado = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("problema", salida)
        self.assertIn("bug", salida.lower())
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_cerrar_con_recibo_confirmado_pasa_la_puerta(self):
        nombre = self.unidad_cerrable("con-confirmado")
        self.dejar_recibo(nombre, "confirmado")

        resultado = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).exists(), salida)

    def test_recibo_de_otra_unidad_no_sirve(self):
        nombre = self.unidad_cerrable("recibo-ajeno")
        self.dejar_recibo("999-otra-unidad-cualquiera", "confirmado")

        resultado = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn(f"validar {nombre}", salida)

    def test_recibo_confirmado_de_otro_dia_no_firma_esta_fecha(self):
        """Un `confirmado` de la semana pasada no acredita el OK de hoy."""
        nombre = self.unidad_cerrable("recibo-viejo")
        viejo = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        self.dejar_recibo(nombre, "confirmado", fecha=viejo)

        resultado = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn(f"validar {nombre}", salida)

    def test_confirmado_posterior_al_problema_desbloquea(self):
        """El usuario marcó «problema», se arregló y volvió a validar: eso sí cierra."""
        nombre = self.unidad_cerrable("revalidada")
        ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.dejar_recibo(nombre, "problema", fecha=ayer, comentario="no recalculaba")
        self.dejar_recibo(nombre, "confirmado")

        resultado = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)

    def test_sin_la_web_del_metodo_la_puerta_avisa_pero_no_bloquea(self):
        """Una puerta cuyo ejecutor no está en este workspace se dice, no se finge
        (ADR-029): sin `requisitos/web/` no hay recibo que pedir."""
        nombre = self.unidad_cerrable("sin-web")
        shutil.rmtree(self.web)

        resultado = self.ejecutar(self.unidad, "cerrar", nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("web del método", salida.lower())


if __name__ == "__main__":
    unittest.main()
