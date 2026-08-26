# Runbook · sesión de SANIDAD (revisión de limpieza del workspace)

Rol: `roles.md` §SANIDAD. Checklist eje a eje: `auditoria-sanidad.md`. Decisión: ADR-031.
Actividad del mapa: `sanear-workspace`.

**Cuándo se abre:** cada 5 cierres o cada 14 días (lo cuenta `sanidad.py atraso`), antes de
publicar una versión del método, y cuando el usuario lo pide. Es una **sesión propia**: no se
mezcla con una unidad en obra, porque la mano que repara papeles no puede estar además
tocando código.

**Las dos manos, y la frontera entre ellas (G-2401):**

| | Papeles del meta-repo | Todo lo del código |
|---|---|---|
| Quién lo hace | `sanidad.py reparar`, aquí y ahora | una unidad de la ola, después |
| Qué es | lista CERRADA: archivar actas, reescribir rutas rotas con destino único, borrar generados | código muerto, tests, docstrings, dependencias, docs mal ubicadas, decisiones sin registrar |
| Quién decide | nadie: es mecánico y reversible | **el usuario**, en el visor de contratos |
| Cómo se deshace | un `git revert` del commit `sanidad: …` | como cualquier unidad |

---

## Paso 0 · Arranque: ¿toca?

```bash
python3 docs/00-metodo/scripts/sanidad.py atraso
```

`OK sanidad al día (N cierres, D días)` → no hace falta abrir la sesión. `WARN` (o «nunca se
ha pasado sanidad») → sigue. Este comando se ejecuta **a mano al arrancar sesión** hasta que
la petición hija `P-20260825-7f23b7f6` lo cablee en `lint_metodo.py`.

**Puerta:** la sesión de sanidad no se abre con trabajo sin guardar en ningún worktree. Se
comprueba con `python3 docs/00-metodo/scripts/lint_metodo.py` antes de tocar nada.

## Paso 1 · Medir (siempre lo primero)

```bash
python3 docs/00-metodo/scripts/sanidad.py medir
python3 docs/00-metodo/scripts/sanidad.py medir --detalle    # cuando algo sorprenda
```

Se lee la tabla entera antes de tocar nada, con `auditoria-sanidad.md` al lado. Tres cosas que
NO se pueden hacer aquí:

- dar por bueno un eje `NO_COMPROBADO` (G-2402: lleva su motivo y su `SALIDA:`);
- comparar «de memoria» con la última vez (G-2403: la comparación la hace el guardián contra
  el libro, y si no hay libro dice «primera pasada»);
- capturar nada todavía.

Los listados largos están en `.runtime/sanidad/<AAAA-MM-DD>/<eje>.txt`. El informe estable
para el tablero queda en `.runtime/sanidad/ultima.json` (esquema `sanidad/v1`).

## Paso 2 · Reparar papeles — la única puerta que escribe

```bash
python3 docs/00-metodo/scripts/sanidad.py reparar --simular
```

Se **lee** la simulación línea a línea. Cada `SIMULADO <eje> · <origen> → <destino>` es un
cambio concreto: si alguno no se entiende, se para y se mira el fichero. Cuando la lista está
entendida:

```bash
python3 docs/00-metodo/scripts/sanidad.py reparar
git status                       # se revisa lo movido y lo reescrito
git add docs/05-trabajo/archivo/actas docs/05-trabajo/ESTADO.md   # RUTAS EXPLÍCITAS
git commit -m "sanidad: archiva actas y arregla rutas rotas con destino único"
```

- El guardián **no ejecuta git**: el commit lo hace el padre, con rutas explícitas (nunca
  `git add -A`, `auditoria-metodo.md` check 7).
- `reparar` no toca jamás `main/`, `worktrees/`, `.private/`, `docs/02-flujos/planos/`,
  `docs/00-metodo/` ni ficheros de peticiones, unidades o bugs.
- Una ruta rota con dos candidatos **no se toca**: sale como hallazgo con la lista, y la
  decide una persona en el paso 3.
- `--solo papeles` / `--solo rutas` acotan la reparación cuando se quiere ir por partes.

## Paso 3 · Refutar, con el fichero delante

Antes de que nada salga de aquí, cada hallazgo del código se intenta **refutar**, uno por uno,
con las reglas de su eje en `auditoria-sanidad.md` §1. La pregunta no es «¿parece un
hallazgo?» sino «¿qué explicación inocente tiene esto?».

