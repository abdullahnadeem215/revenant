"""Append-only trace store: TraceStore Protocol and SQLite implementation.

This module never issues UPDATE or DELETE statements against stored events.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from revenant.errors import ChainIntegrityError, RevenantError, SessionNotFoundError
from revenant.events import GENESIS_HASH, Event, canonical_json, utc_timestamp

__all__ = ["SQLiteTraceStore", "SessionInfo", "TraceStore"]


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    created_at: str
    parent_session_id: str | None
    parent_step: int | None


@runtime_checkable
class TraceStore(Protocol):
    """Storage contract used by the recorder. Implementations must be append-only.

    create_session writes only the session row. It writes no event. The recorder
    appends session_start as the first event. Fork children copy the parent's
    session_start (step 0) along with the rest of the replayed prefix, so the store
    must not add a second one.

    A session with zero events is valid: load_session returns [] and verify_chain
    returns True. The first append must be step 0 with prev_hash GENESIS_HASH.
    """

    def create_session(
        self,
        session_id: str,
        *,
        parent_session_id: str | None = None,
        parent_step: int | None = None,
    ) -> None:
        """Create an empty session. parent_session_id and parent_step must be given together."""
        ...

    def append_event(self, event: Event) -> None:
        """Append one event at the end of its session's chain, or raise ChainIntegrityError."""
        ...

    def load_session(self, session_id: str) -> list[Event]:
        """Return all events of a session in step order. Raises SessionNotFoundError."""
        ...

    def list_sessions(self) -> list[SessionInfo]:
        """Return every session, including its parent link."""
        ...

    def verify_chain(self, session_id: str) -> bool:
        """Recompute every hash from stored content. False on any gap or mismatch."""
        ...


_SESSIONS_DDL = (
    "CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, "
    "created_at TEXT NOT NULL, parent_session_id TEXT, parent_step INTEGER)"
)

_EVENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, "
    "session_id TEXT NOT NULL REFERENCES sessions(session_id), "
    "step INTEGER NOT NULL, type TEXT NOT NULL, payload_json TEXT NOT NULL, "
    "timestamp TEXT NOT NULL, parent_step INTEGER, prev_hash TEXT NOT NULL, "
    "hash TEXT NOT NULL, UNIQUE(session_id, step))"
)
_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_events_session_step ON events(session_id, step)"

_INSERT_EVENT = (
    "INSERT INTO events (event_id, session_id, step, type, payload_json, timestamp, "
    "parent_step, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_SELECT_EVENTS = (
    "SELECT event_id, session_id, step, type, payload_json, timestamp, parent_step, "
    "prev_hash, hash FROM events WHERE session_id = ? ORDER BY step"
)


def _row_to_event(row: sqlite3.Row) -> Event:
    fields = dict(row)
    fields["payload"] = json.loads(fields.pop("payload_json"))
    return Event(**fields)


class SQLiteTraceStore:
    """Append-only SQLite store in WAL mode. Satisfies TraceStore."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        synchronous: Literal["FULL", "NORMAL"] = "FULL",
    ) -> None:
        """Open or create a store. synchronous=FULL (default) makes every append durable;
        NORMAL is faster and still corruption-safe in WAL mode, but the last appends can be
        lost on power failure."""
        if synchronous not in ("FULL", "NORMAL"):
            raise RevenantError(f"unsupported synchronous mode {synchronous!r}")
        self._conn = sqlite3.connect(os.fspath(path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA synchronous={synchronous}")
        mode = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            self._conn.close()
            raise RevenantError(f"could not enable WAL journal mode (got {mode!r})")
        for ddl in (_SESSIONS_DDL, _EVENTS_DDL, _INDEX_DDL):
            self._conn.execute(ddl)

    def close(self) -> None:
        self._conn.close()

    def create_session(
        self,
        session_id: str,
        *,
        parent_session_id: str | None = None,
        parent_step: int | None = None,
    ) -> None:
        """Insert the session row only. No event is written (see TraceStore)."""
        if not session_id:
            raise RevenantError("session_id must be a non-empty string")
        if (parent_session_id is None) != (parent_step is None):
            raise RevenantError("parent_session_id and parent_step must be given together")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if parent_session_id is not None and not self._exists(parent_session_id):
                raise SessionNotFoundError(parent_session_id)
            self._conn.execute(
                "INSERT INTO sessions (session_id, created_at, parent_session_id, parent_step)"
                " VALUES (?, ?, ?, ?)",
                (session_id, utc_timestamp(), parent_session_id, parent_step),
            )
            self._conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            self._conn.execute("ROLLBACK")
            raise RevenantError(f"session {session_id!r} already exists") from exc
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def append_event(self, event: Event) -> None:
        """Append one event in a single transaction, enforcing the hash chain."""
        if event.hash != event.computed_hash():
            raise ChainIntegrityError(f"event at step {event.step} has an incorrect hash")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if not self._exists(event.session_id):
                raise SessionNotFoundError(event.session_id)
            last = self._conn.execute(
                "SELECT step, hash FROM events WHERE session_id = ? ORDER BY step DESC LIMIT 1",
                (event.session_id,),
            ).fetchone()
            expected_step = 0 if last is None else last["step"] + 1
            expected_prev = GENESIS_HASH if last is None else last["hash"]
            if event.step != expected_step:
                raise ChainIntegrityError(f"expected step {expected_step}, got {event.step}")
            if event.prev_hash != expected_prev:
                raise ChainIntegrityError(
                    f"prev_hash does not continue the chain at step {event.step}"
                )
            self._conn.execute(_INSERT_EVENT, self._event_row(event))
            self._conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            self._conn.execute("ROLLBACK")
            raise ChainIntegrityError(
                f"event {event.event_id!r} conflicts with stored data"
            ) from exc
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def load_session(self, session_id: str) -> list[Event]:
        if not self._exists(session_id):
            raise SessionNotFoundError(session_id)
        rows = self._conn.execute(_SELECT_EVENTS, (session_id,)).fetchall()
        return [_row_to_event(row) for row in rows]

    def list_sessions(self) -> list[SessionInfo]:
        rows = self._conn.execute(
            "SELECT session_id, created_at, parent_session_id, parent_step"
            " FROM sessions ORDER BY created_at, session_id"
        ).fetchall()
        return [SessionInfo(**dict(row)) for row in rows]

    def verify_chain(self, session_id: str) -> bool:
        """Recompute every hash from stored content. False on any mismatch or gap.

        A session with zero events returns True: there is nothing to break.
        """
        if not self._exists(session_id):
            raise SessionNotFoundError(session_id)
        rows = self._conn.execute(_SELECT_EVENTS, (session_id,)).fetchall()
        prev_hash = GENESIS_HASH
        for expected_step, row in enumerate(rows):
            if row["step"] != expected_step or row["prev_hash"] != prev_hash:
                return False
            try:
                event = _row_to_event(row)
            except (ValueError, TypeError, RevenantError):
                return False
            if event.computed_hash() != row["hash"]:
                return False
            prev_hash = row["hash"]
        return True

    def _exists(self, session_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _event_row(event: Event) -> tuple[str, str, int, str, str, str, int | None, str, str]:
        return (
            event.event_id,
            event.session_id,
            event.step,
            event.type.value,
            canonical_json(event.payload),
            event.timestamp,
            event.parent_step,
            event.prev_hash,
            event.hash,
        )
