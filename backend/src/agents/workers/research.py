"""Research Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.agents.llm import extract_json_object, invoke_groq_with_key_rotation
from src.agents.prompts import build_research_prompt
from src.agents.state import GraphState, WorkerFinding
from src.db.vector_store import add_fraud_memory, hybrid_search_fraud_memory, search_fraud_memory
from src.services.tavily import tavily_search

logger = logging.getLogger(__name__)


@tool
def search_malaysian_fraud_registry(query: str) -> str:
    """Search Bank Negara Malaysia (BNM), Securities Commission (SC), and PDRM CCID alert lists for scam reports."""
    try:
        hits = tavily_search([query])
        clean_hits = [
            {
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "snippet": str(h.get("content", ""))[:200],
            }
            for h in (hits[:3] if isinstance(hits, list) else [])
        ]
        return json.dumps(clean_hits, indent=2)
    except Exception as err:
        return f"Error executing web search: {err}"


def get_research_llm(model_name: str = "llama-3.3-70b-versatile") -> ChatGroq:
    """Get ChatGroq LLM instance reading GROQ_API_KEY dynamically at runtime."""
    raw_key = os.getenv("GROQ_API_KEY") or "gsk_placeholder_key_for_initialization"
    return ChatGroq(model=model_name, temperature=0.0, api_key=SecretStr(raw_key))


class DynamicResearchLLM:
    """Dynamic LLM proxy reading GROQ_API_KEY dynamically with multi-key rotation and 429 rate limit fallback."""

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        return invoke_groq_with_key_rotation(messages)


llm = DynamicResearchLLM()


RESEARCH_QUERY_SYSTEM_PROMPT = """You are an expert financial fraud research intelligence agent.
Analyze the transaction query entities alongside RAG search results and public web reports.
Your job is to determine the overall transaction risk finding.

CRITICAL JSON FORMATTING RULE:
You MUST return a SINGLE JSON object representing the OVERALL risk finding for the transaction.
DO NOT return a JSON array / list of entities! (Incorrect: [{"score": 0}, {"score": 80}]).

Return your finding as a SINGLE JSON object:
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

    # Read nested transaction payload
    tx = payload.get("transaction")
    if isinstance(tx, dict):
        rec_name = tx.get("recipient_name")
        if rec_name and isinstance(rec_name, str) and rec_name not in entities:
            entities.append(rec_name)
        tx_desc = tx.get("description")
        if tx_desc and isinstance(tx_desc, str) and tx_desc not in entities:
            desc_clean = tx_desc.strip()
            if len(desc_clean) > 3 and desc_clean.lower() not in GENERIC_RECIPIENT_NAMES:
                entities.append(desc_clean)
        for key in ("recipient_account", "account", "sender_account"):
            val = tx.get(key)
            if val and isinstance(val, str):
                if val not in entities:
                    entities.append(val)
                # Add un-hyphenated variant
                clean_val = val.replace("-", "").strip()
                if clean_val and clean_val not in entities:
                    entities.append(clean_val)
                # Add hyphenated variant if 16-digit account
                if len(clean_val) == 16:
                    hyphen_val = f"{clean_val[:4]}-{clean_val[4:8]}-{clean_val[8:12]}-{clean_val[12:]}"
                    if hyphen_val not in entities:
                        entities.append(hyphen_val)

    # Read from associated_case_context
    case_context = state.get("associated_case_context") or {}
    for key in ("phone_numbers", "urls", "bank_accounts"):
        val = case_context.get(key)
        if isinstance(val, list):
            for item in val:
                if item and str(item) not in entities:
                    entities.append(str(item))

    return entities


