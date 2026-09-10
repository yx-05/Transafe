"""Adaptation loop — turn an evaluation miss into a better core skill (B7b).

The loop in 07_evaluation.md §6:

    evaluate -> collect misses -> generalise -> auto-approve if confident
             -> publish + propagate -> evaluate again -> report the delta

Two things this module refuses to do:

**It will not manufacture a proposal.** If the misses share no structural
invariant, no patch is proposed and the loop reports that. ``None`` is a normal
outcome, exactly as in :mod:`src.enterprise.generaliser`.

**It will not flatter the result.** The post-adaptation run is a full,
independent evaluation. If the delta is zero or negative it is stored, emitted
with ``warning`` severity, and returned as-is. A rule that did not help is a
finding, not a bug to be papered over.

Auto-approval is gated on *measured* confidence, never on an LLM's self-report:

    confidence = support x (1 - false_fire_rate)

where ``support`` is the fraction of missed cases the candidate rule actually
fires on, and ``false_fire_rate`` is the fraction of the negative controls it
also fires on. A rule that catches every miss but also trips on a third of the
legitimate calls scores 0.67 and stays behind the human gate.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.enterprise import metrics as metrics_mod
from src.enterprise import registry
from src.enterprise.corpus import (
    EVAL_DIR,
    STRUCTURAL_RULE_FEATURES,
    derive_mo,
    load_eval_ground_truth,
    structural_features,
)
from src.enterprise.evaluation import (
    CORE_ARTIFACT_NAME,
    STRUCTURAL_RULE,
    _ground_truth_for,
    _load_corpus,
    parse_core_rules,
    run_evaluation,
)
from src.enterprise.events import emit_event
from src.enterprise.generaliser import (
    build_core_patch,
    check_agnosticism,
    maybe_generalise,
)
from src.enterprise.propagation import publish_and_propagate_core

logger = logging.getLogger(__name__)

#: A patch is applied without a human only when measured confidence exceeds
#: this. Everything at or below it waits in the approval queue.
AUTO_APPROVE_THRESHOLD = 0.8

#: Used as the patch base when no core artifact has been published yet (for
#: example before the v2 migration has been applied). Deliberately contains no
#: structural escalation rule, so "before" really is before.
DEFAULT_CORE_CONTENT = """# phone_agent_core

Baseline conversational defence for the phone agent.

## Escalation rules

