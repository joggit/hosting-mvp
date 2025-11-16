"""Logging setup"""
import logging

def setup_logger(name):
    """Setup logger with consistent format"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(name)
