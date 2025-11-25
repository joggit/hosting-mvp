"""
WordPress Routes - Extended with WooCommerce and Cleanup
Add these routes to your routes/wordpress_routes.py file
"""

from flask import Blueprint, request, jsonify
import logging

# Import the new services
from services.woocommerce import (
    setup_woocommerce,
    create_sample_products,
    get_store_info,
)
from services.cleanup import (
    list_sites_for_cleanup,
    cleanup_wordpress_site,
    cleanup_orphaned_containers,
    get_docker_resources_usage,
)

logger = logging.getLogger(__name__)

# Add to existing wordpress blueprint
wp_bp = Blueprint("wordpress", __name__, url_prefix="/api/wordpress")


# ============================================================================
# WooCommerce Routes
# ============================================================================


@wp_bp.route("/<site_name>/woocommerce/setup", methods=["POST"])
def setup_site_woocommerce(site_name):
    """
    Setup WooCommerce on a WordPress site

    POST /api/wordpress/<site_name>/woocommerce/setup

    Body:
    {
        "store_name": "My Store",
        "store_address": "123 Main St",
        "store_city": "Johannesburg",
        "store_postcode": "2000",
        "store_country": "ZA",
        "currency": "ZAR",
        "products_per_page": 12,
        "install_storefront": true,
        "install_plugins": ["woocommerce-gateway-payfast"],
        "create_sample_products": true,
        "sample_product_count": 5
    }
    """
    try:
        data = request.get_json() or {}

        logger.info(f"Setting up WooCommerce for {site_name}")

        # Setup WooCommerce
        config = {
            "store_name": data.get("store_name"),
            "store_address": data.get("store_address"),
            "store_city": data.get("store_city"),
            "store_postcode": data.get("store_postcode"),
            "store_country": data.get("store_country", "ZA"),
            "currency": data.get("currency", "ZAR"),
            "products_per_page": data.get("products_per_page", 12),
            "install_storefront": data.get("install_storefront", True),
            "install_plugins": data.get("install_plugins", []),
        }

        result = setup_woocommerce(site_name, config)

        # Create sample products if requested
        if data.get("create_sample_products", False):
            sample_count = data.get("sample_product_count", 5)
            product_result = create_sample_products(site_name, sample_count)
            result["sample_products"] = product_result

        if result["success"]:
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"WooCommerce setup complete for {site_name}",
                        "result": result,
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "WooCommerce setup had errors",
                        "result": result,
                    }
                ),
                500,
            )

    except Exception as e:
        logger.error(f"WooCommerce setup failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/<site_name>/woocommerce/info", methods=["GET"])
def get_site_woocommerce_info(site_name):
    """
    Get WooCommerce information for a site

    GET /api/wordpress/<site_name>/woocommerce/info
    """
    try:
        result = get_store_info(site_name)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Failed to get WooCommerce info: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/<site_name>/woocommerce/products/sample", methods=["POST"])
def create_site_sample_products(site_name):
    """
    Create sample products for a WooCommerce site

    POST /api/wordpress/<site_name>/woocommerce/products/sample

    Body:
    {
        "count": 5
    }
    """
    try:
        data = request.get_json() or {}
        count = data.get("count", 5)

        result = create_sample_products(site_name, count)

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Created {result['products_created']} sample products",
                    "result": result,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Failed to create sample products: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Cleanup Routes
# ============================================================================


@wp_bp.route("/cleanup/list", methods=["GET"])
def list_cleanup_sites():
    """
    List all WordPress sites with cleanup information

    GET /api/wordpress/cleanup/list
    """
    try:
        result = list_sites_for_cleanup()
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Failed to list sites for cleanup: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/<site_name>/cleanup", methods=["POST", "DELETE"])
def cleanup_site(site_name):
    """
    Complete cleanup of a WordPress site

    POST/DELETE /api/wordpress/<site_name>/cleanup

    Body (optional):
    {
        "remove_volumes": true,
        "remove_nginx": true,
        "remove_db_entry": true
    }
    """
    try:
        data = request.get_json() or {}

        remove_volumes = data.get("remove_volumes", True)
        remove_nginx = data.get("remove_nginx", True)
        remove_db_entry = data.get("remove_db_entry", True)

        logger.info(f"Cleaning up WordPress site: {site_name}")

        result = cleanup_wordpress_site(
            site_name,
            remove_volumes=remove_volumes,
            remove_nginx=remove_nginx,
            remove_db_entry=remove_db_entry,
        )

        if result["success"]:
            return (
                jsonify(
                    {
                        "success": True,
                        "message": f"Site {site_name} cleaned up successfully",
                        "result": result,
                    }
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Cleanup completed with errors",
                        "result": result,
                    }
                ),
                200,
            )  # Still return 200 as partial cleanup succeeded

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/cleanup/orphaned", methods=["POST"])
def cleanup_orphaned():
    """
    Find and cleanup orphaned Docker containers

    POST /api/wordpress/cleanup/orphaned
    """
    try:
        logger.info("Starting orphaned container cleanup...")

        result = cleanup_orphaned_containers()

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Cleaned up {len(result['cleaned_containers'])} orphaned containers",
                    "result": result,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Orphaned cleanup failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/cleanup/resources", methods=["GET"])
