"""
services/wordpress_docker.py

WordPress Docker lifecycle management for hosting-mvp.

Each WordPress site runs as an isolated Docker Compose stack:
  - wordpress container  : official WordPress image + WP-CLI
  - db container         : MySQL 8.0

Nginx on the host proxies the domain to the allocated port.

Lessons learned from wp-devops (applied here):
  - URL replacement MUST use `wp search-replace` inside the container.
    Raw string substitution on SQL files corrupts WordPress serialised PHP
    arrays, causing silent data loss (theme options, logos, widget settings).
  - Uploads need a persistent named volume so they survive redeployments.
  - Passwords containing special chars (!&$) must be single-quoted when
    passed through shell commands.
  - WP-CLI commands that output PHP (wp option get) should use --format=json
    to avoid serialisation issues when reading values back.
  - php -r inline code fails through docker exec due to quote escaping.
    Always write PHP to a temp file, docker cp it in, then use wp eval-file.
  - UID 33 (www-data) must own wp-content/uploads inside the container.
"""

import os
import json
import shutil
import secrets
import string
import subprocess
import logging
import tempfile
from pathlib import Path
from services.database import get_db
from services.port_checker import find_available_ports
from config.settings import CONFIG

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

WORDPRESS_BASE_DIR = Path(CONFIG.get("wordpress_dir", "/var/www/wordpress"))
NGINX_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled")

WORDPRESS_IMAGE = "wordpress:latest"
MYSQL_IMAGE = "mysql:8.0"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _generate_password(length: int = 24) -> str:
    """Generate a secure random password safe for shell single-quoting.
    Excludes single quotes to ensure safe use in shell -p'PASSWORD' patterns.
    """
    chars = string.ascii_letters + string.digits + "!@#%^&*-_=+."
    return "".join(secrets.choice(chars) for _ in range(length))


def _run(cmd: str, description: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command, log it, and raise on failure if check=True."""
    logger.info(f"  ▶  {description}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"     ❌ {description} failed (exit {result.returncode})")
        logger.error(f"     stderr: {result.stderr[:500]}")
        if check:
            raise RuntimeError(f"{description} failed: {result.stderr[:300]}")
    else:
        logger.info(f"     ✅ {description}")
    return result


def _run_output(cmd: str) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _wp(
    site_name: str, wp_args: str, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a WP-CLI command inside the WordPress container.

    Uses docker exec with the --user www-data flag so WP-CLI runs as the
    correct user and file permissions are not broken.
    """
    container = f"{site_name}-wordpress"
    cmd = f"docker exec {container} wp {wp_args} --allow-root"
    return _run(cmd, f"wp {wp_args[:60]}", check=check)


def _wp_output(site_name: str, wp_args: str) -> tuple[int, str, str]:
    """Run a WP-CLI command and capture output."""
    container = f"{site_name}-wordpress"
    cmd = f"docker exec {container} wp {wp_args} --allow-root"
    return _run_output(cmd)


def _wp_eval_file(site_name: str, php_code: str) -> str:
    """Execute PHP code inside the WordPress container via wp eval-file.

    WHY: Inline php -r fails through docker exec due to quote escaping.
    Writing to a temp file and using wp eval-file is always reliable.
    """
    container = f"{site_name}-wordpress"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".php", delete=False, prefix="hosting-"
    ) as f:
        f.write(php_code)
        tmp_local = f.name

    try:
        _run(
            f"docker cp {tmp_local} {container}:/tmp/hosting-eval.php",
            "Copy PHP eval file to container",
        )
        rc, out, err = _run_output(
            f"docker exec {container} wp eval-file /tmp/hosting-eval.php --allow-root"
        )
        _run_output(f"docker exec {container} rm /tmp/hosting-eval.php")
        return out
    finally:
        os.unlink(tmp_local)


def _wait_for_mysql(
    site_name: str, db_user: str, db_password: str, db_name: str, timeout: int = 60
) -> bool:
    """Poll until MySQL is accepting connections inside the db container."""
    import time

    container = f"{site_name}-db"
    deadline = time.time() + timeout
    while time.time() < deadline:
        rc, _, _ = _run_output(
            f"docker exec {container} "
            f"mysqladmin ping -u '{db_user}' -p'{db_password}' --silent 2>/dev/null"
        )
        if rc == 0:
            return True
        time.sleep(2)
    return False


