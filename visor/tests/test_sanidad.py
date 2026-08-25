"""Unidad 059 · el guardián de sanidad (`scripts/sanidad.py`).

Once ejes con veredicto, número y «con qué midió» (R1), salida corta con la evidencia
larga por ruta (R2), libro comparable (R3), reparación de papeles con lista cerrada y
reversible (R4), captura de lo del código como petición idempotente (R5), degradación
honesta cuando falta la herramienta o la red (R6), atraso con ejecutor (R7), hallazgos con
confianza y auto-refutación (R8), juntas texto↔código (R9), seguridad (R10) y workspace
recién creado (R11).

Los workspaces son de juguete (`tempfile`), con `main/` bajo git de verdad y con
`peticion.py` llamado como subproceso: lo que se prueba es el guardián completo, no una
función suelta.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
METODO = RAIZ / "plantilla" / "docs" / "00-metodo"
SCRIPTS = METODO / "scripts"
SANIDAD = SCRIPTS / "sanidad.py"
PLANTILLA_LIBRO = METODO / "plantillas" / "sanidad.md"
PLAYBOOK = METODO / "auditoria-sanidad.md"

EJES = (
    "pendiente",
    "deuda",
    "papeles",
    "rutas",
    "docs-en-codigo",
    "codigo-muerto",
    "tests",
    "docstrings",
    "drift",
    "decisiones",
    "dependencias",
)
HOY = datetime.date.today()
VEREDICTOS = {"OK", "WARN", "FAIL", "NO_COMPROBADO"}


def hash_arbol(*carpetas):
    """Huella del contenido de unas carpetas: nombre + bytes de cada fichero regular."""
    resumen = hashlib.sha256()
    for carpeta in carpetas:
        if not carpeta.exists():
            resumen.update(b"\0AUSENTE\0" + str(carpeta.name).encode("utf-8"))
            continue
        for ruta in sorted(p for p in carpeta.rglob("*") if p.is_file()):
            resumen.update(str(ruta.relative_to(carpeta)).encode("utf-8"))
            resumen.update(b"\0")
            resumen.update(ruta.read_bytes())
            resumen.update(b"\0")
    return resumen.hexdigest()


class WorkspaceJuguete:
    """Un workspace mínimo pero real: método copiado, `main/` con git y papeles a medida."""

    def __init__(self, raiz, con_main=True):
        self.ws = Path(raiz)
        self.scripts = self.ws / "docs/00-metodo/scripts"
        self.scripts.mkdir(parents=True)
        for nombre in ("sanidad.py", "control_plane.py", "repo_config.py",
                       "workspace_paths.py", "peticion.py"):
            origen = SCRIPTS / nombre
            if origen.exists():
                shutil.copy2(origen, self.scripts / nombre)
        plantillas = self.ws / "docs/00-metodo/plantillas"
        plantillas.mkdir(parents=True)
        if PLANTILLA_LIBRO.exists():
            shutil.copy2(PLANTILLA_LIBRO, plantillas / "sanidad.md")
        (self.ws / "repos.yaml").write_text(
            "repos:\n  - ruta_local: main/\n    rama_principal: main\n", encoding="utf-8"
        )
        (self.ws / "docs/05-trabajo/peticiones").mkdir(parents=True)
        (self.ws / "docs/05-trabajo/archivo").mkdir(parents=True)
        (self.ws / "docs/bugs").mkdir(parents=True)
        (self.ws / "docs/conocimiento").mkdir(parents=True)
        (self.ws / "docs/decisiones").mkdir(parents=True)
        (self.ws / "docs/01-constitucion").mkdir(parents=True)
        (self.ws / "docs/01-constitucion/bias.md").write_text(
            "# Bias\n\nPython y biblioteca estándar. Nada de dependencias nuevas.\n",
            encoding="utf-8",
        )
        (self.ws / "docs/02-flujos").mkdir(parents=True)
        (self.ws / "docs/02-flujos/INDICE.md").write_text(
            "# Mapa\n\n| actividad | estado |\n|---|---|\n", encoding="utf-8"
        )
        (self.ws / "worktrees").mkdir()
        self.escribir("docs/05-trabajo/ESTADO.md", "# Estado\n\nNada en vuelo.\n")
        if con_main:
            self.crear_main()

    # -- construcción -----------------------------------------------------

    def escribir(self, relativa, texto, dias=None):
        ruta = self.ws / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(texto, encoding="utf-8")
        if dias is not None:
            viejo = time.time() - dias * 86400
            os.utime(ruta, (viejo, viejo))
        return ruta

    def crear_main(self):
        repo = self.ws / "main"
        (repo / "app").mkdir(parents=True)
        (repo / "tests").mkdir(parents=True)
        (repo / "app/__init__.py").write_text("", encoding="utf-8")
        (repo / "app/motor.py").write_text(
            '"""Motor documentado."""\n\n\ndef arrancar():\n'
            '    """Arranca el motor."""\n    return 1\n',
            encoding="utf-8",
        )
        (repo / "app/cli.py").write_text(
            "import app.motor\n\n\ndef main():\n    return app.motor.arrancar()\n",
            encoding="utf-8",
        )
        (repo / "tests/test_motor.py").write_text(
            "import app.motor\n\n\ndef test_motor():\n    assert app.motor.arrancar() == 1\n",
            encoding="utf-8",
        )
        (repo / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
        (repo / "README.md").write_text("# App\n", encoding="utf-8")
        self.git_init(repo)
        return repo

    def git_init(self, repo):
        correr = lambda *o: subprocess.run(list(o), cwd=str(repo), check=True,
                                           capture_output=True)
        correr("git", "init", "-b", "main")
        correr("git", "config", "user.name", "Test")
        correr("git", "config", "user.email", "test@example.com")
        correr("git", "add", ".")
        correr("git", "commit", "-m", "base")

    def peticion(self, pid, estado="evaluando", dias=0, resumen="algo", texto="x"):
        instante = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=dias)
        ).isoformat()
        datos = {
            "formato": 1, "id": pid, "estado": estado, "revision": 1,
            "responsable": None, "creada": instante, "actualizada": instante,
            "original": {"resumen": resumen, "texto": texto, "autor": "nate"},
            "aclaraciones": [], "evaluaciones": [], "relaciones": [],
            "procesos": [], "cierres": [], "reclamos": [],
        }
        ruta = self.ws / "docs/05-trabajo/peticiones" / pid / "peticion.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, indent=2), encoding="utf-8")
        return ruta

    # -- ejecución --------------------------------------------------------

    def correr(self, *args, entorno=None):
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        if entorno:
            env.update(entorno)
        return subprocess.run(
            [sys.executable, str(self.scripts / "sanidad.py"), *args],
            cwd=str(self.ws), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
        )

    def medir_json(self, *args):
        resultado = self.correr("medir", "--json", *args)
        assert resultado.returncode == 0, resultado.stdout + resultado.stderr
        return json.loads(resultado.stdout)

    def eje(self, informe, nombre):
        for fila in informe["ejes"]:
            if fila["eje"] == nombre:
                return fila
        raise AssertionError(f"eje ausente: {nombre}")


class BaseSanidad(unittest.TestCase):
    con_main = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sanidad-")
        self.addCleanup(self.tmp.cleanup)
        self.w = WorkspaceJuguete(self.tmp.name, con_main=self.con_main)


# ---------------------------------------------------------------- R1 · R2

class MedirTest(BaseSanidad):
    """R1/R2: una orden, once ejes, salida corta y evidencia larga por ruta."""

    def setUp(self):
        super().setUp()
        for numero in (1, 2, 3):
            self.w.escribir(f"docs/05-trabajo/VALIDACION-0{numero}-08.md",
                            f"# Acta {numero}\n", dias=90)
        self.w.escribir(
            "docs/05-trabajo/ESTADO.md",
            "# Estado\n\n"
            "- ver `docs/05-trabajo/perdido-uno.md`\n"
            "- ver `docs/05-trabajo/perdido-dos.md`\n"
            "- ver `docs/conocimiento/perdido-tres.md`\n"
            "- ver `docs/02-flujos/perdido-cuatro.md`\n",
        )
        for indice in range(6):
            self.w.peticion(f"P-20260801-0000000{indice}", estado="evaluando")

    def test_ejes_lista_los_once_en_orden(self):
        resultado = self.w.correr("ejes")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(resultado.stdout.split(), list(EJES))

    def test_medir_saca_once_filas_con_veredicto_numero_y_midio_con(self):
        informe = self.w.medir_json()
        self.assertEqual([f["eje"] for f in informe["ejes"]], list(EJES))
        for fila in informe["ejes"]:
            self.assertIn(fila["veredicto"], VEREDICTOS, fila)
            self.assertIn("unidad", fila, fila)
            self.assertTrue(
                fila["midio_con"].startswith(("herramienta:", "stdlib:")),
                f"{fila['eje']} no declara con qué midió: {fila['midio_con']!r}",
            )

    def test_la_tabla_de_pantalla_trae_una_fila_por_eje(self):
        resultado = self.w.correr("medir")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        for eje in EJES:
            self.assertRegex(resultado.stdout, rf"(?m)^{re.escape(eje)}\s+\S+")

    def test_sin_detalle_la_salida_cabe_en_cuarenta_lineas(self):
        resultado = self.w.correr("medir")
        lineas = resultado.stdout.rstrip("\n").splitlines()
        self.assertLessEqual(len(lineas), 40, resultado.stdout)
        self.assertLessEqual(max(len(l) for l in lineas), 100, resultado.stdout)

    def test_los_numeros_de_actas_rutas_y_peticiones_salen_tal_cual(self):
        informe = self.w.medir_json()
        self.assertEqual(self.w.eje(informe, "papeles")["valor"], 3)
        self.assertEqual(self.w.eje(informe, "rutas")["valor"], 4)
        self.assertEqual(self.w.eje(informe, "pendiente")["valor"], 6)

    def test_el_listado_largo_va_a_runtime_y_la_tabla_lo_referencia_por_ruta(self):
        resultado = self.w.correr("medir")
        detalle = self.w.ws / ".runtime/sanidad" / HOY.isoformat() / "rutas.txt"
        self.assertTrue(detalle.is_file(), resultado.stdout)
        texto = detalle.read_text(encoding="utf-8")
        self.assertIn("perdido-uno.md", texto)
        self.assertIn(".runtime/sanidad", resultado.stdout)

    def test_json_esquema_estable_y_copia_en_runtime(self):
        informe = self.w.medir_json()
        self.assertEqual(informe["esquema"], "sanidad/v1")
        for clave in ("fecha", "raiz", "sha_main", "ejes", "comparacion"):
            self.assertIn(clave, informe)
        copia = self.w.ws / ".runtime/sanidad/ultima.json"
        self.assertTrue(copia.is_file())
        self.assertEqual(json.loads(copia.read_text(encoding="utf-8"))["esquema"],
                         "sanidad/v1")

    def test_un_solo_eje_con_la_bandera_eje(self):
        informe = json.loads(self.w.correr("medir", "--eje", "rutas", "--json").stdout)
        self.assertEqual([f["eje"] for f in informe["ejes"]], ["rutas"])

    def test_medir_sale_cero_siempre_y_estricto_falla_con_fail(self):
        self.w.escribir("docs/05-trabajo/ESTADO.md", "# Estado\n" + "x\n" * 200)
        self.assertEqual(self.w.correr("medir").returncode, 0)
        (self.w.ws / "worktrees" / "999-fantasma").mkdir()
        self.assertEqual(self.w.correr("medir", "--estricto").returncode, 1)

    def test_nunca_imprime_el_contenido_de_un_fichero(self):
        self.w.escribir("docs/conocimiento/nota.md",
                        "# Nota\n\nSECRETO-DE-CONTENIDO en prosa.\n")
        resultado = self.w.correr("medir", "--detalle")
        self.assertNotIn("SECRETO-DE-CONTENIDO", resultado.stdout)


# --------------------------------------------------------------------- R3

class LibroTest(BaseSanidad):
    """R3: el libro de sanidad, la comparación contra su última fila y el tope de 100."""

    @property
    def libro(self):
        return self.w.ws / "docs/05-trabajo/SANIDAD.md"

    def test_anotar_crea_el_libro_desde_la_plantilla_y_añade_una_fila(self):
        self.assertFalse(self.libro.exists())
        resultado = self.w.correr("medir", "--anotar")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        texto = self.libro.read_text(encoding="utf-8")
        self.assertIn(HOY.isoformat(), texto)
        filas = [l for l in texto.splitlines() if l.startswith(f"| {HOY.isoformat()}")]
        self.assertEqual(len(filas), 1, texto)

    def test_la_comparacion_dice_mejor_y_empeoro_contra_la_ultima_fila(self):
        self.w.escribir("docs/05-trabajo/VALIDACION-01-08.md", "# a\n", dias=90)
        self.w.escribir("docs/05-trabajo/VALIDACION-02-08.md", "# b\n", dias=90)
        self.w.correr("medir", "--anotar")
        (self.w.ws / "docs/05-trabajo/VALIDACION-02-08.md").unlink()
        informe = self.w.medir_json()
        self.assertEqual(self.w.eje(informe, "papeles")["comparacion"], "mejor 2→1")
        self.w.escribir("docs/05-trabajo/VALIDACION-03-08.md", "# c\n", dias=90)
        self.w.escribir("docs/05-trabajo/VALIDACION-04-08.md", "# d\n", dias=90)
        self.w.escribir("docs/05-trabajo/VALIDACION-05-08.md", "# e\n", dias=90)
        informe = self.w.medir_json()
        self.assertEqual(self.w.eje(informe, "papeles")["comparacion"], "EMPEORÓ 2→4")

    def test_sin_fila_anterior_no_se_inventa_comparacion(self):
        informe = self.w.medir_json()
        self.assertEqual(self.w.eje(informe, "papeles")["comparacion"], "primera pasada")

    def test_el_libro_nunca_pasa_de_cien_lineas_y_compacta_por_mes(self):
        cabecera = PLANTILLA_LIBRO.read_text(encoding="utf-8")
        columnas = " | ".join(["0"] * (len(EJES) + 3))
        viejas = "\n".join(
            f"| 2026-{mes:02d}-{dia:02d} | {columnas} |"
            for mes in (1, 2, 3, 4) for dia in range(1, 29)
        )
        self.libro.write_text(cabecera.rstrip("\n") + "\n" + viejas + "\n",
                              encoding="utf-8")
        self.w.correr("medir", "--anotar")
        texto = self.libro.read_text(encoding="utf-8")
        self.assertLessEqual(len(texto.splitlines()), 100, texto)
        self.assertIn("2026-01 ·", texto)
        self.assertIn(HOY.isoformat(), texto)

    def test_estricto_falla_si_un_eje_empeoro_aunque_no_haya_fail(self):
        self.w.correr("medir", "--anotar")
        self.w.escribir("docs/05-trabajo/VALIDACION-09-08.md", "# tarde\n", dias=90)
        self.assertEqual(self.w.correr("medir", "--estricto").returncode, 1)


# --------------------------------------------------------------------- R4

class RepararTest(BaseSanidad):
    """R4: lista cerrada, listada, reversible y ciega a todo lo que no son papeles."""

    def setUp(self):
        super().setUp()
        self.w.escribir("docs/05-trabajo/VALIDACION-18-08.md", "# Acta vieja\n", dias=90)
        self.w.escribir("docs/05-trabajo/RETOMADA-22-08.md", "# Otra acta\n", dias=90)
        self.w.escribir("docs/05-trabajo/archivo/actas/movido.md", "# Ya archivado\n")
        self.w.escribir("docs/05-trabajo/archivo/actas/ambiguo.md", "# Uno\n")
        self.w.escribir("docs/conocimiento/ambiguo.md", "# Dos\n")
        self.w.escribir(
            "docs/05-trabajo/ESTADO.md",
            "# Estado\n\n"
            "- acta: `docs/05-trabajo/VALIDACION-18-08.md`\n"
            "- rota con destino único: `docs/05-trabajo/movido.md`\n"
            "- rota ambigua: `docs/05-trabajo/ambiguo.md`\n",
        )
        (self.w.ws / "docs/.DS_Store").write_bytes(b"basura")
        (self.w.ws / "docs/02-flujos/planos").mkdir(parents=True, exist_ok=True)
        self.w.escribir("docs/02-flujos/planos/actividades/x/planos.json", "{}\n")
        self.protegidas = (
            self.w.ws / "main",
            self.w.ws / "worktrees",
            self.w.ws / "docs/02-flujos/planos",
            self.w.ws / "docs/00-metodo",
            self.w.ws / "docs/05-trabajo/peticiones",
            self.w.ws / "docs/bugs",
        )

    def test_simular_lista_y_no_escribe_nada(self):
        antes = hash_arbol(self.w.ws / "docs", self.w.ws / "main")
        resultado = self.w.correr("reparar", "--simular")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("SIMULADO", resultado.stdout)
        self.assertNotIn("REPARADO", resultado.stdout)
        self.assertEqual(hash_arbol(self.w.ws / "docs", self.w.ws / "main"), antes)

    def test_archiva_las_actas_y_reescribe_las_referencias(self):
        resultado = self.w.correr("reparar")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("REPARADO", resultado.stdout)
        destino = self.w.ws / "docs/05-trabajo/archivo/actas/VALIDACION-18-08.md"
        self.assertTrue(destino.is_file(), resultado.stdout)
        self.assertFalse((self.w.ws / "docs/05-trabajo/VALIDACION-18-08.md").exists())
        estado = (self.w.ws / "docs/05-trabajo/ESTADO.md").read_text(encoding="utf-8")
        self.assertIn("docs/05-trabajo/archivo/actas/VALIDACION-18-08.md", estado)

    def test_reescribe_la_ruta_rota_con_destino_unico_y_deja_la_ambigua(self):
        self.w.correr("reparar")
        estado = (self.w.ws / "docs/05-trabajo/ESTADO.md").read_text(encoding="utf-8")
        self.assertIn("docs/05-trabajo/archivo/actas/movido.md", estado)
        self.assertIn("`docs/05-trabajo/ambiguo.md`", estado)

    def test_la_ruta_ambigua_queda_como_hallazgo_con_sus_candidatos(self):
        informe = self.w.medir_json()
        detalle = (self.w.ws / ".runtime/sanidad" / HOY.isoformat() / "rutas.txt")
        texto = detalle.read_text(encoding="utf-8")
        self.assertIn("docs/05-trabajo/ambiguo.md", texto)
        self.assertIn("docs/conocimiento/ambiguo.md", texto)
        self.assertGreaterEqual(self.w.eje(informe, "rutas")["valor"], 2)

    def test_borra_los_generados_que_no_deberian_estar_en_docs(self):
        self.w.correr("reparar")
        self.assertFalse((self.w.ws / "docs/.DS_Store").exists())

    def test_jamas_toca_main_worktrees_planos_metodo_peticiones_ni_bugs(self):
        self.w.peticion("P-20260801-aaaaaaaa")
        self.w.escribir("docs/bugs/013-algo.md", "# Bug\n\n`docs/05-trabajo/movido.md`\n")
        antes = hash_arbol(*self.protegidas)
        self.w.correr("reparar")
        self.assertEqual(hash_arbol(*self.protegidas), antes)

    def test_reparar_no_ejecuta_git(self):
        cabeza = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(self.w.ws / "main"),
            capture_output=True, text=True, check=True).stdout
        self.w.correr("reparar")
        despues = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(self.w.ws / "main"),
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(despues, "")
        self.assertEqual(subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(self.w.ws / "main"),
            capture_output=True, text=True, check=True).stdout, cabeza)

    def test_solo_acota_la_reparacion_a_un_eje(self):
        self.w.correr("reparar", "--solo", "rutas")
        self.assertTrue((self.w.ws / "docs/05-trabajo/VALIDACION-18-08.md").is_file())
        estado = (self.w.ws / "docs/05-trabajo/ESTADO.md").read_text(encoding="utf-8")
        self.assertIn("docs/05-trabajo/archivo/actas/movido.md", estado)


# --------------------------------------------------------------------- R5

class CapturarTest(BaseSanidad):
    """R5: una petición por eje del código, por `peticion.py`, e idempotente."""

    def setUp(self):
        super().setUp()
        repo = self.w.ws / "main"
        (repo / "app/huerfano.py").write_text(
            '"""Nadie me importa."""\n\n\ndef nadie():\n    """Nada."""\n    return 0\n',
            encoding="utf-8",
        )

    def peticiones(self):
        salidas = []
        for ruta in sorted(
            (self.w.ws / "docs/05-trabajo/peticiones").glob("P-*/peticion.json")
        ):
            salidas.append(json.loads(ruta.read_text(encoding="utf-8")))
        return salidas

    def test_captura_una_peticion_por_eje_con_autor_sanidad_y_evidencia(self):
        resultado = self.w.correr("capturar", "--eje", "codigo-muerto")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        creadas = self.peticiones()
        self.assertEqual(len(creadas), 1, creadas)
        datos = creadas[0]
        self.assertEqual(datos["original"]["autor"], "sanidad")
        self.assertIn(f"Sanidad {HOY.isoformat()} · codigo-muerto",
                      datos["original"]["resumen"])
        self.assertIn("sanidad/codigo-muerto", datos["original"]["texto"])
        self.assertIn("app/huerfano.py", datos["original"]["texto"])

    def test_repetirlo_aclara_la_misma_peticion_en_vez_de_duplicar(self):
        self.w.correr("capturar", "--eje", "codigo-muerto")
        (self.w.ws / "main/app/otro_muerto.py").write_text(
            '"""Otro."""\n\n\ndef nada():\n    """x."""\n    return 0\n', encoding="utf-8"
        )
        resultado = self.w.correr("capturar", "--eje", "codigo-muerto")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        creadas = self.peticiones()
        self.assertEqual(len(creadas), 1, [d["id"] for d in creadas])
        self.assertTrue(creadas[0]["aclaraciones"], creadas[0])

    def test_capturar_no_crea_unidades_ni_despacha(self):
        self.w.correr("capturar")
        self.assertEqual(
            sorted(p.name for p in (self.w.ws / "docs/05-trabajo").iterdir()),
            sorted(["ESTADO.md", "peticiones", "archivo"]),
        )

    def test_incluir_media_suma_los_hallazgos_de_confianza_media(self):
        (self.w.ws / "main/scripts").mkdir(parents=True, exist_ok=True)
        (self.w.ws / "main/app/citado_en_sh.py").write_text(
            '"""Se llama desde un .sh."""\n\n\ndef corre():\n    """x."""\n    return 0\n',
            encoding="utf-8",
        )
        (self.w.ws / "main/scripts/arranque.sh").write_text(
            "#!/bin/sh\npython3 app/citado_en_sh.py\n", encoding="utf-8"
        )
        self.w.correr("capturar", "--eje", "codigo-muerto")
        alta = self.peticiones()[0]["original"]["texto"]
        self.assertNotIn("citado_en_sh.py", alta)
        for ruta in (self.w.ws / "docs/05-trabajo/peticiones").glob("P-*"):
            shutil.rmtree(ruta)
        self.w.correr("capturar", "--eje", "codigo-muerto", "--incluir-media")
        con_media = self.peticiones()[0]["original"]["texto"]
        self.assertIn("citado_en_sh.py", con_media)


# --------------------------------------------------------------------- R6

class DegradacionTest(BaseSanidad):
    """R6: lo no medido no está bien; se dice con qué se midió y qué falta."""

    def test_sin_herramientas_en_el_path_mide_por_aproximacion_y_lo_dice(self):
        informe = json.loads(
            self.w.correr("medir", "--json", entorno={"PATH": ""}).stdout
        )
        for nombre in ("codigo-muerto", "tests", "docstrings"):
            fila = self.w.eje(informe, nombre)
            self.assertTrue(fila["midio_con"].startswith("stdlib:"),
                            f"{nombre}: {fila['midio_con']!r}")
            self.assertIn("aproximación", fila["midio_con"])

    def test_dependencias_sin_red_es_no_comprobado_con_salida_y_nunca_ok(self):
        fila = self.w.eje(self.w.medir_json(), "dependencias")
        self.assertNotEqual(fila["veredicto"], "OK")
        self.assertEqual(fila["veredicto"], "NO_COMPROBADO")
        self.assertIn("SALIDA:", fila["motivo"])

    def test_sin_suite_ni_modulos_el_eje_tests_es_no_comprobado(self):
        shutil.rmtree(self.w.ws / "main/app")
        shutil.rmtree(self.w.ws / "main/tests")
        fila = self.w.eje(self.w.medir_json(), "tests")
        self.assertEqual(fila["veredicto"], "NO_COMPROBADO")
        self.assertIn("SALIDA:", fila["motivo"])


# --------------------------------------------------------------------- R7

class AtrasoTest(BaseSanidad):
    """R7: la cadencia la cuenta un ejecutor, no la memoria."""

    SALIDA = "python3 docs/00-metodo/scripts/sanidad.py medir --anotar"

    def libro_con_fecha(self, fecha):
        cabecera = PLANTILLA_LIBRO.read_text(encoding="utf-8").rstrip("\n")
        columnas = " | ".join(["0"] * (len(EJES) + 3))
        (self.w.ws / "docs/05-trabajo/SANIDAD.md").write_text(
            f"{cabecera}\n| {fecha.isoformat()} | {columnas} |\n", encoding="utf-8"
        )

    def unidad_archivada(self, nombre, fecha):
        self.w.escribir(
            f"docs/05-trabajo/archivo/{nombre}/especificacion.md",
            f"---\nunidad: {nombre}\ntipo: feature\nestado: archivada\n"
            f"actualizado: {fecha.isoformat()}\n---\n\n# {nombre}\n",
        )

    def test_sin_libro_avisa_de_que_nunca_se_ha_pasado_sanidad(self):
        resultado = self.w.correr("atraso")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("WARN nunca se ha pasado sanidad", resultado.stdout)
        self.assertIn(self.SALIDA, resultado.stdout)

    def test_al_dia_con_pocos_cierres_y_pocos_dias(self):
        self.libro_con_fecha(HOY - datetime.timedelta(days=3))
        for indice in range(2):
            self.unidad_archivada(f"00{indice}-x", HOY - datetime.timedelta(days=1))
        resultado = self.w.correr("atraso")
        self.assertEqual(resultado.returncode, 0)
        self.assertIn("OK sanidad al día (2 cierres, 3 días)", resultado.stdout)

    def test_seis_cierres_desde_la_ultima_pasada_avisan_con_el_comando(self):
        fecha = HOY - datetime.timedelta(days=4)
        self.libro_con_fecha(fecha)
        for indice in range(6):
            self.unidad_archivada(f"01{indice}-x", HOY - datetime.timedelta(days=1))
        resultado = self.w.correr("atraso")
        self.assertEqual(resultado.returncode, 0)
        self.assertIn("WARN sanidad atrasada: 6 cierres / 4 días", resultado.stdout)
        self.assertIn(fecha.isoformat(), resultado.stdout)
        self.assertIn(self.SALIDA, resultado.stdout)

    def test_mas_de_catorce_dias_tambien_avisa_y_estricto_sale_uno(self):
        self.libro_con_fecha(HOY - datetime.timedelta(days=20))
        self.assertIn("WARN sanidad atrasada", self.w.correr("atraso").stdout)
        self.assertEqual(self.w.correr("atraso", "--estricto").returncode, 1)

    def test_los_bugs_mergeados_posteriores_cuentan_como_cierre(self):
        self.libro_con_fecha(HOY - datetime.timedelta(days=2))
        self.w.escribir(
            "docs/bugs/013-algo.md",
            f"---\nbug: 013-algo\nestado: mergeada\n"
            f"actualizado: {HOY.isoformat()}\n---\n\n# Bug\n",
        )
        self.assertIn("(1 cierres, 2 días)", self.w.correr("atraso").stdout)


# --------------------------------------------------------------------- R8

class FalsosPositivosTest(BaseSanidad):
    """R8: precisión antes que volumen. Ninguno de estos sale con confianza alta."""

    def hallazgos_altos(self, informe, eje):
        return [h for h in self.w.eje(informe, eje)["hallazgos"]
                if h["confianza"] == "alta"]

    def test_un_modulo_citado_en_un_sh_no_es_codigo_muerto_de_confianza_alta(self):
        (self.w.ws / "main/scripts").mkdir(parents=True, exist_ok=True)
        (self.w.ws / "main/app/tarea.py").write_text(
            '"""Tarea."""\n\n\ndef corre():\n    """x."""\n    return 0\n', encoding="utf-8"
        )
        (self.w.ws / "main/scripts/cron.sh").write_text(
            "#!/bin/sh\npython3 app/tarea.py\n", encoding="utf-8"
        )
        informe = self.w.medir_json()
        altos = self.hallazgos_altos(informe, "codigo-muerto")
        self.assertFalse([h for h in altos if "tarea.py" in h["ruta"]], altos)
        todos = self.w.eje(informe, "codigo-muerto")["hallazgos"]
        self.assertTrue([h for h in todos
                         if "tarea.py" in h["ruta"] and h["confianza"] == "media"], todos)

    def test_main_setup_tests_metodos_magicos_y_decoradas_no_son_hallazgo(self):
        (self.w.ws / "main/app/varias.py").write_text(
            '"""Varias."""\n'
            "import functools\n\n\n"
            'def main():\n    """x."""\n    return 0\n\n\n'
            'def test_algo():\n    """x."""\n    return 0\n\n\n'
            "class C:\n"
            '    """c."""\n'
            '    def __init__(self):\n        """x."""\n        self.a = 1\n\n'
            '    def setUp(self):\n        """x."""\n        return 1\n\n'
            "    @functools.lru_cache\n"
            '    def cacheada(self):\n        """x."""\n        return 2\n',
            encoding="utf-8",
        )
        informe = self.w.medir_json()
        textos = " ".join(h["texto"] + h["ruta"]
                          for h in self.w.eje(informe, "codigo-muerto")["hallazgos"])
        for nombre in ("main", "test_algo", "__init__", "setUp", "cacheada"):
            self.assertNotIn(f"función {nombre}", textos)

    def test_los_md_de_lista_blanca_no_son_docs_en_el_codigo(self):
        for nombre in ("README.md", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md",
                       "LICENSE.md", "CONTRIBUTING.md"):
            (self.w.ws / "main" / nombre).write_text("# x\n", encoding="utf-8")
        (self.w.ws / "main/docs").mkdir(parents=True, exist_ok=True)
        (self.w.ws / "main/docs/guia.md").write_text("# guía\n", encoding="utf-8")
        fila = self.w.eje(self.w.medir_json(), "docs-en-codigo")
        self.assertEqual(fila["valor"], 0, fila["hallazgos"])

    def test_un_todo_recien_escrito_no_es_deuda(self):
        repo = self.w.ws / "main"
        (repo / "app/reciente.py").write_text(
            '"""Reciente."""\n\n\ndef f():\n    """x."""\n    # TODO: mañana\n    return 0\n',
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "hoy"], cwd=str(repo), check=True,
                       capture_output=True)
        informe = self.w.medir_json()
        altos = self.hallazgos_altos(informe, "deuda")
        self.assertFalse([h for h in altos if "reciente.py" in h["ruta"]], altos)

    def test_una_dependencia_suelta_solo_en_dev_es_de_confianza_media(self):
        (self.w.ws / "main/requirements-dev.txt").write_text("pytest\n", encoding="utf-8")
        informe = self.w.medir_json()
        sueltas = [h for h in self.w.eje(informe, "dependencias")["hallazgos"]
                   if "pytest" in h["texto"]]
        self.assertTrue(sueltas, self.w.eje(informe, "dependencias"))
        self.assertEqual(sueltas[0]["confianza"], "media")


# --------------------------------------------------------------------- R9

class JuntasTest(unittest.TestCase):
    """R9: los once ejes del script, del playbook y del libro son los mismos."""

    def test_ejes_playbook_y_plantilla_del_libro_coinciden(self):
        salida = subprocess.run(
            [sys.executable, str(SANIDAD), "ejes"], cwd=str(RAIZ),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(salida.returncode, 0, salida.stderr)
        del_script = salida.stdout.split()
        self.assertEqual(del_script, list(EJES))

        playbook = PLAYBOOK.read_text(encoding="utf-8")
        del_playbook = re.findall(r"(?m)^### \d+ · ([a-z-]+)$", playbook)
        self.assertEqual(del_playbook, del_script, "playbook desincronizado")

        plantilla = PLANTILLA_LIBRO.read_text(encoding="utf-8")
        cabecera = next(l for l in plantilla.splitlines() if l.startswith("| fecha "))
        columnas = [c.strip() for c in cabecera.strip("|").split("|")]
        self.assertEqual(columnas[1:1 + len(EJES)], del_script, cabecera)

    def test_el_playbook_da_comando_umbral_y_refutacion_por_eje(self):
        playbook = PLAYBOOK.read_text(encoding="utf-8")
        bloques = re.split(r"(?m)^### \d+ · ", playbook)[1:]
        self.assertEqual(len(bloques), len(EJES))
        for bloque in bloques:
            nombre = bloque.splitlines()[0]
            for etiqueta in ("**Comando:**", "**Umbral:**", "**Auto-repara:**",
                             "**Cómo se refuta:**", "**Qué NO ve:**"):
                self.assertIn(etiqueta, bloque, f"eje {nombre} sin {etiqueta}")


class DoctrinaTest(unittest.TestCase):
    """R9: el rol, el ADR, el runbook y las tablas del método hablan del guardián."""

    def test_roles_gana_la_seccion_sanidad(self):
        texto = (METODO / "roles.md").read_text(encoding="utf-8")
        self.assertIn("## SANIDAD (mide, repara papeles, nunca código)", texto)
        self.assertIn("scripts/sanidad.py", texto)

    def test_el_adr_030_existe_y_esta_aceptado(self):
        adr = METODO / "decisiones/031-sanidad-repara-papeles-nunca-codigo.md"
        texto = adr.read_text(encoding="utf-8")
        self.assertIn("**Estado:** aceptada", texto)
        self.assertIn("ADR-031", texto)

    def test_detectores_lista_al_guardian_con_lo_que_no_ve(self):
        texto = (METODO / "detectores.md").read_text(encoding="utf-8")
        self.assertIn("`sanidad.py`", texto)
        self.assertIn("reflexión", texto)

    def test_comunicacion_traduce_sanidad(self):
        texto = (METODO / "comunicacion.md").read_text(encoding="utf-8")
        self.assertIn("revisión de limpieza del proyecto", texto)

    def test_el_readme_del_metodo_lista_la_pieza(self):
        texto = (METODO / "README.md").read_text(encoding="utf-8")
        self.assertIn("scripts/sanidad.py", texto)

    def test_el_runbook_describe_la_pasada_completa(self):
        texto = (METODO / "runbooks/sanidad.md").read_text(encoding="utf-8")
        for paso in ("medir", "reparar", "capturar", "atraso"):
            self.assertIn(f"sanidad.py {paso}", texto)


# -------------------------------------------------------------------- R10

class SeguridadTest(BaseSanidad):
    """R10: `.private/` no se lee, la red no se toca sola y `.runtime/` va redactado."""

    def test_nunca_mira_dentro_de_private(self):
        privado = self.w.ws / ".private"
        privado.mkdir()
        (privado / "secreto.txt").write_text("CLAVE-PRIVADA-XYZ\n", encoding="utf-8")
        (privado / "notas.md").write_text(
            "`docs/05-trabajo/ruta-que-no-existe.md`\n", encoding="utf-8"
        )
        resultado = self.w.correr("medir", "--detalle")
        self.assertNotIn("CLAVE-PRIVADA-XYZ", resultado.stdout)
        self.assertNotIn(".private", resultado.stdout)
        volcado = "\n".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p in (self.w.ws / ".runtime").rglob("*") if p.is_file()
        )
        self.assertNotIn("CLAVE-PRIVADA-XYZ", volcado)
        self.assertNotIn("ruta-que-no-existe.md", volcado)

    def test_lo_que_va_a_runtime_sale_redactado(self):
        repo = self.w.ws / "main"
        (repo / "app/config.py").write_text(
            '"""Config."""\n\n\ndef f():\n'
            '    """x."""\n'
            '    # TODO: rotar password="hunter2-en-claro"\n'
            "    return 0\n",
            encoding="utf-8",
        )
        for orden in (["git", "add", "."], ["git", "commit", "-m", "viejo",
                                            "--date=2020-01-01T00:00:00"]):
            subprocess.run(orden, cwd=str(repo), check=True, capture_output=True,
                           env=dict(os.environ, GIT_COMMITTER_DATE="2020-01-01T00:00:00"))
        self.w.correr("medir", "--detalle")
        detalle = self.w.ws / ".runtime/sanidad" / HOY.isoformat() / "deuda.txt"
        texto = detalle.read_text(encoding="utf-8")
        self.assertIn("config.py", texto)
        self.assertNotIn("hunter2-en-claro", texto)

    def test_ultima_json_tambien_sale_redactado(self):
        """R10 (ronda 2): `ultima.json` va a `.runtime/`, así que va redactado.

        `escribir_detalle` redactaba los `.txt` y `ultima.json` se volcaba en crudo:
        el secreto salía en claro por el JSON aunque el detalle estuviera limpio."""
        repo = self.w.ws / "main"
        (repo / "app/config.py").write_text(
            '"""Config."""\n\n\ndef f():\n'
            '    """x."""\n'
            '    # TODO: rotar password="hunter2-en-claro"\n'
            "    return 0\n",
            encoding="utf-8",
        )
        for orden in (["git", "add", "."], ["git", "commit", "-m", "viejo",
                                            "--date=2020-01-01T00:00:00"]):
            subprocess.run(orden, cwd=str(repo), check=True, capture_output=True,
                           env=dict(os.environ, GIT_COMMITTER_DATE="2020-01-01T00:00:00"))
        resultado = self.w.correr("medir", "--eje", "deuda", "--json")
        ultima = self.w.ws / ".runtime/sanidad/ultima.json"
        crudo = ultima.read_text(encoding="utf-8")
        self.assertIn("config.py", crudo)
        self.assertNotIn("hunter2-en-claro", crudo)
        self.assertNotIn("hunter2-en-claro", resultado.stdout)
        informe = json.loads(crudo)  # redactar no puede romper el JSON
        textos = " ".join(h["texto"] for f in informe["ejes"] for h in f["hallazgos"])
        self.assertIn("password=***", textos)

    def test_no_sale_a_la_red_sin_la_bandera(self):
        fila = self.w.eje(self.w.medir_json(), "dependencias")
        self.assertNotIn("herramienta:pip-audit", fila["midio_con"])
        self.assertEqual(fila["veredicto"], "NO_COMPROBADO")


# -------------------------------------------------------------------- R11

class WorkspaceVacioTest(BaseSanidad):
    """R11: el primer día de cada alumno, sin `main/`, sin unidades y sin libro."""

    con_main = False

    def test_los_once_ejes_salen_sin_una_sola_traza_de_python(self):
        resultado = self.w.correr("medir")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertNotIn("Traceback", resultado.stdout + resultado.stderr)
        informe = self.w.medir_json()
        self.assertEqual(len(informe["ejes"]), len(EJES))
        for fila in informe["ejes"]:
            self.assertIn(fila["veredicto"], VEREDICTOS)

    def test_reparar_no_hace_nada_y_lo_dice(self):
        resultado = self.w.correr("reparar")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("nada que reparar", resultado.stdout)
        self.assertNotIn("Traceback", resultado.stderr)

    def test_atraso_avisa_de_que_nunca_se_ha_pasado(self):
        resultado = self.w.correr("atraso")
        self.assertEqual(resultado.returncode, 0)
        self.assertIn("WARN nunca se ha pasado sanidad", resultado.stdout)

    def test_capturar_sin_codigo_no_crea_peticiones(self):
        resultado = self.w.correr("capturar")
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertFalse(
            list((self.w.ws / "docs/05-trabajo/peticiones").glob("P-*")), resultado.stdout
        )


if __name__ == "__main__":
    unittest.main()
