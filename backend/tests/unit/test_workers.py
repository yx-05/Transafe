"""Unit tests for TranSafe Module 4 Worker Agents."""

from unittest.mock import MagicMock, patch

from src.agents.state import GraphState, WorkerFinding
from src.agents.workers.financial import financial_worker_node
from src.agents.workers.phishing import phishing_worker_node
from src.agents.workers.phone import phone_worker_node
from src.agents.workers.research import research_worker_node
from src.agents.workers.telemetry import telemetry_worker_node


def test_worker_finding_pydantic_schema():
    """Verify WorkerFinding model validates attributes correctly."""
    finding = WorkerFinding(
        worker="financial",
        score=85,
        confidence=0.9,
        evidence=["High transaction amount"],
        error=None,
    )
    assert finding.worker == "financial"
    assert finding.score == 85
    assert finding.confidence == 0.9
    assert finding.evidence == ["High transaction amount"]
    assert finding.error is None


# ── 1. Telemetry Worker Tests ──

@patch("src.agents.workers.telemetry.llm")
@patch("src.agents.workers.telemetry.fetch_telemetry_events", new_callable=MagicMock)
def test_telemetry_worker_handles_missing_biometrics_gracefully(
    mock_fetch_events: MagicMock, mock_llm: MagicMock
):
    """Assert telemetry_worker_node handles missing optional biometric blocks gracefully."""
    mock_fetch_events.return_value = []
    mock_llm.invoke.side_effect = Exception("LLM disabled in test")

    state: GraphState = {
        "user_id": "user-123",
        "session_id": "sess-456",
        "trigger_type": "TELEMETRY",
        "trigger_payload": {},
    }

    res = telemetry_worker_node(state)
    finding = res["telemetry_finding"]

    assert finding["worker"] == "telemetry"
    assert isinstance(finding["score"], int)
    assert finding["score"] <= 20
    assert finding["confidence"] >= 0.80
    assert any("empty or clean" in ev for ev in finding["evidence"])


@patch("src.agents.workers.telemetry.fetch_telemetry_events", new_callable=MagicMock)
def test_telemetry_worker_detects_anomalies(mock_fetch_events: MagicMock):
    """Verify telemetry worker flags high flight times and copy paste events."""
    mock_fetch_events.return_value = [
        {"event_type": "KEYSTROKE", "event_value": 650.0},
        {"event_type": "COPY_PASTE", "event_value": "account_number"},
        {"event_type": "SCREEN_SHARE_DETECTED", "event_value": True},
    ]

    state: GraphState = {
        "user_id": "user-123",
        "session_id": "sess-456",
        "trigger_type": "TELEMETRY",
        "trigger_payload": {},
    }

    res = telemetry_worker_node(state)
    finding = res["telemetry_finding"]

    assert finding["score"] >= 80
    assert any("flight time" in ev for ev in finding["evidence"])
    assert any("copy-paste" in ev.lower() for ev in finding["evidence"])


# ── 2. Financial Worker Tests ──

@patch("src.agents.workers.financial.fetch_user_transaction_history", new_callable=MagicMock)
@patch("src.agents.workers.financial.llm")
def test_financial_worker_case_context_override(
    mock_llm: MagicMock, mock_history: MagicMock
):
    """Assert financial_worker_node overrides score to 95+ when recipient_account matches associated_case_context."""
    mock_history.return_value = {"avg_amount": 200.0, "known_recipients": ["1111-2222"]}

    # Mock LLM returning lower score
    mock_response = MagicMock()
    mock_response.content = '{"score": 50, "confidence": 0.8, "evidence": ["Normal amount"]}'
    mock_llm.invoke.return_value = mock_response

    state: GraphState = {
        "trigger_type": "TRANSACTION",
        "trigger_payload": {
            "transaction": {
                "sender_account": "1234-5678",
                "recipient_account": "7653-1234-5678-9012",
                "amount": 5000.0,
            }
        },
        "associated_case_context": {
            "bank_accounts": ["7653-1234-5678-9012"],
            "transcripts": ["Scammer told me to transfer to 7653-1234-5678-9012"],
        },
    }

    res = financial_worker_node(state)
    finding = res["financial_finding"]

    assert finding["worker"] == "financial"
    assert finding["score"] >= 95
    assert finding["confidence"] >= 0.95
    assert any("matches active call transcript" in ev for ev in finding["evidence"])


# ── 3. Research Worker Tests ──

