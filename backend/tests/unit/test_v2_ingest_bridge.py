"""Unit tests for the v1 → v2 ingest bridge (src.enterprise.ingest).

The v2 discovery layer is only real if something actually feeds it. These tests
pin the two halves of that: v1's call teardown hands the finished case over, and
the handover is genuinely fire-and-forget — it awaits nothing, raises nothing,
and cannot take a call down with it.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.enterprise.ingest import (
    _INFLIGHT,
    load_case_transcript,
    notify_case_completed,
    run_ingest_pipeline,
)


# ---------------------------------------------------------------------------
# v1 actually calls v2
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_call_teardown_hands_the_case_to_v2() -> None:
    """Ending a call must hand the persisted case id to the v2 ingest bridge.

    Without this the whole discovery layer never fires from real traffic: the
    ingest endpoint exists but nothing in the product calls it.
    """
    from src.api.websocket_call import _finalize_ended_call

    with (
        patch(
            "src.api.websocket_call._run_deep_transcript_analysis",
            new=AsyncMock(return_value=None),
        ),
        patch("src.api.websocket_call._flush_all_coalesced", new=AsyncMock(return_value=None)),
        patch(
            "src.api.websocket_call._persist_call_case",
            new=AsyncMock(return_value="case-abc"),
        ),
        patch("src.api.websocket_call.session_store", MagicMock()),
        patch("src.api.websocket_call.notify_case_completed") as mock_notify,
    ):
        await _finalize_ended_call("call-teardown-1")

    mock_notify.assert_called_once_with("case-abc")


@pytest.mark.asyncio
async def test_call_teardown_does_not_ingest_when_no_case_was_persisted() -> None:
    """A call with nothing persisted (no transcript / no user) hands over ``None``.

    ``notify_case_completed`` treats that as a no-op, so v2 never invents a
    case id v1 did not write.
    """
    from src.api.websocket_call import _finalize_ended_call

    with (
        patch(
            "src.api.websocket_call._run_deep_transcript_analysis",
            new=AsyncMock(return_value=None),
        ),
        patch("src.api.websocket_call._flush_all_coalesced", new=AsyncMock(return_value=None)),
        patch("src.api.websocket_call._persist_call_case", new=AsyncMock(return_value=None)),
        patch("src.api.websocket_call.session_store", MagicMock()),
        patch("src.api.websocket_call.notify_case_completed") as mock_notify,
    ):
        await _finalize_ended_call("call-teardown-2")

    mock_notify.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# The handover is fire-and-forget
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notify_returns_before_the_pipeline_runs() -> None:
    """The caller must not pay for the pipeline: it returns with work pending."""
    started = asyncio.Event()

    async def _slow(case_id: str) -> None:
        started.set()
        await asyncio.sleep(0.05)

    with patch("src.enterprise.ingest.run_ingest_pipeline", new=_slow):
        task = notify_case_completed("case-1")
        assert task is not None
        # Nothing has run yet — control never left the caller.
        assert not started.is_set()
        assert not task.done()
        await task

    assert task.done()


@pytest.mark.asyncio
async def test_notify_holds_a_strong_reference_until_the_task_finishes() -> None:
    """An in-flight ingest must be referenced, or the GC can drop it mid-await.

    ``asyncio`` keeps only a weak reference to a running task, so a detached
    ``create_task`` whose return value is discarded can silently vanish.
    """

    async def _noop(case_id: str) -> None:
        await asyncio.sleep(0)

    with patch("src.enterprise.ingest.run_ingest_pipeline", new=_noop):
        task = notify_case_completed("case-1")
        assert task in _INFLIGHT
        await task

    await asyncio.sleep(0)
    assert task not in _INFLIGHT


def test_notify_without_an_event_loop_is_a_silent_no_op() -> None:
    """Called from sync context there is nothing to schedule onto — never raise."""
    assert notify_case_completed("case-1") is None


@pytest.mark.asyncio
async def test_notify_ignores_a_missing_case_id() -> None:
    """A falsy case id schedules nothing rather than ingesting the string 'None'."""
    assert notify_case_completed(None) is None
    assert notify_case_completed("") is None


@pytest.mark.asyncio
async def test_pipeline_swallows_a_failure_in_every_stage() -> None:
    """A v2 blow-up must die inside the task, never surface to v1."""
    with (
        patch("src.enterprise.ingest.emit_event", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        await run_ingest_pipeline("case-1")  # must not raise


@pytest.mark.asyncio
async def test_teardown_frees_v1_audio_state_even_if_the_v2_handoff_raises() -> None:
    """v1's cleanup must not depend on v2 behaving.

    ``notify_case_completed`` raises nothing today, but that is the callee's
    discipline rather than this function's structure. If a future edit lets one
    escape, the pops below it stop running and every ended call leaks its audio
    buffer inside the live v1 service — a v2 change breaking v1.
    """
    from src.api import websocket_call as wc

    call_id = "call-leak-1"
    wc.call_audio_buffers[call_id] = [b"pcm"]
    wc.call_webm_headers[call_id] = b"hdr"
    wc.call_stt_active_locks[call_id] = True
    wc.call_phone_states[call_id] = {"transcript": []}

    with (
        patch(
            "src.api.websocket_call._run_deep_transcript_analysis",
            new=AsyncMock(return_value=None),
        ),
        patch("src.api.websocket_call._flush_all_coalesced", new=AsyncMock(return_value=None)),
        patch("src.api.websocket_call._persist_call_case", new=AsyncMock(return_value="case-x")),
        patch("src.api.websocket_call.session_store", MagicMock()),
        patch(
            "src.api.websocket_call.notify_case_completed",
            side_effect=RuntimeError("v2 import blew up"),
        ),
    ):
        await wc._finalize_ended_call(call_id)  # must not raise

    assert call_id not in wc.call_audio_buffers
    assert call_id not in wc.call_webm_headers
    assert call_id not in wc.call_stt_active_locks
    assert call_id not in wc.call_phone_states


# ---------------------------------------------------------------------------
# case_ingested must not claim work that did not happen
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_case_ingested_marks_a_transcriptless_case_as_skipped() -> None:
    """A case with no transcript gets no MO, no entities and no discovery.

    The event still fires — it is the console's refetch trigger for the case
    list, the overview counters and the graph, and the case row genuinely does
    exist. What must not happen is it arriving indistinguishable from a fully
    processed case, which is what a bare ``{"case_id": ...}`` emitted before
    the early return looked like.
    """
    emit = AsyncMock()
    with (
        patch("src.enterprise.ingest.emit_event", new=emit),
        patch("src.enterprise.ingest.load_case_transcript", return_value=[]),
    ):
        await run_ingest_pipeline("case-empty")

    emit.assert_awaited_once()
    payload = emit.await_args.kwargs["payload"]
    assert payload["case_id"] == "case-empty"
    assert payload["skipped"] is True
    assert payload["skipped_reason"] == "no_transcript"
    assert payload["utterances"] == 0


@pytest.mark.asyncio
async def test_case_ingested_is_not_flagged_skipped_when_the_pipeline_proceeds() -> None:
    """The happy path must be positively distinguishable, not merely un-flagged."""
    emit = AsyncMock()
    transcript = [
        {"speaker": "CALLER", "utterance": "one", "seq_idx": 0},
        {"speaker": "USER", "utterance": "two", "seq_idx": 1},
    ]
    engine = MagicMock()
    engine.on_case_ingested = AsyncMock()

    with (
        patch("src.enterprise.ingest.emit_event", new=emit),
        patch("src.enterprise.ingest.load_case_transcript", return_value=transcript),
        patch("src.enterprise.mo_extractor.run_mo_extraction", return_value=None),
        patch("src.enterprise.discovery.get_discovery_engine", return_value=engine),
    ):
        await run_ingest_pipeline("case-full")

    first = emit.await_args_list[0].kwargs
    assert first["event_type"] == "case_ingested"
    assert first["payload"]["skipped"] is False
    assert first["payload"]["utterances"] == 2
    assert "skipped_reason" not in first["payload"]
    engine.on_case_ingested.assert_awaited_once_with("case-full")


@pytest.mark.asyncio
async def test_case_ingested_is_announced_only_after_the_transcript_is_known() -> None:
    """Ordering is the fix: the claim cannot be made before the fact is checked.

    Emitting first and checking second is what allowed the skipped case to be
    announced as ingested, so the read has to precede the announcement.
    """
    order: list[str] = []

    async def _emit(**_kwargs: object) -> None:
        order.append("emit")

    def _load(_case_id: str) -> list[dict[str, object]]:
        order.append("load")
        return []

    with (
        patch("src.enterprise.ingest.emit_event", new=_emit),
        patch("src.enterprise.ingest.load_case_transcript", new=_load),
    ):
        await run_ingest_pipeline("case-order")

    assert order == ["load", "emit"]


# ---------------------------------------------------------------------------
# Transcript ordering — MO citations are list positions
# ---------------------------------------------------------------------------
def _transcript_client(rows: list[dict[str, object]]) -> tuple[MagicMock, MagicMock]:
    """Supabase mock whose call_transcripts SELECT yields ``rows``."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.execute.return_value.data = rows
    client = MagicMock()
    client.table.return_value = chain
    return client, chain


