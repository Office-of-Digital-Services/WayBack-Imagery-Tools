"""Centralized File and Stream Logging Configuration for Wayback Add-in.

Provides automated full-path file logging to the project root directory with
rotating file handler support, custom log formatting, and graceful fallback
if the target filesystem is read-only.
"""

import logging
from logging.handlers import RotatingFileHandler
import os
from typing import Optional

LOG_FILE_NAME: str = "wayback_addin.log"

# Determine the absolute project root directory (two levels up from this file)
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_PATH: str = os.path.join(PROJECT_ROOT, LOG_FILE_NAME)
PACKAGE_LOGGER_NAME: str = "wayback_addin"

DEFAULT_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def get_default_log_path() -> str:
    """Returns the absolute path to the default log file in the project root.

    Returns:
        Absolute filesystem path string to wayback_addin.log.
    """
    return DEFAULT_LOG_PATH


def setup_file_logger(
    log_file_path: Optional[str] = None,
    level: int = logging.DEBUG,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    logger_name: str = PACKAGE_LOGGER_NAME,
) -> logging.Logger:
    """Configures and attaches a RotatingFileHandler to the specified logger.

    If a handler writing to the resolved file path is already registered on the
    logger, its level is updated and no duplicate handler is added.

    Args:
        log_file_path: Full path to the log file. Defaults to DEFAULT_LOG_PATH.
        level: Logging level threshold. Defaults to logging.INFO.
        max_bytes: Maximum size in bytes before log file rotation (default 5 MB).
        backup_count: Number of rotated backup files to retain (default 3).
        logger_name: Name of the logger to configure (default 'wayback_addin').

    Returns:
        The configured logging.Logger instance.
    """
    if log_file_path is None:
        log_file_path = DEFAULT_LOG_PATH

    pkg_logger = logging.getLogger(logger_name)
    pkg_logger.setLevel(level)

    resolved_path = os.path.abspath(log_file_path)

    # Avoid duplicate handlers pointing to the exact same file
    for handler in pkg_logger.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == resolved_path:
            handler.setLevel(level)
            return pkg_logger

    try:
        log_dir = os.path.dirname(resolved_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            resolved_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        formatter = logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_DATE_FORMAT)
        file_handler.setFormatter(formatter)
        pkg_logger.addHandler(file_handler)
    except (OSError, PermissionError) as exc:
        # Gracefully handle restricted or read-only filesystem environments
        logging.getLogger(__name__).warning(
            "Unable to initialize file logger at '%s': %s", resolved_path, exc
        )

    return pkg_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Retrieves a logger instance, ensuring the package file logger is initialized.

    Args:
        name: Logger name (e.g., 'wayback_addin.cache'). If None, returns the root
            package logger ('wayback_addin').

    Returns:
        logging.Logger instance.
    """
    setup_file_logger()
    if not name:
        return logging.getLogger(PACKAGE_LOGGER_NAME)
    return logging.getLogger(name)
