# Implementation Plan

Each phase ends with a checkpoint. A checkpoint runs, from `revenant-core/`:

- `python -m pytest -q`
- `python -m mypy --strict src tests`
- `python -m ruff check src tests` and `python -m ruff format --check src tests`
- the Hypothesis tests 20 times in a row: `1..20 | % { python -m pytest -q -m hypothesis -p no:cacheprovider; if ($LASTEXITCODE) { throw "run $_ failed" } }`. Hypothesis is not derandomized, so each run uses a new seed.

After every checkpoint, the real output is shown, followed by a 5-line summary, and work stops until you say "continue".

Test numbers below follow `requirements.md` (Required tests 1-12).

## Phase 1: events and errors

- [x] 1. Set up the project and implement `errors.py` and `events.py`
- [x] 1.1 Create the project skeleton
  - `revenant-core/pyproject.toml`: Python >= 3.11, dependency `pydantic>=2`, dev extras `pytest`, `pytest-asyncio`, `hypothesis`, `mypy`, `ruff`
  - Configure mypy `strict = true`, ruff rules (`E`, `F`, `I`, `B`, `UP`, `ANN`, `S`, `RUF`), pytest `asyncio_mode = "strict"` and a `hypothesis` marker
  - `src/revenant/__init__.py` with public exports, `py.typed`, empty `tests/conftest.py`
  - _Requirements: tech.md, structure.md_
- [x] 1.2 Implement `errors.py`
  - `RevenantError` base. `DivergenceError(step, expected, actual, reason)` with attributes. `ReplayExhaustedError`, `ChainIntegrityError`, `SessionNotFoundError`, `InvalidForkPointError`, `ConcurrentCallError(active, attempted)`, `PayloadSerializationError`
  - `UnconsumedEventsWarning(Warning)` with `count`
  - _Requirements: 7.1, 7.2, 7.3, 7.4_
- [x] 1.3 Implement `canonical_json` and `JSONValue` in `events.py`
  - A strict recursive type check that rejects tuples, sets, bytes, NaN/Infinity, non-str keys and objects with `PayloadSerializationError`
  - `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)`
  - _Requirements: 1.6, 1.8, 3.11_
- [x] 1.4 Implement `EventType`, the `Event` model, `GENESIS_HASH`, `compute_hash`, `request_fingerprint`
  - Frozen Pydantic v2 model with `extra="forbid"` and the fields from design section 2
  - `hash = sha256(prev_hash + canonical_json(body))`, where body is all fields except `hash`
  - A `build_event(...)` helper that fills in `hash`
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 1.7_
- [x] 1.5 Implement `default_redactor`
  - Masks `api_key, password, token, secret, authorization, cookie, bearer, private_key`, case-insensitive, at any depth, including dicts inside lists. Returns a new object.
  - _Requirements: 3.7, 3.8_
- [x] 1.6 Write tests for phase 1
  - `canonical_json`: key order, rejection of each non-JSON type
  - Hash: determinism, genesis, and that a change in any field changes the hash
  - Fingerprint: stable for equal args, different for different args
  - Redaction: nested and mixed-case keys, lists, no mutation (test 10)
  - Hypothesis: `canonical_json` stable across key order (part of test 12)
  - _Requirements: 1.4-1.8, 3.8, 3.11_
- [x] 1.7 Checkpoint: run pytest, mypy --strict, ruff, and Hypothesis 20 times. Show output and stop.

## Phase 2: store

- [x] 2. Implement `store.py`
- [x] 2.1 Define the `TraceStore` Protocol and `SessionInfo`
  - Five methods with the signatures from design section 9
  - _Requirements: 2.1_
- [x] 2.2 Implement `SQLiteTraceStore`
  - `PRAGMA journal_mode=WAL`, tables `sessions` and `events`, `UNIQUE(session_id, step)`, index `idx_events_session_step`
  - `create_session` writes only the session row. The recorder writes `session_start` (deviation from the original wording; see docs/kiro-notes.md)
  - `append_event` uses one `BEGIN IMMEDIATE` transaction and checks step, `prev_hash` and hash, raising `ChainIntegrityError` on failure
  - `load_session` returns events in step order or raises `SessionNotFoundError`. `list_sessions` returns `SessionInfo`. `verify_chain` follows design section 6.
  - Parameterized SQL only. No UPDATE or DELETE in the module.
  - _Requirements: 2.2-2.8_
