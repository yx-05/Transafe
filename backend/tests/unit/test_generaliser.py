"""Unit tests for the generaliser (L4 core tier).

Implements the cases specified in doc/transafe_v2/03_artifact_registry.md §9.3.
The central property under test is that emitting *nothing* is a correct
outcome — the generaliser must never be forced into producing a core rule.
"""

from unittest.mock import MagicMock, patch

from src.enterprise.generaliser import (
    MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION,
    build_core_patch,
    check_agnosticism,
    maybe_generalise,
    validate_campaign_agnostic,
)

THREE_CAMPAIGNS = [
    {"code": "SCAM-019", "mo_fingerprints": [{}]},
    {"code": "SCAM-024", "mo_fingerprints": [{}]},
    {"code": "SCAM-027", "mo_fingerprints": [{}]},
]

GENERIC_RULE = "When authority_claim, isolation and safe_account_instruction co-occur, escalate."


def test_min_campaigns_constant() -> None:
    """A generalisation needs at least two *other* approved campaigns."""
    assert MIN_APPROVED_CAMPAIGNS_FOR_GENERALISATION == 2


def test_validate_agnostic_passes_generic_rule() -> None:
    """A rule phrased over MO features is campaign-agnostic."""
    assert validate_campaign_agnostic(GENERIC_RULE) is True


def test_validate_agnostic_fails_named_campaign() -> None:
    """C1: a rule naming a campaign code is rejected."""
    assert validate_campaign_agnostic("When SCAM-027 pattern is detected, escalate.") is False


def test_validate_agnostic_fails_named_institution() -> None:
    """C1: a rule naming an impersonated institution is rejected."""
    assert validate_campaign_agnostic("When Bank Negara is impersonated, escalate.") is False


def test_validate_agnostic_fails_named_account() -> None:
    """C1: a rule naming a specific account identifier is rejected."""
    rule = "If the caller mentions account 1592, escalate."
    assert validate_campaign_agnostic(rule) is False
    assert any(v["condition"] == "C1" for v in check_agnosticism(rule)["violations"])


def test_validate_agnostic_fails_temporal_reference() -> None:
    """C2: a rule tied to one wave in time is rejected."""
    rule = "Escalate calls matching the pattern observed in March 2026."
    assert validate_campaign_agnostic(rule) is False
    assert any(v["condition"] == "C2" for v in check_agnosticism(rule)["violations"])


def test_validate_agnostic_fails_empty_rule() -> None:
    """An empty rule is never publishable to the core tier."""
    assert validate_campaign_agnostic("") is False


def test_maybe_generalise_returns_none_for_few_campaigns() -> None:
    """The generaliser does not run with fewer than three approved campaigns."""
    campaigns = [{"code": "SCAM-019"}, {"code": "SCAM-024"}]
    assert maybe_generalise(campaigns, "current content") is None


@patch("src.enterprise.generaliser.invoke_deepseek_with_key_rotation")
def test_maybe_generalise_returns_rule_when_found(mock_llm: MagicMock) -> None:
    """A validated cross-campaign invariant is returned as a proposal."""
    mock_response = MagicMock()
    mock_response.content = """{
        "found": true,
        "rule_text": "When authority_claim and isolation co-occur, escalate.",
        "rule_id": "R-4",
        "justification": "Seen across 3 campaigns",
        "source_campaigns": ["SCAM-019", "SCAM-024", "SCAM-027"],
        "evidence_summary": "Pattern co-occurrence"
    }"""
    mock_llm.return_value = mock_response

    result = maybe_generalise(THREE_CAMPAIGNS, "current content")
    assert result is not None
    assert result["found"] is True
    assert result["rule_id"] == "R-4"


@patch("src.enterprise.generaliser.invoke_deepseek_with_key_rotation")
def test_maybe_generalise_returns_none_when_not_found(mock_llm: MagicMock) -> None:
    """`{"found": false}` is a correct, expected answer."""
    mock_response = MagicMock()
    mock_response.content = '{"found": false}'
    mock_llm.return_value = mock_response

    campaigns = [{"code": "SCAM-019", "mo_fingerprints": [{}]}] * 3
    assert maybe_generalise(campaigns, "current content") is None


@patch("src.enterprise.generaliser.invoke_deepseek_with_key_rotation")
def test_maybe_generalise_rejects_campaign_specific_rule(mock_llm: MagicMock) -> None:
    """A proposal that fails the agnosticism validator is discarded."""
    mock_response = MagicMock()
    mock_response.content = """{
        "found": true,
        "rule_text": "When Bank Negara is impersonated, escalate.",
        "rule_id": "R-4"
    }"""
    mock_llm.return_value = mock_response

    assert maybe_generalise(THREE_CAMPAIGNS, "current content") is None


@patch("src.enterprise.generaliser.invoke_deepseek_with_key_rotation")
def test_maybe_generalise_survives_llm_failure(mock_llm: MagicMock) -> None:
    """A dead API key yields no core patch rather than a bad one."""
    mock_llm.side_effect = RuntimeError("LLM down")
    assert maybe_generalise(THREE_CAMPAIGNS, "current content") is None


def test_build_core_patch_appends_rule_in_context() -> None:
    """The patch adds one rule to the escalation section, keeping the rest."""
    current = "# phone_agent_core\n\n## Escalation rules\nR-1: Existing rule.\n\n## Other\ntext\n"
    patched = build_core_patch(
        current,
        {"rule_id": "R-2", "rule_text": GENERIC_RULE, "source_campaigns": ["A", "B", "C"]},
    )
    assert "R-1: Existing rule." in patched
    assert "R-2: " + GENERIC_RULE in patched
    assert "## Other" in patched
    assert patched.index("R-2") < patched.index("## Other")


def test_build_core_patch_creates_section_when_absent() -> None:
    """A core body without an escalation section gains one."""
    patched = build_core_patch("# phone_agent_core\n", {"rule_text": GENERIC_RULE})
    assert "## Escalation rules" in patched
    assert GENERIC_RULE in patched
