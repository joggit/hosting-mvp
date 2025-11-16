"""Logging endpoints"""
from flask import jsonify, request
from services.database import get_db

def register_routes(app):
    """Register log-related routes"""
    
    @app.route('/api/logs')
    def get_logs():
        """Get deployment logs"""
        try:
            limit = request.args.get('limit', 100, type=int)
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT domain_name, action, status, message, created_at
                FROM deployment_logs
                ORDER BY created_at DESC LIMIT ?
            ''', (limit,))
            
            logs = [{
                "domain_name": r[0],
                "action": r[1],
                "status": r[2],
                "message": r[3],
                "created_at": r[4]
            } for r in cursor.fetchall()]
            
            conn.close()
            return jsonify({"success": True, "logs": logs})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
