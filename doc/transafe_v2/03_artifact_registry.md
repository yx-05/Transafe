# 03 — Artifact Registry & Compiler Design (L4)

> **Parent:** `01_upgrade_plan.md` §7
> **Scope:** Two-tier artifact model, compiler (pack tier), generaliser (core tier), registry (versioned store), propagation (L5)
> **Build blocks:** B4 (compiler + registry), B4b (generaliser), B5 (propagation)
> **Status:** Implementation-ready

---

## 1. Module inventory

| Module | File | Layer | Build block | Depends on |
|---|---|---|---|---|
| Compiler (pack tier) | `enterprise/compiler.py` | L4 | B4 | `agents/llm.py`, `db/vector_store.py` |
| Generaliser (core tier) | `enterprise/generaliser.py` | L4 | B4b | `agents/llm.py`, `enterprise/compiler.py` |
| Registry | `enterprise/registry.py` | L4 | B4 | `db/supabase.py` |
| Propagation | `enterprise/propagation.py` | L5 | B5 | `enterprise/registry.py`, `enterprise/events.py` |
| Events | `enterprise/events.py` | cross-cutting | B0 | Supabase `ns_events` table |

---

## 2. The two-tier artifact model

### 2.1 Decision

> Campaign knowledge goes into a **campaign pack** retrieved at runtime. The **core skill** changes only when something *generalisable* is learned.

The naive design appends every new scam's phrases into `phone_dialogue_guide.md`. At v7 that produces a beautiful diff. At v70 it produces an unmaintainable file, a prompt that no longer fits a context window, and an obvious question: *"what does that file look like after a year?"*

So artifacts are split into two tiers with different change rates:

| Tier | Contains | Changes | Lives in |
|---|---|---|---|
| **Core skill** — `phone_agent_core.md` | *procedure*: identify caller → detect coercion → **consult fraud memory** → apply the matched strategy → escalate | rarely; only on a cross-campaign generalisation | registry, versioned |
| **Campaign pack** — `SCAM-027.json` | *instance knowledge*: phrases, indicators, entities, response strategy for **one** campaign | once per campaign | Institutional Fraud Memory, retrieved at runtime |

The core skill never names a campaign. It contains the instruction to *look one up*. That is the difference between a skill that scales to 100,000 scams and a file that collapses at 100.

### 2.2 When the core skill changes (C1 / C2)

| | Condition | Evidence | Why it implies a campaign-agnostic rule |
|---|---|---|---|
| **C1** | **Recurrence-driven** — a pattern observed across **≥ 2 approved campaigns** | the generaliser pass over the MO fingerprints of all approved campaigns | a pattern present in several campaigns is by construction specific to none |
| **C2** | **Failure-driven** — a red-team variant is missed (§11.3) | the mutation that evaded detection | a rule that failed on a mutation of its own campaign was overfitted; the correction must generalise |

**Example (C1):**

```
Observed in SCAM-019, SCAM-024, SCAM-027:
  authority_claim + isolation + safe_account_instruction co-occur
→ Core skill rule (campaign-agnostic):
  "When these three phases co-occur in one call, escalate to enhanced
   verification regardless of the claimed institution."
```

That rule protects against campaign #4 **before it is discovered**.

---

## 3. Artifact types

| Tier | Artifact type | Target | Format | Effect |
|---|---|---|---|---|
| pack | `campaign_pack` | `phone_worker` (retrieved) | JSON | phrases, indicators, entities, response strategy for one campaign |
| pack | `phishing_playbook_patch` | `phishing_worker` | JSON | new heavy/light keywords, new URL patterns |
| pack | `txn_rule` | `financial_worker` / txn monitor | JSON | block/step-up on named accounts or patterns |
| pack | `cs_advisory` | customer service (via MCP, `customer_service` role) | Markdown | verified script for inbound enquiries |
| pack | `compliance_brief` | compliance (via MCP, `compliance` role) | Markdown | regulator-facing summary with case citations |
| **core** | `phone_agent_core` | `phone_worker` | Markdown | procedural rule change — **only on C1 or C2** |

### 3.1 Campaign pack schema (`campaign_pack` JSON)

```json
{
  "campaign": "SCAM-027",
  "name": "Fake BNM Safe-Account Wave",
  "high_risk_phrases": [
    {"text": "akaun selamat sementara", "lang": "ms", "case_count": 6},
    {"text": "pegawai siasatan BNM", "lang": "ms", "case_count": 6}
  ],
  "indicators": {
    "accounts": ["1592-XXXX-XXXX-XXXX"],
    "domains": ["bnm-*.online"],
    "phones": ["+60XXXXXXXXX"]
  },
  "anchor_question": "Ask for the case reference and state that you will call back on the published BNM hotline. BNM never requests transfers.",
  "response_strategy": "deny_transfer + verify_callback + escalate",
  "cited_cases": ["case-007", "case-012", "case-019", "case-023", "case-024", "case-031"]
}
```

### 3.2 Phishing playbook patch schema

```json
{
  "campaign": "SCAM-027",
  "heavy_keywords": ["akaun selamat sementara", "pegawai siasatan BNM"],
  "light_keywords": ["temporary safe account", "investigation officer"],
  "url_patterns": ["bnm-*\\.online", "bnm-verify\\."],
  "risk_boost": 20
}
```

### 3.3 Transaction rule schema

```json
{
  "campaign": "SCAM-027",
  "rules": [
    {
      "action": "BLOCK",
      "condition": {"field": "recipient_account", "op": "in", "values": ["1592-XXXX-XXXX-XXXX"]},
      "reason": "Known mule account in SCAM-027 campaign"
    },
    {
      "action": "STEP_UP",
      "condition": {"field": "amount", "op": "gt", "values": [10000]},
      "reason": "High-value transfer during active impersonation campaign"
    }
  ]
}
```

### 3.4 Compliance brief schema (Markdown)

```markdown
# Compliance Brief — SCAM-027: Fake BNM Safe-Account Wave

## Campaign summary
Caller impersonates a Bank Negara Malaysia investigation officer, claims the
victim's account is implicated in money laundering, and instructs transfer
to a "safe account" (mule account).

## Key indicators
- Impersonated entity: Bank Negara Malaysia
- Mule accounts: 1592-XXXX-XXXX-XXXX
- Domains: bnm-*.online
- Novel phrases: "akaun selamat sementara", "pegawai siasatan BNM"

## Case citations
Case #7, #12, #19, #23, #24, #31 (6 cases, 4 distinct customers)

## Regulatory considerations
- Potential violation of: Section 415 Penal Code (cheating)
- Reporting obligation: Bank Negara Malaysia fraud portal
- SAR filing threshold: RM 25,000 (all 6 cases exceed)

## Risk assessment
HIGH confidence (0.87). Active wave, 41-minute span.
```

