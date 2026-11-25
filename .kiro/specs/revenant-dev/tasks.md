# Implementation Plan

No app code is written until you approve this spec. Work stays in `applications/revenant-dev/`. Nothing under `revenant-core/` is edited.

Each phase ends with a checkpoint. Run the app checks from `applications/revenant-dev/` with the app venv:

- `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`
- `.venv\Scripts\python.exe -m mypy --strict src tests`
- `.venv\Scripts\python.exe -m ruff check src tests`
- `.venv\Scripts\python.exe -m ruff format --check src tests`

At each checkpoint, show the real output, then a summary of 5 lines or fewer. Then stop until you say "continue".

Write each source file in pieces of about 100 lines or fewer, and check the line count after each piece (see `docs/kiro-notes.md`). Test numbers follow `requirements.md`.

## Task B: revenant-core baseline (run first)

- [ ] B.0 Gates: stop unless both hold
  - `D:\Revenant\revenant-core\README.md` exists. If not, stop.
  - `tests/test_readme.py` passes in `D:\Revenant\revenant-core` (`.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_readme.py`). If it fails, stop.
  - _Requirements: precondition_
- [ ] B.1 Run the revenant-core checkpoint from `D:\Revenant`
  - `powershell -ExecutionPolicy Bypass -File scripts\checkpoint.ps1`. It runs pytest, mypy --strict, ruff check, ruff format --check, and the Hypothesis tests 20 times, so it takes a few minutes. Show the real output.
  - _Requirements: precondition_
- [ ] B.2 Stop if the baseline fails
  - If the script exits with a code other than 0, stop. Report which step failed (the script prints `CHECKPOINT FAILED: ...`). Do not start Phase 0.
- [ ] B.3 Checkpoint: show the summary (5 lines or fewer) and stop.

## Phase 0: project setup

- [ ] 0. Set up the project
  - [ ] 0.1 Create `pyproject.toml`, `.gitignore` (`.venv/`, `.data/`) and the package `src/revenant_dev/__init__.py`
    - Python `>=3.11`, runtime dependency `pydantic>=2`. The dev extras are `pytest`, `mypy`, `ruff`.
    - Configure `[tool.mypy] strict = true`, `[tool.ruff]` with `src = ["src", "tests"]` and `exclude = ["sample_repo"]` (D8), and `[tool.pytest.ini_options] testpaths = ["tests"]`.
    - _Requirements: 1.1, 1.4, 12.1, 12.2_
  - [ ] 0.2 Create the venv and install the core in editable mode
    - `python -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -e ..\..\revenant-core -e ".[dev]"`.
    - _Requirements: 1.2, 1.3_
  - [ ] 0.3 Record the baseline state of `revenant-core/`
    - Before any edit, note `git -C f:\Revenant status --short -- revenant-core`. Two untracked files existed there at baseline: `revenant-core/src/README.md` and `revenant-core/tests/test_integration_guide.py`. The stray `revenant-core/src/README.md` was deleted in the commit `remove stray src README`. It was never tracked, so that commit only records this line. `revenant-core/tests/test_integration_guide.py` stays untracked until the commit `docs: integration guide`. After the install, the status must match this baseline.
    - _Requirements: 1.3_
  - [ ] 0.4 Write `tests/test_smoke.py`
    - Imports `revenant.Recorder` and `revenant_dev`. This proves the editable install works.
    - _Requirements: 1.2_
- [ ] 0.5 Checkpoint: run the four checks. Show output and stop.

## Phase 1: sample repository, errors, workspace and tools

Phase 1 is done (commit `922e8ed`). By decision, the scripted LLM and agent loop from Phase 2, and milestone 1 from Phase 3, were built in the same phase. The Phase 2 and Phase 3 checkboxes below stay unchecked, because their tasks were not tracked one by one.

