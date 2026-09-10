# TranSafe Enterprise Console

The operator-facing console for TranSafe v2 — seven screens over the
organisational nervous system.

```bash
npm install
npm run dev      # http://localhost:5174, proxies /enterprise → :8000 (ws included)
npm test         # vitest
npm run lint
npm run build
```

## Governing rule

**Every animation is driven by a real `ns_event` from the WebSocket.**
There is no `setInterval`, no CSS keyframe loop, no fake heartbeat anywhere in
`src/`. If the backend is silent, the console is still. The only timers in the
codebase are (a) WebSocket reconnect backoff and (b) `ReplayEventSource`
honouring the *recorded* gaps between real events.

## Layout

```
src/
  components/     Shell, NervousSystem (NerveMap), LiveEventFeed (EventTicker),
                  MetricBar, CaseDetail, ScamGraph, ValidationConsole,
                  ArtifactRegistry, EvalScreen, McpAccessLog,
                  StatusBadge, DiffViewer
  pages/          one thin container per screen (data fetch + routing)
  store/          useEventStore (ring buffer, 500), useCampaignStore
  services/       api.ts (typed /enterprise client), eventSource.ts
                  (Live/Replay), replay.ts, mockData.ts (fixtures)
  hooks/          useWebSocket, useEventSubscription
  types/          events.ts, campaign.ts, api.ts
```

## Screens

| Route | Screen |
| --- | --- |
| `/` | A Overview — nerve map, live ticker, before/after metric bars |
| `/cases/:id` | B Case Detail — transcript with novel phrases marked in place |
| `/graph` | C Scam Graph — force-directed cases + entities, hover an edge for why |
| `/validation/:id` | D Validation Console — computed evidence ⟷ LLM hypothesis |
| `/registry` | E Artifact Registry — CORE / CAMPAIGN PACKS, diff, rollback |
| `/eval` | F Evaluation — paired before/after, FP row at equal weight |
| `/mcp` | G MCP Log — live rows, role selector shows the redaction change |

`M` toggles LIVE ⇄ REPLAY, `R` resets the demo.

## Backend

Talks to the `/enterprise/*` surface in `doc/transafe_v2/01_upgrade_plan.md` §13.
Every call falls back to a fixture in `src/services/mockData.ts` when the
backend is unreachable, so the console is always demoable. Set
`VITE_DISABLE_MOCKS=true` to make failures loud instead.
