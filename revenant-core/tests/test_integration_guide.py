from __future__ import annotations

import re
from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "integration-guide.md"


def python_blocks() -> list[str]:
    return re.findall(r"```python\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.DOTALL)


def test_guide_is_under_150_lines() -> None:
    assert len(GUIDE.read_text(encoding="utf-8").splitlines()) < 150


def test_guide_has_exactly_one_example() -> None:
    assert len(python_blocks()) == 1


def test_guide_example_runs_and_checks_its_own_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    exec(compile(python_blocks()[0], "integration-guide.md", "exec"), {})  # noqa: S102
