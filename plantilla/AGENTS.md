# AGENTS.md — {{TITULO}} (meta-repo)

Este es el **meta-repo de orquestación**: aquí vive el pensamiento del proyecto (`docs/`) y el
método. El código vive en otro repo, `main/` (solo lectura), y se trabaja en `worktrees/`.
`.claude/personalidad.md` con directrices se aplica desde tu primera respuesta (CÓMO hablas, no QUÉ haces);
placeholder o vacío: ni lo apliques ni lo menciones; si NO existe, créalo tú en silencio
(cabecera `# Personalidad del agente (opcional)`); ilegible: avísalo UNA vez y sigue, sin bloquear.

## Al arrancar (haz esto antes que nada)

0. **El aviso del método corre SIEMPRE, también en solo-consulta, y va lo primero.** Ejecuta
   `python3 docs/00-metodo/scripts/herramienta.py comprobar` (se corta solo: ≤15 s TODO el
   proceso): compara con el repo del método (`origen` de `METODO.json`) leyendo solo su fichero de
   versión; calla si `.claude/actualizaciones.md` dice `preferencia: nunca`. Con versión nueva, dilo
   UNA vez por sesión: **tu PRIMER párrafo al usuario ES ese aviso con sus cuatro respuestas, antes
   de cualquier otro contenido o trabajo** — posponerlo o mencionarlo de pasada es un fallo de arranque:
   **sí** (`… herramienta.py aplicar`: consigue la herramienta sola —tu clon si es del mismo origen y
   está limpio; si no, descarga temporal que jamás toca el tuyo— y confirma qué cambió) · **todos** (`… aplicar --todos`) · **no
   por ahora** · **nunca más** (`… herramienta.py nunca`). ¿Fallo, tardanza, red o acceso? Ni una línea: arranca igual, sin aviso ni pedir nada.
1. **Solo-consulta arranca ligero.** ¿La petición solo LEE? Salta el resto del arranque (2-6) —el
   paso 0 no se salta jamás— y responde con el router, sin rol. Si va a escribir o ejecutar: 2-6.
2. **Actualiza el taller:** ejecuta `setup.py` con el Python disponible: coloca `main/` en la última
   `origin/main` por fast-forward; si no puede, PARA y explica por qué. Nunca trabajes desde una referencia remota antigua.
3. **Linta el método:** `python3 docs/00-metodo/scripts/lint_metodo.py`. Un FAIL tuyo se
   arregla antes de seguir; uno causado por el método no te bloquea (regla 13, ADR-026).
4. **Lee `docs/05-trabajo/ESTADO.md`**: dónde estamos, qué hay en vuelo y qué toca ahora.
5. **Declara tu rol al usuario y confírmalo ANTES de trabajar.** Ofrécele los tres:
   - **CONSTRUCTOR** (el de por defecto): construye, especifica, despacha y cierra unidades.
   - **OBSERVABILIDAD** (solo lectura): revisa el estado real del sistema y reporta; no arregla.
   - **DEPLOY**: el único con manos en producción.
   Un rol = una sesión: **no se mezclan**. Por defecto: CONSTRUCTOR. Para tocar flujos asume
   ANALISTA DE FLUJOS (regla 14). Permisos y gates: `docs/00-metodo/roles.md`.
6. **Mira el canario:** `python3 docs/00-metodo/scripts/canario.py`, y otra vez tras cada tarea larga. Si avisa
   —capacidad ("zona de riesgo") o conducta ("ya está degradando")— pega el parte de `canario.py retomada` y di que
   esta sesión está degradada: mejor cortar y seguir en una NUEVA. En Codex, sin hook, es el ÚNICO mecanismo.

## Orden de lectura (router) — lee solo lo que tu tarea necesita

