"""Unidad 033: cada regla del método tiene quien la haga cumplir.

Seis puertas que hoy se saltan tecleando un dato. La evidencia que necesitan YA se
escribe (recibos de `.runtime/ejecuciones/`, rastro del visor, huella de planos, base
de despacho de la rama, fecha del OK del usuario): estas pruebas exigen que se lea.
"""
import datetime
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
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
PLANTILLAS = RAIZ / "plantilla/docs/00-metodo/plantillas"
VISOR = RAIZ / "visor"
HOY = datetime.date.today().isoformat()

# Marca que R7 exige a toda puerta nueva: ningún bloqueo sin vía de salida escrita.
SALIDA = "SALIDA:"


class WorkspaceBase(unittest.TestCase):
    """Workspace de método mínimo pero REAL: scripts, plantillas y repo de código."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reglas-ejecutor-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()

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

        self.repo = self.ws / "main"
        (self.repo / "app").mkdir(parents=True)
        for indice in range(1, 7):
            (self.repo / "app" / f"modulo{indice}.py").write_text(
                "print('base')\n", encoding="utf-8"
            )
        self.git(self.repo, "init", "-b", "main")
        self.git(self.repo, "config", "user.name", "Test")
        self.git(self.repo, "config", "user.email", "test@example.com")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-m", "base")
        self.sha = self.git(self.repo, "rev-parse", "HEAD")

    # ------------------------------------------------------------------ utilidades
    def git(self, cwd, *args):
        resultado = subprocess.run(
            ["git", *args], cwd=str(cwd), text=True, capture_output=True
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        return resultado.stdout.strip()

    def ejecutar(self, script, *args):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True,
        )

    def capturar(self, resumen="Cambio solicitado"):
        resultado = self.ejecutar(
            self.peticion, "capturar", "--resumen", resumen,
            "--texto", "Implementa el cambio descrito", "--autor", "Nate",
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return re.search(r"P-\d{8}-[a-f0-9]{8}", resultado.stdout).group(0)

    def evaluar(self, pid, ruta="feature", tipo=None, huella="planos-v1",
                ruta_codigo="app/modulo1.py"):
        args = [
            "evaluar", pid, "--ruta", ruta, "--investigacion", "ninguna",
            "--motivo", "contraste suficiente para encaminar",
            "--flujo", "REC-1", "--huella-flujo", huella,
            "--sha", self.sha, "--ruta-codigo", ruta_codigo,
            "--conocimiento", "docs/decisiones/004-paleta.md",
        ]
        if tipo:
            args.extend(("--tipo", tipo))
        return self.ejecutar(self.peticion, *args)

    def recibo_ejecucion(self, unidad, rol, session_id, modelo=None, sufijo="",
                         resultado="ok", exit_code=0):
        """Escribe un recibo del control plane como el que deja `ejecucion.py`.

        `resultado`/`exit_code` son parametrizables porque `ejecucion.py` escribe el recibo
        ANTES de lanzar el harness: existe también cuando la revisión falló o ni arrancó.
        """
        carpeta = self.ws / ".runtime/ejecuciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        identificador = f"{rol}{sufijo}"
        ruta = carpeta / f"{unidad}-{identificador}.json"
        ruta.write_text(json.dumps({
            "schema": "ejecucion/v1",
            "id": identificador,
            "unidad": unidad,
            "harness": "claude",
            "rol": rol,
            "modelo": modelo,
            "cwd": str(self.ws / "worktrees" / unidad),
            "rama": unidad,
            "lease": {"session_id": session_id, "fencing": {}},
            "git": {"inicial": {}, "final": {}},
            "skills_tecnicas": [],
            "checkpoints": [],
            "exit_code": exit_code,
            **({} if resultado is None else {"resultado": resultado}),
        }, ensure_ascii=False), encoding="utf-8")
        return ruta

    # -------------------------------------------------- unidad documental cerrable
    def unidad_documental(self, slug, revisor="agente-fresco"):
        """Unidad real, en_revision, con revisión firmada. Lista para `cerrar`."""
        pid = self.capturar(f"Documentar {slug}")
        evaluada = self.evaluar(pid, ruta="documentacion")
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        creada = self.ejecutar(
            self.unidad, "nueva", "documentacion", slug, "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        carpeta = next((self.ws / "docs/05-trabajo").glob(f"[0-9][0-9][0-9]-{slug}"))
        spec = carpeta / "especificacion.md"
        texto = spec.read_text(encoding="utf-8")
        texto = texto.replace("estado: planificada", "estado: en_revision")
        texto = texto.replace("aprobado: no", f"aprobado: {HOY}")
        texto = texto.replace("\n---\n", "\nejecucion: documental\n---\n", 1)
        spec.write_text(texto, encoding="utf-8")
        self.firmar_revision(carpeta / "hallazgos.md", revisor)
        return carpeta.name

    def firmar_revision(self, hallazgos, revisor="agente-fresco", fecha=HOY):
        texto = hallazgos.read_text(encoding="utf-8")
        texto = re.sub(r"^revisor:.*$", f"revisor: {revisor}", texto, count=1, flags=re.M)
        texto = re.sub(r"^revisado:.*$", f"revisado: {fecha}", texto, count=1, flags=re.M)
        texto = texto.replace(
            "- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN", "- **Veredicto:** LIMPIO"
        )
        hallazgos.write_text(texto, encoding="utf-8")

    def cerrar(self, nombre, *extra):
        return self.ejecutar(self.unidad, "cerrar", nombre, *extra)


# ===================================================================== R1 y R2
class RecibosDeRevisionTest(WorkspaceBase):
    """R1/R2 — la firma del revisor no vale sin recibo de ejecución propio."""

    def test_r1_cierre_sin_recibo_de_revisor_falla_y_nombra_el_comando(self):
        nombre = self.unidad_documental("revision-sin-recibo")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("recibo", salida.lower())
        self.assertIn("ejecucion.py", salida)
        self.assertIn("--rol revisor", salida)
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_cierre_con_recibo_de_revisor_pasa_la_puerta(self):
        nombre = self.unidad_documental("revision-con-recibo")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "sesion-revisor")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())

    def test_r2_recibo_de_revisor_con_la_sesion_del_constructor_falla(self):
        nombre = self.unidad_documental("auto-sello")
        self.recibo_ejecucion(nombre, "constructor", "sesion-unica")
        self.recibo_ejecucion(nombre, "revisor", "sesion-unica")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("misma", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_recibo_de_revisor_fallido_no_acredita_la_revision(self):
        """Un recibo con `resultado: fail` prueba que la revisión NO salió bien."""
        nombre = self.unidad_documental("revision-fallida")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "sesion-revisor",
                              resultado="fail", exit_code=2)

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("no acredita", salida.lower())
        self.assertIn("ejecucion.py", salida)
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_recibo_de_revisor_sin_identidad_de_sesion_no_acredita(self):
        """Sin identidad de sesión no se puede demostrar que el revisor no sea el
        constructor: la puerta de R2 se queda sin dato y el cierre no pasa."""
        nombre = self.unidad_documental("revision-sin-sesion")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("no acredita", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_recibo_de_revisor_abortado_no_acredita_la_revision(self):
        """`ejecucion.py` escribe el recibo ANTES de lanzar el harness: un recibo sin
        `resultado` y con `exit_code: null` es una revisión que ni siquiera terminó."""
        nombre = self.unidad_documental("revision-abortada")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "sesion-revisor",
                              resultado=None, exit_code=None)

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("no acredita", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r2_mismo_modelo_y_distinta_sesion_avisa_pero_cierra(self):
        nombre = self.unidad_documental("mismo-modelo")
        self.recibo_ejecucion(nombre, "constructor", "sesion-a", modelo="opus")
        self.recibo_ejecucion(nombre, "revisor", "sesion-b", modelo="opus")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("mismo modelo", salida.lower())
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())


# ============================================================ paso 2: modelo en el recibo
class ReciboGuardaModeloTest(unittest.TestCase):
    """El recibo del control plane guarda el modelo: hoy llega por argumento y se pierde,
    y sin él R2 no puede distinguir 'otro agente' de 'otro modelo'."""

    def test_el_recibo_inicial_incluye_el_modelo_del_harness(self):
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(lambda: sys.path.remove(str(SCRIPTS)))
        import importlib
        ejecucion = importlib.import_module("ejecucion")

        class Args:
            unidad = "001-x"
            harness = "claude"
            rol = "revisor"
            modelo = "claude-sonnet-5"
            skill_tecnica = []

        recibo = ejecucion.recibo_inicial(
            Args(), "id-1", Path("/tmp/wt"), "sesion-1", {}, {}
        )

        self.assertEqual(recibo["modelo"], "claude-sonnet-5")
        self.assertEqual(recibo["rol"], "revisor")
        self.assertEqual(recibo["lease"]["session_id"], "sesion-1")


# =========================================================================== R6
class OkEnLoteTest(WorkspaceBase):
    """R6 — el OK del usuario no se firma en lote con una sola fecha."""

    def cerrar_documental_con_ok(self, slug):
        nombre = self.unidad_documental(slug)
        self.recibo_ejecucion(nombre, "constructor", f"c-{slug}")
        self.recibo_ejecucion(nombre, "revisor", f"r-{slug}")
        return nombre, self.cerrar(nombre, "--ok-usuario", HOY)

    def test_r6_cuarta_unidad_con_la_misma_fecha_de_ok_falla(self):
        for indice in range(1, 4):
            nombre, resultado = self.cerrar_documental_con_ok(f"lote-{indice}")
            self.assertEqual(
                resultado.returncode, 0, resultado.stdout + resultado.stderr
            )

        nombre, resultado = self.cerrar_documental_con_ok("lote-4")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("lote", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r6_acta_que_solo_nombra_las_unidades_no_vale(self):
        """El contrato pide un acta con UNA FILA POR UNIDAD, no una lista de nombres:
        una enumeración no dice qué probó el usuario en cada entrega."""
        cerradas = []
        for indice in range(1, 4):
            nombre, resultado = self.cerrar_documental_con_ok(f"sinfila-{indice}")
            self.assertEqual(
                resultado.returncode, 0, resultado.stdout + resultado.stderr
            )
            cerradas.append(nombre)

        nombre = self.unidad_documental("sinfila-4")
        self.recibo_ejecucion(nombre, "constructor", "c-sf4")
        self.recibo_ejecucion(nombre, "revisor", "r-sf4")
        acta = self.ws / "docs/05-trabajo/lista-suelta.md"
        acta.write_text(
            "# Validación en lote\n\nEl usuario validó todas estas unidades:\n\n"
            + "".join(f"- {cerrada}\n" for cerrada in [*cerradas, nombre]),
            encoding="utf-8",
        )

        resultado = self.cerrar(
            nombre, "--ok-usuario", HOY, "--validacion-lote", str(acta)
        )

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("fila", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r6_acta_con_filas_vacias_de_validacion_no_vale(self):
        """Una tabla cuyas filas solo repiten el nombre y la fecha no acredita nada:
        la fila tiene que decir QUÉ probó el usuario en esa unidad."""
        cerradas = []
        for indice in range(1, 4):
            nombre, resultado = self.cerrar_documental_con_ok(f"filavacia-{indice}")
            self.assertEqual(
                resultado.returncode, 0, resultado.stdout + resultado.stderr
            )
            cerradas.append(nombre)

        nombre = self.unidad_documental("filavacia-4")
        self.recibo_ejecucion(nombre, "constructor", "c-fv4")
        self.recibo_ejecucion(nombre, "revisor", "r-fv4")
        acta = self.ws / "docs/05-trabajo/tabla-hueca.md"
        filas = "\n".join(
            f"| {cerrada} | {HOY} |  |" for cerrada in [*cerradas, nombre]
        )
        acta.write_text(
            f"# Validación en lote\n\n| unidad | fecha | qué probó el usuario |\n"
            f"|---|---|---|\n{filas}\n",
            encoding="utf-8",
        )

        resultado = self.cerrar(
            nombre, "--ok-usuario", HOY, "--validacion-lote", str(acta)
        )

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("fila", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r6_con_documento_de_validacion_por_unidad_cierra(self):
        cerradas = []
        for indice in range(1, 4):
            nombre, resultado = self.cerrar_documental_con_ok(f"conlote-{indice}")
            self.assertEqual(
                resultado.returncode, 0, resultado.stdout + resultado.stderr
            )
            cerradas.append(nombre)

        nombre = self.unidad_documental("conlote-4")
        self.recibo_ejecucion(nombre, "constructor", "c-4")
        self.recibo_ejecucion(nombre, "revisor", "r-4")
        acta = self.ws / "docs/05-trabajo/validacion-lote.md"
        filas = "\n".join(
            f"| {cerrada} | {HOY} | probada en la app corriendo |"
            for cerrada in [*cerradas, nombre]
        )
        acta.write_text(
            f"# Validación en lote\n\n| unidad | fecha | qué probó el usuario |\n"
            f"|---|---|---|\n{filas}\n",
            encoding="utf-8",
        )

        resultado = self.cerrar(
            nombre, "--ok-usuario", HOY, "--validacion-lote", str(acta)
        )

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())


# =========================================================================== R4
class HuellaDeFlujoTest(WorkspaceBase):
    """R4 — la huella declarada al evaluar se compara con la real de los planos."""

    def escribir_planos(self):
        planos = self.ws / "docs/02-flujos/planos"
        planos.mkdir(parents=True)
        (planos / "planos.json").write_text(
            json.dumps({"version": 1, "actividades": []}), encoding="utf-8"
        )
        return planos / "planos.json"

    def huella_real(self):
        sys.path.insert(0, str(self.ws / "docs/00-metodo/scripts"))
        try:
            resultado = self.ejecutar(self.peticion, "huella-planos")
        finally:
            sys.path.pop(0)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        return re.search(r"[0-9a-f]{64}", resultado.stdout).group(0)

    def test_r4_huella_inventada_falla_y_muestra_las_dos(self):
        self.escribir_planos()
        real = self.huella_real()
        pid = self.capturar("Con huella inventada")

        resultado = self.evaluar(pid, huella="planos-v1")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("planos-v1", salida)
        self.assertIn(real, salida)
        self.assertIn(SALIDA, salida)

    def test_r4_huella_real_evalua(self):
        self.escribir_planos()
        real = self.huella_real()
        pid = self.capturar("Con huella real")

        resultado = self.evaluar(pid, huella=real)

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)

    def test_r4_sin_planos_no_bloquea_pero_avisa(self):
        pid = self.capturar("Workspace sin planos todavía")

        resultado = self.evaluar(pid, huella="planos-v1")

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn(SALIDA, salida)


# =========================================================================== R5
class CarrilDirectoMedidoTest(WorkspaceBase):
    """R5 — el carril directo se mide contra el punto de partida de su rama."""

    CUERPO = """

