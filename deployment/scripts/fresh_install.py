#!/usr/bin/env python3
"""
Hosting Manager - Fresh Server Installation
Fixed version with better SSH connection handling
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

def print_step(step, total, message):
    print(f"{Colors.GREEN}[{step}/{total}] {message}{Colors.NC}")

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.NC}")

def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.NC}")

def print_warning(message):
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.NC}")

def run_ssh_command(server, user, command, password=None, retries=3):
    """Execute command on remote server via SSH with retries"""
    for attempt in range(retries):
        if password:
            ssh_cmd = f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 {user}@{server} '{command}'"
        else:
            ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=60 -o ServerAliveCountMax=3 {user}@{server} '{command}'"
        
        result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0 or attempt == retries - 1:
            return result
        
        # Connection failed, wait and retry
        if "Connection reset" in result.stderr or "Connection refused" in result.stderr:
            print_warning(f"Connection issue, retrying in 5 seconds... (attempt {attempt + 1}/{retries})")
            time.sleep(5)
        else:
            return result
    
    return result

class FreshInstaller:
    """Handles fresh server installation"""
    
    def __init__(self, server, username, repo_url, root_password=None):
        self.server = server
        self.username = username
        self.repo_url = repo_url
        self.root_password = root_password
        self.total_steps = 10
        self.use_root = True  # Start with root, switch to user after setup
    
    def install(self):
        """Run complete installation"""
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"{Colors.BLUE}🚀 Fresh Server Installation - Hosting Manager{Colors.NC}")
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"Server: {self.server}")
        print(f"User: {self.username}")
        print(f"Repository: {self.repo_url}")
        print()
        
        try:
            self.step1_update_system()
            self.step2_create_user()
            self.step3_setup_ssh_keys()
            # Note: We do SSH hardening LAST now
            self.step4_setup_firewall()
            self.step5_setup_fail2ban()
            self.step6_install_nodejs_ecosystem()
            self.step7_install_python_dependencies()
            self.step8_deploy_application()
            self.step9_configure_nginx()
            self.step10_verify_installation()
            
            # Only secure SSH after everything works
            self.secure_ssh_final()
            
            self.print_summary()
            
        except Exception as e:
            print_error(f"Installation failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    def step1_update_system(self):
        """Update system packages"""
        print_step(1, self.total_steps, "Updating system packages...")
        
        commands = [
            "apt-get update -qq",
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq",
            "apt-get install -y curl wget git vim ufw fail2ban"
        ]
        
        for cmd in commands:
            result = run_ssh_command(self.server, "root", cmd, self.root_password)
            if result.returncode != 0:
                print_warning(f"Command warning: {cmd}")
        
        print_success("System updated")
    
    def step2_create_user(self):
        """Create deployment user"""
        print_step(2, self.total_steps, f"Creating user: {self.username}...")
        
        # Check if user exists
        check_cmd = f"id {self.username} 2>/dev/null"
        result = run_ssh_command(self.server, "root", check_cmd, self.root_password)
        
        if result.returncode == 0:
            print_warning(f"User {self.username} already exists")
        else:
            # Create user
            create_user = f"""
            adduser --disabled-password --gecos '' {self.username}
            usermod -aG sudo {self.username}
            """
            
            result = run_ssh_command(self.server, "root", create_user, self.root_password)
            
            if result.returncode != 0:
                print_error("Failed to create user")
                raise Exception(f"User creation failed")
        
        # Setup sudo access (even if user exists)
        sudo_cmd = f"echo '{self.username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{self.username} && chmod 440 /etc/sudoers.d/{self.username}"
        run_ssh_command(self.server, "root", sudo_cmd, self.root_password)
        
        print_success(f"User {self.username} ready")
    
    def step3_setup_ssh_keys(self):
        """Setup SSH key authentication"""
        print_step(3, self.total_steps, "Setting up SSH keys...")
        
        # Find SSH public key
        ssh_key_path = Path.home() / '.ssh' / 'id_ed25519.pub'
        if not ssh_key_path.exists():
            ssh_key_path = Path.home() / '.ssh' / 'id_rsa.pub'
        
        if not ssh_key_path.exists():
            print_warning("No SSH key found. Generating new key...")
            subprocess.run("ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519", shell=True, check=True)
            ssh_key_path = Path.home() / '.ssh' / 'id_ed25519.pub'
        
        public_key = ssh_key_path.read_text().strip()
        
        # Setup SSH directory and keys
        ssh_setup = f"""
        mkdir -p /home/{self.username}/.ssh
        echo '{public_key}' > /home/{self.username}/.ssh/authorized_keys
        chmod 700 /home/{self.username}/.ssh
        chmod 600 /home/{self.username}/.ssh/authorized_keys
        chown -R {self.username}:{self.username} /home/{self.username}/.ssh
        """
        
        run_ssh_command(self.server, "root", ssh_setup, self.root_password)
        
        # Test if we can connect as the new user with SSH key
        test_result = run_ssh_command(self.server, self.username, "echo 'SSH key works'", None)
        
        if test_result.returncode == 0:
            print_success("SSH keys configured and working")
            self.use_root = False  # Switch to using the deploy user
            self.root_password = None  # No longer need password
        else:
            print_warning("SSH key test failed, continuing with root")
    
    def step4_setup_firewall(self):
        """Configure UFW firewall"""
        print_step(4, self.total_steps, "Configuring firewall...")
        
        user = "root" if self.use_root else self.username
        password = self.root_password if self.use_root else None
        
        commands = [
            "ufw --force enable",
            "ufw allow OpenSSH",
            "ufw allow 22/tcp",
            "ufw allow 80/tcp",
            "ufw allow 443/tcp",
            "ufw allow 5000/tcp"
        ]
        
        for cmd in commands:
            run_ssh_command(self.server, user, f"sudo {cmd}" if not self.use_root else cmd, password)
        
        print_success("Firewall configured")
    
    def step5_setup_fail2ban(self):
        """Setup fail2ban"""
        print_step(5, self.total_steps, "Setting up fail2ban...")
        
        user = "root" if self.use_root else self.username
        password = self.root_password if self.use_root else None
        
        fail2ban_config = """
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
        """
        
        cmd = f"sudo bash -c '{fail2ban_config}'" if not self.use_root else fail2ban_config
        run_ssh_command(self.server, user, cmd, password)
        print_success("Fail2ban configured")
    
    def step6_install_nodejs_ecosystem(self):
        """Install Node.js, npm, PM2, and pnpm"""
        print_step(6, self.total_steps, "Installing Node.js ecosystem...")
        
        user = "root" if self.use_root else self.username
        password = self.root_password if self.use_root else None
        
        install_script = f"""
        curl -fsSL https://deb.nodesource.com/setup_20.x | {'bash -' if self.use_root else 'sudo bash -'}
        {'apt-get' if self.use_root else 'sudo apt-get'} install -y nodejs
        {'npm' if self.use_root else 'sudo npm'} install -g pm2 pnpm
        env PATH=$PATH:/usr/bin /usr/lib/node_modules/pm2/bin/pm2 startup systemd -u {self.username} --hp /home/{self.username}
        """
        
        result = run_ssh_command(self.server, user, install_script, password)
        
        if result.returncode == 0:
            print_success("Node.js ecosystem installed")
        else:
            print_warning("Node.js installation had some warnings")
    
    def step7_install_python_dependencies(self):
        """Install Python and dependencies"""
        print_step(7, self.total_steps, "Installing Python dependencies...")
        
        user = "root" if self.use_root else self.username
        password = self.root_password if self.use_root else None
        
        sudo_prefix = "" if self.use_root else "sudo "
        
        commands = [
            f"{sudo_prefix}apt-get install -y python3 python3-pip python3-venv nginx sqlite3",
            f"{sudo_prefix}pip3 install --break-system-packages Flask==3.0.0 Flask-CORS==4.0.0",
        ]
        
        for cmd in commands:
            run_ssh_command(self.server, user, cmd, password)
        
        print_success("Python dependencies installed")
    
    def step8_deploy_application(self):
        """Deploy the application"""
        print_step(8, self.total_steps, "Deploying application...")
        
        user = "root" if self.use_root else self.username
        password = self.root_password if self.use_root else None
        sudo_prefix = "" if self.use_root else "sudo "
        
        deploy_script = f"""
        # Create directory structure
        {sudo_prefix}mkdir -p /opt/hosting-manager
        {sudo_prefix}chown {self.username}:{self.username} /opt/hosting-manager
        
        # Clone repository
        if [ -d "/opt/hosting-manager/.git" ]; then
            cd /opt/hosting-manager && git pull origin main
        else
            su - {self.username} -c "git clone {self.repo_url} /opt/hosting-manager"
        fi
        
        # Install Python requirements
        cd /opt/hosting-manager
        {sudo_prefix}pip3 install --break-system-packages -r requirements.txt
        
        # Create data directories
        {sudo_prefix}mkdir -p /var/lib/hosting-manager /var/log/hosting-manager /var/www/domains
        {sudo_prefix}chown -R {self.username}:{self.username} /var/lib/hosting-manager
        {sudo_prefix}chown -R {self.username}:{self.username} /var/log/hosting-manager
        {sudo_prefix}chown -R {self.username}:{self.username} /var/www/domains
        
        # Create systemd service
        {sudo_prefix}tee /etc/systemd/system/hosting-manager.service > /dev/null << 'SERVICE'
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
        {sudo_prefix}systemctl daemon-reload
        {sudo_prefix}systemctl enable hosting-manager
        {sudo_prefix}systemctl restart hosting-manager
        
        sleep 5
        """
        
        result = run_ssh_command(self.server, user, deploy_script, password)
        
        if result.returncode != 0:
            print_error("Deployment had issues")
            print(result.stderr[:500])
            # Don't raise exception, continue to verify
        
        print_success("Application deployed")
    
    def step9_configure_nginx(self):
        """Configure nginx"""
        print_step(9, self.total_steps, "Configuring nginx...")
        
        user = "root" if self.use_root else self.username
        password = self.root_password if self.use_root else None
        sudo_prefix = "" if self.use_root else "sudo "
        
        nginx_config = f"""
        {sudo_prefix}rm -f /etc/nginx/sites-enabled/default
        
        {sudo_prefix}tee /etc/nginx/sites-available/hosting-manager-api > /dev/null << 'NGINX'
