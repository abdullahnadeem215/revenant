# Revenant integration guide

For developers wrapping their own model client and tools. Requires Python 3.11 or newer.

## 1. Install

From the repository:

```
cd revenant-core
python -m pip install -e ".[dev]"
```

The core makes no network calls and has no LLM SDK.

## 2. Wrap your model and tools

Wrap every function that does work outside your program: model calls and tool calls.

```
llm = recorder.wrap_llm(my_model_call, name="llm")
search = recorder.wrap_tool(my_search)
```

- Sync and async functions both work, and each wrapper keeps its kind and signature.
- Arguments and results must be plain JSON (dict, list, str, int, float, bool, None). Anything
  else raises `PayloadSerializationError`, and that call is not recorded.
- Pass `name=` for a stable name. The default is `__qualname__`, so renaming a function makes
  replay diverge.
- Make wrapped calls one at a time. Overlap, including `asyncio.gather` and threads, raises
  `ConcurrentCallError`.

## 3. Record and replay

```
with Recorder.record(store, session_id="run-1", metadata={"app": "demo"}) as rec:
    ...  # run your code with wrapped functions

with Recorder.replay(store, "run-1") as rec:
    ...  # run the same code path with the same wrapped functions
```

- Recording runs your real functions and writes each call. Replay runs the same code path,
  never calls a real function, and returns each recorded result or re-raises its exception.
- End each run with `rec.final_answer(value)`. In replay, the value must match the recording.
- A mismatch in tool name, arguments or call order raises `DivergenceError`. The recorder then
  closes. Every later call raises `RevenantError` with the message
  `replay diverged at step N; recorder is closed`. Fix the cause, then start a new replay.
- If a replay finishes early, `close()` warns with `UnconsumedEventsWarning` and the count.

## 4. Fork

Fork starts a new session from a call in a recorded session:

```
with Recorder.fork(store, "run-1", at_step=3, override=["cached doc"], session_id="run-1b") as rec:
    ...
```

- `at_step` must be an `llm_call` or `tool_call` step. Any other step raises `InvalidForkPointError`.
- Calls before `at_step` are replayed from the parent. The call at `at_step` is checked against
  the parent's call.
- With `override`, the call at `at_step` is recorded in the child with the override as its
  result. The real function does not run for that call. `None` is a valid override.
- Without `override`, the real function runs for the call at `at_step`.
- Later calls run live in both cases. The child copies the parent's prefix and links back;
  the parent is not changed.
- Live calls have real side effects. Decide before forking whether that is acceptable.

## 5. Diff

```
from revenant.diff import diff_sessions

result = diff_sessions(store.load_session("run-1"), store.load_session("run-1b"))
```

`result` gives the first divergent step, its kind (`different_tool`, `args`, `result` or
`length`), and every differing step. Ids, timestamps and hashes are ignored.

## 6. Nondeterminism

Use `rec.now()` (UTC `datetime`), `rec.uuid4()` (`uuid.UUID`) and `rec.random()` (float in
[0, 1), not for security use) instead of the underlying sources. Each call writes one event in
record mode and returns the recorded value in replay.
Any other source of time, randomness, environment, file or network input must go through a
wrapped function. Otherwise replay can differ silently.

## 7. Known limits

The README's Limitations section has the full list. Most important: truncation of the last
events is not detected, `redact_text` is best-effort, and replay returns plain JSON.

## 8. Worked example

This script runs as written. The test suite runs it.

```python
import tempfile
from pathlib import Path

from revenant import Recorder, SQLiteTraceStore
from revenant.diff import diff_sessions

calls = {"llm": 0, "search": 0}


def fake_llm(prompt: str) -> str:  # stand-in for your model client
    calls["llm"] += 1
    return "search for cats"


def search(query: str) -> list[str]:  # stand-in for your tool
    calls["search"] += 1
    return [f"doc about {query}"]


store = SQLiteTraceStore(Path(tempfile.mkdtemp()) / "trace.db")

# 1. Record one run.
with Recorder.record(store, session_id="run-1") as rec:
    plan = rec.wrap_llm(fake_llm, name="llm")("what should I look up?")
    hits = rec.wrap_tool(search)("cats")
    run_id = rec.uuid4()
    rec.final_answer({"plan": plan, "hits": hits})

# 2. Replay it. No real function runs.
with Recorder.replay(store, "run-1") as rec:
    plan2 = rec.wrap_llm(fake_llm, name="llm")("what should I look up?")
    hits2 = rec.wrap_tool(search)("cats")
    run_id2 = rec.uuid4()
    rec.final_answer({"plan": plan2, "hits": hits2})
assert (plan2, hits2, run_id2) == (plan, hits, run_id)
assert calls == {"llm": 1, "search": 1}

# 3. Fork at the search call (step 3) with an override. Earlier calls replay.
with Recorder.fork(store, "run-1", at_step=3, override=["cached doc"], session_id="run-1b") as rec:
    plan3 = rec.wrap_llm(fake_llm, name="llm")("what should I look up?")
    hits3 = rec.wrap_tool(search)("cats")
    rec.final_answer({"plan": plan3, "hits": hits3})
assert hits3 == ["cached doc"]
assert calls == {"llm": 1, "search": 1}  # the override means search did not run

# 4. Diff the parent and the fork.
result = diff_sessions(store.load_session("run-1"), store.load_session("run-1b"))
assert (result.first_divergent_step, result.kind) == (4, "result")
store.close()
```
