"""Graph node implementations for Risk Scorer, XAI Report, and Action Dispatcher."""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from src.agents.state import GraphState
from src.db.supabase import (
    freeze_transaction,
    insert_admin_alert,
    insert_fraud_case,
    insert_phishing_submission,
    resolve_transaction_uuid,
)

WORKER_WEIGHTS: dict[str, float] = {
    "telemetry": 0.15,
    "research": 0.25,
    "financial": 0.30,
    "phone": 0.20,
    "phishing": 0.10,
}


def _is_uuid(value: str | None) -> bool:
    """Return True if value is a valid UUID string (fraud_cases.session_id is UUID NOT NULL)."""
    if not value:
        return False
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False


def risk_scorer_node(state: GraphState) -> dict[str, Any]:
    """Aggregates findings from active worker nodes using weighted scoring and tier rules."""
    trigger_type = state.get("trigger_type", "")
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

    # Case-coercion match override: when the financial worker confirms the
    # recipient account matches a linked case's context (scam call transcript
    # or phishing material), this is a dominant signal. Coerce the overall
    # score to 98 regardless of other workers so the transaction is frozen
    # instead of being diluted by low telemetry/research scores.
    if financial_f and any(
        "matches active call transcript or phishing case context" in str(ev)
        for ev in financial_f.get("evidence", [])
    ):
        score = max(score, 98)

    if phone_f and phone_f.get("score", 0) >= 90 and phone_f.get("confidence", 0.0) > 0.95:
        score = max(score, 90)

    # PHISHING trigger: the phishing worker's verdict is the dominant signal.
    # A confident high phishing score means the submitted material IS phishing
    # even if the research worker found no blacklist entry yet (or could not
    # verify an image-only URL). Without this, a strong phishing finding is
    # diluted by the low research score and an obvious phishing page can fall
    # to LOW — which is what happened for the PayPal lookalike test image.
    phishing_f = active_findings.get("phishing")
    if (
        trigger_type == "PHISHING"
        and phishing_f
        and phishing_f.get("score", 0) >= 75
        and phishing_f.get("confidence", 0.0) > 0.80
    ):
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

    try:
        from langchain_core.messages import HumanMessage
        from src.agents.llm import extract_json_object, invoke_groq_with_key_rotation

        response = invoke_groq_with_key_rotation([HumanMessage(content=prompt)])
        content = extract_json_object(response.content if hasattr(response, "content") else response)
        if isinstance(content, dict):
            verdict_summary = content.get("verdict_summary", verdict_summary)
            verdict_summary_ms = content.get("verdict_summary_ms", verdict_summary_ms)
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
        "associated_case_id": state.get("associated_case_id"),
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

    # Transaction triggers carry transaction_id nested under payload["transaction"]
    # (frontend sends {transaction: {transaction_id: ...}}), while some legacy
    # flows send it flat — handle both shapes.
    tx_payload = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else payload
    transaction_id = str(tx_payload.get("transaction_id") or "").strip() or None

    case_id = f"case-{session_id}" if session_id else "case-unknown"
    action_taken = ""

    # fraud_cases.session_id is UUID NOT NULL — the frontend sends human-readable
    # session ids ("sess-..."), so normalize to a fresh UUID and preserve the real
    # session id in the XAI report (a non-UUID value would make the insert fail).
    if not _is_uuid(session_id):
        xai_report["source_session_id"] = session_id
        session_id = str(uuid.uuid4())

    if tier == "LOW":
        action_taken = "APPROVE"
        status = "approved"
    elif tier == "MEDIUM":
        action_taken = "BIOMETRIC_CHALLENGE"
        status = "pending_biometric"
    elif tier == "HIGH" and trigger_type != "PHISHING":
        action_taken = "FREEZE_30_MIN"
        status = "frozen"
        if transaction_id:
            try:
                await asyncio.to_thread(
                    freeze_transaction,
                    transaction_id=transaction_id,
                    freeze_duration_seconds=1800,
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

    phishing_submission_data: dict[str, Any] | None = None
    if trigger_type == "PHISHING":
        if tier == "HIGH":
            action_taken = "WARNING"
            status = "reported"
        elif tier == "MEDIUM":
            action_taken = "ADVISORY"
            status = "pending"
        else:
            action_taken = "NO_ACTION"
            status = "pending"

        material = payload.get("material") or payload.get("phishing_material") or {}
        content_type = str(material.get("content_type") or material.get("source_type") or "TEXT").upper()
        raw_content = str(material.get("content") or "")
        extracted_text = str(state.get("phishing_ocr_text") or "").strip()
        image_description = str(state.get("phishing_image_description") or "").strip()

        if content_type == "IMAGE":
            raw_content = extracted_text or image_description or "[image submitted]"

        phishing_submission_data = {
            "case_id": case_id,
            "content_type": content_type,
            "raw_content": raw_content,
            "extracted_text": extracted_text if content_type == "IMAGE" else None,
            "analysis_result": {
                **xai_report,
                "phishing_ocr_text": state.get("phishing_ocr_text"),
                "phishing_image_description": state.get("phishing_image_description"),
            },
        }

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
        if transaction_id:
            # fraud_cases.transaction_id is UUID REFERENCES transactions(id), so
            # the TEXT business id must be resolved to the row's UUID PK before
            # the insert — otherwise the case insert fails with 22P02 and the
            # transaction never gets a case row it can be flagged under.
            tx_uuid = await asyncio.to_thread(
                resolve_transaction_uuid, transaction_id
            )
            if tx_uuid:
                case_data["transaction_id"] = tx_uuid
            else:
                status_messages.append(
                    f"Action Dispatcher: transaction {transaction_id} not found "
                    "in DB — case created without transaction link"
                )

        # insert_fraud_case is a SYNC Supabase call — run it in a thread so the
        # event loop is not blocked, and never await it directly.
        inserted_id = await asyncio.to_thread(insert_fraud_case, case_data)
        if inserted_id:
            case_id = inserted_id
    except Exception as e:  # noqa: BLE001
        status_messages.append(f"Action Dispatcher: DB insert_fraud_case warning: {e}")

    if tier == "HIGH" and trigger_type != "PHISHING":
        try:
            await asyncio.to_thread(
                insert_admin_alert,
                {
                    "case_id": case_id,
                    "alert_type": "HIGH_RISK_FREEZE",
                    "details": xai_report,
                },
            )
        except Exception as e:  # noqa: BLE001
            status_messages.append(
                f"Action Dispatcher: DB insert_admin_alert warning: {e}"
            )

    # Wire the phishing submission row (PHISHING trigger): persist the case
    # evidence trail without storing the uploaded image bytes. If the fraud
    # case insert failed, case_id is still the placeholder "case-..." string
    # (not a UUID) — store NULL so the submission row still records (schema:
    # case_id UUID REFERENCES fraud_cases(id) ON DELETE SET NULL).
    if phishing_submission_data:
        phishing_submission_data["case_id"] = (
            case_id if _is_uuid(case_id) else None
        )
        try:
            await asyncio.to_thread(
                insert_phishing_submission,
                phishing_submission_data,
            )
        except Exception as e:  # noqa: BLE001
            status_messages.append(
                f"Action Dispatcher: DB insert_phishing_submission warning: {e}"
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
