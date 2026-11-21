# Kiro build notes

Real findings from building Revenant with Kiro. Each entry is dated by phase.

## Phase 1: events and errors

- Commit: Phase 1 and Phase 2 share commit e0b2f2a. Phase 1 was never committed on its own,
  so its files went into the Phase 2 commit.
- Setup: system Python is 3.12.5. The project requires 3.11+, so 3.12 is used locally.
- pytest-asyncio 1.x warns when `asyncio_default_fixture_loop_scope` is unset. With
  `filterwarnings = ["error"]` that warning becomes an internal error, so the option is set
  to `function` in `pyproject.toml`.
- `pyproject.toml` referenced `README.md` before it existed. The build failed, so `readme`
  was removed. It goes back in Phase 7.
- ruff flagged `Any` in `DivergenceError` (ANN401) and an unsorted union (RUF036). Both
  were fixed in code, not suppressed.
- Hook helper check: `revenant_checks.py lint` and `related` both ran successfully from the
  command line. I have not confirmed that Kiro itself fires the hooks on a save.

## Phase 2: SQLite trace store

### Stalled file writes

- Several large single writes (roughly 100+ lines) to `store.py` and `design.md` were
  aborted or never reached disk. The tool reported the call as cancelled or aborted, and
  nothing was running in the background (checked with `list_processes`).
- Workaround: write files in chunks of about 100 lines or fewer, using `fs_write` for the
  first chunk and appending the rest. Verify the line count after each chunk.
- Earlier, I also wrote temporary `design.part*` files and merged them. That was a mistake:
  it left stray files and confused the review. Use one target file per document.

### create_session deviation

- The original task 2.2 said `create_session` writes the session row and the `session_start`
  event in one transaction.
- Implemented behavior: `create_session` writes only the `sessions` row. The recorder
  appends `session_start` as step 0.
- Reason: a fork child copies the parent's replayed prefix, which includes the parent's
  `session_start` at step 0. If `create_session` also wrote one, the child would have two
  start events.
- Consequence: a session with zero events is valid. `verify_chain` returns `True`, and the
  first append must be step 0 with `GENESIS_HASH`.

### Durability cost

- Measured on this machine: `synchronous=FULL` costs about 32 ms per append. `NORMAL` costs
  about 0.34 ms.
- The default stays `FULL`, so durability is the default. Only the Hypothesis mutation test
  (`test_any_single_field_mutation_breaks_chain`) uses `NORMAL`, to keep it fast.

### Test runs that stalled

- A full `pytest` run stopped after `test_errors.py` and never finished. Leftover `pytest`
  and `mypy` processes from earlier runs were still alive. I stopped them, and each test file
  then passed on its own, as did the full suite (73 passed).
- Lesson: check for leftover processes (`Get-CimInstance Win32_Process`) before blaming the
  tests. Long multi-line PowerShell loops also got cut off by the shell, so run Hypothesis
  batches of about five runs at a time.
- Debug output files (`out_*.txt`, `err_*.txt`) were written to the workspace root by
  mistake. They were removed before the commit.

### Known limitations found while testing

- A hash chain cannot detect truncation of the last events, or moving the last event into
  another session. Changing `session_id` on a middle row is detected. These limits go in the
  README and in `design.md` section 10.
