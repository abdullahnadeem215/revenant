from __future__ import annotations

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parents[1] / "README.md"


def python_example() -> str:
    match = re.search(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.DOTALL)
    assert match is not None, "README has no python example"
    return match.group(1)


def test_readme_example_is_under_twenty_lines() -> None:
    assert len(python_example().strip().splitlines()) < 20


def test_readme_example_runs_and_replay_makes_no_real_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the example writes trace.db to the working directory
    namespace: dict[str, object] = {}
    exec(compile(python_example(), "README.md", "exec"), namespace)  # noqa: S102
    assert namespace["calls"] == {"search": 1}


def test_readme_states_each_known_limitation() -> None:
    text = README.read_text(encoding="utf-8").lower()
    for phrase in [
        "truncation",
        "best-effort",
        "over-redact",
        "__qualname__",
        "only when it completes",
        "exception text",
        "recorder is closed",
        "sequential",
        "side effects",
        "partial child",
    ]:
        assert phrase in text, f"README limitations do not mention {phrase!r}"
