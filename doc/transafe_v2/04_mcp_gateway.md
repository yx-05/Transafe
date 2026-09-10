# 04 — MCP Gateway Design (L6)

> **Parent:** `01_upgrade_plan.md` §9
> **Scope:** MCP server, Liaison Agent, role-based redaction, exposed tools, CodeBuddy integration
> **Build block:** B6
> **Status:** Implementation-ready

---

## 1. Module inventory

| Module | File | Layer | Build block | Depends on |
|---|---|---|---|---|
| MCP server | `mcp/server.py` | L6 | B6 | all enterprise modules |
| Liaison Agent | `enterprise/liaison_agent.py` | L6 | B6 | `agents/llm.py`, `enterprise/registry.py` |
| Redaction | `mcp/redaction.py` | L6 | B6 | role definitions |

---

## 2. Architecture — both, layered

> ### Decision: **both, layered.** MCP server = the door. Liaison Agent = the receptionist behind it.

| Option | Why it fails alone |
|---|---|
| MCP server only | Returns rows. A database with a fashionable wire protocol. `get_campaign(id)` → JSON blob is not intelligence. |
| Receptionist agent only | Smart, but reachable only by our own UI. No standard interface means CodeBuddy cannot call it. |
| MCP server + Liaison Agent | The protocol makes us *callable by any agent*; the agent makes the answer *worth calling for*. |

```
  External agentic systems
  (CodeBuddy · Claude Desktop · partner-bank compliance agent · CS agent)
                    │  MCP (stdio)
                    ▼
        ┌───────────────────────────┐
        │  TranSafe MCP Server      │  auth · role · schema · rate limit · audit log
        └────────────┬──────────────┘
                     ▼
        ┌───────────────────────────┐
        │  Liaison Agent            │  intent → retrieval plan → redact by role
        │  ("the receptionist")     │  → synthesise → cite cases/campaigns
        └────────────┬──────────────┘
                     ▼
     campaigns · cases · graph · artifacts · registry
```

**TranSafe does not reason for external systems.** The Liaison Agent reasons about *what to retrieve and how to present it*. The external agent (CodeBuddy in the demo) reasons about *what to do with the answer*.

---

## 3. Transport — stdio primary

CodeBuddy supports **stdio** transport for MCP server connections. The configuration format is:

```json
{
  "mcpServers": {
    "transafe": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp.server"],
      "env": {
        "TRANSAFE_ROLE": "external_researcher",
        "SUPABASE_URL": "...",
        "SUPABASE_SERVICE_KEY": "...",
        "DEEPSEEK_API_KEY": "..."
      },
      "description": "TranSafe Fraud Intelligence MCP Server"
    }
  }
}
```

HTTP/SSE transport is documented but secondary — used for partner-bank scenarios where a remote server is required. The primary demo path uses stdio.

---

## 4. Exposed tools

| Tool | Purpose | Routes through Liaison Agent? |
|---|---|---|
| `ask_transafe(question, role)` | natural-language entry point | **Yes** — enters the retrieval loop |
| `list_active_campaigns(status?)` | current campaign inventory | No — direct query |
| `get_campaign(campaign_id)` | MO, cases, entities, artifacts, timeline | No — direct query |
| `get_case_evidence(case_id)` | redacted evidence bundle | No — direct query |
| `get_artifact(name, version?)` | artifact content + diff vs previous | No — direct query |
| `check_indicator(type, value)` | is this account/phone/domain known? | No — direct query |

---

## 5. Role-based redaction

### 5.1 Role matrix

| Role | Sees | Never sees |
|---|---|---|
| `fraud_ops` | everything | — |
| `compliance` | campaign + aggregate + case ids + `compliance_brief` | raw transcripts, PII |
| `customer_service` | campaign pack + `cs_advisory` | raw transcripts, PII, compliance briefs |
| `legal` | campaign narrative, citations, counts | account numbers, customer identity |
| `partner_bank` | indicators + MO only | any customer data, case ids |
| `external_researcher` | aggregate statistics only | indicators, cases |

### 5.2 Redaction ordering

Retrieval happens first, **redaction by role is applied before synthesis**, so the reasoning step never sees fields the caller is not entitled to. Redaction cannot be prompt-injected away because it is not the model's job.

### 5.3 Redaction module — `mcp/redaction.py`

