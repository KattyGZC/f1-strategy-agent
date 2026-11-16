import asyncio

import pytest

from f1_strategy.application.readiness import (
    CheckReadiness,
    Dependency,
    DependencyCheck,
    DependencyUnavailableError,
    Readiness,
)


async def answers() -> None:
    return None


async def refuses() -> None:
    raise DependencyUnavailableError("ConnectionError")


async def hangs() -> None:
    await asyncio.sleep(10)


@pytest.mark.anyio
async def test_the_api_is_ready_when_every_store_answers() -> None:
    check = CheckReadiness({Dependency.POSTGRES: answers, Dependency.REDIS: answers}, 1)

    readiness = await check()

    assert readiness == Readiness(
        (DependencyCheck(Dependency.POSTGRES, None), DependencyCheck(Dependency.REDIS, None))
    )
    assert readiness.ready


@pytest.mark.anyio
async def test_a_store_that_refuses_or_does_not_answer_in_time_is_named() -> None:
    check = CheckReadiness({Dependency.POSTGRES: refuses, Dependency.REDIS: hangs}, 0.05)

    readiness = await check()

    assert readiness == Readiness(
        (
            DependencyCheck(Dependency.POSTGRES, "ConnectionError"),
            DependencyCheck(Dependency.REDIS, "TimeoutError"),
        )
    )
    assert not readiness.ready


@pytest.mark.anyio
async def test_one_store_down_is_enough_to_be_not_ready() -> None:
    check = CheckReadiness({Dependency.POSTGRES: answers, Dependency.REDIS: refuses}, 1)

    assert not (await check()).ready


@pytest.mark.anyio
async def test_the_stores_are_checked_at_once() -> None:
    slow_s = 0.2

    async def slow() -> None:
        await asyncio.sleep(slow_s)

    check = CheckReadiness({Dependency.POSTGRES: slow, Dependency.REDIS: slow}, 1)
    started_s = asyncio.get_running_loop().time()

    await check()

    assert asyncio.get_running_loop().time() - started_s < 2 * slow_s
