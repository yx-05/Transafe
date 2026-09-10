"""Liaison Agent — L6, the single new reasoning site in v2.

The MCP server is the door; this is the receptionist behind it. It reasons
about *what to retrieve and how to present it* — never about what the caller
should do with the answer. That decision belongs to the external agent.

Four-property contract (01_upgrade_plan.md §9.1, 04_mcp_gateway.md §6.1)
------------------------------------------------------------------------
Gate      Direct-tool questions bypass this module entirely; only
          ``ask_transafe`` enters the loop.
Bound     At most :data:`MAX_ITERATIONS` (4) retrieval iterations, then the
          agent answers with whatever it has gathered.
Fallback  On planning failure it degrades to ``list_active_campaigns`` plus a
          deterministic template answer; on synthesis failure it degrades to a
          deterministic summary built from the retrieved rows. Both still cite
          honestly, and both work with no LLM reachable at all.
Trace     Every iteration's intent, tool and arguments is recorded and returned
          alongside the answer, and written to ``mcp_access_log`` by the caller.

Two invariants make this trustworthy rather than decorative:

1. **Redaction precedes synthesis.** Tool output is passed through
   :func:`mcp.redaction.redact_by_role` *before* it is appended to
   ``gathered_data``, and ``gathered_data`` is the only thing the synthesis
   step ever sees. The model is structurally incapable of reading a field the
   caller is not entitled to — there is no prompt asking it to behave.
2. **Citations are verified against what was actually retrieved.** A citation
   the model invented is dropped into ``dropped_citations`` rather than being
   passed off as evidence, and the answer's stated confidence is lowered to
   match — a model that cited a record that does not exist has demonstrated
   its confidence signal is unreliable for that answer.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.llm import extract_json_object, invoke_deepseek_with_key_rotation

logger = logging.getLogger(__name__)

#: Hard bound on retrieval iterations. Exceeding it is not an error — the agent
#: answers with what it has.
MAX_ITERATIONS = 4

#: Keys whose values are treated as citable record identifiers.
_ID_KEYS: frozenset[str] = frozenset(
    {"id", "code", "case_id", "campaign_id", "entity_id", "name", "artifact_name"}
)

LIAISON_SYSTEM_PROMPT = """\
You are the TranSafe Liaison Agent — a retrieval and synthesis agent for \
fraud intelligence. You answer questions about fraud campaigns, cases, \
indicators, and defense artifacts.

Rules:
1. Plan your retrieval: decide which tools to call and in what order.
2. You have at most 4 retrieval iterations.
3. After retrieval, synthesise a concise answer with citations.
4. Cite ONLY records that appear in the gathered data. Never invent an id.
5. If you cannot answer, say so honestly — do not fabricate.
6. Return ONLY a JSON object.

Schema for planning:
{"intent": "summary of what the question is asking",
 "retrieval_plan": [{"tool": "tool_name", "args": {...}, "reason": "..."}]}

Schema for synthesis:
{"answer": "your answer with case/campaign citations",
 "citations": [{"type": "campaign|case|artifact", "id": "...", "detail": "..."}],
 "confidence": "high|medium|low"}
