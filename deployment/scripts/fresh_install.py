#!/usr/bin/env python3
"""
Fresh Server Install - Complete Automation
Automates the entire process from fresh Ubuntu server to running Hosting Manager

Usage:
    python3 fresh_install.py --server IP --user USERNAME --repo REPO_URL
    
Example:
    python3 fresh_install.py --server 75.119.141.162 --user deploy --repo https://github.com/user/hosting-mvp.git
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

def print_header(message):
    """Print a header message"""
    print(f"\n{Colors.BLUE}{'=' * 60}{Colors.NC}")
    print(f"{Colors.BLUE}{message}{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 60}{Colors.NC}\n")

def print_step(step, total, message):
    """Print step progress"""
    print(f"{Colors.GREEN}[{step}/{total}] {message}{Colors.NC}")

def print_success(message):
    """Print success message"""
    print(f"{Colors.GREEN}✅ {message}{Colors.NC}")

def print_error(message):
    """Print error message"""
    print(f"{Colors.RED}❌ {message}{Colors.NC}")

def print_warning(message):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.NC}")

def run_ssh_command(server, user, command, password=None):
    """Execute command on remote server via SSH"""
    if password:
        # Using sshpass for password authentication
        ssh_cmd = f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no {user}@{server} '{command}'"
    else:
        ssh_cmd = f"ssh -o StrictHostKeyChecking=no {user}@{server} '{command}'"
    
    result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
    return result

def run_local_command(command):
    """Execute command locally"""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result

class FreshInstaller:
    """Handles fresh server installation"""
    
    def __init__(self, server, username, repo_url, ssh_key=None, root_password=None):
        self.server = server
        self.username = username
        self.repo_url = repo_url
        self.ssh_key = ssh_key
        self.root_password = root_password
        self.total_steps = 10
        
    def install(self):
        """Run complete installation"""
        print_header("🚀 Fresh Server Installation - Hosting Manager")
        print(f"Server: {self.server}")
        print(f"User: {self.username}")
        print(f"Repository: {self.repo_url}")
        print()
        
        try:
            self.step1_update_system()
            self.step2_create_user()
            self.step3_setup_ssh_keys()
            self.step4_secure_ssh()
            self.step5_setup_firewall()
            self.step6_setup_fail2ban()
            self.step7_install_dependencies()
            self.step8_deploy_application()
            self.step9_configure_nginx()
            self.step10_verify_installation()
            
            self.print_summary()
            
        except Exception as e:
            print_error(f"Installation failed: {e}")
            sys.exit(1)
    
    def step1_update_system(self):
        """Update system packages"""
        print_step(1, self.total_steps, "Updating system packages...")
        
        commands = [
            "apt-get update -qq",
            "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq",
            "apt-get install -y curl wget git vim ufw fail2ban python3 python3-pip python3-venv"
        ]
        
        for cmd in commands:
            result = run_ssh_command(self.server, "root", cmd, self.root_password)
            if result.returncode != 0:
                print_warning(f"Command warning: {cmd}")
        
        print_success("System updated")
    
    def step2_create_user(self):
        """Create deployment user"""
        print_step(2, self.total_steps, f"Creating user: {self.username}...")
        
        # Check if user already exists
        check_cmd = f"id {self.username}"
        result = run_ssh_command(self.server, "root", check_cmd, self.root_password)
        
        if result.returncode == 0:
            print_warning(f"User {self.username} already exists, skipping creation")
            return
        
        # Create user
        commands = [
            f"adduser --disabled-password --gecos '' {self.username}",
            f"usermod -aG sudo {self.username}",
            f"echo '{self.username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{self.username}"
        ]
        
        for cmd in commands:
            run_ssh_command(self.server, "root", cmd, self.root_password)
        
        print_success(f"User {self.username} created")
    
    def step3_setup_ssh_keys(self):
        """Setup SSH key authentication"""
        print_step(3, self.total_steps, "Setting up SSH keys...")
        
        # Check for local SSH key
        ssh_key_path = Path.home() / '.ssh' / 'id_ed25519.pub'
        if not ssh_key_path.exists():
            ssh_key_path = Path.home() / '.ssh' / 'id_rsa.pub'
        
        if not ssh_key_path.exists():
            print_warning("No SSH key found. Generating new key...")
            run_local_command("ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519")
            ssh_key_path = Path.home() / '.ssh' / 'id_ed25519.pub'
        
        # Read public key
        public_key = ssh_key_path.read_text().strip()
        
        # Copy key to server
        commands = [
            f"mkdir -p /home/{self.username}/.ssh",
            f"echo '{public_key}' >> /home/{self.username}/.ssh/authorized_keys",
            f"chmod 700 /home/{self.username}/.ssh",
            f"chmod 600 /home/{self.username}/.ssh/authorized_keys",
            f"chown -R {self.username}:{self.username} /home/{self.username}/.ssh"
        ]
        
        for cmd in commands:
            run_ssh_command(self.server, "root", cmd, self.root_password)
        
        print_success("SSH keys configured")
    
    def step4_secure_ssh(self):
        """Secure SSH configuration"""
        print_step(4, self.total_steps, "Securing SSH...")
        
        ssh_config = """