@patch("src.agents.workers.research.tavily_search")
@patch("src.agents.workers.research.search_fraud_memory")
@patch("src.agents.workers.research.llm")
def test_research_worker_executes_tavily_fallback_low_score(
    mock_llm: MagicMock, mock_search_memory: MagicMock, mock_tavily: MagicMock
):
    """Assert research_worker_node executes Tavily fallback when internal pgvector score < 0.75."""
    mock_search_memory.return_value = [
        {"case_id": "case-old", "similarity": 0.41, "content": "Unrelated report"}
    ]
    mock_tavily.return_value = [
        {"title": "Low Yat Scam Post", "url": "https://lowyat.net/topic/scam123"}
    ]
    mock_llm.invoke.side_effect = Exception("LLM fallback to rules")

    state: GraphState = {
        "trigger_type": "TRANSACTION",
        "trigger_payload": {"recipient_account": "9999-8888-7777"},
    }

    res = research_worker_node(state)
    finding = res["research_finding"]

    mock_tavily.assert_called_once_with(["9999-8888-7777"])
    assert finding["worker"] == "research"
    assert finding["score"] >= 70
    assert any("Tavily web search" in ev for ev in finding["evidence"])


@patch("src.agents.workers.research.add_fraud_memory")
@patch("src.agents.workers.research.llm")
def test_research_worker_ingest_mode(mock_llm: MagicMock, mock_add_memory: MagicMock):
    """Verify research_worker_node handles INGEST mode for REPORT trigger."""
    mock_llm_response = MagicMock()
    mock_llm_response.content = "Victim reported Macau scam caller pretending to be Bank Negara."
    mock_llm.invoke.return_value = mock_llm_response

    state: GraphState = {
        "case_id": "case-report-1",
        "trigger_type": "REPORT",
        "trigger_payload": {
            "description": "Scammer called asking for RM 10,000",
            "fraud_type": "macau_scam",
            "phone_numbers": ["0161234567"],
        },
    }

    res = research_worker_node(state)
    finding = res["research_finding"]

    mock_add_memory.assert_called_once()
    assert finding["score"] == 0
    assert any("Successfully ingested fraud report" in ev for ev in finding["evidence"])


# ── 4. Phishing Analyst Worker Tests ──

@patch("src.agents.workers.phishing.search_fraud_memory")
@patch("src.agents.workers.phishing.extract_text_from_image", new_callable=MagicMock)
@patch("src.agents.workers.phishing.llm")
def test_phishing_worker_returns_extracted_entities(
    mock_llm: MagicMock, mock_ocr: MagicMock, mock_search_memory: MagicMock
):
    """Assert phishing_worker_node returns extracted entities in state updates."""
    mock_ocr.return_value = "URGENT: Verify your account at http://cimb-secure.xyz or call 0123456789"
    mock_search_memory.return_value = []
    mock_llm.invoke.side_effect = Exception("LLM fallback")

    state: GraphState = {
        "trigger_type": "PHISHING",
        "trigger_payload": {
            "content_type": "IMAGE",
            "content": "fake_base64_image_string",
        },
    }

    res = phishing_worker_node(state)

    assert "phishing_finding" in res
    assert "extracted_entities" in res

    entities = res["extracted_entities"]
    assert "0123456789" in entities["phone_numbers"]
    assert "http://cimb-secure.xyz" in entities["urls"]

    finding = res["phishing_finding"]
    assert finding["worker"] == "phishing"
    assert finding["score"] >= 40


# ── 5. Phone Worker Tests ──

@patch("src.agents.workers.phone.check_blacklist")
def test_phone_worker_listen_mode_highlighter(mock_check_blacklist: MagicMock):
    """Verify phone_worker_node Listen Mode highlights scam phrases."""
    mock_check_blacklist.return_value = []

    state: GraphState = {
        "trigger_type": "CALL",
        "call_mode": "LISTEN",
        "trigger_payload": {
            "caller_number": "0169998888",
            "transcript": [
                {
                    "speaker": "CALLER",
                    "text": "Your account is flagged for money laundering. You must transfer money to a safe account immediately.",
                    "utterance_id": "utt-1",
                }
            ],
        },
    }

    res = phone_worker_node(state)
    finding = res["phone_finding"]
    session = res["phone_session"]

    assert finding["worker"] == "phone"
    assert finding["score"] >= 70
    assert len(session["highlight_events"]) > 0
    assert session["highlight_events"][0]["utterance_risk_score"] == 90


@patch("src.agents.workers.phone.check_blacklist")
def test_phone_worker_autotalk_mode_dialogue(mock_check_blacklist: MagicMock):
    """Verify phone_worker_node Auto-Talk Mode state machine processing."""
    mock_check_blacklist.return_value = [{"case_id": "case-blacklisted"}]

    state: GraphState = {
        "trigger_type": "CALL",
        "call_mode": "AUTO_TALK",
        "trigger_payload": {
            "caller_number": "1300888888",
            "transcript": [
                {
                    "speaker": "CALLER",
                    "text": "What is your employee ID? I am not going to hang up.",
                }
            ],
        },
    }

    res = phone_worker_node(state)
    finding = res["phone_finding"]
    session = res["phone_session"]

    assert finding["worker"] == "phone"
    assert finding["score"] >= 80
    assert session["call_mode"] == "AUTO_TALK"
    assert any("blacklisted" in ev for ev in finding["evidence"])
