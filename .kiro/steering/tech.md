# Tech

- Python 3.11+, Pydantic v2, stdlib sqlite3, pytest, pytest-asyncio, hypothesis, mypy --strict, ruff.
- No network access, no third-party LLM SDKs, no web frameworks.
- Fully typed. All code must pass mypy --strict and ruff.
- The trace store is an append-only SQLite store behind a Protocol.
- One canonical_json() function is used everywhere for serialization/hashing.
