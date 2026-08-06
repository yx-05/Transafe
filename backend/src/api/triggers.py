import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

logger = logging.getLogger(__name__)

from src.api.dependencies import verify_api_key
from src.api.session_store import session_store
from src.api.websocket_call import broadcast_event, handle_call_ended
from src.services.call_precheck import run_call_precheck
from src.db.supabase import (
    get_user_biometrics,
    insert_telemetry_event,
    insert_transaction,
    lookup_scam_recipient,
    update_transaction_status,
    upsert_user_biometrics,
)
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
    TelemetryIngestRequest,
    TelemetryTriggerData,
    TelemetryTriggerRequest,
    TransactionTriggerData,
    TransactionTriggerRequest,
)
from src.db.supabase import insert_telemetry_event

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
    "/telemetry/event",
    response_model=ResponseEnvelope[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
)
async def ingest_telemetry_event(
    payload: TelemetryIngestRequest,
) -> ResponseEnvelope[dict[str, Any]]:
    """Ingest real-time passive telemetry event into session_store and Supabase."""
    event_dict = {
        "event_type": payload.event_type,
        "event_value": payload.event_value,
        "user_id": payload.user_id,
        "session_id": payload.session_id,
        "device_id": payload.device_id,
    }
    session_store.add_telemetry_event(payload.session_id, event_dict)
    try:
        res = insert_telemetry_event(
            user_id=payload.user_id,
            session_id=payload.session_id,
            device_id=payload.device_id,
            event_type=payload.event_type,
            event_value=payload.event_value,
            app_version=payload.app_version,
        )
        return make_envelope(res or {"status": "recorded"})
    except Exception as err:
        return make_envelope({"status": "recorded_memory", "detail": str(err)})


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

    # Persist transaction record into Supabase public.transactions table
    try:
        insert_transaction(payload.transaction.model_dump())
    except Exception as err:
        logger.warning(f"Failed to persist transaction to DB: {err}")

    # Persist summary telemetry blocks into Supabase telemetry_events table
    try:
        if payload.session_metrics:
            insert_telemetry_event(
                user_id=payload.user_id,
                session_id=payload.session_id,
                device_id="device_web_001",
                event_type="SESSION_METRICS",
                event_value=json.dumps(payload.session_metrics),
            )
        if payload.behavioral_biometrics:
            insert_telemetry_event(
                user_id=payload.user_id,
                session_id=payload.session_id,
                device_id="device_web_001",
                event_type="BEHAVIORAL_BIOMETRICS",
                event_value=json.dumps(payload.behavioral_biometrics),
            )
        if payload.browser_network_fingerprint:
            insert_telemetry_event(
                user_id=payload.user_id,
                session_id=payload.session_id,
                device_id="device_web_001",
                event_type="NETWORK_FINGERPRINT",
                event_value=json.dumps(payload.browser_network_fingerprint),
            )
    except Exception as err:
        logger.warning(f"Failed to persist transaction summary telemetry to DB: {err}")

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

    # Auto-engage AUTO_TALK on incoming unknown calls when opted in: an unknown
    # caller (no real identity claimed) is exactly when the AI should answer first.
    requested_mode = str(payload.call.call_mode or "LISTEN").upper()
    caller_name = str(payload.call.caller_name or "Unknown").strip()
    is_unknown_caller = (not caller_name) or caller_name.lower() in (
        "unknown", "n/a", "unknown caller", "unknown number",
    )
    auto_autotalk = bool(getattr(payload.call, "auto_autotalk_on_unknown", False))
    effective_mode = "AUTO_TALK" if (auto_autotalk and is_unknown_caller) else requested_mode
    auto_engaged = effective_mode == "AUTO_TALK" and requested_mode != "AUTO_TALK"

    session_store.register_call(
        call_session_id=call_session_id,
        session_id=payload.session_id,
        user_id=payload.user_id,
        call_mode=effective_mode,
        caller_number=payload.call.caller_number,
        caller_name=caller_name or "Unknown",
        initiated_by="SCAMMER",
    )
    registered_call = session_store.get_call(call_session_id)
    if registered_call:
        engine_val = getattr(payload.call, "stt_engine", None) or "groq"
        registered_call["stt_engine"] = str(engine_val)

    precheck = run_call_precheck(payload.call.caller_number)
    pre_check = CallPreCheck(
        blacklisted=bool(precheck["blacklisted"]),
        blacklist_cases=int(precheck["blacklist_cases"]),
        spoofed_prefix=bool(precheck["spoofed_prefix"]),
        initial_risk=str(precheck["initial_risk"]),
        warning=precheck["warning"],
    )

    return make_envelope(
        CallTriggerData(
            session_id=payload.session_id,
            call_session_id=call_session_id,
            call_mode=effective_mode,
            call_channel=payload.call.call_channel,
            pre_check=pre_check,
            message=(
                f"Phone session started in {effective_mode} mode "
                f"({payload.call.call_channel})."
                + (
                    " Unknown caller — TranSafe AI auto-engaged (AUTO_TALK). "
                    if auto_engaged else " "
                )
                + "Stream audio to "
                f"/ws/call/{call_session_id}/audio and connect to events at "
                f"/ws/call/{call_session_id}/events"
            ),
            ws_audio_url=f"/ws/call/{call_session_id}/audio",
            ws_events_url=f"/ws/call/{call_session_id}/events",
        )
    )


