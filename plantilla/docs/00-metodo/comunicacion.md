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

## Pedir un OK sobre un contrato

Nunca se pide a ciegas. Antes de pedirle al usuario que apruebe un contrato (una unidad o un
bug), se levanta el visor de contratos EN EL MISMO TURNO —`python3 main/visor_contratos/servir.py
--workspace . --minutos 0`— y se le enseña ahí, no pegando el markdown en el chat.

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
