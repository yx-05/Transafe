/**
 * API response envelopes for /enterprise/*.
 * Paths follow 01_upgrade_plan.md §13 exactly.
 */

import type {
  ArtifactGroup,
  CampaignSummary,
  CaseSummary,
  GraphData,
} from "./campaign";
import type { Layer } from "./events";

export interface OverviewMetric {
  label: string;
  before_value: number;
  after_value: number;
  unit: string;
  /** lower_is_better drives the bar direction on Screen A */
  lower_is_better: boolean;
}

export interface OverviewResponse {
  counters: {
    cases: number;
    open_cases: number;
    unrecognised: number;
    campaigns: number;
    core_version: number;
    exposure_rm: number;
  };
  metrics: OverviewMetric[];
  mode: "LIVE" | "REPLAY";
}

/** GET /enterprise/cases — ?limit&offset&state&campaign_id */
export interface CaseFilters {
  limit?: number;
  offset?: number;
  state?: string;
  campaign_id?: string;
}

/** GET /enterprise/events — ?limit&layer&run_id&since_id */
export interface EventQuery {
  limit?: number;
  layer?: Layer;
  run_id?: string;
  /** Backfill everything newer than this id after a drop or reconnect. */
  since_id?: number | null;
}

export interface CasesResponse {
  cases: CaseSummary[];
  total: number;
}

export interface CampaignsResponse {
  campaigns: CampaignSummary[];
}

export interface ArtifactsResponse {
  artifacts: ArtifactGroup[];
}

export interface EvalVariantResult {
  variant_id: string;
  is_scam: boolean;
  detected: boolean;
  score: number | null;
  latency_ms: number | null;
}

export interface EvalRunSummary {
  run_id: string;
  label: string;
  started_at: string;
  detected: number;
  total: number;
  false_positives: number;
  fp_total: number;
  mean_latency_ms: number | null;
  artifact_ver: Record<string, number>;
}

export interface EvalComparison {
  before: EvalRunSummary | null;
  after: EvalRunSummary | null;
  /** per-variant detail, optional */
  before_results?: EvalVariantResult[];
  after_results?: EvalVariantResult[];
}

export interface EvalRunResponse {
  run_id: string;
  label: string;
  status: string;
}

/**
 * Display hint only — NOT the role vocabulary.
 *
 * The authoritative list is `ROLE_VISIBILITY` in `backend/mcp/redaction.py`,
 * surfaced as the `roles` key of `GET /enterprise/mcp/log`. This union is a
 * stale subset (it omits `fraud_ops`, `auditor`, `partner_bank` and
 * `external_researcher`). Nothing access-related may depend on it: use the
 * server's `roles` list, so an unrecognised role is unsendable by
 * construction rather than something the client has to validate.
 */
export type McpRole = "legal" | "compliance" | "customer_service" | "analyst" | "public";

export interface McpLogRow {
  id: number;
  ts: string;
  caller: string;
  /** The role the logged call ran under — free-form, server-supplied. */
  role: string;
  tool: string;
  params: Record<string, unknown> | null;
  latency_ms: number | null;
  citations: string[] | null;
  /**
   * Categories the reader did NOT receive, computed server-side by
   * `redacted_categories_for`. Absent means the lens is unknown — render
   * least privilege, never "nothing was redacted".
   */
  redacted_fields?: string[];
  /** Present on projected rows: how many citations existed before withholding. */
  citation_count?: number;
  outcome?: string | null;
}

export interface McpLogResponse {
  entries: McpLogRow[];
  count?: number;
  /** Authoritative role vocabulary, `sorted(ROLE_VISIBILITY)`. Drives the switcher. */
  roles?: string[];
}

export interface DemoScenarioResponse {
  run_id: string;
  mode: "live" | "replay";
  speed: number;
  event_count?: number;
}

export type GraphResponse = GraphData;

export interface ActionResponse {
  ok: boolean;
  message?: string;
}
