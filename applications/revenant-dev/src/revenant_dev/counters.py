"""Real-call counters. Each real function increments its own field when its body runs.

Replay must leave every field at 0. Tests assert on these counters, not on printed output.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RealCallCounters"]


@dataclass
class RealCallCounters:
    llm: int = 0
    read_file: int = 0
    write_file: int = 0
    run_tests: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "llm": self.llm,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "run_tests": self.run_tests,
        }

    def reset(self) -> None:
        self.llm = 0
        self.read_file = 0
        self.write_file = 0
        self.run_tests = 0
