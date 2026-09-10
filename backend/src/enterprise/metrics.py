"""Metrics — evaluation scoring primitives (B7, 07_evaluation.md §3).

Pure functions over evaluation output. Nothing here touches the database, the
network or an LLM, so every number the console shows can be re-derived from the
stored per-case results by anyone who doubts it.

Targets from 07_evaluation.md §3.1, for reference — they are *targets*, never
inputs. No function in this module clamps, floors or nudges a value towards
them:

    detection rate on base variants  >= 0.90
    false-positive rate on negatives <= 0.05
    red-team adaptation delta        >= +0.15
    time to detection                <  300 s
    time to defence                  <   60 s
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

TARGET_DETECTION_RATE = 0.90
TARGET_FP_RATE = 0.05
TARGET_ADAPTATION_DELTA = 0.15
TARGET_TIME_TO_DETECTION_SEC = 300.0
TARGET_TIME_TO_DEFENCE_SEC = 60.0


def compute_detection_metrics(
    results: list[dict[str, Any]],
    ground_truth: dict[str, list[str]],
) -> dict[str, Any]:
    """Compute detection rate and false-positive rate.

    Cases absent from both ground-truth lists are counted in ``total`` but
    contribute to no rate — an unlabelled case is not evidence of anything.

    Args:
        results: List of ``{case_id, detected: bool}`` for each eval case.
        ground_truth: Dict with ``expected_detected`` and ``expected_fp`` id lists.

    Returns:
        Dict with ``detection_rate``, ``fp_rate``, ``tp``, ``fp``, ``fn``, ``tn``,
        ``total``, ``coverage``, ``missed`` and ``false_positives``.
    """
    expected_detected = set(ground_truth.get("expected_detected") or [])
    expected_fp = set(ground_truth.get("expected_fp") or [])

    tp = fn = fp = tn = 0
    missed: list[str] = []
    false_positives: list[str] = []

    for result in results:
        case_id = result.get("case_id")
        detected = bool(result.get("detected", False))

        if case_id in expected_detected:
            if detected:
                tp += 1
            else:
                fn += 1
                missed.append(str(case_id))
        elif case_id in expected_fp:
            if detected:
                fp += 1
                false_positives.append(str(case_id))
            else:
                tn += 1

    return {
        "detection_rate": round(detection_rate(tp, fn), 4),
        "fp_rate": round(false_positive_rate(fp, tn), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "total": len(results),
        "labelled": tp + fn + fp + tn,
        "coverage": round(coverage(results, ground_truth), 4),
        "missed": missed,
        "false_positives": false_positives,
    }


def detection_rate(tp: int, fn: int) -> float:
    """Return TP / (TP + FN), or 0.0 when nothing was labelled positive.

    Args:
        tp: True positives.
        fn: False negatives.

    Returns:
        Detection rate in [0, 1].
    """
    denominator = tp + fn
    return tp / denominator if denominator > 0 else 0.0


def false_positive_rate(fp: int, tn: int) -> float:
    """Return FP / (FP + TN), or 0.0 when there were no negatives to get wrong.

    Args:
        fp: False positives.
        tn: True negatives.

    Returns:
        False-positive rate in [0, 1].
    """
    denominator = fp + tn
    return fp / denominator if denominator > 0 else 0.0


def coverage(
    results: list[dict[str, Any]],
    ground_truth: dict[str, list[str]],
) -> float:
    """Fraction of the labelled corpus that actually produced a result.

    Coverage guards the other metrics: a detection rate of 1.0 over three cases
    that happened to run is not the same claim as 1.0 over forty. If the harness
    silently drops cases, this is the number that shows it.

    Args:
        results: Per-case evaluation results.
        ground_truth: Dict with ``expected_detected`` and ``expected_fp`` id lists.

    Returns:
        Coverage in [0, 1]; 0.0 when ground truth labels nothing.
    """
    labelled = set(ground_truth.get("expected_detected") or []) | set(
        ground_truth.get("expected_fp") or []
    )
    if not labelled:
        return 0.0
    seen = {r.get("case_id") for r in results if not r.get("error")}
    return len(labelled & seen) / len(labelled)


def adaptation_delta(pre_detection: float, post_detection: float) -> float:
    """Return the post-minus-pre detection difference, signed.

    A negative delta is a real result and is returned as-is: the adaptation made
    detection worse and the operator needs to see that, not a zero.

    Args:
        pre_detection: Detection rate before the core-skill update.
        post_detection: Detection rate after the core-skill update.

    Returns:
        Signed delta, rounded to 4 decimal places.
    """
    return round(post_detection - pre_detection, 4)


def compute_adaptation_metrics(
    pre_results: list[dict[str, Any]],
    post_results: list[dict[str, Any]],
    ground_truth: dict[str, list[str]],
) -> dict[str, Any]:
    """Compute the pre/post adaptation detection delta.

    Args:
        pre_results: Detection results before the core-skill update.
        post_results: Detection results after the core-skill update.
        ground_truth: Ground truth with ``expected_detected`` for the mutations.

    Returns:
        Dict with ``pre_detection``, ``post_detection``, ``delta``, ``pre_fp``,
        ``post_fp``, ``newly_detected``, ``regressed`` and both detail blocks.
    """
    pre = compute_detection_metrics(pre_results, ground_truth)
    post = compute_detection_metrics(post_results, ground_truth)

    pre_by_id = {r.get("case_id"): bool(r.get("detected")) for r in pre_results}
    post_by_id = {r.get("case_id"): bool(r.get("detected")) for r in post_results}
    newly_detected = sorted(
        str(cid) for cid, det in post_by_id.items() if det and not pre_by_id.get(cid, False)
    )
    regressed = sorted(
        str(cid) for cid, det in post_by_id.items() if not det and pre_by_id.get(cid, False)
    )

    delta = adaptation_delta(pre["detection_rate"], post["detection_rate"])

    return {
        "pre_detection": pre["detection_rate"],
        "post_detection": post["detection_rate"],
        "delta": delta,
        "pre_fp": pre["fp_rate"],
        "post_fp": post["fp_rate"],
        "fp_delta": round(post["fp_rate"] - pre["fp_rate"], 4),
        "newly_detected": newly_detected,
        "regressed": regressed,
        "meets_target": delta >= TARGET_ADAPTATION_DELTA,
        "pre_details": pre,
        "post_details": post,
    }


def compute_timing_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute time-to-detection and time-to-defence from ``ns_events``.

    Time to detection is ingest → campaign proposal; time to defence is campaign
    proposal → propagation acknowledged. Events without a ``case_id`` payload
    cannot be attributed to a case and are ignored.

    Args:
        events: List of ns_event dicts for one eval run.

    Returns:
        Dict with mean/max detection and defence seconds plus ``case_count``.
    """
    case_events: dict[str, list[dict[str, Any]]] = {}
    for evt in events or []:
        payload = evt.get("payload") or {}
        case_id = payload.get("case_id") if isinstance(payload, dict) else None
        if case_id:
            case_events.setdefault(str(case_id), []).append(evt)

    detection_times: list[float] = []
    defence_times: list[float] = []

    for evts in case_events.values():
        ingest_ts = detection_ts = defence_ts = None
        for evt in evts:
            parsed = _parse_ts(evt.get("ts"))
            if parsed is None:
                continue
            event_type = evt.get("event_type")
            if event_type == "case_ingested":
                ingest_ts = parsed if ingest_ts is None else min(ingest_ts, parsed)
            elif event_type == "campaign_proposed":
                detection_ts = parsed if detection_ts is None else min(detection_ts, parsed)
            elif event_type == "propagation_acknowledged":
                defence_ts = parsed if defence_ts is None else min(defence_ts, parsed)

        if ingest_ts and detection_ts:
            detection_times.append((detection_ts - ingest_ts).total_seconds())
        if detection_ts and defence_ts:
            defence_times.append((defence_ts - detection_ts).total_seconds())

    return {
        "mean_time_to_detection_sec": round(mean_time_to_detect(detection_times), 1),
        "mean_time_to_defence_sec": round(mean_time_to_detect(defence_times), 1),
        "max_time_to_detection_sec": round(max(detection_times) if detection_times else 0.0, 1),
        "max_time_to_defence_sec": round(max(defence_times) if defence_times else 0.0, 1),
        "case_count": len(case_events),
        "measured_detections": len(detection_times),
        "measured_defences": len(defence_times),
    }


