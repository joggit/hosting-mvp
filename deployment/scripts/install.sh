#!/bin/bash

# Hosting Manager - Single Command Installer
# Usage: ./install.sh SERVER USERNAME REPO_URL

set -e  # Exit on error

SERVER=$1
USERNAME=$2
REPO_URL=$3

if [ -z "$SERVER" ] || [ -z "$USERNAME" ] || [ -z "$REPO_URL" ]; then
    echo "Usage: ./install.sh SERVER USERNAME REPO_URL"
    echo "Example: ./install.sh 75.119.141.162 deploy https://github.com/user/repo.git"
    exit 1
fi

echo "=========================================="
echo "🚀 Installing Hosting Manager"
echo "=========================================="
echo "Server: $SERVER"
echo "User: $USERNAME"
echo "Repo: $REPO_URL"
echo ""

# Create the full installation script
ssh root@$SERVER 'bash -s' << ENDSSH
set -e

echo "============================================"
echo "Starting installation..."
echo "============================================"

# 1. Update system
echo "[1/10] Updating system..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y curl wget git vim ufw fail2ban

# 2. Create user if doesn't exist
echo "[2/10] Setting up user ${USERNAME}..."
if id "${USERNAME}" &>/dev/null; then
    echo "User ${USERNAME} already exists"
else
    adduser --disabled-password --gecos '' ${USERNAME}
fi

# Always ensure sudo access
usermod -aG sudo ${USERNAME}
echo '${USERNAME} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/${USERNAME}
chmod 440 /etc/sudoers.d/${USERNAME}

# 3. Setup SSH keys
echo "[3/10] Setting up SSH keys..."
mkdir -p /home/${USERNAME}/.ssh
cat /root/.ssh/authorized_keys > /home/${USERNAME}/.ssh/authorized_keys 2>/dev/null || echo "No root keys to copy"
chmod 700 /home/${USERNAME}/.ssh
chmod 600 /home/${USERNAME}/.ssh/authorized_keys 2>/dev/null || true
chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}/.ssh

# 4. Setup firewall
echo "[4/10] Configuring firewall..."
ufw --force enable
ufw allow OpenSSH
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5000/tcp

# 5. Setup fail2ban
echo "[5/10] Setting up fail2ban..."
cat > /etc/fail2ban/jail.local << 'F2B'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
F2B

systemctl enable fail2ban
systemctl restart fail2ban

# 6. Install Node.js
echo "[6/10] Installing Node.js..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

# Install PM2 and pnpm
npm install -g pm2 pnpm

# Setup PM2 startup
env PATH=\$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u ${USERNAME} --hp /home/${USERNAME}

echo "Node.js: \$(node --version)"
echo "npm: \$(npm --version)"
echo "PM2: \$(pm2 --version)"
echo "pnpm: \$(pnpm --version)"

# 7. Install Python
echo "[7/10] Installing Python dependencies..."
apt-get install -y python3 python3-pip python3-venv nginx sqlite3
pip3 install --break-system-packages Flask==3.0.0 Flask-CORS==4.0.0

# 8. Deploy application
echo "[8/10] Deploying application..."
mkdir -p /opt/hosting-manager
chown ${USERNAME}:${USERNAME} /opt/hosting-manager

# Clone repo
if [ -d "/opt/hosting-manager/.git" ]; then
    cd /opt/hosting-manager && git pull origin main
else
    su - ${USERNAME} -c "git clone ${REPO_URL} /opt/hosting-manager"
fi

# Install requirements
cd /opt/hosting-manager
pip3 install --break-system-packages -r requirements.txt

# Create directories
mkdir -p /var/lib/hosting-manager /var/log/hosting-manager /var/www/domains
chown -R ${USERNAME}:${USERNAME} /var/lib/hosting-manager /var/log/hosting-manager /var/www/domains

# Create systemd service
cat > /etc/systemd/system/hosting-manager.service << 'SERVICE'
[Unit]
Description=Hosting Manager API
After=network.target

[Service]
Type=simple
User=${USERNAME}
Group=${USERNAME}
WorkingDirectory=/opt/hosting-manager
Environment="PYTHONUNBUFFERED=1"
Environment="PATH=/usr/bin:/usr/local/bin"
ExecStart=/usr/bin/python3 /opt/hosting-manager/app.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable hosting-manager
systemctl restart hosting-manager

sleep 5

# 9. Configure nginx
echo "[9/10] Configuring nginx..."
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/hosting-manager-api << 'NGINX'
server {
    listen 80 default_server;
    server_name _;

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        default_type text/html;
        return 200 '<!DOCTYPE html><html><head><title>Hosting Manager</title></head><body style="font-family:Arial;max-width:800px;margin:50px auto;padding:20px;"><h1>🚀 Hosting Manager</h1><p>API is running.</p><ul><li><a href="/api/health">Health</a></li><li><a href="/api/status">Status</a></li><li><a href="/api/domains">Domains</a></li></ul></body></html>';
    }
}
NGINX

ln -sf /etc/nginx/sites-available/hosting-manager-api /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# 10. Verify
echo "[10/10] Verifying installation..."
systemctl is-active hosting-manager
curl -f http://localhost:5000/api/health

echo ""
echo "============================================"
echo "✅ Installation Complete!"
echo "============================================"
echo ""
echo "🎯 Installed:"
echo "  ✓ Node.js \$(node --version)"
echo "  ✓ PM2 \$(pm2 --version)"
echo "  ✓ Python 3"
echo "  ✓ Nginx"
echo ""
echo "📡 Access:"
echo "  SSH:  ssh ${USERNAME}@${SERVER}"
echo "  API:  http://${SERVER}:5000/api/health"
echo "  Web:  http://${SERVER}"
echo ""
echo "🔧 Commands:"
echo "  Status:  ssh ${USERNAME}@${SERVER} 'sudo systemctl status hosting-manager'"
echo "  Logs:    ssh ${USERNAME}@${SERVER} 'sudo journalctl -u hosting-manager -f'"
echo "  PM2:     ssh ${USERNAME}@${SERVER} 'pm2 list'"
echo ""

ENDSSH

echo ""
echo "=========================================="
echo "✅ Remote installation complete!"
echo "=========================================="
echo ""
echo "Testing from local machine..."
curl http://${SERVER}/api/health
echo ""
echo ""
echo "🎉 All done! Your hosting manager is ready."
