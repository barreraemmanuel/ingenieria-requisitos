# RUNBOOK/comun.md — planos, visor y conducta (todas las sesiones de entrevista)

> Módulo de `RUNBOOK.md` (el router). Se lee en Modo A, B y C: describe el
> formato de `planos.json`, el visor local que lo enseña y las normas de
> conducta con el usuario.

## Conducta

- Modo Barrio Sésamo, SIEMPRE: habla muy claro y muy masticado, como a un
  amigo que no sabe nada de informática. Ningún mensaje al usuario debe
  necesitar diccionario. Usa los nombres llanos de la web, nunca los
  técnicos del método. Traducciones fijas: "recorrido" se dice "un trozo de
  la app que ya se puede probar"; "esqueleto" se dice "la primera versión,
  que recorre todo el camino aunque sea en fino"; "requisito" se dice "una
  promesa: cuando pase tal cosa, la app hará tal otra"; "criterio de
  aceptación" se dice "la prueba con datos reales para comprobar una
  promesa"; "spec" se dice "el documento con todo lo acordado";
  "superficie de uso" se dice "por dónde se usa la app"; "matriz de
  permisos" se dice "quién puede hacer qué". Si un término técnico es
  inevitable, va seguido de "o sea, ..." con su traducción. Presenta cada
  fase con una frase de andar por casa antes de empezarla ("ahora vamos a
  dibujar cómo funciona tu negocio hoy, paso a paso").
- Una sola pregunta por turno, abierta, en prosa. Nada de formularios ni
  listas de opciones a elegir: las opciones inducen soluciones imaginadas y
  este método pregunta por hechos.
- Cero jerga técnica con el usuario. Ni código, ni arquitectura, ni nombres
  de tecnologías: el cómo pertenece al agente que construya.
- Ningún requisito inferido se hace pasar por dicho por el usuario: si hace
  falta completar sin colaboración, se añade como supuesto `inferido` y
  `propuesto`, visible para aprobación.
- El volcado puede llegar en varios mensajes; no empieces a estructurar hasta
  que el usuario confirme que terminó.
- Cuando propongas un caso límite y el usuario responda "eso no nos pasa
  nunca, fuera", acéptalo y anótalo en fuera de alcance: decidir que un borde
  no importa también es claridad.
- En modo B, el código se analiza antes de entrevistar y se vuelve a
  consultar cuando haga falta contrastar cobertura; nunca se modifica.


## Los ficheros del proyecto (los planos)

REGLA DURA DE UBICACIÓN: la carpeta de este paquete (donde vive este
RUNBOOK.md) es una herramienta compartida y reutilizable. No escribas JAMÁS
dentro de ella: ni proyectos, ni specs, ni notas, ni temporales. Todo lo del
usuario vive FUERA, en su carpeta de trabajo. En los comandos de este
documento, RUTA_HERRAMIENTA es la carpeta del paquete y CARPETA_PROYECTO la
carpeta del proyecto del usuario.

En el triaje deriva o propone un slug corto en kebab-case y crea de inmediato
el workspace con `visor/iniciar.py` en el directorio de trabajo del usuario
(o donde él te diga), nunca dentro del paquete. Los planos son:

- `planos.json`: TODO el proyecto como datos, conforme al esquema
  `visor/esquema.json`: contrato, actores, vocabulario, flujos, recorridos
  con requisitos y criterios, reglas, estados, datos, integraciones,
  superficie, calidad, fuera de alcance y preguntas abiertas. Es la única
  fuente de verdad: la web lo pinta entero y los agentes lo leen como
  estructura maestra.
- `spec.md`: NO se escribe a mano. Se regenera cada vez que cambian los
  planos con:
  `python3 RUTA_HERRAMIENTA/visor/generar_spec.py --datos CARPETA_PROYECTO/planos.json`
- `encargo.md`: el texto para la IA constructora o auditora (ver F5).
- `mural.md`: notas de trabajo en bruto (transcripciones, respuestas,
  ejemplos). Registro interno tuyo: no viaja al agente.

Regla de oro operativa: **al cerrar cada fase, actualiza `planos.json` antes
de seguir**. La web se refresca sola cada pocos segundos: el usuario ve su
proyecto crecer en tiempo real, y esa es parte de la experiencia.


## El visor local (plantilla fija)

Antes de empezar, comprueba que `python3` funciona en esta máquina; si
falta, díselo al usuario e instálalo con su permiso (macOS lo trae de serie;
en Windows, winget o python.org). El visor lo necesita. Los comandos de este
documento se escriben con `python3`, que es el nombre del intérprete en macOS
y Linux (`python` a secas ya no existe en los sistemas modernos). En Windows
el intérprete se llama `py` o `python`: usa ese nombre allí en TODOS los
comandos.

### Windows

Todo funciona en Windows nativo tal cual: la entrevista, los planos, y
también los carriles normal/completo y el revisor (`scripts/ejecucion.py`
no exige ningún sandbox de sistema operativo — ver
`plantilla/docs/00-metodo/sandbox.md`). Si `bash` o el intérprete `python3`
no están disponibles, `visor/doctor.py` lo avisa en el primer arranque
(bash viene con Git for Windows; donde el manual diga `python3`, en Windows
puede llamarse `python`).

Los planos se enseñan SIEMPRE con el visor local de esta carpeta. La página
ya está hecha (`visor/plantilla.html`) y no se genera ni se toca jamás:
misma fuente, mismo fondo, mismos bloques, en cualquier ordenador. Lo único
que se genera con el usuario son datos: `planos.json`.

La plantilla incluye SIEMPRE un menú lateral izquierdo con todos los flujos
navegables. En un mapa enumera sus actividades; en el plano de una actividad
enumera sus flujos. El lateral no desaparece ni se transforma en una barra
superior en pantallas estrechas. Una entrega sin ese lateral es un FALLO y no
se presenta al usuario.

La web tiene pestañas: Resumen (contrato, actores, vocabulario y progreso),
Flujos, Por actor (el corte transversal: qué hace cada uno, por dónde toca
la app, permisos y avisos; se calcula solo desde los datos), Recorridos,
Reglas, Estados, Datos, Superficie, Calidad, Fuera de alcance, Preguntas y
Documentos (el `spec.md` y el `encargo.md` tal cual, en cuanto existen junto
a `planos.json`). Las pestañas aparecen según se rellenan los bloques.

Vocabulario cerrado de pasos en los flujos (el visor no dibuja nada más):

| Tipo (en el JSON) | En pantalla | Significado |
|---|---|---|
| `humano` | redondeado naranja, etiqueta "Persona" | lo hace una persona (con su `quien`) |
| `estatico` | barras dobles azul, etiqueta "Automático · código" | lo hace la app con reglas fijas |
| `ia` | hexágono aqua, etiqueta "Automático · IA" | lo hace la app con un modelo de IA |
| `externo` | redondeado punteado gris, etiqueta "Tercero externo" | lo hace alguien de fuera (el banco, la gestora) |
| `decision` | rombo gris, etiqueta "Regla" o "Excepción" | bifurcación; `quien` opcional = quién la decide |
| inicio/fin | círculos oscuros | los pone el visor solo |

Cada bloque lleva su etiqueta escrita encima: el usuario nunca tiene que
recordar qué significa una forma o un color.

La web es básica y estrictamente de visualización. No incluye formularios,
comentarios, botones de aprobación ni ninguna acción que escriba datos. El
usuario da todo el feedback al agente por conversación; las mutaciones y la
aprobación se hacen únicamente con los comandos locales.

Sobre las decisiones: una decisión lleva `rama` (un desvío) o `ramas` (varias
salidas con contenido); cada rama vuelve al flujo salvo que lleve
`"termina": true` (una anulación, una baja: caminos que acaban ahí). Los
textos van en pasado TAMBIÉN en los flujos futuros ("la app avisó al
almacén"): se validan como episodios imaginados ya ocurridos. Si al usuario
le choca, dile: "lo contamos como si ya hubiera pasado, que es como se
comprueba si es verdad".

Cómo se usa:

1. Escribe o actualiza `CARPETA_PROYECTO/planos.json`. Textos en pasado,
   nombres reales; excepciones y reglas como `decision` con su `rama` o sus
   `ramas` (cada rama vuelve al flujo, salvo que lleve `"termina": true`).
2. Valídalo con la herramienta del paquete tras CADA escritura:
   `python3 RUTA_HERRAMIENTA/visor/validar.py --datos CARPETA_PROYECTO/planos.json`
   Corrige los errores antes de seguir; los avisos señalan fichas cojas,
   avisos sin canal o referencias rotas. Los ids R-n, C-n, G-n, Q-n y REC-n
   son globales al proyecto: el validador rechaza duplicados.
3. Pasa el E2E obligatorio del lateral con navegador real:
   `python3 RUTA_HERRAMIENTA/visor/validar_web.py --datos CARPETA_PROYECTO/planos.json`
   Tiene que terminar con `OK: menú lateral visible y navegable`. Comprueba
   dos anchos de ventana, que el menú esté geométricamente a la izquierda,
   que incluya todas las actividades o flujos y que cada entrada navegue.
   Si falla, el reporte queda RECHAZADO: no des la URL ni pidas aprobación
   hasta corregirlo.
4. Abre la sesión estable y dale la URL al usuario:
   `python3 RUTA_HERRAMIENTA/visor/requisitos.py abrir --workspace <workspace>`
   Sirve sólo en `127.0.0.1`, no caduca por defecto y conserva una URL
   estable para ese workspace. Si ya está corriendo para el mismo proyecto,
   reutiliza la sesión; si el puerto pertenece a otro, elige uno estable
   derivado de la ruta.
5. La página se actualiza sola cuando cambias `planos.json`: no hace falta
   que el usuario recargue.

Los ficheros `visor/ejemplo.json`, `visor/spec.md` y `visor/encargo.md` son
material de muestra del visor, no un proyecto: no los toques.

Plan B sin visor: si el visor o su E2E no pueden ejecutarse (sin navegador,
sesión remota, entorno restringido), el resultado se marca como NO APTO PARA
ENTREGA. Puedes enseñar cada bloque en la conversación para seguir trabajando,
pero no afirmar que la web está terminada ni pedir la aprobación final hasta
que `validar_web.py` pase.

Prohibido: generar HTML propio, editar la plantilla, el esquema o los
scripts del visor, inventar tipos de paso o campos fuera del esquema. La
paleta está validada para daltonismo y la identidad viaja por triple canal
(color, forma y texto). Si algo no cabe en el vocabulario, se simplifica o
se cuenta en texto.
