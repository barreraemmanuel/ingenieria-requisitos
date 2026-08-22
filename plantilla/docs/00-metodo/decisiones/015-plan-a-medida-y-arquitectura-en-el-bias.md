# ADR-015 · El plan de trabajo a medida, y la arquitectura decidida una sola vez

**Fecha:** 2026-08-03 · **Estado:** aceptada

## Contexto

El método declara su propia jerarquía de confianza (`00-metodo/README.md`):
**script/hook > plantilla > prosa**. Medido contra esa jerarquía, el método se contradecía:

- Toda la **ceremonia** estaba en marcas de puerta infranqueable y en scripts que bloquean.
- Todo el **freno** —"iteración corta", "resolver el problema de hoy y no los futuros",
  "unidades pequeñas y contratos breves"— era **prosa, en el último párrafo de un README de 175
  líneas**. Por su propia regla, perdía siempre.

Dos sitios concretos donde eso producía trabajo de más en cada unidad, del tamaño que fuera:

1. **El plan de trabajo era un esqueleto FIJO** que exigía tests de integración **y**
   end-to-end en rojo antes de implementar, más un paso 4 de "tests adicionales que claven los
   casos límite". Para un cambio de una regla de negocio, eso es una suite ceremonial: tests que
   no pueden fallar por culpa de ese cambio, que tardan, y que no protegen nada.
2. **`feature.md` paso 3 y la plantilla de especificación ordenaban, en CADA feature:**
   *"Single Responsibility, KISS, clean code; encapsular por funcionalidades con capas de
   abstracción; los módulos se comunican entre ellos… refactorizando si hace falta"*. Eso no es
   una guía de diseño: es una invitación a rediseñar la aplicación en cada tarea, escrita dentro
   del documento que debía ser un contrato acotado. El over-engineering estaba **prescrito**.

## Decisión

**1. El nivel de test lo declara la spec, no la costumbre.** `§Verificación` incluye una línea
obligatoria que lo elige y lo justifica: end-to-end sólo si el cambio cruza la aplicación de
punta a punta · integración si cruza una frontera (base de datos, servicio, API) · unitario si es
una regla de negocio. Regla de corte: **un test que no puede fallar por culpa de ESTE cambio no
se escribe.** El paso 4 del plan pasa a ser condicional y se BORRA si el paso 1 ya lo cubre — un
paso que se cumple marcando la casilla sin escribir nada no es un paso, es un peaje.

**2. Las reglas de diseño se escriben una vez, en `01-constitucion/bias.md`**, sección "Cómo se
diseña el código", y valen para toda unidad. Ninguna spec las repite ni las re-argumenta. En la
spec queda sólo lo específico: dónde vive ya esto y cómo se encaja ahí.

**3. Si no cabe en el módulo que le corresponde, se PARA.** Eso es un refactor con
su propia unidad y su propia aprobación, nunca un rodeo dentro de otra tarea. Antes, "encajar
refactorizando si hace falta" autorizaba a cualquier constructor a abrir la caja entera sin que
nadie lo aprobara.

## Consecuencias

- El freno deja de ser prosa: vive en la plantilla (el hueco obligatorio del nivel de test) y en
  un hard-gate, que es donde el propio método dice que las reglas se cumplen.
- Riesgo asumido: un nivel de test elegido a la baja deja un hueco. Se cubre porque la elección
  se **escribe y se justifica** en la spec que el usuario aprueba, y el revisor la mira contra el
  diff — un nivel mal elegido es ahora visible, no implícito.
- El bias pasa a contener decisiones de diseño además de decisiones de tecnología. Es su sitio:
  ya era el documento que responde "cómo se construye aquí", y es el único que el constructor
  lee siempre (va en el Contexto de todas las plantillas).
