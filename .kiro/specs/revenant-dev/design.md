# Design Document

## 1. Overview

The app has three layers. The core is used unchanged. The domain layer (tools, scripted LLM, agent loop) is plain Python that the core wraps from outside. The entry layer (`demo.py` for milestone 1, `api.py` for the JSON functions) only composes the other two.

```
api.py / demo.py       entry points: milestone report, JSON functions
   |
agent.py               run_agent(rec, ...): one loop, used for record, replay and fork
llm.py   tools.py      scripted LLM; read_file / write_file / run_tests
workspace.py           path confinement, sample copy
   |
revenant-core          Recorder, SQLiteTraceStore, diff_sessions, typed errors
```

The agent receives a `Recorder` in whatever mode it is in. It wraps the raw LLM and tool functions itself. The same loop therefore runs live, under replay, and in a fork, so replay checks the real agent code.

## 2. Layout

```
applications/revenant-dev/
  pyproject.toml             deps: revenant-core (editable, ../../revenant-core), pydantic
  .gitignore                 .venv/, .data/
  README.md                  what the app is, how to run it, and a Limits section (requirement 9.3)
  src/revenant_dev/
    __init__.py
    errors.py                DemoError and subclasses (section 6)
    counters.py              RealCallCounters dataclass
    workspace.py             Workspace (confinement), copy_sample
    tools.py                 make_tools(workspace, counters)
    llm.py                   ScriptedLLM, planned_script()
    agent.py                 run_agent(), AgentResult
    demo.py                  run_milestone1(), find_first_bad_edit(), main()
    api.py                   list_sessions, session_events, fork_session, diff_sessions
  sample_repo/
    pytest.ini               empty [pytest] section, so pytest stops at this root
    sample_pkg/__init__.py, stats.py (planted bug), text.py
    tests/test_stats.py      test_mean_of_three (fails at baseline)
    tests/test_text.py       passing tests for slugify
  tests/
    conftest.py, test_workspace.py, test_tools.py, test_llm.py,
    test_agent.py, test_milestone.py, test_api.py
  .data/                     created at run time, git-ignored
```

`sample_repo/pytest.ini` matters. A workspace lives under `applications/revenant-dev/`, so without its own ini file, pytest would walk up and use the app's `pyproject.toml`. Its `testpaths` would then point at the app's tests.

## 3. Components

### 3.1 Workspace (`workspace.py`)

```python
class Workspace:
    def __init__(self, root: Path) -> None: ...   # root is resolved once
    def resolve(self, relative: str) -> Path: ...  # SandboxViolationError on escape

def copy_sample(sample: Path, dest: Path) -> None: ...  # copytree, skips __pycache__ and .pytest_cache
```

`resolve` rejects an empty path, an absolute path, and any path whose resolved form is not inside the root. `Path.resolve()` follows symlinks, so a symlink that leaves the root is caught by the same check.

The module docstring states the redaction limit (D5): recorded file content may hold `[REDACTED]` in place of a secret.

v1 has no file restore. Stretch S1 (section 10) covers it.

### 3.2 Real-call counters (`counters.py`)

```python
@dataclass
class RealCallCounters:
    llm: int = 0
    read_file: int = 0
    write_file: int = 0
    run_tests: int = 0
    def snapshot(self) -> dict[str, int]: ...
```

Each real function increments its own field first thing in its body, before any check. A rejected sandbox path still counts as a call.

### 3.3 Tools (`tools.py`)

```python
def make_tools(workspace: Workspace, counters: RealCallCounters) -> dict[str, Callable[..., JSONValue]]:
    # keys: "read_file", "write_file", "run_tests"
```

- `read_file(path: str) -> {"path": str, "content": str}`. Content is read as UTF-8. Missing files raise `ToolError`.
- `write_file(path: str, content: str) -> {"path": str, "bytes": int}`. It creates parent directories.
- `run_tests() -> {"exit_code", "passed", "failed", "failed_tests"}`. It runs `[sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-rf", "-q"]` with `cwd` set to the workspace root and a 60-second timeout. Timeout raises `ToolError`. The counts and the node ids come from the pytest output. Timings, durations and temporary paths are not returned.