def mean_time_to_detect(durations: list[float]) -> float:
    """Arithmetic mean of a list of durations in seconds, 0.0 when empty.

    Args:
        durations: Durations in seconds.

    Returns:
        Mean duration in seconds.
    """
    return sum(durations) / len(durations) if durations else 0.0


def summarise(
    base: dict[str, Any],
    noise: dict[str, Any],
    redteam: dict[str, Any],
    timing: dict[str, Any],
) -> dict[str, Any]:
    """Build the flat summary stored on an ``eval_runs`` row.

    Args:
        base: Detection metrics for the base variants.
        noise: Detection metrics for the negative controls.
        redteam: Detection metrics for the red-team mutations.
        timing: Output of :func:`compute_timing_metrics`.

    Returns:
        Flat summary dict, including whether each target was met.
    """
    return {
        "base_detection": base.get("detection_rate", 0.0),
        "noise_fp": noise.get("fp_rate", 0.0),
        "redteam_detection": redteam.get("detection_rate", 0.0),
        "mean_time_to_detection_sec": timing.get("mean_time_to_detection_sec", 0.0),
        "mean_time_to_defence_sec": timing.get("mean_time_to_defence_sec", 0.0),
        "detected": base.get("tp", 0) + redteam.get("tp", 0),
        "total": base.get("labelled", 0) + redteam.get("labelled", 0),
        "false_positives": noise.get("fp", 0),
        "fp_total": noise.get("labelled", 0),
        "coverage": round(
            (base.get("coverage", 0.0) + noise.get("coverage", 0.0) + redteam.get("coverage", 0.0))
            / 3,
            4,
        ),
        "targets": {
            "base_detection_met": base.get("detection_rate", 0.0) >= TARGET_DETECTION_RATE,
            "noise_fp_met": noise.get("fp_rate", 1.0) <= TARGET_FP_RATE,
        },
    }


def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating ``Z`` and returning None on junk."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
