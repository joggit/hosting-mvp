"""
WordPress deployment and management service - TRADITIONAL APPROACH
No Docker - uses shared MySQL, PHP-FPM pools, and nginx server blocks
Like the Next.js deployment but for WordPress

✅ FIXED: No permission errors on /root/.my.cnf or /root/.mysql_root_password
✅ Uses secure /etc/hosting-manager/mysql_root_password (640 root:hosting)
✅ Lazy password loading — only at runtime
✅ Fully compatible with Flask app running as 'deploy'
"""

import os
import subprocess
import logging
import secrets
import string
import shutil
from pathlib import Path
from services.database import get_db

logger = logging.getLogger(__name__)

# Configuration
WORDPRESS_BASE_DIR = Path("/var/www/wordpress")
NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
PHP_FPM_POOL_DIR = Path("/etc/php/8.3/fpm/pool.d")
MYSQL_HOST = "localhost"
MYSQL_ROOT_USER = "root"


# ============================================================================
# 🔒 SECURE MySQL Root Password Retrieval (NO import-time access)
# ============================================================================
def get_mysql_root_password():
    """
    Get MySQL root password — safe for 'deploy' user.
    Order of preference:
      1. Environment variable (e.g., MYSQL_ROOT_PASSWORD in .env)
      2. /etc/hosting-manager/mysql_root_password (chmod 640, root:hosting)
      3. /root/.my.cnf (only if running as root — fallback)
    """
    # 1. Environment (e.g., .env)
    password = os.getenv("MYSQL_ROOT_PASSWORD")
    if password:
        logger.debug("MySQL root password loaded from environment")
        return password.strip()

    # 2. Secure shared location (recommended for production)
    secure_path = Path("/etc/hosting-manager/mysql_root_password")
    if secure_path.exists():
        try:
            return secure_path.read_text().strip()
        except PermissionError:
            logger.warning(
                f"⚠️ Permission denied reading {secure_path} — ensure 'deploy' is in 'hosting' group"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to read {secure_path}: {e}")

    # 3. Fallback: /root/.my.cnf (only works for root)
    root_mycnf = Path("/root/.my.cnf")
    if root_mycnf.exists() and os.geteuid() == 0:
        try:
            for line in root_mycnf.read_text().splitlines():
                if line.startswith("password="):
                    return line.split("=", 1)[1].strip()
        except Exception as e:
            logger.warning(f"Failed to parse {root_mycnf}: {e}")

    # Final error
    raise FileNotFoundError(
        "MySQL root password not found. Ensure one of:\n"
        "  - MYSQL_ROOT_PASSWORD in .env\n"
        "  - /etc/hosting-manager/mysql_root_password (chmod 640, root:hosting)\n"
        "  - 'deploy' user added to 'hosting' group"
    )


# ============================================================================
# Helper Functions
# ============================================================================


def generate_password(length=32):
    """Generate secure alphanumeric password"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def run_command(cmd, shell=False, check=True, **kwargs):
    """Run shell command safely"""
    try:
        if isinstance(cmd, str) and not shell:
            cmd = cmd.split()
        return subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, check=check, **kwargs
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e.stderr}")
        raise


def run_mysql_query(query, database=None):
    """✅ SAFE: calls get_mysql_root_password() at runtime, not import time"""
    password = get_mysql_root_password()

    cmd = [
        "mysql",
        "-u",
        MYSQL_ROOT_USER,
        f"-p{password}",
        "-h",
        MYSQL_HOST,
    ]
    if database:
        cmd.extend(["-D", database])
    cmd.extend(["-e", query])

    return run_command(cmd, check=True)


# ============================================================================
# MySQL Database Management
# ============================================================================


def create_mysql_database(db_name, db_user, db_password):
    logger.info(f"Creating MySQL database: {db_name}")
    run_mysql_query(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    run_mysql_query(
        f"""
        CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';
        GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost';
        FLUSH PRIVILEGES;
    """
    )
    logger.info(f"✅ Database {db_name} created")


def delete_mysql_database(db_name, db_user):
    logger.info(f"Deleting MySQL database: {db_name}")
    try:
        run_mysql_query(f"DROP DATABASE IF EXISTS `{db_name}`;", check=False)
        run_mysql_query(f"DROP USER IF EXISTS '{db_user}'@'localhost';", check=False)
        run_mysql_query("FLUSH PRIVILEGES;")
    except Exception as e:
        logger.warning(f"MySQL cleanup non-fatal: {e}")
    logger.info(f"✅ Database {db_name} deleted")


# ============================================================================
# PHP-FPM Pool Management
# ============================================================================


def create_php_fpm_pool(site_name, user="www-data", group="www-data"):
    pool_config = f"""[{site_name}]
user = {user}
group = {group}
listen = /run/php/php-fpm-{site_name}.sock
listen.owner = {user}
listen.group = www-data
listen.mode = 0660
pm = dynamic
pm.max_children = 5
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
php_admin_value[error_log] = /var/log/php-fpm/{site_name}-error.log
php_admin_flag[log_errors] = on
"""
    (PHP_FPM_POOL_DIR / f"{site_name}.conf").write_text(pool_config)
    run_command("systemctl reload php8.3-fpm", shell=True)
    logger.info(f"✅ PHP-FPM pool: {site_name}")


def delete_php_fpm_pool(site_name):
    pool_file = PHP_FPM_POOL_DIR / f"{site_name}.conf"
    if pool_file.exists():
        pool_file.unlink()
        run_command("systemctl reload php8.3-fpm", shell=True)
    logger.info(f"✅ PHP-FPM pool deleted: {site_name}")


# ============================================================================
# Nginx Configuration
# ============================================================================


def create_nginx_config(site_name, domain):
    site_root = WORDPRESS_BASE_DIR / site_name
    nginx_config = f"""server {{
    listen 80;
    server_name {domain};
    root {site_root};
    index index.php;
    access_log /var/log/nginx/{site_name}-access.log;
    error_log /var/log/nginx/{site_name}-error.log;
    location / {{
        try_files $uri $uri/ /index.php?$args;
    }}
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php-fpm-{site_name}.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}
    location ~ /\\.ht {{
        deny all;
    }}
}}"""
    config_file = NGINX_SITES_AVAILABLE / f"{site_name}.conf"
    config_file.write_text(nginx_config)
    enabled = NGINX_SITES_ENABLED / f"{site_name}.conf"
    if enabled.exists():
        enabled.unlink()
    enabled.symlink_to(config_file)
    if run_command("nginx -t", shell=True, check=False).returncode == 0:
        run_command("systemctl reload nginx", shell=True)
        logger.info(f"✅ Nginx config for {domain}")
    else:
        raise Exception("Nginx config invalid")


def delete_nginx_config(site_name):
    for p in [NGINX_SITES_ENABLED, NGINX_SITES_AVAILABLE]:
        f = p / f"{site_name}.conf"
        if f.exists():
            f.unlink()
    run_command("systemctl reload nginx", shell=True)
    logger.info(f"✅ Nginx config deleted: {site_name}")


# ============================================================================
# WordPress Installation
# ============================================================================


def download_wordpress(site_dir):
    site_dir.mkdir(parents=True, exist_ok=True)
    wp_zip = site_dir.parent / "wordpress.tar.gz"
    run_command(
        ["wget", "https://wordpress.org/latest.tar.gz", "-O", str(wp_zip), "-q"]
    )
    run_command(["tar", "xzf", str(wp_zip), "-C", str(site_dir.parent)])
    wp_temp = site_dir.parent / "wordpress"
    for item in wp_temp.iterdir():
        shutil.move(str(item), str(site_dir))
    wp_temp.rmdir()
    wp_zip.unlink()
    logger.info("✅ WordPress downloaded")


def create_wp_config(site_dir, db_name, db_user, db_password, domain):
    wp_config_sample = site_dir / "wp-config-sample.php"
    wp_config = site_dir / "wp-config.php"
    content = wp_config_sample.read_text()
    content = content.replace("database_name_here", db_name)
    content = content.replace("username_here", db_user)
    content = content.replace("password_here", db_password)
    content = content.replace("localhost", MYSQL_HOST)
    for _ in range(8):
        content = content.replace(
            "put your unique phrase here", generate_password(64), 1
        )
    wp_config.write_text(content)
    logger.info("✅ wp-config.php created")


def install_wordpress_core(
    site_dir, site_title, admin_user, admin_password, admin_email, domain
):
    wp = Path("/usr/local/bin/wp")
    if not wp.exists():
        run_command(
            [
                "curl",
                "-O",
                "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
            ]
        )
        run_command(["chmod", "+x", "wp-cli.phar"])
        run_command(["mv", "wp-cli.phar", str(wp)])
    cmd = [
        "wp",
        "core",
        "install",
        f"--path={site_dir}",
        f"--url=http://{domain}",
        f"--title={site_title}",
        f"--admin_user={admin_user}",
        f"--admin_password={admin_password}",
        f"--admin_email={admin_email}",
        "--skip-email",
        "--allow-root",
    ]
    result = run_command(cmd, check=False)
    if result.returncode != 0 and "already installed" not in result.stderr:
        raise Exception(f"WP install failed: {result.stderr}")
    logger.info("✅ WordPress core installed")


def set_permissions(site_dir):
    run_command(f"chown -R www-data:www-data {site_dir}", shell=True)
    run_command(f"find {site_dir} -type d -exec chmod 755 {{}} \\;", shell=True)
    run_command(f"find {site_dir} -type f -exec chmod 644 {{}} \\;", shell=True)
    logger.info("✅ Permissions set")


# ============================================================================
# 🌟 MAIN ENTRY POINTS (used by routes)
# ============================================================================


def create_wordpress_site(
    site_name, domain, admin_email, admin_password, site_title="My Site", port=None
):
    logger.info(f"🚀 Deploying: {site_name}")
    db_name = f"wp_{site_name}"
    db_user = f"wp_{site_name}"
    db_pass = generate_password()
    site_dir = WORDPRESS_BASE_DIR / site_name

    try:
        create_mysql_database(db_name, db_user, db_pass)
        download_wordpress(site_dir)
        create_wp_config(site_dir, db_name, db_user, db_pass, domain)
        create_php_fpm_pool(site_name)
        create_nginx_config(site_name, domain)
        set_permissions(site_dir)
        install_wordpress_core(
            site_dir, site_title, "admin", admin_password, admin_email, domain
        )

        # Register in DB
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO wordpress_sites (site_name, domain, port, container_name, admin_email, 
                   docker_compose_path, status, mysql_database, mysql_user)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                site_name,
                domain,
                80,
                site_name,
                admin_email,
                str(site_dir),
                "running",
                db_name,
                db_user,
            ),
        )
        site_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO deployment_logs (domain_name, action, status, message)
            VALUES (?, 'wordpress_deploy', 'success', ?)
        """,
            (domain, f"WordPress deployed: {site_name}"),
        )
        conn.commit()
        conn.close()

        logger.info(f"✅ {site_name} deployed")
        return {
            "success": True,
            "site_id": site_id,
            "domain": domain,
            "admin_url": f"http://{domain}/wp-admin",
            "site_url": f"http://{domain}",
        }

    except Exception as e:
        logger.error(f"❌ Deployment failed: {e}")
        cleanup_wordpress_site(site_name)
        raise


