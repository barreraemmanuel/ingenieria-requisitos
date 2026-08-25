# Runbook · DEPLOY EN UN VPS CON DOCKER (la receta de serie)

**Cuándo:** el usuario eligió `internet` en `runbooks/primer-despliegue.md` §1 y quiere el
camino de serie: su aplicación en un servidor alquilado de unos 4 €/mes, detrás de
Cloudflare, con sus errores en un Bugsink propio, la salud vigilada desde fuera y una copia
diaria de la base de datos en su Google Drive que se ha probado a restaurar.
**Quién:** el rol DEPLOY (`roles.md`: un rol = una sesión). Los pasos de manos humanas los
hace **el usuario** con el agente dictándole; los de terminal los hace **el agente** con
`scripts/vps.py`, desde el ordenador del usuario.
**Resultado:** la aplicación corriendo en `https://<dominio>`, la ficha §3bis del
`conocimiento/plano-deploy.md` rellena con los valores de esta receta, `lint_deploy.py` en
verde, y una restauración de prueba fechada. A partir de ahí, cada despliegue siguiente es
`runbooks/deploy.md` con el `camino` que aquí queda escrito.

> **Esta receta es UNA opción, la de serie** (ADR-032). No es obligatoria: si el usuario
> prefiere otro proveedor u otra forma, se investiga y se decide con él como siempre
> (`primer-despliegue.md` §3). Lo que esta receta evita es que cada proyecto reinvente el
> despliegue desde cero y termine sin copias y sin protección.
>
> **Precios y planes CADUCAN.** Los de este documento se consultaron el **2026-08-25** y
> están fechados uno a uno. Se revisan cada vez que se publica una versión del método
> (ADR-032); si al leerlos no coinciden con la web del proveedor, mandan la web y el
> proveedor, no este fichero.
>
> **Aquí no hay CI remota.** Todo lo lanza una persona desde su ordenador.
> Este runbook no crea ni propone workflows de GitHub Actions.
> Si el usuario los pide algún día, es una unidad aparte.

## Lo que vas a montar (para que sepas dónde vas)

```
   navegador → Cloudflare (proxy, WAF, DDoS) → [VPS 2 vCPU/4 GB]
                                                 caddy    (TLS con certificado Origin CA)
                                                   ├── app      (tu Dockerfile, /health)
                                                   └── bugsink  (errores.<dominio>)
                                                 db       (Postgres 16, volumen)
                                                 autoheal (reinicia lo que se pone enfermo)
                                                 cron 03:00 → backup.sh → Google Drive cifrado
   fuera del VPS: Better Stack mira /health y escucha el latido del backup
```

## 0 · Requisitos previos (si falta uno, se para aquí)

| # | Qué | Quién lo tiene que traer |
|---|---|---|
| 1 | Un `Dockerfile` que arranca tu aplicación en el puerto 8000 | tu proyecto |
| 2 | Un `/health` que responde 200 y devuelve `{"commit": "<sha>"}` | tu proyecto |
| 3 | Docker corriendo en el ordenador del usuario (`docker --version`) | el usuario |
| 4 | Un dominio comprado (en cualquier registrador) | el usuario |

El `/health` con el commit dentro no es un capricho: es lo que permite comprobar que lo que
responde en internet es lo que se acaba de mandar. El `Dockerfile` recibe el commit como
`ARG COMMIT` — lo pasa `vps.py desplegar` — y la aplicación lo devuelve en `/health`.

## 1 · Cuenta de Cloudflare y dominio dentro

**Quién:** el usuario. **Dónde:** https://dash.cloudflare.com

1. Crea la cuenta (plan **Free**, 0 €/mes) y pulsa «Add a site» con tu dominio.
2. Cloudflare te da **dos servidores de nombres**. Cópialos y pégalos en tu registrador,
   sustituyendo los que hubiera.
3. Espera a que el dominio salga como **Active** (de minutos a unas horas).

**Apunta:** el dominio. **Dónde queda:** en el `.env` del paso 6 (variable `DOMINIO`).

## 2 · Qué te está dando el plan Free (y qué no)

