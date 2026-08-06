"""Telemetry Worker Agent for TranSafe Multi-Agent pipeline."""

import inspect
import json
import logging
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from pydantic import SecretStr

from src.agents.prompts import build_telemetry_prompt
from src.agents.state import GraphState, WorkerFinding
from src.db.supabase import fetch_telemetry_events

from src.agents.llm import extract_json_object, invoke_groq_with_key_rotation

logger = logging.getLogger(__name__)


def get_telemetry_llm(model_name: str = "llama-3.1-8b-instant") -> ChatGroq:
    """Get ChatGroq LLM instance reading GROQ_API_KEY dynamically at runtime."""
    raw_key = os.getenv("GROQ_API_KEY") or "gsk_placeholder_key_for_initialization"
    return ChatGroq(model=model_name, temperature=0.0, api_key=SecretStr(raw_key))


class DynamicTelemetryLLM:
    """Dynamic LLM proxy reading GROQ_API_KEY dynamically with multi-key rotation and fallback."""

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        return invoke_groq_with_key_rotation(messages, preferred_model="llama-3.1-8b-instant")


llm = DynamicTelemetryLLM()


TELEMETRY_SYSTEM_PROMPT = """You are an expert fraud behavioral biometrics analyst at a retail bank.
Your job is to analyze the sequence of telemetry events and behavioral biometrics from a user's session and output a risk assessment.
Look for the following signals:
1. Hesitation or Dictation: Typing cadence that is extremely slow (avg flight time > 500ms) or contains high backspace counts, indicating the user is typing under coercion/dictation.
2. Automation/Bots: Flight times near 0ms or highly constant typing speed, indicating automated inputs.
3. Instruction Following: Copy-pasting account numbers or names, erratic mouse cursor movements, and frequent tab switches (indicating user is copying details from WhatsApp/Telegram).
4. Direct Compromise: Orientations changing rapidly, screenshots taken, or active screen sharing flags indicating a remote scammer.

You must respond in strict JSON format with keys "score" (0-100), "confidence" (0.0-1.0), and "evidence" (list of strings)."""


def _rule_based_telemetry_analysis(
    events: list[dict[str, Any]], device_id: str, known_device_id: str | None
) -> WorkerFinding:
    """Fallback / rule-based telemetry evaluation when LLM is unavailable or for deterministic scoring."""
    evidence: list[str] = []
    score = 10
    confidence = 0.85

    if not events:
        evidence.append("No biometric anomalies detected; telemetry event log is empty or clean")
        return WorkerFinding(
            worker="telemetry",
            score=score,
            confidence=confidence,
            evidence=evidence,
        )

    # Biometric analysis with safe dict gets
    flight_times: list[float] = [
        float(e.get("event_value"))  # type: ignore[arg-type]
        for e in events
        if e.get("event_type") in ("KEYSTROKE", "FLIGHT_TIME")
        and isinstance(e.get("event_value"), (int, float))
    ]
    copy_pastes = [e for e in events if e.get("event_type") in ("COPY_PASTE", "PASTE")]
    tab_switches = [e for e in events if e.get("event_type") == "TAB_SWITCH"]
    screen_shares = [
        e
        for e in events
        if e.get("event_type") in ("SCREEN_SHARE_DETECTED", "REMOTE_ACCESS")
        or e.get("event_value") == "SCREEN_SHARE_DETECTED"
        or e.get("event_value") is True
    ]

    if flight_times:
        avg_flight_time = sum(flight_times) / len(flight_times)
        if avg_flight_time > 500:
            score += 35
            evidence.append(
                f"Elevated keystroke flight time (avg {avg_flight_time:.1f}ms) indicates hesitation or manual dictation"
            )
        elif avg_flight_time < 10:
            score += 40
            evidence.append(
                f"Extremely low flight time (avg {avg_flight_time:.1f}ms) suggests automated bot input"
            )

    if copy_pastes:
        score += 25
        evidence.append(
            f"Detected {len(copy_pastes)} copy-paste event(s) into transaction input fields"
        )

    if tab_switches:
        score += 15
        evidence.append(
            f"Detected {len(tab_switches)} tab switch(es) during transaction entry"
        )

    if screen_shares:
        score += 50
        evidence.append("Active screen sharing or remote access software detected")

    if known_device_id and device_id and device_id != known_device_id:
        score += 20
        evidence.append(f"Device ID mismatch: active device '{device_id}' differs from registered device")

    score = min(score, 100)
    if not evidence:
        evidence.append("Device fingerprint and user behavioral biometrics are within normal ranges")

    return WorkerFinding(
        worker="telemetry",
        score=score,
        confidence=confidence,
        evidence=evidence,
    )


