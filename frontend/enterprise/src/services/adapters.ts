/**
 * Wire → view-model adapters.
 *
 * The backend (`backend-core`, B0) speaks a slightly different dialect to the
 * one the screens render: `/overview` returns per-layer stat blocks rather than
 * a flat counter strip, and `/graph` calls its edges `edges` not `links`.
 * Rather than bend every component to the wire, we normalise here — one place
 * to change when the contract moves again.
 *
 * Every adapter is total: a missing table (the SQL migration is not applied
 * yet, so read endpoints degrade to 0/[]) yields an empty view model, never a
 * throw and never a fabricated number.
 */

import type { OverviewMetric, OverviewResponse } from "../types/api";
import type {
  CampaignSummary,
  CaseDetail,
  CaseSummary,
  DiscoveryState,
  Entity,
  EntityType,
  GraphData,
  GraphLink,
  GraphNode,
  MoFingerprint,
  TraceStep,
  TranscriptLine,
} from "../types/campaign";
import { isNsEvent, type NsEvent } from "../types/events";

type Dict = Record<string, unknown>;

function dict(value: unknown): Dict {
  return typeof value === "object" && value !== null ? (value as Dict) : {};
}

function arr(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function strOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** First key present with a numeric (or numeric-string) value. */
function num(source: Dict, keys: string[], fallback = 0): number {
  for (const key of keys) {
    const v = source[key];
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) {
      return Number(v);
    }
  }
  return fallback;
}

