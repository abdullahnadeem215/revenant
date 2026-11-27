const SUMMARY_LIMIT = 140;

/** Shorten text to `limit` characters, ending with an ellipsis when it is cut. */
export function truncate(text: string, limit: number = SUMMARY_LIMIT): string {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function compactJson(value: unknown): string {
  return truncate(JSON.stringify(value) ?? String(value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * One-line summary of an event's payload. Only the fields the backend writes are read, and
 * anything unexpected falls back to the compact JSON of the whole payload.
 */
export function summarizeEvent(type: string, payload: Record<string, unknown>): string {
  switch (type) {
    case "session_start": {
      const metadata = payload.metadata;
      if (isRecord(metadata) && typeof metadata.task === "string") {
        return `task: ${metadata.task}`;
      }
      return "session started";
    }
    case "llm_call": {
      const args = payload.args;
      if (isRecord(args) && typeof args.turn === "number") {
        return `llm turn ${args.turn}`;
      }
      return compactJson(payload);
    }
    case "tool_call": {
      // File tools show their path first. Stored arguments have sorted keys, so "content"
      // would otherwise come before "path" and fill the summary.
      const args = payload.args;
      if (isRecord(args) && typeof args.path === "string") {
        return `${String(payload.name)} ${args.path}`;
      }
      return `${String(payload.name)} ${compactJson(args)}`;
    }
    case "tool_result": {
      const result = payload.result;
      if (payload.name === "llm" && isRecord(result)) {
        if (typeof result.tool === "string") {
          return `→ asks for ${result.tool}`;
        }
        if ("final" in result) {
          return "→ final answer";
        }
      }
      return `→ ${compactJson(result)}`;
    }
    case "error":
      return `${String(payload.exc_type)}: ${String(payload.message)}`;
    case "nondeterminism":
      return `${String(payload.kind)} = ${compactJson(payload.value)}`;
    case "final_answer": {
      const value = payload.value;
      if (isRecord(value) && typeof value.answer === "string") {
        return `answer: ${value.answer}`;
      }
      return compactJson(value);
    }
    default:
      return compactJson(payload);
  }
}

/** Local date and time for an ISO timestamp, or the raw text if it does not parse. */
export function formatCreatedAt(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}
