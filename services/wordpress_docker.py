"""
WordPress deployment via Docker containers.
One compose stack per site; host nginx proxies by domain to the container port.
"""

import os
import subprocess
import logging
import shutil
import time
from pathlib import Path

from services.database import get_db
from services.port_checker import find_available_ports
from services.nginx_config import create_nginx_reverse_proxy, remove_nginx_site, reload_nginx

logger = logging.getLogger(__name__)

WORDPRESS_DOCKER_BASE = Path(
    os.getenv("WORDPRESS_DOCKER_BASE", "/var/lib/hosting-manager/wordpress-docker")
)
PORT_START = 9080
THEME_SLUG = "wordpress-starter"

# Nginx config for the container (proxy PHP to wordpress:9000)
CONTAINER_NGINX_CONF = """server {
    listen 80;
    server_name _;
    root /var/www/html;
    index index.php;

    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    location ~ \\.php$ {
        try_files $uri =404;
        fastcgi_split_path_info ^(.+\\.php)(/.+)$;
        fastcgi_pass wordpress:9000;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $fastcgi_path_info;
        fastcgi_buffers 16 16k;
        fastcgi_buffer_size 32k;
    }
}
"""


def _run(cmd, cwd=None, check=True, capture=True, timeout=300):
    kwargs = {"capture_output": capture, "text": True, "timeout": timeout}
    if cwd:
        kwargs["cwd"] = str(cwd)
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"Exit {result.returncode}")
    return result


def _allocate_port():
    used = set()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT port FROM wordpress_docker_sites WHERE port IS NOT NULL")
    for (p,) in cursor.fetchall():
        used.add(p)
    conn.close()
    # Get multiple candidates (not bound on host), pick first not already in DB
    candidates = find_available_ports(PORT_START, 50)
    for port in candidates:
        if port not in used:
            return port
    raise RuntimeError(f"No available port in range starting {PORT_START} (tried {len(candidates)} ports, all in use or assigned)")


def _generate_password(length=32):
    import secrets
    import string
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))


def _write_compose(site_dir: Path, port: int, db_name: str, db_user: str, db_pass: str):
    compose = f"""services:
  nginx:
    image: nginx:alpine
    ports:
      - "{port}:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - wp_html:/var/www/html:ro
      - ./theme:/var/www/html/wp-content/themes/{THEME_SLUG}:ro
    depends_on:
      - wordpress

  wordpress:
    image: wordpress:fpm
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: {db_user}
      WORDPRESS_DB_PASSWORD: {db_pass}
      WORDPRESS_DB_NAME: {db_name}
    volumes:
      - wp_html:/var/www/html
      - ./theme:/var/www/html/wp-content/themes/{THEME_SLUG}
    depends_on:
      db:
        condition: service_healthy

  db:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: {db_name}
      MYSQL_USER: {db_user}
      MYSQL_PASSWORD: {db_pass}
      MYSQL_ROOT_PASSWORD: {db_pass}
    volumes:
      - db_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  wp_html:
  db_data:
"""
    (site_dir / "docker-compose.yml").write_text(compose)


