# Runbook · FEATURE

**Entrada:** petición evaluada por `runbooks/peticiones.md`; la investigación acotada, si la
hay, se sintetiza antes de escribir esta spec.

**Cuándo:** el usuario entra en la carpeta, lanza su harness (rol CONSTRUCTOR por defecto,
según el router) y pide comportamiento nuevo: "quiero una feature: la aplicación debe hacer
esto, esto y esto".
**Plantilla:** `especificacion.md` (documento único: contrato + plan de trabajo — ADR-005).
**Contrato de cierre:** los criterios de aceptación de la spec en verde con evidencia + el
flujo del mapa en `entregada` + validación del usuario sobre la app corriendo.

## Regla de carril

Una feature cambia comportamiento → **nunca es exprés**. ¿Encaja en una actividad que ya está
en el mapa, sin moverlo, en 1-3 ficheros sin hotspots, y se deshace revirtiendo? → **carril
directo**, y este runbook no aplica: `runbooks/directo.md`. ¿Transversal, arriesgada o
territorio desconocido? → carril completo (`investigacion.md` de la unidad). El resto —lo que
mueve el mapa, toca hotspots o no cabe en una ficha— es carril normal, que es lo que sigue.

## El flujo, paso a paso

(Pasos 1-4 = fase 5, especificar · paso 5 = fase 6, construir · paso 6 = fase 7, cerrar.)

1. **Encaje con los flujos de usuario (`02-flujos/`).** Tres casos: (a) **encaja tal cual con
   los flujos actuales → seguir al paso 2 sin abrir la web ni pedir aprobación de flujos**: no
   hay delta que acordar, y montar el aparato de flujos para un cambio que el mapa ya promete
   es la ceremonia más cara del método pagada por nada (ADR-014); (b) modifica un flujo
   existente → se habla con el usuario,
   se le plantea cómo quedaría el flujo nuevo (en la web de flujos) y se acuerda; (c) es un
   flujo nuevo → se añade y aparece en la web de flujos. Lo que se edita es SIEMPRE la fuente
   —`docs/02-flujos/planos/planos.json`, siguiendo el runbook de requisitos—, nunca los
   `.md` compilados a mano. Para enseñárselo: primero
   `python3 docs/00-metodo/requisitos/validar_web.py --datos docs/02-flujos/planos/planos.json`
   (si falla, no se da la URL ni se pide aprobación) y después
   `python3 docs/00-metodo/requisitos/requisitos.py abrir`
   → el apartado **Flujos** de la web del método, que se refresca solo cada 3 s: se edita el JSON y el usuario lo
   ve al momento en pantalla. El flujo acordado queda ESCRITO en el mapa con estado
   `especificada` (vocabulario del aparato, `00-metodo/README.md`); el cierre lo pasará a
   `entregada`.
   **Solo en los casos (b) y (c) —los que mueven el mapa—: el flujo acordado queda
   ESCRITO en el mapa y APROBADO por el usuario sobre la web ANTES de especificar nada.** Sin eso
   no se pasa al paso 2: no se abre unidad, no se asigna `NNN`, no se escribe spec. En el caso
   (a) esta puerta no existe: no hay nada que aprobar que no esté ya aprobado.
   (El aparato de flujos — runbook + web — viene heredado de la herramienta de ingeniería de
   requisitos; aquí no se reinventa, se usa.)
2. **¿Hace falta investigar?** Contra el stack actual (`01-constitucion/bias.md` +
   `03-investigacion/SINTESIS.md` — **ese fichero lo crea la fase 3**, `runbooks/investigacion.md`;
   aún no existe: si la feature depende de él, correr la fase 3 es el paso previo; si no, manda
   el bias a secas): ¿esto ya sabemos hacerlo? Cubierto → adelante sin
   investigación. Territorio nuevo → pequeña investigación primero (carril completo:
   plantilla `investigacion.md` de la unidad; si es un tema de proyecto, se añade a la
   fase 3 por su ritual).
