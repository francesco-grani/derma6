"""Unit tests for backend/logging_config.py"""

import logging
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from backend.logging_config import init_langsmith, init_sentry, log_new_session, setup_logging


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
                assert len(root_logger.handlers) > 0, "No handlers added"

                # At least one handler must have our format (pytest also adds its own
                # StreamHandler with a different format, so check with any()).
                def _has_our_format(h: logging.Handler) -> bool:
                    fmt = getattr(h.formatter, "_fmt", "") or ""
                    return (
                        "%(asctime)s" in fmt
                        and "%(levelname)s" in fmt
                        and "%(name)s" in fmt
                        and "%(message)s" in fmt
                    )

                assert any(_has_our_format(h) for h in root_logger.handlers), (
                    "No handler with expected format found"
                )

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


class TestLogNewSession:
    def test_log_new_session_does_not_raise(self) -> None:
        log_new_session("testuser")

    def test_log_new_session_logs_username(self) -> None:
        with mock.patch("backend.logging_config.logging.getLogger") as mock_get_logger:
            mock_logger = mock.Mock()
            mock_get_logger.return_value = mock_logger
            log_new_session("alice")
        calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("alice" in c for c in calls)


class TestInitLangsmith:
    def setup_method(self):
        import backend.logging_config
        backend.logging_config._langsmith_initialised = False

    def test_init_langsmith_sets_env_vars_when_key_present(self) -> None:
        import os
        import backend.logging_config
        backend.logging_config._langsmith_initialised = False

        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.langsmith_api_key = "lsv2_test_key"
            mock_settings.langsmith_tracing = "true"
            mock_settings.langsmith_project = "my_project"
            mock_settings.langsmith_endpoint = "https://eu.api.smith.langchain.com"

            with mock.patch.dict(os.environ, {}, clear=False):
                init_langsmith()
                assert os.environ.get("LANGSMITH_API_KEY") == "lsv2_test_key"
                assert os.environ.get("LANGSMITH_PROJECT") == "my_project"
                assert os.environ.get("LANGSMITH_ENDPOINT") == "https://eu.api.smith.langchain.com"

    def test_init_langsmith_skips_when_no_key(self) -> None:
        import os
        import backend.logging_config
        backend.logging_config._langsmith_initialised = False

        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.langsmith_api_key = "   "

            env_before = os.environ.get("LANGSMITH_API_KEY")
            init_langsmith()
            assert os.environ.get("LANGSMITH_API_KEY") == env_before

    def test_init_langsmith_is_idempotent(self) -> None:
        import backend.logging_config
        backend.logging_config._langsmith_initialised = False

        with mock.patch("backend.logging_config.settings") as mock_settings:
            mock_settings.langsmith_api_key = "lsv2_test_key"
            mock_settings.langsmith_tracing = "true"
            mock_settings.langsmith_project = "proj"
            mock_settings.langsmith_endpoint = "https://example.com"

            init_langsmith()
            assert backend.logging_config._langsmith_initialised is True

            mock_settings.langsmith_api_key = "different_key"
            init_langsmith()
            import os
            assert os.environ.get("LANGSMITH_API_KEY") == "lsv2_test_key"


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
