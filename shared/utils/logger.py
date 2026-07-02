"""
ATMS Shared Utilities - Structured Logging
"""
import logging
import sys
from typing import Optional
import structlog
from pythonjsonlogger import jsonlogger


def setup_logger(
    service_name: str,
    level: str = "INFO",
    json_format: bool = True
) -> structlog.BoundLogger:
    """
    Setup structured logging with JSON format
    
    Args:
        service_name: Name of the service
        level: Logging level (string: DEBUG, INFO, WARNING, ERROR)
        json_format: Whether to use JSON formatting
        
    Returns:
        Configured structured logger
    """
    
    # Convert string level to logging constant
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer() if json_format else structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False
    )
    
    logger = structlog.get_logger(service_name)
    logger = logger.bind(service=service_name)
    
    return logger


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """Get a logger instance"""
    return structlog.get_logger(name)

