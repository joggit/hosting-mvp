"""Port checking utilities"""
import socket

def check_port_available(port):
    """Check if a port is available"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result != 0

def find_available_ports(start_port, count):
    """Find N available ports starting from start_port"""
    available = []
    port = start_port
    
    while len(available) < count and port < 65535:
        if check_port_available(port):
            available.append(port)
        port += 1
    
    return available
