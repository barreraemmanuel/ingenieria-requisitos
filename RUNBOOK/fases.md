# RUNBOOK/fases.md — F0 a F5: la entrevista completa

> Módulo de `RUNBOOK.md` (el router). Se lee junto con `RUNBOOK/arranque.md` y
> `RUNBOOK/comun.md` cuando el modo es A (construir de cero) o B (código existente).
> Sigue las fases en orden; no te saltes ninguna, pero tampoco alargues una fase
> si ya tienes la información (regla del `RUNBOOK.md` original).

## F0: Apertura, volcado y contrato

Abre con el contrato conversacional, en un párrafo: qué vais a hacer (los
planos de su aplicación), qué se espera de él (contar hechos reales y
corregir leyendo, nunca redactar; no prometas ninguna duración: cada negocio
lleva lo que lleva y se puede pausar y retomar cuando quiera) y
qué saldrá al final (una web con sus planos y un encargo listo para la IA
que construya).

Pide el volcado: todo lo que ya sabe sobre lo que quiere, qué problema
resuelve, quién lo usará, cómo funciona hoy el negocio sin la app, y
cualquier idea que tenga. Déjale hablar sin interrumpir ni estructurar.
Cuando termine, pregunta solo: "¿algo más antes de que empecemos a ordenar?"

Puerta de claridad (interna, no se la anuncies): si el volcado contiene un
proceso de negocio reconocible (qué pasa, quién, en qué orden, con qué reglas
aunque sea a grandes rasgos), adelante, y en las fases siguientes pregunta
SOLO por los huecos: nada cuya respuesta ya te dio. Si solo contiene una
solución imaginada (pantallas, "un dashboard") sin proceso detrás, díselo sin
rodeos: "Me has contado la app pero no el negocio. Nárrame cómo funciona hoy,
de principio a fin, la última vez que ocurrió." Si no puede, dile
honestamente que le falta claridad para hacer planos y qué necesita traer; no
intentes descubrirlo por él a base de entrevista. Y recuerda: su claridad
será siempre claridad sobre el camino feliz; las fases F2 a F4 se recorren
SIEMPRE, por claro que lo tenga.

Cierra la fase con la frase de contrato. Propónla rellena y pide que la
corrija:

"Cuando [situación], [quién] necesita [hacer qué] para [resultado medible]."

No sigas hasta que la dé por buena. Si no sabe definir el resultado medible,
ayúdale con preguntas: sin eso no sabréis si la app funcionó. Con la frase
acordada, crea la carpeta del proyecto (fuera del paquete, ver la regla de
ubicación), escribe `planos.json` (version, titulo,
`descripcion` con dos o tres frases en sus palabras sobre qué es el negocio
y qué se construye, contrato, actores) y levanta el visor: que vea sus
planos nacer. Si el usuario da varios resultados medibles, `contrato.exito`
admite una lista: no los comprimas en una frase.

## F1: Cartografía de flujos

Reconstruye TODOS los flujos de trabajo actuales del negocio que toque la
app, contados en manual: como si no hubiera ordenadores, o con las
herramientas que ya usan, sean las que sean (un Excel, un WhatsApp, un SAP,
un Holded, la web del banco, la web de un proveedor, un Google Drive, una
app de terceros). Si una de esas herramientas hace algo sola, ese paso es
`estatico`; si lo hace una empresa de fuera (el banco carga los recibos),
es `externo`.

