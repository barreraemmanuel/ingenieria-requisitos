# Runbook · ADOPCIÓN (brownfield — primera unidad del proyecto, obligatoria)

**Cuándo:** el workspace se provisiona sobre un repo que YA tiene implementación real
(`main/` contiene algo más que README/CI; el bootstrap lo detecta y viaja
`bias/brownfield.md`). **Ninguna unidad de código se despacha antes de tener
una adopción demostrable**: primero conocer, después tocar.
**Tipo y carril:** unidad `investigacion` + `auditoria`, carril **completo**
(`especificacion.md` + `investigacion.md`). **NO toca el repo de código**: solo lectura de
`main/`, sin worktree de escritura — todas las salidas van al meta-repo.
**Contrato de cierre:** inventario, comandos y estado de la suite **con output real pegado**,
`03-investigacion/SINTESIS.md` escrita, el gap-map revisado y decidido por el usuario, y la
**fase 3 acotada corrida o declarada "sin temas"** por escrito (paso 6).

## Paso a paso

### Paso 0 · No repetir trabajo ya hecho

La ingeniería de requisitos brownfield analiza el código antes de entrevistar y debe dejar
`03-investigacion/ADOPCION.md`. Si existe, el padre comprueba que contiene inventario,
comandos ejecutados, estado real de tests y gap-map con evidencias. Completo: la adopción ya
está cerrada y se continúa directamente por el paso 6, investigación técnica acotada.
Incompleto o ausente: se ejecutan ahora los pasos 1-5. Nunca se repite todo “por si acaso”.

**Doctrina: de memoria nada, todo con rutas citadas.** Cada afirmación cita el fichero de
`main/` que la sostiene (ruta exacta) o el output del comando que la demuestra.

El padre lanza **un subagente cartógrafo principal** para los pasos 1-5. Ese subagente puede
leer todo `main/`, pero no escribir en él; deja el inventario y el gap-map en la unidad de
adopción. Se usa uno para mantener una visión coherente del sistema completo. Si el repositorio
es demasiado grande, el padre puede darle ayudantes con zonas disjuntas, pero el cartógrafo
principal integra y responde por el mapa final.

1. **Inventario del código** (solo lectura de `main/`): estructura del repo · stack real **y
   versiones leídas de los ficheros de dependencias** — `package.json`, `pyproject.toml`,
   `go.mod`, lockfiles, `Dockerfile`, CI — nunca supuestas por el nombre del framework ·
   convenciones vivas (capas, nombrado, patrones que se repiten) · **toda la documentación
   existente**: README, `docs/`, configs, variables de entorno de ejemplo, comentarios clave.
2. **Comandos reales de build / test / arranque: EJECUTADOS**, no citados de memoria ni
   copiados del README (el README miente con frecuencia). Se pega el output. Si un comando
   documentado no funciona, eso es un hallazgo: se anota el comando que SÍ funciona.
3. **Estado de la suite de tests:** ¿existe? ¿corre? ¿está en verde? Output real pegado,
   incluidos los fallos. **Sin suite (o con suite en rojo) = deuda declarada
   nº 1: no se toca comportamiento sin red de tests.** La primera unidad después de la
   adopción es añadir **tests de caracterización** de la zona que se vaya a tocar (fijan lo
   que el código hace HOY, no lo que debería hacer) — antes de eso no se modifica nada.
4. **Gap-map código↔flujos.** Contrastar `02-flujos/` (que salió de la entrevista y **jamás
   miró el código**) con lo encontrado, en dos direcciones: (a) qué promete el mapa que el
   código NO hace; (b) qué hace el código que el mapa NO recoge. Cada hueco, con su evidencia
   (ruta, o ausencia comprobada), es un **candidato al ROADMAP**.
5. **Salidas** (todas al meta-repo): `03-investigacion/ADOPCION.md` con inventario, comandos,
   tests y gap-map; y `03-investigacion/SINTESIS.md` con el stack existente documentado como
   **bias efectivo**, más la lista de **unidades candidatas** derivadas del gap-map.
