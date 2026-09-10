/**
 * Mock fixtures.
 *
 * These exist so all seven screens render before the backend router lands.
 * They are shaped exactly like the contract in 01_upgrade_plan.md §13 —
 * when the backend replies, nothing in the components changes.
 *
 * NOTE: fixtures are data only. They never drive animation; animation is
 * always driven by ns_events arriving through the event store.
 */

import type {
  ArtifactsResponse,
  CampaignsResponse,
  CasesResponse,
  EvalComparison,
  McpLogResponse,
  McpLogRow,
  OverviewResponse,
} from "../types/api";
import type {
  ArtifactDetail,
  ArtifactGroup,
  CampaignDetail,
  CaseDetail,
  GraphData,
} from "../types/campaign";
import type { NsEvent } from "../types/events";

export const mockOverview = (): OverviewResponse => ({
  counters: {
    cases: 47,
    open_cases: 12,
    unrecognised: 1,
    campaigns: 2,
    core_version: 7,
    exposure_rm: 284500,
  },
  metrics: [
    {
      label: "TIME TO DISCOVERY",
      before_value: 12960,
      after_value: 41,
      unit: "min",
      lower_is_better: true,
    },
    {
      label: "VICTIMS BEFORE DISCOVERY",
      before_value: 24,
      after_value: 3,
      unit: "victims",
      lower_is_better: true,
    },
    {
      label: "TIME TO PROPAGATION",
      before_value: 604800,
      after_value: 1,
      unit: "s",
      lower_is_better: true,
    },
  ],
  mode: "LIVE",
});

export const mockCases = (): CasesResponse => ({
  total: 4,
  cases: [
    {
      id: "case-24",
      case_number: 24,
      tier: "tier2",
      scam_type: "Impersonation",
      risk_score: 87,
      risk_label: "HIGH",
      created_at: "2026-09-10T12:04:11Z",
      campaign_id: "camp-027",
      campaign_name: 'Fake BNM "Safe Account" Wave',
      discovery_state: "CLUSTERED",
    },
    {
      id: "case-41",
      case_number: 41,
      tier: "tier2",
      scam_type: "Impersonation",
      risk_score: 79,
      risk_label: "HIGH",
      created_at: "2026-09-10T12:04:33Z",
      campaign_id: "camp-027",
      campaign_name: 'Fake BNM "Safe Account" Wave',
      discovery_state: "CLUSTERED",
    },
    {
      id: "case-42",
      case_number: 42,
      tier: "tier1",
      scam_type: "Phishing",
      risk_score: 55,
      risk_label: "MEDIUM",
      created_at: "2026-09-10T12:04:48Z",
      campaign_id: null,
      campaign_name: null,
      discovery_state: "OBSERVED",
    },
    {
      id: "case-43",
      case_number: 43,
      tier: "tier1",
      scam_type: "Investment",
      risk_score: 31,
      risk_label: "LOW",
      created_at: "2026-09-10T12:05:01Z",
      campaign_id: null,
      campaign_name: null,
      discovery_state: "NORMAL",
    },
  ],
});

