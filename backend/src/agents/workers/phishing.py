"""Phishing Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.agents.llm import extract_json_object, invoke_groq_with_key_rotation
from src.agents.prompts import (
    build_phishing_analysis_prompt,
    build_phishing_research_planner_prompt,
)
from src.agents.state import GraphState, WorkerFinding
from src.db.vector_store import search_fraud_memory
from src.services.tavily import tavily_search
from src.services.vision import extract_text_from_image

logger = logging.getLogger(__name__)


def get_phishing_llm(model_name: str = "llama-3.3-70b-versatile") -> ChatGroq:
    """Get ChatGroq LLM instance reading GROQ_API_KEY dynamically at runtime."""
    raw_key = os.getenv("GROQ_API_KEY") or "gsk_placeholder_key_for_initialization"
    return ChatGroq(model=model_name, temperature=0.0, api_key=SecretStr(raw_key))


class DynamicPhishingLLM:
    """Dynamic LLM proxy reading GROQ_API_KEY dynamically with multi-key rotation and fallback."""

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        return invoke_groq_with_key_rotation(messages)


llm = DynamicPhishingLLM()


PHISHING_SYSTEM_PROMPT = """You are an expert cybersecurity phishing analyst.
Analyze the user-submitted content (which may be SMS text, email body, URL strings, or transcribed text from screenshots) and determine the risk of it being a phishing or scam attempt.

Look for the following signals:
1. Bank/Government Impersonation: Pretending to be Maybank, CIMB, RHB, Bank Negara, PDRM, LHDN, POS Malaysia, etc.
2. Urgent/Threatening Language: Claiming account suspension, immediate blocks, packages held, or legal actions unless action is taken in hours.
3. Call-to-Action Lookalikes: Providing links that mimic official bank domains or asking user to call suspicious numbers.
4. Information Harvester: Requesting login credentials, card numbers, PINs, or OTPs.

Respond in strict JSON format:
{
  "score": integer (0-100),
  "confidence": float (0.0-1.0),
  "evidence": ["bullet point 1", "bullet point 2"]
}"""


PHISHING_RESEARCH_PLANNER_SYSTEM_PROMPT = """You are a research planner for a phishing detection system.
A phishing analyst has analyzed material (SMS, email, URL, or a live-call transcript) and produced an initial risk score.
Your job: decide whether an ONLINE WEB SEARCH of Malaysian fraud alert lists (Bank Negara Malaysia, Securities Commission Malaysia, PDRM) would improve the verdict.

Reason to search (search=true) when:
- The material references a specific phone number, bank account, or URL that is NOT confirmed by the internal fraud database.
- The material names an organization or person whose legitimacy is unknown (e.g. "Inspector Tan", "Commercial Crime Investigation Department", investment schemes like "JJPTR", "Genneva", "MBI", "mCoin").
- The score is mid-range or confidence is low, and specific searchable entities exist.

Do NOT search (search=false) when:
- The material is clearly benign with no entities, score < 40, and no internal database matches.
- An internal fraud database match (similarity >= 0.80) already confirms the verdict and score >= 70.

Queries must be short (1-4 keywords). Include the specific entity value (phone number, brand, name) plus a Malaysian fraud context term like "scam", "BNM alert list", or "PDRM". Output at most 3 queries.

