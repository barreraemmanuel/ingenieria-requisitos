"""Unidad 146 · R3 — dientes: un par de tests por ejecutor, y el par cambia de color.

Un test verde no demuestra nada si pasa igual con el mecanismo quitado. `funcion_existe()`
de `lint_juntas.py` acepta hoy un `def` VACIADO como ejecutor (medido: devuelve `True` sobre
la función con el cuerpo sustituido por «todo bien»), así que «esta regla tiene ejecutor»
significa hoy «existe un `def` con ese nombre», que es la forma en que los mecanismos se
pierden de verdad: nadie los borra, se vacían.

El par es siempre el MISMO acto ejecutado dos veces:

- `test_dientes_<ID>_bloquea` — con el mecanismo puesto, el acto se rechaza (o el aviso sale);
- `test_dientes_<ID>_abierto_pasa` — con el ejecutor abierto SOLO dentro del test, el mismo
  acto ya no se rechaza por ese motivo.

El interruptor vive en la suite y en ninguna otra parte: `unittest.mock.patch.object` sobre
el módulo importado cuando el acto corre en proceso, y —cuando el acto es un subproceso
sobre la COPIA de los scripts que el fixture monta en su `TemporaryDirectory`— el vaciado
de esa copia. Ninguna variable de entorno, ningún interruptor en producción.

Estos tests son VERDES y corren en la suite rápida; los rojos de la reforma están en
`test_transiciones_ayudante.py`.
"""
import ast
import io
import json
import contextlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[3]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
for ruta in (str(RAIZ / "visor/tests"), str(SCRIPTS)):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import canario                       # noqa: E402
import herramienta                   # noqa: E402
import lint_juntas                   # noqa: E402
import test_reglas_con_ejecutor as fixture_metodo   # noqa: E402

SALIDA = "SALIDA:"
# El nombre que `reglas.json` declara en `dientes:` para cada ejecutor medido.
PARES = {
    "R-REV-01": ("unidad.py:puerta_recibo_revisor", "test_dientes_R_REV_01"),
    "R-DIR-01": ("lint_juntas.py:junta_tope_directo", "test_dientes_R_DIR_01"),
    "R-AVI-01": ("herramienta.py:cmd_comprobar", "test_dientes_R_AVI_01"),
    "R-CAN-01": ("canario.py:salida_hook_stop", "test_dientes_R_CAN_01"),
}


def vaciar_en_la_copia(ruta, funcion, cuerpo):
    """Abre el interruptor sobre una COPIA del script: el `def` sigue ahí y no hace nada.

    Es la mutación «no-op con forma válida» —la manera real en que un mecanismo se pierde—
    y solo se aplica a los scripts que el fixture copia a su temporal, nunca a los del repo.
    """
    ruta = Path(ruta)
    fuente = ruta.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == funcion:
            lineas = fuente.splitlines(keepends=True)
            inicio = nodo.body[0].lineno - 1
            fin = max(getattr(n, "end_lineno", n.lineno) for n in nodo.body)
            sangria = " " * (nodo.col_offset + 4)
            nuevas = lineas[:inicio] + [f"{sangria}{cuerpo}\n"] + lineas[fin:]
            ruta.write_text("".join(nuevas), encoding="utf-8")
            return
    raise AssertionError(f"no encuentro `def {funcion}` en {ruta}")


# ---------------------------------------------------------------- R-REV-01
class DientesReciboDelRevisorTest(fixture_metodo.WorkspaceBase):
    """`unidad.py:puerta_recibo_revisor` — el cierre sin revisión firmada."""

    def cerrar_sin_recibo(self):
        nombre = self.unidad_revisable("dientes-recibo-revisor")
        return self.cerrar(nombre, "--ok-usuario", fixture_metodo.HOY)

    def test_dientes_R_REV_01_bloquea(self):
        hecho = self.cerrar_sin_recibo()
        salida = hecho.stdout + hecho.stderr
        self.assertEqual(hecho.returncode, 1, salida)
        self.assertIn("recibo", salida.lower())
        self.assertIn(SALIDA, salida)

    def test_dientes_R_REV_01_abierto_pasa(self):
        vaciar_en_la_copia(self.unidad, "puerta_recibo_revisor", "return [], []")
        hecho = self.cerrar_sin_recibo()
        salida = hecho.stdout + hecho.stderr
        self.assertNotIn("--rol revisor", salida,
                         "el cierre sigue reclamando el recibo con el ejecutor vaciado: "
                         "o hay otro camino que lo reclama, o el par no mide este ejecutor")


