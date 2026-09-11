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
from starlette.websockets import WebSocketState

from src.enterprise.events import fetch_recent_events, get_broadcaster

logger = logging.getLogger(__name__)

enterprise_ws_router = APIRouter()

HEARTBEAT_SECONDS = 25
DEFAULT_BACKLOG = 25


async def _release(task: asyncio.Task[Any]) -> None:
    """Cancel a pending task and wait for it to actually stop.

    Awaiting the cancellation matters: a bare ``cancel()`` leaves the task
    scheduled, so an in-flight ``queue.get()`` can still pull an event off the
    queue after we have moved on and drop it on the floor.
    """
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


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

    async def send(payload: Any) -> bool:
        """Send one frame, reporting whether the client is still there.

        This is a second line of defence, not the primary detection. It cannot
        be: asyncio's transport *silently discards* writes to a socket whose
        peer has gone — it bumps ``_conn_lost`` and returns without raising —
        so ``send_json`` reports success and this never returns False for a
        dead client. See :func:`drain_client` for what actually works.
        """
        if websocket.client_state is not WebSocketState.CONNECTED:
            return False
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001 - a dead socket is not an error
            return False
        return True

    async def drain_client() -> None:
        """Return as soon as the client goes away, for any reason.

        This endpoint is push-only, so nothing else here reads inbound frames —
        which is exactly why this task has to exist. Starlette only moves
        ``client_state`` to DISCONNECTED inside ``receive()``, and uvicorn only
        hands the ``websocket.disconnect`` message over there. With no reader:

        * the guard in ``send`` above could never trip, because asyncio
          swallows the write instead of raising;
        * the loop never broke, so the ``finally`` below never ran and every
          vanished client stayed subscribed for the life of the process.

        A leaked subscriber is not merely untidy. ``EventBroadcaster.publish``
        fans out to it on every event, and once its queue fills it logs a
        second warning per event — so a handful of dead sockets turn every
        later event into a burst of noise that buries the real error.
        """
        while True:
            try:
                message = await websocket.receive()
            except Exception:  # noqa: BLE001 - any receive failure means gone
                return
            if message.get("type") == "websocket.disconnect":
                return
            # Anything else is unsolicited. Ignoring it matches the previous
            # behaviour, where inbound frames were simply never read.

    # Started before the first send so a client that vanishes during the
    # backlog replay is noticed too.
    disconnect: asyncio.Task[None] = asyncio.create_task(drain_client())

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
        if not await send(history):
            return

        while True:
            # Race the next event against the client going away. ``wait`` does
            # not cancel the loser, so whichever task is left pending is
            # released explicitly.
            pending: asyncio.Task[dict[str, Any]] = asyncio.create_task(queue.get())
            done, _pending = await asyncio.wait(
                {pending, disconnect},
                timeout=HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if disconnect in done:
                await _release(pending)
                break

            if not done:
                # Idle for a whole window, so prove the socket is still there.
                await _release(pending)
                if not await send({"type": "heartbeat"}):
                    break
                continue

            event = pending.result()
            if layer and event.get("layer") != layer:
                continue
            if not await send(event):
                break

    except WebSocketDisconnect:
        logger.debug("enterprise ws: client disconnected")
    except Exception:
        logger.exception("enterprise ws: stream error")
        with contextlib.suppress(Exception):
            await websocket.close()
    finally:
        await _release(disconnect)
        # The subscription must not outlive the socket, or every publish keeps
        # filling a queue nobody will ever drain.
        broadcaster.unsubscribe(queue)