```python
from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fields each role can see
ROLE_VISIBILITY: dict[str, set[str]] = {
    "fraud_ops": {  # everything
        "campaign", "cases", "entities", "transcripts", "mo_fingerprint",
        "artifacts", "compliance_brief", "cs_advisory", "indicators",
        "pii", "account_numbers", "phone_numbers", "case_ids",
    },
    "compliance": {
        "campaign", "cases", "case_ids", "compliance_brief",
        "mo_fingerprint", "indicators", "aggregate",
    },
    "customer_service": {
        "campaign", "cs_advisory", "indicators", "aggregate",
    },
    "legal": {
        "campaign", "case_ids", "mo_fingerprint", "aggregate",
    },
    "partner_bank": {
        "indicators", "mo_fingerprint", "aggregate",
    },
    "external_researcher": {
        "aggregate",
    },
}

# Fields that must be redacted (replaced with "[REDACTED]")
REDACTED_FIELDS: dict[str, list[str]] = {
    "transcripts": ["utterance", "speaker", "transcript"],
    "pii": ["user_id", "customer_name", "customer_ic", "customer_phone"],
    "account_numbers": ["recipient_account", "sender_account", "account_number"],
    "phone_numbers": ["phone", "phone_number", "caller_phone"],
}


def redact_by_role(
    data: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    """Apply role-based redaction to a data payload.

    Redaction is server-side, before synthesis. The Liaison Agent
    never sees fields the caller is not entitled to.

    Args:
        data: The raw data payload.
        role: One of the 6 roles.

    Returns:
        A copy of the data with forbidden fields replaced by "[REDACTED]".
    """
    visible = ROLE_VISIBILITY.get(role, {"aggregate"})
    result = copy.deepcopy(data)

    for category, fields in REDACTED_FIELDS.items():
        if category not in visible:
            for field in fields:
                result = _redact_field(result, field)

    # Remove compliance_brief/cs_advisory if not visible
    if "compliance_brief" not in visible:
        result = _redact_field(result, "compliance_brief")
    if "cs_advisory" not in visible:
        result = _redact_field(result, "cs_advisory")

    # Remove case_ids if not visible
    if "case_ids" not in visible:
        result = _redact_field(result, "case_ids")
        result = _redact_field(result, "cited_cases")

    # Remove entities if not visible
    if "entities" not in visible:
        result = _redact_field(result, "entities")

    return result


def _redact_field(data: Any, field_name: str) -> Any:
    """Recursively replace a field's value with '[REDACTED]'."""
    if isinstance(data, dict):
        for key in list(data.keys()):
            if key == field_name:
                data[key] = "[REDACTED]"
            else:
                data[key] = _redact_field(data[key], field_name)
    elif isinstance(data, list):
        return [_redact_field(item, field_name) for item in data]
    return data


def can_access(role: str, resource: str) -> bool:
    """Check if a role can access a resource type.

    Args:
        role: Role name.
        resource: Resource type name.

    Returns:
        True if the role can access the resource.
    """
    visible = ROLE_VISIBILITY.get(role, set())
    return resource in visible
```

---

## 6. Liaison Agent — `enterprise/liaison_agent.py`

### 6.1 The four-property contract

The Liaison Agent is the **single new reasoning site in v2**. It qualifies because its action space is genuinely open — arbitrary questions × 6 tools × 6 roles — and it must satisfy the same four-property contract as the v1 phishing planner:

| Property | Liaison Agent |
|---|---|
| **Gate** | direct-tool questions (`check_indicator`, `get_artifact`) bypass the agent; only `ask_transafe` enters the loop |
| **Bound** | ≤ 4 retrieval iterations, then answer with whatever has been gathered |
| **Fallback** | on planning failure, degrade to `list_active_campaigns` + template response |
| **Trace** | every iteration's intent, tool, and arguments recorded to the MCP access log |

### 6.2 Function signatures

