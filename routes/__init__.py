"""
Route registration system
Automatically loads all route files and registers them
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def register_all_routes(app):
    """
    Automatically discover and register all route modules
    Each module should have a register_routes(app) function
    """
    routes_dir = Path(__file__).parent
    route_files = [f for f in routes_dir.glob('*.py') if f.stem not in ['__init__']]
    
    for route_file in route_files:
        module_name = f"routes.{route_file.stem}"
        try:
            # Import the module
            module = __import__(module_name, fromlist=['register_routes'])
            
            # Call its register_routes function
            if hasattr(module, 'register_routes'):
                module.register_routes(app)
                logger.info(f"✅ Registered routes from {route_file.stem}")
            else:
                logger.warning(f"⚠️  {route_file.stem} has no register_routes() function")
        except Exception as e:
            logger.error(f"❌ Failed to load {module_name}: {e}")

    logger.info(f"✅ All routes registered")
