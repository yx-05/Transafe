"""Demo controller and evaluation endpoints (B9).

This module is the operator's remote control for the Enterprise Console demo:
it loads the fictional SCAM-027 seed corpus, replays the recorded five-act
event sequence, resets v2 state between runs, and triggers the evaluation and
adaptation harnesses.

Design rules
------------
* **Additive only.** Nothing here imports from, patches, or alters a v1 code
  path. It is mounted at the bottom of ``main.py`` and can be deleted without
  affecting the v1 call pipeline.
* **Reset is v2-only by construction**, not by careful coding. The list of
  purgeable tables is a module constant that is checked against the v1 table
  list at import time; there is no parameter, query string, or request body
  field anywhere in this module that can add a table to it. See
  :data:`PURGE_PLAN`.
* **Degrade, never 500.** Before ``migrations/v2_enterprise.sql`` is applied,
  every endpoint returns an empty/zero result with a ``warnings`` list rather
  than an error, so the console renders instead of showing a crash.
* **Injectable client.** Every database helper takes an optional ``client`` so
  the whole module is testable without a Supabase instance.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.db.vector_store import embed_text, get_supabase_client
from src.enterprise import adaptation as adaptation_mod
from src.enterprise.corpus import (
    CAMPAIGN_CODE,
    EVAL_DIR,
    load_replay_sequence,
    load_seed_transcripts,
    normalised_entities,
    transcript_text,
)
from src.enterprise.entity_resolver import refresh_entity_stats
from src.enterprise.events import emit_event, get_broadcaster
from src.enterprise.seed_prior import build_prior_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enterprise", tags=["enterprise-demo"])

# ── Table safety ────────────────────────────────────────────────────────────
#: Every table that existed before the v2 upgrade. Demo reset must never touch
#: one of these: the seeded customers and their call transcripts are the demo's
#: *input*, and a live deployment's real cases live here too.
V1_TABLES: frozenset[str] = frozenset(
    {
        "users",
        "fraud_cases",
        "call_transcripts",
        "scam_patterns",
        "evidence_bundles",
        "case_actions",
        "trusted_contacts",
        "alerts",
    }
)

#: ``(table, column, floor)`` triples describing how to empty each v2 table.
#: Supabase requires a filter on every delete, so each entry names a column that
#: is present and non-null on every row plus a floor value that always matches.
#: Children precede parents so foreign keys never block a purge.
PURGE_PLAN: tuple[tuple[str, str, str], ...] = (
    ("eval_results", "id", "0"),
    ("eval_runs", "started_at", "1970-01-01T00:00:00Z"),
    ("artifact_consumption", "consumed_at", "1970-01-01T00:00:00Z"),
    ("artifacts", "created_at", "1970-01-01T00:00:00Z"),
    ("campaign_cases", "joined_at", "1970-01-01T00:00:00Z"),
    ("campaigns", "created_at", "1970-01-01T00:00:00Z"),
    ("case_links", "created_at", "1970-01-01T00:00:00Z"),
    ("case_discovery_state", "updated_at", "1970-01-01T00:00:00Z"),
    ("case_mo", "extracted_at", "1970-01-01T00:00:00Z"),
    ("case_entity_links", "created_at", "1970-01-01T00:00:00Z"),
    ("entities", "first_seen", "1970-01-01T00:00:00Z"),
    ("mcp_access_log", "ts", "1970-01-01T00:00:00Z"),
    ("ns_events", "ts", "1970-01-01T00:00:00Z"),
)

#: Tables the purge is allowed to empty, derived from the plan.
PURGEABLE_TABLES: frozenset[str] = frozenset(table for table, _, _ in PURGE_PLAN)

if not PURGEABLE_TABLES.isdisjoint(V1_TABLES):
    # Import-time guard. If someone ever adds a v1 table to the purge plan the
    # process refuses to start, instead of silently deleting customer data on
    # the next demo reset.
    raise RuntimeError(
        "demo reset purge plan targets v1 tables: "
        f"{sorted(PURGEABLE_TABLES & V1_TABLES)}"
    )

# ── Seed identity ───────────────────────────────────────────────────────────
_SEED_URL_NS = uuid.NAMESPACE_URL
_SEED_PREFIX = "https://transafe.local/v2/seed"

#: Human-readable label for the recorded demo run. Kept separate from the id
#: because ``ns_events.run_id`` is a UUID column: emitting the literal string
#: "demo-replay" fails the INSERT with 22P02, and because the persist failure is
#: swallowed the events still broadcast live while never being stored — so a
#: reload mid-replay lost the run, and the console's backlog showed nothing.
REPLAY_RUN_LABEL = "demo-replay"

#: Stable UUID for the recorded run, derived the same way as the seed ids.
REPLAY_RUN_ID = str(uuid.uuid5(_SEED_URL_NS, f"{_SEED_PREFIX}/{REPLAY_RUN_LABEL}"))

_replay_lock = asyncio.Lock()


def _client(client: Any = None) -> Any:
    """Return the injected client, falling back to the process-wide one."""
    return client if client is not None else get_supabase_client()


def _seed_uuid(kind: str, key: str) -> str:
    """Derive a stable UUID so re-seeding upserts instead of duplicating."""
    return str(uuid.uuid5(_SEED_URL_NS, f"{_SEED_PREFIX}/{kind}/{key}"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── Seeding ─────────────────────────────────────────────────────────────────
#: v1 ``call_transcripts.speaker`` accepts only these three values; the corpus
#: uses the more explicit ``AI_AGENT`` label internally.
_SPEAKER_MAP = {"AI_AGENT": "AI", "CALLER": "CALLER", "USER": "USER"}


def _case_rows(seed: dict[str, Any]) -> dict[str, Any]:
    """Build every row a single seed case needs, across v1 and v2 tables.

    Args:
        seed: One entry from :func:`load_seed_transcripts`.

    Returns:
        Dict with ``user``, ``case``, ``transcripts``, ``entities`` and ``mo``.
    """
    case_id = seed["case_id"]
    user_id = seed["user_id"]
    transcript = seed["transcript"]
    entities = normalised_entities(transcript)
    phone = next((e["value"] for e in entities if e["entity_type"] == "PHONE"), None)

    user = {
        "id": user_id,
        "display_name": seed["customer_name"],
        "risk_profile": "normal",
    }
    case = {
        "id": case_id,
        "session_id": _seed_uuid("session", case_id),
        "user_id": user_id,
        "trigger_type": "CALL",
        "risk_score": seed["risk_score"],
        "risk_tier": "HIGH" if seed["risk_score"] >= 70 else "MEDIUM",
        "status": "reviewed",
        "caller_number": phone,
        "created_at": seed["created_at"],
    }
    transcripts = [
        {
            "id": _seed_uuid("transcript", f"{case_id}/{idx}"),
            "case_id": case_id,
            "speaker": _SPEAKER_MAP.get(str(utt.get("speaker", "")).upper(), "CALLER"),
            "utterance": utt.get("utterance", ""),
            # v1 has no sequence column; the console orders on created_at, so
            # the recorded per-utterance timestamps carry the ordering.
            "created_at": utt.get("ts"),
        }
        for idx, utt in enumerate(transcript)
    ]
    mo = {
        "case_id": case_id,
        "fingerprint": seed["mo_fingerprint"],
        # Mirrors the shipped extractor's no-LLM path, which embeds the
        # transcript text itself. Using the fingerprint's placeholder string
        # would give every seed case an identical vector and silently disable
        # narrative linkage.
        "narrative": transcript_text(transcript)[:300],
        "extractor": "seed-corpus",
        "extracted_at": seed["created_at"],
    }
    return {
        "user": user,
        "case": case,
        "transcripts": transcripts,
        "entities": entities,
        "mo": mo,
    }


def _upsert(client: Any, table: str, rows: list[dict[str, Any]], warnings: list[str]) -> int:
    """Upsert rows, recording a warning instead of raising on failure."""
    if not rows:
        return 0
    try:
        client.table(table).upsert(rows).execute()
    except Exception as exc:  # noqa: BLE001 - degrade, never 500
        warnings.append(f"{table}: {exc}")
        logger.warning("demo seed: %s upsert failed: %s", table, exc)
        return 0
    return len(rows)


def _seed_entities(
    client: Any,
    entity_rows: dict[tuple[str, str], dict[str, Any]],
    links: list[tuple[str, tuple[str, str]]],
    warnings: list[str],
) -> tuple[int, int]:
    """Upsert entities then join them to cases.

    Entities are deduplicated on ``(entity_type, value_norm)`` — the same unique
    key the live resolver uses — so a shared scammer phone number becomes one
    row referenced by several cases, which is exactly what makes the linkage
    graph light up.

    Args:
        client: Supabase client.
        entity_rows: Deduplicated entity payloads keyed by identity.
        links: ``(case_id, entity_key)`` pairs.
        warnings: Mutable warning sink.

    Returns:
        ``(entities_written, links_written)``.
    """
    payload = list(entity_rows.values())
    written = _upsert(client, "entities", payload, warnings)
    if not written:
        return 0, 0
    link_rows = [
        {
            "case_id": case_id,
            "entity_id": entity_rows[key]["id"],
            "source": "regex",
        }
        for case_id, key in links
    ]
    link_count = _upsert(client, "case_entity_links", link_rows, warnings)

    # Reconcile each entity's case_count against the links that actually
    # landed, using the same derivation the live resolver uses.
    #
    # The counts computed while building `entity_rows` are a Python-side
    # prediction of this upsert. They agree with the link table only for as
    # long as the upsert wholly succeeds: a partial write leaves an entity
    # claiming "seen in 3 cases" with one edge on the graph, and the number a
    # human reads off the demo would be one nothing in the database supports.
    # Deriving it from `case_entity_links` also keeps the seed honest when the
    # corpus gains a case, where a hand-maintained literal would quietly rot.
    #
    # `last_seen` is passed explicitly: the corpus is dated historically and
    # the live default of "now" would rewrite the seeded timeline.
    if link_count:
        for row in payload:
            refresh_entity_stats(client, row["id"], last_seen=row["last_seen"])

    return written, link_count


async def seed_demo_corpus(client: Any = None) -> dict[str, Any]:
    """Load the fictional seed corpus into v1 inputs and v2 derived state.

    Seeding is idempotent: every row carries a UUID derived from its slug, so
    running it twice upserts rather than duplicating, and a half-finished seed
    can simply be re-run.

    The MO fingerprints and entities are written directly rather than by
    invoking the LLM extractor, so the demo produces identical linkage results
    with or without a live model key.

    Args:
        client: Optional Supabase client.

    Returns:
        Counts per table plus any warnings encountered.
    """
    supabase = _client(client)
    seeds = load_seed_transcripts()
    warnings: list[str] = []

    users: dict[str, dict[str, Any]] = {}
    cases: list[dict[str, Any]] = []
    transcripts: list[dict[str, Any]] = []
    mos: list[dict[str, Any]] = []
    entity_rows: dict[tuple[str, str], dict[str, Any]] = {}
    links: list[tuple[str, tuple[str, str]]] = []

    for seed in seeds:
        rows = _case_rows(seed)
        users[rows["user"]["id"]] = rows["user"]
        cases.append(rows["case"])
        transcripts.extend(rows["transcripts"])
        mos.append(rows["mo"])
        for ent in rows["entities"]:
            key = (ent["entity_type"], ent["value_norm"])
            if key not in entity_rows:
                entity_rows[key] = {
                    "id": _seed_uuid("entity", f"{key[0]}/{key[1]}"),
                    "entity_type": ent["entity_type"],
                    "value_raw": ent["value"],
                    "value_norm": ent["value_norm"],
                    "first_seen": seed["created_at"],
                    "last_seen": seed["created_at"],
                    "case_count": 0,
                }
            entity_rows[key]["case_count"] += 1
            entity_rows[key]["last_seen"] = max(
                entity_rows[key]["last_seen"], seed["created_at"]
            )
            links.append((rows["case"]["id"], key))

    # ── Prior approved campaigns (the generaliser's precondition) ───────────
    # ``maybe_generalise`` needs three approved campaigns before it will propose
    # a core-tier rule, because a pattern present in one campaign is specific to
    # it. With only the wave seeded, a LIVE run can approve exactly one campaign
    # and the generaliser — correctly — declines, so the campaign-agnostic rule
    # would exist only in the recorded replay. See ``src/enterprise/seed_prior.py``.
    prior = build_prior_state(_seed_uuid)
    users.update({row["id"]: row for row in prior["users"]})
    cases.extend(prior["fraud_cases"])
    transcripts.extend(prior["call_transcripts"])
    mos.extend(prior["case_mo"])
    for key, row in prior["entity_rows"].items():
        existing = entity_rows.get(key)
        if existing is None:
            entity_rows[key] = row
        else:
            existing["case_count"] += row["case_count"]
            if row["last_seen"] > existing["last_seen"]:
                existing["last_seen"] = row["last_seen"]
    links.extend(prior["links"])

    for mo in mos:
        # embed_text falls back to a deterministic local vector when no
        # embedding key is configured, so this never blocks the demo.
        try:
            mo["embedding"] = await asyncio.to_thread(embed_text, mo["narrative"])
        except Exception as exc:  # noqa: BLE001 - degrade, never 500
            warnings.append(f"embedding: {exc}")
            logger.warning("demo seed: embedding failed: %s", exc)

    for campaign in prior["campaigns"]:
        # The novelty check compares a candidate campaign against these vectors,
        # so a prior campaign without one would make every new wave look novel.
        try:
            campaign["mo_embedding"] = await asyncio.to_thread(
                embed_text, campaign["mo_summary"]
            )
        except Exception as exc:  # noqa: BLE001 - degrade, never 500
            warnings.append(f"campaign embedding: {exc}")

    counts = {
        "users": _upsert(supabase, "users", list(users.values()), warnings),
        "fraud_cases": _upsert(supabase, "fraud_cases", cases, warnings),
        "call_transcripts": _upsert(supabase, "call_transcripts", transcripts, warnings),
        "case_mo": _upsert(supabase, "case_mo", mos, warnings),
        "campaigns": _upsert(supabase, "campaigns", prior["campaigns"], warnings),
        "campaign_cases": _upsert(supabase, "campaign_cases", prior["campaign_cases"], warnings),
        "artifacts": _upsert(supabase, "artifacts", prior["artifacts"], warnings),
    }
    ents, link_count = _seed_entities(supabase, entity_rows, links, warnings)
    counts["entities"] = ents
    counts["case_entity_links"] = link_count

    await emit_event(
        layer="case",
        event_type="demo_seeded",
        severity="info",
        payload={
            "campaign": CAMPAIGN_CODE,
            "cases": counts["fraud_cases"],
            "entities": counts["entities"],
            "warnings": len(warnings),
        },
    )
    return {"status": "ok", "counts": counts, "warnings": warnings}


# ── Reset ───────────────────────────────────────────────────────────────────
def purge_v2_state(client: Any = None) -> dict[str, Any]:
    """Empty every v2 table listed in :data:`PURGE_PLAN`.

    The plan is a module constant with no injection point, so this function
    cannot be steered at a v1 table by any caller, request body, or config.
    Seeded customers, cases and transcripts therefore survive a reset — they
    are the demo's starting position, not its output.

    Args:
        client: Optional Supabase client.

    Returns:
        Per-table outcome plus warnings for tables that do not exist yet.
    """
    supabase = _client(client)
    cleared: list[str] = []
    warnings: list[str] = []
    for table, column, floor in PURGE_PLAN:
        if table in V1_TABLES:  # pragma: no cover - import guard prevents this
            continue
        try:
            supabase.table(table).delete().gte(column, floor).execute()
        except Exception as exc:  # noqa: BLE001 - degrade, never 500
            warnings.append(f"{table}: {exc}")
            logger.warning("demo reset: %s purge failed: %s", table, exc)
            continue
        cleared.append(table)
    return {"cleared": cleared, "warnings": warnings}


# ── Replay ──────────────────────────────────────────────────────────────────
class _ReplayState:
    """Tracks the single in-flight replay, if any."""

    def __init__(self) -> None:
        self.task: asyncio.Task[None] | None = None
        self.started_at: float | None = None
        self.speed: float = 1.0
        self.emitted: int = 0
        self.total: int = 0

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "emitted": self.emitted,
            "total": self.total,
            "speed": self.speed,
            "elapsed_sec": (
                round(time.monotonic() - self.started_at, 2) if self.started_at else 0.0
            ),
        }


_replay_state = _ReplayState()


def replay_events() -> list[dict[str, Any]]:
    """Return the recorded five-act sequence in live ``ns_events`` shape."""
    return load_replay_sequence()


def _replay_duration(events: list[dict[str, Any]], speed: float) -> float:
    """Wall-clock length of the replay at the given speed multiplier."""
    offsets = [_offset(e) for e in events]
    return round((max(offsets) - min(offsets)) / speed, 2) if offsets else 0.0


def _offset(event: dict[str, Any]) -> float:
    """Seconds from the epoch for an event's recorded timestamp."""
    try:
        return datetime.fromisoformat(str(event["ts"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return 0.0


async def _run_replay(events: list[dict[str, Any]], speed: float) -> None:
    """Broadcast the recorded sequence, preserving its original pacing.

    Frames are published to the in-process broadcaster rather than written to
    ``ns_events``: a replay is a rehearsal of history, and persisting it would
    contaminate the same table the console reads real activity from. The
    ``run_id`` on every frame stays :data:`REPLAY_RUN_ID` so a consumer can
    always tell the two apart.
    """
    broadcaster = get_broadcaster()
    base = min((_offset(e) for e in events), default=0.0)
    start = time.monotonic()
    for event in events:
        target = (_offset(event) - base) / speed
        delay = target - (time.monotonic() - start)
        if delay > 0:
            await asyncio.sleep(delay)
        broadcaster.publish(event)
        _replay_state.emitted += 1


@router.post("/demo/seed")
async def demo_seed() -> dict[str, Any]:
    """Load the fictional SCAM-027 seed corpus."""
    return await seed_demo_corpus()


@router.get("/demo/replay")
async def demo_replay() -> dict[str, Any]:
    """Return the recorded five-act demo sequence.

    The frames are returned exactly as stored in
    ``seeds/ns_events/replay_sequence.json`` and carry the same schema as live
    ``ns_events`` rows, so the console can render a replay through the identical
    code path it uses for the WebSocket stream.
    """
    events = replay_events()
    acts: dict[str, int] = {}
    for event in events:
        act = str((event.get("payload") or {}).get("act", "unknown"))
        acts[act] = acts.get(act, 0) + 1
    return {
        "run_id": REPLAY_RUN_ID,
        "count": len(events),
        "duration_sec": _replay_duration(events, 1.0),
        "acts": acts,
        "events": events,
    }


class ReplayStartRequest(BaseModel):
    """Body for ``POST /enterprise/demo/replay/start``."""

    speed: float = Field(1.0, gt=0, le=60, description="Playback speed multiplier.")


@router.post("/demo/replay/start")
async def demo_replay_start(body: ReplayStartRequest | None = None) -> dict[str, Any]:
    """Begin streaming the recorded sequence to connected console clients."""
    req = body or ReplayStartRequest()
    events = replay_events()
    async with _replay_lock:
        if _replay_state.running:
            return {
                "status": "already_running",
                **_replay_state.snapshot(),
                "run_id": REPLAY_RUN_ID,
            }
        _replay_state.emitted = 0
        _replay_state.total = len(events)
        _replay_state.speed = req.speed
        _replay_state.started_at = time.monotonic()
        _replay_state.task = asyncio.create_task(_run_replay(events, req.speed))

    await emit_event(
        layer="exposure",
        event_type="demo_replay_started",
        severity="info",
        payload={"events": len(events), "speed": req.speed},
        run_id=REPLAY_RUN_ID,
    )
    return {
        "status": "started",
        "run_id": REPLAY_RUN_ID,
        "total": len(events),
        "speed": req.speed,
        "duration_sec": _replay_duration(events, req.speed),
    }


@router.post("/demo/replay/stop")
async def demo_replay_stop() -> dict[str, Any]:
    """Stop an in-flight replay. Safe to call when nothing is running."""
    async with _replay_lock:
        task = _replay_state.task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        snapshot = _replay_state.snapshot()
        _replay_state.task = None
        _replay_state.started_at = None

    await emit_event(
        layer="exposure",
        event_type="demo_replay_stopped",
        severity="info",
        payload={"emitted": snapshot["emitted"], "total": snapshot["total"]},
        run_id=REPLAY_RUN_ID,
    )
    return {"status": "stopped", "run_id": REPLAY_RUN_ID, **snapshot}


# ``POST /enterprise/demo/scenario`` is served by
# :mod:`src.api.enterprise.router`, which owns every path the console calls and
# answers in the client's response shape. It drives the transport through
# :func:`demo_replay_start` / :func:`demo_replay_stop` below, so the replay
# state still lives in exactly one place. Registering it here as well would
# shadow that handler depending on router mount order.


class ResetRequest(BaseModel):
    """Body for ``POST /enterprise/demo/reset``.

    Deliberately exposes no table selector: what gets cleared is fixed by
    :data:`PURGE_PLAN`.
    """

    reseed: bool = Field(True, description="Re-load the seed corpus after clearing.")


async def demo_reset(body: ResetRequest | None = None) -> dict[str, Any]:
    """Clear v2 discovery state and return the demo to its opening position.

    Not routed here: ``POST /enterprise/demo/reset`` is served by
    :mod:`src.api.enterprise.router`, which wraps this result in the
    ``{ok, message}`` envelope the console expects. This stays a plain
    coroutine so the purge/reseed sequence has one implementation.
    """
    req = body or ResetRequest()
    await demo_replay_stop()
    result = purge_v2_state()

    reseed: dict[str, Any] | None = None
    if req.reseed:
        reseed = await seed_demo_corpus()

    await emit_event(
        layer="case",
        event_type="demo_reset",
        severity="warning",
        payload={
            "cleared": result["cleared"],
            "reseeded": bool(reseed),
            "warnings": len(result["warnings"]),
        },
    )
    return {"status": "ok", **result, "reseed": reseed}


# ── Evaluation ──────────────────────────────────────────────────────────────
# ``POST /enterprise/eval/run`` and ``GET /enterprise/eval/latest`` are served
# by :mod:`src.api.enterprise.router`. Both are console-contract endpoints:
# the run reports whether its numbers were actually persisted, and the read
# returns an explicit "no run yet" state, so the console can never render a
# score that no run produced. The adaptation loop below is an operator tool
# with no console caller, so it stays here.


@router.post("/eval/adaptation")
async def eval_adaptation() -> dict[str, Any]:
    """Run the B7b loop: evaluate, generalise a miss, auto-approve, re-evaluate.

    The rule is published only when its measured confidence clears
    :data:`~src.enterprise.adaptation.AUTO_APPROVE_THRESHOLD`; otherwise the
    proposal is returned for human review and the 'after' numbers are absent.
    """
    return await adaptation_mod.run_adaptation_loop(EVAL_DIR)


@router.get("/demo/status")
async def demo_status() -> dict[str, Any]:
    """Report replay progress so the console can drive its transport controls."""
    return {"run_id": REPLAY_RUN_ID, **_replay_state.snapshot()}


__all__ = [
    "PURGEABLE_TABLES",
    "PURGE_PLAN",
    "REPLAY_RUN_ID",
    "V1_TABLES",
    "purge_v2_state",
    "replay_events",
    "router",
    "seed_demo_corpus",
]
