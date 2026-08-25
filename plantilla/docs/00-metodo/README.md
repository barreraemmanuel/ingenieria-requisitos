# El Método — manual de operación

## Principio rector: sistema cerrado

Este método deja **lo mínimo posible a la imaginación y a la variabilidad entre sesiones**:

- Todo lo repetible está en una **plantilla** (se rellena), un **runbook** (se sigue paso a
  paso), un **script** (se ejecuta) o un **hook** (se cumple solo).
- El agente **rellena y ejecuta; no inventa**. Formatos, estados y rituales son vocabulario
  cerrado: no se crean variantes.
- Lo que el método no cubre **se escala al padre; no se improvisa**.
- Regla de confianza: script/hook (se cumple solo) > plantilla (guía la forma) > prosa (se pide).

## Las 7 fases

Antes de entrar en una fase o carril, toda petición accionable pasa por
`runbooks/peticiones.md`: se captura, contrasta e investiga con perfil `ninguna`, `acotada` o
`plataforma`. Es una entrada trazable, no una octava fase ni un sustituto del ROADMAP.

| # | Fase | Nivel | Produce |
|---|---|---|---|
| 1 | Constitución | proyecto | `01-constitucion/` — manifiesto + bias tecnológico |
| 2 | Flujos | proyecto | `02-flujos/` — mapa del negocio por actividades (de la entrevista) |
| 3 | Investigación | proyecto | `03-investigacion/` — cimientos técnicos (multi-rol, multi-sesgo, acotada por el bias) |
| 4 | Planificación | proyecto | `04-planificacion/ROADMAP.md` — unidades, orden, dependencias; esqueleto andante primero |
| 5 | Especificación | unidad | `05-trabajo/NNN-slug/especificacion.md` — contrato + plan de trabajo (ADR-005) |
| 6 | Construcción | unidad | padre en exprés/directo; subagente en normal/completo (ADR-017) |
| 7 | Cierre | unidad | verificar → revisar → merge → e2e + instancia validada → consolidar (indivisible; `runbooks/cierre.md`) |

Las fases 1-4 se recorren al arrancar el proyecto y se **actualizan** después (nunca se
re-hacen enteras). Las fases 5-7 se repiten por cada unidad de trabajo.

## Los 4 carriles (criterio de entrada, obligatorio decidirlo al abrir trabajo)

| Carril | Criterio de entrada | Papeles | Puertas del usuario |
|---|---|---|---|
| **Exprés** | El diff cabe en una frase **Y** no cambia comportamiento | Ninguno — el rastro es el commit/PR (`expres.md`) | 0 (solo el aviso) |
| **Directo** | Cambia comportamiento pero **encaja donde ya vive**: una actividad que ya está en el mapa, sin moverlo, 1-3 ficheros sin hotspots, y se deshace revirtiendo | Ficha de una pantalla (`directo.md`) copiada como `especificacion.md` | 2 |
| **Normal** | Todo lo demás: mueve el mapa, toca hotspots, o no cabe en una ficha | `especificacion.md` (contrato + plan de trabajo) | 4 |
| **Completo** | Transversal, arriesgado, o toca territorio desconocido | + `investigacion.md` de la unidad | 4 |

**El carril por defecto del día a día es DIRECTO**, no normal: casi todo el trabajo real encaja
en una actividad que ya existe. Normal es para lo que de verdad mueve el mapa. Ante la duda se
sube un carril, nunca se baja: la duda ya es la prueba de que el cambio es más grande.

Si cambia comportamiento, **nunca** es exprés. Producción caída para usuarios reales no es un
carril sino una **excepción de despacho**: runbook `hotfix.md` (bug P0 que se salta la espera de
aprobación, nunca la verificación).

**Lo que ninguna ruta recorta jamás**, porque no es ceremonia sino garantía: evidencia ligada al
target, no perder datos y no filtrar secretos. Revisión, fusión y OK sobre una app son obligatorios
cuando existe una entrega desplegable; documental y prototipo no los fingen. La matriz y los
presupuestos viven en `runbooks/control-plane.md` (ADR-024).

