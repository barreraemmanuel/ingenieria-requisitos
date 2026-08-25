---
unidad: NNN-slug
tipo: feature            # feature | refactor | migracion | documentacion | auditoria | investigacion (bug: usa plantillas/bug.md → docs/bugs/)
carril: normal           # normal | completo
estado: planificada
aprobado: no             # LO PONE EL USUARIO, jamás el agente: `no` | fecha YYYY-MM-DD del día
                         # que aprueba el contrato. Sin fecha, `unidad.py despachar` bloquea.
actividad: <id del INDICE de flujos>
ficheros: []             # rutas del repo de código que esta unidad POSEE (lista en línea o
                         # multilínea). Dos unidades paralelas jamás comparten ficheros y el
                         # despacho lo BLOQUEA, así que con trabajo en vuelo es obligatoria.
                         # Los hotspots (migraciones, rutas, modelos compartidos, manifiestos,
                         # lockfiles) son SIEMPRE secuenciales.
peticiones: []            # referencias P-ID@revision que satisface esta unidad
actualizado: YYYY-MM-DD
---

# NNN · <título en una frase>

> Documento ÚNICO de la unidad (ADR-005): contrato + plan de trabajo. El usuario aprueba el
> contrato (de "Qué" a "Verificación") ANTES de que se despache nada.

## Diseño conversado

<Antes de delegar: problema y restricciones explicados por el usuario; sistema existente
inspeccionado; 2-3 opciones comparadas; recomendación concreta y decisión. Esto no crea otro
documento: diseño, contrato y plan viven en esta única ficha.>

- **Decisión:** <enfoque elegido y por qué>
- **Alternativas descartadas:** <opción — coste o riesgo que hizo descartarla>
- **Diseño aprobado por el usuario:** PENDIENTE | OK (YYYY-MM-DD)
- **Plan listo para despacho:** NO | SÍ — <qué comprobó el padre>

## Qué (el contrato, en idioma de negocio)

<2-5 frases: qué podrá hacer el usuario cuando esto esté hecho, con el vocabulario del mapa
de flujos. Sin tecnología.>

## Criterios de aceptación

<Cada criterio será un test ejecutable ANTES de implementar. Verificables, con datos reales
del negocio. Numerados R1, R2…>

- **R1** — Cuando <situación>, <resultado observable>.
- **R2** — …
- **R3** — (caso límite) Cuando <situación rara>, <resultado>.

## Cómo lo pruebas tú (máximo 10 filas, sin tecnicismos)

<Lo escribe el padre ANTES de pedir la aprobación; es lo que el usuario tendrá delante al dar
el OK sobre la app corriendo (paso 5 de `runbooks/cierre.md`). Los R* dicen QUÉ debe pasar;
esto, DÓNDE se mira y QUÉ se toca, con datos reales suyos. Si no cabe en 10 filas, la unidad
es demasiado grande.>

| # | Dónde | Qué haces | Qué deberías ver |
|---|---|---|---|
| 1 | <pantalla o menú> | <acción con un dato real: "busca el albarán 4471"> | <lo que aparece> |
| 2 | <…> | <…> | <…> |

- **NO debe haber cambiado:** <lo de al lado que sigue igual — donde es más fácil romper algo>.
- **Si algo no cuadra:** dilo con lo que viste → se abre un bug con tu ejemplo.

## Deltas al mapa

<Qué cambiará en 02-flujos/ cuando esta unidad se mergee. El cierre los APLICA tal cual.>

- AÑADIDO: —
- MODIFICADO: —
- ELIMINADO: —

## Cómo (enfoque técnico)

<Breve: qué piezas del stack se usan (el bias decide; aquí solo lo específico), qué ficheros
se crean/tocan y en qué orden. ANTES de escribirlo: buscar en main/ DÓNDE VIVE YA esto o algo
parecido, y encajarlo ahí. Si no cabe en el módulo que le corresponde, PARA: eso es un refactor
con su propia unidad, no un rodeo dentro de esta. Las reglas de diseño están escritas una vez
en `01-constitucion/bias.md` y valen siempre: aquí no se re-argumentan ni se rediseña la
aplicación (ADR-015). Si algo se desvía del bias → ADR primero.>

## Fuera de alcance

<Lo que esta unidad NO hace, para que el constructor no lo intente.>

## Verificación

- Comando(s) que deben salir en verde: `<comando de test>`

<Una fila por comportamiento o familia parametrizada distinta. Agrupa en una sola fila los
casos que comparten nivel, datos y motivo; no enumeres el producto cartesiano. La matriz
completa de roles, grupos y restricciones va en tests rápidos; cada entrada protegida, en
integración; navegador solo para los recorridos y fronteras E2E seleccionados en los planos
(ADR-019).>

| Caso | Nivel | Referencias al plano | Datos | Resultado observable | Motivo |
|---|---|---|---|---|---|
| <caso> | <unitario / integración / E2E / sistema> | <R-n, C-n, P-n, E2E-n> | <alias sintético o fixture> | <qué demuestra> | <por qué puede fallar aquí> |

- **Nivel de test:** <resume el reparto de la tabla para la puerta automática de despacho.
  End-to-end solo si cruza la aplicación completa; integración si cruza una frontera; unitario
  si es una regla. Un test que no puede fallar por ESTE cambio no se escribe. `unidad.py
  despachar` BLOQUEA si esta línea sigue sin rellenar.>
