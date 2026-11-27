import { describe, expect, it } from "vitest";

import { parseRoute } from "./App";

describe("parseRoute", () => {
  it("maps the empty hash and '#/' to the session list", () => {
    expect(parseRoute("")).toEqual({ name: "list" });
    expect(parseRoute("#/")).toEqual({ name: "list" });
  });

  it("maps '#/sessions/{id}' to that session, decoding the id", () => {
    expect(parseRoute("#/sessions/47a2b7a2e1cd452fadf5a9309112ccd5")).toEqual({
      name: "session",
      sessionId: "47a2b7a2e1cd452fadf5a9309112ccd5",
    });
    expect(parseRoute("#/sessions/a%2Fb")).toEqual({ name: "session", sessionId: "a/b" });
  });

  it("falls back to the list for a malformed session id", () => {
    expect(parseRoute("#/sessions/%E0%A4%A")).toEqual({ name: "list" });
  });
});
