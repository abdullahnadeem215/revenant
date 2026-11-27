from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient
from revenant import EventType, JSONValue, Recorder, SQLiteTraceStore

import revenant_dev.http as http_module
from revenant_dev.agent import run_agent
from revenant_dev.api import find_bad_edit, fork, get_session, list_sessions, replay_summary
from revenant_dev.counters import RealCallCounters
from revenant_dev.demo import RecordedRun, record_scripted_run
from revenant_dev.http import FRONTEND_ORIGINS, create_app, main
from revenant_dev.llm import ScriptedLLM


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "http-sessions.db"


@pytest.fixture
def recorded(db_path: Path, workspace_root: Path) -> RecordedRun:
    store = SQLiteTraceStore(db_path)
    try:
        return record_scripted_run(store, workspace_root, extra_reads=0)
    finally:
        store.close()


@pytest.fixture
def reader(db_path: Path, recorded: RecordedRun) -> Iterator[SQLiteTraceStore]:
    store = SQLiteTraceStore(db_path)
    yield store
    store.close()


@pytest.fixture
def client(db_path: Path, workspace_root: Path, recorded: RecordedRun) -> Iterator[TestClient]:
    with TestClient(create_app(db_path, workspace_root)) as test_client:
        yield test_client


def _bad_step(reader: SQLiteTraceStore, session_id: str) -> int:
    edit = find_bad_edit(reader, session_id)["bad_edit"]
    assert isinstance(edit, dict)
    step = edit["step"]
    assert isinstance(step, int)
    return step


def test_list_sessions_endpoint_equals_the_function(
    client: TestClient, reader: SQLiteTraceStore
) -> None:
    response = client.get("/sessions")
    assert response.status_code == 200
    assert response.json() == list_sessions(reader)


def test_get_session_endpoint_equals_the_function(
    client: TestClient, reader: SQLiteTraceStore, recorded: RecordedRun
) -> None:
    response = client.get(f"/sessions/{recorded.session_id}")
    assert response.status_code == 200
    assert response.json() == get_session(reader, recorded.session_id)


def test_replay_endpoint_equals_the_function(
    client: TestClient,
    reader: SQLiteTraceStore,
    recorded: RecordedRun,
    workspace_root: Path,
) -> None:
    response = client.get(f"/sessions/{recorded.session_id}/replay")
    assert response.status_code == 200
    expected = replay_summary(reader, recorded.session_id, workspace_root=workspace_root)
    assert response.json() == expected
    assert response.json()["replay_counters"] == {
        "llm": 0,
        "read_file": 0,
        "write_file": 0,
        "run_tests": 0,
    }


def test_bad_edit_endpoint_equals_the_function(
    client: TestClient, reader: SQLiteTraceStore, recorded: RecordedRun
) -> None:
    response = client.get(f"/sessions/{recorded.session_id}/bad-edit")
    assert response.status_code == 200
    assert response.json() == find_bad_edit(reader, recorded.session_id)


def test_fork_endpoint_returns_a_child_with_the_functions_diff(
    client: TestClient, reader: SQLiteTraceStore, recorded: RecordedRun
) -> None:
    step = _bad_step(reader, recorded.session_id)
    body = {"at_step": step, "override": {"ok": True}, "use_override": True}
    response = client.post(f"/sessions/{recorded.session_id}/fork", json=body)
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"child_session_id", "diff"}
    assert data["child_session_id"] != recorded.session_id
    direct = fork(reader, recorded.session_id, step, override={"ok": True}, use_override=True)
    assert data["diff"] == direct["diff"]
    child_info = {s.session_id: s for s in reader.list_sessions()}[data["child_session_id"]]
    assert child_info.parent_session_id == recorded.session_id
    assert child_info.parent_step == step


def test_fork_without_use_override_returns_400_not_500(
    client: TestClient, reader: SQLiteTraceStore, recorded: RecordedRun
) -> None:
    step = _bad_step(reader, recorded.session_id)
    before = len(reader.list_sessions())
    response = client.post(f"/sessions/{recorded.session_id}/fork", json={"at_step": step})
    assert response.status_code == 400
    assert "use_override" in response.json()["detail"]
    assert len(reader.list_sessions()) == before


