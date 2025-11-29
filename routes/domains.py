"""Domain management endpoints"""
from flask import jsonify, request
from services.database import get_db
from services.port_checker import find_available_ports
import logging
import re

logger = logging.getLogger(__name__)


def validate_domain(domain):
    """Validate domain name format"""
    # Basic domain validation
    pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    return re.match(pattern, domain) is not None


def register_routes(app):
    """Register domain-related routes"""

    @app.route('/api/domains', methods=['GET'])
    def list_domains():
        """List all domains"""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT domain_name, port, app_name, ssl_enabled, status, created_at FROM domains'
            )
            domains = [
                {
                    "domain_name": r[0],
                    "port": r[1],
                    "app_name": r[2],
                    "ssl_enabled": bool(r[3]),
                    "status": r[4],
                    "created_at": r[5],
                }
                for r in cursor.fetchall()
            ]
            conn.close()
            return jsonify({"success": True, "domains": domains, "count": len(domains)})
        except Exception as e:
            logger.error(f"Failed to list domains: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route('/api/domains', methods=['POST'])
    def add_domain():
        """
        Add/register a new domain
        
        Body:
        {
            "domain": "example.com",
            "description": "My domain",
            "ssl_enabled": true
        }
        """
        try:
            data = request.get_json()
            
            if not data or 'domain' not in data:
                return jsonify({
                    "success": False, 
                    "error": "Missing required field: domain"
                }), 400
            
            domain = data['domain'].lower().strip()
            description = data.get('description', '')
            ssl_enabled = data.get('ssl_enabled', False)
            
            # Validate domain format
            if not validate_domain(domain):
                return jsonify({
                    "success": False,
                    "error": f"Invalid domain format: {domain}"
                }), 400
            
            # Check if domain already exists
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute(
                "SELECT domain_name FROM domains WHERE domain_name = ?",
                (domain,)
            )
            
            if cursor.fetchone():
                conn.close()
                return jsonify({
                    "success": False,
                    "error": f"Domain {domain} already exists"
                }), 409
            
            # Insert domain
            cursor.execute(
                """
                INSERT INTO domains 
                (domain_name, port, app_name, ssl_enabled, status, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (domain, None, description or domain, 1 if ssl_enabled else 0, 'registered')
            )
            
            # Log the action
            cursor.execute(
                """
                INSERT INTO deployment_logs 
                (domain_name, action, status, message, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (domain, 'domain_added', 'success', f'Domain {domain} registered')
            )
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Domain registered: {domain}")
            
            return jsonify({
                "success": True,
                "message": f"Domain {domain} registered successfully",
                "domain": {
                    "domain_name": domain,
                    "ssl_enabled": ssl_enabled,
                    "status": "registered",
                    "description": description
                }
            }), 201
            
        except Exception as e:
            logger.error(f"Failed to add domain: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route('/api/domains/<domain_name>', methods=['DELETE'])
    def delete_domain(domain_name):
        """
        Delete/unregister a domain
        
        DELETE /api/domains/example.com
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            # Check if domain exists
            cursor.execute(
                "SELECT domain_name, app_name FROM domains WHERE domain_name = ?",
                (domain_name,)
            )
            
            domain = cursor.fetchone()
            if not domain:
                conn.close()
                return jsonify({
                    "success": False,
                    "error": f"Domain {domain_name} not found"
                }), 404
            
            # Delete domain
            cursor.execute(
                "DELETE FROM domains WHERE domain_name = ?",
                (domain_name,)
            )
            
            # Log the action
            cursor.execute(
                """
                INSERT INTO deployment_logs 
                (domain_name, action, status, message, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (domain_name, 'domain_deleted', 'success', f'Domain {domain_name} unregistered')
            )
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Domain deleted: {domain_name}")
            
            return jsonify({
                "success": True,
                "message": f"Domain {domain_name} deleted successfully"
            })
            
        except Exception as e:
            logger.error(f"Failed to delete domain: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route('/api/domains/<domain_name>', methods=['GET'])
    def get_domain(domain_name):
        """
        Get details for a specific domain
        
        GET /api/domains/example.com
        """
        try:
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT domain_name, port, app_name, ssl_enabled, status, created_at
                FROM domains 
                WHERE domain_name = ?
                """,
                (domain_name,)
            )
            
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                return jsonify({
                    "success": False,
                    "error": f"Domain {domain_name} not found"
                }), 404
            
            return jsonify({
                "success": True,
                "domain": {
                    "domain_name": row[0],
                    "port": row[1],
                    "app_name": row[2],
                    "ssl_enabled": bool(row[3]),
                    "status": row[4],
                    "created_at": row[5]
                }
            })
            
        except Exception as e:
            logger.error(f"Failed to get domain: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route('/api/sites')
    def list_sites():
        """Alias for /api/domains (frontend compatibility)"""
        return list_domains()

    @app.route('/api/check-ports', methods=['POST'])
    def check_ports():
        """Find available ports"""
        try:
            data = request.get_json() or {}
            start_port = data.get('startPort', 3000)
            count = data.get('count', 5)

            available_ports = find_available_ports(start_port, count)

            return jsonify({"success": True, "availablePorts": available_ports})
        except Exception as e:
            logger.error(f"Failed to check ports: {e}")
            return jsonify({"success": False, "error": str(e)}), 500