"""Invariants that must hold in replay: no real function runs, no event is written, and any
mismatch raises DivergenceError. The replay-related hook runs this file."""

from __future__ import annotations

import pytest

from revenant.errors import DivergenceError
from revenant.recorder import Recorder
from revenant.store import SQLiteTraceStore


def tripwire(v: int) -> int:
    """Fails the test if the real function is ever called during replay."""
    raise AssertionError(f"real function called with {v}")


def double(v: int) -> int:
    return v * 2


def record_one_call(store: SQLiteTraceStore, value: int) -> int:
    rec = Recorder.record(store, session_id="s1")
    result = rec.wrap_tool(double, name="double")(value)
    assert isinstance(result, int)
    return result


def test_replay_never_calls_the_real_function(store: SQLiteTraceStore) -> None:
    record_one_call(store, 4)
    replay = Recorder.replay(store, "s1")
    assert replay.wrap_tool(tripwire, name="double")(4) == 8


def test_replay_writes_no_events(store: SQLiteTraceStore) -> None:
    record_one_call(store, 4)
    before = len(store.load_session("s1"))
    replay = Recorder.replay(store, "s1")
    replay.wrap_tool(tripwire, name="double")(4)
    assert len(store.load_session("s1")) == before
    assert store.verify_chain("s1")


def test_divergence_is_raised_before_any_real_call(store: SQLiteTraceStore) -> None:
    record_one_call(store, 4)
    replay = Recorder.replay(store, "s1")
    with pytest.raises(DivergenceError) as info:
        replay.wrap_tool(tripwire, name="double")(5)  # arguments differ from the recording
    assert info.value.step == 1
    assert info.value.reason == "arguments differ"


def test_divergence_on_a_different_tool_name_is_raised(store: SQLiteTraceStore) -> None:
    record_one_call(store, 4)
    replay = Recorder.replay(store, "s1")
    with pytest.raises(DivergenceError) as info:
        replay.wrap_tool(tripwire, name="triple")(4)
    assert info.value.reason == "different tool name"
