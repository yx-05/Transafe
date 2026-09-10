"""Unit tests for the presenter wiring behind Screens B, C and D.

These endpoints cannot be verified against the live database: every v2 table
(``case_mo``, ``entities``, ``case_links``, ``campaigns``, ``campaign_cases``,
``artifacts``, ``ns_events``) is currently absent from it, and the router's
``_safe`` turns a missing relation into an empty ``200``. Until the migration is
applied these fakes are the only thing standing between the console and a
screen reading "Case #0 / — / UNKNOWN".

Everything external is mocked: no Supabase, no LLM, no API keys.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _table_client(
    tables: dict[str, list[dict[str, object]]],
    order_log: list[tuple[str, str]] | None = None,
) -> MagicMock:
    """A Supabase mock that dispatches per table name.

    Every builder method returns the same builder, so any chain of
    select/eq/in_/gte/order/limit/range/or_ terminates at the rows registered
    for that table name.

    ``order_log``, when supplied, collects ``(table, column)`` for every
    ``.order()`` call. Fixture rows cannot catch a query that names a column
    the database does not have — only the sort key can.
    """
    supabase = MagicMock()

    def _table(name: str) -> MagicMock:
        builder = MagicMock()
        for method in ("select", "eq", "in_", "gte", "limit", "range", "or_"):
            getattr(builder, method).return_value = builder

        def _order(column: str, **_kwargs: object) -> MagicMock:
            if order_log is not None:
                order_log.append((name, column))
            return builder

        builder.order.side_effect = _order
        builder.execute.return_value.data = tables.get(name, [])
        return builder

    supabase.table.side_effect = _table
    return supabase


CASE_ROWS: list[dict[str, object]] = [
    {"id": "case-a", "risk_tier": "HIGH", "risk_score": 88, "created_at": "2026-09-01T10:00:00Z"},
    {"id": "case-b", "risk_tier": "MEDIUM", "risk_score": 55, "created_at": "2026-09-01T11:00:00Z"},
]


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
