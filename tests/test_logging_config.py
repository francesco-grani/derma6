"""Unit tests for backend/logging_config.py"""

import logging
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from backend.logging_config import init_sentry, setup_logging


class TestSetupLogging:
    """Tests for setup_logging() function."""

    def test_setup_logging_creates_log_file(self) -> None:
        """Verify setup_logging creates the log file and its parent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "subdir" / "app.log"

            with mock.patch("backend.logging_config.settings") as mock_settings:
                mock_settings.log_level = "INFO"
                mock_settings.log_file = str(log_file)

                setup_logging()

                assert log_file.exists(), "Log file was not created"

    def test_setup_logging_format(self) -> None:
        """Verify setup_logging creates handlers with correct format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"

            with mock.patch("backend.logging_config.settings") as mock_settings:
                mock_settings.log_level = "DEBUG"
                mock_settings.log_file = str(log_file)

                setup_logging()

                root_logger = logging.getLogger()
                # Check that handlers exist
                assert len(root_logger.handlers) > 0, "No handlers added"

                # Check formatter includes ISO timestamp and component
                for handler in root_logger.handlers:
                    assert handler.formatter is not None
                    format_str = handler.formatter._fmt
                    assert "%(asctime)s" in format_str
                    assert "%(levelname)s" in format_str
                    assert "%(name)s" in format_str  # component
                    assert "%(message)s" in format_str

    def test_setup_logging_removes_duplicates(self) -> None:
        """Verify multiple calls to setup_logging don't accumulate handlers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"

            with mock.patch("backend.logging_config.settings") as mock_settings:
                mock_settings.log_level = "INFO"
                mock_settings.log_file = str(log_file)

                setup_logging()
                handlers_after_first = len(logging.getLogger().handlers)

                setup_logging()
                handlers_after_second = len(logging.getLogger().handlers)

                assert (
                    handlers_after_first == handlers_after_second
                ), "Handlers accumulated on second call"

    def test_setup_logging_rotating_file_handler(self) -> None:
        """Verify rotating file handler has correct configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"

            with mock.patch("backend.logging_config.settings") as mock_settings:
                mock_settings.log_level = "INFO"
                mock_settings.log_file = str(log_file)

                setup_logging()

                from logging.handlers import RotatingFileHandler

                root_logger = logging.getLogger()
                rotating_handlers = [
                    h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)
                ]

                assert len(rotating_handlers) > 0, "No RotatingFileHandler found"
                handler = rotating_handlers[0]
                assert handler.maxBytes == 10_000_000, f"maxBytes is {handler.maxBytes}"
                assert handler.backupCount == 3, f"backupCount is {handler.backupCount}"


class TestInitSentry:
    """Tests for init_sentry() function."""

    def test_init_sentry_no_dsn(self) -> None:
        """Verify init_sentry does not raise when SENTRY_DSN is absent or empty."""
        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.sentry_dsn = ""

            # Should not raise
            init_sentry()

    def test_init_sentry_no_dsn_logs_warning(self) -> None:
        """Verify init_sentry logs a warning when SENTRY_DSN is empty."""
        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.sentry_dsn = ""

            with mock.patch("backend.logging_config.logging.getLogger") as mock_logger:
                mock_logger_instance = mock.Mock()
                mock_logger.return_value = mock_logger_instance

                init_sentry()

                mock_logger_instance.warning.assert_called_once()
                warning_msg = mock_logger_instance.warning.call_args[0][0]
                assert "Sentry DSN not configured" in warning_msg

    def test_init_sentry_idempotent(self) -> None:
        """Verify calling init_sentry() twice doesn't double-initialize."""
        # Reset the module-level flag first
        import backend.logging_config

        backend.logging_config._sentry_initialised = False

        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.sentry_dsn = "https://example@sentry.io/123456"
            mock_settings.sentry_traces_sample_rate = 0.1

            with mock.patch("backend.logging_config.sentry_sdk.init") as mock_init:
                # First call
                init_sentry()
                assert mock_init.call_count == 1

                # Second call should not call sentry_sdk.init again
                init_sentry()
                assert mock_init.call_count == 1

    def test_init_sentry_idempotent_no_dsn(self) -> None:
        """Verify idempotency with no DSN (should not cause issues)."""
        # Reset the module-level flag first
        import backend.logging_config

        backend.logging_config._sentry_initialised = False

        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.sentry_dsn = ""

            with mock.patch("backend.logging_config.logging.getLogger"):
                # Multiple calls with empty DSN should not raise
                init_sentry()
                init_sentry()
                # If we get here without exception, test passes

    def test_init_sentry_with_dsn(self) -> None:
        """Verify init_sentry initializes Sentry when DSN is provided."""
        # Reset the module-level flag first
        import backend.logging_config

        backend.logging_config._sentry_initialised = False

        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.sentry_dsn = "https://example@sentry.io/123456"
            mock_settings.sentry_traces_sample_rate = 0.1

            with mock.patch("backend.logging_config.sentry_sdk.init") as mock_init:
                init_sentry()

                mock_init.assert_called_once_with(
                    dsn="https://example@sentry.io/123456",
                    traces_sample_rate=0.1,
                )

    def test_init_sentry_strips_whitespace_from_dsn(self) -> None:
        """Verify init_sentry treats DSN with only whitespace as empty."""
        # Reset the module-level flag first
        import backend.logging_config

        backend.logging_config._sentry_initialised = False

        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.sentry_dsn = "   "  # Only whitespace

            with mock.patch("backend.logging_config.logging.getLogger") as mock_logger:
                mock_logger_instance = mock.Mock()
                mock_logger.return_value = mock_logger_instance

                init_sentry()

                # Should treat as empty and log warning
                mock_logger_instance.warning.assert_called_once()