- [x] 2.3 Write tests for the store
  - Round trip, ordering, and the parent link in `list_sessions`
  - WAL via `PRAGMA journal_mode`, the index via `sqlite_master`, a source scan for `UPDATE`/`DELETE`
  - A bad step or `prev_hash` raises `ChainIntegrityError`. An unknown session raises `SessionNotFoundError`.
  - Test 6: edit a row through a separate raw sqlite3 connection, then `verify_chain` is `False`
  - Hypothesis: any single-field mutation breaks the chain (part of test 12)
  - _Requirements: 2.1-2.8, 1.4_
- [x] 2.4 Checkpoint: run pytest, mypy --strict, ruff, and Hypothesis 20 times. Show output and stop.

## Phase 3: recorder (record mode)

- [x] 3. Implement record mode in `recorder.py`
- [x] 3.1 Implement the recorder core
  - `Recorder.record(store, session_id=None, metadata=None, redactor=default_redactor)` and an internal `_append(type, payload, parent_step)` that redacts, serializes and builds the hashed event
  - A redactor that raises is wrapped in a `RevenantError`, and nothing is appended
  - _Requirements: 3.1, 3.3, 3.7, 3.11_
- [x] 3.2 Implement `wrap_llm` and `wrap_tool` for record mode
  - Sync and async overloads with `ParamSpec` and `functools.wraps`. `inspect.iscoroutinefunction` chooses the wrapper.
  - Bind, redact, fingerprint, write the call event, call the real function, then write `tool_result` or `error` with `parent_step`
  - Re-raise the original exception. Store `exc_type` as `module.qualname`, with `message` and `args`.
  - _Requirements: 3.2, 3.3, 3.4, 3.9_
- [x] 3.3 Implement `now()`, `uuid4()`, `random()`, `final_answer()`, the `_active` guard, `close()` and the context manager
  - Each of the first four writes one event. The guard raises `ConcurrentCallError` on overlap or nesting.
  - _Requirements: 3.6, 3.10, 3.12_
- [x] 3.4 Write tests for record mode
  - Fixtures in `conftest.py`: `ScriptedLLM` (canned responses by call index, with a counter), tools `add` (sync), `lookup` (async) and `fail` (raises `ValueError`), each with a counter. The `driver` fixture runs a fixed call sequence and is not an agent.
  - Event sequence and `parent_step` match design section 3, and the chain verifies
  - Wrapped functions keep `__name__`, `__doc__`, `inspect.signature`, and their sync/async kind
  - Secrets in args are stored as `[REDACTED]`. A non-JSON result raises `PayloadSerializationError` and adds no event. A raising redactor stores nothing.
  - `asyncio.gather` on two wrapped calls raises `ConcurrentCallError`
  - _Requirements: 3.2-3.4, 3.7-3.12_
- [x] 3.5 Checkpoint: run pytest, mypy --strict, ruff, and Hypothesis 20 times. Show output and stop.

## Phase 4: replay

- [x] 4. Implement `replay.py` and replay mode
- [x] 4.1 Implement `ReplayCursor`
  - Built from a `list[Event]`. Provides `take_call`, `take_answer`, `take_nondeterminism`, `take_final_answer` and `remaining`.
  - Raises `DivergenceError` and `ReplayExhaustedError` as in the design section 4 table. The cursor does not advance on error.
  - _Requirements: 4.1, 4.3, 4.4_
- [x] 4.2 Implement `Recorder.replay`
  - Unknown session raises `SessionNotFoundError`. A false `verify_chain` raises `ChainIntegrityError`. The cursor starts after `session_start`.
  - The wrappers never call the real function in replay. They return `payload["result"]` or rebuild and raise the recorded exception. An exception that cannot be rebuilt raises `DivergenceError`.
  - `now/uuid4/random` return the recorded values as `datetime`, `UUID` and `float`
  - `close()` emits `UnconsumedEventsWarning(count)`. After a failure, only `close()` is accepted.
  - _Requirements: 3.5, 3.6, 3.12, 3.13, 4.2, 4.5, 4.6_
- [x] 4.3 Write the replay and divergence tests (`tests/test_replay.py`, `tests/test_invariants.py`)
  - Test 1: record then replay gives identical outputs, and every real-call counter is 0
  - Test 2: the sync `add` and the async `lookup` both replay
  - Test 3: `fail` raises `ValueError` in record, and replay raises `ValueError` with the same message and a counter of 0
  - Test 4: changed args at call 2 raise `DivergenceError` with the expected step, and expected/actual fingerprints differ. A different tool name and an extra call also diverge.
  - Test 5: one extra call past the end raises `ReplayExhaustedError`
  - Test 9: `now()`, `uuid4()` and `random()` are identical across record and replay
  - Test 11: fingerprints match after redaction even when the secret changes. `close()` and `with` emit `UnconsumedEventsWarning` with the right count. Replayed values are plain JSON. A tampered session raises `ChainIntegrityError` when opened.
  - Hypothesis (test 12): for any generated sequence of calls, replay gives identical outputs with zero real calls
  - `tests/test_invariants.py` holds the zero-real-calls and divergence tests that hook (c) runs
  - _Requirements: 3.5, 3.6, 3.9, 3.12, 3.13, 4.1-4.6_
