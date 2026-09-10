"""Unit tests for the presenter wiring behind Screens B, C and D.

The v2 tables now exist, and these endpoints have been verified against live
rows. These fakes still earn their place: the router's ``_safe`` turns any query
error into an empty ``200``, so a broken query and an empty table are
indistinguishable from the outside. Pinning the shapes here means a regression
shows up as a red test rather than as a console reading "Case #0 / — / UNKNOWN".

Everything external is mocked: no Supabase, no LLM, no API keys.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from src.api.enterprise import presenters

client = TestClient(app)


def _table_client(
    tables: dict[str, list[dict[str, object]]],
    order_log: list[tuple[str, str]] | None = None,
    project: bool = True,
) -> MagicMock:
    """A Supabase mock that dispatches per table name.

    Every builder method returns the same builder, so any chain of
    select/eq/in_/gte/order/limit/range/or_ terminates at the rows registered
    for that table name. Builders are memoised per table name, so a test can
    reach back into ``supabase.table("campaigns").update`` and assert on what a
    handler wrote.

    ``order_log``, when supplied, collects ``(table, column)`` for every
    ``.order()`` call. Fixture rows cannot catch a query that names a column
    the database does not have — only the sort key can.

    ``project`` makes ``execute()`` return only the columns the caller actually
    named in ``select()``, the way PostgREST does. **On by default**, because a
    pass-everything fixture cannot see a handler that reads a field its own
    query never asked for — such a handler looks perfectly correct under test
    and silently reads ``None`` in production. That is how
    ``layers.case.open`` equalled the total case count for the life of the
    endpoint.

    Note its one blind spot, which cost a second defect here: projection can
    only strip a column the *fixture* carries. A fixture written to match the
    query rather than the schema drops nothing and the mismatch stays
    invisible — see
    ``test_campaign_detail_reports_the_campaigns_that_produced_an_artifact``.
    When adding a fixture, populate it from the table's real columns, not from
    the handler's select list.
    """
    supabase = MagicMock()
    builders: dict[str, MagicMock] = {}

    def _table(name: str) -> MagicMock:
        if name in builders:
            return builders[name]

        builder = MagicMock()
        for method in ("eq", "in_", "gte", "limit", "range", "or_"):
            getattr(builder, method).return_value = builder
        selected: dict[str, str] = {"columns": "*"}

        def _select(columns: str = "*", **_kwargs: object) -> MagicMock:
            selected["columns"] = columns
            return builder

        def _order(column: str, **_kwargs: object) -> MagicMock:
            if order_log is not None:
                order_log.append((name, column))
            return builder

        def _execute(**_kwargs: object) -> MagicMock:
            rows = tables.get(name, [])
            columns = selected["columns"]
            if project and columns != "*":
                wanted = {c.strip() for c in columns.split(",")}
                rows = [{k: v for k, v in row.items() if k in wanted} for row in rows]
            result = MagicMock()
            result.data = rows
            return result

        builder.select.side_effect = _select
        builder.order.side_effect = _order
        builder.execute.side_effect = _execute
        builders[name] = builder
        return builder

    supabase.table.side_effect = _table
    return supabase


CASE_ROWS: list[dict[str, object]] = [
    {"id": "case-a", "risk_tier": "HIGH", "risk_score": 88, "created_at": "2026-09-01T10:00:00Z"},
    {"id": "case-b", "risk_tier": "MEDIUM", "risk_score": 55, "created_at": "2026-09-01T11:00:00Z"},
]


# ---------------------------------------------------------------------------
# Screen A — the MetricBar, and the counters beside it
# ---------------------------------------------------------------------------
#: One campaign named at 12:00, with one case ingested long before it existed
#: and one ingested after. That split is the whole metric.
METRIC_CAMPAIGNS: list[dict[str, object]] = [
    {
        "id": "camp-1",
        "code": "SCAM-027",
        "status": "CANDIDATE",
        "created_at": "2026-09-01T12:00:00Z",
    }
]
METRIC_CASES: list[dict[str, object]] = [
    {
        "id": "case-early",
        "risk_tier": "HIGH",
        "status": "OPEN",
        "created_at": "2026-09-01T00:00:00Z",
    },
    {
        "id": "case-late",
        "risk_tier": "HIGH",
        "status": "OPEN",
        "created_at": "2026-09-01T13:00:00Z",
    },
]
METRIC_MEMBERSHIPS: list[dict[str, object]] = [
    # Ingested 12h before the pattern was named, linked the moment it was.
    {"campaign_id": "camp-1", "case_id": "case-early", "joined_at": "2026-09-01T12:00:00Z"},
    # Ingested after; recognised against the known pattern in 10 minutes.
    {"campaign_id": "camp-1", "case_id": "case-late", "joined_at": "2026-09-01T13:10:00Z"},
]


def _overview(tables: dict[str, list[dict[str, object]]], project: bool = True):
    """Call GET /enterprise/overview against a fixture database."""
    supabase = _table_client(tables, project=project)
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.fetch_recent_events", new=AsyncMock(return_value=[])),
    ):
        return client.get("/enterprise/overview")


def test_overview_emits_a_measured_time_to_discovery_metric() -> None:
    """Screen A's headline MetricBar must be fed by the live backend.

    ``normaliseOverview`` maps ``wire.metrics``; with the key absent the bar
    renders its empty state permanently against a real database and is
    populated only when the mock fixture is serving. Both numbers here are a
    subtraction of two fixture timestamps, so the assertion is on arithmetic,
    not on a constant the endpoint happens to carry.
    """
    response = _overview(
        {
            "fraud_cases": METRIC_CASES,
            "campaigns": METRIC_CAMPAIGNS,
            "campaign_cases": METRIC_MEMBERSHIPS,
        }
    )

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert len(metrics) == 1
    metric = metrics[0]
    assert metric["label"] == "TIME TO DISCOVERY"
    assert metric["unit"] == "min"
    assert metric["lower_is_better"] is True
    # case-early: 00:00 ingest -> 12:00 clustered = 720 min waiting to be discovered.
    assert metric["before_value"] == 720.0
    # case-late: 13:00 ingest -> 13:10 clustered = 10 min to be recognised.
    assert metric["after_value"] == 10.0
    assert metric["before_sample"] == 1
    assert metric["after_sample"] == 1


def test_overview_omits_the_metric_rather_than_reporting_an_unmeasured_zero() -> None:
    """With no case ingested after its campaign, there is no "after" to show.

    The empty list is the point: a metric rendered with ``after_value`` 0 would
    claim instantaneous discovery, which is both the strongest statement on the
    screen and the one nothing in the database supports.
    """
    response = _overview(
        {
            "fraud_cases": [METRIC_CASES[0]],
            "campaigns": METRIC_CAMPAIGNS,
            "campaign_cases": [METRIC_MEMBERSHIPS[0]],
        }
    )

    assert response.status_code == 200
    assert response.json()["metrics"] == []


def test_overview_open_case_count_reads_a_column_it_actually_selected() -> None:
    """``layers.case.open`` must exclude closed cases.

    The query selected ``id, risk_tier, created_at`` and then filtered on
    ``status``, so every row looked status-less and therefore open: the counter
    silently equalled the total case count. This fixture projects to the
    selected columns the way PostgREST does, so the missing column shows up as
    a wrong number rather than passing on fixture rows that carry more fields
    than the query asked for.
    """
    response = _overview(
        {
            "fraud_cases": [
                {"id": "c1", "status": "OPEN", "created_at": "2026-09-01T10:00:00Z"},
                {"id": "c2", "status": "CLOSED", "created_at": "2026-09-01T10:00:00Z"},
                {"id": "c3", "status": "RESOLVED", "created_at": "2026-09-01T10:00:00Z"},
            ]
        },
        project=True,
    )

    assert response.status_code == 200
    layers = response.json()["layers"]["case"]
    assert layers["cases"] == 3
    assert layers["open"] == 1


def test_time_to_discovery_drops_impossible_negative_waits() -> None:
    """A case clustered before it was ingested is skew, not a fast discovery.

    Averaging it in would drag the headline number down with a measurement
    that cannot have happened.
    """
    metric = presenters.time_to_discovery_metric(
        {"camp-1": "2026-09-01T12:00:00Z"},
        [
            {"campaign_id": "camp-1", "case_id": "sane", "joined_at": "2026-09-01T12:00:00Z"},
            {"campaign_id": "camp-1", "case_id": "skewed", "joined_at": "2026-09-01T12:05:00Z"},
            {"campaign_id": "camp-1", "case_id": "after", "joined_at": "2026-09-01T13:10:00Z"},
        ],
        {
            "sane": "2026-09-01T11:00:00Z",
            "skewed": "2026-09-01T18:00:00Z",
            "after": "2026-09-01T13:00:00Z",
        },
    )

    assert metric is not None
    # `skewed` would have contributed -355 min to the "after" cohort.
    assert metric["after_sample"] == 1
    assert metric["after_value"] == 10.0


def test_case_list_carries_the_console_display_fields() -> None:
    """Screen B renders case_number/tier/scam_type — all absent before wiring."""
    supabase = _table_client(
        {
            "fraud_cases": CASE_ROWS,
            "case_mo": [
                {"case_id": "case-a", "fingerprint": {"pretext": "bank security transfer"}}
            ],
            "campaign_cases": [{"case_id": "case-a", "campaign_id": "camp-1"}],
            "campaigns": [{"id": "camp-1", "code": "SCAM-027", "name": "Fake Bank Officer"}],
            "case_discovery_state": [{"case_id": "case-a", "state": "CLUSTERED"}],
        }
    )
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/cases?limit=10")

    assert response.status_code == 200
    cases = {c["id"]: c for c in response.json()["cases"]}
    assert cases["case-a"]["case_number"] == 1
    assert cases["case-b"]["case_number"] == 2
    assert cases["case-a"]["scam_type"] == "bank security transfer"
    assert cases["case-a"]["campaign_name"] == "Fake Bank Officer"
    assert cases["case-a"]["discovery_state"] == "CLUSTERED"
    assert cases["case-a"]["risk_label"] == "CRITICAL"


def test_case_detail_flattens_mo_and_returns_a_bare_discovery_state() -> None:
    """normaliseMo reads the fingerprint at the top level of `mo`, not nested."""
    supabase = _table_client(
        {
            "fraud_cases": [CASE_ROWS[0]],
            "case_mo": [
                {
                    "case_id": "case-a",
                    "narrative": "Caller posed as bank security.",
                    "fingerprint": {
                        "impersonated_entity": "Maybank",
                        "pretext": "account compromised",
                        "script_phases": ["greeting", "fear", "transfer"],
                        "time_to_money_ask_sec": 185,
                        "languages": ["ms"],
                    },
                }
            ],
            "case_discovery_state": [{"case_id": "case-a", "state": "OBSERVED"}],
        }
    )
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/cases/case-a")

    assert response.status_code == 200
    body = response.json()
    assert body["mo"]["impersonates"] == "Maybank"
    assert body["mo"]["phases"] == ["greeting", "fear", "transfer"]
    assert body["mo"]["money_ask_at"] == "03:05"
    assert body["mo"]["language"] == "ms"
    assert body["narrative"] == "Caller posed as bank security."
    # Bare string, not {"state": ...} — the console types this as a union.
    assert body["discovery_state"] == "OBSERVED"
    assert isinstance(body["transcript"], list)
    assert isinstance(body["trace"], list)


def test_case_detail_reads_the_transcript_in_the_extractor_s_order() -> None:
    """The console must enumerate the transcript exactly as the extractor did.

    ``novel_phrases[].utterance_idx`` / ``evidence_utterances`` are positions in
    the list handed to MO extraction, and ``transcript_lines`` re-derives those
    positions by enumerating the rows this endpoint reads. ``created_at`` is not
    a total order, so without the same tie-break the two enumerations can differ
    and every highlight lands on the wrong line.
    """
    order_log: list[tuple[str, str]] = []
    supabase = _table_client({"fraud_cases": [CASE_ROWS[0]]}, order_log=order_log)
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        assert client.get("/enterprise/cases/case-a").status_code == 200

    transcript_order = [col for table, col in order_log if table == "call_transcripts"]
    assert transcript_order == ["created_at", "id"]


def test_case_detail_and_ingest_agree_on_transcript_order() -> None:
    """Pin the two reads together so they cannot drift apart independently."""
    from src.enterprise.ingest import load_case_transcript

    order_log: list[tuple[str, str]] = []
    supabase = _table_client({"fraud_cases": [CASE_ROWS[0]]}, order_log=order_log)
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        client.get("/enterprise/cases/case-a")
    console_order = [col for table, col in order_log if table == "call_transcripts"]

    ingest_log: list[tuple[str, str]] = []
    ingest_client = _table_client({"call_transcripts": []}, order_log=ingest_log)
    with patch("src.enterprise.ingest.get_supabase_client", return_value=ingest_client):
        load_case_transcript("case-a")
    ingest_order = [col for table, col in ingest_log if table == "call_transcripts"]

    assert console_order == ingest_order


def test_graph_edges_explain_themselves() -> None:
    """An edge with no reason is a number with no argument (B4)."""
    supabase = _table_client(
        {
            "fraud_cases": CASE_ROWS,
            "case_links": [
                {
                    "case_a": "case-a",
                    "case_b": "case-b",
                    "score": 0.95,
                    "signals": {
                        "shared_identifier": {"matched": True, "shared_values": ["60123456789"]}
                    },
                }
            ],
            "case_entity_links": [{"case_id": "case-a", "entity_id": "ent-1"}],
            "entities": [
                {
                    "id": "ent-1",
                    "entity_type": "PHONE",
                    "value_norm": "60123456789",
                    "case_count": 2,
                }
            ],
            "campaign_cases": [
                {"case_id": "case-a", "campaign_id": "camp-1"},
                {"case_id": "case-b", "campaign_id": "camp-1"},
            ],
            "campaigns": [{"id": "camp-1", "code": "SCAM-027", "name": "Fake Bank Officer"}],
        }
    )
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/graph")

    assert response.status_code == 200
    body = response.json()
    link = next(e for e in body["edges"] if e["kind"] == "case-case")
    assert "60123456789" in link["reason"]
    assert "PHONE" in link["reason"]
    # A list of key names makes the console's Object.entries() yield indices.
    assert isinstance(link["signals"], dict)
    assert link["weight"] == 0.95
    # mini_graph is cast to GraphData with no adapter, which names it `links`.
    assert body["links"] == body["edges"]
    hull = body["hulls"][0]
    assert hull["code"] == "SCAM-027"
    assert sorted(hull["node_ids"]) == ["case-a", "case-b"]
    case_node = next(n for n in body["nodes"] if n["id"] == "case-a")
    assert case_node["campaign_id"] == "camp-1"
    assert case_node["label"] == "#1"


def test_campaign_detail_matches_the_console_contract() -> None:
    """getCampaign has no adapter, so the wire shape must be exact (B2)."""
    supabase = _table_client(
        {
            "campaigns": [
                {
                    "id": "camp-1",
                    "code": "SCAM-027",
                    "name": "Fake Bank Officer",
                    "status": "PENDING_VALIDATION",
                    "confidence": 0.89,
                    "case_count": 2,
                    "customer_count": 2,
                    "mo_summary": "Caller impersonates bank security.",
                    "indicators": ["60123456789"],
                    "first_seen": "2026-09-01T10:00:00Z",
                    "last_seen": "2026-09-01T11:00:00Z",
                }
            ],
            "campaign_cases": [
                {"case_id": "case-a", "campaign_id": "camp-1", "linkage_score": 0.95},
                {"case_id": "case-b", "campaign_id": "camp-1", "linkage_score": 0.91},
            ],
            "fraud_cases": CASE_ROWS,
            "artifacts": [
                {
                    "name": "scam_pack_027",
                    "tier": "pack",
                    "target_agent": "phone_agent",
                    "version": 3,
                    "artifact_type": "detection_rules",
                }
            ],
        }
    )
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/campaigns/camp-1")

    assert response.status_code == 200
    body = response.json()
    assert body["case_ids"] == ["case-a", "case-b"]
    assert body["span_minutes"] == 60
    assert body["hypothesis"]["mo_summary"] == "Caller impersonates bank security."
    assert body["hypothesis"]["novel_indicators"] == ["60123456789"]
    assert body["proposed_artifacts"][0]["name"] == "scam_pack_027"
    assert body["proposed_artifacts"][0]["version"] == 3
    assert "links" in body["mini_graph"]
    assert all({"label", "value", "passed"} <= set(e) for e in body["evidence"])
    assert body["cases"][0]["case_number"] == 1


def test_campaign_detail_reports_the_campaigns_that_produced_an_artifact() -> None:
    """``proposed_artifacts[].source_campaigns`` must not be permanently empty.

    ``presenters.proposed_artifact`` reads ``source_campaigns``, a populated
    JSONB column that the generaliser writes when a rule is promoted from
    several campaigns at once. The detail query never named it, so the read
    returned ``None`` and the list rendered ``[]`` for every artifact ever
    shown — the provenance of a cross-campaign rule, blank on the screen where
    a human approves it.

    Same shape as the ``layers.case.open`` defect: a handler reading a field
    its own query did not request. It survived the projection sweep only
    because the fixture above carries exactly the selected columns, so there
    was nothing for the projection to strip — the fixture agreed with the
    query rather than with the schema.
    """
    supabase = _table_client(
        {
            "campaigns": [{"id": "camp-1", "code": "SCAM-027", "name": "Fake Bank Officer"}],
            "artifacts": [
                {
                    "name": "phone_agent_core",
                    "tier": "core",
                    "target_agent": "phone_worker",
                    "version": 14,
                    "artifact_type": "core_rule",
                    "campaign_id": "camp-1",
                    "source_campaigns": ["SCAM-019", "SCAM-024", "SCAM-027"],
                }
            ],
        }
    )
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/campaigns/camp-1")

    assert response.status_code == 200
    artifact = response.json()["proposed_artifacts"][0]
    assert artifact["source_campaigns"] == ["SCAM-019", "SCAM-024", "SCAM-027"]


# ---------------------------------------------------------------------------
# Screen D — PATCH /enterprise/campaigns/{id}
# ---------------------------------------------------------------------------
def _campaign_row(status: str) -> dict[str, object]:
    return {
        "id": "camp-1",
        "code": "SCAM-027",
        "name": "Fake Bank Officer",
        "status": status,
        "confidence": 0.89,
        "mo_summary": "Caller impersonates bank security.",
        "indicators": ["60123456789"],
        "first_seen": "2026-09-01T10:00:00Z",
        "last_seen": "2026-09-01T11:00:00Z",
    }


def _patch_campaign(status: str, body: dict[str, object]):
    """PATCH camp-1 in ``status``; returns (response, supabase, emit_event mock)."""
    supabase = _table_client({"campaigns": [_campaign_row(status)], "fraud_cases": CASE_ROWS})
    emit = AsyncMock()
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new=emit),
    ):
        response = client.patch("/enterprise/campaigns/camp-1", json=body)
    return response, supabase, emit


def test_patch_campaign_persists_the_analysts_correction() -> None:
    """The Edit control on Screen D hit an unrouted PATCH and got 405.

    The client papered over it with a fabricated saved record, so the analyst
    saw their correction accepted and the database never changed.
    """
    response, supabase, _ = _patch_campaign(
        "PENDING_VALIDATION",
        {"name": "Fake Bank Officer (Maybank)", "mo_summary": "Refined hypothesis."},
    )

    assert response.status_code == 200
    written = supabase.table("campaigns").update.call_args[0][0]
    assert written == {
        "name": "Fake Bank Officer (Maybank)",
        "mo_summary": "Refined hypothesis.",
    }
    # The response is re-read state, not an echo of the request.
    assert response.json()["id"] == "camp-1"
    assert "hypothesis" in response.json()


def test_patch_campaign_refuses_to_rewrite_an_approved_hypothesis() -> None:
    """Approval compiles and propagates artifacts; the text is frozen after it.

    A rewrite accepted here would leave the propagated artifact describing one
    thing and the campaign a human signed off describing another, with nothing
    on either record showing they had diverged.
    """
    response, supabase, emit = _patch_campaign("APPROVED", {"mo_summary": "Rewritten."})

    assert response.status_code == 409
    # main.py wraps HTTPException.detail in an error envelope; the analyst has
    # to be told *why* it was refused, not just that it was.
    assert "APPROVED" in response.text
    assert "no longer editable" in response.text
    supabase.table("campaigns").update.assert_not_called()
    emit.assert_not_awaited()


def test_patch_campaign_refuses_an_edit_to_a_live_campaign() -> None:
    """ACTIVE is past the same gate as APPROVED and must be refused too."""
    response, supabase, _ = _patch_campaign("ACTIVE", {"name": "Renamed"})

    assert response.status_code == 409
    supabase.table("campaigns").update.assert_not_called()


def test_patch_campaign_rejects_a_body_that_changes_nothing() -> None:
    """A no-op edit must not report "saved" — the defect this endpoint fixes."""
    response, supabase, emit = _patch_campaign("CANDIDATE", {"edited_by": "analyst"})

    assert response.status_code == 422
    supabase.table("campaigns").update.assert_not_called()
    emit.assert_not_awaited()


def test_patch_campaign_rejects_a_blank_name() -> None:
    """Blanking the campaign's identity is a mistake, not an edit."""
    response, supabase, _ = _patch_campaign("CANDIDATE", {"name": "   "})

    assert response.status_code == 422
    supabase.table("campaigns").update.assert_not_called()


