from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.errors import (
    ChainIntegrityError,
    DivergenceError,
    ReplayExhaustedError,
    SessionNotFoundError,
    UnconsumedEventsWarning,
)
from revenant.events import GENESIS_HASH, EventType, JSONValue, build_event, request_fingerprint
from revenant.recorder import Recorder
from revenant.store import SQLiteTraceStore
from tests.fakes import RealTools, ScriptedLLM, run_driver


def test_record_then_replay_gives_identical_outputs_with_zero_real_calls(
    store: SQLiteTraceStore,
) -> None:
    recorded = run_driver(
        Recorder.record(store, session_id="s1"), ScriptedLLM(["three"]), RealTools()
    )
    llm = ScriptedLLM(["SHOULD-NOT-BE-USED"])
    tools = RealTools()
    replayed = run_driver(Recorder.replay(store, "s1"), llm, tools)
    assert replayed == recorded
    assert (llm.calls, tools.add_calls, tools.lookup_calls, tools.fail_calls) == (0, 0, 0, 0)


def test_sync_and_async_tools_both_replay(store: SQLiteTraceStore) -> None:
    rec_tools = RealTools()
    rec = Recorder.record(store, session_id="s1")
    add = rec.wrap_tool(rec_tools.add)
    lookup = rec.wrap_tool(rec_tools.lookup)
    recorded_sum = add(2, 3)
    recorded_lookup = asyncio.run(lookup("k"))

    tools = RealTools()
    replay = Recorder.replay(store, "s1")
    replayed_add = replay.wrap_tool(tools.add)(2, 3)
    replayed_lookup = asyncio.run(replay.wrap_tool(tools.lookup)("k"))
    assert (replayed_add, replayed_lookup) == (recorded_sum, recorded_lookup)
    assert type(replayed_lookup) is dict  # replay returns plain JSON values
    assert (tools.add_calls, tools.lookup_calls) == (0, 0)


def test_recorded_exception_is_reraised_identically_on_replay(store: SQLiteTraceStore) -> None:
    rec_tools = RealTools()
    rec = Recorder.record(store, session_id="s1")
    with pytest.raises(ValueError) as recorded:
        rec.wrap_tool(rec_tools.fail)("boom")

    tools = RealTools()
    replay = Recorder.replay(store, "s1")
    with pytest.raises(ValueError) as replayed:
        replay.wrap_tool(tools.fail)("boom")
    assert type(replayed.value) is ValueError
    assert str(replayed.value) == str(recorded.value) == "boom"
    assert tools.fail_calls == 0


def test_changed_arguments_raise_divergence_at_the_right_step(store: SQLiteTraceStore) -> None:
    run_driver(Recorder.record(store, session_id="s1"), ScriptedLLM(["three"]), RealTools())
    llm = ScriptedLLM(["three"])
    tools = RealTools()
    replay = Recorder.replay(store, "s1")
    replay.wrap_llm(llm, name="llm")("what is 1 + 2?")
    add = replay.wrap_tool(tools.add)
    with pytest.raises(DivergenceError) as info:
        add(1, 99)
    assert info.value.step == 3  # session_start 0, llm 1-2, add call 3
    assert info.value.reason == "arguments differ"
    assert tools.add_calls == 0


def test_replay_past_the_end_raises_exhausted(store: SQLiteTraceStore) -> None:
    run_driver(Recorder.record(store, session_id="s1"), ScriptedLLM(["x"]), RealTools())
    replay = Recorder.replay(store, "s1")
    run_driver(replay, ScriptedLLM(["x"]), RealTools())  # consumes every recorded event
    extra = replay.wrap_tool(RealTools().add)
    with pytest.raises(ReplayExhaustedError):
        extra(1, 2)


def test_editing_a_stored_event_fails_replay_on_open(
    store: SQLiteTraceStore, tmp_path: Path
) -> None:
    run_driver(Recorder.record(store, session_id="s1"), ScriptedLLM(["x"]), RealTools())
    raw = sqlite3.connect(tmp_path / "trace.db")
    raw.execute(
        "UPDATE events SET payload_json = ? WHERE session_id = 's1' AND step = 2",
        ('{"name":"llm","result":"forged"}',),
    )
    raw.commit()
    raw.close()
    with pytest.raises(ChainIntegrityError):
        Recorder.replay(store, "s1")


