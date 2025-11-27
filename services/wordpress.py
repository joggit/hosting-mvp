"""
WordPress deployment and management service - TRADITIONAL APPROACH
No Docker - uses shared MySQL, PHP-FPM pools, and nginx server blocks
Like the Next.js deployment but for WordPress
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
PHP_FPM_POOL_DIR = Path("/etc/php/8.3/fpm/pool.d")  # Adjust version as needed
MYSQL_HOST = "localhost"
MYSQL_ROOT_USER = "root"
MYSQL_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "root_password")


# ============================================================================
# Helper Functions
# ============================================================================


def generate_password(length=32):
    """Generate secure alphanumeric password"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def run_command(cmd, shell=False, check=True, **kwargs):
    """Run a shell command and return result"""
    try:
        if isinstance(cmd, str) and not shell:
            cmd = cmd.split()

        result = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, check=check, **kwargs
        )
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e.stderr}")
        raise


def run_mysql_query(query, database=None):
    """Execute MySQL query"""
    cmd = [
        "mysql",
        "-u",
        MYSQL_ROOT_USER,
        f"-p{MYSQL_ROOT_PASSWORD}",
    ]

    if database:
        cmd.extend(["-D", database])

    cmd.extend(["-e", query])

    result = run_command(cmd, check=True)
    return result.stdout


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

    # Create user and grant privileges
    run_mysql_query(
        f"""
        CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}';
        GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost';
        FLUSH PRIVILEGES;
    """
    )

    logger.info(f"✅ Database {db_name} created with user {db_user}")


def delete_mysql_database(db_name, db_user):
    """Delete MySQL database and user"""
    logger.info(f"Deleting MySQL database: {db_name}")

    run_mysql_query(f"DROP DATABASE IF EXISTS `{db_name}`;", check=False)
    run_mysql_query(f"DROP USER IF EXISTS '{db_user}'@'localhost';", check=False)
    run_mysql_query("FLUSH PRIVILEGES;")

    logger.info(f"✅ Database {db_name} deleted")


# ============================================================================
# PHP-FPM Pool Management
# ============================================================================


def create_php_fpm_pool(site_name, user="www-data", group="www-data"):
    """Create dedicated PHP-FPM pool for site"""
    logger.info(f"Creating PHP-FPM pool for {site_name}")

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

