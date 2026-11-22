"""Recorder: wraps LLM and tool functions and writes each call into a TraceStore session.

Phase 3 implements record mode only. Replay and fork come in later phases.

A call is written only after the real function returns: first the call event, then a
tool_result event (or an error event if the function raised) whose parent_step points at
the call. A call that never completes leaves nothing in the store.
"""

from __future__ import annotations

import functools
import inspect
import random as stdlib_random
import uuid
import warnings
from collections.abc import Callable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal, ParamSpec, Self, TypeVar, cast, overload

from revenant.errors import (
    ChainIntegrityError,
    ConcurrentCallError,
    DivergenceError,
    RevenantError,
    UnconsumedEventsWarning,
)
from revenant.events import (
    GENESIS_HASH,
    EventType,
    JSONValue,
    Redactor,
    build_event,
    canonical_json,
    default_redactor,
    request_fingerprint,
    to_json_value,
)
from revenant.replay import ReplayCursor, rebuild_exception
from revenant.store import TraceStore

P = ParamSpec("P")
R = TypeVar("R")

__all__ = ["Recorder"]


def _prepare(redactor: Redactor, value: object) -> JSONValue:
    """Redact, then validate and copy as plain JSON. Writes nothing.

    A raising hook is wrapped in RevenantError. Non-JSON values raise
    PayloadSerializationError from to_json_value.
    """
    try:
        redacted = redactor(cast("JSONValue", value))
    except Exception as exc:
        raise RevenantError("redaction hook failed; nothing was stored") from exc
    return to_json_value(redacted)


def _bind_arguments(
    signature: inspect.Signature, args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, JSONValue]:
    """Map a call onto the function's parameter names, with defaults applied.

    *args is stored as a list, because tuples are not JSON.
    """
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    arguments: dict[str, JSONValue] = {}
    for name, value in bound.arguments.items():
        if signature.parameters[name].kind is inspect.Parameter.VAR_POSITIONAL:
            value = list(value)
        arguments[name] = value
    return arguments


def _default_name(fn: object) -> str:
    qualname = getattr(fn, "__qualname__", None)
    return qualname if isinstance(qualname, str) else type(fn).__qualname__


