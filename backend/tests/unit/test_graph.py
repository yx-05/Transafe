"""Unit tests for LangGraph Orchestrator & State Machine (Module 5)."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.agents.graph import compile_graph
from src.agents.graph_nodes import action_dispatcher_node, risk_scorer_node
from src.agents.orchestrator import orchestrator_node
from src.agents.state import GraphState, WorkerFinding


@pytest.mark.asyncio
async def test_orchestrator_routing_transaction() -> None:
    """Assert orchestrator_node routes TRANSACTION trigger to financial, telemetry, research."""
    state: GraphState = {
        "trigger_type": "TRANSACTION",
        "trigger_payload": {"associated_case_id": None},
        "status_messages": [],
    }

    res = await orchestrator_node(state)

    assert res["workers_to_activate"] == ["financial", "telemetry", "research"]
    assert res["associated_case_id"] is None
    assert any("TRANSACTION" in msg for msg in res["status_messages"])


@pytest.mark.asyncio
async def test_orchestrator_routing_call_and_telemetry() -> None:
    """Assert orchestrator_node routes CALL and TELEMETRY triggers correctly."""
    call_state: GraphState = {
        "trigger_type": "CALL",
        "trigger_payload": {},
        "status_messages": [],
    }
    call_res = await orchestrator_node(call_state)
    assert call_res["workers_to_activate"] == ["phone", "research", "phishing"]

    telemetry_state: GraphState = {
        "trigger_type": "TELEMETRY",
        "trigger_payload": {},
        "status_messages": [],
    }
    telemetry_res = await orchestrator_node(telemetry_state)
    assert telemetry_res["workers_to_activate"] == ["telemetry"]


@pytest.mark.asyncio
async def test_orchestrator_routing_phishing() -> None:
    """Assert orchestrator_node routes PHISHING triggers to the phishing worker.

    The research worker runs as documented Stage 2 after it (see
    ``route_after_phishing`` in graph.py) so it can consume the OCR-extracted
    URLs from IMAGE submissions.
    """
    state: GraphState = {
        "trigger_type": "PHISHING",
        "trigger_payload": {},
        "status_messages": [],
    }

    res = await orchestrator_node(state)

    assert res["workers_to_activate"] == ["phishing"]


def test_risk_scorer_node_weighted_scoring() -> None:
    """Assert risk_scorer_node normalizes weighted scores correctly when only a subset of workers is active."""
    financial_finding: WorkerFinding = {
        "worker": "financial",
        "score": 90,
        "confidence": 0.9,
        "evidence": ["High amount deviation"],
    }
    telemetry_finding: WorkerFinding = {
        "worker": "telemetry",
        "score": 10,
        "confidence": 0.8,
        "evidence": ["Normal device"],
    }

    state: GraphState = {
        "financial_finding": financial_finding,
        "telemetry_finding": telemetry_finding,
        "research_finding": None,
        "phone_finding": None,
        "phishing_finding": None,
        "status_messages": [],
    }

    res = risk_scorer_node(state)

    # Active weights: financial (0.30) + telemetry (0.15) = 0.45
    # Weighted score: (90 * 0.30 / 0.45) + (10 * 0.15 / 0.45) = 60 + 3.333 = 63.33 -> 63
    assert res["risk_score"] == 63
    assert res["risk_tier"] == "MEDIUM"


def test_risk_scorer_case_coercion_override() -> None:
    """Assert risk_scorer_node coerces score to HIGH when the financial worker
    flags a case-context coercion match, even with low other-worker scores."""
    financial_finding: WorkerFinding = {
        "worker": "financial",
        "score": 98,
        "confidence": 0.99,
        "evidence": [
            "Recipient account 9988776655 matches active call transcript or "
            "phishing case context"
        ],
    }
    telemetry_finding: WorkerFinding = {
        "worker": "telemetry",
        "score": 0,
        "confidence": 1.0,
        "evidence": ["Normal device"],
    }
    research_finding: WorkerFinding = {
        "worker": "research",
        "score": 0,
        "confidence": 0.95,
        "evidence": ["No matches found"],
    }

    state: GraphState = {
        "financial_finding": financial_finding,
        "telemetry_finding": telemetry_finding,
        "research_finding": research_finding,
        "phone_finding": None,
        "phishing_finding": None,
        "status_messages": [],
    }

    res = risk_scorer_node(state)

    # Weighted score alone would be ~42 (MEDIUM), but the coercion match must
    # force the overall score to 98 -> HIGH so the transaction is frozen.
    assert res["risk_score"] == 98
    assert res["risk_tier"] == "HIGH"


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.insert_admin_alert", new_callable=Mock)
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=Mock)
@patch("src.agents.graph_nodes.resolve_transaction_uuid", new_callable=Mock)
@patch("src.agents.graph_nodes.freeze_transaction", new_callable=Mock)
async def test_action_dispatcher_high_risk_freeze(
    mock_freeze: Mock,
    mock_resolve_tx: Mock,
    mock_insert_case: Mock,
    mock_insert_alert: Mock,
) -> None:
    """Assert action_dispatcher_node sets FREEZE_30_MIN action for HIGH risk tier."""
    mock_insert_case.return_value = "case-uuid-high-123"
    mock_insert_alert.return_value = "alert-uuid-456"
    mock_resolve_tx.return_value = "00000000-0000-4000-8000-000000000101"

    state: GraphState = {
        "session_id": "sess-high-risk",
        "user_id": "user-999",
        "trigger_type": "TRANSACTION",
        "risk_score": 85,
        "risk_tier": "HIGH",
        "trigger_payload": {"transaction_id": "tx-freeze-789"},
        "xai_report": {"verdict_summary": "High risk detected"},
        "status_messages": [],
    }

    res = await action_dispatcher_node(state)

    assert res["action_taken"] == "FREEZE_30_MIN"
    assert res["case_id"] == "case-uuid-high-123"
    assert "unfreeze_at" in res["xai_report"]
    mock_freeze.assert_called_once_with(
        transaction_id="tx-freeze-789", freeze_duration_seconds=1800
    )
    # The case must store the transactions row UUID, not the TEXT business id
    mock_resolve_tx.assert_called_once_with("tx-freeze-789")
    call_kwargs = mock_insert_case.call_args[0][0]
    assert call_kwargs["transaction_id"] == "00000000-0000-4000-8000-000000000101"
    mock_insert_alert.assert_called_once()


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.insert_admin_alert", new_callable=Mock)
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=Mock)
@patch("src.agents.graph_nodes.resolve_transaction_uuid", new_callable=Mock)
@patch("src.agents.graph_nodes.freeze_transaction", new_callable=Mock)
async def test_action_dispatcher_high_risk_freeze_nested_transaction_id(
    mock_freeze: Mock,
    mock_resolve_tx: Mock,
    mock_insert_case: Mock,
    mock_insert_alert: Mock,
) -> None:
    """Assert dispatcher finds transaction_id nested under payload['transaction'].

    The frontend sends {transaction: {transaction_id: ...}}; previously the
    dispatcher only read payload['transaction_id'] (flat) so the freeze action
    and the case's transaction_id link were both silently skipped.
    """
    mock_insert_case.return_value = "case-uuid-nested-1"
    mock_resolve_tx.return_value = "00000000-0000-4000-8000-000000000202"

    state: GraphState = {
        "session_id": "sess-nested-1",
        "user_id": "user-999",
        "trigger_type": "TRANSACTION",
        "risk_score": 90,
        "risk_tier": "HIGH",
        "trigger_payload": {
            "transaction": {
                "transaction_id": "tx-nested-456",
                "recipient_account": "9988776655",
            }
        },
        "xai_report": {"verdict_summary": "High risk detected"},
        "status_messages": [],
    }

    res = await action_dispatcher_node(state)

    assert res["action_taken"] == "FREEZE_30_MIN"
    mock_freeze.assert_called_once_with(
        transaction_id="tx-nested-456", freeze_duration_seconds=1800
    )
    # The case row must be linked to the transaction's UUID PK
    mock_resolve_tx.assert_called_once_with("tx-nested-456")
    call_kwargs = mock_insert_case.call_args[0][0]
    assert call_kwargs["transaction_id"] == "00000000-0000-4000-8000-000000000202"
    mock_insert_alert.assert_called_once()


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.insert_admin_alert", new_callable=Mock)
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=Mock)
@patch("src.agents.graph_nodes.resolve_transaction_uuid", new_callable=Mock)
@patch("src.agents.graph_nodes.freeze_transaction", new_callable=Mock)
async def test_action_dispatcher_case_created_without_tx_link_when_unknown(
    mock_freeze: Mock,
    mock_resolve_tx: Mock,
    mock_insert_case: Mock,
    mock_insert_alert: Mock,
) -> None:
    """Assert the case is still created when the transaction row cannot be found.

    If resolve_transaction_uuid returns None (the transaction insert failed
    earlier in the trigger flow), the case insert must NOT include
    transaction_id so the row still persists and can be flagged later.
    """
    mock_insert_case.return_value = "case-uuid-nolink-1"
    mock_resolve_tx.return_value = None

    state: GraphState = {
        "session_id": "sess-nolink-1",
        "user_id": "user-999",
        "trigger_type": "TRANSACTION",
        "risk_score": 95,
        "risk_tier": "HIGH",
        "trigger_payload": {
            "transaction": {
                "transaction_id": "tx-missing-999",
                "recipient_account": "9988776655",
            }
        },
        "xai_report": {"verdict_summary": "High risk detected"},
        "status_messages": [],
    }

    res = await action_dispatcher_node(state)

    assert res["action_taken"] == "FREEZE_30_MIN"
    assert res["case_id"] == "case-uuid-nolink-1"
    call_kwargs = mock_insert_case.call_args[0][0]
    assert "transaction_id" not in call_kwargs
    assert any("without transaction link" in msg for msg in res["status_messages"])


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.insert_admin_alert", new_callable=Mock)
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=Mock)
@patch("src.agents.graph_nodes.insert_phishing_submission", new_callable=Mock)
@patch("src.agents.graph_nodes.resolve_transaction_uuid", new_callable=Mock)
@patch("src.agents.graph_nodes.freeze_transaction", new_callable=Mock)
async def test_action_dispatcher_phishing_case_logging(
    mock_freeze: Mock,
    mock_resolve_tx: Mock,
    mock_insert_submission: Mock,
    mock_insert_case: Mock,
    mock_insert_alert: Mock,
) -> None:
    """Assert phishing submissions create a case log without freeze/admin alert side effects."""
    case_uuid = "11111111-2222-4333-8444-555555555555"
    mock_insert_case.return_value = case_uuid

    state: GraphState = {
        "session_id": "sess-phish-1",
        "user_id": "user-phish",
        "trigger_type": "PHISHING",
        "risk_score": 88,
        "risk_tier": "HIGH",
        "trigger_payload": {
            "material": {
                "content_type": "IMAGE",
                "content": "data:image/png;base64,ZmFrZS1pbWFnZS1ieXRlcw==",
                "source": "SMS",
            }
        },
        "phishing_ocr_text": "URGENT: verify your account",
        "phishing_image_description": "Urgency banner and lookalike login form",
        "xai_report": {"verdict_summary": "High risk phishing"},
        "status_messages": [],
    }

    res = await action_dispatcher_node(state)

    assert res["action_taken"] == "WARNING"
    assert res["case_id"] == case_uuid
    mock_freeze.assert_not_called()
    mock_resolve_tx.assert_not_called()
    mock_insert_alert.assert_not_called()
    mock_insert_submission.assert_called_once()
    submission_kwargs = mock_insert_submission.call_args[0][0]
    assert submission_kwargs["content_type"] == "IMAGE"
    assert "data:image" not in submission_kwargs["raw_content"]
    assert submission_kwargs["extracted_text"] == "URGENT: verify your account"
    # The submission row must reference the fraud case UUID returned by the
    # insert (never the non-UUID "case-<session>" placeholder).
    assert submission_kwargs["case_id"] == case_uuid


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.Groq")
@patch("src.agents.graph_nodes.resolve_transaction_uuid", new_callable=Mock)
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=Mock)
async def test_full_graph_execution_mocked(
    mock_insert_case: Mock,
    mock_resolve_tx: Mock,
    mock_groq: Any,
) -> None:
    """Test full compiled graph execution with mocked LLM and DB calls."""
    mock_insert_case.return_value = "case-test-full-graph"
    mock_resolve_tx.return_value = None

    compiled_graph = compile_graph()

    initial_state: dict[str, Any] = {
        "session_id": "sess-graph-run",
        "user_id": "usr-graph-owner",
        "trigger_type": "TRANSACTION",
        "trigger_payload": {
            "transaction_id": "tx-graph-101",
            "amount": 5000.0,
        },
        "status_messages": [],
    }

    final_state = await compiled_graph.ainvoke(initial_state)

    assert final_state["workers_to_activate"] == ["financial", "telemetry", "research"]
    assert final_state["risk_score"] is not None
    assert final_state["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]
    assert final_state["action_taken"] in ["APPROVE", "BIOMETRIC_CHALLENGE", "FREEZE_30_MIN"]
    assert final_state["xai_report"] is not None
    assert len(final_state["status_messages"]) > 0


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.Groq")
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=Mock)
@patch("src.agents.graph_nodes.insert_phishing_submission", new_callable=Mock)
@patch("src.agents.workers.phishing.analyze_image", new_callable=MagicMock)
@patch("src.agents.workers.phishing.search_fraud_memory", new_callable=MagicMock)
@patch("src.agents.workers.phishing.llm", new_callable=MagicMock)
@patch("src.agents.workers.research.hybrid_search_fraud_memory", new_callable=MagicMock)
@patch("src.agents.workers.research.tavily_search", new_callable=MagicMock)
@patch("src.agents.llm.invoke_groq_with_key_rotation", new_callable=MagicMock)
async def test_full_graph_phishing_image_high_risk(
    mock_llm_rotate: MagicMock,
    mock_research_tavily: MagicMock,
    mock_hybrid: MagicMock,
    mock_phish_llm: MagicMock,
    mock_mem: MagicMock,
    mock_analyze_image: MagicMock,
    mock_insert_submission: Mock,
    mock_insert_case: Mock,
    mock_groq: Any,
) -> None:
    """PHISHING IMAGE trigger runs phishing (Stage 1) then research (Stage 2) and lands HIGH/WARNING.

    The PayPal-lookalike OCR text must score HIGH deterministically even when
    every LLM call fails (rule engine + PHISHING scorer override), and the
    submission row must link to the real fraud-case UUID.
    """
    case_uuid = "11111111-2222-4333-8444-555555555555"
    mock_insert_case.return_value = case_uuid
    mock_insert_submission.return_value = "sub-phish-1"
    mock_analyze_image.return_value = {
        "extracted_text": (
            "Log in to your PayPal Account\nDangerous\n"
            "www.kmacraeandson.co.uk/Online-Support\nEmail\nPassword\nLog In"
        ),
        "description": "Phishing page mimicking the PayPal login interface",
    }
    mock_mem.return_value = []
    mock_phish_llm.invoke.side_effect = Exception("LLM fallback")
    mock_hybrid.return_value = []
    mock_research_tavily.return_value = []
    mock_llm_rotate.return_value = Mock(
        content=json.dumps(
            {
                "verdict_summary": "This looks like a phishing page.",
                "verdict_summary_ms": "Halaman ini kelihatan seperti phishing.",
                "recommendation": "Do not enter your credentials.",
            }
        )
    )

    compiled_graph = compile_graph()

    initial_state: dict[str, Any] = {
        "session_id": "sess-phish-graph-1",
        "user_id": "619ebd02-82fc-4a13-81f6-ff575c20278d",
        "trigger_type": "PHISHING",
        "trigger_payload": {
            "material": {
                "content_type": "IMAGE",
                "content": "ZmFrZS1pbWFnZS1ieXRlcw==",
                "source": "SMS",
            }
        },
        "status_messages": [],
    }

    final_state = await compiled_graph.ainvoke(initial_state)

    # Stage 1 phishing worker ran and scored the lookalike page high via rules.
    assert final_state["workers_to_activate"] == ["phishing"]
    assert final_state["phishing_finding"] is not None
    assert final_state["phishing_finding"]["score"] >= 75
    # Stage 2 research worker ran after phishing (consumed the OCR text).
    assert final_state["research_finding"] is not None
    # PHISHING override keeps the verdict HIGH despite the low research score.
    assert final_state["risk_tier"] == "HIGH"
    assert final_state["action_taken"] == "WARNING"
    assert final_state["case_id"] == case_uuid

    mock_insert_submission.assert_called_once()
    submission_kwargs = mock_insert_submission.call_args[0][0]
    assert submission_kwargs["case_id"] == case_uuid
    assert submission_kwargs["content_type"] == "IMAGE"
    assert "PayPal" in submission_kwargs["extracted_text"]
    assert "data:image" not in submission_kwargs["raw_content"]
