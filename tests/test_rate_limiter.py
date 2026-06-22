"""Unit tests for backend.rate_limiter.RateLimiter."""

import time
from unittest.mock import patch

import pytest

from backend.rate_limiter import RateLimiter


class TestRateLimiterAllow:
    def test_first_request_allowed(self):
        rl = RateLimiter()
        assert rl.check("alice") is True

    def test_multiple_requests_within_limit(self):
        rl = RateLimiter()
        for _ in range(5):
            assert rl.check("bob") is True

    def test_requests_up_to_limit_all_allowed(self, monkeypatch):
        monkeypatch.setattr("backend.rate_limiter.settings.rate_limit_requests", 3)
        rl = RateLimiter()
        assert rl.check("carol") is True
        assert rl.check("carol") is True
        assert rl.check("carol") is True

    def test_request_over_limit_blocked(self, monkeypatch):
        monkeypatch.setattr("backend.rate_limiter.settings.rate_limit_requests", 3)
        rl = RateLimiter()
        rl.check("dave")
        rl.check("dave")
        rl.check("dave")
        assert rl.check("dave") is False

    def test_different_users_independent(self, monkeypatch):
        monkeypatch.setattr("backend.rate_limiter.settings.rate_limit_requests", 2)
        rl = RateLimiter()
        rl.check("eve")
        rl.check("eve")
        assert rl.check("eve") is False
        assert rl.check("frank") is True  # different user, window fresh

    def test_expired_timestamps_purged(self, monkeypatch):
        monkeypatch.setattr("backend.rate_limiter.settings.rate_limit_requests", 2)
        monkeypatch.setattr("backend.rate_limiter.settings.rate_limit_window_seconds", 1)
        rl = RateLimiter()

        rl.check("grace")
        rl.check("grace")
        assert rl.check("grace") is False

        # Advance monotonic clock past the window
        future_time = time.monotonic() + 2
        with patch("time.monotonic", return_value=future_time):
            assert rl.check("grace") is True  # window has expired → allowed

    def test_bypass_user_always_allowed(self, monkeypatch):
        monkeypatch.setattr("backend.rate_limiter.settings.rate_limit_requests", 1)
        rl = RateLimiter()
        for _ in range(20):
            assert rl.check("ragas_eval_bot") is True

    def test_purge_expired_noop_for_unknown_user(self):
        rl = RateLimiter()
        rl._purge_expired("nonexistent_user")  # must not raise

    def test_blocked_request_does_not_append_timestamp(self, monkeypatch):
        monkeypatch.setattr("backend.rate_limiter.settings.rate_limit_requests", 1)
        rl = RateLimiter()
        rl.check("henry")  # allowed, 1 timestamp
        rl.check("henry")  # blocked, should NOT append
        from collections import deque
        assert len(rl._user_requests["henry"]) == 1
