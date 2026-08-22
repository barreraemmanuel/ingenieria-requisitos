"""Unidad 033: cada regla del método tiene quien la haga cumplir.

Seis puertas que hoy se saltan tecleando un dato. La evidencia que necesitan YA se
escribe (recibos de `.runtime/ejecuciones/`, rastro del visor, huella de planos, base
de despacho de la rama, fecha del OK del usuario): estas pruebas exigen que se lea.
"""
import argparse
import contextlib
import datetime
import importlib
import io
import json
import os
import re
import shlex
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
            "control_plane.py", "ejecucion.py", "lease.py", "peticion.py",
            "repo_config.py", "unidad.py", "workspace_paths.py",
        ):
            shutil.copy2(SCRIPTS / nombre, scripts / nombre)
        self.peticion = scripts / "peticion.py"
        self.unidad = scripts / "unidad.py"
        self.ejecucion = scripts / "ejecucion.py"

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

    def ejecutar(self, script, *args, entorno=None):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=self.ws, text=True, encoding="utf-8", errors="replace",
            capture_output=True, env=entorno,
        )

    def sin_harness(self):
        """Entorno con `git` a mano y NINGÚN harness: `lanzar` llega hasta el final.

        `ejecucion.py` comprueba el estado de la ficha mucho antes de buscar el binario del
        harness. Recortar el PATH deja que la prueba atraviese de verdad toda la puerta de
        estado —que es lo que R2 mide— y se pare justo en el `shutil.which` siguiente, sin
        arrancar ningún agente en la máquina de quien ejecuta los tests.
        """
        entorno = dict(os.environ)
        entorno["PATH"] = str(Path(shutil.which("git")).parent)
        return entorno

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
        """Unidad documental REAL: despachada con `--documental`, firmada y en_revision.

        Se despacha de verdad, y no se simula editando el frontmatter, porque el cierre ya
        no se cree lo que la ficha dice de sí misma: el modo documental lo acredita el
        registro de despacho (bug 034, R5), que solo existe si alguien despachó.
        """
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
        cabecera = texto[: texto.find("---", 4) + 3].replace(
            "aprobado: no", f"aprobado: {HOY}"
        )
        spec.write_text(
            cabecera + self.CUERPO.format(nnn=carpeta.name), encoding="utf-8"
        )
        despachada = self.ejecutar(
            self.unidad, "despachar", carpeta.name, "--documental"
        )
        self.assertEqual(
            despachada.returncode, 0, despachada.stdout + despachada.stderr
        )
        spec.write_text(
            re.sub(r"^estado:\s*\S+", "estado: en_revision",
                   spec.read_text(encoding="utf-8"), count=1, flags=re.M),
            encoding="utf-8",
        )
        self.firmar_revision(carpeta / "hallazgos.md", revisor)
        return carpeta.name

    # ------------------------------------- unidad con worktree: donde la puerta SÍ aplica
    def unidad_revisable(self, slug, revisor="agente-fresco"):
        """Unidad REAL con rama y worktree, fusionada y firmada, sin recibos todavía.

        Las puertas del recibo se prueban aquí y ya no sobre una documental: una unidad
        documental no crea worktree por diseño (regla 2) y `ejecucion.py` lo exige, así
        que pedirle el recibo era pedirle una evidencia que su carril le prohíbe producir
        (bug 034, hallazgo D). R3 la deja fuera de la puerta; la puerta se sigue midiendo
        donde tiene sentido, que es una entrega con código.
        """
        nombre = self.unidad_con_rama(slug, ["app/modulo1.py"])
        self.trabajar_y_fusionar(nombre, {"app/modulo1.py": 10}, recibos=False)
        ficha, firma = self.ficha_de(nombre)
        self.firmar_revision(firma, revisor)
        return nombre

    def firmar_revision(self, hallazgos, revisor="agente-fresco", fecha=HOY):
        texto = hallazgos.read_text(encoding="utf-8")
        texto = re.sub(r"^revisor:.*$", f"revisor: {revisor}", texto, count=1, flags=re.M)
        texto = re.sub(r"^revisado:.*$", f"revisado: {fecha}", texto, count=1, flags=re.M)
        texto = texto.replace(
            "- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN", "- **Veredicto:** LIMPIO"
        )
        # La ficha de un bug es a la vez contrato y bitácora (ADR-006): su veredicto no
        # vive en un hallazgos.md aparte sino en su propia sección 6.
        texto = texto.replace(
            "LIMPIO | HUECOS DE CORRECCIÓN → <cuáles;", "LIMPIO ·"
        )
        hallazgos.write_text(texto, encoding="utf-8")

    def cerrar(self, nombre, *extra):
        return self.ejecutar(self.unidad, "cerrar", nombre, *extra)

    # -------------------------------------- unidades y bugs REALES, con rama y worktree
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

    CUERPO_BUG = """

# {nnn} · BUG: el listado pierde la última línea

## 1 · Reporte (el padre, con lo que cuenta el usuario)

- **Qué esperaba el usuario:** que al abrir el listado de pedidos apareciesen todas las
  filas guardadas, incluida la última que acaba de crear desde la misma pantalla.
- **Qué pasa en realidad:** la última fila no aparece hasta que se recarga la página
  entera, así que el usuario cree que su pedido no se ha guardado y lo repite.
- **Severidad: P2.** No hay pérdida de datos, pero genera pedidos duplicados a diario.

## 2 · Reproducción

1. Abre el listado de pedidos. 2. Crea uno nuevo. 3. Vuelve al listado sin recargar.
La fila recién creada no está; al recargar sí aparece, con sus datos correctos.

## 3 · Diagnóstico

El listado se pinta desde una copia en memoria que no se invalida al guardar, así que la
vista muestra el estado anterior a la escritura hasta la siguiente carga completa.

## 5 · Resolución

- **R1** — Cuando el usuario crea un pedido, la fila aparece en el listado sin recargar.

## 6 · Cierre (el padre, a petición del usuario)

- **Revisión (revisor fresco, ANTES del merge):** LIMPIO | HUECOS DE CORRECCIÓN → <cuáles;
  cada uno vuelve al subagente antes del merge> · Fecha: YYYY-MM-DD
- **Validación del usuario:** PENDIENTE
"""

    def ficha_de(self, nombre):
        """(ficha canónica, documento donde firma el revisor) de una unidad o un bug."""
        carpeta = self.ws / "docs/05-trabajo" / nombre
        if carpeta.is_dir():
            return carpeta / "especificacion.md", carpeta / "hallazgos.md"
        ficha = self.ws / "docs/bugs" / f"{nombre}.md"
        return ficha, ficha

    def unidad_con_rama(self, slug, ficheros, carril="normal", tipo="feature"):
        """Unidad (o bug) REAL: petición evaluada, ficha aprobada, rama y worktree.

        Es lo que las puertas de esta unidad vigilan de verdad: una entrega con worktree,
        a diferencia de la documental, que por diseño no tiene ninguno.
        """
        pid = self.capturar(f"Trabajo {slug}")
        evaluada = self.evaluar(pid, ruta=carril, tipo=tipo, ruta_codigo=ficheros[0])
        self.assertEqual(evaluada.returncode, 0, evaluada.stderr)
        argumentos = ["nueva", tipo, slug]
        if carril == "directo":
            argumentos.append("--directo")
        argumentos.extend(("--desde", pid))
        creada = self.ejecutar(self.unidad, *argumentos)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        if tipo == "bug":
            ruta = next((self.ws / "docs/bugs").glob(f"[0-9][0-9][0-9]-{slug}.md"))
            nombre = ruta.stem
        else:
            carpeta = next((self.ws / "docs/05-trabajo").glob(f"[0-9][0-9][0-9]-{slug}"))
            ruta, nombre = carpeta / "especificacion.md", carpeta.name
        texto = ruta.read_text(encoding="utf-8")
        cabecera = texto[: texto.find("---", 4) + 3]
        cabecera = cabecera.replace("aprobado: no", f"aprobado: {HOY}")
        cabecera = re.sub(
            r"^ficheros:.*$", "ficheros: [" + ", ".join(ficheros) + "]",
            cabecera, count=1, flags=re.M,
        )
        cabecera = re.sub(r"^actividad:.*$", "actividad: pedidos", cabecera,
                          count=1, flags=re.M)
        cuerpo = self.CUERPO_BUG if tipo == "bug" else self.CUERPO
        ruta.write_text(cabecera + cuerpo.format(nnn=nombre), encoding="utf-8")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(
            despachada.returncode, 0, despachada.stdout + despachada.stderr
        )
        return nombre

    def trabajar_y_fusionar(self, nombre, cambios, quitar_worktree=True,
                            estado="en_revision", recibos=True):
        worktree = self.ws / "worktrees" / nombre
        for fichero, lineas in cambios.items():
            (worktree / fichero).write_text(
                "".join(f"print({indice})\n" for indice in range(lineas)),
                encoding="utf-8",
            )
        self.git(worktree, "add", "-A")
        self.git(worktree, "commit", "-m", f"trabajo de {nombre}")
        self.git(self.repo, "merge", "--ff-only", nombre)
        if quitar_worktree:
            self.git(self.repo, "worktree", "remove", str(worktree))
        ficha, firma = self.ficha_de(nombre)
        ficha.write_text(
            re.sub(r"^estado:\s*\S+", f"estado: {estado}",
                   ficha.read_text(encoding="utf-8"), count=1, flags=re.M),
            encoding="utf-8",
        )
        self.firmar_revision(firma)
        if recibos:
            self.recibo_ejecucion(nombre, "constructor", f"c-{nombre}")
            self.recibo_ejecucion(nombre, "revisor", f"r-{nombre}")

    def borrar_rama(self, nombre):
        """Borra la rama ya fusionada: el cierre real la borra, y sin ella la medida
        tenía que salir igual de la punta que la base de despacho ya identifica."""
        self.git(self.repo, "branch", "-D", nombre)

    def olvidar_base_de_despacho(self, nombre):
        """Deja la unidad como una legacy: sin `base_sha` anotado en su petición."""
        self.reescribir_despacho(nombre, lambda metadata: metadata.pop("base_sha", None))

    def reescribir_despacho(self, nombre, mutar):
        """Aplica `mutar` sobre la metadata de despacho que la petición conserva."""
        for ruta in (self.ws / "docs/05-trabajo/peticiones").glob("*/peticion.json"):
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            tocado = False
            for proceso in datos.get("procesos", []):
                if proceso.get("ref") == nombre:
                    mutar(proceso.setdefault("metadata", {}))
                    tocado = True
            if tocado:
                ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")


