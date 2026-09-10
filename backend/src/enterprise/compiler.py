"""Artifact compiler (pack tier) — L4.

Input: an **approved** campaign. Output: concrete, versioned, executable
artifacts (01_upgrade_plan.md §7.1, 03_artifact_registry.md §4).

The compiler is a single DeepSeek call with a strict output schema. It is given
the campaign MO summary, its novel phrases, its resolved entity list and **the
current version of each target artifact**, so it emits a *patch in context*
rather than a from-scratch rewrite that would clobber existing rules.

Two hard guarantees:

* **The approval gate is real.** :func:`compile_approved_campaign` re-reads the
  campaign row and refuses to compile anything a human has not approved.
* **The demo survives a dead API key.** Every LLM path falls back to
  :func:`_compiler_fallback`, which builds the same five artifacts from
  structured data alone.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm import extract_json_object, invoke_deepseek_with_key_rotation
from src.db.vector_store import get_supabase_client

logger = logging.getLogger(__name__)

# The five pack-tier artifact types the compiler must always produce.
PACK_ARTIFACT_TYPES: tuple[str, ...] = (
    "campaign_pack",
    "phishing_playbook_patch",
    "txn_rule",
    "compliance_brief",
    "cs_advisory",
)

# Campaign states a human has signed off on. Nothing else may be compiled.
APPROVED_STATUSES: frozenset[str] = frozenset({"APPROVED", "ACTIVE"})

COMPILER_SYSTEM_PROMPT = """\
You are a fraud defence artifact compiler. Given an approved campaign's \
MO summary, novel phrases, entity list, and the current version of each \
target artifact, you produce concrete, versioned artifacts.

Rules:
1. Campaign packs contain INSTANCE knowledge for ONE campaign only.
2. Never clobber existing rules — emit a patch in context.
3. Every indicator must trace to a cited case.
4. Return ONLY a JSON object with the artifact types as keys.
5. NEVER include victim-side identity in any artifact. Indicators describe the
   ATTACKER: mule accounts, scammer phones, malicious domains. A victim's name,
   phone, account, NRIC, email or quoted speech must never appear — least of
   all in the free-text `compliance_brief` and `cs_advisory`. Published
   artifacts are served to partner banks, legal and compliance, who are
   entitled to the attack pattern and never to the people it was worked on.
   Refer to victims only as "the customer" or "the affected party".

