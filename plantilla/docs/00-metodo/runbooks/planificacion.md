# Runbook · PLANIFICACIÓN (fase 4 — el padre, debatiendo con el usuario)

**Cuándo:** al terminar la fase 3 (síntesis escrita); después se alimenta en cada cierre,
nunca se re-hace entera.
**Entrada:** solo peticiones ya evaluadas por `runbooks/peticiones.md`; la cola no decide
prioridad ni sustituye las dependencias del ROADMAP.
**Produce:** `04-planificacion/ROADMAP.md` (plantilla `roadmap.md`).
**Contrato de cierre:** cada decisión debatida y aprobada por el usuario + plan de
construcción con el esqueleto andante primero.

## Paso a paso

1. **Cargar y corroborar TODO:** la constitución, TODOS los flujos, TODOS los informes de
   `03-investigacion/`, la `SINTESIS.md` y lo ya aprendido (`docs/decisiones/` y
   `docs/conocimiento/`). Se leen uno a uno; nada se planifica sin haberlos leído. Si algo se
   contradice entre ellos → se resuelve con el usuario antes de seguir.
   (**Los informes y la `SINTESIS.md` los produce la fase 3**, `runbooks/investigacion.md`; aún
   no existen: si faltan, correr la fase 3 es el paso previo y esta fase no arranca. En
   brownfield la fase 3 va acotada — `runbooks/adopcion.md` §6 — pero va.)
2. **Preparar las decisiones.** **Antes de proponer tecnología, mirar la
   máquina:** `python3 docs/00-metodo/scripts/doctor.py --escribir`. **El ROADMAP no fija una
   herramienta que el doctor no haya visto en verde** — si no hay Docker, el plan no dice
   "se desarrolla con contenedores"; si no hay `gh`, el cierre va por el camino B de
   `runbooks/cierre.md` y eso se escribe AQUÍ, no se descubre en el paso del pull request.
   Por cada decisión a tomar (lenguaje, framework, librerías,
   integraciones, dónde corre): una opción recomendada y sus alternativas, con pros y
   contras EN CRISTIANO — cero jerga técnica; si un término técnico es inevitable, se
   explica en una frase. Entre las decisiones SIEMPRE está el **entorno de ejecución y
   testing local**, y esa se decide PREGUNTANDO al usuario antes de mirar el código, con
   estas palabras: **«¿esto lo va a usar más gente a la vez, o lo corres tú en tu máquina?»**
   y **«¿la máquina donde corre es la que ya usas?»**.
   - Si lo corre él en su máquina: **por defecto, lo mínimo que arranque** — entorno nativo
     (venv o equivalente) y los servicios que esa máquina YA tenga instalados.
   - Docker/compose se PROPONE, con su porqué escrito, cuando lo vaya a usar más de una
     persona a la vez, cuando corra en una máquina que no es la suya, o cuando el usuario
     pida aislamiento.

   Que el código nombre varios servicios (BD, colas, índices) no decide por sí solo: un
   Postgres ya instalado en esa máquina vale igual. **La complejidad de manejo no es argumento
   ni a favor ni en contra: los comandos los ejecuta un agente y al usuario no le llegan.** Lo
   que sí le llega es lo que queda encendido en su máquina cuando el agente se va, y eso es lo
   que se pesa.

   **Antes de proponer NADA, mirar qué ya existe.** Buscar en el código
   (`main/`) si YA hay un módulo o componente que haga eso o algo parecido: **no se duplica
   código ni responsabilidades**. Si lo hay, la funcionalidad se encaja ahí (refactorizando
   ese módulo si hace falta), JAMÁS levantando un sistema paralelo; solo se propone módulo
   nuevo cuando ninguno existente es su sitio, y se dice a qué capa pertenece. Lo encontrado
   —módulos que se tocan y por qué no se duplica— se escribe en el ROADMAP.

   **Si la decisión toca dónde corre esto para OTROS**, se hace primero la pregunta de
   `runbooks/primer-despliegue.md` §1 —«¿quién tiene que poder usar esto?»— y su respuesta se
   anota en el ROADMAP. Es la misma pregunta y con las mismas palabras: no se reformula en
   jerga, no se deduce del código y no la contesta el agente por él.

   **Las reglas de diseño están escritas UNA vez en `01-constitucion/bias.md`** («Cómo se diseña
   el código», ADR-015) y valen siempre. Aquí se APLICAN al trocear; no se repiten, no se
   re-argumentan y **ninguna unidad las vuelve a discutir en su fase 5**: una spec que debate
   arquitectura ha dejado de ser un contrato.
3. **Debatir con el usuario, ping-pong.** Las decisiones se presentan DE UNA EN UNA:
   "he encontrado esta tecnología, tiene estos pros, estos contras, se haría así".
   El usuario pregunta, el padre responde, y el usuario decide. Nada queda
   decidido sin su OK. Una decisión gorda (contradice el bias, elimina algo) → ADR.
