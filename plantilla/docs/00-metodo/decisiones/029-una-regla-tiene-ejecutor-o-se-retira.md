# ADR-029 · Una regla del método tiene ejecutor, está declarada inejecutable, o se retira

**Fecha:** 2026-08-22 · **Estado:** aceptada · Unidad 033 · Petición P-20260822-bed4ab44@2

## Contexto

El dueño del método preguntó si tiene sentido cómo se trabaja. El inventario del 22-08-2026
contestó con números, no con impresiones: de 110 reglas escritas, 36 las ejecuta un script,
8 son inejecutables por construcción, 58 no las hace cumplir nadie y 8 son decorativas. De
las 49 puertas que el texto marca como infranqueables, 25 están huérfanas.

El daño no es hipotético; está verificado sobre este workspace y sobre 93 sesiones reales:

- Tres unidades archivadas declaran revisor firmado sin que exista ningún recibo de ejecución
  con rol revisor. La firma era un nombre tecleado a mano.
- Quince entregas se cerraron el 17-08 con la misma fecha de OK del usuario. Una tarde no da
  para probar quince aplicaciones.
- Dos aprobaciones del mapa de negocio se aceptaron sin enseñar el visor, con la regla 14 y
  ADR-007 escritos y vigentes.
- Un trabajo de carril directo declaró cuatro ficheros cuando el límite escrito son tres, y
  el tope de 250 líneas no lo medía ningún script.

El patrón es siempre el mismo: la regla existe, es correcta, y no hay nada que la haga
cumplir. Y lo que la haría cumplir ya está escrito en disco — recibos de ejecución, rastro
del visor, huella de planos, punto de partida de cada rama — sin que nadie lo lea.

Medido aparte, y por eso descartado como motivo: adelgazar la prosa no ahorra nada. El texto
del método que se carga siempre cuesta el 1,2 por ciento del gasto, los documentos nunca
abiertos cuestan cero y todos los runbooks juntos suman el 0,65. La prosa se toca cuando una
regla se retira o una contradicción hay que zanjarla; jamás por coste.

## Decisión

**Toda regla del método está en una de estas tres casillas, y en ninguna otra:**

1. **La ejecuta un script**, y el ADR o el propio texto dice cuál. Una regla ejecutada se
   prueba: si no hay test que demuestre que bloquea, no está ejecutada.
2. **Es inejecutable por construcción, y se declara así con su motivo.** El OK del usuario
   sobre la app corriendo es el ejemplo canónico: ningún programa puede comprobar que una
   persona miró una pantalla. Lo que sí se puede ejecutar es su *forma* — que la fecha exista,
   que sea real, que no esté en el futuro y que no firme un lote entero.
3. **Se retira del método, con el motivo escrito.** Una regla sin ejecutor y sin daño medible
   es texto que se arrastra y que enseña a leer el método como decoración.

**Dejar una regla escrita sin que nadie la ejecute deja de ser aceptable**, porque es
exactamente el estado del que venimos.

**Toda puerta nueva escribe su vía de salida.** Un mensaje de bloqueo nombra el comando que
desbloquea o la vía legítima de salida, detrás de la marca literal `SALIDA:`. Hoy solo 7 de
458 mensajes de bloqueo (el 2 por ciento) lo hacen. Una puerta sin salida escrita es un
defecto del método, no una protección: convierte una regla en un callejón y empuja a saltarla.

## Las cuatro contradicciones vivas, zanjadas

Cuatro reglas afirmaban en prosa algo que el código no hacía. Se zanjan poniéndoles ejecutor
—el texto tenía razón, la implementación no lo respaldaba—, no relajando el texto.

1. **«El revisor es SIEMPRE un agente fresco, distinto de quien construyó» (regla 1, ADR-017).**
   `unidad.py cerrar` solo comprobaba que la cabecera de `hallazgos.md` no estuviera vacía.
   *Zanjada:* el cierre exige un recibo de `.runtime/ejecuciones/` con rol revisor para esa
   unidad, y con identidad de sesión distinta de la del constructor. Mismo modelo con distinta
   identidad avisa y deja cerrar: la regla 10 (modelo distinto) es de calidad, no de
   integridad, y no debe bloquear una entrega correcta.
2. **«Enseña el visor y obtén la aprobación» (regla 14, ADR-007).** `revision.aprobar`
   aceptaba la aprobación sin rastro de que el visor se hubiera abierto.
   *Zanjada:* aprobar exige rastro de sesión del visor posterior al último cambio de los
   planos. `requisitos.py abrir` anota ese rastro también cuando el visor ya estaba activo,
   para que mirar unos planos en una ventana abierta ayer cuente como haberlos visto hoy.
3. **«Directo: 1-3 ficheros, diff < 250 líneas» (regla 9, `runbooks/directo.md`).** Era una
   norma declarada al despachar y nunca comprobada.
   *Zanjada:* el cierre mide el cambio contra el punto de partida de la rama, que ya se
   anotaba, y bloquea si se pasa de ficheros, de líneas o se sale de los declarados.
4. **«Sin el OK del usuario no hay cierre» (regla 7).** El script validaba la forma de la
   fecha, nunca su procedencia, así que una fecha servía para firmar entregas en lote.
   *Zanjada:* una fecha de OK que ya firma tres entregas cerradas no vale para la cuarta sin
   un acta de validación con una fila por unidad.

A las cuatro se les suma la huella de flujo, que no era contradicción sino evidencia sin
leer: `huella_planos_actual()` se calculaba y no se comparaba con la declarada al evaluar.
Ahora se compara, y si el workspace todavía no tiene planos se dice, en vez de callarlo.

## Lo que se retira del texto

