"""Unit tests for the utterance-coalescing window in websocket_call.py.

The VAD/STT emits multiple "final" fragments for one spoken turn because of
natural mid-sentence pauses. queue_utterance_for_broadcast buffers same-speaker
fragments and emits ONE merged broadcast, so a long sentence becomes one chat
bubble and the AUTO_TALK agent replies to the complete message.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.api.websocket_call import call_utterance_coalesce, queue_utterance_for_broadcast


@pytest.fixture(autouse=True)
def _clean_coalesce_state():
    """Reset module-level coalesce state + cancel lingering waiter tasks."""
    for by_speaker in call_utterance_coalesce.values():
        for entry in by_speaker.values():
            task = entry.get("flush_task")
            if task and not task.done():
                task.cancel()
    call_utterance_coalesce.clear()
    yield
    for by_speaker in call_utterance_coalesce.values():
        for entry in by_speaker.values():
            task = entry.get("flush_task")
            if task and not task.done():
                task.cancel()
    call_utterance_coalesce.clear()


@pytest.mark.asyncio
@patch("src.api.websocket_call.UTTERANCE_COALESCE_WINDOW", 0.05)
@patch("src.api.websocket_call.broadcast_text_and_highlights", new_callable=AsyncMock)
async def test_coalesces_same_speaker_fragments_into_one_turn(mock_broadcast) -> None:
    """Two fragments arriving inside the quiet window become ONE merged utterance."""
    await queue_utterance_for_broadcast("call-1", "SCAMMER", "transfer the money")
    await asyncio.sleep(0.02)  # still within the window
    await queue_utterance_for_broadcast("call-1", "SCAMMER", "to my account now")
    await asyncio.sleep(0.1)  # let the window elapse

    mock_broadcast.assert_awaited_once_with(
        "call-1", "SCAMMER", "transfer the money to my account now"
    )


@pytest.mark.asyncio
@patch("src.api.websocket_call.UTTERANCE_COALESCE_WINDOW", 0.05)
@patch("src.api.websocket_call.broadcast_text_and_highlights", new_callable=AsyncMock)
async def test_fragments_across_window_become_two_turns(mock_broadcast) -> None:
    """Fragments separated by a real pause (> window) are separate turns."""
    await queue_utterance_for_broadcast("call-1", "SCAMMER", "first sentence")
    await asyncio.sleep(0.08)  # window elapsed -> first turn flushed
    await queue_utterance_for_broadcast("call-1", "SCAMMER", "second sentence")
    await asyncio.sleep(0.08)

    assert mock_broadcast.await_count == 2
    calls = [c.args for c in mock_broadcast.await_args_list]
    assert ("call-1", "SCAMMER", "first sentence") in calls
    assert ("call-1", "SCAMMER", "second sentence") in calls


@pytest.mark.asyncio
@patch("src.api.websocket_call.UTTERANCE_COALESCE_WINDOW", 10.0)
@patch("src.api.websocket_call.UTTERANCE_COALESCE_MAX_FRAGMENTS", 3)
@patch("src.api.websocket_call.broadcast_text_and_highlights", new_callable=AsyncMock)
async def test_hard_fragment_cap_flushes_immediately(mock_broadcast) -> None:
    """A turn that grows past the fragment cap flushes without waiting the window."""
    for i in range(3):
        await queue_utterance_for_broadcast("call-1", "SCAMMER", f"frag {i}")

    mock_broadcast.assert_awaited_once_with("call-1", "SCAMMER", "frag 0 frag 1 frag 2")


@pytest.mark.asyncio
@patch("src.api.websocket_call.UTTERANCE_COALESCE_WINDOW", 0.05)
@patch("src.api.websocket_call.broadcast_text_and_highlights", new_callable=AsyncMock)
async def test_different_speakers_do_not_merge(mock_broadcast) -> None:
    """SCAMMER and CUSTOMER fragments are buffered independently."""
    await queue_utterance_for_broadcast("call-1", "SCAMMER", "hello")
    await queue_utterance_for_broadcast("call-1", "CUSTOMER", "hi there")
    await asyncio.sleep(0.08)

    assert mock_broadcast.await_count == 2


@pytest.mark.asyncio
@patch("src.api.websocket_call.UTTERANCE_COALESCE_WINDOW", 10.0)
@patch("src.api.websocket_call.broadcast_text_and_highlights", new_callable=AsyncMock)
async def test_flush_all_coalesced_preserves_pending_fragments(mock_broadcast) -> None:
    """Call-end flush emits any pending fragments so nothing is lost to deep analysis."""
    from src.api.websocket_call import _flush_all_coalesced

    await queue_utterance_for_broadcast("call-1", "SCAMMER", "final")
    await queue_utterance_for_broadcast("call-1", "SCAMMER", "words")
    await _flush_all_coalesced("call-1")

    mock_broadcast.assert_awaited_once_with("call-1", "SCAMMER", "final words")
    assert "call-1" not in call_utterance_coalesce


@pytest.mark.asyncio
@patch("src.api.websocket_call.UTTERANCE_COALESCE_WINDOW", 0.05)
@patch("src.api.websocket_call.broadcast_text_and_highlights", new_callable=AsyncMock)
async def test_short_text_is_ignored(mock_broadcast) -> None:
    """Sub-2-char fragments (STT noise) never enter the coalesce buffer."""
    await queue_utterance_for_broadcast("call-1", "SCAMMER", ".")
    await asyncio.sleep(0.08)

    mock_broadcast.assert_not_awaited()
    assert "call-1" not in call_utterance_coalesce
