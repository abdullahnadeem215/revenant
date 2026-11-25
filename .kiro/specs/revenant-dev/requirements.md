# Requirements Document

## Introduction

revenant-dev is a demo coding agent built on revenant-core. It lives in `applications/revenant-dev/`. The agent edits a small sample Python package, the run is recorded with the core, and the recording is replayed. The app is backend only: no UI, no network, no real model.

Its purpose is to prove the core on a real agent loop before later apps (DEV debugging, QA regression) are built. Those apps are out of scope.

Scope boundary: nothing under `revenant-core/` is modified. Domain code (files, tests, the agent) stays in the app. The core is used only through its public API: `Recorder`, `SQLiteTraceStore`, `diff_sessions`, `canonical_json` and the typed errors.

### Glossary

- **Agent loop**: the function that alternates LLM turns and tool calls until it gets a final answer or reaches the step limit.
- **Scripted LLM**: a fake model that returns canned responses selected by turn index. It makes no network call.
- **Turn index**: the zero-based number of an LLM turn. The agent passes it as an argument, so the same turn gives the same answer in record, replay and fork.
- **Workspace**: a directory holding one copy of `sample_repo/`. A session edits only its own workspace.
- **Real function**: the body of a tool or of the scripted LLM. Each real function increments its own counter when it runs.
- **Bad edit**: a `write_file` call after which the next recorded `run_tests` result exits non-zero, with no other write in between. The verdict comes only from recorded results. It does not mean any wrong behavior. A write that the agent fixed later is still bad if the `run_tests` right after it failed. A write with no `run_tests` after it, before the next write, is not a bad edit.

## Requirements

### Requirement 1: Project setup

**User Story:** As a developer, I want the demo installed against the local core, so that it runs the core code I can see without a copy.

#### Acceptance Criteria

1. THE project SHALL live in `applications/revenant-dev/`, with a `pyproject.toml` and the package `src/revenant_dev/`.
2. THE project SHALL install `revenant-core` in editable mode from `../../revenant-core`, relative to the app directory, into its own virtual environment at `applications/revenant-dev/.venv`.
3. THE project SHALL NOT modify any tracked file under `revenant-core/`. The editable install may regenerate `revenant-core/src/revenant_core.egg-info`, which `.gitignore` already excludes.
4. THE runtime dependencies SHALL be revenant-core and its dependencies. THE dev extras SHALL be `pytest`, `mypy` and `ruff`.

### Requirement 2: Sample repository

**User Story:** As a developer, I want a small package with one known bug, so that the agent has a concrete fix to make and a test to show it.

#### Acceptance Criteria

1. THE directory `applications/revenant-dev/sample_repo/` SHALL be a small Python package named `sample_pkg`, with a `tests/` directory.
2. THE planted bug SHALL be in `sample_pkg/stats.py`: `mean(values)` divides by `len(values) - 1` instead of `len(values)`.
3. `sample_pkg/text.py` SHALL hold `slugify(title)`, with passing tests. This keeps every failure in the suite tied to the one planted bug.
4. AT baseline, exactly one test SHALL fail: `tests/test_stats.py::test_mean_of_three`. All other tests SHALL pass.
5. THE committed sample SHALL NOT be edited by any run. A test SHALL check this by hashing the sample before and after a run.

### Requirement 3: Scripted LLM

**User Story:** As a developer, I want a fake model with canned answers, so that the agent loop can be run and replayed without a real model.

#### Acceptance Criteria

1. THE scripted LLM SHALL return the canned response for the turn index it is given. It SHALL NOT make network calls or import any model SDK.
2. THE turn index SHALL be a recorded argument of the wrapped LLM call, so the fingerprint of each turn matches across record, replay and fork.
3. IF the turn index is past the end of the script, THEN THE scripted LLM SHALL raise `ScriptExhaustedError`.
4. EACH response SHALL be either `{"tool": <name>, "args": {...}}` or `{"final": <text>}`. Any other shape SHALL raise `AgentProtocolError`.
5. THE scripted LLM SHALL count its real invocations.

### Requirement 4: Tools