def test_patch_campaign_allows_clearing_a_hypothesis_the_analyst_rejects() -> None:
    """An empty mo_summary is a real edit: "I do not believe this summary"."""
    response, supabase, _ = _patch_campaign("CANDIDATE", {"mo_summary": ""})

    assert response.status_code == 200
    assert supabase.table("campaigns").update.call_args[0][0] == {"mo_summary": ""}


def test_patch_campaign_refuses_a_field_it_cannot_store() -> None:
    """Dropping an unknown key and answering 200 would look identical to saving it.

    The unknown key is sent *alongside* a valid one on purpose. On its own it
    would be refused anyway for changing nothing, so the test would pass
    against a model that silently discards extras and prove nothing; paired
    with a real edit, only ``extra="forbid"`` produces the 422.
    """
    response, supabase, _ = _patch_campaign(
        "CANDIDATE", {"name": "Renamed", "confidence": 0.99}
    )

    assert response.status_code == 422
    supabase.table("campaigns").update.assert_not_called()


def test_patch_campaign_404s_on_an_unknown_campaign() -> None:
    supabase = _table_client({"campaigns": []})
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new=AsyncMock()),
    ):
        response = client.patch("/enterprise/campaigns/nope", json={"name": "x"})

    assert response.status_code == 404


def test_patch_campaign_emits_an_event_so_the_console_refetches() -> None:
    """The console does not poll; without this every other client stays stale."""
    _, _, emit = _patch_campaign("CANDIDATE", {"name": "Renamed", "edited_by": "analyst"})

    emit.assert_awaited_once()
    kwargs = emit.await_args.kwargs
    assert kwargs["event_type"] == "campaign_edited"
    assert kwargs["payload"]["campaign_id"] == "camp-1"
    assert kwargs["payload"]["fields"] == ["name"]
    assert kwargs["payload"]["edited_by"] == "analyst"


