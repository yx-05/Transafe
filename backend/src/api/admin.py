"""Admin REST Endpoints for TranSafe Fraud Operations Dashboard."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status

from src.api.dependencies import verify_admin_key
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


@router.get(
    "/cases",
    response_model=ResponseEnvelope[AdminCaseListResponseData],
    status_code=status.HTTP_200_OK,
)
async def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    risk_tier: str | None = Query("all"),
    status: str | None = Query("all"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    trigger_type: str | None = Query("all"),
) -> ResponseEnvelope[AdminCaseListResponseData]:
    """List fraud cases with filtering and pagination."""
    now = datetime.now(UTC).isoformat()
    mock_items = [
        AdminCaseItem(
            case_id="case-101",
            user_id="usr-123",
            trigger_type="TRANSACTION",
            risk_score=82,
            risk_tier="HIGH",
            status="frozen",
            action_taken="FREEZE_30_MIN",
            created_at=now,
            verdict_summary="Multiple fraud indicators detected...",
        ),
        AdminCaseItem(
            case_id="case-102",
            user_id="usr-456",
            trigger_type="CALL",
            risk_score=91,
            risk_tier="HIGH",
            status="reported",
            action_taken="FREEZE_30_MIN",
            created_at=now,
            verdict_summary="Macau impersonation scam call detected.",
        ),
    ]

    return make_envelope(
        AdminCaseListResponseData(
            items=mock_items,
            total=len(mock_items),
            page=page,
            page_size=page_size,
            has_next=False,
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
    """Retrieve full detail for a single fraud case."""
    now = datetime.now(UTC).isoformat()
    data = {
        "case_id": case_id,
        "user_id": "usr-123",
        "trigger_type": "TRANSACTION",
        "risk_score": 82,
        "risk_tier": "HIGH",
        "status": "frozen",
        "action_taken": "FREEZE_30_MIN",
        "unfreeze_at": now,
        "xai_report": {
            "verdict_summary": "Suspicious transaction to known scam account.",
            "risk_score": 82,
            "risk_tier": "HIGH",
        },
        "created_at": now,
        "updated_at": now,
    }
    return make_envelope(data)


@router.post(
    "/accounts/{account}/freeze",
    response_model=ResponseEnvelope[AccountActionData],
    status_code=status.HTTP_200_OK,
)
async def freeze_account(
    account: str,
    payload: AccountFreezeRequest,
) -> ResponseEnvelope[AccountActionData]:
    """Admin-initiated freeze of a bank account."""
    now = datetime.now(UTC).isoformat()
    return make_envelope(
        AccountActionData(
            account_number=account,
            status="frozen",
            frozen_at=now,
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
    """Admin-initiated unfreeze of a bank account."""
    now = datetime.now(UTC).isoformat()
    return make_envelope(
        AccountActionData(
            account_number=account,
            status="active",
            unfrozen_at=now,
            unfrozen_by="admin",
            reason=payload.reason,
        )
    )


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
    """Retrieve dashboard summary analytics."""
    return make_envelope(
        AnalyticsSummaryData(
            period={"from": date_from or "2026-07-01", "to": date_to or "2026-07-26"},
            total_cases=142,
            by_risk_tier={"LOW": 89, "MEDIUM": 35, "HIGH": 18},
            by_trigger_type={
                "TRANSACTION": 67,
                "CALL": 42,
                "PHISHING": 28,
                "REPORT": 5,
            },
            by_fraud_type={
                "MACAU_SCAM": 31,
                "INVESTMENT_SCAM": 24,
                "IMPERSONATION_SCAM": 19,
                "PHISHING": 28,
                "OTHER": 40,
            },
            accounts_frozen=12,
            total_amount_protected_myr=287500.0,
            avg_risk_score=52.3,
            worker_activation_counts={
                "financial": 67,
                "telemetry": 72,
                "research": 142,
                "phone": 42,
                "phishing": 28,
            },
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
    """Retrieve case trend chart series."""
    series = [
        AnalyticsTrendPoint(date="2026-07-20", total=4, HIGH=1, MEDIUM=2, LOW=1),
        AnalyticsTrendPoint(date="2026-07-21", total=7, HIGH=3, MEDIUM=2, LOW=2),
        AnalyticsTrendPoint(date="2026-07-22", total=3, HIGH=0, MEDIUM=1, LOW=2),
    ]
    return make_envelope(AnalyticsTrendData(series=series))


@router.get(
    "/alerts",
    response_model=ResponseEnvelope[AdminAlertListResponseData],
    status_code=status.HTTP_200_OK,
)
async def list_alerts(
    status: str | None = Query("pending"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ResponseEnvelope[AdminAlertListResponseData]:
    """List unreviewed/reviewed admin alerts."""
    now = datetime.now(UTC).isoformat()
    mock_alerts = [
        AdminAlertItem(
            alert_id=f"alert-{uuid.uuid4().hex[:8]}",
            case_id="case-101",
            alert_type="HIGH_RISK_FREEZE",
            status="pending",
            risk_score=82,
            verdict_summary="Multiple fraud indicators detected.",
            created_at=now,
        )
    ]
    return make_envelope(
        AdminAlertListResponseData(
            items=mock_alerts,
            total=len(mock_alerts),
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
    """Mark an admin alert as reviewed."""
    now = datetime.now(UTC).isoformat()
    return make_envelope(
        AdminAlertUpdateData(
            alert_id=alert_id,
            status=payload.status,
            reviewed_at=now,
        )
    )
