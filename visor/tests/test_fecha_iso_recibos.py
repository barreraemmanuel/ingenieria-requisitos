"""Bug 128: los dos consumidores leen el instante emitido por el aprobador."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[2] / "plantilla/docs/00-metodo/scripts"
REF = "docs/02-flujos/planos/aprobacion.json"
PID = "P-20260928-abcd1234"


def cargar(nombre):
    with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
        spec = importlib.util.spec_from_file_location(f"recibos_128_{nombre}", SCRIPTS / f"{nombre}.py")
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo


class FechaReciboTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.peticion = cargar("peticion")

    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="recibos-128-")
        self.addCleanup(temporal.cleanup)
        self.raiz = Path(temporal.name).resolve()
        planos = self.raiz / "docs/02-flujos/planos"
        planos.mkdir(parents=True)
        (planos / "planos.json").write_text('{"actividades": []}', encoding="utf-8")
        for modulo in (self.peticion,):
            parche = patch.object(modulo, "RAIZ", self.raiz)
            parche.start()
            self.addCleanup(parche.stop)
        self.huella = self.peticion.huella_planos_actual()
        carpeta = self.raiz / "docs/05-trabajo/peticiones" / PID
        carpeta.mkdir(parents=True)
        datos = {
            "formato": 1, "id": PID, "revision": 1, "estado": "encaminada",
            "original": {"autor": "test", "resumen": "Aprobar planos", "texto": "Aprobar planos"},
            "procesos": [{"tipo": "flujos", "ref": REF, "estado": "terminal",
                          "revision": 1, "relacion": "satisface",
                          "contrato_terminal": "flujos-aprobados-v1"}],
        }
        (carpeta / "peticion.json").write_text(json.dumps(datos), encoding="utf-8")

    def comprobar(self, fecha, valida, **cambios):
        recibo = dict(estado="aprobado", huella=self.huella, por="Persona de prueba", fecha=fecha)
        recibo.update(cambios)
        (self.raiz / REF).write_text(json.dumps(recibo), encoding="utf-8")
        with self.subTest(consumidor="peticion"):
            if valida:
                self.assertEqual(self.peticion.validar_proceso_canonico("flujos", REF, True), self.raiz / REF)
            else:
                with self.assertRaises(self.peticion.ErrorPeticion):
                    self.peticion.validar_proceso_canonico("flujos", REF, True)
        with self.subTest(consumidor="lint_metodo"):
            resultado = subprocess.run(
                [sys.executable, str(SCRIPTS / "lint_metodo.py"), "--raiz", str(self.raiz)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertNotIn("Traceback", resultado.stderr)
            self.assertIn("FAIL", resultado.stdout)  # workspace mínimo, ajeno al recibo
            rechazado = "flujos terminal sin recibo aprobado" in resultado.stdout
            self.assertEqual(rechazado, not valida, resultado.stdout)

    def test_fechas_e_instantes_del_productor(self):
        for valor in ("2026-08-31", "2026-08-31T16:38:00+00:00",
                      "2026-08-31T18:38:00+02:00", "2026-08-31T16:38:00Z",
                      "2026-08-31T16:38:00.123456+00:00"):
            with self.subTest(fecha=valor):
                self.comprobar(valor, True)

    def test_fechas_invalidas_y_tipos_ajenos(self):
        for valor in ("2026-02-30", "2026-02-30T16:38:00Z", "2026-08-31T25:00:00Z",
                      "2026-08-31T16:38:00Zbasura", "texto", "", " ", None, 123, True, [], {}):
            with self.subTest(fecha=valor):
                self.comprobar(valor, False)

    def test_identidad_huella_y_estado_siguen_siendo_obligatorios(self):
        for cambios in ({"por": ""}, {"por": " "}, {"por": 123}, {"huella": "obsoleta"},
                        {"estado": "pendiente"}):
            with self.subTest(cambios=cambios):
                self.comprobar("2026-08-31T16:38:00Z", False, **cambios)


if __name__ == "__main__":
    unittest.main()
