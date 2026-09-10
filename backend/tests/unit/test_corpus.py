"""Unit tests for the evaluation corpus and demo seed data (B7/B9).

The corpus is the measuring instrument for every number the console reports, so
these tests check the instrument itself: that the negative controls are as
carefully built as the scam cases, that the seed wave really does cluster when
put through the shipped linkage code rather than merely being labelled as if it
would, and that the recorded replay sequence matches the live event schema.

No database, no network, no API keys.
"""

import json
from typing import Any

from src.enterprise.clustering import check_promotion_gates, cluster_components
from src.enterprise.corpus import (
    CAMPAIGN_CODE,
    EVAL_DIR,
    EVIDENCE_SPEAKERS,
    SIGNATURE_PHRASES,
    STRUCTURAL_RULE_FEATURES,
    campaign_profile,
    derive_mo,
    load_eval_ground_truth,
    load_replay_sequence,
    load_seed_transcripts,
    matched_signature_phrases,
    normalised_entities,
    structural_features,
    transcript_text,
)
from src.enterprise.events import VALID_LAYERS, VALID_SEVERITIES
from src.enterprise.linkage import LINK_THRESHOLD, score_case_pair

#: Narrative order of the demo acts. Declared explicitly because the act labels
#: do not sort into story order lexicographically (``III`` precedes ``II``).
ACT_ORDER = ("I_sensing", "II_discovery", "III_validation", "IV_compile", "V_proof")


def _corpus(category: str) -> list[dict[str, Any]]:
    """Load every case file in one eval category directory."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((EVAL_DIR / category).glob("*.json"))
    ]


# ── Corpus shape ────────────────────────────────────────────────────────────
def test_corpus_has_forty_cases_in_the_documented_split() -> None:
    """20 base variants + 10 red-team mutations + 10 legitimate controls."""
    assert len(_corpus("base")) == 20
    assert len(_corpus("redteam")) == 10
    assert len(_corpus("noise")) == 10


def test_every_case_has_a_transcript_and_unique_id() -> None:
    """No placeholder rows, no duplicate ids across the whole corpus."""
    seen: set[str] = set()
    for category in ("base", "redteam", "noise"):
        for case in _corpus(category):
            assert case["case_id"] not in seen, f"duplicate {case['case_id']}"
            seen.add(case["case_id"])
            assert case["transcript"], f"{case['case_id']} has an empty transcript"
    assert len(seen) == 40


def test_ground_truth_labels_every_case_exactly_once() -> None:
    """Ground truth is complete and non-overlapping — coverage depends on it."""
    truth = load_eval_ground_truth()
    labelled: set[str] = set()
    for block, directory in (
        ("base_variants", "base"),
        ("redteam_mutations", "redteam"),
        ("noise", "noise"),
    ):
        detected = set(truth[block]["expected_detected"])
        fp = set(truth[block]["expected_fp"])
        assert not detected & fp, f"{block} labels a case both ways"

        on_disk = {case["case_id"] for case in _corpus(directory)}
        assert detected | fp == on_disk, block
        labelled |= on_disk

    assert len(labelled) == 40


def test_negative_controls_are_the_only_expected_non_detections() -> None:
    """Scam categories expect detection; the control category expects none."""
    truth = load_eval_ground_truth()
    assert truth["noise"]["expected_detected"] == []
    assert truth["base_variants"]["expected_fp"] == []
    assert truth["redteam_mutations"]["expected_fp"] == []


def test_negative_controls_are_real_conversations_not_stubs() -> None:
    """Controls get the same care as scam cases: multi-turn, two-sided calls."""
    for case in _corpus("noise"):
        transcript = case["transcript"]
        speakers = {u["speaker"] for u in transcript}
        assert len(transcript) >= 6, f"{case['case_id']} is too short to be a control"
        assert "CALLER" in speakers and "USER" in speakers


def test_negative_controls_carry_no_signature_phrase() -> None:
    """A legitimate call must not contain the campaign's signature phrasing."""
    for case in _corpus("noise"):
        assert matched_signature_phrases(case["transcript"]) == []


