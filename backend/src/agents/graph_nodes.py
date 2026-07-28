"""Graph node implementations for Risk Scorer, XAI Report, and Action Dispatcher."""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from groq import Groq

from src.agents.state import GraphState
from src.db.supabase import (
    freeze_transaction,
    insert_admin_alert,
    insert_fraud_case,
)

WORKER_WEIGHTS: dict[str, float] = {
    "telemetry": 0.15,
    "research": 0.25,
    "financial": 0.30,
    "phone": 0.20,
    "phishing": 0.10,
}


def risk_scorer_node(state: GraphState) -> dict[str, Any]:
    """Aggregates findings from active worker nodes using weighted scoring and tier rules."""
    findings: dict[str, Any] = {
        "telemetry": state.get("telemetry_finding"),
        "research": state.get("research_finding"),
        "financial": state.get("financial_finding"),
        "phone": state.get("phone_finding"),
        "phishing": state.get("phishing_finding"),
    }

    active_findings: dict[str, dict[str, Any]] = {
        k: v
        for k, v in findings.items()
        if v is not None and isinstance(v, dict) and not v.get("error")
    }

    status_messages = list(state.get("status_messages") or [])

    if not active_findings:
        score = 0
    else:
        active_weight_sum = sum(WORKER_WEIGHTS[k] for k in active_findings)
        if active_weight_sum <= 0:
            active_weight_sum = 1.0

        weighted_score = sum(
            (
                active_findings[worker]["score"]
                * WORKER_WEIGHTS[worker]
                / active_weight_sum
            )
            for worker in active_findings
        )
        score = round(weighted_score)

    # Score override rules
    research_f = active_findings.get("research")
    financial_f = active_findings.get("financial")
    phone_f = active_findings.get("phone")

    if (
        research_f
        and research_f.get("score", 0) >= 80
        and research_f.get("confidence", 0.0) > 0.90
    ):
        score = max(score, 90)

    if (
        financial_f
        and financial_f.get("score", 0) > 90
        and research_f
        and research_f.get("score", 0) > 80
    ):
        score = max(score, 90)

    if phone_f and phone_f.get("score", 0) >= 90 and phone_f.get("confidence", 0.0) > 0.95:
        score = max(score, 90)

    score = max(0, min(100, score))

    if score < 40:
        tier: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    elif score < 70:
        tier = "MEDIUM"
    else:
        tier = "HIGH"

    status_messages.append(f"Risk Scorer: final score {score}/100 → {tier}")

    return {
        "risk_score": score,
        "risk_tier": tier,
        "status_messages": status_messages,
    }


def xai_node(state: GraphState) -> dict[str, Any]:
    """Generates structured bilingual (EN/MS) explainable AI report via Groq LLM."""
    risk_score = state.get("risk_score", 0)
    risk_tier = state.get("risk_tier", "LOW")
    status_messages = list(state.get("status_messages") or [])

    active_findings: list[dict[str, Any]] = [
        f
        for f in [
            state.get("telemetry_finding"),
            state.get("research_finding"),
            state.get("financial_finding"),
            state.get("phone_finding"),
            state.get("phishing_finding"),
        ]
        if f is not None and isinstance(f, dict)
    ]

    prompt = f"""
You are an AI explainability specialist for a banking fraud prevention system.
Based on the following agent findings, generate a clear, non-technical explanation
of why this activity was flagged as {risk_tier} risk (score: {risk_score}/100).

Worker findings:
{json.dumps(active_findings, indent=2)}

Provide your response in JSON format:
{{
  "verdict_summary": "1-2 sentence plain English explanation",
  "verdict_summary_ms": "1-2 sentence Bahasa Melayu explanation",
  "recommendation": "Specific advice for the user given this situation"
}}

Keep the verdict_summary under 50 words. Use simple language a non-technical user can understand.
"""

    verdict_summary = f"Activity flagged as {risk_tier} risk with score {risk_score}/100."
    verdict_summary_ms = (
        f"Aktiviti ditandakan sebagai risiko {risk_tier} dengan skor {risk_score}/100."
    )
    recommendation = "Please review your transactions and report any unrecognized activity."

    api_key = os.getenv("GROQ_API_KEY")
    if api_key:
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            if response.choices and response.choices[0].message.content:
                content = json.loads(response.choices[0].message.content)
                verdict_summary = content.get("verdict_summary", verdict_summary)
                verdict_summary_ms = content.get(
                    "verdict_summary_ms", verdict_summary_ms
                )
                recommendation = content.get("recommendation", recommendation)
        except Exception as e:  # noqa: BLE001
            status_messages.append(f"XAI Node: LLM generation fallback: {e}")


    xai_report: dict[str, Any] = {
        "session_id": state.get("session_id", ""),
        "trigger_type": state.get("trigger_type", ""),
        "risk_score": risk_score,
        "risk_tier": risk_tier,
        "verdict_summary": verdict_summary,
        "verdict_summary_ms": verdict_summary_ms,
        "workers_activated": [
            str(f.get("worker", "")) for f in active_findings if "worker" in f
        ],
        "worker_findings": active_findings,
        "recommendation": recommendation,
    }

    status_messages.append("XAI Node: structured explanation generated")

    return {
        "xai_report": xai_report,
        "status_messages": status_messages,
    }


