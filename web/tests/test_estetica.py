"""Unidad 082 — la estética unificada de la web del método (dashboard oscuro,
monoespaciado, tipo Nothing), medida donde se puede medir: en el CSS y en el
HTML que produce el motor de bloques.

Qué vigila cada bloque, con el R* del contrato al lado:

- R1 — tokens únicos: la paleta vive en `visor/base.css` y NINGÚN otro fichero
  de la web declara un color literal. La única excusa es el mínimo de
  emergencia marcado `id="minimo-sin-base-css"` (R5 de la 076), que por
  definición no puede usar `var()`: se le exige, a cambio, que sus literales
  sean EXACTAMENTE los de los tokens por defecto.
- R2 — monoespaciado en todo: una sola pila, la del sistema, y ni una regla
  que vuelva a sans-serif (ni en la hoja ni en las cuatro secciones).
- R3 — un solo acento: fuera de los grises sólo existen el verde menta y el
  rojo; cualquier otro color de la hoja es un color de más.
- R4 — texturas: la hoja define la matriz de puntos y el rayado en CSS puro
  (sin imágenes), y el motor de bloques pinta el progreso de un plan con
  ellas: celda llena para lo hecho, celda rayada para lo pendiente.
- R7 — contraste: calculado desde los valores de los tokens, en los DOS temas.

R5 (los cuatro apartados se parecen) y R6 (el interruptor) no se miden aquí:
R5 lo juzga el usuario con las capturas y R6 lo cubre `visor/tests/test_base_css.py`.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASE_CSS = RAIZ / "visor" / "base.css"
RENDER_JS = RAIZ / "visor_contratos" / "render.js"
CASCARA = RAIZ / "web" / "plantilla.html"
BASE_CSS_TEXTO = (RAIZ / "visor" / "base.css").read_text(encoding="utf-8")

# Las cuatro secciones de la web única: su `<style>` propio también cuenta.
SECCIONES = (
    ("flujos", RAIZ / "visor" / "plantilla.html"),
    ("contratos", RAIZ / "visor_contratos" / "plantilla.html"),
    ("presentaciones", RAIZ / "visor_presentaciones" / "plantilla.html"),
    ("tablero", RAIZ / "visor_tablero" / "plantilla.html"),
)

MARCA_MINIMO = 'id="minimo-sin-base-css"'
NODE = shutil.which("node")
TOPE_SEGUNDOS = 5

# Un color es GRIS si sus tres canales no se separan más que esto. Deja pasar
# el negro, el blanco y toda la escala de grises; no deja pasar un ámbar ni un
# azul disfrazados de neutros.
TOLERANCIA_GRIS = 8


# --------------------------------------------------------------- utilidades

def sin_comentarios(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def bloques_style(html):
    return re.findall(r"<style([^>]*)>(.*?)</style>", html, flags=re.S)


def style_propio(html):
    """El `<style>` de una plantilla que NO es el mínimo de emergencia."""
    return "\n".join(cuerpo for atributos, cuerpo in bloques_style(html)
                     if MARCA_MINIMO not in atributos)


def style_minimo(html):
    trozos = [cuerpo for atributos, cuerpo in bloques_style(html)
              if MARCA_MINIMO in atributos]
    return trozos[0] if trozos else ""


def literales_color(texto):
    """Todo color escrito a mano: `#rgb`, `#rrggbb`, `rgb()`, `hsl()`."""
    texto = sin_comentarios(texto)
    hallados = re.findall(r"#[0-9A-Fa-f]{3,8}\b", texto)
    hallados += re.findall(r"\b(?:rgba?|hsla?)\s*\([^)]*\)", texto)
    return hallados


def declaraciones(css):
    """(selector, cuerpo) de cada regla, incluidas las de dentro de un @media."""
    css = sin_comentarios(css)
    return [(" ".join(cab.split()), cuerpo)
            for cab, cuerpo in re.findall(r"([^{}@]+)\{([^{}]*)\}", css)]


def variables(css):
    """Las variables declaradas en un bloque de CSS, la ÚLTIMA gana (como en CSS).

    Se devuelven por bloque: `:root`, `:root[data-theme="light"]`, … Así el
    tema claro se puede medir aparte del oscuro sin resolver la cascada entera.
    """
    salida = {}
    for selector, cuerpo in declaraciones(css):
        tabla = salida.setdefault(selector, {})
        for nombre, valor in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+)", cuerpo):
            tabla[nombre] = valor.strip()
    return salida


def tema(css, selector=":root"):
    """Los tokens de un tema, con `var()` resuelto contra el propio tema."""
    tablas = variables(css)
    tabla = dict(tablas.get(":root", {}))
    tabla.update(tablas.get(selector, {}))
    for _ in range(3):
        for nombre, valor in list(tabla.items()):
            tabla[nombre] = re.sub(
                r"var\(\s*(--[a-z0-9-]+)\s*\)",
                lambda m: tabla.get(m.group(1), m.group(0)), valor)
    return tabla


def rgb(color):
    color = color.strip()
    hallado = re.match(r"#([0-9A-Fa-f]{3})$|#([0-9A-Fa-f]{6})$", color)
    if not hallado:
        raise ValueError("no es un color sólido: %r" % color)
    if hallado.group(1):
        return tuple(int(c * 2, 16) for c in hallado.group(1))
    seis = hallado.group(2)
    return tuple(int(seis[i:i + 2], 16) for i in (0, 2, 4))


def es_gris(color):
    canales = rgb(color)
    return max(canales) - min(canales) <= TOLERANCIA_GRIS


def luminancia(color):
    def canal(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(uno, otro):
    a, b = luminancia(uno), luminancia(otro)
    claro, oscuro = max(a, b), min(a, b)
    return (claro + 0.05) / (oscuro + 0.05)


def familias(css):
    """Cada pila de fuente declarada, con su selector: `font-family` y el
    atajo `font:` (donde la familia es lo que va tras el tamaño/interlineado)."""
    salida = []
    for selector, cuerpo in declaraciones(css):
        for prop, valor in re.findall(r"(?:^|;)\s*(font-family|font)\s*:\s*([^;]+)",
                                      cuerpo):
            valor = valor.strip()
            if prop == "font":
                # `font: bold 13px var(--sans)` → la familia es la cola.
                partes = valor.split()
                if len(partes) < 2:
                    continue
                valor = " ".join(p for p in partes
                                 if not re.match(r"^(bold|normal|italic|\d)", p))
                if not valor:
                    continue
            salida.append((selector, valor))
    return salida


def renderizar(lineas):
    programa = RENDER_JS.read_text(encoding="utf-8") + (
        "\nprocess.stdout.write(bloques(%s));" % json.dumps(lineas))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fichero:
        fichero.write(programa)
        ruta = fichero.name
    try:
        return subprocess.run([NODE, ruta], capture_output=True, text=True,
                              timeout=TOPE_SEGUNDOS, check=True).stdout
    finally:
        Path(ruta).unlink(missing_ok=True)


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BASE_CSS.is_file(), "no existe visor/base.css")
        self.css = BASE_CSS.read_text(encoding="utf-8")
        self.oscuro = tema(self.css)
        self.claro = tema(self.css, ':root[data-theme="light"]')


# ----------------------------------------------------------------------- R1

class TokensUnicosTest(BaseTest):
    """R1 — la paleta se declara UNA vez, en `base.css`, y nadie más pinta."""

    def test_la_hoja_declara_los_tokens_del_sistema(self):
        for token in ("--paper", "--sheet", "--line", "--ink", "--muted",
                      "--ok", "--fail", "--radio", "--textura-matriz",
                      "--textura-rayado"):
            with self.subTest(token=token):
                self.assertIn(token, self.oscuro,
                              "`:root` no declara %s" % token)

    def test_ningun_fichero_de_la_web_declara_un_color_literal(self):
        fuentes = [("web/plantilla.html", style_propio(
            CASCARA.read_text(encoding="utf-8")))]
        fuentes.append(("visor_contratos/render.js",
                        RENDER_JS.read_text(encoding="utf-8")))
        for nombre, plantilla in SECCIONES:
            fuentes.append((nombre, style_propio(
                plantilla.read_text(encoding="utf-8"))))
        for nombre, texto in fuentes:
            with self.subTest(fuente=nombre):
                self.assertEqual(
                    [], literales_color(texto),
                    "%s escribe colores a mano: usa los tokens de base.css"
                    % nombre)

    def test_el_minimo_de_emergencia_repite_los_tokens_al_pie_de_la_letra(self):
        """El único sitio sin `var()` (R5 de la 076) no puede ir por libre.

        Si el mínimo pinta otro fondo que el token, la página da un fogonazo
        con otro color justo antes de que llegue `base.css`.
        """
        minimo = style_minimo(CASCARA.read_text(encoding="utf-8"))
        self.assertTrue(minimo, "la cáscara perdió su mínimo de emergencia")
        colores = [c.lower() for c in literales_color(minimo)]
        self.assertIn(self.oscuro["--paper"].lower(), colores,
                      "el mínimo no usa el fondo del tema por defecto")
        self.assertIn(self.oscuro["--ink"].lower(), colores,
                      "el mínimo no usa la tinta del tema por defecto")
        for color in colores:
            with self.subTest(color=color):
                self.assertIn(color, [self.oscuro["--paper"].lower(),
                                      self.oscuro["--ink"].lower()],
                              "el mínimo inventa un color que no es token")


# ----------------------------------------------------------------------- R2

class MonoespaciadoTest(BaseTest):
    """R2 — la misma pila monoespaciada en todo: títulos, cifras y controles."""

    def test_la_pila_es_monoespaciada_y_del_sistema(self):
        pila = self.oscuro.get("--mono", "")
        self.assertTrue(pila.strip().endswith("monospace"),
                        "la pila no acaba en `monospace`: %r" % pila)
        self.assertNotIn("http", pila, "la pila sale a buscar una fuente fuera")

    def test_no_queda_ninguna_pila_sans(self):
        """Incluido el alias `--sans`, que las secciones siguen usando."""
        for nombre, tabla in (("oscuro", self.oscuro), ("claro", self.claro)):
            for token, valor in tabla.items():
                if "font" not in token and token not in ("--sans", "--mono"):
                    continue
                with self.subTest(tema=nombre, token=token):
                    self.assertNotIn("sans-serif", valor,
                                     "%s sigue siendo sans" % token)
        self.assertEqual(self.oscuro.get("--sans"), self.oscuro.get("--mono"),
                         "`--sans` y `--mono` ya no pueden ser dos pilas")

    def test_ninguna_regla_vuelve_a_sans_serif(self):
        fuentes = [("base.css", self.css)]
        for nombre, plantilla in SECCIONES:
            fuentes.append((nombre, style_propio(
                plantilla.read_text(encoding="utf-8"))))
        fuentes.append(("web/plantilla.html", style_propio(
            CASCARA.read_text(encoding="utf-8"))))
        for nombre, texto in fuentes:
            for selector, pila in familias(texto):
                with self.subTest(fuente=nombre, selector=selector):
                    self.assertNotIn("sans-serif", pila)
                    resuelta = re.sub(
                        r"var\(\s*(--[a-z0-9-]+)\s*\)",
                        lambda m: self.oscuro.get(m.group(1), ""), pila)
                    self.assertIn("monospace", resuelta,
                                  "%s · %s no es monoespaciada: %r"
                                  % (nombre, selector, pila))

    def test_el_minimo_de_emergencia_tambien_es_mono(self):
        minimo = style_minimo(CASCARA.read_text(encoding="utf-8"))
        self.assertIn("monospace", minimo)
        self.assertNotIn("sans-serif", minimo)


# ----------------------------------------------------------------------- R3

class UnSoloAcentoTest(BaseTest):
    """R3 — grises, verde menta y rojo. Nada más."""

    def acentos(self, tabla):
        return {tabla[t].lower() for t in ("--ok", "--ok-bg", "--fail",
                                           "--fail-bg") if t in tabla}

    def test_hay_exactamente_dos_acentos_y_son_los_de_la_referencia(self):
        for nombre, tabla in (("oscuro", self.oscuro), ("claro", self.claro)):
            with self.subTest(tema=nombre):
                verde = rgb(tabla["--ok"])
                rojo = rgb(tabla["--fail"])
                self.assertGreater(verde[1], verde[0], "`--ok` no tira a verde")
                self.assertGreater(verde[1], verde[2], "`--ok` no tira a verde")
                self.assertGreater(rojo[0], rojo[1], "`--fail` no tira a rojo")
                self.assertGreater(rojo[0], rojo[2], "`--fail` no tira a rojo")

    def test_todo_lo_demas_es_gris(self):
        for nombre, tabla in (("oscuro", self.oscuro), ("claro", self.claro)):
            permitidos = self.acentos(tabla)
            for token, valor in tabla.items():
                if not valor.startswith("#"):
                    continue
                if valor.lower() in permitidos:
                    continue
                with self.subTest(tema=nombre, token=token):
                    self.assertTrue(
                        es_gris(valor),
                        "%s = %s no es ni gris ni uno de los dos acentos"
                        % (token, valor))

    def test_los_estados_de_espera_ya_no_tienen_color_propio(self):
        """Ámbar y morado eran un tercer y un cuarto acento (076)."""
        for nombre, tabla in (("oscuro", self.oscuro), ("claro", self.claro)):
            for token in ("--warn", "--warn-bg", "--alt", "--alt-bg",
                          "--accent", "--accent-bg"):
                with self.subTest(tema=nombre, token=token):
                    self.assertTrue(es_gris(tabla[token]),
                                    "%s = %s sigue siendo un acento de color"
                                    % (token, tabla[token]))

    def test_la_hoja_no_esconde_colores_fuera_de_los_tokens(self):
        """Un `#hex` suelto en una regla es un acento por la puerta de atrás."""
        permitidos = self.acentos(self.oscuro) | self.acentos(self.claro)
        for selector, cuerpo in declaraciones(self.css):
            if selector.startswith(":root"):
                continue
            for color in literales_color(cuerpo):
                with self.subTest(selector=selector, color=color):
                    self.assertTrue(
                        color.lower() in permitidos or (
                            color.startswith("#") and es_gris(color)),
                        "%s pinta %s a mano" % (selector, color))


# ----------------------------------------------------------------------- R4

class TexturasTest(BaseTest):
    """R4 — matriz de puntos y rayado, en CSS puro y puestos donde se ven."""

    def test_las_dos_texturas_son_gradientes_sin_una_sola_imagen(self):
        matriz = self.oscuro["--textura-matriz"]
        rayado = self.oscuro["--textura-rayado"]
        self.assertIn("radial-gradient", matriz)
        self.assertIn("repeating-linear-gradient", rayado)
        self.assertIn("45deg", rayado, "el rayado no va a 45°")
        for nombre, valor in (("matriz", matriz), ("rayado", rayado)):
            with self.subTest(textura=nombre):
                self.assertNotIn("url(", valor, "la textura carga una imagen")

    def test_la_ocupacion_del_tablero_es_carril_rayado_con_lo_hecho_solido(self):
        """R4 en el tablero (decisión del padre, H1 de la revisión, 27-08): la ocupación se
        pinta como carril RAYADO (lo pendiente) con lo hecho en tinta sólida; la matriz de
        puntos queda para el progreso del plan. Sin este test nada miraba el tablero."""
        # 27-08: `.barra` pasó a la hoja común como componente compartido.
        css = sin_comentarios(BASE_CSS_TEXTO)
        barra = re.search(r"\.barra\s*\{([^}]*)\}", css)
        hecho = re.search(r"\.barra span\s*\{([^}]*)\}", css)
        self.assertIsNotNone(barra, "el tablero no declara .barra")
        self.assertIsNotNone(hecho, "el tablero no declara .barra span")
        self.assertIn("var(--textura-rayado)", barra.group(1))
        self.assertIn("var(--ink)", hecho.group(1))

    def test_la_hoja_ofrece_las_dos_utilidades(self):
        selectores = {s for s, _ in declaraciones(self.css)}
        self.assertIn(".matriz-puntos", selectores)
        self.assertIn(".rayado", selectores)
        for selector, cuerpo in declaraciones(self.css):
            if selector == ".matriz-puntos":
                self.assertIn("var(--textura-matriz)", cuerpo)
            if selector == ".rayado":
                self.assertIn("var(--textura-rayado)", cuerpo)

    def test_el_progreso_del_plan_se_pinta_con_las_texturas(self):
        """Las casillas del plan de trabajo: llenas las hechas, rayadas las que faltan."""
        selectores = {s for s, _ in declaraciones(self.css)}
        self.assertIn(".plan-progreso", selectores,
                      "la hoja no sabe pintar el progreso de un plan")
        cuerpos = {s: c for s, c in declaraciones(self.css)}
        hecha = cuerpos.get(".plan-celda.hecha", "")
        pendiente = cuerpos.get(".plan-celda", "")
        self.assertTrue(hecha, "falta la celda hecha")
        self.assertIn("var(--textura-rayado)", pendiente,
                      "la celda pendiente no va rayada")

    @unittest.skipUnless(NODE, "sin node no se puede ejecutar render.js")
    def test_el_motor_pinta_la_matriz_de_un_plan(self):
        html = renderizar(["- [x] 1. hecha", "- [x] 2. hecha",
                           "- [ ] 3. pendiente"])
        self.assertIn('class="plan-progreso"', html,
                      "un plan de trabajo no trae su matriz de progreso")
        self.assertEqual(2, html.count('class="plan-celda hecha"'))
        self.assertEqual(1, html.count('class="plan-celda"'))
        self.assertIn('aria-label="2 de 3 hechas"', html,
                      "la matriz no se puede leer sin verla")

    @unittest.skipUnless(NODE, "sin node no se puede ejecutar render.js")
    def test_una_lista_normal_no_se_disfraza_de_plan(self):
        html = renderizar(["- uno", "- dos"])
        self.assertNotIn("plan-progreso", html)
        self.assertIn("<ul>", html)


# ----------------------------------------------------------------------- R7

class ContrasteTest(BaseTest):
    """R7 — legibilidad medida sobre los valores de los tokens, en los dos temas."""

    PRINCIPAL = 7.0
    SECUNDARIO = 4.5

    def test_el_texto_principal_llega_a_siete(self):
        for nombre, tabla in (("oscuro", self.oscuro), ("claro", self.claro)):
            for fondo in ("--paper", "--sheet", "--panel"):
                with self.subTest(tema=nombre, fondo=fondo):
                    ratio = contraste(tabla["--ink"], tabla[fondo])
                    self.assertGreaterEqual(
                        round(ratio, 2), self.PRINCIPAL,
                        "tinta sobre %s: %.2f:1" % (fondo, ratio))

    def test_el_texto_secundario_llega_a_cuatro_y_medio(self):
        for nombre, tabla in (("oscuro", self.oscuro), ("claro", self.claro)):
            for token in ("--muted", "--faint"):
                for fondo in ("--paper", "--sheet", "--panel"):
                    with self.subTest(tema=nombre, texto=token, fondo=fondo):
                        ratio = contraste(tabla[token], tabla[fondo])
                        self.assertGreaterEqual(
                            round(ratio, 2), self.SECUNDARIO,
                            "%s sobre %s: %.2f:1" % (token, fondo, ratio))

    def test_los_dos_acentos_tambien_se_leen(self):
        for nombre, tabla in (("oscuro", self.oscuro), ("claro", self.claro)):
            for token in ("--ok", "--fail"):
                with self.subTest(tema=nombre, acento=token):
                    ratio = contraste(tabla[token], tabla["--paper"])
                    self.assertGreaterEqual(
                        round(ratio, 2), self.SECUNDARIO,
                        "%s sobre el fondo: %.2f:1" % (token, ratio))

    def test_el_tema_por_defecto_es_el_oscuro(self):
        self.assertLess(luminancia(self.oscuro["--paper"]), 0.05,
                        "el fondo por defecto ya no es casi negro")
        self.assertGreater(luminancia(self.claro["--paper"]), 0.5,
                           "el tema claro dejó de ser claro")


# ------------------------------------- la iteración de legibilidad del 26-08

# Cada componente compartido, con la pinta que tiene que seguir teniendo. Si uno
# se borra de `base.css`, la plantilla que lo usaba se queda sin estilo y NADIE
# se entera hasta que alguien abre esa pantalla: por eso el inventario es un test.
COMPONENTES = (
    (".tarjeta", "border"),          # la caja de una unidad, una entrega, un flujo
    (".dato", "border"),             # la cifra grande del tablero
    (".subtitulo", "font-size"),     # el rótulo que parte una sección
    (".lista-pasos", "list-style"),  # los pasos de una validación guiada
    (".lista-criterios", "list-style"),  # los criterios con casilla
    ("dl.vocab", "display"),         # término arriba, definición debajo
    ("nav.pestanas", "display"),     # detalle · adjuntos
    (".boton", "border"),            # el botón, incluido Aprobar
    (".decision", None),             # el formulario de decidir una entrega
    (".menu-lateral", "border"),     # el menú, uno para los cuatro apartados
)

# Los trozos del menú lateral: si una plantilla los vuelve a estilar, vuelven las
# cuatro webs con cuatro menús distintos que la 091 acaba de unificar.
SELECTOR_DE_MENU = re.compile(r"\.menu-[a-z-]+|\.titulo-menu")


class MenuLateralUnicoTest(BaseTest):
    """Un solo menú para los cuatro apartados: el marcado lo dicen las plantillas,
    el ESTILO lo dice `base.css` y sólo `base.css`."""

    def test_las_cuatro_plantillas_montan_el_menu_compartido(self):
        for nombre, plantilla in SECCIONES:
            with self.subTest(web=nombre):
                self.assertIn('class="menu-lateral"',
                              plantilla.read_text(encoding="utf-8"),
                              "%s no usa el menú compartido" % nombre)

    def test_ninguna_plantilla_estila_el_menu_por_su_cuenta(self):
        for nombre, plantilla in SECCIONES:
            propio = sin_comentarios(style_propio(
                plantilla.read_text(encoding="utf-8")))
            for selector, _cuerpo in declaraciones(propio):
                with self.subTest(web=nombre, selector=selector):
                    self.assertIsNone(
                        SELECTOR_DE_MENU.search(selector),
                        "%s vuelve a estilar el menú (%s): eso vive en base.css"
                        % (nombre, selector))

    def test_el_menu_lo_declara_la_hoja_comun(self):
        self.assertIn(".menu-lateral", self.css)


class SinMayusculasForzadasTest(BaseTest):
    """26-08: las mayúsculas forzadas y el tracking salieron de TODA la web.

    Se leen peor y gritan; y `letter-spacing` sobre una pila monoespaciada
    deshace justo la rejilla por la que se eligió. Ni una regla de ninguna de
    las dos, ni en la hoja ni en las cuatro secciones.
    """

    def hojas(self):
        salida = [("base.css", sin_comentarios(self.css))]
        for nombre, plantilla in SECCIONES:
            salida.append((nombre, sin_comentarios(
                plantilla.read_text(encoding="utf-8"))))
        return salida

    def test_ninguna_regla_fuerza_mayusculas(self):
        for nombre, css in self.hojas():
            with self.subTest(web=nombre):
                self.assertEqual(
                    [], re.findall(r"text-transform\s*:\s*(?!none)[a-z-]+", css),
                    "%s vuelve a forzar mayúsculas" % nombre)

    def test_nadie_separa_las_letras(self):
        for nombre, css in self.hojas():
            with self.subTest(web=nombre):
                self.assertEqual(
                    [], re.findall(r"letter-spacing\s*:", css),
                    "%s vuelve a tocar el tracking" % nombre)


class ComponentesCompartidosTest(BaseTest):
    """Los componentes que las cuatro webs comparten viven UNA vez, en la hoja."""

    def test_la_hoja_declara_cada_componente(self):
        selectores = {sel for selector, _ in declaraciones(self.css)
                      for sel in selector.split(",")}
        selectores = {s.strip() for s in selectores}
        for componente, _propiedad in COMPONENTES:
            with self.subTest(componente=componente):
                self.assertTrue(
                    any(s == componente or s.startswith(componente + " ")
                        or s.startswith(componente + ".")
                        or s.startswith(componente + ":")
                        or s.startswith(componente + ">")
                        for s in selectores),
                    "falta %s en base.css" % componente)

    def test_cada_componente_trae_su_pinta_puesta(self):
        """Declarado no basta: un selector vacío es un componente que no existe."""
        for componente, propiedad in COMPONENTES:
            if propiedad is None:
                continue
            with self.subTest(componente=componente):
                cuerpos = [cuerpo for selector, cuerpo in declaraciones(self.css)
                           if componente in [s.strip()
                                             for s in selector.split(",")]]
                self.assertTrue(
                    any(re.search(r"(?:^|;)\s*%s\s*:" % propiedad, cuerpo)
                        for cuerpo in cuerpos),
                    "%s no declara %s" % (componente, propiedad))


if __name__ == "__main__":
    unittest.main()