### 3.5 CS advisory schema (Markdown)

```markdown
# Customer Advisory — SCAM-027

## If a customer calls about this scam:
1. Ask: "Did the caller claim to be from Bank Negara Malaysia?"
2. Ask: "Were you told to transfer to a 'safe account'?"
3. If yes: Advise the customer NOT to make any transfer.
4. Provide the official BNM hotline: 1-300-88-5465
5. File a police report at the nearest police station.
6. BNM never requests transfers to "safe accounts."

## Key phrases to listen for:
- "akaun selamat sementara" (temporary safe account)
- "pegawai siasatan BNM" (BNM investigation officer)
```

---

## 4. Compiler — `enterprise/compiler.py`

### 4.1 Purpose

Input: an **approved** campaign. Output: concrete, versioned, executable artifacts.

The compiler is an LLM call with a strict output schema, given: campaign MO summary, novel phrases, entity list, and **the current version of each target artifact** (so it produces a *patch in context*, not a from-scratch rewrite that would clobber existing rules).

### 4.2 Function signatures

```python
from __future__ import annotations

import json
import logging
from typing import Any

from agents.llm import extract_json_object, invoke_deepseek_with_key_rotation
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

COMPILER_SYSTEM_PROMPT = """\
You are a fraud defence artifact compiler. Given an approved campaign's \
MO summary, novel phrases, entity list, and the current version of each \
target artifact, you produce concrete, versioned artifacts.

Rules:
1. Campaign packs contain INSTANCE knowledge for ONE campaign only.
2. Never clobber existing rules — emit a patch in context.
3. Every indicator must trace to a cited case.
4. Return ONLY a JSON object with the artifact types as keys.

Schema:
{
  "campaign_pack": {...},
  "phishing_playbook_patch": {...},
  "txn_rule": {...},
  "compliance_brief": "markdown string",
  "cs_advisory": "markdown string"
}
"""


def compile_campaign(
    campaign_id: str,
    campaign_data: dict[str, Any],
    mo_fingerprints: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    current_artifacts: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Compile an approved campaign into pack-tier artifacts.

    Args:
        campaign_id: UUID of the approved campaign.
        campaign_data: Campaign dict with code, name, confidence, indicators.
        mo_fingerprints: List of MO fingerprint dicts for cases in the campaign.
        entities: List of resolved entities (PHONE, ACCOUNT, URL, DOMAIN).
        current_artifacts: Dict of artifact_name → current content (for patch-in-context).

    Returns:
        Dict of artifact_type → compiled content, or None on failure.
    """
    # Build the prompt context
    mo_summary = _summarise_mo(mo_fingerprints)
    entity_summary = _summarise_entities(entities)
    current_artifacts_str = json.dumps(current_artifacts or {}, indent=2)

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

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        compiled = extract_json_object(response.content)
        if compiled is None:
            logger.error("Compiler: LLM returned unparseable JSON for campaign %s", campaign_id)
            return _compiler_fallback(campaign_data, mo_fingerprints, entities)
        return compiled
    except Exception:
        logger.exception("Compiler failed for campaign %s", campaign_id)
        return _compiler_fallback(campaign_data, mo_fingerprints, entities)


def _summarise_mo(mo_fingerprints: list[dict[str, Any]]) -> str:
    """Summarise MO fingerprints for the compiler prompt."""
    if not mo_fingerprints:
        return "No MO fingerprints available."
    parts = []
    for i, mo in enumerate(mo_fingerprints):
        parts.append(
            f"Case {i+1}:\n"
            f"  Impersonated: {mo.get('impersonated_entity', 'N/A')}\n"
            f"  Pretext: {mo.get('pretext', 'N/A')}\n"
            f"  Phases: {mo.get('script_phases', [])}\n"
            f"  Tactics: {mo.get('pressure_tactics', [])}\n"
            f"  Novel phrases: {[p.get('text') for p in mo.get('novel_phrases', [])]}\n"
            f"  Narrative: {mo.get('narrative', 'N/A')}"
        )
    return "\n".join(parts)


def _summarise_entities(entities: list[dict[str, Any]]) -> str:
    """Summarise resolved entities for the compiler prompt."""
    if not entities:
        return "No entities available."
    parts = []
    for ent in entities:
        parts.append(
            f"  {ent.get('entity_type', 'OTHER')}: {ent.get('value_raw', '')} "
            f"(norm: {ent.get('value_norm', '')})"
        )
    return "\n".join(parts)


def _compiler_fallback(
    campaign_data: dict[str, Any],
    mo_fingerprints: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministic fallback when LLM is unavailable.

    Produces minimal artifacts from structured data only.
    """
    code = campaign_data.get("code", "UNKNOWN")
    name = campaign_data.get("name", "Unknown campaign")

    # Collect entities by type
    accounts = [e["value_norm"] for e in entities if e.get("entity_type") == "ACCOUNT"]
    domains = [e["value_norm"] for e in entities if e.get("entity_type") == "DOMAIN"]
    phones = [e["value_norm"] for e in entities if e.get("entity_type") == "PHONE"]

    # Collect novel phrases
    phrases = []
    for mo in mo_fingerprints:
        for p in mo.get("novel_phrases", []):
            phrases.append({"text": p.get("text", ""), "lang": p.get("lang", "ms")})

    campaign_pack = {
        "campaign": code,
        "name": name,
        "high_risk_phrases": [{"text": p["text"], "lang": p["lang"], "case_count": 1} for p in phrases],
        "indicators": {
            "accounts": accounts,
            "domains": domains,
            "phones": phones,
        },
        "anchor_question": "Ask for the case reference and state that you will call back on the published hotline.",
        "response_strategy": "deny_transfer + verify_callback + escalate",
        "cited_cases": [],
    }

    return {
        "campaign_pack": campaign_pack,
        "phishing_playbook_patch": {
            "campaign": code,
            "heavy_keywords": [p["text"] for p in phrases],
            "light_keywords": [],
            "url_patterns": [f"{d}.*" for d in domains],
            "risk_boost": 20,
        },
        "txn_rule": {
            "campaign": code,
            "rules": [
                {
                    "action": "BLOCK",
                    "condition": {"field": "recipient_account", "op": "in", "values": accounts},
                    "reason": f"Known mule account in {code} campaign",
                }
            ],
        },
        "compliance_brief": f"# Compliance Brief — {code}: {name}\n\nFallback compiled. See campaign data.",
        "cs_advisory": f"# Customer Advisory — {code}\n\nFallback compiled. See campaign data.",
    }
```

