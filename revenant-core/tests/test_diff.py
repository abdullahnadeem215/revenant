from __future__ import annotations

import dataclasses

from revenant.diff import DivergenceKind, diff_sessions
from revenant.events import (
    GENESIS_HASH,
    Event,
    EventType,
    JSONValue,
    build_event,
    request_fingerprint,
)
from revenant.recorder import Recorder
from revenant.store import SQLiteTraceStore
from tests.fakes import RealTools, ScriptedLLM, run_driver


def trace(*calls: tuple[str, dict[str, JSONValue], JSONValue]) -> list[Event]:
    """Build an in-memory session: session_start, then a tool_call and tool_result per call."""
    start = build_event(
        session_id="x",
        step=0,
        type=EventType.SESSION_START,
        payload={"metadata": {}},
        prev_hash=GENESIS_HASH,
    )
    events = [start]
    for name, args, result in calls:
        call = build_event(
            session_id="x",
            step=len(events),
            type=EventType.TOOL_CALL,
            payload={"name": name, "args": args, "fingerprint": request_fingerprint(name, args)},
            prev_hash=events[-1].hash,
        )
        answer = build_event(
            session_id="x",
            step=len(events) + 1,
            type=EventType.TOOL_RESULT,
            payload={"name": name, "result": result},
            prev_hash=call.hash,
            parent_step=call.step,
        )
        events.extend([call, answer])
    return events


def test_identical_runs_compare_as_identical(store: SQLiteTraceStore) -> None:
    """Two recordings of the same run differ in ids, timestamps and hashes, but not in content."""
    for sid in ("a", "b"):
        run_driver(Recorder.record(store, session_id=sid), ScriptedLLM(["three"]), RealTools())
    result = diff_sessions(store.load_session("a"), store.load_session("b"))
    assert result.first_divergent_step is None
    assert result.kind is None
    assert result.differing_steps == ()
    assert (result.len_a, result.len_b) == (10, 10)


def test_different_tool_is_reported_at_the_call_step() -> None:
    left = trace(("search", {"q": 1}, "r"))
    right = trace(("lookup", {"q": 1}, "r"))
    result = diff_sessions(left, right)
    assert (result.first_divergent_step, result.kind) == (1, DivergenceKind.DIFFERENT_TOOL)


def test_changed_args_are_reported_as_args() -> None:
    left = trace(("search", {"q": 1}, "r"))
    right = trace(("search", {"q": 2}, "r"))
    result = diff_sessions(left, right)
    assert (result.first_divergent_step, result.kind) == (1, DivergenceKind.ARGS)


def test_changed_result_is_reported_at_the_answer_step() -> None:
    left = trace(("search", {"q": 1}, "r"))
    right = trace(("search", {"q": 1}, "s"))
    result = diff_sessions(left, right)
    assert (result.first_divergent_step, result.kind) == (2, DivergenceKind.RESULT)


def test_json_one_and_true_are_different_values() -> None:
    left = trace(("search", {"q": 1}, "r"))
    right = trace(("search", {"q": True}, "r"))
    result = diff_sessions(left, right)
    assert result.kind is DivergenceKind.ARGS


def test_extra_steps_are_reported_as_length() -> None:
    short = trace(("search", {"q": 1}, "r"))
    long = trace(("search", {"q": 1}, "r"), ("lookup", {"k": 2}, "s"))
    result = diff_sessions(short, long)
    assert (result.len_a, result.len_b) == (3, 5)
    assert (result.first_divergent_step, result.kind) == (3, DivergenceKind.LENGTH)
    assert [d.step for d in result.differing_steps] == [3, 4]
    assert result.differing_steps[0].a is None  # the shorter session has no step 3


def test_every_differing_step_is_listed_in_order() -> None:
    left = trace(("search", {"q": 1}, "r"), ("lookup", {"k": 2}, "s"))
    right = trace(("search", {"q": 9}, "r"), ("lookup", {"k": 2}, "t"))
    result = diff_sessions(left, right)
    assert [(d.step, d.kind) for d in result.differing_steps] == [
        (1, DivergenceKind.ARGS),
        (4, DivergenceKind.RESULT),
    ]
    assert (result.first_divergent_step, result.kind) == (1, DivergenceKind.ARGS)


def test_trace_diff_is_plain_data() -> None:
    result = diff_sessions(trace(("search", {"q": 1}, "r")), trace(("search", {"q": 2}, "r")))
    as_dict = dataclasses.asdict(result)
    assert as_dict["kind"] == "args"
    assert as_dict["differing_steps"][0]["kind"] == "args"


def test_fork_child_diverges_from_parent_first_at_the_override(store: SQLiteTraceStore) -> None:
    run_driver(Recorder.record(store, session_id="parent"), ScriptedLLM(["three"]), RealTools())
    run_driver(
        Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child"),
        ScriptedLLM(["x"]),
        RealTools(),
    )
    result = diff_sessions(store.load_session("parent"), store.load_session("child"))
    assert (result.first_divergent_step, result.kind) == (4, DivergenceKind.RESULT)
