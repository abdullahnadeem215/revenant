"""The agent loop.

One function serves record, replay and fork. It wraps the raw LLM and the raw tools with
whatever Recorder it is given, so the same code runs live and under replay.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from revenant import JSONValue, Recorder

from revenant_dev.errors import AgentProtocolError, AgentStepLimitError, ToolError

__all__ = [
    "AgentResult",
    "FinalAnswer",
    "ToolRequest",
    "parse_response",
    "run_agent",
]


@dataclass(frozen=True)
class ToolRequest:
    name: str
    args: dict[str, JSONValue]


@dataclass(frozen=True)
class FinalAnswer:
    text: str


@dataclass(frozen=True)
class AgentResult:
    """final is None when the loop stopped at max_calls before a final answer."""

    final: str | None
    messages: list[JSONValue]


def parse_response(response: JSONValue) -> ToolRequest | FinalAnswer:
    """Read one LLM response. Only the keys and types are checked, never the values."""
    if not isinstance(response, dict):
        raise AgentProtocolError("LLM response must be a JSON object")
    final = response.get("final")
    if set(response) == {"final"} and isinstance(final, str):
        return FinalAnswer(final)
    name = response.get("tool")
    args = response.get("args")
    if set(response) == {"tool", "args"} and isinstance(name, str) and isinstance(args, dict):
        return ToolRequest(name, args)
    raise AgentProtocolError(f"LLM response has an unknown shape with keys {sorted(response)}")


def _check_arguments(fn: Callable[..., JSONValue], name: str, args: dict[str, JSONValue]) -> None:
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as exc:
        raise AgentProtocolError(f"bad arguments for {name}: {exc}") from exc


def run_agent(
    rec: Recorder,
    task: str,
    llm: Callable[..., JSONValue],
    tools: Mapping[str, Callable[..., JSONValue]],
    *,
    max_steps: int,
    max_calls: int | None = None,
) -> AgentResult:
    """Run the loop until a final answer, max_calls, or max_steps.

    max_calls counts completed wrapped calls (LLM and tool together). The loop returns as soon
    as that many have completed, so a fork can stop at its fork step.

    A ToolError from a tool becomes the tool result, so the model can react to it. Every other
    exception, including DivergenceError from the core, reaches the caller.
    """
    wrapped_llm = rec.wrap_llm(llm, name="llm")
    wrapped_tools = {name: rec.wrap_tool(fn, name=name) for name, fn in tools.items()}
    history: list[JSONValue] = [{"role": "user", "content": task}]
    calls = 0
    for turn in range(max_steps):
        response = wrapped_llm(turn=turn, messages=history)
        calls += 1
        if max_calls is not None and calls >= max_calls:
            return AgentResult(final=None, messages=history)
        history.append({"role": "assistant", "content": response})
        request = parse_response(response)
        if isinstance(request, FinalAnswer):
            rec.final_answer({"answer": request.text})
            return AgentResult(final=request.text, messages=history)
        tool_fn = tools.get(request.name)
        if tool_fn is None:
            raise AgentProtocolError(f"unknown tool {request.name!r}")
        _check_arguments(tool_fn, request.name, request.args)
        result: JSONValue
        try:
            result = wrapped_tools[request.name](**request.args)
        except ToolError as exc:
            result = {"error": str(exc)}
        history.append({"role": "tool", "name": request.name, "content": result})
        calls += 1
        if max_calls is not None and calls >= max_calls:
            return AgentResult(final=None, messages=history)
    raise AgentStepLimitError(f"no final answer after {max_steps} turns")
