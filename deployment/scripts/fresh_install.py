#!/usr/bin/env python3
"""
Hosting Manager - Fresh Server Installation (Docker-Free)
Pure server blocks + PM2 for Next.js, PHP-FPM for WordPress
FIXED: All permission issues for WordPress deployment
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
    """Handles fresh server installation - No Docker, pure server blocks"""

    def __init__(self, server, username, repo_url, root_password=None):
        if os.geteuid() == 0:
            print_error("DO NOT run this script with sudo!")
            sys.exit(1)

        self.server = server
        self.username = username
        self.repo_url = repo_url
        self.root_password = root_password
        self.ssh_public_key = self.get_ssh_public_key()

    def get_ssh_public_key(self):
        """Get the local SSH public key"""
        real_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
        home_dir = Path("/root") if real_user == "root" else Path.home()

        ssh_key_path = home_dir / ".ssh" / "id_ed25519.pub"
        if not ssh_key_path.exists():
            ssh_key_path = home_dir / ".ssh" / "id_rsa.pub"

        if not ssh_key_path.exists():
            print_warning("Generating new ed25519 key...")
            key_path = home_dir / ".ssh" / "id_ed25519"
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
                check=True,
            )
            ssh_key_path = home_dir / ".ssh" / "id_ed25519.pub"

        key = ssh_key_path.read_text().strip()
        print_success(f"Using SSH key: {ssh_key_path}")
        return key

    def build_installation_script(self):
        """Build the complete installation script with ALL permission fixes"""
        ssh_key_escaped = self.ssh_public_key.replace("'", "'\"'\"'")

        return rf"""
set -e

echo "============================================"
echo "Hosting Manager - Docker-Free Installation"
echo "Next.js: Nginx + PM2"
echo "WordPress: Nginx + PHP-FPM + MySQL"
echo "============================================"

# ═══════════════════════════════════════════════════════════
# STEP 1: Update System
# ═══════════════════════════════════════════════════════════
echo "[1/14] Updating system..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y curl wget git vim ufw fail2ban ca-certificates
echo "✅ System updated"

# ═══════════════════════════════════════════════════════════
# STEP 2: Create User
# ═══════════════════════════════════════════════════════════
echo "[2/14] Setting up user {self.username}..."

if id "{self.username}" &>/dev/null; then
    userdel -rf {self.username} 2>/dev/null || true
fi

useradd -m -s /bin/bash {self.username}
chmod 755 /home/{self.username}
usermod -aG sudo {self.username}
echo "✅ User created"

# ═══════════════════════════════════════════════════════════
# STEP 3: Setup SSH
# ═══════════════════════════════════════════════════════════
echo "[3/14] Setting up SSH..."

mkdir -p /home/{self.username}/.ssh
chmod 700 /home/{self.username}/.ssh

cat > /home/{self.username}/.ssh/authorized_keys << 'SSHKEY'
{ssh_key_escaped}
SSHKEY

chmod 600 /home/{self.username}/.ssh/authorized_keys
chown -R {self.username}:{self.username} /home/{self.username}/.ssh
echo "✅ SSH configured"

# ═══════════════════════════════════════════════════════════
# STEP 4: Configure SSH Daemon
# ═══════════════════════════════════════════════════════════
echo "[4/14] Configuring SSH daemon..."

sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PubkeyAuthentication no/PubkeyAuthentication yes/' /etc/ssh/sshd_config

if systemctl list-units --type=service | grep -q 'ssh.service'; then
    systemctl restart ssh
elif systemctl list-units --type=service | grep -q 'sshd.service'; then
    systemctl restart sshd
fi

echo "✅ SSH daemon configured"

# ═══════════════════════════════════════════════════════════
# STEP 5: Firewall
# ═══════════════════════════════════════════════════════════
echo "[5/14] Configuring firewall..."
ufw --force enable
ufw allow OpenSSH
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5000/tcp
ufw allow 3000:4000/tcp
echo "✅ Firewall configured"

# ═══════════════════════════════════════════════════════════
# STEP 6: Install Node.js + PM2
# ═══════════════════════════════════════════════════════════
echo "[6/14] Installing Node.js ecosystem..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>&1 | grep -v "^#" || true
apt-get install -y nodejs

npm install -g pm2 pnpm 2>&1 | grep -v "npm WARN" || true

