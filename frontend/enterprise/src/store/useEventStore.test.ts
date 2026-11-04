import { beforeEach, describe, expect, it } from "vitest";
import {
  MAX_EVENTS,
  filterEvents,
  selectByEventType,
  selectByLayer,
  selectBySeverity,
  selectLatestByLayer,
  selectNewestFirst,
  useEventStore,
} from "./useEventStore";
import { makeEvent, resetEventStore } from "../test-utils";

describe("useEventStore", () => {
  beforeEach(() => resetEventStore());

  it("starts empty, disconnected and in LIVE mode", () => {
    const s = useEventStore.getState();
    expect(s.events).toHaveLength(0);
    expect(s.isConnected).toBe(false);
    expect(s.mode).toBe("LIVE");
  });

  it("appends events and tracks the last one", () => {
    const evt = makeEvent({ id: 1, event_type: "campaign_proposed" });
    useEventStore.getState().appendEvent(evt);
    const s = useEventStore.getState();
    expect(s.events).toHaveLength(1);
    expect(s.lastEvent?.event_type).toBe("campaign_proposed");
    expect(s.received).toBe(1);
  });

  it("caps the ring buffer at 500 events, keeping the newest", () => {
    const { appendEvent } = useEventStore.getState();
    for (let i = 1; i <= 600; i += 1) appendEvent(makeEvent({ id: i }));
    const { events } = useEventStore.getState();
    expect(events).toHaveLength(MAX_EVENTS);
    expect(events[0].id).toBe(101);
    expect(events[events.length - 1].id).toBe(600);
  });

  it("ignores a duplicate id — the WS snapshot overlaps REST hydration", () => {
    const { appendEvent } = useEventStore.getState();
    appendEvent(makeEvent({ id: 5 }));
    appendEvent(makeEvent({ id: 5 }));
    expect(useEventStore.getState().events).toHaveLength(1);
    expect(useEventStore.getState().received).toBe(1);
  });

  it("tolerates a gapped id sequence — the server drops events for slow clients", () => {
    const { appendEvent } = useEventStore.getState();
    appendEvent(makeEvent({ id: 2 }));
    appendEvent(makeEvent({ id: 57 }));
    expect(useEventStore.getState().events.map((e) => e.id)).toEqual([2, 57]);
    expect(useEventStore.getState().highestId()).toBe(57);
  });

  it("merges a backfill batch in timestamp order without duplicating", () => {
    const base = Date.UTC(2026, 8, 10, 12, 0, 0);
    const at = (s: number) => new Date(base + s * 1000).toISOString();
    useEventStore.getState().appendEvent(makeEvent({ id: 1, ts: at(0) }));
    useEventStore.getState().appendEvent(makeEvent({ id: 9, ts: at(9) }));

    useEventStore.getState().mergeEvents([
      makeEvent({ id: 9, ts: at(9) }), // already held
      makeEvent({ id: 4, ts: at(4) }), // the gap
      makeEvent({ id: 12, ts: at(12) }),
    ]);

    expect(useEventStore.getState().events.map((e) => e.id)).toEqual([1, 4, 9, 12]);
    expect(useEventStore.getState().lastEvent?.id).toBe(12);
  });

  it("reports no highest id when empty", () => {
    expect(useEventStore.getState().highestId()).toBeNull();
  });

  it("clears events", () => {
    useEventStore.getState().appendEvent(makeEvent());
    useEventStore.getState().clearEvents();
    expect(useEventStore.getState().events).toHaveLength(0);
    expect(useEventStore.getState().lastEvent).toBeNull();
  });

  it("switches mode", () => {
    useEventStore.getState().setMode("REPLAY");
    expect(useEventStore.getState().mode).toBe("REPLAY");
  });

  it("disconnect marks the store disconnected", () => {
    useEventStore.setState({ isConnected: true });
    useEventStore.getState().disconnect();
    expect(useEventStore.getState().isConnected).toBe(false);
  });
});

describe("selectors", () => {
  const events = [
    makeEvent({ id: 1, layer: "sensing", event_type: "call_received" }),
    makeEvent({ id: 2, layer: "case", event_type: "case_ingested" }),
    makeEvent({
      id: 3,
      layer: "discovery",
      event_type: "campaign_proposed",
      severity: "critical",
    }),
    makeEvent({ id: 4, layer: "case", event_type: "entity_linked", severity: "warning" }),
  ];

  it("filters by layer", () => {
    expect(selectByLayer(events, "case").map((e) => e.id)).toEqual([2, 4]);
  });

  it("filters by severity", () => {
    expect(selectBySeverity(events, "critical").map((e) => e.id)).toEqual([3]);
  });

  it("filters by event type", () => {
    expect(selectByEventType(events, "case_ingested").map((e) => e.id)).toEqual([2]);
  });

  it("combines filters and limits", () => {
    const out = filterEvents(events, { layers: ["case"], limit: 1 });
    expect(out.map((e) => e.id)).toEqual([4]);
  });

  it("returns newest first for the ticker", () => {
    expect(selectNewestFirst(events).map((e) => e.id)).toEqual([4, 3, 2, 1]);
  });

  it("resolves the latest event per layer", () => {
    const latest = selectLatestByLayer(events);
    expect(latest.case?.id).toBe(4);
    expect(latest.discovery?.id).toBe(3);
    expect(latest.compiler).toBeUndefined();
  });
});