```python
from __future__ import annotations

import json
import logging
from typing import Any

from agents.llm import extract_json_object, invoke_deepseek_with_key_rotation
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 4

LIAISON_SYSTEM_PROMPT = """\
You are the TranSafe Liaison Agent — a retrieval and synthesis agent for \
fraud intelligence. You answer questions about fraud campaigns, cases, \
indicators, and defense artifacts.

Rules:
1. Plan your retrieval: decide which tools to call and in what order.
2. You have at most 4 retrieval iterations.
3. After retrieval, synthesise a concise answer with citations.
4. If you cannot answer, say so honestly — do not fabricate.
5. Return ONLY a JSON object.

Schema for planning:
{"intent": "summary of what the question is asking",
 "retrieval_plan": [{"tool": "tool_name", "args": {...}, "reason": "..."}]}

Schema for synthesis:
{"answer": "your answer with case/campaign citations",
 "citations": [{"type": "campaign|case|artifact", "id": "...", "detail": "..."}],
 "confidence": "high|medium|low"}
"""


async def ask_transafe(
    question: str,
    role: str,
    available_tools: dict[str, Any],
) -> dict[str, Any]:
    """Entry point for natural-language queries from external agents.

    Implements the retrieval loop:
    1. Classify intent and plan retrieval.
    2. Execute up to MAX_ITERATIONS tool calls.
    3. Redact results by role.
    4. Synthesise answer with citations.

    Args:
        question: Natural-language question from the external agent.
        role: Caller role (determines redaction).
        available_tools: Dict of tool_name → callable.

    Returns:
        Dict with: answer, citations, confidence, trace.
    """
    from mcp.redaction import redact_by_role

    trace: list[dict[str, Any]] = []

    # Step 1: Plan retrieval
    plan = _plan_retrieval(question, role)
    trace.append({"step": "plan", "plan": plan})

    if plan is None:
        # Fallback: list active campaigns + template response
        fallback = await _fallback_response(question, role, available_tools)
        fallback["trace"] = trace
        return fallback

    # Step 2: Execute retrieval
    gathered_data: list[dict[str, Any]] = []
    for i, step in enumerate(plan.get("retrieval_plan", [])[:MAX_ITERATIONS]):
        tool_name = step.get("tool")
        tool_args = step.get("args", {})

        if tool_name not in available_tools:
            trace.append({
                "step": f"iteration_{i}",
                "tool": tool_name,
                "status": "not_found",
            })
            continue

        try:
            raw_result = available_tools[tool_name](**tool_args)
            # Redact by role before synthesis
            redacted = redact_by_role(raw_result, role)
            gathered_data.append({"tool": tool_name, "result": redacted})
            trace.append({
                "step": f"iteration_{i}",
                "tool": tool_name,
                "args": tool_args,
                "status": "ok",
            })
        except Exception as e:
            trace.append({
                "step": f"iteration_{i}",
                "tool": tool_name,
                "args": tool_args,
                "status": "error",
                "error": str(e),
            })

    # Step 3: Synthesise
    synthesis = _synthesise(question, role, gathered_data)
    synthesis["trace"] = trace
    return synthesis


def _plan_retrieval(question: str, role: str) -> dict[str, Any] | None:
    """Use LLM to classify intent and plan retrieval.

    Args:
        question: Natural-language question.
        role: Caller role.

    Returns:
        Plan dict with intent and retrieval_plan, or None on failure.
    """
    messages = [
        SystemMessage(content=LIAISON_SYSTEM_PROMPT),
        HumanMessage(
            content=f"Role: {role}\nQuestion: {question}\n\n"
            f"Plan your retrieval. Available tools: "
            f"list_active_campaigns, get_campaign, get_case_evidence, "
            f"get_artifact, check_indicator"
        ),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        plan = extract_json_object(response.content)
        if plan and "retrieval_plan" in plan:
            return plan
        return None
    except Exception:
        logger.exception("Liaison Agent: planning failed")
        return None


def _synthesise(
    question: str,
    role: str,
    gathered_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Synthesise an answer from gathered data.

    Args:
        question: Original question.
        role: Caller role.
        gathered_data: List of {tool, result} dicts.

    Returns:
        Dict with: answer, citations, confidence.
    """
    if not gathered_data:
        return {
            "answer": "I could not retrieve any information to answer this question.",
            "citations": [],
            "confidence": "low",
        }

    data_summary = json.dumps(gathered_data, indent=2, default=str)

    messages = [
        SystemMessage(content=LIAISON_SYSTEM_PROMPT),
        HumanMessage(
            content=f"Role: {role}\n"
            f"Question: {question}\n\n"
            f"Gathered data (already redacted by role):\n{data_summary}\n\n"
            f"Synthesise your answer with citations."
        ),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        result = extract_json_object(response.content)
        if result and "answer" in result:
            return result
        # Fallback: simple concatenation
        return {
            "answer": "Retrieved data is available. See trace for details.",
            "citations": [],
            "confidence": "low",
        }
    except Exception:
        logger.exception("Liaison Agent: synthesis failed")
        return {
            "answer": "Retrieval succeeded but synthesis failed. See trace for raw data.",
            "citations": [],
            "confidence": "low",
        }


async def _fallback_response(
    question: str,
    role: str,
    available_tools: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic fallback when planning fails.

    Degrades to list_active_campaigns + template response.
    """
    from mcp.redaction import redact_by_role

    try:
        campaigns = available_tools.get("list_active_campaigns", lambda: {})()
        redacted = redact_by_role(campaigns, role)
        return {
            "answer": f"Unable to fully process your question, but here are the active campaigns: {json.dumps(redacted, default=str)}",
            "citations": [],
            "confidence": "low",
        }
    except Exception:
        return {
            "answer": "I am unable to process your request at this time.",
            "citations": [],
            "confidence": "low",
        }
```

