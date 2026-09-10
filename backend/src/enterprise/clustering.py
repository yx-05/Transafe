"""Clustering — L3 connected components + campaign promotion gates.

A connected component of linked cases becomes a **campaign candidate** only if
every gate passes. The gates exist so that the system can be wrong out loud
rather than confidently: three reports from one confused customer is not a
campaign, and a chain of weak narrative links is not evidence.

Fully deterministic. No LLM decides whether a cluster is a campaign.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.enterprise.linkage import _narrative_similarity

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768

# ── Promotion gates (01_upgrade_plan.md §6.4.1) ─────────────────────────────
MIN_CASE_COUNT = 3               # two cases is a coincidence
MIN_DISTINCT_CUSTOMERS = 2       # blocks one confused user filing three reports
MIN_EDGE_THRESHOLD = 0.60        # edge must exist at all
MIN_STRONG_EDGE = 0.80           # prevents clusters made only of weak narrative links
MAX_TIME_SPAN_DAYS = 14          # older = archived pattern, not an active wave
NOVELTY_THRESHOLD = 0.90         # at or above this cosine → merge, don't propose


def cluster_components(
    links: list[dict[str, Any]],
    min_weight: float = MIN_EDGE_THRESHOLD,
) -> list[set[str]]:
    """Group cases into connected components using ``networkx``.

    Cases connected only by sub-threshold edges are returned as singleton
    components, so a weak edge never silently merges two clusters.

    Args:
        links: Case-pair link dicts with ``case_a``, ``case_b``, ``score``.
        min_weight: Minimum edge weight to include as a real edge.

    Returns:
        List of sets, each containing the case IDs of one component.
    """
    import networkx as nx

    graph = nx.Graph()
    for link in links:
        case_a = link["case_a"]
        case_b = link["case_b"]
        graph.add_node(case_a)
        graph.add_node(case_b)
        if link["score"] >= min_weight:
            graph.add_edge(case_a, case_b, weight=link["score"])

    return [set(comp) for comp in nx.connected_components(graph)]


def check_promotion_gates(
    component: set[str],
    links: list[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    existing_campaign_embeddings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check every promotion gate for a component.

    Args:
        component: Set of case IDs in the component.
        links: All case-pair links (filtered internally to the component).
        cases: ``case_id`` → case data with ``user_id``, ``created_at``, ``mo_embedding``.
        existing_campaign_embeddings: ``[{"id"/"campaign_id", "mo_embedding"/"embedding"}]``
            used for the novelty check.

    Returns:
        Dict with ``passes``, ``gates``, ``confidence``, ``novel``,
        ``case_count``, ``customer_count`` and ``matched_campaign_id``.
    """
    gates: dict[str, Any] = {}

    # Gate 1 — case count.
    case_count = len(component)
    gates["case_count"] = {
        "value": case_count,
        "min": MIN_CASE_COUNT,
        "pass": case_count >= MIN_CASE_COUNT,
    }

    # Gate 2 — distinct customers.
    customer_ids: set[str] = set()
    for cid in component:
        user_id = cases.get(cid, {}).get("user_id")
        if user_id:
            customer_ids.add(str(user_id))
    gates["distinct_customers"] = {
        "value": len(customer_ids),
        "min": MIN_DISTINCT_CUSTOMERS,
        "pass": len(customer_ids) >= MIN_DISTINCT_CUSTOMERS,
    }

    # Gate 3 — at least one strong edge.
    component_links = [
        link
        for link in links
        if link["case_a"] in component
        and link["case_b"] in component
        and link["score"] >= MIN_EDGE_THRESHOLD
    ]
    max_edge = max((link["score"] for link in component_links), default=0.0)
    gates["strong_edge"] = {
        "value": max_edge,
        "min": MIN_STRONG_EDGE,
        "pass": max_edge >= MIN_STRONG_EDGE,
    }

    # Gate 4 — time span.
    timestamps: list[datetime] = []
    for cid in component:
        ts = cases.get(cid, {}).get("created_at")
        if not ts:
            continue
        try:
            timestamps.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
        except (ValueError, TypeError):
            logger.debug("check_promotion_gates: unparseable created_at %r", ts)
    time_span = (max(timestamps) - min(timestamps)).days if timestamps else 0
    gates["time_span"] = {
        "value": time_span,
        "max": MAX_TIME_SPAN_DAYS,
        "pass": time_span <= MAX_TIME_SPAN_DAYS,
    }

    # Gate 5 — novelty. At or above the threshold the component is not a new
    # campaign; it is growth of an existing one.
    novel = True
    best_cosine = 0.0
    matched_campaign_id: str | None = None
    if existing_campaign_embeddings:
        mean_emb = compute_campaign_embedding(component, cases, strict_dim=False)
        if any(v != 0.0 for v in mean_emb):
            for existing in existing_campaign_embeddings:
                emb = existing.get("mo_embedding") or existing.get("embedding")
                sim = _narrative_similarity(mean_emb, emb)
                if sim is None:
                    continue
                if sim > best_cosine:
                    best_cosine = sim
                    matched_campaign_id = existing.get("id") or existing.get("campaign_id")
                if sim >= NOVELTY_THRESHOLD:
                    novel = False
                    break
    gates["novelty"] = {
        "best_cosine": round(best_cosine, 4),
        "threshold": NOVELTY_THRESHOLD,
        "pass": novel,
        "matched_campaign_id": matched_campaign_id,
    }

    # Confidence — mean intra-cluster edge weight, penalised when the cluster is
    # chain-shaped rather than dense (penalty = density^0.5).
    if component_links:
        mean_weight = sum(link["score"] for link in component_links) / len(component_links)
        n = len(component)
        max_edges = n * (n - 1) / 2 if n > 1 else 1
        density = len(component_links) / max_edges if max_edges > 0 else 0.0
        confidence = mean_weight * (density**0.5)
    else:
        confidence = 0.0

    return {
        "passes": all(gate["pass"] for gate in gates.values()),
        "gates": gates,
        "confidence": round(confidence, 3),
        "novel": novel,
        "case_count": case_count,
        "customer_count": len(customer_ids),
        "matched_campaign_id": matched_campaign_id,
    }


