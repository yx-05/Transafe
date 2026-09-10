"""Evaluation harness — does the defence actually work? (B7, 07_evaluation.md)

Runs the 40-case corpus through the detection pipeline, scores the output with
:mod:`src.enterprise.metrics`, and writes one ``eval_runs`` row per run with the
per-case detail in ``eval_results``.

Two properties this module is built around:

**Every number is derived from a real run.** Nothing is seeded, hardcoded or
nudged. If the "after" run is worse than the "before" run, the negative delta is
what gets stored, emitted and rendered.

**The verdict cannot depend on a live API key.** Detection is a rule engine over
regex-extracted identifiers, phrase matching and structural features. The LLM MO
fingerprint contributes at most :data:`W_MO_MAX` — below
:data:`DETECTION_THRESHOLD` — so it can support a detection but never create one
on its own. A dead ``DEEPSEEK_API_KEY`` changes scores slightly; it cannot change
whether the demo runs.

Detector tiers, mirroring what is actually deployed:

===============================  ======  =======================================
Signal                           Weight  Tier
===============================  ======  =======================================
watchlist PHONE / ACCOUNT hit     0.95   pack artifact (campaign watchlist)
watchlist URL / DOMAIN hit        0.80   pack artifact (campaign watchlist)
signature phrase hit              0.85   pack artifact (phrase gate)
structural escalation rule        0.72   core artifact (only once generalised)
MO structural overlap            <=0.50  supporting evidence only
===============================  ======  =======================================

Signals fuse with the same noisy-OR that :mod:`src.enterprise.linkage` uses, and
the detection threshold is the same 0.60 as ``LINK_THRESHOLD``. That is the whole
mechanism behind the before/after story: rotate the phrases and the identifiers
and the pack tier stops firing; only a core-tier structural rule survives.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from src.db.vector_store import get_supabase_client
from src.enterprise import metrics as metrics_mod
from src.enterprise import registry
from src.enterprise.corpus import (
    EVAL_DIR,
    STRUCTURAL_RULE_FEATURES,
    campaign_profile,
    derive_mo,
    load_eval_ground_truth,
    matched_signature_phrases,
    normalised_entities,
    structural_features,
)
from src.enterprise.events import emit_event
from src.enterprise.linkage import _mo_structural_overlap
from src.enterprise.mo_extractor import extract_mo_fingerprint

logger = logging.getLogger(__name__)

EVAL_RUNS_TABLE = "eval_runs"
EVAL_RESULTS_TABLE = "eval_results"
CORE_ARTIFACT_NAME = "phone_agent_core"

#: Same threshold as ``linkage.LINK_THRESHOLD`` — one bar for "this is the
#: same thing", used for both linking and detecting.
DETECTION_THRESHOLD = 0.60

W_HARD_IDENTIFIER = 0.95
W_SOFT_IDENTIFIER = 0.80
W_SIGNATURE_PHRASE = 0.85
W_STRUCTURAL_RULE = 0.72
W_MO_MAX = 0.50

STRUCTURAL_RULE = "structural_escalation"

_HARD_TYPES = frozenset({"PHONE", "ACCOUNT"})
_SOFT_TYPES = frozenset({"URL", "DOMAIN"})

# Vocabulary used to recognise a *generalised* structural rule in a core-skill
# body. Deliberately generic: a rule that names a campaign would have been
# rejected by ``generaliser.validate_campaign_agnostic`` before it got here.
_CORE_AUTHORITY_TERMS = (
    "authority",
    "official",
    "regulator",
    "law enforcement",
    "government",
    "officer",
    "agency",
    "police",
)
_CORE_ISOLATION_TERMS = (
    "secret",
    "secrecy",
    "isolat",
    "confidential",
    "not to tell",
    "tell no one",
    "stay on the line",
    "discourag",
    "dissuad",
    "prevent",
    "verification",
    "verify",
)

#: A rule body runs from its ``R-n`` marker to the next marker or blank line, so
#: a rule that wraps across lines is still read as one rule — and a rule is never
#: conflated with the paragraph that happens to follow it.
_RULE_SPLIT_RE = re.compile(r"(?=\bR-\d+\b)")
_CORE_MONEY_TERMS = (
    "transfer",
    "move funds",
    "move money",
    "remit",
    "payment",
    "third-party account",
    "third party account",
    "funds",
)


# ── Core-rule parsing ────────────────────────────────────────────────────────
def parse_core_rules(core_content: str | None) -> set[str]:
    """Identify which behavioural rules an active core-skill body encodes.

    Only one rule matters to the detector today: a *structural escalation* rule
    that fires on the co-occurrence of an authority claim, an isolation
    instruction and a money-movement instruction, without naming any campaign,
    phrase or identifier. That is precisely the rule
    :mod:`src.enterprise.generaliser` proposes.

    Args:
        core_content: Body of the published ``phone_agent_core`` artifact.

    Returns:
        Set of rule names; empty when the body encodes no recognised rule.
    """
    rules: set[str] = set()
    for block in _rule_blocks(core_content or ""):
        low = block.casefold()
        if (
            any(t in low for t in _CORE_AUTHORITY_TERMS)
            and any(t in low for t in _CORE_ISOLATION_TERMS)
            and any(t in low for t in _CORE_MONEY_TERMS)
        ):
            rules.add(STRUCTURAL_RULE)
    return rules


def _rule_blocks(core_content: str) -> list[str]:
    """Split a core body into one string per rule.

    A rule runs from its ``R-n`` marker to the next marker or to the next blank
    line, whichever comes first. Splitting this way means a rule that wraps over
    several lines is still read as a single rule, while two adjacent rules are
    never merged into one.

    Args:
        core_content: Body of a core-skill artifact.

    Returns:
        Rule bodies. Falls back to the whole paragraph list when the body uses
        no ``R-n`` markers at all.
    """
    blocks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", core_content):
        chunk = paragraph.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in _RULE_SPLIT_RE.split(chunk) if p.strip()]
        blocks.extend(parts or [chunk])
    return blocks


def active_core_rules(
    core_content: str | None = None,
    client: Any | None = None,
) -> tuple[set[str], int | None]:
    """Resolve the active core rules, from an explicit body or from the registry.

    Args:
        core_content: Explicit core body. When ``None`` the published artifact
            is read from the registry.
        client: Optional injected Supabase client.

    Returns:
        ``(rules, version)``. Version is ``None`` when no artifact exists — the
        pre-migration / pre-adaptation state, which must degrade, not raise.
    """
    if core_content is not None:
        return parse_core_rules(core_content), None
    try:
        artifact = registry.get_artifact(CORE_ARTIFACT_NAME, client=client)
    except Exception as exc:  # pragma: no cover - registry already guards
        logger.warning("core artifact lookup failed: %s", exc)
        artifact = None
    if not artifact:
        return set(), None
    return parse_core_rules(str(artifact.get("content") or "")), artifact.get("version")


# ── Detection ────────────────────────────────────────────────────────────────
def _noisy_or(weights: list[float]) -> float:
    """Fuse independent signal weights with a noisy-OR, as linkage does."""
    product = 1.0
    for weight in weights:
        product *= 1.0 - max(0.0, min(1.0, weight))
    return 1.0 - product


def score_case(
    case_data: dict[str, Any],
    profile: dict[str, Any] | None = None,
    core_rules: set[str] | None = None,
    mo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one case against the campaign profile and the active core rules.

    Args:
        case_data: Corpus case with a ``transcript``.
        profile: Campaign profile; defaults to :func:`campaign_profile`.
        core_rules: Active core rules; defaults to none (pre-adaptation).
        mo: MO fingerprint, when one is available.

    Returns:
        Dict with ``score``, ``detected``, ``signals``, ``features`` and
        ``entities``.
    """
    prof = profile or campaign_profile()
    rules = core_rules or set()
    transcript = case_data.get("transcript") or []

    entities = normalised_entities(transcript)
    features = structural_features(transcript)
    signals: list[dict[str, Any]] = []
    weights: list[float] = []

    watch_hard = {
        w["value_norm"] for w in prof["watchlist"] if w["entity_type"] in _HARD_TYPES
    }
    watch_soft = {
        w["value_norm"] for w in prof["watchlist"] if w["entity_type"] in _SOFT_TYPES
    }

    for ent in entities:
        if ent["entity_type"] in _HARD_TYPES and ent["value_norm"] in watch_hard:
            signals.append(
                {
                    "signal": "watchlist_identifier",
                    "tier": "pack",
                    "weight": W_HARD_IDENTIFIER,
                    "detail": f"{ent['entity_type']} {ent['value_norm']}",
                }
            )
            weights.append(W_HARD_IDENTIFIER)
            break

    for ent in entities:
        if ent["entity_type"] in _SOFT_TYPES and ent["value_norm"] in watch_soft:
            signals.append(
                {
                    "signal": "watchlist_domain",
                    "tier": "pack",
                    "weight": W_SOFT_IDENTIFIER,
                    "detail": f"{ent['entity_type']} {ent['value_norm']}",
                }
            )
            weights.append(W_SOFT_IDENTIFIER)
            break

    phrases = matched_signature_phrases(transcript)
    if phrases:
        signals.append(
            {
                "signal": "signature_phrase",
                "tier": "pack",
                "weight": W_SIGNATURE_PHRASE,
                "detail": phrases[0],
            }
        )
        weights.append(W_SIGNATURE_PHRASE)

    if STRUCTURAL_RULE in rules and set(STRUCTURAL_RULE_FEATURES).issubset(features):
        signals.append(
            {
                "signal": STRUCTURAL_RULE,
                "tier": "core",
                "weight": W_STRUCTURAL_RULE,
                "detail": "+".join(STRUCTURAL_RULE_FEATURES),
            }
        )
        weights.append(W_STRUCTURAL_RULE)

    if mo:
        overlap = _mo_structural_overlap(mo, prof["mo"])
        mo_weight = round(float(overlap.get("score", 0.0)) * W_MO_MAX, 4)
        if mo_weight > 0:
            signals.append(
                {
                    "signal": "mo_overlap",
                    "tier": "supporting",
                    "weight": mo_weight,
                    "detail": ", ".join(overlap.get("intersection", [])[:4]),
                }
            )
            weights.append(mo_weight)

    score = round(_noisy_or(weights), 4)
    return {
        "score": score,
        "detected": score >= DETECTION_THRESHOLD,
        "signals": signals,
        "features": sorted(features),
        "entities": entities,
    }