- **Criterio portante:** <cuál de los R* es el que sostiene esta unidad: el que, si no
  estuviera implementado, deja el resto sin sentido. UNO, nombrado como `R-n` y en una
  frase. Lo elige quien redacta el contrato, NO quien construye ni quien revisa: el
  cierre exige la contraprueba sobre ESE test (ADR-030), y elegirlo después es elegir
  el más fácil de romper. `unidad.py despachar` BLOQUEA en normal y completo si sigue
  sin rellenar; en directo y exprés no se pide.>
- Evidencia exigida al cerrar: output de tests + <capturas si hay UI>

## Contexto para el constructor (leer ANTES de empezar, en este orden)

<La carga automática NO cruza la frontera del worktree (ADR-001): esta lista es el mecanismo.
Rutas desde el worktree.>

1. Este fichero — tu contrato y tu plan
2. `../../docs/01-constitucion/bias.md` — con qué se construye (no te desvíes sin parar)
3. `../../docs/02-flujos/<actividad>.md` — el negocio que tocas
4. `<AGENTS.md del repo de código>` — comandos de build/test
5. <otros ficheros específicos de esta unidad>

## Plan de trabajo (marcar `[x]` inmediatamente al completar)

<Los pasos 1-3 y 5-8 son fijos. El paso 4 se BORRA si los casos límite ya están cubiertos por
el paso 1: un paso que se cumple marcando la casilla sin escribir nada no es un paso, es un
peaje. El nivel de test del paso 1 es el que dice §Verificación, no "de todo por si acaso".>

- [ ] 1. Test(s) al nivel declarado en §Verificación que demuestren que esto NO existe aún, en ROJO · _Req: R1-R3_ · _Depende de: —_
- [ ] 2. Implementar según el contrato · _Depende de: 1_
- [ ] 3. Iterar hasta que TODOS esos tests pasen, SIN tocarlos · _Depende de: 2_
- [ ] 4. (solo si faltan) Tests de los casos límite de los R* que el paso 1 no cubra · _Depende de: 3_
- [ ] 5. Verificación final: suite completa + lint en verde; evidencia pegada en hallazgos.md · _Depende de: todas_
- [ ] 6. Commit y push de la rama `NNN-slug` · _Depende de: 5_
- [ ] 7. Abrir el **pull request** contra la rama principal, con `NNN-slug` en el título y enlace a esta especificación. **Si esta máquina no tiene `gh`** (lo dice `doctor.py`), sáltate el PR: la rama se queda tal cual y el revisor mirará el diff — camino B de `runbooks/cierre.md` · _Depende de: 6_
- [ ] 8. **PARAR.** La rama queda PENDIENTE DE APROBACIÓN. Devuelve el control al padre con el enlace del PR (o el nombre de la rama, camino B) y la evidencia; **el `estado: en_revision` del frontmatter lo escribe el PADRE al recibirla** (regla 2: el constructor no toca el frontmatter). · _Depende de: 7_

<Pasos extra SOLO si esta unidad los necesita (p. ej. migración: backup antes, rollback escrito).>

## Reglas del constructor (fijas)

- Escribes SOLO en tu worktree. La documentación se lee, jamás se toca. Dos excepciones:
  `../../docs/05-trabajo/NNN-slug/hallazgos.md` y marcar las casillas `[x]` del Plan de
  trabajo de esta especificación.
- **Esas dos excepciones están en el META-repo, otro repositorio, y ahí no haces git jamás**:
  ni `add`, ni `commit`, ni `push`. Escribes el fichero y ya. Tu `git` es el de tu worktree.
- Lo que no está en `ficheros:` no se edita, aunque tu cambio lo necesite (manifiestos y
  config compartida): propones el cambio exacto en `hallazgos.md` y lo aplica el padre.
- Si tu trabajo va a contradecir este contrato o el mapa → **PARA y devuelve la tarea**.
- **No mergeas tú. Tu trabajo termina en el pull request abierto** (o en la rama parada, si
  no hay `gh`). El merge, la suite
  end-to-end sobre main y el lanzamiento de la instancia para que el usuario valide los hace
  el padre, a petición del usuario. Ni `git merge`, ni `gh pr merge`, ni push a la principal.
- Los tests escritos no se debilitan ni se borran.
- Prohibido `git stash`: la pila es única y compartida entre TODOS los worktrees — un pop
  puede llevarse trabajo de otra rama.
- Nada está "hecho" sin el output del check en verde. Evidencia, no afirmación.

## Definición de hecho (no negociable)

1. Todos los R* en verde (tests intactos desde que se escribieron).
2. Suite completa + lint + typecheck en verde. Si el criterio es "no empeorar", la línea base
   se mide contra la rama principal EN ESE MOMENTO, nunca de una foto guardada (main avanza
   mientras trabajas). Y si nunca se ha medido, se mide la primera vez que se exija: una
   casilla que nadie ha podido cumplir jamás no es un criterio.
3. Evidencia pegada en `hallazgos.md` (output real, capturas si hay UI).
4. `hallazgos.md` relleno (aunque sea "sin hallazgos").
5. Pull request abierto (título con `NNN-slug`) —o, sin `gh`, la rama con todo commiteado— y
   PARADA, pendiente de aprobación: sin merge por tu parte.
