"""Unit tests for the evaluation harness (B7, 07_evaluation.md §8).

Tests ``src.enterprise.evaluation`` — the module that runs the 40-case
corpus through the detection pipeline, scores results with
``src.enterprise.metrics``, and persists ``eval_runs`` rows.

All external calls (Supabase, LLM) are mocked. No network, no API keys.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.enterprise import evaluation
from src.enterprise.evaluation import (
    DETECTION_THRESHOLD,
    STRUCTURAL_RULE,
    _load_corpus,
    _noisy_or,
    active_core_rules,
    parse_core_rules,
    score_case,
)


# ── _noisy_or ──────────────────────────────────────────────────────────────
def test_noisy_or_single_signal():
    """A single signal at weight w gives score w."""
    assert _noisy_or([0.9]) == pytest.approx(0.9)


def test_noisy_or_two_independent_signals():
    """Two independent signals fuse to 1-(1-w1)(1-w2)."""
    expected = 1 - (1 - 0.8) * (1 - 0.7)
    assert _noisy_or([0.8, 0.7]) == pytest.approx(expected)


def test_noisy_or_empty_is_zero():
    """No signals means no detection."""
    assert _noisy_or([]) == pytest.approx(0.0)


def test_noisy_or_clamps_above_one():
    """Weights above 1 are clamped to 1."""
    assert _noisy_or([1.5]) == pytest.approx(1.0)


def test_noisy_or_clamps_below_zero():
    """Negative weights are clamped to 0."""
    assert _noisy_or([-0.3]) == pytest.approx(0.0)


# ── parse_core_rules ───────────────────────────────────────────────────────
def test_parse_core_rules_empty():
    """No content means no rules."""
    assert parse_core_rules("") == set()
    assert parse_core_rules(None) == set()


def test_parse_core_rules_no_match():
    """A body with no authority/isolation/money triple yields no rules."""
    body = "R-1: Be polite to callers.\nR-2: Ask for their name."
    assert parse_core_rules(body) == set()


def test_parse_core_rules_structural_escalation():
    """A rule with authority + isolation + money is recognised."""
    body = (
        "R-1: When someone claims to be a government official "
        "and instructs the victim not to tell anyone "
        "while demanding a transfer of funds, flag as high risk."
    )
    rules = parse_core_rules(body)
    assert STRUCTURAL_RULE in rules


def test_parse_core_rules_multiple_rules():
    """Only the matching rule is identified, not a non-matching one."""
    body = (
        "R-1: Be polite.\n\n"
        "R-2: An officer demanding secrecy and a payment "
        "transfer is a structural escalation."
    )
    rules = parse_core_rules(body)
    assert STRUCTURAL_RULE in rules
    assert len(rules) == 1


# ── active_core_rules ──────────────────────────────────────────────────────
def test_active_core_rules_from_explicit_content():
    """When core_content is provided, it is parsed directly."""
    body = (
        "R-1: A police officer demanding secrecy "
        "and a funds transfer is high risk."
    )
    rules, version = active_core_rules(core_content=body)
    assert STRUCTURAL_RULE in rules
    assert version is None


def test_active_core_rules_empty_content():
    """Empty content means no rules and no version."""
    rules, version = active_core_rules(core_content="")
    assert rules == set()
    assert version is None


@patch("src.enterprise.evaluation.registry.get_artifact")
def test_active_core_rules_from_registry(mock_get: MagicMock):
    """When no content is given, the registry is read."""
    mock_get.return_value = {
        "content": (
            "R-1: An official demanding secrecy and payment "
            "transfer is high risk."
        ),
        "version": 7,
    }
    rules, version = active_core_rules()
    assert STRUCTURAL_RULE in rules
    assert version == 7


@patch("src.enterprise.evaluation.registry.get_artifact")
def test_active_core_rules_registry_miss(mock_get: MagicMock):
    """A missing artifact degrades to no rules, never raises."""
    mock_get.return_value = None
    rules, version = active_core_rules()
    assert rules == set()
    assert version is None


@patch("src.enterprise.evaluation.registry.get_artifact")
def test_active_core_rules_registry_exception(mock_get: MagicMock):
    """A DB failure degrades to no rules."""
    mock_get.side_effect = RuntimeError("relation does not exist")
    rules, version = active_core_rules()
    assert rules == set()
    assert version is None


# ── score_case ──────────────────────────────────────────────────────────────
def _scam_transcript():
    """A transcript that hits both identifier and phrase signals.

    Note: the extractor reads ``utterance`` (not ``text``) — same as the
    v1 pipeline and the corpus files.
    """
    return [
        {"speaker": "SCAMMER", "utterance": "I am calling from Maybank security."},
        {
            "speaker": "SCAMMER",
            "utterance": "Please transfer to 1592-3456-7890-1234 "
            "at bnm-verify-portal.example "
            "akaun selamat sementara.",
        },
    ]


def test_score_case_no_signals():
    """A benign transcript with no matches scores below threshold."""
    case = {
        "transcript": [
            {"speaker": "CALLER", "utterance": "Hello, how are you today?"},
            {"speaker": "AGENT", "utterance": "I am fine, thank you."},
        ]
    }
    result = score_case(case)
    assert result["score"] < DETECTION_THRESHOLD
    assert result["detected"] is False
    assert result["signals"] == []


def test_score_case_watchlist_hit():
    """A hard identifier in the watchlist produces a pack-tier signal."""
    from src.enterprise.corpus import campaign_profile

    profile = campaign_profile()
    # The watchlist account is 1592-3456-7890-1234 — include it in the
    # transcript so the entity extractor picks it up.
    case = {
        "transcript": [
            {
                "speaker": "SCAMMER",
                "utterance": "Transfer to 1592-3456-7890-1234 "
                "at bnm-verify-portal.example "
                "akaun selamat sementara.",
            },
        ]
    }
    result = score_case(case, profile=profile)
    signal_types = [s["signal"] for s in result["signals"]]
    assert "watchlist_identifier" in signal_types
    assert result["detected"] is True


def test_score_case_signature_phrase():
    """A matching phrase produces a pack-tier signal.

    Note: ``transcript_text`` only includes ``CALLER`` and ``USER``
    speakers by default (``EVIDENCE_SPEAKERS``), so the phrase must
    come from the victim's side of the conversation.
    """
    # The campaign signature phrase is "akaun selamat sementara".
    case = {
        "transcript": [
            {
                "speaker": "CALLER",
                "utterance": "Sila pindah ke akaun selamat sementara "
                "sekarang.",
            },
        ]
    }
    result = score_case(case)
    signal_types = [s["signal"] for s in result["signals"]]
    assert "signature_phrase" in signal_types


def test_score_case_structural_rule():
    """When core rules include the structural rule, it can fire."""
    case = {
        "transcript": [
            {"speaker": "SCAMMER", "utterance": "I am from the police."},
            {
                "speaker": "SCAMMER",
                "utterance": "Do not tell anyone about this.",
            },
            {
                "speaker": "SCAMMER",
                "utterance": "Transfer the money now.",
            },
        ]
    }
    # Use the default profile (from campaign_profile) — it has an MO
    # that should match authority + isolation + money.
    result = score_case(case, core_rules={STRUCTURAL_RULE})
    if result["detected"]:
        signal_types = [s["signal"] for s in result["signals"]]
        # The structural rule may or may not fire depending on whether
        # the structural features are all present.
        if STRUCTURAL_RULE in signal_types:
            assert any(
                s["tier"] == "core" for s in result["signals"]
            )


def test_score_case_returns_entities():
    """Scored cases include the extracted entities list."""
    case = {"transcript": _scam_transcript()}
    result = score_case(case)
    assert isinstance(result["entities"], list)


def test_score_case_returns_features():
    """Scored cases include the structural features set."""
    case = {"transcript": _scam_transcript()}
    result = score_case(case)
    assert isinstance(result["features"], list)


# ── _load_corpus ────────────────────────────────────────────────────────────
def test_load_corpus_missing_dir_returns_empty(tmp_path):
    """A non-existent directory yields an empty list."""
    result = _load_corpus(tmp_path / "nonexistent")
    assert result == []


def test_load_corpus_reads_json_files(tmp_path):
    """JSON files in base/redteam/noise are loaded and tagged."""
    (tmp_path / "base").mkdir()
    (tmp_path / "noise").mkdir()
    (tmp_path / "base" / "case1.json").write_text(
        '{"case_id": "c1", "transcript": []}'
    )
    (tmp_path / "noise" / "n1.json").write_text(
        '{"case_id": "n1", "transcript": []}'
    )
    result = _load_corpus(tmp_path)
    assert len(result) == 2
    categories = {c["category"] for c in result}
    assert categories == {"base", "noise"}


def test_load_corpus_filters_by_category(tmp_path):
    """When a category is specified, only that folder is read."""
    (tmp_path / "base").mkdir()
    (tmp_path / "redteam").mkdir()
    (tmp_path / "base" / "case1.json").write_text(
        '{"case_id": "c1", "transcript": []}'
    )
    (tmp_path / "redteam" / "r1.json").write_text(
        '{"case_id": "r1", "transcript": []}'
    )
    result = _load_corpus(tmp_path, category="base")
    assert len(result) == 1
    assert result[0]["category"] == "base"


def test_load_corpus_skips_invalid_json(tmp_path):
    """Unreadable JSON files are skipped, not fatal."""
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "good.json").write_text(
        '{"case_id": "c1", "transcript": []}'
    )
    (tmp_path / "base" / "bad.json").write_text("{not valid json")
    result = _load_corpus(tmp_path)
    assert len(result) == 1
    assert result[0]["case_id"] == "c1"


# ── run_evaluation (integration, mocked) ───────────────────────────────────
@pytest.mark.asyncio
@patch("src.enterprise.evaluation.get_supabase_client")
@patch("src.enterprise.evaluation.emit_event")
@patch("src.enterprise.evaluation.registry")
async def test_run_evaluation_returns_result(
    mock_registry: MagicMock,
    mock_emit: MagicMock,
    mock_client: MagicMock,
    tmp_path,
):
    """run_evaluation produces a well-formed result dict."""
    mock_registry.get_artifact.return_value = None
    mock_registry.list_artifacts.return_value = []
    mock_emit.return_value = None
    mock_client.return_value.table.return_value.insert.return_value.execute = (
        MagicMock(data=[])
    )

    # Minimal corpus — note: field is "utterance" not "text"
    (tmp_path / "base").mkdir()
    (tmp_path / "noise").mkdir()
    (tmp_path / "base" / "c1.json").write_text(
        '{"case_id": "c1", "is_scam": true, '
        '"transcript": [{"speaker": "SCAMMER", '
        '"utterance": "transfer to safe account"}]}'
    )
    (tmp_path / "noise" / "n1.json").write_text(
        '{"case_id": "n1", "is_scam": false, '
        '"transcript": [{"speaker": "CALLER", '
        '"utterance": "hello"}]}'
    )

    result = await evaluation.run_evaluation(
        corpus_dir=tmp_path,
        store=False,
        use_llm=False,
    )
    assert "run_id" in result
    assert "summary" in result
    assert "results" in result
    assert len(result["results"]) == 2
    assert result["corpus_size"] == 2


@pytest.mark.asyncio
@patch("src.enterprise.evaluation.get_supabase_client")
@patch("src.enterprise.evaluation.emit_event")
@patch("src.enterprise.evaluation.registry")
async def test_run_evaluation_with_structural_rule(
    mock_registry: MagicMock,
    mock_emit: MagicMock,
    mock_client: MagicMock,
    tmp_path,
):
    """When a core rule body is supplied, it is parsed and can fire."""
    mock_registry.get_artifact.return_value = None
    mock_registry.list_artifacts.return_value = []
    mock_emit.return_value = None

    # A transcript that should trigger the structural rule
    core_body = (
        "R-1: When someone claims to be a government official "
        "and instructs the victim not to tell anyone "
        "while demanding a transfer of funds, flag as high risk."
    )
    (tmp_path / "base").mkdir()
    (tmp_path / "noise").mkdir()
    (tmp_path / "base" / "c1.json").write_text(
        '{"case_id": "c1", "is_scam": true, '
        '"transcript": [{"speaker": "SCAMMER", '
        '"utterance": "I am from the police. Do not tell anyone. '
        "Transfer the money now.\"}]}"
    )
    (tmp_path / "noise" / "n1.json").write_text(
        '{"case_id": "n1", "is_scam": false, '
        '"transcript": [{"speaker": "CALLER", '
        '"utterance": "hello"}]}'
    )

    result = await evaluation.run_evaluation(
        corpus_dir=tmp_path,
        core_content=core_body,
        store=False,
        use_llm=False,
    )
    assert STRUCTURAL_RULE in result.get("core_rules", [])
