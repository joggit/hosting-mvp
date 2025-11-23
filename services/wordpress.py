"""
WordPress deployment and management service
Handles Docker-based WordPress deployments
"""

import os
import subprocess
import json
import logging
import secrets
import string
from pathlib import Path
from services.database import get_db

logger = logging.getLogger(__name__)

WORDPRESS_BASE_DIR = "/var/www/wordpress-sites"


def generate_password(length=20):
    """Generate secure random password"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_wordpress_site(
    site_name, domain, port, admin_email, admin_password, site_title
):
    """
    Deploy a new WordPress site using Docker

    Returns: dict with site details or raises exception
    """
    logger.info(f"Creating WordPress site: {site_name}")

    # Generate passwords
    db_password = generate_password()
    db_root_password = generate_password()

    # Container names
    wp_container = f"{site_name}_wordpress"
    mysql_container = f"{site_name}_mysql"
    cli_container = f"{site_name}_cli"

    # Create site directory
    site_dir = os.path.join(WORDPRESS_BASE_DIR, site_name)
    os.makedirs(site_dir, exist_ok=True)

    # Create docker-compose.yml
    docker_compose = f"""version: '3.8'

services:
  wordpress:
    image: wordpress:latest
    container_name: {wp_container}
    restart: always
    ports:
      - "{port}:80"
    environment:
      WORDPRESS_DB_HOST: mysql
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: {db_password}
      WORDPRESS_DB_NAME: wordpress
      WORDPRESS_CONFIG_EXTRA: |
        define('WP_HOME', 'http://{domain}');
        define('WP_SITEURL', 'http://{domain}');
        define('WP_MEMORY_LIMIT', '256M');
        define('WP_MAX_MEMORY_LIMIT', '512M');
    volumes:
      - wordpress_data:/var/www/html
    depends_on:
      - mysql
    networks:
      - wordpress_network

  mysql:
    image: mysql:8.0
    container_name: {mysql_container}
    restart: always
    environment:
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wordpress
      MYSQL_PASSWORD: {db_password}
      MYSQL_ROOT_PASSWORD: {db_root_password}
    volumes:
      - mysql_data:/var/lib/mysql
    networks:
      - wordpress_network
    command: '--default-authentication-plugin=mysql_native_password'

  wp-cli:
    image: wordpress:cli
    container_name: {cli_container}
    volumes:
      - wordpress_data:/var/www/html
    depends_on:
      - wordpress
      - mysql
    networks:
      - wordpress_network
    environment:
      WORDPRESS_DB_HOST: mysql
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: {db_password}
      WORDPRESS_DB_NAME: wordpress

volumes:
  wordpress_data:
  mysql_data:

networks:
  wordpress_network:
    driver: bridge
"""

    # Write docker-compose.yml
    compose_path = os.path.join(site_dir, "docker-compose.yml")
    with open(compose_path, "w") as f:
        f.write(docker_compose)

    logger.info(f"Docker Compose written to: {compose_path}")

    # Start containers
    logger.info("Starting Docker containers...")
    try:
        subprocess.run(
            ["docker-compose", "up", "-d"],
            cwd=site_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("✅ Containers started")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to start containers: {e.stderr}")
        raise Exception(f"Docker Compose failed: {e.stderr}")

    # Wait for WordPress to be ready
    logger.info("Waiting for WordPress to initialize...")
    import time

    time.sleep(15)

    # Install WordPress with WP-CLI
    logger.info("Installing WordPress...")
    wp_install_cmd = [
        "docker",
        "exec",
        cli_container,
        "wp",
        "core",
        "install",
        f"--url=http://{domain}",
        f"--title={site_title}",
        "--admin_user=admin",
        f"--admin_password={admin_password}",
        f"--admin_email={admin_email}",
        "--skip-email",
    ]

    try:
        result = subprocess.run(
            wp_install_cmd, capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0:
            logger.warning(f"WP install output: {result.stderr}")
            # Try again after a short wait
            time.sleep(5)
            result = subprocess.run(
                wp_install_cmd, capture_output=True, text=True, timeout=60
            )

        logger.info("✅ WordPress installed")
    except Exception as e:
        logger.error(f"WordPress installation error: {e}")
        raise Exception(f"WordPress installation failed: {e}")

    # Save to database
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO wordpress_sites 
        (site_name, domain, port, container_name, mysql_container, cli_container, 
         admin_email, docker_compose_path, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running')
    """,
        (
            site_name,
            domain,
            port,
            wp_container,
            mysql_container,
            cli_container,
            admin_email,
            compose_path,
        ),
    )

    site_id = cursor.lastrowid

    # Log deployment
    cursor.execute(
        """
        INSERT INTO deployment_logs (domain_name, action, status, message)
        VALUES (?, 'wordpress_deploy', 'success', ?)
    """,
        (domain, f"WordPress site deployed: {site_name}"),
    )

    conn.commit()
    conn.close()

    logger.info(f"✅ WordPress site created: {site_name}")

    return {
        "site_id": site_id,
        "site_name": site_name,
        "domain": domain,
        "port": port,
        "admin_url": f"http://{domain}/wp-admin",
        "containers": {
            "wordpress": wp_container,
            "mysql": mysql_container,
            "cli": cli_container,
        },
    }