export const mockCaseDetail = (id: string): CaseDetail => ({
  id,
  case_number: Number(id.replace(/\D/g, "")) || 24,
  tier: "tier2",
  scam_type: "Impersonation",
  risk_score: 87,
  risk_label: "HIGH",
  created_at: "2026-09-10T12:04:11Z",
  campaign_id: "camp-027",
  campaign_name: 'Fake BNM "Safe Account" Wave',
  discovery_state: "CLUSTERED",
  narrative:
    "Caller impersonating a Bank Negara Malaysia officer claims the customer's account " +
    "is implicated in a money-laundering probe and instructs a transfer to a temporary " +
    "'safe account', forbidding contact with family.",
  mo: {
    impersonates: "Bank Negara Malaysia",
    pretext: "money-laundering probe",
    phases: ["authority", "fear", "isolation", "urgency", "safe-account"],
    money_ask_at: "03:07",
    channel: "voice",
    language: "ms-MY",
  },
  transcript: [
    {
      t: "00:03",
      speaker: "CALLER",
      text: "Saya pegawai dari Bank Negara Malaysia, bahagian siasatan.",
      score: 48,
    },
    { t: "00:11", speaker: "USER", text: "Ya, kenapa?", score: 12 },
    {
      t: "00:22",
      speaker: "CALLER",
      text: "Akaun encik terlibat dalam kes pengubahan wang haram. Kita perlu pindahkan ke akaun selamat sementara.",
      score: 91,
      novel_phrases: ["akaun selamat sementara"],
    },
    {
      t: "00:31",
      speaker: "AI",
      text: "Boleh saya semak nombor rujukan kes tersebut?",
      score: null,
    },
    {
      t: "01:02",
      speaker: "CALLER",
      text: "Jangan beritahu keluarga. Ini siasatan sulit.",
      score: 84,
      novel_phrases: ["Jangan beritahu keluarga"],
    },
    {
      t: "03:07",
      speaker: "CALLER",
      text: "Pindahkan RM 18,500 ke akaun 1592 8834 0021 sekarang.",
      score: 96,
    },
  ],
  entities: [
    {
      id: "ent-acct",
      entity_type: "ACCOUNT",
      value_raw: "1592 8834 0021",
      value_norm: "159288340021",
      case_count: 7,
    },
    {
      id: "ent-phone",
      entity_type: "PHONE",
      value_raw: "+6011-2288 4410",
      value_norm: "+601122884410",
      case_count: 4,
    },
    {
      id: "ent-url",
      entity_type: "URL",
      value_raw: "bnm-verify.online",
      value_norm: "bnm-verify.online",
      case_count: 3,
    },
  ],
  trace: [
    { name: "orchestrator", duration_ms: 12, detail: null },
    { name: "phone_worker", duration_ms: 840, detail: "groq 612 tok" },
    { name: "research", duration_ms: 610, detail: "tavily 3 hits" },
    { name: "scorer", duration_ms: 4, detail: null },
    { name: "xai_explainer", duration_ms: 430, detail: null },
  ],
});

export const mockCampaigns = (): CampaignsResponse => ({
  campaigns: [
    {
      id: "camp-027",
      code: "SCAM-027",
      name: 'Fake BNM "Safe Account" Wave',
      status: "CANDIDATE",
      confidence: 0.87,
      case_count: 6,
      customer_count: 4,
      first_seen: "2026-09-10T11:24:00Z",
      last_seen: "2026-09-10T12:05:00Z",
      span_minutes: 41,
    },
    {
      id: "camp-024",
      code: "SCAM-024",
      name: "Parcel Customs Clearance Fee",
      status: "ACTIVE",
      confidence: 0.91,
      case_count: 9,
      customer_count: 8,
      first_seen: "2026-09-02T09:41:00Z",
      last_seen: "2026-09-08T18:12:00Z",
      span_minutes: 8911,
    },
    {
      id: "camp-019",
      code: "SCAM-019",
      name: "Police Impersonation Bail Transfer",
      status: "ACTIVE",
      confidence: 0.88,
      case_count: 11,
      customer_count: 10,
      first_seen: "2026-08-28T10:02:00Z",
      last_seen: "2026-08-30T16:40:00Z",
      span_minutes: 3278,
    },
  ],
});

