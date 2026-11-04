"""Unit tests for ``GET /enterprise/mcp/log`` — the Screen G data source.

Screen G lists live audit rows and re-renders the same payload under a
different role so the redaction difference is visible. That demo only works if
the endpoint (a) survives the migration not being applied, and (b) labels each
row with what its role does *not* receive.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

URL = "/enterprise/mcp/log"

ROWS = [
    {
        "id": 2,
        "ts": "2026-09-10T10:00:01+00:00",
        "caller": "codebuddy",
        "role": "public",
        "tool": "get_case_evidence",
        "params": {"outcome": "denied", "case_id": "case-1"},
        "latency_ms": 3,
        "citations": None,
    },
    {
        "id": 1,
        "ts": "2026-09-10T10:00:00+00:00",
        "caller": "codebuddy",
        "role": "fraud_ops",
        "tool": "ask_transafe",
        "params": {"outcome": "ok", "question": "what is active?"},
        "latency_ms": 812,
        "citations": ["SCAM-027"],
    },
]


def _supabase_returning(rows: list[dict]) -> MagicMock:
    """Build a Supabase mock whose ordered/limited SELECT yields ``rows``."""
    supabase = MagicMock()
    chain = supabase.table.return_value.select.return_value
    chain.order.return_value.limit.return_value.execute.return_value.data = rows
    chain.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = rows
    return supabase


def _entries(response) -> list[dict]:
    """Unwrap the app-wide ``{success, data}`` envelope if one is present."""
    body = response.json()
    payload = body.get("data", body) if isinstance(body, dict) else body
    return payload["entries"]


def test_route_is_mounted_without_an_api_segment() -> None:
    paths = app.openapi()["paths"]
    assert "/enterprise/mcp/log" in paths
    assert "/enterprise/api/mcp/log" not in paths


def test_returns_entries_with_outcome_and_redacted_fields() -> None:
    with patch(
        "src.api.enterprise.router.get_supabase_client",
        return_value=_supabase_returning(ROWS),
    ):
        response = client.get(URL)

    assert response.status_code == 200
    entries = _entries(response)
    assert len(entries) == 2

    denied, ok = entries
    assert denied["outcome"] == "denied"
    assert ok["outcome"] == "ok"
    # The public row must advertise that it withheld far more than the
    # fraud_ops row — this is what makes the role selector legible.
    assert len(denied["redacted_fields"]) > len(ok["redacted_fields"])
    assert ok["redacted_fields"] == []
    assert "transcripts" in denied["redacted_fields"]


def test_role_filter_is_passed_through() -> None:
    supabase = _supabase_returning([ROWS[0]])
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get(URL, params={"role": "public", "limit": 10})

    assert response.status_code == 200
    supabase.table.return_value.select.return_value.eq.assert_any_call("role", "public")


def test_degrades_to_empty_when_migration_not_applied() -> None:
    supabase = MagicMock()
    supabase.table.side_effect = Exception("relation mcp_access_log does not exist")
    with patch("src.api.enterprise.router.get_supabase_client", return_value=supabase):
        response = client.get(URL)

    assert response.status_code == 200
    assert _entries(response) == []


def test_as_role_applies_the_redaction_lens() -> None:
    """``role`` filters rows; ``as_role`` redacts them. Different questions.

    Without ``as_role`` this endpoint serves the internal console and returns
    the operator view. With it, the caller sees exactly what an external MCP
    caller holding that role would receive.
    """
    rows = [
        {
            "id": 1,
            "ts": "2026-09-10T10:00:00+00:00",
            "caller": "codebuddy",
            "role": "fraud_ops",
            "tool": "check_indicator",
            "params": {"outcome": "ok", "value": "5501-9090-1111"},
            "latency_ms": 9,
            "citations": ["SCAM-027"],
        }
    ]

    with patch(
        "src.api.enterprise.router.get_supabase_client",
        return_value=_supabase_returning(rows),
    ):
        operator = client.get(URL)
        lensed = client.get(URL, params={"as_role": "public"})

    # Operator view keeps the arguments.
    assert _entries(operator)[0]["params"]["value"] == "5501-9090-1111"
    # Lensed view does not.
    lensed_entry = _entries(lensed)[0]
    assert lensed_entry["params"] == {"outcome": "ok"}
    assert lensed_entry["citations"] is None
    assert "5501-9090-1111" not in lensed.text
    assert "SCAM-027" not in lensed.text
    # Still legible as an access record.
    assert lensed_entry["tool"] == "check_indicator"
    assert lensed_entry["outcome"] == "ok"


def test_advertises_the_role_vocabulary() -> None:
    """The console role selector needs the server's list, not a hardcoded one."""
    with patch(
        "src.api.enterprise.router.get_supabase_client",
        return_value=_supabase_returning([]),
    ):
        body = client.get(URL).json()

    payload = body.get("data", body)
    assert {"fraud_ops", "compliance", "public"} <= set(payload["roles"])
