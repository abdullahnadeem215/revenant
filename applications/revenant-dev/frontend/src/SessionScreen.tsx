import { useEffect, useState } from "react";

import { getBadEdit, getSession } from "./api";
import { formatCreatedAt } from "./format";
import { type LoadState, messageOf } from "./loadState";
import { SessionTimeline } from "./SessionTimeline";
import type { BadEditResponse, SessionDetail } from "./types";

interface Loaded {
  session: SessionDetail;
  badEdit: BadEditResponse;
}

/** Screen 2: one session as a timeline, with the first bad edit highlighted. Read-only. */
export function SessionScreen({ sessionId }: { sessionId: string }) {
  const [state, setState] = useState<LoadState<Loaded>>({ status: "loading" });

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    Promise.all([getSession(sessionId), getBadEdit(sessionId)])
      .then(([session, badEdit]) => {
        if (active) setState({ status: "ready", data: { session, badEdit } });
      })
      .catch((error: unknown) => {
        if (active) setState({ status: "error", message: messageOf(error) });
      });
    return () => {
      active = false;
    };
  }, [sessionId]);

  return (
    <section>
      <p>
        <a href="#/">← All sessions</a>
      </p>
      {state.status === "loading" && <p className="status">Loading session…</p>}
      {state.status === "error" && <p className="status error">{state.message}</p>}
      {state.status === "ready" && <SessionBody loaded={state.data} />}
    </section>
  );
}

function SessionBody({ loaded }: { loaded: Loaded }) {
  const { session, badEdit } = loaded;
  const bad = badEdit.bad_edit;
  const task = typeof session.metadata.task === "string" ? session.metadata.task : null;

  return (
    <>
      <h1 className="session-id">{session.session_id}</h1>
      <dl className="facts">
        <dt>Created</dt>
        <dd>{formatCreatedAt(session.created_at)}</dd>
        {task !== null && (
          <>
            <dt>Task</dt>
            <dd>{task}</dd>
          </>
        )}
        {session.parent_session_id !== null && (
          <>
            <dt>Forked from</dt>
            <dd>
              <a href={`#/sessions/${encodeURIComponent(session.parent_session_id)}`}>
                {session.parent_session_id}
              </a>{" "}
              at step {session.parent_step}
            </dd>
          </>
        )}
        <dt>Events</dt>
        <dd>{session.events.length}</dd>
      </dl>
      {bad === null ? (
        <p className="banner">No bad edit: no write was followed by a failing test run.</p>
      ) : (
        <>
          <p className="banner warn">
            First bad edit: step {bad.step} ({bad.path}).
          </p>
          <p className="explain">
            A bad edit is a write_file call after which the next recorded test run failed.
          </p>
        </>
      )}
      <SessionTimeline events={session.events} highlightStep={bad?.step ?? null} />
    </>
  );
}
