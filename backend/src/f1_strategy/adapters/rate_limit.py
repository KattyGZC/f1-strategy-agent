import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimit:
    max_requests: int
    period_s: float


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limits: Sequence[RateLimit],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not limits:
            raise ValueError("at least one rate limit is required")
        self._limits = tuple(limits)
        self._longest_period_s = max(limit.period_s for limit in limits)
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._sent_at: deque[float] = deque()

    async def acquire(self) -> None:
        async with self._lock:
            while (wait_s := self._wait_s(self._clock())) > 0:
                await self._sleep(wait_s)
            self._sent_at.append(self._clock())

    def _wait_s(self, now: float) -> float:
        while self._sent_at and self._sent_at[0] <= now - self._longest_period_s:
            self._sent_at.popleft()
        return max(self._wait_for(limit, now) for limit in self._limits)

    def _wait_for(self, limit: RateLimit, now: float) -> float:
        in_window = [sent for sent in self._sent_at if sent > now - limit.period_s]
        if len(in_window) < limit.max_requests:
            return 0.0
        return in_window[-limit.max_requests] + limit.period_s - now
