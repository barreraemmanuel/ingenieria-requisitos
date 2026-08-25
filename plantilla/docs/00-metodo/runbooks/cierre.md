# Runbook · CIERRE (el padre, a petición del usuario)

**Cuándo:** una unidad de CUALQUIER tipo está terminada y el usuario pide cerrarla.
**Vale para todos los runbooks:** `feature`, `bug`, `refactor`, `migracion`, `documentacion`,
`auditoria`, `investigacion`, `hotfix` y `expres` cierran POR AQUÍ. Su runbook describe lo
específico de su tipo; el cierre es este y es el mismo para todos.
**Contrato de cierre:** las puertas dependen de la ruta (ADR-024). Directo/normal exigen fusión,
revisión fresca y OK sobre la app; exprés no exige ese OK; documental no inventa fusión ni app.
Un prototipo se cancela y conserva como descartado: nunca entra en este cierre ni se reconcilia
como entrega. La tabla de `runbooks/control-plane.md` es la autoridad.
**Origen:** el cierre revalida `P-ID@revision` y reconcilia los procesos terminales; una
petición con más procesos sigue abierta.

## Los dos caminos (los deciden el doctor y `repos.yaml`, no el paso 7)

El camino lo deciden DOS cosas, no una: que esta máquina tenga `gh`
(`python3 docs/00-metodo/scripts/doctor.py`) **y que el repo de código tenga remoto en
GitHub** (`git -C main remote -v`). Con `gh` pero sin remoto, el camino A no existe: es el
B. **Se mira al arrancar el proyecto, no al llegar aquí**: descubrir en el paso del pull
request que no hay GitHub es descubrirlo con el código ya terminado. Y hay una tercera
cosa que manda por encima de las otras dos: la clave `push:` de `repos.yaml` (ver abajo).

| | **Camino A — con `gh`** (lo normal) | **Camino B — sin `gh`** (o sin GitHub) |
|---|---|---|
| Dónde termina el constructor | pull request abierto, rama empujada | rama local (o empujada, si hay remoto) |
| Qué mira el revisor | el diff del PR | `git -C main diff main..NNN-slug` |
| Dónde queda el veredicto | sección **Revisión** de `hallazgos.md` | igual: sección **Revisión** de `hallazgos.md` |
| Quién fusiona y cómo | el padre: `gh pr merge NNN-slug` | el padre: `git -C main merge --ff-only NNN-slug` **y después `git -C main push origin main`** |
| Cuándo NO aplica | con `push: usuario` en `repos.yaml`: nunca | con `push: usuario`: SIEMPRE este, **sin su push final** |

**Camino B: el push de la rama principal NO es opcional.** Al despachar, la rama de cada
unidad nace de `origin/<principal>`. Si el merge se queda en local, la siguiente unidad parte
de una base vieja y su merge ya no será un fast-forward: a partir de ahí cada cierre pelea con
git. Si el proyecto no tiene remoto, no hay nada que empujar y esto no aplica; y tiene una
excepción nombrada, la de aquí abajo.

**La excepción nombrada de `push: usuario`.** Si `repos.yaml` declara `push: usuario`, el
camino es **SIEMPRE el B** aunque esta máquina tenga `gh` y el repo tenga remoto en GitHub: lo
decide la clave, no el doctor. No hay PR que fusionar porque el constructor nunca lo abrió, el
merge local `--ff-only` del paso 3 se hace igual (es trabajo local, no escribe en el remoto
ajeno) y el `git -C main push origin main` **queda prohibido para el método**: se le imprime al
usuario como recibo del cierre —`unidad.py cerrar` lo dice con el conteo de commits— y lo
ejecuta él cuando quiera, con sus propios controles. El método se detiene exactamente ahí.

