"""
WordPress deployment via Docker containers.
One compose stack per site; host nginx proxies by domain to the container port.
"""

import os
import re
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


def _copy_theme_and_plugins_into_volume(site_dir: Path, theme_slug: str) -> None:
    """Copy theme and plugins from host into the wp_html volume so the container sees them with correct ownership."""
    slug = (theme_slug or THEME_SLUG).strip()[:64]
    if not slug or "/" in slug or "\\" in slug:
        return
    theme_src = site_dir / "theme"
    plugins_src = site_dir / "plugins"
    if not theme_src.is_dir():
        return
    # Compose project name = directory name by default → volume name = {name}_wp_html
    volume_name = f"{site_dir.name}_wp_html"
    dest = "/dest"
    try:
        # Use alpine to copy into the volume (no bind-mount override); www-data uid:gid = 33:33
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{theme_src.resolve()}:/.src_theme:ro",
            "-v", f"{volume_name}:{dest}",
            "alpine",
            "sh", "-c",
            f"cp -r /.src_theme {dest}/wp-content/themes/{slug} && chown -R 33:33 {dest}/wp-content/themes/{slug}",
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
        if plugins_src.is_dir():
            cmd_plugins = [
                "docker", "run", "--rm",
                "-v", f"{plugins_src.resolve()}:/.src_plugins:ro",
                "-v", f"{volume_name}:{dest}",
                "alpine",
                "sh", "-c",
                f"cp -r /.src_plugins/. {dest}/wp-content/plugins/ 2>/dev/null || true && chown -R 33:33 {dest}/wp-content/plugins",
            ]
            subprocess.run(cmd_plugins, capture_output=True, text=True, timeout=300, check=False)
        logger.info("Copied theme (and plugins) into volume for %s", slug)
    except subprocess.CalledProcessError as e:
        logger.warning("Copy theme/plugins into volume failed (non-fatal): %s", e.stderr or e.stdout)
    except Exception as e:
        logger.warning("Copy theme/plugins into volume failed (non-fatal): %s", e)


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


def _write_compose(
    site_dir: Path,
    port: int,
    db_name: str,
    db_user: str,
    db_pass: str,
    theme_slug: str = None,
):
    slug = (theme_slug or THEME_SLUG).strip() or THEME_SLUG
    # Safe for compose: no path separators or quotes
    if "/" in slug or "\\" in slug or '"' in slug or "\n" in slug:
        slug = THEME_SLUG
    # Theme/plugins are copied into wp_html volume after compose up (no bind mounts)
    compose = f"""services:
  nginx:
    image: nginx:alpine
    ports:
      - "{port}:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - wp_html:/var/www/html:ro
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


def create_site(
    site_name: str, domain: str, files: dict, theme_slug: str = None
) -> dict:
    """
    Create a WordPress Docker site: write theme and plugin files, generate compose, start stack, create nginx.
    files: dict of path -> content (paths like "theme/style.css", "plugins/.../file.php").
    theme_slug: directory name under wp-content/themes/ (must match dev so DB option template/stylesheet is valid).
    """
    site_dir = WORDPRESS_DOCKER_BASE / site_name
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    theme_dir = site_dir / "theme"
    theme_dir.mkdir(exist_ok=True)
    plugins_dir = site_dir / "plugins"
    plugins_dir.mkdir(exist_ok=True)

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
    resolved_slug = (theme_slug or THEME_SLUG).strip() or THEME_SLUG
    if "/" in resolved_slug or "\\" in resolved_slug or '"' in resolved_slug or "\n" in resolved_slug:
        resolved_slug = THEME_SLUG
    _write_compose(site_dir, port, db_name, db_user, db_pass, theme_slug=theme_slug)

    _run(["docker", "compose", "up", "-d"], cwd=site_dir, timeout=120)
    # Copy theme and plugins into the container volume so they exist with correct ownership (not only bind mount)
    _copy_theme_and_plugins_into_volume(site_dir, resolved_slug)
    create_nginx_reverse_proxy(domain, port)
    reload_nginx()

    # Insert site record (retry on SQLite "database is locked")
    conn = None
    for attempt in range(5):
        try:
            conn = get_db()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO wordpress_docker_sites (site_name, domain, port, site_path, status, db_name, db_user, db_password, theme_slug)
                    VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)
                    """,
                    (site_name, domain, port, str(site_dir), db_name, db_user, db_pass, resolved_slug),
                )
            except Exception as col_err:
                if "theme_slug" in str(col_err) or "no such column" in str(col_err).lower():
                    cursor.execute(
                        """
                        INSERT INTO wordpress_docker_sites (site_name, domain, port, site_path, status, db_name, db_user, db_password)
                        VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                        """,
                        (site_name, domain, port, str(site_dir), db_name, db_user, db_pass),
                    )
                else:
                    raise
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
    try:
        cursor.execute(
            "SELECT site_path, db_name, db_user, db_password, theme_slug FROM wordpress_docker_sites WHERE site_name = ?",
            (site_name,),
        )
    except Exception:
        cursor.execute(
            "SELECT site_path, db_name, db_user, db_password FROM wordpress_docker_sites WHERE site_name = ?",
            (site_name,),
        )
    row = cursor.fetchone()
    conn.close()
    if not row or not row[0]:
        raise ValueError(f"Site not found: {site_name}")
    site_path, db_name, db_user, db_password = row[0], row[1], row[2], row[3]
    theme_slug = row[4] if len(row) > 4 and row[4] else None
    if not all((db_name, db_user, db_password)):
        raise ValueError(f"Site {site_name} has no DB credentials (deploy may predate mirror support)")
    return Path(site_path), db_name, db_user, db_password, theme_slug