---

## 5. Generaliser — `enterprise/generaliser.py`

### 5.1 Purpose

A second, separate compiler pass that runs only when a campaign is approved and **≥ 2 other approved campaigns exist**. It is given the MO fingerprints of all approved campaigns and asked for cross-campaign invariants. Its output is a proposed `phone_agent_core` patch, which goes through the same human approval gate. If it finds nothing, it emits nothing; that is a normal outcome.

### 5.2 The agnosticism validator

The core tier changes only when the resulting rule is **campaign-agnostic** — it names no campaign, no institution, no account. That is the test.

### 5.3 Function signatures

```python
from __future__ import annotations

import json
import logging
from typing import Any

from agents.llm import extract_json_object, invoke_deepseek_with_key_rotation
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

GENERALISER_SYSTEM_PROMPT = """\
You are a fraud defence generaliser. You look for patterns that appear across \
multiple approved campaigns and propose campaign-agnostic rules.

Rules:
1. The proposed rule must NOT name any specific campaign, institution, or account.
2. It must be a generalisation — applicable to future, unseen campaigns.
3. If no cross-campaign invariant is found, return {"found": false}.
4. Return ONLY a JSON object.

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

MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION = 2


def maybe_generalise(
    approved_campaigns: list[dict[str, Any]],
    current_core_content: str,
) -> dict[str, Any] | None:
    """Attempt to find a cross-campaign invariant and propose a core skill patch.

    Args:
        approved_campaigns: List of approved campaign dicts, each with:
            code, mo_fingerprints (list of MO dicts).
        current_core_content: The current phone_agent_core.md content.

    Returns:
        Dict with the proposed rule, or None if no invariant found.
        Returns {"found": False} if the LLM says nothing to generalise.
    """
    if len(approved_campaigns) < MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION + 1:
        # Need ≥ 2 OTHER campaigns + the new one = ≥ 3 total
        logger.info(
            "Generaliser: only %d approved campaigns, need ≥ %d (including new one)",
            len(approved_campaigns),
            MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION + 1,
        )
        return None

    # Build MO summaries for all campaigns
    mo_summaries = []
    for camp in approved_campaigns:
        for mo in camp.get("mo_fingerprints", []):
            mo_summaries.append({
                "campaign": camp.get("code"),
                "impersonated_entity": mo.get("impersonated_entity"),
                "script_phases": mo.get("script_phases", []),
                "pressure_tactics": mo.get("pressure_tactics", []),
                "novel_phrases": [p.get("text") for p in mo.get("novel_phrases", [])],
            })

    user_prompt = f"""Current phone_agent_core.md:
{current_core_content}

Approved campaigns and their MO fingerprints:
{json.dumps(mo_summaries, indent=2)}

Find a pattern that appears across multiple campaigns and propose a \
campaign-agnostic rule that could be added to phone_agent_core.md."""

    messages = [
        SystemMessage(content=GENERALISER_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        result = extract_json_object(response.content)
        if result is None:
            logger.error("Generaliser: LLM returned unparseable JSON")
            return None
        if not result.get("found", False):
            logger.info("Generaliser: no cross-campaign invariant found")
            return None
        # Validate agnosticism
        if not validate_campaign_agnostic(result.get("rule_text", "")):
            logger.warning("Generaliser: proposed rule is not campaign-agnostic")
            return None
        return result
    except Exception:
        logger.exception("Generaliser failed")
        return None


def validate_campaign_agnostic(rule_text: str) -> bool:
    """Validate that a proposed core rule names no specific campaign, institution, or account.

    Args:
        rule_text: The proposed rule text.

    Returns:
        True if the rule is campaign-agnostic, False otherwise.
    """
    if not rule_text:
        return False
    text_lower = rule_text.lower()
    # Check for specific entity names that would make it campaign-specific
    # This is a heuristic; the human gate (§10) is the real check
    forbidden = [
        "scam-0",  # campaign codes
        "bank negara",  # specific institutions
        "maybank",
"cimb",
        "public bank",
        "rhb",
        "ambank",
        "1592",  # specific account fragments
    ]
    for term in forbidden:
        if term in text_lower:
            return False
    return True
```

---

## 6. Registry — `enterprise/registry.py`

### 6.1 Properties

Append-only, versioned, attributed. Both tiers live here; the diff view is the same for both.

- **Immutable versions** — once published, a version never changes
- **Diffable** — every version shows a diff vs the previous
- **Attributed** — every version traces to the campaign(s) and cases that justified it
- **One-click rollback** — publish v6 again as v8
- **Consumption receipts** — proving agents actually loaded it
- **Effectiveness record** — written back by the evaluation harness (§11)

### 6.2 Function signatures

