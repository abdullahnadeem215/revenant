from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

import revenant.store
from revenant.errors import ChainIntegrityError, RevenantError, SessionNotFoundError
from revenant.events import GENESIS_HASH, Event, EventType, JSONValue, build_event
from revenant.store import SessionInfo, SQLiteTraceStore, TraceStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "trace.db"


@pytest.fixture
def store(db_path: Path) -> Iterator[SQLiteTraceStore]:
    s = SQLiteTraceStore(db_path)
    yield s
    s.close()


def append(store: SQLiteTraceStore, session_id: str, payload: dict[str, JSONValue]) -> Event:
    """Append the next event of a session, continuing its chain."""
    events = store.load_session(session_id)
    prev = events[-1].hash if events else GENESIS_HASH
    event = build_event(
        session_id=session_id,
        step=len(events),
        type=EventType.SESSION_START if not events else EventType.FINAL_ANSWER,
        payload=payload,
        prev_hash=prev,
    )
    store.append_event(event)
    return event


def make_session(store: SQLiteTraceStore, session_id: str = "s1", n: int = 4) -> list[Event]:
    store.create_session(session_id)
    return [append(store, session_id, {"value": i}) for i in range(n)]


def test_sqlite_store_satisfies_protocol(store: SQLiteTraceStore) -> None:
    assert isinstance(store, TraceStore)


def test_round_trip_and_order(store: SQLiteTraceStore) -> None:
    written = make_session(store)
    assert store.load_session("s1") == written
    assert [e.step for e in written] == [0, 1, 2, 3]


def test_persists_across_connections(db_path: Path) -> None:
    first = SQLiteTraceStore(db_path)
    written = make_session(first)
    first.close()
    second = SQLiteTraceStore(db_path)
    assert second.load_session("s1") == written
    assert second.verify_chain("s1")
    second.close()


def test_list_sessions_includes_parent_link(store: SQLiteTraceStore) -> None:
    make_session(store, "parent")
    store.create_session("child", parent_session_id="parent", parent_step=1)
    infos = {info.session_id: info for info in store.list_sessions()}
    assert infos["parent"].parent_session_id is None
    assert infos["child"] == SessionInfo(
        session_id="child",
        created_at=infos["child"].created_at,
        parent_session_id="parent",
        parent_step=1,
    )


def test_wal_mode_and_index(store: SQLiteTraceStore, db_path: Path) -> None:
    raw = sqlite3.connect(db_path)
    try:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        index = raw.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_events_session_step'"
        ).fetchone()
        assert index is not None
        assert "(session_id, step)" in index[0]
    finally:
        raw.close()


