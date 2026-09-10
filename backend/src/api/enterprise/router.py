"""Enterprise Console REST API (v2).

Paths follow 01_upgrade_plan.md §13 — ``/enterprise/...``, never
``/enterprise/api/...``. Read endpoints are defensive: the console must render
even when a v2 table is empty or the migration has not been applied yet.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.enterprise import presenters
from src.db.vector_store import get_supabase_client
from src.enterprise import registry
from src.enterprise.events import emit_event, fetch_recent_events
from src.enterprise.ingest import notify_case_completed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enterprise", tags=["enterprise"])

CASE_FIELDS = "id, user_id, risk_tier, risk_score, status, created_at, trigger_type"

CAMPAIGN_FIELDS = (
    "id, code, name, status, confidence, mo_summary, indicators, case_count, "
    "customer_count, first_seen, last_seen, created_at, approved_by, approved_at, reject_reason"
)

#: Case statuses that count as finished for the overview's open-case counter.
CLOSED_STATUSES = frozenset({"CLOSED", "RESOLVED", "DISMISSED", "ARCHIVED"})

#: Campaign states a human may still approve.
APPROVABLE_STATUSES = ("CANDIDATE", "PENDING_VALIDATION")

#: Campaign states a human may still edit.
#:
#: Deliberately excludes APPROVED/ACTIVE. Approval compiles the hypothesis into
#: artifacts and propagates them to workers, so a later edit would leave the
#: propagated artifact describing one thing and the campaign text a human signed
#: off describing another — with nothing on either record to show they had ever
#: diverged. The edit is refused instead; correcting an approved campaign is a
#: new version, not a rewrite of the approved one.
EDITABLE_STATUSES = ("CANDIDATE", "PENDING_VALIDATION")

#: Campaign states a human may still reject — deliberately the same gate as
#: approval. A decision that has already been recorded (APPROVED / ACTIVE /
#: REJECTED, or a lifecycle end state) is never quietly reversed by a second
#: POST; the caller gets a 409 instead.
REJECTABLE_STATUSES = APPROVABLE_STATUSES


def _rows(result: Any) -> list[dict[str, Any]]:
    """Extract rows from a Supabase response, tolerating None."""
    return list(getattr(result, "data", None) or [])


def _safe(fn: Any, default: Any) -> Any:
    """Run a blocking Supabase query, returning ``default`` on any failure."""
    try:
        return fn()
    except Exception:
        logger.exception("enterprise API: query failed")
        return default


def _case_ordinal_map(client: Any) -> dict[str, int]:
    """Build the case-id → display-number map (blocking).

    Reads the whole ``fraud_cases`` id column rather than the current page,
    because the ordinal has to be the case's position in the entire incident
    log: numbering a page would restart at 1 on page two and give one case two
    different numbers on two screens.
    """
    rows = _safe(
        lambda: _rows(
            client.table("fraud_cases")
            .select("id, created_at")
            .order("created_at")
            .limit(10000)
            .execute()
        ),
        [],
    )
    return presenters.case_ordinals(rows)


def _entity_type_index(client: Any, case_ids: list[str]) -> dict[str, str]:
    """Map entity value → entity type, for naming identifiers in link reasons.

    ``case_links.signals`` records *which* identifier two cases shared but not
    what kind it was, so "shared 60xxxx" becomes "shared phone" only with this.
    """
    if not case_ids:
        return {}
    mentions = _safe(
        lambda: _rows(
            client.table("case_entity_links").select("entity_id").in_("case_id", case_ids).execute()
        ),
        [],
    )
    entity_ids = sorted({str(m["entity_id"]) for m in mentions if m.get("entity_id")})
    if not entity_ids:
        return {}
    rows = _safe(
        lambda: _rows(
            client.table("entities")
            .select("entity_type, value_norm, value_raw")
            .in_("id", entity_ids)
            .execute()
        ),
        [],
    )
    index: dict[str, str] = {}
    for row in rows:
        etype = str(row.get("entity_type") or "")
        for key in (row.get("value_norm"), row.get("value_raw")):
            if key:
                index[str(key)] = etype
    return index


@router.get("/overview")
async def get_overview() -> dict[str, Any]:
    """Nervous-system overview: layer counters, live campaigns and recent events.

    Returns:
        Dict with ``layers``, ``metrics``, ``campaigns``, ``recent_events`` and
        ``generated_at``.
    """

    def _query() -> dict[str, Any]:
        client = get_supabase_client()
        cutoff_24h = (datetime.now(UTC) - timedelta(hours=24)).isoformat()

        # `status` is read below for the open-case counter. It has to be named
        # here: PostgREST returns only the selected columns, so omitting it
        # made every case look status-less and therefore open, and
        # `layers.case.open` silently equalled `layers.case.cases` forever.
        cases = _safe(
            lambda: _rows(
                client.table("fraud_cases").select("id, risk_tier, status, created_at").execute()
            ),
            [],
        )
        entities = _safe(lambda: _rows(client.table("entities").select("id").execute()), [])
        links = _safe(lambda: _rows(client.table("case_links").select("score").execute()), [])
        campaigns = _safe(
            lambda: _rows(
                client.table("campaigns")
                .select(
                    "id, code, name, status, confidence, case_count, customer_count, "
                    "first_seen, last_seen, created_at"
                )
                .order("created_at", desc=True)
                .limit(50)
                .execute()
            ),
            [],
        )
        artifacts = _safe(
            lambda: _rows(client.table("artifacts").select("id, tier, status, version").execute()),
            [],
        )
        observed = _safe(
            lambda: _rows(
                client.table("case_discovery_state")
                .select("case_id")
                .eq("state", "OBSERVED")
                .execute()
            ),
            [],
        )
        memberships = _safe(
            lambda: _rows(
                client.table("campaign_cases")
                .select("campaign_id, case_id, joined_at")
                .execute()
            ),
            [],
        )

        cases_24h = [c for c in cases if str(c.get("created_at") or "") >= cutoff_24h]
        active_campaigns = [c for c in campaigns if c.get("status") in ("APPROVED", "ACTIVE")]
        pending = [c for c in campaigns if c.get("status") in ("CANDIDATE", "PENDING_VALIDATION")]
        open_cases = [c for c in cases if str(c.get("status") or "").upper() not in CLOSED_STATUSES]
        core_version = max(
            (int(a.get("version") or 0) for a in artifacts if a.get("tier") == "core"),
            default=0,
        )

        # Screen A's MetricBar. `metrics` is a list precisely so that a metric
        # nobody can measure yet is *absent* rather than zero — the panel's
        # "no metrics yet" empty state is an honest report, a bar reading 0 is
        # not. Only campaigns in the window fetched above are measurable, which
        # is why the campaign list is read before this runs.
        metric = presenters.time_to_discovery_metric(
            {str(c["id"]): c.get("created_at") for c in campaigns if c.get("id")},
            memberships,
            {str(c["id"]): c.get("created_at") for c in cases if c.get("id")},
        )

        # The console's counter strip (adapters.normaliseOverview) reads
        # `layers.case.cases`, `layers.case.open`, `layers.discovery.unrecognised`,
        # `layers.discovery.campaigns` and `layers.registry.core_version`. The
        # per-layer detail keys below are kept for the layer panels; the names
        # the adapter looks for are supplied alongside them, in the layer it
        # looks in. Without these every counter renders 0 while the system is
        # working — indistinguishable from an idle system.
        return {
            "layers": {
                "sensing": {"cases_total": len(cases), "cases_24h": len(cases_24h)},
                "case": {
                    "cases": len(cases),
                    "open": len(open_cases),
                    "entities": len(entities),
                    "observed": len(observed),
                },
                "discovery": {
                    "links": len(links),
                    "unrecognised": len(observed),
                    "campaigns": len(campaigns),
                    "campaigns_total": len(campaigns),
                    "campaigns_active": len(active_campaigns),
                    "campaigns_pending": len(pending),
                },
                "registry": {
                    "artifacts_total": len(artifacts),
                    "artifacts_published": len(
                        [a for a in artifacts if a.get("status") == "PUBLISHED"]
                    ),
                    "core_artifacts": len([a for a in artifacts if a.get("tier") == "core"]),
                    "core_version": core_version,
                },
            },
            "metrics": [metric] if metric else [],
            "campaigns": campaigns,
        }

    overview = await asyncio.to_thread(_query)
    overview["recent_events"] = await fetch_recent_events(limit=25)
    overview["generated_at"] = datetime.now(UTC).isoformat()
    return overview


@router.get("/cases")
async def list_cases(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: str | None = Query(None, description="NORMAL | OBSERVED | CLUSTERED"),
    campaign_id: str | None = Query(None),
) -> dict[str, Any]:
    """List cases enriched with their discovery state and campaign membership.

    Args:
        limit: Page size.
        offset: Page offset.
        state: Optional discovery-state filter.
        campaign_id: Optional campaign membership filter.

    Returns:
        Dict with ``cases``, ``total`` and paging echo.
    """

    def _query() -> list[dict[str, Any]]:
        client = get_supabase_client()

        allowed_ids: set[str] | None = None
        if campaign_id:
            member_rows = _safe(
                lambda: _rows(
                    client.table("campaign_cases")
                    .select("case_id")
                    .eq("campaign_id", campaign_id)
                    .execute()
                ),
                [],
            )
            allowed_ids = {str(r["case_id"]) for r in member_rows if r.get("case_id")}
            if not allowed_ids:
                return []

        if state:
            state_rows = _safe(
                lambda: _rows(
                    client.table("case_discovery_state")
                    .select("case_id")
                    .eq("state", state.upper())
                    .execute()
                ),
                [],
            )
            state_ids = {str(r["case_id"]) for r in state_rows if r.get("case_id")}
            allowed_ids = state_ids if allowed_ids is None else (allowed_ids & state_ids)
            if not allowed_ids:
                return []

        query = client.table("fraud_cases").select(CASE_FIELDS)
        if allowed_ids is not None:
            query = query.in_("id", sorted(allowed_ids))
        cases = _safe(
            lambda: _rows(
                query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
            ),
            [],
        )
        if not cases:
            return []

        case_ids = [str(c["id"]) for c in cases]

        states = _safe(
            lambda: _rows(
                client.table("case_discovery_state")
                .select("case_id, state, best_campaign_cosine")
                .in_("case_id", case_ids)
                .execute()
            ),
            [],
        )
        state_by_case = {str(s["case_id"]): s for s in states if s.get("case_id")}

        memberships = _safe(
            lambda: _rows(
                client.table("campaign_cases")
                .select("case_id, campaign_id, linkage_score")
                .in_("case_id", case_ids)
                .execute()
            ),
            [],
        )
        campaign_by_case = {str(m["case_id"]): m for m in memberships if m.get("case_id")}

        campaign_ids = sorted({str(m["campaign_id"]) for m in memberships if m.get("campaign_id")})
        campaign_names: dict[str, str] = {}
        if campaign_ids:
            for row in _safe(
                lambda: _rows(
                    client.table("campaigns")
                    .select("id, code, name")
                    .in_("id", campaign_ids)
                    .execute()
                ),
                [],
            ):
                campaign_names[str(row["id"])] = str(row.get("name") or row.get("code") or "")

        mo_rows = _safe(
            lambda: _rows(
                client.table("case_mo")
                .select("case_id, fingerprint")
                .in_("case_id", case_ids)
                .execute()
            ),
            [],
        )
        fingerprint_by_case = {
            str(m["case_id"]): m.get("fingerprint") for m in mo_rows if m.get("case_id")
        }

        ordinals = _case_ordinal_map(client)

        summarised: list[dict[str, Any]] = []
        for case in cases:
            cid = str(case["id"])
            owning = campaign_by_case.get(cid, {}).get("campaign_id")
            owning_id = str(owning) if owning else None
            # Raw row kept underneath the mapped view: the console reads the
            # mapped keys, but user_id/status/best_campaign_cosine are already
            # relied on elsewhere and extra keys are harmless.
            summarised.append(
                {
                    **case,
                    "best_campaign_cosine": state_by_case.get(cid, {}).get("best_campaign_cosine"),
                    **presenters.case_summary(
                        case,
                        ordinal=ordinals.get(cid, 0),
                        discovery_state=state_by_case.get(cid, {}).get("state", "NORMAL"),
                        campaign_id=owning_id,
                        campaign_name=campaign_names.get(owning_id or ""),
                        fingerprint=fingerprint_by_case.get(cid),
                    ),
                }
            )
        return summarised

    cases = await asyncio.to_thread(_query)
    return {"cases": cases, "total": len(cases), "limit": limit, "offset": offset}


@router.get("/cases/{case_id}")
async def get_case_detail(case_id: str) -> dict[str, Any]:
    """Return one case with its MO fingerprint, entities, links and campaign.

    Args:
        case_id: UUID of the fraud case.

    Returns:
        Case detail dict.

    Raises:
        HTTPException: 404 when the case does not exist.
    """

    def _query() -> dict[str, Any] | None:
        client = get_supabase_client()
        rows = _safe(
            lambda: _rows(client.table("fraud_cases").select("*").eq("id", case_id).execute()), []
        )
        if not rows:
            return None
        case = rows[0]

        mo_rows = _safe(
            lambda: _rows(
                client.table("case_mo")
                .select("fingerprint, narrative, extractor, extracted_at")
                .eq("case_id", case_id)
                .execute()
            ),
            [],
        )
        mo_row = mo_rows[0] if mo_rows else {}
        fingerprint = mo_row.get("fingerprint") if isinstance(mo_row, dict) else None

        # The console's MoFingerprint is flat — normaliseMo reads
        # impersonates/pretext/phases/money_ask_at at the top level of `mo`, so
        # the nested extractor shape has to be flattened and renamed here. The
        # raw fingerprint stays alongside for anything that wants the original.
        case["mo"] = presenters.mo_fingerprint(fingerprint)
        case["fingerprint"] = fingerprint
        case["narrative"] = mo_row.get("narrative") if isinstance(mo_row, dict) else None
        case["mo_meta"] = {
            "extractor": mo_row.get("extractor") if isinstance(mo_row, dict) else None,
            "extracted_at": mo_row.get("extracted_at") if isinstance(mo_row, dict) else None,
        }

        # Must use the SAME order as src.enterprise.ingest.load_case_transcript.
        # `fingerprint.novel_phrases[].utterance_idx` and `evidence_utterances`
        # are positions in the list the extractor was handed, and
        # presenters.transcript_lines re-derives those positions by enumerating
        # these rows. If the two reads disagree — which ordering on `created_at`
        # alone permits, since it is not a total order — every highlight lands
        # on the wrong line. `id` is the tie-break that keeps them identical.
        transcript_rows = _safe(
            lambda: _rows(
                client.table("call_transcripts")
                .select("*")
                .eq("case_id", case_id)
                .order("created_at")
                .order("id")
                .execute()
            ),
            [],
        )
        case["transcript"] = presenters.transcript_lines(transcript_rows, fingerprint)

        entity_rows = _safe(
            lambda: _rows(
                client.table("case_entity_links")
                .select(
                    "entity_id, source, "
                    "entities!inner(id, entity_type, value_norm, value_raw, case_count)"
                )
                .eq("case_id", case_id)
                .execute()
            ),
            [],
        )
        case["entities"] = [
            {
                "entity_id": r.get("entity_id"),
                "source": r.get("source"),
                **(r.get("entities") or {}),
                "entity_type": presenters.coerce_entity_type(
                    (r.get("entities") or {}).get("entity_type")
                ),
            }
            for r in entity_rows
        ]

        # Trace = this case's v2 ingest pipeline as actually recorded in
        # ns_events, with each step's duration measured from the next step's
        # timestamp. These are pipeline stages (case_ingested, mo_extracted,
        # entity_linked), NOT v1 LangGraph node latencies — there is no stored
        # source for those.
        # The timestamp column is `ts`, not `created_at`: ordering by the wrong
        # name raises inside _safe, which returns [] — an empty trace that looks
        # exactly like a case with no recorded pipeline events.
        #
        # A case is named by `payload.case_id` on ingest events and by
        # `case_a`/`case_b` on linking events; matching only the first leaves the
        # trace panel empty for every case, since nothing currently emits it.
        trace_events = _safe(
            lambda: _rows(
                client.table("ns_events")
                .select("event_type, layer, payload, ts")
                .or_(
                    f"payload->>case_id.eq.{case_id},"
                    f"payload->>case_a.eq.{case_id},"
                    f"payload->>case_b.eq.{case_id}"
                )
                .order("ts")
                .limit(200)
                .execute()
            ),
            [],
        )
        case["trace"] = presenters.trace_steps(trace_events)

        case["links"] = _safe(
            lambda: _rows(
                client.table("case_links")
                .select("*")
                .or_(f"case_a.eq.{case_id},case_b.eq.{case_id}")
                .execute()
            ),
            [],
        )

        state_rows = _safe(
            lambda: _rows(
                client.table("case_discovery_state").select("*").eq("case_id", case_id).execute()
            ),
            [],
        )
        # Bare string, not {"state": ...}: the console types discovery_state as
        # a DiscoveryState union and only reached NORMAL before because an
        # unrecognised object fell through to the same default.
        state_row = state_rows[0] if state_rows else {}
        case["discovery_state"] = str(state_row.get("state") or "NORMAL")
        case["discovery_detail"] = state_row or None

        membership = _safe(
            lambda: _rows(
                client.table("campaign_cases")
                .select("campaign_id, linkage_score, joined_at")
                .eq("case_id", case_id)
                .execute()
            ),
            [],
        )
        case["campaign"] = membership[0] if membership else None

        owning_id = str(membership[0]["campaign_id"]) if membership else None
        campaign_name = None
        if owning_id:
            campaign_rows = _safe(
                lambda: _rows(
                    client.table("campaigns").select("id, code, name").eq("id", owning_id).execute()
                ),
                [],
            )
            if campaign_rows:
                campaign_name = str(
                    campaign_rows[0].get("name") or campaign_rows[0].get("code") or ""
                )

        ordinals = _case_ordinal_map(client)
        case.update(
            presenters.case_summary(
                case,
                ordinal=ordinals.get(str(case.get("id")), 0),
                discovery_state=case["discovery_state"],
                campaign_id=owning_id,
                campaign_name=campaign_name,
                fingerprint=fingerprint,
            )
        )
        return case

    case = await asyncio.to_thread(_query)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


def _empty_graph() -> dict[str, Any]:
    """The zero-case graph, in the same shape as a populated one."""
    return {
        "nodes": [],
        "edges": [],
        "links": [],
        "hulls": [],
        "stats": {"cases": 0, "entities": 0, "links": 0},
    }


def _build_graph(client: Any, case_ids: list[str], min_score: float) -> dict[str, Any]:
    """Build the graph payload for a set of cases (blocking).

    Shared by ``/graph`` (Screen C) and the ``mini_graph`` of
    ``/campaigns/{id}`` (Screen D) so the two screens cannot disagree about the
    same cases.

    ``edges`` and ``links`` are the *same list under both names*: Screen C is
    normalised by an adapter that accepts either, but ``mini_graph`` is cast
    straight to ``GraphData`` with no adapter, and that type calls the field
    ``links``. Emitting both is cheaper than having one screen silently render
    an edgeless graph.
    """
    if not case_ids:
        return _empty_graph()

    scoped = set(case_ids)

    cases = _safe(
        lambda: _rows(
            client.table("fraud_cases").select(CASE_FIELDS).in_("id", case_ids).execute()
        ),
        [],
    )

    links = [
        link
        for link in _safe(
            lambda: _rows(client.table("case_links").select("*").gte("score", min_score).execute()),
            [],
        )
        if str(link.get("case_a")) in scoped and str(link.get("case_b")) in scoped
    ]

    mentions = _safe(
        lambda: _rows(
            client.table("case_entity_links")
            .select("case_id, entity_id")
            .in_("case_id", case_ids)
            .execute()
        ),
        [],
    )
    entity_ids = sorted({str(m["entity_id"]) for m in mentions if m.get("entity_id")})

    entities = (
        _safe(
            lambda: _rows(
                client.table("entities")
                .select("id, entity_type, value_norm, value_raw, case_count")
                .in_("id", entity_ids)
                .execute()
            ),
            [],
        )
        if entity_ids
        else []
    )

    states = _safe(
        lambda: _rows(
            client.table("case_discovery_state")
            .select("case_id, state")
            .in_("case_id", case_ids)
            .execute()
        ),
        [],
    )
    state_by_case = {str(s["case_id"]): s.get("state") for s in states if s.get("case_id")}

    memberships = _safe(
        lambda: _rows(
            client.table("campaign_cases")
            .select("case_id, campaign_id")
            .in_("case_id", case_ids)
            .execute()
        ),
        [],
    )
    campaign_by_case = {
        str(m["case_id"]): str(m["campaign_id"])
        for m in memberships
        if m.get("case_id") and m.get("campaign_id")
    }

    campaign_ids = sorted(set(campaign_by_case.values()))
    campaign_rows = (
        _safe(
            lambda: _rows(
                client.table("campaigns").select("id, code, name").in_("id", campaign_ids).execute()
            ),
            [],
        )
        if campaign_ids
        else []
    )

    ordinals = _case_ordinal_map(client)

    # Built from the entities already loaded rather than re-queried: this is
    # what turns "shared 60xxxxxxx" into "shared PHONE 60xxxxxxx" in the hover.
    entity_type_by_value: dict[str, str] = {}
    entity_label_by_id: dict[str, str] = {}
    for entity in entities:
        etype = str(entity.get("entity_type") or "")
        for key in (entity.get("value_norm"), entity.get("value_raw")):
            if key:
                entity_type_by_value[str(key)] = etype
        entity_label_by_id[str(entity.get("id"))] = str(
            entity.get("value_norm") or entity.get("value_raw") or ""
        )

    nodes: list[dict[str, Any]] = [
        presenters.case_node(
            case,
            ordinal=ordinals.get(str(case.get("id"))),
            state=str(state_by_case.get(str(case.get("id"))) or "NORMAL"),
            campaign_id=campaign_by_case.get(str(case.get("id"))),
        )
        for case in cases
    ]
    nodes.extend(presenters.entity_node(entity) for entity in entities)

    edges: list[dict[str, Any]] = [
        presenters.case_link_edge(
            link,
            ordinals=ordinals,
            entity_type_by_value=entity_type_by_value,
        )
        for link in links
    ]
    edges.extend(
        presenters.mention_edge(
            m["case_id"],
            m["entity_id"],
            label=entity_label_by_id.get(str(m["entity_id"])),
        )
        for m in mentions
        if m.get("case_id") and m.get("entity_id")
    )

    node_ids_by_campaign: dict[str, list[str]] = {}
    for case_id_str, owning in campaign_by_case.items():
        node_ids_by_campaign.setdefault(owning, []).append(case_id_str)

    return {
        "nodes": nodes,
        "edges": edges,
        "links": edges,
        "hulls": presenters.campaign_hulls(campaign_rows, node_ids_by_campaign),
        "stats": {"cases": len(cases), "entities": len(entities), "links": len(links)},
    }


@router.get("/graph")
async def get_graph(
    campaign_id: str | None = Query(None),
    min_score: float = Query(0.60, ge=0.0, le=1.0),
    limit: int = Query(300, ge=1, le=2000),
) -> dict[str, Any]:
    """Return the Scam Graph as ``{nodes, edges}`` for the force-directed view.

    Nodes are cases and entities; edges are case↔case links and case→entity
    mentions.

    Args:
        campaign_id: Optional campaign scope.
        min_score: Minimum case-link score to include.
        limit: Maximum number of cases to include.

    Returns:
        Dict with ``nodes``, ``edges`` and ``stats``.
    """

    def _query() -> dict[str, Any]:
        client = get_supabase_client()

        if campaign_id:
            member_rows = _safe(
                lambda: _rows(
                    client.table("campaign_cases")
                    .select("case_id")
                    .eq("campaign_id", campaign_id)
                    .execute()
                ),
                [],
            )
            case_ids = [str(r["case_id"]) for r in member_rows if r.get("case_id")][:limit]
        else:
            case_rows = _safe(
                lambda: _rows(
                    client.table("fraud_cases")
                    .select("id")
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute()
                ),
                [],
            )
            case_ids = [str(r["id"]) for r in case_rows if r.get("id")]

        if not case_ids:
            return _empty_graph()

        return _build_graph(client, case_ids, min_score)

    return await asyncio.to_thread(_query)


@router.post("/discovery/run")
async def run_discovery() -> dict[str, Any]:
    """Force a full discovery sweep (the demo 'Run Scenario' button).

    The sweep runs as a background task so the request returns immediately —
    v2 never blocks on discovery.

    Returns:
        Dict with ``status`` and ``started_at``.
    """
    from src.enterprise.discovery import get_discovery_engine

    engine = get_discovery_engine()
    started_at = datetime.now(UTC).isoformat()

    await emit_event(
        layer="discovery",
        event_type="discovery_sweep_started",
        payload={"trigger": "manual", "started_at": started_at},
    )

    async def _run() -> None:
        try:
            await engine.run_full_sweep()
            await emit_event(
                layer="discovery",
                event_type="discovery_sweep_completed",
                payload={"trigger": "manual", "started_at": started_at},
            )
        except Exception:
            logger.exception("enterprise API: manual discovery sweep failed")
            await emit_event(
                layer="discovery",
                event_type="discovery_sweep_failed",
                severity="warning",
                payload={"trigger": "manual", "started_at": started_at},
            )

    asyncio.create_task(_run())
    return {"status": "started", "started_at": started_at}


@router.post("/ingest/case/{case_id}")
async def ingest_case(case_id: str) -> dict[str, Any]:
    """Run the full v2 ingest pipeline for a completed v1 case.

    A manual/backfill entry point onto the same bridge the live call path uses.
    The pipeline itself lives in :mod:`src.enterprise.ingest` so that v1 can
    hand a case over by calling :func:`~src.enterprise.ingest.notify_case_completed`
    in-process, without importing the v2 HTTP layer or paying an HTTP round
    trip; this endpoint exists for replays, backfills and the demo runner.

    Pipeline: MO extraction → entity resolution → discovery (OBSERVED check,
    candidate scoring, debounced re-clustering). It runs as a background task,
    so the caller returns immediately.

    Args:
        case_id: UUID of the completed fraud case.

    Returns:
        Dict with ``status`` and ``case_id``.
    """
    notify_case_completed(case_id)
    return {"status": "accepted", "case_id": case_id}


@router.get("/events")
async def list_events(
    limit: int = Query(100, ge=1, le=500),
    layer: str | None = Query(None),
    run_id: str | None = Query(None),
    since_id: int | None = Query(None),
) -> dict[str, Any]:
    """Return persisted ``ns_events`` (newest first) for page load and REPLAY.

    Args:
        limit: Maximum rows.
        layer: Optional layer filter.
        run_id: Optional demo-run filter.
        since_id: Only events newer than this id.

    Returns:
        Dict with ``events`` and ``count``.
    """
    events = await fetch_recent_events(limit=limit, layer=layer, run_id=run_id, since_id=since_id)
    return {"events": events, "count": len(events)}


# ── MCP gateway audit log (L6) ───────────────────────────────────────────────
@router.get("/mcp/log")
async def list_mcp_log(
    limit: int = Query(50, ge=1, le=500),
    role: str | None = Query(None, description="Filter by the role the call ran under"),
    caller: str | None = Query(None, description="Filter by caller identifier"),
    as_role: str | None = Query(
        None, description="Read the log through this role's redaction lens"
    ),
) -> dict[str, Any]:
    """Return recent MCP gateway audit entries (newest first) for Screen G.

    Every MCP tool call is recorded here — successes, denials, rate-limit
    rejections and errors alike — so the console can show *who asked what,
    under which role, and what was withheld*. Each row is annotated with
    ``redacted_fields``: the categories that row's role did not receive. The
    console re-renders the same payload under a different role to make the
    redaction difference visible, and this field is what labels it.

    ``outcome`` is surfaced to the top level from ``params`` for legibility;
    the shipped ``mcp_access_log`` schema has no dedicated column for it.

    Trust boundary
    --------------
    ``role`` **filters** rows; ``as_role`` **redacts** them. They are different
    questions ("what did compliance do?" vs "what would compliance be allowed
    to read?") and conflating them would make the filter silently destructive.

    Without ``as_role`` this returns the operator view: full ``params`` and
    ``citations``. That is deliberate — this endpoint serves the internal
    console, which sits inside the trust boundary, whereas the externally
    reachable ``query_mcp_log`` MCP tool always projects. Supply ``as_role``
    to see exactly what an external caller holding that role would get.

    Args:
        limit: Maximum rows.
        role: Optional filter on the role the logged call ran under.
        caller: Optional caller filter.
        as_role: Optional redaction lens; omit for the operator view.

    Returns:
        Dict with ``entries`` and ``count``. Degrades to ``[]`` when the v2
        migration has not been applied — never a 500.
    """
    from mcp.redaction import ROLE_VISIBILITY, project_log_entry, redacted_categories_for

    def _query() -> list[dict[str, Any]]:
        client = get_supabase_client()
        query = client.table("mcp_access_log").select("*")
        if role:
            query = query.eq("role", role)
        if caller:
            query = query.eq("caller", caller)
        return _rows(query.order("ts", desc=True).limit(limit).execute())

    rows = await asyncio.to_thread(_safe, _query, [])

    entries: list[dict[str, Any]] = []
    for row in rows:
        if as_role:
            entries.append(project_log_entry(dict(row), as_role))
            continue
        entry = dict(row)
        params = entry.get("params") or {}
        if isinstance(params, dict) and "outcome" in params:
            entry["outcome"] = params.get("outcome")
        entry["redacted_fields"] = redacted_categories_for(str(entry.get("role") or ""))
        entries.append(entry)

    return {"entries": entries, "count": len(entries), "roles": sorted(ROLE_VISIBILITY)}


# ── Artifact registry ────────────────────────────────────────────────────────
class RollbackRequest(BaseModel):
    """Body of ``POST /enterprise/artifacts/{name}/rollback``.

    The console (``api.rollbackArtifact``) sends ``{"version": n}``, so
    ``version`` is accepted as an alias for ``to_version``. Without it every
    rollback issued from Screen E was a 422 that the client's fixture fallback
    turned into a fake success banner.
    """

    model_config = ConfigDict(populate_by_name=True)

    to_version: int = Field(
        ...,
        ge=1,
        alias="version",
        description="Version whose body is republished",
    )
    approved_by: str = Field("fraud_ops", description="Human approving the rollback")


class ApproveRequest(BaseModel):
    """Body of ``POST /enterprise/campaigns/{id}/approve``."""

    approved_by: str = Field("fraud_ops", description="Human approving the campaign")
    generalise: bool = Field(
        True,
        description="Also run the generaliser and publish a core patch if one validates",
    )


class RejectRequest(BaseModel):
    """Body of ``POST /enterprise/campaigns/{id}/reject``.

    The reason is mandatory. A rejection without a stated reason has no audit
    value — ``campaigns.reject_reason`` is precisely what a post-incident
    review reads to learn why a machine-proposed campaign was refused — so a
    blank or whitespace-only reason is rejected with 422 and nothing is
    persisted.
    """

    reason: str = Field(..., description="Why the campaign was refused (mandatory)")
    rejected_by: str = Field("fraud_ops", description="Human rejecting the campaign")

    @field_validator("reason")
    @classmethod
    def _reason_must_not_be_blank(cls, value: str) -> str:
        """Reject a whitespace-only reason and store the trimmed text."""
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("reason must not be empty")
        return trimmed


@router.get("/artifacts")
async def list_artifacts(
    tier: str | None = Query(None, description="core | pack"),
    name: str | None = Query(None, description="Exact artifact name"),
    campaign_id: str | None = Query(None),
) -> dict[str, Any]:
    """List published artifacts, latest version per name.

    Args:
        tier: Optional tier filter (``core`` or ``pack``).
        name: Optional exact-name filter.
        campaign_id: Optional originating-campaign filter.

    Returns:
        Dict with ``artifacts`` and ``count``. Empty while the v2 migration is
        unapplied — never a 500.
    """
    artifacts = await asyncio.to_thread(registry.list_artifacts, tier, campaign_id, name)
    return {"artifacts": artifacts, "count": len(artifacts), "tier": tier, "name": name}


def _resolve_artifact_version(name: str, version: str) -> int | None:
    """Resolve a path version to an int, expanding ``latest``.

    Returns ``None`` when the value is neither a positive integer nor
    ``latest``, so the caller can answer 400 rather than 500. ``latest`` on an
    artifact with no published version resolves to 0, which then 404s — an
    honest "nothing published yet" rather than a crash.
    """
    if version.strip().lower() == "latest":
        newest = registry.get_artifact(name)
        return int(newest.get("version") or 0) if newest else 0
    try:
        parsed = int(version)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


@router.get("/artifacts/{name}/{version}")
async def get_artifact_version(name: str, version: str) -> dict[str, Any]:
    """Return one artifact version together with its diff to the previous one.

    ``version`` is a positive integer or the literal ``latest``. The console
    (``api.getArtifact``) defaults to ``latest`` when no version is selected,
    so refusing the word would 422 the registry's own default request.

    Args:
        name: Artifact name.
        version: Version number, or ``latest`` for the newest published one.

    Returns:
        Dict with ``current``, ``previous``, ``diff`` and the version history.

    Raises:
        HTTPException: 400 when ``version`` is neither an integer nor
            ``latest``, 404 when the version does not exist.
    """
    resolved = await asyncio.to_thread(_resolve_artifact_version, name, version)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid artifact version {version!r}: expected a positive integer or 'latest'",
        )

    result = await asyncio.to_thread(registry.get_artifact_diff, name, resolved)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Artifact {name} v{resolved} not found")

    history = await asyncio.to_thread(registry.list_artifact_versions, name)
    consumption = await asyncio.to_thread(
        registry.get_consumption, str(result["current"].get("id", ""))
    )
    return {
        **result,
        "versions": [
            {
                "version": row.get("version"),
                "created_at": row.get("created_at"),
                "created_by": row.get("created_by"),
                "approved_by": row.get("approved_by"),
                "status": row.get("status"),
            }
            for row in history
        ],
        "consumption": consumption,
    }


@router.post("/artifacts/{name}/rollback")
async def rollback_artifact(name: str, body: RollbackRequest) -> dict[str, Any]:
    """Roll an artifact back by republishing an earlier body as a new version.

    The registry is append-only: nothing is mutated or deleted, so the rollback
    itself is an auditable event in the artifact's history.

    Args:
        name: Artifact name.
        body: ``{to_version, approved_by}``.

    Returns:
        The newly published artifact row.

    Raises:
        HTTPException: 404 when the target version does not exist.
    """
    artifact = await asyncio.to_thread(
        registry.rollback_artifact, name, body.to_version, body.approved_by
    )
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot roll back {name}: version {body.to_version} not found",
        )

    await emit_event(
        layer="registry",
        event_type="artifact_rolled_back",
        payload={
            "artifact_name": name,
            "restored_from": body.to_version,
            "new_version": artifact.get("version"),
            "approved_by": body.approved_by,
        },
        severity="warning",
    )

    from src.enterprise.propagation import propagate_artifact

    propagation = await propagate_artifact(artifact)
    return {"artifact": artifact, "restored_from": body.to_version, "propagation": propagation}


# ── Campaigns ────────────────────────────────────────────────────────────────
@router.get("/campaigns")
async def list_campaigns(
    status: str | None = Query(None, description="CANDIDATE | PENDING_VALIDATION | APPROVED | …"),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """List campaigns with their case membership counts.

    Args:
        status: Optional status filter.
        limit: Page size.

    Returns:
        Dict with ``campaigns``, ``count`` and ``pending_count``. Empty while
        the v2 migration is unapplied — never a 500.
    """

    def _query() -> list[dict[str, Any]]:
        client = get_supabase_client()
        query = client.table("campaigns").select(CAMPAIGN_FIELDS)
        if status:
            query = query.eq("status", status.upper())
        campaigns = _safe(
            lambda: _rows(query.order("created_at", desc=True).limit(limit).execute()), []
        )
        if not campaigns:
            return []

        campaign_ids = [str(c["id"]) for c in campaigns if c.get("id")]
        members = _safe(
            lambda: _rows(
                client.table("campaign_cases")
                .select("campaign_id, case_id")
                .in_("campaign_id", campaign_ids)
                .execute()
            ),
            [],
        )
        artifacts = _safe(
            lambda: _rows(
                client.table("artifacts")
                .select("campaign_id, artifact_type, version")
                .in_("campaign_id", campaign_ids)
                .execute()
            ),
            [],
        )

        for campaign in campaigns:
            cid = str(campaign.get("id"))
            campaign["linked_cases"] = len([m for m in members if str(m["campaign_id"]) == cid])
            campaign["artifact_count"] = len(
                [a for a in artifacts if str(a.get("campaign_id")) == cid]
            )
            campaign["span_minutes"] = presenters.span_minutes(
                campaign.get("first_seen"), campaign.get("last_seen")
            )
        return campaigns

    campaigns = await asyncio.to_thread(_query)
    pending = [c for c in campaigns if c.get("status") in APPROVABLE_STATUSES]
    return {"campaigns": campaigns, "count": len(campaigns), "pending_count": len(pending)}


def _load_campaign(campaign_id: str) -> dict[str, Any] | None:
    """Load one campaign row (blocking). Returns ``None`` when absent.

    Shared by the approve and reject gates so both decide on exactly the same
    view of the row.
    """
    client = get_supabase_client()
    rows = _safe(
        lambda: _rows(client.table("campaigns").select("*").eq("id", campaign_id).execute()),
        [],
    )
    return rows[0] if rows else None


@router.get("/campaigns/{campaign_id}")
async def get_campaign_detail(campaign_id: str) -> dict[str, Any]:
    """Return one campaign with the evidence an approver needs (Screen D).

    Every field is derived from a stored row. Nothing on this response is
    generated prose: the approval screen is the one place in the system where a
    plausible fabrication would be indistinguishable from a finding, so where
    there is no data the field is empty rather than filled in.

    Args:
        campaign_id: UUID of the campaign.

    Returns:
        A ``CampaignDetail``-shaped dict.

    Raises:
        HTTPException: 404 when the campaign does not exist.
    """

    def _query() -> dict[str, Any] | None:
        client = get_supabase_client()
        campaign = _load_campaign(campaign_id)
        if campaign is None:
            return None

        member_rows = _safe(
            lambda: _rows(
                client.table("campaign_cases")
                .select("case_id, linkage_score, joined_at")
                .eq("campaign_id", campaign_id)
                .execute()
            ),
            [],
        )
        case_ids = [str(m["case_id"]) for m in member_rows if m.get("case_id")]
        linkage_by_case = {
            str(m["case_id"]): m.get("linkage_score") for m in member_rows if m.get("case_id")
        }

        # Per-case summaries use the same mapper as Screen B, so a case reads
        # identically on the list and inside the campaign that claims it.
        cases: list[dict[str, Any]] = []
        if case_ids:
            case_rows = _safe(
                lambda: _rows(
                    client.table("fraud_cases").select(CASE_FIELDS).in_("id", case_ids).execute()
                ),
                [],
            )
            mo_rows = _safe(
                lambda: _rows(
                    client.table("case_mo")
                    .select("case_id, fingerprint")
                    .in_("case_id", case_ids)
                    .execute()
                ),
                [],
            )
            fingerprint_by_case = {
                str(m["case_id"]): m.get("fingerprint") for m in mo_rows if m.get("case_id")
            }
            states = _safe(
                lambda: _rows(
                    client.table("case_discovery_state")
                    .select("case_id, state")
                    .in_("case_id", case_ids)
                    .execute()
                ),
                [],
            )
            state_by_case = {str(s["case_id"]): s.get("state") for s in states if s.get("case_id")}
            ordinals = _case_ordinal_map(client)
            campaign_name = str(campaign.get("name") or campaign.get("code") or "")
            for case in case_rows:
                cid = str(case.get("id"))
                summary = presenters.case_summary(
                    case,
                    ordinal=ordinals.get(cid, 0),
                    discovery_state=str(state_by_case.get(cid) or "NORMAL"),
                    campaign_id=campaign_id,
                    campaign_name=campaign_name,
                    fingerprint=fingerprint_by_case.get(cid),
                )
                summary["linkage_score"] = linkage_by_case.get(cid)
                cases.append(summary)
            cases.sort(key=lambda c: c.get("case_number") or 0)

        # Real promotion-gate outcomes, as recorded when discovery proposed the
        # campaign. Absent for campaigns seeded outside the discovery sweep, in
        # which case campaign_evidence falls back to the row's own columns.
        gates: dict[str, Any] = {}
        for event in _safe(
            lambda: _rows(
                client.table("ns_events")
                .select("event_type, payload, ts")
                .eq("event_type", "campaign_proposed")
                .eq("payload->>campaign_id", campaign_id)
                .order("ts", desc=True)
                .limit(1)
                .execute()
            ),
            [],
        ):
            payload = event.get("payload")
            if isinstance(payload, dict) and isinstance(payload.get("gates"), dict):
                gates = payload["gates"]

        artifact_rows = _safe(
            lambda: _rows(
                client.table("artifacts")
                # `source_campaigns` is named here because presenters.
                # proposed_artifact reads it. Omitting it did not fail: the read
                # returned None and the presenter emitted [], so every artifact
                # on Screen D showed no provenance at all — and a core rule
                # generalised from three campaigns is precisely the artifact
                # whose provenance an approver needs to see.
                .select(
                    "name, tier, target_agent, version, artifact_type, "
                    "campaign_id, source_campaigns"
                )
                .eq("campaign_id", campaign_id)
                .order("version", desc=True)
                .execute()
            ),
            [],
        )

        detail: dict[str, Any] = {
            "id": str(campaign.get("id")),
            "code": str(campaign.get("code") or ""),
            "name": str(campaign.get("name") or ""),
            "status": str(campaign.get("status") or "CANDIDATE"),
            "confidence": campaign.get("confidence") or 0,
            "case_count": campaign.get("case_count") or len(case_ids),
            "customer_count": campaign.get("customer_count") or 0,
            "first_seen": campaign.get("first_seen"),
            "last_seen": campaign.get("last_seen"),
            "span_minutes": presenters.span_minutes(
                campaign.get("first_seen"), campaign.get("last_seen")
            ),
            "case_ids": case_ids,
            "cases": cases,
            "evidence": presenters.campaign_evidence(campaign, gates),
            "hypothesis": presenters.campaign_hypothesis(campaign),
            "proposed_artifacts": [presenters.proposed_artifact(a) for a in artifact_rows],
            "mini_graph": _build_graph(client, case_ids, 0.0) if case_ids else _empty_graph(),
            "mo_summary": campaign.get("mo_summary"),
            "approved_by": campaign.get("approved_by"),
            "approved_at": campaign.get("approved_at"),
            "reject_reason": campaign.get("reject_reason"),
        }
        return detail

    detail = await asyncio.to_thread(_query)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return detail


@router.post("/campaigns/{campaign_id}/approve")
async def approve_campaign(campaign_id: str, body: ApproveRequest) -> dict[str, Any]:
    """Approve a campaign, then compile and propagate its artifacts.

    This endpoint **is** the governance gate. Compilation runs nowhere else:
    :func:`src.enterprise.compiler.compile_approved_campaign` re-reads the row
    and refuses anything that is not in an approved state, so no autonomously
    generated artifact can reach a customer.

    Args:
        campaign_id: Campaign UUID.
        body: ``{approved_by, generalise}``.

    Returns:
        Dict with ``status``, ``campaign`` and ``approved_by``.

    Raises:
        HTTPException: 404 when the campaign is unknown, 409 when its status
            is not approvable, 503 when the approval cannot be persisted.
    """

    campaign = await asyncio.to_thread(_load_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")

    current_status = str(campaign.get("status", ""))
    if current_status not in APPROVABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Campaign {campaign_id} is {current_status or 'UNKNOWN'}, not approvable",
        )

    approved_at = datetime.now(UTC).isoformat()

    def _approve() -> bool:
        try:
            get_supabase_client().table("campaigns").update(
                {
                    "status": "APPROVED",
                    "approved_by": body.approved_by,
                    "approved_at": approved_at,
                }
            ).eq("id", campaign_id).execute()
            return True
        except Exception:
            logger.exception("enterprise API: failed to approve campaign %s", campaign_id)
            return False

    if not await asyncio.to_thread(_approve):
        raise HTTPException(status_code=503, detail="Could not persist campaign approval")

    campaign["status"] = "APPROVED"
    campaign["approved_by"] = body.approved_by
    campaign["approved_at"] = approved_at

    await emit_event(
        layer="registry",
        event_type="campaign_approved",
        payload={
            "campaign_id": campaign_id,
            "code": campaign.get("code"),
            "approved_by": body.approved_by,
            "previous_status": current_status,
        },
    )

    asyncio.create_task(
        _run_approval_pipeline(campaign_id, campaign, body.approved_by, body.generalise)
    )
    return {"status": "approved", "campaign": campaign, "compilation": "started"}


@router.post("/campaigns/{campaign_id}/reject")
async def reject_campaign(campaign_id: str, body: RejectRequest) -> dict[str, Any]:
    """Reject a campaign candidate, recording **why**.

    The other half of the governance gate. Nothing is compiled and nothing is
    published: the row moves to ``REJECTED`` and the analyst's reason is
    written to ``campaigns.reject_reason``, which is the audit trail a
    post-incident review reads. Because
    :func:`src.enterprise.compiler.compile_approved_campaign` only compiles
    ``APPROVED``/``ACTIVE`` rows, a rejected campaign can never be compiled
    afterwards.

    Who and when are recorded in the same two columns the approve handler
    uses — ``approved_by``/``approved_at`` are the row's decision-maker and
    decision-time columns; ``status`` says which decision was taken. The v2
    schema deliberately carries no separate ``rejected_by``/``rejected_at``.

    Args:
        campaign_id: Campaign UUID.
        body: ``{reason, rejected_by}``. ``reason`` is mandatory and may not
            be blank.

    Returns:
        Dict with ``status``, ``campaign`` and ``reject_reason``.

    Raises:
        HTTPException: 404 when the campaign is unknown, 409 when a decision
            has already been recorded, 503 when the rejection cannot be
            persisted. A missing or blank ``reason`` is a 422 from the model.
    """
    campaign = await asyncio.to_thread(_load_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")

    current_status = str(campaign.get("status", ""))
    if current_status not in REJECTABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Campaign {campaign_id} is {current_status or 'UNKNOWN'}; "
                "a recorded decision is not reversed by rejection"
            ),
        )

    rejected_at = datetime.now(UTC).isoformat()

    def _reject() -> bool:
        try:
            # approved_by/approved_at are the row's decision-maker and
            # decision-time columns, NOT approval-specific ones: on a REJECTED
            # row they name who refused it and when. Read `status` to learn
            # which decision was taken.
            get_supabase_client().table("campaigns").update(
                {
                    "status": "REJECTED",
                    "reject_reason": body.reason,
                    "approved_by": body.rejected_by,
                    "approved_at": rejected_at,
                }
            ).eq("id", campaign_id).execute()
            return True
        except Exception:
            logger.exception("enterprise API: failed to reject campaign %s", campaign_id)
            return False

    if not await asyncio.to_thread(_reject):
        raise HTTPException(status_code=503, detail="Could not persist campaign rejection")

    campaign["status"] = "REJECTED"
    campaign["reject_reason"] = body.reason
    campaign["approved_by"] = body.rejected_by
    campaign["approved_at"] = rejected_at

    # The console does not poll — without this event Screen D keeps showing
    # the campaign as pending.
    await emit_event(
        layer="registry",
        event_type="campaign_rejected",
        payload={
            "campaign_id": campaign_id,
            "status": "REJECTED",
            "code": campaign.get("code"),
            "reason": body.reason,
            "rejected_by": body.rejected_by,
            "previous_status": current_status,
        },
        severity="warning",
    )

    return {"status": "rejected", "campaign": campaign, "reject_reason": body.reason}


class CampaignEditRequest(BaseModel):
    """Body of ``PATCH /enterprise/campaigns/{id}``.

    The console (``api.editCampaign``) sends only the fields the analyst
    touched — today ``{name, mo_summary}`` from Screen D's edit form — so every
    field is optional. A body that sets none of them is a 422 rather than a
    silent 200: "saved" is the one thing this endpoint must never report when
    it wrote nothing.

    ``extra="forbid"`` for the same reason. Pydantic's default is to drop
    unrecognised keys, so a console sending a field this endpoint cannot store
    would be answered ``200`` with that field quietly discarded — the edit
    would look saved and be gone on the next refetch.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, description="Analyst's corrected campaign name")
    mo_summary: str | None = Field(None, description="Analyst's corrected MO hypothesis")
    indicators: list[Any] | None = Field(None, description="Replacement indicator list")
    edited_by: str = Field("fraud_ops", description="Human making the edit")

    @field_validator("name")
    @classmethod
    def _name_must_not_be_blank(cls, value: str | None) -> str | None:
        """Refuse a whitespace-only name and store the trimmed text.

        ``name`` is the campaign's identity on every screen and in the
        artifacts compiled from it; blanking it would leave the row displayed
        as its bare code with no way to tell that a human had erased it.
        """
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("name must not be empty")
        return trimmed

    def changes(self) -> dict[str, Any]:
        """Return only the columns this request actually sets.

        ``mo_summary`` may legitimately be set to an empty string — an analyst
        deleting a hypothesis they do not believe is a real edit — so emptiness
        is not used to mean "unset". Absence is.
        """
        patch: dict[str, Any] = {}
        if self.name is not None:
            patch["name"] = self.name
        if self.mo_summary is not None:
            patch["mo_summary"] = self.mo_summary.strip()
        if self.indicators is not None:
            patch["indicators"] = self.indicators
        return patch


