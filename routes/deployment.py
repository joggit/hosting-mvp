"""
Deployment endpoints - Enhanced version
Handles Node.js/Next.js deployment with domain configuration
"""

import os
import subprocess
import shutil
import json
from pathlib import Path
from services.database import get_db
from services.port_checker import find_available_ports
from services.wordpress_docker import (
    create_site as wp_docker_create_site,
    list_sites as wp_docker_list_sites,
    delete_site as wp_docker_delete_site,
    import_site_database as wp_docker_import_db,
)
from config.settings import CONFIG
from routes.pages import init_pages_table
from flask import request, jsonify


def register_routes(app):
    """Register deployment-related routes"""

    def create_deployment_pages(domain, selected_pages, site_name, app):
        """Create pages during deployment"""
        if not selected_pages or not domain:
            return

        app.logger.info(f"📄 Creating {len(selected_pages)} pages for {domain}")
        init_pages_table()

        conn = get_db()
        cursor = conn.cursor()

        try:
            for page in selected_pages:
                cursor.execute(
                    "SELECT id FROM pages WHERE site_id = ? AND slug = ?",
                    (domain, page.get("slug")),
                )
                if cursor.fetchone():
                    continue

                cursor.execute(
                    """
                    INSERT INTO pages (
                        site_id, page_name, slug, template_id, sections, 
                        metadata, published
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        domain,
                        page.get("pageName"),
                        page.get("slug"),
                        page.get("templateId"),
                        json.dumps({}),
                        json.dumps({"title": f"{page.get('pageName')} - {site_name}"}),
                        page.get("published", True),
                    ),
                )

                app.logger.info(f"  ✅ {page.get('pageName')} ({page.get('slug')})")

            conn.commit()
        except Exception as e:
            app.logger.error(f"Error creating pages: {e}")
            conn.rollback()
        finally:
            conn.close()

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
            # START OF DEBUGGING CODE
            app.logger.info(f"📋 Files received from frontend:")
            for file_path in sorted(project_files.keys()):
                file_size = (
                    len(project_files[file_path])
                    if isinstance(project_files[file_path], str)
                    else 0
                )
                app.logger.info(f"   - {file_path} ({file_size} bytes)")
            # END OF DEBUGGING CODE

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
            domain = None
            if domain_config:
                # Get domain directly
                domain = domain_config.get("domain")
                if domain:
                    domain = domain.lower().strip()
                    app.logger.info(f"🌐 Domain deployment: {domain}")
                    # Check if domain already exists
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM domains WHERE domain_name = ?",
                        (domain,),
                    )
                    exists = cursor.fetchone()[0] > 0
                    conn.close()

                    if exists:
                        error_msg = f"Domain {domain} already exists. Please delete it first or use a different name."
                        app.logger.error(f"❌ {error_msg}")
                        return jsonify({"success": False, "error": error_msg}), 400

                    app.logger.info(f"✅ Domain {domain} is available")

            # ═══════════════════════════════════════════════════════════
            # STEP 3: Fix package.json for Next.js + PM2 compatibility
            # ═══════════════════════════════════════════════════════════
            if "package.json" in project_files:
                app.logger.info("Processing package.json...")
                try:
                    package_data = json.loads(project_files["package.json"])
                    fixes_applied = []

                    # Remove "type": "module" for PM2 compatibility
                    # if package_data.get("type") == "module":
                    # del package_data["type"]
                    # fixes_applied.append(
                    #    "Removed 'type: module' for PM2 compatibility - commenting out for now"
                    # )

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
            app_dir = f"{CONFIG['web_root']}/{domain}"
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
                                app.logger.error("❌ Build failed")
                                app.logger.error(build_result.stdout)
                                app.logger.error(build_result.stderr)
                                shutil.rmtree(app_dir, ignore_errors=True)
                                return (
                                    jsonify(
                                        {
                                            "success": False,
                                            "error": "Build failed",
                                            "stdout": build_result.stdout[
                                                -4000:
                                            ],  # prevent huge payloads
                                            "stderr": build_result.stderr[-4000:],
                                        }
                                    ),
                                    500,
                                )

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
            if domain:
                app.logger.info(f"🌐 Creating nginx config for {domain}")

                nginx_config = f"""server {{
                listen 80;
                server_name {domain} www.{domain};
                # Allow for localhost:5000 calls instead of public ip address   
                location /api/ {{
                    proxy_pass http://127.0.0.1:5000;
                    proxy_http_version 1.1;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    proxy_set_header X-Forwarded-Proto $scheme;
                }}
                
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
                    nginx_path = f"/etc/nginx/sites-available/{domain}"

                    # Write config using sudo
                    with open("/tmp/nginx_config.tmp", "w") as f:
                        f.write(nginx_config)

                    subprocess.run(
                        ["sudo", "cp", "/tmp/nginx_config.tmp", nginx_path], check=True
                    )
                    os.remove("/tmp/nginx_config.tmp")

                    # Enable site
                    enabled_path = f"/etc/nginx/sites-enabled/{domain}"
                    subprocess.run(["sudo", "rm", "-f", enabled_path], check=False)
                    subprocess.run(
                        ["sudo", "ln", "-sf", nginx_path, enabled_path], check=True
                    )
                    # Test and reload nginx
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

            # ═══════════════════════════════════════════════════════════
            # STEP 9: Save to database
            # ═══════════════════════════════════════════════════════════
            conn = get_db()
            cursor = conn.cursor()

            # Save domain (without port - it's tracked in processes)
            if domain:
                # Check if domain already exists
                cursor.execute(
                    "SELECT id FROM domains WHERE domain_name = ?", (domain,)
                )
                existing = cursor.fetchone()

                if existing:
                    # Update existing domain
                    cursor.execute(
                        """
                        UPDATE domains 
                        SET app_name = ?, ssl_enabled = ?, status = 'active'
                        WHERE domain_name = ?
                        """,
                        (site_name, False, domain),
                    )
                else:
                    # Insert new domain (without port column)
                    cursor.execute(
                        """
                        INSERT INTO domains (domain_name, app_name, ssl_enabled, status)
                        VALUES (?, ?, ?, 'active')
                        """,
                        (domain, site_name, False),
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
                (domain or site_name, f"Deployed application"),
            )
            conn.commit()
            conn.close()

            app.logger.info("✅ Database updated")

            # Create pages from selection
            selected_pages = data.get("selectedPages", [])
            if selected_pages and domain:
                create_deployment_pages(domain, selected_pages, site_name, app)

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

            if domain:
                response_data["domain"] = {
                    "domain": domain,
                    "url": f"http://{domain}",
                    "ssl_enabled": False,
                }
            else:
                response_data["url"] = f"http://localhost:{allocated_port}"

            app.logger.info(f"═══════════════════════════════════════")
            app.logger.info(f"✅ Deployment completed successfully")
            app.logger.info(f"Site: {site_name}")
            app.logger.info(f"Port: {allocated_port}")
            if domain:
                app.logger.info(f"Domain: {domain}")
            app.logger.info(f"═══════════════════════════════════════")

            return jsonify(response_data)

        except Exception as e:
            app.logger.error(f"Deployment error: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # POST: Deploy WordPress (Docker container, same host nginx)
    # ============================================================
    @app.route("/api/deploy/wordpress", methods=["POST"])
    def deploy_wordpress():
        """Deploy a WordPress theme to a new Docker stack; nginx on host proxies by domain."""
        try:
            if not request.is_json:
                return jsonify({"success": False, "error": "Content-Type must be application/json"}), 400
            try:
                data = request.get_json(force=True)
            except Exception as e:
                return jsonify({"success": False, "error": f"Invalid JSON: {str(e)}"}), 400
            if not data:
                return jsonify({"success": False, "error": "Request body is empty"}), 400

            name = data.get("name")
            files = data.get("files")
            domain_config = data.get("domain_config") or {}
            domain = (domain_config.get("domain") or "").strip().lower()

            if not name or not files:
                return jsonify({"success": False, "error": "Missing required fields: name and files"}), 400
            if not domain:
                return jsonify({"success": False, "error": "Missing domain in domain_config.domain"}), 400

            site_name = name.replace(".", "-").replace(" ", "-")[:64]
            if not site_name:
                return jsonify({"success": False, "error": "Invalid name"}), 400

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM domains WHERE domain_name = ?", (domain,))
            if cursor.fetchone():
                conn.close()
                return jsonify({"success": False, "error": f"Domain {domain} already in use"}), 400
            cursor.execute("SELECT 1 FROM wordpress_docker_sites WHERE domain = ?", (domain,))
            if cursor.fetchone():
                conn.close()
                return jsonify({"success": False, "error": f"Domain {domain} already in use"}), 400
            conn.close()

            result = wp_docker_create_site(site_name, domain, files)

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO domains (domain_name, port, app_name, status) VALUES (?, ?, ?, 'active')",
                (domain, result["port"], site_name),
            )
            cursor.execute(
                "INSERT INTO deployment_logs (domain_name, action, status, message) VALUES (?, 'wordpress_docker_deploy', 'success', ?)",
                (domain, f"WordPress Docker deployed: {site_name}"),
            )
            conn.commit()
            conn.close()

            return jsonify({
                "success": True,
                "message": "WordPress deployed successfully",
                "site_name": result.get("site_name", site_name),
                "url": result["url"],
                "domain": result["url"],
                "port": result["port"],
                "admin_url": result["admin_url"],
            })
        except Exception as e:
            app.logger.exception("WordPress Docker deploy failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # GET: List WordPress Docker sites
    # ============================================================
    @app.route("/api/deploy/wordpress", methods=["GET"])
    def list_wordpress_docker_sites():
        """List WordPress sites deployed as Docker containers."""
        try:
            sites = wp_docker_list_sites()
            return jsonify({"success": True, "sites": sites})
        except Exception as e:
            app.logger.error("List WordPress Docker sites: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/deploy/wordpress/<site_name>", methods=["DELETE"])
    def delete_wordpress_docker_site(site_name):
        """Remove a WordPress Docker site (containers, nginx, files, DB entry)."""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT domain FROM wordpress_docker_sites WHERE site_name = ?", (site_name,))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return jsonify({"success": False, "error": "Site not found"}), 404
            domain = row[0]
            wp_docker_delete_site(site_name, domain)
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM domains WHERE domain_name = ? AND app_name = ?", (domain, site_name))
            cursor.execute(
                "INSERT INTO deployment_logs (domain_name, action, status, message) VALUES (?, 'wordpress_docker_delete', 'success', ?)",
                (domain, f"WordPress Docker removed: {site_name}"),
            )
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": f"Site {site_name} removed"})
        except Exception as e:
            app.logger.exception("Delete WordPress Docker site failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # POST: Import database (mirror) for WordPress Docker site
    # ============================================================
    @app.route("/api/deploy/wordpress/<site_name>/import", methods=["POST"])
    def import_wordpress_database(site_name):
        """Import a SQL dump to mirror a WordPress site. Form: dump=file, source_url=, target_url= (or target_domain=)."""
        try:
            if "dump" not in request.files:
                return jsonify({"success": False, "error": "Missing 'dump' file"}), 400
            f = request.files["dump"]
            if not f.filename or not f.filename.lower().endswith(".sql"):
                return jsonify({"success": False, "error": "Upload a .sql file"}), 400
            source_url = (request.form.get("source_url") or "").strip() or None
            target_url = (request.form.get("target_url") or "").strip()
            target_domain = (request.form.get("target_domain") or "").strip()
            if not target_url and target_domain:
                target_url = f"http://{target_domain}"
            if not target_url:
                target_url = None
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
                f.save(tmp.name)
                tmp_path = Path(tmp.name)
            try:
                wp_docker_import_db(site_name, tmp_path, source_url=source_url, target_url=target_url)
            finally:
                tmp_path.unlink(missing_ok=True)
            return jsonify({"success": True, "message": "Database imported"})
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            app.logger.exception("WordPress import failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # GET: List all Node.js/Next.js sites
    # ============================================================
    @app.route("/api/deploy/nodejs", methods=["GET"])
    def list_nodejs_sites():
        """Returns a JSON list of all deployed Node.js/Next.js applications"""
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Fetch all processes
            cursor.execute("SELECT id, name, port, status FROM processes")
            process_rows = cursor.fetchall()

            # Fetch all domains mapped by app_name
            cursor.execute(
                "SELECT domain_name, app_name, ssl_enabled, status FROM domains"
            )
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
    # GET: Fetch info about specific site
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
                        app.logger.info(
                            f"Removing nginx enabled site: {nginx_enabled_conf}"
                        )
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
