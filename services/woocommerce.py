"""
WooCommerce Setup Service
Handles WooCommerce installation and configuration for WordPress sites
"""

import logging
from services.wordpress import execute_wp_cli

logger = logging.getLogger(__name__)


def setup_woocommerce(site_name, config=None):
    """
    Install and configure WooCommerce on a WordPress site

    Args:
        site_name: Name of the WordPress site
        config: Optional configuration dict with:
            - store_name: Store name
            - store_address: Store address
            - store_city: City
            - store_postcode: Postal code
            - store_country: Country code (e.g., 'ZA')
            - currency: Currency code (e.g., 'ZAR')
            - products_per_page: Number of products per page
            - install_storefront: Install Storefront theme (default: True)
            - install_plugins: List of additional plugins to install

    Returns:
        dict: Installation results
    """
    logger.info(f"Setting up WooCommerce for {site_name}")

    config = config or {}
    results = {"success": True, "steps_completed": [], "errors": []}

    try:
        # Step 1: Install WooCommerce plugin
        logger.info("Installing WooCommerce plugin...")
        result = execute_wp_cli(site_name, "plugin install woocommerce --activate")
        if result["success"]:
            results["steps_completed"].append("woocommerce_installed")
            logger.info("✅ WooCommerce installed")
        else:
            raise Exception(f"Failed to install WooCommerce: {result['error']}")

        # Step 2: Install Storefront theme (WooCommerce official theme)
        if config.get("install_storefront", True):
            logger.info("Installing Storefront theme...")
            result = execute_wp_cli(site_name, "theme install storefront --activate")
            if result["success"]:
                results["steps_completed"].append("storefront_installed")
                logger.info("✅ Storefront theme installed")

        # Step 3: Create WooCommerce pages (shop, cart, checkout, account)
        logger.info("Creating WooCommerce pages...")
        result = execute_wp_cli(site_name, "wc tool run install_pages --user=admin")
        if result["success"]:
            results["steps_completed"].append("pages_created")
            logger.info("✅ WooCommerce pages created")

        # Step 4: Configure store settings
        logger.info("Configuring store settings...")

        # Set store address
        if config.get("store_address"):
            execute_wp_cli(
                site_name,
                f"option update woocommerce_store_address '{config['store_address']}'",
            )

        if config.get("store_city"):
            execute_wp_cli(
                site_name,
                f"option update woocommerce_store_city '{config['store_city']}'",
            )

        if config.get("store_postcode"):
            execute_wp_cli(
                site_name,
                f"option update woocommerce_store_postcode '{config['store_postcode']}'",
            )

        if config.get("store_country"):
            execute_wp_cli(
                site_name,
                f"option update woocommerce_default_country '{config['store_country']}'",
            )

        # Set currency
        currency = config.get("currency", "ZAR")
        execute_wp_cli(site_name, f"option update woocommerce_currency '{currency}'")

        # Set products per page
        products_per_page = config.get("products_per_page", 12)
        execute_wp_cli(
            site_name, f"option update woocommerce_catalog_rows {products_per_page}"
        )

        results["steps_completed"].append("settings_configured")
        logger.info("✅ Store settings configured")

        # Step 5: Install additional plugins if specified
        additional_plugins = config.get("install_plugins", [])
        for plugin in additional_plugins:
            logger.info(f"Installing plugin: {plugin}")
            result = execute_wp_cli(site_name, f"plugin install {plugin} --activate")
            if result["success"]:
                results["steps_completed"].append(f"plugin_{plugin}_installed")

        # Step 6: Set up payment gateways (enable Cash on Delivery by default)
        logger.info("Enabling Cash on Delivery payment...")
        execute_wp_cli(
            site_name,
            'option update woocommerce_cod_settings \'{"enabled":"yes","title":"Cash on Delivery"}\'',
        )
        results["steps_completed"].append("payment_gateway_configured")

        # Step 7: Skip WooCommerce setup wizard
        execute_wp_cli(site_name, "option update woocommerce_onboarding_opt_in 'no'")
        execute_wp_cli(site_name, "option update woocommerce_task_list_complete 'yes'")

        logger.info("✅ WooCommerce setup complete!")

        return results

    except Exception as e:
        logger.error(f"WooCommerce setup failed: {e}")
        results["success"] = False
        results["errors"].append(str(e))
        return results


def create_sample_products(site_name, count=5):
    """
    Create sample products for testing

    Args:
        site_name: Name of the WordPress site
        count: Number of sample products to create

    Returns:
        dict: Creation results
    """
    logger.info(f"Creating {count} sample products for {site_name}")

    sample_products = [
        {
            "name": "Premium T-Shirt",
            "price": "299.99",
            "description": "High-quality cotton t-shirt",
            "category": "Clothing",
        },
        {
            "name": "Classic Jeans",
            "price": "799.99",
            "description": "Comfortable denim jeans",
            "category": "Clothing",
        },
        {
            "name": "Running Shoes",
            "price": "1299.99",
            "description": "Professional running shoes",
            "category": "Footwear",
        },
        {
            "name": "Backpack",
            "price": "549.99",
            "description": "Spacious and durable backpack",
            "category": "Accessories",
        },
        {
            "name": "Sunglasses",
            "price": "349.99",
            "description": "UV protection sunglasses",
            "category": "Accessories",
        },
    ]

    created_products = []

    for i, product in enumerate(sample_products[:count]):
        try:
            # Create product
            cmd = (
                f"wc product create "
                f"--name='{product['name']}' "
                f"--type=simple "
                f"--regular_price={product['price']} "
                f"--description='{product['description']}' "
                f"--status=publish "
                f"--user=admin"
            )

            result = execute_wp_cli(site_name, cmd)

            if result["success"]:
                created_products.append(product["name"])
                logger.info(f"✅ Created product: {product['name']}")
            else:
                logger.warning(f"Failed to create product: {product['name']}")

        except Exception as e:
            logger.error(f"Error creating product {product['name']}: {e}")

    return {
        "success": True,
        "products_created": len(created_products),
        "product_names": created_products,
    }


def get_store_info(site_name):
    """
    Get WooCommerce store information

    Args:
        site_name: Name of the WordPress site

    Returns:
        dict: Store information
    """
    try:
        # Check if WooCommerce is active
        result = execute_wp_cli(site_name, "plugin list --format=json --status=active")

        if result["success"]:
            import json

            plugins = json.loads(result["output"])
            wc_active = any(p.get("name") == "woocommerce" for p in plugins)

            if not wc_active:
                return {"success": False, "message": "WooCommerce is not active"}

            # Get store settings
            store_info = {"success": True, "woocommerce_active": True, "settings": {}}

            # Get various settings
            settings_to_check = [
                "woocommerce_currency",
                "woocommerce_store_address",
                "woocommerce_store_city",
                "woocommerce_store_postcode",
            ]

            for setting in settings_to_check:
                result = execute_wp_cli(site_name, f"option get {setting}")
                if result["success"]:
                    store_info["settings"][setting] = result["output"].strip()

            return store_info

        return {"success": False, "message": "Could not check WooCommerce status"}

    except Exception as e:
        logger.error(f"Error getting store info: {e}")
        return {"success": False, "error": str(e)}