# ---------------------------------------------------------------- R-DIR-01
class DientesTopeDelDirectoTest(unittest.TestCase):
    """`lint_juntas.py:junta_tope_directo` — un carril directo de 300 líneas."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dientes-directo-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()
        ficha = self.ws / "docs/05-trabajo/300-directo-de-mas"
        ficha.mkdir(parents=True)
        (ficha / "especificacion.md").write_text(
            "---\nunidad: 300-directo-de-mas\ntipo: feature\ncarril: directo\n"
            "estado: en_obra\n---\n\n# 300\n", encoding="utf-8")
        repo = self.ws / "main"
        repo.mkdir()
        self.git(repo, "init", "-b", "main")
        self.git(repo, "config", "user.name", "Suite")
        self.git(repo, "config", "user.email", "suite@example.invalid")
        (repo / "base.py").write_text("print(0)\n", encoding="utf-8")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", "base")
        self.git(repo, "checkout", "-b", "300-directo-de-mas")
        (repo / "grande.py").write_text("".join(f"linea = {i}\n" for i in range(300)),
                                        encoding="utf-8")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-m", "300 líneas")
        self.git(repo, "checkout", "main")

    def git(self, cwd, *args):
        hecho = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
        self.assertEqual(hecho.returncode, 0, hecho.stdout + hecho.stderr)

    def acto(self):
        """El acto: pasar el guardián de juntas sobre este taller."""
        pantalla = io.StringIO()
        with contextlib.redirect_stdout(pantalla):
            lint_juntas.main(["--raiz", str(self.ws)])
        return pantalla.getvalue()

    def test_dientes_R_DIR_01_bloquea(self):
        salida = self.acto()
        self.assertIn("300-directo-de-mas", salida)
        self.assertIn("tope", salida.lower())

    def test_dientes_R_DIR_01_abierto_pasa(self):
        with mock.patch.object(lint_juntas, "junta_tope_directo", lambda raiz: []):
            salida = self.acto()
        self.assertNotIn("300-directo-de-mas", salida,
                         "el tope del directo lo denuncia algo que no es `junta_tope_directo`")


# ---------------------------------------------------------------- R-AVI-01
class DientesAvisoDelMetodoTest(unittest.TestCase):
    """`herramienta.py:cmd_comprobar` — el aviso de versión nueva del paso 0 del arranque."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dientes-aviso-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name).resolve()
        (self.ws / "docs/00-metodo").mkdir(parents=True)
        (self.ws / "docs/00-metodo/VERSION").write_text("1.0.0\n", encoding="utf-8")
        (self.ws / "docs/00-metodo/METODO.json").write_text(
            json.dumps({"origen": "https://example.invalid/metodo.git"}), encoding="utf-8")

    def acto(self):
        """El acto: el paso 0 del arranque, `herramienta.py comprobar <ws>`."""
        pantalla = io.StringIO()
        with mock.patch.object(sys, "argv",
                               ["herramienta.py", "comprobar", str(self.ws)]), \
                mock.patch.object(herramienta, "origen",
                                  lambda ws: "https://example.invalid/metodo.git"), \
                mock.patch.object(herramienta, "sha_remoto", lambda url: "f" * 40), \
                mock.patch.object(herramienta, "version_remota", lambda url: "9.9.9"), \
                mock.patch.object(herramienta, "abrir_presupuesto", lambda: None), \
                contextlib.redirect_stdout(pantalla):
            herramienta.main()
        return pantalla.getvalue()

    def test_dientes_R_AVI_01_bloquea(self):
        salida = self.acto()
        self.assertIn("9.9.9", salida, "el arranque no avisó de la versión publicada")

    def test_dientes_R_AVI_01_abierto_pasa(self):
        with mock.patch.object(herramienta, "cmd_comprobar", lambda ws, args: 0):
            salida = self.acto()
        self.assertNotIn("9.9.9", salida,
                         "alguien más imprime el aviso: el par no mide `cmd_comprobar`")


