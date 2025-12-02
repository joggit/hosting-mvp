"""
WordPress Management Routes - Traditional Deployment Only
No Docker dependencies - Pure Nginx + PHP-FPM + MySQL
"""

import os
from pathlib import Path
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
    """Get available WordPress templates for deployment"""
    try:
        templates = [
            {
                "id": "blog",
                "name": "Blog",
                "description": "Perfect for personal or professional blogging with SEO features",
                "plugins": [
                    "akismet",
                    "wordpress-seo",
                    "classic-editor",
                    "google-analytics-for-wordpress",
                ],
                "theme": "twentytwentyfour",
                "plugin_count": 4,
            },
            {
                "id": "business",
                "name": "Business Website",
                "description": "Professional business website with contact forms and analytics",
                "plugins": [
                    "contact-form-7",
                    "wordpress-seo",
                    "wpforms-lite",
                    "google-analytics-for-wordpress",
                ],
                "theme": "twentytwentyfour",
                "plugin_count": 4,
            },
            {
                "id": "ecommerce",
                "name": "E-commerce Store",
                "description": "Full-featured online store with WooCommerce",
                "plugins": [
                    "woocommerce",
                    "wordpress-seo",
                ],
                "theme": "storefront",
                "plugin_count": 2,
            },
            {
                "id": "portfolio",
                "name": "Portfolio",
                "description": "Showcase your work with a beautiful portfolio site",
                "plugins": [
                    "envira-gallery-lite",
                    "wordpress-seo",
                ],
                "theme": "twentytwentyfour",
                "plugin_count": 2,
            },
            {
                "id": "news",
                "name": "News/Magazine",
                "description": "News site with magazine layout and social sharing",
                "plugins": [
                    "wordpress-seo",
                    "social-warfare",
                    "google-analytics-for-wordpress",
                ],
                "theme": "newspaper",
                "plugin_count": 3,
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
    """Manage WordPress site (restart or delete)"""
    try:
        data = request.get_json()
        action = data.get("action")

        if action not in ["restart", "delete"]:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Invalid action. Must be: restart or delete",
                    }
                ),
                400,
            )

        result = manage_wordpress_site(site_name, action)
        return jsonify(result)

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


