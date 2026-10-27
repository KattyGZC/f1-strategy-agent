from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    backoff_base_s: float

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")

    def backoff_s(self, attempt: int) -> float:
        return self.backoff_base_s * 2.0 ** (attempt - 1)
