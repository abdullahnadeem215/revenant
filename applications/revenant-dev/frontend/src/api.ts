import type { BadEditResponse, SessionDetail, SessionSummary } from "./types";

// The API binds 127.0.0.1 only, and its CORS list allows the Vite dev server on port 5173.
export const API_BASE = "http://127.0.0.1:8000";

/** Raised for every failed call. `status` is 0 when the API cannot be reached at all. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${API_BASE}. Is the server running?`);
  }
  if (!response.ok) {
    let detail = response.statusText || `HTTP ${response.status}`;
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null && "detail" in body) {
        const value = (body as { detail: unknown }).detail;
        if (typeof value === "string") {
          detail = value;
        }
      }
    } catch {
      // The body is not JSON. Keep the status text.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

/** GET /sessions */
export function listSessions(): Promise<SessionSummary[]> {
  return getJson<SessionSummary[]>("/sessions");
}

/** GET /sessions/{session_id} */
export function getSession(sessionId: string): Promise<SessionDetail> {
  return getJson<SessionDetail>(`/sessions/${encodeURIComponent(sessionId)}`);
}

/** GET /sessions/{session_id}/bad-edit */
export function getBadEdit(sessionId: string): Promise<BadEditResponse> {
  return getJson<BadEditResponse>(`/sessions/${encodeURIComponent(sessionId)}/bad-edit`);
}