- [x] 1. Build the sample repository and the tool layer
  - [x] 1.1 Create `sample_repo/` (done in Phase 0, commit `f9b9ab4`)
    - `pytest.ini` (an empty `[pytest]` section), `sample_pkg/__init__.py`, `sample_pkg/stats.py` (the planted bug, `mean` divides by `len(values) - 1`), `sample_pkg/text.py` (`slugify`), `tests/test_stats.py` (`test_mean_of_three` fails), `tests/test_text.py` (passing tests).
    - Run `python -m pytest` inside `sample_repo/`. The output must show exactly one failure, `test_stats.py::test_mean_of_three`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [x] 1.2 Implement `errors.py` and `counters.py`
    - The error classes from design section 6. Each takes one message argument. `RealCallCounters` with `snapshot()` and `reset()`.
    - `ForkNotSupportedError` is not built. It belongs to fork (Phase 4).
    - _Requirements: 3.5, 4.5, 6.4, 10.4_
  - [x] 1.3 Implement `workspace.py`
    - `Workspace.resolve` with the escape checks, and `copy_sample`. The module docstring states the redaction limit (D5). There is no restore helper in v1 (D4).
    - _Requirements: 4.2, 5.1_
  - [x] 1.4 Implement `tools.py`
    - `read_file`, `write_file`, `run_tests` as closures over one `Workspace` and one `RealCallCounters`. `run_tests` uses `sys.executable -m pytest -p no:cacheprovider -rf -q`, with `cwd` set to the workspace and a 60-second timeout. It parses counts and node ids only.
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6_
  - [x] 1.5 Write tests for phase 1
    - `test_workspace.py` and `test_tools.py` as set out in design section 8. The symlink test in `test_workspace.py` is skipped on this machine.
    - _Requirements: 2.4, 4.2, 4.5, 5.1_
- [x] 1.6 Checkpoint: run the four checks, and show `python -m pytest` run from `sample_repo/`. Show output and stop.

## Phase 2: scripted LLM and agent loop

Built in Phase 1 by decision (commit `922e8ed`). The checks in Phase 1 covered this code.

- [ ] 2. Build the scripted LLM and the agent loop
  - [ ] 2.1 Implement `llm.py`
    - `ScriptedLLM.__call__(turn, messages)`, the shape check, and `planned_script(extra_reads=0)` with the six turns from design 5.1. `extra_reads=1` gives the variant that moves the bad write to a different step.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 7.7_
  - [ ] 2.2 Implement `agent.py`
    - `run_agent(rec, task, llm, tools, *, max_steps, max_calls=None) -> AgentResult` as in design 3.5. It wraps `llm` and the tools inside the function, so the same call works for record, replay and fork. `max_calls` stops the loop after that many completed wrapped calls, with `final=None`.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_
  - [ ] 2.3 Write tests for phase 2
    - `test_llm.py`, and `test_agent.py`. The divergence test uses a real `Recorder.record` session and a changed agent, then checks that `DivergenceError` reaches the caller. A `max_calls` test checks the exact number of real calls made.
    - _Requirements: 3.1-3.5, 6.1-6.7, 8.1_
- [ ] 2.4 Checkpoint: run the four checks. Show output and stop.

## Phase 3: milestone 1 (record, save, replay, report)

Built in Phase 1 by decision (commit `922e8ed`). The checks in Phase 1 covered this code. Run 3.3 was done with `python -m revenant_dev.demo`.