# ===================================================================== R1 y R2
class RecibosDeRevisionTest(WorkspaceBase):
    """R1/R2 — la firma del revisor no vale sin recibo de ejecución propio."""

    def test_r1_cierre_sin_recibo_de_revisor_falla_y_nombra_el_comando(self):
        nombre = self.unidad_revisable("revision-sin-recibo")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("recibo", salida.lower())
        self.assertIn("ejecucion.py", salida)
        self.assertIn("--rol revisor", salida)
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_cierre_con_recibo_de_revisor_pasa_la_puerta(self):
        nombre = self.unidad_revisable("revision-con-recibo")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "sesion-revisor")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())

    def test_r2_recibo_de_revisor_con_la_sesion_del_constructor_falla(self):
        nombre = self.unidad_revisable("auto-sello")
        self.recibo_ejecucion(nombre, "constructor", "sesion-unica")
        self.recibo_ejecucion(nombre, "revisor", "sesion-unica")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("misma", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_recibo_de_revisor_fallido_no_acredita_la_revision(self):
        """Un recibo con `resultado: fail` prueba que la revisión NO salió bien."""
        nombre = self.unidad_revisable("revision-fallida")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "sesion-revisor",
                              resultado="fail", exit_code=2)

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("no acredita", salida.lower())
        self.assertIn("ejecucion.py", salida)
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_recibo_de_revisor_sin_identidad_de_sesion_no_acredita(self):
        """Sin identidad de sesión no se puede demostrar que el revisor no sea el
        constructor: la puerta de R2 se queda sin dato y el cierre no pasa."""
        nombre = self.unidad_revisable("revision-sin-sesion")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("no acredita", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r1_recibo_de_revisor_abortado_no_acredita_la_revision(self):
        """`ejecucion.py` escribe el recibo ANTES de lanzar el harness: un recibo sin
        `resultado` y con `exit_code: null` es una revisión que ni siquiera terminó."""
        nombre = self.unidad_revisable("revision-abortada")
        self.recibo_ejecucion(nombre, "constructor", "sesion-constructor")
        self.recibo_ejecucion(nombre, "revisor", "sesion-revisor",
                              resultado=None, exit_code=None)

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("no acredita", salida.lower())
        self.assertIn(SALIDA, salida)
        self.assertFalse((self.ws / "docs/05-trabajo/archivo" / nombre).exists())

    def test_r2_mismo_modelo_y_distinta_sesion_avisa_pero_cierra(self):
        nombre = self.unidad_revisable("mismo-modelo")
        self.recibo_ejecucion(nombre, "constructor", "sesion-a", modelo="opus")
        self.recibo_ejecucion(nombre, "revisor", "sesion-b", modelo="opus")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

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

    def unidad_directa(self, slug, ficheros):
        return self.unidad_con_rama(slug, ficheros, carril="directo")

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
def mensajes_de_bloqueo(caso):
    """Todo mensaje de bloqueo que una puerta del método puede imprimir.

    Vive fuera de las clases porque lo usan dos requisitos: R7 exige que cada uno nombre
    una salida y R1 (034) exige que esa salida ARRANQUE.
    """
    sys.path.insert(0, str(SCRIPTS))
    sys.path.insert(0, str(VISOR))
    caso.addCleanup(lambda: sys.path.remove(str(SCRIPTS)))
    caso.addCleanup(lambda: sys.path.remove(str(VISOR)))
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
        "R4-sin-planos": peticion.mensaje_sin_planos(),
        "R5": unidad.mensaje_directo_desbordado("001-x", 5, 400, ["app/otro.py"]),
        "R6": unidad.mensaje_ok_en_lote("001-x", "2026-08-22", 3),
        "R6-acta": unidad.mensaje_lote_incompleto("docs/acta.md", ["001-x"]),
    }