## Los 7 tipos de unidad (cada uno con su runbook y su plantilla)

| Tipo | Contrato de cierre |
|---|---|
| `bug` | Fichero vivo en `docs/bugs/` que NO se archiva (ADR-006): tests de integración + e2e (+ unit si hacen falta) en rojo → fix → verde, sin tocar los tests + regresión contraprobada |
| `feature` | Comportamiento nuevo verificado por los criterios de la especificación |
| `refactor` | Nada observable cambia; la suite existente sigue verde |
| `migracion` | Mismo comportamiento sobre base nueva; suite completa |
| `auditoria` | Informe con hallazgos verificados (no toca código); los aceptados paren unidades |
| `investigacion` | Preguntas respondidas con fuentes → se promueve a `conocimiento/` |
| `documentacion` | Docs correctos verificados contra la realidad |

## Vocabulario cerrado de estados

- **Unidad** (`estado:` en el frontmatter de su especificación):
  `planificada → en_obra → en_revision → mergeada` · desvíos: `bloqueada`, `descartada`.
  Entre medias cabe `en_validacion` (ADR-010): la rama ya está fusionada y el trabajo
  de construcción terminó; lo único pendiente es que el usuario pruebe la app, así que
  NO cuenta como trabajo en vuelo y no ocupa cupo de paralelismo.
  Al cerrar, la carpeta pasa a `archivo/` (estado final implícito: archivada).
- **Actividad**: la fuente de verdad es `02-flujos/planos/planos.json`, que lo escribe el
  aparato heredado de ingeniería de requisitos (ADR-007); `02-flujos/INDICE.md` lo refleja.
  Manda el vocabulario del aparato —
  `sin empezar → en entrevista → especificada → en obra → entregada` — y estas son las
  equivalencias con los nombres cortos que usan los runbooks: `por_descomponer` = *sin
  empezar*, `en_obra` = *en obra*. No se crean más variantes.

## Frontmatter obligatorio de `especificacion.md`

```yaml
---
unidad: NNN-slug
tipo: bug | feature | refactor | migracion | auditoria | investigacion | documentacion
carril: directo | normal | completo
estado: planificada | en_obra | en_revision | en_validacion | mergeada | bloqueada |
        descartada
aprobado: no | YYYY-MM-DD
actividad: <id del INDICE de flujos>
ficheros: [rutas que esta unidad posee — dos unidades paralelas jamás comparten]
peticiones: [P-ID@revision que esta unidad satisface]
actualizado: YYYY-MM-DD
---
```

**`aprobado:` lo pone el USUARIO, nunca el agente.** Es el rastro comprobable de la puerta
de aprobación de la especificación: `no` mientras no lo haya leído y aceptado, y la **fecha
del día en que lo aprueba** cuando da su OK (se exige fecha y no un "sí" porque una fecha dice
*cuándo* se leyó). Sin esa fecha, `unidad.py despachar` **bloquea** y el linter da FAIL si
encuentra una unidad `en_obra`/`en_revision` sin ella. Única excepción: el hotfix P0
(`--force --motivo "…"`), que deja marca de deuda con reloj de 24 h.

## Los rituales (pasos fijos, en orden, sin saltos)

**Despacho de una unidad** (el padre): 1. capturar y evaluar la petición · 2. ejecutar
`unidad.py nueva <tipo> <slug> --desde P-ID` y rellenar la especificación · 3. el usuario anota y aprueba el contrato, y su OK
queda escrito como `aprobado: YYYY-MM-DD` (sin esa fecha `unidad.py despachar` bloquea) ·
4. rellenar contexto y plan de trabajo (misma spec) · 5. crear worktree `NNN-slug` · 6. lanzar
constructor con la especificación como punto de entrada · 7. actualizar ESTADO.md.

