"""Phishing Analyst Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.agents.prompts import build_phishing_analysis_prompt
from src.agents.state import GraphState, WorkerFinding
from src.db.vector_store import search_fraud_memory
from src.services.vision import extract_text_from_image

logger = logging.getLogger(__name__)

# Default LLM for phishing worker
_raw_key = os.getenv("GROQ_API_KEY") or "gsk_placeholder_key_for_initialization"
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.0, api_key=SecretStr(_raw_key))

PHISHING_SYSTEM_PROMPT = """You are an expert cybersecurity phishing analyst.
Analyze the user-submitted content (which may be SMS text, email body, URL strings, or transcribed text from screenshots) and determine the risk of it being a phishing or scam attempt.

Look for the following signals:
1. Bank/Government Impersonation: Pretending to be Maybank, CIMB, RHB, Bank Negara, PDRM, LHDN, POS Malaysia, etc.
2. Urgent/Threatening Language: Claiming account suspension, immediate blocks, packages held, or legal actions unless action is taken in hours.
3. Call-to-Action Lookalikes: Providing links that mimic official bank domains (e.g. cimb-secure-login.net, maybank2u-verify.xyz) or asking the user to call suspicious mobile numbers.
4. Information Harvester: Requesting login credentials, card numbers, PINs, or OTPs.

Respond in strict JSON format:
{
  "score": integer (0-100),
  "confidence": float (0.0-1.0),
  "evidence": ["bullet point 1", "bullet point 2"]
}"""


def extract_entities_regex(content: str) -> dict[str, list[str]]:
    """Extract phone numbers, URLs, and bank accounts using regex patterns."""
    phone_pattern = r"(?:\+?60|0)(?:1[0-9]-?\d{7,8}|3-?\d{8}|[4-9]\d{7})"
    url_pattern = r"https?://[^\s<>\"']+|www\.[^\s<>\"']+"
    account_pattern = r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}(?:[-\s]?\d{4})?\b"

    phones = list(set(re.findall(phone_pattern, content)))
    urls = list(set(re.findall(url_pattern, content)))
    accounts = list(set(re.findall(account_pattern, content)))

    return {
        "phone_numbers": phones,
        "urls": urls,
        "bank_accounts": accounts,
    }


def _rule_based_phishing_analysis(
    content: str, content_type: str, entities: dict[str, list[str]]
) -> WorkerFinding:
    """Rule-based phishing indicator detection baseline."""
    evidence: list[str] = []
    score = 10
    confidence = 0.88

    lower_content = content.lower()

    # Impersonation signals
    keywords = [
        "maybank", "cimb", "rhb", "public bank", "bank negara", "pdrm",
        "lhdn", "pos malaysia", "account suspended", "gantung akaun",
        "verify account", "kemaskini", "otp", "one time password", "urgent",
        "tindakan undang-undang", "2 hours", "lockout"
    ]
    matched_keywords = [k for k in keywords if k in lower_content]
    if matched_keywords:
        score += 35
        evidence.append(f"Suspicious phishing keywords detected: {', '.join(matched_keywords[:4])}")

    # Suspicious URLs
    if entities.get("urls"):
        score += 30
        evidence.append(f"Contains external links: {', '.join(entities['urls'][:2])}")

    # Phone numbers
    if entities.get("phone_numbers"):
        score += 15
        evidence.append(f"Extracted contact numbers: {', '.join(entities['phone_numbers'][:2])}")

    if content_type == "IMAGE":
        evidence.append("Screenshot text extracted via Groq Vision OCR")

    score = min(score, 100)
    if not evidence:
        evidence.append("No obvious phishing language or malicious URLs detected")

    return WorkerFinding(
        worker="phishing",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )


def phishing_worker_node(state: GraphState) -> dict[str, Any]:
    """Pure state transformation node for Phishing Analyst Worker.

    Extracts text from screenshots via Groq Vision (if IMAGE), parses entities,
    evaluates phishing indicators, and relays extracted_entities in state.
    """
    payload = state.get("trigger_payload") or {}
    content_type = str(payload.get("content_type", "TEXT")).upper()
    raw_content = str(payload.get("content", ""))

    analysis_content = raw_content

    # Step 1: Groq Vision OCR if IMAGE
    if content_type == "IMAGE" and raw_content:
        try:
            ocr_res = extract_text_from_image(raw_content)
            if inspect.isawaitable(ocr_res):
                ocr_text = str(raw_content)
            else:
                ocr_text = str(ocr_res)
            analysis_content = f"[Extracted from screenshot via Groq Vision]\n{ocr_text}"
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Groq Vision OCR failed: {err}")

    # Step 2: Extract structured entities (CRITICAL ASSERTION REQUIREMENT)
    extracted_entities = extract_entities_regex(analysis_content)

    # Step 3: Rule-based baseline analysis
    finding = _rule_based_phishing_analysis(analysis_content, content_type, extracted_entities)

    # Step 4: Semantic search against fraud memory
    try:
        raw_hits = search_fraud_memory(analysis_content[:200], threshold=0.75, top_k=3)
        if inspect.isawaitable(raw_hits):
            hits: list[dict[str, Any]] = []
        elif isinstance(raw_hits, list):
            hits = raw_hits
        else:
            hits = []

        if hits:
            max_sim = max(float(h.get("similarity", 0.0)) for h in hits)
            if max_sim >= 0.75:
                finding.score = max(finding.score, int(max_sim * 95))
                finding.confidence = max(finding.confidence, 0.92)
                finding.evidence.append(
                    f"Matches historical phishing template in database (pgvector similarity {max_sim:.2f})"
                )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Phishing pgvector search skipped or failed: {err}")

    # Step 5: LLM analysis if active / mocked
    try:
        prompt_text = build_phishing_analysis_prompt(content_type, analysis_content)
        messages = [
            SystemMessage(content=PHISHING_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text),
        ]
        llm_response = llm.invoke(messages)
        content = str(llm_response.content).strip()

        if content.startswith("{") and content.endswith("}"):
            parsed = json.loads(content)
            llm_score = int(parsed.get("score", finding.score))
            llm_conf = float(parsed.get("confidence", finding.confidence))
            llm_ev = list(parsed.get("evidence", finding.evidence))
            finding = WorkerFinding(
                worker="phishing",
                score=llm_score,
                confidence=llm_conf,
                evidence=llm_ev,
            )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Phishing LLM invocation skipped or failed: {err}")

    # Return both phishing_finding and extracted_entities in state updates
    return {
        "phishing_finding": finding.model_dump(),
        "extracted_entities": extracted_entities,
    }
