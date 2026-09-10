"""In-memory session registry for managing active trigger pipelines and calls."""

from datetime import UTC, datetime
from typing import Any


class SessionStore:
    """Manages active WebSocket sessions, call session states, and recent user cases."""

    def __init__(self) -> None:
        self.active_sessions: dict[str, dict[str, Any]] = {}
        self.call_sessions: dict[str, dict[str, Any]] = {}
        self.recent_user_cases: dict[str, list[dict[str, Any]]] = {}
        self.session_telemetry_events: dict[str, list[dict[str, Any]]] = {}
        self.call_audio_sockets: dict[str, dict[str, Any]] = {}  # call_session_id -> {"SCAMMER": ws, "CUSTOMER": ws}
        self.call_event_sockets: dict[str, list[Any]] = {}  # call_session_id -> list of event ws
        self.user_incoming_calls: dict[str, list[str]] = {}  # user_id -> list of call_session_id
        self.call_tts_audio: dict[str, dict[str, bytes]] = {}  # call_session_id -> {tts_id: mp3 bytes}

    def register_session(
        self, session_id: str, trigger_type: str, user_id: str, payload: dict[str, Any]
    ) -> None:
        """Register a new trigger pipeline session."""
        now = datetime.now(UTC).isoformat()
        session_data = {
            "session_id": session_id,
            "trigger_type": trigger_type,
            "user_id": user_id,
            "payload": payload,
            "status": "pending",
            "created_at": now,
        }
        self.active_sessions[session_id] = session_data

        # Add to recent user cases
        if user_id not in self.recent_user_cases:
            self.recent_user_cases[user_id] = []

        case_item = {
            "case_id": f"case-{session_id[:8]}",
            "session_id": session_id,
            "trigger_type": trigger_type,
            "risk_tier": "HIGH",
            "created_at": now,
        }
        if trigger_type == "CALL" and "call" in payload:
            case_item["caller_number"] = payload["call"].get("caller_number")

        self.recent_user_cases[user_id].insert(0, case_item)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve active trigger session by ID."""
        return self.active_sessions.get(session_id)

    def add_telemetry_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Buffer live telemetry event into session store memory."""
        if session_id not in self.session_telemetry_events:
            self.session_telemetry_events[session_id] = []
        self.session_telemetry_events[session_id].append(event)

    def get_telemetry_events(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve buffered live telemetry events for session."""
        return self.session_telemetry_events.get(session_id, [])

    def register_call(
        self,
        call_session_id: str,
        session_id: str,
        user_id: str,
        call_mode: str,
        caller_number: str = "+60161234567",
        caller_name: str = "Inspector Tan (PDRM Fake)",
        initiated_by: str = "SCAMMER",
    ) -> None:
        """Register an active call session, marking any previous call for user as ENDED."""
        # End any previous un-ended calls for this user
        existing_cids = self.user_incoming_calls.get(user_id, [])
        for cid in existing_cids:
            if cid in self.call_sessions:
                self.call_sessions[cid]["status"] = "ENDED"

        call_data = {
            "call_session_id": call_session_id,
            "session_id": session_id,
            "user_id": user_id,
            "caller_number": caller_number,
            "caller_name": caller_name,
            "initiated_by": initiated_by,
            "call_mode": call_mode,
            "stt_engine": "dashscope",
            "status": "RINGING",
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.call_sessions[call_session_id] = call_data

        if user_id not in self.user_incoming_calls:
            self.user_incoming_calls[user_id] = []
        self.user_incoming_calls[user_id].insert(0, call_session_id)

    def get_call(self, call_session_id: str) -> dict[str, Any] | None:
        """Retrieve active call session by ID."""
        return self.call_sessions.get(call_session_id)

    def get_active_call_for_user(self, user_id: str) -> dict[str, Any] | None:
        """Fetch current active ringing call session for user (auto-expires after 60s)."""
        call_ids = self.user_incoming_calls.get(user_id, [])
        for cid in list(call_ids):
            call = self.call_sessions.get(cid)
            if call and call.get("status") == "RINGING":
                try:
                    created_at = datetime.fromisoformat(call.get("created_at", ""))
                    age = (datetime.now(UTC) - created_at).total_seconds()
                    if age > 60:
                        call["status"] = "EXPIRED"
                        continue
                except Exception:
                    pass
                return call
        return None

    def set_call_mode(self, call_session_id: str, new_mode: str) -> None:
        """Update call session mode (e.g. takeover to AUTO_TALK)."""
        if call_session_id in self.call_sessions:
            self.call_sessions[call_session_id]["call_mode"] = new_mode

    def set_call_status(self, call_session_id: str, status: str) -> None:
        """Update call session status (RINGING, ANSWERED, DECLINED, ENDED)."""
        if call_session_id in self.call_sessions:
            self.call_sessions[call_session_id]["status"] = status

    def register_call_audio_socket(
        self, call_session_id: str, role: str, socket: Any
    ) -> None:
        """Register audio WebSocket handle for a role (SCAMMER or CUSTOMER)."""
        if call_session_id not in self.call_audio_sockets:
            self.call_audio_sockets[call_session_id] = {}
        self.call_audio_sockets[call_session_id][role.upper()] = socket

    def remove_call_audio_socket(self, call_session_id: str, role: str) -> None:
        """Remove audio WebSocket handle."""
        if call_session_id in self.call_audio_sockets:
            self.call_audio_sockets[call_session_id].pop(role.upper(), None)

    def get_peer_audio_socket(self, call_session_id: str, role: str) -> Any | None:
        """Get the peer's audio WebSocket handle."""
        sockets = self.call_audio_sockets.get(call_session_id, {})
        peer_role = "CUSTOMER" if role.upper() == "SCAMMER" else "SCAMMER"
        return sockets.get(peer_role)

    def register_call_event_socket(
        self, call_session_id: str, socket: Any
    ) -> None:
        """Register event WebSocket handle."""
        if call_session_id not in self.call_event_sockets:
            self.call_event_sockets[call_session_id] = []
        self.call_event_sockets[call_session_id].append(socket)

    def remove_call_event_socket(self, call_session_id: str, socket: Any) -> None:
        """Remove event WebSocket handle."""
        if call_session_id in self.call_event_sockets:
            try:
                self.call_event_sockets[call_session_id].remove(socket)
            except ValueError:
                pass

    def get_call_event_sockets(self, call_session_id: str) -> list[Any]:
        """Get all event WebSocket handles for session."""
        return self.call_event_sockets.get(call_session_id, [])

    def put_tts_audio(self, call_session_id: str, tts_id: str, audio_bytes: bytes) -> None:
        """Store a generated AUTO_TALK agent speech MP3 for the frontends to fetch."""
        self.call_tts_audio.setdefault(call_session_id, {})[tts_id] = audio_bytes

    def get_tts_audio(self, call_session_id: str, tts_id: str) -> bytes | None:
        """Retrieve a stored AUTO_TALK agent speech MP3 by tts_id."""
        return (self.call_tts_audio.get(call_session_id) or {}).get(tts_id)

    def clear_tts_audio(self, call_session_id: str) -> None:
        """Drop all stored AUTO_TALK speech MP3s for a call."""
        self.call_tts_audio.pop(call_session_id, None)

    def get_recent_cases(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch recent cases for a given user."""
        return self.recent_user_cases.get(user_id, [])


session_store = SessionStore()