**Cierre de una unidad** (el padre, **a petición del usuario**, indivisible, sea del tipo que
sea): el ritual completo, con sus dos caminos (con `gh` y sin él) y la frontera del revisor,
vive en **`runbooks/cierre.md`**, que es por donde cierran TODOS los tipos. En corto:
1. verificar con evidencia (checks + output) · 2. revisión por quien NO construyó — **siempre
una sesión o subagente fresco de solo lectura**, en todo carril que revisa (ADR-017; el
exprés no revisa: solo el verde): diff contra especificación
(requisitos, edge cases, alcance; **que los ficheros de test no se tocaron después del commit
que los creó** y **que no se ha duplicado un módulo que ya existía en `main/`**) — veredicto a
la sección **Revisión** de `hallazgos.md`, firmado con `revisor:` y `revisado:`; huecos →
vuelven al constructor · 3. merge · 4. **tests sobre main al nivel del carril** (ADR-016;
tabla exacta en `runbooks/cierre.md`) · 5. **lanzar
una instancia de la app** (comando de arranque: el `AGENTS.md` del repo de código) y
**validación del usuario sobre ella**; sin su OK no hay cierre, "no es lo que pedí" → unidad
`bug` · 6. `unidad.py cerrar NNN-slug --ok-usuario YYYY-MM-DD`, que aplica las puertas y hace
lo mecánico (estado `mergeada`, archivar la unidad — los bugs no, ADR-006 —, borrar worktree y
rama **local** — la remota NO se borra jamás: es la única copia del trabajo fuera de este
disco (ADR-011) —, y lintar) · 7. lo que es criterio y no mecánica, que sigue siendo del
padre: aplicar deltas a `02-flujos/`, promover hallazgos → `conocimiento/` y decisiones →
`decisiones/`, y actualizar `ESTADO.md` + `INDICE.md`.

**Frontera del revisor** (ADR-009): devuelven el trabajo al constructor los incumplimientos
del contrato de ESA unidad, los fallos de seguridad y lo que pierda datos — nada más. Riesgos
de flujos futuros y mejoras se anotan como trabajo descubierto y NO reabren la unidad; solo un
fallo crítico permite una segunda ronda. Preparar hoy problemas que aún no existen retrasa lo
único que enseña de verdad: que el usuario use la aplicación.

## Piezas del método

- `runbooks/` — además de los 7 tipos: `cierre.md` (**el ritual de cierre, común a todos los
  tipos**, con el camino con `gh` y el camino sin él), `directo.md` (el carril corto del día a
  día), `expres.md` (carril exprés: rama efímera, sin unidad) y `hotfix.md` (producción caída:
  se salta la espera de aprobación, con deuda de spec a pagar en 24 h). Cada tipo tiene su
  recorrido, sus puertas y su cierre.
  `investigacion.md` es también el runbook de la fase 3; `planificacion.md`, el de la fase 4.
- `plantillas/` — por unidad: especificacion (contrato + plan de trabajo, ADR-005),
  directo (la ficha de una pantalla del carril directo, ADR-014),
  bug (fichero vivo en `docs/bugs/`, ADR-006), hallazgos, investigacion (carril completo) ·
  por proyecto: informe y sintesis (fase 3), roadmap (fase 4), y `agents-repo-codigo.md` (el
  AGENTS.md que la primera unidad deja DENTRO del repo de código, con los comandos exactos de
  entorno, suite, e2e, instancia para el usuario y seguridad).
- `roles.md` — los roles del padre (analista de flujos, constructor, observabilidad, deploy),
  con la entrevista de arranque de los dos operativos (ADR-008).
- `decisiones/` — **los ADR DEL MÉTODO**: el porqué de estas reglas. El índice es el listado
  de la carpeta (`ls`), no una lista escrita a mano que se queda atrás. Se leen, no se editan;
  cuando un runbook cita "ADR-005", está aquí. Las decisiones de TU proyecto van en
  `docs/decisiones/`, con numeración propia desde `001` y citadas como `DP-NNN`: así
  `ADR-NNN` señala siempre, sin ambigüedad, a esta carpeta.
- `requisitos/` — el kit heredado de la herramienta de ingeniería de requisitos: runbook,
  visor web y scripts para mantener vivos los `planos.json` de `02-flujos/` (ADR-007).
- `detectores.md` — **qué mira cada guardián y qué NO ve**: la tabla que impide confundir
  «el linter está verde» con «esto está bien». Todo `lint_*.py` tiene su fila.
