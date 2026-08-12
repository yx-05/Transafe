"""Unit tests for external integration services (vision, stt, tts, tavily)."""

from unittest.mock import MagicMock, patch

import pytest

from src.services.stt import transcribe_audio_chunk
from src.services.tavily import TARGET_DOMAINS, tavily_search
from src.services.tts import (
    get_elevenlabs_api_keys,
    synthesize_agent_speech,
    synthesize_text_to_audio,
    synthesize_text_to_audio_elevenlabs,
)
from src.services.vision import analyze_image, extract_text_from_image


# -------------------------------------------------------------------
# Vision OCR Tests
# -------------------------------------------------------------------
@patch("src.services.vision._get_groq_client")
def test_extract_text_from_image_success(mock_groq: MagicMock) -> None:
    """Assert vision OCR extraction handles base64 image strings properly."""
    mock_choice = MagicMock()
    mock_choice.message.content = "URGENT: Verify account at http://scam.xyz"
    client = mock_groq.return_value
    client.chat.completions.create.return_value.choices = [mock_choice]

    result = extract_text_from_image("fake_base64_string")

    assert "URGENT: Verify account" in result
    client.chat.completions.create.assert_called_once()
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "llama-3.2-11b-vision-preview"
    message_content = call_kwargs["messages"][0]["content"]
    assert message_content[1]["image_url"]["url"] == "data:image/jpeg;base64,fake_base64_string"


@patch("src.services.vision._get_groq_client")
def test_extract_text_from_image_with_data_prefix(mock_groq: MagicMock) -> None:
    """Assert vision OCR preserves existing data prefix."""
    mock_choice = MagicMock()
    mock_choice.message.content = "Extracted OCR text"
    client = mock_groq.return_value
    client.chat.completions.create.return_value.choices = [mock_choice]

    prefixed_base64 = "data:image/png;base64,abc123data"
    result = extract_text_from_image(prefixed_base64)

    assert result == "Extracted OCR text"
    call_kwargs = client.chat.completions.create.call_args.kwargs
    message_content = call_kwargs["messages"][0]["content"]
    assert message_content[1]["image_url"]["url"] == prefixed_base64


@patch("src.services.vision._get_groq_client")
def test_extract_text_from_image_empty(mock_groq: MagicMock) -> None:
    """Assert empty base64 string returns empty string without API call."""
    result = extract_text_from_image("")
    assert result == ""
    mock_groq.chat.completions.create.assert_not_called()


@patch("src.services.vision._get_groq_client")
def test_analyze_image_uses_qwen_model_and_json_output(mock_groq: MagicMock) -> None:
    """Assert qwen vision analysis is used for phishing image interpretation."""
    mock_choice = MagicMock()
    mock_choice.message.content = (
        '{"extracted_text": "URGENT: Verify now", "description": "Urgency banner and lookalike bank login form."}'
    )
    client = mock_groq.return_value
    client.chat.completions.create.return_value.choices = [mock_choice]

    result = analyze_image("fake_base64_string")

    assert result["extracted_text"] == "URGENT: Verify now"
    assert "lookalike bank login form" in result["description"]
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "qwen/qwen3.6-27b"
    message_content = call_kwargs["messages"][0]["content"]
    assert message_content[1]["image_url"]["url"] == "data:image/jpeg;base64,fake_base64_string"


# -------------------------------------------------------------------
# STT Tests
# -------------------------------------------------------------------
@pytest.mark.asyncio
@patch("src.services.stt.groq_client")
async def test_transcribe_audio_chunk_success(mock_groq: MagicMock) -> None:
    """Assert STT returns transcribed text string from audio bytes input."""
    mock_transcription = MagicMock()
    mock_transcription.text = "Hello, this is a scam alert test audio."
    mock_groq.audio.transcriptions.create.return_value = mock_transcription

    audio_data = b"fake_audio_bytes_12345"
    result = await transcribe_audio_chunk(audio_data, language="en")

    assert result == "Hello, this is a scam alert test audio."
    mock_groq.audio.transcriptions.create.assert_called_once()
    call_kwargs = mock_groq.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["model"] in ("whisper-large-v3-turbo", "whisper-large-v3")
    assert call_kwargs["language"] == "en"
    assert call_kwargs["file"][1] == audio_data


