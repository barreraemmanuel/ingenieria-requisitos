# Runbook · CONTROL PLANE DE TEST Y EVIDENCIA

**Cuándo:** una prueba crea/muta datos, arranca un preview, construye una imagen o presenta output
como evidencia de un target. **Autoridad:** ADR-024 y `scripts/control_plane.py`.

## Orden obligatorio: identidad → guard → conexión

1. Deriva una identidad con valores estables del repositorio, unidad y run. No uses PID ni hora si
   necesitas reanudar el mismo run después de SIGKILL.
2. Usa sus derivados para DB, puerto, nombre/tag Docker, temporal y log. Nunca uses `latest`.
3. Construye el entorno del target y ejecuta `assert_safe_test_target` antes de crear pool, cliente,
   socket o migración. La única forma segura de envolver una API es `connect_if_safe(callback, env)`:
   ante un target rojo el callback queda sin invocar.
4. Tras arrancar un preview, consulta su endpoint de identidad y pasa el JSON a
   `identity.assert_preview_identity`. HTTP 200 por sí solo no identifica nada.

Ejemplo importable:

```python
from control_plane import RunIdentity, connect_if_safe

identity = RunIdentity("facturacion", "042-recalculo", "ci-17")
env = {"APP_ENV": "test", "DB_HOST": "localhost", "DB_NAME": identity.database()}
connection, target = connect_if_safe(connect_database, env,
                                     expected_namespace=identity.namespace)
```

Un host E2E remoto requiere `allow_hosts={"e2e.internal"}` exacto aportado por el operador o por
la configuración protegida del CI. El manifiesto no puede autorizar su propio host: `allow_hosts`
dentro de un target es inválido. Esa allowlist externa tampoco autoriza un entorno o nombre
productivos. Los errores y la caja negra redactan de forma estructural cabeceras de autenticación,
cookies, DSN, URL con `userinfo` y valores secretos incluso entre comillas; aun así, nunca pegues
`.env` ni manifiestos con contraseñas en `hallazgos.md`.

## Manifiesto CI

`scripts/ci/control-plane.json` contiene solo identidad, targets declarados y las rutas de los
artefactos de control:

```json
{
  "version": 1,
  "identity": {
    "repo": "facturacion", "unit": "042-recalculo", "run": "ci-17",
    "namespace": "<salida de identity>", "fingerprint": "<salida de identity>"
  },
  "targets": [{
    "env": "test", "host": "localhost", "database": "<database derivada>",
    "fingerprint": "<salida exacta de guard-test para este target>"
  }],
  "guard_script": "scripts/ci/control-plane-guard",
  "receipt": ".runtime/control-plane-receipt.json"
}
```

Genera la identidad con `python3 docs/00-metodo/scripts/control_plane.py identity ...`; genera la
huella del target ejecutando `guard-test` sobre el JSON de entorno. `lint_ci.py` vuelve a derivar
ambas: una huella escrita a mano o copiada de otro destino bloquea. El wrapper ejecutable
`scripts/ci/control-plane-guard` solo invoca ese guard canónico y `scripts/ci/provision-e2e` debe
invocarlo como primera orden sustantiva, con fail-fast activo, antes de provisionar o conectar.

Valida un target local con:

`python3 docs/00-metodo/scripts/lint_ci.py --repo worktrees/NNN --require-control-plane`

Para un host remoto autorizado desde configuración protegida, no edites el manifiesto; pasa la
confianza desde fuera:

`python3 docs/00-metodo/scripts/lint_ci.py --repo worktrees/NNN --require-control-plane --control-plane-allow-host e2e.internal`

## Evidencia causal

La evidencia de una corrección determinista se conserva como recibo JSON. Registra `version: 1`,
`claim`, `target_fingerprint`, `route`, `test_scope`, las métricas de presupuesto y exactamente
tres `runs`: versión antigua falla, versión nueva pasa y mutante deliberado falla. Cada run incluye
`phase`, la misma huella, `passed` booleano real, `command`, `exit_code` y el SHA-256 del output.
Una cadena como `"false"`, un comando ausente, un exit code contradictorio, otra huella o un scope
menor bloquean.

El manifiesto CI consume el recibo indicado por `receipt`. Para ligar además el cierre mecánico,
la ficha declara:

```yaml
control_plane: requerido
target_fingerprint: <huella esperada>
```

y se cierra con
`unidad.py cerrar NNN-slug --recibo-control-plane .runtime/control-plane-receipt.json`.
El script compara ruta, scope, target, causalidad y presupuesto con la política real de la unidad;
no basta con que el recibo se describa a sí mismo como válido.

