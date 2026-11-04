"""Unit tests for Supabase & vector store database module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.db.supabase import (
    fetch_case_context,
    fetch_telemetry_events,
    fetch_user_transaction_history,
    insert_admin_alert,
    insert_call_transcript,
    insert_case_entities,
    insert_fraud_case,
    insert_phishing_submission,
    update_fraud_case_status,
    update_transaction_status,
)
from src.db.vector_store import (
    add_fraud_memory,
    check_blacklist,
    embed_text,
    search_fraud_memory,
)


def test_embed_text_returns_768_float_vector() -> None:
    """Assert embed_text returns a 768-dimensional float vector."""

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"embedding": [0.1] * 768}]}
    mock_response.raise_for_status = MagicMock()

    with patch.dict("os.environ", {"DASHSCOPE_API_KEY": "test-dashscope-key"}):
        with patch("httpx.post", return_value=mock_response):
            vector = embed_text("Scam alert message")
    assert isinstance(vector, list)
    assert len(vector) == 768
    assert all(isinstance(val, float) for val in vector)


@patch("src.db.vector_store.supabase_client")
@patch("src.db.vector_store.embed_text")
def test_search_fraud_memory_filters_by_threshold(
    mock_embed: MagicMock, mock_supabase: MagicMock
) -> None:
    """Assert search_fraud_memory passes embedding vector to Supabase RPC search."""
    mock_embed.return_value = [0.05] * 768
    mock_rpc_response = MagicMock()
    mock_rpc_response.execute.return_value.data = [
        {
            "case_id": "case-101",
            "similarity": 0.88,
            "content": "Macau scam victim report",
        }
    ]
    mock_supabase.rpc.return_value = mock_rpc_response

    results = search_fraud_memory("0161234567", threshold=0.75, top_k=5)
    assert len(results) == 1
    assert results[0]["case_id"] == "case-101"
    assert results[0]["similarity"] == 0.88
    mock_supabase.rpc.assert_called_once_with(
        "search_fraud_memory",
        {
            "query_embedding": [0.05] * 768,
            "match_threshold": 0.75,
            "match_count": 5,
        },
    )


@patch("src.db.vector_store.search_fraud_memory")
def test_check_blacklist_invokes_search_with_high_threshold(
    mock_search: MagicMock,
) -> None:
    """Assert check_blacklist calls search_fraud_memory with threshold 0.80."""
    mock_search.return_value = [
        {"case_id": "case-99", "similarity": 0.85, "content": "Blacklisted phone"}
    ]

    res = check_blacklist(phone="0161234567", url="http://scam.xyz")
    assert len(res) == 1
    mock_search.assert_called_once_with(
        "phone number 0161234567 URL http://scam.xyz", threshold=0.80, top_k=3
    )


@patch("src.db.vector_store.supabase_client")
@patch("src.db.vector_store.embed_text")
def test_add_fraud_memory_inserts_record(
    mock_embed: MagicMock, mock_supabase: MagicMock
) -> None:
    """Assert add_fraud_memory embeds content and inserts memory row."""
    mock_embed.return_value = [0.0] * 768
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    add_fraud_memory(
        case_id="case-001",
        fraud_type="macau_scam",
        content="Impersonation scam call",
        metadata={
            "phone_numbers": ["0161234567"],
            "bank_accounts": ["12345678"],
            "urls": [],
            "risk_tier": "HIGH",
        },
    )

    mock_supabase.table.assert_called_once_with("fraud_memory")
    mock_table.insert.assert_called_once()
    inserted_row = mock_table.insert.call_args[0][0]
    assert inserted_row["case_id"] == "case-001"
    assert inserted_row["fraud_type"] == "macau_scam"
    assert inserted_row["embedding"] == [0.0] * 768
    assert inserted_row["phone_numbers"] == ["0161234567"]


@patch("src.db.supabase.supabase_client")
def test_insert_fraud_case(mock_supabase: MagicMock) -> None:
    """Assert insert_fraud_case executes table insert and returns inserted ID."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "case-uuid-123"}
    ]

    case_data = {
        "session_id": "sess-1",
        "user_id": "usr-1",
        "trigger_type": "TRANSACTION",
        "risk_score": 85,
        "risk_tier": "HIGH",
        "status": "frozen",
        "action_taken": "FREEZE_30_MIN",
        "xai_report": {"verdict_summary": "High risk transfer"},
    }
    case_id = insert_fraud_case(case_data)
    assert case_id == "case-uuid-123"
    mock_supabase.table.assert_called_once_with("fraud_cases")


@patch("src.db.supabase.supabase_client")
def test_update_fraud_case_status(mock_supabase: MagicMock) -> None:
    """Assert update_fraud_case_status updates status and action_taken."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    update_fraud_case_status(
        "case-123", status="approved", action_taken="BIOMETRIC_PASSED"
    )
    mock_supabase.table.assert_called_once_with("fraud_cases")
    mock_table.update.assert_called_once()


@patch("src.db.supabase.supabase_client")
def test_insert_call_transcript(mock_supabase: MagicMock) -> None:
    """Assert insert_call_transcript inserts transcript record."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "ts-111"}
    ]

    res_id = insert_call_transcript(
        case_id="case-123",
        speaker="CALLER",
        utterance="Please transfer money to safe account",
        risk_score=95,
    )
    assert res_id == "ts-111"
    mock_supabase.table.assert_called_once_with("call_transcripts")