def test_negative_controls_never_show_the_full_structural_pattern() -> None:
    """No control combines authority, isolation and money movement."""
    for case in _corpus("noise"):
        features = structural_features(case["transcript"])
        assert not set(STRUCTURAL_RULE_FEATURES).issubset(features), case["case_id"]


def test_base_variants_all_show_the_structural_pattern() -> None:
    """Every base variant is a full escalation — that is what makes it a scam."""
    for case in _corpus("base"):
        features = structural_features(case["transcript"])
        assert set(STRUCTURAL_RULE_FEATURES).issubset(features), case["case_id"]


def test_redteam_mutations_each_declare_and_apply_a_change() -> None:
    """A mutation that changes nothing measures nothing.

    Each red-team case must both document its mutation and differ observably
    from every base variant, otherwise the adaptation delta is measured against
    cases the detector was always going to catch.
    """
    base_signatures = {
        (
            frozenset(structural_features(c["transcript"])),
            tuple(matched_signature_phrases(c["transcript"])),
            frozenset(e["value_norm"] for e in normalised_entities(c["transcript"])),
        )
        for c in _corpus("base")
    }
    for case in _corpus("redteam"):
        assert case.get("variant_note"), f"{case['case_id']} declares no mutation"
        signature = (
            frozenset(structural_features(case["transcript"])),
            tuple(matched_signature_phrases(case["transcript"])),
            frozenset(e["value_norm"] for e in normalised_entities(case["transcript"])),
        )
        assert signature not in base_signatures, case["case_id"]


# ── Detector input hygiene ──────────────────────────────────────────────────
def test_detection_never_reads_the_ai_agents_own_warnings() -> None:
    """The defence's output must not be fed back in as evidence.

    TranSafe's in-call warnings name the tactic they just spotted. Including
    them in feature extraction would let the detector read its own conclusion
    off the page and 'detect' a call that contained no such cue.
    """
    assert "AI_AGENT" not in EVIDENCE_SPEAKERS
    transcript = [
        {"speaker": "CALLER", "utterance": "Good morning, this is a courtesy call."},
        {
            "speaker": "AI_AGENT",
            "utterance": (
                "Warning: the caller claims to be from Bank Negara Malaysia, is "
                "telling you to keep this secret and to transfer money now."
            ),
        },
    ]
    assert structural_features(transcript) == set()
    assert "bank negara" not in transcript_text(transcript)


def test_transcript_text_can_include_everything_when_asked() -> None:
    """The speaker filter is opt-out, for display and archival use."""
    transcript = [{"speaker": "AI_AGENT", "utterance": "Warning issued."}]
    assert transcript_text(transcript) == ""
    assert "warning issued" in transcript_text(transcript, speakers=None)


# ── Profile and MO ──────────────────────────────────────────────────────────
def test_campaign_profile_exposes_watchlist_identifiers() -> None:
    """The pack-tier profile carries normalised identifiers, not raw strings."""
    profile = campaign_profile()
    assert profile["code"] == CAMPAIGN_CODE
    assert profile["watchlist"], "profile has no watchlist identifiers"
    for entry in profile["watchlist"]:
        assert entry["value_norm"] == entry["value_norm"].strip()
        assert entry["entity_type"] in {"PHONE", "ACCOUNT", "URL", "DOMAIN", "NAME"}


def test_derive_mo_is_deterministic_without_an_llm() -> None:
    """The same transcript always yields the same fingerprint."""
    transcript = _corpus("base")[0]["transcript"]
    assert derive_mo(transcript) == derive_mo(transcript)


def test_signature_phrases_are_lowercase_for_matching() -> None:
    """Phrase matching is done on casefolded text; the constants must agree."""
    for phrase in SIGNATURE_PHRASES:
        assert phrase == phrase.casefold()


# ── Seed corpus ─────────────────────────────────────────────────────────────
def test_seed_corpus_is_six_wave_cases_plus_four_non_linking() -> None:
    """The demo needs a wave that clusters and noise that stubbornly does not."""
    seeds = load_seed_transcripts()
    wave = [s for s in seeds if s["kind"] == "wave"]
    noise = [s for s in seeds if s["kind"] != "wave"]
    assert len(wave) == 6
    assert len(noise) == 4