class SalidaEscritaTest(unittest.TestCase):
    """R7 — ninguna puerta nueva bloquea sin nombrar su comando o su vía de salida.

    No basta con que el mensaje diga `SALIDA:`: detrás tiene que haber algo que el
    lector pueda TECLEAR o HACER. Se exige un comando real o un carril nombrado.
    """

    ACCIONABLE = re.compile(r"(python3 \S+\.py|`[^`]+`)")

    def mensajes(self):
        return mensajes_de_bloqueo(self)

    def test_r7_cada_mensaje_de_bloqueo_nombra_su_salida(self):
        for requisito, mensaje in self.mensajes().items():
            with self.subTest(requisito=requisito):
                self.assertIn(SALIDA, mensaje)
                cola = mensaje.split(SALIDA, 1)[1]
                self.assertTrue(
                    self.ACCIONABLE.search(cola),
                    f"{requisito}: la salida no nombra nada accionable: {cola!r}",
                )


# ==================================================================== 034 · R1 y R7
# Dónde vive de verdad cada script que un mensaje de bloqueo puede nombrar. Los scripts
# se publican en `docs/00-metodo/scripts/` y el kit del visor en
# `docs/00-metodo/requisitos/` (bootstrap.py), pero en ESTE repo son `plantilla/` y
# `visor/`: la traducción se hace aquí para poder importar el módulo REAL.
CARPETAS_PUBLICADAS = {
    "docs/00-metodo/scripts": SCRIPTS,
    "docs/00-metodo/requisitos": VISOR,
}
RE_COMANDO = re.compile(r"`(python3 [^`]+)`")
RE_HUECO = re.compile(r"<[^>]+>")