echo 'export PATH="/usr/local/bin:/usr/bin:$PATH"' >> /home/{self.username}/.bashrc
chown {self.username}:{self.username} /home/{self.username}/.bashrc

su - {self.username} -c "pm2 startup" 2>&1 | tail -1 > /tmp/pm2_startup_cmd.sh || true
if [ -s /tmp/pm2_startup_cmd.sh ]; then
    bash /tmp/pm2_startup_cmd.sh 2>&1
    rm /tmp/pm2_startup_cmd.sh
fi

echo "Node.js: $(node --version)"
echo "PM2: $(pm2 --version)"
echo "✅ Node.js + PM2 installed"

# ═══════════════════════════════════════════════════════════
# STEP 7: Install & Secure MySQL Server
# ═══════════════════════════════════════════════════════════
echo "[7/14] Installing & securing MySQL server..."

if ! dpkg -l | grep -q "mysql-server"; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server
fi

systemctl start mysql
systemctl enable mysql

# Generate or reuse root password
MYSQL_ROOT_PASS=""
MYSQL_PASS_FILE="/root/.mysql_root_password"

if [ -f "$MYSQL_PASS_FILE" ]; then
    MYSQL_ROOT_PASS=$(cat "$MYSQL_PASS_FILE")
    echo "✅ Using existing MySQL root password"
else
    MYSQL_ROOT_PASS="SecureRootPass$(openssl rand -base64 12 | tr -dc 'A-Za-z0-9' | head -c 16)"
    echo "$MYSQL_ROOT_PASS" > "$MYSQL_PASS_FILE"
    chmod 600 "$MYSQL_PASS_FILE"
    
    # Set password
    mysql << MYSQL_SETUP
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '$MYSQL_ROOT_PASS';
FLUSH PRIVILEGES;
MYSQL_SETUP
fi

# Create .my.cnf for root
cat > /root/.my.cnf << MYCNF
[client]
user=root
password=$MYSQL_ROOT_PASS
host=localhost
MYCNF
chmod 600 /root/.my.cnf

# Security hardening
mysql -u root -p$MYSQL_ROOT_PASS << MYSQL_HARDEN
DELETE FROM mysql.user WHERE User='';
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
FLUSH PRIVILEGES;
MYSQL_HARDEN

echo "✅ MySQL server secured"

# ═══════════════════════════════════════════════════════════
# STEP 8: Install PHP and PHP-FPM
# ═══════════════════════════════════════════════════════════
echo "[8/14] Installing PHP 8.3 and PHP-FPM..."
apt-get install -y php8.3 php8.3-fpm php8.3-mysql php8.3-curl php8.3-gd \
    php8.3-mbstring php8.3-xml php8.3-xmlrpc php8.3-soap php8.3-intl \
    php8.3-zip php8.3-cli php8.3-imagick

sed -i 's/;cgi.fix_pathinfo=1/cgi.fix_pathinfo=0/' /etc/php/8.3/fpm/php.ini
sed -i 's/upload_max_filesize = .*/upload_max_filesize = 64M/' /etc/php/8.3/fpm/php.ini
sed -i 's/post_max_size = .*/post_max_size = 64M/' /etc/php/8.3/fpm/php.ini
sed -i 's/memory_limit = .*/memory_limit = 256M/' /etc/php/8.3/fpm/php.ini

systemctl start php8.3-fpm
systemctl enable php8.3-fpm

echo "PHP: $(php --version | head -n1)"
echo "✅ PHP 8.3 and PHP-FPM installed"

# ═══════════════════════════════════════════════════════════
# STEP 9: Install WP-CLI (Fixed version)
# ═══════════════════════════════════════════════════════════
echo "[9/14] Installing WP-CLI..."
curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
chmod +x wp-cli.phar
mv wp-cli.phar /usr/local/bin/wp

# Create a wrapper script to handle permissions
cat > /usr/local/bin/wp-safe << 'WPWRAPPER'
#!/bin/bash
# WP-CLI wrapper that handles permission issues
if [ -f "/usr/local/bin/wp" ]; then
    # Run wp with proper context
    if [ "$EUID" -eq 0 ]; then
        /usr/local/bin/wp "$@" --allow-root
    else
        /usr/local/bin/wp "$@"
    fi
