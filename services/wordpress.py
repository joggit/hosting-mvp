"""
WordPress deployment and management service - TRADITIONAL APPROACH
No Docker - uses shared MySQL, PHP-FPM pools, and nginx server blocks
Clean, focused traditional hosting

✅ NO Docker dependencies
✅ Uses secure MySQL password from /etc/hosting-manager/mysql_root_password
✅ Traditional PHP-FPM pool management
✅ Nginx server blocks (no reverse proxy for WordPress)
"""

import os
import subprocess
import logging
import secrets
import string
import shutil
import tempfile
from pathlib import Path
import time

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
# 🔒 SECURE MySQL Root Password Retrieval
# ============================================================================
def get_mysql_root_password():
    """
    Get MySQL root password — safe for 'deploy' user.
    Order of preference:
      1. Environment variable (e.g., MYSQL_ROOT_PASSWORD in .env)
      2. /etc/hosting-manager/mysql_root_password (chmod 640, root:hosting)
    """
    # 1. Environment (e.g., .env)
    password = os.getenv("MYSQL_ROOT_PASSWORD")
    if password:
        logger.debug("MySQL root password loaded from environment")
        return password.strip()

    # 2. Secure shared location
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
    """Run MySQL query as root"""
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
    """Create MySQL database and user"""
    logger.info(f"Creating MySQL database: {db_name}")

    # Create database
    run_mysql_query(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )

    # Create user if not exists
    run_mysql_query(
        f"""
        CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';
        GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost';
        FLUSH PRIVILEGES;
        """
    )
    logger.info(f"✅ Database {db_name} created")


def delete_mysql_database(db_name, db_user):
    """Delete MySQL database and user"""
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


