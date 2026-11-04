"""Unit tests for src.enterprise.events."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.enterprise.events import (
    EventBroadcaster,
    build_event,
    emit_event,
    fetch_recent_events,
    get_broadcaster,
)


def test_build_event_shape():
    event = build_event("discovery", "campaign_proposed", {"code": "SCAM-001"}, "critical")
    assert event["layer"] == "discovery"
    assert event["event_type"] == "campaign_proposed"
    assert event["severity"] == "critical"
    assert event["payload"] == {"code": "SCAM-001"}
    assert event["run_id"] is None
    assert "ts" in event


def test_build_event_coerces_invalid_severity():
    event = build_event("discovery", "x", severity="apocalyptic")
    assert event["severity"] == "info"


def test_build_event_defaults_empty_payload():
    event = build_event("sensing", "case_ingested")
    assert event["payload"] == {}


def test_broadcaster_subscribe_and_publish():
    bus = EventBroadcaster()
    queue = bus.subscribe()
    delivered = bus.publish({"event_type": "x"})
    assert delivered == 1
    assert queue.get_nowait() == {"event_type": "x"}


def test_broadcaster_unsubscribe_stops_delivery():
    bus = EventBroadcaster()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    assert bus.publish({"event_type": "x"}) == 0
    assert bus.subscriber_count == 0


def test_broadcaster_recent_buffer_bounded():
    bus = EventBroadcaster(buffer_size=3)
    for i in range(5):
        bus.publish({"n": i})
    recent = bus.recent(10)
    assert [e["n"] for e in recent] == [2, 3, 4]


def test_broadcaster_full_queue_drops_event():
    bus = EventBroadcaster()
    queue = bus.subscribe()
    for _ in range(queue.maxsize):
        queue.put_nowait({"filler": True})
    assert bus.publish({"event_type": "overflow"}) == 0


def test_get_broadcaster_is_singleton():
    assert get_broadcaster() is get_broadcaster()


@patch("src.enterprise.events.get_supabase_client")
async def test_emit_event_persists_and_broadcasts(mock_client):
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value.data = [{"id": 42}]
    mock_client.return_value.table.return_value = mock_table

    queue = get_broadcaster().subscribe()
    try:
        event = await emit_event("discovery", "cases_linked", {"score": 0.9})
    finally:
        get_broadcaster().unsubscribe(queue)

    assert event["id"] == 42
    assert mock_table.insert.called
    assert queue.get_nowait()["event_type"] == "cases_linked"


@patch("src.enterprise.events.get_supabase_client")
async def test_emit_event_never_raises_on_db_failure(mock_client):
    mock_client.side_effect = RuntimeError("supabase down")
    event = await emit_event("discovery", "cases_linked")
    assert event["event_type"] == "cases_linked"
    # A fallback id is mandatory: the console drops any event without a numeric
    # id, so an unpersisted event would otherwise vanish silently in the UI.
    assert isinstance(event["id"], int)


@patch("src.enterprise.events.get_supabase_client")
async def test_emit_event_fallback_ids_are_unique_and_sort_newest(mock_client):
    mock_client.side_effect = RuntimeError("supabase down")
    first = await emit_event("discovery", "a")
    second = await emit_event("discovery", "b")
    assert second["id"] > first["id"] > 2**39


@patch("src.enterprise.events.get_supabase_client")
async def test_emit_event_never_writes_id_column(mock_client):
    """A fallback/replay id must never be INSERTed over the bigserial column."""
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value.data = [{"id": 7}]
    mock_client.return_value.table.return_value = mock_table

    await emit_event("discovery", "cases_linked")

    inserted = mock_table.insert.call_args[0][0]
    assert "id" not in inserted


@patch("src.enterprise.events.get_supabase_client")
async def test_fetch_recent_events_returns_rows(mock_client):
    mock_query = MagicMock()
    mock_query.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1, "layer": "discovery"}
    ]
    mock_client.return_value.table.return_value.select.return_value = mock_query

    events = await fetch_recent_events(limit=10)
    assert events == [{"id": 1, "layer": "discovery"}]


@patch("src.enterprise.events.get_supabase_client")
async def test_fetch_recent_events_returns_empty_on_failure(mock_client):
    mock_client.side_effect = RuntimeError("boom")
    assert await fetch_recent_events() == []


@patch("src.enterprise.events.get_supabase_client")
async def test_emit_event_adds_no_meaningful_latency(mock_client):
    mock_client.return_value.table.return_value.insert.return_value.execute.return_value.data = []
    start = asyncio.get_running_loop().time()
    await emit_event("sensing", "case_ingested")
    assert asyncio.get_running_loop().time() - start < 1.0


@pytest.mark.parametrize("layer", ["sensing", "case", "discovery", "compiler", "registry"])
def test_build_event_accepts_all_layers(layer):
    assert build_event(layer, "x")["layer"] == layer
