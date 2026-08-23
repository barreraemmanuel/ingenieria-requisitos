import importlib.util
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import ayuda_windows  # noqa: E402 - módulo hermano de la suite


RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
MODULO = SCRIPTS / "lease.py"
# lease.py importa su hermano workspace_paths (la primitiva `es_enlace`, unidad 043).
# Al cargarlo aquí por ruta no hay paquete que resuelva ese import, así que se pone la
# carpeta en sys.path — igual que hace test_ejecucion_control_plane.py con ejecucion.py.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def cargar_modulo():
    spec = importlib.util.spec_from_file_location(
        f"lease_under_test_{uuid.uuid4().hex}", MODULO
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.lease = cargar_modulo()

    def tearDown(self):
        self.tmp.cleanup()

    def manager(self, session, **kwargs):
        return self.lease.LeaseManager(
            self.workspace,
            session_id=session,
            host="host-local",
            **kwargs,
        )

    def test_scope_exclusivo_rechaza_segundo_propietario(self):
        primero = self.manager("sesion-a").acquire("unit:004")

        with self.assertRaises(self.lease.LeaseBusy) as error:
            self.manager("sesion-b").acquire("unit:004")

        self.assertIn("sesion-a", str(error.exception))
        primero.release()

    def test_scopes_disjuntos_pueden_coexistir(self):
        primero = self.manager("sesion-a").acquire("unit:004")
        segundo = self.manager("sesion-b").acquire("unit:005")

        primero.assert_owner()
        segundo.assert_owner()

        segundo.release()
        primero.release()

    def test_workspace_exclusivo_conflicta_con_cualquier_operacion(self):
        unidad = self.manager("sesion-a").acquire("unit:004")

        with self.assertRaises(self.lease.LeaseBusy):
            self.manager("modo-d").acquire("workspace")

        unidad.release()
        workspace = self.manager("modo-d").acquire("workspace")
        with self.assertRaises(self.lease.LeaseBusy):
            self.manager("sesion-b").acquire("resource:app/settings.py")
        workspace.release()

    def test_fencing_crece_al_cambiar_de_propietario(self):
        primero = self.manager("sesion-a").acquire("git-index")
        token_primero = primero.tokens["git-index"]
        primero.release()

        segundo = self.manager("sesion-b").acquire("git-index")

        self.assertGreater(segundo.tokens["git-index"], token_primero)
        segundo.release()

    def test_pid_reutilizado_no_mantiene_vivo_un_lease_antiguo(self):
        antiguo = self.manager(
            "sesion-antigua",
            pid=os.getpid(),
            process_started="inicio-que-no-corresponde",
        ).acquire("unit:004")

        nuevo = self.manager("sesion-nueva").acquire("unit:004")

        nuevo.assert_owner()
        with self.assertRaises(self.lease.LeaseLost):
            antiguo.assert_owner()
        nuevo.release()

    def test_host_remoto_no_se_reclama_como_muerto(self):
        remoto = self.lease.LeaseManager(
            self.workspace,
            session_id="sesion-remota",
            host="otro-host",
            pid=99999999,
            process_started="desconocido",
        ).acquire("unit:004")

        with self.assertRaises(self.lease.LeaseBusy) as error:
            self.manager("sesion-local").acquire("unit:004")

        self.assertIn("otro-host", str(error.exception))
        remoto.release()

    def test_assert_owner_detecta_un_token_obsoleto(self):
        antiguo = self.manager("sesion-a").acquire("unit:004")
        antiguo.release()
        nuevo = self.manager("sesion-b").acquire("unit:004")

        with self.assertRaises(self.lease.LeaseLost):
            antiguo.assert_owner()

        nuevo.release()

    def test_lease_activo_corrupto_falla_cerrado(self):
        manager = self.manager("sesion-a")
        manager.active.mkdir(parents=True)
        ruta = manager._path("unit:004")
        ruta.write_text('{"format": 1, "scope": "unit:004"', encoding="utf-8")

        with self.assertRaises(self.lease.LeaseError):
            manager.acquire("unit:005")

        self.assertTrue(ruta.exists(), "un registro corrupto no se debe retirar como huérfano")

    def test_lease_rechaza_schema_scope_owner_y_hash_incoherentes(self):
        casos = (
            lambda record: record.update(format=2),
            lambda record: record.update(scope="unit:otro"),
            lambda record: record["owner"].update(session_id=""),
            lambda record: record.update(integrity="0" * 64),
        )
        for indice, mutar in enumerate(casos):
            with self.subTest(mutacion=mutar):
                manager = self.manager(f"sesion-{id(mutar)}")
                scope = f"unit:{indice:03d}"
                grupo = manager.acquire(scope)
                ruta = manager._path(scope)
                record = json.loads(ruta.read_text(encoding="utf-8"))
                mutar(record)
                ruta.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaises(self.lease.LeaseError):
                    self.manager("intruso").acquire("unit:005")
                with self.assertRaises(self.lease.LeaseError):
                    grupo.release()
                ruta.unlink()

    def test_fencing_corrupto_nunca_se_reinicia(self):
        manager = self.manager("sesion-a")
        primero = manager.acquire("git-index")
        token = primero.tokens["git-index"]
        primero.release()
        contador = manager.fencing / f"{self.lease._scope_key('git-index')}.counter"
        contador.write_text("corrupto\n", encoding="ascii")

        with self.assertRaises(self.lease.LeaseError):
            self.manager("sesion-b").acquire("git-index")

        self.assertEqual(contador.read_text(encoding="ascii"), "corrupto\n")
        self.assertGreaterEqual(token, 1)

    def test_adquisicion_multiple_revierte_solo_lo_publicado_por_su_operacion(self):
        ajeno = self.manager("sesion-ajena").acquire("unit:ajena")
        manager = self.manager("sesion-a")
        manager.fencing.mkdir(parents=True, exist_ok=True)
        corrupto = manager.fencing / f"{self.lease._scope_key('resource:dos')}.counter"
        corrupto.write_text("corrupto\n", encoding="ascii")

        with self.assertRaises(self.lease.LeaseError):
            manager.acquire(("resource:uno", "resource:dos"))

        self.assertFalse(manager._path("resource:uno").exists())
        ajeno.assert_owner()
        ajeno.release()

    def test_raices_active_y_fencing_no_pueden_ser_symlink(self):
        for nombre in ("active", "fencing"):
            with self.subTest(nombre=nombre):
                workspace = self.workspace / nombre
                workspace.mkdir()
                manager = self.lease.LeaseManager(
                    workspace, session_id="sesion", host="host-local"
                )
                manager.root.mkdir(parents=True)
                exterior = workspace / "exterior"
                exterior.mkdir()
                ayuda_windows.enlazar_o_saltar(
                    self, manager.root / nombre, exterior, directorio=True
                )
                with self.assertRaises(self.lease.LeaseError):
                    manager.acquire("unit:004")
                self.assertEqual(list(exterior.iterdir()), [])

    def test_failpoint_sin_entorno_no_hace_nada(self):
        self.lease.failpoint("despues_precondiciones")

    def test_sin_ningun_mecanismo_de_lock_falla_cerrado(self):
        self.lease.fcntl = None
        self.lease.msvcrt = None
        with self.assertRaises(self.lease.LeaseError):
            self.manager("sesion-a").acquire("unit:004")

    def test_coordinator_usa_msvcrt_cuando_no_hay_fcntl(self):
        # Doble de la rama Windows: verifica que el coordinator bloquea y
        # libera con msvcrt.locking; la semántica real la ejercita el CI de
        # Windows con toda la suite.
        llamadas = []

        class MsvcrtDoble:
            LK_NBLCK = "LK_NBLCK"
            LK_UNLCK = "LK_UNLCK"

            @staticmethod
            def locking(descriptor, modo, cuantos):
                llamadas.append(modo)

        self.lease.fcntl = None
        self.lease.msvcrt = MsvcrtDoble
        adquirido = self.manager("sesion-a").acquire("unit:004")
        adquirido.release()
        # LK_NBLCK (sondeo no bloqueante con reintento), no LK_LOCK: ese abandona
        # a los ~10 s con EDEADLK y su OSError no lo captura ningún llamador.
        self.assertIn("LK_NBLCK", llamadas)
        self.assertIn("LK_UNLCK", llamadas)
        candado = self.workspace / ".runtime/leases/coordinator.lock"
        self.assertTrue(candado.is_file())
        self.assertGreater(candado.stat().st_size, 0)

    def test_pid_vivo_distingue_procesos_reales_de_inexistentes(self):
        self.assertTrue(self.lease._pid_vivo(os.getpid()))
        # Muy por encima del máximo de PID de macOS y del default de Linux.
        self.assertFalse(self.lease._pid_vivo(2**22 + 12345))


if __name__ == "__main__":
    unittest.main()
