"""Backend API for revenant-dev.

Plain functions that take a TraceStore and return JSON-compatible data. There is no web server
and no web framework. Each output shape is documented in API.md.

fork is override-only in v1: it replays the parent up to the fork step, records that step with
the override as its result, and stops. It makes no live call and writes no file.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

from revenant import (
    Event,
    EventType,
    JSONValue,
    Recorder,
    SessionInfo,
    SessionNotFoundError,
    TraceStore,
    canonical_json,
)
from revenant.diff import TraceDiff, diff_sessions
from revenant.events import CALL_TYPES

from revenant_dev.agent import run_agent
from revenant_dev.counters import RealCallCounters
from revenant_dev.demo import APP_ROOT, find_first_bad_edit, replay_recorded_run, session_config
from revenant_dev.errors import ForkNotSupportedError
from revenant_dev.llm import ScriptedLLM, planned_script
from revenant_dev.tools import make_tools
from revenant_dev.workspace import Workspace

__all__ = [
    "find_bad_edit",
    "fork",
    "get_session",
    "list_sessions",
    "replay_summary",
]

# Fork tools are built on this path, which is never created. A real tool call would have to
# create it, so a fork that wrote a file would show up as a new folder.
FORK_NO_FILES_ROOT = APP_ROOT / ".data" / "fork-no-workspace"


def _info(store: TraceStore, session_id: str) -> SessionInfo:
    for info in store.list_sessions():
        if info.session_id == session_id:
            return info
    raise SessionNotFoundError(session_id)


def _event_dict(event: Event) -> dict[str, JSONValue]:
    dumped: dict[str, JSONValue] = event.model_dump(mode="json")
    return dumped


def _stored_final(events: Sequence[Event]) -> str | None:
    """The answer recorded by the final_answer event, or None if there is none."""
    for event in events:
        if event.type is EventType.FINAL_ANSWER:
            value = event.payload.get("value")
            answer = value.get("answer") if isinstance(value, dict) else None
            return answer if isinstance(answer, str) else None
    return None


def _diff_summary(diff: TraceDiff) -> dict[str, JSONValue]:
    kind = diff.kind.value if diff.kind is not None else None
    differing: list[JSONValue] = [
        {"step": item.step, "kind": item.kind.value, "a": item.a, "b": item.b}
        for item in diff.differing_steps
    ]
    return {
        "first_divergent_step": diff.first_divergent_step,
        "kind": kind,
        "differing_steps": differing,
        "len_a": diff.len_a,
        "len_b": diff.len_b,
    }


def list_sessions(store: TraceStore) -> list[dict[str, JSONValue]]:
    """One entry per session, oldest first, with its task (None if it has no metadata)."""
    rows: list[dict[str, JSONValue]] = []
    for info in store.list_sessions():
        events = store.load_session(info.session_id)
        metadata = events[0].payload.get("metadata") if events else None
        task = metadata.get("task") if isinstance(metadata, dict) else None
        rows.append(
            {
                "session_id": info.session_id,
                "created_at": info.created_at,
                "parent_session_id": info.parent_session_id,
                "parent_step": info.parent_step,
                "event_count": len(events),
                "task": task if isinstance(task, str) else None,
            }
        )
    return rows


def get_session(store: TraceStore, session_id: str) -> dict[str, JSONValue]:
    """One session with its metadata and every stored event, in step order."""
    info = _info(store, session_id)
    events = store.load_session(session_id)
    metadata = events[0].payload.get("metadata") if events else None
    return {
        "session_id": info.session_id,
        "created_at": info.created_at,
        "parent_session_id": info.parent_session_id,
        "parent_step": info.parent_step,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "events": [_event_dict(event) for event in events],
    }


def replay_summary(
    store: TraceStore, session_id: str, *, workspace_root: Path
) -> dict[str, JSONValue]:
    """Replay a recorded session and report the replay's counters.

    matches_recorded is True when the replayed final answer equals the one stored by the
    final_answer event. replay_counters must be all 0.
    """
    result, counters = replay_recorded_run(store, session_id, workspace_root)
    replay_counters: dict[str, JSONValue] = dict(counters)
    stored = _stored_final(store.load_session(session_id))
    return {
        "session_id": session_id,
        "final": result.final,
        "replay_counters": replay_counters,
        "matches_recorded": result.final is not None and result.final == stored,
    }


def find_bad_edit(store: TraceStore, session_id: str) -> dict[str, JSONValue]:
    """The first bad edit in a session, read from its stored events only, or None."""
    bad = find_first_bad_edit(store.load_session(session_id))
    edit: dict[str, JSONValue] | None = None
    if bad is not None:
        edit = {"step": bad[0], "path": bad[1]}
    return {"session_id": session_id, "bad_edit": edit}


def _fork(
    store: TraceStore,
    parent_session_id: str,
    at_step: int,
    *,
    override: JSONValue,
    use_override: bool,
) -> tuple[str, dict[str, JSONValue], dict[str, int]]:
    """Run the override-only fork. Returns the child id, the diff, and the real-call counters."""
    if not use_override:
        raise ForkNotSupportedError(
            "v1 fork is override-only: pass use_override=True together with an override"
        )
    # Reject values that are not finite JSON before the core creates the child session, so a
    # bad override leaves no partial child behind.
    canonical_json(override)
    parent_events = store.load_session(parent_session_id)
    task, max_steps, extra_reads = session_config(parent_events)
    calls_before = sum(1 for e in parent_events if e.step < at_step and e.type in CALL_TYPES)
    child_id = uuid.uuid4().hex
    counters = RealCallCounters()
    llm = ScriptedLLM(planned_script(extra_reads), counters)
    tools = make_tools(Workspace(FORK_NO_FILES_ROOT), counters)
    # The core checks the fork point before it creates the child. The loop then replays the
    # parent's calls, returns the override at the fork step, and stops.
    with Recorder.fork(
        store, parent_session_id, at_step, override=override, session_id=child_id
    ) as rec:
        run_agent(rec, task, llm, tools, max_steps=max_steps, max_calls=calls_before + 1)
    diff = diff_sessions(parent_events, store.load_session(child_id))
    return child_id, _diff_summary(diff), counters.snapshot()


def fork(
    store: TraceStore,
    parent_session_id: str,
    at_step: int,
    *,
    override: JSONValue = None,
    use_override: bool = False,
) -> dict[str, JSONValue]:
    """Fork a session at a call step with an override as that call's result.

    Requires use_override=True. Returns {"child_session_id", "diff"}, where diff compares the
    parent with the child. Writes no files and leaves the parent unchanged.
    """
    child_id, diff, _counters = _fork(
        store, parent_session_id, at_step, override=override, use_override=use_override
    )
    return {"child_session_id": child_id, "diff": diff}