**User Story:** As a developer, I want three tools confined to the workspace, so that the agent can read, edit and test code without reaching anything else on disk.

#### Acceptance Criteria

1. THE tools SHALL be `read_file(path)`, `write_file(path, content)` and `run_tests()`. They operate only on the session workspace.
2. A path SHALL be relative and SHALL resolve inside the workspace root. An absolute path, a `..` that leaves the root, or a symlink that leaves the root SHALL raise `SandboxViolationError` before any file is touched.
3. `write_file` SHALL write UTF-8 text, creating or overwriting the file. It SHALL return `{"path": str, "bytes": int}`.
4. `run_tests` SHALL run pytest in the workspace as a subprocess, using `sys.executable`, with a fixed timeout. It SHALL return `{"exit_code": int, "passed": int, "failed": int, "failed_tests": [str]}` with the node ids of the failures. It SHALL NOT return timings or temporary paths.
5. EACH tool SHALL increment its own real-call counter when its body runs.
6. EVERY tool result SHALL be plain JSON.

### Requirement 5: Workspace

**User Story:** As a developer, I want each run to start from a clean copy, so that one run cannot change the next one.

#### Acceptance Criteria

1. EACH live session SHALL get a new workspace, made by copying `sample_repo/` into a directory owned by that session.
2. WHEN a session is replayed, THE replay SHALL NOT write to any workspace.

### Requirement 6: Agent loop

**User Story:** As a developer, I want one agent loop that behaves the same live and under replay, so that replay checks the real agent code.

#### Acceptance Criteria

1. THE agent loop SHALL call the LLM with the turn index and the message history. IF the response is a tool request, THE loop SHALL call the named tool and append its result to the history. IF the response is a final answer, THE loop SHALL call `final_answer` and stop.
2. AN unknown tool name SHALL raise `AgentProtocolError`.
3. THE loop SHALL stop after `max_steps` LLM turns and raise `AgentStepLimitError`.
4. A `ToolError` raised by a tool (for example `SandboxViolationError`) SHALL be returned to the model as the tool result, so the agent can react to it.
5. THE loop SHALL NOT catch `DivergenceError` or any other `RevenantError` from the core. Those SHALL reach the caller.
6. THE message history SHALL be plain JSON, so that it can be fingerprinted.
7. WHERE a `max_calls` limit is given, THE loop SHALL return without a final answer as soon as that many wrapped calls (LLM and tool calls together) have completed. Fork uses this to stop at its fork step.

### Requirement 7: Record, save and replay (milestone 1)

**User Story:** As a developer, I want to run the agent live, save the session and replay it, so that I can see that replay makes no real call and find the first bad edit.

#### Acceptance Criteria

1. THE milestone SHALL run the agent live under `Recorder.record`, save the session in `SQLiteTraceStore`, and return a report.
2. THE milestone SHALL then replay the saved session with `Recorder.replay`, using the same agent code and the same wrapped tool and LLM names.
3. THE report SHALL include the real-call counters of the replay run: one counter for each tool and one for the scripted LLM. THE counters SHALL be 0.
4. THE replayed final answer and the replayed tool results SHALL equal the recorded ones.
5. THE report SHALL name the first bad edit: the step of the first `write_file` `tool_call` that is a bad edit (see the glossary). THE report SHALL say so if no write is bad.
6. THE report SHALL be computed from the recorded results only. The finder SHALL take the stored events as its only input. It SHALL NOT read an expected fix, an expected step, a test name or the scripted answers from the app or the script. A test SHALL check the reported step against the stored `write_file` event, not against a number written into the code. A second test SHALL run the finder on a hand-built event list that has no script and no sample, and check the result.
7. A second scripted run SHALL put one extra read before the bad write, so the bad write falls on a different step. THE report for that run SHALL name the new step, computed from the recorded results only. A test SHALL check it against the stored `write_file` event.

### Requirement 8: Divergence

**User Story:** As a developer, I want a changed agent to fail loudly on replay, so that stale recordings are never silently reused.

#### Acceptance Criteria

