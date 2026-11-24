from __future__ import annotations

import pytest

from revenant.errors import (
    DivergenceError,
    InvalidForkPointError,
    SessionNotFoundError,
    UnconsumedEventsWarning,
)
from revenant.events import EventType
from revenant.recorder import Recorder
from revenant.store import SQLiteTraceStore
from tests.fakes import RealTools, ScriptedLLM, run_driver


def record_parent(store: SQLiteTraceStore) -> None:
    run_driver(Recorder.record(store, session_id="parent"), ScriptedLLM(["three"]), RealTools())


def test_fork_replays_prefix_overrides_fork_step_and_runs_later_calls_live(
    store: SQLiteTraceStore,
) -> None:
    record_parent(store)
    llm = ScriptedLLM(["SHOULD-NOT-BE-USED"])
    tools = RealTools()
    child = Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child")
    outputs = run_driver(child, llm, tools)

    assert outputs[0] == "three"  # prefix replayed from the parent
    assert outputs[1] == {"hits": []}  # the override answers the call at step 3
    # The prefix and the fork step never run the real function. Later calls run live.
    assert (llm.calls, tools.add_calls, tools.lookup_calls, tools.fail_calls) == (0, 0, 1, 1)

    events = store.load_session("child")
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
    assert events[4].payload == {
        "name": "RealTools.add",
        "result": {"hits": []},
        "overridden": True,
    }
    assert events[4].parent_step == 3


def test_child_is_linked_to_parent_and_both_chains_verify(store: SQLiteTraceStore) -> None:
    record_parent(store)
    parent_before = store.load_session("parent")
    run_driver(
        Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child"),
        ScriptedLLM(["SHOULD-NOT-BE-USED"]),
        RealTools(),
    )
    sessions = {info.session_id: info for info in store.list_sessions()}
    assert (sessions["child"].parent_session_id, sessions["child"].parent_step) == ("parent", 3)
    assert sessions["parent"].parent_session_id is None
    assert store.verify_chain("child")
    assert store.verify_chain("parent")
    assert store.load_session("parent") == parent_before  # the parent is unchanged


def test_child_copies_the_prefix_with_new_ids_and_keeps_content(
    store: SQLiteTraceStore,
) -> None:
    record_parent(store)
    parent = store.load_session("parent")
    run_driver(
        Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child"),
        ScriptedLLM(["x"]),
        RealTools(),
    )
    child = store.load_session("child")
    for source, copied in zip(parent[:3], child[:3], strict=True):
        assert (copied.type, copied.payload, copied.timestamp, copied.parent_step) == (
            source.type,
            source.payload,
            source.timestamp,
            source.parent_step,
        )
        assert copied.event_id != source.event_id
        assert copied.session_id == "child"
        assert copied.hash != source.hash  # recomputed in the child's chain


def test_fork_without_override_runs_the_real_function_once_at_the_fork_step(
    store: SQLiteTraceStore,
) -> None:
    record_parent(store)
    tools = RealTools()
    outputs = run_driver(
        Recorder.fork(store, "parent", 3, session_id="child"), ScriptedLLM(["x"]), tools
    )
    assert outputs[1] == 3
    assert tools.add_calls == 1
    tool_result = store.load_session("child")[4]
    assert tool_result.payload == {"name": "RealTools.add", "result": 3}  # no overridden flag


def test_none_is_a_valid_override(store: SQLiteTraceStore) -> None:
    record_parent(store)
    tools = RealTools()
    outputs = run_driver(
        Recorder.fork(store, "parent", 3, override=None, session_id="child"),
        ScriptedLLM(["x"]),
        tools,
    )
    assert outputs[1] is None
    assert tools.add_calls == 0
    assert store.load_session("child")[4].payload == {
        "name": "RealTools.add",
        "result": None,
        "overridden": True,
    }


@pytest.mark.parametrize("at_step", [0, 2, 99])
def test_fork_point_must_be_a_call_event_inside_the_parent(
    store: SQLiteTraceStore, at_step: int
) -> None:
    record_parent(store)
    with pytest.raises(InvalidForkPointError):
        Recorder.fork(store, "parent", at_step, session_id="child")


def test_fork_of_an_unknown_parent_raises(store: SQLiteTraceStore) -> None:
    with pytest.raises(SessionNotFoundError):
        Recorder.fork(store, "missing", 1, session_id="child")


def test_changed_arguments_at_the_fork_step_raise_divergence(store: SQLiteTraceStore) -> None:
    record_parent(store)
    tools = RealTools()
    child = Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child")
    child.wrap_llm(ScriptedLLM(["x"]), name="llm")("what is 1 + 2?")
    add = child.wrap_tool(tools.add)
    for _ in range(2):  # a retry gives the same error: the cursor did not move
        with pytest.raises(DivergenceError) as info:
            add(1, 99)
        assert (info.value.step, info.value.reason) == (3, "arguments differ")
    assert tools.add_calls == 0


def test_prefix_mismatch_raises_divergence_before_the_fork_step(
    store: SQLiteTraceStore,
) -> None:
    record_parent(store)
    child = Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child")
    with pytest.raises(DivergenceError) as info:
        child.wrap_llm(ScriptedLLM(["x"]), name="llm")("a different question")
    assert info.value.step == 1


def test_a_fork_child_replays_to_the_same_outputs(store: SQLiteTraceStore) -> None:
    record_parent(store)
    child_outputs = run_driver(
        Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child"),
        ScriptedLLM(["x"]),
        RealTools(),
    )
    tools = RealTools()
    llm = ScriptedLLM(["SHOULD-NOT-BE-USED"])
    replayed = run_driver(Recorder.replay(store, "child"), llm, tools)
    assert replayed == child_outputs
    assert (llm.calls, tools.add_calls, tools.lookup_calls, tools.fail_calls) == (0, 0, 0, 0)


def test_closing_a_fork_early_warns_about_the_unused_prefix(store: SQLiteTraceStore) -> None:
    record_parent(store)
    child = Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child")
    with pytest.warns(UnconsumedEventsWarning) as caught:
        child.close()  # the llm pair (steps 1-2) was never replayed
    warning = caught[0].message
    assert isinstance(warning, UnconsumedEventsWarning)
    assert warning.count == 2


def test_a_fully_driven_fork_closes_silently(store: SQLiteTraceStore) -> None:
    record_parent(store)
    child = Recorder.fork(store, "parent", 3, override={"hits": []}, session_id="child")
    run_driver(child, ScriptedLLM(["x"]), RealTools())
    child.close()  # any warning here fails the test (filterwarnings = error)
