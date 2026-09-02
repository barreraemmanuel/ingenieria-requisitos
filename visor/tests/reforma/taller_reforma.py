"""Ayuda de la carpeta `reforma/`: un worktree de verdad y recibos de verdad, en un temporal.

La junta que mide la 146 —ayudante → revisor → prefusión → cierre— decide sobre HECHOS de
git (¿el árbol está limpio?, ¿la cabeza cambió desde el despacho?) y sobre recibos
`ejecucion/v1`. Nada de eso se puede simular con un diccionario suelto sin volver a caer en
el fallo que se está midiendo (el 034 fue exactamente «el recibo dice fail y alguien lo dio
por bueno»), así que aquí se crea un repo `git` real y se leen recibos reales anonimizados
de `visor/tests/fixtures/reforma/recibos/`.
"""
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
SCRIPTS = RAIZ / "plantilla/docs/00-metodo/scripts"
FIXTURES = RAIZ / "visor/tests/fixtures/reforma/recibos"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ejecucion  # noqa: E402 - se importa tras fijar la ruta de los scripts del método

# La marca que toda puerta del método deja al rechazar (regla 13 · lint_salidas.py).
SALIDA = "SALIDA:"


def git(cwd, *args):
    hecho = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    if hecho.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {hecho.stdout}{hecho.stderr}")
    return hecho.stdout.strip()


def recibo_fixture(nombre):
    """Un recibo real anonimizado de `fixtures/reforma/recibos/`."""
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


class Worktree:
    """Un worktree de unidad de juguete, con su historia y su suciedad a medida."""

    def __init__(self, ruta, unidad="146-unidad-de-juguete"):
        self.ruta = Path(ruta)
        self.unidad = unidad
        self.ruta.mkdir(parents=True, exist_ok=True)
        git(self.ruta, "init", "-b", "main")
        git(self.ruta, "config", "user.name", "Suite")
        git(self.ruta, "config", "user.email", "suite@example.invalid")
        (self.ruta / "modulo.py").write_text("print('base')\n", encoding="utf-8")
        git(self.ruta, "add", "-A")
        git(self.ruta, "commit", "-m", "base")
        self.base_head = git(self.ruta, "rev-parse", "HEAD")

    def commitear(self, texto="trabajo del ayudante"):
        (self.ruta / "modulo.py").write_text(f"print({texto!r})\n", encoding="utf-8")
        git(self.ruta, "add", "-A")
        git(self.ruta, "commit", "-m", texto)
        return git(self.ruta, "rev-parse", "HEAD")

    def ensuciar(self, nombre="a-medio-escribir.py"):
        (self.ruta / nombre).write_text("# sin commitear\n", encoding="utf-8")

    def head(self):
        return git(self.ruta, "rev-parse", "HEAD")

    def base(self, *, marcadas=0, totales=4):
        """Lo que `unidad.py despachar` deja anotado al ABRIR la entrega (arreglo 1b)."""
        return {"head": self.base_head, "unidad": self.unidad,
                "plan": {"marcadas": marcadas, "totales": totales},
                "carril": "normal", "espera_cambios": True}

    def recibo(self, *, resultado="ok", rol="constructor", unidad=None, head=None,
               sucio=False, corrupto=False):
        """Un recibo `ejecucion/v1` con la forma que escribe `ejecucion.py`."""
        if corrupto:
            return {"schema": "ejecucion/v1", "unidad": unidad or self.unidad}
        datos = recibo_fixture("constructor-ok")
        datos = json.loads(json.dumps(datos))          # copia, no alias del fixture
        datos["unidad"] = unidad or self.unidad
        datos["rol"] = rol
        if resultado is None:
            datos.pop("resultado", None)
        else:
            datos["resultado"] = resultado
        final = head or self.head()
        datos["git"]["inicial"]["head"] = self.base_head
        datos["git"]["final"]["head"] = final
        datos["git"]["final"]["status_porcelain"] = (
            ["?? a-medio-escribir.py"] if sucio else [])
        return datos


def salida_de(mensaje):
    """El comando que un rechazo nombra tras `SALIDA:`, o None si no nombra ninguno."""
    if SALIDA not in mensaje:
        return None
    cola = mensaje.split(SALIDA, 1)[1].strip()
    return cola.splitlines()[0].strip() if cola else None
