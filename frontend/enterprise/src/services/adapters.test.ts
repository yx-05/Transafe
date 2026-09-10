import { describe, expect, it } from "vitest";
import {
  normaliseArtifactDetail,
  normaliseArtifacts,
  normaliseCampaignDetail,
  normaliseCampaigns,
  normaliseCaseDetail,
  normaliseCases,
  normaliseEvents,
  normaliseGraph,
  normaliseOverview,
  overviewEvents,
} from "./adapters";
import { makeEvent } from "../test-utils";

/**
 * The SQL migration is not applied yet: read endpoints degrade per-table to
 * 0/[] rather than 500. Every adapter must survive that and produce an honest
 * empty view model — never a throw, never an invented number.
 */
describe("empty-state degradation", () => {
  it("survives an entirely empty overview", () => {
    const out = normaliseOverview({ layers: {}, campaigns: [], recent_events: [] });
    expect(out.counters.cases).toBe(0);
    expect(out.counters.core_version).toBe(0);
    expect(out.metrics).toEqual([]);
  });

  it("survives null / garbage payloads", () => {
    expect(normaliseOverview(null).counters.cases).toBe(0);
    expect(normaliseCases(null)).toEqual({ cases: [], total: 0 });
    expect(normaliseCampaigns(undefined)).toEqual({ campaigns: [] });
    expect(normaliseGraph({})).toEqual({ nodes: [], links: [], hulls: [] });
    expect(normaliseEvents(null)).toEqual([]);
  });

  it("does not invent metrics the backend never measured", () => {
    expect(normaliseOverview({ layers: { case: { cases: 12 } } }).metrics).toEqual([]);
  });

  it("survives null / garbage on the two Screen D/E detail payloads", () => {
    // Screen D reads `confidence.toFixed`, `evidence.map`, `hypothesis.name`
    // and `proposed_artifacts.map` unguarded; Screen E reads
    // `versions.map` and `source_campaigns.length`. Each of these is a
    // white-screen, not a blank field, if the adapter lets a hole through.
    const campaign = normaliseCampaignDetail(null, "camp-1");
    expect(campaign.id).toBe("camp-1");
    expect(campaign.confidence).toBe(0);
    expect(campaign.evidence).toEqual([]);
    expect(campaign.hypothesis.novel_indicators).toEqual([]);
    expect(campaign.proposed_artifacts).toEqual([]);
    expect(campaign.case_ids).toEqual([]);
    expect(campaign.mini_graph).toBeNull();

    expect(normaliseArtifacts(null)).toEqual({ artifacts: [] });
    expect(normaliseArtifacts({ artifacts: [] })).toEqual({ artifacts: [] });

    const detail = normaliseArtifactDetail(undefined, "phone_agent_core");
    expect(detail.name).toBe("phone_agent_core");
    expect(detail.source_campaigns).toEqual([]);
    expect(detail.previous_version).toBeNull();
    expect(detail.effectiveness).toBeNull();
  });
});

