# hosting-mvp

Control plane API for deploying and managing WordPress and Next.js sites on a single VPS. Handles Docker orchestration for WordPress, PM2 process management for Next.js, Nginx vhost configuration, SSL, domain registration, and full site lifecycle management.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     hosting-mvp  (Flask :5000)                   │
│                                                                  │
│  /api/deploy/nodejs      → PM2 + Nginx for Next.js apps         │
│  /api/deploy/wordpress   → Docker + Nginx for WordPress sites    │
│  /api/domains            → Domain registry and management        │
│  /api/ssl                → Certbot SSL automation                │
└──────────┬────────────────────────────┬─────────────────────────┘
           │                            │
    ┌──────▼──────┐              ┌──────▼──────┐
    │  PM2        │              │  Docker     │
    │  Next.js    │              │  WordPress  │
    │  processes  │              │  containers │
    └──────┬──────┘              └──────┬──────┘
           │                            │
    ┌──────▼────────────────────────────▼──────┐
    │              Nginx (host)                 │
    │  Proxies domains → correct port/container │
    └───────────────────────────────────────────┘
```

### Three-System Integration

hosting-mvp is the infrastructure layer. The other two systems call it:

```
┌─────────────────┐    POST /api/deploy/wordpress       ┌──────────────────┐
│   wp-devops     │ ──────────────────────────────────► │                  │
│                 │    POST /api/deploy/wordpress/       │   hosting-mvp    │
│  (CLI tool)     │         <site>/import               │   (this repo)    │
└─────────────────┘                                     │                  │
                                                        │                  │
┌─────────────────┐    POST /api/deploy/nodejs          │                  │
│ nextjs-starter  │ ──────────────────────────────────► │                  │
│                 │                                     └──────────────────┘
│ (Figma → Next)  │
└─────────────────┘
```

### Site Types

| Type      | Runtime | Process Manager | Files                        |
| --------- | ------- | --------------- | ---------------------------- |
| Next.js   | Node.js | PM2 (fork mode) | `/var/www/sites/<domain>/`   |
| WordPress | PHP-FPM | Docker Compose  | `/var/www/wordpress/<site>/` |

---

## Setup

### Requirements

- Python 3.10+
- Node.js 18+ and PM2 — `npm install -g pm2`
- Docker and Docker Compose
- Nginx
- Certbot — `apt install certbot python3-certbot-nginx`

### Install

```bash
git clone <repo>
cd hosting-mvp

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python app.py
```

API starts on `http://0.0.0.0:5000`.

### Run with PM2 (production)

```bash
pm2 start app.py --name hosting-mvp --interpreter python3
pm2 save && pm2 startup
```

### Configuration

Edit `config/settings.py`:

```python
CONFIG = {
    "database_path": "/var/data/hosting.db",   # SQLite database
    "web_root":      "/var/www/sites",          # Next.js app root
    "wordpress_dir": "/var/www/wordpress",      # WordPress Docker root
}
```

---

## API Reference

### Next.js / Node.js

#### Deploy

```
POST /api/deploy/nodejs
Content-Type: application/json
```

```json
{
  "name": "my-site",
  "files": {
    "package.json": "{ \"name\": \"my-site\", ... }",
    "app/page.tsx": "export default function Page() { ... }"
  },
  "domain_config": { "domain": "mysite.com" },
  "deployConfig": { "port": 3001 }
}
```

Pipeline:

1. Validate name and files
2. Check domain availability
3. Patch `package.json` (add build/start scripts if missing)
4. Patch `next.config.js` (remove Next.js 15+ incompatible options)
5. Allocate port (auto if not specified)
6. Write files to `/var/www/sites/<domain>/`
7. `npm install` + `npm run build`
8. Start via PM2 in fork mode
9. Write Nginx vhost → reload Nginx
10. Register in database

```json
{
  "success": true,
  "site_name": "my-site",
  "port": 3001,
  "process_manager": "pm2",
  "domain": { "domain": "mysite.com", "url": "http://mysite.com" }
}
```

