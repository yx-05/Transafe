"""Unit tests for the demo preflight checks.

Everything external is mocked: no Supabase, no API key, no network. The two
properties worth protecting are that a check **never raises** (a readiness
check that throws tells the operator nothing) and that it **never reports a
false failure** (an alarm that lies is one the operator learns to ignore).
"""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import pytest

from src.enterprise import preflight

# ── Supabase ────────────────────────────────────────────────────────────────


@patch("src.db.vector_store.get_supabase_client")
def test_supabase_check_passes_when_it_can_read(mock_client):
    table = mock_client.return_value.table.return_value
    table.select.return_value.limit.return_value.execute.return_value.data = []

    assert preflight._check_supabase()["status"] == "pass"


@patch("src.db.vector_store.get_supabase_client")
def test_supabase_check_reports_a_failure_instead_of_raising(mock_client):
    """An unreachable database must come back as a verdict, not a traceback."""
    mock_client.side_effect = RuntimeError("Supabase client is not initialized.")

    result = preflight._check_supabase()

    assert result["status"] == "fail"
    assert "not initialized" in result["detail"]


# ── Schema ──────────────────────────────────────────────────────────────────


@patch("src.db.vector_store.get_supabase_client")
def test_schema_check_probes_without_assuming_an_id_column(mock_client):
    """Probe with ``select("*")``, never ``select("id")``.

    ``campaign_cases`` is a join table keyed on (campaign_id, case_id) with no
    ``id`` column, so asking for one raises 42703 and the table is reported
    missing while it is present and working. A false NOT READY is worse than no
    check at all.
    """
    supabase = MagicMock()
    mock_client.return_value = supabase

    preflight._check_v2_schema()

    for call in supabase.table.return_value.select.call_args_list:
        assert call.args == ("*",)


@patch("src.db.vector_store.get_supabase_client")
def test_schema_check_names_only_the_missing_tables(mock_client):
    supabase = MagicMock()
    mock_client.return_value = supabase

    # Only eval_runs fails; every other table reads fine.
    def _table(name):
        if name == "eval_runs":
            raise Exception("relation does not exist")
        return MagicMock()

    supabase.table.side_effect = _table

    result = preflight._check_v2_schema()

    assert result["status"] == "fail"
    assert result["missing"] == ["eval_runs"]
    assert "campaigns" not in result["detail"]


# ── MCP server ──────────────────────────────────────────────────────────────


def test_mcp_check_passes_with_the_full_tool_surface():
    result = preflight._check_mcp_server()
    assert result["status"] == "pass"
    assert result["tools"] == preflight.EXPECTED_MCP_TOOLS


@patch("mcp.server.TOOL_DEFINITIONS", [{"name": "only_one"}])
def test_mcp_check_fails_when_a_tool_goes_missing():
    """The count is the point: a silently removed tool breaks Act 5."""
    result = preflight._check_mcp_server()

    assert result["status"] == "fail"
    assert "only_one" not in result["detail"]
    assert result["tools"] == 1


@patch.dict("sys.modules", {"mcp.server": None})
def test_mcp_check_reports_an_import_error_instead_of_raising():
    result = preflight._check_mcp_server()
    assert result["status"] == "fail"


# ── Verdict aggregation ─────────────────────────────────────────────────────


def _patched(**statuses: str) -> list:
    """Build the patch set for ``run_preflight`` with per-check statuses.

    Returns a list of patchers rather than a nested ``with`` pyramid, which is
    both unreadable and a lint error at this width.
    """
    defaults = {
        "supabase": "pass",
        "v2_schema": "pass",
        "core_artifact": "pass",
        "campaigns": "info",
        "mcp_server": "pass",
        "llm": "pass",
    }
    defaults.update(statuses)
    return [
        patch.object(
            preflight,
            f"_check_{name}",
            return_value=preflight._result(name, status, "detail"),
        )
        for name, status in defaults.items()
    ]


async def _run_with(**statuses: str) -> dict:
    with contextlib.ExitStack() as stack:
        for patcher in _patched(**statuses):
            stack.enter_context(patcher)
        return await preflight.run_preflight()


@pytest.mark.asyncio
async def test_no_failures_means_ready():
    result = await _run_with()

    assert result["ok"] is True
    assert result["summary"] == "Ready"


@pytest.mark.asyncio
async def test_a_warning_does_not_block_a_demo():
    """``warn`` must leave ``ok`` True.

    The thinking-model warning and the unpublished-core-skill case are both
    demos you can still give. Treating them as failure would make the verdict
    cry wolf, and the operator would stop reading it.
    """
    result = await _run_with(core_artifact="warn")

    assert result["ok"] is True
    assert "warning" in result["summary"]


@pytest.mark.asyncio
async def test_any_failure_makes_the_verdict_not_ready():
    result = await _run_with(supabase="fail")

    assert result["ok"] is False
    assert "NOT READY" in result["summary"]
    assert "supabase" in result["summary"]


@pytest.mark.asyncio
async def test_every_check_returns_a_status():
    """A check with no ``status`` would render as a blank row in the console."""
    result = await preflight.run_preflight()

    assert result["checks"]
    for check in result["checks"]:
        assert check["name"]
        assert check["status"] in {"pass", "warn", "fail", "info"}
        assert check["detail"]