php_value[session.save_handler] = files
php_value[session.save_path] = /var/lib/php/sessions
"""

    pool_file = PHP_FPM_POOL_DIR / f"{site_name}.conf"
    pool_file.write_text(pool_config)

    # Reload PHP-FPM
    run_command("systemctl reload php8.3-fpm", shell=True)

    logger.info(f"✅ PHP-FPM pool created: {site_name}")


def delete_php_fpm_pool(site_name):
    """Delete PHP-FPM pool"""
    logger.info(f"Deleting PHP-FPM pool for {site_name}")

    pool_file = PHP_FPM_POOL_DIR / f"{site_name}.conf"
    if pool_file.exists():
        pool_file.unlink()
        run_command("systemctl reload php8.3-fpm", shell=True)

    logger.info(f"✅ PHP-FPM pool deleted: {site_name}")


# ============================================================================
# Nginx Configuration
# ============================================================================


def create_nginx_config(site_name, domain):
    """Create nginx server block for WordPress site"""
    logger.info(f"Creating nginx config for {domain}")

    site_root = WORDPRESS_BASE_DIR / site_name

    nginx_config = f"""server {{
    listen 80;
    server_name {domain};
    
    root {site_root};
    index index.php index.html;
    
    access_log /var/log/nginx/{site_name}-access.log;
    error_log /var/log/nginx/{site_name}-error.log;
    
    # WordPress permalinks
    location / {{
        try_files $uri $uri/ /index.php?$args;
    }}
    
    # PHP handling
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php-fpm-{site_name}.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}
    
    # Deny access to sensitive files
    location ~ /\\.ht {{
        deny all;
    }}
    
    location = /favicon.ico {{
        log_not_found off;
        access_log off;
    }}
    
    location = /robots.txt {{
        log_not_found off;
        access_log off;
    }}
    
    # Static files caching
    location ~* \\.(css|js|jpg|jpeg|png|gif|ico|svg|woff|woff2|ttf)$ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}
}}
"""

    # Write config
    config_file = NGINX_SITES_AVAILABLE / f"{site_name}.conf"
    config_file.write_text(nginx_config)

    # Enable site
    enabled_link = NGINX_SITES_ENABLED / f"{site_name}.conf"
    if enabled_link.exists():
        enabled_link.unlink()
    enabled_link.symlink_to(config_file)

    # Test and reload nginx
    test_result = run_command("nginx -t", shell=True, check=False)
    if test_result.returncode == 0:
        run_command("systemctl reload nginx", shell=True)
        logger.info(f"✅ Nginx config created and activated for {domain}")
    else:
        logger.error(f"Nginx config test failed: {test_result.stderr}")
        raise Exception("Invalid nginx configuration")


def delete_nginx_config(site_name):
    """Delete nginx configuration"""
    logger.info(f"Deleting nginx config for {site_name}")

    enabled_link = NGINX_SITES_ENABLED / f"{site_name}.conf"
    config_file = NGINX_SITES_AVAILABLE / f"{site_name}.conf"

    if enabled_link.exists():
        enabled_link.unlink()
    if config_file.exists():
        config_file.unlink()

    run_command("systemctl reload nginx", shell=True)
    logger.info(f"✅ Nginx config deleted")


# ============================================================================
# WordPress Installation
# ============================================================================


def download_wordpress(site_dir):
    """Download and extract WordPress"""
    logger.info("Downloading WordPress...")

    site_dir.mkdir(parents=True, exist_ok=True)

    # Download WordPress
    wp_zip = site_dir.parent / "wordpress.tar.gz"
    run_command(
        ["wget", "https://wordpress.org/latest.tar.gz", "-O", str(wp_zip), "-q"]
    )

    # Extract
    run_command(["tar", "xzf", str(wp_zip), "-C", str(site_dir.parent)])

    # Move files from wordpress/ subdirectory to site root
    wp_temp = site_dir.parent / "wordpress"
    for item in wp_temp.iterdir():
        shutil.move(str(item), str(site_dir))
    wp_temp.rmdir()
    wp_zip.unlink()

    logger.info("✅ WordPress downloaded and extracted")


def create_wp_config(site_dir, db_name, db_user, db_password, domain):
    """Create wp-config.php"""
    logger.info("Creating wp-config.php...")

    wp_config_sample = site_dir / "wp-config-sample.php"
    wp_config = site_dir / "wp-config.php"

    if not wp_config_sample.exists():
        raise Exception("wp-config-sample.php not found")

    config_content = wp_config_sample.read_text()

    # Replace database settings
    config_content = config_content.replace("database_name_here", db_name)
    config_content = config_content.replace("username_here", db_user)
    config_content = config_content.replace("password_here", db_password)
    config_content = config_content.replace("localhost", MYSQL_HOST)

    # Generate salts
    salts = {
        "AUTH_KEY": generate_password(64),
        "SECURE_AUTH_KEY": generate_password(64),
        "LOGGED_IN_KEY": generate_password(64),
        "NONCE_KEY": generate_password(64),
        "AUTH_SALT": generate_password(64),
        "SECURE_AUTH_SALT": generate_password(64),
        "LOGGED_IN_SALT": generate_password(64),
        "NONCE_SALT": generate_password(64),
    }

    for key, value in salts.items():
        config_content = config_content.replace(
            f"put your unique phrase here", value, 1
        )

    # Add custom settings
    custom_settings = f"""
