/**
 * Recorded ns_events for REPLAY mode.
 *
 * The recording is a real LIVE run read back out of the event log:
 *   GET /enterprise/events?run_id=<run>&limit=500
 *
 * If no run_id is given we replay the most recent slice of the log as-is. We
 * deliberately do not narrow it to the newest run present: `run_id` is null on
 * essentially every event the demo produces, so that narrowing dropped the
 * whole narrative and kept a couple of eval rows. See branch 2 below. Same
 * schema as LIVE, so one renderer drives both.
 *
 * Falls back to a bundled fixture only when the log is unreachable or empty,
 * so the console is never dead on stage.
 */

import { api } from "./api";
import { normaliseEvents } from "./adapters";
import type { NsEvent } from "../types/events";
import { mockReplaySequence } from "./mockData";

const LIMIT = 500;

/** Static copies, in case the backend is down entirely. */
const STATIC_SOURCES = ["/replay_sequence.json"];

function byTimestamp(events: NsEvent[]): NsEvent[] {
  return [...events].sort(
    (a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime() || a.id - b.id,
  );
}

/**
 * The run_id of the newest event that has one, or null when none is tagged.
 *
 * No longer used by {@link loadReplaySequence} — see branch 2 for why scoping
 * to it was removed. Kept because it is a correct, tested utility and callers
 * that genuinely want the newest recorded run (rather than the newest slice of
 * the log) should use it rather than re-derive it.
 */
export function latestRunId(events: NsEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i].run_id) return events[i].run_id;
  }
  return null;
}

export async function loadReplaySequence(runId?: string): Promise<NsEvent[]> {
  // 1. A specific recorded run.
  if (runId) {
    const events = await api.getEvents({ run_id: runId, limit: LIMIT });
    if (events.length) return byTimestamp(events);
  }

  // 2. The most recent slice of the log, unscoped.
  //
  // This deliberately does NOT narrow to `latestRunId(recent)`. It used to,
  // and the result was that replay played 2 events out of 100: `emit_event`
  // defaults `run_id` to `None` and 0 of the 38 call sites across
  // `src/enterprise/` and `src/api/enterprise/` pass one, so the only tagged
  // rows in the log are a handful of eval events. Scoping to the newest run
  // therefore selected those and discarded every campaign, link, sweep and
  // `mcp_call` event — the entire demo narrative.
  //
  // The failure inverted the usual expectation: with *nothing* tagged the
  // scoping branch was skipped and all 100 events replayed correctly, so
  // partial tagging was strictly worse than none. That also means tagging the
  // demo flow would not have fixed it — it would have re-broken the MCP audit
  // feed instead, since `_audit` emits from a different path and would not
  // carry the demo's run_id. The scoping can only ever misfire while the emit
  // sites stay untagged, so it is gone rather than corrected.
  //
  // Branch 1 above still serves a deliberately recorded run by id, which is
  // the only case where narrowing was ever meaningful.
  try {
    const recent = byTimestamp(await api.getEvents({ limit: LIMIT }));
    if (recent.length) return recent;
  } catch {
    /* fall through to the static copies */
  }

  // 3. Static copy, then bundled fixture.
  for (const url of STATIC_SOURCES) {
    try {
      const res = await fetch(url);
      if (!res.ok) continue;
      const parsed = normaliseEvents(await res.json());
      if (parsed.length) return byTimestamp(parsed);
    } catch {
      /* try the next source */
    }
  }

  return mockReplaySequence();
}
