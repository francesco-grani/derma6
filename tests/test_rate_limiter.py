"""Tests for the sliding-window rate limiter."""

import time
from unittest.mock import patch

import pytest

from backend.rate_limiter import RateLimiter


@pytest.fixture
def rate_limiter():
    """Create a fresh RateLimiter instance for each test."""
    return RateLimiter()


class TestRateLimiter:
    """Test suite for the RateLimiter class."""

    def test_allows_requests_within_limit(self, rate_limiter):
        """First N requests within the limit should all return True.

        With default settings (10 requests per 60 seconds), the first 10
        requests for any user should be allowed.
        """
        username = "test_user"

        # Make 10 requests (the default limit)
        for i in range(10):
            assert rate_limiter.check(username) is True, \
                f"Request {i+1} should be allowed"

    def test_blocks_on_limit_exceeded(self, rate_limiter):
        """The (N+1)th request should be blocked when limit is exceeded.

        After making N allowed requests, the next request should return False.
        """
        username = "test_user"

        # Make 10 allowed requests
        for _ in range(10):
            rate_limiter.check(username)

        # The 11th request should be blocked
        assert rate_limiter.check(username) is False, \
            "11th request should be blocked"

    def test_unblocks_after_window_expires(self, rate_limiter):
        """After the window expires, new requests should be allowed again.

        Uses mocking of time.monotonic to control the window expiration.
        """
        username = "test_user"

        with patch("time.monotonic") as mock_time:
            # Set initial time to 0
            mock_time.return_value = 0.0

            # Make 10 requests at time 0
            for _ in range(10):
                rate_limiter.check(username)

            # At time 0, the 11th request should be blocked
            assert rate_limiter.check(username) is False

            # Advance time by 61 seconds (window is 60 seconds)
            mock_time.return_value = 61.0

            # After the window expires, new requests should be allowed
            assert rate_limiter.check(username) is True, \
                "Request should be allowed after window expires"

    def test_per_user_isolation(self, rate_limiter):
        """Rate limit for one user should not affect another user.

        User A hitting the rate limit should not block requests from User B.
        """
        user_a = "user_a"
        user_b = "user_b"

        # User A makes 10 requests (hits the limit)
        for _ in range(10):
            rate_limiter.check(user_a)

        # User A's next request should be blocked
        assert rate_limiter.check(user_a) is False

        # User B should still be able to make requests
        assert rate_limiter.check(user_b) is True, \
            "User B should not be affected by User A's rate limit"

        # User B should be able to make multiple requests (up to the limit)
        for _ in range(9):
            assert rate_limiter.check(user_b) is True

        # User B should also be blocked on the 11th request
        assert rate_limiter.check(user_b) is False

    def test_purge_removes_old_timestamps(self, rate_limiter):
        """Old timestamps should be removed from the deque after the window.

        Directly test the _purge_expired method to ensure it removes
        timestamps outside the current window.
        """
        username = "test_user"

        with patch("time.monotonic") as mock_time:
            # Set initial time to 0
            mock_time.return_value = 0.0

            # Make 5 requests at time 0
            for _ in range(5):
                rate_limiter.check(username)

            # Verify 5 timestamps are stored
            assert len(rate_limiter._user_requests[username]) == 5

            # Advance time by 61 seconds (window is 60 seconds)
            mock_time.return_value = 61.0

            # Manually call _purge_expired
            rate_limiter._purge_expired(username)

            # All old timestamps should have been removed
            assert len(rate_limiter._user_requests[username]) == 0, \
                "Old timestamps should be purged after window expires"

    def test_purge_with_mixed_timestamps(self, rate_limiter):
        """_purge_expired should remove only timestamps outside the window.

        Test that old timestamps are removed while recent ones are kept.
        """
        username = "test_user"

        with patch("time.monotonic") as mock_time:
            # Make 5 requests at time 0
            mock_time.return_value = 0.0
            for _ in range(5):
                rate_limiter.check(username)

            # Advance time by 35 seconds (still within the 60-second window)
            mock_time.return_value = 35.0

            # Make 5 more requests at time 35
            for _ in range(5):
                rate_limiter.check(username)

            # Should have 10 total timestamps
            assert len(rate_limiter._user_requests[username]) == 10

            # Advance time by 26 more seconds (total 61 seconds from start)
            mock_time.return_value = 61.0

            # Purge should remove only the first 5 (which are now 61 seconds old)
            rate_limiter._purge_expired(username)

            # Should have 5 remaining timestamps (from time 35)
            assert len(rate_limiter._user_requests[username]) == 5, \
                "Only timestamps from before window start should be removed"

    def test_empty_user_purge(self, rate_limiter):
        """_purge_expired should handle users with no request history gracefully."""
        username = "nonexistent_user"

        # Should not raise an error
        rate_limiter._purge_expired(username)

        # User should still not exist in tracking
        assert username not in rate_limiter._user_requests

    def test_config_settings_respected(self, rate_limiter):
        """Rate limiter should respect settings from backend.config.

        This test verifies that the implementation reads from the correct
        configuration object.
        """
        # Access the rate limiter's check method to ensure it uses settings
        from backend.config import settings

        # The defaults should be 10 requests per 60 seconds
        assert settings.rate_limit_requests == 10
        assert settings.rate_limit_window_seconds == 60

        username = "test_user"

        # Make exactly the limit number of requests
        for _ in range(settings.rate_limit_requests):
            rate_limiter.check(username)

        # Next request should be blocked
        assert rate_limiter.check(username) is False
