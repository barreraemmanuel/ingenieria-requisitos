# Runbook · REFACTOR

**Entrada:** petición evaluada por `runbooks/peticiones.md`.

**Cuándo:** mejorar estructura, legibilidad, mantenibilidad o rendimiento sin cambiar el
comportamiento observable.
**Resultado:** el mismo producto, con la suite existente intacta y una estructura mejor
demostrada.

## Paso a paso

1. **Justificar.** El padre identifica el problema concreto: duplicación, módulo demasiado
   grande, acoplamiento, deuda o cuello medido. “Limpiar un poco” no abre una unidad.
2. **Buscar cobertura.** Ejecutar la suite actual y localizar qué tests protegen la zona.
   Sin cobertura suficiente, primero se crea una unidad separada de tests de
   caracterización que documenten lo que hace hoy.
3. **Crear la unidad:**
   `python3 docs/00-metodo/scripts/unidad.py nueva refactor <slug> --desde P-ID`.
4. **Contrato específico.**
   - `Qué`: qué responsabilidad se mueve o simplifica.
   - R*: comportamientos que deben permanecer idénticos.
   - Métrica antes/después si el motivo es rendimiento.
   - `Fuera de alcance`: cualquier cambio funcional.
   - Ficheros exactos; hotspots compartidos hacen la unidad secuencial.
5. **El usuario aprueba** el alcance y entiende que no ganará una función
   nueva.
6. **Despachar** con `unidad.py despachar NNN-slug`. El script crea la rama desde la `main`
   más reciente y el worktree.
7. **Línea base verde.** El subagente pega el output de la suite antes de tocar código.
   Si ya está roja, para: no se atribuyen fallos heredados al refactor.
8. **Transformar en pasos pequeños.** Un cambio estructural por commit lógico. Después de
   cada paso, ejecutar las pruebas de la zona.
9. **Los tests existentes no se editan, debilitan ni eliminan.** Si uno impide
   el cambio porque el comportamiento debe variar, esto dejó de ser refactor: parar y volver
   al usuario como feature o bug.
10. **Verificación final.** Suite completa, lint y comprobaciones de tipos en verde. Para
    rendimiento, misma carga y entorno que la medición inicial.
11. **PR.** Commit, push y pull request `NNN-slug`; el subagente se detiene y
    el `estado: en_revision` lo escribe el padre al recibir el PR (regla 2).

    **Política de publicación (`push:` de `repos.yaml`).** Con `push: agente` —el defecto— este
    paso es el de siempre. Con `push: usuario` termina en el **commit local**: ni `git push` ni
    `gh pr create`. La rama se queda en su worktree y el comando exacto para publicarla
    —`git -C main push -u origin NNN-slug`— se deja escrito en `hallazgos.md` (en exprés, que
    no lo tiene, en el aviso al usuario), para que lo ejecute él con sus propios controles
    cuando quiera.
12. **Cierre del padre** (`runbooks/cierre.md`). Revisor fresco compara diff, spec y tests; huecos vuelven al
    constructor. Limpio: merge, suite e2e sobre `main`, instancia real y validación del
    usuario de que nada cambió. Después se actualiza estado, se archiva y se elimina
    worktree/rama.

## Puertas de cierre

- Línea base y resultado final verdes, con outputs.
- Ningún test existente modificado.
- Ningún comportamiento o flujo cambiado.
- Métrica comparable cuando el objetivo era rendimiento.
- Usuario valida la aplicación ejecutándose.
