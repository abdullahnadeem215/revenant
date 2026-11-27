import { summarizeEvent } from "./format";
import type { StoredEvent } from "./types";

interface SessionTimelineProps {
  events: StoredEvent[];
  /** Step of the first bad edit, or null when there is none. That row is highlighted. */
  highlightStep: number | null;
}

/** Vertical timeline of stored events, in step order. Read-only. */
export function SessionTimeline({ events, highlightStep }: SessionTimelineProps) {
  return (
    <ol className="timeline" aria-label="Event timeline">
      {events.map((event) => {
        const highlighted = highlightStep !== null && event.step === highlightStep;
        return (
          <li
            key={event.event_id}
            className={highlighted ? "timeline-event highlighted" : "timeline-event"}
            data-step={event.step}
            data-highlighted={highlighted ? "true" : "false"}
          >
            <div className="timeline-step">{event.step}</div>
            <div className="timeline-body">
              <div className="timeline-head">
                <span className="timeline-type">{event.type}</span>
                {highlighted && <span className="badge">first bad edit</span>}
              </div>
              <div className="timeline-summary">{summarizeEvent(event.type, event.payload)}</div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