- [x] 4.4 Checkpoint: run pytest, mypy --strict, ruff, and Hypothesis 20 times. Show output and stop.

## Phase 5: fork

- [ ] 5. Implement fork mode
- [ ] 5.1 Implement `Recorder.fork(store, parent_session_id, at_step, *, override=UNSET, session_id=None, redactor=...)`
  - Verify the parent chain and validate `at_step`, raising `InvalidForkPointError`
  - Create the child with `parent_session_id` and `parent_step`, and copy steps `0..at_step-1` with re-hashed chain links
  - Replay the prefix, then match the call at `at_step` against the parent and record it in the child
  - With an override, skip the real call and record `result = override`, `overridden = true`. Without one, call live. After that, everything is live.
  - Parent events after `at_step` do not count as unconsumed
  - _Requirements: 5.1-5.6_
- [ ] 5.2 Write the fork tests (test 7)
  - Use the worked example from design section 5. Counters must be `llm` 0, `search` 0 and `fetch` 1. The child has the parent link, the prefix copy is equal to the parent's prefix in content, the child chain verifies, and the parent is unchanged.
  - Fork without an override calls the real function once at `at_step`. `None` works as an override.
  - A non-call `at_step` and an out-of-range `at_step` raise `InvalidForkPointError`. Changed args at `at_step` raise `DivergenceError`.
  - _Requirements: 5.1-5.6_
- [ ] 5.3 Checkpoint: run pytest, mypy --strict, ruff, and Hypothesis 20 times. Show output and stop.

## Phase 6: diff

- [ ] 6. Implement `diff.py`
- [ ] 6.1 Implement `DivergenceKind`, `StepDiff`, `TraceDiff`, `diff_sessions`
  - A pure function over two `Sequence[Event]` that ignores `event_id`, `session_id`, `timestamp`, `prev_hash` and `hash`
  - Kind rules from design section 9
  - _Requirements: 6.1-6.4_
- [ ] 6.2 Write the diff tests (test 8)
  - Identical sessions give `first_divergent_step=None`. A different tool, different args, a different result and a different length each give the correct first step and kind.
  - Several differences are all listed in `differing_steps`. `TraceDiff` is data, and `dataclasses.asdict` works.
  - A forked child compared with its parent diverges first at the override step, with kind `result`
  - _Requirements: 6.1-6.4_
- [ ] 6.3 Checkpoint: run pytest, mypy --strict, ruff, and Hypothesis 20 times. Show output and stop.

## Phase 7: README

- [ ] 7. Write `revenant-core/README.md`
- [ ] 7.1 Write the README
  - Known limitations, stated plainly: a hash chain cannot detect truncation of the last events, or moving the last event into another session (changing `session_id` on a middle row is detected). The head hash must be anchored elsewhere if this matters.
  - Exception text is redacted only by the default hook, and only for the `key=value`, `key: value`, JSON-style and `Bearer <token>` forms. A custom redactor replaces that behavior.
  - `redact_text` is pattern-based and best-effort. It is not a guarantee that no secret is stored. A secret written in any other form passes through unchanged. The default hook may also over-redact text that merely looks like `key: value`, for example `token: refresh needed` becomes `token: [REDACTED] needed`.
  - A call is recorded only when it completes. A call interrupted by a `BaseException` leaves no event. A call whose result is not JSON leaves no event, and the recorder then refuses further calls.
  - Default names are the function's `__qualname__` (for example `RealTools.add`) unless `name=` is given.
  - What Revenant core is, and what "deterministic" means here
  - A record and replay usage example under 20 lines
  - Short sections on fork, diff, redaction, and the limitations from design section 10 (unwrapped nondeterminism, side effects in fork, plain JSON, sequential only)
  - _Requirements: product.md_
- [ ] 7.2 Add a test that extracts the README example and runs it
  - The test checks that the example is under 20 lines and that its replay real-call counter is 0
- [ ] 7.3 Final checkpoint: run pytest, mypy --strict, ruff, and Hypothesis 20 times. Check the codebase for network or model calls (no `socket`, `urllib`, `http`, `requests` or LLM SDK imports). Show output and stop.
