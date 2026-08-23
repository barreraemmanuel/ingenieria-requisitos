import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
GENERADOR = RAIZ / "visor" / "generar_spec.py"


def plano_con_e2e():
    return {
        "version": 2,
        "proyecto": "pedidos",
        "titulo": "Pedidos seguros",
        "secreto": "secreto-raiz-no-proyectable",
        "actores": [
            {
                "nombre": "María",
                "rol": "operadora",
                "organizacion": "Almacén Norte",
                "grupos": ["pedidos", "turno de mañana"],
                "estado": "activa",
                "email_acceso": "maria-acceso@example.test",
                "contraseña": "clave-hostil-no-proyectable",
            }
        ],
        "recorridos": [
            {
                "id": "REC-1",
                "nombre": "Editar un pedido propio",
                "estado": "pendiente",
                "requisitos": [
                    {
                        "id": "R-1",
                        "texto": "Cuando María edite su pedido, el sistema deberá guardar el cambio.",
                        "regla": "G-1",
                    },
                    {
                        "id": "R-2",
                        "texto": "Si María intenta editar un pedido ajeno, entonces el sistema deberá denegarlo.",
                    },
                ],
                "criterios": [
                    {
                        "id": "C-1",
                        "tipo": "feliz",
                        "dado": "un pedido propio de María",
                        "cuando": "María cambia la fecha",
                        "entonces": "el pedido conserva la nueva fecha",
                        "cubre": "R-1",
                    },
                    {
                        "id": "C-2",
                        "tipo": "denegacion",
                        "dado": "un pedido de otra persona",
                        "cuando": "María intenta cambiar la fecha",
                        "entonces": "se rechaza sin modificar el pedido",
                        "cubre": "R-2",
                    },
                ],
            }
        ],
        "superficie": {
            "puntos": [
                {
                    "nombre": "Panel de pedidos",
                    "quien": ["María"],
                    "llega": "ordenador",
                    "cuando": "al revisar un pedido",
                    "ve": "sus pedidos",
                    "puede": ["editar pedido"],
                    "nunca": [
                        {
                            "accion": "editar pedidos ajenos",
                            "requisito": "R-2",
                            "criterio": "C-2",
                        }
                    ],
                }
            ],
            "permisos": {
                "acciones": ["editar pedido"],
                "roles": [{"rol": "operadora", "permitidas": ["editar pedido"]}],
                "grupos": [{"grupo": "pedidos", "permitidas": ["editar pedido"]}],
                "restricciones": [
                    {
                        "id": "P-1",
                        "rol": "operadora",
                        "accion": "editar pedido",
                        "recurso": "pedido",
                        "alcance": "propio",
                        "condicion": "cuenta activa",
                        "requisito": "R-2",
                        "criterio": "C-2",
                    }
                ],
            },
        },
        "pruebas_e2e": [
            {
                "id": "E2E-1",
                "tipo": "camino_feliz",
                "criterios": ["C-1"],
                "personas": ["María"],
                "fronteras": ["rol"],
                "token": "token-hostil-no-proyectable",
            },
            {
                "id": "E2E-2",
                "tipo": "denegacion",
                "criterios": ["C-2"],
                "personas": ["María"],
                "fronteras": ["propiedad"],
                "restricciones": ["P-1"],
            },
        ],
    }


