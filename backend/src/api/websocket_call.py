"""WebSocket handlers for WebRTC phone call audio streaming, relaying, synchronized call ending, and real-time STT."""

import asyncio
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.agents.workers.phone import (
    AUTOTALK_VOICE,
    _fallback_autotalk_reply,
    _run_autotalk_responder,
    phone_worker_node,
)
from src.agents.prompts import get_anchor_questions
from src.agents.workers.phishing import analyze_call_transcript
from src.api.session_store import session_store
from src.db.supabase import (
    insert_call_transcript,
    insert_case_entities,
    insert_fraud_case,
)
from src.services.call_precheck import run_call_precheck
from src.services.stt import transcribe_audio_chunk
from src.services.stt_streaming import DeepgramStreamingSession
from src.services.tts import synthesize_agent_speech

call_ws_router = APIRouter(tags=["call_websockets"])

# In-memory audio buffers, headers, and locks for live STT transcription
call_audio_buffers: dict[str, dict[str, bytearray]] = {}
call_webm_headers: dict[str, dict[str, bytes]] = {}
call_stt_active_locks: dict[str, dict[str, bool]] = {}
call_last_audio_time: dict[str, dict[str, float]] = {}
call_deepgram_sessions: dict[str, dict[str, DeepgramStreamingSession]] = {}
call_phone_states: dict[str, dict[str, Any]] = {}
# In-flight broadcast_text_and_highlights count per call (for call-end deep analysis quiescence)
call_pending_broadcasts: dict[str, int] = {}
# AUTO_TALK reply task guards (one in-flight agent reply per call)
call_autotalk_busy: set[str] = set()

# Minimum seconds between AUTO_TALK agent replies. STT delivers sentence
# fragments and the LLM reply + TTS audio plays for ~6-8s, so replies must be
# spaced out or the agent talks over its own previous utterance.
AUTO_TALK_REPLY_MIN_GAP = 6.0

# Utterance coalescing: the VAD/STT emits multiple "final" fragments for a
# single spoken turn because of natural mid-sentence pauses. We buffer
# same-speaker fragments and emit ONE merged utterance after a short quiet
# window, so a long sentence becomes one chat bubble and the AUTO_TALK agent
# answers the COMPLETE message rather than each broken piece. Hard caps below
# force a flush even while the speaker keeps talking in short bursts.
UTTERANCE_COALESCE_WINDOW = 1.0          # seconds of silence after last fragment
UTTERANCE_COALESCE_MAX_FRAGMENTS = 5     # flush if a turn grows this fragmented
UTTERANCE_COALESCE_MAX_SPAN = 5.0        # flush if a turn has run this long
# cid -> speaker_tag -> {fragments: [str], first_ts: float, flush_task: Task|None}
call_utterance_coalesce: dict[str, dict[str, dict[str, Any]]] = {}


async def broadcast_event(call_session_id: str, event_data: dict[str, Any]) -> None:
    """Helper to broadcast JSON event payloads to all connected event WebSockets for a session."""
    sockets = session_store.get_call_event_sockets(call_session_id)
    dead_sockets = []
    for ws in list(sockets):
        try:
            await ws.send_json(event_data)
        except Exception:
            dead_sockets.append(ws)

    for ws in dead_sockets:
        session_store.remove_call_event_socket(call_session_id, ws)


async def handle_call_ended(call_session_id: str, ended_by_role: str) -> None:
    """Synchronize call ending across both Scammer & Customer UIs.

    The ``call_ended`` event is broadcast FIRST so both UIs reset immediately.
    The final deep Phishing Worker analysis (Groq — can take 30s+ under rate
    limits) and in-memory cleanup run afterwards in a background task, so a
    slow LLM can never delay the visible call end.
    """
    call_data = session_store.get_call(call_session_id)
    if call_data:
        call_data["status"] = "ENDED"

    now = datetime.now(UTC).isoformat()

    end_event = {
        "type": "call_ended",
        "call_session_id": call_session_id,
        "ended_by": ended_by_role,
        "timestamp": now,
    }
    await broadcast_event(call_session_id, end_event)

    # Deep analysis + cleanup in the background — never block call_ended on Groq.
    asyncio.create_task(_finalize_ended_call(call_session_id))


async def _finalize_ended_call(call_session_id: str) -> None:
    """Run the call-end deep analysis, persist the call as a fraud case, then tear down state."""
    deep_event: dict[str, Any] | None = None
    try:
        # Flush any fragments still sitting in the coalesce window so the final
        # deep analysis sees the speaker's complete last message.
        try:
            await _flush_all_coalesced(call_session_id)
        except Exception as err:  # noqa: BLE001
            print(f"[COALESCE FLUSH ❌] {call_session_id} call-end: {err}")
        deep_event = await _run_deep_transcript_analysis(call_session_id, "call_end")
    except Exception as err:  # noqa: BLE001
        print(f"[DEEP ANALYSIS ❌] {call_session_id} call-end: {err}")

    # Persist every call (even LOW risk) as a case so the user can label it later.
    try:
        await _persist_call_case(call_session_id, deep_event)
    except Exception as err:  # noqa: BLE001
        print(f"[PERSIST CASE ❌] {call_session_id}: {err}")

    # Clean up audio buffers immediately
    call_audio_buffers.pop(call_session_id, None)
    call_webm_headers.pop(call_session_id, None)
    call_stt_active_locks.pop(call_session_id, None)
    call_last_audio_time.pop(call_session_id, None)

    # Drop in-memory phone agent state
    call_phone_states.pop(call_session_id, None)
    call_pending_broadcasts.pop(call_session_id, None)
    call_autotalk_busy.discard(call_session_id)
    # Cancel + drop any leftover coalesce entries (fragments already flushed above)
    pending_coalesce = call_utterance_coalesce.pop(call_session_id, {})
    for entry in pending_coalesce.values():
        task = entry.get("flush_task")
        if task and not task.done():
            task.cancel()
    session_store.clear_tts_audio(call_session_id)

    # Close any active Deepgram streaming sessions for this call
    dg_map = call_deepgram_sessions.pop(call_session_id, {})
    for dg in dg_map.values():
        try:
            await dg.close()
        except Exception:  # noqa: BLE001
            pass


