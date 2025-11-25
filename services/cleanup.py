"""
WordPress Cleanup Service
Handles deletion and cleanup of WordPress sites and Docker containers
"""

import os
import subprocess
import logging
import shutil
from services.database import get_db
from services.nginx_config import remove_nginx_site, reload_nginx

logger = logging.getLogger(__name__)


def list_sites_for_cleanup():
    """
    List all WordPress sites with their container status

    Returns:
        dict: List of sites with cleanup information
    """
    logger.info("Listing all WordPress sites for cleanup...")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, site_name, domain, port, container_name, mysql_container, 
               cli_container, docker_compose_path, status, created_at
        FROM wordpress_sites
        ORDER BY created_at DESC
    """
    )

    sites = []
    for row in cursor.fetchall():
        site = {
            "id": row[0],
            "site_name": row[1],
            "domain": row[2],
            "port": row[3],
            "container_name": row[4],
            "mysql_container": row[5],
            "cli_container": row[6],
            "docker_compose_path": row[7],
            "status": row[8],
            "created_at": row[9],
            "containers_running": False,
            "container_details": [],
        }

        # Check if containers are actually running
        containers = [row[4], row[5], row[6]]
        for container in containers:
            if container:
                try:
                    result = subprocess.run(
                        [
                            "docker",
                            "ps",
                            "-a",
                            "--filter",
                            f"name={container}",
                            "--format",
                            "{{.Names}}:{{.Status}}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.stdout.strip():
                        status = result.stdout.strip().split(":")
                        site["container_details"].append(
                            {
                                "name": status[0] if len(status) > 0 else container,
                                "status": status[1] if len(status) > 1 else "unknown",
                            }
                        )
                        if "Up" in result.stdout:
                            site["containers_running"] = True
                except Exception as e:
                    logger.debug(f"Error checking container {container}: {e}")

        sites.append(site)

    conn.close()

    return {"success": True, "total_sites": len(sites), "sites": sites}


def cleanup_wordpress_site(
    site_name, remove_volumes=True, remove_nginx=True, remove_db_entry=True
):
    """
    Complete cleanup of a WordPress site

    Args:
        site_name: Name of the site to cleanup
        remove_volumes: Remove Docker volumes (default: True)
        remove_nginx: Remove nginx configuration (default: True)
        remove_db_entry: Remove database entry (default: True)

    Returns:
        dict: Cleanup results
    """
    logger.info(f"Starting cleanup for WordPress site: {site_name}")

    results = {
        "success": True,
        "site_name": site_name,
        "steps_completed": [],
        "errors": [],
    }

    # Get site details from database
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, domain, docker_compose_path, container_name, mysql_container, cli_container
        FROM wordpress_sites
        WHERE site_name = ?
    """,
        (site_name,),
    )

    site = cursor.fetchone()

    if not site:
        conn.close()
        return {"success": False, "error": f"Site '{site_name}' not found in database"}

    site_id, domain, compose_path, wp_container, mysql_container, cli_container = site
    site_dir = os.path.dirname(compose_path) if compose_path else None

    try:
        # Step 1: Stop and remove Docker containers
        logger.info("Stopping Docker containers...")
        if site_dir and os.path.exists(site_dir):
            try:
                # Try docker-compose down
                down_cmd = ["docker-compose", "down"]
                if remove_volumes:
                    down_cmd.append("-v")

                subprocess.run(
                    down_cmd, cwd=site_dir, capture_output=True, text=True, timeout=30
                )
                results["steps_completed"].append("docker_compose_down")
                logger.info("✅ Docker compose down completed")
            except Exception as e:
                logger.warning(f"docker-compose down failed: {e}")
                results["errors"].append(f"docker-compose down: {str(e)}")

        # Step 2: Force remove individual containers if they still exist
        logger.info("Removing individual containers...")
        containers = [wp_container, mysql_container, cli_container]
        for container in containers:
            if container:
                try:
                    subprocess.run(
                        ["docker", "rm", "-f", container],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    logger.info(f"✅ Removed container: {container}")
                except Exception as e:
                    logger.debug(f"Could not remove {container}: {e}")

        results["steps_completed"].append("containers_removed")

        # Step 3: Remove Docker volumes if requested
        if remove_volumes:
            logger.info("Removing Docker volumes...")
            volume_prefix = site_name.replace("-", "").replace("_", "")
            try:
                # List volumes matching the site
                result = subprocess.run(
                    ["docker", "volume", "ls", "-q"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                volumes = result.stdout.strip().split("\n")
                for volume in volumes:
                    if site_name in volume or volume_prefix in volume:
                        try:
                            subprocess.run(
                                ["docker", "volume", "rm", "-f", volume],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            logger.info(f"✅ Removed volume: {volume}")
                        except Exception as e:
                            logger.debug(f"Could not remove volume {volume}: {e}")

                results["steps_completed"].append("volumes_removed")
            except Exception as e:
                logger.warning(f"Volume cleanup failed: {e}")
                results["errors"].append(f"volumes: {str(e)}")

        # Step 4: Remove nginx configuration
        if remove_nginx and domain:
            logger.info(f"Removing nginx configuration for {domain}...")
            try:
                remove_nginx_site(domain)
                reload_nginx()
                results["steps_completed"].append("nginx_removed")
                logger.info(f"✅ Nginx configuration removed for {domain}")
            except Exception as e:
                logger.warning(f"Nginx removal failed: {e}")
                results["errors"].append(f"nginx: {str(e)}")

        # Step 5: Remove site directory
        if site_dir and os.path.exists(site_dir):
            logger.info(f"Removing site directory: {site_dir}")
            try:
                shutil.rmtree(site_dir, ignore_errors=True)
                results["steps_completed"].append("directory_removed")
                logger.info(f"✅ Site directory removed")
            except Exception as e:
                logger.warning(f"Directory removal failed: {e}")
                results["errors"].append(f"directory: {str(e)}")

        # Step 6: Remove database entries
        if remove_db_entry:
            logger.info("Removing database entries...")
            try:
                # Remove from wordpress_sites
                cursor.execute("DELETE FROM wordpress_sites WHERE id = ?", (site_id,))

                # Remove related plugin entries
                cursor.execute(
                    "DELETE FROM wordpress_plugins WHERE site_id = ?", (site_id,)
                )

                # Remove CLI history
                cursor.execute(
                    "DELETE FROM wordpress_cli_history WHERE site_id = ?", (site_id,)
                )

                # Log the cleanup
                cursor.execute(
                    """
                    INSERT INTO deployment_logs (domain_name, action, status, message)
                    VALUES (?, 'wordpress_cleanup', 'success', ?)
                """,
                    (domain, f"Site {site_name} completely cleaned up"),
                )

                conn.commit()
                results["steps_completed"].append("database_cleaned")
                logger.info("✅ Database entries removed")
            except Exception as e:
                logger.error(f"Database cleanup failed: {e}")
                results["errors"].append(f"database: {str(e)}")

        conn.close()

        logger.info(f"✅ Cleanup complete for {site_name}")
        logger.info(f"   Steps completed: {len(results['steps_completed'])}")
        logger.info(f"   Errors: {len(results['errors'])}")

        return results

    except Exception as e:
        conn.close()
        logger.error(f"Cleanup failed for {site_name}: {e}")
        results["success"] = False
        results["errors"].append(str(e))
        return results


def cleanup_orphaned_containers():
    """
    Find and clean up Docker containers that are not in the database

    Returns:
        dict: Cleanup results
    """
    logger.info("Searching for orphaned Docker containers...")

    results = {
        "success": True,
        "orphaned_containers": [],
        "cleaned_containers": [],
        "errors": [],
    }

    try:
        # Get all WordPress/MySQL containers
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=_wordpress",
                "--filter",
                "name=_mysql",
                "--filter",
                "name=_cli",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        all_containers = (
            result.stdout.strip().split("\n") if result.stdout.strip() else []
        )

        # Get containers from database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT container_name, mysql_container, cli_container FROM wordpress_sites"
        )

        db_containers = set()
        for row in cursor.fetchall():
            db_containers.update([c for c in row if c])

        conn.close()

        # Find orphaned containers
        for container in all_containers:
            if container and container not in db_containers:
                results["orphaned_containers"].append(container)

                # Optionally remove orphaned containers
                try:
                    subprocess.run(
                        ["docker", "rm", "-f", container],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    results["cleaned_containers"].append(container)
                    logger.info(f"✅ Removed orphaned container: {container}")
                except Exception as e:
                    logger.warning(f"Could not remove {container}: {e}")
                    results["errors"].append(f"{container}: {str(e)}")

        logger.info(f"✅ Orphaned container cleanup complete")
        logger.info(f"   Found: {len(results['orphaned_containers'])}")
        logger.info(f"   Cleaned: {len(results['cleaned_containers'])}")

        return results

    except Exception as e:
        logger.error(f"Orphaned container cleanup failed: {e}")
        results["success"] = False
        results["errors"].append(str(e))
        return results


def get_docker_resources_usage():
    """
    Get Docker resources usage statistics

    Returns:
        dict: Resource usage information
    """
    logger.info("Getting Docker resource usage...")

    try:
        # Get container stats
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}:{{.Size}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        containers = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split(":")
                if len(parts) == 2:
                    containers.append({"name": parts[0], "size": parts[1]})

        # Get volume usage
        result = subprocess.run(
            ["docker", "system", "df", "-v", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        import json

        df_data = json.loads(result.stdout) if result.stdout else {}

        return {"success": True, "containers": containers, "system_df": df_data}

    except Exception as e:
        logger.error(f"Could not get Docker resource usage: {e}")
        return {"success": False, "error": str(e)}