@pytest.mark.asyncio
@patch("src.services.stt.groq_client")
async def test_transcribe_audio_chunk_empty(mock_groq: MagicMock) -> None:
    """Assert empty audio bytes returns empty string without API call."""
    result = await transcribe_audio_chunk(b"")
    assert result == ""
    mock_groq.audio.transcriptions.create.assert_not_called()


# -------------------------------------------------------------------
# TTS Tests
# -------------------------------------------------------------------
@pytest.mark.asyncio
@patch("src.services.tts.edge_tts.Communicate")
async def test_synthesize_text_to_audio_luna(mock_communicate_cls: MagicMock) -> None:
    """Assert TTS synthesizes non-empty audio bytes with default voice."""
    async def mock_stream():
        yield {"type": "audio", "data": b"\x00\x01\x02\x03"}
        yield {"type": "WordBoundary", "data": "test"}
        yield {"type": "audio", "data": b"\x04\x05\x06"}

    mock_instance = MagicMock()
    mock_instance.stream.side_effect = mock_stream
    mock_communicate_cls.return_value = mock_instance

    text = "Warning: Suspected scam call."
    voice = "en-SG-LunaNeural"
    audio_bytes = await synthesize_text_to_audio(text, voice)

    assert audio_bytes == b"\x00\x01\x02\x03\x04\x05\x06"
    assert len(audio_bytes) > 0
    mock_communicate_cls.assert_called_once_with(text, voice)


@pytest.mark.asyncio
@patch("src.services.tts.edge_tts.Communicate")
async def test_synthesize_text_to_audio_yasmin(mock_communicate_cls: MagicMock) -> None:
    """Assert TTS synthesizes non-empty audio bytes with ms-MY-YasminNeural voice."""
    async def mock_stream():
        yield {"type": "audio", "data": b"yasmin_audio_data"}

    mock_instance = MagicMock()
    mock_instance.stream.side_effect = mock_stream
    mock_communicate_cls.return_value = mock_instance

    text = "Amaran: Panggilan penipuan dikesan."
    voice = "ms-MY-YasminNeural"
    audio_bytes = await synthesize_text_to_audio(text, voice)

    assert audio_bytes == b"yasmin_audio_data"
    mock_communicate_cls.assert_called_once_with(text, voice)


@pytest.mark.asyncio
@patch("src.services.tts.edge_tts.Communicate")
async def test_synthesize_text_to_audio_empty(mock_communicate_cls: MagicMock) -> None:
    """Assert empty input text returns empty bytes without calling Communicate."""
    audio_bytes = await synthesize_text_to_audio("")
    assert audio_bytes == b""
    mock_communicate_cls.assert_not_called()


# -------------------------------------------------------------------
# ElevenLabs TTS (primary) + edge-tts fallback tests
# -------------------------------------------------------------------
@patch.dict(
    "os.environ",
    {
        "ELEVENLAB_API_KEY": "sk_test_base",
        "ELEVENLAB_API_KEY_1": "sk_test_one",
        "ELEVENLAB_API_KEY_2": "sk_test_two",
        "ELEVENLAB_API_KEYS": "sk_comma_a, sk_comma_b",
    },
    clear=False,
)
@patch("src.services.tts.load_dotenv")
def test_get_elevenlabs_api_keys_pool(mock_load: MagicMock) -> None:
    """Assert the ElevenLabs key pool dedupes and filters all env sources."""
    keys = get_elevenlabs_api_keys()
    assert "sk_test_base" in keys
    assert "sk_test_one" in keys
    assert "sk_test_two" in keys
    assert "sk_comma_a" in keys
    assert "sk_comma_b" in keys
    assert len(keys) == len(set(keys))  # deduped


