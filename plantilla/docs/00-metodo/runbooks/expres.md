# Runbook · EXPRÉS

**Cuándo:** el diff cabe en una frase **Y** no cambia comportamiento observable.
**Entrada:** petición evaluada por `runbooks/peticiones.md`, perfil `ninguna`.
**Plantilla:** ninguna. No hay `NNN` ni ficha de unidad; el rastro es P-ID + commit/PR.
**Contrato de cierre:** tests del área VERDES con el output pegado en el PR + merge + worktree
y rama borrados. Nada que archivar, nada que tocar en el mapa.

## Criterio de entrada (las dos condiciones, a la vez)

Cabe en una frase (si necesitas dos, no es exprés) **y** nadie que use la app nota nada.

| SÍ | NO |
|---|---|
| errata en un comentario o docstring | cualquier texto que ve el usuario |
| formateo, orden de imports | tocar lógica, aunque sea "una línea" |
| bump de una dependencia **de desarrollo** | cualquier dependencia de producción |
| añadir un fichero al `.gitignore` | añadir/borrar ficheros que la app carga |
| — | **un bug: NUNCA, ni el más pequeño** (runbook `bug.md`) |

**Un bug JAMÁS es exprés, sin excepciones.** Un bug restaura comportamiento
prometido, luego cambia comportamiento, y lo que cambia comportamiento nunca es exprés
(`00-metodo/README.md`, §Los 4 carriles). No importa que el diff quepa en una frase ni que sea
"solo texto": una errata que ve el usuario es comportamiento observable. Este carril **no
tiene ficha, ni `NNN`, ni test rojo, ni OK del usuario** — es decir, no tiene ninguna de las
tres cosas que hacen verificable el arreglo de un bug. Si lo que llega es "esto está mal" →
`bug.md`, con su ficha en `docs/bugs/`.

**Ante la duda, NO es exprés.** La duda ya es la prueba de que algo cambia. Un
exprés mal clasificado es código sin contrato entrando en main. El escalón de al lado no es el
ritual completo: es el **carril directo** (`runbooks/directo.md`), ficha de una pantalla y dos
puertas, que es donde cae casi todo lo que se cuela mal por aquí.

## El flujo, paso a paso

1. **Clasificar (el padre) y AVISAR al usuario.** ¿No pasa el criterio, o hay duda? → runbook
   del tipo que toque. Si pasa, antes de despachar el padre se lo dice al usuario en una frase,
   con el porqué: *"esto lo trato como exprés: cabe en una frase y no cambia comportamiento —
   sin ficha, sin `NNN` y sin aprobación tuya"*. Este es el único carril que llega a main sin
   ninguna puerta del usuario, así que ese aviso es su única ocasión de corregir antes del
   commit. Si duda u objeta, se degrada a carril normal (hard-gate de arriba).
2. **Despacho.** `peticion.py abrir-expres P-ID <slug-corto>` crea la rama canónica
   `expres-P-ID-<slug-corto>`; el padre añade su worktree efímero. `ESTADO.md` no se toca:
   no hay unidad que censar.
3. **Obra: construye el padre** (ADR-017), a la vista del usuario. Hace EXACTAMENTE el cambio
   de la frase y nada más. Corre los tests del **área tocada** (ADR-016): verde obligatorio.
   Si no puede delimitar el área, corre la suite.
4. **Pull request.** Commit, push y PR con `expres` en el título. En el cuerpo: la frase del
   cambio y el **output de esos tests pegado** — no hay `hallazgos.md`, así que esa es la única
   evidencia que existirá. Sin output pegado no hay merge.

   **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
   paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
   `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
   —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que no
   lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles cuando
   quiera.
5. **Cierre (el padre).** Verificar el verde (sin revisor: en exprés la única puerta es el
   verde, `runbooks/cierre.md`) → merge → reconciliar el P-ID
   con evidencia → borrar worktree y rama. Se acabó: **NO
   se archiva nada** (no hay unidad) y **NO se toca `02-flujos/`** (si hubiera que tocar el
   mapa, no era exprés). Mientras el worktree exista el linter lo canta como huérfano: es el
   cronómetro del carril — un exprés que sobreviva a un lint del padre no era exprés.

## Escalada

Si el constructor descubre a mitad que **sí cambia comportamiento**, que **el
diff crece** más allá de la frase, o que **detrás había un defecto** (lo que parecía cosmético
tapaba un bug): PARA, no commitea, devuelve la tarea (regla 8). El trabajo se re-abre por
carril normal con su `NNN`, su contrato y su aprobación —y si era un defecto, por `bug.md`, con
ficha y test rojo—; la rama exprés se borra sin merge.

> **Aviso.** El exprés no es un atajo para saltarse la spec. Si se usa **dos veces seguidas
> sobre lo mismo**, eso no eran dos exprés: era una unidad disfrazada. Se para y se especifica.