sed -i 's/#PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config
systemctl restart sshd
"""
        
        run_ssh_command(self.server, "root", ssh_config, self.root_password)
        print_success("SSH secured")
    
    def step5_setup_firewall(self):
        """Configure UFW firewall"""
        print_step(5, self.total_steps, "Configuring firewall...")
        
        commands = [
            "ufw --force enable",
            "ufw allow OpenSSH",
            "ufw allow 22/tcp",
            "ufw allow 80/tcp",
            "ufw allow 443/tcp",
            "ufw allow 5000/tcp",
            "ufw status"
        ]
        
        for cmd in commands:
            run_ssh_command(self.server, self.username, cmd)
        
        print_success("Firewall configured")
    
    def step6_setup_fail2ban(self):
        """Setup fail2ban"""
        print_step(6, self.total_steps, "Setting up fail2ban...")
        
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
        
        run_ssh_command(self.server, self.username, fail2ban_config)
        print_success("Fail2ban configured")
    
    def step7_install_dependencies(self):
        """Install required dependencies"""
        print_step(7, self.total_steps, "Installing dependencies...")
        
        commands = [
            "sudo apt-get install -y nginx sqlite3",
        ]
        
        for cmd in commands:
            run_ssh_command(self.server, self.username, cmd)
        
        print_success("Dependencies installed")
    
    def step8_deploy_application(self):
        """Deploy the application"""
        print_step(8, self.total_steps, "Deploying application...")
        
        deploy_script = f"""
# Setup application directory
sudo mkdir -p /opt/hosting-manager
sudo chown {self.username}:{self.username} /opt/hosting-manager

# Clone repository
if [ -d "/opt/hosting-manager/.git" ]; then
    cd /opt/hosting-manager && git pull origin main
else
    git clone {self.repo_url} /opt/hosting-manager
fi

cd /opt/hosting-manager

# Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Create necessary directories
sudo mkdir -p /var/lib/hosting-manager
sudo mkdir -p /var/log/hosting-manager
sudo mkdir -p /var/www/domains
sudo chown -R {self.username}:{self.username} /var/lib/hosting-manager
sudo chown -R {self.username}:{self.username} /var/log/hosting-manager
sudo chown -R {self.username}:{self.username} /var/www/domains

# Create systemd service
sudo tee /etc/systemd/system/hosting-manager.service > /dev/null << 'SERVICE'
[Unit]
Description=Hosting Manager API
After=network.target

[Service]
Type=simple
User={self.username}
Group={self.username}
WorkingDirectory=/opt/hosting-manager
Environment="PATH=/opt/hosting-manager/venv/bin:/usr/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/opt/hosting-manager/venv/bin/python3 /opt/hosting-manager/app.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

# Start service
sudo systemctl daemon-reload
sudo systemctl enable hosting-manager
sudo systemctl restart hosting-manager

# Wait for service to start
sleep 3
"""
        
        run_ssh_command(self.server, self.username, deploy_script)
        print_success("Application deployed")
    
    def step9_configure_nginx(self):
        """Configure nginx reverse proxy"""
        print_step(9, self.total_steps, "Configuring nginx...")
        
        nginx_config = """
