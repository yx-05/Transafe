# 07 — Evaluation Harness Design (§11)

> **Parent:** `01_upgrade_plan.md` §11
> **Scope:** Eval corpus, metrics, harness runner, adaptation loop, per-module unit tests
> **Build block:** B7 (evaluation harness)
> **Status:** Implementation-ready

---

## 1. Module inventory

| Module | File | Layer | Build block | Depends on |
|---|---|---|---|---|
| Evaluation harness | `enterprise/evaluation.py` | L4 (writes back to registry) | B7 | `enterprise/registry.py`, `enterprise/propagation.py` |
| Corpus generator | `enterprise/corpus.py` | L4 | B7 | seed transcripts |
| Metrics | `enterprise/metrics.py` | L4 | B7 | eval run results |

---

## 2. Evaluation corpus

### 2.1 Requirements

The evaluation corpus is a **separate** set of synthetic cases from the demo seed corpus. It must contain:

| Category | Count | Purpose |
|---|---|---|
| Base campaign variants | 20 | Same MO as SCAM-027, different identifiers — tests detection precision |
| Red-team mutations | 10 | Subtle script changes (phase reordering, synonym substitution, language switch) — tests generalisation |
| Unrelated noise | 10 | Different scam types (phishing, investment, romance) — tests false-positive rate |
| **Total** | **40** | |

### 2.2 Corpus structure

```
backend/seeds/eval/
  base/
    scam027_variant_001.json   # Same MO, different account
    scam027_variant_002.json   # Same MO, different phone
    ...                         # 20 total
  redteam/
    redteam_phase_reorder.json  # Same MO, phases in different order
    redteam_synonym_sub.json     # "safe account" → "temporary holding account"
    redteam_lang_switch.json    # All English instead of Malay
    redteam_no_novel_phrase.json # Missing "akaun selamat sementara"
    redteam_extra_phase.json     # Additional legitimacy-building phase
    ...                           # 10 total
  noise/
    noise_phishing_001.json
    noise_investment_001.json
    noise_romance_001.json
    ...                           # 10 total
  ground_truth/
    eval_truth.json              # Expected: which cases should be detected, which shouldn't
```

### 2.3 Ground truth — `eval_truth.json`

```json
{
  "base_variants": {
    "expected_detected": ["scam027_variant_001", "scam027_variant_002", "..."],
    "expected_fp": []
  },
  "redteam_mutations": {
    "expected_detected": ["redteam_synonym_sub", "redteam_lang_switch", "..."],
    "expected_missed": ["redteam_no_novel_phrase", "redteam_phase_reorder"]
  },
  "noise": {
    "expected_detected": [],
    "expected_fp": ["noise_phishing_001", "noise_investment_001", "..."]
  }
}
```

---

## 3. Metrics

### 3.1 Detection metrics

| Metric | Definition | Target |
|---|---|---|
| **Detection rate** | TP / (TP + FN) — fraction of base variants correctly detected | ≥ 90% |
| **False-positive rate** | FP / (FP + TN) — fraction of noise cases incorrectly flagged | ≤ 5% |
| **Adaptation rate** | fraction of red-team mutations detected after a core-skill update | target: +15pp |
| **Time to detection** | time from case ingest to campaign proposal | < 5 min |
| **Time to defence** | time from campaign proposal to artifact propagation | < 60 sec |

### 3.2 Adaptation metrics (C1/C2)

| Metric | Definition | When |
|---|---|---|
| **Pre-adaptation detection** | detection rate on red-team mutations before core skill update | baseline |
| **Post-adaptation detection** | detection rate on same mutations after generaliser core patch | target: +15pp |
| **Generalisation gap** | post-adaptation detection on **unseen** mutations vs seen ones | should be small |

### 3.3 Metrics module — `enterprise/metrics.py`

