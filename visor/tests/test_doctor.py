"""revisar_plataforma() de visor/doctor.py: desde la unidad 013 (bug), ninguna plataforma
comprueba ni receta un mecanismo de sandbox de SO — la unidad 012 lo quitó del lanzador
(ejecucion.py) y la promesa de WSL2/bubblewrap que dependía de él quedó falsa. Windows solo
avisa de lo que sigue siendo real: bash y el alias python3.

Este fichero cubre los DOS doctores, que son distintos y viven en sitios distintos:
  · `visor/doctor.py` — el de la herramienta (bloque de arriba, unidades 013/014/044/052)
  · `plantilla/docs/00-metodo/scripts/doctor.py` — el que viaja a los proyectos (bloque
    de abajo, unidad 098: `instalar docker|wsl` con aviso y permiso)."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ayuda_windows

RAIZ = Path(__file__).resolve().parents[2]
DOCTOR_PATH = RAIZ / "visor/doctor.py"

_spec = importlib.util.spec_from_file_location("doctor_bajo_test", DOCTOR_PATH)
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)


class RevisarPlataformaTest(unittest.TestCase):
    def setUp(self):
        self._platform_original = sys.platform
        # buscar_bash() decide por os.name, no por sys.platform: simular Windows a medias
        # dejaba el test comprobando algo que en un Mac no podía pasar nunca. El doble lo
        # pone y lo quita `mock.patch.object`; esto es la red por si alguien lo asigna a mano.
        self._os_original = doctor.os
        self._which_original = doctor.shutil.which
        self._rutas_original = doctor.rutas_largas_activas
        # Las rutas largas son una señal APARTE: se fija en "activadas" para que los
        # tests de bash/python3 midan solo lo suyo. Su propio test la maneja.
        doctor.rutas_largas_activas = lambda: True
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        sys.platform = self._platform_original
        doctor.os = self._os_original
        doctor.shutil.which = self._which_original
        doctor.rutas_largas_activas = self._rutas_original

    # R1 (bug 013): win32 ya NO receta WSL2/sandbox --------------------------

    def test_win32_no_menciona_wsl2_ni_sandbox(self):
        sys.platform = "win32"
        # `path=` porque buscar_bash() usa shutil.which con esa firma.
        doctor.shutil.which = lambda nombre, path=None: "/usr/bin/" + nombre

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "OK")
        texto = detalle + " " + consecuencia
        self.assertNotIn("WSL2", texto)
        self.assertNotIn("sandbox", texto)
        self.assertNotIn("VERSION 2", texto)

    def test_win32_sin_bash_sigue_avisando_bash(self):
        """Lo que seguía siendo real (bash/python3 vienen de Git for Windows, no del
        sandbox) no se pierde al quitar la promesa falsa de WSL2."""
        sys.platform = "win32"
        # Ni en el PATH ni junto a git: aquí bash de verdad no está.
        doctor.shutil.which = lambda nombre, path=None: (
            None if nombre in ("bash", "git") else "/usr/bin/" + nombre
        )

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "WARN")
        self.assertIn("bash", consecuencia)
        self.assertNotIn("WSL2", consecuencia)

    def test_win32_encuentra_el_bash_de_git_for_windows_fuera_del_PATH(self):
        """El PATH de Windows lleva `Git\\cmd` (solo git.exe), no `Git\\bin`: which("bash")
        daba None y el doctor avisaba de una falta que no existía, mientras el despacho
        se negaba a correr hooks con el bash que tenía al lado. Se busca junto a git.

        `os.name` va parcheado ADEMÁS de `sys.platform`: `buscar_bash()` decide por
        `os.name`, y mover solo `sys.platform` dejaba este test en rojo fuera de Windows
        (así se fusionó en la primera ronda). El doble vive en `ayuda_windows`: la 052
        traía aquí una copia local (`_OsDeWindows`) y esta unidad otra en la ayuda; al
        rebasar se funden en UNA, la compartida, que es la que usan los tres tests que
        fingen Windows. La raíz del temporal va con `.resolve()` porque en macOS es
        `/var/…`, un symlink a `/private/var/…`, y la producción resuelve la ruta de git
        antes de subir a la raíz de la instalación.
        """
        sys.platform = "win32"
        temporal = tempfile.TemporaryDirectory(prefix="git-for-windows-")
        self.addCleanup(temporal.cleanup)
        raiz = Path(temporal.name).resolve()
        (raiz / "cmd").mkdir(parents=True)
        (raiz / "bin").mkdir(parents=True)
        (raiz / "cmd" / "git.exe").write_text("", encoding="utf-8")
        (raiz / "bin" / "bash.exe").write_text("", encoding="utf-8")
        doctor.shutil.which = lambda nombre, path=None: (
            str(raiz / "cmd" / "git.exe") if nombre == "git"
            else None if nombre == "bash"
            else "/usr/bin/" + nombre
        )

        with mock.patch.object(doctor, "os", ayuda_windows.OsDeWindows()):
            self.assertEqual(doctor.buscar_bash(), str(raiz / "bin" / "bash.exe"))
            estado, _detalle, consecuencia = doctor.revisar_plataforma()
        self.assertEqual(estado, "OK")
        self.assertNotIn("bash", consecuencia)

    def test_win32_sin_python3_sigue_avisando_el_alias(self):
        sys.platform = "win32"
        doctor.shutil.which = lambda nombre, path=None: (
            None if nombre == "python3" else "/usr/bin/" + nombre
        )

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "WARN")
        self.assertIn("python3", consecuencia)
        self.assertNotIn("WSL2", consecuencia)

    # Bug 044: rutas largas ------------------------------------------------

    def test_win32_avisa_si_las_rutas_largas_estan_desactivadas(self):
        """`worktrees/NNN-slug/` añade ~80 caracteres: con MAX_PATH en 260 y un
        node_modules corriente, `git worktree add` muere. git lo sortea con
        core.longpaths, pero npm y compiladores no: por eso se avisa."""
        sys.platform = "win32"
        doctor.shutil.which = lambda nombre, path=None: "/usr/bin/" + nombre
        doctor.rutas_largas_activas = lambda: False

        estado, _detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "WARN")
        self.assertIn("rutas largas", consecuencia)
        self.assertIn("260", consecuencia)

    def test_win32_no_avisa_si_las_rutas_largas_estan_activadas(self):
        sys.platform = "win32"
        doctor.shutil.which = lambda nombre, path=None: "/usr/bin/" + nombre
        doctor.rutas_largas_activas = lambda: True

        estado, _detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "OK")
        self.assertNotIn("rutas largas", consecuencia)

    def test_fuera_de_windows_las_rutas_largas_no_son_un_problema(self):
        """El límite es de Windows: en POSIX no se lee registro ni se avisa."""
        sys.platform = "linux"
        doctor.rutas_largas_activas = self._rutas_original

        self.assertTrue(doctor.rutas_largas_activas())

    # R2 (bug 013): linux/darwin ya NO comprueban ningún mecanismo de sandbox --

    def test_linux_no_comprueba_mecanismo_de_sandbox(self):
        sys.platform = "linux"

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "OK")
        self.assertNotIn("bubblewrap", detalle + consecuencia)
        self.assertNotIn("bwrap", detalle + consecuencia)
        self.assertNotIn("srt", detalle + consecuencia)

    def test_darwin_no_comprueba_mecanismo_de_sandbox(self):
        sys.platform = "darwin"

        estado, detalle, consecuencia = doctor.revisar_plataforma()

        self.assertEqual(estado, "OK")
        self.assertNotIn("sandbox-exec", detalle + consecuencia)
        self.assertNotIn("srt", detalle + consecuencia)


class LosTresTextosYaNoNombranWSL2Test(unittest.TestCase):
    """R3 (bug 014): la misma verdad en manual, RUNBOOK y sandbox.md de la plantilla — sin
    sandbox de SO desde la unidad 012, ninguno de los tres debe recetar WSL2/bubblewrap."""

    def test_manual_faq_funciona_en_windows_no_nombra_wsl2(self):
        texto = (RAIZ / "manual-ingenieria-requisitos.html").read_text(encoding="utf-8")
        inicio = texto.index("¿Funciona en Windows?")
        fragmento = texto[inicio:inicio + 1500]
        self.assertNotIn("WSL2", fragmento)
        self.assertNotIn("VERSION 2", fragmento)
        self.assertIn("Windows", fragmento)  # sigue respondiendo la pregunta

    def test_runbook_no_nombra_wsl2_ni_version_2(self):
        texto = (RAIZ / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertNotIn("WSL2", texto)
        self.assertNotIn("VERSION 2", texto)
        self.assertNotIn("bubblewrap", texto)

    def test_sandbox_md_no_nombra_wsl2_ni_version_2(self):
        texto = (RAIZ / "plantilla/docs/00-metodo/sandbox.md").read_text(encoding="utf-8")
        self.assertNotIn("WSL2", texto)
        self.assertNotIn("VERSION 2", texto)
        self.assertNotIn("win32", texto)

    def test_sandbox_md_describe_el_mecanismo_real_sin_sandbox_de_so(self):
        """No basta con que no mencione WSL2: tiene que decir la verdad de hoy — que ya
        no hay sandbox de SO, no quedarse en blanco. Mencionar sandbox-exec/bwrap para
        explicar que se retiraron sigue siendo honesto; lo que no puede pasar es que el
        documento SIGA recetando un mecanismo por plataforma como si aplicara hoy."""
        texto = (RAIZ / "plantilla/docs/00-metodo/sandbox.md").read_text(encoding="utf-8")
        self.assertNotIn("Mecanismos por plataforma", texto)
        self.assertIn("no impone", texto.lower())
        self.assertIn("cwd", texto)


if __name__ == "__main__":
    unittest.main()


# =========================================================================== #
#  Unidad 098 · el doctor de la PLANTILLA (docs/00-metodo/scripts/doctor.py):  #
#  `instalar docker|wsl` avisa, pide permiso y solo entonces toca la máquina.  #
#                                                                             #
#  REGLA DURA DE ESTOS TESTS: aquí no se instala NADA de verdad. La receta se  #
#  sustituye siempre por un doble (`instalar_paquete`); si algún día un test   #
#  de este bloque llega a ejecutar la receta real, es un defecto del test.     #
# =========================================================================== #

import io                                                        # noqa: E402
from contextlib import redirect_stdout                           # noqa: E402

DOCTOR_PLANTILLA = RAIZ / "plantilla/docs/00-metodo/scripts/doctor.py"

_spec_p = importlib.util.spec_from_file_location("doctor_plantilla_bajo_test",
                                                 DOCTOR_PLANTILLA)
doctor_plantilla = importlib.util.module_from_spec(_spec_p)
_spec_p.loader.exec_module(doctor_plantilla)


class _Instalador:
    """El doble de la instalación real. Cuenta llamadas y devuelve lo que se le diga."""

    def __init__(self, codigo=0, salida="ok"):
        self.llamadas = []
        self.codigo = codigo
        self.salida = salida

    def __call__(self, pasos):
        self.llamadas.append(list(pasos))
        return self.codigo, self.salida


class InstalarBase(unittest.TestCase):
    def setUp(self):
        self.doctor = doctor_plantilla
        self.instalador = _Instalador()
        self.temporal = tempfile.TemporaryDirectory(prefix="doctor-098-")
        self.addCleanup(self.temporal.cleanup)
        self.raiz = Path(self.temporal.name)
        parches = {
            "RAIZ": self.raiz,
            "instalar_paquete": self.instalador,
            "hay_tty": lambda: True,
            "plataforma": lambda: "Darwin",
            "tiene": lambda nombre: True,          # brew/winget presentes
            "pedir_confirmacion": lambda: True,
        }
        for nombre, valor in parches.items():
            parche = mock.patch.object(self.doctor, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)

    def instalar(self, *argv):
        """Devuelve (codigo, texto impreso)."""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            codigo = self.doctor.orden_instalar(list(argv))
        return codigo, buffer.getvalue()

    def recibos(self):
        carpeta = self.raiz / ".runtime" / "doctor"
        return sorted(carpeta.glob("*.json")) if carpeta.is_dir() else []


class R1AvisaYPidePermisoTest(InstalarBase):
    """R1 — criterio PORTANTE: antes de tocar la máquina se enseña todo y se pide un «sí»."""

    def test_el_aviso_dice_que_de_donde_cuanto_que_cambia_y_como_se_quita(self):
        with mock.patch.object(self.doctor, "pedir_confirmacion", lambda: False):
            codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 1, texto)
        for trozo in ("Docker", "https://", "Tamaño", "Qué cambia en tu máquina",
                      "Cómo se desinstala"):
            self.assertIn(trozo, texto)
        self.assertEqual(self.instalador.llamadas, [])

    def test_sin_el_si_no_se_ejecuta_nada_y_la_salida_queda_escrita(self):
        with mock.patch.object(self.doctor, "pedir_confirmacion", lambda: False):
            codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 1)
        self.assertIn("SALIDA:", texto)
        self.assertEqual(self.instalador.llamadas, [])

    def test_solo_un_si_de_verdad_cuenta_como_si(self):
        for bueno in ("sí", "si", "SÍ", " Si "):
            self.assertTrue(self.doctor.es_un_si(bueno), bueno)
        for malo in ("", "s", "yes", "y", "no", "vale", "sip"):
            self.assertFalse(self.doctor.es_un_si(malo), malo)

    def test_si_ya_esta_instalado_no_pregunta_ni_instala(self):
        with mock.patch.object(self.doctor, "esta_instalado", lambda clave: True):
            codigo, texto = self.instalar("docker")

        self.assertEqual(codigo, 0, texto)
        self.assertIn("ya está", texto)
        self.assertEqual(self.instalador.llamadas, [])

    def test_el_catalogo_es_cerrado(self):
        self.assertEqual(sorted(self.doctor.CATALOGO), ["docker", "wsl"])
        codigo, texto = self.instalar("podman", "--simular-ausente")
        self.assertEqual(codigo, 1)
        self.assertIn("docker", texto)
        self.assertIn("SALIDA:", texto)
        self.assertEqual(self.instalador.llamadas, [])


class R2InstalaPorLaRecetaOficialTest(InstalarBase):
    """R2 — con el «sí», la receta OFICIAL del SO detectado, verificación y recibo."""

    def test_macos_con_brew_instala_docker_desktop_por_el_cask_oficial(self):
        codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 0, texto)
        self.assertEqual(self.instalador.llamadas,
                         [[["brew", "install", "--cask", "docker"]]])

    def test_macos_sin_brew_no_inventa_receta_deja_el_enlace_oficial(self):
        with mock.patch.object(self.doctor, "tiene", lambda nombre: False):
            codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 1)
        self.assertIn("https://docs.docker.com", texto)
        self.assertIn("SALIDA:", texto)
        self.assertEqual(self.instalador.llamadas, [])

    def test_linux_usa_el_script_oficial_de_docker(self):
        with mock.patch.object(self.doctor, "plataforma", lambda: "Linux"):
            codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 0, texto)
        pasos = self.instalador.llamadas[0]
        plano = " ".join(" ".join(p) for p in pasos)
        self.assertIn("https://get.docker.com", plano)
        self.assertNotIn("|", plano)            # sin shell: nada de tuberías

    def test_windows_usa_winget_para_docker_y_wsl_install_para_wsl(self):
        with mock.patch.object(self.doctor, "plataforma", lambda: "Windows"):
            self.instalar("docker", "--simular-ausente")
            self.instalar("wsl", "--simular-ausente")

        plano_docker = " ".join(" ".join(p) for p in self.instalador.llamadas[0])
        plano_wsl = " ".join(" ".join(p) for p in self.instalador.llamadas[1])
        self.assertIn("winget", plano_docker)
        self.assertIn("Docker.DockerDesktop", plano_docker)
        self.assertIn("wsl --install", plano_wsl)

    def test_wsl_fuera_de_windows_se_niega_con_salida(self):
        codigo, texto = self.instalar("wsl", "--simular-ausente")   # Darwin

        self.assertEqual(codigo, 1)
        self.assertIn("Windows", texto)
        self.assertIn("SALIDA:", texto)
        self.assertEqual(self.instalador.llamadas, [])

    def test_al_terminar_verifica_y_deja_el_recibo_en_runtime_doctor(self):
        with mock.patch.object(self.doctor, "verificar",
                               lambda clave: (True, "Docker version 27.0.0")):
            codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 0, texto)
        recibos = self.recibos()
        self.assertEqual(len(recibos), 1, "falta el recibo en .runtime/doctor/")
        datos = json.loads(recibos[0].read_text(encoding="utf-8"))
        self.assertEqual(datos["paquete"], "docker")
        self.assertEqual(datos["resultado"], "instalado")
        self.assertIn("Docker version", datos["verificacion"])

    def test_si_la_verificacion_falla_lo_dice_y_sale_1(self):
        with mock.patch.object(self.doctor, "verificar", lambda clave: (False, "")):
            codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 1)
        self.assertIn("SALIDA:", texto)

    def test_el_no_tambien_deja_recibo(self):
        with mock.patch.object(self.doctor, "pedir_confirmacion", lambda: False):
            self.instalar("docker", "--simular-ausente")

        datos = json.loads(self.recibos()[0].read_text(encoding="utf-8"))
        self.assertEqual(datos["resultado"], "sin permiso")


class R3NadieSeQuedaSinCaminoTest(unittest.TestCase):
    """R3 — donde hoy hay un FAIL seco por falta de Docker, ahora se nombra el comando."""

    COMANDO = "doctor.py instalar docker"

    def test_el_diagnostico_de_docker_nombra_el_comando(self):
        with mock.patch.object(doctor_plantilla, "correr", lambda *cmd: (False, "")):
            estado, _detalle, consecuencia = doctor_plantilla.revisar_docker()

        self.assertEqual(estado, "NO")
        self.assertIn(self.COMANDO, consecuencia)

    def test_los_dos_runbooks_de_despliegue_nombran_el_comando(self):
        for relativa in ("plantilla/docs/00-metodo/runbooks/primer-despliegue.md",
                         "plantilla/docs/00-metodo/runbooks/deploy-vps-docker.md"):
            with self.subTest(relativa):
                texto = (RAIZ / relativa).read_text(encoding="utf-8")
                self.assertIn(self.COMANDO, texto)

    def test_vps_py_nombra_el_comando_donde_detecta_la_falta(self):
        texto = (RAIZ / "plantilla/docs/00-metodo/scripts/vps.py").read_text(encoding="utf-8")
        self.assertIn(self.COMANDO, texto)


class R4NadieInstalaACiegasTest(InstalarBase):
    """R4 — la confirmación exige a una persona delante: ni bandera ni tubería la sustituyen."""

    def test_sin_tty_se_niega_y_pide_una_terminal(self):
        with mock.patch.object(self.doctor, "hay_tty", lambda: False):
            codigo, texto = self.instalar("docker", "--simular-ausente")

        self.assertEqual(codigo, 1)
        self.assertIn("terminal", texto.lower())
        self.assertIn("SALIDA:", texto)
        self.assertEqual(self.instalador.llamadas, [])

    def test_la_bandera_si_no_sustituye_a_la_persona(self):
        codigo, texto = self.instalar("docker", "--si", "--simular-ausente")

        self.assertEqual(codigo, 1)
        self.assertIn("SALIDA:", texto)
        self.assertEqual(self.instalador.llamadas, [])


class R5SoloEnLocalTest(InstalarBase):
    """R5 — el VPS se prepara con servidor-preparar.sh; `instalar` no sale de esta máquina."""

    def test_no_admite_host_y_manda_al_camino_del_vps(self):
        codigo, texto = self.instalar("docker", "--host", "vps.ejemplo.com")

        self.assertEqual(codigo, 1)
        self.assertIn("vps.py", texto)
        self.assertIn("SALIDA:", texto)
        self.assertEqual(self.instalador.llamadas, [])

    def test_el_subcomando_no_declara_ninguna_bandera_de_maquina_remota(self):
        for bandera in ("--host", "--remoto", "--ssh"):
            self.assertNotIn(bandera, self.doctor.BANDERAS_DE_INSTALAR)


class ElDiagnosticoDeSiempreSigueIgualTest(unittest.TestCase):
    """No debe haber cambiado: `doctor.py` a secas sigue informando y saliendo con 0."""

    def test_sin_argumentos_sigue_siendo_el_informe_de_entorno(self):
        resultado = subprocess.run(
            [sys.executable, str(DOCTOR_PLANTILLA)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")

        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("Entorno de esta máquina", resultado.stdout)


class R3ElDespliegueTampocoDejaTiradoTest(unittest.TestCase):
    """R3, caso límite en vivo: `vps.py desplegar` construye la imagen en ESTA máquina.
    Sin Docker local no falla a mitad con un error de `docker: command not found`: para
    antes y nombra el comando que lo instala (con su aviso)."""

    def setUp(self):
        ruta = RAIZ / "plantilla/docs/00-metodo/scripts/vps.py"
        spec = importlib.util.spec_from_file_location("vps_bajo_test", ruta)
        self.vps = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.vps)

    def test_sin_docker_local_para_y_nombra_el_comando(self):
        with mock.patch.object(self.vps.shutil, "which", lambda nombre: None):
            with self.assertRaises(self.vps.Rechazo) as caja:
                self.vps.exigir_docker_local()

        self.assertIn("doctor.py instalar docker", caja.exception.salida)

    def test_con_docker_local_no_estorba(self):
        with mock.patch.object(self.vps.shutil, "which", lambda nombre: "/usr/bin/docker"):
            self.assertIsNone(self.vps.exigir_docker_local())
