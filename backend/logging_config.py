"""Logging and error monitoring configuration for Skincare Routine Builder.

Provides setup_logging() for standard logging with rotating file handlers,
and init_sentry() for optional Sentry error monitoring with idempotency.
"""

import logging
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

import sentry_sdk

from backend.config import settings

# Module-level idempotency flags
_logging_initialised = False
_langsmith_initialised = False
_sentry_initialised = False

# Per-request username injected into every log record
_current_username: ContextVar[str] = ContextVar("current_username", default="-")


def set_log_username(username: str) -> None:
    """Set the username for the current execution context."""
    _current_username.set(username)


class _UsernameFilter(logging.Filter):
    """Injects the current username into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.username = _current_username.get()  # type: ignore[attr-defined]
        return True


def setup_logging() -> None:
    """Configure Python's standard logging module (idempotent).

    Sets up:
    - Stdout handler with ISO timestamp format
    - Rotating file handler (10MB per file, 3 backups)

    Log format: ISO-timestamp | LEVEL | component | message

    Configuration is read from settings:
    - settings.log_level: logging level (default "INFO")
    - settings.log_file: path to log file (default "./logs/app.log")
    """
    global _logging_initialised
    if _logging_initialised:
        return

    log_level = settings.log_level.upper()
    log_file = settings.log_file

    # Create logs directory if it doesn't exist
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Log format includes username between level and component
    log_format = "%(asctime)s | %(levelname)s | %(username)s | %(name)s | %(message)s"
    date_format = "%Y-%m-%dT%H:%M:%S"

    formatter = logging.Formatter(log_format, datefmt=date_format)
    username_filter = _UsernameFilter()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Stdout handler
    stdout_handler = logging.StreamHandler()
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(username_filter)
    root_logger.addHandler(stdout_handler)

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,  # 10 MB
        backupCount=3,
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(username_filter)
    root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _logging_initialised = True


def log_new_session(username: str) -> None:
    """Write a prominent banner to the log when a user starts a new session."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("  NEW SESSION — user: %s", username)
    logger.info("=" * 60)


def init_langsmith() -> None:
    """Enable LangSmith tracing if LANGCHAIN_API_KEY is configured (idempotent).

    LangChain reads these env vars directly from os.environ, so we must
    set them explicitly — pydantic-settings loads them into the Settings
    object but does not write them back to os.environ.

    Safe to call multiple times; only initializes once.
    """
    global _langsmith_initialised
    if _langsmith_initialised:
        return

    import os

    logger = logging.getLogger(__name__)

    if not settings.langchain_api_key.strip():
        logger.debug("LangSmith tracing disabled (LANGCHAIN_API_KEY not set).")
        return

    os.environ["LANGCHAIN_TRACING_V2"] = settings.langchain_tracing_v2
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint

    logger.info(
        "LangSmith tracing enabled — project: %s, endpoint: %s",
        settings.langchain_project,
        settings.langchain_endpoint,
    )

    _langsmith_initialised = True


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
