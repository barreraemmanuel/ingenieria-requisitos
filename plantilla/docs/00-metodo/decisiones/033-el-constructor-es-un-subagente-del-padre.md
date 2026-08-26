# ADR-033 · El constructor es un subagente del padre, no un `claude -p` aparte

**Fecha:** 2026-08-26 · **Estado:** aceptada · **Supera** a la parte de ADR-022 que hacía de
`ejecucion.py` el único lanzador de constructores · **Modifica:** las reglas duras 1 y 15

## Contexto

ADR-022 nació de un incidente real (un constructor que arrancó en `main/` y una variable vacía
que lo sacó del worktree) y resolvió bien lo que quería resolver: cwd, rama y entorno fijados
por código, con recibo. Pero lo hizo a un precio que no se discutió entonces: el constructor
pasó a ser un proceso `claude -p` independiente —safe mode, sin MCP, sin sesión— que el padre
solo podía vigilar por su recibo en `.runtime/ejecuciones/` y por lo que él quisiera escribir
en `hallazgos.md`. Ni verlo pensar, ni preguntarle, ni redirigirlo, ni cortarlo salvo matando
el proceso. La prosa del método lo llamaba «subagente»; el script hacía otra cosa.

El 26-08-2026 Nate lo vio arrancar en la unidad 082 y lo paró: «¿no sería mejor que fueran
subagentes tuyos?», «¿por qué los ejecutas así?». ADR-017 ya había argumentado lo mismo para
exprés/directo (la delegación es lo que produce la caja negra) y dejó normal/completo fuera solo
por el tamaño del contexto, no por el aislamiento.

Lo que ADR-022 protegía se cubre hoy sin proceso aparte: un subagente del padre puede nacer con
el worktree de la unidad como cwd y frontera de escritura, con el modelo de la tabla de la regla
10 fijado por quien lo abre, y con el contrato como único encargo. Lo que NO se cubre igual es
el recibo firmado con leases y diff inicial/final — y eso importa donde se firma algo: la
revisión.

## Decisión

1. **En normal y completo el constructor es un subagente del propio padre.** Aislado en
   `worktrees/NNN-slug/` (cwd y frontera de escritura), con el modelo y el esfuerzo que
   `repo_config.plan_de_modelo(carril, "constructor")` da al carril, y con el encargo que
   `unidad.py despachar` imprime. El padre lo gestiona: parte por casilla, silencio máximo de
   5 minutos, corte si se desvía del contrato (regla 8).
2. **El revisor no cambia:** agente fresco de solo lectura, modelo distinto, lanzado por
   `ejecucion.py lanzar … --rol revisor`. Su recibo es lo que `unidad.py cerrar` lee para
   acreditar la firma; una revisión sin recibo sigue sin valer.
3. **`ejecucion.py` deja de ser obligatorio para construir** y queda como vía opcional: Codex,
   sesiones desatendidas, o cuando el usuario quiera un proceso que sobreviva a la sesión del
   padre. Nada de lo que verifica (cwd, rama, leases, recibo) se retira.
4. **La frontera de escritura del constructor no se relaja:** su worktree, `hallazgos.md` y las
   casillas del plan (regla 2), y ni un `git` en el meta-repo.

## Consecuencias

- El usuario ve construir la unidad en la conversación donde la pidió y puede pararla en el
  minuto tres. Es la misma ganancia que ADR-017 dio al carril directo, extendida a los carriles
  donde más se tardaba a ciegas.
- Se pierde, para el constructor, el recibo con leases y diff de `ejecucion.py`. Se acepta: el
  rastro del constructor son su rama, su PR y su `hallazgos.md`, y lo que hay que acreditar
  —la revisión— sigue con recibo.
- El padre carga con el avance del subagente en su contexto (resumen, no ficheros). El canario
  sigue midiéndolo; si una unidad no cabe, la unidad es demasiado grande (regla 16).
- Un constructor lanzado por `ejecucion.py` no es un error: es la excepción declarada del
  punto 3 y su recibo se lee igual que antes.
- ADR-022 sigue vigente para todo lo demás: derivación de unidad → worktree → rama, saneado del
  entorno, skills, recibo del revisor.

## Verificación

- `visor/tests/test_constructor_subagente_del_padre.py`: el despacho de una unidad normal
  imprime el encargo del subagente (worktree, modelo, esfuerzo) y no un
  `ejecucion.py lanzar … --rol constructor`; las reglas 1 y 15 y los runbooks ya no mandan
  construir por `ejecucion.py`; este ADR viaja en `bootstrap.py`.
- `python3 docs/00-metodo/scripts/lint_metodo.py` → sin FAIL nuevo.
