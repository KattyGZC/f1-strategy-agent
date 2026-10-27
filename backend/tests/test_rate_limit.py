import pytest

from f1_strategy.adapters.rate_limit import RateLimit, SlidingWindowRateLimiter
from tests.factories import FakeClock


def limiter(clock: FakeClock, *limits: RateLimit) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(limits, clock=clock, sleep=clock.sleep)


@pytest.mark.anyio
async def test_requests_within_the_limit_do_not_wait() -> None:
    clock = FakeClock()
    rate = limiter(clock, RateLimit(3, 1.0))

    for _ in range(3):
        await rate.acquire()

    assert clock.slept_s == []


@pytest.mark.anyio
async def test_the_request_past_the_limit_waits_until_the_oldest_leaves_the_window() -> None:
    clock = FakeClock()
    rate = limiter(clock, RateLimit(3, 1.0))
    for _ in range(3):
        await rate.acquire()
        clock.now_s += 0.1

    await rate.acquire()

    assert clock.slept_s == pytest.approx([0.7])


@pytest.mark.anyio
async def test_the_strictest_of_several_limits_wins() -> None:
    clock = FakeClock()
    rate = limiter(clock, RateLimit(3, 1.0), RateLimit(5, 60.0))
    for _ in range(5):
        await rate.acquire()
        clock.now_s += 1.0

    await rate.acquire()

    assert sum(clock.slept_s) == pytest.approx(55.0)


@pytest.mark.anyio
async def test_a_long_idle_gap_resets_every_window() -> None:
    clock = FakeClock()
    rate = limiter(clock, RateLimit(2, 1.0), RateLimit(2, 60.0))
    await rate.acquire()
    await rate.acquire()
    clock.now_s += 60.0

    await rate.acquire()
    await rate.acquire()

    assert clock.slept_s == []


def test_at_least_one_limit_is_required() -> None:
    with pytest.raises(ValueError, match="at least one rate limit is required"):
        SlidingWindowRateLimiter([])