#### List all Next.js sites

```
GET /api/deploy/nodejs
```

#### Get site details

```
GET /api/deploy/nodejs/<site_name>
```

Returns port, PM2 status, Nginx config presence, domain info, filesystem status.

#### Delete a site

```
DELETE /api/deploy/nodejs/<site_name>
```

Stops PM2 process → removes Nginx vhost → deletes files → cleans database.

---

### WordPress (Docker)

#### Deploy

```
POST /api/deploy/wordpress
Content-Type: application/json
```

```json
{
  "name": "my-wp-site",
  "files": {
    "wp-content/themes/mytheme/style.css": "..."
  },
  "domain_config": { "domain": "mysite.com" },
  "theme_slug": "mytheme"
}
```

Pipeline:

1. Validate name, files, domain
2. Check domain not already registered
3. Create Docker Compose stack (WordPress + MySQL) via `services/wordpress_docker.py`
4. Copy theme/plugin files into the container
5. Allocate port and write Nginx vhost
6. Register domain and site in database

```json
{
  "success": true,
  "site_name": "mysite-com",
  "url": "http://mysite.com",
  "admin_url": "http://mysite.com/wp-admin",
  "port": 8010
}
```

#### List WordPress sites

```
GET /api/deploy/wordpress
```

#### Delete a WordPress site

```
DELETE /api/deploy/wordpress/<site_name>
```

Stops and removes Docker containers → Nginx vhost → files → database entries.

#### Import / mirror a WordPress database

```
POST /api/deploy/wordpress/<site_name>/import
Content-Type: multipart/form-data
```

| Field           | Type   | Description                                               |
| --------------- | ------ | --------------------------------------------------------- |
| `dump`          | file   | `.sql` dump file (required)                               |
| `source_url`    | string | Original URL to replace (e.g. `http://localhost:8082`)    |
| `target_url`    | string | Production URL to replace with (e.g. `http://mysite.com`) |
| `target_domain` | string | Alternative to `target_url` — domain only                 |
| `theme_slug`    | string | Theme to activate after import                            |

> **Note:** URL replacement inside this endpoint uses `wp search-replace` via WP-CLI
> inside the container which correctly handles serialised PHP data. Do not use raw
> string replacement on SQL dumps — it corrupts WordPress serialised arrays and causes
> silent data loss (theme options, widget settings, logo URLs etc.).

---

### Domains

#### List all domains

```
GET /api/domains
```

#### Register a domain

```
POST /api/domains
```

```json
{ "domain": "mysite.com", "ssl_enabled": false }
```

#### Get domain

```
GET /api/domains/<domain>
```

#### Delete domain

```
DELETE /api/domains/<domain>
```

#### Check available ports

```
POST /api/check-ports
```

```json
{ "startPort": 3000, "count": 5 }
```

---

## Database Schema

SQLite at `CONFIG["database_path"]`. WAL mode enabled for concurrent reads.

### Active Tables

| Table                    | Purpose                                                     |
| ------------------------ | ----------------------------------------------------------- |
| `domains`                | All registered domains — name, port, app, SSL, status       |
| `processes`              | PM2-managed Node.js processes — name, port, PID, status     |
| `wordpress_docker_sites` | WordPress Docker sites — name, domain, port, DB credentials |
| `deployment_logs`        | Audit trail for all deploy/delete/import actions            |

### Unused / Legacy Tables

| Table                   | Status         | Notes                                                                                    |
| ----------------------- | -------------- | ---------------------------------------------------------------------------------------- |
| `wordpress_sites`       | **Unused**     | Pre-Docker WordPress approach — safe to drop                                             |
| `wordpress_plugins`     | **Unused**     | Belongs to `wordpress_sites` — safe to drop                                              |
| `wordpress_themes`      | **Unused**     | Belongs to `wordpress_sites` — safe to drop                                              |
| `wordpress_cli_history` | **Unused**     | Belongs to `wordpress_sites` — safe to drop                                              |
| `pages`                 | Partially used | Created by `routes/pages.py`, only populated during Next.js deploys with `selectedPages` |

