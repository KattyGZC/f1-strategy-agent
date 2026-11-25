from dataclasses import replace
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from f1_strategy.domain.assistant import (
    CitationEvent,
    CitationLedger,
    RowSource,
    RowTable,
    source_id,
)

STINT = RowSource(
    table=RowTable.STINT,
    session_key=9590,
    meeting_name="Italian Grand Prix",
    year=2024,
    key={"driver_number": 4, "stint_number": 2},
    values={"compound": "HARD", "lap_start": 17, "lap_end": 53},
)
WEATHER = RowSource(
    table=RowTable.WEATHER,
    session_key=9590,
    meeting_name="Italian Grand Prix",
    year=2024,
    key={"date": datetime(2024, 9, 1, 13, 10, tzinfo=UTC)},
    values={"track_temperature_c": 44.1, "rainfall": False},
)


def test_a_row_source_id_names_its_table_race_and_key_in_order() -> None:
    assert source_id(STINT) == "row:stint:9590:4:2"


def test_a_row_keyed_by_an_instant_names_it_in_utc_iso_format() -> None:
    assert source_id(WEATHER) == "row:weather:9590:2024-09-01T13:10:00+00:00"


def test_a_session_row_is_keyed_by_its_session_alone() -> None:
    race = RowSource(
        table=RowTable.SESSION,
        session_key=9590,
        meeting_name="Italian Grand Prix",
        year=2024,
        key={},
        values={"session_name": "Race"},
    )

    assert source_id(race) == "row:session:9590"


def test_the_first_citation_of_a_source_carries_it_and_later_ones_only_its_number() -> None:
    ledger = CitationLedger()
    ledger.record(STINT)
    ledger.record(WEATHER)

    assert ledger.cite(source_id(WEATHER)) == CitationEvent(number=1, source=WEATHER)
    assert ledger.cite(source_id(STINT)) == CitationEvent(number=2, source=STINT)
    assert ledger.cite(source_id(WEATHER)) == CitationEvent(number=1, source=None)


def test_a_citation_of_a_source_no_tool_returned_is_dropped() -> None:
    ledger = CitationLedger()
    ledger.record(STINT)

    assert ledger.cite("row:stint:9590:16:1") is None
    assert ledger.cite(source_id(STINT)) == CitationEvent(number=1, source=STINT)


def test_a_source_returned_twice_keeps_its_first_values() -> None:
    ledger = CitationLedger()
    ledger.record(STINT)
    ledger.record(replace(STINT, values={"compound": "SOFT"}))

    assert ledger.cite(source_id(STINT)) == CitationEvent(number=1, source=STINT)


@given(st.lists(st.sampled_from(range(4)), max_size=20))
def test_citations_are_numbered_in_order_of_first_use_and_carry_their_source_once(
    order: list[int],
) -> None:
    sources = [
        replace(STINT, key={"driver_number": number, "stint_number": 1}) for number in range(4)
    ]
    ledger = CitationLedger()
    for source in sources:
        ledger.record(source)

    citations = [ledger.cite(source_id(sources[index])) for index in order]

    first_uses = list(dict.fromkeys(order))
    expected = [
        CitationEvent(
            number=first_uses.index(index) + 1,
            source=sources[index] if order.index(index) == position else None,
        )
        for position, index in enumerate(order)
    ]
    assert citations == expected
