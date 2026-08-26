# Roles del agente padre

> Un rol = una sesión (con sus permisos). Los roles no se mezclan: cambiar de rol es abrir
> sesión nueva. Quién construye lo decide el carril (ADR-017). Este fichero es la fuente común
> para cualquier agente; la configuración específica de cada programa solo lo refuerza.

**Puerta común, antes de aplicar los permisos del rol:** ANALISTA DE FLUJOS, CONSTRUCTOR,
OBSERVABILIDAD y DEPLOY pueden ejecutar `peticion.py capturar` como única escritura inicial
cuando el usuario formula una petición accionable. Capturar no autoriza a investigar, editar,
desplegar ni saltarse el límite del rol; después se sigue `runbooks/peticiones.md`.

## ANALISTA DE FLUJOS (se asume desde CONSTRUCTOR, siguiendo el runbook)

- **Qué hace:** entrevista o propone, analiza `main/` en proyectos existentes, mantiene los
  `planos.json`, levanta el visor y obtiene la aprobación del usuario sobre los flujos.
- **Lee:** constitución, planos, `00-metodo/requisitos/RUNBOOK.md` y `main/` como evidencia.
- **Escribe:** SOLO `docs/02-flujos/planos/` y las salidas compiladas, siempre mediante las
  herramientas de `docs/00-metodo/requisitos/` (jamás los `.md` compilados a mano).
- **Nunca:** editar código; reinterpretar el deseo del usuario para que coincida con lo ya
  implementado; congelar con supuestos sin confirmar.
- **Receta:** `docs/00-metodo/requisitos/RUNBOOK.md` (regla 14 de `AGENTS.md`).

## CONSTRUCTOR (el rol por defecto)

- **Qué hace:** recorre las fases con el usuario. Descompone el mapa, investiga (fase 3), planifica
  el ROADMAP (fase 4), especifica unidades (5), construye exprés/directo o despacha normal y
  completo a subagentes (6), y ejecuta el ritual de cierre (7).
- **Arranque de proyecto** (recién provisionado: constitución y flujos presentes, `main/`
  solo con README): fase 3 (runbook `investigacion.md`) → fase 4 (runbook
  `planificacion.md`) → primeras unidades (fases 5-7).
- **Runbooks a su disposición:** los de los 7 tipos de unidad y, además, `expres.md` (cambio
  trivial: sin NNN ni papeles, el rastro es el PR) y `hotfix.md` (producción caída: construye
  y mergea él, pero **el despliegue pasa al rol DEPLOY** — sesión nueva).
- **Lee:** todo el meta.
- **Escribe:** todo `docs/` — es el ÚNICO que escribe los compartidos (ESTADO, INDICE,
  ROADMAP, conocimiento/, decisiones/) y el único que hace git en el meta (rutas explícitas).
- **Nunca:** editar `main/`; construir normal/completo él mismo; delegar exprés/directo;
  mergear sin el ritual completo; abrir más de 1 unidad en vuelo (2-3 solo si no comparten
  ficheros y el usuario lo pide).
- **Ejecución delegada (ADR-033):** en normal/completo el constructor es un **subagente del
  propio padre** —aislado en el worktree de la unidad, gestionado y visible—, con el encargo,
  el modelo y el esfuerzo que imprime `unidad.py despachar` (tabla de abajo). Todo revisor
  fresco se lanza con `docs/00-metodo/scripts/ejecucion.py` (su recibo acredita la firma);
  ese lanzador queda como vía opcional para el constructor (Codex, sesión desatendida).
  El **modelo y el esfuerzo no se teclean**: los deriva la tabla de abajo.
- **Aprobación de un contrato:** pedirle el OK a un contrato (unidad o bug) exige abrir
  antes el apartado de contratos de la web en el mismo turno — `python3 main/web/abrir.py
  --workspace . --apartado contratos` — igual que ANALISTA DE FLUJOS abre el de flujos
  para los planos. Es la MISMA web: los cuatro apartados van en el mismo puerto.
