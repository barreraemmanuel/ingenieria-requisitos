#!/bin/sh
# Deja un VPS Ubuntu 24.04 recién alquilado listo para la receta de serie.
# NO se ejecuta a mano: lo manda `python3 docs/00-metodo/scripts/vps.py servidor preparar`
# por SSH (`ssh ... 'bash -s' < servidor-preparar.sh`), paso 7 del runbook.
#
# Es IDEMPOTENTE: se puede volver a lanzar tantas veces como haga falta sin romper nada.
# Hace cuatro cosas y ninguna más:
#   1. Docker Engine + Compose desde el repo apt OFICIAL
#      (https://docs.docker.com/engine/install/ubuntu/, consultado 2026-08-25)
#   2. Cortafuegos ufw: 22 abierto, y 80/443 SOLO desde los rangos publicados de Cloudflare
#      (https://www.cloudflare.com/ips-v4 y https://www.cloudflare.com/ips-v6)
#   3. /srv/app, que es donde vive todo
#   4. rclone y el cron diario del backup a las 03:00
set -eu

echo "== 1/4 · Docker (repo apt oficial)"
if ! command -v docker >/dev/null 2>&1; then
	apt-get update
	apt-get install -y ca-certificates curl gnupg
	install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
		-o /etc/apt/keyrings/docker.asc
	chmod a+r /etc/apt/keyrings/docker.asc
	echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
		> /etc/apt/sources.list.d/docker.list
	apt-get update
	apt-get install -y docker-ce docker-ce-cli containerd.io \
		docker-buildx-plugin docker-compose-plugin
else
	echo "   ya estaba instalado: $(docker --version)"
fi
systemctl enable --now docker

echo "== 2/4 · Cortafuegos: 80/443 solo desde Cloudflare"
apt-get install -y ufw curl iptables >/dev/null
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw --force enable

# ATENCIÓN, y es la trampa clásica de este montaje: Docker publica puertos escribiendo sus
# PROPIAS reglas en iptables, por delante de ufw. Un `ufw deny 80` no impide entrar al
# contenedor de Caddy. La única cadena que Docker respeta como del administrador es
# DOCKER-USER: ahí es donde se cierra de verdad el origen. Se deja en un script aparte
# porque hay que volver a aplicarlo en cada arranque (las cadenas no sobreviven al reboot).
mkdir -p /srv/app
cat > /srv/app/cortafuegos-docker.sh <<'CIERRE'
#!/bin/sh
# Deja pasar a los puertos 80 y 443 SOLO a los rangos publicados de Cloudflare.
# Lo aplica servidor-preparar.sh y lo repite el cron @reboot. Idempotente: vacía y rehace.
set -eu
iptables -F DOCKER-USER 2>/dev/null || iptables -N DOCKER-USER
for rango in $(curl -fsS https://www.cloudflare.com/ips-v4); do
	iptables -A DOCKER-USER -s "$rango" -p tcp -m multiport --dports 80,443 -j RETURN
done
iptables -A DOCKER-USER -p tcp -m multiport --dports 80,443 -j DROP
iptables -A DOCKER-USER -j RETURN

if command -v ip6tables >/dev/null 2>&1; then
	ip6tables -F DOCKER-USER 2>/dev/null || ip6tables -N DOCKER-USER
	for rango in $(curl -fsS https://www.cloudflare.com/ips-v6); do
		ip6tables -A DOCKER-USER -s "$rango" -p tcp -m multiport --dports 80,443 -j RETURN
	done
	ip6tables -A DOCKER-USER -p tcp -m multiport --dports 80,443 -j DROP
	ip6tables -A DOCKER-USER -j RETURN
fi
echo "origen cerrado: 80/443 solo desde los rangos de Cloudflare"
CIERRE
chmod +x /srv/app/cortafuegos-docker.sh
sh /srv/app/cortafuegos-docker.sh

echo "== 3/4 · /srv/app"
mkdir -p /srv/app/certificados /srv/app/copias /srv/app/.config/rclone
chmod 700 /srv/app/certificados /srv/app/.config/rclone

echo "== 4/4 · rclone y el cron del backup (03:00 cada día)"
if ! command -v rclone >/dev/null 2>&1; then
	curl -fsS https://rclone.org/install.sh | bash
else
	echo "   rclone ya estaba: $(rclone version | head -1)"
fi
cron_linea='0 3 * * * cd /srv/app && /bin/sh /srv/app/backup.sh >> /srv/app/copias/backup.log 2>&1'
# 03:00, una vez al día. Idempotente: se reescribe la tabla sin duplicar la línea.
reboot_linea='@reboot /bin/sh /srv/app/cortafuegos-docker.sh >> /srv/app/copias/cortafuegos.log 2>&1'
(crontab -l 2>/dev/null | grep -v -e 'backup.sh' -e 'cortafuegos-docker.sh' || true; \
 echo "$cron_linea"; echo "$reboot_linea") | crontab -

echo "OK · servidor preparado. Siguiente: paso 8 del runbook (vps.py cloudflare)."
