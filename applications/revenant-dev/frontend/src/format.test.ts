import { describe, expect, it } from "vitest";

import { formatCreatedAt, summarizeEvent, truncate } from "./format";

describe("summarizeEvent", () => {
  it("names the task of a session_start", () => {
    expect(summarizeEvent("session_start", { metadata: { task: "Fix the mean" } })).toBe(
      "task: Fix the mean",
    );
  });

  it("names the turn of an llm_call", () => {
    expect(
      summarizeEvent("llm_call", { name: "llm", args: { turn: 1, messages: [] }, fingerprint: "f" }),
    ).toBe("llm turn 1");
  });

  it("shows the tool and its arguments for a tool_call", () => {
    const summary = summarizeEvent("tool_call", {
      name: "write_file",
      args: { path: "sample_pkg/stats.py", content: "x" },
    });
    expect(summary.startsWith("write_file ")).toBe(true);
    expect(summary).toContain("sample_pkg/stats.py");
  });

  it("says what the model asked for in an llm tool_result", () => {
    expect(
      summarizeEvent("tool_result", { name: "llm", result: { tool: "run_tests", args: {} } }),
    ).toBe("→ asks for run_tests");
    expect(summarizeEvent("tool_result", { name: "llm", result: { final: "done" } })).toBe(
      "→ final answer",
    );
  });

  it("shows the counts of a run_tests result", () => {
    const summary = summarizeEvent("tool_result", {
      name: "run_tests",
      result: { exit_code: 1, failed: 1 },
    });
    expect(summary).toContain("exit_code");
  });

  it("shows the exception type and message of an error", () => {
    expect(
      summarizeEvent("error", {
        name: "read_file",
        exc_type: "revenant_dev.errors.ToolError",
        message: "no such file",
      }),
    ).toBe("revenant_dev.errors.ToolError: no such file");
  });

  it("shows the answer of a final_answer", () => {
    expect(summarizeEvent("final_answer", { value: { answer: "done" } })).toBe("answer: done");
  });

  it("falls back to the payload's JSON for an unknown type", () => {
    expect(summarizeEvent("something_new", { a: 1 })).toBe('{"a":1}');
  });
});

describe("truncate", () => {
  it("cuts long text to 140 characters and ends with an ellipsis", () => {
    const cut = truncate("x".repeat(200));
    expect(cut).toHaveLength(140);
    expect(cut.endsWith("…")).toBe(true);
  });

  it("leaves short text alone", () => {
    expect(truncate("short")).toBe("short");
  });
});

describe("formatCreatedAt", () => {
  it("returns the raw text when the timestamp does not parse", () => {
    expect(formatCreatedAt("not a date")).toBe("not a date");
  });

  it("formats a valid ISO timestamp", () => {
    const iso = "2026-11-25T16:31:44.675462+00:00";
    expect(formatCreatedAt(iso)).not.toBe(iso);
  });
});
