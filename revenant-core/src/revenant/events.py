"""Event model, canonical JSON, hashing, fingerprints and default redaction."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from revenant.errors import PayloadSerializationError

if TYPE_CHECKING:
    JSONValue: TypeAlias = (
        bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None
    )
    Redactor: TypeAlias = Callable[[JSONValue], JSONValue]
else:
    # At runtime Pydantic sees Any; canonical_json() performs the strict check.
    JSONValue = Any
    Redactor = Callable[[Any], Any]

__all__ = [
    "CALL_TYPES",
    "GENESIS_HASH",
    "REDACTED",
    "SENSITIVE_KEYS",
    "Event",
    "EventType",
    "JSONValue",
    "Redactor",
    "build_event",
    "canonical_json",
    "compute_hash",
    "default_redactor",
    "request_fingerprint",
    "to_json_value",
    "utc_timestamp",
]

GENESIS_HASH: Final[str] = "0" * 64
"""prev_hash of the first event (step 0) of every session."""

REDACTED: Final[str] = "[REDACTED]"
SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "password",
        "token",
        "secret",
        "authorization",
        "cookie",
        "bearer",
        "private_key",
    }
)


class EventType(StrEnum):
    SESSION_START = "session_start"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    NONDETERMINISM = "nondeterminism"
    FINAL_ANSWER = "final_answer"


CALL_TYPES: Final[frozenset[EventType]] = frozenset({EventType.LLM_CALL, EventType.TOOL_CALL})


def _check_json(value: object, path: str, depth: int = 0) -> None:
    """Raise PayloadSerializationError unless value is plain JSON.

    Messages name the path and type only, never the value, so secrets cannot leak.
    """
    if depth > 200:
        raise PayloadSerializationError(f"payload nested too deeply at {path}")
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise PayloadSerializationError(f"non-finite float at {path}")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _check_json(item, f"{path}[{index}]", depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise PayloadSerializationError(
                    f"non-string key of type {type(key).__name__} at {path}"
                )
            _check_json(item, f"{path}.{key}", depth + 1)
        return
    raise PayloadSerializationError(f"value of type {type(value).__name__} at {path} is not JSON")


def canonical_json(obj: object) -> str:
    """The single serializer used for hashing, fingerprints, storage and diffing.

    Sorted keys, no whitespace, ASCII only, no NaN. Anything that is not plain JSON
    (tuples, sets, bytes, datetimes, custom objects, non-str keys) raises
    PayloadSerializationError; nothing is ever converted lossily.
    """
    _check_json(obj, "$")
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def to_json_value(obj: object) -> JSONValue:
    """Validate obj and return an independent deep copy as plain JSON."""
    result: JSONValue = json.loads(canonical_json(obj))
    return result


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_fingerprint(name: str, args: JSONValue) -> str:
    """Stable fingerprint of a call. Callers pass post-redaction args."""
    return _sha256(canonical_json({"name": name, "args": args}))


def compute_hash(prev_hash: str, body: Mapping[str, JSONValue]) -> str:
    """sha256(prev_hash + canonical_json(body)), hex-encoded."""
    return _sha256(prev_hash + canonical_json(dict(body)))


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def default_redactor(value: JSONValue) -> JSONValue:
    """Mask values of SENSITIVE_KEYS (case-insensitive) at any depth. Returns a new object."""
    if isinstance(value, dict):
        return {
            key: REDACTED
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS
            else default_redactor(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [default_redactor(item) for item in value]
    return value


class Event(BaseModel):
    """One immutable, hash-chained event. See design section 2."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    step: int = Field(ge=0)
    type: EventType
    payload: dict[str, JSONValue]
    timestamp: str
    parent_step: int | None = Field(default=None, ge=0)
    prev_hash: str
    hash: str

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, value: object) -> object:
        # Strict mode would reject the plain string read back from storage.
        return EventType(value) if isinstance(value, str) else value

    @field_validator("payload", mode="before")
    @classmethod
    def _plain_json_payload(cls, value: object) -> object:
        if type(value) is not dict:
            raise PayloadSerializationError("event payload must be a JSON object")
        # Validates strictly and stores an independent copy the caller cannot mutate.
        return to_json_value(value)

    def hash_body(self) -> dict[str, JSONValue]:
        """Every field except hash, as plain JSON."""
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "step": self.step,
            "type": self.type.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "parent_step": self.parent_step,
            "prev_hash": self.prev_hash,
        }

    def computed_hash(self) -> str:
        return compute_hash(self.prev_hash, self.hash_body())


def build_event(
    *,
    session_id: str,
    step: int,
    type: EventType,
    payload: Mapping[str, JSONValue],
    prev_hash: str,
    timestamp: str | None = None,
    parent_step: int | None = None,
    event_id: str | None = None,
) -> Event:
    """Create an Event with its hash filled in."""
    draft = Event(
        event_id=event_id or uuid4().hex,
        session_id=session_id,
        step=step,
        type=type,
        payload=dict(payload),
        timestamp=timestamp or utc_timestamp(),
        parent_step=parent_step,
        prev_hash=prev_hash,
        hash="",
    )
    return draft.model_copy(update={"hash": draft.computed_hash()})
