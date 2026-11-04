"""Phishing Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.agents.llm import DEEPSEEK_BASE_URL, extract_json_object, invoke_groq_with_key_rotation
from src.agents.prompts import (
    build_phishing_analysis_prompt,
    build_phishing_research_planner_prompt,
    get_phishing_playbook,
)
from src.agents.state import GraphState, WorkerFinding
from src.db.vector_store import search_fraud_memory
from src.services.tavily import tavily_search
from src.services.vision import analyze_image, extract_text_from_image

logger = logging.getLogger(__name__)


def get_phishing_llm(model_name: str = "deepseek-chat") -> ChatOpenAI:
    """Get ChatOpenAI LLM instance (DeepSeek) reading DEEPSEEK_API_KEY dynamically at runtime."""
    raw_key = os.getenv("DEEPSEEK_API_KEY") or "sk-placeholder_key_for_initialization"
    return ChatOpenAI(
        model=model_name,
        temperature=0.0,
        api_key=SecretStr(raw_key),
        base_url=DEEPSEEK_BASE_URL,
    )


class DynamicPhishingLLM:
    """Dynamic LLM proxy using DeepSeek with multi-key rotation and fallback."""

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
5. Social Engineering / Financial Fraud: Impersonating a friend, relative, or authority figure and pressing for urgent money transfers, "investment" payments, card details, OTPs, or forbidding the victim from hanging up.

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


# ---------------------------------------------------------------------------
# Phishing Detection Playbook (single source of truth)
# ---------------------------------------------------------------------------
# backend/skills/phishing_detection_playbook.md drives BOTH detection paths:
#   - the deterministic rule engine reads its keyword columns
#   - the LLM system prompt reads its archetype guidance columns
# If the skill file is missing or malformed we fall back to the built-in
# keyword lists below so the pipeline never degrades.
_DEFAULT_HEAVY_DEMAND = [
    "transfer", "wire", "bank account", "safe account", "akaun selamat",
    "otp", "card number", "card password", "card pin", "send money",
    "deposit", "withdraw", "top up", "topup", "remit",
]
_DEFAULT_LIGHT_DEMAND = [
    "don't hang up", "do not hang up", "must not disconnect", "arrest",
    "jail", "investment", "invest", "friend", "relative", "sister",
    "brother", "urgent", "right now", "asap", "immediately", "pay",
    "payment", "money", "cash", "redeem", "prize", "won",
]
_PLAYBOOK_DEFAULT_GUIDANCE = """- **Friend / Relative Emergency**: Impersonating a friend or relative in distress and pressing for an urgent money transfer.
- **Bank Impersonation**: Pretending to be a bank and demanding funds be moved to a "safe account", or harvesting card / OTP details.
- **Government / Authority**: Impersonating police, tax, or court and threatening arrest unless a fine or bail is paid immediately."""

_PHISHING_PLAYBOOK_CACHE: dict[str, Any] | None = None
_PHISHING_PLAYBOOK_CACHE_TS: float = 0.0
_LEARNED_MERGE_TTL_SECONDS: float = 45.0


def _parse_phishing_playbook(text: str) -> dict[str, Any]:
    """Parse the Detection Archetypes table into keyword lists + LLM guidance.

    Expected columns:
        | ID | Archetype | Typical script phrases | Heavy money-demand keywords |
        | Light social-engineering / urgency keywords | LLM guidance |

    Returns dict with keys ``heavy``, ``light``, ``guidance``. Malformed rows
    are skipped.
    """
    heavy: list[str] = []
    light: list[str] = []
    guidance: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 6:
            continue
        raw_id = parts[0].replace("*", "").strip()
        if raw_id.upper().startswith("ID") or not raw_id:
            continue
        heavy += [k.strip().lower() for k in parts[3].split(",") if k.strip()]
        light += [k.strip().lower() for k in parts[4].split(",") if k.strip()]
        if parts[5].strip():
            guidance.append(f"- **{parts[1].strip()}**: {parts[5].strip()}")

    return {
        "heavy": sorted(set(heavy)),
        "light": sorted(set(light)),
        "guidance": "\n".join(guidance),
    }


def get_phishing_playbook_data() -> dict[str, Any]:
    """Load (once) and parse the phishing detection playbook skill.

    Returns a dict with keys ``heavy`` (list[str]), ``light`` (list[str]),
    ``guidance`` (str) and ``raw`` (str). Falls back to built-in defaults if
    the skill file is missing or unparseable.

    User-confirmed ``learned_keywords`` (from adaptive labeling) are merged
    into the heavy/light keyword lists with a short TTL so new scam tactics
    take effect within about a minute.
    """
    global _PHISHING_PLAYBOOK_CACHE, _PHISHING_PLAYBOOK_CACHE_TS
    if _PHISHING_PLAYBOOK_CACHE is None or _PHISHING_PLAYBOOK_CACHE_TS == 0.0:
        try:
            raw = get_phishing_playbook()
            parsed = _parse_phishing_playbook(raw)
            if not parsed["heavy"] or not parsed["light"]:
                raise ValueError("playbook table has no keyword rows")
            parsed["raw"] = raw
            parsed["_learned_merged"] = False
            _PHISHING_PLAYBOOK_CACHE = parsed
            _PHISHING_PLAYBOOK_CACHE_TS = time.monotonic()
        except Exception as err:  # noqa: BLE001
            logger.debug(f"Phishing playbook unavailable, using built-in defaults: {err}")
            _PHISHING_PLAYBOOK_CACHE = {
                "heavy": list(_DEFAULT_HEAVY_DEMAND),
                "light": list(_DEFAULT_LIGHT_DEMAND),
                "guidance": _PLAYBOOK_DEFAULT_GUIDANCE,
                "raw": "",
                "_learned_merged": False,
            }
            _PHISHING_PLAYBOOK_CACHE_TS = time.monotonic()

    # Re-merge learned keywords every TTL window so labels propagate quickly.
    if not _PHISHING_PLAYBOOK_CACHE.get("_learned_merged") or (
        time.monotonic() - _PHISHING_PLAYBOOK_CACHE_TS > _LEARNED_MERGE_TTL_SECONDS
    ):
        _PHISHING_PLAYBOOK_CACHE = _merge_learned_keywords(_PHISHING_PLAYBOOK_CACHE)
        _PHISHING_PLAYBOOK_CACHE = _merge_published_patch(_PHISHING_PLAYBOOK_CACHE)
        _PHISHING_PLAYBOOK_CACHE_TS = time.monotonic()

    return _PHISHING_PLAYBOOK_CACHE


def _merge_published_patch(playbook: dict[str, Any]) -> dict[str, Any]:
    """Union published ``phishing_playbook_patch`` keywords into the playbook.

    The pack-tier counterpart of ``phone_agent_core`` for this worker: an
    approved campaign compiles a patch, and the next analysis scans with it.
    Reading is also what writes the consumption receipt, so the console's
    ``consumed_by: phishing_worker`` is earned here rather than asserted by the
    propagator on this agent's behalf.
    """
    merged = dict(playbook)
    try:
        from src.agents.workers.artifact_feed import load_phishing_patch

        patch = load_phishing_patch()
    except Exception as err:  # noqa: BLE001 - detection must not depend on it
        logger.debug(f"published phishing patch merge skipped: {err}")
        return merged

    if not (patch.get("heavy") or patch.get("light") or patch.get("url_patterns")):
        return merged

    heavy = set(str(k).lower().strip() for k in (merged.get("heavy") or []))
    light = set(str(k).lower().strip() for k in (merged.get("light") or []))
    heavy |= set(patch.get("heavy") or [])
    light |= set(patch.get("light") or [])
    merged["heavy"] = sorted(heavy)
    merged["light"] = sorted(light)
    if patch.get("url_patterns"):
        existing = {str(p).lower() for p in (merged.get("url_patterns") or [])}
        merged["url_patterns"] = sorted(existing | {str(p).lower() for p in patch["url_patterns"]})
    merged["_published_patch_merged"] = True
    logger.debug(
        f"playbook merged with published patches: heavy={len(heavy)} light={len(light)}"
    )
    return merged


def _merge_learned_keywords(playbook: dict[str, Any]) -> dict[str, Any]:
    """Union learned_keywords rows (heavy/light) into the playbook keyword lists."""
    merged = dict(playbook)
    merged["_learned_merged"] = True
    try:
        from src.db.supabase import fetch_learned_keywords

        rows = fetch_learned_keywords()
        if not rows:
            return merged
        heavy = set(str(k).lower().strip() for k in (merged.get("heavy") or []))
        light = set(str(k).lower().strip() for k in (merged.get("light") or []))
        for row in rows:
            kw = str(row.get("keyword") or "").strip().lower()
            ktype = str(row.get("keyword_type") or "light").strip().lower()
            if not kw:
                continue
            if ktype == "heavy":
                heavy.add(kw)
            else:
                light.add(kw)
        merged["heavy"] = sorted(heavy)
        merged["light"] = sorted(light)
        logger.debug(
            f"playbook merged with learned_keywords: heavy={len(heavy)} light={len(light)}"
        )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"learned keyword merge skipped: {err}")
    return merged


def _build_phishing_system_prompt() -> str:
    """PHISHING_SYSTEM_PROMPT + the playbook's archetype guidance section."""
    base = PHISHING_SYSTEM_PROMPT
    guidance = (get_phishing_playbook_data().get("guidance") or "").strip()
    if not guidance:
        return base
    return base + "\n\n## Scam Archetype Playbook (TranSafe skill)\n" + guidance


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

    # Financial-demand / social-engineering signals — common in live-call
    # transcripts (friend/relative scams, urgent money movement, OTP/card
    # harvesting, hangup coercion). Distinct from bank-impersonation phishing.
    # Keywords come from the phishing detection playbook skill (single source
    # of truth shared with the LLM prompt); defaults apply if it is missing.
    playbook = get_phishing_playbook_data()
    heavy_demand = playbook["heavy"]
    light_demand = playbook["light"]
    heavy_hits = [kw for kw in heavy_demand if kw in lower_text]
    light_hits = [kw for kw in light_demand if kw in lower_text]
    amount_hit = bool(
        re.search(
            r"\b(rm|usd|us\$|\$|myr)\s?\d{2,}|"
            r"\d{2,}\s?(?:dollars?|ringgit|bucks|thousand)|"
            r"(?:thousand|million|hundred)\s?(?:dollars?|ringgit|bucks|rm)?",
            lower_text,
        )
    )
    if heavy_hits:
        # A bare mention ("can you transfer the file?") is weak; corroboration
        # from urgency / coercion / social-engineering / an amount is the
        # classic scam pattern and pushes the verdict decisively HIGH.
        corroborated = bool(light_hits) or amount_hit
        score += len(heavy_hits) * (35 if corroborated else 15)
        evidence.append(
            f"Financial demand detected ({'with corroborating signals' if corroborated else 'mention only'}): "
            f"{', '.join(heavy_hits)}"
        )
    if light_hits:
        score += len(light_hits) * 10
        evidence.append(f"Social-engineering / urgency signals: {', '.join(light_hits)}")

    # URL anomalies (.xyz, .top, unencrypted http)
    if "http://" in lower_text or ".xyz" in lower_text or ".top" in lower_text or ".site" in lower_text:
        score += 35
        evidence.append("Suspicious URL TLD or unencrypted HTTP link detected")

    # Credential-harvesting / lookalike-login signals — covers phishing pages
    # mimicking PayPal/Apple/Netflix/bank login screens (email+password
    # fields, "verify your account" flows) that the bank-impersonation
    # keywords above do not match.
    login_keywords = [
        "password", "log in", "login", "sign in", "signin", "sign into",
        "verify your account", "verify account", "account locked",
        "account has been locked", "secure your account",
        "update your information", "confirm your identity",
        "email address", "re-enter", "credentials", "deactivated",
        "unusual activity", "suspicious activity",
    ]
    login_hits = [kw for kw in login_keywords if kw in lower_text]
    if login_hits:
        score += len(login_hits) * 12
        evidence.append(
            f"Credential-harvesting login-form signals: {', '.join(login_hits)}"
        )

    # Brand impersonation: a well-known brand alongside login-form signals
    # strongly suggests a lookalike credential-harvesting page.
    brand_keywords = [
        "paypal", "apple", "icloud", "netflix", "microsoft", "outlook",
        "dbs", "citibank", "hsbc", "standard chartered", "shopee",
        "lazada", "grab", "facebook", "instagram", "whatsapp", "wechat",
        "maybank", "cimb", "rhb", "bank negara", "pos malaysia",
    ]
    brand_hits = [b for b in brand_keywords if b in lower_text]
    if brand_hits and login_hits:
        score += 25
        evidence.append(
            f"Brand impersonation ({', '.join(brand_hits)}) combined with "
            "login-form signals — classic credential phishing"
        )

    # Embedded URL/domain that is NOT the claimed brand's own domain — e.g. a
    # PayPal login page hosted on an unrelated domain (kmacraeandson.co.uk).
    # Bare URLs are suspicious even without a brand mention.
    embedded_urls = [
        u.rstrip(".,;:!?)\"]'")
        for u in re.findall(r"https?://[^\s]+|www\.[^\s]+", lower_text)
    ]
    if embedded_urls:
        suspicious_urls = [
            u for u in embedded_urls
            if not brand_hits
            or not any(f"{b}." in u or f"/{b}." in u for b in brand_hits)
        ]
        if suspicious_urls:
            score += 25
            evidence.append(
                "Embedded link/domain unrelated to the claimed brand: "
                f"{', '.join(suspicious_urls[:3])}"
            )

    # Browser security warning text captured in the screenshot.
    if "dangerous" in lower_text:
        score += 20
        evidence.append("Browser 'Dangerous' security warning present in the page")

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
    strong_rag = any(float(h.get("similarity") or 0.0) >= 0.80 for h in rag_hits)

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
            SystemMessage(content=_build_phishing_system_prompt()),
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
    # Canonical payload shape is `material` (FastAPI PhishingTriggerRequest).
    # Fall back to the legacy `phishing_material` key (scammer simulator) and
    # finally to the flat payload (unit-test fixtures) so every caller works.
    phish_material = payload.get("material") or payload.get("phishing_material") or payload

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
            "phishing_ocr_text": "",
            "phishing_image_description": "",
        }

    # Stage 1: image analysis for IMAGE material — qwen3.6-27b extracts the
    # text AND describes visual phishing indicators (fake branding, urgency
    # banners, lookalike login forms, QR codes). Falls back to Groq llama vision
    # OCR, then to the raw content.
    is_image = source in ("IMAGE", "SCREENSHOT")
    image_analysis: dict[str, str] = {}
    if is_image and raw_content:
        try:
            image_analysis = analyze_image(raw_content)
            ocr_text = (image_analysis.get("extracted_text") or "").strip()
            description = (image_analysis.get("description") or "").strip()
            if ocr_text:
                analysis_content = ocr_text
            elif description:
                analysis_content = description
            if description:
                analysis_content = (
                    f"{analysis_content}\n\n[Visual description: {description}]"
                    if analysis_content
                    else f"[Visual description: {description}]"
                )
        except Exception as err:  # noqa: BLE001
            logger.warning(f"qwen image analysis failed, falling back to OCR: {err}")
            try:
                ocr_res = extract_text_from_image(raw_content)
                if isinstance(ocr_res, str) and ocr_res.strip():
                    analysis_content = ocr_res.strip()
            except Exception as err2:  # noqa: BLE001
                logger.warning(f"Groq Vision OCR failed, using raw content: {err2}")

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
            SystemMessage(content=_build_phishing_system_prompt()),
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

    # Stage 4: Agentic research enhancement (planner-gated, on-demand web search).
    # For PHISHING material triggers the dedicated Research Worker runs the web
    # verification (Stage 2 of the documented design) — skip the internal search
    # here to avoid duplicate Tavily queries. CALL transcripts keep it.
    if state.get("trigger_type") == "PHISHING":
        research = {
            "queried": False,
            "decision": "delegated-to-research-worker",
            "reasoning": "Research Worker verifies web evidence for PHISHING material triggers.",
            "queries": [],
            "web_hits": [],
        }
    else:
        research = _run_research_enhancement(analysis_content, extracted_entities, RAG_hits, finding)
        if research.get("queried") and research.get("web_hits"):
            finding = _final_verdict_with_web(source, analysis_content, finding, research)

    # Surface the visual-indicator description as evidence so the explanation
    # panel shows why the screenshot was flagged.
    if is_image and image_analysis.get("description"):
        finding.evidence.insert(
            0, f"Visual indicators in screenshot: {image_analysis['description']}"
        )

    return {
        "phishing_finding": finding.model_dump(),
        "extracted_entities": extracted_entities,
        "research": research,
        "phishing_ocr_text": analysis_content if is_image else "",
        "phishing_image_description": (image_analysis.get("description") or "") if is_image else "",
    }


def analyze_call_transcript(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Deep Phishing Worker analysis over an entire live-call transcript.

    Joins transcribed utterances into a single content blob, then runs the
    standard phishing pipeline (entity extraction, RAG pattern match, rule +
    LLM analysis) with the agentic web-research enhancement step, producing an
    in-depth verdict (with optional external research evidence) for a CALL
    session.
    """
    # Only the caller's speech determines the fraud verdict. The AUTO_TALK
    # agent's own anchor-question probes (and the customer's replies) must not
    # inflate the score — e.g. the agent asking "have you been asked to
    # transfer money?" is not evidence of fraud.
    ignored_speakers = {
        "TRANSAFE_AI", "AGENT", "TRANSAFE", "BOT", "ASSISTANT", "COPILOT",
        "CUSTOMER", "USER", "VICTIM", "TARGET",
    }
    lines: list[str] = []
    for utt in transcript:
        speaker = str(utt.get("speaker", "CALLER")).upper()
        text = str(utt.get("text") or utt.get("utterance", "")).strip()
        if not text:
            continue
        if speaker in ignored_speakers:
            continue
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
