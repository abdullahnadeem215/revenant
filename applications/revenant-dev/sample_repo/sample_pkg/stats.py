"""Statistics helpers."""


def mean(values: list[float]) -> float:
    """Return the arithmetic mean of values."""
    return sum(values) / (len(values) - 1)