**El hook `pre-push` deja pasar exactamente ese recibo (020).** El cierre borra la rama NNN
local y reconcilia su proceso (pasa a `terminal`) ANTES de imprimir el recibo/aviso — así que,
cuando el usuario ejecuta el comando, el hook ya no ve una rama `pendiente`: ve un proceso
`terminal` y una ficha con `fusion: <sha>` anotada por el propio cierre. El hook acepta ESE
caso con una condición estricta: el `sha` que se empuja tiene que coincidir EXACTO con el
`fusion:` anotado, no basta con que sea un antepasado suyo. Sin esa igualdad exacta, cualquier
push futuro de la principal quedaría autorizado en cuanto una sola unidad se hubiera cerrado
alguna vez con esa prueba — justo el commit directo no trazado que el hook existe para
bloquear. Ventana que queda abierta, con honestidad: si entre el cierre y el push alguien
añade, reescribe o reordena un commit sobre `main` (otro cierre, un rebase, un amend), ese sha
ya no es el anotado y el hook vuelve a bloquear — hay que repetir el comando exacto que el
recibo imprimió, sin tocarlo, o cerrar de nuevo para que anote la fusión vigente.

**La excepción nombrada de `main/`.** La regla es que `main/` es de solo lectura
(`AGENTS.md`). El camino B la rompe una vez, a propósito y con nombre: **el merge del paso 3
de este ritual, y nada más**. Ni editar ficheros, ni crear ramas, ni commitear a mano allí.
Sin esta excepción escrita, el método obligaba a improvisar justo en el paso más delicado.

## El ritual (indivisible: no existe "fusionado pero sin cerrar")

**Se escribe según se hace.** Cada paso se marca en la §Bitácora del cierre de `hallazgos.md`
NADA MÁS terminarlo, con fecha y con quién lo hizo. Indivisible no significa que la sesión no
se pueda morir a mitad: significa que si se muere, la siguiente lo retoma leyendo esas
casillas — lo marcado no se repite, lo no marcado no se da por hecho— en vez de deducir de
`git log` qué pasó. Lo que solo está en el contexto de la sesión, está perdido.

1. **Verificar con evidencia.** El output real de los checks pegado en `hallazgos.md`
   (o en la ficha, si es un bug). "Hecho" sin output no es hecho.
   En toda unidad de código, antes de revisar o fusionar:
   `python3 docs/00-metodo/scripts/lint_ci.py --repo worktrees/NNN-slug`. La primera unidad
   materializa el contrato; las siguientes demuestran que no lo han roto. Una unidad
   documental, que no tiene worktree de código, no ejecuta esta puerta.

   **El parte de cierre tiene que cuadrar** (`lint_cierre.py`, lo llama `unidad.py cerrar`
   antes que ninguna otra puerta). Comprueba cuatro cosas sobre el bloque
   ```parte-de-cierre``` de `hallazgos.md`: que un veredicto de éxito no conviva con un
   código de salida ≠ 0, ni uno de fallo con toda la evidencia en verde; que los `N/M` de
   requisitos y casillas coincidan con el conteo real sobre `especificacion.md`; y que las
   rutas de `.runtime/` citadas existan con el hash declarado.
   Lo que **NO** comprueba: si los tests son buenos, si muerden o si el comando declarado
   es el que tocaba. Dice que lo escrito cuadra con lo ejecutado, no que lo ejecutado
   bastara. Suelto: `python3 docs/00-metodo/scripts/lint_cierre.py NNN-slug`.
   Si los planos declaran `pruebas_e2e`, añade `--require-e2e`: deben existir
   `scripts/ci/{provision-e2e,e2e}` y la cadena debe ser `full-suite → e2e →
   provision-e2e → tests E2E`; el provisionador demuestra que rechaza producción. En la
   primera unidad de código/CI esto implica autenticación mínima en greenfield o adopción de
   la existente en brownfield: no se aplaza una puerta necesaria para este mismo merge
   (ADR-019).
   Para toda unidad nueva que muta datos o arranca previews añade también
   `--require-control-plane`: el manifiesto liga el target a un namespace reproducible. La llamada
   al guard sucede antes de conectar y el preview acredita su fingerprint; un 200 no basta. El
   manifiesto señala el wrapper ejecutable y el recibo causal; el linter comprueba que el
   provisionador llama al guard canónico antes de su primera mutación. Una allowlist de hosts
   remotos se aporta con `--control-plane-allow-host` desde configuración de confianza, nunca
   desde el propio target.

   **La contraprueba del criterio portante** (ADR-030), en carril **normal y completo**: la
   suite en verde no demuestra que los tests MUERDAN — un test vacuo pasa exista o no el
   comportamiento, y atraviesa esta revisión, la suite y el OK del usuario sin que nadie lo
   note. Quien construye la paga sobre UN solo criterio, el **portante** que declara
   §Verificación de la especificación (lo eligió quien redactó el contrato, no quien
   construyó ni quien revisa) y la deja en la sección **Contraprueba del criterio portante**
   de `hallazgos.md`:
   1. rompe a propósito la implementación de ESE criterio;
   2. pega el rojo LITERAL, que tiene que fallar **por eso** —un rojo por un import roto o
      un error de sintaxis no prueba nada—;
   3. restaura: `git checkout -- <fichero>` o `git restore <fichero>`, **nunca `git stash`**
      (prohibido: la pila es única y compartida entre TODOS los worktrees, y un pop se lleva
      el trabajo de otra rama);
   4. **demuestra** que el árbol quedó igual, no lo afirma: `git diff HEAD` vacío y
      `git rev-parse HEAD` idéntico al de antes de romper, los dos pegados, y el test otra
      vez en verde.
   En **directo y exprés no se pide**: el carril entero existe para no pagar ceremonia. En
   **bug** no se repite: ya la exige el par ROJO→VERDE del paso 7 de `runbooks/bug.md`.
