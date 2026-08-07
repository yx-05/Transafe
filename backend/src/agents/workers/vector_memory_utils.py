"""Helpers to turn a user-confirmed fraud case into adaptive fraud memory + learned keywords.

Used by the human-in-the-loop labeling flow: when a user labels a case as
``fraud``, we (1) upsert a fraud_memory vector row so future queries/blacklists
match it, and (2) extract novel heavy/light phrases into learned_keywords so the
phishing playbook adapts to new scam tactics.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Phrases that would not add value as learned keywords (generic filler).
_STOP_WORDS: set[str] = {
    "the", "and", "for", "are", "but", "not", "you", "your", "this", "that",
    "with", "have", "from", "they", "there", "here", "what", "when", "where",
    "which", "who", "whom", "how", "will", "would", "should", "could", "can",
    "please", "sir", "madam", "maam", "okay", "ok", "yes", "no", "hello", "hi",
    "bank", "account", "call", "money", "transfer", "today", "now", "right",
    "need", "want", "going", "gonna", "like", "just", "really", "actually",
    "something", "anything", "everything", "nothing", "one", "two", "three",
    "get", "got", "let", "tell", "say", "said", "know", "think", "see", "look",
}


def _extract_phrases_from_text(text: str) -> list[str]:
    """Pull plausible 1-3 word scam phrases from a text blob."""
    text = (text or "").lower()
    phrases: list[str] = []
    # 1-3 word n-grams from the raw text
    words = re.findall(r"[a-z][a-z']+", text)
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i : i + n])
            if len(phrase) < 5:
                continue
            tokens = phrase.split()
            if all(t in _STOP_WORDS for t in tokens):
                continue
            if tokens[0] in _STOP_WORDS and n > 1:
                continue
            phrases.append(phrase)
    return phrases


def _score_phrase_weight(phrase: str) -> str:
    """Heuristic: phrases with money/urgency/account words are 'heavy', else 'light'."""
    heavy_hints = (
        "rm", "ringgit", "myr", "transfer", "fee", "tax", "prize", "refund",
        "verify", "security", "password", "otp", "pin", "bank", "account",
        "freeze", "lock", "suspend", "urgent", "immediately", "deadline",
        "win", "winner", "claim", "redeem", "gift", "coupon", "voucher",
        "gov", "government", "police", "bank negara", "lhdn", "customs",
    )
    return "heavy" if any(h in phrase for h in heavy_hints) else "light"


def normalize_fraud_type(value: Any) -> str:
    """Map an arbitrary archetype/trigger/fraud_type value onto the CHECK constraint set.

    Allowed: macau_scam, investment_scam, impersonation_scam, love_scam,
    phishing, parcel_scam, other. Anything unrecognised maps to 'other'.
    """
    raw = str(value or "").strip().lower()
    if not raw or raw in ("none", "user_report", "user_confirmed", "system_detected"):
        return "other"
    if "macau" in raw:
        return "macau_scam"
    if "invest" in raw:
        return "investment_scam"
    if "imperson" in raw or "authority" in raw or "police" in raw or "bnm" in raw:
        return "impersonation_scam"
    if "love" in raw or "romance" in raw or "dating" in raw:
        return "love_scam"
    if "phish" in raw:
        return "phishing"
    if "parcel" in raw or "customs" in raw or "courier" in raw:
        return "parcel_scam"
    if raw in ("macau_scam", "investment_scam", "impersonation_scam", "love_scam", "phishing", "parcel_scam", "other"):
        return raw
    return "other"


def upsert_fraud_memory_from_case(
    case_id: str, case: dict[str, Any], context: dict[str, Any]
) -> None:
    """Write a fraud_memory vector row from a user-confirmed case.

    Args:
        case_id: Fraud case UUID.
        case: The fraud_cases row (as returned by fetch_fraud_case).
        context: fetch_case_context output (transcripts, phishing, entities...).
    """
    from src.db.vector_store import add_fraud_memory

    transcript_text = "\n".join(
        f"{t.get('speaker', '')}: {t.get('utterance', '')}"
        for t in (context.get("transcripts") or [])
        if t.get("utterance")
    )
    phishing_text = "\n".join(
        f"{p.get('content_type', '')}: {p.get('raw_content', '')}"
        for p in (context.get("phishing") or [])
        if p.get("raw_content")
    )
    xai_report = case.get("xai_report") or {}
    if isinstance(xai_report, str):
        try:
            xai_report = json.loads(xai_report)
        except Exception:  # noqa: BLE001
            xai_report = {}
    evidence_text = "\n".join(
        str(e) for e in (xai_report.get("evidence") or []) if e
    )

    content = (
        f"User-confirmed fraud case. Transcript:\n{transcript_text}\n\n"
        f"Submitted material:\n{phishing_text}\n\n"
        f"Evidence:\n{evidence_text}"
    ).strip()
    if not content:
        logger.debug(f"fraud memory skipped for {case_id}: empty content")
        return

    fraud_type = normalize_fraud_type(
        xai_report.get("archetype")
        or case.get("archetype")
        or case.get("trigger_type")
        or "user_report"
    )

    metadata: dict[str, Any] = {
        "phone_numbers": context.get("phone_numbers") or [],
        "bank_accounts": context.get("bank_accounts") or [],
        "urls": context.get("urls") or [],
        "amount_lost_myr": case.get("amount_lost_myr"),
        "risk_tier": case.get("risk_tier") or "HIGH",
        "source": "user_confirmed",
        "language": "en",
    }
    try:
        add_fraud_memory(case_id, fraud_type, content, metadata)
        logger.info(f"fraud memory upserted for {case_id} (type={fraud_type})")
    except Exception as err:  # noqa: BLE001
        logger.warning(f"add_fraud_memory failed for {case_id}: {err}")


def extract_novel_phrases(
    case: dict[str, Any], context: dict[str, Any]
) -> list[tuple[str, str]]:
    """Extract novel heavy/light phrases from the case for learned_keywords.

    Returns:
        List of (keyword, keyword_type) tuples, deduped, excluding phrases
        already present in the default phishing playbook.
    """
    from src.agents.workers.phishing import get_phishing_playbook_data

    xai_report = case.get("xai_report") or {}
    if isinstance(xai_report, str):
        try:
            xai_report = json.loads(xai_report)
        except Exception:  # noqa: BLE001
            xai_report = {}

    # Gather text blobs: evidence, research summary, transcripts, phishing content
    blobs: list[str] = []
    evidence = xai_report.get("evidence") or []
    if isinstance(evidence, list):
        blobs.extend(str(e) for e in evidence)
    research = xai_report.get("research") or {}
    if isinstance(research, dict) and research.get("summary"):
        blobs.append(str(research["summary"]))
    for t in (context.get("transcripts") or []):
        if t.get("utterance"):
            blobs.append(str(t["utterance"]))
    for p in (context.get("phishing") or []):
        if p.get("raw_content"):
            blobs.append(str(p["raw_content"]))
    blob = "\n".join(blobs)

    # Existing known phrases (default playbook + already-learned keywords)
    playbook = get_phishing_playbook_data()
    known: set[str] = set()
    for k in playbook.get("heavy") or []:
        known.add(str(k).lower().strip())
    for k in playbook.get("light") or []:
        known.add(str(k).lower().strip())
    from src.db.supabase import fetch_learned_keywords

    try:
        for row in fetch_learned_keywords():
            known.add(str(row.get("keyword") or "").lower().strip())
    except Exception as err:  # noqa: BLE001
        logger.debug(f"fetch_learned_keywords failed: {err}")

    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    for phrase in _extract_phrases_from_text(blob):
        key = phrase.lower().strip()
        if key in known or key in seen:
            continue
        seen.add(key)
        results.append((phrase, _score_phrase_weight(phrase)))
    return results[:30]
