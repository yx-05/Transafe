"""Unit tests for Database and Vector Persistence Layer (Module 1)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.db.supabase import (
    FraudCaseRecord,
    fetch_case_context,
    fetch_telemetry_events,
    fetch_user_transaction_history,
    init_supabase,
    insert_admin_alert,
    insert_call_transcript,
    insert_case_entities,
    insert_fraud_case,
    insert_phishing_submission,
    update_fraud_case_status,
    update_transaction_status,
)
from src.db.vector_store import (
    FraudMemoryRecord,
    add_fraud_memory,
    check_blacklist,
    embed_text,
    init_vector_store,
    search_fraud_memory,
)


def test_fraud_case_record_model() -> None:
    """Test FraudCaseRecord Pydantic model validation."""
    record = FraudCaseRecord(
        session_id="sess-123",
        user_id="usr-456",
        trigger_type="TRANSACTION",
        risk_score=85,
        risk_tier="HIGH",
        status="pending",
        action_taken="FREEZE_30_MIN",
        xai_report={"reason": "Suspicious large transfer"},
        transaction_id="tx-789",
    )
    assert record.session_id == "sess-123"
    assert record.risk_score == 85
    assert record.risk_tier == "HIGH"
    assert record.transaction_id == "tx-789"


def test_fraud_memory_record_model() -> None:
    """Test FraudMemoryRecord Pydantic model validation."""
    memory = FraudMemoryRecord(
        case_id="case-101",
        fraud_type="macau_scam",
        content="Impersonation of PDRM officer",
        phone_numbers=["0161234567"],
        bank_accounts=["7653-1234-5678-9012"],
        urls=["http://scam.site"],
        amount_lost_myr=12000.0,
        risk_tier="HIGH",
        source="user_report",
    )
    assert memory.case_id == "case-101"
    assert memory.fraud_type == "macau_scam"
    assert len(memory.phone_numbers) == 1
    assert memory.amount_lost_myr == 12000.0


@patch("src.db.vector_store.groq_client")
def test_embed_text_returns_768_float_vector(mock_groq: MagicMock) -> None:
    """Assert embed_text returns 768-dimensional float vector."""
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1] * 768)]
    mock_groq.embeddings.create.return_value = mock_response

    vec = embed_text("test scam message")
    assert len(vec) == 768
    assert isinstance(vec[0], float)
    assert vec[0] == 0.1
    mock_groq.embeddings.create.assert_called_once_with(
        model="nomic-embed-text-v1.5", input="test scam message"
    )


@patch("src.db.vector_store.supabase_client")
@patch("src.db.vector_store.embed_text")
def test_search_fraud_memory_filters_by_threshold(
    mock_embed: MagicMock, mock_supabase: MagicMock
) -> None:
    """Assert search_fraud_memory calls RPC with correct threshold and returns results."""
    mock_embed.return_value = [0.1] * 768
    mock_rpc_response = MagicMock()
    mock_rpc_response.execute.return_value.data = [
        {
            "id": "mem-1",
            "case_id": "case-1",
            "similarity": 0.88,
            "content": "Macau scam report",
        }
    ]
    mock_supabase.rpc.return_value = mock_rpc_response

    results = search_fraud_memory("0161234567", threshold=0.75, top_k=5)
    assert len(results) == 1
    assert results[0]["case_id"] == "case-1"
    assert results[0]["similarity"] == 0.88
    mock_supabase.rpc.assert_called_once_with(
        "search_fraud_memory",
        {
            "query_embedding": [0.1] * 768,
            "match_threshold": 0.75,
            "match_count": 5,
        },
    )


@patch("src.db.vector_store.search_fraud_memory")
def test_check_blacklist(mock_search: MagicMock) -> None:
    """Assert check_blacklist constructs search query with high threshold."""
    mock_search.return_value = [{"id": "mem-1", "similarity": 0.95}]

    res = check_blacklist(
        phone="0161234567", url="http://maybank2u-verify.xyz"
    )
    assert len(res) == 1
    mock_search.assert_called_once_with(
        "phone number 0161234567 URL http://maybank2u-verify.xyz",
        threshold=0.80,
        top_k=3,
    )


@patch("src.db.vector_store.supabase_client")
@patch("src.db.vector_store.embed_text")
def test_add_fraud_memory(
    mock_embed: MagicMock, mock_supabase: MagicMock
) -> None:
    """Assert add_fraud_memory embeds content and inserts row into pgvector table."""
    mock_embed.return_value = [0.2] * 768
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    metadata = {
        "phone_numbers": ["0161234567"],
        "bank_accounts": ["7653-1234-5678-9012"],
        "urls": [],
        "amount_lost_myr": 5000.0,
        "risk_tier": "HIGH",
        "source": "user_report",
    }
    add_fraud_memory(
        case_id="case-200",
        fraud_type="phishing",
        content="Phishing attempt narrative",
        metadata=metadata,
    )

    mock_embed.assert_called_once_with("Phishing attempt narrative")
    mock_supabase.table.assert_called_once_with("fraud_memory")
    mock_table.insert.assert_called_once()
    inserted_arg = mock_table.insert.call_args[0][0]
    assert inserted_arg["case_id"] == "case-200"
    assert inserted_arg["fraud_type"] == "phishing"
    assert len(inserted_arg["embedding"]) == 768


@patch("src.db.supabase.create_client")
@patch("os.getenv")
def test_init_supabase(mock_getenv: MagicMock, mock_create: MagicMock) -> None:
    """Test init_supabase initializes client from env variables."""

    def side_effect(key: str, default: str = "") -> str:
        if key == "SUPABASE_URL":
            return "https://xyz.supabase.co"
        if key == "SUPABASE_SERVICE_KEY":
            return "secret-key"
        return default

    mock_getenv.side_effect = side_effect
    init_supabase()
    mock_create.assert_called_once_with("https://xyz.supabase.co", "secret-key")


@patch("src.db.vector_store.Groq")
@patch("src.db.vector_store.create_client")
@patch("os.getenv")
def test_init_vector_store(
    mock_getenv: MagicMock, mock_create_sp: MagicMock, mock_groq: MagicMock
) -> None:
    """Test init_vector_store initializes Groq and Supabase clients."""

    def side_effect(key: str, default: str = "") -> str:
        if key == "GROQ_API_KEY":
            return "groq-key"
        if key == "SUPABASE_URL":
            return "https://xyz.supabase.co"
        if key == "SUPABASE_SERVICE_KEY":
            return "secret-key"
        return default

    mock_getenv.side_effect = side_effect
    init_vector_store()
    mock_groq.assert_called_once_with(api_key="groq-key")
    mock_create_sp.assert_called_once_with(
        "https://xyz.supabase.co", "secret-key"
    )


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_insert_fraud_case(mock_supabase: MagicMock) -> None:
    """Assert insert_fraud_case inserts row and returns inserted ID."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "case-uuid-999"}
    ]

    case_data = {
        "session_id": "sess-1",
        "user_id": "usr-1",
        "trigger_type": "TRANSACTION",
        "risk_score": 90,
        "risk_tier": "HIGH",
        "status": "pending",
        "action_taken": "FREEZE_30_MIN",
        "xai_report": {},
    }
    case_id = await insert_fraud_case(case_data)
    assert case_id == "case-uuid-999"
    mock_supabase.table.assert_called_once_with("fraud_cases")


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_update_fraud_case_status(mock_supabase: MagicMock) -> None:
    """Assert update_fraud_case_status updates status and action_taken."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    await update_fraud_case_status(
        "case-123", "reviewed", "BIOMETRIC_CHALLENGE"
    )
    mock_supabase.table.assert_called_once_with("fraud_cases")
    mock_table.update.assert_called_once()
    update_arg = mock_table.update.call_args[0][0]
    assert update_arg["status"] == "reviewed"
    assert update_arg["action_taken"] == "BIOMETRIC_CHALLENGE"


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_insert_call_transcript(mock_supabase: MagicMock) -> None:
    """Assert insert_call_transcript inserts transcript record."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "ts-111"}
    ]

    res_id = await insert_call_transcript(
        case_id="case-123",
        speaker="CALLER",
        utterance="Please transfer money to safe account",
        risk_score=95,
    )
    assert res_id == "ts-111"
    mock_supabase.table.assert_called_once_with("call_transcripts")


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_fetch_case_context_aggregates_subtables(
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

    ctx = await fetch_case_context("case-123")
    assert "transcripts" in ctx
    assert "phishing" in ctx
    assert "entities" in ctx
    assert len(ctx["transcripts"]) == 1
    assert len(ctx["phishing"]) == 1
    assert len(ctx["entities"]) == 1
    assert ctx["transcripts"][0]["utterance"] == "call message"
    assert ctx["phishing"][0]["raw_content"] == "http://scam.xyz"
    assert ctx["entities"][0]["entity_value"] == "0161234567"


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_fetch_telemetry_events(mock_supabase: MagicMock) -> None:
    """Assert fetch_telemetry_events queries telemetry events for user & session."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_execute = MagicMock()
    mock_execute.data = [{"event_type": "SCREEN_SHARE_DETECTED"}]
    mock_table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = (
        mock_execute
    )

    events = await fetch_telemetry_events("usr-1", "sess-1", limit=10)
    assert len(events) == 1
    assert events[0]["event_type"] == "SCREEN_SHARE_DETECTED"
    mock_supabase.table.assert_called_once_with("telemetry_events")


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_fetch_user_transaction_history(
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

    history = await fetch_user_transaction_history("ACC-1", days=90)
    assert history["total_count"] == 2
    assert history["total_amount_myr"] == 400.0
    assert history["avg_amount"] == 200.0
    assert history["max_amount"] == 300.0
    assert set(history["known_recipients"]) == {"ACC-2", "ACC-3"}


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_insert_case_entities(mock_supabase: MagicMock) -> None:
    """Assert insert_case_entities formats and inserts entity rows."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    entities = [
        {"entity_type": "PHONE", "entity_value": "0161234567"},
        {"entity_type": "URL", "entity_value": "http://scam.xyz"},
    ]
    await insert_case_entities("case-555", entities)
    mock_supabase.table.assert_called_once_with("case_entities")
    mock_table.insert.assert_called_once()
    inserted = mock_table.insert.call_args[0][0]
    assert len(inserted) == 2
    assert inserted[0]["case_id"] == "case-555"


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_insert_phishing_submission(mock_supabase: MagicMock) -> None:
    """Assert insert_phishing_submission inserts record and returns ID."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "phish-777"}
    ]

    sub_id = await insert_phishing_submission(
        {
            "case_id": "case-1",
            "content_type": "URL",
            "raw_content": "http://scam.xyz",
        }
    )
    assert sub_id == "phish-777"
    mock_supabase.table.assert_called_once_with("phishing_submissions")


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_update_transaction_status(mock_supabase: MagicMock) -> None:
    """Assert update_transaction_status updates transaction status and timestamps."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table

    await update_transaction_status(
        "tx-999", status="frozen", unfreeze_at="2026-07-28T14:00:00Z"
    )
    mock_supabase.table.assert_called_once_with("transactions")
    mock_table.update.assert_called_once()
    payload = mock_table.update.call_args[0][0]
    assert payload["status"] == "frozen"
    assert "frozen_at" in payload
    assert payload["unfreeze_at"] == "2026-07-28T14:00:00Z"


@pytest.mark.asyncio
@patch("src.db.supabase.supabase_client")
async def test_insert_admin_alert(mock_supabase: MagicMock) -> None:
    """Assert insert_admin_alert inserts high risk alert record."""
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [
        {"id": "alert-888"}
    ]

    alert_id = await insert_admin_alert(
        {
            "case_id": "case-1",
            "alert_type": "HIGH_RISK_FREEZE",
            "status": "pending",
            "details": {"risk_score": 95},
        }
    )
    assert alert_id == "alert-888"
    mock_supabase.table.assert_called_once_with("admin_alerts")
