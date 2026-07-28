"""REST API Trigger Endpoints for TranSafe User App."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.dependencies import verify_api_key
from src.api.session_store import session_store
from src.models.schemas import (
    BiometricResultData,
    BiometricResultRequest,
    CallPreCheck,
    CallTakeoverData,
    CallTriggerData,
    CallTriggerRequest,
    PhishingTriggerData,
    PhishingTriggerRequest,
    RecentCaseItem,
    RecentCasesData,
    ReportTriggerData,
    ReportTriggerRequest,
    ResponseEnvelope,
    TelemetryTriggerData,
    TelemetryTriggerRequest,
    TransactionTriggerData,
    TransactionTriggerRequest,
)

router = APIRouter(tags=["triggers"], dependencies=[Depends(verify_api_key)])


def make_envelope(data: Any) -> ResponseEnvelope[Any]:
    """Helper to wrap endpoint return data in standard ResponseEnvelope."""
    return ResponseEnvelope(
        success=True,
        data=data,
        error=None,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.post(
    "/trigger/telemetry",
    response_model=ResponseEnvelope[TelemetryTriggerData],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_telemetry(
    payload: TelemetryTriggerRequest,
) -> ResponseEnvelope[TelemetryTriggerData]:
    """Trigger telemetry risk analysis."""
    session_store.register_session(
        session_id=payload.session_id,
        trigger_type="TELEMETRY",
        user_id=payload.user_id,
        payload=payload.model_dump(),
    )
    return make_envelope(
        TelemetryTriggerData(
            session_id=payload.session_id,
            message="Telemetry analysis initiated. Connect to WebSocket for results.",
        )
    )


@router.post(
    "/trigger/transaction",
    response_model=ResponseEnvelope[TransactionTriggerData],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_transaction(
    payload: TransactionTriggerRequest,
) -> ResponseEnvelope[TransactionTriggerData]:
    """Trigger transaction pre-execution risk assessment."""
    session_store.register_session(
        session_id=payload.session_id,
        trigger_type="TRANSACTION",
        user_id=payload.user_id,
        payload=payload.model_dump(),
    )
    return make_envelope(
        TransactionTriggerData(
            session_id=payload.session_id,
            transaction_id=payload.transaction.transaction_id,
            message="Risk assessment initiated. Connect to WebSocket for results.",
            estimated_seconds=10,
        )
    )


@router.post(
    "/trigger/call",
    response_model=ResponseEnvelope[CallTriggerData],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_call(
    payload: CallTriggerRequest,
) -> ResponseEnvelope[CallTriggerData]:
    """Trigger phone call risk assessment and initialize phone session."""
    call_session_id = f"call-{uuid.uuid4().hex[:12]}"
    session_store.register_session(
        session_id=payload.session_id,
        trigger_type="CALL",
        user_id=payload.user_id,
        payload=payload.model_dump(),
    )
    session_store.register_call(
        call_session_id=call_session_id,
        session_id=payload.session_id,
        user_id=payload.user_id,
        call_mode=payload.call.call_mode,
    )

    blacklisted = payload.call.caller_number in [
        "+60161234567",
        "0161234567",
        "+60197654321",
    ]
    pre_check = CallPreCheck(
        blacklisted=blacklisted,
        blacklist_cases=2 if blacklisted else 0,
        initial_risk="HIGH" if blacklisted else "LOW",
        warning=(
            "This number has been reported 2 times for impersonation scams."
            if blacklisted
            else None
        ),
    )

    return make_envelope(
        CallTriggerData(
            session_id=payload.session_id,
            call_session_id=call_session_id,
            call_mode=payload.call.call_mode,
            call_channel=payload.call.call_channel,
            pre_check=pre_check,
            message=(
                f"Phone session started in {payload.call.call_mode} mode "
                f"({payload.call.call_channel}). Stream audio to "
                f"/ws/call/{call_session_id}/audio and connect to events at "
                f"/ws/call/{call_session_id}/events"
            ),
            ws_audio_url=f"/ws/call/{call_session_id}/audio",
            ws_events_url=f"/ws/call/{call_session_id}/events",
        )
    )


@router.post(
    "/trigger/phishing",
    response_model=ResponseEnvelope[PhishingTriggerData],
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_phishing(
    payload: PhishingTriggerRequest,
) -> ResponseEnvelope[PhishingTriggerData]:
    """Submit suspicious text, URL, or image for phishing analysis."""
    session_store.register_session(
        session_id=payload.session_id,
        trigger_type="PHISHING",
        user_id=payload.user_id,
        payload=payload.model_dump(),
    )
    return make_envelope(
        PhishingTriggerData(
            session_id=payload.session_id,
            message="Phishing analysis initiated.",
            estimated_seconds=12,
        )
    )


@router.post(
    "/trigger/report",
    response_model=ResponseEnvelope[ReportTriggerData],
    status_code=status.HTTP_200_OK,
)
async def trigger_report(
    payload: ReportTriggerRequest,
) -> ResponseEnvelope[ReportTriggerData]:
    """Submit a user fraud report."""
    case_id = f"case-{uuid.uuid4().hex[:12]}"
    entities = {
        "phone_numbers": payload.report.phone_numbers,
        "bank_accounts": payload.report.bank_accounts,
    }
    return make_envelope(
        ReportTriggerData(
            case_id=case_id,
            message=(
                "Thank you for your report. Your information helps protect"
                " other users."
            ),
            entities_recorded=entities,
        )
    )


@router.post(
    "/biometric/result",
    response_model=ResponseEnvelope[BiometricResultData],
    status_code=status.HTTP_200_OK,
)
async def biometric_result(
    payload: BiometricResultRequest,
) -> ResponseEnvelope[BiometricResultData]:
    """Report outcome of device-side biometric challenge."""
    res = payload.biometric_result.upper()
    if res == "PASSED":
        tx_status = "approved"
        msg = "Biometric authentication passed. Transaction approved."
        msg_ms = "Pengesahan biometrik berjaya. Transaksi diluluskan."
    elif res in ("FAILED", "DECLINED"):
        tx_status = "blocked"
        msg = "Biometric authentication failed. Transaction blocked."
        msg_ms = "Pengesahan biometrik gagal. Transaksi disekat."
    else:
        tx_status = "manual_review"
        msg = (
            "Biometric authentication unavailable. Transaction held for"
            " review."
        )
        msg_ms = "Pengesahan biometrik tidak tersedia. Transaksi disemak."

    return make_envelope(
        BiometricResultData(
            session_id=payload.session_id,
            transaction_id=payload.transaction_id,
            transaction_status=tx_status,
            message=msg,
            message_ms=msg_ms,
        )
    )


@router.post(
    "/call/{session_id}/takeover",
    response_model=ResponseEnvelope[CallTakeoverData],
    status_code=status.HTTP_200_OK,
)
async def call_takeover(session_id: str) -> ResponseEnvelope[CallTakeoverData]:
    """Switch an active LISTEN mode call to AUTO_TALK mode mid-call."""
    call = session_store.get_call(session_id)
    if not call:
        matching_call = None
        for c_id, c_data in session_store.call_sessions.items():
            if c_data.get("session_id") == session_id or c_id == session_id:
                matching_call = c_data
                break
        if not matching_call:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NOT_FOUND",
                    "message": (
                        f"No active call session found for session_id"
                        f" '{session_id}'"
                    ),
                },
            )
        call = matching_call

    call_session_id = str(call["call_session_id"])
    if call.get("status") == "ENDED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CALL_ENDED",
                "message": "Call session has ended — takeover not possible.",
            },
        )
    if call.get("call_mode") == "AUTO_TALK":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALREADY_AUTO_TALK",
                "message": "Session is already in AUTO_TALK mode.",
            },
        )

    session_store.set_call_mode(call_session_id, "AUTO_TALK")
    return make_envelope(
        CallTakeoverData(
            session_id=call_session_id,
            call_mode="AUTO_TALK",
            message="TranSafe is now speaking on your behalf.",
            ws_events_url=f"/ws/call/{call_session_id}/events",
        )
    )


@router.get(
    "/cases/recent",
    response_model=ResponseEnvelope[RecentCasesData],
    status_code=status.HTTP_200_OK,
)
async def get_recent_cases(
    user_id: str = Query(..., description="User UUID"),
) -> ResponseEnvelope[RecentCasesData]:
    """Fetch recent active call sessions or phishing submissions for a user."""
    raw_cases = session_store.get_recent_cases(user_id)
    recent_items = [
        RecentCaseItem(
            case_id=c.get("case_id", ""),
            trigger_type=c.get("trigger_type", "CALL"),
            caller_number=c.get("caller_number"),
            risk_tier=c.get("risk_tier", "HIGH"),
            created_at=c.get(
                "created_at", datetime.now(UTC).isoformat()
            ),
        )
        for c in raw_cases
    ]
    return make_envelope(
        RecentCasesData(
            has_recent_activity=len(recent_items) > 0,
            recent_cases=recent_items,
        )
    )
