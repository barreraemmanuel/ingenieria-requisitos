#!/bin/sh
# Prueba que la copia de anoche SE PUEDE RESTAURAR. Sin esto, un backup es un fichero
# grande, no una copia de seguridad. Lo lanza `vps.py backup --probar-restauracion`
# (paso 13 del runbook), que además anota la fecha en la ficha §3bis del plano de deploy.
#
# Nunca toca la base de datos de verdad: baja el último volcado, lo restaura en una base
# TEMPORAL, cuenta las tablas que salieron y la borra.
set -eu

cd /srv/app
. /srv/app/.env
export RCLONE_CONFIG=/srv/app/.config/rclone/rclone.conf

TEMPORAL="${POSTGRES_DB}_prueba_restauracion"
TRABAJO=$(mktemp -d)
trap 'rm -rf "$TRABAJO"' EXIT

echo "[$(date -Is)] bajando el último volcado de ${RCLONE_REMOTE}"
ULTIMO=$(rclone lsf "${RCLONE_REMOTE}/" \
	--include '*.dump' | sort | tail -1)
if [ -z "$ULTIMO" ]; then
	echo "FALLO: no hay ningún volcado en ${RCLONE_REMOTE}. Lanza antes: vps.py backup" >&2
	exit 1
fi
rclone copy "${RCLONE_REMOTE}/${ULTIMO}" "$TRABAJO/"

compose="docker compose -f /srv/app/compose.prod.yml exec -T db"
echo "[$(date -Is)] restaurando ${ULTIMO} en la base temporal ${TEMPORAL}"
$compose psql -U "$POSTGRES_USER" -d postgres \
	-c "DROP DATABASE IF EXISTS ${TEMPORAL};"
$compose psql -U "$POSTGRES_USER" -d postgres \
	-c "CREATE DATABASE ${TEMPORAL};"
$compose pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$TEMPORAL" \
	< "$TRABAJO/$ULTIMO"

TABLAS=$($compose psql -U "$POSTGRES_USER" -d "$TEMPORAL" -tAc \
	"select count(*) from information_schema.tables where table_schema='public';")
echo "tablas restauradas: ${TABLAS}"

$compose psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE ${TEMPORAL};"

if [ "$TABLAS" -lt 1 ]; then
	echo "FALLO: la copia se restauró vacía. Revisa el paso 12 del runbook." >&2
	exit 1
fi
echo "OK · restauración de prueba correcta el $(date +%F) con ${ULTIMO}"
