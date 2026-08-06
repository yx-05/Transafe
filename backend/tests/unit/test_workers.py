"""Unit tests for TranSafe Module 4 Worker Agents."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.agents.state import GraphState, WorkerFinding
from src.agents.workers.financial import financial_worker_node
from src.agents.workers.phishing import analyze_call_transcript, phishing_worker_node
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
@patch("src.agents.workers.phishing.tavily_search")
def test_phishing_worker_returns_extracted_entities(
    mock_tavily: MagicMock, mock_llm: MagicMock, mock_ocr: MagicMock, mock_search_memory: MagicMock
):
    """Assert phishing_worker_node returns extracted entities in state updates."""
    mock_ocr.return_value = "URGENT: Verify your account at http://cimb-secure.xyz or call 0123456789"
    mock_search_memory.return_value = []
    mock_tavily.return_value = []
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


@patch("src.agents.workers.phishing.search_fraud_memory")
@patch("src.agents.workers.phishing.llm")
@patch("src.agents.workers.phishing.tavily_search")
def test_analyze_call_transcript_deep_analysis(
    mock_tavily: MagicMock, mock_llm: MagicMock, mock_search_memory: MagicMock
):
    """Verify analyze_call_transcript deep-analyzes a full call transcript."""
    mock_search_memory.return_value = []
    mock_tavily.return_value = []
    mock_llm.invoke.side_effect = Exception("LLM fallback")

    transcript = [
        {"speaker": "CALLER", "text": "Hello, this is Inspector Tan from PDRM.", "utterance_id": "utt-1"},
        {"speaker": "CALLER", "text": "You must transfer money to a safe account immediately or face arrest.", "utterance_id": "utt-2"},
    ]

    res = analyze_call_transcript(transcript)

    assert "phishing_finding" in res
    assert "extracted_entities" in res
    assert res["phishing_finding"]["worker"] == "phishing"


def test_analyze_call_transcript_empty_returns_benign():
    """Verify analyze_call_transcript returns a benign finding on empty input."""
    res = analyze_call_transcript([])
    assert res["phishing_finding"]["score"] == 0
    assert res["extracted_entities"] == {}
    assert res["research"]["queried"] is False


@patch("src.agents.workers.phishing.tavily_search")
@patch("src.agents.workers.phishing.search_fraud_memory")
@patch("src.agents.workers.phishing.llm")
def test_analyze_call_transcript_triggers_web_research(
    mock_llm: MagicMock, mock_search_memory: MagicMock, mock_tavily: MagicMock
):
    """Planner approves search → tavily returns a hit → final verdict uses web evidence."""
    stage3 = {"score": 55, "confidence": 0.6, "evidence": ["Base signal: unverified number"]}
    planner = {
        "search": True,
        "reasoning": "unverified phone number not in internal DB",
        "queries": ["0123456789 scam PDRM"],
        "confidence": 0.85,
    }
    final = {"score": 88, "confidence": 0.95, "evidence": ["External alert list confirms this number"]}
    mock_llm.invoke.side_effect = [
        SimpleNamespace(content=json.dumps(stage3)),
        SimpleNamespace(content=json.dumps(planner)),
        SimpleNamespace(content=json.dumps(final)),
    ]
    mock_search_memory.return_value = []
    mock_tavily.return_value = [
        {"title": "SemakMule - Fraud Number Check", "url": "https://semak.my/check/0123456789", "content": "reported scam number"}
    ]

    transcript = [
        {"speaker": "CALLER", "text": "This is Inspector Tan from the Commercial Crime Investigation Department."},
        {"speaker": "CALLER", "text": "Your bank account is compromised. Call 0123456789 immediately."},
    ]

    res = analyze_call_transcript(transcript)

    assert res["research"]["queried"] is True
    assert res["research"]["decision"] == "llm"
    assert "0123456789 scam PDRM" in res["research"]["queries"]
    assert len(res["research"]["web_hits"]) == 1
    assert res["research"]["web_hits"][0]["url"] == "https://semak.my/check/0123456789"
    assert res["phishing_finding"]["score"] == 88
    assert any("External alert list" in ev for ev in res["phishing_finding"]["evidence"])


@patch("src.agents.workers.phishing.tavily_search")
@patch("src.agents.workers.phishing.search_fraud_memory")
@patch("src.agents.workers.phishing.llm")
def test_analyze_call_transcript_skips_research_when_benign(
    mock_llm: MagicMock, mock_search_memory: MagicMock, mock_tavily: MagicMock
):
    """Benign transcript (no entities, low score) never triggers web research."""
    stage3 = {"score": 10, "confidence": 0.8, "evidence": ["No phishing indicators"]}
    mock_llm.invoke.return_value = SimpleNamespace(content=json.dumps(stage3))
    mock_search_memory.return_value = []

    transcript = [
        {"speaker": "CALLER", "text": "Hello, how are you today?"},
        {"speaker": "CUSTOMER", "text": "I am good, thank you."},
    ]

    res = analyze_call_transcript(transcript)

    assert res["research"]["queried"] is False
    assert res["research"]["decision"] == "skipped"
    mock_tavily.assert_not_called()
    assert mock_llm.invoke.call_count == 1  # only the Stage 3 verdict LLM ran


@patch("src.agents.workers.phishing.tavily_search")
@patch("src.agents.workers.phishing.search_fraud_memory")
@patch("src.agents.workers.phishing.llm")
def test_analyze_call_transcript_heuristic_fallback_on_planner_failure(
    mock_llm: MagicMock, mock_search_memory: MagicMock, mock_tavily: MagicMock
):
    """Planner LLM unavailable → heuristic searches entities but stays graceful."""
    mock_llm.invoke.side_effect = Exception("LLM down")
    mock_search_memory.return_value = []
    mock_tavily.return_value = []

    transcript = [
        {"speaker": "CALLER", "text": "Call 0123456789 to resolve your case."},
    ]

    res = analyze_call_transcript(transcript)

    assert res["research"]["queried"] is True
    assert res["research"]["decision"] == "heuristic"
    assert "0123456789" in res["research"]["queries"]
    assert res["research"]["web_hits"] == []
    assert res["phishing_finding"]["worker"] == "phishing"


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
@patch("src.agents.workers.phone.llm.invoke", new_callable=MagicMock)
def test_phone_worker_llm_catches_novel_phrasing(mock_llm: MagicMock, mock_check_blacklist: MagicMock):
    """LLM pass must fire even with zero rule matches and flag novel scam phrasing."""
    mock_check_blacklist.return_value = []
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "spans": [
            {
                "text": "remit the funds into the designated holding account",
                "risk_level": "HIGH",
                "tag": "fund_transfer_request",
                "utterance_risk_score": 90,
            }
        ],
        "utterance_risk_score": 90,
    })
    mock_llm.return_value = mock_response

    state: GraphState = {
        "trigger_type": "CALL",
        "call_mode": "LISTEN",
        "trigger_payload": {
            "caller_number": "0169998888",
            "transcript": [
                {
                    "speaker": "CALLER",
                    "text": "Please remit the funds into the designated holding account before noon.",
                    "utterance_id": "utt-llm-1",
                }
            ],
        },
    }

    res = phone_worker_node(state)
    session = res["phone_session"]
    finding = res["phone_finding"]

    # No HIGH_RISK_PHRASE matched, yet the LLM span is surfaced as a highlight
    assert any("remit the funds" in ev["phrase"] for ev in session["highlight_events"])
    # Score lifted by the LLM (base 10 -> 90), proving the pass ran without rules
    assert finding["score"] == 90
    assert any("LLM highlighter flagged" in ev for ev in finding["evidence"])


@patch("src.agents.workers.phone.check_blacklist")
@patch("src.agents.workers.phone.llm.invoke", new_callable=MagicMock)
def test_phone_worker_skips_llm_for_filler(mock_llm: MagicMock, mock_check_blacklist: MagicMock):
    """Filler/backchannel utterances must NOT trigger a Groq LLM call (cost guard)."""
    mock_check_blacklist.return_value = []

    state: GraphState = {
        "trigger_type": "CALL",
        "call_mode": "LISTEN",
        "trigger_payload": {
            "caller_number": "0169998888",
            "transcript": [
                {"speaker": "CUSTOMER", "text": "Okay, thanks.", "utterance_id": "utt-fill-1"},
            ],
        },
    }

    res = phone_worker_node(state)
    mock_llm.invoke.assert_not_called()
    # No rule match and no LLM pass -> benign baseline, no highlights
    assert res["phone_finding"]["score"] == 10
    assert res["phone_session"]["highlight_events"] == []


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


# ── 5b. AUTO_TALK Responder Tests ──

@patch("src.agents.workers.phone.llm.invoke", new_callable=MagicMock)
def test_autotalk_responder_parses_llm_json(mock_llm: MagicMock):
    """AUTO_TALK responder must parse the LLM JSON reply into structured fields."""
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "reply": "May I know the full name of your department and your employee ID, please?",
        "next_aq": "AQ-1",
        "signal_detected": False,
        "suspicion_delta": 5,
        "action": "continue",
        "reasoning": "Opening the identity-verification question.",
    })
    mock_llm.return_value = mock_response

    from src.agents.workers.phone import _run_autotalk_responder

    reply = _run_autotalk_responder(
        transcript=[{"speaker": "SCAMMER", "text": "Hello ma'am, this is Bank Negara Malaysia."}],
        caller_number="+60161234567",
        pre_check={"blacklisted": False},
        suspicion=20,
        aq_progress={"asked": []},
    )

    assert reply["reply"].startswith("May I know")
    assert reply["next_aq"] == "AQ-1"
    assert reply["signal_detected"] is False
    assert reply["suspicion_delta"] == 5
    assert reply["action"] == "continue"


@patch("src.agents.workers.phone.llm.invoke", new_callable=MagicMock)
def test_autotalk_responder_fallback_uses_anchor_skill_schedule(mock_llm: MagicMock):
    """When the LLM fails, the responder must fall back to the anchor-question
    skill schedule (first un-asked AQ template becomes the spoken reply)."""
    mock_llm.side_effect = RuntimeError("Groq down")

    from src.agents.workers.phone import _run_autotalk_responder

    reply = _run_autotalk_responder(
        transcript=[{"speaker": "SCAMMER", "text": "Hello."}],
        caller_number="+60161234567",
        pre_check={"blacklisted": False},
        suspicion=10,
        aq_progress={"asked": []},
    )

    assert reply["next_aq"] == "AQ-1"
    assert "employee ID" in reply["reply"]  # AQ-1 template from anchor_questions.md
    assert reply["action"] == "continue"


@patch("src.agents.workers.phone.llm.invoke", new_callable=MagicMock)
def test_autotalk_responder_hangup_on_confirmed_signal(mock_llm: MagicMock):
    """A confirmed scam signal must produce a hangup action + short goodbye."""
    mock_response = MagicMock()
    mock_response.content = json.dumps({
        "reply": "I'm ending this call, bye.",
        "next_aq": "NONE",
        "signal_detected": True,
        "suspicion_delta": 40,
        "action": "hangup",
        "reasoning": "Caller confirmed transferring money to a safe account.",
    })
    mock_llm.return_value = mock_response

    from src.agents.workers.phone import _run_autotalk_responder

    reply = _run_autotalk_responder(
        transcript=[{"speaker": "SCAMMER", "text": "Yes, just transfer everything to our safe account now."}],
        caller_number="+60161234567",
        pre_check={"blacklisted": True},
        suspicion=60,
        aq_progress={"asked": ["AQ-1", "AQ-2", "AQ-3"]},
    )

    assert reply["action"] == "hangup"
    assert reply["signal_detected"] is True
    assert reply["suspicion_delta"] == 40
    assert "ending this call" in reply["reply"]


def test_autotalk_mode_uses_anchor_skill_evidence():
    """Auto-Talk Mode analysis must reference the anchor-question skill schedule
    (evidence lines name AQ ids + goals from anchor_questions.md)."""
    from src.agents.workers.phone import _analyze_autotalk_mode

    finding = _analyze_autotalk_mode(
        transcript=[
            {"speaker": "CALLER", "text": "I am the security department. What is your employee ID?"},
            {"speaker": "CALLER", "text": "Do not hang up, and transfer to the safe account now."},
        ],
        caller_number="+60161234567",
        pre_check={"blacklisted": False},
    )

    assert finding.worker == "phone"
    evidence_text = " ".join(finding.evidence)
    assert "AQ-1" in evidence_text
    assert "AQ-3" in evidence_text
    assert finding.score >= 60