describe("normaliseCampaignDetail", () => {
  // Exactly what `get_campaign_detail` builds in router.py.
  const wire = {
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
    case_ids: ["case-7", "case-19"],
    evidence: [
      { label: "hard link", value: "ACCT 1592… (×4)", passed: true },
      { label: "novelty", value: "0.62 < 0.90 → NEW", passed: false },
    ],
    hypothesis: {
      name: 'Fake BNM "Safe Account" Wave',
      mo_summary: "Caller impersonates a BNM officer.",
      novel_indicators: ["akaun selamat sementara"],
    },
    proposed_artifacts: [
      {
        name: "SCAM-027.json",
        tier: "pack",
        target_agent: "phone_agent",
        version: 1,
        note: "campaign_pack",
        source_campaigns: ["SCAM-027"],
      },
    ],
    mini_graph: { nodes: [], edges: [] },
  };

  it("maps the router payload without losing anything", () => {
    const out = normaliseCampaignDetail(wire, "camp-027");
    expect(out.confidence).toBe(0.87);
    expect(out.status).toBe("CANDIDATE");
    expect(out.evidence).toHaveLength(2);
    expect(out.evidence[1].passed).toBe(false);
    expect(out.hypothesis.mo_summary).toBe("Caller impersonates a BNM officer.");
    expect(out.proposed_artifacts[0]).toMatchObject({ tier: "pack", version: 1 });
    expect(out.case_ids).toEqual(["case-7", "case-19"]);
    expect(out.mini_graph).toEqual({ nodes: [], links: [], hulls: [] });
  });

  it("keeps a missing hypothesis renderable rather than null", () => {
    // `campaign_hypothesis` always returns an object today, but the console
    // seeds its edit form from these two fields during render — a null here
    // is a blank screen on the approval path, not a blank field.
    const out = normaliseCampaignDetail({ ...wire, hypothesis: null }, "camp-027");
    expect(out.hypothesis.name).toBe('Fake BNM "Safe Account" Wave');
    expect(out.hypothesis.mo_summary).toBe("");
    expect(out.hypothesis.novel_indicators).toEqual([]);
  });

  it("does not mark an evidence line passed when the gate reported nothing", () => {
    const out = normaliseCampaignDetail(
      { ...wire, evidence: [{ label: "span", value: "41 min" }] },
      "camp-027",
    );
    expect(out.evidence[0].passed).toBe(false);
  });

  it("accepts indicators given as objects", () => {
    const out = normaliseCampaignDetail(
      {
        ...wire,
        hypothesis: { ...wire.hypothesis, novel_indicators: [{ value: "bnm-*.online" }, ""] },
      },
      "camp-027",
    );
    expect(out.hypothesis.novel_indicators).toEqual(["bnm-*.online"]);
  });
});

describe("normaliseArtifacts", () => {
  // `registry.list_artifacts` collapses to the newest row per name and the
  // router wraps it as {artifacts:[...flat rows...]}. There is no `versions`
  // key anywhere on the wire — Screen E maps over exactly that key.
  const flatWire = {
    artifacts: [
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
        effectiveness: { eval_run_id: "eval-after", detected: 19, total: 20, fp: 1, fp_total: 10 },
      },
      {
        id: "art-core-7",
        name: "phone_agent_core",
        tier: "core",
        artifact_type: "system_prompt",
        target_agent: "phone_agent",
        version: 7,
        status: "PUBLISHED",
        created_at: "2026-09-10T12:05:06Z",
        created_by: "generaliser",
        approved_by: "fraud_ops",
        source_campaigns: ["SCAM-019", "SCAM-024"],
        campaign_id: null,
        effectiveness: null,
      },
    ],
    count: 2,
  };

  it("groups the flat backend list into the shape the screen renders", () => {
    const { artifacts } = normaliseArtifacts(flatWire);
    expect(artifacts).toHaveLength(2);

    const pack = artifacts.find((g) => g.name === "SCAM-027.json");
    expect(pack).toBeDefined();
    expect(pack?.tier).toBe("pack");
    expect(pack?.target_agent).toBe("phone_agent");
    expect(pack?.latest_version).toBe(1);
    expect(pack?.versions).toHaveLength(1);
    expect(pack?.versions[0].effectiveness).toMatchObject({ detected: 19, total: 20 });

    const core = artifacts.find((g) => g.name === "phone_agent_core");
    expect(core?.latest_version).toBe(7);
    expect(core?.versions[0].source_campaigns).toEqual(["SCAM-019", "SCAM-024"]);
    expect(core?.versions[0].effectiveness).toBeNull();
  });

  it("collects several rows of one artifact into a single group, newest first", () => {
    const { artifacts } = normaliseArtifacts({
      artifacts: [
        { name: "SCAM-024.json", tier: "pack", version: 1, status: "ROLLED_BACK" },
        { name: "SCAM-024.json", tier: "pack", version: 2, status: "PUBLISHED" },
      ],
    });
    expect(artifacts).toHaveLength(1);
    expect(artifacts[0].versions.map((v) => v.version)).toEqual([2, 1]);
    expect(artifacts[0].latest_version).toBe(2);
  });

  it("still accepts an already-grouped payload", () => {
    const { artifacts } = normaliseArtifacts({
      artifacts: [
        {
          name: "phone_agent_core",
          tier: "core",
          target_agent: "phone_agent",
          latest_version: 7,
          versions: [{ version: 7, status: "PUBLISHED", created_by: "generaliser" }],
        },
      ],
    });
    expect(artifacts[0].versions).toHaveLength(1);
    expect(artifacts[0].versions[0].name).toBe("phone_agent_core");
    expect(artifacts[0].versions[0].tier).toBe("core");
    expect(artifacts[0].latest_version).toBe(7);
  });

  it("never emits a group whose versions are missing", () => {
    const { artifacts } = normaliseArtifacts({
      artifacts: [{ name: "half_written", tier: "pack" }, {}, null],
    });
    for (const group of artifacts) expect(Array.isArray(group.versions)).toBe(true);
    // The nameless rows are dropped rather than rendered as a blank group.
    expect(artifacts.map((g) => g.name)).toEqual(["half_written"]);
  });
});

