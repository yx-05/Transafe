"""Admin REST Endpoints for TranSafe Fraud Operations Dashboard.

All endpoints are DB-backed (Supabase) — no mock data. Admin actions
(freeze/unfreeze accounts, review alerts) persist to real tables.
"""

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.dependencies import verify_admin_key
from src.db.supabase import (
    count_all_cases,
    fetch_account_by_number,
    fetch_all_accounts,
    fetch_all_cases_for_analytics,
    fetch_all_transactions_for_analytics,
    fetch_fraud_case,
    fetch_fraud_memory_types,
    freeze_transactions_by_sender,
    list_admin_alerts,
    list_all_cases,
    unfreeze_transactions_by_sender,
    update_account_status,
    update_admin_alert,
    update_fraud_case_status,
)
from src.models.schemas import (
    AccountActionData,
    AccountFreezeRequest,
    AccountUnfreezeRequest,
    AdminAlertItem,
    AdminAlertListResponseData,
    AdminAlertUpdateData,
    AdminAlertUpdateRequest,
    AdminCaseItem,
    AdminCaseListResponseData,
    AnalyticsSummaryData,
    AnalyticsTrendData,
    AnalyticsTrendPoint,
    CaseActionData,
    ResponseEnvelope,
)

router = APIRouter(
    prefix="/admin/v1",
    tags=["admin"],
    dependencies=[Depends(verify_admin_key)],
)


def make_envelope(data: Any) -> ResponseEnvelope[Any]:
    """Helper to wrap response in standard envelope."""
    return ResponseEnvelope(
        success=True,
        data=data,
        error=None,
        timestamp=datetime.now(UTC).isoformat(),
    )


def _verdict_from_case(case: dict[str, Any]) -> str:
    """Extract a human-readable verdict summary from a fraud case row."""
    xr = case.get("xai_report")
    if isinstance(xr, dict):
        verdict = xr.get("verdict_summary")
        if verdict:
            return str(verdict)
    return ""


def _build_admin_case_item(case: dict[str, Any]) -> AdminCaseItem:
    """Map a fraud_cases DB row to the admin list item."""
    return AdminCaseItem(
        case_id=str(case.get("id") or case.get("case_id") or ""),
        user_id=str(case.get("user_id") or ""),
        trigger_type=str(case.get("trigger_type") or ""),
        risk_score=int(case.get("risk_score") or 0),
        risk_tier=str(case.get("risk_tier") or "LOW"),
        status=str(case.get("status") or "pending"),
        action_taken=str(case.get("action_taken") or ""),
        created_at=str(case.get("created_at") or ""),
        verdict_summary=_verdict_from_case(case) or None,
    )


@router.get(
    "/cases",
    response_model=ResponseEnvelope[AdminCaseListResponseData],
    status_code=status.HTTP_200_OK,
)
async def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    risk_tier: str | None = Query("all"),
    status_filter: str | None = Query("all", alias="status"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    trigger_type: str | None = Query("all"),
) -> ResponseEnvelope[AdminCaseListResponseData]:
    """List real fraud cases from the DB with filtering and pagination."""
    offset = (page - 1) * page_size
    cases = await asyncio.to_thread(
        list_all_cases,
        page_size,
        offset,
        risk_tier or "all",
        status_filter or "all",
        trigger_type or "all",
    )

    # Post-query date filtering (created_at) applied in Python since
    # PostgREST range filtering on ISO strings is unreliable for partial dates.
    if date_from or date_to:
        filtered: list[dict[str, Any]] = []
        for case in cases:
            created = str(case.get("created_at") or "")[:10]
            if date_from and created < date_from[:10]:
                continue
            if date_to and created > date_to[:10]:
                continue
            filtered.append(case)
        cases = filtered

    total = await asyncio.to_thread(
        count_all_cases,
        risk_tier or "all",
        status_filter or "all",
        trigger_type or "all",
    )
    return make_envelope(
        AdminCaseListResponseData(
            items=[_build_admin_case_item(c) for c in cases],
            total=total,
            page=page,
            page_size=page_size,
            has_next=(page * page_size) < total,
        )
    )


