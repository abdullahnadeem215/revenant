from __future__ import annotations

import pytest

from revenant import errors


@pytest.mark.parametrize(
    "cls",
    [
        errors.DivergenceError,
        errors.ReplayExhaustedError,
        errors.ChainIntegrityError,
        errors.SessionNotFoundError,
        errors.InvalidForkPointError,
        errors.ConcurrentCallError,
        errors.PayloadSerializationError,
    ],
)
def test_every_error_is_a_revenant_error(cls: type[Exception]) -> None:
    assert issubclass(cls, errors.RevenantError)
    assert issubclass(errors.RevenantError, Exception)


def test_divergence_error_exposes_fields() -> None:
    err = errors.DivergenceError(3, {"name": "a"}, {"name": "b"}, "name differs")
    assert (err.step, err.expected, err.actual, err.reason) == (
        3,
        {"name": "a"},
        {"name": "b"},
        "name differs",
    )


def test_concurrent_call_error_exposes_names() -> None:
    err = errors.ConcurrentCallError(active="search", attempted="fetch")
    assert (err.active, err.attempted) == ("search", "fetch")


def test_unconsumed_events_warning_carries_count() -> None:
    warning = errors.UnconsumedEventsWarning(4)
    assert isinstance(warning, Warning)
    assert not isinstance(warning, errors.RevenantError)
    assert warning.count == 4