class _ParserCapturado(Exception):
    """Transporta el parser real de un script sin dejar que su `main()` siga."""

    def __init__(self, parser):
        super().__init__("parser capturado")
        self.parser = parser


def parser_real(ruta_script):
    """El `argparse` REAL del script publicado en `ruta_script`, o None si no existe.

    No se reimplementa ni se aproxima: se importa el módulo tal cual se publica y se le
    deja construir su parser, interceptando la llamada a `parse_args()` que hace su
    `main()`. Comprobar un comando contra una expresión regular de comillas es lo que
    dejó pasar dos comandos rotos con 26 tests en verde (bug 034, hallazgo H).
    """
    carpeta, _, fichero = ruta_script.rpartition("/")
    raiz = CARPETAS_PUBLICADAS.get(carpeta)
    if raiz is None or not (raiz / fichero).is_file():
        return None
    sys.path.insert(0, str(raiz))
    try:
        modulo = importlib.import_module(fichero[: -len(".py")])
    finally:
        sys.path.remove(str(raiz))
    original = argparse.ArgumentParser.parse_args

    def interceptar(self, args=None, namespace=None):
        raise _ParserCapturado(self)

    argparse.ArgumentParser.parse_args = interceptar
    try:
        modulo.main()
    except _ParserCapturado as capturado:
        return capturado.parser
    finally:
        argparse.ArgumentParser.parse_args = original
    return None


