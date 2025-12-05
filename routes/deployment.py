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
                    app.logger.error(f"❌ Invalid package.json: {e}")
                    return (
                        jsonify(
                            {"success": False, "error": "Invalid package.json format"}
                        ),
                        400,
                    )

            # Add next.config.js if missing or fix incompatible options
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
            else:
                # Check if next.config.js has incompatible options
                config_key = (
                    "next.config.js"
                    if "next.config.js" in project_files
                    else "next.config.mjs"
                )
                config_content = project_files[config_key]

                # Remove serverExternalPackages if present (Next.js 15+ feature)
                if "serverExternalPackages" in config_content:
                    app.logger.warning(
                        "Removing serverExternalPackages from next.config (requires Next.js 15+)"
                    )
                    # For simplicity, use a safe default config
                    project_files[
                        config_key
                    ] = """/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  compress: true
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

            app.logger.info(f"Checking app directory: {app_dir}")

            if os.path.exists(app_dir):
                app.logger.warning(f"⚠️  Directory exists, cleaning up: {app_dir}")
                try:
                    shutil.rmtree(app_dir)
                    app.logger.info(f"✅ Cleaned up old directory")
                except Exception as e:
                    app.logger.error(f"❌ Failed to clean directory: {e}")
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Directory exists and cannot be removed: {str(e)}",
                            }
                        ),
                        400,
                    )

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

                    # Create PM2 ecosystem file with FORK mode (critical for Next.js)
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
                                "exec_mode": "fork",  # CRITICAL: Use fork mode for Next.js
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

                # Create nginx config
                nginx_config = f"""server {{
    listen 80;
    server_name {full_domain} www.{full_domain};
    
    location / {{
        proxy_pass http://localhost:{allocated_port};
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

                try:
                    nginx_path = f"/etc/nginx/sites-available/{full_domain}"
                    app.logger.info(f"Writing nginx config to: {nginx_path}")

                    # Write config using sudo
                    with open("/tmp/nginx_config.tmp", "w") as f:
                        f.write(nginx_config)

                    subprocess.run(
                        ["sudo", "cp", "/tmp/nginx_config.tmp", nginx_path], check=True
                    )
                    os.remove("/tmp/nginx_config.tmp")

                    # Enable site
                    enabled_path = f"/etc/nginx/sites-enabled/{full_domain}"
                    subprocess.run(["sudo", "rm", "-f", enabled_path], check=False)
                    subprocess.run(
                        ["sudo", "ln", "-sf", nginx_path, enabled_path], check=True
                    )

                    app.logger.info("Nginx config created and enabled")

                    # Disable default site if it exists
                    subprocess.run(
                        ["sudo", "rm", "-f", "/etc/nginx/sites-enabled/default"],
                        check=False,
                    )
                    app.logger.info("Disabled default nginx site")

                    # Test nginx config
                    test_result = subprocess.run(
                        ["sudo", "nginx", "-t"], capture_output=True, text=True
                    )

                    if test_result.returncode == 0:
                        subprocess.run(["sudo", "systemctl", "reload", "nginx"])
                        app.logger.info("✅ Nginx configured and reloaded")
                    else:
                        app.logger.error(
                            f"Nginx config test failed: {test_result.stderr}"
                        )

                except Exception as nginx_error:
                    app.logger.error(f"Could not configure nginx: {nginx_error}")
                    import traceback

                    traceback.print_exc()

            # ═══════════════════════════════════════════════════════════
            # STEP 9: Save to database
            # ═══════════════════════════════════════════════════════════
            conn = get_db()
            cursor = conn.cursor()

        # Save domain (without port - it's tracked in processes)
        if full_domain:
            # Check if domain already exists
            cursor.execute("SELECT id FROM domains WHERE domain_name = ?", (full_domain,))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing domain
                cursor.execute(
                    """
                    UPDATE domains 
                    SET app_name = ?, ssl_enabled = ?, status = 'active'
                    WHERE domain_name = ?
                    """,
                    (site_name, False, full_domain),
                )
            else:
                # Insert new domain (without port column)
                cursor.execute(
                    """
                    INSERT INTO domains (domain_name, app_name, ssl_enabled, status)
                    VALUES (?, ?, ?, 'active')
                    """,
                    (full_domain, site_name, False),
                )

        # Save process
        # Check if process already exists
        cursor.execute("SELECT id FROM processes WHERE name = ?", (site_name,))
        existing_process = cursor.fetchone()

        if existing_process:
            # Update existing process
            cursor.execute(
                """
                UPDATE processes 
                SET port = ?, status = 'running'
                WHERE name = ?
                """,
                (allocated_port, site_name),
            )
        else:
            # Insert new process
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

    # ============================================================
    # GET: Fetch info about a deployed Node.js/Next.js site
    # ============================================================
    @app.route("/api/deploy/nodejs/<site_name>", methods=["GET"])
    def get_nodejs_site(site_name):
        """Return information about a deployed Node.js/Next.js site"""
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Look up process info
            cursor.execute(
                "SELECT port, status FROM processes WHERE name = ?",
                (site_name,),
            )
            process_row = cursor.fetchone()

            if not process_row:
                conn.close()
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"No process entry found for site '{site_name}'",
                        }
                    ),
                    404,
                )

            port, proc_status = process_row

            # Look up domain info (may or may not exist)
            cursor.execute(
                "SELECT domain_name, ssl_enabled, status FROM domains WHERE app_name = ?",
                (site_name,),
            )
            domain_row = cursor.fetchone()
            conn.close()

            domain_info = None
            nginx_available = False
            nginx_enabled = False

            if domain_row:
                domain_name, ssl_enabled, domain_status = domain_row
                domain_info = {
                    "domain_name": domain_name,
                    "ssl_enabled": bool(ssl_enabled),
                    "status": domain_status,
                    "url": f"http://{domain_name}",
                }

                nginx_conf = Path(f"/etc/nginx/sites-available/{domain_name}")
                nginx_enabled_conf = Path(f"/etc/nginx/sites-enabled/{domain_name}")
                nginx_available = nginx_conf.exists()
                nginx_enabled = nginx_enabled_conf.exists()

            # Filesystem info
            app_dir = Path(CONFIG["web_root"]) / site_name
            app_dir_exists = app_dir.exists()

            # PM2 status (if available)
            pm2_path = shutil.which("pm2") or "/usr/bin/pm2"
            pm2_running = False
            pm2_status_output = None

            if os.path.exists(pm2_path):
                try:
                    pm2_result = subprocess.run(
                        [pm2_path, "describe", site_name],
                        capture_output=True,
                        text=True,
                    )
                    if pm2_result.returncode == 0:
                        pm2_status_output = pm2_result.stdout
                        pm2_running = "online" in pm2_result.stdout.lower()
                except Exception:
                    # PM2 not critical here; ignore errors
                    pass

            return jsonify(
                {
                    "success": True,
                    "site_name": site_name,
                    "port": port,
                    "process_status": proc_status,
                    "app_dir": str(app_dir),
                    "app_dir_exists": app_dir_exists,
                    "domain": domain_info,
                    "nginx": {
                        "has_config": nginx_available,
                        "is_enabled": nginx_enabled,
                    },
                    "pm2": {
                        "available": os.path.exists(pm2_path),
                        "running": pm2_running,
                        "raw_status": pm2_status_output,
                    },
                }
            )

        except Exception as e:
            app.logger.error(f"Error fetching site info for {site_name}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        
        # ============================================================
    # LIST ALL DEPLOYED NODEJS/NEXTJS SITES
    # ============================================================
    @app.route("/api/deploy/nodejs", methods=["GET"])
    def list_nodejs_sites():
        """
        Returns a JSON list of all deployed Node.js/Next.js applications.
        Includes:
         - process info
         - domain info
         - filesystem path
         - PM2 status (if available)
        """
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Fetch all processes
            cursor.execute("SELECT id, name, port, status FROM processes")
            process_rows = cursor.fetchall()

            # Fetch all domains mapped by app_name
            cursor.execute("SELECT domain_name, app_name, ssl_enabled, status FROM domains")
            domain_rows = cursor.fetchall()

            # Domain lookup table for fast matching
            domains_by_app = {}
            for domain_name, app_name, ssl_enabled, status in domain_rows:
                domains_by_app.setdefault(app_name, []).append(
                    {
                        "domain_name": domain_name,
                        "ssl_enabled": bool(ssl_enabled),
                        "status": status,
                        "url": f"http://{domain_name}",
                    }
                )

            conn.close()

            pm2_path = shutil.which("pm2") or "/usr/bin/pm2"
            pm2_available = os.path.exists(pm2_path)

            site_list = []

            for proc_id, site_name, port, proc_status in process_rows:
                app_dir = Path(CONFIG["web_root"]) / site_name

                # Check if PM2 process is running
                pm2_running = False
                if pm2_available:
                    try:
                        pm2_res = subprocess.run(
                            [pm2_path, "describe", site_name],
                            capture_output=True,
                            text=True,
                        )
                        pm2_running = "online" in pm2_res.stdout.lower()
                    except Exception:
                        pass

                # Attach domain info (may be multiple domains)
                domain_info = domains_by_app.get(site_name, None)

                site_list.append(
                    {
                        "site_name": site_name,
                        "port": port,
                        "process_status": proc_status,
                        "files_path": str(app_dir),
                        "exists_on_disk": app_dir.exists(),
                        "pm2": {
                            "available": pm2_available,
                            "running": pm2_running,
                        },
                        "domains": domain_info,
                    }
                )

            return jsonify({"success": True, "sites": site_list})

        except Exception as e:
            app.logger.error(f"Error listing NodeJS sites: {e}")
            return jsonify({"success": False, "error": str(e)}), 500


    # ============================================================
    # DELETE: Fully remove a Node.js/Next.js site
    # ============================================================
    @app.route("/api/deploy/nodejs/<site_name>", methods=["DELETE"])
    def delete_nodejs_site(site_name):
        """
        Completely remove a Node.js/Next.js site:
        - Stop & delete PM2 process
        - Remove nginx vhost (available + enabled)
        - Delete app files from web_root
        - Remove SQLite entries (domains, processes, logs)
        """
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Fetch process info
            cursor.execute(
                "SELECT id, port FROM processes WHERE name = ?",
                (site_name,),
            )
            process_row = cursor.fetchone()

            if not process_row:
                conn.close()
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"No process entry found for site '{site_name}'",
                        }
                    ),
                    404,
                )

            process_id, port = process_row

            # Fetch domain info (optional)
            cursor.execute(
                "SELECT id, domain_name FROM domains WHERE app_name = ?",
                (site_name,),
            )
            domain_row = cursor.fetchone()

            domain_id = None
            domain_name = None
            if domain_row:
                domain_id, domain_name = domain_row

            app.logger.info("═══════════════════════════════════════")
            app.logger.info(f"🗑 Starting deletion for {site_name}")
            app.logger.info(f"Process ID: {process_id}, Port: {port}")
            if domain_name:
                app.logger.info(f"Domain: {domain_name}")
            app.logger.info("═══════════════════════════════════════")

            # 1) Stop & delete PM2 process
            pm2_path = shutil.which("pm2") or "/usr/bin/pm2"
            if os.path.exists(pm2_path):
                try:
                    app.logger.info(f"Stopping PM2 process for {site_name}...")
                    subprocess.run(
                        [pm2_path, "stop", site_name],
                        capture_output=True,
                        text=True,
                    )

                    app.logger.info(f"Deleting PM2 process for {site_name}...")
                    subprocess.run(
                        [pm2_path, "delete", site_name],
                        capture_output=True,
                        text=True,
                    )

                    # Save PM2 state
                    subprocess.run([pm2_path, "save"], capture_output=True, text=True)

                    app.logger.info("✅ PM2 process removed")
                except Exception as e:
                    app.logger.warning(f"PM2 cleanup failed (non-fatal): {e}")

            # 2) Remove nginx config (if domain exists)
            if domain_name:
                nginx_conf = Path(f"/etc/nginx/sites-available/{domain_name}")
                nginx_enabled_conf = Path(f"/etc/nginx/sites-enabled/{domain_name}")

                try:
                    if nginx_enabled_conf.exists():
                        app.logger.info(f"Removing nginx enabled site: {nginx_enabled_conf}")
                        subprocess.run(
                            ["sudo", "rm", "-f", str(nginx_enabled_conf)],
                            check=False,
                        )

                    if nginx_conf.exists():
                        app.logger.info(f"Removing nginx available site: {nginx_conf}")
                        subprocess.run(
                            ["sudo", "rm", "-f", str(nginx_conf)],
                            check=False,
                        )

                    # Test and reload nginx if configs changed
                    app.logger.info("Reloading nginx...")
                    test_result = subprocess.run(
                        ["sudo", "nginx", "-t"],
                        capture_output=True,
                        text=True,
                    )
                    if test_result.returncode == 0:
                        subprocess.run(
                            ["sudo", "systemctl", "reload", "nginx"],
                            capture_output=True,
                            text=True,
                        )
                        app.logger.info("✅ Nginx reloaded")
                    else:
                        app.logger.error(
                            f"Nginx test failed after deletion: {test_result.stderr}"
                        )
                except Exception as e:
                    app.logger.warning(f"Nginx cleanup failed (non-fatal): {e}")

            # 3) Remove app files
            app_dir = Path(CONFIG["web_root"]) / site_name
            if app_dir.exists():
                try:
                    app.logger.info(f"Removing app directory: {app_dir}")
                    shutil.rmtree(app_dir)
                    app.logger.info("✅ App directory removed")
                except Exception as e:
                    app.logger.warning(f"App directory cleanup failed (non-fatal): {e}")

            # 4) Remove SQLite entries (domains, processes, logs)
            try:
                if domain_name:
                    cursor.execute(
                        "DELETE FROM domains WHERE id = ?",
                        (domain_id,),
                    )

                cursor.execute(
                    "DELETE FROM processes WHERE id = ?",
                    (process_id,),
                )

                # Optional: log deletion
                cursor.execute(
                    """
                    INSERT INTO deployment_logs (domain_name, action, status, message)
                    VALUES (?, 'delete', 'success', ?)
                    """,
                    (domain_name or site_name, f"Deleted application {site_name}"),
                )

                conn.commit()
                conn.close()
                app.logger.info("✅ Database entries cleaned up")
            except Exception as e:
                app.logger.error(f"Database cleanup failed: {e}")
                conn.rollback()
                conn.close()
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Database cleanup failed: {str(e)}",
                        }
                    ),
                    500,
                )

            app.logger.info("═══════════════════════════════════════")
            app.logger.info(f"✅ Deletion completed for {site_name}")
            app.logger.info("═══════════════════════════════════════")

            return jsonify(
                {
                    "success": True,
                    "message": f"Site '{site_name}' deleted successfully",
                    "site_name": site_name,
                    "removed": {
                        "pm2": True,
                        "nginx": bool(domain_name),
                        "files": True,
                        "database": True,
                    },
                }
            )

        except Exception as e:
            app.logger.error(f"Error deleting site {site_name}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500