"""Orchestrator node for evaluating trigger types and routing worker agents."""

import inspect
from typing import Any

from src.agents.state import GraphState
from src.db.supabase import fetch_case_context

TRIGGER_WORKER_MAP: dict[str, list[str]] = {
    "TELEMETRY": ["telemetry"],
    "TRANSACTION": ["financial", "telemetry", "research"],
    "CALL": ["phone", "research", "phishing"],
    # PHISHING activates ONLY the phishing worker here; the research worker
    # runs as documented Stage 2 AFTER it (see route_after_phishing in
    # graph.py) so it can verify the URLs/domains the phishing worker
    # extracted from the material — including OCR text from uploaded images.
    "PHISHING": ["phishing"],
}


async def orchestrator_node(state: GraphState) -> dict[str, Any]:
    """Evaluates trigger_type, loads associated_case_context from DB if present,

    and determines workers_to_activate.
    """
    trigger_type = state.get("trigger_type", "")
    workers = list(TRIGGER_WORKER_MAP.get(trigger_type, []))

    payload = state.get("trigger_payload") or {}
    associated_id = state.get("associated_case_id") or payload.get("associated_case_id")

    status_messages = list(state.get("status_messages") or [])

    associated_context = state.get("associated_case_context")
    if associated_id and associated_context is None:
        try:
            res = fetch_case_context(associated_id)
            if inspect.isawaitable(res):
                associated_context = await res
            else:
                associated_context = res
            status_messages.append(
                f"Orchestrator: linked active case {associated_id} context"
            )
        except Exception as e:  # noqa: BLE001
            associated_context = None

            status_messages.append(
                f"Orchestrator: failed to fetch case {associated_id} context: {e}"
            )
    elif associated_id:
        status_messages.append(
            f"Orchestrator: linked active case {associated_id} context"
        )

    status_messages.append(
        f"Orchestrator: routing {trigger_type} trigger to {workers}"
    )

    return {
        "workers_to_activate": workers,
        "associated_case_id": associated_id,
        "associated_case_context": associated_context,
        "status_messages": status_messages,
    }
