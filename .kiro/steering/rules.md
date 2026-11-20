# Rules (non-negotiable)

- Replay must NEVER call the real function.
- Divergence must raise DivergenceError. Never guess or skip silently.
- No UPDATE or DELETE on stored events.
- Tests assert on call counters, not printed output.
- No secrets in logs or stored payloads (redaction hook required).
- Fail closed: errors raise typed exceptions, never silently continue.