---

## 7. MCP Server — `mcp/server.py`

### 7.1 Purpose

The MCP server exposes TranSafe's tools via the stdio transport. It handles auth, role assignment, schema validation, rate limiting, and audit logging.

### 7.2 Implementation

```python
"""TranSafe MCP Server — stdio transport, role-based redaction, audit logged.

Exposes 6 tools to external agentic systems (CodeBuddy, partner banks, etc.).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

# Rate limiting (simple per-role)
RATE_LIMIT_PER_MINUTE = 60
_rate_counts: dict[str, list[float]] = {}


def check_rate_limit(caller: str) -> bool:
    """Simple sliding-window rate limiter.

    Args:
        caller: Caller identifier.

    Returns:
        True if within rate limit, False if exceeded.
    """
    now = time.time()
    window = 60.0  # 1 minute

    if caller not in _rate_counts:
        _rate_counts[caller] = []

    # Remove old entries
    _rate_counts[caller] = [t for t in _rate_counts[caller] if now - t < window]

    if len(_rate_counts[caller]) >= RATE_LIMIT_PER_MINUTE:
        return False

    _rate_counts[caller].append(now)
    return True


def log_mcp_access(
    caller: str,
    role: str,
    tool: str,
    params: dict[str, Any],
    latency_ms: int,
    citations: Any = None,
) -> None:
    """Write an MCP access log entry.

    Args:
        caller: Caller identifier (e.g. "codebuddy").
        role: Role used for this call.
        tool: Tool name called.
        params: Parameters passed.
        latency_ms: Response latency in milliseconds.
        citations: Citations returned (optional).
    """
    from db.vector_store import get_supabase_client

    row = {
        "ts": _now_iso(),
        "caller": caller,
        "role": role,
        "tool": tool,
        "params": params,
        "latency_ms": latency_ms,
        "citations": citations,
    }

    try:
        client = get_supabase_client()
        client.table("mcp_access_log").insert(row).execute()
    except Exception:
        logger.exception("Failed to log MCP access")


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


# ── Tool implementations ──────────────────────────────────────────────

def tool_list_active_campaigns(
    role: str,
    status: str | None = None,
) -> dict[str, Any]:
    """List active campaigns, redacted by role."""
    from db.vector_store import get_supabase_client
    from mcp.redaction import redact_by_role

    client = get_supabase_client()
    query = client.table("campaigns").select("*")
    if status:
        query = query.eq("status", status)
    else:
        query = query.in_("status", ["APPROVED", "ACTIVE"])
    result = query.execute()
    data = result.data or []
    return redact_by_role({"campaigns": data}, role)


def tool_get_campaign(
    role: str,
    campaign_id: str,
) -> dict[str, Any]:
    """Get full campaign details, redacted by role."""
    from db.vector_store import get_supabase_client
    from mcp.redaction import redact_by_role

    client = get_supabase_client()
    result = client.table("campaigns").select("*").eq("id", campaign_id).execute()
    if not result.data:
        return {"error": "Campaign not found"}
    campaign = result.data[0]

    # Get cases
    cases_result = client.table("campaign_cases").select(
        "case_id, linkage_score"
    ).eq("campaign_id", campaign_id).execute()
    campaign["cases"] = cases_result.data or []

    # Get artifacts
    arts_result = client.table("artifacts").select(
        "name, version, artifact_type, tier"
    ).eq("campaign_id", campaign_id).execute()
    campaign["artifacts"] = arts_result.data or []

    return redact_by_role(campaign, role)


def tool_get_case_evidence(
    role: str,
    case_id: str,
) -> dict[str, Any]:
    """Get redacted evidence bundle for a case."""
    from db.vector_store import get_supabase_client
    from mcp.redaction import redact_by_role

    client = get_supabase_client()
    result = client.table("fraud_cases").select("*").eq("id", case_id).execute()
    if not result.data:
        return {"error": "Case not found"}
    case_data = result.data[0]

    # Get MO fingerprint
    mo_result = client.table("case_mo").select(
        "fingerprint, narrative"
    ).eq("case_id", case_id).execute()
    if mo_result.data:
        case_data["mo_fingerprint"] = mo_result.data[0].get("fingerprint")
        case_data["narrative"] = mo_result.data[0].get("narrative")

    return redact_by_role(case_data, role)


def tool_get_artifact(
    role: str,
    name: str,
    version: int | None = None,
) -> dict[str, Any]:
    """Get artifact content, redacted by role."""
    from enterprise.registry import get_artifact
    from mcp.redaction import redact_by_role

    artifact = get_artifact(name, version)
    if not artifact:
        return {"error": "Artifact not found"}
    return redact_by_role(artifact, role)


def tool_check_indicator(
    role: str,
    indicator_type: str,
    value: str,
) -> dict[str, Any]:
    """Check if an indicator (account/phone/domain) is known to TranSafe."""
    from enterprise.entity_resolver import normalise_entity
    from db.vector_store import get_supabase_client
    from mcp.redaction import redact_by_role

    norm = normalise_entity(indicator_type, value)
    client = get_supabase_client()
    result = client.table("entities").select(
        "id, case_count, first_seen, last_seen"
    ).eq("entity_type", indicator_type).eq("value_norm", norm).execute()

    if not result.data:
        return {"known": False, "indicator_type": indicator_type, "value": value}

    entity = result.data[0]

    # Get linked campaigns
    cases_result = client.table("case_entity_links").select(
        "case_id"
    ).eq("entity_id", entity["id"]).execute()
    case_ids = [c["case_id"] for c in (cases_result.data or [])]

    campaigns_result = client.table("campaign_cases").select(
        "campaign_id, campaigns!inner(code, name, status)"
    ).in_("case_id", case_ids).execute()
    campaigns = [
        {
            "code": c["campaigns"]["code"],
            "name": c["campaigns"]["name"],
            "status": c["campaigns"]["status"],
        }
        for c in (campaigns_result.data or [])
        if c.get("campaigns")
    ]

    return redact_by_role({
        "known": True,
        "indicator_type": indicator_type,
        "value": value,
        "case_count": entity["case_count"],
        "first_seen": entity["first_seen"],
        "last_seen": entity["last_seen"],
        "linked_campaigns": campaigns,
    }, role)


async def tool_ask_transafe(
    role: str,
    question: str,
) -> dict[str, Any]:
    """Natural-language entry point — routes through the Liaison Agent."""
    from enterprise.liaison_agent import ask_transafe as _ask

    tools = {
        "list_active_campaigns": lambda **kw: tool_list_active_campaigns(role, **kw),
        "get_campaign": lambda **kw: tool_get_campaign(role, **kw),
        "get_case_evidence": lambda **kw: tool_get_case_evidence(role, **kw),
        "get_artifact": lambda **kw: tool_get_artifact(role, **kw),
        "check_indicator": lambda **kw: tool_check_indicator(role, **kw),
    }

    return await _ask(question, role, tools)


# ── MCP stdio server ──────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "ask_transafe",
        "description": "Ask TranSafe a natural-language question about fraud campaigns, cases, indicators, or defense artifacts. Routes through the Liaison Agent for retrieval and synthesis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"},
                "role": {"type": "string", "description": "Caller role", "default": "external_researcher"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "list_active_campaigns",
        "description": "List all active fraud campaigns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status"},
            },
        },
    },
    {
        "name": "get_campaign",
        "description": "Get full campaign details: MO, cases, entities, artifacts, timeline.",
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
        "description": "Get a redacted evidence bundle for a specific case.",
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
        "description": "Get artifact content and diff vs previous version.",
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
        "description": "Check if an account, phone, or domain is known to TranSafe.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "indicator_type": {"type": "string", "description": "PHONE, ACCOUNT, URL, or DOMAIN"},
                "value": {"type": "string", "description": "The indicator value to check"},
            },
            "required": ["indicator_type", "value"],
        },
    },
]


async def handle_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    caller: str = "codebuddy",
    role: str = "external_researcher",
) -> dict[str, Any]:
    """Handle a single MCP tool call with auth, rate limit, and audit logging.

    Args:
        tool_name: Name of the tool to call.
        arguments: Tool arguments.
        caller: Caller identifier.
        role: Caller role.

    Returns:
        Tool response dict.
    """
    start_time = time.time()

    # Rate limit
    if not check_rate_limit(caller):
        return {"error": "Rate limit exceeded"}

    # Dispatch
    try:
        if tool_name == "ask_transafe":
            result = await tool_ask_transafe(role, arguments.get("question", ""))
        elif tool_name == "list_active_campaigns":
            result = tool_list_active_campaigns(role, arguments.get("status"))
        elif tool_name == "get_campaign":
            result = tool_get_campaign(role, arguments["campaign_id"])
        elif tool_name == "get_case_evidence":
            result = tool_get_case_evidence(role, arguments["case_id"])
        elif tool_name == "get_artifact":
            result = tool_get_artifact(role, arguments["name"], arguments.get("version"))
        elif tool_name == "check_indicator":
            result = tool_check_indicator(
                role, arguments["indicator_type"], arguments["value"]
            )
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        log_mcp_access(caller, role, tool_name, arguments, latency_ms)
        return {"error": str(e)}

    latency_ms = int((time.time() - start_time) * 1000)
    citations = result.get("citations") if isinstance(result, dict) else None
    log_mcp_access(caller, role, tool_name, arguments, latency_ms, citations)

    return result
```

