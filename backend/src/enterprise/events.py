"""ns_events emitter — the nervous system of the Enterprise Console.

Every v2 layer writes here; the WebSocket at ``/enterprise/ws/events`` streams
it; the dashboard animations are driven by it; REPLAY mode replays it.
One table, one event schema, one source of truth.

Design rules
------------
* ``emit_event`` never raises. A telemetry failure must never break a caller.
* Persistence runs in a worker thread (the Supabase client is sync/blocking),
  so emitting adds no measurable latency to the async caller.
* Broadcast is in-process and non-blocking: slow WebSocket clients drop
  events rather than back-pressuring the emitter.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from src.db.vector_store import get_supabase_client

logger = logging.getLogger(__name__)

# ── Vocabulary (kept permissive: unknown values are logged, not rejected) ────
VALID_LAYERS: frozenset[str] = frozenset(
    {
        "sensing",
        "case",
        "discovery",
        "compiler",
        "registry",
        "propagation",
        "exposure",
    }
)

VALID_SEVERITIES: frozenset[str] = frozenset({"info", "warning", "critical"})

# Max events retained in memory for late-joining WebSocket clients.
REPLAY_BUFFER_SIZE = 200
# Per-subscriber queue depth. A client that falls this far behind drops events.
SUBSCRIBER_QUEUE_SIZE = 100

# Fallback ids for events that could not be persisted (migration not applied,
# Supabase down, or a sync emit whose write is still in flight).
#
# The console's runtime guard requires `typeof id === "number"` and SILENTLY
# DROPS any frame without it. An unpersisted event that still broadcasts but
# carries no id is therefore invisible in the UI with no error anywhere — so
# every broadcast event is guaranteed an id here. The base is far above any
# realistic bigserial value so fallback ids sort as newest (matching arrival
# order) and can never collide with a real row id.
_FALLBACK_ID_BASE = 1 << 40
_fallback_ids = itertools.count(_FALLBACK_ID_BASE)


class EventBroadcaster:
    """In-process publish/subscribe fan-out for ``ns_events``.

    One instance per process. WebSocket handlers call :meth:`subscribe` to get
    a queue, and :meth:`unsubscribe` on disconnect.
    """

    def __init__(self, buffer_size: int = REPLAY_BUFFER_SIZE) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._recent: deque[dict[str, Any]] = deque(maxlen=buffer_size)

    @property
    def subscriber_count(self) -> int:
        """Number of currently attached subscribers."""
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber and return its event queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Detach a subscriber. Safe to call twice."""
        self._subscribers.discard(queue)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return up to ``limit`` most recent in-memory events (oldest first)."""
        if limit <= 0:
            return []
        events = list(self._recent)
        return events[-limit:]

    def publish(self, event: dict[str, Any]) -> int:
        """Fan an event out to all subscribers without blocking.

        Args:
            event: Serialised event dict.

        Returns:
            Number of subscribers the event was delivered to.
        """
        self._recent.append(event)
        delivered = 0
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                logger.warning("ns_events subscriber queue full — dropping event for one client")
            except Exception:  # pragma: no cover - defensive
                logger.exception("ns_events publish failed for a subscriber")
        return delivered


_broadcaster = EventBroadcaster()


def get_broadcaster() -> EventBroadcaster:
    """Return the process-wide event broadcaster."""
    return _broadcaster


def build_event(
    layer: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a validated ``ns_events`` row (not yet persisted).

    Args:
        layer: Nervous-system layer emitting the event.
        event_type: Machine-readable event name, e.g. ``campaign_proposed``.
        payload: JSON-serialisable event body.
        severity: ``info`` | ``warning`` | ``critical``.
        run_id: Optional demo-scenario run UUID grouping the event.

    Returns:
        Event dict with keys ``ts``, ``layer``, ``event_type``, ``severity``,
        ``payload``, ``run_id``.
    """
    if layer not in VALID_LAYERS:
        logger.warning("ns_events: unknown layer %r", layer)
    if severity not in VALID_SEVERITIES:
        logger.warning("ns_events: unknown severity %r — coercing to 'info'", severity)
        severity = "info"

    return {
        "ts": datetime.now(UTC).isoformat(),
        "layer": layer,
        "event_type": event_type,
        "severity": severity,
        "payload": payload or {},
        "run_id": run_id,
    }


