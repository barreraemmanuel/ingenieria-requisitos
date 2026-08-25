# Runbook · PRIMER DESPLIEGUE (el usuario nunca ha desplegado nada)

**Cuándo:** dice "quiero que esto lo use mi gente", "quiero verlo en internet" o "¿cómo lo
pongo en marcha?" — y no hay `docs/conocimiento/plano-deploy.md`.
**Quién:** el rol DEPLOY (`roles.md`). Un rol = una sesión.
**Resultado:** la ficha §3bis de `conocimiento/plano-deploy.md` rellena y `lint_deploy.py` en
verde. A partir de ahí, todos los despliegues siguientes son `runbooks/deploy.md`.

> La entrevista normal del rol (`roles.md`) pregunta "¿cómo se despliega hoy?". Si el usuario
> no ha desplegado nunca, esa pregunta no tiene respuesta: se empieza por aquí, que pregunta
> por su negocio y deduce lo técnico.

## 1 · La única pregunta que él sabe responder

**«¿Quién tiene que poder usar esto?»** De ahí cae la etapa sin que nadie sepa qué es un VPS.

| Responde… | etapa | Qué implica | Coste |
|---|---|---|---|
| "solo yo, en mi ordenador" | `local` | se apaga cuando apagas el ordenador; nadie más entra | 0 |
| "la gente de mi oficina" | `lan` | un ordenador que no se apague; solo desde esa red | 0 (la luz) |
| "cualquiera con el enlace" | `internet` | servidor + dominio + copias + auditoría de seguridad | de pago, mensual |

**No se sube de etapa por gusto.** Si con `local` le vale, se queda en `local`: cada peldaño
añade cosas que hay que mantener. Subir de etapa después es una unidad tipo `migracion`.

## 2 · Qué hace falta para la etapa que eligió

| | `local` | `lan` | `internet` |
|---|---|---|---|
| Dónde corre | su ordenador | un ordenador encendido de la oficina | máquina alquilada |
| Cómo entra la gente | no entra | la dirección interna de ese ordenador | un dominio |
| Copias de seguridad | las suyas | copia a otro disco | copia FUERA de esa máquina |
| Auditoría de seguridad | no | recomendable | obligatoria antes de salir |

## 3 · Si eligió `internet`: la receta de serie, o se investiga HOY

**Primero, la opción de serie** (ADR-032): `runbooks/deploy-vps-docker.md` — un VPS de unos
4 €/mes con Docker, Cloudflare delante, errores en un Bugsink propio, salud vigilada desde
fuera y copia diaria de la base de datos, guiada paso a paso y con sus precios fechados. Se
le ofrece antes que nada: tener un camino por defecto es lo que evita que cada proyecto
improvise el suyo. No es obligatoria.

**Si no le encaja, se investiga.** El método **no trae más proveedor ni precio que los
fechados de esa receta**: envejecen. Se abre una unidad tipo
`investigacion` (o se investiga en la sesión, si es corto) y se aplica la regla 11 de
`AGENTS.md`: doc oficial, con fuente y fecha. Se le traen **tres** opciones y elige él:

| opción | qué es, en cristiano | precio/mes | quién lo mantiene |
|---|---|---|---|
| <A> | <una frase> | <precio, con fecha de consulta> | <él / el proveedor> |

Se decide con él y **queda una decisión `DP-NNN` en `docs/decisiones/`**: qué se eligió, qué se descartó y
por qué. Es la decisión más cara de deshacer del proyecto.

## 4 · Lo que no puede hacer un agente (manos humanas)

Se le dan como pasos, uno a uno, y se espera a que confirme cada uno. No se le pide que
"configure" nada: se le dice dónde hace clic y qué apuntar.

| # | Paso | Quién | Dónde queda |
|---|---|---|---|
| 1 | Crear la cuenta del proveedor y pagar | el usuario | — |
| 2 | Comprar el dominio | el usuario | — |
| 3 | Apuntar el dominio a la máquina | el agente le dicta, él pega | plano de deploy |
| 4 | Guardar contraseñas y claves | el usuario | `.private/` (**jamás** en docs ni en git) |

## 5 · Escribir el plano

Se rellena `docs/conocimiento/plano-deploy.md` desde `plantillas/plano-operativo.md`
(`rol: deploy`), **con la ficha §3bis completa**: `etapa`, `camino`, `vuelta_atras`, `datos`,
`vigilancia`. Si la app no guarda datos propios (un mod, una app sin servidor), `datos` es
`SIN DATOS` y eso es una respuesta válida, no un hueco.

## 6 · Ensayo en falso, antes de que haya nada que perder

Se despliega **una vez** con la app vacía y se hace la vuelta atrás entera, tal y como está
escrita en `vuelta_atras`. Es el único momento de la vida del proyecto en que equivocarse no
cuesta nada. Si el camino escrito no funciona, se corrige el plano AHORA.

## 7 · A partir de aquí, el camino normal

`python3 docs/00-metodo/scripts/lint_deploy.py` y `runbooks/deploy.md`. Este runbook no se
vuelve a usar: solo se repite si el proyecto cambia de etapa o de máquina.