sudo tee /etc/nginx/sites-available/hosting-manager > /dev/null << 'NGINX'
server {
    listen 80;
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
}
NGINX

sudo ln -sf /etc/nginx/sites-available/hosting-manager /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
"""
        
        run_ssh_command(self.server, self.username, nginx_config)
        print_success("Nginx configured")
    
    def step10_verify_installation(self):
        """Verify the installation"""
        print_step(10, self.total_steps, "Verifying installation...")
        
        # Check service status
        result = run_ssh_command(self.server, self.username, 
                                "systemctl is-active hosting-manager")
        
        if result.stdout.strip() != "active":
            print_error("Service is not running")
            # Show logs
            logs = run_ssh_command(self.server, self.username,
                                  "sudo journalctl -u hosting-manager -n 20 --no-pager")
            print(logs.stdout)
            raise Exception("Service failed to start")
        
        print_success("Service is running")
        
        # Test API
        time.sleep(2)
        test_cmd = f"curl -f http://localhost:5000/api/health"
        result = run_ssh_command(self.server, self.username, test_cmd)
        
        if result.returncode == 0:
            print_success("API is responding")
        else:
            print_warning("API not responding yet")
    
    def print_summary(self):
        """Print installation summary"""
        print_header("✅ Installation Complete!")
        
        print(f"{Colors.CYAN}Server Details:{Colors.NC}")
        print(f"  Address:  {self.server}")
        print(f"  User:     {self.username}")
        print(f"  API URL:  http://{self.server}:5000")
        print()
        
        print(f"{Colors.CYAN}Access Commands:{Colors.NC}")
        print(f"  SSH:      ssh {self.username}@{self.server}")
        print(f"  Status:   ssh {self.username}@{self.server} 'sudo systemctl status hosting-manager'")
        print(f"  Logs:     ssh {self.username}@{self.server} 'sudo journalctl -u hosting-manager -f'")
        print()
        
        print(f"{Colors.CYAN}API Endpoints:{Colors.NC}")
        print(f"  Health:   curl http://{self.server}:5000/api/health")
        print(f"  Status:   curl http://{self.server}:5000/api/status")
        print(f"  Domains:  curl http://{self.server}:5000/api/domains")
        print()
        
        print(f"{Colors.CYAN}Next Steps:{Colors.NC}")
        print(f"  1. Test API: curl http://{self.server}:5000/api/health")
        print(f"  2. View logs: ssh {self.username}@{self.server} 'sudo journalctl -u hosting-manager -f'")
        print(f"  3. Update code: ssh {self.username}@{self.server} 'cd /opt/hosting-manager && git pull && sudo systemctl restart hosting-manager'")
        print()

def main():
    parser = argparse.ArgumentParser(
        description='Fresh server installation for Hosting Manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # With root password
  python3 fresh_install.py --server 75.119.141.162 --user deploy --repo https://github.com/user/hosting-mvp.git --root-password YOUR_PASSWORD
  
  # With SSH key (if you already have root access via key)
  python3 fresh_install.py --server 75.119.141.162 --user deploy --repo https://github.com/user/hosting-mvp.git
        """
    )
    
    parser.add_argument('--server', required=True, help='Server IP address')
    parser.add_argument('--user', required=True, help='Username to create')
    parser.add_argument('--repo', required=True, help='Git repository URL')
    parser.add_argument('--root-password', help='Root password (if not using SSH key)')
    parser.add_argument('--ssh-key', help='Path to SSH private key')
    
    args = parser.parse_args()
    
    # Check if sshpass is installed (needed for password auth)
    if args.root_password:
        result = subprocess.run('which sshpass', shell=True, capture_output=True)
        if result.returncode != 0:
            print_error("sshpass is not installed")
            print("Install it with: sudo apt-get install sshpass  (Ubuntu/Debian)")
            print("               or: brew install hudochenkov/sshpass/sshpass  (macOS)")
            sys.exit(1)
    
    # Run installation
    installer = FreshInstaller(
        server=args.server,
        username=args.user,
        repo_url=args.repo,
        ssh_key=args.ssh_key,
        root_password=args.root_password
    )
    
    installer.install()

if __name__ == '__main__':
    main()
