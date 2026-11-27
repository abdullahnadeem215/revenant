import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, listSessions } from "./api";
import { SessionListScreen } from "./SessionListScreen";
import sessionsFixture from "./fixtures/sessions.json";
import type { SessionSummary } from "./types";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, listSessions: vi.fn(), getSession: vi.fn(), getBadEdit: vi.fn() };
});

const sessions = sessionsFixture as SessionSummary[];

beforeEach(() => {
  vi.mocked(listSessions).mockReset();
});

afterEach(() => cleanup());

describe("SessionListScreen", () => {
  it("lists every session with its id, created time and event count, newest first", async () => {
    vi.mocked(listSessions).mockResolvedValue(sessions);
    render(<SessionListScreen />);
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(sessions.length);

    const newest = sessions[sessions.length - 1];
    expect(within(rows[0]).getByRole("link").getAttribute("href")).toBe(
      `#/sessions/${newest.session_id}`,
    );
    expect(within(rows[0]).getByText(newest.session_id)).toBeTruthy();
    expect(within(rows[0]).getByText(String(newest.event_count))).toBeTruthy();
    expect(within(rows[0]).getAllByRole("cell")[1].textContent).not.toBe(newest.created_at);
  });

  it("shows the API's message when the list cannot be loaded", async () => {
    vi.mocked(listSessions).mockRejectedValue(
      new ApiError(0, "Cannot reach the API at http://127.0.0.1:8000. Is the server running?"),
    );
    render(<SessionListScreen />);
    await waitFor(() => {
      expect(screen.getByText(/Cannot reach the API/)).toBeTruthy();
    });
  });
});