@router.patch("/campaigns/{campaign_id}")
async def edit_campaign(campaign_id: str, body: CampaignEditRequest) -> dict[str, Any]:
    """Record a human's corrections to a campaign hypothesis, before approval.

    Screen D lets an analyst rewrite a machine-generated name and MO summary.
    This is the third door in the governance gate alongside approve and reject,
    and it is the one that has to stay shut *after* a decision: approval
    compiles the hypothesis into artifacts and propagates them to workers, so
    an edit accepted afterwards would silently decouple what was propagated
    from the text a human signed off. ``EDITABLE_STATUSES`` is therefore
    checked against the freshly loaded row, not against anything the client
    sends.

    The response is the full ``CampaignDetail`` produced by
    :func:`get_campaign_detail`, re-read after the write. The console replaces
    its cached campaign with whatever comes back, so this deliberately returns
    stored state rather than echoing the request — an echo would render
    identically whether or not the update landed.

    Args:
        campaign_id: Campaign UUID.
        body: ``{name?, mo_summary?, indicators?, edited_by}``.

    Returns:
        The updated ``CampaignDetail``.

    Raises:
        HTTPException: 404 when the campaign is unknown, 409 when its status is
            not editable, 422 when the body changes nothing or blanks the name,
            503 when the edit cannot be persisted.
    """
    campaign = await asyncio.to_thread(_load_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")

    current_status = str(campaign.get("status", ""))
    if current_status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Campaign {campaign_id} is {current_status or 'UNKNOWN'}; "
                "its hypothesis has already been compiled and propagated and is "
                "no longer editable"
            ),
        )

    patch = body.changes()
    if not patch:
        raise HTTPException(
            status_code=422,
            detail="No editable fields supplied (name, mo_summary, indicators)",
        )

    def _update() -> bool:
        try:
            get_supabase_client().table("campaigns").update(patch).eq(
                "id", campaign_id
            ).execute()
            return True
        except Exception:
            logger.exception("enterprise API: failed to edit campaign %s", campaign_id)
            return False

    if not await asyncio.to_thread(_update):
        raise HTTPException(status_code=503, detail="Could not persist campaign edit")

    # The console does not poll — without this event Screen D keeps showing the
    # pre-edit hypothesis to every other connected client. `fields` names what
    # changed so the ticker line is specific; the corrected text itself is
    # fetched, not pushed.
    await emit_event(
        layer="discovery",
        event_type="campaign_edited",
        payload={
            "campaign_id": campaign_id,
            "code": campaign.get("code"),
            "status": current_status,
            "fields": sorted(patch),
            "edited_by": body.edited_by,
        },
    )

    return await get_campaign_detail(campaign_id)