```python
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def publish_artifact(
    name: str,
    tier: str,
    artifact_type: str,
    target_agent: str,
    content: str,
    content_json: dict[str, Any] | None = None,
    campaign_id: str | None = None,
    source_campaigns: list[str] | None = None,
    created_by: str = "compiler",
    approved_by: str = "fraud_ops",
) -> dict[str, Any] | None:
    """Publish a new version of an artifact to the registry.

    Args:
        name: Artifact name (e.g. "phone_agent_core", "SCAM-027").
        tier: "core" or "pack".
        artifact_type: One of: campaign_pack, phishing_playbook_patch, txn_rule,
            cs_advisory, compliance_brief, phone_agent_core.
        target_agent: Agent that consumes this artifact.
        content: Text content (markdown for core, JSON string for pack).
        content_json: Optional structured JSON content.
        campaign_id: Campaign UUID (None for core-tier).
        source_campaigns: List of campaign codes for core-tier generalisation.
        created_by: "compiler" | "generaliser" | "human".
        approved_by: Name of the approver.

    Returns:
        The published artifact dict, or None on failure.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()

    # Get next version number
    existing = client.table("artifacts").select("version").eq(
        "name", name
    ).order("version", desc=True).limit(1).execute()
    next_version = (existing.data[0]["version"] + 1) if existing.data else 1

    row = {
        "name": name,
        "tier": tier,
        "artifact_type": artifact_type,
        "target_agent": target_agent,
        "version": next_version,
        "content": content,
        "content_json": content_json,
        "campaign_id": campaign_id,
        "source_campaigns": source_campaigns or [],
        "status": "PUBLISHED",
        "created_by": created_by,
        "approved_by": approved_by,
    }

    try:
        result = client.table("artifacts").insert(row).execute()
        return result.data[0] if result.data else None
    except Exception:
        logger.exception("Failed to publish artifact %s v%d", name, next_version)
        return None


def get_artifact(
    name: str,
    version: int | None = None,
) -> dict[str, Any] | None:
    """Get an artifact by name and version (latest if version is None).

    Args:
        name: Artifact name.
        version: Version number, or None for latest published.

    Returns:
        Artifact dict, or None if not found.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    query = client.table("artifacts").select("*").eq("name", name).eq(
        "status", "PUBLISHED"
    )
    if version is not None:
        query = query.eq("version", version)
    else:
        query = query.order("version", desc=True).limit(1)
    result = query.execute()
    return result.data[0] if result.data else None


def get_artifact_diff(
    name: str,
    version: int,
) -> dict[str, Any] | None:
    """Get an artifact version with a diff against the previous version.

    Args:
        name: Artifact name.
        version: Version to diff.

    Returns:
        Dict with current content, previous content, and unified diff lines.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    current = get_artifact(name, version)
    if not current:
        return None

    previous = None
    if version > 1:
        prev_result = client.table("artifacts").select("*").eq(
            "name", name
        ).eq("version", version - 1).execute()
        if prev_result.data:
            previous = prev_result.data[0]

    diff_lines = _compute_diff(
        previous.get("content", "") if previous else "",
        current["content"],
    )

    return {
        "current": current,
        "previous": previous,
        "diff": diff_lines,
    }


def list_artifacts(
    tier: str | None = None,
    campaign_id: str | None = None,
) -> list[dict[str, Any]]:
    """List all published artifacts, optionally filtered by tier or campaign.

    Args:
        tier: Filter by "core" or "pack" (None for all).
        campaign_id: Filter by campaign (None for all).

    Returns:
        List of artifact dicts (latest version of each).
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    query = client.table("artifacts").select("*").eq("status", "PUBLISHED")
    if tier:
        query = query.eq("tier", tier)
    if campaign_id:
        query = query.eq("campaign_id", campaign_id)
    query = query.order("created_at", desc=True)
    result = query.execute()

    # Deduplicate by name, keeping the highest version
    seen: dict[str, dict[str, Any]] = {}
    for row in result.data or []:
        name = row["name"]
        if name not in seen or row["version"] > seen[name]["version"]:
            seen[name] = row
    return list(seen.values())


def rollback_artifact(
    name: str,
    to_version: int,
    approved_by: str = "fraud_ops",
) -> dict[str, Any] | None:
    """Rollback an artifact to a previous version by publishing it as a new version.

    Args:
        name: Artifact name.
        to_version: The version to rollback to.
        approved_by: Name of the approver.

    Returns:
        The newly published artifact dict, or None on failure.
    """
    target = get_artifact(name, to_version)
    if not target:
        return None

    return publish_artifact(
        name=name,
        tier=target["tier"],
        artifact_type=target["artifact_type"],
        target_agent=target["target_agent"],
        content=target["content"],
        content_json=target.get("content_json"),
        campaign_id=target.get("campaign_id"),
        source_campaigns=target.get("source_campaigns", []),
        created_by="human",
        approved_by=approved_by,
    )


def record_consumption(
    artifact_id: str,
    agent_name: str,
) -> None:
    """Record that an agent consumed an artifact (consumption receipt).

    Args:
        artifact_id: UUID of the artifact.
        agent_name: Name of the consuming agent.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    try:
        client.table("artifact_consumption").upsert({
            "artifact_id": artifact_id,
            "agent_name": agent_name,
        }).execute()
    except Exception:
        logger.exception(
            "Failed to record consumption for artifact %s by %s",
            artifact_id, agent_name,
        )


def update_effectiveness(
    artifact_id: str,
    effectiveness: dict[str, Any],
) -> None:
    """Write evaluation effectiveness back to an artifact.

    Args:
        artifact_id: UUID of the artifact.
        effectiveness: Dict with eval_run_id, detected, total, fp, fp_total, measured_at.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    try:
        client.table("artifacts").update({
            "effectiveness": effectiveness,
        }).eq("id", artifact_id).execute()
    except Exception:
        logger.exception(
            "Failed to update effectiveness for artifact %s", artifact_id
        )


def _compute_diff(old: str, new: str) -> list[dict[str, str]]:
    """Compute a simple line-level diff between two strings.

    Args:
        old: Previous content.
        new: Current content.

    Returns:
        List of {"type": "added"|"removed"|"context", "line": str}.
    """
    import difflib

    old_lines = old.splitlines(keepends=False)
    new_lines = new.splitlines(keepends=False)

    diff: list[dict[str, str]] = []
    for line in difflib.unified_diff(
        old_lines, new_lines, lineterm="", n=3
    ):
        if line.startswith("+"):
            diff.append({"type": "added", "line": line[1:]})
        elif line.startswith("-"):
            diff.append({"type": "removed", "line": line[1:]})
        elif line.startswith(" "):
            diff.append({"type": "context", "line": line[1:]})
    return diff
```

### 6.3 Deferred design — publish-time victim-value denylist

> **Status: NOT IMPLEMENTED. Design of record only.**
> Deferred deliberately: it backstops a failure mode whose exposure in the
> shipped pipeline is currently nil, at a cost the demo-critical path needs.
> Recorded here so the reasoning is not lost and so any future implementation
> starts from the corrected costing in §6.3.4 rather than the original one.

#### 6.3.1 The gap it addresses

Compiler prompt rule 5 (`compiler.py:55-61`) forbids victim-side identity in
any published artifact. It is an **advisory** control: it is a sentence in a
system prompt, and nothing downstream enforces it. The two artifacts most at
risk are `compliance_brief` and `cs_advisory`, the only free-text Markdown in
the pack tier. Per `ROLE_VISIBILITY`, `compliance_brief` reaches `compliance`
and `auditor`, and `cs_advisory` reaches `customer_service` and `auditor`
(besides `fraud_ops`) — readers entitled to the attack pattern and never to the
people it was worked on. Note that `legal` and `partner_bank` receive neither.

Note what does *not* guard this. The generaliser's `check_agnosticism` runs
only on core-tier `rule_text`, never on pack-tier bodies. The MCP redaction
layer gates `compliance_brief` and `cs_advisory` as **whole categories**
(`redaction.py:197-198`, `STRUCTURAL_FIELDS`) — all-or-nothing, and it never
inspects the body. A role entitled to the category therefore receives the text
verbatim, whatever is in it. Pack-tier free text reaches those readers having
passed no automated victim-identity check at any layer.

#### 6.3.2 The inversion (the part worth keeping)

