from datetime import UTC, datetime

from f1_strategy.domain.openf1 import JsonObject

RACE_KEY = 9472
QUALIFYING_KEY = 9468
PRACTICE_KEY = 9465
CANCELLED_KEY = 9999
RACE_START = datetime(2024, 3, 2, 15, tzinfo=UTC)
RACE_END = datetime(2024, 3, 2, 17, tzinfo=UTC)
SEASON_2024_SETTLED = datetime(2025, 2, 1, tzinfo=UTC)


def session_row(
    session_key: int,
    session_type: str,
    *,
    date_start: str = "2024-03-02T15:00:00+00:00",
    date_end: str = "2024-03-02T17:00:00+00:00",
    is_cancelled: bool = False,
) -> JsonObject:
    return {
        "session_key": session_key,
        "session_type": session_type,
        "session_name": session_type,
        "date_start": date_start,
        "date_end": date_end,
        "is_cancelled": is_cancelled,
        "year": 2024,
    }


SEASON_2024: list[JsonObject] = [
    session_row(PRACTICE_KEY, "Practice"),
    session_row(
        QUALIFYING_KEY,
        "Qualifying",
        date_start="2024-03-01T16:00:00+00:00",
        date_end="2024-03-01T17:00:00+00:00",
    ),
    session_row(RACE_KEY, "Race"),
    session_row(CANCELLED_KEY, "Race", is_cancelled=True),
]

DRIVERS: list[JsonObject] = [
    {"driver_number": 16, "session_key": RACE_KEY},
    {"driver_number": 1, "session_key": RACE_KEY},
]


class FakeClock:
    def __init__(self) -> None:
        self.now_s = 1000.0
        self.slept_s: list[float] = []

    def __call__(self) -> float:
        return self.now_s

    async def sleep(self, seconds: float) -> None:
        self.slept_s.append(seconds)
        self.now_s += seconds
