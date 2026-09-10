import { useEventStore } from "./store/useEventStore";
import type { Layer, NsEvent, Severity } from "./types/events";

let seq = 0;

export function makeEvent(overrides: Partial<NsEvent> = {}): NsEvent {
  seq += 1;
  return {
    id: overrides.id ?? seq,
    ts: overrides.ts ?? new Date(Date.UTC(2026, 8, 10, 12, 0, seq % 60)).toISOString(),
    layer: (overrides.layer ?? "case") as Layer,
    event_type: overrides.event_type ?? "case_ingested",
    severity: (overrides.severity ?? "info") as Severity,
    payload: overrides.payload ?? { case_number: seq },
    run_id: overrides.run_id ?? "test-run",
  };
}

export function resetEventStore(): void {
  useEventStore.getState().disconnect();
  useEventStore.setState({
    events: [],
    isConnected: false,
    mode: "LIVE",
    received: 0,
    lastEvent: null,
    replaySpeed: 1,
  });
}

/** Push events straight into the store, bypassing any transport. */
export function seedEvents(events: NsEvent[]): void {
  useEventStore.setState({
    events,
    received: events.length,
    lastEvent: events[events.length - 1] ?? null,
  });
}

/** A minimal WebSocket double for LiveEventSource tests. */
export class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  open() {
    this.onopen?.();
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  close() {
    this.closed = true;
    this.onclose?.();
  }

  static reset() {
    MockWebSocket.instances = [];
  }

  static get last(): MockWebSocket | undefined {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}