Schema:
{
  "campaign_pack": {
    "campaign": "SCAM-0XX",
    "name": "...",
    "high_risk_phrases": [{"text": "...", "lang": "ms", "case_count": 1}],
    "indicators": {"accounts": [], "domains": [], "phones": []},
    "anchor_question": "...",
    "response_strategy": "deny_transfer + verify_callback + escalate",
    "cited_cases": []
  },
  "phishing_playbook_patch": {
    "campaign": "SCAM-0XX",
    "heavy_keywords": [], "light_keywords": [], "url_patterns": [],
    "risk_boost": 20
  },
  "txn_rule": {
    "campaign": "SCAM-0XX",
    "rules": [{"action": "BLOCK", "condition": {"field": "recipient_account",
               "op": "in", "values": []}, "reason": "..."}]
  },
  "compliance_brief": "markdown string",
  "cs_advisory": "markdown string"
}
"""


# ── Public API ───────────────────────────────────────────────────────────────
def compile_campaign(
    campaign_id: str,
    campaign_data: dict[str, Any],
    mo_fingerprints: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    current_artifacts: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Compile an approved campaign into the five pack-tier artifacts.

    Args:
        campaign_id: UUID of the approved campaign.
        campaign_data: Campaign row (``code``, ``name``, ``confidence``, …).
        mo_fingerprints: MO fingerprint dicts for the cases in the campaign.
        entities: Resolved entities (PHONE, ACCOUNT, URL, DOMAIN, NAME).
        current_artifacts: ``artifact_name -> current content``, so the LLM
            patches in context instead of rewriting.

    Returns:
        Dict of ``artifact_type -> content`` covering all five pack types.
        Never ``None`` in practice — an LLM failure degrades to the
        deterministic fallback.
    """
    mo_summary = _summarise_mo(mo_fingerprints)
    entity_summary = _summarise_entities(entities)
    current_artifacts_str = json.dumps(current_artifacts or {}, indent=2, ensure_ascii=False)

    user_prompt = f"""Campaign ID: {campaign_id}
Campaign code: {campaign_data.get('code', 'UNKNOWN')}
Campaign name: {campaign_data.get('name', 'UNKNOWN')}
Confidence: {campaign_data.get('confidence', 0)}

MO Summary:
{mo_summary}

Entities:
{entity_summary}

Current artifact versions (patch in context, do not clobber):
{current_artifacts_str}

Compile all 5 pack-tier artifacts for this campaign."""

    messages = [
        SystemMessage(content=COMPILER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    fallback = _compiler_fallback(campaign_data, mo_fingerprints, entities)

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        compiled = extract_json_object(getattr(response, "content", response))
    except Exception:
        logger.exception("compiler: LLM call failed for campaign %s", campaign_id)
        return fallback

    if not compiled:
        logger.error("compiler: unparseable LLM JSON for campaign %s", campaign_id)
        return fallback

    return _merge_with_fallback(compiled, fallback)


def compile_approved_campaign(
    campaign_id: str,
    current_artifacts: dict[str, str] | None = None,
    client: Any | None = None,
) -> dict[str, Any] | None:
    """Load an **approved** campaign from Postgres and compile it.

    This is the enforcement point of the governance rule "nothing autonomous
    ever reaches a customer": a campaign that no human approved is never
    compiled, whatever the caller asks for.

    Args:
        campaign_id: UUID of the campaign.
        current_artifacts: Optional current artifact bodies for patch-in-context.
        client: Optional injected Supabase client.

    Returns:
        Compiled artifacts, or ``None`` when the campaign is missing or has not
        been approved.
    """
    supabase = client if client is not None else get_supabase_client()

    campaign = fetch_campaign(campaign_id, client=supabase)
    if campaign is None:
        logger.warning("compiler: campaign %s not found", campaign_id)
        return None

    status = str(campaign.get("status", ""))
    if status not in APPROVED_STATUSES:
        logger.warning(
            "compiler: refusing to compile campaign %s in status %s (approval gate)",
            campaign_id,
            status or "UNKNOWN",
        )
        return None

    case_ids = fetch_campaign_case_ids(campaign_id, client=supabase)
    mo_fingerprints = fetch_mo_fingerprints(case_ids, client=supabase)
    entities = fetch_campaign_entities(case_ids, client=supabase)

    compiled = compile_campaign(
        campaign_id=campaign_id,
        campaign_data=campaign,
        mo_fingerprints=mo_fingerprints,
        entities=entities,
        current_artifacts=current_artifacts,
    )
    if compiled and isinstance(compiled.get("campaign_pack"), dict):
        pack = compiled["campaign_pack"]
        pack.setdefault("cited_cases", case_ids)
        if not pack.get("cited_cases"):
            pack["cited_cases"] = case_ids
    return compiled


# ── Supabase readers (all failure-tolerant) ──────────────────────────────────
def fetch_campaign(campaign_id: str, client: Any | None = None) -> dict[str, Any] | None:
    """Fetch one campaign row.

    Args:
        campaign_id: Campaign UUID.
        client: Optional injected Supabase client.

    Returns:
        The campaign row, or ``None`` when absent / on failure.
    """
    try:
        supabase = client if client is not None else get_supabase_client()
        result = supabase.table("campaigns").select("*").eq("id", campaign_id).execute()
        rows = list(getattr(result, "data", None) or [])
    except Exception:
        logger.exception("compiler: campaign lookup failed for %s", campaign_id)
        return None
    return dict(rows[0]) if rows else None


def fetch_approved_campaigns_with_mo(
    limit: int = 10,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Return approved campaigns, each with the MO fingerprints of its cases.

    This is the generaliser's input: it may only reason over campaigns a human
    has approved.

    Args:
        limit: Maximum number of campaigns.
        client: Optional injected Supabase client.

    Returns:
        List of campaign dicts carrying a ``mo_fingerprints`` list. Empty on
        failure.
    """
    try:
        supabase = client if client is not None else get_supabase_client()
        result = (
            supabase.table("campaigns")
            .select("id, code, name, status, mo_summary")
            .in_("status", ["APPROVED", "ACTIVE"])
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        campaigns = [dict(row) for row in (getattr(result, "data", None) or [])]
    except Exception:
        logger.exception("compiler: approved-campaign lookup failed")
        return []

    for campaign in campaigns:
        case_ids = fetch_campaign_case_ids(str(campaign.get("id", "")), client=client)
        campaign["mo_fingerprints"] = fetch_mo_fingerprints(case_ids, client=client)
    return campaigns


def fetch_campaign_case_ids(campaign_id: str, client: Any | None = None) -> list[str]:
    """Return the case IDs that belong to a campaign.

    Args:
        campaign_id: Campaign UUID.
        client: Optional injected Supabase client.

    Returns:
        Sorted list of case UUIDs; empty on failure.
    """
    try:
        supabase = client if client is not None else get_supabase_client()
        result = (
            supabase.table("campaign_cases")
            .select("case_id")
            .eq("campaign_id", campaign_id)
            .execute()
        )
        rows = list(getattr(result, "data", None) or [])
    except Exception:
        logger.exception("compiler: campaign_cases lookup failed for %s", campaign_id)
        return []
    return sorted({str(row["case_id"]) for row in rows if row.get("case_id")})


def fetch_mo_fingerprints(
    case_ids: list[str],
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Return the MO fingerprints of the given cases.

    Args:
        case_ids: Case UUIDs.
        client: Optional injected Supabase client.

    Returns:
        List of fingerprint dicts, each carrying ``case_id`` and ``narrative``.
    """
    if not case_ids:
        return []
    try:
        supabase = client if client is not None else get_supabase_client()
        result = (
            supabase.table("case_mo")
            .select("case_id, fingerprint, narrative")
            .in_("case_id", case_ids)
            .execute()
        )
        rows = list(getattr(result, "data", None) or [])
    except Exception:
        logger.exception("compiler: case_mo lookup failed")
        return []

    fingerprints: list[dict[str, Any]] = []
    for row in rows:
        fingerprint = dict(row.get("fingerprint") or {})
        fingerprint.setdefault("narrative", row.get("narrative", ""))
        fingerprint["case_id"] = str(row.get("case_id", ""))
        fingerprints.append(fingerprint)
    return fingerprints


def fetch_campaign_entities(
    case_ids: list[str],
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Return the resolved entities linked to the given cases, deduplicated.

    Entities are matched on ``value_norm`` only — the same rule the entity
    resolver uses — so the watchlist an artifact carries is the exact key the
    graph joins on.

    Args:
        case_ids: Case UUIDs.
        client: Optional injected Supabase client.

    Returns:
        List of ``{entity_type, value_norm, value_raw, case_count}`` dicts.
    """
    if not case_ids:
        return []
    try:
        supabase = client if client is not None else get_supabase_client()
        result = (
            supabase.table("case_entity_links")
            .select("case_id, entities!inner(entity_type, value_norm, value_raw)")
            .in_("case_id", case_ids)
            .execute()
        )
        rows = list(getattr(result, "data", None) or [])
    except Exception:
        logger.exception("compiler: case_entity_links lookup failed")
        return []

    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        entity = row.get("entities") or {}
        value_norm = str(entity.get("value_norm") or "")
        if not value_norm:
            continue
        existing = merged.get(value_norm)
        if existing is None:
            merged[value_norm] = {
                "entity_type": entity.get("entity_type", "OTHER"),
                "value_norm": value_norm,
                "value_raw": entity.get("value_raw", value_norm),
                "case_count": 1,
            }
        else:
            existing["case_count"] += 1
    return [*merged.values()]


# ── Prompt helpers ───────────────────────────────────────────────────────────
def _summarise_mo(mo_fingerprints: list[dict[str, Any]]) -> str:
    """Summarise MO fingerprints for the compiler prompt.

    Args:
        mo_fingerprints: MO fingerprint dicts.

    Returns:
        A human-readable block, or a sentinel line when there is nothing.
    """
    if not mo_fingerprints:
        return "No MO fingerprints available."
    parts = []
    for i, mo in enumerate(mo_fingerprints):
        novel = [p.get("text") for p in mo.get("novel_phrases", []) if isinstance(p, dict)]
        parts.append(
            f"Case {i + 1}:\n"
            f"  Impersonated: {mo.get('impersonated_entity', 'N/A')}\n"
            f"  Pretext: {mo.get('pretext', 'N/A')}\n"
            f"  Phases: {mo.get('script_phases', [])}\n"
            f"  Tactics: {mo.get('pressure_tactics', [])}\n"
            f"  Novel phrases: {novel}\n"
            f"  Narrative: {mo.get('narrative', 'N/A')}"
        )
    return "\n".join(parts)


def _summarise_entities(entities: list[dict[str, Any]]) -> str:
    """Summarise resolved entities for the compiler prompt.

    Args:
        entities: Resolved entity dicts.

    Returns:
        A human-readable block, or a sentinel line when there is nothing.
    """
    if not entities:
        return "No entities available."
    return "\n".join(
        f"  {ent.get('entity_type', 'OTHER')}: {ent.get('value_raw', '')} "
        f"(norm: {ent.get('value_norm', '')})"
        for ent in entities
    )


def _collect_phrases(mo_fingerprints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect novel phrases across fingerprints, counting recurrences."""
    counted: dict[str, dict[str, Any]] = {}
    for mo in mo_fingerprints:
        for phrase in mo.get("novel_phrases", []) or []:
            if not isinstance(phrase, dict):
                continue
            text = str(phrase.get("text") or "").strip()
            if not text:
                continue
            entry = counted.get(text)
            if entry is None:
                counted[text] = {
                    "text": text,
                    "lang": phrase.get("lang", "ms"),
                    "case_count": 1,
                }
            else:
                entry["case_count"] += 1
    return [*counted.values()]


def _merge_with_fallback(
    compiled: dict[str, Any],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Backfill any artifact type the LLM omitted with its deterministic form."""
    merged = dict(compiled)
    for artifact_type in PACK_ARTIFACT_TYPES:
        if not merged.get(artifact_type):
            logger.warning("compiler: LLM omitted %s — using fallback", artifact_type)
            merged[artifact_type] = fallback[artifact_type]
    return merged


def _compiler_fallback(
    campaign_data: dict[str, Any],
    mo_fingerprints: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the five artifacts from structured data only (no LLM).

    Args:
        campaign_data: Campaign row.
        mo_fingerprints: MO fingerprints of the campaign's cases.
        entities: Resolved entities.

    Returns:
        Dict of ``artifact_type -> content`` for all five pack types.
    """
    code = campaign_data.get("code", "UNKNOWN")
    name = campaign_data.get("name", "Unknown campaign")

    accounts = [e.get("value_norm", "") for e in entities if e.get("entity_type") == "ACCOUNT"]
    domains = [e.get("value_norm", "") for e in entities if e.get("entity_type") == "DOMAIN"]
    phones = [e.get("value_norm", "") for e in entities if e.get("entity_type") == "PHONE"]
    urls = [e.get("value_norm", "") for e in entities if e.get("entity_type") == "URL"]

    phrases = _collect_phrases(mo_fingerprints)
    cited_cases = [mo["case_id"] for mo in mo_fingerprints if mo.get("case_id")]
    impersonated = next(
        (mo.get("impersonated_entity") for mo in mo_fingerprints if mo.get("impersonated_entity")),
        None,
    )

    campaign_pack = {
        "campaign": code,
        "name": name,
        "high_risk_phrases": phrases,
        "indicators": {
            "accounts": accounts,
            "domains": domains,
            "phones": phones,
            "urls": urls,
        },
        "anchor_question": (
            "Ask for the case reference and state that you will call back on the "
            "published hotline. A real institution never requests a transfer."
        ),
        "response_strategy": "deny_transfer + verify_callback + escalate",
        "cited_cases": cited_cases,
    }

    txn_rules: list[dict[str, Any]] = []
    if accounts:
        txn_rules.append(
            {
                "action": "BLOCK",
                "condition": {"field": "recipient_account", "op": "in", "values": accounts},
                "reason": f"Known mule account in {code} campaign",
            }
        )
    txn_rules.append(
        {
            "action": "STEP_UP",
            "condition": {"field": "amount", "op": "gt", "values": [10000]},
            "reason": f"High-value transfer during active {code} campaign",
        }
    )

    return {
        "campaign_pack": campaign_pack,
        "phishing_playbook_patch": {
            "campaign": code,
            "heavy_keywords": [p["text"] for p in phrases],
            "light_keywords": [],
            "url_patterns": [f"{d}.*" for d in domains],
            "risk_boost": 20,
        },
        "txn_rule": {"campaign": code, "rules": txn_rules},
        "compliance_brief": _fallback_compliance_brief(
            code, name, campaign_data, impersonated, accounts, domains, phrases, cited_cases
        ),
        "cs_advisory": _fallback_cs_advisory(code, impersonated, phrases),
    }


def _fallback_compliance_brief(
    code: str,
    name: str,
    campaign_data: dict[str, Any],
    impersonated: str | None,
    accounts: list[str],
    domains: list[str],
    phrases: list[dict[str, Any]],
    cited_cases: list[str],
) -> str:
    """Render the deterministic compliance brief (Markdown)."""
    phrase_lines = "\n".join(f'- "{p["text"]}"' for p in phrases) or "- (none recorded)"
    return (
        f"# Compliance Brief — {code}: {name}\n\n"
        "## Campaign summary\n"
        f"{campaign_data.get('mo_summary') or 'Compiled from linked case evidence.'}\n\n"
        "## Key indicators\n"
        f"- Impersonated entity: {impersonated or 'unknown'}\n"
        f"- Mule accounts: {', '.join(accounts) if accounts else 'none recorded'}\n"
        f"- Domains: {', '.join(domains) if domains else 'none recorded'}\n\n"
        "## Novel phrases\n"
        f"{phrase_lines}\n\n"
        "## Case citations\n"
        f"{len(cited_cases)} linked case(s): {', '.join(cited_cases) if cited_cases else 'n/a'}\n\n"
        "## Risk assessment\n"
        f"Confidence {campaign_data.get('confidence', 'n/a')} · "
        f"{campaign_data.get('case_count', len(cited_cases))} cases · "
        f"{campaign_data.get('customer_count', 0)} distinct customers.\n\n"
        "_Compiled without LLM assistance (deterministic fallback)._\n"
    )


def _fallback_cs_advisory(
    code: str,
    impersonated: str | None,
    phrases: list[dict[str, Any]],
) -> str:
    """Render the deterministic customer-service advisory (Markdown)."""
    phrase_lines = "\n".join(f'- "{p["text"]}"' for p in phrases) or "- (none recorded)"
    who = impersonated or "a government body or bank"
    return (
        f"# Customer Advisory — {code}\n\n"
        "## If a customer calls about this scam:\n"
        f'1. Ask: "Did the caller claim to be from {who}?"\n'
        '2. Ask: "Were you told to move money to a \'safe account\'?"\n'
        "3. If yes: advise the customer to make no transfer.\n"
        "4. Verify by calling back on the institution's published hotline only.\n"
        "5. File a police report at the nearest station.\n"
        "6. No legitimate institution requests transfers to a \"safe account\".\n\n"
        "## Key phrases to listen for:\n"
        f"{phrase_lines}\n"
    )


# ── Alias artifact views (IMPLEMENTATION_PROMPT naming) ──────────────────────
def build_entity_watchlist(
    campaign_data: dict[str, Any],
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the ``entity_watchlist.json`` view of a campaign's entities.

    Entities are emitted on ``value_norm`` — the only key the entity resolver
    and the Scam Graph match on.

    Args:
        campaign_data: Campaign row.
        entities: Resolved entities.

    Returns:
        ``{"campaign", "entities": [{entity_type, value_norm, value_raw, case_count}]}``.
    """
    return {
        "campaign": campaign_data.get("code", "UNKNOWN"),
        "entities": [
            {
                "entity_type": ent.get("entity_type", "OTHER"),
                "value_norm": ent.get("value_norm", ""),
                "value_raw": ent.get("value_raw", ent.get("value_norm", "")),
                "case_count": ent.get("case_count", 1),
            }
            for ent in entities
            if ent.get("value_norm")
        ],
    }


def build_alias_artifacts(
    campaign_data: dict[str, Any],
    compiled: dict[str, Any],
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Render the compiled artifacts under the file-oriented alias names.

    ``IMPLEMENTATION_PROMPT.md`` names the five outputs ``detection_rules.md``,
    ``advisory_template.md``, ``risk_score_overrides.json``, ``narrative.md``
    and ``entity_watchlist.json``, while both design documents (§7.1, §3) name
    them ``phishing_playbook_patch``, ``cs_advisory``, ``txn_rule``,
    ``compliance_brief`` and ``campaign_pack``. They are the same five
    artifacts. The registry stores the documented types; this helper renders
    the alias view for consumers that expect the file naming. Nothing here is
    published automatically.

    Args:
        campaign_data: Campaign row.
        compiled: Output of :func:`compile_campaign`.
        entities: Resolved entities (for the watchlist).

    Returns:
        Dict keyed by alias filename.
    """
    playbook = compiled.get("phishing_playbook_patch") or {}
    heavy = playbook.get("heavy_keywords", []) if isinstance(playbook, dict) else []
    light = playbook.get("light_keywords", []) if isinstance(playbook, dict) else []
    patterns = playbook.get("url_patterns", []) if isinstance(playbook, dict) else []

    def _bullets(values: list[Any]) -> str:
        return "\n".join(f"- `{v}`" for v in values) or "- (none)"

    detection_rules = (
        f"# Detection Rules — {campaign_data.get('code', 'UNKNOWN')}\n\n"
        "## Heavy keywords\n"
        f"{_bullets(heavy)}\n\n"
        "## Light keywords\n"
        f"{_bullets(light)}\n\n"
        "## URL patterns\n"
        f"{_bullets(patterns)}\n"
    )

    return {
        "detection_rules.md": detection_rules,
        "advisory_template.md": compiled.get("cs_advisory", ""),
        "risk_score_overrides.json": compiled.get("txn_rule", {}),
        "narrative.md": compiled.get("compliance_brief", ""),
        "entity_watchlist.json": build_entity_watchlist(campaign_data, entities),
    }
