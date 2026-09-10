/**
 * ns_events — the nervous-system event stream.
 * Mirrors the `ns_events` table in 01_upgrade_plan.md §12.
 * Every animation in this console is driven by one of these. Never a CSS timer.
 */

export const LAYERS = [
  "sensing",
  "case",
  "discovery",
  "compiler",
  "registry",
  "propagation",
  "exposure",
] as const;

export type Layer = (typeof LAYERS)[number];

export const SEVERITIES = ["info", "warning", "critical"] as const;
export type Severity = (typeof SEVERITIES)[number];

export interface NsEvent {
  id: number;
  ts: string;
  layer: Layer;
  event_type: string;
  severity: Severity;
  payload: Record<string, unknown>;
  run_id: string | null;
}

export type Mode = "LIVE" | "REPLAY";

/** Runtime guard — the WebSocket is untrusted input. */
export function isNsEvent(value: unknown): value is NsEvent {
  if (typeof value !== "object" || value === null) return false;
  const e = value as Record<string, unknown>;
  return (
    typeof e.id === "number" &&
    typeof e.ts === "string" &&
    typeof e.layer === "string" &&
    (LAYERS as readonly string[]).includes(e.layer) &&
    typeof e.event_type === "string" &&
    typeof e.severity === "string" &&
    typeof e.payload === "object" &&
    e.payload !== null
  );
}

/** Display glyph per event family — used by the ticker. */
export const EVENT_GLYPHS: Record<string, string> = {
  case_ingested: "▸",
  entity_linked: "⚡",
  case_linked: "⚡",
  mo_extracted: "🧬",
  cluster_formed: "◎",
  campaign_proposed: "🔴",
  campaign_approved: "✅",
  campaign_rejected: "⛔",
  campaign_edited: "✎",
  artifact_compiled: "📦",
  artifact_published: "📦",
  artifact_rolled_back: "↩",
  propagated: "→",
  worker_consumed: "→",
  mcp_call: "🌐",
  eval_completed: "📊",
  unrecognised_pattern: "⚠",
};
