"""Tests for the prior-campaign seeding — the generaliser's precondition.

The property that matters is not "some rows exist". It is that after seeding, a
LIVE run that approves the wave's campaign has the **three** approved campaigns
``maybe_generalise`` requires, so the core-tier rule can actually be produced
outside REPLAY. Before this seeding existed the generaliser always returned
``None`` live, and Screen E's core diff was only ever narrated by the recorded
replay.

The last test drives the real ``maybe_generalise`` with the seeded campaigns and
only stubs the LLM, so it fails if the seeded data stops satisfying the
generaliser's input contract.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

from src.enterprise.adaptation import DEFAULT_CORE_CONTENT
from src.enterprise.generaliser import maybe_generalise
from src.enterprise.seed_prior import (
    CORE_ARTIFACT_NAME,
    CORE_BASELINE_VERSION,
    PRIOR_CAMPAIGNS,
    build_prior_state,
)

_NS = uuid.NAMESPACE_URL


def _seed_uuid(kind: str, key: str) -> str:
    """Same deterministic id scheme the demo seeder uses."""
    return str(uuid.uuid5(_NS, f"https://transafe.local/v2/seed/{kind}/{key}"))


def _state() -> dict[str, Any]:
    return build_prior_state(_seed_uuid)


def test_two_prior_campaigns_are_approved() -> None:
    """Two prior campaigns, both APPROVED — three is the generaliser's minimum."""
    state = _state()
    assert len(state["campaigns"]) == 2
    assert {c["code"] for c in state["campaigns"]} == {c["code"] for c in PRIOR_CAMPAIGNS}
    assert all(c["status"] == "APPROVED" for c in state["campaigns"])
    # approved_by/at must be set: an "approved" campaign with no decision-maker
    # would not survive an audit question about who authorised the artifact.
    assert all(c["approved_by"] and c["approved_at"] for c in state["campaigns"])


def test_every_prior_case_produces_a_mo_fingerprint() -> None:
    """Each seeded case carries an MO, which is all the generaliser reads."""
    state = _state()
    case_ids = {c["id"] for c in state["fraud_cases"]}
    mo_case_ids = {m["case_id"] for m in state["case_mo"]}
    assert case_ids == mo_case_ids
    assert len(state["case_mo"]) == len(PRIOR_CAMPAIGNS) * 3


def test_the_invariant_is_present_in_every_campaign() -> None:
    """The structural trio is the cross-campaign signal, so it must be universal.

    A prior campaign missing one of these phases would make the invariant
    campaign-specific and the generaliser's proposal would (correctly) be
    rejected as not generalisable.
    """
    required = {"authority_claim", "isolation", "safe_account_instruction"}
    for mo in _state()["case_mo"]:
        phases = set(mo["fingerprint"]["script_phases"])
        assert required <= phases, f"{mo['case_id']} is missing {required - phases}"


def test_no_single_campaign_proves_the_invariant_alone() -> None:
    """Each campaign names a different institution, so the trio is the only link."""
    state = _state()
    entities = {
        mo["fingerprint"]["impersonated_entity"] for mo in state["case_mo"]
    }
    assert len(entities) == len(PRIOR_CAMPAIGNS)


def test_prior_cases_seed_real_graph_entities() -> None:
    """Identifiers are spoken in the script, so the prior campaigns have nodes.

    Seeding campaigns whose cases produce no entities would leave the scam graph
    empty for two thirds of the console's campaigns.
    """
    state = _state()
    assert state["entity_rows"], "no entities extracted from prior-campaign scripts"
    assert state["links"], "no case→entity links built for prior cases"
    types = {key[0] for key in state["entity_rows"]}
    assert "PHONE" in types or "ACCOUNT" in types


