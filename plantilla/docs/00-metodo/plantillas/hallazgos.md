---
unidad: NNN-slug
revisor: no              # LO ESCRIBE EL REVISOR, en la MISMA escritura que su veredicto: un
                         # agente FRESCO, en todos los carriles (ADR-017): solo lee código,
                         # y SU única escritura es este veredicto y esta firma.
                         # Prohibido siempre: que firme quien construyó —que en carril directo
                         # es el padre— y que la firma se rellene DESPUÉS de memoria. Si llega
                         # vacía, la revisión se perdió y se repite (`cierre.md`, paso 2).
revisado: no             # `no` | fecha YYYY-MM-DD de esa revisión. `unidad.py cerrar` la exige.
---

# NNN · Hallazgos de la obra

> Único fichero del meta que rellena quien construye (subagente, o el padre en carril
> directo). El padre lo cosecha en el cierre:
> promociones a conocimiento/, ADRs, nuevas unidades, correcciones al método.

## Plan

<Las casillas del plan viven AQUÍ, no en la ficha: `especificacion.md` corre en `0444`
mientras dura la obra (unidad 028) y el constructor no puede escribirla. `unidad.py despachar`
copia aquí el `## Plan de trabajo` del contrato al abrir la obra; quien construye marca `[x]`
EN EL MOMENTO en que termina cada paso, y de aquí lo leen `unidad.py estado` y el tablero.
La ficha se queda como contrato: sus casillas no se tocan.>

## Evidencia de verificación (obligatorio)

<La cabecera de abajo la comprueba `lint_cierre.py` y `unidad.py cerrar` la exige: el
«47/47 verdes» deja de creerse por estar escrito y tiene que cuadrar con algo que se pueda
volver a mirar. Se rellena con lo que EJECUTASTE, no de memoria. Los marcadores `—` no
valen: mientras sigan ahí, el cierre no pasa.>

```parte-de-cierre
veredicto: —                 # entregada | fallo (lo que de verdad salió)
tests_cmd: —                 # el comando exacto de la suite
tests_exit: —                # su código de salida (0 si verde)
tests_output: —              # .runtime/NNN-slug/tests.txt — la salida volcada, no pegada
tests_sha256: —              # shasum -a 256 <esa ruta>
build_cmd: —                 # el comando de build/lint
build_exit: —
build_output: —              # .runtime/NNN-slug/lint.txt
build_sha256: —
requisitos: —                # N/M cubiertos: M son los `- **Rn** —` de especificacion.md
plan: —                      # N/M casillas: contadas sobre el `## Plan` de aquí arriba
bloqueadores: —              # cuántos quedan abiertos (0 si ninguno)
```


```
<output real de la suite de tests + lint. Pegado, no resumido.>
```

<Capturas y volcados si hay UI: van a `.runtime/NNN-slug/` (fuera de git, ya existe) y aquí
se referencian por RUTA, nunca pegados. Lo sensible (credenciales, PII) va a `.private/`.>

## Contraprueba del criterio portante (normal y completo)

<Que los tests estén verdes no demuestra que MUERDAN: un test vacuo pasa igual exista o no el
comportamiento (ADR-030). Aquí se enseña que el test del **criterio portante** declarado en
§Verificación de la especificación se pone ROJO cuando se rompe a propósito lo que protege.
UNO solo, el portante: contraprobar todos los criterios sería un segundo desarrollo.
En carril **directo y exprés no se pide**, y en **bug** no va aquí: lo cubre el par ROJO→VERDE
del paso 7 de `runbooks/bug.md`. Prohibido `git stash` para deshacer la rotura —la pila es
única y compartida entre TODOS los worktrees—: se usa `git checkout -- <fichero>` o
`git restore <fichero>`.>

```contraprueba
criterio: —                  # el R-n portante, copiado de §Verificación de la especificación
test: —                      # el test concreto que lo protege
rotura: —                    # qué se rompió a propósito y dónde (fichero:línea, y el diff)
rojo: —                      # el fallo LITERAL, y tiene que nombrar el criterio: un rojo por
                             # un import roto o un error de sintaxis no prueba nada