- `auditoria-metodo.md`, `auditoria-calidad.md`, `auditoria-sanidad.md`, `auditoria-seguridad.md`,
  `seguridad-por-stack.md`, `sandbox.md` y `scripts/lint_deploy.py` — seguridad, aislamiento y
  gate de pre-despliegue.
- `scripts/ejecucion.py` — **control plane obligatorio** de constructores delegados y revisores:
  deriva unidad/worktree/rama, fija cwd/PWD, sanea entorno y skills, prueba el sandbox y deja
  checkpoints en `.runtime/ejecuciones/` (ADR-022). Exprés/directo no lanzan otro LLM.
- `scripts/unidad.py` — **el despachador**: `nnn` (siguiente número libre, mirando unidades,
  archivo, bugs y ramas) · `nueva <tipo> <slug> [--directo]` (crea la unidad desde su plantilla;
  con `--directo`, desde la ficha corta del carril directo) ·
  `despachar <NNN-slug>` (crea rama y worktree, registra `preparado`/`sin_hook` en
  `.runtime/worktree-readiness/` y BLOQUEA/deshace si el hook explícito falla; también bloquea
  si falta la aprobación del usuario —`aprobado:` sin fecha—, si la spec no tiene prosa real
  o si ya hay trabajo en vuelo;
  `--force` es la válvula de producción caída: **solo** unidades tipo `bug` con severidad
  **P0** declarada y `--motivo "…"` obligatorio, que se escribe en la ficha junto a la deuda) ·
  `cerrar <NNN-slug> --ok-usuario YYYY-MM-DD` (**el cierre**: puertas —OK del usuario con
  fecha, revisión firmada por alguien distinto del constructor, worktree sin nada sin guardar,
  rama fusionada de verdad— y después la mecánica; ADR-009) · `estado`.
- `scripts/lease.py` — autoridad local para operaciones concurrentes (ADR-023): serializa la
  numeración, el despacho, los recursos declarados y Modo D con UUID de sesión, PID+inicio y
  fencing. Vive en `.runtime/`; otro host nunca se declara libre por su ausencia local.
- `scripts/control_plane.py` — guard anti-producción de los tests (un DSN de producción no se
  conecta), namespacing de puertos/DB/tags por repo+unidad (`:latest` rechazado) y la redacción
  de credenciales que reutilizan los demás scripts (ADR-024). `scripts/caja_negra.py` — la caja
  negra estructurada: `registrar`, `listar`, `validar` y `enviar` (feedback voluntario y
  redactado al autor del método). `repo_config.py` y `workspace_paths.py` son sus cimientos
  compartidos de rutas y configuración.
- `scripts/doctor.py` — **qué hay de verdad en esta máquina** (Python, git y su identidad,
  `gh`, Docker, Node) y qué implica cada ausencia. Lo corre `setup.py` y la fase 4: el ROADMAP
  no fija una herramienta que no esté aquí en verde. Informa, nunca bloquea.
- `scripts/coste.py` — **¿en qué se va el cupo?** Lectura pasiva de los rollouts que el
  harness ya escribe (`~/.claude/projects`): reparte el gasto en cuatro ejes (relectura de
  caché, escritura, entrada, salida), atribuye la relectura a cuatro orígenes (razonamiento,
  herramientas, andamiaje, persona), mide el texto siempre cargado como tamaño x turnos y
  simula qué habría ahorrado cortar cada N turnos, con el supuesto escrito al lado. `--json`
  deja una línea base y `--linea-base` compara contra ella: así se comprueba si un cambio del
  método abarató de verdad. No emite nota compuesta, no escribe en `~/.claude/` y no envía nada.
- `scripts/herramienta.py` — **el canal de actualización, sin depender de que la herramienta
  esté en el disco**: `comprobar` mira contra el repo del método (`origen` de `METODO.json`)
  leyendo solo su fichero de versión —un `git ls-remote` y, si se movió, un clon superficial
  y sparse—; `aplicar` consigue la herramienta (tu clon si está sano, con `pull --ff-only`;
  si no, una descarga a carpeta temporal, sin reparar jamás la tuya) y delega en su
  `visor/actualizar.py`. Sin red, sin credenciales o sin `origen`: silencio y exit 0.
