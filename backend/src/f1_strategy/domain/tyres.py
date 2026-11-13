"""The tyre each lap was driven on, read from its driver's stints (ADR 0008).

Every function here is pure.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from f1_strategy.domain.clean import Compound, Lap, Stint


@dataclass(frozen=True)
class Tyre:
    compound: Compound
    age_laps: int


class TyreLookup:
    """One session's stints, by driver, newest first."""

    def __init__(self, stints: Sequence[Stint]) -> None:
        # Newest stint first: consecutive stints share their boundary lap (ADR 0008), and the
        # lap belongs to the stint that starts on it.
        newest_first: defaultdict[int, list[Stint]] = defaultdict(list)
        for stint in sorted(stints, key=lambda stint: stint.stint_number, reverse=True):
            newest_first[stint.driver_number].append(stint)
        self._newest_first = dict(newest_first)

    def tyre_on(self, lap: Lap) -> Tyre | None:
        """The tyre of the stint that covers the lap; None when no stint does, since the source
        does not say."""
        for stint in self._newest_first.get(lap.driver_number, ()):
            if stint.lap_start is None or stint.lap_end is None:
                continue
            if stint.lap_start <= lap.lap_number <= stint.lap_end:
                age_laps = stint.tyre_age_at_start + lap.lap_number - stint.lap_start
                return Tyre(stint.compound, age_laps)
        return None
