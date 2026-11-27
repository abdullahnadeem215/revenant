from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from revenant import (
    Event,
    EventType,
    InvalidForkPointError,
    JSONValue,
    PayloadSerializationError,
    Recorder,
    SessionNotFoundError,
    SQLiteTraceStore,
    canonical_json,
)

from revenant_dev.agent import run_agent
from revenant_dev.api import (
    FORK_NO_FILES_ROOT,
    _fork,
    find_bad_edit,
    fork,
    get_session,
    list_sessions,
    replay_summary,
)
from revenant_dev.counters import RealCallCounters
from revenant_dev.demo import MAX_STEPS, TASK, RecordedRun, record_scripted_run
from revenant_dev.errors import ForkNotSupportedError
from revenant_dev.llm import CORRECT_STATS, STATS_PATH, WRONG_STATS, ScriptedLLM
from revenant_dev.tools import make_tools
from revenant_dev.workspace import Workspace, copy_sample

ZERO = {"llm": 0, "read_file": 0, "write_file": 0, "run_tests": 0}


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def _wrong_write_steps(events: Sequence[Event]) -> list[int]:
    """Steps of write_file calls that carry the planted wrong content. The oracle comes from
    the script, not from the app's finder."""
    steps: list[int] = []
    for event in events:
        args = event.payload.get("args")
        is_write = event.type is EventType.TOOL_CALL and event.payload.get("name") == "write_file"
        if is_write and isinstance(args, dict) and args.get("content") == WRONG_STATS:
            steps.append(event.step)
    return steps


def _answer_step(events: Sequence[Event], call_step: int) -> int:
    """Step of the tool_result that answers the call at call_step, from stored events."""
    return next(e.step for e in events if e.parent_step == call_step)


@pytest.fixture
def base(store: SQLiteTraceStore, workspace_root: Path) -> RecordedRun:
    return record_scripted_run(store, workspace_root, extra_reads=0)


def test_list_sessions_matches_the_store(store: SQLiteTraceStore, base: RecordedRun) -> None:
    rows = list_sessions(store)
    row = next(r for r in rows if r["session_id"] == base.session_id)
    assert row["event_count"] == len(store.load_session(base.session_id))
    assert row["task"] == TASK
    assert len(rows) == len(store.list_sessions())
    assert canonical_json(rows)


def test_get_session_returns_every_stored_event(store: SQLiteTraceStore, base: RecordedRun) -> None:
    data = get_session(store, base.session_id)
    stored = store.load_session(base.session_id)
    assert data["events"] == [event.model_dump(mode="json") for event in stored]
    assert data["metadata"] == {"task": TASK, "max_steps": MAX_STEPS, "extra_reads": 0}
    assert canonical_json(data)


def test_get_session_raises_for_an_unknown_session(store: SQLiteTraceStore) -> None:
    with pytest.raises(SessionNotFoundError):
        get_session(store, "no-such-session")


def test_replay_summary_has_zero_calls_and_matches_the_stored_answer(
    store: SQLiteTraceStore, workspace_root: Path, base: RecordedRun
) -> None:
    out = replay_summary(store, base.session_id, workspace_root=workspace_root)
    stored = store.load_session(base.session_id)
    final_event = next(e for e in stored if e.type is EventType.FINAL_ANSWER)
    value = final_event.payload["value"]
    assert isinstance(value, dict)
    assert out["replay_counters"] == ZERO
    assert out["final"] == value["answer"]
    assert out["matches_recorded"] is True
    assert canonical_json(out)


def test_find_bad_edit_names_the_stored_wrong_write(
    store: SQLiteTraceStore, base: RecordedRun
) -> None:
    out = find_bad_edit(store, base.session_id)
    wrong = _wrong_write_steps(store.load_session(base.session_id))
    assert len(wrong) == 1
    assert out == {
        "session_id": base.session_id,
        "bad_edit": {"step": wrong[0], "path": STATS_PATH},
    }


def test_find_bad_edit_is_none_when_no_write_fails_its_test(
    store: SQLiteTraceStore, workspace_root: Path, sample_dir: Path
) -> None:
    workspace_dir = workspace_root / "clean"
    copy_sample(sample_dir, workspace_dir)
    tools = make_tools(Workspace(workspace_dir), RealCallCounters())
    script: list[JSONValue] = [
        {"tool": "write_file", "args": {"path": STATS_PATH, "content": CORRECT_STATS}},
        {"tool": "run_tests", "args": {}},
        {"final": "fixed"},
    ]
    llm = ScriptedLLM(script, RealCallCounters())
    with Recorder.record(store, session_id="clean") as rec:
        run_agent(rec, TASK, llm, tools, max_steps=5)
    assert find_bad_edit(store, "clean") == {"session_id": "clean", "bad_edit": None}


