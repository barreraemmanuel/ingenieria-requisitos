# Runbook · DOCUMENTACIÓN

**Entrada:** petición evaluada por `runbooks/peticiones.md`.

**Cuándo:** crear o corregir documentación como entregable: guía de usuario, README del
repositorio de código, operación, API o explicación de un proceso.
**Resultado:** documentos comprobados contra el sistema real y útiles para su lector.

## Elegir el modo antes de crear la unidad

- **Documentación del meta-repo:** no toca código; despacho `--documental`.
- **Documentación que pertenece al software** (`main/README.md`, manual empacado, API):
  rama y worktree normales; termina en PR.
- **Flujos de usuario:** no usa este runbook. Se modifica `planos.json` mediante el kit de
  requisitos, se enseña el visor y se obtiene aprobación.

## Paso a paso

1. **Definir lector y tarea.** “Documentar X” no basta. La spec dice quién lo leerá y qué
   podrá hacer sin ayuda al terminar.
2. **Comprobar la realidad antes de escribir.** Abrir las rutas citadas, ejecutar cada
   comando, revisar las pantallas y comparar con el código. Lo antiguo se identifica antes
   de copiarlo.
3. **Crear la unidad:**
   `python3 docs/00-metodo/scripts/unidad.py nueva documentacion <slug> --desde P-ID`.
4. **Rellenar el contrato.**
   - R* verificables: “una persona nueva puede arrancar la app siguiendo estos pasos”.
   - Idioma y nivel del lector.
   - Documentos creados, actualizados y eliminados.
   - Deltas al mapa si se descubre una contradicción, que no se aplican sin el usuario.
5. **Aprobación del usuario** del alcance y del documento que se sustituirá.
6. **Despachar.**
   - Solo meta: `unidad.py despachar NNN-slug --documental`.
   - Código: `unidad.py despachar NNN-slug`; el subagente trabaja en su worktree.
7. **Escribir lo no deducible:** motivos, límites, comandos, ejemplos, errores frecuentes y
   cómo recuperarse. No narrar línea a línea un código que ya se explica solo.
8. **Verificar cada promesa.** Ejecutar los comandos desde un entorno limpio, comprobar
   rutas/enlaces y recorrer los pasos con los ejemplos de la spec.
9. **Revisor fresco.** Repite la guía sin contexto previo y señala pasos ambiguos, ausentes
   o falsos. Los huecos vuelven al subagente.
10. **Entrega.**
    - Si toca código: commit, push, PR, revisión, merge y verificación sobre `main`.
    - Si es documental: el padre integra el documento en el meta-repo.

    **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
    paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
    `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
    —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que
    no lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles
    cuando quiera.
11. **Validación del usuario.** El usuario lee la guía y realiza la tarea prometida. Sin su
    confirmación el trabajo sigue `en_revision`.
12. **Cierre** (`runbooks/cierre.md`). Aplicar deltas aprobados, actualizar ESTADO/ROADMAP, promover aprendizajes,
    archivar la unidad y borrar rama/worktree cuando existan.

## Puertas de cierre

- Cero comandos no ejecutados.
- Cero rutas o enlaces rotos.
- Diferencia clara entre hecho actual, decisión futura y ejemplo.
- El documento antiguo se actualiza o se elimina; no quedan dos verdades.
- Una persona del público objetivo completa la tarea descrita.
