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
    blocked_recipient_accounts,
    extract_pack_phrases,
    load_core_guide,
    load_learned_phrases,
    load_phishing_patch,
    load_txn_rules,
    reset_artifact_cache,
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
    """Every artifact cache is process-global; leaking one across tests hides bugs."""
    reset_artifact_cache()
    yield
    reset_artifact_cache()


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
    transcript = [
        {"utterance_id": "u1", "speaker": "CALLER", "text": f"Sila berikan {NOVEL_PHRASE}"}
    ]
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


# ══════════════════════════════════════════════════════════════════════════════
# Core tier — phone_agent_core
# ══════════════════════════════════════════════════════════════════════════════
CORE_BODY = (
    "# phone_agent_core\n\n## Escalation rules\n"
    "R-4: When an authority claim, an isolation instruction and a money-movement "
    "instruction co-occur in one call, escalate to enhanced verification "
    "regardless of the institution named.\n"
)


def _core(artifact_id: str = "art-core", version: int = 7) -> dict[str, Any]:
    """Build a published phone_agent_core artifact row."""
    return {
        "id": artifact_id,
        "name": "phone_agent_core",
        "artifact_type": "phone_agent_core",
        "tier": "core",
        "version": version,
        "content": CORE_BODY,
        "content_json": None,
    }


def test_load_core_guide_returns_published_body() -> None:
    """The published core skill is returned, and the reader earns a receipt."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_core()]),
        patch("src.enterprise.registry.record_consumption") as mock_receipt,
        patch("src.enterprise.events.emit_event_sync") as mock_ack,
    ):
        body = load_core_guide()

    assert body == CORE_BODY
    mock_receipt.assert_called_once_with("art-core", "phone_worker", client=None)
    # The acknowledgement is emitted by the consumer, not the propagator.
    assert mock_ack.call_args.kwargs["event_type"] == "propagation_acknowledged"
    assert mock_ack.call_args.kwargs["payload"]["acknowledged_by"] == "consumer"


def test_load_core_guide_empty_when_nothing_published() -> None:
    """No published core skill → empty string, so the caller falls back to the file."""
    with patch("src.enterprise.registry.list_artifacts", return_value=[]):
        assert load_core_guide() == ""


def test_load_core_guide_ignores_pack_tier_rows() -> None:
    """A campaign pack is not a core skill, even if its type were mislabelled."""
    pack = _pack(artifact_id="art-pack")
    pack["artifact_type"] = "phone_agent_core"  # right type, wrong tier
    with patch("src.enterprise.registry.list_artifacts", return_value=[pack]):
        assert load_core_guide() == ""


def test_load_core_guide_survives_registry_failure() -> None:
    """An unreachable registry degrades to the pre-artifact behaviour, never raises."""
    with patch("src.enterprise.registry.list_artifacts", side_effect=RuntimeError("down")):
        assert load_core_guide() == ""


def test_phone_worker_prefers_core_skill_over_skill_file() -> None:
    """The core skill is the prompt the phone agent actually runs."""
    from src.agents.workers.phone import _run_autotalk_responder

    captured: dict[str, Any] = {}

    def _capture(transcript: Any, anchors: Any, guide: Any, suspicion: Any, aq: Any) -> str:
        captured["guide"] = guide
        return "prompt"

    class _LLM:
        def invoke(self, _messages: Any) -> Any:
            return type("R", (), {"content": '{"reply": "ok"}'})()

    with (
        patch("src.agents.workers.phone.load_core_guide", return_value=CORE_BODY),
        patch("src.agents.workers.phone.get_phone_dialogue_guide", return_value="FILE BODY"),
        patch("src.agents.workers.phone.get_anchor_questions", return_value=[]),
        patch("src.agents.workers.phone.build_autotalk_response_prompt", side_effect=_capture),
    ):
        _run_autotalk_responder([], "+60123", {}, 0, {})

    assert captured["guide"] == CORE_BODY


def test_phone_worker_falls_back_to_skill_file_when_no_core() -> None:
    """An empty core body means the checked-in guide still drives the agent."""
    from src.agents.workers.phone import _run_autotalk_responder

    captured: dict[str, Any] = {}

    def _capture(transcript: Any, anchors: Any, guide: Any, suspicion: Any, aq: Any) -> str:
        captured["guide"] = guide
        return "prompt"

    with (
        patch("src.agents.workers.phone.load_core_guide", return_value=""),
        patch("src.agents.workers.phone.get_phone_dialogue_guide", return_value="FILE BODY"),
        patch("src.agents.workers.phone.get_anchor_questions", return_value=[]),
        patch("src.agents.workers.phone.build_autotalk_response_prompt", side_effect=_capture),
    ):
        _run_autotalk_responder([], "+60123", {}, 0, {})

    assert captured["guide"] == "FILE BODY"


# ══════════════════════════════════════════════════════════════════════════════
# Pack tier — phishing_playbook_patch
# ══════════════════════════════════════════════════════════════════════════════
PHISHING_NOVEL = "suruhanjaya sekuriti malaysia"


def _patch_artifact(artifact_id: str = "art-patch", code: str = "SCAM-042") -> dict[str, Any]:
    """Build a published phishing_playbook_patch artifact row."""
    return {
        "id": artifact_id,
        "name": f"{code}_phishing_playbook_patch",
        "artifact_type": "phishing_playbook_patch",
        "tier": "pack",
        "version": 1,
        "content_json": {
            "campaign": code,
            "heavy_keywords": [PHISHING_NOVEL],
            "light_keywords": ["semak akaun"],
            "url_patterns": ["sc-verify.online*"],
        },
    }


def test_load_phishing_patch_merges_and_receipts() -> None:
    """Published patches are unioned, and each read earns a receipt."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_patch_artifact()]),
        patch("src.enterprise.registry.record_consumption") as mock_receipt,
        patch("src.enterprise.events.emit_event_sync"),
    ):
        patch_data = load_phishing_patch()

    assert PHISHING_NOVEL in patch_data["heavy"]
    assert "semak akaun" in patch_data["light"]
    assert "sc-verify.online*" in patch_data["url_patterns"]
    mock_receipt.assert_called_once_with("art-patch", "phishing_worker", client=None)