@patch.dict(
    "os.environ",
    {"ELEVENLAB_API_KEY": "sk_test_only"},
    clear=False,
)
@patch("src.services.tts.load_dotenv")
def test_get_elevenlabs_api_keys_filters_non_sk(mock_load: MagicMock) -> None:
    """Assert non-`sk_` prefixed values are filtered out of the pool."""
    keys = get_elevenlabs_api_keys()
    assert "sk_test_only" in keys
    assert not any(k and not k.startswith("sk_") for k in keys)


@patch.dict(
    "os.environ",
    {},
    clear=True,
)
@patch("src.services.tts.load_dotenv")
def test_get_elevenlabs_api_keys_empty_returns_empty(mock_load: MagicMock) -> None:
    """Assert an empty environment yields no ElevenLabs keys."""
    assert get_elevenlabs_api_keys() == []


@pytest.mark.asyncio
@patch("src.services.tts.synthesize_text_to_audio_elevenlabs")
@patch("src.services.tts.edge_tts.Communicate")
async def test_synthesize_agent_speech_uses_elevenlabs_first(
    mock_communicate_cls: MagicMock,
    mock_elevenlabs: MagicMock,
) -> None:
    """Assert agent speech prefers ElevenLabs and skips edge-tts on success."""
    mock_elevenlabs.return_value = b"elevenlabs_mp3_bytes"
    audio_bytes = await synthesize_agent_speech("Amaran: Panggilan penipuan dikesan.")

    assert audio_bytes == b"elevenlabs_mp3_bytes"
    mock_elevenlabs.assert_awaited_once_with("Amaran: Panggilan penipuan dikesan.")
    mock_communicate_cls.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.tts.synthesize_text_to_audio_elevenlabs")
@patch("src.services.tts.edge_tts.Communicate")
async def test_synthesize_agent_speech_falls_back_to_edge_tts(
    mock_communicate_cls: MagicMock,
    mock_elevenlabs: MagicMock,
) -> None:
    """Assert agent speech falls back to Microsoft edge-tts when ElevenLabs fails."""

    async def mock_stream():
        yield {"type": "audio", "data": b"fallback_audio"}
        yield {"type": "audio", "data": b"_bytes"}

    mock_elevenlabs.side_effect = RuntimeError("All keys out of credits")
    mock_instance = MagicMock()
    mock_instance.stream.side_effect = mock_stream
    mock_communicate_cls.return_value = mock_instance

    audio_bytes = await synthesize_agent_speech(
        "Amaran: Panggilan penipuan dikesan.", voice="ms-MY-YasminNeural"
    )

    assert audio_bytes == b"fallback_audio_bytes"
    mock_elevenlabs.assert_awaited_once()
    mock_communicate_cls.assert_called_once_with(
        "Amaran: Panggilan penipuan dikesan.", "ms-MY-YasminNeural"
    )


@pytest.mark.asyncio
@patch("src.services.tts.synthesize_text_to_audio_elevenlabs")
async def test_synthesize_agent_speech_empty_skips_elevenlabs(
    mock_elevenlabs: MagicMock,
) -> None:
    """Assert empty agent speech returns early without calling any provider."""
    audio_bytes = await synthesize_agent_speech("")
    assert audio_bytes == b""
    mock_elevenlabs.assert_not_called()


