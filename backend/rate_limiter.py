"""Rate limiter implementing a sliding-window algorithm.

Maintains per-user request timestamps and enforces rate limits based on
a configurable window (e.g., max 10 requests per 60 seconds).
"""

import time
from collections import deque
from typing import Dict

from backend.config import settings


class RateLimiter:
    """Sliding-window rate limiter for request throttling.

    Tracks request timestamps per user and allows requests only if the count
    of requests within the current window is below the configured limit.

    Attributes:
        _user_requests: Dictionary mapping username to deque of timestamps
    """

    def __init__(self) -> None:
        """Initialize the rate limiter with empty user request tracking."""
        self._user_requests: Dict[str, deque] = {}

    def check(self, username: str) -> bool:
        """Check if a request is allowed for the given user.

        Implements sliding-window algorithm:
        1. Purge expired timestamps from the user's request history
        2. Check if the number of remaining requests equals or exceeds the limit
        3. If limit exceeded, return False without appending timestamp
        4. If allowed, append current timestamp and return True

        Args:
            username: Identifier for the user/client making the request

        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        # Ensure the user has a deque for tracking
        if username not in self._user_requests:
            self._user_requests[username] = deque()

        # Remove timestamps outside the current window
        self._purge_expired(username)

        # Check if at limit
        if len(self._user_requests[username]) >= settings.rate_limit_requests:
            return False

        # Request allowed: append current timestamp and return True
        self._user_requests[username].append(time.monotonic())
        return True

    def _purge_expired(self, username: str) -> None:
        """Remove timestamps older than the rate limit window.

        Removes all timestamps from the user's deque that are older than
        RATE_LIMIT_WINDOW_SECONDS from now.

        Args:
            username: User identifier whose request history to clean
        """
        if username not in self._user_requests:
            return

        current_time = time.monotonic()
        window_start = current_time - settings.rate_limit_window_seconds
        deque_ref = self._user_requests[username]

        # Remove all timestamps that are older than the window
        while deque_ref and deque_ref[0] < window_start:
            deque_ref.popleft()