def _theme_slug_from_compose(site_dir: Path) -> str:
    """Read the theme slug from the site's docker-compose.yml (what we actually mounted)."""
    compose_path = site_dir / "docker-compose.yml"
    if not compose_path.is_file():
        return ""
    try:
        text = compose_path.read_text(encoding="utf-8")
        # .../themes/SLUG:ro or .../themes/SLUG\n
        m = re.search(r"/wp-content/themes/([a-zA-Z0-9_-]+)(?::ro)?\s", text)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _replace_urls_in_dump_safe(content: str, source_url: str, target_url: str) -> str:
    """
    Replace source_url with target_url in dump. Updates PHP serialized string lengths so options (e.g. WooCommerce) stay valid.
    """
    if not source_url or not target_url or source_url == target_url:
        return content
    result = []
    i = 0
    while i < len(content):
        # Look for PHP serialized string s:N:"
        m = re.search(r"s:(\d+):\"", content[i:])
        if not m:
            result.append(content[i:].replace(source_url, target_url))
            break
        j = i + m.start()
        result.append(content[i:j].replace(source_url, target_url))
        orig_len = int(m.group(1))
        payload_start = j + m.end()
        payload_end = payload_start + orig_len
        if payload_end + 2 > len(content):
            result.append(content[j:].replace(source_url, target_url))
            break
        if content[payload_end : payload_end + 2] != '";':
            result.append(content[j : payload_end + 2].replace(source_url, target_url))
            i = payload_end + 2
            continue
        payload = content[payload_start:payload_end]
        after = content[payload_end : payload_end + 2]
        if source_url in payload:
            new_payload = payload.replace(source_url, target_url)
            new_len = len(new_payload)
            result.append(f's:{new_len}:"')
            result.append(new_payload)
        else:
            result.append(content[j:payload_end])
        result.append(after)
        i = payload_end + 2
    return "".join(result)


