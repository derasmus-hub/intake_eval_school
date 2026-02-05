"""
Simple in-memory rate limiter for auth endpoints.
No external dependencies required.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Optional

# Configuration
MAX_ATTEMPTS = 10  # attempts per IP
WINDOW_SECONDS = 300  # 5 minutes


class RateLimiter:
    """Thread-safe in-memory rate limiter."""

    def __init__(self, max_attempts: int = MAX_ATTEMPTS, window_seconds: int = WINDOW_SECONDS):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _cleanup_old(self, key: str, now: float) -> None:
        """Remove attempts older than the window."""
        cutoff = now - self.window_seconds
        self._attempts[key] = [t for t in self._attempts[key] if t > cutoff]

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed and record the attempt."""
        now = time.time()

        with self._lock:
            self._cleanup_old(key, now)
            if len(self._attempts[key]) >= self.max_attempts:
                return False
            self._attempts[key].append(now)
            return True

    def get_remaining(self, key: str) -> int:
        """Get remaining attempts for a key."""
        now = time.time()
        with self._lock:
            self._cleanup_old(key, now)
            return max(0, self.max_attempts - len(self._attempts[key]))

    def get_retry_after(self, key: str) -> Optional[int]:
        """Get seconds until next attempt allowed (if rate limited)."""
        now = time.time()
        with self._lock:
            self._cleanup_old(key, now)
            if len(self._attempts[key]) < self.max_attempts:
                return None
            # Return time until oldest attempt expires
            oldest = min(self._attempts[key])
            return int(oldest + self.window_seconds - now) + 1

    def reset(self, key: str) -> None:
        """Reset rate limit for a key (for testing)."""
        with self._lock:
            self._attempts.pop(key, None)

    def reset_all(self) -> None:
        """Reset all rate limits (for testing)."""
        with self._lock:
            self._attempts.clear()


# Global instance for auth endpoints
auth_limiter = RateLimiter()
