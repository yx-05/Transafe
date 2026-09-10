"""Pydantic models and schemas for TranSafe API requests and responses."""

import base64
import binascii
from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

DataT = TypeVar("DataT")


class ResponseEnvelope(BaseModel, Generic[DataT]):  # noqa: UP046
    """Standard API response envelope for all TranSafe endpoints."""

    success: bool = True
    data: DataT | None = None
    error: dict[str, Any] | None = None
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


# Telemetry Trigger Schemas
class TelemetryIngestRequest(BaseModel):
    user_id: str
    session_id: str
    device_id: str = "unknown_device"
    event_type: str
    event_value: str | None = None
    app_version: str = "1.0.0"


class TelemetryEventItem(BaseModel):
    event_type: str
    event_value: str | None = None
    timestamp: str


class SessionMetrics(BaseModel):
    time_on_page_seconds: int | None = None
    tab_switch_count: int | None = None
    page_focused: bool | None = None


class BehavioralBiometrics(BaseModel):
    is_account_number_pasted: bool | None = None
    avg_keystroke_flight_time_ms: float | None = None
    backspace_count: int | None = None
    mouse_cursor_erratic_score: int | None = None
    device_tremor_detected: bool | None = None


class BrowserNetworkFingerprint(BaseModel):
    browser_fingerprint_hash: str | None = None
    user_agent: str | None = None
    screen_resolution: str | None = None
    network_type: str | None = None
    browser_timezone: str | None = None


class TelemetryTriggerRequest(BaseModel):
    user_id: str
    session_id: str
    device_id: str
    app_version: str | None = None
    events: list[TelemetryEventItem] = Field(default_factory=list)
    session_metrics: SessionMetrics | None = None
    behavioral_biometrics: BehavioralBiometrics | None = None
    browser_network_fingerprint: BrowserNetworkFingerprint | None = None


class TelemetryTriggerData(BaseModel):
    session_id: str
    message: str = "Telemetry analysis initiated. Connect to WebSocket for results."


# Transaction Trigger Schemas
class TransactionDetail(BaseModel):
    transaction_id: str
    sender_account: str
    recipient_account: str
    recipient_name: str | None = None
    amount: float
    currency: str = "MYR"
    description: str | None = None
    initiated_at: str


class TransactionTriggerRequest(BaseModel):
    user_id: str
    session_id: str
    associated_case_id: str | None = None
    transaction: TransactionDetail
    session_metrics: dict[str, Any] | None = None
    behavioral_biometrics: dict[str, Any] | None = None
    browser_network_fingerprint: dict[str, Any] | None = None


class TransactionTriggerData(BaseModel):
    session_id: str
    transaction_id: str
    message: str = "Risk assessment initiated. Connect to WebSocket for results."
    estimated_seconds: int = 10


# Call Trigger Schemas
class CallDetail(BaseModel):
    caller_number: str
    caller_name: str | None = "Unknown"
    call_direction: str = "INCOMING"
    received_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    is_during_banking_session: bool = True
    call_mode: str = "LISTEN"
    call_channel: str = "WEBRTC"
    stt_engine: str = "dashscope"
    auto_autotalk_on_unknown: bool = False


class CallTriggerRequest(BaseModel):
    user_id: str
    session_id: str
    associated_case_id: str | None = None
    call: CallDetail


class CallPreCheck(BaseModel):
    blacklisted: bool = False
    blacklist_cases: int = 0
    spoofed_prefix: bool = False
    initial_risk: str = "LOW"
    warning: str | None = None


class CallTriggerData(BaseModel):
    session_id: str
    call_session_id: str
    call_mode: str
    call_channel: str
    pre_check: CallPreCheck
    message: str
    ws_audio_url: str
    ws_events_url: str


# Phishing Trigger Schemas
class PhishingMaterial(BaseModel):
    content_type: str
    content: str
    source: str = "SMS"

    @model_validator(mode="after")
    def _validate_image_size(self) -> "PhishingMaterial":
        if str(self.content_type).upper() != "IMAGE":
            return self

        content = self.content.strip()
        if not content:
            raise ValueError("Image content is required for phishing image analysis.")

        if content.startswith("data:") and "," in content:
            content = content.split(",", 1)[1]

        try:
            decoded = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid base64 image payload.") from exc

        if len(decoded) > 10 * 1024 * 1024:
            raise ValueError("Image upload exceeds the 10 MB limit.")

        return self


