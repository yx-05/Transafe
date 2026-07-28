"""In-memory session registry for managing active trigger pipelines and calls."""

from datetime import UTC, datetime
from typing import Any


class SessionStore:
    """Manages active WebSocket sessions, call session states, and recent user cases."""

    def __init__(self) -> None:
        self.active_sessions: dict[str, dict[str, Any]] = {}
        self.call_sessions: dict[str, dict[str, Any]] = {}
        self.recent_user_cases: dict[str, list[dict[str, Any]]] = {}

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

    def register_call(
        self, call_session_id: str, session_id: str, user_id: str, call_mode: str
    ) -> None:
        """Register an active call session."""
        self.call_sessions[call_session_id] = {
            "call_session_id": call_session_id,
            "session_id": session_id,
            "user_id": user_id,
            "call_mode": call_mode,
            "status": "ACTIVE",
            "created_at": datetime.now(UTC).isoformat(),
        }

    def get_call(self, call_session_id: str) -> dict[str, Any] | None:
        """Retrieve active call session by ID."""
        return self.call_sessions.get(call_session_id)

    def set_call_mode(self, call_session_id: str, new_mode: str) -> None:
        """Update call session mode (e.g. takeover to AUTO_TALK)."""
        if call_session_id in self.call_sessions:
            self.call_sessions[call_session_id]["call_mode"] = new_mode

    def get_recent_cases(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch recent cases for a given user."""
        return self.recent_user_cases.get(user_id, [])


session_store = SessionStore()
