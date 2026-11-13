from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from f1_strategy.domain.clean import Compound, Lap, Stint
from f1_strategy.domain.tyres import Tyre, TyreLookup

SESSION = 9472


def lap(driver_number: int, lap_number: int) -> Lap:
    return Lap(
        SESSION, driver_number, lap_number, None, Decimal("92.5"),
        None, None, None, None, None, None, is_pit_out_lap=False,
    )  # fmt: skip


def stint(
    driver_number: int,
    stint_number: int,
    laps: tuple[int | None, int | None],
    *,
    compound: Compound = Compound.SOFT,
    tyre_age_at_start: int = 0,
) -> Stint:
    lap_start, lap_end = laps
    return Stint(
        SESSION, driver_number, stint_number, compound, lap_start, lap_end, tyre_age_at_start
    )


def test_a_lap_has_the_compound_and_age_of_its_stint() -> None:
    tyres = TyreLookup([stint(1, 2, (5, 20), compound=Compound.MEDIUM, tyre_age_at_start=3)])

    assert tyres.tyre_on(lap(1, 7)) == Tyre(Compound.MEDIUM, 5)


def test_the_first_lap_of_a_stint_is_at_its_age_at_start() -> None:
    tyres = TyreLookup([stint(1, 1, (5, 20), tyre_age_at_start=3)])

    assert tyres.tyre_on(lap(1, 5)) == Tyre(Compound.SOFT, 3)


def test_the_last_lap_of_a_stint_has_its_tyre() -> None:
    tyres = TyreLookup([stint(1, 1, (1, 10), tyre_age_at_start=2)])

    assert tyres.tyre_on(lap(1, 10)) == Tyre(Compound.SOFT, 11)


@pytest.mark.parametrize("stint_order", [(0, 1), (1, 0)])
def test_a_shared_boundary_lap_belongs_to_the_new_stint(stint_order: tuple[int, int]) -> None:
    stints = [stint(1, 1, (1, 15)), stint(1, 2, (15, 40), compound=Compound.HARD)]
    tyres = TyreLookup([stints[index] for index in stint_order])

    assert tyres.tyre_on(lap(1, 15)) == Tyre(Compound.HARD, 0)


@pytest.mark.parametrize("laps", [(None, None), (None, 5)])
def test_a_newer_stint_without_a_range_leaves_the_lap_to_an_older_one(
    laps: tuple[int | None, int | None],
) -> None:
    tyres = TyreLookup(
        [stint(1, 1, (1, 10), compound=Compound.MEDIUM), stint(1, 2, laps, compound=Compound.HARD)]
    )

    assert tyres.tyre_on(lap(1, 3)) == Tyre(Compound.MEDIUM, 2)


def test_a_lap_after_the_last_stint_has_no_tyre() -> None:
    tyres = TyreLookup([stint(1, 1, (1, 20)), stint(1, 2, (None, None))])

    assert tyres.tyre_on(lap(1, 21)) is None


def test_another_drivers_stint_gives_no_tyre() -> None:
    tyres = TyreLookup([stint(16, 1, (1, 57))])

    assert tyres.tyre_on(lap(1, 3)) is None


def test_no_stints_give_no_tyre() -> None:
    assert TyreLookup([]).tyre_on(lap(1, 3)) is None


STINT_LENGTHS = st.lists(st.integers(min_value=1, max_value=30), min_size=1, max_size=5)


@given(lengths=STINT_LENGTHS, data=st.data())
def test_the_tyre_does_not_depend_on_the_order_of_the_stints(
    lengths: list[int], data: st.DataObject
) -> None:
    shared = data.draw(st.lists(st.booleans(), min_size=len(lengths), max_size=len(lengths)))
    stints, lap_start = [], 1
    for number, (length, shares_boundary) in enumerate(zip(lengths, shared, strict=True), 1):
        stints.append(stint(1, number, (lap_start, lap_start + length - 1)))
        lap_start += length - 1 if shares_boundary else length
    shuffled = data.draw(st.permutations(stints))
    laps = [lap(1, lap_number) for lap_number in range(1, lap_start + 2)]

    in_order, out_of_order = TyreLookup(stints), TyreLookup(shuffled)

    assert [out_of_order.tyre_on(one) for one in laps] == [in_order.tyre_on(one) for one in laps]
