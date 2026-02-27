"""
Deployment endpoints
Handles Node.js/Next.js and WordPress Docker deployment
"""

import os
import subprocess
import shutil
import json
import tempfile
import logging
from pathlib import Path
from services.database import get_db
from services.port_checker import find_available_ports
from services.pages import create_pages_for_site
from services.wordpress_docker import (
    create_site as wp_docker_create_site,
    list_sites as wp_docker_list_sites,
    delete_site as wp_docker_delete_site,
    import_site_database as wp_docker_import_db,
    set_theme_option,
)
from config.settings import CONFIG
from flask import request, jsonify

logger = logging.getLogger(__name__)


def _post_deploy_fixes(site_name: str, domain: str, options: dict, app_logger):
    """
    Reapply WordPress theme options after a database import via wp eval-file.

    Even with wp search-replace (correct serialisation handling), some Redux
    framework options store nested arrays as a single blob where inner URL
    references may not be fully updated. Rewriting via eval-file guarantees
    clean, correctly serialised data.

    Only called when post_deploy_options is passed in the import request.
    """
    if not options:
        return

    app_logger.info(f"Applying post-deploy theme fixes for {site_name}")
    for option_name, values in options.items():
        try:
            set_theme_option(site_name, option_name, values)
            app_logger.info(f"  ✅ Fixed option: {option_name}")
        except Exception as e:
            app_logger.warning(f"  ⚠️  Could not fix {option_name}: {e}")

    container = f"{site_name}-wordpress"
    for wp_cmd in ["cache flush", "elementor flush-css", "rewrite flush"]:
        subprocess.run(
            f"docker exec {container} wp {wp_cmd} --allow-root",
            shell=True,
            capture_output=True,
        )
    app_logger.info("  ✅ Caches flushed")