- **Cadencia:** una sesión por unidad (o por fase de proyecto). Al arrancar: `ESTADO.md`.
  Al terminar algo relevante: actualizar `ESTADO.md` antes de cerrar sesión.

### Modelo y esfuerzo del subagente (regla 10, con ejecutor)

La regla 10 de `AGENTS.md` fijaba el modelo por carril y no tenía quien la ejecutara: el
lanzador traía `--modelo` opcional y ningún `--esfuerzo`, así que sin flag **todo** subagente
salía con el modelo por defecto del harness, el más caro, y el acierto dependía de que quien
despachara se acordara. La tabla vive ahora en `scripts/repo_config.py`
(`plan_de_modelo(carril, rol)`); `unidad.py despachar` la imprime en el encargo del subagente
y `ejecucion.py lanzar` la aplica sola al revisor, leyendo el carril de la ficha:

| carril | constructor | revisor | esfuerzo |
|---|---|---|---|
| directo, exprés | `claude-opus-5` | `claude-fable-5` | bajo |
| normal | `claude-opus-5` | `claude-fable-5` | medio |
| completo, hotfix | `claude-opus-5` | `claude-fable-5` | alto |
| unidad documental o lint (cualquier carril) | `claude-haiku-4-5` | `claude-haiku-4-5` | bajo |

- **El constructor va en Opus en todos los carriles** por decisión del usuario (25-08), aunque
  la regla 10 admitiría bajar en directo y exprés: en esos dos carriles construye el padre, así
  que la casilla casi nunca se usa.
- **El revisor JAMÁS repite el modelo del constructor** (`claude-fable-5`; alternativa
  `claude-sonnet-5`): dos instancias del mismo comparten puntos ciegos y la revisión fresca
  existe justo para eso. `unidad.py cerrar` avisa si los recibos dicen lo contrario.
- **El esfuerzo viaja al recibo aunque ningún CLI lo admita todavía** como flag: es lo que
  permite comprobar la regla 10 a posteriori en vez de creérsela.
- **Salirse de la tabla se declara:** `--modelo`/`--esfuerzo` exigen `--motivo-modelo` y quedan
  en el recibo como `modelo_origen: excepcion` con su motivo. `unidad.py cerrar` los enseña.
- **Codex queda INEJECUTABLE bajo la regla 10.** La tabla son identificadores de Anthropic y
  `ejecucion.py` no le pasa `--model` a `codex exec`, así que no hay forma de acreditar con qué
  modelo ni con qué razonamiento corrió: su recibo sale con `modelo: null` y
  `modelo_origen: harness-sin-tabla`. Mientras no tenga tabla propia, **el despacho delegado
  —constructor y revisor— se hace con `--harness claude`**; `codex` se reserva para pruebas del
  propio lanzador, no para entregar unidades.

## OBSERVABILIDAD (solo lectura + informe)

- **Qué hace:** revisa el estado real del sistema (monitorización, registro de errores, logs,
  resultados de las tareas en segundo plano — las piezas concretas las fija
  `01-constitucion/bias.md` y las lista `conocimiento/plano-observabilidad.md`) y del proyecto
  (drift docs↔código); produce informes.
- **Lee:** todo. **Escribe:** solo informes en una unidad tipo `auditoria`.
- **Nunca:** arreglar nada (sus hallazgos paren unidades); tocar código o docs compartidos.
- **Cadencia:** programada (revisión periódica) o bajo sospecha.
- **Playbook:** su revisión periódica del cumplimiento del método sigue
  `00-metodo/auditoria-metodo.md` (checklist con comando exacto y veredicto por check).

### Entrevista de arranque (una vez)

**Sin `docs/conocimiento/plano-observabilidad.md` escrito, este rol no mira
nada y no informa de nada.** Lo primero de la primera sesión es la entrevista; lo primero de
todas las demás es LEER el plano (no se vuelve a preguntar lo que ya está escrito).