"""

TOOL_MENU = (
    "list_active_campaigns, get_campaign, get_case_evidence, get_artifact, "
    "check_indicator, query_stats"
)


async def ask_transafe(
    question: str,
    role: str,
    available_tools: dict[str, Any],
) -> dict[str, Any]:
    """Entry point for natural-language queries from external agents.

    The bounded retrieval loop:

    1. Classify intent and plan retrieval (LLM, with a deterministic fallback).
    2. Execute at most :data:`MAX_ITERATIONS` tool calls.
    3. Redact each result by role **before** it is retained.
    4. Synthesise an answer whose citations are verified against step 3.

    Args:
        question: Natural-language question from the external agent.
        role: Caller role — determines redaction. Unknown roles get least
            privilege, they are not rejected.
        available_tools: Mapping of ``tool_name`` → callable. Callables may be
            sync or async; both are supported.

    Returns:
        Dict with ``answer``, ``citations``, ``confidence`` and ``trace``.
    """
    from mcp.redaction import redact_by_role

    trace: list[dict[str, Any]] = []

    # ── Step 1: classify intent and plan retrieval ───────────────────────────
    plan = _plan_retrieval(question, role)
    trace.append({"step": "plan", "plan": plan})

    if plan is None:
        fallback = await _fallback_response(question, role, available_tools)
        fallback["trace"] = trace
        return fallback

    # ── Step 2/3: execute, redacting each result before it is retained ───────
    gathered_data: list[dict[str, Any]] = []
    steps = list(plan.get("retrieval_plan") or [])[:MAX_ITERATIONS]

    for i, step in enumerate(steps):
        tool_name = step.get("tool")
        tool_args = step.get("args") or {}

        if tool_name not in available_tools:
            trace.append({"step": f"iteration_{i}", "tool": tool_name, "status": "not_found"})
            continue

        try:
            raw_result = available_tools[tool_name](**tool_args)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
            # The single security-critical line in this module: redaction
            # happens here, so `gathered_data` — the only input to synthesis —
            # can never carry an unentitled field.
            redacted = redact_by_role(raw_result, role)
            gathered_data.append({"tool": tool_name, "result": redacted})
            trace.append(
                {"step": f"iteration_{i}", "tool": tool_name, "args": tool_args, "status": "ok"}
            )
        except Exception as exc:
            logger.exception("Liaison Agent: tool %s failed", tool_name)
            trace.append(
                {
                    "step": f"iteration_{i}",
                    "tool": tool_name,
                    "args": tool_args,
                    "status": "error",
                    "error": str(exc),
                }
            )

    # ── Step 4: synthesise with verified citations ───────────────────────────
    synthesis = _synthesise(question, role, gathered_data)
    synthesis["trace"] = trace
    return synthesis


def _plan_retrieval(question: str, role: str) -> dict[str, Any] | None:
    """Classify intent and plan retrieval via the LLM.

    Args:
        question: Natural-language question.
        role: Caller role, included so the planner does not plan a retrieval
            whose entire result would be redacted away.

    Returns:
        ``{"intent": ..., "retrieval_plan": [...]}``, or ``None`` when the LLM
        is unreachable or returns something unusable — the signal that the
        caller should take the deterministic fallback path.
    """
    messages = [
        SystemMessage(content=LIAISON_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Role: {role}\nQuestion: {question}\n\n"
                f"Plan your retrieval. Available tools: {TOOL_MENU}"
            )
        ),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        plan = extract_json_object(response.content)
    except Exception:
        logger.exception("Liaison Agent: planning failed")
        return None

    if plan and isinstance(plan.get("retrieval_plan"), list):
        return plan
    return None


def _synthesise(
    question: str,
    role: str,
    gathered_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Synthesise an answer from already-redacted data.

    ``gathered_data`` has passed through :func:`mcp.redaction.redact_by_role`
    before it reaches this function. Nothing here re-fetches, so there is no
    path by which an unentitled value can enter the synthesis input.

    Args:
        question: Original question.
        role: Caller role, for phrasing only — enforcement already happened.
        gathered_data: List of ``{"tool", "result"}`` dicts, already redacted.

    Returns:
        Dict with ``answer``, ``citations``, ``confidence``, and — when the
        model cited something it did not retrieve — ``dropped_citations``
        plus a ``confidence`` lowered by :func:`_downgrade_confidence`.
    """
    if not gathered_data:
        return {
            "answer": "I could not retrieve any information to answer this question.",
            "citations": [],
            "confidence": "low",
        }

    known_ids = _known_record_ids(gathered_data)
    data_summary = json.dumps(gathered_data, indent=2, default=str)

    messages = [
        SystemMessage(content=LIAISON_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Role: {role}\n"
                f"Question: {question}\n\n"
                f"Gathered data (already redacted by role):\n{data_summary}\n\n"
                f"Synthesise your answer with citations."
            )
        ),
    ]

    try:
        response = invoke_deepseek_with_key_rotation(messages)
        result = extract_json_object(response.content)
    except Exception:
        logger.exception("Liaison Agent: synthesis failed — using deterministic synthesis")
        return _deterministic_synthesis(gathered_data)

    if not result or "answer" not in result:
        return _deterministic_synthesis(gathered_data)

    kept, dropped = _verify_citations(result.get("citations"), known_ids)
    result["citations"] = kept
    if dropped:
        logger.warning("Liaison Agent: dropped %d unretrieved citation(s)", len(dropped))
        result["dropped_citations"] = dropped
        result["confidence"] = _downgrade_confidence(result.get("confidence"), kept)
    return result


