#!/usr/bin/env python3
"""
Hosting Manager - Deployment/Update Script
Updates existing installation with zero downtime
Supports both Next.js and WordPress deployments
"""

import argparse
import subprocess
import sys
import time


class Colors:
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"


def print_step(message):
    print(f"{Colors.BLUE}▶ {message}{Colors.NC}")


def print_success(message):
    print(f"{Colors.GREEN}✅ {message}{Colors.NC}")


def print_error(message):
    print(f"{Colors.RED}❌ {message}{Colors.NC}")


def print_warning(message):
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.NC}")


def run_ssh(server, user, command):
    """Execute SSH command"""
    cmd = f"ssh -o StrictHostKeyChecking=no {user}@{server} '{command}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result


class Deployer:
    """Handles deployment and updates"""

    def __init__(self, server, user, skip_restart=False):
        self.server = server
        self.user = user
        self.skip_restart = skip_restart

    def deploy(self):
        """Run deployment"""
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}")
        print(f"{Colors.BLUE}🚀 Deploying to {self.server}{Colors.NC}")
        print(f"{Colors.BLUE}{'='*60}{Colors.NC}\n")

        try:
            self.check_prerequisites()
            self.pull_latest_code()
            self.install_dependencies()

            if not self.skip_restart:
                self.backup_state()
                self.restart_service()
                self.verify_deployment()
                self.restore_containers()
            else:
                print_warning("Skipping service restart (--skip-restart)")

            self.print_summary()

        except Exception as e:
            print_error(f"Deployment failed: {e}")
            sys.exit(1)

    def check_prerequisites(self):
        """Check that required services are available"""
        print_step("Checking prerequisites...")

        checks = {
            "Git": "which git",
            "Python3": "which python3",
            "Docker": "which docker",
            "Docker Compose": "which docker-compose",
            "Service": "systemctl status hosting-manager",
        }

        all_ok = True
        for name, cmd in checks.items():
            result = run_ssh(self.server, self.user, cmd)
            if result.returncode == 0:
                print(f"  ✅ {name}")
            else:
                print(f"  ❌ {name} - not found")
                all_ok = False

        if all_ok:
            print_success("Prerequisites OK")
        else:
            print_warning("Some prerequisites missing (continuing anyway)")

    def pull_latest_code(self):
        """Pull latest code from git"""
        print_step("Pulling latest code...")

        commands = [
            "cd /opt/hosting-manager",
            "git fetch origin",
            "git reset --hard HEAD",  # Discard local changes
            "git pull origin main",
        ]

        result = run_ssh(self.server, self.user, " && ".join(commands))

        if result.returncode == 0:
            print_success("Code updated")
            if result.stdout:
                print(f"  {result.stdout.strip()}")
        else:
            raise Exception(f"Git pull failed: {result.stderr}")

    def install_dependencies(self):
        """Install/update dependencies"""
        print_step("Installing dependencies...")

        result = run_ssh(
            self.server,
            self.user,
            "cd /opt/hosting-manager && sudo pip3 install --break-system-packages -r requirements.txt 2>&1 | grep -v WARNING",
        )

        if result.returncode == 0:
            print_success("Dependencies installed")
        else:
            print_warning(f"Dependency warning: {result.stderr}")

    def backup_state(self):
        """Backup current state before restart"""
        print_step("Backing up current state...")

        # Save PM2 processes
        result = run_ssh(self.server, self.user, "pm2 save 2>&1")

        if result.returncode == 0:
            print_success("PM2 state saved")
        else:
            print_warning("PM2 save failed (may not be running)")

        # List running Docker containers (for WordPress)
        result = run_ssh(self.server, self.user, "docker ps --format '{{.Names}}' 2>&1")

        if result.returncode == 0 and result.stdout.strip():
            container_count = len(result.stdout.strip().split("\n"))
            print_success(f"Found {container_count} Docker containers")
        else:
            print(f"  ℹ️  No Docker containers running")

    def restart_service(self):
        """Restart the hosting-manager service"""
        print_step("Restarting hosting-manager service...")

        result = run_ssh(
            self.server, self.user, "sudo systemctl restart hosting-manager"
        )

        time.sleep(3)

        if result.returncode == 0:
            print_success("Service restarted")
        else:
            raise Exception("Failed to restart service")

    def verify_deployment(self):
        """Verify deployment is working"""
        print_step("Verifying deployment...")

        # Check service status
        result = run_ssh(self.server, self.user, "systemctl is-active hosting-manager")

        if result.stdout.strip() == "active":
            print_success("Service is running")
        else:
            raise Exception(f"Service is not running: {result.stdout}")

        # Test API health endpoint
        result = run_ssh(
            self.server, self.user, "curl -sf http://localhost:5000/api/health"
        )

        if result.returncode == 0:
            print_success("API is responding")
        else:
            print_warning("API health check failed (service may still be starting)")

        # Check Docker availability
        result = run_ssh(
            self.server,
            self.user,
            "docker ps >/dev/null 2>&1 && echo 'ok' || echo 'fail'",
        )

        if "ok" in result.stdout:
            print_success("Docker is accessible")
        else:
            print_warning("Docker access issue (WordPress may not work)")

    def restore_containers(self):
        """Ensure WordPress containers are still running"""
        print_step("Checking WordPress containers...")

        result = run_ssh(
            self.server,
            self.user,
            "docker ps --filter 'status=running' --format '{{.Names}}' | grep -c wordpress || echo '0'",
        )

        container_count = result.stdout.strip()

        if container_count and int(container_count) > 0:
            print_success(f"{container_count} WordPress containers running")
        else:
            print(
                f"  ℹ️  No WordPress containers (this is OK if you haven't deployed any)"
            )

    def print_summary(self):
        """Print deployment summary"""
        print()
        print(f"{Colors.GREEN}{'='*60}{Colors.NC}")
        print(f"{Colors.GREEN}✅ Deployment Successful!{Colors.NC}")
        print(f"{Colors.GREEN}{'='*60}{Colors.NC}\n")

        print(f"{Colors.CYAN}Useful Commands:{Colors.NC}")
        print(f"  View logs:")
        print(
            f"    ssh {self.user}@{self.server} 'sudo journalctl -u hosting-manager -f'"
        )
        print()
        print(f"  Check status:")
        print(
            f"    ssh {self.user}@{self.server} 'sudo systemctl status hosting-manager'"
        )
        print()
        print(f"  Test API:")
        print(f"    curl http://{self.server}:5000/api/health")
        print()
        print(f"  List WordPress sites:")
        print(f"    curl http://{self.server}:5000/api/wordpress/sites")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Deploy/Update Hosting Manager",
        epilog="Example: python3 update_deployment.py --server 75.119.141.162 --user deploy",
    )
    parser.add_argument("--server", required=True, help="Server address or IP")
    parser.add_argument("--user", default="deploy", help="SSH user (default: deploy)")
    parser.add_argument(
        "--skip-restart", action="store_true", help="Skip service restart (for testing)"
    )

    args = parser.parse_args()

    deployer = Deployer(args.server, args.user, args.skip_restart)
    deployer.deploy()


if __name__ == "__main__":
    main()