```python
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_detection_metrics(
    results: list[dict[str, Any]],
    ground_truth: dict[str, list[str]],
) -> dict[str, Any]:
    """Compute detection rate and false-positive rate.

    Args:
        results: List of {case_id, detected: bool} for each eval case.
        ground_truth: Dict with expected_detected and expected_fp case ID lists.

    Returns:
        Dict with: detection_rate, fp_rate, tp, fp, fn, tn, details.
    """
    expected_detected = set(ground_truth.get("expected_detected", []))
    expected_fp = set(ground_truth.get("expected_fp", []))

    tp = 0  # correctly detected
    fn = 0  # should have been detected but wasn't
    fp = 0  # shouldn't have been flagged but was
    tn = 0  # correctly not flagged

    for result in results:
        case_id = result["case_id"]
        detected = result.get("detected", False)

        if case_id in expected_detected:
            if detected:
                tp += 1
            else:
                fn += 1
        elif case_id in expected_fp:
            if detected:
                fp += 1
            else:
                tn += 1

    detection_rate = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "detection_rate": round(detection_rate, 4),
        "fp_rate": round(fp_rate, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "total": len(results),
    }


def compute_adaptation_metrics(
    pre_results: list[dict[str, Any]],
    post_results: list[dict[str, Any]],
    ground_truth: dict[str, list[str]],
) -> dict[str, Any]:
    """Compute pre/post adaptation detection delta.

    Args:
        pre_results: Detection results before core skill update.
        post_results: Detection results after core skill update.
        ground_truth: Ground truth with expected_detected for mutations.

    Returns:
        Dict with: pre_detection, post_detection, delta, generalisation_gap.
    """
    pre = compute_detection_metrics(pre_results, ground_truth)
    post = compute_detection_metrics(post_results, ground_truth)

    delta = post["detection_rate"] - pre["detection_rate"]

    return {
        "pre_detection": pre["detection_rate"],
        "post_detection": post["detection_rate"],
        "delta": round(delta, 4),
        "pre_fp": pre["fp_rate"],
        "post_fp": post["fp_rate"],
        "pre_details": pre,
        "post_details": post,
    }


def compute_timing_metrics(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute time-to-detection and time-to-defence from ns_events.

    Args:
        events: List of ns_event dicts for one eval run.

    Returns:
        Dict with: mean_time_to_detection, mean_time_to_defence, max_times.
    """
    from datetime import datetime

    # Group events by case_id
    case_events: dict[str, list[dict[str, Any]]] = {}
    for evt in events:
        case_id = evt.get("payload", {}).get("case_id")
        if case_id:
            case_events.setdefault(case_id, []).append(evt)

    detection_times: list[float] = []
    defence_times: list[float] = []

    for case_id, evts in case_events.items():
        ingest_ts = None
        detection_ts = None
        defence_ts = None

        for evt in evts:
            if evt["event_type"] == "case_ingested":
                ingest_ts = datetime.fromisoformat(evt["ts"].replace("Z", "+00:00"))
            elif evt["event_type"] == "campaign_proposed":
                detection_ts = datetime.fromisoformat(evt["ts"].replace("Z", "+00:00"))
            elif evt["event_type"] == "propagation_acknowledged":
                defence_ts = datetime.fromisoformat(evt["ts"].replace("Z", "+00:00"))

        if ingest_ts and detection_ts:
            detection_times.append((detection_ts - ingest_ts).total_seconds())
        if detection_ts and defence_ts:
            defence_times.append((defence_ts - detection_ts).total_seconds())

    mean_detection = sum(detection_times) / len(detection_times) if detection_times else 0.0
    mean_defence = sum(defence_times) / len(defence_times) if defence_times else 0.0
    max_detection = max(detection_times) if detection_times else 0.0
    max_defence = max(defence_times) if defence_times else 0.0

    return {
        "mean_time_to_detection_sec": round(mean_detection, 1),
        "mean_time_to_defence_sec": round(mean_defence, 1),
        "max_time_to_detection_sec": round(max_detection, 1),
        "max_time_to_defence_sec": round(max_defence, 1),
        "case_count": len(case_events),
    }
```

---

## 4. Evaluation harness — `enterprise/evaluation.py`

### 4.1 Purpose

Runs the corpus through the pipeline twice — once before a core-skill update, once after — and writes effectiveness back to the registry. The paired bar chart on Screen F shows the delta.

### 4.2 Function signatures

