# ADR-031 · La sanidad se mide con un guardián, repara papeles y jamás código

**Fecha:** 2026-08-25 · **Estado:** aceptada · Unidad 059 · Petición P-20260825-3cbb95bd@1

## Contexto

El método tenía la doctrina de la limpieza —auditoría de calidad, auditoría del método,
auditoría de drift, «docs fuera del repo» (ADR-001)— y ningún ejecutor (ADR-029): nadie
contaba papeles, nadie medía cobertura, nadie cruzaba rutas con ficheros, y el único rol que
miraba (OBSERVABILIDAD) tenía prohibido tocar. Medido el 25-08-2026 en el workspace del
método: 287 documentos, 5 actas sueltas junto a ESTADO.md (119 líneas, tope 100), 50
peticiones sin evaluar, 20 rutas citadas que no existen, 46 TODO sin dueño, cobertura nunca
medida, y el linter arrancando con 5 FAIL y 69 WARN sin que nadie lo tomara como señal.

## Decisión

1. **Un guardián estático mide once ejes** (`scripts/sanidad.py medir`) con veredicto,
   número y «con qué midió», y deja cada pasada en un libro comparable
   (`05-trabajo/SANIDAD.md`). Lo que no se pudo medir se muestra como no comprobado, nunca
   como correcto.
2. **Nunca peor que la última vez.** Cobertura, docstrings y deuda se comparan con la
   última fila del libro; empeorar es un hallazgo. No hay umbral fijo inventado el primer día.
3. **Un rol SANIDAD, sesión propia, con dos manos.** Repara papeles del meta-repo con una
   lista cerrada, listada y reversible (`sanidad.py reparar`). Todo lo del código entra como
   petición con evidencia (`sanidad.py capturar`), lo decide el usuario en el visor de
   contratos y se construye como ola de unidades por el cauce normal. La actividad de
   auditoría y su regla «quien observa no arregla» quedan intactas.
4. **La cadencia tiene ejecutor.** `sanidad.py atraso` cuenta cierres y días desde la última
   pasada; el arranque lo avisa con el comando de salida.
5. **Las herramientas externas se usan si están y no se exigen.** El guardián funciona con la
   biblioteca estándar y mejora con vulture, coverage, interrogate, pip-audit o deptry.

## Consecuencias

- Nace `sanear-workspace` en el mapa; `roles.md`, `README.md`, `detectores.md` y
  `comunicacion.md` cambian; `auditoria-calidad.md` cita al script en vez de pegar código.
- Deuda declarada: el aviso en `lint_metodo.py` y el rol en `AGENTS.md` esperan a que la 049
  libere esos ficheros (P-20260825-7f23b7f6, P-20260825-287cbdeb).
- Lo malo: once ejes son once sitios donde equivocarse; por eso cada hallazgo lleva confianza
  y solo los de confianza alta paren peticiones por defecto.

## Verificación

- `python3 -m unittest visor.tests.test_sanidad` → verde; incluye los falsos positivos que NO
  deben salir y el hash del árbol de `main/` antes y después de `reparar`.
- `python3 docs/00-metodo/scripts/sanidad.py ejes` → once nombres, los mismos que los
  encabezados de `auditoria-sanidad.md` y las columnas de `plantillas/sanidad.md`.
