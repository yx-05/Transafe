"""Tests for the adaptation loop's persistence behaviour.

The loop writes two ``eval_runs`` rows — a baseline and a re-score — and
``/eval/latest`` pairs the two newest rows, calling the older one "before".

That contract makes *when* the baseline is written load-bearing. A cycle can
end without producing a re-score (no misses, no invariant to generalise, or a
proposal below threshold), and if the baseline were written unconditionally it
would become the newest row on its own. ``/eval/latest`` would then pair it
with the previous cycle's re-score and show the comparison **inverted**: the
"after" side labelled "before adaptation" and vice versa.

Reproduced in the live environment, hence this file.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.enterprise import adaptation

MODULE = "src.enterprise.adaptation"


def _patchers(pre_run: dict, *, proposal=None, confidence=0.0, store_calls: list | None = None):
    """Build the patch set for one cycle.

    Args:
        pre_run: Result the baseline ``run_evaluation`` returns.
        proposal: Proposal the generaliser returns, or ``None`` to bail.
        confidence: Confidence to report for the proposal.
        store_calls: Optional list that records ``_store_eval_run`` arguments.

    Returns:
        A list of patchers, ready for ``contextlib.ExitStack``.
    """
    runs = [pre_run, {**pre_run, "run_id": "post-run"}]

    def _record(*args, **kwargs):
        # Note: `store_calls or []` would silently write to a throwaway list
        # whenever the caller passed an empty one, which is every caller.
        if store_calls is not None:
            store_calls.append(args[0].get("run_id"))
        return "stored"

    store = MagicMock(side_effect=_record)

    return [
        patch(
            f"{MODULE}.registry.get_artifact",
            return_value={"content": "R-1: base", "version": 6},
        ),
        patch(f"{MODULE}.emit_event", new_callable=AsyncMock),
        patch(f"{MODULE}.run_evaluation", new_callable=AsyncMock, side_effect=runs),
        patch(f"{MODULE}._store_eval_run", store),
        patch(f"{MODULE}._propose", return_value=(proposal, confidence, {"support": 1.0})),
        patch(f"{MODULE}.check_agnosticism", return_value={"agnostic": True, "violations": []}),
        patch(f"{MODULE}.build_core_patch", return_value="R-1: base\nR-4: patched"),
        patch(
            f"{MODULE}.publish_and_propagate_core",
            new_callable=AsyncMock,
            return_value=({"name": "phone_agent_core", "version": 7}, []),
        ),
        patch(f"{MODULE}.load_eval_ground_truth", return_value={}),
        patch(
            f"{MODULE}.metrics_mod.compute_adaptation_metrics",
            return_value={
                "pre_detection": 0.2,
                "post_detection": 0.9,
                "delta": 0.7,
                "fp_delta": 0.0,
                "newly_detected": ["rt-1"],
                "regressed": [],
            },
        ),
    ]


def _pre_with_misses() -> dict:
    return {
        "run_id": "pre-run",
        "base_variants": {"missed": ["case-1"]},
        "redteam_mutations": {"missed": ["rt-1"]},
        "result": {},
    }


@pytest.mark.asyncio
async def test_a_bailing_cycle_persists_nothing():
    """No misses → nothing written, so the previous pair stays intact."""
    calls: list = []
    empty_pre = {"run_id": "pre-run", "base_variants": {}, "redteam_mutations": {}}
    with contextlib.ExitStack() as stack:
        for patcher in _patchers(empty_pre, store_calls=calls):
            stack.enter_context(patcher)
        result = await adaptation.run_adaptation_loop()

    assert result["outcome"] == "no_misses"
    assert calls == [], "a cycle that learns nothing must not write a lone baseline row"


@pytest.mark.asyncio
async def test_no_proposal_persists_nothing():
    """No invariant to generalise → still nothing written."""
    calls: list = []
    with contextlib.ExitStack() as stack:
        for patcher in _patchers(_pre_with_misses(), proposal=None, store_calls=calls):
            stack.enter_context(patcher)
        result = await adaptation.run_adaptation_loop()

    assert result["outcome"] == "no_proposal"
    assert calls == []


@pytest.mark.asyncio
async def test_baseline_is_written_before_the_rescore():
    """Order is the contract: the older row is what /eval/latest calls "before"."""
    written: list = []
    with contextlib.ExitStack() as stack:
        for patcher in _patchers(
            _pre_with_misses(),
            proposal={"rule_id": "R-4", "rule_text": "..."},
            confidence=0.9,
            store_calls=written,
        ):
            stack.enter_context(patcher)
        result = await adaptation.run_adaptation_loop()

    assert result["outcome"] == "applied"
    assert written == ["pre-run"], "exactly the baseline is stored, and it is stored first"


@pytest.mark.asyncio
async def test_the_baseline_run_is_asked_not_to_persist_itself():
    """``run_evaluation(store=False)`` for the baseline.

    Asserting the flag rather than a side effect: it is the flag that keeps
    ``run_evaluation`` from writing the row before the cycle knows whether a
    re-score will follow.
    """
    run_eval = AsyncMock(side_effect=[_pre_with_misses()])
    with contextlib.ExitStack() as stack:
        for patcher in _patchers(_pre_with_misses(), proposal=None):
            stack.enter_context(patcher)
        stack.enter_context(patch(f"{MODULE}.run_evaluation", run_eval))
        await adaptation.run_adaptation_loop()

    assert run_eval.await_args_list[0].kwargs["store"] is False
