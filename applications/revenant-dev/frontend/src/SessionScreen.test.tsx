import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getBadEdit, getSession } from "./api";
import badEditFixture from "./fixtures/bad-edit-base.json";
import sessionFixture from "./fixtures/session-base.json";
import { SessionScreen } from "./SessionScreen";
import type { BadEditResponse, SessionDetail } from "./types";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return { ...actual, listSessions: vi.fn(), getSession: vi.fn(), getBadEdit: vi.fn() };
});

const session = sessionFixture as SessionDetail;
const badEdit = badEditFixture as BadEditResponse;

beforeEach(() => {
  vi.mocked(getSession).mockReset();
  vi.mocked(getBadEdit).mockReset();
});

afterEach(() => cleanup());

describe("SessionScreen", () => {
  it("shows the timeline and highlights the bad-edit step returned by the API", async () => {
    vi.mocked(getSession).mockResolvedValue(session);
    vi.mocked(getBadEdit).mockResolvedValue(badEdit);
    const { container } = render(<SessionScreen sessionId={session.session_id} />);

    await waitFor(() => {
      expect(screen.getByText(/First bad edit: step 7/)).toBeTruthy();
    });
    expect(screen.getByText("First bad edit: step 7 (sample_pkg/stats.py).")).toBeTruthy();
    expect(
      screen.getByText(
        "A bad edit is a write_file call after which the next recorded test run failed.",
      ),
    ).toBeTruthy();
    const highlighted = container.querySelectorAll('li[data-highlighted="true"]');
    expect(highlighted).toHaveLength(1);
    expect(highlighted[0].getAttribute("data-step")).toBe("7");
    expect(getSession).toHaveBeenCalledWith(session.session_id);
    expect(getBadEdit).toHaveBeenCalledWith(session.session_id);
  });

  it("says so when the session has no bad edit", async () => {
    vi.mocked(getSession).mockResolvedValue(session);
    vi.mocked(getBadEdit).mockResolvedValue({ session_id: session.session_id, bad_edit: null });
    const { container } = render(<SessionScreen sessionId={session.session_id} />);
    await waitFor(() => {
      expect(screen.getByText(/No bad edit/)).toBeTruthy();
    });
    expect(container.querySelectorAll('li[data-highlighted="true"]')).toHaveLength(0);
  });

  it("shows the API's message for an unknown session", async () => {
    vi.mocked(getSession).mockRejectedValue(new Error("unknown session"));
    vi.mocked(getBadEdit).mockRejectedValue(new Error("unknown session"));
    render(<SessionScreen sessionId="nope" />);
    await waitFor(() => {
      expect(screen.getByText("unknown session")).toBeTruthy();
    });
  });
});
