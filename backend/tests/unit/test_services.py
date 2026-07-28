"""Unit tests for external integration services (vision, stt, tts, tavily)."""

from unittest.mock import MagicMock, patch

import pytest

from src.services.stt import transcribe_audio_chunk
from src.services.tavily import TARGET_DOMAINS, tavily_search
from src.services.tts import synthesize_text_to_audio
from src.services.vision import extract_text_from_image


# -------------------------------------------------------------------
# Vision OCR Tests
# -------------------------------------------------------------------
@pytest.mark.asyncio
@patch("src.services.vision.groq_client")
async def test_extract_text_from_image_success(mock_groq: MagicMock) -> None:
    """Assert vision OCR extraction handles base64 image strings properly."""
    mock_choice = MagicMock()
    mock_choice.message.content = "URGENT: Verify account at http://scam.xyz"
    mock_groq.chat.completions.create.return_value.choices = [mock_choice]

    result = await extract_text_from_image("fake_base64_string")

    assert "URGENT: Verify account" in result
    mock_groq.chat.completions.create.assert_called_once()
    call_kwargs = mock_groq.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "llama-3.2-11b-vision-preview"
    message_content = call_kwargs["messages"][0]["content"]
    assert message_content[1]["image_url"]["url"] == "data:image/jpeg;base64,fake_base64_string"


@pytest.mark.asyncio
@patch("src.services.vision.groq_client")
async def test_extract_text_from_image_with_data_prefix(mock_groq: MagicMock) -> None:
    """Assert vision OCR preserves existing data prefix."""
    mock_choice = MagicMock()
    mock_choice.message.content = "Extracted OCR text"
    mock_groq.chat.completions.create.return_value.choices = [mock_choice]

    prefixed_base64 = "data:image/png;base64,abc123data"
    result = await extract_text_from_image(prefixed_base64)

    assert result == "Extracted OCR text"
    call_kwargs = mock_groq.chat.completions.create.call_args.kwargs
    message_content = call_kwargs["messages"][0]["content"]
    assert message_content[1]["image_url"]["url"] == prefixed_base64


@pytest.mark.asyncio
@patch("src.services.vision.groq_client")
async def test_extract_text_from_image_empty(mock_groq: MagicMock) -> None:
    """Assert empty base64 string returns empty string without API call."""
    result = await extract_text_from_image("")
    assert result == ""
    mock_groq.chat.completions.create.assert_not_called()


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
    assert call_kwargs["model"] == "whisper-large-v3"
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

    mock_tavily_cls.assert_called_once()
    mock_instance.search.assert_called_once_with(
        query="0161234567 scam",
        include_domains=TARGET_DOMAINS,
    )
    assert len(results) == 2
    assert any("lowyat.net" in r["url"] for r in results)
    assert any("bnm.gov.my" in r["url"] for r in results)
    assert not any("randomsite.com" in r["url"] for r in results)


@patch("src.services.tavily.TavilyClient")
def test_tavily_search_empty_entities(mock_tavily_cls: MagicMock) -> None:
    """Assert empty entities list returns empty list without calling TavilyClient."""
    results = tavily_search([])
    assert results == []
    mock_tavily_cls.assert_not_called()
