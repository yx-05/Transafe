/**
 * Screen A left panel — the live ns_event ticker.
 * Also exported as `EventTicker` (shared component name).
 *
 * Rows appear because an event arrived. Nothing here is on a timer.
 */

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { selectNewestFirst, useEventStore } from "../store/useEventStore";
import { LAYERS, SEVERITIES, type Layer, type Severity } from "../types/events";
import { clockTime, describeEvent, glyphFor } from "../lib/format";

interface Props {
  limit?: number;
  showFilters?: boolean;
  layers?: Layer[];
  title?: string;
}

export function LiveEventFeed({
  limit = 200,
  showFilters = true,
  layers,
  title = "LIVE EVENT FEED",
}: Props) {
  const events = useEventStore((s) => s.events);
  const [layerFilter, setLayerFilter] = useState<Layer[]>(layers ?? []);
  const [severityFilter, setSeverityFilter] = useState<Severity[]>([]);

  const rows = useMemo(
    () =>
      selectNewestFirst(events, {
        layers: layerFilter.length ? layerFilter : undefined,
        severities: severityFilter.length ? severityFilter : undefined,
      }).slice(0, limit),
    [events, layerFilter, severityFilter, limit],
  );

  const toggleLayer = (l: Layer) =>
    setLayerFilter((cur) => (cur.includes(l) ? cur.filter((x) => x !== l) : [...cur, l]));
  const toggleSeverity = (s: Severity) =>
    setSeverityFilter((cur) =>
      cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s],
    );

  return (
    <div className="panel feed" data-testid="live-event-feed">
      <div className="panel-title">
        {title}
        {showFilters && (
          <div className="ticker-filters">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                type="button"
                className={`chip ${severityFilter.includes(s) ? "on" : ""}`}
                onClick={() => toggleSeverity(s)}
                aria-pressed={severityFilter.includes(s)}
              >
                {s.slice(0, 4).toUpperCase()}
              </button>
            ))}
          </div>
        )}
      </div>

      {showFilters && (
        <div className="ticker-filters" style={{ padding: "6px 10px", flexWrap: "wrap" }}>
          {LAYERS.map((l) => (
            <button
              key={l}
              type="button"
              className={`chip ${layerFilter.includes(l) ? "on" : ""}`}
              onClick={() => toggleLayer(l)}
              aria-pressed={layerFilter.includes(l)}
            >
              {l.toUpperCase()}
            </button>
          ))}
        </div>
      )}

      <div className="panel-body flush">
        {rows.length === 0 ? (
          <p className="ticker-empty">
            waiting for ns_events… nothing is animated until the system does something.
          </p>
        ) : (
          <ul className="ticker-list">
            {rows.map((evt) => (
              <motion.li
                key={evt.id}
                className={`ticker-row severity-${evt.severity}`}
                data-layer={evt.layer}
                data-event-type={evt.event_type}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.18 }}
              >
                <span className="t">{clockTime(evt.ts)}</span>
                <span className="glyph">{glyphFor(evt)}</span>
                <span className="msg">{describeEvent(evt)}</span>
              </motion.li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export const EventTicker = LiveEventFeed;
export default LiveEventFeed;