| Protección | En Free | Se activa |
|---|---|---|
| DDoS L3-L7 sin medir | sí | sola, al estar el dominio detrás del proxy |
| WAF gestionado («Free Managed Ruleset») | sí | un clic (paso 8) |
| Bot Fight Mode | sí | un clic (paso 8) |
| Rate limiting | **1 regla** | un clic (paso 8) |
| Always Use HTTPS · TLS Full (strict) | sí | por script (paso 8) |
| Certificado de origen (Origin CA), 15 años | sí | paso 4 |

Consultado el 2026-08-25; las fuentes, al final.

## 3 · El token de Cloudflare (manos humanas)

**Quién:** el usuario. **Dónde:** dash.cloudflare.com → My Profile → API Tokens →
«Create Token» → «Create Custom Token».

Permisos, exactamente estos tres y ninguno más:

- **Zone:Read**
- **DNS:Edit**
- **Zone Settings:Edit**

En «Zone Resources», acota a *tu* zona (no a todas las de la cuenta).

**Apunta:** el token, que se enseña UNA sola vez.
**Dónde queda:** `.private/cloudflare.token`, un fichero con el token y nada más.
Jamás en docs, jamás en git, jamás pegado en el chat.

## 4 · El certificado de origen (manos humanas)

**Quién:** el usuario. **Dónde:** SSL/TLS → Origin Server → «Create Certificate».

1. Deja las opciones por defecto (RSA, `<dominio>` y `*.<dominio>`, 15 años).
2. Cloudflare enseña el certificado y la clave privada **una sola vez**.

**Apunta:** los dos bloques de texto.
**Dónde queda:** `.private/origin.pem` (el certificado) y `.private/origin.key` (la clave).
`vps.py desplegar` los sube al VPS; Caddy los usa y no pide certificados a nadie.

## 5 · Alquilar el VPS (manos humanas)

**Quién:** el usuario. Sirve cualquiera de los dos; con 2 vCPU y 4 GB caben la aplicación,
Postgres, Caddy y Bugsink.

| Proveedor | Plan | vCPU / RAM / disco | Precio/mes | Consultado | Detalle |
|---|---|---|---|---|---|
| Hetzner Cloud | **CX22** | 2 / 4 GB / 40 GB | ~**3,79 €** netos (IVA aparte) | 2026-08-25 | cortafuegos de red gratis |
| Hetzner Cloud | CX32 | 4 / 8 GB / 80 GB | ~6,80 € netos | 2026-08-25 | si se queda corto |
| OVHcloud | **VPS-1** | 2 / 4 GB / 40 GB NVMe | **3,81 €** | 2026-08-25 | anti-DDoS incluido; el cortafuegos hay que activarlo |
| OVHcloud | VPS-2 | 4 / 8 GB / 75 GB NVMe | 7,21 € | 2026-08-25 | si se queda corto |

Los precios **caducan**: se comprueban en el checkout antes de pagar.

1. Crea el servidor con **Ubuntu 24.04**.
2. Sube tu clave SSH pública al crearlo (si no tienes: `ssh-keygen -t ed25519`).
3. En Hetzner, deja además el cortafuegos de red con 22, 80 y 443; el fino lo pone el
   paso 7 dentro de la máquina.

**Apunta:** la IP pública (por ejemplo `203.0.113.10`) y el usuario de SSH.
**Dónde queda:** el `.env` del paso 6 (`VPS_IP`, `VPS_USUARIO`).

## 6 · La configuración de producción

**Quién:** el agente, preguntando; contesta el usuario.

```
python3 docs/00-metodo/scripts/vps.py env
```

Pregunta cada valor con su explicación, **inventa los secretos** (contraseña de Postgres,
claves de firma, contraseña del administrador de Bugsink) y escribe
`.private/produccion.env` en modo 0600. Ninguna contraseña sale por pantalla: si hace falta
leer una, se lee del fichero.

- `vps.py env --comprobar` dice qué variable falta, sin preguntar nada.
- `SENTRY_DSN` y `HEARTBEAT_URL` se quedan vacías a propósito: se rellenan en los pasos 10 y 11.

**Dónde queda:** `.private/produccion.env` (nunca en git).

## 7 · Preparar el servidor

**Quién:** el agente.

```
python3 docs/00-metodo/scripts/vps.py servidor preparar --dry-run   # primero, a ver qué hará
python3 docs/00-metodo/scripts/vps.py servidor preparar
```

Manda `plantillas/vps/servidor-preparar.sh` por SSH y deja el VPS con:

- **Docker Engine + Compose** desde el repositorio apt oficial;
- **`ufw`**: 22 abierto y todo lo demás cerrado;
- **el origen cerrado de verdad**: los puertos 80 y 443 solo aceptan los rangos publicados de
  Cloudflare, de modo que nadie puede saltarse el proxy yendo a la IP. Ojo con esto si lo
  tocas a mano: **Docker publica sus puertos por delante de `ufw`**, así que el cierre se
  escribe en la cadena `DOCKER-USER` de iptables (script `/srv/app/cortafuegos-docker.sh`,
  que se vuelve a aplicar en cada arranque). Un `ufw deny 80` a secas no cerraría nada;
- `/srv/app` con sus carpetas (`certificados/`, `copias/`, `.config/rclone/`);
- **rclone** instalado y el **cron diario de las 03:00** que lanza `backup.sh`.

Es idempotente: se puede relanzar tantas veces como haga falta.

## 8 · Cloudflare: lo que hace el script y los tres clics que te quedan

**Quién:** el agente primero, el usuario después.

```
python3 docs/00-metodo/scripts/vps.py cloudflare --dry-run
python3 docs/00-metodo/scripts/vps.py cloudflare
```

Por API (con el token del paso 3): localiza la zona, crea o actualiza el registro **A**
`<dominio>` y `errores.<dominio>` apuntando a la IP del VPS **con el proxy puesto**, y fija
`ssl=strict`, `always_use_https=on`, `min_tls_version=1.2` y `security_level=medium`.

Y te deja escritos los **tres clics** que el plan Free no da por API:

| # | Quién | Dónde | Qué |
|---|---|---|---|
| 1 | el usuario | Security → WAF → Managed rules | activar el «Free Managed Ruleset» |
| 2 | el usuario | Security → Bots | activar «Bot Fight Mode» |
| 3 | el usuario | Security → WAF → Rate limiting rules | crear la regla (100 peticiones / 10 s por IP, acción Block) |

**Apunta:** que los tres están activados, con la fecha.
**Dónde queda:** la ficha de despliegue de la unidad y el plano de deploy (paso 14).

## 9 · Desplegar

**Quién:** el agente.

```
python3 docs/00-metodo/scripts/vps.py desplegar --dry-run
python3 docs/00-metodo/scripts/vps.py desplegar
```

Construye tu imagen en el portátil, la lleva al VPS con `docker save` + `scp` (sin registro
que pagar; si prefieres un registro, cambia `APP_IMAGEN` por su ruta y sáltate el envío),
copia `compose.prod.yml`, el `Caddyfile`, el certificado y el `.env`, arranca todo, **espera
a que `/health` conteste 200** y **comprueba que el commit que responde es el que mandaste**.
El registro de cada despliegue queda en `.runtime/deploy/<fecha>-<sha>.log`.

Si algo sale mal: `vps.py desplegar --anterior` vuelve a la imagen de antes.

## 10 · Bugsink: tus errores, en tu servidor

**Quién:** el agente y el usuario a medias.

1. Entra en `https://errores.<dominio>` con el correo de `BUGSINK_SUPERUSER` y la contraseña
   que hay en `.private/produccion.env` (la inventó el paso 6; **el agente no la imprime**).
2. Crea un proyecto y copia su **DSN**.
3. Pega el DSN en `.private/produccion.env` (`SENTRY_DSN=`) y vuelve a lanzar `vps.py desplegar`.
4. **Prueba que llega:** provoca un error a propósito en la aplicación y compruébalo en
   Bugsink. Un canal de errores sin un error de prueba es una suposición.

Bugsink vale con cualquier SDK de Sentry: solo cambia el DSN. Arranca con **SQLite en un
volumen**, que sobra para uso pequeño; cuando crezca (miles de eventos al día), se le pone
MySQL con `DATABASE_URL` — está documentado en su web, y es el momento de subir de plan de VPS.

**Apunta:** que el error de prueba se vio, con la fecha. **Dónde queda:** la ficha de despliegue.

## 11 · Salud: tres capas, y una de ellas fuera del servidor

**Quién:** el agente monta las dos primeras; el usuario crea la cuenta de la tercera.

1. **Cada contenedor** tiene `healthcheck` en `compose.prod.yml`, y **autoheal** reinicia al
   que se ponga enfermo (Docker no reinicia por `unhealthy`: por eso está ese contenedor).