def test_now_uuid4_random_match_across_record_and_replay(store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1")
    recorded = (rec.now(), rec.uuid4(), rec.random())
    replay = Recorder.replay(store, "s1")
    assert (replay.now(), replay.uuid4(), replay.random()) == recorded


def test_unknown_session_and_empty_session_are_rejected(store: SQLiteTraceStore) -> None:
    with pytest.raises(SessionNotFoundError):
        Recorder.replay(store, "missing")
    store.create_session("empty")
    with pytest.raises(ChainIntegrityError):
        Recorder.replay(store, "empty")


def test_divergence_leaves_cursor_and_a_retry_gives_the_same_error(
    store: SQLiteTraceStore,
) -> None:
    run_driver(Recorder.record(store, session_id="s1"), ScriptedLLM(["three"]), RealTools())
    replay = Recorder.replay(store, "s1")
    replay.wrap_llm(ScriptedLLM(["three"]), name="llm")("what is 1 + 2?")
    tools = RealTools()
    add = replay.wrap_tool(tools.add)
    errors: list[DivergenceError] = []
    for _ in range(2):
        with pytest.raises(DivergenceError) as info:
            add(1, 99)
        errors.append(info.value)
    assert (
        (errors[0].step, errors[0].reason)
        == (errors[1].step, errors[1].reason)
        == (3, "arguments differ")
    )
    assert add(1, 2) == 3  # the matching call still lines up with recorded step 3
    assert tools.add_calls == 0


def test_last_call_without_a_result_raises_exhausted_not_a_partial_success(
    store: SQLiteTraceStore,
) -> None:
    store.create_session("half")
    args: JSONValue = {"a": 1, "b": 2}
    name = "RealTools.add"
    session_start = build_event(
        session_id="half",
        step=0,
        type=EventType.SESSION_START,
        payload={"metadata": {}},
        prev_hash=GENESIS_HASH,
    )
    store.append_event(session_start)
    call = build_event(
        session_id="half",
        step=1,
        type=EventType.TOOL_CALL,
        payload={"name": name, "args": args, "fingerprint": request_fingerprint(name, args)},
        prev_hash=session_start.hash,
    )
    store.append_event(call)  # crash here: the result was never written
    tools = RealTools()
    replay = Recorder.replay(store, "half")
    with pytest.raises(ReplayExhaustedError):
        replay.wrap_tool(tools.add)(1, 2)
    assert tools.add_calls == 0


def test_replay_starts_after_session_start(store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1")
    rec.wrap_tool(RealTools().add)(1, 2)  # first call: step 1
    replay = Recorder.replay(store, "s1")
    with pytest.raises(DivergenceError) as info:
        replay.wrap_tool(RealTools().add)(9, 9)
    assert info.value.step == 1
    assert replay.wrap_tool(RealTools().add)(1, 2) == 3


def test_unconsumed_events_warn_with_the_count_on_close(store: SQLiteTraceStore) -> None:
    run_driver(Recorder.record(store, session_id="s1"), ScriptedLLM(["three"]), RealTools())
    replay = Recorder.replay(store, "s1")
    replay.wrap_llm(ScriptedLLM(["three"]), name="llm")("what is 1 + 2?")
    with pytest.warns(UnconsumedEventsWarning) as caught:
        replay.close()
    warning = caught[0].message
    assert isinstance(warning, UnconsumedEventsWarning)
    assert warning.count == 7  # 10 events, 3 used (session_start plus the llm pair)


def test_fully_consumed_replay_closes_silently(store: SQLiteTraceStore) -> None:
    run_driver(Recorder.record(store, session_id="s1"), ScriptedLLM(["three"]), RealTools())
    replay = Recorder.replay(store, "s1")
    run_driver(replay, ScriptedLLM(["three"]), RealTools())
    replay.close()  # any warning here fails the test (filterwarnings = error)


def test_final_answer_must_match_the_recording(store: SQLiteTraceStore) -> None:
    rec = Recorder.record(store, session_id="s1")
    rec.final_answer({"a": 1})
    replay = Recorder.replay(store, "s1")
    with pytest.raises(DivergenceError):
        replay.final_answer({"a": 2})
    assert replay.final_answer({"a": 1}) == {"a": 1}


def test_error_for_an_unloaded_exception_class_is_a_divergence(
    store: SQLiteTraceStore,
) -> None:
    store.create_session("odd")
    args: JSONValue = {"reason": "x"}
    name = "RealTools.fail"
    start = build_event(
        session_id="odd",
        step=0,
        type=EventType.SESSION_START,
        payload={"metadata": {}},
        prev_hash=GENESIS_HASH,
    )
    store.append_event(start)
    call = build_event(
        session_id="odd",
        step=1,
        type=EventType.TOOL_CALL,
        payload={"name": name, "args": args, "fingerprint": request_fingerprint(name, args)},
        prev_hash=start.hash,
    )
    store.append_event(call)
    failure = build_event(
        session_id="odd",
        step=2,
        type=EventType.ERROR,
        payload={
            "name": name,
            "exc_type": "no_such_module_for_revenant.Boom",
            "message": "x",
            "args": ["x"],
        },
        prev_hash=call.hash,
        parent_step=1,
    )
    store.append_event(failure)
    replay = Recorder.replay(store, "odd")
    with pytest.raises(DivergenceError) as info:
        replay.wrap_tool(RealTools().fail)("x")
    assert info.value.reason == "recorded exception class is not loaded in this process"


def _run_ops(recorder: Recorder, tools: RealTools, ops: list[tuple[object, ...]]) -> list[object]:
    add = recorder.wrap_tool(tools.add)
    lookup = recorder.wrap_tool(tools.lookup)

    async def go() -> list[object]:
        outputs: list[object] = []
        for op in ops:
            if op[0] == "add":
                left, right = op[1], op[2]
                assert isinstance(left, int) and isinstance(right, int)
                outputs.append(add(left, right))
            else:
                key = op[1]
                assert isinstance(key, str)
                outputs.append(await lookup(key))
        return outputs

    result = asyncio.run(go())
    recorder.final_answer({"ops": len(ops)})
    return result


@pytest.mark.hypothesis
@settings(max_examples=50)
@given(
    st.lists(
        st.one_of(
            st.tuples(st.just("add"), st.integers(-5, 5), st.integers(-5, 5)),
            st.tuples(st.just("lookup"), st.text(max_size=4)),
        ),
        max_size=6,
    )
)
def test_record_replay_identical_with_zero_real_calls_for_any_sequence(
    ops: list[tuple[object, ...]],
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteTraceStore(Path(tmp) / "trace.db", synchronous="NORMAL")
        try:
            recorded = _run_ops(Recorder.record(store, session_id="s"), RealTools(), ops)
            tools = RealTools()
            replayed = _run_ops(Recorder.replay(store, "s"), tools, ops)
            assert replayed == recorded
            assert (tools.add_calls, tools.lookup_calls) == (0, 0)
        finally:
            store.close()
