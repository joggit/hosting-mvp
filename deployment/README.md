# Deployment Guide - Python Scripts

All deployment scripts are Python-based for consistency and cross-platform compatibility.

## Quick Start - Single Server
```bash
# On the server
curl -o deploy.py https://raw.githubusercontent.com/YOUR_USERNAME/hosting-mvp/main/deployment/scripts/deploy.py
chmod +x deploy.py
sudo python3 deploy.py https://github.com/YOUR_USERNAME/hosting-mvp.git
```

## Multi-Server Deployment
```bash
# On your local machine (requires Python 3.7+)
pip3 install requests  # For health checks

cd deployment/scripts
python3 deploy_multi.py \
  --repo https://github.com/YOUR_USERNAME/hosting-mvp.git \
  --parallel 5 \
  server1.com server2.com server3.com
```

## Update Existing Deployment
```bash
# On the server
sudo python3 /opt/hosting-manager/deployment/scripts/update.py
```

## Rollback
```bash
# On the server
sudo python3 /opt/hosting-manager/deployment/scripts/rollback.py
```

## Health Check
```bash
# From local machine
cd deployment/scripts
python3 health_check.py server1.com server2.com server3.com
```

## Script Options

### deploy.py
```bash
sudo python3 deploy.py <repo-url> [--branch main] [--dir /opt/hosting-manager]
```

### deploy_multi.py
```bash
python3 deploy_multi.py \
  --repo <repo-url> \
  --branch main \
  --parallel 3 \
  server1 server2 server3
```

### health_check.py
```bash
python3 health_check.py [--port 5000] server1 server2 server3
```

## Examples

### Deploy to Single Server
```bash
sudo python3 deploy.py https://github.com/user/hosting-mvp.git
```

### Deploy to Multiple Servers (3 at a time)
```bash
python3 deploy_multi.py \
  --repo https://github.com/user/hosting-mvp.git \
  --parallel 3 \
  75.119.141.162 192.168.1.100 192.168.1.101
```

### Check Health of All Servers
```bash
python3 health_check.py 75.119.141.162 192.168.1.100 192.168.1.101
```

## Requirements

- Python 3.7+
- SSH access to servers (for multi-deploy)
- Root access on target servers

## Troubleshooting

**Deployment fails:**
```bash
# Check service logs
ssh root@server "journalctl -u hosting-manager -n 50"
```

**Health check fails:**
```bash
# Verify port is accessible
curl http://server:5000/api/health
```

**Update fails:**
```bash
# Check git status
cd /opt/hosting-manager
git status
git log -5
```
