"""Shared test fixtures. Recorder fixtures (fake LLM, tools, driver) are added in Phase 3."""

from __future__ import annotations

from hypothesis import HealthCheck, settings

# Not derandomized: each run uses a new seed, so the 20x checkpoint loop searches new inputs.
settings.register_profile(
    "revenant",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("revenant")
