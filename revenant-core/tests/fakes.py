"""Fakes for recorder tests: a scripted fake LLM, plain tools with call counters, and the
driver. The driver is a fixed sequence of calls, not an agent. No test contacts a real model."""

from __future__ import annotations

import asyncio

from revenant.events import JSONValue
from revenant.recorder import Recorder


class ScriptedLLM:
    """Returns canned responses by call index and counts calls. Never calls a model."""

    def __init__(self, responses: list[JSONValue]) -> None:
        self._responses = responses
        self.calls = 0

    def __call__(self, prompt: str) -> JSONValue:
        index = self.calls
        self.calls += 1
        return self._responses[index]


class RealTools:
    """Plain tool functions. Each counts its real invocations."""

    def __init__(self) -> None:
        self.add_calls = 0
        self.lookup_calls = 0
        self.fail_calls = 0
        self.login_calls = 0
        self.seen_passwords: list[str] = []

    def add(self, a: int, b: int) -> int:
        """Add two integers."""
        self.add_calls += 1
        return a + b

    async def lookup(self, key: str) -> dict[str, JSONValue]:
        """Look up a key asynchronously."""
        self.lookup_calls += 1
        await asyncio.sleep(0)
        return {"key": key, "found": True}

    def fail(self, reason: str) -> int:
        """Always raises ValueError."""
        self.fail_calls += 1
        raise ValueError(reason)

    def login(self, user: str, password: str) -> bool:
        """Accepts any user and records the password it actually received."""
        self.login_calls += 1
        self.seen_passwords.append(password)
        return True


async def _drive(recorder: Recorder, llm: ScriptedLLM, tools: RealTools) -> list[object]:
    ask = recorder.wrap_llm(llm, name="llm")
    add = recorder.wrap_tool(tools.add)
    lookup = recorder.wrap_tool(tools.lookup)
    fail = recorder.wrap_tool(tools.fail)
    outputs: list[object] = []
    outputs.append(ask("what is 1 + 2?"))
    outputs.append(add(1, 2))
    outputs.append(await lookup("cats"))
    try:
        fail("boom")
    except ValueError as exc:
        outputs.append(f"caught: {exc}")
    recorder.final_answer({"done": True})
    return outputs


def run_driver(recorder: Recorder, llm: ScriptedLLM, tools: RealTools) -> list[object]:
    """Run the fixed sequence: llm, add, lookup (async), fail, then a final answer."""
    return asyncio.run(_drive(recorder, llm, tools))