export const mockCampaignDetail = (id: string): CampaignDetail => ({
  id,
  code: "SCAM-027",
  name: 'Fake BNM "Safe Account" Wave',
  status: "CANDIDATE",
  confidence: 0.87,
  case_count: 6,
  customer_count: 4,
  first_seen: "2026-09-10T11:24:00Z",
  last_seen: "2026-09-10T12:05:00Z",
  span_minutes: 41,
  case_ids: ["case-7", "case-19", "case-24", "case-31", "case-38", "case-41"],
  evidence: [
    { label: "cases / distinct customers", value: "6 cases, 4 customers", passed: true },
    { label: "hard link", value: "ACCT 1592… (×4)", passed: true },
    { label: "narrative cosine", value: "0.89", passed: true },
    { label: "span", value: "41 min < 14 d → EMERGING", passed: true },
    { label: "novelty", value: "0.62 < 0.90 → NEW", passed: true },
  ],
  hypothesis: {
    name: 'Fake BNM "Safe Account" Wave',
    mo_summary:
      "Caller impersonates a Bank Negara Malaysia officer, claims the account is being " +
      "used for laundering, forbids family contact, and directs the victim to move funds " +
      "to a temporary 'safe account' controlled by the syndicate.",
    novel_indicators: ["akaun selamat sementara", "domain pattern bnm-*.online"],
  },
  proposed_artifacts: [
    {
      name: "SCAM-027.json",
      tier: "pack",
      target_agent: "phone_agent",
      version: 1,
      note: "campaign pack — instance knowledge",
    },
    {
      name: "phone_agent_core",
      tier: "core",
      target_agent: "phone_agent",
      version: 7,
      note: "generalised from 019 · 024 · 027",
      source_campaigns: ["SCAM-019", "SCAM-024", "SCAM-027"],
    },
    {
      name: "txn_monitor_rule",
      tier: "pack",
      target_agent: "txn_monitor",
      version: 1,
      note: "block ACCT 1592…",
    },
    {
      name: "compliance_brief",
      tier: "pack",
      target_agent: "compliance (via MCP)",
      version: 1,
      note: "brief",
    },
    {
      name: "customer_advisory",
      tier: "pack",
      target_agent: "customer_svc (via MCP)",
      version: 1,
      note: "advisory",
    },
  ],
  mini_graph: null,
});

export const mockGraph = (): GraphData => {
  const caseIds = ["7", "19", "24", "31", "38", "41", "12", "15", "22", "44"];
  const nodes: GraphData["nodes"] = caseIds.map((n) => ({
    id: `case-${n}`,
    kind: "case",
    label: `#${n}`,
    risk_score: 40 + ((Number(n) * 7) % 55),
    campaign_id: ["7", "19", "24", "31", "38", "41"].includes(n) ? "camp-027" : null,
  }));

  nodes.push(
    {
      id: "ent-acct",
      kind: "entity",
      label: "ACCT 1592…",
      entity_type: "ACCOUNT",
      case_count: 4,
    },
    {
      id: "ent-phone",
      kind: "entity",
      label: "+6011…",
      entity_type: "PHONE",
      case_count: 3,
    },
    {
      id: "ent-url",
      kind: "entity",
      label: "bnm-verify.online",
      entity_type: "URL",
      case_count: 3,
    },
    {
      id: "ent-domain",
      kind: "entity",
      label: "bnm-*.online",
      entity_type: "DOMAIN",
      case_count: 2,
    },
    {
      id: "camp-027",
      kind: "campaign",
      label: "SCAM-027",
      campaign_id: "camp-027",
      case_count: 6,
    },
  );

  const links: GraphData["links"] = [
    {
      source: "case-7",
      target: "ent-acct",
      kind: "case-entity",
      weight: 1,
      reason: "mentions ACCOUNT 1592…",
    },
    {
      source: "case-19",
      target: "ent-acct",
      kind: "case-entity",
      weight: 1,
      reason: "mentions ACCOUNT 1592…",
    },
    {
      source: "case-24",
      target: "ent-acct",
      kind: "case-entity",
      weight: 1,
      reason: "mentions ACCOUNT 1592…",
    },
    {
      source: "case-41",
      target: "ent-acct",
      kind: "case-entity",
      weight: 1,
      reason: "mentions ACCOUNT 1592…",
    },
    {
      source: "case-31",
      target: "ent-phone",
      kind: "case-entity",
      weight: 1,
      reason: "mentions PHONE +6011…",
    },
    {
      source: "case-38",
      target: "ent-url",
      kind: "case-entity",
      weight: 1,
      reason: "mentions URL bnm-verify.online",
    },
    {
      source: "case-38",
      target: "ent-domain",
      kind: "case-entity",
      weight: 1,
      reason: "matches DOMAIN bnm-*.online",
    },
    {
      source: "case-7",
      target: "case-19",
      kind: "case-case",
      weight: 0.95,
      reason: "shared ACCOUNT 1592… · w 0.95 · cases #7, #19",
      signals: { shared_identifier: "ACCOUNT", narrative: 0.89 },
      case_refs: ["case-7", "case-19"],
    },
    {
      source: "case-19",
      target: "case-24",
      kind: "case-case",
      weight: 0.91,
      reason: "narrative cosine 0.91 + shared ACCOUNT · cases #19, #24",
      signals: { narrative: 0.91 },
      case_refs: ["case-19", "case-24"],
    },
    {
      source: "case-24",
      target: "case-41",
      kind: "case-case",
      weight: 0.88,
      reason: "shared ACCOUNT 1592… · w 0.88 · cases #24, #41",
      signals: { shared_identifier: "ACCOUNT" },
      case_refs: ["case-24", "case-41"],
    },
    {
      source: "case-31",
      target: "case-38",
      kind: "case-case",
      weight: 0.74,
      reason: "narrative cosine 0.74 · cases #31, #38",
      signals: { narrative: 0.74 },
      case_refs: ["case-31", "case-38"],
    },
  ];

  for (const n of ["7", "19", "24", "31", "38", "41"]) {
    links.push({
      source: "camp-027",
      target: `case-${n}`,
      kind: "campaign-case",
      weight: 0.5,
      reason: `member of SCAM-027`,
    });
  }

  return {
    nodes,
    links,
    hulls: [
      {
        campaign_id: "camp-027",
        code: "SCAM-027",
        name: 'Fake BNM "Safe Account" Wave',
        node_ids: [
          "case-7",
          "case-19",
          "case-24",
          "case-31",
          "case-38",
          "case-41",
          "ent-acct",
        ],
        colour: "#FFB74D",
      },
    ],
  };
};

