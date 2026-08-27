# ADR-037 · El método es el mismo con Codex que con Claude: la tabla de la regla 10 es por harness

**Fecha:** 2026-08-27 · **Estado:** aceptada · **Enmienda** a ADR-033 (el «subagente del padre»
vale para los dos harness) y a la regla 10 tal y como la escribía `roles.md` · **Modifica:**
`repo_config.plan_de_modelo`, el argv de Codex en `ejecucion.py` y los hooks del bootstrap

## Contexto

El método nació sobre Claude Code y se le fue quedando encima. Tres piezas eran solo-Claude, y
`roles.md` lo daba por inevitable con una frase que sonaba a ley de la naturaleza: «**Codex
queda INEJECUTABLE bajo la regla 10**».

1. **La tabla de modelo y esfuerzo** (regla 10, ADR-016) eran identificadores de Anthropic.
2. **El lanzador vetaba el modelo en Codex**: `argv_harness` levantaba «`--modelo` solo aplica
   al harness claude» y el recibo salía con `modelo: null`, `modelo_origen: harness-sin-tabla`.
3. **Los hooks del método** (canario del contexto y aviso sonoro) vivían solo en
   `.claude/settings.json`, anclados a `$CLAUDE_PROJECT_DIR`.

Nate, 27-08: «luego tenemos que asegurarnos que tooodo esto funciona con codex eh, tiene que
funcionar igual con codex que con claude». La investigación acotada de la petición
`P-20260827-9630b5c1` demostró contra el binario instalado (`codex-cli 0.149.0`) que las tres
carencias eran del MÉTODO, no de Codex: hay subagentes gestionables por el padre (`spawn_agent`,
`send_input`, `wait_agent`, `close_agent`), hooks con los mismos eventos y más, y modelo y
esfuerzo fijables por invocación. Las tres, activas por defecto.

Las pruebas de riesgo de la unidad 100 corrigieron tres suposiciones de esa investigación —lo
que sigue está probado corriendo el binario, no leyendo su documentación—, y una de ellas
obligó a parar y escalar (regla 8). Están en el «Cómo se probó», abajo.

## Decisión

1. **La tabla de la regla 10 es POR HARNESS**, no una lista de modelos. `plan_de_modelo(carril,
   rol, harness=…)` responde para los dos. La regla no cambia: el carril fija el esfuerzo y el
   revisor jamás repite el modelo del constructor. Lo único que cambia es de dónde salen los
   nombres.
2. **Los identificadores de OpenAI NO se memorizan: se consultan.** El catálogo sale de
   `codex debug models` (el del binario instalado, una vez por sesión y cacheado) y la elección
   es **por posición**: constructor = el primero de los visibles, revisor = el siguiente,
   pequeño = el último. Un slug escrito en el código es un slug que caduca en silencio; un
   test prohíbe que aparezca ninguno. Si el catálogo no se puede leer, se para nombrando la
   salida — nunca se inventa un modelo.
3. **El recibo de Codex ACREDITA en vez de declarar.** El lanzador lee el evento `turn_context`
   del rollout de la sesión y escribe `model_slug` (lo que corrió) junto a `requested_model` y
   `requested_reasoning_effort` (lo que se pidió), con `modelo_origen: harness-acreditado`. Es
   una garantía MÁS FUERTE que la del camino Claude, donde el recibo solo puede declarar.
4. **El subagente del padre de ADR-033 vale para los dos harness.** Lo que allí era el Agent
   tool de Claude Code es `spawn_agent` / `send_input` / `wait_agent` / `close_agent` en Codex:
   las cuatro operaciones que ADR-033 exigía —lanzar, hablarle, esperarlo y cortarlo— existen y
   son estables. `subagente.py` no depende del harness, solo del PID.
5. **Los hooks del método se publican también como `.codex/hooks.json`**, con los mismos
   guardianes y la raíz resuelta por `git rev-parse --show-toplevel`, porque Codex no tiene
   equivalente a `$CLAUDE_PROJECT_DIR`. El bootstrap los siembra igual que los de `.claude/`.
