"""
WordPress Site Templates - Frontend Format
Formatted to match React frontend expectations
"""

TEMPLATES = {
    "ecommerce": {
        "id": "ecommerce",
        "name": "E-commerce Store",
        "description": "Full WooCommerce setup with payment gateways and shop pages",
        "theme": "Storefront",
        "plugin_count": 9,
        "theme_config": {"name": "storefront", "activate": True},
        "plugins": [
            {"name": "woocommerce", "version": "latest", "activate": True},
            {
                "name": "woocommerce-gateway-payfast",
                "version": "latest",
                "activate": True,
            },
            {
                "name": "woocommerce-gateway-stripe",
                "version": "latest",
                "activate": False,
            },
            {"name": "wordpress-seo", "version": "latest", "activate": True},
            {"name": "wp-fastest-cache", "version": "latest", "activate": True},
            {"name": "wordfence", "version": "latest", "activate": True},
            {"name": "contact-form-7", "version": "latest", "activate": True},
            {
                "name": "mailchimp-for-woocommerce",
                "version": "latest",
                "activate": False,
            },
            {
                "name": "woo-gutenberg-products-block",
                "version": "latest",
                "activate": True,
            },
        ],
        "settings": {
            "timezone": "Africa/Johannesburg",
            "date_format": "d/m/Y",
            "time_format": "H:i",
            "permalink_structure": "/%postname%/",
        },
        "pages": [
            {"title": "Shop", "slug": "shop", "type": "shop"},
            {"title": "Cart", "slug": "cart", "type": "cart"},
            {"title": "Checkout", "slug": "checkout", "type": "checkout"},
            {"title": "My Account", "slug": "my-account", "type": "myaccount"},
            {"title": "Terms & Conditions", "slug": "terms", "type": "page"},
            {"title": "Privacy Policy", "slug": "privacy-policy", "type": "page"},
            {"title": "Refund Policy", "slug": "refund-policy", "type": "page"},
        ],
        "woocommerce_setup": True,
    },
    "blog": {
        "id": "blog",
        "name": "Blog Site",
        "description": "Content-focused blog with SEO and social media tools",
        "theme": "Twenty Twenty-Four",
        "plugin_count": 6,
        "theme_config": {"name": "twentytwentyfour", "activate": True},
        "plugins": [
            {"name": "wordpress-seo", "version": "latest", "activate": True},
            {"name": "wp-fastest-cache", "version": "latest", "activate": True},
            {"name": "classic-editor", "version": "latest", "activate": True},
            {"name": "contact-form-7", "version": "latest", "activate": True},
            {"name": "social-warfare", "version": "latest", "activate": True},
            {"name": "wordfence", "version": "latest", "activate": True},
        ],
        "settings": {
            "timezone": "Africa/Johannesburg",
            "date_format": "d/m/Y",
            "time_format": "H:i",
            "permalink_structure": "/%year%/%monthnum%/%postname%/",
        },
        "pages": [
            {"title": "About", "slug": "about", "type": "page"},
            {"title": "Contact", "slug": "contact", "type": "page"},
            {"title": "Privacy Policy", "slug": "privacy-policy", "type": "page"},
        ],
    },
    "business": {
        "id": "business",
        "name": "Business Website",
        "description": "Corporate website with contact forms and service pages",
        "theme": "Astra",
        "plugin_count": 5,
        "theme_config": {"name": "astra", "activate": True},
        "plugins": [
            {"name": "contact-form-7", "version": "latest", "activate": True},
            {"name": "wordpress-seo", "version": "latest", "activate": True},
            {"name": "wp-fastest-cache", "version": "latest", "activate": True},
            {"name": "wordfence", "version": "latest", "activate": True},
            {
                "name": "google-analytics-for-wordpress",
                "version": "latest",
                "activate": True,
            },
        ],
        "settings": {
            "timezone": "Africa/Johannesburg",
            "date_format": "d/m/Y",
            "time_format": "H:i",
            "permalink_structure": "/%postname%/",
        },
        "pages": [
            {"title": "Services", "slug": "services", "type": "page"},
            {"title": "About Us", "slug": "about", "type": "page"},
            {"title": "Contact", "slug": "contact", "type": "page"},
            {"title": "Privacy Policy", "slug": "privacy-policy", "type": "page"},
        ],
    },
    "portfolio": {
        "id": "portfolio",
        "name": "Portfolio Site",
        "description": "Professional portfolio with gallery and contact form",
        "theme": "Twenty Twenty-Four",
        "plugin_count": 4,
        "theme_config": {"name": "twentytwentyfour", "activate": True},
        "plugins": [
            {"name": "elementor", "version": "latest", "activate": True},
            {"name": "contact-form-7", "version": "latest", "activate": True},
            {"name": "wordpress-seo", "version": "latest", "activate": True},
            {"name": "wordfence", "version": "latest", "activate": True},
        ],
        "settings": {
            "timezone": "Africa/Johannesburg",
            "date_format": "d/m/Y",
            "time_format": "H:i",
            "permalink_structure": "/%postname%/",
        },
        "pages": [
            {"title": "Portfolio", "slug": "portfolio", "type": "page"},
            {"title": "About", "slug": "about", "type": "page"},
            {"title": "Contact", "slug": "contact", "type": "page"},
        ],
    },
    "basic": {
        "id": "basic",
        "name": "Basic WordPress",
        "description": "Clean WordPress installation with essential plugins",
        "theme": "Twenty Twenty-Four",
        "plugin_count": 3,
        "theme_config": {"name": "twentytwentyfour", "activate": True},
        "plugins": [
            {"name": "classic-editor", "version": "latest", "activate": True},
            {"name": "contact-form-7", "version": "latest", "activate": True},
            {"name": "wordfence", "version": "latest", "activate": True},
        ],
        "settings": {
            "timezone": "Africa/Johannesburg",
            "date_format": "d/m/Y",
            "time_format": "H:i",
            "permalink_structure": "/%postname%/",
        },
        "pages": [],
    },
}


def get_template(template_id):
    """Get template configuration by ID"""
    return TEMPLATES.get(template_id, TEMPLATES["basic"])


def list_templates():
    """List all available templates in frontend format"""
    return {
        template_id: {
            "id": config["id"],
            "name": config["name"],
            "description": config["description"],
            "theme": config["theme"],
            "plugin_count": config["plugin_count"],
        }
        for template_id, config in TEMPLATES.items()
    }