def import_site_database(
    site_name: str,
    dump_path: Path,
    source_url: str = None,
    target_url: str = None,
    theme_slug: str = None,
) -> None:
    """
    Import a SQL dump into the site's MySQL container.
    If source_url and target_url are set, replace the former with the latter in the dump (serialized-safe) before importing.
    If theme_slug is set, after import the active theme (template + stylesheet) is set to that slug so the mirrored theme is selected.
    """
    site_dir, db_name, db_user, db_password, theme_slug_from_db = _get_site_db_credentials(site_name)
    dump_path = Path(dump_path)
    if not dump_path.is_file():
        raise FileNotFoundError(f"Dump file not found: {dump_path}")

    # Resolve theme slug: client param > stored at create time > read from compose file
    active_theme_slug = (theme_slug or theme_slug_from_db or _theme_slug_from_compose(site_dir) or "").strip() or None

    import_path = dump_path
    if source_url and target_url and source_url != target_url:
        content = dump_path.read_text(encoding="utf-8", errors="replace")
        content = _replace_urls_in_dump_safe(content, source_url, target_url)
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

    # Mark WooCommerce setup wizard as completed so mirror deploy doesn't show "setup store" again
    _mark_woocommerce_wizard_completed(site_dir, db_name, db_user, db_password)

    # Force active theme: SQL update first, then WordPress API via PHP script (reliable inside container)
    if active_theme_slug:
        _set_active_theme(site_dir, db_name, db_user, db_password, active_theme_slug)
        _activate_theme_via_php(site_dir, active_theme_slug)
        logger.info("Set active theme to %s for %s", active_theme_slug, site_name)

    logger.info("Database import completed for %s", site_name)


def _activate_theme_via_php(site_dir: Path, theme_slug: str) -> None:
    """Run the theme's activate_theme.php inside the wordpress container so switch_theme() is used."""
    slug = (theme_slug or "").strip()[:64]
    if not slug or "/" in slug or "\\" in slug:
        return
    script_path = f"/var/www/html/wp-content/themes/{slug}/activate_theme.php"
    try:
        r = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "wordpress",
                "php",
                script_path,
            ],
            cwd=site_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            logger.warning(
                "Theme PHP activation failed (non-fatal): %s",
                r.stderr or r.stdout or "exit %s" % r.returncode,
            )
    except Exception as e:
        logger.warning("Theme PHP activation failed (non-fatal): %s", e)


def _set_active_theme(
    site_dir: Path,
    db_name: str,
    db_user: str,
    db_password: str,
    theme_slug: str,
    table_prefix: str = "wp_",
) -> None:
    """Set WordPress active theme (template and stylesheet options) so the mirrored theme is selected."""
    slug = theme_slug.strip()[:64]
    if not slug or "/" in slug or "\\" in slug or "'" in slug:
        return
    try:
        for option_name in ("template", "stylesheet"):
            r = subprocess.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "db",
                    "mysql",
                    "-h",
                    "127.0.0.1",
                    f"-u{db_user}",
                    f"-p{db_password}",
                    db_name,
                    "-e",
                    f"UPDATE {table_prefix}options SET option_value = '{slug}' "
                    f"WHERE option_name = '{option_name}';",
                ],
                cwd=site_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode != 0:
                logger.warning(
                    "Could not set option %s (non-fatal): %s",
                    option_name,
                    r.stderr or r.stdout,
                )
    except Exception as e:
        logger.warning("Could not set active theme (non-fatal): %s", e)


def _mark_woocommerce_wizard_completed(
    site_dir: Path, db_name: str, db_user: str, db_password: str, table_prefix: str = "wp_"
) -> None:
    """Set woocommerce_onboarding_profile so the setup wizard is skipped (mirror = already set up)."""
    # WordPress stores options as PHP-serialized; completed + skipped so wizard doesn't show
    value = "a:2:{s:9:\"completed\";b:1;s:7:\"skipped\";b:1;}"
    try:
        r = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "mysql",
                "-h",
                "127.0.0.1",
                f"-u{db_user}",
                f"-p{db_password}",
                db_name,
                "-e",
                f"INSERT INTO {table_prefix}options (option_name, option_value, autoload) "
                f"VALUES ('woocommerce_onboarding_profile', '{value}', 'no') "
                f"ON DUPLICATE KEY UPDATE option_value = '{value}';",
            ],
            cwd=site_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            logger.warning(
                "Could not set WooCommerce wizard completed (non-fatal): %s",
                r.stderr or r.stdout,
            )
    except Exception as e:
        logger.warning("Could not set WooCommerce wizard completed (non-fatal): %s", e)


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
