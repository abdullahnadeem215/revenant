// Shapes returned by the revenant-dev API. They match applications/revenant-dev/API.md.

export interface SessionSummary {
  session_id: string;
  created_at: string;
  parent_session_id: string | null;
  parent_step: number | null;
  event_count: number;
  task: string | null;
}

export type EventType =
  | "session_start"
  | "llm_call"
  | "tool_call"
  | "tool_result"
  | "error"
  | "nondeterminism"
  | "final_answer";

export interface StoredEvent {
  event_id: string;
  session_id: string;
  step: number;
  type: EventType;
  payload: Record<string, unknown>;
  timestamp: string;
  parent_step: number | null;
  prev_hash: string;
  hash: string;
}

export interface SessionDetail {
  session_id: string;
  created_at: string;
  parent_session_id: string | null;
  parent_step: number | null;
  metadata: Record<string, unknown>;
  events: StoredEvent[];
}

export interface BadEdit {
  step: number;
  path: string;
}

export interface BadEditResponse {
  session_id: string;
  bad_edit: BadEdit | null;
}
