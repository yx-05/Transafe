import { beforeEach, describe, expect, it, vi } from "vitest";
import { latestRunId, loadReplaySequence } from "./replay";
import { api, markFixtureServed } from "./api";
import { makeEvent } from "../test-utils";
import type { NsEvent } from "../types/events";

/**
 * The defect this file exists to prevent: REPLAY played 2 events out of 100.
 *
 * Branch 2 narrowed the log to `latestRunId(recent)`. Because `emit_event`
 * defaults `run_id` to null and none of the demo's emit sites pass one, the
 * only tagged rows were a couple of eval events — so replay selected those and
 * discarded every campaign, link, sweep and `mcp_call` event.
 *
 * The shape worth keeping in a test is the inversion: with *nothing* tagged the
 * scoping branch was skipped and replay worked, so the bug appeared only once
 * a minority of events carried a run. A fixture where everything is tagged, or
 * nothing is, cannot reproduce it. The mixed case below is the whole point.
 */

vi.mock("./api", () => ({
  api: { getEvents: vi.fn() },
  markFixtureServed: vi.fn(),
}));

const getEvents = vi.mocked(api.getEvents);
const markFixture = vi.mocked(markFixtureServed);

/**
 * An untagged event.
 *
 * Not `makeEvent({ run_id: null })`: the helper does `overrides.run_id ??
 * "test-run"`, and `null` is nullish, so that spelling silently produces a
 * *tagged* event. A fixture built that way would have every row carrying the
 * same run — the one shape in which the old scoping behaved correctly — and
 * the regression test would have passed against the unfixed code.
 */
function untaggedEvent(overrides: Partial<NsEvent> = {}): NsEvent {
  return { ...makeEvent(overrides), run_id: null };
}

/** 100 events of which 8 carry a run_id — the live log's actual shape. */
function mixedLog(): NsEvent[] {
  const tagged = Array.from({ length: 8 }, (_, i) =>
    makeEvent({ id: i + 1, event_type: "eval_started", run_id: "b707dda9" }),
  );
  const untagged = Array.from({ length: 92 }, (_, i) =>
    untaggedEvent({ id: i + 9, event_type: "mcp_call" }),
  );
  return [...tagged, ...untagged];
}

beforeEach(() => {
  getEvents.mockReset();
  markFixture.mockReset();
});

describe("loadReplaySequence", () => {
  it("replays the whole log when only a minority of events carry a run_id", async () => {
    getEvents.mockResolvedValue(mixedLog());

    const played = await loadReplaySequence();

    // The regression: this returned 8 (the tagged eval slice), not 100.
    expect(played).toHaveLength(100);
    expect(played.some((e) => e.event_type === "mcp_call")).toBe(true);
  });

  it("replays the whole log when nothing is tagged", async () => {
    getEvents.mockResolvedValue(
      Array.from({ length: 12 }, (_, i) => untaggedEvent({ id: i + 1 })),
    );

    expect(await loadReplaySequence()).toHaveLength(12);
  });

  it("still narrows to a run when one is asked for explicitly", async () => {
    // Branch 1 is where scoping was ever meaningful: the caller names the run,
    // rather than the module guessing which one the operator meant.
    const scoped = [makeEvent({ id: 1, run_id: "chosen" })];
    getEvents.mockResolvedValueOnce(scoped);

    const played = await loadReplaySequence("chosen");

    expect(getEvents).toHaveBeenCalledWith({ run_id: "chosen", limit: 500 });
    expect(played).toHaveLength(1);
  });

  it("orders by timestamp so the narrative plays in the order it happened", async () => {
    const out = await (async () => {
      getEvents.mockResolvedValue([
        makeEvent({ id: 2, ts: "2026-09-10T12:00:05Z" }),
        makeEvent({ id: 1, ts: "2026-09-10T12:00:01Z" }),
      ]);
      return loadReplaySequence();
    })();

    expect(out.map((e) => e.id)).toEqual([1, 2]);
  });

  it("falls back rather than returning nothing when the log is unreachable", async () => {
    getEvents.mockRejectedValue(new Error("backend down"));

    // The console must never be dead on stage; the bundled fixture is the
    // last resort and is expected to be non-empty.
    expect((await loadReplaySequence()).length).toBeGreaterThan(0);
  });

  it("flags the bundled corpus as a fixture when a healthy backend has an empty log", async () => {
    // The dangerous case is not the unreachable backend — that already trips
    // the fixture flag inside `api.getEvents`. It is the *successful* request
    // that returns nothing: a fresh database, every request 200, no error
    // anywhere. Replay then plays a scripted 100-event narrative — nerve nodes
    // firing, a campaign proposed, artifacts published — that this system
    // never performed, with no badge to say so.
    getEvents.mockResolvedValue([]);

    const played = await loadReplaySequence();

    expect(played.length).toBeGreaterThan(0);
    expect(markFixture).toHaveBeenCalledTimes(1);
    expect(markFixture.mock.calls[0][0]).toMatch(/replay/i);
  });

  it("does not flag a fixture when the log actually had events", async () => {
    getEvents.mockResolvedValue(mixedLog());

    await loadReplaySequence();

    expect(markFixture).not.toHaveBeenCalled();
  });
});

describe("latestRunId", () => {
  it("returns the run of the newest tagged event", () => {
    expect(
      latestRunId([
        makeEvent({ id: 1, run_id: "old" }),
        makeEvent({ id: 2, run_id: "new" }),
        untaggedEvent({ id: 3 }),
      ]),
    ).toBe("new");
  });

  it("returns null when nothing is tagged", () => {
    expect(latestRunId([untaggedEvent()])).toBeNull();
    expect(latestRunId([])).toBeNull();
  });
});