2. **`/health` de tu aplicación**, que mira la base de datos y devuelve el commit.
3. **Un vigilante FUERA del VPS**, porque si se cae la máquina entera nadie de dentro lo va a
   contar: **Better Stack** plan gratuito (10 monitores + 10 latidos, cada 3 minutos), que
   sí permite uso comercial. UptimeRobot gratis **no** vale: su plan libre excluye el uso
   comercial desde diciembre de 2024.
   - Monitor HTTP sobre `https://<dominio>/health`, alerta por correo.
   - Un **heartbeat** («latido») para el backup: copia su URL en `HEARTBEAT_URL` del `.env`.
     Si una noche el backup no corre, Better Stack avisa.

**Apunta:** las dos URLs. **Dónde queda:** `.private/produccion.env` y la casilla `vigilancia`
de la ficha §3bis.

## 12 · La copia de la base de datos, en tu Drive y cifrada

**Quién:** el usuario en Google Cloud (manos humanas), el agente el resto.

1. **client_id propio** (obligatorio: el compartido de rclone se retira en 2026):
   console.cloud.google.com → proyecto nuevo → habilita «Google Drive API» → «Credenciales»
   → «ID de cliente de OAuth» tipo *Aplicación de escritorio*.
   **Apunta** el ID y el secreto.
2. En el portátil: `rclone config` → remote nuevo tipo `drive`, con ese `client_id` y
   `client_secret`, **scope `drive.file`** (rclone solo verá lo que él mismo suba). Como el
   VPS no tiene navegador, se autoriza en el portátil con `rclone authorize drive` y se pega
   el token.
3. Encima, un remote **`crypt`** que envuelve al de Drive: lo que sale de la máquina va
   cifrado y en tu Drive ni el nombre del fichero es legible. Ese es el que va en
   `RCLONE_REMOTE` (por ejemplo `copias-cifradas:miapp`).
4. **Dónde queda:** `.private/rclone.conf`. `vps.py servidor preparar` lo copia al VPS.
5. Lánzalo a mano una vez: `python3 docs/00-metodo/scripts/vps.py backup`.

`backup.sh` hace `pg_dump -Fc`, sube con `rclone copy`, borra lo de más de 30 días
(`--min-age 30d`) y solo entonces manda el latido. Si algo falla, no hay latido y Better
Stack avisa.

Espacio: Drive gratis son 15 GB, que dan para meses de volcados de una aplicación pequeña.
Cuando no lleguen: Google One 100 GB por **1,99 €/mes**, o Backblaze B2 a **6,95 $/TB/mes**
con 10 GB gratis (ambos consultados el 2026-08-25; caducan).

## 13 · Restaurar de prueba (sin esto, no hay copia)

**Quién:** el agente.

```
python3 docs/00-metodo/scripts/vps.py backup --probar-restauracion
```

Baja el último volcado, lo restaura en una base de datos **temporal** con
`pg_restore --clean --if-exists`, cuenta las tablas que salieron y la borra. Después **anota
la fecha** en la ficha §3bis del plano de deploy. Un volcado que nadie ha restaurado es un
fichero grande, no una copia de seguridad.

## 14 · Rellenar la ficha §3bis del plano de deploy

**Quién:** el agente escribe, el usuario confirma. **Fichero:**
`docs/conocimiento/plano-deploy.md` (desde `plantillas/plano-operativo.md`, `rol: deploy`).

| clave | valor con esta receta |
|---|---|
| `etapa` | `internet` |
| `camino` | `python3 docs/00-metodo/scripts/vps.py desplegar` (runbook `deploy-vps-docker.md`) |
| `vuelta_atras` | `python3 docs/00-metodo/scripts/vps.py desplegar --anterior` — vuelve a la imagen previa en ~1 min |
| `datos` | `pg_dump -Fc` diario a las 03:00 al Drive cifrado `<RCLONE_REMOTE>`, 30 días de rotación · restauración de prueba: `<fecha del paso 13>` |
| `vigilancia` | Better Stack (monitor de `/health` + latido del backup), Bugsink en `errores.<dominio>`, `vps.py comprobar` |

Después: `python3 docs/00-metodo/scripts/lint_deploy.py` en verde.

## 15 · Ensayo de vuelta atrás (ahora, que no hay nada que perder)

**Quién:** el agente, delante del usuario.