def ensure_php_fpm_running():
    """Ensure PHP-FPM service is running"""
    try:
        # Check if service is active
        result = subprocess.run(
            ["systemctl", "is-active", "php8.3-fpm"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            logger.info("PHP-FPM not running, starting service...")
            subprocess.run(["sudo", "systemctl", "start", "php8.3-fpm"], check=True)
            time.sleep(2)  # Give it time to start
            logger.info("✅ PHP-FPM started")
        return True
    except Exception as e:
        logger.error(f"Failed to start PHP-FPM: {e}")
        raise


def create_php_fpm_pool(site_name):
    """Create PHP-FPM pool configuration for WordPress site"""
    logger.info(f"Creating PHP-FPM pool for {site_name}")

    # Ensure PHP-FPM is running first
    ensure_php_fpm_running()

    # Build pool configuration
    pool_config = f"""[{site_name}]
user = www-data
group = www-data
listen = /run/php/php-fpm-{site_name}.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
pm = dynamic
pm.max_children = 10
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
pm.max_requests = 500
access.log = /var/log/php8.3-fpm/{site_name}-access.log
php_admin_value[error_log] = /var/log/php8.3-fpm/{site_name}-error.log
php_admin_flag[log_errors] = on
php_admin_value[memory_limit] = 256M
php_admin_value[upload_max_filesize] = 64M
php_admin_value[post_max_size] = 64M
php_admin_value[max_execution_time] = 300
php_admin_value[max_input_time] = 300
"""

    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as tmp:
        tmp.write(pool_config)
        tmp_path = tmp.name

    try:
        # Copy to PHP-FPM pool directory using sudo
        dest_path = f"/etc/php/8.3/fpm/pool.d/{site_name}.conf"
        subprocess.run(["sudo", "cp", tmp_path, dest_path], check=True)
        subprocess.run(["sudo", "chmod", "644", dest_path], check=True)
        logger.info(f"✅ Pool config installed: {dest_path}")

        # Reload PHP-FPM
        subprocess.run(["sudo", "systemctl", "reload", "php8.3-fpm"], check=True)
        logger.info("✅ PHP-FPM reloaded")

    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


def delete_php_fpm_pool(site_name):
    """Delete PHP-FPM pool configuration"""
    pool_file = PHP_FPM_POOL_DIR / f"{site_name}.conf"
    if pool_file.exists():
        try:
            pool_file.unlink()
            subprocess.run(["sudo", "systemctl", "reload", "php8.3-fpm"], check=False)
            logger.info(f"✅ PHP-FPM pool deleted: {site_name}")
        except Exception as e:
            logger.warning(f"Failed to delete PHP-FPM pool: {e}")


# ============================================================================
# Nginx Configuration
# ============================================================================


def create_nginx_config(site_name, domain):
    """Create Nginx server block for WordPress site"""
    site_root = WORDPRESS_BASE_DIR / site_name

    nginx_config = f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
    root {site_root};
    index index.php index.html index.htm;
    
    access_log /var/log/nginx/{site_name}-access.log;
    error_log /var/log/nginx/{site_name}-error.log;
    
    client_max_body_size 64M;
    
    location / {{
        try_files $uri $uri/ /index.php?$args;
    }}
    
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php-fpm-{site_name}.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
        
        fastcgi_read_timeout 300;
        fastcgi_send_timeout 300;
    }}
    
    location ~* \\.(css|js|png|jpg|jpeg|gif|ico|svg)$ {{
        expires max;
        log_not_found off;
    }}
    
    location ~ /\\.ht {{
        deny all;
    }}
    
    location = /favicon.ico {{
        log_not_found off;
        access_log off;
    }}
    
    location = /robots.txt {{
        allow all;
        log_not_found off;
        access_log off;
    }}
}}"""

    # Write to sites-available
    config_file = NGINX_SITES_AVAILABLE / f"{site_name}.conf"
    config_file.write_text(nginx_config)

    # Create symlink in sites-enabled
    enabled_link = NGINX_SITES_ENABLED / f"{site_name}.conf"
    if enabled_link.exists():
        enabled_link.unlink()
    enabled_link.symlink_to(config_file)

    # Test and reload Nginx
    nginx_test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if nginx_test.returncode == 0:
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        logger.info(f"✅ Nginx config created for {domain}")
    else:
        logger.error(f"Nginx config test failed: {nginx_test.stderr}")
        raise Exception(f"Nginx config invalid: {nginx_test.stderr}")


def delete_nginx_config(site_name):
    """Delete Nginx configuration for site"""
    # Remove from sites-enabled
    enabled_link = NGINX_SITES_ENABLED / f"{site_name}.conf"
    if enabled_link.exists():
        enabled_link.unlink()

    # Remove from sites-available
    config_file = NGINX_SITES_AVAILABLE / f"{site_name}.conf"
    if config_file.exists():
        config_file.unlink()

    # Reload Nginx
    subprocess.run(["systemctl", "reload", "nginx"], check=False)
    logger.info(f"✅ Nginx config deleted: {site_name}")


# ============================================================================
# WordPress Installation
# ============================================================================


def download_wordpress(site_dir):
    """Download and extract WordPress core"""
    site_dir.mkdir(parents=True, exist_ok=True)

    # Download WordPress
    wp_zip = site_dir.parent / "wordpress-latest.tar.gz"
    logger.info("Downloading WordPress...")

    result = subprocess.run(
        ["wget", "https://wordpress.org/latest.tar.gz", "-O", str(wp_zip), "-q"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise Exception(f"Failed to download WordPress: {result.stderr}")

    # Extract WordPress
    logger.info("Extracting WordPress...")
    result = subprocess.run(
        [
            "tar",
            "-xzf",
            str(wp_zip),
            "-C",
            str(site_dir.parent),
            "--strip-components=1",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise Exception(f"Failed to extract WordPress: {result.stderr}")

    # Clean up
    wp_zip.unlink(missing_ok=True)
    logger.info("✅ WordPress downloaded and extracted")


def create_wp_config(site_dir, db_name, db_user, db_password, domain):
    """Create wp-config.php file"""
    wp_config_sample = site_dir / "wp-config-sample.php"

    if not wp_config_sample.exists():
        # Create basic wp-config.php if sample doesn't exist
        content = f"""<?php
