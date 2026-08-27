# RUNBOOK/modo-d.md — Actualizar los proyectos ya creados

> Módulo de `RUNBOOK.md` (el router). Se lee solo en Modo D: mantenimiento de
> proyectos ya creados ("actualiza mis proyectos", "¿están al día?"). No hace
> falta ningún otro módulo de `RUNBOOK/` para este modo.

## Modo D: actualizar los proyectos ya creados

Cuando esta herramienta mejora su método, los workspaces ya creados **no se
enteran solos**: cada uno es un repositorio aparte y su copia del método salió
de aquí por copia de ficheros, no por clonado. Un `git pull` allí trae el
historial de ESE proyecto; del método, nada. Esto es lo que lo reparte.

**Cómo se deshace — que es lo que permite que todo lo demás sea simple.** Antes
de tocar un solo fichero, `aplicar` exige que el workspace sea un repositorio
Git con árbol e índice limpios; su HEAD es el punto de retorno. Volver atrás es
`git checkout <ese commit>`, y ese commit queda escrito en
`docs/00-metodo/HISTORIAL.md`. Por eso el método se sobrescribe ENTERO, sin
clasificar fichero por fichero ni preguntar por cada uno: si ese proyecto había
adaptado un runbook a su gusto, esa versión no se pierde — está a un checkout de
distancia. Si no hay un punto de retorno limpio, no se toca nada y se dice por qué.

0. **Encuentra los proyectos.** El registro local solo conoce lo que se creó en
   ESTA máquina con esta herramienta; un workspace clonado, movido o hecho en
   otro ordenador no está. Así que primero se rastrea y se registra lo que
   aparezca:

   `python3 RUTA_HERRAMIENTA/visor/actualizar.py buscar`

   Mira la carpeta del usuario y las de trabajo habituales. Si sus proyectos
   viven en otro sitio, pregúntaselo y añade `--en /ruta/donde/estan`.

1. **Enseña la foto y pregunta.** Sin tocar nada:

   `python3 RUTA_HERRAMIENTA/visor/actualizar.py revisar --todos`

   Sale, proyecto por proyecto, qué ficheros del método cambian y cuáles hay
   allí que el método ya no publica (esos NO se borran: solo se avisan).
   Si el proyecto aún no tenía inbox, anuncia también el `LEGACY.json` exacto
   que se creará en modo observación; `revisar` sigue sin escribirlo.
   Cuéntaselo en cristiano ("de tus tres proyectos, dos están al día y uno tiene
   veintisiete cosas nuevas del método") y **pregúntale cuáles quiere
   actualizar**: todos, algunos o ninguno.

2. **Aplica lo que te diga:**

   `python3 RUTA_HERRAMIENTA/visor/actualizar.py aplicar --todos` (o con la ruta
   de uno). Adquiere autoridad exclusiva sobre el workspace y su índice Git: si otra
   sesión mantiene una operación incompatible, PARA antes de escribir y dice quién la posee.
   Hace `fetch` antes del punto de retorno y bloquea si el remoto avanzó. Exige árbol e índice
   limpios: nunca stagea ni commitea trabajo ajeno. Una ficha con trabajo en vuelo no bloquea
   (ADR-025): se avisa con su lista, el trabajo queda intacto y esas unidades cerrarán ya con
   el método nuevo. Si aparece trabajo después, las rutas explícitas también lo dejan fuera. Sobrescribe el método, lo anota
   en el HISTORIAL y pasa el linter de ese workspace **antes** del commit final.
   Si el proceso cae, la siguiente ejecución recupera primero el snapshot durable de
   `.runtime/transactions/modo-d.json`. Si el linter falla, mide de quién es el rojo
   comparándolo con lo que ese mismo workspace decía ANTES de tocarlo: los fallos que ya
   estaban no revierten nada (se avisa "ya estaban antes de actualizar" y la actualización
   se queda — revertir no los limpiaría y dejaría el workspace atrapado en el método viejo);
   solo si la actualización introduce fallos NUEVOS restaura las rutas tocadas, los lista
   como causa y devuelve error: nunca anuncia una actualización aplicada a medias. La primera
   adopción del inbox guarda unidades, bugs y ramas anteriores en `LEGACY.json` con modo
   `observacion`; no fabrica peticiones retroactivas.

3. **Enséñale el resultado.** `git -C <workspace> log --oneline -2` y
   `git -C <workspace> show --stat` (jamás el diff entero: el método son ~90 ficheros
   y casi un mega — `--stat` dice qué cambió sin pagarlo): qué ha cambiado, contado
   en negocio ("ahora el cierre avisa si algo se quedó sin guardar"). Si algo no le convence, el
   comando para deshacerlo está escrito en `docs/00-metodo/HISTORIAL.md`. Si ese
   workspace tiene remoto, ofrécele publicarlo — pero **`git push` solo con su OK
   explícito, workspace por workspace**: publicar en un remoto es del dueño, nunca
   parte automática de actualizar (un agente ya publicó una actualización sin
   autoridad en un repo ajeno y quedó como incidente P1). Con su OK, sus otras
   máquinas se lo bajan con un `git pull` normal; sin él, la actualización se
   queda local y perfecta.

Límites que el modo D no cruza jamás: no toca `01-constitucion/`,
`02-flujos/`, `03-investigacion/`, `04-planificacion/`, unidades vivas o
archivadas, `bugs/`, `conocimiento/`, `decisiones/`, `repos.yaml`, `.private/`,
`main/` ni `worktrees/`. Única escritura fuera del método: al adoptar el inbox,
`05-trabajo/peticiones/LEGACY.json`, derivado del inventario y sin P-IDs.
