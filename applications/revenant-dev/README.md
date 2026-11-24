# revenant-dev

A demo coding agent built on revenant-core. It edits a small sample package, records the run, and replays it. Backend only: no UI, no network, no real model.

Status: spec approved, no code yet. The full README (how to run, fork limits, Limits section) is written in Phase 5 of `.kiro/specs/revenant-dev/tasks.md`.

## Terms

**Bad edit.** A `write_file` call after which the next recorded `run_tests` result exits non-zero, with no other write in between. The verdict comes only from recorded results.

A bad edit does not mean the agent behaved wrongly in general. It is a narrow, mechanical label: the write was followed by a failing test run. A write that the agent fixed later is still a bad edit if the `run_tests` right after it failed. A write with no `run_tests` before the next write is not a bad edit.
