/**
 * REST client for the /enterprise API surface.
 *
 * Two classes of endpoint live here:
 *
 *  1. IMPLEMENTED by backend B0 — /overview, /cases, /cases/{id}, /graph,
 *     /events, /discovery/run. These go through an adapter in adapters.ts
 *     because the wire shape differs from the view model, and they must render
 *     an honest empty state: the SQL migration is not applied yet, so the
 *     backend degrades per-table to 0/[] rather than 500. An empty result is a
 *     real answer and is NOT replaced with a fixture.
 *
 *  2. FIXTURE-BACKED ON FAILURE — campaigns detail, artifacts, eval, mcp,
 *     demo. Most of these are now implemented server-side; the fixture is a
 *     fallback for a failed request, not a placeholder for a missing route.
 *
 * On any failed request the fixture is served and `isServingFixture()` flips
 * permanently, which the shell renders as a FIXTURE badge. Fabricated data
 * that is indistinguishable from real data on screen is the worst failure
 * mode this client has, so the fallback is never silent. Set
 * VITE_DISABLE_MOCKS=true to turn it into a thrown error instead.
 */

import type {
  ActionResponse,
  AdaptationRunResponse,
  ArtifactsResponse,
  CampaignsResponse,
  CaseFilters,
  CasesResponse,
  DemoScenarioResponse,
  EvalComparison,
  EvalRunResponse,
  EventQuery,
  McpLogResponse,
  OverviewResponse,
  PreflightResponse,
} from "../types/api";
import type {
  ArtifactDetail,
  CampaignDetail,
  CaseDetail,
  GraphData,
} from "../types/campaign";
import type { NsEvent } from "../types/events";
import * as adapt from "./adapters";
import * as mocks from "./mockData";

export const API_BASE = "/enterprise";

const MOCKS_DISABLED =
  typeof import.meta !== "undefined" &&
  import.meta.env?.VITE_DISABLE_MOCKS === "true";

/** Set once any request succeeds. Null until the first request resolves. */
let backendReachable: boolean | null = null;
export function isBackendReachable(): boolean | null {
  return backendReachable;
}

/**
 * Set the first time a fixture is served in place of a real response, and
 * never cleared for the life of the page.
 *
 * Sticky on purpose. A screen that fell back once has shown fabricated data
 * to whoever was watching, and a later successful request does not unshow it.
 * Clearing this on recovery would reproduce the exact failure it exists to
 * expose: an indicator that reads healthy while the thing it reports on
 * already went wrong.
 */
let servedFixture = false;
let lastFixturePath: string | null = null;

/**
 * Listeners notified whenever a fixture is served.
 *
 * Polling this module from a `useEffect` keyed on some unrelated piece of
 * state only catches a fallback that happens to coincide with that state
 * changing. A fixture served by Screen E while the shell's overview sits
 * unchanged went unannounced entirely — fabricated artifact rows on screen,
 * no badge above them. The indicator has to be pushed, not sampled.
 */
type FixtureListener = () => void;
const fixtureListeners = new Set<FixtureListener>();

export function subscribeFixture(listener: FixtureListener): () => void {
  fixtureListeners.add(listener);
  return () => {
    fixtureListeners.delete(listener);
  };
}

export function isServingFixture(): boolean {
  return servedFixture;
}

export function lastFixtureRoute(): string | null {
  return lastFixturePath;
}

/**
 * Record that fabricated data was rendered for `path` and tell anyone
 * watching. Exported because the fixture fallback is not confined to
 * `request` — `loadReplaySequence` can reach its bundled corpus after a
 * perfectly successful request that simply returned an empty log.
 */
export function markFixtureServed(path: string): void {
  const changed = !servedFixture || lastFixturePath !== path;
  servedFixture = true;
  lastFixturePath = path;
  if (changed) for (const listener of fixtureListeners) listener();
}

