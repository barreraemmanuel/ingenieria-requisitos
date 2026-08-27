"""Bug 123: una ficha recién creada (todavía plantilla) se veía como contrato aprobable.

`unidad.py nueva` deja el H1 de plantilla (`<título en una frase>` / `<síntoma en una frase>`)
y marcadores `<…>`; el visor la listaba y ofrecía Aprobar igual que a un contrato escrito.
R1: el JSON la marca `sin_escribir` y el POST de aprobar/pedir-cambios responde 409; R2: en
cuanto se rellena, deja de estarlo sin reiniciar; NO cambia: los contratos escritos.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import test_visor_contratos as base  # noqa: E402

PLANTILLA_UNIDAD = """---
unidad: 013-recien-creada
tipo: feature
carril: directo
estado: planificada
aprobado: no
ficheros: []
---

# 013 · <título en una frase>

## Qué (en idioma de negocio)

<1-3 frases: qué podrá hacer el usuario cuando esto esté hecho, con el vocabulario del mapa.>

## Criterios de aceptación

- **R1** — Cuando <situación>, <resultado observable>.
"""

PLANTILLA_BUG = """---
unidad: 014-bug-recien-creado
tipo: bug
carril: directo
estado: planificada
aprobado: no
ficheros: []
---

# 014 · BUG: <síntoma en una frase>

## 1 · Reporte (el padre, con lo que cuenta el usuario)

- **Qué esperaba el usuario:** <comportamiento prometido; cita el criterio del mapa/spec si existe>
"""


class ContratoSinEscribirTest(unittest.TestCase):
    def setUp(self):
        self.workspace = base.montar_workspace()
        self.addCleanup(shutil.rmtree, self.workspace, True)
        carpeta = self.workspace / "docs" / "05-trabajo" / "013-recien-creada"
        carpeta.mkdir()
        self.ficha = carpeta / "especificacion.md"
        self.ficha.write_text(PLANTILLA_UNIDAD, encoding="utf-8")
        bugs = self.workspace / "docs" / "bugs"
        bugs.mkdir(parents=True, exist_ok=True)
        (bugs / "014-bug-recien-creado.md").write_text(PLANTILLA_BUG, encoding="utf-8")
        self.servidor = base.ServidorDePrueba(self.workspace)
        self.addCleanup(self.servidor.parar)

    def unidades(self):
        _, _, cuerpo = self.servidor.pedir("/unidades.json")
        return {u["unidad"]: u for u in json.loads(cuerpo)["unidades"]}

    def test_la_plantilla_sale_marcada_como_sin_escribir_y_un_contrato_escrito_no(self):
        unidades = self.unidades()
        self.assertTrue(unidades["013-recien-creada"].get("sin_escribir"),
                        "bug 123: una ficha plantilla se lista como contrato normal")
        self.assertTrue(unidades["014-bug-recien-creado"].get("sin_escribir"))
        self.assertFalse(unidades["010-personalidad-agente"].get("sin_escribir"))

    def test_aprobar_una_plantilla_responde_409_y_no_escribe(self):
        codigo, _, cuerpo = self.servidor.pedir("/aprobar/013-recien-creada", metodo="POST")
        self.assertEqual(codigo, 409, cuerpo)
        self.assertIn("sin escribir", json.loads(cuerpo)["error"])
        self.assertIn("aprobado: no", self.ficha.read_text(encoding="utf-8"))
        codigo, _, _ = self.servidor.pedir("/pedir-cambios/013-recien-creada", metodo="POST")
        self.assertEqual(codigo, 409)

    def test_en_cuanto_se_rellena_es_un_contrato_normal(self):
        texto = PLANTILLA_UNIDAD.replace("<título en una frase>", "el albarán recalcula el total")
        texto = texto.replace("<1-3 frases: qué podrá hacer el usuario cuando esto esté hecho, con el vocabulario del mapa.>",
                              "Al editar un albarán facturado, el total se recalcula y se guarda.")
        texto = texto.replace("Cuando <situación>, <resultado observable>.", "Cuando edito la cantidad, el total cambia.")
        self.ficha.write_text(texto, encoding="utf-8")
        self.assertFalse(self.unidades()["013-recien-creada"].get("sin_escribir"))

    def test_la_plantilla_ofrece_el_estado_sin_botones(self):
        _, _, cuerpo = self.servidor.pedir("/")
        html = cuerpo if isinstance(cuerpo, str) else cuerpo.decode("utf-8")
        self.assertIn("sin_escribir", html, "bug 123: la web no distingue una ficha sin escribir")
        self.assertIn("no lo ha escrito", html)


class JuntaConLasPlantillasRealesTest(unittest.TestCase):
    """R1: el criterio del visor es el de `unidad.titulo_de_plantilla` (bug 120) y se comprueba
    contra las plantillas REALES del método, no contra copias del test: si alguien cambia el
    H1 de `plantillas/{directo,especificacion,bug}.md`, esto se pone rojo."""

    RAIZ = Path(__file__).resolve().parents[2]
    PLANTILLAS = RAIZ / "plantilla/docs/00-metodo/plantillas"
    SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"

    def cargar_servir(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("servir_contratos", self.RAIZ / "visor_contratos/servir.py")
        modulo = importlib.util.module_from_spec(spec); spec.loader.exec_module(modulo)
        return modulo

    def plantillas_rellenas(self):
        for nombre in ("directo.md", "especificacion.md", "bug.md"):
            texto = (self.PLANTILLAS / nombre).read_text(encoding="utf-8")
            yield nombre, texto.replace("NNN", "013").replace("<slug>", "recien-creada")

    def test_las_tres_plantillas_reales_son_contratos_sin_escribir(self):
        servir = self.cargar_servir()
        for nombre, texto in self.plantillas_rellenas():
            self.assertTrue(servir.contrato_sin_escribir(texto), f"{nombre}: la plantilla real no se detecta")

    def test_el_criterio_coincide_con_el_de_unidad_py(self):
        servir = self.cargar_servir()
        if str(self.SCRIPTS) not in sys.path:
            sys.path.insert(0, str(self.SCRIPTS))
        import unidad
        for nombre, texto in self.plantillas_rellenas():
            self.assertEqual(bool(unidad.titulo_de_plantilla(texto)), servir.contrato_sin_escribir(texto), nombre)
        self.assertFalse(servir.contrato_sin_escribir(base.CONTRATO_010))
        self.assertIsNone(unidad.titulo_de_plantilla(base.CONTRATO_010))


if __name__ == "__main__":
    unittest.main()