@router.get("/call/{call_session_id}/tts/{tts_id}")
async def get_tts_audio(call_session_id: str, tts_id: str) -> Response:
    """Fetch a generated AUTO_TALK agent speech MP3 for frontend playback.

    The AUTO_TALK responder broadcasts a ``talking`` event containing a
    ``tts_id``; the customer/scammer UIs fetch the MP3 here and play it via a
    plain HTML5 <audio> element (no WebM/Opus transcoding needed).
    """
    audio = session_store.get_tts_audio(call_session_id, tts_id)
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TTS_NOT_FOUND", "message": "TTS audio not found or expired."},
        )
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/call/{call_session_id}/answer")
async def answer_call(call_session_id: str) -> ResponseEnvelope[dict[str, Any]]:
    """Customer answers an incoming call."""
    call = session_store.get_call(call_session_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call session not found")
    session_store.set_call_status(call_session_id, "ANSWERED")
    return make_envelope({
        "call_session_id": call_session_id,
        "status": "ANSWERED",
        "message": "Call answered. Connect microphone and audio WebSockets."
    })


@router.post("/call/{call_session_id}/decline")
async def decline_call(call_session_id: str) -> ResponseEnvelope[dict[str, Any]]:
    """Customer declines / ends an incoming call.

    Marks the call ended AND broadcasts ``call_ended`` to both the scammer and
    customer event sockets, so the scammer UI also resets. Previously this only
    set the status — the scammer side stayed stuck in the call forever. The
    response keeps ``status="DECLINED"`` for backwards compatibility.
    """
    call = session_store.get_call(call_session_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call session not found")
    await handle_call_ended(call_session_id, "CUSTOMER")
    return make_envelope({
        "call_session_id": call_session_id,
        "status": "DECLINED",
        "message": "Call declined.",
    })


@router.get("/call/active")
async def get_active_call(user_id: str) -> ResponseEnvelope[dict[str, Any] | None]:
    """Fetch current ringing or active call session for a user."""
    call = session_store.get_active_call_for_user(user_id)
    return make_envelope(call)


@router.post("/call/reset")
async def reset_active_calls(user_id: str) -> ResponseEnvelope[dict[str, Any]]:
    """Clear all ringing or active calls for a user."""
    cids = session_store.user_incoming_calls.get(user_id, [])
    for cid in cids:
        session_store.set_call_status(cid, "ENDED")
    return make_envelope({"user_id": user_id, "message": "All active calls cleared."})


@router.post("/call/{call_session_id}/stt_engine")
async def update_stt_engine(call_session_id: str, engine: str) -> ResponseEnvelope[dict[str, Any]]:
    """Update STT engine ('groq' or 'nova-3') for a call session."""
    call = session_store.get_call(call_session_id)
    if call:
        call["stt_engine"] = engine
    return make_envelope({"call_session_id": call_session_id, "stt_engine": engine})


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
    """Report outcome of device-side biometric challenge and persist to DB."""
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

    # 1. Persist biometric result event into Supabase telemetry_events table
    try:
        insert_telemetry_event(
            user_id=payload.user_id,
            session_id=payload.session_id,
            device_id="device_web_001",
            event_type="BIOMETRIC_CHALLENGE_RESULT",
            event_value=json.dumps({
                "transaction_id": payload.transaction_id,
                "result": res,
                "status": tx_status,
                "timestamp": datetime.now(UTC).isoformat(),
            }),
        )
    except Exception as err:
        logger.warning(f"Failed to persist biometric result event to DB: {err}")

    # 2. Update transaction status in Supabase transactions table
    try:
        update_transaction_status(
            transaction_id=payload.transaction_id,
            status=tx_status,
        )
    except Exception as err:
        logger.warning(f"Failed to update transaction status in DB: {err}")

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

    # Broadcast the mode change so both the customer and scammer UIs update live
    try:
        await broadcast_event(call_session_id, {
            "type": "mode_change",
            "call_session_id": call_session_id,
            "call_mode": "AUTO_TALK",
            "timestamp": datetime.now(UTC).isoformat(),
        })
    except Exception as err:  # noqa: BLE001
        logger.warning(f"Failed to broadcast mode_change for {call_session_id}: {err}")

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


@router.get("/user/biometrics/{user_id}")
async def fetch_biometrics_status(
    user_id: str, _api_key: str = Depends(verify_api_key)
) -> dict[str, Any]:
    """Fetch biometric registration status for a user."""
    data = get_user_biometrics(user_id)
    return {"success": True, "data": data}


@router.post("/user/biometrics/register")
async def register_user_biometrics(
    payload: dict[str, Any], _api_key: str = Depends(verify_api_key)
) -> dict[str, Any]:
    """Register TouchID or Face baseline biometrics for a user."""
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    res = upsert_user_biometrics(
        user_id=user_id,
        fingerprint_registered=payload.get("fingerprint_registered"),
        face_enrolled=payload.get("face_enrolled"),
        face_embedding=payload.get("face_embedding"),
        passkey_credential_id=payload.get("passkey_credential_id"),
        security_pin=payload.get("security_pin"),
    )
    return {"success": True, "data": res}


@router.get("/recipient/lookup")
async def lookup_recipient_account(
    account_number: str = Query(..., description="Recipient bank account number"),
    _api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Lookup beneficiary account name and scam risk status for an account number."""
    rec = lookup_scam_recipient(account_number=account_number)
    if rec:
        return {"success": True, "data": rec}
    return {
        "success": True,
        "data": {
            "account_number": account_number,
            "beneficiary_name": "Standard Transfer Account",
            "bank_name": "Malaysian Retail Bank",
            "risk_level": "LOW",
            "scam_category": "Standard Account",
        },
    }