@wp_bp.route("/deploy-template", methods=["POST"])
def deploy_wordpress_template():
    """Deploy WordPress with template configuration"""
    try:
        data = request.get_json()

        # Extract configuration
        template = data.get("template")
        domain_config = data.get("domain_config", {})
        site_config = data.get("site_config", {})
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

        logger.info(f"🚀 Deploying WordPress template '{template}' to {full_domain}")

        # Create WordPress site
        result = create_wordpress_site(
            site_name=subdomain,
            domain=full_domain,
            admin_email=site_config["admin_email"],
            admin_password=site_config["admin_password"],
            site_title=site_config.get("site_title", subdomain),
        )

        # TODO: Apply template-specific configurations
        # (Install plugins, set theme, configure settings)
        if template == "ecommerce":
            # Setup WooCommerce for ecommerce template
            wc_config = {
                "store_country": "ZA:WC",
                "currency": "ZAR",
            }
            setup_woocommerce(subdomain, wc_config)

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
                    },
                    "wordpress": {
                        "admin_url": f"http://{full_domain}/wp-admin",
                        "admin_user": site_config.get("admin_user", "admin"),
                        "site_title": site_config.get("site_title", subdomain),
                        "template": template,
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
# WooCommerce Routes
# ============================================================================


@wp_bp.route("/deploy-woocommerce", methods=["POST"])
def deploy_woocommerce_site():
    """Deploy a complete WooCommerce site"""
    try:
        data = request.get_json()

        # Validate required fields
        required = ["name", "domain", "adminEmail", "adminPassword"]
        for field in required:
            if field not in data:
                return jsonify({"success": False, "error": f"Missing: {field}"}), 400

        site_name = data["name"]
        domain = data["domain"]
        admin_email = data["adminEmail"]
        admin_password = data["adminPassword"]
        site_title = data.get("siteTitle", f"{site_name} Shop")

        logger.info(f"🛒 Deploying WooCommerce: {site_name} on {domain}")

        # Step 1: Deploy WordPress
        logger.info("Step 1: Deploying WordPress...")
        create_wordpress_site(
            site_name=site_name,
            domain=domain,
            admin_email=admin_email,
            admin_password=admin_password,
            site_title=site_title,
        )

        # Step 2: Setup WooCommerce
        logger.info("Step 2: Setting up WooCommerce...")
        store_config = data.get("store", {})
        wc_config = {
            "store_address": store_config.get("store_address"),
            "store_city": store_config.get("store_city"),
            "store_postcode": store_config.get("store_postcode"),
            "store_country": store_config.get("store_country", "ZA:WC"),
            "currency": store_config.get("currency", "ZAR"),
        }

        wc_result = setup_woocommerce(site_name, wc_config)

        # Step 3: Create sample products if requested
        if store_config.get("create_sample_products", False):
            logger.info("Step 3: Creating sample products...")
            product_count = store_config.get("sample_product_count", 5)
            products_result = create_sample_products(site_name, product_count)
            wc_result["sample_products"] = products_result

        # Return response
        return (
            jsonify(
                {
                    "success": True,
                    "message": "WooCommerce site deployed successfully",
                    "domain": {
                        "url": f"http://{domain}",
                        "full_domain": domain,
                    },
                    "wordpress": {
                        "admin_url": f"http://{domain}/wp-admin",
                        "admin_user": "admin",
                        "site_title": site_title,
                    },
                    "woocommerce": {
                        "shop_url": f"http://{domain}/shop",
                        "setup_complete": wc_result["success"],
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


@wp_bp.route("/<site_name>/woocommerce/setup", methods=["POST"])
def setup_site_woocommerce(site_name):
    """Setup WooCommerce on existing WordPress site"""
    try:
        data = request.get_json()

        store_config = data.get("store_config", {})
        result = setup_woocommerce(site_name, store_config)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"WooCommerce setup failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/<site_name>/woocommerce/products/create-sample", methods=["POST"])
def create_woocommerce_sample_products(site_name):
    """Create sample WooCommerce products"""
    try:
        data = request.get_json()
        count = data.get("count", 5)

        result = create_sample_products(site_name, count)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Failed to create sample products: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/<site_name>/woocommerce/info", methods=["GET"])
def get_woocommerce_info(site_name):
    """Get WooCommerce store information"""
    try:
        result = get_store_info(site_name)
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Failed to get WooCommerce info: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Cleanup Routes
# ============================================================================


@wp_bp.route("/<site_name>/cleanup", methods=["DELETE", "POST"])
def cleanup_site(site_name):
    """Complete cleanup of a WordPress site"""
    try:
        logger.info(f"🧹 Cleaning up: {site_name}")

        result = cleanup_wordpress_site(site_name)

        return (
            jsonify(
                {
                    "success": True,
                    "message": f"Site {site_name} cleaned up",
                    "result": result,
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/cleanup/list", methods=["GET"])
def list_cleanup_sites():
    """List all WordPress sites that can be cleaned up"""
    try:
        sites = list_wordpress_sites()

        # Add cleanup info to each site
        for site in sites:
            site["can_cleanup"] = True
            site["cleanup_warning"] = (
                "This will delete the site, database, and all files"
            )

        return jsonify({"success": True, "sites": sites, "total": len(sites)}), 200

    except Exception as e:
        logger.error(f"Failed to list cleanup sites: {e}")
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


# ============================================================================
# Site Health & Status Routes
# ============================================================================


@wp_bp.route("/<site_name>/health", methods=["GET"])
def get_site_health(site_name):
    """Get health status of a WordPress site"""
    try:
        from pathlib import Path

        site_dir = Path(f"/var/www/wordpress/{site_name}")

        if not site_dir.exists():
            return (
                jsonify(
                    {"success": False, "error": f"Site directory not found: {site_dir}"}
                ),
                404,
            )

        # Check if WordPress files exist
        required_files = ["wp-config.php", "index.php", "wp-login.php"]
        missing_files = []

        for file in required_files:
            if not (site_dir / file).exists():
                missing_files.append(file)

        # Check if PHP-FPM pool exists
        php_pool = Path(f"/etc/php/8.3/fpm/pool.d/{site_name}.conf")

        # Check if Nginx config exists
        nginx_config = Path(f"/etc/nginx/sites-available/{site_name}.conf")

        health_status = {
            "site_exists": site_dir.exists(),
            "wordpress_files_complete": len(missing_files) == 0,
            "missing_files": missing_files,
            "php_fpm_pool_exists": php_pool.exists(),
            "nginx_config_exists": nginx_config.exists(),
            "directory_size": sum(
                f.stat().st_size for f in site_dir.rglob("*") if f.is_file()
            ),
            "file_count": sum(1 for _ in site_dir.rglob("*") if _.is_file()),
        }

        # Overall status
        if (
            health_status["site_exists"]
            and health_status["wordpress_files_complete"]
            and health_status["php_fpm_pool_exists"]
            and health_status["nginx_config_exists"]
        ):
            health_status["overall"] = "healthy"
        else:
            health_status["overall"] = "unhealthy"

        return (
            jsonify({"success": True, "site_name": site_name, "health": health_status}),
            200,
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/<site_name>/status", methods=["GET"])
def get_site_status(site_name):
    """Get detailed status of a WordPress site"""
    try:
        from pathlib import Path
        import datetime

        site_dir = Path(f"/var/www/wordpress/{site_name}")

        if not site_dir.exists():
            return (
                jsonify({"success": False, "error": f"Site not found: {site_name}"}),
                404,
            )

        # Get basic info
        stat = site_dir.stat()
        created = datetime.datetime.fromtimestamp(stat.st_ctime)
        modified = datetime.datetime.fromtimestamp(stat.st_mtime)

        # Get WordPress version if possible
        version = "Unknown"
        version_file = site_dir / "wp-includes" / "version.php"
        if version_file.exists():
            try:
                content = version_file.read_text()
                import re

                match = re.search(r"\$wp_version\s*=\s*'([^']+)'", content)
                if match:
                    version = match.group(1)
            except:
                pass

        status = {
            "site_name": site_name,
            "directory": str(site_dir),
            "exists": site_dir.exists(),
            "created": created.isoformat(),
            "last_modified": modified.isoformat(),
            "wordpress_version": version,
            "directory_size_mb": round(stat.st_size / (1024 * 1024), 2),
        }

        return jsonify({"success": True, "status": status}), 200

    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Permission & System Check Routes
# ============================================================================


@wp_bp.route("/permissions/check", methods=["GET"])
def check_permissions():
    """Check if system has proper permissions for WordPress deployment"""
    try:
        result = ensure_permissions()

        return (
            jsonify(
                {
                    "success": True,
                    "permissions_ok": result,
                    "message": (
                        "Permissions check completed"
                        if result
                        else "Permission issues found"
                    ),
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"Permission check failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@wp_bp.route("/system/requirements", methods=["GET"])
def check_system_requirements():
    """Check system requirements for WordPress deployment"""
    try:
        import shutil

        requirements = {
            "php_installed": shutil.which("php") is not None,
            "php_fpm_running": False,
            "nginx_installed": shutil.which("nginx") is not None,
            "nginx_running": False,
            "mysql_installed": shutil.which("mysql") is not None,
            "mysql_running": False,
            "wp_cli_installed": shutil.which("wp") is not None,
            "wordpress_directory_exists": Path("/var/www/wordpress").exists(),
            "wordpress_directory_writable": os.access("/var/www/wordpress", os.W_OK),
        }

        # Check services
        try:
            import subprocess

            # Check PHP-FPM
            php_result = subprocess.run(
                ["systemctl", "is-active", "php8.3-fpm"], capture_output=True, text=True
            )
            requirements["php_fpm_running"] = php_result.returncode == 0

            # Check Nginx
            nginx_result = subprocess.run(
                ["systemctl", "is-active", "nginx"], capture_output=True, text=True
            )
            requirements["nginx_running"] = nginx_result.returncode == 0

            # Check MySQL
            mysql_result = subprocess.run(
                ["systemctl", "is-active", "mysql"], capture_output=True, text=True
            )
            requirements["mysql_running"] = mysql_result.returncode == 0

        except Exception as e:
            logger.warning(f"Service check failed: {e}")

        # Count satisfied requirements
        satisfied = sum(1 for req in requirements.values() if req)
        total = len(requirements)

        return (
            jsonify(
                {
                    "success": True,
                    "requirements": requirements,
                    "summary": {
                        "satisfied": satisfied,
                        "total": total,
                        "percentage": round((satisfied / total) * 100, 1),
                    },
                }
            ),
            200,
        )

    except Exception as e:
        logger.error(f"System requirements check failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Route Registration
# ============================================================================


def register_routes(app):
    """Register all WordPress-related routes"""
    app.register_blueprint(wp_bp)
    app.register_blueprint(ai_bp)
    logger.info("✅ WordPress routes registered (traditional deployment only)")
