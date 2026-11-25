from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from revenant import JSONValue

from revenant_dev.counters import RealCallCounters
from revenant_dev.errors import SandboxViolationError, ToolError
from revenant_dev.llm import CORRECT_STATS, STATS_PATH
from revenant_dev.tools import make_tools
from revenant_dev.workspace import Workspace, copy_sample

Tool = Callable[..., JSONValue]


@pytest.fixture
def fixture_tools(sample_dir: Path, tmp_path: Path) -> tuple[dict[str, Tool], RealCallCounters]:
    dest = tmp_path / "ws"
    copy_sample(sample_dir, dest)
    counters = RealCallCounters()
    return make_tools(Workspace(dest), counters), counters


def test_read_and_write_round_trip(fixture_tools: tuple[dict[str, Tool], RealCallCounters]) -> None:
    tools, counters = fixture_tools
    written = tools["write_file"](path="notes.txt", content="hello\n")
    assert written == {"path": "notes.txt", "bytes": 6}
    read = tools["read_file"](path="notes.txt")
    assert read == {"path": "notes.txt", "content": "hello\n"}
    assert counters.write_file == 1
    assert counters.read_file == 1


def test_rejected_path_counts_as_a_call_and_writes_nothing(
    fixture_tools: tuple[dict[str, Tool], RealCallCounters], tmp_path: Path
) -> None:
    tools, counters = fixture_tools
    with pytest.raises(SandboxViolationError):
        tools["write_file"](path="../escape.txt", content="x")
    assert counters.write_file == 1
    assert not (tmp_path / "escape.txt").exists()


def test_missing_file_raises_tool_error(
    fixture_tools: tuple[dict[str, Tool], RealCallCounters],
) -> None:
    tools, _ = fixture_tools
    with pytest.raises(ToolError):
        tools["read_file"](path="does/not/exist.py")


def test_run_tests_reports_the_planted_failure(
    fixture_tools: tuple[dict[str, Tool], RealCallCounters],
) -> None:
    tools, counters = fixture_tools
    result = tools["run_tests"]()
    assert result == {
        "exit_code": 1,
        "passed": 2,
        "failed": 1,
        "failed_tests": ["tests/test_stats.py::test_mean_of_three"],
    }
    assert counters.run_tests == 1


def test_run_tests_passes_after_the_correct_fix(
    fixture_tools: tuple[dict[str, Tool], RealCallCounters],
) -> None:
    tools, _ = fixture_tools
    tools["write_file"](path=STATS_PATH, content=CORRECT_STATS)
    result = tools["run_tests"]()
    assert result == {"exit_code": 0, "passed": 3, "failed": 0, "failed_tests": []}


def test_sample_dir_is_not_touched_by_tools(sample_dir: Path, tmp_path: Path) -> None:
    before = (sample_dir / "sample_pkg" / "stats.py").read_bytes()
    dest = tmp_path / "ws"
    shutil.copytree(sample_dir, dest, ignore=shutil.ignore_patterns("__pycache__"))
    tools = make_tools(Workspace(dest), RealCallCounters())
    tools["write_file"](path=STATS_PATH, content=CORRECT_STATS)
    assert (sample_dir / "sample_pkg" / "stats.py").read_bytes() == before
