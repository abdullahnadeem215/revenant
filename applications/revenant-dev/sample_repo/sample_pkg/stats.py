"""Statistics helpers. Contains one planted bug for the demo agent to find."""


def mean(values: list[float]) -> float:
    """Return the arithmetic mean of values."""
    return sum(values) / (len(values) - 1)
