"""
PM2 Process Management Routes
"""
from flask import jsonify
import subprocess
import json

def register_routes(app):
    """Register PM2 management routes"""
    
    @app.route('/api/pm2/list', methods=['GET'])
    def pm2_list():
        """List all PM2 processes"""
        try:
            result = subprocess.run(
                ['pm2', 'jlist'],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                processes = json.loads(result.stdout)
                return jsonify({
                    "success": True,
                    "processes": processes
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "Failed to get PM2 process list"
                }), 500
                
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route('/api/pm2/<process_name>/restart', methods=['POST'])
    def pm2_restart(process_name):
        """Restart a PM2 process"""
        try:
            result = subprocess.run(
                ['pm2', 'restart', process_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return jsonify({
                    "success": True,
                    "message": f"Process {process_name} restarted"
                })
            else:
                return jsonify({
                    "success": False,
                    "error": result.stderr
                }), 500
                
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route('/api/pm2/<process_name>/stop', methods=['POST'])
    def pm2_stop(process_name):
        """Stop a PM2 process"""
        try:
            result = subprocess.run(
                ['pm2', 'stop', process_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return jsonify({
                    "success": True,
                    "message": f"Process {process_name} stopped"
                })
            else:
                return jsonify({
                    "success": False,
                    "error": result.stderr
                }), 500
                
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    @app.route('/api/pm2/<process_name>/delete', methods=['DELETE'])
    def pm2_delete(process_name):
        """Delete a PM2 process"""
        try:
            result = subprocess.run(
                ['pm2', 'delete', process_name],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                subprocess.run(['pm2', 'save'], capture_output=True)
                return jsonify({
                    "success": True,
                    "message": f"Process {process_name} deleted"
                })
            else:
                return jsonify({
                    "success": False,
                    "error": result.stderr
                }), 500
                
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
