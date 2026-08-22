---
rol: observabilidad | deploy
actualizado: YYYY-MM-DD
---

# Plano operativo · <OBSERVABILIDAD | DEPLOY>

> Resultado escrito de la **entrevista de arranque** del rol (ADR-008). Vive en
> `docs/conocimiento/plano-observabilidad.md` o `docs/conocimiento/plano-deploy.md`.
> Un rol = una sesión: sin este fichero, cada sesión nueva volvería a interrogar al usuario.
> Se entrevista UNA vez; las sesiones siguientes ARRANCAN leyendo este plano y solo
> re-preguntan si detectan drift (ver la última sección).
> **Ningún rol operativo actúa sin su plano escrito.**
> Lo escribe el padre en el rol correspondiente. Credenciales: JAMÁS aquí.

## 1 · Qué se me preguntó y qué respondió el usuario

> Las preguntas de la ficha del rol (`docs/00-metodo/roles.md`), una por una, con la
> respuesta EN PALABRAS DEL USUARIO. Si no lo sabía, se escribe "no lo sabe" y pasa a la
> sección 2. Si dijo "me da igual, decide tú", se escribe eso y la decisión tomada.

| pregunta | respuesta del usuario | fecha |
|---|---|---|
| <pregunta 1> | <respuesta literal, o "no lo sabe" → ver §2> | YYYY-MM-DD |

## 2 · Lo que derivé yo (la información existía; el usuario no la sabía)

> Caso (a): la cosa EXISTE pero el usuario no sabe dónde ni cómo. El rol la deriva mirando
> código, configuración y máquina — y **se la confirma al usuario** antes de darla por buena.
> Sin evidencia no se apunta: cada fila lleva el fichero o el comando que lo demuestra.

| qué derivé | evidencia (fichero:línea o comando + su salida) | ¿confirmado por el usuario? |
|---|---|---|
| <p.ej. los logs de la app salen por stdout del contenedor> | `docker compose logs web` → <salida> | sí / pendiente (YYYY-MM-DD) |

## 3 · Lo que NO existe todavía

> Caso (b): la cosa NO EXISTE (no hay monitorización, no hay backups, no hay pipeline).
> **OBSERVABILIDAD no la construye** (su regla dura es que no arregla nada): cada carencia
> es un hallazgo que **pare una unidad**, y el padre la especifica en el rol constructor.
> **DEPLOY sí la construye**, pero por el canal normal: unidad con su especificación, nunca
> a mano y sin rastro.
> Punto de partida obligatorio: `01-constitucion/bias.md` — las piezas que ese fichero fije
> para vigilancia, registro de errores, copias y etapas (ejemplo del bias webapp: un monitor
> de disponibilidad + un recolector de errores, volcado diario de la base de datos con copia
> en otro sitio, etapas 0 local / 1 LAN / 2 internet). La entrevista parte de ahí, no de cero:
> se comprueba qué de eso está montado y qué no.

| carencia | por qué importa (una frase) | unidad propuesta | estado |
|---|---|---|---|
| <p.ej. no hay backup de la base de datos> | <un fallo de disco se lleva el negocio> | `NNN-backup-pg-dump-diario` (tipo `feature`) | propuesta / en ROADMAP / NNN asignado |

## 3bis · Ficha de despliegue (SOLO `rol: deploy` — la lee `scripts/lint_deploy.py`)

> Las cinco decisiones que tiene todo despliegue, se despliegue como se despliegue. El gate
> no las juzga: comprueba que están DECIDIDAS. Una casilla con el menú sin elegir o con un
> hueco `<...>` cuenta como no decidida y cierra el gate.

| clave | valor |
|---|---|
| `etapa` | <local — solo el usuario · lan — la gente de su sitio · internet — cualquiera con el enlace> |
| `camino` | <el comando o los pasos EXACTOS con que sube: `flyctl deploy`, `docker compose up -d`, `eas build`, "copiar la carpeta X a la máquina Y"> |
| `vuelta_atras` | <qué se deshace, con qué, y en cuánto tiempo> |
| `datos` | <qué se copia y adónde antes de tocar nada, y cuándo se restauró la última prueba — o `SIN DATOS` si esta app no guarda nada propio> |
| `vigilancia` | <dónde se mira si falla: fichero de registro, panel, comando> |

## 4 · Comandos y accesos

> Copiables y verificados: el que los escribe los ha ejecutado. Si un comando no se ha
> probado, se marca `[SIN VERIFICAR]`.
> **Credenciales, tokens, IPs privadas y datos personales JAMÁS aquí.**
> Viven en `.private/` y se referencian POR RUTA (`.private/<fichero>`), nunca por copia.

| para qué | comando / acceso | dónde se ejecuta | secreto que necesita |
|---|---|---|---|
| <ver el estado de los servicios> | `docker compose ps` | <máquina/etapa> | — |
| <entrar a la máquina> | `ssh <usuario>@<host>` | <desde dónde> | `.private/<fichero>` |

## 5 · Cuándo re-preguntar (señales de drift)

> El plano caduca por hechos, no por calendario. Si se cumple cualquiera de estas señales,
> la sesión NO sigue con el plano viejo: re-pregunta lo afectado, actualiza el fichero y
> sube la fecha del frontmatter.

- El proyecto **cambia de etapa** (local → LAN → internet) o de máquina.
- Aparece o desaparece un servicio de la definición de infra (o cambia el runtime).
- Una carencia de la §3 se resuelve (su unidad se cierra) — o aparece una nueva.
- Un comando de la §4 falla al ejecutarlo.
- Cambia quién da el OK, a quién se avisa, o por qué canal.
- El plano tiene más de <N> meses sin tocarse y nadie ha verificado nada desde entonces.

**Última verificación de que este plano sigue siendo cierto:** YYYY-MM-DD — <qué se comprobó>
