"""Checks run by the Revenant Kiro hooks.

Usage: revenant_checks.py lint | related [FILE] | invariants

related takes the saved file from its second argument (manual use), or else from the
`file_path` key of the JSON Kiro writes to stdin (the hook). It falls back to searching
stdin for a revenant-core path.
Logging is off unless REVENANT_HOOK_LOG names a file. A log line holds the action, the
resolved file path and the names of the top-level stdin JSON keys. It never holds stdin
values.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "revenant-core"
INVARIANT_TESTS = "tests/test_invariants.py"
PATH_IN_TEXT = re.compile(r"[^\"\s]*revenant-core[\\/]+(?:src|tests)[^\"\s]*?\.py")


def log(message: str) -> None:
    """Append one line to the file named by REVENANT_HOOK_LOG. Off unless that variable is set."""
    target = os.environ.get("REVENANT_HOOK_LOG", "")
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def normalize(path: str) -> str:
    return path.replace("\\\\", "/").replace("\\", "/")


def saved_file(arg: str) -> tuple[str, list[str]]:
    """Return (path, top-level stdin JSON keys). The path comes from arg when it is a real
    .py path, otherwise from the first revenant-core path found on stdin."""
    if arg.endswith(".py") and "{{" not in arg:
        return normalize(arg), []
    if sys.stdin.isatty():
        return "", []
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        match = PATH_IN_TEXT.search(raw)
        return (normalize(match.group(0)) if match else ""), []
    keys = sorted(data)
    file_path = data.get("file_path")
    if isinstance(file_path, str) and file_path.endswith(".py"):
        return normalize(file_path), keys
    match = PATH_IN_TEXT.search(raw)
    return (normalize(match.group(0)) if match else ""), keys


def run(*cmd: str) -> int:
    """Run `python -m <cmd>` inside revenant-core (preferring its .venv) and echo the output."""
    if not CORE.is_dir():
        print(f"{CORE} does not exist yet; check skipped.")
        return 0
    venv = CORE / ".venv" / "Scripts" / "python.exe"
    python = str(venv) if venv.exists() else sys.executable
    proc = subprocess.run([python, "-m", *cmd], cwd=CORE, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    print(out, file=sys.stderr if proc.returncode else sys.stdout)
    return proc.returncode


def lint() -> int:
    ruff = run("ruff", "check", "src")
    mypy = run("mypy", "--strict", "src")
    if ruff or mypy:
        print("FAILED: ruff and/or mypy --strict reported errors in src/.", file=sys.stderr)
    return 1 if ruff or mypy else 0


def related(arg: str) -> int:
    path, keys = saved_file(arg)
    log(f"related arg={arg!r} stdin_keys={keys} resolved={path!r}")
    if not path:
        print("Could not find the saved file path; related tests skipped.")
        return 0
    stem = Path(path).stem
    target = f"tests/{Path(path).name}" if "/tests/" in path else f"tests/test_{stem}.py"
    if not (CORE / target).exists():
        print(f"No related test file {target} for {path}; skipped.")
        return 0
    return run("pytest", "-q", "-p", "no:cacheprovider", target)


def invariants() -> int:
    if not (CORE / INVARIANT_TESTS).exists():
        print(f"{INVARIANT_TESTS} does not exist yet; invariant check skipped.")
        return 0
    code = run("pytest", "-q", "-p", "no:cacheprovider", INVARIANT_TESTS)
    if code:
        print("WARNING: invariant tests failed (zero real calls in replay / divergence detection).",
              file=sys.stderr)
    return code


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else ""
    arg = argv[2] if len(argv) > 2 else ""
    if action == "lint":
        code = lint()
    elif action == "related":
        code = related(arg)
    elif action == "invariants":
        code = invariants()
    else:
        sys.exit("usage: revenant_checks.py lint | related [FILE] | invariants")
    log(f"action={action} exit={code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