# -------------------------------------------------------------------
# ElevenLabs paid-voice-first / free-voice fallback tests
# -------------------------------------------------------------------
@pytest.mark.asyncio
@patch("src.services.tts.get_elevenlabs_api_keys", return_value=["sk_paid_key"])
@patch("src.services.tts.ELEVENLABS_VOICE_ID", "free-voice")
@patch("src.services.tts.ELEVENLABS_VOICE_ID_PAID", "paid-voice")
async def test_elevenlabs_paid_voice_tried_first_then_falls_back_free(
    mock_keys: MagicMock,
) -> None:
    """Paid voice is attempted first; free voice is used when the key can't access it."""
    with patch("elevenlabs.client.ElevenLabs") as mock_el:
        mock_client = mock_el.return_value
        convert = mock_client.text_to_speech.convert

        def fake_convert(**kwargs):
            if kwargs["voice_id"] == "paid-voice":
                raise Exception("HTTP 402: paid_plan_required")
            return iter([b"free_audio"])

        convert.side_effect = fake_convert

        audio = await synthesize_text_to_audio_elevenlabs("hello there")

    assert audio == b"free_audio"
    voices = [c.kwargs["voice_id"] for c in convert.call_args_list]
    assert voices == ["paid-voice", "free-voice"]


@pytest.mark.asyncio
@patch("src.services.tts.get_elevenlabs_api_keys", return_value=["sk_paid_key"])
@patch("src.services.tts.ELEVENLABS_VOICE_ID_PAID", "paid-voice")
async def test_elevenlabs_uses_paid_voice_when_accessible(
    mock_keys: MagicMock,
) -> None:
    """When the paid voice works, it is used and no fallback is attempted."""
    with patch("elevenlabs.client.ElevenLabs") as mock_el:
        convert = mock_el.return_value.text_to_speech.convert
        convert.return_value = iter([b"paid_audio"])

        audio = await synthesize_text_to_audio_elevenlabs("hello")

    assert audio == b"paid_audio"
    assert convert.call_count == 1
    assert convert.call_args.kwargs["voice_id"] == "paid-voice"


@pytest.mark.asyncio
@patch("src.services.tts.get_elevenlabs_api_keys", return_value=["sk_paid_key"])
async def test_elevenlabs_explicit_voice_id_skips_paid_fallback(
    mock_keys: MagicMock,
) -> None:
    """An explicit voice_id is honored directly (no paid/free candidate logic)."""
    with patch("elevenlabs.client.ElevenLabs") as mock_el:
        convert = mock_el.return_value.text_to_speech.convert
        convert.return_value = iter([b"custom_audio"])

        audio = await synthesize_text_to_audio_elevenlabs("hi", voice_id="custom-voice")

    assert audio == b"custom_audio"
    voices = [c.kwargs["voice_id"] for c in convert.call_args_list]
    assert voices == ["custom-voice"]


# -------------------------------------------------------------------
# Tavily Search Tests
# -------------------------------------------------------------------
@patch("src.services.tavily.TavilyClient")
def test_tavily_search_success(mock_tavily_cls: MagicMock) -> None:
    """Assert Tavily search formats query and returns filtered results list."""
    mock_instance = MagicMock()
    mock_instance.search.return_value = {
        "results": [
            {
                "title": "LowYat Scam Thread",
                "url": "https://forum.lowyat.net/topic/12345",
                "content": "Known scammer phone 0161234567",
            },
            {
                "title": "Unrelated Website",
                "url": "https://randomsite.com/article",
                "content": "Not in target domains",
            },
            {
                "title": "BNM Alert List",
                "url": "https://www.bnm.gov.my/consumer-alert",
                "content": "Financial scam alert",
            },
        ]
    }
    mock_tavily_cls.return_value = mock_instance

    entities = ["0161234567", "scam"]
    results = tavily_search(entities)

    assert mock_tavily_cls.called
    assert mock_instance.search.called
    assert len(results) >= 1
    assert any("lowyat.net" in r["url"] for r in results) or any("bnm.gov.my" in r["url"] for r in results)


@patch("src.services.tavily.TavilyClient")
def test_tavily_search_empty_entities(mock_tavily_cls: MagicMock) -> None:
    """Assert empty entities list returns empty list without calling TavilyClient."""
    results = tavily_search([])
    assert results == []
    mock_tavily_cls.assert_not_called()