class Recorder:
    """Records wrapped calls and nondeterministic values into one session.

    Typical use:

        with Recorder.record(store, metadata={"app": "demo"}) as rec:
            ask = rec.wrap_llm(llm, name="llm")
            answer = ask("hello")
    """

    def __init__(
        self,
        store: TraceStore,
        session_id: str,
        redactor: Redactor,
        cursor: ReplayCursor | None = None,
    ) -> None:
        self._store = store
        self._redactor = redactor
        self._cursor = cursor
        self.session_id = session_id
        self.mode: Literal["record", "replay"] = "record" if cursor is None else "replay"
        self._next_step = 0
        self._prev_hash = GENESIS_HASH
        self._active: str | None = None
        self._closed = False
        self._failure: str | None = None

    @classmethod
    def record(
        cls,
        store: TraceStore,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, JSONValue] | None = None,
        redactor: Redactor = default_redactor,
    ) -> Self:
        """Create a new session and write its session_start event.

        Metadata is redacted before the session is created, so a failing hook leaves
        nothing behind.
        """
        cleaned = _prepare(redactor, dict(metadata or {}))
        sid = session_id if session_id is not None else uuid.uuid4().hex
        store.create_session(sid)
        recorder = cls(store, sid, redactor)
        recorder._write(EventType.SESSION_START, {"metadata": cleaned}, None)
        return recorder

    @classmethod
    def replay(
        cls,
        store: TraceStore,
        session_id: str,
        *,
        redactor: Redactor = default_redactor,
    ) -> Self:
        """Open a recorded session for replay. Nothing is written and no real function runs.

        Raises SessionNotFoundError for an unknown id. Raises ChainIntegrityError if the hash
        chain does not verify, or if the session does not begin with session_start at step 0.
        """
        events = store.load_session(session_id)
        if not store.verify_chain(session_id):
            raise ChainIntegrityError(f"session {session_id!r} failed hash-chain verification")
        return cls(store, session_id, redactor, ReplayCursor(events))

    def _write(
        self, event_type: EventType, payload: dict[str, JSONValue], parent_step: int | None
    ) -> int:
        """Append one event at the next step. Advances state only after the store accepts it."""
        event = build_event(
            session_id=self.session_id,
            step=self._next_step,
            type=event_type,
            payload=payload,
            prev_hash=self._prev_hash,
            parent_step=parent_step,
        )
        self._store.append_event(event)
        self._next_step += 1
        self._prev_hash = event.hash
        return event.step

    def _ensure_usable(self) -> None:
        if self._failure is not None:
            raise RevenantError(f"{self._failure}; the recorder is closed")
        if self._closed:
            raise RevenantError("recorder is closed")

    def _fail_closed(self, reason: str) -> None:
        """Close the recorder because a completed call could not be fully recorded."""
        self._failure = reason
        self._closed = True

    @contextmanager
    def _slot(self, name: str) -> Iterator[None]:
        """Mark one wrapped call or nondeterminism op as active. Calls must not overlap."""
        self._ensure_usable()
        if self._active is not None:
            raise ConcurrentCallError(active=self._active, attempted=name)
        self._active = name
        try:
            yield
        finally:
            self._active = None

    def _nondeterminism(self, kind: str, produce: Callable[[], JSONValue]) -> JSONValue:
        """Record a fresh value in record mode. In replay mode, return the recorded value."""
        if self._cursor is None:
            value = produce()
            self._write(EventType.NONDETERMINISM, {"kind": kind, "value": value}, None)
            return value
        event = self._cursor.match_nondeterminism(kind)
        self._cursor.advance(1)
        return event.payload.get("value")

    def _replay_call(self, call_type: EventType, name: str, args: JSONValue) -> JSONValue:
        """Replay one wrapped call. No real function runs. The cursor moves only on success."""
        if self._cursor is None:
            raise RevenantError("replay requested on a recorder that is not in replay mode")
        answer = self._cursor.match_call_pair(call_type, name, request_fingerprint(name, args))
        if answer.type is EventType.ERROR:
            error = rebuild_exception(answer)
            self._cursor.advance(2)
            raise error
        self._cursor.advance(2)
        return answer.payload.get("result")

    def _write_call(self, call_type: EventType, name: str, args: JSONValue) -> int:
        """Write the call event for a finished call. args are already redacted and validated."""
        payload: dict[str, JSONValue] = {
            "name": name,
            "args": args,
            "fingerprint": request_fingerprint(name, args),
        }
        return self._write(call_type, payload, None)

    def _record_success(
        self, call_type: EventType, name: str, args: JSONValue, result: object
    ) -> None:
        """Write the call and its tool_result after the real function returned.

        The result is prepared before the first write, so a result that is not JSON stores
        nothing for this call. The call still happened, so the recorder then refuses further
        calls instead of recording a gap.
        """
        try:
            payload = _prepare(self._redactor, result)
            call_step = self._write_call(call_type, name, args)
            self._write(EventType.TOOL_RESULT, {"name": name, "result": payload}, call_step)
        except BaseException as exc:
            self._fail_closed(
                f"call {name!r} ran but its result could not be recorded ({type(exc).__name__})"
            )
            raise

    def _record_failure(
        self, call_type: EventType, name: str, args: JSONValue, exc: Exception
    ) -> None:
        """Write the call and its error after the real function raised.

        The exception text and args go through the redactor. Same failure rule as
        _record_success.
        """
        try:
            error: dict[str, JSONValue] = {
                "name": name,
                "exc_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": _prepare(self._redactor, str(exc)),
                "args": _prepare(self._redactor, list(exc.args)),
            }
            call_step = self._write_call(call_type, name, args)
            self._write(EventType.ERROR, error, call_step)
        except BaseException as err:
            self._fail_closed(
                f"call {name!r} raised, but its error could not be recorded ({type(err).__name__})"
            )
            raise

    def _wrap(
        self, fn: Callable[..., Any], call_type: EventType, name: str | None
    ) -> Callable[..., Any]:
        call_name = name if name is not None else _default_name(fn)
        signature = inspect.signature(fn)

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: object, **kwargs: object) -> object:
                with self._slot(call_name):
                    args_json = _prepare(self._redactor, _bind_arguments(signature, args, kwargs))
                    if self._cursor is not None:
                        return self._replay_call(call_type, call_name, args_json)
                    try:
                        result = await fn(*args, **kwargs)
                    except Exception as exc:
                        self._record_failure(call_type, call_name, args_json, exc)
                        raise
                    self._record_success(call_type, call_name, args_json, result)
                    return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: object, **kwargs: object) -> object:
            with self._slot(call_name):
                args_json = _prepare(self._redactor, _bind_arguments(signature, args, kwargs))
                if self._cursor is not None:
                    return self._replay_call(call_type, call_name, args_json)
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    self._record_failure(call_type, call_name, args_json, exc)
                    raise
                self._record_success(call_type, call_name, args_json, result)
                return result

        return sync_wrapper

    @overload
    def wrap_llm(
        self, fn: Callable[P, Coroutine[Any, Any, R]], *, name: str | None = None
    ) -> Callable[P, Coroutine[Any, Any, R]]: ...
    @overload
    def wrap_llm(self, fn: Callable[P, R], *, name: str | None = None) -> Callable[P, R]: ...
    def wrap_llm(self, fn: Callable[..., Any], *, name: str | None = None) -> Callable[..., Any]:
        """Wrap an LLM call. Sync functions stay sync, async functions stay async."""
        return self._wrap(fn, EventType.LLM_CALL, name)

    @overload
    def wrap_tool(
        self, fn: Callable[P, Coroutine[Any, Any, R]], *, name: str | None = None
    ) -> Callable[P, Coroutine[Any, Any, R]]: ...
    @overload
    def wrap_tool(self, fn: Callable[P, R], *, name: str | None = None) -> Callable[P, R]: ...
    def wrap_tool(self, fn: Callable[..., Any], *, name: str | None = None) -> Callable[..., Any]:
        """Wrap a tool call. Sync functions stay sync, async functions stay async."""
        return self._wrap(fn, EventType.TOOL_CALL, name)

    def now(self) -> datetime:
        """Timezone-aware UTC time. The recorded string is parsed back, so the returned value
        is the one replay will return."""
        with self._slot("now"):
            stamp = self._nondeterminism("now", lambda: datetime.now(UTC).isoformat())
            if not isinstance(stamp, str):
                raise RevenantError("recorded 'now' value is not a timestamp string")
            return datetime.fromisoformat(stamp)

    def uuid4(self) -> uuid.UUID:
        with self._slot("uuid4"):
            text = self._nondeterminism("uuid4", lambda: str(uuid.uuid4()))
            if not isinstance(text, str):
                raise RevenantError("recorded 'uuid4' value is not a string")
            return uuid.UUID(text)

    def random(self) -> float:
        """A pseudo-random float in [0, 1). Not for security use."""
        with self._slot("random"):
            value = self._nondeterminism("random", lambda: stdlib_random.random())  # noqa: S311
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise RevenantError("recorded 'random' value is not a number")
            return float(value)

    def final_answer(self, value: JSONValue) -> JSONValue:
        with self._slot("final_answer"):
            cleaned = _prepare(self._redactor, value)
            if self._cursor is None:
                self._write(EventType.FINAL_ANSWER, {"value": cleaned}, None)
                return cleaned
            event = self._cursor.match_final_answer()
            recorded = event.payload.get("value")
            if canonical_json(recorded) != canonical_json(cleaned):
                raise DivergenceError(
                    event.step,
                    {"value": recorded},
                    {"value": cleaned},
                    "final answer differs from the recording",
                )
            self._cursor.advance(1)
            return cleaned

    def close(self) -> None:
        """Stop accepting calls. Idempotent. The store is owned by the caller and stays open.

        In replay mode, warn with UnconsumedEventsWarning if recorded events were not used.
        """
        if self._closed:
            return
        self._closed = True
        if self._cursor is not None and self._cursor.remaining() > 0:
            warnings.warn(UnconsumedEventsWarning(self._cursor.remaining()), stacklevel=2)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