class GenerarSpecE2ETest(unittest.TestCase):
    def generar(self, plano):
        with tempfile.TemporaryDirectory() as directorio:
            raiz = Path(directorio)
            datos = raiz / "planos.json"
            salida = raiz / "spec.md"
            datos.write_text(json.dumps(plano), encoding="utf-8")
            resultado = subprocess.run(
                [sys.executable, str(GENERADOR), "--datos", str(datos), "--salida", str(salida)],
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                check=False,
            )
            self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
            return salida.read_text(encoding="utf-8")

    def test_proyecta_trazabilidad_roles_restricciones_y_e2e(self):
        spec = self.generar(plano_con_e2e())

        self.assertIn("regla G-1", spec)
        self.assertIn("cubre R-1", spec)
        self.assertIn("E2E-1", spec)
        self.assertIn("María · operadora", spec)
        self.assertIn("organización: Almacén Norte", spec)
        self.assertIn("grupos: pedidos, turno de mañana", spec)
        self.assertIn("grupo: pedidos", spec)
        self.assertIn("estado: activa", spec)
        self.assertIn("P-1", spec)
        self.assertIn("editar pedidos ajenos (R-2 · C-2)", spec)
        self.assertIn("fronteras: rol", spec)
        self.assertIn("fronteras: propiedad", spec)
        self.assertNotIn("contraseña", spec.lower())
        self.assertNotIn("maria-acceso@example.test", spec)
        self.assertNotIn("clave-hostil-no-proyectable", spec)
        self.assertNotIn("token-hostil-no-proyectable", spec)
        self.assertNotIn("secreto-raiz-no-proyectable", spec)

    def test_plan_anterior_sin_contrato_e2e_se_sigue_generando(self):
        plano = plano_con_e2e()
        del plano["pruebas_e2e"]
        del plano["superficie"]["permisos"]["restricciones"]
        for actor in plano["actores"]:
            actor.pop("rol", None)

        spec = self.generar(plano)

        self.assertIn("REC-1", spec)
        self.assertNotIn("Pruebas E2E seleccionadas", spec)

    def test_fixture_enlaza_fronteras_a_denegaciones_y_caminos_felices(self):
        ejemplo = plano_con_e2e()
        requisitos = {
            requisito["id"]: requisito
            for recorrido in ejemplo["recorridos"]
            for requisito in recorrido["requisitos"]
        }
        criterios = {
            criterio["id"]: criterio
            for recorrido in ejemplo["recorridos"]
            for criterio in recorrido["criterios"]
        }
        restricciones = ejemplo["superficie"]["permisos"]["restricciones"]

        for restriccion in restricciones:
            criterio = criterios[restriccion["criterio"]]
            self.assertEqual(criterio["cubre"], restriccion["requisito"])
            self.assertEqual(criterio["tipo"], "denegacion")
            self.assertTrue(
                any(
                    prueba["tipo"] == "denegacion"
                    and restriccion["id"] in prueba["restricciones"]
                    and restriccion["criterio"] in prueba["criterios"]
                    for prueba in ejemplo["pruebas_e2e"]
                )
            )

        feliz = next(p for p in ejemplo["pruebas_e2e"] if p["tipo"] == "camino_feliz")
        self.assertEqual(feliz["criterios"], ["C-1"])
        self.assertEqual(criterios["C-1"]["tipo"], "feliz")
        self.assertIn("denegarlo", requisitos["R-2"]["texto"])

    def test_cada_nunca_del_fixture_tiene_requisito_y_criterio_negativos(self):
        ejemplo = plano_con_e2e()
        requisitos = {
            requisito["id"]: requisito
            for recorrido in ejemplo["recorridos"]
            for requisito in recorrido["requisitos"]
        }
        criterios = {
            criterio["id"]: criterio
            for recorrido in ejemplo["recorridos"]
            for criterio in recorrido["criterios"]
        }
        self.assertEqual(
            ejemplo["superficie"]["puntos"][0]["nunca"],
            [
                {
                    "accion": "editar pedidos ajenos",
                    "requisito": "R-2",
                    "criterio": "C-2",
                }
            ],
        )
        nunca = ejemplo["superficie"]["puntos"][0]["nunca"][0]
        requisito = requisitos[nunca["requisito"]]
        criterio = criterios[nunca["criterio"]]
        self.assertRegex(requisito["texto"].strip().lower(), r"^si\b")
        self.assertEqual(criterio["cubre"], nunca["requisito"])
        self.assertEqual(criterio["tipo"], "denegacion")
        self.assertRegex(criterio["entonces"].lower(), r"(se rechaza|sin modificar)")


if __name__ == "__main__":
    unittest.main()
