import { useEffect, useState } from "react";

import { SessionListScreen } from "./SessionListScreen";
import { SessionScreen } from "./SessionScreen";

export type Route = { name: "list" } | { name: "session"; sessionId: string };

/** Hash routes: "#/" is the list, "#/sessions/{id}" is one session. */
export function parseRoute(hash: string): Route {
  const match = /^#\/sessions\/(.+)$/.exec(hash);
  if (match) {
    try {
      return { name: "session", sessionId: decodeURIComponent(match[1]) };
    } catch {
      return { name: "list" };
    }
  }
  return { name: "list" };
}

export function App() {
  const [hash, setHash] = useState(() => window.location.hash);

  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const route = parseRoute(hash);
  return (
    <div className="app">
      <header className="app-header">
        <a className="brand" href="#/">
          revenant-dev
        </a>
        <span className="subtitle">sessions (read-only)</span>
      </header>
      <main>
        {route.name === "list" ? (
          <SessionListScreen />
        ) : (
          <SessionScreen key={route.sessionId} sessionId={route.sessionId} />
        )}
      </main>
    </div>
  );
}
