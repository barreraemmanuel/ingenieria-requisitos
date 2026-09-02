import contextlib
import importlib
import importlib.util
import io
import json
import datetime
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import ayuda_cierre  # noqa: E402 - módulo hermano de la suite
import ayuda_windows  # noqa: E402 - módulo hermano de la suite


RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
PLANTILLAS = RAIZ / "plantilla/docs/00-metodo/plantillas"
LINTER = SCRIPTS / "lint_metodo.py"
HOOK = RAIZ / "plantilla/githooks/pre-push"


class PeticionUnidadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="peticion-unidad-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)

        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        for nombre in (
            "control_plane.py", "entrega.py", "lease.py", "lint_cierre.py", "peticion.py",
            "repo_config.py", "subagente.py", "unidad.py", "veredicto_lint.py",
            "workspace_paths.py",
        ):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.peticion = scripts / "peticion.py"
        self.unidad = scripts / "unidad.py"
        # La tabla de señales de riesgo (unidad 070) viaja PEGADA a los scripts que la leen:
        # sin ella, la puerta del carril directo no tiene contra qué comparar.
        shutil.copy2(
            RAIZ / "plantilla/docs/00-metodo/senales-de-riesgo.json",
            self.ws / "docs/00-metodo/senales-de-riesgo.json",
        )

        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True)
        for nombre in (
            "especificacion.md",
            "directo.md",
            "bug.md",
            "hallazgos.md",
            "peticion-investigacion-plan.md",
            "peticion-investigacion-informe.md",
            "peticion-investigacion-sintesis.md",
        ):
            shutil.copy2(PLANTILLAS / nombre, plantillas / nombre)

        (self.ws / "docs/05-trabajo").mkdir(parents=True)
        (self.ws / "docs/bugs").mkdir(parents=True)
        (self.ws / ".worktrees").mkdir()
        self.repo = self.ws / "main"
        (self.repo / "app").mkdir(parents=True)
        (self.repo / "app/terminal.py").write_text("print('ok')\n", encoding="utf-8")
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=self.repo, check=True, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True
        )
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "base"], cwd=self.repo, check=True, capture_output=True
        )
        self.sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        conocimiento = self.ws / "docs/decisiones/004-paleta.md"
        conocimiento.parent.mkdir(parents=True)
        conocimiento.write_text("# Paleta vigente\n", encoding="utf-8")

    def ejecutar(self, script, *args):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.ws,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )

    def proceso_con_failpoint(self, nombre, *args, session_id):
        # Barrera por ficheros: los FDs no cruzan procesos en Windows (pass_fds
        # es POSIX). El hijo toca `ready` al llegar y espera a que exista `gate`.
        barrera = Path(tempfile.mkdtemp(prefix="barrera-"))
        self.addCleanup(shutil.rmtree, barrera, True)
        ready = barrera / "ready"
        gate = barrera / "gate"
        env = os.environ.copy()
        prefijo = f"IR_FAILPOINT_{nombre.upper()}"
        env[f"{prefijo}_READY_FILE"] = str(ready)
        env[f"{prefijo}_WAIT_FILE"] = str(gate)
        env["IR_SESSION_ID"] = session_id
        proceso = subprocess.Popen(
            [sys.executable, str(self.unidad), *args],
            cwd=self.ws,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        return proceso, ready, gate

    def esperar_barrera(self, ready, timeout=40):
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if ready.exists():
                return
            time.sleep(0.01)
        self.fail("el proceso no alcanzó el failpoint")

    def abrir_barrera(self, gate):
        gate.write_text("1", encoding="ascii")

    def capturar(self, resumen="Cambio solicitado"):
        resultado = self.ejecutar(
            self.peticion,
            "capturar",
            "--resumen",
            resumen,
            "--texto",
            "Implementa el cambio descrito",
            "--autor",
            "Nate",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        encontrado = re.search(r"P-\d{8}-[a-f0-9]{8}", resultado.stdout)
        self.assertIsNotNone(encontrado, resultado.stdout)
        return encontrado.group(0)

    def evaluar(self, pid, perfil="ninguna", ruta="feature"):
        args = [
            "evaluar",
            pid,
            "--ruta",
            ruta,
            "--investigacion",
            perfil,
            "--motivo",
            "contraste suficiente para encaminar",
            "--flujo",
            "REC-1",
            "--huella-flujo",
            "planos-v1",
            "--sha",
            self.sha,
            "--ruta-codigo",
            "app/terminal.py",
            "--conocimiento",
            "docs/decisiones/004-paleta.md",
        ]
        if perfil != "ninguna":
            args.extend(("--disparador", "incertidumbre", "--pregunta", "¿qué cambia?"))
        resultado = self.ejecutar(self.peticion, *args)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def preparar_hotfix(self, slug, ficheros=None):
        pid = self.capturar(f"Hotfix {slug}")
        self.evaluar(pid, ruta="bug")
        creada = self.ejecutar(
            self.unidad, "nueva", "bug", slug, "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        ficha = next((self.ws / "docs/bugs").glob(f"[0-9][0-9][0-9]-{slug}.md"))
        texto = ficha.read_text(encoding="utf-8").replace(
            "P0 (producción caída) … P4 (cosmético)",
            "P0 (producción caída)",
        )
        if ficheros:
            texto = texto.replace("ficheros: []", f"ficheros: [{', '.join(ficheros)}]")
        ficha.write_text(texto, encoding="utf-8")
        return ficha.stem

    def dejar_rastro_visor_contratos(self, nombre, fecha=None, con_web=True):
        """Lo que `visor_contratos/servir.py` anota por contrato mostrado (R2, bug 054):
        estos fixtures aprueban a mano, así que dejan también el rastro que la puerta 3
        de `despachar` exige (R3) — sin él, `despachar` bloquearía un fixture legítimo.

        Desde la unidad 107 hay una puerta MÁS (R5): una fecha en `aprobado:` sin rastro
        de que el clic viniera de la web ya no vale. La aprobación de verdad deja los DOS
        rastros a la vez —el visor mostró el contrato y el usuario pulsó Aprobar—, así
        que el fixture deja los dos. `con_web=False` reproduce la fecha tecleada."""
        fecha = fecha or datetime.date.today().isoformat()
        registro = self.ws / ".runtime" / "visor-contratos.log"
        registro.parent.mkdir(parents=True, exist_ok=True)
        with open(registro, "a", encoding="utf-8") as rastro:
            rastro.write(f"{fecha}T00:00:00 contrato mostrado: {nombre}\n")
        if con_web:
            self.dejar_rastro_aprobacion_web(nombre, fecha)

    def dejar_rastro_aprobacion_web(self, nombre, fecha=None):
        """Lo que `web/servir.py` escribe cuando el usuario pulsa Aprobar (unidad 107):
        `.runtime/aprobaciones/<unidad>-<fecha>.json` con ruta, huella, hora y cliente."""
        fecha = fecha or datetime.date.today().isoformat()
        carpeta = self.ws / ".runtime" / "aprobaciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{nombre}-{fecha}.json").write_text(json.dumps({
            "unidad": nombre, "fecha": fecha, "ruta": f"docs/05-trabajo/{nombre}",
            "huella": "0" * 64, "hora": f"{fecha}T00:00:00", "cliente": "127.0.0.1",
        }), encoding="utf-8")

    def aprobar_para_despacho(self, nombre, nivel=None):
        nivel = nivel or "unitario, porque la conducta es una regla local."
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        texto = ruta.read_text(encoding="utf-8")
        texto = re.sub(
            r"^aprobado:.*$",
            f"aprobado: {datetime.date.today().isoformat()}",
            texto,
            count=1,
            flags=re.M,
        )
        self.dejar_rastro_visor_contratos(nombre)
        cierre = texto.find("---", 4)
        cabecera = texto[:cierre + 3]
        cuerpo = (
            "\n\n# Contrato aprobado\n\n"
            "El usuario podrá completar el cambio solicitado sin alterar el comportamiento "
            "adyacente. La implementación conservará los datos existentes y mostrará un "
            "resultado verificable en la misma entrada que usa hoy. Los errores se mostrarán "
            "sin perder el trabajo y el caso límite permanecerá estable.\n\n"
            "## Criterios de aceptación\n\n"
            "- R1: el resultado solicitado aparece con un ejemplo real.\n"
            "- R2: el caso límite no cambia los datos existentes.\n\n"
            "## Verificación\n\n"
            f"- **Nivel de test:** {nivel}\n"
            "- **Criterio portante:** R1 — sin él la unidad entera no sirve de nada.\n"
        )
        ruta.write_text(cabecera + cuerpo, encoding="utf-8")
        return ruta

    def preparar_feature_aprobada(self, slug):
        pid = self.capturar(f"Preparar {slug}")
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", slug, "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = f"001-{slug}"
        self.aprobar_para_despacho(nombre)
        return nombre

    def recibos_de_revision(self, nombre):
        """Recibos del control plane como los que deja `ejecucion.py` al delegar.

        Desde la unidad 033 el cierre los LEE: la firma del revisor sin recibo propio no
        acredita nada. Un cierre en verde necesita, por tanto, haber pasado por aquí.
        """
        carpeta = self.ws / ".runtime/ejecuciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        ficha = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        documental = ficha.is_file() and "ejecucion: documental" in ficha.read_text(
            encoding="utf-8")
        worktree = self.ws / "worktrees" / nombre
        repo_entrega = worktree if worktree.is_dir() else self.repo
        final = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_entrega, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        entrega_git = None
        if not documental:
            inicial = subprocess.run(
                ["git", "rev-parse", f"{final}^"], cwd=self.repo, check=True,
                text=True, encoding="utf-8", errors="replace", capture_output=True,
            ).stdout.strip()
            arbol_inicial = subprocess.run(
                ["git", "rev-parse", f"{inicial}^{{tree}}"], cwd=self.repo, check=True,
                text=True, encoding="utf-8", errors="replace", capture_output=True,
            ).stdout.strip()
            arbol_final = subprocess.run(
                ["git", "rev-parse", f"{final}^{{tree}}"], cwd=self.repo, check=True,
                text=True, encoding="utf-8", errors="replace", capture_output=True,
            ).stdout.strip()
            entrega_git = {
                "inicial": {"head": inicial, "tree": arbol_inicial,
                            "plan": {"marcadas": 0, "totales": 1}},
                "final": {"head": final, "tree": arbol_final,
                          "status_porcelain": [], "materializada": False},
            }
        for rol, sesion in (("constructor", "sesion-constructor"), ("revisor", "sesion-revisor")):
            recibo = {
                "schema": "ejecucion/v1", "id": rol, "unidad": nombre,
                "harness": ("subagente-del-padre" if rol == "constructor" else "claude"),
                "rol": rol, "modelo": f"modelo-{rol}",
                "lease": {"session_id": sesion, "fencing": {}},
                "checkpoints": [], "exit_code": 0, "resultado": "ok",
            }
            if rol == "constructor" and entrega_git is not None:
                recibo["git"] = entrega_git
                recibo["trabajo"] = {
                    "acreditado": True, "plan": {"marcadas": 1, "totales": 1}}
            (carpeta / f"{nombre}-{rol}.json").write_text(
                json.dumps(recibo), encoding="utf-8")

    def recibo_preparacion(self, nombre):
        ruta = self.ws / ".runtime/worktree-readiness" / f"{nombre}.json"
        self.assertTrue(ruta.is_file(), f"falta recibo de preparación: {ruta}")
        return json.loads(ruta.read_text(encoding="utf-8"))

    def test_no_crea_unidad_sin_peticion_de_origen(self):
        resultado = self.ejecutar(self.unidad, "nueva", "feature", "sin-origen")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("petici", resultado.stderr.lower())
        self.assertFalse((self.ws / "docs/05-trabajo/001-sin-origen").exists())

    def test_crea_unidad_con_peticion_evaluada_y_revision_fijada(self):
        pid = self.capturar()
        self.evaluar(pid)

        resultado = self.ejecutar(
            self.unidad, "nueva", "feature", "con-origen", "--desde", pid
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        contrato = (self.ws / "docs/05-trabajo/001-con-origen/especificacion.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"peticiones: [{pid}@1]", contrato)
        datos = json.loads(
            (
                self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(datos["estado"], "encaminada")
        self.assertEqual(datos["procesos"][-1]["ref"], "001-con-origen")

    def test_dos_procesos_serializan_numeracion_y_creacion(self):
        primera = self.capturar("Primera concurrente")
        segunda = self.capturar("Segunda concurrente")
        self.evaluar(primera)
        self.evaluar(segunda)
        args_a = ("nueva", "feature", "concurrente-a", "--desde", primera)
        args_b = ("nueva", "feature", "concurrente-b", "--desde", segunda)

        proceso_a, ready_a, gate_a = self.proceso_con_failpoint(
            "nueva_tras_nnn", *args_a, session_id="sesion-a"
        )
        self.addCleanup(lambda: proceso_a.poll() is None and proceso_a.kill())
        self.esperar_barrera(ready_a)
        proceso_b, ready_b, gate_b = self.proceso_con_failpoint(
            "nueva_tras_nnn", *args_b, session_id="sesion-b"
        )
        self.addCleanup(lambda: proceso_b.poll() is None and proceso_b.kill())

        salida_b, error_b = proceso_b.communicate(timeout=3)
        self.assertFalse(
            ready_b.exists(),
            "el segundo proceso atravesó numeración mientras el primero conservaba el lease",
        )
        self.assertEqual(proceso_b.returncode, 1, salida_b + error_b)
        self.assertIn("numerar otra unidad", error_b)
        self.abrir_barrera(gate_a)
        salida_a, error_a = proceso_a.communicate(timeout=3)
        self.assertEqual(proceso_a.returncode, 0, salida_a + error_a)
        reintento = self.ejecutar(self.unidad, *args_b)
        self.assertEqual(reintento.returncode, 0, reintento.stdout + reintento.stderr)
        creadas = sorted(
            path.name
            for path in (self.ws / "docs/05-trabajo").glob("[0-9][0-9][0-9]-*")
        )
        self.assertEqual(creadas, ["001-concurrente-a", "002-concurrente-b"])

    def test_doble_despacho_solo_permite_un_propietario(self):
        nombre = self.preparar_hotfix("despacho-concurrente")
        args = (
            "despachar",
            nombre,
            "--force",
            "--motivo",
            "producción caída durante la prueba concurrente",
        )

        proceso_a, ready_a, gate_a = self.proceso_con_failpoint(
            "despachar_antes_accion", *args, session_id="sesion-a"
        )
        self.addCleanup(lambda: proceso_a.poll() is None and proceso_a.kill())
        self.esperar_barrera(ready_a)
        proceso_b, ready_b, gate_b = self.proceso_con_failpoint(
            "despachar_antes_accion", *args, session_id="sesion-b"
        )
        self.addCleanup(lambda: proceso_b.poll() is None and proceso_b.kill())
        salida_b, error_b = proceso_b.communicate(timeout=3)
        self.assertFalse(
            ready_b.exists(),
            "el segundo proceso atravesó el failpoint con el lease del primero vivo",
        )

        self.assertEqual(proceso_b.returncode, 1, salida_b + error_b)
        self.assertIn("propietario", error_b.lower())
        self.abrir_barrera(gate_a)
        salida_a, error_a = proceso_a.communicate(timeout=5)
        self.assertEqual(proceso_a.returncode, 0, salida_a + error_a)
        self.assertTrue((self.ws / "worktrees" / nombre).is_dir())
        self.assertEqual(
            subprocess.run(
                ["git", "branch", "--list", nombre],
                cwd=self.repo,
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
                check=True,
            ).stdout.count(nombre),
            1,
        )

    def test_despachos_distintos_no_comparten_recurso(self):
        primero = self.preparar_hotfix("recurso-a", ["app/terminal.py"])
        segundo = self.preparar_hotfix("recurso-b", ["app/terminal.py"])
        args_a = (
            "despachar", primero, "--force", "--motivo", "producción caída A"
        )
        args_b = (
            "despachar", segundo, "--force", "--motivo", "producción caída B"
        )

        proceso_a, ready_a, gate_a = self.proceso_con_failpoint(
            "despachar_antes_accion", *args_a, session_id="sesion-a"
        )
        self.addCleanup(lambda: proceso_a.poll() is None and proceso_a.kill())
        self.esperar_barrera(ready_a)
        proceso_b, ready_b, gate_b = self.proceso_con_failpoint(
            "despachar_antes_accion", *args_b, session_id="sesion-b"
        )
        self.addCleanup(lambda: proceso_b.poll() is None and proceso_b.kill())
        salida_b, error_b = proceso_b.communicate(timeout=3)
        self.assertFalse(
            ready_b.exists(),
            "el segundo proceso atravesó el failpoint con el lease del primero vivo",
        )

        self.assertEqual(proceso_b.returncode, 1, salida_b + error_b)
        self.assertIn("resource:app/terminal.py", error_b)
        self.abrir_barrera(gate_a)
        salida_a, error_a = proceso_a.communicate(timeout=5)
        self.assertEqual(proceso_a.returncode, 0, salida_a + error_a)

    def test_despachar_detecta_cambio_de_recursos_tras_adquirir_lease(self):
        primero = self.preparar_hotfix("toctou-a", ["app/a.py"])
        segundo = self.preparar_hotfix("toctou-b", ["app/compartido.py"])
        args_a = (
            "despachar", primero, "--force", "--motivo", "producción caída A"
        )
        args_b = (
            "despachar", segundo, "--force", "--motivo", "producción caída B"
        )
        proceso_a, ready_a, gate_a = self.proceso_con_failpoint(
            "despachar_antes_accion", *args_a, session_id="sesion-a"
        )
        self.addCleanup(lambda: proceso_a.poll() is None and proceso_a.kill())
        self.esperar_barrera(ready_a)
        ficha_a = self.ws / "docs/bugs" / f"{primero}.md"
        ficha_a.write_text(
            ficha_a.read_text(encoding="utf-8").replace(
                "app/a.py", "app/compartido.py"
            ),
            encoding="utf-8",
        )
        proceso_b, ready_b, gate_b = self.proceso_con_failpoint(
            "despachar_antes_accion", *args_b, session_id="sesion-b"
        )
        self.addCleanup(lambda: proceso_b.poll() is None and proceso_b.kill())
        self.esperar_barrera(ready_b)

        self.abrir_barrera(gate_a)
        salida_a, error_a = proceso_a.communicate(timeout=5)
        self.abrir_barrera(gate_b)
        salida_b, error_b = proceso_b.communicate(timeout=5)

        self.assertEqual(proceso_a.returncode, 1, salida_a + error_a)
        self.assertIn("cambió", (salida_a + error_a).lower())
        self.assertFalse((self.ws / "worktrees" / primero).exists())
        self.assertEqual(proceso_b.returncode, 0, salida_b + error_b)

    def sembrar_lease_huerfano(self, scope):
        """Deja en el workspace un lease a nombre de un proceso que YA NO EXISTE.

        Es exactamente el rastro que deja un `kill -9` (o el cierre de golpe de la
        terminal) sobre `ejecucion.py lanzar`: nadie corrió ningún manejador, así que el
        lease sigue ahí con el PID de un muerto. Se siembra desde un proceso aparte que
        termina, para que el PID sea real y esté realmente muerto."""
        difunto = subprocess.Popen([sys.executable, "-c", "pass"])
        difunto.wait()
        scripts = self.ws / "docs/00-metodo/scripts"
        codigo = (
            "import sys\n"
            f"sys.path.insert(0, {str(scripts)!r})\n"
            "import lease\n"
            f"lease.LeaseManager({str(self.ws)!r}, session_id='sesion-muerta', "
            f"pid={difunto.pid}, process_started='ps:una-sesion-que-ya-no-esta')"
            f".acquire({scope!r})\n"
        )
        sembrado = subprocess.run(
            [sys.executable, "-c", codigo], cwd=self.ws, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertEqual(sembrado.returncode, 0, sembrado.stdout + sembrado.stderr)
        activos = sorted((self.ws / ".runtime/leases/active").glob("*.json"))
        self.assertEqual(len(activos), 1, activos)
        return activos[0]

    def test_despachar_no_se_lleva_por_delante_un_lanzamiento_interrumpido(self):
        # Bug 077 · R2, hueco del revisor: `lanzar` ya paraba ante un lease de dueño
        # muerto, pero `despachar` —la otra puerta a la misma unidad— seguía adquiriendo
        # encima. `acquire` retira ese lease POR EL CAMINO, así que el rastro del
        # lanzamiento interrumpido desaparecía en silencio y con él la única pista de que
        # podía quedar un harness huérfano escribiendo en el worktree y la ficha en 0444.
        nombre = self.preparar_hotfix("lanzamiento-interrumpido")
        lease = self.sembrar_lease_huerfano(f"unit:{nombre}")

        resultado = self.ejecutar(
            self.unidad, "despachar", nombre, "--force", "--motivo", "producción caída",
        )

        traza = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, traza)
        self.assertIn("INTERRUMPIDO", traza)
        self.assertIn(f"desbloquear {nombre}", traza,
                      f"el rechazo no nombra el comando que lo deshace · {traza}")
        self.assertTrue(
            lease.exists(),
            "despachar se llevó por delante el lease del lanzamiento interrumpido",
        )
        self.assertFalse((self.ws / "worktrees" / nombre).exists())

    def test_unidad_y_peticion_rechazan_ruta_local_absoluta(self):
        pid = self.capturar("Cambio exprés")
        self.evaluar(pid, ruta="expres")
        (self.ws / "repos.yaml").write_text(
            f"codigo:\n  ruta_local: {self.repo}\n  rama_principal: main\n",
            encoding="utf-8",
        )
        estado = self.ejecutar(self.unidad, "estado")
        expres = self.ejecutar(self.peticion, "abrir-expres", pid, "ruta-insegura")

        self.assertEqual(estado.returncode, 1, estado.stdout + estado.stderr)
        self.assertIn("ruta_local", (estado.stdout + estado.stderr).lower())
        self.assertEqual(expres.returncode, 1, expres.stdout + expres.stderr)
        self.assertIn("ruta_local", (expres.stdout + expres.stderr).lower())

    def test_unidad_rechaza_push_invalido_en_repos_yaml(self):
        """Unidad 018: `push:` se valida en la misma lectura que `ruta_local`/`rama_principal`;
        un valor que nadie entiende no arranca comandos con una política a medias."""
        (self.ws / "repos.yaml").write_text(
            "codigo:\n  ruta_local: main/\n  rama_principal: main\n  push: banana\n",
            encoding="utf-8",
        )

        estado = self.ejecutar(self.unidad, "estado")

        salida = estado.stdout + estado.stderr
        self.assertEqual(estado.returncode, 1, salida)
        self.assertIn("push", salida)
        self.assertIn("agente | usuario", salida)

    def test_sin_clave_push_el_estado_funciona_como_hoy(self):
        """R3: el repos.yaml de siempre (sin `push:`) no cambia de comportamiento."""
        (self.ws / "repos.yaml").write_text(
            "codigo:\n  ruta_local: main/\n  rama_principal: main\n", encoding="utf-8",
        )

        estado = self.ejecutar(self.unidad, "estado")

        self.assertEqual(estado.returncode, 0, estado.stdout + estado.stderr)

    def test_unidad_no_sigue_symlink_de_ficha_bug(self):
        nombre = self.preparar_hotfix("ficha-symlink")
        ficha = self.ws / "docs/bugs" / f"{nombre}.md"
        exterior = self.ws / ".ficha-bug-exterior.md"
        contenido = ficha.read_bytes()
        exterior.write_bytes(contenido)
        ficha.unlink()
        ayuda_windows.enlazar_o_saltar(self, ficha, exterior)

        resultado = self.ejecutar(
            self.unidad, "despachar", nombre, "--force",
            "--motivo", "producción caída",
        )

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("symlink", (resultado.stdout + resultado.stderr).lower())
        self.assertEqual(exterior.read_bytes(), contenido)
        self.assertFalse((self.ws / "worktrees" / nombre).exists())

    def test_unidad_no_sigue_ancestro_symlink_de_especificacion(self):
        pid = self.capturar("Ficha con ancestro alterado")
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "ancestro-symlink", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = "001-ancestro-symlink"
        ficha = self.aprobar_para_despacho(nombre)
        contenido = ficha.read_bytes()
        exterior = self.ws / ".ficha-exterior" / nombre
        exterior.parent.mkdir()
        shutil.move(str(ficha.parent), str(exterior))
        ayuda_windows.enlazar_o_saltar(self, ficha.parent, exterior, directorio=True)

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("symlink", (resultado.stdout + resultado.stderr).lower())
        self.assertEqual((exterior / "especificacion.md").read_bytes(), contenido)
        self.assertFalse((self.ws / "worktrees" / nombre).exists())

    def test_carril_directo_rechaza_investigacion_acotada(self):
        pid = self.capturar()
        self.evaluar(pid, "acotada", ruta="directo")

        resultado = self.ejecutar(
            self.unidad,
            "nueva",
            "feature",
            "demasiado-incierto",
            "--directo",
            "--desde",
            pid,
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("directo", resultado.stderr.lower())
        self.assertFalse((self.ws / "docs/05-trabajo/001-demasiado-incierto").exists())

    def test_ruta_directo_documentada_crea_unidad_feature_directa(self):
        pid = self.capturar()
        self.evaluar(pid, ruta="directo")

        resultado = self.ejecutar(
            self.unidad,
            "nueva",
            "feature",
            "ajuste-directo",
            "--directo",
            "--desde",
            pid,
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        texto = (
            self.ws / "docs/05-trabajo/001-ajuste-directo/especificacion.md"
        ).read_text(encoding="utf-8")
        self.assertIn("carril: directo", texto)

    def test_una_orden_puede_satisfacer_varias_peticiones(self):
        primera = self.capturar("Primera petición")
        segunda = self.capturar("Segunda petición")
        self.evaluar(primera, ruta="refactor")
        self.evaluar(segunda, ruta="refactor")

        resultado = self.ejecutar(
            self.unidad,
            "nueva",
            "refactor",
            "cambio-compuesto",
            "--desde",
            primera,
            "--desde",
            segunda,
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        contrato = (
            self.ws / "docs/05-trabajo/001-cambio-compuesto/especificacion.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"peticiones: [{primera}@1, {segunda}@1]", contrato)

    def test_fallo_al_enlazar_varias_peticiones_no_deja_media_orden(self):
        primera = self.capturar("Primera petición")
        segunda = self.capturar("Segunda petición")
        self.evaluar(primera, ruta="refactor")
        self.evaluar(segunda, ruta="refactor")
        bloqueada = min(primera, segunda)
        lock = self.ws / ".runtime/locks" / f"peticion-{bloqueada}.lock"
        lock.mkdir(parents=True)

        resultado = self.ejecutar(
            self.unidad,
            "nueva",
            "refactor",
            "cambio-atomico",
            "--desde",
            primera,
            "--desde",
            segunda,
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("modificada por otra sesión", resultado.stderr)
        self.assertFalse(
            (self.ws / "docs/05-trabajo/001-cambio-atomico").exists(),
            "una orden que no pudo enlazarse completa debe retirarse",
        )
        for pid in (primera, segunda):
            datos = json.loads(
                (
                    self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(datos["procesos"], [], pid)

    def test_bug_conserva_la_peticion_de_origen(self):
        pid = self.capturar("Defecto observado")
        self.evaluar(pid, ruta="bug")

        resultado = self.ejecutar(
            self.unidad, "nueva", "bug", "falla-visible", "--desde", pid
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        ficha = (self.ws / "docs/bugs/001-falla-visible.md").read_text(encoding="utf-8")
        self.assertIn(f"peticiones: [{pid}@1]", ficha)
        datos = json.loads(
            (
                self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(datos["procesos"][-1]["tipo"], "bug")

    def test_tipo_de_unidad_distinto_de_la_ruta_evaluada_falla(self):
        pid = self.capturar()
        self.evaluar(pid, ruta="feature")

        resultado = self.ejecutar(
            self.unidad, "nueva", "refactor", "ruta-distinta", "--desde", pid
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("ruta", resultado.stderr.lower())
        self.assertFalse((self.ws / "docs/05-trabajo/001-ruta-distinta").exists())

    def preparar_bug_aprobado(self, slug, ficheros):
        nombre = self.preparar_hotfix(slug, ficheros=ficheros)
        ficha = self.ws / "docs/bugs" / f"{nombre}.md"
        texto = ficha.read_text(encoding="utf-8")
        texto = re.sub(
            r"^aprobado:.*$",
            f"aprobado: {datetime.date.today().isoformat()}",
            texto,
            count=1,
            flags=re.M,
        )
        # Bug 120: la ficha de un bug lleva título; con el de la plantilla ya no se despacha.
        texto = texto.replace("<síntoma en una frase>", "el runbook cuenta el orden antiguo", 1)
        texto += (
            "\n## Reporte\n\n"
            "El usuario esperaba que el runbook del carril corto describiera el paso de "
            "cierre tal y como lo ejecuta el script, pero el documento sigue contando el "
            "orden antiguo y el agente que lo siguió dejó la unidad a medio cerrar. Pasa "
            "siempre que se llega al paso seis con la sesión recién abierta. Severidad P2: "
            "no rompe datos, pero cada sesión nueva tropieza igual. Triaje: corregir el "
            "texto del runbook y contrastarlo con el script de cierre real.\n"
        )
        ficha.write_text(texto, encoding="utf-8")
        self.dejar_rastro_visor_contratos(nombre)
        return nombre

    def test_documental_en_vuelo_no_consume_cupo_de_constructor(self):
        """Caso de campo (05-08): el tope de vuelo contaba una auditoría
        documental aparcada y bloqueaba el despacho de constructores. La regla 5 exime
        a las --documental («leen, no escriben código: pueden ir en paralelo»)."""
        doc = self.preparar_bug_aprobado(
            "auditoria-aparcada", ficheros=["docs/00-metodo/runbooks/bug.md"]
        )
        despacho_doc = self.ejecutar(self.unidad, "despachar", doc, "--documental")
        self.assertEqual(despacho_doc.returncode, 0,
                         despacho_doc.stdout + despacho_doc.stderr)

        pid = self.capturar("Cambio normal")
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "cambio-normal", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = next(
            p.name for p in (self.ws / "docs/05-trabajo").iterdir()
            if p.name.endswith("-cambio-normal")
        )
        self.aprobar_para_despacho(nombre)

        # Sin --paralelo: la documental en vuelo no debe contar como unidad en obra.
        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("en vuelo", resultado.stderr)

    def preparar_unidad_en_vuelo(self, numero, ficheros):
        """Unidad ya `en_obra` con `ficheros:` declarados, sin pasar por despacho real:
        censo() solo mira el frontmatter, así que basta con escribirlo directamente para
        simular varias unidades en vuelo a la vez (ADR-027, R2/R3)."""
        nombre = f"{numero:03d}-en-vuelo-{numero}"
        carpeta = self.ws / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            "---\n"
            f"unidad: {nombre}\n"
            "tipo: feature\n"
            "carril: normal\n"
            "estado: en_obra\n"
            "aprobado: 2026-08-04\n"
            "actividad: REC-1\n"
            f"ficheros: [{', '.join(ficheros)}]\n"
            "peticiones: []\n"
            "actualizado: 2026-08-04\n"
            "---\n\n# Contrato\n",
            encoding="utf-8",
        )
        return nombre

    def test_cuarta_unidad_disjunta_con_paralelo_despacha_sin_tope_numerico(self):
        """ADR-027, R2: con 3 unidades ya en vuelo y ficheros disjuntos, una cuarta
        también disjunta con --paralelo despacha igual — se retira TOPE_EN_VUELO, el
        único gate real es la disjunción de ficheros."""
        for numero, fichero in enumerate(("app/uno.py", "app/dos.py", "app/tres.py"), start=1):
            self.preparar_unidad_en_vuelo(numero, [fichero])

        pid = self.capturar("Cuarta unidad")
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "cuarta-disjunta", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = next(
            p.name for p in (self.ws / "docs/05-trabajo").iterdir()
            if p.name.endswith("-cuarta-disjunta")
        )
        ruta = self.aprobar_para_despacho(nombre)
        texto = ruta.read_text(encoding="utf-8").replace(
            "ficheros: []", "ficheros: [app/cuatro.py]"
        )
        ruta.write_text(texto, encoding="utf-8")

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--paralelo")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("tope absoluto", (resultado.stdout + resultado.stderr).lower())

    def test_fichero_compartido_sigue_bloqueando_con_paralelo(self):
        """ADR-027, R3 (caso límite): retirar el tope numérico NO relaja la disjunción
        de ficheros — dos unidades que declaran el mismo fichero siguen bloqueadas."""
        self.preparar_unidad_en_vuelo(1, ["app/terminal.py"])

        pid = self.capturar("Choca fichero")
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "choca-fichero", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = next(
            p.name for p in (self.ws / "docs/05-trabajo").iterdir()
            if p.name.endswith("-choca-fichero")
        )
        ruta = self.aprobar_para_despacho(nombre)
        texto = ruta.read_text(encoding="utf-8").replace(
            "ficheros: []", "ficheros: [app/terminal.py]"
        )
        ruta.write_text(texto, encoding="utf-8")

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--paralelo")

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("comparten ficheros declarados", resultado.stderr)
        self.assertIn("app/terminal.py", resultado.stderr)

    # ------------------------------------------------------------------ 099 · ADR-036
    def test_despacho_en_paralelo_por_defecto_sin_pedir_ningun_flag(self):
        """099 R1 (criterio portante): con tres unidades en vuelo y ficheros disjuntos,
        la cuarta despacha SIN flags. El paralelismo deja de ser la excepción que hay
        que recordar y pasa a ser el defecto (ADR-036)."""
        for numero, fichero in enumerate(("app/uno.py", "app/dos.py", "app/tres.py"), start=1):
            self.preparar_unidad_en_vuelo(numero, [fichero])
        nombre = self.preparar_con_ficheros("cuarta-por-defecto", ["app/cuatro.py"])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertNotIn("--paralelo", salida)
        self.assertIn("ficheros disjuntos", salida)

    def test_flag_paralelo_se_acepta_y_avisa_de_que_ya_es_el_defecto(self):
        """099 R1: `--paralelo` sigue en los runbooks y en las sesiones abiertas, así que
        no puede reventar el despacho: se acepta y se dice que ya no hace falta."""
        self.preparar_unidad_en_vuelo(1, ["app/uno.py"])
        nombre = self.preparar_con_ficheros("acepta-paralelo", ["app/dos.py"])

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--paralelo")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("ya es el defecto", salida)

    def test_serie_bloquea_cuando_hay_otra_unidad_en_vuelo(self):
        """099 R1: `--serie` es la excepción — pide explícitamente ir de uno en uno, así
        que con trabajo en vuelo bloquea, y el bloqueo dice por dónde se sale."""
        self.preparar_unidad_en_vuelo(1, ["app/uno.py"])
        nombre = self.preparar_con_ficheros("pide-serie", ["app/dos.py"])

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--serie")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("001-en-vuelo-1", salida)
        self.assertIn("SALIDA:", salida)

    def test_serie_deja_escrito_paralelo_no_en_el_registro_de_despacho(self):
        """099 R1: la excepción deja rastro del lado de quien despacha, no en el
        frontmatter que teclea el constructor."""
        pid = self.capturar("Va en serie")
        self.evaluar(pid)
        creada = self.ejecutar(self.unidad, "nueva", "feature", "sola-en-serie", "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = next(
            p.name for p in (self.ws / "docs/05-trabajo").iterdir()
            if p.name.endswith("-sola-en-serie")
        )
        ruta = self.aprobar_para_despacho(nombre)
        ruta.write_text(
            ruta.read_text(encoding="utf-8").replace(
                "ficheros: []", "ficheros: [app/terminal.py]"),
            encoding="utf-8",
        )

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--serie")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        datos = json.loads(
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json")
            .read_text(encoding="utf-8")
        )
        procesos = [p for p in datos["procesos"] if p.get("ref") == nombre]
        self.assertTrue(procesos, datos)
        self.assertEqual((procesos[0].get("metadata") or {}).get("paralelo"), "no", procesos)

    def test_fichero_compartido_bloquea_tambien_sin_flags(self):
        """099 R2: el defecto en paralelo NO relaja el cruce de `ficheros:` — sigue
        bloqueando, y nombra la otra unidad y el fichero compartido."""
        self.preparar_unidad_en_vuelo(1, ["app/terminal.py"])
        nombre = self.preparar_con_ficheros("choca-sin-flags", ["app/terminal.py"])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("comparten ficheros declarados", salida)
        self.assertIn("001-en-vuelo-1", salida)
        self.assertIn("app/terminal.py", salida)
        self.assertIn("SALIDA:", salida)

    def preparar_con_ficheros(self, slug, ficheros, nivel=None):
        """Unidad feature aprobada, con `ficheros:` escritos tal cual y el nivel de test
        que pida el caso. Es el fixture de la unidad 089: lo que se contrasta contra el
        disco y contra el plan de tests es exactamente esa lista."""
        pid = self.capturar(f"Preparar {slug}")
        self.evaluar(pid)
        creada = self.ejecutar(self.unidad, "nueva", "feature", slug, "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = next(
            p.name for p in (self.ws / "docs/05-trabajo").iterdir()
            if p.name.endswith(f"-{slug}")
        )
        ruta = self.aprobar_para_despacho(nombre, nivel=nivel)
        texto = ruta.read_text(encoding="utf-8").replace(
            "ficheros: []", f"ficheros: [{', '.join(ficheros)}]"
        )
        ruta.write_text(texto, encoding="utf-8")
        return nombre

    def test_fichero_declarado_sin_carpeta_madre_bloquea_el_despacho(self):
        """089 R1: `ficheros:` con una ruta que no existe y cuya carpeta madre tampoco,
        es una omisión del contrato que hoy solo se descubría en la revisión."""
        nombre = self.preparar_con_ficheros("ruta-huerfana", ["app/no_existe/x.py"])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("app/no_existe/x.py", salida)
        self.assertIn("SALIDA:", salida)

    def test_fichero_nuevo_bajo_carpeta_existente_despacha_con_informacion(self):
        """089 R1 (el otro lado): una ruta que aún no existe pero cuya carpeta madre sí
        es lo normal al crear un módulo — pasa, y se dice."""
        nombre = self.preparar_con_ficheros("ruta-nueva", ["app/nuevo.py"])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("ruta nueva", salida)
        self.assertIn("app/nuevo.py", salida)

    def test_ruta_marcada_como_nueva_no_necesita_carpeta_madre(self):
        """089 R1: la salida que ofrece el bloqueo tiene que existir de verdad —
        `nuevo:` delante declara que la carpeta la crea esta unidad."""
        nombre = self.preparar_con_ficheros("carpeta-nueva", ["nuevo:app/modulo/x.py"])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("app/modulo/x.py", salida)

    def test_nivel_de_integracion_sin_carpeta_de_tests_bloquea(self):
        """089 R2: si la Verificación pide integración/E2E, la carpeta de tests que va a
        crecer es parte de lo que la unidad POSEE; si no está, dos unidades en paralelo
        escriben en el mismo fichero de tests sin que nada lo vea."""
        nombre = self.preparar_con_ficheros(
            "integracion-sin-tests",
            ["app/terminal.py"],
            nivel="de integración, porque cruza la frontera del repo de código.",
        )

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("SALIDA:", salida)
        self.assertIn("tests", salida.lower())

    def test_nivel_de_integracion_con_carpeta_de_tests_despacha(self):
        """089 R2 (el otro lado): declarada la carpeta de tests, el despacho sigue."""
        (self.repo / "app/tests").mkdir(parents=True)
        (self.repo / "app/tests/test_base.py").write_text("", encoding="utf-8")
        nombre = self.preparar_con_ficheros(
            "integracion-con-tests",
            ["app/terminal.py", "app/tests/test_terminal.py"],
            nivel="de integración, porque cruza la frontera del repo de código.",
        )

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)

    def test_integracion_con_ficheros_vacios_tambien_bloquea(self):
        """H1 del revisor de la 089 (R2): con `ficheros: []` el bloqueo se saltaba, y ese
        es justo el contrato que MÁS lo necesita — no declara nada y va a escribir tests
        de integración donde le parezca."""
        nombre = self.preparar_feature_aprobada("integracion-sin-ficheros")
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        self.assertIn("ficheros: []", ruta.read_text(encoding="utf-8"))
        self.aprobar_para_despacho(
            nombre, nivel="de integración, porque cruza la frontera del repo de código."
        )

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("SALIDA:", salida)
        self.assertIn("tests", salida.lower())

    def test_documental_no_se_cruza_contra_el_disco_del_repo_de_codigo(self):
        """089 R2 (caso límite): una unidad --documental no toca código, así que ni sus
        rutas se buscan en main/ ni se le exige carpeta de tests."""
        nombre = self.preparar_bug_aprobado(
            "solo-meta", ["docs/00-metodo/README.md", "docs/no_existe_aun/x.md"]
        )

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--documental")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)

    def test_bug_evaluado_directo_se_crea_por_carril_directo(self):
        """Incidente de campo (P1, 06-08): la evaluación aceptó ruta
        'directo' para un bug y la creación exigía ruta 'bug' — imposible complacer
        a las dos validaciones. Un bug evaluado como directo se crea con --directo."""
        pid = self.capturar("El launcher no arranca Codex")
        self.evaluar(pid, ruta="directo")

        creada = self.ejecutar(
            self.unidad, "nueva", "bug", "launcher-no-arranca", "--directo",
            "--desde", pid,
        )

        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)

    def test_bug_del_meta_repo_se_despacha_documental_sin_worktree(self):
        nombre = self.preparar_bug_aprobado(
            "runbook-roto", ficheros=["docs/00-metodo/runbooks/bug.md"]
        )

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--documental")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse((self.ws / "worktrees" / nombre).exists())
        ficha = (self.ws / "docs/bugs" / f"{nombre}.md").read_text(encoding="utf-8")
        self.assertIn("ejecucion: documental", ficha)

    def test_bug_que_toca_main_no_puede_ir_documental(self):
        nombre = self.preparar_bug_aprobado(
            "toca-codigo", ficheros=["docs/bugs/INDICE.md", "main/app/x.py"]
        )

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--documental")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("main/app/x.py", resultado.stderr)
        self.assertIn("se despacha normal", resultado.stderr)

    def test_bug_documental_sin_ficheros_declarados_no_pasa(self):
        nombre = self.preparar_bug_aprobado("sin-rutas", ficheros=None)

        resultado = self.ejecutar(self.unidad, "despachar", nombre, "--documental")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("ficheros", resultado.stderr)

    def test_despacho_bloquea_si_la_peticion_cambio_de_revision(self):
        pid = self.capturar()
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "revision-obsoleta", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        aclarada = self.ejecutar(
            self.peticion,
            "aclarar",
            pid,
            "--texto",
            "La petición cambia materialmente",
            "--autor",
            "Nate",
        )
        self.assertEqual(aclarada.returncode, 0, aclarada.stderr)

        resultado = self.ejecutar(self.unidad, "despachar", "001-revision-obsoleta")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("revisi", resultado.stderr.lower())
        self.assertIn("orden usa", resultado.stderr.lower())

    def test_despacho_normal_entrega_el_encargo_del_subagente_del_padre(self):
        # Hasta la 1.8.1 aquí se exigía `ejecucion.py lanzar … --rol constructor` (un
        # `claude -p` aparte). Bug 084 / ADR-033: el constructor es un subagente del padre;
        # el detalle del encargo lo fija test_constructor_subagente_del_padre.py.
        pid = self.capturar()
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "lanzamiento", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        self.aprobar_para_despacho("001-lanzamiento")

        resultado = self.ejecutar(self.unidad, "despachar", "001-lanzamiento")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("SUBAGENTE DEL PADRE", resultado.stdout)
        self.assertNotIn("--rol constructor", resultado.stdout)
        self.assertIn("--rol revisor", resultado.stdout)
        self.assertIn("sin_hook", resultado.stdout)
        recibo = self.recibo_preparacion("001-lanzamiento")
        self.assertEqual(recibo["estado"], "sin_hook")
        self.assertFalse(recibo["preparacion_verificada"])
        self.assertEqual(recibo["motivo"], "hook_ausente")

    def test_despacho_con_hook_verde_deja_entorno_y_recibo_verificados(self):
        nombre = self.preparar_feature_aprobada("hook-verde")
        hook = self.ws / "worktree-listo"
        # El contrato (cwd = worktree y $1 = worktree) se verifica desde python:
        # comparar $PWD con $1 dentro de sh no es portable (git-bash da /c/… y
        # el launcher pasa C:\…; mismas carpetas, formas distintas).
        hook.write_text(
            "#!/bin/sh\n"
            "printf preparado > .entorno-preparado\n"
            "printf %s \"$1\" > .arg-recibido\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        worktree = self.ws / "worktrees" / nombre
        self.assertEqual(
            (worktree / ".entorno-preparado").read_text(encoding="utf-8"),
            "preparado",
        )
        self.assertTrue(
            os.path.samefile((worktree / ".arg-recibido").read_text(encoding="utf-8"), worktree),
            "el hook no recibió el worktree como $1",
        )
        recibo = self.recibo_preparacion(nombre)
        self.assertEqual(recibo["estado"], "preparado")
        self.assertTrue(recibo["preparacion_verificada"])
        self.assertEqual(recibo["hook"], "worktree-listo")
        self.assertRegex(recibo["hook_sha256"], r"^[a-f0-9]{64}$")

    def test_despacho_con_hook_rojo_bloquea_y_deshace_worktree(self):
        nombre = self.preparar_feature_aprobada("hook-rojo")
        hook = self.ws / "worktree-listo"
        hook.write_text("#!/bin/sh\nexit 23\n", encoding="utf-8")
        hook.chmod(0o755)

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("bloqueado", resultado.stderr.lower())
        self.assertFalse((self.ws / "worktrees" / nombre).exists())
        ramas = subprocess.run(
            ["git", "branch", "--list", nombre], cwd=self.repo, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout
        self.assertEqual(ramas.strip(), "")
        contrato = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        self.assertIn("estado: planificada", contrato.read_text(encoding="utf-8"))
        recibo = self.recibo_preparacion(nombre)
        self.assertEqual(recibo["estado"], "fallido")
        self.assertFalse(recibo["preparacion_verificada"])
        self.assertEqual(recibo["codigo_salida"], 23)

    def test_despacho_rechaza_hook_symlink_y_no_lo_ejecuta(self):
        nombre = self.preparar_feature_aprobada("hook-symlink")
        objetivo = self.ws / ".private/hook-real"
        objetivo.parent.mkdir(parents=True)
        objetivo.write_text(
            "#!/bin/sh\nprintf ejecutado > hook-ejecutado\n",
            encoding="utf-8",
        )
        objetivo.chmod(0o755)
        ayuda_windows.enlazar_o_saltar(self, self.ws / "worktree-listo", objetivo)

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("enlace simbólico", resultado.stderr.lower())
        self.assertFalse((self.ws / "worktrees" / nombre).exists())
        self.assertFalse((self.ws / "hook-ejecutado").exists())
        recibo = self.recibo_preparacion(nombre)
        self.assertEqual(recibo["estado"], "fallido")
        self.assertEqual(recibo["motivo"], "hook_no_regular")

    def test_despacho_directo_no_lanza_otro_llm(self):
        pid = self.capturar()
        self.evaluar(pid, ruta="directo")
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "cambio-directo", "--directo", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        self.aprobar_para_despacho("001-cambio-directo")

        resultado = self.ejecutar(self.unidad, "despachar", "001-cambio-directo")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("Construye el padre", resultado.stdout)
        self.assertNotIn("ejecucion.py lanzar", resultado.stdout)

    # ------------------------------------------- 070 · el riesgo se lee en lo que se toca
    def preparar_directo(self, slug, ficheros, nivel=None):
        """Una unidad de carril directo aprobada y con su `ficheros:` puesto a mano."""
        pid = self.capturar()
        self.evaluar(pid, ruta="directo")
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", slug, "--directo", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = f"001-{slug}"
        ruta = self.aprobar_para_despacho(nombre, nivel=nivel)
        texto = re.sub(
            r"(?m)^ficheros:.*$", f"ficheros: [{', '.join(ficheros)}]",
            ruta.read_text(encoding="utf-8"), count=1,
        )
        ruta.write_text(texto, encoding="utf-8")
        return nombre

    def sembrar(self, relativa, contenido="print('ok')\n"):
        destino = self.repo / relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", f"añade {relativa}"], cwd=self.repo,
                       check=True, capture_output=True)
        return f"main/{relativa}"

    def test_directo_que_toca_acceso_no_se_despacha_y_nombra_la_salida(self):
        """R2 — el criterio PORTANTE: si el atajo no se cierra, el resto es un informe."""
        declarado = self.sembrar("app/auth/login.py")
        nombre = self.preparar_directo("toca-el-login", [declarado])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("acceso y autenticación", salida)
        self.assertIn("app/auth/login.py", salida)
        self.assertIn("carril: normal", salida)
        self.assertIn(f"unidad.py despachar {nombre}", salida)
        self.assertFalse((self.ws / "worktrees" / nombre).exists())

    def test_directo_sin_senales_se_despacha_sin_una_palabra_nueva(self):
        """R4 — sin señales, el despacho es el de hoy: ni una línea de más."""
        declarado = self.sembrar("docs/manual.md", contenido="# Manual\n")
        nombre = self.preparar_directo("solo-un-texto", [declarado])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertNotIn("señal", salida.lower())
        self.assertNotIn("senales-de-riesgo", salida)

    def test_el_cierre_de_un_directo_rechaza_el_contenido_delicado_del_diff(self):
        """H1 · R2, mitad «contenido»: en el cierre SÍ hay diff, y ahí es donde se mira.

        El despacho solo pudo leer `ficheros:`. Entre aquel momento y el cierre, el trabajo
        metió `os.system(` en un fichero de nombre inocente y dentro de los topes de tamaño:
        sin esta puerta, el atajo se cerraba con acta de entrega.
        """
        self.sembrar("app/util.py", contenido="def limpiar(nombre):\n    return nombre\n")
        nombre = self.preparar_directo("shell-en-el-diff", ["app/util.py"])
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        worktree = self.ws / "worktrees" / nombre
        (worktree / "app/util.py").write_text(
            "import os\n\n\ndef limpiar(nombre):\n    os.system(\"rm -rf \" + nombre)\n",
            encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "limpieza"], cwd=worktree, check=True,
                       capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", nombre], cwd=self.repo, check=True,
                       capture_output=True)
        self.preparar_cierre(nombre)

        resultado = self.ejecutar(
            self.unidad, "cerrar", nombre, "--ok-usuario", datetime.date.today().isoformat())

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("comandos de sistema", salida)
        self.assertIn("app/util.py:5", salida)
        self.assertIn(f"unidad.py reencuadrar {nombre} --carril normal", salida)

    def preparar_cierre(self, nombre):
        """Lo que el ritual de cierre exige antes de la puerta 6: estado, revisión y parte."""
        carpeta = self.ws / "docs/05-trabajo" / nombre
        spec = carpeta / "especificacion.md"
        spec.write_text(
            re.sub(r"(?m)^estado:.*$", "estado: en_revision",
                   spec.read_text(encoding="utf-8"), count=1),
            encoding="utf-8")
        hallazgos = carpeta / "hallazgos.md"
        texto = hallazgos.read_text(encoding="utf-8")
        texto = re.sub(r"^revisor:.*$", "revisor: agente-fresco", texto, count=1, flags=re.M)
        texto = re.sub(r"^revisado:.*$", f"revisado: {datetime.date.today().isoformat()}",
                       texto, count=1, flags=re.M)
        texto = texto.replace("- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN",
                              "- **Veredicto:** LIMPIO")
        hallazgos.write_text(texto, encoding="utf-8")
        ayuda_cierre.escribir_parte_honesto(self.ws, hallazgos)
        self.recibos_de_revision(nombre)

    # ------------------------------ 069 · el veredicto es un vocabulario CERRADO (R1, R3)
    def preparar_unidad_cerrable(self, slug):
        """Una unidad mergeada y con todo lo que el cierre pide, lista para la puerta 2."""
        nombre = self.preparar_con_plan(slug)
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        worktree = self.ws / "worktrees" / nombre
        (worktree / "app/terminal.py").write_text("print('cambiado')\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "cambio"], cwd=worktree,
                       check=True, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", nombre], cwd=self.repo,
                       check=True, capture_output=True)
        self.preparar_cierre(nombre)
        return nombre, self.ws / "docs/05-trabajo" / nombre / "hallazgos.md"

    def cerrar(self, nombre):
        return self.ejecutar(self.unidad, "cerrar", nombre,
                             "--ok-usuario", datetime.date.today().isoformat())

    def test_cerrar_rechaza_una_entrega_cuya_ultima_revision_deja_huecos(self):
        """R3 — el agujero de `P-20260813-f1c820b6`: la puerta aceptaba CUALQUIER texto de
        veredicto, así que una unidad con HUECOS DE CORRECCIÓN cerraba igual que una limpia.
        """
        nombre, hallazgos = self.preparar_unidad_cerrable("con-huecos")
        hallazgos.write_text(
            hallazgos.read_text(encoding="utf-8").replace(
                "- **Veredicto:** LIMPIO", "- **Veredicto:** HUECOS DE CORRECCIÓN"),
            encoding="utf-8")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("huecos de corrección", salida.lower())
        self.assertIn("SALIDA:", salida)
        self.assertIn("ejecucion.py lanzar", salida)

    def test_cerrar_con_veredicto_limpio_sigue_pasando_igual_que_hoy(self):
        """El camino feliz no se toca: una revisión LIMPIA a la primera cierra igual."""
        nombre, _ = self.preparar_unidad_cerrable("limpia-a-la-primera")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("veredicto: LIMPIO", salida)

    def test_cerrar_avisa_de_un_veredicto_fuera_del_vocabulario_pero_no_bloquea(self):
        """Bloquear lo desconocido dejaría encerrada a toda unidad anterior que escribiera
        su veredicto con sus palabras. Se avisa, que es lo que merece un dato sin normalizar.
        """
        nombre, hallazgos = self.preparar_unidad_cerrable("veredicto-raro")
        hallazgos.write_text(
            hallazgos.read_text(encoding="utf-8").replace(
                "- **Veredicto:** LIMPIO", "- **Veredicto:** todo correcto, adelante"),
            encoding="utf-8")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("vocabulario", salida.lower())

    def test_cerrar_denuncia_una_ronda_tecleada_que_los_recibos_no_acreditan(self):
        """R1 — el contador lo escribe `ejecucion.py`. Un número mayor que el que consta en
        los recibos justifica vueltas que nadie dio, y eso es la firma del revisor de la 033
        otra vez, con otro nombre."""
        nombre, hallazgos = self.preparar_unidad_cerrable("ronda-inventada")
        recibo = self.ws / ".runtime/ejecuciones" / f"{nombre}-constructor.json"
        datos = json.loads(recibo.read_text(encoding="utf-8"))
        datos["ronda"] = 1
        recibo.write_text(json.dumps(datos), encoding="utf-8")
        hallazgos.write_text(
            re.sub(r"(?m)^ronda:.*$", "ronda: 3",
                   hallazgos.read_text(encoding="utf-8"), count=1),
            encoding="utf-8")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("ronda: 3", salida)
        self.assertIn("SALIDA:", salida)

    def test_cerrar_denuncia_una_ronda_BAJADA_a_mano_por_debajo_de_los_recibos(self):
        """H1 de la revisión — el simétrico del anterior, y el que de verdad muerde: una
        ronda de MENOS no justifica vueltas de más, sino que BORRA las que ocurrieron. Con el
        cotejo solo en `>`, el constructor bajaba `ronda: 2` a `ronda: 1`, se regalaba la
        tercera vuelta y el cierre acreditaba lo contrario de lo que dicen los recibos."""
        nombre, hallazgos = self.preparar_unidad_cerrable("ronda-bajada")
        recibo = self.ws / ".runtime/ejecuciones" / f"{nombre}-constructor.json"
        datos = json.loads(recibo.read_text(encoding="utf-8"))
        datos["ronda"] = 2
        recibo.write_text(json.dumps(datos), encoding="utf-8")
        hallazgos.write_text(
            re.sub(r"(?m)^ronda:.*$", "ronda: 1",
                   hallazgos.read_text(encoding="utf-8"), count=1),
            encoding="utf-8")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("ronda: 1", salida)
        self.assertIn("acreditan 2", salida)
        self.assertIn("SALIDA:", salida)

    def test_cerrar_acepta_la_ronda_que_los_recibos_acreditan(self):
        """La simétrica: una ronda 2 con su recibo detrás no es un problema, es un dato."""
        nombre, hallazgos = self.preparar_unidad_cerrable("ronda-acreditada")
        recibo = self.ws / ".runtime/ejecuciones" / f"{nombre}-constructor.json"
        datos = json.loads(recibo.read_text(encoding="utf-8"))
        datos["ronda"] = 2
        recibo.write_text(json.dumps(datos), encoding="utf-8")
        hallazgos.write_text(
            re.sub(r"(?m)^ronda:.*$", "ronda: 2",
                   hallazgos.read_text(encoding="utf-8"), count=1),
            encoding="utf-8")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("ronda 2 de corrección", salida)

    def test_una_senal_solo_en_tests_avisa_pero_no_cierra_el_atajo(self):
        """R5 — un fixture con la palabra `login` dentro no es un cambio de acceso."""
        declarado = self.sembrar("tests/test_login.py", contenido="def test_login():\n    pass\n")
        nombre = self.preparar_directo("senal-en-un-test", [declarado])

        resultado = self.ejecutar(self.unidad, "despachar", nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("acceso y autenticación", salida)
        self.assertIn("informativa", salida.lower())
    # --------------------------------- 078 · el progreso del plan vive en hallazgos.md
    PLAN_SINTETICO = (
        "\n## Plan de trabajo (marcar `[x]` inmediatamente al completar)\n\n"
        "- [ ] 1. Test en rojo\n"
        "- [ ] 2. Implementar\n"
        "- [ ] 3. Verde y evidencia\n"
    )

    def preparar_con_plan(self, slug, ficheros=("app/terminal.py",)):
        """Una feature de carril normal, aprobada y CON su `## Plan de trabajo` escrito.

        `aprobar_para_despacho` reescribe el cuerpo del contrato y se lleva el plan por
        delante: aquí se vuelve a poner, que es justo lo que estos tests miden.
        """
        pid = self.capturar(f"Preparar {slug}")
        self.evaluar(pid)
        creada = self.ejecutar(self.unidad, "nueva", "feature", slug, "--desde", pid)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = f"001-{slug}"
        ruta = self.aprobar_para_despacho(nombre)
        texto = re.sub(
            r"(?m)^ficheros:.*$", f"ficheros: [{', '.join(ficheros)}]",
            ruta.read_text(encoding="utf-8") + self.PLAN_SINTETICO, count=1,
        )
        ruta.write_text(texto, encoding="utf-8")
        return nombre

    def test_despachar_siembra_el_plan_en_hallazgos(self):
        """R1 — el constructor no puede tocar su ficha (0444), así que el despacho le deja
        las MISMAS casillas en `hallazgos.md`, que sí posee. Sin esto, la regla 2 le manda
        escribir donde el lanzador le ha denegado la escritura."""
        nombre = self.preparar_con_plan("plan-sembrado")

        despachada = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        hallazgos = (self.ws / "docs/05-trabajo" / nombre / "hallazgos.md").read_text(
            encoding="utf-8")
        self.assertIn("## Plan", hallazgos)
        self.assertIn("- [ ] 1. Test en rojo", hallazgos)
        self.assertIn("- [ ] 2. Implementar", hallazgos)
        self.assertIn("- [ ] 3. Verde y evidencia", hallazgos)

    def test_estado_cuenta_el_plan_desde_hallazgos(self):
        """R3 — «Plan: 0 de 8» con un constructor llevando media hora era un dato que
        mentía: se contaba sobre la ficha congelada. Se cuenta donde de verdad se marca."""
        nombre = self.preparar_con_plan("plan-contado")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        hallazgos = self.ws / "docs/05-trabajo" / nombre / "hallazgos.md"
        hallazgos.write_text(
            hallazgos.read_text(encoding="utf-8").replace(
                "- [ ] 1. Test en rojo", "- [x] 1. Test en rojo"),
            encoding="utf-8")

        resultado = self.ejecutar(self.unidad, "estado", "--sin-navegador")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("plan 1/3", salida.lower())

    def test_estado_cae_a_la_ficha_si_hallazgos_no_trae_plan(self):
        """R4 — las unidades ya en vuelo tienen las casillas en la ficha: el contador lee
        de donde estén, primero `hallazgos.md` y si no la ficha, y lo dice."""
        nombre = self.preparar_con_plan("plan-heredado")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        carpeta = self.ws / "docs/05-trabajo" / nombre
        hallazgos = carpeta / "hallazgos.md"
        # Una unidad nacida ANTES de esta corrección: sin sección `## Plan` y con las
        # casillas marcadas en la ficha (que en su día se pudo escribir).
        hallazgos.write_text(
            "\n".join(l for l in hallazgos.read_text(encoding="utf-8").splitlines()
                      if not l.startswith("- [ ] ")).replace("## Plan\n", ""),
            encoding="utf-8")
        spec = carpeta / "especificacion.md"
        spec.write_text(
            spec.read_text(encoding="utf-8").replace(
                "- [ ] 1. Test en rojo", "- [x] 1. Test en rojo"),
            encoding="utf-8")

        resultado = self.ejecutar(self.unidad, "estado", "--sin-navegador")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("plan 1/3", salida.lower())
        self.assertIn("en la ficha", salida.lower())

    def test_despachar_no_toca_las_casillas_de_la_ficha(self):
        """R6 — la frontera de la 028 no se relaja: la ficha sigue siendo el contrato y
        sus casillas se quedan como estaban (el 0444 del lanzador sigue siendo legítimo)."""
        nombre = self.preparar_con_plan("ficha-intacta")
        spec = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        antes = spec.read_text(encoding="utf-8")

        despachada = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        despues = spec.read_text(encoding="utf-8")
        # Lo único que `despachar` escribe en la ficha es el frontmatter de estado/fecha.
        self.assertEqual(antes.split("---", 2)[2], despues.split("---", 2)[2])
        self.assertEqual(3, despues.count("- [ ] "))

    def test_la_seccion_del_plan_se_ancla_en_su_cabecera_no_en_una_mencion(self):
        """H1 del revisor — la sección se localiza por su LÍNEA de cabecera. Estas mismas
        plantillas CITAN `## Plan de trabajo` y `## Plan` en su prosa, así que buscar la
        primera aparición del texto anclaba el conteo y la siembra en el párrafo equivocado
        y el plan volvía a leerse vacío: el bug 078 otra vez, por la puerta de atrás."""
        nombre = self.preparar_con_plan("plan-citado-en-prosa")
        spec = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        spec.write_text(
            spec.read_text(encoding="utf-8").replace(
                "## Verificación\n",
                "## Contexto\n\nOjo: el `## Plan de trabajo` de esta ficha es el contrato y "
                "sus casillas se marcan en hallazgos.md.\n\n## Verificación\n", 1),
            encoding="utf-8")

        despachada = self.ejecutar(self.unidad, "despachar", nombre)

        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        hallazgos = self.ws / "docs/05-trabajo" / nombre / "hallazgos.md"
        texto = hallazgos.read_text(encoding="utf-8")
        self.assertIn("- [ ] 1. Test en rojo", texto)
        # Y ahora la misma trampa del otro lado: una mención de `## Plan` en la prosa que
        # va ANTES de la cabecera de verdad, con una casilla ya marcada más abajo.
        hallazgos.write_text(
            texto.replace(
                "# 001 · Hallazgos de la obra",
                "# 001 · Hallazgos de la obra\n\n> Las casillas van en el `## Plan` de aquí "
                "abajo, no en la ficha.", 1
            ).replace("- [ ] 1. Test en rojo", "- [x] 1. Test en rojo"),
            encoding="utf-8")

        resultado = self.ejecutar(self.unidad, "estado", "--sin-navegador")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("plan 1/3", salida.lower())
        self.assertNotIn("en la ficha", salida.lower())

    def test_cerrar_dice_lo_que_falta_del_plan_y_no_revienta(self):
        """R5 — el cierre ya no copia casillas a mano (así se hizo en la 060): mira dónde se
        marcaron y, si falta alguna, lo DICE con el comando que lo enseña. No bloquea."""
        nombre = self.preparar_con_plan("plan-a-medias")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        carpeta = self.ws / "docs/05-trabajo" / nombre
        hallazgos = carpeta / "hallazgos.md"
        hallazgos.write_text(
            hallazgos.read_text(encoding="utf-8").replace(
                "- [ ] 1. Test en rojo", "- [x] 1. Test en rojo"),
            encoding="utf-8")
        (self.ws / "worktrees" / nombre / "app/terminal.py").write_text(
            "print('cambiado')\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "cambio"], cwd=self.ws / "worktrees" / nombre,
                       check=True, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", nombre], cwd=self.repo, check=True,
                       capture_output=True)
        self.preparar_cierre(nombre)

        resultado = self.ejecutar(
            self.unidad, "cerrar", nombre, "--ok-usuario", datetime.date.today().isoformat())

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("plan 1/3", salida.lower())
        self.assertIn("unidad.py estado", salida)

    # ------------------------------------------------------ 096 · reencuadre de carril
    def despachar_directo(self, slug):
        """Una unidad directo ya en obra: el punto en que se descubre que era más grande."""
        pid = self.capturar()
        self.evaluar(pid, ruta="directo")
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", slug, "--directo", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = f"001-{slug}"
        self.aprobar_para_despacho(nombre)
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        return pid, nombre

    def metadata_del_despacho(self, pid, nombre):
        datos = json.loads(
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json").read_text(
                encoding="utf-8")
        )
        proceso = next(p for p in datos["procesos"] if p.get("ref") == nombre)
        return proceso.get("metadata") or {}

    def test_reencuadrar_sube_el_carril_en_el_registro_y_en_la_ficha(self):
        pid, nombre = self.despachar_directo("cambio-que-crecio")
        antes = self.metadata_del_despacho(pid, nombre)
        self.assertEqual(antes.get("carril"), "directo")

        resultado = self.ejecutar(
            self.unidad, "reencuadrar", nombre,
            "--carril", "normal", "--motivo", "el diff mide 346 lineas",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        despues = self.metadata_del_despacho(pid, nombre)
        self.assertEqual(despues.get("carril"), "normal")
        # La base de despacho es el dato con el que el cierre MIDE: el reencuadre la conserva.
        self.assertEqual(despues.get("base_sha"), antes.get("base_sha"))
        self.assertEqual(despues.get("ejecucion"), antes.get("ejecucion"))
        ficha = (self.ws / "docs/05-trabajo" / nombre / "especificacion.md").read_text(
            encoding="utf-8")
        self.assertRegex(ficha, r"(?m)^carril: normal\b")
        self.assertIn("el diff mide 346 lineas", ficha)
        self.assertIn(datetime.date.today().isoformat(), ficha)
        self.assertIn("directo", ficha.split("---", 2)[2][:400])

    def test_reencuadrar_no_baja_de_carril_ni_toca_una_unidad_ya_mergeada(self):
        pid, nombre = self.despachar_directo("no-se-achica")
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"

        bajada = self.ejecutar(
            self.unidad, "reencuadrar", nombre,
            "--carril", "directo", "--motivo", "quiero saltarme la revisión",
        )

        self.assertEqual(bajada.returncode, 1, bajada.stdout)
        self.assertIn("SALIDA", bajada.stdout + bajada.stderr)
        self.assertEqual(self.metadata_del_despacho(pid, nombre).get("carril"), "directo")

        ruta.write_text(
            re.sub(r"(?m)^estado:.*$", "estado: mergeada",
                   ruta.read_text(encoding="utf-8"), count=1),
            encoding="utf-8",
        )
        tarde = self.ejecutar(
            self.unidad, "reencuadrar", nombre,
            "--carril", "normal", "--motivo", "me di cuenta al cerrar",
        )

        self.assertEqual(tarde.returncode, 1, tarde.stdout)
        self.assertIn("SALIDA", tarde.stdout + tarde.stderr)
        self.assertEqual(self.metadata_del_despacho(pid, nombre).get("carril"), "directo")

    def test_el_guardian_del_directo_ofrece_el_reencuadre_como_salida(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            modulo = importlib.import_module("unidad")
        finally:
            sys.path.remove(str(SCRIPTS))
        mensaje = modulo.mensaje_directo_desbordado("001-x", 5, 400, ["app/otro.py"])
        self.assertIn("unidad.py reencuadrar 001-x --carril normal", mensaje)
        self.assertNotIn("NO tiene comando", mensaje)

    def test_orden_existente_adopta_revision_material_sin_perder_historia(self):
        pid = self.capturar()
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "revision-adoptada", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        aclarada = self.ejecutar(
            self.peticion,
            "aclarar",
            pid,
            "--texto",
            "También cubre el caso sin conexión",
            "--autor",
            "Nate",
        )
        self.assertEqual(aclarada.returncode, 0, aclarada.stderr)
        self.evaluar(pid)

        resultado = self.ejecutar(
            self.peticion,
            "reencuadrar-orden",
            pid,
            "--desde-revision",
            "1",
            "--tipo",
            "unidad",
            "--ref",
            "001-revision-adoptada",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        contrato = (
            self.ws / "docs/05-trabajo/001-revision-adoptada/especificacion.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"peticiones: [{pid}@2]", contrato)
        self.assertIn("aprobado: no", contrato)
        procesos = json.loads(
            (
                self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
            ).read_text(encoding="utf-8")
        )["procesos"]
        self.assertEqual([p["revision"] for p in procesos], [1, 2])
        self.assertEqual(procesos[0]["estado"], "sustituido")
        self.assertEqual(procesos[1]["estado"], "pendiente")

    def test_cierre_archiva_antes_del_lint_y_reconcilia_al_final(self):
        pid = self.capturar("Documentar la operación")
        self.evaluar(pid, ruta="documentacion")
        creada = self.ejecutar(
            self.unidad,
            "nueva",
            "documentacion",
            "cierre-ordenado",
            "--desde",
            pid,
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        carpeta = self.ws / "docs/05-trabajo/001-cierre-ordenado"
        spec = carpeta / "especificacion.md"
        texto = spec.read_text(encoding="utf-8")
        texto = texto.replace("estado: planificada", "estado: en_revision")
        texto = texto.replace("aprobado: no", "aprobado: 2026-08-04")
        texto = texto.replace(
            "\n---\n",
            "\nejecucion: documental\ncontrol_plane: requerido\n"
            "target_fingerprint: target-documental-abc\n---\n",
            1,
        )
        spec.write_text(texto, encoding="utf-8")
        hallazgos = carpeta / "hallazgos.md"
        texto = hallazgos.read_text(encoding="utf-8")
        texto = re.sub(r"^revisor:.*$", "revisor: agente-fresco", texto, count=1, flags=re.M)
        texto = re.sub(r"^revisado:.*$", "revisado: 2026-08-04", texto, count=1, flags=re.M)
        texto = texto.replace(
            "- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN",
            "- **Veredicto:** LIMPIO",
        )
        hallazgos.write_text(texto, encoding="utf-8")
        ayuda_cierre.escribir_parte_honesto(self.ws, hallazgos)
        self.recibos_de_revision("001-cierre-ordenado")
        linter = self.ws / "docs/00-metodo/scripts/lint_metodo.py"
        linter.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "raiz = Path(__file__).resolve().parents[3]\n"
            "activa = raiz / 'docs/05-trabajo/001-cierre-ordenado/especificacion.md'\n"
            "texto = activa.read_text(encoding='utf-8') if activa.exists() else ''\n"
            "sys.exit(1 if 'estado: mergeada' in texto else 0)\n",
            encoding="utf-8",
        )

        sin_recibo = self.ejecutar(
            self.unidad,
            "cerrar",
            "001-cierre-ordenado",
        )

        self.assertEqual(sin_recibo.returncode, 1)
        self.assertIn("recibo-control-plane", sin_recibo.stderr)
        recibo = self.ws / ".runtime/recibo-cierre.json"
        recibo.parent.mkdir(exist_ok=True)
        recibo.write_text(json.dumps({
            "version": 1,
            "claim": "documentación coincide con la realidad",
            "target_fingerprint": "target-documental-abc",
            "route": "documental",
            "test_scope": "document",
            "runs": [
                {"phase": "legacy", "target_fingerprint": "target-documental-abc",
                 "passed": False, "command": "check legacy", "exit_code": 1,
                 "output_digest": "a" * 64},
                {"phase": "new", "target_fingerprint": "target-documental-abc",
                 "passed": True, "command": "check new", "exit_code": 0,
                 "output_digest": "b" * 64},
                {"phase": "mutant", "target_fingerprint": "target-documental-abc",
                 "passed": False, "command": "check mutant", "exit_code": 1,
                 "output_digest": "c" * 64},
            ],
            "metrics": {
                "first_artifact_seconds": 20, "close_seconds": 100,
                "method_seconds": 10, "total_seconds": 100,
            },
        }), encoding="utf-8")

        resultado = self.ejecutar(
            self.unidad,
            "cerrar",
            "001-cierre-ordenado",
            "--recibo-control-plane",
            str(recibo),
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(carpeta.exists())
        archivada = self.ws / "docs/05-trabajo/archivo/001-cierre-ordenado"
        self.assertTrue(archivada.is_dir())
        self.assertNotIn("en_validacion", resultado.stdout)
        datos = json.loads(
            (
                self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(datos["estado"], "cerrada")
        self.assertEqual(datos["procesos"][0]["estado"], "terminal")

    # --------------------------------------------------------- unidad 027: cerrar legacy (R1/R2)

    def preparar_unidad_sin_peticiones(self, slug):
        """Crea una unidad normal (vía petición real) y luego LE BORRA `peticiones:` del
        frontmatter, simulando una unidad anterior al sistema de peticiones. La petición real
        queda como huella sin usar: es exactamente lo que R1/R2 tienen que poder cerrar (o
        seguir bloqueando) sin ella."""
        pid = self.capturar(f"Trabajo legacy {slug}")
        self.evaluar(pid, ruta="documentacion")
        creada = self.ejecutar(
            self.unidad, "nueva", "documentacion", slug, "--desde", pid,
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        carpeta = next((self.ws / "docs/05-trabajo").glob(f"[0-9][0-9][0-9]-{slug}"))
        spec = carpeta / "especificacion.md"
        texto = spec.read_text(encoding="utf-8")
        texto = texto.replace("estado: planificada", "estado: en_revision")
        texto = re.sub(
            r"^peticiones:\s*\[.*\].*$", "peticiones: []", texto, count=1, flags=re.M
        )
        texto = texto.replace("\n---\n", "\nejecucion: documental\n---\n", 1)
        spec.write_text(texto, encoding="utf-8")
        hallazgos = carpeta / "hallazgos.md"
        texto = hallazgos.read_text(encoding="utf-8")
        texto = re.sub(r"^revisor:.*$", "revisor: agente-fresco", texto, count=1, flags=re.M)
        texto = re.sub(r"^revisado:.*$", "revisado: 2026-08-04", texto, count=1, flags=re.M)
        texto = texto.replace(
            "- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN",
            "- **Veredicto:** LIMPIO",
        )
        hallazgos.write_text(texto, encoding="utf-8")
        ayuda_cierre.escribir_parte_honesto(self.ws, hallazgos)
        self.recibos_de_revision(carpeta.name)
        return carpeta.name

    def escribir_legacy(self, unidades=(), bugs=(), modo="estricto"):
        legacy = self.ws / "docs/05-trabajo/peticiones/LEGACY.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps({
                "formato": 1, "modo": modo,
                "unidades": list(unidades), "bugs": list(bugs), "ramas": [],
            }),
            encoding="utf-8",
        )

    def test_cerrar_legacy_listada_cierra_citando_legacy(self):
        nombre = self.preparar_unidad_sin_peticiones("unidad-legacy")
        self.escribir_legacy(unidades=[nombre])

        resultado = self.ejecutar(
            self.unidad, "cerrar", nombre, "--ok-usuario", "2026-08-04",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("legacy", resultado.stdout.lower())
        final = self.ws / "docs/05-trabajo/archivo" / nombre / "especificacion.md"
        self.assertTrue(final.exists())
        self.assertIn("origen: legacy", final.read_text(encoding="utf-8"))

    def test_cerrar_sin_peticiones_no_listada_en_legacy_sigue_bloqueando(self):
        nombre = self.preparar_unidad_sin_peticiones("unidad-huerfana")
        self.escribir_legacy(unidades=["999-otra-unidad-cualquiera"])

        resultado = self.ejecutar(
            self.unidad, "cerrar", nombre, "--ok-usuario", "2026-08-04",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("no declara peticiones", resultado.stderr)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_cerrar_sin_peticiones_sin_legacy_json_sigue_bloqueando(self):
        nombre = self.preparar_unidad_sin_peticiones("unidad-sin-legacy")

        resultado = self.ejecutar(
            self.unidad, "cerrar", nombre, "--ok-usuario", "2026-08-04",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("no declara peticiones", resultado.stderr)

    # --------------------------------------------------------- unidad 027: par ruta/tipo (R5)

    def evaluar_par(self, pid, ruta, tipo, perfil="ninguna"):
        args = [
            "evaluar", pid, "--ruta", ruta, "--tipo", tipo,
            "--investigacion", perfil,
            "--motivo", "contraste suficiente para encaminar",
            "--flujo", "REC-1", "--huella-flujo", "planos-v1",
            "--sha", self.sha, "--ruta-codigo", "app/terminal.py",
            "--conocimiento", "docs/decisiones/004-paleta.md",
        ]
        resultado = self.ejecutar(self.peticion, *args)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_par_directo_bug_evaluado_una_vez_llega_a_despachar_sin_reevaluar(self):
        """El caso 1 de "Cómo lo pruebas tú" de la unidad 027 (R5), hasta despachar."""
        pid = self.capturar("El launcher no arranca Codex")
        self.evaluar_par(pid, "directo", "bug")

        creada = self.ejecutar(
            self.unidad, "nueva", "bug", "launcher-directo-par", "--directo",
            "--desde", pid,
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)

        nombre = self.preparar_bug_directo_ya_creado("launcher-directo-par")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)

    def preparar_bug_directo_ya_creado(self, slug):
        """Igual que `preparar_bug_aprobado`, pero sobre un bug que YA existe (creado a mano
        por el propio test, en carril directo) en vez de crearlo con `preparar_hotfix`."""
        ficha = next((self.ws / "docs/bugs").glob(f"[0-9][0-9][0-9]-{slug}.md"))
        texto = ficha.read_text(encoding="utf-8")
        texto = re.sub(
            r"^aprobado:.*$",
            f"aprobado: {datetime.date.today().isoformat()}",
            texto,
            count=1,
            flags=re.M,
        )
        texto = texto.replace("<síntoma en una frase>", "el runbook cuenta el orden antiguo", 1)
        texto += (
            "\n## Reporte\n\n"
            "El usuario esperaba que el runbook del carril corto describiera el paso de "
            "cierre tal y como lo ejecuta el script, pero el documento sigue contando el "
            "orden antiguo y el agente que lo siguió dejó la unidad a medio cerrar. Pasa "
            "siempre que se llega al paso seis con la sesión recién abierta. Severidad P2: "
            "no rompe datos, pero cada sesión nueva tropieza igual. Triaje: corregir el "
            "texto del runbook y contrastarlo con el script de cierre real.\n"
        )
        ficha.write_text(texto, encoding="utf-8")
        self.dejar_rastro_visor_contratos(ficha.stem)
        return ficha.stem

    def test_cerrar_respeta_git_index_de_otra_sesion(self):
        """ADR-023: el cierre reescribe el metarrepo — si otra sesión tiene
        `git-index` (p. ej. Modo D aplicando), cerrar falla nombrando al
        propietario y no archiva nada; al soltarse el lease, cierra normal."""
        from importlib import util as importlib_util

        pid = self.capturar("Documentar la operación bloqueada")
        self.evaluar(pid, ruta="documentacion")
        creada = self.ejecutar(
            self.unidad, "nueva", "documentacion", "cierre-con-lease",
            "--desde", pid,
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        carpeta = self.ws / "docs/05-trabajo/001-cierre-con-lease"
        spec = carpeta / "especificacion.md"
        texto = spec.read_text(encoding="utf-8")
        texto = texto.replace("estado: planificada", "estado: en_revision")
        texto = texto.replace("aprobado: no", "aprobado: 2026-08-04")
        texto = texto.replace("\n---\n", "\nejecucion: documental\n---\n", 1)
        spec.write_text(texto, encoding="utf-8")
        hallazgos = carpeta / "hallazgos.md"
        texto = hallazgos.read_text(encoding="utf-8")
        texto = re.sub(r"^revisor:.*$", "revisor: agente-fresco", texto,
                       count=1, flags=re.M)
        texto = re.sub(r"^revisado:.*$", "revisado: 2026-08-04", texto,
                       count=1, flags=re.M)
        texto = texto.replace(
            "- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN",
            "- **Veredicto:** LIMPIO",
        )
        hallazgos.write_text(texto, encoding="utf-8")
        ayuda_cierre.escribir_parte_honesto(self.ws, hallazgos)
        self.recibos_de_revision("001-cierre-con-lease")
        (self.ws / "docs/00-metodo/scripts/lint_metodo.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8"
        )

        spec_lease = importlib_util.spec_from_file_location(
            "lease_ws", self.ws / "docs/00-metodo/scripts/lease.py"
        )
        modulo = importlib_util.module_from_spec(spec_lease)
        spec_lease.loader.exec_module(modulo)
        ajeno = modulo.LeaseManager(self.ws, session_id="sesion-ajena")
        with ajeno.acquire("git-index"):
            bloqueado = self.ejecutar(self.unidad, "cerrar", "001-cierre-con-lease")
        self.assertEqual(bloqueado.returncode, 1,
                         bloqueado.stdout + bloqueado.stderr)
        self.assertIn("cierre bloqueado", bloqueado.stderr)
        self.assertTrue(carpeta.exists(),
                        "el cierre bloqueado no debe archivar nada")

        liberado = self.ejecutar(self.unidad, "cerrar", "001-cierre-con-lease")
        self.assertEqual(liberado.returncode, 0,
                         liberado.stdout + liberado.stderr)
        self.assertFalse(carpeta.exists())

    def test_prototipo_no_puede_cerrar_ni_reconciliar_como_entrega(self):
        pid = self.capturar("Probar una hipótesis descartable")
        self.evaluar(pid, ruta="documentacion")
        creada = self.ejecutar(
            self.unidad,
            "nueva",
            "documentacion",
            "prototipo-descartable",
            "--desde",
            pid,
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        carpeta = self.ws / "docs/05-trabajo/001-prototipo-descartable"
        spec = carpeta / "especificacion.md"
        texto = spec.read_text(encoding="utf-8")
        texto = texto.replace("estado: planificada", "estado: en_revision")
        texto = texto.replace("aprobado: no", "aprobado: 2026-08-04")
        texto = texto.replace("\n---\n", "\nejecucion: prototipo\n---\n", 1)
        spec.write_text(texto, encoding="utf-8")
        (carpeta / "hallazgos.md").unlink()

        bloqueado = self.ejecutar(
            self.unidad, "cerrar", "001-prototipo-descartable"
        )

        self.assertEqual(bloqueado.returncode, 1)
        self.assertIn("cancelado", bloqueado.stderr.lower())
        spec.write_text(
            texto.replace("\n---\n", "\ndescarte: confirmado\n---\n", 1),
            encoding="utf-8",
        )

        cerrado = self.ejecutar(
            self.unidad, "cerrar", "001-prototipo-descartable"
        )

        self.assertEqual(cerrado.returncode, 1)
        self.assertIn("cancelado", cerrado.stderr.lower())
        self.assertFalse(
            (self.ws / "docs/05-trabajo/archivo/001-prototipo-descartable").exists()
        )
        datos = json.loads(
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json")
                .read_text(encoding="utf-8")
        )
        self.assertNotEqual(datos["estado"], "cerrada")
        self.assertNotEqual(datos["procesos"][0]["estado"], "terminal")

    def test_abrir_expres_crea_rama_canonica_y_enlaza_peticion(self):
        repo = self.repo
        pid = self.capturar("Ordenar imports")
        self.evaluar(pid, ruta="expres")

        resultado = self.ejecutar(
            self.peticion, "abrir-expres", pid, "ordenar-imports"
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        rama = f"expres-{pid}-ordenar-imports"
        ramas = subprocess.run(
            ["git", "branch", "--list", rama],
            cwd=repo,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
            check=True,
        ).stdout
        self.assertIn(rama, ramas)
        datos = json.loads(
            (
                self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            any(p["tipo"] == "expres" and p["ref"] == rama for p in datos["procesos"])
        )
        prematuro = self.ejecutar(
            self.peticion, "reconciliar", pid,
            "--revision", "1", "--tipo", "expres", "--ref", rama,
            "--evidencia", "todavía no hay cambio",
        )
        self.assertEqual(prematuro.returncode, 1)
        subprocess.run(["git", "checkout", rama], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("base\nimports ordenados\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Ordena imports"], cwd=repo,
            check=True, capture_output=True,
        )
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "merge", "--ff-only", rama], cwd=repo,
            check=True, capture_output=True,
        )

        cerrada = self.ejecutar(
            self.peticion, "reconciliar", pid,
            "--revision", "1", "--tipo", "expres", "--ref", rama,
            "--evidencia", "commit fusionado y suite verde",
        )

        self.assertEqual(cerrada.returncode, 0, cerrada.stderr)
        datos = json.loads(
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json")
                .read_text(encoding="utf-8")
        )
        self.assertEqual(datos["estado"], "cerrada")
        metadata = datos["procesos"][0]["metadata"]
        self.assertEqual(metadata["tip_sha"], metadata["merge_sha"])

        subprocess.run(["git", "branch", "-d", rama], cwd=repo, check=True, capture_output=True)
        for nombre in (
            "01-constitucion", "02-flujos", "03-investigacion", "04-planificacion",
            "conocimiento",
        ):
            (self.ws / "docs" / nombre).mkdir(parents=True, exist_ok=True)
        (self.ws / "docs/05-trabajo/archivo").mkdir(exist_ok=True)
        (self.ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        (self.ws / "AGENTS.md").write_text("# Router\n", encoding="utf-8")
        for puente in ("CLAUDE.md", "GEMINI.md"):
            (self.ws / puente).write_text("@AGENTS.md\n", encoding="utf-8")
        linter = self.ws / "docs/00-metodo/scripts/lint_metodo.py"
        shutil.copy2(LINTER, linter)

        lint = self.ejecutar(linter)

        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_expres_admite_squash_si_el_commit_nombra_la_rama(self):
        repo = self.repo
        pid = self.capturar("Ordenar imports")
        self.evaluar(pid, ruta="expres")
        abierto = self.ejecutar(
            self.peticion, "abrir-expres", pid, "ordenar-imports"
        )
        self.assertEqual(abierto.returncode, 0, abierto.stderr)
        rama = f"expres-{pid}-ordenar-imports"
        subprocess.run(["git", "checkout", rama], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("cambio exprés\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "trabajo exprés"], cwd=repo,
            check=True, capture_output=True,
        )
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "merge", "--squash", rama], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", rama], cwd=repo, check=True, capture_output=True
        )

        cierre = self.ejecutar(
            self.peticion, "reconciliar", pid, "--revision", "1", "--tipo", "expres",
            "--ref", rama, "--evidencia", "squash fusionado y suite verde",
        )

        self.assertEqual(cierre.returncode, 0, cierre.stderr)
        datos = json.loads(
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json")
                .read_text(encoding="utf-8")
        )
        self.assertEqual(datos["estado"], "cerrada")
        metadata = datos["procesos"][0]["metadata"]
        self.assertNotEqual(metadata["tip_sha"], metadata["merge_sha"])
        self.assertEqual(metadata["modo_fusion"], "squash")
        subprocess.run(["git", "branch", "-D", rama], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "reflog", "expire", "--expire=now", "--all"],
            cwd=repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "gc", "--prune=now"], cwd=repo, check=True, capture_output=True
        )
        podada = subprocess.run(
            ["git", "cat-file", "-e", metadata["tip_sha"]], cwd=repo,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        self.assertNotEqual(podada.returncode, 0)

        reanudada = self.ejecutar(
            self.peticion, "reconciliar", pid, "--revision", "1", "--tipo", "expres",
            "--ref", rama, "--evidencia", "cierre idempotente tras limpiar la rama",
        )

        self.assertEqual(reanudada.returncode, 0, reanudada.stderr)
        for nombre in (
            "01-constitucion", "02-flujos", "03-investigacion", "04-planificacion",
            "conocimiento",
        ):
            (self.ws / "docs" / nombre).mkdir(parents=True, exist_ok=True)
        (self.ws / "docs/05-trabajo/archivo").mkdir(exist_ok=True)
        (self.ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        (self.ws / "AGENTS.md").write_text("# Router\n", encoding="utf-8")
        for puente in ("CLAUDE.md", "GEMINI.md"):
            (self.ws / puente).write_text("@AGENTS.md\n", encoding="utf-8")
        linter = self.ws / "docs/00-metodo/scripts/lint_metodo.py"
        shutil.copy2(LINTER, linter)

        lint = self.ejecutar(linter)

        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_abrir_hotfix_tria_p0_y_despacha_sin_pasos_intermedios(self):
        repo = self.repo
        pid = self.capturar("Producción caída")
        self.evaluar(pid, ruta="bug")

        resultado = self.ejecutar(
            self.peticion,
            "abrir-hotfix",
            pid,
            "produccion-caida",
            "--motivo",
            "el usuario declara producción caída",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        ficha = self.ws / "docs/bugs/001-produccion-caida.md"
        texto = ficha.read_text(encoding="utf-8")
        self.assertIn("**Severidad preliminar:** P0", texto)
        self.assertIn("estado: en_obra", texto)
        self.assertTrue((self.ws / "worktrees/001-produccion-caida").is_dir())
        datos = json.loads(
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json")
                .read_text(encoding="utf-8")
        )
        proceso = next(item for item in datos["procesos"] if item["tipo"] == "bug")
        self.assertEqual(proceso["metadata"]["base_sha"], self.sha)
        self.assertEqual(proceso["metadata"]["principal"], "main")


class LintPeticionesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-peticiones-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        for nombre in (
            "00-metodo",
            "01-constitucion",
            "02-flujos",
            "03-investigacion",
            "04-planificacion",
            "05-trabajo",
            "bugs",
            "conocimiento",
            "decisiones",
        ):
            (self.ws / "docs" / nombre).mkdir(parents=True)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir()
        self.linter = scripts / "lint_metodo.py"
        shutil.copy2(LINTER, self.linter)
        shutil.copy2(SCRIPTS / "repo_config.py", scripts / "repo_config.py")
        shutil.copy2(SCRIPTS / "workspace_paths.py", scripts / "workspace_paths.py")
        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir()
        (plantillas / "bug.md").write_text("", encoding="utf-8")
        (self.ws / "AGENTS.md").write_text("# Router\n", encoding="utf-8")
        for puente in ("CLAUDE.md", "GEMINI.md"):
            (self.ws / puente).write_text("@AGENTS.md\n", encoding="utf-8")
        (self.ws / "docs/05-trabajo/ESTADO.md").write_text(
            "# Estado\n", encoding="utf-8"
        )
        (self.ws / "docs/05-trabajo/archivo").mkdir()
        (self.ws / "docs/05-trabajo/peticiones").mkdir()

    def ejecutar(self):
        return subprocess.run(
            [sys.executable, str(self.linter)],
            cwd=self.ws,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    def peticion(self, pid="P-20260804-1234abcd", revision=1, estado="encaminada",
                  procesos=None, aparcada=None):
        carpeta = self.ws / "docs/05-trabajo/peticiones" / pid
        carpeta.mkdir(parents=True)
        contratos = {
            "unidad": "unidad-mergeada-v1", "bug": "bug-mergeado-v1",
            "expres": "rama-expres-v1", "investigacion": "fase3-sintetizada-v1",
            "auditoria": "unidad-auditoria-mergeada-v1", "flujos": "planos-aprobados-v1",
            "deploy": "despliegue-verificado-v1",
        }
        procesos = procesos or []
        for proceso in procesos:
            proceso.setdefault("contrato_terminal", contratos.get(proceso.get("tipo")))
        datos = {
            "id": pid,
            "revision": revision,
            "estado": estado,
            "original": {"resumen": "Cambio"},
            "evaluaciones": [],
            "procesos": procesos,
            "cierres": [],
        }
        if aparcada:
            datos["aparcada"] = aparcada
        (carpeta / "peticion.json").write_text(
            json.dumps(datos), encoding="utf-8"
        )
        return pid

    def unidad(self, nombre="001-cambio", peticiones=""):
        carpeta = self.ws / "docs/05-trabajo" / nombre
        carpeta.mkdir()
        (carpeta / "especificacion.md").write_text(
            "---\n"
            f"unidad: {nombre}\n"
            "tipo: feature\n"
            "carril: normal\n"
            "estado: planificada\n"
            "aprobado: no\n"
            "actividad: REC-1\n"
            "ficheros: []\n"
            f"peticiones: [{peticiones}]\n"
            "actualizado: 2026-08-04\n"
            "---\n\n# Contrato\n",
            encoding="utf-8",
        )

    def test_workspace_nuevo_rechaza_unidad_sin_peticion(self):
        self.unidad()

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("sin petición", resultado.stdout.lower())

    def test_grafias_distintas_del_mismo_fichero_chocan_en_paralelo(self):
        # Auditoría 2026-08-03, hallazgo 2: `api/x.py` y `./API/x.py` pasaban por disjuntos.
        for nombre, grafia in (("001-puerta", "api/x.py"), ("002-choque", "./API/x.py")):
            carpeta = self.ws / "docs/05-trabajo" / nombre
            carpeta.mkdir()
            (carpeta / "especificacion.md").write_text(
                "---\n"
                f"unidad: {nombre}\n"
                "tipo: feature\n"
                "carril: normal\n"
                "estado: en_obra\n"
                "aprobado: 2026-08-04\n"
                "actividad: REC-1\n"
                f"ficheros: [{grafia}]\n"
                "peticiones: []\n"
                "actualizado: 2026-08-04\n"
                "---\n\n# Contrato\n",
                encoding="utf-8",
            )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("comparten ficheros declarados", resultado.stdout)
        self.assertIn("api/x.py", resultado.stdout)

    def test_referencia_inexistente_o_revision_obsoleta_falla(self):
        pid = self.peticion(revision=2)
        self.unidad(peticiones=f"{pid}@1")

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("revisión", resultado.stdout.lower())

    def test_unidad_historica_en_allowlist_conserva_validez(self):
        self.unidad("001-antigua")
        (self.ws / "docs/05-trabajo/peticiones/LEGACY.json").write_text(
            json.dumps(
                {
                    "formato": 1,
                    "modo": "observacion",
                    "unidades": ["001-antigua"],
                    "bugs": [],
                    "ramas": [],
                }
            ),
            encoding="utf-8",
        )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("001-antigua: sin petición", resultado.stdout.lower())

    def test_peticion_cerrada_con_proceso_abierto_falla(self):
        self.peticion(
            estado="cerrada",
            procesos=[
                {
                    "tipo": "unidad",
                    "ref": "001-cambio",
                    "relacion": "satisface",
                    "revision": 1,
                    "estado": "pendiente",
                }
            ],
        )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("proceso abierto", resultado.stdout.lower())

    def test_peticion_no_puede_referenciar_un_proceso_inexistente(self):
        self.peticion(
            procesos=[
                {
                    "tipo": "unidad",
                    "ref": "999-inventada",
                    "relacion": "satisface",
                    "revision": 1,
                    "estado": "terminal",
                }
            ]
        )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("proceso unidad inexistente", resultado.stdout.lower())

    def test_capturada_y_aparcada_vencida_se_hacen_visibles(self):
        capturada = self.peticion("P-20260804-aaaaaaaa", estado="capturada")
        aparcada = self.peticion(
            "P-20260804-bbbbbbbb",
            estado="aparcada",
            aparcada={"revisar_el": "2020-01-01", "motivo": "esperar"},
        )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn(capturada, resultado.stdout)
        self.assertIn(aparcada, resultado.stdout)
        self.assertGreaterEqual(resultado.stdout.count("WARN"), 2)

    def test_trabajo_descubierto_promovido_exige_pid(self):
        pid = self.peticion()
        carpeta = self.ws / "docs/05-trabajo/archivo/001-cerrada"
        carpeta.mkdir()
        (carpeta / "especificacion.md").write_text(
            "---\nunidad: 001-cerrada\ntipo: feature\ncarril: normal\n"
            "estado: mergeada\naprobado: 2026-08-04\nactividad: REC-1\n"
            f"ficheros: []\npeticiones: [{pid}@1]\nactualizado: 2026-08-04\n---\n",
            encoding="utf-8",
        )
        (carpeta / "hallazgos.md").write_text(
            "# Hallazgos\n\n## Trabajo descubierto\n\n"
            "- Conviene rehacer la caché. → promovido a próxima unidad\n",
            encoding="utf-8",
        )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("promovido", resultado.stdout.lower())
        self.assertIn("p-id", resultado.stdout.lower())

    def test_investigacion_terminal_con_informes_vacios_falla_tambien_en_linter(self):
        sintesis = self.ws / "docs/03-investigacion/SINTESIS.md"
        sintesis.write_text(
            "# Síntesis\n\n" + "Conclusión de plataforma contrastada. " * 12,
            encoding="utf-8",
        )
        for indice in range(1, 11):
            (sintesis.parent / f"informe-{indice:02d}-enfoque.md").write_text(
                "# Vacío\n", encoding="utf-8"
            )
        self.peticion(
            estado="cerrada",
            procesos=[{
                "tipo": "investigacion",
                "ref": "docs/03-investigacion/SINTESIS.md",
                "relacion": "satisface",
                "revision": 1,
                "estado": "terminal",
            }],
        )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("investigación terminal", resultado.stdout.lower())

    def test_deploy_terminal_minimo_falla_tambien_en_linter(self):
        pid = "P-20260804-1234abcd"
        ficha = self.ws / "docs/05-trabajo/001-release/despliegue.md"
        ficha.parent.mkdir()
        ficha.write_text(
            "---\nproceso: deploy\nestado: desplegado\n"
            f"peticiones: [{pid}@1]\netapa: 1-lan\ncommit: deadbeef\n"
            "fecha: 2026-08-04\n---\n\n"
            "- **Validación del usuario sobre la etapa desplegada:** OK (2026-08-04)\n",
            encoding="utf-8",
        )
        self.peticion(
            pid=pid,
            estado="cerrada",
            procesos=[{
                "tipo": "deploy",
                "ref": "docs/05-trabajo/001-release/despliegue.md",
                "relacion": "satisface",
                "revision": 1,
                "estado": "terminal",
            }],
        )

        resultado = self.ejecutar()

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("deploy", resultado.stdout.lower())
        self.assertIn("sin ficha desplegada y completa", resultado.stdout.lower())


class PrePushPeticionesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hook-peticiones-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        githooks = self.ws / "githooks"
        githooks.mkdir()
        self.hook = githooks / "pre-push"
        shutil.copy2(HOOK, self.hook)
        (self.ws / "docs/00-metodo/plantillas").mkdir(parents=True)
        (self.ws / "docs/00-metodo/plantillas/especificacion.md").write_text(
            "plantilla", encoding="utf-8"
        )

    def ejecutar(self, rama, sha=None, espacio="heads"):
        sha = sha or "1" * 40
        cero = "0" * 40
        entrada = f"refs/{espacio}/{rama} {sha} refs/{espacio}/{rama} {cero}\n"
        return subprocess.run(
            [sys.executable, str(self.hook)],
            cwd=self.ws,
            input=entrada,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    def test_rama_de_unidad_sin_peticion_no_se_empuja(self):
        carpeta = self.ws / "docs/05-trabajo/001-cambio"
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            "---\nunidad: 001-cambio\npeticiones: []\n---\n" + "contrato " * 80,
            encoding="utf-8",
        )

        resultado = self.ejecutar("001-cambio")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("petición", resultado.stderr.lower())

    def test_rama_expres_sin_nombre_canonico_falla_en_estricto(self):
        resultado = self.ejecutar("expres-arreglo-rapido")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("expres-p-id", resultado.stderr.lower())

    def test_referencia_inventada_no_supera_el_pre_push(self):
        carpeta = self.ws / "docs/05-trabajo/001-falsa"
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            "---\nunidad: 001-falsa\npeticiones: [P-20260804-deadbeef@99]\n---\n"
            + "contrato escrito " * 40,
            encoding="utf-8",
        )

        resultado = self.ejecutar("001-falsa")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("inexistentes", resultado.stderr.lower())

    def test_push_directo_a_main_se_bloquea_en_modo_estricto(self):
        resultado = self.ejecutar("main")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("principal", resultado.stderr.lower())

    def test_camino_b_permite_main_si_el_commit_sigue_en_su_rama_trazada(self):
        pid = "P-20260804-1234abcd"
        nombre = "001-cambio"
        carpeta = self.ws / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            "---\nunidad: 001-cambio\n"
            f"peticiones: [{pid}@1]\n---\n" + "contrato escrito " * 40,
            encoding="utf-8",
        )
        peticion = self.ws / "docs/05-trabajo/peticiones" / pid
        peticion.mkdir(parents=True)
        repo = self.ws / "main"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-b", nombre], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("base\ncambio\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "cambio"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", nombre], cwd=repo, check=True, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        (peticion / "peticion.json").write_text(
            json.dumps(
                {
                    "id": pid,
                    "estado": "encaminada",
                    "revision": 1,
                    "evaluaciones": [
                        {"revision": 1, "investigacion": {"perfil": "ninguna"}}
                    ],
                    "procesos": [
                        {
                            "tipo": "unidad", "ref": nombre, "revision": 1,
                            "estado": "pendiente",
                            "metadata": {"base_sha": base, "principal": "main"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        resultado = self.ejecutar("main", sha=sha)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_crear_rama_despues_del_commit_directo_no_disfraza_camino_b(self):
        pid = "P-20260804-1234abcd"
        nombre = "001-cambio"
        carpeta = self.ws / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            f"---\nunidad: {nombre}\npeticiones: [{pid}@1]\n---\n"
            + "contrato escrito " * 40,
            encoding="utf-8",
        )
        repo = self.ws / "main"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        (repo / "README.md").write_text("commit directo\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "directo"], cwd=repo, check=True, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        subprocess.run(["git", "branch", nombre], cwd=repo, check=True)
        peticion = self.ws / "docs/05-trabajo/peticiones" / pid
        peticion.mkdir(parents=True)
        (peticion / "peticion.json").write_text(json.dumps({
            "id": pid, "estado": "encaminada", "revision": 1,
            "evaluaciones": [{"revision": 1, "investigacion": {"perfil": "ninguna"}}],
            "procesos": [{
                "tipo": "unidad", "ref": nombre, "revision": 1, "estado": "pendiente",
                "metadata": {"base_sha": sha, "principal": "main"},
            }],
        }), encoding="utf-8")

        resultado = self.ejecutar("main", sha=sha)

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("principal", resultado.stderr.lower())

    def test_camino_b_admite_squash_si_el_commit_nombra_la_rama_trazada(self):
        pid = "P-20260804-1234abcd"
        nombre = "001-cambio"
        carpeta = self.ws / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True)
        (carpeta / "especificacion.md").write_text(
            f"---\nunidad: {nombre}\npeticiones: [{pid}@1]\n---\n"
            + "contrato escrito " * 40,
            encoding="utf-8",
        )
        repo = self.ws / "main"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-b", nombre], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("base\ncambio\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "trabajo"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "merge", "--squash", nombre], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", nombre], cwd=repo, check=True, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        peticion = self.ws / "docs/05-trabajo/peticiones" / pid
        peticion.mkdir(parents=True)
        (peticion / "peticion.json").write_text(json.dumps({
            "id": pid, "estado": "encaminada", "revision": 1,
            "evaluaciones": [{"revision": 1, "investigacion": {"perfil": "ninguna"}}],
            "procesos": [{
                "tipo": "unidad", "ref": nombre, "revision": 1, "estado": "pendiente",
                "metadata": {"base_sha": base, "principal": "main"},
            }],
        }), encoding="utf-8")

        resultado = self.ejecutar("main", sha=sha)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_el_hook_ignora_tags(self):
        resultado = self.ejecutar("v1.0.0", espacio="tags")

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def _unidad_fusionada_y_reconciliada(self, nombre="001-cambio",
                                          pid="P-20260804-1234abcd"):
        """Reproduce el estado que deja `unidad.py cerrar` (020): la rama NNN local YA NO
        existe, el proceso de la petición ya está `terminal` (y la petición puede estar
        `cerrada`) y la ficha conserva `fusion: <sha>` como única prueba. Devuelve
        (repo, sha_fusionado, base_sha)."""
        carpeta = self.ws / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True)
        repo = self.ws / "main"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-b", nombre], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("base\ncambio\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "cambio"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", nombre], cwd=repo, check=True, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        # El cierre borra la rama local ANTES de imprimir el recibo/aviso (020).
        subprocess.run(["git", "branch", "-D", nombre], cwd=repo, check=True, capture_output=True)

        (carpeta / "especificacion.md").write_text(
            f"---\nunidad: {nombre}\n"
            f"peticiones: [{pid}@1]\nfusion: {sha}\n---\n" + "contrato escrito " * 40,
            encoding="utf-8",
        )
        peticion = self.ws / "docs/05-trabajo/peticiones" / pid
        peticion.mkdir(parents=True)
        (peticion / "peticion.json").write_text(json.dumps({
            "id": pid, "estado": "cerrada", "resultado": "entregada", "revision": 1,
            "evaluaciones": [{"revision": 1, "investigacion": {"perfil": "ninguna"}}],
            "procesos": [{
                "tipo": "unidad", "ref": nombre, "revision": 1, "estado": "terminal",
                "metadata": {"base_sha": base, "principal": "main"},
            }],
        }), encoding="utf-8")
        return repo, sha, base

    def test_recibo_post_cierre_pasa_con_proceso_terminal_y_fusion_anotada(self):
        # 020: el mismo `git push origin main` que el cierre imprime como recibo (push:
        # usuario) o como WARN (modo agente) ya no lo veta el hook que lo emitió.
        _, sha, _ = self._unidad_fusionada_y_reconciliada()

        resultado = self.ejecutar("main", sha=sha)

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_fusion_anotada_no_autoriza_un_commit_directo_posterior(self):
        # 020, regresión: la prueba de fusión anotada liga SOLO al commit que cerró esa
        # unidad. Un commit directo posterior a main (no trazado por ninguna unidad) sigue
        # bloqueado, aunque la principal siga conteniendo esa fusión legítima como antepasado.
        repo, sha_legitimo, _ = self._unidad_fusionada_y_reconciliada()
        (repo / "intruso.txt").write_text("commit directo sin rama\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "directo"], cwd=repo, check=True, capture_output=True)
        sha_intruso = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        ).stdout.strip()
        self.assertNotEqual(sha_intruso, sha_legitimo)

        resultado = self.ejecutar("main", sha=sha_intruso)

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("principal", resultado.stderr.lower())


class ContratoTextualPeticionesTest(unittest.TestCase):
    def texto(self, ruta):
        return (RAIZ / "plantilla" / ruta).read_text(encoding="utf-8")

    def test_router_envia_primero_las_peticiones_accionables_al_inbox(self):
        agents = self.texto("AGENTS.md")

        self.assertIn("runbooks/peticiones.md", agents)
        self.assertIn("primera escritura", agents.lower())
        self.assertLess(
            agents.index("runbooks/peticiones.md"),
            agents.index("runbooks/directo.md"),
        )

    def test_captura_precede_a_los_limites_de_todos_los_roles(self):
        roles = self.texto("docs/00-metodo/roles.md")

        self.assertIn("peticion.py capturar", roles)
        for rol in ("CONSTRUCTOR", "OBSERVABILIDAD", "DEPLOY", "ANALISTA DE FLUJOS"):
            self.assertIn(rol, roles)
        self.assertIn("antes de aplicar los permisos", roles.lower())

    def test_quien_construye_sigue_siendo_decision_del_carril(self):
        expres = self.texto("docs/00-metodo/runbooks/expres.md").lower()
        directo = self.texto("docs/00-metodo/runbooks/directo.md").lower()
        agents = self.texto("AGENTS.md").lower()

        self.assertIn("construye el padre", expres)
        self.assertIn("construye el padre", directo)
        self.assertIn("normal y completo", agents)
        self.assertIn("subagente del propio padre", agents)  # bug 084 / ADR-033

    def test_hallazgo_aceptado_pasa_por_pid_antes_de_otra_unidad(self):
        hallazgos = self.texto("docs/00-metodo/plantillas/hallazgos.md")

        self.assertIn("promovido a P-ID", hallazgos)
        self.assertIn("antes de crear otra unidad", hallazgos.lower())

    def test_investigacion_acotada_se_sintetiza_antes_de_la_spec(self):
        peticiones = self.texto("docs/00-metodo/runbooks/peticiones.md").lower()

        posicion_acotada = peticiones.index("investigación acotada")
        posicion_sintesis = peticiones.index("síntesis", posicion_acotada)
        posicion_unidad = peticiones.index("unidad.py nueva", posicion_sintesis)
        self.assertLess(posicion_acotada, posicion_sintesis)
        self.assertLess(posicion_sintesis, posicion_unidad)

    def test_agents_no_anuncia_tope_numerico_de_paralelismo(self):
        # ADR-027, R4: la regla 5 de AGENTS.md debe describir "sin tope numérico" y ya
        # no puede mencionar el antiguo tope de 3 unidades en vuelo.
        agents = self.texto("AGENTS.md")

        self.assertIn("sin tope numérico", agents)
        self.assertNotIn("tope 3", agents)

    def test_regla_cinco_manda_paralelizar_por_defecto_y_una_suite_a_la_vez(self):
        """099 R3 y R5: la regla 5 dice lo mismo que hace el script —paralelo por
        defecto, el freno es el cruce de ficheros— y escribe el único límite que el
        script no puede imponer porque no ve las otras sesiones: una suite a la vez."""
        agents = self.texto("AGENTS.md")
        duras = agents[agents.index("## Reglas duras"):]
        regla = duras[duras.index("\n5. **"):duras.index("\n6. **")].lower()

        self.assertIn("en paralelo", regla)
        self.assertIn("no compartan ficheros", regla)
        self.assertIn("una suite completa a la vez", regla)
        self.assertIn("en_validacion", regla)
        self.assertIn("documental", regla)
        self.assertNotIn("una unidad de código por defecto", regla)

    def test_roles_y_readme_no_limitan_las_unidades_en_vuelo(self):
        """099 R3: el CONSTRUCTOR ya no tiene prohibido «abrir más de 1 unidad en
        vuelo», y el README cuenta el paralelismo como norma."""
        roles = self.texto("docs/00-metodo/roles.md")
        readme = self.texto("docs/00-metodo/README.md")

        self.assertNotIn("abrir más de 1 unidad en vuelo", roles)
        self.assertIn("un subagente por unidad", roles.lower())
        self.assertIn("en paralelo", readme.lower())
        self.assertNotIn("o si ya hay trabajo en vuelo", readme)

    def test_adr_036_existe_y_viaja_en_el_manifiesto_del_bootstrap(self):
        """099 R3: una decisión que no viaja en `bootstrap.py` no llega a ningún
        workspace nuevo, así que no existe para nadie salvo para este repo."""
        adr = self.texto("docs/00-metodo/decisiones/036-paralelizar-por-defecto.md")
        bootstrap = (RAIZ / "visor/bootstrap.py").read_text(encoding="utf-8")

        self.assertIn("ADR-036", adr)
        self.assertIn("036-paralelizar-por-defecto.md", bootstrap)

    def test_runbooks_no_abren_unidades_sin_desde(self):
        runbooks = RAIZ / "plantilla/docs/00-metodo/runbooks"
        infracciones = []
        for ruta in sorted(runbooks.glob("*.md")):
            for numero, linea in enumerate(
                ruta.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "unidad.py nueva" in linea and "--desde" not in linea:
                    infracciones.append(f"{ruta.name}:{numero}")
        self.assertEqual(infracciones, [], infracciones)


def cargar_modulo_unidad():
    """Importa unidad.py con sus módulos hermanos resolubles. Una vez por proceso."""
    if "unidad" in sys.modules:
        return sys.modules["unidad"]
    sys.path.insert(0, str(SCRIPTS))
    try:
        return importlib.import_module("unidad")
    finally:
        sys.path.remove(str(SCRIPTS))


class SalidaDelTrabajoProbadaTest(unittest.TestCase):
    """Regresión de la auditoría adversaria 2026-08-03, hallazgos 1 y 2.

    Hallazgo 1: `rama_mergeada` devolvía True cuando la rama YA NO EXISTÍA («cierre a
    medias: sigo con lo que falta»), así que un `git branch -D` sin fusionar se archivaba
    como `mergeada` — pérdida de trabajo con acta de entrega. Hallazgo 2: la puerta de
    paralelismo comparaba cadenas sin normalizar, y `api/x.py`, `./api/x.py` y `API/x.py`
    pasaban por tres ficheros disjuntos.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="salida-trabajo-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "main"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.unidad = cargar_modulo_unidad()

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace"
        ).stdout.strip()

    def commit_en_rama(self, rama="001-perdida"):
        self.git("checkout", "-b", rama)
        (self.repo / "trabajo.txt").write_text("trabajo\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "Edicion de paquetes (R1-R3)")
        self.git("checkout", "main")
        return rama

    def test_rama_borrada_sin_fusionar_no_cuenta_como_mergeada(self):
        rama = self.commit_en_rama()
        self.git("branch", "-D", rama)

        mergeada, motivo, fuerte, sha = self.unidad.rama_mergeada(self.repo, rama, "main")

        self.assertFalse(mergeada, motivo)
        self.assertFalse(fuerte)
        self.assertIn("NO prueba", motivo)

    def test_rama_viva_sin_fusionar_tampoco(self):
        rama = self.commit_en_rama()

        mergeada, motivo, fuerte, _ = self.unidad.rama_mergeada(self.repo, rama, "main")

        self.assertFalse(mergeada, motivo)
        self.assertIn("NO está fusionada", motivo)

    def test_rama_fusionada_da_prueba_fuerte(self):
        rama = self.commit_en_rama()
        self.git("merge", "--ff-only", rama)

        mergeada, motivo, fuerte, sha = self.unidad.rama_mergeada(self.repo, rama, "main")

        self.assertTrue(mergeada, motivo)
        self.assertTrue(fuerte)
        self.assertEqual(sha, self.git("rev-parse", rama))

    def test_fusion_anotada_reanuda_un_cierre_sin_rama(self):
        rama = self.commit_en_rama()
        self.git("merge", "--ff-only", rama)
        sha = self.git("rev-parse", "main")
        self.git("branch", "-d", rama)

        mergeada, motivo, fuerte, _ = self.unidad.rama_mergeada(
            self.repo, rama, "main", fusion_declarada=sha
        )

        self.assertTrue(mergeada, motivo)
        self.assertTrue(fuerte)

    def test_squash_borrada_es_prueba_debil_y_lo_dice(self):
        rama = self.commit_en_rama("002-squash")
        self.git("merge", "--squash", rama)
        self.git("commit", "-m", f"{rama}: edición de paquetes")
        self.git("branch", "-D", rama)

        mergeada, motivo, fuerte, _ = self.unidad.rama_mergeada(self.repo, rama, "main")

        self.assertTrue(mergeada, motivo)
        self.assertFalse(fuerte)
        self.assertIn("INDIRECTA", motivo)

    def test_ficheros_de_unifica_grafias_del_mismo_fichero(self):
        fm = {"ficheros": "[api/x.py, ./api/x.py, API/x.py, api\\x.py]"}

        self.assertEqual(self.unidad.ficheros_de(fm), {"api/x.py"})


class SenalesDeRiesgoTest(unittest.TestCase):
    """Unidad 070: el riesgo se lee en lo que toca el cambio, no en cuántas líneas tiene.

    El carril directo se decidía por tamaño (1-3 ficheros, 250 líneas) y los hotspots eran
    una lista en prosa de `runbooks/directo.md` que solo recordaba quien redactaba la ficha.
    Aquí se comprueba la tabla ejecutable que la sustituye.
    """

    def setUp(self):
        self.unidad = cargar_modulo_unidad()
        self.tabla = self.unidad.cargar_senales(
            RAIZ / "plantilla/docs/00-metodo/senales-de-riesgo.json"
        )
        self.tmp = tempfile.TemporaryDirectory(prefix="senales-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "codigo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "notas.txt").write_text("base\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        ).stdout.strip()

    def commit(self, relativa, contenido):
        destino = self.repo / relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", f"toca {relativa}")
        return self.git("rev-parse", "HEAD")

    # ------------------------------------------------------------------ R1 · la tabla
    def test_la_tabla_es_valida_y_lleva_los_hotspots_que_directo_md_listaba(self):
        ids = [senal.id for senal in self.tabla]
        self.assertEqual(len(ids), len(set(ids)), "ids repetidos en senales-de-riesgo.json")
        for senal in self.tabla:
            self.assertIn(senal.nivel, ("alta", "informativa"))
            self.assertTrue(senal.nombre.strip(), f"{senal.id} sin nombre humano")
            self.assertTrue(senal.rutas or senal.contenido,
                            f"{senal.id} no tiene ni un patrón: no puede casar nunca")
        for hotspot in ("migraciones", "rutas", "modelos-compartidos", "lockfiles"):
            self.assertIn(hotspot, ids)

    def test_directo_md_remite_al_fichero_en_vez_de_repetir_la_lista(self):
        runbook = (RAIZ / "plantilla/docs/00-metodo/runbooks/directo.md").read_text(
            encoding="utf-8")
        self.assertIn("senales-de-riesgo.json", runbook)

    # ------------------------------------------- R2 · la señal por ruta y por contenido
    def test_la_ruta_declarada_basta_para_cantar_la_senal(self):
        detectadas = self.unidad.senales_del_diff(
            ficheros=["main/app/pagos/checkout.py"], senales=self.tabla)

        self.assertEqual([d.id for d in detectadas], ["dinero"])
        self.assertEqual(detectadas[0].nivel, "alta")
        self.assertIsNone(detectadas[0].linea)

    def test_el_contenido_del_diff_canta_aunque_la_ruta_sea_inocente(self):
        punta = self.commit(
            "app/util.py",
            "def limpiar(nombre):\n    os.system(\"rm -rf \" + nombre)\n",
        )

        detectadas = self.unidad.senales_del_diff(
            repo=self.repo, base=self.base, punta=punta, senales=self.tabla)

        ids = {d.id for d in detectadas}
        self.assertIn("comandos-de-sistema", ids)
        comando = next(d for d in detectadas if d.id == "comandos-de-sistema")
        self.assertEqual(comando.nivel, "alta")
        self.assertEqual(comando.ruta, "app/util.py")
        self.assertEqual(comando.linea, 2)

    def test_el_mensaje_del_rechazo_nombra_senal_fichero_y_comando(self):
        detectadas = self.unidad.senales_del_diff(
            ficheros=["main/app/auth/login.py"], senales=self.tabla)

        mensaje = self.unidad.mensaje_senales_altas("001-x", detectadas)

        self.assertIn("acceso y autenticación", mensaje)
        self.assertIn("main/app/auth/login.py", mensaje)
        self.assertIn("unidad.py despachar 001-x", mensaje)
        self.assertIn("senales-de-riesgo.json", mensaje)

        # Tras la rama la salida es OTRA: reencuadrar, no corregir la ficha (H1).
        con_rama = self.unidad.mensaje_senales_altas("001-x", detectadas, tras_la_rama=True)
        self.assertIn("unidad.py reencuadrar 001-x --carril normal", con_rama)
        self.assertNotIn("unidad.py despachar 001-x", con_rama)

    # --------------------------------------------------- R4 · sin señales, nada cambia
    def test_sin_senales_no_hay_deteccion_alguna(self):
        punta = self.commit("docs/manual.md", "# Manual\n\nUn párrafo.\n")

        self.assertEqual(
            self.unidad.senales_del_diff(repo=self.repo, base=self.base, punta=punta,
                                         ficheros=["main/docs/manual.md"],
                                         senales=self.tabla),
            [],
        )

    def test_un_nombre_de_fichero_suelto_no_es_un_hotspot(self):
        """H2 — los cinco ejemplos que la revisión encontró dando ALTA sin tocar nada.

        La frontera ancha que R5 necesitaba (`test_login.py`) hacía que los hotspots casaran
        contra NOMBRES sueltos y contra documentación: un directo que editaba `docs/api.md`
        se rechazaba, y eso es justo lo que R4 prohíbe («un texto pasa exactamente como hoy»).
        Los hotspots casan por segmento de ruta o por fichero de código, nunca por el nombre.
        """
        for inocente in ("docs/api.md", "docs/api-reference.md", "docs/roles.md",
                         "docs/models.md", "hot-keys.js"):
            with self.subTest(fichero=inocente):
                self.assertEqual(
                    self.unidad.senales_del_diff(ficheros=[inocente], senales=self.tabla), [],
                    f"{inocente} no toca nada delicado y no puede cerrar el carril directo")

    def test_el_hotspot_sigue_cantando_donde_de_verdad_vive(self):
        """El otro lado de H2: acotar no puede dejar la señal sin morder."""
        for ruta, esperado in (("app/routes.py", "rutas"),
                               ("app/routes/publicas.py", "rutas"),
                               ("app/models.py", "modelos-compartidos"),
                               ("db/migrations/001_inicial.sql", "migraciones"),
                               ("package-lock.json", "lockfiles"),
                               ("app/secrets.py", "secretos")):
            with self.subTest(fichero=ruta):
                detectadas = self.unidad.senales_del_diff(ficheros=[ruta], senales=self.tabla)
                self.assertEqual([(d.id, d.nivel) for d in detectadas], [(esperado, "alta")])

    def test_un_secreto_pegado_en_un_markdown_sigue_cantando_por_contenido(self):
        """La exclusión de H2 es solo para los patrones de RUTA: el contenido sigue vivo."""
        punta = self.commit("README.md", "# Guía\n\n    API_KEY = sk-live-1234\n")

        detectadas = self.unidad.senales_del_diff(
            repo=self.repo, base=self.base, punta=punta, senales=self.tabla)

        self.assertEqual([(d.id, d.ruta, d.linea) for d in detectadas],
                         [("secretos", "README.md", 3)])

    # --------------------------------------------- R5 · dentro de tests, solo informa
    def test_una_senal_dentro_de_tests_baja_a_informativa(self):
        detectadas = self.unidad.senales_del_diff(
            ficheros=["main/tests/test_login.py", "main/app/fixtures/pagos.json"],
            senales=self.tabla)

        self.assertEqual(
            {(d.id, d.ruta) for d in detectadas},
            {("acceso", "main/tests/test_login.py"),
             ("dinero", "main/app/fixtures/pagos.json")},
        )
        self.assertEqual({d.nivel for d in detectadas}, {"informativa"})

    # --------------------------------------- R3 · el encargo del revisor lleva el foco
    def test_el_encargo_del_revisor_lleva_las_senales_con_fichero_y_linea(self):
        sys.path.insert(0, str(SCRIPTS))
        try:
            ejecucion = importlib.import_module("ejecucion")
        finally:
            sys.path.remove(str(SCRIPTS))
        detectadas = [
            self.unidad.Deteccion("acceso", "acceso y autenticación", "alta",
                                  "app/auth/login.py", 12),
            self.unidad.Deteccion("lockfiles", "ficheros de bloqueo de dependencias "
                                  "(hotspot)", "alta", "package-lock.json", None),
        ]
        argumentos = ("001-x", "revisor", Path("docs/05-trabajo/001-x/especificacion.md"),
                      "Revisa el diff", (), Path.home())

        con = ejecucion.encargo(*argumentos, senales=detectadas)
        sin = ejecucion.encargo(*argumentos, senales=())

        self.assertIn("Señales de riesgo detectadas", con)
        self.assertIn("app/auth/login.py:12", con)
        self.assertIn("package-lock.json", con)
        # R4: sin señales el encargo es el de hoy, byte a byte.
        self.assertEqual(sin, ejecucion.encargo(*argumentos))
        self.assertNotIn("Señales de riesgo", sin)

    # ------------------------------------------------------- R6 · rechazos en banda
    def test_los_rechazos_nuevos_estan_en_banda(self):
        guardian = SCRIPTS / "lint_salidas.py"
        resultado = subprocess.run(
            [sys.executable, str(guardian)], cwd=RAIZ / "plantilla",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)


if __name__ == "__main__":
    unittest.main()


class EstadoParalelismoTest(unittest.TestCase):
    """099 R4: `unidad.py estado` es lo que el padre mira antes de repartir trabajo.

    Hasta ADR-036 avisaba de «N unidades en vuelo» como si fuera una anomalía —lo que
    ahora es la norma— y no decía quién las está construyendo, aunque el recibo del
    subagente ya estuviera escrito en `.runtime/ejecuciones/`.
    """

    def setUp(self):
        self.modulo = cargar_modulo_unidad()
        self.tmp = tempfile.TemporaryDirectory(prefix="estado-paralelo-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name).resolve()
        (self.raiz / "docs/05-trabajo").mkdir(parents=True)
        (self.raiz / "docs/bugs").mkdir(parents=True)
        (self.raiz / "worktrees").mkdir()
        for parche in (
            mock.patch.object(self.modulo, "RAIZ", self.raiz),
            mock.patch.object(self.modulo, "TRABAJO", self.raiz / "docs/05-trabajo"),
            mock.patch.object(self.modulo, "ARCHIVO", self.raiz / "docs/05-trabajo/archivo"),
            mock.patch.object(self.modulo, "BUGS", self.raiz / "docs/bugs"),
            mock.patch.object(self.modulo, "WORKTREES", self.raiz / "worktrees"),
            mock.patch.object(self.modulo, "siguiente_nnn", lambda: ("999", {})),
            mock.patch.object(self.modulo, "repo_codigo", lambda: (self.raiz, "main")),
        ):
            parche.start()
            self.addCleanup(parche.stop)

    def unidad_en_obra(self, nombre, ficheros):
        carpeta = self.raiz / "docs/05-trabajo" / nombre
        carpeta.mkdir(parents=True)
        (self.raiz / "worktrees" / nombre).mkdir(exist_ok=True)
        (carpeta / "especificacion.md").write_text(
            "---\n"
            f"unidad: {nombre}\n"
            "tipo: feature\ncarril: normal\nestado: en_obra\n"
            "aprobado: 2026-08-27\nactividad: REC-1\n"
            f"ficheros: [{', '.join(ficheros)}]\n"
            "peticiones: []\nactualizado: 2026-08-27\n---\n\n# Contrato\n",
            encoding="utf-8",
        )

    def recibo_de_subagente(self, nombre, modelo="claude-opus-5"):
        ruta = self.raiz / ".runtime/ejecuciones"
        ruta.mkdir(parents=True, exist_ok=True)
        (ruta / f"{nombre}-abc123.json").write_text(json.dumps({
            "schema": "ejecucion/v1", "id": "abc123", "unidad": nombre,
            "harness": "subagente-del-padre", "rol": "constructor",
            "modelo": modelo, "esfuerzo": "medio", "exit_code": None,
        }), encoding="utf-8")

    def estado(self):
        salida, errores = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            codigo = self.modulo.cmd_estado(None)
        return codigo, salida.getvalue() + errores.getvalue()

    def test_tres_unidades_en_vuelo_no_se_denuncian_como_anomalia(self):
        for numero, fichero in enumerate(("a.py", "b.py", "c.py"), start=1):
            self.unidad_en_obra(f"10{numero}-paralela-{numero}", [fichero])

        codigo, salida = self.estado()

        self.assertEqual(codigo, 0, salida)
        self.assertIn("3 unidades en vuelo", salida)
        self.assertNotIn("WARN", salida.split("Coherencia:")[1].split("Siguiente NNN")[0])
        self.assertIn("101-paralela-1", salida)

    def test_estado_enseña_el_subagente_de_cada_unidad_por_su_recibo(self):
        self.unidad_en_obra("101-con-recibo", ["a.py"])
        self.unidad_en_obra("102-sin-recibo", ["b.py"])
        self.recibo_de_subagente("101-con-recibo", modelo="claude-opus-5")

        codigo, salida = self.estado()

        self.assertEqual(codigo, 0, salida)
        linea = next(l for l in salida.splitlines() if "101-con-recibo" in l
                     and "subagente" in l)
        self.assertIn("claude-opus-5", linea)
        self.assertNotIn(
            "subagente",
            next(l for l in salida.splitlines()
                 if l.strip().startswith("102-sin-recibo")),
        )


class PuertaAprobacionWebTest(unittest.TestCase):
    """Unidad 107, R5 — `despachar` deja de creerse una fecha escrita a mano.

    Nivel unitario, que es el que declara §Verificación del contrato: la decisión vive
    en `puerta_aprobacion_web(nombre, aprobado)` y aquí se prueba directamente, sin
    montar un workspace entero. La fecha desde la que se exige (`APROBACION_WEB_DESDE`)
    se mueve en el test porque lo que se prueba es la REGLA, no el calendario.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="puerta-aprobacion-web-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        spec = importlib.util.spec_from_file_location(
            "unidad_puerta_web", SCRIPTS / "unidad.py")
        self.unidad_mod = importlib.util.module_from_spec(spec)
        sys.modules["unidad_puerta_web"] = self.unidad_mod
        spec.loader.exec_module(self.unidad_mod)
        self.unidad_mod.RAIZ = self.ws
        self.unidad_mod.APROBACION_WEB_DESDE = "2026-01-01"

    def dejar_clic(self, nombre, fecha, **cambios):
        """Lo que escribe `web/servir.py` cuando el usuario pulsa Aprobar (unidad 107)."""
        carpeta = self.ws / ".runtime" / "aprobaciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        datos = {"unidad": nombre, "fecha": fecha,
                 "ruta": f"docs/05-trabajo/{nombre}/especificacion.md",
                 "huella": "0" * 64, "hora": f"{fecha}T09:00:00",
                 "cliente": "127.0.0.1"}
        datos.update(cambios)
        (carpeta / f"{nombre}-{fecha}.json").write_text(
            json.dumps(datos), encoding="utf-8")

    def test_una_fecha_sin_clic_bloquea_y_manda_a_la_web(self):
        problema, nota = self.unidad_mod.puerta_aprobacion_web(
            "001-fecha-tecleada", "2026-06-01")
        self.assertIsNotNone(problema)
        self.assertIn(".runtime/aprobaciones", problema)
        self.assertIn("SALIDA:", problema)
        self.assertIn("web/abrir.py", problema)
        self.assertIsNone(nota)

    def test_con_el_clic_del_usuario_pasa_y_lo_dice(self):
        self.dejar_clic("001-clic-de-verdad", "2026-06-01")
        problema, nota = self.unidad_mod.puerta_aprobacion_web(
            "001-clic-de-verdad", "2026-06-01")
        self.assertIsNone(problema, problema)
        self.assertIn("pulsó Aprobar en la web", nota)

    def test_un_clic_posterior_a_la_fecha_aprobada_no_cuenta(self):
        """Mismo criterio que el rastro del visor (bug 054): pulsar el botón DESPUÉS de
        haber escrito la fecha no prueba que la fecha saliera del botón."""
        self.dejar_clic("001-tardio", "2026-06-05")
        problema, _ = self.unidad_mod.puerta_aprobacion_web("001-tardio", "2026-06-01")
        self.assertIsNotNone(problema)

    def test_el_rastro_de_otra_unidad_no_sirve(self):
        self.dejar_clic("001-otra", "2026-06-01")
        problema, _ = self.unidad_mod.puerta_aprobacion_web("001-mia", "2026-06-01")
        self.assertIsNotNone(problema)

    def test_un_rastro_con_el_nombre_de_otra_unidad_dentro_no_cuela(self):
        """El fichero se llama como la unidad, pero dentro dice otra: el contenido manda."""
        self.dejar_clic("001-mia", "2026-06-01", unidad="001-otra")
        problema, _ = self.unidad_mod.puerta_aprobacion_web("001-mia", "2026-06-01")
        self.assertIsNotNone(problema)

    def test_un_rastro_ilegible_no_acredita_nada(self):
        carpeta = self.ws / ".runtime" / "aprobaciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "001-rota-2026-06-01.json").write_text("{", encoding="utf-8")
        problema, _ = self.unidad_mod.puerta_aprobacion_web("001-rota", "2026-06-01")
        self.assertIsNotNone(problema)

    def test_lo_aprobado_antes_de_que_existiera_la_puerta_sigue_valiendo(self):
        """R5, la otra mitad: la puerta no invalida a posteriori lo que se aprobó cuando
        el botón todavía no existía."""
        problema, nota = self.unidad_mod.puerta_aprobacion_web(
            "001-vieja", "2025-12-31")
        self.assertIsNone(problema)
        self.assertIsNone(nota)

    def test_la_fecha_desde_la_que_se_exige_es_la_de_la_fusion_de_la_107(self):
        """El valor de verdad, sin monkeypatch: si alguien lo adelanta, invalida de golpe
        todo lo ya aprobado del workspace; si lo retrasa, la puerta no llega nunca."""
        self.assertRegex(
            (SCRIPTS / "unidad.py").read_text(encoding="utf-8"),
            r'APROBACION_WEB_DESDE = "2026-08-2[78]"')
