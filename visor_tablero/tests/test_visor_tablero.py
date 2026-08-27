"""Suite del tablero de control (unidad 058-tablero-de-control).

Un test por criterio del contrato, al nivel que declara §Verificación:

- R1 — «Ahora»: agentes vivos (recibo sin `resultado` + cerrojo con PID vivo) y
  terminados fuera de «Ahora», en el historial del día (integración: recibos y
  cerrojos sintéticos sobre disco).
- R2 — «Te toca a ti»: contratos sin aprobar, unidades `en_validacion` y
  peticiones `capturada`, con enlace y desde cuándo esperan (integración).
- R3 — «Por hacer»: fase de cada unidad y, para las planificadas, con QUÉ unidad
  en vuelo chocan y en qué ficheros (unitario: el mismo cruce que `despachar`).
- R4 — «Historial»: entregas cerradas por fecha de OK y commits de `main` del día.
- R5 — «Documentación»: árbol de `docs/`, `.md` servido y `render.js` COMPARTIDO
  con el visor de contratos (el mismo fichero, no una copia). Desde el bug 067 la
  PÁGINA ya no pinta esa sección (la duplicaba); el dato y la ruta `/doc/` siguen,
  intactos, porque `estado.py` no se toca.
- R6 — cabecera: versión, commits sin empujar, canario y servidores; una fuente
  que no se puede leer se dice, nunca sale como cero.
- R7 — estilos idénticos a los del visor de contratos, línea a línea (unitario).
- R8 — solo lectura: ningún POST y la guarda de rutas de los `.md`.
"""

import html.parser
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SERVIR = BASE / "servir.py"
ESTADO = BASE / "estado.py"
PLANTILLA = BASE / "plantilla.html"
PLANTILLA_CONTRATOS = BASE.parent / "visor_contratos" / "plantilla.html"
RENDER_JS_CONTRATOS = BASE.parent / "visor_contratos" / "render.js"


def _cargar(ruta, nombre):
    if str(ruta.parent) not in sys.path:
        sys.path.insert(0, str(ruta.parent))
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


servir = _cargar(SERVIR, "servir_tablero_bajo_prueba")
estado_mod = _cargar(ESTADO, "estado_tablero_bajo_prueba")


# --------------------------------------------------------------------------- fixtures

def _ficha(unidad, **campos):
    campos.setdefault("tipo", "feature")
    campos.setdefault("carril", "normal")
    campos.setdefault("actividad", "construir-unidad")
    lineas = ["---", f"unidad: {unidad}"]
    for clave, valor in campos.items():
        if valor is None:
            continue
        lineas.append(f"{clave}: {valor}")
    lineas += [
        "---",
        "",
        f"# {unidad} · ficha sintética",
        "",
        "## Qué (el contrato, en idioma de negocio)",
        "",
        "Texto de prueba.",
        "",
        "## Plan de trabajo",
        "",
        "- [x] 1. Test en rojo",
        "- [x] 2. Implementar",
        "- [ ] 3. Verde",
        "- [ ] 4. Cerrar",
        "",
    ]
    return "\n".join(lineas)


def _hace(dias):
    return (datetime.now(timezone.utc) - timedelta(days=dias)).date().isoformat()


def _pid_muerto():
    proceso = subprocess.Popen([sys.executable, "-c", "pass"])
    proceso.wait()
    return proceso.pid


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )


def _repo_de_codigo(raiz, con_remoto):
    """`main/`: el repo de código del workspace, con o sin remoto configurado."""
    main = raiz / "main"
    (main / "plantilla" / "docs" / "00-metodo").mkdir(parents=True)
    (main / "plantilla" / "docs" / "00-metodo" / "VERSION").write_text(
        "1.7.6\n", encoding="utf-8"
    )
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "prueba@local")
    _git(main, "config", "user.name", "prueba")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "058: commit del día en main")
    if con_remoto:
        espejo = raiz / ".espejo.git"
        _git(raiz, "init", "-q", "--bare", str(espejo))
        _git(main, "remote", "add", "origin", str(espejo))
        _git(main, "push", "-q", "origin", "main")
        _git(main, "branch", "-q", "--set-upstream-to=origin/main", "main")
        (main / "nuevo.txt").write_text("sin empujar\n", encoding="utf-8")
        _git(main, "add", "-A")
        _git(main, "commit", "-q", "-m", "058: commit sin empujar")
    return main