class PhishingTriggerRequest(BaseModel):
    user_id: str
    session_id: str
    associated_case_id: str | None = None
    material: PhishingMaterial


class PhishingTriggerData(BaseModel):
    session_id: str
    message: str = "Phishing analysis initiated."
    estimated_seconds: int = 12


# Biometric Result Schemas
class BiometricResultRequest(BaseModel):
    user_id: str
    session_id: str
    transaction_id: str
    biometric_result: str
    method: str = "TOUCH_ID"
    attempted_at: str | None = None


class BiometricResultData(BaseModel):
    session_id: str
    transaction_id: str
    transaction_status: str
    message: str
    message_ms: str | None = None


# Call Takeover Schemas
class CallTakeoverData(BaseModel):
    session_id: str
    call_mode: str = "AUTO_TALK"
    message: str = "TranSafe is now speaking on your behalf."
    ws_events_url: str


# Recent Cases Schemas
class RecentCaseItem(BaseModel):
    case_id: str
    trigger_type: str
    caller_number: str | None = None
    risk_tier: str | None = None
    risk_score: int = 0
    status: str = "pending"
    user_label: str = "unlabeled"
    archetype: str | None = None
    snippet: str | None = None
    created_at: str


class RecentCasesData(BaseModel):
    has_recent_activity: bool
    recent_cases: list[RecentCaseItem] = Field(default_factory=list)


class CaseLabelRequest(BaseModel):
    label: Literal["fraud", "benign", "unlabeled"] = "fraud"


class CaseLabelData(BaseModel):
    case_id: str
    user_label: str
    message: str


# Admin Endpoints Schemas
class AdminCaseItem(BaseModel):
    case_id: str
    user_id: str
    trigger_type: str
    risk_score: int
    risk_tier: str
    status: str
    action_taken: str
    created_at: str
    verdict_summary: str | None = None


class AdminCaseListResponseData(BaseModel):
    items: list[AdminCaseItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_next: bool = False


class AccountFreezeRequest(BaseModel):
    reason: str
    case_id: str | None = None
    admin_note: str | None = None


class AccountUnfreezeRequest(BaseModel):
    reason: str
    case_id: str | None = None
    admin_note: str | None = None


class AccountActionData(BaseModel):
    account_number: str
    status: str
    frozen_at: str | None = None
    unfrozen_at: str | None = None
    frozen_by: str | None = None
    unfrozen_by: str | None = None
    reason: str | None = None


class AnalyticsSummaryData(BaseModel):
    period: dict[str, str] = Field(default_factory=dict)
    total_cases: int = 0
    by_risk_tier: dict[str, int] = Field(default_factory=dict)
    by_trigger_type: dict[str, int] = Field(default_factory=dict)
    by_fraud_type: dict[str, int] = Field(default_factory=dict)
    accounts_frozen: int = 0
    total_amount_protected_myr: float = 0.0
    avg_risk_score: float = 0.0
    worker_activation_counts: dict[str, int] = Field(default_factory=dict)


class AnalyticsTrendPoint(BaseModel):
    date: str
    total: int
    HIGH: int = 0
    MEDIUM: int = 0
    LOW: int = 0


class AnalyticsTrendData(BaseModel):
    series: list[AnalyticsTrendPoint] = Field(default_factory=list)


class AdminAlertItem(BaseModel):
    alert_id: str
    case_id: str
    alert_type: str
    status: str
    risk_score: int
    verdict_summary: str
    created_at: str


class AdminAlertListResponseData(BaseModel):
    items: list[AdminAlertItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    has_next: bool = False


class AdminAlertUpdateRequest(BaseModel):
    status: str
    admin_note: str | None = None


class AdminAlertUpdateData(BaseModel):
    alert_id: str
    status: str
    reviewed_at: str


class CaseActionData(BaseModel):
    case_id: str
    status: str
    action_taken: str
    unfreeze_at: str | None = None
    reason: str | None = None
