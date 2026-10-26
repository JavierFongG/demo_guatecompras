#!/usr/bin/env bash
# Preparación inicial del servidor (Ubuntu 24.04). Correr UNA vez como root:
#   ssh root@<servidor> 'bash -s' < deploy/server/bootstrap.sh
# Antes: agrega tu clave SSH al crear el servidor en Hetzner (se copia al usuario deploy).
set -euo pipefail

# Usuario sin privilegios para desplegar
id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh /home/deploy/gc
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh /home/deploy/gc
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
echo "deploy ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/systemctl" > /etc/sudoers.d/deploy

# SSH solo con clave, sin root
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh || systemctl restart sshd

# Actualizaciones de seguridad automáticas
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades
dpkg-reconfigure -f noninteractive -plow unattended-upgrades

# Docker
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy

# 2 GB de swap (margen al cambiar de versión del índice)
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "Listo. Entra como: ssh deploy@<servidor>  (root ya no puede entrar por SSH)"
