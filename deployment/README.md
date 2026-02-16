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

## WordPress Docker (same host as Next.js)

WordPress can be deployed as **Docker containers** on the same host. Each site gets its own stack (nginx + WordPress PHP-FPM + MySQL). Host nginx proxies by domain to the container port (9080+).

- **Requires:** Docker and Docker Compose on the server. Deploy user must be able to run `docker compose` (e.g. in `docker` group).
- **API:** `POST /api/deploy/wordpress` with `{ name, files, domain_config: { domain } }`. Theme files (paths like `theme/style.css`) are written under `/var/lib/hosting-manager/wordpress-docker/<site_name>/theme/`, then `docker compose up -d` runs in that directory and nginx is configured for the domain.
- **List:** `GET /api/deploy/wordpress` returns all WordPress Docker sites.
- **Delete:** `DELETE /api/deploy/wordpress/<site_name>` removes the site (containers, nginx config, files, DB row).
- **Base path:** Set `WORDPRESS_DOCKER_BASE` on the server to override `/var/lib/hosting-manager/wordpress-docker`.

The WordPress starter repo (`npm run deploy:hosting -- domain.com`) uses this endpoint by default.

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
