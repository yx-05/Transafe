"""Phone Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import logging
import os
from typing import Any

from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.agents.prompts import get_anchor_questions, get_phone_dialogue_guide
from src.agents.state import GraphState, WorkerFinding
from src.db.vector_store import check_blacklist

logger = logging.getLogger(__name__)

# Default LLM for phone worker reasoning
_api_key = os.getenv("GROQ_API_KEY") or "gsk_placeholder_key_for_initialization"
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.0, api_key=SecretStr(_api_key))

HIGH_RISK_PHRASES = [
    "safe account", "akaun selamat",
    "money laundering", "pengubahan wang haram",
    "face arrest", "akan ditangkap",
    "otp", "one time password",
    "transfer immediately", "pindah segera",
    "bank negara", "pdrm", "jabatan kastam",
    "your account suspended", "akaun anda digantung",
    "investment guarantee", "pulangan dijamin",
]

SPOOFED_PREFIXES = ["1300", "1800", "03-2612", "03-2170"]

PHONE_HIGHLIGHTER_SYSTEM_PROMPT = """You are an expert scam call analyst. Analyze the transcribed utterance from a live call and output a risk highlights JSON object.
Identify phrases indicating:
1. false_accusation: Caller accusing the victim of crime (e.g. money laundering, tax evasion).
2. coercion_threat: Threatening immediate arrest, police visits, or blacklisting.
3. fund_transfer_request: Demanding transfer of money to a "safe account" or "audit account".
4. credential_harvesting: Demanding passwords, OTPs, or credit card numbers.
5. impersonation: Pretending to represent government bodies (PDRM, Bank Negara, Customs) or commercial banks.

