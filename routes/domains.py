"""Domain management endpoints"""
from flask import jsonify, request
from services.database import get_db
from services.port_checker import find_available_ports

def register_routes(app):
    """Register domain-related routes"""
    
    @app.route('/api/domains')
    def list_domains():
        """List all domains"""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT domain_name, port, app_name, ssl_enabled, status, created_at FROM domains')
            
            domains = [{
                "domain_name": r[0],
                "port": r[1],
                "app_name": r[2],
                "ssl_enabled": bool(r[3]),
                "status": r[4],
                "created_at": r[5]
            } for r in cursor.fetchall()]
            
            conn.close()
            return jsonify({"success": True, "domains": domains, "count": len(domains)})
        except Exception as e:
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
            return jsonify({"success": False, "error": str(e)}), 500