// Custom Settings
define('WP_HOME', 'http://{domain}');
define('WP_SITEURL', 'http://{domain}');
define('WP_MEMORY_LIMIT', '256M');
define('WP_MAX_MEMORY_LIMIT', '512M');
"""

    # Insert before "That's all"
    config_content = config_content.replace(
        "/* That's all, stop editing!",
        custom_settings + "\n/* That's all, stop editing!",
    )

    wp_config.write_text(config_content)
    logger.info("✅ wp-config.php created")


def install_wordpress_core(
    site_dir, site_title, admin_user, admin_password, admin_email, domain
):
    """Install WordPress using WP-CLI"""
    logger.info("Installing WordPress core...")

    # Download WP-CLI if not exists
    wpcli = Path("/usr/local/bin/wp")
    if not wpcli.exists():
        logger.info("Downloading WP-CLI...")
        run_command(
            [
                "curl",
                "-O",
                "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
            ]
        )
        run_command(["chmod", "+x", "wp-cli.phar"])
        run_command(["mv", "wp-cli.phar", str(wpcli)])

    # Install WordPress
    result = run_command(
        [
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
        ],
        check=False,
    )

    if result.returncode != 0 and "already installed" not in result.stderr.lower():
        raise Exception(f"WordPress installation failed: {result.stderr}")

    logger.info("✅ WordPress core installed")


def set_permissions(site_dir):
    """Set correct file permissions"""
    logger.info("Setting file permissions...")

    run_command(f"chown -R www-data:www-data {site_dir}", shell=True)
    run_command(f"find {site_dir} -type d -exec chmod 755 {{}} \\;", shell=True)
    run_command(f"find {site_dir} -type f -exec chmod 644 {{}} \\;", shell=True)

    logger.info("✅ Permissions set")


# ============================================================================
# Main WordPress Deployment
# ============================================================================


def deploy_wordpress_site(
    site_name, domain, admin_email, admin_password, site_title="My WordPress Site"
):
    """
    Deploy a WordPress site using traditional hosting approach

    Returns: dict with site details
    """
    logger.info(f"🚀 Deploying WordPress site: {site_name}")

    # Generate database credentials
    db_name = f"wp_{site_name}"
    db_user = f"wp_{site_name}"
    db_password = generate_password()

    site_dir = WORDPRESS_BASE_DIR / site_name

    try:
        # 1. Create MySQL database
        create_mysql_database(db_name, db_user, db_password)

        # 2. Download WordPress
        download_wordpress(site_dir)

        # 3. Create wp-config.php
        create_wp_config(site_dir, db_name, db_user, db_password, domain)

        # 4. Create PHP-FPM pool
        create_php_fpm_pool(site_name)

        # 5. Create nginx config
        create_nginx_config(site_name, domain)

        # 6. Set permissions
        set_permissions(site_dir)

        # 7. Install WordPress
        install_wordpress_core(
            site_dir, site_title, "admin", admin_password, admin_email, domain
        )

        # 8. Save to database
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO wordpress_sites 
            (site_name, domain, port, container_name, admin_email, 
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
            (domain, f"WordPress site deployed: {site_name}"),
        )

        conn.commit()
        conn.close()

        logger.info(f"✅ WordPress site deployed successfully: {site_name}")

        return {
            "success": True,
            "site_id": site_id,
            "site_name": site_name,
            "domain": domain,
            "admin_url": f"http://{domain}/wp-admin",
            "site_url": f"http://{domain}",
            "admin_user": "admin",
            "site_dir": str(site_dir),
            "database": db_name,
        }

    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        # Cleanup on failure
        cleanup_wordpress_site(site_name)
        raise


def cleanup_wordpress_site(site_name):
    """Complete cleanup of WordPress site"""
    logger.info(f"Cleaning up WordPress site: {site_name}")

    try:
        # Get database info
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT mysql_database, mysql_user FROM wordpress_sites WHERE site_name = ?",
            (site_name,),
        )
        result = cursor.fetchone()

        if result:
            db_name, db_user = result
            delete_mysql_database(db_name, db_user)

        # Delete from database
        cursor.execute("DELETE FROM wordpress_sites WHERE site_name = ?", (site_name,))
        conn.commit()
        conn.close()

    except Exception as e:
        logger.warning(f"Database cleanup warning: {e}")

    # Delete PHP-FPM pool
    try:
        delete_php_fpm_pool(site_name)
    except Exception as e:
        logger.warning(f"PHP-FPM cleanup warning: {e}")

    # Delete nginx config
    try:
        delete_nginx_config(site_name)
    except Exception as e:
        logger.warning(f"Nginx cleanup warning: {e}")

    # Delete files
    site_dir = WORDPRESS_BASE_DIR / site_name
    if site_dir.exists():
        shutil.rmtree(site_dir, ignore_errors=True)

    logger.info(f"✅ Cleanup complete for {site_name}")


# ============================================================================
# WooCommerce Deployment
# ============================================================================


def deploy_woocommerce_site(
    site_name, domain, admin_email, admin_password, site_title, store_config
):
    """
    Deploy WordPress + WooCommerce

    Args:
        store_config: dict with store settings
    """
    logger.info(f"🛒 Deploying WooCommerce site: {site_name}")

    # Deploy WordPress first
    result = deploy_wordpress_site(
        site_name, domain, admin_email, admin_password, site_title
    )

    site_dir = WORDPRESS_BASE_DIR / site_name

    try:
        # Install WooCommerce
        logger.info("Installing WooCommerce...")
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

        # Configure WooCommerce
        logger.info("Configuring WooCommerce...")

        # Set store address
        if store_config.get("store_address"):
            run_command(
                [
                    "wp",
                    "option",
                    "update",
                    "woocommerce_store_address",
                    store_config["store_address"],
                    f"--path={site_dir}",
                    "--allow-root",
                ]
            )

        # Set store city
        if store_config.get("store_city"):
            run_command(
                [
                    "wp",
                    "option",
                    "update",
                    "woocommerce_store_city",
                    store_config["store_city"],
                    f"--path={site_dir}",
                    "--allow-root",
                ]
            )

        # Set store country
        if store_config.get("store_country"):
            run_command(
                [
                    "wp",
                    "option",
                    "update",
                    "woocommerce_default_country",
                    store_config["store_country"],
                    f"--path={site_dir}",
                    "--allow-root",
                ]
            )

        # Set currency
        if store_config.get("currency"):
            run_command(
                [
                    "wp",
                    "option",
                    "update",
                    "woocommerce_currency",
                    store_config["currency"],
                    f"--path={site_dir}",
                    "--allow-root",
                ]
            )

        # Create sample products if requested
        if store_config.get("create_sample_products"):
            count = store_config.get("sample_product_count", 5)
            logger.info(f"Creating {count} sample products...")

            for i in range(1, count + 1):
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

        result["woocommerce"] = {"installed": True, "shop_url": f"http://{domain}/shop"}

        logger.info(f"✅ WooCommerce site deployed successfully")
        return result

    except Exception as e:
        logger.error(f"WooCommerce setup failed: {e}")
        cleanup_wordpress_site(site_name)
        raise


# ============================================================================
# Site Management
# ============================================================================


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
        sites.append(
            {
                "id": row[0],
                "name": row[1],
                "domain": row[2],
                "status": row[3],
                "admin_email": row[4],
                "created_at": row[5],
                "admin_url": f"http://{row[2]}/wp-admin",
                "type": "traditional",
            }
        )

    conn.close()
    return sites


def execute_wp_cli(site_name, command):
    """Execute WP-CLI command"""
    site_dir = WORDPRESS_BASE_DIR / site_name

    cmd = ["wp"] + command.split() + [f"--path={site_dir}", "--allow-root"]

    result = run_command(cmd, check=False)

    return {
        "success": result.returncode == 0,
        "output": result.stdout,
        "error": result.stderr,
    }
