"""Live end-to-end phishing analyzer test: IMAGE, URL, and TEXT cases.

Runs against the running backend (uvicorn on :8000) exactly like the frontend:
1. POST /api/v1/trigger/phishing  (registers session)
2. GET  /ws/session/{session_id}?api_key=...  (streams status + final XAI report)
"""

import asyncio
import base64
import json
import sys
import uuid

import httpx
import websockets

BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"
API_KEY = "transafe-hackathon-key-2026"
# Seeded user row in Supabase (fraud_cases.user_id is UUID NOT NULL)
USER_ID = "619ebd02-82fc-4a13-81f6-ff575c20278d"
IMG_PATH = "tests/assets/scam.png"

PHISHING_TEXT = (
    "URGENT: Your Maybank account has been temporarily locked due to suspicious "
    "activity. To avoid permanent suspension, verify your account immediately at "
    "http://maybank-verify-secure.com within 24 hours. Failure to do so will "
    "result in your funds being frozen. - Maybank Security Team"
)


async def run_case(label: str, payload: dict) -> None:
    sid = f"sess-phish-e2e-{uuid.uuid4().hex[:8]}"
    payload = {"user_id": USER_ID, "session_id": sid, **payload}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE}/api/v1/trigger/phishing",
            json=payload,
            headers={"X-API-Key": API_KEY},
        )
        print(f"\n{'='*70}\n[{label}] POST -> HTTP {resp.status_code}")

    async with websockets.connect(
        f"{WS_BASE}/ws/session/{sid}?api_key={API_KEY}", open_timeout=10
    ) as ws:
        result = None
        statuses: list[str] = []
        while True:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            except asyncio.TimeoutError:
                print(f"[{label}] TIMEOUT waiting for result")
                break
            if msg.get("type") == "status":
                statuses.append(msg.get("message", ""))
            elif msg.get("type") == "result":
                result = msg
                break
        if not result:
            print(f"[{label}] NO RESULT — statuses received: {len(statuses)}")
            return

        print(f"[{label}] status steps streamed: {len(statuses)}")
        for s in statuses:
            print(f"    • {s}")
        data = result.get("data", {}) or result.get("xai_report", {}) or {}
        print(f"[{label}] RESULT:")
        print(f"    score={data.get('risk_score')} tier={data.get('risk_tier')} "
              f"action={data.get('action_taken')} case_id={data.get('case_id')}")
        summary = (data.get("verdict_summary") or data.get("summary") or "").replace("\n", " ")[:220]
        print(f"    verdict: {summary}")
        for wf in (data.get("worker_findings") or []):
            ev = (wf.get("evidence") or [])[:2]
            print(f"    worker {wf.get('worker')}: score={wf.get('score')} "
                  f"conf={wf.get('confidence')} evidence={ev}")


async def main() -> None:
    cases = [
        (
            "TEXT",
            {
                "material": {
                    "content_type": "TEXT",
                    "content": PHISHING_TEXT,
                    "source": "SMS",
                }
            },
        ),
        (
            "URL",
            {
                "material": {
                    "content_type": "URL",
                    "content": "grcontestzackretsport.000webhostapp.com",
                    "source": "SMS",
                }
            },
        ),
    ]
    # IMAGE case: read scam.png, base64 encode
    with open(IMG_PATH, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    cases.append(
        (
            "IMAGE",
            {
                "material": {
                    "content_type": "IMAGE",
                    "content": b64,
                    "source": "SMS",
                }
            },
        )
    )

    for label, payload in cases:
        try:
            await run_case(label, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] ERROR: {exc!r}")


if __name__ == "__main__":
    asyncio.run(main())
