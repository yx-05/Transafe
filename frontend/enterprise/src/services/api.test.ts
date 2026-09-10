import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  api,
  isServingFixture,
  lastFixtureRoute,
  subscribeFixture,
  __resetFixtureState,
} from "./api";

/**
 * These cover the two ways the client can lie to the operator:
 *
 *  1. serving a fixture without telling anyone it did, and
 *  2. reporting a write as saved when the endpoint behind it does not exist.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 405 ? "Method Not Allowed" : "OK",
    json: async () => body,
  } as Response;
}

describe("fixture fallback is announced", () => {
  beforeEach(() => {
    __resetFixtureState();
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    __resetFixtureState();
  });

  it("notifies subscribers when a screen falls back to fabricated data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("connection refused")),
    );

    const seen: (string | null)[] = [];
    const unsubscribe = subscribeFixture(() => seen.push(lastFixtureRoute()));

    // Screen E asks for artifacts. Nothing else in the app is touched — no
    // overview reload, no ns_event. The shell must still learn about it.
    await api.getArtifacts();

    expect(isServingFixture()).toBe(true);
    expect(seen).toEqual(["/artifacts"]);

    unsubscribe();
  });

  it("stops notifying after unsubscribe", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("connection refused")),
    );

    const seen: string[] = [];
    const unsubscribe = subscribeFixture(() => seen.push("hit"));
    unsubscribe();

    await api.getArtifacts();

    expect(seen).toEqual([]);
  });
});

describe("editCampaign", () => {
  beforeEach(() => {
    __resetFixtureState();
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    __resetFixtureState();
  });

  it("rejects instead of fabricating a saved campaign when the server refuses", async () => {
    // 405 stands in for any refusal from the write path — the endpoint now
    // exists and answers 409 (campaign already approved and propagated), 422
    // (empty or name-blanking body) and 404. Whatever the code, the one
    // outcome that must never occur is a resolved promise carrying an edit
    // the server did not store.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, 405));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      api.editCampaign("camp-1", { name: "operator's new name" }),
    ).rejects.toThrow(/405/);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PATCH" });
  });

  it("rejects when the network is down rather than echoing the edit back", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("connection refused")),
    );

    await expect(
      api.editCampaign("camp-1", { name: "operator's new name" }),
    ).rejects.toThrow();
  });

  it("returns the server's record when the endpoint does exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ id: "camp-1", name: "stored" })),
    );

    await expect(api.editCampaign("camp-1", { name: "stored" })).resolves.toMatchObject({
      id: "camp-1",
      name: "stored",
    });
  });
});
