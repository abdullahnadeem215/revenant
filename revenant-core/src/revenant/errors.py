"""Typed exceptions and warnings raised by Revenant. Every failure is a RevenantError."""

from __future__ import annotations

__all__ = [
    "ChainIntegrityError",
    "ConcurrentCallError",
    "DivergenceError",
    "InvalidForkPointError",
    "PayloadSerializationError",
    "ReplayExhaustedError",
    "RevenantError",
    "SessionNotFoundError",
    "UnconsumedEventsWarning",
]


class RevenantError(Exception):
    """Base class for every error raised by Revenant."""


class DivergenceError(RevenantError):
    """Replay saw something different from the recording."""

    def __init__(self, step: int, expected: object, actual: object, reason: str) -> None:
        self.step = step
        self.expected = expected
        self.actual = actual
        self.reason = reason
        super().__init__(
            f"divergence at step {step}: {reason} (expected={expected!r}, actual={actual!r})"
        )


class ReplayExhaustedError(RevenantError):
    """Replay needed another recorded event but none remain."""


class ChainIntegrityError(RevenantError):
    """The hash chain of a session is broken or an append does not continue it."""


class SessionNotFoundError(RevenantError):
    """The requested session id does not exist in the store."""


class InvalidForkPointError(RevenantError):
    """The fork step is out of range or does not point at a call event."""


class ConcurrentCallError(RevenantError):
    """A wrapped call started while another one was still active on the same recorder."""

    def __init__(self, active: str, attempted: str) -> None:
        self.active = active
        self.attempted = attempted
        super().__init__(
            f"{attempted!r} started while {active!r} is still active; "
            "v1 supports sequential calls only"
        )


class PayloadSerializationError(RevenantError):
    """A payload is not plain JSON and cannot be canonically serialized."""


class UnconsumedEventsWarning(Warning):
    """Replay closed while recorded events were still unconsumed."""

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(f"{count} recorded event(s) were not consumed during replay")
