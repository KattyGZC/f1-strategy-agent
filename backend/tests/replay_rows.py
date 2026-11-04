from dataclasses import dataclass, field

from f1_strategy.domain.clean import (
    Interval,
    Lap,
    Overtake,
    Pit,
    Position,
    RaceControl,
    Stint,
    TeamRadio,
    Weather,
)


@dataclass
class Rows:
    laps: list[Lap] = field(default_factory=list)
    stints: list[Stint] = field(default_factory=list)
    pits: list[Pit] = field(default_factory=list)
    intervals: list[Interval] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    race_control: list[RaceControl] = field(default_factory=list)
    weather: list[Weather] = field(default_factory=list)
    overtakes: list[Overtake] = field(default_factory=list)
    team_radio: list[TeamRadio] = field(default_factory=list)