- `scripts/lint_metodo.py` — **el linter del método**: valida estructura congelada,
  vocabulario cerrado, frontmatters, aprobación del usuario en lo que está en obra, deudas de
  hotfix sin pagar (WARN dentro de las 24 h, FAIL pasadas o si la unidad ya está mergeada),
  ESTADO ≤100, coherencia worktrees↔unidades, cierres a medias, **trabajo huérfano** (worktree
  con cambios sin guardar, rama que dice estar terminada sin un solo commit) y **secretos
  horneables** (Dockerfile sin `.dockerignore` que excluya el `.env`). Se ejecuta al arrancar
  sesión del padre, al final de cada cierre, y en CI.
- `scripts/sanidad.py` — **el guardián de sanidad** (ADR-031): `medir` da once ejes de salud
  del workspace y del código —pendiente, deuda, papeles, rutas, docs en el código, código
  muerto, tests, docstrings, drift, decisiones, dependencias— con veredicto, número y **con
  qué midió**; lo que no pudo medir sale `NO_COMPROBADO`, jamás `OK`. `reparar` aplica una
  lista CERRADA de arreglos de papeles del meta-repo (archivar actas, reescribir rutas rotas
  con destino único, borrar generados) y no toca código, planos ni git; `capturar` convierte
  lo del código en peticiones con evidencia; `atraso` cuenta cierres y días desde la última
  pasada. El libro comparable vive en `05-trabajo/SANIDAD.md`. Rol: `roles.md` §SANIDAD;
  receta: `runbooks/sanidad.md`; checklist eje a eje: `auditoria-sanidad.md`.
- `scripts/lint_ci.py` — **el contrato del CI por stack** (ADR-018): acepta el repositorio
  todavía vacío y, en cuanto hay código, exige suite completa, lint, seguridad, workflows y
  Dependabot reales; Actions por SHA y cero `|| true`. Se ejecuta sobre el worktree antes del
  merge. `lint_deploy.py` reutiliza esas mismas entradas sobre `main/` antes de producción.
- El **bootstrap** no vive aquí sino en la herramienta de ingeniería de requisitos
  (`visor/bootstrap.py`, junto a su `plantilla/`): es la ÚNICA forma de crear un workspace,
  y es quien coloca este `00-metodo/` en cada proyecto (ADR-002).

## Lo que cuesta cada carril (y por qué se elige el más corto que sirva)

| | Exprés | Directo | Normal | Completo |
|---|---|---|---|---|
| Quién construye | el padre | **el padre** | subagente | subagente |
| Quién revisa | nadie (solo el verde) | agente fresco | agente fresco | agente fresco |
| Puertas del usuario | 0 | 2 | 4 | 4 |
| Tests al cerrar | área tocada | área tocada | + suite completa | + end-to-end |
| Esfuerzo del modelo | el mínimo | bajo | medio | alto |

**Principio rector de esta fase: sencillez Barrio Sésamo.** Lo mínimo que cumpla el trabajo,
invisible para el usuario final; ante la duda, la pieza NO se construye. Descartado por
simplicidad: el presupuesto de tokens por unidad — el límite real de atención ya es UNA unidad
en vuelo. Lo que SÍ entra es el **criterio de parada**: antes de explorar se dice qué se busca y
cuándo se para; encontrado lo que contesta la pregunta, se para y se construye (regla 11).

**Iteración corta, no entrega perfecta.** La pregunta que ordena el trabajo no es "¿está todo
previsto?" sino **"¿cuál es la parte más pequeña que podemos poner hoy delante del usuario
para aprender algo?"**. De ahí: unidades pequeñas y contratos breves · un constructor y UNA
revisión · resolver el problema de hoy y no los futuros · pruebas sobre el comportamiento
nuevo, no sobre escenarios que aún no existen · enseñar cada incremento cuanto antes. Lo que
NO se recorta nunca, porque no es ceremonia sino garantía: no perder datos, no filtrar
secretos y no romper lo que el usuario ya aprobó.