async def _run_approval_pipeline(
    campaign_id: str,
    campaign: dict[str, Any],
    approved_by: str,
    generalise: bool,
) -> None:
    """Compile, publish and propagate an approved campaign. Never raises."""
    from src.enterprise.compiler import compile_approved_campaign
    from src.enterprise.propagation import propagate_campaign_artifacts

    code = campaign.get("code", "UNKNOWN")
    try:
        await emit_event(
            layer="compiler",
            event_type="compilation_started",
            payload={"campaign_id": campaign_id, "code": code},
        )

        compiled = await asyncio.to_thread(compile_approved_campaign, campaign_id)
        if not compiled:
            await emit_event(
                layer="compiler",
                event_type="compilation_failed",
                payload={"campaign_id": campaign_id, "code": code},
                severity="warning",
            )
            return

        await emit_event(
            layer="compiler",
            event_type="compilation_completed",
            payload={
                "campaign_id": campaign_id,
                "code": code,
                "artifact_types": sorted(compiled.keys()),
            },
        )

        results = await propagate_campaign_artifacts(
            campaign_id, compiled, campaign, approved_by=approved_by
        )
        await emit_event(
            layer="registry",
            event_type="artifacts_published",
            payload={
                "campaign_id": campaign_id,
                "code": code,
                "published": sorted(results.keys()),
                "receipts": sum(len(r) for r in results.values()),
            },
        )

        if generalise:
            await _maybe_publish_core_patch(approved_by)
    except Exception:
        logger.exception("enterprise API: approval pipeline failed for %s", campaign_id)


