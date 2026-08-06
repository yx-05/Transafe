"""Unit test suite validating 2-way WebRTC call relaying, incoming call controls, and event broadcasting."""

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

API_KEY = "transafe-hackathon-key-2026"
USER_HEADERS = {"X-API-Key": API_KEY}


def test_scammer_initiates_call_and_customer_answers():
    """Test full incoming call cycle: Scammer fires call -> Customer active lookup -> Customer answers."""
    session_id = "sess-scam-test-1"
    user_id = "usr-victim-99"

    # 1. Scammer fires call trigger
    trigger_payload = {
        "user_id": user_id,
        "session_id": session_id,
        "call": {
            "caller_number": "+60161234567",
            "caller_name": "Inspector Tan (PDRM Fake)",
            "call_mode": "LISTEN",
            "call_channel": "WEBRTC",
            "received_at": "2026-08-03T10:00:00Z",
        },
    }
    response = client.post(
        "/api/v1/trigger/call", json=trigger_payload, headers=USER_HEADERS
    )
    assert response.status_code == 202
    data = response.json()["data"]
    call_session_id = data["call_session_id"]
    assert call_session_id.startswith("call-")

    # 2. Customer checks active incoming call for user_id
    active_resp = client.get(
        f"/api/v1/call/active?user_id={user_id}", headers=USER_HEADERS
    )
    assert active_resp.status_code == 200
    active_data = active_resp.json()["data"]
    assert active_data is not None
    assert active_data["call_session_id"] == call_session_id
    assert active_data["status"] == "RINGING"
    assert active_data["caller_number"] == "+60161234567"

    # 3. Customer accepts call
    answer_resp = client.post(
        f"/api/v1/call/{call_session_id}/answer", headers=USER_HEADERS
    )
    assert answer_resp.status_code == 200
    assert answer_resp.json()["data"]["status"] == "ANSWERED"


def test_customer_declines_incoming_call():
    """Test customer declining an incoming call session."""
    session_id = "sess-scam-test-2"
    user_id = "usr-victim-88"

    trigger_payload = {
        "user_id": user_id,
        "session_id": session_id,
        "call": {
            "caller_number": "+60197654321",
            "caller_name": "Tax Officer (Fake)",
            "call_mode": "LISTEN",
            "call_channel": "WEBRTC",
            "received_at": "2026-08-03T10:00:00Z",
        },
    }
    res = client.post(
        "/api/v1/trigger/call", json=trigger_payload, headers=USER_HEADERS
    )
    call_session_id = res.json()["data"]["call_session_id"]

    # Customer declines call
    decline_resp = client.post(
        f"/api/v1/call/{call_session_id}/decline", headers=USER_HEADERS
    )
    assert decline_resp.status_code == 200
    assert decline_resp.json()["data"]["status"] == "DECLINED"


def test_dual_role_audio_and_event_websockets():
    """Test Scammer & Customer dual-role audio WebSocket connections and event broadcasting."""
    session_id = "sess-scam-test-3"
    user_id = "usr-victim-77"

    res = client.post(
        "/api/v1/trigger/call",
        json={
            "user_id": user_id,
            "session_id": session_id,
            "call": {
                "caller_number": "+60161234567",
                "received_at": "2026-08-03T10:00:00Z",
                "call_mode": "LISTEN",
                "call_channel": "WEBRTC",
            },
        },
        headers=USER_HEADERS,
    )
    call_session_id = res.json()["data"]["call_session_id"]

    # 1. Connect Scammer Audio WS (kept open so the call is not ENDED while
    #    the events WS broadcasts a transcript — closing it triggers the
    #    server-side handle_call_ended which marks the call ENDED)
    scammer_ws_url = (
        f"/ws/call/{call_session_id}/audio?api_key={API_KEY}&role=SCAMMER"
    )
    with client.websocket_connect(scammer_ws_url) as scammer_ws:
        scammer_ws.send_json({"type": "ping"})
        resp = scammer_ws.receive_json()
        assert resp["type"] == "pong"

        # 2. Connect Customer Events WS
        events_ws_url = (
            f"/ws/call/{call_session_id}/events?api_key={API_KEY}&role=CUSTOMER"
        )
        with client.websocket_connect(events_ws_url) as events_ws:
            # Check pre-check event
            msg1 = events_ws.receive_json()
            assert msg1["type"] == "pre_check_result"
            assert msg1["blacklisted"] is True

            # Broadcast transcript with high-risk keyword
            events_ws.send_json({
                "type": "broadcast_transcript",
                "speaker": "SCAMMER",
                "text": "Transfer money to safe account immediately!",
            })

            # Receive transcript event
            t_msg = events_ws.receive_json()
            assert t_msg["type"] == "transcript"
            assert t_msg["speaker"] == "SCAMMER"
            assert "safe account" in t_msg["text"]

            # Receive highlight event (rules wave, from Phone Worker highlight_events)
            h_msg = events_ws.receive_json()
            assert h_msg["type"] == "highlight"
            assert any(s["phrase"] == "safe account" for s in h_msg["highlighted_spans"])

            # Receive the LLM-enriched highlight wave (second highlight event)
            h2_msg = events_ws.receive_json()
            assert h2_msg["type"] == "highlight"
            assert h2_msg["enrichment"] == "llm"

            # Receive suspicion_update event (Phone Worker cumulative score),
            # skipping any async deep_analysis event that races in
            s_msg = None
            for _ in range(10):
                m = events_ws.receive_json()
                if m["type"] == "suspicion_update":
                    s_msg = m
                    break
                assert m["type"] in ("highlight", "deep_analysis")
            assert s_msg is not None
            assert s_msg["type"] == "suspicion_update"
            assert s_msg["suspicion_score"] is not None
            assert s_msg["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
