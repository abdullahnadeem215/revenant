from __future__ import annotations

import pytest
from revenant import JSONValue

from revenant_dev.counters import RealCallCounters
from revenant_dev.errors import AgentProtocolError, ScriptExhaustedError
from revenant_dev.llm import STATS_PATH, WRONG_STATS, ScriptedLLM, planned_script


def test_returns_the_turn_and_counts_the_call() -> None:
    counters = RealCallCounters()
    llm = ScriptedLLM([{"final": "done"}], counters)
    assert llm(turn=0, messages=[]) == {"final": "done"}
    assert counters.llm == 1


def test_turn_past_the_end_raises() -> None:
    counters = RealCallCounters()
    llm = ScriptedLLM([{"final": "done"}], counters)
    with pytest.raises(ScriptExhaustedError):
        llm(turn=1, messages=[])
    assert counters.llm == 1


def test_bad_response_shape_raises_protocol_error() -> None:
    script: list[JSONValue] = [{"tool": "run_tests"}]
    llm = ScriptedLLM(script, RealCallCounters())
    with pytest.raises(AgentProtocolError):
        llm(turn=0, messages=[])


def test_planned_script_length_follows_extra_reads() -> None:
    assert len(planned_script(0)) == 6
    assert len(planned_script(1)) == 7


def test_planned_script_has_one_bad_write_on_the_expected_turn() -> None:
    script = planned_script(0)
    assert script[1] == {"tool": "write_file", "args": {"path": STATS_PATH, "content": WRONG_STATS}}
    assert script[-1] == {"final": "Divide by len(values) in mean."}


def test_negative_extra_reads_is_rejected() -> None:
    with pytest.raises(ValueError):
        planned_script(-1)