Se retira aquello cuya ausencia de ejecutor está medida Y cuyo daño no lo está:

- **La marca `<HARD-GATE>` como señal de puerta infranqueable.** Aparecía 62 veces en 25
  ficheros (este ADR aparte): 56 en 20 documentos del método, cuatro en los scripts —dos de
  ellas para BORRARLA antes de imprimir (`lint_metodo.py`, `peticion.py`), una para
  imprimirla (`unidad.py nueva`) y otra para escribirla en cada plano operativo sin
  entrevistar (`bootstrap.py`)— y dos en fichas de prueba. Ya se descubrió una vez que una
  de esas marcas era prosa que nadie ejecutaba (comentario en `unidad.py`).
  *Motivo de la retirada:* una marca que se estampa a mano y se borra al imprimir no acredita
  nada; lo que hace infranqueable a una puerta es el script que la ejecuta y el test que lo
  demuestra, y ahora esa es la única forma admitida de declararlo. Las puertas siguen; la
  etiqueta se va.

  **Aplicado:** las 62 están fuera. Ninguna frase perdió su fuerza —el texto en negrita que
  la marca acompañaba sigue entero—; las dos únicas reescrituras son las de `README.md` y
  el ADR-015, donde la marca era el sujeto de la frase. Lo comprueba
  `test_r8_la_marca_retirada_no_queda_en_el_texto_del_metodo`, que barre el método y el
  visor y deja este documento como única excepción: quien retira una regla es el único que
  puede seguir nombrándola.

Las otras 54 reglas huérfanas NO se retiran aquí. Se abordan después, ordenadas por daño y
una a una, bajo esta misma doctrina: ejecutor, declaración de inejecutable, o retirada con
motivo. Retirarlas en bloque sería sustituir un método que no se cumple por uno que no dice
nada, y esta unidad quedaría además imposible de revisar.

## Y quién ejecuta ESTE ADR (unidad 073, 27-08-2026)

Esta doctrina tenía el mismo defecto que denuncia: estaba escrita y no la hacía cumplir nadie.
El recuento del 22-08 vivía en una petición, que es un sitio que ningún script lee, así que
nada impedía escribir mañana una regla nueva sin ejecutor y volver al punto de partida.

Su ejecutor es la junta **(d)** de `lint_juntas.py`, con `docs/00-metodo/reglas.json` como
memoria. Cada regla del método —los numerales de `AGENTS.md`, las viñetas de «Reglas de oro»
y las puertas duras marcadas en la prosa— tiene ahí su ancla y su casilla: `ejecutor`
(`script.py:función`), `por_diseno` con el motivo, o ninguna de las dos. Y entonces:

- una regla nueva sin entrada en el inventario es **FAIL**, con su ancla y el comando;
- el número de reglas sin ejecutor está **congelado y solo puede bajar**: si sube, FAIL;
- una función declarada como ejecutor que ya no existe es **FAIL** —arreglada y perdida son
  indistinguibles desde fuera, igual que en la 049 y en la 050—;
- la base la reescribe `lint_juntas.py --congelar-reglas`, con su fecha y su commit. Bajar el
  número a mano en el JSON no cuenta: sin fecha ni commit, la base se rechaza.

Punto de partida honesto del 27-08-2026, medido y no estimado: **31 reglas** inventariadas,
**16 con ejecutor**, **4 declaradas inejecutables** y **11 huérfanas**. Es un trinquete y no
un gate limpio por el mismo motivo que en la 049 y la 050: exigir cero al nacer significa que
el guardián no existe nunca. Las 11 que quedan se atacan una a una por `P-20260822-3c2e49f6`,
y cada una que encuentre dueño baja la base sin que nadie tenga que acordarse.

## Consecuencias aplicadas

- `ejecucion.py` guarda el modelo en el recibo: llegaba por argumento, gobernaba qué modelo
  corría y se perdía, así que al cerrar no había forma de distinguir "otro agente" de "otro
  modelo" — y la regla 10 pide exactamente esa distinción.
- `unidad.py cerrar` lee los recibos del control plane, mide el carril directo contra su base
  de despacho y cuenta las entregas que comparten fecha de OK.
- `peticion.py` compara la huella declarada con la real y publica `huella-planos` para que la
  vía de salida sea teclear un comando, no adivinar una cadena.
- `revision.aprobar` exige el rastro del visor; `requisitos.py abrir` lo deja fechado.
- El recibo del revisor solo acredita la revisión si dice cómo TERMINÓ: `resultado: ok`,
  `exit_code` cero e identidad de sesión. `ejecucion.py` lo escribe al arrancar, así que su
  mera existencia no prueba nada — probaba que alguien lanzó el comando, no que revisara.
- El tamaño del carril directo se mide aunque la rama ya no exista: con la base de despacho
  anotada, la punta fusionada sirve igual. Borrar la rama era la forma de saltarse la puerta.
- Cerrar una unidad antigua cuyo revisor no dejó recibo ahora falla. Es el efecto buscado y
  su salida está escrita: se vuelve a revisar con un agente fresco, y el mensaje da el comando.

## Límites

Esto no toca el coste en tokens, que es el otro eje del encargo y tiene su propia palanca: la
longitud de la sesión, con crecimiento cuadrático y un 35,7 por ciento de ahorro solo por
cortar cada 250 turnos. Va en su propia unidad, porque la medida es distinta.

Tampoco convierte en ejecutable lo que no lo es. Que el usuario haya entendido lo que aprobó
sigue sin poder comprobarse desde un script; lo que sí se comprueba es que la evidencia de
que ocurrió exista, sea suya y no se pueda fabricar tecleando una fecha.