2. **Revisión: alguien que no construyó, con el diff y el contrato delante.** Cada criterio
   implementado, casos límite con test, nada fuera de
   los ficheros declarados, los tests no tocados después de crearse, y ningún módulo
   duplicado de lo que ya existía. Su veredicto va a la sección **Revisión** de
   `hallazgos.md`, y su nombre y la fecha al frontmatter (`revisor:`, `revisado:`) **en la
   misma escritura que el veredicto** — es el único que sabe quién es; el despacho del revisor
   se lo pide con esas palabras.

   **Y mira la contraprueba, no la cree.** En normal y completo, el revisor comprueba que la
   sección Contraprueba de `hallazgos.md` está pagada de verdad: que el criterio es el
   portante declarado en la especificación, que el rojo pegado **nombra ese criterio**, que
   la restauración no usó `git stash`, y que el `git diff HEAD` vacío y los dos
   `git rev-parse HEAD` cuadran. Si falta, si el rojo va de otra cosa o si la restauración
   se afirma sin pegarse, es hueco de corrección y vuelve al constructor. Esto no lo puede
   comprobar ningún script —por eso lo hace una persona leyendo el parte— y por eso está
   escrito aquí en vez de fingir un linter que no puede fallar.

   **El revisor es SIEMPRE una sesión o subagente NUEVO** (ADR-017), en todo carril que
   revisa (el exprés no revisa: solo el verde). "De solo lectura" significa sobre el CÓDIGO
   y los papeles de la unidad: su única escritura permitida —y obligada— es su veredicto y
   su firma (`revisor:`, `revisado:`) en la sección Revisión de `hallazgos.md`, en la misma
   pasada. En `normal` y `completo` el contexto fresco importa porque el trabajo mueve el
   mapa o toca hotspots; en `directo` es además obligado, porque ahí quien construyó fue el
   padre (regla 1 de `AGENTS.md`).

   Se lanza por `ejecucion.py lanzar NNN-slug --harness claude --rol revisor --prompt
   "Revisa el diff contra el contrato y firma hallazgos.md"` (o `--harness codex`). El perfil
   hace read-only el código y solo permite como escritura persistente la firma derivada de esa
   unidad; cwd, rama y el probe quedan en el recibo `ejecucion/v1` (ADR-022).

   **El revisor no puede ser quien construyó.** Esto no lo relaja ningún carril:
   lo que los carriles cambian es cuánto papeleo hay, no que la revisión exista.
   **Una firma que falta no se rellena después.** Si al cerrar `revisor:` sigue
   vacío, ya nadie puede saber quién revisó: se vuelve a revisar con un agente fresco. El padre
   escribiendo un nombre plausible es justo el auto-sello que este campo existe para impedir.

   **Frontera del revisor (regla, no preferencia).** Devuelven el trabajo al constructor, y
   solo ellos: los incumplimientos del contrato de ESTA unidad, los fallos de seguridad y
   todo lo que pierda datos. Un riesgo de un flujo futuro, una mejora, un "convendría dejarlo
   preparado para cuando…" **no reabren la unidad**: se anotan como trabajo descubierto y
   siguen su camino. Una segunda ronda de revisión solo la abre un fallo crítico. Preparar
   hoy problemas que aún no existen retrasa lo único que enseña de verdad: que el usuario use
   la app.
