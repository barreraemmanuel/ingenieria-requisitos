# Runbook · MIGRACIÓN

**Entrada:** petición evaluada por `runbooks/peticiones.md`; los riesgos de datos, contrato o
rollback no concluyentes bloquean la spec.

**Cuándo:** conservar el comportamiento sobre una base nueva: versión de framework,
librería, motor de datos, formato, infraestructura o etapa de ejecución.
**Resultado:** datos y comportamiento preservados, suite completa verde, vuelta atrás
probada y destino verificado.

## Paso a paso de construcción

1. **Definir una sola frontera.** Origen y destino exactos. No mezclar actualización de
   framework, tres librerías y rediseño de datos en la misma unidad.
2. **Investigar fuentes oficiales.** Changelog, guía de migración, incompatibilidades,
   soporte y seguridad, con versión y fecha. Territorio incierto implica carril completo.
3. **Inventariar datos y dependencias.** Qué se transforma, cuánto ocupa, quién lo consume,
   tiempo de indisponibilidad permitido y qué integraciones podrían romperse.
4. **Crear la unidad:**
   `python3 docs/00-metodo/scripts/unidad.py nueva migracion <slug> --desde P-ID`.
5. **Escribir la spec antes de tocar nada.**
   - Origen → destino.
   - R* que fijan el comportamiento existente.
   - Comprobaciones de integridad: conteos, relaciones, hashes o muestras.
   - Backup y restauración de prueba.
   - Plan de vuelta atrás con comandos y tiempo máximo.
   - Pasos manuales, variables, orden y dueño.
6. **El usuario aprueba** riesgo, ventana, pérdida máxima aceptable y vuelta
   atrás.
7. **Despachar** con `unidad.py despachar NNN-slug`; rama desde la `main` más reciente y
   worktree aislado.
8. **Caracterizar primero.** El subagente crea o ejecuta pruebas que describen el estado
   previo y guarda la línea base. Si faltan, las añade antes de migrar.
9. **Backup verificable.** Crear la copia y restaurarla en un entorno desechable. “El archivo
   existe” no prueba que se pueda recuperar.
10. **Ensayo completo.** Ejecutar migración, integridad, suite y rollback en entorno no
    productivo con un volumen representativo. Registrar duración y problemas.
11. **Implementar el camino repetible.** La migración y su reversión quedan en código o
    programas Python del repositorio, no como una secuencia recordada.
12. **Verificación.** Suite completa, flujos críticos, integridad de datos y compatibilidad
    con integraciones en verde.
13. **PR.** Commit, push y pull request `NNN-slug`; el subagente PARA; el `estado: en_revision` lo escribe el padre al recibir el PR (regla 2).

    **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
    paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
    `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
    —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que
    no lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles
    cuando quiera.
14. **Cierre de código** (`runbooks/cierre.md`). Revisor fresco, correcciones, merge, suite e2e sobre `main`,
    instancia local y validación del usuario.

## Subir de etapa o desplegar

Lo ejecuta el rol DEPLOY en sesión separada y siguiendo `runbooks/deploy.md`.

1. Leer `conocimiento/plano-deploy.md`; si no existe, hacer primero su entrevista.
2. Verificar de nuevo backup y restauración justo antes del cambio.
3. Confirmar por escrito commit, destino, ventana, responsable y orden.
4. Confirmar que el rollback sigue siendo ejecutable y cabe en la ventana.
5. Ejecutar únicamente el camino declarado; nada improvisado en la máquina.
6. Comprobar en caliente la aplicación y al menos un flujo real de punta a punta.
7. Comprobar observabilidad: disponibilidad, errores y tareas de fondo.
8. Si falla una puerta, volver atrás inmediatamente y abrir bug; no encadenar parches.
9. Anotar qué commit corre, dónde, desde cuándo y quién lo desplegó.
10. Obtener el OK del usuario sobre la etapa real. Fusionar `main` nunca equivale a
    desplegar.

## Puertas de cierre

- Backup restaurado de prueba.
- Rollback ensayado y documentado.
- Integridad antes/después demostrada.
- Suite completa y flujos críticos verdes.
- Commit/PR revisados.
- Destino real y usuario validados cuando hubo despliegue.