The obvious framing — "detect PII in the artifact before publishing" — is not
implementable, and it is worth being precise about why. Attacker-versus-victim
is **not a property of the string**. `7712345678` is a mule account or a
victim's account depending entirely on facts outside the text. Any classifier
operating on the artifact body alone must therefore produce false positives on
exactly the values the artifact exists to carry, and a control that flags mule
accounts is a control that gets switched off.

Invert it. Do not ask "is this PII?" Ask "**is this one of the specific values
we already know to be victim-side for this campaign?**" Those values are not
inferred — they are already in the database, on the case rows the campaign was
built from.

This makes false positives on attacker indicators **structurally impossible**
rather than merely unlikely, and that is the whole asset:

- attacker indicators live in the resolved-entity table for the campaign;
- victim values live on the case rows;
- the two sets are **disjoint by construction** — a value that is a mule
  account is an entity, not a victim field.

So the check can never fire on a legitimate indicator. That property comes from
the data model, not from tuning a threshold, which is why it is worth writing
down even unimplemented.

#### 6.3.3 Shape

At publish time, resolve the campaign(s) for the artifact, load the victim-side
values for their cases (name, phone, account, NRIC, email, and verbatim quoted
speech), and reject the publish if any appears **verbatim** in `content`.
Rejection must be loud: refuse the insert and emit a `warning`-severity
`ns_event`, never publish-and-log.

#### 6.3.4 Costing correction — the chokepoint is weaker than it looks

The original costing claimed `publish_artifact()` is a single chokepoint that
"already receives `campaign_id`". **It receives it optionally**
(`registry.py:98`, `campaign_id: str | None = None`), and the three call sites
do not agree:

| Call site | Passes | Resolvable? |
|---|---|---|
| `propagation.py:197` (`propagate_campaign_artifacts`, pack tier) | `campaign_id=campaign_id` explicitly | yes |
| `registry.py:188` (`rollback_artifact`) | `campaign_id=target.get("campaign_id")` | **may be `None`** |
| `propagation.py:236` (`publish_and_propagate_core`, core tier) | no `campaign_id` at all — `source_campaigns` instead | only via `source_campaigns` |

Implemented as originally designed, the control would silently no-op wherever
`campaign_id` is `None` — **present, tested, green, and not running**, which is
the worst available failure mode for a security control.

Two requirements follow, and any future implementation must honour both:

1. Resolve **`source_campaigns` as well as `campaign_id`**.
2. **Fail loudly when it can resolve neither.** Passing by default reproduces
   the silent no-op this note exists to prevent.

One mitigating detail, worth recording honestly because it is luck and not
design: the path that carries no `campaign_id` (`propagation.py:236`) is the
core-tier generaliser path, which *does* go through `check_agnosticism`, while
the pack-tier paths that rule 5 alone guards are the ones that do carry
`campaign_id`. The coverage happens to land on the right tier. Nothing in the
code causes that to remain true.

#### 6.3.5 What this is not

It converts rule 5 from *advisory* to *advisory plus a verbatim backstop*. It
is **not a guarantee**, and must not be described as one:

- it matches **verbatim occurrences only**;
- **paraphrase defeats it** — an LLM-rewritten victim detail is not a string
  match;
- **reconstructed speech defeats it** — quoted dialogue rendered in the
  compiler's own words carries the content without carrying the characters;
- it covers only values already recorded as victim-side; anything the case row
  never captured is invisible to it.

The human approval gate remains the real control. This would catch the
mechanical copy-paste case, which is the common one — not the adversarial one.

---

## 7. Propagation — `enterprise/propagation.py`

### 7.1 Purpose

Publishing an artifact emits a `propagation_event` per subscribed agent. Each agent acknowledges by writing a **consumption receipt** (`artifact_consumption`).

| Agent | Real or simulated | Consumes |
|---|---|---|
| `phone_worker` | **real** (v1 code) | `campaign_pack` (runtime retrieval) + `phone_agent_core` |
| `phishing_worker` | **real** (v1 code) | `phishing_playbook_patch` |
| `financial_worker` / txn monitor | **real** (v1 code) | `txn_rule` |

### 7.2 Subscription map

```python
SUBSCRIPTION_MAP: dict[str, list[str]] = {
    "campaign_pack": ["phone_worker"],
    "phishing_playbook_patch": ["phishing_worker"],
    "txn_rule": ["financial_worker"],
    "cs_advisory": [],  # consumed externally via MCP
    "compliance_brief": [],  # consumed externally via MCP
    "phone_agent_core": ["phone_worker"],
}
```

### 7.3 Function signatures

```python
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SUBSCRIPTION_MAP: dict[str, list[str]] = {
    "campaign_pack": ["phone_worker"],
    "phishing_playbook_patch": ["phishing_worker"],
    "txn_rule": ["financial_worker"],
    "cs_advisory": [],
    "compliance_brief": [],
    "phone_agent_core": ["phone_worker"],
}


async def propagate_artifact(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Propagate a published artifact to all subscribed agents.

    Args:
        artifact: Published artifact dict with id, name, artifact_type, version.

    Returns:
        List of propagation result dicts with agent_name, artifact_id, status.
    """
    from enterprise.events import emit_event
    from enterprise.registry import record_consumption

    artifact_type = artifact.get("artifact_type", "")
    subscribed_agents = SUBSCRIPTION_MAP.get(artifact_type, [])

    results = []
    for agent_name in subscribed_agents:
        # Emit propagation event
        await emit_event(
            layer="propagation",
            event_type="propagation_event",
            payload={
                "artifact_id": artifact["id"],
                "artifact_name": artifact["name"],
                "version": artifact["version"],
                "agent_name": agent_name,
            },
        )

        # Record consumption receipt
        record_consumption(artifact["id"], agent_name)

        # Emit acknowledgement
        await emit_event(
            layer="propagation",
            event_type="propagation_acknowledged",
            payload={
                "artifact_id": artifact["id"],
                "artifact_name": artifact["name"],
                "version": artifact["version"],
                "agent_name": agent_name,
            },
        )

        results.append({
            "agent_name": agent_name,
            "artifact_id": artifact["id"],
            "status": "acknowledged",
        })

    return results


async def propagate_campaign_artifacts(
    campaign_id: str,
    compiled_artifacts: dict[str, Any],
    campaign_data: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Publish and propagate all artifacts for a campaign.

    Args:
        campaign_id: UUID of the approved campaign.
        compiled_artifacts: Dict from compiler.compile_campaign().
        campaign_data: Campaign dict with code, name.

    Returns:
        Dict of artifact_type → list of propagation results.
    """
    from enterprise.registry import publish_artifact

    code = campaign_data.get("code", "UNKNOWN")
    results: dict[str, list[dict[str, Any]]] = {}

    # Artifact type → (name, tier, target_agent) mapping
    artifact_specs = {
        "campaign_pack": (code, "pack", "phone_worker"),
        "phishing_playbook_patch": (code, "pack", "phishing_worker"),
        "txn_rule": (code, "pack", "financial_worker"),
        "cs_advisory": (f"{code}_cs_advisory", "pack", "customer_service"),
        "compliance_brief": (f"{code}_compliance_brief", "pack", "compliance"),
    }

    for art_type, content in compiled_artifacts.items():
        if art_type not in artifact_specs:
            continue

        name, tier, target_agent = artifact_specs[art_type]

        # Serialize content
        if isinstance(content, dict):
            content_str = json.dumps(content, indent=2)
            content_json = content
        else:
            content_str = str(content)
            content_json = None

        artifact = publish_artifact(
            name=name,
            tier=tier,
            artifact_type=art_type,
            target_agent=target_agent,
            content=content_str,
            content_json=content_json,
            campaign_id=campaign_id,
            created_by="compiler",
        )

        if artifact:
            prop_results = await propagate_artifact(artifact)
            results[art_type] = prop_results

    return results
```

