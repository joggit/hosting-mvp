#!/usr/bin/env python3
"""
Update deployed Hosting Manager
"""
import os
import sys
import subprocess
from pathlib import Path

def run(cmd):
    """Run command and check result"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Command failed: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result

def main():
    if os.geteuid() != 0:
        print("❌ Must run as root")
        sys.exit(1)
    
    app_dir = Path('/opt/hosting-manager')
    if not app_dir.exists():
        print("❌ Application not installed")
        sys.exit(1)
    
    print("🔄 Updating Hosting Manager...")
    
    # Pull latest code
    os.chdir(app_dir)
    run('git pull origin main')
    
    # Update dependencies
    venv_pip = app_dir / 'venv' / 'bin' / 'pip'
    run(f'{venv_pip} install -r requirements.txt')
    
    # Restart service
    run('systemctl restart hosting-manager')
    
    print("✅ Update complete")
    print("Check status: systemctl status hosting-manager")

if __name__ == '__main__':
    main()