def _persist(event: dict[str, Any]) -> dict[str, Any] | None:
    """Insert an event row into ``ns_events``. Returns the stored row or None.

    Any ``id`` on the incoming dict is stripped: it is either a fallback id or a
    replayed row id, and must never be written over the bigserial column.
    """
    try:
        client = get_supabase_client()
        row = {k: v for k, v in event.items() if k != "id"}
        result = client.table("ns_events").insert(row).execute()
        data = getattr(result, "data", None)
        if data:
            return dict(data[0])
        return None
    except Exception:
        logger.exception("ns_events: failed to persist %s/%s", event["layer"], event["event_type"])
        return None


async def emit_event(
    layer: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Emit an ``ns_event``: persist to Postgres and broadcast to WebSockets.

    Never raises — a telemetry failure must not break the caller. If the
    database write fails, the event is still broadcast so the live dashboard
    stays truthful about what happened.

    Args:
        layer: sensing | case | discovery | compiler | registry | propagation | exposure.
        event_type: e.g. ``case_ingested``, ``entity_linked``, ``campaign_proposed``.
        payload: JSON-serialisable event body.
        severity: ``info`` | ``warning`` | ``critical``.
        run_id: Optional demo-scenario run UUID.

    Returns:
        The emitted event dict (including ``id``/``ts`` from the DB when available).
    """
    event = build_event(layer, event_type, payload, severity, run_id)

    stored: dict[str, Any] | None = None
    try:
        stored = await asyncio.to_thread(_persist, event)
    except Exception:  # pragma: no cover - defensive
        logger.exception("ns_events: persistence thread failed")

    if stored:
        event = {**event, **stored}
    else:
        event["id"] = next(_fallback_ids)

    _broadcaster.publish(event)
    return event


def emit_event_sync(
    layer: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Synchronous emit for non-async callers (LangGraph nodes, scripts).

    If an event loop is running, persistence is scheduled on it; otherwise the
    write happens inline. Broadcast always happens immediately.
    """
    event = build_event(layer, event_type, payload, severity, run_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # Fire-and-forget: the row id is not available in time to broadcast, so
        # this event always goes out with a fallback id. Pass a copy so the
        # fallback id assigned below can never reach the INSERT.
        loop.create_task(asyncio.to_thread(_persist, dict(event)))
        event["id"] = next(_fallback_ids)
    else:
        stored = _persist(event)
        if stored:
            event = {**event, **stored}
        else:
            event["id"] = next(_fallback_ids)

    _broadcaster.publish(event)
    return event


async def fetch_recent_events(
    limit: int = 100,
    layer: str | None = None,
    run_id: str | None = None,
    since_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch persisted ``ns_events`` (newest first), for REPLAY and page load.

    Args:
        limit: Maximum rows to return.
        layer: Optional layer filter.
        run_id: Optional demo-run filter.
        since_id: Only return events with ``id`` greater than this.

    Returns:
        List of event rows; empty list on any failure.
    """

    def _query() -> list[dict[str, Any]]:
        client = get_supabase_client()
        query = client.table("ns_events").select("*")
        if layer:
            query = query.eq("layer", layer)
        if run_id:
            query = query.eq("run_id", run_id)
        if since_id is not None:
            query = query.gt("id", since_id)
        result = query.order("id", desc=True).limit(limit).execute()
        return list(getattr(result, "data", None) or [])

    try:
        return await asyncio.to_thread(_query)
    except Exception:
        logger.exception("ns_events: fetch_recent_events failed")
        return []
