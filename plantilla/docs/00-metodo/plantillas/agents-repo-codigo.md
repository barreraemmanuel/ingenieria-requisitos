# AGENTS.md del REPO DE CÓDIGO — plantilla

> Esto NO es el AGENTS.md del meta-repo (ese ya existe en la raíz del workspace y es el
> router del padre). Esto es el fichero que vive **dentro del repo de código**, en `main/`, y
> lo escribe la PRIMERA unidad del esqueleto andante, cuando ya se sabe con qué se construye.
>
> Por qué es obligatorio: el método dice "suite en verde" y "lanzar una instancia para que el
> usuario la pruebe" en cada cierre de cada unidad. Sin los comandos exactos escritos aquí,
> esos pasos no los puede ejecutar un agente fresco, y cada constructor se los inventa.
> Regla que lo exige: `runbooks/planificacion.md`, regla 6.
>
> Copia lo de debajo de la línea al `AGENTS.md` del repo de código y rellena los huecos con
> comandos **literales y copiables**, probados en esta máquina. Ni "instala las dependencias"
> ni "corre los tests": el comando exacto.

---

# AGENTS.md — <nombre del repo de código>

Repo de código de «<título del proyecto>». Se orquesta desde su meta-repo (la carpeta padre;
ver `repos.yaml` allí). Aquí solo vive el código de la aplicación.

## Comandos (literales, probados; los usa el método en cada cierre)

| Para… | Comando |
|---|---|
| Levantar el entorno desde cero | `<comando>` |
| Correr la suite completa | `scripts/ci/full-suite` |
| Correr los linters | `scripts/ci/lint` |
| Lanzar una instancia para que la use el usuario | `<comando>` → `<URL o cómo se abre>` |
| Comprobación de seguridad | `scripts/ci/security` |
| Parar / limpiar | `<comando>` |

### Solo si los planos declaran `pruebas_e2e`

<Conserva este bloque entero —tabla y reglas— solo en ese caso. Sin `pruebas_e2e`, bórralo
entero: no se crean usuarios, scripts ni obligaciones E2E por ser una app con usuarios.>

| Para… | Comando |
|---|---|
| Preparar identidades y datos E2E | `scripts/ci/provision-e2e` |
| Correr solo los end-to-end | `scripts/ci/e2e` |

- Documenta los aliases sintéticos estables como
  `<maría-operadora · rol operadora · organización norte>`; nunca emails de acceso,
  contraseñas ni tokens.
- `scripts/ci/provision-e2e` es explícito e idempotente; solo admite local/test/E2E, verifica
  además una base, tenant o instancia inequívocamente de pruebas y rechaza producción antes
  de escribir. Ningún seed se ejecuta al arrancar, migrar o desplegar ni imprime credenciales.
- La secuencia es única: `scripts/ci/full-suite` invoca `scripts/ci/e2e`; `e2e` invoca
  `scripts/ci/provision-e2e` antes de ejecutar los tests y propaga cualquier rojo.

## Qué necesita esta máquina

<Lo que hay que tener instalado, y la versión. Si algo de aquí no aparece en verde en
`docs/00-metodo/scripts/doctor.py` del meta-repo, no es una dependencia: es un problema.>

## Estructura

<Dos o tres líneas: dónde vive cada cosa, para que el discovery de código de un agente sea
barato. Una funcionalidad vive en SU módulo.>

## Reglas de este repo

- Los secretos van en `.env` (fuera de git) y **el `.env` está en `.dockerignore`**: un
  secreto horneado en una imagen es un secreto publicado.
- Las dependencias de desarrollo y test están separadas de las de producción.
- Los tests se escriben antes que el código y no se debilitan para que pase la suite.
- Los scripts obligatorios de `scripts/ci/` —los tres base, cinco cuando se conserva el bloque
  E2E— preparan su entorno, usan herramientas fijadas y propagan cualquier rojo. Prohibido
  `|| true` o dar verde por no encontrar tests.
- La suite, el lint y la seguridad se ejecutan en local antes de fusionar; anota arriba los
  comandos probados para que cualquier agente pueda repetirlos.
- Solo si el proyecto pide CI remoto mediante `ci_remoto: sí` en `01-constitucion/bias.md`,
  crea `.github/workflows/tests.yml` para la suite en pull requests y
  `quality-security.yml` para lint y seguridad en paralelo en pull requests, al entrar en
  `main` y semanalmente. En ese caso, `.github/dependabot.yml` propone las
  actualizaciones normales.
  Las Actions externas van por SHA; los workflows propagan cualquier fallo.
