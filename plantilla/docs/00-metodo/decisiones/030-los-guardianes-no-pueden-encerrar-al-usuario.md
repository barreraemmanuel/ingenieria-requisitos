# ADR-030 · Dos guardianes que encerraban al usuario: la huella de los planos y el proceso cancelado

**Fecha:** 2026-08-18 · **Estado:** aceptada · Aplica ADR-026 a dos gates concretos · **Debe a Nate un PR**
· **Renumerada de 028 a 030 el 2026-08-20**: upstream tomó el 028 en la 1.7.x. Vivía solo
dentro de un workspace y por eso no viajaba; desde hoy vive en la plantilla, como las demás.

## Contexto

ADR-026 fijó la regla: *un control que deja a la persona atrapada trabaja contra el propósito
del método*, y **un gate sin salida escrita es un bug del método**. El 2026-08-18, construyendo
la tanda 1 del ERP de transporte, se toparon dos gates que hacen exactamente eso. Ninguno
protege de daño irreversible; los dos paran la obra en seco.

### 1 · `huella_planos_actual()` revienta siempre, y sin ella no se puede abrir NINGUNA unidad

La función —duplicada en `peticion.py` y en `lint_metodo.py`— recorre las actividades de
`docs/02-flujos/planos/planos.json` y abre el `planos.json` de cada una:

```python
rutas.extend(
    mapa.parent / "actividades" / actividad["id"] / "planos.json"
    for actividad in raiz.get("actividades", [])
)
```

**Una actividad solo tiene `planos.json` cuando se especificó.** Las que están fuera de alcance
o todavía sin abrir tienen solo su `mural.md`. En este workspace eran 8 de 45 ese día, y 14 de
45 dos días antes. O sea que la función falla **siempre**, en cualquier proyecto, hasta que la
última actividad del mapa esté escrita — que es justo cuando ya no hace falta.

Las dos copias tratan el fallo distinto, y por eso solo una se nota:

| Copia | Al no encontrar el fichero | Efecto |
|---|---|---|
| `lint_metodo.py` | `except OSError: return None` | degrada en silencio, el linter pasa |
| `peticion.py` | `except OSError: raise ErrorPeticion(...)` | **`evaluar` es imposible → `unidad.py nueva` rechaza → no se construye nada** |

Y la huella no es opcional: `evaluar` la exige para cualquier `--ruta`, no solo al anclar en un
flujo. El mensaje de bloqueo de `unidad.py nueva` —«no está evaluada en revisión 1»— **no nombra
ninguna salida**, que es la definición de bug de ADR-026.

### 2 · Un proceso `cancelado` cierra la petición pero deja el linter en FAIL para siempre

`peticion.py` trata `{terminal, sustituido, cancelado}` como estados acabados (líneas 1524 y
1681) y por eso deja cerrar la petición. `lint_metodo.py` exige que **todo** enlace `satisface`
esté en `terminal` (línea 596) y falla con «entregada con procesos no terminales».

**Dos guardianes del mismo método, con dos definiciones distintas de «terminado».** Como
`unidad.py cerrar` aborta si el linter falla, un solo proceso cancelado bloquea el cierre de
**todas** las unidades futuras del workspace. Agrava que `abrir-expres` crea el enlace como
`satisface` y ningún comando permite reetiquetarlo: `marcar-proceso` solo ofrece `terminal` o
`cancelado`, o sea que el método te obliga a elegir el valor que él mismo rechaza después.

El caso real: se abrió carril exprés para subir una dependencia, el `AGENTS.md` del repo de
código lo prohibía —«subir una versión es una unidad de tipo `migracion`»—, se abandonó el
exprés como manda el método… y el workspace quedó con un FAIL permanente.

## Decisión

**Los dos gates pasan a guiar en vez de encerrar, sin perder ni una garantía.**

1. **`huella_planos_actual()` salta las actividades que no tienen `planos.json`**, en las dos
   copias. Una actividad sin especificar no es un error: es el estado normal de un mapa en
   construcción. La huella sigue siendo un sha256 sobre el contenido real de los planos que
   existen, así que sigue detectando cualquier cambio; lo único que deja de hacer es explotar.
2. **`lint_metodo.py` acepta `{terminal, sustituido, cancelado}`** como estados acabados de un
   enlace `satisface`, exactamente los mismos que ya acepta `peticion.py`. La garantía que
   protegía —que una petición entregada no deje trabajo colgando— se mantiene entera: un
   proceso `evaluando` o `en obra` la sigue haciendo fallar.

**La fórmula de la huella no se inventa aquí: se comprobó.** Calculada saltando las actividades
sin ficha sobre el árbol del commit `8a9e21e`, reproduce **carácter por carácter** la huella
`d4f26cb3ea776636283a0fb4a446ae47681ff2067964ff661d78b44e33d7e21f` que quedó grabada en
`P-20260816-86fa77c3`, la petición que produjo la unidad 002. Es la prueba de que ese `if` es lo
único que le faltaba a la función y de que ninguna huella histórica se invalida.

## Consecuencias

- Se puede volver a evaluar peticiones y abrir unidades sin calcular la huella a mano.
- Se puede volver a cerrar unidades después de abandonar un enfoque, que es el caso normal:
  se prueba un carril, no era, se cambia.
- **Ninguna huella anterior cambia de valor**, así que las peticiones ya evaluadas siguen
  válidas y `comprobar-revision` sigue diciendo la verdad.
- **Se debe un PR a Nate**, como ADR-027. Hasta que llegue, `setup.py` puede traer la versión
  de arriba y revertir estas dos líneas: si vuelven los síntomas de §Contexto, es eso.
  El detalle operativo y las otras dos trampas de `evaluar` —`--ruta` es el TIPO de unidad y no
  el carril, y `--ruta-codigo` va sin `main/` delante— están en
  `docs/conocimiento/la-huella-de-los-planos-salta-las-actividades-sin-ficha.md`.

## Estado al 2026-08-20 · qué sobrevivió a la 1.7.3

Al traer de la 1.3.0 a la 1.7.3 se comprobó decisión por decisión:

- **§1 (la huella) la adoptó upstream** en la 1.5.0, con la misma semántica y además un aviso
  por `stderr` («actividad X sin planos todavía: fuera de la huella hasta que exista»). El
  parche local sobra y se retira: manda su versión.
- **§2 (el linter y `cancelado`) NO la adoptó, y su versión revirtió la nuestra** — el escenario
  que esta misma ADR anticipó en §Consecuencias. Su `lint_metodo.py` sigue incoherente consigo
  mismo: la comprobación de `abiertos` (línea 598) trata `{terminal, sustituido, cancelado}`
  como acabados y doce líneas más abajo exige `terminal` para todos. Reaplicado, esta vez **en
  `plantilla/`**, que es lo que faltaba: el parche anterior se aplicó solo dentro del workspace
  y por eso ningún rebase lo protegía.
- Evidencia del rojo que reapareció: `P-20260818-24c59c2c` (`satisface` a un exprés `cancelado`
  más la unidad `004-sqlparse-al-dia` `terminal`). Registrado en la caja negra como P1.

## Límites

No relaja ningún gate de daño irreversible. No toca quién puede escribir dónde, ni la revisión
fresca, ni el OK del usuario sobre la app, ni las puertas de seguridad: los dos cambios son
sobre cuándo un guardián considera que algo está *acabado* o *ausente*, no sobre qué se permite.
