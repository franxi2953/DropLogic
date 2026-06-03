"""
Centralized logging configuration for the DropLogic library.

This module provides a standardized logging setup that can be used across
all DropLogic modules with configurable levels and consistent formatting.
"""

import logging
import os
from typing import Optional


def setup_droplogic_logger(
    name: str, 
    level: Optional[int] = None,
    log_file: Optional[str] = None,
    console_output: bool = True
) -> logging.Logger:
    """
    Set up a logger for DropLogic modules with standardized configuration.
    
    Args:
        name: Logger name (typically module name like 'droplogic.advanced_drop.sipp')
        level: Logging level (default: ERROR for production use)
        log_file: Optional log file path (default: 'droplogic_debug.log')
        console_output: Whether to output to console (default: True)
    
    Returns:
        Configured logger instance
    """
    if log_file is None:
        log_file = 'droplogic_debug.log'
    
    if level is None:
        level = logging.INFO
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers if logger already exists
    if logger.handlers:
        return logger
    
    # Create formatter with module identification
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler (optional)
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger


def set_droplogic_logging_level(level: int):
    """
    Set logging level for all DropSystem loggers.
    
    Args:
        level: Logging level (e.g., logging.INFO, logging.DEBUG)
    """
    # Get all loggers that start with 'droplogic'
    for name in logging.Logger.manager.loggerDict:
        if name.startswith('droplogic'):
            logger = logging.getLogger(name)
            logger.setLevel(level)
            # Update handler levels too
            for handler in logger.handlers:
                handler.setLevel(level)


def enable_debug_logging():
    """Enable DEBUG level logging for all DropLogic modules."""
    set_droplogic_logging_level(logging.DEBUG)


def enable_info_logging():
    """Enable INFO level logging for all DropLogic modules."""
    set_droplogic_logging_level(logging.INFO)


def enable_error_only_logging():
    """Enable ERROR level logging only for all DropLogic modules."""
    set_droplogic_logging_level(logging.ERROR)
