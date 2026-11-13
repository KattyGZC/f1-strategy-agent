from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from f1_strategy.domain.least_squares import SingularSystemError, least_squares


def fractions(*values: int | str) -> list[Fraction]:
    return [Fraction(value) for value in values]


def test_an_exact_line_is_recovered() -> None:
    rows = [fractions(1, x) for x in (0, 1, 2, 3)]
    targets = fractions(5, 7, 9, 11)

    assert least_squares(rows, targets) == (Fraction(5), Fraction(2))


def test_noisy_points_give_the_least_squares_line() -> None:
    rows = [fractions(1, x) for x in (0, 1, 2)]
    targets = fractions(0, 2, 1)

    assert least_squares(rows, targets) == (Fraction(1, 2), Fraction(1, 2))


def test_a_zero_first_pivot_is_swapped_with_a_later_row() -> None:
    rows = [fractions(0, 1), fractions(1, 0), fractions(1, 1)]
    targets = fractions(3, 2, 5)

    assert least_squares(rows, targets) == (Fraction(2), Fraction(3))


def test_three_unknowns_are_solved_exactly() -> None:
    rows = [fractions(1, 0, 0), fractions(0, 1, 0), fractions(0, 0, 1), fractions(1, 1, 1)]
    targets = fractions(1, 2, 3, 6)

    assert least_squares(rows, targets) == (Fraction(1), Fraction(2), Fraction(3))


def test_a_column_of_zeros_has_no_unique_coefficient() -> None:
    rows = [fractions(1, 0), fractions(1, 0)]

    with pytest.raises(SingularSystemError, match="no unique coefficient 1"):
        least_squares(rows, fractions(1, 2))


def test_two_equal_columns_have_no_unique_coefficients() -> None:
    rows = [fractions(1, 1), fractions(2, 2), fractions(3, 3)]

    with pytest.raises(SingularSystemError, match="no unique coefficient 1"):
        least_squares(rows, fractions(1, 2, 3))


def test_no_rows_have_no_coefficients() -> None:
    with pytest.raises(SingularSystemError, match="0 rows for 0 targets"):
        least_squares([], [])


def test_rows_and_targets_must_match() -> None:
    with pytest.raises(SingularSystemError, match="2 rows for 1 targets"):
        least_squares([fractions(1), fractions(2)], fractions(1))


COEFFICIENT = st.fractions(min_value=-100, max_value=100, max_denominator=1000)
POINT = st.integers(min_value=-50, max_value=50)


@given(
    intercept=COEFFICIENT,
    slope=COEFFICIENT,
    xs=st.lists(POINT, min_size=2, max_size=12, unique=True),
    data=st.data(),
)
def test_any_line_is_recovered_whatever_the_order_of_its_points(
    intercept: Fraction, slope: Fraction, xs: list[int], data: st.DataObject
) -> None:
    points = data.draw(st.permutations(xs))
    rows = [fractions(1, x) for x in points]
    targets = [intercept + slope * x for x in points]

    assert least_squares(rows, targets) == (intercept, slope)