def create_site(site_name: str, domain: str, files: dict) -> dict:
    """
    Create a WordPress Docker site: write theme files, generate compose, start stack, create nginx.
    files: dict of path -> content (paths like "theme/style.css").
    """
    site_dir = WORDPRESS_DOCKER_BASE / site_name
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    theme_dir = site_dir / "theme"
    theme_dir.mkdir(exist_ok=True)

    for rel_path, content in files.items():
        if not rel_path.strip() or ".." in rel_path:
            continue
        full = site_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        text = content if isinstance(content, str) else str(content)
        full.write_text(text, encoding="utf-8", errors="replace")

    port = _allocate_port()
    db_name = f"wp_{site_name}".replace("-", "_")[:64]
    db_user = db_name
    db_pass = _generate_password()

    (site_dir / "nginx.conf").write_text(CONTAINER_NGINX_CONF)
    _write_compose(site_dir, port, db_name, db_user, db_pass)

    _run(["docker", "compose", "up", "-d"], cwd=site_dir, timeout=120)
    create_nginx_reverse_proxy(domain, port)
    reload_nginx()

    # Insert site record (retry on SQLite "database is locked")
    conn = None
    for attempt in range(5):
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO wordpress_docker_sites (site_name, domain, port, site_path, status, db_name, db_user, db_password)
                VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                """,
                (site_name, domain, port, str(site_dir), db_name, db_user, db_pass),
            )
            conn.commit()
            conn.close()
            conn = None
            break
        except Exception as e:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise

    return {
        "port": port,
        "site_path": str(site_dir),
        "site_name": site_name,
        "url": f"http://{domain}",
        "admin_url": f"http://{domain}/wp-admin",
    }


def delete_site(site_name: str, domain: str = None):
    """Stop containers, remove nginx config, remove dir, delete from DB."""
    site_dir = WORDPRESS_DOCKER_BASE / site_name
    if not domain:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT domain FROM wordpress_docker_sites WHERE site_name = ?", (site_name,))
        row = cursor.fetchone()
        conn.close()
        domain = row[0] if row else None
    if domain:
        try:
            remove_nginx_site(domain)
            reload_nginx()
        except Exception as e:
            logger.warning("Remove nginx: %s", e)
    if site_dir.exists():
        try:
            _run(["docker", "compose", "down", "-v"], cwd=site_dir, timeout=60)
        except Exception as e:
            logger.warning("Compose down: %s", e)
        shutil.rmtree(site_dir, ignore_errors=True)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM wordpress_docker_sites WHERE site_name = ?", (site_name,))
    conn.commit()
    conn.close()


def _get_site_db_credentials(site_name: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT site_path, db_name, db_user, db_password FROM wordpress_docker_sites WHERE site_name = ?",
        (site_name,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        raise ValueError(f"Site not found: {site_name}")
    site_path, db_name, db_user, db_password = row
    if not all((db_name, db_user, db_password)):
        raise ValueError(f"Site {site_name} has no DB credentials (deploy may predate mirror support)")
    return Path(site_path), db_name, db_user, db_password


def import_site_database(
    site_name: str,
    dump_path: Path,
    source_url: str = None,
    target_url: str = None,
) -> None:
    """
    Import a SQL dump into the site's MySQL container.
    If source_url and target_url are set, replace the former with the latter in the dump before importing.
    """
    site_dir, db_name, db_user, db_password = _get_site_db_credentials(site_name)
    dump_path = Path(dump_path)
    if not dump_path.is_file():
        raise FileNotFoundError(f"Dump file not found: {dump_path}")

    import_path = dump_path
    if source_url and target_url and source_url != target_url:
        content = dump_path.read_text(encoding="utf-8", errors="replace")
        content = content.replace(source_url, target_url)
        import_path = site_dir / ".import_dump.sql"
        import_path.write_text(content, encoding="utf-8", errors="replace")

    # Use -h 127.0.0.1 so mysql client connects via TCP (socket path can differ in container)
    try:
        with open(import_path, "rb") as f:
            r = subprocess.run(
                ["docker", "compose", "exec", "-T", "db", "mysql", "-h", "127.0.0.1", f"-u{db_user}", f"-p{db_password}", db_name],
                cwd=site_dir,
                stdin=f,
                capture_output=True,
                text=False,
                timeout=600,
            )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", errors="replace") if r.stderr else "Import failed")
    except Exception:
        if import_path != dump_path and import_path.exists():
            import_path.unlink(missing_ok=True)
        raise
    if import_path != dump_path and import_path.exists():
        import_path.unlink(missing_ok=True)
    logger.info("Database import completed for %s", site_name)


def list_sites():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT site_name, domain, port, site_path, status, created_at FROM wordpress_docker_sites ORDER BY created_at DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "site_name": r[0],
            "domain": r[1],
            "port": r[2],
            "site_path": r[3],
            "status": r[4],
            "created_at": r[5],
            "url": f"http://{r[1]}" if r[1] else None,
            "admin_url": f"http://{r[1]}/wp-admin" if r[1] else None,
        }
        for r in rows
    ]
