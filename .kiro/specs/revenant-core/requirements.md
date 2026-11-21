# Requirements Document

## Introduction

Revenant is a record-and-replay core library for AI agent sessions. It is domain-independent. "Deterministic" means replaying recorded outputs, never re-running a model.

### Glossary

- **Session**: ordered list of events sharing a `session_id`.
- **Step**: zero-based, monotonic index of an event within a session.
- **Recorder**: object that wraps functions and runs in `record`, `replay` or `fork` mode.
- **Real function**: the user-supplied function wrapped by `wrap_llm` or `wrap_tool`.

## Requirements

### Requirement 1: Events

**User Story:** As a library user, I want a typed, tamper-evident event log, so that sessions can be stored, verified and compared.

#### Acceptance Criteria

1. THE system SHALL define event types `session_start`, `llm_call`, `tool_call`, `tool_result`, `error`, `nondeterminism`, `final_answer`.
2. EVERY event SHALL have `event_id`, `session_id`, `step`, `type`, `payload`, `timestamp`, `parent_step` (nullable), `prev_hash`, `hash`.
3. WHEN events are appended to a session, THE `step` values SHALL start at 0 and increase by exactly 1.
4. THE `hash` SHALL be `sha256(prev_hash + canonical_json(event without hash))`, hex-encoded.
5. THE first event of a session SHALL use `prev_hash = GENESIS_HASH`, a single module-level constant defined once.
6. THE system SHALL provide exactly one `canonical_json()` function, used for all serialization and hashing.
7. THE system SHALL provide `request_fingerprint(name, args)` returning a stable string for call matching.
8. WHEN dicts differ only in key order, THE `canonical_json()` output SHALL be identical.

### Requirement 2: Store

**User Story:** As a library user, I want an append-only durable store, so that recorded history cannot be silently changed.

#### Acceptance Criteria

1. THE store SHALL be a `Protocol` with `create_session`, `append_event`, `load_session`, `list_sessions`, `verify_chain(session_id) -> bool`.
2. THE SQLite implementation SHALL use WAL journal mode.
3. WHEN an event is appended, THE store SHALL do it in one transaction.
4. THE store SHALL have an index on `(session_id, step)`.
5. THE store SHALL NOT issue `UPDATE` or `DELETE` on stored events.
6. IF an appended event's `step` or `prev_hash` does not continue the chain, THEN THE store SHALL raise `ChainIntegrityError`.
7. WHEN a stored event was modified outside the API, THEN `verify_chain` SHALL return `False`.
8. IF a session does not exist, THEN `load_session` SHALL raise `SessionNotFoundError`.

### Requirement 3: Recorder

**User Story:** As a library user, I want to wrap my LLM and tool functions, so that calls are recorded and later replayed without side effects.

#### Acceptance Criteria

1. THE recorder SHALL support modes `record`, `replay` and `fork(at_step, override=...)`. The override is a single optional value (a mapping of overrides is out of scope).
2. THE `wrap_llm` and `wrap_tool` SHALL support sync and async functions and preserve signatures (sync stays sync, async stays async, `functools.wraps`, type-preserving).
3. WHEN in record mode, THE recorder SHALL call the real function and persist the call and its result as events.
4. WHEN a real function raises, THE recorder SHALL record an `error` event and re-raise the original exception.
5. WHEN replaying a recorded error, THE recorder SHALL raise the same exception type with the same message, without calling the real function.
6. THE recorder SHALL provide `now()`, `uuid4()`, `random()`: recorded as `nondeterminism` events in record mode, returned from the recording in replay mode.
7. THE recorder SHALL apply a redaction hook to payloads before persisting. IF the hook raises, THEN the append SHALL fail with a typed exception and nothing SHALL be stored.
8. THE default redaction hook SHALL recursively mask the values of keys `api_key`, `password`, `token`, `secret`, `authorization`, `cookie`, `bearer`, `private_key` with `"[REDACTED]"`. Key matching SHALL be case-insensitive and apply at any nesting depth, including dicts inside lists.
9. THE `request_fingerprint` SHALL be computed on post-redaction arguments, identically in record and replay.
10. THE recorder SHALL support sequential wrapped calls only. IF a wrapped call starts while another wrapped call on the same recorder is still in progress, THEN THE recorder SHALL raise `ConcurrentCallError`. This is a documented v1 limitation.
11. IF a call's arguments or result cannot be canonically serialized to JSON, THEN THE recorder SHALL raise `PayloadSerializationError`, SHALL NOT store any lossy version, and SHALL store neither the call event nor a result event for that call. A call's events are written only after the real function returns, so a non-JSON result leaves the session with no event for that call. The recorder then refuses further calls, because the call did happen.
12. THE recorder SHALL provide `close()` and SHALL be usable as a context manager. WHEN `close()` runs in replay or fork mode, THE recorder SHALL perform the unconsumed-events check (R4.5).
13. THE replay SHALL return plain JSON values (dicts, lists, strings, numbers, booleans, null), not the original object types.
14. THE recorder SHALL apply the redactor to exception messages and exception args before storing an `error` event. The default redactor SHALL mask secrets in free text written as `key=value`, `key: value`, JSON-style `"key": "value"`, or `Bearer <token>`. The exception the caller receives SHALL keep its original message.
15. A wrapped call SHALL be recorded only when it completes. A call interrupted by a `BaseException` (such as `KeyboardInterrupt` or task cancellation) SHALL leave no event, and the recorder SHALL remain usable.