- R-1: Escalate when the caller requests a one-time code or password.
- R-2: Escalate when the caller refuses to be called back on a published number.
"""

_FALLBACK_RULE_TEXT = (
    "Escalate immediately when a caller who claims to represent an official authority "
    "also instructs the customer to keep the call secret and to move funds to another "
    "account, whatever wording, language or institution the caller uses."
)


async def run_adaptation_loop(
    corpus_dir: str | Path | None = None,
    auto_approve_threshold: float = AUTO_APPROVE_THRESHOLD,
    use_llm: bool | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Run one full adaptation cycle and report what changed.

    Args:
        corpus_dir: Corpus root. Defaults to ``backend/seeds/eval``.
        auto_approve_threshold: Measured confidence a proposal must *exceed* to
            be applied without a human.
        use_llm: Force LLM use on or off for MO extraction and generalisation.
        client: Optional injected Supabase client.

    Returns:
        Dict with ``pre``, ``post`` (or ``None``), ``proposal``, ``confidence``,
        ``auto_approved``, ``adaptation`` metrics and ``published`` artifact.
    """
    cycle_id = str(uuid4())
    root = Path(corpus_dir) if corpus_dir else EVAL_DIR
    base_content, base_version = _current_core_artifact(client=client)

    await emit_event(
        layer="compiler",
        event_type="adaptation_started",
        payload={"cycle_id": cycle_id, "threshold": auto_approve_threshold},
        severity="info",
        run_id=cycle_id,
    )

    pre = await run_evaluation(
        corpus_dir=root,
        label="before adaptation",
        core_content=base_content,
        core_version=base_version,
        use_llm=use_llm,
        client=client,
    )
    missed_ids = _missed_ids(pre)

    if not missed_ids:
        await emit_event(
            layer="compiler",
            event_type="adaptation_skipped",
            payload={
                "cycle_id": cycle_id,
                "reason": "no misses to learn from",
                "pre_run_id": pre["run_id"],
            },
            severity="info",
            run_id=cycle_id,
        )
        return _result(cycle_id, pre, None, None, 0.0, False, None, "no_misses")

    cases = _load_corpus(root)
    by_id = {str(c.get("case_id")): c for c in cases}
    missed_cases = [by_id[cid] for cid in missed_ids if cid in by_id]
    negative_cases = [c for c in cases if not c.get("is_scam", False)]

    proposal, confidence, evidence = _propose(
        missed_cases,
        negative_cases,
        base_content,
        use_llm=use_llm,
        client=client,
    )

    if proposal is None:
        await emit_event(
            layer="compiler",
            event_type="generalisation_skipped",
            payload={
                "cycle_id": cycle_id,
                "reason": evidence.get("reason", "no invariant found"),
                "missed": missed_ids,
            },
            severity="warning",
            run_id=cycle_id,
        )
        return _result(cycle_id, pre, None, None, 0.0, False, None, "no_proposal")

    await emit_event(
        layer="compiler",
        event_type="core_patch_proposed",
        payload={
            "cycle_id": cycle_id,
            "rule_id": proposal.get("rule_id"),
            "rule_text": proposal.get("rule_text"),
            "source": proposal.get("source", "generaliser"),
            "confidence": confidence,
            "evidence": evidence,
            "missed": missed_ids,
        },
        severity="warning",
        run_id=cycle_id,
    )

    agnostic = check_agnosticism(str(proposal.get("rule_text") or ""))
    auto_approved = confidence > auto_approve_threshold and bool(agnostic.get("agnostic"))

    if not auto_approved:
        await emit_event(
            layer="compiler",
            event_type="adaptation_awaiting_approval",
            payload={
                "cycle_id": cycle_id,
                "rule_id": proposal.get("rule_id"),
                "confidence": confidence,
                "threshold": auto_approve_threshold,
                "agnostic": bool(agnostic.get("agnostic")),
                "violations": agnostic.get("violations", []),
            },
            severity="warning",
            run_id=cycle_id,
        )
        return _result(
            cycle_id, pre, None, proposal, confidence, False, None, "below_threshold"
        )

    patched_content = build_core_patch(base_content, proposal)
    artifact, receipts = await publish_and_propagate_core(
        patched_content,
        proposal,
        approved_by="auto_adaptation",
        client=client,
    )

    await emit_event(
        layer="registry",
        event_type="core_patch_auto_approved",
        payload={
            "cycle_id": cycle_id,
            "rule_id": proposal.get("rule_id"),
            "confidence": confidence,
            "threshold": auto_approve_threshold,
            "artifact_version": (artifact or {}).get("version"),
            "propagated_to": [r.get("agent_name") for r in receipts or []],
            "persisted": bool(artifact),
        },
        severity="info",
        run_id=cycle_id,
    )

    post = await run_evaluation(
        corpus_dir=root,
        label="after adaptation",
        core_content=patched_content,
        core_version=(artifact or {}).get("version") or base_version,
        use_llm=use_llm,
        client=client,
    )

    ground_truth = load_eval_ground_truth(root)
    adaptation = metrics_mod.compute_adaptation_metrics(
        _results_for(pre, "redteam"),
        _results_for(post, "redteam"),
        _ground_truth_for(ground_truth, "redteam"),
    )

    improved = adaptation["delta"] > 0
    await emit_event(
        layer="compiler",
        event_type="adaptation_completed",
        payload={
            "cycle_id": cycle_id,
            "pre_run_id": pre["run_id"],
            "post_run_id": post["run_id"],
            "pre_detection": adaptation["pre_detection"],
            "post_detection": adaptation["post_detection"],
            "delta": adaptation["delta"],
            "fp_delta": adaptation["fp_delta"],
            "newly_detected": adaptation["newly_detected"],
            "regressed": adaptation["regressed"],
            "improved": improved,
        },
        # A null or negative result is reported loudly rather than quietly.
        severity="info" if improved else "warning",
        run_id=cycle_id,
    )

    return _result(
        cycle_id, pre, post, proposal, confidence, True, artifact, "applied", adaptation
    )


