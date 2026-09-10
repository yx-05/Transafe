"""Phone Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.agents.llm import DEEPSEEK_BASE_URL, extract_json_object, invoke_groq_with_key_rotation
from src.agents.prompts import (
    AUTOTALK_SYSTEM_PROMPT,
    build_autotalk_response_prompt,
    build_phone_highlighter_prompt,
    get_anchor_questions,
    get_phone_dialogue_guide,
)
from src.agents.state import GraphState, WorkerFinding
from src.agents.workers.artifact_feed import load_learned_phrases
from src.db.vector_store import check_blacklist, search_fraud_memory

logger = logging.getLogger(__name__)

# Agent's spoken voice for AUTO_TALK replies (edge-tts, MP3 delivered via REST)
AUTOTALK_VOICE = "ms-MY-YasminNeural"


def get_phone_llm(model_name: str = "deepseek-chat") -> ChatOpenAI:
    """Get ChatOpenAI LLM instance (DeepSeek) reading DEEPSEEK_API_KEY dynamically at runtime."""
    raw_key = os.getenv("DEEPSEEK_API_KEY") or "sk-placeholder_key_for_initialization"
    return ChatOpenAI(
        model=model_name,
        temperature=0.0,
        api_key=SecretStr(raw_key),
        base_url=DEEPSEEK_BASE_URL,
    )


class DynamicPhoneLLM:
    """Dynamic LLM proxy using DeepSeek with multi-key rotation and fallback."""

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        return invoke_groq_with_key_rotation(messages)


llm = DynamicPhoneLLM()


HIGH_RISK_PHRASES = [
    # Generic English coercion / fund-transfer indicators
    "transfer", "transfer money", "transfer the money", "transfer to me",
    "send me money", "send money", "to my account", "into my account",
    "pay me", "wire transfer", "bank transfer", "money now", "give me money",
    "give me the money", "all your money", "your savings", "withdraw",
    "bitcoin", "crypto", "gift card", "western union",
    # Malaysian / legacy indicators
    "safe account", "akaun selamat",
    "money laundering", "pengubahan wang haram",
    "face arrest", "akan ditangkap",
    "otp", "one time password", 
    "bank negara malaysia", "pdrm", "lhdn",
    "transfer immediately", "pindah segera",
    "jabatan kastam", "your account suspended", "akaun anda digantung",
    "investment guarantee", "pulangan dijamin",
]


FILLER_TOKENS = {
    "okay", "ok", "thanks", "thank", "thank you", "yeah", "yep", "yes", "no",
    "uh", "uhh", "um", "hmm", "ah", "sure", "alright", "right", "got it",
    "understood", "mhm", "huh", "bye", "hello", "hi", "please", "thankyou",
}


def _is_filler_utterance(raw_text: str) -> bool:
    """True for short/backchannel utterances that don't warrant an LLM call."""
    text = raw_text.strip()
    if not text:
        return True
    if len(text) <= 20:
        return True
    words = [w.strip(".,!?;:'\"()") for w in text.split()]
    meaningful = [w for w in words if w.lower() not in FILLER_TOKENS]
    return len(meaningful) == 0