def compute_campaign_embedding(
    component: set[str],
    cases: dict[str, dict[str, Any]],
    strict_dim: bool = True,
) -> list[float]:
    """Compute the mean MO narrative embedding for a campaign candidate.

    Args:
        component: Set of case IDs.
        cases: ``case_id`` → case data containing ``mo_embedding``.
        strict_dim: When True, only 768-dim vectors contribute.

    Returns:
        Mean embedding; a zero vector when no usable embeddings exist.
    """
    embeddings: list[list[float]] = []
    for cid in component:
        emb = cases.get(cid, {}).get("mo_embedding")
        if not isinstance(emb, list) or not emb:
            continue
        if strict_dim and len(emb) != EMBEDDING_DIM:
            continue
        embeddings.append(emb)

    if not embeddings:
        return [0.0] * EMBEDDING_DIM

    width = min(len(e) for e in embeddings)
    return [
        sum(e[i] for e in embeddings) / len(embeddings)
        for i in range(width)
    ]


def summarise_component(
    component: set[str],
    cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Summarise a component's shared MO for campaign naming and review.

    Deterministic: returns the most common impersonated entity, the union of
    script phases and pressure tactics, and the observed time window.

    Args:
        component: Set of case IDs.
        cases: ``case_id`` → case data containing ``mo_fingerprint``.

    Returns:
        Dict with ``impersonated_entity``, ``script_phases``, ``pressure_tactics``,
        ``first_seen`` and ``last_seen``.
    """
    from src.enterprise.linkage import _coerce_fingerprint

    impersonators: dict[str, int] = {}
    phases: set[str] = set()
    tactics: set[str] = set()
    timestamps: list[datetime] = []

    for cid in sorted(component):
        case = cases.get(cid, {})
        mo = _coerce_fingerprint(case.get("mo_fingerprint"))
        impersonated = mo.get("impersonated_entity")
        if impersonated:
            key = str(impersonated)
            impersonators[key] = impersonators.get(key, 0) + 1
        phases.update(str(p) for p in (mo.get("script_phases") or []))
        tactics.update(str(t) for t in (mo.get("pressure_tactics") or []))
        ts = case.get("created_at")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(str(ts).replace("Z", "+00:00")))
            except (ValueError, TypeError):
                continue

    top_impersonator = None
    if impersonators:
        top_impersonator = max(sorted(impersonators), key=lambda k: impersonators[k])

    return {
        "impersonated_entity": top_impersonator,
        "script_phases": sorted(phases),
        "pressure_tactics": sorted(tactics),
        "first_seen": min(timestamps).isoformat() if timestamps else None,
        "last_seen": max(timestamps).isoformat() if timestamps else None,
    }
