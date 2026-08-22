import importlib
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
from pathlib import Path


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
            "control_plane.py", "lease.py", "peticion.py", "repo_config.py",
            "unidad.py", "workspace_paths.py",
        ):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.peticion = scripts / "peticion.py"
        self.unidad = scripts / "unidad.py"

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
            text=True, capture_output=True,
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

    def aprobar_para_despacho(self, nombre):
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        texto = ruta.read_text(encoding="utf-8")
        texto = re.sub(
            r"^aprobado:.*$",
            f"aprobado: {datetime.date.today().isoformat()}",
            texto,
            count=1,
            flags=re.M,
        )
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
            "- **Nivel de test:** unitario, porque la conducta es una regla local.\n"
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
        for rol, sesion in (("constructor", "sesion-constructor"), ("revisor", "sesion-revisor")):
            (carpeta / f"{nombre}-{rol}.json").write_text(json.dumps({
                "schema": "ejecucion/v1", "id": rol, "unidad": nombre,
                "harness": "claude", "rol": rol, "modelo": f"modelo-{rol}",
                "lease": {"session_id": sesion, "fencing": {}},
                "checkpoints": [], "exit_code": 0, "resultado": "ok",
            }), encoding="utf-8")

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
                text=True,
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
        ficha.symlink_to(exterior)

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
        ficha.parent.symlink_to(exterior, target_is_directory=True)

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

    def test_despacho_normal_entrega_el_launcher_canonico(self):
        pid = self.capturar()
        self.evaluar(pid)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", "lanzamiento", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stderr)
        self.aprobar_para_despacho("001-lanzamiento")

        resultado = self.ejecutar(self.unidad, "despachar", "001-lanzamiento")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ejecucion.py lanzar 001-lanzamiento", resultado.stdout)
        self.assertIn(
            str((self.ws / "docs/00-metodo/scripts/ejecucion.py").resolve()),
            resultado.stdout,
        )
        self.assertIn("--harness claude", resultado.stdout)
        self.assertIn("--harness codex", resultado.stdout)
        self.assertIn("--rol constructor", resultado.stdout)
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
            (worktree / ".entorno-preparado").read_text(),
            "preparado",
        )
        self.assertTrue(
            os.path.samefile((worktree / ".arg-recibido").read_text(), worktree),
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
        (self.ws / "worktree-listo").symlink_to(objetivo)

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
        self.recibos_de_revision("001-cierre-ordenado")
        linter = self.ws / "docs/00-metodo/scripts/lint_metodo.py"
        linter.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "raiz = Path(__file__).resolve().parents[3]\n"
            "activa = raiz / 'docs/05-trabajo/001-cierre-ordenado/especificacion.md'\n"
            "sys.exit(1 if activa.exists() and 'estado: mergeada' in activa.read_text() else 0)\n",
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
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json").read_text()
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
            text=True,
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
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json").read_text()
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
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json").read_text()
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
            text=True, capture_output=True,
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
            (self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json").read_text()
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
            text=True,
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
            text=True,
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
            text=True, capture_output=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-b", nombre], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("base\ncambio\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "cambio"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", nombre], cwd=repo, check=True, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, capture_output=True,
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
            text=True, capture_output=True,
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
            text=True, capture_output=True,
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
            text=True, capture_output=True,
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
            text=True, capture_output=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-b", nombre], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("base\ncambio\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "cambio"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "merge", "--ff-only", nombre], cwd=repo, check=True, capture_output=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, capture_output=True,
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
            text=True, capture_output=True,
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
        self.assertIn("subagente constructor", agents)

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
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
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


if __name__ == "__main__":
    unittest.main()
