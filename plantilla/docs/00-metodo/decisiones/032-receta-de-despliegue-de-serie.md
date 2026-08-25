# ADR-032 · El método trae UNA receta de despliegue de serie, con proveedores y precios FECHADOS

**Fecha:** 2026-08-25 · **Estado:** aceptada · Unidad 060 · Petición P-20260825-210b6223@1

## Contexto

ADR-011 §4 zanjó que el gate de despliegue comprueba que el despliegue está **definido**, no
**cómo** se hace, y con ello sacó del método la receta de una webapp autoalojada que estaba
aplicada a todos los proyectos. La frase que lo acompañaba —«el método deja de opinar sobre
proveedores y precios, que envejecen dentro de una plantilla»— pasó a `primer-despliegue.md`
§3 como una orden: *se investiga hoy, no se recita de memoria*, y se le traen tres opciones
al usuario.

Eso arregló el gate imposible y creó otro problema, medido en campo: quien dice «quiero que
esto lo use mi gente» recibe una sola pregunta, un encargo de investigación y ninguna
recomendación. El resultado es que **cada proyecto reinventa el despliegue**, cada uno de una
manera, y —porque investigar proveedores agota la sesión antes de llegar a lo importante— casi
ninguno termina con copias probadas, con los errores yendo a alguna parte ni con el origen
cerrado. El rol DEPLOY no tiene un camino que operar; tiene un formulario que rellenar.

La investigación del 2026-08-25 (cuatro lentes, solo fuentes oficiales) confirmó además que
la parte que envejece es **pequeña y acotada**: dos precios de VPS y los límites de dos planes
gratuitos. Todo lo demás de una receta razonable —Docker, Compose con `healthcheck`, un proxy
con TLS, `pg_dump` + rotación, restaurar de prueba, vigilar desde fuera— no caduca.

## Decisión

1. **El método trae UNA receta de serie, y solo una.** Es
   `runbooks/deploy-vps-docker.md` + `scripts/vps.py` + `plantillas/vps/` (seis ficheros):
   Cloudflare Free delante, VPS de 2 vCPU/4 GB con Docker Compose (app, Postgres, Caddy,
   Bugsink, autoheal), vigilancia externa gratuita y copia cifrada de la base de datos a
   Google Drive con restauración probada.
2. **La receta es una OPCIÓN, no la única.** `primer-despliegue.md` §3 la ofrece primero
   —porque tener una recomendación por defecto es lo que evita el despliegue improvisado— y
   sigue exigiendo las tres opciones investigadas si el usuario quiere otra cosa.
3. **Un proveedor o un precio solo puede escribirse con su fecha de consulta y su fuente
   oficial al lado.** Sin fecha y sin URL, no entra en el método.
4. **Los precios y los planes se revisan al publicar cada versión del método.** Quien publica
   comprueba la tabla de VPS y los límites de los planes gratuitos del runbook, y sube la
   fecha o corrige los números. Un precio caducado no es un fallo del runbook: es una tarea
   de publicación que no se hizo.
5. **Lo que ADR-011 §4 decidió SE MANTIENE, entero:** `lint_deploy.py` sigue comprobando las
   cinco casillas de la ficha §3bis (`etapa`, `camino`, `vuelta_atras`, `datos`, `vigilancia`)
   y **no** sabe —ni sabrá— cómo se despliega ningún proyecto. Lo que cambia es solo esto:
   que el método pueda ofrecer una receta con nombres y precios fechados. Un proyecto que
   despliega una app de móvil, un mod o un proceso por lotes pasa el gate exactamente igual
   que antes, sin tocar esta receta.
6. **La receta no monta ninguna CI remota** (integración continua en el servidor de otro).
   El despliegue lo conduce una persona desde su ordenador, con sus llaves en `.private/`, y
   ningún fichero del método crea un flujo automático en un servicio externo. Si un proyecto
   lo quiere, es una unidad aparte y una decisión suya (`DP-NNN`), no del método. El runbook
   lo dice con todas las letras en su paso 17.

## Consecuencias

- `primer-despliegue.md` §3 y `deploy.md` (precondición 1) ganan un enlace a la receta. Nada
  más de esos dos runbooks cambia.
- El método adquiere **deuda de mantenimiento fechada**: la tabla de VPS y los límites de los
  planes gratuitos del runbook envejecen y hay que mirarlos al publicar. Es el coste que se
  paga a cambio de que el usuario no tenga que investigar un mercado para poner su aplicación
  en internet. Si un día nadie revisa esa tabla, la nota «los precios caducan; mandan la web
  y el proveedor» es lo que evita que un número viejo se lea como una promesa.
- Se descarta hacer TODO Cloudflare por API: la regla de rate limiting y Bot Fight Mode del
  plan Free están documentadas por panel, así que el runbook las guía con clics en vez de
  apuntar a un endpoint que la documentación liga a Enterprise.
- Se descarta Cloudflare Tunnel (otra pieza y otro binario en el VPS), Traefik (más
  configuración que Caddy para el mismo TLS) y Bugsink con MySQL desde el día uno (dos
  motores de base de datos en 4 GB); los tres quedan documentados como el camino de subida
  cuando el proyecto crezca.
- La receta **no** sustituye ninguna de las precondiciones de `deploy.md`: ficha, gate, backup
  restaurado, OK del usuario y auditoría de seguridad antes de la primera salida a internet.

## Verificación

- `python3 -m unittest visor.tests.test_vps` → verde: comprueba que las plantillas cumplen el
  contrato operativo (cinco servicios vigilados, solo Caddy publica puertos, `pg_dump -Fc`,
  rotación, `pg_restore --clean --if-exists`), que el runbook lleva sus precios **fechados** y
  su sección «Fuentes», que ningún fichero de la receta propone una CI remota y que ningún
  secreto sale por la salida de `vps.py`.
- `python3 docs/00-metodo/scripts/lint_deploy.py` → sigue mirando exactamente lo mismo que
  antes de este ADR (las cinco casillas de la ficha §3bis): que siga sin nombrar `vps.py` lo
  comprueba también `test_vps.py`.
