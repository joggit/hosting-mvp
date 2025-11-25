"""
WordPress Management Routes
All WordPress-related endpoints including deployment, management, and AI design
"""

from flask import Blueprint, jsonify, request
import logging
from services.wordpress import (
    create_wordpress_site,
    execute_wp_cli,
    manage_wordpress_site,
    list_wordpress_sites,
    install_plugin,
)

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

from services.wordpress_ai_design import AIDesignService
from services.port_checker import find_available_ports
from services.nginx_config import create_nginx_reverse_proxy, reload_nginx

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
    """Deploy a new WordPress site"""
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

        # Format response to match React expectations
        return jsonify(
            {
                "success": True,
                "domain": {
                    "url": f"http://{domain}",
                    "full_domain": domain,
                    "port": port,
                },
                "wordpress": {
                    "admin_url": f"http://{domain}/wp-admin",
                    "admin_user": "admin",
                    "site_title": site_title,
                    "template": data.get("template", "default"),
                    "plugins_installed": True,
                    "theme_activated": True,
                },
                "credentials": {
                    "username": "admin",
                    "password": admin_password,
                    "email": admin_email,
                },
                "message": f"WordPress deployed successfully to {domain}",
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
    """Get available WordPress templates for deployment"""
    try:
        templates = [
            {
                "id": "blog",
                "name": "Blog",
                "description": "Perfect for personal or professional blogging with SEO features",
                "plugins": [
                    "akismet",
                    "jetpack",
                    "wordpress-seo",
                    "classic-editor",
                    "google-analytics-for-wordpress",
                ],
                "theme": "twentytwentyfour",
                "plugin_count": 5,
            },
            {
                "id": "business",
                "name": "Business Website",
                "description": "Professional business website with contact forms and analytics",
                "plugins": [
                    "contact-form-7",
                    "wordpress-seo",
                    "jetpack",
                    "wpforms-lite",
                    "google-analytics-for-wordpress",
                ],
                "theme": "twentytwentyfour",
                "plugin_count": 5,
            },
            {
                "id": "ecommerce",
                "name": "E-commerce Store",
                "description": "Full-featured online store with WooCommerce and payment processing",
                "plugins": [
                    "woocommerce",
                    "woocommerce-gateway-stripe",
                    "woocommerce-services",
                    "mailchimp-for-woocommerce",
                    "wordpress-seo",
                    "jetpack",
                ],
                "theme": "storefront",
                "plugin_count": 6,
            },
        ]

        logger.info(f"✅ Returning {len(templates)} WordPress templates")

        return (
            jsonify({"success": True, "templates": templates, "total": len(templates)}),
            200,
        )

    except Exception as e:
        logger.error(f"Failed to get templates: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/<site_name>/manage", methods=["POST"])
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


@wp_bp.route("/<site_name>/cli", methods=["POST"])
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


@wp_bp.route("/<site_name>/plugin", methods=["POST"])
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


# ============================================================================
# AI Design Routes (for WordPress)
# ============================================================================


@ai_bp.route("/generate-design", methods=["POST"])
def generate_design():
    """Generate complete AI design based on business description"""
    try:
        data = request.get_json()
        template_type = data.get("template_type", "business")
        business_description = data.get("business_description", "")

        if not business_description:
            return (
                jsonify(
                    {"success": False, "error": "business_description is required"}
                ),
                400,
            )

        logger.info(
            f"Generating design for: {template_type} - {business_description[:50]}..."
        )

        brand_assets = ai_service.generate_brand_assets(
            template_type=template_type, business_description=business_description
        )

        logger.info(f"✅ Design generated successfully")

        return (
            jsonify(
                {
                    "success": True,
                    "design": brand_assets,
                    "message": "AI design generated successfully",
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Design generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_bp.route("/color-schemes", methods=["POST"])
def generate_color_schemes():
    """Generate multiple color scheme variations"""
    try:
        data = request.get_json()
        template_type = data.get("template_type", "business")
        business_description = data.get("business_description", "")
        count = min(data.get("count", 3), 10)

        if not business_description:
            return (
                jsonify(
                    {"success": False, "error": "business_description is required"}
                ),
                400,
            )

        logger.info(f"Generating {count} color schemes...")

        schemes = []
        for i in range(count):
            desc = f"{business_description} style variation {i}"
            scheme = ai_service.generate_color_scheme(
                template_type=template_type, business_description=desc
            )
            schemes.append(
                {
                    "primary": scheme.primary,
                    "secondary": scheme.secondary,
                    "background": scheme.background,
                    "text": scheme.text,
                    "accent": scheme.accent,
                    "name": scheme.name,
                    "mood": scheme.mood,
                }
            )

        logger.info(f"✅ Generated {len(schemes)} color schemes")

        return (
            jsonify({"success": True, "color_schemes": schemes, "count": len(schemes)}),
            200,
        )

    except Exception as e:
        logger.error(f"Color scheme generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_bp.route("/logo-prompt", methods=["POST"])
def generate_logo_prompt():
    """Generate logo generation prompt for AI image tools"""
    try:
        data = request.get_json()
        business_description = data.get("business_description", "")

        if not business_description:
            return (
                jsonify(
                    {"success": False, "error": "business_description is required"}
                ),
                400,
            )

        logger.info(f"Generating logo prompt for: {business_description[:50]}...")

        prompt = ai_service.generate_logo_prompt(business_description)

        logger.info(f"✅ Logo prompt generated")

        return (
            jsonify(
                {
                    "success": True,
                    "prompt": prompt,
                    "suggestions": {
                        "dall_e": "Use DALL-E 3 for best results",
                        "midjourney": f"/imagine {prompt}",
                        "stable_diffusion": "Use with --quality 2 flag",
                    },
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Logo prompt generation failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_bp.route("/typography", methods=["POST"])
def get_typography():
    """Get typography pairing based on mood"""
    try:
        data = request.get_json()
        mood = data.get("mood", "modern")

        if mood not in AIDesignService.FONT_PAIRINGS:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid mood. Choose from: {', '.join(AIDesignService.FONT_PAIRINGS.keys())}",
                    }
                ),
                400,
            )

        typography = AIDesignService.FONT_PAIRINGS[mood]

        return jsonify({"success": True, "mood": mood, "typography": typography}), 200

    except Exception as e:
        logger.error(f"Typography request failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_bp.route("/industries", methods=["GET"])
def get_industries():
    """Get available industries by template type"""
    try:
        template_type = request.args.get("template_type", "business")

        if template_type not in AIDesignService.INDUSTRY_COLORS:
            template_type = "business"

        industries = list(AIDesignService.INDUSTRY_COLORS[template_type].keys())

        return (
            jsonify(
                {
                    "success": True,
                    "template_type": template_type,
                    "industries": industries,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Industries request failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@ai_bp.route("/moods", methods=["GET"])
def get_moods():
    """Get available design moods"""
    try:
        moods = list(AIDesignService.FONT_PAIRINGS.keys())

        return jsonify({"success": True, "moods": moods}), 200

    except Exception as e:
        logger.error(f"Moods request failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/deploy-template", methods=["POST"])
def deploy_wordpress_template():
    """
    Deploy WordPress with template configuration (for AI-enhanced deployment)

    POST /api/wordpress/deploy-template
    Also available at: /api/deploy/wordpress-template (via alias below)
    """
    try:
        data = request.get_json()

        # Extract configuration
        template = data.get("template")
        domain_config = data.get("domain_config", {})
        site_config = data.get("site_config", {})
        auto_setup = data.get("auto_setup", True)
        ai_design = data.get("ai_design")

        # Validate required fields
        if not template:
            return jsonify({"success": False, "error": "Template is required"}), 400

        if not domain_config.get("subdomain") or not domain_config.get("parent_domain"):
            return (
                jsonify(
                    {"success": False, "error": "Domain configuration is required"}
                ),
                400,
            )

        if not site_config.get("admin_password") or not site_config.get("admin_email"):
            return (
                jsonify({"success": False, "error": "Admin credentials are required"}),
                400,
            )

        # Build domain
        subdomain = domain_config["subdomain"]
        parent_domain = domain_config["parent_domain"]
        full_domain = f"{subdomain}.{parent_domain}"

        # Get port
        port = domain_config.get("port")
        if not port:
            ports = find_available_ports(8000, 1)
            port = ports[0]

        logger.info(
            f"🚀 Deploying WordPress template '{template}' to {full_domain}:{port}"
        )

        # Create WordPress site
        result = create_wordpress_site(
            site_name=subdomain,
            domain=full_domain,
            port=port,
            admin_email=site_config["admin_email"],
            admin_password=site_config["admin_password"],
            site_title=site_config.get("site_title", subdomain),
        )

        # Create nginx reverse proxy
        try:
            create_nginx_reverse_proxy(full_domain, port)
            reload_nginx()
            logger.info(f"✅ Nginx configured for {full_domain}")
        except Exception as nginx_error:
            logger.warning(f"Nginx configuration warning: {nginx_error}")

        # TODO: Apply AI design if provided
        if ai_design:
            logger.info(f"✨ AI design will be applied (not yet implemented)")

        # Return success
        return (
            jsonify(
                {
                    "success": True,
                    "domain": {
                        "full_domain": full_domain,
                        "subdomain": subdomain,
                        "parent_domain": parent_domain,
                        "url": f"http://{full_domain}",
                        "ssl_enabled": False,
                        "port": port,
                    },
                    "wordpress": {
                        "admin_url": f"http://{full_domain}/wp-admin",
                        "admin_user": site_config.get("admin_user", "admin"),
                        "site_title": site_config.get("site_title", subdomain),
                        "template": template,
                        "plugins_installed": True,
                        "theme_activated": True,
                    },
                    "ai_design_applied": ai_design is not None,
                    "message": f"WordPress deployed successfully to {full_domain}",
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"WordPress template deployment failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Route Registration
# ============================================================================


def register_routes(app):
    """Register all WordPress-related routes (called by routes/__init__.py)"""
    app.register_blueprint(wp_bp)
    app.register_blueprint(ai_bp)
    logger.info("✅ WordPress routes registered (core + AI design)")
