import importlib.util
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import ayuda_windows  # noqa: E402 - módulo hermano de la suite


RAIZ = Path(__file__).resolve().parents[2]
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
ACTUALIZAR = RAIZ / "visor/actualizar.py"
PROYECTOS = RAIZ / "visor/proyectos.py"


borrar_arbol = ayuda_windows.borrar_arbol


def borrar_tmp_silencioso(ruta):
    """Cleanup del temporal de un test: en Windows un fichero recién reemplazado
    por una escritura atómica puede seguir retenido; eso es ruido de cleanup, no
    un fallo del test. (ignore_cleanup_errors de TemporaryDirectory es 3.10+.)"""
    shutil.rmtree(ruta, ignore_errors=True)


class PeticionBootstrapActualizarTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="peticion-distribucion-"))
        self.addCleanup(borrar_tmp_silencioso, self.base)
        self.entorno = dict(os.environ)
        self.entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(
            self.base / "registro-suite.json"
        )

    def ejecutar(self, script, *args):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=RAIZ,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env=self.entorno,
        )

    def proceso_actualizar_con_failpoint(self, nombre, ws):
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
        env["IR_SESSION_ID"] = f"modo-d-{uuid.uuid4()}"
        proceso = subprocess.Popen(
            [sys.executable, str(ACTUALIZAR), "aplicar", str(ws)],
            cwd=RAIZ,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.addCleanup(lambda: proceso.poll() is None and proceso.kill())
        self._proceso = proceso
        return proceso, ready, gate

    def esperar_barrera(self, ready, timeout=40):
        # 40 s (ronda 2 del bug 017: 20 s seguía siendo insuficiente en runners
        # windows-latest compartidos y con carga variable — flakeo observado en
        # el run 32083456376, job py3.13): en Windows el CI arranca un
        # intérprete nuevo y hace todo el trabajo de Modo D hasta el failpoint;
        # 3 s no le llegaban, y 20 s tampoco siempre.
        proceso = getattr(self, "_proceso", None)
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if ready.exists():
                return
            if proceso is not None and proceso.poll() is not None:
                salida, err = proceso.communicate()
                self.fail(f"Modo D murió antes del failpoint: {salida}{err}")
            time.sleep(0.01)
        self.fail("Modo D no alcanzó el failpoint")

    def abrir_barrera(self, gate):
        gate.write_text("1", encoding="ascii")

    def entrada_journal(self, contenido, modo=0o644):
        return {
            "contenido": base64.b64encode(contenido).decode("ascii"),
            "modo": modo,
            "sha256": hashlib.sha256(contenido).hexdigest(),
        }

    def escribir_journal(self, ws, snapshot, *, published=None, fase="escribiendo", **extra):
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()
        datos = {
            "formato": 2,
            "operacion": "modo-d",
            "id": str(uuid.uuid4()),
            "fase": fase,
            "punto_retorno": head,
            "snapshot": snapshot,
            "publicado": published if published is not None else snapshot,
            "arbol_publicado": None,
            "commit": None,
        }
        datos.update(extra)
        journal = ws / ".runtime/transactions/modo-d.json"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps(datos), encoding="utf-8")
        return journal

    def planos_minimos(self):
        proyecto = self.base / "planos"
        (proyecto / "especificaciones/01-constitution").mkdir(parents=True)
        (proyecto / "especificaciones/02-flows").mkdir()
        (proyecto / "planos.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "proyecto": "demo",
                    "titulo": "Demo",
                    "contrato": {"frase": "Una demostración"},
                    "actividades": [],
                }
            ),
            encoding="utf-8",
        )
        (proyecto / "especificaciones/01-constitution/constitution.md").write_text(
            "# Constitución\n", encoding="utf-8"
        )
        return proyecto

    def test_bootstrap_publica_peticiones_y_nace_estricto(self):
        destino = self.base / "demo-agents"

        resultado = self.ejecutar(
            BOOTSTRAP,
            "--planos",
            str(self.planos_minimos()),
            "--destino",
            str(destino),
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertTrue((destino / "docs/00-metodo/scripts/peticion.py").is_file())
        self.assertTrue((destino / "docs/00-metodo/scripts/lease.py").is_file())
        self.assertTrue((destino / "docs/00-metodo/scripts/ejecucion.py").is_file())
        self.assertTrue(
            (destino / "docs/00-metodo/decisiones/022-control-plane-de-ejecucion.md").is_file()
        )
        # ADR-027, R1: la tupla DECISIONES se olvidó de propagar el 027 la primera vez.
        adr_027 = destino / "docs/00-metodo/decisiones/027-sin-tope-numerico-de-paralelismo.md"
        self.assertTrue(adr_027.is_file())
        self.assertIn("tope", adr_027.read_text(encoding="utf-8").lower())
        self.assertTrue((destino / "docs/05-trabajo/peticiones").is_dir())
        self.assertFalse(
            (destino / "docs/05-trabajo/peticiones/LEGACY.json").exists()
        )
        # Unidad 018: la política de publicación nace documentada en el repos.yaml, con sus
        # dos valores. Si no se genera, nadie descubre nunca que el modo existe.
        repos = (destino / "repos.yaml").read_text(encoding="utf-8")
        self.assertRegex(repos, r"(?m)^\s*push:\s*agente")
        self.assertIn("usuario", repos)
        lint = self.ejecutar(destino / "docs/00-metodo/scripts/lint_metodo.py")
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_workspace_virgen_arranca_sin_semaforos_rojos_permanentes(self):
        # Familia 004/018: un linter que FALLA sobre un workspace recién nacido, cuando la
        # condición que vigila no aplica todavía, enseña a convivir con el rojo. Los dos
        # linters de arranque/merge deben salir en verde. El gate de deploy es aparte: solo
        # se corre al desplegar, y su único rojo permitido en un workspace virgen es el del
        # plano de deploy sin decidir — deliberado (bootstrap, PLANOS_OPERATIVOS) y con
        # instrucciones que SÍ lo quitan (runbooks/primer-despliegue.md). Nada estructural.
        destino = self.base / "virgen-agents"
        resultado = self.ejecutar(
            BOOTSTRAP, "--planos", str(self.planos_minimos()), "--destino", str(destino)
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

        lint = self.ejecutar(destino / "docs/00-metodo/scripts/lint_metodo.py")
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        self.assertIn("arsenal del método completo", lint.stdout)

        ci = self.ejecutar(
            destino / "docs/00-metodo/scripts/lint_ci.py", "--repo", str(destino / "main")
        )
        self.assertEqual(ci.returncode, 0, ci.stdout + ci.stderr)

        deploy = self.ejecutar(destino / "docs/00-metodo/scripts/lint_deploy.py")
        fails = [
            linea for linea in deploy.stdout.splitlines()
            if linea.strip().startswith("FAIL")
        ]
        self.assertEqual(len(fails), 1, deploy.stdout)
        self.assertIn("plano-deploy.md sin decidir", fails[0])

    def test_setup_y_lint_rechazan_ruta_local_con_escape_o_symlink(self):
        destino = self.base / "rutas-agents"
        resultado = self.ejecutar(
            BOOTSTRAP, "--planos", str(self.planos_minimos()), "--destino", str(destino)
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        externo = self.base / "codigo-externo"
        externo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=externo, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=externo, check=True)
        repos = destino / "repos.yaml"
        original = repos.read_text(encoding="utf-8")
        repos.write_text(
            re.sub(r"ruta_local:\s*\S+", "ruta_local: ../codigo-externo", original),
            encoding="utf-8",
        )

        setup = self.ejecutar(destino / "setup.py")
        lint = self.ejecutar(destino / "docs/00-metodo/scripts/lint_metodo.py")

        self.assertNotEqual(setup.returncode, 0, setup.stdout + setup.stderr)
        self.assertIn("ruta_local", (setup.stdout + setup.stderr).lower())
        self.assertNotEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        self.assertIn("ruta_local", (lint.stdout + lint.stderr).lower())

        repos.write_text(original, encoding="utf-8")
        main = destino / "main"
        if main.is_dir() and not main.is_symlink():
            borrar_arbol(main)
        ayuda_windows.enlazar_o_saltar(self, main, externo, directorio=True)
        lint_symlink = self.ejecutar(destino / "docs/00-metodo/scripts/lint_metodo.py")
        self.assertNotEqual(lint_symlink.returncode, 0, lint_symlink.stdout + lint_symlink.stderr)
        salida_lint = (lint_symlink.stdout + lint_symlink.stderr).lower()
        self.assertIn("no admite enlaces", salida_lint)
        self.assertIn("ruta_local", salida_lint)

    def test_depurar_registro_es_dry_run_y_solo_olvida_rutas_ausentes(self):
        registro = self.base / "registro-aislado.json"
        existente = self.base / "workspace-real"
        existente.mkdir()
        ausente = self.base / "workspace-borrado"
        registro.write_text(
            json.dumps(
                {
                    "formato": 1,
                    "proyectos": [
                        {"ruta": str(existente), "titulo": "Real", "huella": "a"},
                        {"ruta": str(ausente), "titulo": "Viejo", "huella": "b"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        entorno = dict(os.environ)
        entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(registro)

        previo = registro.read_bytes()
        dry_run = subprocess.run(
            [sys.executable, str(PROYECTOS), "depurar"],
            cwd=RAIZ,
            env=entorno,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertEqual(registro.read_bytes(), previo)
        self.assertIn(str(ausente), dry_run.stdout)

        aplicar = subprocess.run(
            [sys.executable, str(PROYECTOS), "depurar", "--aplicar"],
            cwd=RAIZ,
            env=entorno,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )
        self.assertEqual(aplicar.returncode, 0, aplicar.stdout + aplicar.stderr)
        datos = json.loads(registro.read_text(encoding="utf-8"))
        self.assertEqual([p["ruta"] for p in datos["proyectos"]], [str(existente)])

    def test_registro_rechaza_dos_clones_vivos_del_mismo_meta_remoto(self):
        registro = self.base / "registro-remotos.json"
        entorno = dict(os.environ)
        entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(registro)
        clones = []
        for nombre in ("original-agents", "copia-agents"):
            workspace = self.base / nombre
            (workspace / "docs/02-flujos/planos").mkdir(parents=True)
            (workspace / "AGENTS.md").write_text("# Demo\n", encoding="utf-8")
            (workspace / "docs/02-flujos/planos/planos.json").write_text(
                json.dumps({"titulo": nombre}), encoding="utf-8"
            )
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=workspace, check=True)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=workspace, check=True)
            subprocess.run(
                [
                    "git",
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:nategentile/demo-agents.git",
                ],
                cwd=workspace,
                check=True,
            )
            clones.append(workspace)

        primero = subprocess.run(
            [sys.executable, str(PROYECTOS), "registrar", str(clones[0])],
            cwd=RAIZ,
            env=entorno,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )
        segundo = subprocess.run(
            [sys.executable, str(PROYECTOS), "registrar", str(clones[1])],
            cwd=RAIZ,
            env=entorno,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )
        self.assertEqual(primero.returncode, 0, primero.stdout + primero.stderr)
        self.assertNotEqual(segundo.returncode, 0)
        self.assertIn("mismo remoto", segundo.stdout + segundo.stderr)
        datos = json.loads(registro.read_text(encoding="utf-8"))
        self.assertEqual(len(datos["proyectos"]), 1)
        self.assertEqual(datos["proyectos"][0]["ruta"], str(clones[0].resolve()))

    def test_registro_concurrente_no_pierde_altas(self):
        registro = self.base / "registro-concurrente.json"
        entorno = dict(os.environ)
        entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(registro)
        procesos = []
        total = 24
        for numero in range(total):
            workspace = self.base / f"workspace-{numero:02d}"
            (workspace / "docs/02-flujos/planos").mkdir(parents=True)
            (workspace / "AGENTS.md").write_text("# Demo\n", encoding="utf-8")
            (workspace / "docs/02-flujos/planos/planos.json").write_text(
                json.dumps({"titulo": f"Demo {numero}"}), encoding="utf-8"
            )
            procesos.append(
                subprocess.Popen(
                    [sys.executable, str(PROYECTOS), "registrar", str(workspace)],
                    cwd=RAIZ,
                    env=entorno,
                    text=True, encoding="utf-8", errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )

        salidas = [proceso.communicate(timeout=20) for proceso in procesos]
        for proceso, (stdout, stderr) in zip(procesos, salidas):
            self.assertEqual(proceso.returncode, 0, stdout + stderr)
        datos = json.loads(registro.read_text(encoding="utf-8"))
        self.assertEqual(len(datos["proyectos"]), total)
        self.assertEqual(
            {Path(p["ruta"]).name for p in datos["proyectos"]},
            {f"workspace-{numero:02d}" for numero in range(total)},
        )

    def workspace_antiguo(self, con_trabajo=True, nombre=None):
        ws = self.base / (nombre or ("antiguo-trabajo" if con_trabajo else "antiguo"))
        for nombre in (
            "00-metodo",
            "01-constitucion",
            "02-flujos",
            "03-investigacion",
            "04-planificacion",
            "05-trabajo/archivo",
            "bugs",
            "conocimiento",
            "decisiones",
        ):
            (ws / "docs" / nombre).mkdir(parents=True)
        (ws / "AGENTS.md").write_text(
            "# AGENTS.md — Antiguo (meta-repo)\n", encoding="utf-8"
        )
        (ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        (ws / "docs/bugs/INDICE.md").write_text("001-antigua\n", encoding="utf-8")
        (ws / "docs/02-flujos/planos").mkdir()
        (ws / "docs/02-flujos/planos/planos.json").write_text(
            '{"version": 2, "titulo": "Antiguo"}\n', encoding="utf-8"
        )
        if con_trabajo:
            unidad = ws / "docs/05-trabajo/001-antigua"
            unidad.mkdir()
            (unidad / "especificacion.md").write_text(
                "---\nunidad: 001-antigua\ntipo: feature\ncarril: normal\n"
                "estado: planificada\naprobado: no\nactividad: REC-1\nficheros: []\n"
                "actualizado: 2026-08-01\n---\n",
                encoding="utf-8",
            )
            (ws / "docs/bugs/002-antiguo.md").write_text(
                "---\nunidad: 002-antiguo\ntipo: bug\ncarril: normal\n"
                "estado: planificada\naprobado: no\nactividad: REC-1\nficheros: []\n"
                "actualizado: 2026-08-01\n---\n",
                encoding="utf-8",
            )
        subprocess.run(["git", "init", "-b", "main"], cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=ws, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=ws, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=ws, check=True
        )
        subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
        subprocess.run(
            ["git", "commit", "-m", "estado antiguo"],
            cwd=ws,
            check=True,
            capture_output=True,
        )
        return ws

    def test_actualizar_crea_allowlist_sin_inventar_peticiones(self):
        ws = self.workspace_antiguo()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        legacy = json.loads(
            (ws / "docs/05-trabajo/peticiones/LEGACY.json").read_text(encoding="utf-8")
        )
        self.assertEqual(legacy["modo"], "observacion")
        self.assertIn("001-antigua", legacy["unidades"])
        self.assertIn("002-antiguo", legacy["bugs"])
        self.assertEqual(
            list((ws / "docs/05-trabajo/peticiones").glob("P-*")), []
        )

    def test_actualizar_retira_launcher_inseguro_y_la_reversion_lo_recupera(self):
        ws = self.workspace_antiguo()
        antiguo = ws / "docs/00-metodo/scripts/sandbox_lanzar.py"
        antiguo.parent.mkdir(parents=True, exist_ok=True)
        antiguo.write_text("#!/usr/bin/env python3\n# launcher antiguo\n", encoding="utf-8")
        subprocess.run(["git", "add", str(antiguo)], cwd=ws, check=True)
        subprocess.run(
            ["git", "commit", "-m", "launcher antiguo"],
            cwd=ws,
            check=True,
            capture_output=True,
        )
        punto_retorno = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(antiguo.exists())
        cambio = subprocess.run(
            ["git", "show", "--format=", "--name-status", "HEAD"],
            cwd=ws, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True,
        ).stdout
        self.assertIn("D\tdocs/00-metodo/scripts/sandbox_lanzar.py", cambio)
        recuperable = subprocess.run(
            [
                "git",
                "show",
                f"{punto_retorno}:docs/00-metodo/scripts/sandbox_lanzar.py",
            ],
            cwd=ws,
            text=True, encoding="utf-8", errors="replace",
            capture_output=True,
            check=True,
        ).stdout
        self.assertIn("launcher antiguo", recuperable)

    def test_colision_tardia_detecta_edicion_en_ruta_del_metodo(self):
        """P0 de la revisión adversarial: una edición sin commitear en una ruta que
        Modo D va a sobrescribir, aparecida tras declararse el árbol limpio, se detecta
        antes de escribir y no se pierde."""
        if str(RAIZ / "visor") not in sys.path:
            sys.path.insert(0, str(RAIZ / "visor"))
        import actualizar

        ws = self.workspace_antiguo(con_trabajo=False)
        rutas_tocadas = ["AGENTS.md", "docs/00-metodo/scripts/lint_metodo.py"]

        # Árbol limpio: sin colisión.
        self.assertEqual(actualizar.colision_tardia(ws, rutas_tocadas), [])

        # El usuario edita AGENTS.md sin commitear (la ventana del linter).
        (ws / "AGENTS.md").write_text("# EDICIÓN DEL USUARIO\n", encoding="utf-8")
        self.assertEqual(
            actualizar.colision_tardia(ws, rutas_tocadas), ["AGENTS.md"]
        )
        # Una edición fuera de las rutas del método no colisiona.
        self.assertEqual(actualizar.colision_tardia(ws, ["docs/otro.md"]), [])

    def test_actualizar_no_revierte_por_rojo_heredado_aunque_no_hubiera_linter(self):
        """ADR-026: la línea base la mide el linter NUEVO sobre el estado viejo (--raiz),
        así que un defecto preexistente es heredado aunque el workspace ni siquiera
        tuviera linter — antes eso revertía y dejaba al workspace atrapado en el
        método viejo (caso de campo 08-08)."""
        ws = self.workspace_antiguo(con_trabajo=False)
        (ws / "codebase").mkdir()
        subprocess.run(["git", "add", "codebase"], cwd=ws, check=True)
        # Git no guarda carpetas vacías: el linter sí las ve, que es justo el fallo inducido.

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ya estaban antes de actualizar", resultado.stdout)
        self.assertNotIn("REVERTIDA", resultado.stdout)
        # La actualización se quedó entera: el inbox y su inventario existen.
        self.assertTrue((ws / "docs/00-metodo/scripts/peticion.py").exists())
        self.assertTrue((ws / "docs/05-trabajo/peticiones/LEGACY.json").exists())

    def test_actualizar_respeta_lease_exclusivo_del_workspace(self):
        ws = self.workspace_antiguo()
        modulo_path = RAIZ / "plantilla/docs/00-metodo/scripts/lease.py"
        spec = importlib.util.spec_from_file_location("lease_test_modo_d", modulo_path)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        autoridad = modulo.LeaseManager(ws, session_id="auditoria-activa").acquire(
            "unit:002-auditoria"
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("auditoria-activa", resultado.stdout + resultado.stderr)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout.strip(),
            head,
        )
        self.assertFalse((ws / "docs/00-metodo/scripts/peticion.py").exists())
        autoridad.release()

    def test_actualizar_rechaza_repo_local_symlink_antes_de_tocar(self):
        ws = self.workspace_antiguo()
        externo = self.base / "repo-externo-modo-d"
        externo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=externo, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=externo, check=True)
        ayuda_windows.enlazar_o_saltar(self, ws / "main", externo, directorio=True)
        (ws / "repos.yaml").write_text(
            "codigo:\n  ruta_local: main/\n  rama_principal: main\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "repos.yaml", "main"], cwd=ws, check=True)
        subprocess.run(
            ["git", "commit", "-m", "configura repo"], cwd=ws,
            check=True, capture_output=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        # La guarda de la 043 rechaza symlinks y junctions, y lo dice así:
        salida = (resultado.stdout + resultado.stderr).lower()
        self.assertIn("no admite enlaces", salida)
        self.assertIn("ruta_local", salida)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout.strip(),
            head,
        )
        self.assertFalse((ws / "docs/00-metodo/scripts/peticion.py").exists())

    def test_actualizar_no_stagea_trabajo_ajeno_que_aparece_durante_la_operacion(self):
        ws = self.workspace_antiguo()
        proceso, ready, gate = self.proceso_actualizar_con_failpoint(
            "actualizar_antes_stage_final", ws
        )
        self.esperar_barrera(ready)
        ajeno = ws / "docs/05-trabajo/nota-ajena.md"
        ajeno.write_text("trabajo de otra sesión\n", encoding="utf-8")
        self.abrir_barrera(gate)
        salida, error = proceso.communicate(timeout=30)

        self.assertEqual(proceso.returncode, 0, salida + error)
        incluidos = subprocess.run(
            ["git", "show", "--format=", "--name-only", "HEAD"],
            cwd=ws, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True,
        ).stdout.splitlines()
        self.assertNotIn("docs/05-trabajo/nota-ajena.md", incluidos)
        self.assertIn("?? docs/05-trabajo/nota-ajena.md", subprocess.run(
            ["git", "status", "--porcelain"], cwd=ws, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout)

    def test_actualizar_bloquea_arbol_sucio_sin_stagear_ni_commitear(self):
        ws = self.workspace_antiguo()
        ajeno = ws / "docs/05-trabajo/nota-ajena.md"
        ajeno.write_text("trabajo previo de otra sesión\n", encoding="utf-8")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("sucio", (resultado.stdout + resultado.stderr).lower())
        self.assertEqual(subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip(), head)
        self.assertEqual(subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=ws, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout, "")
        self.assertIn("?? docs/05-trabajo/nota-ajena.md", subprocess.run(
            ["git", "status", "--porcelain"], cwd=ws, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout)
        self.assertFalse((ws / "docs/00-metodo/scripts/peticion.py").exists())

    def test_actualizar_avisa_del_trabajo_en_vuelo_y_aplica(self):
        # ADR-025: una unidad aparcada no bloquea la actualización; se avisa
        # con su lista, el método entra y la ficha queda intacta. La unidad
        # es una en_obra legítima (aprobada y con plan): una en_obra sin
        # aprobación es un workspace roto y ahí el linter post-update revierte.
        ws = self.workspace_antiguo()
        ficha = ws / "docs/05-trabajo/001-antigua/especificacion.md"
        ficha.write_text(
            ficha.read_text(encoding="utf-8").replace(
                "estado: planificada", "estado: en_obra"
            ).replace(
                "aprobado: no", "aprobado: 2026-08-01"
            ) + "\n## Plan de trabajo\n\n- [ ] paso pendiente\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", str(ficha)], cwd=ws, check=True)
        subprocess.run(
            ["git", "commit", "-m", "unidad en obra"], cwd=ws,
            check=True, capture_output=True,
        )

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("001-antigua", salida)
        self.assertIn("trabajo en vuelo", salida)
        self.assertTrue((ws / "docs/00-metodo/scripts/peticion.py").exists())
        self.assertIn("estado: en_obra", ficha.read_text(encoding="utf-8"))

    def test_actualizar_bloquea_si_origin_avanza_antes_de_tocar(self):
        ws = self.workspace_antiguo()
        remoto = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", remoto], check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", remoto], cwd=ws, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=ws,
                       check=True, capture_output=True)
        otro = self.base / "otro-host"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "-b", "main", remoto, otro],
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Otro"], cwd=otro, check=True)
        subprocess.run(["git", "config", "user.email", "otro@example.com"], cwd=otro,
                       check=True)
        (otro / "avance-remoto.md").write_text("avance\n", encoding="utf-8")
        subprocess.run(["git", "add", "avance-remoto.md"], cwd=otro, check=True)
        subprocess.run(["git", "commit", "-m", "avance remoto"], cwd=otro,
                       check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=otro,
                       check=True, capture_output=True)
        agents_previo = (ws / "AGENTS.md").read_bytes()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("remoto", (resultado.stdout + resultado.stderr).lower())
        self.assertEqual((ws / "AGENTS.md").read_bytes(), agents_previo)
        self.assertFalse((ws / "docs/00-metodo/scripts/peticion.py").exists())

    def test_actualizar_recupera_sigkill_con_journal_durable(self):
        ws = self.workspace_antiguo()
        proceso, ready, gate = self.proceso_actualizar_con_failpoint(
            "actualizar_despues_primera_escritura", ws
        )
        self.esperar_barrera(ready)
        proceso.kill()
        proceso.wait(timeout=3)
        proceso.communicate()
        self.abrir_barrera(gate)
        journal = ws / ".runtime/transactions/modo-d.json"
        self.assertTrue(journal.is_file())

        recuperada = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(recuperada.returncode, 0, recuperada.stdout + recuperada.stderr)
        self.assertFalse(journal.exists())
        revision = self.ejecutar(ACTUALIZAR, "revisar", str(ws))
        self.assertEqual(revision.returncode, 0, revision.stdout + revision.stderr)
        self.assertIn("0 proyecto(s) con cambios pendientes", revision.stdout)

    def test_crash_despues_del_commit_conserva_commit_y_cierra_journal(self):
        ws = self.workspace_antiguo()
        anterior = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()
        proceso, ready, gate = self.proceso_actualizar_con_failpoint(
            "actualizar_despues_commit", ws
        )
        self.esperar_barrera(ready)
        publicado = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()
        self.assertNotEqual(publicado, anterior)
        proceso.kill()
        proceso.wait(timeout=3)
        proceso.communicate()
        self.abrir_barrera(gate)
        journal = ws / ".runtime/transactions/modo-d.json"
        self.assertTrue(journal.is_file())

        recuperada = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(recuperada.returncode, 0, recuperada.stdout + recuperada.stderr)
        self.assertIn("ya estaba commiteada", recuperada.stdout)
        self.assertFalse(journal.exists())
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout.strip(),
            publicado,
        )
        self.assertEqual(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout,
            "",
        )

    def test_journal_rechaza_path_traversal_sin_tocar_fuera(self):
        ws = self.workspace_antiguo()
        victima = self.base / "victima.txt"
        victima.write_bytes(b"contenido privado\n")
        atacante = self.entrada_journal(b"sobrescrito desde journal\n")
        journal = self.escribir_journal(
            ws,
            {"../victima.txt": atacante},
            published={"../victima.txt": atacante},
        )

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(victima.read_bytes(), b"contenido privado\n")
        self.assertTrue(journal.is_file())
        self.assertIn("journal", (resultado.stdout + resultado.stderr).lower())

    def test_journal_rechaza_symlink_sin_seguirlo(self):
        ws = self.workspace_antiguo()
        victima = self.base / "fuera-agents.md"
        victima.write_bytes(b"fuera intacto\n")
        agents = ws / "AGENTS.md"
        agents.unlink()
        ayuda_windows.enlazar_o_saltar(self, agents, victima)
        atacante = self.entrada_journal(b"contenido atacante\n")
        journal = self.escribir_journal(
            ws,
            {"AGENTS.md": atacante},
            published={"AGENTS.md": atacante},
        )

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(victima.read_bytes(), b"fuera intacto\n")
        self.assertTrue(agents.is_symlink())
        self.assertTrue(journal.is_file())

    def test_journal_rechaza_schema_y_fase_no_canonicos(self):
        ws = self.workspace_antiguo()
        agents_previo = (ws / "AGENTS.md").read_bytes()
        atacante = self.entrada_journal(b"contenido atacante\n")
        journal = self.escribir_journal(
            ws,
            {"AGENTS.md": atacante},
            published={"AGENTS.md": atacante},
            fase="lo-que-diga-el-atacante",
            campo_ignorado="bypass",
        )

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual((ws / "AGENTS.md").read_bytes(), agents_previo)
        self.assertTrue(journal.is_file())

    def test_crash_antes_del_replace_no_publica_un_fichero_parcial(self):
        ws = self.workspace_antiguo()
        destino = ws / ".githooks/pre-push"
        self.assertFalse(destino.exists())
        proceso, ready, gate = self.proceso_actualizar_con_failpoint(
            "actualizar_antes_reemplazo_atomico", ws
        )

        self.esperar_barrera(ready)
        self.assertFalse(destino.exists())
        proceso.kill()
        proceso.wait(timeout=3)
        proceso.communicate()
        self.abrir_barrera(gate)

        self.assertFalse(destino.exists())
        self.assertTrue((ws / ".runtime/transactions/modo-d.json").is_file())

    def test_cambio_ajeno_en_misma_ruta_antes_del_stage_bloquea_sin_clobber(self):
        ws = self.workspace_antiguo()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()
        proceso, ready, gate = self.proceso_actualizar_con_failpoint(
            "actualizar_antes_stage_final", ws
        )
        self.esperar_barrera(ready)
        ajeno = b"cambio concurrente en la misma ruta\n"
        (ws / "AGENTS.md").write_bytes(ajeno)
        self.abrir_barrera(gate)
        salida, error = proceso.communicate(timeout=30)

        self.assertNotEqual(proceso.returncode, 0, salida + error)
        self.assertEqual((ws / "AGENTS.md").read_bytes(), ajeno)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout.strip(),
            head,
        )
        self.assertEqual(
            subprocess.run(
                ["git", "diff", "--cached", "--name-only"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout,
            "",
        )

    def test_stage_exacto_no_absorbe_cambio_ajeno_posterior(self):
        ws = self.workspace_antiguo()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()
        proceso, ready, gate = self.proceso_actualizar_con_failpoint(
            "actualizar_despues_stage_exact", ws
        )
        self.esperar_barrera(ready)
        esperado = (RAIZ / "plantilla/AGENTS.md").read_text(encoding="utf-8").replace(
            "{{TITULO}}", "Antiguo"
        )
        blob_stageado = subprocess.run(
            ["git", "show", ":AGENTS.md"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout
        self.assertEqual(blob_stageado, esperado)
        ajeno = b"cambio despues del stage exacto\n"
        (ws / "AGENTS.md").write_bytes(ajeno)
        self.abrir_barrera(gate)
        salida, error = proceso.communicate(timeout=30)

        self.assertNotEqual(proceso.returncode, 0, salida + error)
        self.assertEqual((ws / "AGENTS.md").read_bytes(), ajeno)
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout.strip(),
            head,
        )
        self.assertEqual(
            subprocess.run(
                ["git", "diff", "--cached", "--name-only"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout,
            "",
        )

    def test_actualizar_no_toca_personalidad_agente(self):
        """R-1601/R-1603: la preferencia de tono vive fuera del árbol que Modo D
        gestiona — .claude/ no aparece en contenido_esperado(), así que Modo D
        nunca la pisa ni la borra al actualizar."""
        ws = self.workspace_antiguo()
        personalidad = ws / ".claude/personalidad.md"
        personalidad.parent.mkdir(parents=True)
        contenido_original = "Háblame cercano y breve.\n"
        personalidad.write_text(contenido_original, encoding="utf-8")
        subprocess.run(["git", "add", str(personalidad)], cwd=ws, check=True)
        subprocess.run(
            ["git", "commit", "-m", "preferencia de tono"], cwd=ws,
            check=True, capture_output=True,
        )

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(personalidad.read_text(encoding="utf-8"), contenido_original)

    def test_claude_y_gemini_importan_personalidad_exista_o_no_el_fichero(self):
        """R-1602: CLAUDE.md y GEMINI.md siempre importan la preferencia de tono
        además del router, tanto si el workspace ya tiene .claude/personalidad.md
        como si todavía no la ha fijado nadie."""
        sin_personalidad = self.workspace_antiguo(con_trabajo=False)
        con_personalidad = self.workspace_antiguo(con_trabajo=True)
        ficha_personalidad = con_personalidad / ".claude/personalidad.md"
        ficha_personalidad.parent.mkdir(parents=True)
        ficha_personalidad.write_text("Sé formal y detallado.\n", encoding="utf-8")
        subprocess.run(["git", "add", str(ficha_personalidad)], cwd=con_personalidad, check=True)
        subprocess.run(
            ["git", "commit", "-m", "preferencia de tono"], cwd=con_personalidad,
            check=True, capture_output=True,
        )

        for ws in (sin_personalidad, con_personalidad):
            resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
            self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
            for puente in ("CLAUDE.md", "GEMINI.md"):
                contenido = (ws / puente).read_text(encoding="utf-8")
                self.assertIn("@AGENTS.md", contenido)
                self.assertIn("@.claude/personalidad.md", contenido)
                self.assertLess(
                    contenido.index("@AGENTS.md"),
                    contenido.index("@.claude/personalidad.md"),
                )

    def importar_actualizar(self):
        if str(RAIZ / "visor") not in sys.path:
            sys.path.insert(0, str(RAIZ / "visor"))
        import actualizar
        return actualizar

    def fijar_desfase(self, actualizar, valor):
        original = actualizar.desfase_herramienta
        actualizar.desfase_herramienta = lambda: valor
        self.addCleanup(setattr, actualizar, "desfase_herramienta", original)

    def test_aviso_se_construye_con_huella_distinta_y_origen_accesible(self):
        """R1: método del workspace por detrás del de la herramienta, origen accesible
        → se construye el mensaje de aviso con las cuatro respuestas. Al día → nada."""
        actualizar = self.importar_actualizar()
        self.fijar_desfase(actualizar, 0)
        ws = self.workspace_antiguo(con_trabajo=False, nombre="aviso-agents")

        mensaje = actualizar.comprobar_aviso(ws)

        self.assertTrue(mensaje, "con el método desactualizado debe haber aviso")
        for opcion in ("sí", "todos", "nunca", "aplicar"):
            self.assertIn(opcion, mensaje)

        al_dia = self.workspace_antiguo(con_trabajo=False, nombre="aldia-agents")
        (al_dia / "METODO.json").write_text(
            json.dumps(
                {
                    "formato": 1,
                    "huella": actualizar.bootstrap.huella_plantilla(),
                    "version": actualizar.bootstrap.version_metodo(),
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(actualizar.comprobar_aviso(al_dia), "")

    def test_nunca_persiste_fuera_del_arbol_y_silencia_arranques(self):
        """R4: `avisar --nunca` guarda la preferencia en .claude/actualizaciones.md
        (fuera de contenido_esperado, o sea fuera de lo que Modo D toca), el chequeo
        deja de avisar, y la preferencia sobrevive a la propia actualización."""
        actualizar = self.importar_actualizar()
        self.fijar_desfase(actualizar, 0)
        ws = self.workspace_antiguo(con_trabajo=False, nombre="nunca-agents")

        resultado = self.ejecutar(ACTUALIZAR, "avisar", str(ws), "--nunca")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        preferencia = ws / ".claude/actualizaciones.md"
        self.assertTrue(preferencia.is_file())
        self.assertIn("nunca", preferencia.read_text(encoding="utf-8"))
        self.assertEqual(actualizar.comprobar_aviso(ws), "")

        esperado, _avisos = actualizar.contenido_esperado(ws)
        self.assertEqual(
            [ruta for ruta in esperado if ruta.startswith(".claude/")], []
        )

        aplicada = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
        self.assertEqual(aplicada.returncode, 0, aplicada.stdout + aplicada.stderr)
        self.assertTrue(preferencia.is_file())
        self.assertEqual(actualizar.comprobar_aviso(ws), "")

    def test_avisar_sin_origen_accesible_no_avisa_ni_bloquea(self):
        """R5: el origen del método no responde (sin red, repo privado sin
        credenciales…) → `avisar` termina en 0, sin aviso y sin tocar nada."""
        ws = self.workspace_antiguo(con_trabajo=False, nombre="sinred-agents")
        falsa = self.base / "herramienta-sin-origen"
        falsa.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=falsa, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=falsa, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=falsa, check=True
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "raiz"],
            cwd=falsa, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(self.base / "origen-que-no-existe.git")],
            cwd=falsa, check=True,
        )
        self.entorno["INGENIERIA_REQUISITOS_HERRAMIENTA"] = str(falsa)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout.strip()

        resultado = self.ejecutar(ACTUALIZAR, "avisar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertEqual(resultado.stdout.strip(), "")
        self.assertFalse((ws / ".claude/actualizaciones.md").exists())
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ws, text=True,
                encoding="utf-8", errors="replace",
                capture_output=True, check=True,
            ).stdout.strip(),
            head,
        )

    def test_todos_aplica_a_todos_los_registrados(self):
        """R3: la respuesta "todos" delega en `aplicar --todos`, que actualiza cada
        workspace registrado y reporta el resultado de cada uno."""
        self.entorno["INGENIERIA_REQUISITOS_SIN_FETCH"] = "1"
        workspaces = [
            self.workspace_antiguo(con_trabajo=False, nombre="todos-uno-agents"),
            self.workspace_antiguo(con_trabajo=False, nombre="todos-dos-agents"),
        ]
        for ws in workspaces:
            registro = subprocess.run(
                [sys.executable, str(PROYECTOS), "registrar", str(ws)],
                cwd=RAIZ, env=self.entorno, text=True,
                encoding="utf-8", errors="replace", capture_output=True,
            )
            self.assertEqual(registro.returncode, 0, registro.stdout + registro.stderr)

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", "--todos")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        for ws in workspaces:
            # os.path.realpath, no str(ws) a pelo: actualizar.py reporta la ruta ya
            # pasada por Path.resolve(), que en Windows normaliza al nombre LARGO
            # (runneradmin); `ws` viene de tempfile.mkdtemp() tal cual, que hereda el
            # alias CORTO 8.3 (RUNNER~1) que trae el TMP del runner (familia 3, bug
            # 017 — aquí en el propio test, no en el launcher).
            self.assertIn(os.path.realpath(str(ws)), resultado.stdout)
            self.assertTrue((ws / "docs/00-metodo/scripts/peticion.py").is_file())
        self.assertEqual(resultado.stdout.count("sobrescritos"), len(workspaces))

    def test_aviso_desaparece_tras_aplicar_este_workspace(self):
        """R2: tras responder "sí" (aplicar solo esa ruta) el resultado se confirma
        y el chequeo del siguiente arranque ya no avisa."""
        actualizar = self.importar_actualizar()
        self.fijar_desfase(actualizar, 0)
        ws = self.workspace_antiguo(con_trabajo=False, nombre="si-agents")
        self.assertTrue(actualizar.comprobar_aviso(ws))

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("sobrescritos", resultado.stdout)
        self.assertEqual(actualizar.comprobar_aviso(ws), "")

    def test_agents_md_reparte_el_canal_proactivo(self):
        """El arranque del agente hijo (AGENTS.md, repartido por Modo D) trae el
        chequeo proactivo: preferencia en .claude/actualizaciones.md, el comando que
        comprueba y las cuatro respuestas, sin bloquear si no hay red o acceso.

        Unidad 031: ese comando ya no es una ruta a la herramienta (que puede no
        existir en el disco) sino el script del propio workspace; el resto del
        contrato del canal es el mismo y se sigue exigiendo aquí."""
        ws = self.workspace_antiguo(con_trabajo=False, nombre="canal-agents")

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(".claude/actualizaciones.md", agents)
        self.assertIn("docs/00-metodo/scripts/herramienta.py comprobar", agents)
        self.assertIn("herramienta.py nunca", agents)
        self.assertIn("aplicar --todos", agents)
        self.assertIn("sin aviso", agents)
        # Y el script que ese comando invoca viaja en la misma actualización.
        self.assertTrue((ws / "docs/00-metodo/scripts/herramienta.py").is_file())

    def test_agents_md_avisa_lo_primero_incluso_en_arranque_ligero(self):
        """Unidad 032 (orden de Nate, 19-08): el aviso de método debe salir en
        CUALQUIER arranque, también en solo-consulta, y ser "lo primero de lo
        primero". El AGENTS.md repartido tiene que (a) ordenar el chequeo ANTES de
        la regla de arranque ligero, (b) mandar que el PRIMER párrafo al usuario
        sea el aviso con sus cuatro respuestas, y (c) prohibir posponerlo o
        mencionarlo de pasada — que es exactamente lo que pasó en campo."""
        ws = self.workspace_antiguo(con_trabajo=False, nombre="aviso-primero-agents")

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("también en solo-consulta", agents)
        self.assertIn("PRIMER párrafo", agents)
        self.assertIn("posponerlo", agents)
        idx_aviso = agents.index("herramienta.py comprobar")
        idx_ligero = agents.index("Solo-consulta arranca ligero")
        self.assertLess(idx_aviso, idx_ligero,
                        "el chequeo del método debe ordenarse ANTES del arranque ligero")
        # Sin versión nueva, sin red o sin acceso: ni una línea (el silencio no empeora).
        self.assertIn("sin aviso", agents)

    def test_bootstrap_siembra_personalidad_y_la_anuncia_una_vez(self):
        """Unidad 032: .claude/personalidad.md nace de serie como placeholder (adiós
        al aviso "no existe" en cada arranque). Quien lo menciona, UNA sola vez, es
        el propio bootstrap en su salida. Y el AGENTS.md repartido manda: placeholder
        sin directrices ni se aplica ni se menciona; si falta (workspace viejo), el
        agente lo crea en silencio."""
        destino = self.base / "personalidad-agents"
        resultado = self.ejecutar(
            BOOTSTRAP, "--planos", str(self.planos_minimos()), "--destino", str(destino)
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        fichero = destino / ".claude/personalidad.md"
        self.assertTrue(fichero.is_file())
        texto = fichero.read_text(encoding="utf-8")
        self.assertIn("Personalidad del agente", texto)
        self.assertIn("tono", texto)
        self.assertEqual(resultado.stdout.count("personalidad.md"), 1,
                         "el bootstrap lo anuncia UNA vez, ni cero ni dos:\n"
                         + resultado.stdout)
        agents = (destino / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("ni lo apliques ni lo menciones", agents)
        self.assertIn("créalo tú en silencio", agents)

    def test_agents_md_actualizado_conserva_el_aviso_de_personalidad_corrupta(self):
        """R-1604: la instrucción de avisar una vez y seguir con el tono por defecto
        ante un .claude/personalidad.md corrupto vive en AGENTS.md, así que Modo D
        la reparte y la conserva en cada actualización — no depende de que el dueño
        del workspace la haya escrito a mano."""
        ws = self.workspace_antiguo()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(".claude/personalidad.md", agents)
        self.assertIn("avís", agents)
        self.assertIn("sin bloque", agents)

    # --- bug 088: el aviso de árbol sucio dice QUIÉN lo dejó y CÓMO desbloquear ---

    MENSAJE_COLA = "docs: cola y conocimiento del método"

    def ensuciar_con_cola_del_metodo(self, ws, peticiones=6):
        """Deja el árbol como lo deja el propio método en un workspace de usuario:
        peticiones capturadas sin seguimiento y el conocimiento de la máquina tocado
        por setup.py. Nada de esto lo escribió el usuario."""
        cola = ws / "docs/05-trabajo/peticiones"
        cola.mkdir(parents=True, exist_ok=True)
        for indice in range(peticiones):
            carpeta = cola / f"P-20260825-{indice:08x}"
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / "peticion.json").write_text(
                json.dumps({"id": carpeta.name, "revision": 1}) + "\n", encoding="utf-8")
        conocimiento = ws / "docs/conocimiento/entorno-de-esta-maquina.md"
        conocimiento.parent.mkdir(parents=True, exist_ok=True)
        conocimiento.write_text("# Entorno\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "docs/conocimiento/entorno-de-esta-maquina.md"],
                       cwd=ws, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "conocimiento"], cwd=ws, check=True,
                       capture_output=True)
        conocimiento.write_text("# Entorno\n\npython3.13\n", encoding="utf-8")
        despliegue = ws / "docs/05-trabajo/despliegue-2026-08-25.md"
        despliegue.write_text("# Despliegue\n", encoding="utf-8")

    def asuntos(self, ws):
        return subprocess.run(
            ["git", "log", "--format=%s"], cwd=ws, text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=True).stdout.splitlines()

    def ficheros_del_commit(self, ws, asunto):
        sha = subprocess.run(
            ["git", "log", "--format=%H %s"], cwd=ws, text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=True).stdout
        linea = [l for l in sha.splitlines() if l.split(" ", 1)[1:] == [asunto]]
        self.assertTrue(linea, f"no hay commit con asunto {asunto!r}:\n{sha}")
        return subprocess.run(
            ["git", "show", "--format=", "--name-only", linea[0].split(" ", 1)[0]],
            cwd=ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=True).stdout.splitlines()

    def test_arbol_sucio_agrupa_por_dueno_y_nombra_el_commit_que_desbloquea(self):
        """Bug 088: el alumno veía «trabajo sin confirmar» sin saber que era del propio
        método ni qué teclear. El aviso reparte por dueño y da el comando exacto."""
        ws = self.workspace_antiguo()
        self.ensuciar_con_cola_del_metodo(ws)

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
        salida = resultado.stdout + resultado.stderr

        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("lo dejó el método", salida.lower())
        self.assertIn("docs/05-trabajo/peticiones/", salida)
        self.assertIn("docs/conocimiento/entorno-de-esta-maquina.md", salida)
        self.assertIn("docs/05-trabajo/despliegue-2026-08-25.md", salida)
        self.assertIn(
            'git add docs/05-trabajo/despliegue-2026-08-25.md '
            'docs/05-trabajo/peticiones/ docs/conocimiento/entorno-de-esta-maquina.md '
            f'&& git commit -m "{self.MENSAJE_COLA}"',
            salida)
        self.assertIn("--confirmar-lo-del-metodo", salida)
        self.assertNotIn("stash", salida.lower())

    def test_aviso_separa_lo_del_usuario_y_no_le_ofrece_confirmarlo(self):
        ws = self.workspace_antiguo()
        self.ensuciar_con_cola_del_metodo(ws)
        (ws / "docs/05-trabajo/nota-ajena.md").write_text("mío\n", encoding="utf-8")

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
        salida = resultado.stdout + resultado.stderr

        self.assertNotEqual(resultado.returncode, 0, salida)
        tuyo = salida.lower().split("tuyo", 1)
        self.assertEqual(len(tuyo), 2, "el aviso no separa lo del usuario:\n" + salida)
        self.assertIn("docs/05-trabajo/nota-ajena.md", tuyo[1])
        self.assertNotIn("docs/05-trabajo/nota-ajena.md",
                         tuyo[0].split("lo dejó el método", 1)[-1])
        self.assertIn("guarda", tuyo[1])
        self.assertIn("descarta", tuyo[1])

    def test_confirmar_lo_del_metodo_commitea_solo_esas_rutas_y_actualiza(self):
        ws = self.workspace_antiguo()
        self.ensuciar_con_cola_del_metodo(ws)

        resultado = self.ejecutar(
            ACTUALIZAR, "aplicar", str(ws), "--confirmar-lo-del-metodo")
        salida = resultado.stdout + resultado.stderr

        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn(self.MENSAJE_COLA, self.asuntos(ws))
        tocados = self.ficheros_del_commit(ws, self.MENSAJE_COLA)
        self.assertIn("docs/conocimiento/entorno-de-esta-maquina.md", tocados)
        self.assertIn("docs/05-trabajo/despliegue-2026-08-25.md", tocados)
        self.assertEqual(
            6, len([t for t in tocados if t.startswith("docs/05-trabajo/peticiones/")]),
            tocados)
        self.assertTrue((ws / "docs/00-metodo/scripts/peticion.py").is_file(), salida)
        self.assertEqual(subprocess.run(
            ["git", "status", "--porcelain"], cwd=ws, text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=True).stdout, "")

    def test_confirmar_lo_del_metodo_para_igual_si_queda_algo_del_usuario(self):
        ws = self.workspace_antiguo()
        self.ensuciar_con_cola_del_metodo(ws)
        (ws / "docs/05-trabajo/nota-ajena.md").write_text("mío\n", encoding="utf-8")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=True).stdout.strip()

        resultado = self.ejecutar(
            ACTUALIZAR, "aplicar", str(ws), "--confirmar-lo-del-metodo")
        salida = resultado.stdout + resultado.stderr

        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("docs/05-trabajo/nota-ajena.md", salida)
        self.assertNotIn(self.MENSAJE_COLA, self.asuntos(ws))
        self.assertEqual(subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=True).stdout.strip(), head)
        self.assertEqual(subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=ws, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, check=True).stdout, "")



if __name__ == "__main__":
    unittest.main()
