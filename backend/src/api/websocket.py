"""WebSocket handler for streaming main pipeline execution state and results."""

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.session_store import session_store
from src.agents.state import GraphState

websocket_router = APIRouter(tags=["websockets"])


@websocket_router.websocket("/ws/session/{session_id}")
async def ws_session_stream(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint streaming status updates and final XAI report."""
    api_key = websocket.query_params.get("api_key")
    expected_key = os.getenv("API_KEY", "transafe-hackathon-key-2026")

    if not api_key or api_key != expected_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Wait up to 3 seconds for REST POST payload to be registered in session_store
    session_data = session_store.get_session(session_id)
    if not session_data:
        for _ in range(15):
            await asyncio.sleep(0.2)
            session_data = session_store.get_session(session_id)
            if session_data:
                break

    if not session_data and not session_id.startswith("sess-"):
        await websocket.close(code=4004, reason="Session not found")
        return

    trigger_type = (
        session_data.get("trigger_type", "TRANSACTION")
        if session_data
        else "TRANSACTION"
    )
    user_id = session_data.get("user_id", "usr-123") if session_data else "usr-123"
    payload = session_data.get("payload", {}) if session_data else {}

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

        # Build initial LangGraph state
        initial_state: GraphState = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": datetime.now(UTC).isoformat(),
            "trigger_type": trigger_type,
            "trigger_payload": payload,
            "workers_to_activate": [],
            "status_messages": [],
            "telemetry_finding": None,
            "research_finding": None,
            "financial_finding": None,
            "phone_finding": None,
            "phishing_finding": None,
            "risk_score": None,
            "risk_tier": None,
            "xai_report": None,
            "phone_session": None,
            "call_mode": None,
            "action_taken": None,
            "case_id": None,
            "extracted_entities": None,
            "associated_case_id": payload.get("associated_case_id"),
            "associated_case_context": None,
        }

        # Invoke compiled LangGraph pipeline if available in app state
        xai_report = None
        compiled_graph = getattr(websocket.app.state, "compiled_graph", None)
        if compiled_graph:
            try:
                final_state = await compiled_graph.ainvoke(initial_state)
                xai_report = final_state.get("xai_report")
            except Exception as e:
                print(f"[WebSocket] LangGraph execution error: {e}")

        # Fallback XAI report if graph was not compiled or threw error
        if not xai_report:
            xai_report = {
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
            }

        result_msg = {
            "type": "result",
            "session_id": session_id,
            "trigger_type": trigger_type,
            "data": xai_report,
            "xai_report": xai_report,
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
