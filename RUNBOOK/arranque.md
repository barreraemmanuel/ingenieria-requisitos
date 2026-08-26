# RUNBOOK/arranque.md — Modo A y Modo B: del triaje a la entrega

> Módulo de `RUNBOOK.md` (el router). Se lee junto con `RUNBOOK/fases.md` y
> `RUNBOOK/comun.md` cuando el modo es A (construir de cero) o B (código existente).
> Contenido calcado del `RUNBOOK.md` original, sin cambios de fondo (unidad
> 008-modularizar-runbook-tokens).

## Arranque obligatorio: el workspace existe desde el minuto uno

Nada de la entrevista vive suelto en la carpeta de esta herramienta. En
cuanto conozcas o propongas un nombre, crea una carpeta visible
`<nombre>-agents` fuera de aquí:

`python3 RUTA_HERRAMIENTA/visor/iniciar.py --destino <ruta>/<nombre>-agents
--nombre <nombre> --titulo "<título>" --tipo <webapp|automatizacion|agente|otro>`

- Proyecto nuevo: `main/` nace como repo vacío con un README.
- Repo remoto: añade `--remoto <url>`; se clona dentro de `main/`.
- Carpeta local: añade `--carpeta <ruta>`; se COPIA literalmente dentro de
  `main/`. Nunca se mueve ni se modifica el original.

Desde ese instante se trabaja únicamente en
`<nombre>-agents/docs/02-flujos/planos/`. En modo B, analiza `main/` ANTES de
preguntar: ejecuta sus tests si es viable, localiza interfaces, actores,
acciones, estados, reglas y datos, y extrae todos los flujos observables con
referencias concretas. Este análisis describe el presente; no decide el
futuro. Deja además `docs/03-investigacion/ADOPCION.md` con el inventario,
los comandos realmente ejecutados, el estado de la suite y el gap-map
código↔flujos. Su formato NO se inventa: es el que describe el runbook de
adopción que ya viaja dentro del workspace
(`<workspace>/docs/00-metodo/runbooks/adopcion.md`, pasos 1 a 5) — si el
formato no coincide, la sesión siguiente no podrá validarlo y repetirá la
adopción entera. Ese fichero demuestra a la siguiente sesión que la adopción
ya se hizo y evita repetirla.

Regla semántica central: **lo que cuenta el usuario es el diseño futuro** y
son cambios que habrá que implementar aunque difieran del código actual.
Eso no se reinterpreta para coincidir con la implementación. Cada flujo y requisito
lleva `origen`; cada requisito lleva además `implementacion.estado`,
`evidencias` y `pruebas`. Así se distingue “lo queremos” de “ya existe”.

El usuario puede **saltar la entrevista**. Eso no autoriza una entrega
incompleta: el agente propone detalles de forma autónoma, completa TODOS los bloques
y marca cada decisión como `inferido` y cada supuesto como
`propuesto`. La web explica con claridad qué fue dicho, leído del código o
inferido; la aprobación se comunica al agente, nunca se escribe en la web.

En el mismo triaje, identifica también el TIPO de software (no se lo
preguntes con jerga: dedúcelo de lo que cuenta y confírmalo con una frase).
Vocabulario cerrado, decide el bias tecnológico que montará la lanzadera:

- **webapp**: una aplicación donde personas gestionan un negocio o una
  actividad (fichas, estados, permisos). El caso con receta completa.
- **automatizacion**: un proceso que corre solo (informes, pipelines,
  transformar ficheros). La entrevista funciona igual: los "actores" son
  quien dispara y quien recibe; los flujos, el proceso paso a paso.
- **agente**: el producto ES un asistente que conversa o actúa. Entrevista
  igual (qué hace, con qué habla, qué NO puede hacer jamás).
- **otro**: lo demás (plugins, sistemas, móvil nativo…).

Solo `webapp` tiene hoy receta tecnológica completa. Con `automatizacion`,
`agente` y `otro` viaja el bias genérico: la entrevista y la lanzadera sirven
igual, y el stack lo decidirá la fase de investigación con ADR. Sé honesto
con el usuario en los TRES casos, no solo en `otro`: dile que la receta
tecnológica de su tipo aún no existe y que esa decisión se tomará
investigando, no de memoria.


## Aplicaciones grandes: el mapa y las actividades

"Hacer un pedido" es UNA actividad. Una aplicación de verdad tiene entre 12
y 100 (vender, facturar, dar altas, emitir, soportar...). Un solo plano
para todo eso sería una chapuza: el método se aplica a dos escalas, con el
mismo esquema y el mismo visor.

