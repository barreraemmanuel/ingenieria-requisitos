# Ingeniería de requisitos: instrucciones para el agente

Esta carpeta es una HERRAMIENTA, no un proyecto: contiene un método completo
para entrevistar a una persona de negocio y producir los planos (los spec
files) de su aplicación, con una web local para que los valide mirando.

0. **El saludo, literal.** Si el usuario abre sesión sin decir qué quiere
   ("hola", "buenas", o nada), preséntate en una frase y ofrécele ESTAS CINCO
   opciones, con estas palabras y en este orden. No improvises el menú ni te
   dejes ninguna: si una opción no aparece, el usuario no sabe que existe.

   > ¿Qué quieres hacer?
   >
   > - **Construir de cero** — partimos de una idea y te entrevisto hasta tener los planos.
   > - **Auditar código existente** — leo un proyecto ya escrito y extraigo sus planos.
   > - **Iterar unos planos** — ya tienes planos y quieres cambiarlos o ampliarlos.
   > - **Poner al día mis proyectos** — reparto a tus proyectos ya creados las mejoras del método.
   > - **Trabajar sobre la herramienta misma** — tocar el RUNBOOK, el visor o las plantillas.

   Las cuatro primeras son los modos A, B, C y D del RUNBOOK. Si elige poner al
   día sus proyectos, empieza por `python3 visor/actualizar.py buscar` y sigue el
   Modo D (`RUNBOOK/modo-d.md`); si elige cualquier otra, lee `RUNBOOK.md`
   (el router) y el módulo de su modo antes de nada — ver la tabla de
   `RUNBOOK.md` § "Qué leer para cada modo".

1. Ante CUALQUIER petición que involucre un proyecto — una idea nueva, un
   código que YA EXISTE (en GitHub o en una carpeta local), una auditoría,
   o cambios sobre unos planos ya hechos — lee `RUNBOOK.md` (el router) y el
   módulo o módulos de `RUNBOOK/` que tu modo necesita, según su tabla, y
   sigue su triaje de modos (A: de cero, B: código existente, C: iteración).
   "Trabajar en un proyecto existente" es Modo B: jamás clones el repo y lo
   trabajes a pelo saltándote el método. Si lo que trae es mantenimiento de
   los proyectos YA creados ("actualiza mis proyectos", "¿están al día?"),
   es el **Modo D** del RUNBOOK: `visor/actualizar.py revisar --todos`,
   preguntar cuáles quiere y aplicar. Si dudas de
   si algún flujo aplica, la duda se resuelve leyendo `RUNBOOK.md` y su
   tabla de módulos, nunca concluyendo desde este resumen que "ningún flujo
   aplica".
1bis. **Caja negra.** Registra lo raro con
   `python3 plantilla/docs/00-metodo/scripts/caja_negra.py registrar --repo . ...`.
   `.caja-negra/incidentes.jsonl` queda fuera de git y conserva contexto/referencias, no
   conversaciones ni secretos. Su análisis posterior es semántico y lo hace un LLM.
1ter. **Proceso nativo.** Al trabajar sobre esta herramienta no invoques skills externas de
   brainstorming, planificación, debugging, TDD, revisión o cierre: son precisamente el
   proceso que este repositorio define y prueba. Se pueden consultar como antecedentes, pero
   no gobernar la sesión ni crear specs/planes paralelos. Las skills técnicas o de dominio sí
   se permiten cuando no alteran el workspace ni el ciclo local.
2. Regla dura: NO guardes proyectos dentro de esta carpeta. La única escritura
   local permitida es el registro ignorado `.ingenieria-requisitos-local/`.
   Ni proyectos, ni
   specs, ni notas, ni temporales. El proyecto del usuario vive en SU
   carpeta de trabajo, fuera de aquí; si tu sesión está corriendo dentro de
   esta carpeta, pregúntale dónde quiere guardar su proyecto y trabaja allí.
3. Los scripts de la herramienta se invocan con la ruta de ESTA carpeta:
   `visor/servir.py` (la web local), `visor/validar.py` (validación de los
   planos), `visor/generar_spec.py` (el spec de un plano),
   `visor/compilar.py` (la documentación completa de la aplicación),
   `visor/bootstrap.py` (monta el workspace de trabajo completo desde los
   planos: meta-repo + repo de código, con el método de `plantilla/`) y
   `visor/actualizar.py` (Modo D: reparte el método con punto de retorno),
   `visor/migrar_skills.py` (saca del descubrimiento skills locales de proceso sin borrarlas;
   las técnicas solo se conservan mediante `--permitir`) y
   `visor/doctor.py` (primer arranque: ¿funciona la herramienta en esta máquina?).
4. **El tablero de control** (unidad 058) muestra en una sola web qué agentes
   trabajan ahora, qué espera una decisión tuya, qué queda por hacer, qué se
   entregó y toda la documentación del meta-repo. Sólo lee, no escribe nada:
   `python3 visor_tablero/abrir.py --workspace <ruta del meta-repo>`.