def test_load_case_transcript_orders_deterministically() -> None:
    """``created_at`` alone is not a total order — ``id`` must break the tie.

    Utterance positions in this list are what MO extraction cites, so two reads
    of the same case have to produce the same order.
    """
    client, chain = _transcript_client([])
    with patch("src.enterprise.ingest.get_supabase_client", return_value=client):
        load_case_transcript("case-1")

    ordered_by = [c.args[0] for c in chain.order.call_args_list]
    assert ordered_by == ["created_at", "id"]


def test_load_case_transcript_seq_idx_is_the_list_position() -> None:
    """``seq_idx`` is positional; a value on the row must never override it.

    ``call_transcripts`` has no sequence column, so reading one back would
    silently disagree with the indices the extractor cites.
    """
    client, _ = _transcript_client(
        [
            {"speaker": "CALLER", "utterance": "one", "seq_idx": 99},
            {"speaker": "USER", "utterance": "two", "seq_idx": 7},
        ]
    )
    with patch("src.enterprise.ingest.get_supabase_client", return_value=client):
        transcript = load_case_transcript("case-1")

    assert [u["seq_idx"] for u in transcript] == [0, 1]


def test_load_case_transcript_survives_a_dead_database() -> None:
    """A read failure yields an empty transcript, not an exception in the task."""
    with patch(
        "src.enterprise.ingest.get_supabase_client", side_effect=RuntimeError("down")
    ):
        assert load_case_transcript("case-1") == []