def test_campaign_evidence_uses_recorded_gate_verdicts() -> None:
    """Evidence must be the real promotion gates, not numbers invented here."""
    from src.api.enterprise import presenters

    gates = {
        "case_count": {"value": 6, "min": 3, "pass": True},
        "distinct_customers": {"value": 4, "min": 2, "pass": True},
        "strong_edge": {"value": 0.95, "min": 0.80, "pass": True},
        "time_span": {"value": 2, "max": 14, "pass": True},
        "novelty": {"best_cosine": 0.41, "threshold": 0.90, "pass": True},
    }
    evidence = presenters.campaign_evidence({"case_count": 6}, gates)
    by_label = {e["label"]: e for e in evidence}

    assert by_label["cases"]["value"] == "6 (min 3)"
    assert by_label["distinct customers"]["value"] == "4 (min 2)"
    assert by_label["strongest link"]["value"] == "0.95 (min 0.80)"
    assert all(e["passed"] for e in evidence)


def test_campaign_evidence_reports_a_failed_gate_as_failed() -> None:
    """A gate that did not pass must not render as a tick."""
    from src.api.enterprise import presenters

    gates = {"distinct_customers": {"value": 1, "min": 2, "pass": False}}
    evidence = presenters.campaign_evidence({}, gates)

    assert evidence[0]["passed"] is False


