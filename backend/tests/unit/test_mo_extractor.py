"""Unit tests for src.enterprise.mo_extractor."""

from unittest.mock import MagicMock, patch

from src.enterprise.mo_extractor import (
    extract_identifiers,
    extract_mo_fingerprint,
    store_mo_fingerprint,
)

SAMPLE_TRANSCRIPT = [
    {"speaker": "CALLER", "utterance": "Saya pegawai BNM", "risk_score": 60, "seq_idx": 0},
    {"speaker": "USER", "utterance": "Ya?", "risk_score": 0, "seq_idx": 1},
    {
        "speaker": "CALLER",
        "utterance": "Transfer ke akaun 1234567890",
        "risk_score": 90,
        "seq_idx": 2,
    },
]


@patch("src.enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_valid_transcript(mock_llm):
    mock_llm.return_value = MagicMock(
        content='{"impersonated_entity": "BNM", "pretext": "account frozen", '
        '"script_phases": ["authority_claim", "money_ask"], "pressure_tactics": ["urgency"], '
        '"novel_phrases": [], "languages": ["ms"], "time_to_money_ask_sec": 45, '
        '"verification_evasion": null, "evidence_utterances": [0, 2], '
        '"narrative": "Caller impersonates BNM and demands transfer."}'
    )
    result = extract_mo_fingerprint("case-1", SAMPLE_TRANSCRIPT)
    assert result is not None
    assert result["impersonated_entity"] == "BNM"
    assert result["case_id"] == "case-1"
    assert "narrative" in result
    assert result["evidence_utterances"] == [0, 2]


@patch("src.enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_ambiguous_returns_none(mock_llm):
    mock_llm.return_value = MagicMock(content='{"ambiguous": true}')
    assert extract_mo_fingerprint("case-1", SAMPLE_TRANSCRIPT) is None


def test_extract_mo_short_transcript_returns_none():
    assert extract_mo_fingerprint("case-1", [{"speaker": "USER", "utterance": "Hi"}]) is None
    assert extract_mo_fingerprint("case-1", []) is None


@patch("src.enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_llm_failure_triggers_fallback(mock_llm):
    mock_llm.side_effect = Exception("API down")
    result = extract_mo_fingerprint("case-1", SAMPLE_TRANSCRIPT)
    assert result is not None
    assert result["extractor"] == "fallback-v1"
    assert result["case_id"] == "case-1"
    assert "ms" in result["languages"]
    assert result["time_to_money_ask_sec"] is not None


@patch("src.enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_unparseable_json_triggers_fallback(mock_llm):
    mock_llm.return_value = MagicMock(content="not json at all")
    result = extract_mo_fingerprint("case-1", SAMPLE_TRANSCRIPT)
    assert result is not None
    assert result["extractor"] == "fallback-v1"


@patch("src.enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_extract_mo_clamps_out_of_range_evidence(mock_llm):
    mock_llm.return_value = MagicMock(
        content='{"impersonated_entity": "BNM", "evidence_utterances": [0, 99], '
        '"novel_phrases": [{"text": "x", "lang": "ms", "utterance_idx": 77}], '
        '"narrative": "n"}'
    )
    result = extract_mo_fingerprint("case-1", SAMPLE_TRANSCRIPT)
    assert result["evidence_utterances"] == [0]
    assert result["novel_phrases"] == []


@patch("src.enterprise.mo_extractor.invoke_deepseek_with_key_rotation")
def test_llm_output_never_supplies_identifiers(mock_llm):
    """§4.2 hard rule: identifiers come from regex only, never from the LLM."""
    mock_llm.return_value = MagicMock(
        content='{"impersonated_entity": "BNM", "narrative": "n", '
        '"identifiers": {"phones": [{"value": "+60199999999", "utterance_idx": 0}]}}'
    )
    result = extract_mo_fingerprint("case-1", SAMPLE_TRANSCRIPT)
    assert result["identifiers"]["phones"] == []
    assert result["identifiers"]["accounts"] == [
        {"value": "1234567890", "utterance_idx": 2}
    ]


def test_extract_identifiers_regex_only():
    transcript = [
        {"utterance": "Call me at 012-3456789 or visit bnm-verify.online"},
        {"utterance": "Transfer RM5,000 to account 1234-5678-9012"},
    ]
    ids = extract_identifiers(transcript)
    assert any("012" in p["value"] for p in ids["phones"])
    assert any("bnm-verify.online" in u["value"] for u in ids["urls"])
    assert any("1234" in a["value"] for a in ids["accounts"])
    assert any("5,000" in a["value"] for a in ids["amounts"])


def test_extract_identifiers_empty_transcript():
    ids = extract_identifiers([])
    assert ids == {"phones": [], "accounts": [], "urls": [], "amounts": []}


def test_extract_identifiers_dedupes_repeats():
    transcript = [
        {"utterance": "account 1234567890"},
        {"utterance": "again account 1234567890"},
    ]
    assert len(extract_identifiers(transcript)["accounts"]) == 1


def test_extract_identifiers_records_utterance_index():
    transcript = [{"utterance": "hello"}, {"utterance": "pay to 1234567890"}]
    assert extract_identifiers(transcript)["accounts"][0]["utterance_idx"] == 1


@patch("src.enterprise.mo_extractor.get_supabase_client")
@patch("src.enterprise.mo_extractor.embed_text")
def test_store_mo_fingerprint(mock_embed, mock_client):
    mock_embed.return_value = [0.1] * 768
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    result = store_mo_fingerprint({"case_id": "case-1", "narrative": "test narrative"})
    assert result == "case-1"
    mock_table.upsert.assert_called_once()
    stored = mock_table.upsert.call_args[0][0]
    assert len(stored["embedding"]) == 768
    assert stored["narrative"] == "test narrative"


@patch("src.enterprise.mo_extractor.get_supabase_client")
@patch("src.enterprise.mo_extractor.embed_text")
def test_store_mo_fingerprint_embedding_failure_uses_zero_vector(mock_embed, mock_client):
    mock_embed.side_effect = RuntimeError("dashscope down")
    mock_table = MagicMock()
    mock_client.return_value.table.return_value = mock_table

    assert store_mo_fingerprint({"case_id": "c1", "narrative": "n"}) == "c1"
    assert mock_table.upsert.call_args[0][0]["embedding"] == [0.0] * 768


def test_store_mo_fingerprint_without_case_id_returns_none():
    assert store_mo_fingerprint({"narrative": "n"}) is None
