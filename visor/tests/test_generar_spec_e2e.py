import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
GENERADOR = RAIZ / "visor" / "generar_spec.py"
COMPILAR = RAIZ / "visor" / "compilar.py"


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


# --- Bug 092: compilar.py respeta la estructura que YA tiene el proyecto -------------
#
# Un workspace nacido del bootstrap guarda sus specs APLANADAS (docs/02-flujos/<id>.md,
# un .md por actividad, hermanos del INDICE.md que mantiene el padre). compilar.py
# escribía SIEMPRE 01-constitution/ + 02-flows/ bajo --salida, dejando el .md histórico
# huérfano y la documentación incoherente. Ahora mira la salida antes de escribir.


def plano_de_proyecto_simple():
    """Mapa de proyecto de una sola actividad (sin lista `actividades`)."""
    plano = plano_con_e2e()
    plano["proyecto"] = "pedidos"
    plano["titulo"] = "Pedidos seguros"
    return plano


def plano_de_mapa_con_actividades():
    return {
        "version": 2,
        "proyecto": "taller",
        "titulo": "Taller",
        "actividades": [
            {"id": "recibir-pedido", "nombre": "Recibir pedido", "area": "General",
             "estado": "especificada"},
            {"id": "enviar-pedido", "nombre": "Enviar pedido", "area": "General",
             "estado": "especificada"},
        ],
    }