### Requirement 4: Replay

**User Story:** As a library user, I want strict replay, so that any difference from the recording is detected instead of guessed.

#### Acceptance Criteria

1. THE replay SHALL read a cursor over recorded events in step order.
2. THE replay SHALL NEVER call the real function.
3. IF the call name or `request_fingerprint` differs from the next recorded call, THEN THE replay SHALL raise `DivergenceError(step, expected, actual, reason)`.
4. IF no recorded events remain when one is needed, THEN THE replay SHALL raise `ReplayExhaustedError`.
5. WHEN the recorder closes with unconsumed events, THE recorder SHALL emit `UnconsumedEventsWarning` carrying the count.
6. WHEN replay starts, THE recorder SHALL verify the chain and raise `ChainIntegrityError` on failure.

### Requirement 5: Fork

**User Story:** As a library user, I want to branch a recorded session at a step, so that I can explore an alternative without losing the original.

#### Acceptance Criteria

1. `at_step` SHALL be the step of an `llm_call` or `tool_call` event. WHEN a fork starts, THE recorder SHALL replay recorded events before `at_step`, then continue live from that call.
2. THE fork SHALL create a NEW session linked to its parent via `parent_session_id` and `parent_step`.
3. WHERE an override is given, THE call event at `at_step` SHALL still be recorded in the child, only its result SHALL be replaced by the override, and the real function SHALL NOT be called for that call.
4. THE parent session SHALL remain unchanged.
5. IF `at_step` is outside the parent session or is not a call event, THEN THE recorder SHALL raise `InvalidForkPointError`.
6. THE child session SHALL copy the replayed prefix (events before `at_step`) so that its hash chain verifies on its own.

### Requirement 6: Diff

**User Story:** As a library user, I want a structured comparison of two sessions, so that tools can inspect the differences as data.

#### Acceptance Criteria

1. `diff_sessions(a, b)` SHALL return a `TraceDiff` data object, not a printed string.
2. THE `TraceDiff` SHALL contain the first divergent step (or none), the divergence kind, and all differing steps.
3. THE divergence kind SHALL be one of: different tool, args, result, length.
4. WHEN two sessions have equal content, THE result SHALL report no divergence. `event_id`, `session_id`, `timestamp` and hashes SHALL be ignored.

### Requirement 7: Errors

**User Story:** As a library user, I want typed exceptions, so that failures are explicit and can be handled precisely.

#### Acceptance Criteria

1. THE system SHALL define `RevenantError` as base class.
2. `DivergenceError`, `ReplayExhaustedError`, `ChainIntegrityError`, `SessionNotFoundError`, `InvalidForkPointError`, `ConcurrentCallError`, `PayloadSerializationError` SHALL subclass it.
3. `DivergenceError` SHALL expose `step`, `expected`, `actual`, `reason`.
4. `UnconsumedEventsWarning` SHALL be a `Warning` subclass exposing `count`.

## Required tests

Setup: scripted fake LLM (canned responses by call index), 2-3 plain tool functions, a driver fixture (not an agent). Assertions use call counters.

1. Record then replay: identical outputs, real-call counter 0.
2. Sync and async tools both replay.
3. Raised exception recorded and re-raised identically.
4. Changed arguments raise `DivergenceError` at the right step.
5. Replay past the end raises `ReplayExhaustedError`.
6. Editing a stored event makes `verify_chain` fail.
7. Fork at step N: earlier replayed, later live, child linked, override applied.
8. `diff_sessions` gives the correct first divergent step per divergence kind.
9. `now()`, `uuid4()`, `random()` identical across record and replay.
10. Redaction masks nested and mixed-case keys (including `Cookie`, `Bearer`, `PRIVATE_KEY`, dicts inside lists).
11. Overlapping wrapped calls raise `ConcurrentCallError`; a non-serializable payload raises `PayloadSerializationError` and stores nothing; fingerprints match across record and replay after redaction; `close()` and the context manager emit `UnconsumedEventsWarning`; replay returns plain JSON values.
12. Hypothesis: record/replay identical with zero real calls for any call sequence; `canonical_json` stable across key order; any single-field mutation breaks the chain.

## Non-goals

Agents, framework adapters (LangGraph, MCP), UI, FastAPI, Postgres, auth, LLM-based analysis, pytest export, CLI.

## Decisions (approved)

- Single optional `override` for fork; mapping out of scope.
- `at_step` is the step of the call event; the call event is recorded, only its result is replaced.
- Child copies the replayed prefix.
- Hash formula as in R1.4; genesis is one constant.
- Hook globs: `revenant-core/src/**/*.py`, `revenant-core/tests/**/*.py`.
- Default redaction as in R3.8, plus a test with nested and mixed-case keys.
