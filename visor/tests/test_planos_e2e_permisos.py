import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
VALIDAR = RAIZ / "visor" / "validar.py"


def plano_coherente():
    return {
        "version": 2,
        "titulo": "Pedidos",
        "descripcion": "María gestiona los pedidos que tiene asignados.",
        "definicion": {
            "estado": "listo para revisar",
            "modo": "entrevista",
            "bloques_no_aplican": [
                "reglas",
                "volumen",
                "integraciones",
                "estados",
                "datos",
                "calidad",
                "fuera",
            ],
            "supuestos": [],
        },
        "cobertura": {
            "estado": "no implementado",
            "evidencias": [],
            "pruebas": [],
        },
        "contrato": {
            "frase": "Cuando llega un pedido, María necesita editarlo para tramitarlo.",
            "exito": "Todos los pedidos quedan tramitados.",
        },
        "actores": [{"nombre": "María", "rol": "operadora"}],
        "flujos": [
            {
                "id": "editar-pedido",
                "titulo": "Editar un pedido propio",
                "momento": "futuro",
                "origen": "usuario",
                "pasos": [
                    {
                        "tipo": "humano",
                        "texto": "María editó el pedido",
                        "quien": "María",
                    }
                ],
            }
        ],
        "episodios": [
            {
                "id": "EP-1",
                "texto": "María no pudo cambiar el pedido 42 asignado a Carmen.",
                "refs": ["C-1"],
            }
        ],
        "recorridos": [
            {
                "id": "REC-1",
                "nombre": "Editar pedido propio",
                "flujos": ["editar-pedido"],
                "requisitos": [
                    {
                        "id": "R-1",
                        "texto": "Si María intenta editar un pedido ajeno, entonces el sistema deberá denegarlo.",
                        "origen": "usuario",
                        "implementacion": {
                            "estado": "no implementado",
                            "evidencias": [],
                            "pruebas": [],
                        },
                    },
                    {
                        "id": "R-2",
                        "texto": "Cuando María abre un pedido propio, el sistema deberá permitir editarlo.",
                        "origen": "usuario",
                        "implementacion": {
                            "estado": "no implementado",
                            "evidencias": [],
                            "pruebas": [],
                        },
                    },
                    {
                        "id": "R-4",
                        "texto": "Si María intenta borrar un pedido, entonces el sistema deberá denegarlo.",
                        "origen": "usuario",
                        "implementacion": {
                            "estado": "no implementado",
                            "evidencias": [],
                            "pruebas": [],
                        },
                    },
                ],
                "criterios": [
                    {
                        "id": "C-1",
                        "tipo": "denegacion",
                        "dado": "el pedido 42 asignado a Carmen",
                        "cuando": "María cambia su dirección",
                        "entonces": "la app lo rechaza y el pedido no cambia",
                        "cubre": "R-1",
                    },
                    {
                        "id": "C-2",
                        "tipo": "feliz",
                        "dado": "el pedido 41 asignado a María",
                        "cuando": "María cambia su dirección",
                        "entonces": "el pedido conserva la nueva dirección",
                        "cubre": "R-2",
                    },
                    {
                        "id": "C-4",
                        "tipo": "denegacion",
                        "dado": "el pedido 41 asignado a María",
                        "cuando": "María intenta borrarlo",
                        "entonces": "la app lo rechaza y el pedido no cambia",
                        "cubre": "R-4",
                    },
                ],
            }
        ],
        "superficie": {
            "puntos": [
                {
                    "id": "SUP-1",
                    "nombre": "Panel de María",
                    "quien": ["María"],
                    "llega": "ordenador",
                    "cuando": "al tramitar un pedido",
                    "ve": "sus pedidos asignados",
                    "puede": ["editar pedido"],
                    "nunca": [
                        {
                            "accion": "borrar pedido",
                            "requisito": "R-4",
                            "criterio": "C-4",
                        }
                    ],
                }
            ],
            "permisos": {
                "acciones": ["editar pedido"],
                "roles": [
                    {"rol": "operadora", "permitidas": ["editar pedido"]}
                ],
                "restricciones": [
                    {
                        "id": "P-1",
                        "rol": "operadora",
                        "accion": "editar pedido",
                        "recurso": "pedido",
                        "alcance": "propio",
                        "condicion": "cuenta activa",
                        "requisito": "R-1",
                        "criterio": "C-1",
                    }
                ],
            },
        },
        "pruebas_e2e": [
            {
                "id": "E2E-1",
                "tipo": "denegacion",
                "criterios": ["C-1"],
                "personas": ["María"],
                "fronteras": ["rol", "propiedad"],
                "restricciones": ["P-1"],
            },
            {
                "id": "E2E-2",
                "tipo": "camino_feliz",
                "criterios": ["C-2"],
                "personas": ["María"],
                "fronteras": ["rol"],
            },
        ],
    }


