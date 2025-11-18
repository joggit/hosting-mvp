#!/usr/bin/env python3
"""
Hosting Manager - Fresh Server Installation
Fixed user creation and SSH key setup
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'

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
    """Handles fresh server installation with proper user setup"""
    
    def __init__(self, server, username, repo_url, root_password=None):
        self.server = server
        self.username = username
        self.repo_url = repo_url
        self.root_password = root_password
        
        # Get local SSH public key
        self.ssh_public_key = self.get_ssh_public_key()
    
    def get_ssh_public_key(self):
        """Get the local SSH public key"""
        ssh_key_path = Path.home() / '.ssh' / 'id_ed25519.pub'
        if not ssh_key_path.exists():
            ssh_key_path = Path.home() / '.ssh' / 'id_rsa.pub'
        
        if not ssh_key_path.exists():
            print_warning("No SSH key found. Generating new key...")
            subprocess.run("ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519", shell=True, check=True)
            ssh_key_path = Path.home() / '.ssh' / 'id_ed25519.pub'
        
        return ssh_key_path.read_text().strip()
    
    def build_installation_script(self):
        """Build the complete installation script with proper user setup"""
        # Escape single quotes in SSH key for shell
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
echo "[1/10] Updating system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y curl wget git vim ufw fail2ban
echo "✅ System updated"

# ═══════════════════════════════════════════════════════════
# STEP 2: Create User (PROPERLY)
# ═══════════════════════════════════════════════════════════
echo "[2/10] Setting up user {self.username}..."

# Check if user exists
if id "{self.username}" &>/dev/null; then
    echo "User {self.username} already exists"
    # Ensure home directory exists
    if [ ! -d "/home/{self.username}" ]; then
        echo "Creating home directory..."
        mkhomedir_helper {self.username}
    fi
else
    # Create user with home directory
    echo "Creating user {self.username}..."
    useradd -m -s /bin/bash {self.username}
    echo "User created with home directory"
fi

# Ensure sudo access
usermod -aG sudo {self.username}
echo '{self.username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{self.username}
chmod 440 /etc/sudoers.d/{self.username}

# Verify user and home directory
if [ ! -d "/home/{self.username}" ]; then
    echo "ERROR: Home directory was not created!"
    exit 1
fi

echo "User info:"
id {self.username}
ls -la /home/{self.username}
echo "✅ User {self.username} ready"

# ═══════════════════════════════════════════════════════════
# STEP 3: Setup SSH Keys (PROPERLY)
# ═══════════════════════════════════════════════════════════
echo "[3/10] Setting up SSH keys..."

# Create .ssh directory
mkdir -p /home/{self.username}/.ssh
chmod 700 /home/{self.username}/.ssh

# Add YOUR SSH public key (from local machine)
echo '{ssh_key_escaped}' > /home/{self.username}/.ssh/authorized_keys

# Also copy root's keys if they exist (for backwards compatibility)
if [ -f /root/.ssh/authorized_keys ]; then
    cat /root/.ssh/authorized_keys >> /home/{self.username}/.ssh/authorized_keys
fi

# Set proper permissions
chmod 600 /home/{self.username}/.ssh/authorized_keys
chown -R {self.username}:{self.username} /home/{self.username}/.ssh

# Verify
echo "SSH directory contents:"
ls -la /home/{self.username}/.ssh/
echo "Authorized keys:"
wc -l /home/{self.username}/.ssh/authorized_keys
echo "✅ SSH keys configured"

# ═══════════════════════════════════════════════════════════
# STEP 4: Configure Firewall
# ═══════════════════════════════════════════════════════════
echo "[4/10] Configuring firewall..."
ufw --force enable
ufw allow OpenSSH
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5000/tcp
echo "✅ Firewall configured"

# ═══════════════════════════════════════════════════════════
# STEP 5: Setup Fail2ban
# ═══════════════════════════════════════════════════════════
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
echo "✅ Fail2ban configured"

# ═══════════════════════════════════════════════════════════
# STEP 6: Install Node.js Ecosystem
# ═══════════════════════════════════════════════════════════
echo "[6/10] Installing Node.js ecosystem..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - 2>&1 | grep -v "^#" || true
apt-get install -y nodejs

# Install PM2 and pnpm globally
npm install -g pm2 pnpm 2>&1 | grep -v "npm WARN" || true

# Setup PM2 startup for deploy user
echo "Setting up PM2 for user {self.username}..."
su - {self.username} -c "pm2 startup" | tail -1 > /tmp/pm2_startup_cmd.sh
if [ -s /tmp/pm2_startup_cmd.sh ]; then
    bash /tmp/pm2_startup_cmd.sh
    rm /tmp/pm2_startup_cmd.sh
fi

echo "Node.js: $(node --version)"
echo "npm: $(npm --version)"
echo "PM2: $(pm2 --version)"
echo "pnpm: $(pnpm --version)"
echo "✅ Node.js ecosystem installed"

# ═══════════════════════════════════════════════════════════
# STEP 7: Install Python Dependencies
# ═══════════════════════════════════════════════════════════
echo "[7/10] Installing Python dependencies..."
apt-get install -y python3 python3-pip python3-venv nginx sqlite3
pip3 install --break-system-packages Flask==3.0.0 Flask-CORS==4.0.0 2>&1 | grep -v "WARNING" || true
echo "✅ Python dependencies installed"

# ═══════════════════════════════════════════════════════════
# STEP 8: Deploy Application
# ═══════════════════════════════════════════════════════════
echo "[8/10] Deploying application..."
mkdir -p /opt/hosting-manager
chown {self.username}:{self.username} /opt/hosting-manager

# Clone repository as deploy user
if [ -d "/opt/hosting-manager/.git" ]; then
    echo "Updating existing repository..."
    cd /opt/hosting-manager
    sudo -u {self.username} git pull origin main
else
    echo "Cloning repository..."
    sudo -u {self.username} git clone {self.repo_url} /opt/hosting-manager
fi

# Install Python requirements
cd /opt/hosting-manager
pip3 install --break-system-packages -r requirements.txt 2>&1 | grep -v "WARNING" || true

# Create data directories
mkdir -p /var/lib/hosting-manager /var/log/hosting-manager /var/www/domains
chown -R {self.username}:{self.username} /var/lib/hosting-manager /var/log/hosting-manager /var/www/domains

# Create systemd service
cat > /etc/systemd/system/hosting-manager.service << 'SERVICE'
[Unit]
Description=Hosting Manager API
After=network.target

[Service]
Type=simple
User={self.username}
Group={self.username}
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

# Enable and start service
systemctl daemon-reload
systemctl enable hosting-manager
systemctl restart hosting-manager

# Wait for service to start
sleep 5

# Check if service started
if systemctl is-active --quiet hosting-manager; then
    echo "✅ Application deployed and running"
else
    echo "⚠️  Service may need a moment to start"
    journalctl -u hosting-manager -n 10 --no-pager
fi

# ═══════════════════════════════════════════════════════════
# STEP 9: Configure Nginx
# ═══════════════════════════════════════════════════════════
echo "[9/10] Configuring nginx..."
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/hosting-manager-api << 'NGINX'
server {{
    listen 80 default_server;
    server_name _;

    location /api/ {{
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }}

    location / {{
        default_type text/html;
        return 200 '<!DOCTYPE html>
<html>
<head><title>Hosting Manager</title></head>
<body style="font-family:Arial;max-width:800px;margin:50px auto;padding:20px;">
    <h1>🚀 Hosting Manager Active</h1>
    <p>The hosting manager is running successfully.</p>
    <h2>API Endpoints:</h2>
    <ul>
        <li><a href="/api/health">Health Check</a></li>
        <li><a href="/api/status">Status</a></li>
        <li><a href="/api/domains">Domains</a></li>
    </ul>
</body>
</html>';
    }}
}}
NGINX

ln -sf /etc/nginx/sites-available/hosting-manager-api /etc/nginx/sites-enabled/
nginx -t 2>&1 && systemctl reload nginx
echo "✅ Nginx configured"

# ═══════════════════════════════════════════════════════════
# STEP 10: Verify Installation & Test SSH
# ═══════════════════════════════════════════════════════════
echo "[10/10] Verifying installation..."

# Check service
if systemctl is-active --quiet hosting-manager; then
    echo "✅ Hosting Manager service is running"
else
    echo "❌ Hosting Manager service is not running"
    systemctl status hosting-manager --no-pager
fi

# Test API
sleep 2
if curl -f http://localhost:5000/api/health 2>/dev/null; then
    echo "✅ API is responding"
else
    echo "⚠️  API not responding yet (may need more time)"
fi

# Test SSH login for deploy user
echo ""
echo "Testing SSH access for {self.username} user..."
su - {self.username} -c "echo 'SSH access works!'" && echo "✅ Deploy user can login"

echo ""
echo "============================================"
echo "✅ Installation Complete!"
echo "============================================"
echo ""
echo "🎯 Installed Components:"
echo "  ✓ Node.js $(node --version)"
echo "  ✓ npm $(npm --version)"
echo "  ✓ PM2 $(pm2 --version)"
echo "  ✓ pnpm $(pnpm --version)"
echo "  ✓ Python 3 + Flask"
echo "  ✓ Nginx with virtual hosting"
echo "  ✓ UFW Firewall"
echo "  ✓ Fail2ban"
echo ""
echo "📡 Server Access:"
echo "  SSH:  ssh {self.username}@{self.server}"
echo "  API:  http://{self.server}:5000/api/health"
echo "  Web:  http://{self.server}"
echo ""
echo "🔧 Useful Commands:"
echo "  Status:  ssh {self.username}@{self.server} 'sudo systemctl status hosting-manager'"
echo "  Logs:    ssh {self.username}@{self.server} 'sudo journalctl -u hosting-manager -f'"
echo "  PM2:     ssh {self.username}@{self.server} 'pm2 list'"
echo ""
echo "✅ You should now be able to: ssh {self.username}@{self.server}"
echo ""
"""
    
    def install(self):
        """Run installation via single SSH session"""
        print_header("🚀 Fresh Server Installation - Hosting Manager")
        print(f"Server:     {self.server}")
        print(f"User:       {self.username}")
        print(f"Repository: {self.repo_url}")
        print(f"SSH Key:    {self.ssh_public_key[:50]}...")
        print()
        
        # Check prerequisites
        if self.root_password:
            result = subprocess.run('which sshpass', shell=True, capture_output=True)
            if result.returncode != 0:
                print_error("sshpass is not installed")
                print("Install it with: sudo apt-get install sshpass (Linux) or brew install hudochenkov/sshpass/sshpass (Mac)")
                sys.exit(1)
        
        # Build the installation script
        install_script = self.build_installation_script()
        
        print_step("Connecting to server and starting installation...")
        print_warning("This will take several minutes. Please be patient...")
        print()
        
        # Execute via SSH
        try:
            if self.root_password:
                ssh_cmd = f"sshpass -p '{self.root_password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{self.server} 'bash -s'"
            else:
                ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@{self.server} 'bash -s'"
            
            # Run the installation
            process = subprocess.Popen(
                ssh_cmd,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # Send the script
            process.stdin.write(install_script)
            process.stdin.close()
            
            # Show output in real-time
            for line in process.stdout:
                print(line, end='')
            
            # Wait for completion
            return_code = process.wait()
            
            if return_code != 0:
                print_error(f"Installation failed with exit code {return_code}")
                sys.exit(1)
            
            print()
            print_header("✅ Installation Successful!")
            
            # Test SSH connection as deploy user
            print_step(f"Testing SSH connection as {self.username} user...")
            time.sleep(2)
            
            test_result = subprocess.run(
                f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 {self.username}@{self.server} 'echo SSH works'",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if test_result.returncode == 0:
                print_success(f"✅ Can SSH as {self.username} user!")
            else:
                print_error(f"❌ Cannot SSH as {self.username} user")
                print(f"Error: {test_result.stderr}")
                print_warning("Try: ssh -v {self.username}@{self.server}")
            
            # Test API
            print_step("Testing API from your local machine...")
            time.sleep(2)
            
            try:
                result = subprocess.run(
                    f"curl -f http://{self.server}/api/health",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    print_success("✅ API is accessible!")
                    print(f"\n{result.stdout}\n")
                else:
                    print_warning("⚠️  API not accessible yet")
            except:
                print_warning("⚠️  Could not test API")
            
            # Print final summary
            self.print_final_summary()
            
        except KeyboardInterrupt:
            print()
            print_error("Installation interrupted by user")
            sys.exit(1)
        except Exception as e:
            print_error(f"Installation failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    def print_final_summary(self):
        """Print final summary"""
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"{Colors.CYAN}📚 Next Steps:{Colors.NC}\n")
        print(f"1. Test SSH access:")
        print(f"   ssh {self.username}@{self.server}\n")
        print(f"2. Test API:")
        print(f"   curl http://{self.server}/api/health\n")
        print(f"3. Deploy your first app:")
        print(f"   Use the /api/deploy/nodejs endpoint\n")
        print(f"4. Monitor with PM2:")
        print(f"   ssh {self.username}@{self.server}")
        print(f"   pm2 list\n")
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")

def main():
    parser = argparse.ArgumentParser(
        description='Fresh server installation for Hosting Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # With root password
  python3 fresh_install.py --server 75.119.141.162 --user deploy \\
    --repo https://github.com/joggit/hosting-mvp.git --root-password PASSWORD
  
  # With SSH key
  python3 fresh_install.py --server 75.119.141.162 --user deploy \\
    --repo https://github.com/joggit/hosting-mvp.git
        """
    )
    
    parser.add_argument('--server', required=True, help='Server IP address')
    parser.add_argument('--user', required=True, help='Username to create')
    parser.add_argument('--repo', required=True, help='Git repository URL')
    parser.add_argument('--root-password', help='Root password')
    
    args = parser.parse_args()
    
    installer = FreshInstaller(
        server=args.server,
        username=args.user,
        repo_url=args.repo,
        root_password=args.root_password
    )
    
    installer.install()

if __name__ == '__main__':
    main()