# ── Proposal ─────────────────────────────────────────────────────────────────
def _propose(
    missed_cases: list[dict[str, Any]],
    negative_cases: list[dict[str, Any]],
    base_content: str,
    use_llm: bool | None = None,
    client: Any | None = None,
) -> tuple[dict[str, Any] | None, float, dict[str, Any]]:
    """Propose a core patch for a cohort of missed cases and measure it.

    The LLM generaliser is tried first. Whatever it returns — including nothing
    — the candidate rule is then *measured* against the corpus, and that
    measurement, not the model's opinion, decides the confidence.

    Args:
        missed_cases: Corpus cases the current defence missed.
        negative_cases: Negative controls, used to measure false firing.
        base_content: Current core-skill body.
        use_llm: Force the LLM path on or off.
        client: Optional injected Supabase client.

    Returns:
        ``(proposal | None, confidence, evidence)``.
    """
    proposal: dict[str, Any] | None = None

    if use_llm is not False:
        try:
            campaigns = _approved_campaigns(missed_cases, client=client)
            proposal = maybe_generalise(campaigns, base_content)
            if proposal:
                proposal = {**proposal, "source": "generaliser_llm"}
        except Exception as exc:
            logger.warning("LLM generalisation failed, using deterministic path: %s", exc)
            proposal = None

    support, firing_ids = _rule_support(missed_cases)
    false_fire_rate, false_ids = _false_fire_rate(negative_cases)

    if proposal is not None:
        # Only a rule the detector can actually evaluate can be measured. An
        # unmeasurable rule keeps confidence 0.0 and therefore a human gate.
        if STRUCTURAL_RULE not in parse_core_rules(str(proposal.get("rule_text") or "")):
            return (
                proposal,
                0.0,
                {
                    "reason": "proposed rule is not machine-evaluable; human review required",
                    "support": support,
                    "false_fire_rate": false_fire_rate,
                },
            )
    else:
        if support <= 0.0:
            return (
                None,
                0.0,
                {
                    "reason": "missed cases share no structural invariant",
                    "support": support,
                    "false_fire_rate": false_fire_rate,
                },
            )
        proposal = {
            "found": True,
            "rule_text": _FALLBACK_RULE_TEXT,
            "rule_id": _next_rule_id(base_content),
            "justification": (
                "The missed cases differ in wording and identifiers but share the same "
                "structural sequence, so a structural rule generalises where a phrase "
                "rule cannot."
            ),
            "source_campaigns": sorted(
                {str(c.get("campaign")) for c in missed_cases if c.get("campaign")}
            ),
            "evidence_summary": (
                f"fires on {len(firing_ids)}/{len(missed_cases)} missed cases and "
                f"{len(false_ids)}/{len(negative_cases)} negative controls"
            ),
            "source": "deterministic_fallback",
        }

    confidence = round(support * (1.0 - false_fire_rate), 4)
    evidence = {
        "support": round(support, 4),
        "false_fire_rate": round(false_fire_rate, 4),
        "fires_on": firing_ids,
        "false_fires_on": false_ids,
        "missed_total": len(missed_cases),
        "negative_total": len(negative_cases),
        "formula": "confidence = support x (1 - false_fire_rate)",
    }
    return proposal, confidence, evidence


