# Auditoría de sanidad — playbook del rol SANIDAD

Checklist eje a eje de la revisión de limpieza del workspace. Lo ejecuta el guardián
(`scripts/sanidad.py`); esto es lo que hay que saber para **leer** su salida: de dónde sale
cada número, cuándo es grave, qué se arregla solo y —lo más importante— **cómo se refuta un
hallazgo antes de llevárselo al usuario**.

Recorrido completo de la sesión: `runbooks/sanidad.md`. Decisión que lo fija: ADR-031.
Roles y fronteras: `roles.md` §SANIDAD. Puntos ciegos del guardián: `detectores.md`.

## 0 · Antes de nada

```bash
python3 docs/00-metodo/scripts/sanidad.py medir            # los once ejes, salida corta
python3 docs/00-metodo/scripts/sanidad.py medir --detalle  # con cada hallazgo
```

Tres reglas que mandan sobre todo lo que sigue:

- **Lo no medido no está bien** (G-2402). Un eje `NO_COMPROBADO` no es un aprobado: lleva su
  motivo y su `SALIDA:` con lo que falta instalar o clonar. Nunca se cuenta como OK.
- **Nunca peor que la última vez** (G-2403). La comparación se hace contra la última fila de
  `docs/05-trabajo/SANIDAD.md`, no contra un número recordado. Sin libro, la primera pasada
  solo mide y anota.
- **Precisión antes que volumen** (R8). Cada hallazgo lleva `confianza: alta | media`. Solo
  los de confianza alta se capturan como petición por defecto. Un hallazgo que no se ha
  refutado con el fichero delante no sale de aquí.

La evidencia larga no se imprime: cada eje deja su listado en
`.runtime/sanidad/<AAAA-MM-DD>/<eje>.txt` y la tabla lo referencia por ruta.

## 1 · Los once ejes

### 1 · pendiente

**Qué mira:** peticiones en `capturada`/`evaluando` con su edad, unidades y bugs
`en_validacion` y sus días esperando, contratos en obra con `aprobado: no`, y worktrees sin
unidad viva (el inventario real lo da `git worktree list` unido a lo que hay en `worktrees/`).

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje pendiente --detalle`

**Número:** peticiones en cola, y entre paréntesis la edad de la más vieja.

**Umbral:** más de 20 en cola o alguna de más de 14 días → WARN · `en_validacion` de más de 7
días → WARN · worktree huérfano → **FAIL** (es trabajo perdido o un cierre a medias).

**Severidad:** el huérfano es grave: o hay una rama con trabajo sin dueño o un cierre no
terminó. Lo demás es cola, y la cola larga esconde lo urgente.

**Auto-repara:** no. Aquí no se toca nada: triar una petición es del usuario.

**Cómo se refuta:** una petición vieja puede seguir siendo deseada — se comprueba abriéndola
en el visor de contratos, no por su edad. Un worktree «huérfano» puede ser un despacho de
hace cinco minutos: se mira `git -C main worktree list` y la rama antes de decir nada.

**Qué NO ve:** si una petición vieja sigue siendo deseada; si lo que espera validación está
bloqueado por el usuario o por el método.

### 2 · deuda

**Qué mira:** `TODO`/`FIXME`/`XXX`/`HACK` en el código con su fecha de `git blame`, deudas de
hotfix con fecha de vencimiento en los frontmatters, y el «Trabajo descubierto» de los
`hallazgos.md` de unidades activas que no acabó en petición ni en descarte.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje deuda --detalle`

**Número:** marcas de más de 90 días, y entre paréntesis el total.

**Umbral:** TODO de más de 90 días → WARN con la lista · deuda de hotfix vencida → **FAIL**.

**Severidad:** la deuda de hotfix vencida es un contrato incumplido (`runbooks/hotfix.md`).
Los TODO fósiles son leves en masa, salvo que uno esconda un bug conocido: entonces es un bug
sin unidad y sube a MEDIA.

**Auto-repara:** no. Borrar un TODO no paga la deuda; solo la esconde.

**Cómo se refuta:** se abre el fichero por la línea. Un TODO que documenta una decisión
consciente («TODO: no soportamos X a propósito hasta que…») no es deuda: es una nota, y lo que
procede es reescribirla sin la marca, en una unidad. Sin `git` en la máquina no hay fecha:
todo sale con confianza media y el eje lo dice (`stdlib:aproximación`).

