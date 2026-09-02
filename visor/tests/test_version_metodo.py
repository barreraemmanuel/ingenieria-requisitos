import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
ACTUALIZAR = RAIZ / "visor/actualizar.py"
VERSION = RAIZ / "plantilla/docs/00-metodo/VERSION"


class VersionMetodoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="version-metodo-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.entorno = dict(os.environ)
        self.entorno["INGENIERIA_REQUISITOS_REGISTRO"] = str(
            self.base / "registro-suite.json"
        )
        self.version = VERSION.read_text(encoding="utf-8").strip()

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

    def workspace_antiguo(self, *, sin_bugs=False):
        """Workspace anterior al versionado: sin METODO.json y sin el método publicado."""
        ws = self.base / ("antiguo-sin-bugs" if sin_bugs else "antiguo")
        carpetas = [
            "00-metodo",
            "01-constitucion",
            "02-flujos",
            "03-investigacion",
            "04-planificacion",
            "05-trabajo/archivo",
            "conocimiento",
            "decisiones",
        ]
        if not sin_bugs:
            carpetas.append("bugs")
        for nombre in carpetas:
            (ws / "docs" / nombre).mkdir(parents=True)
        (ws / "AGENTS.md").write_text(
            "# AGENTS.md — Antiguo (meta-repo)\n", encoding="utf-8"
        )
        (ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        if not sin_bugs:
            (ws / "docs/bugs/INDICE.md").write_text("001-antigua\n", encoding="utf-8")
        (ws / "docs/02-flujos/planos").mkdir()
        (ws / "docs/02-flujos/planos/planos.json").write_text(
            '{"version": 2, "titulo": "Antiguo"}\n', encoding="utf-8"
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

    def commitear(self, ws, mensaje):
        subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
        subprocess.run(
            ["git", "commit", "-m", mensaje], cwd=ws, check=True, capture_output=True
        )

    def plantar_fail_estable(self, ws):
        """Una ficha sin frontmatter: FAIL determinista que aplicar no repara."""
        carpeta = ws / "docs/05-trabajo/001-demo"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "especificacion.md").write_text("sin frontmatter\n", encoding="utf-8")

    def test_version_declarada_es_semver(self):
        self.assertRegex(self.version, r"^\d+\.\d+\.\d+$")

    def test_bootstrap_escribe_version_en_metodo_json_y_publica_el_fichero(self):
        destino = self.base / "demo-agents"

        resultado = self.ejecutar(
            BOOTSTRAP, "--planos", str(self.planos_minimos()), "--destino", str(destino)
        )

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        metodo = json.loads((destino / "METODO.json").read_text(encoding="utf-8"))
        self.assertEqual(metodo["version"], self.version)
        self.assertEqual(
            (destino / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip(),
            self.version,
        )

    def test_aplicar_muestra_el_salto_de_version_y_la_escribe(self):
        ws = self.workspace_antiguo()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("método sin versión", resultado.stdout)
        self.assertIn(self.version, resultado.stdout)
        metodo = json.loads((ws / "METODO.json").read_text(encoding="utf-8"))
        self.assertEqual(metodo["version"], self.version)
        revision = self.ejecutar(ACTUALIZAR, "revisar", str(ws))
        self.assertEqual(revision.returncode, 0, revision.stdout + revision.stderr)
        self.assertIn(f"método {self.version} (al día)", revision.stdout)

    def test_aplicar_repone_el_esqueleto_de_bugs_ausente_y_el_linter_pasa(self):
        ws = self.workspace_antiguo(sin_bugs=True)

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("docs/bugs", resultado.stdout)
        self.assertTrue((ws / "docs/bugs/.gitkeep").is_file())
        indice = (ws / "docs/bugs/INDICE.md").read_text(encoding="utf-8")
        self.assertIn("# Índice de bugs", indice)
        commiteados = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=ws, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True,
        ).stdout.splitlines()
        self.assertIn("docs/bugs/INDICE.md", commiteados)
        lint = self.ejecutar(ws / "docs/00-metodo/scripts/lint_metodo.py")
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_aplicar_no_revierte_por_fallos_heredados_del_linter(self):
        """Caso de campo (03-08): el rojo ya estaba y la actualización cargó
        con la culpa. Un FAIL idéntico antes y después NO puede revertir el update:
        revertirlo no limpia nada y deja al workspace atrapado en el método viejo."""
        ws = self.workspace_antiguo()
        primera = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
        self.assertEqual(primera.returncode, 0, primera.stdout + primera.stderr)
        self.plantar_fail_estable(ws)
        # Y hay método pendiente de publicar: un runbook se perdió.
        (ws / "docs/00-metodo/runbooks/expres.md").unlink()
        self.commitear(ws, "ficha rota y runbook perdido")

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ya estaban antes de actualizar", resultado.stdout)
        self.assertNotIn("REVERTIDA", resultado.stdout)
        # La actualización se quedó: el runbook volvió.
        self.assertTrue((ws / "docs/00-metodo/runbooks/expres.md").is_file())

    def test_aplicar_no_revierte_aunque_el_linter_viejo_fuera_permisivo(self):
        """ADR-026: la vara es la MISMA antes y después (el linter nuevo, vía --raiz).
        Un workspace cuyo linter viejo era permisivo ya no convierte sus defectos
        preexistentes en «fallos nuevos» del update: el rojo queda como heredado y la
        actualización se queda (caso de campo 08-08: migración imposible en bucle)."""
        ws = self.workspace_antiguo()
        primera = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))
        self.assertEqual(primera.returncode, 0, primera.stdout + primera.stderr)
        self.plantar_fail_estable(ws)
        # El linter "viejo" del workspace era más permisivo: verde siempre.
        linter = ws / "docs/00-metodo/scripts/lint_metodo.py"
        linter.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        self.commitear(ws, "linter permisivo y ficha rota")

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ya estaban antes de actualizar", resultado.stdout)
        self.assertNotIn("REVERTIDA", resultado.stdout)
        # La actualización se quedó: el linter permisivo fue reemplazado por el real.
        self.assertNotIn("sys.exit(0)", linter.read_text(encoding="utf-8"))

    def test_aplicar_revierte_si_la_actualizacion_introduce_fallos_nuevos(self):
        """Un rojo que NO existía midiendo el estado viejo con el linter nuevo y SÍ
        existe tras escribir los ficheros nuevos es culpa del update: eso revierte,
        y el mensaje lo nombra como causa."""
        copia = self.herramienta_doctorada()
        ws = self.workspace_antiguo()
        agents_previo = (ws / "AGENTS.md").read_bytes()

        resultado = self.ejecutar(copia / "visor/actualizar.py", "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 1, resultado.stdout + resultado.stderr)
        self.assertIn("REVERTIDA", resultado.stdout)
        self.assertIn("introdujo", resultado.stdout)
        self.assertIn("MARCADOR_ROJO", resultado.stdout)
        # El revert restauró lo tocado: el marcador no quedó en el workspace.
        self.assertEqual((ws / "AGENTS.md").read_bytes(), agents_previo)
        self.assertFalse((ws / "docs/00-metodo/runbooks/expres.md").exists())

    def test_aplicar_sin_linter_previo_mide_con_el_nuevo_y_no_revierte(self):
        """ADR-026: antes, «sin línea base» cualquier rojo revertía y el workspace
        quedaba atrapado. Ahora la línea base siempre existe: la da el linter nuevo
        midiendo el estado viejo, y el rojo preexistente es heredado."""
        ws = self.workspace_antiguo()
        self.plantar_fail_estable(ws)
        self.commitear(ws, "ficha rota en workspace sin linter")

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("ya estaban antes de actualizar", resultado.stdout)
        self.assertNotIn("REVERTIDA", resultado.stdout)

    def test_fallos_del_linter_cae_al_linter_del_workspace_si_el_nuevo_revienta(self):
        """El linter nuevo que revienta (exit != 0/1, sin FAIL) no es una medición:
        se cae al linter del workspace y, si tampoco hay, a None (rama conservadora)."""
        if str(RAIZ / "visor") not in sys.path:
            sys.path.insert(0, str(RAIZ / "visor"))
        import actualizar

        ws = self.base / "ws-fallback"
        ws.mkdir()
        esperado_roto = {
            "docs/00-metodo/scripts/lint_metodo.py": "import sys\nsys.exit(3)\n"
        }
        # Sin linter en el workspace: None (y la política revierte, conservadora).
        self.assertIsNone(actualizar.fallos_del_linter(ws, esperado_roto))
        # Con linter viejo en el workspace: su medición vale como línea base.
        viejo = ws / "docs/00-metodo/scripts/lint_metodo.py"
        viejo.parent.mkdir(parents=True)
        viejo.write_text(
            "print('  FAIL medido por el linter viejo')\nraise SystemExit(1)\n",
            encoding="utf-8",
        )
        self.assertEqual(
            actualizar.fallos_del_linter(ws, esperado_roto),
            {"FAIL medido por el linter viejo"},
        )

    def herramienta_doctorada(self):
        """Copia funcional de la herramienta cuyo método introduce un rojo NUEVO:
        su linter falla si expres.md trae MARCADOR_ROJO, y su plantilla lo trae."""
        copia = self.base / "herramienta-doctorada"
        # La copia lleva TODO lo que la herramienta reparte. Desde la unidad 081
        # eso es la web entera (`ARCHIVOS_WEB`): la cáscara de `web/` y los cuatro
        # módulos de datos, que siguen viviendo en la carpeta de su visor.
        for carpeta in ("visor", "plantilla", "web", "visor_presentaciones",
                        "visor_contratos", "visor_tablero"):
            shutil.copytree(RAIZ / carpeta, copia / carpeta,
                            ignore=shutil.ignore_patterns("tests", "__pycache__"))
        for nombre in ("RUNBOOK.md", "requirements-dev.txt"):
            shutil.copyfile(RAIZ / nombre, copia / nombre)
        shutil.copytree(RAIZ / "RUNBOOK", copia / "RUNBOOK")
        expres = copia / "plantilla/docs/00-metodo/runbooks/expres.md"
        expres.write_text(expres.read_text(encoding="utf-8") + "\nMARCADOR_ROJO\n",
                          encoding="utf-8")
        linter = copia / "plantilla/docs/00-metodo/scripts/lint_metodo.py"
        ancla = 'agents = RAIZ / "AGENTS.md"'
        inyeccion = (
            '_expres = RAIZ / "docs/00-metodo/runbooks/expres.md"\n'
            'if _expres.is_file() and "MARCADOR_ROJO" in _expres.read_text('
            'encoding="utf-8"):\n'
            '    fail("expres.md trae MARCADOR_ROJO: rojo introducido por la '
            'actualización (inducido por el test)", id_="test-actualizacion-marcador-rojo")\n'
        )
        contenido = linter.read_text(encoding="utf-8")
        self.assertIn(ancla, contenido)
        linter.write_text(contenido.replace(ancla, inyeccion + ancla),
                          encoding="utf-8")
        return copia

    def herramienta_clonada(self):
        """Un 'origin' local de la herramienta y su clon; devuelve (origen, clon)."""
        origen = self.base / "herramienta-origen"
        origen.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=origen, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=origen, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=origen, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"],
                       cwd=origen, check=True)
        (origen / "METODO.txt").write_text("v1\n", encoding="utf-8")
        self.commitear(origen, "método v1")
        clon = self.base / "herramienta-clon"
        subprocess.run(["git", "clone", "-c", "core.autocrlf=false", str(origen), str(clon)], check=True,
                       capture_output=True)
        return origen, clon

    def test_revisar_todos_avisa_si_la_herramienta_va_por_detras(self):
        """Caso de campo (03→10 ago): 7 proyectos una semana con el método
        viejo sin que nada avisara. Quien reparte tiene que enterarse de que va viejo."""
        origen, clon = self.herramienta_clonada()
        (origen / "METODO.txt").write_text("v2\n", encoding="utf-8")
        self.commitear(origen, "método v2")
        (origen / "METODO.txt").write_text("v3\n", encoding="utf-8")
        self.commitear(origen, "método v3")
        self.entorno["INGENIERIA_REQUISITOS_HERRAMIENTA"] = str(clon)

        resultado = self.ejecutar(ACTUALIZAR, "revisar", "--todos")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("2 commit(s) por detrás", resultado.stdout)
        self.assertIn("git pull", resultado.stdout)

    def test_revisar_todos_no_avisa_si_la_herramienta_esta_al_dia(self):
        _, clon = self.herramienta_clonada()
        self.entorno["INGENIERIA_REQUISITOS_HERRAMIENTA"] = str(clon)

        resultado = self.ejecutar(ACTUALIZAR, "revisar", "--todos")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("por detrás", resultado.stdout)

    def test_revisar_una_ruta_no_toca_la_red_ni_avisa(self):
        """Una ruta suelta debe funcionar offline: sin fetch y sin aviso."""
        origen, clon = self.herramienta_clonada()
        (origen / "METODO.txt").write_text("v2\n", encoding="utf-8")
        self.commitear(origen, "método v2")
        self.entorno["INGENIERIA_REQUISITOS_HERRAMIENTA"] = str(clon)
        ws = self.workspace_antiguo()

        resultado = self.ejecutar(ACTUALIZAR, "revisar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("por detrás", resultado.stdout)
        # Y el clon sigue sin enterarse del avance: nadie hizo fetch a sus espaldas.
        cuenta = subprocess.run(
            ["git", "-C", str(clon), "rev-list", "--count", "HEAD..origin/main"],
            text=True, encoding="utf-8", errors="replace", capture_output=True, check=True,
        ).stdout.strip()
        self.assertEqual(cuenta, "0")

    def test_huella_estado_colapsa_el_modo_en_windows(self):
        """Caso de campo (09-08): Windows relee 0o644/0o755 como 0o666 y el fichero que
        Modo D acababa de escribir pasaba por "trabajo ajeno". En Windows el modo se
        colapsa a escribible/solo-lectura; en POSIX sigue contando entero."""
        sys.path.insert(0, str(RAIZ / "visor"))
        import actualizar
        from unittest import mock

        # En POSIX el modo distingue: 644 y 666 son huellas distintas.
        with mock.patch("os.name", "posix"):
            self.assertNotEqual(
                actualizar.huella_estado((b"x", 0o100644)),
                actualizar.huella_estado((b"x", 0o100666)),
            )
        with mock.patch("os.name", "nt"):
            self.assertEqual(
                actualizar.huella_estado((b"x", 0o100644)),
                actualizar.huella_estado((b"x", 0o100666)),
            )
            self.assertEqual(
                actualizar.huella_estado((b"x", 0o100755)),
                actualizar.huella_estado((b"x", 0o100666)),
            )
            # Solo-lectura sigue siendo distinguible de escribible.
            self.assertNotEqual(
                actualizar.huella_estado((b"x", 0o100444)),
                actualizar.huella_estado((b"x", 0o100666)),
            )
            # Y el contenido sigue mandando: mismo modo, bytes distintos.
            self.assertNotEqual(
                actualizar.huella_estado((b"x", 0o100644)),
                actualizar.huella_estado((b"y", 0o100644)),
            )

    def test_manifiesto_y_huella_usan_rutas_posix(self):
        """Caso de campo (09-08): el manifiesto es POSIX y el disco se recorría con
        separador nativo — en Windows todo faltaba y sobraba a la vez, y la huella de la
        plantilla no casaba con ninguna. Contrato: nada de backslashes en ninguna pieza."""
        sys.path.insert(0, str(RAIZ / "visor"))
        import bootstrap

        for relativo in bootstrap.manifiesto_metodo():
            self.assertNotIn("\\", relativo)
        # La verificación real de publicabilidad la ejercita el CI de Windows; aquí el
        # contrato local: la huella se calcula y es estable (sin depender del separador).
        self.assertTrue(bootstrap.huella_plantilla())

    def test_runbook_modo_d_no_invita_a_push_sin_autoridad(self):
        """Incidente de campo (P1, 06-08): un agente en Modo D publicó en un remoto ajeno.
        El runbook decía 'un git push y listo'. Contrato: en la sección del Modo D,
        ninguna mención a git push sin exigir el OK explícito del dueño en el mismo
        párrafo."""
        runbook = (RAIZ / "RUNBOOK" / "modo-d.md").read_text(encoding="utf-8")
        inicio = runbook.index("## Modo D")
        fin = runbook.find("## ", inicio + 1)
        seccion = runbook[inicio:] if fin == -1 else runbook[inicio:fin]
        parrafos_con_push = [
            p for p in seccion.split("\n\n") if "git push" in p or "`push`" in p
        ]
        self.assertTrue(parrafos_con_push, "el Modo D ya no documenta el push: revisa el test")
        for parrafo in parrafos_con_push:
            self.assertIn(
                "OK explícito",
                " ".join(parrafo.split()),
                "el Modo D menciona git push sin exigir el OK explícito del dueño:\n"
                + parrafo,
            )

    def test_aplicar_no_repone_esqueleto_sobre_carpeta_existente(self):
        ws = self.workspace_antiguo()

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        # El índice de bugs del workspace tenía contenido propio: Modo D no lo toca.
        self.assertEqual(
            (ws / "docs/bugs/INDICE.md").read_text(encoding="utf-8"), "001-antigua\n"
        )

    def test_aplicar_ignora_pycache_sucio_y_no_lo_commitea(self):
        ws = self.workspace_antiguo()
        pycache = ws / "docs/00-metodo/scripts/__pycache__"
        pycache.mkdir(parents=True)
        pyc = pycache / "repo_config.cpython-311.pyc"
        pyc.write_bytes(b"\x00bytecode")

        resultado = self.ejecutar(ACTUALIZAR, "aplicar", str(ws))

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("sucio", (resultado.stdout + resultado.stderr).lower())
        self.assertTrue(pyc.is_file())
        commiteados = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            cwd=ws, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True,
        ).stdout
        self.assertNotIn("__pycache__", commiteados)
        # El .gitignore repartido ya ignora el bytecode: el árbol queda limpio de verdad.
        estado = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ws, text=True,
            encoding="utf-8", errors="replace",
            capture_output=True, check=True,
        ).stdout
        self.assertNotIn("__pycache__", estado)