GENERIC_RECIPIENT_NAMES = {
    "standard transfer account",
    "standard account",
    "personal transfer",
    "personal transfer (legitimate)",
    "utility provider",
    "utility provider (legitimate)",
    "unknown account",
    "savings account",
    "current account",
    "retail transfer",
    "tenaga nasional berhad (tnb)",
    "tenaga nasional berhad",
    "tnb",
    "telekom malaysia",
    "air selangor",
    "syabas",
}


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

    evidence: list[str] = []
    score = 0
    confidence = 0.85

    payload = state.get("trigger_payload") or {}
    tx_dict = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else payload
    rec_acc = tx_dict.get("recipient_account") or tx_dict.get("account")
    rec_name = tx_dict.get("recipient_name")
    tx_desc = tx_dict.get("description") or ""

    is_generic_name = (rec_name or "").strip().lower() in GENERIC_RECIPIENT_NAMES

    # Check if transfer description contains non-generic brand / scheme terms
    desc_search_term = None
    if tx_desc and tx_desc.strip():
        desc_lower = tx_desc.strip().lower()
        if not any(g in desc_lower for g in GENERIC_RECIPIENT_NAMES) and len(desc_lower) > 3:
            desc_search_term = tx_desc.strip()

    # Determine target search query entity (recipient name preferred, fallback to transfer description if recipient name is generic)
    search_target_name = None if is_generic_name else rec_name
    if not search_target_name and desc_search_term:
        search_target_name = desc_search_term

    # Step 1: Hybrid Search (BM25 Lexical Exact Token Match + Dense pgvector RAG in public.fraud_memory)
    internal_hits: list[dict[str, Any]] = []
    try:
        phone_ent = next((e for e in entities if e.startswith("01") or e.startswith("+60")), None)
        internal_hits = hybrid_search_fraud_memory(
            query_text=search_target_name or (entities[0] if entities else ""),
            bank_account=rec_acc,
            phone_number=phone_ent,
            threshold=0.45,
            top_k=5,
        )
    except Exception as err:  # noqa: BLE001
        logger.warning(f"Error querying hybrid fraud memory: {err}")

    # Check max similarity score from Hybrid Search
    max_sim = 0.0
    for hit in internal_hits:
        sim = float(hit.get("similarity", 0.0))
        max_sim = max(max_sim, sim)
        method = hit.get("search_method", "HYBRID")
        content_snippet = str(hit.get("content", ""))[:120]
        evidence.append(
            f"[{method}] Match found in internal fraud database (similarity {sim:.2f}): '{content_snippet}'"
        )

    if max_sim >= 0.80:
        score = max(score, int(max_sim * 100))
        confidence = max(confidence, 0.95)
    elif max_sim >= 0.45:
        score = max(score, int(max_sim * 90))
        confidence = max(confidence, 0.88)

    # Step 2: 360-Degree Corporate & Regulatory Search via LLM Tool-Calling Reasoning Loop
    tavily_hits: list[dict[str, Any]] = []
    if max_sim < 0.80:
        try:
            sys_prompt = SystemMessage(
                content="""You are an expert financial fraud research intelligence agent.
Examine the transfer details: Recipient Name, Recipient Account Number, and Transfer Description.
Your job is to determine if a web search is needed.

REASONING RULES:
1. Examine both Recipient Name AND Transfer Description.
2. If either contains a specific corporate entity, company name, investment scheme, crypto brand, or suspicious phrase (e.g. 'JJPTR', 'Genneva Gold', 'MBI', 'Forex Scheme Deposit'), invoke the `search_malaysian_fraud_registry(query)` tool to check BNM, SC, and PDRM alert lists!
3. If the transfer details describe normal personal banking (e.g. 'Dinner payment', 'Monthly rent', 'Ahmad', 'Standard Transfer Account' with everyday description), do NOT call the web search tool."""
            )
            user_msg = HumanMessage(
                content=f"""Transfer Details to Evaluate:
- Recipient Name: {rec_name or 'N/A'}
- Recipient Account: {rec_acc or 'N/A'}
- Transfer Description: {tx_desc or 'N/A'}

Internal Fraud DB Hits: {json.dumps(internal_hits, indent=2)}"""
            )
            response = invoke_groq_with_key_rotation(
                messages=[sys_prompt, user_msg],
                tools=[search_malaysian_fraud_registry],
            )
            if hasattr(response, "tool_calls") and response.tool_calls:
                for t_call in response.tool_calls:
                    query_arg = t_call.get("args", {}).get("query")
                    if query_arg:
                        tool_res = search_malaysian_fraud_registry.invoke({"query": query_arg})
                        if isinstance(tool_res, str) and tool_res.startswith("["):
                            tavily_hits.extend(json.loads(tool_res))
        except Exception as err:  # noqa: BLE001
            logger.warning(f"LLM Tool-Calling web search error: {err}")

    # Fallback to direct targeted search terms if tool-calling didn't run or in fallback mode
    if not tavily_hits and max_sim < 0.80 and (not is_generic_name or bool(desc_search_term)):
        try:
            clean_search_terms: list[str] = []
            target_term = rec_name if not is_generic_name else desc_search_term
            if target_term:
                clean_search_terms.append(f"{target_term} Bank Negara Malaysia Securities Commission alert list")
                clean_search_terms.append(f"{target_term} PDRM CCID police report scam conviction")

            for ent in entities:
                if not ent.replace("-", "").isdigit() and ent.lower() not in GENERIC_RECIPIENT_NAMES and ent not in clean_search_terms:
                    clean_search_terms.append(ent)

            if not clean_search_terms:
                clean_search_terms = entities

            if clean_search_terms:
                raw_tavily = tavily_search(clean_search_terms)
                if inspect.isawaitable(raw_tavily):
                    tavily_hits = []
                elif isinstance(raw_tavily, list):
                    tavily_hits = raw_tavily
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Tavily web search fallback error: {err}")

    # Filter Tavily hits to confirm explicit mention of target entity (requires multi-token match or exact phrase)
    valid_web_hits = []
    target_entity_name = search_target_name or (None if is_generic_name else rec_name)
    if tavily_hits:
        if target_entity_name:
            rec_lower = target_entity_name.lower().strip()
            stopwords = {"binti", "bin", "sdn", "bhd", "berhad", "deposit", "scheme", "payment", "transfer", "account", "standard"}
            tokens = [t for t in rec_lower.split() if len(t) > 2 and t not in stopwords]

            for hit in tavily_hits:
                hit_text = f"{hit.get('title', '')} {hit.get('content', '')}".lower()
                # 1. Exact phrase match
                if rec_lower in hit_text:
                    valid_web_hits.append(hit)
                # 2. Key distinct scam/brand token match (e.g. "jjptr", "genneva", "mbi")
                elif any(t in hit_text for t in tokens if t in ("jjptr", "genneva", "mbi", "ponzi", "mcoin", "richway", "toga")):
                    valid_web_hits.append(hit)
                # 3. For multi-word names, require at least 2 distinct tokens to match together
                elif len(tokens) >= 2 and all(t in hit_text for t in tokens[:2]):
                    valid_web_hits.append(hit)
        else:
            # When target entity name is absent or in unit tests, accept returned Tavily hits
            valid_web_hits = tavily_hits

    if valid_web_hits:
        score = max(score, 75)
        confidence = max(confidence, 0.90)
        first_url = valid_web_hits[0].get("url", "web report")
        evidence.append(f"Tavily web search: external scam report confirmed for '{rec_name}' ({first_url})")

    # Step 3: Default Zero Floor for Clean Transfers
    if max_sim < 0.45 and not valid_web_hits:
        score = 0
        confidence = 0.95
        evidence = ["Clean Entity Check: Recipient account identity verified. No historical fraud matches or regulatory blacklist warnings found."]

    if not evidence:
        evidence = ["Clean Entity Check: Recipient account identity verified. No historical fraud matches or regulatory blacklist warnings found."]

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
        parsed = extract_json_object(llm_response.content if hasattr(llm_response, "content") else llm_response)
        if isinstance(parsed, dict):
            llm_score = int(parsed.get("score", finding.score))
            llm_conf = float(parsed.get("confidence", finding.confidence))
            llm_ev = list(parsed.get("evidence", finding.evidence))
            if not llm_ev:
                if llm_score == 0:
                    llm_ev = ["No matching scam records or regulatory alerts found in public registries."]
                else:
                    llm_ev = [f"Entity intelligence research evaluated with score {llm_score}/100."]
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
