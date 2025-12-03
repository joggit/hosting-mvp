"""
COMPLETE REPLACEMENT FOR services/wordpress.py MySQL SECTION

Replace everything from the imports through run_mysql_query() function
(approximately lines 1-115 in your current file)
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
MYSQL_HOSTING_USER = "hosting_manager"  # NEW: Alternative user


# ============================================================================
# 🔒 SECURE MySQL Root Password Retrieval - IMPROVED VERSION
# ============================================================================
def get_mysql_root_password():
    """
    Get MySQL credentials with multiple fallback strategies.

    Returns:
        tuple: (username, password) to use for MySQL connection
    """
    password = None
    username = "root"

    # Strategy 1: Environment variable
    password = os.getenv("MYSQL_ROOT_PASSWORD")
    if password:
        logger.debug("MySQL password from environment")
        return (username, password.strip())

    # Strategy 2: Primary location
    secure_path = Path("/etc/hosting-manager/mysql_root_password")
    if secure_path.exists():
        try:
            password = secure_path.read_text().strip()
            logger.debug(f"MySQL password from {secure_path}")
            return (username, password)
        except PermissionError:
            logger.warning(f"⚠️ Permission denied reading {secure_path}")
        except Exception as e:
            logger.warning(f"Failed to read {secure_path}: {e}")

    # Strategy 3: Root home fallback
    root_path = Path("/root/.mysql_root_password")
    if root_path.exists():
        try:
            password = root_path.read_text().strip()
            logger.debug(f"MySQL password from {root_path}")
            return (username, password)
        except Exception as e:
            logger.debug(f"Could not read {root_path}: {e}")

    # Strategy 4: Try alternative user with found password
    if password and secure_path.exists():
        logger.info(f"Attempting connection with '{MYSQL_HOSTING_USER}' user")
        return (MYSQL_HOSTING_USER, password)

    # Final error with diagnostics
    current_user = os.getenv("USER", "unknown")
    try:
        groups_output = subprocess.run(
            ["groups", current_user], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except:
        groups_output = "unknown"

    error_msg = f"""
MySQL password not found.

Current user: {current_user}
Groups: {groups_output}

Fix:
  1. sudo chown root:hosting /etc/hosting-manager/mysql_root_password
  2. sudo chmod 640 /etc/hosting-manager/mysql_root_password
  3. sudo usermod -aG hosting {current_user}
  4. Log out and log back in
  5. Verify: cat /etc/hosting-manager/mysql_root_password
"""

    logger.error(error_msg)
    raise FileNotFoundError(error_msg)


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
    """
    Run MySQL query - IMPROVED VERSION

    Returns:
        subprocess.CompletedProcess result
    """
    # Get credentials (now returns tuple)
    username, password = get_mysql_root_password()

    cmd = [
        "mysql",
        "-u",
        username,
        f"-p{password}",
        "-h",
        MYSQL_HOST,
    ]

    if database:
        cmd.extend(["-D", database])

    cmd.extend(["-e", query])

    try:
        result = run_command(cmd, check=True)
        return result

    except subprocess.CalledProcessError as e:
        # Enhanced error logging
        cmd_safe = " ".join(cmd[:3]) + " -p*** ..."
        logger.error(f"MySQL query failed")
        logger.error(f"Command: {cmd_safe}")
        logger.error(f"Query: {query[:200]}...")
        logger.error(f"Error: {e.stderr}")

        # Provide helpful error messages
        if "Access denied" in e.stderr:
            logger.error(
                "\n❌ MySQL Authentication Failed\n"
                "Common causes:\n"
                "  1. Wrong password in /etc/hosting-manager/mysql_root_password\n"
                "  2. User doesn't exist\n"
                "  3. MySQL using auth_socket instead of password\n"
                "\n"
                "To fix:\n"
                "  sudo mysql\n"
                "  > ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'password';\n"
                "  > FLUSH PRIVILEGES;\n"
                "  > exit\n"
                "  Then update /etc/hosting-manager/mysql_root_password with the correct password\n"
            )
        elif "Can't connect" in e.stderr:
            logger.error(
                "\n❌ Cannot Connect to MySQL\n"
                "Check:\n"
                "  1. MySQL is running: sudo systemctl status mysql\n"
                "  2. Socket exists: ls -la /var/run/mysqld/mysqld.sock\n"
            )
        elif "doesn't exist" in e.stderr:
            logger.error(
                f"\n❌ Database or table doesn't exist in query: {query[:100]}\n"
            )

        raise


# ============================================================================
# Continue with rest of wordpress.py below this line
# (MySQL Database Management, PHP-FPM Pool Management, etc.)
# ============================================================================

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


"""
Fixed Nginx functions for services/wordpress.py
Replace the existing create_nginx_config and delete_nginx_config functions
"""


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

    # Test and reload Nginx (with sudo)
    nginx_test = subprocess.run(["sudo", "nginx", "-t"], capture_output=True, text=True)

    if nginx_test.returncode == 0:
        subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=True)
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

    # Reload Nginx (with sudo)
    subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=False)

    logger.info(f"✅ Nginx config deleted: {site_name}")


# ============================================================================
# WordPress Installation
# ============================================================================


def download_wordpress(site_dir):
    """Download and extract WordPress core - FIXED VERSION"""
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

    # Extract WordPress WITH FIXED FLAGS
    logger.info("Extracting WordPress...")
    result = subprocess.run(
        [
            "sudo",
            "-u",
            "www-data",  # Run as www-data user
            "tar",
            "-xzf",
            str(wp_zip),
            "-C",
            str(site_dir.parent),
            "--strip-components=1",
            "--no-same-owner",  # FIX: Don't preserve ownership
            "--no-same-permissions",  # FIX: Don't preserve setgid permissions
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise Exception(f"Failed to extract WordPress: {result.stderr}")

    # Fix ownership after extraction
    subprocess.run(
        ["sudo", "chown", "-R", "www-data:www-data", str(site_dir)], check=True
    )

    # Clean up
    wp_zip.unlink(missing_ok=True)
    logger.info("✅ WordPress downloaded and extracted")


def create_wp_config(site_dir, db_name, db_user, db_pass, domain):
    """Create wp-config.php with proper permissions"""
    wp_config_path = site_dir / "wp-config.php"

    config_content = f"""<?php
