# 06 — Demo Runbook

> **Parent:** `01_upgrade_plan.md` §15
> **Scope:** 5-act demo structure, seed corpus, REPLAY/LIVE modes, setup and teardown
> **Build block:** B8 (polish + demo prep)
> **Status:** Implementation-ready

---

## 1. Demo structure — 5 acts

| Act | Duration | Mode | Screen | What happens |
|---|---|---|---|---|
| 1 | 90s | REPLAY | A+B split | Victim phone call (left) → console ingests, MO extracts, entities link (right) |
| 2 | 60s | REPLAY | A | Campaign discovery: cases cluster → cluster tightens → candidate proposed |
| 3 | 90s | LIVE | C+D split | Judge types own scam → graph shows real-time → validation console → approve |
| 4 | 60s | REPLAY | E | Artifact compiled, versioned, diffed, propagated to 3 workers |
| 5 | 60s | LIVE | A+B split | CodeBuddy calls MCP → Liaison Agent answers → CodeBuddy drafts advisory |

**Total: ~6 minutes.** The timing is tight by design — it forces the story to move.

---

## 2. Seed corpus

### 2.1 Requirements

- **10 synthetic transcripts** — 6 belong to the SCAM-027 wave, 4 are noise
- All from **fictional** victims, **fictional** accounts, **fictional** domains
- Wave cases share: one mule account, one domain pattern, similar MO (authority_claim + isolation + safe_account_instruction)
- Noise cases: different scam types (phishing, investment, romance), no shared identifiers with wave
- Each transcript is 20-40 utterances, mixed Malay/English
- Each has known-ground-truth MO fingerprint for evaluation

### 2.2 Corpus structure

```
backend/seeds/
  transcripts/
    scam027_001.json    # Wave case 1
    scam027_002.json    # Wave case 2
    scam027_003.json    # Wave case 3
    scam027_004.json    # Wave case 4
    scam027_005.json    # Wave case 5
    scam027_006.json    # Wave case 6
    noise_phish_001.json  # Noise: phishing
    noise_phish_002.json  # Noise: phishing
    noise_invest_001.json # Noise: investment scam
    noise_romance_001.json # Noise: romance scam
  ground_truth/
    scam027_truth.json  # Expected MO, entities, campaign, artifacts
  ns_events/
    replay_sequence.json  # Pre-recorded ns_events for REPLAY mode
```

### 2.3 Sample transcript — `scam027_001.json`

```json
{
  "case_id": "seed-001",
  "victim_name": "Ahmad Rahman (FICTIONAL)",
  "scenario": "Fake BNM Safe-Account",
  "transcript": [
    {"seq_idx": 0, "speaker": "CALLER", "utterance": "Selamat sejahtera, saya pegawai dari Bank Negara Malaysia. Nama saya Haji Ismail.", "risk_score": 30},
    {"seq_idx": 1, "speaker": "USER", "utterance": "Ya, apa halnya?", "risk_score": 10},
    {"seq_idx": 2, "speaker": "CALLER", "utterance": "Kita ada laporan bahawa akaun anda terlibat dalam kesalahan pengubahan wang haram.", "risk_score": 45},
    {"seq_idx": 3, "speaker": "USER", "utterance": "Apa? Tak mungkin!", "risk_score": 15},
    {"seq_idx": 4, "speaker": "CALLER", "utterance": "Untuk melindungi akaun anda, anda perlu pindahkan wang ke akaun selamat sementara kita siaskan siasatan.", "risk_score": 85},
    {"seq_idx": 5, "speaker": "CALLER", "utterance": "Jangan beritahu keluarga anda tentang ini. Ia siasatan sulit.", "risk_score": 90},
    {"seq_idx": 6, "speaker": "CALLER", "utterance": "Akaun selamat sementara: 1592-3456-7890-1234, Maybank.", "risk_score": 95},
    {"seq_idx": 7, "speaker": "USER", "utterance": "Tapi...", "risk_score": 20},
    {"seq_idx": 8, "speaker": "CALLER", "utterance": "Cepat, jika tidak, kita akan membekukan akaun anda.", "risk_score": 88},
    {"seq_idx": 9, "speaker": "AI_AGENT", "utterance": "Tuan, ini kelihatan seperti penipuan. Bank Negara tidak akan meminta anda memindahkan wang ke akaun lain. Sila tutup panggilan ini.", "risk_score": 0}
  ],
  "expected_entities": [
    {"entity_type": "ACCOUNT", "value": "1592-3456-7890-1234"},
    {"entity_type": "NAME", "value": "Haji Ismail"},
    {"entity_type": "NAME", "value": "Bank Negara Malaysia"}
  ],
  "expected_mo": {
    "impersonated_entity": "Bank Negara Malaysia",
    "pretext": "money laundering investigation",
    "script_phases": ["authority_claim", "fear_induction", "isolation", "urgency", "safe_account_instruction"],
    "pressure_tactics": ["arrest threat", "do not tell family", "stay on the line"],
    "novel_phrases": [{"text": "akaun selamat sementara", "lang": "ms"}],
    "languages": ["ms", "en"]
  }
}
```