@router.get(
    "/cases/{case_id}",
    response_model=ResponseEnvelope[dict[str, Any]],
    status_code=status.HTTP_200_OK,
)
async def get_case_detail(
    case_id: str,
) -> ResponseEnvelope[dict[str, Any]]:
    """Retrieve full real detail for a single fraud case (incl. XAI report)."""
    case = await asyncio.to_thread(fetch_fraud_case, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case {case_id} not found."},
        )
    return make_envelope(case)


@router.post(
    "/cases/{case_id}/freeze",
    response_model=ResponseEnvelope[CaseActionData],
    status_code=status.HTTP_200_OK,
)
async def freeze_case(
    case_id: str,
    payload: AccountFreezeRequest,
) -> ResponseEnvelope[CaseActionData]:
    """Freeze a fraud case: update its status/action in the DB."""
    case = await asyncio.to_thread(fetch_fraud_case, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case {case_id} not found."},
        )
    await asyncio.to_thread(update_fraud_case_status, case_id, "frozen", "FREEZE_30_MIN")
    unfreeze_at = (datetime.now(UTC) + timedelta(minutes=30)).isoformat() + "Z"
    return make_envelope(
        CaseActionData(
            case_id=case_id,
            status="frozen",
            action_taken="FREEZE_30_MIN",
            unfreeze_at=unfreeze_at,
            reason=payload.reason,
        )
    )


@router.post(
    "/cases/{case_id}/unfreeze",
    response_model=ResponseEnvelope[CaseActionData],
    status_code=status.HTTP_200_OK,
)
async def unfreeze_case(
    case_id: str,
    payload: AccountUnfreezeRequest,
) -> ResponseEnvelope[CaseActionData]:
    """Unfreeze a fraud case: update its status/action in the DB."""
    case = await asyncio.to_thread(fetch_fraud_case, case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CASE_NOT_FOUND", "message": f"Case {case_id} not found."},
        )
    await asyncio.to_thread(update_fraud_case_status, case_id, "approved", "APPROVE")
    return make_envelope(
        CaseActionData(
            case_id=case_id,
            status="approved",
            action_taken="APPROVE",
            reason=payload.reason,
        )
    )


@router.post(
    "/accounts/{account}/freeze",
    response_model=ResponseEnvelope[AccountActionData],
    status_code=status.HTTP_200_OK,
)
async def freeze_account(
    account: str,
    payload: AccountFreezeRequest,
) -> ResponseEnvelope[AccountActionData]:
    """Admin-initiated freeze of a bank account (persisted to accounts table)."""
    account_row = await asyncio.to_thread(fetch_account_by_number, account)
    if not account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ACCOUNT_NOT_FOUND",
                "message": f"Account {account} not found.",
            },
        )
    now = datetime.now(UTC)
    frozen_at = now.isoformat()
    unfreeze_at = (now + timedelta(minutes=30)).isoformat()
    await asyncio.to_thread(
        update_account_status,
        account,
        "frozen",
        frozen_at,
        "admin",
        payload.reason,
        unfreeze_at,
    )
    await asyncio.to_thread(freeze_transactions_by_sender, account, 1800)
    return make_envelope(
        AccountActionData(
            account_number=account,
            status="frozen",
            frozen_at=now.isoformat(),
            frozen_by="admin",
            reason=payload.reason,
        )
    )


