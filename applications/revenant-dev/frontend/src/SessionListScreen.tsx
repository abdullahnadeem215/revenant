import { useEffect, useState } from "react";

import { listSessions } from "./api";
import { formatCreatedAt } from "./format";
import { type LoadState, messageOf } from "./loadState";
import type { SessionSummary } from "./types";

/** Screen 1: every session, newest first, each linking to its detail screen. */
export function SessionListScreen() {
  const [state, setState] = useState<LoadState<SessionSummary[]>>({ status: "loading" });

  useEffect(() => {
    let active = true;
    listSessions()
      .then((data) => {
        if (active) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (active) setState({ status: "error", message: messageOf(error) });
      });
    return () => {
      active = false;
    };
  }, []);

  if (state.status === "loading") {
    return <p className="status">Loading sessions…</p>;
  }
  if (state.status === "error") {
    return <p className="status error">{state.message}</p>;
  }
  if (state.data.length === 0) {
    return <p className="status">No sessions yet.</p>;
  }

  const sessions = [...state.data].reverse();
  return (
    <table className="session-table">
      <thead>
        <tr>
          <th scope="col">Session</th>
          <th scope="col">Created</th>
          <th scope="col">Events</th>
        </tr>
      </thead>
      <tbody>
        {sessions.map((session) => (
          <tr key={session.session_id}>
            <td>
              <a href={`#/sessions/${encodeURIComponent(session.session_id)}`}>
                {session.session_id}
              </a>
            </td>
            <td>{formatCreatedAt(session.created_at)}</td>
            <td>{session.event_count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