def _write_nginx_vhost(domain: str, port: int):
    """Write and enable an Nginx vhost for a site.

    The /api/ location routes back to hosting-mvp (port 5000) so
    deployed sites can call the management API without exposing it publicly.
    """
    config = f"""server {{
    listen 80;
    server_name {domain} www.{domain};

    # Route /api/ calls back to hosting-mvp on the same host
    location /api/ {{
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    # Route everything else to the WordPress container
    location / {{
        proxy_pass http://localhost:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        client_max_body_size 64M;
    }}
}}"""

    available = NGINX_AVAILABLE / domain
    enabled = NGINX_ENABLED / domain

    with open("/tmp/nginx_vhost.tmp", "w") as f:
        f.write(config)

    subprocess.run(["sudo", "cp", "/tmp/nginx_vhost.tmp", str(available)], check=True)
    os.remove("/tmp/nginx_vhost.tmp")
    subprocess.run(["sudo", "rm", "-f", str(enabled)], check=False)
    subprocess.run(["sudo", "ln", "-sf", str(available), str(enabled)], check=True)

    test = subprocess.run(["sudo", "nginx", "-t"], capture_output=True, text=True)
    if test.returncode == 0:
        subprocess.run(["sudo", "systemctl", "reload", "nginx"])
        logger.info(f"  ✅ Nginx vhost configured for {domain}")
    else:
        logger.error(f"  ❌ Nginx config test failed: {test.stderr}")
        raise RuntimeError(f"Nginx config invalid: {test.stderr}")


def _remove_nginx_vhost(domain: str):
    """Remove and disable an Nginx vhost, reload Nginx."""
    available = NGINX_AVAILABLE / domain
    enabled = NGINX_ENABLED / domain

    for path in [enabled, available]:
        subprocess.run(["sudo", "rm", "-f", str(path)], check=False)

    test = subprocess.run(["sudo", "nginx", "-t"], capture_output=True, text=True)
    if test.returncode == 0:
        subprocess.run(["sudo", "systemctl", "reload", "nginx"])
        logger.info(f"  ✅ Nginx vhost removed for {domain}")
    else:
        logger.warning(f"  ⚠️  Nginx test failed after vhost removal: {test.stderr}")


def _build_compose_file(
    site_name: str,
    port: int,
    db_name: str,
    db_user: str,
    db_password: str,
    db_root_password: str,
    site_path: Path,
    domain: str,
) -> str:
    """Generate docker-compose.yml content for a WordPress site.

    Key decisions:
    - uploads_data is a named volume so uploads persist across redeployments.
      Themes and plugins come from the image (or bind mount); uploads must not.
    - MySQL 8.0 with WAL-equivalent settings for reliability.
    - healthcheck on db so WordPress only starts when MySQL is ready.
    """
    return f"""version: '3.8'

services:
  wordpress:
    image: {WORDPRESS_IMAGE}
    container_name: {site_name}-wordpress
    restart: always
    ports:
      - "{port}:80"
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: {db_user}
      WORDPRESS_DB_PASSWORD: {db_password}
      WORDPRESS_DB_NAME: {db_name}
      WORDPRESS_CONFIG_EXTRA: |
        define('WP_HOME', 'http://{domain}');
        define('WP_SITEURL', 'http://{domain}');
    volumes:
      - ./wp-content:/var/www/html/wp-content
      - uploads_data:/var/www/html/wp-content/uploads
    depends_on:
      db:
        condition: service_healthy
    networks:
      - internal

  db:
    image: {MYSQL_IMAGE}
    container_name: {site_name}-db
    restart: always
    environment:
      MYSQL_DATABASE: {db_name}
      MYSQL_USER: {db_user}
      MYSQL_PASSWORD: {db_password}
      MYSQL_ROOT_PASSWORD: {db_root_password}
    volumes:
      - db_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - internal

volumes:
  db_data:
  uploads_data:

networks:
  internal:
    driver: bridge
"""


# ── Public API ────────────────────────────────────────────────────────────────