def test_core_baseline_is_v6_and_has_no_structural_rule() -> None:
    """The baseline is the "before" state, so the diff is a real addition.

    If the shipped baseline already encoded the escalation rule, the generaliser
    would be re-stating existing behaviour and Screen E's green lines would be
    decoration rather than a change.
    """
    artifact = _state()["artifacts"][0]
    assert artifact["name"] == CORE_ARTIFACT_NAME
    assert artifact["tier"] == "core"
    assert artifact["version"] == CORE_BASELINE_VERSION
    assert artifact["status"] == "PUBLISHED"
    assert artifact["content"] == DEFAULT_CORE_CONTENT
    low = artifact["content"].casefold()
    assert "authority" not in low
    assert "isolation" not in low


def test_core_baseline_makes_a_live_publish_read_v7() -> None:
    """next_version() over v6 yields 7, so the demo says v6→v7 live too.

    On an empty registry the first core publish is v1, which contradicts the
    recorded replay's narration and makes a live run look like a different
    system from the one on the slide.
    """
    from src.enterprise.registry import next_version

    class _Query:
        def select(self, *_a: Any, **_k: Any) -> _Query:
            return self

        def eq(self, *_a: Any, **_k: Any) -> _Query:
            return self

        def order(self, *_a: Any, **_k: Any) -> _Query:
            return self

        def limit(self, *_a: Any, **_k: Any) -> _Query:
            return self

        def execute(self) -> Any:
            return type("R", (), {"data": [{"version": CORE_BASELINE_VERSION}]})()

    class _Client:
        def table(self, _name: str) -> _Query:
            return _Query()

    assert next_version(CORE_ARTIFACT_NAME, client=_Client()) == CORE_BASELINE_VERSION + 1


def test_seeding_is_idempotent() -> None:
    """Stable ids mean re-seeding upserts instead of duplicating the campaigns."""
    first, second = _state(), _state()
    assert [c["id"] for c in first["campaigns"]] == [c["id"] for c in second["campaigns"]]
    assert [c["id"] for c in first["fraud_cases"]] == [c["id"] for c in second["fraud_cases"]]


def test_generaliser_can_run_with_the_seeded_campaigns() -> None:
    """End-to-end precondition: seeded campaigns satisfy maybe_generalise.

    Only the LLM is stubbed. Everything else — the ≥3-campaign gate, the MO
    shaping and the agnosticism validator — runs for real, so this fails if the
    seeded data stops being usable input.
    """
    state = _state()
    by_campaign: dict[str, list[dict[str, Any]]] = {}
    mo_by_case = {m["case_id"]: m["fingerprint"] for m in state["case_mo"]}
    for link in state["campaign_cases"]:
        by_campaign.setdefault(str(link["campaign_id"]), []).append(
            mo_by_case[str(link["case_id"])]
        )
    campaigns = [
        {
            "code": campaign["code"],
            "mo_fingerprints": by_campaign.get(str(campaign["id"]), []),
        }
        for campaign in state["campaigns"]
    ]
    # The wave's own campaign joins them, as it would on approval.
    campaigns.append({"code": "SCAM-027", "mo_fingerprints": [{}]})
    assert len(campaigns) == 3

    response = MagicMock()
    response.content = """{
        "found": true,
        "rule_text": "When authority_claim and isolation co-occur, escalate.",
        "rule_id": "R-4",
        "justification": "Co-occurrence seen in all three campaigns",
        "source_campaigns": ["SCAM-019", "SCAM-024", "SCAM-027"],
        "evidence_summary": "Structural overlap"
    }"""

    with patch(
        "src.enterprise.generaliser.invoke_deepseek_with_key_rotation",
        return_value=response,
    ):
        proposal = maybe_generalise(campaigns, DEFAULT_CORE_CONTENT)

    assert proposal is not None, "generaliser precondition not met by the seed"
    assert proposal["rule_id"] == "R-4"


def test_generaliser_declines_with_only_one_approved_campaign() -> None:
    """Guards the test above: the old seed really was insufficient."""
    with patch("src.enterprise.generaliser.invoke_deepseek_with_key_rotation") as mock_llm:
        assert maybe_generalise([{"code": "SCAM-027", "mo_fingerprints": [{}]}], "") is None
    mock_llm.assert_not_called()