def test_campaign_hypothesis_is_never_null() -> None:
    """ValidationConsole reads hypothesis.name unguarded — null is a blank screen."""
    supabase = _table_client(
        {"campaigns": [{"id": "camp-1", "code": "SCAM-027", "name": "", "mo_summary": None}]}
    )
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/campaigns/camp-1")

    assert response.status_code == 200
    hypothesis = response.json()["hypothesis"]
    assert hypothesis is not None
    # Empty, not synthesised: an approver must never read invented prose.
    assert hypothesis["mo_summary"] == ""
    assert hypothesis["novel_indicators"] == []


def test_link_reason_distinguishes_edges_that_differ_only_by_temporal_boost() -> None:
    """Live data has two edges whose strongest signal is identical.

    Both read "shared DOMAIN bnm-verify…"; one scores 0.90 and the other 1.00,
    and the entire difference is a temporal multiplier recorded in ``signals``.
    A hover that gives the same justification for two different numbers invites
    the operator to assume one of them is wrong.
    """
    from src.api.enterprise import presenters

    domain_signal = {
        "shared_domain": {
            "type": "shared_domain",
            "weight": 0.8,
            "matched": True,
            "shared_values": ["bnm-verify-portal.example"],
        }
    }

    plain = presenters.link_reason(dict(domain_signal), 0.9, ordinal_a=110, ordinal_b=119)
    boosted = presenters.link_reason(
        {**domain_signal, "temporal": {"applied": True, "multiplier": 1.15}},
        1.0,
        ordinal_a=110,
        ordinal_b=116,
    )

    assert plain == "shared DOMAIN bnm-verify… · w 0.90 · cases #110,#119"
    assert boosted == "shared DOMAIN bnm-verify… · w 1.00 · temporal ×1.15 · cases #110,#116"
    assert plain != boosted

    # An unapplied or absent boost must not add noise.
    assert "temporal" not in presenters.link_reason(
        {**domain_signal, "temporal": {"applied": False, "multiplier": 1.15}}, 0.9
    )
    assert "temporal" not in presenters.link_reason(
        {**domain_signal, "temporal": {"applied": True}}, 0.9
    )

    # case_links orders its pair by UUID, so ordinals arrive unsorted.
    assert presenters.link_reason({}, 0.5, ordinal_a=119, ordinal_b=111).endswith("cases #111,#119")