# {nnn} · Cambio pequeño y localizado

## Qué (en idioma de negocio)

El usuario podrá completar el cambio solicitado sin alterar el comportamiento adyacente.
La implementación conserva los datos existentes y muestra un resultado verificable en la
misma entrada que usa hoy, sin pedirle ningún paso nuevo ni mover nada de sitio.

## Criterios de aceptación

- **R1** — Cuando el usuario repite la acción de siempre, el resultado aparece igual.
- **R2** — (caso límite) Cuando el dato falta, no se pierde el trabajo ya hecho.

## Verificación

- Comando(s) que deben salir en verde: `python3 -m pytest`
- **Nivel de test:** unitario, porque la conducta es una regla local y no cruza fronteras.
"""

    def unidad_directa(self, slug, ficheros):
        pid = self.capturar(f"Directo {slug}")
        evaluada = self.evaluar(
            pid, ruta="directo", tipo="feature", ruta_codigo=ficheros[0]
        )
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        creada = self.ejecutar(
            self.unidad, "nueva", "feature", slug, "--directo", "--desde", pid
        )
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        carpeta = next((self.ws / "docs/05-trabajo").glob(f"[0-9][0-9][0-9]-{slug}"))
        spec = carpeta / "especificacion.md"
        texto = spec.read_text(encoding="utf-8")
        cabecera = texto[: texto.find("---", 4) + 3]
        cabecera = cabecera.replace("aprobado: no", f"aprobado: {HOY}")
        cabecera = re.sub(
            r"^ficheros:.*$", "ficheros: [" + ", ".join(ficheros) + "]",
            cabecera, count=1, flags=re.M,
        )
        cabecera = re.sub(r"^actividad:.*$", "actividad: pedidos", cabecera,
                          count=1, flags=re.M)
        spec.write_text(
            cabecera + self.CUERPO.format(nnn=carpeta.name), encoding="utf-8"
        )
        despachada = self.ejecutar(self.unidad, "despachar", carpeta.name)
        self.assertEqual(
            despachada.returncode, 0, despachada.stdout + despachada.stderr
        )
        return carpeta.name

    def trabajar_y_fusionar(self, nombre, cambios):
        worktree = self.ws / "worktrees" / nombre
        for fichero, lineas in cambios.items():
            (worktree / fichero).write_text(
                "".join(f"print({indice})\n" for indice in range(lineas)),
                encoding="utf-8",
            )
        self.git(worktree, "add", "-A")
        self.git(worktree, "commit", "-m", f"trabajo de {nombre}")
        self.git(self.repo, "merge", "--ff-only", nombre)
        self.git(self.repo, "worktree", "remove", str(worktree))
        carpeta = self.ws / "docs/05-trabajo" / nombre
        spec = carpeta / "especificacion.md"
        spec.write_text(
            re.sub(r"^estado:\s*\S+", "estado: en_revision",
                   spec.read_text(encoding="utf-8"), count=1, flags=re.M),
            encoding="utf-8",
        )
        self.firmar_revision(carpeta / "hallazgos.md")
        self.recibo_ejecucion(nombre, "constructor", f"c-{nombre}")
        self.recibo_ejecucion(nombre, "revisor", f"r-{nombre}")

    def borrar_rama(self, nombre):
        """Borra la rama ya fusionada: el cierre real la borra, y sin ella la medida
        tenía que salir igual de la punta que la base de despacho ya identifica."""
        self.git(self.repo, "branch", "-D", nombre)

    def olvidar_base_de_despacho(self, nombre):
        """Deja la unidad como una legacy: sin `base_sha` anotado en su petición."""
        for ruta in (self.ws / "docs/05-trabajo/peticiones").glob("*/peticion.json"):
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            tocado = False
            for proceso in datos.get("procesos", []):
                if proceso.get("ref") == nombre:
                    (proceso.get("metadata") or {}).pop("base_sha", None)
                    tocado = True
            if tocado:
                ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    def test_r5_directo_desbordado_con_la_rama_ya_borrada_sigue_fallando(self):
        """Borrar la rama antes de cerrar no puede ser la forma de saltarse la puerta:
        la base de despacho registrada permite medir contra la punta fusionada."""
        nombre = self.unidad_directa(
            "directo-sin-rama",
            ["app/modulo1.py", "app/modulo2.py", "app/modulo3.py"],
        )
        self.trabajar_y_fusionar(nombre, {
            f"app/modulo{indice}.py": 80 for indice in range(1, 6)
        })
        self.borrar_rama(nombre)

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("directo", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r5_sin_base_registrada_ni_rama_avisa_pero_cierra(self):
        """Solo cuando NO hay base de despacho anotada (unidades legacy) la puerta se
        queda sin dato: entonces avisa en vez de bloquear, porque medir sería inventar."""
        nombre = self.unidad_directa("directo-legacy", ["app/modulo1.py"])
        self.trabajar_y_fusionar(nombre, {
            f"app/modulo{indice}.py": 80 for indice in range(1, 6)
        })
        self.borrar_rama(nombre)
        self.olvidar_base_de_despacho(nombre)

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("sin base de despacho", salida.lower())
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())

    def test_r5_directo_con_cinco_ficheros_y_400_lineas_falla(self):
        nombre = self.unidad_directa(
            "directo-desbordado",
            ["app/modulo1.py", "app/modulo2.py", "app/modulo3.py"],
        )
        self.trabajar_y_fusionar(nombre, {
            f"app/modulo{indice}.py": 80 for indice in range(1, 6)
        })

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("directo", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r5_directo_dentro_de_los_limites_cierra(self):
        nombre = self.unidad_directa("directo-contenido", ["app/modulo1.py"])
        self.trabajar_y_fusionar(nombre, {"app/modulo1.py": 10})

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())

    def test_r5_directo_fuera_de_los_ficheros_declarados_falla(self):
        nombre = self.unidad_directa("directo-desviado", ["app/modulo1.py"])
        self.trabajar_y_fusionar(nombre, {"app/modulo6.py": 5})

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("app/modulo6.py", salida)
        self.assertIn(SALIDA, salida)


# =========================================================================== R3
class VisorAntesDeAprobarTest(unittest.TestCase):
    """R3 — aprobar el mapa exige rastro de visor posterior al último cambio."""

    def setUp(self):
        sys.path.insert(0, str(VISOR))
        self.addCleanup(lambda: sys.path.remove(str(VISOR)))
        import importlib
        self.revision = importlib.import_module("revision")
        importlib.reload(self.revision)

        self.tmp = tempfile.TemporaryDirectory(prefix="visor-aprobar-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()
        self.mapa = self.ws / "docs/02-flujos/planos/planos.json"
        self.mapa.parent.mkdir(parents=True)
        shutil.copyfile(VISOR / "ejemplo.json", self.mapa)
        (self.ws / ".runtime").mkdir()

    def rastro_visor(self, edad_segundos=0):
        registro = self.ws / ".runtime/visor-8765.log"
        registro.write_text("Visor abierto\n", encoding="utf-8")
        if edad_segundos:
            momento = registro.stat().st_mtime - edad_segundos
            os.utime(registro, (momento, momento))
        return registro

    def test_r3_aprobar_sin_rastro_de_visor_falla_y_nombra_el_comando(self):
        with self.assertRaises(ValueError) as capturado:
            self.revision.aprobar(self.mapa, "Nate")

        mensaje = str(capturado.exception)
        self.assertIn("visor", mensaje.lower())
        self.assertIn("requisitos.py", mensaje)
        self.assertIn(SALIDA, mensaje)

    def test_r3_rastro_anterior_al_ultimo_cambio_de_planos_falla(self):
        self.rastro_visor(edad_segundos=3600)

        with self.assertRaises(ValueError) as capturado:
            self.revision.aprobar(self.mapa, "Nate")

        self.assertIn(SALIDA, str(capturado.exception))

    def test_r3_con_rastro_fresco_aprueba(self):
        self.rastro_visor()

        recibo = self.revision.aprobar(self.mapa, "Nate", True)

        self.assertEqual(recibo["estado"], "aprobado")
        self.assertEqual(recibo["por"], "Nate")


# =========================================================================== R7
class SalidaEscritaTest(unittest.TestCase):
    """R7 — ninguna puerta nueva bloquea sin nombrar su comando o su vía de salida.

    No basta con que el mensaje diga `SALIDA:`: detrás tiene que haber algo que el
    lector pueda TECLEAR o HACER. Se exige un comando real o un carril nombrado.
    """

    ACCIONABLE = re.compile(r"(python3 \S+\.py|`[^`]+`)")

    def mensajes(self):
        sys.path.insert(0, str(SCRIPTS))
        sys.path.insert(0, str(VISOR))
        self.addCleanup(lambda: sys.path.remove(str(SCRIPTS)))
        self.addCleanup(lambda: sys.path.remove(str(VISOR)))
        import importlib
        unidad = importlib.import_module("unidad")
        peticion = importlib.import_module("peticion")
        revision = importlib.import_module("revision")
        return {
            "R1": unidad.mensaje_sin_recibo_revisor("001-x"),
            "R1-recibo": unidad.mensaje_recibo_no_acredita(
                "001-x", ["el recibo revisor-1 terminó con exit_code 2"]
            ),
            "R2": unidad.mensaje_auto_sello("001-x", "sesion-unica"),
            "R3": revision.MENSAJE_SIN_VISOR,
            "R4": peticion.mensaje_huella_discrepante("a" * 8, "b" * 64),
            "R5": unidad.mensaje_directo_desbordado(
                "001-x", 5, 400, ["app/otro.py"]
            ),
            "R6": unidad.mensaje_ok_en_lote("001-x", "2026-08-22", 3),
        }

    def test_r7_cada_mensaje_de_bloqueo_nombra_su_salida(self):
        for requisito, mensaje in self.mensajes().items():
            with self.subTest(requisito=requisito):
                self.assertIn(SALIDA, mensaje)
                cola = mensaje.split(SALIDA, 1)[1]
                self.assertTrue(
                    self.ACCIONABLE.search(cola),
                    f"{requisito}: la salida no nombra nada accionable: {cola!r}",
                )


# =========================================================================== R8
class MarcaRetiradaTest(unittest.TestCase):
    """R8 — lo que el ADR-029 declara retirado tiene que estar retirado DEL TEXTO.

    La marca retirada se estampaba a mano y se borraba antes de imprimir: no acreditaba
    nada. Lo que hace infranqueable a una puerta es el script que la ejecuta y el test que
    lo demuestra. Las puertas siguen; la etiqueta se va.

    La marca se compone en trozos a propósito: este fichero entra en el barrido y escribirla
    entera aquí haría que la prueba se señalara a sí misma. La comprobación es la misma.
    """

    MARCA = "<HARD" + "-GATE>"
    ADR = "029-una-regla-tiene-ejecutor-o-se-retira.md"

    def ficheros_del_metodo(self):
        raices = [RAIZ / "plantilla/docs/00-metodo", RAIZ / "visor"]
        for raiz in raices:
            for ruta in sorted(raiz.rglob("*")):
                if ruta.suffix in {".md", ".py"} and ruta.is_file():
                    if ruta.name == self.ADR or "__pycache__" in ruta.parts:
                        continue
                    yield ruta

    def test_r8_la_marca_retirada_no_queda_en_el_texto_del_metodo(self):
        supervivientes = []
        for ruta in self.ficheros_del_metodo():
            texto = ruta.read_text(encoding="utf-8", errors="replace")
            for numero, linea in enumerate(texto.splitlines(), 1):
                if self.MARCA in linea:
                    supervivientes.append(f"{ruta.relative_to(RAIZ)}:{numero}")
        self.assertEqual(
            supervivientes, [],
            "el ADR-029 la declara retirada y sigue en el texto:\n  "
            + "\n  ".join(supervivientes),
        )

    def test_r8_el_adr_sigue_explicando_por_que_se_retiro(self):
        """La retirada sin motivo escrito es exactamente lo que el ADR prohíbe."""
        adr = (RAIZ / "plantilla/docs/00-metodo/decisiones" / self.ADR).read_text(
            encoding="utf-8"
        )
        self.assertIn(self.MARCA, adr)
        self.assertIn("Motivo de la retirada", adr)


if __name__ == "__main__":
    unittest.main()
