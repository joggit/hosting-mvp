#!/usr/bin/env python3
"""
Quick Install - Assumes you already have SSH access to the server
Just deploys the application

Usage:
    python3 quick_install.py USER@SERVER REPO_URL
    
Example:
    python3 quick_install.py deploy@75.119.141.162 https://github.com/user/hosting-mvp.git
"""

import sys
import subprocess

def run(cmd):
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"❌ Command failed: {cmd}")
        sys.exit(1)

if len(sys.argv) < 3:
    print("Usage: python3 quick_install.py USER@SERVER REPO_URL")
    print("Example: python3 quick_install.py deploy@75.119.141.162 https://github.com/user/hosting-mvp.git")
    sys.exit(1)

server = sys.argv[1]
repo_url = sys.argv[2]

print(f"🚀 Quick Install to {server}")
print(f"📦 Repository: {repo_url}")
print()

# Create deployment script
deploy_script = f"""
set -e
echo "Installing dependencies..."
sudo apt-get update -qq
sudo apt-get install -y python3-venv git nginx sqlite3

echo "Setting up application..."
sudo mkdir -p /opt/hosting-manager
sudo chown $USER:$USER /opt/hosting-manager

if [ -d "/opt/hosting-manager/.git" ]; then
    cd /opt/hosting-manager && git pull origin main
else
    git clone {repo_url} /opt/hosting-manager
fi

cd /opt/hosting-manager
python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "Creating directories..."
sudo mkdir -p /var/lib/hosting-manager /var/log/hosting-manager /var/www/domains
sudo chown -R $USER:$USER /var/lib/hosting-manager /var/log/hosting-manager /var/www/domains

echo "Installing service..."
sudo tee /etc/systemd/system/hosting-manager.service > /dev/null << 'SERVICE'
[Unit]
Description=Hosting Manager API
After=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=/opt/hosting-manager
Environment="PATH=/opt/hosting-manager/venv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/opt/hosting-manager/venv/bin/python3 /opt/hosting-manager/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable hosting-manager
sudo systemctl restart hosting-manager

sleep 3

echo ""
echo "✅ Installation complete!"
echo ""
echo "Status: sudo systemctl status hosting-manager"
echo "Logs:   sudo journalctl -u hosting-manager -f"
echo "Test:   curl http://localhost:5000/api/health"
"""

# Execute on server
run(f"ssh {server} 'bash -s' << 'SCRIPT'\n{deploy_script}\nSCRIPT")

print()
print("=" * 60)
print("✅ Deployment Complete!")
print("=" * 60)
print()
print(f"Test: curl http://{server.split('@')[1]}:5000/api/health")

