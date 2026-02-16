#!/bin/bash
# Install Docker and Docker Compose on the hosting server (Ubuntu or Debian).
# Run as root or with sudo. Adds the deploy user to the docker group so
# WordPress Docker deployments work.
#
# Usage (on server):
#   curl -sSL https://raw.githubusercontent.com/.../install_docker.sh | sudo bash
#   # or
#   sudo bash install_docker.sh
#   # or from your machine:
#   scp deployment/scripts/install_docker.sh deploy@SERVER:/tmp/ && ssh deploy@SERVER 'sudo bash /tmp/install_docker.sh'

set -e

DEPLOY_USER="${1:-deploy}"

echo "▶ Installing Docker and Docker Compose (for WordPress containers)..."

apt-get update -qq
apt-get install -y ca-certificates curl

install -m 0755 -d /etc/apt/keyrings
if [ -f /etc/os-release ]; then
  . /etc/os-release
  if [ "$ID" = "debian" ]; then
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  else
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  fi
else
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
fi
chmod a+r /etc/apt/keyrings/docker.asc

apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

if id "$DEPLOY_USER" &>/dev/null; then
  usermod -aG docker "$DEPLOY_USER"
  echo "✅ User $DEPLOY_USER added to group docker"
fi

systemctl enable docker
systemctl start docker

mkdir -p /var/lib/hosting-manager/wordpress-docker
chown "$DEPLOY_USER:$DEPLOY_USER" /var/lib/hosting-manager/wordpress-docker 2>/dev/null || true

echo "Docker: $(docker --version)"
echo "Compose: $(docker compose version 2>/dev/null || true)"
echo "✅ Docker and Docker Compose installed. If $DEPLOY_USER was added to docker, they may need to log out and back in (or restart the hosting-manager service) for group to apply."