def _dump(store: SQLiteTraceStore, session_id: str) -> str:
    return canonical_json([e.model_dump(mode="json") for e in store.load_session(session_id)])


def test_fork_without_use_override_raises_and_creates_no_session(
    store: SQLiteTraceStore, base: RecordedRun
) -> None:
    step = _wrong_write_steps(store.load_session(base.session_id))[0]
    before = len(store.list_sessions())
    with pytest.raises(ForkNotSupportedError):
        fork(store, base.session_id, step)
    assert len(store.list_sessions()) == before


def test_fork_returns_child_id_and_the_diff_at_the_answer_step(
    store: SQLiteTraceStore, base: RecordedRun
) -> None:
    events = store.load_session(base.session_id)
    step = _wrong_write_steps(events)[0]
    answer_step = _answer_step(events, step)
    out = fork(store, base.session_id, step, override={"ok": True}, use_override=True)
    assert set(out) == {"child_session_id", "diff"}
    child_id = out["child_session_id"]
    assert isinstance(child_id, str) and child_id != base.session_id
    info = {s.session_id: s for s in store.list_sessions()}[child_id]
    assert info.parent_session_id == base.session_id
    assert info.parent_step == step
    diff = out["diff"]
    assert isinstance(diff, dict)
    assert diff["first_divergent_step"] == answer_step
    assert diff["kind"] == "result"
    child_answer = store.load_session(child_id)[answer_step]
    assert child_answer.payload["overridden"] is True
    assert child_answer.payload["result"] == {"ok": True}


def test_fork_runs_no_real_call_and_writes_no_files(
    store: SQLiteTraceStore,
    base: RecordedRun,
    workspace_root: Path,
    sample_dir: Path,
) -> None:
    step = _wrong_write_steps(store.load_session(base.session_id))[0]
    workspace_before = _tree(workspace_root)
    sample_before = _tree(sample_dir)
    _child, _diff, counters = _fork(
        store, base.session_id, step, override={"ok": True}, use_override=True
    )
    assert counters == ZERO
    assert not FORK_NO_FILES_ROOT.exists()
    assert _tree(workspace_root) == workspace_before
    assert _tree(sample_dir) == sample_before


def test_fork_leaves_the_parent_unchanged(store: SQLiteTraceStore, base: RecordedRun) -> None:
    step = _wrong_write_steps(store.load_session(base.session_id))[0]
    before = _dump(store, base.session_id)
    fork(store, base.session_id, step, override={"ok": True}, use_override=True)
    assert _dump(store, base.session_id) == before
    assert store.verify_chain(base.session_id) is True
    parent = {s.session_id: s for s in store.list_sessions()}[base.session_id]
    assert parent.parent_session_id is None


def test_fork_rejects_a_step_that_is_not_a_call(store: SQLiteTraceStore, base: RecordedRun) -> None:
    events = store.load_session(base.session_id)
    answer_step = next(e.step for e in events if e.type is EventType.TOOL_RESULT)
    with pytest.raises(InvalidForkPointError):
        fork(store, base.session_id, answer_step, override={"ok": True}, use_override=True)


def test_every_output_is_plain_json(
    store: SQLiteTraceStore, workspace_root: Path, base: RecordedRun
) -> None:
    step = _wrong_write_steps(store.load_session(base.session_id))[0]
    outputs: list[object] = [
        list_sessions(store),
        get_session(store, base.session_id),
        replay_summary(store, base.session_id, workspace_root=workspace_root),
        find_bad_edit(store, base.session_id),
        fork(store, base.session_id, step, override={"ok": True}, use_override=True),
    ]
    for output in outputs:
        assert canonical_json(output)


def test_fork_rejects_a_non_finite_override_before_creating_a_child(
    store: SQLiteTraceStore, base: RecordedRun
) -> None:
    step = _wrong_write_steps(store.load_session(base.session_id))[0]
    before = len(store.list_sessions())
    with pytest.raises(PayloadSerializationError):
        fork(store, base.session_id, step, override=float("nan"), use_override=True)
    assert len(store.list_sessions()) == before
