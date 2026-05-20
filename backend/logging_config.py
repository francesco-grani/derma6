"""Logging and error monitoring configuration for Skincare Routine Builder.

Provides setup_logging() for standard logging with rotating file handlers,
and init_sentry() for optional Sentry error monitoring with idempotency.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import sentry_sdk

from backend.config import settings

# Module-level flag for Sentry idempotency
_sentry_initialised = False


def setup_logging() -> None:
    """Configure Python's standard logging module.

    Sets up:
    - Stdout handler with ISO timestamp format
    - Rotating file handler (10MB per file, 3 backups)

    Log format: ISO-timestamp | LEVEL | component | message

    Configuration is read from settings:
    - settings.log_level: logging level (default "INFO")
    - settings.log_file: path to log file (default "./logs/app.log")
    """
    log_level = settings.log_level.upper()
    log_file = settings.log_file

    # Create logs directory if it doesn't exist
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Define log format: ISO-timestamp | LEVEL | component | message
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    # ISO 8601 timestamp format
    date_format = "%Y-%m-%dT%H:%M:%S"

    # Create formatter
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Stdout handler
    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,  # 10 MB
        backupCount=3,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def init_sentry() -> None:
    """Initialize Sentry SDK for error monitoring (idempotent).

    Reads configuration from settings:
    - settings.sentry_dsn: Sentry DSN (optional, default "")
    - settings.sentry_traces_sample_rate: trace sampling rate (default 0.1)

    If SENTRY_DSN is empty or not set:
    - Logs a WARNING and returns without raising an error

    If SENTRY_DSN is set:
    - Initializes Sentry SDK with the configured DSN and sampling rate
    - Uses module-level _sentry_initialised flag to prevent double initialization

    Safe to call multiple times; only initializes once.
    """
    global _sentry_initialised

    sentry_dsn = settings.sentry_dsn.strip()

    if not sentry_dsn:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Sentry DSN not configured. Error monitoring is disabled. "
            "Set SENTRY_DSN environment variable to enable."
        )
        return

    if _sentry_initialised:
        return

    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )

    _sentry_initialised = True