def workspace_sintetico(raiz, con_remoto=True, con_canario=True):
    """Un meta-repo de mentira con TODAS las fuentes que lee el tablero."""
    raiz = Path(raiz)
    trabajo = raiz / "docs" / "05-trabajo"
    bugs = raiz / "docs" / "bugs"
    peticiones = trabajo / "peticiones"
    archivo = trabajo / "archivo"
    for carpeta in (trabajo, bugs, peticiones, archivo):
        carpeta.mkdir(parents=True, exist_ok=True)

    # --- unidades vivas -----------------------------------------------------
    def unidad(nombre, **campos):
        carpeta = trabajo / nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "especificacion.md").write_text(
            _ficha(nombre, **campos), encoding="utf-8"
        )

    unidad("100-en-obra", estado="en_obra", aprobado=_hace(2),
           ficheros="[api/rutas.py, api/modelos.py]", actualizado=_hace(1))
    unidad("101-planificada-chocando", estado="planificada", aprobado=_hace(1),
           ficheros="[api/modelos.py, web/pagina.py]", actualizado=_hace(1))
    unidad("102-planificada-libre", estado="planificada", aprobado=_hace(1),
           ficheros="[otro/modulo.py]", actualizado=_hace(1))
    unidad("103-sin-aprobar", estado="planificada", aprobado="no",
           ficheros="[nada/aqui.py]", actualizado=_hace(4))
    unidad("104-en-validacion", estado="en_validacion", aprobado=_hace(9),
           ficheros="[val/idar.py]", actualizado=_hace(3))
    unidad("105-en-revision", estado="en_revision", aprobado=_hace(5),
           ficheros="[rev/isar.py]", actualizado=_hace(1))
    # Bug 078: el progreso vive en hallazgos.md, que es lo único que el constructor
    # puede escribir (la ficha corre en 0444 mientras dura la obra). La bitácora del
    # cierre lleva sus propias casillas y NO cuenta como plan.
    (trabajo / "105-en-revision" / "hallazgos.md").write_text(
        "---\nunidad: 105-en-revision\nrevisor: no\nrevisado: no\n---\n\n"
        "# 105 · Hallazgos de la obra\n\n"
        "## Plan\n\n"
        "- [x] 1. Test en rojo\n- [x] 2. Implementar\n- [x] 3. Verde\n- [ ] 4. Cerrar\n\n"
        "## Bitácora del cierre\n\n- [ ] 1 · Evidencia — —\n",
        encoding="utf-8",
    )

    # --- bugs ---------------------------------------------------------------
    (bugs / "200-bug-abierto.md").write_text(
        _ficha("200-bug-abierto", tipo="bug", estado="planificada", aprobado="no",
               ficheros="[api/rutas.py]", actualizado=_hace(6)),
        encoding="utf-8",
    )
    (bugs / "201-bug-cerrado.md").write_text(
        _ficha("201-bug-cerrado", tipo="bug", estado="mergeada", aprobado=_hace(8),
               ficheros="[api/viejo.py]", actualizado=_hace(0), fusion="abc1234"),
        encoding="utf-8",
    )
    (bugs / "INDICE.md").write_text("# Índice de bugs\n", encoding="utf-8")

    # --- archivo (entregas cerradas) ---------------------------------------
    cerrada = archivo / "099-entregada"
    cerrada.mkdir(parents=True, exist_ok=True)
    (cerrada / "especificacion.md").write_text(
        _ficha("099-entregada", estado="mergeada", aprobado=_hace(12),
               ficheros="[viejo/modulo.py]", actualizado=_hace(0),
               fusion="def5678"),
        encoding="utf-8",
    )

    # --- peticiones ---------------------------------------------------------
    def peticion(identificador, estado_peticion, resumen, dias):
        carpeta = peticiones / identificador
        carpeta.mkdir(parents=True, exist_ok=True)
        marca = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
        (carpeta / "peticion.json").write_text(json.dumps({
            "id": identificador,
            "estado": estado_peticion,
            "creada": marca,
            "actualizada": marca,
            "original": {"autor": "Nate", "resumen": resumen, "texto": "detalle"},
            "procesos": [],
        }, ensure_ascii=False), encoding="utf-8")

    peticion("P-20260820-aaaaaaaa", "capturada", "Quiero un tablero", 5)
    peticion("P-20260821-bbbbbbbb", "capturada",
             "Escríbeme a nate@example.com si hace falta", 2)
    peticion("P-20260822-cccccccc", "evaluando", "En evaluación", 3)
    peticion("P-20260823-dddddddd", "cerrada", "Ya cerrada", 10)

    # --- documentación ------------------------------------------------------
    (trabajo / "ESTADO.md").write_text(
        "# ESTADO — hoy\n\nLa portada del tablero.\n", encoding="utf-8"
    )
    decisiones = raiz / "docs" / "04-decisiones"
    decisiones.mkdir(parents=True, exist_ok=True)
    (decisiones / "005-documento-unico.md").write_text(
        "# ADR-005\n\nUn documento por unidad.\n", encoding="utf-8"
    )
    metodo = raiz / "docs" / "00-metodo"
    (metodo / "scripts").mkdir(parents=True, exist_ok=True)
    (metodo / "VERSION").write_text("1.7.7\n", encoding="utf-8")
    if con_canario:
        (metodo / "scripts" / "canario.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'veredicto': 'sano', 'porcentaje': 12.5,\n"
            "  'modelo': 'claude-opus-5', 'ventana': 1000000, 'tokens': 125000,\n"
            "  'sintoma': None}))\n",
            encoding="utf-8",
        )

    # --- lo privado: existe, y el tablero NO lo mira ------------------------
    privado = raiz / ".private"
    privado.mkdir(parents=True, exist_ok=True)
    (privado / "credenciales.md").write_text(
        "# Secreto\n\nnate@example.com / token\n", encoding="utf-8"
    )

    _repo_de_codigo(raiz, con_remoto)
    (raiz / ".runtime" / "ejecuciones").mkdir(parents=True, exist_ok=True)
    (raiz / ".runtime" / "leases" / "active").mkdir(parents=True, exist_ok=True)
    return raiz


def worktree_con_cambios(raiz, nombre):
    """Un worktree de mentira donde el agente lleva un fichero tocado."""
    arbol = Path(raiz) / "worktrees" / nombre
    arbol.mkdir(parents=True, exist_ok=True)
    _git(arbol, "init", "-q", "-b", nombre)
    _git(arbol, "config", "user.email", "prueba@local")
    _git(arbol, "config", "user.name", "prueba")
    (arbol / "base.txt").write_text("base\n", encoding="utf-8")
    _git(arbol, "add", "-A")
    _git(arbol, "commit", "-q", "-m", "base")
    (arbol / "visor_tablero_nuevo.py").write_text("# en obra\n", encoding="utf-8")
    return arbol


