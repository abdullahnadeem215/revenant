"""Scripted fake LLM. It returns canned responses by turn index and makes no network call.

The planted script makes one bad edit on purpose. The bad-edit finder never reads this module.
It reads only the recorded results.
"""

from __future__ import annotations

from collections.abc import Sequence

from revenant import JSONValue

from revenant_dev.agent import parse_response
from revenant_dev.counters import RealCallCounters
from revenant_dev.errors import ScriptExhaustedError

__all__ = [
    "CORRECT_STATS",
    "STATS_PATH",
    "TEXT_PATH",
    "WRONG_STATS",
    "ScriptedLLM",
    "planned_script",
]

STATS_PATH = "sample_pkg/stats.py"
TEXT_PATH = "sample_pkg/text.py"
FINAL_TEXT = "Divide by len(values) in mean."

WRONG_STATS = (
    '"""Statistics helpers."""\n'
    "\n"
    "\n"
    "def mean(values: list[float]) -> float:\n"
    '    """Return the arithmetic mean of values."""\n'
    "    return sum(values) / len(values) - 1\n"
)

CORRECT_STATS = (
    '"""Statistics helpers."""\n'
    "\n"
    "\n"
    "def mean(values: list[float]) -> float:\n"
    '    """Return the arithmetic mean of values."""\n'
    "    return sum(values) / len(values)\n"
)


class ScriptedLLM:
    """Returns script[turn]. The turn index is a recorded argument, so every replay and fork sees
    the same answer for the same turn."""

    def __init__(self, script: Sequence[JSONValue], counters: RealCallCounters) -> None:
        self._script: list[JSONValue] = list(script)
        self._counters = counters

    def __call__(self, turn: int, messages: list[JSONValue]) -> JSONValue:
        self._counters.llm += 1
        if not 0 <= turn < len(self._script):
            raise ScriptExhaustedError(
                f"turn {turn} is past the end of the script ({len(self._script)} turns)"
            )
        response = self._script[turn]
        parse_response(response)
        return response


def _tool(name: str, args: dict[str, JSONValue]) -> JSONValue:
    return {"tool": name, "args": args}


def planned_script(extra_reads: int = 0) -> list[JSONValue]:
    """The demo script. extra_reads adds read_file turns before the bad write.

    With extra_reads=0 the bad write is on turn 1. Each extra read moves it one turn later.
    """
    if extra_reads < 0:
        raise ValueError("extra_reads must be zero or more")
    turns: list[JSONValue] = [_tool("read_file", {"path": STATS_PATH})]
    turns.extend(_tool("read_file", {"path": TEXT_PATH}) for _ in range(extra_reads))
    turns.append(_tool("write_file", {"path": STATS_PATH, "content": WRONG_STATS}))
    turns.append(_tool("run_tests", {}))
    turns.append(_tool("write_file", {"path": STATS_PATH, "content": CORRECT_STATS}))
    turns.append(_tool("run_tests", {}))
    turns.append({"final": FINAL_TEXT})
    return turns