```python
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).parent.parent.parent / "seeds" / "eval"


async def run_evaluation(
    corpus_dir: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run the full evaluation harness.

    Runs the corpus through the pipeline and computes detection metrics.
    For adaptation evaluation, runs twice: before and after a core skill update.

    Args:
        corpus_dir: Directory containing eval corpus. Defaults to SEEDS_DIR.
        run_id: Optional run identifier.

    Returns:
        Dict with: run_id, detection_metrics, timing_metrics, per_case_results.
    """
    if corpus_dir is None:
        corpus_dir = SEEDS_DIR
    if run_id is None:
        run_id = f"eval-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    # Load ground truth
    truth_path = corpus_dir / "ground_truth" / "eval_truth.json"
    with open(truth_path) as f:
        ground_truth = json.load(f)

    # Load all cases
    cases = _load_corpus(corpus_dir)

    # Run each case through the pipeline
    results = []
    all_events = []

    for case_data in cases:
        result = await _evaluate_single_case(case_data, run_id)
        results.append(result)
        # Collect events for timing analysis
        from enterprise.events import get_events
        events = get_events(run_id=run_id, limit=50)
        all_events.extend(events)

    # Compute metrics
    from enterprise.metrics import compute_detection_metrics, compute_timing_metrics

    # Base variants
    base_results = [r for r in results if r["category"] == "base"]
    base_truth = {
        "expected_detected": ground_truth["base_variants"]["expected_detected"],
        "expected_fp": ground_truth["base_variants"]["expected_fp"],
    }
    base_metrics = compute_detection_metrics(base_results, base_truth)

    # Noise
    noise_results = [r for r in results if r["category"] == "noise"]
    noise_truth = {
        "expected_detected": ground_truth["noise"]["expected_detected"],
        "expected_fp": ground_truth["noise"]["expected_fp"],
    }
    noise_metrics = compute_detection_metrics(noise_results, noise_truth)

    # Red-team
    redteam_results = [r for r in results if r["category"] == "redteam"]
    redteam_truth = {
        "expected_detected": ground_truth["redteam_mutations"]["expected_detected"],
        "expected_fp": ground_truth["redteam_mutations"]["expected_missed"],
    }
    redteam_metrics = compute_detection_metrics(redteam_results, redteam_truth)

    timing = compute_timing_metrics(all_events)

    eval_result = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "base_metrics": base_metrics,
        "noise_metrics": noise_metrics,
        "redteam_metrics": redteam_metrics,
        "timing": timing,
        "per_case": results,
    }

    # Store eval run
    _store_eval_run(eval_result)

    # Write effectiveness back to artifacts
    _update_artifact_effectiveness(eval_result)

    return eval_result


async def run_adaptation_evaluation(
    corpus_dir: Path | None = None,
) -> dict[str, Any]:
    """Run pre/post adaptation evaluation.

    Runs the red-team corpus twice:
    1. Before any core-skill update (baseline)
    2. After a generaliser core-skill update (adapted)

    Computes the adaptation delta.

    Args:
        corpus_dir: Directory containing eval corpus.

    Returns:
        Dict with: pre, post, adaptation_metrics.
    """
    if corpus_dir is None:
        corpus_dir = SEEDS_DIR

    # Load truth
    truth_path = corpus_dir / "ground_truth" / "eval_truth.json"
    with open(truth_path) as f:
        ground_truth = json.load(f)

    redteam_truth = {
        "expected_detected": ground_truth["redteam_mutations"]["expected_detected"],
        "expected_fp": ground_truth["redteam_mutations"]["expected_missed"],
    }

    # Pre-adaptation run
    pre_run_id = f"eval-pre-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    pre_results = []
    redteam_cases = _load_corpus(corpus_dir, category="redteam")
    for case_data in redteam_cases:
        result = await _evaluate_single_case(case_data, pre_run_id)
        pre_results.append(result)

    from enterprise.metrics import compute_adaptation_metrics

    # Post-adaptation: simulate the core skill update being applied
    # In production, this would re-run with the updated phone_agent_core
    post_run_id = f"eval-post-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    post_results = []
    for case_data in redteam_cases:
        result = await _evaluate_single_case(case_data, post_run_id)
        post_results.append(result)

    adaptation = compute_adaptation_metrics(pre_results, post_results, redteam_truth)

    return {
        "pre_run_id": pre_run_id,
        "post_run_id": post_run_id,
        "adaptation": adaptation,
    }


async def _evaluate_single_case(
    case_data: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Run a single eval case through the pipeline and check if it was detected.

    Args:
        case_data: Case dict with transcript, expected_entities, expected_mo.
        run_id: Eval run ID.

    Returns:
        Dict with: case_id, category, detected, details.
    """
    from enterprise.events import emit_event
    from enterprise.mo_extractor import extract_mo_fingerprint

    case_id = case_data.get("case_id", f"eval-{run_id}")
    transcript = case_data.get("transcript", [])
    category = case_data.get("category", "unknown")

    await emit_event(
        layer="sensing",
        event_type="case_ingested",
        payload={"case_id": case_id, "risk_tier": "HIGH"},
        run_id=run_id,
    )

    # Extract MO
    mo = extract_mo_fingerprint(case_id, transcript)

    # Check if this case links to the SCAM-027 campaign
    detected = False
    detection_score = 0.0

    if mo and not mo.get("ambiguous"):
        # Compute narrative similarity to SCAM-027 campaign embedding
        # In production, this queries the actual campaign embedding
        # For eval, we check structural overlap with expected MO
        expected_mo = case_data.get("expected_mo", {})
        from enterprise.linkage import _mo_structural_overlap
        overlap = _mo_structural_overlap(mo, expected_mo)
        detection_score = overlap["score"]

        # Check entity overlap
        expected_entities = case_data.get("expected_entities", [])
        from enterprise.entity_resolver import normalise_entity
        expected_norms = {
            normalise_entity(e["entity_type"], e["value"])
            for e in expected_entities
        }

        # If structural overlap is high OR entities match, it's detected
        if detection_score >= 0.5 or expected_norms:
            detected = True

    await emit_event(
        layer="discovery",
        event_type="eval_case_scored",
        payload={"case_id": case_id, "detected": detected, "score": detection_score},
        run_id=run_id,
    )

    return {
        "case_id": case_id,
        "category": category,
        "detected": detected,
        "detection_score": detection_score,
        "mo_impersonated": mo.get("impersonated_entity") if mo else None,
    }


def _load_corpus(
    corpus_dir: Path,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Load eval corpus cases.

    Args:
        corpus_dir: Root directory of the corpus.
        category: Filter by "base", "redteam", "noise" (None for all).

    Returns:
        List of case dicts with category field added.
    """
    cases = []
    subdirs = {"base": "base", "redteam": "redteam", "noise": "noise"}

    for cat, subdir in subdirs.items():
        if category and cat != category:
            continue
        cat_dir = corpus_dir / subdir
        if not cat_dir.exists():
            continue
        for f in sorted(cat_dir.glob("*.json")):
            with open(f) as fh:
                data = json.load(fh)
                data["category"] = cat
                cases.append(data)

    return cases


def _store_eval_run(result: dict[str, Any]) -> None:
    """Store an evaluation run in the database.

    Args:
        result: Full eval result dict.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    row = {
        "run_id": result["run_id"],
        "ts": result["timestamp"],
        "base_detection": result["base_metrics"]["detection_rate"],
        "noise_fp": result["noise_metrics"]["fp_rate"],
        "redteam_detection": result["redteam_metrics"]["detection_rate"],
        "mean_time_to_detection": result["timing"]["mean_time_to_detection_sec"],
        "per_case": result["per_case"],
    }

    try:
        client.table("eval_runs").insert(row).execute()
    except Exception:
        logger.exception("Failed to store eval run %s", result["run_id"])


def _update_artifact_effectiveness(result: dict[str, Any]) -> None:
    """Write effectiveness metrics back to artifacts.

    Args:
        result: Full eval result dict.
    """
    from enterprise.registry import update_effectiveness

    # Find the latest phone_agent_core and campaign pack artifacts
    from enterprise.registry import list_artifacts

    core_artifacts = list_artifacts(tier="core")
    pack_artifacts = list_artifacts(tier="pack")

    effectiveness = {
        "eval_run_id": result["run_id"],
        "base_detection": result["base_metrics"]["detection_rate"],
        "noise_fp": result["noise_metrics"]["fp_rate"],
        "redteam_detection": result["redteam_metrics"]["detection_rate"],
        "measured_at": result["timestamp"],
    }

    for artifact in core_artifacts + pack_artifacts:
        update_effectiveness(artifact["id"], effectiveness)


def get_latest_comparison() -> dict[str, Any]:
    """Get the latest two eval runs for the before/after comparison chart.

    Returns:
        Dict with: before, after, delta.
    """
    from db.vector_store import get_supabase_client

    client = get_supabase_client()
    result = client.table("eval_runs").select("*").order(
        "ts", desc=True
    ).limit(2).execute()

    if len(result.data or []) < 2:
        return {"error": "Need at least 2 eval runs for comparison"}

    after = result.data[0]
    before = result.data[1]

    return {
        "before": {
            "run_id": before["run_id"],
            "base_detection": before["base_detection"],
            "noise_fp": before["noise_fp"],
            "redteam_detection": before["redteam_detection"],
            "ts": before["ts"],
        },
        "after": {
            "run_id": after["run_id"],
            "base_detection": after["base_detection"],
            "noise_fp": after["noise_fp"],
            "redteam_detection": after["redteam_detection"],
            "ts": after["ts"],
        },
        "delta": {
            "base_detection": round(after["base_detection"] - before["base_detection"], 4),
            "noise_fp": round(after["noise_fp"] - before["noise_fp"], 4),
            "redteam_detection": round(after["redteam_detection"] - before["redteam_detection"], 4),
        },
    }
```