async def _maybe_publish_core_patch(approved_by: str) -> None:
    """Run the generaliser; publish a core patch only if one validates.

    Emitting nothing is the expected outcome most of the time — the core tier
    changes only when a genuinely campaign-agnostic invariant is found.
    """
    from src.enterprise.compiler import fetch_approved_campaigns_with_mo
    from src.enterprise.generaliser import build_core_patch, maybe_generalise
    from src.enterprise.propagation import publish_and_propagate_core

    campaigns = await asyncio.to_thread(fetch_approved_campaigns_with_mo)
    current = await asyncio.to_thread(registry.get_artifact, "phone_agent_core")
    current_content = str((current or {}).get("content") or "")

    proposal = await asyncio.to_thread(maybe_generalise, campaigns, current_content)
    if not proposal:
        await emit_event(
            layer="compiler",
            event_type="generalisation_skipped",
            payload={
                "approved_campaigns": len(campaigns),
                "reason": "no validated cross-campaign invariant",
            },
        )
        return

    await emit_event(
        layer="compiler",
        event_type="core_patch_proposed",
        payload={
            "rule_id": proposal.get("rule_id"),
            "rule_text": proposal.get("rule_text"),
            "source_campaigns": proposal.get("source_campaigns", []),
            "justification": proposal.get("justification"),
        },
    )

    new_content = build_core_patch(current_content, proposal)
    artifact, propagation = await publish_and_propagate_core(
        new_content, proposal, approved_by=approved_by
    )
    if artifact is None:
        await emit_event(
            layer="registry",
            event_type="core_publish_failed",
            payload={"rule_id": proposal.get("rule_id")},
            severity="warning",
        )
        return

    await emit_event(
        layer="registry",
        event_type="core_artifact_published",
        payload={
            "artifact_name": artifact.get("name"),
            "version": artifact.get("version"),
            "rule_id": proposal.get("rule_id"),
            "source_campaigns": proposal.get("source_campaigns", []),
            "receipts": len(propagation),
        },
    )


