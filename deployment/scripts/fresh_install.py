#!/usr/bin/env python3
"""
Hosting Manager - Final Production Installation Script
All bugs fixed, tested and working
"""

import argparse
import subprocess
import sys
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


class ProductionInstaller:
    """Production-ready server installation - Battle-tested"""

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
        """Build the complete production installation script"""
        ssh_key_escaped = self.ssh_public_key.replace("'", "'\"'\"'")

        return rf"""
set -e

echo "============================================"
echo "Hosting Manager - Production Installation"
echo "All Fixes Incorporated - Battle Tested"
echo "============================================"

# ═══════════════════════════════════════════════════════════
# STEP 1: Update System
# ═══════════════════════════════════════════════════════════
echo "[1/12] Updating system..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y curl wget git vim ufw fail2ban ca-certificates
echo "✅ System updated"

# ═══════════════════════════════════════════════════════════
# STEP 2: Create User
# ═══════════════════════════════════════════════════════════
echo "[2/12] Setting up user {self.username}..."

if id "{self.username}" &>/dev/null; then
    userdel -rf {self.username} 2>/dev/null || true
fi

useradd -m -s /bin/bash {self.username}
chmod 755 /home/{self.username}
usermod -aG sudo {self.username}
echo '{self.username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{self.username}
chmod 440 /etc/sudoers.d/{self.username}
echo "✅ User created"

# ═══════════════════════════════════════════════════════════
# STEP 3: Setup SSH
# ═══════════════════════════════════════════════════════════
echo "[3/12] Setting up SSH..."

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
echo "[4/12] Configuring SSH daemon..."

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
echo "[5/12] Configuring firewall..."
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
echo "[6/12] Installing Node.js ecosystem..."
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
# STEP 7: Install MySQL Server (BULLETPROOF)
# ═══════════════════════════════════════════════════════════
echo "[7/12] Installing MySQL server..."

# Clean slate
systemctl stop mysql 2>/dev/null || true
apt-get remove --purge mysql-server mysql-client mysql-common -y 2>/dev/null || true
rm -rf /etc/mysql /var/lib/mysql /var/log/mysql
rm -rf /etc/hosting-manager/mysql_root_password /root/.mysql_root_password
rm -rf /root/.my.cnf /root/.mysql /home/{self.username}/.my.cnf /home/{self.username}/.mysql

# Install fresh
DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server

mkdir -p /var/run/mysqld
chown -R mysql:mysql /var/run/mysqld
chmod -R 755 /var/run/mysqld

systemctl start mysql
systemctl enable mysql
sleep 5

# Generate password
MYSQL_ROOT_PASS=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)

# Create hosting group
groupadd -f hosting
usermod -aG hosting {self.username}

# Method 1: Try init file
echo "Setting MySQL password (init file method)..."
systemctl stop mysql

echo "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '$MYSQL_ROOT_PASS';" > /tmp/mysql-init.sql
echo "FLUSH PRIVILEGES;" >> /tmp/mysql-init.sql

mysqld --user=mysql --init-file=/tmp/mysql-init.sql &
MYSQLD_PID=$!
sleep 8
kill $MYSQLD_PID 2>/dev/null || true
pkill -f "mysqld.*init-file" 2>/dev/null || true
sleep 2
rm -f /tmp/mysql-init.sql

systemctl start mysql
sleep 3

# Method 2: Force it with socket auth (CRITICAL FIX)
# Ubuntu 24.04 MySQL is stubborn - always force password auth
echo "Forcing password authentication (Ubuntu 24.04 fix)..."
mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '$MYSQL_ROOT_PASS';" 2>/dev/null || true
mysql -e "FLUSH PRIVILEGES;" 2>/dev/null || true
sleep 2

# Final verification
if ! mysql -u root -p"$MYSQL_ROOT_PASS" -e "SELECT 1;" >/dev/null 2>&1; then
    echo "❌ MySQL password setup failed"
    exit 1
fi

echo "✅ MySQL password set successfully"

# Create users
echo "Creating MySQL users..."

mysql -u root -p"$MYSQL_ROOT_PASS" -e "DROP USER IF EXISTS 'hosting_manager'@'localhost';"
mysql -u root -p"$MYSQL_ROOT_PASS" -e "CREATE USER 'hosting_manager'@'localhost' IDENTIFIED WITH mysql_native_password BY '$MYSQL_ROOT_PASS';"
mysql -u root -p"$MYSQL_ROOT_PASS" -e "GRANT ALL PRIVILEGES ON *.* TO 'hosting_manager'@'localhost' WITH GRANT OPTION;"

mysql -u root -p"$MYSQL_ROOT_PASS" -e "DROP USER IF EXISTS 'wp_manager'@'localhost';"
mysql -u root -p"$MYSQL_ROOT_PASS" -e "CREATE USER 'wp_manager'@'localhost' IDENTIFIED WITH mysql_native_password BY '$MYSQL_ROOT_PASS';"
mysql -u root -p"$MYSQL_ROOT_PASS" -e "GRANT CREATE, DROP, SELECT, INSERT, UPDATE, DELETE, ALTER, INDEX, CREATE TEMPORARY TABLES, LOCK TABLES ON *.* TO 'wp_manager'@'localhost';"

mysql -u root -p"$MYSQL_ROOT_PASS" -e "FLUSH PRIVILEGES;"

# Save passwords
mkdir -p /etc/hosting-manager
echo "$MYSQL_ROOT_PASS" > /etc/hosting-manager/mysql_root_password
echo "$MYSQL_ROOT_PASS" > /root/.mysql_root_password
chown root:hosting /etc/hosting-manager/mysql_root_password
chmod 640 /etc/hosting-manager/mysql_root_password
chmod 600 /root/.mysql_root_password

mkdir -p /home/{self.username}/.mysql
echo "[client]" > /home/{self.username}/.mysql/my.cnf
echo "user=root" >> /home/{self.username}/.mysql/my.cnf
echo "password=$MYSQL_ROOT_PASS" >> /home/{self.username}/.mysql/my.cnf
echo "host=localhost" >> /home/{self.username}/.mysql/my.cnf
chown -R {self.username}:{self.username} /home/{self.username}/.mysql
chmod 700 /home/{self.username}/.mysql
chmod 600 /home/{self.username}/.mysql/my.cnf

if mysql -u root -p"$MYSQL_ROOT_PASS" -e "SELECT 'MySQL Ready' as status;" 2>/dev/null | grep -q "MySQL Ready"; then
    echo "✅ MySQL installed: root, hosting_manager, wp_manager"
else
    echo "❌ MySQL verification failed"
    exit 1
fi

# ═══════════════════════════════════════════════════════════
# STEP 8: Install PHP and PHP-FPM
# ═══════════════════════════════════════════════════════════
echo "[8/12] Installing PHP 8.3 and PHP-FPM..."
apt-get install -y php8.3 php8.3-fpm php8.3-mysql php8.3-curl php8.3-gd \
    php8.3-mbstring php8.3-xml php8.3-xmlrpc php8.3-soap php8.3-intl \
    php8.3-zip php8.3-cli php8.3-imagick

sed -i 's/;cgi.fix_pathinfo=1/cgi.fix_pathinfo=0/' /etc/php/8.3/fpm/php.ini
sed -i 's/upload_max_filesize = .*/upload_max_filesize = 64M/' /etc/php/8.3/fpm/php.ini
sed -i 's/post_max_size = .*/post_max_size = 64M/' /etc/php/8.3/fpm/php.ini
sed -i 's/memory_limit = .*/memory_limit = 256M/' /etc/php/8.3/fpm/php.ini

# Create log directory (CRITICAL)
mkdir -p /var/log/php8.3-fpm
chown www-data:www-data /var/log/php8.3-fpm
chmod 755 /var/log/php8.3-fpm

systemctl start php8.3-fpm
systemctl enable php8.3-fpm

echo "PHP: $(php --version | head -n1)"
echo "✅ PHP 8.3 and PHP-FPM installed"

# ═══════════════════════════════════════════════════════════
# STEP 9: Install WP-CLI
# ═══════════════════════════════════════════════════════════
echo "[9/12] Installing WP-CLI..."
curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
chmod +x wp-cli.phar
mv wp-cli.phar /usr/local/bin/wp

echo "WP-CLI: $(wp --version --allow-root)"
echo "✅ WP-CLI installed"

# ═══════════════════════════════════════════════════════════
# STEP 10: Install Python + Nginx
# ═══════════════════════════════════════════════════════════
echo "[10/12] Installing Python dependencies..."
apt-get install -y python3 python3-pip python3-venv nginx sqlite3
pip3 install --break-system-packages Flask==3.0.0 Flask-CORS==4.0.0 PyMySQL==1.1.0 2>&1 | grep -v "WARNING" || true

# Configure Nginx user (CRITICAL)
sed -i 's/^user .*/user www-data;/' /etc/nginx/nginx.conf
if ! grep -q "^user www-data;" /etc/nginx/nginx.conf; then
    sed -i '1iuser www-data;' /etc/nginx/nginx.conf
fi

echo "✅ Python + Nginx installed"

# ═══════════════════════════════════════════════════════════
# STEP 11: Setup Directory Structure
# ═══════════════════════════════════════════════════════════
echo "[11/12] Creating directory structure..."

mkdir -p /var/lib/hosting-manager
mkdir -p /var/log/hosting-manager
mkdir -p /var/www/domains
mkdir -p /var/www/wordpress

chown -R {self.username}:{self.username} /var/lib/hosting-manager
chown -R {self.username}:{self.username} /var/log/hosting-manager
chown -R {self.username}:{self.username} /var/www/domains
chown -R www-data:www-data /var/www/wordpress

usermod -aG www-data {self.username}

chmod -R 2775 /var/www/wordpress

mkdir -p /run/nginx
chown -R www-data:www-data /run/nginx
chmod -R 755 /run/nginx

# Make config directories writable (CRITICAL FIX)
chown -R {self.username}:www-data /etc/nginx/sites-available
chown -R {self.username}:www-data /etc/nginx/sites-enabled
chmod 775 /etc/nginx/sites-available
chmod 775 /etc/nginx/sites-enabled
chmod 775 /etc/php/8.3/fpm/pool.d

echo "✅ Directory structure created"

# ═══════════════════════════════════════════════════════════
# STEP 12: Deploy Application
# ═══════════════════════════════════════════════════════════
echo "[12/12] Deploying application..."

mkdir -p /opt/hosting-manager
chown {self.username}:{self.username} /opt/hosting-manager

if [ -d "/opt/hosting-manager/.git" ]; then
    cd /opt/hosting-manager
    sudo -u {self.username} git fetch --all
    sudo -u {self.username} git reset --hard origin/main
    sudo -u {self.username} git clean -fd
else
    sudo -u {self.username} git clone {self.repo_url} /opt/hosting-manager
fi

cd /opt/hosting-manager
pip3 install --break-system-packages -r requirements.txt 2>&1 | grep -v "WARNING" || true

# Create environment file
MYSQL_ROOT_PASS=$(cat /root/.mysql_root_password)
echo "MYSQL_ROOT_PASSWORD=$MYSQL_ROOT_PASS" > /opt/hosting-manager/.env
echo "WORDPRESS_BASE_DIR=/var/www/wordpress" >> /opt/hosting-manager/.env

chown {self.username}:{self.username} /opt/hosting-manager/.env

# Create systemd service
cat > /etc/systemd/system/hosting-manager.service << 'SERVICEEOF'
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

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable hosting-manager
systemctl restart hosting-manager
sleep 5

echo "✅ Application deployed"

# Configure Nginx
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/hosting-manager-api << 'NGINXEOF'
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
        return 200 '<!DOCTYPE html><html><head><title>Hosting Manager</title></head><body><h1>Hosting Manager Active</h1></body></html>';
        add_header Content-Type text/html;
    }}
}}
NGINXEOF

ln -sf /etc/nginx/sites-available/hosting-manager-api /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo ""
echo "============================================"
echo "✅ Installation Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Log out and log back in: exit && ssh {self.username}@{self.server}"
echo "  2. Test API: curl http://localhost:5000/api/health"
echo "  3. Deploy WordPress:"
echo '     curl -X POST http://localhost:5000/api/wordpress/deploy \\'
echo '       -H "Content-Type: application/json" \\'
echo '       -d '"'"'{{"name":"site","domain":"example.com","adminEmail":"admin@example.com","adminPassword":"pass","siteTitle":"Site"}}'"'"
echo ""
echo "MySQL password: $(cat /etc/hosting-manager/mysql_root_password)"
echo ""
"""

    def install(self):
        """Run installation"""
        print_header("🚀 Hosting Manager - Production Installation")
        print(f"Server:     {self.server}")
        print(f"User:       {self.username}")
        print(f"Repository: {self.repo_url}")
        print()
        print_warning("This will install a fresh WordPress hosting platform!")
        print()

        response = input("Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(0)

        install_script = self.build_installation_script()

        print_step("Starting installation...")
        print_warning("This will take 5-10 minutes...")
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

        except Exception as e:
            print_error(f"Installation failed: {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Production-ready WordPress hosting platform installer"
    )
    parser.add_argument("--server", required=True, help="Server IP address")
    parser.add_argument("--user", required=True, help="Username (e.g., deploy)")
    parser.add_argument("--repo", required=True, help="Git repository URL")
    parser.add_argument("--root-password", help="Root password (optional)")

    args = parser.parse_args()

    installer = ProductionInstaller(
        server=args.server,
        username=args.user,
        repo_url=args.repo,
        root_password=args.root_password,
    )

    installer.install()


if __name__ == "__main__":
    main()