@router.post(
    "/accounts/{account}/unfreeze",
    response_model=ResponseEnvelope[AccountActionData],
    status_code=status.HTTP_200_OK,
)
async def unfreeze_account(
    account: str,
    payload: AccountUnfreezeRequest,
) -> ResponseEnvelope[AccountActionData]:
    """Admin-initiated unfreeze of a bank account (persisted to accounts table)."""
    account_row = await asyncio.to_thread(fetch_account_by_number, account)
    if not account_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "ACCOUNT_NOT_FOUND",
                "message": f"Account {account} not found.",
            },
        )
    now = datetime.now(UTC)
    await asyncio.to_thread(update_account_status, account, "active")
    await asyncio.to_thread(unfreeze_transactions_by_sender, account)
    return make_envelope(
        AccountActionData(
            account_number=account,
            status="active",
            unfrozen_at=now.isoformat(),
            unfrozen_by="admin",
            reason=payload.reason,
        )
    )


@router.get(
    "/accounts",
    response_model=ResponseEnvelope[dict[str, Any]],
    status_code=status.HTTP_200_OK,
)
async def list_accounts() -> ResponseEnvelope[dict[str, Any]]:
    """List real bank accounts from the DB for the admin workbench."""
    accounts = await asyncio.to_thread(fetch_all_accounts, 500)
    return make_envelope({"items": accounts, "total": len(accounts)})


@router.post("/transactions/auto-unfreeze", status_code=status.HTTP_200_OK)
async def trigger_auto_unfreeze() -> dict[str, Any]:
    """Scan and automatically unfreeze any transactions whose cooling-off period has expired."""
    from src.db.supabase import auto_unfreeze_expired_transactions
    unfrozen_records = auto_unfreeze_expired_transactions()
    return {
        "success": True,
        "unfrozen_count": len(unfrozen_records),
        "unfrozen_transactions": unfrozen_records,
    }


