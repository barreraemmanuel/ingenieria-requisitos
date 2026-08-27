# ADR-036 · Paralelizar por defecto: el freno es el fichero compartido, no un flag que hay que recordar

**Fecha:** 2026-08-27 · **Estado:** aceptada · Extiende ADR-027 y ADR-033 · Reescribe la regla 5

## Contexto

ADR-027 retiró el tope numérico de unidades en vuelo y dejó el único gate real donde debía
estar: el cruce de `ficheros:` declarados. Pero no tocó el **defecto**. La regla 5 seguía
diciendo «UNA unidad de código por defecto» y `unidad.py despachar` bloqueaba con cualquier
cosa en vuelo salvo que se le pasara `--paralelo`. El resultado práctico: el método salía en
serie **por olvido**, no por decisión. Con diez contratos aprobados, la máquina ociosa y el
usuario esperando, bastaba con que nadie se acordara del flag para que el trabajo fuera de
uno en uno.

Petición `P-20260827-90195e7d` (Nate, 27-08): «es lento e ineficiente que solo trabajes con un
subagente pudiendo tener 20 trabajando en todos los contratos» · «si no hay choques el método
debería priorizar paralelizar al máximo».

La evidencia de que se puede: la noche del 26-27/08 se construyeron 10 unidades a la vez con
subagentes del padre (ADR-033), cada una en su worktree y con su recibo, sin más incidente que
la carga de la máquina cuando coincidían dos suites completas.

## Decisión

**El paralelismo es la norma.**

1. `unidad.py despachar` **sin flags** despacha aunque haya otras unidades en vuelo, siempre
   que los `ficheros:` declarados no choquen. El cruce de ficheros no se relaja en nada: con
   choque sigue bloqueando y nombrando la otra unidad y el fichero compartido, con su `SALIDA:`.
2. `--paralelo` deja de hacer falta. Se **sigue aceptando** —vive en runbooks y en sesiones ya
   abiertas— y solo imprime «ya es el defecto».
3. `--serie` es la nueva excepción: pide expresamente que la unidad vaya sola, bloquea si hay
   otra en vuelo y deja `paralelo: no` escrito en el registro de despacho (del lado de quien
   despacha, no del frontmatter que teclea el constructor).
4. `unidad.py estado` deja de tratar «más de una en vuelo» como anomalía —era exactamente lo
   que el método pide— y pasa a enseñar, por unidad en vuelo, el **subagente que la construye**
   leído de su recibo (`subagente.py`, `harness: subagente-del-padre`).
5. **El límite que ningún script puede imponer:** UNA suite completa a la vez. Desde una sesión
   no se ven las demás, así que esto vive en la prosa (regla 5 y `runbooks/cierre.md`), no en
   una puerta. Dos suites a la vez en esta máquina producen rojos de timeout que no son del
   código, y un rojo que no es del código enseña a ignorar los rojos.

## Alternativas descartadas

- **Un tope numérico ("hasta N a la vez")** — ya lo descartó ADR-027: el número no protege nada
  que la disjunción de ficheros no proteja, y envejece con la máquina.
- **Paralelizar también las suites** — es de donde vienen los rojos de timeout. La construcción
  va en paralelo; la verificación completa, de una en una.
- **Dejar el defecto en serie y "acordarse" del flag** — es el estado que esta decisión corrige.
  Una regla que depende de que alguien la recuerde no es una regla, es una intención.

## Consecuencias aplicadas

- `unidad.py`: se invierte el defecto de la precondición 5; `--serie` nuevo; `--paralelo`
  degradado a aviso; `cmd_estado` sin WARN de vuelo y con la columna de subagente; el rechazo
  por ficheros compartidos gana su `SALIDA:`.
- `AGENTS.md` regla 5, `roles.md` (CONSTRUCTOR) y `README.md` (§carriles) reescritos acordes.
- `runbooks/cierre.md`: la frase «UNA suite completa a la vez» junto al paso de la suite.

## Límites

Esta decisión no reparte trabajo entre sesiones distintas ni sabe nada de la carga de la
máquina: solo retira un freno que no protegía nada. Si dos unidades disjuntas en los papeles
resultan acopladas en el código, eso es un `ficheros:` mal declarado — y se arregla ahí, no
volviendo a la serie.