# ── Evaluation harness (Screen F) ────────────────────────────────────────────
#: Run id stamped on events emitted while the console is in live mode. Mirrors
#: ``enterprise_demo.REPLAY_RUN_ID`` so a consumer of ``ns_events`` can always
#: tell a scripted frame from a live one.
LIVE_RUN_ID = "demo-live"


class EvalRunRequest(BaseModel):
    """Body of ``POST /enterprise/eval/run``.

    The console (``api.runEval``) posts an empty object, so every field must
    have a default — a required field here would 422 the console's own request
    and the client's fixture fallback would turn that failure into a fake
    green score.
    """

    label: str = Field("manual", description="Label stored on the eval_runs row")
    use_llm: bool | None = Field(
        None, description="Force LLM MO extraction on or off; None = env default"
    )
    store: bool = Field(True, description="Persist the run to eval_runs")


def _eval_passes(label: str) -> list[tuple[str, str | None, int | None]]:
    """Build the pass list for one ``POST /eval/run``.

    One press must produce the before/after pair the console draws — not two
    runs of the same configuration, which is what a single unpinned pass per
    press yields (both sides score against whatever is published *now*, so the
    delta is always zero). Each pass therefore pins ``core_content`` to a
    specific published version, holding the corpus constant while the learned
    artifact varies.

    The "before" pass is returned **first** on purpose: ``/eval/latest`` reads
    the two most recent rows newest-first and calls the older of the pair
    "before", so the before row must be written first.

    With fewer than two published versions there is nothing to compare, so a
    single pass is returned and the console renders one bar instead of a
    fabricated delta.

    Args:
        label: Caller-supplied label, used as a prefix when it is not the
            default. Empty prefix keeps the console's own labels readable.

    Returns:
        ``[(pass_label, core_content, core_version), ...]`` of length 1 or 2.
        ``core_content`` is ``None`` when no artifact is published, meaning
        "evaluate with no core rules".
    """
    from src.enterprise import evaluation

    prefix = "" if not label or label == "manual" else f"{label} · "
    try:
        history = registry.list_artifact_versions(evaluation.CORE_ARTIFACT_NAME)
    except Exception:
        logger.warning("enterprise API: core version history unavailable")
        history = []

    published = [
        row
        for row in history or []
        if str(row.get("status") or "").upper() == "PUBLISHED"
    ]

    if len(published) >= 2:
        current, previous = published[0], published[1]
        return [
            (
                f"{prefix}before · core v{previous.get('version')}",
                previous.get("content"),
                previous.get("version"),
            ),
            (
                f"{prefix}after · core v{current.get('version')}",
                current.get("content"),
                current.get("version"),
            ),
        ]
    if published:
        current = published[0]
        return [
            (
                f"{prefix}baseline · core v{current.get('version')}",
                current.get("content"),
                current.get("version"),
            )
        ]
    return [(label or "manual", None, None)]


