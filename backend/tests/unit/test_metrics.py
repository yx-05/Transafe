"""Unit tests for evaluation metric primitives (B7).

Implements the cases specified in doc/transafe_v2/07_evaluation.md.
Pure functions only: no database, no network, no API keys.
"""

from src.enterprise.metrics import (
    TARGET_ADAPTATION_DELTA,
    adaptation_delta,
    compute_adaptation_metrics,
    compute_detection_metrics,
    compute_timing_metrics,
    coverage,
    detection_rate,
    false_positive_rate,
    mean_time_to_detect,
    summarise,
)

GROUND_TRUTH = {
    "expected_detected": ["s1", "s2", "s3", "s4"],
    "expected_fp": ["n1", "n2"],
}


def _results(**detected: bool) -> list[dict[str, object]]:
    """Build a results list from ``case_id=detected`` keyword pairs."""
    return [{"case_id": cid, "detected": det} for cid, det in detected.items()]


# ── detection_rate / false_positive_rate ────────────────────────────────────
def test_detection_rate_basic() -> None:
    """TP / (TP + FN)."""
    assert detection_rate(3, 1) == 0.75


def test_detection_rate_no_positives_is_zero_not_one() -> None:
    """With nothing to detect the rate is 0.0, never a flattering 1.0."""
    assert detection_rate(0, 0) == 0.0


def test_false_positive_rate_basic() -> None:
    """FP / (FP + TN)."""
    assert false_positive_rate(1, 9) == 0.1


def test_false_positive_rate_no_negatives_is_zero() -> None:
    """No negative controls means no false-positive rate to report."""
    assert false_positive_rate(0, 0) == 0.0


# ── compute_detection_metrics ───────────────────────────────────────────────
def test_compute_detection_metrics_counts_all_four_cells() -> None:
    """TP, FN, FP and TN are counted from the ground-truth membership."""
    results = _results(s1=True, s2=True, s3=False, s4=True, n1=True, n2=False)
    m = compute_detection_metrics(results, GROUND_TRUTH)

    assert (m["tp"], m["fn"], m["fp"], m["tn"]) == (3, 1, 1, 1)
    assert m["detection_rate"] == 0.75
    assert m["fp_rate"] == 0.5
    assert m["missed"] == ["s3"]
    assert m["false_positives"] == ["n1"]


def test_compute_detection_metrics_ignores_unlabelled_cases() -> None:
    """An unlabelled case inflates neither the numerator nor the denominator."""
    results = _results(s1=True, s2=True, s3=True, s4=True, mystery=True)
    m = compute_detection_metrics(results, GROUND_TRUTH)

    assert m["detection_rate"] == 1.0
    assert m["labelled"] == 4
    assert m["total"] == 5


def test_compute_detection_metrics_empty_run_reports_zero() -> None:
    """An empty run reports zero detection, not a division error."""
    m = compute_detection_metrics([], GROUND_TRUTH)
    assert m["detection_rate"] == 0.0
    assert m["coverage"] == 0.0


# ── coverage ────────────────────────────────────────────────────────────────
def test_coverage_full_corpus() -> None:
    """Every labelled case produced a result."""
    results = _results(s1=True, s2=True, s3=True, s4=True, n1=False, n2=False)
    assert coverage(results, GROUND_TRUTH) == 1.0


def test_coverage_exposes_dropped_cases() -> None:
    """A perfect detection rate over half the corpus reports coverage 0.5."""
    results = _results(s1=True, s2=True, n1=False)
    assert coverage(results, GROUND_TRUTH) == 0.5


def test_coverage_excludes_errored_cases() -> None:
    """A case that raised is not covered, even though it has a row."""
    results = [
        {"case_id": "s1", "detected": False, "error": "boom"},
        {"case_id": "s2", "detected": True},
        {"case_id": "s3", "detected": True},
        {"case_id": "s4", "detected": True},
        {"case_id": "n1", "detected": False},
        {"case_id": "n2", "detected": False},
    ]
    assert coverage(results, GROUND_TRUTH) < 1.0


def test_coverage_without_ground_truth_is_zero() -> None:
    """Nothing labelled means nothing covered."""
    assert coverage(_results(s1=True), {}) == 0.0


# ── adaptation delta ────────────────────────────────────────────────────────
def test_adaptation_delta_positive() -> None:
    """A genuine improvement is reported as a positive delta."""
    assert adaptation_delta(0.2, 0.9) == 0.7


def test_adaptation_delta_negative_is_not_clamped() -> None:
    """A regression must survive to the operator's screen as a negative number."""
    assert adaptation_delta(0.9, 0.4) == -0.5