### 2.4 REPLAY event sequence — `replay_sequence.json`

This file is a recording of `ns_events` from a real LIVE run of the seed corpus. It is what REPLAY mode streams.

```json
[
  {"ts": "2026-09-10T12:04:11Z", "layer": "sensing", "event_type": "case_ingested", "severity": "info", "payload": {"case_id": "seed-001", "risk_tier": "HIGH"}},
  {"ts": "2026-09-10T12:04:12Z", "layer": "case", "event_type": "mo_extracted", "severity": "info", "payload": {"case_id": "seed-001", "impersonated_entity": "Bank Negara Malaysia"}},
  {"ts": "2026-09-10T12:04:13Z", "layer": "case", "event_type": "entity_linked", "severity": "info", "payload": {"case_id": "seed-001", "entity_type": "ACCOUNT", "value_norm": "1592345678901234"}},
  {"ts": "2026-09-10T12:04:14Z", "layer": "sensing", "event_type": "case_ingested", "severity": "info", "payload": {"case_id": "seed-002", "risk_tier": "HIGH"}},
  {"ts": "2026-09-10T12:04:15Z", "layer": "case", "event_type": "mo_extracted", "severity": "info", "payload": {"case_id": "seed-002", "impersonated_entity": "Bank Negara Malaysia"}},
  {"ts": "2026-09-10T12:04:16Z", "layer": "case", "event_type": "entity_linked", "severity": "info", "payload": {"case_id": "seed-002", "entity_type": "ACCOUNT", "value_norm": "1592345678901234"}},
  {"ts": "2026-09-10T12:04:17Z", "layer": "sensing", "event_type": "case_ingested", "severity": "info", "payload": {"case_id": "seed-003", "risk_tier": "HIGH"}},
  {"ts": "2026-09-10T12:04:18Z", "layer": "case", "event_type": "mo_extracted", "severity": "info", "payload": {"case_id": "seed-003"}},
  {"ts": "2026-09-10T12:04:19Z", "layer": "case", "event_type": "entity_linked", "severity": "info", "payload": {"case_id": "seed-003", "entity_type": "ACCOUNT", "value_norm": "1592345678901234"}},
  {"ts": "2026-09-10T12:04:30Z", "layer": "discovery", "event_type": "link_scored", "severity": "info", "payload": {"case_a": "seed-001", "case_b": "seed-002", "score": 0.95}},
  {"ts": "2026-09-10T12:04:31Z", "layer": "discovery", "event_type": "link_scored", "severity": "info", "payload": {"case_a": "seed-002", "case_b": "seed-003", "score": 0.92}},
  {"ts": "2026-09-10T12:04:32Z", "layer": "discovery", "event_type": "link_scored", "severity": "info", "payload": {"case_a": "seed-001", "case_b": "seed-003", "score": 0.91}},
  {"ts": "2026-09-10T12:04:35Z", "layer": "discovery", "event_type": "campaign_proposed", "severity": "critical", "payload": {"campaign_id": "camp-001", "code": "SCAM-027", "case_count": 3, "confidence": 0.87}},
  {"ts": "2026-09-10T12:05:02Z", "layer": "discovery", "event_type": "campaign_validated", "severity": "info", "payload": {"campaign_id": "camp-001", "validated_by": "fraud_ops"}},
  {"ts": "2026-09-10T12:05:04Z", "layer": "compiler", "event_type": "artifacts_compiled", "severity": "info", "payload": {"campaign_id": "camp-001", "artifact_types": ["campaign_pack", "phishing_playbook_patch", "txn_rule", "compliance_brief", "cs_advisory"]}},
  {"ts": "2026-09-10T12:05:05Z", "layer": "registry", "event_type": "artifact_published", "severity": "info", "payload": {"artifact_name": "SCAM-027", "version": 1, "tier": "pack"}},
  {"ts": "2026-09-10T12:05:05Z", "layer": "registry", "event_type": "artifact_published", "severity": "info", "payload": {"artifact_name": "phone_agent_core", "version": 7, "tier": "core", "source_campaigns": ["SCAM-019", "SCAM-024", "SCAM-027"]}},
  {"ts": "2026-09-10T12:05:06Z", "layer": "propagation", "event_type": "propagation_event", "severity": "info", "payload": {"artifact_name": "SCAM-027", "agent_name": "phone_worker"}},
  {"ts": "2026-09-10T12:05:06Z", "layer": "propagation", "event_type": "propagation_event", "severity": "info", "payload": {"artifact_name": "SCAM-027", "agent_name": "phishing_worker"}},
  {"ts": "2026-09-10T12:05:06Z", "layer": "propagation", "event_type": "propagation_event", "severity": "info", "payload": {"artifact_name": "SCAM-027", "agent_name": "financial_worker"}},
  {"ts": "2026-09-10T12:05:06Z", "layer": "propagation", "event_type": "propagation_acknowledged", "severity": "info", "payload": {"artifact_name": "SCAM-027", "agent_name": "phone_worker"}},
  {"ts": "2026-09-10T12:05:14Z", "layer": "exposure", "event_type": "mcp_call", "severity": "info", "payload": {"caller": "codebuddy", "tool": "ask_transafe", "role": "legal"}},
  {"ts": "2026-09-10T12:05:15Z", "layer": "exposure", "event_type": "mcp_response", "severity": "info", "payload": {"caller": "codebuddy", "cited_campaign": "SCAM-027", "citations": 6}}
]
```