The tools never import the sample package. They only run it in a subprocess. A failing test is data, not an exception, so `run_tests` returns normally with `failed > 0`.

### 3.4 Scripted LLM (`llm.py`)

```python
class ScriptedLLM:
    def __init__(self, script: Sequence[JSONValue], counters: RealCallCounters) -> None: ...
    def __call__(self, turn: int, messages: list[JSONValue]) -> JSONValue: ...
```

It increments `counters.llm`, then returns `script[turn]`. It validates the shape of the response: a dict with exactly `tool` and `args`, or exactly `final`. Index past the end raises `ScriptExhaustedError`. `messages` is accepted so that the history is part of the recorded arguments. The answer is not computed from it.

`planned_script()` returns the script for the demo (section 5).

### 3.5 Agent loop (`agent.py`)

```python
@dataclass(frozen=True)
class AgentResult:
    final: str | None   # None when the loop stopped at max_calls
    messages: list[JSONValue]

def run_agent(
    rec: Recorder,
    task: str,
    llm: Callable[..., JSONValue],
    tools: Mapping[str, Callable[..., JSONValue]],
    *,
    max_steps: int,
    max_calls: int | None = None,
) -> AgentResult: ...
```

The loop wraps `llm` once as `rec.wrap_llm(llm, name="llm")` and each tool as `rec.wrap_tool(fn, name=tool_name)`. Then, for turn `t` from 0 to `max_steps - 1`:

1. Call `wrapped_llm(turn=t, messages=history)`.
2. If the answer is `{"final": text}`, call `rec.final_answer({"answer": text})` and return.
3. If it is `{"tool": name, "args": args}`, look up `name`. An unknown name raises `AgentProtocolError`. Call the wrapped tool with `**args`. A `ToolError` is caught, and its message becomes the tool result `{"error": message}`. Append the call and its result to `history`.
4. After `max_steps` turns with no final answer, raise `AgentStepLimitError`.
5. If `max_calls` is given, return `AgentResult(final=None, ...)` as soon as that many wrapped calls (LLM and tool calls together) have completed. The check runs after each completed call, before the next one. Fork uses this to stop at its fork step (section 4.3).

`DivergenceError` and every other `RevenantError` pass through, because the loop catches only `ToolError`. `messages` holds plain dicts and strings.

The argument `args` from the model must be a JSON object. The loop validates this before the call and raises `AgentProtocolError` otherwise.

## 4. Data flows

### 4.1 Milestone 1 (`demo.run_milestone1`)

1. Create `SQLiteTraceStore(store_path)`. Create a new workspace directory, then `copy_sample` into it.
2. Create one `RealCallCounters`, `ScriptedLLM(planned_script(), counters)` and `make_tools(workspace, counters)`.
3. Record. Open `Recorder.record(store, session_id=sid, metadata={"task": TASK, "max_steps": 10})`. Call `run_agent`. Take the live counter snapshot, then reset the counters to zero.
4. Close the store and reopen the same file. This shows that the session was saved. Open `Recorder.replay(store, sid)`. Call `run_agent` again with the same `llm` and `tools` callables.
5. Take the replay counter snapshot. Check that the replayed `AgentResult` equals the live one. Run `find_first_bad_edit` on the stored events.
6. Return `Milestone1Report` (section 5.3). `main()` prints it.

The task text and `max_steps` are stored in the `session_start` metadata. `fork_session` reads them from there, so a fork needs no outside configuration.

### 4.2 Replay

The wrappers answer each call from the recording. Each answer is consumed in order, and the real functions are never reached. A changed agent that makes a call the recording does not have raises `DivergenceError` (requirement 8). The recorder then refuses further calls, as the core specifies.

