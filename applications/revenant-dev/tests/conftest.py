from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from revenant import SQLiteTraceStore

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_repo"


@pytest.fixture
def sample_dir() -> Path:
    return SAMPLE_DIR


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path / "workspaces"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SQLiteTraceStore]:
    trace_store = SQLiteTraceStore(tmp_path / "sessions.db")
    yield trace_store
    trace_store.close()