Todo el mundo con nombre propio: si alguien aparece sin nombre ("un
cliente", "la del mostrador", o el usuario no quiere dar el real),
bautízalo tú con un nombre español normal y corriente, fácil de leer
(Carmen, Andrés, Marta, Jorge, Teresa, Paco) y úsalo SIEMPRE igual en
actores, diagramas, ejemplos y pruebas. Avísale de que es inventado y que
puede cambiarlo. Un "Cliente 1" no cuenta historias; una "Carmen" sí. Varios flujos y varios actores; cada
flujo es una línea temporal de hechos en pasado con los nombres reales que
use el usuario, y las excepciones y reglas pegadas al paso donde ocurren, no
en lista aparte.

Vuelca cada flujo a `planos.json` con `momento` "hoy": el usuario los ve
aparecer en la pestaña Flujos. Para una persona no técnica el gráfico es el
formato principal de validación; `mural.md` es tu registro en texto.

Pide que los corrija: pasos que faltan, orden equivocado, excepciones que no
están, personas que intervienen y no aparecen, flujos enteros que se te
escapan ("¿hay algún otro trabajo que pase alrededor de esto?") y los que
miran sin aparecer ("¿quién más toca o revisa esto aunque no salga en el
flujo? ¿el gestor, tu socio, soporte, Hacienda?"). Si detectas un hueco
lógico (algo pasa pero nadie lo hace, un paso sin desencadenante), señálalo.
Itera hasta que diga que así es como pasa de verdad, en todos.

En estos flujos de hoy casi todo será `humano`; `estatico` solo si su sistema
actual hace algo solo; `ia` no debería aparecer todavía.

El flujo de hoy es ANDAMIO, no entregable: se valida UNA vez ("¿así pasa de
verdad?") y queda archivado como contexto. Desde el reparto (F3) en
adelante, las correcciones van SOLO al flujo con la app; en el visor, el de
hoy queda plegado bajo "ver cómo funciona hoy". Y si la actividad no existe
hoy (nace con la app), sáltate su flujo de hoy sin culpa y anótalo en el
mural: "no hay proceso actual".

## F2: Interrogatorio de huecos

Recorre los flujos validados y pregunta, y pregunta, y pregunta: una sola
cuestión por turno, siempre apuntando a un agujero concreto. Normas:

- Pregunta por episodios reales: "cuéntame la última vez que [paso] salió
  mal", "¿qué pasó la última vez que dos clientes pidieron lo mismo a la
  vez?". Nunca "¿qué función quieres?" ni "¿te gustaría que...?".
- Si responde con un deseo ("estaría bien que..."), pídele el hecho que hay
  detrás.

Red de seguridad: comprueba que el material ya cubre estos puntos y pregunta
SOLO los que falten, de uno en uno:

1. **Excepciones**: qué pasa cuando el cliente no paga, el dato no llega,
   alguien se equivoca.
2. **Concurrencia**: y si dos personas tocan lo mismo a la vez.
3. **Estados**: en qué situaciones puede estar cada cosa importante (un
   pedido, un cliente, una reserva) y, en cada una, qué se puede hacer,
   quién, y a qué situación pasa después (campo `pasa_a`): sin destino no
   hay máquina, hay una lista.
4. **Primer día**: cómo se ve todo vacío, sin datos, con el primer usuario.
5. **Volumen**: cuántos usuarios, cuántos registros, con qué frecuencia.
6. **Fuera de alcance**: qué NO hará esto, aunque parezca que debería.
7. **Éxito**: qué número miraremos en un mes para saber que funcionó.
8. **Plazos y esperas**: cuando alguien tiene que responder (aprobar,
   confirmar, pagar), ¿y si no contesta en todo el día? ¿Cuánto se espera,
   a quién se avisa, qué pasa mientras tanto?
9. **Identidad donde hay dinero**: si un canal mueve pedidos o pagos
   (WhatsApp, correo), ¿cómo se sabe que quien escribe es quien dice ser?
   ¿Qué pasó la última vez que escribió un número desconocido?

En cada punto caliente (reglas, excepciones, dinero), exige ejemplos con
datos de verdad: 2 normales y 1 raro, con nombres y números reales. No
aceptes "un cliente hace un pedido"; exige "Paco pide 40 sacos y debe 300€".
Si el nombre real no existe o no lo quiere dar, usa el nombre inventado
estable de ese actor: lo que no puede quedar es un ejemplo sin nombre.
Si aparece una regla con 3 o más condiciones combinadas, conviértela en una
tabla de decisión y métela en el bloque `reglas` de los planos para que la
corrija viéndola en la web.

Trucos de esta fase, que es la más larga:

- Cada 4 o 5 preguntas, un mini resumen de avance ("llevamos excepciones y
  concurrencia; faltan estados y volumen"): sin él la fase se siente
  interrogatorio.
- Para estados no preguntes en abstracto ("¿en qué situaciones puede estar
  un pedido?"): pregunta "¿a quién tienes ahora mismo a medias o sin servir,
  y por qué?".
- Los episodios con nombres y números van al bloque `episodios` de
  `planos.json`, con `refs` a los ids que alimentan: son la munición de los
  tests y deben viajar al constructor, no morir en `mural.md`.
- Los números de escala van al bloque `volumen`.

Lo que salga aquí va cayendo en `planos.json`: reglas, estados, episodios,
volumen, fuera de alcance, y el éxito a `contrato.exito` (lista si son
varios).

## F3: Materia prima y reparto

Primero la materia prima, preguntando solo lo que falte:

- **Formatos y archivos predeterminados**: qué plantillas, Excels, PDFs,
  facturas tipo, correos tipo existen ya y deben respetarse o producirse.
- **Sistemas actuales**: qué usa hoy el negocio y qué pasa con ello; puede
  ser cualquier cosa: un Excel, un SAP, un Holded, un Google Drive, la web
  del banco, la app de un proveedor. Para cada uno: ¿se migra, se importa,
  se sigue usando al lado, o se jubila? De dónde viene cada dato (bloque
  `datos`).
- **Integraciones**: con qué tiene que seguir hablando esto (bloque
  `integraciones`): el programa de facturación o el ERP (Holded, SAP), el
  banco, el calendario, WhatsApp, la web del proveedor... Y para cada una,
  el CÓMO de verdad: ¿WhatsApp es la API de empresa con sus plantillas y su
  número, o un enlace que abre el chat? ¿El banco es un fichero que se sube
  a su web, y con qué formato? Si el usuario no lo sabe, entrada obligatoria
  en `preguntas` ("mecanismo de X sin decidir"): que quede como hueco
  visible, nunca como invento del constructor.
- **Obligaciones**: qué debe cumplir por ley o contrato: facturas legales,
  datos personales de clientes, lo que exija el gestor (al bloque `calidad`).

Cuando exista el documento real (la factura de verdad, el Excel real), pide
verlo: un documento real es la mejor especificación de sí mismo y destapa
reglas que nadie cuenta. Si no puede o no quiere enseñarlo, no insistas:
anota en `preguntas` "pendiente ver el [documento] real" y sigue; esa deuda
viaja al constructor.

Después el reparto: el mismo proceso, con cada paso tipado según quién lo
ejecutará cuando exista la app:

- `humano`: lo que exige juicio o responsabilidad de una persona, y lo que el
  usuario quiera seguir haciendo él.
- `estatico`: reglas fijas, cálculos, registros, avisos.
- `ia`: interpretar texto libre, clasificar, resumir, redactar borradores.

OJO con la `ia`: lo más probable es que la aplicación no la necesite EN
NINGÚN SITIO, y mejor así. Un paso `ia` cuesta dinero cada vez que corre,
puede equivocarse y exige revisión humana. Cuestiónalo SIEMPRE antes de
proponerlo: ¿un formulario, un desplegable o una regla fija lo resuelve?
(que el cliente elija el producto de una lista mata a "la IA que interpreta
el mensaje"). Solo queda `ia` cuando la entrada es inevitablemente libre
(texto, audio, foto) y estructurarla costaría más que revisarla. Cero pasos
`ia` es un resultado excelente, no un fracaso del método.

Aquí propones tú primero, porque la automatización es tu terreno; la última
palabra es del usuario. Añade los flujos futuros a `planos.json` (`momento`
"futuro") y pide correcciones con el flujo de hoy delante. "Esto lo quiero
seguir haciendo yo" es una respuesta válida y se respeta tal cual. No nombres
tecnologías: `ia` o `estatico` es todo el detalle técnico que el diagrama
admite. Y patrulla un borde: si un paso `ia` decide algo con dinero o
clientes y nadie lo revisa después, señálalo como riesgo antes de darlo por
bueno.

## F4: Superficie de uso

Baja a tierra por dónde se toca la aplicación. Súper estándar y súper
rígido: una ficha fija por cada punto de entrada, siempre con los mismos
campos, en lenguaje del usuario. Un punto de entrada es cada sitio por donde
alguien entra en contacto con la app (un panel, un formulario, un WhatsApp,
un correo que llega, un enlace).

Ficha (los 7 campos, siempre todos): nombre en palabras del usuario ("el
panel de María"); quién entra; por dónde llega (móvil, ordenador, WhatsApp,
correo); cuándo lo usa (qué momento del flujo lo dispara); qué ve nada más
entrar (en puntos que no son pantallas, "qué recibe"); qué puede hacer
(verbo + objeto); y qué NO debe poder hacer ni ver jamás (piensa en el
empleado enfadado su último día). En un punto de SOLO RECEPCIÓN (un correo
que llega, un fichero que cae en una carpeta) "qué puede hacer" se declara
vacío a propósito (`"puede": []`): decidir que ahí no se hace nada también
es una respuesta, y así la ficha no queda coja ni inventa acciones para la
matriz.

Con varios puntos de entrada no hagas 7 preguntas por ficha: propón la ficha
entera rellena con lo que ya sabes y pide que la corrija, igual que con la
frase de contrato. Si un permiso tiene matiz ("puede dar citas, pero solo
por la tarde"), desdobla la acción en la matriz o recógelo en el campo
"nunca"; la matriz es sí/no a propósito.

Canales, siempre explícitos: cada punto de entrada dice por dónde llega (UI
web, app del móvil, WhatsApp, SMS, correo, llamada de voz, un fichero en una
carpeta, papel impreso) y cada aviso dice por dónde sale. Pregunta también
por la vuelta: cómo prefiere comunicar el negocio hacia fuera (¿al cliente
se le contesta por WhatsApp? ¿al gestor se le deja un Excel en una
carpeta?). Y en los flujos futuros, los pasos de aviso nombran su canal en
el propio texto: "Se avisó al almacén por WhatsApp", no "se notificó".

Cierra la fase con tres piezas transversales, validadas mirando la web:

- **Matriz de permisos**: roles por acciones, sí/no.
- **Avisos**: quién tiene que enterarse de qué, por dónde y cuándo.
- **Condiciones de uso**: la calidad contada en negocio, sin jerga. Cinco
  preguntas: cuánta espera es tolerable y dónde, qué pasa si se cae medio
  día, qué datos son delicados y quién no debe verlos jamás, desde qué
  aparatos y en qué condiciones se usa, y si alguien que lo usará tiene
  alguna dificultad (vista, idioma, poca soltura). Estas condiciones son el
  relato; su versión comprobable serán los Q-n de F5, y si divergen manda
  el Q-n.

Si la aplicación tiene usuarios, no mezcles cuatro cosas distintas: la **persona** es el
nombre concreto que protagoniza los ejemplos; el **rol** es su función estable en el negocio;
el **grupo u organización** marca a qué conjunto pertenece; y el **alcance** dice si actúa
sobre lo propio, lo asignado, su organización o todo. Los permisos base se conceden a roles o
grupos, nunca a una persona concreta salvo que exista una política excepcional y una decisión
explícita. Propiedad, organización, estado del usuario o del recurso y separación de funciones
son restricciones aparte: no se fuerzan dentro del nombre de un rol. En los planos, cada actor
que vaya a autenticarse declara `actor.rol` y, cuando apliquen, `actor.organizacion`,
`actor.grupos` y `actor.estado`; la persona sigue siendo su nombre narrativo estable. La
concesión base vive en `superficie.permisos.roles` o `superficie.permisos.grupos`. Cada
restricción identifica exactamente un `rol` o un `grupo`, nunca una persona.

La identidad estructurada vive en `actores`; los puntos de entrada, matrices y restricciones
viven en `superficie`. No diseñes pantallas ni menús: la superficie dice quién, por dónde,
qué puede y qué no; el aspecto es de la obra.

## F5: Los planos completos

Cuando no queden huecos:

1. Completa `planos.json`: los recorridos (bloque `recorridos`) con sus
   requisitos en EARS (ids R-n) y sus criterios de aceptación con los datos
   reales de la fase 2 (Dado/Cuando/Entonces, ids C-n); la calidad como
   criterios comprobables (ids Q-n) traducidos de las condiciones de uso; y
   el orden: el primer recorrido es siempre el esqueleto que recorre el
   flujo entero por el camino feliz. Para ordenar el resto pregunta una sola
   cosa: "si mañana solo existiera un trozo, ¿cuál te quita más trabajo?";
   él ordena por valor, tú ajustas por dependencias.

   EARS completo, no solo el patrón de evento: "Cuando [disparador], el
   sistema deberá..." (evento); "Mientras [estado], el sistema deberá..."
   (estado); "Si [fallo o situación no deseada], entonces el sistema
   deberá..." (protección); "El sistema deberá siempre..." (invariante).
   Los requisitos de estado y de fallo son requisitos con su R-n, no notas
   de calidad.

   Rellena la trazabilidad SIEMPRE: cada requisito que implementa una regla
   lleva su campo `regla` (G-n) y cada criterio lleva `cubre` (el R-n que
   prueba). No es burocracia: es lo que permite detectar reglas huérfanas y
   promesas sin prueba.

   En aplicaciones con usuarios, convierte cada `nunca` y cada restricción crítica de
   propiedad, organización, estado o separación de funciones en un R-n y un C-n que demuestren
   una denegación real. Después selecciona en `pruebas_e2e` solo un camino feliz por rol
   interactivo y una denegación por cada frontera crítica distinta. La matriz completa se
   probará en una capa rápida: no multipliques navegador por (rol o grupo) × acción ×
   recurso. Los planos solo llevan personas, roles, criterios y fronteras; nunca correos de acceso,
   contraseñas, tokens ni nombres de herramientas de test.

2. Pasa el cierre de coherencia con
   `validar.py --perfil revision`, el E2E obligatorio
   `validar_web.py` y la revisión humana, y arregla lo que salga ANTES de
   enseñar nada:
   - Toda regla G-n tiene al menos un requisito que la implementa y toda
     fila de sus tablas al menos un criterio con datos reales.
   - Todo requisito R-n tiene al menos una prueba C-n que lo cubre.
   - Todo paso `ia` tiene al menos un requisito de fallo ("Si el modelo no
     entiende o el remitente es desconocido, entonces...") con su criterio.
   - Toda acción de las fichas de superficie está en la tabla de permisos,
     y al revés.
   - Todo estado es alcanzable y tiene salida (o es final a propósito), con
     quién y `pasa_a` en cada acción.
   - Todo dato que usan los requisitos existe en el bloque `datos` (si un
     requisito manda un correo, el cliente guarda un correo).
   - Cada número de `contrato.exito` se puede medir con los datos que la
     app guarda: si no, añade el requisito y los campos que lo midan.

   Las preguntas que el usuario NO sabe responder (un mecanismo sin decidir,
   un documento pendiente de ver) no bloquean la entrega: se quedan en
   `preguntas`, la web las enseña en "Sin decidir" y viajan al constructor
   dentro del spec como deuda visible. El validador avisa de ellas y solo
   bloquea con más de 3: a partir de ahí ya no es deuda, es una entrevista
   sin terminar — responde las que el usuario sí sepa o conviértelas en
   supuestos propuestos.

   De esta lista, `validar.py --perfil revision` respalda como ERROR la
   trazabilidad (reglas huérfanas, requisitos sin prueba), la protección de
   todo paso `ia` y la doble dirección fichas↔matriz, y avisa de estados
   inalcanzables. Lo demás (filas de tabla con criterio y datos reales,
   datos que existan en `datos`, éxito medible) sigue siendo TUYO: el OK del
   validador no te exime de repasar la lista entera.
3. Genera el spec:
   `python3 RUTA_HERRAMIENTA/visor/generar_spec.py --datos CARPETA_PROYECTO/planos.json`
4. Escribe `encargo.md` según el modo (abajo): el texto del encargo y,
   debajo, la ruta de la carpeta de planos. Nada más.
5. Marca la entrega como lista con
   `python3 RUTA_HERRAMIENTA/visor/requisitos.py listo --workspace <workspace>`
   (valida revisión y pone "listo para revisar"; el estado no se escribe a
   mano). Después pide al usuario que recorra TODAS las pestañas de la web
   buscando mentiras y huecos, y señálale las 3 partes donde tengas menos
   confianza de haberle entendido bien, para que las revise primero.
6. El usuario aprueba esa versión diciéndoselo al agente. Registra la
   aprobación con `requisitos.py aprobar --por "NOMBRE"
   --confirmar-supuestos`; no escribas `aprobado` a mano. Comprueba
   `requisitos.py estado` y finaliza con `visor/finalizar.py`, que rechazará
   cualquier plano distinto del recibo.
7. Solo cuando `finalizar.py` ha terminado en verde (te imprime la ruta del
   `<proyecto>-agents` creado), dile qué hacer después: cerrar esta sesión y
   abrir una nueva desde la raíz `<proyecto>-agents`. El agente padre leerá
   `AGENTS.md`, `ESTADO.md`, los planos y el encargo; no se abre directamente
   dentro de `main/`. Y que la validación final es usar la obra con los
   ejemplos de los planos ("haz el pedido de Paco con la deuda de 300€"), no
   mirar pantallas. Si `requisitos.py aprobar` o `finalizar.py` se bloquean
   (el visor no abre, el E2E sale en rojo, los planos no coinciden con el
   recibo), NO le mandes cerrar nada: dile qué está bloqueado, con el mensaje
   literal, y cómo desbloquearlo; el relevo llega cuando el paso 6 esté en
   verde (bug 116).

Encargo modo A, construcción:

> Este workspace contiene los planos aprobados en `docs/02-flujos/planos/`.
> Lee `AGENTS.md` y `docs/05-trabajo/ESTADO.md` y continúa por la primera fase
> pendiente. No programes todavía: primero completa investigación y después
> acuerda la planificación con la persona. Cada trozo de obra tendrá su propia
> especificación aprobada, rama y worktree. Si algo de negocio no está definido,
> registra la pregunta para que el analista actualice los planos; el constructor
> nunca los modifica. La última prueba es la aplicación real usada por la persona
> con los ejemplos Dado/Cuando/Entonces.

Encargo modo B, auditoría (rellena la ruta: pregúntala al usuario al cerrar,
que pedir la ruta del código no es mirar el código):

> El código a auditar vive en [RUTA]. Audítalo contra estos planos:
> `spec.md` y `planos.json`. No
> asumas que el código es correcto ni que los planos son completos.
> Reconstruye el proceso que el código implementa en el mismo formato de
> flujos de `planos.json` y busca tres cosas: lo que los planos exigen y el
> código no hace, lo que el código hace y los planos no piden, y lo que
> ambos cubren con reglas distintas. Ejecuta los criterios
> Dado/Cuando/Entonces contra el código real siempre que puedas. Cada
> desviación se reporta en `desviaciones.md` (junto a los planos) con el
> ejemplo concreto que la
> demuestra, en lenguaje de negocio, citando el identificador (R-n, C-n,
> Q-n) incumplido. No arregles nada sin encargo aparte.
