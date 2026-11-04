"""TranSafe MCP Server — L6, the door.

Exposes TranSafe's fraud intelligence to external agentic systems (WorkBuddy,
Claude Desktop, a partner bank's compliance agent) over MCP's stdio transport,
and enforces the four things that make that safe to do:

* **Role** — every tool call carries a role, and every payload is passed
  through :func:`mcp.redaction.redact_by_role` before it leaves the process.
* **Entitlement** — :data:`TOOL_REQUIREMENTS` denies a tool outright when the
  role has no business calling it, rather than returning an empty husk.
* **Rate limit** — :data:`RATE_LIMIT_PER_MINUTE` (60/min) per caller,
  enforced server-side, returning a legible error and never an exception.
* **Audit** — *every* call is written to ``mcp_access_log`` and emitted as an
  ``exposure``/``mcp_call`` ns_event: successes, denials, rate-limit
  rejections and errors alike. An audit log that only records successes is
  useless for exactly the incident you would want to investigate.

Transport
---------
The stdio loop below is a hand-rolled JSON-RPC 2.0 implementation rather than
the PyPI ``mcp`` SDK. Two reasons: this package is itself named ``mcp`` and
would shadow the SDK on ``sys.path``, and a dependency-free transport keeps the
tool layer importable and unit-testable with no transport running at all.
Everything above :func:`serve_stdio` is pure functions over a Supabase client.

Read paths are failure-tolerant: the v2 migration may not be applied yet, so a
missing table renders as ``[]`` / ``0``, never a 500 and never a traceback
across the wire.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

# ``python -m mcp.server`` from backend/ already puts backend/ on sys.path;
# this makes `python backend/mcp/server.py` work too.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, _BACKEND_ROOT)

from mcp.redaction import (  # noqa: E402
    can_access,
    project_log_entry,
    redact_by_role,
    redacted_categories_for,
)
from src.db.vector_store import get_supabase_client  # noqa: E402
from src.enterprise.entity_resolver import normalise_entity  # noqa: E402
from src.enterprise.events import emit_event  # noqa: E402
from src.enterprise.registry import get_artifact as registry_get_artifact  # noqa: E402

logger = logging.getLogger(__name__)

MCP_LOG_TABLE = "mcp_access_log"

#: Least-privilege default. A caller that does not declare a role gets the
#: public policy, never an internal one.
DEFAULT_ROLE = "public"
#: Caller name recorded on every audit row. The client config sets
#: ``TRANSAFE_CALLER`` explicitly; this is the fallback for a direct run.
DEFAULT_CALLER = "workbuddy"

#: The statuses a campaign can hold and still be worth listing. Declared here
#: rather than inline so the filter and the error message cannot disagree.
KNOWN_CAMPAIGN_STATUSES: tuple[str, ...] = ("APPROVED", "ACTIVE")

#: Rate limiting — sliding one-minute window, per caller.
RATE_LIMIT_PER_MINUTE = 60
RATE_LIMIT_WINDOW_SECONDS = 60.0
_rate_counts: dict[str, list[float]] = {}

#: Resource category a role must hold to invoke each tool.
TOOL_REQUIREMENTS: dict[str, str] = {
    "ask_transafe": "aggregate",
    "list_active_campaigns": "campaign",
    "get_campaign": "campaign",
    "get_case_evidence": "cases",
    "get_artifact": "artifacts",
    "check_indicator": "indicators",
    "query_stats": "aggregate",
    "query_mcp_log": "aggregate",
}

#: Alternate tool names accepted by the dispatcher. ``01_upgrade_plan.md`` §9.2
#: and ``04_mcp_gateway.md`` §4 name the retrieval tools ``get_*``; the B6 task
#: brief names them ``query_*``. Both are honoured so neither caller breaks.
TOOL_ALIASES: dict[str, str] = {
    "query_campaign": "get_campaign",
    "query_case": "get_case_evidence",
    "query_case_evidence": "get_case_evidence",
    "query_artifact": "get_artifact",
    "query_campaigns": "list_active_campaigns",
    "query_indicator": "check_indicator",
}

#: Artifact types that are themselves role-gated, independent of the
#: ``artifacts`` entitlement.
_GATED_ARTIFACT_TYPES: frozenset[str] = frozenset({"compliance_brief", "cs_advisory"})


# ── Rate limiting ────────────────────────────────────────────────────────────
def check_rate_limit(caller: str) -> bool:
    """Sliding-window rate limiter, 60 calls per minute per caller.

    Args:
        caller: Caller identifier.

    Returns:
        ``True`` when the call is within budget (and the call is recorded),
        ``False`` when the caller has exceeded it.
    """
    now = time.time()
    recent = [t for t in _rate_counts.get(caller, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    _rate_counts[caller] = recent

    if len(recent) >= RATE_LIMIT_PER_MINUTE:
        return False

    recent.append(now)
    return True


def rate_limit_remaining(caller: str) -> int:
    """Return how many calls ``caller`` may still make in the current window.

    Args:
        caller: Caller identifier.

    Returns:
        Remaining call budget, never negative.
    """
    now = time.time()
    recent = [t for t in _rate_counts.get(caller, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    return max(0, RATE_LIMIT_PER_MINUTE - len(recent))


def reset_rate_limits() -> None:
    """Clear all rate-limit state. Test and process-restart helper."""
    _rate_counts.clear()


# ── Audit log ────────────────────────────────────────────────────────────────
def log_mcp_access(
    caller: str,
    role: str,
    tool: str,
    params: dict[str, Any] | None,
    latency_ms: int,
    citations: Any = None,
    outcome: str = "ok",
    client: Any | None = None,
) -> bool:
    """Write one ``mcp_access_log`` row. Called for **every** outcome.

    ``outcome`` is carried inside ``params`` because the shipped
    ``migrations/v2_enterprise.sql`` schema for this table has no status
    column and B6 must not alter a table another block owns. It renders in
    Screen G alongside the caller's own arguments.

    Args:
        caller: Caller identifier, e.g. ``workbuddy``.
        role: Role the call was evaluated under.
        tool: Tool name requested (pre-alias-resolution name is fine).
        params: Arguments the caller supplied.
        latency_ms: Wall-clock latency in milliseconds.
        citations: Citations returned, if any.
        outcome: ``ok`` | ``denied`` | ``rate_limited`` | ``error`` |
            ``unknown_tool``.
        client: Optional injected Supabase client.

    Returns:
        ``True`` when the row was written, ``False`` when it could not be —
        logging failure never propagates to the caller.
    """
    row = {
        "ts": _now_iso(),
        "caller": caller,
        "role": role,
        "tool": tool,
        "params": {"outcome": outcome, **(params or {})},
        "latency_ms": latency_ms,
        "citations": _citation_ids(citations),
    }

    try:
        supabase = client if client is not None else get_supabase_client()
        supabase.table(MCP_LOG_TABLE).insert(row).execute()
        return True
    except Exception:
        logger.exception("Failed to log MCP access for %s/%s", caller, tool)
        return False


def fetch_mcp_log(limit: int = 50, client: Any | None = None) -> list[dict[str, Any]]:
    """Return the most recent audit rows, newest first.

    Args:
        limit: Maximum rows to return.
        client: Optional injected Supabase client.

    Returns:
        List of log rows; ``[]`` when the table is absent or empty.
    """
    try:
        supabase = client if client is not None else get_supabase_client()
        result = (
            supabase.table(MCP_LOG_TABLE)
            .select("*")
            .order("ts", desc=True)
            .limit(limit)
            .execute()
        )
        return [dict(row) for row in (getattr(result, "data", None) or [])]
    except Exception:
        logger.exception("mcp: fetch_mcp_log failed")
        return []


def _citation_ids(citations: Any) -> list[str] | None:
    """Flatten citations to the ``string[] | null`` shape Screen G consumes.

    Args:
        citations: Raw citations — list of dicts, list of strings, or ``None``.

    Returns:
        List of identifier strings, or ``None`` when there are none.
    """
    if not citations:
        return None
    if isinstance(citations, dict):
        citations = [citations]
    if not isinstance(citations, list):
        return [str(citations)]

    ids: list[str] = []
    for citation in citations:
        if isinstance(citation, dict):
            value = citation.get("id") or citation.get("code") or citation.get("detail")
            if value:
                ids.append(str(value))
            else:
                # No recognised identifier key. Dropping is deliberate: the
                # alternative is stringifying the dict into Screen G's
                # ``join(", ")``, which is the ``[object Object]`` failure this
                # normaliser exists to prevent. But an audit citation vanishing
                # is a hole in the trail, so make it diagnosable rather than
                # silent — a new producer emitting an unknown key shape shows
                # up in logs instead of quietly shrinking the citation list.
                logger.warning(
                    "mcp: dropping citation with no id/code/detail key: %r", citation
                )
        elif citation:
            ids.append(str(citation))
    return ids or None


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _rows(result: Any) -> list[dict[str, Any]]:
    """Extract rows from a Supabase response, tolerating ``None``."""
    return [dict(row) for row in (getattr(result, "data", None) or [])]


def _looks_like_uuid(value: Any) -> bool:
    """True when ``value`` can be cast to a Postgres ``uuid``.

    Used to choose the lookup column *before* querying rather than to catch the
    failure afterwards. ``campaigns.id`` is a ``uuid`` column, so filtering it
    by a code-shaped argument (``SCAM-001``) makes Postgres raise ``22P02`` at
    cast time. That is a malformed *argument*, not an infrastructure fault, and
    a ``try/except`` around it would record it as the latter — the distinction
    this module otherwise keeps.
    """
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _count(client: Any, table: str, column: str = "id") -> int:
    """Return a row count, degrading to ``0`` when the table is unavailable."""
    try:
        return len(_rows(client.table(table).select(column).execute()))
    except Exception:
        logger.info("mcp: count unavailable for %s (migration not applied?)", table)
        return 0


# ── Tool implementations ─────────────────────────────────────────────────────
def tool_list_active_campaigns(role: str, status: str | None = None) -> dict[str, Any]:
    """List active campaigns, redacted by role.

    Args:
        role: Caller role.
        status: Optional status filter. Matched case-insensitively against
            :data:`KNOWN_CAMPAIGN_STATUSES`. When omitted, every active
            campaign is returned.

    Returns:
        ``{"campaigns": [...]}``, redacted. When a supplied filter matches
        nothing, the payload also carries a ``note`` naming the valid values,
        because an unexplained empty list is indistinguishable from a broken
        tool to whoever asked.
    """
    client = get_supabase_client()
    query = client.table("campaigns").select("*")
    if status:
        # Case-insensitive on purpose: the stored values are upper-case
        # (``APPROVED``) and callers write ``Approved``. PostgREST compares
        # exactly, so without this the filter silently returns nothing.
        query = query.eq("status", str(status).strip().upper())
    else:
        query = query.in_("status", list(KNOWN_CAMPAIGN_STATUSES))
    data = _rows(query.execute())

    payload: dict[str, Any] = {"campaigns": data}
    if status and not data:
        payload["note"] = (
            f"No campaign has status {str(status).strip().upper()!r}. "
            f"Valid statuses: {', '.join(KNOWN_CAMPAIGN_STATUSES)}. "
            "Omit the status argument to list the whole active set."
        )
    return redact_by_role(payload, role)


def tool_get_campaign(role: str, campaign_id: str) -> dict[str, Any]:
    """Get one campaign with its cases and artifacts, redacted by role.

    Accepts **either** the campaign UUID or its human-facing ``code``
    (``SCAM-001``) — the identifier Screens C/D display and the one
    :func:`tool_list_active_campaigns` hands back. Previously only the UUID
    worked: ``campaigns.id`` is a ``uuid`` column, so a code-shaped argument
    raised ``22P02`` out of the unguarded lookup and surfaced raw SQLSTATE at
    the tool boundary, which also meant the ``Campaign not found`` branch below
    was unreachable for precisely the inputs that needed it.

    Args:
        role: Caller role.
        campaign_id: Campaign UUID, or campaign ``code`` such as ``SCAM-001``.

    Returns:
        The campaign dict, redacted, or ``{"error": ...}`` when unknown.
    """
    client = get_supabase_client()
    column = "id" if _looks_like_uuid(campaign_id) else "code"
    rows = _rows(client.table("campaigns").select("*").eq(column, campaign_id).execute())
    if not rows:
        return {"error": "Campaign not found", "campaign_id": campaign_id}
    campaign = rows[0]

    # Key the child lookups off the *resolved* UUID, never the argument.
    # ``campaign_cases.campaign_id`` and ``artifacts.campaign_id`` are uuid
    # columns too, so passing a code through would raise 22P02 inside the
    # ``try`` blocks below — where it is caught and rendered as ``[]``. The
    # campaign would then come back looking merely quiet (no cases, no
    # artifacts) rather than broken, which is the failure mode this module
    # keeps finding: a guard converting a malformed argument into a plausible
    # empty result.
    resolved_id = campaign.get("id") or campaign_id

    try:
        campaign["cases"] = _rows(
            client.table("campaign_cases")
            .select("case_id, linkage_score")
            .eq("campaign_id", resolved_id)
            .execute()
        )
    except Exception:
        logger.exception("mcp: campaign_cases lookup failed for %s", resolved_id)
        campaign["cases"] = []

    try:
        campaign["artifacts"] = _rows(
            client.table("artifacts")
            .select("name, version, artifact_type, tier")
            .eq("campaign_id", resolved_id)
            .execute()
        )
    except Exception:
        logger.exception("mcp: artifacts lookup failed for %s", resolved_id)
        campaign["artifacts"] = []

    return redact_by_role(campaign, role)


def tool_get_case_evidence(role: str, case_id: str) -> dict[str, Any]:
    """Get a redacted evidence bundle for one case.

    Args:
        role: Caller role.
        case_id: Case UUID.

    Returns:
        The case dict with its MO fingerprint, redacted, or ``{"error": ...}``.
    """
    client = get_supabase_client()
    rows = _rows(client.table("fraud_cases").select("*").eq("id", case_id).execute())
    if not rows:
        return {"error": "Case not found", "case_id": case_id}
    case_data = rows[0]

    try:
        mo_rows = _rows(
            client.table("case_mo")
            .select("fingerprint, narrative")
            .eq("case_id", case_id)
            .execute()
        )
    except Exception:
        logger.exception("mcp: case_mo lookup failed for %s", case_id)
        mo_rows = []

    if mo_rows:
        case_data["mo_fingerprint"] = mo_rows[0].get("fingerprint")
        case_data["narrative"] = mo_rows[0].get("narrative")

    return redact_by_role(case_data, role)


def tool_get_artifact(role: str, name: str, version: int | None = None) -> dict[str, Any]:
    """Get artifact content plus its diff against the previous version.

    Args:
        role: Caller role.
        name: Artifact name.
        version: Specific version, or ``None`` for the latest published one.

    Returns:
        The artifact dict, redacted, or ``{"error": ...}``.
    """
    artifact = registry_get_artifact(name, version)
    if not artifact:
        return {"error": "Artifact not found", "name": name, "version": version}

    # A second, finer gate: holding ``artifacts`` is not the same as holding
    # every *type* of artifact. ``legal`` may read the campaign pack but not the
    # compliance brief. This returns the same ``forbidden`` shape as the coarse
    # entitlement gate in :func:`handle_tool_call` so that both denials are
    # recognisable to callers and land in the audit log as ``denied``.
    artifact_type = str(artifact.get("artifact_type", ""))
    if artifact_type in _GATED_ARTIFACT_TYPES and not can_access(role, artifact_type):
        return {
            "error": "forbidden",
            "message": (
                f"Role {role!r} is not entitled to artifacts of type {artifact_type!r}."
            ),
            "role": role,
            "name": name,
            "artifact_type": artifact_type,
        }

    return redact_by_role(artifact, role)


def tool_check_indicator(role: str, indicator_type: str, value: str) -> dict[str, Any]:
    """Check whether an account, phone, URL or domain is known to TranSafe.

    Args:
        role: Caller role.
        indicator_type: ``PHONE`` | ``ACCOUNT`` | ``URL`` | ``DOMAIN``.
        value: The indicator value to check.

    Returns:
        ``{"known": False, ...}`` or a redacted hit with counts, first/last
        seen and linked campaigns.
    """
    try:
        norm = normalise_entity(indicator_type, value)
    except ValueError:
        return {"error": f"Unknown indicator type: {indicator_type}", "known": False}

    client = get_supabase_client()
    rows = _rows(
        client.table("entities")
        .select("id, case_count, first_seen, last_seen")
        .eq("entity_type", indicator_type)
        .eq("value_norm", norm)
        .execute()
    )
    if not rows:
        return {"known": False, "indicator_type": indicator_type, "value": value}
    entity = rows[0]

    try:
        case_ids = [
            str(row["case_id"])
            for row in _rows(
                client.table("case_entity_links")
                .select("case_id")
                .eq("entity_id", entity["id"])
                .execute()
            )
            if row.get("case_id")
        ]
    except Exception:
        logger.exception("mcp: case_entity_links lookup failed")
        case_ids = []

    campaigns: list[dict[str, Any]] = []
    if case_ids:
        try:
            for row in _rows(
                client.table("campaign_cases")
                .select("campaign_id, campaigns!inner(code, name, status)")
                .in_("case_id", case_ids)
                .execute()
            ):
                linked = row.get("campaigns")
                if linked:
                    campaigns.append(
                        {
                            "code": linked.get("code"),
                            "name": linked.get("name"),
                            "status": linked.get("status"),
                        }
                    )
        except Exception:
            logger.exception("mcp: campaign_cases lookup failed")

    return redact_by_role(
        {
            "known": True,
            "indicator_type": indicator_type,
            "value": value,
            "case_count": entity.get("case_count"),
            "first_seen": entity.get("first_seen"),
            "last_seen": entity.get("last_seen"),
            "linked_campaigns": campaigns,
        },
        role,
    )


def tool_query_stats(role: str) -> dict[str, Any]:
    """Return aggregate statistics — the one tool every role can call.

    Args:
        role: Caller role.

    Returns:
        ``{"aggregate": {...}}``. Counts degrade to ``0`` when the v2 migration
        has not been applied, never to an error.
    """
    try:
        client = get_supabase_client()
    except Exception:
        logger.exception("mcp: Supabase unavailable for query_stats")
        return {"aggregate": {"available": False}}

    campaigns = _rows(_safe_select(client, "campaigns", "id, status, confidence"))
    # Counter names are deliberately ``*_count`` rather than ``cases`` /
    # ``entities`` / ``artifacts``: those are redactable resource names, and a
    # count is not the resource. Naming them after the resource would blank the
    # one payload every role is entitled to see.
    aggregate = {
        "available": True,
        "case_count": _count(client, "fraud_cases"),
        "entity_count": _count(client, "entities"),
        "link_count": _count(client, "case_links", "score"),
        "artifact_count": _count(client, "artifacts"),
        "campaigns_total": len(campaigns),
        "campaigns_active": len(
            [c for c in campaigns if c.get("status") in ("APPROVED", "ACTIVE")]
        ),
        "campaigns_pending": len(
            [c for c in campaigns if c.get("status") in ("CANDIDATE", "PENDING_VALIDATION")]
        ),
        "generated_at": _now_iso(),
    }
    return redact_by_role({"aggregate": aggregate}, role)


def tool_query_mcp_log(role: str, limit: int = 50) -> dict[str, Any]:
    """Return recent MCP audit entries, projected and redacted by role.

    Exposing the audit log through the audited surface is deliberate: the
    caller's own read of it is itself logged.

    The audit log is a *second, indirect path* to the same data the primary
    tools guard, because it stores the previous caller's arguments and
    citations. If it were only key-name redacted, a ``public`` caller could
    recover an account number simply by reading what a ``fraud_ops`` caller
    asked. Each row therefore goes through :func:`mcp.redaction.project_log_entry`
    — a whitelist — before the ordinary redactor runs over the result as a
    second layer.

    Args:
        role: Caller role.
        limit: Maximum rows.

    Returns:
        ``{"entries": [...], "count": n}``, projected then redacted.
    """
    entries = [project_log_entry(entry, role) for entry in fetch_mcp_log(limit=limit)]
    return redact_by_role({"entries": entries, "count": len(entries)}, role)


def _safe_select(client: Any, table: str, columns: str) -> Any:
    """Run a select, returning an empty stand-in response on failure."""
    try:
        return client.table(table).select(columns).execute()
    except Exception:
        logger.info("mcp: select unavailable for %s (migration not applied?)", table)
        return None


async def tool_ask_transafe(role: str, question: str) -> dict[str, Any]:
    """Natural-language entry point — routes through the Liaison Agent.

    The tool callables handed to the agent are role-bound closures, so the
    agent cannot widen its own entitlement by choosing different arguments.

    Args:
        role: Caller role.
        question: The natural-language question.

    Returns:
        ``{"answer", "citations", "confidence", "trace"}``.
    """
    from src.enterprise.liaison_agent import ask_transafe as _ask

    tools: dict[str, Any] = {}
    if can_access(role, "campaign"):
        tools["list_active_campaigns"] = lambda **kw: tool_list_active_campaigns(role, **kw)
        tools["get_campaign"] = lambda **kw: tool_get_campaign(role, **kw)
    if can_access(role, "cases"):
        tools["get_case_evidence"] = lambda **kw: tool_get_case_evidence(role, **kw)
    if can_access(role, "artifacts"):
        tools["get_artifact"] = lambda **kw: tool_get_artifact(role, **kw)
    if can_access(role, "indicators"):
        tools["check_indicator"] = lambda **kw: tool_check_indicator(role, **kw)
    tools["query_stats"] = lambda **kw: tool_query_stats(role, **kw)

    return await _ask(question, role, tools)


# ── Tool schemas ─────────────────────────────────────────────────────────────
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "ask_transafe",
        "description": (
            "Ask TranSafe a natural-language question about fraud campaigns, cases, "
            "indicators, or defense artifacts. Routes through the Liaison Agent for "
            "retrieval and synthesis; returns a cited answer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"},
                "role": {"type": "string", "description": "Caller role", "default": DEFAULT_ROLE},
            },
            "required": ["question"],
        },
    },
    {
        "name": "list_active_campaigns",
        "description": "List all active fraud campaigns. Alias: query_campaigns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": (
                        "Narrow the result to one exact status. Valid values: "
                        "APPROVED, ACTIVE. Omit to get the whole active set — "
                        "that is what the tool already means, so only pass this "
                        "to exclude one of the two."
                    ),
                },
            },
        },
    },
    {
        "name": "get_campaign",
        "description": (
            "Get full campaign details: MO, cases, artifacts, timeline. Alias: query_campaign."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "Campaign UUID"},
            },
            "required": ["campaign_id"],
        },
    },
    {
        "name": "get_case_evidence",
        "description": "Get a redacted evidence bundle for a specific case. Alias: query_case.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "description": "Case UUID"},
            },
            "required": ["case_id"],
        },
    },
    {
        "name": "get_artifact",
        "description": (
            "Get artifact content for a named defense artifact. Alias: query_artifact."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Artifact name"},
                "version": {"type": "integer", "description": "Version (latest if omitted)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "check_indicator",
        "description": "Check if an account, phone, URL or domain is known to TranSafe.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "indicator_type": {
                    "type": "string",
                    "description": "PHONE, ACCOUNT, URL, or DOMAIN",
                },
                "value": {"type": "string", "description": "The indicator value to check"},
            },
            "required": ["indicator_type", "value"],
        },
    },
    {
        "name": "query_stats",
        "description": (
            "Aggregate fraud-intelligence statistics: case, entity, link, campaign and "
            "artifact counts. Available to every role."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_mcp_log",
        "description": "Recent MCP audit-log entries. Reading the log is itself audited.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum rows", "default": 50},
            },
        },
    },
]


def list_tool_definitions() -> list[dict[str, Any]]:
    """Return the MCP tool schemas advertised to clients."""
    return [dict(definition) for definition in TOOL_DEFINITIONS]


def resolve_tool_name(tool_name: str) -> str:
    """Resolve an alias to its canonical tool name.

    Args:
        tool_name: Name as requested by the caller.

    Returns:
        The canonical tool name, or the input unchanged when it is not an alias.
    """
    return TOOL_ALIASES.get(tool_name, tool_name)


# ── Dispatch ─────────────────────────────────────────────────────────────────
async def _dispatch(tool: str, arguments: dict[str, Any], role: str) -> dict[str, Any]:
    """Invoke one canonical tool. Blocking tools run off the event loop."""
    if tool == "ask_transafe":
        return await tool_ask_transafe(role, str(arguments.get("question", "")))
    if tool == "list_active_campaigns":
        return await asyncio.to_thread(
            tool_list_active_campaigns, role, arguments.get("status")
        )
    if tool == "get_campaign":
        return await asyncio.to_thread(tool_get_campaign, role, arguments["campaign_id"])
    if tool == "get_case_evidence":
        return await asyncio.to_thread(tool_get_case_evidence, role, arguments["case_id"])
    if tool == "get_artifact":
        return await asyncio.to_thread(
            tool_get_artifact, role, arguments["name"], arguments.get("version")
        )
    if tool == "check_indicator":
        return await asyncio.to_thread(
            tool_check_indicator, role, arguments["indicator_type"], arguments["value"]
        )
    if tool == "query_stats":
        return await asyncio.to_thread(tool_query_stats, role)
    if tool == "query_mcp_log":
        return await asyncio.to_thread(tool_query_mcp_log, role, int(arguments.get("limit", 50)))
    raise KeyError(tool)


async def _audit(
    caller: str,
    role: str,
    tool: str,
    params: dict[str, Any],
    latency_ms: int,
    citations: Any = None,
    outcome: str = "ok",
) -> None:
    """Persist an audit row and emit its ns_event. Never raises.

    The emit is deliberately **not** gated on the write succeeding, but it does
    carry the write's outcome. These are two different stores and the failure
    that matters is when they disagree: ``log_mcp_access`` swallows its own
    errors and returns ``False``, so discarding that return would let Screen G
    paint a healthy ``mcp_call`` for a call that left no audit row — a console
    selling an auditable access trail, showing traffic and recording none.

    Suppressing the event instead would make the access itself invisible, which
    is worse: the point of the trail is that a call is never unobserved. So the
    event is always emitted, ``audit_persisted`` states whether the durable row
    exists, and a failed write escalates severity to ``error`` regardless of
    how the tool call itself resolved.
    """
    persisted = False
    try:
        persisted = bool(
            await asyncio.to_thread(
                log_mcp_access, caller, role, tool, params, latency_ms, citations, outcome
            )
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("mcp: audit write failed for %s/%s", caller, tool)

    if not persisted:
        logger.error(
            "mcp: audit row NOT persisted for %s/%s (outcome=%s); "
            "ns_event will be emitted with audit_persisted=false",
            caller,
            tool,
            outcome,
        )

    # ``critical``, not ``error``: the vocabulary is info|warning|critical and
    # build_event() silently coerces anything else to ``info`` — which would
    # render a lost audit row as the most benign thing on the feed, restoring
    # the exact invisibility this function exists to remove.
    if not persisted:
        severity = "critical"
    elif outcome == "ok":
        severity = "info"
    else:
        severity = "warning"

    try:
        await emit_event(
            layer="exposure",
            event_type="mcp_call",
            payload={
                "caller": caller,
                "role": role,
                "tool": tool,
                "params": params,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "citations": _citation_ids(citations),
                "redacted": redacted_categories_for(role),
                "audit_persisted": persisted,
            },
            severity=severity,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("mcp: ns_event emit failed for %s/%s", caller, tool)


async def handle_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    caller: str = DEFAULT_CALLER,
    role: str = DEFAULT_ROLE,
) -> dict[str, Any]:
    """Handle one MCP tool call: rate limit, entitle, dispatch, audit.

    Every exit path — including rate limiting, denial, an unknown tool and an
    unhandled exception — writes an audit row and emits an ``mcp_call``
    ns_event before returning. Errors are returned as ``{"error": ...}``
    payloads; no exception is allowed to escape onto the transport.

    Args:
        tool_name: Tool requested by the caller (aliases accepted).
        arguments: Tool arguments.
        caller: Caller identifier, used as the rate-limit key.
        role: Caller role, used for entitlement and redaction.

    Returns:
        The tool response dict, or ``{"error": ...}``.
    """
    args = dict(arguments or {})
    start = time.time()

    def _elapsed() -> int:
        return int((time.time() - start) * 1000)

    # 1. Rate limit — checked before anything else, so a flood cannot be used
    #    to drive load into the database.
    if not check_rate_limit(caller):
        await _audit(caller, role, tool_name, args, _elapsed(), outcome="rate_limited")
        return {
            "error": "rate_limit_exceeded",
            "message": (
                f"Rate limit of {RATE_LIMIT_PER_MINUTE} calls per minute exceeded for "
                f"caller {caller!r}. Retry in under a minute."
            ),
            "retry_after_seconds": int(RATE_LIMIT_WINDOW_SECONDS),
        }

    # 2. Resolve alias and check the tool exists.
    tool = resolve_tool_name(tool_name)
    if tool not in TOOL_REQUIREMENTS:
        await _audit(caller, role, tool_name, args, _elapsed(), outcome="unknown_tool")
        return {"error": f"Unknown tool: {tool_name}"}

    # 3. Entitlement — denied is a first-class, audited outcome.
    required = TOOL_REQUIREMENTS[tool]
    if not can_access(role, required):
        await _audit(caller, role, tool_name, args, _elapsed(), outcome="denied")
        return {
            "error": "forbidden",
            "message": (
                f"Role {role!r} is not entitled to {tool!r} "
                f"(requires access to {required!r})."
            ),
            "role": role,
            "tool": tool,
        }

    # 4. Dispatch.
    try:
        result = await _dispatch(tool, args, role)
    except KeyError as exc:
        await _audit(caller, role, tool_name, args, _elapsed(), outcome="error")
        return {"error": f"Missing required argument: {exc}"}
    except Exception as exc:
        logger.exception("mcp: tool %s failed", tool)
        await _audit(caller, role, tool_name, args, _elapsed(), outcome="error")
        return {"error": str(exc)}

    citations = result.get("citations") if isinstance(result, dict) else None
    # Some entitlement gates live *inside* a tool because they depend on the
    # record fetched — the artifact-type gate cannot fire until the artifact's
    # type is known. Those are denials too, and an audit log that filed them
    # under "ok" would misreport exactly the events worth investigating.
    denied = isinstance(result, dict) and result.get("error") == "forbidden"
    await _audit(
        caller,
        role,
        tool_name,
        args,
        _elapsed(),
        citations=citations,
        outcome="denied" if denied else "ok",
    )
    return result


# ── stdio JSON-RPC transport ─────────────────────────────────────────────────
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "transafe", "version": "2.0.0"}


def _rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC success envelope."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build a JSON-RPC error envelope."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def handle_rpc(
    request: dict[str, Any],
    caller: str = DEFAULT_CALLER,
    role: str = DEFAULT_ROLE,
) -> dict[str, Any] | None:
    """Handle one JSON-RPC request.

    Args:
        request: Decoded JSON-RPC request object.
        caller: Caller identifier for auditing and rate limiting.
        role: Caller role.

    Returns:
        The response object, or ``None`` for notifications (which take no
        reply per JSON-RPC).
    """
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _rpc_result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return _rpc_result(request_id, {})

    if method == "tools/list":
        return _rpc_result(request_id, {"tools": list_tool_definitions()})

    if method == "tools/call":
        arguments = dict(params.get("arguments") or {})
        # A caller may name its own role, but only downward: the process-level
        # role is the ceiling, so an argument cannot escalate entitlement.
        requested_role = str(arguments.pop("role", role) or role)
        effective_role = _narrower_role(role, requested_role)
        result = await handle_tool_call(
            str(params.get("name", "")), arguments, caller=caller, role=effective_role
        )
        return _rpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, default=str, indent=2)}],
                "isError": bool(isinstance(result, dict) and result.get("error")),
            },
        )

    return _rpc_error(request_id, -32601, f"Method not found: {method}")


def _narrower_role(process_role: str, requested_role: str) -> str:
    """Return whichever of the two roles is not broader than the other.

    A caller may voluntarily downgrade itself (a ``fraud_ops`` process asking
    a question "as compliance" to preview the redaction), but a request
    argument can never grant entitlement the process was not launched with.

    Args:
        process_role: Role from the server environment.
        requested_role: Role named in the tool arguments.

    Returns:
        ``requested_role`` when it is a subset of ``process_role``'s
        entitlement, otherwise ``process_role``.
    """
    from mcp.redaction import visibility_for

    if requested_role == process_role:
        return process_role
    if visibility_for(requested_role) <= visibility_for(process_role):
        return requested_role
    logger.warning(
        "mcp: refused role escalation %r → %r; using %r",
        process_role,
        requested_role,
        process_role,
    )
    return process_role


async def serve_stdio(
    caller: str | None = None,
    role: str | None = None,
) -> None:  # pragma: no cover - transport loop
    """Run the MCP server over line-delimited JSON-RPC on stdin/stdout.

    Args:
        caller: Caller identifier; defaults to ``$TRANSAFE_CALLER``.
        role: Process role ceiling; defaults to ``$TRANSAFE_ROLE``.
    """
    caller = caller or os.getenv("TRANSAFE_CALLER", DEFAULT_CALLER)
    role = role or os.getenv("TRANSAFE_ROLE", DEFAULT_ROLE)
    logger.info("TranSafe MCP server ready (caller=%s role=%s)", caller, role)

    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _write(_rpc_error(None, -32700, "Parse error"))
            continue

        try:
            response = await handle_rpc(request, caller=caller, role=role)
        except Exception as exc:
            logger.exception("mcp: unhandled RPC failure")
            response = _rpc_error(request.get("id"), -32603, f"Internal error: {exc}")

        if response is not None:
            _write(response)


def _write(payload: dict[str, Any]) -> None:  # pragma: no cover - transport loop
    """Write one JSON-RPC message to stdout and flush."""
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def _load_env() -> None:
    """Load ``backend/.env`` before serving.

    ``main.py`` calls ``load_dotenv()`` for the API process, but this server is
    normally launched by an *external MCP client* as its own subprocess, with
    whatever environment that client happens to have — which is empty of
    Supabase credentials. Without this, ``initialize`` and ``tools/list`` still
    succeed (they touch nothing), so the client happily reports the server as
    connected, and then **every tool call** fails with
    ``RuntimeError: Supabase client is not initialized``.

    Not overridden: anything already in the environment wins, so the
    ``TRANSAFE_ROLE`` / ``TRANSAFE_CALLER`` set by the client config cannot be
    clobbered by this file. Entitlement must be decided by how the client
    launched us, not by whatever happens to be on disk.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a runtime dependency
        logger.warning("mcp: python-dotenv unavailable; relying on the inherited environment")
        return
    load_dotenv(os.path.join(_BACKEND_ROOT, ".env"), override=False)


def main() -> None:  # pragma: no cover - process entry point
    """Process entry point for ``python -m mcp.server``."""
    _load_env()
    logging.basicConfig(level=os.getenv("TRANSAFE_LOG_LEVEL", "INFO"), stream=sys.stderr)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve_stdio())


if __name__ == "__main__":  # pragma: no cover
    main()