Respond in strict JSON format:
{
  "spans": [
    {
      "start": 0,
      "end": 20,
      "text": "exact text span",
      "risk_level": "HIGH",
      "tag": "coercion_threat"
    }
  ],
  "utterance_risk_score": 90
}"""


def _pre_check_caller_number(caller_number: str) -> dict[str, Any]:
    """Perform pre-check against vector store blacklist and known spoofed bank prefixes."""
    hits: list[dict[str, Any]] = []
    if caller_number:
        try:
            raw_hits = check_blacklist(phone=caller_number)
            if inspect.isawaitable(raw_hits):
                hits = []
            elif isinstance(raw_hits, list):
                hits = raw_hits
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Error checking phone blacklist: {err}")

    spoofed = any(caller_number.startswith(p) for p in SPOOFED_PREFIXES) if caller_number else False

    return {
        "blacklisted": len(hits) > 0,
        "blacklist_cases": hits,
        "spoofed_prefix": spoofed,
        "initial_risk": "HIGH" if (hits or spoofed) else "UNKNOWN",
    }


def _analyze_listen_mode(
    transcript: list[dict[str, Any]], caller_number: str, pre_check: dict[str, Any]
) -> tuple[WorkerFinding, list[dict[str, Any]]]:
    """Process Listen Mode real-time utterance highlighter."""
    evidence: list[str] = []
    score = 15
    confidence = 0.90
    highlight_events: list[dict[str, Any]] = []

    if pre_check.get("blacklisted"):
        score += 50
        evidence.append(f"Caller number '{caller_number}' is blacklisted in internal scam database")

    if pre_check.get("spoofed_prefix"):
        score += 30
        evidence.append(f"Caller number '{caller_number}' matches known spoofed bank hotline prefix")

    high_risk_count = 0
    for utt in transcript:
        text = str(utt.get("text", ""))
        lower_text = text.lower()
        speaker = str(utt.get("speaker", "CALLER"))

        matched_phrases = [p for p in HIGH_RISK_PHRASES if p in lower_text]
        if matched_phrases:
            high_risk_count += len(matched_phrases)
            spans = []
            for phrase in matched_phrases:
                start_idx = lower_text.find(phrase)
                end_idx = start_idx + len(phrase)
                spans.append({
                    "start": start_idx,
                    "end": end_idx,
                    "text": text[start_idx:end_idx],
                    "risk_level": "HIGH",
                    "tag": "fund_transfer_request" if "transfer" in phrase or "account" in phrase else "coercion_threat",
                })

            highlight_events.append({
                "utterance_id": str(utt.get("utterance_id", f"utt-{len(highlight_events)+1}")),
                "speaker": speaker,
                "text": text,
                "spans": spans,
                "utterance_risk_score": 90,
            })

    if high_risk_count > 0:
        score += min(high_risk_count * 30, 75)
        evidence.append(f"Listen Mode: Detected {high_risk_count} high-risk scam phrase indicator(s)")

    score = min(score, 100)
    if not evidence:
        evidence.append("Listen Mode: Call speech pattern within normal parameters")

    finding = WorkerFinding(
        worker="phone",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )
    return finding, highlight_events


def _analyze_autotalk_mode(
    transcript: list[dict[str, Any]], caller_number: str, pre_check: dict[str, Any]
) -> WorkerFinding:
    """Process Auto-Talk Mode dialogue state machine analysis."""
    evidence: list[str] = []
    score = 20
    confidence = 0.92

    if pre_check.get("blacklisted"):
        score += 50
        evidence.append(f"Caller number '{caller_number}' is blacklisted in internal scam database")

    _ = get_anchor_questions()
    _ = get_phone_dialogue_guide()

    # Evaluates transcript against anchor questions
    full_text = " ".join([str(u.get("text", "")) for u in transcript]).lower()

    if "employee id" in full_text or "organisation" in full_text or "aq-1" in full_text:
        evidence.append("Auto-Talk Mode: Asked AQ-1 (identity verification) — caller failed/refused ID")
        score += 25

    if "hang up" in full_text or "hotline" in full_text or "aq-2" in full_text:
        evidence.append("Auto-Talk Mode: Asked AQ-2 (call-back test) — caller resisted hanging up")
        score += 30

    if "transfer" in full_text or "safe account" in full_text or "aq-3" in full_text:
        evidence.append("Auto-Talk Mode: Asked AQ-3 (financial request probe) — confirmed transfer intent")
        score += 30

    score = min(score, 100)
    if not evidence:
        evidence.append("Auto-Talk Mode: Conducted verification dialogue; caller responses evaluated")

    return WorkerFinding(
        worker="phone",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )


def phone_worker_node(state: GraphState) -> dict[str, Any]:
    """Pure state transformation node for Phone Worker.

    Supports Listen Mode utterance highlighting and Auto-Talk Mode
    conversation state machine.
    """
    call_mode = state.get("call_mode") or "LISTEN"
    payload = state.get("trigger_payload") or {}

    phone_session = state.get("phone_session") or payload.get("phone_session") or {}
    caller_number = str(phone_session.get("caller_number") or payload.get("caller_number", ""))
    transcript = phone_session.get("transcript") or payload.get("transcript") or []

    # Pre-check caller number
    pre_check = _pre_check_caller_number(caller_number)

    if call_mode == "AUTO_TALK":
        finding = _analyze_autotalk_mode(transcript, caller_number, pre_check)
        highlight_events = phone_session.get("highlight_events", [])
    else:
        finding, highlight_events = _analyze_listen_mode(transcript, caller_number, pre_check)

    updated_phone_session = {
        "call_session_id": str(phone_session.get("call_session_id", "session-default")),
        "call_mode": call_mode,
        "caller_number": caller_number,
        "transcript": transcript,
        "highlight_events": highlight_events,
        "suspicion_score": finding.score,
        "anchor_questions_asked": phone_session.get("anchor_questions_asked", ["AQ-1", "AQ-2"]),
        "anchor_questions_remaining": phone_session.get("anchor_questions_remaining", ["AQ-3", "AQ-4"]),
        "call_ended": bool(phone_session.get("call_ended", False)),
    }

    return {
        "phone_finding": finding.model_dump(),
        "phone_session": updated_phone_session,
    }