@router.post("/eval/run")
async def run_eval(body: EvalRunRequest | None = None) -> dict[str, Any]:
    """Run the evaluation corpus once and report what the run actually did.

    Response shape follows the console's ``EvalRunResponse``
    (``{run_id, label, status}``); the extra keys are diagnostics the client
    ignores.

    One press runs the corpus against the **previously published** core version
    and then against the **current** one (see :func:`_eval_passes`), so the
    before/after pair the console draws is a real comparison of two learned
    configurations rather than the same configuration twice. When only one
    version is published, a single baseline pass runs instead.

    ``status`` is the honest part of this contract:

    ``completed``
        The run finished **and** its row reached ``eval_runs``, so
        ``/eval/latest`` will report it.
    ``completed_unpersisted``
        The corpus was scored but the row could not be stored — typically the
        v2 migration is not applied. The numbers existed for the duration of
        this request only; the console will still show "no run yet".
    ``failed``
        The harness raised. No numbers were produced and none are returned.

    A failure answers 200 deliberately: the console silently substitutes a
    fixture for any non-OK response, so a 500 here would render an invented
    passing score. A 200 carrying ``status: "failed"`` cannot.

    Args:
        body: ``{label, use_llm, store}``; all optional.

    Returns:
        Dict with ``run_id``, ``label``, ``status``, ``persisted``,
        ``corpus_size``, ``summary`` and ``passes`` (per-pass labels and the
        core version each was pinned to).
    """
    from src.enterprise import evaluation
    from src.enterprise.corpus import EVAL_DIR

    req = body or EvalRunRequest()
    # Identifies this *press*, not an individual pass: each pass gets its own
    # uuid below because ``eval_runs.id`` is a primary key. A failure has no
    # pass row to point at, so the press id is what the event and the response
    # carry.
    run_id = str(uuid4())
    passes = await asyncio.to_thread(_eval_passes, req.label)

    # run_evaluation emits eval_started and eval_completed itself, so the
    # start/finish pair is on ns_events for every run — including runs whose
    # rows never reach the database.
    result: dict[str, Any] = {}
    completed: list[dict[str, Any]] = []
    for pass_label, core_content, core_version in passes:
        try:
            result = await evaluation.run_evaluation(
                EVAL_DIR,
                run_id=str(uuid4()),
                label=pass_label,
                core_content=core_content,
                core_version=core_version,
                use_llm=req.use_llm,
                store=req.store,
            )
        except Exception:
            logger.exception("enterprise API: eval pass %r failed", pass_label)
            await emit_event(
                layer="registry",
                event_type="eval_failed",
                payload={"run_id": run_id, "label": pass_label},
                severity="warning",
                run_id=run_id,
            )
            return {
                "run_id": run_id,
                "label": pass_label,
                "status": "failed",
                "persisted": False,
                "corpus_size": 0,
                "summary": None,
                "passes": [
                    {"label": lbl, "core_version": ver} for lbl, _, ver in passes
                ],
            }
        completed.append(
            {
                "run_id": str(result.get("run_id") or ""),
                "label": pass_label,
                "core_version": core_version,
            }
        )

    persisted = bool(result.get("stored_id"))
    return {
        "run_id": str(result.get("run_id") or run_id),
        "label": str(result.get("label") or req.label),
        "status": "completed" if persisted else "completed_unpersisted",
        "persisted": persisted,
        "corpus_size": int(result.get("corpus_size") or 0),
        "summary": result.get("summary") or {},
        "passes": completed,
    }


