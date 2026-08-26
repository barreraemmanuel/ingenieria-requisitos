# ADR-035 · Sin CI remoto por defecto: la verificación del método es local

**Fecha:** 2026-08-27 · **Estado:** aceptada · Supera lo que ADR-018 y ADR-028 daban por hecho

## Contexto

Petición P-20260827-2b832e8b: «por defecto nunca usar GitHub Actions y correr las pruebas en
local», y «tiene que quedar constancia en el método oficial, no solo en este meta-repo».

Hasta hoy eso vivía en la memoria del agente y en el `ESTADO.md` de un workspace concreto, así
que no viajaba a ningún proyecto. El método escrito decía lo contrario en tres sitios:

- **ADR-018** («el CI real nace con el stack») da por hecho que la primera unidad técnica crea
  `scripts/ci/*` **y** los workflows de GitHub Actions y el Dependabot.
- **ADR-028** («el CI es guía, no gate») bajó el bloqueo a aviso, pero dejó el aviso: el WARN
  `DEUDA-CI: contrato sin materializar` seguía llamando *deuda* a no tener CI remoto.
- `lint_ci.py` imprimía ese WARN en cada ronda de lint y remataba con «para materializarlo,
  abre una unidad»: un guardián empujando, cada arranque, hacia algo que nadie había pedido.

El coste real no es el WARN: es que un aviso repetido que nadie va a atender enseña a ignorar
los avisos, y que la CI remota gratis se paga en minutos de cola, secretos en un tercero y
falsos rojos que no reproduce nadie. Quien construye con este método ya corre la suite entera
en su máquina antes de fusionar, y esa es la evidencia que el cierre exige (regla 12).

## Decisión

**La verificación del método es LOCAL.** La suite, los lints y los checks de seguridad se
corren en la máquina de quien construye, antes de fusionar, y su output es la evidencia del
cierre. **No se crea ningún CI remoto** —GitHub Actions, GitLab CI, CircleCI o el que sea—
salvo que el usuario lo pida expresamente y quede escrito en `01-constitucion/bias.md`:

```
- ci_remoto: sí        # ausente o `no` = verificación local (ADR-035)
```

Consecuencias concretas:

1. `AGENTS.md` (regla 12, «Evidencia, no afirmación») lo dice como regla dura: la verificación
   es local y el CI remoto solo nace de una petición escrita en el bias.
2. `lint_ci.py` deja de tratar la ausencia de CI remoto como deuda. Con `ci_remoto` ausente o
   `no`, comprueba que el repo de código **declare sus checks locales** en su `AGENTS.md`
   (comandos entre comillas invertidas en las líneas de tests, lint, suite o seguridad) y sale
   con `OK` y 0 FAIL. Sin esa declaración avisa —pero pidiendo que se escriban los comandos
   reales, no que se monte un CI.
3. Con `ci_remoto: sí` y sin CI montado, el WARN de siempre: ADR-028 sigue vivo, es guía y no
   gate, y ahora nombra sus dos salidas (materializarlo o corregir el bias).
4. Un repo que YA tiene workflows se valida exactamente como hasta hoy: sin marcadores sin
   rellenar, sin `||` que convierta un rojo en verde y con las Actions ancladas por SHA. Tener
   CI remoto nunca fue el problema; el problema era que faltarlo pareciera un defecto.

## Qué supera de ADR-018 y ADR-028 (que NO se editan)

ADR-018 sigue describiendo bien **cómo tiene que ser** un CI que se monte: por stack, sin
mentiras, materializado con la primera unidad técnica. Lo que queda superado es su premisa de
que ese CI es **remoto y obligatorio**: hoy la primera unidad materializa los checks —los
scripts y comandos que se corren— y solo los publica en un CI remoto si el bias lo pide.

ADR-028 sigue vigente entero: este control avisa, nunca bloquea. Lo que queda superado es qué
cuenta como aviso: la ausencia de CI remoto ya no es «deuda», es la configuración por defecto.

## Límites

- No borra `lint_ci.py` ni relaja una sola de sus comprobaciones sobre quien sí tiene CI.
- No toca el ritual de cierre: la suite local en verde antes del merge sigue siendo dura.
- No crea plantillas de workflows, ni las prohíbe: prohíbe **suponerlas**.
- El caso «CI remoto pedido» se declara en un solo sitio, el bias del proyecto. Ni en el
  ESTADO, ni en la memoria del agente, ni en la costumbre de la máquina.
