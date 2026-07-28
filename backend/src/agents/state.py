"""GraphState definition for TranSafe LangGraph orchestration."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


class WorkerFinding(BaseModel):
    """Structured risk output returned by an individual worker node."""

    worker: str  # "telemetry" | "research" | "financial" | "phone" | "phishing"
    score: int  # 0 - 100 risk sub-score
    confidence: float  # 0.0 - 1.0 LLM confidence
    evidence: list[str] = Field(default_factory=list)  # Bullet-point evidence list
    error: str | None = None  # Set if worker failed


class GraphState(TypedDict, total=False):
    """LangGraph shared state schema across all agent nodes."""

    session_id: str
    user_id: str
    created_at: str
    trigger_type: Literal["TELEMETRY", "TRANSACTION", "CALL", "PHISHING", "REPORT"]
    trigger_payload: dict[str, Any]
    workers_to_activate: list[str]
    telemetry_finding: dict[str, Any] | None
    research_finding: dict[str, Any] | None
    financial_finding: dict[str, Any] | None
    phone_finding: dict[str, Any] | None
    phishing_finding: dict[str, Any] | None
    risk_score: int | None
    risk_tier: Literal["LOW", "MEDIUM", "HIGH"] | None
    xai_report: dict[str, Any] | None
    phone_session: dict[str, Any] | None
    call_mode: Literal["LISTEN", "AUTO_TALK"] | None
    action_taken: str | None
    case_id: str | None
    extracted_entities: dict[str, Any] | None
    status_messages: list[str]
    associated_case_id: str | None
    associated_case_context: dict[str, Any] | None
