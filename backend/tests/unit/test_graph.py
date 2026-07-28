"""Unit tests for LangGraph Orchestrator & State Machine (Module 5)."""

from typing import Any
from unittest.mock import AsyncMock, patch

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
    assert call_res["workers_to_activate"] == ["phone", "research"]

    telemetry_state: GraphState = {
        "trigger_type": "TELEMETRY",
        "trigger_payload": {},
        "status_messages": [],
    }
    telemetry_res = await orchestrator_node(telemetry_state)
    assert telemetry_res["workers_to_activate"] == ["telemetry"]


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


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.insert_admin_alert", new_callable=AsyncMock)
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=AsyncMock)
@patch("src.agents.graph_nodes.freeze_transaction", new_callable=AsyncMock)
async def test_action_dispatcher_high_risk_freeze(
    mock_freeze: AsyncMock,
    mock_insert_case: AsyncMock,
    mock_insert_alert: AsyncMock,
) -> None:
    """Assert action_dispatcher_node sets FREEZE_30_MIN action for HIGH risk tier."""
    mock_insert_case.return_value = "case-uuid-high-123"
    mock_insert_alert.return_value = "alert-uuid-456"

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
    mock_insert_case.assert_called_once()
    mock_insert_alert.assert_called_once()


@pytest.mark.asyncio
@patch("src.agents.graph_nodes.Groq")
@patch("src.agents.graph_nodes.insert_fraud_case", new_callable=AsyncMock)
async def test_full_graph_execution_mocked(
    mock_insert_case: AsyncMock,
    mock_groq: Any,
) -> None:
    """Test full compiled graph execution with mocked LLM and DB calls."""
    mock_insert_case.return_value = "case-test-full-graph"

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
