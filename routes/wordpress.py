"""
WordPress management endpoints
"""

from flask import jsonify, request
import logging
from services.wordpress import (
    create_wordpress_site,
    execute_wp_cli,
    manage_wordpress_site,
    list_wordpress_sites,
    install_plugin,
)
from services.port_checker import find_available_ports
from services.nginx_config import create_nginx_reverse_proxy, reload_nginx

logger = logging.getLogger(__name__)


def register_routes(app):
    """Register WordPress-related routes"""

    @app.route("/api/wordpress/deploy", methods=["POST"])
    def deploy_wordpress():
        """Deploy a new WordPress site"""
        try:
            data = request.get_json()

            # Validate required fields
            required = ["name", "domain", "adminEmail", "adminPassword"]
            for field in required:
                if field not in data:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Missing required field: {field}",
                            }
                        ),
                        400,
                    )

            site_name = data["name"]
            domain = data["domain"]
            admin_email = data["adminEmail"]
            admin_password = data["adminPassword"]
            site_title = data.get("siteTitle", site_name)

            # Get port
            port = data.get("port")
            if not port:
                ports = find_available_ports(8000, 1)
                port = ports[0]

            logger.info(f"Deploying WordPress: {site_name} on {domain}:{port}")

            # Create WordPress site
            result = create_wordpress_site(
                site_name=site_name,
                domain=domain,
                port=port,
                admin_email=admin_email,
                admin_password=admin_password,
                site_title=site_title,
            )

            # Create nginx reverse proxy
            try:
                create_nginx_reverse_proxy(domain, port)
                reload_nginx()
                logger.info(f"✅ Nginx configured for {domain}")
            except Exception as nginx_error:
                logger.warning(f"Nginx configuration warning: {nginx_error}")

            return jsonify(
                {
                    "success": True,
                    **result,
                    "credentials": {
                        "username": "admin",
                        "password": admin_password,
                        "email": admin_email,
                    },
                }
            )

        except Exception as e:
            logger.error(f"WordPress deployment failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/wordpress/sites", methods=["GET"])
    def get_wordpress_sites():
        """List all WordPress sites"""
        try:
            sites = list_wordpress_sites()
            return jsonify({"success": True, "sites": sites})
        except Exception as e:
            logger.error(f"Failed to list WordPress sites: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/wordpress/<site_name>/manage", methods=["POST"])
    def manage_site(site_name):
        """Manage WordPress site (start, stop, restart, delete)"""
        try:
            data = request.get_json()
            action = data.get("action")

            if action not in ["start", "stop", "restart", "delete"]:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Invalid action. Must be: start, stop, restart, or delete",
                        }
                    ),
                    400,
                )

            result = manage_wordpress_site(site_name, action)
            return jsonify({"success": True, **result})

        except Exception as e:
            logger.error(f"Site management failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/wordpress/<site_name>/cli", methods=["POST"])
    def execute_cli(site_name):
        """Execute WP-CLI command"""
        try:
            data = request.get_json()
            command = data.get("command")

            if not command:
                return jsonify({"success": False, "error": "Missing command"}), 400

            result = execute_wp_cli(site_name, command)
            return jsonify(result)

        except Exception as e:
            logger.error(f"WP-CLI execution failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/wordpress/<site_name>/plugin", methods=["POST"])
    def install_wp_plugin(site_name):
        """Install WordPress plugin"""
        try:
            data = request.get_json()
            plugin_name = data.get("plugin")
            activate = data.get("activate", True)

            if not plugin_name:
                return jsonify({"success": False, "error": "Missing plugin name"}), 400

            result = install_plugin(site_name, plugin_name, activate)
            return jsonify(result)

        except Exception as e:
            logger.error(f"Plugin installation failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
