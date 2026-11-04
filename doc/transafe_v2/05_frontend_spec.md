# 05 — Enterprise Console Frontend Spec

> **Parent:** `01_upgrade_plan.md` §14
> **Scope:** 7 screens, visual language, component architecture, WebSocket events, animation rules
> **Build blocks:** B0 (shell + live feed), B3 (graph + validation), B4 (registry + diff), B8 (polish)
> **Status:** Implementation-ready

---

## 1. Architecture decision

> ### Decision: build the console as a **separate Vite + React app at `frontend/enterprise`**, deployed independently. Do not extend `frontend/transafe`.

- **Different audience, different auth.** Consumer app = victim. Console = bank staff.
- **Blast-radius isolation.** A crash in the console cannot take down the v1 consumer demo.
- **They must run side by side.** Acts 1 and 5 are split-screen: consumer phone on the left, console on the right. Two apps, two windows — trivial.
- **Same stack as v1** (Vite + React + TS) so components, `services/` API helpers and `types/` can be copied over without a toolchain change. No Next.js.

Shared code is copied, not abstracted into a package. Two days is not the time to introduce a monorepo.

---

## 2. Technology stack

| Concern | Choice | Rationale |
|---|---|---|
| Framework | Vite + React 18 + TypeScript | Same as v1 consumer app |
| Graph visualisation | `react-force-graph-2d` | Force-directed, supports custom node/edge rendering |
| Charts | `recharts` | Simple paired bar charts for eval screen |
| Artifact diff | `diff` npm package + custom renderer | Green/red line-level diff |
| Animation | `framer-motion` | Node pulses, edge travelling dots |
| Real-time | Native `WebSocket` | No Socket.io — adds a dependency for nothing |
| Routing | React Router 6 | Simple — 7 routes |
| State | Zustand | Lightweight, no boilerplate |
| API client | `fetch` + custom `services/` helpers | Same pattern as v1 |

---

## 3. Visual language

> **Governing principle: every animation is driven by a real `ns_event` over the WebSocket. Never a CSS timer.**

If a judge types a scam message at the booth, the dashboard reacts. This single rule is what separates the console from a Figma prototype, and judges test for it.

| Element | Style |
|---|---|
| Background | `#0A0E14` (dark ops console) |
| Accent (alerts) | Amber `#FFB74D` |
| Accent (success) | Green `#4CAF50` |
| Accent (danger) | Red `#EF5350` |
| Text (primary) | `#E0E0E0` |
| Text (secondary) | `#9E9E9E` |
| Monospace (evidence) | `JetBrains Mono` or `Fira Code` |
| Motion | Only when something real happened — driven by `ns_event` |

---

## 4. Directory structure

```
frontend/enterprise/
  src/
    main.tsx
    App.tsx                  # Router + layout shell
    store/
      useEventStore.ts       # Zustand: ns_events, WebSocket connection
      useCampaignStore.ts    # Campaigns, cases, artifacts
    services/
      api.ts                  # REST helpers
      websocket.ts            # /enterprise/ws/events client
    types/
      events.ts               # ns_event type definitions
      campaign.ts             # Campaign, case, artifact types
      api.ts                   # API response types
    components/
      Shell.tsx               # Persistent header + mode badge
      LiveEventFeed.tsx       # Screen A left panel
      NervousSystem.tsx        # Screen A center panel
      MetricBar.tsx            # Screen A bottom panel
      CaseDetail.tsx           # Screen B
      ScamGraph.tsx            # Screen C
      ValidationConsole.tsx    # Screen D
      ArtifactRegistry.tsx     # Screen E
      EvalScreen.tsx           # Screen F
      McpAccessLog.tsx        # Screen G
    hooks/
      useWebSocket.ts
      useEventSubscription.ts
    pages/
      OverviewPage.tsx
      CaseDetailPage.tsx
      GraphPage.tsx
      ValidationPage.tsx
      RegistryPage.tsx
      EvalPage.tsx
      McpLogPage.tsx
  index.html
  vite.config.ts
  package.json
  tsconfig.json
```