3. **Fusionar** por el camino A o el B (tabla de arriba), **pero antes, la puerta de
   prefusión** (bug 066):

   `python3 docs/00-metodo/scripts/unidad.py prefusion NNN-slug`

   Exige dos cosas y no fusiona nada: que la rama esté **rebasada sobre la principal** (que la
   punta de la principal sea antecesora suya) y que **`lint_metodo.py` —que lleva dentro el
   trinquete de `lint_salidas`— esté en verde sobre ese árbol ya rebasado**. Si falta la
   primera, el FAIL trae `git -C worktrees/NNN-slug rebase main`; si falta la segunda, el
   comando del linter y su salida literal.

   Por qué aquí y no después. La principal **avanza** entre el veredicto LIMPIO del revisor y
   el ff: el 25-08 avanzó dos veces y cada avance metió un rechazo mudo nuevo, que el trinquete
   cazó al fusionar —con el cierre ya en marcha y arreglando dentro del ritual. Y el diff que
   el revisor dio por bueno era el de otro árbol. Un rojo aquí no se negocia: se rebasa, se
   arregla y se vuelve a pasar la puerta.

   De paso, y solo si las dos están en verde, **re-anota la base de despacho** que el rebase
   dejó vieja: `base_sha` pasa a ser el `merge-base` con la principal de HOY y el
   `origin/main` del día del despacho se conserva en `base_sha_despacho_original`. Sin esto,
   la medida del carril directo del paso 6 cuenta como propios los commits ajenos que el
   rebase metió por debajo (el 25-08 hubo que corregir el SHA a mano ocho veces). Es el único
   momento en que se puede: después del ff la rama entera está dentro de la principal y el
   `merge-base` ya no distingue el trabajo de nadie.
4. **Tests sobre la rama principal, al nivel que el cambio merece** (ADR-016), con los comandos
   del `AGENTS.md` del repo de código:

   | Carril | Qué se corre |
   |---|---|
   | exprés · directo | los tests del **área tocada** (los ficheros de `ficheros:` y lo que dependa de ellos) |
   | normal | área tocada + **suite completa** |
   | completo · migración · hotfix | suite completa **end-to-end** |

   Correr la suite entera por un cambio de dos ficheros no compra seguridad: gasta minutos y
   llena el contexto de salida irrelevante. Y si el proyecto **no tiene forma de saber qué
   depende de qué**, no se adivina: se corre la suite completa y se anota la deuda en
   `hallazgos.md`.
   Un rojo NO se negocia, sea del nivel que sea.

   Después del merge, `quality-security` debe quedar verde sobre el commit de la principal.
   Con GitHub se espera y verifica ese check; sin GitHub se ejecutan desde `main/`
   `scripts/ci/lint` y `scripts/ci/security`. Un rojo deja la unidad sin cerrar y `main` sin
   permiso de despliegue: el merge no convierte un fallo en aceptable (ADR-018).
   Cuando la unidad toca permisos, la evidencia incluye una denegación real del servidor. Si
   los planos declaran `pruebas_e2e`, incluye además los aliases sintéticos afectados;
   `full-suite` ya contiene los E2E mínimos seleccionados y no se repite en navegador la
   matriz exhaustiva que vive en tests rápidos (ADR-019).
