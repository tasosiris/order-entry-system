import logging
from logging.handlers import RotatingFileHandler
import os
import sys

def log_request_response(method: str, endpoint: str, response_status: int, body_length: int):
    """Utility function for consistent API logging"""
    print(f"INFO:root:Request: {method} {endpoint} - Body: Empty")
    print(f"INFO:root:Response: {response_status} - Body length: {body_length} characters")

def setup_logging(log_level=logging.INFO):
    """
    Setup application logging configuration.
    
    Args:
        log_level: The logging level (default: INFO)
    
    Returns:
        The configured logger
    """
    # Create logger
    logger = logging.getLogger("oes")
    logger.setLevel(log_level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(console_handler)
    
    # Try to create a file handler if possible
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=os.path.join(log_dir, 'oes.log'),
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not setup file logging: {e}")
    
    return logger 