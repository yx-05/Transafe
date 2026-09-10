"""Unit tests for the v2 Enterprise Console REST API (governance endpoints).

Everything external is mocked: no Supabase, no LLM, no API keys. The focus is
the campaign decision gate — approve and reject — because that gate is what
makes autonomous discovery safe to ship.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from src.api.enterprise.router import (
    APPROVABLE_STATUSES,
    REJECTABLE_STATUSES,
    _eval_passes,
)

client = TestClient(app)

REJECT_URL = "/enterprise/campaigns/camp-1/reject"


def _client_returning(rows: list[dict[str, object]]) -> MagicMock:
    """Build a Supabase mock whose campaign SELECT yields ``rows``."""
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = rows
    return supabase


def _error_message(response: object) -> str:
    """Read the error text out of the app-wide ``{success, data, error}`` envelope."""
    body = response.json()  # type: ignore[attr-defined]
    return str(body.get("error", {}).get("message", body.get("detail", "")))


def test_reject_route_is_mounted() -> None:
    """The route exists on the live app under /enterprise, with no /api segment."""
    paths = app.openapi()["paths"]
    assert "/enterprise/campaigns/{campaign_id}/reject" in paths
    assert not any(p.startswith("/enterprise/api/") for p in paths)


# ── eval pass pairing ──────────────────────────────────────────────────────
#
# One press of RUN EVAL must produce a before/after pair scored against two
# different core versions. A single unpinned pass per press scores both sides
# against whatever is published *now*, so the delta is structurally always
# zero — the chart then shows two identical bars, which is worse than showing
# nothing because it looks like the system failed to learn.


def _version_rows(*versions: tuple[int, str, str]) -> list[dict[str, object]]:
    """Build registry rows as ``list_artifact_versions`` returns them."""
    return [
        {"version": v, "content": content, "status": status}
        for v, content, status in versions
    ]


def test_eval_passes_pins_before_and_after_to_distinct_versions() -> None:
    """Two published versions yield a before pass and an after pass."""
    rows = _version_rows(
        (7, "R-1: learned body", "PUBLISHED"),
        (6, "R-1: baseline body", "PUBLISHED"),
    )
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        return_value=rows,
    ):
        passes = _eval_passes("manual")

    assert len(passes) == 2
    before, after = passes
    assert before[0] == "before · core v6"
    assert before[1] == "R-1: baseline body"
    assert before[2] == 6
    assert after[0] == "after · core v7"
    assert after[1] == "R-1: learned body"
    assert after[2] == 7


def test_eval_passes_returns_before_first_so_latest_pairs_them_correctly() -> None:
    """The before pass must be listed first.

    ``/eval/latest`` reads the two newest ``eval_runs`` rows and calls the
    older one "before". The rows are written in list order, so listing the
    after pass first would invert the chart and show learning running
    backwards.
    """
    rows = _version_rows(
        (7, "new", "PUBLISHED"),
        (6, "old", "PUBLISHED"),
    )
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        return_value=rows,
    ):
        passes = _eval_passes("manual")

    assert passes[0][2] == 6
    assert passes[-1][2] == 7


def test_eval_passes_ignores_unpublished_versions() -> None:
    """Drafts must not be scored as if they were deployed."""
    rows = _version_rows(
        (9, "draft", "DRAFT"),
        (7, "live", "PUBLISHED"),
        (6, "previous", "PUBLISHED"),
    )
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        return_value=rows,
    ):
        passes = _eval_passes("manual")

    assert [p[2] for p in passes] == [6, 7]


def test_eval_passes_single_version_runs_a_baseline() -> None:
    """One version means nothing to compare — one pass, not a fake delta."""
    rows = _version_rows((6, "only", "PUBLISHED"))
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        return_value=rows,
    ):
        passes = _eval_passes("manual")

    assert len(passes) == 1
    assert passes[0][0] == "baseline · core v6"
    assert passes[0][2] == 6


def test_eval_passes_with_no_versions_scores_without_core_rules() -> None:
    """An un-migrated database must still be evaluable, not raise."""
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        return_value=[],
    ):
        passes = _eval_passes("manual")

    assert len(passes) == 1
    assert passes[0] == ("manual", None, None)


def test_eval_passes_survives_a_registry_failure() -> None:
    """A registry outage degrades to a single unpinned pass."""
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        side_effect=RuntimeError("registry down"),
    ):
        passes = _eval_passes("manual")

    assert passes == [("manual", None, None)]


def test_eval_passes_prefixes_a_custom_label() -> None:
    """A caller-supplied label survives into the row, so runs stay traceable."""
    rows = _version_rows(
        (7, "new", "PUBLISHED"),
        (6, "old", "PUBLISHED"),
    )
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        return_value=rows,
    ):
        passes = _eval_passes("red-team drill")

    assert passes[0][0] == "red-team drill · before · core v6"
    assert passes[1][0] == "red-team drill · after · core v7"


def test_eval_passes_treats_the_default_label_as_no_prefix() -> None:
    """The console posts ``{}``, which must read as a clean label, not "manual "."""
    rows = _version_rows(
        (7, "new", "PUBLISHED"),
        (6, "old", "PUBLISHED"),
    )
    with patch(
        "src.api.enterprise.router.registry.list_artifact_versions",
        return_value=rows,
    ):
        passes = _eval_passes("manual")

    assert passes[0][0].startswith("before")


def test_reject_and_approve_share_the_same_gate() -> None:
    """A campaign is rejectable exactly while it is still approvable."""
    assert REJECTABLE_STATUSES == APPROVABLE_STATUSES


def test_reject_campaign_persists_status_reason_and_decider() -> None:
    """A valid rejection writes REJECTED + reason + who/when in one update."""
    supabase = _client_returning(
        [{"id": "camp-1", "code": "SCAM-027", "status": "PENDING_VALIDATION"}]
    )
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock),
    ):
        response = client.post(
            REJECT_URL,
            json={"reason": "coincidental overlap, not one campaign", "rejected_by": "hui"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["campaign"]["status"] == "REJECTED"
    assert body["reject_reason"] == "coincidental overlap, not one campaign"

    update = supabase.table.return_value.update.call_args[0][0]
    assert update["status"] == "REJECTED"
    assert update["reject_reason"] == "coincidental overlap, not one campaign"
    # Same who/when convention as the approve handler.
    assert update["approved_by"] == "hui"
    assert update["approved_at"]


def test_reject_campaign_emits_campaign_rejected_event() -> None:
    """Screen D re-renders only on an event, so rejection must emit one."""
    supabase = _client_returning([{"id": "camp-1", "code": "SCAM-027", "status": "CANDIDATE"}])
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock) as mock_emit,
    ):
        response = client.post(REJECT_URL, json={"reason": "false positive"})

    assert response.status_code == 200
    mock_emit.assert_awaited_once()
    kwargs = mock_emit.await_args.kwargs
    assert kwargs["layer"] == "registry"
    assert kwargs["event_type"] == "campaign_rejected"
    assert kwargs["payload"]["campaign_id"] == "camp-1"
    assert kwargs["payload"]["status"] == "REJECTED"
    assert kwargs["payload"]["reason"] == "false positive"


@pytest.mark.parametrize(
    "payload",
    [{}, {"reason": ""}, {"reason": "   "}, {"reason": "\n\t "}, {"rejected_by": "hui"}],
)
def test_reject_campaign_requires_a_reason(payload: dict[str, str]) -> None:
    """A reasonless rejection is a 422 and persists nothing."""
    supabase = _client_returning([{"id": "camp-1", "code": "SCAM-027", "status": "CANDIDATE"}])
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock) as mock_emit,
    ):
        response = client.post(REJECT_URL, json=payload)

    assert response.status_code == 422
    supabase.table.return_value.update.assert_not_called()
    mock_emit.assert_not_awaited()


def test_reject_campaign_trims_the_reason() -> None:
    """Surrounding whitespace never reaches the audit column."""
    supabase = _client_returning([{"id": "camp-1", "code": "SCAM-027", "status": "CANDIDATE"}])
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock),
    ):
        response = client.post(REJECT_URL, json={"reason": "  duplicate of SCAM-019  "})

    assert response.status_code == 200
    assert response.json()["reject_reason"] == "duplicate of SCAM-019"


@pytest.mark.parametrize("status", ["APPROVED", "ACTIVE", "REJECTED", "SUPERSEDED", "ARCHIVED"])
def test_reject_campaign_conflicts_with_a_recorded_decision(status: str) -> None:
    """A decision already taken is a 409, never a silent overwrite."""
    supabase = _client_returning([{"id": "camp-1", "code": "SCAM-027", "status": status}])
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock) as mock_emit,
    ):
        response = client.post(REJECT_URL, json={"reason": "changed my mind"})

    assert response.status_code == 409
    assert status in _error_message(response)
    supabase.table.return_value.update.assert_not_called()
    mock_emit.assert_not_awaited()


def test_reject_unknown_campaign_returns_404() -> None:
    """An unknown campaign id is a 404."""
    supabase = _client_returning([])
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock),
    ):
        response = client.post("/enterprise/campaigns/nope/reject", json={"reason": "n/a"})

    assert response.status_code == 404


def test_reject_campaign_fails_cleanly_when_the_write_fails() -> None:
    """An unapplied migration produces a legible 503, not a stack trace."""
    supabase = _client_returning([{"id": "camp-1", "code": "SCAM-027", "status": "CANDIDATE"}])
    supabase.table.return_value.update.side_effect = RuntimeError("relation does not exist")
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock) as mock_emit,
    ):
        response = client.post(REJECT_URL, json={"reason": "false positive"})

    assert response.status_code == 503
    assert "rejection" in _error_message(response)
    mock_emit.assert_not_awaited()


def test_reject_campaign_survives_an_unreadable_campaigns_table() -> None:
    """A missing table degrades to 404, never a 500."""
    supabase = MagicMock()
    supabase.table.side_effect = RuntimeError("relation does not exist")
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock),
    ):
        response = client.post(REJECT_URL, json={"reason": "false positive"})

    assert response.status_code == 404


def test_approve_campaign_still_emits_campaign_approved() -> None:
    """Approve keeps its event after the shared-loader refactor."""
    supabase = _client_returning(
        [{"id": "camp-1", "code": "SCAM-027", "status": "PENDING_VALIDATION"}]
    )
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock) as mock_emit,
        patch(
            "src.api.enterprise.router._run_approval_pipeline", new_callable=AsyncMock
        ),
    ):
        response = client.post(
            "/enterprise/campaigns/camp-1/approve",
            json={"approved_by": "hui", "generalise": False},
        )

    assert response.status_code == 200
    assert response.json()["campaign"]["status"] == "APPROVED"
    assert mock_emit.await_args.kwargs["event_type"] == "campaign_approved"


def test_approve_conflicts_with_a_rejected_campaign() -> None:
    """A rejected campaign cannot be approved back into compilation."""
    supabase = _client_returning([{"id": "camp-1", "code": "SCAM-027", "status": "REJECTED"}])
    with (
        patch("src.api.enterprise.router.get_supabase_client", return_value=supabase),
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock),
    ):
        response = client.post("/enterprise/campaigns/camp-1/approve", json={})

    assert response.status_code == 409


# --------------------------------------------------------------------------
# Live-contract regressions: shapes the console actually sends and reads.
# Each of these was a real mismatch found by driving the running server, where
# the client's fixture fallback made the failure look identical to success.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("body", [{"version": 2}, {"to_version": 2}])
def test_rollback_accepts_the_console_version_field(body: dict[str, int]) -> None:
    """``api.rollbackArtifact`` sends ``{version}``; ``to_version`` still works."""
    with (
        patch("src.api.enterprise.router.registry.rollback_artifact") as mock_rollback,
        patch("src.api.enterprise.router.emit_event", new_callable=AsyncMock),
    ):
        mock_rollback.return_value = {"name": "phone_agent_core", "version": 5}
        response = client.post("/enterprise/artifacts/phone_agent_core/rollback", json=body)

    assert response.status_code == 200
    assert mock_rollback.call_args.args[1] == 2


@pytest.mark.parametrize("body", [{}, {"version": 0}, {"version": -1}])
def test_rollback_rejects_a_missing_or_invalid_version(body: dict[str, int]) -> None:
    """Rolling back to nothing is refused rather than guessed."""
    with patch("src.api.enterprise.router.registry.rollback_artifact") as mock_rollback:
        response = client.post("/enterprise/artifacts/phone_agent_core/rollback", json=body)

    assert response.status_code == 422
    mock_rollback.assert_not_called()


def test_get_artifact_version_accepts_latest() -> None:
    """``api.getArtifact`` defaults to 'latest'; it must not 422."""
    with (
        patch("src.api.enterprise.router.registry.get_artifact") as mock_get,
        patch("src.api.enterprise.router.registry.get_artifact_diff") as mock_diff,
    ):
        mock_get.return_value = {"name": "phone_agent_core", "version": 4}
        mock_diff.return_value = {"current": {"version": 4}, "previous": None, "diff": []}
        response = client.get("/enterprise/artifacts/phone_agent_core/latest")

    assert response.status_code == 200
    assert mock_diff.call_args.args[1] == 4


def test_get_artifact_version_rejects_a_nonsense_version() -> None:
    """A non-numeric, non-'latest' version is a legible 400, not a 500."""
    with patch("src.api.enterprise.router.registry.get_artifact_diff") as mock_diff:
        response = client.get("/enterprise/artifacts/phone_agent_core/banana")

    assert response.status_code == 400
    mock_diff.assert_not_called()


def test_get_artifact_latest_with_nothing_published_is_404() -> None:
    """'latest' on an empty registry is an honest 404, not a crash."""
    with (
        patch("src.api.enterprise.router.registry.get_artifact", return_value=None),
        patch("src.api.enterprise.router.registry.get_artifact_diff", return_value=None),
    ):
        response = client.get("/enterprise/artifacts/unknown_artifact/latest")

    assert response.status_code == 404


def test_overview_supplies_the_keys_the_console_counter_strip_reads() -> None:
    """adapters.normaliseOverview reads specific key names in specific layers.

    It looks for `cases`/`open` under `case`, `unrecognised`/`campaigns` under
    `discovery`, and `core_version` under `registry`. Publishing only
    `cases_total` etc. left every counter at 0 while the system was working.
    """
    supabase = MagicMock()

    def _table(name: str) -> MagicMock:
        rows: list[dict[str, object]] = {
            "fraud_cases": [
                {"id": "c1", "status": "OPEN", "created_at": "2026-09-10T00:00:00Z"},
                {"id": "c2", "status": "CLOSED", "created_at": "2026-09-10T00:00:00Z"},
                {"id": "c3", "status": "open", "created_at": "2026-09-10T00:00:00Z"},
            ],
            "case_entities": [{"id": "e1"}],
            "case_links": [{"id": "l1"}],
            "campaigns": [{"id": "camp-1", "status": "ACTIVE"}],
            "artifacts": [
                {"id": "a1", "tier": "core", "status": "PUBLISHED", "version": 7},
                {"id": "a2", "tier": "core", "status": "SUPERSEDED", "version": 3},
                {"id": "a3", "tier": "pack", "status": "PUBLISHED", "version": 9},
            ],
        }.get(name, [])
        # A chainable stub: select/order/eq/limit all return the same builder,
        # so the mock does not depend on the exact call order in the router.
        builder = MagicMock()
        builder.select.return_value = builder
        builder.order.return_value = builder
        builder.eq.return_value = builder
        builder.limit.return_value = builder
        builder.execute.return_value.data = rows
        return builder

    supabase.table.side_effect = _table
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/overview")

    assert response.status_code == 200
    layers = response.json()["layers"]
    assert layers["case"]["cases"] == 3
    assert layers["case"]["open"] == 2  # CLOSED excluded, lower-case 'open' counted
    assert layers["discovery"]["campaigns"] == 1
    assert "unrecognised" in layers["discovery"]
    # Newest core version, not the pack's higher number.
    assert layers["registry"]["core_version"] == 7


def test_overview_degrades_to_zeroes_without_the_v2_migration() -> None:
    """Every counter key is still present (and 0) when the tables are absent."""
    supabase = MagicMock()
    supabase.table.side_effect = RuntimeError("relation does not exist")
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get("/enterprise/overview")

    assert response.status_code == 200
    layers = response.json()["layers"]
    assert layers["case"]["cases"] == 0
    assert layers["case"]["open"] == 0
    assert layers["discovery"]["unrecognised"] == 0
    assert layers["registry"]["core_version"] == 0