def register_routes(app):
    """Register deployment-related routes"""

    # ============================================================
    # POST: Deploy Node.js / Next.js
    # ============================================================
    @app.route("/api/deploy/nodejs", methods=["POST"])
    def deploy_nodejs():
        """Deploy a Node.js/Next.js application"""
        try:
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

            # ── Step 1: Validate ──────────────────────────────────────────────
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

            app.logger.info(
                f"🚀 Starting deployment for {site_name} ({len(project_files)} files)"
            )

            cleaned_name = site_name.replace("-", "").replace("_", "").replace(".", "")
            if not cleaned_name.isalnum():
                return (
                    jsonify(
                        {"success": False, "error": f"Invalid site name '{site_name}'"}
                    ),
                    400,
                )

            # ── Step 2: Domain check ──────────────────────────────────────────
            domain = None
            if domain_config:
                domain = (domain_config.get("domain") or "").lower().strip() or None
                if domain:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT COUNT(*) FROM domains WHERE domain_name = ?", (domain,)
                    )
                    exists = cursor.fetchone()[0] > 0
                    conn.close()
                    if exists:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Domain {domain} already exists",
                                }
                            ),
                            400,
                        )
                    app.logger.info(f"✅ Domain {domain} is available")

            # ── Step 3: Fix package.json and next.config.js ───────────────────
            if "package.json" in project_files:
                try:
                    package_data = json.loads(project_files["package.json"])
                    scripts = package_data.setdefault("scripts", {})
                    scripts.setdefault("build", "next build")
                    scripts.setdefault("start", "next start")
                    project_files["package.json"] = json.dumps(package_data, indent=2)
                except json.JSONDecodeError as e:
                    return (
                        jsonify(
                            {"success": False, "error": "Invalid package.json format"}
                        ),
                        400,
                    )

            safe_next_config = """/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  compress: true,
};
module.exports = nextConfig;"""

            if (
                "next.config.js" not in project_files
                and "next.config.mjs" not in project_files
            ):
                project_files["next.config.js"] = safe_next_config
            else:
                config_key = (
                    "next.config.js"
                    if "next.config.js" in project_files
                    else "next.config.mjs"
                )
                if "serverExternalPackages" in project_files[config_key]:
                    app.logger.warning(
                        "Replacing next.config: serverExternalPackages requires Next.js 15+"
                    )
                    project_files[config_key] = safe_next_config

            # ── Step 4: Port allocation ───────────────────────────────────────
            allocated_port = deploy_config.get("port")
            if not allocated_port:
                available_ports = find_available_ports(3000, 1)
                allocated_port = available_ports[0] if available_ports else 3000
            app.logger.info(f"Allocated port: {allocated_port}")

            # ── Step 5: Write files ───────────────────────────────────────────
            app_dir = f"{CONFIG['web_root']}/{domain or site_name}"
            if os.path.exists(app_dir):
                try:
                    shutil.rmtree(app_dir)
                except Exception as e:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Cannot clean existing directory: {str(e)}",
                            }
                        ),
                        400,
                    )

            os.makedirs(app_dir, exist_ok=True)
            for file_path, content in project_files.items():
                full_path = os.path.join(app_dir, file_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(content)
            app.logger.info(f"Written {len(project_files)} files to {app_dir}")

            # ── Step 6: Install and build ─────────────────────────────────────
            if "package.json" in project_files:
                pkg_manager = "pnpm" if shutil.which("pnpm") else "npm"
                app.logger.info(f"Running {pkg_manager} install...")

                result = subprocess.run(
                    [pkg_manager, "install"],
                    cwd=app_dir,
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
                if result.returncode != 0:
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
                app.logger.info("✅ Install complete")

                try:
                    package_data = json.loads(project_files.get("package.json", "{}"))
                    if "build" in package_data.get("scripts", {}):
                        app.logger.info(f"Running {pkg_manager} build...")
                        build_result = subprocess.run(
                            [pkg_manager, "run", "build"],
                            cwd=app_dir,
                            capture_output=True,
                            text=True,
                            timeout=900,
                        )
                        if build_result.returncode != 0:
                            shutil.rmtree(app_dir, ignore_errors=True)
                            return (
                                jsonify(
                                    {
                                        "success": False,
                                        "error": "Build failed",
                                        "stdout": build_result.stdout[-4000:],
                                        "stderr": build_result.stderr[-4000:],
                                    }
                                ),
                                500,
                            )
                        app.logger.info("✅ Build complete")
                except subprocess.TimeoutExpired:
                    app.logger.warning("Build timed out — continuing anyway")
                except Exception as build_error:
                    app.logger.warning(
                        f"Build error (continuing anyway): {build_error}"
                    )

            # ── Step 7: Start with PM2 ────────────────────────────────────────
            process_manager = "simple"
            pm2_path = shutil.which("pm2") or "/usr/bin/pm2"

            if os.path.exists(pm2_path):
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
                            "exec_mode": "fork",  # CRITICAL for Next.js — cluster mode breaks it
                            "autorestart": True,
                            "watch": False,
                            "max_memory_restart": "1G",
                        }
                    ]
                }
                ecosystem_path = os.path.join(app_dir, "ecosystem.config.json")
                with open(ecosystem_path, "w") as f:
                    json.dump(ecosystem, f, indent=2)

                pm2_result = subprocess.run(
                    [pm2_path, "start", ecosystem_path], capture_output=True, text=True
                )
                if pm2_result.returncode == 0:
                    process_manager = "pm2"
                    subprocess.run([pm2_path, "save"], capture_output=True)
                    app.logger.info("✅ Started with PM2")
                else:
                    app.logger.warning(
                        f"PM2 start failed: {pm2_result.stderr} — falling back to background process"
                    )

            if process_manager == "simple":
                subprocess.Popen(
                    ["npm", "start"],
                    cwd=app_dir,
                    env={**os.environ, "PORT": str(allocated_port)},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                app.logger.info("✅ Started as background process")

            # ── Step 8: Nginx vhost ───────────────────────────────────────────
            if domain:
                nginx_config = f"""server {{
    listen 80;
    server_name {domain} www.{domain};

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
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
}}"""
                try:
                    nginx_path = f"/etc/nginx/sites-available/{domain}"
                    enabled_path = f"/etc/nginx/sites-enabled/{domain}"
                    with open("/tmp/nginx_config.tmp", "w") as f:
                        f.write(nginx_config)
                    subprocess.run(
                        ["sudo", "cp", "/tmp/nginx_config.tmp", nginx_path], check=True
                    )
                    os.remove("/tmp/nginx_config.tmp")
                    subprocess.run(["sudo", "rm", "-f", enabled_path], check=False)
                    subprocess.run(
                        ["sudo", "ln", "-sf", nginx_path, enabled_path], check=True
                    )
                    test = subprocess.run(
                        ["sudo", "nginx", "-t"], capture_output=True, text=True
                    )
                    if test.returncode == 0:
                        subprocess.run(["sudo", "systemctl", "reload", "nginx"])
                        app.logger.info("✅ Nginx configured and reloaded")
                    else:
                        app.logger.error(f"Nginx config test failed: {test.stderr}")
                except Exception as nginx_error:
                    app.logger.error(f"Could not configure nginx: {nginx_error}")

            # ── Step 9: Save to database ──────────────────────────────────────
            conn = get_db()
            cursor = conn.cursor()

            if domain:
                cursor.execute(
                    "SELECT id FROM domains WHERE domain_name = ?", (domain,)
                )
                if cursor.fetchone():
                    cursor.execute(
                        "UPDATE domains SET app_name=?, ssl_enabled=?, status='active' WHERE domain_name=?",
                        (site_name, False, domain),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO domains (domain_name, app_name, ssl_enabled, status) VALUES (?,?,?,'active')",
                        (domain, site_name, False),
                    )

            cursor.execute("SELECT id FROM processes WHERE name = ?", (site_name,))
            if cursor.fetchone():
                cursor.execute(
                    "UPDATE processes SET port=?, status='running' WHERE name=?",
                    (allocated_port, site_name),
                )
            else:
                cursor.execute(
                    "INSERT INTO processes (name, port, status) VALUES (?,?,?)",
                    (site_name, allocated_port, "running"),
                )

            cursor.execute(
                "INSERT INTO deployment_logs (domain_name, action, status, message) VALUES (?,?,?,?)",
                (domain or site_name, "deploy", "success", f"Deployed {site_name}"),
            )
            conn.commit()
            conn.close()
            app.logger.info("✅ Database updated")

            # ── Create pages ──────────────────────────────────────────────────
            selected_pages = data.get("selectedPages", [])
            if selected_pages and domain:
                create_pages_for_site(domain, selected_pages, site_name)

            # ── Step 10: Response ─────────────────────────────────────────────
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

            app.logger.info(
                f"✅ Deployment complete: {site_name} → {domain or f'localhost:{allocated_port}'}"
            )
            return jsonify(response_data)

        except Exception as e:
            app.logger.error(f"Deployment error: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500

    # ═══════════════════════════════════════════════════════════════════════════════
    # ADD to routes/deployment.py inside register_routes(app)
    # ═══════════════════════════════════════════════════════════════════════════════
    #
    # Add this BEFORE the existing POST /api/deploy/wordpress route so Flask matches
    # /register first (more specific path).
    # ───────────────────────────────────────────────────────────────────────────────

    @app.route("/api/deploy/wordpress/register", methods=["POST"])
    def register_wordpress_site():
        """
        Register a new WordPress site deployed via Docker Hub image.

        Unlike POST /api/deploy/wordpress (which requires theme file uploads),
        this endpoint sets up the full server-side infrastructure using an image
        that already exists on Docker Hub.

        JSON body:
          site_name           — site identifier (container prefix)
          domain              — production domain
          port                — production container port
          db_name             — MySQL database name
          db_user             — MySQL user
          db_password         — MySQL password
          db_root_password    — MySQL root password (optional — auto-generated if omitted)
          dockerhub_username  — Docker Hub account (optional, default: dockster1)
          compose_content     — docker-compose.prod.yml content (optional — auto-generated if omitted)
        """
        try:
            data = request.get_json(force=True) or {}

            site_name = (data.get("site_name") or "").strip()
            domain = (data.get("domain") or "").strip().lower()
            port = data.get("port")
            db_name = (data.get("db_name") or "wordpress").strip()
            db_user = (data.get("db_user") or "wpuser").strip()
            db_password = (data.get("db_password") or "").strip()
            db_root_password = (data.get("db_root_password") or "").strip()
            dockerhub = (data.get("dockerhub_username") or "dockster1").strip()
            compose_content = data.get("compose_content")  # optional

            # Validate required fields
            missing = [
                f
                for f, v in [
                    ("site_name", site_name),
                    ("domain", domain),
                    ("port", port),
                    ("db_password", db_password),
                ]
                if not v
            ]
            if missing:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Missing required fields: {', '.join(missing)}",
                        }
                    ),
                    400,
                )

            try:
                port = int(port)
            except (TypeError, ValueError):
                return (
                    jsonify({"success": False, "error": "port must be an integer"}),
                    400,
                )

            # Auto-generate root password if not provided
            if not db_root_password:
                import secrets, string

                chars = string.ascii_letters + string.digits + "@#%^*-_=+."
                db_root_password = "".join(secrets.choice(chars) for _ in range(32))

            from services.wordpress_docker import register_site

            result = register_site(
                site_name=site_name,
                domain=domain,
                port=port,
                db_name=db_name,
                db_user=db_user,
                db_password=db_password,
                db_root_password=db_root_password,
                dockerhub_username=dockerhub,
                compose_content=compose_content,
            )

            return jsonify(
                {
                    "success": True,
                    "message": f"Site registered: {domain}",
                    "site_name": result["site_name"],
                    "domain": result["domain"],
                    "port": result["port"],
                    "url": result["url"],
                    "admin_url": result["admin_url"],
                }
            )

        except Exception as e:
            app.logger.exception("Site registration failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # POST: Deploy WordPress (Docker)
    # ============================================================
    @app.route("/api/deploy/wordpress", methods=["POST"])
    def deploy_wordpress():
        """Deploy a WordPress theme to a new Docker stack; nginx on host proxies by domain."""
        try:
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
            except Exception as e:
                return (
                    jsonify({"success": False, "error": f"Invalid JSON: {str(e)}"}),
                    400,
                )
            if not data:
                return (
                    jsonify({"success": False, "error": "Request body is empty"}),
                    400,
                )

            name = data.get("name")
            files = data.get("files")
            domain = (
                ((data.get("domain_config") or {}).get("domain") or "").strip().lower()
            )
            theme_slug = (data.get("theme_slug") or "").strip() or None

            if not name or not files:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Missing required fields: name and files",
                        }
                    ),
                    400,
                )
            if not domain:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Missing domain in domain_config.domain",
                        }
                    ),
                    400,
                )

            site_name = (
                domain.replace(".", "-").replace(" ", "-").replace(":", "-")[:64]
            )

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM domains WHERE domain_name = ?", (domain,))
            if cursor.fetchone():
                conn.close()
                return (
                    jsonify(
                        {"success": False, "error": f"Domain {domain} already in use"}
                    ),
                    400,
                )
            cursor.execute(
                "SELECT 1 FROM wordpress_docker_sites WHERE domain = ?", (domain,)
            )
            if cursor.fetchone():
                conn.close()
                return (
                    jsonify(
                        {"success": False, "error": f"Domain {domain} already in use"}
                    ),
                    400,
                )
            conn.close()

            result = wp_docker_create_site(
                site_name, domain, files, theme_slug=theme_slug
            )

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO domains (domain_name, port, app_name, status) VALUES (?,?,?,'active')",
                (domain, result["port"], site_name),
            )
            cursor.execute(
                "INSERT INTO deployment_logs (domain_name, action, status, message) VALUES (?,?,?,?)",
                (
                    domain,
                    "wordpress_docker_deploy",
                    "success",
                    f"WordPress Docker deployed: {site_name}",
                ),
            )
            conn.commit()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "message": "WordPress deployed successfully",
                    "site_name": result.get("site_name", site_name),
                    "url": result["url"],
                    "domain": result["url"],
                    "port": result["port"],
                    "admin_url": result["admin_url"],
                }
            )

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
            return jsonify({"success": True, "sites": wp_docker_list_sites()})
        except Exception as e:
            app.logger.error("List WordPress Docker sites: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # DELETE: Remove a WordPress Docker site
    # ============================================================
    @app.route("/api/deploy/wordpress/<site_name>", methods=["DELETE"])
    def delete_wordpress_docker_site(site_name):
        """Remove a WordPress Docker site (containers, nginx, files, DB entry)."""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT domain FROM wordpress_docker_sites WHERE site_name = ?",
                (site_name,),
            )
            row = cursor.fetchone()
            conn.close()
            if not row:
                return jsonify({"success": False, "error": "Site not found"}), 404

            domain = row[0]
            wp_docker_delete_site(site_name, domain)

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM domains WHERE domain_name = ? AND app_name = ?",
                (domain, site_name),
            )
            cursor.execute(
                "INSERT INTO deployment_logs (domain_name, action, status, message) VALUES (?,?,?,?)",
                (
                    domain,
                    "wordpress_docker_delete",
                    "success",
                    f"WordPress Docker removed: {site_name}",
                ),
            )
            conn.commit()
            conn.close()
            return jsonify({"success": True, "message": f"Site {site_name} removed"})

        except Exception as e:
            app.logger.exception("Delete WordPress Docker site failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # POST: Import database for WordPress Docker site
    # ============================================================
    @app.route("/api/deploy/wordpress/<site_name>/import", methods=["POST"])
    def import_wordpress_database(site_name):
        """
        Import a SQL dump to mirror a WordPress site.

        Form fields:
          dump                 — .sql file (required)
          source_url           — URL to replace FROM (e.g. http://localhost:8082)
          target_url           — URL to replace TO   (e.g. http://mysite.com)
          target_domain        — Alternative to target_url — domain only
          theme_slug           — Theme to activate after import
          post_deploy_options  — JSON string of theme options to rewrite after import
                                 via wp eval-file. Handles nested Redux option arrays
                                 that wp search-replace may miss.
                                 Example:
                                   '{"donatm_theme_options": {"header_logo": {"url": "..."}}}'

        URL replacement uses wp search-replace inside the container — the only
        correct approach for WordPress serialised PHP arrays.
        """
        try:
            if "dump" not in request.files:
                return jsonify({"success": False, "error": "Missing 'dump' file"}), 400

            f = request.files["dump"]
            if not f.filename or not f.filename.lower().endswith(".sql"):
                return jsonify({"success": False, "error": "Upload a .sql file"}), 400

            source_url = (request.form.get("source_url") or "").strip() or None
            target_url = (request.form.get("target_url") or "").strip() or None
            target_domain = (request.form.get("target_domain") or "").strip() or None
            theme_slug = (request.form.get("theme_slug") or "").strip() or None

            post_deploy_options = {}
            raw = (request.form.get("post_deploy_options") or "").strip()
            if raw:
                try:
                    post_deploy_options = json.loads(raw)
                except json.JSONDecodeError:
                    app.logger.warning("Invalid post_deploy_options JSON — skipping")

            if not target_url and target_domain:
                target_url = f"http://{target_domain}"

            with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
                f.save(tmp.name)
                tmp_path = Path(tmp.name)

            try:
                wp_docker_import_db(
                    site_name,
                    tmp_path,
                    source_url=source_url,
                    target_url=target_url,
                    theme_slug=theme_slug,
                )
            finally:
                tmp_path.unlink(missing_ok=True)

            if post_deploy_options:
                domain = target_domain or (
                    target_url.replace("https://", "").replace("http://", "")
                    if target_url
                    else None
                )
                _post_deploy_fixes(site_name, domain, post_deploy_options, app.logger)

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
            cursor.execute("SELECT id, name, port, status FROM processes")
            process_rows = cursor.fetchall()
            cursor.execute(
                "SELECT domain_name, app_name, ssl_enabled, status FROM domains"
            )
            domain_rows = cursor.fetchall()
            conn.close()

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

            pm2_path = shutil.which("pm2") or "/usr/bin/pm2"
            pm2_available = os.path.exists(pm2_path)
            site_list = []

            for proc_id, site_name, port, proc_status in process_rows:
                app_dir = Path(CONFIG["web_root"]) / site_name
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

                site_list.append(
                    {
                        "site_name": site_name,
                        "port": port,
                        "process_status": proc_status,
                        "files_path": str(app_dir),
                        "exists_on_disk": app_dir.exists(),
                        "pm2": {"available": pm2_available, "running": pm2_running},
                        "domains": domains_by_app.get(site_name),
                    }
                )

            return jsonify({"success": True, "sites": site_list})

        except Exception as e:
            app.logger.error(f"Error listing NodeJS sites: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # ============================================================
    # GET: Fetch info about specific Node.js site
    # ============================================================
    @app.route("/api/deploy/nodejs/<site_name>", methods=["GET"])
    def get_nodejs_site(site_name):
        """Return information about a deployed Node.js/Next.js site"""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT port, status FROM processes WHERE name = ?", (site_name,)
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
            cursor.execute(
                "SELECT domain_name, ssl_enabled, status FROM domains WHERE app_name = ?",
                (site_name,),
            )
            domain_row = cursor.fetchone()
            conn.close()

            domain_info = None
            nginx_available = nginx_enabled = False
            if domain_row:
                domain_name, ssl_enabled, domain_status = domain_row
                domain_info = {
                    "domain_name": domain_name,
                    "ssl_enabled": bool(ssl_enabled),
                    "status": domain_status,
                    "url": f"http://{domain_name}",
                }
                nginx_available = Path(
                    f"/etc/nginx/sites-available/{domain_name}"
                ).exists()
                nginx_enabled = Path(f"/etc/nginx/sites-enabled/{domain_name}").exists()

            app_dir = Path(CONFIG["web_root"]) / site_name
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
                    pass

            return jsonify(
                {
                    "success": True,
                    "site_name": site_name,
                    "port": port,
                    "process_status": proc_status,
                    "app_dir": str(app_dir),
                    "app_dir_exists": app_dir.exists(),
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
        """Stop PM2, remove nginx vhost, delete files and DB entries."""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, port FROM processes WHERE name = ?", (site_name,)
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
            cursor.execute(
                "SELECT id, domain_name FROM domains WHERE app_name = ?", (site_name,)
            )
            domain_row = cursor.fetchone()
            domain_id = domain_name = None
            if domain_row:
                domain_id, domain_name = domain_row

            app.logger.info(
                f"🗑 Deleting {site_name} (port {port}, domain {domain_name})"
            )

            # Stop PM2
            pm2_path = shutil.which("pm2") or "/usr/bin/pm2"
            if os.path.exists(pm2_path):
                try:
                    subprocess.run(
                        [pm2_path, "stop", site_name], capture_output=True, text=True
                    )
                    subprocess.run(
                        [pm2_path, "delete", site_name], capture_output=True, text=True
                    )
                    subprocess.run([pm2_path, "save"], capture_output=True, text=True)
                    app.logger.info("✅ PM2 process removed")
                except Exception as e:
                    app.logger.warning(f"PM2 cleanup failed (non-fatal): {e}")

            # Remove nginx vhost
            if domain_name:
                try:
                    for path in [
                        f"/etc/nginx/sites-enabled/{domain_name}",
                        f"/etc/nginx/sites-available/{domain_name}",
                    ]:
                        subprocess.run(["sudo", "rm", "-f", path], check=False)
                    test = subprocess.run(
                        ["sudo", "nginx", "-t"], capture_output=True, text=True
                    )
                    if test.returncode == 0:
                        subprocess.run(
                            ["sudo", "systemctl", "reload", "nginx"],
                            capture_output=True,
                        )
                        app.logger.info("✅ Nginx vhost removed")
                    else:
                        app.logger.error(
                            f"Nginx test failed after deletion: {test.stderr}"
                        )
                except Exception as e:
                    app.logger.warning(f"Nginx cleanup failed (non-fatal): {e}")

            # Delete files
            app_dir = Path(CONFIG["web_root"]) / site_name
            if app_dir.exists():
                try:
                    shutil.rmtree(app_dir)
                    app.logger.info("✅ App directory removed")
                except Exception as e:
                    app.logger.warning(f"File cleanup failed (non-fatal): {e}")

            # Clean database
            try:
                if domain_id:
                    cursor.execute("DELETE FROM domains WHERE id = ?", (domain_id,))
                cursor.execute("DELETE FROM processes WHERE id = ?", (process_id,))
                cursor.execute(
                    "INSERT INTO deployment_logs (domain_name, action, status, message) VALUES (?,?,?,?)",
                    (
                        domain_name or site_name,
                        "delete",
                        "success",
                        f"Deleted {site_name}",
                    ),
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

            app.logger.info(f"✅ Deletion complete: {site_name}")
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
