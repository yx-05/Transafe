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
 *  2. NOT YET IMPLEMENTED — campaigns detail, artifacts, eval, mcp, demo.
 *     These 404/throw and fall back to a fixture so screens D–G stay
 *     demoable. Set VITE_DISABLE_MOCKS=true to make that loud instead.
 */

import type {
  ActionResponse,
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

/** Set once any request succeeds; surfaced in the shell badge. */
let backendReachable: boolean | null = null;
export function isBackendReachable(): boolean | null {
  return backendReachable;
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
    console.warn(`[api] ${path} unavailable, serving fixture:`, err);
    return fallback();
  }
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
    fetchJSON<CampaignDetail>(`/campaigns/${id}`, () => mocks.mockCampaignDetail(id)),
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
  editCampaign: (id: string, edits: Record<string, unknown>) =>
    sendJSON<CampaignDetail>(`/campaigns/${id}`, "PATCH", edits, () => ({
      ...mocks.mockCampaignDetail(id),
      ...(edits as Partial<CampaignDetail>),
    })),

  getArtifacts: (tier?: "core" | "pack") =>
    fetchJSON<ArtifactsResponse>(`/artifacts${tier ? `?tier=${tier}` : ""}`, () =>
      mocks.mockArtifacts(tier),
    ),
  getArtifact: (name: string, version?: number | "latest") =>
    fetchJSON<ArtifactDetail>(`/artifacts/${name}/${version ?? "latest"}`, () =>
      mocks.mockArtifactDetail(name, version),
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
