# Novedades del método

La versión del método viaja con cada proyecto (en su `METODO.json`). Para llevar
estas mejoras a tus proyectos ya creados: abre tu agente aquí y dile «pon al día
mis proyectos».

## 1.7.7 — 2026-08-24

**Seis trabajos que llevaban días hechos y sin repartir.** Desde la 1.7.3 entraron al método
033, 034, 035, 040, los cuatro arreglos de Windows (041-044) y el 052, y ninguno subió el
número: como el aviso de arranque compara solo eso, callaba, y los workspaces seguían con el
método viejo. Esta publicación es la que los reparte.

- **Windows deja de ser territorio hostil.** La suite corre allí (encoding explícito, symlinks
  que se saltan con motivo, dobles de harness que arrancan, `rmtree` contra los `0o444` de
  git); se acabó el mojibake en consola real y el clon de git olvidado en `%TEMP%` en cada
  arranque; el `bash` de Git for Windows se encuentra aunque no esté en el PATH; y
  `git worktree add` ya no muere con rutas de más de 260 caracteres.
- **SEGURIDAD: un junction ya no esquiva las guardas.** Un junction de Windows se crea **sin
  privilegio** y es invisible para `islink`, pero redirige igual. Se auditaron todas las
  guardas anti-enlace: caían dos, y las dos escribían FUERA del workspace — el lease y el
  reparto del propio método. Ahora se miran los reparse tags, no solo los symlinks.
- **Cada regla del método tiene quien la haga cumplir**, y las puertas que encerraban trabajo
  dicen por dónde se sale (033, 034).
- **El canario avisa por turnos, no por porcentaje** (035), y el visor abre la actividad que le
  pides en vez de la portada (040).
- **La suite vuelve a comprobar lo que dice comprobar** (052): seis tests medían el vocabulario
  viejo de un mensaje o simulaban Windows a medias, y tapaban que en macOS estaba roja.

Se publica como 1.7.7, y no como 1.7.4, porque el PR #54 tiene reservados 1.7.4, 1.7.5 y 1.7.6.

## 1.7.3 — 2026-08-19

Publicación de prueba, pedida por Nate, para verificar el update en un workspace cliente.
Sin ningún cambio de código.

## 1.7.2 — 2026-08-19

Publicación de demostración, pedida por Nate, para ver en vivo el aviso-primero de la
1.7.1 (un «hola» en un workspace al día en 1.7.1 debe abrir con este aviso). Sin ningún
otro cambio.

## 1.7.1 — 2026-08-19

**El aviso de actualización es lo primero que ves, en cualquier arranque** (unidad 032,
orden de Nate tras verlo enterrarse en campo). El chequeo del método pasa a ser el paso 0
del arranque y no se salta jamás — tampoco en un simple «hola»—: con versión nueva, el
primer párrafo del agente ES el aviso con sus cuatro respuestas; posponerlo o mencionarlo
de pasada queda definido como fallo de arranque. Además `.claude/personalidad.md` nace de
serie en cada workspace (placeholder anunciado una sola vez por el bootstrap) y los
workspaces anteriores lo crean solos en silencio: se acabó el aviso de «no existe» en cada
arranque. Revisado en dos rondas (Codex): las obligaciones históricas del canal («UNA vez
por sesión», «confirma qué cambió») se conservan.

## 1.7.0 — 2026-08-19

Publicación de refuerzo, a orden de Nate, para forzar el primer update de campo por el
canal nuevo: sin cambios de comportamiento sobre la 1.6.0.

## 1.6.0 — 2026-08-19

**El workspace se actualiza aunque la herramienta no esté en el ordenador** (unidad 031,
prioridad máxima de Nate). Un script nuevo viaja con el método en cada workspace,
`docs/00-metodo/scripts/herramienta.py`: al arrancar, `comprobar` mira contra GitHub
(el `origen` grabado en `METODO.json`) solo el fichero de versión, con un presupuesto
total de 15 segundos; si hay versión nueva pregunta, y con el «sí» consigue la
herramienta solo — tu clon si está limpio y es del mismo origen (`pull --ff-only`), o
una descarga a carpeta temporal si no está o está enferma, sin reparar ni tocar jamás
tu carpeta. Al terminar ofrece actualizar los demás workspaces. Sin red o sin
credenciales: silencio y arranque normal. Revisado en dos rondas (Codex): un clon
enfermo no recibe ni un fetch, y una copia local de otro origen no ejecuta ni una línea.

