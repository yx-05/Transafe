"""Unit tests for worker-side artifact consumption.

The propagation layer already emitted acknowledgements and wrote receipts for
campaign packs before any worker could read one (see test_propagation.py:41 —
"emits two events per agent and records a receipt"). These tests pin the other
half: that a published pack actually changes what the phone worker detects,
and that a receipt is written only for an artifact whose phrases were folded in.

The load-bearing case is `test_novel_phrase_only_in_artifact_is_detected` — it
uses a phrase deliberately absent from HIGH_RISK_PHRASES, so it can only pass
if the artifact was genuinely read.
"""

from typing import Any
from unittest.mock import patch

import pytest

from src.agents.workers.artifact_feed import (
    extract_pack_phrases,
    load_learned_phrases,
    reset_learned_phrase_cache,
)
from src.agents.workers.phone import HIGH_RISK_PHRASES, _scan_high_risk_phrases

#: A phrase no shipped rule contains. If detection fires on this, the only
#: possible source is a published artifact.
NOVEL_PHRASE = "kod pengesahan segera"


def _pack(
    artifact_id: str = "art-1",
    code: str = "SCAM-042",
    phrases: list[Any] | None = None,
    content_json: Any = None,
) -> dict[str, Any]:
    """Build a published campaign_pack artifact row."""
    if content_json is None:
        content_json = {
            "campaign": code,
            "high_risk_phrases": (
                phrases if phrases is not None else [{"text": NOVEL_PHRASE, "lang": "ms"}]
            ),
        }
    return {
        "id": artifact_id,
        "name": code,
        "artifact_type": "campaign_pack",
        "tier": "pack",
        "version": 1,
        "content_json": content_json,
    }


@pytest.fixture(autouse=True)
def _clear_cache() -> Any:
    """The phrase cache is process-global; leaking it across tests hides bugs."""
    reset_learned_phrase_cache()
    yield
    reset_learned_phrase_cache()


# ── extraction ───────────────────────────────────────────────────────────────
def test_extract_phrases_from_compiler_schema() -> None:
    """The compiler's {"text", "lang", "case_count"} shape is read."""
    assert extract_pack_phrases(_pack()) == [NOVEL_PHRASE]


def test_extract_phrases_from_json_text_column() -> None:
    """content_json still encoded as text is decoded, not skipped."""
    import json

    art = _pack(content_json=json.dumps({"campaign": "SCAM-1", "high_risk_phrases": ["akaun x"]}))
    assert extract_pack_phrases(art) == ["akaun x"]


def test_extract_phrases_tolerates_malformed_content() -> None:
    """A malformed artifact yields nothing rather than taking the loader down."""
    assert extract_pack_phrases(_pack(content_json="{not json")) == []
    assert extract_pack_phrases({"id": "x"}) == []


def test_extract_phrases_drops_substring_noise() -> None:
    """A 1-2 char phrase would substring-match nearly every transcript."""
    assert extract_pack_phrases(_pack(phrases=["a", "ok", "valid phrase"])) == ["valid phrase"]


# ── loading + receipts ───────────────────────────────────────────────────────
def test_load_maps_phrase_to_campaign_and_records_receipt() -> None:
    """A pack that is read produces a receipt naming the subscriber agent."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_pack()]),
        patch("src.enterprise.registry.record_consumption") as mock_record,
    ):
        learned = load_learned_phrases()

    assert learned == {NOVEL_PHRASE: "SCAM-042"}
    mock_record.assert_called_once()
    assert mock_record.call_args.args[0] == "art-1"
    assert mock_record.call_args.args[1] == "phone_worker"


def test_no_receipt_for_a_pack_that_taught_nothing() -> None:
    """A receipt asserts phrases were folded in; an empty pack folded none."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_pack(phrases=[])]),
        patch("src.enterprise.registry.record_consumption") as mock_record,
    ):
        assert load_learned_phrases() == {}
    mock_record.assert_not_called()


def test_non_campaign_pack_artifacts_are_ignored() -> None:
    """txn_rule / cs_advisory are not the phone worker's to consume."""
    other = _pack(artifact_id="art-9")
    other["artifact_type"] = "txn_rule"
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[other]),
        patch("src.enterprise.registry.record_consumption") as mock_record,
    ):
        assert load_learned_phrases() == {}
    mock_record.assert_not_called()


def test_registry_failure_degrades_to_builtin_rules() -> None:
    """An unreachable registry must never fail a live call."""
    with patch("src.enterprise.registry.list_artifacts", side_effect=RuntimeError("db down")):
        assert load_learned_phrases() == {}


def test_cache_avoids_requerying_per_utterance() -> None:
    """The scanner runs per call; the registry must not be hit each time."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_pack()]) as mock_list,
        patch("src.enterprise.registry.record_consumption"),
    ):
        load_learned_phrases()
        load_learned_phrases()
        load_learned_phrases()
    assert mock_list.call_count == 1


def test_force_bypasses_the_cache() -> None:
    """A caller that needs the newest packs can demand a re-read."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_pack()]) as mock_list,
        patch("src.enterprise.registry.record_consumption"),
    ):
        load_learned_phrases()
        load_learned_phrases(force=True)
    assert mock_list.call_count == 2


# ── the loop actually closing ────────────────────────────────────────────────
def test_novel_phrase_is_absent_from_shipped_rules() -> None:
    """Guards the test below: if this ever fails, that test proves nothing."""
    assert not any(NOVEL_PHRASE in p or p in NOVEL_PHRASE for p in HIGH_RISK_PHRASES)


def test_novel_phrase_only_in_artifact_is_detected() -> None:
    """An approved campaign changes detection, not just the receipt table.

    Before worker-side consumption existed this could not pass: the phrase
    appears in no shipped rule, so a hit is only possible by reading the pack.
    """
    transcript = [{"utterance_id": "u1", "speaker": "CALLER", "text": f"Sila berikan {NOVEL_PHRASE}"}]
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_pack()]),
        patch("src.enterprise.registry.record_consumption"),
    ):
        highlights, score, evidence = _scan_high_risk_phrases(transcript)

    assert score > 0, "learned phrase did not contribute to the risk score"
    assert any(NOVEL_PHRASE in h["phrase"] for h in highlights)
    assert any("learned from campaign SCAM-042" in e for e in evidence)


def test_builtin_rules_still_fire_without_any_artifact() -> None:
    """Learning is additive: an empty registry keeps the shipped behaviour."""
    transcript = [{"utterance_id": "u1", "speaker": "CALLER", "text": "Please transfer money now"}]
    with patch("src.enterprise.registry.list_artifacts", return_value=[]):
        _, score, evidence = _scan_high_risk_phrases(transcript)

    assert score > 0
    assert all("learned from campaign" not in e for e in evidence)
