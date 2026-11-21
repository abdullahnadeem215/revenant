from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Callable
from datetime import datetime

import pytest

from revenant.errors import ConcurrentCallError, PayloadSerializationError, RevenantError
from revenant.events import Event, EventType, JSONValue, canonical_json
from revenant.recorder import Recorder
from revenant.store import SQLiteTraceStore
from tests.fakes import RealTools, ScriptedLLM

Driver = Callable[[Recorder, ScriptedLLM, RealTools], list[object]]


def session_events(store: SQLiteTraceStore, session_id: str) -> list[Event]:
    return store.load_session(session_id)


def only_session(store: SQLiteTraceStore) -> str:
    sessions = store.list_sessions()
    assert len(sessions) == 1
    return sessions[0].session_id


def test_driver_writes_call_then_result_pairs(
    store: SQLiteTraceStore, tools: RealTools, llm: ScriptedLLM, driver: Driver
) -> None:
    rec = Recorder.record(store, session_id="s1")
    outputs = driver(rec, llm, tools)
    events = session_events(store, "s1")

    assert [e.type for e in events] == [
        EventType.SESSION_START,
        EventType.LLM_CALL,
        EventType.TOOL_RESULT,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TOOL_CALL,
        EventType.ERROR,
        EventType.FINAL_ANSWER,
    ]
    assert [e.step for e in events] == list(range(10))
    # Each answer points at the call event right before it.
    assert events[2].parent_step == 1
    assert events[4].parent_step == 3
    assert events[6].parent_step == 5
    assert events[8].parent_step == 7
    assert events[1].parent_step is None
    assert events[9].parent_step is None
    assert events[1].payload["name"] == "llm"
    # Without name=, the name is the function's __qualname__.
    assert events[3].payload["name"] == "RealTools.add"
    assert events[8].payload["exc_type"] == "builtins.ValueError"
    assert store.verify_chain("s1")
    assert outputs[0] == "three"
    assert (llm.calls, tools.add_calls, tools.lookup_calls, tools.fail_calls) == (1, 1, 1, 1)


def test_wrapped_functions_keep_kind_and_signature(
    tools: RealTools, store: SQLiteTraceStore
) -> None:
    rec = Recorder.record(store)
    add = rec.wrap_tool(tools.add)
    lookup = rec.wrap_tool(tools.lookup)
    assert not inspect.iscoroutinefunction(add)
    assert inspect.iscoroutinefunction(lookup)
    assert inspect.signature(add) == inspect.signature(tools.add)
    assert inspect.signature(lookup) == inspect.signature(tools.lookup)
    assert add.__name__ == "add"
    assert add.__doc__ == tools.add.__doc__
    assert lookup.__name__ == "lookup"


def test_results_pass_through_unchanged(tools: RealTools, store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store)
    add = rec.wrap_tool(tools.add)
    lookup = rec.wrap_tool(tools.lookup)
    assert add(2, 3) == 5
    assert asyncio.run(lookup("k")) == {"key": "k", "found": True}