/** Test-only: reset fixture tracking between cases. */
export function __resetFixtureState(): void {
  servedFixture = false;
  lastFixturePath = null;
  backendReachable = null;
  for (const listener of fixtureListeners) listener();
}

export function toQuery(params?: Record<string, unknown>): string {
  if (!params) return "";
  const pairs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}

async function request<T>(
  path: string,
  init: RequestInit | undefined,
  fallback: () => T,
  adapter?: (raw: unknown) => T,
): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, init);
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    const data: unknown = await res.json();
    backendReachable = true;
    return adapter ? adapter(data) : (data as T);
  } catch (err) {
    backendReachable = false;
    if (MOCKS_DISABLED) throw err;
    markFixtureServed(path);
    console.warn(`[api] ${path} unavailable, serving fixture:`, err);
    return fallback();
  }
}

/**
 * A request with **no fixture fallback**.
 *
 * For endpoints where a fabricated success is worse than a visible failure —
 * a write the operator believes landed but which never reached the database.
 */
async function requestStrict<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  backendReachable = true;
  return (await res.json()) as T;
}

function fetchJSON<T>(
  path: string,
  fallback: () => T,
  adapter?: (raw: unknown) => T,
): Promise<T> {
  return request<T>(path, undefined, fallback, adapter);
}

function sendJSON<T>(
  path: string,
  method: "POST" | "PATCH",
  body: unknown,
  fallback: () => T,
): Promise<T> {
  return request<T>(
    path,
    {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    },
    fallback,
  );
}

