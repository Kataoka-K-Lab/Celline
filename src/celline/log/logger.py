import logging
import sys
from typing import Optional


class Logger:
    @classmethod
    def build(cls):
        return ""


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance with consistent formatting."""
    logger = logging.getLogger(name or __name__)
    
    if not logger.handlers:
        # Create console handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    
    return logger