class RamaFusionadaDelLinterTest(unittest.TestCase):
    """Bug 022: rama_fusionada de lint_metodo.py es una copia del testigo de
    peticion.py y quedó atrás del arreglo del bug 021 — FAIL falso sobre un
    exprés squash-mergeado de verdad con la rama borrada y el P-ID (no el
    nombre exacto) en el asunto. Mismo contrato que el 021, sin relajar la
    anti-fabricación. El linter es un guion: se prueba como subprocess."""

    LINT = RAIZ / "plantilla/docs/00-metodo/scripts/lint_metodo.py"
    PID = "P-20260815-032bc9b1"
    RAMA = "expres-P-20260815-032bc9b1-gitignore-ci-visor-contratos"
    DENUNCIA = "exprés terminal sin cambio fusionado"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lint-testigo-")
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / "docs/05-trabajo/peticiones" / self.PID).mkdir(parents=True)
        self.repo = self.raiz / "main"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        (self.repo / "a.txt").write_text("base\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, text=True,
            encoding="utf-8", errors="replace", capture_output=True
        ).stdout.strip()

    def squash_en_main(self, asunto):
        (self.repo / "a.txt").write_text("cambio\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", asunto)

    def peticion_terminal(self, base_sha):
        ruta = self.raiz / "docs/05-trabajo/peticiones" / self.PID / "peticion.json"
        ruta.write_text(json.dumps({
            "formato": 1, "id": self.PID, "estado": "cerrada", "revision": 1,
            "resultado": "entregada",
            "original": {"autor": "Test", "resumen": "x", "texto": "x"},
            "aclaraciones": [], "evaluaciones": [], "reclamos": [], "relaciones": [],
            "cierres": [], "responsable": None,
            "creada": "2026-08-15T00:00:00+00:00",
            "actualizada": "2026-08-18T00:00:00+00:00",
            "procesos": [{
                "tipo": "expres", "ref": self.RAMA, "relacion": "satisface",
                "estado": "terminal", "revision": 1,
                "fecha": "2026-08-15T00:00:00+00:00",
                "contrato_terminal": "rama-expres-v1",
                "metadata": {"base_sha": base_sha, "principal": "main"},
            }],
        }, ensure_ascii=False), encoding="utf-8")

    def lint(self):
        return subprocess.run(
            [sys.executable, str(self.LINT), "--raiz", str(self.raiz)],
            text=True, encoding="utf-8", errors="replace", capture_output=True,
        )

    def test_squash_real_sin_rama_viva_no_es_fail(self):
        self.squash_en_main("expres P-20260815-032bc9b1: desbloquea visor_contratos/ (#16)")
        self.peticion_terminal(self.base)

        salida = self.lint()
        texto = salida.stdout + salida.stderr

        self.assertNotIn(self.DENUNCIA, texto,
                         "el linter debe reconocer el mismo testigo que peticion.py (021/022)")

    def test_sin_p_id_ni_nombre_en_el_asunto_sigue_siendo_fail(self):
        self.squash_en_main("commit cualquiera sin rastro de la peticion")
        self.peticion_terminal(self.base)

        texto = self.lint().stdout

        self.assertIn(self.DENUNCIA, texto, "sin testigo el FAIL debe seguir: no se relaja")

    def test_base_fuera_de_la_principal_sigue_siendo_fail(self):
        subprocess.run(["git", "checkout", "--orphan", "huerfana"],
                       cwd=self.repo, check=True, capture_output=True)
        (self.repo / "b.txt").write_text("otra\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "raiz ajena")
        base_ajena = self.git("rev-parse", "HEAD")
        self.git("checkout", "main")
        self.squash_en_main("expres P-20260815-032bc9b1: lo que sea (#16)")
        self.peticion_terminal(base_ajena)

        texto = self.lint().stdout

        self.assertIn(self.DENUNCIA, texto)


if __name__ == "__main__":
    unittest.main()