export const api = {
  /* ── Implemented by backend B0 ─────────────────────────────────────── */

  getOverview: () =>
    fetchJSON<OverviewResponse>("/overview", mocks.mockOverview, adapt.normaliseOverview),

  getCases: (filters?: CaseFilters) =>
    fetchJSON<CasesResponse>(
      `/cases${toQuery(filters as Record<string, unknown> | undefined)}`,
      mocks.mockCases,
      adapt.normaliseCases,
    ),

  getCase: (id: string) =>
    fetchJSON<CaseDetail>(
      `/cases/${id}`,
      () => mocks.mockCaseDetail(id),
      (raw) => adapt.normaliseCaseDetail(raw, id),
    ),

  getGraph: (params?: { campaign_id?: string; min_score?: number; limit?: number }) =>
    fetchJSON<GraphData>(`/graph${toQuery(params)}`, mocks.mockGraph, adapt.normaliseGraph),

  /**
   * Page-load hydration and gap backfill. `since_id` recovers events dropped
   * while a slow or disconnected client wasn't reading the socket.
   */
  getEvents: (query?: EventQuery) =>
    fetchJSON<NsEvent[]>(
      `/events${toQuery(query as Record<string, unknown> | undefined)}`,
      () => [],
      adapt.normaliseEvents,
    ),

  runDiscovery: () =>
    sendJSON<ActionResponse>("/discovery/run", "POST", {}, () => ({ ok: true })),

  /* ── Fixture-backed until the backend catches up ───────────────────── */

  getCampaigns: () =>
    fetchJSON<CampaignsResponse>(
      "/campaigns",
      mocks.mockCampaigns,
      adapt.normaliseCampaigns,
    ),
  getCampaign: (id: string) =>
    fetchJSON<CampaignDetail>(
      `/campaigns/${id}`,
      () => mocks.mockCampaignDetail(id),
      (raw) => adapt.normaliseCampaignDetail(raw, id),
    ),
  approveCampaign: (id: string) =>
    sendJSON<ActionResponse>(`/campaigns/${id}/approve`, "POST", {}, () => ({
      ok: true,
      message: "approved (fixture)",
    })),
  rejectCampaign: (id: string, reason: string) =>
    sendJSON<ActionResponse>(`/campaigns/${id}/reject`, "POST", { reason }, () => ({
      ok: true,
      message: "rejected (fixture)",
    })),
  /**
   * PATCH /enterprise/campaigns/{id}.
   *
   * The route exists (`router.edit_campaign`) and returns the re-read
   * `CampaignDetail`, not an echo of the request. Accepts `{name?, mo_summary?,
   * indicators?, edited_by}` under `extra="forbid"`, so an unrecognised key is
   * a 422 rather than a 200 with the field silently dropped.
   *
   * Deliberately no fixture fallback: the original merged the operator's edits
   * into a mock campaign and returned it as a saved record, so the console
   * closed the editor on a write that never happened. Every refusal must stay
   * visible — 409 once the campaign leaves an editable status (approval has
   * already compiled and propagated the hypothesis), 422 on an empty or
   * name-blanking body, 404, 503. These surface as a thrown error carrying the
   * status code; the wording is generic, which is a known gap, but the polarity
   * is right: a failed edit never reads as a saved one.
   */
  editCampaign: async (id: string, edits: Record<string, unknown>) =>
    adapt.normaliseCampaignDetail(
      await requestStrict<unknown>(`/campaigns/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(edits),
      }),
      id,
    ),

  getArtifacts: (tier?: "core" | "pack") =>
    fetchJSON<ArtifactsResponse>(
      `/artifacts${tier ? `?tier=${tier}` : ""}`,
      () => mocks.mockArtifacts(tier),
      adapt.normaliseArtifacts,
    ),
  getArtifact: (name: string, version?: number | "latest") =>
    fetchJSON<ArtifactDetail>(
      `/artifacts/${name}/${version ?? "latest"}`,
      () => mocks.mockArtifactDetail(name, version),
      (raw) => adapt.normaliseArtifactDetail(raw, name),
    ),
  rollbackArtifact: (name: string, version?: number) =>
    sendJSON<ActionResponse>(
      `/artifacts/${name}/rollback`,
      "POST",
      version ? { version } : {},
      () => ({ ok: true, message: `rolled back ${name} (fixture)` }),
    ),

  runEval: () =>
    sendJSON<EvalRunResponse>("/eval/run", "POST", {}, () => ({
      run_id: "fixture-run",
      label: "after",
      status: "completed",
    })),
  /**
   * Readiness report. The failure fallback is deliberately NOT a green
   * fixture: a readiness check that can be satisfied by fabricated data is
   * worse than no check, because it is exactly the moment you would trust it.
   */
  getPreflight: () =>
    fetchJSON<PreflightResponse>("/preflight", () => ({
      ok: false,
      summary: "Preflight unavailable — the backend did not answer",
      checks: [],
    })),
  /**
   * The blue-team half: score the corpus, generalise a rule from the misses,
   * auto-approve it if its measured confidence clears the threshold, then
   * re-score. Publishes a new core-skill version, so this is the one button
   * here that changes system state.
   */
  runAdaptation: () =>
    sendJSON<AdaptationRunResponse>("/eval/adaptation", "POST", {}, () => ({
      cycle_id: "fixture-cycle",
      status: "fixture",
    })),
  getLatestEval: () => fetchJSON<EvalComparison>("/eval/latest", mocks.mockEval),

  /**
   * `asRole` is the redaction *lens*, not a filter — it asks "what would this
   * role be allowed to read of this log?" and the server projects every row
   * accordingly. Omit it for the operator view (full `params`/`citations`).
   *
   * Screen G always sends it, so the payload genuinely changes when the
   * selector changes rather than the label alone.
   */
  getMcpLog: (asRole?: string) =>
    fetchJSON<McpLogResponse>(`/mcp/log${toQuery({ as_role: asRole })}`, () =>
      mocks.mockMcpLog(asRole),
    ),

  startScenario: (mode: "live" | "replay", speed = 1) =>
    sendJSON<DemoScenarioResponse>("/demo/scenario", "POST", { mode, speed }, () => ({
      run_id: "fixture-run",
      mode,
      speed,
    })),
  resetDemo: () =>
    sendJSON<ActionResponse>("/demo/reset", "POST", {}, () => ({ ok: true })),
};

export type Api = typeof api;
