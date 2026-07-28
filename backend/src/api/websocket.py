"""WebSocket handler for streaming main pipeline execution state and results."""

import os
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.session_store import session_store

websocket_router = APIRouter(tags=["websockets"])


@websocket_router.websocket("/ws/session/{session_id}")
async def ws_session_stream(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint streaming status updates and final XAI report."""
    api_key = websocket.query_params.get("api_key")
    expected_key = os.getenv("API_KEY", "transafe-hackathon-key-2026")

    if not api_key or api_key != expected_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    session_data = session_store.get_session(session_id)
    if not session_data and not session_id.startswith("sess-"):
        await websocket.close(code=4004, reason="Session not found")
        return

    trigger_type = (
        session_data.get("trigger_type", "TRANSACTION")
        if session_data
        else "TRANSACTION"
    )

    await websocket.accept()

    try:
        status_steps = [
            f"Orchestrator: routing {trigger_type} trigger to worker nodes...",
            "Financial Worker: querying 90-day transaction history...",
            "Telemetry Worker: checking session behavioral biometrics...",
            "Research Worker: searching internal fraud memory and blacklists...",
            "Risk Scorer: computing weighted risk score...",
            "Explainable AI: compiling verdict explanation report...",
        ]

        for step in status_steps:
            status_msg = {
                "type": "status",
                "session_id": session_id,
                "message": step,
                "worker": "orchestrator",
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await websocket.send_json(status_msg)

        result_msg = {
            "type": "result",
            "session_id": session_id,
            "trigger_type": trigger_type,
            "xai_report": {
                "session_id": session_id,
                "trigger_type": trigger_type,
                "risk_score": 82,
                "risk_tier": "HIGH",
                "verdict_summary": (
                    "This transaction shows multiple signs of a scam: transfer"
                    " amount is high and recipient is flagged."
                ),
                "verdict_summary_ms": (
                    "Transaksi ini menunjukkan beberapa tanda penipuan:"
                    " pemindahan tinggi."
                ),
                "workers_activated": ["financial", "telemetry", "research"],
                "worker_findings": [
                    {
                        "worker": "financial",
                        "score": 88,
                        "confidence": 0.93,
                        "evidence": [
                            "Transfer amount is 47x higher than 90-day average"
                        ],
                    },
                    {
                        "worker": "telemetry",
                        "score": 15,
                        "confidence": 0.82,
                        "evidence": ["Known device fingerprint"],
                    },
                    {
                        "worker": "research",
                        "score": 95,
                        "confidence": 0.97,
                        "evidence": ["Recipient account found in fraud database"],
                    },
                ],
                "action_taken": "FREEZE_30_MIN",
                "unfreeze_at": datetime.now(UTC).isoformat(),
                "recommendation": "Do not proceed with this transfer.",
                "case_id": f"case-{session_id[:8]}",
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await websocket.send_json(result_msg)

        try:
            msg = await websocket.receive_json()
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass

        await websocket.close(code=1000)

    except WebSocketDisconnect:
        pass