def test_load_phishing_patch_empty_when_nothing_published() -> None:
    """No published patch → empty lists, never an exception."""
    with patch("src.enterprise.registry.list_artifacts", return_value=[]):
        patch_data = load_phishing_patch()
    assert patch_data == {"heavy": [], "light": [], "url_patterns": []}


def test_phishing_playbook_merges_published_patch() -> None:
    """An approved patch reaches the keyword lists the rule engine scans with."""
    import src.agents.workers.phishing as phishing

    phishing._PHISHING_PLAYBOOK_CACHE = None
    phishing._PHISHING_PLAYBOOK_CACHE_TS = 0.0
    try:
        with patch(
            "src.enterprise.registry.list_artifacts",
            return_value=[_patch_artifact()],
        ):
            data = phishing._merge_published_patch({"heavy": ["existing"], "light": []})
            assert PHISHING_NOVEL in data["heavy"]
            assert "existing" in data["heavy"]
    finally:
        phishing._PHISHING_PLAYBOOK_CACHE = None
        phishing._PHISHING_PLAYBOOK_CACHE_TS = 0.0


def test_merge_published_patch_survives_registry_failure() -> None:
    """A registry outage leaves the playbook byte-for-byte as it was."""
    import src.agents.workers.phishing as phishing

    with patch(
        "src.agents.workers.artifact_feed.load_phishing_patch",
        side_effect=RuntimeError("down"),
    ):
        data = phishing._merge_published_patch({"heavy": ["existing"], "light": ["l"]})

    assert data["heavy"] == ["existing"]
    assert data["light"] == ["l"]


# ══════════════════════════════════════════════════════════════════════════════
# Pack tier — txn_rule
# ══════════════════════════════════════════════════════════════════════════════
MULE_ACCOUNT = "159255887741"