- **El mapa** (el plano general): el `planos.json` raíz de la carpeta del
  proyecto, con la
  visión global: descripción, frase de contrato de la aplicación, actores,
  vocabulario y datos compartidos, integraciones, calidad global, fuera de
  alcance... y el bloque `actividades`: el catálogo COMPLETO agrupado por
  áreas del negocio, cada actividad con una línea de resumen, su estado y
  sus dependencias. El mapa no detalla ninguna actividad: es el índice y el
  panel de control.
- **Cada actividad**: su propia carpeta `actividades/<id>/` dentro de la
  carpeta del proyecto, con su `planos.json` COMPLETO de
  siempre (flujos, reglas, estados, entregas, superficie), hecho con las
  fases F1 a F5 normales, con alcance de UNA actividad.

Cómo se trabaja:

1. **Sesión de mapa** (la primera): volcado global, frase de contrato de la
   aplicación, actores y vocabulario globales, y la cartografía: "cuéntame
   todo lo que PASA en tu negocio, solo el nombre de cada cosa y una
   línea". De ahí salen las actividades en verbo ("hacer un pedido",
   "emitir un certificado"), agrupadas por áreas, con dependencias gordas.
   No entres al detalle de ninguna: si el usuario se mete en una, apunta y
   reconduce ("esa la abrimos en su sesión").
2. **Una sesión por actividad**, en el orden del mapa: método completo
   F1-F5 en su carpeta. Abre cada sesión leyendo el mapa: lo global NO se
   re-pregunta. Si en una actividad aparece algo global nuevo (un actor, un
   término, una entidad, una integración), se añade AL MAPA, no a la
   actividad. Al cerrar su F5, cada actividad baja a SU PROPIO spec file:
   `python3 RUTA_HERRAMIENTA/visor/generar_spec.py --datos CARPETA_PROYECTO/actividades/<id>/planos.json`
   genera `spec.md` y tú escribes `encargo.md`, ambos en su carpeta.
3. **El estado vive en el mapa**: sin empezar → en entrevista →
   especificada → en obra → entregada. Lo actualizas tú al cerrar cada
   sesión o cada entrega. Quien mira el mapa ve el proyecto entero de un
   vistazo.
4. **La obra va actividad a actividad**: cada una genera su spec y su
   encargo; el constructor recibe el mapa (contexto y datos compartidos)
   más la actividad que toca, y NADA más. El esqueleto global de la
   aplicación es la primera tanda: el camino mínimo que cruza la app de
   punta a punta (en una tienda: registrar pedido → cobrar → entregar),
   una actividad fina de cada área imprescindible.
5. **Coherencia**: al cerrar una actividad, comprueba contra el mapa que
   sus actores y su vocabulario existen allí y significan lo mismo.
   `validar.py` funciona igual en el mapa (valida el catálogo y sus
   dependencias) y en cada actividad.

Cuándo NO hace falta mapa: solo si el encargo es UNA única actividad (el
almacén de Paco). En cuanto al cartografiar salga más de una actividad, hay
mapa: así la web enseña siempre el menú lateral y cada actividad tiene su
carpeta y su spec propios.

**La frontera flujo/actividad** (aquí se decide mapa o no, y aquí es donde
más se falla): una actividad es UN verbo con UN resultado que alguien del
negocio reconoce como terminado ("pedido registrado", "pago devuelto",
"reparto entregado"). Los flujos de una actividad son variantes del MISMO
resultado: el de hoy y el del futuro, el mismo verbo por otro canal
(teléfono o WhatsApp), el camino con sus excepciones. Por eso una actividad
sana tiene 2 o 3 flujos —casi siempre `hoy` y `futuro`— y al dibujar el
cuarto toca sospechar (`validar.py` avisa ahí en el perfil de revisión). El
test: dos flujos que terminan en resultados distintos, que los disparan
personas distintas o que pueden pasar el uno sin el otro son DOS
actividades. Antes de decidir actividad única, di la frase "todo esto es
<verbo> y termina en <resultado>"; si no sale en una frase, es un mapa. La
web lo delata: con mapa cada actividad tiene su propia página
(`#<actividad>::resumen`); una actividad única mal trazada apelmaza todos
los flujos en una sola página con anchors, y el usuario ve el índice de su
negocio convertido en scroll. **La norma del método es el mapa**: varias
actividades, cada una con su página, aunque el proyecto sea pequeño — un
mapa de dos actividades es barato y crece solo, y la web es estática igual
(la misma plantilla, rutas de hash; el mapa no cuesta servidor ni HTML de
más). Actividad única es la EXCEPCIÓN, solo para el encargo que pasa el
test de la frase; repartir a mano una actividad única inflada sí que
cuesta.

