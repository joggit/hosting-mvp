#!/usr/bin/env python3
"""
Hosting Manager - Fresh Server Installation
Includes: Node.js, PM2, Python, Nginx, Docker, Docker Compose, WordPress directories
"""

import argparse
import subprocess
import sys
import time
import os
from pathlib import Path


class Colors:
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"


def print_step(message):
    print(f"{Colors.GREEN}▶ {message}{Colors.NC}")


def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.NC}")


def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.NC}")


def print_warning(message):
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.NC}")


def print_header(message):
    print(f"\n{Colors.BLUE}{'='*60}{Colors.NC}")
    print(f"{Colors.BLUE}{message}{Colors.NC}")
    print(f"{Colors.BLUE}{'='*60}{Colors.NC}\n")


class FreshInstaller:
    """Handles fresh server installation with all fixes applied"""

    def __init__(self, server, username, repo_url, root_password=None):
        # Check if running as root (BAD!)
        if os.geteuid() == 0:
            print_error("DO NOT run this script with sudo!")
            print_error("Run as your regular user:")
            print(f"  python3 fresh_install.py --server {server} --user {username} ...")
            sys.exit(1)

        self.server = server
        self.username = username
        self.repo_url = repo_url
        self.root_password = root_password
        self.ssh_public_key = self.get_ssh_public_key()

    def get_ssh_public_key(self):
        """Get the local SSH public key - ALWAYS from actual user's home"""
        # Get the real user's home directory (even if using sudo - which we prevent)
        real_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
        if real_user == "root":
            print_warning("Running as root user. Using /root/.ssh/")
            home_dir = Path("/root")
        else:
            home_dir = Path.home()

        print(f"Looking for SSH keys in: {home_dir}/.ssh/")

        # Try ed25519 first
        ssh_key_path = home_dir / ".ssh" / "id_ed25519.pub"
        if not ssh_key_path.exists():
            # Try rsa
            ssh_key_path = home_dir / ".ssh" / "id_rsa.pub"

        if not ssh_key_path.exists():
            print_warning(f"No SSH key found in {home_dir}/.ssh/")
            print_warning("Generating new ed25519 key...")

            key_path = home_dir / ".ssh" / "id_ed25519"
            subprocess.run(
                [
                    "ssh-keygen",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-f",
                    str(key_path),
                    "-C",
                    f"{real_user}@{os.uname().nodename}",
                ],
                check=True,
            )
            ssh_key_path = home_dir / ".ssh" / "id_ed25519.pub"

        key = ssh_key_path.read_text().strip()
        print_success(f"Using SSH key: {ssh_key_path}")
        print(f"  Key: {key[:60]}...")
        print(f"  Full key: {key}")
        return key

    def build_installation_script(self):
        """Build the complete installation script"""
        # Properly escape the SSH key for shell
        ssh_key_escaped = self.ssh_public_key.replace("'", "'\"'\"'")

        return f"""
set -e  # Exit on any error

echo "============================================"
echo "Starting Hosting Manager Installation"
echo "============================================"
echo ""

# ═══════════════════════════════════════════════════════════
# STEP 1: Update System
# ═══════════════════════════════════════════════════════════
echo "[1/12] Updating system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y curl wget git vim ufw fail2ban ca-certificates gnupg lsb-release
echo "✅ System updated"

# ═══════════════════════════════════════════════════════════
# STEP 2: Create User (PROPERLY)
# ═══════════════════════════════════════════════════════════
echo "[2/12] Setting up user {self.username}..."

# Remove user if exists (clean slate)
if id "{self.username}" &>/dev/null; then
    echo "User {self.username} exists, removing for clean installation..."
    userdel -rf {self.username} 2>/dev/null || true
fi

# Create user with home directory
useradd -m -s /bin/bash {self.username}
chmod 755 /home/{self.username}  
echo "✅ User {self.username} created with home directory"

# Verify home directory
if [ ! -d "/home/{self.username}" ]; then
    echo "❌ ERROR: Home directory was not created!"
    exit 1
fi

# Add to sudo group
usermod -aG sudo {self.username}
echo '{self.username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{self.username}
chmod 440 /etc/sudoers.d/{self.username}

echo "✅ User {self.username} configured"

# ═══════════════════════════════════════════════════════════
# STEP 3: Setup SSH Keys (CRITICAL FIX)
# ═══════════════════════════════════════════════════════════
echo "[3/12] Setting up SSH keys for {self.username}..."

# Create .ssh directory
mkdir -p /home/{self.username}/.ssh
chmod 700 /home/{self.username}/.ssh

# CRITICAL: Add the SSH public key from your laptop
echo "Adding SSH key from local machine..."
echo "Key being installed: {self.ssh_public_key[:60]}..."

cat > /home/{self.username}/.ssh/authorized_keys << 'SSHKEY'
{ssh_key_escaped}
SSHKEY

# Set CRITICAL permissions
chmod 600 /home/{self.username}/.ssh/authorized_keys
chown -R {self.username}:{self.username} /home/{self.username}/.ssh

# Verify setup
echo "Verifying SSH setup..."
ls -la /home/{self.username}/.ssh/
cat /home/{self.username}/.ssh/authorized_keys
echo "Number of keys: $(wc -l < /home/{self.username}/.ssh/authorized_keys)"

echo "✅ SSH keys configured"

# ═══════════════════════════════════════════════════════════
# STEP 4: Configure SSH Daemon (FIXED for Ubuntu/Debian)
# ═══════════════════════════════════════════════════════════
echo "[4/12] Configuring SSH daemon..."

# Ensure SSH accepts public keys
sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PubkeyAuthentication no/PubkeyAuthentication yes/' /etc/ssh/sshd_config

# Ensure authorized_keys is read
sed -i 's/#AuthorizedKeysFile/AuthorizedKeysFile/' /etc/ssh/sshd_config

# Allow both password and key auth during setup
sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Test SSH config
if command -v sshd &> /dev/null; then
    sshd -t 2>/dev/null || /usr/sbin/sshd -t 2>/dev/null || echo "SSH config test skipped"
fi

# Restart SSH service
if systemctl list-units --type=service | grep -q 'ssh.service'; then
    systemctl restart ssh
    echo "✅ SSH service (ssh) restarted"
elif systemctl list-units --type=service | grep -q 'sshd.service'; then
    systemctl restart sshd
    echo "✅ SSH service (sshd) restarted"
fi

echo "✅ SSH daemon configured"

# ═══════════════════════════════════════════════════════════
# STEP 5: Configure Firewall
# ═══════════════════════════════════════════════════════════
echo "[5/12] Configuring firewall..."
ufw --force enable
ufw allow OpenSSH
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5000/tcp
ufw allow 3000:4000/tcp
ufw allow 8000:9000/tcp  # WordPress ports
echo "✅ Firewall configured"

# ═══════════════════════════════════════════════════════════
# STEP 6: Setup Fail2ban (with relaxed settings)
# ═══════════════════════════════════════════════════════════
echo "[6/12] Setting up fail2ban..."
cat > /etc/fail2ban/jail.local << 'F2B'
[DEFAULT]
bantime = 600
findtime = 600
maxretry = 10

[sshd]
enabled = true
maxretry = 10
F2B

systemctl enable fail2ban 2>/dev/null || true
systemctl restart fail2ban 2>/dev/null || true
echo "✅ Fail2ban configured (relaxed for development)"

# ═══════════════════════════════════════════════════════════
# STEP 7: Install Docker & Docker Compose
# ═══════════════════════════════════════════════════════════
echo "[7/12] Installing Docker & Docker Compose..."

# Install Docker
if ! command -v docker &> /dev/null; then
    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Add Docker repository
    echo \
      "deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      \$(. /etc/os-release && echo "\$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker Engine
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    echo "✅ Docker installed"
else
    echo "✅ Docker already installed"
fi

# Add user to docker group
usermod -aG docker {self.username}
echo "✅ User {self.username} added to docker group"

# Install docker-compose (standalone) if not present
if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-\$(uname -s)-\$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose installed"
else
    echo "✅ Docker Compose already installed"
fi

# Start and enable Docker
systemctl start docker
systemctl enable docker

echo "Docker version: \$(docker --version)"
echo "Docker Compose version: \$(docker-compose --version)"
echo "✅ Docker & Docker Compose ready"

# ═══════════════════════════════════════════════════════════
# STEP 8: Install Node.js Ecosystem
# ═══════════════════════════════════════════════════════════
echo "[8/12] Installing Node.js ecosystem..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>&1 | grep -v "^#" || true
apt-get install -y nodejs

npm install -g pm2 pnpm 2>&1 | grep -v "npm WARN" || true

# Make tools accessible
ln -sf /usr/bin/node /usr/local/bin/node || true
ln -sf /usr/bin/npm /usr/local/bin/npm || true
ln -sf /usr/lib/node_modules/pm2/bin/pm2 /usr/local/bin/pm2 || true
ln -sf /usr/bin/pnpm /usr/local/bin/pnpm || true

# Add to user's PATH
echo 'export PATH="/usr/local/bin:/usr/bin:$PATH"' >> /home/{self.username}/.bashrc
chown {self.username}:{self.username} /home/{self.username}/.bashrc

# Setup PM2 startup
su - {self.username} -c "pm2 startup" 2>&1 | tail -1 > /tmp/pm2_startup_cmd.sh || true
if [ -s /tmp/pm2_startup_cmd.sh ]; then
    bash /tmp/pm2_startup_cmd.sh 2>&1
    rm /tmp/pm2_startup_cmd.sh
fi

echo "Node.js: \$(node --version)"
echo "PM2: \$(pm2 --version)"
echo "✅ Node.js ecosystem installed"

# ═══════════════════════════════════════════════════════════
# STEP 9: Install Python Dependencies
# ═══════════════════════════════════════════════════════════
echo "[9/12] Installing Python dependencies..."
apt-get install -y python3 python3-pip python3-venv nginx sqlite3
pip3 install --break-system-packages Flask==3.0.0 Flask-CORS==4.0.0 2>&1 | grep -v "WARNING" || true
echo "✅ Python dependencies installed"

# ═══════════════════════════════════════════════════════════
# STEP 10: Create Directory Structure
# ═══════════════════════════════════════════════════════════
echo "[10/12] Creating directory structure..."

# Standard directories
mkdir -p /var/lib/hosting-manager
mkdir -p /var/log/hosting-manager
mkdir -p /var/www/domains
mkdir -p /var/www/wordpress-sites

# Set ownership
chown -R {self.username}:{self.username} /var/lib/hosting-manager
chown -R {self.username}:{self.username} /var/log/hosting-manager
chown -R {self.username}:{self.username} /var/www/domains
chown -R {self.username}:{self.username} /var/www/wordpress-sites

echo "✅ Directory structure created:"
echo "   - /var/lib/hosting-manager (database)"
echo "   - /var/log/hosting-manager (logs)"
echo "   - /var/www/domains (Next.js apps)"
echo "   - /var/www/wordpress-sites (WordPress sites)"

# In the build_installation_script method, STEP 11:

# ═══════════════════════════════════════════════════════════
# STEP 11: Deploy Application
# ═══════════════════════════════════════════════════════════
echo "[11/12] Deploying application..."
mkdir -p /opt/hosting-manager
chown {self.username}:{self.username} /opt/hosting-manager

if [ -d "/opt/hosting-manager/.git" ]; then
    cd /opt/hosting-manager
    sudo -u {self.username} git pull origin main
else
    sudo -u {self.username} git clone {self.repo_url} /opt/hosting-manager
fi

cd /opt/hosting-manager
pip3 install --break-system-packages -r requirements.txt 2>&1 | grep -v "WARNING" || true

# ⭐ NO MORE MIGRATION STEP - Tables auto-create on app startup

# Create systemd service
cat > /etc/systemd/system/hosting-manager.service << 'SERVICE'
[Unit]
Description=Hosting Manager API
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User={self.username}
Group={self.username}
WorkingDirectory=/opt/hosting-manager
Environment="PYTHONUNBUFFERED=1"
Environment="PATH=/usr/local/bin:/usr/bin"
ExecStart=/usr/bin/python3 /opt/hosting-manager/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable hosting-manager
systemctl restart hosting-manager
sleep 5

echo "✅ Application deployed"
# ═══════════════════════════════════════════════════════════
# STEP 12: Configure Nginx
# ═══════════════════════════════════════════════════════════
echo "[12/12] Configuring nginx..."
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/hosting-manager-api << 'NGINX'
server {{
    listen 80 default_server;
    server_name _;

    location /api/ {{
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }}

    location / {{
        return 200 '<!DOCTYPE html><html><head><title>Hosting Manager</title></head><body><h1>Hosting Manager Active</h1><p>Next.js + WordPress Deployments</p></body></html>';
    }}
}}
NGINX

ln -sf /etc/nginx/sites-available/hosting-manager-api /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
echo "✅ Nginx configured"

# ═══════════════════════════════════════════════════════════
# FINAL: Verify Installation
# ═══════════════════════════════════════════════════════════
echo ""
echo "============================================"
echo "Verifying Installation"
echo "============================================"

# Test SSH access
echo "Testing SSH access for {self.username}..."
su - {self.username} -c "whoami && pwd && pm2 --version && docker --version" && echo "✅ {self.username} can use PM2 and Docker"

# Test hosting-manager service
echo ""
echo "Checking hosting-manager service..."
systemctl is-active hosting-manager && echo "✅ hosting-manager service is running" || echo "❌ Service not running"

echo ""
echo "============================================"
echo "✅ Installation Complete!"
echo "============================================"
echo ""
echo "🚀 Server is ready for:"
echo "   - Next.js deployments"
echo "   - WordPress deployments"
echo "   - Shopify development (learning)"
echo ""
echo "Test SSH now from your laptop:"
echo "  ssh {self.username}@{self.server}"
echo ""
echo "Test API:"
echo "  curl http://{self.server}:5000/api/health"
echo ""
# Test Docker access
echo ""
echo "Testing Docker access for {self.username}..."
su - {self.username} -c "docker ps" && echo "✅ {self.username} can use Docker without sudo" || echo "⚠️  Docker permissions need session refresh"

# Note about docker group
echo ""
echo "⚠️  Note: {self.username} needs to log out and back in for Docker group to take effect"
echo "   Or run: newgrp docker"
"""

    def install(self):
        """Run installation via single SSH session"""
        print_header("🚀 Fresh Server Installation - Hosting Manager")
        print(f"Server:     {self.server}")
        print(f"User:       {self.username}")
        print(f"Repository: {self.repo_url}")
        print(f"\n🔑 SSH Key that will be installed:")
        print(f"   {self.ssh_public_key}\n")

        input("Press Enter to continue with installation...")

        install_script = self.build_installation_script()

        print_step("Connecting to server and starting installation...")
        print_warning("This will take several minutes...")
        print()

        try:
            if self.root_password:
                ssh_cmd = f"sshpass -p '{self.root_password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{self.server} 'bash -s'"
            else:
                ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{self.server} 'bash -s'"

            process = subprocess.Popen(
                ssh_cmd,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            process.stdin.write(install_script)
            process.stdin.close()

            for line in process.stdout:
                print(line, end="")

            return_code = process.wait()

            if return_code != 0:
                print_error(f"Installation failed with exit code {return_code}")
                sys.exit(1)

            print()
            print_header("✅ Installation Successful!")

            # Test SSH
            print_step("Testing SSH connection...")
            time.sleep(3)

            test_result = subprocess.run(
                f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 {self.username}@{self.server} 'whoami'",
                shell=True,
                capture_output=True,
                text=True,
            )

            if test_result.returncode == 0 and self.username in test_result.stdout:
                print_success(f"✅ SSH works! You can now connect as {self.username}")
                print(f"\n   ssh {self.username}@{self.server}\n")

                # Show the key that was installed
                print_warning("💡 Your SSH key is now installed on the server")
                print(f"   If you regenerate your local SSH key, re-run this script.")
            else:
                print_warning("⚠️  SSH test inconclusive. Try manually:")
                print(f"   ssh {self.username}@{self.server}")

        except Exception as e:
            print_error(f"Installation failed: {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Fresh server installation with Docker & WordPress support",
        epilog="Note: This script should be run as your regular user, not with sudo!",
    )
    parser.add_argument("--server", required=True, help="Server IP")
    parser.add_argument("--user", required=True, help="Username to create")
    parser.add_argument("--repo", required=True, help="Git repository URL")
    parser.add_argument("--root-password", help="Root password (optional)")

    args = parser.parse_args()

    installer = FreshInstaller(
        server=args.server,
        username=args.user,
        repo_url=args.repo,
        root_password=args.root_password,
    )

    installer.install()


if __name__ == "__main__":
    main()
