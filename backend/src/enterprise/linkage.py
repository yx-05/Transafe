"""Linkage — L3 deterministic case-pair scoring.

Four independent signals plus a temporal modifier, fused with **noisy-OR**:

    combined = 1 − Π(1 − wᵢ)

Why noisy-OR and not a weighted sum: a weighted sum lets one strong signal be
diluted by missing ones and requires weights that sum to 1 (they don't — the
signals are not mutually exclusive). Noisy-OR is the standard combiner for
independent evidence and is explainable to a risk committee: *each signal
independently fails to explain the link with probability (1 − w); the link
exists unless all of them fail.*

**No LLM adjudicates a link.** Everything in this module is deterministic.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from src.db.vector_store import get_supabase_client

logger = logging.getLogger(__name__)

# ── Signal weights (01_upgrade_plan.md §6.3) ────────────────────────────────
WEIGHT_SHARED_IDENTIFIER = 0.95
WEIGHT_SHARED_DOMAIN = 0.80
MAX_NARRATIVE_WEIGHT = 0.75
NARRATIVE_GATE_COSINE = 0.82
MAX_MO_OVERLAP_WEIGHT = 0.50
TEMPORAL_MULTIPLIER = 1.15
TEMPORAL_WINDOW_HOURS = 72
LINK_THRESHOLD = 0.60

HARD_IDENTIFIER_TYPES = frozenset({"PHONE", "ACCOUNT"})


def score_case_pair(
    case_a: dict[str, Any],
    case_b: dict[str, Any],
    entities_a: list[dict[str, Any]],
    entities_b: list[dict[str, Any]],
    embedding_a: list[float] | None = None,
    embedding_b: list[float] | None = None,
) -> dict[str, Any]:
    """Compute the fused linkage score between two cases.

    Args:
        case_a: First case dict with at least ``id``, ``created_at``, ``mo_fingerprint``.
        case_b: Second case dict.
        entities_a: Resolved entities for ``case_a``.
        entities_b: Resolved entities for ``case_b``.
        embedding_a: 768-dim narrative embedding for ``case_a`` (or None).
        embedding_b: 768-dim narrative embedding for ``case_b`` (or None).

    Returns:
        Dict with ``score`` (float in [0, 1]), ``signals`` (per-signal evidence)
        and ``evidence_case_ids``.
    """
    signals: dict[str, Any] = {}
    weights: list[float] = []

    # Signal 1 — shared hard identifier (PHONE / ACCOUNT): the precision anchor.
    shared_id = _shared_identifier(entities_a, entities_b)
    if shared_id["matched"]:
        signals["shared_identifier"] = shared_id
        weights.append(WEIGHT_SHARED_IDENTIFIER)

    # Signal 2 — shared registrable domain: hosting gets reused.
    shared_domain = _shared_domain(entities_a, entities_b)
    if shared_domain["matched"]:
        signals["shared_domain"] = shared_domain
        weights.append(WEIGHT_SHARED_DOMAIN)

    # Signal 3 — narrative similarity: the recall engine, survives account rotation.
    narrative_sim = _narrative_similarity(
        _coerce_embedding(embedding_a),
        _coerce_embedding(embedding_b),
    )
    if narrative_sim is not None and narrative_sim >= NARRATIVE_GATE_COSINE:
        narrative_weight = min(narrative_sim * MAX_NARRATIVE_WEIGHT, MAX_NARRATIVE_WEIGHT)
        signals["narrative"] = {"cosine": narrative_sim, "weight": round(narrative_weight, 4)}
        weights.append(narrative_weight)
    elif narrative_sim is not None:
        signals["narrative"] = {"cosine": narrative_sim, "below_gate": True}

    # Signal 4 — MO structural overlap: cheap, no LLM, robust.
    mo_overlap = _mo_structural_overlap(
        _coerce_fingerprint(case_a.get("mo_fingerprint")),
        _coerce_fingerprint(case_b.get("mo_fingerprint")),
    )
    if mo_overlap["score"] > 0:
        mo_weight = mo_overlap["score"] * MAX_MO_OVERLAP_WEIGHT
        signals["mo_overlap"] = mo_overlap
        weights.append(mo_weight)

    # Fusion — noisy-OR.
    prob_none = 1.0
    for weight in weights:
        prob_none *= 1.0 - weight
    combined = 1.0 - prob_none if weights else 0.0

    # Temporal modifier. It is a modifier, never a standalone link, and it never
    # inflates a hard-identifier match — 0.95 is already near-proof and must stay
    # distinguishable from certainty.
    #
    # DELIBERATE DEVIATION FROM 02_discovery_design.md §5 — DO NOT "FIX" THIS BACK.
    # The doc's prose applies x1.15 to the fused score unconditionally, but the
    # doc's own unit test (test_score_case_pair_shared_identifier) requires
    # exactly 0.95 for two same-day cases sharing a phone; unconditional boosting
    # yields 0.95*1.15 clamped to 1.0 and fails it. Ruled by team-lead: the test
    # is the tighter contract. A recency boost on top of near-proof buys nothing
    # and destroys the 0.95-vs-1.0 distinction, so the boost is confined to the
    # weak narrative/MO-only pairs, which is where recency actually carries
    # information. Pinned by test_score_case_pair_hard_identifier_not_inflated_by_temporal
    # and test_score_case_pair_temporal_boosts_weak_signals.
    temporal_mult = _temporal_multiplier(case_a.get("created_at"), case_b.get("created_at"))
    if temporal_mult > 1.0:
        apply_boost = not shared_id["matched"]
        if apply_boost:
            combined = min(combined * temporal_mult, 1.0)
        signals["temporal"] = {"multiplier": temporal_mult, "applied": apply_boost}

    combined = min(max(combined, 0.0), 1.0)

    return {
        "score": round(combined, 3),
        "signals": signals,
        "evidence_case_ids": [case_a.get("id"), case_b.get("id")],
    }


def _coerce_fingerprint(value: Any) -> dict[str, Any]:
    """Return an MO fingerprint as a dict, tolerating JSON-string storage."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _coerce_embedding(value: Any) -> list[float] | None:
    """Return an embedding as ``list[float]``, tolerating JSON-string storage.

    ``case_mo.embedding`` comes back from PostgREST as a JSON *string*, not a
    list. ``_narrative_similarity`` then compares two strings: ``len()`` is the
    character count, the elementwise maths never runs, and the function returns
    ``None`` — the narrative signal vanishes with no error and no log line, the
    same failure shape as ``_safe`` swallowing a query into ``[]``. Mirrors
    ``_coerce_fingerprint``.

    Coercion makes the signal *evaluable*, not necessarily *useful*: with the
    current seeded vectors every pair still lands far below the gate and is
    recorded as ``below_gate`` evidence rather than silently omitted.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None
    else:
        parsed = value
    if not isinstance(parsed, list | tuple):
        return None
    try:
        return [float(v) for v in parsed]
    except (TypeError, ValueError):
        return None


def _shared_identifier(
    entities_a: list[dict[str, Any]],
    entities_b: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check for shared PHONE or ACCOUNT entities (near-proof)."""
    norms_a = {
        e.get("value_norm")
        for e in entities_a
        if e.get("entity_type") in HARD_IDENTIFIER_TYPES and e.get("value_norm")
    }
    norms_b = {
        e.get("value_norm")
        for e in entities_b
        if e.get("entity_type") in HARD_IDENTIFIER_TYPES and e.get("value_norm")
    }
    shared = norms_a & norms_b
    if shared:
        return {
            "matched": True,
            "type": "hard_identifier",
            "shared_values": sorted(str(v) for v in shared),
            "weight": WEIGHT_SHARED_IDENTIFIER,
        }
    return {"matched": False}


