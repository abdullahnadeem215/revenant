"""Structured comparison of two recorded sessions.

Pure: takes two event sequences and returns data. Ignores event_id, session_id, timestamp,
prev_hash and hash, so the same run recorded twice compares as identical. Payloads are
compared through canonical_json, so 1 and True are different values.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from revenant.events import CALL_TYPES, Event, EventType, JSONValue, canonical_json

__all__ = ["DivergenceKind", "StepDiff", "TraceDiff", "diff_sessions"]

RESULT_TYPES = frozenset({EventType.TOOL_RESULT, EventType.ERROR})


class DivergenceKind(StrEnum):
    DIFFERENT_TOOL = "different_tool"
    ARGS = "args"
    RESULT = "result"
    LENGTH = "length"


@dataclass(frozen=True)
class StepDiff:
    step: int
    kind: DivergenceKind
    a: JSONValue
    b: JSONValue


@dataclass(frozen=True)
class TraceDiff:
    first_divergent_step: int | None
    kind: DivergenceKind | None
    differing_steps: tuple[StepDiff, ...]
    len_a: int
    len_b: int


def _view(event: Event | None) -> JSONValue:
    """A comparable view of an event for the diff output. None when the step is missing."""
    if event is None:
        return None
    return {"type": event.type.value, "parent_step": event.parent_step, "payload": event.payload}


def _same(left: object, right: object) -> bool:
    return canonical_json(left) == canonical_json(right)


def _classify(a: Event, b: Event) -> DivergenceKind | None:
    """The divergence kind for two events at the same step, or None when they match."""
    if a.type in CALL_TYPES or b.type in CALL_TYPES:
        if a.type is not b.type or a.payload.get("name") != b.payload.get("name"):
            return DivergenceKind.DIFFERENT_TOOL
        if not _same(a.payload.get("args"), b.payload.get("args")):
            return DivergenceKind.ARGS
    elif a.type is not b.type:
        # tool_result and error are both answers, so a change between them is a result change.
        if a.type in RESULT_TYPES and b.type in RESULT_TYPES:
            return DivergenceKind.RESULT
        return DivergenceKind.DIFFERENT_TOOL
    if a.parent_step != b.parent_step or not _same(a.payload, b.payload):
        return DivergenceKind.RESULT
    return None


def diff_sessions(a: Sequence[Event], b: Sequence[Event]) -> TraceDiff:
    """Compare two sessions step by step and report every differing step."""
    differing: list[StepDiff] = []
    shared = min(len(a), len(b))
    for index in range(shared):
        kind = _classify(a[index], b[index])
        if kind is not None:
            differing.append(StepDiff(index, kind, _view(a[index]), _view(b[index])))
    for index in range(shared, max(len(a), len(b))):
        left = a[index] if index < len(a) else None
        right = b[index] if index < len(b) else None
        differing.append(StepDiff(index, DivergenceKind.LENGTH, _view(left), _view(right)))
    first = differing[0] if differing else None
    return TraceDiff(
        first_divergent_step=first.step if first is not None else None,
        kind=first.kind if first is not None else None,
        differing_steps=tuple(differing),
        len_a=len(a),
        len_b=len(b),
    )
