/**
 * The nervous system, client side.
 *
 * A ring buffer of the last 500 ns_events plus the active event source.
 * Every animated element in the console subscribes here — no component is
 * allowed to invent motion from a timer.
 */

import { create } from "zustand";
import {
  LiveEventSource,
  ReplayEventSource,
  defaultWsUrl,
  type EventSource,
} from "../services/eventSource";
import { api } from "../services/api";
import type { Layer, Mode, NsEvent, Severity } from "../types/events";

export const MAX_EVENTS = 500;

export interface EventStore {
  events: NsEvent[];
  isConnected: boolean;
  mode: Mode;
  /** counts how many events have ever arrived — a monotonic animation key */
  received: number;
  lastEvent: NsEvent | null;
  replaySpeed: number;

  connect: (url?: string) => void;
  disconnect: () => void;
  appendEvent: (event: NsEvent) => void;
  /** Merge a batch (WS snapshot / REST backfill) in id order, ignoring dupes. */
  mergeEvents: (events: NsEvent[]) => void;
  /** Highest id currently held — the `since_id` for a backfill. */
  highestId: () => number | null;
  /** Pull anything newer than what we hold from GET /enterprise/events. */
  hydrate: (limit?: number) => Promise<void>;
  clearEvents: () => void;
  setMode: (mode: Mode) => void;
  setConnected: (connected: boolean) => void;
  /** Tear down the current source and start the one for `mode`. */
  activate: (mode: Mode, options?: { replay?: NsEvent[]; speed?: number }) => void;
}

let activeSource: EventSource | null = null;

function teardown() {
  activeSource?.disconnect();
  activeSource = null;
}

function cap(events: NsEvent[]): NsEvent[] {
  return events.length > MAX_EVENTS ? events.slice(-MAX_EVENTS) : events;
}

export const useEventStore = create<EventStore>((set, get) => ({
  events: [],
  isConnected: false,
  mode: "LIVE",
  received: 0,
  lastEvent: null,
  replaySpeed: 1,

  connect: (url?: string) => {
    teardown();
    const source = new LiveEventSource(url ?? defaultWsUrl());
    activeSource = source;
    source.connect(
      (event) => get().appendEvent(event),
      (connected) => set({ isConnected: connected }),
      // Slow clients get events dropped server-side, so a reconnect is not
      // enough — backfill the gap over REST before trusting the stream again.
      (sinceId) => {
        void api
          .getEvents({ since_id: sinceId ?? get().highestId(), limit: MAX_EVENTS })
          .then((missed) => get().mergeEvents(missed))
          .catch(() => {
            /* the socket is live again; a failed backfill is not fatal */
          });
      },
    );
  },

  disconnect: () => {
    teardown();
    set({ isConnected: false });
  },

  appendEvent: (event: NsEvent) =>
    set((state) => {
      // ids are not gap-free and the WS snapshot overlaps REST hydration.
      if (state.events.some((e) => e.id === event.id)) return state;
      return {
        events: cap([...state.events, event]),
        received: state.received + 1,
        lastEvent: event,
      };
    }),

  mergeEvents: (incoming: NsEvent[]) =>
    set((state) => {
      const seen = new Set(state.events.map((e) => e.id));
      const fresh = incoming.filter((e) => !seen.has(e.id));
      if (fresh.length === 0) return state;
      const merged = cap(
        [...state.events, ...fresh].sort(
          (a, b) =>
            new Date(a.ts).getTime() - new Date(b.ts).getTime() || a.id - b.id,
        ),
      );
      return {
        events: merged,
        received: state.received + fresh.length,
        lastEvent: merged[merged.length - 1] ?? state.lastEvent,
      };
    }),

  highestId: () => {
    const { events } = get();
    return events.length ? Math.max(...events.map((e) => e.id)) : null;
  },

  hydrate: async (limit = 100) => {
    const events = await api.getEvents({
      since_id: get().highestId(),
      limit,
    });
    get().mergeEvents(events);
  },

  clearEvents: () => set({ events: [], received: 0, lastEvent: null }),

  setMode: (mode: Mode) => set({ mode }),

  setConnected: (isConnected: boolean) => set({ isConnected }),

  activate: (mode, options) => {
    teardown();
    set({ mode, replaySpeed: options?.speed ?? get().replaySpeed });

    if (mode === "REPLAY") {
      const recorded = options?.replay ?? [];
      const source = new ReplayEventSource(recorded, options?.speed ?? 1);
      activeSource = source;
      source.connect(
        (event) => get().appendEvent(event),
        (connected) => set({ isConnected: connected }),
      );
      return;
    }

    get().connect();
  },
}));

/* ── Selectors ─────────────────────────────────────────────────────────── */

export interface EventFilter {
  layers?: Layer[];
  severities?: Severity[];
  eventTypes?: string[];
  runId?: string | null;
  limit?: number;
}

export function filterEvents(events: NsEvent[], filter: EventFilter = {}): NsEvent[] {
  const { layers, severities, eventTypes, runId, limit } = filter;
  let out = events;
  if (layers?.length) out = out.filter((e) => layers.includes(e.layer));
  if (severities?.length) out = out.filter((e) => severities.includes(e.severity));
  if (eventTypes?.length) out = out.filter((e) => eventTypes.includes(e.event_type));
  if (runId !== undefined && runId !== null) out = out.filter((e) => e.run_id === runId);
  if (limit !== undefined) out = out.slice(-limit);
  return out;
}

/** Newest first — what the ticker renders. */
export function selectNewestFirst(events: NsEvent[], filter?: EventFilter): NsEvent[] {
  return [...filterEvents(events, filter)].reverse();
}

export function selectByLayer(events: NsEvent[], layer: Layer): NsEvent[] {
  return filterEvents(events, { layers: [layer] });
}

export function selectBySeverity(events: NsEvent[], severity: Severity): NsEvent[] {
  return filterEvents(events, { severities: [severity] });
}

export function selectByEventType(events: NsEvent[], eventType: string): NsEvent[] {
  return filterEvents(events, { eventTypes: [eventType] });
}

/** Most recent event per layer — drives the nerve-map pulses. */
export function selectLatestByLayer(events: NsEvent[]): Partial<Record<Layer, NsEvent>> {
  const latest: Partial<Record<Layer, NsEvent>> = {};
  for (const evt of events) {
    const current = latest[evt.layer];
    if (!current || evt.id >= current.id) latest[evt.layer] = evt;
  }
  return latest;
}
