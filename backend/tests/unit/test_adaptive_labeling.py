"""Unit tests for the adaptive case-labeling feature (fraud_cases.user_label + learned_keywords)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.graph_nodes import _is_uuid
from src.agents.workers.phishing import _merge_learned_keywords
from src.agents.workers.vector_memory_utils import (
    _score_phrase_weight,
    extract_novel_phrases,
)
from src.db.supabase import fetch_case_context


# ---------------------------------------------------------------------------
# _is_uuid helper
# ---------------------------------------------------------------------------
def test_is_uuid_validates_uuid_shapes() -> None:
    assert _is_uuid("123e4567-e89b-12d3-a456-426614174000") is True
    assert _is_uuid("sess-call-123") is False
    assert _is_uuid(None) is False
    assert _is_uuid("") is False
    assert _is_uuid("not-a-uuid") is False


# ---------------------------------------------------------------------------
# fetch_case_context groups entities
# ---------------------------------------------------------------------------
@patch("src.db.supabase.get_supabase")
def test_fetch_case_context_groups_entities(mock_supabase: MagicMock) -> None:
    """Assert fetch_case_context returns grouped bank_accounts/phone_numbers/urls lists."""
    table_mock = MagicMock()
    mock_supabase.return_value.table.return_value = table_mock
    table_mock.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=[]),  # transcripts
        MagicMock(data=[]),  # phishing
        MagicMock(  # entities
            data=[
                {"entity_type": "ACCOUNT", "entity_value": "1122334455"},
                {"entity_type": "PHONE", "entity_value": "+60161234567"},
                {"entity_type": "URL", "entity_value": "https://fake-bank.example"},
                {"entity_type": "OTHER", "entity_value": "ignore me"},
            ]
        ),
    ]

    ctx = fetch_case_context("case-1")
    assert ctx["bank_accounts"] == ["1122334455"]
    assert ctx["phone_numbers"] == ["+60161234567"]
    assert ctx["urls"] == ["https://fake-bank.example"]
    assert len(ctx["entities"]) == 4  # raw rows preserved


# ---------------------------------------------------------------------------
# _persist_call_case persists case + transcripts + entities
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@patch("src.api.websocket_call.insert_fraud_case")
@patch("src.api.websocket_call.insert_call_transcript")
@patch("src.api.websocket_call.insert_case_entities")
@patch("src.api.websocket_call.session_store")
async def test_persist_call_case_writes_case_and_transcripts(
    mock_store: MagicMock,
    mock_insert_entities: MagicMock,
    mock_insert_transcript: MagicMock,
    mock_insert_case: MagicMock,
) -> None:
    """Assert _persist_call_case writes a fraud case + transcripts + entities."""
    from src.api.websocket_call import call_phone_states, _persist_call_case

    mock_insert_case.return_value = "case-persisted-1"
    mock_store.get_call.return_value = {
        "user_id": "usr-123",
        "caller_number": "+60161234567",
        "session_id": "sess-abc",
    }

    call_phone_states["call-x"] = {
        "transcript": [
            {"speaker": "SCAMMER", "text": "Transfer to safe account now", "ts": 0.1},
            {"speaker": "CUSTOMER", "text": "Which account?", "ts": 0.2},
            {"speaker": "TRANSAFE_AI", "text": "Please do not share your OTP.", "ts": 0.3},
        ]
    }
    deep_event = {
        "score": 88,
        "risk_tier": "HIGH",
        "confidence": 0.9,
        "evidence": ["Urgent demand to transfer funds"],
        "extracted_entities": {"bank_accounts": ["1122334455"]},
        "research": {},
    }

    try:
        case_id = await _persist_call_case("call-x", deep_event)
        assert case_id == "case-persisted-1"

        # Case insert: session_id UUID-normalized, status reported for HIGH
        case_args = mock_insert_case.call_args[0][0]
        assert case_args["trigger_type"] == "CALL"
        assert case_args["user_id"] == "usr-123"
        assert case_args["status"] == "reported"
        assert case_args["action_taken"] == "AGENT_HANGUP"
        assert case_args["risk_tier"] == "HIGH"

        # Transcript rows use DB CHECK speaker values
        speakers = [c.args[1] for c in mock_insert_transcript.call_args_list]
        assert speakers == ["CALLER", "USER", "AI"]

        # Entities include caller number + extracted account
        entity_rows = mock_insert_entities.call_args[0][1]
        values = {r["entity_type"]: r["entity_value"] for r in entity_rows}
        assert values.get("PHONE") == "+60161234567"
        assert values.get("ACCOUNT") == "1122334455"
    finally:
        call_phone_states.pop("call-x", None)


@pytest.mark.asyncio
@patch("src.api.websocket_call.session_store")
async def test_persist_call_case_skips_without_transcript(
    mock_store: MagicMock,
) -> None:
    """Assert _persist_call_case returns None when there is no transcript."""
    from src.api.websocket_call import call_phone_states, _persist_call_case

    call_phone_states["call-empty"] = {"transcript": []}
    try:
        result = await _persist_call_case("call-empty", None)
        assert result is None
        mock_store.get_call.assert_not_called()
    finally:
        call_phone_states.pop("call-empty", None)


# ---------------------------------------------------------------------------
# learned keyword merge (B2)
# ---------------------------------------------------------------------------
@patch("src.db.supabase.fetch_learned_keywords")
def test_merge_learned_keywords_unions_heavy_and_light(
    mock_fetch: MagicMock,
) -> None:
    """Assert _merge_learned_keywords unions DB keywords into playbook lists."""
    mock_fetch.return_value = [
        {"keyword": "safe account", "keyword_type": "heavy"},
        {"keyword": "don't hang up", "keyword_type": "light"},
        {"keyword": "VICTIM PAYS TAX", "keyword_type": "heavy"},
    ]
    playbook = {
        "heavy": ["transfer"],
        "light": ["arrest"],
        "guidance": "g",
        "raw": "",
        "_learned_merged": False,
    }
    merged = _merge_learned_keywords(playbook)
    assert "transfer" in merged["heavy"]
    assert "safe account" in merged["heavy"]
    assert "victim pays tax" in merged["heavy"]  # lowercased
    assert "arrest" in merged["light"]
    assert "don't hang up" in merged["light"]
    assert merged["_learned_merged"] is True


def test_score_phrase_weight_heuristic() -> None:
    assert _score_phrase_weight("transfer to safe account") == "heavy"
    assert _score_phrase_weight("please call me tomorrow") == "light"


# ---------------------------------------------------------------------------
# extract_novel_phrases (B1 learning path)
# ---------------------------------------------------------------------------
@patch("src.db.supabase.fetch_learned_keywords")
@patch("src.agents.workers.phishing.get_phishing_playbook_data")
def test_extract_novel_phrases_skips_known_playbook_terms(
    mock_playbook: MagicMock, mock_learned: MagicMock
) -> None:
    """Assert novel phrase extraction excludes phrases already in the playbook."""
    mock_playbook.return_value = {
        "heavy": ["transfer", "safe account"],
        "light": ["don't hang up"],
        "guidance": "",
        "raw": "",
    }
    mock_learned.return_value = [{"keyword": "already learned", "keyword_type": "light"}]

    case = {"xai_report": {"evidence": ["The scammer demanded a transfer to a safe account immediately"]}}
    context = {"transcripts": [], "phishing": []}
    phrases = extract_novel_phrases(case, context)
    keys = {p[0].lower() for p in phrases}
    # Known playbook / learned terms must NOT be re-learned
    assert "transfer" not in keys
    assert "already learned" not in keys
    # At least one novel phrase surfaced
    assert len(phrases) > 0


# ---------------------------------------------------------------------------
# label endpoint happy path (B1) — via FastAPI TestClient
# ---------------------------------------------------------------------------
def test_label_endpoint_rejects_unknown_case() -> None:
    """Assert POST /cases/{id}/label returns 404 for a missing case."""
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    with patch("src.api.triggers.fetch_fraud_case", return_value=None):
        resp = client.post(
            "/api/v1/cases/nope/label",
            json={"label": "fraud"},
            headers={"X-API-Key": "transafe-hackathon-key-2026"},
        )
        assert resp.status_code == 404