def comandos_de(mensaje):
    """Los comandos que un mensaje ofrece como salida, listos para el analizador.

    Los huecos `<así>` son un ARGUMENTO que el lector rellena, así que se sustituyen por
    un token único antes de trocear: sin eso, `<modelo distinto del constructor>` se leería
    como cuatro argumentos sueltos.
    """
    cola = mensaje.split(SALIDA, 1)[1] if SALIDA in mensaje else mensaje
    return [crudo.strip() for crudo in RE_COMANDO.findall(cola)]


class ComandosDeSalidaTest(unittest.TestCase):
    """R1/R7 (034) — todo comando ofrecido como salida ARRANCA de verdad.

    La 033 comprobó la FORMA del mensaje (que hubiera algo entre comillas) en vez de su
    EFECTO, y publicó dos llaves que no abren: una invocaba `ejecucion.py` sin subcomando
    y con un `--unidad` que no existe, y la otra pedía a `peticion.py` un reencuadre de
    carril que ese comando no hace. Aquí cada comando pasa por el analizador de argumentos
    del script al que invoca.
    """

    def comandos(self):
        encontrados = []
        for requisito, mensaje in mensajes_de_bloqueo(self).items():
            for comando in comandos_de(mensaje):
                encontrados.append((requisito, comando))
        return encontrados

    def test_r1_las_puertas_ofrecen_comandos_como_salida(self):
        """Si esto se queda a cero, el resto del test no comprueba nada."""
        self.assertGreaterEqual(len(self.comandos()), 5, self.comandos())

    def test_r1_cada_comando_de_salida_apunta_a_un_script_que_existe(self):
        for requisito, comando in self.comandos():
            with self.subTest(requisito=requisito, comando=comando):
                piezas = shlex.split(RE_HUECO.sub("HUECO", comando))
                self.assertEqual(piezas[0], "python3", comando)
                self.assertIsNotNone(
                    parser_real(piezas[1]),
                    f"{requisito}: {piezas[1]} no es un script publicado del método",
                )

    def test_r1_cada_comando_de_salida_parsea_contra_su_argparse_real(self):
        for requisito, comando in self.comandos():
            with self.subTest(requisito=requisito, comando=comando):
                piezas = shlex.split(RE_HUECO.sub("HUECO", comando))
                parser = parser_real(piezas[1])
                if parser is None:
                    continue          # lo cubre el test de arriba, con su propio mensaje
                quejas = io.StringIO()
                try:
                    with contextlib.redirect_stderr(quejas):
                        parser.parse_args(piezas[2:])
                except SystemExit:
                    self.fail(
                        f"{requisito}: la salida ofrecida no arranca contra el argparse "
                        f"real de {piezas[1]}:\n      {comando}\n    "
                        + quejas.getvalue().strip().replace("\n", "\n    ")
                    )



