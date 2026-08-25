# ADR-030 · El test portante tiene que morder, y se demuestra

**Fecha:** 2026-08-25 · **Estado:** aceptada · Unidad 046 · Petición P-20260823-9ac867f1@1

## Contexto

El paso 7 de `runbooks/bug.md` ya exige la contraprueba, y la exige bien: romper a propósito la
implementación, pegar el rojo, restaurar, y prohibido usar `git stash`. Un test que pasa en los
dos casos no vale.

Pero eso vive **solo en el carril bug**. Para una feature, un refactor o una migración, el paso
2 del cierre le pide al revisor «cada criterio implementado, casos límite con test», y **nada
demuestra que esos tests fallarían si el comportamiento no existiera**. Un test vacuo pasa
nuestra revisión firmada, la suite completa y el OK del usuario sin que nadie lo note.

Tenemos la técnica escrita y la aplicamos a un solo tipo de unidad.

El encuadre que hay que copiar viene del informe de verificación de gentle-ai (sección
CRITICAL-3): en vez de fiarse de la evidencia registrada, sustituyeron el rechazo real por una
resolución fabricada, el test falló con exactamente el mensaje registrado, restauraron con
`git checkout` y volvieron a verificar **byte a byte** antes de repetir el test en verde. No es
«corrí el test»: es «provoqué exactamente la mentira que el criterio prohíbe y el test la cazó».

## Decisión

En los carriles **normal y completo**, quien construye demuestra que **un** test del criterio
portante es no vacuo, y el revisor lo comprueba leyendo el parte (no puede romper código: su
perfil lo tiene en solo lectura, ADR-017 y ADR-022):

1. Rompe a propósito la implementación de ese criterio.
2. Pega el rojo: el test tiene que fallar, y fallar **por eso**.
3. Restaura.
4. **Demuestra** que el árbol quedó igual —`git diff HEAD` vacío y la punta de la rama
   idéntica—, no lo afirma.

La especificación gana un campo, `**Criterio portante:**` en §Verificación, que declara
**cuál es el criterio portante**, para que no lo elija a ojo el que construyó ni el que revisa:
lo fija quien redacta el contrato, antes de que exista una línea de código. `unidad.py
despachar` BLOQUEA si sigue sin rellenar, igual que con el nivel de test.

Prohibido `git stash`: la pila es única y compartida entre todos los worktrees.

## Alcance, y por qué está acotado

- **Un solo criterio**, no todos. La contraprueba de cada criterio de cada unidad convertiría
  el cierre en un segundo desarrollo.
- **Solo normal y completo.** En directo no: el carril entero existe para no pagar ceremonia y
  allí el diff cabe en una pantalla.
- **No entra en el carril bug**, donde ya existe y funciona.

## Consecuencias

- Añade un paso al cierre de normal y completo. Es una puerta nueva, y por eso hace falta este
  ADR: la regla 13 no deja meter puertas por la puerta de atrás.
- Un test vacuo deja de poder atravesar el cierre en silencio.
- El coste es real y se declara: unas líneas de runbook, un campo en la plantilla, y unos
  minutos de revisor por unidad. Se acepta porque el fallo que evita —dar por entregado un
  criterio que ningún test protege— no lo caza ningún otro guardián de la lista de
  `detectores.md`.

## Alternativas descartadas

- **Mutación automática de código.** Es la solución completa y la correcta a largo plazo, pero
  exige herramienta, tiempo de corrida y ajuste por proyecto. Esto es el 5 % del coste con la
  mayor parte del valor.
- **Pedirlo en la prosa del cierre sin puerta.** Es exactamente lo que ya pasa con las 58
  reglas huérfanas del inventario del 22-08: escrito y sin ejecutor.
- **Aplicarlo a todos los criterios.** Convierte el cierre en un segundo desarrollo y garantiza
  que se salte.
