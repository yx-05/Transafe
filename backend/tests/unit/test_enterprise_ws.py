"""Unit tests for the Enterprise Console WebSocket (``/enterprise/ws/events``).

The endpoint is push-only: it streams ``ns_events`` and never expects a frame
from the client. The one thing it *must* read is the client leaving, and
getting that wrong is not cosmetic.

A browser tab that vanished stayed "connected" forever, because:

* Starlette only moves ``client_state`` to DISCONNECTED inside ``receive()``;
* the handler never called ``receive()``;
* asyncio's transport silently discards writes to a lost socket instead of
  raising, so the ``send`` guard and its ``except`` never fired.

So the loop never broke, ``finally`` never ran, and every reconnect leaked
another subscription that ``EventBroadcaster.publish`` fanned out to forever.
"""

import time
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from main import app
from src.enterprise.events import build_event, get_broadcaster

client = TestClient(app)

# ``backlog=0`` keeps these tests hermetic: no Supabase read on connect.
WS_URL = "/enterprise/ws/events?backlog=0"


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    """Poll ``predicate`` until it holds, returning whether it ever did.

    The app runs on the TestClient's own event loop, so the handler unwinds on
    another thread and needs a moment to be observed.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _receive_backlog(ws: Any) -> Any:
    """Read the connect-time backlog frame.

    Receiving it proves the handler has already subscribed: the endpoint calls
    ``subscribe()`` *before* its first ``send()``, so this frame is a
    happens-before marker and removes the race between connecting and
    publishing.
    """
    return ws.receive_json()


def test_ws_streams_a_published_event_to_a_connected_client() -> None:
    """The rewritten loop must still deliver events, not only detect exits."""
    bus = get_broadcaster()
    with client.websocket_connect(WS_URL) as ws:
        assert _receive_backlog(ws) == []

        event = build_event("discovery", "campaign_proposed", {"code": "SCAM-999"})
        assert bus.publish(event) >= 1, "no subscriber received the event"
        frame = ws.receive_json()

    assert frame["event_type"] == "campaign_proposed"
    assert frame["payload"] == {"code": "SCAM-999"}


def test_ws_releases_its_subscription_when_the_client_disconnects() -> None:
    """A departed client must not stay subscribed.

    This is the regression test for the leak. Before the drain task existed it
    failed permanently, not intermittently.
    """
    bus = get_broadcaster()
    before = bus.subscriber_count

    with client.websocket_connect(WS_URL) as ws:
        assert _receive_backlog(ws) == []
        assert bus.subscriber_count == before + 1

        # Close while the portal is still up, so the handler can react.
        ws.close()
        assert _wait_until(lambda: bus.subscriber_count == before), (
            "the handler kept its subscriber after the client disconnected"
        )

    assert bus.subscriber_count == before


def test_repeated_reconnects_do_not_accumulate_subscribers() -> None:
    """Console remounts must not leak a queue each time.

    The console remounts on every navigation and React StrictMode mounts
    twice, so a leak here compounds for the life of the process.
    """
    bus = get_broadcaster()
    before = bus.subscriber_count

    for _ in range(5):
        with client.websocket_connect(WS_URL) as ws:
            assert _receive_backlog(ws) == []
            ws.close()
            assert _wait_until(lambda: bus.subscriber_count == before), (
                "subscriber count grew across reconnects"
            )

    assert bus.subscriber_count == before


def test_ws_unsubscribes_when_the_backlog_read_fails() -> None:
    """A failure before the first send must still release the subscription."""
    bus = get_broadcaster()
    before = bus.subscriber_count

    with patch(
        "src.api.enterprise_ws.fetch_recent_events",
        new=AsyncMock(side_effect=RuntimeError("supabase unreachable")),
    ), client.websocket_connect("/enterprise/ws/events?backlog=5") as ws:
        ws.close()

    assert _wait_until(lambda: bus.subscriber_count == before), (
        "the subscriber outlived a failed backlog read"
    )