def test_fork_at_a_non_call_step_returns_400(
    client: TestClient, reader: SQLiteTraceStore, recorded: RecordedRun
) -> None:
    answer_step = next(
        e.step for e in reader.load_session(recorded.session_id) if e.type.value == "tool_result"
    )
    body = {"at_step": answer_step, "override": {"ok": True}, "use_override": True}
    response = client.post(f"/sessions/{recorded.session_id}/fork", json=body)
    assert response.status_code == 400


def test_unknown_session_returns_404_on_every_route(client: TestClient) -> None:
    assert client.get("/sessions/no-such-session").status_code == 404
    assert client.get("/sessions/no-such-session/replay").status_code == 404
    assert client.get("/sessions/no-such-session/bad-edit").status_code == 404
    body = {"at_step": 7, "override": {"ok": True}, "use_override": True}
    assert client.post("/sessions/no-such-session/fork", json=body).status_code == 404


def test_fork_body_without_at_step_returns_422(client: TestClient, recorded: RecordedRun) -> None:
    response = client.post(f"/sessions/{recorded.session_id}/fork", json={"use_override": True})
    assert response.status_code == 422


def test_cors_allows_the_frontend_origins_only(client: TestClient) -> None:
    assert FRONTEND_ORIGINS == ["http://localhost:5173", "http://127.0.0.1:5173"]
    for origin in FRONTEND_ORIGINS:
        response = client.get("/sessions", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin
    refused = client.get("/sessions", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in refused.headers


def test_cors_preflight_for_fork_from_the_frontend(client: TestClient) -> None:
    response = client.options(
        "/sessions/x/fork",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_main_binds_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(app: object, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(http_module, "create_app", lambda *_args: object())
    monkeypatch.setattr(uvicorn, "run", fake_run)
    main()
    assert captured == {"host": "127.0.0.1", "port": 8000}


def _record_mismatched_session(db_path: Path) -> str:
    """Record a session whose metadata says task A while the agent ran with task B. Replay reads
    the metadata, so its first LLM call differs from the recording."""
    store = SQLiteTraceStore(db_path)
    try:
        metadata: dict[str, JSONValue] = {"task": "task A", "max_steps": 3, "extra_reads": 0}
        script: list[JSONValue] = [{"final": "done"}]
        llm = ScriptedLLM(script, RealCallCounters())
        with Recorder.record(store, session_id="mismatch", metadata=metadata) as rec:
            run_agent(rec, "task B", llm, {}, max_steps=3)
    finally:
        store.close()
    return "mismatch"


def test_divergence_maps_to_409_with_step_and_details(client: TestClient, db_path: Path) -> None:
    session_id = _record_mismatched_session(db_path)
    store = SQLiteTraceStore(db_path)
    try:
        first_call = next(
            e.step for e in store.load_session(session_id) if e.type is EventType.LLM_CALL
        )
    finally:
        store.close()
    response = client.get(f"/sessions/{session_id}/replay")
    assert response.status_code == 409
    body = response.json()
    assert body["step"] == first_call
    assert body["reason"] == "arguments differ"
    assert {"detail", "step", "expected", "actual", "reason"} <= set(body)


def test_session_without_agent_metadata_maps_to_409_with_message(
    client: TestClient, db_path: Path
) -> None:
    store = SQLiteTraceStore(db_path)
    try:
        with Recorder.record(store, session_id="bare") as rec:
            rec.final_answer({"answer": "no metadata"})
    finally:
        store.close()
    response = client.get("/sessions/bare/replay")
    assert response.status_code == 409
    assert "has no agent metadata" in response.json()["detail"]
    fork_response = client.post(
        "/sessions/bare/fork", json={"at_step": 1, "override": None, "use_override": True}
    )
    assert fork_response.status_code == 409


def test_non_finite_override_returns_400_and_creates_no_child(
    client: TestClient, reader: SQLiteTraceStore, recorded: RecordedRun
) -> None:
    step = _bad_step(reader, recorded.session_id)
    before = len(reader.list_sessions())
    raw = f'{{"at_step": {step}, "override": NaN, "use_override": true}}'
    response = client.post(
        f"/sessions/{recorded.session_id}/fork",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert len(reader.list_sessions()) == before