### 4.3 Fork (`api.fork_session`), v1

A v1 fork replays the prefix, records the fork step with the override as its result, and stops. It runs no live call and writes no file.

1. If `use_override` is false, raise `ForkNotSupportedError`. Without an override, the fork step would need a live call, and v1 has none.
2. Load the parent events. Count the call events (`llm_call`, `tool_call`) with `step < at_step`, and call the count `k`. The fork step is call number `k`, zero-based, so the agent must make `k + 1` wrapped calls.
3. Call `Recorder.fork(store, parent, at_step, override=override, session_id=child_id)`. The core validates the fork point and copies the prefix before anything else runs.
4. Call `run_agent(rec, task, llm, tools, max_steps=..., max_calls=k + 1)`. `task` and `max_steps` come from the parent's `session_start` metadata. Prefix calls are answered from the parent. The call at the fork step returns the override, and the loop stops after it.
5. Build the tools on an empty temporary directory. No real function should run. Tests check this with the counters (section 8).
6. Close the recorder. Read the overridden result from the child's `tool_result` at step `at_step + 1`.
7. Return `{child_session_id, overridden_result, diff}`, where `diff` is `diff_sessions(parent, child)`.

## 5. Demo script and expected recording

### 5.1 Planned script (`llm.planned_script`)

| Turn | Response | Effect |
|---|---|---|
| 0 | `tool: read_file, path: sample_pkg/stats.py` | Reads the buggy file |
| 1 | `tool: write_file`, `mean` returns `sum(values) / len(values) - 1` | **Wrong edit**, planted on purpose |
| 2 | `tool: run_tests` | Fails: `test_mean_of_three` |
| 3 | `tool: write_file`, `mean` returns `sum(values) / len(values)` | Correct fix |
| 4 | `tool: run_tests` | Passes |
| 5 | `final: "Divide by len(values) in mean."` | Ends the run |

The planted wrong edit gives the milestone something to find. The report does not read the answer from the script. It finds the bad edit from the recorded `run_tests` exit code (section 5.2).

**Variant.** `planned_script(extra_reads=1)` adds one `read_file` of `sample_pkg/text.py` at turn 1, before the bad write. Each later turn moves up by one, and the final answer is turn 6. The bad write then falls at step 11, not 7. The second run is recorded in its own session, and the milestone test checks the reported step against that session's stored `write_file` event. The step 11 is for reference only.

### 5.2 Finding the first bad edit (`demo.find_first_bad_edit`)

The function takes the stored event list and nothing else. It reads recorded results only. It does not import the script, the sample or any test name, and it holds no expected fix or expected step.

A write is bad when the next recorded `run_tests` result after it exits non-zero, with no other write in between. Walk the events in step order, keeping one pending write:

- A `write_file` `tool_call` sets `pending` to its step and path. An earlier pending write with no verdict is dropped.
- The `tool_result` whose `parent_step` is `pending.step` confirms the write. An `error` answer clears `pending`, because nothing was written.
- A `run_tests` `tool_result` after a confirmed write gives the verdict. If `exit_code != 0`, the write is bad, and the function returns `(pending.step, pending.path)`. Otherwise it clears `pending`.

The function returns `None` when no write is bad. A `run_tests` before any write has no pending write, so it is never a verdict.

Expected recording under the planned script (one row per event, `llm` is the `llm_call` / `tool_result` pair):

| Step | Type | Note |
|---|---|---|
| 0 | `session_start` | metadata carries the task |
| 1, 2 | `llm_call`, `tool_result` | turn 0 |
| 3, 4 | `tool_call`, `tool_result` | `read_file` |
| 5, 6 | `llm_call`, `tool_result` | turn 1 |
| **7**, 8 | `tool_call`, `tool_result` | `write_file`, **wrong edit** |
| 9, 10 | `llm_call`, `tool_result` | turn 2 |
| 11, 12 | `tool_call`, `tool_result` | `run_tests`, fails |
| 13, 14 | `llm_call`, `tool_result` | turn 3 |
| 15, 16 | `tool_call`, `tool_result` | `write_file`, correct |
| 17, 18 | `llm_call`, `tool_result` | turn 4 |
| 19, 20 | `tool_call`, `tool_result` | `run_tests`, passes |
| 21, 22 | `llm_call`, `tool_result` | turn 5 (final) |
| 23 | `final_answer` | |