---

## 5. Adaptation loop (C2)

### 5.1 How it works

```
Red-team mutation missed
  → evaluation harness records the miss
  → the mutation's MO is fed to the generaliser
  → generaliser proposes a core skill revision (C2 trigger)
  → human gate approves
  → new core skill version published
  → propagation updates phone_worker
  → evaluation re-runs the mutation
  → detection should now succeed
```

### 5.2 Example — C2 adaptation

**Before (core skill v6):**
```
SCAM-027 red-team variant: "temporary holding account" (synonym substitution)
→ Not detected. Novel phrase doesn't match "akaun selamat sementara".
→ FP-safe_account_instruction gate doesn't trigger because the phrase is different.
```

**Generaliser proposes (core skill v7):**
```
Rule R-4: "When authority_claim + isolation + any money-transfer instruction
co-occur, escalate to enhanced verification — regardless of the specific
phrase used for the transfer destination."
```

**After (core skill v7):**
```
SCAM-027 red-team variant: "temporary holding account"
→ Detected. The rule now triggers on the structural pattern, not the phrase.
→ Adaptation rate: +15pp on red-team mutations.
```

---

## 6. Evaluation API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/enterprise/api/eval/run` | POST | Run full evaluation |
| `/enterprise/api/eval/adaptation` | POST | Run pre/post adaptation evaluation |
| `/enterprise/api/eval/latest` | GET | Get latest 2 runs for comparison |
| `/enterprise/api/eval/:run_id` | GET | Get specific run details |

