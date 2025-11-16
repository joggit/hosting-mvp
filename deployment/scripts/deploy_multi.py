#!/usr/bin/env python3
"""
Deploy to multiple servers
Usage: python3 deploy_multi.py --repo URL server1 server2 server3
"""
import argparse
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

def deploy_to_server(server, repo_url, branch='main'):
    """Deploy to a single server"""
    print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")
    print(f"{Colors.BLUE}Deploying to: {server}{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")
    
    try:
        # Copy deployment script to server
        script_path = Path(__file__).parent / 'deploy.py'
        subprocess.run(
            f'scp {script_path} root@{server}:/tmp/',
            shell=True,
            check=True
        )
        
        # Run deployment
        result = subprocess.run(
            f'ssh root@{server} "python3 /tmp/deploy.py {repo_url} --branch {branch}"',
            shell=True,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"{Colors.GREEN}✅ {server} - SUCCESS{Colors.NC}\n")
            return (server, True, None)
        else:
            print(f"{Colors.RED}❌ {server} - FAILED{Colors.NC}")
            print(result.stderr)
            return (server, False, result.stderr)
    
    except Exception as e:
        print(f"{Colors.RED}❌ {server} - ERROR: {e}{Colors.NC}\n")
        return (server, False, str(e))

def main():
    parser = argparse.ArgumentParser(description='Deploy to multiple servers')
    parser.add_argument('--repo', required=True, help='Git repository URL')
    parser.add_argument('--branch', default='main', help='Git branch')
    parser.add_argument('--parallel', type=int, default=3, help='Number of parallel deployments')
    parser.add_argument('servers', nargs='+', help='Server addresses')
    
    args = parser.parse_args()
    
    print(f"{Colors.GREEN}Deploying to {len(args.servers)} servers...{Colors.NC}")
    print(f"Repository: {args.repo}")
    print(f"Branch: {args.branch}")
    print()
    
    # Deploy to servers in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = {
            executor.submit(deploy_to_server, server, args.repo, args.branch): server
            for server in args.servers
        }
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
    
    # Print summary
    print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")
    print(f"{Colors.BLUE}Deployment Summary{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 50}{Colors.NC}")
    
    successful = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    
    print(f"{Colors.GREEN}✅ Successful: {len(successful)}{Colors.NC}")
    for server, _, _ in successful:
        print(f"   - {server}")
    
    if failed:
        print(f"\n{Colors.RED}❌ Failed: {len(failed)}{Colors.NC}")
        for server, _, error in failed:
            print(f"   - {server}: {error}")
        sys.exit(1)

if __name__ == '__main__':
    main()
