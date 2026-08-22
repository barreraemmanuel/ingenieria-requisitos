# Runbook · HOTFIX

**Entrada:** incluso en P0, `peticion.py capturar` es la primera escritura atómica. No añade
una aprobación ni retrasa la contención; conserva qué emergencia declaró el usuario.

**Cuándo:** SOLO producción caída o rota para usuarios reales, y SOLO con el OK explícito del
usuario declarando la emergencia. Lo demás, por urgente que se sienta, es un bug normal
(runbook `bug.md`).
**Plantilla:** `plantillas/bug.md`, como cualquier bug — ficha en `docs/bugs/NNN-slug.md` con
severidad **P0**, alta en `docs/bugs/INDICE.md`, y esta marca visible bajo el título:

> **DEUDA DE SPEC — HOTFIX**: se creó la rama sin contrato completo. Rellenar las secciones
> pendientes en cuanto se estabilice.

**Contrato de cierre:** sangría parada y verificada en caliente + suite completa verde + **la
deuda de spec pagada en 24 h**.

## Qué se salta y qué NO

Se salta **una sola cosa**: la espera de aprobación previa — se despacha ya. NO se salta nunca
el test que reproduce (aunque sea mínimo), la suite completa antes de mergear, ni la evidencia
pegada en la ficha. La urgencia acorta la espera, jamás la verificación. Todo lo demás es
`bug.md`: un hotfix **es un bug** con una válvula de despacho, no otro carril — y por tanto
**tampoco es nunca exprés**.

## El flujo, paso a paso

1. **Emergencia declarada (el usuario).** Sin declaración explícita no hay hotfix: hay un bug P1.
2. **Ficha y despacho, a la vez (el padre).** Tras capturar atómicamente la emergencia:
   `peticion.py abrir-hotfix P-ID <slug> --motivo "producción caída: …"`. El comando crea la
   ficha desde `plantillas/bug.md`, la tria P0 y ejecuta el único uso legítimo de `--force`,
   que salta la espera de aprobación y deja la deuda anotada. Si el despacho falla, la
   petición y la ficha P0 permanecen guardadas; nunca se pierde la emergencia.
3. **Reproducir (el subagente).** El test más rápido que exhiba el fallo, ROJO, con el **output
   pegado literal** en la sección 2 de la ficha (`bug.md`, paso 3). ¿Imposible reproducir en
   caliente? Se documentan los intentos y **se sigue** — pero queda escrito en la ficha como
   **riesgo asumido**: un arreglo sin reproducción puede no ser el arreglo. Esta excepción es
   EXCLUSIVA del hotfix (P0 con emergencia declarada) y **se paga en el paso de la deuda**: no
   existe fuera de aquí y no se cita nunca desde `bug.md`.
4. **Arreglar.** El defecto y nada más (los refactors que se vean, a otra unidad). Test del bug
   en VERDE sin haberlo tocado, **suite completa verde**, evidencia pegada, commit, push y PR
   (título con `NNN-slug` y `hotfix`) y PARA; el `estado: en_revision` lo escribe el padre (regla 2).

   **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
   paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
   `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
   —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que no
   lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles cuando
   quiera.
5. **Merge (el padre en rol CONSTRUCTOR, con el OK del usuario).** Revisor fresco → merge →
   suite sobre main (el ritual indivisible de `runbooks/cierre.md`; aquí la validación del
   usuario llega en el paso 7, sobre producción). **Ahí acaba el constructor: estar en main no
   es estar en producción.** Y estar en main **no es estar cerrado**: el estado sigue
   `en_revision` — igual que en `bug.md`, `mergeada` solo se escribe con el OK del usuario,
   que aquí es el del paso 7.
6. **Traspaso a DEPLOY y despliegue (sesión nueva).** Un rol = una sesión y DEPLOY es el único
   con manos en producción (`roles.md`): el constructor **no despliega**. Se cierra su sesión y
   se abre otra en rol DEPLOY, que arranca leyendo `docs/conocimiento/plano-deploy.md` y
   despliega siguiendo `runbooks/migracion.md` (§Subir de etapa / desplegar). En la ficha queda
   escrito el traspaso: qué commit va a producción, quién dio el OK y a qué hora.
7. **Verificación en caliente (DEPLOY, con el usuario).** Comprobar sobre producción que la
   sangría paró — el síntoma real, no el test — y anotarlo en la sección Cierre, junto al
   estado desplegado. **Sin el OK del usuario sobre producción no hay cierre**:
   el estado NO pasa a `mergeada` y el hotfix sigue abierto. Con el OK → `mergeada`
   (**Validación del usuario: OK**, con fecha) y la deuda de spec queda corriendo. ¿Sigue
   sangrando? → se REABRE la misma ficha: estado vuelve a `en_obra` y se repite desde el paso 3
   con un test nuevo en rojo.

## La deuda se paga

En las **24 horas** siguientes a estabilizar se completa la ficha: reproducción determinista,
causa raíz de verdad (sección 3) y tests de regresión **contraprobados** — rojo sin el arreglo,
verde con él. Solo entonces se borra la marca de deuda.

**Mientras exista una ficha con la marca de deuda sin pagar, no se abre trabajo
nuevo que no sea otro hotfix.** Ni features, ni refactors, ni exprés.

> **Puerta automática.** `scripts/lint_metodo.py` y `scripts/unidad.py` comprueban la deuda
> sin pagar y reservan `--force` para este runbook. El padre vuelve a revisarlo al arrancar
> cada sesión.