3. **Diseño conversado y planificación de la feature.** En cristiano, mínimo lenguaje
   técnico ("aprovechando lo que ya usamos, crearía una tabla en la base de datos que guarde
   X…"). OBLIGATORIO en este paso, y es lo único de diseño que se decide aquí: buscar en el
   código (`main/`) **dónde vive ya esto o algo parecido**, y encajarlo ahí. No se duplica un
   sistema que ya existe.
   Las reglas de diseño (responsabilidad única, KISS, una funcionalidad en su módulo) están
   escritas UNA vez en `01-constitucion/bias.md` y valen siempre: no se re-argumentan en cada
   unidad, y esta spec no es el sitio para rediseñar la aplicación (ADR-015).
   **Si la feature no cabe en el módulo que le corresponde, PARA**: eso es un
   refactor con su propia unidad y su propia aprobación, no un rodeo dentro de esta feature.
   Se comparan 2-3 enfoques cuando haya una decisión material, se recomienda uno y se anotan
   la elección y las alternativas descartadas en `especificacion.md`: diseño, contrato y plan
   son **un único contrato canónico**, no tres documentos ni una spec paralela del harness.
   **El usuario aprueba la planificación.**
4. **Spec file.** El padre crea la unidad **con el script, no a mano**:
   `python3 docs/00-metodo/scripts/unidad.py nueva feature <slug> --desde P-ID` (asigna el siguiente `NNN`
   desde main y copia `plantillas/especificacion.md` a `docs/05-trabajo/NNN-slug/`).
   Rellena el contrato:
   **Qué** y **Criterios (R\*)** en idioma de negocio, con el vocabulario del mapa (cada
   criterio convertible en test, al menos un caso límite, datos reales del negocio);
   **Deltas al mapa** (el flujo acordado en el paso 1) — si la feature elimina o contradice
   algo del mapa, el usuario lo aprueba AHORA, no en el cierre; **Cómo** (bias + SINTESIS si
   ya existe; desviación del bias → ADR primero, spec después); **ficheros** (ownership contra las
   unidades en vuelo de `ESTADO.md`: si comparte ficheros con otra → secuenciales; hotspots
   — migraciones de BD, rutas, modelos compartidos, lockfiles — secuenciales SIEMPRE).
   Después, el **Contexto para el constructor** (rutas exactas — la carga automática NO
   funciona, ADR-001) y el **Plan de trabajo** (esqueleto fijo; pasos extra solo si esta
   unidad los necesita). Test de autocontención: ¿un constructor sin NADA de contexto previo
   puede trabajar leyendo solo esta spec + su contexto? Si no → reescribir.
   La tabla de **Verificación** reparte cada caso por referencia al plano y por nivel. Si toca
   autorización: matriz de roles, grupos, acciones y restricciones exhaustiva en tests rápidos;
   integración contra cada entrada protegida del servidor; y solo los E2E seleccionados en los
   planos (un feliz por rol interactivo y denegaciones de fronteras críticas distintas). No se
   duplica toda la matriz en el navegador (ADR-019).
   Si los planos declaran `pruebas_e2e` y esta es la primera unidad de código/CI, su alcance
   incluye el mínimo de autenticación y harness: se crea en greenfield o se adopta la existente
   en brownfield. No se despacha una primera unidad que el `--require-e2e` del cierre haría
   imposible fusionar.
   **El usuario anota el contrato** (lee, corrige, aprueba — su ritual de
   mayor apalancamiento). Su OK lo escribe ÉL como `aprobado: YYYY-MM-DD` en el frontmatter
   (`00-metodo/README.md`): sin esa fecha no hay despacho, y el script lo bloquea.
5. **Despacho y obra.** Solo después del Diseño conversado y de la aprobación del contrato, el
   padre despacha **con el script, no a mano**:
   `python3 docs/00-metodo/scripts/unidad.py despachar NNN-slug`, que crea la rama `NNN-slug`
   desde la rama principal (remota si existe; local si aún no se conectó GitHub), con su
   checkout en `worktrees/NNN-slug`, y **aplica las
   precondiciones** (contrato aprobado por el usuario, contrato con prosa real, tope de trabajo
   en vuelo, rama no reutilizada); el camino manual las salta todas. La rama es local hasta el
   push del PR. Después el padre actualiza `ESTADO.md` y abre un **subagente propio** con el
   encargo que imprime el despacho: la especificación como punto de entrada, el worktree como
   cwd y frontera de escritura, y el modelo/esfuerzo de la tabla (estado → `en_obra`, ADR-033). El constructor trabaja
   ÚNICAMENTE en esa rama/worktree, ejecutando el Plan de trabajo en orden y marcando `[x]`:
   PRIMERO crea los tests que demuestran que esto NO existe aún, y deben FALLAR (rojo);
   después implementa hasta que TODO esté verde, SIN tocar los tests; suite completa y
   evidencia pegada (Definición de hecho de la spec cumplida). **El nivel de test lo fija la
   spec, no la costumbre** (ADR-015): end-to-end solo si el cambio cruza la aplicación de punta
   a punta; de integración si cruza una frontera (base de datos, servicio, API); unitario si es
   una regla de negocio. Si toca autorización, toda denegación se comprueba también llamando
   directamente al servidor: esconder un botón no prueba un permiso. Solo cuando los planos
   declaran `pruebas_e2e` se usan los aliases documentados y la cadena
   `full-suite → e2e → provision-e2e → tests E2E`; una app con usuarios o unos planos
   antiguos no la activan por sí solos. Nunca se usan datos o credenciales de producción. Un
   test que no puede fallar por culpa de ESTE cambio no se escribe. Si el sandbox bloquea el
   commit porque Git necesita el `.git` común, el padre valida el recibo `ejecucion/v1` y hace
   commit/push desde ese worktree; nunca se ensancha el sandbox. Se abre el **pull request**
   (título con `NNN-slug`), y la rama queda
   PENDIENTE DE APROBACIÓN; el `estado: en_revision` lo escribe el padre al recibir el PR (regla 2). Sorpresas → `hallazgos.md`.
   Contradicción con la spec o el mapa → **PARAR y devolver la tarea**.

   **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
   paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
   `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
   —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que no
   lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles cuando
   quiera.
6. **Cierre (el padre, a petición del usuario).** Es el ritual indivisible de
   `runbooks/cierre.md` (con `gh` y sin `gh`), cerrado con `unidad.py cerrar`; resumen de
   los 7 pasos en `00-metodo/README.md` — aquí solo lo específico de una feature:
   - **El prompt del revisor fresco** (sesión/subagente nuevo, solo lectura): *"Revisa el
     diff contra especificacion.md: cada R\* implementado, los casos límite con test, y nada
     fuera de los ficheros declarados. Comprueba además que los ficheros de test NO se
     modificaron después del commit que los creó —ni se debilitaron, ni se borraron, ni se
     marcaron como saltados para que pasara el código— y que la feature no DUPLICA
     funcionalidad que ya existía en otro módulo de `main/`. Reporta solo huecos de
     corrección, no preferencias de estilo."*
   - **La validación del usuario es en modo novato**, probando los ejemplos reales de los
     R\*. Sin ese OK no hay cierre; "no es lo que pedí" → nueva unidad tipo
     `bug`.
   - **Al consolidar:** aplicar los Deltas a `02-flujos/` y pasar el flujo del mapa a
     **`entregada`** · cosechar `hallazgos.md` (conocimiento/, ADRs, nuevas unidades al
     ROADMAP — lo crea la fase 4, `runbooks/planificacion.md`; mientras no exista, se quedan
     anotadas en `hallazgos.md`).
