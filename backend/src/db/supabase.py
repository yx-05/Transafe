"""Supabase Relational Database Client and CRUD Operations for TranSafe."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel
from supabase import Client, create_client

supabase_client: Client | None = None


class FraudCaseRecord(BaseModel):
    """Pydantic model representing a fraud case record."""

    id: str | None = None
    session_id: str
    user_id: str
    trigger_type: str
    risk_score: int
    risk_tier: str
    status: str
    action_taken: str
    xai_report: dict[str, Any]
    transaction_id: str | None = None


def init_supabase() -> None:
    """Initialize the global Supabase client using environment variables."""
    global supabase_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if url and key:
        supabase_client = create_client(url, key)


def get_supabase() -> Client:
    """Get the initialized Supabase client.

    Raises:
        RuntimeError: If Supabase client has not been initialized.
    """
    if supabase_client is None:
        init_supabase()
    if supabase_client is None:
        raise RuntimeError("Supabase client is not initialized.")
    return supabase_client


def _extract_id(data: Any) -> str:
    """Extract ID string safely from Supabase response data."""
    if isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            val = first.get("id")
            if val is not None:
                return str(val)
    return ""


def _extract_list(data: Any) -> list[dict[str, Any]]:
    """Extract list of dicts safely from Supabase response data."""
    if isinstance(data, list):
        result: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                result.append(dict(item))
        return result
    return []


async def insert_fraud_case(case_data: dict[str, Any]) -> str:
    """Insert a new fraud case record into public.fraud_cases.

    Args:
        case_data: Dictionary containing fraud case attributes.

    Returns:
        The inserted record ID as a string.
    """
    client = get_supabase()
    response = client.table("fraud_cases").insert(cast(Any, case_data)).execute()
    return _extract_id(response.data)


async def update_fraud_case_status(
    case_id: str, status: str, action_taken: str
) -> None:
    """Update the status and action_taken of an existing fraud case.

    Args:
        case_id: The UUID string of the fraud case.
        status: Updated status value.
        action_taken: Action taken string.
    """
    client = get_supabase()
    update_data = {
        "status": status,
        "action_taken": action_taken,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    client.table("fraud_cases").update(update_data).eq("id", case_id).execute()


async def insert_call_transcript(
    case_id: str, speaker: str, utterance: str, risk_score: int
) -> str:
    """Insert a call transcript record associated with a fraud case.

    Args:
        case_id: Fraud case UUID string.
        speaker: Speaker role ('CALLER', 'AI', 'USER').
        utterance: Transcribed text.
        risk_score: Risk score for the utterance.

    Returns:
        The inserted record ID as a string.
    """
    client = get_supabase()
    row = {
        "case_id": case_id,
        "speaker": speaker,
        "utterance": utterance,
        "risk_score": risk_score,
    }
    response = client.table("call_transcripts").insert(cast(Any, row)).execute()
    return _extract_id(response.data)


async def fetch_case_context(case_id: str) -> dict:
    """Fetch transcripts, phishing submissions, and extracted entities for a case.

    Args:
        case_id: Fraud case UUID string.

    Returns:
        Dict aggregating transcripts, phishing submissions, and entities.
    """
    client = get_supabase()
    transcripts_res = (
        client.table("call_transcripts")
        .select("*")
        .eq("case_id", case_id)
        .execute()
    )
    phishing_res = (
        client.table("phishing_submissions")
        .select("*")
        .eq("case_id", case_id)
        .execute()
    )
    entities_res = (
        client.table("case_entities")
        .select("*")
        .eq("case_id", case_id)
        .execute()
    )

    return {
        "transcripts": _extract_list(transcripts_res.data),
        "phishing": _extract_list(phishing_res.data),
        "entities": _extract_list(entities_res.data),
    }


async def fetch_telemetry_events(
    user_id: str, session_id: str, limit: int = 100
) -> list[dict]:
    """Fetch recent telemetry events for a given user and session.

    Args:
        user_id: User UUID.
        session_id: Session UUID.
        limit: Max number of events to return.

    Returns:
        List of telemetry event dictionaries.
    """
    client = get_supabase()
    response = (
        client.table("telemetry_events")
        .select("*")
        .eq("user_id", user_id)
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _extract_list(response.data)


async def fetch_user_transaction_history(
    sender_account: str, days: int = 90
) -> dict:
    """Fetch and aggregate transaction history for a sender account over past days.

    Args:
        sender_account: Account number string.
        days: Number of days lookback window.

    Returns:
        Dict with total_count, total_amount_myr, avg_amount, max_amount,
        known_recipients, and raw transactions list.
    """
    client = get_supabase()
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    response = (
        client.table("transactions")
        .select("*")
        .eq("sender_account", sender_account)
        .gte("initiated_at", cutoff)
        .execute()
    )

    txs = _extract_list(response.data)
    amounts: list[float] = [float(t.get("amount_myr", 0.0)) for t in txs]
    recipients: list[str] = [
        str(t.get("recipient_account"))
        for t in txs
        if t.get("recipient_account") is not None
    ]
    known_recipients = list(set(recipients))

    total_count = len(txs)
    total_amount = sum(amounts)
    avg_amount = total_amount / total_count if total_count > 0 else 0.0
    max_amount = max(amounts) if total_count > 0 else 0.0

    return {
        "total_count": total_count,
        "total_amount_myr": total_amount,
        "avg_amount": avg_amount,
        "max_amount": max_amount,
        "known_recipients": known_recipients,
        "transactions": txs,
    }


async def insert_case_entities(case_id: str, entities: list) -> None:
    """Insert entity records linked to a fraud case into public.case_entities.

    Args:
        case_id: Parent fraud case UUID string.
        entities: List of dicts with keys 'entity_type' and 'entity_value'.
    """
    if not entities:
        return
    client = get_supabase()
    rows = []
    for item in entities:
        if isinstance(item, dict):
            rows.append(
                {
                    "case_id": case_id,
                    "entity_type": str(item.get("entity_type", "OTHER")),
                    "entity_value": str(item.get("entity_value", "")),
                }
            )
    if rows:
        client.table("case_entities").insert(cast(Any, rows)).execute()


async def insert_phishing_submission(submission_data: dict[str, Any]) -> str:
    """Insert a new phishing submission record into public.phishing_submissions.

    Args:
        submission_data: Dictionary containing phishing submission fields.

    Returns:
        The inserted record ID as a string.
    """
    client = get_supabase()
    response = (
        client.table("phishing_submissions")
        .insert(cast(Any, submission_data))
        .execute()
    )
    return _extract_id(response.data)


async def update_transaction_status(
    transaction_id: str, status: str, unfreeze_at: str | None = None
) -> None:
    """Update transaction status and optional unfreeze_at / frozen_at timestamps.

    Args:
        transaction_id: App transaction_id or UUID string.
        status: New transaction status.
        unfreeze_at: Optional ISO timestamp when auto-unfreeze occurs.
    """
    client = get_supabase()
    update_payload: dict[str, Any] = {"status": status}
    if status == "frozen":
        update_payload["frozen_at"] = datetime.now(UTC).isoformat()
    if unfreeze_at is not None:
        update_payload["unfreeze_at"] = unfreeze_at

    client.table("transactions").update(update_payload).eq(
        "transaction_id", transaction_id
    ).execute()


async def insert_admin_alert(alert_data: dict[str, Any]) -> str:
    """Insert a high risk alert record into public.admin_alerts.

    Args:
        alert_data: Dictionary of admin alert parameters.

    Returns:
        The inserted record ID as a string.
    """
    client = get_supabase()
    response = client.table("admin_alerts").insert(cast(Any, alert_data)).execute()
    return _extract_id(response.data)


async def freeze_transaction(
    transaction_id: str,
    freeze_duration_seconds: int = 1800,
    unfreeze_at: str | None = None,
) -> None:
    """Freeze a transaction by updating status to frozen."""
    if unfreeze_at is None and freeze_duration_seconds > 0:
        unfreeze_at = (
            datetime.now(UTC) + timedelta(seconds=freeze_duration_seconds)
        ).isoformat()
    await update_transaction_status(
        transaction_id, status="frozen", unfreeze_at=unfreeze_at
    )


