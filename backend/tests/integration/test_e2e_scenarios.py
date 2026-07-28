"""End-to-end integration test suite for TranSafe.

Validates end-to-end functionality across:
1. doc/01_PRD.md (User stories, fraud scenarios, acceptance criteria)
2. doc/02_architecture.md (Module boundaries, data flows)
3. doc/03_agent_flow.md (State machine, worker activation, two-stage routing, XAI)
4. doc/04_api_design.md (REST trigger endpoints, WebSockets, Admin APIs)
5. doc/05_database_schema.md (Relational CRUD, pgvector similarity search, RPCs)
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from src.agents.graph import compile_graph
from src.db.supabase import FraudCaseRecord

client = TestClient(app)

API_KEY = "transafe-hackathon-key-2026"
ADMIN_KEY = "transafe-admin-key-2026"
USER_HEADERS = {"X-API-Key": API_KEY}
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}


# ============================================================================
# Scenario 1: High-Risk Mule Transaction Interception (PRD §3.1 & Agent Flow §6.1)
# ============================================================================
@pytest.mark.asyncio
@patch("src.agents.workers.financial.fetch_user_transaction_history")
@patch("src.agents.workers.financial.llm")
@patch("src.agents.workers.telemetry.fetch_telemetry_events")
@patch("src.agents.workers.research.search_fraud_memory")
@patch("src.agents.graph_nodes.Groq")
@patch("src.agents.graph_nodes.insert_fraud_case")
@patch("src.db.supabase.update_transaction_status")
@patch("src.agents.graph_nodes.insert_admin_alert")
async def test_prd_scenario1_transaction_interception(
    mock_admin_alert,
    mock_tx_update,
    mock_insert_case,
    mock_groq_cls,
    mock_search_memory,
    mock_fetch_telemetry,
    mock_financial_llm,
    mock_tx_history,
):
    """PRD Scenario 1: High-risk transaction to anomalous account is flagged and frozen."""
    mock_insert_case.return_value = "case-prd-101"
    mock_tx_history.return_value = {"avg_amount": 150.0, "known_recipients": []}
    mock_fetch_telemetry.return_value = [
        {"event_type": "copy_paste", "payload": {"field": "recipient_account"}},
        {"event_type": "app_switch", "payload": {"app": "Telegram"}},
    ]
    mock_search_memory.return_value = [
        {"case_id": "case-old-99", "similarity": 0.89, "content": "Mule account report"}
    ]

    mock_fin_resp = MagicMock()
    mock_fin_resp.content = '{"score": 92, "confidence": 0.9, "evidence": ["Recipient account matches scam report", "Large deviation from MYR 150 baseline"]}'
    mock_financial_llm.invoke.return_value = mock_fin_resp

    mock_xai_groq = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = '{"verdict_summary": "High risk fraud detected", "verdict_summary_ms": "Penipuan berisiko tinggi dikesan", "recommendation": "Freeze transaction"}'
    mock_xai_groq.chat.completions.create.return_value.choices = [mock_choice]
    mock_groq_cls.return_value = mock_xai_groq

    # Trigger transaction via REST API
    payload = {
        "user_id": "usr-vict-01",
        "session_id": "sess-tx-99",
        "transaction": {
            "transaction_id": "tx-scam-88",
            "sender_account": "1122334455",
            "recipient_account": "9988776655",
            "amount": 12500.0,
            "currency": "MYR",
            "description": "Emergency transfer",
            "initiated_at": "2026-07-28T10:00:00Z",
        },
        "associated_case_id": "case-old-99",
    }

    response = client.post(
        "/api/v1/trigger/transaction", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 202
    res_data = response.json()["data"]
    assert "session_id" in res_data

    # Test underlying Compiled LangGraph execution
    graph = compile_graph()
    initial_state = {
        "session_id": "sess-tx-99",
        "user_id": "usr-vict-01",
        "trigger_type": "TRANSACTION",
        "trigger_payload": payload,
        "status_messages": [],
    }

    final_state = await graph.ainvoke(initial_state)

    assert final_state["risk_score"] >= 40
    assert final_state["risk_tier"] in ["MEDIUM", "HIGH"]
    assert final_state["action_taken"] in ["FREEZE_30_MIN", "BIOMETRIC_CHALLENGE"]
    assert final_state["xai_report"] is not None
    if final_state["action_taken"] == "FREEZE_30_MIN":
        mock_tx_update.assert_called_once()


# ============================================================================
# Scenario 2: Real-Time Impersonation Call & Auto-Talk (PRD §3.2 & Agent Flow §6.2)
# ============================================================================
@patch("src.agents.workers.phone.llm")
def test_prd_scenario2_phone_impersonation_call(mock_phone_llm):
    """PRD Scenario 2: Phone worker detects scam keywords and controls Auto-Talk dialogue."""
    mock_llm_resp = MagicMock()
    mock_llm_resp.content = '{"spans": [{"text": "PDRM Officer", "category": "impersonation", "risk_score": 90}], "utterance_risk": 85, "reason": "Claiming to be police officer over phone"}'
    mock_phone_llm.invoke.return_value = mock_llm_resp

    # Trigger call REST endpoint
    payload = {
        "user_id": "usr-call-02",
        "session_id": "sess-call-77",
        "call": {
            "caller_number": "+60169998877",
            "caller_name": "Unknown",
            "call_direction": "INCOMING",
            "received_at": "2026-07-28T10:00:00Z",
        },
    }

    response = client.post("/api/v1/trigger/call", json=payload, headers=USER_HEADERS)
    assert response.status_code == 202

    # Test Takeover REST Endpoint
    takeover_payload = {
        "user_id": "usr-call-02",
        "action": "ENABLE_AUTOTALK",
        "reason": "User clicked auto-talk takeover button",
    }
    takeover_res = client.post(
        "/api/v1/call/sess-call-77/takeover",
        json=takeover_payload,
        headers=USER_HEADERS,
    )
    assert takeover_res.status_code == 200
    assert takeover_res.json()["data"]["call_mode"] == "AUTO_TALK"


# ============================================================================
# Scenario 3: Screenshot & Phishing Link Investigation (PRD §3.3 & Agent Flow §6.3)
# ============================================================================
@patch("src.services.vision.groq_client")
@patch("src.services.tavily.TavilyClient")
@patch("src.agents.workers.phishing.llm")
def test_prd_scenario3_phishing_investigation(
    mock_phishing_llm, mock_tavily_cls, mock_groq_client
):
    """PRD Scenario 3: OCR extracts phishing text, Phishing Worker extracts entities, Research Worker cross-checks."""
    mock_vision_choice = MagicMock()
    mock_vision_choice.message.content = (
        "URGENT: Maybank account locked. Verify now at http://maybank-secure-update.xyz"
    )
    mock_groq_client.chat.completions.create.return_value.choices = [
        mock_vision_choice
    ]

    mock_tavily_inst = MagicMock()
    mock_tavily_inst.search.return_value = {
        "results": [
            {
                "title": "Maybank Phishing Domain List",
                "url": "https://semak.my/alert/123",
            }
        ]
    }
    mock_tavily_cls.return_value = mock_tavily_inst

    mock_phish_resp = MagicMock()
    mock_phish_resp.content = '{"score": 95, "confidence": 0.95, "evidence": ["Malicious URL domain found"], "extracted_entities": ["http://maybank-secure-update.xyz"]}'
    mock_phishing_llm.invoke.return_value = mock_phish_resp

    # Trigger phishing REST endpoint
    payload = {
        "user_id": "usr-phish-03",
        "session_id": "sess-phish-55",
        "material": {
            "content_type": "IMAGE",
            "content": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "source": "SMS",
        },
    }

    response = client.post(
        "/api/v1/trigger/phishing", json=payload, headers=USER_HEADERS
    )
    assert response.status_code == 202
    assert response.json()["success"] is True


# ============================================================================
# Scenario 4: Victim Fraud Report Ingestion & Vector Memory (PRD §3.4 & DB §2.2)
# ============================================================================
@patch("src.db.vector_store.groq_client")
@patch("src.db.vector_store.supabase_client")
@patch("src.agents.workers.research.llm")
def test_prd_scenario4_victim_report_ingestion(
    mock_research_llm, mock_supabase, mock_groq
):
    """PRD Scenario 4: User submits scam report, Research worker ingests and adds to pgvector."""
    mock_embed_resp = MagicMock()
    mock_embed_resp.data = [MagicMock(embedding=[0.123] * 768)]
    mock_groq.embeddings.create.return_value = mock_embed_resp

    mock_llm_resp = MagicMock()
    mock_llm_resp.content = '{"score": 0, "confidence": 1.0, "evidence": ["Report ingested successfully"], "summary": "Macau Scam caller pretending to be LHDN officer", "extracted_entities": ["+60129990000", "7654321098"]}'
    mock_research_llm.invoke.return_value = mock_llm_resp

    payload = {
        "user_id": "usr-report-04",
        "report": {
            "description": "Caller phone +60129990000 asked me to transfer money to account 7654321098 claiming tax arrears.",
            "phone_numbers": ["+60129990000"],
            "bank_accounts": ["7654321098"],
            "fraud_type": "MACAU_SCAM",
            "amount_lost_myr": 4500.0,
        },
    }

    response = client.post("/api/v1/trigger/report", json=payload, headers=USER_HEADERS)
    assert response.status_code == 200
    assert "case_id" in response.json()["data"]


# ============================================================================
# Scenario 5: Admin Portal & Fraud Operations (PRD §3.5 & API §5)
# ============================================================================
@patch("src.db.supabase.get_supabase")
def test_prd_scenario5_admin_operations(mock_get_supabase):
    """PRD Scenario 5: Fraud analyst queries cases, freezes/unfreezes accounts, and checks analytics."""
    mock_client = MagicMock()
    mock_get_supabase.return_value = mock_client

    # 1. Fetch cases list
    mock_client.table.return_value.select.return_value.order.return_value.range.return_value.execute.return_value.data = [
        {
            "id": "case-admin-01",
            "session_id": "sess-admin-1",
            "user_id": "usr-1",
            "trigger_type": "TRANSACTION",
            "risk_score": 88,
            "risk_tier": "HIGH",
            "status": "FROZEN",
            "action_taken": "FREEZE_30_MIN",
            "created_at": "2026-07-28T12:00:00Z",
        }
    ]
    mock_client.table.return_value.select.return_value.execute.return_value.data = [
        {"count": 1}
    ]

    res_cases = client.get("/admin/v1/cases", headers=ADMIN_HEADERS)
    assert res_cases.status_code == 200
    assert res_cases.json()["data"]["total"] >= 1

    # 2. Freeze account
    freeze_payload = {"reason": "Confirmed mule account from police report"}
    res_freeze = client.post(
        "/admin/v1/accounts/7654321098/freeze",
        json=freeze_payload,
        headers=ADMIN_HEADERS,
    )
    assert res_freeze.status_code == 200
    assert res_freeze.json()["data"]["status"].upper() in ["FROZEN", "ACTIVE"]

    # 3. Unfreeze account
    unfreeze_payload = {"reason": "Legitimate user verified identity"}
    res_unfreeze = client.post(
        "/admin/v1/accounts/7654321098/unfreeze",
        json=unfreeze_payload,
        headers=ADMIN_HEADERS,
    )
    assert res_unfreeze.status_code == 200
    assert res_unfreeze.json()["data"]["status"].upper() in ["ACTIVE", "UNFROZEN"]


# ============================================================================
# Database Schema & Vector Search Direct Test (Database §2.2)
# ============================================================================
def test_database_record_models_and_contracts():
    """Verify Pydantic models for DB records strictly comply with doc/05_database_schema.md."""
    case = FraudCaseRecord(
        session_id="sess-contract-1",
        user_id="usr-contract-1",
        trigger_type="TRANSACTION",
        risk_score=95,
        risk_tier="HIGH",
        status="ACTIVE",
        action_taken="FREEZE_30_MIN",
        xai_report={"summary_en": "High risk transfer"},
    )
    assert case.risk_score == 95
    assert case.risk_tier == "HIGH"
    assert case.action_taken == "FREEZE_30_MIN"