describe("normaliseArtifactDetail", () => {
  // `get_artifact_diff` returns {current, previous, diff}; the router adds
  // `versions`. The screen reads a flat record.
  const wire = {
    current: {
      id: "art-core-7",
      name: "phone_agent_core",
      tier: "core",
      artifact_type: "system_prompt",
      target_agent: "phone_agent",
      version: 7,
      status: "PUBLISHED",
      created_at: "2026-09-10T12:05:06Z",
      created_by: "generaliser",
      approved_by: "fraud_ops",
      source_campaigns: ["SCAM-019", "SCAM-024"],
      content: "# core v7\nnever move funds to a 'safe account'\n",
    },
    previous: { version: 6, content: "# core v6\n" },
    diff: { added: 1, removed: 0 },
  };

  it("unwraps the current/previous envelope into the flat record", () => {
    const out = normaliseArtifactDetail(wire, "phone_agent_core");
    expect(out.version).toBe(7);
    expect(out.name).toBe("phone_agent_core");
    expect(out.created_by).toBe("generaliser");
    expect(out.content).toContain("safe account");
    expect(out.previous_version).toBe(6);
    expect(out.previous_content).toBe("# core v6\n");
    expect(out.source_campaigns).toEqual(["SCAM-019", "SCAM-024"]);
  });

  it("reports no predecessor for a first version", () => {
    const out = normaliseArtifactDetail(
      { current: { ...wire.current, version: 1 }, previous: null },
      "phone_agent_core",
    );
    expect(out.previous_version).toBeNull();
    expect(out.previous_content).toBeNull();
  });
});