def _txn_artifact(artifact_id: str = "art-txn", code: str = "SCAM-042") -> dict[str, Any]:
    """Build a published txn_rule artifact row."""
    return {
        "id": artifact_id,
        "name": f"{code}_txn_rule",
        "artifact_type": "txn_rule",
        "tier": "pack",
        "version": 1,
        "content_json": {
            "campaign": code,
            "rules": [
                {
                    "action": "BLOCK",
                    "condition": {
                        "field": "recipient_account",
                        "op": "in",
                        "values": [MULE_ACCOUNT],
                    },
                    "reason": f"Known mule account in {code}",
                },
                {
                    "action": "STEP_UP",
                    "condition": {"field": "amount", "op": "gt", "values": [10000]},
                    "reason": "High-value transfer",
                },
            ],
        },
    }


def test_load_txn_rules_flattens_with_campaign() -> None:
    """Rules are flattened and stamped with the campaign that taught them."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_txn_artifact()]),
        patch("src.enterprise.registry.record_consumption") as mock_receipt,
        patch("src.enterprise.events.emit_event_sync"),
    ):
        rules = load_txn_rules()

    assert len(rules) == 2
    assert rules[0]["campaign"] == "SCAM-042"
    assert rules[0]["action"] == "BLOCK"
    mock_receipt.assert_called_once_with("art-txn", "financial_worker", client=None)


def test_blocked_recipient_accounts_returns_digits_only() -> None:
    """BLOCK rules on recipient_account become a digit-only deny set."""
    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_txn_artifact()]),
        patch("src.enterprise.registry.record_consumption"),
        patch("src.enterprise.events.emit_event_sync"),
    ):
        blocked = blocked_recipient_accounts()

    assert blocked == {MULE_ACCOUNT}
    # STEP_UP on `amount` must not leak into the recipient deny set.
    assert "10000" not in blocked


def test_blocked_recipient_accounts_empty_when_nothing_published() -> None:
    """No published rule → nothing blocked, no exception."""
    with patch("src.enterprise.registry.list_artifacts", return_value=[]):
        assert blocked_recipient_accounts() == set()


def test_financial_worker_hard_blocks_published_mule_account() -> None:
    """A published BLOCK rule reaches the financial finding deterministically.

    The transfer is unremarkable by every behavioural heuristic — modest amount,
    known recipient, no case context — so a score of 100 is only possible if the
    published rule was read.
    """
    from src.agents.workers.financial import _rule_based_financial_analysis

    pending_tx = {
        "amount": 300.0,
        "sender_account": "6373-5093-3430-8430",
        # Same account, dash-formatted the way a transaction would carry it:
        # the match is on digits, so formatting must not defeat the rule.
        "recipient_account": "1592-5588-7741",
        "currency": "MYR",
    }
    history = {"avg_amount": 300.0, "known_recipients": [pending_tx["recipient_account"]]}

    with (
        patch("src.enterprise.registry.list_artifacts", return_value=[_txn_artifact()]),
        patch("src.enterprise.registry.record_consumption"),
        patch("src.enterprise.events.emit_event_sync"),
    ):
        finding = _rule_based_financial_analysis(pending_tx, history, None)

    assert finding.score == 100
    assert any("published campaign rule" in e for e in finding.evidence)


def test_financial_worker_unaffected_without_published_rules() -> None:
    """Fail-soft: no artifacts means the pre-artifact score is unchanged."""
    from src.agents.workers.financial import _rule_based_financial_analysis

    pending_tx = {
        "amount": 300.0,
        "sender_account": "6373-5093-3430-8430",
        "recipient_account": "9999-8888-7777",
        "currency": "MYR",
    }
    history = {"avg_amount": 300.0, "known_recipients": ["9999-8888-7777"]}

    with patch("src.enterprise.registry.list_artifacts", return_value=[]):
        finding = _rule_based_financial_analysis(pending_tx, history, None)

    assert finding.score == 10
    assert not any("published campaign rule" in e for e in finding.evidence)
