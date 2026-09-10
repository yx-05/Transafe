"""Unit and integration test suite for TranSafe Module 6 REST and WebSocket APIs."""


import base64
from unittest.mock import patch

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


def test_trigger_phishing_rejects_oversized_image():
    """Test POST /api/v1/trigger/phishing rejects images above the 10 MB cap."""
    oversized_bytes = b"a" * (10 * 1024 * 1024 + 1)
    oversized_b64 = base64.b64encode(oversized_bytes).decode("ascii")
    payload = {
        "user_id": "usr-123",
        "session_id": "sess-phish-big",
        "material": {
            "content_type": "IMAGE",
            "content": oversized_b64,
            "source": "SMS",
        },
    }
    response = client.post(
        "/api/v1/trigger/phishing", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 422


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
    """Test GET /admin/v1/cases with valid admin key (mocked DB)."""
    mock_case = {
        "id": "case-uuid-001",
        "user_id": "usr-1",
        "trigger_type": "TRANSACTION",
        "risk_score": 88,
        "risk_tier": "HIGH",
        "status": "frozen",
        "action_taken": "FREEZE_30_MIN",
        "created_at": "2026-07-28T12:00:00Z",
        "xai_report": {"verdict_summary": "High-risk transfer to known mule account."},
    }
    with patch("src.api.admin.list_all_cases", return_value=[mock_case]), patch(
        "src.api.admin.count_all_cases", return_value=1
    ):
        response = client.get("/admin/v1/cases", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["case_id"] == "case-uuid-001"
    assert item["risk_score"] == 88
    assert item["verdict_summary"] == "High-risk transfer to known mule account."


def test_admin_cases_with_filters():
    """Test GET /admin/v1/cases forwards risk/status/trigger filters to DB."""
    with patch("src.api.admin.list_all_cases", return_value=[]) as mock_list, patch(
        "src.api.admin.count_all_cases", return_value=0
    ):
        response = client.get(
            "/admin/v1/cases?risk_tier=HIGH&status=frozen&trigger_type=TRANSACTION",
            headers=ADMIN_HEADERS,
        )
    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0
    mock_list.assert_called_once_with(20, 0, "HIGH", "frozen", "TRANSACTION")


def test_admin_case_not_found_404():
    """GET /admin/v1/cases/{id} with a missing case returns 404."""
    with patch("src.api.admin.fetch_fraud_case", return_value=None):
        response = client.get("/admin/v1/cases/does-not-exist", headers=ADMIN_HEADERS)
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CASE_NOT_FOUND"


def test_admin_case_freeze_unfreeze():
    """Case-level freeze/unfreeze updates status in the DB (mocked)."""
    mock_case = {
        "id": "case-uuid-002",
        "user_id": "usr-2",
        "trigger_type": "PHISHING",
        "risk_score": 95,
        "risk_tier": "HIGH",
        "status": "pending",
        "action_taken": "",
        "created_at": "2026-07-28T12:00:00Z",
    }
    with patch("src.api.admin.fetch_fraud_case", return_value=mock_case) as mock_fetch, patch(
        "src.api.admin.update_fraud_case_status"
    ) as mock_update:
        freeze_res = client.post(
            "/admin/v1/cases/case-uuid-002/freeze",
            json={"reason": "Confirmed fraud"},
            headers=ADMIN_HEADERS,
        )
        assert freeze_res.status_code == 200
        assert freeze_res.json()["data"]["status"] == "frozen"
        assert freeze_res.json()["data"]["action_taken"] == "FREEZE_30_MIN"
        mock_update.assert_called_with("case-uuid-002", "frozen", "FREEZE_30_MIN")

        unfreeze_res = client.post(
            "/admin/v1/cases/case-uuid-002/unfreeze",
            json={"reason": "Resolved"},
            headers=ADMIN_HEADERS,
        )
        assert unfreeze_res.status_code == 200
        assert unfreeze_res.json()["data"]["status"] == "approved"
        mock_update.assert_called_with("case-uuid-002", "approved", "APPROVE")
        assert mock_fetch.call_count == 2


def test_admin_case_detail():
    """Test GET /admin/v1/cases/{case_id} endpoint (mocked DB)."""
    mock_case = {
        "id": "case-uuid-003",
        "session_id": "sess-3",
        "user_id": "usr-3",
        "trigger_type": "CALL",
        "risk_score": 82,
        "risk_tier": "HIGH",
        "status": "frozen",
        "action_taken": "FREEZE_30_MIN",
        "created_at": "2026-07-28T12:00:00Z",
        "xai_report": {
            "verdict_summary": "Scammer instructed victim to transfer to safe account.",
            "risk_factors": ["urgency", "safe_account"],
        },
    }
    with patch("src.api.admin.fetch_fraud_case", return_value=mock_case):
        response = client.get("/admin/v1/cases/case-uuid-003", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == "case-uuid-003"
    assert data["risk_score"] == 82
    assert data["xai_report"]["verdict_summary"].startswith("Scammer")


def test_admin_freeze_and_unfreeze():
    """Account freeze/unfreeze persists to DB and flips status (mocked)."""
    mock_account = {
        "account_number": "7653-1234",
        "user_id": "usr-4",
        "account_type": "savings",
        "balance_myr": 12000.0,
        "status": "active",
        "created_at": "2026-07-01T00:00:00Z",
    }
    with patch("src.api.admin.fetch_account_by_number", return_value=mock_account) as mock_fetch, patch(
        "src.api.admin.update_account_status"
    ) as mock_update, patch(
        "src.api.admin.freeze_transactions_by_sender", return_value=2
    ) as mock_freeze_tx, patch(
        "src.api.admin.unfreeze_transactions_by_sender", return_value=1
    ) as mock_unfreeze_tx:
        freeze_res = client.post(
            "/admin/v1/accounts/7653-1234/freeze",
            json={"reason": "Confirmed fraud"},
            headers=ADMIN_HEADERS,
        )
        assert freeze_res.status_code == 200
        data = freeze_res.json()["data"]
        assert data["status"] == "frozen"
        assert data["frozen_by"] == "admin"
        assert data["reason"] == "Confirmed fraud"
        # update_account_status called with ('7653-1234', 'frozen', ...)
        update_args = mock_update.call_args.args
        assert update_args[0] == "7653-1234"
        assert update_args[1] == "frozen"
        mock_freeze_tx.assert_called_once_with("7653-1234", 1800)

        unfreeze_res = client.post(
            "/admin/v1/accounts/7653-1234/unfreeze",
            json={"reason": "Resolved"},
            headers=ADMIN_HEADERS,
        )
        assert unfreeze_res.status_code == 200
        assert unfreeze_res.json()["data"]["status"] == "active"
        update_args = mock_update.call_args.args
        assert update_args[0] == "7653-1234"
        assert update_args[1] == "active"
        mock_unfreeze_tx.assert_called_once_with("7653-1234")
        assert mock_fetch.call_count == 2


def test_admin_account_not_found_404():
    """Freezing a non-existent account returns 404."""
    with patch("src.api.admin.fetch_account_by_number", return_value=None):
        response = client.post(
            "/admin/v1/accounts/0000-0000/freeze",
            json={"reason": "test"},
            headers=ADMIN_HEADERS,
        )
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_admin_list_accounts():
    """GET /admin/v1/accounts returns real account rows (mocked DB)."""
    mock_accounts = [
        {
            "id": "acc-uuid-1",
            "account_number": "6373-5093-3430-8430",
            "user_id": "usr-5",
            "account_type": "savings",
            "balance_myr": 5400.0,
            "status": "active",
            "created_at": "2026-07-01T00:00:00Z",
        },
        {
            "id": "acc-uuid-2",
            "account_number": "7653-1234-5678-9012",
            "user_id": "usr-6",
            "account_type": "current",
            "balance_myr": 0.0,
            "status": "frozen",
            "frozen_by": "admin",
            "frozen_at": "2026-07-28T12:00:00Z",
            "created_at": "2026-07-01T00:00:00Z",
        },
    ]
    with patch("src.api.admin.fetch_all_accounts", return_value=mock_accounts):
        response = client.get("/admin/v1/accounts", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert data["items"][1]["status"] == "frozen"
    assert data["items"][1]["frozen_by"] == "admin"


def test_admin_analytics_summary():
    """Test GET /admin/v1/analytics/summary endpoint (mocked DB)."""
    mock_cases = [
        {
            "id": "c1",
            "risk_tier": "HIGH",
            "trigger_type": "TRANSACTION",
            "risk_score": 88,
            "created_at": "2026-07-28T10:00:00Z",
            "xai_report": {"workers_activated": ["financial", "research"]},
        },
        {
            "id": "c2",
            "risk_tier": "LOW",
            "trigger_type": "CALL",
            "risk_score": 30,
            "created_at": "2026-07-28T11:00:00Z",
            "xai_report": {"workers_activated": ["phone"]},
        },
        {
            "id": "c3",
            "risk_tier": "MEDIUM",
            "trigger_type": "PHISHING",
            "risk_score": 55,
            "created_at": "2026-07-27T09:00:00Z",
            "xai_report": {"workers_activated": ["research"]},
        },
    ]
    mock_txs = [
        {"status": "frozen", "amount_myr": 15000.0, "risk_tier": "HIGH"},
        {"status": "completed", "amount_myr": 100.0, "risk_tier": "LOW"},
        {"status": "rejected", "amount_myr": 5000.0, "risk_tier": "HIGH"},
    ]
    mock_accounts = [
        {"status": "frozen"},
        {"status": "active"},
        {"status": "frozen"},
    ]
    mock_fraud_types = [
        {"fraud_type": "MACAU_SCAM"},
        {"fraud_type": "MACAU_SCAM"},
        {"fraud_type": "JOB_SCAM"},
    ]
    with (
        patch("src.api.admin.fetch_all_cases_for_analytics", return_value=mock_cases),
        patch("src.api.admin.fetch_all_transactions_for_analytics", return_value=mock_txs),
        patch("src.api.admin.fetch_all_accounts", return_value=mock_accounts),
        patch("src.api.admin.fetch_fraud_memory_types", return_value=mock_fraud_types),
    ):
        response = client.get("/admin/v1/analytics/summary", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_cases"] == 3
    assert data["by_risk_tier"] == {"LOW": 1, "MEDIUM": 1, "HIGH": 1}
    assert data["by_trigger_type"]["TRANSACTION"] == 1
    assert data["by_trigger_type"]["CALL"] == 1
    assert data["accounts_frozen"] == 2
    assert data["total_amount_protected_myr"] == 20000.0
    assert data["avg_risk_score"] == round((88 + 30 + 55) / 3, 1)
    assert data["worker_activation_counts"]["research"] == 2
    assert data["by_fraud_type"]["MACAU_SCAM"] == 2


def test_admin_analytics_trend():
    """Test GET /admin/v1/analytics/trend endpoint (mocked DB)."""
    mock_cases = [
        {"id": "t1", "risk_tier": "HIGH", "created_at": "2026-07-28T10:00:00Z"},
        {"id": "t2", "risk_tier": "LOW", "created_at": "2026-07-28T11:00:00Z"},
        {"id": "t3", "risk_tier": "MEDIUM", "created_at": "2026-07-27T09:00:00Z"},
    ]
    with patch("src.api.admin.fetch_all_cases_for_analytics", return_value=mock_cases):
        response = client.get("/admin/v1/analytics/trend", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["series"]) == 2
    day1 = next(p for p in data["series"] if p["date"] == "2026-07-28")
    assert day1["total"] == 2
    assert day1["HIGH"] == 1
    assert day1["LOW"] == 1
    assert "date" in data["series"][0]


def test_admin_list_alerts_and_update():
    """Test GET /admin/v1/alerts and PATCH /admin/v1/alerts/{alert_id} endpoints (mocked DB)."""
    mock_alerts = [
        {
            "id": "alert-uuid-1",
            "case_id": "case-uuid-001",
            "alert_type": "HIGH_RISK_FREEZE",
            "status": "pending",
            "created_at": "2026-07-28T12:00:00Z",
            "details": {
                "risk_score": 88,
                "verdict_summary": "High-risk transfer to known mule account.",
            },
        }
    ]
    with patch("src.api.admin.list_admin_alerts", return_value=mock_alerts) as mock_list, patch(
        "src.api.admin.update_admin_alert"
    ) as mock_update:
        res_list = client.get("/admin/v1/alerts", headers=ADMIN_HEADERS)
        assert res_list.status_code == 200
        data_list = res_list.json()["data"]
        assert data_list["total"] == 1
        alert_id = data_list["items"][0]["alert_id"]
        assert alert_id == "alert-uuid-1"
        assert data_list["items"][0]["risk_score"] == 88
        mock_list.assert_called_once_with("pending", 20, 0)

        res_patch = client.patch(
            f"/admin/v1/alerts/{alert_id}",
            json={"status": "reviewed", "admin_note": "Handled by analyst"},
            headers=ADMIN_HEADERS,
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["data"]["status"] == "reviewed"
        mock_update.assert_called_once_with(
            "alert-uuid-1", "reviewed", "Handled by analyst"
        )


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

        websocket.send_json({
            "type": "broadcast_transcript",
            "speaker": "SCAMMER",
            "text": "Transfer money to safe account immediately!",
        })

        m2 = websocket.receive_json()
        assert m2["type"] == "transcript"

        m3 = websocket.receive_json()
        assert m3["type"] == "highlight"
        assert len(m3["spans"]) >= 1


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