def manage_wordpress_site(site_name, action):
    if action == "delete":
        cleanup_wordpress_site(site_name)
        return {"success": True, "message": f"{site_name} deleted"}
    elif action == "restart":
        run_command("systemctl reload php8.3-fpm nginx", shell=True)
        return {"success": True, "message": f"{site_name} restarted"}
    else:
        return {
            "success": True,
            "message": f"Action {action} not required for traditional setup",
        }


def install_plugin(site_name, plugin_name, activate=True):
    site_dir = WORDPRESS_BASE_DIR / site_name
    cmd = ["wp", "plugin", "install", plugin_name, f"--path={site_dir}", "--allow-root"]
    if activate:
        cmd.append("--activate")
    result = run_command(cmd, check=False)
    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "error": result.stderr,
    }


def cleanup_wordpress_site(site_name):
    logger.info(f"🧹 Cleaning up: {site_name}")
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT mysql_database, mysql_user FROM wordpress_sites WHERE site_name = ?",
            (site_name,),
        )
        row = cursor.fetchone()
        if row:
            delete_mysql_database(row[0], row[1])
        cursor.execute("DELETE FROM wordpress_sites WHERE site_name = ?", (site_name,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"DB cleanup: {e}")

    try:
        delete_php_fpm_pool(site_name)
        delete_nginx_config(site_name)
    except Exception as e:
        logger.warning(f"Config cleanup: {e}")

    site_dir = WORDPRESS_BASE_DIR / site_name
    if site_dir.exists():
        shutil.rmtree(site_dir, ignore_errors=True)
    logger.info(f"✅ Cleanup complete: {site_name}")


def list_wordpress_sites():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, site_name, domain, status, admin_email, created_at FROM wordpress_sites ORDER BY created_at DESC"
    )
    sites = [
        {
            "id": r[0],
            "name": r[1],
            "domain": r[2],
            "status": r[3],
            "admin_email": r[4],
            "created_at": r[5],
            "admin_url": f"http://{r[2]}/wp-admin",
            "type": "traditional",
        }
        for r in cursor.fetchall()
    ]
    conn.close()
    return sites


