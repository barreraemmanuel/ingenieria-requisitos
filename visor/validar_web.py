#!/usr/bin/env python3
"""E2E obligatorio del menú lateral del visor.

Levanta el servidor real, abre Chrome mediante Playwright y comprueba que el
lateral existe, permanece a la izquierda y permite navegar por todas las
actividades o flujos. Sale con código 1 ante cualquier incumplimiento.

Uso:
    python3 visor/validar_web.py --datos /ruta/planos.json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
REQUISITOS = next(
    (ruta for ruta in (BASE / "requirements-dev.txt", BASE.parent / "requirements-dev.txt")
     if ruta.is_file()),
    BASE / "requirements-dev.txt",
)

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:
    # El módulo debe poder importarse sin Playwright (los tests de lógica pura
    # lo hacen); el error salta al EJECUTAR, no al importar.
    PlaywrightError = None
    sync_playwright = None

FALTA_PLAYWRIGHT = (
    "ERROR: falta Playwright. Instala las dependencias E2E con "
    f"`python3 -m pip install -r \"{REQUISITOS}\"` "
    "y después `python3 -m playwright install chromium`."
)


SERVIR = BASE / "servir.py"
ANCHOS = (1280, 700)


def encontrar_chrome():
    candidatas = [
        os.environ.get("CHROME_BIN"),
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        str(
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            / "Google/Chrome/Application/chrome.exe"
        ),
        str(
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Google/Chrome/Application/chrome.exe"
        ),
        str(
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google/Chrome/Application/chrome.exe"
        ),
    ]
    for candidata in candidatas:
        if candidata and Path(candidata).is_file():
            return candidata
    return None


def arrancar_visor(datos):
    proceso = subprocess.Popen(
        [
            sys.executable,
            str(SERVIR),
            "--datos",
            str(datos),
            "--minutos",
            "2",
            "--puerto",
            "0",
            "--sin-navegador",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for _ in range(20):
        linea = proceso.stdout.readline()
        encontrada = re.search(r"Visor levantado: (http://\S+/)", linea)
        if encontrada:
            return proceso, encontrada.group(1)
        if proceso.poll() is not None:
            break
    salida = proceso.stdout.read()
    proceso.terminate()
    raise RuntimeError("el visor no arrancó: " + salida)


def comprobar_lateral(page, datos, ancho):
    page.goto(page.url.split("#")[0] + "#resumen")
    page.wait_for_function(
        """() => document.querySelector('#titulo').textContent !==
                 'Cargando…'"""
    )
    menu = page.locator("#menuIzq")
    panel = page.locator(".panel")
    if not menu.is_visible():
        raise AssertionError("el menú lateral está oculto a %d px" % ancho)
    caja_menu = menu.bounding_box()
    caja_panel = panel.bounding_box()
    if caja_menu["x"] + caja_menu["width"] > caja_panel["x"] + 1:
        raise AssertionError(
            "el menú no está a la izquierda del contenido a %d px" % ancho
        )

    actividades = datos.get("actividades") or []
    flujos = datos.get("flujos") or []
    textos = page.locator("#menuIzq button").all_inner_texts()
    if actividades:
        areas = []
        for actividad in actividades:
            if actividad["area"] not in areas:
                areas.append(actividad["area"])
        ordenadas = [
            actividad
            for area in areas
            for actividad in actividades
            if actividad["area"] == area
        ]
        esperados = ["🗺 El mapa"] + [x["nombre"] for x in ordenadas]
        if textos != esperados:
            raise AssertionError(
                "actividades del lateral distintas: %r != %r"
                % (textos, esperados)
            )
        for actividad in actividades:
            print(
                "E2E %d px · actividad: %s" %
                (ancho, actividad["nombre"]),
                flush=True,
            )
            page.get_by_role(
                "button", name=actividad["nombre"], exact=True
            ).click()
            page.wait_for_function(
                """titulo => Array.from(
                  document.querySelectorAll('#menuIzq button')
                ).some(b => b.textContent.trim() === titulo &&
                            b.classList.contains('activo'))""",
                arg=actividad["nombre"],
            )
    elif flujos:
        esperados = [x["titulo"] for x in flujos]
        if textos != esperados:
            raise AssertionError(
                "flujos del lateral distintos: %r != %r"
                % (textos, esperados)
            )
        for flujo in flujos:
            print(
                "E2E %d px · flujo: %s" % (ancho, flujo["titulo"]),
                flush=True,
            )
            page.get_by_role(
                "button", name=flujo["titulo"], exact=True
            ).click()
            page.wait_for_function(
                """id => {
                  const flujo = document.querySelector('#flujo-' + id);
                  return flujo && flujo.offsetParent !== null &&
                    flujo.closest('section').classList.contains('activa');
                }""",
                arg=flujo["id"],
            )
    elif not page.locator("#menuIzq .menu-vacio").first.is_visible():
        raise AssertionError(
            "el lateral vacío no explica que todavía no hay flujos"
        )


def volver_a_vista_global(page, datos):
    """Tras recorrer el lateral, la SPA queda en la ÚLTIMA actividad, una sub-vista
    que oculta el `nav` de pestañas (plantilla.html: pintarVacia hace nav.hidden).
    El botón del mapa dispara `seleccionar('mapa')` y restaura la vista global con
    pestañas; una navegación por hash (#resumen) NO sirve: el visor lee el hash una
    sola vez al arrancar y no escucha `hashchange` (issue #3). En proyectos sin mapa
    el lateral ya deja una vista con nav, así que no hay nada que restaurar."""
    if not datos.get("actividades"):
        return
    page.get_by_role("button", name="🗺 El mapa", exact=True).click()
    page.wait_for_function(
        """() => Array.from(document.querySelectorAll('#menuIzq button'))
          .some(b => b.textContent.trim() === '🗺 El mapa' &&
                     b.classList.contains('activo'))"""
    )


def pestana_si_existe(page, nombre):
    """El botón de la pestaña si el visor decidió pintarla, o None. Qué pestañas
    existen lo decide plantilla.html (p.ej. 'Por persona' exige actores + flujos o
    superficie); en vez de reimplementar esa lógica en Python —y desalinearse: `!!{}`
    es true en JS pero `{}` es falso en Python— se pregunta al DOM ya en la vista
    global."""
    boton = page.get_by_role("button", name=nombre, exact=True)
    return boton if boton.count() else None


def comprobar_contrato_e2e(page, datos):
    pruebas = datos.get("pruebas_e2e") or []
    restricciones = ((datos.get("superficie") or {}).get("permisos") or {}).get(
        "restricciones"
    ) or []
    actores = datos.get("actores") or []

    volver_a_vista_global(page, datos)

    permisos = ((datos.get("superficie") or {}).get("permisos") or {})
    boton_actores = pestana_si_existe(page, "Por persona") if actores else None
    if boton_actores is not None:
        boton_actores.click()
        comprobar_actores(page, actores, permisos)

    if pruebas and pestana_si_existe(page, "Las entregas") is not None:
        page.get_by_role("button", name="Las entregas", exact=True).click()
        texto_recorridos = page.locator("#s-recorridos").inner_text().casefold()
        for prueba in pruebas:
            if str(prueba.get("id")).casefold() not in texto_recorridos:
                raise AssertionError("la selección %s no aparece en Recorridos" % prueba.get("id"))

    if restricciones and pestana_si_existe(page, "Por dónde se usa") is not None:
        page.get_by_role("button", name="Por dónde se usa", exact=True).click()
        texto_superficie = page.locator("#s-superficie").inner_text().casefold()
        for restriccion in restricciones:
            if str(restriccion.get("id")).casefold() not in texto_superficie:
                raise AssertionError(
                    "la restricción %s no aparece en Superficie" % restriccion.get("id")
                )


def comprobar_actores(page, actores, permisos):
    tarjetas = {
        candidata.locator(".tarjeta-cabecera .nombre").inner_text(): candidata
        for candidata in page.locator("#s-actores .tarjeta").all()
    }
    for actor in actores:
        tarjeta = tarjetas.get(actor.get("nombre", ""))
        if tarjeta is None:
            raise AssertionError("no aparece la ficha de %s" % actor.get("nombre"))
        texto_tarjeta = tarjeta.inner_text().casefold()
        for valor in (
            actor.get("nombre"),
            actor.get("rol"),
            actor.get("organizacion"),
            actor.get("estado"),
            *(actor.get("grupos") or []),
        ):
            if valor and str(valor).casefold() not in texto_tarjeta:
                raise AssertionError(
                    "la identidad %r no aparece en la ficha de %s" %
                    (valor, actor.get("nombre"))
                )
        rol_canonico = str(actor.get("rol") or "").casefold()
        rol_legacy = str(actor.get("nombre") or "").casefold()
        filas_roles = permisos.get("roles") or []
        rol = (
            rol_canonico
            if any(
                str(fila.get("rol") or "").casefold() == rol_canonico
                for fila in filas_roles
            )
            else rol_legacy
        )
        grupos = {str(g).casefold() for g in actor.get("grupos") or []}
        efectivas = {
            accion
            for fila in filas_roles
            if str(fila.get("rol") or "").casefold() == rol
            for accion in fila.get("permitidas") or []
        }
        efectivas.update(
            accion
            for fila in permisos.get("grupos") or []
            if str(fila.get("grupo") or "").casefold() in grupos
            for accion in fila.get("permitidas") or []
        )
        for accion in efectivas:
            if str(accion).casefold() not in texto_tarjeta:
                raise AssertionError(
                    "%s no muestra el permiso efectivo %r" %
                    (actor.get("nombre"), accion)
                )


def main():
    if sync_playwright is None:
        sys.exit(FALTA_PLAYWRIGHT)
    parser = argparse.ArgumentParser(
        description="Valida con navegador real el lateral del visor"
    )
    parser.add_argument("--datos", required=True)
    args = parser.parse_args()
    ruta = Path(args.datos).resolve()
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        chrome = encontrar_chrome()
        proceso, url = arrancar_visor(ruta)
        try:
            with sync_playwright() as playwright:
                opciones = {"headless": True}
                if chrome:
                    opciones["executable_path"] = chrome
                browser = playwright.chromium.launch(**opciones)
                try:
                    for ancho in ANCHOS:
                        page = browser.new_page(
                            viewport={"width": ancho, "height": 900}
                        )
                        page.set_default_timeout(8000)
                        page.goto(url + "#resumen")
                        comprobar_lateral(page, datos, ancho)
                        comprobar_contrato_e2e(page, datos)
                        page.close()
                finally:
                    browser.close()
        finally:
            if proceso.poll() is None:
                proceso.terminate()
                proceso.wait(timeout=5)
    except (
        OSError,
        ValueError,
        RuntimeError,
        AssertionError,
        PlaywrightError,
    ) as exc:
        sys.exit("ERROR: menú lateral inválido: %s" % exc)

    cantidad = len(datos.get("actividades") or datos.get("flujos") or [])
    print(
        "OK: menú lateral visible y navegable "
        "(%d entradas, anchos %s)." %
        (cantidad, ", ".join(str(x) for x in ANCHOS))
    )


if __name__ == "__main__":
    main()
