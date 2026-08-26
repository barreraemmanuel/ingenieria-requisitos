# Runbook · DIRECTO

**Entrada:** petición evaluada por `runbooks/peticiones.md`; después construye el padre y
revisa un agente fresco (ADR-017).

**Cuándo:** cambia comportamiento —luego no es exprés— pero es **pequeño y encaja donde ya
vive**. El carril por defecto de casi todo el trabajo del día a día.
**Plantilla:** `plantillas/directo.md` (se copia como `especificacion.md`: la misma maquinaria,
un contrato de una pantalla en vez de uno de cinco).
**Contrato de cierre:** sus criterios en verde con evidencia + revisión firmada + tu OK sobre
la app corriendo.

## Criterio de entrada (las cuatro, a la vez)

| | |
|---|---|
| **Encaja** | cabe dentro de una actividad que YA está en el mapa |
| **No mueve el mapa** | no añade, no quita y no contradice ningún flujo (si lo mueve → `feature.md`) |
| **Cabe** | 1-3 ficheros del repo de código, y ninguno con una señal ALTA de `docs/00-metodo/senales-de-riesgo.json` (ahí viven los hotspots y el resto de lo delicado; ya no hay lista que recordar: `unidad.py despachar` la mide) |
| **Se deshace** | revertir el commit lo deja como estaba: no migra datos ni toca dinero |

**Qué es "delicado" no se recuerda: está escrito y se mide.** La lista de hotspots que
antes vivía en este runbook —migraciones, rutas, modelos compartidos, lockfiles— es ahora
`docs/00-metodo/senales-de-riesgo.json`, junto al resto de lo que pesa aunque ocupe cinco
líneas: acceso y autenticación, dinero, borrado de datos, secretos y comandos de sistema.
Cada señal lleva su nombre humano y sus patrones. `unidad.py despachar` cierra el carril
directo cuando el `ficheros:` declarado casa con una señal ALTA (y nombra cuál, dónde y cómo
subir de carril), y `ejecucion.py` se las pasa al revisor como foco. Una señal que solo
aparece dentro de `tests/` o de un fixture se lista como informativa y no cierra nada.

**Ante la duda, no es directo: es normal.** La duda ya es la prueba de que el
cambio es más grande de lo que parece.

**Dos directos seguidos sobre lo mismo no eran dos directos**: era una unidad
disfrazada. Se para y se especifica por `feature.md`.

## Qué se ahorra (y qué NO)

| | Directo | Normal |
|---|---|---|
| Puertas que te esperan a ti | **2** (contrato · app corriendo) | 4 |
| Contratos de flujos antes de especificar | no (el delta se escribe al cerrar, si lo hay) | sí, con la web y tu OK |
| Contrato | ficha de una pantalla | `especificacion.md` completa |
| Quién construye | **el padre**, a tu vista (ADR-017) | subagente constructor |
| Quién revisa el diff | agente fresco | agente fresco |
| Tests al cerrar | los del área tocada | + suite completa |
| Evidencia, firma, OK sobre la app, no perder datos | **igual de obligatorio** | igual |

Lo que se recorta es papeleo y esperas. Lo que **no** se recorta nunca: la evidencia en verde,
la revisión firmada por alguien que no construyó, y tu OK sobre la app corriendo.

## El flujo, paso a paso

1. **Clasificar y decirlo (el padre).** Pasa las cuatro condiciones → se anuncia en una frase:
   *"esto lo trato como directo: cabe en la actividad X, no mueve el mapa y son dos ficheros —
   ficha corta, y te lo enseño funcionando"*. Si dudas u objetas, se degrada a normal.
2. **Ficha.** `python3 docs/00-metodo/scripts/unidad.py nueva <tipo> <slug> --directo --desde P-ID`.
   Se rellenan sus cinco huecos: Qué · Criterios · Cómo lo pruebas tú · ficheros · Verificación.
   **El usuario aprueba la ficha** y su OK se escribe como `aprobado: YYYY-MM-DD`.
   Sin esa fecha, `despachar` bloquea igual que en el carril normal.
3. **Obra: la hace el PADRE, a la vista del usuario** (ADR-017). `unidad.py despachar NNN-slug`
   crea la rama y el worktree, y el padre trabaja ahí él mismo — **sin subagente**. Delegar un
   cambio de dos ficheros cuesta la caché, un salto de contexto y toda la visibilidad, y no
   devuelve nada. Va contando por dónde va, una línea por casilla del plan (regla 16). El nivel
   de test lo fija la ficha: **el que demuestra ESTE cambio y ninguno más**; `despachar` bloquea
   si esa línea sigue sin rellenar. Commit, push, PR, y PARAR (estado → `en_revision`).

   **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
   paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
   `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
   —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que no
   lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles cuando
   quiera.
4. **Cierre.** El ritual de `runbooks/cierre.md`, con una sola diferencia: al cerrar solo se
   corren **los tests del área tocada**, no la suite entera. El revisor es un **agente fresco**
   como en cualquier otro carril — y aquí es obligado, porque quien construyó fue el padre. Lo
   demás idéntico: merge → tests → app lanzada → tu OK → `unidad.py cerrar`.

## Escalada

Si a mitad de obra el cambio **crece más allá de los ficheros declarados**,
**toca una señal alta de `senales-de-riesgo.json`** o **hay que mover el mapa**: PARA y
devuelve la tarea. La unidad se re-abre
por `feature.md` con su contrato completo; el trabajo hecho no se tira, se re-encuadra.