---

## Project Structure

```
hosting-mvp/
├── app.py                          # Flask entry point — init DB, register routes, start server
├── config/
│   └── settings.py                 # CONFIG dict — paths, ports, environment
├── routes/
│   ├── __init__.py                 # Auto-discovers and registers all route modules
│   ├── deployment.py               # /api/deploy/nodejs + /api/deploy/wordpress
│   ├── domains.py                  # /api/domains + /api/check-ports
│   ├── ssl.py                      # /api/ssl — Certbot automation
│   └── pages.py                    # /api/pages — page registry per site
├── services/
│   ├── database.py                 # SQLite init, schema, get_db()
│   ├── port_checker.py             # find_available_ports()
│   └── wordpress_docker.py         # Docker Compose lifecycle for WordPress
└── utils/
    └── logger.py                   # Structured logging setup
```

### Route Auto-Discovery

Any `.py` file in `routes/` with a `register_routes(app)` function is loaded automatically on startup. To add a new route group:

```python
# routes/myfeature.py
def register_routes(app):
    @app.route("/api/myfeature", methods=["GET"])
    def my_endpoint():
        return jsonify({"success": True})
```

No manual registration needed.

---

## Nginx Template

Both site types use this vhost pattern. WordPress containers are accessed by port, not by socket, so the pattern is identical:

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    # Route /api/ calls back to hosting-mvp on the same host
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Route everything else to the app
    location / {
        proxy_pass http://localhost:<PORT>;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
}
```

---

## Logging

All deployment steps logged to stdout (captured by PM2) and written to `deployment_logs`.

```bash
# Live logs
pm2 logs hosting-mvp

# Audit trail
sqlite3 /var/data/hosting.db \
  "SELECT created_at, domain_name, action, status, message
   FROM deployment_logs ORDER BY created_at DESC LIMIT 20;"
```

---

## Known Issues and Planned Improvements

### Critical

**Serialised PHP corruption on DB import** — the import endpoint in `deployment.py` must use `wp search-replace` via WP-CLI inside the Docker container for URL replacement. Raw string substitution on SQL files corrupts WordPress serialised PHP arrays causing silent data loss. Theme options (logos, colours, widget settings) are the most common victims.

**No API authentication** — the API has no auth layer. It must run behind a firewall or on a private network. Add API key middleware (`flask-httpauth` or a simple decorator) before any public exposure.

**Synchronous builds block the worker** — `npm install` and `npm run build` can take up to 15 minutes and block the Flask worker for the duration. Move long-running builds to a background job queue (Redis + RQ or Celery) to allow concurrent deployments.

### Housekeeping

**Remove legacy WordPress tables** — `wordpress_sites`, `wordpress_plugins`, `wordpress_themes`, `wordpress_cli_history` are unused pre-Docker remnants. They add noise to the schema and should be dropped in a migration.

**Remove debugging code in `deployment.py`** — the file listing loop (`# START OF DEBUGGING CODE` ... `# END OF DEBUGGING CODE`) logs every filename and size on every deploy. Remove before production use.

**Consolidate `create_deployment_pages`** — this helper is defined as a nested function inside `register_routes()` in `deployment.py`. It should live in a `services/pages.py` module so it can be tested and reused independently.

**`/api/sites` alias is confusing** — `domains.py` registers `/api/sites` as an alias for `/api/domains`. This implies sites and domains are the same concept, which they are not (a site can have multiple domains; a domain entry might not have a live site). The alias should be removed or pointed at a proper unified sites endpoint.

### Future

- Replace SQLite with PostgreSQL when hosting-mvp runs across multiple servers
- Add a proper `/api/sites` unified endpoint that merges `processes`, `domains`, and `wordpress_docker_sites` into one response
- Add rollback — if deploy fails mid-way, partial state (PM2 process running but Nginx not configured) currently requires manual cleanup
- Add `GET /api/health` endpoint listing all sites, their PM2/Docker status, and last deploy timestamp in one call
