from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from revenant import (
    GENESIS_HASH,
    Event,
    EventType,
    JSONValue,
    Recorder,
    SQLiteTraceStore,
    canonical_json,
)
from revenant.events import build_event

from revenant_dev.counters import RealCallCounters
from revenant_dev.demo import (
    find_first_bad_edit,
    record_scripted_run,
    replay_recorded_run,
)
from revenant_dev.llm import STATS_PATH, WRONG_STATS, planned_script
from revenant_dev.tools import make_tools
from revenant_dev.workspace import Workspace


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def _stored_wrong_write_steps(store: SQLiteTraceStore, session_id: str) -> list[int]:
    """Steps of the write_file calls that carry the planted wrong content. The test knows the
    content from the script. The app's finder never reads it."""
    steps: list[int] = []
    for event in store.load_session(session_id):
        args = event.payload.get("args")
        is_write = event.type is EventType.TOOL_CALL and event.payload.get("name") == "write_file"
        if is_write and isinstance(args, dict) and args.get("content") == WRONG_STATS:
            steps.append(event.step)
    return steps


def test_record_then_replay_makes_zero_real_calls(
    store: SQLiteTraceStore, workspace_root: Path
) -> None:
    base = record_scripted_run(store, workspace_root, extra_reads=0)
    assert base.live_counters == {
        "llm": len(planned_script(0)),
        "read_file": 1,
        "write_file": 2,
        "run_tests": 2,
    }
    replayed, replay_counters = replay_recorded_run(store, base.session_id, workspace_root)
    assert replayed == base.result
    assert replay_counters == {"llm": 0, "read_file": 0, "write_file": 0, "run_tests": 0}


def test_replay_writes_nothing_to_the_workspace(
    store: SQLiteTraceStore, workspace_root: Path
) -> None:
    base = record_scripted_run(store, workspace_root, extra_reads=0)
    workspace = workspace_root / base.session_id
    before = _tree(workspace)
    replay_recorded_run(store, base.session_id, workspace_root)
    assert _tree(workspace) == before


def test_a_run_does_not_change_the_committed_sample(
    store: SQLiteTraceStore, workspace_root: Path, sample_dir: Path
) -> None:
    before = _tree(sample_dir)
    record_scripted_run(store, workspace_root, extra_reads=0)
    assert _tree(sample_dir) == before


def test_first_bad_edit_is_the_stored_wrong_write(
    store: SQLiteTraceStore, workspace_root: Path
) -> None:
    base = record_scripted_run(store, workspace_root, extra_reads=0)
    wrong_steps = _stored_wrong_write_steps(store, base.session_id)
    assert len(wrong_steps) == 1
    assert base.first_bad_edit == (wrong_steps[0], STATS_PATH)


def test_second_run_with_one_extra_read_moves_the_reported_step(
    store: SQLiteTraceStore, workspace_root: Path
) -> None:
    base = record_scripted_run(store, workspace_root, extra_reads=0)
    variant = record_scripted_run(store, workspace_root, extra_reads=1)
    variant_wrong = _stored_wrong_write_steps(store, variant.session_id)
    assert len(variant_wrong) == 1
    assert variant.first_bad_edit == (variant_wrong[0], STATS_PATH)
    assert base.first_bad_edit is not None and variant.first_bad_edit is not None
    assert variant.first_bad_edit[0] > base.first_bad_edit[0]


def test_secret_in_a_file_is_stored_redacted(store: SQLiteTraceStore, workspace_root: Path) -> None:
    workspace_dir = workspace_root / "redaction"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "notes.txt").write_text("password=hunter2\n", encoding="utf-8")
    counters = RealCallCounters()
    tools = make_tools(Workspace(workspace_dir), counters)
    with Recorder.record(store, session_id="redaction") as rec:
        rec.wrap_tool(tools["read_file"], name="read_file")(path="notes.txt")
    stored = canonical_json([e.payload for e in store.load_session("redaction")])
    assert "[REDACTED]" in stored
    assert "hunter2" not in stored


def _event(
    step: int, kind: EventType, payload: dict[str, JSONValue], parent_step: int | None = None
) -> Event:
    return build_event(
        session_id="hand",
        step=step,
        type=kind,
        payload=payload,
        prev_hash=GENESIS_HASH,
        timestamp="2026-01-01T00:00:00+00:00",
        parent_step=parent_step,
    )


def _write_call(step: int, path: str) -> Event:
    return _event(
        step, EventType.TOOL_CALL, {"name": "write_file", "args": {"path": path, "content": "c"}}
    )


def _result(step: int, parent: int, name: str, result: JSONValue) -> Event:
    return _event(step, EventType.TOOL_RESULT, {"name": name, "result": result}, parent)


def _error(step: int, parent: int, name: str) -> Event:
    return _event(
        step, EventType.ERROR, {"name": name, "exc_type": "x.Y", "message": "m", "args": []}, parent
    )


def _tests(exit_code: int, failed: Sequence[str]) -> JSONValue:
    return {
        "exit_code": exit_code,
        "passed": 0,
        "failed": len(failed),
        "failed_tests": list(failed),
    }


def test_finder_reads_only_recorded_results() -> None:
    # A write followed by a failing run: bad, whatever the failing test is called.
    bad = [
        _write_call(1, "x.py"),
        _result(2, 1, "write_file", {}),
        _event(3, EventType.TOOL_CALL, {"name": "run_tests", "args": {}}),
        _result(4, 3, "run_tests", _tests(1, ["anything::else"])),
    ]
    assert find_first_bad_edit(bad) == (1, "x.py")
    # A write followed by a passing run is not bad.
    good = [
        _write_call(1, "x.py"),
        _result(2, 1, "write_file", {}),
        _result(3, 0, "run_tests", _tests(0, [])),
    ]
    assert find_first_bad_edit(good) is None
    # A write with no verdict before the next write is not bad. The second write is.
    replaced = [
        _write_call(1, "x.py"),
        _result(2, 1, "write_file", {}),
        _write_call(3, "y.py"),
        _result(4, 3, "write_file", {}),
        _result(5, 0, "run_tests", _tests(1, ["t"])),
    ]
    assert find_first_bad_edit(replaced) == (3, "y.py")
    # A write whose answer is an error never happened.
    failed_write = [
        _write_call(1, "x.py"),
        _error(2, 1, "write_file"),
        _result(3, 0, "run_tests", _tests(1, ["t"])),
    ]
    assert find_first_bad_edit(failed_write) is None