Respond ONLY in strict JSON format:
{
  "search": true or false,
  "reasoning": "one short sentence",
  "queries": ["..."],
  "confidence": float (0.0-1.0)
}"""


def _extract_entities_from_text(text: str) -> dict[str, list[str]]:
    """Regex entity extractor for phone numbers, URLs, and bank account candidates."""
    phones = re.findall(r"\+?60\d{8,10}|\b0\d{8,10}\b", text)
    urls = re.findall(r"https?://[^\s]+|[a-zA-Z0-9.-]+\.(?:com|xyz|net|org|site|top|cc)[^\s]*", text)
    accounts = re.findall(r"\b\d{10,16}\b", text)

    return {
        "phone_numbers": list(set(phones)),
        "urls": list(set(urls)),
        "bank_accounts": list(set(accounts)),
    }


def _rule_based_phishing_analysis(
    content_type: str, content: str, RAG_hits: list[dict[str, Any]]
) -> WorkerFinding:
    """Deterministic rule-based baseline for phishing material evaluation."""
    evidence: list[str] = []
    score = 10
    confidence = 0.85

    lower_text = content.lower()

    # Impersonation signals
    keywords = ["maybank", "cimb", "pdrm", "lhdn", "bank negara", "kwsp", "pos malaysia", "suspension", "urgent"]
    found_kw = [kw for kw in keywords if kw in lower_text]

    if found_kw:
        score += len(found_kw) * 15
        evidence.append(f"Detected suspicious keywords: {', '.join(found_kw)}")

    # URL anomalies (.xyz, .top, unencrypted http)
    if "http://" in lower_text or ".xyz" in lower_text or ".top" in lower_text or ".site" in lower_text:
        score += 35
        evidence.append("Suspicious URL TLD or unencrypted HTTP link detected")

    # Vector memory hits
    if RAG_hits:
        max_sim = max([float(h.get("similarity", 0.0)) for h in RAG_hits], default=0.0)
        if max_sim > 0.80:
            score = max(score, int(max_sim * 100))
            evidence.append(f"Matches historical phishing database (similarity {max_sim:.2f})")

    score = min(score, 100)
    if not evidence:
        evidence.append("No obvious phishing keywords or suspicious URLs detected")

    return WorkerFinding(
        worker="phishing",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )


def _run_research_enhancement(
    content: str,
    entities: dict[str, list[str]],
    rag_hits: list[dict[str, Any]],
    base_finding: WorkerFinding,
) -> dict[str, Any]:
    """Planner-gated agentic web research step for deep phishing analysis.

    Asks the planner LLM whether an online search of Malaysian fraud alert
    lists would improve the verdict. If yes, runs ``tavily_search`` over the
    suggested entity queries and returns a structured ``research`` context
    (bounded: at most one round, at most 3 queries).

    Hard gates (skip research entirely):
    - clearly benign: no entities, score < 40, no internal DB hits
    - verdict already solid: score >= 70 AND internal hit similarity >= 0.80
    """
    result: dict[str, Any] = {
        "queried": False,
        "decision": "skipped",
        "reasoning": "",
        "queries": [],
        "web_hits": [],
    }

    has_entities = bool(
        entities.get("phone_numbers") or entities.get("urls") or entities.get("bank_accounts")
    )
    has_rag = bool(rag_hits)
    strong_rag = any(float((h.get("similarity") or 0.0)) >= 0.80 for h in rag_hits)

    # Hard gate 1: clearly benign → no research needed
    if not has_entities and base_finding.score < 40 and not has_rag:
        result["reasoning"] = "skipped by hard gate (benign)"
        return result
    # Hard gate 2: internal DB already confirms a solid verdict
    if base_finding.score >= 70 and strong_rag:
        result["reasoning"] = "skipped by hard gate (verdict confirmed by internal DB)"
        return result

    # Planner LLM decides whether a web search is needed
    plan: dict[str, Any] = {}
    try:
        prompt_text = build_phishing_research_planner_prompt(
            content=content,
            entities_json=json.dumps(entities, indent=2),
            rag_json=json.dumps(rag_hits, indent=2)[:1500],
            base_score=base_finding.score,
            base_confidence=base_finding.confidence,
        )
        messages = [
            SystemMessage(content=PHISHING_RESEARCH_PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text),
        ]
        llm_response = llm.invoke(messages)
        parsed = extract_json_object(
            llm_response.content if hasattr(llm_response, "content") else llm_response
        )
        if isinstance(parsed, dict):
            plan = parsed
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Phishing research planner LLM failed, using heuristic: {err}")

    queries: list[str] = []
    if plan.get("search") is True and isinstance(plan.get("queries"), list):
        queries = [str(q).strip() for q in plan["queries"] if str(q).strip()]
        result["decision"] = "llm"
        result["reasoning"] = str(plan.get("reasoning", "") or "planner approved search")
    elif isinstance(plan.get("search"), bool):
        # Planner explicitly decided no search is needed
        result["decision"] = "llm"
        result["reasoning"] = str(plan.get("reasoning", "") or "planner decided search not needed")
        return result
    else:
        # Planner LLM unavailable / malformed → conservative heuristic fallback:
        # search only when specific entities exist (phones / urls / accounts)
        result["decision"] = "heuristic"
        result["reasoning"] = "planner unavailable; heuristic fallback"
        if has_entities:
            queries = [
                e
                for e in (
                    entities.get("phone_numbers", [])
                    + entities.get("urls", [])
                    + entities.get("bank_accounts", [])
                )
                if e
            ][:3]

    if not queries:
        result["reasoning"] = result.get("reasoning") or "no searchable queries"
        return result

    # Bounded execution: single web search round over the planner's queries
    web_hits: list[dict[str, Any]] = []
    try:
        raw = tavily_search(queries)
        if inspect.isawaitable(raw):
            web_hits = []
        elif isinstance(raw, list):
            web_hits = [h for h in raw if isinstance(h, dict)]
    except Exception as err:  # noqa: BLE001
        logger.warning(f"Phishing web research search failed: {err}")

    result["queried"] = True
    result["queries"] = queries
    result["web_hits"] = [
        {
            "title": str(h.get("title", "") or "")[:200],
            "url": str(h.get("url", "") or ""),
        }
        for h in web_hits
    ]
    return result


def _final_verdict_with_web(
    source: str,
    content: str,
    base_finding: WorkerFinding,
    research: dict[str, Any],
) -> WorkerFinding:
    """Stage 4: re-run the phishing LLM verdict with external web evidence.

    Only called when web research produced hits. If the LLM fails, falls back
    to the base finding with a web-confirmation evidence line appended (and a
    score floor of 70, matching the research worker's external-confirmation
    confidence).
    """
    web_lines = [
        f"- {hit.get('title', '')} ({hit.get('url', '')})"
        for hit in research.get("web_hits", [])
    ]
    web_results = "\n".join(web_lines)

    try:
        prompt_text = build_phishing_analysis_prompt(
            source, content, web_results=web_results
        )
        messages = [
            SystemMessage(content=PHISHING_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text),
        ]
        llm_response = llm.invoke(messages)
        parsed = extract_json_object(
            llm_response.content if hasattr(llm_response, "content") else llm_response
        )
        if isinstance(parsed, dict):
            score = int(parsed.get("score", base_finding.score))
            confidence = float(parsed.get("confidence", base_finding.confidence))
            evidence = list(parsed.get("evidence", base_finding.evidence))
            if not evidence:
                evidence = list(base_finding.evidence)
            return WorkerFinding(
                worker="phishing",
                score=score,
                confidence=confidence,
                evidence=evidence,
            )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Phishing final web-verdict LLM failed, using base + web evidence: {err}")

    # Fallback: web confirmation of a scam entity lifts the verdict
    return WorkerFinding(
        worker="phishing",
        score=max(base_finding.score, 70),
        confidence=max(base_finding.confidence, 0.90),
        evidence=list(base_finding.evidence)
        + [
            "Tavily web search: external scam report confirmed "
            f"({research['web_hits'][0].get('url', 'web report')})"
        ],
    )


def phishing_worker_node(
    state: GraphState, enable_web_research: bool = True
) -> dict[str, Any]:
    """Pure state transformation node for Phishing Worker.

    Stage 1: If IMAGE material, uses Groq Vision OCR to transcribe text.
    Stage 2: Extracts entities (phone numbers, URLs, accounts), performs pgvector search,
             and returns risk finding plus extracted_entities for downstream workers.
    Stage 3: LLM analysis (rules + RAG + LLM verdict).
    Stage 4 (optional, gated): agentic web research — a planner LLM decides
             whether an online search of Malaysian fraud alert lists is needed,
             runs ``tavily_search``, then re-runs the verdict with web evidence.
    """
    payload = state.get("trigger_payload") or {}
    phish_material = payload.get("phishing_material") or payload

    source = str(phish_material.get("source_type") or phish_material.get("content_type") or "TEXT").upper()
    raw_content = str(phish_material.get("content", ""))

    analysis_content = raw_content

    # Guard: nothing to analyze (avoids OCR/LLM churn on empty CALL-trigger payloads)
    if not analysis_content.strip() and source not in ("IMAGE", "SCREENSHOT"):
        return {
            "phishing_finding": WorkerFinding(
                worker="phishing",
                score=0,
                confidence=0.0,
                evidence=["No content provided for phishing analysis."],
            ).model_dump(),
            "extracted_entities": {},
            "research": {
                "queried": False,
                "decision": "skipped",
                "reasoning": "no content",
                "queries": [],
                "web_hits": [],
            },
        }

    # Stage 1: Groq Vision OCR if IMAGE source
    if source in ("IMAGE", "SCREENSHOT") and raw_content:
        try:
            ocr_res = extract_text_from_image(raw_content)
            if inspect.isawaitable(ocr_res):
                analysis_content = raw_content
            elif isinstance(ocr_res, str) and ocr_res.strip():
                analysis_content = ocr_res.strip()
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Groq Vision OCR failed, using raw content: {err}")

    # Stage 2: Entity extraction & pgvector RAG search
    extracted_entities = _extract_entities_from_text(analysis_content)

    RAG_hits: list[dict[str, Any]] = []
    if analysis_content:
        try:
            raw_hits = search_fraud_memory(analysis_content[:200], threshold=0.75, top_k=3)
            if inspect.isawaitable(raw_hits):
                RAG_hits = []
            elif isinstance(raw_hits, list):
                RAG_hits = raw_hits
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Failed to query fraud memory for phishing node: {err}")

    # Baseline rule analysis
    finding = _rule_based_phishing_analysis(source, analysis_content, RAG_hits)

    # Stage 3: LLM analysis if available
    try:
        prompt_text = build_phishing_analysis_prompt(source, analysis_content)
        messages = [
            SystemMessage(content=PHISHING_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text),
        ]
        llm_response = llm.invoke(messages)
        parsed = extract_json_object(llm_response.content if hasattr(llm_response, "content") else llm_response)
        if isinstance(parsed, dict):
            score = int(parsed.get("score", finding.score))
            confidence = float(parsed.get("confidence", finding.confidence))
            evidence = list(parsed.get("evidence", finding.evidence))
            if not evidence:
                if score == 0:
                    evidence = ["No phishing indicators or impersonation keywords detected in submitted content."]
                else:
                    evidence = [f"Phishing content analysis evaluated with score {score}/100."]
            finding = WorkerFinding(
                worker="phishing",
                score=score,
                confidence=confidence,
                evidence=evidence,
            )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Phishing LLM invocation skipped or failed, using rule base: {err}")

    # Stage 4: Agentic research enhancement (planner-gated, on-demand web search)
    research = _run_research_enhancement(analysis_content, extracted_entities, RAG_hits, finding)
    if research.get("queried") and research.get("web_hits"):
        finding = _final_verdict_with_web(source, analysis_content, finding, research)

    return {
        "phishing_finding": finding.model_dump(),
        "extracted_entities": extracted_entities,
        "research": research,
    }


def analyze_call_transcript(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Deep Phishing Worker analysis over an entire live-call transcript.

    Joins transcribed utterances into a single content blob, then runs the
    standard phishing pipeline (entity extraction, RAG pattern match, rule +
    LLM analysis) with the agentic web-research enhancement step, producing an
    in-depth verdict (with optional external research evidence) for a CALL
    session.
    """
    lines: list[str] = []
    for utt in transcript:
        speaker = str(utt.get("speaker", "CALLER"))
        text = str(utt.get("text") or utt.get("utterance", "")).strip()
        if text:
            lines.append(f"[{speaker}] {text}")
    content = "\n".join(lines)

    if not content.strip():
        return {
            "phishing_finding": WorkerFinding(
                worker="phishing",
                score=0,
                confidence=0.0,
                evidence=["No speech transcript available for deep analysis."],
            ).model_dump(),
            "extracted_entities": {},
            "research": {
                "queried": False,
                "decision": "skipped",
                "reasoning": "no transcript",
                "queries": [],
                "web_hits": [],
            },
        }

    state: GraphState = {
        "trigger_type": "CALL",
        "trigger_payload": {
            "phishing_material": {
                "source_type": "TRANSCRIPT",
                "content": content,
            }
        },
    }
    return phishing_worker_node(state)
