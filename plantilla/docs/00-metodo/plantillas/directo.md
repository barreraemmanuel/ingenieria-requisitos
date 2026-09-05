---
unidad: NNN-slug
tipo: feature            # feature | refactor | documentacion (bug: usa plantillas/bug.md)
carril: directo          # cambia comportamiento, encaja donde ya vive, 1-3 ficheros, se deshace
estado: planificada
aprobado: no             # LO PONE EL USUARIO: `no` | fecha YYYY-MM-DD. Sin fecha no hay despacho.
actividad: <id del INDICE de flujos — la que YA existe y donde esto encaja>
ficheros: []             # 1-3 rutas del repo de código. Ningún hotspot (migraciones, rutas,
                         # modelos compartidos, lockfiles): esos son SIEMPRE carril normal.
peticiones: []            # referencias P-ID@revision que satisface esta unidad
actualizado: YYYY-MM-DD
---

# NNN · <título en una frase>

> Carril **directo** (`runbooks/directo.md`): contrato de una pantalla. Si al escribirlo no cabe
> aquí, no era directo — se rehace por `runbooks/feature.md`.

## Qué (en idioma de negocio)

<1-3 frases: qué podrá hacer el usuario cuando esto esté hecho, con el vocabulario del mapa.>

## Criterios de aceptación

<Verificables, con datos reales del negocio. Si necesitas más de tres, no es directo.>

- **R1** — Cuando <situación>, <resultado observable>.
- **R2** — (caso límite) Cuando <situación rara>, <resultado>.

- **Requisitos del plano que esta unidad toca:** <los R-n del `planos.json` de la actividad
  que este cambio roza, LEÍDOS antes de escribir los criterios — contradecir un R-n aprobado
  nunca es directo: es mover el mapa (regla 14), y va por `feature.md` con su delta.>

## Cómo lo pruebas tú

<Lo escribe el padre ANTES de pedir la aprobación; es lo que el usuario tendrá delante al dar
el OK sobre la app corriendo. Máximo 5 filas.>

| # | Dónde | Qué haces | Qué deberías ver |
|---|---|---|---|
| 1 | <pantalla o menú> | <acción con un dato real suyo> | <lo que aparece> |

- **NO debe haber cambiado:** <lo de al lado que sigue igual>.

## Cómo (enfoque técnico, breve)

<Dónde vive ya esto y cómo se encaja ahí. Si no cabe en el módulo que le corresponde, PARA: eso
no es un directo, es un refactor o una feature. Las reglas de diseño están en
`01-constitucion/bias.md` y valen siempre: aquí solo lo específico de este cambio.>

## Verificación

- Comando(s) que deben salir en verde: `<comando de test>`
- **Nivel de test:** <el que demuestra ESTE cambio y ninguno más (ADR-015): unitario si es una
  regla, de integración si cruza una frontera, end-to-end solo si cruza la app entera.
  `unidad.py despachar` BLOQUEA si esta línea sigue sin rellenar.>
- Evidencia exigida al cerrar: output de tests + <capturas si hay UI>

## Contexto para el constructor (rutas desde el worktree)

1. Este fichero — tu contrato y tu plan
2. `../../docs/01-constitucion/bias.md` — con qué se construye y cómo se diseña
3. `<AGENTS.md del repo de código>` — comandos de build/test
4. <el módulo donde esto vive hoy, si existe>

## Plan de trabajo (marcar `[x]` inmediatamente al completar)

- [ ] 1. Test(s) que demuestren que esto NO existe aún, en ROJO · _Req: R1-R2_
- [ ] 2. Implementar hasta que pasen, SIN tocarlos · _Depende de: 1_
- [ ] 3. Tests del **área tocada** (ADR-016) + lint en verde; evidencia pegada en `hallazgos.md` · _Depende de: 2_
- [ ] 4. Commit, push y PR con `NNN-slug` en el título (sin `gh`: la rama commiteada) · _Depende de: 3_
- [ ] 5. **PARAR.** Devuelve el control al padre con el enlace del PR y la evidencia. · _Depende de: 4_

## Reglas del constructor (fijas)

- Escribes SOLO en tu worktree. En el meta-repo escribes dos cosas y sin git jamás:
  `../../docs/05-trabajo/NNN-slug/hallazgos.md` y las casillas `[x]` de este plan.
- Lo que no está en `ficheros:` no se edita: lo propones en `hallazgos.md` y lo aplica el padre.
- **Si el cambio crece, toca un hotspot o hay que mover el mapa → PARA y devuelve la tarea.**
  Eso ya no es un directo (escalada de `runbooks/directo.md`).
- No mergeas tú: tu trabajo termina en el PR abierto. Prohibido `git stash`.
- **Sin gasto real:** tus tests NO llaman a servicios de pago. Toda llamada a un proveedor
  externo va con mock (`unittest.mock.patch`, `responses`, `respx`, `vcr`, `jest.mock`) o contra
  un sandbox declarado en `docs/01-constitucion/bias.md`; las credenciales de pago no entran en
  tu entorno. Lo comprueba `lint_ci.py` (`gasto-real`) antes del merge.
- Nada está "hecho" sin el output del check en verde. Evidencia, no afirmación.

## Definición de hecho

1. Los R* en verde, con los tests intactos desde que se escribieron.
2. Tests del **área tocada** (ADR-016) + lint en verde (línea base medida contra la
   principal EN ESE MOMENTO).
3. Evidencia pegada en `hallazgos.md` y PR abierto (o rama commiteada), y PARADA.
