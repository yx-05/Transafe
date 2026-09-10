import { describe, expect, it } from "vitest";
import {
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