## 1.5.0 — 2026-08-18

La campaña de las cajas negras: 45 incidentes de campo de 7 workspaces analizados en un
día y lo vivo, arreglado. **Codex vuelve a arrancar** (la CLI actual había retirado un flag
que el lanzador seguía pasando). **Una actividad a medias de entrevista ya no bloquea** el
gobierno de peticiones del workspace entero. **Ningún gate vuelve a dejarte en un
callejón**: las unidades anteriores al sistema de peticiones se cierran con tu OK, un
despliegue de muchas unidades se documenta como lote, un enlace equivocado se cancela con
su motivo, y evaluar un bug pequeño ya no exige contradecirse (tipo y carril en una sola
pasada, con compatibilidad hacia atrás). **El control plane ya no se fía de sí mismo**: el
lease no se roba ante la duda, el constructor no puede tocar su propio contrato (denegación
real del sistema, no una convención) y el recibo distingue "el proceso terminó" de "hay
trabajo acreditado". **Los linters dicen la verdad sobre el CI**: un proyecto que nunca
tuvo el esqueleto recibe un aviso con la deuda nombrada, no un bloqueo eterno; un esqueleto
roto sigue bloqueando. Y el canario del 1.4.0 aprendió que las rutas tienen dos ortografías
(symlinks, nombres cortos de Windows) y encuentra tu sesión con cualquiera de las dos.

## 1.4.0 — 2026-08-18

**Canario de contexto.** Un comando avisa cuando la sesión se está llenando o ya está
repitiéndose, y `canario.py retomada` deja el parte para continuar en una sesión nueva sin
releer nada. En Claude Code, además, el aviso salta solo al auto-compactar. Dos señales con
avisos distintos — capacidad (% de la ventana del modelo, umbral configurable por modelo,
default 80 %) y conducta (el mismo comando fallando repetido: eso ya es degradación) — y
overhead cero: solo lee los ficheros de sesión que el harness ya escribe. Un harness o un
modelo desconocidos degradan a silencio o a incertidumbre declarada, jamás a un arranque
roto ni a un número inventado.

## 1.3.0 — 2026-08-12

Nacida del feedback de campo de la primera semana con usuarios: cuatro quejas reales
(subagentes «esperando una aprobación que no llega», migraciones que se saltan la
adopción o revierten en falso, publicación bloqueada por un rojo del propio método, y
tests interrumpidos sin aviso), una decisión de fondo, y veinticinco escenarios de
regresión que reproducen cada queja y demuestran que ya no ocurre.

- **Guiar, no bloquear (ADR-026).** Cada control del método queda clasificado: gate duro
  SOLO ante daño irreversible (perder trabajo, producción, secretos), siempre con la
  salida escrita en el propio mensaje; todo lo demás avisa y te deja seguir.
- **Un rojo del método ya no te deja tirado.** Si el linter falla, `setup.py` lo enseña y
  el arranque continúa: ¿el fallo es tuyo? se arregla; ¿es del método? se registra en la
  caja negra y se sigue — el arreglo llega con la versión siguiente. Antes ese rojo
  mataba el arranque también cuando la culpa era nuestra.
- **La migración mide antes y después con la misma vara.** El Modo D calcula su línea
  base con el linter NUEVO sobre tu workspace tal como está: un check reescrito o más
  estricto ya no se disfraza de «fallo nuevo» ni revierte una actualización sana. Lo que
  SÍ introduce un fallo de verdad sigue revirtiendo, y ahora te nombra la causa completa.
- **Modo D respeta lo tuyo, también en los detalles.** Tus líneas del `.gitignore` se
  conservan bajo un marcador (antes se machacaban y el árbol quedaba «sucio» para
  siempre); un `git add` tuyo a mitad de actualización la aborta entera en vez de
  absorberse en el commit del método; y un corte de luz entre el stage y el commit ya no
  deja el índice bloqueado con un diagnóstico falso: la siguiente pasada se recupera sola.
- **La adopción brownfield ya no se salta en silencio.** Si tu proyecto nace sobre código
  existente, `ESTADO.md` la nombra como PRIMERA tarea, el bootstrap te manda a ella (no a
  la fase 3), y despachar código sin `ADOPCION.md` avisa en claro — avisa, no encierra.
