# Fixture de la reforma · comandos adjudicados uno a uno

**Fecha de extracción: 2026-09-02.** Corpus del que sale: 12.397 llamadas reales a
Bash/Edit/Write/MultiEdit/NotebookEdit de este taller (Claude Code 12.084 · Codex 313),
de 49 sesiones y 155 subagentes.

`comandos-adjudicados.jsonl` es la **muestra pública** de ese corpus: 152 casos revisados a
mano, uno a uno, para medir si un guardián que decide por **la ruta a la que va** un comando
—y no por cómo está escrito— para las escrituras prohibidas en `main/` sin estorbar el
trabajo de todos los días. Lo usan `visor/tests/test_guardian_rutas.py` (suite rápida) y
`visor/tests/nightly/test_replay_corpus.py` (corpus entero).

## Qué hay dentro

| `categoria` | Casos | Qué es | `esperado` |
|---|---|---|---|
| `escritura_real` | 9 | escrituras en `main/` que **ocurrieron de verdad** en los rollouts | `deny` |
| `rodeo` | 32 | las formas de `verificacion-02-arreglos-2-y-6.md` §2: la puerta de al lado que un agente bloqueado probaría | `deny` |
| `legitimo` | 87 | lo que se teclea a diario y **no puede bloquearse** | `allow` |
| `irresoluble` | 24 | `rm -r` con `$VAR`, `~` o `*` que no se deja resolver | `aviso` |

Campos de cada línea: `id`, `herramienta`, `entrada`, `cwd`, `raiz`, `esperado`, `categoria`,
`motivo` (por qué se adjudicó así) y `origen`. **`origen`** es el id del registro en el corpus
cuando el caso está copiado literalmente de un rollout, o `sintetico` cuando está escrito a
mano con la forma de uno real (los rodeos que nadie ha usado todavía para escribir, y los
casos reales cuyo texto lleva prosa privada que no puede viajar a un repo público).

## Privacidad

El repo es público y el corpus completo **no cabe aquí**: lleva nombres, correos y prosa de
bugs. La anonimización se hace en el extractor, en el origen, no después: `/Users/<quien sea>`
→ `/Users/agente`, correos → `correo-oculto`, el scratchpad → `/tmp/agente/scratchpad`, y el
nombre del dueño de la máquina → `agente`. `test_guardian_rutas.py` lee esta fixture entera y
falla si encuentra un `@`, una ruta de usuario real o un nombre propio de la lista.

Los marcadores no llevan `<`, `>` ni `@` a propósito: dentro de un comando, `<x>` son dos
redirecciones, y un marcador con corchetes angulares se inventaba destinos de escritura que
nunca existieron (20 rechazos falsos en la primera medición).

## Cómo se regenera

```sh
# el corpus completo, fuera de git, en la máquina del dueño (~1 s)
python3 visor/tests/extraer_replay.py --privado          # → .runtime/replay/comandos.jsonl

# solo las llamadas ya adjudicadas aquí, por su id
python3 visor/tests/extraer_replay.py --publico

# nombres extra que tapar, además del usuario de la máquina
REPLAY_NOMBRES="apellido,empresa" python3 visor/tests/extraer_replay.py --privado
```

Los casos con `origen` real se vuelven a buscar en el corpus por ese id: si el texto ya no
coincide, `nightly/test_replay_corpus.py` lo dice en vez de callarse.

## Cuando aparezca un caso nuevo

Un `deny` nuevo sobre el corpus **no se arregla subiendo el tope** del nightly: se adjudica a
mano, se añade aquí con su `motivo`, y solo entonces cuenta. Igual una escritura en `main/`
que se escape: es un caso para esta fixture antes que un parche al guardián.