# ===================================================== 034 · R2, R3, R4 y R5
class UnidadEnValidacionTest(WorkspaceBase):
    """R2 (034) — la salida que se ofrece FUNCIONA sobre la unidad tal como está.

    La 033 dejó ocho unidades atrapadas: `en_validacion` sin recibo de revisión válido no
    puede cerrarse, y `ejecucion.py` solo admitía `en_obra`/`en_revision`, así que tampoco
    podía producir el recibo que se le pedía. La puerta miraba hacia atrás sin comprobar
    que el camino de vuelta existiera.
    """

    def unidad_en_validacion(self, slug):
        """Unidad real, fusionada, con worktree vivo y parada en `en_validacion`."""
        nombre = self.unidad_con_rama(slug, ["app/modulo1.py"])
        self.trabajar_y_fusionar(
            nombre, {"app/modulo1.py": 10}, quitar_worktree=False,
            estado="en_validacion", recibos=False,
        )
        return nombre

    def test_r2_el_revisor_se_lanza_sobre_una_unidad_en_validacion(self):
        """`en_validacion` es un estado ejecutable PARA EL REVISOR y solo para él."""
        nombre = self.unidad_en_validacion("validacion-revisable")

        resultado = self.ejecutar(
            self.ejecucion, "lanzar", nombre, "--harness", "claude",
            "--rol", "revisor", "--prompt", "Revisa el diff contra el contrato",
            entorno=self.sin_harness(),
        )

        salida = resultado.stdout + resultado.stderr
        self.assertNotIn("solo en_obra", salida, salida)
        # Que se pare AQUÍ prueba que atravesó entera la puerta de estado: el binario del
        # harness se busca mucho después de validar la ficha.
        self.assertIn("no encuentro el ejecutable", salida, salida)

    def test_r2_el_constructor_sigue_sin_entrar_en_una_unidad_en_validacion(self):
        """La salida se abre para revisar, no para seguir construyendo lo ya entregado."""
        nombre = self.unidad_en_validacion("validacion-cerrada-al-constructor")

        resultado = self.ejecutar(
            self.ejecucion, "lanzar", nombre, "--harness", "claude",
            "--rol", "constructor", "--prompt", "Sigue construyendo",
            entorno=self.sin_harness(),
        )

        salida = resultado.stdout + resultado.stderr
        self.assertNotEqual(resultado.returncode, 0, salida)
        self.assertIn("en_validacion", salida)
        self.assertIn(SALIDA, salida)

    def test_r2_la_salida_que_ofrece_el_cierre_bloqueado_se_ejecuta_tal_cual(self):
        """De punta a punta: el cierre bloquea, y su comando literal atraviesa la puerta.

        Esto es lo que ningún test de la 033 hacía. El único hueco `<...>` que queda es el
        modelo, que depende de quién construyó y por eso no se puede escribir aquí.
        """
        nombre = self.unidad_en_validacion("validacion-salida-real")

        bloqueado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = bloqueado.stdout + bloqueado.stderr
        self.assertEqual(bloqueado.returncode, 1, salida)
        comandos = comandos_de(salida)
        self.assertTrue(comandos, salida)
        crudo = next(c for c in comandos if "ejecucion.py" in c)
        piezas = shlex.split(RE_HUECO.sub("un-modelo-cualquiera", crudo))

        ejecutado = self.ejecutar(
            self.ws / piezas[1], *piezas[2:], entorno=self.sin_harness()
        )

        rastro = ejecutado.stdout + ejecutado.stderr
        self.assertNotIn("invalid choice", rastro, rastro)
        self.assertNotIn("unrecognized arguments", rastro, rastro)
        self.assertNotIn("solo en_obra", rastro, rastro)
        self.assertIn("no encuentro el ejecutable", rastro, rastro)


class DocumentalSinWorktreeTest(WorkspaceBase):
    """R3 (034) — a quien no puede tener worktree, la puerta del recibo no le aplica.

    Una unidad documental no crea rama ni worktree por diseño (regla 2), y `ejecucion.py`
    exige worktree para lanzar nada. Exigirle el recibo era pedirle una evidencia que su
    propio carril le prohíbe producir: dos unidades reales de mastermind-agents quedaron
    así. El cierre no calla la excepción: dice por qué no aplica.
    """

    def test_r3_una_documental_cierra_sin_recibo_de_revision(self):
        nombre = self.unidad_documental("documental-sin-recibo")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())

    def test_r3_el_cierre_dice_por_que_la_puerta_no_le_aplica(self):
        nombre = self.unidad_documental("documental-motivo-escrito")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertIn("worktree", salida.lower(), salida)
        self.assertIn("documental", salida.lower(), salida)

    def test_r3_la_firma_del_revisor_le_sigue_haciendo_falta(self):
        """Que no aplique el RECIBO no relaja la revisión: sin firma no se cierra."""
        nombre = self.unidad_documental("documental-sin-firma", revisor="no")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("revisor", salida.lower())
        self.assertIn(SALIDA, salida)