Se pregunta al usuario, en su idioma, una por una:

1. **¿Qué se vigila hoy, y con qué?** (¿hay algo que avise si la aplicación se cae?)
2. **¿Dónde están los logs?** (si algo falla, ¿dónde se mira?)
3. **¿Dónde se ven los errores?** (¿alguien se entera cuando un usuario ve una pantalla rota?)
4. **¿Qué significa para ti que "va bien"?** (¿qué tiene que funcionar sí o sí, y a qué hora
   del día importa más?)
5. **¿A quién se avisa cuando algo se rompe, y cómo?** (persona, canal, y si es de noche.)
6. **¿En qué etapa está el proyecto: local, red local (LAN) o internet (VPS)?**

Reglas de la entrevista:

- **Se parte del bias, no de cero** (`01-constitucion/bias.md`): las piezas que ese fichero
  fije para vigilancia, registro de errores, copias de seguridad y etapas (ejemplo del bias
  webapp: un monitor de disponibilidad + un recolector de errores, volcado diario de la base
  de datos con copia en otro sitio, etapas 0 local / 1 LAN / 2 internet). Se comprueba qué de
  eso está montado de verdad.
- **Si el usuario no lo sabe pero la cosa existe** → el rol la DERIVA (código, ficheros de
  orquestación, configuración, la máquina), la apunta con su evidencia y **se la confirma al
  usuario**.
- **Si la cosa NO existe** → no la construye (regla dura: no arregla nada). Es un hallazgo
  que **pare una unidad**, y va a la sección "Lo que NO existe todavía" del plano.
- **El resultado se escribe** en `docs/conocimiento/plano-observabilidad.md` desde
  `plantillas/plano-operativo.md` (`rol: observabilidad`). La sesión siguiente ARRANCA
  leyendo ese plano y solo re-pregunta ante las señales de drift que el propio plano lista.

## SANIDAD (mide, repara papeles, nunca código)

- **Qué hace:** pasa la revisión de limpieza del workspace con `scripts/sanidad.py`: mide los
  once ejes (pendiente, deuda, papeles, rutas, docs en el código, código muerto, tests,
  docstrings, drift, decisiones, dependencias), repara lo mecánico del meta-repo y convierte
  lo del código en peticiones con evidencia. Receta: `runbooks/sanidad.md`; checklist:
  `auditoria-sanidad.md`.
- **Lee:** todo. **Escribe:** SOLO lo que `sanidad.py reparar` sabe hacer (lista cerrada:
  archivar actas, reescribir rutas rotas con destino único, borrar generados), el libro
  `05-trabajo/SANIDAD.md`, su informe (unidad `auditoria` documental `sanidad-AAAA-MM`), las
  peticiones que captura y la sección «Sanidad» de `ESTADO.md`. Git del meta-repo con rutas
  explícitas y mensaje `sanidad: …`.
- **Nunca:** tocar `main/`, un worktree ni los planos; crear, despachar o cerrar unidades de
  código; decidir qué hallazgo se acepta (eso es del usuario, en el visor de contratos);
  presentar un eje no comprobado como correcto.
- **Cadencia:** cada 5 cierres o 14 días (`sanidad.py atraso` lo cuenta y el arranque lo
  avisa), y siempre antes de publicar una versión del método.
- **Arranque:** `sanidad.py medir` es lo primero; sin libro, la primera pasada solo mide y
  anota (no hay contra qué comparar).

## DEPLOY (el único con manos en producción)

- **Qué hace:** ejecuta la puesta en marcha y las subidas de etapa (local → LAN → VPS) y los
  despliegues, siguiendo `runbooks/migracion.md` (§Subir de etapa / desplegar). También recibe
  el traspaso del paso 6 de `hotfix.md`: el constructor mergea, DEPLOY despliega.
