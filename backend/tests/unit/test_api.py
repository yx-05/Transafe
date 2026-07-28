"""Unit and integration test suite for TranSafe Module 6 REST and WebSocket APIs."""


import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from main import app

client = TestClient(app)

API_KEY = "transafe-hackathon-key-2026"
ADMIN_KEY = "transafe-admin-key-2026"
USER_HEADERS = {"X-API-Key": API_KEY}
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}


def test_health_check():
    """Test health check endpoint without authentication."""
    response = client.get("/health")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json["status"] == "healthy"
    assert "version" in res_json
    assert res_json["services"]["supabase"] == "connected"


def test_trigger_endpoint_requires_api_key():
    """Assert 401 Unauthorized when X-API-Key is missing or invalid."""
    # Missing key
    response = client.post("/api/v1/trigger/transaction", json={})
    assert response.status_code == 401

    # Invalid key
    response = client.post(
        "/api/v1/trigger/transaction",
        json={},
        headers={"X-API-Key": "invalid-key"},
    )
    assert response.status_code == 401


def test_trigger_transaction_success():
    """Assert 202 Accepted and valid session_id on transaction trigger."""
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-456",
        "transaction": {
            "transaction_id": "tx-789",
            "sender_account": "12345678",
            "recipient_account": "87654321",
            "amount": 5000.0,
            "currency": "MYR",
            "description": "Test transfer",
            "initiated_at": "2026-07-26T10:00:00Z",
        },
    }
    response = client.post(
        "/api/v1/trigger/transaction", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 202
    res_data = response.json()
    assert res_data["success"] is True
    assert res_data["data"]["session_id"] == "sess-456"
    assert res_data["data"]["transaction_id"] == "tx-789"


def test_trigger_telemetry_success():
    """Test POST /api/v1/trigger/telemetry endpoint."""
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-telem-1",
        "device_id": "dev-999",
        "events": [
            {
                "event_type": "APP_OPEN",
                "event_value": None,
                "timestamp": "2026-07-26T10:00:00Z",
            }
        ],
    }
    response = client.post(
        "/api/v1/trigger/telemetry", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 202
    assert response.json()["data"]["session_id"] == "sess-telem-1"


def test_trigger_call_success():
    """Test POST /api/v1/trigger/call endpoint returning pre_check."""
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-call-1",
        "call": {
            "caller_number": "+60161234567",
            "received_at": "2026-07-26T10:00:00Z",
            "call_mode": "LISTEN",
            "call_channel": "WEBRTC",
        },
    }
    response = client.post(
        "/api/v1/trigger/call", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 202
    data = response.json()["data"]
    assert "call_session_id" in data
    assert data["pre_check"]["blacklisted"] is True


def test_trigger_phishing_success():
    """Test POST /api/v1/trigger/phishing endpoint."""
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-phish-1",
        "material": {
            "content_type": "TEXT",
            "content": "Urgent account update required at http://fake.site",
            "source": "SMS",
        },
    }
    response = client.post(
        "/api/v1/trigger/phishing", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 202
    assert response.json()["data"]["session_id"] == "sess-phish-1"


def test_trigger_report_success():
    """Test POST /api/v1/trigger/report endpoint."""
    payload = {
        "user_id": "usr-123",
        "report": {
            "description": "Phone scam impersonation",
            "phone_numbers": ["0161234567"],
            "bank_accounts": ["123456789"],
            "fraud_type": "IMPERSONATION_SCAM",
            "amount_lost_myr": 1000.0,
        },
    }
    response = client.post(
        "/api/v1/trigger/report", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "case_id" in data
    assert "0161234567" in data["entities_recorded"]["phone_numbers"]


def test_biometric_result_success():
    """Test POST /api/v1/biometric/result callback endpoint."""
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-bio-1",
        "transaction_id": "tx-bio-1",
        "biometric_result": "PASSED",
        "method": "FACE_ID",
        "attempted_at": "2026-07-26T10:01:00Z",
    }
    response = client.post(
        "/api/v1/biometric/result", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["transaction_status"] == "approved"


def test_call_takeover_success():
    """Test POST /api/v1/call/{session_id}/takeover endpoint."""
    # First create call session
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-takeover-1",
        "call": {
            "caller_number": "+60123456789",
            "received_at": "2026-07-26T10:00:00Z",
            "call_mode": "LISTEN",
        },
    }
    res_call = client.post(
        "/api/v1/trigger/call", json=payload, headers=USER_HEADERS
    )
    call_session_id = res_call.json()["data"]["call_session_id"]

    # Perform takeover
    response = client.post(
        f"/api/v1/call/{call_session_id}/takeover", headers=USER_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["data"]["call_mode"] == "AUTO_TALK"

    # Second takeover should return 409 ALREADY_AUTO_TALK
    res_repeat = client.post(
        f"/api/v1/call/{call_session_id}/takeover", headers=USER_HEADERS
    )
    assert res_repeat.status_code == 409


def test_get_recent_cases():
    """Assert GET /api/v1/cases/recent returns user case history."""
    # Register a call trigger for user
    payload = {
        "user_id": "usr-history-1",
        "session_id": "sess-hist-1",
        "call": {
            "caller_number": "+60161234567",
            "received_at": "2026-07-26T10:00:00Z",
        },
    }
    client.post("/api/v1/trigger/call", json=payload, headers=USER_HEADERS)

    response = client.get(
        "/api/v1/cases/recent?user_id=usr-history-1", headers=USER_HEADERS
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["has_recent_activity"] is True
    assert len(data["recent_cases"]) >= 1


def test_admin_cases_requires_admin_key():
    """Assert 401 Unauthorized when X-Admin-Key is missing or wrong."""
    response = client.get("/admin/v1/cases")
    assert response.status_code == 401

    response = client.get(
        "/admin/v1/cases", headers={"X-Admin-Key": "wrong-key"}
    )
    assert response.status_code == 401


def test_admin_cases_success():
    """Test GET /admin/v1/cases with valid admin key."""
    response = client.get("/admin/v1/cases", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert "items" in data
    assert data["total"] >= 1


def test_admin_freeze_and_unfreeze():
    """Test account freeze and unfreeze endpoints."""
    freeze_res = client.post(
        "/admin/v1/accounts/7653-1234/freeze",
        json={"reason": "Confirmed fraud"},
        headers=ADMIN_HEADERS,
    )
    assert freeze_res.status_code == 200
    assert freeze_res.json()["data"]["status"] == "frozen"

    unfreeze_res = client.post(
        "/admin/v1/accounts/7653-1234/unfreeze",
        json={"reason": "Resolved"},
        headers=ADMIN_HEADERS,
    )
    assert unfreeze_res.status_code == 200
    assert unfreeze_res.json()["data"]["status"] == "active"


def test_admin_analytics_summary():
    """Test GET /admin/v1/analytics/summary endpoint."""
    response = client.get("/admin/v1/analytics/summary", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_cases"] == 142


def test_websocket_session_stream():
    """Test WebSocket session handler streaming status and result messages."""
    with client.websocket_connect(
        f"/ws/session/sess-ws-1?api_key={API_KEY}"
    ) as websocket:
        messages = []
        # Read status and result frames
        for _ in range(7):
            data = websocket.receive_json()
            messages.append(data)

        types = [m.get("type") for m in messages]
        assert "status" in types
        assert "result" in types


def test_websocket_session_stream_unauthorized():
    """Test WebSocket session rejection with invalid API key."""
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/session/sess-ws-1?api_key=wrong"),
    ):
        pass


def test_websocket_call_events():
    """Test WebSocket call events streaming pre_check, transcript, and highlight."""
    with client.websocket_connect(
        f"/ws/call/call-event-1/events?api_key={API_KEY}"
    ) as websocket:
        m1 = websocket.receive_json()
        assert m1["type"] == "pre_check_result"

        m2 = websocket.receive_json()
        assert m2["type"] == "transcript"

        m3 = websocket.receive_json()
        assert m3["type"] == "highlight"
        assert len(m3["spans"]) >= 1


def test_admin_case_detail():
    """Test GET /admin/v1/cases/{case_id} endpoint."""
    response = client.get("/admin/v1/cases/case-101", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["case_id"] == "case-101"
    assert data["risk_score"] == 82


def test_admin_analytics_trend():
    """Test GET /admin/v1/analytics/trend endpoint."""
    response = client.get("/admin/v1/analytics/trend", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["series"]) >= 1
    assert "date" in data["series"][0]


def test_admin_list_alerts_and_update():
    """Test GET /admin/v1/alerts and PATCH /admin/v1/alerts/{alert_id} endpoints."""
    res_list = client.get("/admin/v1/alerts", headers=ADMIN_HEADERS)
    assert res_list.status_code == 200
    data_list = res_list.json()["data"]
    assert data_list["total"] >= 1
    alert_id = data_list["items"][0]["alert_id"]

    res_patch = client.patch(
        f"/admin/v1/alerts/{alert_id}",
        json={"status": "reviewed", "admin_note": "Handled by analyst"},
        headers=ADMIN_HEADERS,
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["data"]["status"] == "reviewed"


def test_websocket_call_audio():
    """Test binary WebRTC audio WebSocket handler."""
    with client.websocket_connect(
        f"/ws/call/call-audio-1/audio?api_key={API_KEY}"
    ) as websocket:
        # Send audio bytes chunk
        fake_pcm_audio = b"\x00\x01" * 1000
        websocket.send_bytes(fake_pcm_audio)

        # Send ping control JSON
        websocket.send_json({"type": "ping"})
        response = websocket.receive_json()
        assert response["type"] == "pong"

        # Send call_end to close cleanly
        websocket.send_json({"type": "call_end"})

