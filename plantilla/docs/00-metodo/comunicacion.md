# Cómo se le habla al usuario (detalle de la regla 16)

Lo esencial está en `AGENTS.md`. Aquí el detalle, que se lee cuando hace falta.

## Nada de jerga del método

**Si una palabra solo existe dentro de `docs/00-metodo/`, no sale por el chat.** Traducciones
fijas:

| Se dice… | …no esto |
|---|---|
| "un trabajo" | unidad |
| "hecho, a falta de que lo pruebes" | `en_validacion` |
| "una comprobación que bloquea" | hard-gate |
| "un cambio de una línea" | exprés |
| "un cambio pequeño que encaja donde ya está" | carril directo |
| "una copia aparte del código para no tocar lo bueno" | worktree |
| "una decisión que dejamos escrita" | ADR |
| "la revisión de limpieza del proyecto" | sanidad |

`cupo`, `meta-repo`, `NNN`, `frontmatter`, `linter`: o se dicen por lo que son, o no se dicen.
Nombres de fichero y de script SÍ, con lo que hacen al lado — "he tocado papeles" no informa de
nada.

## El parte de avance

La señal **ya existe**: el plan de trabajo se marca casilla a casilla según se hace y
`hallazgos.md` se escribe sobre la marcha. El trabajo aquí no es fabricarla, es **sacarla**.

- **Una línea por casilla, en cuanto se marca.** En cristiano y con lo que significa para él:
  *"He escrito la prueba del filtro por fechas; está en rojo, como toca. Ahora lo implemento."*
- **Antes de empezar, la previsión**: cuántos pasos son y cuánto va a durar más o menos.
  **Pasos, no porcentajes** — un porcentaje que no se sabe calcular es una mentira con cifras.
  Y **jamás "ya casi"**: si no se sabe, se dice que no se sabe.
- **Silencio máximo: 5 minutos.** Si se van a superar, se avisa ANTES: qué se está haciendo y
  cuánto queda. Es lo que le permite cortar en el minuto tres en vez de en el cuarenta.
- **Si el silencio no cabe en su paciencia, la unidad es demasiado grande**: se trocea. El
  tamaño de la unidad ES la frecuencia del parte.
- **Atascado se dice, no se disimula.** Dos intentos con el mismo error, o el mismo comando
  repetido, se cuentan en vez de seguir probando en silencio.

Y un aviso que conviene tener presente: **enseñar el trabajo hace la espera más llevadera, pero
el efecto se invierte si el resultado es malo.** Contar bien lo que se hace sube la apuesta, no
sustituye a acertar.

## Pedir un OK: se ejecuta un comando, no se recuerda una costumbre

Nunca se pide a ciegas, y nunca depende de que el agente se acuerde de enseñar una web: los
dos OK del método tienen COMANDO, y el comando abre el navegador solo.

- **OK sobre un contrato** (aprobar una unidad o un bug): `unidad.py nueva <tipo> <slug>
  --desde P-ID` y `unidad.py estado` levantan el visor de contratos y lo abren en el contrato
  sin aprobar. A mano: `python3 main/visor_contratos/servir.py --workspace . --minutos 0`.
- **OK sobre una entrega** (probar lo entregado, paso 5 de `runbooks/cierre.md`):
  `python3 docs/00-metodo/scripts/unidad.py validar NNN-slug` — genera la validación guiada
  desde la ficha, levanta el visor de presentaciones y la abre. El usuario decide ahí
  (`confirmado` / `problema`) y su decisión queda en un recibo que el cierre lee.

Pegar el markdown o la tabla en el chat es un RESUMEN de lo que ya tiene delante, no el
camino por el que se da el OK. Si no hay pantalla (`--sin-navegador`, una sesión sin
escritorio), los comandos lo dicen e imprimen la dirección: nadie se queda esperando a
ciegas a que el agente se acuerde.

## Cuando se te necesita, suena

Un agente que espera en silencio le cuesta al usuario la sesión entera mirando la pantalla.
Por eso el aviso no depende de que nadie se acuerde de nada: son dos hooks que el método
siembra de serie en cada workspace (`.claude/settings.json`).

| Suena cuando… | Hook | Qué significa |
|---|---|---|
| te pide un permiso, o lleva rato esperando una respuesta | `Notification` | te toca a ti |
| ha terminado el turno | `Stop` | puedes mirar lo hecho |

Mientras trabaja **no suena**: sonar cada dos minutos es la forma más rápida de que alguien
lo apague para siempre.

Se cambia en `.claude/personalidad.md`, con una línea: `sonido: no` (calla), `sonido: sistema`
(lo de serie), `sonido: toasty` (tu clip en `.claude/sonidos/toasty.wav`) o la ruta entera de
un fichero. Los clips no vienen en el método —tienen dueño—: los pone cada cual. Si el que
pides no está, suena el del sistema y se dice una vez. Para ver qué sonaría en esta máquina:
`python3 docs/00-metodo/scripts/aviso.py --diagnostico`.

**En Codex CLI esto no existe**: ese harness no tiene hooks, así que allí nada puede sonar
solo. Es una limitación declarada del harness, no un fallo — está en la fila del canario de
`detectores.md`, que comparte la misma frontera. Si el usuario trabaja en Codex y pregunta
por el sonido, se le dice eso, no se le promete un arreglo.

## Cómo se cuenta un problema

Un rojo son tres datos: **qué comprobación, qué falla y quién lo arregla.** Si son varios, tabla.
Lo que el usuario no puede decidir ni tocar, se calla.

## Cómo se cierra un mensaje

Pidiendo lo que necesitas en preguntas de sí o no, y que el informe quepa en una pantalla.

## Compartir la caja negra es del usuario, no tuyo

Los tropiezos registrados pueden compartirse con el autor de la herramienta con
`scripts/caja_negra.py enviar`: es voluntario, enseña antes el paquete ya redactado (sin
secretos, hostname ni nombre de usuario) y no manda nada sin un sí explícito del usuario.
Hoy el comando solo deja el paquete en `.caja-negra/` — la entrega usará un canal privado
cuando exista; nunca sugieras publicarlo en un sitio público: la redacción quita
credenciales, no la información del negocio del usuario.