---

## 5. WebSocket event store — `store/useEventStore.ts`

```typescript
import { create } from "zustand";

export interface NsEvent {
  id: number;
  ts: string;
  layer: "sensing" | "case" | "discovery" | "compiler" | "registry" | "propagation" | "exposure";
  event_type: string;
  severity: "info" | "warning" | "critical";
  payload: Record<string, unknown>;
  run_id: string | null;
}

interface EventStore {
  events: NsEvent[];
  isConnected: boolean;
  mode: "LIVE" | "REPLAY";
  connect: (url: string) => void;
  disconnect: () => void;
  appendEvent: (event: NsEvent) => void;
  clearEvents: () => void;
  setMode: (mode: "LIVE" | "REPLAY") => void;
}

export const useEventStore = create<EventStore>((set, get) => ({
  events: [],
  isConnected: false,
  mode: "LIVE",

  connect: (url: string) => {
    const ws = new WebSocket(url);
    ws.onopen = () => set({ isConnected: true });
    ws.onclose = () => set({ isConnected: false });
    ws.onmessage = (e) => {
      const event: NsEvent = JSON.parse(e.data);
      get().appendEvent(event);
    };
  },

  disconnect: () => set({ isConnected: false }),

  appendEvent: (event: NsEvent) =>
    set((state) => ({
      events: [...state.events.slice(-499), event],  // keep last 500
    })),

  clearEvents: () => set({ events: [] }),

  setMode: (mode: "LIVE" | "REPLAY") => set({ mode }),
}));
```

---

## 6. Screen specifications

### 6.1 Screen A — Overview (the presentation screen)

```
┌─────────────────────────┬──────────────────────────────────────────────────┐
│ LIVE EVENT FEED         │   ORGANISATIONAL NERVOUS SYSTEM                  │
│ 12:04:11 case #41 in    │                                                  │
│ 12:04:11 ⚡ entity link  │    ┌────────┐   ┌──────┐   ┌───────────┐        │
│          acct 1592…     │    │ SENSING│──▶│ CASE │──▶│ DISCOVERY │        │
│ 12:04:12 case #42 in    │    └────────┘   └──────┘   └─────┬─────┘        │
│ 12:04:13 🔴 CAMPAIGN     │                                   ▼              │
│          PROPOSED (3)   │    ┌────────────┐  ┌──────────┐  ┌──────────┐   │
│ 12:05:02 ✅ validated    │    │ PROPAGATION│◀─│ REGISTRY │◀─│ COMPILER │   │
│          by Fraud Ops   │    └─────┬──────┘  └──────────┘  └──────────┘   │
│ 12:05:04 📦 skill v6→v7  │          │                                       │
│ 12:05:06 → phone_agent  │   ┌───────┼────────┬─────────┐               │
│ 12:05:06 → fraud_ops    │   ▼       ▼        ▼         ▼               │
│ 12:05:06 → phishing     │ [Phone] [FraudOps] [Phishing] [Txn]            │
│ 12:05:06 → txn_monitor  │                                                  │
│ 12:05:14 🌐 CodeBuddy    │   external agentic system — reasons & produces  │
│          ask_transafe() │   own artifacts from TranSafe's intelligence    │
│          → drafts       │                                                  │
│          advisory.txt   │   nodes PULSE · edges animate on real events     │
├─────────────────────────┴──────────────────────────────────────────────────┤
│ TIME TO DISCOVERY    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  before: 24 victims / 9 days         │
│                      ▓▓                 after:   3 victims / 41 minutes    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Components:**
- `LiveEventFeed` — left panel, scrollable list of `ns_events`, newest first
- `NervousSystem` — center panel, SVG graph of 6 layers, nodes pulse amber on their event
- `MetricBar` — bottom panel, before/after discovery time bar chart

**Animation rules:**
- Each node listens to its layer's events
- On matching event: node scales 1.0 → 1.15 → 1.0 over 400ms, colour flashes amber
- Edges animate a travelling dot when a real message passes between layers
- **Never a CSS timer** — all motion is event-driven

### 6.2 Screen B — Case detail (Living Case)

```
Case #24 · Impersonation · HIGH 87 · 🔗 Campaign "Fake BNM Safe-Account Wave"
┌ Transcript ──────────────────────┬ MO Fingerprint ─────────────────────────┐
│ 00:03 CALLER  Saya pegawai…  ▓48 │ Impersonates : Bank Negara Malaysia     │
│ 00:11 USER    Ya, kenapa?    ▓12 │ Pretext      : money-laundering probe   │
│ 00:22 CALLER  akaun selamat  ▓91 │ Phases       : authority▸fear▸isolation │
│               sementara ⚠ NOVEL  │                ▸urgency▸safe-account    │
│ 00:31 AI      Boleh saya…    ▓—  │ Money ask at : 03:07                    │
├──────────────────────────────────┼─────────────────────────────────────────┤
│ Entities  ACCT 1592… (7 cases)   │ Trace ──────────────────────────────────│
│           PHONE +6011… (4 cases) │ orchestrator  ▉ 12ms                    │
│           URL bnm-verify.online  │ phone_worker  ▉▉▉▉▉▉ 840ms  groq 612tok │
│           ↑ click → jump to graph│ research      ▉▉▉▉ 610ms   tavily 3 hits│
│                                  │ scorer ▉ 4ms · xai ▉▉▉ 430ms            │
└──────────────────────────────────┴─────────────────────────────────────────┘
```

**Key detail:** the novel phrase is highlighted **on the exact transcript line it was said**, proving the extraction is grounded rather than invented.

### 6.3 Screen C — Scam Graph

Force-directed, full-bleed. Victims = small grey dots; entities = squares coloured by type; campaigns = translucent hulls. Edge thickness = fused weight. **Hover any edge → why it exists**: `shared ACCOUNT 1592… · w 0.95 · cases #7, #19`. During the wave, nodes fly in and the cluster visibly tightens.