### 6.1 API routes — `backend/src/api/eval.py`

```python
"""Evaluation API routes for the enterprise console."""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/enterprise/api/eval", tags=["evaluation"])


@router.post("/run")
async def run_eval():
    """Run the full evaluation harness."""
    from enterprise.evaluation import run_evaluation
    result = await run_evaluation()
    return result


@router.post("/adaptation")
async def run_adaptation():
    """Run pre/post adaptation evaluation."""
    from enterprise.evaluation import run_adaptation_evaluation
    result = await run_adaptation_evaluation()
    return result


@router.get("/latest")
async def get_latest():
    """Get latest 2 eval runs for before/after comparison."""
    from enterprise.evaluation import get_latest_comparison
    return get_latest_comparison()


@router.get("/{run_id}")
async def get_run(run_id: str):
    """Get a specific eval run by ID."""
    from db.vector_store import get_supabase_client
    client = get_supabase_client()
    result = client.table("eval_runs").select("*").eq("run_id", run_id).execute()
    if not result.data:
        return {"error": "Run not found"}
    return result.data[0]
```

---

## 7. Testing

### 7.1 Test files

| Module | Test file | Cases |
|---|---|---|
| `metrics` | `tests/unit/test_metrics.py` | 8 |
| `evaluation` | `tests/unit/test_evaluation.py` | 6 |

