"""Unit tests for the artifact compiler (L4 pack tier).

Implements the cases specified in doc/transafe_v2/03_artifact_registry.md §9.2.
The LLM and Supabase are always mocked; no network and no API keys.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.enterprise.compiler import (
    APPROVED_STATUSES,
    PACK_ARTIFACT_TYPES,
    _compiler_fallback,
    _summarise_entities,
    _summarise_mo,
    build_alias_artifacts,
    compile_approved_campaign,
    compile_campaign,
)

ENTITIES = [
    {"entity_type": "ACCOUNT", "value_norm": "12345", "value_raw": "1234-5"},
    {"entity_type": "DOMAIN", "value_norm": "evil.com", "value_raw": "evil.com"},
]


@patch("src.enterprise.compiler.invoke_deepseek_with_key_rotation")
def test_compile_campaign_returns_all_artifacts(mock_llm: MagicMock) -> None:
    """The compiler returns all five pack-tier artifact types."""
    mock_response = MagicMock()
    mock_response.content = """{
        "campaign_pack": {"campaign": "SCAM-027"},
        "phishing_playbook_patch": {"campaign": "SCAM-027"},
        "txn_rule": {"campaign": "SCAM-027"},
        "compliance_brief": "# Brief",
        "cs_advisory": "# Advisory"
    }"""
    mock_llm.return_value = mock_response

    result = compile_campaign("camp-1", {"code": "SCAM-027"}, [], [])
    assert result is not None
    for artifact_type in PACK_ARTIFACT_TYPES:
        assert artifact_type in result


@patch("src.enterprise.compiler.invoke_deepseek_with_key_rotation")
def test_compile_campaign_llm_failure_triggers_fallback(mock_llm: MagicMock) -> None:
    """A dead API key degrades to the deterministic fallback."""
    mock_llm.side_effect = RuntimeError("LLM down")
    result = compile_campaign("camp-1", {"code": "SCAM-027"}, [], [])
    assert result is not None
    assert result["campaign_pack"]["campaign"] == "SCAM-027"


@patch("src.enterprise.compiler.invoke_deepseek_with_key_rotation")
def test_compile_campaign_backfills_omitted_artifact(mock_llm: MagicMock) -> None:
    """An artifact type the LLM omits is backfilled from the fallback."""
    mock_response = MagicMock()
    mock_response.content = '{"campaign_pack": {"campaign": "SCAM-027"}}'
    mock_llm.return_value = mock_response

    result = compile_campaign("camp-1", {"code": "SCAM-027"}, [], ENTITIES)
    assert result is not None
    assert result["txn_rule"]["campaign"] == "SCAM-027"
    assert "evil.com.*" in result["phishing_playbook_patch"]["url_patterns"]
    assert result["cs_advisory"].startswith("# Customer Advisory")


@patch("src.enterprise.compiler.invoke_deepseek_with_key_rotation")
def test_compile_campaign_unparseable_json_triggers_fallback(mock_llm: MagicMock) -> None:
    """Unparseable model output is treated as a failure, not published."""
    mock_response = MagicMock()
    mock_response.content = "I cannot help with that."
    mock_llm.return_value = mock_response

    result = compile_campaign("camp-1", {"code": "SCAM-027"}, [], [])
    assert result is not None
    assert result["campaign_pack"]["campaign"] == "SCAM-027"


def test_compiler_fallback_includes_entities() -> None:
    """The fallback carries resolved entities into the pack indicators."""
    result = _compiler_fallback({"code": "SCAM-027", "name": "Test"}, [], ENTITIES)
    assert "12345" in result["campaign_pack"]["indicators"]["accounts"]
    assert "evil.com" in result["campaign_pack"]["indicators"]["domains"]


def test_compiler_fallback_blocks_known_mule_accounts() -> None:
    """A known mule account becomes a BLOCK transaction rule."""
    result = _compiler_fallback({"code": "SCAM-027", "name": "Test"}, [], ENTITIES)
    actions = [rule["action"] for rule in result["txn_rule"]["rules"]]
    assert "BLOCK" in actions


def test_summarise_mo_handles_empty() -> None:
    """An empty fingerprint list renders as a sentinel line."""
    assert _summarise_mo([]) == "No MO fingerprints available."


def test_summarise_mo_includes_fields() -> None:
    """The MO summary carries the impersonated entity through."""
    mo = [{"impersonated_entity": "BNM", "script_phases": ["a"], "pressure_tactics": ["b"]}]
    summary = _summarise_mo(mo)
    assert "BNM" in summary
    assert "authority" not in summary


def test_summarise_entities_handles_empty() -> None:
    """An empty entity list renders as a sentinel line."""
    assert _summarise_entities([]) == "No entities available."


def test_summarise_entities_includes_value_norm() -> None:
    """Entities are summarised on their normalised value."""
    assert "evil.com" in _summarise_entities(ENTITIES)


@patch("src.enterprise.compiler.compile_campaign")
def test_compile_approved_campaign_refuses_unapproved(mock_compile: MagicMock) -> None:
    """The approval gate is real: an unapproved campaign is never compiled."""
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "camp-1", "code": "SCAM-027", "status": "PENDING_VALIDATION"}
    ]

    assert compile_approved_campaign("camp-1", client=mock_client) is None
    mock_compile.assert_not_called()


@patch("src.enterprise.compiler.compile_campaign")
def test_compile_approved_campaign_runs_when_approved(mock_compile: MagicMock) -> None:
    """An approved campaign is compiled."""
    mock_compile.return_value = {"campaign_pack": {"campaign": "SCAM-027"}}
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "camp-1", "code": "SCAM-027", "status": "APPROVED"}
    ]

    result = compile_approved_campaign("camp-1", client=mock_client)
    assert result is not None
    mock_compile.assert_called_once()


@patch("src.enterprise.compiler.compile_campaign")
def test_compile_approved_campaign_refuses_rejected(mock_compile: MagicMock) -> None:
    """A REJECTED campaign is never compilable.

    Rejection is the terminal half of the governance gate: once a human has
    refused a candidate, no later call may turn it into artifacts.
    """
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {
            "id": "camp-1",
            "code": "SCAM-027",
            "status": "REJECTED",
            "reject_reason": "coincidental overlap, not one campaign",
        }
    ]

    assert compile_approved_campaign("camp-1", client=mock_client) is None
    mock_compile.assert_not_called()


@pytest.mark.parametrize(
    "status",
    ["CANDIDATE", "PENDING_VALIDATION", "REJECTED", "SUPERSEDED", "ARCHIVED", "", "approved"],
)
@patch("src.enterprise.compiler.compile_campaign")
def test_compile_approved_campaign_refuses_every_non_approved_status(
    mock_compile: MagicMock, status: str
) -> None:
    """The gate is allow-list based: only APPROVED/ACTIVE compile, nothing else.

    Includes the lower-case spelling, which must not slip through the
    membership test.
    """
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "camp-1", "code": "SCAM-027", "status": status}
    ]

    assert compile_approved_campaign("camp-1", client=mock_client) is None
    mock_compile.assert_not_called()


@pytest.mark.parametrize("status", sorted(APPROVED_STATUSES))
@patch("src.enterprise.compiler.compile_campaign")
def test_compile_approved_campaign_allows_only_approved_statuses(
    mock_compile: MagicMock, status: str
) -> None:
    """Both signed-off states — APPROVED and ACTIVE — compile."""
    mock_compile.return_value = {"campaign_pack": {"campaign": "SCAM-027"}}
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "camp-1", "code": "SCAM-027", "status": status}
    ]

    assert compile_approved_campaign("camp-1", client=mock_client) is not None
    mock_compile.assert_called_once()


@patch("src.enterprise.compiler.compile_campaign")
def test_compile_approved_campaign_missing_campaign(mock_compile: MagicMock) -> None:
    """An unknown campaign id compiles nothing and raises nothing."""
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    assert compile_approved_campaign("nope", client=mock_client) is None
    mock_compile.assert_not_called()


def test_build_alias_artifacts_emits_value_norm() -> None:
    """The entity watchlist keys entities on value_norm, the graph join key."""
    compiled = _compiler_fallback({"code": "SCAM-027", "name": "Test"}, [], ENTITIES)
    aliases = build_alias_artifacts({"code": "SCAM-027"}, compiled, ENTITIES)

    assert set(aliases) == {
        "detection_rules.md",
        "advisory_template.md",
        "risk_score_overrides.json",
        "narrative.md",
        "entity_watchlist.json",
    }
    watchlist = aliases["entity_watchlist.json"]
    assert {e["value_norm"] for e in watchlist["entities"]} == {"12345", "evil.com"}
