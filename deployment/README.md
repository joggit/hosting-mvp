# Hosting Manager - Deployment Guide

## Fresh Installation

For a brand new server:
```bash
python3 deployment/scripts/fresh_install.py \
  --server 75.119.141.162 \
  --user deploy \
  --repo https://github.com/yourusername/hosting-mvp.git \
  --root-password YOUR_PASSWORD
```

This installs:
- ✅ Node.js 20.x LTS
- ✅ npm, PM2, pnpm
- ✅ Python 3 + Flask
- ✅ Nginx with virtual hosting
- ✅ SQLite
- ✅ Firewall & Security

## Update Existing Installation
```bash
python3 deployment/scripts/deploy.py \
  --server 75.119.141.162 \
  --user deploy
```

## Manual Commands

### Update code
```bash
ssh deploy@SERVER 'cd /opt/hosting-manager && git pull && sudo systemctl restart hosting-manager'
```

### View logs
```bash
ssh deploy@SERVER 'sudo journalctl -u hosting-manager -f'
```

### Check PM2 processes
```bash
ssh deploy@SERVER 'pm2 list'
ssh deploy@SERVER 'pm2 logs APP_NAME'
```

### Test deployment
```bash
curl http://SERVER:5000/api/health
```

## Troubleshooting

### Service won't start
```bash
ssh deploy@SERVER 'sudo journalctl -u hosting-manager -n 50'
```

### PM2 issues
```bash
ssh deploy@SERVER 'pm2 list'
ssh deploy@SERVER 'pm2 logs --lines 100'
ssh deploy@SERVER 'pm2 delete all && pm2 save'
```

### Nginx issues
```bash
ssh deploy@SERVER 'sudo nginx -t'
ssh deploy@SERVER 'sudo systemctl status nginx'
```