---

## 3. Act-by-act script

### Act 1 — The Victim (90s, REPLAY, Screen A+B split)

**What the audience sees:**
- Left screen: consumer phone call transcript scrolls. Caller impersonates BNM officer, demands transfer to "safe account".
- Right screen: console ingests case. `case_ingested` event → SENSING node pulses. `mo_extracted` → CASE node pulses. Novel phrase "akaun selamat sementara" highlighted on the exact transcript line.
- Entity link appears: account `1592…` links to 7 prior cases → graph edge draws.

**Narration:**
> "A victim receives a call. TranSafe's phone agent intercepts in real time — under 2 seconds. But what happens after the call ends is the enterprise story. The MO fingerprint is extracted, entities are resolved, and the case enters the institutional fraud memory."

**Key moment:** novel phrase highlighted on transcript line.

### Act 2 — Discovery (60s, REPLAY, Screen A)

**What the audience sees:**
- Three more cases stream in (seed-002, 003, 004).
- Graph view: grey dots fly in, edges draw between cases sharing the same account.
- Cluster tightens visibly.
- `campaign_proposed` event → DISCOVERY node pulses amber.
- Validation console slides in: confidence 0.87, 3 cases, 2 customers, 41-minute span.

**Narration:**
> "Within 41 minutes, three cases from three different victims cluster into a campaign candidate. Confidence 0.87 — anchored on a shared mule account, narrative cosine 0.89, and structural MO overlap."

