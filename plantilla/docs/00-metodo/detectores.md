# Detectores: qué mira cada guardián, y qué no puede ver

> Una lista que nombra lo NO cubierto es la diferencia entre «cero defectos encontrados» y
> «cero defectos donde miramos». Este fichero existe para que, cuando algo se escape, haya
> dónde escribir *«esto se escapó porque no tenemos eje X»* — y para que no se vuelva a
> escapar por lo mismo.
>
> La pregunta obligada al cerrar un bug tiene ahora **cuatro** salidas, no tres: regla en el
> AGENTS.md del repo de código · `conocimiento/` · delta al mapa · **faltaba un guardián**.
> Antes preguntábamos por la instancia y nunca por la clase.

## Los guardianes

| Guardián | Qué mira | Qué NO puede ver |
|---|---|---|
| `lint_metodo.py` | La forma del workspace: árbol congelado, frontmatters, estados, archivo, coherencia worktrees↔unidades; y en el cierre, contra git del repo de código, que el `fusion:` anotado y el `commit` de un despliegue sean antecesores de la principal | Si lo escrito es **verdad** donde no hay git que lo contradiga: una unidad ya archivada puede creerse su propio `mergeada` (solo mira la cadena de estado), y de `hallazgos.md` no comprueba nada salvo la cosecha de las unidades ya archivadas — la firma del revisor y su recibo los exige `unidad.py cerrar`, no este linter |
| `lint_juntas.py` (entra con la 050) | Las juntas entre piezas: vocabulario código↔código↔prosa, tope de diff del carril directo, puertas duras con dueño | Juntas que nadie ha nombrado todavía. Solo mira las tres que están escritas en él |
| `lint_salidas.py` (entra con la 049) | Que un rechazo nombre el comando que desbloquea, o declare por qué no puede existir | Si el comando que nombra **funciona**. Comprueba que se diga algo ejecutable, no que ejecutarlo resuelva nada |
| `lint_cierre.py` (entra con la 045) | Que el parte de cierre cuadre con su evidencia: códigos de salida, ficheros citados, hashes, números contra el contrato | Si los tests que salieron en verde **prueban algo**. Un test vacuo produce un parte impecable |
| `lint_ci.py` | Que el contrato de CI del repo esté materializado y ejecutable | Que arranque de verdad. Valida la forma, no la corrida (P-20260820-ddfebe99) |
| `lint_deploy.py` | Las precondiciones del despliegue | La ficha de despliegue: **ni siquiera la lee**. Todo lo que protege se valida al cerrar, cuando producción ya está tocada |
| `canario.py` | Tres ejes: capacidad (% de la ventana del modelo), conducta (el mismo comando fallando igual N veces) y posición (a partir de `turnos_aviso`, 250 turnos del asistente, avisa de que cada turno cuesta más por su posición) | Calidad del trabajo. Una sesión que degrada **sin cruzar ningún umbral** —respuestas peores con la ventana a medias y menos de 250 turnos— no dispara nada. Y sin hook (Codex) solo mira cuando alguien lo ejecuta |
| `coste.py` (entra con la 048) | En qué se va el cupo, y qué ahorraría cortar cada N turnos | Dinero y reloj de pared. Y no emite nota compuesta a propósito: una suma ponderada puede subir mientras baja la dimensión que importa |
| `doctor.py` | Qué hay instalado en esta máquina | Qué hay instalado en la de otro. **Aquí no hay ninguna máquina Windows**, y por eso 037 y 039 se escribirían a ciegas |
| El **revisor fresco** | El diff contra el contrato, con ojos que no construyeron | Lo que el contrato no pidió. Y no puede saber si un número del parte está inventado — para eso está `lint_cierre.py` |
| El **OK del usuario sobre la app** | Que la cosa haga lo prometido, con datos reales suyos | Lo de al lado. Y valida **una** unidad: el 17-08 se firmaron quince entregas con la misma fecha, que es justo el agujero que cerró la 033 |
| El **hook `pre-push`** | Que ningún commit llegue a la principal sin origen persistente | Una frase que nunca salió del chat. El repositorio no puede detectarla: por eso AGENTS.md exige capturar como primera escritura |
| `caja_negra.py` | Los incidentes que alguien se acuerda de registrar | **Un agente atascado que no se declara atascado.** Registrar es manual y su análisis es posterior y semántico |

## Lo que ningún mecanismo de esta lista va a arreglar

- **Un test que pasa tanto si el comportamiento existe como si no.** La contraprueba del carril
  bug lo cubre; en normal y completo, hasta la 046, no lo cubría nadie.
- **Una sesión que degrada sin cruzar ningún umbral.** El canario mide tres ejes (capacidad,
  conducta, posición); lo que empeora por debajo de los tres es invisible.
- **Windows.** Ni una comprobación de este workspace corre en Windows. Tres bugs P0 del frente
  de Windows están diagnosticados leyendo código, no ejecutándolo.
- **Que el trabajo sea el correcto.** Todos estos guardianes comprueban que lo hecho esté bien
  hecho. Ninguno comprueba que fuera lo que había que hacer: eso lo decide el mapa, y el mapa
  lo aprueba una persona.

## Cómo se usa esta lista

1. Cuando algo se escapa, se busca aquí por qué. Si la causa **no** está en ninguna columna
   «qué NO puede ver», falta un eje: se añade la fila, y esa fila es trabajo futuro.
2. Al cerrar un bug, la cuarta salida de la pregunta obligada es *«faltaba un guardián»* y
   apunta aquí.
3. Alimenta el Modo D de ADR-026: lo que aquí queda escrito como no cubierto es la cola de la
   que salen los guardianes siguientes.

**Regla explícita, copiada de gentle-ai:** seguir añadiendo ejes, y mantener escrita la lista
de los que faltan.
