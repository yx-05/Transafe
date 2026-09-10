"""MO (Modus Operandi) fingerprint extractor — L1, post-call, asynchronous.

Runs *after* the v1 pipeline completes, off the live path. Extracts a
structured behavioural fingerprint from the stored transcript. Identifiers give
precision; the MO fingerprint gives recall.

Hard safety split (01_upgrade_plan.md §4.2)
-------------------------------------------
* Phone / account / URL / amount / IBAN → **deterministic regex only, never an
  LLM**. A hallucinated digit creates a false graph edge, a false campaign, and
  a countermeasure justified by a number nobody said.
* Impersonated entity, pretext, script phases, pressure tactics, novel phrases,
  escalation timing → LLM, schema-constrained JSON.

Three hard constraints
----------------------
1. Every extracted field cites an ``utterance_idx``.
2. Runs post-case; zero latency impact on the phone agent.
3. ``narrative`` is the field that gets embedded (768-dim, ``embed_text``) and
   powers narrative linkage in L3.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm import extract_json_object, invoke_deepseek_with_key_rotation
from src.db.vector_store import embed_text, get_supabase_client

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768
MIN_TRANSCRIPT_UTTERANCES = 3

MO_EXTRACTION_SYSTEM_PROMPT = """\
You are a fraud behavioural analyst. You extract a Modus Operandi (MO) fingerprint \
from a call transcript. You MUST:
1. Ground every extracted field in a specific utterance index from the transcript.
2. Never invent identifiers (phone numbers, account numbers, URLs) — those are \
extracted by deterministic regex, not by you.
3. Return ONLY a JSON object matching the required schema.
4. If the transcript is too short or ambiguous, return {"ambiguous": true}.