| Si vas a… | Lee |
|---|---|
| Recibir cualquier petición accionable | **PRIMERO** `docs/00-metodo/runbooks/peticiones.md` |
| Orientarte (¿dónde estamos?) | `docs/05-trabajo/ESTADO.md` |
| Entender qué es esta aplicación | `docs/01-constitucion/manifiesto.md` |
| Decidir o dudar sobre tecnología | `docs/01-constitucion/bias.md` |
| Entender el negocio y sus actividades | `docs/02-flujos/INDICE.md` (el detalle de una actividad, solo si la tocas) |
| Saber cómo trabajamos (fases, carriles, tipos) | `docs/00-metodo/README.md` |
| Detalle de tu rol (analista · constructor · observabilidad · deploy) | `docs/00-metodo/roles.md` |
| Cómo hablarle al usuario y cada cuánto | `docs/00-metodo/comunicacion.md` |
| Trabajar la unidad NNN | `docs/05-trabajo/NNN-*/especificacion.md` (contrato + plan) |
| Reportar o trabajar un bug | `docs/bugs/NNN-slug.md` + runbook `bug` (ADR-006) |
| Cerrar una unidad (de cualquier tipo) | `docs/00-metodo/runbooks/cierre.md` |
| Saber qué hay instalado en esta máquina | `python3 docs/00-metodo/scripts/doctor.py` |
| Cambio pequeño que encaja donde ya vive (**el caso normal**) · cambio trivial sin comportamiento | `runbooks/directo.md` · `runbooks/expres.md` |
| Producción caída / urgencia | `docs/00-metodo/runbooks/hotfix.md` |
| "Quiero que lo use mi gente" / ponerlo en internet | `docs/00-metodo/runbooks/primer-despliegue.md` (la primera vez) · `runbooks/deploy.md` (las demás) |
| Añadir, cambiar o aprobar flujos y requisitos | `docs/00-metodo/requisitos/RUNBOOK.md` |
| Consultar cimientos técnicos del proyecto | `docs/03-investigacion/SINTESIS.md` (lo escribe la fase 3) |
| Ver el roadmap | `docs/04-planificacion/ROADMAP.md` (lo escribe la fase 4) |
| Entender un porqué del MÉTODO | `docs/00-metodo/decisiones/` |
| Entender un porqué de ESTE proyecto | `docs/decisiones/` |
| Aprovechar lo ya aprendido | `docs/conocimiento/` |

## Reglas duras

1. **Quién construye lo dice el CARRIL (ADR-017).** En **exprés y directo construye el PADRE**,
   en el worktree de la unidad, a la vista del usuario: delegar trabajo pequeño cuesta la caché,
   un salto de contexto y toda la visibilidad, y no devuelve casi nada. En **normal y completo**
   lo hace un subagente constructor por `scripts/ejecucion.py` en `worktrees/NNN-slug/`. **El revisor es SIEMPRE un agente
   fresco de solo lectura, distinto de quien construyó** — eso no lo relaja ningún carril.
2. **Escritura.** Quien construye escribe en su worktree y en su unidad: `hallazgos.md` +
   casillas `[x]` del plan (bugs: `docs/bugs/NNN-slug.md`). Los ficheros compartidos —
   `ESTADO.md`, `INDICE.md`, `ROADMAP.md`, `conocimiento/`, `decisiones/`— los escribe SOLO el
   padre, en el cierre. Una unidad `--documental` no crea worktree: lee `main/` y escribe solo
   en SU carpeta.
3. **Git del meta-repo: solo el padre**, con rutas explícitas. Nunca `git add -A`.
4. **Entrada, numeración y despacho: con scripts, no a mano.** La primera escritura de toda
   petición accionable es `peticion.py capturar`; después se evalúa por `runbooks/peticiones.md`.
   Una unidad nace con `unidad.py nueva <tipo> <slug> --desde P-ID [--directo]`: asigna el NNN
   y bloquea trabajo sin origen. `--force` solo sirve para el hotfix y deja deuda escrita. **Pedir un OK sobre un contrato (unidad o bug) = levantar el visor de contratos en el mismo turno:** `python3 main/visor_contratos/servir.py --workspace . --minutos 0`; sin su rastro, `despachar` bloquea aunque `aprobado:` tenga fecha (regla 16).
