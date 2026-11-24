# Revenant core

Revenant records the calls an AI agent makes as an ordered, hash-chained list of events, and
replays them later. Replay returns the recorded outputs. It never calls a model or a tool.

"Deterministic" here means exactly that: replay gives back what was recorded. It does not mean
re-running a model and expecting the same answer.

The core knows nothing about files, refunds, or any particular agent. Domain code is wrapped
from outside. The core has no network access, no LLM SDK, and no web framework.

## Install

From `revenant-core/`:

```
python -m pip install -e ".[dev]"
```

Python 3.11 or newer is required.

## Quick start

Record a session, then replay it. Replay makes no real call.

```python
from revenant import Recorder, SQLiteTraceStore

calls = {"search": 0}

def search(query: str) -> str:
    calls["search"] += 1
    return f"results for {query}"

store = SQLiteTraceStore("trace.db")
with Recorder.record(store, session_id="demo") as rec:
    first = rec.wrap_tool(search, name="search")("cats")
    rec.final_answer({"answer": first})

with Recorder.replay(store, "demo") as rec:
    again = rec.wrap_tool(search, name="search")("cats")
    rec.final_answer({"answer": again})

assert again == first and calls["search"] == 1  # replay made no real call
store.close()
```

Each wrapped call writes a call event, then a `tool_result` or `error` event that points back
at it. `wrap_llm` and `wrap_tool` take sync or async functions and keep their signatures.

## Fork

`Recorder.fork` starts a new session from a call in a recorded one. Calls before that step
are replayed from the parent. The call at that step is recorded in the child with an optional
`override` as its result, and the real function is not called for it. Later calls run live.
The child is linked to the parent and copies the parent's prefix, so its chain verifies alone.

```
child = Recorder.fork(store, "demo", at_step=1, override="cached", session_id="demo-2")
```

## Diff

`diff_sessions(a, b)` compares two event lists and returns a `TraceDiff` value. It gives the
first divergent step, the kind of divergence (`different_tool`, `args`, `result` or `length`),
and every step that differs. It ignores ids, timestamps and hashes.

## Redaction

The default redactor masks the values of keys such as `api_key`, `password`, `token`,
`secret`, `authorization`, `cookie`, `bearer` and `private_key`, at any depth and in any case.
It also masks secrets written in free text as `key=value`, `key: value`, JSON-style, or
`Bearer <token>`. Pass your own `redactor=` to replace it.

## Limitations

- **Hash chain scope.** The chain does not detect truncation of the last events, or moving the
  last event into another session. Changing `session_id` on a middle event is detected. If the
  head hash matters, store it somewhere the attacker cannot write. The fork link
  (`parent_session_id`, `parent_step`) is not covered by the chain either.
- **Exception text.** Exception messages and args are redacted only by the default hook, and
  only in the forms listed under Redaction. A custom redactor replaces that behavior.
- **`redact_text` is best-effort.** It is pattern-based and is not a guarantee that no secret is
  stored. A secret written in any other form passes through unchanged. The default hook may also
  over-redact text that merely looks like `key: value`. For example, `token: refresh needed`
  becomes `token: [REDACTED] needed`.
- **Recording happens on completion.** A call is recorded only when it completes. A call
  interrupted by `KeyboardInterrupt` or cancellation leaves no event. A result that is not
  plain JSON leaves no event for that call, and the recorder then refuses further calls with
  a message that says so.
- **Default names.** Without `name=`, a wrapped function is recorded under its `__qualname__`,
  for example `RealTools.add`. Pass `name=` to choose the name yourself.
- **Unwrapped nondeterminism.** Replay cannot see time, random numbers, environment variables,
  file or network reads that your code makes directly. Use `recorder.now()`, `uuid4()` and
  `random()`, or wrap the source in `wrap_tool`. Otherwise replay can differ from the original
  run without any error.
- **Side effects in fork.** Replay never runs a real function. A fork's live phase does run
  real functions, and their side effects happen again.
- **Sequential calls only.** Overlapping wrapped calls, including `asyncio.gather`, nested
  calls and threads, raise `ConcurrentCallError`.
- **Plain JSON on replay.** Replay returns dicts, lists, strings, numbers, booleans and `None`.
  Tuples and other non-JSON values cannot be recorded at all.
- **Divergence keeps the position.** A mismatch raises `DivergenceError` and does not move the
  replay position. A retry of the same call gives the same error. The recorder stays open.
- **Exception rebuilding.** A recorded exception is rebuilt only if its class is already
  imported in the running process. Otherwise replay raises `DivergenceError`.
- **Partial forks.** The store cannot delete sessions. If copying a fork's prefix fails partway,
  a partial child session remains. Replaying it fails closed, because its chain is incomplete.

## Development

From the repository root:

```
powershell -ExecutionPolicy Bypass -File scripts\checkpoint.ps1
```

It runs pytest, `mypy --strict`, `ruff check`, `ruff format --check`, and the Hypothesis tests
20 times. It exits non-zero if any step fails.