const CORE_V6 = `# phone_agent_core — v6
rules:
  - id: authority_claim
    when: caller claims to represent a regulator, bank or police
    then: raise risk by 25 and require callback verification

  - id: urgency_pressure
    when: caller imposes a deadline under 30 minutes
    then: raise risk by 15

  - id: transfer_request
    when: caller requests a funds transfer during the call
    then: raise risk by 30 and warn the user
`;

const CORE_V7 = `# phone_agent_core — v7
rules:
  - id: authority_claim
    when: caller claims to represent a regulator, bank or police
    then: raise risk by 25 and require callback verification

  - id: urgency_pressure
    when: caller imposes a deadline under 30 minutes
    then: raise risk by 15

  - id: transfer_request
    when: caller requests a funds transfer during the call
    then: raise risk by 30 and warn the user

  - id: isolation_directive
    when: caller instructs the user not to contact family, friends or branch staff
    then: raise risk by 35 and interrupt immediately
    generalised_from: [SCAM-019, SCAM-024, SCAM-027]

  - id: custodial_transfer_pretext
    when: caller frames a transfer as protective custody of the victim's own money
    then: raise risk by 40 and block the transaction
    generalised_from: [SCAM-019, SCAM-024, SCAM-027]
`;

const PACK_027 = `{
  "code": "SCAM-027",
  "name": "Fake BNM \\"Safe Account\\" Wave",
  "indicators": [
    { "type": "phrase", "value": "akaun selamat sementara", "weight": 0.9 },
    { "type": "phrase", "value": "jangan beritahu keluarga", "weight": 0.8 },
    { "type": "domain", "value": "bnm-*.online", "weight": 0.85 },
    { "type": "account", "value": "159288340021", "weight": 1.0 }
  ],
  "impersonates": "Bank Negara Malaysia",
  "response": "interrupt, name the tactic, refuse the transfer"
}
`;

const ARTIFACT_CONTENT: Record<string, Record<number, string>> = {
  phone_agent_core: { 6: CORE_V6, 7: CORE_V7 },
  "SCAM-027.json": { 1: PACK_027 },
};

