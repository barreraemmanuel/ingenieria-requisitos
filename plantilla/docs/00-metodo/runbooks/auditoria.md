# Runbook · AUDITORÍA

**Entrada:** petición evaluada por `runbooks/peticiones.md`.

**Cuándo:** revisar sin construir: seguridad, calidad, rendimiento, accesibilidad,
observabilidad o diferencias entre documentación y código.
**Resultado:** una unidad `auditoria` con `informe.md`; cada hallazgo incluye evidencia,
severidad, alcance y una recomendación. La auditoría nunca arregla lo que encuentra.
**Ejecución:** documental. Lee `main/` y escribe solo en su carpeta de unidad; no crea rama
de código ni worktree.

## Paso a paso

1. **Acotar con el usuario.** El padre escribe qué se audita, qué queda fuera y qué pregunta
   debe responder el informe. Una auditoría genérica de “mira todo” se divide por lentes.
2. **Crear el contrato.**
   `python3 docs/00-metodo/scripts/unidad.py nueva auditoria <slug> --desde P-ID`.
   En la especificación:
   - `Qué`: sistema y periodo examinados.
   - `Criterios R*`: controles concretos y qué evidencia los satisface.
   - `Deltas al mapa`: normalmente ninguno; si se audita drift, se declaran candidatos,
     nunca se modifica el mapa durante la auditoría.
   - `Verificación`: comandos de solo lectura y formato final del informe.
3. **El usuario lee y aprueba el alcance.** Se anota la fecha en `aprobado:`.
   Sin ella no se abre la auditoría.
4. **Elegir lentes independientes.** El padre lanza uno o varios subagentes auditores. Cada
   uno recibe una lente sin solapamiento y escribe en una sección o informe distinto dentro
   de la unidad. Seguridad usa `auditoria-seguridad.md`; calidad,
   `auditoria-calidad.md`; método, `auditoria-metodo.md`.
5. **Despachar sin código:**
   `python3 docs/00-metodo/scripts/unidad.py despachar NNN-slug --documental`.
   No existe permiso de escritura sobre `main/`.
6. **Recoger evidencia.** Cada afirmación cita una ruta, línea, comando con output, captura
   o comportamiento reproducible. “Parece inseguro/lento” no es un hallazgo.
7. **Intentar refutar.** Antes de incluir un hallazgo, otro auditor o el padre intenta
   demostrar que es falso. Lo no confirmado se marca como hipótesis y no pare trabajo.
8. **Clasificar:** P0 crítica y activa; P1 grave; P2 importante; P3 mejora; P4 cosmética.
   Además: confirmado, no reproducible, duplicado o riesgo aceptado.
9. **Revisión con el usuario.** Se presenta en lenguaje normal: qué puede pasar, a quién
   afecta, evidencia y coste aproximado de corregirlo. El usuario decide cuáles acepta.
10. **Cierre documental** (`runbooks/cierre.md`). El padre marca la unidad `mergeada`, promueve
    el informe útil a `conocimiento/` y, por cada hallazgo aceptado, captura primero un P-ID y
    lo enlaza a la petición de auditoría con `peticion.py relacionar <hijo> --tipo padre --con
    <P-ID-auditoría>`; solo después crea con `--desde P-ID` el bug, refactor, documentación o migración. Actualiza
    ROADMAP/ESTADO y mueve la auditoría a `archivo/`.

## Puertas de cierre

- Todos los R* contestados con evidencia o “no comprobable” explicado.
- Ningún subagente modificó código, configuración ni servicios externos.
- Cada hallazgo fue refutado o confirmado antes de presentarlo.
- El usuario decidió qué acepta, descarta o pospone.
- Los aceptados tienen unidad propia; la auditoría no contiene arreglos camuflados.

## Auditoría de drift

Se ejecuta periódicamente y siempre tras cambios grandes. Compara en ambos sentidos:

- Promesas de `02-flujos/` que el código ya no cumple.
- Comportamientos de `main/` que los flujos no explican.
- Comandos o rutas documentados que ya no existen.

Corregir el mapa exige volver al visor de requisitos y obtener el OK del usuario; corregir
el código exige una unidad de construcción.