5. **Trabajo en vuelo: UNA unidad de código por defecto**, sin tope numérico, solo si no
   comparten ficheros (`ficheros:`, que el script cruza). Las `en_validacion` no cuentan. Las unidades
   `--documental` (leen, no escriben código) tampoco: pueden ir en paralelo.
6. **Búsquedas de código: dentro de `main/` o de tu worktree.** Desde la raíz no verás código
   (el gitignore lo oculta a las herramientas de búsqueda); eso es intencional.
7. **Merge y cierre son indivisibles.** Verificar + `lint_ci.py` → revisar (quien no construyó,
   diff contra el contrato) → merge → tests + seguridad → **lanzar la app y que el usuario la pruebe** (sin
   su OK no hay cierre; `cerrar` sin `--ok-usuario` deja `en_validacion` y libera cupo) →
   deltas al mapa → promover hallazgos → `ESTADO.md` → archivar → borrar worktree y rama. No
   existe "mergeado pero sin cerrar". El ritual entero, sus dos caminos (con `gh` y sin él) y
   la frontera del revisor: `runbooks/cierre.md`. Los bugs no se archivan (ADR-006).
8. **Desviación de contrato → PARA y escala.** Si al construir tu trabajo va a contradecir la
   especificación o el mapa (eliminar algo, cambiar comportamiento prometido), detente. Las
   desviaciones de implementación (cambia el cómo, no el contrato) se terminan y se reportan.
9. **Carriles (cuatro).** Exprés: cabe en una frase Y no cambia comportamiento → sin documentos. **Directo, el del día a día**: cambia comportamiento pero encaja en una actividad que YA está en el mapa, sin moverlo, 1-3 ficheros sin hotspots, diff < 250 líneas y se deshace
   revirtiendo → ficha de una pantalla y 2 puertas (`runbooks/directo.md`). Normal: mueve el mapa, toca hotspots o no cabe en la ficha. Completo: transversal, arriesgado o desconocido,
   `+ investigacion.md`. **Si cambia comportamiento nunca es exprés**, y ante la duda se SUBE de carril. Producción caída: `hotfix.md`. Ningún carril recorta la evidencia, la revisión firmada ni el OK del usuario sobre la app.
10. **Esfuerzo y modelo por carril (ADR-016).** Exprés y directo: el modelo y el razonamiento
    más baratos que hagan el trabajo. Normal: medio. Completo y hotfix: el alto. Revisor:
    modelo DISTINTO al que construyó. Lint y unidades documentales: el modelo pequeño.
11. **Buscar tiene fin y la investigación es graduada.** Se elige `ninguna`, `acotada` (2-4
    lentes) o `plataforma` por incertidumbre y riesgo, no por tamaño (`peticiones.md`). Antes de
    explorar, di qué buscas y cuándo paras. Fuente oficial y reciente; afirmación con fuente y
    fecha. Sin fuente = opinión. Un riesgo crítico no concluyente bloquea la orden.
12. **Evidencia, no afirmación.** Nada se da por hecho sin el output del check que lo demuestra.
    "Hecho" sin evidencia no es hecho. Las líneas base se miden al vuelo, no de una foto; un
    fallo repetido no se normaliza. **Los outputs largos se REFERENCIAN por ruta en `.runtime/`,
    no se pegan**: solo el veredicto y las líneas que lo prueban.
13. **Los guardianes se lintean.** `lint_metodo.py` al arrancar y cerrar; `lint_ci.py` antes
    del merge (`--require-e2e` si los planos seleccionan E2E); `lint_deploy.py` antes de producción. Un FAIL del proyecto se arregla; uno causado por el MÉTODO se registra (`caja_negra.py registrar`) y NO te bloquea: sigue, el arreglo llega por Modo D (ADR-026). Estructura solo con ADR.