Schema:
{
  "impersonated_entity": "string or null",
  "pretext": "string or null",
  "script_phases": ["string", ...],
  "pressure_tactics": ["string", ...],
  "novel_phrases": [{"text": "string", "lang": "ms|en|mixed", "utterance_idx": int}, ...],
  "languages": ["ms", "en", ...],
  "time_to_money_ask_sec": int or null,
  "verification_evasion": "string or null",
  "evidence_utterances": [int, ...],
  "narrative": "string — 2-4 sentence summary of the scam script"
}
"""

# ── Deterministic identifier patterns (NEVER LLM) ───────────────────────────
_PHONE_RE = re.compile(r"(?:\+?6?0)[\s-]?1\d[\s-]?\d{3,4}[\s-]?\d{4}")
_ACCOUNT_RE = re.compile(r"\b\d{2,4}(?:[\s-]?\d{3,4}){2,4}\b")
_URL_RE = re.compile(r"\b(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s,;]*)?", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\b(?:RM|MYR|USD|\$)\s?([\d,]+(?:\.\d{1,2})?)\b", re.IGNORECASE)

# Tokens that look like accounts but are not (dates, times, id-cards handled loosely)
_NON_URL_SUFFIXES = frozenset({"etc", "com0"})


def extract_mo_fingerprint(
    case_id: str,
    transcript: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Extract MO fingerprint from a call transcript.

    Args:
        case_id: UUID of the fraud case.
        transcript: List of utterance dicts with keys:
            ``speaker``, ``utterance``, ``risk_score``, ``seq_idx``.

    Returns:
        MO fingerprint dict matching the schema, or ``None`` on failure or on
        an ambiguous transcript. The dict includes ``case_id`` and ``narrative``.
    """
    if not transcript or len(transcript) < MIN_TRANSCRIPT_UTTERANCES:
        logger.warning(
            "Transcript for case %s too short (%d utterances)",
            case_id,
            len(transcript) if transcript else 0,
        )
        return None

    transcript_text = "\n".join(
        f"[{i}] {u.get('speaker', 'UNKNOWN')}: {u.get('utterance', '')}"
        for i, u in enumerate(transcript)
    )

    messages = [
        SystemMessage(content=MO_EXTRACTION_SYSTEM_PROMPT),
        HumanMessage(content=f"Case ID: {case_id}\n\nTranscript:\n{transcript_text}"),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        mo = extract_json_object(response.content)
        if mo is None:
            logger.error("MO extractor: LLM returned unparseable JSON for case %s", case_id)
            return _attach_case_id(_mo_fallback(transcript), case_id)
        if mo.get("ambiguous"):
            logger.info("MO extractor: transcript %s marked ambiguous", case_id)
            return None
        mo["case_id"] = case_id
        mo["evidence_utterances"] = [
            idx
            for idx in mo.get("evidence_utterances", [])
            if isinstance(idx, int) and 0 <= idx < len(transcript)
        ]
        mo["novel_phrases"] = _clamp_novel_phrases(mo.get("novel_phrases", []), len(transcript))
        mo.setdefault("extractor", "llm-v1")
        # Identifiers are regex-only — overwrite anything the LLM may have emitted.
        mo["identifiers"] = extract_identifiers(transcript)
        return mo
    except Exception:
        logger.exception("MO extractor failed for case %s", case_id)
        return _attach_case_id(_mo_fallback(transcript), case_id)


def _attach_case_id(mo: dict[str, Any] | None, case_id: str) -> dict[str, Any] | None:
    """Attach ``case_id`` to a fallback MO dict, if any."""
    if mo is None:
        return None
    mo["case_id"] = case_id
    return mo


def _clamp_novel_phrases(phrases: Any, transcript_len: int) -> list[dict[str, Any]]:
    """Drop novel phrases whose ``utterance_idx`` is out of transcript bounds."""
    if not isinstance(phrases, list):
        return []
    kept: list[dict[str, Any]] = []
    for phrase in phrases:
        if not isinstance(phrase, dict):
            continue
        idx = phrase.get("utterance_idx")
        if isinstance(idx, int) and 0 <= idx < transcript_len:
            kept.append(phrase)
    return kept


def extract_identifiers(transcript: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Deterministically extract identifiers from a transcript. Regex only.

    This function is the *only* sanctioned source of phone numbers, account
    numbers, URLs and amounts in the v2 pipeline. No LLM output is ever
    accepted for these fields.

    Args:
        transcript: List of utterance dicts.

    Returns:
        Dict with keys ``phones``, ``accounts``, ``urls``, ``amounts``; each a
        list of ``{"value": str, "utterance_idx": int}``.
    """
    phones: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    urls: list[dict[str, Any]] = []
    amounts: list[dict[str, Any]] = []

    for idx, utt in enumerate(transcript):
        text = str(utt.get("utterance", "") or "")
        if not text:
            continue

        matched_spans: list[tuple[int, int]] = []

        for match in _PHONE_RE.finditer(text):
            phones.append({"value": match.group(0).strip(), "utterance_idx": idx})
            matched_spans.append(match.span())

        for match in _URL_RE.finditer(text):
            value = match.group(0).strip().rstrip(".,;")
            if "." not in value:
                continue
            urls.append({"value": value, "utterance_idx": idx})
            matched_spans.append(match.span())

        for match in _AMOUNT_RE.finditer(text):
            amounts.append({"value": match.group(0).strip(), "utterance_idx": idx})
            matched_spans.append(match.span())

        for match in _ACCOUNT_RE.finditer(text):
            start, end = match.span()
            if any(start < s_end and s_start < end for s_start, s_end in matched_spans):
                continue
            digits = re.sub(r"\D", "", match.group(0))
            if len(digits) < 8:
                continue
            accounts.append({"value": match.group(0).strip(), "utterance_idx": idx})

    return {
        "phones": _dedupe_identifiers(phones),
        "accounts": _dedupe_identifiers(accounts),
        "urls": _dedupe_identifiers(urls),
        "amounts": _dedupe_identifiers(amounts),
    }


def _dedupe_identifiers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate identifier hits on ``value``, keeping the earliest index."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        value = item["value"]
        if value in seen:
            continue
        seen.add(value)
        out.append(item)
    return out


def _mo_fallback(transcript: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministic fallback when the LLM is unavailable.

    Extracts structural signals only: language detection (ms/en ratio),
    approximate time-to-money-ask, and a minimal narrative from the
    concatenated transcript. No script phases, no pressure tactics — the
    fallback never guesses behaviour it cannot observe.
    """
    if not transcript:
        return None

    full_text = " ".join(str(u.get("utterance", "") or "") for u in transcript)

    ms_markers = (
        "saya",
        "akaun",
        "wang",
        "bayaran",
        "encik",
        "puan",
        "tidak",
        "sila",
        "anda",
        "polis",
        "pegawai",
        "ini",
        "ya",
    )
    lowered = full_text.lower()
    ms_hits = sum(1 for marker in ms_markers if marker in lowered)
    en_chars = sum(1 for c in full_text if c.isascii() and c.isalpha())

    languages: list[str] = []
    if ms_hits >= 2:
        languages.append("ms")
    if en_chars > 10:
        languages.append("en")

    money_keywords = ("transfer", "akaun", "account", "bank", "rm", "wang", "bayaran")
    money_idx: int | None = None
    for i, utt in enumerate(transcript):
        text_lower = str(utt.get("utterance", "") or "").lower()
        if any(kw in text_lower for kw in money_keywords):
            money_idx = i
            break

    # Uniform-spacing heuristic: ~15 seconds per utterance.
    time_to_money = money_idx * 15 if money_idx is not None else None

    return {
        "impersonated_entity": None,
        "pretext": None,
        "script_phases": [],
        "pressure_tactics": [],
        "novel_phrases": [],
        "languages": languages,
        "time_to_money_ask_sec": time_to_money,
        "verification_evasion": None,
        "evidence_utterances": list(range(min(5, len(transcript)))),
        "narrative": full_text[:300] if full_text else "",
        "identifiers": extract_identifiers(transcript),
        "extractor": "fallback-v1",
    }


def store_mo_fingerprint(mo: dict[str, Any]) -> str | None:
    """Store MO fingerprint + narrative embedding in the ``case_mo`` table.

    Args:
        mo: MO fingerprint dict from :func:`extract_mo_fingerprint`.

    Returns:
        The ``case_id`` if stored successfully, ``None`` on failure.
    """
    case_id = mo.get("case_id")
    if not case_id:
        logger.warning("store_mo_fingerprint: MO has no case_id")
        return None

    narrative = mo.get("narrative", "") or ""
    try:
        embedding = embed_text(narrative) if narrative else [0.0] * EMBEDDING_DIM
    except Exception:
        logger.exception("store_mo_fingerprint: embedding failed for case %s", case_id)
        embedding = [0.0] * EMBEDDING_DIM

    row = {
        "case_id": case_id,
        "fingerprint": json.dumps(mo),
        "narrative": narrative,
        "embedding": embedding,
        "extractor": mo.get("extractor", "llm-v1"),
    }

    try:
        client = get_supabase_client()
        client.table("case_mo").upsert(row).execute()
        return str(case_id)
    except Exception:
        logger.exception("Failed to store MO fingerprint for case %s", case_id)
        return None


def run_mo_extraction(case_id: str, transcript: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Full pipeline: extract + store the MO fingerprint for a case.

    Args:
        case_id: UUID of the fraud case.
        transcript: List of utterance dicts.

    Returns:
        The stored MO fingerprint dict, or ``None`` on failure.
    """
    mo = extract_mo_fingerprint(case_id, transcript)
    if mo is None:
        return None
    if store_mo_fingerprint(mo) is None:
        return None
    return mo