**Key moment:** cluster visibly tightens on screen.

### Act 3 — The Judge's Scam (90s, LIVE, Screen C+D split)

**What the audience sees:**
- Judge at the booth types their own scam message (or selects from a menu of 3 preset variants).
- Graph view: case ingested in real time, entity linked, scored against existing cases.
- Validation console: shows the evidence (left: computed) vs hypothesis (right: LLM).
- Fraud Ops clicks ✅ Approve.

**Narration:**
> "Now we go live. Type your own scam — or pick a variant. Watch the graph react in real time. The evidence on the left is computed: shared identifiers, narrative similarity, temporal proximity. The hypothesis on the right is LLM-generated. They are visually separated so you can see which is which."

**Key moment:** judge's own input appears on screen, case links to the existing campaign in real time.

### Act 4 — The Defence Compiles (60s, REPLAY, Screen E)

**What the audience sees:**
- Artifact registry screen: SCAM-027 pack artifacts published (5 types).
- `phone_agent_core` v6 → v7 diff appears — the generaliser found a cross-campaign rule.
- Propagation events: phone_worker, phishing_worker, financial_worker all acknowledge.
- Consumption receipts appear as green checkmarks.

**Narration:**
> "The campaign is approved. The compiler produces five pack-tier artifacts — one per target. The generaliser found a cross-campaign rule, so the core skill goes from v6 to v7. Notice: the pack column grows every campaign. The core column barely moves. That is the scaling answer."

**Key moment:** green/red diff on `phone_agent_core` v6→v7.

### Act 5 — CodeBuddy (60s, LIVE, Screen A+B split)

**What the audience sees:**
- Left: CodeBuddy calls `ask_transafe("What fraud campaigns are active?")`.
- MCP access log row appears: `codebuddy · ask_transafe(role=legal) · 340ms · cited SCAM-027`.
- Liaison Agent retrieves, redacts by role, synthesises answer with citations.
- CodeBuddy receives the answer, reasons about it, drafts a customer advisory.

**Narration:**
> "A third-party agent — CodeBuddy — calls TranSafe through the MCP gateway. The Liaison Agent retrieves what's relevant, redacts by role, and answers with citations. CodeBuddy reasons about the answer and produces its own artifact — a customer advisory. TranSafe does not control CodeBuddy. It exposes intelligence. That is the boundary."

**Key moment:** CodeBuddy's advisory appears on screen, grounded in TranSafe's citations.

---

## 4. Setup

### 4.1 Pre-demo checklist

```bash
# 1. Start backend
cd backend && uv run uvicorn src.api.main:app --reload --port 8000

# 2. Seed the database
cd backend && uv run python scripts/seed_corpus.py

# 3. Record REPLAY sequence (run once, then reuse)
cd backend && uv run python scripts/record_replay.py

# 4. Start consumer app (left screen)
cd frontend/transafe && npm run dev -- --port 5173

# 5. Start enterprise console (right screen)
cd frontend/enterprise && npm run dev -- --port 5174

# 6. Configure CodeBuddy MCP
# Add transafe MCP server config to CodeBuddy settings

# 7. Open both in browser, arrange side by side
open http://localhost:5173  # consumer
open http://localhost:5174  # console
```

### 4.2 Seed script — `scripts/seed_corpus.py`

```python
"""Seed the database with the synthetic fraud corpus for demo."""

import json
from pathlib import Path

SEEDS_DIR = Path(__file__).parent.parent / "seeds"


def seed_corpus():
    """Load and insert all seed transcripts into the database."""
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    transcripts_dir = SEEDS_DIR / "transcripts"

    for transcript_file in sorted(transcripts_dir.glob("*.json")):
        with open(transcript_file) as f:
            data = json.load(f)

        # Insert fraud case
        case_row = {
            "id": data["case_id"],
            "risk_tier": "HIGH",
            "transcript": data["transcript"],
            "created_at": "2026-09-10T12:04:11Z",
        }
        client.table("fraud_cases").upsert(case_row).execute()

        print(f"Seeded: {transcript_file.name} → {data['case_id']}")


if __name__ == "__main__":
    seed_corpus()
    print("Seed corpus loaded.")
```

