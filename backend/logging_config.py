"""Logging and error monitoring configuration for Derma6.

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


# Attributes the logging module puts on every record. Anything outside this set
# arrived via `extra=` at the call site. Derived from a throwaway record rather
# than hardcoded, so it tracks the stdlib across versions (e.g. `taskName` in
# 3.12). `username` is added by _UsernameFilter and already has its own column.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"asctime", "message", "username", "taskName"}


class _ExtraFieldFormatter(logging.Formatter):
    """Renders `extra={...}` payloads, which the stdlib formatter discards.

    Callers such as backend/rag/pipeline/nodes/generate.py attach structured
    observability data (routing, per-node latencies, retry state) via `extra=`.
    Without this, that record prints as a bare "rag_pipeline_complete" and the
    whole payload is silently dropped.
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in _STANDARD_RECORD_ATTRS and not k.startswith("_")
        }
        # `event` duplicates the message for structured-log consumers.
        extras.pop("event", None)
        if not extras:
            return base
        return base + " | " + " ".join(f"{k}={v}" for k, v in extras.items())


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

    formatter = _ExtraFieldFormatter(log_format, datefmt=date_format)
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

    # Silence noisy third-party loggers.
    #
    # These are pinned regardless of log_level so that LOG_LEVEL=DEBUG stays
    # readable: at DEBUG the root level otherwise propagates into every HTTP
    # library, and a single RAG query emits ~200 lines from httpcore.http11 and
    # ~80 from httpcore.connection, burying the ~19 derma6.rag lines that are
    # the actual reason to turn DEBUG on.
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
    for _noisy in ("httpx", "httpcore", "openai", "urllib3", "sentence_transformers", "chromadb"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    # langsmith.client logs one multi-line WARNING per trace when the tenant is
    # over its monthly quota — a condition we can neither fix from here nor act
    # on, so it is held at ERROR to keep it out of the stream. Real client
    # failures still surface.
    logging.getLogger("langsmith.client").setLevel(logging.ERROR)

    _logging_initialised = True


def log_new_session(username: str) -> None:
    """Write a prominent banner to the log when a user starts a new session."""
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("  NEW SESSION — user: %s", username)
    logger.info("=" * 60)


def init_langsmith() -> None:
    """Enable LangSmith tracing if LANGSMITH_API_KEY is configured (idempotent).

    LangSmith reads these env vars directly from os.environ, so we must
    set them explicitly — pydantic-settings loads them into the Settings
    object but does not write them back to os.environ.

    Safe to call multiple times; only initializes once.
    """
    global _langsmith_initialised
    if _langsmith_initialised:
        return

    import os

    logger = logging.getLogger(__name__)

    if not settings.langsmith_api_key.strip():
        logger.debug("LangSmith tracing disabled (LANGSMITH_API_KEY not set).")
        return

    os.environ["LANGSMITH_TRACING"] = "true"  # key is present → always enable
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint

    logger.info(
        "LangSmith tracing enabled — project: %s, endpoint: %s",
        settings.langsmith_project,
        settings.langsmith_endpoint,
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