No se mutan producción, servicios remotos ni datos compartidos para fabricar la contrapueba. El
mutante es una fixture local o una inversión controlada en un proceso efímero.

## Gates y presupuesto

| Ruta | Gates terminales | Pruebas | Primer artefacto | Cierre método | Overhead |
|---|---|---|---:|---:|---:|
| documental | revisión; sin merge/app | validación doc | 30 s | 2 min | 25% |
| prototipo | cancelación explícita; nunca cierre/entrega | smoke local | 5 min | 10 min | 20% |
| exprés | aviso + evidencia; sin OK de app | área | 30 s | 2 min | 20% |
| directo | merge + revisión + OK app | área | 5 min | 15 min | 20% |
| normal | merge + revisión + OK app | área + full | 15 min | 30 min | 25% |

Los límites no convierten un trabajo correcto en incorrecto: disparan una anotación y una decisión
de simplificar/escalar. Seguridad, pérdida de datos, permisos y dinero siempre usan el gate más
fuerte que exija el riesgo.

Un prototipo no pasa por `unidad.py cerrar`: aunque declare descarte, el comando se niega a
archivarlo o reconciliarlo como entrega. Se conserva la ficha en estado `descartada` y se cancela
cada proceso con `peticion.py marcar-proceso P-ID --proceso unidad:NNN-slug --estado cancelado`.

## Un lanzamiento interrumpido no deja rastro (bug 077)

`ejecucion.py lanzar` sostiene tres cosas a la vez mientras corre el harness: el proceso hijo,
los leases de la unidad y la ficha en solo lectura (0444). Si lo interrumpes —Ctrl-C, `kill`,
cierre de la terminal— atiende la señal y las suelta **en este orden**, deja un checkpoint
`interrumpido` en el recibo y muere con la misma señal (salida distinta de 0):

1. **el harness hijo**, entero: nace en su propio grupo de procesos, así que se termina el
   grupo completo (`taskkill /T /F` en Windows). Si ignora el cierre amable, se escala.
2. **los leases** de la unidad y de sus recursos, para que quede lanzable otra vez.
3. **la ficha**, que recupera su modo con la escritura del dueño puesta.

Lo que NINGÚN programa puede atender es `kill -9`, un corte de luz o la sesión cortada de
golpe: ahí no corre ningún manejador. Lo que queda es un lease a nombre de un PID muerto y,
detrás, un harness huérfano y la ficha congelada. El siguiente `lanzar` sobre esa unidad **no
lo atraviesa en silencio**: para y nombra el comando que lo deshace.

```
python3 docs/00-metodo/scripts/lease.py desbloquear NNN-slug
```

Retira los leases huérfanos, remata al harness que quedara vivo (comprobando la marca de
arranque, para no matar a otro proceso que herede el PID), devuelve la escritura a la ficha y
marca el recibo como recuperado. **Nunca le quita el lease a un dueño vivo**: con el proceso
todavía ahí, se niega y te dice cómo comprobarlo. Eso no es un rodeo del bloqueo de otra
sesión, es lo contrario.

En Windows la limpieza automática cubre MENOS de lo que parece, y conviene saber qué
exactamente. Solo las señales de consola —**Ctrl-C y Ctrl-Break**— llegan al manejador:
son las únicas que Windows entrega como tales, y por eso el hijo nace con
`CREATE_NEW_PROCESS_GROUP`. **Todo lo demás termina el proceso sin darle turno a nadie**:
`taskkill` (con o sin `/F`), el "Finalizar tarea" del administrador de tareas y cerrar la
ventana de la consola. Ahí no corre ningún manejador, igual que un `kill -9` en POSIX, y lo
que queda atrás es el lease huérfano, el harness vivo y la ficha congelada. Ese hueco lo
cubre `desbloquear`, y es la vía declarada para esa plataforma (R3).

## Suites de este método

Viven en la herramienta de ingeniería de requisitos (el repositorio que montó este workspace),
no aquí: `visor/tests/run-fast` (rápida) y `visor/tests/run-nightly` (nocturna/adversarial).
Ambas son herméticas. La nocturna recorre fixtures legacy→new→mutant, matrices de DSN y dos árboles
concurrentes sin abrir red, Docker ni bases reales. Desde un workspace no hay nada que ejecutar:
estos scripts se prueban en origen y llegan ya probados con cada actualización del método.