### 4.3 REPLAY recording script — `scripts/record_replay.py`

```python
"""Run a LIVE demo scenario and record all ns_events for REPLAY mode."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from enterprise.events import emit_event


async def record_replay():
    """Run the seed corpus through the pipeline and record all events."""
    run_id = f"replay-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    # Load seed transcripts
    seeds_dir = Path(__file__).parent.parent / "seeds" / "transcripts"
    all_events = []

    # Simulate case ingestion
    for tf in sorted(seeds_dir.glob("scam027_*.json")):
        with open(tf) as f:
            data = json.load(f)

        case_id = data["case_id"]
        await emit_event("sensing", "case_ingested", {"case_id": case_id, "risk_tier": "HIGH"}, run_id=run_id)
        await emit_event("case", "mo_extracted", {"case_id": case_id, "impersonated_entity": "BNM"}, run_id=run_id)
        await emit_event("case", "entity_linked", {"case_id": case_id, "entity_type": "ACCOUNT"}, run_id=run_id)

    # Simulate discovery
    await emit_event("discovery", "campaign_proposed", {"campaign_id": "camp-001", "code": "SCAM-027", "confidence": 0.87}, severity="critical", run_id=run_id)
    await emit_event("discovery", "campaign_validated", {"campaign_id": "camp-001"}, run_id=run_id)

    # Simulate compilation + propagation
    await emit_event("compiler", "artifacts_compiled", {"campaign_id": "camp-001"}, run_id=run_id)
    await emit_event("registry", "artifact_published", {"artifact_name": "SCAM-027", "version": 1}, run_id=run_id)
    await emit_event("registry", "artifact_published", {"artifact_name": "phone_agent_core", "version": 7}, run_id=run_id)
    await emit_event("propagation", "propagation_event", {"artifact_name": "SCAM-027", "agent_name": "phone_worker"}, run_id=run_id)
    await emit_event("propagation", "propagation_acknowledged", {"artifact_name": "SCAM-027", "agent_name": "phone_worker"}, run_id=run_id)

    # Simulate MCP call
    await emit_event("exposure", "mcp_call", {"caller": "codebuddy", "tool": "ask_transafe"}, run_id=run_id)
    await emit_event("exposure", "mcp_response", {"caller": "codebuddy", "cited_campaign": "SCAM-027"}, run_id=run_id)

    # Save events
    output = SEEDS_DIR.parent / "ns_events" / "replay_sequence.json"
    output.parent.mkdir(exist_ok=True)
    # Fetch all events with this run_id
    from enterprise.events import get_events
    events = get_events(run_id=run_id, limit=1000)
    with open(output, "w") as f:
        json.dump(events, f, indent=2)

    print(f"Recorded {len(events)} events → {output}")


if __name__ == "__main__":
    asyncio.run(record_replay())
```

---

## 5. Demo API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/enterprise/api/demo/scenario` | POST | Start a demo scenario (`{mode, speed}`) |
| `/enterprise/api/demo/reset` | POST | Reset to clean pre-campaign state |
| `/enterprise/api/demo/seed` | POST | Re-seed the corpus |
| `/enterprise/api/overview` | GET | Dashboard overview stats |
| `/enterprise/api/cases` | GET | List cases with filters |
| `/enterprise/api/cases/:id` | GET | Case detail with MO + entities + trace |
| `/enterprise/api/graph` | GET | Full graph data (nodes + edges) |
| `/enterprise/api/campaigns` | GET | List campaigns |
| `/enterprise/api/campaigns/:id` | GET | Campaign detail |
| `/enterprise/api/campaigns/:id/approve` | POST | Approve a campaign |
| `/enterprise/api/campaigns/:id/reject` | POST | Reject a campaign |
| `/enterprise/api/artifacts` | GET | List artifacts (filter by tier) |
| `/enterprise/api/artifacts/:name/:version` | GET | Artifact detail with diff |
| `/enterprise/api/artifacts/:name/rollback` | POST | Rollback artifact |
| `/enterprise/api/discovery/run` | POST | Force discovery sweep |
| `/enterprise/api/eval/run` | POST | Run evaluation |
| `/enterprise/api/eval/latest` | GET | Latest eval comparison |
| `/enterprise/api/mcp/log` | GET | MCP access log |
| `/enterprise/ws/events` | WS | WebSocket for live ns_events |