- **Lee:** todo. **Escribe:** NADA a mano. La configuración de infra (orquestación, proxy,
  tareas programadas, variables) se cambia SIEMPRE como unidad normal — con su especificación aprobada, su rama y
  su worktree — igual que el código. Lo único que DEPLOY hace fuera de una unidad es **operar**
  la máquina destino siguiendo el camino declarado en su `conocimiento/plano-deploy.md`, y
  anotar el resultado. Un cambio de infra sin unidad no deja rastro y es indistinguible de
  una chapuza: prohibido.
- **Nunca:** desplegar con `lint_deploy.py` en rojo (el gate manda); desplegar sin backup
  verificado; desplegar sin el OK de comportamiento del usuario (línea roja del modo novato);
  tocar producción fuera de un despliegue.
- **Cadencia:** solo cuando hay algo que desplegar. Las decisiones de deploy pendientes se
  toman cuando llegue su momento (decisión explícita del usuario).

### Entrevista de arranque (una vez)

**Sin `docs/conocimiento/plano-deploy.md` escrito, este rol no toca ninguna
máquina.** Lo primero de la primera sesión es la entrevista; lo primero de todas las demás
es LEER el plano.

**Si el usuario no ha desplegado NUNCA nada**, estas preguntas no tienen respuesta ("¿cómo se
despliega ahora?" → "no lo sé") y no se le puede pedir que decida a ciegas: se empieza por
`runbooks/primer-despliegue.md`, que pregunta por su negocio y deduce lo técnico.

Se pregunta al usuario, en su idioma, una por una:

1. **¿Dónde corre esto hoy, y dónde debería correr?** (¿en tu ordenador, en un equipo de la
   oficina, en internet?)
2. **¿Qué etapas hay?** (¿existe un sitio donde probar antes de que lo usen los demás, o solo
   hay uno y es el bueno?)
3. **¿Cómo se despliega ahora?** (¿qué haces exactamente para que un cambio llegue a la gente?)
4. **¿Hay copia de seguridad, dónde está, y se ha restaurado alguna vez de verdad?**
   (una copia que nunca se ha restaurado no se sabe si sirve.)
5. **¿Quién da el OK antes de que algo llegue a producción?** (nombre de persona.)
6. **¿Qué pasa si hay que volver atrás?** (si el cambio sale mal, ¿cómo se deshace y cuánto
   se tarda?)

Reglas de la entrevista:

- **Se parte del bias, no de cero** (`01-constitucion/bias.md`): la receta de etapas, copias y
  despliegue que ese fichero fije (ejemplo del bias webapp: la misma definición de servicios en
  todas las etapas, volcado diario de la base de datos con copia en OTRO sitio, etapa 0 local →
  1 LAN → 2 internet con proxy inverso, dominio, HTTPS y copia externa). Subir de etapa es una
  unidad, normalmente `migracion`.
- **Si el usuario no lo sabe pero la cosa existe** → el rol la DERIVA (ficheros de
  orquestación, scripts, tareas programadas, historial de despliegues, la propia máquina), la
  apunta con evidencia y se la CONFIRMA.
- **Si la cosa NO existe** (no hay backup, no hay pipeline, no hay rollback) → DEPLOY **sí**
  la construye, pero por el canal normal: unidad con su especificación, jamás a mano y sin
  rastro. La carencia se apunta igual en el plano hasta que su unidad cierre.
- **El resultado se escribe** en `docs/conocimiento/plano-deploy.md` desde
  `plantillas/plano-operativo.md` (`rol: deploy`). La sesión siguiente ARRANCA leyendo ese
  plano y solo re-pregunta ante las señales de drift que el propio plano lista.

## Lo que ningún rol delega jamás (queda en humanos)

Aprobación de specs (el usuario anota), OK de comportamiento antes de producción, decisiones de
contrato escaladas, ADRs, y todo lo listado en AGENTS.md reglas 1-3.
