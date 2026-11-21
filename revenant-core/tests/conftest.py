"""Shared fixtures: a store, a fresh RealTools, a fake LLM, and the driver."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

from revenant.store import SQLiteTraceStore
from tests.fakes import RealTools, ScriptedLLM, run_driver

# Not derandomized: each run uses a new seed, so the 20x checkpoint loop searches new inputs.
settings.register_profile(
    "revenant",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("revenant")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SQLiteTraceStore]:
    # NORMAL keeps the tests fast. The store default stays FULL (see docs/kiro-notes.md).
    s = SQLiteTraceStore(tmp_path / "trace.db", synchronous="NORMAL")
    yield s
    s.close()


@pytest.fixture
def tools() -> RealTools:
    return RealTools()


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM(["three"])


@pytest.fixture
def driver() -> Callable[..., list[object]]:
    return run_driver