class PlanosE2EPermisosTest(unittest.TestCase):
    def ejecutar(self, plano):
        with tempfile.TemporaryDirectory(prefix="planos-e2e-") as temporal:
            ruta = Path(temporal) / "planos.json"
            ruta.write_text(
                json.dumps(plano, ensure_ascii=False), encoding="utf-8"
            )
            return subprocess.run(
                [
                    sys.executable,
                    str(VALIDAR),
                    "--datos",
                    str(ruta),
                    "--perfil",
                    "revision",
                ],
                text=True, encoding="utf-8", errors="replace",
                capture_output=True,
            )

    def test_criterio_no_puede_cubrir_requisito_de_otro_recorrido(self):
        plano = plano_coherente()
        plano["recorridos"].append(
            {
                "id": "REC-2",
                "nombre": "Consultar pedido",
                "flujos": ["editar-pedido"],
                "requisitos": [
                    {
                        "id": "R-3",
                        "texto": "Cuando María consulta un pedido, el sistema deberá mostrarlo.",
                        "origen": "usuario",
                        "implementacion": {
                            "estado": "no implementado",
                            "evidencias": [],
                            "pruebas": [],
                        },
                    }
                ],
                "criterios": [
                    {
                        "id": "C-3",
                        "tipo": "feliz",
                        "dado": "el pedido 42",
                        "cuando": "María lo consulta",
                        "entonces": "ve el pedido",
                        "cubre": "R-3",
                    }
                ],
            }
        )
        plano["recorridos"][0]["criterios"][0]["cubre"] = "R-3"

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("C-1", resultado.stdout)
        self.assertIn("REC-1", resultado.stdout)
        self.assertIn("R-3", resultado.stdout)

    def test_criterio_sin_cubre_bloquea_revision(self):
        plano = plano_coherente()
        del plano["recorridos"][0]["criterios"][0]["cubre"]
        plano["superficie"]["permisos"]["restricciones"] = []

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("C-1", resultado.stdout)
        self.assertIn("cubre", resultado.stdout)

    def test_plan_legacy_sin_e2e_restricciones_ni_cubre_solo_avisa(self):
        plano = plano_coherente()
        del plano["pruebas_e2e"]
        del plano["superficie"]["permisos"]["restricciones"]
        plano["superficie"]["puntos"][0]["nunca"] = ["borrar pedido"]
        for criterio in plano["recorridos"][0]["criterios"]:
            criterio.pop("tipo", None)
            criterio.pop("cubre", None)

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn("AVISO", resultado.stdout)
        self.assertIn("cubre", resultado.stdout)

    def test_prueba_e2e_rechaza_criterio_o_persona_inexistente(self):
        plano = plano_coherente()
        plano["pruebas_e2e"][0]["criterios"] = ["C-404"]
        plano["pruebas_e2e"][0]["personas"] = ["Ana"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("E2E-1", resultado.stdout)
        self.assertIn("C-404", resultado.stdout)
        self.assertIn("Ana", resultado.stdout)

    def test_restricciones_nuevas_sin_pruebas_e2e_bloquean(self):
        plano = plano_coherente()
        del plano["pruebas_e2e"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("P-1", resultado.stdout)
        self.assertIn("pruebas_e2e", resultado.stdout)

    def test_criterio_de_restriccion_debe_estar_seleccionado_en_e2e(self):
        plano = plano_coherente()
        plano["pruebas_e2e"][0]["criterios"] = ["C-2"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("P-1", resultado.stdout)
        self.assertIn("C-1", resultado.stdout)
        self.assertIn("E2E", resultado.stdout)

    def test_restriccion_solo_puede_citar_un_criterio_de_denegacion(self):
        plano = plano_coherente()
        restriccion = plano["superficie"]["permisos"]["restricciones"][0]
        restriccion["requisito"] = "R-2"
        restriccion["criterio"] = "C-2"
        plano["pruebas_e2e"][0]["criterios"] = ["C-2"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("P-1", resultado.stdout)
        self.assertIn("C-2", resultado.stdout)
        self.assertIn("denegacion", resultado.stdout)

    def test_e2e_de_denegacion_debe_enlazar_su_restriccion_y_criterio(self):
        casos = []

        sin_restriccion = plano_coherente()
        del sin_restriccion["pruebas_e2e"][0]["restricciones"]
        casos.append(("sin restricciones", sin_restriccion, "restricciones"))

        inexistente = plano_coherente()
        inexistente["pruebas_e2e"][0]["restricciones"] = ["P-404"]
        casos.append(("restricción inexistente", inexistente, "P-404"))

        criterio_ajeno = plano_coherente()
        criterio_ajeno["pruebas_e2e"][0]["criterios"] = ["C-2"]
        casos.append(("criterio ajeno", criterio_ajeno, "C-1"))

        for nombre, plano, referencia in casos:
            with self.subTest(nombre=nombre):
                resultado = self.ejecutar(plano)
                self.assertEqual(resultado.returncode, 1, resultado.stdout)
                self.assertIn("E2E-1", resultado.stdout)
                self.assertIn(referencia, resultado.stdout)

    def test_e2e_de_denegacion_no_cuenta_como_camino_feliz_del_rol(self):
        plano = plano_coherente()
        plano["pruebas_e2e"] = [plano["pruebas_e2e"][0]]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("operadora", resultado.stdout)
        self.assertIn("camino feliz", resultado.stdout)

    def test_persona_e2e_debe_tener_rol_y_el_rol_existir_en_matriz(self):
        casos = []
        sin_rol = plano_coherente()
        del sin_rol["actores"][0]["rol"]
        casos.append(("sin rol", sin_rol, "María"))

        sin_rol_en_matriz = plano_coherente()
        sin_rol_en_matriz["superficie"]["permisos"]["roles"][0]["rol"] = (
            "supervisora"
        )
        casos.append(("rol fuera de matriz", sin_rol_en_matriz, "operadora"))

        sin_camino_feliz = plano_coherente()
        sin_camino_feliz["actores"].append(
            {"nombre": "Ana", "rol": "supervisora"}
        )
        sin_camino_feliz["superficie"]["puntos"].append(
            {
                "id": "SUP-2",
                "nombre": "Panel de Ana",
                "quien": ["Ana"],
                "llega": "ordenador",
                "cuando": "al revisar un pedido",
                "ve": "los pedidos pendientes",
                "puede": ["revisar pedido"],
                "nunca": [],
            }
        )
        permisos = sin_camino_feliz["superficie"]["permisos"]
        permisos["acciones"].append("revisar pedido")
        permisos["roles"].append(
            {"rol": "supervisora", "permitidas": ["revisar pedido"]}
        )
        casos.append(("sin camino feliz", sin_camino_feliz, "supervisora"))

        for nombre, plano, referencia in casos:
            with self.subTest(nombre=nombre):
                resultado = self.ejecutar(plano)
                self.assertEqual(resultado.returncode, 1, resultado.stdout)
                self.assertIn("E2E-1", resultado.stdout)
                self.assertIn(referencia, resultado.stdout)

    def test_puede_y_nunca_no_pueden_contradecir_la_matriz(self):
        plano = plano_coherente()
        permisos = plano["superficie"]["permisos"]
        permisos["acciones"].append("borrar pedido")
        permisos["roles"][0]["permitidas"] = ["borrar pedido"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("operadora", resultado.stdout)
        self.assertIn("editar pedido", resultado.stdout)
        self.assertIn("borrar pedido", resultado.stdout)

    def test_contrato_nuevo_rechaza_nunca_sin_trazabilidad_estructurada(self):
        plano = plano_coherente()
        plano["superficie"]["puntos"][0]["nunca"] = ["borrar pedido"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("SUP-1", resultado.stdout)
        self.assertIn("borrar pedido", resultado.stdout)
        self.assertIn("requisito", resultado.stdout)

    def test_nunca_estructurado_exige_r_c_denegacion_y_cobertura_coherente(self):
        casos = []

        requisito_inexistente = plano_coherente()
        requisito_inexistente["superficie"]["puntos"][0]["nunca"][0]["requisito"] = "R-404"
        casos.append(("requisito inexistente", requisito_inexistente, "R-404"))

        criterio_inexistente = plano_coherente()
        criterio_inexistente["superficie"]["puntos"][0]["nunca"][0]["criterio"] = "C-404"
        casos.append(("criterio inexistente", criterio_inexistente, "C-404"))

        criterio_feliz = plano_coherente()
        nunca = criterio_feliz["superficie"]["puntos"][0]["nunca"][0]
        nunca["requisito"] = "R-2"
        nunca["criterio"] = "C-2"
        casos.append(("criterio feliz", criterio_feliz, "denegacion"))

        cobertura_cruzada = plano_coherente()
        cobertura_cruzada["superficie"]["puntos"][0]["nunca"][0]["requisito"] = "R-1"
        casos.append(("cobertura cruzada", cobertura_cruzada, "R-1"))

        for nombre, plano, referencia in casos:
            with self.subTest(nombre=nombre):
                resultado = self.ejecutar(plano)
                self.assertEqual(resultado.returncode, 1, resultado.stdout)
                self.assertIn("SUP-1", resultado.stdout)
                self.assertIn(referencia, resultado.stdout)

    def test_contrato_nuevo_rechaza_rol_usado_como_persona(self):
        plano = plano_coherente()
        plano["superficie"]["puntos"][0]["quien"] = ["operadora"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("SUP-1", resultado.stdout)
        self.assertIn("operadora", resultado.stdout)
        self.assertIn("persona", resultado.stdout)

    def test_contrato_nuevo_rechaza_fila_de_rol_con_nombre_de_persona(self):
        plano = plano_coherente()
        plano["superficie"]["permisos"]["roles"].append(
            {"rol": "María", "permitidas": []}
        )

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("superficie.permisos.roles", resultado.stdout)
        self.assertIn("María", resultado.stdout)
        self.assertIn("persona", resultado.stdout)

    def test_plan_legacy_admite_fila_de_matriz_con_nombre_de_persona(self):
        plano = plano_coherente()
        del plano["pruebas_e2e"]
        del plano["superficie"]["permisos"]["restricciones"]
        del plano["actores"][0]["rol"]
        plano["superficie"]["permisos"]["roles"] = [
            {"rol": "María", "permitidas": ["editar pedido"]}
        ]
        plano["superficie"]["puntos"][0]["nunca"] = ["borrar pedido"]
        for criterio in plano["recorridos"][0]["criterios"]:
            criterio.pop("tipo", None)

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 0, resultado.stdout)

    def test_plan_legacy_con_literales_de_accion_antiguos_solo_avisa(self):
        plano = plano_coherente()
        del plano["pruebas_e2e"]
        del plano["superficie"]["permisos"]["restricciones"]
        del plano["actores"][0]["rol"]
        plano["superficie"]["permisos"]["roles"] = [
            {"rol": "María", "permitidas": ["editar pedido"]}
        ]
        plano["superficie"]["puntos"][0]["puede"] = [
            "editar un pedido con el literal anterior"
        ]
        plano["superficie"]["puntos"][0]["nunca"] = ["borrar pedido"]
        for criterio in plano["recorridos"][0]["criterios"]:
            criterio.pop("tipo", None)

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn("AVISO", resultado.stdout)
        self.assertIn("literal anterior", resultado.stdout)

    def test_restriccion_critica_exige_requisito_y_criterio(self):
        plano = plano_coherente()
        restriccion = plano["superficie"]["permisos"]["restricciones"][0]
        restriccion["requisito"] = "R-404"
        restriccion["criterio"] = "C-404"

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("P-1", resultado.stdout)
        self.assertIn("R-404", resultado.stdout)
        self.assertIn("C-404", resultado.stdout)

    def test_episodio_con_referencia_inexistente_bloquea(self):
        plano = plano_coherente()
        plano["episodios"][0]["refs"] = ["C-404"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("EP-1", resultado.stdout)
        self.assertIn("C-404", resultado.stdout)

    def test_plan_anterior_sin_pruebas_e2e_solo_avisa(self):
        plano = plano_coherente()
        del plano["pruebas_e2e"]
        del plano["episodios"][0]["id"]
        del plano["recorridos"][0]["flujos"]
        del plano["superficie"]["puntos"][0]["id"]
        del plano["superficie"]["permisos"]["restricciones"]
        plano["superficie"]["puntos"][0]["nunca"] = ["borrar pedido"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn("AVISO", resultado.stdout)
        self.assertIn("pruebas_e2e", resultado.stdout)

    def test_plan_coherente_con_roles_restricciones_y_e2e_pasa(self):
        resultado = self.ejecutar(copy.deepcopy(plano_coherente()))

        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn("OK: planos válidos", resultado.stdout)

    def test_persona_puede_declarar_organizacion_grupos_y_estado(self):
        plano = plano_coherente()
        plano["actores"][0].update(
            {
                "organizacion": "cooperativa norte",
                "grupos": ["operaciones", "turno mañana"],
                "estado": "activa",
            }
        )

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn("OK: planos válidos", resultado.stdout)

    def test_grupo_puede_conceder_permiso_base_a_sus_miembros(self):
        plano = plano_coherente()
        plano["actores"][0]["grupos"] = ["equipo de pedidos"]
        permisos = plano["superficie"]["permisos"]
        permisos["roles"][0]["permitidas"] = []
        permisos["grupos"] = [
            {"grupo": "equipo de pedidos", "permitidas": ["editar pedido"]}
        ]
        restriccion = permisos["restricciones"][0]
        restriccion["grupo"] = "equipo de pedidos"
        del restriccion["rol"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn("OK: planos válidos", resultado.stdout)

        plano["actores"][0]["grupos"] = []
        resultado = self.ejecutar(plano)
        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("equipo de pedidos", resultado.stdout)

    def test_e2e_de_restriccion_de_grupo_usa_una_persona_del_grupo(self):
        plano = plano_coherente()
        plano["actores"][0]["grupos"] = ["equipo de pedidos"]
        plano["actores"].append({"nombre": "Carmen", "rol": "operadora"})
        permisos = plano["superficie"]["permisos"]
        permisos["grupos"] = [
            {"grupo": "equipo de pedidos", "permitidas": ["editar pedido"]}
        ]
        restriccion = permisos["restricciones"][0]
        restriccion["grupo"] = "equipo de pedidos"
        del restriccion["rol"]
        plano["pruebas_e2e"][0]["personas"] = ["Carmen"]

        resultado = self.ejecutar(plano)

        self.assertEqual(resultado.returncode, 1, resultado.stdout)
        self.assertIn("P-1", resultado.stdout)
        self.assertIn("equipo de pedidos", resultado.stdout)
        self.assertIn("E2E-1", resultado.stdout)

    def test_plan_legacy_con_rol_en_quien_no_rompe_el_validador(self):
        plano = plano_coherente()
        del plano["pruebas_e2e"]
        del plano["superficie"]["permisos"]["restricciones"]
        del plano["actores"][0]["rol"]
        plano["superficie"]["puntos"][0]["quien"] = ["operadora"]
        plano["superficie"]["puntos"][0]["nunca"] = ["borrar pedido"]

        resultado = self.ejecutar(plano)

        self.assertNotIn("Traceback", resultado.stdout + resultado.stderr)
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)


if __name__ == "__main__":
    unittest.main()
