"""El workspace se actualiza aunque la herramienta no esté en el ordenador (unidad 031).

Todo con remotos `file://` de fixture: procesos git reales, cero red. La "herramienta
remota" es una copia real de este repositorio (visor/ + plantilla/ + requisitos), así que
lo que se aplica al workspace es el método de verdad, con su HISTORIAL y su linter.
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import ayuda_windows  # noqa: E402 - módulo hermano de la suite


RAIZ = Path(__file__).resolve().parents[2]
ACTUALIZAR = RAIZ / "visor/actualizar.py"
BOOTSTRAP = RAIZ / "visor/bootstrap.py"
HERRAMIENTA_REL = "docs/00-metodo/scripts/herramienta.py"
# Lo que NO viaja a la copia de fixture: pesa y no lo necesita ni el bootstrap ni Modo D.
FUERA = {".git", "worktrees", "tests", "__pycache__", ".DS_Store", ".venv",
         ".ingenieria-requisitos-local", ".caja-negra"}


def borrar_tmp_silencioso(ruta):
    # Los workspaces de estos tests llevan repos git dentro: en Windows sus objetos son
    # 0o444 y un rmtree normal los deja ahí (con ignore_errors, en silencio). Se intenta
    # el borrado bueno y solo se calla lo que quede después.
    try:
        ayuda_windows.borrar_arbol(ruta)
    except OSError:
        shutil.rmtree(ruta, ignore_errors=True)


def modulo_herramienta():
    """El script del método, cargado como módulo, para mirar sus constantes."""
    ruta = RAIZ / "plantilla" / HERRAMIENTA_REL
    spec = importlib.util.spec_from_file_location("herramienta_031", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class HerramientaAutosuficienteTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="herramienta-autosuficiente-"))
        self.addCleanup(borrar_tmp_silencioso, self.base)
        self.casa = self.base / "casa"
        self.casa.mkdir()
        # Identidad git de esta casa de fixture: sin ella ni el bootstrap ni Modo D
        # pueden commitear (y el linter del método lo declara FAIL, con razón).
        (self.casa / ".gitconfig").write_text(
            "[user]\n\tname = Test\n\temail = test@example.com\n", encoding="utf-8")
        self.temporales = self.base / "temporales"
        self.temporales.mkdir()
        self.entorno = dict(os.environ)
        self.entorno.pop("INGENIERIA_REQUISITOS_HERRAMIENTA", None)
        self.entorno.update({
            "HOME": str(self.casa),
            "USERPROFILE": str(self.casa),
            "TMPDIR": str(self.temporales),
            "TEMP": str(self.temporales),
            "TMP": str(self.temporales),
            "INGENIERIA_REQUISITOS_REGISTRO": str(self.base / "registro.json"),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        })

    # --- utilidades ---------------------------------------------------------

    def git(self, repo, *args, **kwargs):
        return subprocess.run(["git", "-C", str(repo), *args], text=True,
                              encoding="utf-8", errors="replace",
                              capture_output=True, env=self.entorno,
                              check=kwargs.pop("check", True), **kwargs)

    def ejecutar(self, script, *args, cwd=None, entorno=None):
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=str(cwd or RAIZ), text=True, encoding="utf-8", errors="replace",
            capture_output=True, env=entorno or self.entorno,
        )

    def herramienta_remota(self):
        """Una copia real de esta herramienta, en git, servible por `file://`."""
        destino = self.base / "herramienta-origen"
        shutil.copytree(
            RAIZ, destino,
            ignore=lambda carpeta, nombres: [n for n in nombres if n in FUERA],
        )
        self.git(destino, "init", "-q", "-b", "main")
        self.git(destino, "config", "core.autocrlf", "false")
        self.git(destino, "config", "user.name", "Test")
        self.git(destino, "config", "user.email", "test@example.com")
        self.git(destino, "add", "-A")
        self.git(destino, "commit", "-qm", "herramienta de fixture")
        url = destino.resolve().as_uri()
        self.git(destino, "remote", "add", "origin", url)
        return destino, url

    def publicar_version(self, herramienta, version):
        """Nueva versión del método publicada en el remoto (un commit más)."""
        (herramienta / "plantilla/docs/00-metodo/VERSION").write_text(
            version + "\n", encoding="utf-8")
        self.git(herramienta, "add", "-A")
        self.git(herramienta, "commit", "-qm", f"método {version}")

    def workspace(self, url_origen, version="1.5.0", con_origen=True, nombre="demo-agents",
                  en=None):
        """Un workspace vivo mínimo: lo justo para que Modo D y el arranque funcionen."""
        ws = (Path(en) if en else self.base) / nombre
        ws.parent.mkdir(parents=True, exist_ok=True)
        for carpeta in ("00-metodo/scripts", "01-constitucion", "02-flujos/planos",
                        "03-investigacion", "04-planificacion", "05-trabajo/archivo",
                        "bugs", "conocimiento", "decisiones"):
            (ws / "docs" / carpeta).mkdir(parents=True)
        (ws / "AGENTS.md").write_text("# AGENTS.md — Demo (meta-repo)\n", encoding="utf-8")
        (ws / "docs/05-trabajo/ESTADO.md").write_text("# Estado\n", encoding="utf-8")
        (ws / "docs/bugs/INDICE.md").write_text("(vacío)\n", encoding="utf-8")
        (ws / "docs/02-flujos/planos/planos.json").write_text(
            '{"version": 2, "titulo": "Demo"}\n', encoding="utf-8")
        (ws / "docs/00-metodo/VERSION").write_text(version + "\n", encoding="utf-8")
        shutil.copyfile(RAIZ / "plantilla" / HERRAMIENTA_REL, ws / HERRAMIENTA_REL)
        metodo = {"formato": 1, "version": version, "huella": "0" * 64, "archivos": []}
        if con_origen:
            metodo["origen"] = url_origen
        (ws / "METODO.json").write_text(
            json.dumps(metodo, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        self.git(ws, "init", "-q", "-b", "main")
        self.git(ws, "config", "core.autocrlf", "false")
        self.git(ws, "config", "user.name", "Test")
        self.git(ws, "config", "user.email", "test@example.com")
        self.git(ws, "add", "-A")
        self.git(ws, "commit", "-qm", "workspace de fixture")
        return ws

    def comprobar(self, ws, entorno=None):
        return self.ejecutar(ws / HERRAMIENTA_REL, "comprobar", cwd=ws, entorno=entorno)

    def aplicar(self, ws, *extra, entorno=None):
        return self.ejecutar(ws / HERRAMIENTA_REL, "aplicar", *extra, cwd=ws,
                             entorno=entorno)

    def espia_git(self):
        """Un `git` en el PATH que apunta cada invocación en un log. Solo POSIX."""
        binario = self.base / "bin"
        binario.mkdir(exist_ok=True)
        registro = self.base / "git.log"
        real = shutil.which("git")
        atajo = binario / "git"
        atajo.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$*" >> {registro}\n'
            f'exec {real} "$@"\n',
            encoding="utf-8")
        atajo.chmod(atajo.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        entorno = dict(self.entorno)
        entorno["PATH"] = str(binario) + os.pathsep + entorno["PATH"]
        return entorno, registro

    def foto(self, raiz):
        """Cada byte de cada fichero bajo `raiz`, INCLUIDO todo lo de `.git`.

        Lo de `.git` es lo que importa aquí: un `pull` que fracasa ya ha hecho fetch y
        deja FETCH_HEAD y las referencias remotas movidas. Una foto que excluya `.git`
        no ve justo el efecto prohibido."""
        return {p.relative_to(raiz).as_posix(): p.read_bytes()
                for p in sorted(Path(raiz).rglob("*")) if p.is_file()}

    def clon_de_otro_origen(self, local, url_ajeno):
        """Un clon sano de la herramienta… pero de OTRO repositorio."""
        local.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", url_ajeno, str(local)], check=True,
                       env=self.entorno, capture_output=True)
        return local

    def clones_completos(self, raiz):
        """Copias enteras de la herramienta bajo `raiz` (para detectar descargas)."""
        return sorted(p.parents[1] for p in Path(raiz).rglob("visor/actualizar.py"))

    # --- R1 -----------------------------------------------------------------

    def test_comprobar_calla_con_version_igual_y_avisa_con_version_nueva(self):
        herramienta, url = self.herramienta_remota()
        version_publicada = (herramienta / "plantilla/docs/00-metodo/VERSION").read_text(
            encoding="utf-8").strip()
        ws = self.workspace(url, version=version_publicada)
        entorno, registro = (self.espia_git() if os.name == "posix"
                             else (self.entorno, None))

        igual = self.comprobar(ws, entorno=entorno)

        self.assertEqual(igual.returncode, 0, igual.stdout + igual.stderr)
        self.assertEqual(igual.stdout.strip(), "", igual.stdout)
        if registro is not None:
            ordenes = registro.read_text(encoding="utf-8")
            self.assertIn("ls-remote", ordenes)
            # Lo mínimo del remoto: si clona para leer el VERSION, clona superficial,
            # sin blobs y en modo sparse. Nunca el repositorio entero.
            for clone in [l for l in ordenes.splitlines() if l.startswith("clone")]:
                self.assertIn("--depth 1", clone)
                self.assertIn("--filter=blob:none", clone)
                self.assertIn("--sparse", clone)
            registro.unlink()

        segunda = self.comprobar(ws, entorno=entorno)

        self.assertEqual(segunda.stdout.strip(), "")
        if registro is not None:
            # Nada cambió en el remoto: un solo viaje (ls-remote) y ni un clon.
            ordenes = registro.read_text(encoding="utf-8")
            self.assertNotIn("clone", ordenes)
            registro.unlink()

        self.publicar_version(herramienta, "9.9.9")
        nueva = self.comprobar(ws, entorno=entorno)

        self.assertEqual(nueva.returncode, 0, nueva.stdout + nueva.stderr)
        self.assertIn("actualización del método", nueva.stdout)
        self.assertIn("9.9.9", nueva.stdout)
        for opcion in ("sí", "todos", "no por ahora", "nunca más"):
            self.assertIn(opcion, nueva.stdout)

    def test_comprobar_respeta_preferencia_nunca(self):
        herramienta, url = self.herramienta_remota()
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")

        guardada = self.ejecutar(ws / HERRAMIENTA_REL, "nunca", cwd=ws)
        self.assertEqual(guardada.returncode, 0, guardada.stdout + guardada.stderr)

        salida = self.comprobar(ws)
        self.assertEqual(salida.returncode, 0)
        self.assertEqual(salida.stdout.strip(), "")

    # --- R2 -----------------------------------------------------------------

    def test_sin_clon_local_clona_en_temporal_y_actualiza_el_workspace(self):
        herramienta, url = self.herramienta_remota()
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")

        aviso = self.comprobar(ws)
        self.assertIn("actualización del método", aviso.stdout)

        salida = self.aplicar(ws)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        historial = (ws / "docs/00-metodo/HISTORIAL.md").read_text(encoding="utf-8")
        self.assertIn("Estado anterior:", historial)
        self.assertEqual(
            (ws / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        # La descarga ocurrió en un temporal, no en la carpeta del usuario.
        self.assertTrue(self.clones_completos(self.temporales),
                        f"sin clon temporal:\n{salida.stdout}")
        self.assertEqual(self.clones_completos(self.casa), [])
        # Y al acabar ofrece los demás workspaces.
        self.assertIn("--todos", salida.stdout)

    def test_todos_desde_un_clon_recien_descargado_alcanza_a_los_demas(self):
        # La oferta de "actualizar los demás" tiene que servir de algo: el registro de
        # workspaces vive DENTRO de la herramienta, y un clon temporal nace sin memoria.
        herramienta, url = self.herramienta_remota()
        otro = self.workspace(url, nombre="otro-agents", en=self.casa / "Project")
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")
        entorno = dict(self.entorno)
        entorno.pop("INGENIERIA_REQUISITOS_REGISTRO", None)

        salida = self.aplicar(ws, "--todos", entorno=entorno)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(
            (otro / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip(), "9.9.9",
            salida.stdout)

    # --- R3 -----------------------------------------------------------------

    def test_clon_local_sano_se_actualiza_con_pull_y_evita_la_descarga(self):
        herramienta, url = self.herramienta_remota()
        local = self.casa / "Project" / "ingenieria-requisitos"
        local.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", url, str(local)], check=True,
                       env=self.entorno, capture_output=True)
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")

        aviso = self.comprobar(ws)
        self.assertIn("9.9.9", aviso.stdout)

        salida = self.aplicar(ws)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(
            (ws / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        # Usó el clon del usuario, puesto al día con pull: sin descargar la herramienta.
        self.assertIn(str(local), salida.stdout)
        self.assertEqual(self.clones_completos(self.temporales), [],
                         f"descargó pudiendo usar el clon local:\n{salida.stdout}")
        self.assertEqual(
            (local / "plantilla/docs/00-metodo/VERSION").read_text(
                encoding="utf-8").strip(), "9.9.9")

    def test_clon_local_enfermo_se_ignora_intacto_y_cae_al_temporal(self):
        herramienta, url = self.herramienta_remota()
        local = self.casa / "Project" / "ingenieria-requisitos"
        local.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", url, str(local)], check=True,
                       env=self.entorno, capture_output=True)
        # Historia divergente: el pull --ff-only de este clon no puede prosperar.
        (local / "APUNTE-DEL-USUARIO.md").write_text("mío\n", encoding="utf-8")
        self.git(local, "commit", "-q", "--allow-empty", "-m", "commit propio del usuario")
        antes = self.foto(local)
        cabeza = self.git(local, "rev-parse", "HEAD").stdout.strip()
        self.assertNotIn(".git/FETCH_HEAD", antes)   # aún nadie ha hecho fetch aquí
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")

        salida = self.aplicar(ws)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(
            (ws / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        # El clon del usuario ni se repara ni se resetea: queda byte a byte como estaba,
        # TAMBIÉN bajo .git. Ni siquiera se le ha hecho el fetch de un pull fallido.
        self.assertEqual(antes, self.foto(local))
        self.assertNotIn(".git/FETCH_HEAD", self.foto(local))
        self.assertEqual(self.git(local, "rev-parse", "HEAD").stdout.strip(), cabeza)
        self.assertIn("divergido", salida.stdout)
        # Y la actualización llegó igual, desde un clon temporal.
        self.assertTrue(self.clones_completos(self.temporales), salida.stdout)

    def test_clon_local_sucio_se_ignora_sin_tocarlo(self):
        # Sucio, no divergente: un `pull` podría machacar trabajo del usuario. Se mira
        # ANTES de lanzar nada que escriba, y se descarta con la carpeta intacta.
        herramienta, url = self.herramienta_remota()
        local = self.casa / "Project" / "ingenieria-requisitos"
        local.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", url, str(local)], check=True,
                       env=self.entorno, capture_output=True)
        (local / "visor/actualizar.py").write_text("# tocado a mano\n", encoding="utf-8")
        antes = self.foto(local)
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")

        salida = self.aplicar(ws)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(
            (ws / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        self.assertEqual(antes, self.foto(local))
        self.assertIn("cambios sin guardar", salida.stdout)
        self.assertTrue(self.clones_completos(self.temporales), salida.stdout)

    def test_clon_local_de_otro_origen_no_se_usa_ni_se_toca(self):
        # Una copia puede tener los dos ficheros que la delatan como "la herramienta" y
        # ser de otro repositorio: un fork, un señuelo. Ejecutar su visor/actualizar.py
        # es ejecutar código de un desconocido. Solo vale si su remoto ES el `origen`
        # validado de METODO.json.
        herramienta, url = self.herramienta_remota()
        ajeno = self.base / "herramienta-de-otro"
        subprocess.run(["git", "clone", "-q", url, str(ajeno)], check=True,
                       env=self.entorno, capture_output=True)
        self.git(ajeno, "commit", "-q", "--allow-empty", "-m", "fork de otro")
        url_ajeno = ajeno.resolve().as_uri()
        local = self.clon_de_otro_origen(
            self.casa / "Project" / "ingenieria-requisitos", url_ajeno)
        antes = self.foto(local)
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")

        salida = self.aplicar(ws)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(
            (ws / "docs/00-metodo/VERSION").read_text(encoding="utf-8").strip(), "9.9.9")
        # Ni se usa ni se toca: descartada intacta, y la actualización viene del temporal.
        self.assertEqual(antes, self.foto(local))
        self.assertIn("apunta a otro repositorio", salida.stdout)
        self.assertTrue(self.clones_completos(self.temporales), salida.stdout)

    def test_la_misma_url_escrita_de_otra_forma_sigue_siendo_el_mismo_origen(self):
        # La comprobación de identidad no puede volverse un "descarga siempre": `.git`
        # final, barra de más o el usuario en la URL son la MISMA cosa. Y lo que no lo
        # es —otro host, otro camino, otro puerto— no puede colarse.
        normalizar = modulo_herramienta().normalizar_remoto
        iguales = [
            ("https://github.com/org/repo.git", "https://github.com/org/repo"),
            ("https://github.com/org/repo/", "https://github.com/org/repo"),
            ("https://Nate@GitHub.com/org/repo.git", "https://github.com/org/repo"),
            ("git@github.com:org/repo.git", "ssh://git@github.com/org/repo"),
        ]
        for uno, otro in iguales:
            with self.subTest(uno=uno):
                self.assertEqual(normalizar(uno), normalizar(otro))
                self.assertIsNotNone(normalizar(uno))
        distintos = [
            ("https://github.com/org/repo", "https://github.com/org/otro"),
            ("https://github.com/org/repo", "https://github.com.evil.io/org/repo"),
            ("https://github.com/org/repo", "https://github.com/Org/repo"),
            ("ssh://git@github.com:22/org/repo", "ssh://git@github.com:2222/org/repo"),
        ]
        for uno, otro in distintos:
            with self.subTest(uno=uno, otro=otro):
                self.assertNotEqual(normalizar(uno), normalizar(otro))
        for veneno in ("ext::sh -c whoami", "", "   ", None):
            self.assertIsNone(normalizar(veneno))

    # --- R4 -----------------------------------------------------------------

    def test_sin_red_el_arranque_sigue_en_silencio_y_rapido(self):
        ws = self.workspace((self.base / "no-existe.git").resolve().as_uri())

        arranque = time.monotonic()
        salida = self.comprobar(ws)
        tardanza = time.monotonic() - arranque

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(salida.stdout.strip(), "")
        self.assertEqual(salida.stderr.strip(), "")
        self.assertLess(tardanza, modulo_herramienta().PRESUPUESTO + 5)

    @unittest.skipUnless(os.name == "posix", "el git de mentira es un /bin/sh")
    def test_comprobar_no_pasa_del_presupuesto_aunque_el_remoto_se_atasque(self):
        # El caso feo de R4: el remoto SÍ contesta al ls-remote (así que el canal sigue
        # adelante) y se atasca justo después. Con timeouts por orden, el arranque se
        # comería la suma de todos ellos; el presupuesto es del proceso ENTERO.
        herramienta, url = self.herramienta_remota()
        ws = self.workspace(url)
        self.publicar_version(herramienta, "9.9.9")
        modulo = modulo_herramienta()
        self.assertLessEqual(modulo.PRESUPUESTO, 15,
                             "el arranque no puede permitirse más de 15 s")

        binario = self.base / "bin-atasco"
        binario.mkdir()
        real = shutil.which("git")
        atajo = binario / "git"
        # Contesta al ls-remote como siempre; a cualquier otra cosa, se cuelga 300 s.
        atajo.write_text(
            "#!/bin/sh\n"
            'for a in "$@"; do [ "$a" = "ls-remote" ] && exec %s "$@"; done\n'
            "sleep 300\n" % real,
            encoding="utf-8")
        atajo.chmod(atajo.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        entorno = dict(self.entorno)
        entorno["PATH"] = str(binario) + os.pathsep + entorno["PATH"]

        arranque = time.monotonic()
        salida = self.comprobar(ws, entorno=entorno)
        tardanza = time.monotonic() - arranque

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(salida.stdout.strip(), "")
        self.assertLess(tardanza, modulo.PRESUPUESTO + 5,
                        f"el arranque tardó {tardanza:.1f}s con el remoto atascado")

    def test_origen_no_puede_colar_una_orden_a_git(self):
        # METODO.json viaja en un repositorio ajeno: su `origen` es un dato, nunca una
        # orden. Ni opción disfrazada de URL ni transporte `ext::` (ejecuta comandos).
        for veneno in ("--upload-pack=touch /tmp/ir-veneno",
                       "ext::sh -c touch% /tmp/ir-veneno"):
            with self.subTest(veneno=veneno):
                ws = self.workspace(veneno, nombre="veneno-agents")
                salida = self.comprobar(ws)
                self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
                self.assertEqual(salida.stdout.strip(), "")
                self.assertFalse(Path("/tmp/ir-veneno").exists())
                ayuda_windows.borrar_arbol(ws)

    def test_sin_origen_grabado_el_arranque_no_dice_nada(self):
        ws = self.workspace("", con_origen=False)

        salida = self.comprobar(ws)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(salida.stdout.strip(), "")

    # --- R5 -----------------------------------------------------------------

    def test_bootstrap_graba_origen_y_aplicar_lo_repone_si_falta(self):
        herramienta, url = self.herramienta_remota()

        planos = self.base / "planos"
        (planos / "especificaciones/01-constitution").mkdir(parents=True)
        (planos / "planos.json").write_text(
            json.dumps({"version": 2, "titulo": "Demo", "tipo": "otro",
                        "actividades": [], "requisitos": []},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (planos / "especificaciones/01-constitution/constitution.md").write_text(
            "# Constitución\n", encoding="utf-8")
        destino = self.base / "nuevo-agents"

        creado = self.ejecutar(herramienta / "visor/bootstrap.py", "--planos", str(planos),
                               "--destino", str(destino), cwd=herramienta)
        self.assertEqual(creado.returncode, 0, creado.stdout + creado.stderr)
        metodo = json.loads((destino / "METODO.json").read_text(encoding="utf-8"))
        self.assertEqual(metodo.get("origen"), url)
        self.assertTrue((destino / HERRAMIENTA_REL).is_file())

        # Y un workspace anterior a esta versión: la primera actualización se lo graba.
        viejo = self.workspace(url, con_origen=False, nombre="legacy-agents")
        self.assertNotIn("origen", json.loads(
            (viejo / "METODO.json").read_text(encoding="utf-8")))

        salida = self.ejecutar(herramienta / "visor/actualizar.py", "aplicar", str(viejo),
                               cwd=herramienta)

        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertEqual(
            json.loads((viejo / "METODO.json").read_text(encoding="utf-8")).get("origen"),
            url)


if __name__ == "__main__":
    unittest.main()
