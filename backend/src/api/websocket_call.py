"""WebSocket handlers for WebRTC phone call audio streaming and real-time event alerts."""

import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.session_store import session_store

call_ws_router = APIRouter(tags=["call_websockets"])


@call_ws_router.websocket("/ws/call/{call_session_id}/audio")
async def ws_call_audio_stream(
    websocket: WebSocket, call_session_id: str
) -> None:
    """WebRTC binary audio stream handler for real-time STT and phone session processing."""
    api_key = websocket.query_params.get("api_key")
    expected_key = os.getenv("API_KEY", "transafe-hackathon-key-2026")

    if not api_key or api_key != expected_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                # Process audio binary chunk
                _audio_bytes = message["bytes"]
                # Could transcribe chunk via src.services.stt if needed
                continue
            elif message.get("text"):
                try:
                    data: dict[str, Any] = json.loads(message["text"])
                    msg_type = data.get("type")
                    if msg_type == "call_end":
                        call_data = session_store.get_call(call_session_id)
                        if call_data:
                            call_data["status"] = "ENDED"
                        await websocket.close(code=1000, reason="Call ended")
                        break
                    elif msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass

    except WebSocketDisconnect:
        pass


@call_ws_router.websocket("/ws/call/{call_session_id}/events")
async def ws_call_events_stream(
    websocket: WebSocket, call_session_id: str
) -> None:
    """Real-time events stream handler pushing live highlight spans, transcriptions, and alerts."""
    api_key = websocket.query_params.get("api_key")
    expected_key = os.getenv("API_KEY", "transafe-hackathon-key-2026")

    if not api_key or api_key != expected_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    try:
        now = datetime.now(UTC).isoformat()
        _ = session_store.get_call(call_session_id)

        # 1. Send pre_check_result event
        pre_check_event = {
            "type": "pre_check_result",
            "call_session_id": call_session_id,
            "caller_number": "+60161234567",
            "blacklisted": True,
            "blacklist_case_count": 2,
            "spoofed_prefix": False,
            "initial_risk": "HIGH",
            "warning_text": (
                "This number has been reported 2 times for impersonation"
                " scams."
            ),
            "warning_text_ms": (
                "Nombor ini telah dilaporkan 2 kali untuk penipuan penyamaran."
            ),
            "timestamp": now,
        }
        await websocket.send_json(pre_check_event)

        # 2. Send sample transcript event
        transcript_event = {
            "type": "transcript",
            "call_session_id": call_session_id,
            "utterance_id": "utt-001",
            "speaker": "CALLER",
            "text": (
                "Your account has been flagged for money laundering. Transfer"
                " RM 5,000 to safe account."
            ),
            "timestamp": now,
        }
        await websocket.send_json(transcript_event)

        # 3. Send sample highlight event
        highlight_event = {
            "type": "highlight",
            "call_session_id": call_session_id,
            "utterance_id": "utt-001",
            "speaker": "CALLER",
            "text": (
                "Your account has been flagged for money laundering. Transfer"
                " RM 5,000 to safe account."
            ),
            "spans": [
                {
                    "start": 0,
                    "end": 48,
                    "text": "Your account has been flagged for money laundering",
                    "risk_level": "HIGH",
                    "tag": "false_accusation",
                    "tag_label": "False accusation",
                },
                {
                    "start": 50,
                    "end": 88,
                    "text": "Transfer RM 5,000 to safe account",
                    "risk_level": "HIGH",
                    "tag": "fund_transfer_request",
                    "tag_label": "Fund transfer request",
                },
            ],
            "utterance_risk_score": 97,
            "cumulative_suspicion_score": 85,
            "timestamp": now,
        }
        await websocket.send_json(highlight_event)

        # 4. Send suspicion_update event
        suspicion_event = {
            "type": "suspicion_update",
            "call_session_id": call_session_id,
            "suspicion_score": 85,
            "risk_tier": "HIGH",
            "trigger_escalation": True,
            "escalation_reason": "Score exceeded threshold",
            "timestamp": now,
        }
        await websocket.send_json(suspicion_event)

        # Keep connection open or listen for messages
        try:
            while True:
                msg = await websocket.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass

    except WebSocketDisconnect:
        pass