# ---------------------------------------------------------------- R-CAN-01
class DientesCanarioTest(unittest.TestCase):
    """`canario.py:salida_hook_stop` — el aviso de sesión degradada al final del turno."""

    # La forma exacta que `canario.diagnosticar` devuelve, con un síntoma de conducta
    # (comando repetido con el mismo fallo) que es lo que el hook Stop no debe callarse.
    INFORME = {"harness": "claude", "fichero": "sesion.jsonl", "modelo": "claude-fable-5",
               "tokens": 120_000, "ventana": 1_000_000, "porcentaje": 12.0, "umbral": 70,
               "veredicto": "sintomas", "candidatos": 1, "incidentes": [],
               "sintoma": {"tipo": "repeticion", "comando": "python3 correr.py",
                           "fallo": "exit 1", "veces": 3},
               "turnos": 300, "turnos_aviso": 250, "ventana_incoherente": None,
               "ventana_asumida": False, "avisar_modelo": False, "raiz": None,
               "config": "docs/00-metodo/canario.json"}

    def acto(self):
        """El acto: el hook `Stop` del final de turno."""
        pantalla = io.StringIO()
        with tempfile.TemporaryDirectory(prefix="dientes-canario-") as tmp:
            informe = dict(self.INFORME, raiz=Path(tmp))
            with mock.patch.object(canario, "diagnosticar",
                                   lambda **kwargs: informe), \
                    mock.patch.object(canario, "_entrada_del_hook", lambda: {}), \
                    contextlib.redirect_stdout(pantalla):
                canario.main(["hook-stop"])
        return json.loads(pantalla.getvalue())

    def test_dientes_R_CAN_01_bloquea(self):
        salida = self.acto()
        self.assertTrue(salida.get("systemMessage"),
                        "el hook Stop calló sobre una sesión con síntomas")
        self.assertTrue(salida.get("continue"), "el canario JAMÁS bloquea el turno")

    def test_dientes_R_CAN_01_abierto_pasa(self):
        with mock.patch.object(canario, "salida_hook_stop",
                               lambda informe, config, **kwargs: {"continue": True}):
            salida = self.acto()
        self.assertNotIn("systemMessage", salida)


# ---------------------------------------------------------------- el trinquete
class ParesDeclaradosTest(unittest.TestCase):
    """Cada ejecutor medido nombra su par en `reglas.json`, y el par existe de verdad."""

    def reglas(self):
        ruta = RAIZ / "plantilla/docs/00-metodo/reglas.json"
        return json.loads(ruta.read_text(encoding="utf-8"))["reglas"]

    def test_los_cuatro_ejecutores_medidos_declaran_su_par(self):
        declarados = {}
        for entrada in self.reglas().values():
            if entrada.get("dientes"):
                declarados[entrada.get("id")] = (entrada["ejecutor"], entrada["dientes"])
        for identificador, esperado in PARES.items():
            self.assertIn(identificador, declarados,
                          f"{identificador} no está declarado en reglas.json")
            self.assertEqual(declarados[identificador], esperado, identificador)

    def test_cada_par_declarado_existe_en_esta_suite(self):
        aqui = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        nombres = {n.name for n in ast.walk(aqui) if isinstance(n, ast.FunctionDef)}
        for ejecutor, par in PARES.values():
            for sufijo in ("_bloquea", "_abierto_pasa"):
                self.assertIn(par + sufijo, nombres, f"falta el par de {ejecutor}")


if __name__ == "__main__":
    unittest.main()
