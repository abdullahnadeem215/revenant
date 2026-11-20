from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from revenant.errors import PayloadSerializationError
from revenant.events import (
    GENESIS_HASH,
    REDACTED,
    Event,
    EventType,
    JSONValue,
    build_event,
    canonical_json,
    compute_hash,
    default_redactor,
    request_fingerprint,
)

# ---------- strategies ----------

json_scalars: st.SearchStrategy[JSONValue] = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=8),
    st.floats(allow_nan=False, allow_infinity=False),
)
json_keys = st.text(max_size=6) | st.sampled_from(["Token", "PASSWORD", "api_key", "Cookie"])
json_values: st.SearchStrategy[JSONValue] = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(json_keys, children, max_size=4)
    ),
    max_leaves=12,
)
json_objects = st.dictionaries(st.text(max_size=6), json_values, max_size=5)


def reorder(value: JSONValue, reverse: bool) -> JSONValue:
    """Rebuild every dict with its keys inserted in a different order."""
    if isinstance(value, dict):
        keys = sorted(value, reverse=reverse)
        return {key: reorder(value[key], reverse) for key in keys}
    if isinstance(value, list):
        return [reorder(item, reverse) for item in value]
    return value


def sample_event(**overrides: Any) -> Event:
    fields: dict[str, Any] = {
        "session_id": "s1",
        "step": 0,
        "type": EventType.SESSION_START,
        "payload": {"metadata": {"app": "demo"}},
        "prev_hash": GENESIS_HASH,
        "timestamp": "2025-01-01T00:00:00+00:00",
        "event_id": "e0",
    }
    fields.update(overrides)
    return build_event(**fields)


# ---------- canonical_json ----------


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, {"d": None, "c": True}]}) == (
        '{"a":[1,{"c":true,"d":null}],"b":1}'
    )


def test_canonical_json_escapes_non_ascii() -> None:
    assert canonical_json({"k": "é"}) == '{"k":"\\u00e9"}'


@pytest.mark.parametrize(
    "bad",
    [
        (1, 2),
        {1, 2},
        b"bytes",
        datetime(2025, 1, 1, tzinfo=UTC),
        object(),
        math.nan,
        math.inf,
        {1: "int key"},
        {"nested": [{"deep": (1,)}]},
    ],
)
def test_canonical_json_rejects_non_json(bad: object) -> None:
    with pytest.raises(PayloadSerializationError):
        canonical_json(bad)


def test_serialization_error_does_not_leak_values() -> None:
    with pytest.raises(PayloadSerializationError) as info:
        canonical_json({"api_key": ("sk-very-secret",)})
    assert "sk-very-secret" not in str(info.value)


def test_canonical_json_rejects_cycles() -> None:
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    with pytest.raises(PayloadSerializationError):
        canonical_json(cyclic)


@given(json_values)
def test_canonical_json_stable_across_key_order(value: JSONValue) -> None:
    assert canonical_json(reorder(value, False)) == canonical_json(reorder(value, True))


# ---------- fingerprints ----------


def test_fingerprint_is_stable_and_key_order_independent() -> None:
    assert request_fingerprint("search", {"q": "cats", "n": 2}) == request_fingerprint(
        "search", {"n": 2, "q": "cats"}
    )


def test_fingerprint_depends_on_name_and_args() -> None:
    base = request_fingerprint("search", {"q": "cats"})
    assert base != request_fingerprint("search", {"q": "dogs"})
    assert base != request_fingerprint("lookup", {"q": "cats"})
    assert len(base) == 64


# ---------- event model and hashing ----------


def test_genesis_hash_constant() -> None:
    assert GENESIS_HASH == "0" * 64


def test_build_event_hash_matches_formula() -> None:
    event = sample_event()
    assert event.hash == compute_hash(GENESIS_HASH, event.hash_body())
    assert event.hash == event.computed_hash()
    assert "hash" not in event.hash_body()


def test_hash_is_deterministic() -> None:
    assert sample_event().hash == sample_event().hash


def test_event_is_frozen_and_rejects_extra_fields() -> None:
    event = sample_event()
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        event.step = 5  # type: ignore[misc]
    with pytest.raises(Exception):  # noqa: B017
        Event(**{**event.model_dump(), "extra_field": 1})


def test_event_payload_is_copied_from_caller() -> None:
    payload: dict[str, JSONValue] = {"metadata": {"app": "demo"}}
    event = sample_event(payload=payload)
    payload["metadata"] = "changed"
    assert event.payload == {"metadata": {"app": "demo"}}


def test_event_rejects_non_json_payload() -> None:
    with pytest.raises(PayloadSerializationError):
        sample_event(payload={"result": (1, 2)})


def test_event_type_round_trips_from_string() -> None:
    event = sample_event()
    restored = Event(**{**event.model_dump(), "type": "session_start"})
    assert restored == event


MUTATIONS: dict[str, Any] = {
    "event_id": "other",
    "session_id": "s2",
    "step": 1,
    "type": EventType.FINAL_ANSWER,
    "payload": {"metadata": {"app": "evil"}},
    "timestamp": "2030-01-01T00:00:00+00:00",
    "parent_step": 0,
    "prev_hash": "f" * 64,
}


@pytest.mark.parametrize("field", sorted(MUTATIONS))
def test_any_field_change_changes_hash(field: str) -> None:
    event = sample_event()
    mutated = event.model_copy(update={field: MUTATIONS[field]})
    assert mutated.computed_hash() != event.hash


@given(json_objects, json_objects)
def test_payload_change_changes_hash(a: dict[str, JSONValue], b: dict[str, JSONValue]) -> None:
    same = canonical_json(a) == canonical_json(b)
    assert (sample_event(payload=a).hash == sample_event(payload=b).hash) == same


# ---------- redaction ----------


def test_default_redactor_masks_nested_and_mixed_case_keys() -> None:
    value: JSONValue = {
        "query": "cats",
        "API_KEY": "sk-1",
        "headers": {"Authorization": "Bearer x", "Cookie": "sid=1", "Accept": "json"},
        "items": [{"Password": "p"}, {"keep": "ok", "PRIVATE_KEY": "k"}, "token"],
        "Bearer": "b",
        "deep": {"a": {"b": {"Secret": "s", "ToKeN": "t"}}},
    }
    assert default_redactor(value) == {
        "query": "cats",
        "API_KEY": REDACTED,
        "headers": {"Authorization": REDACTED, "Cookie": REDACTED, "Accept": "json"},
        "items": [{"Password": REDACTED}, {"keep": "ok", "PRIVATE_KEY": REDACTED}, "token"],
        "Bearer": REDACTED,
        "deep": {"a": {"b": {"Secret": REDACTED, "ToKeN": REDACTED}}},
    }


def test_default_redactor_masks_whole_subtree_under_sensitive_key() -> None:
    assert default_redactor({"secret": {"nested": [1, 2]}}) == {"secret": REDACTED}


def test_default_redactor_does_not_mutate_input() -> None:
    value: dict[str, JSONValue] = {"token": "t", "inner": {"password": "p"}}
    default_redactor(value)
    assert value == {"token": "t", "inner": {"password": "p"}}


@given(json_values)
def test_default_redactor_output_has_no_sensitive_values(value: JSONValue) -> None:
    def check(node: JSONValue) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key.lower() in {"token", "password", "api_key", "secret"}:
                    assert item == REDACTED
                check(item)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(default_redactor(value))