@router.get("/eval/latest")
async def get_latest_eval() -> dict[str, Any]:
    """Return the latest before/after comparison, or an explicit "no run" state.

    Shape follows the console's ``EvalComparison``: ``before`` and ``after``
    are either a run summary or ``null``, and Screen F renders ``—`` for a
    null side. ``status`` states the same fact in one field so the distinction
    cannot be lost:

    ``no_run``
        Nothing has ever been evaluated (or the migration is unapplied). Both
        sides are ``null``; the console shows no score because none exists.
    ``single_run``
        One run exists, so there is an ``after`` but nothing to compare it to.
    ``comparison``
        Two runs exist and ``delta`` is populated.

    Degrades to ``no_run`` rather than raising when ``eval_runs`` is missing.

    Returns:
        Dict with ``before``, ``after``, ``delta``, ``status``, ``has_run``
        and ``run_count``.
    """
    from src.enterprise import evaluation

    comparison = await asyncio.to_thread(
        _safe, evaluation.get_eval_comparison, {"before": None, "after": None}
    )
    latest = await asyncio.to_thread(_safe, evaluation.get_latest_comparison, None)

    before = comparison.get("before")
    after = comparison.get("after")
    run_count = len([side for side in (before, after) if side])
    status = ("no_run", "single_run", "comparison")[run_count]

    return {
        "before": before,
        "after": after,
        "delta": (latest or {}).get("delta"),
        "status": status,
        "has_run": run_count > 0,
        "run_count": run_count,
    }


