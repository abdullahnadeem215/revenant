import { cleanup, render, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import badEditFixture from "./fixtures/bad-edit-base.json";
import sessionFixture from "./fixtures/session-base.json";
import { SessionTimeline } from "./SessionTimeline";
import type { BadEditResponse, SessionDetail } from "./types";

const session = sessionFixture as SessionDetail;
const badEdit = badEditFixture as BadEditResponse;

afterEach(() => cleanup());

describe("SessionTimeline", () => {
  it("renders one row per stored event, in step order", () => {
    const { container } = render(
      <SessionTimeline events={session.events} highlightStep={badEdit.bad_edit?.step ?? null} />,
    );
    const rows = container.querySelectorAll("li[data-step]");
    expect(rows).toHaveLength(session.events.length);
    const steps = Array.from(rows).map((row) => Number(row.getAttribute("data-step")));
    expect(steps).toEqual(session.events.map((event) => event.step));
  });

  it("highlights exactly the row of the bad-edit step", () => {
    const step = badEdit.bad_edit?.step;
    expect(step).toBeTypeOf("number");
    const { container } = render(
      <SessionTimeline events={session.events} highlightStep={step ?? null} />,
    );
    const highlighted = container.querySelectorAll('li[data-highlighted="true"]');
    expect(highlighted).toHaveLength(1);
    const row = highlighted[0] as HTMLElement;
    expect(Number(row.getAttribute("data-step"))).toBe(step);
    expect(within(row).getByText("first bad edit")).toBeTruthy();
    // The row is the write_file call that the stored events show at that step.
    const stored = session.events.find((event) => event.step === step);
    expect(stored?.type).toBe("tool_call");
    expect(stored?.payload.name).toBe("write_file");
    expect(within(row).getByText("tool_call")).toBeTruthy();
  });

  it("highlights nothing when there is no bad edit", () => {
    const { container } = render(<SessionTimeline events={session.events} highlightStep={null} />);
    expect(container.querySelectorAll('li[data-highlighted="true"]')).toHaveLength(0);
    expect(container.querySelectorAll(".badge")).toHaveLength(0);
  });
});