restauracion: —              # cómo se deshizo (nunca `git stash`)
diff_tras_restaurar: —       # salida de `git diff HEAD` — vacía, pegada
punta_antes: —               # `git rev-parse HEAD` antes de romper
punta_despues: —             # `git rev-parse HEAD` después de restaurar — el mismo sha
verde_de_nuevo: —            # el test otra vez en verde tras restaurar
```

```
<los outputs literales: el rojo, el `git diff HEAD` vacío, los dos `git rev-parse HEAD` y el
verde final. Pegados, no resumidos: la restauración se DEMUESTRA, no se afirma.>
```

## Desviaciones de implementación

<El cómo cambió respecto a lo previsto, sin tocar el contrato. Si hubo desviación de
CONTRATO, esta unidad debió pararse — si estás escribiendo aquí en vez de haber parado,
explica por qué.>

- —

## Descubrimientos (candidatos a conocimiento/)

<Cosas aprendidas que le ahorrarían trabajo al siguiente: trampas de una librería,
comportamientos no documentados, comandos útiles.>

> **Cómo se cosecha esto** (lo hace el PADRE en el cierre, y `unidad.py cerrar` lo exige):
> cada viñeta acaba marcada con `→ promovido a <destino>` o con `→ descartado (motivo)`.
> Puede ir en cualquier punto de la viñeta —también en su última línea, que es donde cae
> natural— y admite negrita. Literalmente así:
>
> - El cliente de X reintenta en silencio: los timeouts hay que mirarlos en sus logs.
>   → promovido a `conocimiento/cliente-x.md`
> - Idea de cachear la home. → descartado (sin medición que lo justifique)

- —

## Trabajo descubierto (candidatos a nuevas unidades)

<Bugs vistos de pasada, deudas, mejoras. NO los arreglaste (fuera de alcance): los apuntas.>

<Los hallazgos que añade el REVISOR en el cierre —no el constructor— empiezan por `[revisor]`.
Es lo que permite, dentro de tres meses, distinguir una revisión de verdad de un constructor
que se puso un sello a sí mismo.>

<Un trabajo aceptado se captura **antes de crear otra unidad** y se marca literalmente
`→ promovido a P-ID`. Si se descarta: `→ descartado (motivo)`. Nunca “para luego”.>

- —

## Revisión (la rellena EL REVISOR, en el momento de revisar)

<Paso 2 del ritual de cierre: veredicto del revisor fresco (sesión/subagente nuevo, solo
lectura) sobre el diff contra la especificación, en TODOS los carriles (ADR-017). Lo escribe él,
de una sentada y antes de soltar la tarea: su veredicto aquí y su
nombre y la fecha en el frontmatter (`revisor:`, `revisado:`), que es lo que `unidad.py cerrar`
exige. El constructor no escribe en esta sección jamás. Una revisión sin firma no se firma
después — se repite.>

- **Veredicto:** LIMPIO | HUECOS DE CORRECCIÓN
- **Huecos** (si los hay; cada uno vuelve al constructor antes del merge):
  - —
- **Fecha:** YYYY-MM-DD
- **Validación del usuario sobre la app corriendo:** — <la escribe `unidad.py cerrar`>

<FRONTERA DEL REVISOR (regla del método, no preferencia): solo son huecos de corrección los
incumplimientos del contrato de ESTA unidad, los fallos de seguridad y la pérdida de datos.
Un riesgo de un flujo futuro, una mejora o un "esto convendría prepararlo para cuando…" NO
reabre la unidad: se anota arriba como trabajo descubierto y sigue su camino. Solo un fallo
crítico permite una segunda ronda.>

## Aprendizajes (los escribe QUIEN LOS APRENDIÓ, al terminar su parte)

<De **1-5 frases** por bloque: lo que sorprendió, lo que no volverías a hacer, lo que
hubieras querido saber al empezar. Si de verdad no hubo ninguno, se escribe `ninguno`
explícito — un hueco en blanco no distingue «no aprendí nada» de «se me olvidó». Cada frase
con fecha y quién: `- 2026-08-27 · constructor: …`. Lo escribe cada uno EN EL MOMENTO, no el
padre de memoria al cerrar: de aquí, y solo de aquí, sale lo que se promueve a
`conocimiento/` (`runbooks/cierre.md`, paso 7). Los marcadores `—` no valen: mientras sigan
ahí, `lint_cierre.py` no deja cerrar.>

```aprendizajes-constructor
- —
```

```aprendizajes-revisor
- —
```

## Bitácora del cierre (se marca AL TERMINAR CADA PASO, nunca al final)

<Si la sesión que cierra se corta a la mitad, esto es lo único que sabrá la siguiente: lo
marcado está hecho y no se repite; lo NO marcado no se da por hecho aunque el git lo insinúe.
Cada línea lleva su fecha y, si lo hizo otro (revisor, usuario, script), quién.>

- [ ] 1 · Evidencia de verificación pegada arriba — —
- [ ] 2 · Revisión fresca con veredicto y firma en el frontmatter — —
- [ ] 3 · Fusionado en la rama principal (commit: —) — —
- [ ] 4 · Tests en verde sobre la principal, al nivel del carril (`cierre.md` §4) — —
- [ ] 5 · App lanzada y OK del usuario (o `en_validacion` si no estaba) — —
- [ ] 6 · `unidad.py cerrar` ejecutado — —
- [ ] 7 · Deltas al mapa, hallazgos promovidos, `ESTADO.md` al día — —
