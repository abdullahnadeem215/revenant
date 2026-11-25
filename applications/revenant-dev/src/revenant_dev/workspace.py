"""Workspace paths and sample copies.

Every tool path goes through Workspace.resolve. A session edits its own copy of the sample, so
the committed sample_repo/ is never changed by a run.

Known limit (design D5): recorded file content is redacted by revenant-core. A recorded write
may hold [REDACTED] in place of a secret. This module has no file restore; live fork restore
is stretch S1.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from revenant_dev.errors import SandboxViolationError

__all__ = ["Workspace", "copy_sample"]

_IGNORED_NAMES = shutil.ignore_patterns("__pycache__", ".pytest_cache")


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve(self, relative: str) -> Path:
        """Return the absolute path for a relative path inside the workspace.

        Raises SandboxViolationError for an empty or absolute path, or for any path that
        resolves outside the root. Path.resolve() follows symlinks, so a symlink that leaves the
        root is caught by the same check.
        """
        if not relative:
            raise SandboxViolationError("empty path is not allowed")
        candidate = Path(relative)
        if candidate.is_absolute() or candidate.drive:
            raise SandboxViolationError(f"absolute path is not allowed: {relative!r}")
        resolved = (self.root / candidate).resolve()
        if not resolved.is_relative_to(self.root):
            raise SandboxViolationError(f"path leaves the workspace: {relative!r}")
        return resolved


def copy_sample(sample: Path, dest: Path) -> None:
    """Copy the sample package to dest, skipping bytecode and pytest caches."""
    shutil.copytree(sample, dest, ignore=_IGNORED_NAMES)
