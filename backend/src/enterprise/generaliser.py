"""Generaliser (core tier) — L4.

A second, separate compiler pass. It runs only when a campaign is approved and
**at least two other approved campaigns already exist**, is given the MO
fingerprints of every approved campaign, and is asked for a cross-campaign
invariant (01_upgrade_plan.md §7.0 C1, 03_artifact_registry.md §5).

Its output is a *proposed* ``phone_agent_core`` patch that passes through the
same human approval gate as everything else.

**Emitting nothing is a correct outcome.** The core tier is rare by
construction; a generaliser that always finds something is a generaliser that
is making things up. Nothing here forces an output: too few campaigns, an
unparseable answer, ``{"found": false}``, or a rule that fails the agnosticism
validator all resolve to ``None``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm import extract_json_object, invoke_deepseek_with_key_rotation

logger = logging.getLogger(__name__)

GENERALISER_SYSTEM_PROMPT = """\
You are a fraud defence generaliser. You look for patterns that appear across \
multiple approved campaigns and propose campaign-agnostic rules.

Rules:
1. The proposed rule must NOT name any specific campaign, institution, or account.
2. It must be a generalisation — applicable to future, unseen campaigns.
3. It must not reference a specific date, month, year or time window.
4. If no cross-campaign invariant is found, return {"found": false}. Finding \
nothing is a correct and common answer; never invent a pattern.
5. Return ONLY a JSON object.

Schema:
{
  "found": true,
  "rule_text": "the rule as it would appear in phone_agent_core.md",
  "rule_id": "R-4",
  "justification": "why this generalises",
  "source_campaigns": ["SCAM-019", "SCAM-024", "SCAM-027"],
  "evidence_summary": "what pattern was observed across these campaigns"
}
"""

#: A pattern must recur across at least this many *other* approved campaigns.
MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION = 2

# ── C1: campaign-specific entity names that disqualify a core rule ───────────
FORBIDDEN_TERMS: tuple[str, ...] = (
    "scam-0",
    "bank negara",
    "maybank",
    "cimb",
    "public bank",
    "rhb",
    "ambank",
    "hong leong",
    "1592",
)

# Campaign codes in any casing, e.g. SCAM-027.
CAMPAIGN_CODE_RE = re.compile(r"\bscam[-_ ]?\d{2,}\b", re.IGNORECASE)
# Long digit runs are account/phone fragments.
IDENTIFIER_RE = re.compile(r"\b\d{4,}\b")

# ── C2: campaign-specific temporal references that disqualify a core rule ────
TEMPORAL_TERMS: tuple[str, ...] = (
    "yesterday",
    "today",
    "tomorrow",
    "last week",
    "this week",
    "last month",
    "this month",
    "last night",
    "this morning",
    "this afternoon",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")


def maybe_generalise(
    approved_campaigns: list[dict[str, Any]],
    current_core_content: str,
) -> dict[str, Any] | None:
    """Look for a cross-campaign invariant and propose a core-skill patch.

    Args:
        approved_campaigns: Approved campaign dicts, each with ``code`` and
            ``mo_fingerprints`` (a list of MO dicts).
        current_core_content: Current ``phone_agent_core.md`` body, so the
            proposal is a patch in context rather than a rewrite.

    Returns:
        The proposal dict when a campaign-agnostic invariant was found and
        validated, otherwise ``None``. ``None`` is a normal outcome.
    """
    required = MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION + 1
    if len(approved_campaigns) < required:
        logger.info(
            "generaliser: only %d approved campaign(s), need >= %d (2 others + the new one)",
            len(approved_campaigns),
            required,
        )
        return None

    mo_summaries: list[dict[str, Any]] = []
    for campaign in approved_campaigns:
        for mo in campaign.get("mo_fingerprints", []) or []:
            mo_summaries.append(
                {
                    "campaign": campaign.get("code"),
                    "impersonated_entity": mo.get("impersonated_entity"),
                    "script_phases": mo.get("script_phases", []),
                    "pressure_tactics": mo.get("pressure_tactics", []),
                    "novel_phrases": [
                        p.get("text")
                        for p in (mo.get("novel_phrases") or [])
                        if isinstance(p, dict)
                    ],
                }
            )

    user_prompt = f"""Current phone_agent_core.md:
{current_core_content}

Approved campaigns and their MO fingerprints:
{json.dumps(mo_summaries, indent=2, ensure_ascii=False)}