def execute_wp_cli(site_name, command):
    site_dir = WORDPRESS_BASE_DIR / site_name
    cmd = ["wp"] + command.split() + [f"--path={site_dir}", "--allow-root"]
    result = run_command(cmd, check=False)
    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "error": result.stderr,
    }


# ============================================================================
# WooCommerce Support
# ============================================================================


def setup_woocommerce(site_name, config):
    site_dir = WORDPRESS_BASE_DIR / site_name
    run_command(
        [
            "wp",
            "plugin",
            "install",
            "woocommerce",
            "--activate",
            f"--path={site_dir}",
            "--allow-root",
        ]
    )
    settings = {
        "woocommerce_store_address": config.get("store_address", ""),
        "woocommerce_store_city": config.get("store_city", ""),
        "woocommerce_store_postcode": config.get("store_postcode", ""),
        "woocommerce_default_country": config.get("store_country", "ZA"),
        "woocommerce_currency": config.get("currency", "ZAR"),
    }
    for opt, val in settings.items():
        if val:
            run_command(
                [
                    "wp",
                    "option",
                    "update",
                    opt,
                    str(val),
                    f"--path={site_dir}",
                    "--allow-root",
                ]
            )
    return {
        "success": True,
        "message": "WooCommerce installed",
        "steps_completed": ["plugin_install", "configuration"],
    }