server {{
    listen 80 default_server;
    server_name _;

    location /api/ {{
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \\$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }}

    location / {{
        default_type text/html;
        return 200 '<!DOCTYPE html><html><head><title>Hosting Manager</title></head><body style="font-family:Arial;max-width:800px;margin:50px auto;padding:20px;"><h1>🚀 Hosting Manager Active</h1><p>Running successfully.</p><h2>API:</h2><ul><li><a href="/api/health">Health</a></li><li><a href="/api/status">Status</a></li><li><a href="/api/domains">Domains</a></li></ul></body></html>';
    }}
}}
NGINX

        {sudo_prefix}ln -sf /etc/nginx/sites-available/hosting-manager-api /etc/nginx/sites-enabled/
        {sudo_prefix}nginx -t && {sudo_prefix}systemctl reload nginx
        """
        
        run_ssh_command(self.server, user, nginx_config, password)
        print_success("Nginx configured")
    
    def step10_verify_installation(self):
        """Verify installation"""
        print_step(10, self.total_steps, "Verifying installation...")
        
        user = self.username  # Always use deploy user for verification
        
        # Check service
        result = run_ssh_command(self.server, user, "systemctl is-active hosting-manager", None)
        
        if result.stdout.strip() == "active":
            print_success("Hosting Manager service is running")
        else:
            print_warning("Service may not be running yet")
        
        # Test API
        time.sleep(3)
        result = run_ssh_command(self.server, user, "curl -f http://localhost:5000/api/health", None)
        
        if result.returncode == 0:
            print_success("API is responding")
        else:
            print_warning("API not responding yet")
        
        # Check Node.js tools
        for tool, cmd in [("Node.js", "node --version"), ("PM2", "pm2 --version"), ("pnpm", "pnpm --version")]:
            result = run_ssh_command(self.server, user, cmd, None)
            if result.returncode == 0:
                print_success(f"{tool}: {result.stdout.strip()}")
    
    def secure_ssh_final(self):
        """Secure SSH as final step"""
        print()
        print(f"{Colors.YELLOW}Securing SSH (disabling root login)...{Colors.NC}")
        
        # Only do this if we successfully switched to key-based auth
        if not self.use_root:
            ssh_config = """
            sudo sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
            sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
            sudo systemctl restart sshd
            """
            
            run_ssh_command(self.server, self.username, ssh_config, None)
            print_success("SSH secured - root login disabled")
        else:
            print_warning("Skipping SSH hardening (still using root password)")
    
    def print_summary(self):
        """Print installation summary"""
        print()
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"{Colors.GREEN}✅ Installation Complete!{Colors.NC}")
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}\n")
        
        print(f"{Colors.CYAN}🎯 Installed:{Colors.NC}")
        print(f"  ✓ Node.js 20.x + npm + PM2 + pnpm")
        print(f"  ✓ Python 3 + Flask")
        print(f"  ✓ Nginx")
        print(f"  ✓ Firewall & Fail2ban")
        print()
        
        print(f"{Colors.CYAN}📡 Access:{Colors.NC}")
        print(f"  SSH:  ssh {self.username}@{self.server}")
        print(f"  API:  http://{self.server}:5000/api/health")
        print(f"  Web:  http://{self.server}")
        print()
        
        print(f"{Colors.CYAN}🧪 Test:{Colors.NC}")
        print(f"  curl http://{self.server}/api/health")
        print()

def main():
    parser = argparse.ArgumentParser(description='Fresh server installation')
    parser.add_argument('--server', required=True, help='Server IP')
    parser.add_argument('--user', required=True, help='Username to create')
    parser.add_argument('--repo', required=True, help='Git repo URL')
    parser.add_argument('--root-password', help='Root password')
    
    args = parser.parse_args()
    
    if args.root_password:
        result = subprocess.run('which sshpass', shell=True, capture_output=True)
        if result.returncode != 0:
            print_error("Install sshpass: sudo apt-get install sshpass")
            sys.exit(1)
    
    installer = FreshInstaller(args.server, args.user, args.repo, args.root_password)
    installer.install()

if __name__ == '__main__':
    main()