---

## 8. Events — `enterprise/events.py`

### 8.1 Purpose

`ns_events` is the backbone of the entire dashboard. Every layer writes to it; the WebSocket streams it; the animations are driven by it; REPLAY mode replays it. One table, one event schema, one source of truth for both modes.

### 8.2 Function signatures

```python
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


async def emit_event(
    layer: str,
    event_type: str,
    payload: dict[str, Any],
    severity: str = "info",
    run_id: str | None = None,
) -> None:
    """Emit a nervous-system event to the ns_events table.

    Args:
        layer: One of: sensing, case, discovery, compiler, registry, propagation, exposure.
        event_type: Event type (e.g. case_ingested, entity_linked, campaign_proposed).
        payload: Event-specific data.
        severity: "info", "warning", "critical".
        run_id: Optional run ID for demo scenario grouping.
    """
    from db.vector_store import get_supabase_client

    row = {
        "ts": datetime.now(UTC).isoformat(),
        "layer": layer,
        "event_type": event_type,
        "severity": severity,
        "payload": payload,
        "run_id": run_id,
    }

    try:
        client = get_supabase_client()
        client.table("ns_events").insert(row).execute()
    except Exception:
        logger.exception("Failed to emit ns_event: %s/%s", layer, event_type)


async def emit_event_batch(
    events: list[dict[str, Any]],
    run_id: str | None = None,
) -> None:
    """Emit multiple ns_events in one batch.

    Args:
        events: List of {layer, event_type, payload, severity?} dicts.
        run_id: Optional run ID.
    """
    from db.vector_store import get_supabase_client

    rows = []
    for evt in events:
        rows.append({
            "ts": datetime.now(UTC).isoformat(),
            "layer": evt.get("layer", "case"),
            "event_type": evt.get("event_type", "unknown"),
            "severity": evt.get("severity", "info"),
            "payload": evt.get("payload", {}),
            "run_id": run_id,
        })

    try:
        client = get_supabase_client()
        client.table("ns_events").insert(rows).execute()
    except Exception:
        logger.exception("Failed to emit batch of %d ns_events", len(rows))


def get_events(
    run_id: str | None = None,
    limit: int = 100,
    layer: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent ns_events, optionally filtered.

    Args:
        run_id: Filter by run ID (None for live).
        limit: Max number of events.
        layer: Filter by layer (None for all).

    Returns:
        List of event dicts, newest first.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    query = client.table("ns_events").select("*").order("ts", desc=True).limit(limit)
    if run_id:
        query = query.eq("run_id", run_id)
    if layer:
        query = query.eq("layer", layer)
    result = query.execute()
    return result.data or []
```

---

## 9. Testing

### 9.1 Test files

| Module | Test file | Cases |
|---|---|---|
| `compiler` | `tests/unit/test_compiler.py` | 6 |
| `generaliser` | `tests/unit/test_generaliser.py` | 6 |
| `registry` | `tests/unit/test_registry.py` | 10 |
| `propagation` | `tests/unit/test_propagation.py` | 6 |
| `events` | `tests/unit/test_events.py` | 5 |

### 9.2 Test cases — `test_compiler.py`

```python
"""Unit tests for the artifact compiler (L4 pack tier)."""

from unittest.mock import MagicMock, patch
import pytest

from enterprise.compiler import (
    compile_campaign,
    _summarise_mo,
    _summarise_entities,
    _compiler_fallback,
)


@patch("enterprise.compiler.invoke_deepseek_with_key_rotation")
def test_compile_campaign_returns_all_artifacts(mock_llm: MagicMock):
    """Assert compiler returns all 5 pack-tier artifact types."""
    mock_response = MagicMock()
    mock_response.content = '''{
        "campaign_pack": {"campaign": "SCAM-027"},
        "phishing_playbook_patch": {"campaign": "SCAM-027"},
        "txn_rule": {"campaign": "SCAM-027"},
        "compliance_brief": "# Brief",
        "cs_advisory": "# Advisory"
    }'''
    mock_llm.return_value = mock_response

    result = compile_campaign("camp-1", {"code": "SCAM-027"}, [], [])
    assert result is not None
    assert "campaign_pack" in result
    assert "phishing_playbook_patch" in result
    assert "txn_rule" in result
    assert "compliance_brief" in result
    assert "cs_advisory" in result


@patch("enterprise.compiler.invoke_deepseek_with_key_rotation")
def test_compile_campaign_llm_failure_triggers_fallback(mock_llm: MagicMock):
    """Assert LLM exception triggers deterministic fallback."""
    mock_llm.side_effect = RuntimeError("LLM down")
    result = compile_campaign("camp-1", {"code": "SCAM-027"}, [], [])
    assert result is not None
    assert result["campaign_pack"]["campaign"] == "SCAM-027"


def test_compiler_fallback_includes_entities():
    """Assert fallback includes entities in artifacts."""
    entities = [
        {"entity_type": "ACCOUNT", "value_norm": "12345", "value_raw": "1234-5"},
        {"entity_type": "DOMAIN", "value_norm": "evil.com", "value_raw": "evil.com"},
    ]
    result = _compiler_fallback({"code": "SCAM-027", "name": "Test"}, [], entities)
    assert "12345" in result["campaign_pack"]["indicators"]["accounts"]
    assert "evil.com" in result["campaign_pack"]["indicators"]["domains"]


def test_summarise_mo_handles_empty():
    assert _summarise_mo([]) == "No MO fingerprints available."


def test_summarise_mo_includes_fields():
    mo = [{"impersonated_entity": "BNM", "script_phases": ["a"], "pressure_tactics": ["b"]}]
    summary = _summarise_mo(mo)
    assert "BNM" in summary
    assert "authority" not in summary  # just checking formatting


def test_summarise_entities_handles_empty():
    assert _summarise_entities([]) == "No entities available."
```

