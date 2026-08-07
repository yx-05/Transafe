"""StateGraph compilation module for TranSafe agent pipeline."""


from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.graph_nodes import action_dispatcher_node, risk_scorer_node, xai_node
from src.agents.orchestrator import orchestrator_node
from src.agents.state import GraphState
from src.agents.workers import (
    financial_worker_node,
    phishing_worker_node,
    phone_worker_node,
    research_worker_node,
    telemetry_worker_node,
)


def route_workers(state: GraphState) -> list[str] | str:
    """Conditional edge router function to fan out from orchestrator to active workers."""
    workers = state.get("workers_to_activate", [])
    if not workers:
        return "scorer"
    return workers


def route_after_phishing(state: GraphState) -> str:
    """After the phishing worker, run the research worker for PHISHING triggers.

    Documented design (PRD §4.4): Phishing Analyst Worker is Stage 1, Research
    Worker is Stage 2 — it verifies the extracted URLs/domains against internal
    fraud memory and public blacklists. Running sequentially lets the research
    worker consume the phishing worker's OCR output (``phishing_ocr_text``),
    which is essential for IMAGE submissions where the URL only exists inside
    the screenshot. All other trigger types go straight to the scorer.
    """
    if state.get("trigger_type") == "PHISHING":
        return "research"
    return "scorer"


def compile_graph() -> CompiledStateGraph:
    """Constructs StateGraph(GraphState), wires conditional edges for worker fan-out,

    join edges back to scorer, and linear evaluation path scorer -> xai -> dispatcher -> END.
    """
    builder = StateGraph(GraphState)

    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("telemetry", telemetry_worker_node)
    builder.add_node("research", research_worker_node)
    builder.add_node("financial", financial_worker_node)
    builder.add_node("phone", phone_worker_node)
    builder.add_node("phishing", phishing_worker_node)
    builder.add_node("scorer", risk_scorer_node)
    builder.add_node("xai", xai_node)
    builder.add_node("dispatcher", action_dispatcher_node)

    builder.set_entry_point("orchestrator")

    builder.add_conditional_edges(
        "orchestrator",
        route_workers,
        ["telemetry", "research", "financial", "phone", "phishing", "scorer"],
    )

    builder.add_edge("telemetry", "scorer")
    builder.add_edge("research", "scorer")
    builder.add_edge("financial", "scorer")
    builder.add_edge("phone", "scorer")
    # PHISHING: phishing worker → research worker (Stage 2) → scorer.
    builder.add_conditional_edges(
        "phishing",
        route_after_phishing,
        ["research", "scorer"],
    )

    builder.add_edge("scorer", "xai")
    builder.add_edge("xai", "dispatcher")
    builder.add_edge("dispatcher", END)

    return builder.compile()
