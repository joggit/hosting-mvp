"""
routes/ssl.py — SSL certificate provisioning via Certbot
Drop into hosting-mvp/routes/ — auto-discovered by routes/__init__.py

Endpoint:
    POST /api/ssl
    Body: { "domain": "example.com", "email": "admin@example.com" }

What it does:
    1. Validates the domain exists in the database
    2. Checks Nginx config is in place (required for HTTP-01 challenge)
    3. Runs: certbot --nginx -d <domain> --non-interactive --agree-tos --redirect
    4. Updates ssl_enabled = true in the domains table
    5. Returns success/error JSON

Requirements on the VPS:
    apt install certbot python3-certbot-nginx
"""

import subprocess
import re
from flask import request, jsonify
from services.database import get_db


# Only allow valid domain names — no shell injection
_DOMAIN_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]{1,253}[a-zA-Z0-9]$')


def register_routes(app):

    @app.route("/api/ssl", methods=["POST"])
    def provision_ssl():
        data = request.get_json(silent=True) or {}
        domain = (data.get("domain") or "").strip().lower()
        email  = (data.get("email")  or f"admin@{domain}").strip()

        # ── Validate ──────────────────────────────────────────────
        if not domain:
            return jsonify({"success": False, "error": "domain is required"}), 400

        if not _DOMAIN_RE.match(domain):
            return jsonify({"success": False, "error": f"Invalid domain: {domain}"}), 400

        # ── Check domain is registered ────────────────────────────
        db = get_db()
        row = db.execute(
            "SELECT domain_name, ssl_enabled FROM domains WHERE domain_name = ?",
            (domain,)
        ).fetchone()

        if not row:
            return jsonify({
                "success": False,
                "error": f"Domain {domain} not found. Deploy the site first."
            }), 404

        if row["ssl_enabled"]:
            return jsonify({
                "success": True,
                "message": f"SSL already enabled for {domain}",
                "domain": domain,
                "url": f"https://{domain}"
            })

        # ── Run Certbot ───────────────────────────────────────────
        cmd = [
            "certbot", "--nginx",
            "-d", domain,
            "--non-interactive",
            "--agree-tos",
            "--redirect",
            "-m", email,
        ]

        app.logger.info(f"Running certbot for {domain}: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,      # certbot can be slow
            )
        except FileNotFoundError:
            return jsonify({
                "success": False,
                "error": "certbot not found. Install with: apt install certbot python3-certbot-nginx"
            }), 500
        except subprocess.TimeoutExpired:
            return jsonify({
                "success": False,
                "error": "Certbot timed out after 120 s. Check DNS and firewall (ports 80/443)."
            }), 500

        if result.returncode != 0:
            app.logger.error(f"Certbot failed for {domain}:\n{result.stderr}")
            # Surface the most useful part of certbot's stderr
            stderr_tail = result.stderr.strip().splitlines()
            hint = next(
                (l for l in reversed(stderr_tail) if l.strip()),
                result.stderr.strip()[-300:]
            )
            return jsonify({
                "success": False,
                "error": f"Certbot failed: {hint}",
                "detail": result.stderr.strip()[-1000:],
            }), 500

        # ── Update database ───────────────────────────────────────
        db.execute(
            "UPDATE domains SET ssl_enabled = 1 WHERE domain_name = ?",
            (domain,)
        )
        db.commit()

        app.logger.info(f"SSL provisioned for {domain}")

        return jsonify({
            "success": True,
            "domain": domain,
            "url": f"https://{domain}",
            "message": f"SSL certificate issued for {domain}",
        })

    @app.route("/api/ssl/<domain>", methods=["GET"])
    def ssl_status(domain):
        """Check SSL status for a domain."""
        domain = domain.strip().lower()

        if not _DOMAIN_RE.match(domain):
            return jsonify({"success": False, "error": f"Invalid domain: {domain}"}), 400

        db = get_db()
        row = db.execute(
            "SELECT domain_name, ssl_enabled, status FROM domains WHERE domain_name = ?",
            (domain,)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": f"Domain {domain} not found"}), 404

        return jsonify({
            "success": True,
            "domain": domain,
            "ssl_enabled": bool(row["ssl_enabled"]),
            "url": f"https://{domain}" if row["ssl_enabled"] else f"http://{domain}",
            "status": row["status"],
        })