def test_store_module_has_no_update_or_delete() -> None:
    source = Path(revenant.store.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', "", source)  # ignore docstrings
    assert not re.search(r"\b(UPDATE|DELETE)\b", code, flags=re.IGNORECASE)


def test_wrong_step_is_rejected(store: SQLiteTraceStore) -> None:
    events = make_session(store, n=2)
    bad = build_event(
        session_id="s1",
        step=5,
        type=EventType.FINAL_ANSWER,
        payload={},
        prev_hash=events[-1].hash,
    )
    with pytest.raises(ChainIntegrityError):
        store.append_event(bad)
    assert len(store.load_session("s1")) == 2


def test_wrong_prev_hash_is_rejected(store: SQLiteTraceStore) -> None:
    make_session(store, n=2)
    bad = build_event(
        session_id="s1", step=2, type=EventType.FINAL_ANSWER, payload={}, prev_hash="f" * 64
    )
    with pytest.raises(ChainIntegrityError):
        store.append_event(bad)
    assert len(store.load_session("s1")) == 2


def test_first_event_must_use_genesis(store: SQLiteTraceStore) -> None:
    store.create_session("s1")
    bad = build_event(
        session_id="s1", step=0, type=EventType.SESSION_START, payload={}, prev_hash="a" * 64
    )
    with pytest.raises(ChainIntegrityError):
        store.append_event(bad)


def test_event_with_forged_hash_is_rejected(store: SQLiteTraceStore) -> None:
    store.create_session("s1")
    event = build_event(
        session_id="s1", step=0, type=EventType.SESSION_START, payload={}, prev_hash=GENESIS_HASH
    )
    with pytest.raises(ChainIntegrityError):
        store.append_event(event.model_copy(update={"hash": "0" * 64}))


def test_unknown_session_raises(store: SQLiteTraceStore) -> None:
    with pytest.raises(SessionNotFoundError):
        store.load_session("missing")
    with pytest.raises(SessionNotFoundError):
        store.verify_chain("missing")
    event = build_event(
        session_id="missing",
        step=0,
        type=EventType.SESSION_START,
        payload={},
        prev_hash=GENESIS_HASH,
    )
    with pytest.raises(SessionNotFoundError):
        store.append_event(event)


def test_duplicate_session_and_bad_parent(store: SQLiteTraceStore) -> None:
    store.create_session("s1")
    with pytest.raises(RevenantError):
        store.create_session("s1")
    with pytest.raises(SessionNotFoundError):
        store.create_session("c", parent_session_id="nope", parent_step=0)
    with pytest.raises(RevenantError):
        store.create_session("c", parent_session_id="s1")


TAMPERS: dict[str, tuple[str, object]] = {
    "payload": ("payload_json", '{"value":999}'),
    "timestamp": ("timestamp", "2030-01-01T00:00:00+00:00"),
    "type": ("type", "error"),
    "event_id": ("event_id", "forged"),
    "parent_step": ("parent_step", 0),
    "prev_hash": ("prev_hash", "e" * 64),
    "hash": ("hash", "d" * 64),
    "step": ("step", 99),
    "bad_json": ("payload_json", "{not json"),
}


def tamper(db_path: Path, column: str, value: object, step: int) -> None:
    """Edit a stored row behind the store's back, as an attacker would."""
    raw = sqlite3.connect(db_path)
    try:
        raw.execute(
            f"UPDATE events SET {column} = ? WHERE session_id = 's1' AND step = ?",  # noqa: S608
            (value, step),
        )
        raw.commit()
    finally:
        raw.close()


@pytest.mark.parametrize("name", sorted(TAMPERS))
def test_editing_a_stored_event_breaks_verify_chain(
    store: SQLiteTraceStore, db_path: Path, name: str
) -> None:
    make_session(store)
    assert store.verify_chain("s1")
    column, value = TAMPERS[name]
    tamper(db_path, column, value, step=2)
    assert store.verify_chain("s1") is False


MUTATION_STRATEGIES: dict[str, st.SearchStrategy[object]] = {
    "event_id": st.text(min_size=1, max_size=10),
    "step": st.integers(min_value=-5, max_value=50),
    "type": st.sampled_from([t.value for t in EventType]) | st.text(max_size=8),
    "payload_json": st.dictionaries(st.text(max_size=4), st.integers(), max_size=3).map(
        lambda d: json.dumps(d, sort_keys=True, separators=(",", ":"))
    ),
    "timestamp": st.text(max_size=30),
    "parent_step": st.none() | st.integers(min_value=0, max_value=50),
    "prev_hash": st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
    "hash": st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
}
# session_id is excluded: moving the LAST row to another session is a tail truncation,
# which a hash chain cannot detect (documented limitation).
MUTABLE_FIELDS = sorted(MUTATION_STRATEGIES)


@pytest.mark.hypothesis
def test_any_single_field_mutation_breaks_chain() -> None:
    """Hypothesis property. One DB per test run; each example uses a fresh session id."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trace.db"
        store = SQLiteTraceStore(path, synchronous="NORMAL")
        raw = sqlite3.connect(path)
        counter = iter(range(10**9))

        @settings(max_examples=100)
        @given(data=st.data(), length=st.integers(min_value=1, max_value=5))
        def check(data: st.DataObject, length: int) -> None:
            sid = f"s{next(counter)}"
            make_session(store, sid, n=length)
            assert store.verify_chain(sid)
            step = data.draw(st.integers(min_value=0, max_value=length - 1), label="step")
            field = data.draw(st.sampled_from(MUTABLE_FIELDS), label="field")
            where = "WHERE session_id = ? AND step = ?"
            original = raw.execute(
                f"SELECT {field} FROM events {where}",  # noqa: S608
                (sid, step),
            ).fetchone()[0]
            value = data.draw(MUTATION_STRATEGIES[field], label="value")
            assume(value != original)
            try:
                raw.execute(f"UPDATE events SET {field} = ? {where}", (value, sid, step))  # noqa: S608
                raw.commit()
            except sqlite3.IntegrityError:
                raw.rollback()
                assume(False)
            assert store.verify_chain(sid) is False

        try:
            check()
        finally:
            raw.close()
            store.close()


def test_synchronous_mode_is_validated(db_path: Path) -> None:
    with pytest.raises(RevenantError):
        SQLiteTraceStore(db_path, synchronous="OFF")  # type: ignore[arg-type]


# ---------- zero-event sessions ----------


def test_empty_session_is_valid(store: SQLiteTraceStore) -> None:
    store.create_session("empty")
    assert store.load_session("empty") == []
    assert store.verify_chain("empty") is True
    assert "empty" in {info.session_id for info in store.list_sessions()}


def test_first_append_must_be_step_zero(store: SQLiteTraceStore) -> None:
    store.create_session("empty")
    late = build_event(
        session_id="empty", step=1, type=EventType.SESSION_START, payload={}, prev_hash=GENESIS_HASH
    )
    with pytest.raises(ChainIntegrityError):
        store.append_event(late)
    assert store.load_session("empty") == []


def test_first_append_at_genesis_is_accepted(store: SQLiteTraceStore) -> None:
    store.create_session("empty")
    first = build_event(
        session_id="empty", step=0, type=EventType.SESSION_START, payload={}, prev_hash=GENESIS_HASH
    )
    store.append_event(first)
    assert store.load_session("empty") == [first]
    assert store.verify_chain("empty") is True


# ---------- session_id changed on a stored row ----------


def test_changing_session_id_on_a_middle_row_breaks_chain(
    store: SQLiteTraceStore, db_path: Path
) -> None:
    make_session(store, "s1", n=4)
    store.create_session("other")
    assert store.verify_chain("s1")
    tamper(db_path, "session_id", "other", step=1)
    assert store.verify_chain("s1") is False
    assert store.verify_chain("other") is False
