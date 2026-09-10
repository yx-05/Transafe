"""WebSocket endpoint streaming ``ns_events`` to the Enterprise Console.

``/enterprise/ws/events``

On connect the client receives a small backlog (so a late-joining dashboard is
not blank), then a live stream. A heartbeat keeps intermediaries from dropping
idle connections. Slow clients drop events rather than back-pressuring the
emitter — see :class:`src.enterprise.events.EventBroadcaster`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.enterprise.events import fetch_recent_events, get_broadcaster

logger = logging.getLogger(__name__)

enterprise_ws_router = APIRouter()

HEARTBEAT_SECONDS = 25
DEFAULT_BACKLOG = 25


@enterprise_ws_router.websocket("/enterprise/ws/events")
async def enterprise_events_ws(
    websocket: WebSocket,
    backlog: int = Query(DEFAULT_BACKLOG, ge=0, le=200),
    layer: str | None = Query(None),
) -> None:
    """Stream ``ns_events`` to a connected Enterprise Console client.

    Args:
        websocket: The client connection.
        backlog: Number of historical events to replay on connect.
        layer: Optional layer filter applied to the live stream.
    """
    await websocket.accept()
    broadcaster = get_broadcaster()
    queue = broadcaster.subscribe()

    try:
        history: list[dict[str, Any]] = []
        if backlog:
            history = list(reversed(await fetch_recent_events(limit=backlog, layer=layer)))
            if not history:
                history = broadcaster.recent(backlog)
                if layer:
                    history = [e for e in history if e.get("layer") == layer]

        # Frame format is dictated by the console's runtime guard (isNsEvent in
        # frontend/enterprise/src/types/events.ts): each frame is either a bare
        # ns_event object or a bare JSON array of them. Do NOT reintroduce an
        # {"type": ..., "event": ...} envelope — the guard would reject every
        # frame and the UI would go silently blank with no error on either side.
        # The heartbeat is deliberately not an ns_event: it fails the guard and
        # is dropped by the client, which is the intended no-op.
        await websocket.send_json(history)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
                continue

            if layer and event.get("layer") != layer:
                continue
            await websocket.send_json(event)

    except WebSocketDisconnect:
        logger.debug("enterprise ws: client disconnected")
    except Exception:
        logger.exception("enterprise ws: stream error")
        with contextlib.suppress(Exception):
            await websocket.close()
    finally:
        broadcaster.unsubscribe(queue)