Los que no se sostengan se descartan en el sitio. Los que sobrevivan siguen. Un hallazgo que
llega al usuario y resulta ser un falso positivo cuesta más que diez hallazgos no encontrados:
es la confianza en el rol lo que se gasta.

## Paso 4 · Capturar lo del código como peticiones

```bash
python3 docs/00-metodo/scripts/sanidad.py capturar
python3 docs/00-metodo/scripts/sanidad.py capturar --eje codigo-muerto --incluir-media
python3 docs/00-metodo/scripts/peticion.py listar --estado capturada
```

Una petición por eje, autor `sanidad`, con cada hallazgo en formato `ruta:línea · qué · por
qué`. Es idempotente: si ya hay una petición viva de sanidad para ese eje, la **aclara** con
los hallazgos nuevos en vez de crear otra. Por defecto solo entra la confianza alta.

**Aquí termina la mano del guardián.** No se crea ninguna unidad, no se despacha nada.

## Paso 5 · El usuario decide (puerta obligatoria)

El padre abre el apartado de contratos de la web **en el mismo turno** en que pide decidir:

```bash
python3 main/web/abrir.py --workspace . --apartado contratos   # o el que declare AGENTS.md
```

Se le presenta cada petición en su idioma (`comunicacion.md`: esto es «la revisión de limpieza
del proyecto», no «sanidad»), con el número del eje y un ejemplo concreto. Acepta, rechaza o
pospone **cada una**. Lo rechazado se cierra con motivo; lo pospuesto se aparca con condición
de retorno (`peticion.py aparcar`).

## Paso 6 · La ola de sanidad

Lo aceptado se construye por el **cauce normal**, sin atajos:

```bash
python3 docs/00-metodo/scripts/unidad.py nueva <tipo> <slug> --desde <P-ID>
```

Una unidad por hallazgo aceptado, o un lote por eje **si y solo si** sus ficheros son
disjuntos de todo lo que está en vuelo. Respeta el tope de trabajo en vuelo como cualquier
otra: la ola es una cola, no una excepción.

## Paso 7 · Re-medir, anotar y contar

```bash
python3 docs/00-metodo/scripts/sanidad.py medir --anotar
```

Escribe la fila del día en `docs/05-trabajo/SANIDAD.md` (lo crea desde
`plantillas/sanidad.md` si no existe). Es lo **último**, para que la fila refleje el estado
después de reparar. Los ejes reparados deben decir `mejor N→M`; si alguno dice `EMPEORÓ`, se
para y se mira por qué antes de cerrar la sesión.

Después, la sección «Sanidad» de `docs/05-trabajo/ESTADO.md`, en tres líneas: fecha, qué se
reparó, qué peticiones esperan decisión.

```bash
git add docs/05-trabajo/SANIDAD.md docs/05-trabajo/ESTADO.md
git commit -m "sanidad: pasada de <AAAA-MM-DD>, libro y estado al día"
```

## Paso 8 · Parte al usuario

Una línea por mano, sin jerga (`comunicacion.md`):

> «He pasado la revisión de limpieza del proyecto. He archivado 5 documentos viejos y
> arreglado 14 enlaces rotos —todo eso se deshace con un solo paso atrás si no te gusta—.
> Hay 3 cosas del código que no toco sin que las decidas: te las he dejado abiertas en la web
> de contratos.»

---

## Si algo sale mal

| Qué ves | Qué haces |
|---|---|
| `reparar` movió algo que no debía | `git revert <commit sanidad:>`; abre un bug con el `SIMULADO` que lo anunció |
| un eje sale `NO_COMPROBADO` siempre | lee su `SALIDA:`: falta una herramienta, falta `--red` o falta el repo. No se cierra la sesión diciendo que ese eje está bien |
| `capturar` duplicó una petición | es un bug (R5 exige idempotencia): ciérrala como duplicada (`peticion.py duplicar`) y ábrelo |
| el guardián tarda más de un minuto | mide un eje cada vez con `--eje`; si sigue, es un bug de rendimiento |
| un hallazgo resultó falso ante el usuario | anótalo: la regla de refutación que faltaba es una mejora de `auditoria-sanidad.md`, y esa sí es una petición |
