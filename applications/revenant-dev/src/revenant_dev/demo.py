"""Milestone 1: record scripted runs, replay one with zero real calls, find the first bad edit.

find_first_bad_edit takes the stored events and nothing else. It reads only recorded results.
It does not read the script, the sample, or any test name.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields
from pathlib import Path

from revenant import Event, EventType, JSONValue, Recorder, SQLiteTraceStore, TraceStore

from revenant_dev.agent import AgentResult, run_agent
from revenant_dev.counters import RealCallCounters
from revenant_dev.errors import AgentProtocolError
from revenant_dev.llm import ScriptedLLM, planned_script
from revenant_dev.tools import make_tools
from revenant_dev.workspace import Workspace, copy_sample

__all__ = [
    "Milestone1Report",
    "RecordedRun",
    "find_first_bad_edit",
    "main",
    "record_scripted_run",
    "replay_recorded_run",
    "run_milestone1",
]

APP_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = APP_ROOT / "sample_repo"
TASK = "Fix sample_pkg.stats.mean so that the test suite passes."
MAX_STEPS = 12


def _write_path(payload: dict[str, JSONValue]) -> str:
    args = payload.get("args")
    path = args.get("path") if isinstance(args, dict) else None
    return path if isinstance(path, str) else ""


def _exit_code(payload: dict[str, JSONValue]) -> int | None:
    result = payload.get("result")
    if isinstance(result, dict):
        code = result.get("exit_code")
        if isinstance(code, int) and not isinstance(code, bool):
            return code
    return None


def find_first_bad_edit(events: Sequence[Event]) -> tuple[int, str] | None:
    """Return (step, path) of the first bad write, or None if no write is bad.

    A write_file call is bad when the next recorded run_tests result after it exits non-zero,
    with no other write in between. A write whose answer is an error never happened, so it is
    not an edit. Only recorded results are read.
    """
    pending: tuple[int, str] | None = None  # a write still waiting for a verdict
    confirmed = False  # the pending write's tool_result has been recorded
    for event in events:
        payload = event.payload
        if event.type is EventType.TOOL_CALL and payload.get("name") == "write_file":
            pending = (event.step, _write_path(payload))
            confirmed = False
            continue
        if pending is None:
            continue
        if event.parent_step == pending[0]:
            if event.type is EventType.TOOL_RESULT:
                confirmed = True
            else:
                pending = None
            continue
        if event.type is EventType.TOOL_RESULT and payload.get("name") == "run_tests" and confirmed:
            code = _exit_code(payload)
            if code is not None and code != 0:
                return pending
            pending = None
    return None


@dataclass(frozen=True)
class RecordedRun:
    session_id: str
    result: AgentResult
    live_counters: dict[str, int]
    first_bad_edit: tuple[int, str] | None


def session_config(events: Sequence[Event]) -> tuple[str, int, int]:
    """Read task, max_steps and extra_reads from the session_start metadata."""
    metadata = events[0].payload.get("metadata") if events else None
    if not isinstance(metadata, dict):
        raise AgentProtocolError("session has no metadata")
    task = metadata.get("task")
    max_steps = metadata.get("max_steps")
    extra_reads = metadata.get("extra_reads")
    if not (isinstance(task, str) and isinstance(max_steps, int) and isinstance(extra_reads, int)):
        raise AgentProtocolError("session metadata is incomplete")
    return task, max_steps, extra_reads


def record_scripted_run(
    store: TraceStore, workspace_root: Path, *, extra_reads: int = 0
) -> RecordedRun:
    """Run the agent live on a fresh copy of the sample and record it.

    The session metadata holds the task, max_steps and extra_reads, so a replay can rebuild the
    same agent configuration.
    """
    session_id = uuid.uuid4().hex
    workspace_dir = workspace_root / session_id
    copy_sample(SAMPLE_DIR, workspace_dir)
    counters = RealCallCounters()
    llm = ScriptedLLM(planned_script(extra_reads), counters)
    tools = make_tools(Workspace(workspace_dir), counters)
    metadata: dict[str, JSONValue] = {
        "task": TASK,
        "max_steps": MAX_STEPS,
        "extra_reads": extra_reads,
    }
    with Recorder.record(store, session_id=session_id, metadata=metadata) as rec:
        result = run_agent(rec, TASK, llm, tools, max_steps=MAX_STEPS)
    events = store.load_session(session_id)
    return RecordedRun(
        session_id=session_id,
        result=result,
        live_counters=counters.snapshot(),
        first_bad_edit=find_first_bad_edit(events),
    )


def replay_recorded_run(
    store: TraceStore, session_id: str, workspace_root: Path
) -> tuple[AgentResult, dict[str, int]]:
    """Replay a recorded session with the same agent code. Returns the result and the counters.

    The workspace is opened only so the tools can be wrapped. No real function runs, so the
    counters stay at 0 and nothing is written there.
    """
    task, max_steps, extra_reads = session_config(store.load_session(session_id))
    counters = RealCallCounters()
    llm = ScriptedLLM(planned_script(extra_reads), counters)
    tools = make_tools(Workspace(workspace_root / session_id), counters)
    with Recorder.replay(store, session_id) as rec:
        result = run_agent(rec, task, llm, tools, max_steps=max_steps)
    return result, counters.snapshot()


@dataclass(frozen=True)
class Milestone1Report:
    session_id: str
    final: str | None
    live_counters: dict[str, int]
    replay_matches_live: bool
    replay_counters: dict[str, int]
    first_bad_edit_step: int | None
    first_bad_edit_path: str | None
    variant_session_id: str
    variant_first_bad_edit_step: int | None
    variant_first_bad_edit_path: str | None


def run_milestone1(store_path: Path, workspace_root: Path) -> Milestone1Report:
    """Record the base run and a variant with one extra read, then replay the base run.

    The base run is saved to store_path and reopened for replay, which shows that the session
    was saved and can be read back.
    """
    store = SQLiteTraceStore(store_path)
    try:
        base = record_scripted_run(store, workspace_root, extra_reads=0)
        variant = record_scripted_run(store, workspace_root, extra_reads=1)
    finally:
        store.close()
    reopened = SQLiteTraceStore(store_path)
    try:
        replayed, replay_counters = replay_recorded_run(reopened, base.session_id, workspace_root)
    finally:
        reopened.close()
    base_bad = base.first_bad_edit
    variant_bad = variant.first_bad_edit
    return Milestone1Report(
        session_id=base.session_id,
        final=base.result.final,
        live_counters=base.live_counters,
        replay_matches_live=replayed == base.result,
        replay_counters=replay_counters,
        first_bad_edit_step=base_bad[0] if base_bad else None,
        first_bad_edit_path=base_bad[1] if base_bad else None,
        variant_session_id=variant.session_id,
        variant_first_bad_edit_step=variant_bad[0] if variant_bad else None,
        variant_first_bad_edit_path=variant_bad[1] if variant_bad else None,
    )


def main() -> None:
    """Run milestone 1 against the app's .data/ folder and print one field per line."""
    data = APP_ROOT / ".data"
    data.mkdir(exist_ok=True)
    report = run_milestone1(data / "sessions.db", data / "workspaces")
    for field in fields(report):
        print(f"{field.name}: {getattr(report, field.name)}")


if __name__ == "__main__":
    main()