def _shared_domain(
    entities_a: list[dict[str, Any]],
    entities_b: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check for shared DOMAIN entities."""
    norms_a = {
        e.get("value_norm")
        for e in entities_a
        if e.get("entity_type") == "DOMAIN" and e.get("value_norm")
    }
    norms_b = {
        e.get("value_norm")
        for e in entities_b
        if e.get("entity_type") == "DOMAIN" and e.get("value_norm")
    }
    shared = norms_a & norms_b
    if shared:
        return {
            "matched": True,
            "type": "shared_domain",
            "shared_values": sorted(str(v) for v in shared),
            "weight": WEIGHT_SHARED_DOMAIN,
        }
    return {"matched": False}


def _narrative_similarity(
    emb_a: list[float] | None,
    emb_b: list[float] | None,
) -> float | None:
    """Cosine similarity between two narrative embeddings, or None if unusable."""
    if not emb_a or not emb_b or len(emb_a) != len(emb_b):
        return None
    dot = sum(a * b for a, b in zip(emb_a, emb_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in emb_a))
    norm_b = math.sqrt(sum(b * b for b in emb_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot / (norm_a * norm_b), 4)


def _mo_structural_overlap(
    mo_a: dict[str, Any],
    mo_b: dict[str, Any],
) -> dict[str, Any]:
    """Jaccard over ``script_phases`` ∪ ``pressure_tactics`` ∪ ``impersonated_entity``."""
    set_a: set[str] = set()
    set_b: set[str] = set()
    for key in ("script_phases", "pressure_tactics"):
        set_a.update(str(v) for v in (mo_a.get(key) or []))
        set_b.update(str(v) for v in (mo_b.get(key) or []))
    if mo_a.get("impersonated_entity"):
        set_a.add(str(mo_a["impersonated_entity"]))
    if mo_b.get("impersonated_entity"):
        set_b.add(str(mo_b["impersonated_entity"]))

    if not set_a and not set_b:
        return {"score": 0.0}

    union = set_a | set_b
    intersection = set_a & set_b
    score = len(intersection) / len(union) if union else 0.0
    return {
        "score": round(score, 4),
        "intersection": sorted(intersection),
        "union_size": len(union),
    }


def _temporal_multiplier(ts_a: str | None, ts_b: str | None) -> float:
    """Return 1.15 when the two cases fall within 72 hours of each other, else 1.0."""
    if not ts_a or not ts_b:
        return 1.0
    try:
        dt_a = datetime.fromisoformat(str(ts_a).replace("Z", "+00:00"))
        dt_b = datetime.fromisoformat(str(ts_b).replace("Z", "+00:00"))
        delta = abs((dt_a - dt_b).total_seconds())
    except (ValueError, TypeError):
        return 1.0
    if delta <= TEMPORAL_WINDOW_HOURS * 3600:
        return TEMPORAL_MULTIPLIER
    return 1.0


def compute_blocking_keys(
    case: dict[str, Any],
    entities: list[dict[str, Any]],
) -> list[str]:
    """Compute blocking keys for a case, to avoid O(n²) pairwise scoring.

    Keys cover every normalised entity value, the impersonated entity, and the
    coarse MO signature (``impersonated_entity`` + first two ``script_phases``).

    Args:
        case: Case dict with ``mo_fingerprint``.
        entities: Resolved entities for the case.

    Returns:
        List of blocking key strings.
    """
    keys: list[str] = []

    for ent in entities:
        etype = ent.get("entity_type")
        norm = ent.get("value_norm")
        if etype and norm:
            keys.append(f"ent:{etype}:{norm}")

    mo = _coerce_fingerprint(case.get("mo_fingerprint"))

    impersonated = mo.get("impersonated_entity")
    if impersonated:
        keys.append(f"imp:{str(impersonated).lower()}")

    phases = mo.get("script_phases") or []
    if impersonated and len(phases) >= 2:
        keys.append(f"mo_sig:{str(impersonated).lower()}:{phases[0]}:{phases[1]}")

    return keys


def get_candidate_pairs(
    case_id: str,
    blocking_keys: list[str],
    store: Any = None,
    window_days: int = 14,
) -> list[str]:
    """Fetch candidate case IDs sharing at least one blocking key.

    Typically returns 0-20 candidates rather than *n*, which is what keeps
    on-ingest discovery cheap enough to run in seconds.

    Args:
        case_id: The ingested case ID.
        blocking_keys: Keys from :func:`compute_blocking_keys`.
        store: Optional GraphStore (unused; kept for interface stability).
        window_days: Time window for candidate lookup.

    Returns:
        Sorted list of unique candidate case IDs, excluding ``case_id`` itself.
    """
    del store  # Candidate lookup is table-driven; the store seam stays for parity.

    candidate_ids: set[str] = set()
    entity_keys = [k for k in blocking_keys if k.startswith("ent:")]
    mo_keys = [k for k in blocking_keys if k.startswith(("imp:", "mo_sig:"))]

    try:
        client = get_supabase_client()
    except Exception:
        logger.exception("get_candidate_pairs: Supabase unavailable")
        return []

    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()

    # ── Entity blocking: exact (type, value_norm) lookups ───────────────────
    if entity_keys:
        pairs = []
        for key in entity_keys:
            _, _, remainder = key.partition(":")
            etype, _, norm = remainder.partition(":")
            if etype and norm:
                pairs.append((etype, norm))

        entity_ids: set[str] = set()
        for etype, norm in pairs:
            try:
                res = (
                    client.table("entities")
                    .select("id")
                    .eq("entity_type", etype)
                    .eq("value_norm", norm)
                    .execute()
                )
                for row in getattr(res, "data", None) or []:
                    if row.get("id"):
                        entity_ids.add(str(row["id"]))
            except Exception:
                logger.exception("get_candidate_pairs: entity lookup failed for %s", norm)

        if entity_ids:
            try:
                res = (
                    client.table("case_entity_links")
                    .select("case_id")
                    .in_("entity_id", sorted(entity_ids))
                    .execute()
                )
                for row in getattr(res, "data", None) or []:
                    cid = str(row.get("case_id", ""))
                    if cid and cid != case_id:
                        candidate_ids.add(cid)
            except Exception:
                logger.exception("get_candidate_pairs: case_entity_links lookup failed")

    # ── MO blocking: windowed scan of recent fingerprints ───────────────────
    if mo_keys:
        wanted = set(mo_keys)
        try:
            res = (
                client.table("case_mo")
                .select("case_id, fingerprint")
                .gte("extracted_at", cutoff)
                .execute()
            )
            for row in getattr(res, "data", None) or []:
                cid = str(row.get("case_id", ""))
                if not cid or cid == case_id:
                    continue
                other_keys = set(
                    compute_blocking_keys({"mo_fingerprint": row.get("fingerprint")}, [])
                )
                if other_keys & wanted:
                    candidate_ids.add(cid)
        except Exception:
            logger.exception("get_candidate_pairs: case_mo scan failed")

    return sorted(candidate_ids)
