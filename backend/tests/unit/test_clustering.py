"""Unit tests for src.enterprise.clustering."""

from src.enterprise.clustering import (
    EMBEDDING_DIM,
    check_promotion_gates,
    cluster_components,
    compute_campaign_embedding,
    summarise_component,
)

LINKS = [
    {"case_a": "c1", "case_b": "c2", "score": 0.85},
    {"case_a": "c2", "case_b": "c3", "score": 0.82},
]

CASES = {
    "c1": {"user_id": "u1", "created_at": "2026-09-08T10:00:00Z"},
    "c2": {"user_id": "u2", "created_at": "2026-09-09T10:00:00Z"},
    "c3": {"user_id": "u3", "created_at": "2026-09-10T10:00:00Z"},
}


def test_cluster_components_single_component():
    components = cluster_components(LINKS, min_weight=0.6)
    assert len(components) == 1
    assert components[0] == {"c1", "c2", "c3"}


def test_cluster_components_two_components():
    links = LINKS + [{"case_a": "c4", "case_b": "c5", "score": 0.90}]
    assert len(cluster_components(links, min_weight=0.6)) == 2


def test_cluster_components_below_threshold_excluded():
    links = [{"case_a": "c1", "case_b": "c2", "score": 0.50}]
    components = cluster_components(links, min_weight=0.6)
    assert len(components) == 2


def test_cluster_components_empty():
    assert cluster_components([], min_weight=0.6) == []


def test_check_promotion_gates_all_pass():
    result = check_promotion_gates({"c1", "c2", "c3"}, LINKS, CASES)
    assert result["passes"] is True
    assert result["gates"]["case_count"]["pass"] is True
    assert result["gates"]["distinct_customers"]["pass"] is True
    assert result["gates"]["strong_edge"]["pass"] is True
    assert result["confidence"] > 0


def test_check_promotion_gates_too_few_cases():
    result = check_promotion_gates({"c1", "c2"}, LINKS[:1], CASES)
    assert result["passes"] is False
    assert result["gates"]["case_count"]["pass"] is False


def test_check_promotion_gates_same_customer():
    cases = {cid: {**c, "user_id": "u1"} for cid, c in CASES.items()}
    result = check_promotion_gates({"c1", "c2", "c3"}, LINKS, cases)
    assert result["passes"] is False
    assert result["gates"]["distinct_customers"]["pass"] is False


def test_check_promotion_gates_weak_edges_only():
    weak_links = [
        {"case_a": "c1", "case_b": "c2", "score": 0.65},
        {"case_a": "c2", "case_b": "c3", "score": 0.70},
    ]
    result = check_promotion_gates({"c1", "c2", "c3"}, weak_links, CASES)
    assert result["passes"] is False
    assert result["gates"]["strong_edge"]["pass"] is False


def test_check_promotion_gates_time_span_exceeded():
    cases = dict(CASES)
    cases["c3"] = {"user_id": "u3", "created_at": "2026-10-30T10:00:00Z"}
    result = check_promotion_gates({"c1", "c2", "c3"}, LINKS, cases)
    assert result["gates"]["time_span"]["pass"] is False
    assert result["passes"] is False


def test_check_promotion_gates_novelty_merge():
    cases = {cid: {**c, "mo_embedding": [1.0, 0.0, 0.0]} for cid, c in CASES.items()}
    existing = [{"id": "camp-1", "mo_embedding": [1.0, 0.0, 0.0]}]
    result = check_promotion_gates({"c1", "c2", "c3"}, LINKS, cases, existing)
    assert result["novel"] is False
    assert result["passes"] is False
    assert result["gates"]["novelty"]["matched_campaign_id"] == "camp-1"


def test_check_promotion_gates_novel_when_dissimilar():
    cases = {cid: {**c, "mo_embedding": [1.0, 0.0, 0.0]} for cid, c in CASES.items()}
    existing = [{"id": "camp-1", "mo_embedding": [0.0, 1.0, 0.0]}]
    result = check_promotion_gates({"c1", "c2", "c3"}, LINKS, cases, existing)
    assert result["novel"] is True
    assert result["passes"] is True


def test_check_promotion_gates_confidence_penalises_chains():
    """A dense triangle must score higher confidence than a chain of the same size."""
    chain = check_promotion_gates({"c1", "c2", "c3"}, LINKS, CASES)
    triangle_links = LINKS + [{"case_a": "c1", "case_b": "c3", "score": 0.83}]
    triangle = check_promotion_gates({"c1", "c2", "c3"}, triangle_links, CASES)
    assert triangle["confidence"] > chain["confidence"]


def test_compute_campaign_embedding_mean():
    cases = {
        "c1": {"mo_embedding": [1.0] * EMBEDDING_DIM},
        "c2": {"mo_embedding": [3.0] * EMBEDDING_DIM},
    }
    result = compute_campaign_embedding({"c1", "c2"}, cases)
    assert len(result) == EMBEDDING_DIM
    assert result[0] == 2.0


def test_compute_campaign_embedding_no_embeddings():
    result = compute_campaign_embedding({"c1"}, {"c1": {}})
    assert result == [0.0] * EMBEDDING_DIM


def test_compute_campaign_embedding_skips_wrong_dim():
    cases = {"c1": {"mo_embedding": [1.0, 2.0]}}
    assert compute_campaign_embedding({"c1"}, cases) == [0.0] * EMBEDDING_DIM


def test_summarise_component():
    cases = {
        "c1": {
            "created_at": "2026-09-08T10:00:00Z",
            "mo_fingerprint": {
                "impersonated_entity": "BNM",
                "script_phases": ["authority_claim"],
                "pressure_tactics": ["urgency"],
            },
        },
        "c2": {
            "created_at": "2026-09-10T10:00:00Z",
            "mo_fingerprint": {
                "impersonated_entity": "BNM",
                "script_phases": ["money_ask"],
                "pressure_tactics": ["urgency"],
            },
        },
    }
    summary = summarise_component({"c1", "c2"}, cases)
    assert summary["impersonated_entity"] == "BNM"
    assert summary["script_phases"] == ["authority_claim", "money_ask"]
    assert summary["pressure_tactics"] == ["urgency"]
    assert summary["first_seen"].startswith("2026-09-08")
    assert summary["last_seen"].startswith("2026-09-10")


def test_summarise_component_empty():
    summary = summarise_component(set(), {})
    assert summary["impersonated_entity"] is None
    assert summary["first_seen"] is None


def test_summarise_component_is_deterministic():
    cases = {
        "c1": {"mo_fingerprint": {"impersonated_entity": "BNM"}},
        "c2": {"mo_fingerprint": {"impersonated_entity": "Maybank"}},
    }
    results = {summarise_component({"c1", "c2"}, cases)["impersonated_entity"] for _ in range(20)}
    assert len(results) == 1
