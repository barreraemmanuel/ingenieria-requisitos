import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
PETICION = RAIZ / "plantilla/docs/00-metodo/scripts/peticion.py"
SCRIPTS = PETICION.parent
PLANTILLAS = RAIZ / "plantilla/docs/00-metodo/plantillas"


class PeticionesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="peticiones-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        scripts = self.ws / "docs/00-metodo/scripts"
        scripts.mkdir(parents=True)
        self.script = scripts / "peticion.py"
        if PETICION.exists():
            shutil.copy2(PETICION, self.script)
            for nombre in ("control_plane.py", "repo_config.py", "workspace_paths.py"):
                shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True)
        for nombre in (
            "peticion-investigacion-plan.md",
            "peticion-investigacion-informe.md",
            "peticion-investigacion-sintesis.md",
        ):
            origen = PLANTILLAS / nombre
            if origen.exists():
                shutil.copy2(origen, plantillas / nombre)
        repo = self.ws / "main"
        (repo / "app").mkdir(parents=True)
        (repo / "app/terminal.py").write_text("print('ok')\n", encoding="utf-8")
        (repo / "app/permisos.py").write_text("DENEGAR = True\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
        self.sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, capture_output=True
        ).stdout.strip()
        conocimiento = self.ws / "docs/decisiones/004-paleta.md"
        conocimiento.parent.mkdir(parents=True)
        conocimiento.write_text("# Paleta vigente\n", encoding="utf-8")

    def ejecutar(self, *args):
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=self.ws,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )

    def capturar(self, resumen="Adoptar la guía v5", texto="aplica esta nueva guía"):
        resultado = self.ejecutar(
            "capturar",
            "--resumen",
            resumen,
            "--texto",
            texto,
            "--autor",
            "Nate",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        encontrado = re.search(r"P-\d{8}-[a-f0-9]{8}", resultado.stdout)
        self.assertIsNotNone(encontrado, resultado.stdout)
        return encontrado.group(0)

    def datos(self, pid):
        ruta = self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
        return json.loads(ruta.read_text(encoding="utf-8"))

    def unidad(self, nombre, estado="planificada", peticiones=None):
        ruta = self.ws / "docs/05-trabajo" / nombre / "especificacion.md"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if peticiones is None and ruta.exists():
            encontrada = re.search(
                r"^peticiones:\s*\[(.*?)\]", ruta.read_text(encoding="utf-8"), re.M
            )
            referencias = encontrada.group(1) if encontrada else ""
        else:
            if isinstance(peticiones, str):
                peticiones = [peticiones]
            referencias = ", ".join(f"{pid}@1" for pid in (peticiones or []))
        ruta.write_text(
            "---\n"
            f"unidad: {nombre}\n"
            "tipo: feature\n"
            "carril: normal\n"
            f"estado: {estado}\n"
            "aprobado: no\n"
            f"peticiones: [{referencias}]\n"
            "---\n\n# Contrato\n",
            encoding="utf-8",
        )
        return ruta

    def evaluar_ninguna(self, pid):
        resultado = self.ejecutar(
            "evaluar",
            pid,
            "--ruta",
            "feature",
            "--investigacion",
            "ninguna",
            "--motivo",
            "el flujo y el módulo ya existen",
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
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return resultado

    def test_captura_sobrevive_y_conserva_el_original(self):
        pid = self.capturar(texto="aplica esta nueva guía a las dinámicas")
        datos = self.datos(pid)

        self.assertEqual(datos["estado"], "capturada")
        self.assertEqual(
            datos["original"]["texto"], "aplica esta nueva guía a las dinámicas"
        )
        self.assertEqual(datos["revision"], 1)

        resultado = self.ejecutar(
            "aclarar",
            pid,
            "--texto",
            "prioriza las dinámicas",
            "--autor",
            "Nate",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        datos = self.datos(pid)
        self.assertEqual(
            datos["original"]["texto"], "aplica esta nueva guía a las dinámicas"
        )
        self.assertEqual(datos["revision"], 2)
        self.assertEqual(datos["estado"], "evaluando")
        self.assertEqual(datos["aclaraciones"][-1]["texto"], "prioriza las dinámicas")

    def test_dos_capturas_concurrentes_no_colisionan(self):
        comando = [
            sys.executable,
            str(self.script),
            "capturar",
            "--resumen",
            "Cambio",
            "--texto",
            "Haz X",
            "--autor",
            "Nate",
        ]
        procesos = [
            subprocess.Popen(
                comando,
                cwd=self.ws,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(2)
        ]
        resultados = []
        for proceso in procesos:
            stdout, stderr = proceso.communicate()
            resultados.append((proceso.returncode, stdout, stderr))

        self.assertEqual([r[0] for r in resultados], [0, 0], resultados)
        self.assertEqual(
            len(
                list(
                    (self.ws / "docs/05-trabajo/peticiones").glob(
                        "P-*/peticion.json"
                    )
                )
            ),
            2,
        )

    def test_solo_se_retira_un_lock_huerfano(self):
        pid = self.capturar()
        lock = self.ws / ".runtime/locks" / f"peticion-{pid}.lock"
        lock.mkdir(parents=True)
        (lock / "owner.json").write_text(
            json.dumps({"pid": os.getpid(), "host": socket.gethostname()}),
            encoding="utf-8",
        )
        vivo = self.ejecutar("desbloquear", pid)
        self.assertEqual(vivo.returncode, 1)
        self.assertTrue(lock.is_dir())
        (lock / "owner.json").write_text(
            json.dumps({"pid": 99999999, "host": socket.gethostname()}),
            encoding="utf-8",
        )

        huerfano = self.ejecutar("desbloquear", pid)

        self.assertEqual(huerfano.returncode, 0, huerfano.stderr)
        self.assertFalse(lock.exists())

    def test_reconciliacion_compuesta_valida_todo_antes_de_cerrar_nada(self):
        primera = self.capturar("Primera")
        segunda = self.capturar("Segunda")
        self.unidad("001-compuesta", peticiones=[primera, segunda])
        for pid in (primera, segunda):
            self.evaluar_ninguna(pid)
            enlazada = self.ejecutar(
                "enlazar", pid, "--tipo", "unidad", "--ref", "001-compuesta"
            )
            self.assertEqual(enlazada.returncode, 0, enlazada.stderr)
        aclarada = self.ejecutar(
            "aclarar",
            segunda,
            "--texto",
            "Cambia el alcance",
            "--autor",
            "Nate",
        )
        self.assertEqual(aclarada.returncode, 0, aclarada.stderr)

        codigo = (
            "import sys; "
            f"sys.path.insert(0, {str(self.script.parent)!r}); "
            "import peticion; "
            f"peticion.reconciliar_ids([{primera + '@1'!r}, {segunda + '@1'!r}], "
            "'unidad', '001-compuesta', 'sha-verificado')"
        )
        resultado = subprocess.run(
            [sys.executable, "-c", codigo],
            cwd=self.ws,
            text=True,
            capture_output=True,
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("revisi", resultado.stderr.lower())
        proceso = self.datos(primera)["procesos"][0]
        self.assertEqual(proceso["estado"], "pendiente")

    def test_enlace_compuesto_restaura_todos_los_json_si_falla_una_escritura(self):
        primera = self.capturar("Primera")
        segunda = self.capturar("Segunda")
        for pid in (primera, segunda):
            self.evaluar_ninguna(pid)
        self.unidad("001-lote", peticiones=[primera, segunda])
        codigo = f"""
import sys
sys.path.insert(0, {str(self.script.parent)!r})
import peticion
real = peticion.guardar
cuenta = {{"n": 0}}
def guardar(datos):
    cuenta["n"] += 1
    if cuenta["n"] == 2:
        raise OSError("fallo inyectado")
    return real(datos)
peticion.guardar = guardar
try:
    peticion.enlazar_procesos(
        [{primera + '@1'!r}, {segunda + '@1'!r}], "unidad", "001-lote"
    )
except OSError:
    pass
else:
    raise SystemExit("el fallo inyectado no se propagó")
"""

        resultado = subprocess.run(
            [sys.executable, "-c", codigo], cwd=self.ws,
            text=True, capture_output=True,
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(self.datos(primera)["procesos"], [])
        self.assertEqual(self.datos(segunda)["procesos"], [])

    def test_aparcar_exige_motivo_y_revision(self):
        pid = self.capturar()

        resultado = self.ejecutar(
            "aparcar", pid, "--motivo", "más adelante", "--por", "agente"
        )
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("revisar", resultado.stderr.lower())

        resultado = self.ejecutar(
            "aparcar",
            pid,
            "--motivo",
            "esperar la guía oficial",
            "--revisar-el",
            "2026-09-01",
            "--por",
            "agente",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        datos = self.datos(pid)
        self.assertEqual(datos["estado"], "aparcada")
        self.assertEqual(datos["aparcada"]["revisar_el"], "2026-09-01")

    def test_duplicada_exige_otra_peticion_existente(self):
        pid = self.capturar("Duplicada", "Haz lo mismo")

        resultado = self.ejecutar("duplicar", pid, "--de", "P-20260804-deadbeef")
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("no existe", resultado.stderr.lower())

        canonica = self.capturar("Canónica", "Haz lo canónico")
        resultado = self.ejecutar("duplicar", pid, "--de", canonica)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        datos = self.datos(pid)
        self.assertEqual(datos["estado"], "cerrada")
        self.assertEqual(datos["resultado"], "duplicada")
        self.assertEqual(datos["relaciones"][-1]["ref"], canonica)

    def test_cancelar_conserva_historia(self):
        pid = self.capturar()
        original = self.datos(pid)["original"].copy()

        resultado = self.ejecutar(
            "cancelar", pid, "--motivo", "Nate cambió de prioridad", "--por", "Nate"
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        datos = self.datos(pid)
        self.assertEqual(datos["estado"], "cancelada")
        self.assertEqual(datos["resultado"], "cancelada")
        self.assertEqual(datos["original"], original)
        self.assertEqual(datos["cierres"][-1]["motivo"], "Nate cambió de prioridad")

    def test_investigacion_ninguna_exige_flujo_codigo_y_conocimiento(self):
        pid = self.capturar()

        resultado = self.ejecutar(
            "evaluar",
            pid,
            "--ruta",
            "feature",
            "--investigacion",
            "ninguna",
            "--motivo",
            "es un patrón conocido",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("flujo", resultado.stderr.lower())
        self.assertIn("sha", resultado.stderr.lower())
        self.assertIn("conocimiento", resultado.stderr.lower())

    def test_acotada_crea_plan_y_no_encamina_sin_sintesis(self):
        pid = self.capturar()

        resultado = self.ejecutar(
            "evaluar",
            pid,
            "--ruta",
            "feature",
            "--investigacion",
            "acotada",
            "--motivo",
            "toca autorización",
            "--disparador",
            "seguridad",
            "--pregunta",
            "¿qué debe denegarse?",
            "--flujo",
            "REC-1",
            "--huella-flujo",
            "planos-v1",
            "--sha",
            self.sha,
            "--ruta-codigo",
            "app/permisos.py",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        plan = (
            self.ws
            / "docs/05-trabajo/peticiones"
            / pid
            / "investigacion/revision-1/PLAN.md"
        )
        self.assertTrue(plan.is_file())
        self.assertIn("¿qué debe denegarse?", plan.read_text(encoding="utf-8"))

        self.unidad("001-permisos", peticiones=pid)
        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-permisos"
        )
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("SINTESIS.md", resultado.stderr)

    def test_acotada_con_sintesis_respondida_puede_encaminar(self):
        pid = self.capturar()
        pregunta = "¿qué debe denegarse?"
        resultado = self.ejecutar(
            "evaluar",
            pid,
            "--ruta",
            "feature",
            "--investigacion",
            "acotada",
            "--motivo",
            "toca autorización",
            "--disparador",
            "seguridad",
            "--pregunta",
            pregunta,
            "--flujo",
            "REC-1",
            "--huella-flujo",
            "planos-v1",
            "--sha",
            self.sha,
            "--ruta-codigo",
            "app/permisos.py",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        sintesis = (
            self.ws
            / "docs/05-trabajo/peticiones"
            / pid
            / "investigacion/revision-1/SINTESIS.md"
        )
        sintesis.write_text(
            f"# Síntesis de investigación · {pid} · revisión 1\n\n"
            "## Respuestas\n\n"
            f"- respondida · {pregunta} · evidencia: main/app/permisos.py#L1 · "
            "fecha: 2026-08-04\n\n"
            "## Decisión para el triaje definitivo\n\n"
            "Se mantiene la ruta feature y el carril normal con denegación por defecto.\n\n"
            "## Conclusiones estables que se promocionan\n\nNinguna.\n",
            encoding="utf-8",
        )

        self.unidad("001-permisos", peticiones=pid)
        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-permisos"
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_no_concluyente_bloquea_un_riesgo_critico(self):
        pid = self.capturar()
        pregunta = "¿qué debe denegarse?"
        resultado = self.ejecutar(
            "evaluar",
            pid,
            "--ruta",
            "feature",
            "--investigacion",
            "acotada",
            "--motivo",
            "toca autorización",
            "--disparador",
            "seguridad",
            "--pregunta",
            pregunta,
            "--flujo",
            "REC-1",
            "--huella-flujo",
            "planos-v1",
            "--sha",
            self.sha,
            "--ruta-codigo",
            "app/permisos.py",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        sintesis = (
            self.ws
            / "docs/05-trabajo/peticiones"
            / pid
            / "investigacion/revision-1/SINTESIS.md"
        )
        sintesis.write_text(
            f"# Síntesis de investigación · {pid} · revisión 1\n\n"
            "## Respuestas\n\n"
            f"- no_concluyente · {pregunta} · evidencia: main/app/permisos.py#L1 · "
            "fecha: 2026-08-04\n\n"
            "## Decisión para el triaje definitivo\n\n"
            "Se bloquea el triaje hasta resolver la contradicción sobre la denegación.\n\n"
            "## Conclusiones estables que se promocionan\n\nNinguna.\n",
            encoding="utf-8",
        )

        self.unidad("001-permisos", peticiones=pid)
        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-permisos"
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("no concluyente", resultado.stderr.lower())
        self.assertIn("seguridad", resultado.stderr.lower())

    def test_aclaracion_material_no_reutiliza_sintesis_de_revision_anterior(self):
        pid = self.capturar()
        pregunta = "¿qué debe denegarse?"

        def evaluar():
            return self.ejecutar(
                "evaluar", pid,
                "--ruta", "feature",
                "--investigacion", "acotada",
                "--motivo", "toca autorización",
                "--disparador", "seguridad",
                "--pregunta", pregunta,
                "--flujo", "REC-1",
                "--huella-flujo", "planos-v1",
                "--sha", self.sha,
                "--ruta-codigo", "app/permisos.py",
            )

        primera = evaluar()
        self.assertEqual(primera.returncode, 0, primera.stderr)
        sintesis_v1 = (
            self.ws / "docs/05-trabajo/peticiones" / pid
            / "investigacion/revision-1/SINTESIS.md"
        )
        sintesis_v1.write_text(
            f"# Síntesis de investigación · {pid} · revisión 1\n\n"
            "## Respuestas\n\n"
            f"- respondida · {pregunta} · evidencia: main/app/permisos.py#L1 · "
            "fecha: 2026-08-04\n\n"
            "## Decisión para el triaje definitivo\n\n"
            "Se mantiene la ruta feature con denegación segura por defecto.\n",
            encoding="utf-8",
        )
        aclarada = self.ejecutar(
            "aclarar", pid, "--texto", "Incluye otro actor", "--autor", "Nate"
        )
        self.assertEqual(aclarada.returncode, 0, aclarada.stderr)
        segunda = evaluar()
        self.assertEqual(segunda.returncode, 0, segunda.stderr)
        self.unidad("001-no-recicla", peticiones=pid)

        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-no-recicla"
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("revision-2", resultado.stderr)

    def test_sintesis_rechaza_una_ruta_con_ancla_inexistente(self):
        pid = self.capturar()
        pregunta = "¿qué debe denegarse?"
        evaluada = self.ejecutar(
            "evaluar", pid,
            "--ruta", "feature",
            "--investigacion", "acotada",
            "--motivo", "toca autorización",
            "--disparador", "seguridad",
            "--pregunta", pregunta,
            "--flujo", "REC-1",
            "--huella-flujo", "planos-v1",
            "--sha", self.sha,
            "--ruta-codigo", "app/permisos.py",
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        sintesis = (
            self.ws / "docs/05-trabajo/peticiones" / pid
            / "investigacion/revision-1/SINTESIS.md"
        )
        sintesis.write_text(
            f"# Síntesis de investigación · {pid} · revisión 1\n\n"
            "## Respuestas\n\n"
            f"- respondida · {pregunta} · evidencia: main/app/permisos.py#L999 · "
            "fecha: 2026-08-04\n\n"
            "## Decisión para el triaje definitivo\n\n"
            "Se mantiene la ruta feature y se deniega por defecto.\n",
            encoding="utf-8",
        )
        self.unidad("001-ancla-falsa", peticiones=pid)

        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-ancla-falsa"
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("evidencia anclada", resultado.stderr.lower())

    def test_plataforma_referencia_la_sintesis_de_fase_tres(self):
        pid = self.capturar("Elegir plataforma")
        sintesis = self.ws / "docs/03-investigacion/SINTESIS.md"
        sintesis.parent.mkdir(parents=True)
        for indice in range(1, 11):
            (sintesis.parent / f"informe-{indice:02d}-enfoque.md").write_text(
                "# Informe de plataforma\n\n"
                "## Fuente\n\n"
                "- nivel: 1\n"
                "- fecha: 2026-08-04\n"
                "- URL: https://example.com/documentacion-oficial\n\n"
                + "Conclusión contrastada y aplicable a los cimientos del proyecto. " * 5,
                encoding="utf-8",
            )
        sintesis.write_text(
            "# SÍNTESIS — cimientos técnicos\n\n"
            "## Decisiones vigentes\n\n"
            "- respondida · ¿dónde corre? · evidencia: "
            "docs/03-investigacion/informe-01-enfoque.md#fuente · fecha: 2026-08-04\n\n"
            + "La plataforma se decide con diez informes fechados y contrastados. " * 8,
            encoding="utf-8",
        )
        evaluada = self.ejecutar(
            "evaluar", pid,
            "--ruta", "feature",
            "--investigacion", "plataforma",
            "--motivo", "cambia los cimientos",
            "--disparador", "plataforma",
            "--pregunta", "¿dónde corre?",
            "--flujo", "REC-1",
            "--huella-flujo", "planos-v1",
            "--sintesis-plataforma", "docs/03-investigacion/SINTESIS.md",
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        self.unidad("001-plataforma", peticiones=pid)

        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-plataforma"
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_plataforma_admite_informes_nuevos_sin_invalidar_los_diez_fundacionales(self):
        pid = self.capturar("Ampliar investigación de plataforma")
        carpeta = self.ws / "docs/03-investigacion"
        carpeta.mkdir(parents=True)
        for indice in range(1, 12):
            (carpeta / f"informe-{indice:02d}-enfoque.md").write_text(
                "# Informe\n\n## Fuente\n\nnivel: 1\nfecha: 2026-08-04\n"
                "URL: https://example.com/fuente-oficial\n\n"
                + "Evidencia independiente, contrastada y útil para decidir la plataforma. " * 5,
                encoding="utf-8",
            )
        (carpeta / "SINTESIS.md").write_text(
            "# Síntesis\n\n"
            "- respondida · ¿dónde corre? · evidencia: "
            "docs/03-investigacion/informe-01-enfoque.md#fuente · fecha: 2026-08-04\n\n"
            + "La síntesis conserva los diez cimientos y añade evidencia posterior. " * 8,
            encoding="utf-8",
        )

        evaluada = self.ejecutar(
            "evaluar", pid, "--ruta", "feature", "--investigacion", "plataforma",
            "--motivo", "cambia los cimientos", "--disparador", "plataforma",
            "--pregunta", "¿dónde corre?", "--flujo", "REC-1",
            "--huella-flujo", "planos-v1", "--sintesis-plataforma",
            "docs/03-investigacion/SINTESIS.md",
        )

        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        self.unidad("001-plataforma-ampliada", peticiones=pid)
        enlace = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-plataforma-ampliada"
        )
        self.assertEqual(enlace.returncode, 0, enlace.stderr)

    def test_plataforma_no_sustituye_un_informe_fundacional_por_el_numero_once(self):
        pid = self.capturar("Investigar plataforma incompleta")
        carpeta = self.ws / "docs/03-investigacion"
        carpeta.mkdir(parents=True)
        for indice in range(2, 12):
            (carpeta / f"informe-{indice:02d}-enfoque.md").write_text(
                "# Informe\n\nnivel: 1\nfecha: 2026-08-04\n"
                "URL: https://example.com/fuente-oficial\n\n"
                + "Evidencia independiente para contrastar la decisión de plataforma. " * 6,
                encoding="utf-8",
            )
        (carpeta / "SINTESIS.md").write_text(
            "# Síntesis\n\n"
            "- respondida · ¿dónde corre? · evidencia: "
            "docs/03-investigacion/informe-02-enfoque.md#fuente · fecha: 2026-08-04\n\n"
            + "La síntesis intenta cerrar sin el primer informe fundacional. " * 8,
            encoding="utf-8",
        )

        evaluada = self.ejecutar(
            "evaluar", pid, "--ruta", "feature", "--investigacion", "plataforma",
            "--motivo", "cambia los cimientos", "--disparador", "plataforma",
            "--pregunta", "¿dónde corre?", "--flujo", "REC-1",
            "--huella-flujo", "planos-v1", "--sintesis-plataforma",
            "docs/03-investigacion/SINTESIS.md",
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        self.unidad("001-plataforma-sin-primero", peticiones=pid)

        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-plataforma-sin-primero"
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("01..10", resultado.stderr)

    def test_plataforma_no_concluyente_bloquea_un_riesgo_critico(self):
        pid = self.capturar("Investigar seguridad de plataforma")
        carpeta = self.ws / "docs/03-investigacion"
        carpeta.mkdir(parents=True)
        for indice in range(1, 11):
            (carpeta / f"informe-{indice:02d}-seguridad.md").write_text(
                "# Informe\n\n## Fuente\n\n"
                "nivel: 1\nfecha: 2026-08-04\n"
                "URL: https://example.com/fuente-oficial\n\n"
                + "La evidencia disponible todavía presenta una contradicción material. " * 5,
                encoding="utf-8",
            )
        (carpeta / "SINTESIS.md").write_text(
            "# SÍNTESIS — cimientos técnicos\n\n"
            "- no_concluyente · ¿cómo se aíslan los datos? · evidencia: "
            "docs/03-investigacion/informe-01-seguridad.md#fuente · fecha: 2026-08-04\n\n"
            + "La decisión queda bloqueada hasta resolver la contradicción de seguridad. " * 6,
            encoding="utf-8",
        )
        evaluada = self.ejecutar(
            "evaluar", pid,
            "--ruta", "feature",
            "--investigacion", "plataforma",
            "--motivo", "cambia el aislamiento",
            "--disparador", "seguridad",
            "--pregunta", "¿cómo se aíslan los datos?",
            "--flujo", "REC-1",
            "--huella-flujo", "planos-v1",
            "--sintesis-plataforma", "docs/03-investigacion/SINTESIS.md",
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        self.unidad("001-plataforma-bloqueada", peticiones=pid)

        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-plataforma-bloqueada"
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("no concluyente", resultado.stderr.lower())

    def test_aclaracion_material_invalida_revision_anterior(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        self.unidad("001-terminal", peticiones=pid)
        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-terminal"
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

        resultado = self.ejecutar(
            "aclarar",
            pid,
            "--texto",
            "también afecta pagos",
            "--autor",
            "Nate",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        resultado = self.ejecutar("comprobar-revision", pid, "--revision", "1")
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("revisión 2", resultado.stderr)

    def test_aclaracion_informativa_no_invalida_la_revision(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)

        resultado = self.ejecutar(
            "aclarar",
            pid,
            "--texto",
            "El ejemplo anterior era ilustrativo",
            "--autor",
            "Nate",
            "--informativa",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(self.datos(pid)["revision"], 1)
        vigente = self.ejecutar("comprobar-revision", pid, "--revision", "1")
        self.assertEqual(vigente.returncode, 0, vigente.stderr)

    def test_no_se_puede_enlazar_ni_entregar_una_unidad_inexistente(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)

        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "999-no-existe"
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("no existe", resultado.stderr.lower())
        self.assertEqual(self.datos(pid)["procesos"], [])

    def test_un_fichero_existente_no_disfraza_una_ruta_de_deploy(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        evidencia = self.ws / "docs/deploy.md"
        evidencia.write_text("# Supuesto deploy\n", encoding="utf-8")

        resultado = self.ejecutar(
            "enlazar", pid, "--tipo", "deploy", "--ref", "docs/deploy.md"
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("ficha canónica", resultado.stderr.lower())
        self.assertEqual(self.datos(pid)["procesos"], [])

    def test_deploy_fuera_de_una_unidad_no_es_proceso_canonico(self):
        pid = self.capturar("Desplegar")
        resultado = self.ejecutar(
            "evaluar", pid, "--ruta", "deploy", "--investigacion", "ninguna",
            "--motivo", "operación conocida", "--flujo", "REC-1",
            "--huella-flujo", "planos-v1", "--sha", self.sha,
            "--ruta-codigo", "app/terminal.py", "--conocimiento",
            "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        ficha = self.ws / "cualquier/despliegue.md"
        ficha.parent.mkdir()
        ficha.write_text(
            "---\nproceso: deploy\nestado: preparado\n"
            f"peticiones: [{pid}@1]\n---\n",
            encoding="utf-8",
        )

        enlace = self.ejecutar(
            "enlazar", pid, "--tipo", "deploy", "--ref", "cualquier/despliegue.md"
        )

        self.assertEqual(enlace.returncode, 1)
        self.assertIn("docs/05-trabajo", enlace.stderr)

    def test_deploy_correctamente_enrutado_exige_ficha_y_contrato_terminal(self):
        pid = self.capturar("Desplegar")
        evaluada = self.ejecutar(
            "evaluar", pid,
            "--ruta", "deploy", "--investigacion", "ninguna",
            "--motivo", "operación conocida",
            "--flujo", "REC-1", "--huella-flujo", "planos-v1",
            "--sha", self.sha, "--ruta-codigo", "app/terminal.py",
            "--conocimiento", "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        ficha = self.ws / "docs/05-trabajo/001-release/despliegue.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nproceso: deploy\nestado: preparada\n"
            f"peticiones: [{pid}@1]\n---\n\n# Ficha todavía pendiente\n",
            encoding="utf-8",
        )
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "deploy", "--ref",
            "docs/05-trabajo/001-release/despliegue.md",
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)

        resultado = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "deploy",
            "--ref", "docs/05-trabajo/001-release/despliegue.md",
            "--evidencia", "afirmación sin ficha completa",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("estado: desplegado", resultado.stderr.lower())
        self.assertEqual(self.datos(pid)["estado"], "encaminada")
        ficha.write_text(
            "---\nproceso: deploy\nestado: desplegado\n"
            f"peticiones: [{pid}@1]\netapa: 1-lan\ncommit: {self.sha}\n"
            "fecha: 2026-08-04\n---\n\n"
            "# Despliegue verificado\n\n> Sin secretos.\n\n"
            "- **Commit/tag:** " + self.sha + " · ya en main\n"
            "- **Etapa destino y máquina exacta:** 1 LAN — servidor de pruebas\n"
            "- **Qué cambia para el usuario, en una frase:** terminal corregida\n"
            "- **OK del usuario ANTES de salir:** OK (2026-08-04, Nate)\n"
            "- **Suite completa sobre este commit:** VERDE · .runtime/pre-deploy/full-suite.log\n"
            "- **Seguridad sobre este commit:** VERDE · .runtime/pre-deploy/security.log\n"
            "- **Qué se copió y adónde:** base y ficheros a backup externo\n"
            "- **Volcado — comando y salida:** backup-db terminó correctamente\n"
            "- **Restauración de prueba:** restaurada en staging; consultas verificadas\n"
            "1. **Pasos**: actualizar servicio y reiniciar worker\n"
            "2. **Vuelta atrás:** restaurar backup y volver al commit anterior\n"
            "- **Flujo real de negocio de punta a punta:** alta completa — captura 42\n"
            "- **Vigilancia:** monitor verde y error inocuo registrado — evento 84\n"
            "- **Validación del usuario sobre la etapa desplegada:** OK (2026-08-04)\n"
            "- **Resultado:** DESPLEGADO → sin incidencias\n"
            "- **Quién y cuándo:** Nate — 2026-08-04 12:30\n"
            "- **Anotado en `conocimiento/plano-deploy.md`:** LAN corre " + self.sha + "\n",
            encoding="utf-8",
        )

        completada = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "deploy",
            "--ref", "docs/05-trabajo/001-release/despliegue.md",
            "--evidencia", "ficha completa y etapa verificada",
        )

        self.assertEqual(completada.returncode, 0, completada.stderr)
        self.assertEqual(self.datos(pid)["estado"], "cerrada")

    def test_deploy_minimo_inventado_no_puede_declararse_entregado(self):
        pid = self.capturar("Desplegar")
        resultado = self.ejecutar(
            "evaluar", pid, "--ruta", "deploy", "--investigacion", "ninguna",
            "--motivo", "operación conocida", "--flujo", "REC-1",
            "--huella-flujo", "planos-v1", "--sha", self.sha,
            "--ruta-codigo", "app/terminal.py", "--conocimiento",
            "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        ficha = self.ws / "docs/05-trabajo/001-release/despliegue.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nproceso: deploy\nestado: desplegado\n"
            f"peticiones: [{pid}@1]\netapa: 1-lan\ncommit: {self.sha}\n"
            "fecha: 2026-08-04\n---\n\n"
            "- **Validación del usuario sobre la etapa desplegada:** OK (2026-08-04)\n",
            encoding="utf-8",
        )
        enlace = self.ejecutar(
            "enlazar", pid, "--tipo", "deploy", "--ref",
            "docs/05-trabajo/001-release/despliegue.md",
        )
        self.assertEqual(enlace.returncode, 0, enlace.stderr)

        cierre = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "deploy", "--ref",
            "docs/05-trabajo/001-release/despliegue.md", "--evidencia", "afirmado",
        )

        self.assertEqual(cierre.returncode, 1)
        self.assertIn("evidencia obligatoria", cierre.stderr.lower())
        self.assertEqual(self.datos(pid)["estado"], "encaminada")

    def test_flujos_solo_cierran_con_recibo_de_la_huella_vigente(self):
        pid = self.capturar("Aprobar flujos")
        resultado = self.ejecutar(
            "evaluar", pid, "--ruta", "flujos", "--investigacion", "ninguna",
            "--motivo", "validar los planos", "--flujo", "REC-1",
            "--huella-flujo", "planos-v1", "--sha", self.sha,
            "--ruta-codigo", "app/terminal.py", "--conocimiento",
            "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        planos = self.ws / "docs/02-flujos/planos"
        planos.mkdir(parents=True)
        mapa = {"version": 1, "actividades": []}
        (planos / "planos.json").write_text(json.dumps(mapa), encoding="utf-8")
        recibo = planos / "aprobacion.json"
        recibo.write_text(
            json.dumps({
                "estado": "aprobado", "huella": "obsoleta",
                "fecha": "2026-08-04", "por": "Nate",
            }),
            encoding="utf-8",
        )
        enlace = self.ejecutar(
            "enlazar", pid, "--tipo", "flujos", "--ref",
            "docs/02-flujos/planos/aprobacion.json",
        )
        self.assertEqual(enlace.returncode, 0, enlace.stderr)
        obsoleto = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "flujos", "--ref",
            "docs/02-flujos/planos/aprobacion.json", "--evidencia", "recibo",
        )
        self.assertEqual(obsoleto.returncode, 1)
        bundle = {"planos.json": mapa}
        huella = hashlib.sha256(json.dumps(
            bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        recibo.write_text(
            json.dumps({
                "estado": "aprobado", "huella": huella,
                "fecha": "2026-99-99", "por": "Nate",
            }),
            encoding="utf-8",
        )
        fecha_invalida = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "flujos", "--ref",
            "docs/02-flujos/planos/aprobacion.json", "--evidencia", "recibo con fecha falsa",
        )
        self.assertEqual(fecha_invalida.returncode, 1)
        recibo.write_text(
            json.dumps({
                "estado": "aprobado", "huella": huella,
                "fecha": "2026-08-04", "por": "Nate",
            }),
            encoding="utf-8",
        )

        vigente = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "flujos", "--ref",
            "docs/02-flujos/planos/aprobacion.json", "--evidencia", "recibo vigente",
        )

        self.assertEqual(vigente.returncode, 0, vigente.stderr)

    def test_una_actividad_a_medias_de_entrevista_no_revienta_la_huella(self):
        # Bug 026 (visto en mindi-agents): planos.json declara una actividad cuyo
        # actividades/<id>/planos.json aún no existe (entrevista a medias) y
        # huella_planos_actual() moría con FileNotFoundError, bloqueando el
        # gobierno de peticiones del workspace entero. La actividad sin fichero
        # queda FUERA de la huella, con aviso; la huella sigue siendo determinista.
        pid = self.capturar("Aprobar flujos con una actividad a medias")
        resultado = self.ejecutar(
            "evaluar", pid, "--ruta", "flujos", "--investigacion", "ninguna",
            "--motivo", "validar los planos", "--flujo", "REC-1",
            "--huella-flujo", "planos-v1", "--sha", self.sha,
            "--ruta-codigo", "app/terminal.py", "--conocimiento",
            "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        planos = self.ws / "docs/02-flujos/planos"
        lista = planos / "actividades/lista"
        lista.mkdir(parents=True)
        mapa = {"version": 1,
                "actividades": [{"id": "lista"}, {"id": "fantasma"}]}
        (planos / "planos.json").write_text(json.dumps(mapa), encoding="utf-8")
        actividad = {"version": 2, "titulo": "Lista"}
        (lista / "planos.json").write_text(json.dumps(actividad), encoding="utf-8")
        bundle = {"planos.json": mapa, "actividades/lista/planos.json": actividad}
        huella = hashlib.sha256(json.dumps(
            bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        recibo = planos / "aprobacion.json"
        recibo.write_text(
            json.dumps({
                "estado": "aprobado", "huella": huella,
                "fecha": "2026-08-04", "por": "Nate",
            }),
            encoding="utf-8",
        )
        enlace = self.ejecutar(
            "enlazar", pid, "--tipo", "flujos", "--ref",
            "docs/02-flujos/planos/aprobacion.json",
        )
        self.assertEqual(enlace.returncode, 0, enlace.stderr)

        vigente = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "flujos", "--ref",
            "docs/02-flujos/planos/aprobacion.json", "--evidencia", "recibo vigente",
        )

        self.assertEqual(vigente.returncode, 0, vigente.stderr)
        self.assertIn("fantasma", vigente.stderr)
        self.assertIn("sin planos todavía", vigente.stderr)

    def test_unidad_descartada_no_cierra_la_peticion_como_entregada(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        self.unidad("001-descartada", peticiones=pid)
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-descartada"
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)
        self.unidad("001-descartada", "descartada")

        resultado = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "unidad",
            "--ref", "001-descartada", "--evidencia", "se descartó",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertNotEqual(self.datos(pid)["estado"], "cerrada")

    def test_reencuadre_de_deploy_no_puede_adoptar_una_ruta_feature(self):
        pid = self.capturar("Desplegar")
        evaluada = self.ejecutar(
            "evaluar", pid,
            "--ruta", "deploy", "--investigacion", "ninguna",
            "--motivo", "operación conocida",
            "--flujo", "REC-1", "--huella-flujo", "planos-v1",
            "--sha", self.sha, "--ruta-codigo", "app/terminal.py",
            "--conocimiento", "docs/decisiones/004-paleta.md",
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        ficha = self.ws / "docs/05-trabajo/001-release/despliegue.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nproceso: deploy\nestado: preparada\n"
            f"peticiones: [{pid}@1]\n---\n\n# Deploy\n",
            encoding="utf-8",
        )
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "deploy", "--ref",
            "docs/05-trabajo/001-release/despliegue.md",
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)
        aclarada = self.ejecutar(
            "aclarar", pid, "--texto", "Ahora pide una feature", "--autor", "Nate"
        )
        self.assertEqual(aclarada.returncode, 0, aclarada.stderr)
        self.evaluar_ninguna(pid)

        resultado = self.ejecutar(
            "reencuadrar-orden", pid, "--desde-revision", "1",
            "--tipo", "deploy", "--ref",
            "docs/05-trabajo/001-release/despliegue.md",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("ruta feature", resultado.stderr.lower())

    def test_reconciliacion_tardia_no_sobrescribe_una_cancelacion(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        self.unidad("001-cancelada", peticiones=pid)
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-cancelada"
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)
        proceso_cancelado = self.ejecutar(
            "marcar-proceso",
            pid,
            "--revision",
            "1",
            "--tipo",
            "unidad",
            "--ref",
            "001-cancelada",
            "--estado",
            "cancelado",
            "--evidencia",
            "parada segura confirmada",
        )
        self.assertEqual(proceso_cancelado.returncode, 0, proceso_cancelado.stderr)
        cancelada = self.ejecutar(
            "cancelar",
            pid,
            "--motivo",
            "el usuario detiene el cambio",
            "--por",
            "Nate",
        )
        self.assertEqual(cancelada.returncode, 0, cancelada.stderr)
        self.unidad("001-cancelada", "mergeada")

        resultado = self.ejecutar(
            "reconciliar",
            pid,
            "--revision",
            "1",
            "--tipo",
            "unidad",
            "--ref",
            "001-cancelada",
            "--evidencia",
            "llegó tarde",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertEqual(self.datos(pid)["estado"], "cancelada")
        self.assertEqual(self.datos(pid)["resultado"], "cancelada")

    def test_un_proceso_cancelado_no_puede_cerrar_como_entregado(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        self.unidad("001-no-entregada", peticiones=pid)
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-no-entregada"
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)
        cancelada = self.ejecutar(
            "marcar-proceso", pid,
            "--revision", "1", "--tipo", "unidad", "--ref", "001-no-entregada",
            "--estado", "cancelado", "--evidencia", "parada segura",
        )
        self.assertEqual(cancelada.returncode, 0, cancelada.stderr)

        resultado = self.ejecutar(
            "cerrar", pid,
            "--resultado", "entregada",
            "--evidencia", "no basta",
            "--cobertura", "no cubre la petición",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertNotEqual(self.datos(pid)["estado"], "cerrada")

    def test_reabrir_y_relacion_padre_conservan_historia(self):
        padre = self.capturar("Auditoría")
        hija = self.capturar("Hallazgo aceptado")
        cancelada = self.ejecutar(
            "cancelar", hija, "--motivo", "espera", "--por", "Nate"
        )
        self.assertEqual(cancelada.returncode, 0, cancelada.stderr)
        reabierta = self.ejecutar(
            "reabrir", hija, "--motivo", "vuelve a prioridad", "--por", "Nate"
        )
        self.assertEqual(reabierta.returncode, 0, reabierta.stderr)
        relacionada = self.ejecutar(
            "relacionar", hija, "--tipo", "padre", "--con", padre
        )
        self.assertEqual(relacionada.returncode, 0, relacionada.stderr)
        repetida = self.ejecutar(
            "relacionar", hija, "--tipo", "padre", "--con", padre
        )
        self.assertEqual(repetida.returncode, 0, repetida.stderr)

        datos = self.datos(hija)
        self.assertEqual(datos["revision"], 2)
        self.assertEqual(datos["estado"], "evaluando")
        self.assertEqual(datos["reaperturas"][0]["resultado_anterior"], "cancelada")
        self.assertEqual(datos["relaciones"][-1]["ref"], padre)
        self.assertEqual(len(datos["relaciones"]), 1)

    def test_cierre_compuesto_espera_todos_los_procesos(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        for ref in ("001-api", "002-ui"):
            self.unidad(ref, peticiones=pid)
            resultado = self.ejecutar(
                "enlazar", pid, "--tipo", "unidad", "--ref", ref
            )
            self.assertEqual(resultado.returncode, 0, resultado.stderr)

        self.unidad("001-api", "mergeada")
        resultado = self.ejecutar(
            "marcar-proceso",
            pid,
            "--revision",
            "1",
            "--tipo",
            "unidad",
            "--ref",
            "001-api",
            "--estado",
            "terminal",
            "--evidencia",
            "docs/05-trabajo/archivo/001-api/hallazgos.md",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        resultado = self.ejecutar(
            "cerrar",
            pid,
            "--resultado",
            "entregada",
            "--evidencia",
            "validación conjunta",
            "--cobertura",
            "API y UI",
        )
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("002-ui", resultado.stderr)

        self.unidad("002-ui", "mergeada")
        resultado = self.ejecutar(
            "marcar-proceso",
            pid,
            "--revision",
            "1",
            "--tipo",
            "unidad",
            "--ref",
            "002-ui",
            "--estado",
            "terminal",
            "--evidencia",
            "docs/05-trabajo/archivo/002-ui/hallazgos.md",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        resultado = self.ejecutar(
            "cerrar",
            pid,
            "--resultado",
            "entregada",
            "--evidencia",
            "validación conjunta",
            "--cobertura",
            "API y UI",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        datos = self.datos(pid)
        self.assertEqual(datos["estado"], "cerrada")
        self.assertEqual(datos["resultado"], "entregada")

    def test_reconciliar_un_proceso_es_idempotente(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        self.unidad("001-cambio", "mergeada", peticiones=pid)
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "unidad", "--ref", "001-cambio"
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)

        for _ in range(2):
            resultado = self.ejecutar(
                "reconciliar",
                pid,
                "--revision",
                "1",
                "--tipo",
                "unidad",
                "--ref",
                "001-cambio",
                "--evidencia",
                "unidad fusionada y validada",
            )
            self.assertEqual(resultado.returncode, 0, resultado.stderr)

        datos = self.datos(pid)
        self.assertEqual(datos["estado"], "cerrada")
        self.assertEqual(len(datos["cierres"]), 1)

    def test_reclamar_impide_dos_responsables(self):
        pid = self.capturar()

        primero = self.ejecutar("reclamar", pid, "--por", "agente-a")
        segundo = self.ejecutar("reclamar", pid, "--por", "agente-b")

        self.assertEqual(primero.returncode, 0, primero.stderr)
        self.assertEqual(segundo.returncode, 1)
        self.assertIn("agente-a", segundo.stderr)
        self.assertEqual(self.datos(pid)["responsable"], "agente-a")

    def test_reanudar_conserva_el_aparcamiento_en_el_historial(self):
        pid = self.capturar()
        aparcada = self.ejecutar(
            "aparcar",
            pid,
            "--motivo",
            "esperar al proveedor",
            "--condicion",
            "publica la versión estable",
            "--por",
            "agente-a",
        )
        self.assertEqual(aparcada.returncode, 0, aparcada.stderr)

        resultado = self.ejecutar("reanudar", pid, "--por", "agente-a")

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        datos = self.datos(pid)
        self.assertEqual(datos["estado"], "evaluando")
        self.assertNotIn("aparcada", datos)
        self.assertEqual(
            datos["historial_aparcados"][-1]["motivo"], "esperar al proveedor"
        )

    # --------------------------------------------------------- unidad 027: ruta/tipo (R5/R6)

    def evaluar_con(self, pid, ruta, tipo=None, investigacion="ninguna",
                     motivo="contraste suficiente para encaminar"):
        args = [
            "evaluar", pid, "--ruta", ruta,
        ]
        if tipo:
            args += ["--tipo", tipo]
        args += [
            "--investigacion", investigacion,
            "--motivo", motivo,
            "--flujo", "REC-1",
            "--huella-flujo", "planos-v1",
            "--sha", self.sha,
            "--ruta-codigo", "app/terminal.py",
            "--conocimiento", "docs/decisiones/004-paleta.md",
        ]
        return self.ejecutar(*args)

    def test_ruta_banana_falla_en_la_evaluacion_con_vocabulario(self):
        pid = self.capturar()

        resultado = self.evaluar_con(pid, "banana")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("vocabulario", resultado.stderr.lower())
        self.assertEqual(self.datos(pid)["evaluaciones"], [])

    def test_ruta_banana_con_tipo_falla_contra_el_vocabulario_de_carriles(self):
        pid = self.capturar()

        resultado = self.evaluar_con(pid, "banana", tipo="bug")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("carriles", resultado.stderr.lower())

    def test_par_carril_directo_y_tipo_bug_permite_nueva_bug_directo_sin_reevaluar(self):
        """El caso 1 de "Cómo lo pruebas tú": una sola evaluación, sin el baile evaluar↔nueva
        (unidad 027, R5)."""
        pid = self.capturar("Arreglar el launcher")

        evaluada = self.evaluar_con(pid, "directo", tipo="bug")

        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        # Sin baile evaluar↔nueva: ningún aviso de la forma antigua de --ruta. (El aviso de
        # "workspace sin planos" de la unidad 033 sí puede salir: no es el baile, es la
        # huella de flujo diciendo que aquí todavía no hay mapa contra el que contrastar.)
        self.assertNotIn("forma antigua", evaluada.stderr)
        datos = self.datos(pid)
        self.assertEqual(datos["evaluaciones"][-1]["carril_provisional"], "directo")
        self.assertEqual(datos["evaluaciones"][-1]["tipo_provisional"], "bug")
        # nueva/despachar validan el PAR sin reevaluar: se comprueba a nivel de puerta,
        # que es lo mismo que mira unidad.py.
        revision = self.ejecutar(
            "comprobar-revision", pid, "--revision", str(datos["revision"])
        )
        self.assertEqual(revision.returncode, 0, revision.stderr)

    def test_ruta_antigua_bug_sigue_funcionando_con_aviso_de_la_forma_nueva(self):
        """Compatibilidad retro (R5): --ruta bug sin --tipo sigue evaluando, con aviso."""
        pid = self.capturar("Bug legacy")

        resultado = self.evaluar_con(pid, "bug")

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("AVISO", resultado.stderr)
        self.assertIn("--ruta", resultado.stderr)
        datos = self.datos(pid)
        self.assertEqual(datos["evaluaciones"][-1]["carril_provisional"], "normal")
        self.assertEqual(datos["evaluaciones"][-1]["tipo_provisional"], "bug")

    def test_ruta_y_tipo_antiguos_incoherentes_no_se_cuelan(self):
        pid = self.capturar()

        resultado = self.evaluar_con(pid, "bug", tipo="feature")

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("carriles", resultado.stderr.lower())

    # ------------------------------------------------------- unidad 027: desenlazar (R4/R7)

    def test_desenlazar_exige_motivo(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        self.unidad("001-una-unidad", peticiones=pid)
        self.ejecutar("enlazar", pid, "--tipo", "unidad", "--ref", "001-una-unidad")

        resultado = self.ejecutar(
            "desenlazar", pid, "--tipo", "unidad", "--ref", "001-una-unidad",
            "--autor", "Nate",
        )

        self.assertEqual(resultado.returncode, 2)  # argparse: --motivo es obligatorio

    def test_desenlazar_el_enlace_vigente_se_rechaza(self):
        pid = self.capturar()
        self.evaluar_ninguna(pid)
        self.unidad("001-vigente", peticiones=pid)
        enlazada = self.ejecutar("enlazar", pid, "--tipo", "unidad", "--ref", "001-vigente")
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)

        resultado = self.ejecutar(
            "desenlazar", pid, "--tipo", "unidad", "--ref", "001-vigente",
            "--motivo", "me equivoqué de unidad", "--autor", "Nate",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("sustituida", resultado.stderr.lower())
        procesos = self.datos(pid)["procesos"]
        self.assertEqual(procesos[0]["estado"], "pendiente")

    def test_desenlazar_una_revision_sustituida_cancela_con_rastro(self):
        pid = self.capturar("Desplegar")
        evaluada = self.evaluar_con(pid, "deploy")
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        ficha = self.ws / "docs/05-trabajo/001-release/despliegue.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nproceso: deploy\nestado: preparada\n"
            f"peticiones: [{pid}@1]\n---\n\n# Deploy\n",
            encoding="utf-8",
        )
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "deploy", "--ref",
            "docs/05-trabajo/001-release/despliegue.md",
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)
        aclarada = self.ejecutar(
            "aclarar", pid, "--texto", "Cambia el destino del despliegue", "--autor", "Nate"
        )
        self.assertEqual(aclarada.returncode, 0, aclarada.stderr)
        reevaluada = self.evaluar_con(pid, "deploy")
        self.assertEqual(reevaluada.returncode, 0, reevaluada.stderr)
        ficha.write_text(
            "---\nproceso: deploy\nestado: preparada\n"
            f"peticiones: [{pid}@1]\n---\n\n# Deploy\n",
            encoding="utf-8",
        )

        reencuadrada = self.ejecutar(
            "reencuadrar-orden", pid, "--desde-revision", "1", "--tipo", "deploy",
            "--ref", "docs/05-trabajo/001-release/despliegue.md",
        )
        self.assertEqual(reencuadrada.returncode, 0, reencuadrada.stderr)

        resultado = self.ejecutar(
            "desenlazar", pid, "--tipo", "deploy",
            "--ref", "docs/05-trabajo/001-release/despliegue.md",
            "--motivo", "la revisión 1 quedó sustituida por la aclaración", "--autor", "Nate",
        )

        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        sustituido = next(
            p for p in self.datos(pid)["procesos"]
            if p["revision"] == 1 and p["tipo"] == "deploy"
        )
        self.assertEqual(sustituido["estado"], "cancelado")
        self.assertEqual(
            sustituido["motivo_cancelacion"], "la revisión 1 quedó sustituida por la aclaración"
        )
        self.assertEqual(sustituido["autor_cancelacion"], "Nate")
        self.assertIn("actualizado", sustituido)

    # ------------------------------------------------- unidad 027: ficha de despliegue LOTE (R3)

    def test_ficha_de_despliegue_de_lote_reconcilia_y_cierra_las_tres_unidades(self):
        pids = [self.capturar(f"Desplegar unidad {i}") for i in range(3)]
        ficha = self.ws / "docs/05-trabajo/despliegues/release-42.md"
        ficha.parent.mkdir(parents=True)
        cuerpo_evidencia = (
            "\n\n# Despliegue verificado\n\n> Sin secretos.\n\n"
            "- **Commit/tag:** " + self.sha + " · ya en main\n"
            "- **Etapa destino y máquina exacta:** 2 VPS — producción\n"
            "- **Qué cambia para el usuario, en una frase:** lote de 3 unidades\n"
            "- **OK del usuario ANTES de salir:** OK (2026-08-04, Nate)\n"
            "- **Suite completa sobre este commit:** VERDE · .runtime/pre-deploy/full-suite.log\n"
            "- **Seguridad sobre este commit:** VERDE · .runtime/pre-deploy/security.log\n"
            "- **Qué se copió y adónde:** base y ficheros a backup externo\n"
            "- **Volcado — comando y salida:** backup-db terminó correctamente\n"
            "- **Restauración de prueba:** restaurada en staging; consultas verificadas\n"
            "1. **Pasos**: actualizar servicio y reiniciar worker\n"
            "2. **Vuelta atrás:** restaurar backup y volver al commit anterior\n"
            "- **Flujo real de negocio de punta a punta:** alta completa — captura 42\n"
            "- **Vigilancia:** monitor verde y error inocuo registrado — evento 84\n"
            "- **Validación del usuario sobre la etapa desplegada:** OK (2026-08-04)\n"
            "- **Resultado:** DESPLEGADO → sin incidencias\n"
            "- **Quién y cuándo:** Nate — 2026-08-04 12:30\n"
            "- **Anotado en `conocimiento/plano-deploy.md`:** lote 42 corre " + self.sha + "\n"
        )
        referencias = ", ".join(f"{pid}@1" for pid in pids)
        ficha.write_text(
            "---\nproceso: deploy\nestado: desplegado\n"
            f"peticiones: [{referencias}]\n"
            "unidades: [017-uno, 018-dos, 019-tres]\n"
            f"etapa: 2-vps\ncommit: {self.sha}\nfecha: 2026-08-04\n---"
            + cuerpo_evidencia,
            encoding="utf-8",
        )
        for pid in pids:
            evaluada = self.evaluar_con(pid, "deploy")
            self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
            enlazada = self.ejecutar(
                "enlazar", pid, "--tipo", "deploy", "--ref",
                "docs/05-trabajo/despliegues/release-42.md",
            )
            self.assertEqual(enlazada.returncode, 0, enlazada.stderr)

        for pid in pids:
            resultado = self.ejecutar(
                "reconciliar", pid, "--revision", "1", "--tipo", "deploy",
                "--ref", "docs/05-trabajo/despliegues/release-42.md",
                "--evidencia", "lote 42 verificado en VPS",
            )
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            self.assertEqual(self.datos(pid)["estado"], "cerrada")

    def test_ficha_de_despliegue_de_lote_con_una_sola_unidad_no_cuela(self):
        pid = self.capturar("Desplegar")
        evaluada = self.evaluar_con(pid, "deploy")
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        ficha = self.ws / "docs/05-trabajo/despliegues/release-43.md"
        ficha.parent.mkdir(parents=True)
        ficha.write_text(
            "---\nproceso: deploy\nestado: desplegado\n"
            f"peticiones: [{pid}@1]\nunidades: [017-uno]\n"
            f"etapa: 2-vps\ncommit: {self.sha}\nfecha: 2026-08-04\n---\n\n"
            "# Despliegue de una sola unidad disfrazado de lote\n",
            encoding="utf-8",
        )
        enlazada = self.ejecutar(
            "enlazar", pid, "--tipo", "deploy", "--ref",
            "docs/05-trabajo/despliegues/release-43.md",
        )
        self.assertEqual(enlazada.returncode, 0, enlazada.stderr)

        resultado = self.ejecutar(
            "reconciliar", pid, "--revision", "1", "--tipo", "deploy",
            "--ref", "docs/05-trabajo/despliegues/release-43.md",
            "--evidencia", "solo una unidad",
        )

        self.assertEqual(resultado.returncode, 1)
        self.assertIn("al menos dos", resultado.stderr.lower())


class EvidenciaRamaFusionadaTest(unittest.TestCase):
    """Bug 021: el testigo del squash debe reconocer un merge REAL aunque la
    rama exprés ya no exista, no haya tip_sha guardado y el título del PR no
    conservara el nombre exacto de la rama — el P-ID que ese nombre siempre
    contiene basta como patrón. Los caminos estrictos no se relajan."""

    RAMA = "expres-P-20260815-032bc9b1-gitignore-ci-visor-contratos"

    def setUp(self):
        import importlib.util
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        spec = importlib.util.spec_from_file_location("peticion_bajo_prueba", PETICION)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.tmp = tempfile.TemporaryDirectory(prefix="testigo-squash-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "codigo"
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
            ["git", *args], cwd=self.repo, check=True, text=True, capture_output=True
        ).stdout.strip()

    def squash_en_main(self, asunto):
        (self.repo / "a.txt").write_text("cambio\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", asunto)
        return self.git("rev-parse", "HEAD")

    def test_squash_real_sin_rama_viva_se_reconoce_por_el_p_id(self):
        merge = self.squash_en_main(
            "expres P-20260815-032bc9b1: desbloquea visor_contratos/ (#16)"
        )
        prueba = self.mod.evidencia_rama_fusionada(
            self.repo, self.RAMA, "main", {"base_sha": self.base}
        )
        self.assertIsNotNone(
            prueba, "un squash real con el P-ID en el asunto debe valer como testigo"
        )
        self.assertEqual(merge, prueba["merge_sha"])
        self.assertEqual("squash", prueba["modo_fusion"])

    def test_sin_p_id_ni_nombre_de_rama_sigue_sin_testigo(self):
        self.squash_en_main("commit directo cualquiera sin rastro de la peticion")
        prueba = self.mod.evidencia_rama_fusionada(
            self.repo, self.RAMA, "main", {"base_sha": self.base}
        )
        self.assertIsNone(prueba, "sin P-ID ni nombre de rama no hay testigo: no se relaja")

    def test_base_fuera_de_la_principal_sigue_sin_testigo(self):
        """La guarda de ancestría de base_sha debe frenar ANTES del grep: un
        base de una rama huérfana (no ancestro de main) no gana testigo aunque
        el asunto del squash contenga el P-ID (hueco 1 de la revisión: el test
        anterior pasaba por accidente vía punta == base_sha)."""
        subprocess.run(
            ["git", "checkout", "--orphan", "huerfana"],
            cwd=self.repo, check=True, capture_output=True,
        )
        (self.repo / "b.txt").write_text("otra historia\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "raiz ajena")
        base_ajena = self.git("rev-parse", "HEAD")
        self.git("checkout", "main")
        self.squash_en_main("expres P-20260815-032bc9b1: lo que sea (#16)")

        prueba = self.mod.evidencia_rama_fusionada(
            self.repo, self.RAMA, "main", {"base_sha": base_ajena}
        )

        self.assertIsNone(
            prueba, "un base_sha fuera de la principal no puede ganar testigo por grep"
        )
        # Y sin base_sha en absoluto, tampoco (guarda de cabecera).
        self.assertIsNone(
            self.mod.evidencia_rama_fusionada(self.repo, self.RAMA, "main", {})
        )


if __name__ == "__main__":
    unittest.main()