- **Nada del método mata tu trabajo.** No se borra un worktree con procesos vivos dentro
  (una suite corriendo sobrevive al cierre), sondear una sesión jamás la interrumpe, y
  matar procesos por nombre (`pkill -f`) sigue siendo FAIL del linter.
- **Los cuelgues «esperando una aprobación que no llega» tienen tope.** El hook de
  preparación corre con stdin cerrado, tope de tiempo y grupo de proceso propio (un hijo
  huérfano ya no retiene la tubería); git no puede pedir credenciales en silencio durante
  el arranque; el candado de leases espera con límite también en Mac/Linux (antes, solo
  Windows); el launcher acepta `--tope-minutos`; y el despacho te dice que lo lances en
  segundo plano, porque un shell con tope corto lo mataría a mitad.
- **El manual dice la verdad sobre el Modo D.** El README que viaja con cada workspace
  describía una «auditoría del método» negociada a diff que no existe (y que salía
  carísima en tokens); ahora describe lo que de verdad pasa. Y el paso de enseñar el
  resultado usa `git show --stat`, no el diff entero de ~90 ficheros.

## 1.2.0 — 2026-08-12

- **Windows funciona de punta a punta, y ahora el CI lo exige.** Cerrada la portabilidad:
  el diario del Modo D guarda sin morir (`fchmod`), el registro aguanta la cola de
  procesos, los hooks y gates en shell corren vía bash, el launcher rechaza en claro
  donde no hay sandbox, la salida ya no sale como mojibake, y los finales de línea se
  fijan al nacer el repo (las huellas comparan bytes). El CI de Windows dejó de ser
  informativo: un rojo en Windows bloquea igual que en Linux.
- **Modo D no puede pisar tu trabajo sin commitear.** Si editas un fichero del método
  mientras la actualización se prepara, ahora se detecta y se aborta sin tocar nada, en
  vez de sobrescribir y commitear tu edición (hallazgo de la revisión adversarial).
- **Preguntar ya no cuesta el arranque entero.** Una sesión que solo lee (una duda,
  ver el estado, que te expliquen algo) responde directamente, sin `setup.py`, sin
  linter y sin declarar rol. El arranque completo se hace en cuanto la sesión vaya
  a escribir o ejecutar algo. (Salía en el feedback de campo: el método pesaba
  hasta para mirar.)
- **Cerrar una unidad ya no puede cruzarse con una actualización.** El cierre toma
  sus candados (la unidad y el índice git) igual que ya hacían el despacho y el
  Modo D: si dos sesiones coinciden, la segunda falla nombrando a la primera en
  vez de mezclar escrituras a ciegas.
- **La herramienta trae médico de primer arranque.** `python3 visor/doctor.py`
  recién clonado: comprueba el clone, Python, git, el validador y qué opcionales
  faltan, en cristiano y en un minuto.
