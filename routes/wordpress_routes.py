"""
WordPress Management Routes - Traditional Deployment Only
No Docker dependencies
"""

from flask import Blueprint, jsonify, request
import logging
from services.wordpress import (
    create_wordpress_site,
    execute_wp_cli,
    manage_wordpress_site,
    list_wordpress_sites,
    install_plugin,
    setup_woocommerce,
    create_sample_products,
    get_store_info,
    cleanup_wordpress_site,
    ensure_permissions,
)

from services.wordpress_ai_design import AIDesignService
from services.port_checker import find_available_ports

logger = logging.getLogger(__name__)

# Create blueprints
wp_bp = Blueprint("wordpress", __name__, url_prefix="/api/wordpress")
ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")

# Initialize AI service
ai_service = AIDesignService()


# ============================================================================
# WordPress Core Routes
# ============================================================================


@wp_bp.route("/deploy", methods=["POST"])
def deploy_wordpress():
    """Deploy a new WordPress site (Traditional - No Docker)"""
    try:
        data = request.get_json()

        # Validate required fields
        required = ["name", "domain", "adminEmail", "adminPassword"]
        for field in required:
            if field not in data:
                return (
                    jsonify(
                        {"success": False, "error": f"Missing required field: {field}"}
                    ),
                    400,
                )

        site_name = data["name"]
        domain = data["domain"]
        admin_email = data["adminEmail"]
        admin_password = data["adminPassword"]
        site_title = data.get("siteTitle", site_name)

        logger.info(f"Deploying WordPress: {site_name} on {domain}")

        # Check permissions
        if not ensure_permissions():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Permission check failed. Ensure 'deploy' user is in 'www-data' group.",
                    }
                ),
                500,
            )

        # Create WordPress site (Traditional - no port needed)
        result = create_wordpress_site(
            site_name=site_name,
            domain=domain,
            admin_email=admin_email,
            admin_password=admin_password,
            site_title=site_title,
        )

        # Format response
        return jsonify(
            {
                "success": True,
                "message": f"WordPress deployed successfully to {domain}",
                "domain": {
                    "url": f"http://{domain}",
                    "full_domain": domain,
                },
                "wordpress": {
                    "admin_url": f"http://{domain}/wp-admin",
                    "admin_user": "admin",
                    "site_title": site_title,
                    "template": data.get("template", "default"),
                },
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


@wp_bp.route("/sites", methods=["GET"])
def get_wordpress_sites():
    """List all WordPress sites"""
    try:
        sites = list_wordpress_sites()
        return jsonify({"success": True, "sites": sites})
    except Exception as e:
        logger.error(f"Failed to list WordPress sites: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/templates", methods=["GET"])
def get_wordpress_templates():
    """Get available WordPress templates"""
    try:
        templates = [
            {
                "id": "blog",
                "name": "Blog",
                "description": "Perfect for personal or professional blogging",
                "plugins": ["akismet", "wordpress-seo", "classic-editor"],
                "theme": "twentytwentyfour",
            },
            {
                "id": "business",
                "name": "Business Website",
                "description": "Professional business website",
                "plugins": ["contact-form-7", "wordpress-seo", "wpforms-lite"],
                "theme": "twentytwentyfour",
            },
            {
                "id": "ecommerce",
                "name": "E-commerce Store",
                "description": "Online store with WooCommerce",
                "plugins": ["woocommerce", "wordpress-seo"],
                "theme": "storefront",
            },
        ]

        return jsonify({"success": True, "templates": templates}), 200

    except Exception as e:
        logger.error(f"Failed to get templates: {e}")
        return jsonify