@router.get(
    "/analytics/summary",
    response_model=ResponseEnvelope[AnalyticsSummaryData],
    status_code=status.HTTP_200_OK,
)
async def analytics_summary(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> ResponseEnvelope[AnalyticsSummaryData]:
    """Real dashboard summary analytics computed from DB rows."""
    cases = await asyncio.to_thread(fetch_all_cases_for_analytics, 2000)
    transactions = await asyncio.to_thread(fetch_all_transactions_for_analytics, 2000)
    accounts = await asyncio.to_thread(fetch_all_accounts, 500)
    fraud_types = await asyncio.to_thread(fetch_fraud_memory_types)

    def _within_range(iso_str: str) -> bool:
        created = str(iso_str or "")[:10]
        if date_from and created < date_from[:10]:
            return False
        if date_to and created > date_to[:10]:
            return False
        return True

    cases = [c for c in cases if _within_range(str(c.get("created_at") or ""))]

    total_cases = len(cases)
    by_tier: Counter[str] = Counter(str(c.get("risk_tier") or "LOW") for c in cases)
    by_trigger: Counter[str] = Counter(
        str(c.get("trigger_type") or "UNKNOWN") for c in cases
    )
    by_fraud: Counter[str] = Counter(
        str(f.get("fraud_type") or "other") for f in fraud_types
    )

    accounts_frozen = sum(
        1 for a in accounts if str(a.get("status") or "").lower() == "frozen"
    )

    protected_amount = sum(
        float(t.get("amount_myr") or 0.0)
        for t in transactions
        if str(t.get("status") or "")
        in ("frozen", "cooling_off_expired", "rejected")
        or str(t.get("risk_tier") or "") == "HIGH"
    )

    scores = [
        int(c.get("risk_score") or 0)
        for c in cases
        if c.get("risk_score") is not None
    ]
    avg_risk = round(sum(scores) / len(scores), 1) if scores else 0.0

    worker_counts: Counter[str] = Counter()
    for c in cases:
        xr = c.get("xai_report")
        if isinstance(xr, dict):
            for w in xr.get("workers_activated") or []:
                worker_counts[str(w)] += 1

    return make_envelope(
        AnalyticsSummaryData(
            period={"from": date_from or "", "to": date_to or ""},
            total_cases=total_cases,
            by_risk_tier={
                "LOW": by_tier.get("LOW", 0),
                "MEDIUM": by_tier.get("MEDIUM", 0),
                "HIGH": by_tier.get("HIGH", 0),
            },
            by_trigger_type={
                "TRANSACTION": by_trigger.get("TRANSACTION", 0),
                "CALL": by_trigger.get("CALL", 0),
                "PHISHING": by_trigger.get("PHISHING", 0),
                "TELEMETRY": by_trigger.get("TELEMETRY", 0),
            },
            by_fraud_type=dict(by_fraud),
            accounts_frozen=accounts_frozen,
            total_amount_protected_myr=round(protected_amount, 2),
            avg_risk_score=avg_risk,
            worker_activation_counts=dict(worker_counts),
        )
    )


@router.get(
    "/analytics/trend",
    response_model=ResponseEnvelope[AnalyticsTrendData],
    status_code=status.HTTP_200_OK,
)
async def analytics_trend(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    group_by: str | None = Query("day"),
) -> ResponseEnvelope[AnalyticsTrendData]:
    """Real case trend series aggregated by day from fraud_cases rows."""
    cases = await asyncio.to_thread(fetch_all_cases_for_analytics, 2000)

    per_day: dict[str, Counter[str]] = {}
    for c in cases:
        created = str(c.get("created_at") or "")[:10]
        if date_from and created < date_from[:10]:
            continue
        if date_to and created > date_to[:10]:
            continue
        per_day.setdefault(created, Counter())[str(c.get("risk_tier") or "LOW")] += 1

    series = [
        AnalyticsTrendPoint(
            date=day,
            total=sum(counts.values()),
            HIGH=counts.get("HIGH", 0),
            MEDIUM=counts.get("MEDIUM", 0),
            LOW=counts.get("LOW", 0),
        )
        for day, counts in sorted(per_day.items())[-30:]
    ]
    return make_envelope(AnalyticsTrendData(series=series))


@router.get(
    "/alerts",
    response_model=ResponseEnvelope[AdminAlertListResponseData],
    status_code=status.HTTP_200_OK,
)
async def list_alerts(
    status_filter: str | None = Query("pending", alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ResponseEnvelope[AdminAlertListResponseData]:
    """List real admin alerts (pending by default)."""
    offset = (page - 1) * page_size
    alerts = await asyncio.to_thread(
        list_admin_alerts, status_filter or "pending", page_size, offset
    )
    items: list[AdminAlertItem] = []
    for alert in alerts:
        details = alert.get("details")
        if isinstance(details, dict):
            risk_score = int(details.get("risk_score") or 0)
            verdict = str(details.get("verdict_summary") or "")
        else:
            risk_score = 0
            verdict = ""
        items.append(
            AdminAlertItem(
                alert_id=str(alert.get("id") or ""),
                case_id=str(alert.get("case_id") or ""),
                alert_type=str(alert.get("alert_type") or ""),
                status=str(alert.get("status") or "pending"),
                risk_score=risk_score,
                verdict_summary=verdict or "Alert generated by TranSafe.",
                created_at=str(alert.get("created_at") or ""),
            )
        )
    return make_envelope(
        AdminAlertListResponseData(
            items=items,
            total=len(items),
            page=page,
            page_size=page_size,
            has_next=False,
        )
    )


@router.patch(
    "/alerts/{alert_id}",
    response_model=ResponseEnvelope[AdminAlertUpdateData],
    status_code=status.HTTP_200_OK,
)
async def update_alert(
    alert_id: str,
    payload: AdminAlertUpdateRequest,
) -> ResponseEnvelope[AdminAlertUpdateData]:
    """Mark an admin alert as reviewed in the DB."""
    await asyncio.to_thread(
        update_admin_alert, alert_id, payload.status, payload.admin_note
    )
    return make_envelope(
        AdminAlertUpdateData(
            alert_id=alert_id,
            status=payload.status,
            reviewed_at=datetime.now(UTC).isoformat(),
        )
    )
