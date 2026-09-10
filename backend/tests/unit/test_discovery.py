"""Unit tests for src.enterprise.discovery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.enterprise.discovery import (
    DEBOUNCE_SECONDS,
    SWEEP_INTERVAL_SECONDS,
    DiscoveryEngine,
    get_discovery_engine,
)
from src.enterprise.events import VALID_SEVERITIES


@patch("src.enterprise.discovery.get_supabase_client")
async def test_on_case_ingested_adds_to_debounce_set(mock_client):
    engine = DiscoveryEngine(store=MagicMock())
    engine._check_observed = AsyncMock()
    engine._score_candidates = AsyncMock()

    await engine.on_case_ingested("case-1")
    assert "case-1" in engine._debounce_set
    engine._check_observed.assert_awaited_once_with("case-1")
    engine._score_candidates.assert_awaited_once_with("case-1")
    await engine.stop()


@patch("src.enterprise.discovery.get_supabase_client")
async def test_debounce_timer_set_on_ingest(mock_client):
    engine = DiscoveryEngine(store=MagicMock())
    engine._check_observed = AsyncMock()
    engine._score_candidates = AsyncMock()

    await engine.on_case_ingested("case-1")
    assert engine._debounce_timer is not None
    await engine.stop()


@patch("src.enterprise.discovery.get_supabase_client")
async def test_debounce_timer_reset_on_second_ingest(mock_client):
    engine = DiscoveryEngine(store=MagicMock())
    engine._check_observed = AsyncMock()
    engine._score_candidates = AsyncMock()

    await engine.on_case_ingested("case-1")
    first_timer = engine._debounce_timer
    await engine.on_case_ingested("case-2")
    assert engine._debounce_timer is not first_timer
    assert first_timer.cancelled()
    assert engine._debounce_set == {"case-1", "case-2"}
    await engine.stop()


@patch("src.enterprise.discovery.get_supabase_client")
async def test_on_case_ingested_survives_stage_failure(mock_client):
    engine = DiscoveryEngine(store=MagicMock())
    engine._check_observed = AsyncMock(side_effect=RuntimeError("boom"))
    engine._score_candidates = AsyncMock(side_effect=RuntimeError("boom"))

    await engine.on_case_ingested("case-1")
    assert "case-1" in engine._debounce_set
    await engine.stop()


async def test_flush_debounce_triggers_recluster():
    engine = DiscoveryEngine(store=MagicMock())
    engine._debounce_set = {"case-1"}
    engine._recluster = AsyncMock()

    engine._flush_debounce()
    await asyncio.sleep(0)

    engine._recluster.assert_called_once()
    assert engine._debounce_set == set()


async def test_flush_debounce_noop_when_empty():
    engine = DiscoveryEngine(store=MagicMock())
    engine._recluster = AsyncMock()
    engine._flush_debounce()
    await asyncio.sleep(0)
    engine._recluster.assert_not_called()


@patch("src.enterprise.discovery.get_supabase_client")
async def test_run_full_sweep_calls_recluster(mock_client):
    engine = DiscoveryEngine(store=MagicMock())
    engine._recluster = AsyncMock()
    await engine.run_full_sweep()
    engine._recluster.assert_called_once()


def _sweep_client(case_ids):
    """Supabase double whose ``fraud_cases`` select returns ``case_ids``."""
    client = MagicMock()
    result = MagicMock()
    result.data = [{"id": cid} for cid in case_ids]
    client.table.return_value.select.return_value.execute.return_value = result
    return client


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_run_full_sweep_scores_every_case_before_clustering(mock_client, mock_emit):
    """Regression: the sweep must drive the ingest pipeline, not only cluster.

    ``_recluster`` reads ``case_links``, and only ``_score_candidates`` writes
    that table. A clustering-only sweep therefore found an empty edge set on a
    freshly seeded database and returned success — the demo's own bootstrap
    button could not bootstrap. Asserting on call *order* as well as presence:
    scoring that ran after clustering would be just as useless.
    """
    mock_client.return_value = _sweep_client(["case-1", "case-2"])
    order: list[tuple[str, str | None]] = []

    engine = DiscoveryEngine(store=MagicMock())
    engine._check_observed = AsyncMock(side_effect=lambda c: order.append(("observed", c)))
    engine._score_candidates = AsyncMock(side_effect=lambda c: order.append(("scored", c)))
    engine._recluster = AsyncMock(side_effect=lambda ids: order.append(("recluster", None)))

    await engine.run_full_sweep()

    assert ("scored", "case-1") in order
    assert ("scored", "case-2") in order
    assert ("observed", "case-1") in order
    assert order[-1] == ("recluster", None)
    engine._recluster.assert_awaited_once()


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_run_full_sweep_warns_when_cases_yield_no_links(mock_client, mock_emit):
    """A sweep over real cases that produces no edges must not look successful."""
    mock_client.return_value = _sweep_client(["case-1"])
    store = MagicMock()
    store.get_all_links.return_value = []

    engine = DiscoveryEngine(store=store)
    engine._check_observed = AsyncMock()
    engine._score_candidates = AsyncMock()
    engine._recluster = AsyncMock()

    await engine.run_full_sweep()

    emitted = [call.kwargs.get("event_type") for call in mock_emit.await_args_list]
    assert "discovery_sweep_empty" in emitted

    # The whole point of this event is that an empty sweep must not look calm.
    # build_event (events.py:147-149) coerces any severity outside
    # VALID_SEVERITIES to "info", so a typo like "warn" would render this as the
    # quietest row on the feed while every assertion above still passed. A
    # mocked emitter records what the call site passed, never the coerced
    # value, so nothing but an explicit check here can catch that.
    sweep_call = next(
        c
        for c in mock_emit.await_args_list
        if c.kwargs.get("event_type") == "discovery_sweep_empty"
    )
    severity = sweep_call.kwargs.get("severity")
    assert severity in VALID_SEVERITIES, f"severity {severity!r} coerces to 'info'"
    assert severity == "warning"


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_run_full_sweep_silent_when_links_exist(mock_client, mock_emit):
    """The warning is for genuine emptiness only — links present, no warning."""
    mock_client.return_value = _sweep_client(["case-1"])
    store = MagicMock()
    store.get_all_links.return_value = [{"src": "case-1", "dst": "case-2", "weight": 0.9}]

    engine = DiscoveryEngine(store=store)
    engine._check_observed = AsyncMock()
    engine._score_candidates = AsyncMock()
    engine._recluster = AsyncMock()

    await engine.run_full_sweep()

    emitted = [call.kwargs.get("event_type") for call in mock_emit.await_args_list]
    assert "discovery_sweep_empty" not in emitted


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_run_full_sweep_survives_one_bad_case(mock_client, mock_emit):
    """One unparseable case must not abort the sweep for every other case."""
    mock_client.return_value = _sweep_client(["case-1", "case-2"])

    engine = DiscoveryEngine(store=MagicMock())
    engine._check_observed = AsyncMock()
    engine._score_candidates = AsyncMock(side_effect=RuntimeError("boom"))
    engine._recluster = AsyncMock()

    await engine.run_full_sweep()

    assert engine._score_candidates.await_count == 2
    engine._recluster.assert_awaited_once()


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_propose_campaign_inserts_campaign(mock_client, mock_emit):
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value.data = [{"id": "camp-1"}]
    mock_table.select.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    engine = DiscoveryEngine(store=MagicMock())
    await engine._propose_campaign(
        {"c1", "c2", "c3"},
        {"passes": True, "confidence": 0.85, "case_count": 3, "customer_count": 3},
        {},
    )

    assert mock_table.insert.called
    payload = mock_table.insert.call_args[0][0]
    assert payload["status"] == "PENDING_VALIDATION"
    assert payload["case_count"] == 3
    assert payload["code"] == "SCAM-001"
    mock_emit.assert_awaited()
    assert mock_emit.await_args.kwargs["event_type"] == "campaign_proposed"


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_propose_campaign_marks_cases_clustered(mock_client, mock_emit):
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value.data = [{"id": "camp-1"}]
    mock_table.select.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    engine = DiscoveryEngine(store=MagicMock())
    await engine._propose_campaign(
        {"c1"}, {"passes": True, "confidence": 0.9, "customer_count": 2}, {}
    )

    tables = [c.args[0] for c in mock_client.return_value.table.call_args_list]
    assert "campaign_cases" in tables
    assert "case_discovery_state" in tables


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_merge_into_campaign_updates_case_count(mock_client, mock_emit):
    mock_table = MagicMock()
    mock_table.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "camp-1", "code": "SCAM-001"}
    ]
    mock_client.return_value.table.return_value = mock_table

    engine = DiscoveryEngine(store=MagicMock())
    await engine._merge_into_campaign(
        {"c4"},
        {
            "confidence": 0.8,
            "novel": False,
            "gates": {"novelty": {"matched_campaign_id": "camp-1", "best_cosine": 0.95}},
        },
        {},
    )

    assert mock_table.update.called
    mock_emit.assert_awaited()
    assert mock_emit.await_args.kwargs["event_type"] == "campaign_grew"


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_merge_into_campaign_no_campaign_is_noop(mock_client, mock_emit):
    mock_table = MagicMock()
    mock_table.select.return_value.in_.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    engine = DiscoveryEngine(store=MagicMock())
    await engine._merge_into_campaign({"c4"}, {"confidence": 0.8, "gates": {}}, {})

    assert not mock_table.update.called
    mock_emit.assert_not_awaited()


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_check_observed_marks_high_risk_unexplained_case(mock_client, mock_emit):
    cases_table = MagicMock()
    cases_table.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "c1", "user_id": "u1", "risk_tier": "HIGH", "created_at": "2026-09-10T10:00:00Z"}
    ]
    mo_table = MagicMock()
    mo_table.select.return_value.eq.return_value.execute.return_value.data = [
        {"embedding": [1.0, 0.0, 0.0], "fingerprint": {}}
    ]
    campaigns_table = MagicMock()
    campaigns_table.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": "camp-1", "code": "SCAM-001", "mo_embedding": [0.0, 1.0, 0.0]}
    ]
    links_table = MagicMock()
    links_table.select.return_value.eq.return_value.execute.return_value.data = []
    state_table = MagicMock()

    def router(name):
        return {
            "fraud_cases": cases_table,
            "case_mo": mo_table,
            "campaigns": campaigns_table,
            "case_entity_links": links_table,
            "case_discovery_state": state_table,
        }[name]

    mock_client.return_value.table.side_effect = router

    engine = DiscoveryEngine(store=MagicMock())
    await engine._check_observed("c1")

    payload = state_table.upsert.call_args[0][0]
    assert payload["state"] == "OBSERVED"
    assert mock_emit.await_args.kwargs["event_type"] == "case_observed"


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_check_observed_skips_non_high_risk(mock_client, mock_emit):
    cases_table = MagicMock()
    cases_table.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "c1", "risk_tier": "LOW"}
    ]
    mock_client.return_value.table.return_value = cases_table

    engine = DiscoveryEngine(store=MagicMock())
    await engine._check_observed("c1")
    mock_emit.assert_not_awaited()


# ── mo_summary provenance ────────────────────────────────────────────────────
# `campaigns.mo_summary` is exposed to `legal` and `compliance` — roles denied
# transcripts and PII — and that entitlement was granted on the strength of one
# claim: the column holds a *brand name*, not prose. It is safe because of what
# is written into it, and `_propose_campaign` below is its only writer.
#
# That was an unenforced assumption. These tests enforce it, so a future change
# that starts writing a generated summary into the column fails here loudly
# instead of silently widening what `legal` and `compliance` can read.
VICTIM_NAME = "Ahmad bin Hassan"
VICTIM_ACCOUNT = "7712345678"
MO_NARRATIVE = (
    f"{VICTIM_NAME} was told his account {VICTIM_ACCOUNT} was frozen and "
    "transferred RM8,000 after the caller threatened arrest."
)

#: A fingerprint carrying both the safe brand name and the transcript-derived
#: prose that must never reach the column.
_LOADED_FINGERPRINT = {
    "impersonated_entity": "Maybank",
    "script_phases": ["authority_claim", "account_freeze", "safe_account_transfer"],
    "pressure_tactics": ["arrest_threat", "urgency"],
    "narrative": MO_NARRATIVE,
    "victim_name": VICTIM_NAME,
}


def _cases_with_prose():
    """Two clustered cases whose MO fingerprints carry victim prose."""
    return {
        cid: {
            "id": cid,
            "user_id": f"u-{cid}",
            "risk_tier": "HIGH",
            "created_at": "2026-09-10T10:00:00Z",
            "mo_fingerprint": dict(_LOADED_FINGERPRINT),
        }
        for cid in ("c1", "c2")
    }


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_mo_summary_is_exactly_the_impersonated_entity(mock_client, mock_emit):
    """The column holds the `impersonated_entity` field verbatim — nothing else.

    Asserted as an identity against the source field rather than against a
    hardcoded string, so the test tracks the fingerprint rather than a literal
    that could drift away from it.
    """
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value.data = [{"id": "camp-1"}]
    mock_table.select.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    engine = DiscoveryEngine(store=MagicMock())
    await engine._propose_campaign(
        {"c1", "c2"},
        {"passes": True, "confidence": 0.88, "case_count": 2, "customer_count": 2},
        _cases_with_prose(),
    )

    payload = mock_table.insert.call_args[0][0]
    assert payload["mo_summary"] == _LOADED_FINGERPRINT["impersonated_entity"]


@patch("src.enterprise.discovery.emit_event", new_callable=AsyncMock)
@patch("src.enterprise.discovery.get_supabase_client")
async def test_mo_summary_never_carries_transcript_prose(mock_client, mock_emit):
    """No victim-side identity reaches `mo_summary`, even when the fingerprint
    it is derived from is full of it.

    This is the assertion that actually protects the `legal` / `compliance`
    entitlement: the fingerprint feeding the writer carries a narrative, a
    victim name and an account number, and none of them may survive into the
    column those roles are allowed to read.
    """
    mock_table = MagicMock()
    mock_table.insert.return_value.execute.return_value.data = [{"id": "camp-1"}]
    mock_table.select.return_value.execute.return_value.data = []
    mock_client.return_value.table.return_value = mock_table

    engine = DiscoveryEngine(store=MagicMock())
    await engine._propose_campaign(
        {"c1", "c2"},
        {"passes": True, "confidence": 0.88, "case_count": 2, "customer_count": 2},
        _cases_with_prose(),
    )

    payload = mock_table.insert.call_args[0][0]
    summary = payload["mo_summary"]

    # Non-vacuity: an empty or absent summary would pass every check below
    # while proving nothing, so establish there is real content first.
    assert isinstance(summary, str) and summary.strip(), (
        f"mo_summary was empty ({summary!r}) — the assertions below prove nothing"
    )
    # Non-vacuity: the dangerous strings must really be in the input, or their
    # absence downstream is not evidence of anything.
    assert VICTIM_NAME in MO_NARRATIVE and VICTIM_ACCOUNT in MO_NARRATIVE

    for secret in (VICTIM_NAME, VICTIM_ACCOUNT, MO_NARRATIVE):
        assert secret not in summary, f"{secret!r} leaked into mo_summary"


def test_constants_match_spec():
    assert DEBOUNCE_SECONDS == 30
    assert SWEEP_INTERVAL_SECONDS == 300


def test_get_discovery_engine_is_singleton():
    assert get_discovery_engine() is get_discovery_engine()


def test_engine_store_is_lazy():
    """Constructing the engine must never touch Supabase."""
    engine = DiscoveryEngine()
    assert engine._store is None
