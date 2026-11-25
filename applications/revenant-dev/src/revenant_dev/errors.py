"""Typed errors for revenant-dev.

Every class takes one message argument. revenant-core rebuilds a recorded exception with
cls(*args) and compares its str() with the recorded message, so this keeps replayed errors
identical to the originals.
"""

from __future__ import annotations

__all__ = [
    "AgentProtocolError",
    "AgentStepLimitError",
    "DemoError",
    "SandboxViolationError",
    "ScriptExhaustedError",
    "ToolError",
]


class DemoError(Exception):
    """Base class for every error raised by revenant-dev."""


class ToolError(DemoError):
    """A tool failed in a way the model can see. The agent returns it as the tool result."""


class SandboxViolationError(ToolError):
    """A path resolved outside the workspace root, or was absolute or empty."""


class ScriptExhaustedError(DemoError):
    """The scripted LLM was asked for a turn past the end of its script."""


class AgentProtocolError(DemoError):
    """The model sent a response or a tool request the agent cannot use."""


class AgentStepLimitError(DemoError):
    """The agent used max_steps turns without a final answer."""