def test_secret_argument_is_stored_as_redacted(tools: RealTools, store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1")
    login = rec.wrap_tool(tools.login)
    assert login("alice", "hunter2-secret") is True
    assert tools.login_calls == 1
    assert tools.seen_passwords == ["hunter2-secret"]  # the real function got the real value

    call = session_events(store, "s1")[1]
    assert call.type is EventType.TOOL_CALL
    assert call.payload["args"] == {"user": "alice", "password": "[REDACTED]"}
    assert "hunter2-secret" not in canonical_json([e.payload for e in session_events(store, "s1")])


def test_raising_redactor_stores_nothing(tools: RealTools, store: SQLiteTraceStore) -> None:
    def strict(value: JSONValue) -> JSONValue:
        if "explode" in canonical_json(value):
            raise RuntimeError("hook bug")
        return value

    rec = Recorder.record(store, session_id="s1", redactor=strict)
    add = rec.wrap_tool(tools.add)
    assert add(1, 2) == 3  # arguments contain no marker, so the hook lets this through
    assert tools.add_calls == 1

    def echo(text: str) -> str:
        return text

    echo_wrapped = rec.wrap_tool(echo, name="echo")
    with pytest.raises(RevenantError, match="nothing was stored"):
        echo_wrapped("explode")
    assert len(session_events(store, "s1")) == 3  # session_start, call, result: no echo call


def test_non_json_argument_is_rejected_before_anything_is_stored(
    tools: RealTools, store: SQLiteTraceStore
) -> None:
    seen: list[object] = []

    def take(item: object) -> bool:
        seen.append(item)
        return True

    rec = Recorder.record(store, session_id="s1")
    take_wrapped = rec.wrap_tool(take)
    with pytest.raises(PayloadSerializationError):
        take_wrapped(object())
    assert seen == []  # the real function never ran
    assert len(session_events(store, "s1")) == 1  # only session_start
    assert add_still_works(rec, tools)


def add_still_works(rec: Recorder, tools: RealTools) -> bool:
    return rec.wrap_tool(tools.add)(10, 1) == 11


def test_non_json_result_leaves_no_event_for_that_call(store: SQLiteTraceStore) -> None:
    def pair() -> tuple[int, int]:
        return (1, 2)

    rec = Recorder.record(store, session_id="s1")
    with pytest.raises(PayloadSerializationError):
        rec.wrap_tool(pair)()
    events = session_events(store, "s1")
    assert [e.type for e in events] == [EventType.SESSION_START]  # no call, no result
    assert store.verify_chain("s1")  # nothing lossy was stored
    with pytest.raises(RevenantError, match="unusable"):
        rec.wrap_tool(pair)()


def test_exception_is_recorded_and_reraised_with_same_type(
    tools: RealTools, store: SQLiteTraceStore
) -> None:
    rec = Recorder.record(store, session_id="s1")
    fail = rec.wrap_tool(tools.fail)
    with pytest.raises(ValueError, match="boom"):
        fail("boom")
    error = session_events(store, "s1")[2]
    assert error.type is EventType.ERROR
    assert error.parent_step == 1
    assert error.payload["exc_type"] == "builtins.ValueError"
    assert error.payload["message"] == "boom"
    assert add_still_works(rec, tools)  # the recorder is usable after a raised call


def test_exception_args_that_are_not_json_raise_serialization_error(
    store: SQLiteTraceStore,
) -> None:
    def boom() -> None:
        raise ValueError(object())

    rec = Recorder.record(store, session_id="s1")
    with pytest.raises(PayloadSerializationError):
        rec.wrap_tool(boom)()
    with pytest.raises(RevenantError, match="unusable"):
        rec.wrap_tool(boom)()


def test_overlapping_async_calls_raise_concurrent_call_error(
    tools: RealTools, store: SQLiteTraceStore
) -> None:
    rec = Recorder.record(store, session_id="s1")
    lookup = rec.wrap_tool(tools.lookup)
    other_calls: list[str] = []

    async def other() -> str:
        other_calls.append("ran")
        return "b"

    other_wrapped = rec.wrap_tool(other, name="other")

    async def scenario() -> list[object]:
        return list(await asyncio.gather(lookup("a"), other_wrapped(), return_exceptions=True))

    results = asyncio.run(scenario())
    assert results[0] == {"key": "a", "found": True}
    assert isinstance(results[1], ConcurrentCallError)
    assert results[1].active == "RealTools.lookup"
    assert results[1].attempted == "other"
    assert other_calls == []  # the second call never reached its real function
    names = [e.payload.get("name") for e in session_events(store, "s1")[1:]]
    assert names == ["RealTools.lookup", "RealTools.lookup"]  # only the first call was written
    assert store.verify_chain("s1")


def test_nested_wrapped_call_raises_concurrent_call_error(store: SQLiteTraceStore) -> None:
    inner_calls: list[str] = []

    def inner_real() -> str:
        inner_calls.append("ran")
        return "x"

    rec = Recorder.record(store, session_id="s1")
    inner = rec.wrap_tool(inner_real, name="inner")

    def outer_real() -> str:
        return inner()

    outer = rec.wrap_tool(outer_real, name="outer")
    with pytest.raises(ConcurrentCallError):
        outer()
    assert inner_calls == []
    assert store.verify_chain("s1")


class Interrupted(BaseException):
    """Stands in for KeyboardInterrupt or task cancellation."""


def test_interrupted_call_leaves_no_event_and_recorder_usable(
    tools: RealTools, store: SQLiteTraceStore
) -> None:
    def cancel() -> None:
        raise Interrupted()

    rec = Recorder.record(store, session_id="s1")
    with pytest.raises(Interrupted):
        rec.wrap_tool(cancel)()
    assert [e.type for e in session_events(store, "s1")] == [EventType.SESSION_START]
    assert rec.wrap_tool(tools.add)(1, 2) == 3  # the recorder still works
    assert tools.add_calls == 1
    assert store.verify_chain("s1")


def test_secret_inside_exception_text_is_masked(store: SQLiteTraceStore) -> None:
    def leak() -> None:
        raise ValueError("login failed: password=hunter2-secret, auth: Bearer abc.def")

    rec = Recorder.record(store, session_id="s1")
    with pytest.raises(ValueError, match="hunter2-secret"):
        rec.wrap_tool(leak)()  # the caller still gets the original exception
    error = session_events(store, "s1")[2]
    assert error.type is EventType.ERROR
    assert error.payload["message"] == "login failed: password=[REDACTED], auth: Bearer [REDACTED]"
    stored = canonical_json([e.payload for e in session_events(store, "s1")])
    assert "hunter2-secret" not in stored
    assert "abc.def" not in stored


def test_nondeterminism_values_are_recorded_and_returned(store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1")
    when = rec.now()
    ident = rec.uuid4()
    roll = rec.random()
    events = session_events(store, "s1")[1:]
    assert [e.type for e in events] == [EventType.NONDETERMINISM] * 3
    assert [e.payload["kind"] for e in events] == ["now", "uuid4", "random"]

    stamp = events[0].payload["value"]
    assert isinstance(stamp, str)
    assert when == datetime.fromisoformat(stamp)
    assert when.tzinfo is not None
    assert ident == uuid.UUID(str(events[1].payload["value"]))
    assert roll == events[2].payload["value"]
    assert 0.0 <= roll < 1.0


def test_final_answer_is_recorded_and_redacted(store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1")
    returned = rec.final_answer({"answer": "ok", "api_key": "sk-1"})
    assert returned == {"answer": "ok", "api_key": "[REDACTED]"}
    last = session_events(store, "s1")[-1]
    assert last.type is EventType.FINAL_ANSWER
    assert last.payload == {"value": {"answer": "ok", "api_key": "[REDACTED]"}}


def test_session_start_carries_redacted_metadata(store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1", metadata={"app": "demo", "password": "p"})
    start = session_events(store, "s1")[0]
    assert start.type is EventType.SESSION_START
    assert start.payload == {"metadata": {"app": "demo", "password": "[REDACTED]"}}
    assert rec.session_id == "s1"


def test_default_session_id_is_generated(store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store)
    assert len(rec.session_id) == 32
    assert [info.session_id for info in store.list_sessions()] == [rec.session_id]


def test_close_stops_calls_and_is_idempotent(tools: RealTools, store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1")
    add = rec.wrap_tool(tools.add)
    rec.close()
    rec.close()
    with pytest.raises(RevenantError, match="closed"):
        add(1, 2)
    assert tools.add_calls == 0


def test_context_manager_closes_the_recorder(store: SQLiteTraceStore) -> None:
    with Recorder.record(store, session_id="s1") as rec:
        assert rec.mode == "record"
    with pytest.raises(RevenantError, match="closed"):
        rec.final_answer({})
    assert len(session_events(store, "s1")) == 1
