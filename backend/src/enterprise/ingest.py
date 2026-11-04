"""v1 → v2 ingest bridge — the single seam between the live pipeline and L1-L3.

The v2 enterprise layer is *additive*: v1's fraud pipeline is never modified,
never slowed, and never made able to fail because of v2. This module is the one
place the two touch.

:func:`notify_case_completed` is what v1 calls once it has finished persisting a
fraud case. It returns immediately: the pipeline (MO extraction → entity
resolution → discovery) runs as a background task and swallows everything it
can. If there is no running event loop, or scheduling itself fails, the call is
a logged no-op — a broken analytics layer must never take a phone call down
with it.

Lives in ``src/enterprise`` rather than ``src/api/enterprise`` on purpose: v1
must be able to hand a case over without importing the v2 HTTP layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.db.vector_store import get_supabase_client
from src.enterprise.events import emit_event

logger = logging.getLogger(__name__)

#: Strong references to in-flight ingest tasks.
#:
#: The event loop only holds a *weak* reference to a running task, so a task
#: whose sole reference is a discarded ``create_task`` return value can be
#: garbage collected mid-await and vanish without ever finishing. Holding it
#: here until completion is what makes "fire-and-forget" mean "runs to the
#: end" rather than "runs until the GC notices".
_INFLIGHT: set[asyncio.Task[None]] = set()


def notify_case_completed(case_id: str | None) -> asyncio.Task[None] | None:
    """Hand a finished v1 fraud case to the v2 discovery layer. Fire-and-forget.

    The only call v1 makes into v2. It awaits nothing and raises nothing, so a
    caller on (or just off) the live path pays a truthy check and one
    ``create_task``.

    Args:
        case_id: UUID of the case v1 just persisted. Falsy values are ignored —
            v1 legitimately skips persistence for e.g. transcript-less calls.

    Returns:
        The scheduled task, or ``None`` when nothing was scheduled. v1 is not
        expected to use the return value; it exists so tests (and the REST
        endpoint) can observe the pipeline deterministically.
    """
    if not case_id:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from sync context / no loop: nothing to schedule onto. This is
        # not an error for v1 — it just means v2 does not run here.
        logger.warning("v2 ingest: no running event loop — case %s not ingested", case_id)
        return None

    try:
        task = loop.create_task(run_ingest_pipeline(str(case_id)))
    except Exception:  # pragma: no cover - defensive
        logger.exception("v2 ingest: failed to schedule pipeline for case %s", case_id)
        return None

    _INFLIGHT.add(task)
    task.add_done_callback(_INFLIGHT.discard)
    return task


async def run_ingest_pipeline(case_id: str) -> None:
    """Background v2 ingest pipeline for one case.

    Pipeline: ``case_ingested`` event → MO extraction → entity resolution →
    discovery (OBSERVED check, candidate scoring, debounced re-clustering).

    Never raises: every ``Exception`` is logged and swallowed, because this runs
    as a detached task launched from v1's call teardown.
    """
    from src.enterprise.discovery import get_discovery_engine
    from src.enterprise.entity_resolver import entities_from_identifiers, resolve_entities
    from src.enterprise.mo_extractor import run_mo_extraction

    try:
        # Load before announcing. `case_ingested` used to fire first and the
        # pipeline then bailed on the next line for a transcript-less case, so
        # the console was told a case had been ingested when nothing had been
        # extracted, linked or clustered for it.
        #
        # The event is still emitted on that path, because it is also the
        # console's refetch trigger (Shell counters, the case list and the
        # graph all reload on it) and the case row genuinely does exist — the
        # case list really did change. What was wrong was that a skipped case
        # was indistinguishable from a fully processed one. `skipped` says
        # which happened; unknown payload keys are ignored by the ticker, so
        # this needs no frontend change to be safe.
        transcript = await asyncio.to_thread(load_case_transcript, case_id)
        skipped = not transcript
        payload: dict[str, Any] = {
            "case_id": case_id,
            "utterances": len(transcript),
            "skipped": skipped,
        }
        if skipped:
            payload["skipped_reason"] = "no_transcript"
        await emit_event(layer="case", event_type="case_ingested", payload=payload)

        if skipped:
            logger.info("v2 ingest: case %s has no transcript — skipping MO extraction", case_id)
            return

        mo = await asyncio.to_thread(run_mo_extraction, case_id, transcript)
        if mo:
            await emit_event(
                layer="case",
                event_type="mo_extracted",
                payload={"case_id": case_id, "extractor": mo.get("extractor", "llm-v1")},
            )
            raw_entities = entities_from_identifiers(mo.get("identifiers", {}))
            resolved = await asyncio.to_thread(resolve_entities, case_id, raw_entities)
            if resolved:
                await emit_event(
                    layer="case",
                    event_type="entity_linked",
                    payload={
                        "case_id": case_id,
                        "entities": [
                            {"type": e["entity_type"], "value": e["value_norm"]} for e in resolved
                        ],
                    },
                )

        await get_discovery_engine().on_case_ingested(case_id)
    except Exception:
        logger.exception("v2 ingest pipeline failed for case %s", case_id)


def load_case_transcript(case_id: str) -> list[dict[str, Any]]:
    """Load a case's utterances from ``call_transcripts`` in a reproducible order.

    ``call_transcripts`` has no sequence column, so a row's **position in this
    list is** its utterance index — and MO extraction cites those positions
    (``evidence_utterances``, ``novel_phrases[].utterance_idx``). Ordering on
    ``created_at`` alone is therefore not sufficient: rows written inside the
    same clock tick come back in an arbitrary order, so the same case could
    produce different citations on two reads. ``id`` is the tie-break that makes
    the order reproducible.

    Args:
        case_id: UUID of the fraud case.

    Returns:
        Utterance dicts with ``speaker``, ``utterance``, ``risk_score`` and
        ``seq_idx``; empty list on any failure.
    """
    try:
        result = (
            get_supabase_client()
            .table("call_transcripts")
            .select("*")
            .eq("case_id", case_id)
            .order("created_at")
            .order("id")
            .execute()
        )
        rows = list(getattr(result, "data", None) or [])
    except Exception:
        logger.exception("v2 ingest: failed to load transcript for case %s", case_id)
        return []

    return [
        {
            "speaker": r.get("speaker", "UNKNOWN"),
            "utterance": r.get("utterance") or r.get("text") or "",
            "risk_score": r.get("risk_score", 0),
            # Positional by definition. The table carries no sequence column, and
            # the extractor cites list positions, so seq_idx must equal the
            # position — never a value read back off the row.
            "seq_idx": i,
        }
        for i, r in enumerate(rows)
    ]