class PuertasDeLosBugsTest(WorkspaceBase):
    """R4 (034) — un bug entrega código igual que una unidad, y cierra por las mismas puertas.

    Las dos puertas de la 033 se colocaron dentro de la rama de código que trata unidades
    (`if clase == "unidad"`), sin mirar qué vías de entrega quedaban fuera. Un bug cerraba
    sin recibo y sin medida de carril: la vía de entrega MÁS usada del método.
    """

    def bug_fusionado(self, slug, ficheros, cambios, carril="normal", recibos=True):
        nombre = self.unidad_con_rama(slug, ficheros, carril=carril, tipo="bug")
        self.trabajar_y_fusionar(nombre, cambios, recibos=recibos)
        return nombre

    def test_r4_un_bug_sin_recibo_de_revision_no_cierra(self):
        nombre = self.bug_fusionado(
            "bug-sin-recibo", ["app/modulo1.py"], {"app/modulo1.py": 10}, recibos=False
        )

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("recibo", salida.lower())
        self.assertIn("ejecucion.py", salida)
        self.assertIn(SALIDA, salida)

    def test_r4_un_bug_con_recibo_de_revision_pasa_la_puerta(self):
        nombre = self.bug_fusionado(
            "bug-con-recibo", ["app/modulo1.py"], {"app/modulo1.py": 10}
        )

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)

    def test_r4_un_bug_directo_desbordado_no_cierra(self):
        nombre = self.bug_fusionado(
            "bug-directo-desbordado",
            ["app/modulo1.py", "app/modulo2.py", "app/modulo3.py"],
            {f"app/modulo{indice}.py": 80 for indice in range(1, 6)},
            carril="directo",
        )

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("directo", salida.lower())
        self.assertIn(SALIDA, salida)

    def test_r4_un_bug_directo_fuera_de_sus_ficheros_no_cierra(self):
        nombre = self.bug_fusionado(
            "bug-directo-desviado", ["app/modulo1.py"], {"app/modulo6.py": 5},
            carril="directo",
        )

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("app/modulo6.py", salida)
        self.assertIn(SALIDA, salida)


class MandaElRegistroDeDespachoTest(WorkspaceBase):
    """R5 (034) — el interruptor no puede estar junto a la cerradura.

    `carril` y `ejecucion` viven en el frontmatter, y el frontmatter lo escribe el mismo
    agente al que la puerta vigila: teclear `ejecucion: expres` apagaba la puerta del
    revisor entera y `carril: normal` apagaba la medida del carril. El dato que decide SI
    la puerta aplica se lee del registro de despacho, que se escribió al despachar y que
    el constructor no puede tocar. Sin registro se avisa y se sigue: una puerta que se
    inventa el dato es peor que no tenerla.
    """

    def reescribir_cabecera(self, nombre, campo, valor):
        ficha, _ = self.ficha_de(nombre)
        texto = ficha.read_text(encoding="utf-8")
        if re.search(rf"^{campo}:", texto, flags=re.M):
            texto = re.sub(rf"^{campo}:.*$", f"{campo}: {valor}", texto, count=1, flags=re.M)
        else:
            texto = texto.replace("\n---\n", f"\n{campo}: {valor}\n---\n", 1)
        ficha.write_text(texto, encoding="utf-8")

    def test_r5_el_carril_tecleado_no_apaga_la_medida_del_directo(self):
        nombre = self.unidad_con_rama(
            "carril-tecleado",
            ["app/modulo1.py", "app/modulo2.py", "app/modulo3.py"],
            carril="directo",
        )
        self.trabajar_y_fusionar(
            nombre, {f"app/modulo{indice}.py": 80 for indice in range(1, 6)}
        )
        self.reescribir_cabecera(nombre, "carril", "normal")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("directo", salida.lower())
        self.assertIn("despacho", salida.lower())
        self.assertIn(SALIDA, salida)

    def test_r5_el_modo_tecleado_no_apaga_la_puerta_del_revisor(self):
        """`ejecucion: expres` en la ficha no convierte en exprés lo que se despachó normal."""
        nombre = self.unidad_con_rama("modo-tecleado", ["app/modulo1.py"])
        self.trabajar_y_fusionar(nombre, {"app/modulo1.py": 10}, recibos=False)
        self.reescribir_cabecera(nombre, "ejecucion", "expres")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 1, salida)
        self.assertIn("recibo", salida.lower())
        self.assertIn(SALIDA, salida)

    def test_r5_el_cierre_canta_la_discrepancia_con_el_registro(self):
        nombre = self.unidad_con_rama("discrepancia-cantada", ["app/modulo1.py"])
        self.trabajar_y_fusionar(nombre, {"app/modulo1.py": 10})
        self.reescribir_cabecera(nombre, "carril", "expres")

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertIn("despacho", salida.lower(), salida)
        self.assertIn("expres", salida.lower(), salida)

    def test_r5_sin_registro_de_despacho_avisa_y_sigue(self):
        """Unidades legadas: el registro no existe y no se puede inventar."""
        nombre = self.unidad_con_rama("despacho-legacy", ["app/modulo1.py"])
        self.trabajar_y_fusionar(nombre, {"app/modulo1.py": 10})
        self.reescribir_despacho(nombre, lambda metadata: metadata.clear())

        resultado = self.cerrar(nombre, "--ok-usuario", HOY)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("sin registro de despacho", salida.lower(), salida)
        self.assertTrue((self.ws / "docs/05-trabajo/archivo" / nombre).is_dir())

    def test_r5_el_registro_manda_tambien_para_las_documentales(self):
        """Y al revés: lo que se despachó documental cierra como documental."""
        nombre = self.unidad_documental("documental-registrada")
        self.reescribir_cabecera(nombre, "ejecucion", "normal")

        resultado = self.cerrar(nombre)

        salida = resultado.stdout + resultado.stderr
        self.assertEqual(resultado.returncode, 0, salida)
        self.assertIn("documental", salida.lower(), salida)