const CORE_GROUP: ArtifactGroup = {
  name: "phone_agent_core",
  tier: "core",
  target_agent: "phone_agent",
  latest_version: 7,
  versions: [
    {
      id: "art-core-7",
      name: "phone_agent_core",
      tier: "core",
      artifact_type: "skill",
      target_agent: "phone_agent",
      version: 7,
      status: "PUBLISHED",
      created_at: "2026-09-10T12:05:05Z",
      created_by: "generaliser",
      approved_by: "fraud_ops",
      source_campaigns: ["SCAM-019", "SCAM-024", "SCAM-027"],
      campaign_id: null,
      effectiveness: {
        eval_run_id: "eval-after",
        detected: 20,
        total: 20,
        fp: 0,
        fp_total: 10,
        measured_at: "2026-09-10T12:07:00Z",
      },
    },
    {
      id: "art-core-6",
      name: "phone_agent_core",
      tier: "core",
      artifact_type: "skill",
      target_agent: "phone_agent",
      version: 6,
      status: "PUBLISHED",
      created_at: "2026-08-30T09:12:00Z",
      created_by: "generaliser",
      approved_by: "fraud_ops",
      source_campaigns: ["SCAM-019", "SCAM-024"],
      campaign_id: null,
      effectiveness: {
        eval_run_id: "eval-before",
        detected: 17,
        total: 20,
        fp: 1,
        fp_total: 10,
        measured_at: "2026-08-30T09:20:00Z",
      },
    },
  ],
};

const PACK_GROUPS: ArtifactGroup[] = [
  {
    name: "SCAM-027.json",
    tier: "pack",
    target_agent: "phone_agent",
    latest_version: 1,
    versions: [
      {
        id: "art-p27-1",
        name: "SCAM-027.json",
        tier: "pack",
        artifact_type: "campaign_pack",
        target_agent: "phone_agent",
        version: 1,
        status: "PUBLISHED",
        created_at: "2026-09-10T12:05:04Z",
        created_by: "compiler",
        approved_by: "fraud_ops",
        source_campaigns: ["SCAM-027"],
        campaign_id: "camp-027",
        effectiveness: {
          eval_run_id: "eval-after",
          detected: 19,
          total: 20,
          fp: 1,
          fp_total: 10,
          measured_at: "2026-09-10T12:07:00Z",
        },
      },
    ],
  },
  {
    name: "SCAM-024.json",
    tier: "pack",
    target_agent: "phone_agent",
    latest_version: 2,
    versions: [
      {
        id: "art-p24-2",
        name: "SCAM-024.json",
        tier: "pack",
        artifact_type: "campaign_pack",
        target_agent: "phone_agent",
        version: 2,
        status: "PUBLISHED",
        created_at: "2026-09-08T09:41:00Z",
        created_by: "compiler",
        approved_by: "fraud_ops",
        source_campaigns: ["SCAM-024"],
        campaign_id: "camp-024",
        effectiveness: {
          eval_run_id: "eval-before",
          detected: 18,
          total: 20,
          fp: 1,
          fp_total: 10,
          measured_at: "2026-09-08T10:00:00Z",
        },
      },
      {
        id: "art-p24-1",
        name: "SCAM-024.json",
        tier: "pack",
        artifact_type: "campaign_pack",
        target_agent: "phone_agent",
        version: 1,
        status: "ROLLED_BACK",
        created_at: "2026-09-02T10:02:00Z",
        created_by: "compiler",
        approved_by: "fraud_ops",
        source_campaigns: ["SCAM-024"],
        campaign_id: "camp-024",
        effectiveness: null,
      },
    ],
  },
  {
    name: "SCAM-019.json",
    tier: "pack",
    target_agent: "phone_agent",
    latest_version: 1,
    versions: [
      {
        id: "art-p19-1",
        name: "SCAM-019.json",
        tier: "pack",
        artifact_type: "campaign_pack",
        target_agent: "phone_agent",
        version: 1,
        status: "PUBLISHED",
        created_at: "2026-08-30T14:20:00Z",
        created_by: "compiler",
        approved_by: "fraud_ops",
        source_campaigns: ["SCAM-019"],
        campaign_id: "camp-019",
        effectiveness: {
          eval_run_id: "eval-before",
          detected: 17,
          total: 20,
          fp: 2,
          fp_total: 10,
          measured_at: "2026-08-30T14:40:00Z",
        },
      },
    ],
  },
];

