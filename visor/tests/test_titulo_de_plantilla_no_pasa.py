"""Bug 120: una ficha con el título de plantilla («<síntoma en una frase>») pasaba el despacho.

`unidad.py nueva` copia la plantilla con `# NNN · BUG: <síntoma en una frase>` (bugs) o
`# NNN · <título en una frase>` (unidades); `despachar` solo miraba que hubiera prosa y el
lint no miraba el título: la ficha se despachaba y la web enseñaba el marcador. R1: despachar
bloquea con SALIDA; R2: el lint avisa; NO cambia: con el título escrito, todo sigue igual.
"""

import datetime
import re
import subprocess
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import test_peticion_unidad  # noqa: E402  (la clase base NO se importa por nombre: el loader la recogería)

PROSA = (
    "\n\n## Contrato\n\nEl usuario podrá completar el cambio solicitado sin alterar el "
    "comportamiento adyacente. La implementación conservará los datos existentes y mostrará "
    "un resultado verificable en la misma entrada que usa hoy. Los errores se mostrarán sin "
    "perder el trabajo y el caso límite permanecerá estable.\n\n"
    "- R1: el resultado solicitado aparece con un ejemplo real.\n"
    "- R2: el caso límite no cambia los datos existentes.\n\n"
    "## Verificación\n\n- **Nivel de test:** unitario, porque la conducta es una regla local.\n"
)


class TituloDePlantillaTest(test_peticion_unidad.PeticionUnidadTest):
    """Hereda la INFRAESTRUCTURA (workspace temporal, scripts, rastro del visor), no sus tests."""

    def ficha_con_prosa_pero_titulo_de_plantilla(self, tipo, slug):
        pid = self.capturar()
        self.evaluar(pid, ruta="directo")
        args = ["nueva", tipo, slug, "--directo", "--desde", pid]
        creada = self.ejecutar(self.unidad, *args)
        self.assertEqual(creada.returncode, 0, creada.stdout + creada.stderr)
        nombre = f"001-{slug}"
        ruta = (self.ws / "docs/bugs" / f"{nombre}.md" if tipo == "bug"
                else self.ws / "docs/05-trabajo" / nombre / "especificacion.md")
        texto = ruta.read_text(encoding="utf-8")
        marcador = "<síntoma en una frase>" if tipo == "bug" else "<título en una frase>"
        self.assertIn(marcador, texto, "la plantilla ya no trae el marcador: el test no aplica")
        texto = re.sub(r"^aprobado:.*$", f"aprobado: {datetime.date.today().isoformat()}",
                       texto, count=1, flags=re.M)
        if tipo == "bug":
            texto = re.sub(r"^ficheros: \[\]", "ficheros: [app/demo.py]", texto, count=1, flags=re.M)
            texto = re.sub(r"^actividad: .*$", "actividad: REC-1", texto, count=1, flags=re.M)
        ruta.write_text(texto + PROSA, encoding="utf-8")
        self.dejar_rastro_visor_contratos(nombre)
        return nombre, ruta, marcador

    def test_despachar_rechaza_un_bug_con_el_titulo_de_plantilla(self):
        nombre, ruta, marcador = self.ficha_con_prosa_pero_titulo_de_plantilla("bug", "sin-titulo")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        salida = despachada.stdout + despachada.stderr
        self.assertNotEqual(despachada.returncode, 0,
                            "bug 120: despachó una ficha con el título de plantilla\n" + salida)
        self.assertIn("título", salida)
        self.assertIn("SALIDA", salida)
        self.assertIn("estado: planificada", ruta.read_text(encoding="utf-8"))

    def test_con_el_titulo_escrito_despacha_igual_que_siempre(self):
        nombre, ruta, marcador = self.ficha_con_prosa_pero_titulo_de_plantilla("bug", "con-titulo")
        ruta.write_text(ruta.read_text(encoding="utf-8").replace(
            marcador, "el total del albarán no se recalcula al editarlo"), encoding="utf-8")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)

    def test_despachar_rechaza_una_unidad_con_el_titulo_de_plantilla(self):
        nombre, ruta, marcador = self.ficha_con_prosa_pero_titulo_de_plantilla("feature", "unidad-sin-titulo")
        despachada = self.ejecutar(self.unidad, "despachar", nombre)
        self.assertNotEqual(despachada.returncode, 0, despachada.stdout + despachada.stderr)
        self.assertIn("título", despachada.stdout + despachada.stderr)

    def test_el_lint_avisa_del_titulo_de_plantilla(self):
        nombre, ruta, marcador = self.ficha_con_prosa_pero_titulo_de_plantilla("bug", "lint-sin-titulo")
        import shutil
        linter = self.ws / "docs/00-metodo/scripts/lint_metodo.py"
        shutil.copy2(test_peticion_unidad.LINTER, linter)   # el workspace temporal no lo trae
        lint = self.ejecutar(linter)
        avisos = [l for l in (lint.stdout + lint.stderr).splitlines()
                  if nombre in l and "título" in l and l.strip().startswith(("WARN", "FAIL"))]
        self.assertTrue(avisos, "bug 120: el lint no avisa del título de plantilla")
        self.assertIn("SALIDA", avisos[0])


for _nombre in dir(test_peticion_unidad.PeticionUnidadTest):
    if _nombre.startswith("test_") and _nombre not in TituloDePlantillaTest.__dict__:
        setattr(TituloDePlantillaTest, _nombre, None)


if __name__ == "__main__":
    unittest.main()