# =========================================================================== R8
class MarcaRetiradaTest(unittest.TestCase):
    """R8 — lo que el ADR-029 declara retirado tiene que estar retirado DEL TEXTO.

    La marca retirada se estampaba a mano y se borraba antes de imprimir: no acreditaba
    nada. Lo que hace infranqueable a una puerta es el script que la ejecuta y el test que
    lo demuestra. Las puertas siguen; la etiqueta se va.

    La marca se compone en trozos a propósito: este fichero entra en el barrido y escribirla
    entera aquí haría que la prueba se señalara a sí misma. La comprobación es la misma.
    """

    # Se busca el NOMBRE, no la forma con ángulos: el manual la publica como una chip HTML
    # (`<span class="chip c-fail">…</span>`) y en un par de sitios se cuela en prosa. La 033
    # solo miraba `<...>` y por eso dio verde con la marca viva en siete sitios (bug 034, G).
    MARCA = "HARD" + "-GATE"
    ADR = "029-una-regla-tiene-ejecutor-o-se-retira.md"

    # R6 (034): el barrido de la 033 solo miraba `.md` y `.py` de dos carpetas, así que el
    # manual publicado conservó cinco apariciones —incluida la fila del glosario que la
    # DEFINE— mientras el test daba verde. Un barrido que no cubre lo que se publica no
    # vigila nada: ahora entra el `.html` y entra la raíz del repositorio.
    SUFIJOS = {".md", ".py", ".html"}

    def ficheros_del_metodo(self):
        raices = [RAIZ / "plantilla/docs/00-metodo", RAIZ / "visor"]
        for raiz in raices:
            for ruta in sorted(raiz.rglob("*")):
                if ruta.suffix in self.SUFIJOS and ruta.is_file():
                    if ruta.name == self.ADR or "__pycache__" in ruta.parts:
                        continue
                    yield ruta
        for ruta in sorted(RAIZ.glob("*")):
            if ruta.suffix in self.SUFIJOS and ruta.is_file():
                yield ruta

    def test_r6_el_barrido_cubre_el_manual_publicado(self):
        """Si el manual no está en la lista, el test de abajo no prueba nada sobre él."""
        barridos = {ruta.name for ruta in self.ficheros_del_metodo()}
        self.assertIn("manual-ingenieria-requisitos.html", barridos)
        self.assertIn("README.md", barridos)

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