**El visor en proyectos con mapa**: sirve SIEMPRE el `planos.json` del mapa
(no el de una actividad): la web enseña un menú a la izquierda con el mapa
y todas las actividades, el usuario elige cuál mirar, y los planos de cada
una se sirven solos desde `actividades/<id>/`. Una actividad sin planos
todavía enseña su ficha con cómo arrancarla.

**El mapa como interfaz de mando.** En cualquier momento, con sus palabras,
el usuario puede pedirte:

- "¿Qué actividades hay? ¿Cómo vamos?": lee el `planos.json` del mapa y
  responde con las áreas, cada actividad con su estado, los números (tantas
  entregadas, tantas sin empezar) y qué toca ahora según el orden y las
  dependencias.
- "Quiero iterar / abrir / seguir con [actividad]": localízala en el mapa
  (si el nombre no casa con ninguna, enseña el índice y pregunta cuál era).
  Según su estado: sin empezar → arranca su sesión F1-F5 en
  `actividades/<id>/` y márcala "en entrevista"; especificada, en obra o
  entregada → modo C sobre su `planos.json` (cosechando antes su buzón de
  preguntas del constructor). Levanta el visor de ESA actividad.
- "Añade [tal cosa] al mapa": nueva entrada en el catálogo, con su área,
  su línea de resumen y sus dependencias, estado "sin empezar".

Cada cambio de estado se escribe en el mapa en el momento en que ocurre:
el mapa siempre dice la verdad del proyecto.

**La documentación final.** Al cerrar cada sesión (y siempre que el usuario
pida "dame la documentación"), compila la carpeta de especificaciones:

`python3 RUTA_HERRAMIENTA/visor/compilar.py --mapa CARPETA_PROYECTO/planos.json`

Sobre una carpeta NUEVA deja `CARPETA_PROYECTO/especificaciones/` con dos
piezas: `01-constitution/constitution.md` (lo que vale para toda la
aplicación: propósito, actores, vocabulario, el mapa, datos compartidos,
compromisos y fuera de alcance) y `02-flows/` (un documento por actividad
con planos, agrupados por área), más el índice README.md. Es la
documentación completa y al día de la aplicación, lista para leer,
versionar, entregar, o darle a una cadena de Spec-Driven Development como
el /specify ya hecho. Se regenera entera en cada compilación: no se edita a
mano jamás.

Esa estructura no es la única, y el script no la impone a ciegas: antes de
escribir mira qué hay en la salida. Si es un `docs/02-flujos` ya aplanado
(un `<actividad>.md` por actividad, hermanos del `INDICE.md` — el formato
que deja `finalizar.py` en el workspace), recompila esos `.md` y NO toca ni
el índice ni el manifiesto, que ahí los mantiene el padre del workspace; si
encuentra `01-constitution/`/`02-flows/`, o la carpeta está vacía, usa la
estructura de dos piezas de siempre. Cuando no puede decidirlo (conviven los
dos formatos, o hay documentación que no sale del mapa) **no escribe nada** y
pide que elijas con `--formato plano` o `--formato carpetas`, que mandan
sobre la detección. `finalizar.py` usa ese mismo `--formato plano` para
volcar los documentos al workspace: el formato plano se escribe en un solo
sitio.


## Finalizar el proyecto de trabajo

El workspace ya existe desde el arranque. Al cerrar la definición no se crea
otro ni se mueve el código: se comprueba, se congela y se finaliza el mismo.

Primero exige una entrega completa y márcala como lista:

`python3 RUTA_HERRAMIENTA/visor/requisitos.py listo --workspace <workspace>`

Ese comando valida el perfil de revisión entero y, solo si pasa, pone
`definicion.estado` en "listo para revisar" — es el único camino a ese
estado, porque a mano no se toca y `aprobar` lo exige ya puesto.

Después abre la sesión estable con `visor/requisitos.py abrir` y pide al
usuario que revise todos los flujos del menú lateral izquierdo. La web es
estrictamente de lectura. El usuario comunica comentarios, cambios y
aprobación al agente en la conversación. El agente incorpora cada cambio y
vuelve a validar. Cuando el usuario aprueba, el agente ejecuta
`visor/requisitos.py aprobar --por "NOMBRE" --confirmar-supuestos`, que crea
`aprobacion.json` con identidad, fecha, versión y huella. No cambies
`definicion.estado` a mano.