1. IF a replayed agent makes a call that differs from the recording (another tool name, or other arguments), THEN replay SHALL raise `DivergenceError` from the core, and the agent SHALL NOT continue.
2. A replay given a changed input SHALL raise `DivergenceError` at the first mismatched call. A test SHALL replay a recorded session with a changed task text, which changes the arguments of the first LLM call, and SHALL check that the error reports step 1.

### Requirement 9: Redaction

**User Story:** As a developer, I want secrets kept out of stored sessions, so that a recording can be shared safely.

#### Acceptance Criteria

1. THE sessions SHALL be recorded with the core default redactor. The app SHALL NOT replace it with a weaker one.
2. A test SHALL put `password=...` text in a sample file, read it through `read_file`, and check that the stored `tool_result` shows `[REDACTED]`.
3. THE app `README.md` SHALL have a Limits section. That section SHALL state that recorded files may hold `[REDACTED]` in place of secrets. It SHALL also state that a live fork restore, if stretch S1 is built, would reproduce that text (see design D5).

### Requirement 10: JSON API layer (function only)

**User Story:** As a developer, I want the session data behind plain functions, so that a web layer can be added later without changing the core or the agent.

#### Acceptance Criteria

1. THE module `revenant_dev.api` SHALL expose these functions: `list_sessions(store)`, `session_events(store, session_id)`, `fork_session(store, parent_session_id, at_step, *, override=None, use_override=False, session_id=None)` and `diff_sessions(store, session_a, session_b)`.
2. EACH function SHALL return JSON-compatible dicts or lists. A test SHALL check that the output round-trips through the core's `canonical_json`.
3. AN unknown session SHALL raise the core's `SessionNotFoundError`. Errors SHALL NOT be turned into error dicts.
4. `fork_session` in v1 SHALL:
   a. raise `ForkNotSupportedError` if `use_override` is false;
   b. validate the fork point through the core (`InvalidForkPointError`);
   c. create the child with `Recorder.fork`, so the prefix is replayed from the parent;
   d. make the agent's call at the fork step, which the core records with the override as its result, without calling the real function;
   e. stop there, with no later call, and return the child session id, the overridden result, and the diff against the parent.
5. THE parent session SHALL NOT change. Its event count and hash chain SHALL be the same after a fork.
5a. A v1 fork SHALL NOT write any file, and no real tool or LLM function SHALL run during it. The real-call counters SHALL stay at 0 across the whole fork.
6. THE API SHALL NOT start a server and SHALL NOT import any web framework.

### Requirement 11 (stretch S1, not in v1): Live fork and file state

**User Story:** As a developer, I want a live fork to run past its fork step on the same files the parent had, so that the forked run is meaningful.

#### Acceptance Criteria

1. Not part of v1. Requirement 10.4 covers the v1 fork, which writes no file and runs no live call.
2. IF S1 is built, every file write during a live fork, including any write that restores files, SHALL go through a wrapped tool and SHALL be recorded as an event in the child.
3. IF S1 is built, a design note SHALL resolve how restore writes fit the core's fork layout before any code is written (design section 10).
4. Replay SHALL still never write to a workspace (requirement 5.2), with or without S1.

### Requirement 12: Quality gates

**User Story:** As a developer, I want every checkpoint to pass the same checks as the core, so that the app meets the project's standard.

#### Acceptance Criteria

1. EACH checkpoint SHALL pass `pytest`, `mypy --strict` over `src` and `tests`, `ruff check` and `ruff format --check`. Real output SHALL be shown.
2. ALL code under `src/` and `tests/` SHALL be fully typed.
3. THE tests SHALL assert on call counters and recorded data. They SHALL NOT assert on printed output.

## Non-goals

- Any UI, web server, HTTP endpoint or web framework.
- Network access, real LLM calls or any LLM SDK.
- The DEV debugging app and the QA regression app.
- Changes to `revenant-core/`.
- Async code, property-based (Hypothesis) tests, or pytest export.
- Live fork execution and file restore after a fork step (stretch S1, requirement 11).
- A command-line interface. The one entry point is `python -m revenant_dev.demo`, which runs milestone 1 and prints the report.
