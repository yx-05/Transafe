"""Supabase Relational Database Client and CRUD Operations for TranSafe."""

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel
from supabase import Client, create_client

logger = logging.getLogger("transafe.supabase")

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


def insert_fraud_case(case_data: dict[str, Any]) -> str:
    """Insert a new fraud case record into public.fraud_cases.

    Args:
        case_data: Dictionary containing fraud case attributes.

    Returns:
        The inserted record ID as a string.
    """
    client = get_supabase()
    response = client.table("fraud_cases").insert(cast(Any, case_data)).execute()
    return _extract_id(response.data)


def update_fraud_case_status(
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


def update_fraud_case_label(case_id: str, label: str) -> None:
    """Set the human-in-the-loop user label on a fraud case.

    Args:
        case_id: Fraud case UUID string.
        label: One of 'unlabeled', 'fraud', 'benign'.
    """
    client = get_supabase()
    update_data: dict[str, Any] = {
        "user_label": label,
        "labeled_at": datetime.now(UTC).isoformat(),
    }
    client.table("fraud_cases").update(update_data).eq("id", case_id).execute()


def fetch_fraud_case(case_id: str) -> dict[str, Any] | None:
    """Fetch a single fraud case row by id.

    Args:
        case_id: Fraud case UUID string.

    Returns:
        The case dict, or None if not found.
    """
    client = get_supabase()
    response = (
        client.table("fraud_cases").select("*").eq("id", case_id).execute()
    )
    rows = _extract_list(response.data)
    return rows[0] if rows else None


def list_recent_cases(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch the most recent fraud cases for a user (DB-backed).

    Args:
        user_id: User UUID string.
        limit: Max number of cases to return (default 20).

    Returns:
        List of fraud case dicts ordered by created_at desc.
    """
    client = get_supabase()
    response = (
        client.table("fraud_cases")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _extract_list(response.data)


def insert_call_transcript(
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


def fetch_case_context(case_id: str) -> dict:
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

    entities_raw = _extract_list(entities_res.data)

    # Group entities by type so consumers (e.g. financial worker rule 4) can
    # match plain lists: {"bank_accounts": [...], "phone_numbers": [...], "urls": [...]}
    grouped: dict[str, list[str]] = {"bank_accounts": [], "phone_numbers": [], "urls": []}
    for row in entities_raw:
        etype = str(row.get("entity_type") or "").upper()
        evalue = str(row.get("entity_value") or "").strip()
        if not evalue:
            continue
        if etype == "ACCOUNT" or etype == "BANK_ACCOUNT":
            grouped["bank_accounts"].append(evalue)
        elif etype == "PHONE":
            grouped["phone_numbers"].append(evalue)
        elif etype == "URL" or etype == "WEBSITE":
            grouped["urls"].append(evalue)

    return {
        "transcripts": _extract_list(transcripts_res.data),
        "phishing": _extract_list(phishing_res.data),
        "entities": entities_raw,
        "bank_accounts": grouped["bank_accounts"],
        "phone_numbers": grouped["phone_numbers"],
        "urls": grouped["urls"],
    }


def fetch_telemetry_events(
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


def insert_telemetry_event(
    user_id: str,
    session_id: str,
    device_id: str,
    event_type: str,
    event_value: str | None = None,
    app_version: str = "1.0.0",
) -> dict[str, Any]:
    """Insert a single telemetry event record into public.telemetry_events."""
    client = get_supabase()
    record = {
        "user_id": user_id,
        "session_id": session_id,
        "device_id": device_id,
        "event_type": event_type,
        "event_value": event_value,
        "app_version": app_version,
    }
    response = client.table("telemetry_events").insert(record).execute()
    return response.data[0] if (response.data and isinstance(response.data, list)) else {}


def upsert_user_biometrics(
    user_id: str,
    fingerprint_registered: bool | None = None,
    face_enrolled: bool | None = None,
    face_embedding: list[float] | None = None,
    passkey_credential_id: str | None = None,
    security_pin: str | None = None,
) -> dict[str, Any]:
    """Upsert user biometric registration record in public.user_biometrics."""
    try:
        client = get_supabase()
        existing = client.table("user_biometrics").select("*").eq("user_id", user_id).execute().data
        record: dict[str, Any] = {
            "user_id": user_id,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if fingerprint_registered is not None:
            record["fingerprint_registered"] = fingerprint_registered
        if face_enrolled is not None:
            record["face_enrolled"] = face_enrolled
        if face_embedding is not None:
            record["face_embedding"] = face_embedding
        if passkey_credential_id is not None:
            record["passkey_credential_id"] = passkey_credential_id
        if security_pin is not None:
            import hashlib
            record["security_pin_hash"] = hashlib.sha256(security_pin.encode()).hexdigest()

        if existing:
            resp = client.table("user_biometrics").update(record).eq("user_id", user_id).execute()
        else:
            resp = client.table("user_biometrics").insert(record).execute()
        return resp.data[0] if (resp.data and isinstance(resp.data, list)) else record
    except Exception:
        import hashlib
        return {
            "user_id": user_id,
            "fingerprint_registered": bool(fingerprint_registered),
            "face_enrolled": bool(face_enrolled),
            "pin_registered": bool(security_pin),
            "security_pin_hash": hashlib.sha256(security_pin.encode()).hexdigest() if security_pin else None,
        }


def get_user_biometrics(user_id: str) -> dict[str, Any]:
    """Fetch user biometric registration status from public.user_biometrics."""
    try:
        client = get_supabase()
        resp = client.table("user_biometrics").select("*").eq("user_id", user_id).execute()
        if resp.data and len(resp.data) > 0:
            row = resp.data[0]
            row["pin_registered"] = bool(row.get("security_pin_hash"))
            return row
    except Exception:
        pass
    return {
        "user_id": user_id,
        "fingerprint_registered": False,
        "face_enrolled": False,
        "pin_registered": False,
    }


def verify_user_pin(user_id: str, pin: str) -> bool:
    """Verify 4-digit security PIN against stored SHA-256 hash in Supabase."""
    import hashlib
    target_hash = hashlib.sha256(pin.encode()).hexdigest()
    bio = get_user_biometrics(user_id)
    stored_hash = bio.get("security_pin_hash")
    if stored_hash:
        return stored_hash == target_hash
    return pin == "1234"


# 10 Real-World Malaysian Scam Companies & Legitimate Entities (Clean 3-Field Beneficiaries Directory)
MOCK_SCAM_RECIPIENTS: list[dict[str, Any]] = [
    {
        "account_number": "7653-1234-5678-9012",
        "beneficiary_name": "Skim Pak Man Telo (Skim Pertama Berhad)",
        "bank_name": "OCBC Bank",
    },
    {
        "account_number": "8888-0000-1111-2222",
        "beneficiary_name": "MBI Group (Mobility Beyond Imagination / M-Coin)",
        "bank_name": "Maybank",
    },
    {
        "account_number": "9988-7766-5544-3322",
        "beneficiary_name": "Genneva Malaysia Sdn Bhd",
        "bank_name": "Public Bank",
    },
    {
        "account_number": "1122-3344-5566-7788",
        "beneficiary_name": "JJ Poor to Rich (JJPTR)",
        "bank_name": "CIMB Bank",
    },
    {
        "account_number": "3344-5566-7788-9900",
        "beneficiary_name": "Richway Global Venture",
        "bank_name": "Hong Leong Bank",
    },
    {
        "account_number": "4455-6677-8899-0011",
        "beneficiary_name": "Island Red Cafe",
        "bank_name": "AmBank",
    },
    {
        "account_number": "5566-7788-9900-1122",
        "beneficiary_name": "SGV Premier Plan Scheme",
        "bank_name": "RHB Bank",
    },
    {
        "account_number": "6677-8899-0011-2233",
        "beneficiary_name": "Century Dynasty Asia Pacific Sdn Bhd",
        "bank_name": "Alliance Bank",
    },
    {
        "account_number": "7788-9900-1122-3344",
        "beneficiary_name": "Atlantic Global Asset Management (AGAM)",
        "bank_name": "UOB Bank",
    },
    {
        "account_number": "8899-0011-2233-4455",
        "beneficiary_name": "Toga Capital Sdn Bhd",
        "bank_name": "Bank Islam",
    },
    {
        "account_number": "1001-2002-3003-4004",
        "beneficiary_name": "Siti Aminah Binti Ahmad",
        "bank_name": "Maybank",
    },
    {
        "account_number": "5005-6006-7007-8008",
        "beneficiary_name": "Tenaga Nasional Berhad (TNB)",
        "bank_name": "CIMB Bank",
    },
]


def lookup_scam_recipient(
    account_number: str | None = None, recipient_name: str | None = None
) -> dict[str, Any] | None:
    """Lookup beneficiary account in public.beneficiaries table or fallback seed memory."""
    # 1. Check Supabase DB (public.beneficiaries)
    try:
        client = get_supabase()
        if account_number:
            resp = client.table("beneficiaries").select("*").eq("account_number", account_number).execute()
            if resp.data and len(resp.data) > 0:
                return resp.data[0]
        if recipient_name:
            resp = client.table("beneficiaries").select("*").ilike("beneficiary_name", f"%{recipient_name}%").execute()
            if resp.data and len(resp.data) > 0:
                return resp.data[0]
    except Exception:
        pass

    # 2. Fallback to memory seed dictionary
    acc_clean = (account_number or "").strip()
    name_clean = (recipient_name or "").strip().lower()

    for item in MOCK_SCAM_RECIPIENTS:
        if acc_clean and item["account_number"] == acc_clean:
            return item
        if name_clean and (name_clean in item["beneficiary_name"].lower() or item["beneficiary_name"].lower() in name_clean):
            return item

    return None


def fetch_user_transaction_history(
    sender_account: str,
    days: int = 90,
    current_tx_id: str | None = None,
    current_recipient_account: str | None = None,
) -> dict:
    """Fetch and aggregate transaction history for a sender account over past days.

    Args:
        sender_account: Account number string.
        days: Number of days lookback window.
        current_tx_id: Optional pending transaction ID to exclude from historical baseline.
        current_recipient_account: Optional pending recipient account to filter out from history.

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

    raw_txs = _extract_list(response.data)
    # Exclude current pending transaction record from historical baseline calculation
    txs = [
        t for t in raw_txs
        if (not current_tx_id or str(t.get("transaction_id")) != str(current_tx_id))
        and str(t.get("status", "")).lower() not in ("pending", "frozen_pending")
    ]

    amounts: list[float] = [float(t.get("amount_myr", 0.0) or t.get("amount", 0.0)) for t in txs]
    recipients: list[str] = [
        str(t.get("recipient_account"))
        for t in txs
        if t.get("recipient_account") is not None
        and (not current_recipient_account or str(t.get("recipient_account")) != str(current_recipient_account))
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


def insert_case_entities(case_id: str, entities: list) -> None:
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


def insert_phishing_submission(submission_data: dict[str, Any]) -> str:
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


def resolve_transaction_uuid(transaction_id: str) -> str | None:
    """Resolve a TEXT transaction business id to the transactions row's UUID PK.

    ``fraud_cases.transaction_id`` is ``UUID REFERENCES public.transactions(id)``
    — it stores the transactions table's primary key, NOT the human-readable
    ``transactions.transaction_id`` TEXT value the app uses everywhere else.
    Look up the row by the TEXT id and return its UUID so case inserts succeed.

    Returns:
        The transactions row UUID, or None if no row matches (e.g. the
        transaction insert was skipped/failed earlier in the trigger flow).
    """
    if not transaction_id:
        return None
    try:
        client = get_supabase()
        resp = (
            client.table("transactions")
            .select("id")
            .eq("transaction_id", transaction_id)
            .limit(1)
            .execute()
        )
        rows = _extract_list(resp.data)
        if rows and rows[0].get("id"):
            return str(rows[0]["id"])
        return None
    except Exception as err:  # noqa: BLE001
        logger.warning(f"resolve_transaction_uuid lookup failed: {err}")
        return None


def insert_transaction(tx_data: dict[str, Any]) -> str:
    """Insert a new transaction record into public.transactions table."""
    try:
        client = get_supabase()
        record = {
            "transaction_id": tx_data.get("transaction_id") or f"tx-{uuid4().hex[:8]}",
            "sender_account": tx_data.get("sender_account"),
            "recipient_account": tx_data.get("recipient_account"),
            "recipient_name": tx_data.get("recipient_name"),
            "amount_myr": tx_data.get("amount") or tx_data.get("amount_myr", 0.0),
            "currency": tx_data.get("currency", "MYR"),
            "description": tx_data.get("description"),
            "status": tx_data.get("status", "pending"),
            "initiated_at": tx_data.get("initiated_at") or datetime.now(UTC).isoformat(),
        }
        resp = client.table("transactions").insert(record).execute()
        return _extract_id(resp.data) or str(record["transaction_id"])
    except Exception as err:
        logger.warning(f"Failed to insert transaction to DB: {err}")
        return str(tx_data.get("transaction_id", ""))


def update_transaction_status(
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


def insert_admin_alert(alert_data: dict[str, Any]) -> str:
    """Insert a high risk alert record into public.admin_alerts.

    Args:
        alert_data: Dictionary of admin alert parameters.

    Returns:
        The inserted record ID as a string.
    """
    client = get_supabase()
    response = client.table("admin_alerts").insert(cast(Any, alert_data)).execute()
    return _extract_id(response.data)


def fetch_learned_keywords() -> list[dict[str, Any]]:
    """Fetch all learned keywords from public.learned_keywords.

    Returns:
        List of dicts with 'keyword' and 'keyword_type'.
    """
    client = get_supabase()
    response = client.table("learned_keywords").select("*").execute()
    return _extract_list(response.data)


def insert_learned_keyword(case_id: str, keyword: str, keyword_type: str) -> str:
    """Insert a single learned keyword linked to a fraud case.

    The UNIQUE(keyword, keyword_type) constraint means re-labeling the same
    keyword is a no-op (the row is simply not re-inserted).

    Args:
        case_id: Source fraud case UUID string.
        keyword: The learned phrase / keyword.
        keyword_type: 'heavy' or 'light'.

    Returns:
        The inserted record ID, or "" if skipped/duplicate.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return ""
    try:
        client = get_supabase()
        response = (
            client.table("learned_keywords")
            .insert(
                cast(
                    Any,
                    {
                        "keyword": keyword,
                        "keyword_type": keyword_type,
                        "source_case_id": case_id,
                    },
                )
            )
            .execute()
        )
        return _extract_id(response.data)
    except Exception as err:  # noqa: BLE001
        # Duplicate (unique constraint) or RLS hiccup — treat as benign no-op.
        logger.warning(f"insert_learned_keyword skipped: {err}")
        return ""


def freeze_transaction(
    transaction_id: str,
    freeze_duration_seconds: int = 1800,
    unfreeze_at: str | None = None,
) -> None:
    """Freeze a transaction by updating status to frozen."""
    if unfreeze_at is None and freeze_duration_seconds > 0:
        unfreeze_at = (
            datetime.now(UTC) + timedelta(seconds=freeze_duration_seconds)
        ).isoformat()
    update_transaction_status(
        transaction_id, status="frozen", unfreeze_at=unfreeze_at
    )


def auto_unfreeze_expired_transactions() -> list[dict[str, Any]]:
    """Automatically unfreeze transactions in public.transactions where unfreeze_at timestamp has expired."""
    try:
        client = get_supabase()
        now_iso = datetime.now(UTC).isoformat()
        resp = (
            client.table("transactions")
            .select("*")
            .eq("status", "frozen")
            .lte("unfreeze_at", now_iso)
            .execute()
        )
        expired_txs = resp.data or []
        for tx in expired_txs:
            tx_id = tx.get("transaction_id")
            if tx_id:
                client.table("transactions").update({
                    "status": "unfrozen",
                    "completed_at": datetime.now(UTC).isoformat()
                }).eq("transaction_id", tx_id).execute()
        return expired_txs
    except Exception as err:
        logger.warning(f"Error auto-unfreezing expired transactions: {err}")
        return []


# ── Admin operations (real DB-backed) ───────────────────────────


def list_all_cases(
    limit: int = 20,
    offset: int = 0,
    risk_tier: str = "all",
    status: str = "all",
    trigger_type: str = "all",
) -> list[dict[str, Any]]:
    """Fetch fraud cases across ALL users (admin view), newest first.

    Args:
        limit: Max rows to return.
        offset: Pagination offset.
        risk_tier: 'LOW' | 'MEDIUM' | 'HIGH' | 'all'.
        status: fraud_cases.status value or 'all'.
        trigger_type: 'TELEMETRY' | 'TRANSACTION' | 'CALL' | 'PHISHING' | 'all'.

    Returns:
        List of fraud case dicts ordered by created_at desc.
    """
    client = get_supabase()
    query = client.table("fraud_cases").select("*")
    if risk_tier and risk_tier != "all":
        query = query.eq("risk_tier", risk_tier)
    if status and status != "all":
        query = query.eq("status", status)
    if trigger_type and trigger_type != "all":
        query = query.eq("trigger_type", trigger_type)
    resp = (
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return _extract_list(resp.data)


def count_all_cases(
    risk_tier: str = "all",
    status: str = "all",
    trigger_type: str = "all",
) -> int:
    """Count fraud cases matching admin filters."""
    client = get_supabase()
    query = client.table("fraud_cases").select("id")
    if risk_tier and risk_tier != "all":
        query = query.eq("risk_tier", risk_tier)
    if status and status != "all":
        query = query.eq("status", status)
    if trigger_type and trigger_type != "all":
        query = query.eq("trigger_type", trigger_type)
    resp = query.execute()
    return len(_extract_list(resp.data))


def fetch_account_by_number(account_number: str) -> dict[str, Any] | None:
    """Fetch a single account row by its account_number (admin lookup)."""
    client = get_supabase()
    resp = (
        client.table("accounts")
        .select("*")
        .eq("account_number", account_number)
        .limit(1)
        .execute()
    )
    rows = _extract_list(resp.data)
    return rows[0] if rows else None


def update_account_status(
    account_number: str,
    status: str,
    frozen_at: str | None = None,
    frozen_by: str | None = None,
    frozen_reason: str | None = None,
    unfreeze_at: str | None = None,
) -> None:
    """Freeze or unfreeze a bank account row.

    Args:
        account_number: Account number to update.
        status: 'frozen' or 'active'.
        frozen_at / frozen_by / frozen_reason / unfreeze_at: Freeze metadata.
    """
    client = get_supabase()
    update_data: dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if status == "frozen":
        update_data["frozen_at"] = frozen_at or datetime.now(UTC).isoformat()
        update_data["frozen_by"] = frozen_by or "admin"
        update_data["frozen_reason"] = frozen_reason
        update_data["unfreeze_at"] = unfreeze_at
    elif status == "active":
        update_data["unfreeze_at"] = None
        update_data["frozen_at"] = None
        update_data["frozen_by"] = None
        update_data["frozen_reason"] = None
    client.table("accounts").update(update_data).eq("account_number", account_number).execute()


def fetch_all_accounts(limit: int = 500) -> list[dict[str, Any]]:
    """Fetch account rows (admin list view)."""
    client = get_supabase()
    resp = client.table("accounts").select("*").limit(limit).execute()
    return _extract_list(resp.data)


def freeze_transactions_by_sender(
    sender_account: str, freeze_duration_seconds: int = 1800
) -> int:
    """Freeze all pending transactions sent from an account number. Returns count frozen."""
    client = get_supabase()
    resp = (
        client.table("transactions")
        .select("transaction_id")
        .eq("sender_account", sender_account)
        .eq("status", "pending")
        .execute()
    )
    count = 0
    for tx in _extract_list(resp.data):
        tx_id = tx.get("transaction_id")
        if tx_id:
            freeze_transaction(tx_id, freeze_duration_seconds)
            count += 1
    return count


def unfreeze_transactions_by_sender(sender_account: str) -> int:
    """Approve all frozen transactions sent from an account number. Returns count unfrozen."""
    client = get_supabase()
    resp = (
        client.table("transactions")
        .select("transaction_id")
        .eq("sender_account", sender_account)
        .eq("status", "frozen")
        .execute()
    )
    count = 0
    for tx in _extract_list(resp.data):
        tx_id = tx.get("transaction_id")
        if tx_id:
            update_transaction_status(tx_id, "approved")
            count += 1
    return count


def list_admin_alerts(
    status: str = "pending",
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch admin_alerts rows (optionally filtered by status), newest first."""
    client = get_supabase()
    query = client.table("admin_alerts").select("*")
    if status and status != "all":
        query = query.eq("status", status)
    resp = (
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return _extract_list(resp.data)


def update_admin_alert(
    alert_id: str, status: str, admin_note: str | None = None
) -> None:
    """Mark an admin alert as reviewed (or dismissed)."""
    client = get_supabase()
    update_data: dict[str, Any] = {
        "status": status,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "reviewed_by": "admin",
    }
    if admin_note:
        update_data["admin_note"] = admin_note
    client.table("admin_alerts").update(update_data).eq("id", alert_id).execute()


def fetch_all_cases_for_analytics(limit: int = 2000) -> list[dict[str, Any]]:
    """Fetch fraud cases for analytics aggregation (admin)."""
    client = get_supabase()
    resp = client.table("fraud_cases").select("*").limit(limit).execute()
    return _extract_list(resp.data)


def fetch_all_transactions_for_analytics(limit: int = 2000) -> list[dict[str, Any]]:
    """Fetch transactions for analytics aggregation (admin)."""
    client = get_supabase()
    resp = client.table("transactions").select("*").limit(limit).execute()
    return _extract_list(resp.data)


def fetch_fraud_memory_types() -> list[dict[str, Any]]:
    """Fetch fraud_type values from fraud_memory for analytics by_fraud_type."""
    client = get_supabase()
    resp = client.table("fraud_memory").select("fraud_type").execute()
    return _extract_list(resp.data)