@patch("src.db.supabase.supabase_client")
def test_fetch_case_context_aggregates_subtables(
    mock_supabase: MagicMock,
) -> None:
    """Assert fetch_case_context aggregates transcripts, phishing content, and entities correctly."""

    def table_side_effect(name: str) -> MagicMock:
        mock_query = MagicMock()
        if name == "call_transcripts":
            mock_query.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": "t1", "utterance": "call message"}
            ]
        elif name == "phishing_submissions":
            mock_query.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": "p1", "raw_content": "http://scam.xyz"}
            ]
        elif name == "case_entities":
            mock_query.select.return_value.eq.return_value.execute.return_value.data = [
                {"id": "e1", "entity_type": "PHONE", "entity_value": "0161234567"}
            ]
        return mock_query

    mock_supabase.table.side_effect = table_side_effect

    ctx = fetch_case_context("case-123")
    assert "transcripts" in ctx
    assert "phishing" in ctx
    assert "entities" in ctx
    assert len(ctx["transcripts"]) == 1
    assert len(ctx["phishing"]) == 1
    assert len(ctx["entities"]) == 1
    assert ctx["transcripts"][0]["utterance"] == "call message"
    assert ctx["phishing"][0]["raw_content"] == "http://scam.xyz"
    assert ctx["entities"][0]["entity_value"] == "0161234567"


@patch("src.db.supabase.supabase_client")
def test_fetch_telemetry_events(mock_supabase: MagicMock) -> None:
    """Assert fetch_telemetry_events queries telemetry events for user & session."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_execute = MagicMock()
    mock_execute.data = [{"event_type": "SCREEN_SHARE_DETECTED"}]
    mock_table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
        mock_execute
    )

    events = fetch_telemetry_events("usr-1", "sess-1", limit=10)
    assert len(events) == 1
    assert events[0]["event_type"] == "SCREEN_SHARE_DETECTED"
    mock_supabase.table.assert_called_once_with("telemetry_events")


@patch("src.db.supabase.supabase_client")
def test_fetch_user_transaction_history(
    mock_supabase: MagicMock,
) -> None:
    """Assert fetch_user_transaction_history aggregates statistics correctly."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    now_iso = datetime.now(UTC).isoformat()
    mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
        {
            "amount_myr": 100.0,
            "recipient_account": "ACC-2",
            "initiated_at": now_iso,
        },
        {
            "amount_myr": 300.0,
            "recipient_account": "ACC-3",
            "initiated_at": now_iso,
        },
    ]

    history = fetch_user_transaction_history("ACC-1", days=90)
    assert history["total_count"] == 2
    assert history["total_amount_myr"] == 400.0
    assert history["avg_amount"] == 200.0
    assert history["max_amount"] == 300.0
    assert set(history["known_recipients"]) == {"ACC-2", "ACC-3"}


@patch("src.db.supabase.supabase_client")
def test_insert_case_entities(mock_supabase: MagicMock) -> None:
    """Assert insert_case_entities formats and inserts entity rows."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    entities = [
        {"entity_type": "PHONE", "entity_value": "0161234567"},
        {"entity_type": "URL", "entity_value": "http://scam.xyz"},
    ]
    insert_case_entities("case-555", entities)
    mock_supabase.table.assert_called_once_with("case_entities")
    mock_table.insert.assert_called_once()
    inserted = mock_table.insert.call_args[0][0]
    assert len(inserted) == 2
    assert inserted[0]["case_id"] == "case-555"


@patch("src.db.supabase.supabase_client")
def test_insert_phishing_submission(mock_supabase: MagicMock) -> None:
    """Assert insert_phishing_submission inserts record and returns ID."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "phish-777"}
    ]

    sub_id = insert_phishing_submission(
        {
            "case_id": "case-1",
            "content_type": "URL",
            "raw_content": "http://scam.xyz",
        }
    )
    assert sub_id == "phish-777"
    mock_supabase.table.assert_called_once_with("phishing_submissions")


@patch("src.db.supabase.supabase_client")
def test_update_transaction_status(mock_supabase: MagicMock) -> None:
    """Assert update_transaction_status updates transaction status and timestamps."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    update_transaction_status(
        "tx-999", status="frozen", unfreeze_at="2026-07-28T14:00:00Z"
    )
    mock_supabase.table.assert_called_once_with("transactions")
    mock_table.update.assert_called_once()
    payload = mock_table.update.call_args[0][0]
    assert payload["status"] == "frozen"
    assert "frozen_at" in payload
    assert payload["unfreeze_at"] == "2026-07-28T14:00:00Z"


@patch("src.db.supabase.supabase_client")
def test_insert_admin_alert(mock_supabase: MagicMock) -> None:
    """Assert insert_admin_alert inserts high risk alert record."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "alert-888"}
    ]

    alert_id = insert_admin_alert(
        {
            "case_id": "case-1",
            "alert_type": "HIGH_RISK_FREEZE",
            "status": "pending",
            "details": {"risk_score": 95},
        }
    )
    assert alert_id == "alert-888"
    mock_supabase.table.assert_called_once_with("admin_alerts")
