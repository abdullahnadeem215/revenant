from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from revenant import DivergenceError, JSONValue, Recorder, SQLiteTraceStore

from revenant_dev.agent import run_agent
from revenant_dev.counters import RealCallCounters
from revenant_dev.errors import AgentProtocolError, AgentStepLimitError
from revenant_dev.llm import ScriptedLLM
from revenant_dev.tools import make_tools
from revenant_dev.workspace import Workspace


def _ping() -> JSONValue:
    return {"ok": True}


def _ping_with_x(x: int) -> JSONValue:
    return {"x": x}


def test_unknown_tool_raises_protocol_error(store: SQLiteTraceStore) -> None:
    script: list[JSONValue] = [{"tool": "nope", "args": {}}]
    llm = ScriptedLLM(script, RealCallCounters())
    with Recorder.record(store) as rec, pytest.raises(AgentProtocolError):
        run_agent(rec, "t", llm, {"ping": _ping}, max_steps=3)


def test_bad_arguments_raise_protocol_error(store: SQLiteTraceStore) -> None:
    script: list[JSONValue] = [{"tool": "ping", "args": {"y": 1}}]
    llm = ScriptedLLM(script, RealCallCounters())
    with Recorder.record(store) as rec, pytest.raises(AgentProtocolError):
        run_agent(rec, "t", llm, {"ping": _ping_with_x}, max_steps=3)


def test_non_object_args_raise_protocol_error(store: SQLiteTraceStore) -> None:
    script: list[JSONValue] = [{"tool": "ping", "args": "x"}]
    llm = ScriptedLLM(script, RealCallCounters())
    with Recorder.record(store) as rec, pytest.raises(AgentProtocolError):
        run_agent(rec, "t", llm, {"ping": _ping}, max_steps=3)


def test_step_limit_without_final_answer(store: SQLiteTraceStore) -> None:
    script: list[JSONValue] = [{"tool": "ping", "args": {}}, {"tool": "ping", "args": {}}]
    llm = ScriptedLLM(script, RealCallCounters())
    with Recorder.record(store) as rec, pytest.raises(AgentStepLimitError):
        run_agent(rec, "t", llm, {"ping": _ping}, max_steps=2)


def test_tool_error_is_returned_to_the_model(store: SQLiteTraceStore, tmp_path: Path) -> None:
    (tmp_path / "ws").mkdir()
    counters = RealCallCounters()
    tools = make_tools(Workspace(tmp_path / "ws"), counters)
    script: list[JSONValue] = [
        {"tool": "read_file", "args": {"path": "../outside.txt"}},
        {"final": "saw the error"},
    ]
    with Recorder.record(store) as rec:
        result = run_agent(rec, "t", ScriptedLLM(script, RealCallCounters()), tools, max_steps=3)
    assert result.final == "saw the error"
    tool_turns = [m for m in result.messages if isinstance(m, dict) and m.get("role") == "tool"]
    assert len(tool_turns) == 1
    assert isinstance(tool_turns[0], dict) and "error" in str(tool_turns[0]["content"])
    assert counters.read_file == 1


def test_max_calls_stops_after_that_many_completed_calls(store: SQLiteTraceStore) -> None:
    script: list[JSONValue] = [{"tool": "ping", "args": {}}, {"final": "done"}]
    counters = RealCallCounters()
    with Recorder.record(store) as rec:
        result = run_agent(
            rec, "t", ScriptedLLM(script, counters), {"ping": _ping}, max_steps=3, max_calls=1
        )
    assert result.final is None
    assert counters.llm == 1


def test_max_calls_two_includes_the_tool_call(store: SQLiteTraceStore) -> None:
    script: list[JSONValue] = [{"tool": "ping", "args": {}}, {"final": "done"}]
    counters = RealCallCounters()
    with Recorder.record(store) as rec:
        result = run_agent(
            rec, "t", ScriptedLLM(script, counters), {"ping": _ping}, max_steps=3, max_calls=2
        )
    assert result.final is None
    assert counters.llm == 1


def test_changed_agent_raises_divergence_on_replay(store: SQLiteTraceStore) -> None:
    script: list[JSONValue] = [{"tool": "ping", "args": {}}, {"final": "done"}]
    tools: dict[str, Callable[..., JSONValue]] = {"ping": _ping}
    with Recorder.record(store, session_id="div") as rec:
        llm = ScriptedLLM(script, RealCallCounters())
        run_agent(rec, "task A", llm, tools, max_steps=3)
    with Recorder.replay(store, "div") as rec, pytest.raises(DivergenceError) as info:
        llm = ScriptedLLM(script, RealCallCounters())
        run_agent(rec, "task B", llm, tools, max_steps=3)
    assert info.value.step == 1