**Qué NO ve:** deuda que nadie escribió — la peor. Ningún grep encuentra lo que no está
marcado.

### 3 · papeles

**Qué mira:** `.md` totales bajo `docs/`; actas sueltas al lado de `ESTADO.md`
(`VALIDACION-*`, `RETOMADA-*`, `APROBACION-*` y cualquier `.md` que no sea `ESTADO.md` ni
`SANIDAD.md`); líneas de `ESTADO.md`; `.md` de más de 40 KB; ficheros de `conocimiento/` que
nadie cita; informes de `03-investigacion/` sin enlace desde `SINTESIS.md`; y ficheros
generados (`.DS_Store`, `*.orig`, `*.rej`, `*~`) dentro de `docs/`.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje papeles --detalle`

**Número:** actas sueltas, y entre paréntesis el total de `.md`.

**Umbral:** más de 2 actas o alguna de más de 30 días → WARN (y se repara) · `ESTADO.md` de
más de 100 líneas → WARN · `.md` de más de 40 KB → WARN · papel huérfano → WARN.

**Severidad:** leve en cuanto a riesgo, alta en cuanto a coste: un `ESTADO.md` de 200 líneas
deja de leerse, y lo que no se lee no informa.

**Auto-repara:** **sí** — actas viejas a `docs/05-trabajo/archivo/actas/` (reescribiendo las
referencias a su ruta vieja) y ficheros generados, que se borran.

**Cómo se refuta:** antes de aceptar «papel huérfano», se busca el fichero por su nombre en
todo `docs/`: un plano de observabilidad se cita desde `roles.md` y sigue siendo esencial
aunque nadie lo enlace esta semana. Un `.md` grande puede ser un manual que se quiere entero.

**Qué NO ve:** si un papel es valioso aunque nadie lo cite. El conteo mide atención, no valor.

### 4 · rutas

**Qué mira:** rutas `docs/…`, `main/…` y `scripts/*.py` citadas en los `.md` del meta-repo que
hoy no existen. Las plantillas (`00-metodo/plantillas/`) se saltan a propósito: son
formularios con huecos, no afirmaciones.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje rutas --detalle`

**Número:** rutas rotas.

**Umbral:** más de 0 → WARN, cada una con sus candidatos.

**Severidad:** media. Una ruta rota en un runbook es una instrucción que no se puede seguir.

**Auto-repara:** **sí, y solo** cuando el nombre final existe **exactamente una vez** bajo
`docs/` (el caso «se archivó y nadie actualizó el enlace»). Con cero o con más de un candidato
se deja como hallazgo con la lista de candidatos, para que lo decida una persona.

**Cómo se refuta:** una ruta puede estar rota **a propósito** (un ejemplo de lo que NO hay que
escribir) o ser una promesa de algo que aún no existe. Se lee la frase entera antes de
reescribir nada.

**Qué NO ve:** rutas escritas de forma que no parecen rutas («el fichero de estado»), y rutas
dentro del repo de código.

### 5 · docs-en-codigo

**Qué mira:** `.md` y `.rst` dentro del repo de código que no están en la lista blanca
(`README.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CHANGELOG.md`, `LICENSE*`,
`CONTRIBUTING.md`, todo lo que cuelga de `plantilla/`, `docs/`, `RUNBOOK/` o `.github/`, y lo
que enlaza un `README.md` vecino). Los que llevan «decisión», «ADR», «arquitectura» o «spec»
en el nombre suben a confianza alta.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje docs-en-codigo --detalle`

**Número:** papeles fuera del meta, y entre paréntesis los que parecen decisiones.

**Umbral:** más de 0 → WARN. Petición: mover al meta-repo (ADR-001).

**Severidad:** media. Documentación en dos sitios es documentación que se contradice.

**Auto-repara:** **no** — es el otro repositorio, y la sanidad no lo toca jamás (G-2401). El
movimiento es una unidad de la ola, con su contrato.

**Cómo se refuta:** un `.md` puede ser un fixture de test, la plantilla que el propio código
genera, o documentación que la herramienta publica desde ahí. Se mira quién lo lee antes de
proponer moverlo.

**Qué NO ve:** documentación que vive en comentarios de código, que es la más difícil de
mover y la que más se pudre.

### 6 · codigo-muerto

**Qué mira:** módulos no importados ni referenciados (detector `ast` portado de
`auditoria-calidad.md` §2.6), funciones y clases públicas nunca referenciadas por nombre, y
bloques de tres o más líneas de código comentado. Si están instalados, `vulture
--min-confidence 80` y `ruff --select F401,F841,ARG` mejoran la medida y el eje lo declara.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje codigo-muerto --detalle`

**Número:** candidatos de confianza alta, y entre paréntesis todos.

**Umbral:** algún candidato de confianza alta → WARN.

**Severidad:** media. Git ya recuerda lo borrado; el fichero no debe.

**Auto-repara:** **no**. Borrar código es una unidad con tests, nunca un efecto secundario de
medir.

**Cómo se refuta:** obligatorio, uno por uno. Un módulo cuyo nombre aparece en un `.sh`,
`.yml`, `.toml`, `.md`, en `AGENTS.md` o en un `subprocess`/`runpy` del repo baja solo a
confianza media, **y con él todo lo que define**: desde fuera no se puede saber quién lo
llama. Nunca son hallazgo `main`, `setUp`/`tearDown`, un `test_*`, un método mágico ni nada
decorado. Lo que quede en alta se abre y se busca a mano (cron, `Procfile`, docs de deploy,
plantillas de despliegue) antes de capturarlo.

**Qué NO ve:** código llamado por reflexión (`getattr`, entry points, plugins) o desde fuera
del repositorio. Por eso ningún hallazgo de este eje autoriza a borrar: autoriza a preguntar.

### 7 · tests

**Qué mira:** cobertura con `coverage json` **si `coverage` está instalado y ya hay medida**
(el guardián no lanza la suite ajena: sale en menos de 60 s y no tiene efectos); si no, la
aproximación por fichero (módulos con `test_<nombre>.py` frente al total). Además: asserts
borrados en commits de modificación bajo `tests/` (`auditoria-metodo.md` check 3) y bugs
archivados cuyo test de regresión ya no existe (`auditoria-calidad.md` §2.5, ADR-006).

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje tests --detalle`

**Número:** % de cobertura si se midió con la herramienta; si no, módulos sin ningún test.

**Umbral:** ratchet contra el libro —peor que la última fila → WARN— · assert borrado sin una
unidad que lo justifique → **FAIL** · bug archivado sin test vivo → **FAIL**.

**Severidad:** los dos FAIL son graves: un test debilitado y un bug sin regresión son la forma
silenciosa de que algo vuelva.

**Auto-repara:** no.

**Cómo se refuta:** un assert «borrado» puede haberse movido de fichero o reescrito más
fuerte: se busca el commit (`git log -S '<assert>' -- tests/`) y se lee su mensaje y su
unidad. Un módulo sin `test_<nombre>.py` puede estar probado desde un test de integración con
otro nombre. Sin `coverage` la medida es por fichero y no dice nada de las ramas: el eje lo
declara como `stdlib:aproximación` y la aproximación no se presenta como si fuera cobertura.

**Qué NO ve:** si un test prueba algo (unidad 046: la contraprueba de test no vacuo es otra
cosa). Un 100 % de cobertura con asserts vacíos sale verde aquí.

### 8 · docstrings

**Qué mira:** `ast.get_docstring` de módulos, clases y funciones públicas del repo de código
(los tests no cuentan); `interrogate` si está. Además, cada comando entre backticks del
`AGENTS.md` del repo que apunte a una ruta que no existe.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje docstrings --detalle`

**Número:** % de definiciones públicas documentadas, y entre paréntesis los módulos.

**Umbral:** módulos por debajo del 100 % → WARN · funciones públicas por debajo del 80 % →
WARN · ratchet contra el libro · comando de `AGENTS.md` roto → **FAIL**.

**Severidad:** el comando roto es grave: es la puerta por la que entra cada agente al repo.

**Auto-repara:** no.

**Cómo se refuta:** un módulo generado o un `__init__` de paquete no necesitan prosa. Una
función pública trivial tampoco: lo que se persigue es el módulo sin explicar y la API sin
contrato, no el porcentaje.

**Qué NO ve:** docstrings falsas o vacías de contenido («devuelve el resultado»), que cuentan
igual que las buenas. El porcentaje mide presencia, no calidad.

### 9 · drift

**Qué mira:** deltas al mapa declarados por unidades archivadas que `02-flujos/` no refleja
(`auditoria-metodo.md` check 6); `cobertura.evidencias` y `pruebas` de cada `planos.json` que
apuntan a rutas inexistentes; `detectores.md` que cita scripts que ya no están, o un
`lint_*.py` sin fila; y `VERSION` frente a la cabecera de `CHANGELOG.md`.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje drift --detalle`

**Número:** inconsistencias.

**Umbral:** más de 0 → WARN; un delta declarado que el mapa no refleja → **FAIL**.

**Severidad:** el delta no aplicado es grave: el merge entró y el mapa quedó mintiendo. Todo
lo que se decida encima de ese mapa se decide sobre algo falso.

**Auto-repara:** no. Aplicar un delta es leer el negocio, no reemplazar una cadena.

**Cómo se refuta:** el nombre que el delta declara puede aparecer en el mapa escrito de otra
forma. Se abre `02-flujos/INDICE.md` y se busca el concepto, no el literal.

**Qué NO ve:** promesas que el código incumple sin cambiar de ruta — la spec dice que hace X,
la ruta existe, y dentro hace Y. Eso es auditoría de calidad, con el código delante.

### 10 · decisiones

**Qué mira:** las tecnologías que el código usa de verdad —paquetes de `requirements*.txt`,
`pyproject.toml`, `setup.cfg` y `package.json`, imports de terceros, imágenes base de
`Dockerfile` y `compose`— que no menciona ni `01-constitucion/bias.md` ni `docs/decisiones/`
ni `docs/conocimiento/`.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje decisiones --detalle`

**Número:** tecnologías sin decisión escrita.

**Umbral:** más de 0 → WARN. Petición: abrir un `DP-NNN` o ampliar el bias.

**Severidad:** media, y creciente: cada dependencia sin decisión es una que nadie podrá
justificar ni retirar dentro de un año.

**Auto-repara:** no. Escribir la decisión es la decisión.

**Cómo se refuta:** la tecnología puede estar decidida con otro nombre (el paquete
`psycopg2-binary` es «PostgreSQL» en el bias), o ser una dependencia transitiva que el
proyecto no eligió. Se busca el concepto en el bias antes de capturarlo.

**Qué NO ve:** decisiones implícitas en la arquitectura —«todo síncrono», «un solo proceso»—
que no aparecen en ningún manifiesto y son las que más cuestan cambiar.

### 11 · dependencias

**Qué mira:** por cada manifiesto, cuántas dependencias están fijadas (`==`, versión exacta,
lockfile) y cuántas sueltas; la edad del lockfile; y **solo con `--red`**, `pip-audit -r` o
`npm audit` para vulnerabilidades.

**Comando:** `python3 docs/00-metodo/scripts/sanidad.py medir --eje dependencias --detalle`
· con red: `… --eje dependencias --red`

**Número:** dependencias sin fijar.

**Umbral:** alguna suelta → WARN · alguna vulnerable → **FAIL** · sin `--red`, o con `--red`
pero sin auditor instalado o sin red utilizable → `NO_COMPROBADO` con su `SALIDA:`, **nunca
OK**.

**Severidad:** la vulnerabilidad es grave y tiene dueño inmediato. Lo suelto es reproducible:
una build de hoy y otra de mañana no traen lo mismo.

**Auto-repara:** no. Fijar una versión es cambiar el código y exige que la suite pase.

**Cómo se refuta:** una dependencia suelta que solo vive en un fichero `*-dev*` o `*-test*`
baja sola a confianza media —no entra en producción—, y muchas veces está bien así. Una
vulnerabilidad reportada puede no ser alcanzable desde este proyecto: se lee el aviso.

**Qué NO ve:** dependencias del sistema (apt, brew, imágenes base sin manifiesto), que son las
que suelen romper la máquina de otro.

## 2 · Cierre de la pasada

Cuando los once ejes están leídos y los hallazgos refutados:

```bash
python3 docs/00-metodo/scripts/sanidad.py reparar --simular   # se lee ANTES de aplicar
python3 docs/00-metodo/scripts/sanidad.py reparar
python3 docs/00-metodo/scripts/sanidad.py capturar            # solo confianza alta
python3 docs/00-metodo/scripts/sanidad.py medir --anotar      # la fila del libro, al final
```

El commit lo hace el padre, con rutas explícitas y mensaje `sanidad: …`: el guardián no
ejecuta git nunca. El recorrido completo, con sus puertas, está en `runbooks/sanidad.md`.
