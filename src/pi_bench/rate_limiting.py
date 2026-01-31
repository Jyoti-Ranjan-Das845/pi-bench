"""Async-safe rate limiter using slot reservation.

Usage:
    rate_limiter = RateLimiter(RateLimitConfig(requests_per_minute=30))
    await rate_limiter.acquire()  # call before each request
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitConfig:
    """Rate limit configuration."""

    requests_per_minute: int = 30

    def __post_init__(self) -> None:
        if self.requests_per_minute < 1:
            msg = f"requests_per_minute must be >= 1, got {self.requests_per_minute}"
            raise ValueError(msg)

    @property
    def min_interval_seconds(self) -> float:
        return 60.0 / self.requests_per_minute


class RateLimiter:
    """Async-safe rate limiter using slot reservation.

    Each request reserves a time slot, then releases the lock and sleeps.
    Parallel requests quickly reserve their slots and sleep independently.

    For 5 RPM (12s interval):
        - Request 1 at t=0: scheduled for t=0, proceeds immediately
        - Request 2 at t=0: scheduled for t=12, sleeps 12s
        - Request 3 at t=0: scheduled for t=24, sleeps 24s
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self._config = config
        self._lock = asyncio.Lock()
        self._next_slot_time: float = 0.0

    @property
    def config(self) -> RateLimitConfig:
        return self._config

    async def acquire(self) -> None:
        """Reserve a time slot under lock, then sleep outside the lock."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            scheduled_time = max(self._next_slot_time, now)
            delay = scheduled_time - now
            self._next_slot_time = scheduled_time + self._config.min_interval_seconds

            if delay > 0:
                logger.info(
                    "[rate_limit] Scheduled for +%.1fs (%d RPM)",
                    delay,
                    self._config.requests_per_minute,
                )

        if delay > 0:
            await asyncio.sleep(delay)

    def reset(self) -> None:
        """Reset state. Useful for testing."""
        self._next_slot_time = 0.0