6. **El revisor Codex conserva la frontera del revisor Claude**, no una más dura. Ver abajo.

## Cómo se probó (y qué se cayó al probarlo)

Nada de esto sale de la documentación de Codex: sale de correr el binario 0.149.0 en la máquina
de Nate, con `stdin` cerrado y `CODEX_HOME` efímero, o sea en las condiciones reales del
lanzador. La evidencia cruda quedó en los hallazgos de la unidad 100.

- **Las aprobaciones NO cuelgan a un subagente anidado.** Era el riesgo que podía tumbar el
  punto 4. Un `spawn_agent` que intenta una acción denegada por el sandbox falla rápido y el
  padre sigue: `approval_policy` es `never` en `codex exec`, así que no hay aprobación que
  encallar. El modo de fallo que ADR-033 quería matar no existe aquí.
- **`codex exec --json` NO emite el modelo.** La investigación lo dio por hecho leyendo cadenas
  del binario; corriéndolo, el flujo son cuatro eventos y ninguno habla de modelo (esos nombres
  son de telemetría interna). De ahí el punto 3, y de ahí que el argv de Codex **pierda
  `--ephemeral`**: es justo lo que impide escribir el rollout. El aislamiento no se resiente,
  porque lo da el `CODEX_HOME` temporal, que se borra al terminar.
- **Los hooks tienen DOS puertas y las dos fallan CALLADAS.** `--ignore-user-config` no es solo
  «no leas el config del usuario»: apaga la capa de configuración entera, hooks del `.codex/`
  DEL REPO incluidos. Y un hook del repo no corre hasta que alguien confía su hash; si nadie lo
  ha hecho, la salida es idéntica a la de un repo sin hooks. Por eso el lanzador retira
  `--ignore-user-config` (no hacía falta: el `CODEX_HOME` efímero solo lleva `auth.json`) y
  pasa `--dangerously-bypass-hook-trust`. En sesión interactiva se confían una vez con `/hooks`.
- **`-s read-only` es absoluto.** La investigación proponía usarlo para el revisor Codex como
  «frontera más dura». Probado: bajo ese sandbox, `--add-dir` y
  `sandbox_workspace_write.writable_roots` se ignoran y no queda **ninguna** ruta escribible —
  el `permission_profile` sale con una sola entrada de lectura sobre la raíz. El revisor tiene
  exactamente una escritura obligatoria, su veredicto y su firma en `hallazgos.md`, así que su
  recibo saldría siempre vacío. El constructor paró (regla 8) y el padre decidió retirar
  `-s read-only`: el revisor Codex queda con la frontera del revisor Claude (cwd + contrato,
  ADR-022). Los perfiles de permisos gestionados, si alguna vez se quieren, son otra unidad.

## Consecuencias

- `roles.md` pierde el párrafo «Codex queda INEJECUTABLE», que a fecha de hoy era falso, y gana
  la tabla por harness. El despacho delegado —constructor y revisor— vale con los dos.
- Un workspace del método trae los dos guardianes de sesión también para quien abra Codex: hasta
  ahora, quien trabajaba con Codex se quedaba sin canario y sin aviso, y nadie lo había notado.
- **Lo que NO cambia:** el camino Claude, ni en modelo, ni en recibo, ni en hooks, ni en la web
  (que ya era agnóstica). La paridad se consigue añadiendo, no moviendo lo que funciona.
- **Coste asumido:** el argv de Codex depende ahora de tres detalles de comportamiento de
  `codex-cli` que no están en su documentación (el rollout como fuente, y las dos puertas de los
  hooks). Los tres tienen test con doble, pero una versión futura del binario puede moverlos:
  el síntoma será un recibo que declara en vez de acreditar, y el recibo lo dice en su
  checkpoint `modelo-acreditado` en vez de callárselo.
- **Fuera de alcance:** Codex en Windows (va a su matriz), los `permission_profiles`
  gestionados, y llevar la acreditación por rollout también al harness Claude — que merece
  considerarse, porque hoy su recibo solo puede declarar.