async def action_dispatcher_node(state: GraphState) -> dict[str, Any]:
    """Resolves tier action (FREEZE_30_MIN, BIOMETRIC_CHALLENGE, APPROVE) and updates DB records."""
    tier = state.get("risk_tier", "LOW")
    payload = state.get("trigger_payload") or {}
    session_id = state.get("session_id", "")
    user_id = state.get("user_id", "")
    trigger_type = state.get("trigger_type", "")
    risk_score = state.get("risk_score", 0)
    xai_report = dict(state.get("xai_report") or {})
    status_messages = list(state.get("status_messages") or [])

    case_id = f"case-{session_id}" if session_id else "case-unknown"
    action_taken = ""

    if tier == "LOW":
        action_taken = "APPROVE"
        status = "approved"
    elif tier == "MEDIUM":
        action_taken = "BIOMETRIC_CHALLENGE"
        status = "pending_biometric"
    elif tier == "HIGH":
        action_taken = "FREEZE_30_MIN"
        status = "frozen"
        transaction_id = payload.get("transaction_id")
        if transaction_id:
            try:
                await freeze_transaction(
                    transaction_id=transaction_id, freeze_duration_seconds=1800
                )
            except Exception as e:  # noqa: BLE001
                status_messages.append(
                    f"Action Dispatcher: transaction freeze warning: {e}"
                )
        unfreeze_iso = (
            datetime.now(UTC) + timedelta(seconds=1800)
        ).isoformat() + "Z"

        xai_report["unfreeze_at"] = unfreeze_iso
    else:
        action_taken = "APPROVE"
        status = "approved"

    try:
        case_data: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "trigger_type": trigger_type,
            "risk_score": risk_score,
            "risk_tier": tier,
            "status": status,
            "action_taken": action_taken,
            "xai_report": xai_report,
        }
        if payload.get("transaction_id"):
            case_data["transaction_id"] = payload.get("transaction_id")

        inserted_id = await insert_fraud_case(case_data)
        if inserted_id:
            case_id = inserted_id
    except Exception as e:  # noqa: BLE001
        status_messages.append(f"Action Dispatcher: DB insert_fraud_case warning: {e}")

    if tier == "HIGH":
        try:
            await insert_admin_alert({
                "case_id": case_id,
                "alert_type": "HIGH_RISK_FREEZE",
                "details": xai_report,
            })
        except Exception as e:  # noqa: BLE001
            status_messages.append(
                f"Action Dispatcher: DB insert_admin_alert warning: {e}"
            )

    xai_report["case_id"] = case_id
    xai_report["action_taken"] = action_taken
    status_messages.append(
        f"Action Dispatcher: action {action_taken} dispatched for tier {tier}"
    )

    return {
        "action_taken": action_taken,
        "case_id": case_id,
        "xai_report": xai_report,
        "status_messages": status_messages,
    }