describe("normaliseOverview", () => {
  const wire = {
    layers: {
      sensing: { calls: 4 },
      case: { cases: 47, open: 12, exposure_rm: 184000 },
      discovery: { unrecognised: 1, campaigns: 2 },
      registry: { core_version: 7 },
    },
    campaigns: [{ id: "camp-027", code: "SCAM-027" }],
    recent_events: [makeEvent({ id: 3 })],
    generated_at: "2026-09-10T12:00:00Z",
  };

  it("flattens per-layer stats into the counter strip", () => {
    expect(normaliseOverview(wire).counters).toEqual({
      cases: 47,
      open_cases: 12,
      unrecognised: 1,
      campaigns: 2,
      core_version: 7,
      exposure_rm: 184000,
    });
  });

  it("falls back to the campaign list length when discovery omits the count", () => {
    const out = normaliseOverview({ ...wire, layers: { ...wire.layers, discovery: {} } });
    expect(out.counters.campaigns).toBe(1);
  });

  it("hydrates the ticker from recent_events", () => {
    expect(overviewEvents(wire).map((e) => e.id)).toEqual([3]);
  });

  // The live payload from presenters.time_to_discovery_metric. `basis` is the
  // backend stating what its two halves mean: two cohorts of a campaign's own
  // member cases split on whether the case predates the campaign — NOT the
  // "before TranSafe" industry baseline the label implies. Screen A cannot
  // qualify the comparison if the adapter drops the sentence that qualifies it.
  it("carries the backend's description of what before/after mean", () => {
    const out = normaliseOverview({
      ...wire,
      metrics: [
        {
          label: "TIME TO DISCOVERY",
          before_value: 12960,
          after_value: 41,
          unit: "min",
          lower_is_better: true,
          basis:
            "median minutes from fraud_cases.created_at to campaign_cases.joined_at; " +
            "before = cases ingested before their campaign existed, " +
            "after = cases ingested once it did",
          before_sample: 6,
          after_sample: 31,
        },
      ],
    });

    expect(out.metrics).toHaveLength(1);
    expect(out.metrics[0].basis).toContain(
      "before = cases ingested before their campaign existed",
    );
  });

  // An unexplained metric gets no explanation rather than a generic one. A
  // hardcoded fallback sentence would be the console asserting a meaning the
  // backend never sent — the same defect as the frame it is meant to fix.
  it("leaves basis null when the backend does not explain the comparison", () => {
    const out = normaliseOverview({
      ...wire,
      metrics: [{ label: "UNEXPLAINED", before_value: 2, after_value: 1, unit: "min" }],
    });

    expect(out.metrics[0].basis).toBeNull();
  });

  // How much the median rests on. The backend sends these as diagnostics so
  // the number can be challenged: a median over 2 cases and a median over 40
  // render as identical bars, and only one of them supports the claim the bar
  // makes. Dropping them at the adapter makes the weak case indistinguishable
  // from the strong one.
  it("carries the sample counts behind each median", () => {
    const out = normaliseOverview({
      ...wire,
      metrics: [
        {
          label: "TIME TO DISCOVERY",
          before_value: 12960,
          after_value: 41,
          unit: "min",
          lower_is_better: true,
          before_sample: 6,
          after_sample: 31,
        },
      ],
    });

    expect(out.metrics[0].before_sample).toBe(6);
    expect(out.metrics[0].after_sample).toBe(31);
  });

  // Absent counts stay absent. A `0` here would read as "median over zero
  // cases", which is a stronger and stranger claim than saying nothing.
  it("leaves sample counts null when the backend does not send them", () => {
    const out = normaliseOverview({
      ...wire,
      metrics: [{ label: "UNCOUNTED", before_value: 2, after_value: 1, unit: "min" }],
    });

    expect(out.metrics[0].before_sample).toBeNull();
    expect(out.metrics[0].after_sample).toBeNull();
  });
});

describe("normaliseCases", () => {
  it("maps the wire rows and derives a risk label from the score", () => {
    const { cases, total } = normaliseCases({
      cases: [
        { id: "c1", case_number: 41, risk_score: 91, scam_type: "IMPERSONATION" },
        { id: "c2", case_number: 42, risk_score: 20 },
      ],
      total: 2,
    });
    expect(total).toBe(2);
    expect(cases[0].risk_label).toBe("CRITICAL");
    expect(cases[1].risk_label).toBe("LOW");
    expect(cases[1].scam_type).toBe("UNKNOWN");
  });

  // Pins the exact boundaries against the v1 risk scorer (graph_nodes.py:
  // <40 LOW, <70 MEDIUM, >=70 HIGH) plus CRITICAL at >=85. The test above
  // uses 91 and 20, which fall the same way under any plausible thresholds —
  // which is how the console silently drifted to 80/60/30 and would have
  // relabelled a v1 MEDIUM case as HIGH.
  it.each([
    [39, "LOW"],
    [40, "MEDIUM"],
    [69, "MEDIUM"],
    [70, "HIGH"],
    [84, "HIGH"],
    [85, "CRITICAL"],
  ])("scores %i as %s, matching the v1 risk scorer", (score, expected) => {
    const { cases } = normaliseCases({ cases: [{ id: "c1", risk_score: score }] });
    expect(cases[0].risk_label).toBe(expected);
  });

  it("prefers an explicit backend risk_label over the score fallback", () => {
    const { cases } = normaliseCases({
      cases: [{ id: "c1", risk_score: 10, risk_label: "CRITICAL" }],
    });
    expect(cases[0].risk_label).toBe("CRITICAL");
  });

  it("accepts a bare array", () => {
    expect(normaliseCases([{ id: "c1", case_number: 1 }]).cases).toHaveLength(1);
  });
});

