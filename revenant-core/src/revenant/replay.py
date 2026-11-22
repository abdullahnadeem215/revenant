"""Replay cursor: strict, ordered matching of live calls against recorded events.

The cursor reads only the event list it was given. It never touches the store and never
calls a real function. Each match_* method checks the events at the current position and
returns the matching event without advancing. The caller calls advance() once the step has
succeeded. So a mismatch raises DivergenceError and leaves the cursor where it was, and a
retry of the same call gives the same error.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from revenant.errors import ChainIntegrityError, DivergenceError, ReplayExhaustedError
from revenant.events import Event, EventType, JSONValue

__all__ = ["ReplayCursor", "rebuild_exception"]


class ReplayCursor:
    """Position in a recorded session. Starts after session_start (step 0)."""

    def __init__(self, events: Sequence[Event]) -> None:
        self._events: tuple[Event, ...] = tuple(events)
        if not self._events or self._events[0].type is not EventType.SESSION_START:
            raise ChainIntegrityError(
                "recorded session does not begin with session_start at step 0"
            )
        self._position = 1

    @property
    def position(self) -> int:
        """Step number of the next unconsumed event."""
        return self._position

    def remaining(self) -> int:
        """Number of recorded events not consumed yet."""
        return len(self._events) - self._position

    def advance(self, count: int = 1) -> None:
        """Consume count events. Called only after the matching step has succeeded."""
        if count < 0 or self._position + count > len(self._events):
            raise ReplayExhaustedError("cannot consume more events than the recording holds")
        self._position += count

    def _event_at(self, offset: int, what: str) -> Event:
        index = self._position + offset
        if index >= len(self._events):
            raise ReplayExhaustedError(
                f"replay needed {what} at step {index}, but the recording has no event there"
            )
        return self._events[index]

    def match_call_pair(self, call_type: EventType, name: str, fingerprint: str) -> Event:
        """Check the call at the cursor and its answer right after it.

        Returns the answer event (tool_result or error). Does not advance.
        """
        call = self._event_at(0, f"a {call_type.value} for {name!r}")
        expected = {"type": call_type.value, "name": name, "fingerprint": fingerprint}
        actual: dict[str, JSONValue] = {
            "type": call.type.value,
            "name": call.payload.get("name"),
            "fingerprint": call.payload.get("fingerprint"),
        }
        if call.type is not call_type:
            reason = f"expected a {call_type.value}, recorded a {call.type.value}"
            raise DivergenceError(call.step, expected, actual, reason)
        if call.payload.get("name") != name:
            raise DivergenceError(call.step, expected, actual, "different tool name")
        if call.payload.get("fingerprint") != fingerprint:
            raise DivergenceError(call.step, expected, actual, "arguments differ")
        answer = self._event_at(1, f"the answer to the call {name!r}")
        if answer.type not in (EventType.TOOL_RESULT, EventType.ERROR):
            actual_answer: dict[str, JSONValue] = {"type": answer.type.value}
            raise DivergenceError(
                answer.step,
                {"answers_step": call.step, "types": ["tool_result", "error"]},
                actual_answer,
                "recording has no answer for this call",
            )
        if answer.parent_step != call.step:
            actual_link: dict[str, JSONValue] = {"parent_step": answer.parent_step}
            raise DivergenceError(
                answer.step,
                {"parent_step": call.step},
                actual_link,
                "answer does not point at this call",
            )
        return answer

    def match_nondeterminism(self, kind: str) -> Event:
        """Check the nondeterminism event of this kind at the cursor. Does not advance."""
        event = self._event_at(0, f"a {kind} value")
        expected = {"type": EventType.NONDETERMINISM.value, "kind": kind}
        actual: dict[str, JSONValue] = {
            "type": event.type.value,
            "kind": event.payload.get("kind"),
        }
        if event.type is not EventType.NONDETERMINISM or event.payload.get("kind") != kind:
            raise DivergenceError(event.step, expected, actual, "nondeterministic value differs")
        return event

    def match_final_answer(self) -> Event:
        """Check that the cursor is at the final_answer event. Does not advance."""
        event = self._event_at(0, "a final_answer")
        if event.type is not EventType.FINAL_ANSWER:
            expected = {"type": EventType.FINAL_ANSWER.value}
            actual: dict[str, JSONValue] = {"type": event.type.value}
            raise DivergenceError(event.step, expected, actual, "expected final_answer")
        return event


def _find_exception_class(qualified: str) -> type[BaseException] | None:
    """Look up an exception class that is already imported. Never imports anything, so a
    stored name cannot trigger module code."""
    parts = qualified.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module = sys.modules.get(".".join(parts[:split]))
        if module is None:
            continue
        found: object = module
        for attribute in parts[split:]:
            found = getattr(found, attribute, None)
        if isinstance(found, type) and issubclass(found, BaseException):
            return found
        return None
    return None


def rebuild_exception(answer: Event) -> BaseException:
    """Recreate the exception recorded in an error event.

    Raises DivergenceError if the class is not loaded, cannot be built from the recorded args,
    or builds an exception whose message differs from the recording.
    """
    exc_type = answer.payload.get("exc_type")
    message = answer.payload.get("message")
    args = answer.payload.get("args")
    cls = _find_exception_class(exc_type) if isinstance(exc_type, str) else None
    if cls is None or not isinstance(args, list):
        reason = "recorded exception class is not loaded in this process"
        raise DivergenceError(answer.step, {"exc_type": exc_type}, None, reason)
    try:
        rebuilt = cls(*args)
    except Exception as err:
        reason = "recorded exception cannot be rebuilt from its args"
        raise DivergenceError(answer.step, {"exc_type": exc_type}, None, reason) from err
    if str(rebuilt) != message:
        expected = {"message": message}
        actual: dict[str, JSONValue] = {"message": str(rebuilt)}
        raise DivergenceError(answer.step, expected, actual, "rebuilt message differs")
    return rebuilt