def execute_wp_cli(site_name, command):
    """Execute WP-CLI command on a WordPress site"""
    logger.info(f"Executing WP-CLI on {site_name}: {command}")

    # Get site details
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT cli_container, id FROM wordpress_sites WHERE site_name = ?",
        (site_name,),
    )
    result = cursor.fetchone()

    if not result:
        conn.close()
        raise Exception(f"WordPress site not found: {site_name}")

    cli_container, site_id = result

    # Execute command
    try:
        result = subprocess.run(
            ["docker", "exec", cli_container, "wp"] + command.split(),
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Log command execution
        cursor.execute(
            """
            INSERT INTO wordpress_cli_history (site_id, command, output, exit_code)
            VALUES (?, ?, ?, ?)
        """,
            (site_id, command, result.stdout + result.stderr, result.returncode),
        )
        conn.commit()
        conn.close()

        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
            "exit_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        conn.close()
        raise Exception("Command timed out")
    except Exception as e:
        conn.close()
        raise Exception(f"Command execution failed: {e}")


def manage_wordpress_site(site_name, action):
    """Manage WordPress site (start, stop, restart, delete)"""
    logger.info(f"Managing WordPress site {site_name}: {action}")

    # Get site details
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT docker_compose_path, id FROM wordpress_sites WHERE site_name = ?",
        (site_name,),
    )
    result = cursor.fetchone()

    if not result:
        conn.close()
        raise Exception(f"WordPress site not found: {site_name}")

    compose_path, site_id = result
    site_dir = os.path.dirname(compose_path)

    try:
        if action == "start":
            subprocess.run(["docker-compose", "start"], cwd=site_dir, check=True)
            cursor.execute(
                "UPDATE wordpress_sites SET status = ? WHERE id = ?",
                ("running", site_id),
            )

        elif action == "stop":
            subprocess.run(["docker-compose", "stop"], cwd=site_dir, check=True)
            cursor.execute(
                "UPDATE wordpress_sites SET status = ? WHERE id = ?",
                ("stopped", site_id),
            )

        elif action == "restart":
            subprocess.run(["docker-compose", "restart"], cwd=site_dir, check=True)
            cursor.execute(
                "UPDATE wordpress_sites SET status = ? WHERE id = ?",
                ("running", site_id),
            )

        elif action == "delete":
            # Stop and remove containers
            subprocess.run(["docker-compose", "down", "-v"], cwd=site_dir, check=True)

            # Delete from database
            cursor.execute("DELETE FROM wordpress_sites WHERE id = ?", (site_id,))

            # Remove directory
            import shutil

            shutil.rmtree(site_dir, ignore_errors=True)

        else:
            raise Exception(f"Unknown action: {action}")

        # Log action
        cursor.execute(
            """
            INSERT INTO deployment_logs (domain_name, action, status, message)
            VALUES (?, ?, 'success', ?)
        """,
            (site_name, f"wordpress_{action}", f"Action {action} completed"),
        )

        conn.commit()
        conn.close()

        logger.info(f"✅ Action {action} completed for {site_name}")
        return {"success": True, "action": action}

    except Exception as e:
        conn.close()
        logger.error(f"Management action failed: {e}")
        raise


def list_wordpress_sites():
    """List all WordPress sites"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, site_name, domain, port, status, admin_email, created_at
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
                "port": row[3],
                "status": row[4],
                "admin_email": row[5],
                "created_at": row[6],
                "admin_url": f"http://{row[2]}/wp-admin",
            }
        )

    conn.close()
    return sites


def install_plugin(site_name, plugin_name, activate=True):
    """Install a WordPress plugin"""
    logger.info(f"Installing plugin {plugin_name} on {site_name}")

    # Install plugin
    cmd = f"plugin install {plugin_name}"
    if activate:
        cmd += " --activate"

    result = execute_wp_cli(site_name, cmd)

    if result["success"]:
        # Save to database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM wordpress_sites WHERE site_name = ?", (site_name,)
        )
        site_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT OR REPLACE INTO wordpress_plugins (site_id, plugin_name, is_active)
            VALUES (?, ?, ?)
        """,
            (site_id, plugin_name, activate),
        )

        conn.commit()
        conn.close()

    return result