- [ ] 3. Run the milestone
  - [ ] 3.1 Implement `demo.py`
    - `find_first_bad_edit(events)` (design 5.2), which takes only the event list. `run_milestone1(store_path, workspace_root, *, session_id=None) -> Milestone1Report` and `main()`. The `__main__` guard lets the file run as `python -m revenant_dev.demo`. Close the store, then reopen the same file for replay.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - [ ] 3.2 Write `test_milestone.py`
    - Replay counters are all 0. Replayed `AgentResult` equals the live one. The reported first bad edit step equals the stored `write_file` step. The sample hash is unchanged. The workspace hash is unchanged by replay. A changed path raises `DivergenceError`. A `password=...` line in a sample file is stored as `[REDACTED]`.
    - A hand-built event list with no script and no sample (a `write_file`, then a `run_tests` with `exit_code` 1) gives the expected step. This shows the finder reads recorded results only.
    - The variant test (`planned_script(extra_reads=1)`) records a second session. The report names the step of that session's stored `write_file` event, which is 11 under the planned script. The test compares against the stored event, not the number 11.
    - Milestone code is in Phase 3, so this test lives here, not in Phase 2. Phase 2 only builds the variant script (task 2.1).
    - _Requirements: 2.5, 5.2, 7.1-7.7, 8.1, 8.2, 9.1, 9.2_
  - [ ] 3.3 Run `python -m revenant_dev.demo` once, against a store under `.data/`
    - Show the real printed report. It must show the live counters, the zero replay counters, and the first bad edit.
    - _Requirements: 7.3, 7.5_
- [ ] 3.4 Checkpoint: run the four checks, then show the report from 3.3. Show output and stop.

## Phase 4: JSON API layer (v1 fork: override only)

- [ ] 4. Expose the session data as plain functions
  - [ ] 4.1 Implement `api.py`
    - `list_sessions`, `session_events`, `diff_sessions`, and `fork_session` as in design section 7. `fork_session` follows design 4.3 steps 1-7: it requires `use_override=True`, counts the prefix calls, calls `Recorder.fork`, runs `run_agent` with `max_calls=k + 1` on a temporary empty workspace, reads the overridden result, and returns the diff. It writes no file and runs no live call.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_
  - [ ] 4.2 Write `test_api.py`
    - Round-trip through `canonical_json`. Unknown session and bad fork step raise the core errors. A fork without `use_override` raises `ForkNotSupportedError`. A fork with an override keeps all real-call counters at 0. The child stores the override at `at_step + 1`, links to its parent, and the diff's first divergent step is `at_step + 1`. The parent's event count and `verify_chain` are unchanged after a fork.
    - _Requirements: 10.2, 10.3, 10.4, 10.5_
- [ ] 4.3 Checkpoint: run the four checks. Show output and stop.

## Phase 5: README and final gates

- [ ] 5. Document the limits and confirm the constraints
  - [ ] 5.1 Write `README.md`
    - What the app is, how to run `python -m revenant_dev.demo`, and what v1 fork does (override only, no file restore). A Limits section states that recorded files may hold `[REDACTED]` in place of secrets, and that a live fork restore (stretch S1), if built, would reproduce that text.
    - _Requirements: 9.3_
  - [ ] 5.2 Run the full checks from a clean state
    - Delete `.data/`. Run the four checks, then rerun the milestone.
    - _Requirements: 12.1_
  - [ ] 5.3 Check that `revenant-core/` is unchanged
    - `git -C f:\Revenant status --short -- revenant-core` must match the baseline from 0.3. Show the output.
    - _Requirements: 1.3_
  - [ ] 5.4 Check that `sample_repo/` is unchanged
    - `git -C f:\Revenant status --short -- applications/revenant-dev/sample_repo` must be empty after all runs.
    - _Requirements: 2.5, 5.1_
- [ ] 5.5 Final checkpoint: show all output from 5.2 to 5.4, then a short report of what was built and what was not. Stop.

## Stretch S1: live fork and file restore (not scheduled)

Do not start these tasks without a separate approval.

- [ ] S1.1 Write the design note
  - Resolve how restore writes fit the core's fork layout (design section 10). Stop and wait for approval.
  - _Requirements: 11.3_
- [ ] S1.2 Build live fork after S1.1 is approved
  - Every live write, including restore writes, goes through a wrapped tool and is recorded. Replay still never writes.
  - _Requirements: 11.2, 11.4_
