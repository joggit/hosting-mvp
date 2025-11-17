"""
Deployment endpoints - Enhanced version
Handles Node.js/Next.js deployment with domain configuration
"""

from flask import request, jsonify
import os
import subprocess
import shutil
import json
from pathlib import Path
from services.database import get_db
from services.port_checker import find_available_ports
from config.settings import CONFIG


def register_routes(app):
    """Register deployment-related routes"""

    @app.route("/api/deploy/nodejs", methods=["POST"])
    def deploy_nodejs():
        """Deploy a Node.js/Next.js application"""
        try:
            # Better JSON parsing with error handling
            if not request.is_json:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Content-Type must be application/json",
                        }
                    ),
                    400,
                )

            try:
                data = request.get_json(force=True)
            except Exception as json_error:
                return (
                    jsonify(
                        {"success": False, "error": f"Invalid JSON: {str(json_error)}"}
                    ),
                    400,
                )

            if not data:
                return (
                    jsonify({"success": False, "error": "Request body is empty"}),
                    400,
                )

            # ═══════════════════════════════════════════════════════════
            # STEP 1: Validate required fields
            # ═══════════════════════════════════════════════════════════
            if "name" not in data or "files" not in data:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Missing required fields: name and files",
                        }
                    ),
                    400,
                )

            site_name = data["name"]
            project_files = data["files"]
            deploy_config = data.get("deployConfig", {})
            domain_config = data.get("domain_config")

            app.logger.info(f"═══════════════════════════════════════")
            app.logger.info(f"🚀 Starting deployment for {site_name}")
            app.logger.info(f"Has domain_config: {domain_config is not None}")
            app.logger.info(f"Files count: {len(project_files)}")
            app.logger.info(f"═══════════════════════════════════════")

            # Validate app name (allow dots for domain names)
            app.logger.info(f"Validating site name: '{site_name}'")

            # More lenient validation - allow dots, hyphens, underscores for domains
            cleaned_name = site_name.replace("-", "").replace("_", "").replace(".", "")
            if not cleaned_name.isalnum():
                app.logger.error(f"Site name validation failed: '{site_name}'")
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Invalid site name '{site_name}'. Use only letters, numbers, hyphens, underscores, and dots",
                        }
                    ),
                    400,
                )

            app.logger.info(f"✅ Site name validation passed: '{site_name}'")

            # ═══════════════════════════════════════════════════════════
            # STEP 2: Process domain configuration
            # ═══════════════════════════════════════════════════════════
            full_domain = None
            deployment_type = "simple"

            if domain_config:
                if domain_config.get("subdomain") and domain_config.get(
                    "parent_domain"
                ):
                    subdomain = domain_config["subdomain"].lower().strip()
                    parent_domain = domain_config["parent_domain"]
                    full_domain = f"{subdomain}.{parent_domain}"
                    deployment_type = "subdomain"
                    app.logger.info(f"Subdomain deployment: {full_domain}")

                elif domain_config.get("root_domain"):
                    full_domain = domain_config["root_domain"]
                    deployment_type = "root"
                    app.logger.info(f"Root domain deployment: {full_domain}")

                # Check if domain already exists
                if full_domain:
                    app.logger.info(
                        f"Checking if domain {full_domain} exists in database..."
                    )
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM domains WHERE domain_name = ?",
                        (full_domain,),
                    )
                    exists = cursor.fetchone()[0] > 0
                    conn.close()

                    app.logger.info(f"Domain exists check: {exists}")

                    if exists:
                        error_msg = f"Domain {full_domain} already exists. Please delete it first or use a different name."
                        app.logger.error(f"❌ {error_msg}")
                        return jsonify({"success": False, "error": error_msg}), 400

                    app.logger.info(f"✅ Domain {full_domain} is available")

            # ═══════════════════════════════════════════════════════════
            # STEP 3: Fix package.json for Next.js + PM2 compatibility
            # ═══════════════════════════════════════════════════════════
            if "package.json" in project_files:
                app.logger.info("Processing package.json...")
                try:
                    package_data = json.loads(project_files["package.json"])
                    fixes_applied = []

                    # Remove "type": "module" for PM2 compatibility
                    if package_data.get("type") == "module":
                        del package_data["type"]
                        fixes_applied.append(
                            "Removed 'type: module' for PM2 compatibility"
                        )

                    # Ensure proper scripts exist
                    if "scripts" not in package_data:
                        package_data["scripts"] = {}

                    scripts = package_data["scripts"]
                    if "build" not in scripts:
                        scripts["build"] = "next build"
                        fixes_applied.append("Added build script")

                    if "start" not in scripts:
                        scripts["start"] = "next start"
                        fixes_applied.append("Added start script")

                    # Update the package.json content
                    project_files["package.json"] = json.dumps(package_data, indent=2)

                    if fixes_applied:
                        app.logger.info(f"Package.json fixes: {fixes_applied}")

                except json.JSONDecodeError as e:
                    app.logger.error(f"Invalid package.json: {e}")
                    return (
                        jsonify(
                            {"success": False, "error": "Invalid package.json format"}
                        ),
                        400,
                    )

            # Add next.config.js if missing
            if (
                "next.config.js" not in project_files
                and "next.config.mjs" not in project_files
            ):
                project_files[
                    "next.config.js"
                ] = """/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
};

module.exports = nextConfig;"""
                app.logger.info("Added next.config.js")

            # ═══════════════════════════════════════════════════════════
            # STEP 4: Port allocation
            # ═══════════════════════════════════════════════════════════
            allocated_port = deploy_config.get("port")

            if not allocated_port:
                # Find available port
                available_ports = find_available_ports(3000, 1)
                allocated_port = available_ports[0] if available_ports else 3000
                app.logger.info(f"Allocated port: {allocated_port}")

            # ═══════════════════════════════════════════════════════════
            # STEP 5: Create app directory and write files
            # ═══════════════════════════════════════════════════════════
            app_dir = f"{CONFIG['web_root']}/{site_name}"
            app.logger.info(f"Checking if app directory exists: {app_dir}")

            if os.path.exists(app_dir):
                error_msg = (
                    f"Application directory '{site_name}' already exists at {app_dir}"
                )
                app.logger.error(f"❌ {error_msg}")
                return jsonify({"success": False, "error": error_msg}), 400

            app.logger.info(f"Creating app directory: {app_dir}")
            os.makedirs(app_dir, exist_ok=True)

            # Write all files
            for file_path, content in project_files.items():
                full_path = os.path.join(app_dir, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)

                with open(full_path, "w") as f:
                    f.write(content)

            app.logger.info(f"Written {len(project_files)} files")

            # ═══════════════════════════════════════════════════════════
            # STEP 6: Install dependencies
            # ═══════════════════════════════════════════════════════════
            # In routes/deployment.py, replace the npm install section:

            if "package.json" in project_files:
                app.logger.info(
                    "Running npm install (this may take several minutes)..."
                )

                try:
                    # Use pnpm if available, fallback to npm
                    pkg_manager = "pnpm" if shutil.which("pnpm") else "npm"
                    app.logger.info(f"Using package manager: {pkg_manager}")

                    result = subprocess.run(
                        [pkg_manager, "install"],
                        cwd=app_dir,
                        capture_output=True,
                        text=True,
                        timeout=900,  # 15 minutes
                    )

                    if result.returncode != 0:
                        app.logger.error(f"npm install failed: {result.stderr}")
                        shutil.rmtree(app_dir)
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "npm install failed",
                                    "details": result.stderr,
                                }
                            ),
                            500,
                        )

                    app.logger.info("✅ npm install completed")

                    # Run build if build script exists
                    try:
                        package_data = json.loads(
                            project_files.get("package.json", "{}")
                        )
                        if "build" in package_data.get("scripts", {}):
                            app.logger.info(
                                "Running npm build (this may take several minutes)..."
                            )
                            build_result = subprocess.run(
                                [pkg_manager, "run", "build"],
                                cwd=app_dir,
                                capture_output=True,
                                text=True,
                                timeout=900,  # 15 minutes
                            )

                            if build_result.returncode == 0:
                                app.logger.info("✅ Build completed")
                            else:
                                app.logger.warning(f"Build completed with warnings")
                    except subprocess.TimeoutExpired:
                        app.logger.warning("Build timed out, but continuing...")
                    except Exception as build_error:
                        app.logger.warning(
                            f"Build error (continuing anyway): {build_error}"
                        )

                except subprocess.TimeoutExpired:
                    app.logger.error("npm install timed out after 15 minutes")
                    shutil.rmtree(app_dir)
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "npm install timed out. The application may have too many dependencies.",
                            }
                        ),
                        500,
                    )

            # ═══════════════════════════════════════════════════════════
            # STEP 7: Start the application (PM2 or simple process)
            # ═══════════════════════════════════════════════════════════
            process_manager = "simple"

            try:
                # Check for PM2 using full path
                pm2_path = shutil.which("pm2") or "/usr/bin/pm2"
                pm2_exists = os.path.exists(pm2_path)

                if pm2_exists:
                    app.logger.info(f"Starting with PM2 at {pm2_path}...")

                    # Create PM2 ecosystem file for better control
                    ecosystem = {
                        "apps": [
                            {
                                "name": site_name,
                                "cwd": app_dir,
                                "script": "npm",
                                "args": "start",
                                "env": {
                                    "PORT": str(allocated_port),
                                    "NODE_ENV": "production",
                                },
                                "instances": 1,
                                "autorestart": True,
                                "watch": False,
                                "max_memory_restart": "1G",
                            }
                        ]
                    }

                    ecosystem_path = os.path.join(app_dir, "ecosystem.config.json")
                    with open(ecosystem_path, "w") as f:
                        json.dump(ecosystem, f, indent=2)

                    # Start with PM2
                    pm2_result = subprocess.run(
                        [pm2_path, "start", ecosystem_path],
                        capture_output=True,
                        text=True,
                    )

                    if pm2_result.returncode == 0:
                        process_manager = "pm2"
                        app.logger.info(f"✅ Started with PM2")

                        # Save PM2 process list
                        subprocess.run([pm2_path, "save"], capture_output=True)
                    else:
                        app.logger.warning(f"PM2 start failed: {pm2_result.stderr}")
                        raise Exception("PM2 failed")
                else:
                    raise Exception("PM2 not found")

            except Exception as e:
                # Fallback to simple background process
                app.logger.info(
                    f"Starting as background process (PM2 not available: {e})"
                )
                subprocess.Popen(
                    ["npm", "start"],
                    cwd=app_dir,
                    env={**os.environ, "PORT": str(allocated_port)},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                app.logger.info("✅ Started as background process")

            # ═══════════════════════════════════════════════════════════
            # STEP 8: Create nginx configuration (if domain provided)
            # ═══════════════════════════════════════════════════════════
            if full_domain:
                app.logger.info(f"Creating nginx config for {full_domain}")

                nginx_config = f"""server {{
    listen 80;
    server_name {full_domain};
    
    location / {{
        proxy_pass http://localhost:{allocated_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}"""

                try:
                    nginx_path = f"/etc/nginx/sites-available/{full_domain}"
                    with open(nginx_path, "w") as f:
                        f.write(nginx_config)

                    # Enable site
                    enabled_path = f"/etc/nginx/sites-enabled/{full_domain}"
                    if os.path.exists(enabled_path):
                        os.remove(enabled_path)
                    os.symlink(nginx_path, enabled_path)

                    # Test and reload nginx
                    test_result = subprocess.run(["nginx", "-t"], capture_output=True)
                    if test_result.returncode == 0:
                        subprocess.run(["systemctl", "reload", "nginx"])
                        app.logger.info("✅ Nginx configured and reloaded")
                    else:
                        app.logger.warning("Nginx config test failed")

                except Exception as nginx_error:
                    app.logger.warning(f"Could not configure nginx: {nginx_error}")

            # ═══════════════════════════════════════════════════════════
            # STEP 9: Save to database
            # ═══════════════════════════════════════════════════════════
            conn = get_db()
            cursor = conn.cursor()

            # Save domain
            if full_domain:
                cursor.execute(
                    """
                    INSERT INTO domains (domain_name, port, app_name, ssl_enabled, status)
                    VALUES (?, ?, ?, ?, 'active')
                """,
                    (full_domain, allocated_port, site_name, False),
                )

            # Save process
            cursor.execute(
                """
                INSERT INTO processes (name, port, status)
                VALUES (?, ?, 'running')
            """,
                (site_name, allocated_port),
            )

            # Log deployment
            cursor.execute(
                """
                INSERT INTO deployment_logs (domain_name, action, status, message)
                VALUES (?, 'deploy', 'success', ?)
            """,
                (full_domain or site_name, f"Deployed {deployment_type} application"),
            )

            conn.commit()
            conn.close()

            app.logger.info("✅ Database updated")

            # ═══════════════════════════════════════════════════════════
            # STEP 10: Build response
            # ═══════════════════════════════════════════════════════════
            response_data = {
                "success": True,
                "site_name": site_name,
                "port": allocated_port,
                "process_manager": process_manager,
                "files_path": app_dir,
                "message": "Deployment successful",
            }

            if full_domain:
                response_data["domain"] = {
                    "full_domain": full_domain,
                    "domain_type": deployment_type,
                    "url": f"http://{full_domain}",
                    "ssl_enabled": False,
                }

                if deployment_type == "subdomain":
                    response_data["domain"]["subdomain"] = domain_config["subdomain"]
                    response_data["domain"]["parent_domain"] = domain_config[
                        "parent_domain"
                    ]
            else:
                response_data["url"] = f"http://localhost:{allocated_port}"

            app.logger.info(f"═══════════════════════════════════════")
            app.logger.info(f"✅ Deployment completed successfully")
            app.logger.info(f"Site: {site_name}")
            app.logger.info(f"Port: {allocated_port}")
            if full_domain:
                app.logger.info(f"Domain: {full_domain}")
            app.logger.info(f"═══════════════════════════════════════")

            return jsonify(response_data)

        except Exception as e:
            app.logger.error(f"Deployment error: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
