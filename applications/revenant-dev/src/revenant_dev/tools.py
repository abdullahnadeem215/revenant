"""The three tools the agent can call: read_file, write_file and run_tests.

Each real function increments its own counter before any check, so a rejected path still
counts as a call. Replay never reaches these functions.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from revenant import JSONValue

from revenant_dev.counters import RealCallCounters
from revenant_dev.errors import ToolError
from revenant_dev.workspace import Workspace

__all__ = ["RUN_TESTS_TIMEOUT_S", "make_tools"]

RUN_TESTS_TIMEOUT_S = 60
_PYTEST_ARGS = ["-m", "pytest", "-p", "no:cacheprovider", "-rf", "-q"]
_COUNT = re.compile(r"(\d+) (passed|failed)")


def make_tools(
    workspace: Workspace, counters: RealCallCounters
) -> dict[str, Callable[..., JSONValue]]:
    def read_file(path: str) -> JSONValue:
        counters.read_file += 1
        target = workspace.resolve(path)
        try:
            content = target.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ToolError(f"no such file: {path}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError(f"cannot read {path}: {exc}") from exc
        return {"path": path, "content": content}

    def write_file(path: str, content: str) -> JSONValue:
        counters.write_file += 1
        target = workspace.resolve(path)
        data = content.encode("utf-8")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            raise ToolError(f"cannot write {path}: {exc}") from exc
        return {"path": path, "bytes": len(data)}

    def run_tests() -> JSONValue:
        counters.run_tests += 1
        return _run_pytest(workspace.root)

    return {"read_file": read_file, "write_file": write_file, "run_tests": run_tests}


def _run_pytest(root: Path) -> JSONValue:
    """Run pytest in the workspace and return counts and failing node ids only.

    Timings, durations and temporary paths are left out, so the recorded result is small
    and stable.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [sys.executable, *_PYTEST_ARGS],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=RUN_TESTS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"run_tests exceeded {RUN_TESTS_TIMEOUT_S} seconds") from exc
    passed, failed = _parse_counts(proc.stdout)
    failed_tests: list[JSONValue] = [
        line[len("FAILED ") :].split(" - ")[0]
        for line in proc.stdout.splitlines()
        if line.startswith("FAILED ")
    ]
    return {
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "failed_tests": failed_tests,
    }


def _parse_counts(output: str) -> tuple[int, int]:
    """Read the pass and fail counts from pytest's final summary line."""
    lines = [line for line in output.splitlines() if line.strip()]
    summary = lines[-1] if lines else ""
    counts = {kind: int(number) for number, kind in _COUNT.findall(summary)}
    return counts.get("passed", 0), counts.get("failed", 0)