class CompilarRespetaEstructuraTest(unittest.TestCase):
    def preparar(self, plano, actividades=None):
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        raiz = Path(directorio.name)
        mapa = raiz / "planos.json"
        mapa.write_text(json.dumps(plano, ensure_ascii=False), encoding="utf-8")
        for identificador, datos in (actividades or {}).items():
            carpeta = raiz / "actividades" / identificador
            carpeta.mkdir(parents=True)
            (carpeta / "planos.json").write_text(
                json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        salida = raiz / "salida"
        salida.mkdir()
        return mapa, salida

    def compilar(self, mapa, salida, *extra):
        return subprocess.run(
            [sys.executable, str(COMPILAR), "--mapa", str(mapa), "--salida", str(salida),
             *extra],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False,
        )

    # 1. El bug: proyecto plano -> se regenera el .md plano, sin estructura nueva.
    def test_proyecto_plano_recompila_el_md_y_no_crea_carpetas(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())
        (salida / "pedidos.md").write_text("# Spec viejo\n", encoding="utf-8")
        (salida / "INDICE.md").write_text(
            "| Pedidos (`pedidos`) | especificada | [pedidos.md](pedidos.md) | — |\n",
            encoding="utf-8")

        r = self.compilar(mapa, salida)

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((salida / "02-flows").exists(), "no debe crear 02-flows/")
        self.assertFalse((salida / "01-constitution").exists(), "no debe crear 01-constitution/")
        self.assertFalse((salida / "README.md").exists(), "no debe crear README.md")
        texto = (salida / "pedidos.md").read_text(encoding="utf-8")
        self.assertIn("REC-1", texto)
        self.assertNotIn("Spec viejo", texto)
        self.assertIn("plano", r.stdout)
        # El índice lo mantiene el padre del workspace: no se pisa.
        self.assertIn("[pedidos.md](pedidos.md)",
                      (salida / "INDICE.md").read_text(encoding="utf-8"))

    # 2. Un mapa con actividades aplanadas: un .md por actividad, hermanos del índice.
    def test_mapa_con_actividades_planas_regenera_cada_md_hermano(self):
        actividades = {
            "recibir-pedido": plano_con_e2e(),
            "enviar-pedido": plano_con_e2e(),
        }
        mapa, salida = self.preparar(plano_de_mapa_con_actividades(), actividades)
        (salida / "recibir-pedido.md").write_text("viejo\n", encoding="utf-8")
        (salida / "enviar-pedido.md").write_text("viejo\n", encoding="utf-8")

        r = self.compilar(mapa, salida)

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((salida / "02-flows").exists())
        for nombre in ("recibir-pedido.md", "enviar-pedido.md"):
            self.assertIn("REC-1", (salida / nombre).read_text(encoding="utf-8"))

    # 3. La señal puede venir solo del índice, aunque el .md se haya borrado.
    def test_indice_que_enlaza_al_plano_basta_como_senal(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())
        (salida / "INDICE.md").write_text("- [Pedidos](pedidos.md)\n", encoding="utf-8")

        r = self.compilar(mapa, salida)

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((salida / "02-flows").exists())
        self.assertTrue((salida / "pedidos.md").is_file())

    # 4. Comportamiento de HOY intacto: salida vacía -> carpetas.
    def test_salida_vacia_sigue_compilando_en_carpetas(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())

        r = self.compilar(mapa, salida)

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((salida / "01-constitution" / "constitution.md").is_file())
        self.assertTrue((salida / "02-flows" / "pedidos.md").is_file())
        self.assertTrue((salida / "README.md").is_file())

    # 5. Comportamiento de HOY intacto: ya hay carpetas -> se regeneran.
    def test_salida_con_carpetas_sigue_compilando_en_carpetas(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())
        (salida / "02-flows").mkdir()
        (salida / "02-flows" / "sobra.md").write_text("residuo\n", encoding="utf-8")

        r = self.compilar(mapa, salida)

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((salida / "02-flows" / "pedidos.md").is_file())
        self.assertFalse((salida / "02-flows" / "sobra.md").exists())

    # 6. Los dos formatos a la vez: no se escribe nada y se dicen las dos salidas.
    def test_ambos_formatos_avisa_con_las_dos_salidas_y_no_escribe(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())
        (salida / "pedidos.md").write_text("# Spec viejo\n", encoding="utf-8")
        (salida / "02-flows").mkdir()
        (salida / "02-flows" / "pedidos.md").write_text("# En carpetas\n", encoding="utf-8")

        r = self.compilar(mapa, salida)

        self.assertNotEqual(r.returncode, 0, r.stdout)
        aviso = r.stdout + r.stderr
        self.assertIn("SALIDA:", aviso)
        self.assertIn("--formato plano", aviso)
        self.assertIn("--formato carpetas", aviso)
        self.assertEqual("# Spec viejo\n", (salida / "pedidos.md").read_text(encoding="utf-8"))
        self.assertEqual("# En carpetas\n",
                         (salida / "02-flows" / "pedidos.md").read_text(encoding="utf-8"))

    # 7. Documentación ajena en la salida: tampoco se adivina.
    def test_salida_con_documentacion_ajena_avisa_y_no_escribe(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())
        (salida / "otra-cosa.md").write_text("# Documento del usuario\n", encoding="utf-8")

        r = self.compilar(mapa, salida)

        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("SALIDA:", r.stdout + r.stderr)
        self.assertFalse((salida / "02-flows").exists())
        self.assertEqual("# Documento del usuario\n",
                         (salida / "otra-cosa.md").read_text(encoding="utf-8"))

    # 8. --formato manda sobre la detección, en los dos sentidos.
    def test_formato_explicito_manda_sobre_la_deteccion(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())
        (salida / "pedidos.md").write_text("# Spec viejo\n", encoding="utf-8")

        r = self.compilar(mapa, salida, "--formato", "carpetas")

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((salida / "02-flows" / "pedidos.md").is_file())

    def test_formato_plano_explicito_sobre_salida_vacia(self):
        mapa, salida = self.preparar(plano_de_proyecto_simple())

        r = self.compilar(mapa, salida, "--formato", "plano")

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((salida / "pedidos.md").is_file())
        self.assertFalse((salida / "02-flows").exists())

    # 9. El incidente c5b972b6 tal cual: docs/02-flujos con el .md del PROYECTO (no de
    #    una actividad) y su INDICE.md. El mapa ya tiene actividades, así que ese .md no
    #    corresponde a ninguna: antes se sepultaba con 01-constitution/ + 02-flows/;
    #    ahora se avisa y no se toca nada.
    def test_incidente_md_de_proyecto_con_mapa_de_actividades_avisa_y_no_escribe(self):
        mapa, salida = self.preparar(plano_de_mapa_con_actividades(),
                                     {"recibir-pedido": plano_con_e2e()})
        (salida / "taller.md").write_text("# Spec: Taller\n", encoding="utf-8")
        (salida / "INDICE.md").write_text("- [Taller](taller.md)\n", encoding="utf-8")

        r = self.compilar(mapa, salida)

        self.assertNotEqual(r.returncode, 0, r.stdout)
        aviso = r.stdout + r.stderr
        self.assertIn("SALIDA:", aviso)
        self.assertIn("--formato plano", aviso)
        self.assertIn("--formato carpetas", aviso)
        self.assertFalse((salida / "02-flows").exists())
        self.assertFalse((salida / "01-constitution").exists())
        self.assertEqual("# Spec: Taller\n", (salida / "taller.md").read_text(encoding="utf-8"))
        self.assertEqual("- [Taller](taller.md)\n",
                         (salida / "INDICE.md").read_text(encoding="utf-8"))

    # 10. Y si el usuario elige plano, se le dice qué queda fuera del mapa.
    def test_formato_plano_nombra_los_md_que_ya_no_salen_del_mapa(self):
        mapa, salida = self.preparar(plano_de_mapa_con_actividades(),
                                     {"recibir-pedido": plano_con_e2e()})
        (salida / "taller.md").write_text("# Spec: Taller\n", encoding="utf-8")

        r = self.compilar(mapa, salida, "--formato", "plano")

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("REC-1", (salida / "recibir-pedido.md").read_text(encoding="utf-8"))
        self.assertIn("taller.md", r.stdout)
        self.assertEqual("# Spec: Taller\n", (salida / "taller.md").read_text(encoding="utf-8"))
        self.assertIn("Enviar pedido", r.stdout)  # la actividad sin planos, nombrada



if __name__ == "__main__":
    unittest.main()
