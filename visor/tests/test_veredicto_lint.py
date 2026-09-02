"""R2/R5/R6: el cierre decide por identidad estructurada, no por texto ni returncode."""

import importlib.util
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "plantilla/docs/00-metodo/scripts/veredicto_lint.py"


def cargar():
    if not MODULO.is_file():
        return None
    spec = importlib.util.spec_from_file_location("veredicto_lint_bajo_prueba", MODULO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def h(id_, severidad="FAIL", sujeto="taller", ruta=".", instancia="unica"):
    return {
        "id": id_, "severidad": severidad, "sujeto": sujeto,
        "ruta": ruta, "instancia": instancia,
    }


def evidencia():
    return {
        "base_revision": "a" * 40,
        "head_revision": "b" * 40,
        "snapshot_id": "snapshot-r2",
        "base_evaluada_en": "2026-09-02T00:00:00+00:00",
        "head_evaluada_en": "2026-09-02T00:00:01+00:00",
    }


class VeredictoLintTest(unittest.TestCase):
    def setUp(self):
        self.modulo = cargar()
        self.assertIsNotNone(
            self.modulo,
            "R2 ROJO: falta plantilla/docs/00-metodo/scripts/veredicto_lint.py",
        )

    def decidir(self, base, head, unidad="148-rojos-por-sujeto", peticiones=None):
        return self.modulo.veredicto_cierre(
            base, head, unidad, peticiones or ["P-20260901-dfd22a99@1"], evidencia()
        )

    def test_meta_acredita_revisiones_snapshot_y_horas(self):
        veredicto = self.decidir([], [])
        self.assertEqual(veredicto.meta["evidencia"], evidencia())

    def test_evidencia_ausente_o_incompleta_falla_cerrado(self):
        for contexto in (None, {}, {"base_revision": "a" * 40}):
            veredicto = self.modulo.veredicto_cierre(
                [], [], "148-rojos-por-sujeto", ["P-20260901-dfd22a99@1"], contexto
            )
            self.assertTrue(veredicto.bloquea, contexto)
            self.assertIn("infraestructura", veredicto.motivo.lower())

    def test_rojo_propio_bloquea_por_igualdad_exacta(self):
        propio = h("mergeada-sin-ok", sujeto="unidad:148-rojos-por-sujeto")
        veredicto = self.decidir([propio], [propio])
        self.assertTrue(veredicto.bloquea)
        parecido = h("mergeada-sin-ok", sujeto="unidad:148-rojos-por-sujeto-extra")
        self.assertFalse(self.decidir([parecido], [parecido]).bloquea)

    def test_rojo_de_cualquiera_de_las_peticiones_propias_bloquea(self):
        propio = h("peticion-invalida", sujeto="peticion:P-20260901-dfd22a99@1")
        self.assertTrue(self.decidir([propio], [propio]).bloquea)

    def test_ajeno_preexistente_se_agrega_y_no_bloquea(self):
        ajeno = h("mergeada-sin-ok", sujeto="bug:080", ruta="docs/bugs/080.md")
        veredicto = self.decidir([ajeno], [ajeno])
        self.assertFalse(veredicto.bloquea)
        self.assertEqual(veredicto.agrega, 1)
        self.assertIn("ajeno", veredicto.salida.lower())

    def test_nuevo_se_calcula_como_multiconjunto_y_detecta_segundo_ejemplar(self):
        uno = h("pkill", ruta="main/scripts/dev.sh", instancia="linea:2")
        dos = h("pkill", ruta="main/scripts/dev.sh", instancia="linea:8")
        self.assertTrue(self.decidir([uno], [uno, dos]).bloquea)

    def test_segundo_ejemplar_bloquea_sin_perder_el_ajeno_preexistente(self):
        uno = h("pkill", ruta="main/scripts/dev.sh", instancia="linea:2")
        veredicto = self.decidir([uno], [uno, uno])
        self.assertTrue(veredicto.bloquea)
        self.assertEqual(len(veredicto.meta["nuevos"]), 1)
        self.assertEqual(veredicto.agrega, 1)
        self.assertEqual(veredicto.meta["ajenos_preexistentes"], 1)

    def test_mover_de_ruta_es_un_hallazgo_nuevo(self):
        base = h("pkill", ruta="main/scripts/a.sh", instancia="linea:2")
        movido = h("pkill", ruta="main/scripts/b.sh", instancia="linea:2")
        self.assertTrue(self.decidir([base], [movido]).bloquea)

    def test_warn_nuevo_no_se_convierte_en_rojo(self):
        aviso = h("cola-peticiones", severidad="WARN", instancia="cola")
        self.assertFalse(self.decidir([], [aviso]).bloquea)

    def test_json_malformado_falla_cerrado_con_salida(self):
        for campo in ("id", "severidad", "sujeto", "ruta", "instancia"):
            roto = h("pkill")
            roto.pop(campo)
            veredicto = self.decidir([], [roto])
            self.assertTrue(veredicto.bloquea, campo)
            self.assertIn("infraestructura", veredicto.motivo.lower())
            self.assertIn("SALIDA:", veredicto.salida)

    def test_json_con_campos_extra_o_sujeto_malformado_falla_cerrado(self):
        extra = h("pkill")
        extra["texto_humano"] = "no forma parte del contrato"
        for roto in (extra, h("pkill", sujeto="unidad:"),
                     h("pkill", sujeto="unidad:148_ROTO")):
            veredicto = self.decidir([], [roto])
            self.assertTrue(veredicto.bloquea, roto)
            self.assertIn("infraestructura", veredicto.motivo.lower())

    def test_campos_de_identidad_json_no_textuales_fallan_cerrado(self):
        for campo, valor in (("id", 1), ("sujeto", ["taller"]),
                             ("ruta", ["a"]), ("instancia", 0)):
            with self.subTest(campo=campo, valor=valor):
                roto = h("pkill")
                roto[campo] = valor
                # En base y HEAD: si se coerciona, parece preexistente y bloquea=False.
                veredicto = self.decidir([roto], [roto])
                self.assertTrue(veredicto.bloquea, roto)
                self.assertIn("infraestructura", veredicto.motivo.lower())

    def test_ruta_absoluta_windows_falla_cerrado(self):
        veredicto = self.decidir([], [h("pkill", ruta="C:/tmp/a.sh")])
        self.assertTrue(veredicto.bloquea)
        self.assertIn("infraestructura", veredicto.motivo.lower())

    def test_rutas_no_canonicas_fallan_cerrado(self):
        for ruta in ("a//b", "a/./b", "a/"):
            with self.subTest(ruta=ruta):
                veredicto = self.decidir([], [h("pkill", ruta=ruta)])
                self.assertTrue(veredicto.bloquea, ruta)
                self.assertIn("infraestructura", veredicto.motivo.lower())

    def test_registro_de_degradados_no_puede_autoindultar_el_mismo_diff(self):
        # Aunque el pkill haya sido rebajado a WARN, tocar el registro genera antes este
        # hallazgo no degradable y el cierre sigue bloqueado.
        head = [
            h("pkill", severidad="WARN", ruta="main/scripts/dev.sh", instancia="linea:2"),
            h("guardianes-degradados-modificado", ruta="docs/00-metodo/guardianes-degradados.json",
              instancia="contenido-no-vacio"),
        ]
        self.assertTrue(self.decidir([], head).bloquea)

    def test_diente_quitar_la_decision_de_nuevos_reabre_el_caso(self):
        nuevo = h("pkill", ruta="main/scripts/dev.sh", instancia="linea:2")
        original = self.modulo._hallazgos_nuevos
        try:
            self.modulo._hallazgos_nuevos = lambda _base, _head: []
            self.assertFalse(self.decidir([], [nuevo]).bloquea)
        finally:
            self.modulo._hallazgos_nuevos = original
        self.assertTrue(self.decidir([], [nuevo]).bloquea)

    def test_dientes_R_LINT_01_bloquea(self):
        nuevo = h("pkill", ruta="main/scripts/dev.sh", instancia="linea:2")
        self.assertTrue(self.modulo.veredicto_cierre(
            [], [nuevo], "148-rojos-por-sujeto", ["P-20260901-dfd22a99@1"], evidencia()
        ).bloquea)

    def test_dientes_R_LINT_01_abierto_pasa(self):
        nuevo = h("pkill", ruta="main/scripts/dev.sh", instancia="linea:2")
        original = self.modulo._hallazgos_nuevos
        try:
            self.modulo._hallazgos_nuevos = lambda _base, _head: []
            self.assertFalse(self.modulo.veredicto_cierre(
                [], [nuevo], "148-rojos-por-sujeto", ["P-20260901-dfd22a99@1"], evidencia()
            ).bloquea)
        finally:
            self.modulo._hallazgos_nuevos = original


if __name__ == "__main__":
    unittest.main()