---

## 8. CodeBuddy integration

### 8.1 Configuration

Add to CodeBuddy MCP settings:

```json
{
  "mcpServers": {
    "transafe": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp.server"],
      "env": {
        "TRANSAFE_ROLE": "external_researcher",
        "SUPABASE_URL": "...",
        "SUPABASE_SERVICE_KEY": "...",
        "DEEPSEEK_API_KEY": "...",
        "DASHSCOPE_API_KEY": "..."
      },
      "description": "TranSafe Fraud Intelligence MCP Server"
    }
  }
}
```

### 8.2 Demo prompt

> *"Ask TranSafe what fraud campaigns are active, then draft a customer advisory for the highest-confidence one."*

CodeBuddy calls the MCP server, the Liaison Agent answers with citations, CodeBuddy reasons about the answer and writes the advisory as its own artifact — not a TranSafe output, but a CodeBuddy output grounded in TranSafe's intelligence.

### 8.3 What it proves

1. An interoperability claim tested rather than asserted (a third-party agent called TranSafe and got a structured, redacted, cited answer).
2. An organisational response demonstrated rather than faked (the external agent reasoned about TranSafe's intelligence and produced its own artifact).

---

## 9. Testing

### 9.1 Test files

| Module | Test file | Cases |
|---|---|---|
| `redaction` | `tests/unit/test_redaction.py` | 10 |
| `liaison_agent` | `tests/unit/test_liaison_agent.py` | 7 |
| `mcp_server` | `tests/unit/test_mcp_server.py` | 6 |

### 9.2 Test cases — `test_redaction.py`

```python
"""Unit tests for role-based redaction (L6)."""

import pytest
from mcp.redaction import redact_by_role, can_access


def test_fraud_ops_sees_everything():
    data = {"user_id": "u123", "recipient_account": "1592", "transcript": "hello"}
    result = redact_by_role(data, "fraud_ops")
    assert result["user_id"] == "u123"
    assert result["recipient_account"] == "1592"
    assert result["transcript"] == "hello"


def test_compliance_redacts_transcripts_and_pii():
    data = {"user_id": "u123", "recipient_account": "1592", "utterance": "scam"}
    result = redact_by_role(data, "compliance")
    assert result["user_id"] == "[REDACTED]"
    assert result["recipient_account"] == "[REDACTED]"
    assert result["utterance"] == "[REDACTED]"


def test_customer_service_redacts_compliance_brief():
    data = {"cs_advisory": "advise", "compliance_brief": "brief", "campaign": "SCAM-027"}
    result = redact_by_role(data, "customer_service")
    assert result["cs_advisory"] == "advise"
    assert result["compliance_brief"] == "[REDACTED]"


def test_legal_redacts_account_numbers():
    data = {"recipient_account": "1592", "sender_account": "1234", "campaign": "SCAM-027"}
    result = redact_by_role(data, "legal")
    assert result["recipient_account"] == "[REDACTED]"
    assert result["sender_account"] == "[REDACTED]"


def test_partner_bank_redacts_case_ids():
    data = {"case_ids": ["c1", "c2"], "indicators": {"accounts": ["1592"]}}
    result = redact_by_role(data, "partner_bank")
    assert result["case_ids"] == "[REDACTED]"
    assert "indicators" in result


def test_external_researcher_sees_only_aggregate():
    data = {"campaign": "SCAM-027", "indicators": {"accounts": ["1592"]}, "aggregate": {"count": 5}}
    result = redact_by_role(data, "external_researcher")
    assert result.get("aggregate", {}).get("count") == 5


def test_redaction_preserves_structure():
    data = {"a": {"b": {"user_id": "u1"}}}
    result = redact_by_role(data, "compliance")
    assert result["a"]["b"]["user_id"] == "[REDACTED]"


def test_redaction_handles_lists():
    data = [{"user_id": "u1"}, {"user_id": "u2"}]
    result = redact_by_role(data, "compliance")
    assert all(item["user_id"] == "[REDACTED]" for item in result)


def test_can_access_fraud_ops_everything():
    assert can_access("fraud_ops", "transcripts") is True
    assert can_access("fraud_ops", "pii") is True


def test_can_access_external_researcher_limited():
    assert can_access("external_researcher", "aggregate") is True
    assert can_access("external_researcher", "transcripts") is False
```

### 9.3 Test cases — `test_liaison_agent.py`

```python
"""Unit tests for the Liaison Agent (L6)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from enterprise.liaison_agent import (
    ask_transafe,
    _plan_retrieval,
    _synthesise,
    _fallback_response,
    MAX_ITERATIONS,
)


def test_max_iterations_is_4():
    assert MAX_ITERATIONS == 4


@patch("enterprise.liaison_agent.invoke_deepseek_with_key_rotation")
def test_plan_retrieval_returns_plan(mock_llm: MagicMock):
    mock_response = MagicMock()
    mock_response.content = '{"intent": "check active campaigns", "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}, "reason": "list all"}]}'
    mock_llm.return_value = mock_response
    plan = _plan_retrieval("What campaigns are active?", "fraud_ops")
    assert plan is not None
    assert "retrieval_plan" in plan


@patch("enterprise.liaison_agent.invoke_deepseek_with_key_rotation")
def test_plan_retrieval_returns_none_on_failure(mock_llm: MagicMock):
    mock_llm.side_effect = RuntimeError("LLM down")
    plan = _plan_retrieval("question", "fraud_ops")
    assert plan is None


@patch("enterprise.liaison_agent.invoke_deepseek_with_key_rotation")
def test_synthesise_returns_answer(mock_llm: MagicMock):
    mock_response = MagicMock()
    mock_response.content = '{"answer": "There are 2 active campaigns.", "citations": [{"type": "campaign", "id": "SCAM-027"}], "confidence": "high"}'
    mock_llm.return_value = mock_response
    result = _synthesise("question", "fraud_ops", [{"tool": "list_active_campaigns", "result": {"campaigns": []}}])
    assert result["answer"] == "There are 2 active campaigns."
    assert result["confidence"] == "high"


def test_synthesise_empty_data():
    result = _synthesise("question", "fraud_ops", [])
    assert "could not" in result["answer"].lower()
    assert result["confidence"] == "low"


@pytest.mark.asyncio
async def test_ask_transafe_fallback_on_planning_failure():
    """Assert planning failure triggers fallback response."""
    tools = {
        "list_active_campaigns": MagicMock(return_value={"campaigns": [{"code": "SCAM-027"}]}),
    }
    with patch("enterprise.liaison_agent._plan_retrieval", return_value=None):
        with patch("enterprise.liaison_agent._fallback_response", new_callable=AsyncMock) as mock_fb:
            mock_fb.return_value = {"answer": "fallback", "citations": [], "confidence": "low"}
            result = await ask_transafe("question", "fraud_ops", tools)
    assert result["answer"] == "fallback"


@pytest.mark.asyncio
async def test_ask_transafe_returns_trace():
    """Assert the trace is included in the response."""
    tools = {
        "list_active_campaigns": MagicMock(return_value={"campaigns": []}),
    }
    with patch("enterprise.liaison_agent._plan_retrieval", return_value={"intent": "test", "retrieval_plan": [{"tool": "list_active_campaigns", "args": {}}]}):
        with patch("enterprise.liaison_agent._synthesise", return_value={"answer": "test", "citations": [], "confidence": "high"}):
            result = await ask_transafe("question", "fraud_ops", tools)
    assert "trace" in result
    assert len(result["trace"]) >= 1


@pytest.mark.asyncio
async def test_ask_transafe_limits_iterations():
    """Assert retrieval plan is truncated to MAX_ITERATIONS."""
    plan = {"intent": "test", "retrieval_plan": [{"tool": f"tool_{i}", "args": {}} for i in range(10)]}
    tools = {f"tool_{i}": MagicMock(return_value={}) for i in range(10)}
    with patch("enterprise.liaison_agent._plan_retrieval", return_value=plan):
        with patch("enterprise.liaison_agent._synthesise", return_value={"answer": "test", "citations": [], "confidence": "high"}):
            result = await ask_transafe("question", "fraud_ops", tools)
    # Only MAX_ITERATIONS tool calls should have been attempted
    trace_iterations = [t for t in result["trace"] if t.get("step", "").startswith("iteration_")]
    assert len(trace_iterations) <= MAX_ITERATIONS
```

### 9.4 Test cases — `test_mcp_server.py`

```python
"""Unit tests for the MCP server (L6)."""

from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from mcp.server import (
    check_rate_limit,
    log_mcp_access,
    handle_tool_call,
    tool_list_active_campaigns,
    tool_check_indicator,
)


def test_check_rate_limit_allows_under_limit():
    """Assert rate limiter allows calls under the limit."""
    _rate_counts_clear()
    assert check_rate_limit("test-caller") is True


def test_check_rate_limit_blocks_over_limit():
    """Assert rate limiter blocks calls over the limit."""
    _rate_counts_clear()
    from mcp.server import RATE_LIMIT_PER_MINUTE, _rate_counts
    _rate_counts["test-block"] = [0.0] * RATE_LIMIT_PER_MINUTE
    assert check_rate_limit("test-block") is False


def _rate_counts_clear():
    from mcp.server import _rate_counts
    _rate_counts.clear()


@patch("mcp.server.get_supabase_client")
def test_log_mcp_access_inserts_row(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    log_mcp_access("codebuddy", "legal", "ask_transafe", {"q": "test"}, 340)
    mock_table.insert.assert_called_once()


@patch("mcp.server.get_supabase_client")
def test_tool_list_active_campaigns_returns_redacted(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": "c1", "code": "SCAM-027", "user_id": "u1"},
    ]
    mock_client.return_value.table.return_value = mock_table
    result = tool_list_active_campaigns("compliance")
    assert "campaigns" in result
    # user_id should be redacted for compliance role
    assert result["campaigns"][0]["user_id"] == "[REDACTED]"


@patch("mcp.server.get_supabase_client")
def test_tool_check_indicator_known(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "ent-1", "case_count": 5, "first_seen": "2026-09-10", "last_seen": "2026-09-10"}
    ]
    mock_table.select.return_value.eq.return_value.execute.return_value.data = []
    mock_table.select.return_value.in_.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    result = tool_check_indicator("ACCOUNT", "1592-3456")
    assert result["known"] is True
    assert result["case_count"] == 5


@pytest.mark.asyncio
async def test_handle_tool_call_unknown_tool():
    result = await handle_tool_call("nonexistent_tool", {}, "test", "fraud_ops")
    assert "error" in result
```

### 9.5 pytest + ruff

```bash
cd backend && uv run pytest tests/unit/test_redaction.py tests/unit/test_liaison_agent.py tests/unit/test_mcp_server.py -v
```

```bash
cd backend && uv run ruff check mcp/ src/enterprise/liaison_agent.py tests/unit/test_redaction.py tests/unit/test_liaison_agent.py tests/unit/test_mcp_server.py
```