**Library:** `react-force-graph-2d`

**Node types:**
- Case nodes: small grey circles
- Entity nodes: squares coloured by type (PHONE=blue, ACCOUNT=green, URL=orange, DOMAIN=red)
- Campaign nodes: large translucent circles (hulls)

**Edge types:**
- `case→entity`: thin grey lines
- `case↔case`: weighted lines, thickness = fused score
- `campaign→case`: dashed lines

### 6.4 Screen D — Campaign Validation Console

```
┌ CANDIDATE · confidence 0.87 · 6 cases · 4 customers · 41 min span ─────────┐
│ EVIDENCE (computed)             │ HYPOTHESIS (LLM)                        │
│ ✓ 6 cases, 4 distinct customers │ Name: Fake BNM "Safe Account" Wave      │
│ ✓ hard link: ACCT 1592… (×4)    │ MO: caller impersonates a BNM officer,  │
│ ✓ narrative cosine 0.89         │     claims the account is used for      │
│ ✓ span 41 min < 14 d → EMERGING │     laundering, forbids family contact… │
│ ✓ novelty 0.62 < 0.90 → NEW     │ Novel indicators:                       │
│ [mini graph]                    │   • "akaun selamat sementara"           │
│                                 │   • domain pattern bnm-*.online         │
│                                 │ Proposed artifacts:                     │
│                                 │   pack  SCAM-027.json      [view diff]  │
│                                 │   core  phone_agent_core v7 [view diff] │
│                                 │         ↳ generalised from 019·024·027  │
│                                 │   txn_monitor  → block ACCT 1592…       │
│                                 │   compliance  → brief (via MCP)          │
│                                 │   customer_svc → advisory (via MCP)      │
│              [ ✅ Approve ]  [ ✏ Edit ]  [ ❌ Reject ]                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Visual rule:** deterministic evidence on the left, LLM hypothesis on the right, visually separated. An enterprise audience must be able to see which claims are computed and which are generated.

### 6.5 Screen E — Artifact Registry (the strongest single screen)

Two tabs — **CORE** and **CAMPAIGN PACKS** — plus a red/green diff.

```
┌ CORE ─────────────────────────────┬ CAMPAIGN PACKS ────────────────────────┐
│ phone_agent_core                  │ SCAM-027.json   v1  12:05:04  19/20 ✓  │
│   v7  12:05:05  from 3 campaigns  │ SCAM-024.json   v2  09:41     18/20 ✓  │
│       20/20 after adaptation ✓    │ SCAM-019.json   v1  Aug 30    17/20 ✓  │
│   v6  Aug 30    17/20             │                                        │
└───────────────────────────────────┴────────────────────────────────────────┘
```

**Diff view:** green/red line-level diff using the `diff` npm package.

The tab split is doing argumentative work: the packs column grows every campaign, the core column barely moves. That is the scaling answer rendered as a screen.

### 6.6 Screen F — Evaluation

Paired before/after bars on identical inputs, with the false-positive row given equal visual weight.

**Library:** `recharts` — `BarChart` with paired bars.

### 6.7 Screen G — MCP Access Log

```
12:05:14 · codebuddy · ask_transafe(role=legal)  · 340 ms · cited SCAM-027 (6 cases)
12:05:31 · codebuddy · get_campaign(SCAM-027)    · 88 ms  · redacted: acct, PII
```

Rows appear live as CodeBuddy calls in — proof the protocol boundary is real because the caller is a third-party product.

---

## 7. API service helpers — `services/api.ts`

```typescript
const API_BASE = "/enterprise";

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