- **El visor valida también los proyectos con mapa.** El chequeo E2E moría por
  timeout en cualquier proyecto con actividades (issue #3). Y el modo oscuro del
  visor queda documentado a raíz de la issue #2: botón ☾/☀, persistente.

## 1.1.3 — 2026-08-10

Diez arreglos nacidos de informes de usuarios reales (gracias a quienes los enviasteis)
y del uso de campo. Cada uno lleva su test de regresión.

Remate del 12-ago, antes de publicar la versión: el CI de Windows seguía con 51 tests
en rojo y cayeron todos con sus causas:

- **Guardar en Windows ya no muere a mitad.** El diario del Modo D usaba una llamada
  del sistema que Windows no tiene (`fchmod`); ahora el permiso se fija por la ruta.
- **El registro de proyectos aguanta la cola.** Con varios procesos registrando a la
  vez, el candado de Windows abandonaba a los ~10 segundos; ahora espera su turno.
- **Los hooks y gates escritos en shell funcionan.** Windows no entiende el shebang:
  `worktree-listo` y los scripts del gate de deploy corren vía bash (viene con Git
  for Windows) y, si no hay bash, se dice en claro en vez de morir con WinError 193.
- **El launcher dice la verdad en Windows.** No existe sandbox de SO allí: `lanzar`
  lo rechaza con un mensaje claro en vez de un traceback.
- **Adiós mojibake.** Toda la salida de los scripts viaja en UTF-8 también por PIPE;
  los acentos ya no salen como `Ã©` en el CI ni en ningún harness.

- **Windows funciona de verdad.** Actualizar moría nada más empezar con un error de
  permisos: una operación de guardado que Mac y Linux permiten y Windows prohíbe.
  Ya no se usa donde no existe. (Reportado por dos usuarios; gracias.)
- **Windows ya no ve fantasmas.** Un fichero recién escrito por la propia actualización
  pasaba por "trabajo ajeno" (Windows relee los permisos a su manera) y abortaba el
  proceso. Ya se compara lo que Windows de verdad distingue.
- **Las rutas hablan el mismo idioma en todas partes.** En Windows, la lista de ficheros
  del método y el disco usaban separadores distintos: todo "faltaba" y "sobraba" a la
  vez, y la huella del método no casaba nunca. Normalizado.
- **Actualizar ya no carga con culpas ajenas.** Si tras actualizar la comprobación del
  método sale en rojo, ahora se distingue: lo que ya estaba mal de antes se avisa y la
  actualización se queda; solo si la actualización rompe algo nuevo se echa atrás, y te
  dice exactamente qué rompió.
- **Se te avisa si repartes una versión vieja.** Si tu copia de la herramienta va por
  detrás de su origin, actualizar te lo dice antes de repartir un método caducado.
- **Publicar exige tu OK.** El manual decía "un `git push` y listo"; ahora publicar en
  un remoto pide siempre el OK explícito del dueño, proyecto por proyecto.
- **El trabajo terminado se puede cerrar aunque el PR se titulara corto.** El cierre
  reconoce un squash por su contenido (el árbol del commit), no por el título.
- **Ya no se llama "muerta" a una unidad terminada.** Si la ficha acredita la fusión,
  cero commits por encima de la principal es la foto de después de fusionar, no un
  constructor caído.
- **Un bug evaluado como cambio directo ya se puede crear.** Dos validaciones se
  contradecían entre sí y lo hacían imposible.
- **Las tareas de solo lectura ya no ocupan plaza.** Una auditoría documental aparcada
  ya no bloquea el despacho de constructores (que es lo que la regla 5 siempre dijo).

## 1.1.2 — 2026-08-06

- **El CI que se reparte a tus proyectos ya no fallaba solo. ** La comprobación
  del método exige que git tenga identidad configurada, pero el propio
  workflow de GitHub Actions que este método instala nunca la configuraba:
  cualquier proyecto actualizado a 1.1.1 veía su CI en rojo desde el primer
  `push`. Ahora el workflow configura una identidad de CI antes de lintar.

## 1.1.1 — 2026-08-05

- **Actualizar ya no se bloquea por trabajo a medias.** Si un proyecto tiene
  unidades abiertas, se te avisa con su lista y el método se actualiza igual;
  tu trabajo queda intacto y esas unidades cerrarán ya con las reglas nuevas.
- **Windows funciona.** Poner al día los proyectos ya no falla por `flock`: en
  Windows se usa el candado nativo del sistema. Y comprobar si otra sesión
  sigue viva es seguro también allí (antes, en Windows, esa comprobación podía
  matar el proceso que estaba mirando).

## 1.1.0 — 2026-08-05

Primera versión numerada. Qué trae:

- **El método tiene versión.** Cada proyecto sabe con qué versión se montó, y al
  actualizar se te dice de cuál a cuál pasas.
- **Pruebas más seguras.** Antes de tocar una base de datos o un servicio, los
  agentes comprueban que es el de prueba y no el de verdad.
- **Caja negra completa.** Los tropiezos de los agentes quedan registrados en tu
  proyecto, sin secretos; ahora se pueden listar, revisar y —solo si tú quieres—
  compartir con el autor de la herramienta para mejorarla.
- **Textos alineados.** Las reglas del método que se contradecían entre sí
  quedaron con una sola fuente de verdad.
- **Comprobaciones automáticas.** Los proyectos nacen con una comprobación (CI)
  que vigila el método en cada cambio.
- **Actualizar es más robusto.** Poner al día un proyecto repone las carpetas de
  su estructura que falten y ya no se bloquea por restos inofensivos, como los
  ficheros temporales de Python.