def test_seed_cases_are_distinct_customers() -> None:
    """Promotion requires distinct customers; the seed must genuinely have them."""
    seeds = load_seed_transcripts()
    assert len({s["user_id"] for s in seeds}) == len(seeds)


def test_seed_data_is_clearly_fictional() -> None:
    """Every seeded customer is labelled fictional, in the data itself."""
    for seed in load_seed_transcripts():
        assert "FICTIONAL" in seed["customer_name"].upper()


def _link_seed_cases(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score every seed pair with the shipped linkage function."""
    links: list[dict[str, Any]] = []
    for i, a in enumerate(seeds):
        for b in seeds[i + 1 :]:
            score = score_case_pair(
                {"case_id": a["case_id"], "mo_fingerprint": a["mo_fingerprint"]},
                {"case_id": b["case_id"], "mo_fingerprint": b["mo_fingerprint"]},
                normalised_entities(a["transcript"]),
                normalised_entities(b["transcript"]),
            )
            links.append(
                {
                    "case_a": a["case_id"],
                    "case_b": b["case_id"],
                    "score": score["score"],
                    "signals": score.get("signals", {}),
                }
            )
    return links


def test_seed_wave_actually_clusters_through_the_shipped_linkage_code() -> None:
    """The six wave cases must link for real, not merely be labelled as a wave.

    This runs the production ``score_case_pair`` and ``cluster_components``, so
    a corpus that only looks like a campaign in the metadata fails here.
    """
    wave = [s for s in load_seed_transcripts() if s["kind"] == "wave"]
    links = _link_seed_cases(wave)

    assert all(link["score"] >= LINK_THRESHOLD for link in links), [
        (link["case_a"], link["case_b"], link["score"])
        for link in links
        if link["score"] < LINK_THRESHOLD
    ]
    components = cluster_components(links)
    assert len(components) == 1
    assert components[0] == {s["case_id"] for s in wave}


def test_seed_wave_passes_every_promotion_gate() -> None:
    """The seeded wave clears the real gates, with no gate given a free pass."""
    wave = [s for s in load_seed_transcripts() if s["kind"] == "wave"]
    links = _link_seed_cases(wave)
    cases = {
        s["case_id"]: {"user_id": s["user_id"], "created_at": s["created_at"]} for s in wave
    }
    result = check_promotion_gates({s["case_id"] for s in wave}, links, cases)

    assert result["passes"] is True, result["gates"]
    assert all(gate["pass"] for gate in result["gates"].values())
    assert result["customer_count"] == 6


def test_seed_noise_cases_do_not_join_the_wave() -> None:
    """Unrelated seeded calls must stay outside the campaign component."""
    seeds = load_seed_transcripts()
    wave_ids = {s["case_id"] for s in seeds if s["kind"] == "wave"}
    links = _link_seed_cases(seeds)

    components = cluster_components(links)
    wave_component = next((c for c in components if c & wave_ids), set())
    assert wave_component == wave_ids


# ── Replay sequence ─────────────────────────────────────────────────────────
def test_replay_sequence_matches_the_live_event_schema() -> None:
    """Replay frames are byte-compatible with rows the WebSocket streams."""
    events = load_replay_sequence()
    assert events
    for event in events:
        assert set(event) == {
            "id",
            "ts",
            "layer",
            "event_type",
            "severity",
            "payload",
            "run_id",
        }
        assert isinstance(event["id"], int)
        assert event["layer"] in VALID_LAYERS
        assert event["severity"] in VALID_SEVERITIES
        assert isinstance(event["payload"], dict)


def test_replay_sequence_covers_all_five_acts_in_order() -> None:
    """The recording tells the whole story, and tells it forwards."""
    events = load_replay_sequence()
    acts = [str(e["payload"].get("act")) for e in events]

    assert set(acts) == set(ACT_ORDER)
    positions = [ACT_ORDER.index(a) for a in acts]
    assert positions == sorted(positions), "acts are interleaved out of order"
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