def agente(raiz, unidad, rol, sesion, pid, minutos=7, resultado=None,
           cwd=None, modelo="claude-opus-5"):
    """Escribe el recibo de ejecución y, si `pid`, su cerrojo `unit:` vivo."""
    raiz = Path(raiz)
    recibo = {
        "schema": "ejecucion/v1",
        "id": sesion.replace("-", "")[:32],
        "unidad": unidad,
        "harness": "claude",
        "rol": rol,
        "modelo": modelo,
        "cwd": str(cwd or (raiz / "worktrees" / unidad)),
        "rama": unidad,
        "lease": {"session_id": sesion, "fencing": {f"unit:{unidad}": 1}},
        "git": {"inicial": {"head": "0" * 40, "status_porcelain": []}, "final": None},
        "skills_tecnicas": [],
        "checkpoints": [
            {"nombre": "lease", "estado": "ok", "detalle": f"unit:{unidad}#1"},
            {"nombre": "identidad", "estado": "ok", "detalle": "worktree listo"},
        ],
        "exit_code": None,
    }
    if resultado is not None:
        recibo["resultado"] = resultado
        recibo["exit_code"] = 0 if resultado == "ok" else 1
        recibo["checkpoints"].append(
            {"nombre": "harness", "estado": "ok", "detalle": "exit 0"}
        )
    ruta = raiz / ".runtime" / "ejecuciones" / f"{unidad}-{recibo['id']}.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(recibo, ensure_ascii=False, indent=2), encoding="utf-8")

    creado = (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()
    cerrojo = {
        "created": creado,
        "fencing": 1,
        "format": 1,
        "integrity": "0" * 64,
        "operation": sesion,
        "owner": {"host": "local", "pid": pid, "process_started": "ps:hoy",
                  "session_id": sesion},
        "scope": f"unit:{unidad}",
    }
    activo = raiz / ".runtime" / "leases" / "active"
    activo.mkdir(parents=True, exist_ok=True)
    (activo / f"{unidad}.json").write_text(
        json.dumps(cerrojo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ruta


class ServidorDePrueba:
    """El tablero levantado en un puerto libre de 127.0.0.1."""

    def __init__(self, workspace):
        self.servidor = servir.ServidorTablero(
            ("127.0.0.1", 0), servir.hacer_handler(str(workspace), {"ultimo": 0.0})
        )
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.hilo.start()

    def parar(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self.hilo.join(timeout=5)

    def pedir(self, ruta, metodo="GET", cuerpo=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            conexion.request(metodo, ruta, body=cuerpo)
            respuesta = conexion.getresponse()
            return respuesta.status, respuesta.headers, respuesta.read().decode("utf-8")
        finally:
            conexion.close()


class ConWorkspace(unittest.TestCase):
    con_remoto = True
    con_canario = True

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="tablero-")
        cls.raiz = workspace_sintetico(cls.tmp, cls.con_remoto, cls.con_canario)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


# --------------------------------------------------------------------------- R1

class AhoraTest(ConWorkspace):
    """R1 — quién trabaja ahora mismo, y quién ya terminó."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        worktree_con_cambios(cls.raiz, "100-en-obra")
        agente(cls.raiz, "100-en-obra", "constructor",
               "11111111-1111-1111-1111-111111111111", os.getpid(), minutos=7)
        agente(cls.raiz, "105-en-revision", "revisor",
               "22222222-2222-2222-2222-222222222222", _pid_muerto(), minutos=40)
        agente(cls.raiz, "104-en-validacion", "padre",
               "33333333-3333-3333-3333-333333333333", os.getpid(), minutos=90,
               resultado="ok")
        cls.ahora = estado_mod.agentes(str(cls.raiz))

    def test_solo_el_del_pid_vivo_y_sin_resultado_esta_en_ahora(self):
        unidades = [a["unidad"] for a in self.ahora["vivos"]]
        self.assertEqual(["100-en-obra"], unidades)

    def test_el_agente_vivo_trae_rol_modelo_minutos_y_ultimo_checkpoint(self):
        vivo = self.ahora["vivos"][0]
        self.assertEqual("constructor", vivo["rol"])
        self.assertEqual("claude-opus-5", vivo["modelo"])
        self.assertGreaterEqual(vivo["minutos"], 6)
        self.assertLessEqual(vivo["minutos"], 10)
        self.assertEqual("identidad", vivo["checkpoint"]["nombre"])

    def test_el_ultimo_paso_no_publica_la_ruta_absoluta_de_la_maquina(self):
        """R8: el checkpoint de `ejecucion.py` trae `/Users/<quien>/…`."""
        agente(self.raiz, "102-planificada-libre", "constructor",
               "55555555-5555-5555-5555-555555555555", os.getpid(), minutos=1)
        ruta = self.raiz / ".runtime" / "ejecuciones"
        fichero = next(f for f in ruta.glob("102-*.json"))
        recibo = json.loads(fichero.read_text(encoding="utf-8"))
        recibo["checkpoints"][-1]["detalle"] = (
            "/Users/quiensea/Project/meta/worktrees/102-x · rama 102-x"
        )
        fichero.write_text(json.dumps(recibo), encoding="utf-8")
        vivos = {a["unidad"]: a for a in estado_mod.agentes(str(self.raiz))["vivos"]}
        detalle = vivos["102-planificada-libre"]["checkpoint"]["detalle"]
        self.assertNotIn("/Users/quiensea", detalle)
        self.assertIn("102-x", detalle)

    def test_el_agente_vivo_dice_que_ficheros_lleva_tocados_en_su_worktree(self):
        vivo = self.ahora["vivos"][0]
        self.assertIn("visor_tablero_nuevo.py", vivo["ficheros"])

    def test_cada_rol_tiene_su_avatar_y_el_vivo_se_mueve(self):
        vivo = self.ahora["vivos"][0]
        self.assertEqual("constructor", vivo["avatar"])
        self.assertTrue(vivo["vivo"])
        avatares = {a["avatar"] for a in self.ahora["terminados_hoy"]}
        self.assertIn("padre", avatares)
        for terminado in self.ahora["terminados_hoy"]:
            self.assertFalse(terminado["vivo"])

    def test_el_que_termino_sale_de_ahora_y_queda_en_el_historial_del_dia(self):
        terminados = {a["unidad"] for a in self.ahora["terminados_hoy"]}
        self.assertIn("104-en-validacion", terminados)
        self.assertNotIn("104-en-validacion",
                         [a["unidad"] for a in self.ahora["vivos"]])

    def test_el_recibo_abierto_con_el_cerrojo_muerto_tampoco_esta_vivo(self):
        self.assertNotIn("105-en-revision",
                         [a["unidad"] for a in self.ahora["vivos"]])


# --------------------------------------------------------------------------- R2

class TeTocaATiTest(ConWorkspace):
    """R2 — las tres listas que esperan a Nate, con enlace y antigüedad."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.servidor = ServidorDePrueba(cls.raiz)
        _, _, cuerpo = cls.servidor.pedir("/estado.json")
        cls.datos = json.loads(cuerpo)["te_toca"]

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()
        super().tearDownClass()

    def test_lista_los_contratos_sin_aprobar_con_enlace_al_visor_de_contratos(self):
        filas = {f["unidad"]: f for f in self.datos["contratos"]}
        self.assertIn("103-sin-aprobar", filas)
        self.assertIn("200-bug-abierto", filas)
        self.assertNotIn("100-en-obra", filas)
        self.assertTrue(
            filas["103-sin-aprobar"]["enlace"].endswith("/#103-sin-aprobar"),
            filas["103-sin-aprobar"]["enlace"],
        )
        self.assertIn("8766", filas["103-sin-aprobar"]["enlace"])

    def test_lista_las_unidades_en_validacion_con_enlace_a_su_ficha(self):
        filas = {f["unidad"]: f for f in self.datos["en_validacion"]}
        self.assertIn("104-en-validacion", filas)
        self.assertEqual(
            "/doc/docs/05-trabajo/104-en-validacion/especificacion.md",
            filas["104-en-validacion"]["enlace"],
        )

    def test_lista_las_peticiones_capturadas_y_solo_esas(self):
        estados = {f["id"] for f in self.datos["peticiones"]}
        self.assertEqual(
            {"P-20260820-aaaaaaaa", "P-20260821-bbbbbbbb"}, estados
        )

    def test_cada_fila_dice_desde_cuando_espera(self):
        for lista in ("contratos", "en_validacion", "peticiones"):
            for fila in self.datos[lista]:
                with self.subTest(lista=lista, fila=fila):
                    self.assertIn("desde", fila)
                    self.assertIsInstance(fila["dias"], int)
                    self.assertGreaterEqual(fila["dias"], 0)


# --------------------------------------------------------------------------- R3

class PorHacerTest(ConWorkspace):
    """R3 — la fase de cada unidad y POR QUÉ una planificada no arranca."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.datos = estado_mod.por_hacer(str(cls.raiz))
        cls.filas = {u["unidad"]: u for u in cls.datos["unidades"]}

    def test_estan_las_planificadas_en_obra_y_en_revision_y_no_las_cerradas(self):
        self.assertEqual(
            {"100-en-obra", "101-planificada-chocando", "102-planificada-libre",
             "103-sin-aprobar", "105-en-revision", "200-bug-abierto"},
            set(self.filas),
        )

    def test_cada_unidad_trae_su_fase(self):
        self.assertEqual("en obra", self.filas["100-en-obra"]["fase"])
        self.assertEqual("en revisión", self.filas["105-en-revision"]["fase"])
        # R4 del bug 078: sin `## Plan` en hallazgos.md (o sin hallazgos.md), el contador
        # cae a la ficha — las unidades en vuelo el día del arreglo no se quedan en cero.
        self.assertEqual({"hechos": 2, "total": 4},
                         self.filas["100-en-obra"]["plan"])

    def test_el_plan_se_cuenta_desde_hallazgos_no_desde_la_ficha(self):
        """R3 del bug 078 — la ficha de 105 dice 2 de 4 y su hallazgos.md dice 3 de 4;
        manda hallazgos.md, que es donde el constructor SÍ puede marcar."""
        self.assertEqual({"hechos": 3, "total": 4},
                         self.filas["105-en-revision"]["plan"])

    def test_la_planificada_que_choca_dice_con_cual_y_en_que_ficheros(self):
        bloqueo = self.filas["101-planificada-chocando"]["bloqueo"]
        self.assertIsNotNone(bloqueo)
        self.assertEqual(["100-en-obra"], bloqueo["con"])
        self.assertEqual(["api/modelos.py"], bloqueo["ficheros"])

    def test_la_planificada_libre_no_dice_que_este_bloqueada(self):
        self.assertIsNone(self.filas["102-planificada-libre"]["bloqueo"])

    def test_el_cruce_ignora_mayusculas_y_puntos_como_el_de_despachar(self):
        self.assertEqual({"api/x.py"},
                         estado_mod.ficheros_de({"ficheros": "[./API/x.py]"}))

    def test_las_peticiones_salen_por_estado_con_su_resumen(self):
        por_estado = self.datos["peticiones"]
        self.assertEqual(2, len(por_estado["capturada"]))
        self.assertEqual(1, len(por_estado["evaluando"]))
        resumenes = [p["resumen"] for p in por_estado["capturada"]]
        self.assertIn("Quiero un tablero", resumenes)


# --------------------------------------------------------------------------- R4

class HistorialTest(ConWorkspace):
    """R4 — lo entregado, por fecha de OK, y los commits de main de hoy."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.datos = estado_mod.historial(str(cls.raiz))

    def test_lista_el_archivo_y_los_bugs_mergeados_con_enlace_a_su_ficha(self):
        entregas = {e["unidad"]: e for e in self.datos["entregas"]}
        self.assertIn("099-entregada", entregas)
        self.assertIn("201-bug-cerrado", entregas)
        self.assertEqual(
            "/doc/docs/05-trabajo/archivo/099-entregada/especificacion.md",
            entregas["099-entregada"]["enlace"],
        )
        self.assertEqual("/doc/docs/bugs/201-bug-cerrado.md",
                         entregas["201-bug-cerrado"]["enlace"])

    def test_la_linea_de_tiempo_va_de_la_entrega_mas_reciente_a_la_mas_vieja(self):
        fechas = [e["fecha"] for e in self.datos["entregas"]]
        self.assertEqual(sorted(fechas, reverse=True), fechas)

    def test_trae_los_commits_de_main_del_dia(self):
        commits = self.datos["commits"]
        self.assertEqual("ok", commits["estado"])
        titulos = [c["titulo"] for c in commits["lista"]]
        self.assertIn("058: commit del día en main", titulos)


# --------------------------------------------------------------------------- R5

class DocumentacionTest(ConWorkspace):
    """R5 — el árbol de docs/, el .md servido y el motor COMPARTIDO."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.servidor = ServidorDePrueba(cls.raiz)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()
        super().tearDownClass()

    def test_el_arbol_trae_los_md_de_docs_y_estado_md_es_la_portada(self):
        _, _, cuerpo = self.servidor.pedir("/estado.json")
        doc = json.loads(cuerpo)["documentacion"]
        self.assertEqual("docs/05-trabajo/ESTADO.md", doc["portada"])
        self.assertIn("docs/04-decisiones/005-documento-unico.md", doc["ficheros"])
        self.assertIn("docs/05-trabajo/ESTADO.md", doc["ficheros"])

    def test_cualquier_md_de_dentro_del_meta_repo_se_sirve_entero(self):
        codigo, cabeceras, cuerpo = self.servidor.pedir(
            "/doc/docs/04-decisiones/005-documento-unico.md"
        )
        self.assertEqual(200, codigo)
        self.assertIn("text/markdown", cabeceras["Content-Type"])
        self.assertIn("Un documento por unidad.", cuerpo)

    def test_el_motor_de_render_es_el_del_visor_de_contratos_sin_copia(self):
        codigo, _, cuerpo = self.servidor.pedir("/render.js")
        self.assertEqual(200, codigo)
        self.assertEqual(
            RENDER_JS_CONTRATOS.read_text(encoding="utf-8"), cuerpo
        )
        # 081: lo carga la CÁSCARA, una sola vez para los cuatro apartados; la
        # sección del tablero ni lo lleva dentro ni lo vuelve a pedir.
        html = PLANTILLA.read_text(encoding="utf-8")
        self.assertNotIn("function bloques(", html)
        self.assertNotIn('<script src="/render.js"></script>', html)
        cascara = (BASE.parent / "web" / "plantilla.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/render.js"></script>', cascara)


# --------------------------------------------------------------------------- R6

class CabeceraTest(ConWorkspace):
    """R6 — versión, commits sin empujar, canario y servidores levantados."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        guion = cls.raiz / "worktrees" / "056-x" / "visor_contratos" / "servir.py"
        cls.datos = estado_mod.cabecera(str(cls.raiz), procesos=lambda: [
            {"pid": 4242, "puerto": 8766,
             "comando": "python3 %s --workspace %s" % (guion, cls.raiz)},
        ])

    def test_compara_la_version_local_con_la_publicada(self):
        version = self.datos["version"]
        self.assertEqual("ok", version["estado"])
        self.assertEqual("1.7.7", version["local"])
        self.assertEqual("1.7.6", version["publicada"])
        self.assertTrue(version["al_dia"] is False)

    def test_cuenta_los_commits_sin_empujar_de_main_y_del_meta_repo(self):
        self.assertEqual("ok", self.datos["sin_empujar"]["main"]["estado"])
        self.assertEqual(1, self.datos["sin_empujar"]["main"]["commits"])

    def test_trae_el_veredicto_del_canario(self):
        canario = self.datos["canario"]
        self.assertEqual("ok", canario["estado"])
        self.assertEqual("sano", canario["veredicto"])
        self.assertEqual(12.5, canario["porcentaje"])

    def test_dice_que_servidores_hay_y_desde_que_arbol_sirven(self):
        servidores = self.datos["servidores"]
        self.assertEqual("ok", servidores["estado"])
        fila = servidores["lista"][0]
        self.assertEqual(8766, fila["puerto"])
        self.assertEqual("visor de contratos", fila["servicio"])
        self.assertEqual("worktrees/056-x", fila["arbol"])

    def test_un_servidor_lanzado_con_ruta_relativa_se_resuelve_con_SU_cwd(self):
        """Las webs se lanzan como `python3 main/visor_contratos/servir.py`.

        Resolver esa ruta contra el cwd del TABLERO decía «worktree 058» de un
        servidor que servía `main/`: la mentira exacta que R6 prohíbe.
        """
        datos = estado_mod.cabecera(str(self.raiz), procesos=lambda: [
            {"pid": 11, "puerto": 8766, "cwd": str(self.raiz),
             "comando": "python3 main/visor_contratos/servir.py"},
        ])
        self.assertEqual("main", datos["servidores"]["lista"][0]["arbol"])

    def test_sin_saber_el_cwd_no_se_inventa_el_arbol(self):
        datos = estado_mod.cabecera(str(self.raiz), procesos=lambda: [
            {"pid": 11, "puerto": 8766, "cwd": None,
             "comando": "python3 main/visor_contratos/servir.py"},
        ])
        fila = datos["servidores"]["lista"][0]
        self.assertEqual("visor de contratos", fila["servicio"])
        self.assertIsNone(fila["arbol"])


class CabeceraConFuentesCaidasTest(ConWorkspace):
    """R6 — una fuente que no se puede leer se DICE; jamás se muestra un cero."""

    con_remoto = False
    con_canario = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.datos = estado_mod.cabecera(str(cls.raiz), procesos=lambda: [])

    def test_sin_remoto_no_dice_cero_commits_sin_empujar(self):
        main = self.datos["sin_empujar"]["main"]
        self.assertEqual("no_comprobable", main["estado"])
        self.assertIsNone(main["commits"])
        self.assertTrue(main["detalle"])

    def test_sin_canario_lo_dice_en_vez_de_darlo_por_sano(self):
        canario = self.datos["canario"]
        self.assertEqual("no_comprobable", canario["estado"])
        self.assertIsNone(canario["veredicto"])

    def test_sin_servidores_detectados_la_lista_va_vacia_pero_comprobada(self):
        self.assertEqual("ok", self.datos["servidores"]["estado"])
        self.assertEqual([], self.datos["servidores"]["lista"])

    def test_cada_seccion_de_la_instantanea_declara_cuando_se_leyo(self):
        foto = estado_mod.instantanea(str(self.raiz))
        for seccion in ("ahora", "te_toca", "por_hacer", "historial",
                        "documentacion"):
            with self.subTest(seccion=seccion):
                self.assertIn(foto[seccion]["estado"],
                              {"ok", "ausente", "no_comprobable"})
                self.assertIn("leido", foto[seccion])


# --------------------------------------------------------------------------- R7

BASE_CSS = BASE.parent / "visor" / "base.css"
ENLACE_BASE_CSS = '<link rel="stylesheet" href="/base.css">'


def bloque_paleta(texto):
    inicio = texto.index(":root {")
    marca = texto.index(':root[data-theme="light"]', inicio)
    fin = texto.index("}", texto.index("{", marca)) + 1
    return [l.strip() for l in texto[inicio:fin].splitlines() if l.strip()]


def bloque_interruptor(texto):
    inicio = texto.index('var GUARDADO = "visor-tema";')
    fin = texto.index("})();", inicio)
    return [l.strip() for l in texto[inicio:fin].splitlines() if l.strip()]


class _Scripts(html.parser.HTMLParser):
    """Recorta cada <script> de una plantilla tal y como lo ve el navegador."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []       # [(atributos, contenido)] de los que tienen cuerpo
        self.cierres_sueltos = 0
        self._dentro = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._dentro = dict(attrs)

    def handle_endtag(self, tag):
        if tag != "script":
            return
        if self._dentro is None:
            self.cierres_sueltos += 1     # un </script> sin su apertura
        self._dentro = None

    def handle_data(self, data):
        if self._dentro is not None:
            self.scripts.append((self._dentro, data))


def sin_comentarios(js):
    """[(nº de línea, línea sin comentarios)] — para no confundir prosa con código."""
    fuera = []
    en_bloque = False
    for numero, linea in enumerate(js.splitlines(), 1):
        limpia, resto = "", linea
        while resto:
            if en_bloque:
                corte = resto.find("*/")
                if corte == -1:
                    resto = ""
                else:
                    en_bloque, resto = False, resto[corte + 2:]
            else:
                abre, hasta_fin = resto.find("/*"), resto.find("//")
                if hasta_fin != -1 and (abre == -1 or hasta_fin < abre):
                    limpia, resto = limpia + resto[:hasta_fin], ""
                elif abre != -1:
                    limpia, resto = limpia + resto[:abre], resto[abre + 2:]
                    en_bloque = True
                else:
                    limpia, resto = limpia + resto, ""
        fuera.append((numero, limpia.strip()))
    return fuera


def scripts_de(texto):
    parser = _Scripts()
    parser.feed(texto)
    parser.close()
    return parser


class ScriptsDeLaPlantillaTest(unittest.TestCase):
    """R7 — el JS de la plantilla es JS de verdad: sin <script> anidados.

    Un `<script>` pegado dentro de otro no rompe ningún test de texto (el
    recorte por `var GUARDADO` lo salta) pero el navegador lo lee como
    `SyntaxError: Unexpected token '<'` en la PRIMERA línea del bloque: el
    interruptor de tema no llega a existir. Se comprueba extrayendo cada
    `<script>` con `html.parser` y validándolo con `node --check` si hay node.
    """

    def setUp(self):
        self.texto = PLANTILLA.read_text(encoding="utf-8")
        self.parser = scripts_de(self.texto)

    def test_ningun_script_lleva_otro_script_dentro(self):
        """Ninguna etiqueta <script> pegada dentro del cuerpo de otro.

        Se mira código, no prosa: nombrar `<script src=…>` DENTRO de un
        comentario de JS es legítimo y no rompe nada, así que los comentarios
        se quitan antes de mirar. Lo que no puede aparecer es una línea de
        CÓDIGO que empiece por `<script`/`</script`, que es exactamente como se
        cuela un bloque copiado con su etiqueta.
        """
        self.assertGreater(len(self.parser.scripts), 0, "no se leyó ningún <script>")
        for indice, (_, cuerpo) in enumerate(self.parser.scripts):
            for numero, linea in sin_comentarios(cuerpo):
                if linea.lower().startswith(("<script", "</script")):
                    self.fail("el script %d de plantilla.html abre otro <script> en su "
                              "línea %d (%r); el navegador lo lee como SyntaxError y el "
                              "bloque entero no se ejecuta" % (indice, numero, linea))

    def test_no_sobra_ningun_cierre_de_script(self):
        self.assertEqual(0, self.parser.cierres_sueltos,
                         "hay %d </script> sin su <script>" % self.parser.cierres_sueltos)

    def test_cada_script_es_javascript_valido(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("sin node: lo cubren los dos tests anteriores")
        for indice, (attrs, cuerpo) in enumerate(self.parser.scripts):
            if attrs.get("src"):
                continue
            with self.subTest(script=indice):
                with tempfile.TemporaryDirectory() as tmp:
                    js = Path(tmp) / ("script_%d.js" % indice)
                    js.write_text(cuerpo, encoding="utf-8")
                    hecho = subprocess.run([node, "--check", str(js)],
                                           capture_output=True, text=True)
                    self.assertEqual(0, hecho.returncode,
                                     "script %d de plantilla.html no es JS válido:\n%s"
                                     % (indice, hecho.stderr))

    def test_el_interruptor_de_tema_va_en_un_solo_script_como_en_la_056(self):
        cuerpos = [c for _, c in self.parser.scripts if 'var GUARDADO = "visor-tema";' in c]
        self.assertEqual(1, len(cuerpos),
                         "el interruptor de tema debe vivir en un único <script>")
        contratos = scripts_de(PLANTILLA_CONTRATOS.read_text(encoding="utf-8"))
        suyos = [c for _, c in contratos.scripts if 'var GUARDADO = "visor-tema";' in c]
        self.assertEqual(1, len(suyos), "la 056 no se leyó")
        self.assertEqual(suyos[0].strip().splitlines()[-1].strip(),
                         cuerpos[0].strip().splitlines()[-1].strip())


class EstiloIgualQueElVisorDeContratosTest(unittest.TestCase):
    """R7 — misma paleta, cabecera, menú lateral e interruptor que la 056."""

    def setUp(self):
        self.tablero = PLANTILLA.read_text(encoding="utf-8")
        self.contratos = PLANTILLA_CONTRATOS.read_text(encoding="utf-8")

    def test_la_paleta_ya_no_se_copia_sino_que_se_enlaza(self):
        """R7, releído por la 076.

        Antes esto comparaba la paleta línea a línea entre las dos plantillas
        porque estaba DUPLICADA. Ahora vive una sola vez en `visor/base.css` y
        lo que hay que vigilar es que ninguna de las dos se la vuelva a traer.
        """
        paleta = bloque_paleta(BASE_CSS.read_text(encoding="utf-8"))
        self.assertGreater(len(paleta), 20, "la paleta de base.css no se leyó")
        for nombre, texto in (("tablero", self.tablero),
                              ("contratos", self.contratos)):
            with self.subTest(web=nombre):
                self.assertIn(ENLACE_BASE_CSS, texto)
                self.assertNotIn(":root", texto)

    def test_el_interruptor_de_tema_se_comporta_igual(self):
        esperado = bloque_interruptor(self.contratos)
        self.assertGreater(len(esperado), 15, "el interruptor no se leyó")
        self.assertEqual(esperado, bloque_interruptor(self.tablero))

    def test_la_cabecera_y_el_menu_lateral_viven_en_la_hoja_comun(self):
        """Una sola definición para las dos webs, en `visor/base.css`."""
        hoja = BASE_CSS.read_text(encoding="utf-8")
        for declaracion in (
            "header { position: relative; padding-right: 44px; }",
            ".boton-tema { position: absolute; top: -2px; right: 0;",
            "h1 { font-size: var(--t-h1);",
            ".sub { color: var(--muted);",
            ".menu-unidades { flex: 0 0 268px;",
            ".chip-pendiente { background: var(--warn-bg); border-color: "
            "var(--warn); color: var(--warn); }",
            ".chip-aprobado { background: var(--ok-bg); border-color: var(--ok); "
            "color: var(--ok); }",
        ):
            with self.subTest(declaracion=declaracion):
                self.assertIn(declaracion, hoja)
                self.assertNotIn(declaracion, self.tablero)
                self.assertNotIn(declaracion, self.contratos)

    def test_la_tipografia_es_la_misma(self):
        hoja = BASE_CSS.read_text(encoding="utf-8")
        # Unidad 082: la pila dejó de ser sans y pasó a ser MONOESPACIADA en
        # todo. Lo que este test vigila no cambia —una sola pila, en la
        # hoja común, para los cuatro apartados—, cambia cuál es.
        for declaracion in ('--mono: "SF Mono"', "--sans: var(--mono)",
                            "font: 16px/1.6 var(--sans)"):
            with self.subTest(declaracion=declaracion):
                self.assertIn(declaracion, hoja)

    def test_los_avatares_son_svg_en_linea_y_se_animan_solo_mientras_viven(self):
        for rol in ("constructor", "revisor", "padre"):
            with self.subTest(rol=rol):
                self.assertIn('data-avatar="%s"' % rol, self.tablero)
        self.assertIn("@keyframes", self.tablero)
        self.assertIn(".avatar.vivo", self.tablero)
        self.assertNotIn("<img", self.tablero)   # nada de recursos externos

    def test_la_pagina_sondea_el_estado_cada_cinco_segundos(self):
        self.assertIn("/estado.json", self.tablero)
        self.assertIn("5000", self.tablero)

    def test_tiene_las_tres_secciones_por_hash(self):
        """Bug 067: quedan TRES. «Historial» y «Documentación» duplicaban el
        visor de contratos y la web de presentaciones, y se fueron con el
        contrato del 067 (R1); `estado.py` las sigue calculando."""
        for hash_ in ("#ahora", "#te-toca", "#por-hacer"):
            with self.subTest(hash=hash_):
                self.assertTrue(hash_ in self.tablero, "falta la sección " + hash_)
        for hash_ in ("#historial", "#documentacion"):
            with self.subTest(hash=hash_):
                self.assertFalse(hash_ in self.tablero,
                                 "el tablero vuelve a duplicar " + hash_)


# --------------------------------------------------------------------------- R8

class SoloLecturaYGuardaDeRutasTest(ConWorkspace):
    """R8 — ni un POST, y los `.md` sólo desde dentro del meta-repo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.servidor = ServidorDePrueba(cls.raiz)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.parar()
        super().tearDownClass()

    def test_ningun_post_se_acepta(self):
        for ruta in ("/", "/estado.json", "/doc/docs/05-trabajo/ESTADO.md"):
            with self.subTest(ruta=ruta):
                codigo, _, _ = self.servidor.pedir(ruta, "POST", cuerpo=b"{}")
                self.assertEqual(405, codigo)

    def test_el_servidor_no_expone_ningun_do_post_que_escriba(self):
        self.assertFalse(
            [n for n in dir(servir) if n.startswith("guardar")
             or n.startswith("escribir")],
            "el tablero sólo lee",
        )

    def test_las_rutas_que_escapan_del_meta_repo_dan_403(self):
        for ruta in (
            "/doc/../../etc/passwd.md",
            "/doc/docs/../../fuera.md",
            "/doc//etc/passwd.md",
            "/doc/%2e%2e/%2e%2e/fuera.md",
            "/doc/~/notas.md",
        ):
            with self.subTest(ruta=ruta):
                codigo, _, _ = self.servidor.pedir(ruta)
                self.assertEqual(403, codigo, ruta)

    def test_un_symlink_que_apunta_fuera_da_403(self):
        fuera = Path(self.tmp).parent / "secreto-fuera.md"
        fuera.write_text("# fuera\n", encoding="utf-8")
        enlace = self.raiz / "docs" / "atajo.md"
        try:
            enlace.symlink_to(fuera)
        except (OSError, NotImplementedError):
            self.skipTest("esta plataforma no deja crear symlinks")
        try:
            codigo, _, _ = self.servidor.pedir("/doc/docs/atajo.md")
            self.assertEqual(403, codigo)
        finally:
            enlace.unlink(missing_ok=True)
            fuera.unlink(missing_ok=True)

    def test_nunca_sirve_nada_de_private(self):
        codigo, _, _ = self.servidor.pedir("/doc/.private/credenciales.md")
        self.assertEqual(403, codigo)

    def test_private_no_aparece_en_el_arbol_de_documentacion(self):
        _, _, cuerpo = self.servidor.pedir("/estado.json")
        self.assertNotIn(".private", cuerpo)

    def test_lo_que_no_es_md_no_se_sirve(self):
        codigo, _, _ = self.servidor.pedir("/doc/docs/00-metodo/VERSION")
        self.assertEqual(403, codigo)

    def test_ningun_correo_viaja_en_el_estado(self):
        _, _, cuerpo = self.servidor.pedir("/estado.json")
        self.assertNotIn("nate@example.com", cuerpo)
        self.assertIn("[correo oculto]", cuerpo)


# --------------------------------------------------------------------------- casos límite

class CacheTest(ConWorkspace):
    """R1 y R6 — el agente que termina desaparece SIN recargar la página.

    La página no recarga: sondea `/estado.json` cada 5 s. Si la caché no se
    invalidase al cambiar `.runtime/ejecuciones/`, el agente muerto seguiría
    «trabajando» en pantalla hasta que a alguien se le ocurriera pulsar F5.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        agente(cls.raiz, "100-en-obra", "constructor",
               "44444444-4444-4444-4444-444444444444", os.getpid(), minutos=3)

    def test_la_misma_foto_se_reutiliza_mientras_nada_cambia(self):
        cache = estado_mod.Cache(str(self.raiz))
        self.assertIs(cache.instantanea(), cache.instantanea())

    def test_al_terminar_el_agente_la_foto_se_rehace_sin_recargar(self):
        cache = estado_mod.Cache(str(self.raiz))
        self.assertEqual(1, len(cache.instantanea()["ahora"]["vivos"]))
        # el mismo recibo, ahora cerrado: es lo que escribe `ejecucion.py` al salir
        agente(self.raiz, "100-en-obra", "constructor",
               "44444444-4444-4444-4444-444444444444", _pid_muerto(),
               minutos=3, resultado="ok")
        self.assertEqual([], cache.instantanea()["ahora"]["vivos"])


# 081: `visor_tablero/abrir.py` se fundió en `web/abrir.py` — hay UN lanzador para
# los cuatro apartados. La sesión por workspace (levantar una sola y reutilizarla,
# y rechazar una carpeta que no es meta-repo) se prueba allí, en
# `web/tests/test_web_unica.py::AbrirTest`, sobre la web entera.


class FrontmatterTest(unittest.TestCase):
    """R3 — el mismo parseo que `unidad.py`, listas multilínea incluidas.

    Una lista multilínea mal leída deja `ficheros:` vacío y el cruce daría el
    visto bueno SIEMPRE: un guardián que mira de menos es peor que ninguno.
    """

    def test_lee_la_lista_de_ficheros_en_sus_dos_formas(self):
        en_linea = estado_mod.frontmatter(
            "---\nunidad: 001-x\nficheros: [a/b.py, c/d.py]\n---\n"
        )
        multilinea = estado_mod.frontmatter(
            "---\nunidad: 001-x\nficheros:\n  - a/b.py\n  - c/d.py\n---\n"
        )
        self.assertEqual({"a/b.py", "c/d.py"}, estado_mod.ficheros_de(en_linea))
        self.assertEqual({"a/b.py", "c/d.py"}, estado_mod.ficheros_de(multilinea))

    def test_el_comentario_de_la_plantilla_no_es_parte_del_valor(self):
        fm = estado_mod.frontmatter(
            "---\naprobado: 2026-08-25       # Nate, en el visor\n---\n"
        )
        self.assertEqual("2026-08-25", fm["aprobado"])


if __name__ == "__main__":
    unittest.main()
