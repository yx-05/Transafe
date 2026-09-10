import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveEventSource, ReplayEventSource, defaultWsUrl } from "./eventSource";
import { MockWebSocket, makeEvent } from "../test-utils";

describe("ReplayEventSource", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("emits the first event immediately and the rest at recorded gaps", () => {
    const base = Date.UTC(2026, 8, 10, 12, 0, 0);
    const events = [
      makeEvent({ id: 1, ts: new Date(base).toISOString() }),
      makeEvent({ id: 2, ts: new Date(base + 1000).toISOString() }),
      makeEvent({ id: 3, ts: new Date(base + 3000).toISOString() }),
    ];
    const onEvent = vi.fn();
    const source = new ReplayEventSource(events, 1);
    source.connect(onEvent);

    expect(onEvent).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1000);
    expect(onEvent).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(2000);
    expect(onEvent).toHaveBeenCalledTimes(3);
    expect(onEvent.mock.calls.map((c) => c[0].id)).toEqual([1, 2, 3]);
  });

  it("honours the speed multiplier", () => {
    const base = Date.UTC(2026, 8, 10, 12, 0, 0);
    const events = [
      makeEvent({ id: 1, ts: new Date(base).toISOString() }),
      makeEvent({ id: 2, ts: new Date(base + 4000).toISOString() }),
    ];
    const onEvent = vi.fn();
    new ReplayEventSource(events, 4).connect(onEvent);
    vi.advanceTimersByTime(999);
    expect(onEvent).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(2);
    expect(onEvent).toHaveBeenCalledTimes(2);
  });

  it("stops playback on disconnect", () => {
    const base = Date.UTC(2026, 8, 10, 12, 0, 0);
    const events = [
      makeEvent({ id: 1, ts: new Date(base).toISOString() }),
      makeEvent({ id: 2, ts: new Date(base + 1000).toISOString() }),
    ];
    const onEvent = vi.fn();
    const source = new ReplayEventSource(events, 1);
    source.connect(onEvent);
    source.disconnect();
    vi.advanceTimersByTime(5000);
    expect(onEvent).toHaveBeenCalledTimes(1);
  });

  it("reports connected then disconnected around playback", () => {
    const onStatus = vi.fn();
    new ReplayEventSource([makeEvent({ id: 1 })], 1).connect(vi.fn(), onStatus);
    expect(onStatus).toHaveBeenNthCalledWith(1, true);
    expect(onStatus).toHaveBeenLastCalledWith(false);
  });
});

describe("LiveEventSource", () => {
  const original = globalThis.WebSocket;

  beforeEach(() => {
    MockWebSocket.reset();
    (globalThis as any).WebSocket = MockWebSocket;
  });

  afterEach(() => {
    (globalThis as any).WebSocket = original;
  });

  it("delivers ns_events wrapped in the {type:'event'} envelope", () => {
    const onEvent = vi.fn();
    const onStatus = vi.fn();
    const source = new LiveEventSource("ws://test/enterprise/ws/events");
    source.connect(onEvent, onStatus);

    const ws = MockWebSocket.last!;
    ws.open();
    expect(onStatus).toHaveBeenCalledWith(true);

    ws.emit({ type: "event", event: makeEvent({ id: 9, event_type: "artifact_published" }) });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent.mock.calls[0][0].event_type).toBe("artifact_published");
  });

  it("replays the connect snapshot oldest-first", () => {
    const onEvent = vi.fn();
    new LiveEventSource("ws://test").connect(onEvent);
    MockWebSocket.last!.emit({
      type: "snapshot",
      events: [makeEvent({ id: 1 }), makeEvent({ id: 2 }), makeEvent({ id: 3 })],
      count: 3,
    });
    expect(onEvent.mock.calls.map((c) => c[0].id)).toEqual([1, 2, 3]);
  });

  it("never forwards a heartbeat as an event", () => {
    const onEvent = vi.fn();
    const onStatus = vi.fn();
    new LiveEventSource("ws://test").connect(onEvent, onStatus);
    const ws = MockWebSocket.last!;
    ws.open();
    ws.emit({ type: "heartbeat" });
    ws.emit({ type: "heartbeat" });
    expect(onEvent).not.toHaveBeenCalled();
    // and it must not be mistaken for a dropped connection
    expect(onStatus).not.toHaveBeenCalledWith(false);
  });

  it("accepts bare events and batched arrays, and rejects malformed payloads", () => {
    const onEvent = vi.fn();
    new LiveEventSource("ws://test").connect(onEvent);
    const ws = MockWebSocket.last!;
    ws.emit([makeEvent({ id: 1 }), makeEvent({ id: 2 })]);
    ws.emit(makeEvent({ id: 3 }));
    expect(onEvent).toHaveBeenCalledTimes(3);

    ws.emit({ nope: true });
    ws.emit({ id: "not-a-number", ts: "x", layer: "case" });
    ws.emit({ type: "event", event: { garbage: true } });
    expect(onEvent).toHaveBeenCalledTimes(3);
  });

  it("tracks the highest id seen so a gap can be backfilled", () => {
    const source = new LiveEventSource("ws://test");
    source.connect(vi.fn());
    const ws = MockWebSocket.last!;
    ws.emit({ type: "snapshot", events: [makeEvent({ id: 4 }), makeEvent({ id: 11 })] });
    // ids are not gap-free — the server drops events for slow clients
    ws.emit({ type: "event", event: makeEvent({ id: 40 }) });
    expect(source.highestId).toBe(40);
  });

  it("asks for a resync with since_id after reconnecting", () => {
    vi.useFakeTimers();
    const onResync = vi.fn();
    const source = new LiveEventSource("ws://test");
    source.connect(vi.fn(), vi.fn(), onResync);

    const first = MockWebSocket.last!;
    first.open();
    expect(onResync).not.toHaveBeenCalled(); // not on the initial connect

    first.emit({ type: "event", event: makeEvent({ id: 17 }) });
    first.close();
    vi.advanceTimersByTime(600);
    MockWebSocket.last!.open();

    expect(onResync).toHaveBeenCalledWith(17);
    source.disconnect();
    vi.useRealTimers();
  });

  it("requests a backlog on the connect URL", () => {
    new LiveEventSource(defaultWsUrl()).connect(vi.fn());
    expect(MockWebSocket.last!.url).toContain("backlog=25");
  });

  it("does not reconnect after an explicit disconnect", () => {
    const source = new LiveEventSource("ws://test");
    source.connect(vi.fn());
    expect(MockWebSocket.instances).toHaveLength(1);
    source.disconnect();
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("reconnects when the socket drops unexpectedly", () => {
    vi.useFakeTimers();
    const source = new LiveEventSource("ws://test");
    source.connect(vi.fn());
    MockWebSocket.last!.close();
    vi.advanceTimersByTime(600);
    expect(MockWebSocket.instances.length).toBeGreaterThan(1);
    source.disconnect();
    vi.useRealTimers();
  });
});
