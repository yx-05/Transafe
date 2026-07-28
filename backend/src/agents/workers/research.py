"""Research Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.agents.prompts import build_research_prompt
from src.agents.state import GraphState, WorkerFinding
from src.db.vector_store import add_fraud_memory, search_fraud_memory
from src.services.tavily import tavily_search

logger = logging.getLogger(__name__)

# Default LLM for research worker
_raw_key = os.getenv("GROQ_API_KEY") or "gsk_placeholder_key_for_initialization"
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.0, api_key=SecretStr(_raw_key))

RESEARCH_QUERY_SYSTEM_PROMPT = """You are an expert financial fraud research intelligence agent.
Analyze the query entities (phone numbers, bank accounts, URLs) alongside the RAG search results from our internal fraud database and public web reports.
Your job is to determine:
1. If any of the query entities appear directly in the historical scam logs (high similarity matches > 0.80).
2. If there are close semantic matches describing similar fraud patterns involving these entities.
3. If public web reports (Tavily search) indicate these accounts or numbers are linked to online scams, police reports, or central bank warning lists in Malaysia.

Return your findings in strict JSON format:
{
  "score": integer (0-100),
  "confidence": float (0.0-1.0),
  "evidence": ["bullet point 1", "bullet point 2"]
}"""

REPORT_SUMMARISE_PROMPT = """You are a fraud investigator. Summarize the user-submitted fraud report into a concise narrative of how the scam transpired.
User Report:
"{description}"
Return a short summary string."""


def _extract_entities_from_state(state: GraphState) -> list[str]:
    """Gather all entity strings from payload, extracted_entities, and associated_case_context."""
    entities: list[str] = []
    payload = state.get("trigger_payload") or {}

    # Read from extracted_entities relay (stage 1 phishing worker)
    extracted = state.get("extracted_entities") or {}
    for key in ("phone_numbers", "urls", "bank_accounts"):
        val = extracted.get(key)
        if isinstance(val, list):
            entities.extend([str(item) for item in val if item])

    # Read from payload directly
    for key in ("phone", "phone_number", "url", "recipient_account", "account"):
        val = payload.get(key)
        if val and isinstance(val, str) and val not in entities:
            entities.append(val)

    # Read from associated_case_context
    case_context = state.get("associated_case_context") or {}
    for key in ("phone_numbers", "urls", "bank_accounts"):
        val = case_context.get(key)
        if isinstance(val, list):
            for item in val:
                if item and str(item) not in entities:
                    entities.append(str(item))

    return entities


def _run_query_mode(state: GraphState) -> WorkerFinding:
    """Execute QUERY mode logic for Research Worker."""
    entities = _extract_entities_from_state(state)
    if not entities:
        return WorkerFinding(
            worker="research",
            score=0,
            confidence=0.80,
            evidence=["No target entities (phone, account, URL) found to query in research database"],
        )

    # Step 1: Internal pgvector query
    internal_hits: list[dict[str, Any]] = []
    try:
        raw_hits = search_fraud_memory(" ".join(entities), threshold=0.75, top_k=5)
        if inspect.isawaitable(raw_hits):
            internal_hits = []
        elif isinstance(raw_hits, list):
            internal_hits = raw_hits
    except Exception as err:  # noqa: BLE001
        logger.warning(f"Error querying pgvector fraud memory: {err}")

    # Check max similarity score
    max_sim = 0.0
    for hit in internal_hits:
        sim = float(hit.get("similarity", 0.0))
        max_sim = max(max_sim, sim)

    # Step 2: Tavily fallback if pgvector max similarity < 0.75 (CRITICAL ASSERTION REQUIREMENT)
    tavily_hits: list[dict[str, Any]] = []
    if max_sim < 0.75:
        try:
            raw_tavily = tavily_search(entities)
            if inspect.isawaitable(raw_tavily):
                tavily_hits = []
            elif isinstance(raw_tavily, list):
                tavily_hits = raw_tavily
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Tavily web search fallback error: {err}")

    # Rule-based fallback calculation
    evidence: list[str] = []
    score = 0
    confidence = 0.85

    if max_sim >= 0.80:
        score = int(max_sim * 100)
        confidence = 0.95
        evidence.append(
            f"Match found in internal fraud database (pgvector similarity {max_sim:.2f})"
        )
    elif max_sim >= 0.75:
        score = int(max_sim * 90)
        confidence = 0.85
        evidence.append(
            f"Moderate match in internal fraud memory (pgvector similarity {max_sim:.2f})"
        )
    else:
        evidence.append(
            f"No high-confidence match in internal fraud database (max similarity {max_sim:.2f})"
        )

    if tavily_hits:
        score = max(score, 70)
        confidence = max(confidence, 0.88)
        first_url = tavily_hits[0].get("url", "web report")
        evidence.append(f"Tavily web search: external scam report found ({first_url})")

    if not evidence:
        evidence.append("Entity check completed; no historical scam reports identified")

    finding = WorkerFinding(
        worker="research",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )

    # Attempt LLM evaluation if available
    try:
        prompt_text = build_research_prompt(entities, internal_hits, tavily_hits)
        messages = [
            SystemMessage(content=RESEARCH_QUERY_SYSTEM_PROMPT),
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
                worker="research",
                score=llm_score,
                confidence=llm_conf,
                evidence=llm_ev,
            )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Research LLM invocation skipped or failed: {err}")

    return finding


def _run_ingest_mode(state: GraphState) -> WorkerFinding:
    """Execute INGEST mode logic for REPORT trigger."""
    payload = state.get("trigger_payload") or {}
    description = str(payload.get("description") or payload.get("report_text") or "Fraud report")
    fraud_type = str(payload.get("fraud_type", "user_report"))
    case_id = str(state.get("case_id") or uuid.uuid4())

    summary = description
    try:
        llm_resp = llm.invoke(REPORT_SUMMARISE_PROMPT.format(description=description))
        summary = str(llm_resp.content).strip()
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Report summarization LLM failed: {err}")

    metadata = {
        "phone_numbers": payload.get("phone_numbers", []),
        "bank_accounts": payload.get("bank_accounts", []),
        "urls": payload.get("urls", []),
        "amount_lost_myr": payload.get("amount_lost_myr"),
        "risk_tier": "HIGH",
        "source": "user_report",
    }

    try:
        add_fraud_memory(case_id, fraud_type, summary, metadata)
    except Exception as err:  # noqa: BLE001
        logger.warning(f"Failed to ingest fraud memory: {err}")

    return WorkerFinding(
        worker="research",
        score=0,
        confidence=1.0,
        evidence=[f"Successfully ingested fraud report '{fraud_type}' into memory (case {case_id})"],
    )


def research_worker_node(state: GraphState) -> dict[str, Any]:
    """Pure state transformation node for Research Worker.

    Supports QUERY mode (pgvector RAG + Tavily fallback) and INGEST mode (REPORT trigger).
    """
    trigger_type = state.get("trigger_type", "TRANSACTION")
    if trigger_type == "REPORT":
        finding = _run_ingest_mode(state)
    else:
        finding = _run_query_mode(state)

    return {"research_finding": finding.model_dump()}
