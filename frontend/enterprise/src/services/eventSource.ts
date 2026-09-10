/**
 * Event source abstraction — the ONLY difference between LIVE and REPLAY.
 *
 * Same UI, same event schema, same store. LIVE opens the WebSocket at
 * /enterprise/ws/events; REPLAY re-emits a recorded run at its recorded
 * relative timestamps. Neither ever fabricates an event.
 *
 * Wire protocol (backend B0):
 *   on connect  {"type":"snapshot","events":[...oldest-first...],"count":n}
 *   then        {"type":"event","event":{...ns_event...}}
 *   when idle   {"type":"heartbeat"}                     ← NOT an event
 *
 * Two consequences we handle explicitly:
 *  - A heartbeat must never reach the store. It is a liveness signal, not
 *    something the system did, and the whole console is built on the promise
 *    that motion means work happened.
 *  - Slow clients get events dropped server-side, so ids are not gap-free.
 *    We track the highest id seen and hand it to `onResync` after a reconnect
 *    so the store can backfill over REST with `since_id`.
 */

import { isNsEvent, type NsEvent } from "../types/events";

export type EventHandler = (event: NsEvent) => void;
export type StatusHandler = (connected: boolean) => void;
/** Called after a re-open with the highest id seen before the drop. */
export type ResyncHandler = (sinceId: number | null) => void;

export interface EventSource {
  connect: (
    onEvent: EventHandler,
    onStatus?: StatusHandler,
    onResync?: ResyncHandler,
  ) => void;
  disconnect: () => void;
}

/** How much history the server replays on connect. */
export const DEFAULT_BACKLOG = 25;

export function defaultWsUrl(backlog: number = DEFAULT_BACKLOG): string {
  const envUrl =
    typeof import.meta !== "undefined"
      ? (import.meta.env?.VITE_WS_URL as string | undefined)
      : undefined;
  const base =
    envUrl ??
    (typeof window === "undefined"
      ? "ws://localhost:8000/enterprise/ws/events"
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${
          window.location.host
        }/enterprise/ws/events`);
  return base.includes("?") ? base : `${base}?backlog=${backlog}`;
}

/** LIVE — the booth. Real pipeline, real WebSocket, auto-reconnecting. */
export class LiveEventSource implements EventSource {
  private ws: WebSocket | null = null;
  private onEvent: EventHandler | null = null;
  private onStatus: StatusHandler | null = null;
  private onResync: ResyncHandler | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  private closedByUs = false;
  private opened = false;
  private lastEventId: number | null = null;

  constructor(
    private readonly url: string = defaultWsUrl(),
    private readonly maxAttempts = 20,
  ) {}

  /** Highest ns_event id seen on this socket — the `since_id` for backfill. */
  get highestId(): number | null {
    return this.lastEventId;
  }

  connect(
    onEvent: EventHandler,
    onStatus?: StatusHandler,
    onResync?: ResyncHandler,
  ): void {
    this.onEvent = onEvent;
    this.onStatus = onStatus ?? null;
    this.onResync = onResync ?? null;
    this.closedByUs = false;
    this.open();
  }

  private emit(candidate: unknown): void {
    if (!isNsEvent(candidate)) return;
    if (this.lastEventId === null || candidate.id > this.lastEventId) {
      this.lastEventId = candidate.id;
    }
    this.onEvent?.(candidate);
  }

  private handleFrame(parsed: unknown): void {
    // Batched array of bare events.
    if (Array.isArray(parsed)) {
      for (const item of parsed) this.emit(item);
      return;
    }
    if (typeof parsed !== "object" || parsed === null) return;

    const frame = parsed as { type?: unknown; event?: unknown; events?: unknown };
    switch (frame.type) {
      case "heartbeat":
        // Liveness only. Deliberately not forwarded.
        return;
      case "snapshot":
        for (const item of Array.isArray(frame.events) ? frame.events : []) {
          this.emit(item);
        }
        return;
      case "event":
        this.emit(frame.event);
        return;
      default:
        // Tolerate a bare ns_event with no envelope.
        this.emit(parsed);
    }
  }

  private open(): void {
    if (typeof WebSocket === "undefined") return;
    const reopening = this.opened;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.attempts = 0;
      this.opened = true;
      this.onStatus?.(true);
      // Events may have been dropped while we were away; ask for the gap.
      if (reopening) this.onResync?.(this.lastEventId);
    };

    ws.onmessage = (e: MessageEvent) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(e.data));
      } catch {
        return;
      }
      this.handleFrame(parsed);
    };

    ws.onerror = () => {
      this.onStatus?.(false);
    };

    ws.onclose = () => {
      this.onStatus?.(false);
      if (!this.closedByUs) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.closedByUs || this.attempts >= this.maxAttempts) return;
    const delay = Math.min(500 * 2 ** this.attempts, 10_000);
    this.attempts += 1;
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  }

  disconnect(): void {
    this.closedByUs = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    try {
      this.ws?.close();
    } catch {
      /* jsdom sockets can throw on close; nothing to do */
    }
    this.ws = null;
    this.onStatus?.(false);
  }
}

/**
 * REPLAY — the timed pitch.
 * Streams a recorded run (fetched from GET /enterprise/events?run_id=…),
 * preserving the recorded gaps between events divided by `speed`. The
 * recording is real: it came out of a real LIVE run.
 */
export class ReplayEventSource implements EventSource {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(
    private readonly events: NsEvent[],
    private readonly speed: number = 1,
  ) {}

  connect(onEvent: EventHandler, onStatus?: StatusHandler): void {
    this.stopped = false;
    onStatus?.(true);
    if (this.events.length === 0) {
      onStatus?.(false);
      return;
    }

    let index = 0;
    const playNext = () => {
      if (this.stopped || index >= this.events.length) return;
      onEvent(this.events[index]);
      index += 1;
      const next = this.events[index];
      if (!next) {
        onStatus?.(false);
        return;
      }
      const prev = this.events[index - 1];
      const gap =
        (new Date(next.ts).getTime() - new Date(prev.ts).getTime()) /
        (this.speed || 1);
      const delay = Number.isFinite(gap) ? Math.max(gap, 40) : 200;
      this.timer = setTimeout(playNext, delay);
    };

    playNext();
  }

  disconnect(): void {
    this.stopped = true;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
