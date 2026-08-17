# ADR-027 · El entorno limpio del launcher también tiene que serlo en Windows

**Fecha:** 2026-08-16 · **Estado:** aceptada · Corrige `ejecucion.py` (ADR-022, ADR-024) sin
tocar su diseño · Decidida por el usuario en sesión, con la evidencia delante

## Contexto

La unidad 012 quitó el sandbox de SO de `ejecucion.py` y con eso **Windows nativo volvió a ser
camino de primera**: cayó el P0 de mudar el taller a Linux. El propio ESTADO lo dejó anotado con
una advertencia honesta: «la puerta se abrió, **no está probada** — el primer despacho real es la
prueba».

El 2026-08-16 llegó ese primer despacho real —la unidad `002-fichas-de-cliente-y-lugar`— y la
puerta estaba cerrada. El constructor murió antes de arrancar:

```
CHECKPOINT lease ok: unit:002-fichas-de-cliente-y-lugar#2, …
CHECKPOINT identidad ok: …\worktrees\002-fichas-de-cliente-y-lugar · rama 002-…
CHECKPOINT harness fail: exit 3221226505
```

`3221226505` es `0xC0000409`, el fail-fast de Windows: el proceso se aborta **antes de su
`main()`**, sin mensaje. La causa está en `entorno_base()`, que construye un entorno limpio
desde la allowlist `HEREDAR_ENV`. Esa lista es **puramente POSIX** —`PATH`, `TERM`, `LANG`,
`HOME`, `SHELL=/bin/sh`…— y no contiene ni una variable de Windows. Un ejecutable nativo de
Windows sin `SystemRoot` no encuentra las DLL del sistema y muere ahí mismo.

Aislado con una prueba de dos líneas, mismo ejecutable y mismo entorno:

| entorno | resultado |
|---|---|
| allowlist actual, sin `SystemRoot` | `exit 3221226505` |
| la misma **más `SystemRoot`** | `exit 0` · `2.1.229 (Claude Code)` |

Una variable. El diseño de ADR-022/024 —allowlist explícita por higiene, no heredar el entorno
entero— **es correcto y no se toca**: lo que estaba mal era dar por universal una lista escrita
para un solo sistema operativo.

## Decisión

`HEREDAR_ENV` incorpora el **mínimo de variables que Windows necesita para que un proceso nativo
arranque**, con el mismo criterio de higiene que ya regía: nombres explícitos, uno a uno, y el
filtro `if os.environ.get(clave)` que ya existía las omite solas en Linux y macOS, donde no
existen. No se hereda el entorno entero, no se añade lógica por plataforma y no cambia ninguna
frontera de seguridad: estas variables dicen dónde está el sistema, no quién eres.

Y una regla que se lleva más lejos que este bug: **una puerta que se declara abierta no lo está
hasta que algo pasa por ella.** La unidad 012 dio por bueno Windows nativo sin ejecutar un
despacho real; el ESTADO lo anotó y aun así se planificó encima. Cuando el método declare
soportada una plataforma, el primer despacho real en ella es parte de la unidad, no del futuro.

## Consecuencias aplicadas

- `ejecucion.py` lanza constructores y revisores en Windows nativo. La unidad 002 se despachó
  por el canal canónico inmediatamente después, sin ningún otro cambio.
- El incidente queda en la caja negra como P0 (`0d9d301b-a33e-4b32-9a64-c178ad1515a0`) con la
  evidencia del recibo y la prueba de las dos líneas.
- **El arreglo tiene que viajar aguas arriba.** El método llega desde la plantilla de Nate y un
  parche local se pierde —o peor, se disfraza de regresión— en la próxima actualización. Hasta
  que esté integrado allí, Modo D debe conservar esta línea: si la comparación posterior a una
  actualización ve desaparecer las variables de Windows de `HEREDAR_ENV`, **eso es la regresión**,
  no el arreglo.

## Límites

Esto NO reabre el debate del sandbox de SO (unidad 012) ni cambia lo que el launcher aísla:
sigue sin heredarse el entorno completo, el `HOME` del harness sigue siendo el que decide
`preparar_claude_home`/`preparar_codex_home`, y los secretos siguen entrando solo por los
nombres ya declarados. Tampoco convierte el workspace en el sitio donde se arregla el método
(ADR-026 sigue vigente): es una excepción nombrada, con su envío aguas arriba como parte de la
decisión, porque el fallo **bloqueaba sin salida** la única plataforma que el método declaraba
de primera — justo lo que ADR-026 llama un bug del método.