def _scan_high_risk_phrases(
    transcript: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Rules-only scan for coercion/danger phrases in a transcript.

    Shared by Listen Mode and Auto-Talk Mode so that scammer utterances are
    always surfaced with highlight spans in the UI, regardless of the active
    call mode. Returns (highlight_events, score_increment, evidence).

    Scans the built-in ``HIGH_RISK_PHRASES`` **plus** phrases learned from
    published campaign packs. The learned set is what makes an approved
    campaign change detection rather than merely produce a receipt; evidence
    for a learned phrase cites the campaign that taught it, so an analyst can
    tell an inherited rule from a shipped one.
    """
    highlight_events: list[dict[str, Any]] = []
    score_increment = 0
    evidence: list[str] = []

    learned = load_learned_phrases()
    scan_phrases = list(HIGH_RISK_PHRASES) + [p for p in learned if p not in HIGH_RISK_PHRASES]

    for utt in transcript:
        raw_text = str(utt.get("text") or utt.get("utterance", ""))
        speaker = str(utt.get("speaker", "CALLER"))
        lower_text = raw_text.lower()
        matched_phrases = [p for p in scan_phrases if p in lower_text]
        if not matched_phrases:
            continue
        score_increment += len(matched_phrases) * 30
        for phrase in matched_phrases:
            source = learned.get(phrase)
            origin = f" (learned from campaign {source})" if source else ""
            evidence.append(f"Spoken danger phrase detected: '{phrase}' by {speaker}{origin}")
            highlight_events.append({
                "utterance_id": str(utt.get("utterance_id", f"utt-{len(highlight_events)+1}")),
                "speaker": speaker,
                "phrase": phrase,
                "risk_level": "HIGH",
                "reason": f"Coercion/scam indicator phrase '{phrase}' spoken by {speaker}",
                "tag": "fund_transfer_request" if "transfer" in phrase or "account" in phrase else "coercion_threat",
                "utterance_risk_score": 90,
            })

    return highlight_events, score_increment, evidence


def _run_listen_mode(
    transcript: list[dict[str, Any]],
    caller_number: str,
    pre_check: dict[str, Any],
    llm_enrich: bool = True,
) -> tuple[WorkerFinding, list[dict[str, Any]]]:
    """Process Listen Mode real-time utterance highlighting."""
    highlight_events: list[dict[str, Any]] = []
    score = 10
    confidence = 0.88
    evidence: list[str] = []

    if pre_check.get("blacklisted"):
        score += 50
        evidence.append(f"Caller number '{caller_number}' is blacklisted in internal scam database")

    # Scan transcript for high risk phrases (shared rules scanner)
    rule_events, rule_score_inc, rule_evidence = _scan_high_risk_phrases(transcript)
    highlight_events.extend(rule_events)
    score += rule_score_inc
    evidence.extend(rule_evidence)

    # LLM enrichment pass: span-level risk scoring on every utterance
    # (rules already produced instant highlights; this adds context spans)
    seen_rules = set(p.lower() for ev in rule_events for p in [ev.get("phrase", "")])
    for utt in transcript:
        raw_text = str(utt.get("text") or utt.get("utterance", ""))
        speaker = str(utt.get("speaker", "CALLER"))
        lower_text = raw_text.lower()

        if llm_enrich and not _is_filler_utterance(raw_text):
            try:
                matched_phrases = [p for p in HIGH_RISK_PHRASES if p in lower_text]
                prompt_text = build_phone_highlighter_prompt(raw_text)
                messages = [
                    SystemMessage(content="You are a scam call analyst."),
                    HumanMessage(content=prompt_text),
                ]
                _llm_resp = llm.invoke(messages)
                _llm_text = _llm_resp.content if hasattr(_llm_resp, "content") else _llm_resp
                parsed = extract_json_object(_llm_text) if isinstance(_llm_text, str) else None
                if isinstance(parsed, dict):
                    for sp in parsed.get("spans") or []:
                        if not isinstance(sp, dict):
                            continue
                        phrase = str(sp.get("text") or "").strip()
                        if not phrase or len(phrase) < 2:
                            continue
                        # Skip spans already covered by rule hits (exact or narrower)
                        ph_lower = phrase.lower()
                        if any(
                            ph_lower == p.lower() or ph_lower in p.lower()
                            for p in matched_phrases
                        ) or ph_lower in seen_rules:
                            continue
                        highlight_events.append({
                            "utterance_id": str(utt.get("utterance_id", f"utt-{len(highlight_events)+1}")),
                            "speaker": speaker,
                            "phrase": phrase,
                            "risk_level": str(sp.get("risk_level", "HIGH")).upper(),
                            "reason": f"LLM span analysis flagged '{phrase}' spoken by {speaker}",
                            "tag": str(sp.get("tag", "coercion_threat")),
                            "utterance_risk_score": int(sp.get("utterance_risk_score", 90) or 90),
                        })
                        evidence.append(f"LLM highlighter flagged '{phrase}' spoken by {speaker}")
                    llm_utt_score = parsed.get("utterance_risk_score")
                    if isinstance(llm_utt_score, (int, float)):
                        score = max(score, int(llm_utt_score))
            except Exception as err:  # noqa: BLE001
                logger.debug(f"Phone LLM highlighter skipped: {err}")

    score = min(score, 100)
    if not evidence:
        evidence.append("Listen Mode: Call speech transcribed; no immediate high-risk coercion phrases detected")

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
    """Process Auto-Talk Mode dialogue state machine analysis.

    Evaluates the transcript against the anchor-question skill schedule:
    each anchor question carries a weight (AQ-1 identity, AQ-2 call-back
    test, AQ-3 transfer probe, AQ-4 urgent-action challenge). Confirmed
    scam indicators per AQ raise suspicion; resistance to the AQ-2 hang-up
    test and AQ-4 urgency pressure are penalized hardest.
    """
    evidence: list[str] = []
    score = 20
    confidence = 0.92

    if pre_check.get("blacklisted"):
        score += 50
        evidence.append(f"Caller number '{caller_number}' is blacklisted in internal scam database")

    # Anchor-question skill schedule: how much each confirmed indicator raises suspicion
    aq_weights = {"AQ-1": 15, "AQ-2": 20, "AQ-3": 30, "AQ-4": 30}
    aq_tokens: dict[str, tuple[list[str], str]] = {
        "AQ-1": (
            ["employee id", "organisation", "department", "registration number", "aq-1"],
            "identity verification — caller failed/refused to provide verifiable ID",
        ),
        "AQ-2": (
            ["hang up", "hotline", "extension number", "aq-2", "must not disconnect", "do not hang up"],
            "call-back test — caller resisted hanging up / claimed line must stay open",
        ),
        "AQ-3": (
            ["transfer", "safe account", "akaun selamat", "secure account", "card password", "otp", "aq-3"],
            "financial transfer probe — caller confirmed/deflected fund movement",
        ),
        "AQ-4": (
            ["immediate", "arrest", "akan ditangkap", "account freeze", "penalty", "family", "aq-4", "right now", "asap"],
            "urgent-action challenge — caller pressured for immediate execution",
        ),
    }

    full_text = " ".join([str(u.get("text", "")) for u in transcript]).lower()

    # Resistance phrases (typically spoken AFTER the agent asks the hang-up test)
    resistance_tokens = [
        "do not hang up", "don't hang up", "must not disconnect", "line is secure",
        "you will be arrested", "immediate arrest", "akan ditangkap",
    ]

    asked_any = False
    for aq_id, (tokens, goal) in aq_tokens.items():
        if any(tok in full_text for tok in tokens):
            asked_any = True
            if any(r in full_text for r in resistance_tokens):
                evidence.append(
                    f"Auto-Talk Mode: {aq_id} ({goal}) + caller resisted call termination — "
                    f"coercive pressure detected (+{aq_weights[aq_id] + 20})"
                )
                score += aq_weights[aq_id] + 20
            else:
                evidence.append(
                    f"Auto-Talk Mode: {aq_id} ({goal}) — caller response evaluated (+{aq_weights[aq_id]})"
                )
                score += aq_weights[aq_id]

    if not asked_any:
        evidence.append("Auto-Talk Mode: Conducted verification dialogue; no anchor-question signal matched yet")

    score = min(score, 100)
    return WorkerFinding(
        worker="phone",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )


def _fallback_autotalk_reply(
    transcript: list[dict[str, Any]],
    suspicion: int,
    anchor_questions: list[dict[str, Any]],
    aq_progress: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic fallback when the LLM responder fails.

    Picks the first anchor question from the skill schedule that has not yet
    been asked; once the full schedule is exhausted (or suspicion is HIGH)
    it asks a stall line from the dialogue guide instead.
    """
    asked = set(aq_progress.get("asked") or [])
    for aq in anchor_questions:
        aq_id = str(aq.get("id", ""))
        if aq_id.startswith("AQ-") and aq_id not in asked:
            template = str(aq.get("question_template") or aq.get("question_example") or "")
            if not template:
                continue
            return {
                "reply": template,
                "next_aq": aq_id,
                "signal_detected": False,
                "suspicion_delta": 0,
                "action": "continue",
                "reasoning": f"Fallback: advancing to {aq_id} from the anchor-question schedule",
            }

    # Full schedule asked → stall, or hang up if suspicion is already confirmed HIGH
    if suspicion >= 70:
        return {
            "reply": "I'm ending this call, bye.",
            "next_aq": "NONE",
            "signal_detected": True,
            "suspicion_delta": 0,
            "action": "hangup",
            "reasoning": "Fallback: suspicion already HIGH and schedule exhausted — hang up",
        }
    return {
        "reply": "Okay, I understand. Please give me a moment — I need to note this down carefully.",
        "next_aq": "NONE",
        "signal_detected": False,
        "suspicion_delta": 0,
        "action": "continue",
        "reasoning": "Fallback: stalling per dialogue guide while schedule is exhausted",
    }


def _run_autotalk_responder(
    transcript: list[dict[str, Any]],
    caller_number: str,
    pre_check: dict[str, Any],
    suspicion: int,
    aq_progress: dict[str, Any],
) -> dict[str, Any]:
    """Generate the AUTO_TALK agent's next reply, grounded in the skills.

    Consumes the anchor-question schedule and phone dialogue guide skill
    files (via prompts.build_autotalk_response_prompt), runs the LLM, and
    parses the strict JSON response. Falls back to the deterministic
    AQ-schedule walk when the LLM is unavailable or returns garbage.

    Returns:
        Dict with keys: reply, next_aq, signal_detected, suspicion_delta,
        action ("continue" | "hangup"), reasoning.
    """
    try:
        anchor_questions = get_anchor_questions()
        dialogue_guide = get_phone_dialogue_guide()
    except Exception as err:  # noqa: BLE001
        logger.warning(f"AUTO_TALK skills unavailable, using fallback reply: {err}")
        anchor_questions = []
        dialogue_guide = ""

    prompt_text = build_autotalk_response_prompt(
        transcript, anchor_questions, dialogue_guide, suspicion, aq_progress
    )
    messages = [
        SystemMessage(content=AUTOTALK_SYSTEM_PROMPT),
        HumanMessage(content=prompt_text),
    ]

    try:
        resp = llm.invoke(messages)
        raw_text = resp.content if hasattr(resp, "content") else resp
        parsed = extract_json_object(str(raw_text)) if isinstance(raw_text, str) else None
        if isinstance(parsed, dict) and str(parsed.get("reply", "")).strip():
            reply = str(parsed.get("reply", "")).strip()
            next_aq = str(parsed.get("next_aq") or "NONE")
            action = str(parsed.get("action") or "continue")
            if action not in ("continue", "hangup"):
                action = "continue"
            return {
                "reply": reply,
                "next_aq": next_aq,
                "signal_detected": bool(parsed.get("signal_detected") or False),
                "suspicion_delta": max(0, min(50, int(parsed.get("suspicion_delta") or 0))),
                "action": action,
                "reasoning": str(parsed.get("reasoning") or "LLM judgement"),
            }
        logger.warning(f"AUTO_TALK LLM returned unparsable reply: {raw_text!r}")
    except Exception as err:  # noqa: BLE001
        logger.warning(f"AUTO_TALK LLM invoke failed: {err}")

    return _fallback_autotalk_reply(transcript, suspicion, anchor_questions, aq_progress)


def phone_worker_node(
    state: GraphState,
    pre_check: dict[str, Any] | None = None,
    llm_enrich: bool = True,
) -> dict[str, Any]:
    """Pure state transformation node for Phone Worker.

    Supports Listen Mode utterance highlighting and Auto-Talk Mode
    verification dialogue state machine evaluation.

    Args:
        state: The LangGraph shared state.
        pre_check: Optional pre-computed call pre-check (blacklist + spoofed
            prefix). When provided, skips the internal blacklist DB query.
    """
    payload = state.get("trigger_payload") or {}
    call_payload = payload.get("call") or payload

    caller_number = str(call_payload.get("caller_number", ""))
    call_mode = str(state.get("call_mode") or call_payload.get("call_mode", "LISTEN")).upper()
    transcript: list[dict[str, Any]] = call_payload.get("transcript") or []

    # Use provided pre-check when available, else query blacklist DB
    if pre_check is not None:
        pre_check = dict(pre_check)
    else:
        pre_check = {"blacklisted": False}
        if caller_number:
            try:
                hits = check_blacklist(phone=caller_number)
                if inspect.isawaitable(hits):
                    hits = []
                if hits:
                    pre_check["blacklisted"] = True
                    pre_check["warning"] = f"Caller number {caller_number} reported in fraud database"
                    pre_check["blacklist_cases"] = len(hits)
            except Exception as err:  # noqa: BLE001
                logger.warning(f"Failed to query phone blacklist: {err}")

    if call_mode == "AUTO_TALK":
        finding = _analyze_autotalk_mode(transcript, caller_number, pre_check)
        
        # Surface both rules-based AND LLM-based coercion phrase highlights 
        # for the scammer's utterances even in Auto-Talk Mode, so the UI can mark them.
        _, highlights = _run_listen_mode(transcript, caller_number, pre_check, llm_enrich=llm_enrich)
        
        # Merge the rules-based score increment into the AutoTalk finding
        _, rule_score_inc, rule_evidence = _scan_high_risk_phrases(transcript)
        if rule_score_inc:
            boosted = finding.score + rule_score_inc
            finding = WorkerFinding(
                worker=finding.worker,
                score=min(boosted, 100),
                confidence=finding.confidence,
                evidence=list(finding.evidence) + rule_evidence,
            )
            
        return {
            "phone_finding": finding.model_dump(),
            "phone_session": {
                "caller_number": caller_number,
                "call_mode": call_mode,
                "pre_check": pre_check,
                "highlights": highlights,
                "highlight_events": highlights,
            },
        }

    finding, highlights = _run_listen_mode(transcript, caller_number, pre_check, llm_enrich=llm_enrich)
    return {
        "phone_finding": finding.model_dump(),
        "phone_session": {
            "caller_number": caller_number,
            "call_mode": call_mode,
            "pre_check": pre_check,
            "highlights": highlights,
            "highlight_events": highlights,
        },
    }