def _default_phone_state(call_session_id: str) -> dict[str, Any]:
    """Lazily initialise per-call phone worker state (pre-check, transcript, suspicion)."""
    state = call_phone_states.get(call_session_id)
    if state is not None:
        return state

    call_data = session_store.get_call(call_session_id) or {}
    caller_number = str(call_data.get("caller_number", ""))
    try:
        pre_check = run_call_precheck(caller_number)
    except Exception:  # noqa: BLE001
        pre_check = {"blacklisted": False, "blacklist_cases": 0, "spoofed_prefix": False,
                     "initial_risk": "LOW", "warning": None, "warning_ms": None}

    state = {
        "pre_check": pre_check,
        "transcript": [],
        "processed": 0,
        "cumulative_suspicion": 0,
        "risk_tier": "LOW",
        "escalated": False,
    }
    call_phone_states[call_session_id] = state
    return state


async def _run_deep_transcript_analysis(call_session_id: str, reason: str) -> dict[str, Any] | None:
    """Run the Phishing Worker deep analysis over the full transcript (async).

    Broadcasts a ``deep_analysis`` event with the deep verdict + extracted
    entities. Called on first HIGH escalation (reason='escalation') and at
    call end (reason='call_end').

    Returns the broadcast event dict (or None if there was no transcript /
    the analysis failed) so callers can persist the case.
    """
    phone_state = call_phone_states.get(call_session_id)
    transcript = list((phone_state or {}).get("transcript", []))
    if not transcript:
        return None

    # Wait for in-flight transcript broadcasts to drain (bounded ~8s): call_end
    # arrives on the AUDIO socket while the EVENTS socket may still be processing
    # queued broadcast_transcript messages.
    for _ in range(80):
        if call_pending_broadcasts.get(call_session_id, 0) <= 0:
            break
        await asyncio.sleep(0.1)
    transcript = list((phone_state or {}).get("transcript", []))
    if not transcript:
        return None

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(analyze_call_transcript, transcript),
            timeout=30,
        )
    except Exception as err:  # noqa: BLE001
        print(f"[DEEP ANALYSIS ❌] {call_session_id} reason={reason}: {err}")
        return None

    finding = result.get("phishing_finding") or {}
    score = int(finding.get("score", 0) or 0)
    event = {
        "type": "deep_analysis",
        "call_session_id": call_session_id,
        "reason": reason,
        "score": score,
        "risk_tier": _risk_tier_for_score(score),
        "confidence": float(finding.get("confidence", 0.0) or 0.0),
        "evidence": list(finding.get("evidence") or []),
        "extracted_entities": result.get("extracted_entities") or {},
        "research": result.get("research") or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    await broadcast_event(call_session_id, event)
    print(f"[DEEP ANALYSIS ✅] {call_session_id} reason={reason} score={score}")
    return event


def _uuid_or_new(value: str | None) -> str:
    """Return value if it is UUID-shaped, else a fresh UUID (fraud_cases.session_id is UUID NOT NULL)."""
    if value:
        try:
            uuid.UUID(str(value))
            return value
        except (ValueError, AttributeError):
            pass
    return str(uuid.uuid4())


async def _persist_call_case(
    call_session_id: str, deep_event: dict[str, Any] | None
) -> str | None:
    """Persist a finished call as a fraud case row + transcripts + extracted entities.

    Every call with a transcript is recorded (even LOW risk) so the user can
    label it via the report card afterwards. All DB calls are SYNC Supabase
    operations, so they run via ``asyncio.to_thread``.
    """
    phone_state = call_phone_states.get(call_session_id)
    transcript = list((phone_state or {}).get("transcript", []))
    if not transcript:
        return None

    call_data = session_store.get_call(call_session_id) or {}
    user_id = str(call_data.get("user_id") or "")
    caller_number = str(call_data.get("caller_number") or "")
    real_session_id = str(call_data.get("session_id") or call_session_id)
    if not user_id:
        print(f"[PERSIST CASE ⚠️] {call_session_id}: no user_id — skipping persist")
        return None

    score = 0
    tier = "LOW"
    evidence: list[Any] = []
    extracted_entities: dict[str, Any] = {}
    research: dict[str, Any] = {}
    if deep_event:
        score = int(deep_event.get("score", 0) or 0)
        tier = str(deep_event.get("risk_tier") or _risk_tier_for_score(score))
        evidence = list(deep_event.get("evidence") or [])
        extracted_entities = deep_event.get("extracted_entities") or {}
        research = deep_event.get("research") or {}

    xai_report = {
        "deep_analysis": deep_event,
        "evidence": evidence,
        "extracted_entities": extracted_entities,
        "research": research,
        "confidence": float((deep_event or {}).get("confidence", 0.0) or 0.0),
        "call_session_id": call_session_id,
        "source_session_id": real_session_id,
    }
    action_taken = "AGENT_HANGUP" if tier == "HIGH" else "MONITORED"
    status = "reported" if tier == "HIGH" else "pending"

    try:
        case_id = await asyncio.to_thread(
            insert_fraud_case,
            {
                "session_id": _uuid_or_new(real_session_id),
                "user_id": user_id,
                "trigger_type": "CALL",
                "risk_score": score,
                "risk_tier": tier,
                "status": status,
                "action_taken": action_taken,
                "xai_report": xai_report,
                "caller_number": caller_number,
            },
        )
        if not case_id:
            print(f"[PERSIST CASE ❌] {call_session_id}: insert_fraud_case returned empty")
            return None
    except Exception as err:  # noqa: BLE001
        print(f"[PERSIST CASE ❌] {call_session_id}: {err}")
        return None

    print(f"[PERSIST CASE ✅] {call_session_id}: case={case_id} score={score} tier={tier}")

    # Persist per-utterance transcripts (speaker mapping to DB CHECK values)
    speaker_map = {"SCAMMER": "CALLER", "CUSTOMER": "USER", "TRANSAFE_AI": "AI"}
    for u in transcript:
        speaker = speaker_map.get(str(u.get("speaker", "")).upper())
        if not speaker:
            continue
        text = str(u.get("text", "")).strip()
        if not text:
            continue
        try:
            await asyncio.to_thread(
                insert_call_transcript, case_id, speaker, text, score
            )
        except Exception as err:  # noqa: BLE001
            print(f"[PERSIST CASE ⚠️] {call_session_id} transcript insert: {err}")

    # Persist extracted entities (phone / account / URL)
    entity_rows: list[dict[str, str]] = []
    if caller_number:
        entity_rows.append({"entity_type": "PHONE", "entity_value": caller_number})
    for phone in extracted_entities.get("phone_numbers") or []:
        entity_rows.append({"entity_type": "PHONE", "entity_value": str(phone)})
    for acc in extracted_entities.get("bank_accounts") or []:
        entity_rows.append({"entity_type": "ACCOUNT", "entity_value": str(acc)})
    for url in extracted_entities.get("urls") or []:
        entity_rows.append({"entity_type": "URL", "entity_value": str(url)})
    if entity_rows:
        try:
            await asyncio.to_thread(insert_case_entities, case_id, entity_rows)
        except Exception as err:  # noqa: BLE001
            print(f"[PERSIST CASE ⚠️] {call_session_id} entities insert: {err}")

    return case_id


# Explicit financial/coercion demand tokens. Only these justify hanging up:
# the agent must stay on the line until the scammer actually demands payment,
# card/OTP details, or forbids hanging up / threatens arrest.
_HANGUP_DEMAND_RE = re.compile(
    r"(money|transfer|send\b|bank account|account number|otp|card (number|password|pin)|"
    r"top.?up|payment|deposit|withdraw|safe account|akaun selamat|"
    r"don'?t hang up|do not hang up|must not disconnect|line (is|must) secure|"
    r"arrest|akan ditangkap|police|jail|immediate action|right now|asap|urgent)",
    re.IGNORECASE,
)


def _scammer_demanded_payment(phone_state: dict[str, Any]) -> bool:
    """True when the scammer's recent utterances contain an explicit demand.

    Scans only SCAMMER turns (the agent's own AQ probe wording must not count),
    limited to the last ~6 utterances so stale context can't trigger a hangup.
    """
    transcript = list((phone_state or {}).get("transcript") or [])
    recent = [u for u in transcript if str(u.get("speaker", "")).upper() == "SCAMMER"][-6:]
    return any(_HANGUP_DEMAND_RE.search(str(u.get("text", ""))) for u in recent)


async def _run_autotalk_reply(call_session_id: str) -> None:
    """Generate the AUTO_TALK agent's next spoken reply (async background task).

    Runs the AUTO_TALK responder grounded in the anchor-question + dialogue
    guide skills, synthesizes the reply with edge-tts (MP3, Yasmin voice),
    stores the audio for frontend fetch, and broadcasts a ``talking`` event.
    If the responder confirms a scam signal (action="hangup"), ends the call.

    Triggered after each SCAMMER final transcript while in AUTO_TALK mode.
    """
    phone_state = call_phone_states.get(call_session_id)
    if not phone_state:
        return
    transcript = list(phone_state.get("transcript", []))
    call_data = session_store.get_call(call_session_id)
    if not call_data or call_data.get("status") == "ENDED":
        return

    caller_number = str(call_data.get("caller_number", ""))
    pre_check = phone_state.get("pre_check") or {}
    suspicion = int(phone_state.get("cumulative_suspicion", 0))
    aq_progress = dict(phone_state.get("aq_progress") or {})

    try:
        reply = await asyncio.wait_for(
            asyncio.to_thread(
                _run_autotalk_responder,
                transcript,
                caller_number,
                pre_check,
                suspicion,
                aq_progress,
            ),
            timeout=25,
        )
    except Exception as err:  # noqa: BLE001
        # LLM unavailable/slow (e.g. Groq rate limits) → fall back to the
        # deterministic anchor-question schedule walk instead of staying silent.
        print(f"[AUTO_TALK ⚠️] {call_session_id}: responder failed ({err}); using skill-schedule fallback")
        try:
            anchor_questions = get_anchor_questions()
        except Exception:  # noqa: BLE001
            anchor_questions = []
        reply = _fallback_autotalk_reply(transcript, suspicion, anchor_questions, aq_progress)

    reply_text = str(reply.get("reply", "")).strip()
    if not reply_text:
        return
    action = str(reply.get("action") or "continue")
    signal_detected = bool(reply.get("signal_detected") or False)
    suspicion_delta = max(0, min(50, int(reply.get("suspicion_delta") or 0)))

    # B) Deterministic hangup guard: never end the call unless the scammer has
    # actually demanded payment/coercion. The LLM (or fallback) can be over-eager
    # — e.g. suspicion pegged at 100 + identity-verification failure — so this
    # keeps the agent on the line until an explicit demand is spoken.
    if action == "hangup" and not _scammer_demanded_payment(phone_state):
        print(f"[AUTO_TALK 🛡️] {call_session_id}: LLM wanted hangup but no explicit demand — staying on the line")
        action = "continue"
        signal_detected = False
        suspicion_delta = 0
        reply_text = (
            "Okay, I understand. Please give me a moment — "
            "I need to note this down carefully."
        )

    # Scam confirmed → the agent's final line is the canonical farewell before hanging up.
    if action == "hangup":
        reply_text = "I'm ending this call, bye."
        signal_detected = True

    # Track anchor-question progress in the phone session
    next_aq = str(reply.get("next_aq") or "NONE")
    asked = set(aq_progress.get("asked") or [])
    if next_aq.startswith("AQ-") and next_aq not in asked:
        asked.add(next_aq)
    aq_progress["asked"] = sorted(asked)
    phone_state["aq_progress"] = aq_progress

    # TTS → MP3 (ElevenLabs primary, edge-tts Yasmin fallback), stored for the frontends to fetch and play
    tts_id = f"tts-{int(time.time() * 1000)}"
    try:
        mp3_bytes = await synthesize_agent_speech(reply_text, voice=AUTOTALK_VOICE)
    except Exception as err:  # noqa: BLE001
        print(f"[AUTO_TALK TTS ❌] {call_session_id}: {err}")
        mp3_bytes = b""
    if mp3_bytes:
        session_store.put_tts_audio(call_session_id, tts_id, mp3_bytes)

    await broadcast_event(call_session_id, {
        "type": "talking",
        "call_session_id": call_session_id,
        "speaker": "TRANSAFE_AI",
        "text": reply_text,
        "tts_id": tts_id,
        "action": action,
        "signal_detected": signal_detected,
        "next_aq": next_aq,
        "timestamp": datetime.now(UTC).isoformat(),
    })
    print(f"[AUTO_TALK 🗣️] {call_session_id}: \"{reply_text}\" action={action}")

    # Record when the agent last spoke so the next reply waits out the TTS
    # audio duration (pacing enforced in the reply guard).
    phone_state["last_agent_reply_ts"] = time.time()

    # Confirmed scam signal → agent hangs up after its final line plays
    if action == "hangup":
        await asyncio.sleep(1.5)
        await handle_call_ended(call_session_id, "TRANSAFE_AI")
        return

    # Fold the responder's suspicion delta into the cumulative score
    if suspicion_delta > 0:
        prev = int(phone_state.get("cumulative_suspicion", 0))
        cumulative = min(100, prev + suspicion_delta)
        tier = _risk_tier_for_score(cumulative)
        first_high = bool(tier == "HIGH" and not phone_state.get("escalated"))
        phone_state["cumulative_suspicion"] = cumulative
        phone_state["risk_tier"] = tier
        await broadcast_event(call_session_id, {
            "type": "suspicion_update",
            "call_session_id": call_session_id,
            "suspicion_score": cumulative,
            "risk_tier": tier,
            "utterance_risk_score": suspicion_delta + 10,
            "trigger_escalation": first_high,
            "escalation_reason": (
                "AUTO_TALK agent detected a scam signal during the anchor-question dialogue."
                if first_high else None
            ),
            "evidence": [str(reply.get("reasoning") or "AUTO_TALK agent detected a scam signal.")],
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if first_high:
            phone_state["escalated"] = True
            asyncio.create_task(_run_deep_transcript_analysis(call_session_id, "escalation"))


def _risk_tier_for_score(score: int) -> str:
    """Map a cumulative suspicion score to a risk tier."""
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def _build_highlight_spans(text: str, highlight_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert phone worker highlight events into UI span objects with offsets."""
    spans: list[dict[str, Any]] = []
    lower_text = text.lower()
    for ev in highlight_events:
        phrase = str(ev.get("phrase", ""))
        idx = lower_text.find(phrase.lower()) if phrase else -1
        if idx < 0:
            continue  # only emit spans for phrases actually present in the text
        spans.append({
            "start": max(idx, 0),
            "end": max(idx + len(phrase), 0),
            "phrase": phrase,
            "text": text,
            "risk_level": str(ev.get("risk_level", "HIGH")),
            "reason": str(ev.get("reason", f"Coercion phrase detected ({phrase})")),
            "tag": str(ev.get("tag", "coercion_threat")),
            "utterance_risk_score": int(ev.get("utterance_risk_score", 90)),
        })
    return spans


async def _flush_coalesced_utterance(call_session_id: str, speaker_tag: str) -> None:
    """Merge and broadcast all buffered fragments for (call, speaker) as ONE turn."""
    entry = call_utterance_coalesce.get(call_session_id, {}).pop(speaker_tag, None)
    if not entry:
        return
    frags = entry.get("fragments") or []
    merged = " ".join(f.strip() for f in frags if f and f.strip()).strip()
    if merged:
        await broadcast_text_and_highlights(call_session_id, speaker_tag, merged)


async def _coalesce_waiter(call_session_id: str, speaker_tag: str, entry: dict[str, Any]) -> None:
    """Wait out the quiet window, then flush the merged utterance if still current."""
    try:
        await asyncio.sleep(UTTERANCE_COALESCE_WINDOW)
        current = call_utterance_coalesce.get(call_session_id, {}).get(speaker_tag)
        if current is entry:
            await _flush_coalesced_utterance(call_session_id, speaker_tag)
    except asyncio.CancelledError:
        pass


async def _schedule_coalesced_flush(call_session_id: str, speaker_tag: str, entry: dict[str, Any]) -> None:
    """(Re)start the quiet window for the current coalescing entry."""
    prev = entry.get("flush_task")
    if prev and not prev.done():
        prev.cancel()
    entry["flush_task"] = asyncio.create_task(
        _coalesce_waiter(call_session_id, speaker_tag, entry)
    )


async def queue_utterance_for_broadcast(call_session_id: str, speaker_tag: str, text: str) -> None:
    """Coalesce final STT fragments from the same speaker into one spoken turn.

    Call this from real-time STT paths (Groq buffered / Deepgram streaming)
    instead of ``broadcast_text_and_highlights``. Natural mid-sentence pauses
    make the VAD emit several "final" fragments; buffering them for a short
    window means the UI shows ONE bubble and the AUTO_TALK agent replies to the
    complete message. Explicit/manual transcripts should still call
    ``broadcast_text_and_highlights`` directly.
    """
    if not text or len(text) < 2:
        return

    now = time.time()
    by_speaker = call_utterance_coalesce.setdefault(call_session_id, {})
    entry = by_speaker.get(speaker_tag)
    if entry is None:
        entry = {"fragments": [], "first_ts": now, "flush_task": None}
        by_speaker[speaker_tag] = entry

    entry["fragments"].append(text)

    # Hard caps: the speaker is still going in short bursts — flush now rather
    # than buffering forever. Otherwise (re)start the quiet window so the next
    # fragment continues merging into the same bubble.
    if (
        len(entry["fragments"]) >= UTTERANCE_COALESCE_MAX_FRAGMENTS
        or (now - entry["first_ts"]) >= UTTERANCE_COALESCE_MAX_SPAN
    ):
        await _flush_coalesced_utterance(call_session_id, speaker_tag)
        return

    await _schedule_coalesced_flush(call_session_id, speaker_tag, entry)


async def _flush_all_coalesced(call_session_id: str) -> None:
    """Force-emit any pending coalesced fragments (used when the call ends)."""
    by_speaker = call_utterance_coalesce.pop(call_session_id, {})
    for speaker_tag, entry in by_speaker.items():
        task = entry.get("flush_task")
        if task and not task.done():
            task.cancel()
        frags = entry.get("fragments") or []
        merged = " ".join(f.strip() for f in frags if f and f.strip()).strip()
        if merged:
            # After call end the wrapper preserves the text in the phone state
            # transcript instead of broadcasting — exactly what the final deep
            # analysis needs so no last fragment is lost.
            await broadcast_text_and_highlights(call_session_id, speaker_tag, merged)


async def broadcast_text_and_highlights(call_session_id: str, speaker_tag: str, text: str) -> None:
    """Run each new utterance through the Phone Worker agent and broadcast results.

    Emits: transcript event, highlight event (from worker highlight_events), and a
    suspicion_update event with cumulative suspicion score / risk tier / escalation.
    """
    if not text or len(text) < 2:
        return

    # Track in-flight transcript broadcasts so the call-end deep analysis can wait
    # for the events socket to finish appending queued utterances.
    call_pending_broadcasts[call_session_id] = call_pending_broadcasts.get(call_session_id, 0) + 1
    try:
        # If the call ended while this utterance was still in flight, preserve it
        # in the transcript for the final deep analysis instead of dropping it.
        call_data = session_store.get_call(call_session_id)
        if call_data and call_data.get("status") == "ENDED":
            _default_phone_state(call_session_id)["transcript"].append({
                "utterance_id": f"utt-{int(time.time() * 1000)}",
                "speaker": speaker_tag,
                "text": text,
                "ts": datetime.now(UTC).isoformat(),
            })
            return
        await _broadcast_text_and_highlights_impl(call_session_id, speaker_tag, text)
    finally:
        pending = call_pending_broadcasts.get(call_session_id, 0) - 1
        if pending <= 0:
            call_pending_broadcasts.pop(call_session_id, None)
        else:
            call_pending_broadcasts[call_session_id] = pending


async def _broadcast_text_and_highlights_impl(call_session_id: str, speaker_tag: str, text: str) -> None:
    """Inner implementation of broadcast_text_and_highlights (counter handled by wrapper)."""
    call_data = session_store.get_call(call_session_id)
    now = datetime.now(UTC).isoformat()
    utterance_id = f"utt-{int(time.time() * 1000)}"
    call_mode = str(call_data.get("call_mode", "LISTEN") if call_data else "LISTEN").upper()

    # 1) Broadcast transcript event
    transcript_event = {
        "type": "transcript",
        "call_session_id": call_session_id,
        "utterance_id": utterance_id,
        "speaker": speaker_tag,
        "text": text,
        "timestamp": now,
    }
    await broadcast_event(call_session_id, transcript_event)

    # 2) Run the Phone Worker agent on this new utterance
    phone_state = _default_phone_state(call_session_id)
    phone_state["transcript"].append({
        "utterance_id": utterance_id,
        "speaker": speaker_tag,
        "text": text,
        "ts": now,
    })
    new_utterances = phone_state["transcript"][phone_state["processed"]:]
    phone_state["processed"] = len(phone_state["transcript"])

    worker_state = {
        "trigger_type": "CALL",
        "call_mode": call_mode,
        "trigger_payload": {
            "call": {
                "caller_number": str((call_data or {}).get("caller_number", "")),
                "call_mode": call_mode,
                "transcript": new_utterances,
            }
        },
    }
    pre_check = phone_state.get("pre_check")

    # 2a) Fast rules-only pass → instant highlight wave
    try:
        rule_result = await asyncio.to_thread(phone_worker_node, worker_state, pre_check, False)
    except Exception as err:  # noqa: BLE001
        print(f"[PHONE WORKER ❌] {call_session_id}: {err}")
        rule_result = {}

    rule_events: list[dict[str, Any]] = []
    if rule_result:
        rule_session = rule_result.get("phone_session") or {}
        rule_events = list(rule_session.get("highlight_events") or rule_session.get("highlights") or [])

    rule_spans = _build_highlight_spans(text, rule_events)
    if rule_spans:
        await broadcast_event(call_session_id, {
            "type": "highlight",
            "call_session_id": call_session_id,
            "speaker": speaker_tag,
            "text": text,
            "highlighted_spans": rule_spans,
            "spans": rule_spans,
            "enrichment": "rules",
            "timestamp": now,
        })

    # 2b) LLM-enriched pass → async highlight wave with span-level context
    try:
        worker_result = await asyncio.to_thread(phone_worker_node, worker_state, pre_check, True)
    except Exception as err:  # noqa: BLE001
        print(f"[PHONE WORKER ❌] {call_session_id}: {err}")
        worker_result = {}

    if worker_result:
        print(f"[PHONE WORKER ✅] {call_session_id} mode={call_mode} -> score={worker_result.get('phone_finding', {}).get('score')}")

    highlight_events: list[dict[str, Any]] = []
    finding_score = 10
    finding_evidence: list[str] = []
    if worker_result:
        finding = worker_result.get("phone_finding") or {}
        finding_score = int(finding.get("score", 10))
        finding_evidence = list(finding.get("evidence") or [])
        session = worker_result.get("phone_session") or {}
        highlight_events = list(session.get("highlight_events") or session.get("highlights") or [])

    spans = _build_highlight_spans(text, highlight_events)
    if spans:
        await broadcast_event(call_session_id, {
            "type": "highlight",
            "call_session_id": call_session_id,
            "speaker": speaker_tag,
            "text": text,
            "highlighted_spans": spans,
            "spans": spans,
            "enrichment": "llm",
            "timestamp": now,
        })

    # 3) Accumulate suspicion & broadcast suspicion_update
    prev_score = int(phone_state.get("cumulative_suspicion", 0))
    incremental = max(0, finding_score - 10)
    cumulative = min(100, prev_score + incremental)
    tier = _risk_tier_for_score(cumulative)
    trigger_escalation = bool(tier == "HIGH" and not phone_state.get("escalated"))
    if trigger_escalation:
        phone_state["escalated"] = True

    phone_state["cumulative_suspicion"] = cumulative
    phone_state["risk_tier"] = tier

    suspicion_event = {
        "type": "suspicion_update",
        "call_session_id": call_session_id,
        "suspicion_score": cumulative,
        "risk_tier": tier,
        "utterance_risk_score": finding_score,
        "trigger_escalation": trigger_escalation,
        "escalation_reason": (
            "Cumulative suspicion reached HIGH tier — scam indicators confirmed."
            if trigger_escalation else None
        ),
        "evidence": finding_evidence,
        "timestamp": now,
    }
    await broadcast_event(call_session_id, suspicion_event)

    # 4) On first HIGH escalation, kick off async deep Phishing Worker analysis
    if trigger_escalation:
        asyncio.create_task(_run_deep_transcript_analysis(call_session_id, "escalation"))

    # 5) AUTO_TALK: the agent replies to the scammer's utterance (after a short
    #    natural turn delay, bounded to one in-flight reply per call).
    if (
        call_mode == "AUTO_TALK"
        and speaker_tag == "SCAMMER"
        and call_session_id not in call_autotalk_busy
    ):
        call_autotalk_busy.add(call_session_id)

        async def _autotalk_reply_guard() -> None:
            try:
                # Short natural turn delay before the agent starts replying.
                await asyncio.sleep(0.4)
                # Pace replies: wait out any remaining gap since the agent's
                # last spoken reply so the TTS audio never overlaps. Fragments
                # that arrive during the wait are folded into the transcript,
                # so the reply naturally answers the latest state.
                last_reply_ts = float(phone_state.get("last_agent_reply_ts") or 0.0)
                elapsed = time.time() - last_reply_ts
                if elapsed < AUTO_TALK_REPLY_MIN_GAP:
                    await asyncio.sleep(AUTO_TALK_REPLY_MIN_GAP - elapsed)
                await _run_autotalk_reply(call_session_id)
            finally:
                call_autotalk_busy.discard(call_session_id)

        asyncio.create_task(_autotalk_reply_guard())


async def _process_deepgram_stream(
    call_session_id: str, speaker_role: str, dg: DeepgramStreamingSession
) -> None:
    """Consume Deepgram streaming results and broadcast interim/final transcripts."""
    speaker_tag = "SCAMMER" if speaker_role == "SCAMMER" else "CUSTOMER"
    try:
        while True:
            msg = await dg.receive()
            if not msg or msg.get("type") != "Results":
                continue
            channel = msg.get("channel") or {}
            alternatives = channel.get("alternatives") or []
            if not alternatives:
                continue
            text = (alternatives[0].get("transcript") or "").strip()
            if not text:
                continue
            is_final = bool(msg.get("is_final"))
            if is_final:
                # Coalesce same-speaker fragments into one spoken turn so long
                # sentences with natural pauses become one bubble / one AI reply.
                await queue_utterance_for_broadcast(call_session_id, speaker_tag, text)
            else:
                await broadcast_event(call_session_id, {
                    "type": "transcript_interim",
                    "call_session_id": call_session_id,
                    "speaker": speaker_tag,
                    "text": text,
                    "is_final": False,
                    "timestamp": datetime.now(UTC).isoformat(),
                })
    except Exception as err:  # noqa: BLE001
        # Session closed or network error -> stop consuming
        print(f"[STT DEEPGRAM STREAM ℹ️] Receive loop ended: {err}")


@call_ws_router.websocket("/ws/call/{call_session_id}/audio")
async def ws_call_audio_stream(
    websocket: WebSocket, call_session_id: str
) -> None:
    """WebRTC binary audio stream handler for real-time STT, peer audio relay, and phone session processing."""
    api_key = websocket.query_params.get("api_key")
    role = (websocket.query_params.get("role") or "CUSTOMER").upper()
    expected_key = os.getenv("API_KEY", "transafe-hackathon-key-2026")

    if not api_key or api_key != expected_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    session_store.register_call_audio_socket(call_session_id, role, websocket)

    if call_session_id not in call_audio_buffers:
        call_audio_buffers[call_session_id] = {}
        call_webm_headers[call_session_id] = {}
        call_stt_active_locks[call_session_id] = {}
        call_last_audio_time[call_session_id] = {}

    call_audio_buffers[call_session_id][role] = bytearray()
    call_stt_active_locks[call_session_id][role] = False
    call_last_audio_time[call_session_id][role] = time.time()

    # STT engine mode: deepgram -> live streaming; groq -> buffered batch
    call_data = session_store.get_call(call_session_id)
    stt_engine = (call_data or {}).get("stt_engine", "dashscope")
    dg_session: DeepgramStreamingSession | None = None
    dg_task: asyncio.Task | None = None
    if str(stt_engine).lower() in ("deepgram", "nova-3", "nova3"):
        dg_session = DeepgramStreamingSession(language="en")
        try:
            await dg_session.connect()
            call_deepgram_sessions.setdefault(call_session_id, {})[role] = dg_session
            dg_task = asyncio.create_task(
                _process_deepgram_stream(call_session_id, role, dg_session)
            )
            print(f"[STT DEEPGRAM STREAM 🎙️] Live streaming session for {role} ({call_session_id})")
        except Exception as err:  # noqa: BLE001
            print(f"[STT DEEPGRAM STREAM ❌] Connect failed for {role}: {err}")
            dg_session = None

    try:
        while True:
            now_ts = time.time()
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=0.2)
            except asyncio.TimeoutError:
                # Silence flushing check: Trigger STT if speaker paused for > 0.6s
                # and we have audio. Lower silence threshold = speech appears faster;
                # the coalesce window re-merges fragments split by short pauses.
                buf = call_audio_buffers[call_session_id].get(role, bytearray())
                last_ts = call_last_audio_time[call_session_id].get(role, now_ts)
                is_busy = call_stt_active_locks[call_session_id].get(role, False)

                if len(buf) >= 4000 and (now_ts - last_ts) >= 0.6 and not is_busy:
                    call_stt_active_locks[call_session_id][role] = True
                    raw_chunk = bytes(buf)
                    buf.clear()
                    hdr = call_webm_headers[call_session_id].get(role, b"")
                    full_payload = hdr + raw_chunk if not raw_chunk.startswith(b"\x1a\x45\xdf\xa3") else raw_chunk

                    asyncio.create_task(
                        process_stt_transcription(call_session_id, role, full_payload)
                    )
                continue
            except (WebSocketDisconnect, RuntimeError, Exception):
                break

            if message.get("bytes"):
                audio_bytes = message["bytes"]
                call_last_audio_time[call_session_id][role] = time.time()

                call_data = session_store.get_call(call_session_id)
                if call_data and call_data.get("status") == "ENDED":
                    break

                current_mode = call_data.get("call_mode", "LISTEN") if call_data else "LISTEN"

                peer_ws = session_store.get_peer_audio_socket(call_session_id, role)
                if peer_ws:
                    try:
                        await peer_ws.send_bytes(audio_bytes)
                    except Exception:
                        pass

                # Deepgram streaming mode: forward chunks directly (no batching / reconstruction)
                if dg_session:
                    try:
                        await dg_session.send_audio(audio_bytes)
                    except Exception as err:  # noqa: BLE001
                        print(f"[STT DEEPGRAM STREAM ⚠️] send failed: {err}")
                    continue

                # Store ONLY the true 256-byte EBML file header
                if role not in call_webm_headers[call_session_id] and len(audio_bytes) >= 256:
                    call_webm_headers[call_session_id][role] = audio_bytes[:256]

                buf = call_audio_buffers[call_session_id][role]
                buf.extend(audio_bytes)

                # Cap buffer size to max 120,000 bytes (prevent forceful chop of long sentences)
                if len(buf) > 120000:
                    hdr = call_webm_headers[call_session_id].get(role, b"")
                    call_audio_buffers[call_session_id][role] = bytearray(buf[-100000:])
                    buf = call_audio_buffers[call_session_id][role]

                # Max buffer flush: if buffer reaches 90,000 bytes (~10.0s), trigger STT as absolute limit
                is_busy = call_stt_active_locks[call_session_id].get(role, False)
                if len(buf) >= 90000 and not is_busy:
                    call_stt_active_locks[call_session_id][role] = True
                    raw_chunk = bytes(buf)
                    buf.clear()
                    hdr = call_webm_headers[call_session_id].get(role, b"")
                    full_payload = hdr + raw_chunk if not raw_chunk.startswith(b"\x1a\x45\xdf\xa3") else raw_chunk

                    asyncio.create_task(
                        process_stt_transcription(call_session_id, role, full_payload)
                    )

                continue

            elif message.get("text"):
                try:
                    data: dict[str, Any] = json.loads(message["text"])
                    msg_type = data.get("type")
                    if msg_type in ("call_end", "end_call"):
                        await handle_call_ended(call_session_id, role)
                        await websocket.close(code=1000, reason="Call ended")
                        break
                    elif msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass

    except (WebSocketDisconnect, RuntimeError, Exception):
        pass
    finally:
        session_store.remove_call_audio_socket(call_session_id, role)
        if dg_task:
            dg_task.cancel()
        if dg_session:
            await dg_session.close()
        if call_session_id in call_deepgram_sessions:
            call_deepgram_sessions.get(call_session_id, {}).pop(role, None)
            if not call_deepgram_sessions[call_session_id]:
                call_deepgram_sessions.pop(call_session_id, None)
        await handle_call_ended(call_session_id, role)


async def process_stt_transcription(call_session_id: str, speaker_role: str, audio_bytes: bytes) -> None:
    """Transcribe audio chunk via non-blocking STT with single-flight locking."""
    # Notify UI that STT processing is in-flight
    await broadcast_event(call_session_id, {
        "type": "stt_status",
        "speaker": "SCAMMER" if speaker_role == "SCAMMER" else "CUSTOMER",
        "status": "transcribing"
    })

    try:
        call_data = session_store.get_call(call_session_id)
        if not call_data or call_data.get("status") == "ENDED":
            return

        stt_engine = call_data.get("stt_engine", "dashscope") if call_data else "dashscope"
        text = await transcribe_audio_chunk(
            audio_bytes, filename="chunk.webm", language="en", stt_engine=stt_engine
        )

        # Check call status again after async STT request completes
        call_data = session_store.get_call(call_session_id)
        if not call_data or call_data.get("status") == "ENDED" or not text:
            return

        # Filter common Whisper silence hallucinations on background noise
        hallucinations = {
            "thank you.", "thank you", "okay.", "okay", "subtitles by",
            "amara.org", "you", "hi.", "hi", "so", "hello.", "hello?",
            "oh hello", "oh", "nice.", "yeah, man.", "to", ".", "..", "...", "it looks like",
            "i see you.", "or a", "$100.", "and", "all that.", "pfff.", "touch.", "what?",
            "schema", "amen", "schema.", "i'm sorry.", "i'm sorry", "i'm", "i'm.",
            "bye.", "bye", "i'm going to go.", "i'm going to go", "not sure.", "i'm not sure."
        }
        clean_text = text.lower().strip()
        if clean_text in hallucinations:
            return
        if len(clean_text) <= 3 and not any(c.isalnum() for c in clean_text):
            return

        speaker_tag = "SCAMMER" if speaker_role == "SCAMMER" else "CUSTOMER"
        # Coalesce same-speaker fragments into one spoken turn so long
        # sentences with natural pauses become one bubble / one AI reply.
        await queue_utterance_for_broadcast(call_session_id, speaker_tag, text)
    finally:
        # Always release lock for role
        if call_session_id in call_stt_active_locks:
            call_stt_active_locks[call_session_id][speaker_role] = False

        await broadcast_event(call_session_id, {
            "type": "stt_status",
            "speaker": "SCAMMER" if speaker_role == "SCAMMER" else "CUSTOMER",
            "status": "idle"
        })


@call_ws_router.websocket("/ws/call/{call_session_id}/events")
async def ws_call_events_stream(
    websocket: WebSocket, call_session_id: str
) -> None:
    """Real-time events stream handler pushing live highlight spans, transcriptions, and alerts."""
    api_key = websocket.query_params.get("api_key")
    expected_key = os.getenv("API_KEY", "transafe-hackathon-key-2026")

    if not api_key or api_key != expected_key:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    session_store.register_call_event_socket(call_session_id, websocket)

    try:
        now = datetime.now(UTC).isoformat()
        call_data = session_store.get_call(call_session_id) or {}
        caller_number = call_data.get("caller_number", "+60161234567")
        caller_name = call_data.get("caller_name", "Inspector Tan (PDRM Fake)")

        precheck = run_call_precheck(caller_number)

        # 1. Send pre_check_result event
        pre_check_event = {
            "type": "pre_check_result",
            "call_session_id": call_session_id,
            "caller_number": caller_number,
            "caller_name": caller_name,
            "blacklisted": bool(precheck["blacklisted"]),
            "blacklist_case_count": int(precheck["blacklist_cases"]),
            "spoofed_prefix": bool(precheck["spoofed_prefix"]),
            "initial_risk": str(precheck["initial_risk"]),
            "warning_text": precheck["warning"] or "No scam reports on file for caller ID.",
            "warning_text_ms": precheck["warning_ms"] or "Tiada laporan penipuan untuk nombor ini.",
            "timestamp": now,
        }
        await websocket.send_json(pre_check_event)

        # 1b. If the call was auto-engaged in AUTO_TALK mode (unknown caller + opt-in),
        # broadcast mode_change so the customer UI shows the agent-active badge.
        call_mode = str(call_data.get("call_mode", "LISTEN") or "LISTEN").upper()
        if call_mode == "AUTO_TALK":
            await broadcast_event(call_session_id, {
                "type": "mode_change",
                "call_session_id": call_session_id,
                "call_mode": "AUTO_TALK",
                "source": "auto_engage",
                "timestamp": datetime.now(UTC).isoformat(),
            })

        # 2. Non-blocking receive loop for real-time events and push alerts
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            except (WebSocketDisconnect, RuntimeError, Exception):
                break

            if isinstance(msg, dict):
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg.get("type") == "broadcast_transcript":
                    text = msg.get("text", "")
                    speaker = (msg.get("speaker") or "SCAMMER").upper()
                    await broadcast_text_and_highlights(call_session_id, speaker, text)

    except (WebSocketDisconnect, RuntimeError, Exception):
        pass
    finally:
        session_store.remove_call_event_socket(call_session_id, websocket)