The planned answer is step 7. Tests take the step from the stored `write_file` event. They do not take it from this table.

### 5.3 Milestone report (`Milestone1Report`)

A frozen dataclass with: `session_id`, `final`, `replay_final_matches`, `live_counters`, `replay_counters`, `first_bad_edit_step`, `first_bad_edit_path`. `main()` prints each field on its own line and exits 0.

## 6. Errors

| Class | Base | Raised by | Agent behavior |
|---|---|---|---|
| `DemoError` | `Exception` | base of app errors | not caught |
| `ToolError` | `DemoError` | a tool fails (missing file, test timeout) | returned to the model |
| `SandboxViolationError` | `ToolError` | `Workspace.resolve` | returned to the model |
| `ScriptExhaustedError` | `DemoError` | scripted LLM past its last turn | not caught |
| `AgentProtocolError` | `DemoError` | bad LLM response shape, unknown tool, non-object args | not caught |
| `AgentStepLimitError` | `DemoError` | `max_steps` reached | not caught |
| `ForkNotSupportedError` | `DemoError` | `fork_session` called without an override (v1) | not caught |

Core errors pass through unchanged: `DivergenceError`, `ReplayExhaustedError`, `ChainIntegrityError`, `SessionNotFoundError`, `InvalidForkPointError`, `PayloadSerializationError`.

Every app error class takes one message argument. The core's `rebuild_exception` calls `cls(*args)` and compares `str(...)` with the recorded message, so a tool error replayed from the recording is rebuilt as the same class with the same text.

## 7. JSON API (`api.py`)

Plain functions, no server and no web framework. Every return value is made of dicts, lists, strings, numbers, booleans and `None`.

| Function | Returns |
|---|---|
| `list_sessions(store)` | `[{session_id, created_at, parent_session_id, parent_step}]` |
| `session_events(store, session_id)` | `[event.model_dump(mode="json")]` in step order |
| `fork_session(store, parent_session_id, at_step, *, override=None, use_override=False, session_id=None)` | `{child_session_id, overridden_result, diff}` |
| `diff_sessions(store, session_a, session_b)` | `{first_divergent_step, kind, differing_steps, len_a, len_b}` |

`override` can be any JSON value, including `None`, so `use_override` says whether to apply it. The core's own sentinel is private. v1 `fork_session` requires `use_override=True` (section 4.3). `overridden_result` is the value the child stored, which is the redacted override. A test checks that every return value round-trips through the core's `canonical_json`.

`diff_sessions` uses the core's `diff_sessions` and converts `TraceDiff` into the dict above. `kind` is a string or `None`.

## 8. Test plan

Tests assert on counters and recorded data. They do not assert on printed output. Each test uses `tmp_path` for the store and the workspaces.