async function postJSON<T>(path: string, body: unknown): Promise<T> => {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

export const api = {
  // Overview
  getOverview: () => fetchJSON<OverviewResponse>("/overview"),

  // Cases
  getCases: (filters?: CaseFilters) =>
    fetchJSON<CasesResponse>(`/cases${toQuery(filters)}`),
  getCase: (id: string) =>
    fetchJSON<CaseDetail>(`/cases/${id}`),

  // Graph
  getGraph: () => fetchJSON<GraphData>("/graph"),

  // Campaigns
  getCampaigns: () => fetchJSON<CampaignsResponse>("/campaigns"),
  getCampaign: (id: string) =>
    fetchJSON<CampaignDetail>(`/campaigns/${id}`),
  approveCampaign: (id: string) =>
    postJSON(`/campaigns/${id}/approve`, {}),
  rejectCampaign: (id: string, reason: string) =>
    postJSON(`/campaigns/${id}/reject`, { reason }),
  editCampaign: (id: string, edits: Record<string, unknown>) =>
    fetchJSON<CampaignDetail>(`/campaigns/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(edits),
    }),

  // Artifacts
  getArtifacts: (tier?: "core" | "pack") =>
    fetchJSON<ArtifactsResponse>(`/artifacts${tier ? `?tier=${tier}` : ""}`),
  getArtifact: (name: string, version?: number) =>
    fetchJSON<ArtifactDetail>(`/artifacts/${name}/${version ?? "latest"}`),
  rollbackArtifact: (name: string) =>
    postJSON(`/artifacts/${name}/rollback`, {}),

  // Discovery
  runDiscovery: () => postJSON("/discovery/run", {}),

  // Eval
  runEval: () => postJSON<EvalRunResponse>("/eval/run", {}),
  getLatestEval: () => fetchJSON<EvalComparison>("/eval/latest"),

  // MCP
  getMcpLog: () => fetchJSON<McpLogResponse>("/mcp/log"),

  // Demo
  startScenario: (mode: "live" | "replay", speed?: number) =>
    postJSON("/demo/scenario", { mode, speed }),
  resetDemo: () => postJSON("/demo/reset", {}),
};

function toQuery(params?: Record<string, unknown>): string {
  if (!params) return "";
  const pairs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}
```

---

## 8. WebSocket client — `services/websocket.ts`

```typescript
import { useEventStore } from "../store/useEventStore";

const WS_BASE =
  import.meta.env.VITE_WS_URL || `ws://${window.location.host}/enterprise/ws/events`;

export function connectWebSocket(): void {
  const store = useEventStore.getState();
  store.connect(WS_BASE);
}

export function disconnectWebSocket(): void {
  const store = useEventStore.getState();
  store.disconnect();
}
```

---

## 9. Component: NervousSystem — `components/NervousSystem.tsx`

```tsx
import { motion } from "framer-motion";
import { useEventStore } from "../store/useEventStore";

interface LayerNode {
  id: string;
  label: string;
  layer: string;
  x: number;
  y: number;
}

const NODES: LayerNode[] = [
  { id: "sensing", label: "SENSING", layer: "sensing", x: 100, y: 50 },
  { id: "case", label: "CASE", layer: "case", x: 250, y: 50 },
  { id: "discovery", label: "DISCOVERY", layer: "discovery", x: 420, y: 50 },
  { id: "compiler", label: "COMPILER", layer: "compiler", x: 590, y: 100 },
  { id: "registry", label: "REGISTRY", layer: "registry", x: 590, y: 50 },
  { id: "propagation", label: "PROPAGATION", layer: "propagation", x: 420, y: 150 },
];

const EDGES: [string, string][] = [
  ["sensing", "case"],
  ["case", "discovery"],
  ["discovery", "compiler"],
  ["compiler", "registry"],
  ["registry", "propagation"],
];

export function NervousSystem() {
  const events = useEventStore((s) => s.events);

  // Find the latest event for each layer
  const latestByLayer: Record<string, typeof events[0]> = {};
  for (const evt of events) {
    if (!latestByLayer[evt.layer]) {
      latestByLayer[evt.layer] = evt;
    }
  }

  return (
    <svg viewBox="0 0 700 200" className="w-full h-full">
      {EDGES.map(([src, dst]) => {
        const srcNode = NODES.find((n) => n.id === src)!;
        const dstNode = NODES.find((n) => n.id === dst)!;
        return (
          <line
            key={`${src}-${dst}`}
            x1={srcNode.x}
            y1={srcNode.y}
            x2={dstNode.x}
            y2={dstNode.y}
            stroke="#333"
            strokeWidth={2}
          />
        );
      })}

      {NODES.map((node) => {
        const isActive = !!latestByLayer[node.layer];
        return (
          <motion.g
            key={node.id}
            initial={{ scale: 1 }}
            animate={{
              scale: isActive ? [1, 1.15, 1] : 1,
              fill: isActive ? "#FFB74D" : "#333",
            }}
            transition={{ duration: 0.4 }}
            style={{ transformOrigin: `${node.x}px ${node.y}px` }}
          >
            <rect
              x={node.x - 50}
              y={node.y - 20}
              width={100}
              height={40}
              rx={8}
              fill={isActive ? "#FFB74D" : "#1A1F2E"}
              stroke="#333"
            />
            <text
              x={node.x}
              y={node.y + 5}
              textAnchor="middle"
              fill={isActive ? "#000" : "#9E9E9E"}
              fontSize={12}
              fontFamily="monospace"
            >
              {node.label}
            </text>
          </motion.g>
        );
      })}
    </svg>
  );
}
```

---

## 10. REPLAY / LIVE mode

| Mode | Use | Behaviour |
|---|---|---|
| **REPLAY** | The timed pitch (~6 min) | Streams a **recorded** `ns_events` sequence at controlled speed. No LLM calls, no network, no rate limits, deterministic. |
| **LIVE** | The booth | Full pipeline. A judge types their own scam message; every layer runs for real. |

**How they stay honest:**
1. Same UI, same event schema, same WebSocket. The only difference is the event source — an `EventSource` abstraction with `LiveEventSource` and `ReplayEventSource`.
2. REPLAY must be recorded from a real LIVE run.
3. The mode badge is always visible.
4. One-key switch, plus `↺ Reset` returning to clean pre-campaign state in under 2 seconds.

```typescript
// services/eventSource.ts
export interface EventSource {
  connect: (onEvent: (e: NsEvent) => void) => void;
  disconnect: () => void;
}

export class LiveEventSource implements EventSource {
  private ws: WebSocket | null = null;
  connect(onEvent: (e: NsEvent) => void) {
    this.ws = new WebSocket(WS_BASE);
    this.ws.onmessage = (e) => onEvent(JSON.parse(e.data));
  }
  disconnect() {
    this.ws?.close();
  }
}

export class ReplayEventSource implements EventSource {
  private events: NsEvent[] = [];
  private timer: number | null = null;
  private speed: number = 1;

  constructor(events: NsEvent[], speed: number = 1) {
    this.events = events;
    this.speed = speed;
  }

  connect(onEvent: (e: NsEvent) => void) {
    let index = 0;
    const playNext = () => {
      if (index >= this.events.length) return;
      onEvent(this.events[index]);
      index++;
      const next = this.events[index];
      if (next) {
        const prev = this.events[index - 1];
        const delay =
          (new Date(next.ts).getTime() - new Date(prev.ts).getTime()) /
          this.speed;
        this.timer = window.setTimeout(playNext, Math.max(delay, 100));
      }
    };
    playNext();
  }

  disconnect() {
    if (this.timer) clearTimeout(this.timer);
  }
}
```

---

## 11. Testing

### 11.1 Test files

Frontend tests use Vitest + React Testing Library.

| Component | Test file | Cases |
|---|---|---|
| Event store | `src/store/__tests__/useEventStore.test.ts` | 5 |
| API helpers | `src/services/__tests__/api.test.ts` | 6 |
| WebSocket | `src/services/__tests__/websocket.test.ts` | 3 |
| NervousSystem | `src/components/__tests__/NervousSystem.test.tsx` | 4 |
| LiveEventFeed | `src/components/__tests__/LiveEventFeed.test.tsx` | 3 |
| ArtifactRegistry | `src/components/__tests__/ArtifactRegistry.test.tsx` | 4 |
| ValidationConsole | `src/components/__tests__/ValidationConsole.test.tsx` | 4 |
| EventSource | `src/services/__tests__/eventSource.test.ts` | 4 |

### 11.2 Example tests — `useEventStore.test.ts`

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useEventStore } from "../useEventStore";
import type { NsEvent } from "../../types/events";

const mockEvent: NsEvent = {
  id: 1,
  ts: "2026-09-10T12:04:11Z",
  layer: "discovery",
  event_type: "campaign_proposed",
  severity: "info",
  payload: { campaign_id: "c1" },
  run_id: null,
};

describe("useEventStore", () => {
  beforeEach(() => {
    useEventStore.setState({ events: [], isConnected: false, mode: "LIVE" });
  });

  it("appends events", () => {
    useEventStore.getState().appendEvent(mockEvent);
    expect(useEventStore.getState().events).toHaveLength(1);
  });

  it("limits to 500 events", () => {
    const events = Array.from({ length: 501 }, (_, i) => ({
      ...mockEvent,
      id: i + 1,
    }));
    events.forEach((e) => useEventStore.getState().appendEvent(e));
    expect(useEventStore.getState().events).toHaveLength(500);
    expect(useEventStore.getState().events[499].id).toBe(501);
  });

  it("clears events", () => {
    useEventStore.getState().appendEvent(mockEvent);
    useEventStore.getState().clearEvents();
    expect(useEventStore.getState().events).toHaveLength(0);
  });

  it("sets mode", () => {
    useEventStore.getState().setMode("REPLAY");
    expect(useEventStore.getState().mode).toBe("REPLAY");
  });

  it("sets connection status", () => {
    useEventStore.getState().disconnect();
    expect(useEventStore.getState().isConnected).toBe(false);
  });
});
```

### 11.3 Example tests — `NervousSystem.test.tsx`

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NervousSystem } from "../NervousSystem";
import { useEventStore } from "../../store/useEventStore";

describe("NervousSystem", () => {
  it("renders all 6 layer nodes", () => {
    render(<NervousSystem />);
    expect(screen.getByText("SENSING")).toBeInTheDocument();
    expect(screen.getByText("CASE")).toBeInTheDocument();
    expect(screen.getByText("DISCOVERY")).toBeInTheDocument();
    expect(screen.getByText("COMPILER")).toBeInTheDocument();
    expect(screen.getByText("REGISTRY")).toBeInTheDocument();
    expect(screen.getByText("PROPAGATION")).toBeInTheDocument();
  });

  it("renders edges between nodes", () => {
    const { container } = render(<NervousSystem />);
    const lines = container.querySelectorAll("line");
    expect(lines.length).toBeGreaterThanOrEqual(5);
  });

  it("does not crash with empty events", () => {
    useEventStore.setState({ events: [] });
    render(<NervousSystem />);
    expect(screen.getByText("SENSING")).toBeInTheDocument();
  });

  it("activates node on matching layer event", () => {
    useEventStore.setState({
      events: [{
        id: 1, ts: "2026-09-10T12:00:00Z", layer: "discovery",
        event_type: "test", severity: "info", payload: {}, run_id: null,
      }],
    });
    const { container } = render(<NervousSystem />);
    // The discovery node should have an amber fill after animation
    const rects = container.querySelectorAll("rect");
    expect(rects.length).toBeGreaterThan(0);
  });
});
```

### 11.4 Example tests — `eventSource.test.ts`

```typescript
import { describe, it, expect, vi } from "vitest";
import { ReplayEventSource } from "../eventSource";
import type { NsEvent } from "../../types/events";

describe("ReplayEventSource", () => {
  const events: NsEvent[] = [
    { id: 1, ts: "2026-09-10T12:00:00Z", layer: "case", event_type: "ingested", severity: "info", payload: {}, run_id: "r1" },
    { id: 2, ts: "2026-09-10T12:00:01Z", layer: "discovery", event_type: "linked", severity: "info", payload: {}, run_id: "r1" },
  ];

  it("calls onEvent for each event", () => {
    const source = new ReplayEventSource(events, 1000); // very fast
    const callback = vi.fn();
    source.connect(callback);
    // First event should be immediate
    expect(callback).toHaveBeenCalledWith(events[0]);
  });

  it("disconnect stops playback", () => {
    const source = new ReplayEventSource(events, 1);
    const callback = vi.fn();
    source.connect(callback);
    source.disconnect();
    expect(callback).toHaveBeenCalledTimes(1); // only the first immediate event
  });

  it("handles empty events array", () => {
    const source = new ReplayEventSource([], 1);
    const callback = vi.fn();
    source.connect(callback);
    expect(callback).not.toHaveBeenCalled();
  });

  it("plays events in order", () => {
    const source = new ReplayEventSource(events, 10000);
    const callback = vi.fn();
    source.connect(callback);
    expect(callback.mock.calls[0][0].id).toBe(1);
  });
});
```

### 11.5 Vitest configuration

Add to `frontend/enterprise/package.json`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run",
    "lint": "eslint src/"
  },
  "devDependencies": {
    "vitest": "^2.0.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "jsdom": "^24.0.0",
    "@typescript-eslint/eslint-plugin": "^8.0.0",
    "eslint": "^9.0.0"
  }
}
```

Add `vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
```

Run tests:

```bash
cd frontend/enterprise && npm test
```

Run lint:

```bash
cd frontend/enterprise && npm run lint
```