14. **Los flujos siguen vivos — la puerta la abre el DELTA, no el cambio.** Si el trabajo **añade, quita o contradice** algo del mapa, asume el rol ANALISTA DE FLUJOS y sigue `docs/00-metodo/requisitos/RUNBOOK.md`: modifica `docs/02-flujos/planos/`, enseña el visor web y obtén la aprobación ANTES de crear unidades de código (ADR-007). Si cabe dentro de un
    flujo ya escrito, esa puerta NO se abre: el delta, si lo hay, se escribe en el cierre con el trabajo ya visto funcionando (ADR-014).
15. **Proceso nativo (ADR-021).** Diseño, plan, debugging, TDD, revisión y cierre son locales;
    skills de proceso no, skills técnicas sí. Todo agente delegado pasa por `ejecucion.py` (ADR-022).
16. **Nadie espera a ciegas** (§ más abajo): un rato largo callado es un fallo, no una espera.

## Reglas de oro (siempre)

- **Producción y servicios externos (pagos, DNS, correo, chat) son LECTURA por defecto.**
  Cualquier mutación exige autorización explícita del usuario.
- **Fusionar main NO despliega.**
- **Nunca mostrar secretos ni PII.** Viven en `.private/` (referencia por ruta, jamás copia);
  lo generado (logs, capturas, dumps), en `.runtime/`. Ambos fuera de git.
- **Escribir sobre material del usuario se anuncia y se deja escrito** (su instancia, sus datos).
- **Antes de afirmar que algo funciona, ejecutar la verificación que lo demuestra.**
- **Se escribe según se hace:** cada paso, en el momento, con fecha y con quién lo hizo. Lo que
  solo está en el contexto de tu sesión está perdido; lo rellenado después de memoria es
  inventado (por eso una revisión sin firma se repite, no se firma).
- **Caja negra.** `caja_negra.py registrar`: contexto y referencias van al JSONL privado,
  nunca conversaciones/secretos. El análisis posterior es semántico y lo hace un LLM.

## Nadie espera a ciegas (regla 16 · detalle y traducciones: `00-metodo/comunicacion.md`)

- **Sin jerga del método.** Si una palabra solo existe dentro de `docs/00-metodo/`, no sale por
  el chat. Nombres de fichero y de script sí, con lo que hacen al lado.
- **Parte de avance: una línea por casilla del plan, en cuanto se marca.** La señal ya existe —
  el plan se marca según se hace—: hay que SACARLA, no guardarla para el cierre.
- **Antes de empezar: cuántos pasos y cuánto va a durar.** Pasos, no porcentajes. Jamás "ya casi".
- **Silencio máximo: 5 minutos.** Si se van a superar, se avisa ANTES. Un rato largo callado es
  un fallo del método. Si el silencio no cabe en su paciencia, la unidad es demasiado grande.
- **Atascado se dice, no se disimula**: dos intentos con el mismo error, o el mismo comando
  repetido, se cuentan en vez de seguir probando en silencio.
- Un rojo son tres datos: qué comprobación, qué falla y quién lo arregla. Informe de una pantalla.

## Autoridad de la información (qué fuente manda en conflicto)

El código y sus tests describen el producto de su rama · `docs/` describe el workspace y el método · `git -C main worktree list` es el inventario autoritativo de worktrees · `docs/bugs/`
es la verdad de los bugs · los papeles de una unidad archivada son historia, no doctrina · **lo escrito gana a lo recordado**.

## El repo de código

- `main/` — clon canónico. Solo `git pull`. **Jamás editar, commitear ni crear ramas aquí.**
  Única excepción, nombrada y acotada (ADR-009): el merge del paso 3 del cierre sin `gh`.
- `worktrees/NNN-slug/` — worktree de unidad; exprés usa `expres-P-ID-slug`. Se crean desde
  peticiones evaluadas y se borran al cerrar. Todo PR conserva ese nombre en el título.

## Origen de este workspace

Bootstrap desde los planos de la entrevista. `01-constitucion/manifiesto.md` y `02-flujos/`
son salida compilada: **no se editan a mano** (los cambios van por el RUNBOOK de requisitos).
El método (`docs/00-metodo/`) viaja con la plantilla; aquí no se modifica sin ADR.
