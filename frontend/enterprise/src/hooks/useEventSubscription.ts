import { useEffect, useRef } from "react";
import { useEventStore } from "../store/useEventStore";
import type { Layer, NsEvent } from "../types/events";

/**
 * Fire `handler` once per newly arriving ns_event, optionally filtered.
 * Screens use this to re-fetch data when the system actually did something —
 * never on a polling interval.
 */
export function useEventSubscription(
  handler: (event: NsEvent) => void,
  filter?: { layers?: Layer[]; eventTypes?: string[] },
): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  const layersKey = filter?.layers?.join(",") ?? "";
  const typesKey = filter?.eventTypes?.join(",") ?? "";

  useEffect(() => {
    const layers = layersKey ? (layersKey.split(",") as Layer[]) : null;
    const types = typesKey ? typesKey.split(",") : null;

    return useEventStore.subscribe((state, prev) => {
      const event = state.lastEvent;
      if (!event || event === prev.lastEvent) return;
      if (layers && !layers.includes(event.layer)) return;
      if (types && !types.includes(event.event_type)) return;
      handlerRef.current(event);
    });
  }, [layersKey, typesKey]);
}

export default useEventSubscription;
