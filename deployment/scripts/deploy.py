#!/usr/bin/env python3
"""
Hosting Manager - Deployment Script
Handles installation, updates, and configuration
"""
import os
import sys
import subprocess
import shutil
import argparse
from pathlib import Path
from datetime import datetime

class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

def print_step(step, total, message):
    """Print formatted step message"""
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

def run_command(cmd, check=True, capture_output=False):
    """Run shell command with error handling"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=check,
            capture_output=capture_output,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {cmd}")
        if capture_output:
            print(e.stderr)
        return None

class Deployer:
    """Handles deployment operations"""
    
    def __init__(self, repo_url, branch='main', app_dir='/opt/hosting-manager'):
        self.repo_url = repo_url
        self.branch = branch
        self.app_dir = Path(app_dir)
        self.venv_dir = self.app_dir / 'venv'
        
        # Check if running as root
        if os.geteuid() != 0:
            print_error("This script must be run as root (use sudo)")
            sys.exit(1)
    
    def deploy(self):
        """Run complete deployment"""
        print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")
        print(f"{Colors.BLUE}Hosting Manager - Deployment{Colors.NC}")
        print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")
        print(f"Repository: {self.repo_url}")
        print(f"Branch: {self.branch}")
        print(f"Install Directory: {self.app_dir}")
        print()
        
        steps = [
            self.install_system_dependencies,
            self.setup_application,
            self.setup_python_environment,
            self.setup_database,
            self.install_systemd_service,
            self.configure_nginx,
            self.start_service,
            self.verify_deployment
        ]
        
        total_steps = len(steps)
        
        for i, step in enumerate(steps, 1):
            try:
                step(i, total_steps)
            except Exception as e:
                print_error(f"Step {i} failed: {e}")
                sys.exit(1)
        
        self.print_summary()
    
    def install_system_dependencies(self, step, total):
        """Install required system packages"""
        print_step(step, total, "Installing system dependencies...")
        
        packages = [
            'python3', 'python3-pip', 'python3-venv',
            'git', 'nginx', 'sqlite3', 'curl'
        ]
        
        # Update package list
        run_command('apt-get update -qq')
        
        # Install packages
        pkg_list = ' '.join(packages)
        run_command(f'apt-get install -y {pkg_list}')
        
        print_success("System dependencies installed")
    
    def setup_application(self, step, total):
        """Clone or update repository"""
        print_step(step, total, "Setting up application...")
        
        if (self.app_dir / '.git').exists():
            print("Updating existing installation...")
            os.chdir(self.app_dir)
            run_command('git fetch origin')
            run_command(f'git checkout {self.branch}')
            run_command(f'git pull origin {self.branch}')
        else:
            print("Fresh installation...")
            self.app_dir.parent.mkdir(parents=True, exist_ok=True)
            run_command(f'git clone -b {self.branch} {self.repo_url} {self.app_dir}')
            os.chdir(self.app_dir)
        
        print_success("Application code ready")
    
    def setup_python_environment(self, step, total):
        """Setup Python virtual environment"""
        print_step(step, total, "Setting up Python environment...")
        
        if not self.venv_dir.exists():
            run_command(f'python3 -m venv {self.venv_dir}')
        
        # Activate and install requirements
        pip_path = self.venv_dir / 'bin' / 'pip'
        run_command(f'{pip_path} install --upgrade pip')
        run_command(f'{pip_path} install -r requirements.txt')
        
        print_success("Python environment ready")
    
    def setup_database(self, step, total):
        """Setup database and directories"""
        print_step(step, total, "Setting up database...")
        
        dirs = [
            '/var/lib/hosting-manager',
            '/var/log/hosting-manager',
            '/var/www/domains'
        ]
        
        for directory in dirs:
            Path(directory).mkdir(parents=True, exist_ok=True)
            run_command(f'chown -R www-data:www-data {directory}')
        
        print_success("Database directories created")
    
    def install_systemd_service(self, step, total):
        """Install and configure systemd service"""
        print_step(step, total, "Installing systemd service...")
        
        service_file = self.app_dir / 'deployment' / 'systemd' / 'hosting-manager.service'
        if service_file.exists():
            shutil.copy(service_file, '/etc/systemd/system/')
            run_command('systemctl daemon-reload')
            print_success("Systemd service installed")
        else:
            print_warning("Systemd service file not found, skipping...")
    
    def configure_nginx(self, step, total):
        """Configure nginx reverse proxy"""
        print_step(step, total, "Configuring nginx...")
        
        nginx_conf = self.app_dir / 'deployment' / 'nginx' / 'hosting-manager.conf'
        if nginx_conf.exists():
            shutil.copy(nginx_conf, '/etc/nginx/sites-available/')
            
            # Create symlink
            src = Path('/etc/nginx/sites-available/hosting-manager.conf')
            dst = Path('/etc/nginx/sites-enabled/hosting-manager.conf')
            if dst.exists():
                dst.unlink()
            dst.symlink_to(src)
            
            # Test nginx config
            result = run_command('nginx -t', check=False, capture_output=True)
            if result and result.returncode == 0:
                run_command('systemctl reload nginx')
                print_success("Nginx configured")
            else:
                print_warning("Nginx config has errors, skipping...")
        else:
            print_warning("Nginx config not found, skipping...")
    
    def start_service(self, step, total):
        """Start the application service"""
        print_step(step, total, "Starting service...")
        
        run_command('systemctl enable hosting-manager')
        run_command('systemctl restart hosting-manager')
        
        # Wait for service to start
        import time
        time.sleep(3)
        
        print_success("Service started")
    
    def verify_deployment(self, step, total):
        """Verify the deployment"""
        print_step(step, total, "Verifying deployment...")
        
        # Check if service is running
        result = run_command(
            'systemctl is-active hosting-manager',
            check=False,
            capture_output=True
        )
        
        if result and result.returncode == 0:
            print_success("Service is running")
        else:
            print_error("Service failed to start")
            print("Check logs: journalctl -u hosting-manager -n 50")
            sys.exit(1)
        
        # Test health endpoint
        result = run_command(
            'curl -f http://localhost:5000/api/health',
            check=False,
            capture_output=True
        )
        
        if result and result.returncode == 0:
            print_success("API is responding")
        else:
            print_warning("API not responding yet (might still be starting)")
    
    def print_summary(self):
        """Print deployment summary"""
        print()
        print(f"{Colors.GREEN}{'=' * 50}{Colors.NC}")
        print(f"{Colors.GREEN}Deployment Complete!{Colors.NC}")
        print(f"{Colors.GREEN}{'=' * 50}{Colors.NC}")
        print()
        print("Useful commands:")
        print(f"  Service Status: systemctl status hosting-manager")
        print(f"  View Logs:      journalctl -u hosting-manager -f")
        print(f"  API Health:     curl http://localhost:5000/api/health")
        print()

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Deploy Hosting Manager')
    parser.add_argument('repo_url', help='Git repository URL')
    parser.add_argument('--branch', default='main', help='Git branch (default: main)')
    parser.add_argument('--dir', default='/opt/hosting-manager', help='Installation directory')
    
    args = parser.parse_args()
    
    deployer = Deployer(args.repo_url, args.branch, args.dir)
    deployer.deploy()

if __name__ == '__main__':
    main()
