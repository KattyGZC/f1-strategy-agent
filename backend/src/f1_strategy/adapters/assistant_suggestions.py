"""The questions the Assistant tab suggests (ADR 0023). Each must be answerable from the clean
model with at least one citation; the golden questions check that every run (phase 6, T15). A
declined question offers one of them, by id, never text from the model."""

from dataclasses import dataclass
from enum import StrEnum


class SuggestionId(StrEnum):
    NORRIS_MONZA_STOPS = "norris_monza_stops"
    SILVERSTONE_WINNER = "silverstone_winner"
    LECLERC_MONZA_TWO_STOPS = "leclerc_monza_two_stops"
    TWO_COMPOUNDS_RULE = "two_compounds_rule"


@dataclass(frozen=True)
class Suggestion:
    suggestion_id: SuggestionId
    question: str


SUGGESTIONS = (
    Suggestion(
        SuggestionId.NORRIS_MONZA_STOPS,
        "How many stops did Norris make at Monza 2024, and on which compounds?",
    ),
    Suggestion(
        SuggestionId.SILVERSTONE_WINNER,
        "Who won the 2024 British Grand Prix, and where did they start?",
    ),
    Suggestion(
        SuggestionId.LECLERC_MONZA_TWO_STOPS, "Should Leclerc have stopped twice at Monza 2024?"
    ),
    Suggestion(
        SuggestionId.TWO_COMPOUNDS_RULE,
        "What do the rules say about using two tyre compounds in a dry race?",
    ),
)
