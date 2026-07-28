"""Unit tests for Dynamic Skills & Prompt Management Layer (Module 3)."""

import pytest

from src.agents.prompts import (
    build_financial_prompt,
    build_phishing_analysis_prompt,
    build_phone_highlighter_prompt,
    build_research_prompt,
    build_telemetry_prompt,
    build_xai_prompt,
    get_anchor_questions,
    get_phone_dialogue_guide,
    load_skill_file,
)


def test_load_skill_file_success() -> None:
    """Test loading existing markdown skill file and asserting key phrases."""
    content = load_skill_file("phone_dialogue_guide.md")
    assert "Safety & Data Privacy Guardrails" in content
    assert "Zero User Information Access" in content
    assert "Auto-Talk" in content


def test_load_skill_file_not_found() -> None:
    """Test loading non-existent skill file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_skill_file("nonexistent_skill_file.md")


def test_get_phone_dialogue_guide() -> None:
    """Test get_phone_dialogue_guide returns phone dialogue guide markdown content."""
    guide = get_phone_dialogue_guide()
    assert "# Phone Agent Dialogue Guide & Safety Rules" in guide
    assert "Zero User Information Access" in guide


def test_get_anchor_questions_parsing() -> None:
    """Test parsing anchor questions and validating structure and content."""
    questions = get_anchor_questions()
    assert len(questions) == 4
    assert questions[0]["id"] == "AQ-1"
    assert "employee ID" in questions[0]["question_example"]
    assert questions[1]["id"] == "AQ-2"
    assert questions[2]["id"] == "AQ-3"
    assert questions[3]["id"] == "AQ-4"

    for q in questions:
        assert "id" in q
        assert "intent" in q
        assert "question_example" in q
        assert "scam_signal_if" in q


def test_build_telemetry_prompt() -> None:
    """Test formatting telemetry worker prompt with sample inputs."""
    user_id = "usr-123"
    session_id = "sess-456"
    device_id = "dev-789"
    events = [{"event_type": "KEYPRESS", "event_value": "flight_time=450ms"}]
    metrics = {"avg_flight_time": 450}
    biometrics = {"backspace_count": 3}
    fingerprint = {"ip": "192.168.1.1"}

    prompt = build_telemetry_prompt(
        user_id=user_id,
        session_id=session_id,
        device_id=device_id,
        events=events,
        metrics=metrics,
        biometrics=biometrics,
        fingerprint=fingerprint,
    )

    assert "User ID: usr-123" in prompt
    assert "Session ID: sess-456" in prompt
    assert "Device ID: dev-789" in prompt
    assert "KEYPRESS" in prompt
    assert "flight_time=450ms" in prompt
    assert "backspace_count" in prompt
    assert "192.168.1.1" in prompt


def test_build_financial_prompt() -> None:
    """Test formatting financial worker prompt with pending tx and baseline."""
    pending_tx = {
        "transaction_id": "tx-001",
        "amount": 9500.0,
        "recipient_account": "7653123456",
    }
    history = {"avg_amount": 200.0, "known_recipients": ["111222333"]}
    case_context = {"bank_accounts": ["7653123456"]}

    prompt = build_financial_prompt(
        pending_tx=pending_tx, history=history, case_context=case_context
    )

    assert "tx-001" in prompt
    assert "9500.0" in prompt
    assert "7653123456" in prompt
    assert "avg_amount" in prompt
    assert "Case Coercion Match" in prompt


def test_build_research_prompt() -> None:
    """Test formatting research worker prompt with query entities and search hits."""
    entities = ["0161234567", "7653123456"]
    internal_hits = [{"case_id": "case-999", "similarity": 0.88}]
    tavily_hits = [{"title": "Scam Report", "url": "https://lowyat.net/topic/1"}]

    prompt = build_research_prompt(
        entities=entities, internal_hits=internal_hits, tavily_hits=tavily_hits
    )

    assert "0161234567" in prompt
    assert "case-999" in prompt
    assert "lowyat.net" in prompt


def test_build_phishing_analysis_prompt() -> None:
    """Test formatting phishing worker analysis prompt."""
    source = "SMS"
    content = "URGENT: Maybank account blocked. Verify at http://cimb-secure.xyz"

    prompt = build_phishing_analysis_prompt(source=source, content=content)

    assert "Material Source: SMS" in prompt
    assert "http://cimb-secure.xyz" in prompt
    assert "Bank/Government Impersonation" in prompt


def test_build_phone_highlighter_prompt() -> None:
    """Test formatting phone worker live utterance highlighter prompt."""
    text = "This is Inspector Ahmad from PDRM. Transfer money immediately."

    prompt = build_phone_highlighter_prompt(text=text)

    assert "Transcribed Utterance:" in prompt
    assert "Inspector Ahmad from PDRM" in prompt
    assert "false_accusation" in prompt


def test_build_xai_prompt() -> None:
    """Test formatting XAI explainability prompt from GraphState."""
    state = {
        "risk_tier": "HIGH",
        "risk_score": 92,
        "financial_finding": {
            "worker": "financial",
            "score": 95,
            "confidence": 0.9,
            "evidence": ["Recipient account matches active scam call"],
        },
        "telemetry_finding": None,
        "research_finding": None,
        "phone_finding": None,
        "phishing_finding": None,
    }

    prompt = build_xai_prompt(state)

    assert "HIGH risk (score: 92/100)" in prompt
    assert "Recipient account matches active scam call" in prompt
    assert "verdict_summary" in prompt