function numOrNull(source: Dict, keys: string[]): number | null {
  for (const key of keys) {
    const v = source[key];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

/* ── Events ───────────────────────────────────────────────────────────── */

/**
 * `GET /enterprise/events` and the WS snapshot both carry ns_events; accept a
 * bare array or an `{events:[...]}` envelope, and drop anything that fails the
 * runtime guard rather than letting a malformed row animate the console.
 */
export function normaliseEvents(data: unknown): NsEvent[] {
  const envelope = dict(data);
  const raw = Array.isArray(data)
    ? data
    : Array.isArray(envelope.events)
      ? (envelope.events as unknown[])
      : Array.isArray(envelope.recent_events)
        ? (envelope.recent_events as unknown[])
        : [];
  return raw.filter(isNsEvent);
}

/* ── Overview ─────────────────────────────────────────────────────────── */

export interface WireOverview {
  layers?: Dict;
  campaigns?: unknown[];
  recent_events?: unknown[];
  metrics?: unknown[];
  generated_at?: string;
}

function normaliseMetric(value: unknown): OverviewMetric | null {
  const m = dict(value);
  const label = str(m.label);
  if (!label) return null;
  return {
    label,
    before_value: num(m, ["before_value", "before"]),
    after_value: num(m, ["after_value", "after"]),
    unit: str(m.unit),
    lower_is_better: m.lower_is_better !== false,
  };
}

/**
 * `{layers:{sensing,case,discovery,registry}, campaigns[], recent_events[]}`
 * → the flat counter strip in the shell header.
 *
 * Metrics are only rendered if the backend actually measured them. We do not
 * synthesise a before/after pair — an unmeasured claim is worse than a blank.
 */
export function normaliseOverview(data: unknown): OverviewResponse {
  const wire = dict(data) as WireOverview;
  const layers = dict(wire.layers);
  const caseLayer = dict(layers.case);
  const discovery = dict(layers.discovery);
  const registry = dict(layers.registry);
  const sensing = dict(layers.sensing);

  const campaignList = arr(wire.campaigns);

  return {
    counters: {
      cases: num(caseLayer, ["cases", "total", "count", "total_cases"]),
      open_cases: num(caseLayer, ["open", "open_cases", "active"]),
      unrecognised: num(discovery, [
        "unrecognised",
        "unrecognized",
        "unrecognised_cases",
        "observed",
      ]),
      campaigns: num(discovery, ["campaigns", "campaign_count"], campaignList.length),
      core_version: num(registry, ["core_version", "latest_version", "version"]),
      exposure_rm: num(caseLayer, ["exposure_rm", "exposure", "amount_rm"], 0) ||
        num(sensing, ["exposure_rm", "exposure"], 0),
    },
    metrics: arr(wire.metrics)
      .map(normaliseMetric)
      .filter((m): m is OverviewMetric => m !== null),
    mode: str(wire["mode" as keyof WireOverview], "LIVE") === "REPLAY" ? "REPLAY" : "LIVE",
  };
}

/** `recent_events` on the overview payload hydrates the ticker on page load. */
export function overviewEvents(data: unknown): NsEvent[] {
  return normaliseEvents(dict(data).recent_events);
}

/* ── Cases ────────────────────────────────────────────────────────────── */

const RISK_LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;
type RiskLabel = (typeof RISK_LABELS)[number];

// Boundaries MUST match the v1 risk scorer (src/agents/graph_nodes.py: <40 LOW,
// <70 MEDIUM, >=70 HIGH) and backend presenters.risk_label, which adds CRITICAL
// at >=85 as a fourth band above v1's three. Diverging here silently relabels
// the risk engine's own verdict — a case v1 scored MEDIUM must never render HIGH.
function riskLabel(value: unknown, score: number): RiskLabel {
  const raw = str(value).toUpperCase();
  if ((RISK_LABELS as readonly string[]).includes(raw)) return raw as RiskLabel;
  if (score >= 85) return "CRITICAL";
  if (score >= 70) return "HIGH";
  if (score >= 40) return "MEDIUM";
  return "LOW";
}

function discoveryState(value: unknown): DiscoveryState {
  const raw = str(value).toUpperCase();
  return raw === "OBSERVED" || raw === "CLUSTERED" ? raw : "NORMAL";
}

export function normaliseCase(value: unknown): CaseSummary {
  const c = dict(value);
  const campaign = dict(c.campaign);
  const score = num(c, ["risk_score", "score"]);
  return {
    id: str(c.id ?? c.case_id, String(num(c, ["case_number"]))),
    case_number: num(c, ["case_number", "number"]),
    tier: str(c.tier, "—"),
    scam_type: str(c.scam_type ?? c.type, "UNKNOWN"),
    risk_score: score,
    risk_label: riskLabel(c.risk_label, score),
    created_at: str(c.created_at ?? c.ts, ""),
    campaign_id: strOrNull(c.campaign_id ?? campaign.id),
    campaign_name: strOrNull(c.campaign_name ?? campaign.name ?? campaign.code),
    discovery_state: discoveryState(c.discovery_state),
  };
}

export function normaliseCases(data: unknown): { cases: CaseSummary[]; total: number } {
  const wire = dict(data);
  const raw = Array.isArray(data) ? data : arr(wire.cases ?? wire.items ?? wire.results);
  const cases = raw.map(normaliseCase);
  return { cases, total: num(wire, ["total", "count"], cases.length) };
}

function normaliseTranscript(value: unknown): TranscriptLine[] {
  return arr(value).map((line) => {
    const l = dict(line);
    const speaker = str(l.speaker, "CALLER").toUpperCase();
    return {
      t: str(l.t ?? l.time ?? l.offset, "00:00"),
      speaker: (["CALLER", "USER", "AI", "SYSTEM"].includes(speaker)
        ? speaker
        : "CALLER") as TranscriptLine["speaker"],
      text: str(l.text ?? l.content),
      score: numOrNull(l, ["score", "risk_score"]),
      novel_phrases: arr(l.novel_phrases ?? l.novel).filter(
        (p): p is string => typeof p === "string",
      ),
    };
  });
}

function normaliseMo(value: unknown): MoFingerprint | null {
  const mo = dict(value);
  if (Object.keys(mo).length === 0) return null;
  return {
    impersonates: strOrNull(mo.impersonates),
    pretext: strOrNull(mo.pretext),
    phases: arr(mo.phases).filter((p): p is string => typeof p === "string"),
    money_ask_at: strOrNull(mo.money_ask_at),
    channel: strOrNull(mo.channel),
    language: strOrNull(mo.language),
  };
}

const ENTITY_TYPES: EntityType[] = [
  "PHONE",
  "ACCOUNT",
  "URL",
  "DOMAIN",
  "NAME",
  "OTHER",
];

export function normaliseEntity(value: unknown): Entity {
  const e = dict(value);
  const type = str(e.entity_type ?? e.type).toUpperCase() as EntityType;
  const raw = str(e.value_raw ?? e.value);
  return {
    id: str(e.id, raw),
    entity_type: ENTITY_TYPES.includes(type) ? type : "OTHER",
    value_raw: raw,
    value_norm: str(e.value_norm ?? e.normalized ?? raw),
    case_count: num(e, ["case_count", "cases", "count"]),
    first_seen: strOrNull(e.first_seen) ?? undefined,
    last_seen: strOrNull(e.last_seen) ?? undefined,
  };
}

function normaliseTrace(value: unknown): TraceStep[] {
  return arr(value).map((step) => {
    const s = dict(step);
    return {
      name: str(s.name ?? s.node ?? s.step, "step"),
      duration_ms: num(s, ["duration_ms", "ms", "latency_ms"]),
      detail: strOrNull(s.detail ?? s.summary),
    };
  });
}

/**
 * `/cases/{id}` → `case + mo + entities[] + links[] + discovery_state +
 * campaign`. The case fields may be nested under `case` or spread at the top
 * level; accept both.
 */
export function normaliseCaseDetail(data: unknown, id: string): CaseDetail {
  const wire = dict(data);
  const core = Object.keys(dict(wire.case)).length > 0 ? dict(wire.case) : wire;
  const summary = normaliseCase({
    ...core,
    id: core.id ?? wire.id ?? id,
    campaign: wire.campaign ?? core.campaign,
    discovery_state: wire.discovery_state ?? core.discovery_state,
  });

  return {
    ...summary,
    transcript: normaliseTranscript(core.transcript ?? wire.transcript),
    mo: normaliseMo(wire.mo ?? core.mo),
    narrative: strOrNull(wire.narrative ?? core.narrative),
    entities: arr(wire.entities ?? core.entities).map(normaliseEntity),
    trace: normaliseTrace(wire.trace ?? core.trace),
  };
}

/* ── Campaigns ────────────────────────────────────────────────────────── */

const CAMPAIGN_STATUSES = [
  "CANDIDATE",
  "PENDING_VALIDATION",
  "APPROVED",
  "ACTIVE",
  "SUPERSEDED",
  "ARCHIVED",
  "REJECTED",
] as const;

export function normaliseCampaign(value: unknown): CampaignSummary {
  const c = dict(value);
  const status = str(c.status, "CANDIDATE").toUpperCase();
  return {
    id: str(c.id ?? c.campaign_id),
    code: str(c.code, "—"),
    name: str(c.name, "untitled campaign"),
    status: ((CAMPAIGN_STATUSES as readonly string[]).includes(status)
      ? status
      : "CANDIDATE") as CampaignSummary["status"],
    confidence: num(c, ["confidence", "score"]),
    case_count: num(c, ["case_count", "cases"]),
    customer_count: num(c, ["customer_count", "customers"]),
    first_seen: strOrNull(c.first_seen),
    last_seen: strOrNull(c.last_seen),
    span_minutes: numOrNull(c, ["span_minutes", "span"]),
  };
}

export function normaliseCampaigns(data: unknown): { campaigns: CampaignSummary[] } {
  const wire = dict(data);
  const raw = Array.isArray(data) ? data : arr(wire.campaigns ?? wire.items);
  return { campaigns: raw.map(normaliseCampaign) };
}

/* ── Graph ────────────────────────────────────────────────────────────── */

function nodeKind(value: unknown): GraphNode["kind"] {
  const raw = str(value).toLowerCase();
  if (raw === "entity" || raw === "campaign") return raw;
  return "case";
}

function linkKind(value: unknown, fallback: GraphLink["kind"]): GraphLink["kind"] {
  const raw = str(value).toLowerCase().replace(/_/g, "-");
  if (raw === "case-entity" || raw === "case-case" || raw === "campaign-case") {
    return raw;
  }
  return fallback;
}

function endpointId(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return str(dict(value).id);
}

/**
 * Build the hover text when the backend hasn't supplied one. Every edge must
 * answer "why does this exist?" — that question is the whole point of Screen C,
 * so we never render a bare unexplained line.
 */
function edgeReason(edge: Dict, weight: number): string {
  const explicit = strOrNull(edge.reason ?? edge.explanation ?? edge.why);
  if (explicit) return explicit;

  const signals = dict(edge.signals);
  const parts = Object.entries(signals)
    .filter(([, v]) => v !== null && v !== undefined && v !== false)
    .map(([k, v]) => (typeof v === "boolean" ? k : `${k} ${String(v)}`));
  const shared = strOrNull(edge.shared_entity ?? edge.entity);
  if (shared) parts.unshift(`shared ${shared}`);

  parts.push(`w ${Math.round(weight * 100) / 100}`);
  return parts.join(" · ");
}

export function normaliseGraph(data: unknown): GraphData {
  const wire = dict(data);

  const nodes: GraphNode[] = arr(wire.nodes).map((value) => {
    const n = dict(value);
    const kind = nodeKind(n.kind ?? n.type);
    const type = str(n.entity_type).toUpperCase() as EntityType;
    return {
      id: endpointId(n.id ?? n.key),
      kind,
      label: str(n.label ?? n.name ?? n.value ?? n.id),
      entity_type: ENTITY_TYPES.includes(type) ? type : undefined,
      campaign_id: strOrNull(n.campaign_id),
      risk_score: numOrNull(n, ["risk_score", "score"]) ?? undefined,
      case_count: numOrNull(n, ["case_count", "cases"]) ?? undefined,
    };
  });

  const byId = new Map(nodes.map((n) => [n.id, n]));

  // The backend calls them `edges`; the force layout and every test call them
  // `links`. Accept either.
  const rawEdges = arr(wire.edges ?? wire.links);
  const links: GraphLink[] = rawEdges.map((value) => {
    const e = dict(value);
    const source = endpointId(e.source ?? e.from);
    const target = endpointId(e.target ?? e.to);
    const weight = num(e, ["weight", "score", "fused_score"], 0.5);
    const sourceKind = byId.get(source)?.kind ?? "case";
    const targetKind = byId.get(target)?.kind ?? "case";
    const inferred: GraphLink["kind"] =
      sourceKind === "campaign" || targetKind === "campaign"
        ? "campaign-case"
        : sourceKind === "entity" || targetKind === "entity"
          ? "case-entity"
          : "case-case";
    return {
      source,
      target,
      kind: linkKind(e.kind ?? e.type, inferred),
      weight,
      reason: edgeReason(e, weight),
      signals: Object.keys(dict(e.signals)).length ? dict(e.signals) : undefined,
      case_refs: arr(e.case_refs).filter((r): r is string => typeof r === "string"),
    };
  });

  // Hulls are optional on the wire; derive them from campaign membership so the
  // campaign outline still appears once cases are assigned.
  const wireHulls = arr(wire.hulls);
  const hulls = wireHulls.length
    ? wireHulls.map((value) => {
        const h = dict(value);
        return {
          campaign_id: str(h.campaign_id ?? h.id),
          code: str(h.code, "—"),
          name: str(h.name),
          node_ids: arr(h.node_ids).map(endpointId).filter(Boolean),
          colour: strOrNull(h.colour ?? h.color) ?? undefined,
        };
      })
    : deriveHulls(nodes);

  return { nodes, links, hulls };
}

function deriveHulls(nodes: GraphNode[]): GraphData["hulls"] {
  const groups = new Map<string, string[]>();
  for (const node of nodes) {
    if (!node.campaign_id) continue;
    const list = groups.get(node.campaign_id) ?? [];
    list.push(node.id);
    groups.set(node.campaign_id, list);
  }
  return [...groups.entries()].map(([campaign_id, node_ids]) => {
    const campaignNode = nodes.find(
      (n) => n.kind === "campaign" && (n.campaign_id === campaign_id || n.id === campaign_id),
    );
    return {
      campaign_id,
      code: campaignNode?.label ?? campaign_id,
      name: campaignNode?.label ?? campaign_id,
      node_ids,
    };
  });
}
