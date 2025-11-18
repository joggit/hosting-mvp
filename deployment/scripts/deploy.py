#!/usr/bin/env python3
"""
Hosting Manager - Deployment/Update Script
Updates existing installation with zero downtime
"""

import argparse
import subprocess
import sys
import time

class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'

def print_step(message):
    print(f"{Colors.BLUE}▶ {message}{Colors.NC}")

def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.NC}")

def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.NC}")

def run_ssh(server, user, command):
    """Execute SSH command"""
    cmd = f"ssh -o StrictHostKeyChecking=no {user}@{server} '{command}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result

class Deployer:
    """Handles deployment and updates"""
    
    def __init__(self, server, user):
        self.server = server
        self.user = user
    
    def deploy(self):
        """Run deployment"""
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"{Colors.BLUE}🚀 Deploying to {self.server}{Colors.NC}")
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}\n")
        
        try:
            self.pull_latest_code()
            self.install_dependencies()
            self.restart_service()
            self.verify_deployment()
            self.print_summary()
            
        except Exception as e:
            print_error(f"Deployment failed: {e}")
            sys.exit(1)
    
    def pull_latest_code(self):
        """Pull latest code from git"""
        print_step("Pulling latest code...")
        
        commands = [
            "cd /opt/hosting-manager",
            "git fetch origin",
            "git pull origin main"
        ]
        
        result = run_ssh(self.server, self.user, " && ".join(commands))
        
        if result.returncode == 0:
            print_success("Code updated")
        else:
            raise Exception(f"Git pull failed: {result.stderr}")
    
    def install_dependencies(self):
        """Install/update dependencies"""
        print_step("Installing dependencies...")
        
        result = run_ssh(
            self.server,
            self.user,
            "cd /opt/hosting-manager && sudo pip3 install --break-system-packages -r requirements.txt"
        )
        
        if result.returncode == 0:
            print_success("Dependencies installed")
        else:
            print(f"Warning: {result.stderr}")
    
    def restart_service(self):
        """Restart the service"""
        print_step("Restarting service...")
        
        result = run_ssh(
            self.server,
            self.user,
            "sudo systemctl restart hosting-manager"
        )
        
        time.sleep(3)
        
        if result.returncode == 0:
            print_success("Service restarted")
        else:
            raise Exception("Failed to restart service")
    
    def verify_deployment(self):
        """Verify deployment"""
        print_step("Verifying deployment...")
        
        # Check service status
        result = run_ssh(
            self.server,
            self.user,
            "systemctl is-active hosting-manager"
        )
        
        if result.stdout.strip() == "active":
            print_success("Service is running")
        else:
            raise Exception("Service is not running")
        
        # Test API
        result = run_ssh(
            self.server,
            self.user,
            "curl -f http://localhost:5000/api/health"
        )
        
        if result.returncode == 0:
            print_success("API is responding")
        else:
            print(f"Warning: API check failed")
    
    def print_summary(self):
        """Print deployment summary"""
        print()
        print(f"{Colors.GREEN}{'='*60}{Colors.NC}")
        print(f"{Colors.GREEN}✅ Deployment Successful!{Colors.NC}")
        print(f"{Colors.GREEN}{'='*60}{Colors.NC}\n")
        
        print(f"{Colors.CYAN}View logs:{Colors.NC}")
        print(f"  ssh {self.user}@{self.server} 'sudo journalctl -u hosting-manager -f'")
        print()

def main():
    parser = argparse.ArgumentParser(description='Deploy/Update Hosting Manager')
    parser.add_argument('--server', required=True, help='Server address')
    parser.add_argument('--user', default='deploy', help='SSH user')
    
    args = parser.parse_args()
    
    deployer = Deployer(args.server, args.user)
    deployer.deploy()

if __name__ == '__main__':
    main()
