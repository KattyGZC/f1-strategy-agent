"""Whether the stores the API reads answer (ADR 0016)."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Dependency(StrEnum):
    POSTGRES = "postgres"
    REDIS = "redis"


class DependencyUnavailableError(Exception):
    """A store did not answer; the message names the error it raised, never its address."""


class Probe(Protocol):
    async def __call__(self) -> None:
        """Returns when the store answers; raises DependencyUnavailableError otherwise."""
        ...


@dataclass(frozen=True)
class DependencyCheck:
    """`error` is None when the dependency answered in time."""

    dependency: Dependency
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class Readiness:
    checks: tuple[DependencyCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.ok for check in self.checks)


TIMED_OUT = "TimeoutError"


class CheckReadiness:
    def __init__(self, probes: Mapping[Dependency, Probe], timeout_s: float) -> None:
        self._probes = probes
        self._timeout_s = timeout_s

    async def __call__(self) -> Readiness:
        # One probe per member of the closed Dependency set: the fan-out is bounded by it.
        checks = await asyncio.gather(
            *(self._check(dependency, probe) for dependency, probe in self._probes.items())
        )
        return Readiness(tuple(checks))

    async def _check(self, dependency: Dependency, probe: Probe) -> DependencyCheck:
        try:
            async with asyncio.timeout(self._timeout_s):
                await probe()
        except DependencyUnavailableError as error:
            return DependencyCheck(dependency, str(error))
        except TimeoutError:
            return DependencyCheck(dependency, TIMED_OUT)
        return DependencyCheck(dependency, None)