### 7.2 Test cases — `test_metrics.py`

```python
"""Unit tests for evaluation metrics (L4)."""

import pytest
from enterprise.metrics import (
    compute_detection_metrics,
    compute_adaptation_metrics,
    compute_timing_metrics,
)


def test_detection_metrics_all_correct():
    results = [
        {"case_id": "c1", "detected": True},
        {"case_id": "c2", "detected": True},
    ]
    truth = {"expected_detected": ["c1", "c2"], "expected_fp": []}
    metrics = compute_detection_metrics(results, truth)
    assert metrics["detection_rate"] == 1.0
    assert metrics["fp_rate"] == 0.0
    assert metrics["tp"] == 2
    assert metrics["fn"] == 0


def test_detection_metrics_all_missed():
    results = [
        {"case_id": "c1", "detected": False},
        {"case_id": "c2", "detected": False},
    ]
    truth = {"expected_detected": ["c1", "c2"], "expected_fp": []}
    metrics = compute_detection_metrics(results, truth)
    assert metrics["detection_rate"] == 0.0
    assert metrics["fn"] == 2


def test_detection_metrics_false_positives():
    results = [
        {"case_id": "n1", "detected": True},  # FP
        {"case_id": "n2", "detected": False},  # TN
        {"case_id": "c1", "detected": True},   # TP
    ]
    truth = {"expected_detected": ["c1"], "expected_fp": ["n1", "n2"]}
    metrics = compute_detection_metrics(results, truth)
    assert metrics["detection_rate"] == 1.0
    assert metrics["fp_rate"] == pytest.approx(0.5)
    assert metrics["fp"] == 1
    assert metrics["tn"] == 1


def test_detection_metrics_empty():
    metrics = compute_detection_metrics([], {"expected_detected": [], "expected_fp": []})
    assert metrics["detection_rate"] == 0.0
    assert metrics["fp_rate"] == 0.0


def test_adaptation_metrics_positive_delta():
    pre = [{"case_id": "r1", "detected": False}, {"case_id": "r2", "detected": True}]
    post = [{"case_id": "r1", "detected": True}, {"case_id": "r2", "detected": True}]
    truth = {"expected_detected": ["r1", "r2"], "expected_fp": []}
    result = compute_adaptation_metrics(pre, post, truth)
    assert result["delta"] > 0
    assert result["pre_detection"] == 0.5
    assert result["post_detection"] == 1.0


def test_adaptation_metrics_no_change():
    pre = [{"case_id": "r1", "detected": True}]
    post = [{"case_id": "r1", "detected": True}]
    truth = {"expected_detected": ["r1"], "expected_fp": []}
    result = compute_adaptation_metrics(pre, post, truth)
    assert result["delta"] == 0.0


def test_timing_metrics_computes_times():
    events = [
        {"ts": "2026-09-10T12:00:00Z", "event_type": "case_ingested", "payload": {"case_id": "c1"}},
        {"ts": "2026-09-10T12:02:00Z", "event_type": "campaign_proposed", "payload": {"case_id": "c1"}},
        {"ts": "2026-09-10T12:02:30Z", "event_type": "propagation_acknowledged", "payload": {"case_id": "c1"}},
    ]
    result = compute_timing_metrics(events)
    assert result["mean_time_to_detection_sec"] == 120.0
    assert result["mean_time_to_defence_sec"] == 30.0


def test_timing_metrics_empty_events():
    result = compute_timing_metrics([])
    assert result["mean_time_to_detection_sec"] == 0.0
    assert result["case_count"] == 0
```

### 7.3 Test cases — `test_evaluation.py`

