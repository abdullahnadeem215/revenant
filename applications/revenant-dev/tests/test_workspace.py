from __future__ import annotations

import os
from pathlib import Path

import pytest

from revenant_dev.errors import SandboxViolationError
from revenant_dev.workspace import Workspace, copy_sample


def test_resolve_inside_root(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    assert ws.resolve("sample_pkg/stats.py") == tmp_path.resolve() / "sample_pkg" / "stats.py"


@pytest.mark.parametrize("bad", ["", "../outside.txt", "sub/../../outside.txt"])
def test_rejects_escape_and_empty(tmp_path: Path, bad: str) -> None:
    with pytest.raises(SandboxViolationError):
        Workspace(tmp_path / "root").resolve(bad)


def test_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(SandboxViolationError):
        Workspace(tmp_path).resolve(str(tmp_path / "x.txt"))


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        os.symlink(outside, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks needs a privilege this machine does not grant")
    with pytest.raises(SandboxViolationError):
        Workspace(root).resolve("link/secret.txt")


def test_copy_sample_skips_caches(sample_dir: Path, tmp_path: Path) -> None:
    dest = tmp_path / "copy"
    copy_sample(sample_dir, dest)
    assert (dest / "pytest.ini").is_file()
    assert not [p for p in dest.rglob("*") if "__pycache__" in p.parts]
