# ADR-013 — Se escribe según se hace: la firma la pone quien estuvo, y el cierre deja rastro

## Decisión vigente

Salida de un caso real: cinco unidades cerradas cuyo `revisor:` estaba vacío. Las revisiones
habían ocurrido —había veredictos fechados—, pero nadie apuntó quién las hizo, y al cerrar, el
padre acabó escribiendo una firma que no podía conocer. El campo que existe para impedir el
auto-sello se rellenó de memoria.

1. **La firma la pone el revisor, en la misma escritura que su veredicto.** Es el único que
   sabe quién es. Ni el constructor ni el padre escriben en la sección Revisión: el padre solo
   la lee. La causa del fallo era una contradicción del propio método —`plantillas/hallazgos.md`
   decía "lo escribe el padre en el cierre" y `runbooks/cierre.md` decía que lo escribe el
   revisor—, y con dos instrucciones opuestas no lo escribía nadie.

2. **Una firma que falta no se rellena después: se vuelve a revisar.** Si al
   cerrar `revisor:` sigue vacío, ya nadie puede saber quién revisó. Escribir ahí un nombre
   plausible es exactamente el auto-sello que el campo impide. Lo dicen la plantilla, el
   runbook y el mensaje de error de `unidad.py cerrar`.

3. **Cada paso del cierre se marca al terminarlo, no al final.** La §Bitácora del cierre de
   `hallazgos.md` lleva una casilla por paso del ritual, con fecha y con quién lo hizo.
   "Indivisible" no significa que la sesión no se pueda morir a mitad: significa que si se
   muere, la siguiente lo retoma leyendo esas casillas —lo marcado no se repite, lo no marcado
   no se da por hecho— en vez de deducir de `git log` qué llegó a pasar.

## Consecuencias

- Regla de oro nueva en `AGENTS.md`: **lo que solo está en el contexto de la sesión, está
  perdido; lo que se rellena después de memoria, es inventado.** Aplica a todo el método, no
  solo al cierre.
- Un cierre a medias deja de ser un misterio arqueológico y pasa a ser una lista con casillas.
- El coste es una línea escrita por paso. Es el precio de que cualquier sesión sea reanudable
  por otra que no estuvo.
