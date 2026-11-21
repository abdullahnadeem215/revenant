"""Recorder: wraps LLM and tool functions and writes each call into a TraceStore session.

Phase 3 implements record mode only. Replay and fork come in later phases.

Each successful wrapped call writes a call event followed by a tool_result event whose
parent_step points at the call. A call that raises writes an error event instead.
"""

from __future__ import annotations

import functools
import inspect
import random as stdlib_random
import uuid
from collections.abc import Callable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal, ParamSpec, Self, TypeVar, cast, overload

from revenant.errors import ConcurrentCallError, RevenantError
from revenant.events import (
    GENESIS_HASH,
    EventType,
    JSONValue,
    Redactor,
    build_event,
    default_redactor,
    request_fingerprint,
    to_json_value,
)
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

    def __init__(self, store: TraceStore, session_id: str, redactor: Redactor) -> None:
        self._store = store
        self._redactor = redactor
        self.session_id = session_id
        self.mode: Literal["record"] = "record"
        self._next_step = 0
        self._prev_hash = GENESIS_HASH
        self._active: str | None = None
        self._closed = False
        self._broken: str | None = None

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
        if self._closed:
            raise RevenantError("recorder is closed")
        if self._broken is not None:
            raise RevenantError(f"recorder is unusable after a failed write: {self._broken}")

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

    def _write_call(self, call_type: EventType, name: str, arguments: dict[str, JSONValue]) -> int:
        """Write the call event. Redaction and serialization happen before anything is stored."""
        cleaned = _prepare(self._redactor, arguments)
        payload: dict[str, JSONValue] = {
            "name": name,
            "args": cleaned,
            "fingerprint": request_fingerprint(name, cleaned),
        }
        return self._write(call_type, payload, None)

    def _record_answer(self, call_step: int, name: str, result: object) -> None:
        """Write tool_result for a call that returned. Any failure leaves the recorder unusable."""
        try:
            payload: dict[str, JSONValue] = {
                "name": name,
                "result": _prepare(self._redactor, result),
            }
            self._write(EventType.TOOL_RESULT, payload, call_step)
        except BaseException as exc:
            self._broken = f"result of {name!r} was not recorded ({type(exc).__name__})"
            raise

    def _record_error(self, call_step: int, name: str, exc: Exception) -> None:
        """Write error for a call that raised. Any failure leaves the recorder unusable."""
        try:
            payload: dict[str, JSONValue] = {
                "name": name,
                "exc_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": str(exc),
                "args": _prepare(self._redactor, list(exc.args)),
            }
            self._write(EventType.ERROR, payload, call_step)
        except BaseException as err:
            self._broken = f"error of {name!r} was not recorded ({type(err).__name__})"
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
                    arguments = _bind_arguments(signature, args, kwargs)
                    call_step = self._write_call(call_type, call_name, arguments)
                    try:
                        result = await fn(*args, **kwargs)
                    except Exception as exc:
                        self._record_error(call_step, call_name, exc)
                        raise
                    except BaseException:
                        self._broken = f"call {call_name!r} was interrupted before it returned"
                        raise
                    self._record_answer(call_step, call_name, result)
                    return result

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: object, **kwargs: object) -> object:
            with self._slot(call_name):
                arguments = _bind_arguments(signature, args, kwargs)
                call_step = self._write_call(call_type, call_name, arguments)
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    self._record_error(call_step, call_name, exc)
                    raise
                except BaseException:
                    self._broken = f"call {call_name!r} was interrupted before it returned"
                    raise
                self._record_answer(call_step, call_name, result)
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
            stamp = datetime.now(UTC).isoformat()
            self._write(EventType.NONDETERMINISM, {"kind": "now", "value": stamp}, None)
            return datetime.fromisoformat(stamp)

    def uuid4(self) -> uuid.UUID:
        with self._slot("uuid4"):
            value = uuid.uuid4()
            self._write(EventType.NONDETERMINISM, {"kind": "uuid4", "value": str(value)}, None)
            return value

    def random(self) -> float:
        """A pseudo-random float in [0, 1). Not for security use."""
        with self._slot("random"):
            value = stdlib_random.random()  # noqa: S311
            self._write(EventType.NONDETERMINISM, {"kind": "random", "value": value}, None)
            return value

    def final_answer(self, value: JSONValue) -> JSONValue:
        with self._slot("final_answer"):
            cleaned = _prepare(self._redactor, value)
            self._write(EventType.FINAL_ANSWER, {"value": cleaned}, None)
            return cleaned

    def close(self) -> None:
        """Stop accepting calls. Idempotent. The store is owned by the caller and stays open."""
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
