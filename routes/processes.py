"""Process management endpoints"""
from flask import jsonify
from services.database import get_db

def register_routes(app):
    """Register process-related routes"""
    
    @app.route('/api/processes')
    def list_processes():
        """List all processes"""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT name, port, pid, status FROM processes')
            
            processes = [{
                "name": r[0],
                "port": r[1],
                "pid": r[2],
                "status": r[3]
            } for r in cursor.fetchall()]
            
            conn.close()
            return jsonify({"success": True, "processes": processes})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
