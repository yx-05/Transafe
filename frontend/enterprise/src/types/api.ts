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
  /**
   * The backend's own statement of what the two halves are measuring, rendered
   * verbatim beside the bar. `null` when it did not supply one.
   *
   * Not decoration. `before`/`after` here are two cohorts of a campaign's own
   * member cases — split on whether the case was ingested before its campaign
   * existed — and *not* a "before TranSafe" industry baseline, which nothing in
   * this system measures. Without this sentence on screen the honest number
   * carries a dishonest frame.
   */
  basis: string | null;
  /**
   * How many cases each half's median was computed over. `null` when the
   * backend did not say.
   *
   * Strength of claim, not decoration: two bars of equal length can rest on 2
   * cases or on 40 and draw identically. The backend labels these diagnostics
   * "so the number can be challenged" — dropping them makes the weak case
   * indistinguishable from the strong one.
   */
  before_sample: number | null;
  after_sample: number | null;
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
  /**
   * Detection on the base wave variants (0–1).
   *
   * Split out from `detected/total` because that blended figure averages the
   * base corpus with the red-team mutations, which hides whether a miss came
   * from an evasion attempt or an ordinary wave variant.
   */
  base_detection?: number;
  /** Detection on the red-team mutations (0–1). */
  redteam_detection?: number;
  /** False-positive rate on the legitimate controls (0–1). */
  noise_fp?: number;
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
 * One blue-team cycle (`POST /eval/adaptation`).
 *
 * Only some keys are typed because the endpoint reports whatever the cycle
 * managed to do: `status` distinguishes "learned something and proved it"
 * (`applied`) from "found no invariant" (`no_proposal`), "no misses" and
 * "below_threshold". A UI that assumed a proposal always exists would claim a
 * lesson that was never learned.
 */
export interface AdaptationRunResponse {
  cycle_id?: string;
  status?: string;
  auto_approved?: boolean;
  confidence?: number;
  adaptation?: {
    pre_detection?: number;
    post_detection?: number;
    delta?: number;
    newly_detected?: string[];
    regressed?: string[];
  } | null;
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