5. **Cuando la política exige app, lanzarla y hacer que el usuario la pruebe** (mismo
   `AGENTS.md`), con los
   ejemplos reales de sus criterios. **Sin su OK no hay cierre**; "no es lo que
   pedí" no se discute: se abre una unidad tipo `bug` — y su contrato pide el mismo OK que
   cualquier otro, con el visor de contratos levantado en el turno en que se le pregunte
   (`python3 main/visor_contratos/servir.py --workspace . --minutos 0`). La fecha de ese OK es
   lo que se le pasa al comando del paso 6.

   **Lo que se le pega en la conversación** (esto, y nada más):

   | unidad | qué se hizo | estado |
   |---|---|---|
   | 007-albaranes | editar un albarán facturado recalcula el total | listo, esperando tu OK |

   App corriendo en: `<enlace>` · Ficha: `docs/05-trabajo/007-albaranes/especificacion.md`

   …y debajo, la tabla **"Cómo lo pruebas tú"** de esa especificación (o la §6 de la ficha,
   si es un bug), tal cual. Si está en blanco, se escribe ANTES de llamarlo: sin ella el
   usuario devuelve un "me parece bien" que firma una entrega sin haber comprobado nada.

   Documental y exprés no inventan una app ni un OK. El prototipo no se cierra: deja la ficha
   `descartada` y cancela sus procesos con `peticion.py marcar-proceso`. Si la
   política sí lo exige y el usuario no está disponible ahora (ADR-010), ejecuta el paso 6 SIN
   `--ok-usuario`.
   Aplica todas las demás puertas y, si están en verde, deja la unidad en `en_validacion`:
   fusionada y terminada, esperando solo a una persona. Deja de contar para el tope de trabajo
   en vuelo —puedes despachar otra— pero NO está cerrada: no se archiva, no se borra worktree
   ni rama, y el linter la recuerda en cada arranque. Cuando llegue el OK, el mismo comando
   con su fecha termina el ritual.
6. **Los pasos mecánicos, con el script:**

   `python3 docs/00-metodo/scripts/unidad.py cerrar NNN-slug --ok-usuario YYYY-MM-DD`

   Si la ficha declara `control_plane: requerido`, también declara el
   `target_fingerprint` esperado y añade
   `--recibo-control-plane .runtime/control-plane-receipt.json`. El recibo debe vivir dentro del
   workspace y acreditar comandos, códigos de salida, digest SHA-256, el mismo target, la secuencia
   causal, el scope y el presupuesto de la ruta. Sin él, o si contradice la ficha, no se toca nada.

   Comprueba lo que la política de la ruta no permite saltar (OK, revisión, descarte o fusión),
   además de no perder trabajo sin guardar, y solo entonces hace lo
   mecánico: deja escrito el OK, anota en la ficha el commit con el que entró el trabajo
   (`fusion:`), pone la unidad en `mergeada`, borra el worktree y la rama **local**, archiva
   la unidad (los bugs no se archivan, ADR-006) y pasa el linter. Si algo falla, dice cuál y
   no toca nada.

   **La rama remota NO se borra.** `origin/NNN-slug` es la única copia del trabajo que no vive
   en este disco: se queda para siempre, y es lo que mira el cierre cuando la rama local ya no
   está. Una rama que no existe no prueba que se fusionara — prueba que alguien la borró — y
   ese es el único camino por el que este método puede perder trabajo entregado. Si no queda
   ningún rastro (proyecto sin remoto, rama borrada y ficha sin `fusion:`), el cierre BLOQUEA
   y solo se desatasca con `--fusion <sha>`, que exige un commit que exista y esté de verdad
   dentro de la principal.
7. **Lo que el script no hace, porque es criterio y no mecánica:** aplicar los deltas
   declarados a `02-flujos/` y pasar el flujo a `entregada` · promover aprendizajes a
   `conocimiento/` y decisiones/orden al ADR o ROADMAP · todo **trabajo descubierto aceptado
   se marca `→ promovido a P-ID` antes de crear otra unidad** · actualizar `ESTADO.md` (e
   `INDICE.md` si es un bug).

## Puertas que no se negocian

- En directo/normal, sin OK del usuario sobre la app corriendo no hay cierre. Lo que
  `en_validacion` permite es seguir trabajando mientras se espera, no dar por cerrado.
- Sin revisor distinto del constructor no hay cierre en las rutas que lo exigen; el prototipo se
  cancela sin convertirse en entrega y exprés conserva su control en commit/PR.
- Nada sin guardar en el worktree: es lo único del método que no respalda nadie.
- Nada desplegable se cierra sin estar fusionado; documental no se fusiona y prototipo no se
  cierra por diseño.
- Sin un resumen que el usuario entienda, no hay cierre: si para pedirle el OK hay que
  explicarle el método, el mensaje está mal escrito (`00-metodo/comunicacion.md`).
