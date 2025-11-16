"""
Deployment endpoints
Handles Node.js/Next.js application deployment
"""
from flask import request, jsonify
import os
import subprocess
import shutil
from pathlib import Path
from services.database import get_db
from config.settings import CONFIG

def register_routes(app):
    """Register deployment-related routes"""
    
    @app.route('/api/deploy/nodejs', methods=['POST'])
    def deploy_nodejs():
        """
        Deploy a Node.js/Next.js application
        
        Expected JSON:
        {
            "name": "app-name",
            "files": {
                "package.json": "...",
                "app.js": "...",
                ...
            },
            "deployConfig": {
                "port": 3000,
                "env": {}
            }
        }
        """
        try:
            data = request.get_json()
            
            # Validate required fields
            if not data or 'name' not in data or 'files' not in data:
                return jsonify({
                    "success": False,
                    "error": "Missing required fields: name and files"
                }), 400
            
            app_name = data['name']
            files = data['files']
            deploy_config = data.get('deployConfig', {})
            port = deploy_config.get('port', 3000)
            env_vars = deploy_config.get('env', {})
            
            # Validate app name
            if not app_name.replace('-', '').replace('_', '').isalnum():
                return jsonify({
                    "success": False,
                    "error": "Invalid app name. Use only letters, numbers, hyphens, and underscores"
                }), 400
            
            # Create app directory
            app_dir = f"{CONFIG['web_root']}/{app_name}"
            
            # Check if already exists
            if os.path.exists(app_dir):
                return jsonify({
                    "success": False,
                    "error": f"Application '{app_name}' already exists"
                }), 400
            
            # Create directory
            os.makedirs(app_dir, exist_ok=True)
            
            # Write all files
            for file_path, content in files.items():
                full_path = os.path.join(app_dir, file_path)
                
                # Create subdirectories if needed
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                # Write file
                with open(full_path, 'w') as f:
                    f.write(content)
            
            # Install dependencies
            if 'package.json' in files:
                result = subprocess.run(
                    ['npm', 'install'],
                    cwd=app_dir,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode != 0:
                    # Cleanup on failure
                    shutil.rmtree(app_dir)
                    return jsonify({
                        "success": False,
                        "error": "npm install failed",
                        "details": result.stderr
                    }), 500
            
            # Run build if build script exists
            try:
                import json as json_lib
                package_json = json_lib.loads(files.get('package.json', '{}'))
                if 'build' in package_json.get('scripts', {}):
                    subprocess.run(
                        ['npm', 'run', 'build'],
                        cwd=app_dir,
                        capture_output=True,
                        timeout=300
                    )
            except:
                pass
            
            # Start with PM2 (if available) or simple background process
            process_manager = 'simple'
            try:
                # Check for PM2
                pm2_check = subprocess.run(['which', 'pm2'], capture_output=True)
                if pm2_check.returncode == 0:
                    # Start with PM2
                    subprocess.run([
                        'pm2', 'start', '--name', app_name,
                        'npm', '--', 'start'
                    ], cwd=app_dir, capture_output=True)
                    process_manager = 'pm2'
                else:
                    # Start as background process
                    subprocess.Popen(
                        ['npm', 'start'],
                        cwd=app_dir,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
            except Exception as e:
                # Cleanup on failure
                shutil.rmtree(app_dir)
                return jsonify({
                    "success": False,
                    "error": f"Failed to start application: {str(e)}"
                }), 500
            
            # Save to database
            conn = get_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO domains (domain_name, port, app_name, status)
                VALUES (?, ?, ?, 'active')
            """, (app_name, port, app_name))
            
            cursor.execute("""
                INSERT INTO processes (name, port, status)
                VALUES (?, ?, 'running')
            """, (app_name, port))
            
            cursor.execute("""
                INSERT INTO deployment_logs (domain_name, action, status, message)
                VALUES (?, 'deploy', 'success', 'Node.js application deployed')
            """, (app_name,))
            
            conn.commit()
            conn.close()
            
            return jsonify({
                "success": True,
                "site_name": app_name,
                "port": port,
                "process_manager": process_manager,
                "url": f"http://{app_name}",
                "files_path": app_dir,
                "message": "Deployment successful"
            })
            
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