#: Confidence levels, weakest first. Used only to *lower* a claim, never raise.
_CONFIDENCE_ORDER: tuple[str, ...] = ("low", "medium", "high")


def _downgrade_confidence(stated: Any, kept: list[dict[str, Any]]) -> str:
    """Lower a stated confidence when citations had to be dropped.

    If the model cited evidence that turned out not to exist, its own
    confidence signal is demonstrably unreliable *for this answer* — that is
    the entire reason :func:`_verify_citations` exists. Returning
    ``confidence: "high"`` beside a citation we had to delete is exactly the
    confident-but-unsupported output this gateway exists to prevent, and a
    consumer reading the answer will not cross-reference ``dropped_citations``.

    Args:
        stated: The confidence the model claimed.
        kept: Citations that survived verification.

    Returns:
        ``"low"`` when nothing survived; otherwise the stated confidence
        capped at ``"medium"``. Never higher than what was stated.
    """
    if not kept:
        return "low"

    ceiling = "medium"
    current = str(stated or "").lower()
    if current not in _CONFIDENCE_ORDER:
        return ceiling
    return min(current, ceiling, key=_CONFIDENCE_ORDER.index)


async def _fallback_response(
    question: str,
    role: str,
    available_tools: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic fallback used when planning fails.

    Degrades to a single ``list_active_campaigns`` call plus a template answer.
    The result is still redacted by role and still cited from real rows; when
    nothing can be retrieved it says so rather than inventing a citation.

    Args:
        question: Original question, echoed so the caller sees what was asked.
        role: Caller role.
        available_tools: Mapping of ``tool_name`` → callable.

    Returns:
        Dict with ``answer``, ``citations``, ``confidence`` and ``degraded``.
    """
    from mcp.redaction import redact_by_role

    lister = available_tools.get("list_active_campaigns")
    if lister is None:
        return _cannot_answer(question)

    try:
        campaigns = lister()
        if inspect.isawaitable(campaigns):
            campaigns = await campaigns
        redacted = redact_by_role(campaigns, role)
    except Exception:
        logger.exception("Liaison Agent: fallback retrieval failed")
        return _cannot_answer(question)

    synthesis = _deterministic_synthesis([{"tool": "list_active_campaigns", "result": redacted}])
    if not synthesis["citations"]:
        return _cannot_answer(question)

    synthesis["answer"] = (
        "Planning was unavailable, so this is a direct listing rather than a "
        f"targeted answer to {question!r}. " + synthesis["answer"]
    )
    synthesis["degraded"] = True
    return synthesis


def _cannot_answer(question: str) -> dict[str, Any]:
    """Return an honest 'no answer' result with no citations.

    Args:
        question: The question that could not be answered.

    Returns:
        Dict with ``answer``, empty ``citations``, ``low`` confidence.
    """
    return {
        "answer": (
            f"I am unable to answer {question!r} at this time: retrieval "
            "returned nothing I am permitted to cite."
        ),
        "citations": [],
        "confidence": "low",
        "degraded": True,
    }


# ── Citation integrity ───────────────────────────────────────────────────────
def _deterministic_synthesis(gathered_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an answer and citations from retrieved rows, with no LLM at all.

    This is what keeps the gateway useful when DeepSeek is unreachable: the
    answer is thinner, but every claim in it is a count of something actually
    retrieved and every citation is a record that actually came back.

    Args:
        gathered_data: List of ``{"tool", "result"}`` dicts, already redacted.

    Returns:
        Dict with ``answer``, ``citations``, ``confidence`` and
        ``synthesis: "deterministic"``.
    """
    citations = _citations_from_data(gathered_data)
    tools_used = [str(entry.get("tool")) for entry in gathered_data if entry.get("tool")]

    if not citations:
        return {
            "answer": (
                "Retrieval completed but returned no records I am permitted to "
                f"cite for this role (tools queried: {', '.join(tools_used) or 'none'})."
            ),
            "citations": [],
            "confidence": "low",
            "synthesis": "deterministic",
        }

    by_type: dict[str, list[str]] = {}
    for citation in citations:
        by_type.setdefault(citation["type"], []).append(citation["id"])
    parts = [f"{len(ids)} {kind}(s): {', '.join(ids[:5])}" for kind, ids in sorted(by_type.items())]

    return {
        "answer": (
            "Language synthesis was unavailable, so this is a direct summary of "
            f"what was retrieved — {'; '.join(parts)}. "
            f"Tools queried: {', '.join(tools_used)}."
        ),
        "citations": citations,
        "confidence": "medium",
        "synthesis": "deterministic",
    }


def _citations_from_data(gathered_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive citations directly from retrieved records.

    Args:
        gathered_data: List of ``{"tool", "result"}`` dicts, already redacted.

    Returns:
        Deduplicated list of ``{"type", "id", "detail"}`` dicts.
    """
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for entry in gathered_data:
        tool = str(entry.get("tool", "unknown"))
        kind = _citation_kind(tool)
        for record_id in _collect_ids(entry.get("result")):
            key = (kind, record_id)
            if key in seen:
                continue
            seen.add(key)
            citations.append({"type": kind, "id": record_id, "detail": f"retrieved via {tool}"})
    return citations


def _citation_kind(tool: str) -> str:
    """Map a tool name onto a citation type.

    Args:
        tool: Tool name that produced the record.

    Returns:
        ``campaign`` | ``case`` | ``artifact`` | ``indicator`` | ``record``.
    """
    if "campaign" in tool:
        return "campaign"
    if "case" in tool:
        return "case"
    if "artifact" in tool:
        return "artifact"
    if "indicator" in tool:
        return "indicator"
    return "record"


def _known_record_ids(gathered_data: list[dict[str, Any]]) -> set[str]:
    """Collect every citable identifier present in the retrieved data.

    Args:
        gathered_data: List of ``{"tool", "result"}`` dicts, already redacted.

    Returns:
        Set of identifier strings the agent is entitled to cite.
    """
    known: set[str] = set()
    for entry in gathered_data:
        known |= set(_collect_ids(entry.get("result")))
    return known


def _collect_ids(node: Any) -> list[str]:
    """Recursively collect identifier-shaped values from a payload.

    Args:
        node: Any nested dict/list/scalar structure.

    Returns:
        List of identifier strings, in encounter order, deduplicated.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, value in item.items():
                if key in _ID_KEYS and isinstance(value, str | int) and not isinstance(value, bool):
                    text = str(value)
                    if text and text != "[REDACTED]" and text not in seen:
                        seen.add(text)
                        found.append(text)
                else:
                    _walk(value)
        elif isinstance(item, list | tuple):
            for element in item:
                _walk(element)

    _walk(node)
    return found


def _verify_citations(
    citations: Any,
    known_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split model-produced citations into verified and unretrieved.

    A citation that does not name a record present in the retrieved data is
    not evidence, it is a hallucination with a footnote. It is removed from
    ``citations`` and surfaced separately.

    Args:
        citations: Whatever the model put in its ``citations`` field.
        known_ids: Identifiers actually present in the retrieved data.

    Returns:
        ``(verified, dropped)``.
    """
    if not isinstance(citations, list):
        return [], []

    verified: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            dropped.append({"raw": citation, "reason": "malformed"})
            continue
        cited_id = str(citation.get("id", ""))
        if cited_id and cited_id in known_ids:
            verified.append(citation)
        else:
            dropped.append({**citation, "reason": "not present in retrieved data"})
    return verified, dropped
