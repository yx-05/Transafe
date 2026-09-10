/**
 * Domain types — campaigns, cases, entities, artifacts.
 * Mirrors the SQL schema in 01_upgrade_plan.md §12.
 */

export type EntityType = "PHONE" | "ACCOUNT" | "URL" | "DOMAIN" | "NAME" | "OTHER";

export type CampaignStatus =
  | "CANDIDATE"
  | "PENDING_VALIDATION"
  | "APPROVED"
  | "ACTIVE"
  | "SUPERSEDED"
  | "ARCHIVED"
  | "REJECTED";

export type ArtifactTier = "core" | "pack";
export type ArtifactStatus = "DRAFT" | "PUBLISHED" | "ROLLED_BACK";
export type DiscoveryState = "NORMAL" | "OBSERVED" | "CLUSTERED";

export interface Entity {
  id: string;
  entity_type: EntityType;
  value_raw: string;
  value_norm: string;
  case_count: number;
  first_seen?: string;
  last_seen?: string;
}

export interface TranscriptLine {
  /** mm:ss offset from call start */
  t: string;
  speaker: "CALLER" | "USER" | "AI" | "SYSTEM";
  text: string;
  /** 0-100 risk contribution for this utterance; null when not scored */
  score: number | null;
  /** phrases on THIS line flagged novel by the MO extractor */
  novel_phrases?: string[];
}

export interface MoFingerprint {
  impersonates: string | null;
  pretext: string | null;
  phases: string[];
  money_ask_at: string | null;
  channel?: string | null;
  language?: string | null;
}

export interface TraceStep {
  name: string;
  duration_ms: number;
  detail?: string | null;
}

export interface CaseSummary {
  id: string;
  case_number: number;
  tier: string;
  scam_type: string;
  risk_score: number;
  risk_label: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  created_at: string;
  campaign_id: string | null;
  campaign_name: string | null;
  discovery_state: DiscoveryState;
}

export interface CaseDetail extends CaseSummary {
  transcript: TranscriptLine[];
  mo: MoFingerprint | null;
  narrative: string | null;
  entities: Entity[];
  trace: TraceStep[];
}

export interface CampaignSummary {
  id: string;
  code: string;
  name: string;
  status: CampaignStatus;
  confidence: number;
  case_count: number;
  customer_count: number;
  first_seen: string | null;
  last_seen: string | null;
  span_minutes: number | null;
}

/** Deterministic, computed. Rendered on the LEFT of the validation console. */
export interface EvidenceItem {
  label: string;
  value: string;
  passed: boolean;
}

/** LLM-generated. Rendered on the RIGHT of the validation console. */
export interface CampaignHypothesis {
  name: string;
  mo_summary: string;
  novel_indicators: string[];
}

export interface ProposedArtifact {
  name: string;
  tier: ArtifactTier;
  target_agent: string;
  version: number;
  note?: string | null;
  source_campaigns?: string[];
}

export interface CampaignDetail extends CampaignSummary {
  evidence: EvidenceItem[];
  hypothesis: CampaignHypothesis;
  proposed_artifacts: ProposedArtifact[];
  case_ids: string[];
  mini_graph?: GraphData | null;
}

export interface ArtifactEffectiveness {
  eval_run_id: string | null;
  detected: number;
  total: number;
  fp: number;
  fp_total: number;
  measured_at: string | null;
}

export interface ArtifactVersion {
  id: string;
  name: string;
  tier: ArtifactTier;
  artifact_type: string;
  target_agent: string;
  version: number;
  status: ArtifactStatus;
  created_at: string;
  created_by: string;
  approved_by: string | null;
  source_campaigns: string[];
  campaign_id: string | null;
  effectiveness: ArtifactEffectiveness | null;
}

export interface ArtifactGroup {
  name: string;
  tier: ArtifactTier;
  target_agent: string;
  latest_version: number;
  versions: ArtifactVersion[];
}

export interface ArtifactDetail extends ArtifactVersion {
  content: string;
  previous_content: string | null;
  previous_version: number | null;
}

/* ── Graph ────────────────────────────────────────────────────────────── */

export type GraphNodeKind = "case" | "entity" | "campaign";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  entity_type?: EntityType;
  campaign_id?: string | null;
  risk_score?: number;
  case_count?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  kind: "case-entity" | "case-case" | "campaign-case";
  weight: number;
  /** Why this edge exists — shown on hover. */
  reason: string;
  signals?: Record<string, unknown>;
  case_refs?: string[];
}

export interface CampaignHull {
  campaign_id: string;
  code: string;
  name: string;
  node_ids: string[];
  colour?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  hulls: CampaignHull[];
}
