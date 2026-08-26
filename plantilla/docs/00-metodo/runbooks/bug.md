# Runbook · BUG

**Entrada:** capturar por `runbooks/peticiones.md` y contrastar primero la promesa escrita con
el comportamiento real; el defecto no nace de una suposición del agente.

**Cuándo:** el usuario reporta "esto está mal" o un comportamiento prometido no se cumple.
**Dónde vive:** `docs/bugs/NNN-slug.md` — UN fichero por bug con TODO su ciclo de vida
(plantilla `bug.md`). No se archiva: `docs/bugs/` es el historial. (ADR-006)
**Contrato de cierre:** test del bug ROJO→VERDE **con los dos outputs pegados en la ficha** +
tests de regresión contraprobados + suite completa verde + validación del usuario sobre una
instancia corriendo.

## Regla de carril

Un bug cambia comportamiento (restaura el prometido) → **nunca es exprés, sin
excepciones**: una errata que ve el usuario es comportamiento (`expres.md`, columna NO). No hay
bug "micro": todo bug lleva ficha, `NNN`, test rojo y OK del usuario. Un bug que revele un
problema de diseño transversal → escalar a decisión con el usuario.

**Carril directo o normal.** Un bug cuyo arreglo encaja donde ya vive (1-3 ficheros sin
hotspots, sin mover el mapa, se deshace revirtiendo) se crea con
`unidad.py nueva bug <slug> --directo --desde P-ID`: **misma ficha y mismo par ROJO→VERDE** —eso no lo
recorta nada—, pero el nivel de test es el que demuestra ESTE bug y construye el padre
(`runbooks/directo.md`). En todos los carriles el diff lo revisa un agente fresco (ADR-017).

## El flujo, paso a paso

1. **Reporte.** El usuario se lo cuenta al agente en la terminal (rol CONSTRUCTOR, según el
   router). El padre asigna NNN y crea la ficha **con el script, no a mano**:
   `python3 docs/00-metodo/scripts/unidad.py nueva bug <slug> --desde P-ID` (asigna el siguiente NNN desde
   main y copia `plantillas/bug.md` a `docs/bugs/NNN-slug.md`). Rellena la sección Reporte con
   lo que el usuario cuenta —preguntándole lo que falte—, incluidos **severidad preliminar**
   (P0-P4) y **estado de triaje**, y registra el bug en `docs/bugs/INDICE.md`. Si no hay promesa
   original incumplida, no es un bug: es una feature sin especificar (cambiar de runbook).
2. **Despacho.** `python3 docs/00-metodo/scripts/unidad.py despachar NNN-slug`: crea la rama
   `NNN-slug` desde la rama principal (remota si existe; local si el proyecto todavía no tiene
   GitHub) con su checkout en `worktrees/NNN-slug`, deja la ficha
   en `en_obra`, y **aplica las precondiciones** (ficha con prosa real, tope de trabajo en
   vuelo, rama no reutilizada). **El camino manual las salta todas: no se usa.** `--force` es la
   válvula EXCLUSIVA de `hotfix.md`. Si el bug es del PROPIO meta-repo (un runbook, un script
   del método, una ficha) y su `ficheros:` no toca `main/`, se despacha con `--documental`:
   sin rama ni worktree de código, y el cierre no exige un merge que nunca existirá. Con el worktree creado, el padre abre el
   **subagente del bug** como subagente propio, con el encargo que imprime el despacho
   (worktree, modelo y esfuerzo; ADR-033); el agente escribe SOLO en su worktree y en SU fichero
   `docs/bugs/NNN-slug.md`. Después,
   `ESTADO.md` (lo escribe el padre).
3. **Reproducir (primera misión del subagente).** Crear un test end-to-end que reproduzca el
   bug: debe estar **ROJO**. Sin test rojo no se toca código: un fix sin
   reproducción no es verificable. **El output literal del test en ROJO se pega
   en la sección 2 de la ficha** (pegado, no resumido ni parafraseado): el hard-gate no lo
   satisface la afirmación "está rojo", lo satisface el output. Sin ese texto en la ficha, para
   el cierre el test rojo no existió (evidencia, no afirmación — regla 12 de `AGENTS.md`).
   ¿No consigue reproducirlo? → PARA y devuelve al padre, que re-pregunta al usuario. (La
   excepción de "imposible reproducir en caliente" es EXCLUSIVA de `hotfix.md` y no se importa
   aquí.)
4. **Diagnosticar.** La causa raíz, al fichero del bug (siempre), mediante el bucle
   Observación → Hipótesis falsable → Experimento discriminante → Conclusión. El resultado de
   cada experimento se conserva aunque refute la hipótesis. Mientras la causa
   raíz siga abierta **no se implementa** una solución: cambiar código sería probar remedios,
   no depurar.