### 9.3 Test cases — `test_generaliser.py`

```python
"""Unit tests for the generaliser (L4 core tier)."""

from unittest.mock import MagicMock, patch
import pytest

from enterprise.generaliser import (
    maybe_generalise,
    validate_campaign_agnostic,
    MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION,
)


def test_validate_agnostic_passes_generic_rule():
    rule = "When authority_claim, isolation and safe_account_instruction co-occur, escalate."
    assert validate_campaign_agnostic(rule) is True


def test_validate_agnostic_fails_named_campaign():
    rule = "When SCAM-027 pattern is detected, escalate."
    assert validate_campaign_agnostic(rule) is False


def test_validate_agnostic_fails_named_institution():
    rule = "When Bank Negara is impersonated, escalate."
    assert validate_campaign_agnostic(rule) is False


def test_maybe_generalise_returns_none_for_few_campaigns():
    """Assert generaliser does not run with < 3 approved campaigns."""
    campaigns = [{"code": "SCAM-019"}, {"code": "SCAM-024"}]
    result = maybe_generalise(campaigns, "current content")
    assert result is None


@patch("enterprise.generaliser.invoke_deepseek_with_key_rotation")
def test_maybe_generalise_returns_rule_when_found(mock_llm: MagicMock):
    mock_response = MagicMock()
    mock_response.content = '''{
        "found": true,
        "rule_text": "When authority_claim and isolation co-occur, escalate.",
        "rule_id": "R-4",
        "justification": "Seen across 3 campaigns",
        "source_campaigns": ["SCAM-019", "SCAM-024", "SCAM-027"],
        "evidence_summary": "Pattern co-occurrence"
    }'''
    mock_llm.return_value = mock_response

    campaigns = [
        {"code": "SCAM-019", "mo_fingerprints": [{}]},
        {"code": "SCAM-024", "mo_fingerprints": [{}]},
        {"code": "SCAM-027", "mo_fingerprints": [{}]},
    ]
    result = maybe_generalise(campaigns, "current content")
    assert result is not None
    assert result["found"] is True
    assert result["rule_id"] == "R-4"


@patch("enterprise.generaliser.invoke_deepseek_with_key_rotation")
def test_maybe_generalise_returns_none_when_not_found(mock_llm: MagicMock):
    mock_response = MagicMock()
    mock_response.content = '{"found": false}'
    mock_llm.return_value = mock_response

    campaigns = [{"code": "SCAM-019", "mo_fingerprints": [{}]}] * 3
    result = maybe_generalise(campaigns, "current content")
    assert result is None
```

### 9.4 Test cases — `test_registry.py`

```python
"""Unit tests for the artifact registry (L4)."""

from unittest.mock import MagicMock, patch
import pytest

from enterprise.registry import (
    publish_artifact,
    get_artifact,
    get_artifact_diff,
    list_artifacts,
    rollback_artifact,
    record_consumption,
    update_effectiveness,
    _compute_diff,
)


@patch("enterprise.registry.get_supabase_client")
def test_publish_artifact_increments_version(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"version": 6}]
    mock_table.insert.return_value.execute.return_value.data = [{"id": "art-1", "version": 7}]
    mock_client.return_value.table.return_value = mock_table

    result = publish_artifact(
        name="phone_agent_core",
        tier="core",
        artifact_type="phone_agent_core",
        target_agent="phone_worker",
        content="# Core skill v7",
    )
    assert result is not None
    assert result["version"] == 7


@patch("enterprise.registry.get_supabase_client")
def test_publish_artifact_first_version(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    mock_table.insert.return_value.execute.return_value.data = [{"id": "art-1", "version": 1}]
    mock_client.return_value.table.return_value = mock_table

    result = publish_artifact("SCAM-027", "pack", "campaign_pack", "phone_worker", "{}")
    assert result["version"] == 1


@patch("enterprise.registry.get_supabase_client")
def test_get_artifact_returns_latest(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"id": "art-1", "version": 7}]
    mock_client.return_value.table.return_value = mock_table

    result = get_artifact("phone_agent_core")
    assert result["version"] == 7


@patch("enterprise.registry.get_supabase_client")
def test_get_artifact_returns_specific_version(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "art-1", "version": 5}]
    mock_client.return_value.table.return_value = mock_table

    result = get_artifact("phone_agent_core", version=5)
    assert result["version"] == 5


@patch("enterprise.registry.get_supabase_client")
def test_get_artifact_diff_returns_diff(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"content": "old line\n"}]
    mock_table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"id": "art-1", "version": 7, "content": "new line\n"}]
    mock_client.return_value.table.return_value = mock_table

    result = get_artifact_diff("phone_agent_core", 7)
    assert result is not None
    assert result["current"]["version"] == 7
    assert isinstance(result["diff"], list)


@patch("enterprise.registry.get_supabase_client")
def test_list_artifacts_deduplicates_by_name(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
        {"id": "art-1", "name": "SCAM-027", "version": 2, "tier": "pack"},
        {"id": "art-2", "name": "SCAM-027", "version": 1, "tier": "pack"},
        {"id": "art-3", "name": "SCAM-019", "version": 1, "tier": "pack"},
    ]
    mock_client.return_value.table.return_value = mock_table

    result = list_artifacts()
    assert len(result) == 2
    scam027 = [a for a in result if a["name"] == "SCAM-027"][0]
    assert scam027["version"] == 2


@patch("enterprise.registry.get_supabase_client")
def test_list_artifacts_filters_by_tier(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value.data = [
        {"id": "art-1", "name": "phone_agent_core", "version": 7, "tier": "core"},
    ]
    mock_client.return_value.table.return_value = mock_table

    result = list_artifacts(tier="core")
    assert len(result) == 1
    assert result[0]["tier"] == "core"


@patch("enterprise.registry.get_supabase_client")
def test_rollback_artifact_publishes_old_version(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"id": "art-1", "version": 7, "content": "current"}]
    mock_table.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": "art-2", "version": 5, "content": "old content", "tier": "core", "artifact_type": "phone_agent_core", "target_agent": "phone_worker"}]
    mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"version": 7}]
    mock_table.insert.return_value.execute.return_value.data = [{"id": "art-3", "version": 8}]
    mock_client.return_value.table.return_value = mock_table

    result = rollback_artifact("phone_agent_core", to_version=5)
    assert result is not None
    assert result["version"] == 8


@patch("enterprise.registry.get_supabase_client")
def test_record_consumption_upserts(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    record_consumption("art-1", "phone_worker")
    mock_table.upsert.assert_called_once()


def test_compute_diff_adds_and_removes():
    diff = _compute_diff("line1\nline2\n", "line1\nline3\n")
    types = [d["type"] for d in diff]
    assert "added" in types
    assert "removed" in types


def test_compute_diff_no_changes():
    diff = _compute_diff("same\n", "same\n")
    assert all(d["type"] == "context" for d in diff)
```