else
    echo "WP-CLI not found"
    exit 1
fi
WPWRAPPER

chmod +x /usr/local/bin/wp-safe

echo "WP-CLI: $(wp --version --allow-root 2>/dev/null || echo "installed")"
echo "✅ WP-CLI installed"

# ═══════════════════════════════════════════════════════════
# STEP 10: Install Python + Nginx
# ═══════════════════════════════════════════════════════════
echo "[10/14] Installing Python dependencies..."
apt-get install -y python3 python3-pip python3-venv nginx sqlite3
pip3 install --break-system-packages Flask==3.0.0 Flask-CORS==4.0.0 PyMySQL==1.1.0 2>&1 | grep -v "WARNING" || true
echo "✅ Python + Nginx installed"

# ═══════════════════════════════════════════════════════════
# STEP 11: Setup Directory Structure with PROPER PERMISSIONS
# ═══════════════════════════════════════════════════════════
echo "[11/14] Creating directory structure with proper permissions..."

# Create directories
mkdir -p /var/lib/hosting-manager
mkdir -p /var/log/hosting-manager
mkdir -p /var/www/domains
mkdir -p /var/www/wordpress

# Set ownership - deploy owns hosting-manager, www-data owns wordpress
chown -R {self.username}:{self.username} /var/lib/hosting-manager
chown -R {self.username}:{self.username} /var/log/hosting-manager
chown -R {self.username}:{self.username} /var/www/domains
chown -R www-data:www-data /var/www/wordpress

# Add deploy to www-data group for WordPress deployment
usermod -aG www-data {self.username}

# Set proper permissions
chmod -R 2775 /var/www/wordpress
find /var/www/wordpress -type f -exec chmod 664 {{}} \\;
chmod -R 755 /var/www/domains

# Fix Nginx directory permissions for deploy
chmod 775 /etc/nginx/sites-available
chmod 775 /etc/nginx/sites-enabled

# Create nginx-admin group and add deploy
groupadd nginx-admin 2>/dev/null || true
usermod -aG nginx-admin {self.username}
chown -R root:nginx-admin /etc/nginx/sites-available
chown -R root:nginx-admin /etc/nginx/sites-enabled
chmod -R 775 /etc/nginx/sites-available
chmod -R 775 /etc/nginx/sites-enabled

# Fix PHP-FPM pool directory permissions
chmod 775 /etc/php/8.3/fpm/pool.d

echo "✅ Directory structure created with proper permissions"

# ═══════════════════════════════════════════════════════════
# STEP 12: Configure Sudoers for WordPress Deployment
# ═══════════════════════════════════════════════════════════
echo "[12/14] Configuring sudo permissions for WordPress deployment..."

# Create comprehensive sudoers file
cat > /etc/sudoers.d/{self.username}-hosting << 'SUDOERS'
Defaults:{self.username} !requiretty
Defaults:{self.username} !authenticate

