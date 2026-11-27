"""HTTP layer for revenant-dev. Each route calls one function in api.py and returns its value.

Local use only. main() binds 127.0.0.1, and CORS allows the frontend dev server on port 5173
and nothing else. create_app takes the store path and the workspace root, so there is no
module-level app and no file is opened at import time.

Status codes: unknown session 404; fork without use_override, at a non-call step, or with a
non-finite override 400; a replay that diverges from its recording 409 (with step, expected,
actual and reason); a session without agent metadata 409; a bad request body 422 (FastAPI);
any other error 500. Error bodies have a "detail" string.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from revenant import (
    DivergenceError,
    InvalidForkPointError,
    JSONValue,
    PayloadSerializationError,
    SessionNotFoundError,
    SQLiteTraceStore,
)

from revenant_dev.api import find_bad_edit, fork, get_session, list_sessions, replay_summary
from revenant_dev.demo import APP_ROOT
from revenant_dev.errors import AgentProtocolError, ForkNotSupportedError

__all__ = ["FRONTEND_ORIGINS", "HOST", "PORT", "ForkBody", "create_app", "main"]

HOST = "127.0.0.1"
PORT = 8000
FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


class ForkBody(BaseModel):
    at_step: int
    override: JSONValue = None
    use_override: bool = False


@contextmanager
def _open_store(path: Path) -> Iterator[SQLiteTraceStore]:
    """One store per request, opened and closed in the thread that runs the route."""
    store = SQLiteTraceStore(path)
    try:
        yield store
    finally:
        store.close()


def _error(status: int, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": str(exc)})


def create_app(store_path: Path, workspace_root: Path) -> FastAPI:
    app = FastAPI(title="revenant-dev API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(SessionNotFoundError)
    async def _unknown_session(_: Request, exc: SessionNotFoundError) -> JSONResponse:
        return _error(404, exc)

    @app.exception_handler(ForkNotSupportedError)
    async def _fork_not_supported(_: Request, exc: ForkNotSupportedError) -> JSONResponse:
        return _error(400, exc)

    @app.exception_handler(InvalidForkPointError)
    async def _invalid_fork_point(_: Request, exc: InvalidForkPointError) -> JSONResponse:
        return _error(400, exc)

    @app.exception_handler(PayloadSerializationError)
    async def _not_json(_: Request, exc: PayloadSerializationError) -> JSONResponse:
        return _error(400, exc)

    @app.exception_handler(AgentProtocolError)
    async def _no_agent_metadata(_: Request, exc: AgentProtocolError) -> JSONResponse:
        return _error(409, exc)

    @app.exception_handler(DivergenceError)
    async def _diverged(_: Request, exc: DivergenceError) -> JSONResponse:
        body: dict[str, object] = {
            "detail": str(exc),
            "step": exc.step,
            "expected": exc.expected,
            "actual": exc.actual,
            "reason": exc.reason,
        }
        return JSONResponse(status_code=409, content=body)

    @app.get("/sessions")
    def sessions() -> list[dict[str, JSONValue]]:
        with _open_store(store_path) as store:
            return list_sessions(store)

    @app.get("/sessions/{session_id}")
    def session(session_id: str) -> dict[str, JSONValue]:
        with _open_store(store_path) as store:
            return get_session(store, session_id)

    @app.get("/sessions/{session_id}/replay")
    def replay(session_id: str) -> dict[str, JSONValue]:
        with _open_store(store_path) as store:
            return replay_summary(store, session_id, workspace_root=workspace_root)

    @app.get("/sessions/{session_id}/bad-edit")
    def bad_edit(session_id: str) -> dict[str, JSONValue]:
        with _open_store(store_path) as store:
            return find_bad_edit(store, session_id)

    @app.post("/sessions/{session_id}/fork")
    def fork_session(session_id: str, body: ForkBody) -> dict[str, JSONValue]:
        with _open_store(store_path) as store:
            return fork(
                store,
                session_id,
                body.at_step,
                override=body.override,
                use_override=body.use_override,
            )

    return app


def main() -> None:
    """Serve the API on 127.0.0.1 only, using the app's .data folder."""
    data = APP_ROOT / ".data"
    data.mkdir(exist_ok=True)
    app = create_app(data / "sessions.db", data / "workspaces")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
