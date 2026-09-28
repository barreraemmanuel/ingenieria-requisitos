"""Contrato de uso local, consentimiento y recepción HTTP en loopback."""
import contextlib
import base64
import hashlib
import http.server
import http.client
import importlib.util
import importlib
import io
import json
import socket
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest import mock
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "plantilla/docs/00-metodo/scripts/telemetria.py"
PETICION = ROOT / "plantilla/docs/00-metodo/scripts/peticion.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def cargar():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("telemetria_153", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Receptor(http.server.BaseHTTPRequestHandler):
    requests = []
    observed = []
    digest_correcto = True
    status_code = 200

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.requests.append(body)
        self.observed.append({"method": self.command, "path": self.path,
                              "host": self.headers["Host"], "body": body})
        digest = hashlib.sha256(body).hexdigest()
        self.send_response(self.status_code)
        if self.status_code == 302:
            self.send_header("Location", "http://127.0.0.1:1/otro")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"sha256": digest if self.digest_correcto else "0" * 64}).encode())

    def log_message(self, *_args):
        pass


class TelemetriaUso(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.mod = cargar()

    def evento(self, **extra):
        value = {"schema": "telemetria-uso-v1", "id": str(uuid.uuid4()),
                 "timestamp": "2026-09-28T12:00:00Z", "accion": "capturar", "resultado": "ok"}
        value.update(extra)
        path = self.repo / ".runtime/telemetria/eventos.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        return value

    @contextlib.contextmanager
    def receptor(self):
        Receptor.requests = []
        Receptor.observed = []
        Receptor.digest_correcto = True
        Receptor.status_code = 200
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Receptor)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/uso"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_registro_y_consulta_peticion_real(self):
        peticion = importlib.import_module("peticion")
        with (mock.patch.object(peticion, "RAIZ", self.repo),
              mock.patch.object(peticion, "PETICIONES", self.repo / "docs/05-trabajo/peticiones"),
              mock.patch.object(peticion, "LOCKS", self.repo / ".runtime/locks"),
              mock.patch.object(sys, "argv", ["peticion.py", "capturar", "--resumen", "Prueba",
                                             "--texto", "privado clienteAcme", "--autor", "sintetico"]),
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(peticion.main(), 0)
            with mock.patch.object(sys, "argv", ["peticion.py", "listar"]):
                self.assertEqual(peticion.main(), 0)
            with mock.patch.object(sys, "argv", ["peticion.py", "aclarar", "P-20260928-deadbeef",
                                                 "--texto", "fallo", "--autor", "sintetico"]), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(peticion.main(), 1)
            with mock.patch.object(sys, "argv", ["peticion.py", "estado", "P-20260928-deadbeef"]), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(peticion.main(), 1)
            with mock.patch.object(sys, "argv", ["peticion.py", "capturar"]), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                peticion.main()
            with mock.patch("telemetria.registrar", side_effect=OSError("private failure")), \
                 mock.patch.object(sys, "argv", ["peticion.py", "capturar", "--resumen", "Otra",
                                                 "--texto", "privado", "--autor", "sintetico"]), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(peticion.main(), 0)
        rows = self.mod.listar_eventos(self.repo)
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), {"schema", "id", "timestamp", "accion", "resultado"})
        self.assertEqual([(x["accion"], x["resultado"]) for x in rows],
                         [("capturar", "ok"), ("aclarar", "error")])
        self.assertEqual(subprocess.run([sys.executable, "-X", "utf8", "-B", str(PETICION), "--help"],
                                        capture_output=True, creationflags=NO_WINDOW).returncode, 0)

    def test_cien_contaminados_se_proyectan_en_orden(self):
        secret = "clienteAcme maría@example.com ghp_" + "a" * 25 + " C:\\Users\\clienteAcme /home/clienteAcme"
        rows = [self.evento(nota=secret) for _ in range(100)]
        ids = [row["id"] for row in reversed(rows)]
        with self.receptor() as url:
            prepared = self.mod.preparar(self.repo, ids, url)
            body = prepared["cuerpo"]
            self.assertNotIn(secret.encode(), body)
            self.assertNotIn(b"clienteAcme", body)
            self.assertNotIn(b"ghp_", body)
            self.assertEqual([x["id"] for x in json.loads(body)["eventos"]], ids)
            self.assertEqual(prepared["omitidos"], 100)
            self.assertEqual(prepared["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(body, json.dumps(json.loads(body), ensure_ascii=False,
                                              sort_keys=True, separators=(",", ":"),
                                              allow_nan=False).encode())
            self.assertEqual(Receptor.requests, [])

    def test_listar_preparar_y_archivos_no_guardan_campos_privados(self):
        secret = "clienteAcme maría@example.com C:\\Users\\clienteAcme"
        row = self.evento(detalle=secret)
        with self.receptor() as url:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(self.mod.main(["--repo", str(self.repo), "listar"]), 0)
                self.assertEqual(self.mod.main(["--repo", str(self.repo), "preparar",
                                                "--id", row["id"], "--destino", url]), 0)
            self.assertNotIn(secret, out.getvalue())
            self.assertNotIn("clienteAcme", out.getvalue())
            files = list((self.repo / ".runtime/telemetria/lotes").glob("*"))
            self.assertEqual(len(files), 2)
            for path in files:
                self.assertNotIn("clienteAcme", path.read_text(encoding="utf-8"))

    def test_ids_y_origen_invalidos_bloquean(self):
        row = self.evento()
        with self.receptor() as url:
            for ids in ([], [row["id"][:8]], [row["id"], row["id"]], [str(uuid.uuid4())]):
                with self.subTest(ids=ids), self.assertRaises(ValueError):
                    self.mod.preparar(self.repo, ids, url)
            self.evento(accion="clienteAcme")
            with self.assertRaises(ValueError):
                self.mod.preparar(self.repo, [row["id"]], url)
            with (self.repo / ".runtime/telemetria/eventos.jsonl").open("a") as file:
                file.write("{broken}\n")
            with self.assertRaises(ValueError):
                self.mod.preparar(self.repo, [row["id"]], url)
            self.assertEqual(Receptor.requests, [])

    def test_consentimiento_guarda_y_http_real(self):
        row = self.evento()
        with self.receptor() as url:
            prepared = self.mod.preparar(self.repo, [row["id"]], url)
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, prepared["sha256"], "rechazo", "sintetico")
            self.assertEqual(Receptor.requests, [])
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, "0" * 64, "si", "sintetico")
            self.assertEqual(Receptor.requests, [])
            result = self.mod.confirmar(self.repo, prepared["sha256"], "si", "sintetico")
            self.assertEqual(result["estado"], "compartido")
            self.assertEqual(Receptor.requests, [prepared["cuerpo"]])
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, prepared["sha256"], "si", "sintetico")
            self.assertEqual(len(Receptor.requests), 1)

    def test_cambio_origen_y_reserva_interrumpida(self):
        row = self.evento()
        with self.receptor() as url:
            prepared = self.mod.preparar(self.repo, [row["id"]], url)
            self.evento()
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, prepared["sha256"], "si", "sintetico")
            self.assertEqual(Receptor.requests, [])
            newer = self.mod.preparar(self.repo, [row["id"]], url)
            self.mod.reservar(self.repo, newer["sha256"], "sintetico")
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, newer["sha256"], "si", "sintetico")
            self.assertEqual(Receptor.requests, [])

    def test_reserva_exclusiva_simultanea(self):
        row = self.evento()
        with self.receptor() as url:
            prepared = self.mod.preparar(self.repo, [row["id"]], url)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.mod.reservar, self.repo, prepared["sha256"],
                                       "sintetico") for _ in range(2)]
            outcomes = [f.exception() for f in futures]
            self.assertEqual(sum(x is None for x in outcomes), 1)
            self.assertEqual(sum(isinstance(x, ValueError) for x in outcomes), 1)
            self.assertEqual(Receptor.requests, [])

    def test_destinos_y_confirmacion_invalida(self):
        row = self.evento()
        for url in ("http://localhost:5/", "https://127.0.0.1:5/", "http://example.com/",
                    "http://127.0.0.2:5/", " http://127.0.0.1:5/",
                    "http://127.0.0.1:5/#x", "http://u:p@127.0.0.1:5/",
                    "http://127.0.0.1:5/\r\nX: y", "http://127.0.0.1:5/uso?token=secreto"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.mod.preparar(self.repo, [row["id"]], url)
        with self.receptor() as url:
            p = self.mod.preparar(self.repo, [row["id"]], url)
            Receptor.digest_correcto = False
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, p["sha256"], "si", "sintetico")
            self.assertEqual(len(Receptor.requests), 1)
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, p["sha256"], "si", "sintetico")
            self.assertEqual(len(Receptor.requests), 1)
        # 302 tampoco se sigue, aunque el servidor anuncie otra URL.
        with self.receptor() as url:
            row2 = self.evento()
            p2 = self.mod.preparar(self.repo, [row["id"], row2["id"]], url)
            Receptor.status_code = 302
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, p2["sha256"], "si", "sintetico")
            self.assertEqual(len(Receptor.requests), 1)

    def test_reconciliacion_local_exige_recibo_observado_exacto(self):
        row = self.evento()
        with self.receptor() as url:
            prepared = self.mod.preparar(self.repo, [row["id"]], url)
            self.mod.reservar(self.repo, prepared["sha256"], "sintetico")
            receipt = self.repo / "observado.json"
            observed = {"schema": "telemetria-recepcion-observada-v1", "metodo": "POST",
                        "http_status": 200, "sha256": prepared["sha256"], "destino": url,
                        "cuerpo_base64": base64.b64encode(prepared["cuerpo"]).decode()}
            receipt.write_text(json.dumps({**observed, "destino": url + "otro"}))
            with self.assertRaises(ValueError):
                self.mod.reconciliar(self.repo, prepared["sha256"], receipt)
            self.assertEqual(Receptor.requests, [])
            receipt.write_text(json.dumps({**observed, "cuerpo_base64": "!!!"}))
            with self.assertRaises(ValueError):
                self.mod.reconciliar(self.repo, prepared["sha256"], receipt)
            receipt.write_text(json.dumps({**observed, "http_status": 302}))
            with self.assertRaises(ValueError):
                self.mod.reconciliar(self.repo, prepared["sha256"], receipt)
            # El harness conserva lo que recibió el servidor tras una reserva
            # previa a la caída; reconciliar sólo lee este recibo local.
            connection = http.client.HTTPConnection("127.0.0.1", int(url.split(":")[2].split("/")[0]))
            connection.request("POST", "/uso", body=prepared["cuerpo"])
            response = connection.getresponse()
            status = response.status
            reported = json.loads(response.read())["sha256"]
            connection.close()
            self.assertEqual(Receptor.requests, [prepared["cuerpo"]])
            captured = Receptor.observed[0]
            self.assertEqual((captured["method"], captured["path"], status), ("POST", "/uso", 200))
            self.assertEqual(captured["body"], prepared["cuerpo"])
            self.assertEqual(reported, hashlib.sha256(captured["body"]).hexdigest())
            observed = {"schema": "telemetria-recepcion-observada-v1", "metodo": captured["method"],
                        "http_status": status, "sha256": reported,
                        "destino": "http://" + captured["host"] + captured["path"],
                        "cuerpo_base64": base64.b64encode(captured["body"]).decode()}
            self.assertEqual(observed["destino"], url)
            receipt.write_text(json.dumps(observed))
            result = self.mod.reconciliar(self.repo, prepared["sha256"], receipt)
            self.assertEqual(result["estado"], "compartido")
            self.assertEqual(result["origen"], "recibo-observado")
            with self.assertRaises(ValueError):
                self.mod.confirmar(self.repo, prepared["sha256"], "si", "sintetico")
            self.assertEqual(Receptor.requests, [prepared["cuerpo"]])

    def test_reconciliar_rechaza_metadata_y_reserva_inconsistentes(self):
        row = self.evento()
        source = self.repo / ".runtime/telemetria/eventos.jsonl"
        first = "http://127.0.0.1:1/first"
        second = "http://127.0.0.1:2/second"
        cases = (
            ("meta-destino", "meta", "destino", second),
            ("meta-sha", "meta", "sha256", "0" * 64),
            ("meta-ids", "meta", "ids", [str(uuid.uuid4())]),
            ("meta-ids-ausentes", "meta", "ids", None),
            ("meta-schema", "meta", "schema", "otro"),
            ("reserva-destino", "reserva", "destino", second),
            ("reserva-destino-ausente", "reserva", "destino", None),
            ("reserva-sha", "reserva", "sha256", "0" * 64),
            ("reserva-schema", "reserva", "schema", "otro"),
            ("observado-sha", "observado", "sha256", "0" * 64),
            ("observado-destino-ausente", "observado", "destino", None),
        )
        for name, which, key, value in cases:
            with self.subTest(name=name):
                repo = self.repo / name
                target = repo / ".runtime/telemetria/eventos.jsonl"
                target.parent.mkdir(parents=True)
                shutil.copyfile(source, target)
                prepared = self.mod.preparar(repo, [row["id"]], first)
                self.mod.reservar(repo, prepared["sha256"], "sintetico")
                _, meta_path, reserve_path, receipt_path = self.mod._paths(repo, prepared["sha256"])
                if which != "observado":
                    path = meta_path if which == "meta" else reserve_path
                    state = json.loads(path.read_bytes())
                    if value is None:
                        state.pop(key)
                    else:
                        state[key] = value
                    path.write_text(json.dumps(state), encoding="utf-8")
                # Prueba adversarial incompleta; no hubo HTTP. El destino
                # observado acompaña la metadata alterada en el caso crítico.
                observed = {"schema": "telemetria-recepcion-observada-v1", "metodo": "POST",
                            "http_status": 200, "sha256": prepared["sha256"],
                            "destino": second if name == "meta-destino" else first,
                            "cuerpo_base64": base64.b64encode(prepared["cuerpo"]).decode()}
                if which == "observado":
                    if value is None:
                        observed.pop(key)
                    else:
                        observed[key] = value
                observed_path = repo / "observado.json"
                observed_path.write_text(json.dumps(observed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.mod.reconciliar(repo, prepared["sha256"], observed_path)
                self.assertFalse(receipt_path.exists())

    def test_reconciliar_rechaza_cuerpo_no_canonico_o_esquema_ajeno(self):
        row = self.evento()
        first = "http://127.0.0.1:1/first"
        prepared = self.mod.preparar(self.repo, [row["id"]], first)
        self.mod.reservar(self.repo, prepared["sha256"], "sintetico")
        original_meta = json.loads(self.mod._paths(self.repo, prepared["sha256"])[1].read_bytes())
        original_reserve = json.loads(self.mod._paths(self.repo, prepared["sha256"])[2].read_bytes())
        for name, body in (
            ("no-canonico", json.dumps(json.loads(prepared["cuerpo"]), indent=2).encode()),
            ("esquema-ajeno", self.mod._canon({**json.loads(prepared["cuerpo"]), "schema": "otro"})),
            ("campo-privado", self.mod._canon({**json.loads(prepared["cuerpo"]), "secreto": "clienteAcme"})),
        ):
            with self.subTest(name=name):
                repo = self.repo / name
                digest = hashlib.sha256(body).hexdigest()
                body_path, meta_path, reserve_path, receipt_path = self.mod._paths(repo, digest)
                body_path.parent.mkdir(parents=True)
                reserve_path.parent.mkdir(parents=True)
                body_path.write_bytes(body)
                meta_path.write_text(json.dumps({**original_meta, "sha256": digest}), encoding="utf-8")
                reserve_path.write_text(json.dumps({**original_reserve, "sha256": digest}), encoding="utf-8")
                observed_path = repo / "observado.json"
                observed_path.write_text(json.dumps({
                    "schema": "telemetria-recepcion-observada-v1", "metodo": "POST", "http_status": 200,
                    "sha256": digest, "destino": first, "cuerpo_base64": base64.b64encode(body).decode(),
                }), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.mod.reconciliar(repo, digest, observed_path)
                self.assertFalse(receipt_path.exists())

    def test_bootstrap_inventario(self):
        from visor import bootstrap
        self.assertIn("scripts/telemetria.py", bootstrap.ARCHIVOS_METODO)

    def test_bootstrap_nuevo_y_modo_d_real(self):
        source = self.repo / "planos"
        source.mkdir()
        shutil.copyfile(ROOT / "visor/ejemplo.json", source / "planos.json")
        ws = self.repo / "nuevo-agents"
        env = os.environ.copy()
        env["INGENIERIA_REQUISITOS_REGISTRO"] = str(self.repo / "registro.json")
        def run(*args):
            return subprocess.run([sys.executable, "-X", "utf8", "-B", *map(str, args)],
                                  cwd=ROOT, env=env, capture_output=True, text=True,
                                  encoding="utf-8", timeout=90, creationflags=NO_WINDOW)
        boot = run(ROOT / "visor/bootstrap.py", "--planos", source, "--destino", ws,
                   "--tipo", "otro", "--compilar")
        self.assertEqual(boot.returncode, 0, boot.stdout + boot.stderr)
        installed = ws / "docs/00-metodo/scripts/telemetria.py"
        self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
        capture = run(ws / "docs/00-metodo/scripts/peticion.py", "capturar", "--resumen",
                      "Prueba", "--texto", "privado", "--autor", "sintetico")
        self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
        rows = ws / ".runtime/telemetria/eventos.jsonl"
        self.assertEqual(len(rows.read_text(encoding="utf-8").splitlines()), 1)
        # Un workspace anterior aislado: commit de retirada y actualización real.
        git = lambda *args: subprocess.run(["git", "-C", str(ws), *args], capture_output=True,
                                           text=True, encoding="utf-8", check=True,
                                           creationflags=NO_WINDOW)
        installed.unlink()
        git("add", "docs/00-metodo/scripts/telemetria.py")
        git("add", "docs/05-trabajo/peticiones")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "versión anterior sin telemetría")
        update = run(ROOT / "visor/actualizar.py", "aplicar", ws)
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        self.assertEqual(installed.read_bytes(), SCRIPT.read_bytes())
        capture2 = run(ws / "docs/00-metodo/scripts/peticion.py", "capturar", "--resumen",
                       "Otra", "--texto", "privado", "--autor", "sintetico")
        self.assertEqual(capture2.returncode, 0, capture2.stdout + capture2.stderr)
        self.assertEqual(len(rows.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
