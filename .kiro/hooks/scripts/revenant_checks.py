"""Checks run by the Revenant Kiro hooks: revenant_checks.py lint|related|invariants."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3] / "revenant-core"
INVARIANT_TESTS = "tests/test_invariants.py"


def saved_file() -> str:
    """Return the saved .py path from argv or from the hook event JSON on STDIN."""
    if len(sys.argv) > 2 and sys.argv[2].endswith(".py"):
        return sys.argv[2]
    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    try:
        text = json.dumps(json.loads(raw)) if raw.strip() else ""
    except json.JSONDecodeError:
        text = raw
    match = re.search(r"[^\"\s]*revenant-core[\\/]+(?:src|tests)[^\"\s]*?\.py", text)
    return match.group(0).replace("\\\\", "/").replace("\\", "/") if match else ""


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


def related() -> int:
    path = saved_file()
    name = Path(path).stem
    if "/tests/" in path:
        target = f"tests/{Path(path).name}"
    else:
        target = f"tests/test_{name}.py"
    if not (CORE / target).exists():
        print(f"No related test file {target} for {path or 'unknown file'}; skipped.")
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


if __name__ == "__main__":
    actions = {"lint": lint, "related": related, "invariants": invariants}
    if len(sys.argv) < 2 or sys.argv[1] not in actions:
        sys.exit("usage: revenant_checks.py lint|related|invariants [file]")
    sys.exit(actions[sys.argv[1]]())
