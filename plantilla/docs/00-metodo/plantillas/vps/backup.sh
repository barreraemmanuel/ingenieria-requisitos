#!/bin/sh
# Copia diaria de la base de datos a Google Drive, cifrada, con rotación y latido.
# Vive en el VPS (/srv/app/backup.sh) y lo lanza el cron de las 03:00 que puso
# servidor-preparar.sh; también lo lanza a mano `vps.py backup` (paso 12 del runbook).
#
# Falla en ROJO a la primera: `set -eu` corta el script, el latido NO se manda y Better
# Stack avisa. Un backup que falla en silencio es peor que no tener backup.
set -eu

cd /srv/app
. /srv/app/.env
# rclone lee su configuración de aquí; el remote es `crypt`, así que sale cifrado.
export RCLONE_CONFIG=/srv/app/.config/rclone/rclone.conf

FECHA=$(date +%Y-%m-%dT%H%M)
VOLCADO="/srv/app/copias/${POSTGRES_DB}-${FECHA}.dump"

echo "[$(date -Is)] volcando ${POSTGRES_DB}"
# -Fc: formato comprimido de Postgres, el que entiende pg_restore.
docker compose -f /srv/app/compose.prod.yml exec -T db \
	pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" > "$VOLCADO"

echo "[$(date -Is)] subiendo a ${RCLONE_REMOTE} (remote cifrado)"
# El remote es de tipo `crypt`: lo que sale de esta máquina va cifrado, y en tu Drive
# ni el nombre del fichero es legible.
rclone copy "$VOLCADO" "${RCLONE_REMOTE}/"

echo "[$(date -Is)] rotando: fuera lo de más de 30 días"
rclone delete "${RCLONE_REMOTE}/" --min-age 30d
find /srv/app/copias -name '*.dump' -mtime +7 -delete

echo "subido: $(basename "$VOLCADO")"
echo "$(basename "$VOLCADO")" > /srv/app/.ultimo-backup

if [ -n "${HEARTBEAT_URL:-}" ]; then
	# El latido solo se manda si TODO lo anterior salió bien: es la prueba de vida.
	curl -fsS -m 10 "$HEARTBEAT_URL" >/dev/null && echo "latido enviado"
fi