| File | What it checks |
|---|---|
| `test_workspace.py` | Absolute path, `..` escape and symlink escape raise `SandboxViolationError` (the symlink case is skipped if Windows will not create the link). `copy_sample` skips caches. |
| `test_tools.py` | Each tool's counter goes up by 1 per call. Read and write round-trip. A rejected path counts as a call and writes nothing. `run_tests` on the sample gives `failed == 1` and the one node id. After the fix it gives `failed == 0`. |
| `test_llm.py` | The turn index selects the response. Past the end raises `ScriptExhaustedError`. A bad shape raises `AgentProtocolError`. The counter goes up per call. |
| `test_agent.py` | Unknown tool name, step limit, non-object args, and a `ToolError` that is returned to the model. A `DivergenceError` from a changed agent passes through. |
| `test_milestone.py` | Replay counters are all 0. Replayed `AgentResult` equals the live one. The reported first bad edit step equals the stored `write_file` step. Sample hash is unchanged after the run. Replay leaves the workspace hash unchanged. A changed path raises `DivergenceError` at the recorded step. A `password=...` line is stored as `[REDACTED]`. A hand-built event list (a `write_file` followed by a `run_tests` with `exit_code` 1, with no script or sample involved) gives the expected step, which shows the finder reads recorded results only. |
| `test_api.py` | Each function's output round-trips through `canonical_json`. Unknown session raises `SessionNotFoundError`. A bad fork step raises `InvalidForkPointError`. `fork_session` without `use_override` raises `ForkNotSupportedError`. With an override: all real-call counters stay 0 for the whole fork, `overridden_result` matches the stored step `at_step + 1`, the child links to its parent, and the diff's first divergent step is `at_step + 1`. The parent's event count and `verify_chain` are the same afterwards. |

## 9. Decisions for approval

- **D1. Per-session workspace.** Tools run on a copy of `sample_repo/`, not on the committed copy. Without this, the first run fixes the planted bug in the repo, and the next run has nothing to fix.
- **D2. Turn index as a recorded argument.** The scripted LLM receives `turn` explicitly, so the same turn gives the same answer in record, replay and fork. The cost is one more field in each `llm_call` payload. The alternative is a hidden counter, which breaks in a fork.
- **D3. Bad edit from recorded results only.** The report uses the recorded `run_tests` exit code after each write. The finder takes only the event list. It reads no answer key, no expected step and no test name. The script plants the wrong edit at turn 1.
- **D4. v1 fork has no file restore.** A v1 fork replays the prefix, records the fork step with the override as its result, and stops. It runs no live call and writes no file. Live forks and file restore move to stretch S1 (section 10). The alternative was to rebuild the child's files by reapplying recorded writes. That needs a core layout change, so it is deferred.
- **D5. Known limitation: redacted writes.** Recorded arguments are redacted. If a `write_file` content contains a secret, the restored fork file contains `[REDACTED]`, not the secret. The sample has no secrets. This is a v1 limitation. It is written in this document and in the docstring of `workspace.py`.
- **D6. Parsed test output only.** `run_tests` returns counts and failing node ids. Raw pytest output is not stored. This keeps recordings small and free of paths and timings, at the cost of debugging detail.
- **D7. Storage paths.** The store defaults to `applications/revenant-dev/.data/sessions.db`. Workspaces go to `.data/workspaces/<session_id>/`. The app `.gitignore` covers `.data/` and `.venv/`.
- **D8. Quality checks cover `src/` and `tests/` only.** `sample_repo/` holds a planted bug and untyped test functions, so it is left out of `mypy --strict` and `ruff`. Pytest still runs it through `run_tests`.
- **D9. Tool errors go to the model.** `ToolError` becomes an observation. Every other exception stops the run.
- **D10. No Hypothesis and no pytest-asyncio.** The scope has no async code and no property test. Add them later if you want them.
- **D11. Editable install.** `pip install -e` rewrites the ignored `revenant-core/src/revenant_core.egg-info`. No tracked file changes.

## 10. Stretch S1: live fork and file restore (not in v1)

Not scheduled. Build only after a separate approval.

- A live fork runs the agent past the fork step. Its file state must match the parent at that step.
- The core layout makes restore hard. The child copies the prefix, and the fork-step call is its next event. A restore write cannot come before the fork step without changing the core.
- If built, every restore write and every live write goes through a wrapped tool and is recorded (D4). Restore writes therefore have to be recorded events in the child. That conflicts with the layout above, so a design note must resolve it before any code is written.
- Replay still never writes (requirement 5.2), with or without this stretch.
- Until S1 is built, `fork_session` rejects calls without an override (`ForkNotSupportedError`).
