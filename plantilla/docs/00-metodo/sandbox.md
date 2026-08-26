# Control plane de ejecución

`scripts/ejecucion.py` es la entrada para lanzar el revisor fresco (y, opcionalmente, un
constructor en Codex o en sesión desatendida; el constructor por defecto es un subagente del
padre, ADR-033).
Recibe el ID de unidad y deriva el worktree y la rama por código: nunca se le pasa un cwd ni
un comando arbitrario, y nunca se invoca por `/bin/sh -c` (así se evitó el incidente que
motivó este control plane: un shell equivocado interpolando mal una variable y saliéndose del
worktree — ADR-022).

Desde la unidad 012, el lanzador **no impone ningún sandbox de sistema operativo**: no hay
`sandbox-exec`/Seatbelt en macOS, ni `bwrap`/`srt` en Linux, ni ninguna comprobación de
plataforma (Windows nativo funciona exactamente igual que cualquier otra). Se retiró porque
los incidentes reales que justificaban el control plane (cwd/entorno mal fijado) no tenían
relación con credenciales ni con el llavero del sistema, y el sandbox sí los bloqueaba —
fricción sin beneficio real. Ver el ADR sucesor de ADR-022 para el detalle de esa decisión.

## Flujo

1. Crea y despacha la unidad mediante `unidad.py`; su salida da los comandos exactos para
   Claude y Codex.
2. Elige harness, rol y, si hace falta, cada `--skill-tecnica` explícita.
3. El launcher verifica unidad, estado, carril, worktree, rama y gitdir por código
   (`resolver_worktree()`), y toma lease/fencing sobre la unidad y sus ficheros declarados
   (ADR-023): dos lanzamientos que compartieran recurso no pueden solaparse.
4. Arranca el harness con `subprocess.run(argv, cwd=worktree, env=...)` — `argv` siempre como
   lista, nunca interpolado por shell — y deja el recibo bajo `.runtime/ejecuciones/`, con
   checkpoints de lease, identidad y resultado del harness, y el estado Git inicial/final del
   worktree.

## La frontera de escritura real, hoy

Sin sandbox de SO, la única frontera es el `cwd` correcto (garantizado por código, no por el
sistema operativo) más la disciplina del contrato de la unidad — el mismo nivel de confianza
que ya tenía el carril `directo`, donde construye el padre sin ningún aislamiento. El
constructor puede escribir en cualquier ruta a la que su proceso tenga acceso normal de
usuario; lo que lo mantiene dentro de su worktree es el contrato, la revisión fresca antes de
mergear (ADR-017, obligatoria en todo carril que revisa) y el hecho de que el `cwd` de arranque
ya apunta al sitio correcto. Es un riesgo aceptado explícitamente, no un descuido.

Claude arranca en `--safe-mode` con `--permission-mode bypassPermissions` (sin esa bandera,
Write/Edit/Bash quedan denegados por defecto en headless). Codex recibe `HOME`/`CODEX_HOME`
efímeros con su `auth.json` copiado, y no carga configuración ni reglas de usuario
(`--ignore-user-config --ignore-rules`). Plugins, hooks, MCP y skills instalados no deciden el
proceso. Solo una skill técnica pedida por nombre se incorpora al encargo; las skills de
proceso conocidas se rechazan incluso si se solicitan. No se siguen symlinks ni aliases: el
nombre declarado en el frontmatter de `SKILL.md` debe coincidir con el solicitado.

Para código hostil o ejecución desatendida sin supervisión, esto NO es suficiente — hace falta
una frontera administrada por el dueño de la máquina (contenedor, VM, o similar). Este control
plane confía en que quien lo lanza confía en el harness y en el contrato de la unidad, igual
que ya confiaba el carril directo.