define('DB_NAME', '{db_name}');
define('DB_USER', '{db_user}');
define('DB_PASSWORD', '{db_pass}');
define('DB_HOST', 'localhost');
define('DB_CHARSET', 'utf8');
define('DB_COLLATE', '');

$table_prefix = 'wp_';

define('WP_DEBUG', false);

if (!defined('ABSPATH'))
    define('ABSPATH', dirname(__FILE__) . '/');

require_once(ABSPATH . 'wp-settings.php');
"""

    # Write to temporary file first
    import tempfile

    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".php", delete=False)
    temp_file.write(config_content)
    temp_file.close()

    # Copy with sudo to ensure proper ownership
    import subprocess

    subprocess.run(["sudo", "cp", temp_file.name, str(wp_config_path)], check=True)

    # Set ownership to www-data
    subprocess.run(
        ["sudo", "chown", "www-data:www-data", str(wp_config_path)], check=True
    )

    subprocess.run(["sudo", "chmod", "644", str(wp_config_path)], check=True)

    # Clean up temp file
    import os

    os.unlink(temp_file.name)

    logger.info(f"✅ Created wp-config.php at {wp_config_path}")


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
    import pwd
    import subprocess

    DEPLOY_USER = "deploy"
    WWW_DIR = Path("/var/www/wordpress")

    logger.info("🔍 Checking deployment permissions...")

    try:
        # Check if deploy user exists
        try:
            pwd.getpwnam(DEPLOY_USER)
        except KeyError:
            logger.error(f"❌ User '{DEPLOY_USER}' does not exist")
            return False

        # Check if www-data group exists
        try:
            www_data_groups = grp.getgrnam("www-data")
        except KeyError:
            logger.error("❌ Group 'www-data' does not exist")
            return False

        # Check if deploy is in www-data group
        if DEPLOY_USER not in www_data_groups.gr_mem:
            logger.warning(f"⚠️ User '{DEPLOY_USER}' not in 'www-data' group.")
            logger.info(f"   Attempting to add '{DEPLOY_USER}' to 'www-data' group...")

            # Try to add deploy to www-data group
            try:
                subprocess.run(
                    ["sudo", "usermod", "-aG", "www-data", DEPLOY_USER], check=True
                )
                logger.info(f"✅ Added '{DEPLOY_USER}' to 'www-data' group")

                # Refresh group membership
                os.setgid(www_data_groups.gr_gid)
            except Exception as e:
                logger.error(f"❌ Failed to add user to group: {e}")
                logger.info(
                    f"   Please run manually: sudo usermod -aG www-data {DEPLOY_USER}"
                )
                return False

        # Ensure WordPress directory exists
        WWW_DIR.mkdir(parents=True, exist_ok=True)

        # Set proper ownership and permissions
        try:
            # Set ownership to www-data:www-data (but deploy can write via group)
            subprocess.run(
                ["sudo", "chown", "-R", "www-data:www-data", str(WWW_DIR)], check=True
            )

            # Set directory permissions
            subprocess.run(["sudo", "chmod", "-R", "2775", str(WWW_DIR)], check=True)

            # Ensure all files are group-writable
            subprocess.run(
                [
                    "sudo",
                    "find",
                    str(WWW_DIR),
                    "-type",
                    "f",
                    "-exec",
                    "chmod",
                    "664",
                    "{}",
                    "+",
                ],
                check=False,
            )

            # Ensure all directories are group-writable and have setgid
            subprocess.run(
                [
                    "sudo",
                    "find",
                    str(WWW_DIR),
                    "-type",
                    "d",
                    "-exec",
                    "chmod",
                    "2775",
                    "{}",
                    "+",
                ],
                check=False,
            )

            logger.info(f"✅ Permissions set for {WWW_DIR}")

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to set permissions: {e}")
            logger.info("   Ensure 'deploy' has passwordless sudo for chown/chmod")
            return False

        # Verify deploy can write to directory
        test_file = WWW_DIR / ".permission_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            logger.info("✅ 'deploy' can write to WordPress directory")
            return True
        except PermissionError:
            logger.error(f"❌ 'deploy' cannot write to {WWW_DIR}")
            logger.info("   Current permissions:")
            subprocess.run(["ls", "-la", str(WWW_DIR)], check=False)
            return False

    except Exception as e:
        logger.error(f"❌ Permission check failed: {e}")
        return False