### 9.5 Test cases — `test_propagation.py`

```python
"""Unit tests for propagation (L5)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from enterprise.propagation import (
    propagate_artifact,
    propagate_campaign_artifacts,
    SUBSCRIPTION_MAP,
)


def test_subscription_map_covers_pack_types():
    """Assert all pack-tier types have subscriptions (except MCP-only)."""
    assert "phone_worker" in SUBSCRIPTION_MAP["campaign_pack"]
    assert "phishing_worker" in SUBSCRIPTION_MAP["phishing_playbook_patch"]
    assert "financial_worker" in SUBSCRIPTION_MAP["txn_rule"]
    assert SUBSCRIPTION_MAP["cs_advisory"] == []  # external via MCP
    assert SUBSCRIPTION_MAP["compliance_brief"] == []


@pytest.mark.asyncio
async def test_propagate_artifact_emits_events():
    """Assert propagation emits events and records consumption."""
    artifact = {
        "id": "art-1",
        "name": "SCAM-027",
        "artifact_type": "campaign_pack",
        "version": 1,
    }
    with patch("enterprise.propagation.emit_event", new_callable=AsyncMock) as mock_emit:
        with patch("enterprise.propagation.record_consumption") as mock_record:
            results = await propagate_artifact(artifact)

    assert len(results) == 1
    assert results[0]["agent_name"] == "phone_worker"
    assert results[0]["status"] == "acknowledged"
    # Two events per agent: propagation_event + propagation_acknowledged
    assert mock_emit.call_count == 2
    mock_record.assert_called_once_with("art-1", "phone_worker")


@pytest.mark.asyncio
async def test_propagate_artifact_no_subscribers():
    """Assert artifacts with no subscribers (cs_advisory) produce no results."""
    artifact = {
        "id": "art-2",
        "name": "SCAM-027_cs_advisory",
        "artifact_type": "cs_advisory",
        "version": 1,
    }
    with patch("enterprise.propagation.emit_event", new_callable=AsyncMock):
        with patch("enterprise.propagation.record_consumption"):
            results = await propagate_artifact(artifact)
    assert results == []


@pytest.mark.asyncio
async def test_propagate_campaign_artifacts_publishes_all():
    """Assert all 5 pack-tier artifacts are published and propagated."""
    compiled = {
        "campaign_pack": {"campaign": "SCAM-027"},
        "phishing_playbook_patch": {"campaign": "SCAM-027"},
        "txn_rule": {"campaign": "SCAM-027"},
        "compliance_brief": "# Brief",
        "cs_advisory": "# Advisory",
    }
    with patch("enterprise.propagation.publish_artifact") as mock_publish:
        with patch("enterprise.propagation.propagate_artifact", new_callable=AsyncMock) as mock_prop:
            mock_publish.return_value = {"id": "art-x", "name": "test", "version": 1, "artifact_type": "campaign_pack"}
            mock_prop.return_value = [{"agent_name": "phone_worker", "status": "acknowledged"}]
            results = await propagate_campaign_artifacts("camp-1", compiled, {"code": "SCAM-027"})

    assert mock_publish.call_count == 5
    assert len(results) == 5


@pytest.mark.asyncio
async def test_propagate_phone_agent_core_reaches_phone_worker():
    """Assert phone_agent_core propagates to phone_worker."""
    artifact = {
        "id": "art-core",
        "name": "phone_agent_core",
        "artifact_type": "phone_agent_core",
        "version": 7,
    }
    with patch("enterprise.propagation.emit_event", new_callable=AsyncMock):
        with patch("enterprise.propagation.record_consumption"):
            results = await propagate_artifact(artifact)
    assert len(results) == 1
    assert results[0]["agent_name"] == "phone_worker"
```

### 9.6 Test cases — `test_events.py`

```python
"""Unit tests for ns_events emitter (cross-cutting)."""

from unittest.mock import MagicMock, patch
import pytest

from enterprise.events import emit_event, emit_event_batch, get_events


@pytest.mark.asyncio
async def test_emit_event_inserts_row():
    with patch("enterprise.events.get_supabase_client") as mock_client:
        mock_table = MagicMock()
        mock_client.return_value.table.return_value = mock_table
        await emit_event(
            layer="discovery",
            event_type="campaign_proposed",
            payload={"campaign_id": "c1"},
        )
    mock_table.insert.assert_called_once()


@pytest.mark.asyncio
async def test_emit_event_handles_failure_gracefully():
    with patch("enterprise.events.get_supabase_client", side_effect=Exception("DB down")):
        # Should not raise
        await emit_event("test", "test_event", {})


@pytest.mark.asyncio
async def test_emit_event_batch_inserts_all():
    events = [
        {"layer": "case", "event_type": "ingested", "payload": {"id": "c1"}},
        {"layer": "discovery", "event_type": "linked", "payload": {"id": "c1"}},
    ]
    with patch("enterprise.events.get_supabase_client") as mock_client:
        mock_table = MagicMock()
        mock_client.return_value.table.return_value = mock_table
        await emit_event_batch(events, run_id="run-1")
    mock_table.insert.assert_called_once()
    inserted_rows = mock_table.insert.call_args[0][0]
    assert len(inserted_rows) == 2


@patch("enterprise.events.get_supabase_client")
def test_get_events_returns_list(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1, "layer": "case", "event_type": "ingested"},
    ]
    mock_client.return_value.table.return_value = mock_table
    events = get_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "ingested"


@patch("enterprise.events.get_supabase_client")
def test_get_events_filters_by_run_id(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.order.return_value.limit.return_value.eq.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table
    events = get_events(run_id="run-1")
    assert events == []
```

### 9.7 pytest + ruff

```bash
cd backend && uv run pytest tests/unit/test_compiler.py tests/unit/test_generaliser.py tests/unit/test_registry.py tests/unit/test_propagation.py tests/unit/test_events.py -v
```

```bash
cd backend && uv run ruff check src/enterprise/compiler.py src/enterprise/generaliser.py src/enterprise/registry.py src/enterprise/propagation.py src/enterprise/events.py
```
