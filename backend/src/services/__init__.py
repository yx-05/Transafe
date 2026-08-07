"""External integration services for Vision, STT, TTS, and Search APIs."""

from src.services.stt import transcribe_audio_chunk
from src.services.tavily import tavily_search
from src.services.tts import (
    get_elevenlabs_api_keys,
    synthesize_agent_speech,
    synthesize_text_to_audio,
)
from src.services.vision import extract_text_from_image

__all__ = [
    "extract_text_from_image",
    "get_elevenlabs_api_keys",
    "synthesize_agent_speech",
    "synthesize_text_to_audio",
    "tavily_search",
    "transcribe_audio_chunk",
]
