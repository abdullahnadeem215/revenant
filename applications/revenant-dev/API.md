# revenant-dev backend API

Values in the examples are illustrative. The field names and types are exact.

Plain Python functions in `src/revenant_dev/api.py`. There is no web server. Each function takes a
`TraceStore` (the SQLite store from revenant-core) and returns JSON-compatible data. Every return
value round-trips through `canonical_json`.

| Function | Arguments | Returns |
|---|---|---|
| `list_sessions` | `store` | list of session summaries |
| `get_session` | `store, session_id` | one session with every stored event |
| `replay_summary` | `store, session_id, *, workspace_root` | replay counters and the replayed answer |
| `find_bad_edit` | `store, session_id` | the first bad edit, or `null` |
| `fork` | `store, parent_session_id, at_step, *, override=None, use_override=False` | child id and diff |

`workspace_root` is the folder that holds one workspace per session. Replay never writes there.

## `list_sessions(store)`

```json
[
  {
    "session_id": "c9c7b81f571149ab97d781e39071b6dd",
    "created_at": "2026-11-25T11:53:08.123456+00:00",
    "parent_session_id": null,
    "parent_step": null,
    "event_count": 24,
    "task": "Fix sample_pkg.stats.mean so that the test suite passes."
  }
]
```

One entry per session, oldest first. `task` is `null` for a session without metadata. The
`event_count` is the number of stored events.

## `get_session(store, session_id)`

```json
{
  "session_id": "c9c7b81f571149ab97d781e39071b6dd",
  "created_at": "2026-11-25T11:53:08.123456+00:00",
  "parent_session_id": null,
  "parent_step": null,
  "metadata": {"task": "...", "max_steps": 12, "extra_reads": 0},
  "events": [
    {
      "event_id": "3f2a...",
      "session_id": "c9c7b81f571149ab97d781e39071b6dd",
      "step": 0,
      "type": "session_start",
      "payload": {"metadata": {"task": "...", "max_steps": 12, "extra_reads": 0}},
      "timestamp": "2026-11-25T11:53:08.123456+00:00",
      "parent_step": null,
      "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000",
      "hash": "9ab1..."
    }
  ]
}
```

`events` lists every stored event in step order. Each event has the fields of the core `Event`
model: `event_id`, `session_id`, `step`, `type`, `payload`, `timestamp`, `parent_step`,
`prev_hash`, `hash`. Payloads are already redacted by the core. Raises `SessionNotFoundError` for
an unknown id.

## `replay_summary(store, session_id, *, workspace_root)`

```json
{
  "session_id": "c9c7b81f571149ab97d781e39071b6dd",
  "final": "Divide by len(values) in mean.",
  "replay_counters": {"llm": 0, "read_file": 0, "write_file": 0, "run_tests": 0},
  "matches_recorded": true
}
```

`replay_counters` counts the real calls made during the replay. It must be all 0.
`matches_recorded` is true when the replayed final answer equals the answer stored by the
`final_answer` event.

## `find_bad_edit(store, session_id)`

```json
{"session_id": "c9c7b81f571149ab97d781e39071b6dd", "bad_edit": {"step": 7, "path": "sample_pkg/stats.py"}}
```

When no write is bad, `bad_edit` is `null`:

```json
{"session_id": "...", "bad_edit": null}
```

A bad edit is a `write_file` call after which the next recorded `run_tests` result exits non-zero,
with no other write in between. The verdict comes only from recorded results. `step` is the step
of the `write_file` call event.

## `fork(store, parent_session_id, at_step, *, override=None, use_override=False)`

Requires `use_override=True`. Without it the call raises `ForkNotSupportedError`.

```json
{
  "child_session_id": "5d1e...",
  "diff": {
    "first_divergent_step": 8,
    "kind": "result",
    "differing_steps": [
      {
        "step": 8,
        "kind": "result",
        "a": {"type": "tool_result", "parent_step": 7, "payload": {"name": "write_file", "result": {}}},
        "b": {"type": "tool_result", "parent_step": 7, "payload": {"name": "write_file", "result": {}}}
      }
    ],
    "len_a": 24,
    "len_b": 9
  }
}
```

`child_session_id` is the new session. Its `parent_session_id` and `parent_step` link it to the
parent. `diff` compares the parent with the child, step by step:

- `first_divergent_step`: the first step that differs, or `null`.
- `kind`: `different_tool`, `args`, `result`, `length`, or `null`.
- `differing_steps`: every step that differs. Each has `step`, `kind`, and the `a` and `b` views.
- `len_a` and `len_b`: the event counts of the parent and the child.

The fork replays the parent up to `at_step` and records the call at `at_step` with `override` as
its result. It makes no live call and writes no file. The parent is not changed. `at_step` must
be a `llm_call` or `tool_call` step, otherwise the core raises `InvalidForkPointError`.

## Errors

| Error | Raised when |
|---|---|
| `SessionNotFoundError` (core) | the session id is unknown |
| `InvalidForkPointError` (core) | `at_step` is not a call step of the parent |
| `ForkNotSupportedError` | `fork` is called without `use_override=True` |
| `DivergenceError` (core) | a replay makes a call that differs from the recording |
| `AgentProtocolError` | stored session metadata is missing or incomplete |