Comprueba que el recibo sigue vigente con:

`python3 RUTA_HERRAMIENTA/visor/requisitos.py estado --workspace <workspace>`

Finalmente confirma el nombre de repositorio con el usuario y ejecuta
`visor/finalizar.py` sobre ese workspace. La finalización regenera
constitución y flows, conserva `main/` y, si se solicita GitHub, crea
`<nombre>` y `<nombre>-agents` como repositorios independientes.
Dentro de esa operación se vuelve a ejecutar `validar.py --perfil congelado`;
si falla, no se genera ni publica nada.

**`finalizar.py` NO se puede ejecutar sin decidir esto**, y es a propósito: exige
`--github <cuenta>` o `--sin-github`, y sin una de las dos se niega a terminar.
Antes se podía olvidar el flag y el proyecto quedaba finalizado, sin remoto y en
silencio: el usuario se iba creyendo que su trabajo estaba guardado en GitHub
cuando vivía en un único disco, y nada volvía a mencionarlo nunca.

Así que pregúntaselo SIEMPRE, con estas palabras: "¿quieres que tu proyecto
quede guardado en tu cuenta de GitHub, además de en este ordenador?".

- **Si dice que sí**: comprueba `gh auth status` (si no hay sesión, guíale por
  `gh auth login`) y añade `--github <su-cuenta>` — eso crea los DOS repos
  privados (`<nombre>` para el código, `<nombre>-agents` para el meta) y deja en
  `repos.yaml` la dirección del código. Al clonar el meta, `setup.py` clona
  `origin/main` dentro de `main/` o lo actualiza si ya existe.
- **Si dice que no**: `--sin-github`, y dile en cristiano lo que eso significa:
  su proyecto entero —planos, código e historial— existe en un solo disco, y si
  ese disco se rompe no hay copia en ninguna parte. Se puede publicar después
  ejecutando lo mismo con `--github <cuenta>`. Además, el linter del workspace se
  lo recordará en cada arranque de sesión hasta que tenga remoto.
- Si el repo de código ya existía: `--remoto <url>`.

Qué le montas (cuéntaselo así: "te preparo la carpeta del proyecto, con tus
planos dentro y todo lo necesario para que los agentes construyan con
orden"):

- Un **meta-repo** con la documentación viva: su constitución y sus flujos
  (salidos de los planos), el método completo de trabajo por fases
  (`docs/00-metodo/`: runbooks, plantillas, roles y linter) y el sitio de
  las fases siguientes (investigación, planificación, unidades de trabajo).
  **Los planos viajan dentro** (`docs/02-flujos/planos/`): desde ese momento
  esa copia es la canónica — las iteraciones futuras (modo C) parten de
  ella y la carpeta de la entrevista queda como borrador desechable.
- El **repo de código** dentro, en `main/`: clonado si ya existe, o creado
  de cero si no. Dos repositorios: los documentos que juzgan la obra viven
  fuera del alcance de quien construye.
- Git inicializado con su primer commit y el linter del método en verde
  (el bootstrap se niega a entregar un workspace mal formado).
- El workspace queda apuntado en el registro local ignorado por Git. Así una
  versión futura puede localizarlo. `METODO.json` conserva la huella de la
  plantilla, para saber de un vistazo si ese workspace va atrasado; el reparto
  de una versión nueva es el Modo D, en `RUNBOOK/modo-d.md`. Si el registro
  no está disponible, puede rehacerse con
  `python3 visor/proyectos.py registrar RUTA_DEL_WORKSPACE`.

El molde vive en `plantilla/` (léete su README si quieres entender el
método completo). La forma del workspace es SIEMPRE la misma para todos los
proyectos; lo único que cambia es el contenido que salió de la entrevista.

**Si el proyecto era modo B (código existente)**: el análisis brownfield ya
se hizo al principio, antes de la entrevista. Al finalizar debe existir un
gap-map explícito entre diseño y código: implementado, parcial, no
implementado, contradice o no verificado, siempre con evidencia.

A partir de ahí esta herramienta suelta la mano: el trabajo sigue en una
sesión nueva DENTRO del workspace, donde el agente padre se orienta solo
(AGENTS.md + ESTADO.md) y arranca la fase 3 (investigación). Si más adelante
el negocio cambia, se vuelve aquí en modo C con CARPETA_PROYECTO =
`<workspace>/docs/02-flujos/planos/`, se iteran los planos, se recompila y
se re-vuelca al workspace en un cierre.

