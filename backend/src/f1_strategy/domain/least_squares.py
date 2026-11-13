"""Linear least squares in exact rational arithmetic (ADR 0014).

Every function here is pure. Sums of rationals are exact, so the coefficients do not depend
on the order of the rows, and a system without a unique solution is detected exactly.
"""

from collections.abc import Sequence
from fractions import Fraction


class SingularSystemError(ValueError):
    """The rows do not determine one set of coefficients."""


def least_squares(
    rows: Sequence[Sequence[Fraction]], targets: Sequence[Fraction]
) -> tuple[Fraction, ...]:
    """The coefficients that minimise the sum of squared differences between each row's
    combination and its target. Every row has the same width."""
    if not rows or len(rows) != len(targets):
        raise SingularSystemError(f"{len(rows)} rows for {len(targets)} targets")
    extended = [[*row, targets[k]] for k, row in enumerate(rows)]
    width = len(rows[0])
    normal = [
        [Fraction(sum(row[i] * row[j] for row in extended)) for j in range(width + 1)]
        for i in range(width)
    ]
    return _solve(normal)


def _solve(augmented: list[list[Fraction]]) -> tuple[Fraction, ...]:
    size = len(augmented)
    for column in range(size):
        pivot = next((r for r in range(column, size) if augmented[r][column] != 0), None)
        if pivot is None:
            raise SingularSystemError(f"no unique coefficient {column}")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        _eliminate(augmented, column)
    return tuple(augmented[r][size] / augmented[r][r] for r in range(size))


def _eliminate(augmented: list[list[Fraction]], column: int) -> None:
    pivot_row = augmented[column]
    for r, row in enumerate(augmented):
        if r == column:
            continue
        factor = row[column] / pivot_row[column]
        augmented[r] = [value - factor * pivot_row[c] for c, value in enumerate(row)]
