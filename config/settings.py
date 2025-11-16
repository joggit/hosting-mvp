"""Application configuration"""
import os

CONFIG = {
    "database_path": os.getenv('DB_PATH', '/var/lib/hosting-manager/hosting.db'),
    "web_root": "/var/www/domains",
    "ssl_email": "admin@smartwave.co.za",
}
