#!/usr/bin/env python3
"""
Hosting Manager MVP - Scalable Structure with WordPress Support
"""
import sys
import logging
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask
from flask_cors import CORS
from config.settings import CONFIG
from services.database import init_database
from routes import register_all_routes
from utils.logger import setup_logger

# Setup
logger = setup_logger(__name__)
app = Flask(__name__)
CORS(app)

# ═══════════════════════════════════════════════════════════
# Initialize Core Services
# ═══════════════════════════════════════════════════════════

# Initialize database (includes WordPress tables)
init_database()

# Ensure WordPress base directory exists
WORDPRESS_BASE_DIR = "/var/www/wordpress"
os.makedirs(WORDPRESS_BASE_DIR, exist_ok=True)
logger.info(f"✅ WordPress directory: {WORDPRESS_BASE_DIR}")

# Ensure standard web root exists
os.makedirs(CONFIG["web_root"], exist_ok=True)
logger.info(f"✅ Web root: {CONFIG['web_root']}")

# Register all routes (automatically includes WordPress routes)
register_all_routes(app)

# ═══════════════════════════════════════════════════════════
# Route Display
# ═══════════════════════════════════════════════════════════


def show_routes():
    """Display all registered routes organized by prefix"""
    logger.info("=" * 60)
    logger.info("📋 Registered Routes:")
    logger.info("=" * 60)

    routes_by_prefix = {}

    for rule in app.url_map.iter_rules():
        if rule.endpoint != "static":
            parts = rule.rule.split("/")
            prefix = parts[2] if len(parts) > 2 else "root"

            if prefix not in routes_by_prefix:
                routes_by_prefix[prefix] = []

            methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
            routes_by_prefix[prefix].append((methods, rule.rule))

    for prefix in sorted(routes_by_prefix.keys()):
        logger.info(f"\n  {prefix.upper()}:")
        for methods, path in sorted(routes_by_prefix[prefix]):
            logger.info(f"    {methods:12} {path}")

    logger.info("\n" + "=" * 60)


# ═══════════════════════════════════════════════════════════
# Startup Checks
# ═══════════════════════════════════════════════════════════


def check_docker_available():
    """Check if Docker is available for WordPress deployments"""
    import shutil

    docker_available = shutil.which("docker") is not None
    docker_compose_available = shutil.which("docker-compose") is not None

    if docker_available and docker_compose_available:
        logger.info("✅ Docker & Docker Compose available (WordPress enabled)")
        return True
    else:
        logger.warning("⚠️  Docker not found (WordPress disabled)")
        logger.warning("   Install: sudo apt install docker.io docker-compose")
        return False


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🚀 Hosting Manager MVP Starting")
    logger.info("=" * 60)
    logger.info(f"Database: {CONFIG['database_path']}")
    logger.info(f"Web Root: {CONFIG['web_root']}")
    logger.info(f"WordPress Sites: {WORDPRESS_BASE_DIR}")
    logger.info("=" * 60)

    # Check Docker availability
    check_docker_available()

    # Show all registered routes
    show_routes()

    logger.info("🌐 Server starting on http://0.0.0.0:5000")
    logger.info("=" * 60 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False)
