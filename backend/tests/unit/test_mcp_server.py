"""Unit tests for the MCP server tool layer (04_mcp_gateway.md §3 Testing).

No transport is started and no API key is required: ``mcp.server`` is written
so the tool layer is importable and exercisable on its own. Supabase, the LLM
and the audit sink are all mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp.redaction import project_log_entry
from mcp.server import (
    RATE_LIMIT_PER_MINUTE,
    TOOL_DEFINITIONS,
    _looks_like_uuid,
    check_rate_limit,
    handle_rpc,
    handle_tool_call,
    list_tool_definitions,
    log_mcp_access,
    rate_limit_remaining,
    reset_rate_limits,
    resolve_tool_name,
    tool_check_indicator,
    tool_get_campaign,
    tool_list_active_campaigns,
    tool_query_mcp_log,
    tool_query_stats,
)


@pytest.fixture(autouse=True)
def _clean_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def audit():
    """Patch the audit sink and ns_event emitter, yielding the log mock."""
    with (
        patch("mcp.server.log_mcp_access") as log,
        patch("mcp.server.emit_event", new_callable=AsyncMock) as emit,
    ):
        log.return_value = True
        yield log, emit


# ── Tools ────────────────────────────────────────────────────────────────────
@patch("mcp.server.get_supabase_client")
def test_tool_list_active_campaigns_redacts(mock_client):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    mock_table.select.return_value.in_.return_value.execute.return_value.data = [
        {"id": "c1", "code": "SCAM-027", "user_id": "u1"}
    ]

    result = tool_list_active_campaigns("compliance")

    assert result["campaigns"][0]["user_id"] == "[REDACTED]"
    assert result["campaigns"][0]["code"] == "SCAM-027"


@patch("mcp.server.get_supabase_client")
def test_tool_check_indicator_known(mock_client):
    """NOTE: 04_mcp_gateway.md's version of this test calls the tool with two
    positional arguments against a three-argument signature and cannot run as
    written. The assertions are kept verbatim; the call supplies the role.
    """
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "e1", "case_count": 5, "first_seen": "2026-01-01", "last_seen": "2026-01-10"}
    ]
    mock_table.select.return_value.eq.return_value.execute.return_value.data = []
    mock_table.select.return_value.in_.return_value.execute.return_value.data = []

    result = tool_check_indicator("fraud_ops", "ACCOUNT", "1592-3456")

    assert result["known"] is True
    assert result["case_count"] == 5


@patch("mcp.server.get_supabase_client")
def test_tool_check_indicator_unknown(mock_client):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    result = tool_check_indicator("fraud_ops", "ACCOUNT", "0000-0000")

    assert result["known"] is False


def test_tool_check_indicator_rejects_unknown_type():
    result = tool_check_indicator("fraud_ops", "TELEPATHY", "x")
    assert result["known"] is False
    assert "error" in result


@patch("mcp.server.get_supabase_client")
def test_tool_get_campaign_not_found(mock_client):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    mock_table.select.return_value.eq.return_value.execute.return_value.data = []

    result = tool_get_campaign("fraud_ops", "missing")

    assert result["error"] == "Campaign not found"


CAMPAIGN_UUID = "21de699c-c84c-48d4-af20-dcc937983873"


def _campaign_client(campaign_row):
    """Supabase double recording the ``(column, value)`` each table was filtered by.

    A single shared ``MagicMock`` cannot express this test: the point is that
    ``campaigns`` and its two child tables are filtered by *different* values,
    so each table needs its own recorder.
    """
    filters: dict[str, tuple[str, object]] = {}
    tables: dict[str, MagicMock] = {}

    def make_table(name: str) -> MagicMock:
        table = MagicMock()

        def eq(column, value):
            filters[name] = (column, value)
            chain = MagicMock()
            chain.execute.return_value.data = (
                ([campaign_row] if campaign_row else []) if name == "campaigns" else []
            )
            return chain

        table.select.return_value.eq.side_effect = eq
        return table

    client = MagicMock()
    client.table.side_effect = lambda name: tables.setdefault(name, make_table(name))
    return client, filters


@patch("mcp.server.get_supabase_client")
def test_get_campaign_accepts_human_code(mock_client):
    """``SCAM-001`` is the identifier Screens C/D show, so it must be usable.

    ``campaigns.id`` is a uuid column: filtering it by a code raised 22P02 out
    of the one unguarded call in the function, which also made the
    ``Campaign not found`` branch unreachable for exactly the malformed inputs
    that needed it.
    """
    client, filters = _campaign_client({"id": CAMPAIGN_UUID, "code": "SCAM-001"})
    mock_client.return_value = client

    result = tool_get_campaign("fraud_ops", "SCAM-001")

    assert "error" not in result
    assert filters["campaigns"] == ("code", "SCAM-001")


@patch("mcp.server.get_supabase_client")
def test_get_campaign_still_accepts_uuid(mock_client):
    client, filters = _campaign_client({"id": CAMPAIGN_UUID, "code": "SCAM-001"})
    mock_client.return_value = client

    tool_get_campaign("fraud_ops", CAMPAIGN_UUID)

    assert filters["campaigns"] == ("id", CAMPAIGN_UUID)


@patch("mcp.server.get_supabase_client")
def test_child_lookups_use_resolved_uuid_not_the_argument(mock_client):
    """The regression this guards is silent, which is why it needs a test.

    ``campaign_cases.campaign_id`` and ``artifacts.campaign_id`` are uuid
    columns as well, and both lookups sit inside ``try/except`` blocks that
    render failure as ``[]``. Passing the code straight through would raise
    22P02 *inside* those guards, and the campaign would come back with no cases
    and no artifacts — looking merely quiet rather than broken.
    """
    client, filters = _campaign_client({"id": CAMPAIGN_UUID, "code": "SCAM-001"})
    mock_client.return_value = client

    tool_get_campaign("fraud_ops", "SCAM-001")

    assert filters["campaign_cases"] == ("campaign_id", CAMPAIGN_UUID)
    assert filters["artifacts"] == ("campaign_id", CAMPAIGN_UUID)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (CAMPAIGN_UUID, True),
        ("21DE699C-C84C-48D4-AF20-DCC937983873", True),
        ("SCAM-001", False),
        ("missing", False),
        ("", False),
        (None, False),
    ],
)
def test_looks_like_uuid(value, expected):
    assert _looks_like_uuid(value) is expected


@patch("mcp.server.get_supabase_client")
def test_tool_query_stats_degrades_when_migration_missing(mock_client):
    """Read paths must render 0, never raise, before the v2 migration lands."""
    mock_client.return_value.table.side_effect = Exception("relation does not exist")

    result = tool_query_stats("public")

    assert result["aggregate"]["case_count"] == 0
    assert result["aggregate"]["campaigns_total"] == 0
    # The counters survive redaction for the most restrictive role — an
    # aggregate count is not the resource it counts.
    assert result["aggregate"]["available"] is True


@patch("mcp.server.get_supabase_client")
def test_tool_query_stats_survives_supabase_outage(mock_client):
    mock_client.side_effect = Exception("no credentials")
    assert tool_query_stats("public") == {"aggregate": {"available": False}}


@patch("mcp.server.get_supabase_client")
def test_tool_query_mcp_log_projects_by_role(mock_client):
    """Audit rows are whitelisted, not key-redacted.

    An unentitled key is *absent* rather than present-and-blanked: the row's
    ``params`` are the previous caller's free-form arguments, which can hold a
    secret under any key at all, so only a known-safe set is emitted.
    """
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    mock_table.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [  # noqa: E501
        {"id": 1, "caller": "codebuddy", "role": "fraud_ops", "tool": "get_campaign",
         "params": {"outcome": "ok", "campaign_id": "c1"}, "user_id": "u-secret"}
    ]

    result = tool_query_mcp_log("public")
    entry = result["entries"][0]

    assert result["count"] == 1
    assert "user_id" not in entry
    assert entry["params"] == {"outcome": "ok"}
    # Access metadata survives, so the row is still legible as an access record.
    assert entry["caller"] == "codebuddy"
    assert entry["tool"] == "get_campaign"
    assert entry["outcome"] == "ok"


def test_project_log_entry_withholds_free_form_params():
    row = {
        "id": 1,
        "ts": "2026-09-10T10:00:00+00:00",
        "caller": "codebuddy",
        "role": "fraud_ops",
        "tool": "check_indicator",
        "latency_ms": 9,
        "params": {"outcome": "ok", "value": "5501-9090-1111", "question": "who is Tan Ah Kow?"},
        "citations": ["SCAM-027"],
    }

    public = project_log_entry(row, "public")
    assert public["params"] == {"outcome": "ok"}
    assert public["citations"] is None
    assert public["citation_count"] == 1
    assert "5501-9090-1111" not in json.dumps(public)
    assert "Tan Ah Kow" not in json.dumps(public)

    full = project_log_entry(row, "fraud_ops")
    assert full["params"]["value"] == "5501-9090-1111"
    assert full["citations"] == ["SCAM-027"]


def test_project_log_entry_survives_a_malformed_row():
    """Audit rows are written by an exception-swallowing sink; assume nothing."""
    projected = project_log_entry({"caller": "x", "params": None, "citations": "oops"}, "public")
    assert projected["outcome"] is None
    assert projected["citation_count"] == 0
    assert projected["params"] == {"outcome": None}


# ── Rate limiting ────────────────────────────────────────────────────────────
def test_rate_limit_blocks_after_60():
    for _ in range(RATE_LIMIT_PER_MINUTE):
        assert check_rate_limit("test_caller") is True
    assert check_rate_limit("test_caller") is False


def test_rate_limit_is_per_caller():
    for _ in range(RATE_LIMIT_PER_MINUTE):
        check_rate_limit("noisy")
    assert check_rate_limit("noisy") is False
    assert check_rate_limit("quiet") is True


def test_rate_limit_remaining():
    assert rate_limit_remaining("fresh") == RATE_LIMIT_PER_MINUTE
    check_rate_limit("fresh")
    assert rate_limit_remaining("fresh") == RATE_LIMIT_PER_MINUTE - 1


async def test_rate_limited_call_returns_clean_error_not_exception(audit):
    log, _ = audit
    for _ in range(RATE_LIMIT_PER_MINUTE):
        check_rate_limit("flooder")

    result = await handle_tool_call("query_stats", {}, caller="flooder", role="fraud_ops")

    assert result["error"] == "rate_limit_exceeded"
    assert "60 calls per minute" in result["message"]
    assert result["retry_after_seconds"] == 60
    # The rejection is itself audited — this is the row an investigator needs.
    assert log.call_args.args[6] == "rate_limited"


# ── Audit log ────────────────────────────────────────────────────────────────
@patch("mcp.server.get_supabase_client")
def test_log_mcp_access_inserts_row(mock_client):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    log_mcp_access("codebuddy", "legal", "ask_transafe", {"q": "test"}, 340)

    mock_table.insert.assert_called_once()
    row = mock_table.insert.call_args[0][0]
    assert row["caller"] == "codebuddy"
    assert row["role"] == "legal"
    assert row["params"]["outcome"] == "ok"
    assert row["params"]["q"] == "test"


@patch("mcp.server.get_supabase_client")
def test_log_mcp_access_never_raises(mock_client):
    mock_client.side_effect = Exception("table missing")
    assert log_mcp_access("codebuddy", "legal", "ask_transafe", {}, 1) is False


@patch("mcp.server.get_supabase_client")
def test_log_mcp_access_flattens_citations(mock_client):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    log_mcp_access(
        "codebuddy", "legal", "ask_transafe", {}, 10,
        citations=[{"type": "campaign", "id": "SCAM-027"}],
    )

    assert mock_table.insert.call_args[0][0]["citations"] == ["SCAM-027"]


async def test_denied_call_is_audited(audit):
    """An audit log that only records successes is useless. Denials count."""
    log, emit = audit

    result = await handle_tool_call(
        "get_case_evidence", {"case_id": "c1"}, caller="partner", role="partner_bank"
    )

    assert result["error"] == "forbidden"
    assert log.call_args.args[6] == "denied"
    assert emit.await_args.kwargs["layer"] == "exposure"
    assert emit.await_args.kwargs["event_type"] == "mcp_call"
    assert emit.await_args.kwargs["severity"] == "warning"


async def test_unknown_tool_is_audited(audit):
    log, _ = audit
    result = await handle_tool_call("drop_all_tables", {}, role="fraud_ops")
    assert "Unknown tool" in result["error"]
    assert log.call_args.args[6] == "unknown_tool"


async def test_successful_call_is_audited_with_info_severity(audit):
    log, emit = audit
    with patch("mcp.server.tool_query_stats", return_value={"aggregate": {"case_count": 1}}):
        result = await handle_tool_call("query_stats", {}, role="compliance")

    assert result["aggregate"]["case_count"] == 1
    assert log.call_args.args[6] == "ok"
    assert emit.await_args.kwargs["severity"] == "info"
    assert emit.await_args.kwargs["payload"]["redacted"]
    assert emit.await_args.kwargs["payload"]["audit_persisted"] is True


async def test_failed_audit_write_is_visible_in_the_emitted_event(audit):
    """A swallowed audit write must not render as a healthy ``mcp_call``.

    ``log_mcp_access`` catches its own exceptions and returns ``False``. If
    ``_audit`` discards that return, Screen G paints an ordinary access-trail
    row for a call that left no durable audit record — traffic shown, nothing
    recorded, no error anywhere. That is the one failure a console selling an
    auditable trail cannot afford, so it is asserted rather than assumed.
    """
    log, emit = audit
    log.return_value = False

    with patch("mcp.server.tool_query_stats", return_value={"aggregate": {}}):
        result = await handle_tool_call("query_stats", {}, role="fraud_ops")

    # The caller is unaffected: audit failure never breaks the tool call.
    assert "error" not in result
    # But the event must not claim health the durable store cannot back.
    assert emit.await_args.kwargs["payload"]["audit_persisted"] is False
    assert emit.await_args.kwargs["severity"] == "critical"


async def test_audit_write_exception_also_marks_the_event(audit):
    """Same guarantee when the write raises rather than returning ``False``."""
    log, emit = audit
    log.side_effect = RuntimeError("cache invalidated by DDL")

    with patch("mcp.server.tool_query_stats", return_value={"aggregate": {}}):
        await handle_tool_call("query_stats", {}, role="fraud_ops")

    assert emit.await_args.kwargs["payload"]["audit_persisted"] is False
    assert emit.await_args.kwargs["severity"] == "critical"


@pytest.mark.parametrize(
    ("persisted", "outcome"),
    [(True, "ok"), (True, "denied"), (False, "ok"), (False, "denied")],
)
async def test_emitted_severity_is_always_in_the_real_vocabulary(
    audit, persisted: bool, outcome: str
) -> None:
    """Guard the blind spot that hid a bug in this very function.

    ``emit_event`` is mocked here, so a mocked emitter will happily accept any
    string. The real :func:`build_event` will not: it coerces an unrecognised
    severity to ``info``, which would render a lost audit row as the most
    benign thing on the feed. A test asserting ``severity == "error"`` passed
    for exactly that reason while the live path silently downgraded it.

    So assert against the shipped vocabulary rather than a literal, and this
    test fails if the two ever drift apart again.
    """
    from src.enterprise.events import VALID_SEVERITIES

    log, emit = audit
    log.return_value = persisted
    tool = "get_case_evidence" if outcome == "denied" else "query_stats"
    role = "partner_bank" if outcome == "denied" else "fraud_ops"

    with patch("mcp.server.tool_query_stats", return_value={"aggregate": {}}):
        await handle_tool_call(tool, {"case_id": "c1"}, caller="probe", role=role)

    severity = emit.await_args.kwargs["severity"]
    assert severity in VALID_SEVERITIES, f"{severity!r} would be coerced to 'info'"
    assert emit.await_args.kwargs["payload"]["audit_persisted"] is persisted


async def test_tool_exception_is_audited_and_not_raised(audit):
    log, _ = audit
    with patch("mcp.server.tool_query_stats", side_effect=RuntimeError("boom")):
        result = await handle_tool_call("query_stats", {}, role="fraud_ops")

    assert result["error"] == "boom"
    assert log.call_args.args[6] == "error"


async def test_missing_argument_is_audited_not_raised(audit):
    log, _ = audit
    result = await handle_tool_call("get_campaign", {}, role="fraud_ops")
    assert "Missing required argument" in result["error"]
    assert log.call_args.args[6] == "error"


# ── Aliases and schemas ──────────────────────────────────────────────────────
def test_resolve_tool_name_handles_both_namings():
    assert resolve_tool_name("query_campaign") == "get_campaign"
    assert resolve_tool_name("query_case") == "get_case_evidence"
    assert resolve_tool_name("query_artifact") == "get_artifact"
    assert resolve_tool_name("get_campaign") == "get_campaign"
    assert resolve_tool_name("query_stats") == "query_stats"


async def test_alias_dispatches_to_canonical_tool(audit):
    with patch("mcp.server.tool_get_campaign", return_value={"id": "c1"}) as tool:
        result = await handle_tool_call(
            "query_campaign", {"campaign_id": "c1"}, role="fraud_ops"
        )
    tool.assert_called_once_with("fraud_ops", "c1")
    assert result["id"] == "c1"


def test_tool_definitions_are_well_formed():
    names = {definition["name"] for definition in list_tool_definitions()}
    assert {"ask_transafe", "query_stats", "query_mcp_log"} <= names
    for definition in TOOL_DEFINITIONS:
        assert definition["description"]
        assert definition["inputSchema"]["type"] == "object"


# ── JSON-RPC layer (no transport) ────────────────────────────────────────────
async def test_rpc_initialize():
    response = await handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response["result"]["serverInfo"]["name"] == "transafe"


async def test_rpc_tools_list():
    response = await handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(response["result"]["tools"]) == len(TOOL_DEFINITIONS)


async def test_rpc_notification_gets_no_reply():
    assert await handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


async def test_rpc_unknown_method():
    response = await handle_rpc({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert response["error"]["code"] == -32601


async def test_rpc_tools_call_wraps_result(audit):
    with patch("mcp.server.tool_query_stats", return_value={"aggregate": {"case_count": 2}}):
        response = await handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "query_stats", "arguments": {}},
            },
            role="fraud_ops",
        )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["aggregate"]["case_count"] == 2
    assert response["result"]["isError"] is False


async def test_rpc_refuses_role_escalation(audit):
    """A tools/call argument must never widen the process-level entitlement."""
    log, _ = audit
    with patch("mcp.server.tool_query_stats", return_value={"aggregate": {}}):
        await handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "query_stats",
                    "arguments": {"role": "fraud_ops"},
                },
            },
            role="public",
        )
    assert log.call_args.args[1] == "public"


async def test_rpc_allows_role_downgrade(audit):
    log, _ = audit
    with patch("mcp.server.tool_query_stats", return_value={"aggregate": {}}):
        await handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "query_stats", "arguments": {"role": "public"}},
            },
            role="fraud_ops",
        )
    assert log.call_args.args[1] == "public"