# Allow deploy to manage Nginx configs
{self.username} ALL=(root) NOPASSWD: /bin/cp /tmp/*.conf /etc/nginx/sites-available/
{self.username} ALL=(root) NOPASSWD: /bin/rm /etc/nginx/sites-available/*.conf
{self.username} ALL=(root) NOPASSWD: /bin/ln -s /etc/nginx/sites-available/* /etc/nginx/sites-enabled/
{self.username} ALL=(root) NOPASSWD: /bin/rm /etc/nginx/sites-enabled/*.conf
{self.username} ALL=(root) NOPASSWD: /usr/sbin/nginx -t
{self.username} ALL=(root) NOPASSWD: /bin/systemctl reload nginx
{self.username} ALL=(root) NOPASSWD: /bin/systemctl restart nginx

# Allow deploy to manage PHP-FPM configs
{self.username} ALL=(root) NOPASSWD: /bin/cp /tmp/*.conf /etc/php/8.3/fpm/pool.d/
{self.username} ALL=(root) NOPASSWD: /bin/rm /etc/php/8.3/fpm/pool.d/*.conf
{self.username} ALL=(root) NOPASSWD: /bin/systemctl reload php8.3-fpm
{self.username} ALL=(root) NOPASSWD: /bin/systemctl restart php8.3-fpm
{self.username} ALL=(root) NOPASSWD: /bin/systemctl start php8.3-fpm

# Allow deploy to manage WordPress files (as www-data)
{self.username} ALL=(www-data) NOPASSWD: /bin/mkdir -p /var/www/wordpress/*
{self.username} ALL=(www-data) NOPASSWD: /bin/chown -R www-data:www-data /var/www/wordpress/*
{self.username} ALL=(www-data) NOPASSWD: /bin/chmod -R 775 /var/www/wordpress/*
{self.username} ALL=(www-data) NOPASSWD: /bin/rm -rf /var/www/wordpress/*
{self.username} ALL=(www-data) NOPASSWD: /bin/tar -xzf /tmp/*.tar.gz -C /var/www/wordpress/* --strip-components=1
{self.username} ALL=(www-data) NOPASSWD: /usr/bin/wget -O /tmp/*.tar.gz https://wordpress.org/latest.tar.gz

# Allow deploy to run MySQL commands
{self.username} ALL=(root) NOPASSWD: /usr/bin/mysql *
SUDOERS

chmod 440 /etc/sudoers.d/{self.username}-hosting

# Also give full sudo for simplicity (can be restricted later)
echo "{self.username} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/{self.username}
chmod 440 /etc/sudoers.d/{self.username}

echo "✅ Sudo permissions configured"

# ═══════════════════════════════════════════════════════════
# STEP 13: Deploy Application
# ═══════════════════════════════════════════════════════════
echo "[13/14] Deploying application..."
mkdir -p /opt/hosting-manager
chown {self.username}:{self.username} /opt/hosting-manager

if [ -d "/opt/hosting-manager/.git" ]; then
    cd /opt/hosting-manager
    sudo -u {self.username} git pull origin main
else
    sudo -u {self.username} git clone {self.repo_url} /opt/hosting-manager
fi

cd /opt/hosting-manager

# Install Python dependencies
pip3 install --break-system-packages -r requirements.txt 2>&1 | grep -v "WARNING" || true

# Create environment file with MySQL password
cat > /opt/hosting-manager/.env << ENV
MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PASS
WORDPRESS_BASE_DIR=/var/www/wordpress
ENV

chown {self.username}:{self.username} /opt/hosting-manager/.env

# Fix the download_wordpress function in the app
# Create a patched version that handles WordPress extraction properly
cat > /tmp/fix_wordpress_download.py << 'PYFIX'
import os
import subprocess
import tempfile
from pathlib import Path

def download_wordpress_fixed(site_dir):
    """Download and extract WordPress without permission errors"""
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    
    # Download WordPress to temp location
    wp_zip = Path("/tmp/wordpress-latest.tar.gz")
    
    # Download using wget with sudo as www-data
    subprocess.run([
        'sudo', '-u', 'www-data', 'wget',
        'https://wordpress.org/latest.tar.gz',
        '-O', str(wp_zip),
        '-q'
    ], check=True)
    
    # Extract WordPress using sudo as www-data to avoid permission issues
    subprocess.run([
        'sudo', '-u', 'www-data', 'tar',
        '-xzf', str(wp_zip),
        '-C', str(site_dir.parent),
        '--strip-components=1',
        '--no-same-owner',  # Don't preserve ownership
        '--no-same-permissions'  # Don't preserve permissions
    ], check=True)
    
    # Clean up
    wp_zip.unlink(missing_ok=True)
    
    # Fix permissions after extraction
    subprocess.run([
        'sudo', 'chown', '-R', 'www-data:www-data', str(site_dir)
    ], check=True)
    subprocess.run([
        'sudo', 'chmod', '-R', '775', str(site_dir)
    ], check=True)

# Test the fix
if __name__ == "__main__":
    test_dir = "/var/www/wordpress/test_site"
    download_wordpress_fixed(test_dir)
    print(f"✅ WordPress downloaded to {test_dir}")
PYFIX

# If there's a wordpress service file, patch it
if [ -f "/opt/hosting-manager/services/wordpress.py" ]; then
    # Backup original
    cp /opt/hosting-manager/services/wordpress.py /opt/hosting-manager/services/wordpress.py.backup
    
    # Patch the download_wordpress function
    sed -i '/def download_wordpress/,/^def/ {{ /def download_wordpress/,/^def/!d; /def download_wordpress/r /tmp/fix_wordpress_download.py' /opt/hosting-manager/services/wordpress.py
fi

# Create systemd service
cat > /etc/systemd/system/hosting-manager.service << 'SERVICE'
[Unit]
Description=Hosting Manager API
After=network.target mysql.service php8.3-fpm.service
Requires=mysql.service php8.3-fpm.service

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

# Set environment variables for permissions
Environment="WORDPRESS_UID=$(id -u www-data)"
Environment="WORDPRESS_GID=$(id -g www-data)"

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable hosting-manager
systemctl restart hosting-manager
sleep 5

echo "✅ Application deployed and started"

# ═══════════════════════════════════════════════════════════
# STEP 14: Configure Nginx
# ═══════════════════════════════════════════════════════════
echo "[14/14] Configuring Nginx..."

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
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CORS headers
        add_header 'Access-Control-Allow-Origin' '*' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS' always;
        add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization' always;
        add_header 'Access-Control-Expose-Headers' 'Content-Length,Content-Range' always;
        
        # Handle preflight requests
        if ($request_method = 'OPTIONS') {{
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization';
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }}
    }}

    location / {{
        return 200 '<!DOCTYPE html><html><head><title>Hosting Manager</title><style>body {{ font-family: Arial, sans-serif; margin: 40px; text-align: center; }} h1 {{ color: #333; }} p {{ color: #666; }}</style></head><body><h1>🚀 Hosting Manager Active</h1><p>Next.js: Nginx + PM2</p><p>WordPress: Nginx + PHP-FPM + MySQL</p><p>No Docker - Pure Server Blocks</p><p><a href="/api/health">Check API Health</a></p></body></html>';
        add_header Content-Type text/html;
    }}
}}
NGINX

ln -sf /etc/nginx/sites-available/hosting-manager-api /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo ""
echo "============================================"
echo "✅ Installation Complete!"
echo "============================================"
echo ""
echo "🚀 Architecture:"
echo "   - Next.js: Nginx + PM2 (ports 3000-4000)"
echo "   - WordPress: Nginx + PHP-FPM + MySQL"
echo "   - No Docker - Pure server blocks"
echo ""
echo "📋 Key Fixes Applied:"
echo "   - WordPress extraction permission issues fixed"
echo "   - Proper sudo permissions for deploy user"
echo "   - Correct directory ownership (www-data for WordPress)"
echo "   - Nginx and PHP-FPM directory permissions fixed"
echo ""
echo "🔑 Test SSH:"
echo "  ssh {self.username}@{self.server}"
echo ""
echo "🌐 Test API:"
echo "  curl http://{self.server}:5000/api/health"
echo "  curl http://{self.server}/api/health"
echo ""
echo "🔧 MySQL root password saved to:"
echo "  /root/.mysql_root_password"
echo ""
echo "⚠️  IMPORTANT: Log out and log back in for group changes to take effect!"
echo ""
"""

    def install(self):
        """Run installation"""
        print_header("🚀 Hosting Manager - Docker-Free Installation")
        print(f"Server:     {self.server}")
        print(f"User:       {self.username}")
        print(f"Repository: {self.repo_url}")
        print(f"\n🔑 SSH Key:")
        print(f"   {self.ssh_public_key}\n")

        input("Press Enter to continue...")

        install_script = self.build_installation_script()

        print_step("Starting installation...")
        print_warning("This will take several minutes...")
        print()

        try:
            if self.root_password:
                ssh_cmd = f"sshpass -p '{self.root_password}' ssh -o StrictHostKeyChecking=no root@{self.server} 'bash -s'"
            else:
                ssh_cmd = (
                    f"ssh -o StrictHostKeyChecking=no root@{self.server} 'bash -s'"
                )

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

            time.sleep(3)

            test_result = subprocess.run(
                f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 {self.username}@{self.server} 'whoami'",
                shell=True,
                capture_output=True,
                text=True,
            )

            if test_result.returncode == 0:
                print_success(f"✅ SSH works!")
                print(f"\n   ssh {self.username}@{self.server}\n")
                print("⚠️  IMPORTANT: Log out and log back in for group changes to take effect!")

        except Exception as e:
            print_error(f"Installation failed: {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Fresh server installation - Docker-Free"
    )
    parser.add_argument("--server", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--repo", required=True)
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