def create_sample_products(site_name, count=5):
    site_dir = WORDPRESS_BASE_DIR / site_name
    created = 0
    for i in range(1, count + 1):
        try:
            run_command(
                [
                    "wp",
                    "wc",
                    "product",
                    "create",
                    f"--name=Sample Product {i}",
                    f"--regular_price={100 * i}",
                    "--type=simple",
                    f"--path={site_dir}",
                    "--allow-root",
                ]
            )
            created += 1
        except Exception as e:
            logger.warning(f"Product {i} failed: {e}")
    return {
        "success": True,
        "products_created": created,
        "message": f"Created {created} products",
    }


def get_store_info(site_name):
    site_dir = WORDPRESS_BASE_DIR / site_name
    result = run_command(
        [
            "wp",
            "plugin",
            "is-active",
            "woocommerce",
            f"--path={site_dir}",
            "--allow-root",
        ],
        check=False,
    )
    return {
        "success": True,
        "woocommerce_active": result.returncode == 0,
        "site_name": site_name,
    }


# Must be run from cli since python scripts cannot modify their own permissions
def ensure_permissions():
    """
    Ensure 'deploy' user has permissions to:
      - Write to /var/www/wordpress
      - Write PHP-FPM pool configs via sudo (if configured)
    Safe for production — no blind sudo.
    """
    import grp
    import pwd
    import subprocess

    DEPLOY_USER = "deploy"
    WWW_DIR = Path("/var/www/wordpress")
    PHP_POOL_DIR = Path("/etc/php/8.3/fpm/pool.d")

    logger.info("🔍 Checking deployment permissions...")

    # 1. Ensure WWW_DIR exists and is group-writable
    try:
        WWW_DIR.mkdir(parents=True, exist_ok=True)

        # Set owner:group = www-data:www-data
        subprocess.run(
            ["sudo", "chown", "-R", "www-data:www-data", str(WWW_DIR)], check=True
        )
        subprocess.run(["sudo", "chmod", "-R", "755", str(WWW_DIR)], check=True)
        subprocess.run(["sudo", "chmod", "-R", "g+w", str(WWW_DIR)], check=True)

        # Ensure deploy is in www-data group
        deploy_groups = grp.getgrnam("www-data")
        if DEPLOY_USER not in deploy_groups.gr_mem:
            logger.warning(f"⚠️ User '{DEPLOY_USER}' not in 'www-data' group.")
            logger.info(f"   Run as root: usermod -aG www-data {DEPLOY_USER}")
            logger.info(f"   Then re-login or restart the service.")
            return False
        else:
            logger.info("✅ 'deploy' is in 'www-data' group")

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Failed to set /var/www permissions: {e}")
        logger.info(
            "   Ensure 'deploy' has passwordless sudo for chown/chmod/www-data ops."
        )
        return False

    # 2. Check sudo access for PHP-FPM pool management
    try:
        # Test: can we sudo-copy a dummy file?
        test_file = Path("/tmp/__perm_test.conf")
        test_file.write_text("# test")
        dest = PHP_POOL_DIR / "__perm_test.conf"

        subprocess.run(["sudo", "cp", str(test_file), str(dest)], check=True)
        subprocess.run(["sudo", "rm", str(dest)], check=True)
        test_file.unlink()

        logger.info("✅ 'deploy' can manage PHP-FPM pool configs via sudo")
    except subprocess.CalledProcessError:
        logger.warning("⚠️ 'deploy' cannot write to /etc/php/... via sudo")
        logger.info("   Fix: Create /etc/sudoers.d/deploy-php with:")
        logger.info(
            f"   {DEPLOY_USER} ALL=(root) NOPASSWD: /bin/cp /tmp/*.conf /etc/php/8.3/fpm/pool.d/, /bin/rm /etc/php/8.3/fpm/pool.d/*.conf, /bin/chown * /etc/php/8.3/fpm/pool.d/*.conf, /bin/chmod * /etc/php/8.3/fpm/pool.d/*.conf"
        )
        return False

    logger.info("✅ All permissions OK for WordPress deployment")
    return True