def telemetry_worker_node(state: GraphState) -> dict[str, Any]:
    """Pure state transformation node for Telemetry Worker.

    Analyzes behavioral biometrics, typing flight times, copy-pastes,
    tab switches, and device posture.

    Handles missing optional biometric fields gracefully.
    """
    user_id = str(state.get("user_id", ""))
    session_id = str(state.get("session_id", ""))
    payload = state.get("trigger_payload") or {}

    device_id = str(payload.get("device_id") or state.get("device_id", "unknown_device"))
    known_device_id_raw = payload.get("known_device_id")
    known_device_id = str(known_device_id_raw) if known_device_id_raw is not None else None

    # Fetch events from payload, DB, or session_store memory
    events: list[dict[str, Any]] = []
    if "telemetry_events" in payload and isinstance(payload["telemetry_events"], list):
        events = payload["telemetry_events"]
    elif user_id and session_id:
        try:
            raw_res = fetch_telemetry_events(user_id, session_id)
            if inspect.isawaitable(raw_res):
                events = []
            elif isinstance(raw_res, list):
                events = raw_res
        except Exception as err:  # noqa: BLE001
            logger.warning(f"Failed to fetch telemetry events from DB: {err}")
            events = []

    # Read from in-memory session_store if DB returned empty
    if not events and session_id:
        from src.api.session_store import session_store
        events = session_store.get_telemetry_events(session_id)

    # If events log is empty, construct events from session_metrics / behavioral_biometrics in payload
    if not events:
        metrics = payload.get("session_metrics") or {}
        biometrics = payload.get("behavioral_biometrics") or {}
        if biometrics.get("avg_flight_time_ms"):
            events.append({"event_type": "KEYSTROKE", "event_value": biometrics.get("avg_flight_time_ms")})
        if biometrics.get("screen_share_detected"):
            events.append({"event_type": "SCREEN_SHARE_DETECTED", "event_value": True})
        if metrics.get("copy_paste_events"):
            for _ in range(int(metrics.get("copy_paste_events"))):
                events.append({"event_type": "COPY_PASTE", "event_value": True})
        if metrics.get("tab_switches"):
            for _ in range(int(metrics.get("tab_switches"))):
                events.append({"event_type": "TAB_SWITCH", "event_value": True})

    # Run default rule-based analysis as baseline
    finding = _rule_based_telemetry_analysis(events, device_id, known_device_id)

    # Attempt LLM analysis if LLM is active / mocked
    try:
        prompt_text = build_telemetry_prompt(
            user_id=user_id,
            session_id=session_id,
            device_id=device_id,
            events=events,
            metrics=payload.get("session_metrics"),
            biometrics=payload.get("behavioral_biometrics"),
            fingerprint=payload.get("browser_network_fingerprint"),
        )
        messages = [
            SystemMessage(content=TELEMETRY_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text),
        ]
        llm_response = llm.invoke(messages)
        parsed = extract_json_object(llm_response.content if hasattr(llm_response, "content") else llm_response)
        if isinstance(parsed, dict):
            score = int(parsed.get("score", finding.score))
            confidence = float(parsed.get("confidence", finding.confidence))
            evidence = list(parsed.get("evidence", finding.evidence))
            if not evidence:
                if score == 0:
                    evidence = ["Device fingerprint, typing cadence, and behavioral biometrics are within normal ranges."]
                else:
                    evidence = [f"Behavioral telemetry risk evaluated with score {score}/100."]
            finding = WorkerFinding(
                worker="telemetry",
                score=score,
                confidence=confidence,
                evidence=evidence,
            )
    except Exception as err:  # noqa: BLE001
        logger.debug(f"Telemetry LLM invocation skipped or failed, using rule base: {err}")

    return {"telemetry_finding": finding.model_dump()}