describe("normaliseCaseDetail", () => {
  const wire = {
    case: {
      id: "case-24",
      case_number: 24,
      risk_score: 88,
      transcript: [
        { t: "00:22", speaker: "caller", text: "pindah ke akaun selamat", score: 90,
          novel_phrases: ["akaun selamat"] },
      ],
    },
    mo: { impersonates: "Bank Negara Malaysia", phases: ["authority", "urgency"] },
    entities: [{ id: "e1", entity_type: "account", value_raw: "1592 8834 0021", case_count: 7 }],
    links: [],
    discovery_state: "CLUSTERED",
    campaign: { id: "camp-027", name: "Fake BNM Wave" },
  };

  it("flattens the nested case envelope", () => {
    const out = normaliseCaseDetail(wire, "case-24");
    expect(out.case_number).toBe(24);
    expect(out.discovery_state).toBe("CLUSTERED");
    expect(out.campaign_id).toBe("camp-027");
    expect(out.campaign_name).toBe("Fake BNM Wave");
  });

  it("keeps novel phrases attached to their utterance line", () => {
    const out = normaliseCaseDetail(wire, "case-24");
    expect(out.transcript[0].t).toBe("00:22");
    expect(out.transcript[0].novel_phrases).toEqual(["akaun selamat"]);
    expect(out.transcript[0].speaker).toBe("CALLER");
  });

  it("upper-cases entity types and keeps case counts", () => {
    const out = normaliseCaseDetail(wire, "case-24");
    expect(out.entities[0].entity_type).toBe("ACCOUNT");
    expect(out.entities[0].case_count).toBe(7);
  });

  it("accepts a flat (un-nested) case payload", () => {
    const out = normaliseCaseDetail({ id: "case-9", case_number: 9 }, "case-9");
    expect(out.case_number).toBe(9);
    expect(out.transcript).toEqual([]);
    expect(out.mo).toBeNull();
  });
});

describe("normaliseGraph", () => {
  const wire = {
    nodes: [
      { id: "case-1", kind: "case", label: "#1", campaign_id: "camp-027" },
      { id: "case-2", kind: "case", label: "#2", campaign_id: "camp-027" },
      { id: "ent-1", kind: "entity", entity_type: "account", label: "1592…" },
    ],
    edges: [
      { source: "case-1", target: "ent-1", weight: 1 },
      { source: "case-1", target: "case-2", score: 0.89, signals: { mo: 0.9 } },
    ],
    stats: { node_count: 3 },
  };

  it("renames `edges` to `links` for the force layout", () => {
    const out = normaliseGraph(wire);
    expect(out.links).toHaveLength(2);
    expect(out.nodes).toHaveLength(3);
  });

  it("infers the edge kind from its endpoints", () => {
    const out = normaliseGraph(wire);
    expect(out.links[0].kind).toBe("case-entity");
    expect(out.links[1].kind).toBe("case-case");
  });

  it("reads the weight from `score` when `weight` is absent", () => {
    expect(normaliseGraph(wire).links[1].weight).toBe(0.89);
  });

  it("always produces a why-this-edge-exists reason", () => {
    for (const link of normaliseGraph(wire).links) {
      expect(link.reason.length).toBeGreaterThan(0);
    }
    expect(normaliseGraph(wire).links[1].reason).toContain("mo 0.9");
  });

  it("derives campaign hulls from node membership when none are sent", () => {
    const [hull] = normaliseGraph(wire).hulls;
    expect(hull.campaign_id).toBe("camp-027");
    expect(hull.node_ids).toEqual(["case-1", "case-2"]);
  });
});

describe("normaliseEvents", () => {
  it("accepts a bare array and an envelope, dropping malformed rows", () => {
    const good = makeEvent({ id: 1 });
    expect(normaliseEvents([good, { junk: true }])).toHaveLength(1);
    expect(normaliseEvents({ events: [good] })).toHaveLength(1);
    expect(normaliseEvents({ recent_events: [good] })).toHaveLength(1);
  });
});