async def _evaluate_single_case(
    case_data: dict[str, Any],
    run_id: str,
    profile: dict[str, Any] | None = None,
    core_rules: set[str] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Run one corpus case through the detection pipeline.

    Args:
        case_data: Corpus case dict.
        run_id: Eval run identifier, carried onto the stored result.
        profile: Campaign profile; defaults to :func:`campaign_profile`.
        core_rules: Active core rules; empty means pre-adaptation behaviour.
        use_llm: Whether to attempt LLM MO extraction. When it is disabled or
            fails, a deterministic MO is derived from the transcript instead.

    Returns:
        Per-case result dict.
    """
    case_id = str(case_data.get("case_id") or "")
    transcript = case_data.get("transcript") or []
    started = time.perf_counter()

    mo: dict[str, Any] | None = None
    mo_source = "derived"
    if use_llm:
        try:
            mo = extract_mo_fingerprint(case_id, transcript)
            mo_source = "llm" if mo else "derived"
        except Exception as exc:  # never let a dead API key end an eval run
            logger.warning("MO extraction failed for %s: %s", case_id, exc)
            mo = None
    if not mo:
        mo = derive_mo(transcript)

    verdict = score_case(case_data, profile=profile, core_rules=core_rules, mo=mo)
    # Kept as a float: rule-engine scoring is routinely sub-millisecond, and
    # rounding here would report a mean latency of 0 ms for a run that really
    # took time. The integer cast happens once, at the DB column boundary.
    latency_ms = round((time.perf_counter() - started) * 1000, 3)

    return {
        "case_id": case_id,
        "category": case_data.get("category"),
        "run_id": run_id,
        "is_scam": bool(case_data.get("is_scam", False)),
        "detected": verdict["detected"],
        "score": verdict["score"],
        "signals": verdict["signals"],
        "features": verdict["features"],
        "entity_count": len(verdict["entities"]),
        "mo_source": mo_source,
        "latency_ms": latency_ms,
        "variant_note": case_data.get("variant_note"),
    }


# ── Corpus loading ───────────────────────────────────────────────────────────
def _load_corpus(
    corpus_dir: str | Path,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Load corpus cases from disk.

    A missing directory returns ``[]`` rather than raising: an eval run over an
    empty corpus reports zero coverage, which is a truthful and readable
    failure, unlike a stack trace in a demo.

    Args:
        corpus_dir: Root directory containing ``base/``, ``redteam/``, ``noise/``.
        category: Restrict to one category.

    Returns:
        List of case dicts, each tagged with its ``category``.
    """
    root = Path(corpus_dir)
    categories = [category] if category else ["base", "redteam", "noise"]
    cases: list[dict[str, Any]] = []
    for cat in categories:
        folder = root / cat
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("skipping unreadable corpus case %s: %s", path, exc)
                continue
            data.setdefault("category", cat)
            cases.append(data)
    return cases


def _ground_truth_for(
    ground_truth: dict[str, Any],
    category: str,
) -> dict[str, list[str]]:
    """Project the ground-truth document onto one corpus category."""
    if category == "base":
        block = ground_truth.get("base_variants") or {}
        return {
            "expected_detected": list(block.get("expected_detected") or []),
            "expected_fp": list(block.get("expected_fp") or []),
        }
    if category == "redteam":
        block = ground_truth.get("redteam_mutations") or {}
        return {
            "expected_detected": list(block.get("expected_detected") or []),
            "expected_fp": list(block.get("expected_missed") or []),
        }
    block = ground_truth.get("noise") or {}
    return {
        "expected_detected": list(block.get("expected_detected") or []),
        "expected_fp": list(block.get("expected_fp") or []),
    }


# ── Run ──────────────────────────────────────────────────────────────────────
async def run_evaluation(
    corpus_dir: str | Path | None = None,
    run_id: str | None = None,
    label: str | None = None,
    core_content: str | None = None,
    use_llm: bool | None = None,
    store: bool = True,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run the full corpus and return the scored result.

    Args:
        corpus_dir: Corpus root. Defaults to ``backend/seeds/eval``.
        run_id: Run UUID. Generated when omitted.
        label: Human label for the run, e.g. ``"before adaptation"``.
        core_content: Explicit core-skill body to evaluate against. When
            omitted the published artifact is used, so an un-migrated database
            simply means "no core rules yet".
        use_llm: Force LLM MO extraction on or off. Defaults to the
            ``EVAL_USE_LLM`` environment variable (off), which keeps a demo run
            fast and reproducible.
        store: Whether to persist the run.
        client: Optional injected Supabase client.

    Returns:
        Result dict with per-category metrics, per-case results and a summary.
    """
    run_id = run_id or str(uuid4())
    started_at = datetime.now(UTC)
    label = label or f"eval {started_at.strftime('%Y-%m-%d %H:%M:%S')}"
    if use_llm is None:
        use_llm = os.getenv("EVAL_USE_LLM", "0").strip().lower() in {"1", "true", "yes"}

    root = Path(corpus_dir) if corpus_dir else EVAL_DIR
    cases = _load_corpus(root)
    ground_truth = load_eval_ground_truth(root)
    profile = campaign_profile()
    core_rules, core_version = active_core_rules(core_content, client=client)

    await emit_event(
        layer="registry",
        event_type="eval_started",
        payload={
            "run_id": run_id,
            "label": label,
            "corpus_size": len(cases),
            "core_rules": sorted(core_rules),
            "core_version": core_version,
        },
        severity="info",
        run_id=run_id,
    )

    results: list[dict[str, Any]] = []
    for case in cases:
        results.append(
            await _evaluate_single_case(
                case,
                run_id,
                profile=profile,
                core_rules=core_rules,
                use_llm=use_llm,
            )
        )

    by_category: dict[str, list[dict[str, Any]]] = {"base": [], "redteam": [], "noise": []}
    for result in results:
        by_category.setdefault(str(result.get("category")), []).append(result)

    base = metrics_mod.compute_detection_metrics(
        by_category.get("base", []), _ground_truth_for(ground_truth, "base")
    )
    redteam = metrics_mod.compute_detection_metrics(
        by_category.get("redteam", []), _ground_truth_for(ground_truth, "redteam")
    )
    noise = metrics_mod.compute_detection_metrics(
        by_category.get("noise", []), _ground_truth_for(ground_truth, "noise")
    )
    timing = metrics_mod.compute_timing_metrics([])

    latencies = [float(r.get("latency_ms") or 0.0) for r in results]
    summary = metrics_mod.summarise(base, noise, redteam, timing)
    summary["mean_latency_ms"] = round(sum(latencies) / len(latencies), 3) if latencies else 0.0
    summary["core_rules"] = sorted(core_rules)

    artifact_ver = _artifact_versions(core_version, client=client)

    result: dict[str, Any] = {
        "run_id": run_id,
        "label": label,
        "timestamp": started_at.isoformat(),
        "started_at": started_at.isoformat(),
        "corpus_size": len(cases),
        "artifact_ver": artifact_ver,
        "core_rules": sorted(core_rules),
        "base_variants": base,
        "redteam_mutations": redteam,
        "noise": noise,
        "timing": timing,
        "summary": summary,
        "results": results,
    }

    stored_id = _store_eval_run(result, client=client) if store else None
    result["stored_id"] = stored_id
    if store:
        _update_artifact_effectiveness(result, client=client)

    await emit_event(
        layer="registry",
        event_type="eval_completed",
        payload={
            "run_id": run_id,
            "label": label,
            "base_detection": summary["base_detection"],
            "redteam_detection": summary["redteam_detection"],
            "noise_fp": summary["noise_fp"],
            "coverage": summary["coverage"],
            "corpus_size": len(cases),
            "persisted": bool(stored_id),
        },
        severity="info",
        run_id=run_id,
    )
    return result


def _artifact_versions(core_version: int | None, client: Any | None = None) -> dict[str, Any]:
    """Snapshot the artifact versions this run was evaluated against."""
    versions: dict[str, Any] = {CORE_ARTIFACT_NAME: core_version}
    try:
        packs = registry.list_artifacts(tier="pack", client=client)
    except Exception:  # pragma: no cover - registry already guards
        packs = []
    for artifact in packs or []:
        name = artifact.get("name")
        if name:
            versions[str(name)] = artifact.get("version")
    return versions


# ── Persistence ──────────────────────────────────────────────────────────────
def _store_eval_run(result: dict[str, Any], client: Any | None = None) -> str | None:
    """Write one ``eval_runs`` row plus its ``eval_results`` detail rows.

    The row shape follows ``migrations/v2_enterprise.sql`` (``label``,
    ``artifact_ver``, ``started_at``, ``summary``), not the flat column list
    sketched in 07_evaluation.md §3.4 — see the module docstring of the tests
    for the reasoning. Failure to persist is logged and swallowed: an eval run
    that cannot reach the database still produced valid numbers.

    Args:
        result: Output of :func:`run_evaluation`.
        client: Optional injected Supabase client.

    Returns:
        The stored run UUID, or ``None`` when persistence was unavailable.
    """
    summary = dict(result.get("summary") or {})
    summary.setdefault("run_id", result.get("run_id"))
    row = {
        "label": result.get("label") or result.get("run_id"),
        "artifact_ver": result.get("artifact_ver") or {},
        "started_at": result.get("started_at") or result.get("timestamp"),
        "summary": summary,
    }
    run_uuid = result.get("run_id")
    if _is_uuid(run_uuid):
        row["id"] = run_uuid

    try:
        supabase = client if client is not None else get_supabase_client()
        response = supabase.table(EVAL_RUNS_TABLE).insert(row).execute()
    except Exception as exc:
        logger.warning("eval_runs insert failed: %s", exc)
        return None

    stored_id = row.get("id")
    if not stored_id:
        rows = getattr(response, "data", None)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            stored_id = rows[0].get("id")

    if not isinstance(stored_id, str):
        return None

    detail_rows = [
        {
            "run_id": stored_id,
            "variant_id": r.get("case_id"),
            "is_scam": bool(r.get("is_scam")),
            "detected": bool(r.get("detected")),
            "score": int(round(float(r.get("score") or 0.0) * 100)),
            # ``eval_results.latency_ms`` is an integer column; round rather
            # than truncate so a sub-millisecond case is not recorded as 0.
            "latency_ms": int(round(float(r.get("latency_ms") or 0.0))),
        }
        for r in result.get("results") or []
    ]
    if detail_rows:
        try:
            supabase.table(EVAL_RESULTS_TABLE).insert(detail_rows).execute()
        except Exception as exc:
            logger.warning("eval_results insert failed: %s", exc)
    return stored_id


def _update_artifact_effectiveness(
    result: dict[str, Any],
    client: Any | None = None,
) -> bool:
    """Write the run's headline numbers back onto the core artifact.

    Args:
        result: Output of :func:`run_evaluation`.
        client: Optional injected Supabase client.

    Returns:
        ``True`` when effectiveness was recorded.
    """
    summary = result.get("summary") or {}
    try:
        artifact = registry.get_artifact(CORE_ARTIFACT_NAME, client=client)
        if not artifact or not artifact.get("id"):
            return False
        return registry.update_effectiveness(
            str(artifact["id"]),
            {
                "eval_run_id": result.get("run_id"),
                "detected": summary.get("detected", 0),
                "total": summary.get("total", 0),
                "fp": summary.get("false_positives", 0),
                "fp_total": summary.get("fp_total", 0),
                "measured_at": datetime.now(UTC).isoformat(),
            },
            client=client,
        )
    except Exception as exc:
        logger.warning("effectiveness update failed: %s", exc)
        return False


# ── Read paths ───────────────────────────────────────────────────────────────
def _latest_rows(limit: int = 2, client: Any | None = None) -> list[dict[str, Any]]:
    """Fetch the most recent eval runs, newest first; ``[]`` on any failure."""
    try:
        supabase = client if client is not None else get_supabase_client()
        response = (
            supabase.table(EVAL_RUNS_TABLE)
            .select("*")
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        logger.warning("eval_runs read failed: %s", exc)
        return []
    rows = getattr(response, "data", None)
    return [dict(r) for r in rows] if isinstance(rows, list) else []


def _row_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise an ``eval_runs`` row into a flat summary.

    Tolerates both the nested ``summary`` JSONB shape written by
    :func:`_store_eval_run` and the flat column shape used in the design doc.
    """
    summary = row.get("summary")
    summary = dict(summary) if isinstance(summary, dict) else {}
    merged: dict[str, Any] = {**summary, **{k: v for k, v in row.items() if k != "summary"}}
    run_id = merged.get("run_id") or merged.get("id")
    return {
        "run_id": str(run_id) if run_id is not None else None,
        "label": merged.get("label"),
        "started_at": merged.get("started_at") or merged.get("ts"),
        "ts": merged.get("ts") or merged.get("started_at"),
        "base_detection": merged.get("base_detection", 0.0),
        "noise_fp": merged.get("noise_fp", 0.0),
        "redteam_detection": merged.get("redteam_detection", 0.0),
        "detected": merged.get("detected", 0),
        "total": merged.get("total", 0),
        "false_positives": merged.get("false_positives", 0),
        "fp_total": merged.get("fp_total", 0),
        "mean_latency_ms": merged.get("mean_latency_ms", 0),
        "coverage": merged.get("coverage", 0.0),
        "artifact_ver": merged.get("artifact_ver") or {},
    }


def get_latest_comparison(client: Any | None = None) -> dict[str, Any] | None:
    """Return the two most recent eval runs as a before/after comparison.

    Args:
        client: Optional injected Supabase client.

    Returns:
        ``{"before", "after", "delta"}``, or ``None`` when fewer than two runs
        exist (including when the migration has not been applied).
    """
    rows = _latest_rows(2, client=client)
    if len(rows) < 2:
        return None

    after = _row_summary(rows[0])
    before = _row_summary(rows[1])
    return {
        "before": before,
        "after": after,
        "delta": {
            "base_detection": round(
                float(after.get("base_detection") or 0.0)
                - float(before.get("base_detection") or 0.0),
                4,
            ),
            "redteam_detection": round(
                float(after.get("redteam_detection") or 0.0)
                - float(before.get("redteam_detection") or 0.0),
                4,
            ),
            "noise_fp": round(
                float(after.get("noise_fp") or 0.0) - float(before.get("noise_fp") or 0.0),
                4,
            ),
        },
    }


def get_eval_comparison(client: Any | None = None) -> dict[str, Any]:
    """Return the before/after comparison in the shape the console consumes.

    Differs from :func:`get_latest_comparison` only in shape: the console needs
    ``{run_id, label, started_at, detected, total, false_positives, fp_total,
    mean_latency_ms, artifact_ver}`` per side and must render *something* when
    only one run (or no run) exists.

    Args:
        client: Optional injected Supabase client.

    Returns:
        ``{"before": ... | None, "after": ... | None}``.
    """
    rows = _latest_rows(2, client=client)
    summaries = [_row_summary(row) for row in rows]

    def project(summary: dict[str, Any] | None) -> dict[str, Any] | None:
        if summary is None:
            return None
        return {
            "run_id": summary.get("run_id"),
            "label": summary.get("label"),
            "started_at": summary.get("started_at"),
            "detected": summary.get("detected", 0),
            "total": summary.get("total", 0),
            "false_positives": summary.get("false_positives", 0),
            "fp_total": summary.get("fp_total", 0),
            "mean_latency_ms": summary.get("mean_latency_ms", 0),
            "artifact_ver": summary.get("artifact_ver") or {},
        }

    after = project(summaries[0]) if summaries else None
    before = project(summaries[1]) if len(summaries) > 1 else None
    return {"before": before, "after": after}


async def run_adaptation_evaluation(
    corpus_dir: str | Path | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run the B7b adaptation loop (07_evaluation.md §6).

    Thin delegation to :mod:`src.enterprise.adaptation`; imported lazily because
    that module evaluates, which would otherwise be a circular import.

    Args:
        corpus_dir: Corpus root.
        client: Optional injected Supabase client.

    Returns:
        The adaptation loop result.
    """
    from src.enterprise.adaptation import run_adaptation_loop

    return await run_adaptation_loop(corpus_dir=corpus_dir, client=client)


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _is_uuid(value: Any) -> bool:
    """Return True when ``value`` is a string holding a well-formed UUID."""
    if not isinstance(value, str) or not _UUID_RE.match(value):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True