1. Despliega una vez más (`vps.py desplegar`).
2. Ejecuta la vuelta atrás entera: `vps.py desplegar --anterior`.
3. Comprueba con `vps.py comprobar` que sigue todo en verde.
4. Vuelve a desplegar la versión buena.

Si el camino escrito no funciona, se corrige **ahora** y se corrige el plano.

## 16 · El día a día: actualizar y volver atrás

| Quiero… | Comando | Cuánto tarda |
|---|---|---|
| subir una versión nueva | `python3 docs/00-metodo/scripts/vps.py desplegar` | minutos |
| deshacerlo | `python3 docs/00-metodo/scripts/vps.py desplegar --anterior` | ~1 minuto |
| ver cómo está aquello | `python3 docs/00-metodo/scripts/vps.py comprobar` | segundos |
| copiar la base de datos ya | `python3 docs/00-metodo/scripts/vps.py backup` | segundos |
| comprobar que la copia sirve | `python3 docs/00-metodo/scripts/vps.py backup --probar-restauracion` | un minuto |

Cada despliegue sigue siendo un despliegue del método: `runbooks/deploy.md`, con su ficha,
su gate y el OK del usuario. Este runbook es el **cómo** de la casilla `camino`, no un atajo
que se salte el proceso.

## 17 · Lo que esta receta NO hace

- **No monta ninguna CI remota.** Ni GitHub Actions ni equivalente: el despliegue lo conduce
  una persona desde su ordenador, con sus llaves en `.private/`. Si el usuario quiere CI, se
  abre una unidad aparte y se decide allí (ADR-032).
- No compra dominios, no manda correo transaccional, no gestiona DNS fuera de Cloudflare.
- No escribe tu `Dockerfile` ni tu `/health`: son requisitos previos (paso 0).
- No sustituye la **auditoría de seguridad** obligatoria antes de la primera salida a
  internet (`primer-despliegue.md` §2, `deploy.md` precondición 4).

## Fuentes

Todas consultadas el **2026-08-25**. Precios y planes **caducan**: se revisan al publicar
cada versión del método (ADR-032).

| Qué | URL |
|---|---|
| Cloudflare · WAF gestionado en Free | https://developers.cloudflare.com/waf/managed-rules/ |
| Cloudflare · protección DDoS | https://developers.cloudflare.com/ddos-protection/ |
| Cloudflare · Bot Fight Mode | https://developers.cloudflare.com/bots/get-started/bot-fight-mode/ |
| Cloudflare · rate limiting (1 regla en Free) | https://developers.cloudflare.com/waf/rate-limiting-rules/ |
| Cloudflare · Origin CA y modos SSL | https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/ · https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/ |
| Cloudflare · permisos del token | https://developers.cloudflare.com/fundamentals/api/reference/permissions/ |
| Cloudflare · crear registro DNS por API | https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/create/ |
| Cloudflare · rangos de IP del proxy | https://www.cloudflare.com/ips-v4 · https://www.cloudflare.com/ips-v6 |
| Hetzner · precios de servidores | https://www.hetzner.com/cloud/regular-performance/ |
| OVHcloud · precios de VPS | https://www.ovhcloud.com/en-ie/vps/ |
| Docker · instalación en Ubuntu | https://docs.docker.com/engine/install/ubuntu/ |
| Docker Compose · healthcheck y depends_on | https://docs.docker.com/reference/compose-file/services/ |
| autoheal (Docker no reinicia por `unhealthy`) | https://github.com/willfarrell/docker-autoheal |
| Bugsink · instalación con Docker | https://www.bugsink.com/docs/docker-install/ |
| Bugsink · ajustes y alertas | https://www.bugsink.com/docs/settings/ · https://www.bugsink.com/docs/alerts/ |
| Better Stack · plan gratuito | https://betterstack.com/uptime |
| UptimeRobot · precios (free = no comercial) | https://uptimerobot.com/pricing/ |
| rclone · Drive (client_id propio, headless) | https://rclone.org/drive/ |
| rclone · remote cifrado | https://rclone.org/crypt/ |
| PostgreSQL · pg_dump y pg_restore | https://www.postgresql.org/docs/current/app-pgdump.html · https://www.postgresql.org/docs/current/app-pgrestore.html |
| Google One · precios | https://one.google.com/about/plans |
| Backblaze B2 · precios | https://www.backblaze.com/cloud-storage/pricing |