def test_compute_adaptation_metrics_lists_newly_detected_and_regressed() -> None:
    """The per-case movement in both directions is itemised."""
    pre = _results(s1=True, s2=False, s3=False, s4=True)
    post = _results(s1=True, s2=True, s3=True, s4=False)
    m = compute_adaptation_metrics(pre, post, GROUND_TRUTH)

    assert m["pre_detection"] == 0.5
    assert m["post_detection"] == 0.75
    assert m["delta"] == 0.25
    assert m["newly_detected"] == ["s2", "s3"]
    assert m["regressed"] == ["s4"]


def test_compute_adaptation_metrics_flags_target() -> None:
    """meets_target reflects the documented +0.15 threshold, nothing else."""
    pre = _results(s1=False, s2=False, s3=False, s4=False)
    post = _results(s1=True, s2=False, s3=False, s4=False)
    m = compute_adaptation_metrics(pre, post, GROUND_TRUTH)

    assert m["delta"] == 0.25
    assert m["meets_target"] is (0.25 >= TARGET_ADAPTATION_DELTA)


def test_compute_adaptation_metrics_reports_fp_regression() -> None:
    """A rule that buys detection with false positives shows fp_delta > 0."""
    pre = _results(s1=False, s2=False, s3=False, s4=False, n1=False, n2=False)
    post = _results(s1=True, s2=True, s3=True, s4=True, n1=True, n2=True)
    m = compute_adaptation_metrics(pre, post, GROUND_TRUTH)

    assert m["delta"] == 1.0
    assert m["fp_delta"] == 1.0


# ── timing ──────────────────────────────────────────────────────────────────
def test_mean_time_to_detect_empty_is_zero() -> None:
    """No measured durations yields 0.0 rather than an error."""
    assert mean_time_to_detect([]) == 0.0


def test_compute_timing_metrics_measures_both_intervals() -> None:
    """Detection is ingest→proposal; defence is proposal→acknowledgement."""
    events = [
        {
            "ts": "2026-09-10T12:00:00Z",
            "event_type": "case_ingested",
            "payload": {"case_id": "c1"},
        },
        {
            "ts": "2026-09-10T12:02:00Z",
            "event_type": "campaign_proposed",
            "payload": {"case_id": "c1"},
        },
        {
            "ts": "2026-09-10T12:02:30Z",
            "event_type": "propagation_acknowledged",
            "payload": {"case_id": "c1"},
        },
    ]
    m = compute_timing_metrics(events)

    assert m["mean_time_to_detection_sec"] == 120.0
    assert m["mean_time_to_defence_sec"] == 30.0
    assert m["measured_detections"] == 1


def test_compute_timing_metrics_ignores_unattributable_events() -> None:
    """An event with no case_id cannot be timed and is skipped, not guessed."""
    events = [
        {"ts": "2026-09-10T12:00:00Z", "event_type": "case_ingested", "payload": {}},
        {"ts": "2026-09-10T12:02:00Z", "event_type": "campaign_proposed", "payload": None},
    ]
    m = compute_timing_metrics(events)

    assert m["case_count"] == 0
    assert m["mean_time_to_detection_sec"] == 0.0


def test_compute_timing_metrics_tolerates_bad_timestamps() -> None:
    """A malformed timestamp is dropped without taking the run down."""
    events = [
        {"ts": "not-a-date", "event_type": "case_ingested", "payload": {"case_id": "c1"}},
        {
            "ts": "2026-09-10T12:02:00Z",
            "event_type": "campaign_proposed",
            "payload": {"case_id": "c1"},
        },
    ]
    assert compute_timing_metrics(events)["measured_detections"] == 0


# ── summarise ───────────────────────────────────────────────────────────────
def test_summarise_averages_coverage_across_categories() -> None:
    """The summary's coverage is the mean of the three category coverages."""
    base = {"detection_rate": 1.0, "tp": 20, "labelled": 20, "coverage": 1.0}
    noise = {"fp_rate": 0.0, "fp": 0, "labelled": 10, "coverage": 1.0}
    redteam = {"detection_rate": 0.9, "tp": 9, "labelled": 10, "coverage": 1.0}
    s = summarise(base, noise, redteam, {})

    assert s["detected"] == 29
    assert s["total"] == 30
    assert s["coverage"] == 1.0
    assert s["targets"]["base_detection_met"] is True
    assert s["targets"]["noise_fp_met"] is True


def test_summarise_missing_timing_defaults_to_zero() -> None:
    """A run with no ns_events still summarises, reporting zero timings."""
    s = summarise({}, {}, {}, {})
    assert s["mean_time_to_detection_sec"] == 0.0
    assert s["targets"]["base_detection_met"] is False
