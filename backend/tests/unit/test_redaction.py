"""Unit tests for role-based redaction (04_mcp_gateway.md §4 Testing).

Beyond the documented per-role cases, these tests pin the three properties the
gateway's safety actually rests on: the walk is recursive to arbitrary depth,
unknown roles fail closed, and the public role leaks nothing at all.
"""

from __future__ import annotations

import json

from mcp.redaction import (
    ALL_CATEGORIES,
    DEFAULT_VISIBILITY,
    ROLE_VISIBILITY,
    can_access,
    redact_by_role,
    redacted_categories_for,
    visibility_for,
)


# ── Documented per-role cases ────────────────────────────────────────────────
def test_fraud_ops_sees_everything():
    data = {"transcripts": [{"utterance": "secret"}], "user_id": "u1"}
    result = redact_by_role(data, "fraud_ops")
    assert result["transcripts"][0]["utterance"] == "secret"
    assert result["user_id"] == "u1"


def test_compliance_redacts_transcripts_and_pii():
    data = {
        "transcripts": [{"utterance": "secret"}],
        "user_id": "u1",
        "case_ids": ["c1", "c2"],
        "compliance_brief": "text",
    }
    result = redact_by_role(data, "compliance")
    assert result["transcripts"] == "[REDACTED]"
    assert result["user_id"] == "[REDACTED]"
    assert result["case_ids"] == ["c1", "c2"]
    assert result["compliance_brief"] == "text"


def test_customer_service_redacts_compliance_brief():
    data = {"cs_advisory": "text", "compliance_brief": "text", "user_id": "u1"}
    result = redact_by_role(data, "customer_service")
    assert result["cs_advisory"] == "text"
    assert result["compliance_brief"] == "[REDACTED]"
    assert result["user_id"] == "[REDACTED]"


def test_legal_redacts_account_numbers():
    data = {
        "campaign": "SCAM-027",
        "recipient_account": "1592-3456",
        "sender_account": "8888-1111",
    }
    result = redact_by_role(data, "legal")
    assert result["campaign"] == "SCAM-027"
    assert result["recipient_account"] == "[REDACTED]"
    assert result["sender_account"] == "[REDACTED]"


def test_partner_bank_redacts_case_ids():
    data = {"case_ids": ["c1"], "indicators": {"accounts": ["1592-3456"]}}
    result = redact_by_role(data, "partner_bank")
    assert result["case_ids"] == "[REDACTED]"
    assert "indicators" in result


def test_external_researcher_sees_only_aggregate():
    data = {"campaign": "SCAM-027", "indicators": {}, "aggregate": {"count": 5}}
    result = redact_by_role(data, "external_researcher")
    assert result["aggregate"]["count"] == 5
    assert result["campaign"] == "[REDACTED]"
    assert result["indicators"] == "[REDACTED]"


# ── Recursion ────────────────────────────────────────────────────────────────
def test_redaction_preserves_structure():
    data = {"a": {"b": {"user_id": "u1"}}}
    result = redact_by_role(data, "compliance")
    assert result["a"]["b"]["user_id"] == "[REDACTED]"


def test_redaction_handles_lists():
    data = [{"user_id": "u1"}, {"user_id": "u2"}]
    result = redact_by_role(data, "compliance")
    assert all(item["user_id"] == "[REDACTED]" for item in result)


def test_redaction_walks_deeply_nested_payload():
    """A secret one level deeper than the walker is a leak. Go six deep."""
    data = {
        "level1": {
            "list_of_dicts": [
                {
                    "level3": {
                        "cases": [
                            {
                                "evidence": {
                                    "transcripts": [
                                        {"speaker": "agent", "utterance": "SUPER_SECRET"}
                                    ],
                                    "customer_phone": "+60123456789",
                                    "meta": {"nested": {"user_id": "u-deep"}},
                                }
                            }
                        ]
                    }
                }
            ],
            "list_of_scalars": ["a", "b", "c"],
        }
    }
    result = redact_by_role(data, "compliance")
    blob = json.dumps(result)

    assert "SUPER_SECRET" not in blob
    assert "+60123456789" not in blob
    assert "u-deep" not in blob
    # Structure survives: the caller can still see that a field existed.
    assert result["level1"]["list_of_scalars"] == ["a", "b", "c"]
    inner = result["level1"]["list_of_dicts"][0]["level3"]["cases"][0]["evidence"]
    assert inner["transcripts"] == "[REDACTED]"
    assert inner["customer_phone"] == "[REDACTED]"
    assert inner["meta"]["nested"]["user_id"] == "[REDACTED]"


def test_redaction_does_not_mutate_input():
    data = {"user_id": "u1", "nested": {"user_id": "u2"}}
    redact_by_role(data, "public")
    assert data["user_id"] == "u1"
    assert data["nested"]["user_id"] == "u2"


def test_redaction_handles_scalars_and_none():
    assert redact_by_role("plain", "public") == "plain"
    assert redact_by_role(None, "public") is None
    assert redact_by_role([1, 2, 3], "public") == [1, 2, 3]


# ── Fail-closed ──────────────────────────────────────────────────────────────
def test_can_access():
    assert can_access("fraud_ops", "transcripts") is True
    assert can_access("compliance", "transcripts") is False
    assert can_access("external_researcher", "aggregate") is True


def test_unknown_role_gets_least_privilege():
    assert visibility_for("chief_executive_officer") == set(DEFAULT_VISIBILITY)
    assert can_access("chief_executive_officer", "transcripts") is False
    assert can_access("", "campaign") is False


def test_unknown_role_redacts_like_public():
    data = {"campaign": "SCAM-027", "user_id": "u1", "aggregate": {"count": 3}}
    assert redact_by_role(data, "not_a_real_role") == redact_by_role(data, "public")


def test_public_role_leaks_nothing():
    """The most restrictive role must surface no PII of any kind."""
    data = {
        "campaign": "SCAM-027",
        "victim_name": "Tan Ah Kow",
        "customer_name": "Lim Bee Choo",
        "customer_phone": "+60123456789",
        "phone_number": "+60198887777",
        "recipient_account": "1592-3456",
        "account_number": "8888-1111",
        "user_id": "u-42",
        "email": "victim@example.com",
        "nric": "900101-14-5555",
        "transcripts": [{"speaker": "victim", "utterance": "my OTP is 449122"}],
        "case_ids": ["case-1"],
        "indicators": {"accounts": ["1592-3456"]},
        "aggregate": {"count": 5},
    }
    result = redact_by_role(data, "public")
    blob = json.dumps(result)

    for secret in (
        "Tan Ah Kow",
        "Lim Bee Choo",
        "+60123456789",
        "+60198887777",
        "1592-3456",
        "8888-1111",
        "u-42",
        "victim@example.com",
        "900101-14-5555",
        "449122",
        "case-1",
        "SCAM-027",
    ):
        assert secret not in blob, f"public role leaked {secret!r}"

    assert result["aggregate"]["count"] == 5


def test_every_role_can_see_aggregate():
    for role in ROLE_VISIBILITY:
        assert can_access(role, "aggregate"), f"{role} cannot see aggregate"


def test_redacted_categories_for():
    assert redacted_categories_for("fraud_ops") == []
    public = redacted_categories_for("public")
    assert set(public) == set(ALL_CATEGORIES)
    assert "transcripts" in redacted_categories_for("compliance")
    assert "compliance_brief" not in redacted_categories_for("compliance")
    # Unknown roles are labelled as withholding everything.
    assert set(redacted_categories_for("nonsense")) == set(ALL_CATEGORIES)
