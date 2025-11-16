"""Health and status endpoints"""
from flask import jsonify
from datetime import datetime
from services.database import get_db

def register_routes(app):
    """Register health-related routes"""
    
    @app.route('/api/health')
    def health():
        return jsonify({
            "status": "healthy",
            "version": "1.0.0-mvp",
            "timestamp": datetime.utcnow().isoformat()
        })
    
    @app.route('/api/status')
    def status():
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM domains WHERE status = "active"')
            domain_count = cursor.fetchone()[0]
            conn.close()
            
            return jsonify({
                "success": True,
                "domain_count": domain_count,
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