def _rule_support(cases: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """Fraction of ``cases`` the candidate structural rule fires on."""
    if not cases:
        return 0.0, []
    firing = [
        str(c.get("case_id"))
        for c in cases
        if set(STRUCTURAL_RULE_FEATURES).issubset(structural_features(c.get("transcript") or []))
    ]
    return len(firing) / len(cases), firing


def _false_fire_rate(negatives: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """Fraction of the negative controls the candidate rule would also flag."""
    if not negatives:
        return 0.0, []
    rate, firing = _rule_support(negatives)
    return rate, firing


def _approved_campaigns(
    missed_cases: list[dict[str, Any]],
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Assemble generaliser input: real approved campaigns plus the miss cohort."""
    campaigns: list[dict[str, Any]] = []
    try:
        supabase = client if client is not None else None
        if supabase is not None:
            rows = (
                supabase.table("campaigns")
                .select("*")
                .eq("status", "APPROVED")
                .execute()
            )
            campaigns = [dict(r) for r in (getattr(rows, "data", None) or [])]
    except Exception as exc:  # pragma: no cover - optional enrichment
        logger.debug("approved campaign lookup skipped: %s", exc)
        campaigns = []

    campaigns.append(
        {
            "code": "eval-miss-cohort",
            "mo_fingerprints": [derive_mo(c.get("transcript") or []) for c in missed_cases],
        }
    )
    return campaigns


def _next_rule_id(core_content: str) -> str:
    """Derive the next ``R-n`` id from the current core body."""
    numbers = [int(n) for n in re.findall(r"\bR-(\d+)\b", core_content or "")]
    return f"R-{max(numbers) + 1}" if numbers else "R-1"


# ── Helpers ──────────────────────────────────────────────────────────────────
def _current_core_content(client: Any | None = None) -> str:
    """Return the published core-skill body, or the documented default."""
    return _current_core_artifact(client=client)[0]


def _current_core_artifact(client: Any | None = None) -> tuple[str, int | None]:
    """Return ``(body, version)`` of the published core skill.

    The version travels with the body because every pass below pins an explicit
    ``core_content``, and a pinned body carries no version of its own — without
    it the stored ``artifact_ver`` reads ``phone_agent_core: None`` and the
    console cannot say which configuration a side of the chart represents.
    """
    try:
        artifact = registry.get_artifact(CORE_ARTIFACT_NAME, client=client)
    except Exception as exc:  # pragma: no cover - registry already guards
        logger.warning("core artifact lookup failed: %s", exc)
        artifact = None
    content = str((artifact or {}).get("content") or "").strip()
    version = (artifact or {}).get("version")
    if not content:
        return DEFAULT_CORE_CONTENT, version
    return content, version


def _missed_ids(run: dict[str, Any]) -> list[str]:
    """Collect every missed case id from an evaluation run."""
    missed: list[str] = []
    for key in ("base_variants", "redteam_mutations"):
        missed.extend(str(cid) for cid in (run.get(key) or {}).get("missed", []))
    return missed


def _results_for(run: dict[str, Any], category: str) -> list[dict[str, Any]]:
    """Per-case results of one category from an evaluation run."""
    return [r for r in run.get("results") or [] if r.get("category") == category]


def _result(
    cycle_id: str,
    pre: dict[str, Any],
    post: dict[str, Any] | None,
    proposal: dict[str, Any] | None,
    confidence: float,
    auto_approved: bool,
    artifact: dict[str, Any] | None,
    outcome: str,
    adaptation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the adaptation loop's return value."""
    return {
        "cycle_id": cycle_id,
        "outcome": outcome,
        "finished_at": datetime.now(UTC).isoformat(),
        "pre": pre,
        "post": post,
        "proposal": proposal,
        "confidence": confidence,
        "auto_approved": auto_approved,
        "published_version": (artifact or {}).get("version") if artifact else None,
        "adaptation": adaptation,
        "missed": _missed_ids(pre),
    }