def test_link_reason_never_justifies_an_edge_with_a_sub_gate_cosine() -> None:
    """A cosine that earned no weight is not the reason for the edge.

    Coercing JSON-string embeddings flipped ``narrative`` from *absent* to
    *present-and-sub-gate on every pair*, which made this branch reachable for
    the first time. It sits above the ``mo_overlap`` branch, so an MO-only link
    would swap "shared MO phases" for "narrative cosine -0.01" — a near-zero
    number from a dead signal standing in as the justification, on the one
    screen where an operator is asked to trust the scoring.

    The guard keys on ``weight`` (presence == contributed to the score) rather
    than on ``not below_gate`` (absence of a negative marker). The third case
    below is why: a bare ``{"cosine": x}`` from any future emitter passes the
    marker test and fails the contribution test.

    All 15 live links carry ``shared_domain``, so none of this is reachable
    today — a fresh ``discovery/run`` forming one MO-only link is enough.
    """
    from src.api.enterprise import presenters

    mo_only = {"mo_overlap": {"type": "mo_overlap", "score": 0.43}}

    sub_gate = presenters.link_reason(
        {**mo_only, "narrative": {"cosine": -0.0088, "below_gate": True}}, 0.42
    )
    assert "narrative" not in sub_gate
    assert "shared MO phases" in sub_gate

    # Control: a gate-passing cosine *did* earn weight and must still explain
    # the edge. Without this, a guard that suppressed the branch unconditionally
    # would pass the assertion above.
    above_gate = presenters.link_reason(
        {**mo_only, "narrative": {"cosine": 0.91, "weight": 0.6825}}, 0.42
    )
    assert "narrative cosine 0.91" in above_gate

    # A cosine carrying neither marker contributed nothing, so it explains
    # nothing; the guard must fail safe rather than fall through to rendering.
    unmarked = presenters.link_reason({**mo_only, "narrative": {"cosine": -0.0088}}, 0.42)
    assert "narrative" not in unmarked
    assert "shared MO phases" in unmarked


