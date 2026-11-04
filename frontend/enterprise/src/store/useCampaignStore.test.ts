/**
 * Burst-coalescing tests for the campaign store.
 *
 * The store's refreshers are fired by `useEventSubscription` on every relevant
 * ns_event, never on a timer. A REPLAY run emits ~25 events in a few seconds and
 * each one triggered a refresh of several Supabase-backed endpoints; the burst
 * exhausted the HTTP/2 connection pool, and because the API degrades to *empty*
 * rather than erroring, the console rendered zeroed counters mid-demo.
 *
 * These tests pin the property that makes that impossible: the number of API
 * calls is bounded by the number of *sequential rounds*, not by the number of
 * events.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../services/api", () => ({
  api: {
    getOverview: vi.fn(),
    getCases: vi.fn(),
    getCampaigns: vi.fn(),
    getArtifacts: vi.fn(),
  },
}));

import { api } from "../services/api";
import { useCampaignStore } from "./useCampaignStore";

const emptyOverview = { layers: {}, metrics: [], campaigns: [] } as never;

/** A promise whose resolution this test controls. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("campaign store burst coalescing", () => {
  beforeEach(() => {
    vi.mocked(api.getOverview).mockReset();
    vi.mocked(api.getCases).mockReset();
    vi.mocked(api.getCampaigns).mockReset();
    vi.mocked(api.getArtifacts).mockReset();
  });

  it("collapses a burst of overview refreshes into one in-flight plus one trailing", async () => {
    const first = deferred<never>();
    vi.mocked(api.getOverview)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue(emptyOverview as never);

    // Five events land while the first request is still open.
    const calls = [
      useCampaignStore.getState().loadOverview(),
      useCampaignStore.getState().loadOverview(),
      useCampaignStore.getState().loadOverview(),
      useCampaignStore.getState().loadOverview(),
      useCampaignStore.getState().loadOverview(),
    ];
    first.resolve(emptyOverview as never);
    await Promise.all(calls);

    // Not five. The first request, then exactly one trailing re-run that
    // supersedes the other four.
    expect(vi.mocked(api.getOverview)).toHaveBeenCalledTimes(2);
  });

  it("does not coalesce separate rounds into one", async () => {
    vi.mocked(api.getOverview).mockResolvedValue(emptyOverview as never);

    await useCampaignStore.getState().loadOverview();
    await useCampaignStore.getState().loadOverview();

    // Sequential refreshes are real refreshes: the second must reach the API.
    expect(vi.mocked(api.getOverview)).toHaveBeenCalledTimes(2);
  });

  it("coalesces every screen's refresher, not just the overview", async () => {
    const first = deferred<never>();
    vi.mocked(api.getArtifacts)
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue({ artifacts: [] } as never);

    const calls = [
      useCampaignStore.getState().loadArtifacts("core"),
      useCampaignStore.getState().loadArtifacts("pack"),
      useCampaignStore.getState().loadArtifacts("core"),
    ];
    first.resolve({ artifacts: [] } as never);
    await Promise.all(calls);

    expect(vi.mocked(api.getArtifacts)).toHaveBeenCalledTimes(2);
  });
});