# ── Demo transport (Shell controls) ──────────────────────────────────────────
class ScenarioRequest(BaseModel):
    """Body of ``POST /enterprise/demo/scenario``.

    The console (``api.startScenario``) sends ``{"mode", "speed"}``.
    ``scenario`` is accepted and echoed for callers that name a scenario
    instead, but it selects nothing: ``mode`` is what switches the transport.
    """

    mode: str = Field("replay", description="'replay' or 'live'")
    speed: float = Field(1.0, gt=0, le=60, description="Playback speed multiplier")
    scenario: str | None = Field(None, description="Optional scenario id, echoed back")

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        """Normalise the mode and refuse anything the transport cannot do."""
        mode = value.strip().lower()
        if mode not in {"live", "replay"}:
            raise ValueError("mode must be 'live' or 'replay'")
        return mode


@router.post("/demo/scenario")
async def start_demo_scenario(body: ScenarioRequest | None = None) -> dict[str, Any]:
    """Switch the console between scripted replay and live operation.

    ``replay`` streams the recorded five-act sequence to connected clients;
    ``live`` stops any replay so the console falls back to real ``ns_events``
    traffic. Nothing here fabricates activity in live mode.

    Response shape follows the console's ``DemoScenarioResponse``
    (``{run_id, mode, speed, event_count}``).

    Args:
        body: ``{mode, speed, scenario}``; all optional.

    Returns:
        Dict with ``run_id``, ``mode``, ``speed``, ``event_count`` and the
        transport's own ``status``.
    """
    from src.api import enterprise_demo as demo

    req = body or ScenarioRequest()

    if req.mode == "live":
        detail = await demo.demo_replay_stop()
        run_id = LIVE_RUN_ID
        event_count = int(detail.get("emitted") or 0)
    else:
        detail = await demo.demo_replay_start(demo.ReplayStartRequest(speed=req.speed))
        run_id = str(detail.get("run_id") or demo.REPLAY_RUN_ID)
        event_count = int(detail.get("total") or 0)

    await emit_event(
        layer="exposure",
        event_type="demo_scenario_started",
        payload={
            "mode": req.mode,
            "speed": req.speed,
            "scenario": req.scenario,
            "event_count": event_count,
        },
        run_id=run_id,
    )

    return {
        "run_id": run_id,
        "mode": req.mode,
        "speed": req.speed,
        "event_count": event_count,
        "status": detail.get("status", "ok"),
    }


class DemoResetRequest(BaseModel):
    """Body of ``POST /enterprise/demo/reset``.

    Deliberately exposes no table selector: what a reset clears is fixed by
    ``enterprise_demo.PURGE_PLAN``, which cannot be steered by a request body.
    """

    reseed: bool = Field(True, description="Re-load the seed corpus after clearing")


@router.post("/demo/reset")
async def reset_demo(body: DemoResetRequest | None = None) -> dict[str, Any]:
    """Clear v2 discovery state and return the demo to its opening position.

    Response shape follows the console's ``ActionResponse`` (``{ok, message}``);
    ``cleared``/``warnings``/``reseed`` are the detail behind the banner. A
    table that does not exist yet lands in ``warnings`` — an unapplied
    migration is not an error here.

    Args:
        body: ``{reseed}``; optional.

    Returns:
        Dict with ``ok``, ``message``, ``cleared``, ``warnings`` and ``reseed``.
    """
    from src.api import enterprise_demo as demo

    req = body or DemoResetRequest()

    # demo_reset stops any replay, purges the v2 tables, optionally reseeds and
    # emits the demo_reset event itself.
    try:
        result = await demo.demo_reset(demo.ResetRequest(reseed=req.reseed))
    except Exception:
        logger.exception("enterprise API: demo reset failed")
        await emit_event(
            layer="case",
            event_type="demo_reset_failed",
            payload={"reseed": req.reseed},
            severity="warning",
        )
        return {"ok": False, "message": "demo reset failed", "cleared": [], "warnings": []}

    cleared = list(result.get("cleared") or [])
    warnings = list(result.get("warnings") or [])
    message = f"cleared {len(cleared)} v2 table(s)"
    if warnings:
        message += f", {len(warnings)} unavailable"
    if req.reseed:
        message += "; corpus reseeded"

    return {
        "ok": True,
        "message": message,
        "cleared": cleared,
        "warnings": warnings,
        "reseed": result.get("reseed"),
    }