6. **Fase 3 ACOTADA — no se salta.** Cerrada la adopción se corre `runbooks/investigacion.md`,
   pero acotado: los investigadores **NO re-eligen el stack** (ya está decidido — es el que
   vive en `main/`, documentado como bias efectivo en el paso 5). Investigan solo:
   (a) lo que el gap-map haya revelado como **desconocido o arriesgado**; (b) **versiones y
   vulnerabilidades del stack existente** (fin de soporte, CVE, notas de versión, upgrades
   pendientes). El mínimo de 10 enfoques es de la fase 3 de cero: aquí el número lo fija el
   gap-map. Los informes van a `03-investigacion/` como siempre y se integran en la
   `SINTESIS.md` ya escrita.
   **Si el gap-map no revela nada desconocido, se escribe "fase 3 sin temas"**
   en `SINTESIS.md` (sección homónima: por qué, quién y cuándo) y se pasa a la 4. Es una
   decisión escrita y aprobada por el usuario, **nunca un salto silencioso**.
7. **Cierre.** El usuario revisa el gap-map y decide qué entra al ROADMAP y en qué orden;
   con eso y con los informes del paso 6, la fase 4 (`planificacion.md`) arranca desde aquí
   en vez de partir de cero. Ritual de cierre normal del `00-metodo/README.md`, salvo lo que
   no aplica: no hay merge ni instancia que validar (esta unidad no toca código).
8. **Primera unidad técnica: materializar el CI real.** Antes de tocar comportamiento, una
   unidad usa el stack, la suite y los comandos YA descubiertos para crear el contrato de
   ADR-018: `scripts/ci/{full-suite,lint,security}`, workflows `tests` y
   `quality-security`, Dependabot y `main/AGENTS.md`. No sustituye la suite ni cambia el
   stack. Sin `pruebas_e2e`, conserva esas tres interfaces y
   `lint_ci.py --repo worktrees/NNN-slug` debe quedar verde antes del primer merge. Si los
   planos declaran `pruebas_e2e`, ESTA misma unidad adopta la autenticación existente —no la
   reescribe—, materializa además `scripts/ci/{provision-e2e,e2e}` y deja la cadena
   `full-suite → e2e → provision-e2e → tests E2E`; antes del primer merge exige
   `lint_ci.py --repo worktrees/NNN-slug --require-e2e`. Son cinco scripts en ese caso, no una
   deuda que pueda aplazarse a otra unidad (ADR-019).

## Reglas duras

1. **Adherencia total al stack existente.** Se construye como ya se construye ahí: mismos
   frameworks, mismas convenciones, mismos comandos. Cambiar una pieza del stack no es una
   unidad normal: es una `migracion` con su ADR.
2. **Prohibido reescribir lo que funciona** sin decisión explícita del usuario.
3. **Los principios universales** (open source, mínimo código, mínima invención, "¿puedo irme
   en una tarde?") valen como criterio para lo NUEVO — **nunca** como excusa para reescribir.
4. **El repo de código sigue siendo solo código:** la adopción no le deja ficheros de agentes
   ni documentación del método.
5. **El entorno local se DESCUBRE, no se decide.** En un proyecto de cero el entorno de
   ejecución y testing se decide en la fase 4; aquí ya existe: sale de los pasos 2-3 y se
   documenta tal cual en `SINTESIS.md`. Solo si está roto o falta se abre decisión con el
   usuario (y entonces sí, por `planificacion.md`). **Cuando no hay entorno NINGUNO** —ni
   fichero de dependencias, ni contenedor, ni README de arranque—, no se reconstruye la
   infraestructura que el código insinúa: se le pregunta («¿lo va a usar más gente a la vez, o
   lo corres tú en tu máquina?») y el punto de partida por defecto es lo mínimo que arranque
   en la máquina que ya usa. Los servicios que el código nombre (bases de datos, índices,
   colas) se comprueban PRIMERO en esa máquina: si ya están, se usan tal cual.
6. **La adopción no escribe CI a escondidas.** Primero documenta la verdad en solo lectura;
   después, la unidad técnica del paso 8 materializa y revisa el cambio como cualquier otro.
