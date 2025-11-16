#!/usr/bin/env python3
"""
Hosting Manager MVP - Scalable Structure
"""
import sys
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

# Initialize database
init_database()

# Register all routes
register_all_routes(app)

# Show routes on startup
def show_routes():
    logger.info("=" * 60)
    logger.info("📋 Registered Routes:")
    logger.info("=" * 60)
    
    routes_by_prefix = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            prefix = rule.rule.split('/')[2] if len(rule.rule.split('/')) > 2 else 'root'
            if prefix not in routes_by_prefix:
                routes_by_prefix[prefix] = []
            methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
            routes_by_prefix[prefix].append((methods, rule.rule))
    
    for prefix in sorted(routes_by_prefix.keys()):
        logger.info(f"\n  {prefix.upper()}:")
        for methods, path in sorted(routes_by_prefix[prefix]):
            logger.info(f"    {methods:12} {path}")
    
    logger.info("\n" + "=" * 60)

if __name__ == '__main__':
    logger.info("🚀 Hosting Manager MVP Starting")
    show_routes()
    logger.info("🌐 Server starting on http://0.0.0.0:5000")
    logger.info("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
