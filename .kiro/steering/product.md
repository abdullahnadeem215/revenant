# Product

- Revenant is a reusable core that records AI agent sessions as ordered events and replays them deterministically (strict replay, fork from a step, divergence detection, session diffing).
- The core is domain-independent: it knows nothing about files, refunds, or any specific agent.
- "Deterministic" means replaying RECORDED outputs, never re-running a model.
- Later apps (DEV debugging, QA regression testing) will be built on the core, but they are out of scope now.
