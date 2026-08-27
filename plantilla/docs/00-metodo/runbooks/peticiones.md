# Runbook · PETICIONES (entrada única antes de elegir ruta)

**Cuándo:** el usuario pide, corrige o acepta algo que puede producir trabajo. Una pregunta,
una conversación exploratoria y una observación sin encargo no se capturan.
**Produce:** `docs/05-trabajo/peticiones/P-ID/peticion.json`, que conserva sus palabras, la
evaluación y los procesos que terminan satisfaciéndola.
**No sustituye:** flujos, ROADMAP, unidades, bugs, auditorías, despliegues ni exprés. Los
enlaza. La cola decide qué se pidió; cada proceso conserva su contrato de cierre.

## Secuencia

1. **Decidir si es accionable.** Si existe una acción que el agente debería realizar ahora o
   después, se captura. Si solo se está explicando contexto, se sigue escuchando.
2. **Primera escritura.** Antes de investigar, diseñar o crear una tarea:

   `python3 docs/00-metodo/scripts/peticion.py capturar --resumen "…" --texto "palabras del usuario" --autor "…"`

   Esto no interrumpe la unidad en vuelo. La petición queda visible en cola; prioridad y P0
   deciden si desplaza trabajo, no el mero hecho de llegar.
   Si una sesión muere dejando un lock, `peticion.py desbloquear P-ID` solo lo retira cuando
   el proceso local ya no existe; un lock de otro host exige `--forzar --motivo`.
3. **Contrastar tres anclajes:** flujo aprobado, código real con SHA y conocimiento vigente.
   Las respuestas pueden ser “ya existe”, “falta aclarar”, “cambia los flujos”, “abre un bug”
   o una ruta de trabajo; no se presupone que toda petición produzca una feature.
4. **Elegir investigación por incertidumbre y riesgo, no por tamaño:**

   - `ninguna`: flujo, código y conocimiento ya contestan; se citan los tres.
   - **investigación acotada**: 2–4 lentes independientes, preguntas y criterio de parada.
   - `plataforma`: decisión fundacional o transversal; fase 3, normalmente diez lentes.

5. **Síntesis antes de especificar.** En `acotada`, completar
   `investigacion/revision-N/SINTESIS.md`: cada pregunta queda `respondida` o
   `no_concluyente`, con fecha y URL o ruta con ancla. Una
   respuesta no concluyente sobre seguridad, dinero, PII, contrato o pérdida de datos
   bloquea la orden; se pregunta, prototipa o aparca.
   El perfil `plataforma` no duplica esos papeles: referencia con
   `--sintesis-plataforma docs/03-investigacion/SINTESIS.md` la fase 3 ya cerrada. El gate
   exige sus diez informes con URL, fecha y nivel, y que cada pregunta de la petición aparezca
   en la síntesis global con el mismo formato `respondida|no_concluyente · … · evidencia ·
   fecha`; un `no_concluyente` crítico bloquea igual que en investigación acotada.
6. **Evaluar y fijar la ruta.** Ejemplo sin investigación nueva:

   `python3 docs/00-metodo/scripts/peticion.py evaluar P-ID --ruta directo --investigacion ninguna --motivo "…" --flujo REC-1 --huella-flujo <huella> --sha <sha> --ruta-codigo <ruta> --conocimiento <ruta>`

7. **Crear o enlazar el proceso canónico.** Una unidad siempre nace así:

   `python3 docs/00-metodo/scripts/unidad.py nueva <tipo> <slug> --desde P-ID`

   `--desde` es repetible cuando una orden satisface varias peticiones. Exprés usa
   `peticion.py abrir-expres P-ID <slug>`. Bugs, auditorías, flujos y despliegues conservan el
   mismo P-ID; no inventan otra cola.
   Pedirle al usuario el OK sobre ese contrato exige levantar antes el visor de contratos EN
   EL MISMO TURNO: `python3 main/web/abrir.py --workspace . --apartado contratos`. Sin su
   rastro, `unidad.py despachar` bloquea aunque el frontmatter ya tenga `aprobado: FECHA`.
   Si no puede abrir la web (SSH, sandbox sin puertos, móvil), la segunda puerta vale
   igual: le pasas `python3 docs/00-metodo/scripts/unidad.py aprobar NNN-slug --por "<su
   nombre>"` y lo teclea ÉL en su terminal — deja los mismos dos rastros, y tú no lo
   ejecutas nunca.
8. **Revalidar durante la obra.** El despacho, push y cierre comprueban `P-ID@revision`. Una
   aclaración material incrementa la revisión y para la orden. Tras reevaluar, el padre usa
   `peticion.py reencuadrar-orden P-ID --desde-revision N --tipo unidad --ref NNN-slug`:
   conserva el enlace anterior como sustituido, actualiza `P-ID@revision` e invalida la
   aprobación para que el usuario apruebe el contrato revisado. Una aclaración informativa
   no cambia la revisión.
   La investigación puede continuar durante el desarrollo, pero un hallazgo que cambia el
   contrato se captura o aclara y vuelve a sus gates; no se cuela en el diff.
9. **Reconciliar y cerrar.** Cada proceso aporta su evidencia terminal. La petición se cierra
   automáticamente cuando existe un único enlace `satisface` y termina. En fan-out, tras
   terminar todos, el padre aporta evidencia y cobertura conjunta con `peticion.py cerrar`.
   Varias peticiones por unidad son relaciones normales, no excepciones.
   - `merge-externo` — el trabajo ya lo trajo un merge ocurrido FUERA del método (un PR de
     un tercero, una fusión a mano). Se cita uno por merge:
     `peticion.py enlazar P-ID --tipo merge-externo --ref '#36' --relacion satisface`
     (`--ref` acepta `#36`, la URL del PR o el SHA, que debe existir en el repo de código).
     Nace terminal: no hay obra pendiente que reconciliar. No sustituye a una unidad cuando
     el trabajo está por hacer — solo describe lo que YA pasó (unidad 087).

## Salidas sin obra

- `ya_existia` o `sin_cambio`: cerrar con evidencia y cobertura.
- `aparcada`: motivo, responsable y fecha o condición de revisión.
- `duplicada`: enlace a la petición canónica.
- `cancelada` o `rechazada`: quién lo decidió y por qué; jamás borrar la historia.
- Una petición terminal que vuelve a cambiar se `reabre`: el cierre anterior permanece en
  historia y nace una revisión nueva. Un hallazgo hijo se enlaza con `relacionar --tipo padre`.

Cancelar trabajo ya abierto exige marcar antes cada proceso como `cancelado`, con evidencia de
parada segura. Una reconciliación tardía nunca puede convertir esa cancelación en entrega.

## Límite honesto de la garantía

El repositorio no puede detectar una frase que nunca salió del chat. Por eso AGENTS.md exige
capturar como primera escritura. Desde ahí, scripts, linter, hook y CI impiden crear, empujar,
despachar o cerrar trabajo nuevo sin origen persistente. En modo estricto la principal solo se
puede empujar por el Camino B de cierre: el commit debe seguir contenido en su rama NNN/exprés
evaluada y enlazada; un commit hecho directamente en `main` no tiene ese testigo y se bloquea.
