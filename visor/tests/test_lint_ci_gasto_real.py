"""Unidad 163: los tests del constructor no gastan dinero real.

Dos capas, y aquí se prueban las dos. (R1) `roles.md` §CONSTRUCTOR escribe la regla —los
tests no llaman a servicios de pago; mock o sandbox declarado en `bias.md`; las credenciales
de pago no entran en el entorno—. (R2) `lint_ci.py` la EJECUTA con la comprobación
`gasto-real`: un fichero de test del repo de código que importa o instancia un proveedor de
la lista de `proveedores-de-pago.json` sin mock en el módulo ni sandbox declarado es FAIL con
ruta y línea y con su SALIDA; con mock, con `responses` o con el sandbox declarado, OK; un
repo sin tests, no aplica. (R3) Un proveedor que solo aparece en un comentario, en un
docstring o en la cadena de un fixture grabado no cuenta — misma familia que el `pkill` del
bug 148-R3a.

El origen no es teórico: un ayudante corrió su suite contra la API de pago del usuario y le
costó unos 25 dólares reales, y lo negó hasta que una auditoría lo demostró.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
METODO = RAIZ / "plantilla" / "docs" / "00-metodo"
LINT_CI = METODO / "scripts" / "lint_ci.py"
ROLES = METODO / "roles.md"
PROVEEDORES = METODO / "proveedores-de-pago.json"

sys.path.insert(0, str(RAIZ / "visor"))
import bootstrap  # noqa: E402


class BaseGastoReal(unittest.TestCase):
    """Un repo de juguete con tests dentro y un workspace con su bias, como en la vida real."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gasto-real-")
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "workspace"
        self.repo = self.ws / "main"
        (self.repo / "tests").mkdir(parents=True)
        (self.ws / "docs" / "01-constitucion").mkdir(parents=True)
        self.escribir_bias("# Bias\n\n- lenguaje: python\n")
        (self.repo / "README.md").write_text("# Demo\n", encoding="utf-8")
        (self.repo / "app.py").write_text("print('demo')\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text(
            "# AGENTS.md\n\n- Suite: `python3 -m unittest discover`\n", encoding="utf-8")

    def escribir_bias(self, texto):
        (self.ws / "docs" / "01-constitucion" / "bias.md").write_text(
            texto, encoding="utf-8")

    def escribir_test(self, nombre, contenido):
        ruta = self.repo / "tests" / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    def lint(self):
        return subprocess.run(
            [sys.executable, str(LINT_CI), "--repo", str(self.repo),
             "--workspace", str(self.ws)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )

    def assert_rojo(self, salida, fragmentos):
        self.assertEqual(salida.returncode, 1, salida.stdout + salida.stderr)
        self.assertIn("gasto-real", salida.stdout)
        for fragmento in fragmentos:
            self.assertIn(fragmento, salida.stdout)

    def assert_sin_gasto(self, salida):
        self.assertNotIn("gasto-real", salida.stdout, salida.stdout)


class DetectaGastoRealTest(BaseGastoReal):
    """R2: el test que llama de verdad al proveedor no pasa la puerta."""

    def test_python_sin_mock_es_fail_con_ruta_y_linea(self):
        self.escribir_test(
            "test_resumen.py",
            "import unittest\n"
            "import anthropic\n"
            "\n"
            "\n"
            "class ResumenTest(unittest.TestCase):\n"
            "    def test_resume(self):\n"
            "        cliente = anthropic.Anthropic()\n"
            "        cliente.messages.create(model='x', max_tokens=1, messages=[])\n",
        )
        salida = self.lint()
        self.assert_rojo(salida, ["tests/test_resumen.py:2", "Anthropic"])

    def test_el_mensaje_dice_como_salir(self):
        self.escribir_test(
            "test_pago.py",
            "import stripe\n\n\ndef test_cobro():\n    stripe.Charge.create()\n",
        )
        salida = self.lint()
        self.assert_rojo(salida, ["SALIDA:"])
        self.assertIn("sandbox: stripe", salida.stdout)
        self.assertIn("docs/01-constitucion/bias.md", salida.stdout)

    def test_javascript_sin_mock_es_fail(self):
        self.escribir_test(
            "pago.spec.js",
            "import Stripe from '@stripe/stripe-js';\n"
            "\n"
            "it('cobra', async () => {\n"
            "  const stripe = new Stripe(process.env.KEY);\n"
            "  await stripe.charges.create({});\n"
            "});\n",
        )
        salida = self.lint()
        self.assert_rojo(salida, ["pago.spec.js:1"])

    def test_cliente_sin_import_visible_tambien_cuenta(self):
        self.escribir_test(
            "test_cliente.py",
            "from mi_app.proveedores import OpenAI\n"
            "\n"
            "\n"
            "def test_llama():\n"
            "    OpenAI().chat.completions.create()\n",
        )
        salida = self.lint()
        self.assert_rojo(salida, ["tests/test_cliente.py:5"])

    def test_host_en_llamada_http_cuenta(self):
        self.escribir_test(
            "test_http.py",
            "import requests\n"
            "\n"
            "\n"
            "def test_pide():\n"
            "    requests.post('https://api.anthropic.com/v1/messages', json={})\n",
        )
        salida = self.lint()
        self.assert_rojo(salida, ["tests/test_http.py:5"])

    def test_el_codigo_de_salida_es_rojo_aunque_no_haya_contrato_de_ci(self):
        """El gasto real no depende del contrato de CI: sin workflows sigue bloqueando."""
        self.escribir_test("test_ia.py", "import openai\n\n\ndef test_x():\n    pass\n")
        salida = self.lint()
        self.assertEqual(salida.returncode, 1, salida.stdout)
        self.assertIn("1 FAIL", salida.stdout)


class NoFabricaRojosTest(BaseGastoReal):
    """R2 (la otra mitad) y R3: lo que sí está simulado o solo mencionado pasa."""

    def test_sin_tests_no_aplica(self):
        salida = self.lint()
        self.assertEqual(salida.returncode, 0, salida.stdout)
        self.assert_sin_gasto(salida)

    def test_con_patch_es_ok(self):
        self.escribir_test(
            "test_resumen.py",
            "import unittest\n"
            "from unittest.mock import patch\n"
            "import anthropic\n"
            "\n"
            "\n"
            "class ResumenTest(unittest.TestCase):\n"
            "    def test_resume(self):\n"
            "        with patch.object(anthropic, 'Anthropic'):\n"
            "            anthropic.Anthropic().messages.create()\n",
        )
        salida = self.lint()
        self.assertEqual(salida.returncode, 0, salida.stdout)
        self.assert_sin_gasto(salida)

    def test_con_responses_es_ok(self):
        self.escribir_test(
            "test_pago.py",
            "import responses\nimport stripe\n"
            "\n"
            "\n"
            "@responses.activate\n"
            "def test_cobro():\n"
            "    stripe.Charge.create()\n",
        )
        self.assert_sin_gasto(self.lint())

    def test_con_jest_mock_es_ok(self):
        self.escribir_test(
            "pago.spec.js",
            "import Stripe from '@stripe/stripe-js';\n"
            "jest.mock('@stripe/stripe-js');\n"
            "\n"
            "it('cobra', () => { new Stripe('k'); });\n",
        )
        self.assert_sin_gasto(self.lint())

    def test_sandbox_declarado_en_bias_es_ok(self):
        self.escribir_bias("# Bias\n\n- lenguaje: python\n- sandbox: anthropic, stripe\n")
        self.escribir_test(
            "test_resumen.py",
            "import anthropic\n\n\ndef test_resume():\n    anthropic.Anthropic()\n",
        )
        self.assert_sin_gasto(self.lint())

    def test_sandbox_de_otro_proveedor_no_exonera(self):
        self.escribir_bias("# Bias\n\n- sandbox: stripe\n")
        self.escribir_test(
            "test_resumen.py",
            "import anthropic\n\n\ndef test_resume():\n    anthropic.Anthropic()\n",
        )
        self.assert_rojo(self.lint(), ["tests/test_resumen.py:1"])

    def test_comentario_docstring_y_cassette_no_cuentan(self):
        """R3: mencionar al proveedor no es llamarlo (familia del bug 148-R3a)."""
        self.escribir_test(
            "test_prosa.py",
            '"""Este módulo NO usa anthropic.Anthropic(): documenta por qué."""\n'
            "# antes esto hacía openai.OpenAI() y costaba dinero\n"
            "CASSETTE = {'uri': 'https://api.stripe.com/v1/charges', 'body': 'Stripe('}\n"
            "\n"
            "\n"
            "def test_lee_el_cassette():\n"
            "    assert CASSETTE['uri']  # ni Anthropic( ni OpenAI( de verdad\n",
        )
        salida = self.lint()
        self.assertEqual(salida.returncode, 0, salida.stdout)
        self.assert_sin_gasto(salida)

    def test_fichero_que_no_es_de_test_no_se_mira(self):
        """La regla es sobre TESTS: el código de producción sí llama al proveedor."""
        (self.repo / "cliente.py").write_text(
            "import anthropic\n\n\ndef responder():\n    return anthropic.Anthropic()\n",
            encoding="utf-8",
        )
        self.assert_sin_gasto(self.lint())


class ContratoDeCiIntactoTest(BaseGastoReal):
    """«NO debe haber cambiado»: el resto de comprobaciones sigue igual."""

    def test_repo_vacio_sigue_siendo_ok(self):
        vacio = Path(self.tmp.name) / "vacio"
        vacio.mkdir()
        (vacio / "README.md").write_text("# vacío\n", encoding="utf-8")
        salida = subprocess.run(
            [sys.executable, str(LINT_CI), "--repo", str(vacio), "--workspace", str(self.ws)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        self.assertEqual(salida.returncode, 0, salida.stdout)
        self.assertIn("repositorio todavía vacío", salida.stdout)

    def test_deuda_de_ci_sigue_siendo_warn_sin_gasto(self):
        salida = self.lint()
        self.assertEqual(salida.returncode, 0, salida.stdout)
        self.assertIn("OK", salida.stdout)
        self.assertNotIn("FAIL falta", salida.stdout)


class ReglaEscritaTest(unittest.TestCase):
    """R1: la regla está en el encargo del constructor, no solo en el script."""

    def setUp(self):
        self.roles = ROLES.read_text(encoding="utf-8")
        self.constructor = self.roles.split("## CONSTRUCTOR", 1)[1].split("\n## ", 1)[0]

    def test_roles_dice_que_los_tests_no_llaman_a_servicios_de_pago(self):
        self.assertIn("los tests no llaman a servicios de pago", self.constructor.lower())

    def test_roles_nombra_mock_sandbox_y_bias(self):
        for pieza in ("mock", "sandbox:", "bias.md"):
            self.assertIn(pieza, self.constructor)

    def test_roles_dice_que_las_credenciales_de_pago_no_entran(self):
        self.assertIn("credenciales de pago no\n  entran", self.constructor)

    def test_roles_nombra_a_su_ejecutor(self):
        self.assertIn("lint_ci.py", self.constructor)
        self.assertIn("gasto-real", self.constructor)


class ListaDeProveedoresTest(unittest.TestCase):
    """La lista es del método, editable, y viaja a cada workspace."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("lint_ci_163", LINT_CI)
        self.lint_ci = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.lint_ci)

    def test_el_json_existe_y_trae_los_proveedores_del_contrato(self):
        ids = {p["id"] for p in self.lint_ci.proveedores_de_pago()}
        self.assertLessEqual(
            {"anthropic", "openai", "stripe", "twilio", "sendgrid", "aws-ses"}, ids)

    def test_cada_proveedor_tiene_nombre_y_alguna_senal(self):
        for proveedor in self.lint_ci.proveedores_de_pago():
            self.assertTrue(proveedor.get("nombre"), proveedor)
            self.assertTrue(
                proveedor.get("paquetes") or proveedor.get("clientes")
                or proveedor.get("hosts"), proveedor)

    def test_sin_el_json_queda_la_lista_minima(self):
        original = self.lint_ci.RUTA_PROVEEDORES
        try:
            self.lint_ci.RUTA_PROVEEDORES = Path("/no/existe/proveedores-de-pago.json")
            ids = {p["id"] for p in self.lint_ci.proveedores_de_pago()}
        finally:
            self.lint_ci.RUTA_PROVEEDORES = original
        self.assertIn("anthropic", ids)

    def test_la_lista_viaja_a_los_workspaces(self):
        self.assertTrue(PROVEEDORES.is_file())
        self.assertIn("proveedores-de-pago.json", bootstrap.ARCHIVOS_METODO)


if __name__ == "__main__":
    unittest.main()