def get_resources():
    """
    Get Docker resources usage

    GET /api/wordpress/cleanup/resources
    """
    try:
        result = get_docker_resources_usage()
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Failed to get resources: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Combined WooCommerce Deployment Route
# ============================================================================


@wp_bp.route("/deploy-woocommerce", methods=["POST"])
def deploy_woocommerce_site():
    """
    Deploy a complete WooCommerce site in one request

    POST /api/wordpress/deploy-woocommerce

    Body:
    {
        "name": "myshop",
        "domain": "myshop.example.com",
        "adminEmail": "admin@example.com",
        "adminPassword": "secure_password",
        "siteTitle": "My Online Shop",
        "store": {
            "store_address": "123 Main St",
            "store_city": "Johannesburg",
            "store_postcode": "2000",
            "store_country": "ZA",
            "currency": "ZAR",
            "create_sample_products": true
        }
    }
    """
    try:
        data = request.get_json()

        # Import from existing wordpress routes
        from services.wordpress import create_wordpress_site
        from services.nginx_config import create_nginx_reverse_proxy, reload_nginx
        from utils.ports import find_available_ports

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
        site_title = data.get("siteTitle", f"{site_name} Shop")

        # Get port
        port = data.get("port")
        if not port:
            ports = find_available_ports(8000, 1)
            port = ports[0]

        logger.info(f"Deploying WooCommerce site: {site_name} on {domain}:{port}")

        # Step 1: Deploy WordPress
        logger.info("Step 1: Deploying WordPress...")
        wp_result = create_wordpress_site(
            site_name=site_name,
            domain=domain,
            port=port,
            admin_email=admin_email,
            admin_password=admin_password,
            site_title=site_title,
        )

        # Step 2: Setup nginx
        logger.info("Step 2: Configuring nginx...")
        try:
            create_nginx_reverse_proxy(domain, port)
            reload_nginx()
        except Exception as e:
            logger.warning(f"Nginx configuration warning: {e}")

        # Step 3: Setup WooCommerce
        logger.info("Step 3: Setting up WooCommerce...")
        store_config = data.get("store", {})
        wc_config = {
            "store_address": store_config.get("store_address"),
            "store_city": store_config.get("store_city"),
            "store_postcode": store_config.get("store_postcode"),
            "store_country": store_config.get("store_country", "ZA"),
            "currency": store_config.get("currency", "ZAR"),
            "products_per_page": store_config.get("products_per_page", 12),
            "install_storefront": store_config.get("install_storefront", True),
            "install_plugins": store_config.get("install_plugins", []),
        }

        wc_result = setup_woocommerce(site_name, wc_config)

        # Step 4: Create sample products if requested
        if store_config.get("create_sample_products", False):
            logger.info("Step 4: Creating sample products...")
            product_count = store_config.get("sample_product_count", 5)
            products_result = create_sample_products(site_name, product_count)
            wc_result["sample_products"] = products_result

        # Format response
        return (
            jsonify(
                {
                    "success": True,
                    "message": f"WooCommerce site deployed successfully",
                    "domain": {
                        "url": f"http://{domain}",
                        "full_domain": domain,
                        "port": port,
                    },
                    "wordpress": {
                        "admin_url": f"http://{domain}/wp-admin",
                        "admin_user": "admin",
                        "site_title": site_title,
                    },
                    "woocommerce": {
                        "shop_url": f"http://{domain}/shop",
                        "setup_complete": wc_result["success"],
                        "steps_completed": wc_result.get("steps_completed", []),
                    },
                    "credentials": {
                        "username": "admin",
                        "password": admin_password,
                        "email": admin_email,
                    },
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"WooCommerce deployment failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
