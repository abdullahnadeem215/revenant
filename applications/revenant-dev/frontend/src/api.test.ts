import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, ApiError, getBadEdit, listSessions } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  it("reads the API at 127.0.0.1 with GET only", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    await listSessions();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${API_BASE}/sessions`);
    expect(API_BASE).toBe("http://127.0.0.1:8000");
    expect(init.method).toBeUndefined();
  });

  it("returns the parsed JSON on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ session_id: "s", bad_edit: null })),
    );
    await expect(getBadEdit("s")).resolves.toEqual({ session_id: "s", bad_edit: null });
  });

  it("turns an error response into ApiError with the API's detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "unknown session" }, 404)),
    );
    const error = await getBadEdit("nope").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe("unknown session");
  });

  it("explains when the API cannot be reached at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await listSessions().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).message).toContain("Cannot reach the API");
  });
});
