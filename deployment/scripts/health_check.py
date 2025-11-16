#!/usr/bin/env python3
"""
Check health of deployed servers
Usage: python3 health_check.py server1 server2 server3
"""
import sys
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    NC = '\033[0m'

def check_server(server, port=5000):
    """Check health of a single server"""
    url = f"http://{server}:{port}/api/health"
    
    try:
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            return {
                'server': server,
                'status': 'healthy',
                'version': data.get('version', 'unknown'),
                'timestamp': data.get('timestamp', 'unknown')
            }
        else:
            return {
                'server': server,
                'status': 'unhealthy',
                'code': response.status_code
            }
    except requests.exceptions.RequestException as e:
        return {
            'server': server,
            'status': 'unreachable',
            'error': str(e)
        }

def main():
    parser = argparse.ArgumentParser(description='Check server health')
    parser.add_argument('servers', nargs='+', help='Server addresses')
    parser.add_argument('--port', type=int, default=5000, help='API port')
    
    args = parser.parse_args()
    
    print(f"Checking health of {len(args.servers)} servers...")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    # Check servers in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(
            lambda s: check_server(s, args.port),
            args.servers
        ))
    
    # Print results
    healthy = 0
    unhealthy = 0
    unreachable = 0
    
    for result in results:
        server = result['server']
        status = result['status']
        
        if status == 'healthy':
            print(f"{Colors.GREEN}✅ {server} - HEALTHY{Colors.NC}")
            print(f"   Version: {result.get('version')}")
            healthy += 1
        elif status == 'unhealthy':
            print(f"{Colors.YELLOW}⚠️  {server} - UNHEALTHY (HTTP {result.get('code')}){Colors.NC}")
            unhealthy += 1
        else:
            print(f"{Colors.RED}❌ {server} - UNREACHABLE{Colors.NC}")
            print(f"   Error: {result.get('error')}")
            unreachable += 1
        print()
    
    # Summary
    print("=" * 50)
    print(f"Total: {len(results)} | Healthy: {healthy} | Unhealthy: {unhealthy} | Unreachable: {unreachable}")
    
    if unhealthy > 0 or unreachable > 0:
        sys.exit(1)

if __name__ == '__main__':
    main()