---

## 6. Demo controller — `backend/src/api/demo.py`

```python
"""Demo scenario controller for the enterprise console."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/enterprise/api/demo", tags=["demo"])

SEEDS_DIR = Path(__file__).parent.parent.parent.parent / "seeds"


@router.post("/scenario")
async def start_scenario(mode: str = "replay", speed: float = 1.0):
    """Start a demo scenario in REPLAY or LIVE mode.

    Args:
        mode: "replay" or "live".
        speed: Playback speed for REPLAY mode.
    """
    if mode == "replay":
        return await _start_replay(speed)
    elif mode == "live":
        return {"status": "live", "message": "Live mode active. Ingest cases to see real-time processing."}
    else:
        return {"error": f"Unknown mode: {mode}"}


async def _start_replay(speed: float) -> dict[str, Any]:
    """Stream pre-recorded ns_events at controlled speed."""
    replay_file = SEEDS_DIR / "ns_events" / "replay_sequence.json"
    if not replay_file.exists():
        return {"error": "No replay sequence found. Run scripts/record_replay.py first."}

    with open(replay_file) as f:
        events = json.load(f)

    # Start streaming in background
    asyncio.create_task(_stream_replay_events(events, speed))
    return {"status": "replay", "event_count": len(events), "speed": speed}


async def _stream_replay_events(events: list[dict[str, Any]], speed: float) -> None:
    """Stream replay events to the WebSocket."""
    from enterprise.events import emit_event

    for event in events:
        await emit_event(
            layer=event["layer"],
            event_type=event["event_type"],
            payload=event.get("payload", {}),
            severity=event.get("severity", "info"),
            run_id=f"replay-{datetime.now().strftime('%H%M%S')}",
        )
        await asyncio.sleep(0.5 / speed)  # 500ms per event at 1x speed


@router.post("/reset")
async def reset_demo():
    """Reset to clean pre-campaign state."""
    from db.vector_store import get_supabase_client

    client = get_supabase_client()

    # Clear enterprise tables
    for table in [
        "ns_events",
        "campaign_cases",
        "campaigns",
        "case_links",
        "case_entity_links",
        "case_mo",
        "case_discovery_state",
        "entities",
        "artifacts",
        "artifact_consumption",
        "mcp_access_log",
    ]:
        try:
            client.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        except Exception:
            pass

    return {"status": "reset", "message": "All enterprise data cleared."}


@router.post("/seed")
async def seed_database():
    """Re-seed the synthetic fraud corpus."""
    from scripts.seed_corpus import seed_corpus
    seed_corpus()
    return {"status": "seeded", "message": "Corpus loaded."}


# ── WebSocket ─────────────────────────────────────────────────────────

@router.websocket("/enterprise/ws/events")
async def websocket_events(websocket: WebSocket):
    """Stream ns_events to the enterprise console in real time."""
    await websocket.accept()

    # Poll ns_events table and stream new events
    from db.vector_store import get_supabase_client
    import time

    client = get_supabase_client()
    last_ts = "1970-01-01T00:00:00Z"

    try:
        while True:
            result = client.table("ns_events").select("*").gt(
                "ts", last_ts
            ).order("ts", desc=False).limit(50).execute()

            for event in result.data or []:
                await websocket.send_json(event)
                last_ts = event["ts"]

            await asyncio.sleep(0.5)  # 500ms poll interval
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        await websocket.close()


# Import here to avoid circular
from datetime import datetime  # noqa: E402
