# Runbook · DEPLOY

**Cuándo:** llevar a una etapa real algo ya mergeado — primer arranque, actualización, subida de
etapa (`01-constitucion/bias.md`) y el despliegue de urgencia del paso 6 de `hotfix.md`.
**Origen:** el despliegue conserva una petición operativa evaluada y un enlace `deploy`; si no
nace de la petición de una unidad/hotfix, DEPLOY captura un P-ID antes de abrir la ficha.
**Quién:** el rol DEPLOY (`roles.md`: un rol = una sesión; el único con manos en la máquina
destino). El constructor jamás despliega; fuera de un despliegue, producción es de solo lectura.
**Plantilla:** `plantillas/despliegue.md` — una ficha POR despliegue, en la unidad que despliega
(`docs/05-trabajo/NNN-slug/despliegue.md`); para un hotfix vive como ficha lateral canónica en
`docs/bugs/NNN-slug/despliegue.md` y su ruta se enlaza desde la petición de deploy.
**Contrato de cierre:** etapa destino verificada en caliente con evidencia + ficha rellena +
anotado qué commit corre dónde, desde cuándo y quién lo puso.

## Precondiciones que BLOQUEAN (se comprueban antes de tocar la máquina)

1. **Plano de deploy escrito**: `docs/conocimiento/plano-deploy.md` con su ficha
   §3bis completa (`etapa`, `camino`, `vuelta_atras`, `datos`, `vigilancia`) — es lo que
   comprueba el gate del paso 3. Máquinas, comandos y quién da el OK salen de ahí, nunca de la
   memoria. Sin plano, lo primero de la sesión es la entrevista de arranque del rol
   (`roles.md`); y si el usuario **no ha desplegado nunca nada**, esa entrevista no tiene
   respuestas: se empieza por `runbooks/primer-despliegue.md`.
2. **Backup verificado = restaurado de prueba**, hecho AHORA (no vale el de anoche
   si hay migración de datos). El detalle no se repite aquí: `migracion.md` §Subir de etapa, paso
   1. Las dos evidencias —volcado y restauración— van pegadas en la ficha.
3. **OK explícito del usuario** sobre el comportamiento que va a salir, probado con
   sus ejemplos reales (`roles.md`, línea roja del modo novato). "Los tests pasan" no es su OK.
4. Antes de la PRIMERA salida a internet (etapa 2): unidad tipo `auditoria` de seguridad cerrada.

## Los pasos

1. **Abrir la ficha** desde `plantillas/despliegue.md`: fija `proceso: deploy`, `estado:
   preparada` y `peticiones: [P-ID@revision]`, además de commit, etapa, responsable, ventana,
   pasos, verificaciones y rollback. Enlázala con `peticion.py enlazar --tipo deploy --ref
   <ruta>/despliegue.md`; otro fichero no sirve como proceso canónico.
2. **Actualizar `main/` a `origin/main`.** Verificar que el commit que se pretende desplegar
   pertenece a esa rama. No se despliega un worktree ni una rama sin merge.
3. **Ejecutar el gate:** `python3 docs/00-metodo/scripts/lint_deploy.py`. Además del plano y
   la rama, ejecuta `main/scripts/ci/full-suite` y `main/scripts/ci/security` sobre el commit
   exacto que va a salir; guarda los outputs en `.runtime/pre-deploy/`. Un rojo bloquea.
4. **Crear y restaurar el backup de prueba.** Pegar ambas evidencias.
5. **Leer el plan en voz alta con el usuario:** qué sale, dónde, cuánto tardará y cómo se
   vuelve atrás. Obtener su autorización explícita para mutar esa etapa.
6. **Ejecutar por el camino declarado** en `plano-deploy.md`, nunca con comandos improvisados.
   Si el camino no cubre el caso, parar y crear una unidad normal para arreglarlo.
7. **Verificación técnica inmediata:** procesos, salud, migraciones, colas y errores.
8. **Verificación de negocio:** recorrer un flujo real de punta a punta con datos seguros.
9. **Verificación de vigilancia:** monitor en verde y un error inocuo visible en el registro
   indicado por `plano-observabilidad.md`.
10. **Decidir:** todo verde → pedir al usuario que pruebe; cualquier rojo → rollback.
11. **OK del usuario sobre la etapa real.** Sin ese OK, el despliegue no se
    declara correcto.
12. **Registrar:** commit, etapa, fecha, persona, duración y resultado en la ficha, el plano
    de deploy y `ESTADO.md`. Solo `estado: desplegado`, sin huecos y con el OK fechado, permite
    reconciliar como entrega; `vuelta_atras` cancela el proceso y abre su petición hija de bug.

## Qué se anota al terminar, y dónde

- **La ficha**: commit/versión, etapa, evidencias, resultado, fecha y quién.
- **`conocimiento/plano-deploy.md`**: la línea de verdad — qué commit corre en qué etapa, desde
  cuándo y quién lo desplegó (`migracion.md`, paso 6) — y se sube `actualizado:`.
- **`ESTADO.md`**: una línea con la etapa y el commit desplegado. Es fichero compartido: se
  escribe dentro del ritual de cierre, indivisible (`00-metodo/README.md` §Los rituales).
- **Al usuario se le cuenta aparte y en cristiano** (`00-metodo/comunicacion.md`): qué
  corre ahora y dónde, qué falta, y qué necesitas de él. Las fichas y los planos son para el
  método, no para él: nunca se le suelta el vocabulario del método por el chat.

## Si falla

- **Se decide en minutos, no en horas.** Disparan vuelta atrás: verificación en caliente en rojo,
  errores nuevos en el registro, o el usuario diciendo "esto no es lo que aprobé". Ante la duda se
  vuelve atrás: investigar se investiga en local, nunca con la etapa real coja.
- **Cómo:** el plan de vuelta atrás de la ficha, tal cual está escrito; si el despliegue migró
  datos, restaurando el backup de la precondición 2 (por eso se prueba ANTES).
- **Después:** el fallo se abre como `bug` con su ficha y su triaje, y el despliegue **no se
  reintenta** hasta que esa unidad cierre. La ficha queda con resultado "vuelta atrás" y su porqué.