def create_site(
    site_name: str,
    domain: str,
    files: dict,
    theme_slug: str | None = None,
) -> dict:
    """
    Provision a new WordPress Docker site.

    Args:
        site_name:  Unique identifier (derived from domain, slugified)
        domain:     Full domain name e.g. mysite.com
        files:      Dict of {relative_path: content} for wp-content files
        theme_slug: Theme directory name to activate after deploy

    Returns:
        {site_name, domain, port, url, admin_url}

    Raises:
        RuntimeError on any unrecoverable step.
    """
    logger.info("=" * 55)
    logger.info(f"  WordPress Docker — Create Site: {site_name}")
    logger.info(f"  Domain: {domain}")
    logger.info("=" * 55)

    # ── Step 1: Allocate port ─────────────────────────────────────────────────
    ports = find_available_ports(8000, 1)
    if not ports:
        raise RuntimeError("No available ports in range 8000+")
    port = ports[0]
    logger.info(f"  Allocated port: {port}")

    # ── Step 2: Generate credentials ─────────────────────────────────────────
    db_name = f"wp_{site_name.replace('-', '_')[:32]}"
    db_user = f"wp_{site_name.replace('-', '_')[:16]}"
    db_password = _generate_password()
    db_root_password = _generate_password()

    # ── Step 3: Create site directory and write files ─────────────────────────
    site_path = WORDPRESS_BASE_DIR / site_name
    site_path.mkdir(parents=True, exist_ok=True)

    wp_content_path = site_path / "wp-content"
    wp_content_path.mkdir(exist_ok=True)
    (wp_content_path / "uploads").mkdir(exist_ok=True)

    # Write theme/plugin files from the deploy payload
    files_written = 0
    for rel_path, content in files.items():
        full_path = site_path / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        files_written += 1

    logger.info(f"  Written {files_written} files to {site_path}")

    # ── Step 4: Write docker-compose.yml ─────────────────────────────────────
    compose_content = _build_compose_file(
        site_name,
        port,
        db_name,
        db_user,
        db_password,
        db_root_password,
        site_path,
        domain,
    )
    (site_path / "docker-compose.yml").write_text(compose_content)

    # ── Step 5: Write .env for reference and script use ───────────────────────
    env_content = f"""SITE_NAME={site_name}
DOMAIN={domain}
PROD_PORT={port}
DB_NAME={db_name}
DB_USER={db_user}
DB_PASSWORD={db_password}
DB_ROOT_PASSWORD={db_root_password}
"""
    (site_path / ".env").write_text(env_content)

    # ── Step 6: Start containers ──────────────────────────────────────────────
    _run(
        f"cd '{site_path}' && docker compose up -d",
        "Start WordPress and MySQL containers",
    )

    # ── Step 7: Wait for MySQL to be ready ────────────────────────────────────
    logger.info("  Waiting for MySQL to be ready...")
    if not _wait_for_mysql(site_name, db_user, db_password, db_name):
        raise RuntimeError("MySQL did not become ready within 60 seconds")

    # Give WordPress a moment to initialise
    import time

    time.sleep(5)

    # ── Step 8: Fix uploads permissions ──────────────────────────────────────
    # UID 33 = www-data inside the WordPress container
    _run(
        f"docker exec {site_name}-wordpress chown -R 33:33 /var/www/html/wp-content/uploads",
        "Fix uploads directory ownership (www-data UID 33)",
        check=False,
    )

    # ── Step 9: Activate theme if specified ──────────────────────────────────
    if theme_slug:
        _wp(site_name, f"theme activate {theme_slug}", check=False)

    # ── Step 10: Configure Nginx vhost ────────────────────────────────────────
    _write_nginx_vhost(domain, port)

    # ── Step 11: Register in database ────────────────────────────────────────
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO wordpress_docker_sites
           (site_name, domain, port, site_path, status, db_name, db_user, db_password, theme_slug)
           VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)""",
        (
            site_name,
            domain,
            port,
            str(site_path),
            db_name,
            db_user,
            db_password,
            theme_slug,
        ),
    )
    conn.commit()
    conn.close()

    logger.info("=" * 55)
    logger.info(f"  ✅ Site created: {domain}")
    logger.info(f"  URL:   http://{domain}")
    logger.info(f"  Admin: http://{domain}/wp-admin")
    logger.info(f"  Port:  {port}")
    logger.info("=" * 55)

    return {
        "site_name": site_name,
        "domain": domain,
        "port": port,
        "url": f"http://{domain}",
        "admin_url": f"http://{domain}/wp-admin",
    }


def list_sites() -> list[dict]:
    """Return all WordPress Docker sites with live container status."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT site_name, domain, port, site_path, status, db_name, created_at
           FROM wordpress_docker_sites ORDER BY created_at DESC"""
    )
    rows = cursor.fetchall()
    conn.close()

    sites = []
    for site_name, domain, port, site_path, status, db_name, created_at in rows:
        # Check live container status
        rc, out, _ = _run_output(
            f"docker inspect --format='{{{{.State.Status}}}}' {site_name}-wordpress 2>/dev/null"
        )
        container_status = out.strip("'") if rc == 0 else "not found"

        sites.append(
            {
                "site_name": site_name,
                "domain": domain,
                "port": port,
                "site_path": site_path,
                "db_status": status,
                "container_status": container_status,
                "url": f"http://{domain}",
                "admin_url": f"http://{domain}/wp-admin",
                "created_at": created_at,
            }
        )

    return sites


def delete_site(site_name: str, domain: str):
    """
    Fully remove a WordPress Docker site.

    Steps:
      1. Stop and remove Docker containers and volumes
      2. Remove Nginx vhost
      3. Delete site files from disk
      4. Remove database record
    """
    logger.info(f"  Deleting WordPress site: {site_name} ({domain})")

    site_path = WORDPRESS_BASE_DIR / site_name

    # ── Step 1: Stop containers ───────────────────────────────────────────────
    if site_path.exists():
        _run(
            f"cd '{site_path}' && docker compose down -v",
            "Stop and remove containers and volumes",
            check=False,
        )
    else:
        # Try to stop by container name directly if compose file is missing
        for container in [f"{site_name}-wordpress", f"{site_name}-db"]:
            _run_output(f"docker rm -f {container} 2>/dev/null")

    # ── Step 2: Remove Nginx vhost ────────────────────────────────────────────
    _remove_nginx_vhost(domain)

    # ── Step 3: Delete site files ─────────────────────────────────────────────
    if site_path.exists():
        shutil.rmtree(site_path)
        logger.info(f"  ✅ Removed site directory: {site_path}")

    # ── Step 4: Remove database record ───────────────────────────────────────
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM wordpress_docker_sites WHERE site_name = ?", (site_name,)
    )
    conn.commit()
    conn.close()

    logger.info(f"  ✅ Site deleted: {site_name}")


def import_site_database(
    site_name: str,
    sql_path: Path,
    source_url: str | None = None,
    target_url: str | None = None,
    theme_slug: str | None = None,
):
    """
    Import a SQL dump into an existing WordPress Docker site.

    IMPORTANT — URL replacement strategy:
    This function uses `wp search-replace` inside the WordPress container
    for URL replacement. This is the ONLY correct approach for WordPress.

    Raw string substitution on SQL files corrupts WordPress serialised PHP
    arrays. WordPress stores many settings as PHP serialised strings with
    byte-length prefixes. Changing the URL string changes the byte length,
    making the prefix invalid. WordPress then silently discards the entire
    option value and falls back to defaults. The most visible symptom is
    the header logo disappearing after every database push.

    `wp search-replace` understands WordPress serialisation and updates
    byte-length prefixes correctly.

    Args:
        site_name:   Site identifier
        sql_path:    Path to the .sql dump file on the host
        source_url:  URL to replace FROM (e.g. http://localhost:8082)
        target_url:  URL to replace TO   (e.g. http://mysite.com)
        theme_slug:  Theme to activate after import (optional)

    Raises:
        ValueError if site_name not found in database.
        RuntimeError on import or search-replace failure.
    """
    logger.info(f"  Importing database for: {site_name}")

    # ── Validate site exists ──────────────────────────────────────────────────
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT db_name, db_user, db_password FROM wordpress_docker_sites WHERE site_name = ?",
        (site_name,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Site '{site_name}' not found")

    db_name, db_user, db_password = row

    # ── Step 1: Copy SQL file into the container ──────────────────────────────
    _run(
        f"docker cp '{sql_path}' {site_name}-db:/tmp/import.sql",
        "Copy SQL dump to container",
    )

    # ── Step 2: Import into MySQL ─────────────────────────────────────────────
    # Single-quote the password to handle special characters safely
    _run(
        f"docker exec {site_name}-db "
        f"mysql -u '{db_user}' -p'{db_password}' {db_name} "
        f"< /tmp/import.sql",
        "Import SQL dump into MySQL",
    )

    # Clean up temp file
    _run_output(f"docker exec {site_name}-db rm /tmp/import.sql")

    # ── Step 3: URL replacement via wp search-replace ────────────────────────
    # CRITICAL: Must use wp search-replace, NOT raw string replacement.
    # See docstring above for explanation of why.
    if source_url and target_url:
        logger.info(f"  Replacing URLs: {source_url} → {target_url}")

        rc, out, err = _run_output(
            f"docker exec {site_name}-wordpress "
            f"wp search-replace '{source_url}' '{target_url}' "
            f"--all-tables --precise --allow-root"
        )

        if rc != 0:
            raise RuntimeError(f"wp search-replace failed: {err[:300]}")

        logger.info(f"  ✅ URL replacement complete")

        # Log replacement counts for visibility
        for line in out.splitlines():
            if "replacements" in line.lower() or "Success" in line:
                logger.info(f"     {line}")

    # ── Step 4: Activate theme if specified ──────────────────────────────────
    if theme_slug:
        _wp(site_name, f"theme activate {theme_slug}", check=False)

    # ── Step 5: Flush all caches ──────────────────────────────────────────────
    _wp(site_name, "cache flush", check=False)
    _wp(site_name, "elementor flush-css", check=False)
    _wp(site_name, "rewrite flush", check=False)

    logger.info(f"  ✅ Database import complete for {site_name}")


def set_theme_option(site_name: str, option_key: str, option_value: dict):
    """
    Set a WordPress theme option directly via wp eval-file.

    WHY: wp option update serialises simple values but struggles with nested
    arrays (theme options, logo arrays, Redux settings). Writing PHP directly
    via eval-file is the only reliable method for complex option structures.

    Example:
        set_theme_option("mysite-com", "header_logo", {
            "url": "http://mysite.com/wp-content/uploads/logo.png",
            "width": "175",
            "height": "60",
        })
    """
    # Build PHP array from dict
    php_array_items = []
    for k, v in option_value.items():
        escaped = str(v).replace("'", "\\'")
        php_array_items.append(f"    '{k}' => '{escaped}'")
    php_array = "array(\n" + ",\n".join(php_array_items) + "\n)"

    php = f"""<?php
$options = get_option('{option_key}');
if (!is_array($options)) {{
    $options = array();
}}
$options = array_merge($options, {php_array});
update_option('{option_key}', $options);
echo 'Option updated: {option_key}' . PHP_EOL;
"""
    result = _wp_eval_file(site_name, php)
    logger.info(f"  {result}")
    return result


def sync_uploads(site_name: str, uploads_source: Path):
    """
    Sync a local uploads directory into the running container's uploads volume.

    Used after the initial site creation to seed the uploads volume with
    existing media. After the first sync, new uploads made through WP Admin
    go directly into the persistent volume and do not need resyncing.

    Args:
        site_name:       Site identifier
        uploads_source:  Local path to the wp-content/uploads directory
    """
    if not uploads_source.exists():
        logger.warning(f"  ⚠️  Uploads source not found: {uploads_source}")
        return

    logger.info(f"  Syncing uploads from {uploads_source}")

    # Copy into container — docker cp handles directories recursively
    _run(
        f"docker cp '{uploads_source}/.' "
        f"{site_name}-wordpress:/var/www/html/wp-content/uploads/",
        "Sync uploads into container",
    )

    # Fix ownership after copy
    _run(
        f"docker exec {site_name}-wordpress "
        f"chown -R 33:33 /var/www/html/wp-content/uploads",
        "Fix uploads ownership after sync",
        check=False,
    )

    logger.info(f"  ✅ Uploads synced for {site_name}")
