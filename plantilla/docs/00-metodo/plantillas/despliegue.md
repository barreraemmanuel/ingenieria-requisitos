---
proceso: deploy
estado: preparada | desplegado | vuelta_atras
peticiones: [P-ID@revision]
etapa: 0-local | 1-lan | 2-vps
commit: <sha corto o tag>
fecha: YYYY-MM-DD
---

# Despliegue · <NNN-slug> → etapa <N>

> Ficha de UN despliegue (el plan estable del proyecto vive en `conocimiento/plano-deploy.md`).
> La rellena el rol DEPLOY siguiendo `runbooks/deploy.md`, EN ORDEN: secciones 1-3 ANTES de tocar
> la máquina, 4-5 después. Vive en `docs/05-trabajo/NNN-slug/despliegue.md`; para un hotfix,
> vive como ficha lateral en `docs/bugs/NNN-slug/despliegue.md`. No se incrusta ni se mueve:
> esa ruta canónica permite que el inbox compruebe su contrato al cerrar.
> Credenciales, tokens, IPs privadas y datos personales JAMÁS aquí: viven en
> `.private/` y se referencian POR RUTA.

## 1 · Qué se despliega

- **Commit/tag:** <sha + título; ya en main y con la suite verde> · **origen:** <unidad | hotfix>
- **Etapa destino y máquina exacta:** <0 local | 1 LAN | 2 VPS> — <máquina, según el plano>
- **Qué cambia para el usuario, en una frase:** <...>
- **OK del usuario ANTES de salir:** PENDIENTE | OK (YYYY-MM-DD, <quién>) — probado con sus ejemplos
- **Suite completa sobre este commit:** <VERDE + ruta `.runtime/pre-deploy/full-suite.log`>
- **Seguridad sobre este commit:** <VERDE + ruta `.runtime/pre-deploy/security.log`>

## 2 · Backup verificado (restaurado de prueba)

- **Qué se copió y adónde:** <BD, ficheros subidos, config → destino que NO es la misma máquina>
- **Volcado — comando y salida:** `<pegada, no resumida>`
- **Restauración de prueba:** <dónde se restauró, qué se comprobó> — `<salida pegada>`

## 3 · Pasos manuales declarados y vuelta atrás (escritos ANTES de desplegar)

1. **Pasos** (lo no declarado NO se hace sobre la marcha): <variables nuevas, migración de datos,
   ficheros a copiar, servicios a reiniciar…>
2. **Vuelta atrás:** <qué se deshace, con qué comandos, en cuánto tiempo; si migra datos, incluye
   restaurar el backup de §2>

## 4 · Verificación en caliente (evidencia pegada, no afirmada)

- **Flujo real de negocio de punta a punta:** <cuál> — `<salida o captura>`
- **Vigilancia:** monitor en verde + un error inocuo llegando al registro — <evidencia>
- **Validación del usuario sobre la etapa desplegada:** PENDIENTE | OK (YYYY-MM-DD)

## 5 · Resultado

- **Resultado:** DESPLEGADO | VUELTA ATRÁS → <por qué + bug abierto NNN-slug>
- **Quién y cuándo:** <persona/sesión> — YYYY-MM-DD HH:MM
- **Anotado en `conocimiento/plano-deploy.md`:** <qué commit corre en qué etapa y desde cuándo>