def test_trace_reads_the_ts_column_not_created_at() -> None:
    """ns_events timestamps rows `ts`.

    Ordering by ``created_at`` raises inside ``_safe``, which returns ``[]`` —
    indistinguishable from a case with no recorded events. This shipped once;
    the assertion is on the column name because no amount of fixture data can
    catch a query that never runs.
    """
    from src.api.enterprise import presenters

    steps = presenters.trace_steps(
        [
            {"event_type": "case_ingested", "ts": "2026-09-01T10:00:00Z", "payload": {}},
            {"event_type": "cases_linked", "ts": "2026-09-01T10:00:02Z", "payload": {}},
        ]
    )
    assert [s["name"] for s in steps] == ["case_ingested", "cases_linked"]
    assert steps[0]["duration_ms"] == 2000
    # Last step has nothing to measure against and must not guess.
    assert steps[1]["duration_ms"] == 0

    ordered_by: list[tuple[str, str]] = []
    supabase = _table_client({"fraud_cases": [CASE_ROWS[0]]}, order_log=ordered_by)
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        assert client.get("/enterprise/cases/case-a").status_code == 200

    ns_event_sorts = [column for table, column in ordered_by if table == "ns_events"]
    assert ns_event_sorts, "the trace query never ran"
    assert ns_event_sorts == ["ts"]


def test_unknown_campaign_detail_is_404() -> None:
    """A missing campaign is a 404, not an empty shell that looks approvable."""
    supabase = _table_client({"campaigns": []})
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/campaigns/nope")

    assert response.status_code == 404


def test_campaign_detail_survives_absent_v2_tables() -> None:
    """The live database is in exactly this state today: degrade, never 500."""
    supabase = MagicMock()
    supabase.table.side_effect = RuntimeError("relation does not exist")
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/campaigns/camp-1")

    assert response.status_code == 404
