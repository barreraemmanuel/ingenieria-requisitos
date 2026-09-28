"""165: herramientas nativas simuladas, Git real, nunca un proceso IA."""
import argparse
import io
import json
import os
import sys
import subprocess
import re
import tempfile
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "plantilla/docs/00-metodo/scripts"), str(ROOT / "visor/tests/reforma")]
import ejecucion
import entrega
import subagente
import unidad
from taller_reforma import Worktree, git


class NativoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.name = "165-demo"
        self.wt = Worktree(self.root / "worktrees" / self.name, self.name)
        git(self.wt.ruta, "checkout", "-b", self.name)
        self.docs = self.root / "docs/05-trabajo" / self.name
        self.docs.mkdir(parents=True)
        (self.docs / "especificacion.md").write_text(f"---\ncarril: completo\nestado: en_obra\nbase: {self.wt.base_head}\n---\nContrato\n")
        self.h = self.docs / "hallazgos.md"
        self.h.write_text("---\nronda: 1\nrevisado_patch_id: no\n---\n## Plan\n- [ ] tarea\n")
        self.receipts = self.root / ".runtime/ejecuciones"
        for module in (subagente, ejecucion, entrega, unidad):
            for key, value in {"RAIZ": self.root, "EJECUCIONES": self.receipts,
                               "WORKTREES": self.root / "worktrees"}.items():
                if hasattr(module, key):
                    p = mock.patch.object(module, key, value)
                    p.start()
                    self.addCleanup(p.stop)

    def call(self, *args):
        salida = io.StringIO()
        with redirect_stdout(salida):
            resultado = subagente.main(list(args))
        self.last_output = salida.getvalue()
        return resultado

    def prepare(self, role="constructor", platform="codex"):
        # Los revisores sin constructor previo representan el carril directo: el padre
        # construyó; sigue siendo obligatoria una revisión nativa independiente.
        ficha = self.docs / "especificacion.md"
        text = ficha.read_text()
        text = text.replace("carril: completo", "carril: directo") if role == "revisor" else text.replace("carril: directo", "carril: completo")
        ficha.write_text(text)
        self.assertEqual(self.call("preparar", self.name, "--rol", role,
                                  "--plataforma", platform, "--modelo", "modelo-solicitado",
                                  "--pid", str(os.getpid())), 0)
        r = entrega.recibos_de(self.name, self.receipts)[-1]
        self.assertEqual(r["estado_nativo"], "preparado")
        return r

    def bind(self, r, task="child-1", model=None):
        source = self.root / (r["id"] + "-tool.json")
        evidence = {"tool": "collaboration.spawn_agent" if r["plataforma"] == "codex" else "Agent",
                    "native_task_id": task, "parent_session_id": "parent", "contexto": "fresco",
                    "modelo_observado": "declaración ignorada"}
        if model:
            metadata = self.root / (r["id"] + "-metadata.jsonl")
            if r["plataforma"] == "codex":
                events = [{"type": "session_meta", "payload": {"id": "session-child", "source": {"subagent": {"thread_spawn": {"agent_path": task, "parent_thread_id": "parent"}}}}},
                          {"type": "turn_context", "payload": {"model": model, "effort": "high"}}]
            else:
                events = [{"type": "assistant", "agentId": task, "sessionId": "parent", "message": {"model": model}}]
            metadata.write_text("\n".join(json.dumps(e) for e in events))
            evidence["metadata_path"] = str(metadata)
        source.write_text(json.dumps(evidence))
        return self.call("vincular", self.name, "--recibo-id", r["id"], "--rol", r["rol"],
                         "--native-task-id", task, "--evidencia", str(source))

    def finish(self, r, task="child-1", result="ok", role=None):
        return self.call("finalizar", self.name, "--recibo-id", r["id"], "--rol", role or r["rol"],
                         "--native-task-id", task, "--resultado", result, "--motivo", "prueba")

    def write_review(self, task="child-1", detail="Revisión nueva", path=None):
        path = path or self.h
        text = path.read_text(encoding="utf-8")
        for key, value in (("revisor", task + " · modelo"), ("revisado", subagente.ahora()[:10])):
            text = re.sub(r"(?m)^" + key + r":.*\n", "", text)
            text = text.replace("---\n", "---\n" + key + ": " + value + "\n", 1)
        text = re.sub(r"(?ms)^## Revisión[^\n]*\n.*?(?=^## |\Z)", "", text)
        path.write_text(text + "\n## Revisión\n- **Veredicto:** LIMPIO\n- " + detail + "\n", encoding="utf-8")

    def test_R5_cancelado_sin_hijo_no_invalida_revision_valida(self):
        r = self.prepare()
        self.bind(r, model="constructor")
        self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.finish(r), 0)
        review = self.prepare("revisor")
        self.assertEqual(self.bind(review, "review", "revisor"), 0)
        self.write_review("review")
        self.assertEqual(self.finish(review, "review"), 0)
        self.assertEqual(unidad.puerta_recibo_revisor(self.name), ([], []))
        empty = self.prepare()
        self.assertEqual(self.call("cancelar", self.name, "--recibo-id", empty["id"], "--rol", "constructor", "--motivo", "sin hijo"), 0)
        self.assertEqual(unidad.puerta_recibo_revisor(self.name), ([], []))

    def test_R3_revisor_no_puede_reescribir_plan_ni_evidencia(self):
        self.wt.commitear()
        r = self.prepare("revisor")
        self.bind(r, model="revisor")
        self.write_review()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertNotEqual(self.finish(r), 0)
        self.assertNotIn("resultado", json.loads(Path(r["_ruta"]).read_text()))

    def test_R3_aprendizaje_no_atribuye_veredicto_preexistente(self):
        self.wt.commitear()
        self.write_review("antiguo")
        r = self.prepare("revisor")
        self.bind(r, model="revisor")
        self.h.write_text(self.h.read_text() + "\n```aprendizajes-revisor\n- Aprendizaje nuevo\n```\n")
        self.assertNotEqual(self.finish(r), 0)
        self.assertNotIn("resultado", json.loads(Path(r["_ruta"]).read_text()))

    def test_R3_frontera_preserva_evidencia_y_hallazgos_previos(self):
        self.wt.commitear()
        self.h.write_text(self.h.read_text() + "\n## Evidencia\npruebas: 42\n"
                          "\n## Trabajo descubierto\n- Previo del constructor\n- [revisor] Previo de otro revisor\n"
                          "\n## Aprendizajes\n```aprendizajes-constructor\n- Del constructor\n```\n"
                          "```aprendizajes-revisor\n- Anterior\n```\n")
        r = self.prepare("revisor")
        self.bind(r, model="revisor")
        self.write_review()
        valido = self.h.read_text()
        for old, new in (("pruebas: 42", "pruebas: 999"),
                         ("[ ] tarea", "[x] tarea"),
                         ("Previo del constructor", "Reescrito"),
                         ("Previo de otro revisor", "Reescrito"),
                         ("Del constructor", "Reescrito"),
                         ("ronda: 1", "ronda: 2"),
                         ("revisado_patch_id: no", "revisado_patch_id: falsificado"),
                         ("child-1 · modelo", "hijo-ajeno · modelo"),
                         (subagente.ahora()[:10], "2000-01-01")):
            with self.subTest(old=old):
                self.h.write_text(valido.replace(old, new))
                self.assertNotEqual(self.finish(r), 0)
        self.h.write_text(valido.replace("- Previo del constructor", "- Nuevo sin marca\n- Previo del constructor"))
        self.assertNotEqual(self.finish(r), 0)
        self.h.write_text(valido.replace("- Anterior", "- Aprendizaje de esta revisión").replace(
            "## Aprendizajes", "- [revisor] Nuevo hallazgo\n  Evidencia reproducible\n  ```text\n  muestra\n  ```\n\n## Aprendizajes"))
        self.assertEqual(self.finish(r), 0)
        final = json.loads(Path(r["_ruta"]).read_text())
        self.assertEqual(final["informe_revisor_final"]["firma"]["revisor"], "child-1 · modelo")

    def test_R3_evidencia_con_ejemplo_de_revision_sigue_protegida(self):
        for valla, cierre in (("```markdown", "```"), ("~~~markdown", "~~~"),
                              ("```aprendizajes-revisor", "")):
            with self.subTest(valla=valla, cierre=cierre):
                original = "## Evidencia\n" + valla + "\n## Revisión\npruebas: 42\n" + cierre + "\n## Plan\n- [x] tarea\n"
                antes = subagente.partes_informe_revisor(original)[0]
                despues = subagente.partes_informe_revisor(original.replace("42", "999"))[0]
                self.assertNotEqual(antes["protegido"], despues["protegido"])

    def test_R3_firma_nueva_no_reutiliza_revision_anterior(self):
        self.wt.commitear()
        self.write_review("anterior")
        r = self.prepare("revisor")
        self.bind(r, model="revisor")
        self.h.write_text(self.h.read_text().replace("anterior · modelo", "child-1 · modelo"))
        self.assertNotEqual(self.finish(r), 0)
        self.write_review(detail="El nuevo hijo revisó de nuevo los seis criterios")
        self.assertEqual(self.finish(r), 0)

    def test_R3_bug_solo_permite_su_revision_sin_reescribir_cierre(self):
        self.wt.commitear()
        ficha = self.docs / "especificacion.md"
        bug = self.root / "docs/bugs" / (self.name + ".md")
        bug.parent.mkdir(parents=True)
        bug.write_text(ficha.read_text().replace("carril: completo", "carril: directo") +
                       "\n## 6 · Cierre\n- **Revisión (revisor fresco):** pendiente\n"
                       "- Merge del PR: pendiente\n- **Validación del usuario:** PENDIENTE\n")
        ficha.unlink()
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor", "--plataforma", "codex", "--modelo", "r"), 0)
        r = entrega.recibos_de(self.name, self.receipts)[-1]
        self.bind(r, model="revisor")
        text = bug.read_text().replace("---\n", "---\nrevisor: child-1\nrevisado: " + subagente.ahora()[:10] + "\n", 1)
        text = text.replace("** pendiente", "** LIMPIO")
        bug.write_text(text.replace("Merge del PR: pendiente", "Merge del PR: inventado"))
        self.assertNotEqual(self.finish(r), 0)
        bug.write_text(text)
        self.assertEqual(self.finish(r), 0)

    def test_R1_lanzador_retirado_no_invoca_ningun_proceso(self):
        with mock.patch.object(ejecucion.subprocess, "Popen") as popen:
            with mock.patch.object(ejecucion.subprocess, "run") as run:
                with self.assertRaisesRegex(ejecucion.ErrorEjecucion, "subagente.py preparar"):
                    ejecucion.lanzar(argparse.Namespace(unidad=self.name, rol="revisor"))
                popen.assert_not_called()
                run.assert_not_called()

    def test_R2_constructor_id_rol_y_finalizacion_idempotente(self):
        r = self.prepare()
        self.assertEqual(self.bind(r), 0)
        self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertNotEqual(self.finish(r, task="ajeno"), 0)
        self.assertNotEqual(self.finish(r, role="revisor"), 0)
        self.assertEqual(self.finish(r), 0)
        before = Path(r["_ruta"]).read_bytes()
        self.assertEqual(self.finish(r), 0)
        self.assertEqual(Path(r["_ruta"]).read_bytes(), before)
        self.assertNotEqual(self.finish(r, result="fallo"), 0)

    def test_R2_identidad_nativa_no_es_el_cerrojo(self):
        r = self.prepare()
        self.assertNotEqual(self.bind(r, r["lease"]["session_id"]), 0)

    def test_R2_cerrojo_ajeno_no_se_retira(self):
        r = self.prepare()
        self.bind(r)
        manager = subagente.gestion_leases.LeaseManager(self.root)
        manager._release_records(r["lease"]["records"])
        foreign = manager.acquire(r["lease"]["scopes"])
        self.addCleanup(foreign.release)
        self.assertNotEqual(self.finish(r, result="cancelado"), 0)
        foreign.assert_owner()

    def test_R3_revisor_sin_commit_y_con_drift_rechazado(self):
        self.wt.commitear()
        r = self.prepare("revisor")
        self.bind(r, model="modelo-observado")
        head = self.wt.head()
        self.write_review()
        self.assertEqual(self.finish(r), 0)
        self.assertEqual(self.wt.head(), head)
        final = json.loads(Path(r["_ruta"]).read_text())
        self.assertEqual(final["modelo_acreditado"], "modelo-observado")
        self.assertTrue(final["revisado_patch_id"])
        r2 = self.prepare("revisor")
        self.bind(r2, "child-2", "otro")
        self.wt.ensuciar()
        self.assertNotEqual(self.finish(r2, "child-2"), 0)

    def test_R4_declaracion_no_acredita_modelo(self):
        self.wt.commitear()
        r = self.prepare("revisor")
        self.bind(r)
        self.write_review()
        self.assertEqual(self.finish(r), 0)
        final = json.loads(Path(r["_ruta"]).read_text())
        self.assertIsNone(final["modelo_acreditado"])
        self.assertIn("modelo", unidad.acredita_revision(final))

    def test_R5_preparacion_vacia_no_desplaza_entrega(self):
        head = self.wt.commitear()
        old = self.wt.recibo(head=head)
        r = self.prepare()
        problems, _ = entrega.validar_entrega(self.wt.ruta, self.name, [old, r], self.wt.base())
        self.assertEqual(problems, [])
        self.assertEqual(self.call("cancelar", self.name, "--recibo-id", r["id"], "--rol", "constructor", "--motivo", "sin iniciar"), 0)
        empty = entrega.recibos_de(self.name, self.receipts)[-1]
        self.assertEqual(entrega.validar_entrega(self.wt.ruta, self.name, [old, empty], self.wt.base())[0], [])

    def test_R6_todos_roles_ambas_plataformas_y_claude_sincrono(self):
        for platform in ("codex", "claude"):
            for role in ("constructor", "revisor", "investigador", "auditor", "validador"):
                with self.subTest(platform=platform, role=role):
                    r = self.prepare(role, platform)
                    self.assertEqual(self.bind(r, r["id"] + "-native"), 0)
                    self.assertEqual(self.finish(r, r["id"] + "-native", "cancelado"), 0)

    def test_R1_comandos_antiguos_solo_muestran_migracion(self):
        with mock.patch.object(subagente.subprocess, "run") as process:
            self.assertEqual(self.call("abrir", self.name, "--modelo", "viejo"), 2)
            self.assertEqual(self.call("cerrar", self.name), 2)
            process.assert_not_called()

    def test_R2_cancelar_preparado_no_inventa_hijo(self):
        r = self.prepare()
        self.assertEqual(self.call("cancelar", self.name, "--recibo-id", r["id"], "--rol", r["rol"], "--motivo", "sin herramienta"), 0)
        final = json.loads(Path(r["_ruta"]).read_text())
        self.assertIsNone(final["native_task_id"])
        self.assertTrue(final["sin_ejecucion"])

    def test_R3_modelo_repetido_y_contexto_heredado_no_acreditan_revision(self):
        r = self.prepare()
        self.bind(r, model="mismo")
        self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.finish(r)
        review = self.prepare("revisor")
        self.assertNotEqual(self.bind(review, "nuevo", "mismo"), 0)
        self.assertNotEqual(self.bind(review, "child-1", "distinto"), 0)
        source = self.root / "heredado.json"
        source.write_text(json.dumps({"tool": "collaboration.spawn_agent", "native_task_id": "nuevo",
                                      "parent_session_id": "parent", "contexto": "heredado"}))
        self.assertNotEqual(self.call("vincular", self.name, "--recibo-id", review["id"], "--rol", "revisor",
                                     "--native-task-id", "nuevo", "--evidencia", str(source)), 0)

    def test_R3_informe_de_investigador_auditor_validador_no_crea_commit(self):
        for role in ("investigador", "auditor", "validador"):
            r = self.prepare(role)
            self.bind(r, r["id"])
            self.h.write_text(self.h.read_text() + "\nResultado " + role)
            head = self.wt.head()
            self.assertEqual(self.finish(r, r["id"]), 0)
            self.assertEqual(self.wt.head(), head)

    def test_R4_metadata_de_otro_padre_se_rechaza(self):
        source = self.root / "ajeno.jsonl"
        source.write_text(json.dumps({"type": "session_meta", "payload": {"id": "ajena", "source": {"subagent": {"thread_spawn": {"agent_path": "otro", "parent_thread_id": "otro"}}}}}))
        with self.assertRaisesRegex(ValueError, "otro hijo o padre"):
            subagente.observar_metadata({"metadata_path": str(source), "native_task_id": "hijo", "parent_session_id": "padre"}, "codex")

    def test_R5_rondas_gastadas_y_cancelacion_vacia(self):
        self.h.write_text(self.h.read_text() + "\n- **Veredicto:** HUECOS DE CORRECCIÓN\n")
        r = self.prepare()
        self.assertEqual(r["ronda"], 2)
        self.bind(r)
        self.assertEqual(self.finish(r, result="cancelado"), 0)
        self.assertEqual(json.loads(Path(r["_ruta"]).read_text())["ronda"], 1)
        r = self.prepare()
        self.bind(r, "otro")
        self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.finish(r, "otro"), 0)
        self.assertEqual(json.loads(Path(r["_ruta"]).read_text())["ronda"], 2)
        self.assertNotEqual(self.call("preparar", self.name, "--rol", "constructor", "--plataforma", "codex", "--modelo", "m"), 0)

    def test_R5_rebase_equivalente_conserva_ancla_del_revisor(self):
        self.wt.commitear()
        r = self.prepare("revisor")
        self.bind(r, model="revisor")
        self.write_review()
        self.assertEqual(self.finish(r), 0)
        before = r["revisado_patch_id"]
        git(self.wt.ruta, "checkout", "main")
        (self.wt.ruta / "otro.txt").write_text("independiente")
        git(self.wt.ruta, "add", "otro.txt")
        git(self.wt.ruta, "commit", "-m", "avance main")
        git(self.wt.ruta, "checkout", self.name)
        git(self.wt.ruta, "rebase", "main")
        self.assertEqual(ejecucion.patch_id_de_la_rama(self.wt.ruta), before)

    def test_R6_documental_true_sin_worktree_termina_informe(self):
        main = self.root / "main"
        self.wt.ruta.rename(main)
        ficha = self.docs / "especificacion.md"
        ficha.write_text(ficha.read_text().replace("estado: en_obra", "estado: en_obra\ndocumental: true"))
        for role in ("investigador", "auditor", "validador"):
            r = self.prepare(role)
            self.assertEqual(Path(r["cwd"]), main)
            self.bind(r, r["id"], model="observado")
            self.h.write_text(self.h.read_text() + "\nInforme " + role)
            self.assertEqual(self.finish(r, r["id"]), 0)


    def test_R3_revisor_exige_entrega_constructor_en_carril_completo(self):
        self.wt.commitear()
        self.assertNotEqual(self.call("preparar", self.name, "--rol", "revisor", "--plataforma", "codex", "--modelo", "m"), 0)
        self.assertEqual(entrega.recibos_de(self.name, self.receipts), [])

    def test_R1_trabajo_anterior_se_acredita_con_git_y_llega_al_revisor(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        recibos = entrega.recibos_de(self.name, self.receipts)
        self.assertEqual(entrega.validar_entrega(self.wt.ruta, self.name, recibos, self.wt.base())[0], [])
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor",
                                   "--plataforma", "codex", "--modelo", "r"), 0)

    def test_R2_recuperacion_y_revision_fresca_llegan_a_consumidores_de_cierre(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        self.assertTrue(unidad.puerta_recibo_revisor(self.name)[0])
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor",
                                   "--plataforma", "codex", "--modelo", "r"), 0)
        review = entrega.recibos_de(self.name, self.receipts)[-1]
        self.assertEqual(self.bind(review, "review-git", "revisor"), 0)
        self.write_review("review-git")
        self.assertEqual(self.finish(review, "review-git"), 0, self.last_output)
        self.assertEqual(unidad.puerta_recibo_revisor(self.name)[0], [])
        ruta_review = Path(review["_ruta"])
        bytes_review = ruta_review.read_bytes()
        ajeno = json.loads(bytes_review)
        ajeno["unidad"] = "999-otra"
        ruta_review.write_text(json.dumps(ajeno), encoding="utf-8")
        self.assertTrue(unidad.puerta_recibo_revisor(self.name)[0])
        ruta_review.write_bytes(bytes_review)
        signed = unidad.frontmatter(self.h)["revisado_patch_id"]
        self.assertIsNone(unidad.puerta_ancla_de_revision(self.wt.ruta, self.name,
                                                           signed, self.wt.base_head, head)[0])
        git(self.wt.ruta, "checkout", "main")
        git(self.wt.ruta, "merge", "--ff-only", self.name)
        git(self.wt.ruta, "checkout", self.name)
        self.assertTrue(unidad.rama_mergeada(self.wt.ruta, self.name, "main", head)[0])
        self.assertFalse(unidad.rama_mergeada(self.wt.ruta, self.name, "main", "esto-no-es-un-sha")[0])
        self.assertFalse(unidad.rama_mergeada(self.wt.ruta, self.name, "main", self.wt.base_head)[0])

    def test_R4_recuperacion_rechaza_base_ajena_arbol_ajeno_y_mutacion_posterior(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        git(self.wt.ruta, "checkout", "main")
        (self.wt.ruta / "ajeno.txt").write_text("ajeno")
        git(self.wt.ruta, "add", "ajeno.txt")
        git(self.wt.ruta, "commit", "-m", "ajeno")
        ajeno = git(self.wt.ruta, "rev-parse", "HEAD").strip()
        git(self.wt.ruta, "checkout", self.name)
        blob = git(self.wt.ruta, "hash-object", "modulo.py").strip()
        for invalido in ("0" * 40, blob):
            with self.subTest(commit=invalido):
                self.assertNotEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                               "--commit", invalido), 0)
        self.assertNotEqual(self.call("acreditar-git", self.name, "--base", ajeno,
                                       "--commit", head), 0)
        self.assertNotEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                       "--commit", ajeno), 0)
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        recibo = entrega.recibos_de(self.name, self.receipts)[-1]
        datos = json.loads(Path(recibo["_ruta"]).read_text())
        datos["recuperacion"]["tree"] = "0" * 40
        self.assertTrue(entrega.validar_entrega(self.wt.ruta, self.name, [datos], self.wt.base())[0])
        (self.wt.ruta / "cambio.txt").write_text("solo espacios  \n")
        git(self.wt.ruta, "add", "cambio.txt")
        git(self.wt.ruta, "commit", "-m", "cambio posterior")
        self.assertTrue(entrega.validar_entrega(self.wt.ruta, self.name,
                                                 entrega.recibos_de(self.name, self.receipts),
                                                 self.wt.base())[0])

    def test_R2_correccion_conserva_recibo_y_exige_revision_nueva(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        primero = next(r for r in entrega.recibos_de(self.name, self.receipts)
                       if r.get("schema") == "entrega-git/v1")
        bytes_primero = Path(primero["_ruta"]).read_bytes()
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor",
                                   "--plataforma", "codex", "--modelo", "r"), 0)
        review = entrega.recibos_de(self.name, self.receipts)[-1]
        self.bind(review, "review-1", "revisor")
        self.write_review("review-1")
        self.assertEqual(self.finish(review, "review-1"), 0, self.last_output)
        nuevo = self.wt.commitear("corrección nueva")
        self.assertTrue(entrega.validar_entrega(self.wt.ruta, self.name,
                                                 entrega.recibos_de(self.name, self.receipts),
                                                 self.wt.base())[0])
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", nuevo), 0, self.last_output)
        self.assertEqual(Path(primero["_ruta"]).read_bytes(), bytes_primero)
        self.assertTrue(unidad.puerta_recibo_revisor(self.name)[0])
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor",
                                   "--plataforma", "codex", "--modelo", "r"), 0)
        review2 = entrega.recibos_de(self.name, self.receipts)[-1]
        self.bind(review2, "review-2", "revisor")
        self.write_review("review-2", "Corrección revisada sobre el árbol nuevo")
        self.assertEqual(self.finish(review2, "review-2"), 0, self.last_output)
        self.assertEqual(unidad.puerta_recibo_revisor(self.name)[0], [])

    def test_R4_espacios_cambian_arbol_aunque_patch_id_persista(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        patch_antes = ejecucion.patch_id_de_la_rama(self.wt.ruta, self.wt.base_head)
        modulo = self.wt.ruta / "modulo.py"
        modulo.write_text(modulo.read_text(encoding="utf-8").replace("print(", "print(  "), encoding="utf-8")
        git(self.wt.ruta, "add", "modulo.py")
        git(self.wt.ruta, "commit", "-m", "solo espacios")
        self.assertEqual(ejecucion.patch_id_de_la_rama(self.wt.ruta, self.wt.base_head), patch_antes)
        self.assertTrue(entrega.validar_entrega(self.wt.ruta, self.name,
                                                 entrega.recibos_de(self.name, self.receipts),
                                                 self.wt.base())[0])
        self.assertIsNotNone(unidad.puerta_ancla_de_revision(
            self.wt.ruta, self.name, patch_antes, self.wt.base_head, self.wt.head())[0])

    def test_R5_recuperacion_persiste_tras_retirar_worktree_fusionado(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        git(self.wt.ruta, "checkout", "main")
        git(self.wt.ruta, "merge", "--ff-only", self.name)
        self.wt.ruta.rename(self.root / "main")
        self.assertEqual(entrega.exigir_entrega_constructor(self.name)[0], [])
        git(self.root / "main", "branch", "-d", self.name)
        self.assertTrue(unidad.rama_mergeada(self.root / "main", self.name, "main")[0])
        self.assertFalse(unidad.rama_mergeada(self.root / "main", self.name,
                                               "main", "esto-no-es-un-sha")[0])

    def test_R3_recuperacion_no_acepta_commit_vacio_con_nombre_de_unidad(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        git(self.wt.ruta, "checkout", "main")
        git(self.wt.ruta, "commit", "--allow-empty", "-m", "Preparar " + self.name)
        git(self.wt.ruta, "checkout", self.name)
        self.assertFalse(unidad.rama_mergeada(self.wt.ruta, self.name, "main")[0])

    def test_R3_base_de_rama_borrada_no_es_fusion_de_trabajo(self):
        self.wt.commitear("trabajo perdido")
        git(self.wt.ruta, "checkout", "main")
        git(self.wt.ruta, "branch", "-D", self.name)
        self.assertFalse(unidad.rama_mergeada(self.wt.ruta, self.name,
                                               "main", self.wt.base_head)[0])

    def test_R3_base_con_padre_no_acredita_rama_borrada(self):
        git(self.wt.ruta, "checkout", "main")
        (self.wt.ruta / "base-adicional.txt").write_text("preexistente", encoding="utf-8")
        git(self.wt.ruta, "add", "base-adicional.txt")
        git(self.wt.ruta, "commit", "-m", "base real no raíz")
        base = git(self.wt.ruta, "rev-parse", "HEAD").strip()
        ficha = self.docs / "especificacion.md"
        ficha.write_text(ficha.read_text().replace(self.wt.base_head, base), encoding="utf-8")
        git(self.wt.ruta, "checkout", self.name)
        git(self.wt.ruta, "merge", "--ff-only", "main")
        head = self.wt.commitear("trabajo que no entra en main")
        git(self.wt.ruta, "checkout", "main")
        git(self.wt.ruta, "branch", "-D", self.name)
        self.assertNotEqual(base, head)
        self.assertFalse(unidad.rama_mergeada(self.wt.ruta, self.name, "main", base)[0])

    def test_R3_rama_borrada_fusionada_con_base_no_raiz_exige_testigo_git(self):
        git(self.wt.ruta, "checkout", "main")
        (self.wt.ruta / "base-adicional.txt").write_text("preexistente", encoding="utf-8")
        git(self.wt.ruta, "add", "base-adicional.txt")
        git(self.wt.ruta, "commit", "-m", "base real no raíz")
        git(self.wt.ruta, "checkout", self.name)
        git(self.wt.ruta, "merge", "--ff-only", "main")
        head = self.wt.commitear("trabajo entregado")
        git(self.wt.ruta, "checkout", "main")
        git(self.wt.ruta, "merge", "--ff-only", self.name)
        git(self.wt.ruta, "branch", "-d", self.name)
        self.assertTrue(unidad.rama_mergeada(self.wt.ruta, self.name, "main", head)[0])
        git(self.wt.ruta, "reflog", "expire", "--expire=now", "--all")
        self.assertFalse(unidad.rama_mergeada(self.wt.ruta, self.name, "main", head)[0])

    def test_R2_nativo_posterior_sustituye_recuperacion_antigua_en_cierre(self):
        head = self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.call("acreditar-git", self.name, "--base", self.wt.base_head,
                                   "--commit", head), 0)
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor",
                                   "--plataforma", "codex", "--modelo", "review"), 0)
        review = entrega.recibos_de(self.name, self.receipts)[-1]
        self.bind(review, "review-A", "review")
        self.write_review("review-A")
        self.assertEqual(self.finish(review, "review-A"), 0, self.last_output)
        self.h.write_text(self.h.read_text() + "\n## Otra tarea\n- [ ] corrección\n")
        builder = self.prepare()
        self.bind(builder, "builder-B", "builder")
        self.wt.commitear("corrección nativa B")
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.finish(builder, "builder-B"), 0, self.last_output)
        self.assertEqual(entrega.exigir_entrega_constructor(self.name)[0], [])
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor",
                                   "--plataforma", "codex", "--modelo", "review"), 0)
        review_b = entrega.recibos_de(self.name, self.receipts)[-1]
        self.bind(review_b, "review-B", "review")
        self.write_review("review-B", "Corrección B revisada")
        self.assertEqual(self.finish(review_b, "review-B"), 0, self.last_output)
        self.assertEqual(unidad.puerta_recibo_revisor(self.name)[0], [])
        signed = unidad.frontmatter(self.h)["revisado_patch_id"]
        self.assertIsNone(unidad.puerta_ancla_de_revision(
            self.wt.ruta, self.name, signed, self.wt.base_head, self.wt.head())[0])

    def test_R5_recuperacion_no_roba_cerrojo_ajeno(self):
        r = self.prepare()
        self.bind(r)
        manager = subagente.gestion_leases.LeaseManager(self.root)
        manager._release_records(r["lease"]["records"])
        foreign = manager.acquire(r["lease"]["scopes"])
        self.addCleanup(foreign.release)
        args = ("recuperar", self.name, "--recibo-id", r["id"], "--rol", "constructor", "--motivo", "padre muerto; hijo comprobado")
        self.assertNotEqual(self.call(*args), 0)
        with mock.patch.object(subagente.gestion_leases.LeaseManager, "_owner_alive", side_effect=lambda owner: owner.get("session_id") != r["lease"]["session_id"]):
            self.assertEqual(self.call(*args), 0)
        foreign.assert_owner()
        self.assertEqual(json.loads(Path(r["_ruta"]).read_text())["resultado"], "fallo")

    def test_R5_revision_entregada_sin_worktree_crea_y_retira_efimero(self):
        head = self.wt.commitear()
        main = self.root / "main"
        self.wt.ruta.rename(main)
        ficha = self.docs / "especificacion.md"
        ficha.write_text(ficha.read_text().replace("estado: en_obra", "estado: mergeada\nfusion: " + head))
        r = self.prepare("revisor")
        self.assertTrue(r["worktree_efimero"])
        self.assertTrue(Path(r["cwd"]).is_dir())
        self.bind(r, model="observado")
        self.write_review()
        self.assertEqual(self.finish(r), 0)
        self.assertFalse(Path(r["cwd"]).exists())


    def test_R2_evidencia_alterada_rechazada_antes_de_materializar(self):
        r = self.prepare()
        self.bind(r)
        self.wt.ensuciar()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        final = json.loads(Path(r["_ruta"]).read_text())
        Path(final["evidencia_nativa"]["ruta"]).write_text("{}")
        with mock.patch.object(entrega, "materializar_commit") as commit:
            self.assertNotEqual(self.finish(r), 0)
            commit.assert_not_called()
        self.assertNotIn("resultado", json.loads(Path(r["_ruta"]).read_text()))

    def test_R2_dos_finalizaciones_concurrentes_materializan_una_entrega(self):
        r = self.prepare()
        self.bind(r)
        self.wt.ensuciar()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        cmd = [sys.executable, str(ROOT / "plantilla/docs/00-metodo/scripts/subagente.py"), "--workspace", str(self.root),
               "finalizar", self.name, "--recibo-id", r["id"], "--native-task-id", "child-1", "--rol", "constructor"]
        children = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for child in children:
            child.communicate(timeout=30)
        self.assertIn(0, [child.returncode for child in children])
        refs = git(self.wt.ruta, "for-each-ref", "--format=%(refname)", "refs/entregas/").splitlines()
        self.assertEqual(len(refs), 1)
        self.assertEqual(self.finish(r), 0)


    def test_R5_entrega_nativa_sobrevive_rebase_equivalente(self):
        r = self.prepare()
        self.bind(r)
        self.wt.commitear()
        self.h.write_text(self.h.read_text().replace("[ ]", "[x]"))
        self.assertEqual(self.finish(r), 0)
        git(self.wt.ruta, "checkout", "main")
        (self.wt.ruta / "ajeno.txt").write_text("avance independiente")
        git(self.wt.ruta, "add", "ajeno.txt")
        git(self.wt.ruta, "commit", "-m", "avance base")
        git(self.wt.ruta, "checkout", self.name)
        git(self.wt.ruta, "rebase", "main")
        receipts = entrega.recibos_de(self.name, self.receipts)
        self.assertEqual(entrega.validar_entrega(self.wt.ruta, self.name, receipts, self.wt.base())[0], [])
        self.wt.commitear("cambio posterior real")
        self.assertTrue(entrega.validar_entrega(self.wt.ruta, self.name, receipts, self.wt.base())[0])

    def test_R3_revisor_bug_preserva_contrato_y_no_depende_de_otro_bug(self):
        self.wt.commitear()
        ficha = self.docs / "especificacion.md"
        bug = self.root / "docs/bugs" / (self.name + ".md")
        bug.parent.mkdir(parents=True)
        bug.write_text(ficha.read_text().replace("carril: completo", "carril: directo") + "\n## 6 · Cierre\n")
        ficha.unlink()
        self.assertEqual(self.call("preparar", self.name, "--rol", "revisor", "--plataforma", "claude", "--modelo", "r"), 0)
        r = entrega.recibos_de(self.name, self.receipts)[-1]
        self.bind(r, model="observado")
        (bug.parent / "999-otro.md").write_text("Otro agente trabaja independiente")
        self.write_review(path=bug)
        self.assertEqual(self.finish(r), 0)


    def test_R3_puerta_de_revision_exige_ronda_del_recibo(self):
        self.wt.commitear()
        r = self.prepare("revisor")
        self.bind(r, model="revisor-observado")
        self.write_review()
        self.assertEqual(self.finish(r), 0)
        self.assertEqual(unidad.puerta_recibo_revisor(self.name)[0], [])
        self.h.write_text(self.h.read_text().replace("ronda: 1", "ronda: 2"))
        self.assertTrue(unidad.puerta_recibo_revisor(self.name)[0])


    def test_R5_cancelacion_sin_rollout_ni_worktree_no_inventa_snapshot(self):
        r = self.prepare()
        self.bind(r, model="observado")
        (self.root / (r["id"] + "-metadata.jsonl")).unlink()
        shutil.rmtree(self.wt.ruta)
        self.assertEqual(self.finish(r, result="cancelado"), 0)
        final = json.loads(Path(r["_ruta"]).read_text())
        self.assertEqual(final["git"]["final"], {})
        self.assertEqual(final["resultado"], "cancelado")


    def test_R6_tablero_no_confunde_preparado_con_vivo_o_terminado(self):
        from visor_tablero import estado
        r = self.prepare()
        tablero = estado.agentes(self.root)
        self.assertEqual(tablero["vivos"], [])
        self.assertEqual(tablero["terminados_hoy"], [])
        self.assertEqual(len(tablero["preparados"]), 1)
        self.assertIn("preparada", unidad._subagente_de(self.name))
        self.bind(r)
        self.assertIn("sin acreditar", unidad._subagente_de(self.name))
        self.assertEqual(len(estado.agentes(self.root)["vivos"]), 1)
        self.assertEqual(self.finish(r, result="cancelado"), 0)
        self.assertEqual(len(estado.agentes(self.root)["terminados_hoy"]), 1)



if __name__ == "__main__":
    unittest.main()
