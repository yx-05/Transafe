/**
 * Thin façade over the event store's connection lifecycle,
 * matching 05_frontend_spec.md §8.
 */

import { useEventStore } from "../store/useEventStore";
import { defaultWsUrl } from "./eventSource";

export const WS_BASE = defaultWsUrl();

export function connectWebSocket(url: string = WS_BASE): void {
  useEventStore.getState().connect(url);
}

export function disconnectWebSocket(): void {
  useEventStore.getState().disconnect();
}
