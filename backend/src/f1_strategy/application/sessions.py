"""The sessions of the clean model a viewer can replay, and who drove in each."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from f1_strategy.application.replay import SessionNotLoadedError
from f1_strategy.domain.openf1 import SessionName, SessionType


@dataclass(frozen=True)
class LoadedSession:
    session_key: int
    session_type: SessionType
    session_name: SessionName
    date_start: datetime
    year: int
    meeting_name: str
    circuit_short_name: str
    country_name: str


@dataclass(frozen=True)
class SessionDriver:
    driver_number: int
    name_acronym: str
    full_name: str
    team_name: str
    team_colour: str


@dataclass(frozen=True)
class SessionEntry:
    session: LoadedSession
    drivers: tuple[SessionDriver, ...]


class SessionCatalog(Protocol):
    async def sessions(self) -> tuple[LoadedSession, ...]:
        """Every loaded session, the latest first."""
        ...

    async def entry(self, session_key: int) -> SessionEntry | None:
        """The session and its drivers by number, or None if it is not loaded."""
        ...


class ListSessions:
    def __init__(self, catalog: SessionCatalog) -> None:
        self._catalog = catalog

    async def __call__(self) -> tuple[LoadedSession, ...]:
        return await self._catalog.sessions()


class ReadSession:
    def __init__(self, catalog: SessionCatalog) -> None:
        self._catalog = catalog

    async def __call__(self, session_key: int) -> SessionEntry:
        entry = await self._catalog.entry(session_key)
        if entry is None:
            raise SessionNotLoadedError(session_key)
        return entry