export const mockArtifacts = (tier?: "core" | "pack"): ArtifactsResponse => {
  if (tier === "core") return { artifacts: [CORE_GROUP] };
  if (tier === "pack") return { artifacts: PACK_GROUPS };
  return { artifacts: [CORE_GROUP, ...PACK_GROUPS] };
};

export const mockArtifactDetail = (
  name: string,
  version?: number | "latest",
): ArtifactDetail => {
  const group =
    [CORE_GROUP, ...PACK_GROUPS].find((g) => g.name === name) ?? CORE_GROUP;
  const wanted =
    version === undefined || version === "latest" ? group.latest_version : version;
  const meta =
    group.versions.find((v) => v.version === wanted) ?? group.versions[0];
  const contents = ARTIFACT_CONTENT[group.name] ?? {};
  const prevVersion = meta.version > 1 ? meta.version - 1 : null;
  return {
    ...meta,
    content: contents[meta.version] ?? `# ${group.name} v${meta.version}\n(no fixture content)\n`,
    previous_version: prevVersion,
    previous_content: prevVersion ? (contents[prevVersion] ?? null) : null,
  };
};

export const mockEval = (): EvalComparison => ({
  before: {
    run_id: "eval-before",
    label: "before · core v6",
    started_at: "2026-09-10T11:58:00Z",
    detected: 12,
    total: 20,
    false_positives: 3,
    fp_total: 10,
    mean_latency_ms: 1240,
    artifact_ver: { phone_agent_core: 6 },
  },
  after: {
    run_id: "eval-after",
    label: "after · core v7 + SCAM-027",
    started_at: "2026-09-10T12:07:00Z",
    detected: 19,
    total: 20,
    false_positives: 1,
    fp_total: 10,
    mean_latency_ms: 1180,
    artifact_ver: { phone_agent_core: 7, "SCAM-027.json": 1 },
  },
});

/** Raw operator-view rows — full `params`/`citations`, as `fraud_ops` sees them. */
const MCP_LOG_ROWS: McpLogRow[] = [
  {
    id: 3,
    ts: "2026-09-10T12:05:31Z",
    caller: "codebuddy",
    role: "compliance",
    tool: "get_campaign",
    params: { code: "SCAM-027" },
    latency_ms: 88,
    citations: ["SCAM-027"],
  },
  {
    id: 2,
    ts: "2026-09-10T12:05:14Z",
    caller: "codebuddy",
    role: "legal",
    tool: "ask_transafe",
    params: { question: "What is the exposure for SCAM-027?" },
    latency_ms: 340,
    citations: ["SCAM-027 (6 cases)"],
  },
  {
    id: 1,
    ts: "2026-09-10T12:04:02Z",
    caller: "partner_bank",
    role: "public",
    tool: "list_campaigns",
    params: {},
    latency_ms: 42,
    citations: [],
  },
];

/**
 * Offline fallback for `GET /enterprise/mcp/log`.
 *
 * This fixture deliberately does **not** reproduce the redaction policy. The
 * policy lives in exactly one place — `ROLE_VISIBILITY` in
 * `backend/mcp/redaction.py` — and a second copy here, in a language that
 * cannot see the first, is precisely what drifted before: the previous fixture
 * emitted `case_transcripts`, a category name the server has never used.
 *
 * What it *can* honestly reproduce is the one structural fact that is not a
 * policy table: only a role with full visibility receives `params` and
 * `citations`, per `project_log_entry`. So switching role offline still shows
 * the payload genuinely shrink.
 *
 * It cannot know the withheld *category list* for a projected role, so it
 * omits `redacted_fields` and lets the component fail closed and say the lens
 * is unavailable — an honest "unknown" rather than a confident wrong answer.
 */