5. **¿La solución es directa?** (no toca contrato ni mapa, no elimina nada, una sola vía
   razonable) → implementar. **¿Tiene miga o hay varias vías?** → escribir la Propuesta de
   solución en el fichero y **PARAR**; el padre pone la ficha en `bloqueada` (vocabulario
   cerrado de `00-metodo/README.md`): un bug esperando decisión no es un bug en obra.
6. **Aprobación.** El padre revisa la propuesta y la plantea al usuario en cristiano
   (pros/contras, preguntas). La decisión queda ANOTADA en el fichero. Aprobada → estado vuelve
   a `en_obra` y sigue la obra. Rechazada → otra vía (sigue `bloqueada`) o, si el usuario decide
   no arreglarlo, `descartada` — el porqué, siempre escrito en la ficha.
7. **Resolver.** Implementar hasta que: el test del bug pasa a **VERDE** (sin tocarlo), hay
   **tests de regresión** que fijan el comportamiento para que no vuelva — comprobados en
   ROJO sin el arreglo y en VERDE con él (un test que pasa en los dos casos no vale; el árbol
   se pone "sin el arreglo" con `git revert --no-commit <commit del fix>` —o
   `git checkout HEAD~1 -- <fichero>`— y se deshace acto seguido, **nunca con `git stash`**:
   está prohibido, ver la plantilla `bug.md`) —, y la
   suite completa sigue verde. **Todos los outputs, pegados literales en la ficha** (sección 5),
   junto al del ROJO del paso 3: el par ROJO→VERDE del mismo test es la única prueba de que se
   arregló ESTE bug y no otra cosa.
8. **Pull request.** El subagente hace commit, push y PR a la rama principal (título con
   `NNN-slug`, enlazando el fichero del bug) y PARA; el `estado: en_revision` lo escribe el padre al recibir el PR (regla 2).

   **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
   paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
   `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
   —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que no
   lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles cuando
   quiera.
9. **Cierre (el padre, a petición del usuario).** Es el ritual indivisible de
   `runbooks/cierre.md`, cerrado con `unidad.py cerrar`. Resumen de
   `00-metodo/README.md`; aquí solo lo específico del bug.
   **Puerta de evidencia, antes de todo lo demás:** si la ficha no lleva pegados
   el output del test en ROJO (sección 2) **y** el del mismo test en VERDE (sección 5), el
   cierre NO empieza — la ficha vuelve al subagente. Sin ese par no hay nada que revisar: el
   arreglo no está demostrado.
   Después, **la revisión** —siempre un subagente fresco de solo
   lectura, sea cual sea el carril (ADR-017)—: *"Revisa el diff contra
   la ficha `docs/bugs/NNN-slug.md`: que el output ROJO y el VERDE están pegados y son del
   mismo test, que ese test reproduce el síntoma reportado, que los tests de regresión están
   contraprobados (rojo sin el arreglo, verde con él), y que no se tocó nada fuera del alcance
   del bug. Reporta solo huecos de corrección, no preferencias de estilo."* — veredicto a la
   sección 6 · Cierre de la ficha; huecos → vuelven al subagente.
   Limpio → merge del PR → **tests sobre main al nivel del carril** (ADR-016; tabla en
   `runbooks/cierre.md`) → **lanzar una instancia
   de la app** (comando de arranque: el `AGENTS.md` del repo de código) y el usuario la prueba.
   **Sin ese OK no hay cierre**: el estado NO pasa a `mergeada` y el bug sigue
   ABIERTO (`en_revision`). Con el OK → estado `mergeada`, sección Cierre rellenada
   (**Validación del usuario: OK**, con fecha), borrar worktree y rama, actualizar `ESTADO.md`
   + linter. La ficha **no se archiva**: se queda en `docs/bugs/`. ¿"Sigue mal"? → se REABRE en
   el mismo fichero (vuelta al paso 3 con un test nuevo en rojo).

Los dos candados principales de este flujo también los comprueba
`scripts/lint_metodo.py`: una ficha no puede darse por cerrada sin la evidencia ROJO→VERDE
ni sin la validación final del usuario.

## Al cerrar, pregunta obligada del padre

¿La causa raíz merece regla permanente?
- Error del agente que se repetirá → regla en AGENTS.md del repo de código o hook.
- Trampa de librería/dominio → `conocimiento/`.
- El mapa prometía algo mal → delta correctivo a `02-flujos/` (con OK del usuario).
- **Faltaba un guardián** (ningún mecanismo podía verlo) → fila nueva en `docs/00-metodo/detectores.md`,
  columna «qué NO puede ver»; esa fila es la cola de la que sale el guardián siguiente (ADR-026).
