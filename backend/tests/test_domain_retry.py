import pytest

from f1_strategy.domain.retry import RetryPolicy


def test_a_retry_policy_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match=r"^max_attempts must be at least 1, got 0$"):
        RetryPolicy(0, 1.0)


def test_the_backoff_doubles_from_its_base() -> None:
    policy = RetryPolicy(4, 0.25)

    assert [policy.backoff_s(attempt) for attempt in (1, 2, 3)] == [0.25, 0.5, 1.0]