4. **Escribir el ROADMAP** con la estructura FIJA de la plantilla, siempre igual:
   ① resumen al principio (qué se construye y con qué, para leer en 30 segundos) ·
   ② los motivos de cada decisión (por qué sí, por qué no las otras) ·
   ③ tabla comparativa al final de las decisiones ·
   ④ plan de construcción: esqueleto andante primero (la cadena mínima que atraviesa el
   sistema punta a punta), los **módulos existentes que se tocan y por qué no se duplica**
   (paso 2), y la tanda actual troceada en unidades con orden y dependencias.
   Cada unidad reparte sus pruebas en la tabla de `plantillas/especificacion.md`: regla o
   matriz exhaustiva de roles/grupos → unitario; entrada protegida real → integración;
   recorrido completo o frontera que solo aparece al cablear la app → end-to-end. Los planos deciden qué conducta
   importa; el stack ya investigado decide cómo demostrarla (ADR-019).
5. **El usuario aprueba el documento final.** Actualizar `ESTADO.md` →
   fase 5: especificar y despachar la primera unidad de la tanda (runbook de su tipo).

## El bias de la planificación (fijo; se aplica a TODA decisión)

- **Quien decide no es técnico** y no tiene background fuerte de programación → todo se le
  explica en cristiano. PERO la elección técnica NO se rebaja por eso: la terminal y la
  implementación compleja las hace un agente, así que la dificultad de instalación no es
  argumento. PROHIBIDO proponer un SaaS o un ecosistema cerrado "porque es más fácil para
  un no técnico" (ejemplo: PostgreSQL sí; Supabase no).
- **Cero overengineering:** lo más sencillo que cumpla, rápido de implementar y que aguante
  en el tiempo.
- **Sin SaaS. Tecnología libre y ecosistemas abiertos SIEMPRE** (máximas libertades).
- **Destino por defecto: un VPS propio o una máquina de la red del usuario** (self-hosted
  siempre, nunca nube ajena). Puede quedarse en su máquina local si con eso le vale: quién
  tiene que poder usarlo lo dice él (`runbooks/primer-despliegue.md` §1), no lo supone el
  método. Lo que no se hace es dar por hecho que hace falta un servidor.

## Reglas fijas

1. **Barrio Sésamo:** todo el documento entendible por alguien sin jerga técnica. Resumen
   SIEMPRE al principio; explicaciones mínimas; comparativa en tabla.
2. **El ROADMAP no asigna NNN.** El número se asigna al DESPACHAR (fase 5, desde main).
   Al abrir la unidad, su fila apunta al `NNN-slug`; al cerrarla, pasa a "Entregado".
3. **Solo el padre lo escribe, en fronteras:** cada cierre añade el trabajo descubierto y
   los hallazgos de auditoría aceptados; reordenar exige OK del usuario.
4. **Planificar poco y cerca:** detalle solo para la tanda actual; lo lejano, una línea.
5. **No duplica estado:** el estado vivo está en `ESTADO.md` y en los frontmatters.
6. **La primera unidad materializa el entorno Y sus guardianes.** Copia
   `plantillas/agents-repo-codigo.md` a `main/AGENTS.md` con comandos probados y crea, para el
   stack ya decidido: `scripts/ci/full-suite`, `scripts/ci/lint`, `scripts/ci/security`, los
   workflows `.github/workflows/tests.yml` y `quality-security.yml`, y el
   `.github/dependabot.yml` del gestor real. Un repositorio vacío no trae CI de mentira: esta
   unidad lo estrena y antes de pedir merge ejecuta
   `python3 docs/00-metodo/scripts/lint_ci.py --repo worktrees/NNN-slug`. Sin esas piezas no
   hay primer merge. Las Actions externas van por SHA; vulnerabilidad = rojo, versión nueva
   sin vulnerabilidad = propuesta de Dependabot (ADR-018).
   Si los planos declaran `pruebas_e2e`, ESA MISMA primera unidad de código y CI incluye el
   mínimo vertical de autenticación y el harness E2E. En greenfield materializa la
   autenticación mínima que necesitan los recorridos; en brownfield adopta la autenticación
   existente y sus comandos sin reescribirla. En ambos crea `scripts/ci/provision-e2e` y
   `scripts/ci/e2e` y deja una sola cadena ejecutable: `full-suite` llama a `e2e`; `e2e` llama
   primero a `provision-e2e` y después ejecuta los tests. No se pospone a otra unidad porque la
   puerta del primer merge ya lo exige. El provisionador usa identidades y datos sintéticos,
   deterministas por alias de persona/rol, es idempotente y rechaza producción. Las
   credenciales nacen por ejecución, fuera de git y logs. Sin selección E2E o sin stack
   decidido no se inventan usuarios, framework ni scripts (ADR-019).