/**
 * The base configuration for WordPress
 */
define('DB_NAME', '{db_name}');
define('DB_USER', '{db_user}');
define('DB_PASSWORD', '{db_password}');
define('DB_HOST', '{MYSQL_HOST}');
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', '');

/** Authentication Unique Keys and Salts */
define('AUTH_KEY',         '{generate_password(64)}');
define('SECURE_AUTH_KEY',  '{generate_password(64)}');
define('LOGGED_IN_KEY',    '{generate_password(64)}');
define('NONCE_KEY',        '{generate_password(64)}');
define('AUTH_SALT',        '{generate_password(64)}');
define('SECURE_AUTH_SALT', '{generate_password(64)}');
define('LOGGED_IN_SALT',   '{generate_password(64)}');
define('NONCE_SALT',       '{generate_password(64)}');

/** WordPress Database Table prefix */
\$table_prefix = 'wp_';

/** WordPress debugging mode */
define('WP_DEBUG', false);

/** Absolute path to the WordPress directory */
if ( !defined('ABSPATH') )
    define('ABSPATH', dirname(__FILE__) . '/');

/** Sets up WordPress vars and included files */
require_once(ABSPATH . 'wp-settings.php');
"""
    else:
        # Use sample file as template
        content = wp_config_sample.read_text()
        content = content.replace("database_name_here", db_name)
        content = content.replace("username_here", db_user)
        content = content.replace("password_here", db_password)
        content = content.replace("localhost", MYSQL_HOST)

        # Generate security keys
        for _ in range(8):
            content = content.replace(
                "put your unique phrase here", generate_password(64), 1
            )

    # Write wp-config.php
    wp_config = site_dir / "wp-config.php"
    wp_config.write_text(content)

    # Set permissions
    subprocess.run(["sudo", "chmod", "644", str(wp_config)], check=False)
    logger.info("✅ wp-config.php created")


def install_wordpress_core(
    site_dir, site_title, admin_user, admin_password, admin_email, domain
):
    """Install WordPress core using WP-CLI"""
    wp_cli = Path("/usr/local/bin/wp")

    # Check if WP-CLI exists
    if not wp_cli.exists():
        logger.info("WP-CLI not found, installing...")
        subprocess.run(
            [
                "curl",
                "-O",
                "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
            ],
            check=True,
        )
        subprocess.run(["chmod", "+x", "wp-cli.phar"], check=True)
        subprocess.run(["mv", "wp-cli.phar", "/usr/local/bin/wp"], check=True)

    # Install WordPress
    logger.info("Installing WordPress core...")
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

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        if "already installed" not in result.stderr:
            raise Exception(f"WordPress installation failed: {result.stderr}")
        else:
            logger.info("WordPress already installed, continuing...")
    else:
        logger.info("✅ WordPress core installed")

    # Update site URL and home
    subprocess.run(
        [
            "wp",
            "option",
            "update",
            "siteurl",
            f"http://{domain}",
            f"--path={site_dir}",
            "--allow-root",
        ],
        check=False,
    )

    subprocess.run(
        [
            "wp",
            "option",
            "update",
            "home",
            f"http://{domain}",
            f"--path={site_dir}",
            "--allow-root",
        ],
        check=False,
    )


def set_permissions(site_dir):
    """Set proper permissions for WordPress site"""
    # Set ownership to www-data
    subprocess.run(
        ["sudo", "chown", "-R", "www-data:www-data", str(site_dir)], check=True
    )

    # Set directory permissions
    subprocess.run(
        [
            "sudo",
            "find",
            str(site_dir),
            "-type",
            "d",
            "-exec",
            "chmod",
            "755",
            "{}",
            "+",
        ],
        check=False,
    )

    # Set file permissions
    subprocess.run(
        [
            "sudo",
            "find",
            str(site_dir),
            "-type",
            "f",
            "-exec",
            "chmod",
            "644",
            "{}",
            "+",
        ],
        check=False,
    )

    # Set writable permissions for wp-content
    wp_content = site_dir / "wp-content"
    if wp_content.exists():
        subprocess.run(["sudo", "chmod", "-R", "775", str(wp_content)], check=False)

    logger.info("✅ Permissions set")


# ============================================================================
# 🌟 MAIN ENTRY POINTS
# ============================================================================


def create_wordpress_site(
    site_name, domain, admin_email, admin_password, site_title="My WordPress Site"
):
    """
    Main function to deploy a WordPress site (Traditional - No Docker)

    Args:
        site_name: Directory name for the site (e.g., "mysite")
        domain: Domain name (e.g., "example.com")
        admin_email: Admin email address
        admin_password: Admin password
        site_title: Site title
    """
    logger.info(f"🚀 Deploying WordPress site: {site_name} ({domain})")

    # Generate database credentials
    db_name = f"wp_{site_name}"
    db_user = f"wp_{site_name}"
    db_pass = generate_password()

    # Site directory
    site_dir = WORDPRESS_BASE_DIR / site_name

    try:
        # Clean up any existing directory
        if site_dir.exists():
            logger.info(f"Cleaning existing directory: {site_dir}")
            shutil.rmtree(site_dir, ignore_errors=True)

        # Step 1: Create MySQL database
        create_mysql_database(db_name, db_user, db_pass)

        # Step 2: Download WordPress
        download_wordpress(site_dir)

        # Step 3: Create wp-config.php
        create_wp_config(site_dir, db_name, db_user, db_pass, domain)

        # Step 4: Create PHP-FPM pool
        create_php_fpm_pool(site_name)

        # Step 5: Create Nginx config
        create_nginx_config(site_name, domain)

        # Step 6: Set permissions
        set_permissions(site_dir)

        # Step 7: Install WordPress core
        install_wordpress_core(
            site_dir, site_title, "admin", admin_password, admin_email, domain
        )

        # Register in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO wordpress_sites 
            (site_name, domain, admin_email, site_path, status, mysql_database, mysql_user)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site_name,
                domain,
                admin_email,
                str(site_dir),
                "running",
                db_name,
                db_user,
            ),
        )
        site_id = cursor.lastrowid

        # Log deployment
        cursor.execute(
            """
            INSERT INTO deployment_logs (domain_name, action, status, message)
            VALUES (?, 'wordpress_deploy', 'success', ?)
            """,
            (domain, f"WordPress deployed: {site_name}"),
        )

        conn.commit()
        conn.close()

        logger.info(f"✅ WordPress site '{site_name}' deployed successfully!")

        return {
            "success": True,
            "site_id": site_id,
            "domain": domain,
            "admin_url": f"http://{domain}/wp-admin",
            "site_url": f"http://{domain}",
            "credentials": {
                "admin_user": "admin",
                "admin_password": admin_password,
                "admin_email": admin_email,
            },
        }

    except Exception as e:
        logger.error(f"❌ Deployment failed: {e}")

        # Clean up on failure
        try:
            if site_dir.exists():
                shutil.rmtree(site_dir, ignore_errors=True)
            delete_php_fpm_pool(site_name)
            delete_nginx_config(site_name)
            delete_mysql_database(db_name, db_user)
        except Exception as cleanup_error:
            logger.warning(f"Cleanup also failed: {cleanup_error}")

        raise


def manage_wordpress_site(site_name, action):
    """Manage WordPress site (restart or delete)"""
    if action == "delete":
        cleanup_wordpress_site(site_name)
        return {"success": True, "message": f"{site_name} deleted"}
    elif action == "restart":
        # Restart services
        subprocess.run(["sudo", "systemctl", "reload", "php8.3-fpm"], check=False)
        subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=False)
        return {"success": True, "message": f"{site_name} services restarted"}
    else:
        return {
            "success": False,
            "message": f"Unknown action: {action}. Use 'delete' or 'restart'",
        }


def install_plugin(site_name, plugin_name, activate=True):
    """Install WordPress plugin"""
    site_dir = WORDPRESS_BASE_DIR / site_name

    cmd = ["wp", "plugin", "install", plugin_name, f"--path={site_dir}", "--allow-root"]
    if activate:
        cmd.append("--activate")

    result = subprocess.run(cmd, capture_output=True, text=True)

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "error": result.stderr,
    }


def cleanup_wordpress_site(site_name):
    """Complete cleanup of a WordPress site"""
    logger.info(f"🧹 Cleaning up WordPress site: {site_name}")

    # Get site info from database
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT mysql_database, mysql_user FROM wordpress_sites WHERE site_name = ?",
        (site_name,),
    )
    row = cursor.fetchone()

    if row:
        db_name, db_user = row
        # Delete database
        delete_mysql_database(db_name, db_user)

    # Delete from database
    cursor.execute("DELETE FROM wordpress_sites WHERE site_name = ?", (site_name,))

    # Log cleanup
    cursor.execute(
        """
        INSERT INTO deployment_logs (domain_name, action, status, message)
        VALUES (?, 'wordpress_cleanup', 'success', ?)
        """,
        (site_name, f"WordPress site cleaned up: {site_name}"),
    )

    conn.commit()
    conn.close()

    # Delete PHP-FPM pool
    delete_php_fpm_pool(site_name)

    # Delete Nginx config
    delete_nginx_config(site_name)

    # Delete site directory
    site_dir = WORDPRESS_BASE_DIR / site_name
    if site_dir.exists():
        shutil.rmtree(site_dir, ignore_errors=True)

    logger.info(f"✅ Cleanup complete: {site_name}")
    return {"success": True, "message": f"Site {site_name} cleaned up"}


def list_wordpress_sites():
    """List all WordPress sites"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, site_name, domain, status, admin_email, created_at 
        FROM wordpress_sites 
        ORDER BY created_at DESC
        """
    )

    sites = []
    for row in cursor.fetchall():
        site_id, site_name, domain, status, admin_email, created_at = row
        sites.append(
            {
                "id": site_id,
                "name": site_name,
                "domain": domain,
                "status": status,
                "admin_email": admin_email,
                "created_at": created_at,
                "admin_url": f"http://{domain}/wp-admin",
                "site_url": f"http://{domain}",
                "type": "traditional",
            }
        )

    conn.close()
    return sites


def execute_wp_cli(site_name, command):
    """Execute WP-CLI command"""
    site_dir = WORDPRESS_BASE_DIR / site_name

    if not site_dir.exists():
        return {
            "success": False,
            "output": "",
            "error": f"Site directory not found: {site_dir}",
        }

    cmd = ["wp"] + command.split() + [f"--path={site_dir}", "--allow-root"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "error": result.stderr,
    }


# ============================================================================
# WooCommerce Support (Traditional)
# ============================================================================


def setup_woocommerce(site_name, config=None):
    """Install and setup WooCommerce"""
    if config is None:
        config = {}

    site_dir = WORDPRESS_BASE_DIR / site_name

    # Install WooCommerce plugin
    result = install_plugin(site_name, "woocommerce", activate=True)

    if not result["success"]:
        return result

    # Configure WooCommerce settings
    settings = {
        "woocommerce_store_address": config.get("store_address", ""),
        "woocommerce_store_city": config.get("store_city", ""),
        "woocommerce_store_postcode": config.get("store_postcode", ""),
        "woocommerce_default_country": config.get("store_country", "ZA:WC"),
        "woocommerce_currency": config.get("currency", "ZAR"),
        "woocommerce_price_num_decimals": config.get("price_decimals", "2"),
        "woocommerce_weight_unit": config.get("weight_unit", "kg"),
        "woocommerce_dimension_unit": config.get("dimension_unit", "cm"),
    }

    for option, value in settings.items():
        if value:
            subprocess.run(
                [
                    "wp",
                    "option",
                    "update",
                    option,
                    str(value),
                    f"--path={site_dir}",
                    "--allow-root",
                ],
                check=False,
            )

    # Set store pages
    subprocess.run(
        [
            "wp",
            "wc",
            "tool",
            "run",
            "install_pages",
            f"--path={site_dir}",
            "--allow-root",
            "--user=1",
        ],
        check=False,
    )

    return {
        "success": True,
        "message": "WooCommerce installed and configured",
        "store_url": f"http://{site_name}/shop",
    }


def create_sample_products(site_name, count=5):
    """Create sample WooCommerce products"""
    site_dir = WORDPRESS_BASE_DIR / site_name
    created = 0

    for i in range(1, count + 1):
        try:
            result = subprocess.run(
                [
                    "wp",
                    "wc",
                    "product",
                    "create",
                    f"--name=Sample Product {i}",
                    f"--regular_price={100 * i}",
                    "--type=simple",
                    "--status=publish",
                    f"--path={site_dir}",
                    "--allow-root",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                created += 1
            else:
                logger.warning(f"Failed to create product {i}: {result.stderr}")
        except Exception as e:
            logger.warning(f"Product {i} failed: {e}")

    return {
        "success": True,
        "products_created": created,
        "message": f"Created {created} sample products",
    }


def get_store_info(site_name):
    """Get WooCommerce store information"""
    site_dir = WORDPRESS_BASE_DIR / site_name

    # Check if WooCommerce is active
    result = subprocess.run(
        [
            "wp",
            "plugin",
            "is-active",
            "woocommerce",
            f"--path={site_dir}",
            "--allow-root",
        ],
        capture_output=True,
        text=True,
    )

    woocommerce_active = result.returncode == 0

    # Get store information
    store_info = {}
    if woocommerce_active:
        # Get currency
        currency_result = subprocess.run(
            [
                "wp",
                "option",
                "get",
                "woocommerce_currency",
                f"--path={site_dir}",
                "--allow-root",
            ],
            capture_output=True,
            text=True,
        )

        if currency_result.returncode == 0:
            store_info["currency"] = currency_result.stdout.strip()

    return {
        "success": True,
        "woocommerce_active": woocommerce_active,
        "site_name": site_name,
        "store_info": store_info,
    }


# ============================================================================
# Permission Checks
# ============================================================================


def ensure_permissions():
    """
    Ensure 'deploy' user has proper permissions for WordPress deployment
    """
    import grp

    DEPLOY_USER = "deploy"
    WWW_DIR = Path("/var/www/wordpress")

    logger.info("🔍 Checking deployment permissions...")

    try:
        # Ensure www-data group exists and deploy is member
        www_data_groups = grp.getgrnam("www-data")
        if DEPLOY_USER not in www_data_groups.gr_mem:
            logger.warning(f"⚠️ User '{DEPLOY_USER}' not in 'www-data' group.")
            logger.info(f"   Run: sudo usermod -aG www-data {DEPLOY_USER}")
            return False

        # Ensure WordPress directory exists and has correct permissions
        WWW_DIR.mkdir(parents=True, exist_ok=True)

        # Set ownership to www-data
        subprocess.run(
            ["sudo", "chown", "-R", "www-data:www-data", str(WWW_DIR)], check=True
        )
        subprocess.run(["sudo", "chmod", "-R", "755", str(WWW_DIR)], check=True)

        logger.info("✅ Permissions OK for WordPress deployment")
        return True

    except Exception as e:
        logger.error(f"❌ Permission check failed: {e}")
        return False