Find a pattern that appears across multiple campaigns and propose a \
campaign-agnostic rule that could be added to phone_agent_core.md. \
If there is no such pattern, return {{"found": false}}."""

    messages = [
        SystemMessage(content=GENERALISER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        result = extract_json_object(getattr(response, "content", response))
    except Exception:
        logger.exception("generaliser: LLM call failed")
        return None

    if not result:
        logger.error("generaliser: unparseable LLM JSON")
        return None

    if not result.get("found", False):
        logger.info("generaliser: no cross-campaign invariant found")
        return None

    rule_text = str(result.get("rule_text") or "")
    report = check_agnosticism(rule_text)
    if not report["agnostic"]:
        logger.warning(
            "generaliser: proposed rule rejected as campaign-specific: %s",
            report["violations"],
        )
        return None

    source = result.get("source_campaigns") or [c.get("code") for c in approved_campaigns]
    result["source_campaigns"] = [code for code in source if code]
    result.setdefault("rule_id", _next_rule_id(current_core_content))
    return result


def check_agnosticism(rule_text: str) -> dict[str, Any]:
    """Run the agnosticism validator and report every violation found.

    Two conditions must hold for a rule to reach the core tier:

    * **C1** — it names no campaign, institution, account or other
      campaign-specific entity.
    * **C2** — it makes no campaign-specific temporal reference (a rule tied to
      "last Tuesday" or "March 2026" describes one wave, not a procedure).

    Args:
        rule_text: The proposed rule.

    Returns:
        ``{"agnostic": bool, "violations": [{"condition", "term"}]}``.
    """
    violations: list[dict[str, str]] = []
    if not rule_text or not rule_text.strip():
        return {"agnostic": False, "violations": [{"condition": "C0", "term": "empty rule"}]}

    lowered = rule_text.lower()

    for term in FORBIDDEN_TERMS:
        if term in lowered:
            violations.append({"condition": "C1", "term": term})
    match = CAMPAIGN_CODE_RE.search(rule_text)
    if match:
        violations.append({"condition": "C1", "term": match.group(0)})
    for identifier in IDENTIFIER_RE.findall(rule_text):
        if not YEAR_RE.fullmatch(identifier):
            violations.append({"condition": "C1", "term": identifier})

    for term in TEMPORAL_TERMS:
        if term in lowered:
            violations.append({"condition": "C2", "term": term})
    year = YEAR_RE.search(rule_text)
    if year:
        violations.append({"condition": "C2", "term": year.group(0)})
    date = DATE_RE.search(rule_text)
    if date:
        violations.append({"condition": "C2", "term": date.group(0)})

    # Deduplicate while preserving order.
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for violation in violations:
        key = (violation["condition"], violation["term"])
        if key not in seen:
            seen.add(key)
            unique.append(violation)

    return {"agnostic": not unique, "violations": unique}


def validate_campaign_agnostic(rule_text: str) -> bool:
    """Return ``True`` when a proposed core rule is campaign-agnostic.

    Args:
        rule_text: The proposed rule text.

    Returns:
        ``True`` if the rule names no campaign, institution, account or date.
    """
    return bool(check_agnosticism(rule_text)["agnostic"])


def build_core_patch(current_core_content: str, proposal: dict[str, Any]) -> str:
    """Append a validated rule to the core skill body, in context.

    The rule is inserted under an existing ``## Escalation rules`` heading when
    one exists, so the patch reads as a diff of one section rather than a
    rewrite of the file.

    Args:
        current_core_content: The current ``phone_agent_core.md`` body.
        proposal: A validated :func:`maybe_generalise` result.

    Returns:
        The new core-skill body.
    """
    rule_id = str(proposal.get("rule_id") or _next_rule_id(current_core_content))
    rule_text = str(proposal.get("rule_text") or "").strip()
    sources = [str(code) for code in (proposal.get("source_campaigns") or [])]
    provenance = (
        f"      Generalised from {len(sources)} campaigns." if sources else "      Generalised."
    )
    rule_block = f"{rule_id}: {rule_text}\n{provenance}"

    body = current_core_content or "# phone_agent_core\n\n## Escalation rules\n"
    heading = "## Escalation rules"
    if heading in body:
        head, _, tail = body.partition(heading)
        lines = tail.splitlines()
        insert_at = len(lines)
        for index, line in enumerate(lines):
            if line.startswith("## "):
                insert_at = index
                break
        while insert_at > 0 and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, rule_block)
        return head + heading + "\n".join(lines).rstrip() + "\n"

    return body.rstrip() + f"\n\n{heading}\n{rule_block}\n"


def _next_rule_id(current_core_content: str) -> str:
    """Derive the next ``R-n`` identifier from the current core body."""
    numbers = [int(n) for n in re.findall(r"\bR-(\d+)\b", current_core_content or "")]
    return f"R-{max(numbers) + 1}" if numbers else "R-1"
