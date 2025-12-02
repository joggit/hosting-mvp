"""
Nginx configuration management
"""

import subprocess
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def create_nginx_reverse_proxy(domain, port):
    """Create nginx reverse proxy configuration - FIXED"""

    nginx_config = f"""server {{
    listen 80;
    server_name {domain} www.{domain};
    
    location / {{
        proxy_pass http://localhost:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
}}"""

    # Write config
    config_path = f"/etc/nginx/sites-available/{domain}"
    enabled_path = f"/etc/nginx/sites-enabled/{domain}"

    # Write to temp file first
    with open("/tmp/nginx_config.tmp", "w") as f:
        f.write(nginx_config)

    # Copy with sudo
    subprocess.run(["sudo", "cp", "/tmp/nginx_config.tmp", config_path], check=True)
    subprocess.run(["sudo", "rm", "-f", enabled_path], check=False)
    subprocess.run(["sudo", "ln", "-sf", config_path, enabled_path], check=True)

    # Test configuration WITH FULL PATH
    test_result = subprocess.run(
        ["sudo", "/usr/sbin/nginx", "-t"],
        capture_output=True,
        text=True,  # CHANGED HERE
    )

    if test_result.returncode != 0:
        raise Exception(f"Nginx config test failed: {test_result.stderr}")

    logger.info(f"✅ Nginx config created for {domain}")


def remove_nginx_site(domain):
    """Remove nginx configuration for a domain"""
    import subprocess

    sites_available = f"/etc/nginx/sites-available/{domain}"
    sites_enabled = f"/etc/nginx/sites-enabled/{domain}"

    # Remove symlink
    if os.path.exists(sites_enabled):
        subprocess.run(["sudo", "rm", sites_enabled], check=True)

    # Remove config file
    if os.path.exists(sites_available):
        subprocess.run(["sudo", "rm", sites_available], check=True)


def reload_nginx():
    """Reload nginx configuration"""
    subprocess.run(["sudo", "systemctl", "reload", "nginx"], check=True)
    logger.info("✅ Nginx reloaded")
