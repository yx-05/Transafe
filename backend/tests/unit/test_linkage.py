"""Unit tests for src.enterprise.linkage."""

from unittest.mock import MagicMock, patch

from src.enterprise.linkage import (
    LINK_THRESHOLD,
    _mo_structural_overlap,
    _narrative_similarity,
    _temporal_multiplier,
    compute_blocking_keys,
    get_candidate_pairs,
    score_case_pair,
)

CASE_A = {"id": "c1", "created_at": "2026-09-10T10:00:00Z", "mo_fingerprint": {}}
CASE_B = {"id": "c2", "created_at": "2026-09-10T14:00:00Z", "mo_fingerprint": {}}


def test_score_case_pair_shared_identifier():
    entities_a = [{"entity_type": "PHONE", "value_norm": "+60112345678"}]
    entities_b = [{"entity_type": "PHONE", "value_norm": "+60112345678"}]
    result = score_case_pair(CASE_A, CASE_B, entities_a, entities_b)
    assert result["score"] == 0.95
    assert result["signals"]["shared_identifier"]["matched"] is True


def test_score_case_pair_no_signals():
    result = score_case_pair(CASE_A, CASE_B, [], [])
    assert result["score"] == 0.0
    assert result["evidence_case_ids"] == ["c1", "c2"]


def test_score_case_pair_narrative_only():
    emb_a = [1.0, 0.0, 0.0]
    emb_b = [0.9, 0.1, 0.0]
    result = score_case_pair(CASE_A, CASE_B, [], [], emb_a, emb_b)
    assert 0.6 <= result["score"] <= 0.9
    assert "narrative" in result["signals"]


def test_score_case_pair_narrative_below_gate_excluded():
    emb_a = [1.0, 0.0, 0.0]
    emb_b = [0.5, 0.9, 0.0]
    result = score_case_pair(CASE_A, CASE_B, [], [], emb_a, emb_b)
    assert result["signals"]["narrative"]["below_gate"] is True
    assert result["score"] == 0.0


def test_score_case_pair_noisy_or_fusion():
    """Two independent signals must fuse above either one alone."""
    entities_a = [
        {"entity_type": "DOMAIN", "value_norm": "bnm-verify.online"},
    ]
    entities_b = [
        {"entity_type": "DOMAIN", "value_norm": "bnm-verify.online"},
    ]
    emb = [1.0, 0.0, 0.0]
    result = score_case_pair(CASE_A, CASE_B, entities_a, entities_b, emb, emb)
    assert result["score"] > 0.80
    assert result["score"] <= 1.0


def test_score_case_pair_hard_identifier_not_inflated_by_temporal():
    """0.95 is near-proof; the temporal modifier must not push it to certainty."""
    entities = [{"entity_type": "PHONE", "value_norm": "+60112345678"}]
    result = score_case_pair(CASE_A, CASE_B, entities, list(entities))
    assert result["score"] == 0.95
    assert result["signals"]["temporal"]["applied"] is False


def test_score_case_pair_temporal_boosts_weak_signals():
    far_b = {"id": "c2", "created_at": "2026-10-30T10:00:00Z", "mo_fingerprint": {}}
    mo = {"script_phases": ["a", "b"], "pressure_tactics": ["urgency"]}
    near = score_case_pair(
        {**CASE_A, "mo_fingerprint": mo}, {**CASE_B, "mo_fingerprint": mo}, [], []
    )
    far = score_case_pair(
        {**CASE_A, "mo_fingerprint": mo}, {**far_b, "mo_fingerprint": mo}, [], []
    )
    assert near["score"] > far["score"]


def test_score_case_pair_handles_json_string_fingerprint():
    mo_json = '{"script_phases": ["a", "b"], "impersonated_entity": "BNM"}'
    result = score_case_pair(
        {**CASE_A, "mo_fingerprint": mo_json},
        {**CASE_B, "mo_fingerprint": mo_json},
        [],
        [],
    )
    assert result["signals"]["mo_overlap"]["score"] == 1.0


def test_narrative_similarity_identical():
    emb = [1.0, 0.0, 0.0]
    assert _narrative_similarity(emb, emb) == 1.0


def test_narrative_similarity_orthogonal():
    assert _narrative_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_narrative_similarity_none_input():
    assert _narrative_similarity(None, [1.0]) is None
    assert _narrative_similarity([1.0], None) is None
    assert _narrative_similarity([1.0, 0.0], [1.0]) is None


def test_narrative_similarity_zero_vector():
    assert _narrative_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_mo_overlap_identical():
    mo = {"script_phases": ["a", "b"], "pressure_tactics": ["urgency"]}
    assert _mo_structural_overlap(mo, mo)["score"] == 1.0


def test_mo_overlap_disjoint():
    assert (
        _mo_structural_overlap({"script_phases": ["a"]}, {"script_phases": ["z"]})["score"] == 0.0
    )


def test_mo_overlap_empty():
    assert _mo_structural_overlap({}, {})["score"] == 0.0


def test_mo_overlap_includes_impersonated_entity():
    result = _mo_structural_overlap(
        {"impersonated_entity": "BNM"}, {"impersonated_entity": "BNM"}
    )
    assert result["score"] == 1.0
    assert result["intersection"] == ["BNM"]


def test_temporal_multiplier_within_window():
    assert _temporal_multiplier("2026-09-10T10:00:00Z", "2026-09-11T10:00:00Z") == 1.15


def test_temporal_multiplier_outside_window():
    assert _temporal_multiplier("2026-09-10T10:00:00Z", "2026-09-20T10:00:00Z") == 1.0


def test_temporal_multiplier_bad_input():
    assert _temporal_multiplier(None, "2026-09-10T10:00:00Z") == 1.0
    assert _temporal_multiplier("not-a-date", "2026-09-10T10:00:00Z") == 1.0


def test_compute_blocking_keys():
    case = {
        "id": "c1",
        "mo_fingerprint": {
            "impersonated_entity": "BNM",
            "script_phases": ["authority_claim", "money_ask"],
        },
    }
    entities = [{"entity_type": "PHONE", "value_norm": "+60112345678"}]
    keys = compute_blocking_keys(case, entities)
    assert "ent:PHONE:+60112345678" in keys
    assert "imp:bnm" in keys
    assert any(k.startswith("mo_sig:") for k in keys)


def test_compute_blocking_keys_empty_case():
    assert compute_blocking_keys({"id": "c1"}, []) == []


@patch("src.enterprise.linkage.get_supabase_client")
def test_get_candidate_pairs_entity_blocking(mock_client):
    entities_table = MagicMock()
    entities_table.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "e1"}
    ]
    links_table = MagicMock()
    links_table.select.return_value.in_.return_value.execute.return_value.data = [
        {"case_id": "c1"},
        {"case_id": "c2"},
    ]

    def table_router(name):
        return entities_table if name == "entities" else links_table

    mock_client.return_value.table.side_effect = table_router

    candidates = get_candidate_pairs("c1", ["ent:PHONE:+60112345678"])
    assert candidates == ["c2"]


@patch("src.enterprise.linkage.get_supabase_client")
def test_get_candidate_pairs_no_keys(mock_client):
    assert get_candidate_pairs("c1", []) == []


@patch("src.enterprise.linkage.get_supabase_client")
def test_get_candidate_pairs_supabase_down(mock_client):
    mock_client.side_effect = RuntimeError("down")
    assert get_candidate_pairs("c1", ["ent:PHONE:x"]) == []


def test_link_threshold_value():
    assert LINK_THRESHOLD == 0.60
