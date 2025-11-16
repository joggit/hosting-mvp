#!/usr/bin/env python3
"""
Rollback to previous version
"""
import os
import sys
import subprocess
from pathlib import Path

def run(cmd, check=True):
    """Run command"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"❌ Command failed: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result

def main():
    if os.geteuid() != 0:
        print("❌ Must run as root")
        sys.exit(1)
    
    app_dir = Path('/opt/hosting-manager')
    os.chdir(app_dir)
    
    # Show recent commits
    print("Recent commits:")
    run('git log --oneline -10', check=False)
    print()
    
    commit = input("Enter commit hash to rollback to: ").strip()
    if not commit:
        print("❌ No commit specified")
        sys.exit(1)
    
    print(f"🔄 Rolling back to {commit}...")
    
    # Checkout commit
    run(f'git checkout {commit}')
    
    # Update dependencies
    venv_pip = app_dir / 'venv' / 'bin' / 'pip'
    run(f'{venv_pip} install -r requirements.txt')
    
    # Restart service
    run('systemctl restart hosting-manager')
    
    print(f"✅ Rolled back to {commit}")
    print("Check status: systemctl status hosting-manager")

if __name__ == '__main__':
    main()