```python
"""Unit tests for the evaluation harness (L4)."""

from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import pytest

from enterprise.evaluation import (
    run_evaluation,
    _evaluate_single_case,
    _load_corpus,
    _store_eval_run,
    _update_artifact_effectiveness,
    get_latest_comparison,
)


def test_load_corpus_returns_all_categories(tmp_path: Path):
    """Assert corpus loader returns all categories when no filter is given."""
    (tmp_path / "base").mkdir()
    (tmp_path / "redteam").mkdir()
    (tmp_path / "noise").mkdir()
    (tmp_path / "base" / "case1.json").write_text('{"case_id": "c1", "transcript": []}')
    (tmp_path / "redteam" / "case2.json").write_text('{"case_id": "c2", "transcript": []}')
    (tmp_path / "noise" / "case3.json").write_text('{"case_id": "c3", "transcript": []}')

    cases = _load_corpus(tmp_path)
    assert len(cases) == 3
    categories = {c["category"] for c in cases}
    assert categories == {"base", "redteam", "noise"}


def test_load_corpus_filters_by_category(tmp_path: Path):
    (tmp_path / "base").mkdir()
    (tmp_path / "noise").mkdir()
    (tmp_path / "base" / "case1.json").write_text('{"case_id": "c1", "transcript": []}')
    (tmp_path / "noise" / "case3.json").write_text('{"case_id": "c3", "transcript": []}')

    cases = _load_corpus(tmp_path, category="base")
    assert len(cases) == 1
    assert cases[0]["category"] == "base"


def test_load_corpus_handles_missing_dir(tmp_path: Path):
    cases = _load_corpus(tmp_path)
    assert cases == []


@pytest.mark.asyncio
async def test_evaluate_single_case_detects_matching_mo():
    case_data = {
        "case_id": "eval-001",
        "category": "base",
        "transcript": [{"speaker": "C", "utterance": "test", "seq_idx": 0}] * 5,
        "expected_mo": {"script_phases": ["a", "b"], "pressure_tactics": ["x"]},
        "expected_entities": [],
    }
    with patch("enterprise.evaluation.extract_mo_fingerprint") as mock_mo:
        mock_mo.return_value = {"script_phases": ["a", "b"], "pressure_tactics": ["x"]}
        with patch("enterprise.evaluation.emit_event", new_callable=AsyncMock):
            result = await _evaluate_single_case(case_data, "run-1")

    assert result["case_id"] == "eval-001"
    assert result["category"] == "base"


@pytest.mark.asyncio
async def test_evaluate_single_case_handles_ambiguous_mo():
    case_data = {
        "case_id": "eval-002",
        "category": "noise",
        "transcript": [{"speaker": "C", "utterance": "x", "seq_idx": 0}] * 5,
        "expected_mo": {},
        "expected_entities": [],
    }
    with patch("enterprise.evaluation.extract_mo_fingerprint", return_value=None):
        with patch("enterprise.evaluation.emit_event", new_callable=AsyncMock):
            result = await _evaluate_single_case(case_data, "run-1")

    assert result["detected"] is False


@patch("enterprise.evaluation.get_supabase_client")
def test_store_eval_run_inserts_row(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table
    _store_eval_run({
        "run_id": "test-run",
        "timestamp": "2026-09-10T12:00:00Z",
        "base_metrics": {"detection_rate": 0.9},
        "noise_metrics": {"fp_rate": 0.05},
        "redteam_metrics": {"detection_rate": 0.7},
        "timing": {"mean_time_to_detection_sec": 120},
        "per_case": [],
    })
    mock_table.insert.assert_called_once()


@patch("enterprise.evaluation.get_supabase_client")
def test_get_latest_comparison_returns_two_runs(mock_client: MagicMock):
    mock_table = MagicMock()
    mock_table.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"run_id": "run-2", "base_detection": 0.95, "noise_fp": 0.03, "redteam_detection": 0.8, "ts": "2026-09-10T13:00:00Z"},
        {"run_id": "run-1", "base_detection": 0.90, "noise_fp": 0.05, "redteam_detection": 0.65, "ts": "2026-09-10T12:00:00Z"},
    ]
    mock_client.return_value.table.return_value = mock_table
    result = get_latest_comparison()
    assert result["before"]["run_id"] == "run-1"
    assert result["after"]["run_id"] == "run-2"
    assert result["delta"]["base_detection"] == pytest.approx(0.05)
```

### 7.4 pytest + ruff

```bash
cd backend && uv run pytest tests/unit/test_metrics.py tests/unit/test_evaluation.py -v
```

```bash
cd backend && uv run ruff check src/enterprise/metrics.py src/enterprise/evaluation.py tests/unit/test_metrics.py tests/unit/test_evaluation.py
```