export const mockMcpLog = (asRole?: string): McpLogResponse => {
  const roles = [
    "analyst",
    "auditor",
    "compliance",
    "customer_service",
    "external_researcher",
    "fraud_ops",
    "legal",
    "partner_bank",
    "public",
  ];
  // Mirrors `has_full_visibility`: only fraud_ops holds every category.
  const fullVisibility = asRole === undefined || asRole === "fraud_ops";

  const entries = MCP_LOG_ROWS.map((row) => {
    // No lens at all — the operator view. `project_log_entry` never runs, so
    // `citation_count` is absent, exactly as the server's operator branch
    // leaves it.
    if (asRole === undefined) return { ...row };

    const citation_count = row.citations?.length ?? 0;
    return fullVisibility
      ? { ...row, citation_count, redacted_fields: [] }
      : {
          ...row,
          params: { outcome: null },
          citations: null,
          citation_count,
          // Unknown offline: the withheld category list is the server's to
          // compute. Omitting it makes the component say so.
          redacted_fields: undefined,
        };
  });

  return { entries, count: entries.length, roles };
};

/**
 * A short recorded ns_events sequence used by REPLAY mode when the backend has
 * no recording available. Timestamps are real relative offsets — the replay
 * source honours them.
 */
export const mockReplaySequence = (): NsEvent[] => {
  const base = Date.parse("2026-09-10T12:04:11Z");
  const at = (sec: number) => new Date(base + sec * 1000).toISOString();
  const runId = "replay-fixture";
  let id = 0;
  const e = (
    sec: number,
    layer: NsEvent["layer"],
    event_type: string,
    severity: NsEvent["severity"],
    payload: Record<string, unknown>,
  ): NsEvent => ({
    id: ++id,
    ts: at(sec),
    layer,
    event_type,
    severity,
    payload,
    run_id: runId,
  });

  return [
    e(0, "sensing", "call_received", "info", { channel: "voice", case_number: 41 }),
    e(0.4, "case", "case_ingested", "info", { case_number: 41, case_id: "case-41" }),
    e(0.9, "case", "entity_linked", "info", {
      case_number: 41,
      entity: "ACCT 1592…",
      entity_type: "ACCOUNT",
    }),
    e(1.6, "case", "case_ingested", "info", { case_number: 42, case_id: "case-42" }),
    e(2.2, "discovery", "case_linked", "info", {
      pair: ["case-41", "case-24"],
      score: 0.88,
    }),
    e(2.9, "discovery", "cluster_formed", "warning", { size: 3 }),
    e(3.4, "discovery", "campaign_proposed", "critical", {
      campaign_id: "camp-027",
      code: "SCAM-027",
      case_count: 3,
    }),
    e(9.0, "discovery", "campaign_approved", "info", {
      campaign_id: "camp-027",
      approved_by: "Fraud Ops",
    }),
    e(10.2, "compiler", "artifact_compiled", "info", {
      name: "SCAM-027.json",
      tier: "pack",
      version: 1,
    }),
    e(11.0, "compiler", "artifact_compiled", "info", {
      name: "phone_agent_core",
      tier: "core",
      version: 7,
      source_campaigns: ["SCAM-019", "SCAM-024", "SCAM-027"],
    }),
    e(11.6, "registry", "artifact_published", "info", {
      name: "phone_agent_core",
      from_version: 6,
      version: 7,
    }),
    e(12.1, "propagation", "propagated", "info", { agent: "phone_agent" }),
    e(12.3, "propagation", "propagated", "info", { agent: "fraud_ops" }),
    e(12.5, "propagation", "propagated", "info", { agent: "phishing_agent" }),
    e(12.7, "propagation", "propagated", "info", { agent: "txn_monitor" }),
    e(18.0, "exposure", "mcp_call", "info", {
      caller: "codebuddy",
      tool: "ask_transafe",
      role: "legal",
      latency_ms: 340,
    }),
    e(20.5, "exposure", "mcp_call", "info", {
      caller: "codebuddy",
      tool: "get_campaign",
      role: "compliance",
      latency_ms: 88,
    }),
  ];
};
